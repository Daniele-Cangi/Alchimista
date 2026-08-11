import pytest

from services.shared.egress import EgressBlocked, prepare_external_text
from services.shared.privacy import (
    PrivacyEngineMetadata,
    PrivacyPolicy,
    PrivacyPseudonymizeResponse,
    PrivacyServiceError,
)


class _SuccessfulPrivacyClient:
    def pseudonymize(self, request):
        return PrivacyPseudonymizeResponse(
            protected_text="Contact [EMAIL_1]",
            findings=[],
            pii_count=1,
            pii_types=["EMAIL"],
            engine=PrivacyEngineMetadata(
                name="rizzo-pii",
                version="test",
                source_revision="abc",
                mode="regex_checksum",
            ),
            reversible=True,
            mapping_stored=True,
        )


class _FailingPrivacyClient:
    def pseudonymize(self, request):
        raise PrivacyServiceError("unavailable")


def test_external_egress_is_pseudonymized_for_protect_egress() -> None:
    prepared = prepare_external_text(
        text="Contact alice@example.com",
        tenant="default",
        doc_id="doc-1",
        policy=PrivacyPolicy.PROTECT_EGRESS,
        privacy_client=_SuccessfulPrivacyClient(),
    )
    assert prepared.pseudonymized is True
    assert "alice@example.com" not in prepared.text
    assert prepared.privacy_engine == "rizzo-pii"


def test_external_egress_fails_closed_when_privacy_transform_fails() -> None:
    with pytest.raises(EgressBlocked, match="blocked"):
        prepare_external_text(
            text="Contact alice@example.com",
            tenant="default",
            doc_id="doc-1",
            policy=PrivacyPolicy.STRICT,
            privacy_client=_FailingPrivacyClient(),
        )


def test_external_egress_fails_closed_without_privacy_client() -> None:
    with pytest.raises(EgressBlocked, match="not configured"):
        prepare_external_text(
            text="Contact alice@example.com",
            tenant="default",
            doc_id="doc-1",
            policy=PrivacyPolicy.PROTECT_EGRESS,
            privacy_client=None,
        )
