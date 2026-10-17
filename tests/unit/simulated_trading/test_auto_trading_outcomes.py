"""Strict business outcome contracts for automatic simulated trading."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from apps.simulated_trading.domain.auto_trading_outcomes import (
    AccountAutoTradingOutcome,
    AutoTradingBatchOutcome,
    AutoTradingIssue,
    AutoTradingIssueKind,
    AutoTradingOutcome,
    AutoTradingOutcomeContractError,
    build_account_auto_trading_outcome,
    build_auto_trading_batch_outcome,
)


def _issue(
    *,
    kind: AutoTradingIssueKind = AutoTradingIssueKind.FAILED,
    stage: str = "buy_execution",
    code: str = "ORDER_WRITE_FAILED",
    asset_code: str | None = "600000.SH",
    effects_indeterminate: bool = False,
) -> AutoTradingIssue:
    return AutoTradingIssue(
        kind=kind,
        stage=stage,
        code=code,
        asset_code=asset_code,
        effects_indeterminate=effects_indeterminate,
    )


@pytest.mark.parametrize(
    ("buy_count", "sell_count", "issues", "expected"),
    [
        (2, 1, (), AutoTradingOutcome.SUCCESS),
        (1, 0, (_issue(),), AutoTradingOutcome.PARTIAL),
        (0, 0, (_issue(kind=AutoTradingIssueKind.BLOCKED),), AutoTradingOutcome.BLOCKED),
        (0, 0, (_issue(),), AutoTradingOutcome.FAILED),
        (0, 0, (), AutoTradingOutcome.NOOP),
    ],
)
def test_account_outcome_is_derived_from_confirmed_trades_and_issues(
    buy_count: int,
    sell_count: int,
    issues: tuple[AutoTradingIssue, ...],
    expected: AutoTradingOutcome,
) -> None:
    outcome = build_account_auto_trading_outcome(
        17,
        buy_count=buy_count,
        sell_count=sell_count,
        issues=issues,
    )

    assert outcome.outcome is expected
    assert outcome.confirmed_trade_count == buy_count + sell_count
    assert outcome.success is (
        expected
        in {
            AutoTradingOutcome.SUCCESS,
            AutoTradingOutcome.PARTIAL,
            AutoTradingOutcome.NOOP,
        }
    )


def test_noop_has_an_explicit_reason_and_no_issues() -> None:
    outcome = build_account_auto_trading_outcome(17, buy_count=0, sell_count=0)

    assert outcome.outcome is AutoTradingOutcome.NOOP
    assert outcome.reason_code == "NO_TRADES_CONFIRMED"
    assert outcome.issues == ()
    assert outcome.stored == 0
    assert outcome.counts_unavailable is False


def test_indeterminate_write_preserves_confirmed_count_but_not_stored_count() -> None:
    outcome = build_account_auto_trading_outcome(
        17,
        buy_count=1,
        sell_count=2,
        issues=(_issue(effects_indeterminate=True),),
    )

    assert outcome.outcome is AutoTradingOutcome.PARTIAL
    assert outcome.confirmed_trade_count == 3
    assert outcome.buy_count == 1
    assert outcome.sell_count == 2
    assert outcome.stored is None
    assert outcome.counts_unavailable is True
    assert outcome.to_payload()["issues"] == [
        {
            "kind": "failed",
            "stage": "buy_execution",
            "code": "ORDER_WRITE_FAILED",
            "asset_code": "600000.SH",
            "effects_indeterminate": True,
        }
    ]


@pytest.mark.parametrize(
    ("account_id", "buy_count", "sell_count"),
    [
        (True, 0, 0),
        (0, 0, 0),
        (17, True, 0),
        (17, 0, False),
        (17, -1, 0),
        (17, 0, -1),
    ],
)
def test_account_builder_rejects_bool_nonpositive_and_negative_counts(
    account_id: int,
    buy_count: int,
    sell_count: int,
) -> None:
    with pytest.raises(AutoTradingOutcomeContractError):
        build_account_auto_trading_outcome(
            account_id,
            buy_count=buy_count,
            sell_count=sell_count,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "failed", "stage": "buy_execution", "code": "ORDER_WRITE_FAILED"},
        {"kind": AutoTradingIssueKind.FAILED, "stage": "raw exception text", "code": "ERROR"},
        {"kind": AutoTradingIssueKind.FAILED, "stage": "buy_execution", "code": "raw exception"},
        {
            "kind": AutoTradingIssueKind.BLOCKED,
            "stage": "buy_execution",
            "code": "RISK_BLOCKED",
            "effects_indeterminate": True,
        },
    ],
)
def test_issue_rejects_untyped_or_unsafe_codes_and_impossible_effect_state(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(AutoTradingOutcomeContractError):
        AutoTradingIssue(**kwargs)  # type: ignore[arg-type]


def test_blocked_issue_with_indeterminate_write_effects_is_rejected_on_wire() -> None:
    payload = _issue().to_payload()
    payload["kind"] = "blocked"
    payload["effects_indeterminate"] = True

    with pytest.raises(AutoTradingOutcomeContractError, match="indeterminate write effects"):
        AutoTradingIssue.from_payload(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", 1),
        ("kind", "future_kind"),
        ("asset_code", "600000 SH"),
        ("effects_indeterminate", 1),
    ],
)
def test_issue_wire_rejects_malformed_identity_and_effect_fields(field: str, value: object) -> None:
    payload = _issue().to_payload()
    payload[field] = value

    with pytest.raises(AutoTradingOutcomeContractError):
        AutoTradingIssue.from_payload(payload)


@pytest.mark.parametrize("payload", [None, []])
def test_issue_wire_requires_an_object(payload: object) -> None:
    with pytest.raises(AutoTradingOutcomeContractError, match="issue must be an object"):
        AutoTradingIssue.from_payload(payload)


def test_account_constructor_rejects_mutable_or_untyped_issues() -> None:
    with pytest.raises(AutoTradingOutcomeContractError, match="issues must be a tuple"):
        AccountAutoTradingOutcome(17, 0, 0, [])  # type: ignore[arg-type]


def test_batch_counts_accounts_and_does_not_count_partial_as_succeeded() -> None:
    partial = build_account_auto_trading_outcome(
        11,
        buy_count=1,
        sell_count=0,
        issues=(_issue(),),
    )
    complete = build_account_auto_trading_outcome(12, buy_count=0, sell_count=2)
    noop = build_account_auto_trading_outcome(13, buy_count=0, sell_count=0)

    batch = build_auto_trading_batch_outcome(
        (11, 12, 13),
        {11: partial, 12: complete, 13: noop},
    )

    assert batch.outcome is AutoTradingOutcome.PARTIAL
    assert batch.success is True
    assert (batch.requested, batch.succeeded, batch.failed, batch.partial_account_count) == (
        3,
        2,
        1,
        1,
    )
    assert (batch.buy_count, batch.sell_count, batch.confirmed_trade_count) == (1, 2, 3)
    assert batch.stored == 3


def test_missing_requested_account_is_failed_and_storage_count_is_unknown() -> None:
    noop = build_account_auto_trading_outcome(11, buy_count=0, sell_count=0)

    batch = build_auto_trading_batch_outcome((11, 12), {11: noop})

    missing = batch.accounts[1]
    assert batch.outcome is AutoTradingOutcome.FAILED
    assert (batch.requested, batch.succeeded, batch.failed) == (2, 1, 1)
    assert batch.confirmed_trade_count == 0
    assert batch.stored is None
    assert batch.counts_unavailable is True
    assert missing.outcome is AutoTradingOutcome.FAILED
    assert missing.issues[0].code == "ACCOUNT_RESULT_MISSING"
    assert missing.issues[0].effects_indeterminate is True


def test_noop_accounts_do_not_hide_blocked_or_failed_batch() -> None:
    noop = build_account_auto_trading_outcome(11, buy_count=0, sell_count=0)
    blocked = build_account_auto_trading_outcome(
        12,
        buy_count=0,
        sell_count=0,
        issues=(_issue(kind=AutoTradingIssueKind.BLOCKED, code="RISK_BLOCKED"),),
    )
    failed = build_account_auto_trading_outcome(
        13,
        buy_count=0,
        sell_count=0,
        issues=(_issue(),),
    )

    blocked_batch = build_auto_trading_batch_outcome((11, 12), {11: noop, 12: blocked})
    failed_batch = build_auto_trading_batch_outcome((11, 13), {11: noop, 13: failed})

    assert blocked_batch.outcome is AutoTradingOutcome.BLOCKED
    assert (blocked_batch.succeeded, blocked_batch.failed) == (1, 1)
    assert failed_batch.outcome is AutoTradingOutcome.FAILED
    assert (failed_batch.succeeded, failed_batch.failed) == (1, 1)


def test_empty_batch_is_noop_with_explicit_reason() -> None:
    batch = build_auto_trading_batch_outcome((), {})

    assert batch.outcome is AutoTradingOutcome.NOOP
    assert batch.reason_code == "NO_ACCOUNTS_REQUESTED"
    assert (batch.requested, batch.succeeded, batch.failed, batch.stored) == (0, 0, 0, 0)


def test_all_noop_accounts_remain_noop_with_reason() -> None:
    first = build_account_auto_trading_outcome(11, buy_count=0, sell_count=0)
    second = build_account_auto_trading_outcome(12, buy_count=0, sell_count=0)

    batch = build_auto_trading_batch_outcome((11, 12), {12: second, 11: first})

    assert tuple(account.account_id for account in batch.accounts) == (11, 12)
    assert batch.outcome is AutoTradingOutcome.NOOP
    assert batch.reason_code == "NO_TRADES_CONFIRMED"
    assert (batch.succeeded, batch.failed, batch.stored) == (2, 0, 0)


@pytest.mark.parametrize(
    ("requested_ids", "results"),
    [
        ((1, 1), {}),
        ((True,), {}),
        ((1,), {True: build_account_auto_trading_outcome(1, buy_count=0, sell_count=0)}),
        ((1,), {2: build_account_auto_trading_outcome(2, buy_count=0, sell_count=0)}),
        ((1,), {1: build_account_auto_trading_outcome(2, buy_count=0, sell_count=0)}),
    ],
)
def test_batch_builder_rejects_invalid_or_unrequested_account_results(
    requested_ids: tuple[int, ...],
    results: Mapping[int, AccountAutoTradingOutcome],
) -> None:
    with pytest.raises(AutoTradingOutcomeContractError):
        build_auto_trading_batch_outcome(requested_ids, results)


def test_batch_constructor_rejects_invalid_identity_and_account_shapes() -> None:
    one = build_account_auto_trading_outcome(1, buy_count=0, sell_count=0)
    two = build_account_auto_trading_outcome(2, buy_count=0, sell_count=0)

    with pytest.raises(AutoTradingOutcomeContractError, match="must be a tuple"):
        AutoTradingBatchOutcome([1], (one,))  # type: ignore[arg-type]
    with pytest.raises(AutoTradingOutcomeContractError, match="unique"):
        AutoTradingBatchOutcome((1, 1), (one, one))
    with pytest.raises(AutoTradingOutcomeContractError, match="tuple of typed outcomes"):
        AutoTradingBatchOutcome((1,), [one])  # type: ignore[arg-type]
    with pytest.raises(AutoTradingOutcomeContractError, match="match every requested"):
        AutoTradingBatchOutcome((1, 2), (two, one))


def test_batch_builder_rejects_wrong_container_and_untyped_result() -> None:
    with pytest.raises(AutoTradingOutcomeContractError, match="must be a tuple"):
        build_auto_trading_batch_outcome([1], {})  # type: ignore[arg-type]
    with pytest.raises(AutoTradingOutcomeContractError, match="must be an account mapping"):
        build_auto_trading_batch_outcome((1,), [])  # type: ignore[arg-type]
    with pytest.raises(AutoTradingOutcomeContractError, match="typed account outcome"):
        build_auto_trading_batch_outcome((1,), {1: None})  # type: ignore[dict-item]


def test_outcome_wire_round_trips_and_returns_fresh_json_containers() -> None:
    account = build_account_auto_trading_outcome(
        17,
        buy_count=1,
        sell_count=0,
        issues=(_issue(effects_indeterminate=True),),
    )
    account_payload = account.to_payload()
    parsed_account = AccountAutoTradingOutcome.from_payload(account_payload)
    batch = build_auto_trading_batch_outcome((17,), {17: account})
    batch_payload = batch.to_payload()
    parsed_batch = AutoTradingBatchOutcome.from_payload(batch_payload)

    assert parsed_account == account
    assert parsed_batch == batch
    account_payload["issues"].clear()
    batch_payload["accounts"].clear()
    assert account.issues
    assert batch.accounts


@pytest.mark.parametrize(
    "payload",
    [
        {"buy_count": 1, "sell_count": 0},
        {
            "account_id": 1,
            "outcome": "unknown",
            "success": True,
            "buy_count": 0,
            "sell_count": 0,
            "confirmed_trade_count": 0,
            "stored": 0,
            "counts_unavailable": False,
            "reason_code": "NO_TRADES_CONFIRMED",
            "issues": [],
        },
        {
            "account_id": 1,
            "outcome": "success",
            "success": True,
            "buy_count": True,
            "sell_count": 0,
            "confirmed_trade_count": 1,
            "stored": 1,
            "counts_unavailable": False,
            "reason_code": None,
            "issues": [],
        },
        {
            "account_id": 1,
            "outcome": "success",
            "success": False,
            "buy_count": 1,
            "sell_count": 0,
            "confirmed_trade_count": 1,
            "stored": 1,
            "counts_unavailable": False,
            "reason_code": None,
            "issues": [],
        },
        {
            "account_id": 1,
            "outcome": "success",
            "success": True,
            "buy_count": 1,
            "sell_count": 0,
            "confirmed_trade_count": 0,
            "stored": 1,
            "counts_unavailable": False,
            "reason_code": None,
            "issues": [],
        },
        {
            "account_id": 1,
            "outcome": "success",
            "success": True,
            "buy_count": 1,
            "sell_count": 0,
            "confirmed_trade_count": 1,
            "stored": 1,
            "counts_unavailable": False,
            "reason_code": None,
            "issues": [],
            "exception": "provider secret text",
        },
        {
            "account_id": 1,
            "outcome": None,
            "success": True,
            "buy_count": 0,
            "sell_count": 0,
            "confirmed_trade_count": 0,
            "stored": 0,
            "counts_unavailable": False,
            "reason_code": "NO_TRADES_CONFIRMED",
            "issues": [],
        },
        {
            "account_id": 1,
            "outcome": "noop",
            "success": True,
            "buy_count": 0,
            "sell_count": 0,
            "confirmed_trade_count": 0,
            "stored": 0,
            "counts_unavailable": False,
            "reason_code": 1,
            "issues": [],
        },
        {
            "account_id": 1,
            "outcome": "noop",
            "success": True,
            "buy_count": 0,
            "sell_count": 0,
            "confirmed_trade_count": 0,
            "stored": 0,
            "counts_unavailable": False,
            "reason_code": "NO_TRADES_CONFIRMED",
            "issues": (),
        },
    ],
)
def test_account_payload_parser_rejects_legacy_unknown_and_inconsistent_shapes(
    payload: object,
) -> None:
    with pytest.raises(AutoTradingOutcomeContractError):
        AccountAutoTradingOutcome.from_payload(payload)


def test_batch_payload_parser_rejects_inconsistent_aggregate_counters() -> None:
    account = build_account_auto_trading_outcome(17, buy_count=1, sell_count=0)
    payload = build_auto_trading_batch_outcome((17,), {17: account}).to_payload()
    payload["failed"] = 1

    with pytest.raises(AutoTradingOutcomeContractError):
        AutoTradingBatchOutcome.from_payload(payload)


@pytest.mark.parametrize("field,value", [("reason_code", 7), ("accounts", ())])
def test_batch_payload_parser_rejects_bad_json_field_shapes(field: str, value: object) -> None:
    account = build_account_auto_trading_outcome(17, buy_count=0, sell_count=0)
    payload = build_auto_trading_batch_outcome((17,), {17: account}).to_payload()
    payload[field] = value

    with pytest.raises(AutoTradingOutcomeContractError):
        AutoTradingBatchOutcome.from_payload(payload)
