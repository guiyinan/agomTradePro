"""Prove SELL proceeds enter BUY power only through the real fill ledger UoW.

All source facts in the risk reader and the preview quote are explicitly
synthetic test inputs. The preview builder, owner-scoped risk service, plan
preparation/compiler/repository, account locks, normal order submission,
reservation, fill receipt, trade, cash and position writes are real.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone as django_timezone

from apps.account.application.market_price_contracts import MarketPriceResult
from apps.config_center.application.runtime_value_evidence import ActiveRuntimeValueEvidence
from apps.data_center.application.instrument_reference_snapshot import (
    SaveInstrumentReferenceSnapshotUseCase,
)
from apps.data_center.application.provider_response_payload import (
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.calendar_publication_operations_composition import (
    read_current_exchange_calendar_reference,
)
from apps.data_center.calendar_workbench_scope_composition import (
    read_calendar_capture_configuration_reference_at,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceFetchRound,
    InstrumentReferenceMappingRecord,
    InstrumentReferenceSnapshotContent,
    InstrumentReferenceSnapshotRecord,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceExchangeSuffixCrosswalk,
    InstrumentReferenceProviderContract,
)
from apps.data_center.infrastructure import tushare_client
from apps.data_center.infrastructure.instrument_reference_snapshot_repository import (
    DjangoInstrumentReferenceSnapshotRepository,
)
from apps.data_center.infrastructure.tushare_instrument_reference_source import (
    TushareInstrumentReferenceSource,
    TushareStockBasicClientPort,
)
from apps.portfolio.application.transition_plan_lifecycle import (
    CreateInitialTransitionPlanRevisionUseCase,
    CreateTransitionPlanSuccessorCommand,
    CreateTransitionPlanSuccessorUseCase,
    TransitionPlanRevisionRequest,
)
from apps.portfolio.domain.transition_plan_revision import (
    TransitionPlanOrderBinding,
    TransitionPlanRevision,
)
from apps.portfolio.domain.transition_plan_revision_support import _canonical_hash
from apps.portfolio.infrastructure.transition_plan_revision_repository import (
    DjangoTransitionPlanRevisionRepository,
)
from apps.risk_center.application.portfolio_baseline_risk import (
    PortfolioBaselinePolicyReader,
    PortfolioBaselinePolicyReadResult,
)
from apps.risk_center.application.portfolio_risk_assets import (
    PortfolioRiskAssetInputs,
    PortfolioRiskAssetsReader,
    PortfolioRiskAssetsReadRequest,
    PortfolioRiskAssetsReadResult,
)
from apps.risk_center.application.portfolio_risk_execution_evidence import (
    PortfolioRiskExecutionEvidenceWriter,
)
from apps.risk_center.application.portfolio_risk_policy import (
    SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
    PortfolioRiskPolicyReader,
    PortfolioRiskPolicyReadResult,
    PortfolioRiskSourceReference,
    parse_portfolio_risk_policy_bundle,
)
from apps.risk_center.application.portfolio_risk_runtime import (
    PortfolioPressureApplicationFactory,
    PortfolioRiskRuntime,
)
from apps.risk_center.application.scenario_ports import (
    ScenarioRunEvidenceReadWriteRepositoryProtocol,
)
from apps.risk_center.domain.local_simulated_market_policy import LocalSimulatedMarketPolicy
from apps.risk_center.domain.portfolio_baseline_risk import PortfolioBaselinePolicy
from apps.risk_center.domain.portfolio_capacity import CapacityValue, CapacityWindowObservation
from apps.risk_center.domain.portfolio_exposure_types import (
    EffectiveEndState,
    IndustryMembership,
    PortfolioAssetKind,
)
from apps.risk_center.domain.portfolio_risk_sources import (
    CoverageStatus,
    PortfolioRiskCoverage,
    PortfolioRiskSourceEvidence,
    SourceObservationPrecision,
)
from apps.risk_center.infrastructure.portfolio_risk_execution_evidence_repository import (
    DjangoPortfolioRiskExecutionEvidenceWriter,
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
    build_portfolio_risk_calendar_reader,
)
from apps.simulated_trading.application.portfolio_risk_context import (
    PortfolioRiskClock,
    PortfolioRiskPressureRunner,
    PreparedPortfolioRisk,
)
from apps.simulated_trading.application.portfolio_risk_public import (
    PortfolioRiskService,
)
from apps.simulated_trading.application.portfolio_risk_service import (
    OwnerScopedPortfolioRiskService,
)
from apps.simulated_trading.application.rebalance_journey_authorization import (
    RebalanceJourneyAccountAuthorizer,
)
from apps.simulated_trading.application.rebalance_journey_preparation import (
    PortfolioJourneyPreparationProvider,
)
from apps.simulated_trading.application.rebalance_journey_readers import (
    ServerRebalanceJourneyReads,
)
from apps.simulated_trading.application.rebalance_plan_preview import (
    ReadOnlyRebalancePlanPreviewBuilder,
)
from apps.simulated_trading.application.rebalance_plan_preview_contracts import RebalancePlanPreview
from apps.simulated_trading.application.temporary_target_entry import (
    parse_temporary_security_targets,
)
from apps.simulated_trading.application.transition_plan_execution import (
    PlanOrderPreviewCommand,
    PreviewTransitionPlanOrderUseCase,
)
from apps.simulated_trading.domain.execution_settlement_primitives import SimulatedTradeSide
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    build_order_fill_settlement_proof,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_configured_execution_calendar_reader,
    build_current_reference_classification_reader,
    build_current_reference_identity_reader,
    get_simulated_execution_runtime_environment,
)
from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_repository import (
    DjangoSimulatedOrderReservationRepository,
)
from apps.simulated_trading.infrastructure.portfolio_risk_resource_repository import (
    DjangoPortfolioRiskResourceRepository,
)
from apps.simulated_trading.infrastructure.rebalance_resource_snapshot_repository import (
    DjangoRebalanceResourceSnapshotRepository,
)
from apps.simulated_trading.owner_order_submission_composition import (
    SINA_SUBMISSION_POLICIES_KEY,
    build_owner_order_submission_use_case,
)
from apps.simulated_trading.transition_plan_journey_composition import (
    build_journey_current_policy_pins_validator,
    build_transition_plan_exact_reader,
    build_transition_plan_locked_guard,
)
from apps.strategy.application.execution_gateway import get_strategy_execution_gateway
from tests.component.data_center.test_instrument_reference_snapshot_repository import (
    FIELDS as STOCK_BASIC_FIELDS,
)
from tests.component.data_center.test_instrument_reference_snapshot_repository import (
    _body as _stock_basic_body,
)
from tests.component.simulated_trading import (
    test_auto_trading_current_reference_t1 as auto_fixtures,
)
from tests.component.simulated_trading import test_owner_order_submission_api as owner_fixtures
from tests.component.simulated_trading.test_auto_trading_current_reference_t1 import (
    AS_OF,
    ASSET_CODE,
    SECURITY_ID,
    TRADE_DATE,
    _persist_sell_position,
    _QualifiedCallerContext,
    _seed_rule_bundle,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _EventReader,
    _FixedClock,
)
from tests.integration.simulated_trading.test_m1_published_close_browser_journey import (
    isolated_m1_revision_table as isolated_m1_revision_table,
)
from tests.support.ash03_auto_calendar_clock_v2 import (
    advance_auto_uow_fixture_clocks,
)
from tests.support.ash03_auto_uow_fixture import (
    _CURRENT_REFERENCE_SELECTION_KEY,
)
from tests.support.ash03_auto_uow_fixture import _runtime_public_write_clock as _write_clock
from tests.support.native_postgres_database import assert_native_postgres_test_database
from tests.unit.data_center.test_tushare_provider_response_capture import (
    _Response,
    _Session,
)
from tests.unit.risk_center import test_local_simulated_market_provider as market_fixture
from tests.unit.simulated_trading import test_portfolio_risk_service as risk_fixtures

_clear_runtime_profile_history = auto_fixtures._clear_runtime_profile_history
_freeze_auto_fixture_knowledge_clocks = auto_fixtures._freeze_auto_fixture_knowledge_clocks
persisted_source_snapshot = auto_fixtures.persisted_source_snapshot
preserve_account_authority_generation = auto_fixtures.preserve_account_authority_generation
qualified_caller_context = auto_fixtures.qualified_caller_context
public_order_context = owner_fixtures.public_order_context

pytestmark = pytest.mark.django_db(transaction=True)

_BUY_ASSET_CODE = "601398.SH"
_BUY_SOURCE_CODE = "601398.SH"
_BUY_SECURITY_ID = "SH.ASH08.SELL_BUY.BUYER"
_TARGET_WEIGHTS = f"{ASSET_CODE},12.4\n{_BUY_ASSET_CODE},25.5"
_CAPACITY_PURPOSE = "simulation_portfolio_risk_capacity"
_MONEY_UNIT = "CNY"


class _TwoBankStockBasicSession(_Session):
    """Capture one explicitly synthetic stock-basic response for the BUY identity."""

    def __init__(self) -> None:
        super().__init__(_Response(b"{}"))

    def post(self, url: str, **kwargs: object) -> _Response:
        """Return only the fixture-owned bank row requested by this source capture."""

        del url
        self.calls.append(kwargs)
        request = kwargs.get("json")
        if not isinstance(request, dict):
            raise AssertionError("stock_basic request envelope must be a mapping")
        params = request.get("params")
        if not isinstance(params, dict):
            raise AssertionError("stock_basic request params must be a mapping")
        list_status = params.get("list_status")
        if list_status not in {"L", "D"}:
            raise AssertionError("stock_basic must request a declared list-status scope")
        rows = (
            [[_BUY_SOURCE_CODE, "Synthetic BUY bank", "SSE", "fixture-main", "L", "20200102", ""]]
            if list_status == "L"
            else []
        )
        body = _stock_basic_body(rows)
        self.response = _Response(body)
        return cast(_Response, self.response)


class _SyntheticMarketPriceProvider:
    """Supply typed test-only preview prices, never the final portfolio risk result."""

    def __init__(self, *, price: Decimal, observed_at: datetime) -> None:
        self._price = price
        self._observed_at = observed_at

    def get_price_result(
        self, asset_code: str, trade_date: date | None = None
    ) -> MarketPriceResult | None:
        """Return the one synthetic current price for either exact target asset."""

        if asset_code not in {ASSET_CODE, _BUY_ASSET_CODE}:
            return None
        if trade_date is not None and trade_date != TRADE_DATE:
            return None
        return MarketPriceResult(
            normalized_code=asset_code,
            price=float(self._price),
            as_of=TRADE_DATE,
            source="ash08-synthetic-preview-only",
            freshness="realtime",
            is_fallback=False,
            observed_at=self._observed_at,
        )

    def clear_cache(self) -> None:
        """This deterministic test provider owns no external cache."""


class _PlanRiskClock:
    """Use the same explicitly advanced Django clock as the real UOW fixture."""

    def now(self) -> datetime:
        """Return the fixture-controlled aware server time."""

        return django_timezone.now().astimezone(UTC)


class _TwoAssetPolicyReader:
    """Parse a real policy DTO over explicit per-asset synthetic source pins."""

    def __init__(
        self, *, account_id: int, source_references: tuple[dict[str, object], ...]
    ) -> None:
        self._account_id = account_id
        base = risk_fixtures._configuration()
        industry = dict(cast(dict[str, object], base["industry"]))
        industry["max_industry_weight"] = "0.95"
        industry["max_security_weight"] = "0.95"
        capacity = dict(cast(dict[str, object], base["capacity"]))
        capacity["unit"] = "shares"
        self._configuration = {
            **base,
            "account_ids": [account_id],
            "industry": industry,
            "capacity": capacity,
            "source_references": [dict(item) for item in source_references],
        }
        config_hash = _canonical_hash(self._configuration)
        self._profile_hash = config_hash
        self._snapshot_hash = config_hash

    def read_policy(
        self, *, as_of: datetime, business_date: date, account_id: int
    ) -> PortfolioRiskPolicyReadResult:
        """Return one active typed profile at the requested simulation cutoff."""

        if account_id != self._account_id:
            return PortfolioRiskPolicyReadResult(policy=None, reason_codes=("TEST_ACCOUNT_SCOPE",))
        created_at = AS_OF - timedelta(minutes=3)
        effective_at = AS_OF - timedelta(minutes=2)
        evidence = ActiveRuntimeValueEvidence(
            environment="test",
            definition_key=SIMULATED_PORTFOLIO_RISK_DEFINITION_KEY,
            value=self._configuration,
            profile_id=f"ash08-sell-buy-profile-{account_id}",
            profile_key="ash08-sell-buy-synthetic",
            profile_version=1,
            profile_content_hash=self._profile_hash,
            snapshot_id=f"ash08-sell-buy-snapshot-{account_id}",
            snapshot_hash=self._snapshot_hash,
            created_at=created_at,
            known_at=created_at,
            activated_at=effective_at,
            snapshot_generated_at=AS_OF - timedelta(minutes=1),
            effective_at=effective_at,
            as_of=as_of,
        )
        policy = parse_portfolio_risk_policy_bundle(
            evidence,
            business_date=business_date,
            as_of=as_of,
        )
        return PortfolioRiskPolicyReadResult(policy=policy, reason_codes=())


class _TwoAssetBaselineReader:
    """Supply explicit broad test-only baseline limits to the real risk assessment."""

    def __init__(self, *, account_id: int) -> None:
        self._account_id = account_id

    def read_baseline_policy(
        self, *, account_id: int, as_of: datetime
    ) -> PortfolioBaselinePolicyReadResult:
        """Return a typed, clocked baseline without changing application defaults."""

        if account_id != self._account_id:
            return PortfolioBaselinePolicyReadResult(
                policy=None, reason_codes=("TEST_ACCOUNT_SCOPE",)
            )
        return PortfolioBaselinePolicyReadResult(
            policy=PortfolioBaselinePolicy(
                account_id=account_id,
                account_policy_id=88008,
                content_sha256="8" * 64,
                known_at=AS_OF - timedelta(minutes=1),
                effective_until=None,
                max_total_weight=Decimal("0.95"),
                max_single_weight=Decimal("0.95"),
                min_cash_weight=Decimal("0.05"),
                hard_exclusions=(),
            ),
            reason_codes=(),
        )


class _TwoAssetRead:
    """Read exact source pins and supply typed facts to the real risk Domain."""

    def read_assets(self, request: PortfolioRiskAssetsReadRequest) -> PortfolioRiskAssetsReadResult:
        """Return separate valuation, membership, capacity and session facts per requested pair."""

        all_refs = request.policy.source_references
        assets: list[PortfolioRiskAssetInputs] = []
        evidences: list[PortfolioRiskSourceEvidence] = []
        for identity in request.requested_assets:
            candidate_refs = tuple(
                reference for reference in all_refs if reference.asset_code == identity.asset_code
            )
            security_ids = {reference.security_id for reference in candidate_refs}
            if len(security_ids) != 1 or None in security_ids:
                raise AssertionError(
                    "each synthetic asset must have one exact source-bound security ID"
                )
            security_id = next(iter(security_ids))
            if identity.security_id is not None and identity.security_id != security_id:
                raise AssertionError(
                    "an explicit requested security ID must match the bound source"
                )
            pair_refs = tuple(
                reference for reference in candidate_refs if reference.security_id == security_id
            )
            if len(pair_refs) != 4:
                raise AssertionError("every requested asset must retain its four exact source refs")
            by_kind = {reference.kind: reference for reference in pair_refs}
            valid_until = request.as_of + timedelta(minutes=30)
            valuation = _synthetic_evidence(
                reference=by_kind["valuation"],
                as_of=request.as_of,
                valid_until=valid_until,
                purpose=request.policy.industry_policy.requested_purpose,
            )
            membership_effective = request.business_date - timedelta(days=2)
            membership_evidence = _synthetic_evidence(
                reference=by_kind["industry_membership"],
                as_of=request.as_of,
                valid_until=valid_until,
                purpose=request.policy.industry_policy.requested_purpose,
                effective_on=membership_effective,
                decision_date_cutoff=request.business_date,
            )
            capacity_evidence = _synthetic_evidence(
                reference=by_kind["capacity_window"],
                as_of=request.as_of,
                valid_until=valid_until,
                purpose=request.capacity_requested_purpose,
                effective_on=request.execution_session - timedelta(days=1),
            )
            state_evidence = _synthetic_evidence(
                reference=by_kind["execution_session_state"],
                as_of=request.as_of,
                valid_until=valid_until,
                purpose=request.capacity_requested_purpose,
                effective_on=request.execution_session,
            )
            membership = IndustryMembership(
                taxonomy_id=request.policy.industry_policy.taxonomy_id,
                taxonomy_kind="industry",
                provider_id=request.policy.industry_policy.provider_id,
                provider_version=request.policy.industry_policy.provider_version,
                industry_code="SYNTHETIC_FINANCIALS",
                effective_from=membership_effective,
                effective_end_state=EffectiveEndState.OPEN,
                source_evidence=membership_evidence,
            )
            capacity = CapacityWindowObservation(
                asset_code=identity.asset_code,
                security_id=security_id,
                window_kind=request.policy.capacity_policy.window_kind,
                window_start=request.execution_session - timedelta(days=2),
                window_end=request.execution_session - timedelta(days=1),
                window_sessions=request.policy.capacity_policy.window_sessions,
                volume=CapacityValue(Decimal("100000"), "shares"),
                amount=CapacityValue(Decimal("1000000"), _MONEY_UNIT),
                execution_session_suspended=False,
                execution_session_state_date=request.execution_session,
                execution_session_state_evidence=state_evidence,
                source_evidence=capacity_evidence,
            )
            assets.append(
                PortfolioRiskAssetInputs(
                    asset_code=identity.asset_code,
                    security_id=security_id,
                    kind=PortfolioAssetKind.EQUITY,
                    price=Decimal("10.04"),
                    quantity_unit="shares",
                    price_unit=_MONEY_UNIT,
                    valuation_evidence=valuation,
                    industry_membership=membership,
                    etf_report=None,
                    capacity_observation=capacity,
                )
            )
            evidences.extend((valuation, membership_evidence, capacity_evidence, state_evidence))
        return PortfolioRiskAssetsReadResult(
            status="complete",
            assets=tuple(assets),
            all_source_evidence=tuple(evidences),
            reason_codes=(),
            policy_snapshot_id=request.policy.snapshot_id,
            policy_snapshot_hash=request.policy.snapshot_hash,
            source_reference_bindings=tuple(
                reference
                for reference in all_refs
                if any(
                    (reference.asset_code, reference.security_id)
                    == (asset.asset_code, asset.security_id)
                    for asset in assets
                )
            ),
        )


def _synthetic_evidence(
    *,
    reference: PortfolioRiskSourceReference,
    as_of: datetime,
    valid_until: datetime,
    purpose: str,
    effective_on: date | None = None,
    decision_date_cutoff: date | None = None,
) -> PortfolioRiskSourceEvidence:
    """Create one fully clocked, exact-reference-bound synthetic source fact."""

    observed_at = as_of - timedelta(minutes=1)
    available_at = as_of - timedelta(seconds=30)
    known_at = as_of - timedelta(seconds=20)
    original_body = f"synthetic vendor body:{reference.source_record_id}".encode()
    body_hash = hashlib.sha256(original_body).hexdigest()
    return PortfolioRiskSourceEvidence(
        source_id=f"synthetic-source:{reference.source_record_id}",
        source_record_id=reference.source_record_id,
        original_payload_sha256=body_hash,
        observation_precision=SourceObservationPrecision.TIMESTAMP,
        observed_at=observed_at,
        observed_on=None,
        available_at=available_at,
        known_at=known_at,
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


def _source_reference_rows() -> tuple[dict[str, object], ...]:
    """Bind all four synthetic source kinds to each exact test security pair."""

    rows: list[dict[str, object]] = []
    for asset_code, security_id in (
        (ASSET_CODE, SECURITY_ID),
        (_BUY_ASSET_CODE, _BUY_SECURITY_ID),
    ):
        for kind in (
            "valuation",
            "industry_membership",
            "capacity_window",
            "execution_session_state",
        ):
            record_id = f"ash08-{kind}-{security_id.lower().replace('.', '-')}"
            manifest_identity = f"retained manifest:{record_id}".encode()
            manifest_hash = hashlib.sha256(manifest_identity).hexdigest()
            rows.append(
                {
                    "kind": kind,
                    "asset_code": asset_code,
                    "security_id": security_id,
                    "raw_payload_hash": f"sha256:{manifest_hash}",
                    "source_record_id": record_id,
                }
            )
    return tuple(rows)


def _install_two_asset_risk_service(
    *,
    monkeypatch: pytest.MonkeyPatch,
    account_id: int,
    owner_id: int,
    calendar_reader: PortfolioRiskCalendarReader,
) -> PortfolioRiskRuntime:
    """Use real owner/ledger/audit ports and the supplied exact calendar reader."""

    references = _source_reference_rows()
    reader = _TwoAssetPolicyReader(account_id=account_id, source_references=references)
    runtime = PortfolioRiskRuntime(
        policy_reader=cast(PortfolioRiskPolicyReader, reader),
        assets_reader=cast(PortfolioRiskAssetsReader, _TwoAssetRead()),
        baseline_reader=cast(
            PortfolioBaselinePolicyReader, _TwoAssetBaselineReader(account_id=account_id)
        ),
        execution_evidence_writer=cast(
            PortfolioRiskExecutionEvidenceWriter,
            DjangoPortfolioRiskExecutionEvidenceWriter(using="default"),
        ),
        pressure_factory=cast(
            PortfolioPressureApplicationFactory, risk_fixtures._UnusedPressureFactory()
        ),
        pressure_evidence_repository=cast(ScenarioRunEvidenceReadWriteRepositoryProtocol, object()),
    )

    def build_service(using: str) -> PortfolioRiskService:
        """Bind the ordinary owner/account repositories to the real isolated database."""

        if using != "default":
            raise AssertionError("the Native plan fixture requires the owned default alias")
        from apps.simulated_trading.composition import build_observer_grant_repository

        return OwnerScopedPortfolioRiskService(
            resources=DjangoPortfolioRiskResourceRepository(
                using=using,
                observer_grant_repository=build_observer_grant_repository(using=using),
            ),
            runtime=runtime,
            clock=cast(PortfolioRiskClock, _PlanRiskClock()),
            business_timezone=ZoneInfo("Asia/Shanghai"),
            code_version="ash08-sell-buy-synthetic-risk",
            using=using,
            pressure_runner=cast(
                PortfolioRiskPressureRunner, risk_fixtures._UnusedPressureRunner()
            ),
            calendar_reader=calendar_reader,
        )

    import apps.simulated_trading.application.portfolio_risk_public as risk_public
    import apps.simulated_trading.transition_plan_journey_composition as journey_composition

    monkeypatch.setattr(risk_public, "_service_factory", build_service)
    monkeypatch.setattr(
        journey_composition,
        "get_portfolio_risk_runtime",
        lambda *, using, environment: runtime,
    )
    if owner_id <= 0:
        raise AssertionError("the exact owner identity must be available")
    return runtime


def _persist_buyer_source_snapshot(
    *,
    mapping_record: InstrumentReferenceMappingRecord,
    previous_snapshot_recorded_at: datetime,
    as_of: datetime,
    monkeypatch: pytest.MonkeyPatch,
) -> InstrumentReferenceSnapshotRecord:
    """Persist a source-bound BUY snapshot on its own one-write repository clock."""

    from apps.data_center.domain.protocols import RawAuditRepositoryProtocol
    from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
    from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository
    from apps.data_center.infrastructure.tushare_instrument_reference_source import (
        DjangoInstrumentReferenceRawAuditOccurrenceWriter,
    )

    raw_audit_repository = RawAuditRepository()
    payload_repository = RawLandingRepository()
    retainer = RetainProviderResponsePayloadUseCase(payload_repository)
    session = _TwoBankStockBasicSession()
    monkeypatch.setattr(tushare_client, "_create_requests_session", lambda: session)
    dataset_key = "fixture.instrument-reference.stock-basic"
    client = tushare_client.create_tushare_pro_client(
        token="fixture-only-token",
        http_url="https://market.example.test/pro",
        request_mode=tushare_client.TUSHARE_REQUEST_MODE_UNIFIED_RELAY,
        dataset_key=dataset_key,
        provider_response_handler=retainer.execute,
    )
    crosswalk = InstrumentReferenceExchangeSuffixCrosswalk(
        crosswalk_id="fixture.stock-basic-crosswalk",
        crosswalk_version="fixture-v1",
        exchange_suffix_pairs=(("SSE", "SH"),),
    )
    provider_contract = InstrumentReferenceProviderContract(
        contract_id="fixture.instrument-reference.stock-basic",
        contract_version="fixture-v1",
        provider_name="tushare",
        dataset_key=dataset_key,
        api_name="stock_basic",
        fields=STOCK_BASIC_FIELDS,
        exchange_scope=("SSE",),
        list_status_scope=("L", "D"),
    )
    source = TushareInstrumentReferenceSource(
        cast(TushareStockBasicClientPort, client),
        payload_repository,
        DjangoInstrumentReferenceRawAuditOccurrenceWriter(raw_audit_repository),
        provider_contract=provider_contract,
        exchange_suffix_crosswalk=crosswalk,
    )
    run_id = uuid4()
    ingested_run_id = uuid4()
    candidate1 = source.fetch_candidate(run_id=run_id, ingested_run_id=ingested_run_id)
    candidate2 = source.fetch_candidate(run_id=run_id, ingested_run_id=ingested_run_id)
    content = InstrumentReferenceSnapshotContent(
        run_id=run_id,
        mapping_record=mapping_record,
        fetch_rounds=(
            InstrumentReferenceFetchRound(fetch_round_id=uuid4(), candidate=candidate1),
            InstrumentReferenceFetchRound(fetch_round_id=uuid4(), candidate=candidate2),
        ),
    )
    if any(
        candidate.source_observed_at is not None or candidate.source_available_at is not None
        for candidate in (candidate1, candidate2)
    ):
        raise AssertionError(
            "stock_basic does not publish upstream observation/availability clocks"
        )
    if any(
        record.source_observed_at is not None or record.source_available_at is not None
        for fetch_round in content.fetch_rounds
        for record in fetch_round.candidate.records
    ):
        raise AssertionError("stock_basic rows must retain unknown source clocks")
    last_response_completed_at = content.last_response_completed_at
    snapshot_recorded_at = max(
        last_response_completed_at,
        mapping_record.recorded_at,
        previous_snapshot_recorded_at,
    ) + timedelta(seconds=1)
    if snapshot_recorded_at >= as_of:
        raise AssertionError("the BUY snapshot must be persisted before the explicit plan cutoff")
    clock_calls: list[datetime] = []

    def snapshot_clock() -> datetime:
        """Return the explicit post-capture repository knowledge time exactly once per write."""

        clock_calls.append(snapshot_recorded_at)
        return snapshot_recorded_at

    repository = DjangoInstrumentReferenceSnapshotRepository(
        cast(RawAuditRepositoryProtocol, raw_audit_repository),
        payload_repository,
        clock=snapshot_clock,
    )
    saved = SaveInstrumentReferenceSnapshotUseCase(repository).execute(content)
    if saved.recorded_at != snapshot_recorded_at:
        raise AssertionError("snapshot recorded_at must be the explicit repository clock")
    if (
        saved.recorded_at < last_response_completed_at
        or saved.recorded_at < mapping_record.recorded_at
    ):
        raise AssertionError("local persistence time must follow capture and mapping knowledge")
    if (
        saved.content.source_observed_at is not None
        or saved.content.source_available_at is not None
    ):
        raise AssertionError("local snapshot persistence must not fill upstream clocks")
    if clock_calls != [snapshot_recorded_at]:
        raise AssertionError("a new immutable snapshot consumes one repository write clock")
    if repository.get_mapping(mapping_record.mapping_record_id) != mapping_record:
        raise AssertionError(
            "exact mapping readback must not alter its original first-record clock"
        )
    if repository.get_snapshot(saved.snapshot_id) != saved:
        raise AssertionError("exact snapshot readback must not consume a new write clock")
    if clock_calls != [snapshot_recorded_at]:
        raise AssertionError("exact Data Center readbacks must not consume repository write clocks")
    if saved.content.record_count == 0 or saved.content.classify_security(_BUY_SOURCE_CODE) is None:
        raise AssertionError("the second immutable source snapshot must pin the BUY security")
    return saved


@pytest.fixture
def _prepared_buyer_source(
    persisted_source_snapshot: tuple[
        DjangoInstrumentReferenceSnapshotRepository, InstrumentReferenceSnapshotContent
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> InstrumentReferenceSnapshotRecord:
    """Persist both source identities during knowledge setup, before the execution clock."""

    repository, content = persisted_source_snapshot
    source = SaveInstrumentReferenceSnapshotUseCase(repository).execute(content)
    return _persist_buyer_source_snapshot(
        mapping_record=source.mapping_record,
        previous_snapshot_recorded_at=source.recorded_at,
        as_of=AS_OF,
        monkeypatch=monkeypatch,
    )


@pytest.fixture
def _mixed_public_order_context(
    _prepared_buyer_source: InstrumentReferenceSnapshotRecord,
    request: pytest.FixtureRequest,
) -> tuple[tuple[_QualifiedCallerContext, list[str]], InstrumentReferenceSnapshotRecord]:
    """Resolve Owner execution only after the second immutable source has been retained."""

    public_context = cast(
        tuple[_QualifiedCallerContext, list[str]],
        request.getfixturevalue("public_order_context"),
    )
    return public_context, _prepared_buyer_source


def _current_reference_item(
    record: InstrumentReferenceSnapshotRecord, *, asset_code: str, security_id: str
) -> dict[str, object]:
    """Build the exact persisted identity item consumed by the public current-reference reader."""

    return {
        "security_id": security_id,
        "asset_code": asset_code,
        "source_code": asset_code,
        "snapshot_id": str(record.snapshot_id),
        "snapshot_content_hash": record.content_hash,
        "snapshot_record_digest": record.record_digest,
        "mapping_record_id": str(record.mapping_record.mapping_record_id),
        "mapping_id": record.mapping_record.content.mapping_id,
        "mapping_version": record.mapping_record.content.mapping_version,
        "mapping_content_hash": record.mapping_record.content_hash,
        "mapping_record_digest": record.mapping_record.record_digest,
        "simulated_asset_type": "equity",
    }


def _activate_two_asset_current_reference(
    *,
    context: _QualifiedCallerContext,
    buyer_record: InstrumentReferenceSnapshotRecord,
) -> None:
    """Bind both persisted snapshot identities and ordinary Sina policies as one profile patch."""

    from tests.component.simulated_trading.test_owner_order_submission_api import _policy

    selection = {
        "schema": "normal-simulated-current-reference-selection.v2",
        "purpose": "normal_simulated_current_reference",
        "max_local_reference_age_seconds": 600,
        "items": [
            _current_reference_item(context.source, asset_code=ASSET_CODE, security_id=SECURITY_ID),
            _current_reference_item(
                buyer_record, asset_code=_BUY_ASSET_CODE, security_id=_BUY_SECURITY_ID
            ),
        ],
    }
    base_rule = context.uow.rule_bundle.execution_submission_v2.execution_rule_v1
    buyer_policy = replace(
        _policy(),
        security_id=_BUY_SECURITY_ID,
        asset_code=_BUY_ASSET_CODE,
        market=base_rule.market,
        board=base_rule.board,
        effective_from=TRADE_DATE,
        effective_until=TRADE_DATE,
        content_hash="",
    )
    from apps.config_center.application.runtime_public import activate_runtime_profile_patch

    with _write_clock():
        activate_runtime_profile_patch(
            environment="development",
            patch={
                _CURRENT_REFERENCE_SELECTION_KEY: selection,
                SINA_SUBMISSION_POLICIES_KEY: {
                    "policies": [
                        _current_sina_policy(context).to_payload(),
                        buyer_policy.to_payload(),
                    ]
                },
            },
            actor="test-ash08-sell-buy-source-pairs",
            reason="bind two exact synthetic stock-basic identities and current local quotes",
        )


def _current_sina_policy(context: _QualifiedCallerContext) -> LocalSimulatedMarketPolicy:
    """Rebuild the already active A policy from the fixture's exact rule identity."""

    from tests.component.simulated_trading.test_owner_order_submission_api import _policy

    rule = context.uow.rule_bundle.execution_submission_v2.execution_rule_v1
    return replace(
        _policy(),
        security_id=SECURITY_ID,
        asset_code=ASSET_CODE,
        market=rule.market,
        board=rule.board,
        effective_from=TRADE_DATE,
        effective_until=TRADE_DATE,
        content_hash="",
    )


def _install_two_quote_capture(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    """Supply typed Sina captures for both exact securities through the regular order path."""

    from apps.data_center.domain.sina_quote_capture import (
        build_sina_quote_request_url,
        parse_sina_quote_capture,
    )
    from apps.simulated_trading import owner_order_submission_composition

    def capture(asset_code: str) -> object:
        """Return an explicitly synthetic but fully typed local quote capture."""

        calls.append(asset_code)
        if asset_code == ASSET_CODE:
            body = market_fixture._body(source_date=TRADE_DATE.isoformat(), source_time="09:59:59")
        elif asset_code == _BUY_ASSET_CODE:
            body = (
                market_fixture._body(source_date=TRADE_DATE.isoformat(), source_time="09:59:59")
                .replace(b"sh600000", b"sh601398")
                .replace("浦发银行".encode("gb18030"), "Synthetic BUY bank".encode("gb18030"))
            )
        else:
            raise AssertionError("the order market requested an unbound asset")
        url = build_sina_quote_request_url(asset_code)
        return parse_sina_quote_capture(
            asset_code=asset_code,
            requested_url=url,
            final_url=url,
            request_started_at=AS_OF - timedelta(milliseconds=200),
            response_completed_at=AS_OF - timedelta(milliseconds=100),
            http_status=200,
            http_date=None,
            content_type="application/javascript; charset=GB18030",
            charset="GB18030",
            content_encoding=None,
            body=body,
        )

    monkeypatch.setattr(owner_order_submission_composition, "capture_sina_quote", capture)


def _risk_service_fixture(
    *,
    context: _QualifiedCallerContext,
    monkeypatch: pytest.MonkeyPatch,
) -> PortfolioRiskRuntime:
    """Install real identity/calendar ports with typed synthetic portfolio-risk facts."""

    return _install_two_asset_risk_service(
        monkeypatch=monkeypatch,
        account_id=context.account.pk,
        owner_id=context.owner_id,
        calendar_reader=build_portfolio_risk_calendar_reader(
            identity_reader=context.uow.identity_reader,
            calendar_reader=build_configured_execution_calendar_reader(
                runtime_environment=get_simulated_execution_runtime_environment(),
                read_publication=read_current_exchange_calendar_reference,
                read_configuration=read_calendar_capture_configuration_reference_at,
            ),
        ),
    )


def _preview_builder_factory(
    *,
    price_reader: _SyntheticMarketPriceProvider,
) -> object:
    """Create the actual production preview builder with only its market quote port synthetic."""

    from apps.risk_center.execution_settlement_composition import (
        build_execution_settlement_v3_rule_reader,
    )
    from apps.risk_center.m1_rebalance_risk_policy_composition import (
        build_m1_risk_policy_application,
    )
    from apps.simulated_trading.infrastructure.m1_risk_policy_account_source_reader import (
        DjangoM1RiskPolicyAccountSourceReader,
    )
    from apps.simulated_trading.m1_risk_policy_composition import (
        build_strategy_m1_risk_source_reader,
    )

    risk_policy_application = build_m1_risk_policy_application(using="default")

    def factory(*, reference_price_basis: str) -> ReadOnlyRebalancePlanPreviewBuilder:
        """Bind real selector/classification/fee/rule/resource readers for this inspection."""

        return ReadOnlyRebalancePlanPreviewBuilder(
            price_reader=price_reader,
            identity_reader=build_current_reference_identity_reader(
                runtime_environment="development"
            ),
            classification_reader=build_current_reference_classification_reader(
                runtime_environment="development"
            ),
            fee_policy_reader=DjangoFeePolicyV2Repository(using="default"),
            quantity_rule_reader=build_execution_settlement_v3_rule_reader(),
            resource_snapshot_reader=DjangoRebalanceResourceSnapshotRepository(using="default"),
            position_rule_evaluator=get_strategy_execution_gateway(),
            reference_price_basis=cast(str, reference_price_basis),
            portfolio_risk_gate=None,
            risk_policy_qualifier=risk_policy_application.qualify,
            risk_policy_account_source_reader=DjangoM1RiskPolicyAccountSourceReader(
                using="default"
            ),
            strategy_risk_source_reader=build_strategy_m1_risk_source_reader(),
        )

    return factory


class _ObservedJourneyReads(ServerRebalanceJourneyReads):
    """Retain real risk diagnostics without changing any qualified context or admission."""

    diagnostic_root: Path
    diagnostic_sequence: int = 0

    def read_risk(
        self, *, user_id: int, account_id: int, preview: RebalancePlanPreview
    ) -> PreparedPortfolioRisk:
        """Return the production result unchanged and retain its explained risk outcome."""

        prepared = super().read_risk(user_id=user_id, account_id=account_id, preview=preview)
        self.diagnostic_sequence += 1
        diagnostic = {
            "report": prepared.report,
            "preview": preview.to_payload(),
            "assets_status": prepared.assets.status,
            "assets_reason_codes": prepared.assets.reason_codes,
            "baseline_reason_codes": prepared.baseline_source.reason_codes,
            "calendar_requested_session_qualified": prepared.calendar.requested_session_qualified,
            "calendar_open_sessions": prepared.calendar.open_sessions,
            "calendar_evidence_hash": prepared.calendar.evidence_hash,
            "calendar_canonical_evidence_json": prepared.calendar.canonical_evidence_json,
            "calendar_valid_until": prepared.calendar.valid_until,
        }
        (self.diagnostic_root / f"risk-{self.diagnostic_sequence}.json").write_text(
            json.dumps(diagnostic, indent=2, default=str), encoding="utf-8"
        )
        return prepared


def _revision_request(
    *, context: _QualifiedCallerContext, key: str
) -> TransitionPlanRevisionRequest:
    """Build the same target/selection hashes the public journey service pins."""

    targets = parse_temporary_security_targets(_TARGET_WEIGHTS)
    target_payload: dict[str, object] = {
        "weights": targets.exact_weight_strings(),
        "residual_cash_weight": str(targets.residual_cash_weight),
    }
    target_id = _canonical_hash(target_payload)
    selection_id = "temporary_security_targets:market"
    selection_hash = _canonical_hash({"target": target_payload, "reference_price_basis": "market"})
    return TransitionPlanRevisionRequest(
        actor_user_id=context.owner_id,
        account_id=context.account.pk,
        target_portfolio_id=target_id,
        selection_id=selection_id,
        expected_selection_hash=selection_hash,
        idempotency_key=key,
    )


def _plan_order(
    revision: TransitionPlanRevision, *, code: str, side: str
) -> TransitionPlanOrderBinding:
    """Return exactly one immutable revision binding for the requested target action."""

    matches = tuple(
        item for item in revision.orders if item.asset_code == code and item.side == side
    )
    if len(matches) != 1:
        raise AssertionError(f"expected one exact {side} binding for {code}, found {len(matches)}")
    return matches[0]


def _plan_command(
    *,
    revision: TransitionPlanRevision,
    context: _QualifiedCallerContext,
    binding: TransitionPlanOrderBinding,
    quantity: Decimal,
    attempt: str,
) -> PlanOrderPreviewCommand:
    """Bind one order request to its complete immutable revision and order hashes."""

    return PlanOrderPreviewCommand(
        actor_user_id=context.owner_id,
        account_id=context.account.pk,
        plan_id=revision.identity.plan_id,
        plan_version=revision.identity.version,
        expected_revision_hash=revision.identity.revision_hash,
        order_ordinal=binding.ordinal,
        expected_order_content_hash=binding.order_content_hash,
        expected_plan_order_binding_id=binding.plan_order_binding_id,
        action_attempt_key=attempt,
        quantity=quantity,
        price=Decimal("10.04"),
        reason="synthetic Native SELL-to-BUY funding journey",
    )


def _order_services(*, revision: TransitionPlanRevision):
    """Use production current-pin, owner-risk, calendar and ordinary order guards."""

    validator = build_journey_current_policy_pins_validator(using="default")
    guard = build_transition_plan_locked_guard(
        using="default",
        current_policy_pins_validator=validator,
    )
    order_service = build_owner_order_submission_use_case(
        market_purpose="local_simulation_only",
        transition_plan_guard=guard,
    )
    preview_service = PreviewTransitionPlanOrderUseCase(
        revision_reader=build_transition_plan_exact_reader(using="default"),
        order_submission=order_service,
        clock=DjangoTransitionPlanRevisionRepository(using="default"),
    )
    return order_service, preview_service


def _assert_asset_cash(
    *, account: SimulatedAccountModel, position: PositionModel, cash: Decimal, quantity: Decimal
) -> None:
    """Assert the exact persisted account cash and surviving position after a fill."""

    account.refresh_from_db()
    position.refresh_from_db()
    assert account.current_cash == cash
    assert position.quantity == quantity
    assert position.available_quantity == quantity


def test_real_preview_partial_sell_funds_only_actual_successor_buy(
    _mixed_public_order_context: tuple[
        tuple[_QualifiedCallerContext, list[str]], InstrumentReferenceSnapshotRecord
    ],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    django_db_use_migrations: bool,
    preserve_account_authority_generation: None,
    isolated_m1_revision_table: None,
) -> None:
    """Generate real immutable plans while isolating M1 rows from teardown flush."""

    if not django_db_use_migrations:
        pytest.skip("the owner SELL-to-BUY journey requires the migrated Native test database")
    assert_native_postgres_test_database()
    del preserve_account_authority_generation
    del isolated_m1_revision_table
    public_context, buyer_record = _mixed_public_order_context
    context, _ = public_context
    account = context.account
    position = _persist_sell_position(account)
    position.quantity = Decimal("350.000000")
    position.available_quantity = Decimal("350.000000")
    position.avg_cost = Decimal("10.0000")
    position.total_cost = Decimal("3500.00")
    position.current_price = Decimal("10.0400")
    position.market_value = Decimal("3514.00")
    position.unrealized_pnl = Decimal("14.00")
    position.unrealized_pnl_pct = 0.4
    position.save()
    account.current_cash = Decimal("500.00")
    account.initial_capital = Decimal("500.00")
    account.current_market_value = Decimal("3514.00")
    account.total_value = Decimal("4014.00")
    account.max_position_pct = 95.0
    account.max_total_position_pct = 95.0
    account.cash_known = True
    account.cash_reconciliation_status = "simulated_ledger"
    account.save()

    from rest_framework.test import APIClient

    from tests.integration.simulated_trading.test_readonly_rebalance_plan_owner_api import (
        _publish_m1_policy_for_preview,
    )

    m1_policy_version = _publish_m1_policy_for_preview(
        monkeypatch,
        client=APIClient(),
        owner=account.user,
        account=account,
        strategy=None,
    )
    assert m1_policy_version
    assert account.user_id == context.owner_id
    assert django_timezone.now().astimezone(UTC) <= AS_OF

    classification = buyer_record.content.classify_security(_BUY_SOURCE_CODE)
    assert classification is not None and classification.blocked_reason is None
    assert classification.rule_market is not None and classification.board is not None
    buyer_bundle = _seed_rule_bundle(
        security_id=_BUY_SECURITY_ID,
        market=classification.rule_market,
        board=classification.board,
    )
    assert buyer_bundle.execution_submission_v2.execution_rule_v1.security_id == _BUY_SECURITY_ID
    _activate_two_asset_current_reference(context=context, buyer_record=buyer_record)
    _install_two_quote_capture(monkeypatch, [])
    _risk_service_fixture(context=context, monkeypatch=monkeypatch)

    reads = _ObservedJourneyReads(
        preview_builder_factory=cast(
            object,
            _preview_builder_factory(
                price_reader=_SyntheticMarketPriceProvider(
                    price=Decimal("10.04"), observed_at=AS_OF - timedelta(seconds=1)
                )
            ),
        ),
        fee_reader=DjangoFeePolicyV2Repository(using="default"),
        quantity_rule_reader=cast(
            object,
            __import__(
                "apps.risk_center.execution_settlement_composition",
                fromlist=["build_execution_settlement_v3_rule_reader"],
            ).build_execution_settlement_v3_rule_reader(),
        ),
        using="default",
    )
    reads.diagnostic_root = tmp_path
    provider = PortfolioJourneyPreparationProvider(
        reads,
        target_weights=_TARGET_WEIGHTS,
        reference_price_basis="market",
        business_timezone=ZoneInfo("Asia/Shanghai"),
    )
    from apps.simulated_trading.composition import build_observer_grant_repository
    from apps.simulated_trading.infrastructure.portfolio_risk_resource_repository import (
        DjangoPortfolioRiskResourceRepository,
    )

    resource_reader = DjangoPortfolioRiskResourceRepository(
        using="default",
        observer_grant_repository=build_observer_grant_repository(using="default"),
    )
    authorizer = RebalanceJourneyAccountAuthorizer(resource_reader)
    repository = DjangoTransitionPlanRevisionRepository(using="default")
    initial_use_case = CreateInitialTransitionPlanRevisionUseCase(
        repository=repository,
        preparation_provider=provider,
        authorizer=authorizer,
        clock=repository,
    )
    successor_use_case = CreateTransitionPlanSuccessorUseCase(
        repository=repository,
        preparation_provider=provider,
        authorizer=authorizer,
        clock=repository,
    )

    initial = initial_use_case.execute(
        _revision_request(context=context, key=f"ash08-sell-buy-initial-{uuid4().hex}")
    )
    assert initial.basis.account_id == account.pk
    assert initial.basis.owner_user_id == context.owner_id
    assert initial.basis.preparation_evidence_json
    initial_sell = _plan_order(initial, code=ASSET_CODE, side="sell")
    initial_buy = _plan_order(initial, code=_BUY_ASSET_CODE, side="buy")
    assert initial_sell.requested_quantity == 300
    assert initial_sell.approved_quantity == 300
    assert initial_buy.requested_quantity == 101
    assert initial_buy.approved_quantity == 0
    assert initial_buy.unapproved_quantity == 101
    assert "BUY_DEPENDS_ON_SETTLED_SALES" in initial_buy.reason_codes

    order_service, preview_service = _order_services(revision=initial)
    cash_before = account.current_cash
    reservation_count = SimulatedOrderReservationModel.objects.filter(account_id=account.pk).count()
    with pytest.raises(SimulatedTradeExecutionBlocked):
        preview_service.execute(
            _plan_command(
                revision=initial,
                context=context,
                binding=initial_buy,
                quantity=Decimal("100"),
                attempt="initial-buy-must-not-borrow-unsettled-sell-proceeds",
            )
        )
    account.refresh_from_db()
    assert account.current_cash == cash_before
    assert (
        SimulatedOrderReservationModel.objects.filter(account_id=account.pk).count()
        == reservation_count
    )

    sell_preview = preview_service.execute(
        _plan_command(
            revision=initial,
            context=context,
            binding=initial_sell,
            quantity=Decimal("300"),
            attempt="initial-sell-300",
        )
    )
    assert sell_preview.binding.revision_hash == initial.identity.revision_hash
    assert sell_preview.preview.result.reservation.status.value == "active"
    confirmed = order_service.confirm(
        account_id=account.pk,
        user_id=context.owner_id,
        token=sell_preview.preview.token,
        confirmed=True,
        expected_key=sell_preview.preview.result.reservation.identity.idempotency_key,
        market_purpose="local_simulation_only",
    )
    reservation = SimulatedOrderReservationModel.objects.get(pk=confirmed.order_id)
    assert reservation.quantity == Decimal("300")
    assert reservation.plan_snapshot["transition_plan_binding"]["binding"]["revision_hash"] == (
        initial.identity.revision_hash
    )
    assert account.current_cash == cash_before

    fill_at = AS_OF + timedelta(seconds=3)
    advance_auto_uow_fixture_clocks(monkeypatch, as_of=fill_at)
    fill_event = LocalSimulatedFillEventV1(
        source_namespace="ash08.synthetic.sell-buy-fill",
        source_version="fixture-v1",
        source_event_id=f"partial-{uuid4().hex}",
        event_payload_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
        source_snapshot_id="ash08-explicit-synthetic-fill-source",
        source_snapshot_hash=hashlib.sha256(b"ash08 synthetic fill source").hexdigest(),
        reservation_id=reservation.pk,
        account_id=account.pk,
        user_id=context.owner_id,
        order_idempotency_key=reservation.idempotency_key,
        intent_payload_hash=reservation.intent_payload_hash,
        reservation_request_hash=reservation.reservation_request_hash,
        plan_snapshot_hash=reservation.plan_snapshot_hash,
        security_id=reservation.security_id,
        asset_code=reservation.asset_code,
        side=SimulatedTradeSide.SELL,
        event_kind=LocalSimulatedFillEventKind.FILL,
        quantity=Decimal("100"),
        price=Decimal("10.04"),
        occurred_at=fill_at,
        source_observed_at=fill_at,
        source_available_at=fill_at,
        recorded_at=fill_at,
    )
    settlement_proof = build_order_fill_settlement_proof(
        calendar_evidence=context.uow.calendar_evidence,
        calendar_read_cutoff=fill_at,
        fill_occurred_at=fill_at,
        settlement_exchange=context.uow.calendar_evidence.snapshot.exchange,
        settlement_lag_sessions=context.uow.rule_bundle.settlement_policy_v1.settlement_lag_sessions,
    )
    fill = DjangoSimulatedOrderFillRepository(
        event_reader=_EventReader(fill_event, []), using="default"
    ).apply_fill_event(
        event=fill_event,
        expected_event_payload_hash=fill_event.event_payload_hash,
        settlement_proof=settlement_proof,
        clock=_FixedClock(fill_at),
    )
    assert fill.replayed is False
    assert fill.reservation.filled_quantity == Decimal("100")
    assert fill.reservation.remaining_shares == Decimal("200")
    trade = SimulatedTradeModel.objects.get(pk=fill.trade_id)
    receipt = SimulatedOrderFillReceiptModel.objects.get(trade_id=trade.pk)
    fees = fill.economics.incremental_fees
    assert fees.total_fee > 0
    assert trade.account_id == account.pk
    assert trade.asset_code == ASSET_CODE
    assert trade.action == "sell"
    assert trade.quantity == Decimal("100")
    assert trade.amount == Decimal("1004.00")
    assert trade.commission == fees.commission
    assert trade.transfer_fee == fees.transfer_fee
    assert trade.stamp_duty == fees.stamp_duty
    assert trade.slippage == fees.slippage
    assert trade.total_cost == fees.total_fee
    assert receipt.reservation_id == reservation.pk
    assert receipt.source_event_id == fill_event.source_event_id
    assert receipt.source_event_payload_hash == fill_event.event_payload_hash
    expected_cash = cash_before + fill.economics.gross_amount - fees.total_fee
    _assert_asset_cash(
        account=account, position=position, cash=expected_cash, quantity=Decimal("250")
    )

    advance_auto_uow_fixture_clocks(monkeypatch, as_of=fill_at + timedelta(seconds=2))
    from apps.simulated_trading.application.order_reservation import (
        CancelSimulatedOrderReservationUseCase,
    )

    cancelled = CancelSimulatedOrderReservationUseCase(
        repository=DjangoSimulatedOrderReservationRepository(using="default"),
        clock=_FixedClock(fill_at + timedelta(seconds=2)),
    ).execute(
        account_id=account.pk,
        user_id=context.owner_id,
        idempotency_key=reservation.idempotency_key,
    )
    assert cancelled.status.value == "cancelled"
    assert cancelled.filled_quantity == Decimal("100")
    assert cancelled.remaining_shares == Decimal("0")
    position.refresh_from_db()
    assert position.available_quantity == Decimal("250")
    account.refresh_from_db()
    assert account.current_cash == expected_cash

    successor_request = _revision_request(
        context=context, key=f"ash08-sell-buy-successor-{uuid4().hex}"
    )
    successor = successor_use_case.execute(
        CreateTransitionPlanSuccessorCommand(
            request=successor_request,
            expected_parent_plan_id=initial.identity.plan_id,
            expected_parent_version=initial.identity.version,
            expected_parent_revision_hash=initial.identity.revision_hash,
        )
    )
    assert successor.identity.family_id == initial.identity.family_id
    assert successor.identity.version == initial.identity.version + 1
    assert successor.identity.parent_plan_id == initial.identity.plan_id
    assert successor.identity.parent_revision_hash == initial.identity.revision_hash
    assert successor.identity.revision_hash != initial.identity.revision_hash
    assert _plan_order(initial, code=_BUY_ASSET_CODE, side="buy").approved_quantity == 0
    successor_sell = _plan_order(successor, code=ASSET_CODE, side="sell")
    successor_buy = _plan_order(successor, code=_BUY_ASSET_CODE, side="buy")
    assert successor_sell.approved_quantity == 200
    assert successor_sell.unapproved_quantity == 0
    assert successor_sell.requested_quantity > 0
    assert successor_buy.approved_quantity == 100
    assert successor_buy.unapproved_quantity == (
        successor_buy.requested_quantity - successor_buy.approved_quantity
    )
    assert Decimal("0") <= successor_buy.unapproved_quantity < Decimal("100")
    assert "BUY_DEPENDS_ON_SETTLED_SALES" not in successor_buy.reason_codes
    assert successor.plan.as_of_time == successor.basis.portfolio_snapshot_as_of
    assert initial.identity.revision_hash != successor.identity.revision_hash
    initial_readback = DjangoTransitionPlanRevisionRepository(using="default").get_exact(
        plan_id=initial.identity.plan_id,
        version=initial.identity.version,
        expected_revision_hash=initial.identity.revision_hash,
        as_of=fill_at + timedelta(seconds=3),
    )
    assert initial_readback is not None
    assert initial_readback == initial
    assert initial_readback.orders == initial.orders

    successor_order_service, successor_preview_service = _order_services(revision=successor)
    buy_preview = successor_preview_service.execute(
        _plan_command(
            revision=successor,
            context=context,
            binding=successor_buy,
            quantity=Decimal("100"),
            attempt="successor-buy-after-real-partial-fill",
        )
    )
    assert buy_preview.binding.revision_hash == successor.identity.revision_hash
    assert buy_preview.preview.result.reservation.status.value == "active"
    confirmed_buy = successor_order_service.confirm(
        account_id=account.pk,
        user_id=context.owner_id,
        token=buy_preview.preview.token,
        confirmed=True,
        expected_key=buy_preview.preview.result.reservation.identity.idempotency_key,
        market_purpose="local_simulation_only",
    )
    buy_reservation = SimulatedOrderReservationModel.objects.get(pk=confirmed_buy.order_id)
    assert buy_reservation.quantity == Decimal("100")
    assert buy_reservation.asset_code == successor_buy.asset_code == _BUY_ASSET_CODE
    assert buy_reservation.security_id == successor_buy.security_id == _BUY_SECURITY_ID
    assert buy_reservation.side == successor_buy.side == "buy"
    persisted_plan_binding = buy_reservation.plan_snapshot["transition_plan_binding"]["binding"]
    assert persisted_plan_binding["revision_hash"] == successor.identity.revision_hash
    assert persisted_plan_binding["plan_order_binding_id"] == successor_buy.plan_order_binding_id
    assert persisted_plan_binding["order_content_hash"] == successor_buy.order_content_hash
    assert persisted_plan_binding["asset_code"] == _BUY_ASSET_CODE
    assert persisted_plan_binding["security_id"] == _BUY_SECURITY_ID
    assert persisted_plan_binding["side"] == "buy"
    assert buy_reservation.notional == buy_reservation.quantity * buy_reservation.limit_price
    assert buy_reservation.fee_estimate > Decimal("0")
    assert buy_reservation.fee_estimate == (
        buy_reservation.commission_estimate
        + buy_reservation.transfer_fee_estimate
        + buy_reservation.stamp_duty_estimate
        + buy_reservation.slippage_estimate
    )
    assert buy_reservation.fee_budget is not None
    assert buy_reservation.fee_budget >= buy_reservation.fee_estimate
    assert buy_reservation.cash_reserved == buy_reservation.notional + buy_reservation.fee_budget
    account.refresh_from_db()
    assert account.current_cash == expected_cash
    unspent_cash = (
        buy_reservation.cash_reserved
        - buy_reservation.cash_consumed
        - buy_reservation.cash_released
    )
    assert buy_reservation.cash_consumed == Decimal("0")
    assert buy_reservation.cash_released == Decimal("0")
    assert unspent_cash == buy_reservation.cash_reserved
    assert Decimal("0") < unspent_cash <= expected_cash
