"""Ordinary-owner reference-holding return across retained raw ex-date closes.

Source notices and exact price-provider responses are explicitly synthetic.
The capture, retention, publication, owner consent, current-window, posting,
and readback paths remain the real production compositions.
"""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol, cast

import pytest
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
)
from apps.config_center.application.runtime_public import activate_runtime_profile_patch
from apps.config_center.application.runtime_value_evidence import (
    read_active_runtime_value_evidence,
)
from apps.data_center.application.public_published_queries import (
    get_published_price_bar_source,
    get_retained_historical_price_source,
)
from apps.data_center.domain.market_time import latest_closed_cn_market_session
from apps.data_center.domain.publication_lanes import M1_REBALANCE_REFERENCE_PUBLICATION_KEY
from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEventReadScope,
    SecurityDisclosureExchange,
)
from apps.data_center.security_disclosure_capture_composition import (
    make_security_disclosure_event_reader,
)
from apps.simulated_trading import corporate_action_owner_workflow_readback as workflow_readback
from apps.simulated_trading.corporate_action_nav_mark_composition import (
    build_corporate_action_nav_raw_mark_reader,
)
from apps.simulated_trading.corporate_action_owner_balance_composition import (
    OwnerCorporateActionBalanceReadback,
)
from apps.simulated_trading.corporate_action_owner_ledger_composition import (
    OwnerCorporateActionPostingState,
)
from apps.simulated_trading.corporate_action_tax_policy_composition import (
    SIMULATED_DIVIDEND_TAX_POLICY_KEY,
)
from apps.simulated_trading.infrastructure.models import PositionModel
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from tests.component.simulated_trading import test_corporate_action_owner_nav_postgres as owner_nav
from tests.component.simulated_trading import (
    test_corporate_action_owner_workflow_http_postgres as owner_workflow,
)
from tests.component.simulated_trading import (
    test_retained_historical_price_source_postgres as retained_prices,
)
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash03_auto_calendar_fixture import (
    FormalCalendarFixture,
    persist_auto_uow_formal_calendar,
)
from tests.support.ash05_owner_market_calendar import (
    OwnerModelCalendarInstaller,
)
from tests.support.ash05_owner_market_calendar import (  # noqa: F401
    owner_model_calendar as owner_model_calendar,
)
from tests.support.ash05_owner_workflow_native_sources import (
    cash_distribution_capture,
    install_synthetic_szse_capture_transport,
    owner_workflow_statutory_bodies,
)
from tests.support.ash05_owner_workflow_native_world import (
    OwnerWorkflowNativeWorld,
    build_owner_workflow_native_world,
)
from tests.support.ash07_native_runtime_role import isolated_ash07_runtime_role
from tests.support.ash07_owner_account_authority import ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS
from tests.support.simulated_tax_model_native_context import _TIMEZONE
from tests.support.simulated_tax_model_native_sources import isolated_task_channels

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
)

_WORKFLOW_URLCONF = "tests.support.ash05_owner_workflow_test_urls"


@pytest.fixture
def actual_runtime_role(transactional_db: None, tmp_path: Path) -> Iterator[dict[str, object]]:
    """Run the retained-source and owner journey under the actual restricted runtime login."""
    del transactional_db
    if connection.vendor != "postgresql":
        yield {}
        return
    database_name = connection.settings_dict.get("NAME")
    if database_name == "ash05_tax_payment_basis_qa":
        target_profile: Literal["ash05_local", "ash05_ci"] = "ash05_local"
    elif database_name == "ash05_owner_goldens_test_ci":
        target_profile = "ash05_ci"
    else:
        raise RuntimeError("runtime-role fixture refuses an unassigned PostgreSQL test database")
    with isolated_ash07_runtime_role(
        tmp_path / "runtime-role", target_profile=target_profile
    ) as report:
        yield report


class _RawCloseSelection(Protocol):
    """Expose the exact retained M1 identity used by these owner journeys."""

    trade_date: date
    publication_id: str
    close: Decimal


def _calendar_and_recent_sessions(
    world: OwnerWorkflowNativeWorld,
) -> tuple[FormalCalendarFixture, tuple[date, ...], date]:
    """Read the current formal SZSE calendar and return its latest closed sessions."""
    calendar = persist_auto_uow_formal_calendar(
        as_of=timezone.now().astimezone(UTC),
        exchange="SZSE",
        timezone_name=_TIMEZONE,
        live_clock=True,
        require_current_open_session=False,
        bootstrap_runtime=False,
        live_coverage_start=world.anchor_date,
    )
    if calendar.dataset_key != world.calendar_dataset_key:
        raise AssertionError("owner and price fixtures do not share the formal calendar dataset")
    activate_runtime_profile_patch(
        environment="development",
        patch={
            "config_center.market.exchange_timezone_map": {
                "SZ": _TIMEZONE,
                "SZSE": _TIMEZONE,
            }
        },
        actor="ash05-reference-return-calendar-scope",
        reason="retain explicit source-exchange and rule-market calendar timezones",
    )
    open_sessions = frozenset(item.calendar_date for item in calendar.snapshot.days if item.is_open)
    latest_closed = latest_closed_cn_market_session(
        timezone.now().astimezone(UTC), open_sessions=open_sessions
    )
    if latest_closed is None:
        raise AssertionError("formal calendar has no closed SZSE session at the actual clock")
    closed = tuple(sorted(day for day in open_sessions if day <= latest_closed))
    if len(closed) < 2:
        raise AssertionError("formal calendar does not cover two closed price sessions")
    return calendar, closed, latest_closed


def _extend_synthetic_tax_candidate_through_record_date(
    *,
    world: OwnerWorkflowNativeWorld,
    record_date: date,
) -> None:
    """Extend only this synthetic candidate to the exact corrected event date.

    The seed world intentionally activates a finite tax candidate through its
    original record date.  This reference-return case creates a distinct,
    synthetic direct successor with a later record date, so the test must
    explicitly amend that modelled applicability window before asking the
    production coverage reader to inspect it.
    """
    as_of = timezone.now().astimezone(UTC)
    evidence = read_active_runtime_value_evidence(
        environment="development",
        definition_key=SIMULATED_DIVIDEND_TAX_POLICY_KEY,
        as_of=as_of,
    )
    if evidence is None or type(evidence.value) is not dict:
        raise AssertionError("synthetic tax candidate evidence is unavailable")
    policy_payload = cast(dict[str, object], deepcopy(evidence.value))
    raw_rows = policy_payload.get("policies")
    if type(raw_rows) is not list or len(raw_rows) != 1:
        raise AssertionError("synthetic tax candidate scope is not unique")
    row = raw_rows[0]
    if type(row) is not dict:
        raise AssertionError("synthetic tax candidate scope is malformed")
    candidate = cast(dict[str, object], row)
    expected_identity = {
        "account_kind": "simulated",
        "physical_account_id": world.account_id,
        "canonical_account_id": world.canonical_account_id,
        "owner_user_id": world.owner.owner.pk,
        "security_id": world.security_id,
        "asset_code": world.asset_code,
        "candidate_id": f"ash05-synthetic-tax-candidate-{world.account_id}",
    }
    if any(candidate.get(key) != value for key, value in expected_identity.items()):
        raise AssertionError("synthetic tax candidate is bound to another owner or instrument")
    lower_raw = candidate.get("record_date_from")
    upper_raw = candidate.get("record_date_through")
    if type(lower_raw) is not str or type(upper_raw) is not str:
        raise AssertionError("synthetic tax candidate has no finite record-date scope")
    try:
        lower = date.fromisoformat(lower_raw)
        previous_upper = date.fromisoformat(upper_raw)
    except ValueError as error:
        raise AssertionError("synthetic tax candidate dates are malformed") from error
    if not lower <= previous_upper < record_date:
        raise AssertionError("test successor date is not a finite extension of the seed scope")
    candidate["record_date_through"] = record_date.isoformat()
    activate_runtime_profile_patch(
        environment="development",
        patch={SIMULATED_DIVIDEND_TAX_POLICY_KEY: policy_payload},
        actor="ash05-synthetic-reference-tax-date-scope",
        reason="extend one explicit synthetic candidate through its corrected record date",
        expected_active_profile_id=evidence.profile_id,
        expected_active_profile_version=evidence.profile_version,
        expected_active_profile_hash=evidence.profile_content_hash,
        expected_active_snapshot_hash=evidence.snapshot_hash,
    )


def _publish_reference_prices(
    *,
    world: OwnerWorkflowNativeWorld,
    calendar: FormalCalendarFixture,
    opening_date: date,
    ex_date: date,
    latest_closed: date,
    opening_price: Decimal,
    ex_price: Decimal,
    latest_price: Decimal,
) -> tuple[_RawCloseSelection, ...]:
    """Capture exact synthetic pre-ex, ex, and current closes through M1."""
    target_prices: dict[date, Decimal] = {
        opening_date: opening_price,
        ex_date: ex_price,
    }
    if latest_closed != ex_date:
        target_prices[latest_closed] = latest_price
    selections: list[_RawCloseSelection] = []
    for target_date, price in sorted(target_prices.items()):
        selections.append(
            owner_nav._publish_synthetic_raw_close_capture(
                world=world,
                calendar=calendar,
                target_trade_date=target_date,
                close=price,
            )
        )
    owner_nav._activate_raw_mark_policy(
        world=world,
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
    )
    return tuple(selections)


def _assert_raw_source_selections(
    *,
    world: OwnerWorkflowNativeWorld,
    selections: tuple[_RawCloseSelection, ...],
    latest_closed: date,
) -> None:
    """Verify old prices via exact retained IDs and keep current NAV on latest close."""
    cutoff = timezone.now().astimezone(UTC)
    latest = next(item for item in selections if item.trade_date == latest_closed)
    current = get_published_price_bar_source(
        world.asset_code,
        trade_date=latest_closed,
        knowledge_cutoff=cutoff,
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
    )
    if current.evidence is None:
        raise AssertionError("latest closed raw price is unavailable")
    assert current.evidence.publication_id == latest.publication_id
    assert current.evidence.values.close == latest.close
    assert current.evidence.adjustment.value == "none"
    assert current.evidence.source_observed_at is None

    for selection in selections:
        source = get_retained_historical_price_source(
            world.asset_code,
            trade_date=selection.trade_date,
            publication_id=selection.publication_id,
            expected_publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
            knowledge_cutoff=cutoff,
            environment="development",
        )
        if source.evidence is None:
            raise AssertionError("exact raw publication could not be read at its original identity")
        evidence = source.evidence
        fact = evidence.price
        assert fact.publication_id == selection.publication_id
        assert fact.trade_date == selection.trade_date
        assert fact.values.close == selection.close
        assert fact.adjustment.value == "none"
        assert fact.source_observed_at is None
        evidence.activation.pair.verify_at_cutoff(as_of=cutoff)

    # Owner refresh may replace the test operator's runtime profile. Activate
    # the independent NAV-only policy after that refresh before checking current.
    owner_nav._activate_raw_mark_policy(
        world=world,
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
    )
    mark = build_corporate_action_nav_raw_mark_reader(
        runtime_environment="development",
        calendar_dataset_key=world.calendar_dataset_key,
    ).read_current_mark(owner_nav._query(world))
    if mark is None:
        raise AssertionError("independent raw NAV mark is unavailable")
    assert mark.trade_date == latest_closed
    assert mark.price == latest.close
    assert mark.source_observed_at is None
    assert mark.must_not_use_for_decision is True


def _issue_cash_only_consent(world: OwnerWorkflowNativeWorld) -> None:
    """Grant only the independently selectable V3 cash-stage capability."""
    path = owner_workflow._CONSENT_ROOT.format(account_id=world.account_id)
    selected = {
        "cash_dividend": True,
        "share_distribution": False,
        "rights_not_exercised": False,
        "tax_assessment": False,
        "tax_withholding": False,
    }
    prepared = owner_workflow._post(
        world.owner.client,
        path + "prepare/",
        selected,
        owner_workflow._headers(world),
    )
    expected = [Capability.CASH_STAGE_WRITE.value]
    if prepared.get("selected_capabilities") != expected:
        raise AssertionError("ordinary owner did not select only the cash-stage capability")
    continuation = prepared.get("continuation")
    if not isinstance(continuation, dict):
        raise AssertionError("owner consent continuation is unavailable")
    inputs = continuation.get("input")
    if not isinstance(inputs, dict):
        raise AssertionError("owner consent continuation input is unavailable")
    token = inputs.get("consent_token")
    if not isinstance(token, str) or not token:
        raise AssertionError("owner consent token is unavailable")
    confirmed = owner_workflow._post(
        world.owner.client,
        path,
        {"consent_token": token, "confirmed": True},
        owner_workflow._headers(world),
    )
    if confirmed.get("selected_capabilities") != expected:
        raise AssertionError("cash consent confirmation changed the selected capability set")
    if confirmed.get("grant_schema") != SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA:
        raise AssertionError("cash workflow did not retain the explicit V3 grant schema")


def _read_reference_row(
    world: OwnerWorkflowNativeWorld, *, latest_closed: date
) -> dict[str, object]:
    """Read the owner endpoint and require the display read to remain side-effect free."""
    owner_nav._activate_raw_mark_policy(
        world=world,
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
    )
    before = retained_prices._read_only_effects(world)
    evidence: dict[str, object] = {}
    read_balance = workflow_readback.read_locked_owner_corporate_action_balance

    def observe_balance(
        *,
        account: SimulatedAccountModel,
        canonical_account_id: str,
        ledger: OwnerCorporateActionPostingState,
        environment: str,
        using: str = "default",
    ) -> OwnerCorporateActionBalanceReadback:
        """Observe bounded proof states without replacing any source or result."""
        result = read_balance(
            account=account,
            canonical_account_id=canonical_account_id,
            ledger=ledger,
            environment=environment,
            using=using,
        )
        coverage = result.tax_coverage
        evidence.update(
            coverage_status=coverage.coverage_status.value if coverage is not None else None,
            coverage_reasons=(
                [reason.value for reason in coverage.reason_codes] if coverage is not None else []
            ),
            mark_count=len(result.marks),
            entitlements=(
                None
                if result.entitlements is None
                else [
                    {
                        "cash_complete": item.cash_complete,
                        "shares_complete": item.shares_complete,
                        "reference_count": (
                            None
                            if item.current_entitlement_references is None
                            else len(item.current_entitlement_references)
                        ),
                    }
                    for item in result.entitlements
                ]
            ),
        )
        return result

    with pytest.MonkeyPatch.context() as observation:
        observation.setattr(
            workflow_readback, "read_locked_owner_corporate_action_balance", observe_balance
        )
        payload = owner_workflow._read(
            world.owner.client,
            owner_workflow._API_ROOT.format(account_id=world.account_id),
            owner_workflow._headers(world),
        )
    if retained_prices._read_only_effects(world) != before:
        raise AssertionError("reference-return GET changed original financial or Audit rows")
    summary = payload.get("reference_return_summary")
    rows = payload.get("reference_returns")
    if not isinstance(summary, str) or not summary.strip() or not isinstance(rows, list):
        raise AssertionError("owner reference-return summary is missing")
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise AssertionError("owner reference-return row is incomplete or ambiguous")
    if rows[0].get("status") != "complete":
        raise AssertionError(
            "owner reference-return row is not complete: "
            f"reason={rows[0].get('reason_code')!r}, "
            f"tax_coverage={payload.get('tax_coverage_status')!r}, "
            f"valuation_dates={payload.get('valuation_trade_dates')!r}, evidence={evidence!r}"
        )
    checked_raw = payload.get("checked_at")
    reference_cutoff_raw = rows[0].get("knowledge_cutoff")
    if type(checked_raw) is not str or type(reference_cutoff_raw) is not str:
        raise AssertionError("owner and reference snapshot clocks are missing")
    assert datetime.fromisoformat(reference_cutoff_raw) <= datetime.fromisoformat(checked_raw)
    if payload.get("valuation_trade_dates") != [latest_closed.isoformat()]:
        raise AssertionError("current account valuation did not remain on the latest closed mark")
    return rows[0]


def _amount(row: dict[str, object], key: str) -> Decimal:
    """Parse one exact public decimal string without accepting floats or nulls."""
    value = row.get(key)
    if type(value) is not str:
        raise AssertionError("reference-return amount is not an exact string")
    try:
        return Decimal(value)
    except ArithmeticError as error:
        raise AssertionError("reference-return amount is not a decimal") from error


def _assert_reference_row(
    *,
    world: OwnerWorkflowNativeWorld,
    selections: tuple[_RawCloseSelection, ...],
    latest_closed: date,
    record_date: date,
    reference_quantity: Decimal,
    ex_date: date,
    opening_date: date,
    closing_date: date,
    opening_price: Decimal,
    closing_price: Decimal,
    closing_cash: Decimal,
    closing_dividend_receivable: Decimal,
    closing_physical_shares: Decimal,
    closing_share_receivable: Decimal,
    expected_value: Decimal,
) -> dict[str, object]:
    """Check gross ex-rights continuity and explicit current-knowledge semantics."""
    row = _read_reference_row(world, latest_closed=latest_closed)
    assert row.get("account_id") == world.account_id
    assert row.get("asset_code") == world.asset_code
    assert row.get("status") == "complete"
    assert row.get("reason_code") is None
    assert row.get("record_date") == record_date.isoformat()
    assert row.get("ex_date") == ex_date.isoformat()
    assert row.get("opening_date") == opening_date.isoformat()
    assert row.get("closing_date") == closing_date.isoformat()
    assert _amount(row, "reference_quantity") == reference_quantity
    assert _amount(row, "opening_price") == opening_price
    assert _amount(row, "closing_price") == closing_price
    assert _amount(row, "opening_value") == expected_value
    assert _amount(row, "closing_value") == expected_value
    assert _amount(row, "wealth_change") == Decimal("0")
    assert _amount(row, "closing_cash") == closing_cash
    assert _amount(row, "closing_dividend_receivable") == closing_dividend_receivable
    assert _amount(row, "closing_physical_shares") == closing_physical_shares
    assert _amount(row, "closing_share_receivable") == closing_share_receivable
    assert row.get("knowledge_semantics") == "currently_known_reference_holding"
    assert row.get("return_basis") == "gross_unreinvested_record_date_holding"
    assert row.get("must_not_use_for_decision") is True
    assert row.get("source_observed_at") is None
    selected_by_date = {item.trade_date: item for item in selections}
    if opening_date not in selected_by_date or closing_date not in selected_by_date:
        raise AssertionError("reference-return dates have no exact captured publication")
    assert row.get("price_publication_ids") == [
        selected_by_date[opening_date].publication_id,
        selected_by_date[closing_date].publication_id,
    ]
    cutoff_raw = row.get("knowledge_cutoff")
    if type(cutoff_raw) is not str:
        raise AssertionError("reference-return knowledge cutoff is unavailable")
    try:
        cutoff = datetime.fromisoformat(cutoff_raw)
    except ValueError as error:
        raise AssertionError("reference-return knowledge cutoff is malformed") from error
    if (
        cutoff.tzinfo is None
        or cutoff.utcoffset() is None
        or cutoff > timezone.now().astimezone(UTC)
    ):
        raise AssertionError("reference-return knowledge cutoff is not an original known clock")
    clock_arrays: dict[str, list[datetime]] = {}
    for key in ("price_interval_end_ats", "price_source_available_ats"):
        raw_times = row.get(key)
        if not isinstance(raw_times, list) or len(raw_times) != 2:
            raise AssertionError("reference-return raw-price clocks are incomplete")
        parsed_times: list[datetime] = []
        for raw_time in raw_times:
            if type(raw_time) is not str:
                raise AssertionError("reference-return raw-price clock is malformed")
            try:
                parsed = datetime.fromisoformat(raw_time)
            except ValueError as error:
                raise AssertionError("reference-return raw-price clock is malformed") from error
            if parsed.tzinfo is None or parsed.utcoffset() is None or parsed > cutoff:
                raise AssertionError("reference-return raw-price clock is not known by cutoff")
            parsed_times.append(parsed)
        clock_arrays[key] = parsed_times
    if any(
        interval > source_known
        for interval, source_known in zip(
            clock_arrays["price_interval_end_ats"],
            clock_arrays["price_source_available_ats"],
            strict=True,
        )
    ):
        raise AssertionError("reference-return original price clocks are out of order")
    valid_until_raw = row.get("valid_until")
    if type(valid_until_raw) is not str:
        raise AssertionError("reference-return finite source deadline is missing")
    try:
        valid_until = datetime.fromisoformat(valid_until_raw)
    except ValueError as error:
        raise AssertionError("reference-return finite source deadline is malformed") from error
    if valid_until.tzinfo is None or valid_until.utcoffset() is None or not cutoff < valid_until:
        raise AssertionError("reference-return source lease is no longer current")
    return row


def test_owner_cash_reference_return_brackets_ex_date_and_keeps_late_payment_late(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    actual_runtime_role: dict[str, object],
    owner_model_calendar: OwnerModelCalendarInstaller,
) -> None:
    """Read a fixed record-date cash entitlement before and after real payment posting."""
    if connection.vendor != "postgresql":
        pytest.skip("owner cash reference return requires the assigned migrated PostgreSQL DB")
    assert actual_runtime_role.get("runtime_acl_verified") is True
    with override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF), isolated_task_channels():
        # The recent record session must follow the seed SELL's modeled tax
        # settlement.  Trading on the record session remains unsupported and
        # must keep the production history reader blocked.
        world = build_owner_workflow_native_world(
            monkeypatch=monkeypatch, tmp_path=tmp_path, history_weeks=2
        )
        calendar, sessions, latest_closed = _calendar_and_recent_sessions(world)
        owner_model_calendar(calendar)
        opening_date, ex_date = sessions[-2:]
        assert world.settlement_date < opening_date
        _extend_synthetic_tax_candidate_through_record_date(
            world=world,
            record_date=opening_date,
        )
        selections = _publish_reference_prices(
            world=world,
            calendar=calendar,
            opening_date=opening_date,
            ex_date=ex_date,
            latest_closed=latest_closed,
            opening_price=Decimal("10.00"),
            ex_price=Decimal("9.80"),
            latest_price=Decimal("9.80"),
        )

        initial = owner_workflow._refresh(world)
        previous_event_id = owner_workflow._event_id(world, payload=initial)
        successor = cash_distribution_capture(
            asset_code=world.asset_code,
            published_on=world.decision_date,
            record_date=opening_date,
            ex_date=ex_date,
            payment_date=ex_date,
            cash_per_ten="2.00",
            title_suffix="（更正后）",
        )
        successor.announcement_id = world.capture.announcement_id + 1
        if b"%ASH05 synthetic fixture" not in successor.pdf_body:
            raise AssertionError("cash notice is not labeled as synthetic fixture content")
        install_synthetic_szse_capture_transport(
            monkeypatch,
            world.capture,
            statutory_documents=owner_workflow_statutory_bodies(),
            additional_captures=(successor,),
        )
        refreshed = owner_workflow._refresh(world)
        event_id = owner_workflow._event_id(world, payload=refreshed)
        owner_workflow._assert_direct_retained_source_successor(
            world=world,
            previous_event_id=previous_event_id,
            current_event_id=event_id,
        )
        retained_events = make_security_disclosure_event_reader(using="default").execute(
            SecurityDisclosureEventReadScope(
                as_of=timezone.now(),
                exchange=SecurityDisclosureExchange.SZSE,
                asset_code=world.asset_code,
            )
        )
        successor_events = tuple(
            record.event for record in retained_events if record.event.source_event_id == event_id
        )
        assert len(successor_events) == 1
        successor_revision_id = successor_events[0].source_revision_id
        _assert_raw_source_selections(
            world=world,
            selections=selections,
            latest_closed=latest_closed,
        )

        account = SimulatedAccountModel.objects.get(pk=world.account_id)
        starting_cash = account.current_cash
        _issue_cash_only_consent(world)
        entitlement = owner_workflow._prepare_and_confirm(
            world,
            event_id=event_id,
            action="cash_entitlement",
            exact_retry=False,
        )
        assert entitlement.get("outcome") == "success"
        posting = owner_workflow.CorporateActionPostingModel.objects.get(
            account_id=world.account_id,
            source_event_id=previous_event_id,
            stage="cash_entitlement",
            entry_kind="posting",
        )
        assert posting.source_record_id == event_id
        assert posting.source_revision_id == successor_revision_id
        assert posting.eligible_quantity == Decimal("70.000000")
        assert posting.cash_amount == Decimal("14.00")
        owner_workflow._refresh(world)
        before_payment = _assert_reference_row(
            world=world,
            selections=selections,
            latest_closed=latest_closed,
            record_date=opening_date,
            reference_quantity=Decimal("70.000000"),
            ex_date=ex_date,
            opening_date=opening_date,
            closing_date=ex_date,
            opening_price=Decimal("10.00"),
            closing_price=Decimal("9.80"),
            closing_cash=Decimal("0.00"),
            closing_dividend_receivable=Decimal("14.00"),
            closing_physical_shares=Decimal("70.000000"),
            closing_share_receivable=Decimal("0.000000"),
            expected_value=Decimal("700.00"),
        )

        _issue_cash_only_consent(world)
        payment = owner_workflow._prepare_and_confirm(
            world,
            event_id=event_id,
            action="cash_payment",
            exact_retry=False,
        )
        assert payment.get("outcome") == "success"
        payment_row = owner_workflow.CorporateActionPostingModel.objects.get(
            account_id=world.account_id,
            source_event_id=previous_event_id,
            stage="cash_payment",
            entry_kind="posting",
        )
        assert payment_row.source_record_id == event_id
        assert payment_row.source_revision_id == successor_revision_id
        assert payment_row.cash_delta == Decimal("14.00")
        assert payment_row.cash_receivable_delta == Decimal("-14.00")
        account.refresh_from_db()
        assert account.current_cash == starting_cash + Decimal("14.00")
        owner_workflow._refresh(world)
        after_payment = _assert_reference_row(
            world=world,
            selections=selections,
            latest_closed=latest_closed,
            record_date=opening_date,
            reference_quantity=Decimal("70.000000"),
            ex_date=ex_date,
            opening_date=opening_date,
            closing_date=ex_date,
            opening_price=Decimal("10.00"),
            closing_price=Decimal("9.80"),
            closing_cash=Decimal("0.00"),
            closing_dividend_receivable=Decimal("14.00"),
            closing_physical_shares=Decimal("70.000000"),
            closing_share_receivable=Decimal("0.000000"),
            expected_value=Decimal("700.00"),
        )
        amount_fields = frozenset(
            {
                "reference_quantity",
                "opening_price",
                "closing_price",
                "opening_value",
                "closing_value",
                "wealth_change",
                "closing_cash",
                "closing_dividend_receivable",
                "closing_physical_shares",
                "closing_share_receivable",
            }
        )
        for field in (
            "account_id",
            "asset_code",
            "status",
            "reason_code",
            "record_date",
            "ex_date",
            "opening_date",
            "closing_date",
            "reference_quantity",
            "opening_price",
            "closing_price",
            "opening_value",
            "closing_value",
            "wealth_change",
            "closing_cash",
            "closing_dividend_receivable",
            "closing_physical_shares",
            "closing_share_receivable",
            "knowledge_semantics",
            "return_basis",
            "must_not_use_for_decision",
            "source_observed_at",
            "source_event_id",
            "logical_source_event_id",
            "source_revision_id",
            "source_body_sha256",
            "event_content_sha256",
            "price_publication_ids",
            "price_interval_end_ats",
            "price_source_available_ats",
        ):
            if field in amount_fields:
                assert _amount(after_payment, field) == _amount(before_payment, field)
            else:
                assert after_payment.get(field) == before_payment.get(field)
        before_cutoff = datetime.fromisoformat(str(before_payment["knowledge_cutoff"]))
        after_cutoff = datetime.fromisoformat(str(after_payment["knowledge_cutoff"]))
        assert before_cutoff < after_cutoff
        for row in (before_payment, after_payment):
            cutoff = datetime.fromisoformat(str(row["knowledge_cutoff"]))
            deadline = datetime.fromisoformat(str(row["valid_until"]))
            assert cutoff.tzinfo is not None and cutoff.utcoffset() is not None
            assert deadline.tzinfo is not None and deadline.utcoffset() is not None
            assert cutoff < deadline
        assert b"%ASH05 synthetic fixture" in successor.pdf_body


def test_owner_share_reference_return_counts_ex_date_rights_once_across_real_stages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    actual_runtime_role: dict[str, object],
    owner_model_calendar: OwnerModelCalendarInstaller,
) -> None:
    """Read the fixed record-date basket through real entitlement/delivery/release writes."""
    if connection.vendor != "postgresql":
        pytest.skip("owner share reference return requires the assigned migrated PostgreSQL DB")
    assert actual_runtime_role.get("runtime_acl_verified") is True
    with override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF), isolated_task_channels():
        world = build_owner_workflow_native_world(
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            capture_kind="share",
        )
        calendar, sessions, latest_closed = _calendar_and_recent_sessions(world)
        owner_model_calendar(calendar)
        if world.settlement_date > latest_closed or world.settlement_date not in sessions:
            raise AssertionError("synthetic share effective date has not reached a closed session")
        prior_sessions = tuple(day for day in sessions if day < world.settlement_date)
        if not prior_sessions:
            raise AssertionError("formal calendar has no pre-ex closed session")
        opening_date = prior_sessions[-1]
        ex_date = world.settlement_date
        selections = _publish_reference_prices(
            world=world,
            calendar=calendar,
            opening_date=opening_date,
            ex_date=ex_date,
            latest_closed=latest_closed,
            opening_price=Decimal("11.00"),
            ex_price=Decimal("10.00"),
            latest_price=Decimal("10.10"),
        )

        refreshed = owner_workflow._refresh(world)
        event_id = owner_workflow._event_id(world, payload=refreshed)
        _assert_raw_source_selections(
            world=world,
            selections=selections,
            latest_closed=latest_closed,
        )
        if not (world.share_delivery_date <= world.share_sellable_date <= world.decision_date):
            raise AssertionError("synthetic share transfer dates are not reached in order")
        position = PositionModel.objects.get(
            account_id=world.account_id,
            asset_code=world.asset_code,
        )
        account = SimulatedAccountModel.objects.get(pk=world.account_id)
        initial_cash = account.current_cash
        assert position.quantity == Decimal("70.000000")
        assert position.available_quantity == Decimal("70.000000")

        owner_workflow._issue_v3_share_consent(world)
        entitlement = owner_workflow._prepare_and_confirm(
            world,
            event_id=event_id,
            action="share_entitlement",
            exact_retry=False,
        )
        assert entitlement.get("outcome") == "success"
        _assert_reference_row(
            world=world,
            selections=selections,
            latest_closed=latest_closed,
            record_date=world.record_date,
            reference_quantity=Decimal("100.000000"),
            ex_date=ex_date,
            opening_date=opening_date,
            closing_date=ex_date,
            opening_price=Decimal("11.00"),
            closing_price=Decimal("10.00"),
            closing_cash=Decimal("0.00"),
            closing_dividend_receivable=Decimal("0.00"),
            closing_physical_shares=Decimal("100.000000"),
            closing_share_receivable=Decimal("10.000000"),
            expected_value=Decimal("1100.00"),
        )

        owner_workflow._refresh(world)
        owner_workflow._issue_v3_share_consent(world)
        delivery = owner_workflow._prepare_and_confirm(
            world,
            event_id=event_id,
            action="share_delivery",
            exact_retry=False,
        )
        assert delivery.get("outcome") == "success"
        owner_workflow._refresh(world)
        _assert_reference_row(
            world=world,
            selections=selections,
            latest_closed=latest_closed,
            record_date=world.record_date,
            reference_quantity=Decimal("100.000000"),
            ex_date=ex_date,
            opening_date=opening_date,
            closing_date=ex_date,
            opening_price=Decimal("11.00"),
            closing_price=Decimal("10.00"),
            closing_cash=Decimal("0.00"),
            closing_dividend_receivable=Decimal("0.00"),
            closing_physical_shares=Decimal("100.000000"),
            closing_share_receivable=Decimal("10.000000"),
            expected_value=Decimal("1100.00"),
        )

        owner_workflow._refresh(world)
        owner_workflow._issue_v3_share_consent(world)
        released = owner_workflow._prepare_and_confirm(
            world,
            event_id=event_id,
            action="share_sellable_release",
            exact_retry=False,
        )
        assert released.get("outcome") == "success"
        owner_workflow._refresh(world)
        _assert_reference_row(
            world=world,
            selections=selections,
            latest_closed=latest_closed,
            record_date=world.record_date,
            reference_quantity=Decimal("100.000000"),
            ex_date=ex_date,
            opening_date=opening_date,
            closing_date=ex_date,
            opening_price=Decimal("11.00"),
            closing_price=Decimal("10.00"),
            closing_cash=Decimal("0.00"),
            closing_dividend_receivable=Decimal("0.00"),
            closing_physical_shares=Decimal("100.000000"),
            closing_share_receivable=Decimal("10.000000"),
            expected_value=Decimal("1100.00"),
        )
        account.refresh_from_db()
        position.refresh_from_db()
        assert account.current_cash == initial_cash
        assert position.quantity == Decimal("80.000000")
        assert position.available_quantity == Decimal("80.000000")
        assert b"%ASH05 synthetic fixture" in world.capture.pdf_body
