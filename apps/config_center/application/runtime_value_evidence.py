"""Read typed runtime values with their stable active-profile provenance."""

from __future__ import annotations

from datetime import datetime

from apps.config_center.application import runtime_public
from core.integration.config_center_runtime import (
    ActiveRuntimeValueEvidence,
    read_active_runtime_value_evidence_from_port,
)


def read_active_runtime_value_evidence(
    *,
    environment: str,
    definition_key: str,
    as_of: datetime,
) -> ActiveRuntimeValueEvidence | None:
    """Read the same cutoff-qualified evidence through Config Center's public API."""

    return read_active_runtime_value_evidence_from_port(
        runtime_public,
        environment=environment,
        definition_key=definition_key,
        as_of=as_of,
    )


__all__ = ("ActiveRuntimeValueEvidence", "read_active_runtime_value_evidence")
