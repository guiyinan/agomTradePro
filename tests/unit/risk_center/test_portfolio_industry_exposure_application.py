"""Application tests for exact input resolution before portfolio-risk assessment."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.risk_center.application.portfolio_industry_exposure import (
    AssessPortfolioIndustryExposureUseCase,
    PortfolioIndustryExposureInputUnavailableError,
    PortfolioIndustryExposureQuery,
)
from apps.risk_center.domain.portfolio_exposure import (
    IndustryExposurePolicy,
    PortfolioExposureProjection,
)
from apps.risk_center.domain.portfolio_risk_sources import SourceObservationPrecision

AS_OF = datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)
BUSINESS_DATE = date(2026, 11, 3)


class _ProjectionReader:
    def __init__(self, projection: PortfolioExposureProjection | None) -> None:
        self.projection = projection

    def read_projection(
        self,
        *,
        account_id: int,
        portfolio_snapshot_id: str,
        as_of: datetime,
        business_date: date,
    ) -> PortfolioExposureProjection | None:
        del account_id, portfolio_snapshot_id, as_of, business_date
        return self.projection


class _PolicyReader:
    def __init__(self, policy: IndustryExposurePolicy | None) -> None:
        self.policy = policy

    def read_policy(
        self,
        *,
        account_id: int,
        as_of: datetime,
    ) -> IndustryExposurePolicy | None:
        del account_id, as_of
        return self.policy


def _policy() -> IndustryExposurePolicy:
    return IndustryExposurePolicy(
        policy_id="industry-risk",
        policy_version="2026-11-03.1",
        content_sha256="b" * 64,
        taxonomy_id="cn-industry-taxonomy",
        taxonomy_kind="industry",
        provider_id="official-sector-provider",
        provider_version="2026-10",
        effective_from=AS_OF - timedelta(days=30),
        effective_until=AS_OF + timedelta(days=30),
        known_at=AS_OF - timedelta(days=2),
        requested_purpose="portfolio_risk_daily",
        date_precision_purposes=("portfolio_risk_daily",),
        allowed_observation_precisions=(SourceObservationPrecision.DATE,),
        allowed_source_restrictions=(),
        coverage_precision_basis="official_nav_weight",
        max_industry_weight=Decimal("0.30"),
        max_security_weight=Decimal("0.20"),
        minimum_industry_coverage=Decimal("0"),
        minimum_etf_lookthrough_coverage=Decimal("0.70"),
        coverage_weight_tolerance=Decimal("0.001"),
    )


def _projection(
    *,
    snapshot_id: str = "snapshot-1",
    as_of: datetime = AS_OF,
    business_date: date = BUSINESS_DATE,
) -> PortfolioExposureProjection:
    return PortfolioExposureProjection(
        portfolio_snapshot_id=snapshot_id,
        as_of=as_of,
        business_date=business_date,
        portfolio_market_value=Decimal("1000"),
        assets=(),
    )


def _use_case(
    *,
    projection: PortfolioExposureProjection | None,
    policy: IndustryExposurePolicy | None,
) -> AssessPortfolioIndustryExposureUseCase:
    return AssessPortfolioIndustryExposureUseCase(
        projection_reader=_ProjectionReader(projection),
        policy_reader=_PolicyReader(policy),
    )


def _query() -> PortfolioIndustryExposureQuery:
    return PortfolioIndustryExposureQuery(
        account_id=12,
        portfolio_snapshot_id="snapshot-1",
        as_of=AS_OF,
        business_date=BUSINESS_DATE,
    )


def test_application_returns_assessment_for_the_exact_requested_projection() -> None:
    assessment = _use_case(
        projection=_projection(),
        policy=_policy(),
    ).execute(_query())

    assert assessment.portfolio_snapshot_id == "snapshot-1"
    assert assessment.policy_version == "2026-11-03.1"
    assert assessment.policy_content_sha256 == "b" * 64
    assert assessment.as_of == AS_OF


def test_application_blocks_when_no_policy_exists() -> None:
    use_case = _use_case(projection=_projection(), policy=None)

    with pytest.raises(PortfolioIndustryExposureInputUnavailableError) as error:
        use_case.execute(_query())

    assert error.value.reason_codes == ("INDUSTRY_RISK_POLICY_NOT_FOUND",)


def test_application_blocks_when_no_projection_exists() -> None:
    use_case = _use_case(projection=None, policy=_policy())

    with pytest.raises(PortfolioIndustryExposureInputUnavailableError) as error:
        use_case.execute(_query())

    assert error.value.reason_codes == ("PORTFOLIO_EXPOSURE_PROJECTION_NOT_FOUND",)


def test_application_blocks_when_projection_scope_differs_from_query() -> None:
    use_case = _use_case(
        projection=_projection(snapshot_id="newer-snapshot"),
        policy=_policy(),
    )

    with pytest.raises(PortfolioIndustryExposureInputUnavailableError) as error:
        use_case.execute(_query())

    assert error.value.reason_codes == ("PORTFOLIO_EXPOSURE_PROJECTION_SCOPE_MISMATCH",)
