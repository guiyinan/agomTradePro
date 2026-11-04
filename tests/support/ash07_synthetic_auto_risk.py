"""Install explicit synthetic portfolio-risk inputs for isolated auto-trading tests.

The returned service keeps the real owner-scoped assessment, database resource
repository, locked-order path, and execution evidence writer. Its policy and
source readers supply typed synthetic facts only; these are not market-source
acceptance or production configuration.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from django.db import DEFAULT_DB_ALIAS

import apps.simulated_trading.application.portfolio_risk_public as portfolio_risk_public
from apps.config_center.application.runtime_value_evidence import ActiveRuntimeValueEvidence
from apps.risk_center.application.portfolio_baseline_risk import (
    PortfolioBaselinePolicyReader,
)
from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetInputs,
    PortfolioRiskAssetsReader,
    PortfolioRiskAssetsReadRequest,
    PortfolioRiskAssetsReadResult,
)
from apps.risk_center.application.portfolio_risk_policy import (
    SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
    PortfolioRiskPolicyReader,
    PortfolioRiskPolicyReadResult,
    parse_portfolio_risk_policy_bundle,
)
from apps.risk_center.application.portfolio_risk_runtime import (
    PortfolioPressureApplicationFactory,
    PortfolioRiskRuntime,
)
from apps.risk_center.application.scenario_ports import (
    ScenarioRunEvidenceReadWriteRepositoryProtocol,
)
from apps.risk_center.infrastructure.portfolio_risk_execution_evidence_repository import (
    DjangoPortfolioRiskExecutionEvidenceWriter,
)
from apps.simulated_trading.application.portfolio_risk_calendar import (
    PortfolioRiskCalendarReader,
)
from apps.simulated_trading.application.portfolio_risk_context import (
    PortfolioRiskClock,
    PortfolioRiskPressureRunner,
)
from apps.simulated_trading.application.portfolio_risk_public import PortfolioRiskService
from apps.simulated_trading.application.portfolio_risk_service import (
    OwnerScopedPortfolioRiskService,
)
from apps.simulated_trading.composition import build_observer_grant_repository
from apps.simulated_trading.infrastructure.portfolio_risk_resource_repository import (
    DjangoPortfolioRiskResourceRepository,
)
from tests.unit.simulated_trading import test_portfolio_risk_service as synthetic_fixtures


class _SyntheticPolicyReader:
    """Parse explicit test policy values at each exact service cutoff."""

    def __init__(
        self,
        *,
        configuration: dict[str, object],
        account_id: int,
        owner_id: int,
    ) -> None:
        self._configuration = configuration
        self._account_id = account_id
        self._owner_id = owner_id

    def read_policy(
        self,
        *,
        as_of: datetime,
        business_date: date,
        account_id: int,
    ) -> PortfolioRiskPolicyReadResult:
        """Return typed synthetic policy evidence bound to the caller's exact clock."""

        if account_id != self._account_id:
            return PortfolioRiskPolicyReadResult(
                policy=None,
                reason_codes=("SIMULATED_PORTFOLIO_RISK_ACCOUNT_SCOPE_INVALID",),
            )
        created_at = as_of - timedelta(minutes=3)
        effective_at = as_of - timedelta(minutes=2)
        generated_at = as_of - timedelta(minutes=1)
        evidence = ActiveRuntimeValueEvidence(
            environment="test",
            definition_key=SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
            value=self._configuration,
            profile_id=f"synthetic-auto-risk-profile-{self._owner_id}-{account_id}",
            profile_key="synthetic-auto-risk-profile",
            profile_version=1,
            profile_content_hash="e" * 64,
            snapshot_id=f"synthetic-auto-risk-snapshot-{self._owner_id}-{account_id}",
            snapshot_hash="f" * 64,
            created_at=created_at,
            known_at=created_at,
            activated_at=effective_at,
            snapshot_generated_at=generated_at,
            effective_at=effective_at,
            as_of=as_of,
        )
        try:
            policy = parse_portfolio_risk_policy_bundle(
                evidence,
                business_date=business_date,
                as_of=as_of,
            )
        except ValueError:
            return PortfolioRiskPolicyReadResult(
                policy=None,
                reason_codes=("SIMULATED_PORTFOLIO_RISK_CONFIGURATION_INVALID",),
            )
        return PortfolioRiskPolicyReadResult(policy=policy, reason_codes=())


class _PricedSyntheticAssetsReader:
    """Use the established typed source fixture with one caller-supplied valuation."""

    def __init__(
        self,
        *,
        asset_code: str,
        security_id: str,
        valuation_price: Decimal,
    ) -> None:
        self._reader = synthetic_fixtures._AssetsReader()
        self._asset_code = asset_code
        self._security_id = security_id
        self._valuation_price = valuation_price

    def read_assets(self, request: PortfolioRiskAssetsReadRequest) -> PortfolioRiskAssetsReadResult:
        """Return the unit fixture's real Domain inputs with an exact synthetic price."""

        result = self._reader.read_assets(request)
        priced_assets: list[PortfolioRiskAssetInputs] = []
        for asset in result.assets:
            if (asset.asset_code, asset.security_id) != (
                self._asset_code,
                self._security_id,
            ):
                raise AssertionError("synthetic auto-risk reader received an unexpected asset")
            priced_assets.append(replace(asset, price=self._valuation_price))
        return replace(result, assets=tuple(priced_assets))


class _FixedRiskClock:
    """Return the explicitly selected synthetic decision cutoff."""

    def __init__(self, as_of: datetime) -> None:
        self._as_of = as_of

    def now(self) -> datetime:
        """Return the test cutoff without consulting or fabricating source clocks."""

        return self._as_of


def install_synthetic_auto_risk_service(
    *,
    monkeypatch: pytest.MonkeyPatch,
    account_id: int,
    owner_id: int,
    asset_code: str,
    security_id: str,
    valuation_price: Decimal,
    as_of: datetime,
    business_date: date,
    execution_session: date,
) -> OwnerScopedPortfolioRiskService:
    """Install a real owner-scoped Risk service with isolated synthetic test facts.

    The service continues to use the real account-resource repository and Risk
    execution-audit writer. Its typed policy, source, baseline, and calendar
    readers are synthetic test fixtures. ``valuation_price`` is an explicit
    source-side mark (the auto-trading quote/limit price is a separate input).
    """

    if type(account_id) is not int or account_id < 1:
        raise ValueError("account_id must be a positive exact integer")
    if type(owner_id) is not int or owner_id < 1:
        raise ValueError("owner_id must be a positive exact integer")
    for name, value in (("asset_code", asset_code), ("security_id", security_id)):
        if (
            type(value) is not str
            or not value
            or value.strip() != value
            or any(character.isspace() for character in value)
        ):
            raise ValueError(f"{name} must be a nonempty exact identifier")
    if (
        type(valuation_price) is not Decimal
        or not valuation_price.is_finite()
        or valuation_price <= 0
    ):
        raise ValueError("valuation_price must be an exact positive Decimal")
    if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be an aware datetime")
    if type(business_date) is not date or type(execution_session) is not date:
        raise TypeError("business_date and execution_session must be exact dates")
    if execution_session != business_date:
        raise ValueError("synthetic auto-risk execution session must equal its business date")
    if as_of.astimezone(ZoneInfo("Asia/Shanghai")).date() != business_date:
        raise ValueError("business_date must match the Asia/Shanghai decision date")

    for name, value in (
        ("_AS_OF", as_of),
        ("_BUSINESS_DATE", business_date),
        ("_SESSION", execution_session),
        ("_ACCOUNT_ID", account_id),
        ("_OWNER_ID", owner_id),
        ("_ASSET_CODE", asset_code),
        ("_SECURITY_ID", security_id),
    ):
        monkeypatch.setattr(synthetic_fixtures, name, value)

    configuration = synthetic_fixtures._configuration()
    industry = cast(dict[str, object], configuration["industry"])
    industry["max_industry_weight"] = "1"
    industry["max_security_weight"] = "1"
    industry["minimum_industry_coverage"] = "1"
    industry["minimum_etf_lookthrough_coverage"] = "1"
    industry["coverage_weight_tolerance"] = "0"
    capacity = cast(dict[str, object], configuration["capacity"])
    capacity["max_participation"] = "1"

    baseline = replace(
        synthetic_fixtures._baseline_policy(),
        max_total_weight=Decimal("1"),
        max_single_weight=Decimal("1"),
        min_cash_weight=Decimal("0"),
    )
    runtime = PortfolioRiskRuntime(
        policy_reader=cast(
            PortfolioRiskPolicyReader,
            _SyntheticPolicyReader(
                configuration=configuration,
                account_id=account_id,
                owner_id=owner_id,
            ),
        ),
        assets_reader=cast(
            PortfolioRiskAssetsReader,
            _PricedSyntheticAssetsReader(
                asset_code=asset_code,
                security_id=security_id,
                valuation_price=valuation_price,
            ),
        ),
        baseline_reader=cast(
            PortfolioBaselinePolicyReader,
            synthetic_fixtures._BaselineReader(baseline),
        ),
        execution_evidence_writer=DjangoPortfolioRiskExecutionEvidenceWriter(
            using=DEFAULT_DB_ALIAS
        ),
        pressure_factory=cast(
            PortfolioPressureApplicationFactory,
            synthetic_fixtures._UnusedPressureFactory(),
        ),
        pressure_evidence_repository=cast(
            ScenarioRunEvidenceReadWriteRepositoryProtocol,
            object(),
        ),
    )
    calendar_reader = cast(
        PortfolioRiskCalendarReader,
        synthetic_fixtures._CalendarReader(),
    )
    clock: PortfolioRiskClock = _FixedRiskClock(as_of)
    pressure_runner = cast(
        PortfolioRiskPressureRunner,
        synthetic_fixtures._UnusedPressureRunner(),
    )

    def build_service(using: str) -> PortfolioRiskService:
        """Keep the ledger resource read and audit writer on the exact test database."""

        if using != DEFAULT_DB_ALIAS:
            raise AssertionError("synthetic auto-risk service accepts only the isolated default")
        resources = DjangoPortfolioRiskResourceRepository(
            using=using,
            observer_grant_repository=build_observer_grant_repository(using=using),
        )
        return OwnerScopedPortfolioRiskService(
            resources=resources,
            runtime=runtime,
            clock=clock,
            business_timezone=ZoneInfo("Asia/Shanghai"),
            code_version="synthetic-ash07-auto-t1-risk",
            using=using,
            pressure_runner=pressure_runner,
            calendar_reader=calendar_reader,
        )

    monkeypatch.setattr(portfolio_risk_public, "_service_factory", build_service)
    return build_service(DEFAULT_DB_ALIAS)
