from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import HTTPException, Request

from services.shared.config import RuntimeConfig


_OPENID_CACHE_TTL_SECONDS = 300
_openid_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}


@dataclass(frozen=True)
class AuthPrincipal:
    subject: str
    issuer: str
    audiences: tuple[str, ...]
    claims: dict[str, Any]


def require_auth(request: Request, *, config: RuntimeConfig, tenant: str | None = None) -> AuthPrincipal | None:
    if not config.auth_enabled:
        return None

    token = _extract_bearer_token(request)
    claims = _decode_claims(token, config)
    principal = AuthPrincipal(
        subject=str(claims.get("sub") or ""),
        issuer=str(claims.get("iss") or ""),
        audiences=_normalize_aud_claim(claims.get("aud")),
        claims=claims,
    )
    if not principal.subject:
        raise HTTPException(status_code=401, detail="Invalid token: missing sub")

    _authorize_tenant(principal, tenant=tenant, config=config)
    return principal


def _extract_bearer_token(request: Request) -> str:
    raw = request.headers.get("authorization", "")
    scheme, _, token = raw.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return token.strip()


def _decode_claims(token: str, config: RuntimeConfig) -> dict[str, Any]:
    try:
        header, claims, signing_input, signature = _decode_unverified(token)
        algorithm = str(header.get("alg") or "")
        allowed_algorithms = set(config.auth_algorithms or ("RS256",))
        if algorithm not in allowed_algorithms:
            raise HTTPException(status_code=401, detail=f"Invalid token: algorithm {algorithm} is not allowed")

        if algorithm.startswith("HS"):
            if not config.auth_jwt_shared_secret:
                raise HTTPException(status_code=503, detail="AUTH_JWT_SHARED_SECRET is required for HMAC tokens")
            _verify_hmac_signature(signing_input, signature, algorithm, config.auth_jwt_shared_secret)
        elif algorithm == "RS256":
            jwks_url = config.auth_jwks_url or _discover_jwks_url(config.auth_issuer or None)
            _verify_rs256_signature(signing_input, signature, header=header, jwks_url=jwks_url)
        else:
            raise HTTPException(status_code=401, detail=f"Invalid token: unsupported algorithm {algorithm}")

        _verify_registered_claims(claims, config)
        return claims
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc


def _discover_jwks_url(issuer: str | None) -> str:
    if not issuer:
        raise HTTPException(status_code=503, detail="AUTH_ISSUER or AUTH_JWKS_URL must be configured")

    normalized_issuer = issuer.rstrip("/")
    cached = _openid_cache.get(normalized_issuer)
    now = time.time()
    if cached and cached[0] > now:
        body = cached[1]
        jwks_url = str(body.get("jwks_uri") or "")
        if jwks_url:
            return jwks_url

    url = f"{normalized_issuer}/.well-known/openid-configuration"
    request = UrlRequest(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:
            payload = response.read().decode("utf-8")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OIDC discovery failed: {exc}") from exc

    try:
        body = json.loads(payload)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OIDC discovery invalid JSON: {exc}") from exc

    jwks_url = str(body.get("jwks_uri") or "")
    if not jwks_url:
        raise HTTPException(status_code=503, detail="OIDC discovery missing jwks_uri")

    _openid_cache[normalized_issuer] = (now + _OPENID_CACHE_TTL_SECONDS, body)
    return jwks_url


def _decode_unverified(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="Invalid token: malformed JWT")
    header_b64, payload_b64, signature_b64 = parts
    try:
        header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        signature = _b64url_decode(signature_b64)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: cannot decode JWT ({exc})") from exc
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise HTTPException(status_code=401, detail="Invalid token: invalid JWT sections")
    return header, payload, signing_input, signature


def _verify_hmac_signature(signing_input: bytes, signature: bytes, algorithm: str, secret: str) -> None:
    if algorithm != "HS256":
        raise HTTPException(status_code=401, detail=f"Invalid token: unsupported HMAC algorithm {algorithm}")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid token: bad signature")


def _verify_rs256_signature(signing_input: bytes, signature: bytes, *, header: dict[str, Any], jwks_url: str) -> None:
    jwk = _resolve_signing_jwk(jwks_url, header.get("kid"))
    n = str(jwk.get("n") or "")
    e = str(jwk.get("e") or "")
    if not n or not e:
        raise HTTPException(status_code=401, detail="Invalid token: jwk missing n/e")
    try:
        public_numbers = rsa.RSAPublicNumbers(
            e=int.from_bytes(_b64url_decode(e), "big", signed=False),
            n=int.from_bytes(_b64url_decode(n), "big", signed=False),
        )
        public_key = public_numbers.public_key()
        public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: bad signature ({exc})") from exc


def _resolve_signing_jwk(jwks_url: str, kid: Any) -> dict[str, Any]:
    now = time.time()
    cached = _jwks_cache.get(jwks_url)
    if cached and cached[0] > now:
        jwks = cached[1]
    else:
        jwks = _fetch_json(jwks_url)
        _jwks_cache[jwks_url] = (now + _OPENID_CACHE_TTL_SECONDS, jwks)

    keys = jwks.get("keys")
    if not isinstance(keys, list) or not keys:
        raise HTTPException(status_code=503, detail="OIDC JWKS is empty")

    if kid:
        for key in keys:
            if isinstance(key, dict) and key.get("kid") == kid:
                return key
        raise HTTPException(status_code=401, detail="Invalid token: key id not found")

    if len(keys) == 1 and isinstance(keys[0], dict):
        return keys[0]
    raise HTTPException(status_code=401, detail="Invalid token: missing kid")


def _verify_registered_claims(claims: dict[str, Any], config: RuntimeConfig) -> None:
    now = int(time.time())
    skew = 30

    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        raise HTTPException(status_code=401, detail="Invalid token: missing exp")
    if now > int(exp) + skew:
        raise HTTPException(status_code=401, detail="Invalid token: expired")

    nbf = claims.get("nbf")
    if isinstance(nbf, (int, float)) and now + skew < int(nbf):
        raise HTTPException(status_code=401, detail="Invalid token: not yet valid")

    iat = claims.get("iat")
    if isinstance(iat, (int, float)) and int(iat) > now + skew:
        raise HTTPException(status_code=401, detail="Invalid token: issued in future")

    if config.auth_issuer:
        issuer = str(claims.get("iss") or "")
        if issuer != config.auth_issuer:
            raise HTTPException(status_code=401, detail="Invalid token: issuer mismatch")

    if config.auth_audiences:
        audience_claim = _normalize_aud_claim(claims.get("aud"))
        if not audience_claim:
            raise HTTPException(status_code=401, detail="Invalid token: audience missing")
        if not set(audience_claim).intersection(set(config.auth_audiences)):
            raise HTTPException(status_code=401, detail="Invalid token: audience mismatch")


def _authorize_tenant(principal: AuthPrincipal, *, tenant: str | None, config: RuntimeConfig) -> None:
    if not tenant:
        return

    allowed_tenants = _extract_tenant_values(principal.claims, config.auth_tenant_claims)
    if not allowed_tenants:
        if config.auth_require_tenant_claim:
            raise HTTPException(status_code=403, detail="Forbidden: tenant claim missing")
        return

    if "*" in allowed_tenants:
        return
    if tenant not in allowed_tenants:
        raise HTTPException(status_code=403, detail="Forbidden: tenant mismatch")


def _extract_tenant_values(claims: dict[str, Any], claim_names: tuple[str, ...]) -> set[str]:
    values: set[str] = set()
    for claim_name in claim_names:
        raw = claims.get(claim_name)
        if raw is None:
            continue
        if isinstance(raw, str):
            value = raw.strip()
            if value:
                values.add(value)
            continue
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str):
                    value = item.strip()
                    if value:
                        values.add(value)
    return values


def _normalize_aud_claim(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        value = raw.strip()
        return (value,) if value else tuple()
    if isinstance(raw, list):
        out: list[str] = []
        for item in raw:
            if isinstance(item, str):
                value = item.strip()
                if value:
                    out.append(value)
        return tuple(out)
    return tuple()


def _b64url_decode(value: str) -> bytes:
    padding_len = (-len(value)) % 4
    padded = value + ("=" * padding_len)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _fetch_json(url: str) -> dict[str, Any]:
    request = UrlRequest(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:
            payload = response.read().decode("utf-8")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Unable to fetch OIDC metadata: {exc}") from exc

    try:
        body = json.loads(payload)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OIDC metadata invalid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=503, detail="OIDC metadata invalid shape")
    return body
