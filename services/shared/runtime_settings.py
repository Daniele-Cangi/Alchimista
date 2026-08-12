from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any

from services.shared.db import get_connection


VALID_PRIVACY_POLICIES = frozenset({"off", "detect", "protect_egress", "strict"})
VALID_PRIVACY_DETECTORS = frozenset({"rizzo_regex", "rizzo_http"})


@dataclass(frozen=True)
class PrivacyRuntimeSettings:
    workspace: str
    privacy_policy: str
    privacy_detector: str
    privacy_mapping_enabled: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeSettingsStore:
    """PostgreSQL-backed workspace settings with environment bootstrap defaults."""

    def __init__(
        self,
        database_url: str,
        *,
        default_policy: str,
        default_detector: str,
        default_mapping_enabled: bool,
    ) -> None:
        self.database_url = database_url
        self.defaults = _validated_settings(
            workspace="default",
            privacy_policy=default_policy,
            privacy_detector=default_detector,
            privacy_mapping_enabled=default_mapping_enabled,
        )

    def get(self, workspace: str) -> PrivacyRuntimeSettings:
        normalized = _normalize_workspace(workspace)
        with get_connection(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT workspace, privacy_policy, privacy_detector, privacy_mapping_enabled
                    FROM runtime_settings
                    WHERE workspace = %s
                    """,
                    (normalized,),
                )
                row = cur.fetchone()
                if row is None:
                    cur.execute(
                        """
                        INSERT INTO runtime_settings (
                          workspace, privacy_policy, privacy_detector, privacy_mapping_enabled
                        ) VALUES (%s, %s, %s, %s)
                        ON CONFLICT (workspace) DO NOTHING
                        RETURNING workspace, privacy_policy, privacy_detector, privacy_mapping_enabled
                        """,
                        (
                            normalized,
                            self.defaults.privacy_policy,
                            self.defaults.privacy_detector,
                            self.defaults.privacy_mapping_enabled,
                        ),
                    )
                    row = cur.fetchone()
                    if row is None:
                        cur.execute(
                            """
                            SELECT workspace, privacy_policy, privacy_detector, privacy_mapping_enabled
                            FROM runtime_settings WHERE workspace = %s
                            """,
                            (normalized,),
                        )
                        row = cur.fetchone()
                    conn.commit()
        if row is None:  # pragma: no cover - database invariant
            raise RuntimeError("Unable to load runtime settings")
        return _from_row(row)

    @contextmanager
    def processing_snapshot(self, workspace: str) -> Iterator[PrivacyRuntimeSettings]:
        """Hold a shared row lock so one operation sees one settings snapshot."""
        normalized = _normalize_workspace(workspace)
        # Bootstrap in its own committed transaction. Otherwise privacy-service
        # could wait on this operation's still-uncommitted unique row insert.
        self.get(normalized)
        with get_connection(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT workspace, privacy_policy, privacy_detector, privacy_mapping_enabled
                    FROM runtime_settings
                    WHERE workspace = %s
                    FOR SHARE
                    """,
                    (normalized,),
                )
                row = cur.fetchone()
            if row is None:  # pragma: no cover - database invariant
                conn.rollback()
                raise RuntimeError("Unable to load runtime settings snapshot")
            try:
                yield _from_row(row)
            except BaseException:
                conn.rollback()
                raise
            else:
                conn.commit()

    def update(
        self,
        *,
        workspace: str,
        privacy_policy: str,
        privacy_detector: str,
        privacy_mapping_enabled: bool,
        changed_by: str = "local-dashboard",
    ) -> PrivacyRuntimeSettings:
        settings = _validated_settings(
            workspace=workspace,
            privacy_policy=privacy_policy,
            privacy_detector=privacy_detector,
            privacy_mapping_enabled=privacy_mapping_enabled,
        )
        actor = changed_by.strip() or "local-dashboard"
        with get_connection(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO runtime_settings (
                      workspace, privacy_policy, privacy_detector, privacy_mapping_enabled, updated_at
                    ) VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (workspace) DO UPDATE SET
                      privacy_policy = EXCLUDED.privacy_policy,
                      privacy_detector = EXCLUDED.privacy_detector,
                      privacy_mapping_enabled = EXCLUDED.privacy_mapping_enabled,
                      updated_at = NOW()
                    """,
                    (
                        settings.workspace,
                        settings.privacy_policy,
                        settings.privacy_detector,
                        settings.privacy_mapping_enabled,
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO runtime_settings_history (
                      workspace, privacy_policy, privacy_detector,
                      privacy_mapping_enabled, changed_by
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        settings.workspace,
                        settings.privacy_policy,
                        settings.privacy_detector,
                        settings.privacy_mapping_enabled,
                        actor,
                    ),
                )
                conn.commit()
        return settings

    def workspaces_using_detector(self, detector: str) -> list[str]:
        normalized = detector.strip().lower()
        if normalized not in VALID_PRIVACY_DETECTORS:
            raise ValueError("privacy_detector must be rizzo_regex or rizzo_http")
        with get_connection(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT workspace FROM runtime_settings WHERE privacy_detector = %s ORDER BY workspace",
                    (normalized,),
                )
                rows = cur.fetchall()
        return [str(row["workspace"]) for row in rows]


def _normalize_workspace(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("workspace must not be empty")
    if len(normalized) > 128:
        raise ValueError("workspace must contain at most 128 characters")
    return normalized


def _validated_settings(
    *,
    workspace: str,
    privacy_policy: str,
    privacy_detector: str,
    privacy_mapping_enabled: bool,
) -> PrivacyRuntimeSettings:
    normalized_policy = privacy_policy.strip().lower()
    normalized_detector = privacy_detector.strip().lower()
    if normalized_policy not in VALID_PRIVACY_POLICIES:
        raise ValueError("privacy_policy must be off, detect, protect_egress, or strict")
    if normalized_detector not in VALID_PRIVACY_DETECTORS:
        raise ValueError("privacy_detector must be rizzo_regex or rizzo_http")
    return PrivacyRuntimeSettings(
        workspace=_normalize_workspace(workspace),
        privacy_policy=normalized_policy,
        privacy_detector=normalized_detector,
        privacy_mapping_enabled=bool(privacy_mapping_enabled),
    )


def _from_row(row: dict[str, Any]) -> PrivacyRuntimeSettings:
    return _validated_settings(
        workspace=str(row["workspace"]),
        privacy_policy=str(row["privacy_policy"]),
        privacy_detector=str(row["privacy_detector"]),
        privacy_mapping_enabled=bool(row["privacy_mapping_enabled"]),
    )
