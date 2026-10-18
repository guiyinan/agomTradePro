"""Missing broker facts must never be presented as current pending outcomes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
from typing import Any, cast

import pytest
from django.contrib.auth.models import User

from apps.account.application.broker_trade_reconciliation_contracts import (
    BaselineRequest,
    BrokerFactCandidate,
    BrokerFactProjectionResult,
    BrokerFactRecord,
    BrokerFactSetReconciliationResult,
    BrokerFactWriteResult,
)
from apps.account.application.manual_trade_sync import (
    BrokerTradeImportResult,
    ManualTradeImportUseCase,
)
from apps.account.application.repository_provider import (
    get_broker_trade_reconciliation_repository,
)
from apps.account.domain.broker_trade_reconciliation import BrokerReconciliationState
from apps.account.infrastructure import models as account_models
from apps.account.infrastructure.models import (
    PortfolioModel,
    TransactionModel,
)
from apps.account.interface.transaction_api_views import _sanitize_tui_import_rows
from apps.simulated_trading.infrastructure import models as ledger_models
from tests.component.account.test_broker_trade_baseline_reconciliation import (
    NoopMatcher,
    _args,
    _content,
)
from tests.component.account.test_broker_trade_baseline_reconciliation import (
    baseline_book as baseline_book,
)
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)


@pytest.mark.django_db(transaction=True)
def test_fact_deleted_before_blocked_followup_has_no_ghost_outcome(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disappeared fact cannot inherit the old state after an abort rollback."""
    owner, portfolio, position = baseline_book
    account = position.account
    before = _capture_business_state(portfolio=portfolio, position=position)
    repository = get_broker_trade_reconciliation_repository()
    original_mark_blocked = cast(
        Callable[..., object],
        repository._mark_blocked,
    )
    deleted_ids: list[int] = []

    def delete_then_mark_blocked(
        *,
        transaction_ids: tuple[int, ...],
        reason_code: str,
        owner_user_id: int,
        portfolio_id: int,
        request: BaselineRequest | None,
        actor_user_id: int | None,
        decision_batch_id: int | None,
        source_file_sha256: str | None,
        declared_at: datetime | None,
    ) -> tuple[TransactionModel, ...]:
        """Delete after the real projection abort and before the locked follow-up."""
        assert reason_code == "BROKER_BALANCE_PREVIEW_CHANGED"
        assert len(transaction_ids) == 1
        deleted, _ = TransactionModel._default_manager.filter(
            pk=transaction_ids[0],
            portfolio_id=portfolio_id,
            portfolio__user_id=owner_user_id,
        ).delete()
        assert deleted == 1
        deleted_ids.extend(transaction_ids)
        rows = original_mark_blocked(
            transaction_ids=transaction_ids,
            reason_code=reason_code,
            owner_user_id=owner_user_id,
            portfolio_id=portfolio_id,
            request=request,
            actor_user_id=actor_user_id,
            decision_batch_id=decision_batch_id,
            source_file_sha256=source_file_sha256,
            declared_at=declared_at,
        )
        return cast(tuple[TransactionModel, ...], rows)

    monkeypatch.setattr(repository, "_mark_blocked", delete_then_mark_blocked)
    case = ManualTradeImportUseCase(
        execution_matcher=NoopMatcher(),
        reconciliation_repo=repository,
    )
    arguments = _args(owner, portfolio, _content(external_id="deleted-after-abort"))
    preview = case.preview(**arguments)
    assert preview.expected_fact_set_fingerprint is not None
    assert preview.expected_balance_fingerprint is not None
    stale_balance_fingerprint = sha256(b"stale local balance").hexdigest()
    assert stale_balance_fingerprint != preview.expected_balance_fingerprint

    result = case.confirm(
        **arguments,
        baseline_decision="excluded",
        expected_fact_set_fingerprint=preview.expected_fact_set_fingerprint,
        expected_balance_fingerprint=stale_balance_fingerprint,
    )

    assert len(deleted_ids) == 1
    assert result.reconciliation_conflict_code == "BROKER_BALANCE_PREVIEW_CHANGED"
    _assert_unavailable_result(result)
    assert not TransactionModel._default_manager.filter(portfolio=portfolio).exists()
    position.refresh_from_db()
    account.refresh_from_db()
    assert _capture_business_state(portfolio=portfolio, position=position) == before


@pytest.mark.django_db(transaction=True)
def test_pending_fact_deleted_before_reconciliation_has_no_ghost_pending_count(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pending retry with a missing fresh lookup is unavailable, not awaiting."""
    owner, portfolio, position = baseline_book
    account = position.account
    before = _capture_business_state(portfolio=portfolio, position=position)
    repository = get_broker_trade_reconciliation_repository()
    persist_fact_first = repository.persist_fact_first
    deleted_ids: list[int] = []

    def persist_then_remove(candidate: BrokerFactCandidate) -> BrokerFactWriteResult:
        """Remove only after the real atomic persist has returned its write receipt."""
        result = persist_fact_first(candidate)
        record = result.record
        if record is not None:
            deleted, _ = TransactionModel._default_manager.filter(
                pk=record.transaction_id,
                portfolio_id=candidate.portfolio_id,
                portfolio__user_id=candidate.owner_user_id,
            ).delete()
            assert deleted == 1
            deleted_ids.append(record.transaction_id)
        return result

    monkeypatch.setattr(repository, "persist_fact_first", persist_then_remove)
    case = ManualTradeImportUseCase(
        execution_matcher=NoopMatcher(),
        reconciliation_repo=repository,
    )

    result = case.confirm(
        **_args(owner, portfolio, _content(external_id="deleted-before-pending-read"))
    )

    assert len(deleted_ids) == 1
    assert result.reconciliation_error_code == "BROKER_RECONCILIATION_ATTEMPT_FAILED"
    _assert_unavailable_result(result)
    assert not TransactionModel._default_manager.filter(portfolio=portfolio).exists()
    position.refresh_from_db()
    account.refresh_from_db()
    assert _capture_business_state(portfolio=portfolio, position=position) == before


def _assert_unavailable_result(result: BrokerTradeImportResult) -> None:
    """Require a stable current-fact absence response without inventing domain state."""
    assert result.facts_saved_count == 1
    assert result.pending_fact_count == 0
    assert result.projected_fact_count == 0
    assert result.already_in_baseline_count == 0
    assert result.projection_blocked_count == 0
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.get("status") == "fact_unavailable"
    assert "reconciliation_state" not in row
    assert "projection_outcome" not in row
    missing_errors = [
        error
        for error in result.errors
        if error.get("error_code") == "BROKER_FACT_CURRENT_STATE_UNAVAILABLE"
    ]
    assert len(missing_errors) == 1
    message = missing_errors[0].get("message")
    assert isinstance(message, str)
    assert "未重建" in message
    assert "重新导入" in message


def _capture_business_state(
    *,
    portfolio: PortfolioModel,
    position: ledger_models.PositionModel,
) -> tuple[object, ...]:
    """Snapshot account, position, transaction, mirror, and mapping business rows."""
    position.refresh_from_db()
    account = position.account
    account.refresh_from_db()
    unified_positions = tuple(
        ledger_models.PositionModel._default_manager.filter(account_id=account.pk)
        .order_by("pk")
        .values_list(
            "pk",
            "quantity",
            "total_cost",
            "avg_cost",
            "current_price",
            "market_value",
            "valuation_known",
            "available_quantity",
            "available_quantity_known",
        )
    )
    legacy_positions = tuple(
        account_models.PositionModel._default_manager.filter(portfolio_id=portfolio.pk)
        .order_by("pk")
        .values_list(
            "pk",
            "shares",
            "avg_cost",
            "current_price",
            "market_value",
            "unrealized_pnl",
            "unrealized_pnl_pct",
            "source_id",
            "is_closed",
        )
    )
    facts = tuple(
        TransactionModel._default_manager.filter(portfolio_id=portfolio.pk)
        .order_by("pk")
        .values_list(
            "pk",
            "position_id",
            "action",
            "asset_code",
            "shares",
            "price",
            "notional",
            "broker_trade_key",
            "broker_reconciliation_state",
        )
    )
    mirrors = tuple(
        ledger_models.SimulatedTradeModel._default_manager.filter(account_id=account.pk)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    mappings = tuple(
        ledger_models.LedgerMigrationMapModel._default_manager.filter(
            source_app="account",
            source_table="transaction",
            target_table="simulated_trade",
        )
        .order_by("pk")
        .values_list("pk", "source_id", "target_id")
    )
    return (
        (account.pk, account.current_cash, account.auto_trading_enabled),
        unified_positions,
        legacy_positions,
        facts,
        mirrors,
        mappings,
    )


@pytest.mark.django_db(transaction=True)
def test_unrequested_stale_projection_result_cannot_restore_current_count(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale projected result for another ID is excluded from this request's count."""
    owner, portfolio, position = baseline_book
    before = _capture_business_state(portfolio=portfolio, position=position)
    repository = get_broker_trade_reconciliation_repository()
    reconcile_fact_set = repository.reconcile_fact_set
    deleted_ids: list[int] = []

    def reconcile_then_delete_and_inject_stale_result(
        *,
        owner_user_id: int,
        portfolio_id: int,
        decision_batch_id: int | None,
        transaction_ids: tuple[int, ...],
        source_file_sha256: str,
        request: BaselineRequest,
    ) -> BrokerFactSetReconciliationResult:
        """Run the real repository, then return a typed result for an unrequested ID."""
        actual = reconcile_fact_set(
            owner_user_id=owner_user_id,
            portfolio_id=portfolio_id,
            decision_batch_id=decision_batch_id,
            transaction_ids=transaction_ids,
            source_file_sha256=source_file_sha256,
            request=request,
        )
        assert len(transaction_ids) == 1
        assert len(actual.facts) == 1
        assert actual.facts[0].transaction_id == transaction_ids[0]
        deleted, _ = TransactionModel._default_manager.filter(
            pk=transaction_ids[0],
            portfolio_id=portfolio_id,
            portfolio__user_id=owner_user_id,
        ).delete()
        assert deleted == 1
        deleted_ids.extend(transaction_ids)
        stale_transaction_id = transaction_ids[0] + 1_000_000
        assert stale_transaction_id not in transaction_ids
        stale_outcome: BrokerFactProjectionResult = replace(
            actual.facts[0],
            transaction_id=stale_transaction_id,
            state=BrokerReconciliationState.PROJECTED,
            outcome="projected",
            reason_code=None,
        )
        return replace(actual, facts=(stale_outcome,))

    monkeypatch.setattr(
        repository,
        "reconcile_fact_set",
        reconcile_then_delete_and_inject_stale_result,
    )
    result = ManualTradeImportUseCase(
        execution_matcher=NoopMatcher(),
        reconciliation_repo=repository,
    ).confirm(**_args(owner, portfolio, _content(external_id="stale-unrequested-result")))

    assert len(deleted_ids) == 1
    _assert_unavailable_result(result)
    assert not TransactionModel._default_manager.filter(portfolio=portfolio).exists()
    assert _capture_business_state(portfolio=portfolio, position=position) == before


@pytest.mark.parametrize("reader_behavior", ("raises", "mismatched_identity"))
@pytest.mark.django_db(transaction=True)
def test_untrusted_fresh_fact_read_never_falls_back_to_write_receipt(
    baseline_book: tuple[User, PortfolioModel, ledger_models.PositionModel],
    monkeypatch: pytest.MonkeyPatch,
    reader_behavior: str,
) -> None:
    """Reader errors or identity mismatches leave current state unavailable."""
    owner, portfolio, position = baseline_book
    repository = get_broker_trade_reconciliation_repository()
    reconcile_fact_set = repository.reconcile_fact_set
    get_fact_by_stable_key = repository.get_fact_by_stable_key

    def omit_reconciliation_facts(
        *,
        owner_user_id: int,
        portfolio_id: int,
        decision_batch_id: int | None,
        transaction_ids: tuple[int, ...],
        source_file_sha256: str,
        request: BaselineRequest,
    ) -> BrokerFactSetReconciliationResult:
        """Keep the real reconciliation attempt but simulate an incomplete receipt."""
        current = reconcile_fact_set(
            owner_user_id=owner_user_id,
            portfolio_id=portfolio_id,
            decision_batch_id=decision_batch_id,
            transaction_ids=transaction_ids,
            source_file_sha256=source_file_sha256,
            request=request,
        )
        assert len(transaction_ids) == 1
        assert len(current.facts) == 1
        return replace(current, facts=())

    def untrusted_current_read(
        *,
        owner_user_id: int,
        portfolio_id: int,
        broker_trade_key: str,
    ) -> BrokerFactRecord | None:
        """Return an exception or a mismatched typed fact at the read boundary."""
        record = get_fact_by_stable_key(
            owner_user_id=owner_user_id,
            portfolio_id=portfolio_id,
            broker_trade_key=broker_trade_key,
        )
        assert record is not None
        if reader_behavior == "raises":
            raise RuntimeError("current fact lookup failed")
        assert reader_behavior == "mismatched_identity"
        return replace(record, transaction_id=record.transaction_id + 1)

    monkeypatch.setattr(repository, "reconcile_fact_set", omit_reconciliation_facts)
    monkeypatch.setattr(repository, "get_fact_by_stable_key", untrusted_current_read)
    result = ManualTradeImportUseCase(
        execution_matcher=NoopMatcher(),
        reconciliation_repo=repository,
    ).confirm(
        **_args(
            owner,
            portfolio,
            _content(external_id=f"untrusted-current-read-{reader_behavior}"),
        )
    )

    _assert_unavailable_result(result)
    assert TransactionModel._default_manager.filter(portfolio=portfolio).count() == 1


def test_tui_sanitizes_unavailable_fact_recovery_without_machine_code() -> None:
    """TUI keeps recovery guidance while hiding the internal stable error code."""
    recovery_message = "成交事实当前状态无法确认，未重建；请重新导入并先核对文件和余额"
    result: dict[str, Any] = {
        "rows": [
            {
                "row_number": 1,
                "status": "fact_unavailable",
                "status_reason": "BROKER_FACT_CURRENT_STATE_UNAVAILABLE",
            }
        ],
        "errors": [
            {
                "row_number": 1,
                "error_code": "BROKER_FACT_CURRENT_STATE_UNAVAILABLE",
                "message": "internal detail: BROKER_FACT_CURRENT_STATE_UNAVAILABLE",
            }
        ],
    }

    _sanitize_tui_import_rows(result)

    row = result["rows"][0]
    assert row["status"] == "成交事实当前状态不可用"
    assert row["reconciliation_status"] == "成交事实当前状态不可用"
    assert row["status_reason"] == recovery_message
    assert result["errors"] == [{"message": recovery_message, "row_number": 1}]
    assert "BROKER_FACT_CURRENT_STATE_UNAVAILABLE" not in repr(result)
    assert "internal detail" not in repr(result)
