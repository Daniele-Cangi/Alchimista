#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import secrets
from pathlib import Path


def build_environment(privacy_policy: str = "protect_egress") -> str:
    vault_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    values = {
        "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
        "ALCHIMISTA_API_TOKEN": secrets.token_urlsafe(48),
        "ADMIN_API_KEY": secrets.token_urlsafe(48),
        "PRIVACY_SERVICE_TOKEN": secrets.token_urlsafe(48),
        "PRIVACY_VAULT_ACTIVE_KEY_VERSION": "v1",
        "PRIVACY_VAULT_KEYS_JSON": json.dumps({"v1": vault_key}, separators=(",", ":")),
        # Legacy mirrors keep generated environments compatible with older images.
        "PRIVACY_VAULT_KEY": vault_key,
        "PRIVACY_VAULT_KEY_VERSION": "v1",
        "AUDIT_REPORT_SIGNING_KEY": secrets.token_urlsafe(48),
        "AUDIT_REPORT_SIGNING_KEY_ID": "local-v1",
        "LOCAL_AUTH_TENANTS": "*",
        "PRIVACY_POLICY": privacy_policy,
        "PRIVACY_MAPPING_ENABLED": "true",
        "PRIVACY_DETECTOR": "rizzo_regex",
    }
    return "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate local Alchimista secrets")
    parser.add_argument("--force", action="store_true", help="replace an existing .env")
    parser.add_argument(
        "--privacy-policy",
        choices=("off", "detect", "protect_egress", "strict"),
        default="protect_egress",
        help="privacy policy written to .env",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    destination = root / ".env"
    if destination.exists() and not args.force:
        parser.error(f"{destination} already exists; use --force to replace it")
    destination.write_text(build_environment(args.privacy_policy), encoding="utf-8", newline="\n")
    try:
        destination.chmod(0o600)
    except OSError:
        pass
    print(f"Generated {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
