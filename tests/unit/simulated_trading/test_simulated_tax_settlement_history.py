from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal, localcontext

import pytest

from apps.simulated_trading.application.corporate_action_tax_settlement_history import (
    ReadSimulatedTaxSettlementHistoryUseCase,
    RecordDateOwnershipHistoryRead,
    SimulatedTaxDateConventionRead,
    SimulatedTaxSettlementHistoryQuery,
)
from apps.simulated_trading.application.local_daily_match import (
    LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
)
from apps.simulated_trading.domain import simulated_tax_settlement_history as tax_history_domain
from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_ownership_history import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionOwnershipEvidence,
    CorporateActionStage,
    OwnershipAnchorKind,
    OwnershipFillFact,
    OwnershipFillSide,
    OwnershipOpeningAnchor,
    RecordDateOwnershipProof,
)
from apps.simulated_trading.domain.corporate_action_tax_settlement_evidence import (
    RecordDateTaxEntitlementEvidence,
    RecordDateTaxEntitlementRuleKind,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    CalendarPublicationReference,
    ExchangeCalendarDay,
    ExchangeCalendarSnapshot,
    ExecutionCalendarEvidence,
    RawCalendarReference,
)
from apps.simulated_trading.domain.simulated_tax_date_convention import (
    SimulatedDividendTaxDateConvention,
)
from apps.simulated_trading.domain.simulated_tax_settlement_history import (
    SimulatedTaxDateRuleRuntimeProvenance,
    SimulatedTaxSettlementFillSource,
    SimulatedTaxSettlementHistoryBuild,
    SimulatedTaxSettlementHistoryRequest,
    build_simulated_tax_settlement_history,
)
from core.exceptions import BusinessLogicError

_ACCOUNT_ID = 7
_OWNER_ID = 11
_SECURITY = "SYNTHETIC.SEC"
_ASSET = "SYNTHETIC.ASSET"
_RECORD_DATE = date(2026, 4, 10)
_COMPLETE_THROUGH = date(2026, 4, 14)
_AS_OF = datetime(2026, 4, 15, 8, tzinfo=UTC)


def _calendar(
    *, response_at: datetime = datetime(2026, 4, 15, 7, tzinfo=UTC)
) -> ExecutionCalendarEvidence:
    open_days = {
        date(2026, 4, 8),
        date(2026, 4, 9),
        date(2026, 4, 10),
        date(2026, 4, 13),
        date(2026, 4, 14),
        date(2026, 4, 15),
    }
    rows: list[ExchangeCalendarDay] = []
    previous_open = date(2026, 3, 31)
    for ordinal in range(date(2026, 4, 1).toordinal(), date(2026, 4, 16).toordinal()):
        current = date.fromordinal(ordinal)
        is_open = current in open_days
        rows.append(
            ExchangeCalendarDay(
                "SYNTHETIC",
                current,
                is_open,
                previous_open,
            )
        )
        if is_open:
            previous_open = current
    raw = RawCalendarReference(
        payload_id="f70c0f8a-bfec-4a0b-8f6c-9021ee01b98d",
        payload_hash="sha256:" + "a" * 64,
        record_digest="sha256:" + "b" * 64,
        body_sha256="c" * 64,
        retained_content_sha256="c" * 64,
        request_scope_sha256="d" * 64,
        original_body_retained=True,
        response_completed_at=response_at,
        provider_name="synthetic-calendar-fixture",
        dataset_key="synthetic-calendar",
        transport="direct",
    )
    snapshot = ExchangeCalendarSnapshot(
        snapshot_id="f418fc8b-8843-4cd8-9693-95b67834827b",
        exchange="SYNTHETIC",
        coverage_start=rows[0].calendar_date,
        coverage_end=rows[-1].calendar_date,
        days=tuple(rows),
        provider_name="synthetic-calendar-fixture",
        raw_reference=raw,
        content_hash="",
        record_digest="",
        first_seen_at=response_at,
        recorded_at=response_at + timedelta(minutes=1),
    )
    publication = CalendarPublicationReference(
        publication_id="synthetic-calendar-publication.v1",
        member_id=snapshot.snapshot_id,
        publication_hash="e" * 64,
        fact_content_hash="f" * 64,
        policy_hash="1" * 64,
        published_at=response_at + timedelta(minutes=2),
        recorded_at=response_at + timedelta(minutes=3),
        reference_valid_from=datetime(2026, 4, 1, tzinfo=UTC),
        reference_valid_until=datetime(2026, 5, 1, tzinfo=UTC),
        timezone_name="Asia/Shanghai",
    )
    return ExecutionCalendarEvidence(snapshot=snapshot, publication=publication)


def _convention(*, sale_offset: int = 0) -> SimulatedDividendTaxDateConvention:
    return SimulatedDividendTaxDateConvention(
        convention_id="synthetic-date-rule.v1",
        version="1",
        physical_account_id=_ACCOUNT_ID,
        canonical_account_id="synthetic-account-7",
        owner_user_id=_OWNER_ID,
        exchange="SYNTHETIC",
        purchase_open_session_offset=0,
        sale_open_session_offset=sale_offset,
        trade_window_start=date(2026, 4, 1),
        trade_window_end=date(2026, 4, 30),
        valid_from=datetime(2026, 4, 1, tzinfo=UTC),
        valid_until=datetime(2026, 5, 1, tzinfo=UTC),
        known_at=datetime(2026, 4, 1, tzinfo=UTC),
        approval_ref="synthetic-owner-approval.v1",
    )


def _runtime_provenance(
    convention: SimulatedDividendTaxDateConvention,
    *,
    as_of: datetime = _AS_OF,
) -> SimulatedTaxDateRuleRuntimeProvenance:
    return SimulatedTaxDateRuleRuntimeProvenance(
        convention_sha256=convention.semantic_sha256,
        environment="synthetic-test",
        definition_key="config_center.simulated_trading.dividend_tax_date_conventions",
        profile_id="synthetic-profile.v1",
        profile_key="synthetic-profile-key",
        profile_version=1,
        profile_content_hash="2" * 64,
        snapshot_id="synthetic-snapshot.v1",
        snapshot_hash="3" * 64,
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
        known_at=convention.known_at,
        activated_at=datetime(2026, 4, 2, tzinfo=UTC),
        snapshot_generated_at=datetime(2026, 4, 2, tzinfo=UTC),
        effective_at=datetime(2026, 4, 2, tzinfo=UTC),
        as_of=as_of,
    )


def _source_fill(
    *,
    trade_id: int,
    event_id: str,
    trade_day: date,
    side: OwnershipFillSide,
    quantity: str,
) -> SimulatedTaxSettlementFillSource:
    occurred_at = datetime.combine(trade_day, time(2), tzinfo=UTC)
    observed_at = occurred_at + timedelta(minutes=1)
    return SimulatedTaxSettlementFillSource(
        ownership_fill=OwnershipFillFact(
            account_id=_ACCOUNT_ID,
            owner_user_id=_OWNER_ID,
            security_id=_SECURITY,
            asset_code=_ASSET,
            trade_id=trade_id,
            reservation_id=trade_id + 100,
            fill_sequence=1,
            side=side,
            quantity=Decimal(quantity),
            execution_date=trade_day,
            occurred_at=occurred_at,
            recorded_at=observed_at + timedelta(minutes=1),
            binding_version=4,
            receipt_version=2,
            receipt_sha256=f"{trade_id:064x}",
        ),
        source_namespace=LOCAL_DAILY_MATCH_SOURCE_NAMESPACE,
        source_version=LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
        source_event_id=event_id,
        event_payload_sha256=f"{trade_id + 200:064x}",
        source_snapshot_id=f"synthetic-source-snapshot-{trade_id}",
        source_snapshot_sha256=f"{trade_id + 400:064x}",
        order_idempotency_key=f"synthetic-order-{trade_id}",
        observation_basis="daily_interval_end",
        source_observed_at=None,
        source_available_at=None,
        local_known_at=observed_at,
        interval_end_at=occurred_at,
        source_recorded_at=observed_at + timedelta(minutes=1),
        trade_observed_at=observed_at,
    )


def _cash_action(
    *,
    account_id: int = _ACCOUNT_ID,
    owner_user_id: int = _OWNER_ID,
    stage_date: date = date(2026, 4, 13),
    recorded_at: datetime = datetime(2026, 4, 13, 3, tzinfo=UTC),
) -> CorporateActionOwnershipEvidence:
    """Return one valid zero-share cash action row for history filtering tests."""

    return CorporateActionOwnershipEvidence(
        account_id=account_id,
        owner_user_id=owner_user_id,
        security_id=_SECURITY,
        asset_code=_ASSET,
        account_revision=1,
        entry_id=42,
        source_event_id="synthetic-cash-event.v1",
        source_revision_id="synthetic-cash-revision.v1",
        action_kind=CorporateActionKind.CASH_DIVIDEND,
        stage_key="posting:cash_entitlement",
        stage=CorporateActionStage.CASH_ENTITLEMENT,
        entry_kind=CorporateActionEntryKind.POSTING,
        stage_date=stage_date,
        posted_at=recorded_at - timedelta(minutes=1),
        recorded_at=recorded_at,
        share_delta=Decimal("0.000000"),
        share_receivable_delta=Decimal("0.000000"),
        reversal_of_entry_id=None,
        supersedes_revision_id=None,
        evidence_sha256="d" * 64,
    )


def _request(
    *, sale_offset: int = 0, calendar: ExecutionCalendarEvidence | None = None
) -> SimulatedTaxSettlementHistoryRequest:
    convention = _convention(sale_offset=sale_offset)
    return SimulatedTaxSettlementHistoryRequest(
        account_kind="simulated",
        physical_account_id=_ACCOUNT_ID,
        canonical_account_id="synthetic-account-7",
        owner_user_id=_OWNER_ID,
        security_id=_SECURITY,
        asset_code=_ASSET,
        record_date=_RECORD_DATE,
        complete_through=_COMPLETE_THROUGH,
        record_date_ownership_proof=RecordDateOwnershipProof(
            account_id=_ACCOUNT_ID,
            owner_user_id=_OWNER_ID,
            security_id=_SECURITY,
            asset_code=_ASSET,
            record_date=_RECORD_DATE,
            ownership_snapshot_as_of_date=_RECORD_DATE,
            record_date_end_exclusive=datetime(2026, 4, 10, 16, tzinfo=UTC),
            exchange="SYNTHETIC",
            exchange_timezone_name="Asia/Shanghai",
            cutoff_policy_id="synthetic-record-cutoff.v1",
            cutoff_policy_sha256="4" * 64,
            eligible_quantity=Decimal("80.000000"),
            ownership_snapshot_id="synthetic-ownership-snapshot.v1",
            ownership_snapshot_sha256="5" * 64,
            ownership_snapshot_observed_at=datetime(2026, 4, 11, 1, tzinfo=UTC),
        ),
        opening_anchor=OwnershipOpeningAnchor(
            account_id=_ACCOUNT_ID,
            owner_user_id=_OWNER_ID,
            anchor_id="synthetic-zero-anchor.v1",
            anchor_kind=OwnershipAnchorKind.ZERO_ORIGIN,
            quantity=Decimal("0.000000"),
            effective_at=datetime(2026, 4, 1, tzinfo=UTC),
            observed_at=datetime(2026, 4, 1, tzinfo=UTC),
            evidence_sha256="6" * 64,
        ),
        source_fills=(
            _source_fill(
                trade_id=1,
                event_id="synthetic-fill-buy-1",
                trade_day=date(2026, 4, 8),
                side=OwnershipFillSide.BUY,
                quantity="100.000000",
            ),
            _source_fill(
                trade_id=2,
                event_id="synthetic-fill-sell-2",
                trade_day=date(2026, 4, 9),
                side=OwnershipFillSide.SELL,
                quantity="20.000000",
            ),
            _source_fill(
                trade_id=3,
                event_id="synthetic-fill-buy-3",
                trade_day=date(2026, 4, 13),
                side=OwnershipFillSide.BUY,
                quantity="15.000000",
            ),
            _source_fill(
                trade_id=4,
                event_id="synthetic-fill-sell-4",
                trade_day=date(2026, 4, 13),
                side=OwnershipFillSide.SELL,
                quantity="5.000000",
            ),
            _source_fill(
                trade_id=5,
                event_id="synthetic-fill-sell-5",
                trade_day=date(2026, 4, 14),
                side=OwnershipFillSide.SELL,
                quantity="12.000000",
            ),
        ),
        corporate_action_evidence=(),
        record_date_entitlement=RecordDateTaxEntitlementEvidence(
            kind=RecordDateTaxEntitlementRuleKind.ALL_COVERED_POSITIONS,
            rule_source_id="synthetic-entitlement-rule.v1",
            rule_source_sha256="7" * 64,
            qualified_total_quantity=Decimal("80.000000"),
            total_evidence_id="synthetic-entitlement-total.v1",
            total_evidence_sha256="8" * 64,
        ),
        convention=convention,
        date_rule_provenance=_runtime_provenance(convention),
        calendar=_calendar() if calendar is None else calendar,
        as_of=_AS_OF,
    )


def test_builder_preserves_zero_sessions_and_applies_same_day_net_after_fifo_record_position() -> (
    None
):
    result = build_simulated_tax_settlement_history(_request())

    history = result.history
    days = {row.settlement_date: row for row in history.settlement_days}
    assert history.covered_session_dates == (
        date(2026, 4, 8),
        date(2026, 4, 9),
        date(2026, 4, 10),
        date(2026, 4, 13),
        date(2026, 4, 14),
    )
    assert days[date(2026, 4, 10)].gross_purchase_quantity == Decimal("0.000000")
    assert days[date(2026, 4, 10)].gross_sale_quantity == Decimal("0.000000")
    assert days[date(2026, 4, 13)].gross_purchase_quantity == Decimal("15.000000")
    assert days[date(2026, 4, 13)].gross_sale_quantity == Decimal("5.000000")
    assert days[date(2026, 4, 13)].closing_eod_quantity == Decimal("90.000000")
    assert days[date(2026, 4, 14)].closing_eod_quantity == Decimal("78.000000")
    assert result.observation.date_observations
    assert result.observation.to_payload()["must_not_use_as_real_custody_proof"] is True


def test_builder_blocks_when_modeled_record_date_position_differs_from_ownership_proof() -> None:
    with pytest.raises(DeferredDividendTaxValidationError):
        build_simulated_tax_settlement_history(_request(sale_offset=1))


def test_builder_blocks_calendar_that_does_not_cover_the_zero_origin_prefix() -> None:
    complete = _calendar()
    shifted_snapshot = replace(
        complete.snapshot,
        coverage_start=date(2026, 4, 8),
        days=complete.snapshot.days[7:],
        content_hash="",
        record_digest="",
    )
    shifted_calendar = replace(complete, snapshot=shifted_snapshot)
    with pytest.raises(DeferredDividendTaxValidationError):
        build_simulated_tax_settlement_history(_request(calendar=shifted_calendar))


def test_reobservation_changes_only_observation_manifest_inputs_not_semantic_history() -> None:
    original = _request()
    first = build_simulated_tax_settlement_history(original)
    later_as_of = datetime(2026, 4, 15, 9, tzinfo=UTC)
    rule = replace(original.convention, known_at=datetime(2026, 4, 1, tzinfo=UTC))
    calendar = _calendar(response_at=datetime(2026, 4, 15, 8, tzinfo=UTC))
    later = replace(
        original,
        convention=rule,
        date_rule_provenance=_runtime_provenance(rule, as_of=later_as_of),
        calendar=calendar,
        as_of=later_as_of,
    )

    second = build_simulated_tax_settlement_history(later)

    assert first.history.source_revision_sha256 == second.history.source_revision_sha256
    assert first.history.settlement_calendar_sha256 == second.history.settlement_calendar_sha256
    assert first.observation.observation_sha256 != second.observation.observation_sha256


def test_build_rejects_observation_from_another_date_rule_or_history_prefix() -> None:
    request = _request()
    first = build_simulated_tax_settlement_history(request)
    changed_convention = replace(request.convention, version="2")
    changed_provenance = replace(
        request.date_rule_provenance,
        convention_sha256=changed_convention.semantic_sha256,
    )
    second = build_simulated_tax_settlement_history(
        replace(
            request,
            convention=changed_convention,
            date_rule_provenance=changed_provenance,
        )
    )

    assert first.history.settlement_date_rule_sha256 != second.history.settlement_date_rule_sha256
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(first, observation=second.observation)
    rebound = replace(
        second.observation,
        history_identity_sha256=first.observation.history_identity_sha256,
    )
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(first, observation=rebound)


def test_semantic_day_hashes_do_not_change_with_decimal_context_zero_signs() -> None:
    """Zero-change days keep one semantic identity under exact alternate rounding contexts."""
    request = _request()
    baseline = build_simulated_tax_settlement_history(request)
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_FLOOR
        alternate = build_simulated_tax_settlement_history(request)
    assert alternate.history.source_revision_sha256 == baseline.history.source_revision_sha256
    assert alternate.history.settlement_days == baseline.history.settlement_days


def test_observation_binds_calendar_validity_and_full_per_fill_rule_clocks() -> None:
    result = build_simulated_tax_settlement_history(_request())
    observation = result.observation
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(
            observation,
            calendar_publication_recorded_at=observation.read_at + timedelta(seconds=1),
        )
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(
            observation,
            convention_valid_until=observation.convention_valid_until + timedelta(days=1),
        )

    evidence_payload = observation.to_payload()["fills"][0]["date_evidence"]
    assert evidence_payload["convention_known_at"] == observation.date_rule.known_at.isoformat(
        timespec="microseconds"
    )
    assert evidence_payload["convention_valid_from"] == observation.convention_valid_from.isoformat(
        timespec="microseconds"
    )
    assert evidence_payload[
        "convention_valid_until"
    ] == observation.convention_valid_until.isoformat(timespec="microseconds")
    assert evidence_payload["read_at"] == observation.read_at.isoformat(timespec="microseconds")


def test_later_known_fill_does_not_change_an_earlier_target_prefix_identity() -> None:
    request = _request()
    first = build_simulated_tax_settlement_history(request)
    later_fill = _source_fill(
        trade_id=6,
        event_id="synthetic-fill-after-target",
        trade_day=date(2026, 4, 15),
        side=OwnershipFillSide.BUY,
        quantity="900.000000",
    )

    second = build_simulated_tax_settlement_history(
        replace(request, source_fills=(*request.source_fills, later_fill))
    )

    assert first.history.source_revision_sha256 == second.history.source_revision_sha256
    assert first.history.settlement_days == second.history.settlement_days


def test_equal_share_values_with_different_decimal_scales_have_same_semantic_identity() -> None:
    request = _request()
    represented_as_integer = tuple(
        replace(
            source,
            ownership_fill=replace(
                source.ownership_fill,
                quantity=source.ownership_fill.quantity.quantize(Decimal("1")),
            ),
        )
        for source in request.source_fills
    )

    first = build_simulated_tax_settlement_history(request)
    second = build_simulated_tax_settlement_history(
        replace(request, source_fills=represented_as_integer)
    )

    assert first.history.source_revision_sha256 == second.history.source_revision_sha256
    assert first.history.settlement_days == second.history.settlement_days


def test_changed_fill_inside_target_prefix_changes_semantic_identity() -> None:
    request = _request()
    original = request.source_fills[2]
    changed_fill = replace(original.ownership_fill, quantity=Decimal("16.000000"))
    changed_source = replace(
        original,
        ownership_fill=changed_fill,
        event_payload_sha256="9" * 64,
        source_snapshot_sha256="a" * 64,
    )
    changed_request = replace(
        request,
        source_fills=(*request.source_fills[:2], changed_source, *request.source_fills[3:]),
    )

    first = build_simulated_tax_settlement_history(request)
    second = build_simulated_tax_settlement_history(changed_request)

    assert first.history.source_revision_sha256 != second.history.source_revision_sha256


def test_builder_rejects_fill_from_another_owner_in_complete_history() -> None:
    request = _request()
    first = request.source_fills[0]
    changed_fill = replace(first.ownership_fill, owner_user_id=_OWNER_ID + 1)
    changed_source = replace(first, ownership_fill=changed_fill)

    with pytest.raises(DeferredDividendTaxValidationError):
        build_simulated_tax_settlement_history(
            replace(request, source_fills=(changed_source, *request.source_fills[1:]))
        )


def test_builder_rejects_rights_no_effect_instead_of_treating_it_as_purchase_history() -> None:
    request = _request()
    action = CorporateActionOwnershipEvidence(
        account_id=_ACCOUNT_ID,
        owner_user_id=_OWNER_ID,
        security_id=_SECURITY,
        asset_code=_ASSET,
        account_revision=1,
        entry_id=41,
        source_event_id="synthetic-rights-event.v1",
        source_revision_id="synthetic-rights-revision.v1",
        action_kind=CorporateActionKind.RIGHTS_ISSUE,
        stage_key="no_effect:rights_not_exercised",
        stage=CorporateActionStage.RIGHTS_NOT_EXERCISED,
        entry_kind=CorporateActionEntryKind.NO_EFFECT,
        stage_date=date(2026, 4, 13),
        posted_at=datetime(2026, 4, 13, 2, tzinfo=UTC),
        recorded_at=datetime(2026, 4, 13, 3, tzinfo=UTC),
        share_delta=Decimal("0.000000"),
        share_receivable_delta=Decimal("0.000000"),
        reversal_of_entry_id=None,
        supersedes_revision_id=None,
        evidence_sha256="c" * 64,
    )

    with pytest.raises(DeferredDividendTaxValidationError):
        build_simulated_tax_settlement_history(
            replace(request, corporate_action_evidence=(action,))
        )


@pytest.mark.parametrize(
    "changes",
    (
        {"account_kind": "real"},
        {"complete_through": _RECORD_DATE},
        {"record_date_ownership_proof": None},
        {"opening_anchor": None},
        {"record_date_entitlement": None},
        {"convention": None},
        {"date_rule_provenance": None},
        {"calendar": None},
        {"source_fills": []},
        {"source_fills": (None,)},
        {"corporate_action_evidence": []},
        {"corporate_action_evidence": (None,)},
    ),
)
def test_history_request_rejects_missing_or_untyped_explicit_inputs(
    changes: dict[str, object],
) -> None:
    request = _request()

    with pytest.raises(DeferredDividendTaxValidationError):
        replace(request, **changes)


@pytest.mark.parametrize(
    "provenance_changes",
    (
        {"definition_key": "config_center.other"},
        {"profile_version": 0},
        {"effective_at": _AS_OF + timedelta(seconds=1)},
        {"known_at": datetime(2026, 4, 1, 0, 0, 1, tzinfo=UTC)},
        {"effective_at": datetime(2026, 4, 2, 0, 0, 1, tzinfo=UTC)},
        {"snapshot_generated_at": datetime(2026, 4, 1, tzinfo=UTC)},
    ),
)
def test_runtime_date_rule_provenance_rejects_wrong_definition_version_or_future_clock(
    provenance_changes: dict[str, object],
) -> None:
    request = _request()

    with pytest.raises(DeferredDividendTaxValidationError):
        replace(request.date_rule_provenance, **provenance_changes)


def test_domain_clock_and_hash_helpers_fail_stably_on_unrepresentable_or_noncanonical_values() -> (
    None
):
    with pytest.raises(DeferredDividendTaxValidationError):
        tax_history_domain._aware(
            datetime.min.replace(tzinfo=timezone(timedelta(hours=14))),
            "synthetic clock",
        )
    with pytest.raises(DeferredDividendTaxValidationError):
        tax_history_domain._sha({"synthetic": "\ud800"})


def test_fill_source_and_date_observation_reject_unknown_or_mismatched_evidence() -> None:
    request = _request()
    source = request.source_fills[0]
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(source, ownership_fill=None)
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(source, observation_basis="unknown")
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(source, local_known_at=None)

    observation = build_simulated_tax_settlement_history(request).observation.date_observations[0]
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(observation, trade_id=0)
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(observation, date_evidence=None)
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(observation, source_event_id="different-event")


def test_observation_and_build_envelopes_reject_malformed_independent_evidence() -> None:
    valid = build_simulated_tax_settlement_history(_request())
    observation = valid.observation
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(observation, date_rule=None)
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(observation, calendar_content_sha256="not-a-prefixed-digest")
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(
            observation,
            calendar_recorded_at=observation.calendar_first_seen_at - timedelta(microseconds=1),
        )
    with pytest.raises(DeferredDividendTaxValidationError):
        replace(observation, date_observations=[])
    with pytest.raises(DeferredDividendTaxValidationError):
        SimulatedTaxSettlementHistoryBuild(history=None, observation=observation)
    with pytest.raises(DeferredDividendTaxValidationError):
        SimulatedTaxSettlementHistoryBuild(history=valid.history, observation=None)


def test_builder_rejects_invalid_anchor_cutoff_and_calendar_scope() -> None:
    request = _request()
    late_anchor = replace(
        request.opening_anchor,
        effective_at=datetime(2026, 4, 11, tzinfo=UTC),
        observed_at=datetime(2026, 4, 11, 1, tzinfo=UTC),
    )
    with pytest.raises(DeferredDividendTaxValidationError):
        build_simulated_tax_settlement_history(replace(request, opening_anchor=late_anchor))

    late_proof = replace(
        request.record_date_ownership_proof,
        ownership_snapshot_observed_at=request.as_of + timedelta(seconds=1),
    )
    with pytest.raises(DeferredDividendTaxValidationError):
        build_simulated_tax_settlement_history(
            replace(request, record_date_ownership_proof=late_proof)
        )

    source_snapshot = request.calendar.snapshot
    previous_open = date(2026, 3, 31)
    changed_days: list[ExchangeCalendarDay] = []
    for day in source_snapshot.days:
        is_open = day.is_open and day.calendar_date != _RECORD_DATE
        changed_days.append(replace(day, is_open=is_open, previous_open_date=previous_open))
        if is_open:
            previous_open = day.calendar_date
    missing_record_date = replace(
        source_snapshot,
        days=tuple(changed_days),
        content_hash="",
        record_digest="",
    )
    with pytest.raises(DeferredDividendTaxValidationError):
        build_simulated_tax_settlement_history(
            replace(request, calendar=replace(request.calendar, snapshot=missing_record_date))
        )

    with pytest.raises(DeferredDividendTaxValidationError):
        build_simulated_tax_settlement_history(
            replace(request, calendar=replace(request.calendar, publication=None))
        )

    publication = replace(request.calendar.publication, timezone_name="UTC")
    with pytest.raises(DeferredDividendTaxValidationError):
        build_simulated_tax_settlement_history(
            replace(request, calendar=replace(request.calendar, publication=publication))
        )


def test_builder_rejects_duplicate_future_unknown_and_unanchored_fills() -> None:
    request = _request()
    with pytest.raises(DeferredDividendTaxValidationError):
        build_simulated_tax_settlement_history(
            replace(request, source_fills=(*request.source_fills, request.source_fills[0]))
        )

    future_fill = _source_fill(
        trade_id=6,
        event_id="synthetic-fill-after-cutoff",
        trade_day=date(2026, 4, 15),
        side=OwnershipFillSide.BUY,
        quantity="1.000000",
    )
    future_at = datetime(2026, 4, 15, 10, tzinfo=UTC)
    future_fact = replace(
        future_fill.ownership_fill,
        occurred_at=future_at,
        recorded_at=future_at + timedelta(minutes=2),
    )
    future_fill = replace(
        future_fill,
        ownership_fill=future_fact,
        local_known_at=future_at + timedelta(minutes=1),
        interval_end_at=future_at,
        source_recorded_at=future_at + timedelta(minutes=2),
        trade_observed_at=future_at + timedelta(minutes=1),
    )
    with pytest.raises(DeferredDividendTaxValidationError):
        build_simulated_tax_settlement_history(
            replace(request, source_fills=(*request.source_fills, future_fill))
        )

    old_fill = _source_fill(
        trade_id=7,
        event_id="synthetic-fill-before-anchor",
        trade_day=date(2026, 3, 31),
        side=OwnershipFillSide.BUY,
        quantity="1.000000",
    )
    with pytest.raises(DeferredDividendTaxValidationError):
        build_simulated_tax_settlement_history(
            replace(request, source_fills=(*request.source_fills, old_fill))
        )

    misdated_fact = replace(
        request.source_fills[0].ownership_fill,
        execution_date=date(2026, 4, 9),
    )
    misdated_fill = replace(request.source_fills[0], ownership_fill=misdated_fact)
    with pytest.raises(DeferredDividendTaxValidationError):
        build_simulated_tax_settlement_history(
            replace(request, source_fills=(misdated_fill, *request.source_fills[1:]))
        )


def test_cash_corporate_action_rows_are_scope_checked_and_future_rows_are_not_hashed() -> None:
    request = _request()
    wrong_owner = _cash_action(owner_user_id=_OWNER_ID + 1)
    with pytest.raises(DeferredDividendTaxValidationError):
        build_simulated_tax_settlement_history(
            replace(request, corporate_action_evidence=(wrong_owner,))
        )

    first = build_simulated_tax_settlement_history(request)
    future_action = _cash_action(
        stage_date=date(2026, 4, 15),
        recorded_at=datetime(2026, 4, 15, 9, tzinfo=UTC),
    )
    second = build_simulated_tax_settlement_history(
        replace(request, corporate_action_evidence=(future_action,))
    )
    assert first.history.source_revision_sha256 == second.history.source_revision_sha256


def test_cash_entitlement_and_payment_do_not_revise_tax_ownership_facts() -> None:
    """Audited zero-share cash stages cannot create a new FIFO/tax-history revision."""
    request = _request()
    original = build_simulated_tax_settlement_history(request)
    entitlement = _cash_action()
    payment = replace(
        entitlement,
        account_revision=2,
        entry_id=43,
        stage_key="posting:cash_payment",
        stage=CorporateActionStage.CASH_PAYMENT,
        stage_date=_COMPLETE_THROUGH,
        evidence_sha256="e" * 64,
    )
    paid = build_simulated_tax_settlement_history(
        replace(request, corporate_action_evidence=(entitlement, payment))
    )
    assert paid.history.source_revision_sha256 == original.history.source_revision_sha256
    assert paid.history.settlement_days == original.history.settlement_days


def test_negative_daily_net_is_rejected_after_fifo_record_position() -> None:
    request = _request()
    original = request.source_fills[4]
    oversized_sale = replace(original.ownership_fill, quantity=Decimal("100.000000"))
    changed_source = replace(original, ownership_fill=oversized_sale)
    sources = (*request.source_fills[:4], changed_source)

    with pytest.raises(DeferredDividendTaxValidationError):
        build_simulated_tax_settlement_history(replace(request, source_fills=sources))


@pytest.mark.parametrize(
    "clock_case",
    ("unchanged", "later-valid", "backwards", "naive", "rule-expired", "calendar-expired"),
)
def test_application_reads_exact_owner_prefix_with_current_rule_calendar_and_server_clock(
    clock_case: str,
) -> None:
    request = _request()
    checked_at = _AS_OF
    if clock_case == "later-valid":
        checked_at += timedelta(seconds=1)
    elif clock_case == "backwards":
        checked_at -= timedelta(microseconds=1)
    elif clock_case == "naive":
        checked_at = checked_at.replace(tzinfo=None)
    elif clock_case == "rule-expired":
        checked_at = request.convention.valid_until
    elif clock_case == "calendar-expired":
        assert request.calendar.publication is not None
        checked_at += timedelta(seconds=1)
        request = replace(
            request,
            calendar=replace(
                request.calendar,
                publication=replace(request.calendar.publication, reference_valid_until=checked_at),
            ),
        )
    ownership_result = RecordDateOwnershipHistoryRead(
        proof=request.record_date_ownership_proof,
        opening_anchor=request.opening_anchor,
        source_fills=request.source_fills,
        corporate_action_evidence=(),
    )

    class _Inputs:
        database_alias = "default"

        def read_record_date_history(self, **scope: object) -> RecordDateOwnershipHistoryRead:
            assert scope["account_id"] == _ACCOUNT_ID
            assert scope["owner_user_id"] == _OWNER_ID
            assert scope["security_id"] == _SECURITY
            assert scope["asset_code"] == _ASSET
            assert scope["record_date"] == _RECORD_DATE
            assert scope["as_of"] == _AS_OF
            return ownership_result

    class _DateRule:
        def read_current(self, **scope: object) -> SimulatedTaxDateConventionRead:
            assert scope == {
                "environment": "synthetic-test",
                "as_of": _AS_OF,
                "physical_account_id": _ACCOUNT_ID,
                "canonical_account_id": "synthetic-account-7",
                "owner_user_id": _OWNER_ID,
            }
            return SimulatedTaxDateConventionRead(
                request.convention,
                request.date_rule_provenance,
            )

    class _Calendar:
        def get_effective_execution_calendar(
            self,
            *,
            exchange: str,
            as_of: datetime,
            coverage_start: date | None,
        ) -> ExecutionCalendarEvidence:
            assert exchange == "SYNTHETIC"
            assert as_of == _AS_OF
            assert coverage_start == date(2026, 4, 1)
            return request.calendar

    class _Clock:
        reads = 0

        def now(self) -> datetime:
            self.reads += 1
            return _AS_OF if self.reads == 1 else checked_at

    use_case = ReadSimulatedTaxSettlementHistoryUseCase(
        input_reader=_Inputs(),
        date_rule_reader=_DateRule(),
        calendar_reader=_Calendar(),
        clock=_Clock(),
        using="default",
    )
    query = SimulatedTaxSettlementHistoryQuery(
        environment="synthetic-test",
        account_kind="simulated",
        physical_account_id=_ACCOUNT_ID,
        canonical_account_id="synthetic-account-7",
        owner_user_id=_OWNER_ID,
        security_id=_SECURITY,
        asset_code=_ASSET,
        record_date=_RECORD_DATE,
        complete_through=_COMPLETE_THROUGH,
        record_date_entitlement=request.record_date_entitlement,
    )
    if clock_case in {"backwards", "naive", "rule-expired", "calendar-expired"}:
        with pytest.raises(BusinessLogicError):
            use_case.execute(query)
        return
    result = use_case.execute(query)

    assert result.history.record_date_ownership_proof == request.record_date_ownership_proof
    assert result.history.opening_anchor == request.opening_anchor
    assert result.observation.date_rule.snapshot_id == "synthetic-snapshot.v1"
    assert result.observation.read_at == _AS_OF


def test_builder_rejects_an_unfinished_completion_day_instead_of_publishing_zero_activity() -> None:
    request = _request()
    # The record date is already past; today's unfinished activity is still unknown.
    with pytest.raises(DeferredDividendTaxValidationError):
        build_simulated_tax_settlement_history(replace(request, complete_through=date(2026, 4, 15)))


def test_application_rejects_current_reader_alias_mismatch() -> None:
    class _Inputs:
        database_alias = "other"

    class _Unused:
        def read_current(self, **scope: object) -> SimulatedTaxDateConventionRead:
            raise AssertionError("a bad-alias use case must not read the rule")

    class _Calendar:
        pass

    class _Clock:
        def now(self) -> datetime:
            return _AS_OF

    with pytest.raises(BusinessLogicError, match="share one database alias"):
        ReadSimulatedTaxSettlementHistoryUseCase(
            input_reader=_Inputs(),
            date_rule_reader=_Unused(),
            calendar_reader=_Calendar(),
            clock=_Clock(),
            using="default",
        )
