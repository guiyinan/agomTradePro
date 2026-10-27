"""Public composition of the owner-scoped fee evidence policy use case."""

from apps.simulated_trading.application.fee_correction_policy import FeeCorrectionPolicyUseCase
from apps.simulated_trading.infrastructure.fee_correction_policy_repository import (
    DjangoFeeCorrectionPolicyRepository,
)


def build_fee_correction_policy_use_case() -> FeeCorrectionPolicyUseCase:
    """Build the policy port sharing the evidence and ledger's default database."""

    return FeeCorrectionPolicyUseCase(DjangoFeeCorrectionPolicyRepository())
