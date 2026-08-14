"""Compatibility exports for the Research-owned composition root.

New callers should import the composition from ``apps.research``. The shim
keeps existing integrations stable without importing concrete infrastructure
from ``core.integration``.
"""

from apps.research.evidence_operator_spec_lifecycle_composition import (
    DjangoEvidenceOperatorSpecRuntime,
    build_django_evidence_operator_spec_runtime,
)

__all__ = [
    "DjangoEvidenceOperatorSpecRuntime",
    "build_django_evidence_operator_spec_runtime",
]
