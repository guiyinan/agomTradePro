"""Strict business-result contracts for automatic simulated trading."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict

_STAGE_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,95}\Z")
_MAX_ASSET_CODE_LENGTH = 192


class AutoTradingOutcomeContractError(ValueError):
    """Raised when an automatic-trading result violates its typed contract."""


class AutoTradingOutcome(StrEnum):
    """Normalized outcomes for simulated automatic-trading work."""

    SUCCESS = "success"
    PARTIAL = "partial"
    NOOP = "noop"
    BLOCKED = "blocked"
    FAILED = "failed"


class AutoTradingIssueKind(StrEnum):
    """Stable distinction between a business gate and an execution failure."""

    BLOCKED = "blocked"
    FAILED = "failed"


class AutoTradingIssuePayload(TypedDict):
    """Exact JSON shape for one safe issue."""

    kind: str
    stage: str
    code: str
    asset_code: str | None
    effects_indeterminate: bool


class AccountAutoTradingOutcomePayload(TypedDict):
    """Exact JSON shape for one account's automatic-trading result."""

    account_id: int
    outcome: str
    success: bool
    buy_count: int
    sell_count: int
    confirmed_trade_count: int
    stored: int | None
    counts_unavailable: bool
    reason_code: str | None
    issues: list[AutoTradingIssuePayload]


class AutoTradingBatchOutcomePayload(TypedDict):
    """Exact JSON shape for a batch whose work unit is an account."""

    outcome: str
    success: bool
    requested: int
    succeeded: int
    failed: int
    partial_account_count: int
    stored: int | None
    counts_unavailable: bool
    buy_count: int
    sell_count: int
    confirmed_trade_count: int
    reason_code: str | None
    accounts: list[AccountAutoTradingOutcomePayload]


def _require_exact_int(value: object, field_name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise AutoTradingOutcomeContractError(f"{field_name} must be an exact integer >= {minimum}")
    return value


def _require_exact_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise AutoTradingOutcomeContractError(f"{field_name} must be an exact boolean")
    return value


def _require_issue_token(value: object, field_name: str, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise AutoTradingOutcomeContractError(f"{field_name} must be a stable bounded token")
    return value


def _require_asset_code(value: object) -> str | None:
    if value is None:
        return None
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > _MAX_ASSET_CODE_LENGTH
        or any(character.isspace() for character in value)
    ):
        raise AutoTradingOutcomeContractError(
            "asset_code must be a bounded canonical token or None"
        )
    return value


def _require_mapping_shape(
    payload: object, keys: frozenset[str], field_name: str
) -> Mapping[object, object]:
    if not isinstance(payload, Mapping):
        raise AutoTradingOutcomeContractError(f"{field_name} must be an object")
    if any(type(key) is not str for key in payload) or frozenset(payload) != keys:
        raise AutoTradingOutcomeContractError(f"{field_name} has missing or unknown fields")
    return payload


def _parse_issue_kind(value: object) -> AutoTradingIssueKind:
    if type(value) is not str:
        raise AutoTradingOutcomeContractError("issue kind must be text")
    try:
        return AutoTradingIssueKind(value)
    except ValueError as error:
        raise AutoTradingOutcomeContractError("issue kind is unknown") from error


def _parse_outcome(value: object) -> AutoTradingOutcome:
    if type(value) is not str:
        raise AutoTradingOutcomeContractError("outcome must be text")
    try:
        return AutoTradingOutcome(value)
    except ValueError as error:
        raise AutoTradingOutcomeContractError("outcome is unknown") from error


def _require_count_or_none(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_exact_int(value, field_name)


@dataclass(frozen=True, slots=True)
class AutoTradingIssue:
    """A safe stable issue, excluding free-form exception text.

    ``effects_indeterminate`` is true only when a failed execution write may
    have partially persisted its operation. It makes the aggregate stored
    count unavailable without erasing confirmed trades.
    """

    kind: AutoTradingIssueKind
    stage: str
    code: str
    asset_code: str | None = None
    effects_indeterminate: bool = False

    def __post_init__(self) -> None:
        if type(self.kind) is not AutoTradingIssueKind:
            raise AutoTradingOutcomeContractError("issue kind must be a recognized enum")
        _require_issue_token(self.stage, "stage", _STAGE_PATTERN)
        _require_issue_token(self.code, "code", _CODE_PATTERN)
        _require_asset_code(self.asset_code)
        _require_exact_bool(self.effects_indeterminate, "effects_indeterminate")
        if self.effects_indeterminate and self.kind is not AutoTradingIssueKind.FAILED:
            raise AutoTradingOutcomeContractError(
                "indeterminate write effects require a failed issue"
            )

    def to_payload(self) -> AutoTradingIssuePayload:
        """Serialize the issue into a fresh JSON-compatible object."""

        return {
            "kind": self.kind.value,
            "stage": self.stage,
            "code": self.code,
            "asset_code": self.asset_code,
            "effects_indeterminate": self.effects_indeterminate,
        }

    @classmethod
    def from_payload(cls, payload: object) -> AutoTradingIssue:
        """Parse an exact issue payload at a JSON boundary."""

        fields = _require_mapping_shape(
            payload,
            frozenset({"kind", "stage", "code", "asset_code", "effects_indeterminate"}),
            "issue",
        )
        kind = _parse_issue_kind(fields["kind"])
        stage = _require_issue_token(fields["stage"], "stage", _STAGE_PATTERN)
        code = _require_issue_token(fields["code"], "code", _CODE_PATTERN)
        asset_code = _require_asset_code(fields["asset_code"])
        effects_indeterminate = _require_exact_bool(
            fields["effects_indeterminate"], "effects_indeterminate"
        )
        return cls(
            kind=kind,
            stage=stage,
            code=code,
            asset_code=asset_code,
            effects_indeterminate=effects_indeterminate,
        )


@dataclass(frozen=True, slots=True)
class AccountAutoTradingOutcome:
    """Outcome for one account, derived from confirmed trades and issues."""

    account_id: int
    buy_count: int
    sell_count: int
    issues: tuple[AutoTradingIssue, ...] = ()

    def __post_init__(self) -> None:
        _require_exact_int(self.account_id, "account_id", minimum=1)
        _require_exact_int(self.buy_count, "buy_count")
        _require_exact_int(self.sell_count, "sell_count")
        if type(self.issues) is not tuple or any(
            type(issue) is not AutoTradingIssue for issue in self.issues
        ):
            raise AutoTradingOutcomeContractError("issues must be a tuple of typed issues")

    @property
    def outcome(self) -> AutoTradingOutcome:
        """Return the outcome implied by this account's confirmed trades."""

        if self.confirmed_trade_count:
            return AutoTradingOutcome.PARTIAL if self.issues else AutoTradingOutcome.SUCCESS
        if any(issue.kind is AutoTradingIssueKind.FAILED for issue in self.issues):
            return AutoTradingOutcome.FAILED
        if self.issues:
            return AutoTradingOutcome.BLOCKED
        return AutoTradingOutcome.NOOP

    @property
    def success(self) -> bool:
        """Return the legacy Celery-compatible success flag."""

        return self.outcome in {
            AutoTradingOutcome.SUCCESS,
            AutoTradingOutcome.PARTIAL,
            AutoTradingOutcome.NOOP,
        }

    @property
    def confirmed_trade_count(self) -> int:
        """Return the number of separately confirmed buy and sell trades."""

        return self.buy_count + self.sell_count

    @property
    def counts_unavailable(self) -> bool:
        """Return whether a write issue makes the stored count indeterminate."""

        return any(issue.effects_indeterminate for issue in self.issues)

    @property
    def stored(self) -> int | None:
        """Return confirmed stored trades only when no write effect is uncertain."""

        if self.counts_unavailable:
            return None
        return self.confirmed_trade_count

    @property
    def reason_code(self) -> str | None:
        """Return the explicit reason for an account with no work to record."""

        if self.outcome is AutoTradingOutcome.NOOP:
            return "NO_TRADES_CONFIRMED"
        return None

    def to_payload(self) -> AccountAutoTradingOutcomePayload:
        """Serialize the derived outcome using fresh JSON-compatible values."""

        return {
            "account_id": self.account_id,
            "outcome": self.outcome.value,
            "success": self.success,
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "confirmed_trade_count": self.confirmed_trade_count,
            "stored": self.stored,
            "counts_unavailable": self.counts_unavailable,
            "reason_code": self.reason_code,
            "issues": [issue.to_payload() for issue in self.issues],
        }

    @classmethod
    def from_payload(cls, payload: object) -> AccountAutoTradingOutcome:
        """Parse and verify an exact account outcome payload.

        Old buy/sell-only dictionaries are deliberately rejected because they
        cannot establish failure status or whether a write outcome is known.
        """

        fields = _require_mapping_shape(
            payload,
            frozenset(
                {
                    "account_id",
                    "outcome",
                    "success",
                    "buy_count",
                    "sell_count",
                    "confirmed_trade_count",
                    "stored",
                    "counts_unavailable",
                    "reason_code",
                    "issues",
                }
            ),
            "account outcome",
        )
        account_id = _require_exact_int(fields["account_id"], "account_id", minimum=1)
        raw_outcome = _parse_outcome(fields["outcome"])
        success = _require_exact_bool(fields["success"], "success")
        buy_count = _require_exact_int(fields["buy_count"], "buy_count")
        sell_count = _require_exact_int(fields["sell_count"], "sell_count")
        confirmed_trade_count = _require_exact_int(
            fields["confirmed_trade_count"], "confirmed_trade_count"
        )
        stored = _require_count_or_none(fields["stored"], "stored")
        counts_unavailable = _require_exact_bool(fields["counts_unavailable"], "counts_unavailable")
        reason_code_value = fields["reason_code"]
        if reason_code_value is not None and type(reason_code_value) is not str:
            raise AutoTradingOutcomeContractError("reason_code must be text or None")
        raw_issues = fields["issues"]
        if type(raw_issues) is not list:
            raise AutoTradingOutcomeContractError("issues must be a JSON array")
        issues = tuple(AutoTradingIssue.from_payload(issue) for issue in raw_issues)
        result = cls(account_id, buy_count, sell_count, issues)
        if (
            raw_outcome is not result.outcome
            or success is not result.success
            or confirmed_trade_count != result.confirmed_trade_count
            or stored != result.stored
            or counts_unavailable is not result.counts_unavailable
            or reason_code_value != result.reason_code
        ):
            raise AutoTradingOutcomeContractError("account payload disagrees with derived outcome")
        return result


@dataclass(frozen=True, slots=True)
class AutoTradingBatchOutcome:
    """Aggregate account outcomes with one consistent account work unit."""

    requested_account_ids: tuple[int, ...]
    accounts: tuple[AccountAutoTradingOutcome, ...]

    def __post_init__(self) -> None:
        if type(self.requested_account_ids) is not tuple:
            raise AutoTradingOutcomeContractError("requested_account_ids must be a tuple")
        requested = tuple(
            _require_exact_int(account_id, "requested_account_id", minimum=1)
            for account_id in self.requested_account_ids
        )
        if len(set(requested)) != len(requested):
            raise AutoTradingOutcomeContractError("requested account IDs must be unique")
        if type(self.accounts) is not tuple or any(
            type(account) is not AccountAutoTradingOutcome for account in self.accounts
        ):
            raise AutoTradingOutcomeContractError("accounts must be a tuple of typed outcomes")
        if tuple(account.account_id for account in self.accounts) != requested:
            raise AutoTradingOutcomeContractError(
                "batch accounts must match every requested account in order"
            )

    @property
    def outcome(self) -> AutoTradingOutcome:
        """Return the batch outcome without allowing no-op accounts to mask failures."""

        if not self.accounts:
            return AutoTradingOutcome.NOOP
        if self.confirmed_trade_count:
            return (
                AutoTradingOutcome.PARTIAL
                if any(account.issues for account in self.accounts)
                else AutoTradingOutcome.SUCCESS
            )
        issues = tuple(issue for account in self.accounts for issue in account.issues)
        if any(issue.kind is AutoTradingIssueKind.FAILED for issue in issues):
            return AutoTradingOutcome.FAILED
        if issues:
            return AutoTradingOutcome.BLOCKED
        # SUCCESS accounts necessarily have confirmed trades and returned above.
        return AutoTradingOutcome.NOOP

    @property
    def success(self) -> bool:
        """Return the legacy Celery-compatible success flag."""

        return self.outcome in {
            AutoTradingOutcome.SUCCESS,
            AutoTradingOutcome.PARTIAL,
            AutoTradingOutcome.NOOP,
        }

    @property
    def requested(self) -> int:
        """Return the number of requested accounts."""

        return len(self.requested_account_ids)

    @property
    def succeeded(self) -> int:
        """Return accounts with complete success or a valid no-op."""

        return sum(
            account.outcome in {AutoTradingOutcome.SUCCESS, AutoTradingOutcome.NOOP}
            for account in self.accounts
        )

    @property
    def failed(self) -> int:
        """Return all accounts not counted as fully successful, including partial."""

        return self.requested - self.succeeded

    @property
    def partial_account_count(self) -> int:
        """Return the number of accounts with some confirmed trades and issues."""

        return sum(account.outcome is AutoTradingOutcome.PARTIAL for account in self.accounts)

    @property
    def buy_count(self) -> int:
        """Return the total number of confirmed buy trades."""

        return sum(account.buy_count for account in self.accounts)

    @property
    def sell_count(self) -> int:
        """Return the total number of confirmed sell trades."""

        return sum(account.sell_count for account in self.accounts)

    @property
    def confirmed_trade_count(self) -> int:
        """Return all separately confirmed buy and sell trades."""

        return self.buy_count + self.sell_count

    @property
    def counts_unavailable(self) -> bool:
        """Return whether any account's storage effects are indeterminate."""

        return any(account.counts_unavailable for account in self.accounts)

    @property
    def stored(self) -> int | None:
        """Return a batch stored count only when every account is determinate."""

        if self.counts_unavailable:
            return None
        return sum(account.stored or 0 for account in self.accounts)

    @property
    def reason_code(self) -> str | None:
        """Return an explicit reason only when the whole batch is a no-op."""

        if not self.requested:
            return "NO_ACCOUNTS_REQUESTED"
        if self.outcome is AutoTradingOutcome.NOOP:
            return "NO_TRADES_CONFIRMED"
        return None

    def to_payload(self) -> AutoTradingBatchOutcomePayload:
        """Serialize the batch using fresh JSON-compatible account payloads."""

        return {
            "outcome": self.outcome.value,
            "success": self.success,
            "requested": self.requested,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "partial_account_count": self.partial_account_count,
            "stored": self.stored,
            "counts_unavailable": self.counts_unavailable,
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "confirmed_trade_count": self.confirmed_trade_count,
            "reason_code": self.reason_code,
            "accounts": [account.to_payload() for account in self.accounts],
        }

    @classmethod
    def from_payload(cls, payload: object) -> AutoTradingBatchOutcome:
        """Parse and verify a complete batch payload with no missing accounts."""

        fields = _require_mapping_shape(
            payload,
            frozenset(
                {
                    "outcome",
                    "success",
                    "requested",
                    "succeeded",
                    "failed",
                    "partial_account_count",
                    "stored",
                    "counts_unavailable",
                    "buy_count",
                    "sell_count",
                    "confirmed_trade_count",
                    "reason_code",
                    "accounts",
                }
            ),
            "batch outcome",
        )
        raw_outcome = _parse_outcome(fields["outcome"])
        success = _require_exact_bool(fields["success"], "success")
        requested = _require_exact_int(fields["requested"], "requested")
        succeeded = _require_exact_int(fields["succeeded"], "succeeded")
        failed = _require_exact_int(fields["failed"], "failed")
        partial_account_count = _require_exact_int(
            fields["partial_account_count"], "partial_account_count"
        )
        stored = _require_count_or_none(fields["stored"], "stored")
        counts_unavailable = _require_exact_bool(fields["counts_unavailable"], "counts_unavailable")
        buy_count = _require_exact_int(fields["buy_count"], "buy_count")
        sell_count = _require_exact_int(fields["sell_count"], "sell_count")
        confirmed_trade_count = _require_exact_int(
            fields["confirmed_trade_count"], "confirmed_trade_count"
        )
        reason_code_value = fields["reason_code"]
        if reason_code_value is not None and type(reason_code_value) is not str:
            raise AutoTradingOutcomeContractError("reason_code must be text or None")
        raw_accounts = fields["accounts"]
        if type(raw_accounts) is not list:
            raise AutoTradingOutcomeContractError("accounts must be a JSON array")
        accounts = tuple(AccountAutoTradingOutcome.from_payload(item) for item in raw_accounts)
        result = cls(tuple(account.account_id for account in accounts), accounts)
        if (
            raw_outcome is not result.outcome
            or success is not result.success
            or requested != result.requested
            or succeeded != result.succeeded
            or failed != result.failed
            or partial_account_count != result.partial_account_count
            or stored != result.stored
            or counts_unavailable is not result.counts_unavailable
            or buy_count != result.buy_count
            or sell_count != result.sell_count
            or confirmed_trade_count != result.confirmed_trade_count
            or reason_code_value != result.reason_code
        ):
            raise AutoTradingOutcomeContractError("batch payload disagrees with derived outcome")
        return result


def build_account_auto_trading_outcome(
    account_id: int,
    *,
    buy_count: int,
    sell_count: int,
    issues: tuple[AutoTradingIssue, ...] = (),
) -> AccountAutoTradingOutcome:
    """Build a validated account result from confirmed counts and safe issues."""

    return AccountAutoTradingOutcome(account_id, buy_count, sell_count, issues)


def build_auto_trading_batch_outcome(
    requested_account_ids: tuple[int, ...],
    results: Mapping[int, AccountAutoTradingOutcome],
) -> AutoTradingBatchOutcome:
    """Build one outcome per request, marking any absent account result failed."""

    if type(requested_account_ids) is not tuple:
        raise AutoTradingOutcomeContractError("requested_account_ids must be a tuple")
    requested = tuple(
        _require_exact_int(account_id, "requested_account_id", minimum=1)
        for account_id in requested_account_ids
    )
    if len(set(requested)) != len(requested):
        raise AutoTradingOutcomeContractError("requested account IDs must be unique")
    if not isinstance(results, Mapping):
        raise AutoTradingOutcomeContractError("results must be an account mapping")
    indexed: dict[int, AccountAutoTradingOutcome] = {}
    for account_id, supplied_outcome in results.items():
        _require_exact_int(account_id, "result account_id", minimum=1)
        if type(supplied_outcome) is not AccountAutoTradingOutcome:
            raise AutoTradingOutcomeContractError("result must be a typed account outcome")
        if supplied_outcome.account_id != account_id:
            raise AutoTradingOutcomeContractError("result key does not match its account outcome")
        if account_id not in requested:
            raise AutoTradingOutcomeContractError("result contains an unrequested account")
        indexed[account_id] = supplied_outcome
    ordered: list[AccountAutoTradingOutcome] = []
    for account_id in requested:
        account_outcome = indexed.get(account_id)
        if account_outcome is None:
            issue = AutoTradingIssue(
                kind=AutoTradingIssueKind.FAILED,
                stage="account_result",
                code="ACCOUNT_RESULT_MISSING",
                effects_indeterminate=True,
            )
            account_outcome = AccountAutoTradingOutcome(account_id, 0, 0, (issue,))
        ordered.append(account_outcome)
    return AutoTradingBatchOutcome(requested, tuple(ordered))
