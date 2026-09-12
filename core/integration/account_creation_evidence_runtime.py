"""Core bridge for one fail-closed Account creation-evidence settings snapshot."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.account.application.creation_evidence_settings import (
    ACCOUNT_CREATION_EVIDENCE_SETTINGS_KEY,
    CanonicalAccountCreationEvidenceSettings,
    decode_canonical_account_creation_evidence_settings,
)
from core.integration import config_center_runtime


def get_active_account_creation_evidence_settings(
    environment: str,
) -> CanonicalAccountCreationEvidenceSettings | None:
    """Read and decode one complete active settings package, failing closed.

    Config Center is queried exactly once for the complete typed JSON value.
    Partial key reads and code-level compatibility defaults are deliberately
    excluded from this bridge.
    """

    if type(environment) is not str or not environment.strip():
        return None
    try:
        raw_value = config_center_runtime.get_active_runtime_value(
            environment=environment,
            definition_key=ACCOUNT_CREATION_EVIDENCE_SETTINGS_KEY,
        )
        if raw_value is None:
            return None
        settings = decode_canonical_account_creation_evidence_settings(raw_value)
        settings.deadline_at(datetime.now(UTC))
        return settings
    except (TypeError, ValueError, RuntimeError):
        return None
    except Exception:
        return None


__all__ = ["get_active_account_creation_evidence_settings"]
