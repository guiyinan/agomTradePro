"""Composition root for correction evidence capture, writes, and history reads."""

from __future__ import annotations

from datetime import datetime

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from apps.simulated_trading.application.fee_correction import (
    ApplySimulatedFeeCorrectionUseCase,
    FeeCorrectionBlockedError,
)
from apps.simulated_trading.application.fee_correction_evidence import (
    FeeCorrectionEvidenceUploadUseCase,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_repository import (
    DjangoFeeCorrectionEvidenceRepository,
)
from apps.simulated_trading.infrastructure.fee_correction_persisted_event_proofs import (
    DjangoPersistedFeeCorrectionSourceProof,
    PersistedFeeCorrectionAuthorityProof,
)
from apps.simulated_trading.infrastructure.fee_correction_repository import (
    DjangoFeeCorrectionRepository,
)


class DjangoFeeCorrectionClock:
    """Use Django's aware server clock for correction posting time."""

    def now(self) -> datetime:
        """Return the current aware posting timestamp."""

        return timezone.now()


def build_django_fee_correction_repository(
    *,
    using: str = DEFAULT_DB_ALIAS,
    evidence_repository: DjangoFeeCorrectionEvidenceRepository | None = None,
) -> DjangoFeeCorrectionRepository:
    """Assemble the real local source, authorization, fingerprint, and history ports."""

    if using != DEFAULT_DB_ALIAS:
        raise FeeCorrectionBlockedError(
            "费用更正证据与账本当前必须使用同一个默认数据库",
            code="FEE_CORRECTION_DATABASE_UNSUPPORTED",
        )
    evidence = evidence_repository or DjangoFeeCorrectionEvidenceRepository()
    return DjangoFeeCorrectionRepository(
        evidence_verifier=evidence,
        authority=evidence,
        fingerprint=evidence,
        persisted_source_proof=DjangoPersistedFeeCorrectionSourceProof(evidence),
        persisted_authority=PersistedFeeCorrectionAuthorityProof(),
        using=using,
    )


def build_apply_simulated_fee_correction_use_case(
    *,
    using: str = DEFAULT_DB_ALIAS,
) -> ApplySimulatedFeeCorrectionUseCase:
    """Build the source-qualified atomic correction application service."""

    evidence = DjangoFeeCorrectionEvidenceRepository()
    return ApplySimulatedFeeCorrectionUseCase(
        repository=build_django_fee_correction_repository(
            using=using,
            evidence_repository=evidence,
        ),
        evidence_verifier=evidence,
        authority=evidence,
        clock=DjangoFeeCorrectionClock(),
    )


def build_fee_correction_evidence_upload_use_case() -> FeeCorrectionEvidenceUploadUseCase:
    """Build the owner-attested local artifact capture service."""

    return FeeCorrectionEvidenceUploadUseCase(DjangoFeeCorrectionEvidenceRepository())


__all__ = [
    "DjangoFeeCorrectionClock",
    "build_apply_simulated_fee_correction_use_case",
    "build_django_fee_correction_repository",
    "build_fee_correction_evidence_upload_use_case",
]
