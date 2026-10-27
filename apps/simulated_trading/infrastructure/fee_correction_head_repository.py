"""Owner-scoped read-only access to validated simulated fee correction history."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import DEFAULT_DB_ALIAS, transaction
from django.utils import timezone

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
    FeeCorrectionReceipt,
)
from apps.simulated_trading.application.fee_correction_head import (
    FeeCorrectionHead,
    FeeCorrectionHeadRepositoryProtocol,
)
from apps.simulated_trading.domain.entities import OrderStatus, SimulatedTrade
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)

from .fee_correction_repository_support import _receipt_from_event
from .trade_repository import DjangoTradeRepository


class DjangoFeeCorrectionHeadRepository(FeeCorrectionHeadRepositoryProtocol):
    """Lock current owner scope and derive a head from the guarded history projection."""

    def get_head(
        self,
        account_id: int,
        trade_id: int,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
        request_key: str | None = None,
    ) -> FeeCorrectionHead:
        """Read a corrected Trade head and optional exact persisted request receipt."""

        principal_user_id = _authenticated_principal_user_id(principal)
        if (
            type(account_id) is not int
            or account_id <= 0
            or type(trade_id) is not int
            or trade_id <= 0
        ):
            raise _blocked("费用更正 head 账户或交易编号无效", "FEE_CORRECTION_INPUT_INVALID")
        _validate_request_key(request_key)
        if principal_user_id is None:
            raise _authority_unavailable()

        with transaction.atomic(using=DEFAULT_DB_ALIAS):
            account = self._lock_owned_account(account_id, principal_user_id)
            as_of = timezone.now()
            projection = DjangoTradeRepository().get_account_history(
                account_id=account.pk,
                as_of=as_of,
            )
            trade = next(
                (row for row in projection.trades if row.trade_id == trade_id),
                None,
            )
            if trade is None or trade.status is not OrderStatus.EXECUTED:
                raise _blocked(
                    "目标模拟成交不存在或尚未执行",
                    "FEE_CORRECTION_TRADE_NOT_FOUND",
                )
            if trade.fee_amounts_known is not True or trade.cost_basis_known is not True:
                raise _blocked(
                    "目标成交费用或成本基数未知，无法提供更正 head",
                    "FEE_CORRECTION_ASSET_HISTORY_UNKNOWN",
                )

            future_event_exists = (
                SimulatedFeeCorrectionEventModel._base_manager.using(DEFAULT_DB_ALIAS)
                .filter(account_id=account.pk, trade_id=trade_id, posted_at__gt=as_of)
                .exists()
            )
            if future_event_exists:
                raise _blocked(
                    "目标成交存在尚未到达当前时点的更正事件",
                    "FEE_CORRECTION_HISTORY_INVALID",
                )

            revision, predecessor_id = _validated_head_identity(trade)
            request_receipt = self._request_receipt(
                account_id=account.pk,
                trade_id=trade_id,
                request_key=request_key,
            )
            return FeeCorrectionHead(
                account_id=account.pk,
                trade_id=trade_id,
                revision=revision,
                expected_predecessor_id=predecessor_id,
                as_of=as_of,
                trade=trade,
                request_receipt=request_receipt,
            )

    @staticmethod
    def _lock_owned_account(account_id: int, principal_user_id: int) -> SimulatedAccountModel:
        """Lock an active simulated account then its active current owner."""

        account = (
            SimulatedAccountModel._base_manager.using(DEFAULT_DB_ALIAS)
            .select_for_update(of=("self",))
            .filter(pk=account_id)
            .first()
        )
        if (
            account is None
            or account.account_type != "simulated"
            or account.is_active is not True
            or type(account.user_id) is not int
            or account.user_id != principal_user_id
        ):
            raise _authority_unavailable()

        user_model = get_user_model()
        actor = (
            user_model._base_manager.using(DEFAULT_DB_ALIAS)
            .select_for_update()
            .filter(pk=principal_user_id)
            .first()
        )
        if actor is None or getattr(actor, "is_active", None) is not True:
            raise _authority_unavailable()
        return account

    @staticmethod
    def _request_receipt(
        *,
        account_id: int,
        trade_id: int,
        request_key: str | None,
    ) -> FeeCorrectionReceipt | None:
        """Return an exact event receipt only after the caller validated full history."""

        if request_key is None:
            return None
        event = (
            SimulatedFeeCorrectionEventModel._base_manager.using(DEFAULT_DB_ALIAS)
            .filter(account_id=account_id, idempotency_key=request_key)
            .first()
        )
        if event is None:
            return None
        if event.trade_id != trade_id:
            raise _blocked(
                "幂等键已绑定到该账户中的另一笔交易",
                "FEE_CORRECTION_IDEMPOTENCY_CONFLICT",
            )
        return _receipt_from_event(event, replayed=True)


def _validated_head_identity(trade: SimulatedTrade) -> tuple[int, int | None]:
    """Derive sequence and predecessor from the complete validated trade projection."""

    revision = trade.fee_correction_revision
    events = trade.fee_correction_cash_events
    if type(events) is not tuple:
        raise _blocked("目标成交更正历史投影无效", "FEE_CORRECTION_HISTORY_INVALID")
    if revision is None:
        if events:
            raise _blocked(
                "目标成交更正事件与投影版本不一致",
                "FEE_CORRECTION_HISTORY_INVALID",
            )
        return 0, None
    if type(revision) is not int or revision <= 0 or len(events) != revision:
        raise _blocked(
            "目标成交更正版本链缺失或不完整",
            "FEE_CORRECTION_HISTORY_INVALID",
        )
    event_ids = tuple(getattr(event, "event_id", None) for event in events)
    if any(type(event_id) is not int or event_id <= 0 for event_id in event_ids) or len(
        set(event_ids)
    ) != len(event_ids):
        raise _blocked("目标成交更正前序身份无效", "FEE_CORRECTION_HISTORY_INVALID")
    return revision, event_ids[-1]


def _authenticated_principal_user_id(
    principal: AuthenticatedFeeCorrectionPrincipalProtocol,
) -> int | None:
    """Narrow an authenticated request actor without accepting body identifiers."""

    user_id = getattr(principal, "pk", None)
    if (
        getattr(principal, "is_authenticated", None) is not True
        or type(user_id) is not int
        or user_id <= 0
    ):
        return None
    return user_id


def _validate_request_key(request_key: str | None) -> None:
    """Enforce the same bounded key form as correction requests."""

    if request_key is None:
        return
    if (
        type(request_key) is not str
        or not request_key
        or request_key.strip() != request_key
        or len(request_key) > 128
        or any(character.isspace() for character in request_key)
    ):
        raise _blocked("费用更正幂等键无效", "FEE_CORRECTION_INPUT_INVALID")


def _authority_unavailable() -> FeeCorrectionBlockedError:
    """Return the non-disclosing owner and actor denial."""

    return _blocked(
        "费用更正历史仅对当前有效的模拟账户所有者开放",
        "FEE_CORRECTION_AUTHORITY_UNAVAILABLE",
    )


def _blocked(message: str, code: str) -> FeeCorrectionBlockedError:
    """Build the application's stable fee-correction block type."""

    return FeeCorrectionBlockedError(message, code=code)


__all__ = ["DjangoFeeCorrectionHeadRepository"]
