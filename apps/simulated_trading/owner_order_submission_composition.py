"""Compose explicit Sina paper-market previews with the ordinary reservation ledger."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

from django.db import DEFAULT_DB_ALIAS

from apps.data_center.application.sina_quote_capture import SinaQuoteCapture
from apps.data_center.calendar_publication_operations_composition import (
    read_current_exchange_calendar_reference,
)
from apps.data_center.calendar_workbench_scope_composition import (
    read_calendar_capture_configuration_reference_at,
)
from apps.data_center.composition import capture_sina_quote
from apps.risk_center.application.execution_settlement_v3 import (
    ReadEffectiveExecutionSettlementV3UseCase,
)
from apps.risk_center.application.local_simulated_market import (
    LocalSimulatedMarketBundle,
    build_submission_market,
)
from apps.risk_center.domain.close_snapshot_simulation import CloseSnapshotSimulationMarket
from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.risk_center.domain.execution_submission_v2 import (
    ExecutionSubmissionDecisionV2,
    ExecutionSubmissionMarketV2,
    evaluate_execution_submission,
)
from apps.risk_center.domain.execution_trading_constraints import (
    ExecutionDecisionStatus,
    ExecutionOrder,
    ExecutionSide,
    SellPositionCompleteness,
    SellPositionEvidence,
    SessionState,
)
from apps.risk_center.domain.local_simulated_market_policy import (
    LocalSimulatedCalendarContext,
    LocalSimulatedMarketPolicy,
)
from apps.risk_center.execution_settlement_composition import (
    build_execution_settlement_v3_rule_reader,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    AutomaticTradeStopLossMarketObservation,
    AutomaticTradeStopLossMarketQuote,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
)
from apps.simulated_trading.application.order_reservation import SimulatedOrderPlanPreparer
from apps.simulated_trading.application.order_submission_market import (
    LocalOrderSubmissionMarket,
    SimulatedOrderSubmissionGuard,
)
from apps.simulated_trading.application.owner_order_submission import (
    OwnerOrderSubmissionUseCase,
    identity_binding_hash,
)
from apps.simulated_trading.application.portfolio_risk_execution_gate import (
    ConfiguredPortfolioRiskLockedOrderGuard,
)
from apps.simulated_trading.application.transition_plan_execution import (
    TransitionPlanLockedActionGuard,
)
from apps.simulated_trading.close_snapshot_stop_loss_composition import (
    build_close_stop_loss_audit,
    capture_close_stop_loss_observation,
)
from apps.simulated_trading.close_snapshot_submission_composition import (
    SINA_CLOSE_SNAPSHOT_POLICIES_KEY as SINA_CLOSE_SNAPSHOT_POLICIES_KEY,
)
from apps.simulated_trading.close_snapshot_submission_composition import (
    CloseSnapshotMarketFactory,
    PurposeOrderMarketFactory,
)
from apps.simulated_trading.domain.account_stop_loss import evaluate_account_stop_loss
from apps.simulated_trading.domain.close_snapshot_execution_market_audit import (
    CloseSnapshotExecutionMarketAuditV1,
)
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
    LocalSimulatedExecutionMarketAuditV1,
    SettlementExecutionPlanV3,
)
from apps.simulated_trading.domain.execution_settlement_calendar import ExecutionCalendarEvidence
from apps.simulated_trading.domain.execution_settlement_identity import SettlementExecutionPlanV2
from apps.simulated_trading.domain.execution_settlement_primitives import (
    _hash_payload,
    _utc_text,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent
from apps.simulated_trading.execution_current_reference_composition import (
    _runtime_environment_from_settings_module,
    _ServerUTCClock,
    build_configured_execution_calendar_reader,
    build_current_reference_identity_reader,
)
from apps.simulated_trading.execution_settlement_composition import (
    build_execute_settlement_bound_simulated_trade_use_case,
)
from apps.simulated_trading.infrastructure.order_reservation_repository import (
    DjangoSimulatedOrderReservationRepository,
)
from apps.simulated_trading.infrastructure.owner_order_preview_codec import (
    SignedOwnerOrderPreviewCodec,
)
from core.exceptions import DataFetchError
from core.integration.config_center_runtime import (
    RuntimeConfigProfileRead,
    RuntimeConfigSnapshotRead,
    get_active_runtime_profile,
    get_active_runtime_value,
    get_latest_runtime_snapshot,
)

SINA_SUBMISSION_POLICIES_KEY = "config_center.market.simulated_sina_submission_policies"


@dataclass(frozen=True, slots=True)
class _PolicyBinding:
    policy: LocalSimulatedMarketPolicy
    runtime: dict[str, object]


def _read_policy(
    *, environment: str, security_id: str, asset_code: str, as_of: datetime
) -> _PolicyBinding:
    """Read one exact policy from an unchanged, integrity-checked active snapshot."""
    profile = get_active_runtime_profile(environment)
    if not isinstance(profile, RuntimeConfigProfileRead):
        raise SimulatedTradeExecutionBlocked("未配置本地模拟行情政策")
    snapshot = get_latest_runtime_snapshot(profile.profile_key)
    if not isinstance(snapshot, RuntimeConfigSnapshotRead):
        raise SimulatedTradeExecutionBlocked("模拟行情政策快照不可用")
    profile.__post_init__()
    snapshot.__post_init__()
    if (
        profile.environment != environment
        or profile.status != "active"
        or profile.activated_at is None
        or snapshot.effective_from != profile.activated_at
        or (snapshot.profile_id, snapshot.profile_key, snapshot.profile_version)
        != (profile.profile_id, profile.profile_key, profile.version)
        or not profile.created_at <= profile.activated_at <= snapshot.generated_at <= as_of
    ):
        raise SimulatedTradeExecutionBlocked("模拟行情政策尚不可用")
    value = get_active_runtime_value(
        environment=environment, definition_key=SINA_SUBMISSION_POLICIES_KEY, as_of=as_of
    )
    encoded = json.dumps(
        dict(snapshot.resolved_values),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if (
        value is None
        or snapshot.resolved_values.get(SINA_SUBMISSION_POLICIES_KEY) != value
        or hashlib.sha256(encoded).hexdigest() != snapshot.snapshot_hash
        or get_active_runtime_profile(environment) != profile
        or get_latest_runtime_snapshot(profile.profile_key) != snapshot
    ):
        raise SimulatedTradeExecutionBlocked("模拟行情政策内容已变化")
    if type(value) is not dict or set(value) != {"policies"}:
        raise SimulatedTradeExecutionBlocked("模拟行情政策配置不完整")
    raw = value.get("policies")
    if type(raw) is not list:
        raise SimulatedTradeExecutionBlocked("模拟行情政策列表无效")
    policies = tuple(
        LocalSimulatedMarketPolicy.from_payload(item) for item in cast(list[object], raw)
    )
    if len({p.security_id for p in policies}) != len(policies):
        raise SimulatedTradeExecutionBlocked("模拟行情政策证券范围有歧义")
    selected = [p for p in policies if (p.security_id, p.asset_code) == (security_id, asset_code)]
    if len(selected) != 1:
        raise SimulatedTradeExecutionBlocked("该证券尚无明确模拟行情政策")
    return _PolicyBinding(
        selected[0],
        {
            "profile_id": profile.profile_id,
            "profile_version": profile.version,
            "profile_hash": profile.content_hash,
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_hash": snapshot.snapshot_hash,
            "activated_at": profile.activated_at.isoformat(),
            "snapshot_generated_at": snapshot.generated_at.isoformat(),
        },
    )


class _RetainedSinaMarket:
    """Rebuild only local-purpose evidence from the original captured response."""

    def __init__(
        self, *, factory: _SinaMarketFactory, binding: _PolicyBinding, capture: SinaQuoteCapture
    ) -> None:
        self._factory = factory
        self._binding = binding
        self._capture = capture

    def export_retained_source(self) -> dict[str, object]:
        """Preserve original bytes and the exact active policy for scoped signing."""
        return {
            "capture": dict(self._capture.to_payload()),
            "security_id": self._binding.policy.security_id,
            "policy_hash": self._binding.policy.content_hash,
            "runtime": self._binding.runtime,
        }

    def read_market(
        self,
        *,
        plan: SettlementExecutionPlanV2 | SettlementExecutionPlanV3,
        execution_bundle: ExecutionSettlementBundleV3,
        as_of: datetime,
    ) -> LocalOrderSubmissionMarket:
        """Recheck current configuration and retained-source TTL under the account lock."""
        policy = self._binding.policy
        current = self._factory.read_binding(
            security_id=plan.intent.security_id, asset_code=plan.intent.asset_code, as_of=as_of
        )
        if current != self._binding:
            raise SimulatedTradeExecutionBlocked("行情政策已变化，请重新预览")
        fresh = self._factory.preparer.prepare(plan.intent, as_of=as_of)
        if (
            fresh.plan.fee_policy_v2.content_hash != plan.fee_policy_v2.content_hash
            or fresh.execution_bundle.content_hash != execution_bundle.content_hash
            or fresh.plan.calendar_evidence.evidence_hash != plan.calendar_evidence.evidence_hash
            or type(fresh.plan.identity_evidence) is not ExecutionInstrumentIdentityEvidenceV2
            or type(plan.identity_evidence) is not ExecutionInstrumentIdentityEvidenceV2
            or identity_binding_hash(fresh.plan.identity_evidence)
            != identity_binding_hash(plan.identity_evidence)
        ):
            raise SimulatedTradeExecutionBlocked("交易配置或来源在确认期间变化，请重新预览")
        evidence = plan.calendar_evidence
        calendar = self._calendar_context(evidence=evidence, as_of=as_of)
        bundle = build_submission_market(
            policy=policy,
            capture=self._capture,
            calendar=calendar,
            rule=execution_bundle.execution_submission_v2,
            as_of=as_of,
        )
        if bundle is None:
            raise SimulatedTradeExecutionBlocked(
                "报价陈旧、状态未知、休市或价界资料不足，当前不能预留",
                code="SIMULATED_ORDER_MARKET_UNAVAILABLE",
            )
        return self._wrap_market(bundle)

    def read_market_for_stop_loss(
        self,
        *,
        identity: ExecutionInstrumentIdentityEvidenceV2,
        calendar_evidence: ExecutionCalendarEvidence,
        execution_bundle: ExecutionSettlementBundleV3,
        as_of: datetime,
    ) -> LocalOrderSubmissionMarket:
        """Build one exact quote before an account stop-loss intent has its price."""

        policy = self._binding.policy
        try:
            identity.validate_at(as_of=as_of)
            ExecutionCalendarEvidence.__post_init__(calendar_evidence)
            ExecutionSettlementBundleV3.__post_init__(execution_bundle)
        except (ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "自动止损身份、日历或 Risk 合同无效",
                code="AUTO_STOP_LOSS_MARKET_UNAVAILABLE",
            ) from error
        if (
            (identity.security_id, identity.asset_code, identity.rule_market, identity.board)
            != (policy.security_id, policy.asset_code, policy.market, policy.board)
            or execution_bundle.execution_submission_v2.execution_rule_v1.security_id
            != identity.security_id
            or execution_bundle.execution_submission_v2.execution_rule_v1.board != identity.board
            or execution_bundle.source_available_at > as_of
            or execution_bundle.latest_source_observed_at > as_of
            or not execution_bundle.effective_from <= as_of < execution_bundle.valid_until
        ):
            raise SimulatedTradeExecutionBlocked(
                "自动止损证券或 Risk 市场范围不一致",
                code="AUTO_STOP_LOSS_MARKET_UNAVAILABLE",
            )
        current = self._factory.read_binding(
            security_id=identity.security_id,
            asset_code=identity.asset_code,
            as_of=as_of,
        )
        if current != self._binding:
            raise SimulatedTradeExecutionBlocked(
                "自动止损模拟行情政策已变化",
                code="AUTO_STOP_LOSS_MARKET_UNAVAILABLE",
            )
        if calendar_evidence.snapshot.exchange != identity.source_exchange:
            raise SimulatedTradeExecutionBlocked(
                "自动止损正式日历与证券交易所不一致",
                code="AUTO_STOP_LOSS_MARKET_UNAVAILABLE",
            )
        calendar = self._calendar_context(evidence=calendar_evidence, as_of=as_of)
        market_bundle = build_submission_market(
            policy=policy,
            capture=self._capture,
            calendar=calendar,
            rule=execution_bundle.execution_submission_v2,
            as_of=as_of,
        )
        if market_bundle is None:
            raise SimulatedTradeExecutionBlocked(
                "自动止损报价陈旧、状态未知、休市或价界资料不足",
                code="AUTO_STOP_LOSS_MARKET_UNAVAILABLE",
            )
        return self._wrap_market(market_bundle)

    def read_market_for_execution(
        self,
        *,
        plan: SettlementExecutionPlanV3,
        execution_bundle: ExecutionSettlementBundleV3,
        as_of: datetime,
    ) -> ExecutionSubmissionMarketV2:
        """Adapt the retained-source reader to the normal UoW Risk guard port."""

        selected = self.read_market(
            plan=plan,
            execution_bundle=execution_bundle,
            as_of=as_of,
        ).market
        if type(selected) is not ExecutionSubmissionMarketV2:
            raise SimulatedTradeExecutionBlocked("盘中行情读取返回了不同用途")
        return selected

    def _calendar_context(
        self, *, evidence: ExecutionCalendarEvidence, as_of: datetime
    ) -> LocalSimulatedCalendarContext:
        """Build the configured continuous-session context from published calendar rows."""

        evidence.validate_for(as_of)
        publication = evidence.publication
        if publication is None:
            raise SimulatedTradeExecutionBlocked("缺少正式交易日历")
        day = evidence.current_open_session(as_of)
        policy = self._binding.policy
        zone = ZoneInfo(policy.session_timezone)
        if not policy.session_windows:
            raise SimulatedTradeExecutionBlocked("未配置模拟交易时段")
        return LocalSimulatedCalendarContext(
            calendar_id=publication.publication_id,
            calendar_version=publication.publication_hash,
            calendar_source_hash=evidence.evidence_hash,
            calendar_observed_at=evidence.snapshot.raw_reference.response_completed_at,
            calendar_available_at=max(
                evidence.snapshot.recorded_at,
                publication.recorded_at,
                evidence.snapshot.raw_reference.response_completed_at,
            ),
            calendar_valid_until=publication.reference_valid_until,
            trading_date=day,
            session_id=f"{evidence.snapshot.exchange}:{day.isoformat()}",
            session_timezone=policy.session_timezone,
            session_open_at=datetime.combine(
                day, min(window.starts_at for window in policy.session_windows), zone
            ),
            session_close_at=datetime.combine(
                day, max(window.ends_at for window in policy.session_windows), zone
            ),
            session_state=SessionState.OPEN,
        )

    def _wrap_market(self, bundle: LocalSimulatedMarketBundle) -> LocalOrderSubmissionMarket:
        """Attach policy and retained-source provenance to one typed market bundle."""

        if type(bundle) is not LocalSimulatedMarketBundle:
            raise SimulatedTradeExecutionBlocked("本地模拟行情包类型无效")
        bundle.__post_init__()
        return LocalOrderSubmissionMarket(
            bundle.market,
            {
                "purpose": "local_simulation_only",
                "boundary_semantics": "configured_paper_derived_bounds",
                "security_state_semantics": "sina_vendor_reported",
                "calendar_clock_basis": "retained_calendar_response_completion",
                "capture_sha256": self._capture.body_sha256,
                "capture_received_at": self._capture.response_completed_at.isoformat(),
                "policy_id": self._binding.policy.policy_id,
                "policy_hash": self._binding.policy.content_hash,
                "policy_runtime": self._binding.runtime,
                "bundle_hash": bundle.content_hash,
                "retained_market_bundle": dict(bundle.to_payload()),
            },
        )


class _SinaMarketFactory:
    """Capture only on explicit preview; confirmation restores signed evidence."""

    def __init__(
        self,
        *,
        environment: str,
        clock: SimulatedTradeExecutionClock,
        preparer: SimulatedOrderPlanPreparer,
    ) -> None:
        """Bind lazy current-policy and ordinary planner dependencies."""
        self._environment = environment
        self._clock = clock
        self.preparer = preparer

    def read_binding(self, *, security_id: str, asset_code: str, as_of: datetime) -> _PolicyBinding:
        """Read current profile provenance for exactly one declared security."""
        return _read_policy(
            environment=self._environment,
            security_id=security_id,
            asset_code=asset_code,
            as_of=as_of,
        )

    def capture(self, *, intent: SimulatedTradeIntent) -> _RetainedSinaMarket:
        """Perform the explicit public GET after validating source configuration."""
        return self.capture_for_security(
            security_id=intent.security_id,
            asset_code=intent.asset_code,
            as_of=self._clock.now(),
        )

    def capture_for_security(
        self, *, security_id: str, asset_code: str, as_of: datetime
    ) -> _RetainedSinaMarket:
        """Capture one public quote for exact identity without inventing an order price."""

        binding = self.read_binding(
            security_id=security_id,
            asset_code=asset_code,
            as_of=as_of,
        )
        capture = capture_sina_quote(asset_code)
        if capture.asset_code != asset_code:
            raise SimulatedTradeExecutionBlocked(
                "新浪报价代码与当前证券不一致",
                code="AUTO_STOP_LOSS_MARKET_UNAVAILABLE",
            )
        return _RetainedSinaMarket(factory=self, binding=binding, capture=capture)

    def restore(self, *, payload: dict[str, object]) -> _RetainedSinaMarket:
        """Reconstruct only previously signed source bytes; do not refresh the quote."""
        if set(payload) != {"capture", "security_id", "policy_hash", "runtime"}:
            raise SimulatedTradeExecutionBlocked("原预览来源不完整")
        security_id = payload["security_id"]
        if type(security_id) is not str:
            raise SimulatedTradeExecutionBlocked("原预览证券来源无效")
        capture = SinaQuoteCapture.from_payload(payload["capture"])
        binding = self.read_binding(
            security_id=security_id, asset_code=capture.asset_code, as_of=self._clock.now()
        )
        if (
            binding.policy.content_hash != payload["policy_hash"]
            or binding.runtime != payload["runtime"]
        ):
            raise SimulatedTradeExecutionBlocked("原预览政策已变化，请重新预览")
        return _RetainedSinaMarket(factory=self, binding=binding, capture=capture)


class _AutomaticStopLossMarketProvider:
    """Capture and revalidate one explicitly configured local Sina market."""

    def __init__(
        self,
        *,
        factory: _SinaMarketFactory | CloseSnapshotMarketFactory,
        rule_reader: ReadEffectiveExecutionSettlementV3UseCase,
        clock: SimulatedTradeExecutionClock,
    ) -> None:
        """Bind current-policy, Risk V3, and server-clock readers without fetching data."""

        self._factory = factory
        self._rule_reader = rule_reader
        self._clock = clock

    def capture_market_for_account(
        self,
        *,
        account_id: int,
        identity: ExecutionInstrumentIdentityEvidenceV2,
        calendar_evidence: ExecutionCalendarEvidence,
        as_of: datetime,
    ) -> AutomaticTradeStopLossMarketObservation:
        """Select a separate account-bound close policy only for an explicit close request."""
        if isinstance(self._factory, CloseSnapshotMarketFactory):
            try:
                return capture_close_stop_loss_observation(
                    factory=self._factory,
                    rule_reader=self._rule_reader,
                    clock=self._clock,
                    account_id=account_id,
                    identity=identity,
                    calendar_evidence=calendar_evidence,
                    as_of=as_of,
                )
            except SimulatedTradeExecutionBlocked:
                raise
            except (
                ArithmeticError,
                AttributeError,
                DataFetchError,
                KeyError,
                TypeError,
                ValueError,
            ) as error:
                raise SimulatedTradeExecutionBlocked(
                    "收盘快照未通过本地模拟资格校验",
                    code="AUTO_STOP_LOSS_MARKET_UNAVAILABLE",
                ) from error
        return self.capture_market(
            identity=identity, calendar_evidence=calendar_evidence, as_of=as_of
        )

    def capture_market(
        self,
        *,
        identity: ExecutionInstrumentIdentityEvidenceV2,
        calendar_evidence: ExecutionCalendarEvidence,
        as_of: datetime,
    ) -> AutomaticTradeStopLossMarketObservation:
        """Capture one exact security and build a fully retained V2 paper-market observation."""

        if isinstance(self._factory, CloseSnapshotMarketFactory):
            raise SimulatedTradeExecutionBlocked("收盘快照止损必须显式指定账户")

        if type(identity) is not ExecutionInstrumentIdentityEvidenceV2:
            raise SimulatedTradeExecutionBlocked(
                "自动止损证券身份来源无效",
                code="AUTO_STOP_LOSS_MARKET_UNAVAILABLE",
            )
        try:
            identity.validate_at(as_of=as_of)
            calendar_evidence.validate_for(as_of)
        except (AttributeError, ArithmeticError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "自动止损证券或交易日历不可用",
                code="AUTO_STOP_LOSS_MARKET_UNAVAILABLE",
            ) from error
        try:
            retained = self._factory.capture_for_security(
                security_id=identity.security_id,
                asset_code=identity.asset_code,
                as_of=as_of,
            )
            captured_at = self._clock.now()
            if type(captured_at) is not datetime or captured_at.tzinfo is None:
                raise ValueError("server clock is not timezone-aware")
            if retained._capture.response_completed_at > captured_at:
                raise ValueError("Sina response completion is in the future")
            identity.validate_at(as_of=captured_at)
            calendar_evidence.validate_for(captured_at)
            execution_bundle = self._rule_reader.execute(
                security_id=identity.security_id,
                as_of=captured_at,
            )
            local_market = retained.read_market_for_stop_loss(
                identity=identity,
                calendar_evidence=calendar_evidence,
                execution_bundle=execution_bundle,
                as_of=captured_at,
            )
            provenance = local_market.provenance
            market_bundle = provenance.get("retained_market_bundle")
            if type(market_bundle) is not dict:
                raise ValueError("retained market bundle is missing")
            retained_source = retained.export_retained_source()
            retained_evidence = {
                "retained_source": retained_source,
                "market_bundle": market_bundle,
            }
            retained_evidence_json = json.dumps(
                retained_evidence,
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            market = local_market.market
            evidence = market.market_evidence_v1
            policy_payload = market_bundle.get("policy")
            calendar_payload = market_bundle.get("calendar")
            if type(policy_payload) is not dict or type(calendar_payload) is not dict:
                raise ValueError("retained policy or calendar payload is missing")
            policy_id = policy_payload.get("policy_id")
            policy_version = policy_payload.get("policy_version")
            policy_hash = policy_payload.get("content_hash")
            market_bundle_hash = market_bundle.get("content_hash")
            rule_hash = market_bundle.get("execution_rule_content_hash")
            calendar_hash = calendar_payload.get("content_hash")
            if (
                type(policy_id) is not str
                or type(policy_version) is not str
                or type(policy_hash) is not str
                or type(market_bundle_hash) is not str
                or type(rule_hash) is not str
                or type(calendar_hash) is not str
            ):
                raise ValueError("retained provenance identifiers are incomplete")
            observation = AutomaticTradeStopLossMarketObservation(
                security_id=identity.security_id,
                asset_code=identity.asset_code,
                market=market,
                reader=retained,
                retained_evidence_json=retained_evidence_json,
                retained_evidence_hash=hashlib.sha256(
                    retained_evidence_json.encode("utf-8")
                ).hexdigest(),
                source_id=evidence.market_source_id,
                source_version=evidence.market_source_version,
                source_hash=retained._capture.body_sha256,
                source_observed_at=evidence.market_observed_at,
                source_available_at=evidence.market_available_at,
                source_valid_until=evidence.market_valid_until,
                policy_id=policy_id,
                policy_version=policy_version,
                policy_hash=policy_hash,
                market_hash=market.content_hash,
                market_bundle_hash=market_bundle_hash,
                rule_hash=rule_hash,
                calendar_hash=calendar_hash,
            )
            observation.__post_init__()
            return observation
        except SimulatedTradeExecutionBlocked as error:
            raise SimulatedTradeExecutionBlocked(
                str(error),
                code="AUTO_STOP_LOSS_MARKET_UNAVAILABLE",
            ) from error
        except (
            ArithmeticError,
            AttributeError,
            DataFetchError,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise SimulatedTradeExecutionBlocked(
                "自动止损当前新浪行情不可用或未通过本地模拟资格校验",
                code="AUTO_STOP_LOSS_MARKET_UNAVAILABLE",
            ) from error

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
    ) -> LocalSimulatedExecutionMarketAuditV1 | CloseSnapshotExecutionMarketAuditV1:
        """Revalidate exact source, Risk V2 permission, and locked free shares."""

        if account_auto_trading_enabled is not True:
            raise SimulatedTradeExecutionBlocked(
                "账户未启用自动交易",
                code="AUTO_STOP_LOSS_ACCOUNT_DISABLED",
            )
        if (
            type(plan) is not SettlementExecutionPlanV3
            or type(quote) is not AutomaticTradeStopLossMarketQuote
        ):
            raise SimulatedTradeExecutionBlocked(
                "自动止损锁内计划或行情报价无效",
                code="AUTO_STOP_LOSS_MARKET_UNAVAILABLE",
            )
        intent = plan.intent
        if intent.side.value != "sell" or quote.intent != intent:
            raise SimulatedTradeExecutionBlocked(
                "自动止损行情与锁内交易意图不一致",
                code="AUTO_STOP_LOSS_MARKET_INTENT_MISMATCH",
            )
        if (
            position_total_quantity is None
            or position_available_after_holds is None
            or type(active_held_shares) is not Decimal
            or not active_held_shares.is_finite()
            or active_held_shares < Decimal(0)
        ):
            raise SimulatedTradeExecutionBlocked(
                "自动止损账户可卖持仓不完整",
                code="AUTO_STOP_LOSS_MARKET_RISK_BLOCKED",
            )
        if (
            type(position_total_quantity) is not Decimal
            or type(position_available_after_holds) is not Decimal
            or not position_total_quantity.is_finite()
            or not position_available_after_holds.is_finite()
            or position_total_quantity < Decimal(0)
            or position_available_after_holds < Decimal(0)
            or position_available_after_holds + active_held_shares > position_total_quantity
            or intent.quantity > position_available_after_holds
        ):
            raise SimulatedTradeExecutionBlocked(
                "自动止损数量超过账户未预留可卖持仓",
                code="AUTO_STOP_LOSS_MARKET_RISK_BLOCKED",
            )
        observation = quote.observation
        try:
            current_market = observation.reader.read_market_for_execution(
                plan=plan,
                execution_bundle=execution_bundle,
                as_of=as_of,
            )
            if (
                current_market.content_hash != observation.market_hash
                or current_market.market_evidence_v1.reference_price != intent.price
                or current_market.latest.value != intent.price
            ):
                raise SimulatedTradeExecutionBlocked(
                    "锁内重新校验的新浪报价与止损成交价格不一致",
                    code="AUTO_STOP_LOSS_MARKET_INTENT_MISMATCH",
                )
            if (
                account_stop_loss_pct is None
                or type(account_stop_loss_pct) is not Decimal
                or not account_stop_loss_pct.is_finite()
                or account_stop_loss_pct <= Decimal(0)
            ):
                raise SimulatedTradeExecutionBlocked(
                    "锁内账户止损阈值已移除或无效",
                    code="AUTO_STOP_LOSS_THRESHOLD_INVALID",
                )
            if (
                position_cost_basis_known is not True
                or position_total_cost is None
                or type(position_total_cost) is not Decimal
                or not position_total_cost.is_finite()
                or position_total_cost <= Decimal(0)
                or position_total_quantity <= Decimal(0)
            ):
                raise SimulatedTradeExecutionBlocked(
                    "锁内持仓成本基数不可用",
                    code="AUTO_STOP_LOSS_COST_BASIS_UNAVAILABLE",
                )
            if intent.quantity != position_total_quantity:
                raise SimulatedTradeExecutionBlocked(
                    "自动止损持仓数量已变化，拒绝部分或超额退出",
                    code="AUTO_STOP_LOSS_POSITION_CHANGED",
                )
            trigger = evaluate_account_stop_loss(
                price=intent.price,
                quantity=position_total_quantity,
                total_cost=position_total_cost,
                threshold_pct=account_stop_loss_pct,
            )
            locked_average_cost = trigger.average_cost
            locked_profit_loss_pct = trigger.pnl_pct
            if not trigger.triggered:
                raise SimulatedTradeExecutionBlocked(
                    "锁内成本或止损阈值已变化，当前行情不再触发止损",
                    code="AUTO_STOP_LOSS_TRIGGER_NO_LONGER_MET",
                )
            locked_position_payload: dict[str, object] = {
                "account_id": intent.account_id,
                "security_id": intent.security_id,
                "total_quantity": str(position_total_quantity),
                "cost_basis_known": position_cost_basis_known,
                "total_cost": str(position_total_cost),
                "derived_average_cost": str(locked_average_cost),
                "account_stop_loss_pct": str(account_stop_loss_pct),
                "market_price": str(intent.price),
                "calculated_pnl_pct": str(locked_profit_loss_pct),
                "threshold_crossed": True,
                "available_before_holds": str(position_available_after_holds + active_held_shares),
                "active_held_shares": str(active_held_shares),
                "available_to_sell_quantity": str(position_available_after_holds),
                "observed_at": as_of.isoformat(),
            }
            position = SellPositionEvidence(
                security_id=intent.security_id,
                account_id=intent.account_id,
                available_to_sell_quantity=position_available_after_holds,
                restricted_quantity=(position_total_quantity - position_available_after_holds),
                completeness=SellPositionCompleteness.COMPLETE,
                source_id="local_locked_simulated_ledger",
                source_version="automatic_stop_loss.v1",
                source_hash=_hash_payload(locked_position_payload),
                observed_at=as_of,
                available_at=as_of,
                valid_until=observation.source_valid_until,
            )
            order = ExecutionOrder(
                order_id=intent.idempotency_key,
                account_id=intent.account_id,
                security_id=intent.security_id,
                side=ExecutionSide.SELL,
                quantity=intent.quantity,
                limit_price=intent.price,
                sell_position_evidence=position,
            )
            if isinstance(current_market, CloseSnapshotSimulationMarket):
                return build_close_stop_loss_audit(
                    plan=plan,
                    execution_bundle=execution_bundle,
                    quote=quote,
                    market=current_market,
                    order=order,
                    locked_position=locked_position_payload,
                    as_of=as_of,
                )
            decision: ExecutionSubmissionDecisionV2 = evaluate_execution_submission(
                execution_bundle.execution_submission_v2,
                current_market,
                order,
                as_of,
            )
            decision_payload = decision.to_payload()
            if decision.status is not ExecutionDecisionStatus.ALLOWED:
                raise SimulatedTradeExecutionBlocked(
                    "Risk V2 未允许本次自动止损模拟卖出",
                    code="AUTO_STOP_LOSS_MARKET_RISK_BLOCKED",
                )
            evidence_payload: dict[str, object] = {
                "schema": "local-simulated-stop-loss-market-audit.v1",
                "purpose": "local_simulation_only",
                "retained_source": json.loads(observation.retained_evidence_json)[
                    "retained_source"
                ],
                "market_bundle": json.loads(observation.retained_evidence_json)["market_bundle"],
                "risk_decision": decision_payload,
                "risk_evaluated_at": _utc_text(as_of),
                "locked_position": locked_position_payload,
                "qualification": {
                    "purpose": "local_simulation_only",
                    "decision_scope": "automatic_account_stop_loss",
                    "freshness": "fresh",
                    "reliability": "vendor_reported_with_explicit_simulation_policy",
                    "must_not_use_for_decision": True,
                    "must_not_execute": True,
                    "execution_authority": False,
                    "global_identity_restrictions": {
                        "must_not_use_for_decision": True,
                        "must_not_execute": True,
                    },
                    "local_market_permission": {
                        "purpose": "local_simulation_only",
                        "must_not_use_for_decision": False,
                        "must_not_execute": True,
                        "execution_authority": False,
                    },
                    "market_available_at_basis": (
                        "local_response_completed_at_not_vendor_published_at"
                    ),
                },
            }
            evidence_json = json.dumps(
                evidence_payload,
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            audit = LocalSimulatedExecutionMarketAuditV1(
                account_id=intent.account_id,
                user_id=intent.user_id,
                idempotency_key=intent.idempotency_key,
                request_payload_hash=intent.request_payload_hash,
                security_id=intent.security_id,
                asset_code=intent.asset_code,
                execution_price=intent.price,
                source_id=observation.source_id,
                source_version=observation.source_version,
                source_hash=observation.source_hash,
                source_observed_at=observation.source_observed_at,
                source_available_at=observation.source_available_at,
                source_valid_until=observation.source_valid_until,
                policy_id=observation.policy_id,
                policy_version=observation.policy_version,
                policy_hash=observation.policy_hash,
                market_hash=observation.market_hash,
                market_bundle_hash=observation.market_bundle_hash,
                rule_hash=observation.rule_hash,
                calendar_hash=observation.calendar_hash,
                risk_decision_hash=_hash_payload(decision_payload),
                risk_evaluated_at=as_of,
                evidence_json=evidence_json,
            )
            audit.__post_init__()
            return audit
        except SimulatedTradeExecutionBlocked:
            raise
        except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as error:
            raise SimulatedTradeExecutionBlocked(
                "自动止损模拟卖出未通过锁内 Risk V2 校验",
                code="AUTO_STOP_LOSS_MARKET_RISK_BLOCKED",
            ) from error


class _GuardedRepositoryFactory:
    def __init__(self, transition_plan_guard: TransitionPlanLockedActionGuard | None) -> None:
        """Keep the same injected plan-context guard through explicit confirmation."""
        self._transition_plan_guard = transition_plan_guard

    def build(
        self, *, guard: SimulatedOrderSubmissionGuard
    ) -> DjangoSimulatedOrderReservationRepository:
        """Keep the public commit on the guarded default-alias writer."""
        from apps.simulated_trading.execution_settlement_composition import (
            build_configured_tax_cash_coverage_reader,
        )

        return DjangoSimulatedOrderReservationRepository(
            using=DEFAULT_DB_ALIAS,
            submission_guard=guard,
            portfolio_risk_guard=ConfiguredPortfolioRiskLockedOrderGuard(using=DEFAULT_DB_ALIAS),
            transition_plan_guard=self._transition_plan_guard,
            tax_cash_coverage_reader=build_configured_tax_cash_coverage_reader(
                using=DEFAULT_DB_ALIAS
            ),
        )


def build_owner_order_submission_use_case(
    *,
    market_purpose: str = "local_simulation_only",
    transition_plan_guard: TransitionPlanLockedActionGuard | None = None,
) -> OwnerOrderSubmissionUseCase:
    """Compose lazy owner ports without creating an order or fetching a quote."""
    if transition_plan_guard is None:
        from apps.simulated_trading.transition_plan_journey_composition import (
            build_configured_transition_plan_guard,
        )

        transition_plan_guard = build_configured_transition_plan_guard(using=DEFAULT_DB_ALIAS)
    environment = _runtime_environment_from_settings_module()
    from apps.simulated_trading.execution_settlement_composition import (
        build_configured_tax_cash_coverage_reader,
    )

    clock = _ServerUTCClock()
    identities = build_current_reference_identity_reader(runtime_environment=environment)
    calendar = build_configured_execution_calendar_reader(
        runtime_environment=environment,
        read_publication=read_current_exchange_calendar_reference,
        read_configuration=read_calendar_capture_configuration_reference_at,
    )
    rule_reader = build_execution_settlement_v3_rule_reader()
    preparer = build_execute_settlement_bound_simulated_trade_use_case(
        using=DEFAULT_DB_ALIAS,
        rule_reader=rule_reader,
        identity_reader=identities,
        calendar_reader=calendar,
        clock=clock,
    )
    return OwnerOrderSubmissionUseCase(
        identity_reader=identities,
        preparer=preparer,
        repository=DjangoSimulatedOrderReservationRepository(
            using=DEFAULT_DB_ALIAS,
            portfolio_risk_guard=ConfiguredPortfolioRiskLockedOrderGuard(using=DEFAULT_DB_ALIAS),
            transition_plan_guard=transition_plan_guard,
            tax_cash_coverage_reader=build_configured_tax_cash_coverage_reader(
                using=DEFAULT_DB_ALIAS
            ),
        ),
        repository_factory=_GuardedRepositoryFactory(transition_plan_guard),
        market_factory=PurposeOrderMarketFactory(
            intraday=_SinaMarketFactory(environment=environment, clock=clock, preparer=preparer),
            close=CloseSnapshotMarketFactory(
                environment=environment, clock=clock, preparer=preparer
            ),
            purpose=market_purpose,
        ),
        codec=SignedOwnerOrderPreviewCodec(),
        clock=clock,
        market_purpose=market_purpose,
    )


def build_automatic_stop_loss_market_provider(
    *, market_purpose: str = "local_simulation_only"
) -> _AutomaticStopLossMarketProvider:
    """Compose the source capture and locked Risk guard for local auto stop-loss."""

    if market_purpose not in ("local_simulation_only", "close_snapshot_simulation"):
        raise SimulatedTradeExecutionBlocked("未知模拟行情用途")
    environment = _runtime_environment_from_settings_module()
    clock = _ServerUTCClock()
    identities = build_current_reference_identity_reader(runtime_environment=environment)
    calendar = build_configured_execution_calendar_reader(
        runtime_environment=environment,
        read_publication=read_current_exchange_calendar_reference,
        read_configuration=read_calendar_capture_configuration_reference_at,
    )
    rule_reader = build_execution_settlement_v3_rule_reader()
    preparer = build_execute_settlement_bound_simulated_trade_use_case(
        using=DEFAULT_DB_ALIAS,
        rule_reader=rule_reader,
        identity_reader=identities,
        calendar_reader=calendar,
        clock=clock,
    )
    return _AutomaticStopLossMarketProvider(
        factory=(
            CloseSnapshotMarketFactory(environment=environment, clock=clock, preparer=preparer)
            if market_purpose == "close_snapshot_simulation"
            else _SinaMarketFactory(environment=environment, clock=clock, preparer=preparer)
        ),
        rule_reader=rule_reader,
        clock=clock,
    )
