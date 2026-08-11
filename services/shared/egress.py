from __future__ import annotations

from dataclasses import dataclass

from services.shared.privacy import (
    PrivacyClient,
    PrivacyPolicy,
    PrivacyPseudonymizeRequest,
    PrivacyServiceError,
)


class EgressBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedEgress:
    text: str
    pseudonymized: bool
    pii_count: int
    privacy_engine: str | None
    privacy_engine_version: str | None
    privacy_engine_source_revision: str | None


def prepare_external_text(
    *,
    text: str,
    tenant: str,
    doc_id: str,
    policy: PrivacyPolicy,
    privacy_client: PrivacyClient | None,
    reversible: bool = True,
) -> PreparedEgress:
    if policy in {PrivacyPolicy.OFF, PrivacyPolicy.DETECT}:
        return PreparedEgress(
            text=text,
            pseudonymized=False,
            pii_count=0,
            privacy_engine=None,
            privacy_engine_version=None,
            privacy_engine_source_revision=None,
        )
    if privacy_client is None:
        raise EgressBlocked("External egress blocked: privacy service is not configured")
    try:
        result = privacy_client.pseudonymize(
            PrivacyPseudonymizeRequest(
                text=text,
                tenant=tenant,
                doc_id=doc_id,
                reversible=reversible,
                persist_mapping=reversible,
            )
        )
    except PrivacyServiceError as exc:
        raise EgressBlocked("External egress blocked: privacy transformation failed") from exc
    return PreparedEgress(
        text=result.protected_text,
        pseudonymized=True,
        pii_count=result.pii_count,
        privacy_engine=result.engine.name,
        privacy_engine_version=result.engine.version,
        privacy_engine_source_revision=result.engine.source_revision,
    )
