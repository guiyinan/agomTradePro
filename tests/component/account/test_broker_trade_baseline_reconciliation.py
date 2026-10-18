"""Actual broker facts require explicit balance inclusion, independently of sellability."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.db import transaction

from apps.account.application.manual_trade_sync import ManualTradeImportUseCase
from apps.account.infrastructure import models as account_models
from apps.account.infrastructure.models import AssetMetadataModel, PortfolioModel, TransactionModel
from apps.account.infrastructure.repositories import PortfolioApiRepository
from apps.simulated_trading.infrastructure import models as ledger_models
from core.exceptions import ExternalServiceError

pytestmark = pytest.mark.django_db


class NoopMatcher:
    """Keep recommendation matching out of financial assertions."""

    def record_imported_execution(self, **kwargs: object) -> dict[str, object]:
        """Return the existing matcher's manual-only response."""
        return {"match_method": "manual_only"}


def test_first_actual_buy_preserves_known_costs_without_inventing_a_current_quote() -> None:
    """A new book admits historical quantity and exact paid cost, without enabling trading."""
    owner = User.objects.create_user(username="first-actual-buy-owner")
    portfolio = PortfolioModel.objects.create(user=owner, name="First actual fill")
    AssetMetadataModel.objects.create(
        asset_code="000001.SZ",
        name="Classified local asset",
        asset_class="equity",
        region="CN",
        cross_border="domestic",
    )
    content = (
        b"traded_at,action,asset_code,shares,price,commission,stamp_duty,transfer_fee,external_trade_id\n"
        b"2020-05-20T10:11:12+08:00,buy,000001.SZ,60000,10.1234,1.23,,0.07,first-buy\n"
    )
    case = ManualTradeImportUseCase(execution_matcher=NoopMatcher())
    result = _confirm_from_preview(case, _args(owner, portfolio, content), decision="excluded")
    fact = TransactionModel._default_manager.get(portfolio=portfolio)
    position = ledger_models.PositionModel._default_manager.get(account__user=owner)
    assert result.projected_fact_count == 1
    assert fact.stamp_duty_known is False
    assert position.quantity == Decimal("60000")
    assert position.total_cost == Decimal("607405.30")
    assert position.avg_cost == Decimal("10.1234")
    assert position.valuation_known is False
    assert position.available_quantity_known is False
    assert position.account.auto_trading_enabled is False
    assert position.account.current_cash == Decimal("0")
    assert fact.position.current_price is None
    trade = ledger_models.SimulatedTradeModel._default_manager.get(account__user=owner)
    assert trade.realized_pnl is None
    assert trade.realized_pnl_pct is None


def test_partial_file_keeps_valid_facts_pending_without_minting_whole_file_cas(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
) -> None:
    """An invalid source row cannot erase a valid execution or authorize partial projection."""
    owner, portfolio, position = baseline_book
    content = _content() + b"invalid,sell,000001.SZ,2,11.25,1.23,,0.07,bad-fill\n"
    case = ManualTradeImportUseCase(execution_matcher=NoopMatcher())
    preview = case.preview(**_args(owner, portfolio, content))
    assert preview.expected_fact_set_fingerprint is None
    result = case.confirm(**_args(owner, portfolio, content))
    assert result.facts_saved_count == 1
    assert result.error_rows >= 1
    assert result.pending_fact_count == 1
    position.refresh_from_db()
    assert position.quantity == Decimal("100")
    assert (
        TransactionModel._default_manager.get(portfolio=portfolio).broker_reconciliation_state
        == "awaiting_baseline"
    )


@pytest.fixture
def baseline_book() -> tuple[User, PortfolioModel, ledger_models.PositionModel]:
    """Build an exact mapped book whose local mark differs from the historic fill."""
    owner = User.objects.create_user(username="ash03-baseline-owner")
    portfolio = PortfolioModel.objects.create(user=owner, name="Baseline reconciliation")
    bridge = PortfolioApiRepository()
    account_id = bridge.ensure_real_account(portfolio)
    position = ledger_models.PositionModel._default_manager.create(
        account_id=account_id,
        asset_code="000001.SZ",
        asset_name="Existing local security",
        asset_type="equity",
        quantity=Decimal("100"),
        available_quantity=Decimal("20"),
        available_quantity_known=False,
        avg_cost=Decimal("10"),
        total_cost=Decimal("1000"),
        current_price=Decimal("19"),
        market_value=Decimal("1900"),
        unrealized_pnl=Decimal("900"),
        unrealized_pnl_pct=90,
        first_buy_date=date(2020, 5, 19),
        first_buy_date_known=False,
        entry_reason="Local economic balance, not a broker sellability proof",
    )
    bridge.upsert_legacy_projection_from_unified(
        unified_position=position,
        portfolio=portfolio,
        asset_class="equity",
        region="CN",
        cross_border="domestic",
        source="manual",
    )
    return owner, portfolio, position


def _content(*, shares: int = 40, external_id: str = "baseline-fill-1") -> bytes:
    """Use one source execution with unknown stamp duty and a historic clock."""
    return (
        "traded_at,action,asset_code,shares,price,commission,stamp_duty,"
        "transfer_fee,external_trade_id\n"
        f"2020-05-20T10:11:12+08:00,sell,000001.SZ,{shares},11.25,1.23,,0.07,{external_id}\n"
    ).encode()


def _args(owner: User, portfolio: PortfolioModel, content: bytes) -> dict[str, Any]:
    """Create the real use-case input, retaining exact file bytes across calls."""
    return {
        "user_id": owner.pk,
        "portfolio_id": portfolio.pk,
        "broker_name": "baseline-fixture-broker",
        "filename": "baseline.csv",
        "content": content,
    }


def _confirm_from_preview(
    case: ManualTradeImportUseCase,
    args: dict[str, Any],
    *,
    decision: str,
) -> object:
    """Make a real preview and forward its two independent CAS expectations."""
    preview = case.preview(**args)
    assert preview.expected_fact_set_fingerprint
    assert preview.expected_balance_fingerprint
    return case.confirm(
        **args,
        baseline_decision=decision,
        expected_fact_set_fingerprint=preview.expected_fact_set_fingerprint,
        expected_balance_fingerprint=preview.expected_balance_fingerprint,
    )


@pytest.mark.parametrize("decision", ["pending", "included", "excluded"])
def test_explicit_inclusion_controls_quantity_without_inventing_sellability(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
    decision: str,
) -> None:
    """Only excluded changes economic quantity; none of these choices proves T+1."""
    owner, portfolio, position = baseline_book
    case = ManualTradeImportUseCase(execution_matcher=NoopMatcher())
    _confirm_from_preview(case, _args(owner, portfolio, _content()), decision=decision)
    fact = TransactionModel._default_manager.get(portfolio=portfolio)
    position.refresh_from_db()
    expected_state = {
        "pending": "awaiting_baseline",
        "included": "already_in_baseline",
        "excluded": "projected",
    }[decision]
    assert fact.broker_reconciliation_state == expected_state
    assert position.quantity == (Decimal("60") if decision == "excluded" else Decimal("100"))
    assert position.available_quantity_known is False
    assert position.current_price == Decimal("19")
    assert position.first_buy_date_known is False
    assert position.account.current_cash == Decimal("0")
    mirrors = ledger_models.SimulatedTradeModel._default_manager.filter(account=position.account)
    assert mirrors.count() == (1 if decision == "excluded" else 0)
    if decision == "excluded":
        mirror = mirrors.get()
        assert mirror.execution_time == fact.traded_at
        assert mirror.created_at != mirror.execution_time
        assert (
            ledger_models.LedgerMigrationMapModel._default_manager.filter(
                source_app="account",
                source_table="transaction",
                source_id=fact.pk,
                target_table="simulated_trade",
                target_id=mirror.pk,
            ).count()
            == 1
        )


def test_pending_duplicate_can_be_reconciled_once_without_rewriting_source(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
) -> None:
    """Re-import restores pending work instead of skipping or duplicating a fact."""
    owner, portfolio, position = baseline_book
    case = ManualTradeImportUseCase(execution_matcher=NoopMatcher())
    args = _args(owner, portfolio, _content())
    case.confirm(**args)
    first = TransactionModel._default_manager.get(portfolio=portfolio)
    provenance = (first.pk, first.created_at, first.raw_payload, first.import_batch_id)
    retry = case.preview(**args)
    assert retry.retryable_existing_rows == 1
    assert retry.new_fact_rows == 0
    _confirm_from_preview(case, args, decision="excluded")
    _confirm_from_preview(case, args, decision="excluded")
    assert TransactionModel._default_manager.filter(portfolio=portfolio).count() == 1
    first.refresh_from_db()
    position.refresh_from_db()
    assert (first.pk, first.created_at, first.raw_payload, first.import_batch_id) == provenance
    assert first.broker_reconciliation_state == "projected"
    assert position.quantity == Decimal("60")
    assert (
        ledger_models.SimulatedTradeModel._default_manager.filter(
            account_id=position.account_id
        ).count()
        == 1
    )


@pytest.mark.parametrize("initial_decision", ["included", "excluded"])
def test_pending_reimport_preserves_terminal_state_and_cannot_repeat_projection(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
    initial_decision: str,
) -> None:
    """A default import cannot reopen a resolved fact and permit another balance delta."""
    owner, portfolio, position = baseline_book
    case = ManualTradeImportUseCase(execution_matcher=NoopMatcher())
    args = _args(owner, portfolio, _content())
    _confirm_from_preview(case, args, decision=initial_decision)
    fact = TransactionModel._default_manager.get(portfolio=portfolio)
    terminal_state = fact.broker_reconciliation_state
    details_before = fact.broker_reconciliation_details
    case.confirm(**args)
    fact.refresh_from_db()
    assert fact.broker_reconciliation_state == terminal_state
    assert fact.broker_reconciliation_details == details_before
    _confirm_from_preview(case, args, decision="excluded")
    fact.refresh_from_db()
    position.refresh_from_db()
    assert fact.broker_reconciliation_state == terminal_state
    assert position.quantity == (
        Decimal("60") if initial_decision == "excluded" else Decimal("100")
    )
    assert ledger_models.SimulatedTradeModel._default_manager.filter(
        account_id=position.account_id,
    ).count() == (1 if initial_decision == "excluded" else 0)


@pytest.mark.parametrize("initial_decision", ["included", "excluded"])
def test_opposite_reimport_preserves_terminal_state_and_projection_evidence(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
    initial_decision: str,
) -> None:
    """A fresh preview cannot reinterpret an already applied balance declaration."""
    owner, portfolio, position = baseline_book
    case = ManualTradeImportUseCase(execution_matcher=NoopMatcher())
    args = _args(owner, portfolio, _content())
    _confirm_from_preview(case, args, decision=initial_decision)
    fact = TransactionModel._default_manager.get(portfolio=portfolio)
    before = (
        fact.pk,
        fact.created_at,
        fact.raw_payload,
        fact.broker_reconciliation_state,
        fact.broker_reconciliation_details,
    )
    mirror_ids = tuple(
        ledger_models.SimulatedTradeModel._default_manager.filter(
            account_id=position.account_id
        ).values_list("pk", flat=True)
    )

    _confirm_from_preview(
        case,
        args,
        decision="included" if initial_decision == "excluded" else "excluded",
    )

    fact.refresh_from_db()
    position.refresh_from_db()
    assert (
        fact.pk,
        fact.created_at,
        fact.raw_payload,
        fact.broker_reconciliation_state,
        fact.broker_reconciliation_details,
    ) == before
    assert position.quantity == (
        Decimal("60") if initial_decision == "excluded" else Decimal("100")
    )
    assert (
        tuple(
            ledger_models.SimulatedTradeModel._default_manager.filter(
                account_id=position.account_id
            ).values_list("pk", flat=True)
        )
        == mirror_ids
    )
    assert TransactionModel._default_manager.filter(portfolio=portfolio).count() == 1


def test_projection_summary_uses_successful_outcome_when_followup_read_fails(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient reread cannot relabel a completed projection as pending."""
    owner, portfolio, position = baseline_book
    case = ManualTradeImportUseCase(execution_matcher=NoopMatcher())
    args = _args(owner, portfolio, _content())
    preview = case.preview(**args)

    def unavailable(**kwargs: object) -> None:
        raise ExternalServiceError("followup state read unavailable")

    monkeypatch.setattr(case.reconciliation_repo, "get_fact_by_stable_key", unavailable)
    result = case.confirm(
        **args,
        baseline_decision="excluded",
        expected_fact_set_fingerprint=preview.expected_fact_set_fingerprint,
        expected_balance_fingerprint=preview.expected_balance_fingerprint,
    )
    position.refresh_from_db()
    assert position.quantity == Decimal("60")
    assert result.projected_fact_count == 1
    assert result.pending_fact_count == 0


def test_mapping_lookup_outage_is_distinct_from_a_missing_mapping(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retryable lookup outage must not instruct users to create another account."""
    owner, portfolio, _ = baseline_book
    case = ManualTradeImportUseCase(execution_matcher=NoopMatcher())

    def unavailable(**kwargs: object) -> None:
        raise ExternalServiceError("mapping lookup temporarily unavailable")

    monkeypatch.setattr(case.reconciliation_repo, "get_existing_real_account_id", unavailable)
    result = case.confirm(**_args(owner, portfolio, _content()))
    fact = TransactionModel._default_manager.get(portfolio=portfolio)
    assert result.facts_saved_count == 1
    assert fact.broker_reconciliation_state == "awaiting_baseline"
    assert fact.broker_reconciliation_details["matching_attempt"]["reason_code"] == (
        "real_account_mapping_lookup_failed"
    )
    assert result.matching_failed_count == 1


def test_stale_balance_preview_preserves_fact_and_external_balance_change(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
) -> None:
    """A balance change after preview cannot be silently overwritten by import."""
    owner, portfolio, position = baseline_book
    case = ManualTradeImportUseCase(execution_matcher=NoopMatcher())
    args = _args(owner, portfolio, _content())
    preview = case.preview(**args)
    ledger_models.PositionModel._default_manager.filter(pk=position.pk).update(
        quantity=Decimal("90"), total_cost=Decimal("900")
    )
    case.confirm(
        **args,
        baseline_decision="excluded",
        expected_fact_set_fingerprint=preview.expected_fact_set_fingerprint,
        expected_balance_fingerprint=preview.expected_balance_fingerprint,
    )
    fact = TransactionModel._default_manager.get(portfolio=portfolio)
    position.refresh_from_db()
    assert position.quantity == Decimal("90")
    assert fact.broker_reconciliation_state == "projection_blocked"
    assert fact.broker_reconciliation_details
    assert not ledger_models.SimulatedTradeModel._default_manager.filter(
        account_id=position.account_id
    ).exists()


def test_excluded_oversized_sell_records_fact_without_negative_balance(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
) -> None:
    """Economic impossibility blocks projection and retains the original execution."""
    owner, portfolio, position = baseline_book
    case = ManualTradeImportUseCase(execution_matcher=NoopMatcher())
    _confirm_from_preview(case, _args(owner, portfolio, _content(shares=101)), decision="excluded")
    fact = TransactionModel._default_manager.get(portfolio=portfolio)
    position.refresh_from_db()
    assert fact.shares == 101
    assert fact.broker_reconciliation_state == "projection_blocked"
    assert position.quantity == Decimal("100")
    assert not ledger_models.SimulatedTradeModel._default_manager.filter(
        account_id=position.account_id
    ).exists()


def test_same_broker_id_with_different_economics_never_replaces_original_fact(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
) -> None:
    """Stable-key conflicts preserve the first source and cannot change holdings."""
    owner, portfolio, position = baseline_book
    case = ManualTradeImportUseCase(execution_matcher=NoopMatcher())
    case.confirm(**_args(owner, portfolio, _content()))
    first = TransactionModel._default_manager.get(portfolio=portfolio)
    original = (
        first.shares,
        first.price,
        first.raw_payload,
        first.created_at,
        first.import_batch_id,
    )
    case.confirm(**_args(owner, portfolio, _content(shares=50)))
    assert TransactionModel._default_manager.filter(portfolio=portfolio).count() == 1
    first.refresh_from_db()
    position.refresh_from_db()
    assert (
        first.shares,
        first.price,
        first.raw_payload,
        first.created_at,
        first.import_batch_id,
    ) == original
    assert position.quantity == Decimal("100")
    assert not ledger_models.SimulatedTradeModel._default_manager.filter(
        account_id=position.account_id
    ).exists()


def test_actual_excluded_sell_is_independent_of_known_but_smaller_available_quantity(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
) -> None:
    """A historic execution is not a new simulated sell-permission request."""
    owner, portfolio, position = baseline_book
    position.available_quantity_known = True
    position.save(update_fields=["available_quantity_known"])
    case = ManualTradeImportUseCase(execution_matcher=NoopMatcher())
    _confirm_from_preview(case, _args(owner, portfolio, _content()), decision="excluded")
    position.refresh_from_db()
    fact = TransactionModel._default_manager.get(portfolio=portfolio)
    assert fact.broker_reconciliation_state == "projected"
    assert position.quantity == Decimal("60")
    assert position.available_quantity_known is False


def test_later_new_fact_requires_its_own_explicit_baseline_declaration(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
) -> None:
    """An unchanged local book cannot prove a newly imported fill was excluded."""
    owner, portfolio, position = baseline_book
    case = ManualTradeImportUseCase(execution_matcher=NoopMatcher())
    _confirm_from_preview(case, _args(owner, portfolio, _content()), decision="excluded")
    case.confirm(**_args(owner, portfolio, _content(shares=10, external_id="later-new-fill")))
    position.refresh_from_db()
    assert position.quantity == Decimal("60")
    new_fact = TransactionModel._default_manager.get(external_trade_id="later-new-fill")
    assert new_fact.broker_reconciliation_state == "awaiting_baseline"
    assert (
        ledger_models.SimulatedTradeModel._default_manager.filter(
            account_id=position.account_id
        ).count()
        == 1
    )


def test_legacy_unverified_fact_cannot_be_projected_again_but_can_be_confirmed_included(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
) -> None:
    """Old mirror provenance is insufficient to replay a quantity delta safely."""
    owner, portfolio, position = baseline_book
    case = ManualTradeImportUseCase(execution_matcher=NoopMatcher())
    args = _args(owner, portfolio, _content())
    case.confirm(**args)
    fact = TransactionModel._default_manager.get(portfolio=portfolio)
    TransactionModel._default_manager.filter(pk=fact.pk).update(
        broker_reconciliation_state="legacy_unverified", broker_reconciliation_details={}
    )
    _confirm_from_preview(case, args, decision="excluded")
    position.refresh_from_db()
    assert position.quantity == Decimal("100")
    assert not ledger_models.SimulatedTradeModel._default_manager.filter(
        account_id=position.account_id
    ).exists()
    # A failed attempt must retain the legacy classification's provenance on retry.
    _confirm_from_preview(case, args, decision="excluded")
    position.refresh_from_db()
    assert position.quantity == Decimal("100")
    _confirm_from_preview(case, args, decision="included")
    fact.refresh_from_db()
    position.refresh_from_db()
    assert fact.broker_reconciliation_state == "already_in_baseline"
    assert position.quantity == Decimal("100")


def test_committed_projection_survives_matching_failure(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
) -> None:
    """A matcher failure cannot undo either the actual fact or a valid balance delta."""
    owner, portfolio, position = baseline_book

    class UnavailableMatcher(NoopMatcher):
        calls = 0

        def record_imported_execution(self, **kwargs: object) -> dict[str, object]:
            self.calls += 1
            raise ExternalServiceError("matcher unavailable", code="TEST_MATCHER_UNAVAILABLE")

    matcher = UnavailableMatcher()
    case = ManualTradeImportUseCase(execution_matcher=matcher)
    _confirm_from_preview(case, _args(owner, portfolio, _content()), decision="excluded")
    fact = TransactionModel._default_manager.get(portfolio=portfolio)
    position.refresh_from_db()
    assert matcher.calls == 1
    assert fact.broker_reconciliation_state == "projected"
    assert position.quantity == Decimal("60")
    assert (
        ledger_models.SimulatedTradeModel._default_manager.filter(
            account_id=position.account_id
        ).count()
        == 1
    )


def test_excluded_full_close_retires_position_map_but_preserves_transaction_history(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
) -> None:
    """A closed book must not leave a dangling source-to-position mapping."""
    owner, portfolio, position = baseline_book
    old_position_id = position.pk
    case = ManualTradeImportUseCase(execution_matcher=NoopMatcher())
    _confirm_from_preview(case, _args(owner, portfolio, _content(shares=100)), decision="excluded")
    fact = TransactionModel._default_manager.get(portfolio=portfolio)
    assert fact.broker_reconciliation_state == "projected"
    assert fact.position_id is not None
    assert fact.position.is_closed is True
    assert fact.position.shares == 0
    assert not ledger_models.PositionModel._default_manager.filter(
        account_id=position.account_id, quantity__gt=0
    ).exists()
    assert not ledger_models.LedgerMigrationMapModel._default_manager.filter(
        source_table="position", target_table="simulated_position", target_id=old_position_id
    ).exists()
    assert (
        fact.broker_reconciliation_details["last_projection"]["retired_unified_position_id"]
        == old_position_id
    )
    assert (
        fact.broker_reconciliation_details["last_projection"]["retired_legacy_position_id"]
        == fact.position_id
    )
    assert (
        ledger_models.SimulatedTradeModel._default_manager.filter(
            account_id=position.account_id
        ).count()
        == 1
    )


def test_matcher_database_constraint_failure_cannot_poison_the_outer_import_transaction(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
) -> None:
    """A real SQL uniqueness violation must roll back only the matching savepoint."""
    owner, portfolio, position = baseline_book

    class DatabaseFailingMatcher(NoopMatcher):
        calls = 0

        def record_imported_execution(self, **kwargs: object) -> dict[str, object]:
            """Trigger the existing username constraint through the real database."""
            self.calls += 1
            User._default_manager.create(username=owner.username)
            return {"match_method": "manual_only"}

    matcher = DatabaseFailingMatcher()
    case = ManualTradeImportUseCase(execution_matcher=matcher)
    with transaction.atomic():
        result = _confirm_from_preview(
            case, _args(owner, portfolio, _content()), decision="excluded"
        )
    assert matcher.calls == 1
    assert TransactionModel._default_manager.filter(portfolio=portfolio).count() == 1
    fact = TransactionModel._default_manager.get(portfolio=portfolio)
    position.refresh_from_db()
    assert position.quantity == Decimal("60")
    assert fact.broker_reconciliation_state == "projected"
    assert (
        ledger_models.SimulatedTradeModel._default_manager.filter(
            account_id=position.account_id
        ).count()
        == 1
    )
    assert result.matching_failed_count == 1
    assert case.reconciliation_repo is not None
    record = case.reconciliation_repo.get_fact_by_stable_key(
        owner_user_id=owner.pk,
        portfolio_id=portfolio.pk,
        broker_trade_key=fact.broker_trade_key,
    )
    assert record is not None
    assert record.matching_attempt is not None
    assert record.matching_attempt.outcome == "failed"


def _asset_boundary_business_rows(owner: User) -> tuple[object, ...]:
    """Capture account, balance, mirror, source-position, and map rows."""
    return (
        tuple(
            ledger_models.SimulatedAccountModel._default_manager.filter(user_id=owner.pk)
            .order_by("pk")
            .values()
        ),
        tuple(
            ledger_models.PositionModel._default_manager.filter(account__user_id=owner.pk)
            .order_by("pk")
            .values()
        ),
        tuple(
            ledger_models.SimulatedTradeModel._default_manager.filter(account__user_id=owner.pk)
            .order_by("pk")
            .values()
        ),
        tuple(
            account_models.PositionModel._default_manager.filter(portfolio__user_id=owner.pk)
            .order_by("pk")
            .values()
        ),
        tuple(ledger_models.LedgerMigrationMapModel._default_manager.order_by("pk").values()),
    )


@pytest.mark.parametrize(
    ("source_kind", "asset_class"),
    [("legacy", "other"), ("metadata", "cash")],
)
def test_ambiguous_asset_class_saves_fact_but_blocks_quantity_projection(
    source_kind: str,
    asset_class: str,
) -> None:
    """Uncertain classifications preserve actual fills without creating a ledger position."""
    owner = User.objects.create_user(username=f"asset-boundary-{source_kind}")
    portfolio = PortfolioModel.objects.create(user=owner, name=f"Asset boundary {source_kind}")
    bridge = PortfolioApiRepository()
    account_id = bridge.ensure_real_account(portfolio)
    action = "sell" if source_kind == "legacy" else "buy"
    shares = "40" if source_kind == "legacy" else "4"
    asset_code = "000001.SZ" if source_kind == "legacy" else f"CASH{owner.pk:06d}"

    if source_kind == "legacy":
        position = ledger_models.PositionModel._default_manager.create(
            account_id=account_id,
            asset_code=asset_code,
            asset_name="Existing local security",
            asset_type="equity",
            quantity=Decimal("100"),
            available_quantity=Decimal("20"),
            available_quantity_known=False,
            avg_cost=Decimal("10"),
            total_cost=Decimal("1000"),
            current_price=Decimal("19"),
            market_value=Decimal("1900"),
            unrealized_pnl=Decimal("900"),
            unrealized_pnl_pct=90,
            valuation_known=True,
            first_buy_date=date(2020, 5, 19),
            first_buy_date_known=False,
            entry_reason="Mapped legacy position used to test classification boundaries",
        )
        bridge.upsert_legacy_projection_from_unified(
            unified_position=position,
            portfolio=portfolio,
            asset_class="equity",
            region="CN",
            cross_border="domestic",
            source="manual",
        )
        legacy_position = account_models.PositionModel._default_manager.get(
            portfolio=portfolio,
            asset_code=asset_code,
        )
        legacy_position.asset_class = asset_class
        legacy_position.save(update_fields=["asset_class"])
    else:
        AssetMetadataModel.objects.create(
            asset_code=asset_code,
            name="Ambiguous cash-class asset",
            asset_class=asset_class,
            region="OTHER",
            cross_border="domestic",
        )

    content = (
        "traded_at,action,asset_code,shares,price,commission,stamp_duty,"
        "transfer_fee,external_trade_id\n"
        f"2020-05-20T10:11:12+08:00,{action},{asset_code},{shares},10.00,1.23,,0.07,"
        f"asset-boundary-{source_kind}\n"
    ).encode()
    case = ManualTradeImportUseCase(execution_matcher=NoopMatcher())
    args = _args(owner, portfolio, content)
    preview = case.preview(**args)
    assert preview.expected_fact_set_fingerprint
    assert preview.expected_balance_fingerprint
    before = _asset_boundary_business_rows(owner)

    result = case.confirm(
        **args,
        baseline_decision="excluded",
        expected_fact_set_fingerprint=preview.expected_fact_set_fingerprint,
        expected_balance_fingerprint=preview.expected_balance_fingerprint,
    )

    fact = TransactionModel._default_manager.get(portfolio=portfolio)
    assert result.facts_saved_count == 1
    assert fact.asset_code == asset_code
    assert fact.action == action
    assert Decimal(str(fact.shares)) == Decimal(shares)
    assert fact.broker_reconciliation_state == "projection_blocked"
    reason_code = (
        "ASSET_TYPE_UNSUPPORTED"
        if source_kind == "legacy"
        else "ASSET_TYPE_UNSUPPORTED_OR_METADATA_MISSING"
    )
    assert fact.broker_reconciliation_details["last_reason_code"] == reason_code
    assert _asset_boundary_business_rows(owner) == before
    fact_row = next(row for row in result.rows if row["transaction_id"] == fact.pk)
    assert fact_row["reconciliation_state"] == fact.broker_reconciliation_state
    assert fact_row["reconciliation_reason_code"] == reason_code
    assert fact_row["projection_outcome"] == "blocked"
    assert result.projected_fact_count == 0
    assert result.projection_blocked_count == 1
    assert result.pending_fact_count == 0
