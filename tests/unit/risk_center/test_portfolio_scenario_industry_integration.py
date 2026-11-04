"""Test-only multi-holding factor shocks through the ordinary Scenario flow.

Every policy, source fact, market-data envelope, and approved Scenario revision in
this module is synthetic.  It demonstrates application wiring and replay, not
qualification of a public provider or a real-market forecast.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

from apps.config_center.application.runtime_value_evidence import ActiveRuntimeValueEvidence
from apps.risk_center.application.portfolio_baseline_risk import (
    PortfolioBaselinePolicyReader,
    PortfolioBaselinePolicyReadResult,
)
from apps.risk_center.application.portfolio_exit_pressure_ports import (
    PortfolioPressureProjectionProviderProtocol,
    ScenarioPressureClockProtocol,
)
from apps.risk_center.application.portfolio_exit_pressure_use_cases import (
    RunPortfolioExitPressureUseCase,
    portfolio_pressure_run_id,
)
from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetInputs,
    PortfolioRiskAssetsReader,
    PortfolioRiskAssetsReadResult,
)
from apps.risk_center.application.portfolio_risk_execution_evidence import (
    PortfolioRiskExecutionEvidenceWriter,
)
from apps.risk_center.application.portfolio_risk_policy import (
    SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
    PortfolioRiskPolicyBundle,
    PortfolioRiskPolicyReader,
    parse_portfolio_risk_policy_bundle,
)
from apps.risk_center.application.portfolio_risk_runtime import (
    PortfolioPressureApplicationFactory,
    PortfolioRiskRuntime,
)
from apps.risk_center.application.portfolio_risk_serialization import (
    canonical_portfolio_risk_json,
)
from apps.risk_center.application.portfolio_risk_snapshot import (
    AccountSnapshot,
    ExecutedUsage,
    HeldPosition,
    PortfolioRiskAssessmentResult,
    assess_simulated_portfolio_risk,
)
from apps.risk_center.application.scenario_dtos import (
    ScenarioMarketDataDTO,
    ScenarioSummaryDTO,
)
from apps.risk_center.application.scenario_ports import (
    PortfolioSnapshotProviderProtocol,
    ScenarioMarketDataProviderProtocol,
    ScenarioQueryRepositoryProtocol,
    ScenarioRunEvidenceReadWriteRepositoryProtocol,
)
from apps.risk_center.application.scenario_use_cases import PreviewScenarioImpactUseCase
from apps.risk_center.domain.portfolio_capacity import CapacityValue, CapacityWindowObservation
from apps.risk_center.domain.portfolio_exposure_types import (
    EffectiveEndState,
    ETFConstituent,
    ETFConstituentKind,
    ETFConstituentReport,
    IndustryMembership,
    PortfolioAssetKind,
)
from apps.risk_center.domain.portfolio_risk_identity import PortfolioRiskIdentityBinding
from apps.risk_center.domain.portfolio_risk_native_limits import (
    PortfolioRiskNativeAccountLimits,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)
from apps.risk_center.domain.scenarios import (
    ParametricShock,
    ParametricShockParameters,
    ScenarioDefinition,
    ScenarioDefinitionStatus,
    ScenarioRevision,
    ScenarioRevisionStatus,
    ScenarioRunEvidence,
    ScenarioSetRevision,
    ScenarioSourceType,
    ScenarioType,
    ShockUnit,
    scenario_run_snapshot_hash,
)
from apps.simulated_trading.application.portfolio_risk_calendar import (
    PortfolioRiskCalendarReadResult,
)
from apps.simulated_trading.application.portfolio_risk_context import (
    PortfolioRiskClock,
    PreparedPortfolioRisk,
)
from apps.simulated_trading.application.portfolio_risk_pressure_runner import (
    PortfolioRiskPressureRunnerService,
)
from apps.simulated_trading.application.portfolio_risk_resource_ports import (
    AccountSnapshotReadResult,
    PortfolioRiskAccountScope,
)

AS_OF = datetime(2026, 11, 3, 2, 0, tzinfo=UTC)
BUSINESS_DATE = date(2026, 11, 3)
EXECUTION_SESSION = BUSINESS_DATE
ACCOUNT_ID = 9410
OWNER_ID = 77
INDUSTRY_PURPOSE = "synthetic_scenario_industry"
CAPACITY_PURPOSE = "synthetic_scenario_capacity"
FINANCE_FACTOR = "fixture_financials"
OTHER_FACTOR = "fixture_technology"
ETF_CODE = "510050.SH"
ETF_SECURITY = "SSE:510050"
BANK_A_CODE = "600036.SH"
BANK_A_SECURITY = "SSE:600036"
BANK_B_CODE = "601398.SH"
BANK_B_SECURITY = "SSE:601398"
OTHER_CODE = "600519.SH"
OTHER_SECURITY = "SSE:600519"
SNAPSHOT_ID = f"simulated-account:{ACCOUNT_ID}:" + "a" * 64


def _source_reference(
    *, kind: str, asset_code: str, security_id: str, source_record_id: str
) -> dict[str, str]:
    """Return an exact test-only manifest pin with a distinct manifest hash."""

    digest = hashlib.sha256(
        f"fixture-manifest:{kind}:{asset_code}:{security_id}:{source_record_id}".encode()
    ).hexdigest()
    return {
        "kind": kind,
        "asset_code": asset_code,
        "security_id": security_id,
        "raw_payload_hash": f"sha256:{digest}",
        "source_record_id": source_record_id,
    }


def _all_source_references() -> list[dict[str, str]]:
    """Bind every held asset and every named ETF constituent by exact identity."""

    references: list[dict[str, str]] = []
    holdings = (
        (
            BANK_A_CODE,
            BANK_A_SECURITY,
            ("valuation", "capacity_window", "execution_session_state", "industry_membership"),
        ),
        (
            BANK_B_CODE,
            BANK_B_SECURITY,
            ("valuation", "capacity_window", "execution_session_state", "industry_membership"),
        ),
        (
            ETF_CODE,
            ETF_SECURITY,
            ("valuation", "capacity_window", "execution_session_state", "etf_report"),
        ),
    )
    for asset_code, security_id, kinds in holdings:
        for kind in kinds:
            references.append(
                _source_reference(
                    kind=kind,
                    asset_code=asset_code,
                    security_id=security_id,
                    source_record_id=f"fixture:{kind}:{asset_code}",
                )
            )
    references.append(
        _source_reference(
            kind="industry_membership",
            asset_code=OTHER_CODE,
            security_id=OTHER_SECURITY,
            source_record_id=f"fixture:industry_membership:{OTHER_CODE}",
        )
    )
    return references


def _policy_configuration() -> dict[str, object]:
    """Return explicit, isolated policy values for this hypothetical Scenario test."""

    return {
        "schema_version": "ash07.simulated_portfolio_risk.v1",
        "scope": "simulation_only",
        "ledger_money_unit": "CNY",
        "account_ids": [ACCOUNT_ID],
        "industry": {
            "taxonomy_id": "fixture-industry-taxonomy",
            "taxonomy_kind": "industry",
            "provider_id": "fixture-membership-provider",
            "provider_version": "fixture-source-binding",
            "requested_purpose": INDUSTRY_PURPOSE,
            "date_precision_purposes": [],
            "allowed_observation_precisions": ["timestamp"],
            "allowed_source_restrictions": [],
            "coverage_precision_basis": "portfolio_weight",
            "max_industry_weight": "0.80",
            "max_security_weight": "0.80",
            "minimum_industry_coverage": "0.90",
            "minimum_etf_lookthrough_coverage": "0.80",
            "coverage_weight_tolerance": "0.01",
        },
        "capacity": {
            "measure": "volume",
            "unit": "share",
            "basis": "average_per_session",
            "usage_scope": "account_security_session",
            "date_basis": "execution_session",
            "max_participation": "0.80",
            "increment": "1",
            "window_kind": "rolling_sessions",
            "sessions": 2,
            "allowed_observation_precisions": ["timestamp"],
            "date_precision_purposes": [],
            "allowed_source_restrictions": [],
        },
        "source_max_timestamp_age_seconds": 3600,
        "source_max_date_age_days": 0,
        "source_references": _all_source_references(),
    }


def _policy() -> PortfolioRiskPolicyBundle:
    """Parse the isolated runtime value through the public policy contract."""

    created_at = AS_OF - timedelta(minutes=3)
    effective_at = AS_OF - timedelta(minutes=2)
    generated_at = AS_OF - timedelta(minutes=1)
    evidence = ActiveRuntimeValueEvidence(
        environment="test",
        definition_key=SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
        value=_policy_configuration(),
        profile_id="fixture-risk-profile",
        profile_key="test",
        profile_version=1,
        profile_content_hash="e" * 64,
        snapshot_id="fixture-risk-snapshot",
        snapshot_hash="f" * 64,
        created_at=created_at,
        # Runtime profile evidence exposes creation, not a separate known clock.
        known_at=created_at,
        activated_at=effective_at,
        snapshot_generated_at=generated_at,
        effective_at=effective_at,
        as_of=AS_OF,
    )
    return parse_portfolio_risk_policy_bundle(
        evidence,
        business_date=BUSINESS_DATE,
        as_of=AS_OF,
    )


def _coverage(
    *,
    status: CoverageStatus = CoverageStatus.COMPLETE,
    fraction: Decimal = Decimal("1"),
    expected: int | None = None,
    observed: int | None = None,
) -> PortfolioRiskCoverage:
    """Create explicit test coverage, retaining the ETF's unreported remainder."""

    return PortfolioRiskCoverage(
        status=status,
        precision_basis="portfolio_weight",
        reported_weight_fraction=fraction,
        expected_item_count=expected,
        observed_item_count=observed,
    )


def _evidence(
    *,
    kind: str,
    asset_code: str,
    purpose: str,
    effective_on: date | None,
    coverage: PortfolioRiskCoverage | None = None,
) -> PortfolioRiskSourceEvidence:
    """Build a clearly synthetic source record with separate capture and source clocks."""

    record_id = f"fixture:{kind}:{asset_code}"
    return PortfolioRiskSourceEvidence(
        source_id=f"test-only-provider:{kind}:{asset_code}",
        source_record_id=record_id,
        original_payload_sha256=hashlib.sha256(f"vendor-body:{record_id}".encode()).hexdigest(),
        observation_precision=SourceObservationPrecision.TIMESTAMP,
        observed_at=AS_OF - timedelta(minutes=2),
        observed_on=None,
        available_at=AS_OF - timedelta(minutes=1),
        known_at=AS_OF - timedelta(seconds=30),
        decision_cutoff=AS_OF,
        decision_date_cutoff=BUSINESS_DATE,
        valid_until=AS_OF + timedelta(hours=2),
        source_purpose=purpose,
        allowed_purposes=(purpose,),
        restrictions=(),
        must_not_use_for_decision=False,
        coverage=coverage or _coverage(),
        effective_on=effective_on,
    )


def _membership(asset_code: str, industry_code: str) -> IndustryMembership:
    """Use only explicit fixture taxonomy facts; never infer membership from a code."""

    return IndustryMembership(
        taxonomy_id="fixture-industry-taxonomy",
        taxonomy_kind="industry",
        provider_id="fixture-membership-provider",
        provider_version="fixture-source-binding",
        industry_code=industry_code,
        effective_from=BUSINESS_DATE,
        effective_end_state=EffectiveEndState.OPEN,
        source_evidence=_evidence(
            kind="industry_membership",
            asset_code=asset_code,
            purpose=INDUSTRY_PURPOSE,
            effective_on=BUSINESS_DATE,
        ),
    )


def _capacity(asset_code: str, security_id: str) -> CapacityWindowObservation:
    """Supply a synthetic rolling window and explicit same-session status fact."""

    window_end = BUSINESS_DATE - timedelta(days=1)
    window_start = window_end - timedelta(days=2)
    return CapacityWindowObservation(
        asset_code=asset_code,
        security_id=security_id,
        window_kind="rolling_sessions",
        window_start=window_start,
        window_end=window_end,
        window_sessions=2,
        volume=CapacityValue(Decimal("100000"), "share"),
        amount=CapacityValue(Decimal("10000000"), "CNY"),
        execution_session_suspended=False,
        execution_session_state_date=EXECUTION_SESSION,
        execution_session_state_evidence=_evidence(
            kind="execution_session_state",
            asset_code=asset_code,
            purpose=CAPACITY_PURPOSE,
            effective_on=EXECUTION_SESSION,
        ),
        source_evidence=_evidence(
            kind="capacity_window",
            asset_code=asset_code,
            purpose=CAPACITY_PURPOSE,
            effective_on=window_end,
        ),
    )


def _asset_inputs(
    policy: PortfolioRiskPolicyBundle,
) -> PortfolioRiskAssetsReadResult:
    """Return complete exact test bindings, including one explicitly partial ETF report."""

    bank_a = _membership(BANK_A_CODE, FINANCE_FACTOR)
    bank_b = _membership(BANK_B_CODE, FINANCE_FACTOR)
    other = _membership(OTHER_CODE, OTHER_FACTOR)
    report_date = BUSINESS_DATE
    report_evidence = _evidence(
        kind="etf_report",
        asset_code=ETF_CODE,
        purpose=INDUSTRY_PURPOSE,
        effective_on=report_date,
        coverage=_coverage(
            status=CoverageStatus.PARTIAL,
            fraction=Decimal("0.90"),
            expected=10,
            observed=3,
        ),
    )
    report = ETFConstituentReport(
        report_date=report_date,
        source_evidence=report_evidence,
        constituents=(
            ETFConstituent(
                asset_code=BANK_A_CODE,
                weight_fraction=Decimal("0.25"),
                kind=ETFConstituentKind.EQUITY,
                industry_membership=bank_a,
            ),
            ETFConstituent(
                asset_code=BANK_B_CODE,
                weight_fraction=Decimal("0.20"),
                kind=ETFConstituentKind.EQUITY,
                industry_membership=bank_b,
            ),
            ETFConstituent(
                asset_code=OTHER_CODE,
                weight_fraction=Decimal("0.45"),
                kind=ETFConstituentKind.EQUITY,
                industry_membership=other,
            ),
        ),
    )
    facts: tuple[
        tuple[
            str,
            str,
            PortfolioAssetKind,
            Decimal,
            IndustryMembership | None,
            ETFConstituentReport | None,
        ],
        ...,
    ] = (
        (
            BANK_A_CODE,
            BANK_A_SECURITY,
            PortfolioAssetKind.EQUITY,
            Decimal("10"),
            bank_a,
            None,
        ),
        (
            BANK_B_CODE,
            BANK_B_SECURITY,
            PortfolioAssetKind.EQUITY,
            Decimal("10"),
            bank_b,
            None,
        ),
        (
            ETF_CODE,
            ETF_SECURITY,
            PortfolioAssetKind.ETF,
            Decimal("100"),
            None,
            report,
        ),
    )
    assets: list[PortfolioRiskAssetInputs] = []
    evidence_by_identity: dict[tuple[str, str], PortfolioRiskSourceEvidence] = {}
    for asset_code, security_id, kind, price, membership, etf_report in facts:
        valuation = _evidence(
            kind="valuation",
            asset_code=asset_code,
            purpose=INDUSTRY_PURPOSE,
            effective_on=BUSINESS_DATE,
        )
        capacity = _capacity(asset_code, security_id)
        assets.append(
            PortfolioRiskAssetInputs(
                asset_code=asset_code,
                security_id=security_id,
                kind=kind,
                price=price,
                quantity_unit="share",
                price_unit="CNY",
                valuation_evidence=valuation,
                industry_membership=membership,
                etf_report=etf_report,
                capacity_observation=capacity,
            )
        )
        for evidence in (
            valuation,
            capacity.source_evidence,
            cast(PortfolioRiskSourceEvidence, capacity.execution_session_state_evidence),
        ):
            evidence_by_identity[(evidence.source_id, evidence.source_record_id)] = evidence
        if membership is not None:
            evidence_by_identity[
                (membership.source_evidence.source_id, membership.source_evidence.source_record_id)
            ] = membership.source_evidence
        if etf_report is not None:
            evidence_by_identity[
                (etf_report.source_evidence.source_id, etf_report.source_evidence.source_record_id)
            ] = etf_report.source_evidence
            for row in etf_report.constituents:
                if row.industry_membership is not None:
                    row_evidence = row.industry_membership.source_evidence
                    evidence_by_identity[
                        (row_evidence.source_id, row_evidence.source_record_id)
                    ] = row_evidence

    return PortfolioRiskAssetsReadResult(
        status="complete",
        assets=tuple(assets),
        all_source_evidence=tuple(
            sorted(
                evidence_by_identity.values(),
                key=lambda item: (item.source_id, item.source_record_id),
            )
        ),
        reason_codes=(),
        policy_snapshot_id=policy.snapshot_id,
        policy_snapshot_hash=policy.snapshot_hash,
        source_reference_bindings=policy.source_references,
    )


def _account_snapshot() -> AccountSnapshot:
    """Return two same-factor equities plus one overlapping, partly unknown ETF."""

    return AccountSnapshot(
        account_id=ACCOUNT_ID,
        owner_user_id=OWNER_ID,
        snapshot_id=SNAPSHOT_ID,
        read_at=AS_OF - timedelta(seconds=20),
        cash=Decimal("6000"),
        money_unit="CNY",
        holdings=(
            HeldPosition(
                asset_code=BANK_A_CODE,
                quantity=Decimal("200"),
                available_quantity=Decimal("200"),
                security_id=BANK_A_SECURITY,
            ),
            HeldPosition(
                asset_code=BANK_B_CODE,
                quantity=Decimal("100"),
                available_quantity=Decimal("100"),
                security_id=BANK_B_SECURITY,
            ),
            HeldPosition(
                asset_code=ETF_CODE,
                quantity=Decimal("10"),
                available_quantity=Decimal("10"),
                security_id=ETF_SECURITY,
            ),
        ),
        active_orders=(),
        executed_usage=(
            ExecutedUsage(
                asset_code=BANK_A_CODE,
                security_id=BANK_A_SECURITY,
                execution_session=EXECUTION_SESSION,
                quantity=Decimal("0"),
                amount=Decimal("0"),
                complete=True,
            ),
            ExecutedUsage(
                asset_code=BANK_B_CODE,
                security_id=BANK_B_SECURITY,
                execution_session=EXECUTION_SESSION,
                quantity=Decimal("0"),
                amount=Decimal("0"),
                complete=True,
            ),
            ExecutedUsage(
                asset_code=ETF_CODE,
                security_id=ETF_SECURITY,
                execution_session=EXECUTION_SESSION,
                quantity=Decimal("0"),
                amount=Decimal("0"),
                complete=True,
            ),
        ),
        active_orders_complete=True,
        execution_session=EXECUTION_SESSION,
        executed_usage_complete=True,
    )


def _revision() -> ScenarioRevision:
    """Create one explicit, hypothetical synchronized decline on the configured factor."""

    return ScenarioRevision(
        revision_id="fixture-scenario-revision-1",
        scenario_key="ash07.fixture.same-industry-shock",
        version=1,
        status=ScenarioRevisionStatus.APPROVED,
        scenario_type=ScenarioType.PARAMETRIC_SHOCK,
        parameters=ParametricShockParameters(
            shocks=(
                ParametricShock(
                    target_kind="factor",
                    target=FINANCE_FACTOR,
                    shock_kind="return",
                    magnitude=Decimal("-0.20"),
                    unit=ShockUnit.PERCENT,
                    horizon_days=1,
                ),
            ),
            correlation_assumption="one explicit test shock applies synchronously to every matching factor loading",
        ),
        assumptions=(
            "Synthetic test-only factor shock; magnitude is a scenario assumption, not a market observation.",
        ),
        source_type=ScenarioSourceType.HUMAN,
        created_by="ash07-test-fixture",
        change_reason="exercise multi-holding source-bound factor projection",
        created_at=AS_OF - timedelta(hours=1),
    )


class _Clock(PortfolioRiskClock):
    """Use one exact test cutoff for preparation and Scenario persistence."""

    def now(self) -> datetime:
        return AS_OF


class _ScenarioRepository(ScenarioQueryRepositoryProtocol):
    """Expose the one immutable fixture revision to the real preview use case."""

    def __init__(self, revision: ScenarioRevision) -> None:
        self.revision = revision
        self.reads = 0

    def get_revision(
        self, identifier: str, *, version: int | None = None
    ) -> ScenarioRevision | None:
        self.reads += 1
        if identifier not in {self.revision.revision_id, self.revision.scenario_key}:
            return None
        if version is not None and version != self.revision.version:
            return None
        return self.revision

    def list_definitions(self, *, include_retired: bool = False) -> tuple[ScenarioDefinition, ...]:
        return ()

    def list_current_revisions(
        self, *, scenario_type: ScenarioType | None = None, include_inactive: bool = False
    ) -> tuple[ScenarioRevision, ...]:
        return ()

    def list_revisions(self, identifier: str) -> tuple[ScenarioRevision, ...]:
        return (
            (self.revision,)
            if identifier in {self.revision.revision_id, self.revision.scenario_key}
            else ()
        )

    def get_active_set_revision(
        self, *, environment: str, purpose: str
    ) -> ScenarioSetRevision | None:
        return None


class _SyntheticParametricMarketData(ScenarioMarketDataProviderProtocol):
    """Return only a synthetic evidence envelope; the factor shock supplies the hypothesis."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], datetime]] = []

    def get_market_data(
        self,
        revision: ScenarioRevision,
        *,
        asset_codes: tuple[str, ...],
        as_of_time: datetime,
    ) -> ScenarioMarketDataDTO:
        self.calls.append((asset_codes, as_of_time))
        return ScenarioMarketDataDTO(
            return_series=(),
            evidence_ids=("synthetic-test-only-parametric-input",),
            observed_at=as_of_time - timedelta(minutes=2),
            published_at=as_of_time - timedelta(minutes=1),
        )


class _EvidenceRepository(ScenarioRunEvidenceReadWriteRepositoryProtocol):
    """Keep one deterministic Scenario record and its exact replay snapshots."""

    def __init__(self) -> None:
        self.rows: dict[str, ScenarioRunEvidence] = {}
        self.saves = 0

    def save_run_evidence(self, evidence: ScenarioRunEvidence) -> ScenarioRunEvidence:
        self.saves += 1
        existing = self.rows.get(evidence.run_id)
        if existing is not None:
            if existing != evidence:
                raise ValueError("scenario run id already exists with different evidence")
            return existing
        self.rows[evidence.run_id] = evidence
        return evidence

    def get_run_evidence(self, run_id: str) -> ScenarioRunEvidence | None:
        return self.rows.get(run_id)


class _PressureFactory(PortfolioPressureApplicationFactory):
    """Build the production Scenario preview and pressure use case over test ports."""

    def __init__(
        self,
        *,
        scenarios: _ScenarioRepository,
        market_data: _SyntheticParametricMarketData,
        evidence: _EvidenceRepository,
    ) -> None:
        self.scenarios = scenarios
        self.market_data = market_data
        self.evidence = evidence
        self.builds = 0

    def build(
        self,
        *,
        portfolio_provider: PortfolioSnapshotProviderProtocol,
        projection_provider: PortfolioPressureProjectionProviderProtocol,
        clock: ScenarioPressureClockProtocol,
    ) -> RunPortfolioExitPressureUseCase:
        self.builds += 1
        preview = PreviewScenarioImpactUseCase(
            scenario_repository=self.scenarios,
            portfolio_provider=portfolio_provider,
            market_data_provider=self.market_data,
        )
        return RunPortfolioExitPressureUseCase(
            preview=preview,
            run_evidence_repository=self.evidence,
            projection_provider=projection_provider,
            clock=clock,
        )


def _assessment(
    snapshot: AccountSnapshot,
    policy: PortfolioRiskPolicyBundle,
    assets: PortfolioRiskAssetsReadResult,
) -> PortfolioRiskAssessmentResult:
    """Run the real Risk Center aggregate and its industry/ETF/capacity algorithms."""

    return assess_simulated_portfolio_risk(
        snapshot=snapshot,
        proposals=(),
        policy=policy,
        asset_inputs=assets,
        as_of=AS_OF,
        business_date=BUSINESS_DATE,
        capacity_requested_purpose=CAPACITY_PURPOSE,
    )


def _calendar() -> PortfolioRiskCalendarReadResult:
    """Bind this synthetic current session to explicit, canonical test evidence."""

    evidence_json = canonical_portfolio_risk_json(
        {
            "provider": "synthetic-test-calendar",
            "requested_session": BUSINESS_DATE,
            "open_sessions": (BUSINESS_DATE,),
            "note": "test fixture only; not an exchange calendar publication",
        }
    )
    return PortfolioRiskCalendarReadResult(
        requested_session_qualified=True,
        open_sessions=(BUSINESS_DATE,),
        reason_codes=(),
        canonical_evidence_json=evidence_json,
        evidence_hash=hashlib.sha256(evidence_json.encode("utf-8")).hexdigest(),
        valid_until=AS_OF + timedelta(hours=1),
    )


def _prepared(
    *,
    policy: PortfolioRiskPolicyBundle,
    snapshot: AccountSnapshot,
    assets: PortfolioRiskAssetsReadResult,
    assessment: PortfolioRiskAssessmentResult,
) -> PreparedPortfolioRisk:
    """Create the runner's exact immutable test context without an order write path."""

    native_limits = PortfolioRiskNativeAccountLimits(
        max_single_weight=Decimal("0.95"),
        max_total_weight=Decimal("0.95"),
        reason_codes=(),
        basis="simulated_account_percent_fields",
    )
    scope = PortfolioRiskAccountScope(owner_user_id=OWNER_ID, can_read=True, can_write=True)
    resources = AccountSnapshotReadResult(
        snapshot=snapshot,
        scope=scope,
        native_account_limits=native_limits,
        reason_codes=(),
        identity_issues=(),
        money_unit_basis="native_simulated_ledger_config",
    )
    identity_bindings = (
        PortfolioRiskIdentityBinding(
            asset_code=BANK_A_CODE,
            ledger_security_id=BANK_A_SECURITY,
            source_security_id=BANK_A_SECURITY,
            basis="ledger",
        ),
        PortfolioRiskIdentityBinding(
            asset_code=BANK_B_CODE,
            ledger_security_id=BANK_B_SECURITY,
            source_security_id=BANK_B_SECURITY,
            basis="ledger",
        ),
        PortfolioRiskIdentityBinding(
            asset_code=ETF_CODE,
            ledger_security_id=ETF_SECURITY,
            source_security_id=ETF_SECURITY,
            basis="ledger",
        ),
    )
    return PreparedPortfolioRisk(
        actor_user_id=OWNER_ID,
        snapshot=snapshot,
        resources=resources,
        proposals=(),
        policy=policy,
        baseline_source=PortfolioBaselinePolicyReadResult(
            policy=None,
            reason_codes=("TEST_FIXTURE_BASELINE_NOT_EXERCISED",),
        ),
        assets=assets,
        calendar=_calendar(),
        assessment=assessment,
        report=assessment.report_payload,
        as_of=AS_OF,
        business_date=BUSINESS_DATE,
        identity_bindings=identity_bindings,
        policy_binding_sha256="b" * 64,
        native_limits_sha256="c" * 64,
        input_snapshot_json=canonical_portfolio_risk_json(
            {"snapshot": snapshot, "policy_snapshot_id": policy.snapshot_id}
        ),
        capacity_requested_purpose=CAPACITY_PURPOSE,
    )


def test_same_industry_factor_shock_projects_all_holdings_and_replays_saved_explanation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply one factor assumption to both stocks and an ETF upper bound, then replay once."""

    import apps.simulated_trading.application.portfolio_risk_pressure_runner as runner_module

    policy = _policy()
    snapshot = _account_snapshot()
    assets = _asset_inputs(policy)
    assessment = _assessment(snapshot, policy, assets)
    industry = assessment.industry_assessment
    assert industry is not None
    assert industry.outcome.value == "within_limit"
    assert industry.unknown_industry_market_value == Decimal("100")
    bank_bound = next(
        item for item in industry.industry_bounds if item.industry_code == FINANCE_FACTOR
    )
    assert bank_bound.known_market_value == Decimal("3450")
    assert bank_bound.unknown_market_value == Decimal("100")
    assert bank_bound.upper_weight == Decimal("0.355")
    etf_bound = next(item for item in industry.etf_bounds if item.asset_code == ETF_CODE)
    assert etf_bound.reported_coverage_fraction == Decimal("0.90")
    assert etf_bound.unknown_market_value == Decimal("100")
    repeated = {item.asset_code: item for item in industry.repeated_underlyings}
    assert repeated[BANK_A_CODE].direct_market_value == Decimal("2000")
    assert repeated[BANK_A_CODE].etf_market_value == Decimal("250")
    assert repeated[BANK_B_CODE].direct_market_value == Decimal("1000")
    assert repeated[BANK_B_CODE].etf_market_value == Decimal("200")

    revision = _revision()
    definition = ScenarioDefinition(
        scenario_key=revision.scenario_key,
        name="Synthetic synchronized financial-factor decline",
        category="ASH07_TEST_ONLY",
        owner="tests",
        status=ScenarioDefinitionStatus.ACTIVE,
        description="A hypothetical test shock, not a market forecast.",
        created_at=AS_OF - timedelta(hours=1),
    )
    summary = ScenarioSummaryDTO(definition=definition, revision=revision)
    monkeypatch.setattr(runner_module, "list_scenarios", lambda: (summary,))

    scenario_repository = _ScenarioRepository(revision)
    market_data = _SyntheticParametricMarketData()
    evidence_repository = _EvidenceRepository()
    pressure_factory = _PressureFactory(
        scenarios=scenario_repository,
        market_data=market_data,
        evidence=evidence_repository,
    )
    unused_port = object()
    runtime = PortfolioRiskRuntime(
        policy_reader=cast(PortfolioRiskPolicyReader, unused_port),
        assets_reader=cast(PortfolioRiskAssetsReader, unused_port),
        baseline_reader=cast(PortfolioBaselinePolicyReader, unused_port),
        execution_evidence_writer=cast(PortfolioRiskExecutionEvidenceWriter, unused_port),
        pressure_factory=cast(PortfolioPressureApplicationFactory, pressure_factory),
        pressure_evidence_repository=cast(
            ScenarioRunEvidenceReadWriteRepositoryProtocol, evidence_repository
        ),
    )
    runner = PortfolioRiskPressureRunnerService(
        runtime=runtime,
        code_version="test-code-sha256:" + "d" * 64,
        clock=_Clock(),
    )
    prepared = _prepared(
        policy=policy,
        snapshot=snapshot,
        assets=assets,
        assessment=assessment,
    )

    first_report = runner.run(
        prepared=prepared,
        scenario_identifier=revision.revision_id,
        idempotency_key="fixture-industry-shock-1",
    )
    second_report = runner.run(
        prepared=prepared,
        scenario_identifier=revision.revision_id,
        idempotency_key="fixture-industry-shock-1",
    )

    exit_check = next(
        item for item in first_report["checks"] if item["dimension"] == "exit_pressure"
    )
    details = exit_check["details"]
    assert details["run_evidence_persisted"] is True
    assert details["scope"] == "simulation_only"
    assert details["must_not_execute"] is True
    assert details["scenario"]["label"] == definition.name
    assert first_report == second_report
    assert len(evidence_repository.rows) == 1
    assert evidence_repository.saves == 1
    assert pressure_factory.builds == 1
    assert len(market_data.calls) == 1
    assert set(market_data.calls[0][0]) == {BANK_A_CODE, BANK_B_CODE, ETF_CODE}
    assert scenario_repository.reads == 1

    expected_run_id = portfolio_pressure_run_id(
        actor_user_id=OWNER_ID,
        account_id=ACCOUNT_ID,
        idempotency_key="fixture-industry-shock-1",
    )
    saved = evidence_repository.get_run_evidence(expected_run_id)
    assert saved is not None
    assert saved.input_snapshot_json is not None
    assert saved.result_snapshot_json is not None
    saved_inputs = json.loads(saved.input_snapshot_json)
    saved_results = json.loads(saved.result_snapshot_json)
    positions = {
        item["asset_code"]: dict(item["attributes"])
        for item in saved_inputs["scenario_context"]["snapshot"]["positions"]
    }
    assert positions[BANK_A_CODE][f"factor_loading:{FINANCE_FACTOR}"] == "1"
    assert positions[BANK_B_CODE][f"factor_loading:{FINANCE_FACTOR}"] == "1"
    assert Decimal(positions[ETF_CODE][f"factor_loading:{FINANCE_FACTOR}"]) == Decimal("0.55")
    impact = saved_results["scenario_impact"]
    assert Decimal(impact["initial_value"]) == Decimal("10000")
    assert Decimal(impact["total_return"]) == Decimal("-0.071")
    assert Decimal(impact["final_value"]) == Decimal("9290.000")
    assert details["scenario_result_hash"] == impact["result_hash"]
    public_impact = details["scenario_impact"]
    assert public_impact["scope"] == "portfolio_snapshot_net_asset_value"
    assert public_impact["initial_value"] == impact["initial_value"]
    assert public_impact["final_value"] == impact["final_value"]
    assert public_impact["value_unit"] == "CNY"
    assert public_impact["total_return"] == impact["total_return"]
    assert public_impact["total_return_unit"] == "fraction"
    assert public_impact["scenario_result_hash"] == impact["result_hash"]
    assert public_impact["hypothetical"] is True
    assert public_impact["market_observation"] is False
    assert saved.result_hash == scenario_run_snapshot_hash(
        input_snapshot_json=saved.input_snapshot_json,
        result_snapshot_json=saved.result_snapshot_json,
    )
