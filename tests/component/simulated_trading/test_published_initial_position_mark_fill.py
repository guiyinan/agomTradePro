"""Exercise retained mark sources through Fill with the accepted-order settlement fixture."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from django.db import connection, transaction
from django.utils import timezone

from apps.audit.infrastructure.publication_activation_audit_writer import (
    DjangoPublicationActivationAuditWriter,
)
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.data_center.application.current_publication_candidate import CurrentPublicationDataset
from apps.data_center.application.current_publication_rebuild import (
    CurrentPublicationRebuildUseCase,
)
from apps.data_center.application.current_publication_staging import (
    CurrentPublicationStageCommand,
    CurrentPublicationStageRawAuditBinding,
    CurrentPublicationStagingUseCase,
)
from apps.data_center.application.public_published_queries import get_published_price_bar_source
from apps.data_center.application.publication_activation import (
    ActivateCanonicalPublicationGroupUseCase,
    PublicationActivationGroupCandidate,
    PublicationActivationGroupRequest,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    exchange_calendar_publication_key,
)
from apps.data_center.domain.instrument_reference_snapshot import (
    make_instrument_reference_mapping_record,
)
from apps.data_center.domain.market_time import (
    cn_market_session_close_utc,
    latest_closed_cn_market_session,
)
from apps.data_center.infrastructure.candidate_raw_audit_metadata_resolver import (
    DjangoCandidateRawAuditMetadataResolver,
)
from apps.data_center.infrastructure.catalog_runtime_repositories import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.current_publication_staging_repository import (
    DjangoCurrentPublicationStagingRepository,
)
from apps.data_center.infrastructure.price_bar_repository import PriceBarRepository
from apps.data_center.infrastructure.publication_group_activation_repository import (
    DjangoPublicationActivationGroupRepository,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationPointerModel,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.initial_position_mark import InitialPositionMarkReader
from apps.simulated_trading.application.local_daily_match import (
    LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
    LocalDailyMatchCommand,
    RecordLocalDailyMatchUseCase,
    stable_local_daily_observation_id,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
    ApplySimulatedOrderFillCommand,
    ApplySimulatedOrderFillUseCase,
    LocalSimulatedFillSourceBinding,
)
from apps.simulated_trading.application.order_reservation_fill_calendar import (
    OrderFillSettlementCalendarResolver,
)
from apps.simulated_trading.domain.initial_position_mark import InitialPositionMarkProof
from apps.simulated_trading.domain.initial_position_mark_policy import InitialPositionMarkPolicy
from apps.simulated_trading.infrastructure.local_daily_match_event_reader import (
    DjangoLocalDailyMatchEventReader,
)
from apps.simulated_trading.infrastructure.local_daily_match_repository import (
    DjangoLocalDailyMatchRepository,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_initial_position_mark_codec import (
    decode_initial_position_mark_evidence,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.initial_position_mark_composition import (
    build_published_initial_position_mark_reader,
)
from tests.component.data_center import (
    test_instrument_reference_snapshot_repository as reference_snapshots,
)
from tests.component.data_center import test_m1_reference_price_publication_activation as m1_price
from tests.component.data_center import test_publication_activation as group_activation
from tests.component.simulated_trading import test_local_daily_match_repository as local_match
from tests.component.simulated_trading import (
    test_local_daily_match_retained_sources as retained_sources,
)
from tests.component.simulated_trading import (
    test_order_reservation_fill_repository as fill_repository,
)
from tests.component.simulated_trading import (
    test_order_reservation_repository as reservation_repository,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_local_daily_match_retained_sources import (
    _align_reused_reservation_fixtures as _align_reused_reservation_fixtures,
)
from tests.component.simulated_trading.test_local_daily_match_retained_sources import (
    local_match_reservation_harness as local_match_reservation_harness,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database
from tests.support.runtime_config import configure_critical_runtime

pytestmark = [
    pytest.mark.django_db(
        transaction=True,
        available_apps=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "apps.audit",
            "apps.config_center",
            "apps.data_center",
            "apps.simulated_trading",
        ],
    ),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="retained publications and Fill transaction behavior require PostgreSQL",
    ),
]

_POLICY_KEY = "config_center.market.simulated_initial_position_mark_policy"
_SELECTOR_KEY = "config_center.market.simulated_current_reference_selection"
_TIMEZONE_KEY = "config_center.market.exchange_timezone_map"


@dataclass(frozen=True, slots=True)
class _FixedClock:
    """Return one explicit aware time to an Application use case."""

    value: datetime

    def now(self) -> datetime:
        """Return the configured test cutoff without changing its source clocks."""

        return self.value


@dataclass(slots=True)
class _ObservedMarkReader:
    """Observe that the composed public mark reader runs inside Fill's transaction."""

    delegate: InitialPositionMarkReader
    proofs: list[InitialPositionMarkProof | None]

    def read_initial_position_mark(
        self,
        *,
        security_id: str,
        asset_code: str,
        asset_type: str,
        market: str,
        board: str,
        read_at: datetime,
    ) -> InitialPositionMarkProof | None:
        """Delegate the exact identity request and assert transaction ownership."""

        assert connection.in_atomic_block
        proof = self.delegate.read_initial_position_mark(
            security_id=security_id,
            asset_code=asset_code,
            asset_type=asset_type,
            market=market,
            board=board,
            read_at=read_at,
        )
        self.proofs.append(proof)
        return proof


def _patch_compatible_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Persist the actual SSE source mapping required by the sealed SH/MAIN order."""

    original = retained_sources._mapping_record()
    content = replace(
        original.content,
        exchange_rule_market_pairs=(("SSE", "SH"),),
        exchange_source_market_board_pairs=(("SSE", "fixture-market", "MAIN"),),
    )
    mapped = make_instrument_reference_mapping_record(
        content,
        mapping_record_id=uuid4(),
        recorded_at=original.recorded_at,
    )
    monkeypatch.setattr(retained_sources, "_mapping_record", lambda: mapped)


def _mark_policy_payload() -> dict[str, object]:
    """Declare the independent current-key mark source and its explicit daily basis."""

    return InitialPositionMarkPolicy(
        schema_version="simulated-initial-position-mark-policy.daily-interval.v1",
        purpose="apply_time_initial_position_mark",
        policy_id="first-buy-mark-component",
        version="1",
        publication_key="current",
        source="tushare",
        frequency="1d",
        adjustment="none",
        supported_asset_types=("equity",),
        freshness_window_seconds=7 * 24 * 60 * 60,
        observation_basis="daily_interval_end",
    ).to_payload()


def _daily_match_input(
    *,
    security_id: str,
    session_date: date,
    as_of: datetime,
) -> local_match.QualifiedLocalDailyMatchInput:
    """Rebind the established typed event fixture to this reservation's session."""

    base = local_match._qualified_input(
        security_id=security_id,
        close_price=Decimal("9.50"),
        as_of=as_of,
    )
    interval_end = cn_market_session_close_utc(session_date)
    local_known_at = interval_end + timedelta(minutes=5)
    return replace(
        base,
        observation=replace(
            base.observation,
            session_date=session_date,
            observation_id=stable_local_daily_observation_id(security_id, session_date),
            observed_at=interval_end,
            available_at=local_known_at,
            traded_volume=Decimal("100"),
        ),
        evidence=tuple(
            replace(
                item,
                identity=f"fixture-{item.identity}",
                recorded_at=local_known_at,
            )
            for item in base.evidence
        ),
    )


def _settlement_resolver_for_fixture(
    *,
    apply_at: datetime,
) -> OrderFillSettlementCalendarResolver:
    """Use only the already accepted order's typed calendar fixture for settlement."""

    start, end, open_sessions = retained_sources._fixture_reservation_calendar_dates()
    evidence = retained_sources.settlement_uow._calendar(
        as_of=retained_sources._RESERVATION_AS_OF,
        open_dates=open_sessions,
        exchange="SSE",
        start=start,
        end=end,
    )
    return OrderFillSettlementCalendarResolver(
        calendar_reader=fill_repository._ExchangeCalendarReader(evidence),
        clock=_FixedClock(apply_at),
    )


def _apply_use_case(
    *,
    event_reader: DjangoLocalDailyMatchEventReader,
    mark_reader: InitialPositionMarkReader | None,
    apply_at: datetime,
    settlement_resolver: OrderFillSettlementCalendarResolver,
) -> ApplySimulatedOrderFillUseCase:
    """Compose the existing Fill Application with exact event and mark readers."""

    return ApplySimulatedOrderFillUseCase(
        repository=DjangoSimulatedOrderFillRepository(
            event_reader=event_reader,
            initial_position_mark_reader=mark_reader,
            using="default",
        ),
        clock=_FixedClock(apply_at),
        source_binding=LocalSimulatedFillSourceBinding(
            reader=event_reader,
            source_namespace=LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
            source_version=LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
        ),
        settlement_resolver=settlement_resolver,
    )


def _ledger_counts(account: SimulatedAccountModel) -> tuple[int, int, int, int, Decimal]:
    """Capture financial row counts and cash before a first-position attempt."""

    return fill_repository._ledger_counts(account)


def _assert_unmutated(
    *,
    account: SimulatedAccountModel,
    reservation: SimulatedOrderReservationModel,
    counts: tuple[int, int, int, int, Decimal],
    financial_state: tuple[object, ...],
) -> None:
    """Require failed mark reads to leave ledger, account and accepted hold intact."""

    assert _ledger_counts(account) == counts
    assert fill_repository._account_financial_state(account) == financial_state
    fill_repository._reservation_unfilled(reservation)
    assert PositionModel._default_manager.filter(account=account).count() == 0
    assert SimulatedTradeModel._default_manager.filter(account=account).count() == 0
    assert (
        SimulatedOrderFillReceiptModel._default_manager.filter(trade__account=account).count() == 0
    )


def test_formal_daily_mark_is_created_by_first_buy_fill_and_exact_receipt_replays(
    local_match_reservation_harness: reservation_repository._Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the real Config Center, calendar, independent price and mark reader in Fill."""

    del persisted_receipt_schema
    assert_native_postgres_test_database()
    configure_critical_runtime()
    runtime_environment = retained_sources._runtime_environment()
    _patch_compatible_mapping(monkeypatch)

    harness = retained_sources._harness_with_source_exchange(local_match_reservation_harness, "SSE")
    security_id = "SH.UOW.SECURITY"
    intent = reservation_repository._intent_for(
        harness,
        key=f"initial-mark-fill-{uuid4().hex}",
        quantity=Decimal("100"),
        price=Decimal("11.50"),
        security_id=security_id,
        asset_code=retained_sources._ASSET_CODE,
    )
    harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=retained_sources._RESERVATION_AS_OF,
    )
    reservation = SimulatedOrderReservationModel._default_manager.get(
        account=harness.account,
        idempotency_key=intent.idempotency_key,
    )
    sealed_identity_payload = reservation.plan_snapshot.get("identity_evidence")
    assert type(sealed_identity_payload) is dict
    assert sealed_identity_payload.get("security_id") == security_id
    assert reservation.market == "SH" and reservation.board == "MAIN"

    price_use_case, price_provider, provider_id, _activation = m1_price._build_m1_test_use_case()
    currency_snapshot = retained_sources._capture_currency_snapshot(
        monkeypatch,
        provider_id=provider_id,
    )
    selector = reference_snapshots._v2_selector_for_persisted_snapshot(
        currency_snapshot,
        max_local_reference_age_seconds=7 * 24 * 60 * 60,
    )
    selector_items = selector.get("items")
    assert type(selector_items) is list and len(selector_items) == 1
    selector_item = selector_items[0]
    assert type(selector_item) is dict
    selector_item["security_id"] = security_id
    policy_payload = _mark_policy_payload()
    activate_runtime_profile_patch(
        environment=runtime_environment,
        patch={
            _TIMEZONE_KEY: {"SSE": "Asia/Shanghai"},
            _SELECTOR_KEY: selector,
            _POLICY_KEY: policy_payload,
        },
        actor="published-initial-mark-fill-component",
        reason="bind mark policy and current-reference selector to one source snapshot",
    )

    event_as_of = timezone.now().astimezone(UTC)
    command = LocalDailyMatchCommand(
        account_id=cast(int, harness.account.pk),
        user_id=harness.user_id,
        order_idempotency_key=intent.idempotency_key,
        operation_key=f"mark-fill-event-{uuid4().hex}",
        session_date=retained_sources._SESSION_DATE,
        qmt_binding_id=str(uuid4()),
    )
    qualified = _daily_match_input(
        security_id=security_id,
        session_date=retained_sources._SESSION_DATE,
        as_of=event_as_of,
    )
    decision = RecordLocalDailyMatchUseCase(
        repository=DjangoLocalDailyMatchRepository(using="default"),
        qualification_reader=local_match._QualificationReader(qualified),
        clock=local_match._FixedClock(event_as_of),
    ).execute(command)
    event = decision.event
    assert event is not None
    assert decision.result.outcome.value == "matched"
    assert event.price == Decimal("9.5000")
    event_reader = DjangoLocalDailyMatchEventReader(using="default")
    apply_command = ApplySimulatedOrderFillCommand(
        account_id=event.account_id,
        user_id=event.user_id,
        order_idempotency_key=event.order_idempotency_key,
        source_namespace=event.source_namespace,
        fill_event_id=event.source_event_id,
        expected_event_payload_hash=event.event_payload_hash,
    )
    mark_delegate = build_published_initial_position_mark_reader(
        runtime_environment=runtime_environment,
        calendar_dataset_key=retained_sources.calendar_source._DATASET.value,
    )
    observed_mark_reader = _ObservedMarkReader(mark_delegate, [])
    counts_before = _ledger_counts(harness.account)
    financial_before = fill_repository._account_financial_state(harness.account)
    assert PositionModel._default_manager.filter(account=harness.account).count() == 0

    _calendar_start, _calendar_end, open_sessions = (
        retained_sources._fixture_reservation_calendar_dates()
    )
    current_rebuilder = CurrentPublicationRebuildUseCase(
        dataset=CurrentPublicationDataset(
            dataset_key="equity.price.bar",
            fact_table="data_center_price_bar",
            created_by="tests.simulated_trading.initial_position_mark",
        ),
        candidate_repository=PriceBarRepository(),
        publication_repository=CanonicalPublicationRepository(),
        policy_repository=PublicationPolicyRepository(),
        publication_key="current",
    )
    current_staging = CurrentPublicationStagingUseCase(
        rebuilder=current_rebuilder,
        raw_audit_resolver=DjangoCandidateRawAuditMetadataResolver(),
        repository=DjangoCurrentPublicationStagingRepository(),
    )

    published_mark_dates: set[date] = set()
    captured_mark_dates: list[date] = []

    def ensure_current_mark_cutoff() -> tuple[date, datetime]:
        """Publish the current completed session and return its stable real cutoff."""

        for _attempt in range(2):
            requested_at = timezone.now().astimezone(UTC)
            mark_date = latest_closed_cn_market_session(
                requested_at,
                open_sessions=frozenset(open_sessions),
            )
            assert mark_date is not None
            if mark_date not in published_mark_dates:
                close_at = cn_market_session_close_utc(mark_date)
                assert close_at <= requested_at
                price_result = price_use_case.execute(
                    m1_price.M1ReferencePricePublicationCommand(
                        provider_id=provider_id,
                        asset_code=retained_sources._ASSET_CODE,
                        target_trade_date=mark_date,
                    )
                )
                assert price_result.sync_result.status == "success"
                captured_mark_dates.append(mark_date)
                assert price_provider.calls == [
                    (retained_sources._ASSET_CODE, captured_date)
                    for captured_date in captured_mark_dates
                ]
                raw_reference = price_result.sync_result.raw_audit_reference
                assert raw_reference is not None
                staged = current_staging.execute(
                    CurrentPublicationStageCommand(
                        asset_codes=(retained_sources._ASSET_CODE,),
                        published_at=timezone.now().astimezone(UTC),
                        run_id=price_result.sync_result.run_id,
                        task_attempt_id=f"initial-mark-current:{uuid4().hex}",
                        raw_audit_bindings=(
                            CurrentPublicationStageRawAuditBinding(
                                reference=raw_reference,
                                expected_source_type="tushare",
                            ),
                        ),
                        required_observation_date=mark_date,
                    )
                )
                # The current market contract activates all three scopes together.
                # Only the mark price comes from the exact captured daily source;
                # the other two scopes reuse the existing activation fixtures.
                publications = (
                    staged.publication,
                    group_activation._build_group_candidate("equity.quote.snapshot"),
                    group_activation._build_group_candidate("equity.valuation.fact"),
                )
                candidates: list[PublicationActivationGroupCandidate] = []
                for publication in publications:
                    pointer = CanonicalPublicationPointerModel._default_manager.get(
                        dataset_key=publication.dataset_key,
                        publication_key="current",
                    )
                    candidates.append(
                        PublicationActivationGroupCandidate(
                            dataset_key=publication.dataset_key,
                            publication_key="current",
                            candidate_publication_id=publication.publication_id,
                            candidate_publication_hash=publication.publication_hash,
                            expected_current_publication_id=(
                                str(pointer.publication_id) if pointer.publication_id else None
                            ),
                            expected_current_publication_hash=pointer.publication_hash or None,
                        )
                    )
                activated = ActivateCanonicalPublicationGroupUseCase(
                    DjangoPublicationActivationGroupRepository(using="default")
                ).execute(
                    PublicationActivationGroupRequest(
                        activation_id=f"initial-mark-current:{uuid4().hex}",
                        candidates=tuple(candidates),
                    ),
                    audit_writer=DjangoPublicationActivationAuditWriter(
                        DjangoSystemAuditEventOutboxCoordinator()
                    ),
                    authority_fence=m1_price._M1AuthorityFence(
                        checked_at=timezone.now().astimezone(UTC),
                        tenant_id="fixture-tenant",
                        owner_id="fixture-owner",
                    ),
                    authority_proof="fixture-authority-proof",
                )
                current_publication = next(
                    item for item in activated if item.dataset_key == "equity.price.bar"
                )
                assert current_publication.publication_key == "current"
                assert (
                    current_publication.dataset_key == "equity.price.bar"
                    and current_publication.member_count == 1
                )
                published_mark_dates.add(mark_date)

            cutoff = timezone.now().astimezone(UTC)
            if (
                latest_closed_cn_market_session(
                    cutoff,
                    open_sessions=frozenset(open_sessions),
                )
                == mark_date
            ):
                price = get_published_price_bar_source(
                    retained_sources._ASSET_CODE,
                    trade_date=mark_date,
                    knowledge_cutoff=cutoff,
                    publication_key="current",
                )
                assert price.evidence is not None, price.blocked_reason
                assert price.evidence.publication_key == "current"
                assert price.evidence.values.close == Decimal("11.4700")
                return mark_date, cutoff

        raise AssertionError(
            "completed market session changed twice while publishing its mark price"
        )

    # The retained current-reference and policy reads are valid, but no formal
    # exchange-calendar pointer exists yet. Settlement uses only its sealed test
    # calendar so the real mark calendar dependency is the failing boundary.
    missing_calendar_date, missing_calendar_at = ensure_current_mark_cutoff()
    assert missing_calendar_date in published_mark_dates
    settlement_fixture = _settlement_resolver_for_fixture(apply_at=missing_calendar_at)
    missing_calendar_pointer = CanonicalPublicationPointerModel._default_manager.filter(
        dataset_key=retained_sources.calendar_source._DATASET.value,
        publication_key=exchange_calendar_publication_key("SSE"),
    )
    assert not missing_calendar_pointer.exists()
    with pytest.raises(SimulatedTradeExecutionBlocked) as missing_calendar:
        _apply_use_case(
            event_reader=event_reader,
            mark_reader=observed_mark_reader,
            apply_at=missing_calendar_at,
            settlement_resolver=settlement_fixture,
        ).execute(apply_command)
    assert missing_calendar.value.code == "INITIAL_POSITION_MARK_UNAVAILABLE"
    assert observed_mark_reader.proofs == [None]
    _assert_unmutated(
        account=harness.account,
        reservation=reservation,
        counts=counts_before,
        financial_state=financial_before,
    )
    assert (
        event_reader.read_event(
            account_id=event.account_id,
            user_id=event.user_id,
            order_idempotency_key=event.order_idempotency_key,
            source_namespace=event.source_namespace,
            fill_event_id=event.source_event_id,
            as_of=missing_calendar_at,
        )
        == event
    )

    calendar_dataset_key = retained_sources._publish_calendar(monkeypatch)
    # A damaged current calendar pointer is not replaced by a latest fallback.
    # Roll back only this deliberate corruption after verifying the fill stays inert.
    pointer = missing_calendar_pointer.get()
    original_publication_hash = pointer.publication_hash
    assert not connection.in_atomic_block
    table = connection.ops.quote_name(CanonicalPublicationPointerModel._meta.db_table)
    pointer_id_field = CanonicalPublicationPointerModel._meta.pk
    pointer_id_column = connection.ops.quote_name(pointer_id_field.column)
    hash_column = connection.ops.quote_name(
        CanonicalPublicationPointerModel._meta.get_field("publication_hash").column
    )
    pointer_identity = pointer_id_field.get_db_prep_value(pointer.pk, connection)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {table} SET {hash_column}=%s WHERE {pointer_id_column}=%s",
                ["f" * 64, pointer_identity],
            )
            assert cursor.rowcount == 1
        corrupt_mark_date, corrupt_at = ensure_current_mark_cutoff()
        assert corrupt_mark_date in published_mark_dates
        with pytest.raises(SimulatedTradeExecutionBlocked) as corrupt_calendar:
            _apply_use_case(
                event_reader=event_reader,
                mark_reader=observed_mark_reader,
                apply_at=corrupt_at,
                settlement_resolver=_settlement_resolver_for_fixture(apply_at=corrupt_at),
            ).execute(apply_command)
        assert corrupt_calendar.value.code == "INITIAL_POSITION_MARK_UNAVAILABLE"
        assert observed_mark_reader.proofs == [None, None]
        _assert_unmutated(
            account=harness.account,
            reservation=reservation,
            counts=counts_before,
            financial_state=financial_before,
        )
        assert (
            event_reader.read_event(
                account_id=event.account_id,
                user_id=event.user_id,
                order_idempotency_key=event.order_idempotency_key,
                source_namespace=event.source_namespace,
                fill_event_id=event.source_event_id,
                as_of=corrupt_at,
            )
            == event
        )
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {table} SET {hash_column}=%s WHERE {pointer_id_column}=%s",
                [original_publication_hash, pointer_identity],
            )
            assert cursor.rowcount == 1
    pointer.refresh_from_db()
    assert pointer.publication_hash == original_publication_hash

    mark_date, apply_at = ensure_current_mark_cutoff()
    assert mark_date in published_mark_dates
    published_price = get_published_price_bar_source(
        retained_sources._ASSET_CODE,
        trade_date=mark_date,
        knowledge_cutoff=apply_at,
        publication_key="current",
    )
    assert published_price.evidence is not None
    assert published_price.evidence.publication_key == "current"
    assert published_price.evidence.values.close == Decimal("11.4700")

    def read_actual_mark() -> InitialPositionMarkProof | None:
        """Read the exact sealed instrument at the fixed post-publication cutoff."""

        return mark_delegate.read_initial_position_mark(
            security_id=reservation.security_id,
            asset_code=reservation.asset_code,
            asset_type=reservation.asset_type,
            market=reservation.market,
            board=reservation.board,
            read_at=apply_at,
        )

    standalone_mark = read_actual_mark()
    assert standalone_mark is not None
    ledger_before_nested_probe = _ledger_counts(harness.account)
    financial_before_nested_probe = fill_repository._account_financial_state(harness.account)
    with transaction.atomic():
        with transaction.atomic():
            nested_mark = read_actual_mark()
    assert nested_mark is None
    assert _ledger_counts(harness.account) == ledger_before_nested_probe
    assert (
        fill_repository._account_financial_state(harness.account) == financial_before_nested_probe
    )
    recovered_standalone_mark = read_actual_mark()
    assert recovered_standalone_mark == standalone_mark
    assert _ledger_counts(harness.account) == ledger_before_nested_probe
    assert calendar_dataset_key == retained_sources.calendar_source._DATASET.value
    applied = _apply_use_case(
        event_reader=event_reader,
        mark_reader=observed_mark_reader,
        apply_at=apply_at,
        settlement_resolver=_settlement_resolver_for_fixture(apply_at=apply_at),
    ).execute(apply_command)
    assert applied.replayed is False
    assert applied.event_payload_hash == event.event_payload_hash
    assert len(observed_mark_reader.proofs) == 3
    mark = observed_mark_reader.proofs[-1]
    assert mark is not None
    assert mark == standalone_mark
    assert mark.observation_basis == "daily_interval_end"
    assert mark.source_observed_at is None
    assert mark.price == published_price.evidence.values.close
    assert mark.price != event.price
    assert mark.publication_id == published_price.evidence.publication_id
    assert mark.source_record_id == published_price.evidence.fact_pk
    assert mark.policy_identity == "apply_time_initial_position_mark:first-buy-mark-component:1"

    trade = SimulatedTradeModel._default_manager.get(account=harness.account)
    position = PositionModel._default_manager.get(
        account=harness.account,
        asset_code=retained_sources._ASSET_CODE,
    )
    receipt = SimulatedOrderFillReceiptModel._default_manager.get(trade=trade)
    assert receipt.receipt_version == 2
    assert type(receipt.initial_position_mark_evidence) is dict
    assert trade.price == event.price
    assert position.current_price == mark.price
    assert position.quantity == event.quantity
    assert position.market_value == event.quantity * mark.price
    assert receipt.initial_position_mark_evidence == mark.to_payload()
    decoded_mark = decode_initial_position_mark_evidence(
        json.dumps(
            receipt.initial_position_mark_evidence,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    assert decoded_mark == mark
    assert reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    reservation.refresh_from_db()
    assert reservation.filled_quantity == event.quantity
    assert _ledger_counts(harness.account) != counts_before
    ledger_after_success = _ledger_counts(harness.account)
    financial_after_success = fill_repository._account_financial_state(harness.account)
    reservation_after_success = (
        reservation.status,
        reservation.filled_quantity,
        reservation.cash_consumed,
        reservation.shares_consumed,
        reservation.cash_released,
        reservation.shares_released,
    )

    class _NoClock:
        """Reject any current clock read during exact receipt replay."""

        def now(self) -> datetime:
            raise AssertionError("receipt replay must not consult current mark sources")

    replay = ApplySimulatedOrderFillUseCase(
        repository=DjangoSimulatedOrderFillRepository(
            event_reader=None,
            initial_position_mark_reader=None,
            using="default",
        ),
        clock=_NoClock(),
        source_binding=None,
        settlement_resolver=None,
    ).execute(apply_command)
    assert replay.replayed is True
    assert replay.trade_id == applied.trade_id
    assert len(observed_mark_reader.proofs) == 3
    assert _ledger_counts(harness.account) == ledger_after_success
    assert fill_repository._account_financial_state(harness.account) == financial_after_success
    reservation.refresh_from_db()
    assert (
        reservation.status,
        reservation.filled_quantity,
        reservation.cash_consumed,
        reservation.shares_consumed,
        reservation.cash_released,
        reservation.shares_released,
    ) == reservation_after_success
