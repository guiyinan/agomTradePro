"""Risk source admission composition with the public Data Center write facade."""

from __future__ import annotations

from apps.risk_center.application.portfolio_risk_source_admission import (
    PortfolioRiskSourceAdmissionUseCase,
)
from apps.risk_center.infrastructure.data_center_raw_payload_writer import (
    DataCenterRawPayloadWriter,
)
from apps.risk_center.infrastructure.portfolio_risk_source_admission_codec import (
    RetainedPortfolioRiskAdmissionManifestCodec,
)


def build_portfolio_risk_source_admission_use_case() -> PortfolioRiskSourceAdmissionUseCase:
    """Build admission without a new repository, table, or network dependency."""

    return PortfolioRiskSourceAdmissionUseCase(
        manifest_factory=RetainedPortfolioRiskAdmissionManifestCodec(),
        writer=DataCenterRawPayloadWriter(),
    )


__all__ = ("build_portfolio_risk_source_admission_use_case",)
