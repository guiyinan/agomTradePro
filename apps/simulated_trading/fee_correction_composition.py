"""Public construction of existing fee evidence, posting and readback services."""

from apps.simulated_trading.application.fee_correction import ApplySimulatedFeeCorrectionUseCase
from apps.simulated_trading.application.fee_correction_evidence import (
    FeeCorrectionEvidenceUploadUseCase,
)
from apps.simulated_trading.application.fee_correction_head import FeeCorrectionHeadUseCase
from apps.simulated_trading.application.fee_correction_preview import FeeCorrectionPreviewUseCase
from apps.simulated_trading.infrastructure.fee_correction_head_repository import (
    DjangoFeeCorrectionHeadRepository,
)
from apps.simulated_trading.infrastructure.fee_correction_preview_repository import (
    DjangoFeeCorrectionPreviewRepository,
)
from apps.simulated_trading.infrastructure.fee_correction_runtime import (
    build_apply_simulated_fee_correction_use_case as _build_apply,
)
from apps.simulated_trading.infrastructure.fee_correction_runtime import (
    build_fee_correction_evidence_upload_use_case as _build_upload,
)


def build_fee_correction_evidence_upload_use_case() -> FeeCorrectionEvidenceUploadUseCase:
    """Use the original local evidence store and immutable owner-attested bindings."""

    return _build_upload()


def build_apply_simulated_fee_correction_use_case() -> ApplySimulatedFeeCorrectionUseCase:
    """Use the original account-locked atomic cash and cost correction implementation."""

    return _build_apply()


def build_fee_correction_head_use_case() -> FeeCorrectionHeadUseCase:
    """Build the owner-scoped reader of validated correction history."""

    return FeeCorrectionHeadUseCase(DjangoFeeCorrectionHeadRepository())


def build_fee_correction_preview_use_case() -> FeeCorrectionPreviewUseCase:
    """Build evidence-only preparation using the existing locked ledger and verifier."""

    return FeeCorrectionPreviewUseCase(DjangoFeeCorrectionPreviewRepository())
