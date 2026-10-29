"""Read-only source qualification for local daily simulated matching."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from apps.data_center.application.price_limit_publication_operations import (
    PriceLimitPublicationReadResult,
    PriceLimitPublicationScope,
)
from apps.data_center.application.published_price_source import (
    PublishedPriceSourceEvidence,
    PublishedPriceSourceResult,
)
from apps.data_center.application.qmt_daily_status import (
    QmtDailyStatusEvidence,
    QmtDailyStatusResult,
)
from apps.data_center.domain.enums import PriceAdjustment
from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceFetchRound,
    InstrumentReferenceSnapshotRecord,
    make_instrument_reference_snapshot_record,
)
from apps.data_center.domain.market_time import cn_market_session_close_utc
from apps.data_center.domain.qmt_daily_status import QmtDailyStatusState
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.application.local_daily_match import (
    LocalDailyMatchCommand,
    QualifiedLocalDailyMatchInput,
    stable_local_daily_observation_id,
)
from apps.simulated_trading.application.order_reservation_fill import OrderFillContext
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.domain.local_daily_simulation_policy import (
    LocalDailySimulationPolicy,
    LocalDailySimulationPolicyBinding,
    LocalDailySimulationPolicyRuntimeProvenance,
)
from apps.simulated_trading.infrastructure.local_daily_match_source_reader import (
    RetainedLocalDailyMatchSourceReader,
)
from apps.simulated_trading.local_daily_match_composition import (
    build_record_local_daily_match_use_case,
)
from tests.unit.data_center import test_formal_price_limit_publication as price_limit_fixtures
from tests.unit.data_center import test_instrument_reference_snapshot as instrument_fixtures
from tests.unit.simulated_trading import test_order_reservation_fill_application as order_fixtures
from tests.unit.simulated_trading import (
    test_published_price_initial_position_mark_reader as price_fixtures,
)

_AS_OF = datetime(2026, 10, 27, 8, 0, tzinfo=UTC)
_SESSION = date(2026, 10, 26)
_SESSION_CLOSE = cn_market_session_close_utc(_SESSION)
_ASSET_CODE = "600000.SH"
_STOCK_BASIC_DATASET = "tushare.stock_basic.reference"
_SNAPSHOT_ID = UUID("e57450a7-2b23-47db-9bc3-7e4b36f75bd6")
_QMT_BINDING_ID = "9cc1ef82-1c6f-47fa-ae0f-2df5be5abf00"


def test_public_producer_cannot_mix_default_sources_with_another_ledger_alias() -> None:
    with pytest.raises(SimulatedTradeExecutionInputError) as error:
        build_record_local_daily_match_use_case(
            runtime_environment="fixture",
            calendar_dataset_key="trade_cal",
            clock=order_fixtures._Clock(_AS_OF),
            using="another-ledger",
        )
    assert error.value.code == "LOCAL_DAILY_MATCH_ALIAS_MISMATCH"


@dataclass
class _PolicyReader:
    """Return the same immutable verified policy binding on both reads."""

    binding: LocalDailySimulationPolicyBinding | None
    calls: int = 0
    second_binding: LocalDailySimulationPolicyBinding | None = None

    def read_policy(self, *, as_of: datetime) -> LocalDailySimulationPolicyBinding | None:
        assert as_of == _AS_OF
        self.calls += 1
        if self.calls > 1 and self.second_binding is not None:
            return self.second_binding
        return self.binding


@dataclass
class _CalendarReader:
    """Return the exact formal execution calendar for the requested exchange."""

    evidence: ExecutionCalendarEvidence | None

    def get_effective_execution_calendar(
        self, *, exchange: str, as_of: datetime, coverage_start: date
    ) -> ExecutionCalendarEvidence | None:
        assert exchange == "SSE"
        assert as_of == _AS_OF
        assert coverage_start == _SESSION
        return self.evidence


@dataclass
class _InstrumentReader:
    """Return the exact explicitly selected immutable instrument snapshot."""

    record: InstrumentReferenceSnapshotRecord | None

    def __call__(self, *, snapshot_id: UUID) -> InstrumentReferenceSnapshotRecord | None:
        if self.record is None:
            return None
        assert snapshot_id == self.record.snapshot_id
        return self.record


@dataclass
class _PriceReader:
    """Return a typed public price-source result at the exact requested scope."""

    result: PublishedPriceSourceResult
    publication_key: str

    def __call__(
        self,
        asset_code: str,
        *,
        trade_date: date,
        knowledge_cutoff: datetime,
        publication_key: str,
    ) -> PublishedPriceSourceResult:
        assert asset_code == _ASSET_CODE
        assert trade_date == _SESSION
        assert knowledge_cutoff == _AS_OF
        assert publication_key == self.publication_key
        return self.result


@dataclass
class _QmtReader:
    """Return owner-scoped retained daily-status evidence without mutation."""

    result: QmtDailyStatusResult

    def __call__(
        self,
        *,
        owner_id: int,
        binding_id: str,
        asset_code: str,
        bar_date: date,
        as_of: datetime,
    ) -> QmtDailyStatusResult:
        assert owner_id == 11
        assert binding_id == _QMT_BINDING_ID
        assert asset_code == _ASSET_CODE
        assert bar_date == _SESSION
        assert as_of == _AS_OF
        return self.result


@dataclass
class _LimitReader:
    """Return one exact formal reference selected at the requested cutoff."""

    result: PriceLimitPublicationReadResult | None
    provider_id: int
    provider_name: str

    def __call__(
        self, *, scope: PriceLimitPublicationScope, as_of: datetime
    ) -> PriceLimitPublicationReadResult | None:
        assert scope.provider_id == self.provider_id
        assert scope.provider_name == self.provider_name
        assert scope.asset_code == _ASSET_CODE
        assert scope.effective_trade_date == _SESSION
        assert as_of == _AS_OF
        return self.result


@dataclass(frozen=True)
class _Scenario:
    """Hold the real typed source evidence and injected reader ports together."""

    reader: RetainedLocalDailyMatchSourceReader
    command: LocalDailyMatchCommand
    context: OrderFillContext
    instrument: InstrumentReferenceSnapshotRecord
    qmt: QmtDailyStatusResult
    price: PublishedPriceSourceEvidence
    policy_reader: _PolicyReader
    calendar_reader: _CalendarReader
    instrument_reader: _InstrumentReader
    price_reader: _PriceReader
    qmt_reader: _QmtReader
    limit_reader: _LimitReader


def _assert_blocked(
    scenario: _Scenario,
    code: str,
    *,
    command: LocalDailyMatchCommand | None = None,
    context: OrderFillContext | None = None,
) -> None:
    """Require one exact stable qualification block from the public reader."""

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        scenario.reader.read(
            command=command or scenario.command,
            context=context or scenario.context,
            as_of=_AS_OF,
        )
    assert error.value.code == f"LOCAL_DAILY_MATCH_{code}"


def _policy_binding(
    *, provider_name: str, instrument_snapshot_id: str
) -> LocalDailySimulationPolicyBinding:
    """Build one explicit policy and exact active runtime provenance at the cutoff."""

    policy = LocalDailySimulationPolicy.from_payload(
        {
            "schema_version": "local-daily-simulation-policy.v1",
            "purpose": "historical_daily_simulation",
            "policy_id": "daily-match-fixture",
            "version": "approved-1",
            "price_publication_key": price_fixtures._POLICY_KEY,
            "provider_configuration_id": 19,
            "provider_name": provider_name,
            "instrument_snapshot_id": instrument_snapshot_id,
            "currency": "CNY",
            "frequency": "1d",
            "adjustment": "none",
            "volume_unit": "shares",
            "participation_rate": "0.1250",
            "share_step": "100",
            "allowed_qmt_suspend_flags": [-1, 0],
            "currency_basis": "same_session_stock_basic_capture",
            "qmt_status_basis": "owner_authenticated_normalized_daily_status",
            "limit_price_basis": "same_provider_cny_listing_native",
        }
    )
    provenance = LocalDailySimulationPolicyRuntimeProvenance(
        runtime_environment="development",
        profile_id="daily-match-profile",
        profile_key="development-profile",
        profile_version=4,
        profile_content_hash="a" * 64,
        profile_activated_at=_SESSION_CLOSE + timedelta(minutes=10),
        snapshot_id="daily-match-snapshot",
        snapshot_content_hash="b" * 64,
        snapshot_generated_at=_AS_OF - timedelta(minutes=10),
        snapshot_effective_from=_SESSION_CLOSE + timedelta(minutes=10),
        read_at=_AS_OF,
    )
    return LocalDailySimulationPolicyBinding(policy=policy, provenance=provenance)


def _instrument_snapshot(
    *,
    provider_name: str,
    dataset_key: str,
    source_currencies: tuple[str | None, ...] = ("CNY", "CNY"),
    include_currency_field: bool = True,
    response_day_offset: int = 0,
    list_date: date | None = date(2020, 1, 2),
) -> InstrumentReferenceSnapshotRecord:
    """Build two retained same-session stock-basic rounds with a sealed snapshot."""

    _mapping, _mapping_record, source_content = instrument_fixtures._persistable_content(
        include_currency_field=True,
        source_currency="CNY",
    )
    rounds: list[InstrumentReferenceFetchRound] = []
    for round_index, fetch_round in enumerate(source_content.fetch_rounds):
        candidate = fetch_round.candidate
        if round_index >= len(source_currencies):
            raise ValueError("fixture needs an explicit currency for every fetch round")
        fields = candidate.provider_contract.fields
        if not include_currency_field:
            fields = tuple(field for field in fields if field != "curr_type")
        contract = replace(
            candidate.provider_contract,
            contract_version="stock-basic-currency-v2",
            provider_name=provider_name,
            dataset_key=dataset_key,
            fields=fields,
        )
        occurrences = tuple(
            replace(
                occurrence,
                response_completed_at=_SESSION_CLOSE
                + timedelta(days=response_day_offset)
                + timedelta(minutes=round_index * 2 + occurrence_index + 1),
            )
            for occurrence_index, occurrence in enumerate(candidate.occurrences)
        )
        rounds.append(
            replace(
                fetch_round,
                candidate=replace(
                    candidate,
                    provider_contract=contract,
                    occurrences=occurrences,
                    records=tuple(
                        replace(
                            record,
                            source_currency=(
                                source_currencies[round_index] if include_currency_field else None
                            ),
                            list_date_raw=(
                                list_date.strftime("%Y%m%d") if list_date is not None else ""
                            ),
                            list_date=list_date,
                        )
                        for record in candidate.records
                    ),
                ),
            )
        )
    content = replace(source_content, fetch_rounds=tuple(rounds))
    return make_instrument_reference_snapshot_record(
        content,
        snapshot_id=_SNAPSHOT_ID,
        recorded_at=_SESSION_CLOSE + timedelta(minutes=10),
    )


def _scenario(
    *,
    policy_provider_name: str = "Tushare Pro",
    stock_provider_name: str = "tushare",
    stock_dataset_key: str = _STOCK_BASIC_DATASET,
    price_source: str = "tushare",
    price_raw_provider_name: str = "Tushare Pro",
    limit_provider_name: str = "Tushare Pro",
    limit_asset_code: str = _ASSET_CODE,
    currency_dataset: str | None = None,
    include_currency_field: bool = True,
    source_currencies: tuple[str | None, ...] = ("CNY", "CNY"),
    response_day_offset: int = 0,
    list_date: date | None = date(2020, 1, 2),
    closed_session: bool = False,
    reserved_at: datetime | None = None,
    price_limit_timezone: str = "Asia/Shanghai",
    limit_requested_name: str | None = None,
) -> _Scenario:
    """Build typed, exact-scope evidence and injected ports for a valid session."""

    instrument = _instrument_snapshot(
        provider_name=stock_provider_name,
        dataset_key=currency_dataset or stock_dataset_key,
        source_currencies=source_currencies,
        include_currency_field=include_currency_field,
        response_day_offset=response_day_offset,
        list_date=list_date,
    )
    binding = _policy_binding(
        provider_name=policy_provider_name,
        instrument_snapshot_id=str(instrument.snapshot_id),
    )
    command = LocalDailyMatchCommand(
        account_id=7,
        user_id=11,
        order_idempotency_key="fill-order-application-001",
        operation_key="daily-match-operation-001",
        session_date=_SESSION,
        qmt_binding_id=_QMT_BINDING_ID,
    )
    context = order_fixtures._scenario(
        reserved_at=reserved_at or _SESSION_CLOSE - timedelta(minutes=10),
        event_occurred_at=_AS_OF,
    ).context

    price = price_fixtures._source_evidence(as_of=_AS_OF, trade_date=_SESSION)
    price_reference = replace(
        price.raw_payload_reference,
        provider_name=price_raw_provider_name,
    )
    price = replace(
        price,
        source=price_source,
        publication_key=price_fixtures._POLICY_KEY,
        provider_configuration_id=19,
        raw_payload_reference=price_reference,
        raw_audit_reference=replace(
            price.raw_audit_reference,
            provider_name=price_raw_provider_name,
        ),
    )
    price_result = PublishedPriceSourceResult(evidence=price, blocked_reason="")

    qmt_recorded = _AS_OF - timedelta(minutes=5)
    qmt_selected_recorded = _AS_OF - timedelta(minutes=20)
    qmt_known = _SESSION_CLOSE + timedelta(minutes=6)
    qmt = QmtDailyStatusResult(
        binding_id=_QMT_BINDING_ID,
        asset_code=_ASSET_CODE,
        bar_date=_SESSION,
        as_of=_AS_OF,
        state=QmtDailyStatusState.NORMAL,
        suspend_flag=0,
        local_known_at=qmt_known,
        recorded_at=qmt_selected_recorded,
        evidence=(
            QmtDailyStatusEvidence(
                batch_id="1f21c127-3a52-4b58-b628-95f43b1ab003",
                content_hash="c" * 64,
                collected_at=_SESSION_CLOSE + timedelta(minutes=5),
                recorded_at=qmt_recorded,
            ),
            QmtDailyStatusEvidence(
                batch_id="2f21c127-3a52-4b58-b628-95f43b1ab004",
                content_hash="d" * 64,
                collected_at=qmt_known,
                recorded_at=qmt_selected_recorded,
            ),
        ),
        blocked_reason="qmt_daily_status_requires_publication_validation",
    )

    limit_snapshot = price_limit_fixtures._snapshot(
        provider_id=19,
        provider_name=limit_provider_name,
        asset_code=limit_asset_code,
        effective_trade_date=_SESSION,
        lower_limit_price=Decimal("9.0000"),
        upper_limit_price=Decimal("11.0000"),
        response_completed_at=_SESSION_CLOSE + timedelta(minutes=5),
        recorded_at=_SESSION_CLOSE + timedelta(minutes=6),
    )
    limit_seal = price_limit_fixtures._seal(limit_snapshot)
    limit_record = price_limit_fixtures._record(
        limit_seal,
        first_published_at=_AS_OF - timedelta(minutes=30),
    )
    limit_result = PriceLimitPublicationReadResult(
        record=limit_record,
        as_of=_AS_OF,
        visible_from=_AS_OF - timedelta(minutes=20),
        lookup_basis="visible_at_cutoff",
    )

    calendar = price_fixtures._calendar(
        as_of=_AS_OF,
        timezone_name=price_limit_timezone,
        covered_days=5,
        closed_dates=frozenset(
            {date(2026, 10, 24), date(2026, 10, 25)} | ({_SESSION} if closed_session else set())
        ),
    )
    policy_reader = _PolicyReader(binding)
    calendar_reader = _CalendarReader(calendar)
    instrument_reader = _InstrumentReader(instrument)
    price_reader = _PriceReader(price_result, price_fixtures._POLICY_KEY)
    qmt_reader = _QmtReader(qmt)
    limit_reader = _LimitReader(
        limit_result,
        provider_id=19,
        provider_name=limit_requested_name or policy_provider_name,
    )
    reader = RetainedLocalDailyMatchSourceReader(
        policy_reader=policy_reader,
        calendar_reader=calendar_reader,
        get_price_source=price_reader,
        read_instrument_snapshot=instrument_reader,
        read_qmt_status=qmt_reader,
        read_limit_reference=limit_reader,
    )
    return _Scenario(
        reader,
        command,
        context,
        instrument,
        qmt,
        price,
        policy_reader,
        calendar_reader,
        instrument_reader,
        price_reader,
        qmt_reader,
        limit_reader,
    )


def test_qualifies_when_source_type_and_provider_configuration_names_differ() -> None:
    scenario = _scenario()

    qualified = scenario.reader.read(
        command=scenario.command,
        context=scenario.context,
        as_of=_AS_OF,
    )

    assert type(qualified) is QualifiedLocalDailyMatchInput
    assert qualified.observation.observed_at == _SESSION_CLOSE
    assert qualified.observation.close_price == Decimal("10.27")
    assert qualified.observation.observation_id == stable_local_daily_observation_id(
        scenario.context.reservation.identity.security_id,
        _SESSION,
    )
    assert qualified.observation.available_at == _AS_OF - timedelta(minutes=5)
    assert scenario.qmt.suspend_flag == 0
    assert scenario.qmt.evidence[0].recorded_at == _AS_OF - timedelta(minutes=5)
    assert scenario.instrument.snapshot_id == _SNAPSHOT_ID


def test_rejects_stock_basic_currency_from_another_dataset() -> None:
    scenario = _scenario(
        policy_provider_name="tushare",
        price_raw_provider_name="tushare",
        limit_provider_name="tushare",
        stock_dataset_key="fixture.stock-basic",
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        scenario.reader.read(
            command=scenario.command,
            context=scenario.context,
            as_of=_AS_OF,
        )

    assert error.value.code == "LOCAL_DAILY_MATCH_CURRENCY_SOURCE_MISMATCH"


def test_rejects_price_raw_capture_from_a_different_configuration_name() -> None:
    scenario = _scenario(
        policy_provider_name="tushare",
        price_raw_provider_name="other configured provider",
        limit_provider_name="tushare",
    )

    _assert_blocked(scenario, "PRICE_SCOPE_MISMATCH")


def test_rejects_order_scope_mismatch_before_reading_sources() -> None:
    scenario = _scenario()
    mismatched = replace(scenario.command, user_id=12)

    _assert_blocked(scenario, "ORDER_SCOPE_MISMATCH", command=mismatched)

    assert scenario.policy_reader.calls == 0


def test_requires_an_explicit_policy_and_a_stable_double_read() -> None:
    missing_policy = _scenario()
    missing_policy.policy_reader.binding = None
    _assert_blocked(missing_policy, "POLICY_UNAVAILABLE")

    changed_policy = _scenario()
    initial = changed_policy.policy_reader.binding
    assert initial is not None
    changed_policy.policy_reader.second_binding = replace(
        initial,
        policy=replace(initial.policy, version="approved-2"),
    )
    _assert_blocked(changed_policy, "POLICY_CHANGED")
    assert changed_policy.policy_reader.calls == 2


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("source", "PRICE_SCOPE_MISMATCH"),
        ("configuration", "PRICE_SCOPE_MISMATCH"),
        ("asset", "PRICE_SCOPE_MISMATCH"),
        ("date", "PRICE_SCOPE_MISMATCH"),
        ("adjustment", "PRICE_SCOPE_MISMATCH"),
        ("volume", "PRICE_SCOPE_MISMATCH"),
        ("future", "PRICE_NOT_KNOWN"),
    ],
)
def test_rejects_price_scope_and_clock_conflicts(change: str, reason: str) -> None:
    scenario = _scenario()
    evidence = scenario.price
    if change == "source":
        evidence = replace(evidence, source="other-source")
    elif change == "configuration":
        evidence = replace(evidence, provider_configuration_id=20)
    elif change == "asset":
        evidence = replace(evidence, asset_code="000001.SZ")
    elif change == "date":
        evidence = replace(evidence, trade_date=date(2026, 10, 23))
    elif change == "adjustment":
        evidence = replace(evidence, adjustment=PriceAdjustment.FORWARD)
    elif change == "volume":
        evidence = replace(evidence, volume_unit="lots")
    else:
        future = _AS_OF + timedelta(minutes=1)
        evidence = replace(
            evidence,
            available_at=future,
            raw_payload_reference=replace(
                evidence.raw_payload_reference,
                response_completed_at=future,
            ),
        )
    scenario.price_reader.result = PublishedPriceSourceResult(evidence=evidence, blocked_reason="")

    _assert_blocked(scenario, reason)


def test_rejects_missing_published_price_and_bad_same_session_currency() -> None:
    missing_price = _scenario()
    missing_price.price_reader.result = PublishedPriceSourceResult(
        evidence=None,
        blocked_reason="price_publication_missing",
    )
    _assert_blocked(missing_price, "PRICE_UNAVAILABLE")

    missing_currency = _scenario(source_currencies=(None, None))
    _assert_blocked(missing_currency, "CURRENCY_OR_LISTING_UNQUALIFIED")

    conflicting_currency = _scenario(source_currencies=("CNY", "USD"))
    _assert_blocked(conflicting_currency, "CURRENCY_OR_LISTING_UNQUALIFIED")

    currency_not_requested = _scenario(include_currency_field=False)
    _assert_blocked(currency_not_requested, "CURRENCY_OR_LISTING_UNQUALIFIED")

    wrong_provider_protocol = _scenario(stock_provider_name="other-provider")
    _assert_blocked(wrong_provider_protocol, "CURRENCY_SOURCE_MISMATCH")

    prior_session_capture = _scenario(response_day_offset=-1)
    _assert_blocked(prior_session_capture, "CURRENCY_NOT_SAME_SESSION")

    missing_listing_date = _scenario(list_date=None)
    _assert_blocked(missing_listing_date, "CURRENCY_OR_LISTING_UNQUALIFIED")


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("unknown", "QMT_STATUS_UNQUALIFIED"),
        ("suspended", "QMT_STATUS_UNQUALIFIED"),
        ("bad-flag", "QMT_STATUS_UNQUALIFIED"),
        ("binding", "QMT_STATUS_UNQUALIFIED"),
        ("date", "QMT_STATUS_UNQUALIFIED"),
        ("no-evidence", "QMT_STATUS_UNQUALIFIED"),
        ("future-record", "QMT_CLOCK_INVALID"),
    ],
)
def test_rejects_unknown_or_mismatched_owner_qmt_status(change: str, reason: str) -> None:
    scenario = _scenario()
    status = scenario.qmt
    if change == "unknown":
        status = replace(status, state=QmtDailyStatusState.UNKNOWN, suspend_flag=None)
    elif change == "suspended":
        status = replace(status, state=QmtDailyStatusState.SUSPENDED, suspend_flag=1)
    elif change == "bad-flag":
        status = replace(status, suspend_flag=2)
    elif change == "binding":
        status = replace(status, binding_id="b59430f5-7534-4f2b-8bda-51e30bb3dc60")
    elif change == "date":
        status = replace(status, bar_date=date(2026, 10, 23))
    elif change == "no-evidence":
        status = replace(status, evidence=())
    else:
        status = replace(
            status,
            evidence=(
                replace(status.evidence[0], recorded_at=_AS_OF + timedelta(minutes=1)),
                status.evidence[1],
            ),
        )
    scenario.qmt_reader.result = status

    _assert_blocked(scenario, reason)


def test_requires_formally_visible_matching_limit_reference() -> None:
    missing = _scenario()
    missing.limit_reader.result = None
    _assert_blocked(missing, "LIMIT_REFERENCE_UNAVAILABLE")

    wrong_asset = _scenario(limit_asset_code="000001.SZ")
    _assert_blocked(wrong_asset, "LIMIT_REFERENCE_SCOPE_MISMATCH")

    wrong_provider = _scenario(
        limit_provider_name="other configured provider",
        limit_requested_name="Tushare Pro",
    )
    _assert_blocked(wrong_provider, "LIMIT_REFERENCE_SCOPE_MISMATCH")

    future_visible = _scenario()
    selected = future_visible.limit_reader.result
    assert selected is not None
    future_visible.limit_reader.result = replace(
        selected,
        visible_from=_AS_OF + timedelta(minutes=1),
    )
    _assert_blocked(future_visible, "LIMIT_REFERENCE_NOT_KNOWN")


def test_requires_open_mainland_calendar_and_order_accepted_before_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = _scenario()
    missing.calendar_reader.evidence = None
    _assert_blocked(missing, "CALENDAR_UNAVAILABLE")

    closed = _scenario(closed_session=True)
    _assert_blocked(closed, "SESSION_NOT_OPEN")

    wrong_timezone = _scenario(price_limit_timezone="UTC")
    _assert_blocked(wrong_timezone, "CALENDAR_TIMEZONE_MISMATCH")

    wrong_exchange = _scenario()
    with monkeypatch.context() as scoped:
        scoped.setattr(price_fixtures, "_SOURCE_EXCHANGE", "SZSE")
        calendar = price_fixtures._calendar(
            as_of=_AS_OF,
            covered_days=5,
            closed_dates=frozenset({date(2026, 10, 24), date(2026, 10, 25)}),
        )
    wrong_exchange.calendar_reader.evidence = calendar
    _assert_blocked(wrong_exchange, "CALENDAR_SCOPE_MISMATCH")

    order_after_close = _scenario(reserved_at=_SESSION_CLOSE + timedelta(minutes=1))
    _assert_blocked(order_after_close, "ORDER_NOT_ACCEPTED_BEFORE_SESSION_END")
