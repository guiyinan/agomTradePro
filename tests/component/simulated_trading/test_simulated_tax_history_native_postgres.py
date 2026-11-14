"""Native PostgreSQL proof for read-only simulated tax history.

The local market calendar, exchange-timezone policy, and aggregate record-date
entitlement below are controlled typed test fixtures. The Config Center rule,
owner account and zero anchor, local match decision, and V4 fill receipt are
read or written through their real persisted interfaces. This test makes no
claim of real custody, official market coverage, or legal qualification.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, tzinfo
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.test import override_settings
from django.utils import timezone

import apps.simulated_trading.corporate_action_tax_settlement_history_composition as history_composition
import tests.component.simulated_trading.test_execution_settlement_uow as execution_fixtures
import tests.component.simulated_trading.test_local_daily_match_repository as match_fixtures
import tests.component.simulated_trading.test_order_reservation_fill_repository as fill_fixtures
import tests.support.ash07_owner_account_authority as owner_fixtures
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.config_center.application.runtime_value_evidence import (
    read_active_runtime_value_evidence,
)
from apps.simulated_trading.application.corporate_action_tax_settlement_history import (
    SimulatedTaxSettlementHistoryQuery,
)
from apps.simulated_trading.application.local_daily_match import (
    LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
    LocalDailyMatchCommand,
    LocalMatchOutcome,
    RecordLocalDailyMatchUseCase,
    stable_local_daily_observation_id,
)
from apps.simulated_trading.application.order_reservation import ReserveSimulatedOrderUseCase
from apps.simulated_trading.corporate_action_tax_date_convention_composition import (
    SIMULATED_TAX_DATE_CONVENTION_KEY,
)
from apps.simulated_trading.domain.corporate_action_tax_settlement_evidence import (
    RecordDateTaxEntitlementEvidence,
    RecordDateTaxEntitlementRuleKind,
)
from apps.simulated_trading.domain.execution_settlement_calendar import ExecutionCalendarEvidence
from apps.simulated_trading.domain.initial_position_mark import InitialPositionMarkProof
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    build_order_fill_settlement_proof,
)
from apps.simulated_trading.infrastructure.corporate_action_ownership_history_repository import (
    DjangoCorporateActionOwnershipHistoryRepository,
    QualifiedExchangeTimezone,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel,
)
from apps.simulated_trading.infrastructure.local_daily_match_event_reader import (
    DjangoLocalDailyMatchEventReader,
)
from apps.simulated_trading.infrastructure.local_daily_match_models import LocalDailyMatchModel
from apps.simulated_trading.infrastructure.local_daily_match_repository import (
    DjangoLocalDailyMatchRepository,
)
from apps.simulated_trading.infrastructure.models import (
    FeeConfigModel,
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_row_reader import (
    read_order_reservation_fill_row,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.order_reservation_repository import (
    DjangoSimulatedOrderReservationRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_ownership_anchor_models import (
    SimulatedAccountOwnershipAnchorModel,
)
from shared.config.secrets import get_secrets
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness,
    _intent_for,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash07_owner_account_authority import (
    ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
    create_owner_account_seed,
)
from tests.support.runtime_config import configure_critical_runtime
from tests.support.synthetic_trade_tax_coverage import SyntheticTradeTaxCoverage

pytestmark = [
    pytest.mark.django_db(
        transaction=True,
        available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
    ),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="Native migrated history/source-reader integration requires PostgreSQL.",
    ),
]

_EXCHANGE = "SH"
_TIMEZONE = "Asia/Shanghai"
_SECURITY_ID = "SH.UOW.SECURITY"
_ASSET_CODE = "600000.SH"
_SETTLEMENT_LAG = 2
_TAX_PURCHASE_OFFSET = 1


@pytest.fixture
def _native_encryption_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Supply and clear the existing Account fixture's test-only encryption secret."""

    monkeypatch.setenv(
        "AGOMTRADEPRO_ENCRYPTION_KEY",
        base64.urlsafe_b64encode(b"t" * 32).decode("ascii"),
    )
    get_secrets.cache_clear()
    try:
        yield
    finally:
        get_secrets.cache_clear()


@dataclass(frozen=True, slots=True)
class _FixedClock:
    """Supply one explicit operation clock without replacing persisted sources."""

    value: datetime

    def now(self) -> datetime:
        """Return the configured aware instant."""

        return self.value


@dataclass(frozen=True, slots=True)
class _ControlledTimezonePolicyReader:
    """Provide a labeled timezone fixture to the real ownership-history reader."""

    def read_exchange_timezone_policy(
        self,
        *,
        exchange: str,
        as_of: datetime,
    ) -> QualifiedExchangeTimezone:
        """Return only the exact synthetic exchange binding used by this test."""

        assert exchange == _EXCHANGE
        assert as_of.tzinfo is not None and as_of.utcoffset() is not None
        return QualifiedExchangeTimezone(
            exchange=_EXCHANGE,
            timezone_name=_TIMEZONE,
            policy_id="native-tax-history-controlled-timezone.v1",
            policy_sha256="a" * 64,
        )


@dataclass(frozen=True, slots=True)
class _ControlledCalendarReader:
    """Return one complete, labeled local session fixture to the real use case."""

    evidence: ExecutionCalendarEvidence

    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> ExecutionCalendarEvidence:
        """Validate the exact requested exchange, cutoff, and anchor coverage."""

        assert exchange == _EXCHANGE
        assert coverage_start is not None
        assert self.evidence.snapshot.coverage_start <= coverage_start
        self.evidence.validate_for(as_of)
        return self.evidence


def _read_only_snapshot(account_id: int) -> tuple[object, ...]:
    """Capture financial, assessment, Audit, and Outbox state around one read."""

    account = SimulatedAccountModel.objects.get(pk=account_id)
    positions = tuple(
        PositionModel.objects.filter(account_id=account_id)
        .order_by("pk")
        .values_list(
            "pk",
            "asset_code",
            "quantity",
            "available_quantity",
            "total_cost",
            "market_value",
        )
    )
    trades = tuple(
        SimulatedTradeModel.objects.filter(account_id=account_id)
        .order_by("pk")
        .values_list("pk", "quantity", "price", "settlement_release_date")
    )
    receipts = tuple(
        SimulatedOrderFillReceiptModel.objects.filter(trade__account_id=account_id)
        .order_by("pk")
        .values_list("pk", "receipt_hash", "source_event_payload_hash")
    )
    return (
        account.current_cash,
        account.current_market_value,
        account.total_value,
        account.total_trades,
        positions,
        trades,
        receipts,
        SimulatedOrderReservationModel.objects.filter(account_id=account_id).count(),
        CorporateActionPostingModel.objects.filter(account_id=account_id).count(),
        CorporateActionTaxAssessmentHeaderModel._base_manager.filter(account_id=account_id).count(),
        SystemAuditEventModel._base_manager.count(),
        SystemAuditOutboxModel._base_manager.count(),
    )


def test_native_simulated_history_uses_explicit_tax_dates_and_only_reads_persisted_sources(
    monkeypatch: pytest.MonkeyPatch,
    _native_encryption_secret: None,
    preserve_account_authority_generation: None,
) -> None:
    """Read a real owner fill through Config Center and preserve all ledgers."""

    del _native_encryption_secret, preserve_account_authority_generation
    assert connection.vendor == "postgresql"
    actual_clock = timezone.now
    actual_read_time = actual_clock()
    anchor_creation_time = actual_read_time - timedelta(days=8)
    monkeypatch.setattr(timezone, "now", _FixedClock(anchor_creation_time).now)
    configure_critical_runtime()

    class _HistoricalSeedClock:
        """Keep the helper's independent datetime cutoff on the declared test clock."""

        @staticmethod
        def now(tz: tzinfo | None = None) -> datetime:
            return (
                anchor_creation_time.astimezone(tz)
                if tz is not None
                else anchor_creation_time.replace(tzinfo=None)
            )

    with monkeypatch.context() as seed_clock:
        seed_clock.setattr(owner_fixtures, "datetime", _HistoricalSeedClock)
        with override_settings(ROOT_URLCONF="tests.support.ash07_owner_source_test_urls"):
            owner_seed = create_owner_account_seed()
    account = owner_seed.account
    assert type(account.pk) is int and type(owner_seed.owner.pk) is int
    assert owner_seed.binding.underlying_unified_account_id_claim == account.pk
    canonical_account_id = owner_seed.binding.account_id_claim
    assert canonical_account_id

    anchor = SimulatedAccountOwnershipAnchorModel.objects.get(account_id=account.pk)
    assert anchor.owner_user_id == owner_seed.owner.pk
    assert anchor.quantity == Decimal("0.000000")

    reserve_as_of = actual_read_time - timedelta(days=7)
    monkeypatch.setattr(timezone, "now", _FixedClock(reserve_as_of).now)
    anchor_date = anchor.account_created_at.astimezone(ZoneInfo(_TIMEZONE)).date()
    reserve_date = reserve_as_of.astimezone(ZoneInfo(_TIMEZONE)).date()
    record_date = reserve_date + timedelta(days=3)
    complete_through = reserve_date + timedelta(days=4)
    calendar_start = min(anchor_date, reserve_date)
    calendar_dates = tuple(
        calendar_start + timedelta(days=offset)
        for offset in range((complete_through - calendar_start).days + 1)
    )
    calendar_evidence = execution_fixtures._calendar(
        as_of=reserve_as_of,
        open_dates=set(calendar_dates),
        exchange=_EXCHANGE,
        start=calendar_start,
        end=complete_through,
    )

    fee_row = FeeConfigModel.objects.create(
        config_name=f"native-tax-history-{uuid4().hex}",
        asset_type="equity",
        commission_rate_buy=0.0003,
        commission_rate_sell=0.0003,
        min_commission=1.0,
        stamp_duty_rate=0.001,
        transfer_fee_rate=0.00002,
        min_transfer_fee=0.0,
        slippage_rate=0.001,
        is_default=False,
        is_active=False,
    )
    monkeypatch.setattr(execution_fixtures, "AS_OF", reserve_as_of)
    execution_fixtures._seed_fee_policy(fee_row)
    preparer, rule_reader, _ = execution_fixtures._execute_use_case(
        account_id=account.pk,
        user_id=owner_seed.owner.pk,
        as_of=reserve_as_of,
        evidence=calendar_evidence,
        lag=_SETTLEMENT_LAG,
    )
    # Controlled seed admission; the later history/qualification reads remain real.
    seed_tax_coverage = SyntheticTradeTaxCoverage()
    reservation_repository = DjangoSimulatedOrderReservationRepository(
        using="default", tax_cash_coverage_reader=seed_tax_coverage
    )
    reservation_harness = _Harness(
        account=account,
        user_id=owner_seed.owner.pk,
        repository=reservation_repository,
        preparer=preparer,
        reserve=ReserveSimulatedOrderUseCase(
            preparer=preparer,
            repository=reservation_repository,
            clock=_FixedClock(reserve_as_of),
        ),
        rule_reader=rule_reader,
    )
    intent = _intent_for(
        reservation_harness,
        key=f"native-tax-history-order-{uuid4().hex}",
        quantity=Decimal("100"),
        price=Decimal("10.00"),
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
    )
    reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("20.00"),
        as_of=reserve_as_of,
    )
    reservation = SimulatedOrderReservationModel.objects.get(
        account_id=account.pk,
        idempotency_key=intent.idempotency_key,
    )

    match_as_of = reserve_as_of + timedelta(minutes=5)
    monkeypatch.setattr(timezone, "now", _FixedClock(match_as_of).now)
    event_time = max(
        reservation.created_at + timedelta(microseconds=1),
        match_as_of - timedelta(milliseconds=1),
    )
    trade_session = event_time.astimezone(ZoneInfo(_TIMEZONE)).date()
    assert event_time > anchor.account_created_at
    assert calendar_evidence.snapshot.coverage_start <= trade_session
    assert calendar_evidence.snapshot.coverage_end >= complete_through

    qualified = match_fixtures._qualified_input(
        security_id=intent.security_id,
        close_price=Decimal("9.50"),
        as_of=match_as_of,
    )
    qualified_observation = replace(
        qualified.observation,
        session_date=trade_session,
        observation_id=stable_local_daily_observation_id(intent.security_id, trade_session),
        observed_at=event_time,
        available_at=match_as_of,
        traded_volume=Decimal("100"),
    )
    qualified = replace(
        qualified,
        observation=qualified_observation,
        evidence=tuple(
            replace(reference, recorded_at=match_as_of) for reference in qualified.evidence
        ),
    )
    match_command = LocalDailyMatchCommand(
        account_id=account.pk,
        user_id=owner_seed.owner.pk,
        order_idempotency_key=intent.idempotency_key,
        operation_key=f"native-tax-history-match-{uuid4().hex}",
        session_date=trade_session,
        qmt_binding_id=str(uuid4()),
    )
    assert not connection.in_atomic_block
    match_decision = RecordLocalDailyMatchUseCase(
        repository=DjangoLocalDailyMatchRepository(using="default"),
        qualification_reader=match_fixtures._QualificationReader(qualified),
        clock=match_fixtures._FixedClock(match_as_of),
    ).execute(match_command)
    event = match_decision.event
    assert match_decision.result.outcome is LocalMatchOutcome.MATCHED
    assert event is not None and event.event_kind.value in {"fill", "final_fill"}
    assert event.account_id == account.pk and event.user_id == owner_seed.owner.pk
    assert event.occurred_at == event_time
    assert event.local_known_at == match_as_of
    assert event.source_namespace == LOCAL_DAILY_MATCH_SOURCE_NAMESPACE
    assert LocalDailyMatchModel.objects.filter(
        account_id=account.pk,
        operation_key=match_command.operation_key,
        outcome=LocalDailyMatchModel.OUTCOME_MATCHED,
    ).exists()

    fill_cutoff = match_as_of + timedelta(minutes=2)
    monkeypatch.setattr(timezone, "now", _FixedClock(fill_cutoff).now)
    settlement_proof = build_order_fill_settlement_proof(
        calendar_evidence=calendar_evidence,
        calendar_read_cutoff=fill_cutoff,
        fill_occurred_at=event.occurred_at,
        settlement_exchange=_EXCHANGE,
        settlement_lag_sessions=_SETTLEMENT_LAG,
    )
    assert settlement_proof.fill_market_session == trade_session
    assert settlement_proof.expected_release_session == trade_session + timedelta(
        days=_SETTLEMENT_LAG
    )
    mark = InitialPositionMarkProof(
        security_id=event.security_id,
        asset_code=event.asset_code,
        asset_type=reservation.asset_type,
        market=reservation.market,
        board=reservation.board,
        price=Decimal("10.2500"),
        source_observed_at=fill_cutoff - timedelta(seconds=10),
        source_available_at=None,
        read_at=fill_cutoff,
        publication_as_of=fill_cutoff - timedelta(seconds=2),
        published_at=fill_cutoff - timedelta(seconds=1),
        valid_until=fill_cutoff + timedelta(seconds=590),
        freshness_window_seconds=600,
        source_identity="native-test.independent-position-mark",
        source_record_id=f"native-test-mark-{uuid4().hex}",
        source_content_hash="b" * 64,
        publication_id=f"native-test-publication-{uuid4().hex}",
        publication_hash="c" * 64,
        policy_identity="native-test-position-mark-policy.v1",
        policy_content_hash="d" * 64,
    )
    mark_reader = fill_fixtures._InitialPositionMarkReader(proof=mark, calls=[])
    fill_result = DjangoSimulatedOrderFillRepository(
        tax_cash_coverage_reader=seed_tax_coverage,
        event_reader=DjangoLocalDailyMatchEventReader(using="default"),
        initial_position_mark_reader=mark_reader,
        using="default",
    ).apply_fill_event(
        event=event,
        expected_event_payload_hash=event.event_payload_hash,
        settlement_proof=settlement_proof,
        clock=_FixedClock(fill_cutoff),
    )
    trade = SimulatedTradeModel.objects.get(pk=fill_result.trade_id)
    receipt = SimulatedOrderFillReceiptModel.objects.get(trade=trade)
    reservation.refresh_from_db()
    decoded_fill = read_order_reservation_fill_row(
        reservation_row=reservation,
        receipt_row=receipt,
        trade_row=trade,
    )
    assert decoded_fill.event == event
    assert receipt.source_namespace == event.source_namespace
    assert receipt.source_event_id == event.source_event_id
    assert trade.settlement_release_date == settlement_proof.expected_release_session

    # Restore the actual server clock before activating and reading current Config Center state.
    monkeypatch.setattr(timezone, "now", actual_clock)
    tax_read_as_of = timezone.now()
    runtime_value = {
        "schema_version": "simulated-dividend-tax-date-conventions.v1",
        "enabled": True,
        "policies": [
            {
                "convention_id": f"native-tax-date-hypothesis-{account.pk}",
                "version": "1",
                "physical_account_id": account.pk,
                "canonical_account_id": canonical_account_id,
                "owner_user_id": owner_seed.owner.pk,
                "exchange": _EXCHANGE,
                "purchase_open_session_offset": _TAX_PURCHASE_OFFSET,
                "sale_open_session_offset": 1,
                "trade_window_start": calendar_start.isoformat(),
                "trade_window_end": complete_through.isoformat(),
                "valid_from": (tax_read_as_of - timedelta(minutes=1)).isoformat(),
                "valid_until": (tax_read_as_of + timedelta(hours=1)).isoformat(),
                "approval_ref": "explicit-controlled-simulated-tax-date-test",
            }
        ],
    }
    activate_runtime_profile_patch(
        environment=owner_seed.environment,
        patch={SIMULATED_TAX_DATE_CONVENTION_KEY: runtime_value},
        actor="native-simulated-tax-history-test",
        reason="explicit simulation-only date hypothesis for a read-only integration test",
    )
    runtime_evidence = read_active_runtime_value_evidence(
        environment=owner_seed.environment,
        definition_key=SIMULATED_TAX_DATE_CONVENTION_KEY,
        as_of=timezone.now(),
    )
    assert runtime_evidence is not None
    assert runtime_evidence.value == runtime_value
    assert runtime_evidence.environment == owner_seed.environment

    ownership_reader = DjangoCorporateActionOwnershipHistoryRepository(
        exchange_timezone_policy_reader=_ControlledTimezonePolicyReader(),
        using="default",
    )
    verified_origin = ownership_reader.read_verified_zero_origin_date(
        account_id=account.pk,
        owner_user_id=owner_seed.owner.pk,
        exchange=_EXCHANGE,
        as_of=timezone.now(),
    )
    assert verified_origin == anchor_date

    controlled_calendar = _ControlledCalendarReader(calendar_evidence)

    def _ownership_repository_factory(
        *, runtime_environment: str, using: str
    ) -> DjangoCorporateActionOwnershipHistoryRepository:
        assert runtime_environment == owner_seed.environment
        assert using == "default"
        return ownership_reader

    def _calendar_reader_factory(
        *,
        dataset_key: str,
        runtime_environment: str,
        read_publication: object | None = None,
    ) -> _ControlledCalendarReader:
        assert dataset_key == "native-controlled-calendar-fixture"
        assert runtime_environment == owner_seed.environment
        assert read_publication is not None
        return controlled_calendar

    monkeypatch.setattr(
        history_composition,
        "build_corporate_action_ownership_history_repository",
        _ownership_repository_factory,
    )
    monkeypatch.setattr(
        history_composition,
        "build_current_published_execution_calendar_reader",
        _calendar_reader_factory,
    )
    history_use_case = history_composition.build_read_simulated_tax_settlement_history_use_case(
        runtime_environment=owner_seed.environment,
        calendar_dataset_key="native-controlled-calendar-fixture",
        using="default",
    )
    query = SimulatedTaxSettlementHistoryQuery(
        environment=owner_seed.environment,
        account_kind="simulated",
        physical_account_id=account.pk,
        canonical_account_id=canonical_account_id,
        owner_user_id=owner_seed.owner.pk,
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        record_date=record_date,
        complete_through=complete_through,
        record_date_entitlement=RecordDateTaxEntitlementEvidence(
            kind=RecordDateTaxEntitlementRuleKind.ALL_COVERED_POSITIONS,
            rule_source_id="controlled-test.entitlement-rule.v1",
            rule_source_sha256="e" * 64,
            qualified_total_quantity=event.quantity,
            total_evidence_id="controlled-test.record-date-total.v1",
            total_evidence_sha256="f" * 64,
        ),
    )

    before = _read_only_snapshot(account.pk)
    history_build = history_use_case.execute(query)
    after = _read_only_snapshot(account.pk)
    assert after == before

    history = history_build.history
    history_build.observation.verify_for(history)
    read_exchange_date = history_build.observation.read_at.astimezone(ZoneInfo(_TIMEZONE)).date()
    assert history.complete_through < read_exchange_date
    assert history.covered_session_dates[-1] < read_exchange_date
    modeled = history_build.observation.date_observations
    assert len(modeled) == 1
    fill_observation = modeled[0]
    assert fill_observation.source_event_id == event.source_event_id
    assert fill_observation.source_namespace == event.source_namespace
    assert fill_observation.receipt_sha256 == receipt.receipt_hash
    assert fill_observation.source_recorded_at == event.recorded_at
    assert event.source_observed_at is None
    assert event.source_available_at is None
    assert fill_observation.source_observed_at is None
    assert fill_observation.source_available_at is None
    assert fill_observation.interval_end_at == event.occurred_at
    assert fill_observation.local_known_at == event.local_known_at
    assert fill_observation.date_evidence.trade_occurred_at == event.occurred_at
    assert fill_observation.date_evidence.trade_observed_at == event.local_known_at
    assert fill_observation.date_evidence.convention_known_at == runtime_evidence.known_at
    assert fill_observation.date_evidence.read_at == history_build.observation.read_at
    rule_observation = history_build.observation.date_rule
    assert rule_observation.created_at == runtime_evidence.created_at
    assert rule_observation.known_at == runtime_evidence.known_at
    assert rule_observation.activated_at == runtime_evidence.activated_at
    assert rule_observation.snapshot_generated_at == runtime_evidence.snapshot_generated_at
    assert rule_observation.effective_at == runtime_evidence.effective_at
    assert runtime_evidence.as_of <= rule_observation.as_of
    assert rule_observation.as_of <= history_build.observation.read_at
    assert rule_observation.profile_content_hash == runtime_evidence.profile_content_hash
    assert rule_observation.snapshot_hash == runtime_evidence.snapshot_hash
    assert fill_observation.date_evidence.modeled_tax_date == trade_session + timedelta(
        days=_TAX_PURCHASE_OFFSET
    )
    assert fill_observation.date_evidence.modeled_tax_date != trade.settlement_release_date
    assert history.covered_session_dates == tuple(
        calendar_date for calendar_date in calendar_dates if calendar_date <= complete_through
    )
    assert history.record_date == query.record_date
    assert history.complete_through == complete_through
    assert len(history.settlement_days) == len(history.covered_session_dates)
    for row in history.settlement_days:
        if row.settlement_date == fill_observation.date_evidence.modeled_tax_date:
            assert row.gross_purchase_quantity == event.quantity
            assert row.gross_sale_quantity == Decimal("0.000000")
        else:
            assert row.gross_purchase_quantity == Decimal("0.000000")
            assert row.gross_sale_quantity == Decimal("0.000000")
            assert row.opening_eod_quantity == row.closing_eod_quantity
            assert row.non_trade_quantity_delta == Decimal("0.000000")
    record_day = next(
        row for row in history.settlement_days if row.settlement_date == query.record_date
    )
    assert record_day.opening_eod_quantity == event.quantity
    assert record_day.closing_eod_quantity == event.quantity
    assert record_day.gross_purchase_quantity == Decimal("0.000000")
    assert record_day.gross_sale_quantity == Decimal("0.000000")
