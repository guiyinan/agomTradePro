"""Atomic persistence and locked reads for simulated fee corrections.

This repository keeps Trade and V4 receipt rows immutable. Corrections append
their own evidence event and update only the cash/basis projections owned by
the simulated ledger. Evidence, authority, and the canonical economic
fingerprint are injected explicitly; omitted adapters fail closed.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

from django.db import DEFAULT_DB_ALIAS, IntegrityError, transaction
from django.utils import timezone

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionAccountHistoryProjection,
    FeeCorrectionAuthorityProtocol,
    FeeCorrectionClockProtocol,
    FeeCorrectionEvidenceVerifierProtocol,
    FeeCorrectionReceipt,
    FeeCorrectionRepositoryProtocol,
    FeeCorrectionRequest,
    VerifiedFeeCorrectionAuthorization,
    VerifiedFeeCorrectionEvidence,
)
from apps.simulated_trading.domain.fee_correction import (
    AverageCostReplayResult,
    CorrectableFeeComponents,
    calculate_fee_correction_delta,
    calculate_ledger_percentage,
    require_exact_ledger_price,
    require_exact_ledger_quantity,
)
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_history import (
    _effective_fee_map,
    _exact_money,
    _money_add,
    fee_components_from_trade,
    project_trades_as_of,
    receipt_hashes_for_trades,
    receipt_snapshot_hash,
    replay_asset_history,
    require_account_ledger_currency,
    validate_cash_ledger,
    validate_event_chains,
)
from apps.simulated_trading.infrastructure.fee_correction_prefix import (
    fee_correction_account_genesis_sha256,
    fee_correction_account_prefix_sha256,
)
from apps.simulated_trading.infrastructure.fee_correction_repository_support import (
    _authority_snapshot_payload,
    _authority_snapshot_sha256,
    _blocked,
    _is_digest,
    _principal_user_id,
    _receipt_from_event,
    _request_payload_hash,
    _same_authority,
    _same_evidence_semantics,
    validate_authority_snapshot_event,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_account_history import (
    validate_account_v4_fill_history,
)
from apps.simulated_trading.infrastructure.order_reservation_guard import (
    lock_active_order_reservations,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)

_SHA256_HEX = frozenset("0123456789abcdef")


class TradeEconomicFingerprintProtocol(Protocol):
    """Build the canonical R4 economic fingerprint from the locked ORM row."""

    def hash_trade(
        self,
        *,
        trade: SimulatedTradeModel,
        original_v4_receipt_hash: str | None,
    ) -> str:
        """Return the application evidence codec's canonical trade SHA-256."""


class PersistedCorrectionSourceProofProtocol(Protocol):
    """Revalidate a previously appended local evidence binding and artifact."""

    def validate_event(
        self,
        event: SimulatedFeeCorrectionEventModel,
        *,
        original_v4_receipt_hash: str | None,
    ) -> bool:
        """Confirm that persisted source bytes and row still match the event."""


class PersistedCorrectionAuthorityProtocol(Protocol):
    """Revalidate the immutable actor authority record captured by an event."""

    def validate_event(
        self,
        event: SimulatedFeeCorrectionEventModel,
        *,
        original_v4_receipt_hash: str | None,
    ) -> bool:
        """Confirm that the historical local authority proof matches the event."""


class DjangoFeeCorrectionRepository(FeeCorrectionRepositoryProtocol):
    """Append source-qualified corrections using account-first ORM locks.

    All verifier callbacks are local and bounded. The absent defaults mean
    this repository cannot be activated until the evidence and authority
    adapters are explicitly wired by the composition root.
    """

    def __init__(
        self,
        *,
        evidence_verifier: FeeCorrectionEvidenceVerifierProtocol | None = None,
        authority: FeeCorrectionAuthorityProtocol | None = None,
        fingerprint: TradeEconomicFingerprintProtocol | None = None,
        persisted_source_proof: PersistedCorrectionSourceProofProtocol | None = None,
        persisted_authority: PersistedCorrectionAuthorityProtocol | None = None,
        using: str = DEFAULT_DB_ALIAS,
    ) -> None:
        self._evidence_verifier = evidence_verifier
        self._authority = authority
        self._fingerprint = fingerprint
        self._persisted_source_proof = persisted_source_proof
        self._persisted_authority = persisted_authority
        self._using = using

    def apply_fee_correction(
        self,
        *,
        request: FeeCorrectionRequest,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
        evidence: VerifiedFeeCorrectionEvidence,
        authorization: VerifiedFeeCorrectionAuthorization,
        clock: FeeCorrectionClockProtocol,
    ) -> FeeCorrectionReceipt:
        """Lock, revalidate, and atomically append one fee correction event."""

        request.__post_init__()
        principal_id = _principal_user_id(principal)
        if principal_id is None:
            raise _blocked("费用更正需要有效的已认证账户主体", "FEE_CORRECTION_PRINCIPAL_INVALID")
        if (
            type(evidence) is not VerifiedFeeCorrectionEvidence
            or type(authorization) is not VerifiedFeeCorrectionAuthorization
        ):
            raise _blocked("费用更正来源或权限证明类型无效", "FEE_CORRECTION_PROOF_INVALID")
        evidence.__post_init__()
        authorization.__post_init__()
        evidence_verifier = self._evidence_verifier
        authority = self._authority
        fingerprint = self._fingerprint
        if evidence_verifier is None or authority is None or fingerprint is None:
            raise _blocked(
                "费用更正的本地来源、权限或经济指纹验证器未配置",
                "FEE_CORRECTION_VERIFIER_UNAVAILABLE",
            )
        try:
            return self._apply_locked(
                request=request,
                principal=principal,
                principal_id=principal_id,
                evidence=evidence,
                authorization=authorization,
                clock=clock,
                evidence_verifier=evidence_verifier,
                authority=authority,
                fingerprint=fingerprint,
            )
        except IntegrityError as error:
            raise _blocked(
                "费用更正与并发版本或幂等键冲突",
                "FEE_CORRECTION_REVISION_CONFLICT",
            ) from error

    def _apply_locked(
        self,
        *,
        request: FeeCorrectionRequest,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
        principal_id: int,
        evidence: VerifiedFeeCorrectionEvidence,
        authorization: VerifiedFeeCorrectionAuthorization,
        clock: FeeCorrectionClockProtocol,
        evidence_verifier: FeeCorrectionEvidenceVerifierProtocol,
        authority: FeeCorrectionAuthorityProtocol,
        fingerprint: TradeEconomicFingerprintProtocol,
    ) -> FeeCorrectionReceipt:
        """Execute the complete account-scoped economic transaction."""

        using = self._using
        with transaction.atomic(using=using):
            account = (
                SimulatedAccountModel._base_manager.using(using)
                .select_for_update(of=("self",))
                .filter(pk=request.account_id)
                .first()
            )
            if (
                account is None
                or account.account_type != "simulated"
                or account.is_active is not True
            ):
                raise _blocked("目标模拟账户不存在或已停用", "SIMULATED_ACCOUNT_UNAVAILABLE")
            if type(account.user_id) is not int or account.user_id != principal_id:
                raise _blocked("费用更正主体不拥有目标账户", "FEE_CORRECTION_OWNER_MISMATCH")
            if (
                evidence.account_id != account.pk
                or evidence.trade_id != request.trade_id
                or evidence.expected_revision != request.expected_revision
                or authorization.account_id != account.pk
                or authorization.actor_user_id != principal_id
            ):
                raise _blocked(
                    "费用更正来源或权限范围与请求不一致", "FEE_CORRECTION_PROOF_SCOPE_MISMATCH"
                )
            if (
                account.cash_known is not True
                or account.cash_reconciliation_status != "simulated_ledger"
            ):
                raise _blocked("模拟账户现金账本未核实", "ACCOUNT_CASH_UNKNOWN")

            active_rows = lock_active_order_reservations(account_id=account.pk, using=using)
            validate_account_v4_fill_history(account=account, intent=None, using=using)

            trade_rows = tuple(
                SimulatedTradeModel._base_manager.using(using)
                .select_for_update(of=("self",))
                .filter(account_id=account.pk)
                .select_related("account")
                .order_by("pk")
            )
            trade_ids = tuple(row.pk for row in trade_rows if type(row.pk) is int)
            if len(trade_ids) != len(trade_rows):
                raise _blocked("账户交易历史包含未保存记录", "FEE_CORRECTION_HISTORY_INVALID")
            receipt_by_trade = receipt_hashes_for_trades(
                trade_ids=trade_ids,
                using=using,
                lock_rows=True,
            )
            event_rows = tuple(
                SimulatedFeeCorrectionEventModel._base_manager.using(using)
                .select_for_update(of=("self",))
                .filter(account_id=account.pk)
                .select_related("trade", "actor_user")
                .order_by("trade_id", "revision", "pk")
            )
            fingerprint_by_trade = self._fingerprints(
                trade_rows=trade_rows,
                receipt_by_trade=receipt_by_trade,
                trade_ids=frozenset(event.trade_id for event in event_rows),
                required=bool(event_rows),
            )
            event_ids_by_trade = validate_event_chains(
                account=account,
                trade_rows=trade_rows,
                event_rows=event_rows,
                receipt_by_trade=receipt_by_trade,
                fingerprint_by_trade=fingerprint_by_trade,
            )
            self._validate_persisted_proofs(event_rows, receipt_by_trade)
            account_prefix_events = sorted(
                event_rows,
                key=lambda event: event.account_revision,
            )
            account_revision = (
                account_prefix_events[-1].account_revision + 1 if account_prefix_events else 1
            )
            account_predecessor_hash = (
                account_prefix_events[-1].account_prefix_hash
                if account_prefix_events
                else fee_correction_account_genesis_sha256(account.pk)
            )
            validate_cash_ledger(
                account=account,
                trade_rows=trade_rows,
                event_rows=event_rows,
                using=using,
            )

            target = next((row for row in trade_rows if row.pk == request.trade_id), None)
            if target is None or target.account_id != account.pk or target.status != "executed":
                raise _blocked("目标成交不属于该账户", "FEE_CORRECTION_TRADE_NOT_FOUND")
            receipt = receipt_by_trade.get(target.pk)
            canonical_trade_hash = fingerprint_by_trade.get(target.pk)
            if canonical_trade_hash is None:
                canonical_trade_hash = fingerprint.hash_trade(
                    trade=target,
                    original_v4_receipt_hash=(
                        receipt.receipt_hash if receipt is not None else None
                    ),
                )
            if canonical_trade_hash != evidence.trade_snapshot_hash:
                raise _blocked("目标成交经济快照已变化", "FEE_CORRECTION_TRADE_SNAPSHOT_CONFLICT")
            if evidence.asset_code != target.asset_code:
                raise _blocked(
                    "来源证据资产与目标成交不一致", "FEE_CORRECTION_SOURCE_SCOPE_MISMATCH"
                )

            # Re-read local source and authority while the owner row is locked.
            # These adapters are forbidden from network I/O; absent adapters
            # were rejected before the transaction above.
            current_evidence = evidence_verifier.verify(request)
            current_authority = authority.authorize(
                account_id=account.pk,
                principal=principal,
            )
            if type(current_evidence) is not VerifiedFeeCorrectionEvidence:
                raise _blocked(
                    "来源材料或授权在保护边界复核时发生变化",
                    "FEE_CORRECTION_PROOF_STALE",
                )
            current_evidence.__post_init__()
            if (
                not _same_evidence_semantics(evidence, current_evidence)
                or type(current_authority) is not VerifiedFeeCorrectionAuthorization
            ):
                raise _blocked(
                    "来源材料或授权在保护边界复核时发生变化",
                    "FEE_CORRECTION_PROOF_STALE",
                )
            current_authority.__post_init__()
            if (
                not _same_authority(authorization, current_authority)
                or current_authority.actor_user_id != principal_id
                or current_authority.account_id != account.pk
            ):
                raise _blocked(
                    "来源材料或授权在保护边界复核时发生变化",
                    "FEE_CORRECTION_PROOF_STALE",
                )

            require_account_ledger_currency(
                event_rows=event_rows,
                authorization_currency=current_authority.policy_ledger_currency,
            )

            idempotency_match = next(
                (row for row in event_rows if row.idempotency_key == request.idempotency_key),
                None,
            )
            request_hash = _request_payload_hash(
                request=request,
                evidence=current_evidence,
                authorization=current_authority,
            )
            if idempotency_match is not None:
                if (
                    idempotency_match.trade_id != target.pk
                    or idempotency_match.request_payload_hash != request_hash
                ):
                    raise _blocked(
                        "费用更正幂等键已用于不同语义的请求",
                        "FEE_CORRECTION_IDEMPOTENCY_CONFLICT",
                    )
                return _receipt_from_event(idempotency_match, replayed=True)

            if active_rows:
                raise _blocked(
                    "账户存在未完成的资金或股份预留",
                    "ORDER_RESERVATION_ACTIVE",
                )

            # One injected, lock-scoped timestamp drives the current-history
            # view and the correction posting. Sampling a separate framework
            # clock here could include a different set of events from the
            # timestamp ultimately committed below.
            posted_at = clock.now()
            if (
                type(posted_at) is not datetime
                or posted_at.tzinfo is None
                or posted_at.utcoffset() is None
                or current_evidence.source_observed_at > current_evidence.verified_at
                or current_evidence.verified_at > posted_at
                or target.execution_time > posted_at
                or (
                    current_authority.policy_valid_from is not None
                    and posted_at < current_authority.policy_valid_from
                )
                or (
                    current_authority.policy_valid_until is not None
                    and posted_at >= current_authority.policy_valid_until
                )
                or (account_prefix_events and account_prefix_events[-1].posted_at > posted_at)
            ):
                raise _blocked(
                    "费用更正来源时间与入账时间顺序无效", "FEE_CORRECTION_CHRONOLOGY_INVALID"
                )
            posting_date = timezone.localdate(posted_at)

            prior_events = event_ids_by_trade.get(target.pk, ())
            expected_predecessor_id = prior_events[-1].pk if prior_events else None
            if (
                request.expected_revision != len(prior_events)
                or current_evidence.expected_revision != request.expected_revision
                or current_evidence.expected_predecessor_id != expected_predecessor_id
            ):
                raise _blocked("费用更正前序版本已变化", "FEE_CORRECTION_REVISION_CONFLICT")
            previous_fees = (
                CorrectableFeeComponents(
                    prior_events[-1].revised_commission,
                    prior_events[-1].revised_transfer_fee,
                    prior_events[-1].revised_stamp_duty,
                )
                if prior_events
                else fee_components_from_trade(target)
            )
            if current_evidence.previous_fee_components != previous_fees:
                raise _blocked(
                    "来源证据前值与最新账本版本不一致", "FEE_CORRECTION_REVISION_CONFLICT"
                )
            delta = calculate_fee_correction_delta(
                previous_fees,
                current_evidence.revised_fee_components,
            )

            position = (
                PositionModel._base_manager.using(using)
                .select_for_update(of=("self",))
                .filter(account_id=account.pk, asset_code=target.asset_code)
                .first()
            )
            account_trades = tuple(
                row
                for row in trade_rows
                if row.status == "executed" and row.asset_code == target.asset_code
            )
            latest_fees = _effective_fee_map(
                trade_rows=account_trades,
                events_by_trade=event_ids_by_trade,
                as_of=posted_at,
            )
            current_replay, _ = replay_asset_history(
                account_id=account.pk,
                asset_code=target.asset_code,
                trade_rows=account_trades,
                fee_map=latest_fees,
            )
            self._require_position_matches(position=position, replay=current_replay)
            corrected_fees = dict(latest_fees)
            corrected_fees[target.pk] = current_evidence.revised_fee_components
            corrected_replay, _ = replay_asset_history(
                account_id=account.pk,
                asset_code=target.asset_code,
                trade_rows=account_trades,
                fee_map=corrected_fees,
            )
            if corrected_replay.ending_quantity != current_replay.ending_quantity:
                raise _blocked("费用更正改变了持仓数量", "FEE_CORRECTION_ASSET_HISTORY_UNKNOWN")

            old_cash = _exact_money(account.current_cash, "account.current_cash")
            new_cash = _money_add(old_cash, delta.cash_delta, "account.corrected_cash")
            if new_cash < 0:
                raise _blocked("更正后的现金不足以覆盖费用差额", "FEE_CORRECTION_CASH_INSUFFICIENT")
            market_value = _exact_money(
                account.current_market_value, "account.current_market_value"
            )
            new_total_value = _money_add(new_cash, market_value, "account.corrected_total_value")
            if current_authority.actor_user_id != principal_id:
                raise _blocked(
                    "授权主体与已认证请求主体不一致", "FEE_CORRECTION_AUTHORITY_SCOPE_MISMATCH"
                )

            receipt_snapshot = receipt_snapshot_hash(receipt) if receipt is not None else None
            authority_snapshot = _authority_snapshot_payload(
                account=account,
                request=request,
                evidence=current_evidence,
                authorization=current_authority,
                request_hash=request_hash,
                revision=request.expected_revision + 1,
                account_revision=account_revision,
                account_predecessor_hash=account_predecessor_hash,
                predecessor_id=expected_predecessor_id,
                receipt_hash=receipt.receipt_hash if receipt is not None else None,
                receipt_snapshot=receipt_snapshot,
                original_slippage=_exact_money(target.slippage, "trade.slippage"),
                posted_at=posted_at,
                posting_date=posting_date,
            )
            authority_snapshot_sha256 = _authority_snapshot_sha256(authority_snapshot)
            account_prefix_hash = fee_correction_account_prefix_sha256(
                account_id=account.pk,
                account_revision=account_revision,
                predecessor_sha256=account_predecessor_hash,
                request_payload_sha256=request_hash,
                cash_delta=delta.cash_delta,
                authority_snapshot_sha256=authority_snapshot_sha256,
                posted_at=posted_at,
                posting_date=posting_date,
            )
            event = SimulatedFeeCorrectionEventModel(
                account_id=account.pk,
                trade_id=target.pk,
                actor_user_id=principal_id,
                revision=request.expected_revision + 1,
                account_revision=account_revision,
                account_predecessor_hash=account_predecessor_hash,
                account_prefix_hash=account_prefix_hash,
                previous_event_id=expected_predecessor_id,
                idempotency_key=request.idempotency_key,
                request_payload_hash=request_hash,
                trade_snapshot_hash=canonical_trade_hash,
                receipt_snapshot_hash=receipt_snapshot,
                source_namespace=current_evidence.source_namespace,
                source_record_id=current_evidence.source_record_id,
                verifier_identity=current_evidence.verifier_identity,
                source_evidence_hash=current_evidence.evidence_sha256,
                source_payload_hash=current_evidence.source_payload_sha256,
                source_observed_at=current_evidence.source_observed_at,
                evidence_verified_at=current_evidence.verified_at,
                authority_identity=current_authority.authority_identity,
                authority_record_id=current_authority.authority_record_id,
                authority_hash=current_authority.authority_sha256,
                authority_snapshot_json=authority_snapshot,
                authority_snapshot_sha256=authority_snapshot_sha256,
                previous_commission=previous_fees.commission,
                previous_transfer_fee=previous_fees.transfer_fee,
                previous_stamp_duty=previous_fees.stamp_duty,
                revised_commission=current_evidence.revised_fee_components.commission,
                revised_transfer_fee=current_evidence.revised_fee_components.transfer_fee,
                revised_stamp_duty=current_evidence.revised_fee_components.stamp_duty,
                original_slippage=_exact_money(target.slippage, "trade.slippage"),
                commission_delta=delta.commission,
                transfer_fee_delta=delta.transfer_fee,
                stamp_duty_delta=delta.stamp_duty,
                total_fee_delta=delta.total_fee_delta,
                cash_delta=delta.cash_delta,
                posted_at=posted_at,
                posting_date=posting_date,
            )
            event.save(using=using, force_insert=True)

            account.current_cash = new_cash
            account.total_value = new_total_value
            account.save(using=using, update_fields=("current_cash", "total_value", "updated_at"))
            self._save_corrected_position(
                position=position,
                replay=corrected_replay,
                using=using,
            )
            return _receipt_from_event(event, replayed=False)

    @staticmethod
    def _require_position_matches(
        *,
        position: PositionModel | None,
        replay: AverageCostReplayResult,
    ) -> None:
        """Reconcile the complete asset replay to the current stored Position."""

        ending_quantity = replay.ending_quantity
        ending_total_cost = replay.ending_total_cost
        ending_average_cost = replay.ending_average_cost
        if position is None:
            if ending_quantity != Decimal("0.000000") or ending_total_cost != Decimal("0.00"):
                raise _blocked(
                    "完整成交历史与当前持仓缺失", "FEE_CORRECTION_POSITION_RECONCILIATION_FAILED"
                )
            return
        quantity = _exact_quantity(position.quantity, "position.quantity")
        available_quantity = _exact_quantity(
            position.available_quantity,
            "position.available_quantity",
        )
        if (
            position.cost_basis_known is not True
            or quantity != ending_quantity
            or available_quantity > quantity
            or _exact_money(position.total_cost, "position.total_cost") != ending_total_cost
            or type(ending_average_cost) is not Decimal
            or _exact_price(position.avg_cost, "position.avg_cost") != ending_average_cost
        ):
            raise _blocked(
                "完整成交历史与当前持仓数量或成本基数不一致",
                "FEE_CORRECTION_POSITION_RECONCILIATION_FAILED",
            )

    @staticmethod
    def _save_corrected_position(
        *,
        position: PositionModel | None,
        replay: AverageCostReplayResult,
        using: str,
    ) -> None:
        """Update only proved cost projections while preserving valuation flags."""

        if position is None:
            return
        ending_quantity = replay.ending_quantity
        ending_total_cost = replay.ending_total_cost
        ending_average_cost = replay.ending_average_cost
        if (
            type(ending_quantity) is not Decimal
            or type(ending_total_cost) is not Decimal
            or type(ending_average_cost) is not Decimal
            or ending_quantity <= 0
        ):
            raise _blocked("更正后持仓结果无效", "FEE_CORRECTION_ASSET_HISTORY_UNKNOWN")
        position.total_cost = ending_total_cost
        position.avg_cost = ending_average_cost
        position.cost_basis_known = True
        update_fields = ["total_cost", "avg_cost", "cost_basis_known", "last_update_date"]
        if position.valuation_known is True:
            market_value = _exact_money(position.market_value, "position.market_value")
            unrealized = _money_add(
                market_value, ending_total_cost.copy_negate(), "position.unrealized_pnl"
            )
            position.unrealized_pnl = unrealized
            if ending_total_cost == 0:
                position.unrealized_pnl_pct = 0.0
            else:
                try:
                    pct = calculate_ledger_percentage(unrealized, ending_total_cost)
                    position.unrealized_pnl_pct = float(pct)
                except (ArithmeticError, InvalidOperation, TypeError, ValueError) as error:
                    raise _blocked(
                        "更正后持仓浮盈比例无法计算",
                        "FEE_CORRECTION_ASSET_HISTORY_UNKNOWN",
                    ) from error
            update_fields.extend(("unrealized_pnl", "unrealized_pnl_pct"))
        position.save(using=using, update_fields=tuple(update_fields))

    def get_account_history(
        self,
        *,
        account_id: int,
        as_of: datetime,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FeeCorrectionAccountHistoryProjection:
        """Read a consistent account-locked, full-history effective overlay."""

        if (
            type(account_id) is not int
            or account_id <= 0
            or type(as_of) is not datetime
            or as_of.tzinfo is None
            or as_of.utcoffset() is None
            or (start_date is not None and type(start_date) is not date)
            or (end_date is not None and type(end_date) is not date)
            or (start_date is not None and end_date is not None and start_date > end_date)
        ):
            raise _blocked("费用更正历史查询范围无效", "FEE_CORRECTION_AS_OF_INVALID")
        using = self._using
        with transaction.atomic(using=using):
            account = (
                SimulatedAccountModel._base_manager.using(using)
                .select_for_update(of=("self",))
                .filter(pk=account_id)
                .first()
            )
            if account is None or account.account_type != "simulated":
                raise _blocked("目标模拟账户不存在", "SIMULATED_ACCOUNT_UNAVAILABLE")
            lock_active_order_reservations(account_id=account_id, using=using)
            event_rows = tuple(
                SimulatedFeeCorrectionEventModel._base_manager.using(using)
                .filter(account_id=account_id)
                .select_related("trade", "actor_user")
                .order_by("trade_id", "revision", "pk")
            )
            if event_rows:
                validate_account_v4_fill_history(account=account, intent=None, using=using)
            trade_rows = tuple(
                SimulatedTradeModel._base_manager.using(using)
                .filter(account_id=account_id)
                .select_related("account")
                .order_by("pk")
            )
            trade_ids = tuple(row.pk for row in trade_rows if type(row.pk) is int)
            if len(trade_ids) != len(trade_rows):
                raise _blocked("账户交易历史包含未保存记录", "FEE_CORRECTION_HISTORY_INVALID")
            receipt_by_trade = receipt_hashes_for_trades(
                trade_ids=trade_ids,
                using=using,
                lock_rows=False,
            )
            fingerprint_by_trade = self._fingerprints(
                trade_rows=trade_rows,
                receipt_by_trade=receipt_by_trade,
                trade_ids=frozenset(event.trade_id for event in event_rows),
                required=bool(event_rows),
            )
            event_ids_by_trade = validate_event_chains(
                account=account,
                trade_rows=trade_rows,
                event_rows=event_rows,
                receipt_by_trade=receipt_by_trade,
                fingerprint_by_trade=fingerprint_by_trade,
            )
            self._validate_persisted_proofs(event_rows, receipt_by_trade)
            if event_rows:
                validate_cash_ledger(
                    account=account,
                    trade_rows=trade_rows,
                    event_rows=event_rows,
                    using=using,
                )
            return project_trades_as_of(
                account_id=account_id,
                trade_rows=trade_rows,
                events_by_trade=event_ids_by_trade,
                receipt_by_trade=receipt_by_trade,
                as_of=as_of,
                start_date=start_date,
                end_date=end_date,
            )

    def _fingerprints(
        self,
        *,
        trade_rows: tuple[SimulatedTradeModel, ...],
        receipt_by_trade: Mapping[int, SimulatedOrderFillReceiptModel],
        trade_ids: frozenset[int],
        required: bool,
    ) -> dict[int, str]:
        """Compute canonical proof identities for every persisted Trade."""

        if self._fingerprint is None:
            if required:
                raise _blocked(
                    "费用更正历史缺少规范经济快照指纹",
                    "FEE_CORRECTION_FINGERPRINT_UNAVAILABLE",
                )
            return {}
        result: dict[int, str] = {}
        for trade in trade_rows:
            if trade.pk not in trade_ids:
                continue
            if type(trade.pk) is not int:
                raise _blocked("Trade 快照缺少持久主键", "FEE_CORRECTION_HISTORY_INVALID")
            receipt = receipt_by_trade.get(trade.pk)
            value = self._fingerprint.hash_trade(
                trade=trade,
                original_v4_receipt_hash=(receipt.receipt_hash if receipt is not None else None),
            )
            if not _is_digest(value):
                raise _blocked(
                    "规范经济快照指纹格式无效",
                    "FEE_CORRECTION_FINGERPRINT_INVALID",
                )
            result[trade.pk] = value
        return result

    def _validate_persisted_proofs(
        self,
        event_rows: tuple[SimulatedFeeCorrectionEventModel, ...],
        receipt_by_trade: Mapping[int, SimulatedOrderFillReceiptModel],
    ) -> None:
        """Validate event-bound authority and require persisted proof readers."""

        for event in event_rows:
            receipt = receipt_by_trade.get(event.trade_id)
            if not validate_authority_snapshot_event(
                event,
                original_v4_receipt_hash=(receipt.receipt_hash if receipt is not None else None),
            ):
                raise _blocked(
                    "费用更正历史的事件授权快照无效",
                    "FEE_CORRECTION_HISTORY_PROOF_INVALID",
                )

        if event_rows and (
            self._persisted_source_proof is None or self._persisted_authority is None
        ):
            raise _blocked(
                "费用更正历史缺少本地来源与权限记录复核器",
                "FEE_CORRECTION_HISTORY_PROOF_UNAVAILABLE",
            )
        if self._persisted_source_proof is not None:
            for event in event_rows:
                receipt = receipt_by_trade.get(event.trade_id)
                original_receipt_hash = receipt.receipt_hash if receipt is not None else None
                if (
                    self._persisted_source_proof.validate_event(
                        event,
                        original_v4_receipt_hash=original_receipt_hash,
                    )
                    is not True
                ):
                    raise _blocked(
                        "费用更正历史的来源原件或绑定无法复核",
                        "FEE_CORRECTION_HISTORY_PROOF_INVALID",
                    )
        if self._persisted_authority is not None:
            for event in event_rows:
                receipt = receipt_by_trade.get(event.trade_id)
                original_receipt_hash = receipt.receipt_hash if receipt is not None else None
                if (
                    self._persisted_authority.validate_event(
                        event,
                        original_v4_receipt_hash=original_receipt_hash,
                    )
                    is not True
                ):
                    raise _blocked(
                        "费用更正历史的历史权限证明无法复核",
                        "FEE_CORRECTION_HISTORY_PROOF_INVALID",
                    )


def _exact_quantity(value: object, field_name: str) -> Decimal:
    """Require positive exact six-place quantity for position reconciliation."""

    if type(value) is not Decimal:
        raise _blocked(
            f"{field_name} cannot be represented", "FEE_CORRECTION_POSITION_RECONCILIATION_FAILED"
        )
    try:
        return require_exact_ledger_quantity(value, field_name, allow_zero=True)
    except (ArithmeticError, InvalidOperation, TypeError, ValueError) as error:
        raise _blocked(
            f"{field_name} cannot be represented", "FEE_CORRECTION_POSITION_RECONCILIATION_FAILED"
        ) from error


def _exact_price(value: object, field_name: str) -> Decimal:
    """Require exact four-place average cost."""

    if type(value) is not Decimal:
        raise _blocked(
            f"{field_name} cannot be represented", "FEE_CORRECTION_POSITION_RECONCILIATION_FAILED"
        )
    try:
        return require_exact_ledger_price(value, field_name, allow_zero=False)
    except (ArithmeticError, InvalidOperation, TypeError, ValueError) as error:
        raise _blocked(
            f"{field_name} cannot be represented", "FEE_CORRECTION_POSITION_RECONCILIATION_FAILED"
        ) from error


__all__ = [
    "DjangoFeeCorrectionRepository",
    "PersistedCorrectionAuthorityProtocol",
    "PersistedCorrectionSourceProofProtocol",
    "TradeEconomicFingerprintProtocol",
]
