"""Settlement-bound simulated-ledger use cases and inward-facing ports.

These use cases update the simulated account ledger after a caller has made
its separate market and order checks. Calendar evidence proves only explicit
exchange open dates and settlement-session advancement, not intraday phase or
execution authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from apps.risk_center.domain.execution_settlement_v3 import (
    ExecutionSettlementBundleV3,
    SettlementBasis,
)
from apps.risk_center.domain.execution_submission_v2 import ExecutionSubmissionMarketV2
from apps.simulated_trading.application.fee_policy_v2 import (
    FeePolicyVersionStorageUnavailable,
)
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
    LocalSimulatedExecutionMarketAuditV1,
    SettlementExecutionPlanV3,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeePolicyAccountScope,
    SimulatedFeePolicyV2,
)
from apps.simulated_trading.domain.execution_settlement_calendar import ExecutionCalendarEvidence
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
    IdentityEvidenceValidationError,
    PendingSettlementScopeV1,
    SettlementExecutionPlanV2,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    CalendarEvidenceValidationError,
    SettlementExecutionPlan,
    SimulatedTradeExecutionReceipt,
    SimulatedTradeIntent,
    SimulatedTradeSide,
    _execution_quantity_deny_code,
)
from core.exceptions import (
    BusinessLogicError,
    DuplicateResourceError,
    InvalidInputError,
    MissingConfigError,
)


class SimulatedTradeExecutionInputError(InvalidInputError):
    """Raised when a simulated settlement-bound trade request is malformed."""

    default_message = "模拟交易请求无效"
    default_code = "SIMULATED_TRADE_INPUT_INVALID"


class SimulatedTradeExecutionBlocked(BusinessLogicError):
    """Raised when source evidence or ledger state cannot support a safe mutation."""

    default_message = "模拟交易证据或账本状态不满足执行条件"
    default_code = "SIMULATED_TRADE_EXECUTION_BLOCKED"


class SimulatedTradeExecutionResultUnknown(SimulatedTradeExecutionBlocked):
    """Raised when the repository returned but its committed result is unverifiable."""

    default_message = "模拟交易账本返回结果不确定"
    default_code = "SIMULATED_TRADE_EXECUTION_RESULT_UNKNOWN"
    effects_indeterminate: bool = True


class SimulatedTradeAccountScopeUnavailable(SimulatedTradeExecutionBlocked):
    """Reject a missing, inactive, or no-longer-owned account before ledger writes."""

    default_message = "simulated account is missing, inactive, or outside the caller's owner scope"
    default_code = "SIMULATED_TRADE_ACCOUNT_SCOPE_UNAVAILABLE"


class ExecutionCalendarUnavailable(MissingConfigError):
    """Raised when a published, complete execution calendar reference is unavailable."""

    default_message = "可验证的交易所日历发布引用不可用"
    default_code = "EXECUTION_CALENDAR_UNAVAILABLE"


class ExecutionInstrumentIdentityUnavailable(MissingConfigError):
    """Raised when no exact, currently qualified source identity is available."""

    default_message = "证券身份来源证据不可用"
    default_code = "EXECUTION_INSTRUMENT_IDENTITY_UNAVAILABLE"


class ExecutionFeeScheduleUnavailable(MissingConfigError):
    """Raised when no exact effective V2 simulated fee policy can be read."""

    default_message = "模拟交易费率配置不可用"
    default_code = "EXECUTION_FEE_SCHEDULE_UNAVAILABLE"


class SimulatedTradeIdempotencyConflict(DuplicateResourceError):
    """Raised when one account reuses an idempotency key for a different intent."""

    default_message = "模拟交易幂等键已绑定到不同请求"
    default_code = "SIMULATED_TRADE_IDEMPOTENCY_CONFLICT"


class SimulatedTradeExecutionClock(Protocol):
    """Provide aware UTC values for default reads and post-lock writes."""

    def now(self) -> datetime:
        """Return the current timezone-aware clock value."""


class AutomaticTradeStopLossMarketReader(Protocol):
    """Revalidate one retained local market capture without fetching new bytes."""

    def read_market_for_execution(
        self,
        *,
        plan: SettlementExecutionPlanV3,
        execution_bundle: ExecutionSettlementBundleV3,
        as_of: datetime,
    ) -> ExecutionSubmissionMarketV2:
        """Return the exact retained market only when current policy and clocks still pass."""

    def export_retained_source(self) -> dict[str, object]:
        """Return original raw capture bytes and the active policy provenance."""


@dataclass(frozen=True, slots=True)
class AutomaticTradeStopLossMarketObservation:
    """One qualified local-market observation before it is bound to an order intent."""

    security_id: str
    asset_code: str
    market: ExecutionSubmissionMarketV2
    reader: AutomaticTradeStopLossMarketReader
    retained_evidence_json: str
    retained_evidence_hash: str
    source_id: str
    source_version: str
    source_hash: str
    source_observed_at: datetime
    source_available_at: datetime
    source_valid_until: datetime
    policy_id: str
    policy_version: str
    policy_hash: str
    market_hash: str
    market_bundle_hash: str
    rule_hash: str
    calendar_hash: str

    def __post_init__(self) -> None:
        """Bind exact V2 market clocks and retained public source evidence."""

        if type(self.market) is not ExecutionSubmissionMarketV2:
            raise SimulatedTradeExecutionBlocked("自动止损行情合同无效")
        try:
            ExecutionSubmissionMarketV2.__post_init__(self.market)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked("自动止损行情合同损坏") from error
        required = ("read_market_for_execution", "export_retained_source")
        if any(not callable(getattr(self.reader, name, None)) for name in required):
            raise SimulatedTradeExecutionBlocked("自动止损行情来源不可回读")
        for field_name, value in (
            ("security_id", self.security_id),
            ("asset_code", self.asset_code),
            ("source_id", self.source_id),
            ("source_version", self.source_version),
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
        ):
            if type(value) is not str or not value or value.strip() != value:
                raise SimulatedTradeExecutionBlocked(f"自动止损行情 {field_name} 无效")
        for field_name, value in (
            ("source_hash", self.source_hash),
            ("policy_hash", self.policy_hash),
            ("market_hash", self.market_hash),
            ("market_bundle_hash", self.market_bundle_hash),
            ("rule_hash", self.rule_hash),
            ("calendar_hash", self.calendar_hash),
        ):
            if (
                type(value) is not str
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise SimulatedTradeExecutionBlocked(f"自动止损行情 {field_name} 无效")
        if type(self.retained_evidence_json) is not str:
            raise SimulatedTradeExecutionBlocked("自动止损行情原件证明无效")
        try:
            evidence = json.loads(self.retained_evidence_json)
        except (TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked("自动止损行情原件证明无效") from error
        if type(evidence) is not dict or set(evidence) != {"retained_source", "market_bundle"}:
            raise SimulatedTradeExecutionBlocked("自动止损行情原件证明字段不完整")
        try:
            canonical_evidence = json.dumps(
                evidence,
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError, UnicodeEncodeError) as error:
            raise SimulatedTradeExecutionBlocked("自动止损行情原件证明不能规范化") from error
        if canonical_evidence != self.retained_evidence_json:
            raise SimulatedTradeExecutionBlocked("自动止损行情原件证明不是规范文本")
        if (
            type(self.retained_evidence_hash) is not str
            or len(self.retained_evidence_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.retained_evidence_hash)
            or hashlib.sha256(self.retained_evidence_json.encode("utf-8")).hexdigest()
            != self.retained_evidence_hash
        ):
            raise SimulatedTradeExecutionBlocked("自动止损行情原件证明哈希无效")
        retained_source = evidence["retained_source"]
        bundle = evidence["market_bundle"]
        if type(retained_source) is not dict or type(bundle) is not dict:
            raise SimulatedTradeExecutionBlocked("自动止损行情原件证明结构无效")
        market_payload = bundle.get("market")
        policy_payload = bundle.get("policy")
        calendar_payload = bundle.get("calendar")
        capture_payload = retained_source.get("capture")
        capture_hash: object = (
            capture_payload.get("body_sha256") if type(capture_payload) is dict else None
        )
        source = self.market.market_evidence_v1
        if (
            bundle.get("purpose") != "local_simulation_only"
            or bundle.get("content_hash") != self.market_bundle_hash
            or bundle.get("execution_rule_content_hash") != self.rule_hash
            or type(market_payload) is not dict
            or market_payload.get("content_hash") != self.market_hash
            or market_payload != self.market.to_payload()
            or type(policy_payload) is not dict
            or policy_payload.get("policy_id") != self.policy_id
            or policy_payload.get("policy_version") != self.policy_version
            or policy_payload.get("content_hash") != self.policy_hash
            or bundle.get("capture") != capture_payload
            or type(calendar_payload) is not dict
            or calendar_payload.get("content_hash") != self.calendar_hash
            or retained_source.get("policy_hash") != self.policy_hash
            or type(capture_payload) is not dict
            or capture_hash != self.source_hash
            or retained_source.get("security_id") != source.security_id
            or source.market_source_id != self.source_id
            or source.market_source_version != self.source_version
            or source.security_id != self.security_id
            or capture_payload.get("asset_code") != self.asset_code
            or self.market_hash != self.market.content_hash
            or source.market_observed_at != self.source_observed_at
            or source.market_available_at != self.source_available_at
            or source.market_valid_until != self.source_valid_until
            or source.market_observed_at > source.market_available_at
            or source.market_available_at >= source.market_valid_until
        ):
            raise SimulatedTradeExecutionBlocked("自动止损行情原件与市场证据不一致")
        try:
            current_source = self.reader.export_retained_source()
        except Exception as error:
            raise SimulatedTradeExecutionBlocked("自动止损行情原件无法回读") from error
        if current_source != retained_source:
            raise SimulatedTradeExecutionBlocked("自动止损行情原件与保留来源不一致")


class AutomaticTradeStopLossMarketProvider(Protocol):
    """Capture one explicitly configured local market for a current stop-loss check."""

    def capture_market(
        self,
        *,
        identity: ExecutionInstrumentIdentityEvidenceV2,
        calendar_evidence: ExecutionCalendarEvidence,
        as_of: datetime,
    ) -> AutomaticTradeStopLossMarketObservation:
        """Fetch public source bytes once and require complete local-simulation qualification."""


@dataclass(frozen=True, slots=True)
class AutomaticTradeStopLossMarketQuote:
    """Bind the captured market observation to one exact account SELL intent."""

    intent: SimulatedTradeIntent
    observation: AutomaticTradeStopLossMarketObservation

    def __post_init__(self) -> None:
        """Reject any difference between selected source price and ledger intent."""

        if type(self.intent) is not SimulatedTradeIntent:
            raise SimulatedTradeExecutionBlocked("自动止损交易意图无效")
        if type(self.observation) is not AutomaticTradeStopLossMarketObservation:
            raise SimulatedTradeExecutionBlocked("自动止损行情观察无效")
        try:
            SimulatedTradeIntent.__post_init__(self.intent)
            self.observation.__post_init__()
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked("自动止损行情与意图校验失败") from error
        market = self.observation.market
        evidence = market.market_evidence_v1
        if (
            self.intent.side is not SimulatedTradeSide.SELL
            or self.intent.security_id != evidence.security_id
            or self.intent.security_id != self.observation.security_id
            or self.intent.asset_code != self.observation.asset_code
            or self.intent.price != evidence.reference_price
            or market.latest.value != self.intent.price
        ):
            raise SimulatedTradeExecutionBlocked(
                "自动止损行情证券或价格与精确 SELL 意图不一致",
                code="AUTO_STOP_LOSS_MARKET_INTENT_MISMATCH",
            )


class AutomaticTradeStopLossMarketGuard(Protocol):
    """Run Risk V2 against the retained quote and actual locked local balances."""

    def validate_locked_submission(
        self,
        *,
        plan: SettlementExecutionPlanV3,
        execution_bundle: ExecutionSettlementBundleV3,
        quote: AutomaticTradeStopLossMarketQuote,
        account_auto_trading_enabled: bool,
        account_stop_loss_pct: Decimal | None,
        position_total_quantity: Decimal | None,
        position_total_cost: Decimal | None,
        position_cost_basis_known: bool,
        position_available_after_holds: Decimal | None,
        active_held_shares: Decimal,
        as_of: datetime,
    ) -> LocalSimulatedExecutionMarketAuditV1:
        """Recheck locked auto-stop-loss trigger inputs and Risk V2 before the SELL."""


class SettlementV3RuleReader(Protocol):
    """Read a source-backed Risk V3 bundle at one exact knowledge cutoff."""

    def execute(self, *, security_id: str, as_of: datetime) -> ExecutionSettlementBundleV3:
        """Return one exact effective V3 bundle or raise a typed block."""


class PublishedExecutionCalendarReader(Protocol):
    """Read an exact calendar snapshot bound to a formal publication reference."""

    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> ExecutionCalendarEvidence | None:
        """Return full-day coverage from the requested date and bind formal publication."""


class ExecutionInstrumentIdentityReader(Protocol):
    """Read an exact source identity mapping for one security at one cutoff."""

    def get_execution_instrument_identity(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV1 | ExecutionInstrumentIdentityEvidenceV2 | None:
        """Return exact identity evidence without inferring an exchange or board."""


class ExecutionFeePolicyReader(Protocol):
    """Read one exact effective V2 fee policy for a normal simulated estimate."""

    def get_execution_fee_policy(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_type: str,
        market: str,
        board: str,
        side: SimulatedTradeSide,
        as_of: datetime,
    ) -> SimulatedFeePolicyV2 | None:
        """Return an exact-case policy or None when no explicit version matches."""


class SimulatedTradeExecutionRepository(Protocol):
    """Read and atomically update simulated ledger rows on one database alias."""

    def find_idempotent_result(
        self, *, account_id: int, user_id: int, idempotency_key: str
    ) -> SimulatedTradeExecutionReceipt | None:
        """Return an existing exact-key result without changing ledger state."""

    def get_pending_settlement_start(
        self, *, account_id: int, user_id: int, asset_code: str
    ) -> date | None:
        """Return the legacy date-only view for existing internal readers."""

    def get_pending_settlement_scope(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_code: str,
    ) -> PendingSettlementScopeV1 | None:
        """Return the exact original exchange and earliest session of pending buys."""

    def execute_trade(
        self,
        *,
        plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
        execution_bundle: ExecutionSettlementBundleV3,
        clock: SimulatedTradeExecutionClock,
        market_guard: AutomaticTradeStopLossMarketGuard | None = None,
        market_quote: AutomaticTradeStopLossMarketQuote | None = None,
    ) -> SimulatedTradeExecutionReceipt:
        """Apply one exact plan, optionally rechecking a retained stop-loss quote."""

    def release_due_settlements(
        self,
        *,
        account_id: int,
        user_id: int,
        asset_code: str,
        calendar_evidence: ExecutionCalendarEvidence,
        clock: SimulatedTradeExecutionClock,
    ) -> int:
        """Release due tracked fills for one account/security in one transaction."""


def _require_aware_clock(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise SimulatedTradeExecutionInputError("交易用例要求带时区的时间")
    try:
        if value.utcoffset() is None:
            raise SimulatedTradeExecutionInputError("交易用例要求带时区的时间")
    except (OverflowError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionInputError("交易用例要求带时区的时间") from error
    return value


def _validate_bundle_scope(
    bundle: ExecutionSettlementBundleV3,
    intent: SimulatedTradeIntent,
    as_of: datetime,
) -> None:
    if type(bundle) is not ExecutionSettlementBundleV3:
        raise SimulatedTradeExecutionBlocked("Risk V3 reader returned a non-V3 contract")
    try:
        ExecutionSettlementBundleV3.__post_init__(bundle)
        policy = bundle.settlement_policy_v1
        base = bundle.execution_submission_v2.execution_rule_v1
        valid_at_cutoff = (
            bundle.source_available_at <= as_of
            and bundle.latest_source_observed_at <= as_of
            and bundle.effective_from <= as_of < bundle.valid_until
        )
    except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked("Risk V3 bundle failed integrity checks") from error
    if not valid_at_cutoff:
        raise SimulatedTradeExecutionBlocked("Risk V3 bundle is unavailable at the trade cutoff")
    if (
        policy.security_id != intent.security_id
        or base.security_id != intent.security_id
        or policy.market != intent.market
        or base.market != intent.market
        or policy.board != intent.board
        or base.board != intent.board
    ):
        raise SimulatedTradeExecutionBlocked(
            "Risk V3 security, market, or board differs from the exact trade intent"
        )
    if policy.settlement_basis is not SettlementBasis.CN_OPEN_MARKET_SESSIONS:
        raise SimulatedTradeExecutionBlocked("Risk V3 settlement basis is unsupported")


def _validate_identity_reader_result(
    value: object,
    *,
    intent: SimulatedTradeIntent,
    as_of: datetime,
) -> ExecutionInstrumentIdentityEvidenceV1 | ExecutionInstrumentIdentityEvidenceV2:
    """Validate one exact legacy or current-purpose identity reader result."""

    if type(value) is ExecutionInstrumentIdentityEvidenceV1:
        evidence: ExecutionInstrumentIdentityEvidenceV1 | ExecutionInstrumentIdentityEvidenceV2 = (
            value
        )
    elif type(value) is ExecutionInstrumentIdentityEvidenceV2:
        evidence = value
    else:
        raise SimulatedTradeExecutionBlocked(
            "instrument identity reader returned an invalid contract"
        )
    try:
        evidence.__post_init__()
        evidence.validate_for(intent=intent, as_of=as_of)
    except (ArithmeticError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            "instrument identity evidence is restricted, unknown, stale, or mismatched"
        ) from error
    return evidence


def _validate_plan_bundle_binding(
    plan: SettlementExecutionPlan | SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
    bundle: ExecutionSettlementBundleV3,
    as_of: datetime,
) -> None:
    """Require every plan summary field to match one exact current V3 bundle."""

    if type(plan) not in (
        SettlementExecutionPlan,
        SettlementExecutionPlanV2,
        SettlementExecutionPlanV3,
    ):
        raise SimulatedTradeExecutionBlocked("repository plan type is unsupported")
    try:
        plan.__post_init__()
        plan.validate_at(as_of)
        _validate_bundle_scope(bundle, plan.intent, as_of)
        policy = bundle.settlement_policy_v1
        expected_values: tuple[tuple[str, object, object], ...] = (
            ("settlement_bundle_id", plan.settlement_bundle_id, bundle.bundle_id),
            ("settlement_bundle_version", plan.settlement_bundle_version, bundle.bundle_version),
            ("settlement_bundle_hash", plan.settlement_bundle_hash, bundle.content_hash),
            ("settlement_policy_id", plan.settlement_policy_id, policy.policy_id),
            ("settlement_policy_version", plan.settlement_policy_version, policy.policy_version),
            ("settlement_policy_hash", plan.settlement_policy_hash, policy.content_hash),
            (
                "execution_rule_v2_hash",
                plan.execution_rule_v2_hash,
                bundle.execution_submission_v2.content_hash,
            ),
            (
                "settlement_lag_sessions",
                plan.settlement_lag_sessions,
                policy.settlement_lag_sessions,
            ),
            (
                "bundle_source_observed_at",
                plan.bundle_source_observed_at,
                bundle.latest_source_observed_at,
            ),
            (
                "bundle_source_available_at",
                plan.bundle_source_available_at,
                bundle.source_available_at,
            ),
            ("bundle_effective_from", plan.bundle_effective_from, bundle.effective_from),
            ("bundle_valid_until", plan.bundle_valid_until, bundle.valid_until),
        )
    except SimulatedTradeExecutionBlocked:
        raise
    except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            "settlement plan or exact V3 bundle failed revalidation"
        ) from error
    for field_name, plan_value, bundle_value in expected_values:
        if plan_value != bundle_value:
            raise SimulatedTradeExecutionBlocked(
                f"settlement plan differs from its exact V3 bundle field {field_name}"
            )


def _validate_quantity_preflight(
    intent: SimulatedTradeIntent,
    bundle: ExecutionSettlementBundleV3,
) -> None:
    """Reject only quantity violations that do not depend on a locked SELL balance."""

    rule = bundle.execution_submission_v2.execution_rule_v1
    quantity_rule = (
        rule.buy_quantity if intent.side is SimulatedTradeSide.BUY else rule.sell_quantity
    )
    deny_code = _execution_quantity_deny_code(
        side=intent.side,
        quantity=intent.quantity,
        minimum=quantity_rule.minimum,
        step=quantity_rule.step,
        maximum=quantity_rule.maximum,
        sell_odd_lot_mode=rule.sell_odd_lot_mode.value,
    )
    if deny_code is not None:
        raise SimulatedTradeExecutionBlocked(
            "trade quantity violates the exact Risk V3 quantity rule",
            code=deny_code,
        )


@dataclass(frozen=True, slots=True)
class PreparedSimulatedTrade:
    """Bind one validated intent to the same source plan used by execution."""

    plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3
    execution_bundle: ExecutionSettlementBundleV3


class ExecuteSettlementBoundSimulatedTradeUseCase:
    """Apply one exact simulated intent after source-backed V3/calendar reads.

    The current legacy buy/sell consumers are not implicitly replaced by this
    entry. A caller must perform its separate market, session, price, and order
    checks before submitting the intent here.
    """

    def __init__(
        self,
        *,
        rule_reader: SettlementV3RuleReader,
        identity_reader: ExecutionInstrumentIdentityReader,
        calendar_reader: PublishedExecutionCalendarReader,
        fee_policy_reader: ExecutionFeePolicyReader,
        repository: SimulatedTradeExecutionRepository,
        clock: SimulatedTradeExecutionClock,
    ) -> None:
        """Require explicit Risk, published-calendar, ledger, and clock ports."""

        self._rule_reader = rule_reader
        self._identity_reader = identity_reader
        self._calendar_reader = calendar_reader
        self._fee_policy_reader = fee_policy_reader
        self._repository = repository
        self._clock = clock

    def execute(
        self,
        intent: SimulatedTradeIntent,
        *,
        as_of: datetime | None = None,
        market_guard: AutomaticTradeStopLossMarketGuard | None = None,
        market_quote: AutomaticTradeStopLossMarketQuote | None = None,
    ) -> SimulatedTradeExecutionReceipt:
        """Read at one explicit cutoff, then write using the fresh locked clock."""

        if type(intent) is not SimulatedTradeIntent:
            raise SimulatedTradeExecutionInputError("必须提供精确的模拟交易意图")
        try:
            SimulatedTradeIntent.__post_init__(intent)
            request_hash = intent.request_payload_hash
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionInputError("模拟交易意图校验失败") from error

        if (market_guard is None) != (market_quote is None):
            raise SimulatedTradeExecutionInputError("自动止损行情校验器与报价必须同时提供")
        if market_quote is not None:
            if type(market_quote) is not AutomaticTradeStopLossMarketQuote:
                raise SimulatedTradeExecutionInputError("自动止损行情报价类型无效")
            try:
                market_quote.__post_init__()
            except (ArithmeticError, TypeError, ValueError) as error:
                raise SimulatedTradeExecutionBlocked("自动止损行情报价校验失败") from error
            if market_quote.intent != intent:
                raise SimulatedTradeExecutionBlocked(
                    "自动止损行情与结算意图不一致",
                    code="AUTO_STOP_LOSS_MARKET_INTENT_MISMATCH",
                )

        requested_cutoff = _require_aware_clock(as_of) if as_of is not None else None
        previous = self._repository.find_idempotent_result(
            account_id=intent.account_id,
            user_id=intent.user_id,
            idempotency_key=intent.idempotency_key,
        )
        if previous is not None:
            if type(previous) is not SimulatedTradeExecutionReceipt:
                raise SimulatedTradeExecutionBlocked(
                    "simulated ledger returned an invalid idempotency record"
                )
            if previous.request_payload_hash != request_hash:
                raise SimulatedTradeIdempotencyConflict(
                    "idempotency key already belongs to another exact request"
                )
            return replace(previous, replayed=True)

        prepared = self.prepare(intent, as_of=requested_cutoff)
        plan = prepared.plan
        bundle = prepared.execution_bundle
        if market_quote is not None and type(plan) is not SettlementExecutionPlanV3:
            raise SimulatedTradeExecutionBlocked("自动止损市场授权要求 V3 当前引用计划")

        if market_guard is None and market_quote is None:
            result = self._repository.execute_trade(
                plan=plan,
                execution_bundle=bundle,
                clock=self._clock,
            )
        else:
            result = self._repository.execute_trade(
                plan=plan,
                execution_bundle=bundle,
                clock=self._clock,
                market_guard=market_guard,
                market_quote=market_quote,
            )
        if type(result) is not SimulatedTradeExecutionReceipt:
            raise SimulatedTradeExecutionResultUnknown(
                "simulated ledger returned an invalid execution result"
            )
        try:
            SimulatedTradeExecutionReceipt.__post_init__(result)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionResultUnknown(
                "simulated ledger returned a damaged execution result"
            ) from error
        if (
            result.account_id != intent.account_id
            or result.idempotency_key != intent.idempotency_key
            or result.request_payload_hash != request_hash
        ):
            raise SimulatedTradeExecutionResultUnknown(
                "simulated ledger result differs from the exact request"
            )
        return result

    def prepare(
        self,
        intent: SimulatedTradeIntent,
        *,
        as_of: datetime | None = None,
    ) -> PreparedSimulatedTrade:
        """Read and qualify exact execution evidence without applying a trade.

        A reservation writer must revalidate this plan after locking its account.
        Preparing evidence does not authorize execution or commit any resources.
        """

        if type(intent) is not SimulatedTradeIntent:
            raise SimulatedTradeExecutionInputError("必须提供精确的模拟交易意图")
        try:
            SimulatedTradeIntent.__post_init__(intent)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionInputError("模拟交易意图校验失败") from error
        requested_cutoff = _require_aware_clock(as_of) if as_of is not None else None
        as_of = (
            requested_cutoff
            if requested_cutoff is not None
            else _require_aware_clock(self._clock.now())
        )
        bundle = self._rule_reader.execute(security_id=intent.security_id, as_of=as_of)
        _validate_bundle_scope(bundle, intent, as_of)
        _validate_quantity_preflight(intent, bundle)
        try:
            identity_evidence = self._identity_reader.get_execution_instrument_identity(
                security_id=intent.security_id,
                asset_code=intent.asset_code,
                as_of=as_of,
            )
        except IdentityEvidenceValidationError as error:
            raise SimulatedTradeExecutionBlocked(
                "instrument identity evidence failed exact source validation"
            ) from error
        if identity_evidence is None:
            raise ExecutionInstrumentIdentityUnavailable(
                "no qualified exact security/source identity is available"
            )
        identity_evidence = _validate_identity_reader_result(
            identity_evidence,
            intent=intent,
            as_of=as_of,
        )

        pending_scope = self._repository.get_pending_settlement_scope(
            account_id=intent.account_id,
            user_id=intent.user_id,
            asset_code=intent.asset_code,
        )
        if pending_scope is not None:
            if type(pending_scope) is not PendingSettlementScopeV1:
                raise SimulatedTradeExecutionBlocked(
                    "simulated ledger returned an invalid pending settlement scope"
                )
            try:
                PendingSettlementScopeV1.__post_init__(pending_scope)
            except (ArithmeticError, TypeError, ValueError) as error:
                raise SimulatedTradeExecutionBlocked(
                    "pending settlement scope failed exact validation"
                ) from error
            if pending_scope.source_exchange != identity_evidence.source_exchange:
                raise SimulatedTradeExecutionBlocked(
                    "pending settlements belong to a different source exchange"
                )
        pending_start = pending_scope.earliest_session if pending_scope is not None else None
        try:
            fee_policy = self._fee_policy_reader.get_execution_fee_policy(
                account_id=intent.account_id,
                user_id=intent.user_id,
                asset_type=intent.asset_type,
                market=intent.market,
                board=intent.board,
                side=intent.side,
                as_of=as_of,
            )
        except FeePolicyVersionStorageUnavailable as error:
            raise SimulatedTradeExecutionBlocked(
                "exact account-scoped simulated fee policy is unavailable"
            ) from error
        if fee_policy is None:
            raise ExecutionFeeScheduleUnavailable(
                "no explicit effective fee policy matches the exact simulated transaction"
            )
        if type(fee_policy) is not SimulatedFeePolicyV2:
            raise SimulatedTradeExecutionBlocked("fee policy reader returned an invalid contract")
        try:
            SimulatedFeePolicyV2.__post_init__(fee_policy)
            fee_policy.validate_at(as_of)
            fee_policy.case_for(
                asset_type=intent.asset_type,
                market=intent.market,
                board=intent.board,
                side=intent.side,
                as_of=as_of,
            )
            if fee_policy.account_scope is not FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS:
                raise ValueError("fee account scope is not explicitly supported")
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "fee policy failed integrity, transaction-case, or account-scope validation"
            ) from error
        evidence = self._calendar_reader.get_effective_execution_calendar(
            exchange=identity_evidence.source_exchange,
            as_of=as_of,
            coverage_start=pending_start,
        )
        if evidence is None:
            raise ExecutionCalendarUnavailable(
                "no published calendar reference covers the requested exchange"
            )
        if type(evidence) is not ExecutionCalendarEvidence:
            raise SimulatedTradeExecutionBlocked("calendar owner returned an invalid evidence type")
        try:
            evidence.validate_for(as_of)
            if evidence.snapshot.exchange != identity_evidence.source_exchange:
                raise CalendarEvidenceValidationError(
                    "calendar exchange differs from the exact instrument source exchange"
                )
            market_session = evidence.current_open_session(as_of)
            if pending_start is not None:
                evidence.elapsed_open_sessions(pending_start, market_session)
            lag = bundle.settlement_policy_v1.settlement_lag_sessions
            release_date = (
                evidence.release_session(market_session, lag)
                if intent.side.value == "buy"
                else None
            )
            if type(identity_evidence) is ExecutionInstrumentIdentityEvidenceV2:
                plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3 = (
                    SettlementExecutionPlanV3(
                        intent=intent,
                        market_session=market_session,
                        pre_read_at=as_of,
                        settlement_lag_sessions=lag,
                        settlement_release_date=release_date,
                        settlement_bundle_id=bundle.bundle_id,
                        settlement_bundle_version=bundle.bundle_version,
                        settlement_bundle_hash=bundle.content_hash,
                        settlement_policy_id=bundle.settlement_policy_v1.policy_id,
                        settlement_policy_version=bundle.settlement_policy_v1.policy_version,
                        settlement_policy_hash=bundle.settlement_policy_v1.content_hash,
                        execution_rule_v2_hash=bundle.execution_submission_v2.content_hash,
                        bundle_source_observed_at=bundle.latest_source_observed_at,
                        bundle_source_available_at=bundle.source_available_at,
                        bundle_effective_from=bundle.effective_from,
                        bundle_valid_until=bundle.valid_until,
                        calendar_evidence=evidence,
                        fee_policy_v2=fee_policy,
                        identity_evidence=identity_evidence,
                    )
                )
            elif type(identity_evidence) is ExecutionInstrumentIdentityEvidenceV1:
                plan = SettlementExecutionPlanV2(
                    intent=intent,
                    market_session=market_session,
                    pre_read_at=as_of,
                    settlement_lag_sessions=lag,
                    settlement_release_date=release_date,
                    settlement_bundle_id=bundle.bundle_id,
                    settlement_bundle_version=bundle.bundle_version,
                    settlement_bundle_hash=bundle.content_hash,
                    settlement_policy_id=bundle.settlement_policy_v1.policy_id,
                    settlement_policy_version=bundle.settlement_policy_v1.policy_version,
                    settlement_policy_hash=bundle.settlement_policy_v1.content_hash,
                    execution_rule_v2_hash=bundle.execution_submission_v2.content_hash,
                    bundle_source_observed_at=bundle.latest_source_observed_at,
                    bundle_source_available_at=bundle.source_available_at,
                    bundle_effective_from=bundle.effective_from,
                    bundle_valid_until=bundle.valid_until,
                    calendar_evidence=evidence,
                    fee_policy_v2=fee_policy,
                    identity_evidence=identity_evidence,
                )
            else:
                raise SimulatedTradeExecutionBlocked(
                    "instrument identity reader returned an invalid contract"
                )
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "calendar or settlement evidence is incomplete, stale, future, or mismatched"
            ) from error

        _validate_plan_bundle_binding(plan, bundle, as_of)

        return PreparedSimulatedTrade(plan=plan, execution_bundle=bundle)


class ReleaseDueSimulatedSettlementsUseCase:
    """Release only due, explicitly tracked simulated BUY fills for one security."""

    def __init__(
        self,
        *,
        calendar_reader: PublishedExecutionCalendarReader,
        repository: SimulatedTradeExecutionRepository,
        clock: SimulatedTradeExecutionClock,
    ) -> None:
        """Require published calendar, transaction repository, and aware clock ports."""

        self._calendar_reader = calendar_reader
        self._repository = repository
        self._clock = clock

    def execute(self, *, account_id: int, user_id: int, asset_code: str, exchange: str) -> int:
        """Release known due rows without rewriting their original settlement identity."""

        if type(account_id) is not int or account_id <= 0:
            raise SimulatedTradeExecutionInputError("account_id must be positive")
        if type(user_id) is not int or user_id <= 0:
            raise SimulatedTradeExecutionInputError("user_id must be positive")
        if (
            type(asset_code) is not str
            or not asset_code
            or asset_code.strip() != asset_code
            or len(asset_code) > 20
            or any(character.isspace() for character in asset_code)
        ):
            raise SimulatedTradeExecutionInputError("asset_code must be a canonical token")
        if (
            type(exchange) is not str
            or not exchange
            or exchange.strip() != exchange
            or any(character.isspace() for character in exchange)
        ):
            raise SimulatedTradeExecutionInputError("exchange must be a canonical token")
        pending_scope = self._repository.get_pending_settlement_scope(
            account_id=account_id,
            user_id=user_id,
            asset_code=asset_code,
        )
        if pending_scope is None:
            return 0
        if type(pending_scope) is not PendingSettlementScopeV1:
            raise SimulatedTradeExecutionBlocked(
                "simulated ledger returned an invalid pending settlement scope"
            )
        try:
            PendingSettlementScopeV1.__post_init__(pending_scope)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "pending settlement scope failed exact validation"
            ) from error
        if exchange != pending_scope.source_exchange:
            raise SimulatedTradeExecutionBlocked(
                "requested release exchange differs from the stored pending scope"
            )
        as_of = _require_aware_clock(self._clock.now())
        evidence = self._calendar_reader.get_effective_execution_calendar(
            exchange=pending_scope.source_exchange,
            as_of=as_of,
            coverage_start=pending_scope.earliest_session,
        )
        if evidence is None:
            raise ExecutionCalendarUnavailable(
                "no published calendar reference is available for settlement release"
            )
        if type(evidence) is not ExecutionCalendarEvidence:
            raise SimulatedTradeExecutionBlocked("calendar owner returned an invalid evidence type")
        try:
            evidence.validate_for(as_of)
            if evidence.snapshot.exchange != pending_scope.source_exchange:
                raise CalendarEvidenceValidationError("calendar exchange scope mismatch")
            current_session = evidence.current_open_session(as_of)
            evidence.elapsed_open_sessions(pending_scope.earliest_session, current_session)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "calendar cannot establish a known current open exchange session"
            ) from error
        return self._repository.release_due_settlements(
            account_id=account_id,
            user_id=user_id,
            asset_code=asset_code,
            calendar_evidence=evidence,
            clock=self._clock,
        )


__all__: tuple[str, ...] = (
    "ExecutionCalendarUnavailable",
    "ExecutionInstrumentIdentityReader",
    "ExecutionInstrumentIdentityUnavailable",
    "ExecutionFeePolicyReader",
    "ExecutionFeeScheduleUnavailable",
    "PublishedExecutionCalendarReader",
    "ReleaseDueSimulatedSettlementsUseCase",
    "SettlementV3RuleReader",
    "SimulatedTradeExecutionBlocked",
    "SimulatedTradeExecutionClock",
    "SimulatedTradeExecutionInputError",
    "SimulatedTradeExecutionRepository",
    "SimulatedTradeExecutionResultUnknown",
    "SimulatedTradeIdempotencyConflict",
    "ExecuteSettlementBoundSimulatedTradeUseCase",
    "PreparedSimulatedTrade",
)
