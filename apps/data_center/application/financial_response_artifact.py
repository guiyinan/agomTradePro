"""Application port for retaining an exact financial response body."""

from __future__ import annotations

from typing import Protocol

from apps.data_center.domain.financial_response_artifact import (
    FinancialResponseArtifact,
    FinancialResponseArtifactRef,
)


class FinancialResponseBodyStorePort(Protocol):
    """Store and retrieve immutable encrypted response artifacts."""

    def store(self, artifact: FinancialResponseArtifact) -> FinancialResponseArtifactRef:
        """Persist one exact response body and return its opaque reference."""
        ...

    def read(self, reference: FinancialResponseArtifactRef) -> bytes:
        """Read and independently verify the exact body for a reference."""
        ...

    def inspect(self, reference: FinancialResponseArtifactRef) -> FinancialResponseArtifactRef:
        """Validate an artifact envelope without returning its body."""
        ...


__all__ = ["FinancialResponseBodyStorePort"]
