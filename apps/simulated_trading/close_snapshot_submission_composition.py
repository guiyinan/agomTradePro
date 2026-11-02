"""Compose explicitly configured, account-bound after-close quote simulations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from apps.data_center.application.sina_quote_capture import SinaQuoteCapture
from apps.data_center.composition import capture_sina_quote
from apps.data_center.domain.market_time import CN_MARKET_CLOSE, CN_MARKET_OPEN, CN_MARKET_TIMEZONE
from apps.risk_center.application.close_snapshot_simulation import (
    CloseSnapshotSimulationInput,
    CloseSnapshotSimulationUseCase,
)
from apps.risk_center.domain.close_snapshot_simulation import (
    CloseSnapshotSimulationBundle,
    CloseSnapshotSimulationMarket,
    CloseSnapshotSimulationPolicy,
)
from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.risk_center.domain.execution_trading_constraints import SessionState
from apps.risk_center.domain.local_simulated_market_policy import LocalSimulatedCalendarContext
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
)
from apps.simulated_trading.application.order_reservation import SimulatedOrderPlanPreparer
from apps.simulated_trading.application.order_submission_market import LocalOrderSubmissionMarket
from apps.simulated_trading.application.owner_order_submission import (
    OwnerOrderSubmissionMarketFactory,
    RetainedOrderSubmissionMarket,
    identity_binding_hash,
)
from apps.simulated_trading.domain.execution_current_reference import (
    ExecutionInstrumentIdentityEvidenceV2,
    SettlementExecutionPlanV3,
)
from apps.simulated_trading.domain.execution_settlement_calendar import ExecutionCalendarEvidence
from apps.simulated_trading.domain.execution_settlement_identity import SettlementExecutionPlanV2
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeIntent
from core.integration.config_center_runtime import (
    RuntimeConfigProfileRead,
    RuntimeConfigSnapshotRead,
    get_active_runtime_profile,
    get_active_runtime_value,
    get_latest_runtime_snapshot,
)

SINA_CLOSE_SNAPSHOT_POLICIES_KEY = "config_center.market.simulated_sina_close_snapshot_policies"
CLOSE_SNAPSHOT_PURPOSE = "close_snapshot_simulation"


@dataclass(frozen=True, slots=True)
class ClosePolicyBinding:
    """Bind an account policy to the exact activated runtime snapshot."""

    policy: CloseSnapshotSimulationPolicy
    runtime: dict[str, object]


def _read_close_policy(
    *,
    environment: str,
    account_id: int,
    security_id: str,
    asset_code: str,
    as_of: datetime,
) -> ClosePolicyBinding:
    """Require an explicit account/security policy in an intact active profile."""
    profile = get_active_runtime_profile(environment)
    if not isinstance(profile, RuntimeConfigProfileRead):
        raise SimulatedTradeExecutionBlocked("未配置收盘快照模拟政策")
    snapshot = get_latest_runtime_snapshot(profile.profile_key)
    if not isinstance(snapshot, RuntimeConfigSnapshotRead):
        raise SimulatedTradeExecutionBlocked("收盘快照模拟政策快照不可用")
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
        raise SimulatedTradeExecutionBlocked("收盘快照模拟政策尚不可用")
    value = get_active_runtime_value(
        environment=environment,
        definition_key=SINA_CLOSE_SNAPSHOT_POLICIES_KEY,
        as_of=as_of,
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
        or snapshot.resolved_values.get(SINA_CLOSE_SNAPSHOT_POLICIES_KEY) != value
        or hashlib.sha256(encoded).hexdigest() != snapshot.snapshot_hash
        or get_active_runtime_profile(environment) != profile
        or get_latest_runtime_snapshot(profile.profile_key) != snapshot
    ):
        raise SimulatedTradeExecutionBlocked("收盘快照模拟政策内容已变化")
    if type(value) is not dict or set(value) != {"policies"} or type(value["policies"]) is not list:
        raise SimulatedTradeExecutionBlocked("收盘快照模拟政策配置不完整")
    policies = tuple(
        CloseSnapshotSimulationPolicy.from_payload(item)
        for item in cast(list[object], value["policies"])
    )
    if len({(p.account_id, p.security_id) for p in policies}) != len(policies):
        raise SimulatedTradeExecutionBlocked("收盘快照模拟政策范围有歧义")
    selected = [
        p
        for p in policies
        if (p.account_id, p.security_id, p.asset_code) == (account_id, security_id, asset_code)
    ]
    if len(selected) != 1:
        raise SimulatedTradeExecutionBlocked("该账户及证券尚无明确收盘快照模拟政策")
    return ClosePolicyBinding(
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


class CloseSnapshotMarketFactory:
    """Capture once on an explicit close-purpose request and restore signed bytes."""

    def __init__(
        self,
        *,
        environment: str,
        clock: SimulatedTradeExecutionClock,
        preparer: SimulatedOrderPlanPreparer,
    ) -> None:
        """Bind lazy policy and financial-plan readers without enabling any account."""
        self.environment = environment
        self.clock = clock
        self.preparer = preparer

    def read_binding(
        self,
        *,
        account_id: int,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ClosePolicyBinding:
        """Read an account-scoped policy without borrowing an intraday policy."""
        return _read_close_policy(
            environment=self.environment,
            account_id=account_id,
            security_id=security_id,
            asset_code=asset_code,
            as_of=as_of,
        )

    def capture(self, *, intent: SimulatedTradeIntent) -> RetainedCloseSnapshotMarket:
        """Fetch the exact requested asset after the owner has been authorized."""
        return self.capture_for_security(
            account_id=intent.account_id,
            security_id=intent.security_id,
            asset_code=intent.asset_code,
            as_of=self.clock.now(),
        )

    def capture_for_security(
        self,
        *,
        account_id: int,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> RetainedCloseSnapshotMarket:
        """Capture actual response bytes for exactly one configured account/security."""
        binding = self.read_binding(
            account_id=account_id,
            security_id=security_id,
            asset_code=asset_code,
            as_of=as_of,
        )
        capture = capture_sina_quote(asset_code)
        if capture.asset_code != asset_code:
            raise SimulatedTradeExecutionBlocked("新浪报价代码与当前证券不一致")
        return RetainedCloseSnapshotMarket(factory=self, binding=binding, capture=capture)

    def restore(self, *, payload: dict[str, object]) -> RetainedCloseSnapshotMarket:
        """Restore authenticated source bytes without recapture or purpose fallback."""
        if set(payload) != {
            "purpose",
            "account_id",
            "capture",
            "security_id",
            "policy_hash",
            "runtime",
        }:
            raise SimulatedTradeExecutionBlocked("原收盘快照预览来源不完整")
        account_id, security_id = payload["account_id"], payload["security_id"]
        if (
            payload["purpose"] != CLOSE_SNAPSHOT_PURPOSE
            or type(account_id) is not int
            or account_id <= 0
            or type(security_id) is not str
        ):
            raise SimulatedTradeExecutionBlocked("原收盘快照预览范围无效")
        capture = SinaQuoteCapture.from_payload(payload["capture"])
        binding = self.read_binding(
            account_id=account_id,
            security_id=security_id,
            asset_code=capture.asset_code,
            as_of=self.clock.now(),
        )
        if (
            binding.policy.content_hash != payload["policy_hash"]
            or binding.runtime != payload["runtime"]
        ):
            raise SimulatedTradeExecutionBlocked("原收盘快照政策已变化，请重新预览")
        return RetainedCloseSnapshotMarket(factory=self, binding=binding, capture=capture)


class RetainedCloseSnapshotMarket:
    """Retain original source clocks while rechecking all current financial bindings."""

    def __init__(
        self,
        *,
        factory: CloseSnapshotMarketFactory,
        binding: ClosePolicyBinding,
        capture: SinaQuoteCapture,
    ) -> None:
        """Keep one policy snapshot and actual public quote response immutable."""
        self._factory = factory
        self._binding = binding
        self._capture = capture

    def export_retained_source(self) -> dict[str, object]:
        """Return account/purpose binding and the original retained response bytes."""
        return {
            "purpose": CLOSE_SNAPSHOT_PURPOSE,
            "account_id": self._binding.policy.account_id,
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
        """Recheck identity, fees, rules and calendar under the ordinary account lock."""
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
        return self.read_market_for_stop_loss(
            account_id=plan.intent.account_id,
            identity=plan.identity_evidence,
            calendar_evidence=plan.calendar_evidence,
            execution_bundle=execution_bundle,
            as_of=as_of,
        )

    def read_market_for_stop_loss(
        self,
        *,
        account_id: int,
        identity: ExecutionInstrumentIdentityEvidenceV2,
        calendar_evidence: ExecutionCalendarEvidence,
        execution_bundle: ExecutionSettlementBundleV3,
        as_of: datetime,
    ) -> LocalOrderSubmissionMarket:
        """Qualify only a CLOSED source-date snapshot with actual local availability."""
        policy = self._binding.policy
        identity.validate_at(as_of=as_of)
        calendar_evidence.validate_for(as_of)
        execution_bundle.__post_init__()
        if (
            self._factory.read_binding(
                account_id=account_id,
                security_id=identity.security_id,
                asset_code=identity.asset_code,
                as_of=as_of,
            )
            != self._binding
            or (identity.security_id, identity.asset_code, identity.rule_market, identity.board)
            != (policy.security_id, policy.asset_code, policy.market, policy.board)
            or calendar_evidence.snapshot.exchange != identity.source_exchange
            or execution_bundle.source_available_at > as_of
            or execution_bundle.latest_source_observed_at > as_of
            or not execution_bundle.effective_from <= as_of < execution_bundle.valid_until
        ):
            raise SimulatedTradeExecutionBlocked("收盘快照政策或金融来源范围已变化")
        publication = calendar_evidence.publication
        if publication is None:
            raise SimulatedTradeExecutionBlocked("缺少正式交易日历")
        day = calendar_evidence.current_open_session(as_of)
        if as_of < datetime.combine(day, CN_MARKET_CLOSE, CN_MARKET_TIMEZONE):
            raise SimulatedTradeExecutionBlocked("当前正式交易日尚未收盘")
        calendar = LocalSimulatedCalendarContext(
            calendar_id=publication.publication_id,
            calendar_version=publication.publication_hash,
            calendar_source_hash=calendar_evidence.evidence_hash,
            calendar_observed_at=calendar_evidence.snapshot.raw_reference.response_completed_at,
            calendar_available_at=max(
                calendar_evidence.snapshot.recorded_at,
                publication.recorded_at,
                calendar_evidence.snapshot.raw_reference.response_completed_at,
            ),
            calendar_valid_until=publication.reference_valid_until,
            trading_date=day,
            session_id=f"{calendar_evidence.snapshot.exchange}:{day.isoformat()}",
            session_timezone="Asia/Shanghai",
            session_open_at=datetime.combine(day, CN_MARKET_OPEN, CN_MARKET_TIMEZONE),
            session_close_at=datetime.combine(day, CN_MARKET_CLOSE, CN_MARKET_TIMEZONE),
            session_state=SessionState.CLOSED,
        )
        evaluation = CloseSnapshotSimulationUseCase().evaluate(
            CloseSnapshotSimulationInput(
                capture=self._capture,
                policy=policy,
                calendar=calendar,
                rule=execution_bundle.execution_submission_v2,
                account_id=account_id,
                security_id=identity.security_id,
                asset_code=identity.asset_code,
                trading_date=day,
                requested_price=(
                    self._capture.quote.last_price if self._capture.quote is not None else None
                ),
                as_of=as_of,
            )
        )
        bundle = evaluation.bundle
        if bundle is None:
            raise SimulatedTradeExecutionBlocked(
                "收盘快照尚不可用、超出使用期限或价界资料不足",
                code="SIMULATED_ORDER_MARKET_UNAVAILABLE",
            )
        return LocalOrderSubmissionMarket(
            bundle.market,
            {
                "purpose": CLOSE_SNAPSHOT_PURPOSE,
                "capture_sha256": self._capture.body_sha256,
                "capture_received_at": self._capture.response_completed_at.isoformat(),
                "policy_id": policy.policy_id,
                "policy_hash": policy.content_hash,
                "policy_runtime": self._binding.runtime,
                "bundle_hash": bundle.content_hash,
                "retained_market_bundle": dict(bundle.to_payload()),
            },
            close_bundle=bundle,
        )

    def read_market_for_execution(
        self,
        *,
        plan: SettlementExecutionPlanV3,
        execution_bundle: ExecutionSettlementBundleV3,
        as_of: datetime,
    ) -> CloseSnapshotSimulationMarket:
        """Revalidate the original capture immediately before a normal UoW write."""
        selected = self.read_market(plan=plan, execution_bundle=execution_bundle, as_of=as_of)
        if type(selected.close_bundle) is not CloseSnapshotSimulationBundle:
            raise SimulatedTradeExecutionBlocked("收盘快照来源包无效")
        return selected.close_bundle.market


class PurposeOrderMarketFactory:
    """Select explicitly at preview and dispatch authenticated retained purpose on confirm."""

    def __init__(
        self,
        *,
        intraday: OwnerOrderSubmissionMarketFactory,
        close: CloseSnapshotMarketFactory,
        purpose: str,
    ) -> None:
        """Reject unknown purposes without changing the ordinary intraday default."""
        if purpose not in ("local_simulation_only", CLOSE_SNAPSHOT_PURPOSE):
            raise SimulatedTradeExecutionBlocked("未知模拟行情用途")
        self._intraday, self._close, self._purpose = intraday, close, purpose

    def capture(self, *, intent: SimulatedTradeIntent) -> RetainedOrderSubmissionMarket:
        """Use only the explicitly selected source qualification path."""
        if self._purpose == CLOSE_SNAPSHOT_PURPOSE:
            return self._close.capture(intent=intent)
        return self._intraday.capture(intent=intent)

    def restore(self, *, payload: dict[str, object]) -> RetainedOrderSubmissionMarket:
        """Honor only a verified original purpose; no automatic fallback is permitted."""
        if payload.get("purpose") == CLOSE_SNAPSHOT_PURPOSE:
            return self._close.restore(payload=payload)
        if "purpose" in payload:
            raise SimulatedTradeExecutionBlocked("原预览模拟用途无效")
        return self._intraday.restore(payload=payload)
