"""Service-level DI contracts using synthetic simulation-only risk sources."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from apps.config_center.application.runtime_value_evidence import ActiveRuntimeValueEvidence
from apps.risk_center.application.portfolio_baseline_risk import (
    PortfolioBaselinePolicy,
    PortfolioBaselinePolicyReader,
    PortfolioBaselinePolicyReadResult,
)
from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetIdentity,
    PortfolioRiskAssetInputs,
    PortfolioRiskAssetsReader,
    PortfolioRiskAssetsReadRequest,
    PortfolioRiskAssetsReadResult,
)
from apps.risk_center.application.portfolio_risk_execution_evidence import (
    PortfolioRiskExecutionEvidence,
    PortfolioRiskExecutionEvidenceWriter,
)
from apps.risk_center.application.portfolio_risk_policy import (
    SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
    PortfolioRiskPolicyBundle,
    PortfolioRiskPolicyReader,
    PortfolioRiskPolicyReadResult,
    parse_portfolio_risk_policy_bundle,
)
from apps.risk_center.application.portfolio_risk_runtime import (
    PortfolioPressureApplicationFactory,
    PortfolioRiskRuntime,
)
from apps.risk_center.application.scenario_ports import ScenarioRunEvidenceRepositoryProtocol
from apps.risk_center.domain.portfolio_baseline_risk import (
    PortfolioBaselinePolicy as BaselinePolicy,
)
from apps.risk_center.domain.portfolio_capacity import (
    CapacityValue,
    CapacityWindowObservation,
)
from apps.risk_center.domain.portfolio_exposure_types import (
    EffectiveEndState,
    IndustryMembership,
    PortfolioAssetKind,
)
from apps.risk_center.domain.portfolio_risk_native_limits import (
    PortfolioRiskNativeAccountLimits,
)
from apps.risk_center.domain.portfolio_risk_snapshot import (
    AccountSnapshot,
    ExecutedUsage,
    HeldPosition,
    OpenOrder,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventKind,
    LocalSimulatedFillEventV1,
)
from apps.simulated_trading.application.portfolio_risk_calendar import (
    PortfolioRiskCalendarReader,
    PortfolioRiskCalendarReadRequest,
    PortfolioRiskCalendarReadResult,
)
from apps.simulated_trading.application.portfolio_risk_context import (
    PortfolioRiskClock,
    PortfolioRiskPressureRunner,
)
from apps.simulated_trading.application.portfolio_risk_public import (
    PortfolioRiskAccountAccessDenied,
)
from apps.simulated_trading.application.portfolio_risk_resource_ports import (
    AccountSnapshotReadResult,
    PortfolioRiskAccountScope,
    PortfolioRiskResourceSnapshotReaderProtocol,
)
from apps.simulated_trading.application.portfolio_risk_service import (
    OwnerScopedPortfolioRiskService,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    SimulatedTradeSide,
)

_AS_OF = datetime(2026, 11, 3, 2, 0, tzinfo=UTC)
_BUSINESS_DATE = date(2026, 11, 3)
_SESSION = date(2026, 11, 3)
_ACCOUNT_ID = 12
_OWNER_ID = 4
_ASSET_CODE = "600036"
_SECURITY_ID = "SSE:600036"
_CAPACITY_PURPOSE = "simulation_portfolio_risk_capacity"
_INDUSTRY_PURPOSE = "ash07_portfolio_exposure"


def _configuration() -> dict[str, object]:
    """Return one explicit synthetic runtime profile used only in these tests."""

    source_references = (
        _reference("valuation", "valuation-record", "a"),
        _reference("industry_membership", "industry-record", "b"),
        _reference("capacity_window", "capacity-record", "c"),
        _reference("execution_session_state", "session-state-record", "d"),
    )
    return {
        "schema_version": "ash07.simulated_portfolio_risk.v1",
        "scope": "simulation_only",
        "ledger_money_unit": "CNY",
        "account_ids": [_ACCOUNT_ID],
        "industry": {
            "taxonomy_id": "synthetic-industry-taxonomy",
            "taxonomy_kind": "industry",
            "provider_id": "synthetic-provider",
            "provider_version": "synthetic-1",
            "requested_purpose": _INDUSTRY_PURPOSE,
            "date_precision_purposes": [_INDUSTRY_PURPOSE],
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
        "source_max_timestamp_age_seconds": 1800,
        "source_max_date_age_days": 5,
        "source_references": list(source_references),
    }


def _reference(kind: str, record_id: str, hash_letter: str) -> dict[str, object]:
    """Build one policy pin for the single explicitly synthetic security."""

    return {
        "kind": kind,
        "asset_code": _ASSET_CODE,
        "security_id": _SECURITY_ID,
        "raw_payload_hash": "sha256:" + hash_letter * 64,
        "source_record_id": record_id,
    }


def _policy_bundle(
    *,
    profile_version: int = 12,
    snapshot_id: str = "synthetic-risk-snapshot-12",
    snapshot_hash: str = "f" * 64,
) -> PortfolioRiskPolicyBundle:
    """Parse a versioned synthetic runtime value into the actual policy DTOs."""

    created_at = _AS_OF - timedelta(minutes=3)
    effective_at = _AS_OF - timedelta(minutes=2)
    generated_at = _AS_OF - timedelta(minutes=1)
    evidence = ActiveRuntimeValueEvidence(
        environment="test",
        definition_key=SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
        value=_configuration(),
        profile_id=f"synthetic-risk-profile-{profile_version}",
        profile_key="synthetic-risk-profile",
        profile_version=profile_version,
        profile_content_hash="e" * 64,
        snapshot_id=snapshot_id,
        snapshot_hash=snapshot_hash,
        created_at=created_at,
        known_at=created_at,
        activated_at=effective_at,
        snapshot_generated_at=generated_at,
        effective_at=effective_at,
        as_of=_AS_OF,
    )
    return parse_portfolio_risk_policy_bundle(
        evidence,
        business_date=_BUSINESS_DATE,
        as_of=_AS_OF,
    )


def _baseline_policy(*, hard_exclusions: tuple[str, ...] = ()) -> BaselinePolicy:
    """Build existing baseline constraints without inventing system defaults."""

    return BaselinePolicy(
        account_id=_ACCOUNT_ID,
        account_policy_id=700,
        content_sha256="7" * 64,
        known_at=_AS_OF - timedelta(minutes=1),
        effective_until=None,
        max_total_weight=Decimal("0.95"),
        max_single_weight=Decimal("0.50"),
        min_cash_weight=Decimal("0.10"),
        hard_exclusions=hard_exclusions,
    )


def _native_limits() -> PortfolioRiskNativeAccountLimits:
    """Build explicit native simulated-account caps for the synthetic ledger."""

    return PortfolioRiskNativeAccountLimits(
        max_single_weight=Decimal("0.95"),
        max_total_weight=Decimal("0.95"),
        reason_codes=(),
        basis="simulated_account_percent_fields",
    )


def _snapshot(*, active_orders: tuple[OpenOrder, ...] | None = None) -> AccountSnapshot:
    """Build an exact synthetic account with held exposure and current-session usage."""

    selected_orders = (
        active_orders
        if active_orders is not None
        else (
            OpenOrder(
                order_id="buy-hold-1",
                asset_code=_ASSET_CODE,
                security_id=_SECURITY_ID,
                side="buy",
                remaining_quantity=Decimal("2"),
                remaining_amount=Decimal("19"),
                remaining_cash=Decimal("25"),
            ),
            OpenOrder(
                order_id="sell-hold-1",
                asset_code=_ASSET_CODE,
                security_id=_SECURITY_ID,
                side="sell",
                remaining_quantity=Decimal("3"),
                remaining_amount=Decimal("30"),
                remaining_cash=Decimal("0"),
            ),
        )
    )
    return AccountSnapshot(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        snapshot_id="synthetic-account-snapshot-12",
        read_at=_AS_OF - timedelta(seconds=1),
        cash=Decimal("10000"),
        money_unit="CNY",
        holdings=(
            HeldPosition(
                asset_code=_ASSET_CODE,
                quantity=Decimal("100"),
                available_quantity=Decimal("90"),
                security_id=_SECURITY_ID,
            ),
        ),
        active_orders=selected_orders,
        executed_usage=(
            ExecutedUsage(
                asset_code=_ASSET_CODE,
                security_id=_SECURITY_ID,
                execution_session=_SESSION,
                quantity=Decimal("5"),
                amount=Decimal("50"),
                complete=True,
            ),
        ),
        active_orders_complete=True,
        execution_session=_SESSION,
        executed_usage_complete=True,
    )


def _intent(*, user_id: int = _OWNER_ID) -> SimulatedTradeIntent:
    """Build one exact BUY intent for owner, delegated-write, and fill cases."""

    return SimulatedTradeIntent(
        account_id=_ACCOUNT_ID,
        user_id=user_id,
        idempotency_key="risk-test-buy",
        side=SimulatedTradeSide.BUY,
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        asset_name="Synthetic Equity",
        asset_type="equity",
        market="SSE",
        board="MAIN",
        quantity=Decimal("10"),
        price=Decimal("9"),
        reason="synthetic portfolio risk service fixture",
        signal_id=None,
    )


def _source_evidence(
    *,
    record_id: str,
    purpose: str,
    as_of: datetime,
    valid_until: datetime,
    effective_on: date | None = None,
    decision_date_cutoff: date | None = None,
    precision: SourceObservationPrecision = SourceObservationPrecision.TIMESTAMP,
) -> PortfolioRiskSourceEvidence:
    """Create a fully clocked synthetic source while preserving precision honestly."""

    observed_at = as_of - timedelta(minutes=1)
    if precision is SourceObservationPrecision.UNKNOWN:
        observed_at = None
    return PortfolioRiskSourceEvidence(
        source_id=f"synthetic-source:{record_id}",
        source_record_id=record_id,
        original_payload_sha256=hashlib.sha256(record_id.encode("utf-8")).hexdigest(),
        observation_precision=precision,
        observed_at=observed_at,
        observed_on=None,
        available_at=as_of - timedelta(seconds=30),
        known_at=as_of - timedelta(seconds=20),
        decision_cutoff=as_of,
        decision_date_cutoff=decision_date_cutoff,
        valid_until=valid_until,
        source_purpose=purpose,
        allowed_purposes=(purpose,),
        restrictions=(),
        must_not_use_for_decision=False,
        coverage=PortfolioRiskCoverage(
            status=CoverageStatus.COMPLETE,
            precision_basis="portfolio_weight",
            reported_weight_fraction=Decimal("1"),
        ),
        effective_on=effective_on,
    )


class _Clock:
    """Return a stable actual-like aware clock for this all-synthetic DI fixture."""

    def now(self) -> datetime:
        """Return the fixed aware test clock."""

        return _AS_OF


class _PolicyReader:
    """Return a replaceable typed policy to exercise service-time revalidation."""

    def __init__(self, policy: PortfolioRiskPolicyBundle) -> None:
        self.policy = policy
        self.reads: list[tuple[int, datetime, date]] = []

    def read_policy(
        self,
        *,
        as_of: datetime,
        business_date: date,
        account_id: int,
    ) -> PortfolioRiskPolicyReadResult:
        """Record the exact caller cutoff and return the currently selected profile."""

        self.reads.append((account_id, as_of, business_date))
        return PortfolioRiskPolicyReadResult(policy=self.policy, reason_codes=())


class _BaselineReader:
    """Return one explicit baseline policy or a caller-selected exclusion fixture."""

    def __init__(self, policy: BaselinePolicy) -> None:
        self.policy = policy
        self.reads: list[tuple[int, datetime]] = []

    def read_baseline_policy(
        self, *, account_id: int, as_of: datetime
    ) -> PortfolioBaselinePolicyReadResult:
        """Record the read cutoff and return only the configured synthetic row."""

        self.reads.append((account_id, as_of))
        return PortfolioBaselinePolicyReadResult(policy=self.policy, reason_codes=())


class _AssetsReader:
    """Build typed synthetic facts so the real application invokes real Domain math."""

    def __init__(self, *, mode: str = "complete") -> None:
        self.mode = mode
        self.requests: list[PortfolioRiskAssetsReadRequest] = []

    def read_assets(self, request: PortfolioRiskAssetsReadRequest) -> PortfolioRiskAssetsReadResult:
        """Return exact policy-bound DTOs, optionally exposing an unknown or expired source."""

        self.requests.append(request)
        references = request.policy.source_references
        reference_by_kind = {item.kind: item for item in references}
        valid_until = request.as_of + timedelta(hours=1)
        valuation_valid_until = (
            request.as_of - timedelta(seconds=1) if self.mode == "expired" else valid_until
        )
        valuation_precision = (
            SourceObservationPrecision.UNKNOWN
            if self.mode == "unknown"
            else SourceObservationPrecision.TIMESTAMP
        )
        valuation = _source_evidence(
            record_id=reference_by_kind["valuation"].source_record_id,
            purpose=_INDUSTRY_PURPOSE,
            as_of=request.as_of,
            valid_until=valuation_valid_until,
            precision=valuation_precision,
        )
        membership_effective = request.business_date - timedelta(days=2)
        membership_source = _source_evidence(
            record_id=reference_by_kind["industry_membership"].source_record_id,
            purpose=_INDUSTRY_PURPOSE,
            as_of=request.as_of,
            valid_until=valid_until,
            effective_on=membership_effective,
            decision_date_cutoff=request.business_date,
        )
        capacity_end = request.execution_session - timedelta(days=1)
        capacity_source = _source_evidence(
            record_id=reference_by_kind["capacity_window"].source_record_id,
            purpose=request.capacity_requested_purpose,
            as_of=request.as_of,
            valid_until=valid_until,
            effective_on=capacity_end,
        )
        state_source = _source_evidence(
            record_id=reference_by_kind["execution_session_state"].source_record_id,
            purpose=request.capacity_requested_purpose,
            as_of=request.as_of,
            valid_until=valid_until,
            effective_on=request.execution_session,
        )
        membership = IndustryMembership(
            taxonomy_id=request.policy.industry_policy.taxonomy_id,
            taxonomy_kind="industry",
            provider_id=request.policy.industry_policy.provider_id,
            provider_version=request.policy.industry_policy.provider_version,
            industry_code="FINANCE",
            effective_from=membership_effective,
            effective_end_state=EffectiveEndState.OPEN,
            source_evidence=membership_source,
        )
        observation = CapacityWindowObservation(
            asset_code=_ASSET_CODE,
            security_id=_SECURITY_ID,
            window_kind="rolling_sessions",
            window_start=request.execution_session - timedelta(days=2),
            window_end=capacity_end,
            window_sessions=2,
            volume=CapacityValue(Decimal("100000"), "share"),
            amount=CapacityValue(Decimal("1000000"), "CNY"),
            execution_session_suspended=False,
            execution_session_state_date=request.execution_session,
            execution_session_state_evidence=state_source,
            source_evidence=capacity_source,
        )
        result_status = "partial" if self.mode in {"unknown", "expired"} else "complete"
        result_reasons = (
            ("RISK_SOURCE_OBSERVATION_CLOCK_UNKNOWN",)
            if self.mode == "unknown"
            else ("RISK_SOURCE_EXPIRED_AT_CUTOFF",) if self.mode == "expired" else ()
        )
        return PortfolioRiskAssetsReadResult(
            status=result_status,
            assets=(
                PortfolioRiskAssetInputs(
                    asset_code=_ASSET_CODE,
                    security_id=_SECURITY_ID,
                    kind=PortfolioAssetKind.EQUITY,
                    price=Decimal("10"),
                    quantity_unit="share",
                    price_unit="CNY",
                    valuation_evidence=valuation,
                    industry_membership=membership,
                    etf_report=None,
                    capacity_observation=observation,
                ),
            ),
            all_source_evidence=(valuation, membership_source, capacity_source, state_source),
            reason_codes=result_reasons,
            policy_snapshot_id=request.policy.snapshot_id,
            policy_snapshot_hash=request.policy.snapshot_hash,
            source_reference_bindings=references,
        )


class _ResourceReader:
    """Supply owner/delegated scope and one exact account snapshot without ORM."""

    def __init__(
        self,
        *,
        snapshot: AccountSnapshot | None,
        scope: PortfolioRiskAccountScope | None,
        native_limits: PortfolioRiskNativeAccountLimits | None,
    ) -> None:
        self.snapshot = snapshot
        self.scope = scope
        self.native_limits = native_limits
        self.reads: list[tuple[int, int, date, str | None]] = []

    def read_account_snapshot(
        self,
        *,
        user_id: int,
        account_id: int,
        execution_session: date,
        money_unit: str | None,
    ) -> AccountSnapshotReadResult:
        """Return no account data for a foreign scope and exact data otherwise."""

        self.reads.append((user_id, account_id, execution_session, money_unit))
        if self.scope is None:
            return AccountSnapshotReadResult(
                snapshot=None,
                scope=None,
                native_account_limits=None,
                reason_codes=(),
                identity_issues=(),
                money_unit_basis="unknown",
            )
        return AccountSnapshotReadResult(
            snapshot=self.snapshot,
            scope=self.scope,
            native_account_limits=self.native_limits,
            reason_codes=(),
            identity_issues=(),
            money_unit_basis="native_simulated_ledger_config",
        )

    def read_account_scope(
        self, *, user_id: int, account_id: int
    ) -> PortfolioRiskAccountScope | None:
        """Expose only the configured fake authorization scope."""

        return self.scope


class _CalendarReader:
    """Return a hash-bound test calendar result, not a live exchange assertion."""

    def __init__(self) -> None:
        self.requests: list[PortfolioRiskCalendarReadRequest] = []

    def read_calendar(
        self, request: PortfolioRiskCalendarReadRequest
    ) -> PortfolioRiskCalendarReadResult:
        """Record requested identities and return a synthetic in-session proof."""

        self.requests.append(request)
        payload = json.dumps(
            {
                "fixture": "synthetic-only",
                "requested_session": request.requested_session.isoformat(),
                "asset_pairs": [
                    [item.asset_code, item.security_id] for item in request.requested_assets
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return PortfolioRiskCalendarReadResult(
            requested_session_qualified=True,
            open_sessions=(request.requested_session,),
            reason_codes=(),
            canonical_evidence_json=payload,
            evidence_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            valid_until=request.as_of + timedelta(hours=1),
        )


class _EvidenceWriter:
    """Record actual service writes so GET and rejected paths can prove no audit."""

    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.records: list[PortfolioRiskExecutionEvidence] = []

    def record_passed_check(self, evidence: PortfolioRiskExecutionEvidence) -> None:
        """Retain only the concrete evidence passed by the service."""

        self.records.append(evidence)


class _UnusedPressureFactory:
    """Fail if a service unit test unexpectedly tries to build Scenario storage."""

    def build(self, **kwargs: object) -> object:
        """No pressure case is part of this execution-gate test suite."""

        raise AssertionError("pressure factory is outside these service test cases")


class _UnusedPressureRunner:
    """Fail if these service cases unexpectedly try to run Scenario pressure."""

    def run(self, **kwargs: object) -> object:
        """No pressure execution is part of this service DI test suite."""

        raise AssertionError("pressure runner is outside these service test cases")


@dataclass(frozen=True, slots=True)
class _Harness:
    """All isolated in-memory dependencies for one real service/context run."""

    service: OwnerScopedPortfolioRiskService
    resources: _ResourceReader
    policy_reader: _PolicyReader
    assets_reader: _AssetsReader
    baseline_reader: _BaselineReader
    writer: _EvidenceWriter
    calendar_reader: _CalendarReader


def _harness(
    *,
    scope: PortfolioRiskAccountScope | None = None,
    snapshot: AccountSnapshot | None = None,
    source_mode: str = "complete",
    hard_exclusions: tuple[str, ...] = (),
) -> _Harness:
    """Compose the real service and context builder around synthetic public ports."""

    selected_scope = scope or PortfolioRiskAccountScope(
        owner_user_id=_OWNER_ID,
        can_read=True,
        can_write=True,
    )
    resources = _ResourceReader(
        snapshot=snapshot or _snapshot(),
        scope=selected_scope,
        native_limits=_native_limits(),
    )
    policy_reader = _PolicyReader(_policy_bundle())
    assets_reader = _AssetsReader(mode=source_mode)
    baseline_reader = _BaselineReader(_baseline_policy(hard_exclusions=hard_exclusions))
    writer = _EvidenceWriter()
    calendar_reader = _CalendarReader()
    runtime = PortfolioRiskRuntime(
        policy_reader=cast(PortfolioRiskPolicyReader, policy_reader),
        assets_reader=cast(PortfolioRiskAssetsReader, assets_reader),
        baseline_reader=cast(PortfolioBaselinePolicyReader, baseline_reader),
        execution_evidence_writer=cast(PortfolioRiskExecutionEvidenceWriter, writer),
        pressure_factory=cast(PortfolioPressureApplicationFactory, _UnusedPressureFactory()),
        pressure_evidence_repository=cast(ScenarioRunEvidenceRepositoryProtocol, object()),
    )
    service = OwnerScopedPortfolioRiskService(
        resources=cast(PortfolioRiskResourceSnapshotReaderProtocol, resources),
        runtime=runtime,
        clock=cast(PortfolioRiskClock, _Clock()),
        business_timezone=ZoneInfo("Asia/Shanghai"),
        code_version="synthetic-ash07-service-test",
        using="default",
        pressure_runner=cast(PortfolioRiskPressureRunner, _UnusedPressureRunner()),
        calendar_reader=cast(PortfolioRiskCalendarReader, calendar_reader),
    )
    return _Harness(
        service=service,
        resources=resources,
        policy_reader=policy_reader,
        assets_reader=assets_reader,
        baseline_reader=baseline_reader,
        writer=writer,
        calendar_reader=calendar_reader,
    )


def test_owner_get_returns_real_synthetic_report_without_writer_side_effect() -> None:
    """GET evaluates real risk dimensions but never appends execution evidence."""

    harness = _harness()

    report = harness.service.get_report(user_id=_OWNER_ID, account_id=_ACCOUNT_ID)

    assert report["outcome"] == "allowed"
    assert report["must_not_use_for_decision"] is False
    assert report["scope"] == "simulation_only"
    assert report["must_not_execute"] is True
    capacity = next(item for item in report["checks"] if item["dimension"] == "liquidity_capacity")
    assert capacity["status"] == "allowed"
    assert capacity["details"]["decisions"][0]["status"] == "allowed"
    assert harness.writer.records == []


def test_observer_can_read_but_cannot_write_or_create_execution_evidence() -> None:
    """Delegated read scope yields a report but never qualifies a new order."""

    harness = _harness(
        scope=PortfolioRiskAccountScope(owner_user_id=_OWNER_ID, can_read=True, can_write=False)
    )

    report = harness.service.get_report(user_id=99, account_id=_ACCOUNT_ID)
    assert report["outcome"] == "allowed"

    with pytest.raises(PortfolioRiskAccountAccessDenied):
        harness.service.validate_order(
            intent=_intent(user_id=99),
            fee_cap=Decimal("0.37"),
            as_of=_AS_OF,
            execution_session=_SESSION,
        )

    assert harness.writer.records == []


def test_foreign_scope_returns_no_report_and_never_reads_account_data() -> None:
    """A foreign caller receives no snapshot, assets, report, or execution audit."""

    harness = _harness(scope=None)
    harness.resources.scope = None

    with pytest.raises(PortfolioRiskAccountAccessDenied):
        harness.service.get_report(user_id=99, account_id=_ACCOUNT_ID)

    assert len(harness.resources.reads) == 1
    assert harness.assets_reader.requests == []
    assert harness.calendar_reader.requests == []
    assert harness.writer.records == []


def test_new_order_binds_exact_fee_and_keeps_buy_sell_usage_gross_in_audit() -> None:
    """Real projection/baseline/capacity rules qualify one exact fee-bound BUY."""

    harness = _harness()
    intent = _intent()
    fee_cap = Decimal("0.37")

    qualification = harness.service.validate_order(
        intent=intent,
        fee_cap=fee_cap,
        as_of=_AS_OF,
        execution_session=_SESSION,
    )

    assert qualification.account_id == _ACCOUNT_ID
    assert qualification.owner_user_id == _OWNER_ID
    assert qualification.execution_session == _SESSION
    assert qualification.checked_at == _AS_OF
    assert len(harness.writer.records) == 1
    evidence = harness.writer.records[0]
    assert evidence.idempotency_key == intent.idempotency_key
    assert evidence.request_payload_hash == intent.request_payload_hash
    assert evidence.report["outcome"] == "allowed"
    assert evidence.report["must_not_execute"] is True
    assert evidence.policy_binding_sha256 == qualification.policy_content_sha256

    bound = json.loads(evidence.input_snapshot_json)
    risk_inputs = json.loads(bound["risk_input_snapshot_json"])
    assert risk_inputs["proposals"][0]["fee_cap"] == "0.37"
    capacity = next(
        item for item in evidence.report["checks"] if item["dimension"] == "liquidity_capacity"
    )
    decision = capacity["details"]["decisions"][0]
    assert decision["status"] == "allowed"
    assert decision["used_capacity"] == "5"
    assert decision["reserved_buy_capacity"] == "2"
    assert decision["reserved_sell_capacity"] == "3"
    assert decision["proposed_capacity"] == "10"
    baseline = next(
        item for item in evidence.report["checks"] if item["dimension"] == "baseline_risk"
    )
    assert baseline["details"]["cash_after_committed_demands"] == "9884.63"


@pytest.mark.parametrize("source_mode", ("unknown", "expired"))
def test_unknown_or_expired_source_blocks_new_order_without_audit(source_mode: str) -> None:
    """Missing clocks and source expiry are evaluated as blocking risk inputs."""

    harness = _harness(source_mode=source_mode)

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        harness.service.validate_order(
            intent=_intent(),
            fee_cap=Decimal("0.37"),
            as_of=_AS_OF,
            execution_session=_SESSION,
        )

    assert error.value.code == "PORTFOLIO_RISK_NOT_QUALIFIED"
    assert harness.writer.records == []


def test_final_verification_rejects_changed_policy_and_expired_proof() -> None:
    """A successful first check cannot survive policy replacement or its deadline."""

    harness = _harness()
    qualification = harness.service.validate_order(
        intent=_intent(),
        fee_cap=Decimal("0.37"),
        as_of=_AS_OF,
        execution_session=_SESSION,
    )
    original_writes = len(harness.writer.records)
    reads_before_verification = len(harness.policy_reader.reads)
    harness.policy_reader.policy = _policy_bundle(
        profile_version=13,
        snapshot_id="synthetic-risk-snapshot-13",
        snapshot_hash="9" * 64,
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as changed:
        harness.service.verify_qualification(
            qualification=qualification,
            as_of=_AS_OF + timedelta(seconds=1),
        )
    assert changed.value.code == "PORTFOLIO_RISK_POLICY_CHANGED"
    assert len(harness.policy_reader.reads) == reads_before_verification + 1
    assert len(harness.writer.records) == original_writes

    with pytest.raises(SimulatedTradeExecutionBlocked) as expired:
        harness.service.verify_qualification(
            qualification=qualification,
            as_of=qualification.valid_until,
        )
    assert expired.value.code == "PORTFOLIO_RISK_EXECUTION_PROOF_EXPIRED"
    assert len(harness.writer.records) == original_writes


def _fill_event(intent: SimulatedTradeIntent) -> LocalSimulatedFillEventV1:
    """Bind a synthetically accepted fill event to the exact intent and hold ID."""

    return LocalSimulatedFillEventV1(
        source_namespace="synthetic-matcher",
        source_version="synthetic-v1",
        source_event_id="synthetic-fill-event-001",
        event_payload_hash="1" * 64,
        source_snapshot_id="synthetic-matcher-snapshot",
        source_snapshot_hash="2" * 64,
        reservation_id=73,
        account_id=intent.account_id,
        user_id=intent.user_id,
        order_idempotency_key=intent.idempotency_key,
        intent_payload_hash=intent.request_payload_hash,
        reservation_request_hash="3" * 64,
        plan_snapshot_hash="4" * 64,
        security_id=intent.security_id,
        asset_code=intent.asset_code,
        side=intent.side,
        event_kind=LocalSimulatedFillEventKind.FILL,
        quantity=Decimal("10"),
        price=Decimal("10"),
        occurred_at=_AS_OF - timedelta(seconds=5),
        source_observed_at=_AS_OF - timedelta(seconds=4),
        source_available_at=_AS_OF - timedelta(seconds=3),
        recorded_at=_AS_OF - timedelta(seconds=2),
    )


def test_reserved_fill_uses_existing_hold_and_audits_original_event_without_proposal() -> None:
    """Fill qualification consumes the current hold and exact event, not a new order."""

    hold = OpenOrder(
        order_id="73",
        asset_code=_ASSET_CODE,
        security_id=_SECURITY_ID,
        side="buy",
        remaining_quantity=Decimal("100"),
        remaining_amount=Decimal("1000"),
        remaining_cash=Decimal("1010"),
    )
    harness = _harness(snapshot=_snapshot(active_orders=(hold,)))
    intent = _intent()
    event = _fill_event(intent)

    qualification = harness.service.validate_reserved_fill(
        intent=intent,
        event=event,
        execution_session=_SESSION,
        as_of=_AS_OF,
    )

    assert qualification.execution_session == _SESSION
    assert len(harness.writer.records) == 1
    evidence = harness.writer.records[0]
    assert evidence.idempotency_key == event.source_event_id
    assert evidence.request_payload_hash == event.event_payload_hash
    bound = json.loads(evidence.input_snapshot_json)
    risk_inputs = json.loads(bound["risk_input_snapshot_json"])
    assert risk_inputs["proposals"] == []
    assert bound["executing_subject"]["kind"] == "reserved_fill"
    assert bound["executing_subject"]["event"]["event_payload_hash"] == event.event_payload_hash
    assert harness.assets_reader.requests[0].requested_assets == (
        PortfolioRiskAssetIdentity(_ASSET_CODE, _SECURITY_ID),
    )


def test_baseline_hard_exclusion_rejects_even_with_qualified_synthetic_sources() -> None:
    """The existing hard exclusion remains an execution blocker before evidence write."""

    harness = _harness(hard_exclusions=(_ASSET_CODE,))

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        harness.service.validate_order(
            intent=_intent(),
            fee_cap=Decimal("0.37"),
            as_of=_AS_OF,
            execution_session=_SESSION,
        )

    assert error.value.code == "PORTFOLIO_RISK_NOT_QUALIFIED"
    assert "PORTFOLIO_BASELINE_HARD_EXCLUSION" in error.value.details["reason_codes"]
    assert harness.writer.records == []
