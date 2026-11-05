"""Shared ordinary-order response formatting for session and plan-context views."""

from __future__ import annotations

from typing import cast

from apps.simulated_trading.application.order_submission_market import (
    CLOSE_ORDER_MARKET_PURPOSE as _CLOSE_MARKET_PURPOSE,
)
from apps.simulated_trading.application.order_submission_market import (
    LOCAL_ORDER_MARKET_PURPOSE as _LOCAL_MARKET_PURPOSE,
)
from apps.simulated_trading.application.order_submission_market import (
    SUPPORTED_ORDER_MARKET_PURPOSES as _SUPPORTED_MARKET_PURPOSES,
)
from apps.simulated_trading.application.owner_order_submission import (
    OwnerOrderPreview,
    OwnerOrderSubmissionResult,
)

CLOSE_SNAPSHOT_ORDER_NOTICE = "使用新浪供应商盘后末笔报价进行本地模拟；该报价不是官方收盘价。"
_CLOSE_MARKET_NOTICE = CLOSE_SNAPSHOT_ORDER_NOTICE


def owner_order_response_payload(
    result: OwnerOrderPreview | OwnerOrderSubmissionResult,
) -> dict[str, object]:
    """Format reviewed or durable resources while preserving unknown cash as null."""
    preview = isinstance(result, OwnerOrderPreview)
    reserved = result.result.reservation
    book = result.result.book
    payload: dict[str, object] = {
        "success": True,
        "outcome": "success",
        "read_only": preview,
        "account_id": reserved.identity.account_id,
        "order_key": reserved.identity.idempotency_key,
        "execution_submitted": False,
        "purpose": (
            result.market_receipt["purpose"]
            if isinstance(result, OwnerOrderPreview)
            else result.purpose
        ),
        "message": (
            "请核对数量、费用和预留后确认"
            if preview
            else (
                "已核对原订单，未重复预留；请查看当前状态"
                if result.result.replayed
                else "订单已预留，尚未成交；可在订单历史继续操作"
            )
        ),
        "replayed": result.result.replayed,
        "order": {
            "idempotency_key": reserved.identity.idempotency_key,
            "security_id": reserved.identity.security_id,
            "side": reserved.side.value,
            "quantity": str(reserved.quantity),
            "limit_price": str(reserved.limit_price),
            "notional": str(reserved.notional),
            "fee_estimate": str(reserved.fee_estimate),
            "fee_budget": str(reserved.fee_budget) if reserved.fee_budget is not None else None,
            "cash_reserved": str(reserved.cash_reserved),
            "shares_reserved": str(reserved.shares_reserved),
            "available_cash": str(book.available_cash) if book.available_cash is not None else None,
            "available_shares": (
                str(book.available_shares) if book.available_shares is not None else None
            ),
            "withdrawable_cash": (
                str(book.withdrawable_cash) if book.withdrawable_cash is not None else None
            ),
            "status": reserved.status.value,
        },
    }
    purpose = cast(str, payload["purpose"])
    if purpose not in _SUPPORTED_MARKET_PURPOSES:
        raise ValueError("订单回执行情用途无效")
    payload["market_purpose"] = purpose
    if purpose == _CLOSE_MARKET_PURPOSE:
        payload["market_notice"] = _CLOSE_MARKET_NOTICE
    if isinstance(result, OwnerOrderPreview):
        payload["continuation"] = {
            "action_key": "simulated-trading.order-confirm",
            "input": {
                "account_id": str(reserved.identity.account_id),
                "order_key": reserved.identity.idempotency_key,
                "preview_token": result.token,
            },
            "expires_at": result.expires_at.isoformat(),
        }
        market = result.market_receipt.get("market")
        if type(market) is dict:
            market_values = cast(dict[str, object], market)
            evidence = market_values.get("market_evidence_v1")
            if type(evidence) is dict:
                values = cast(dict[str, object], evidence)
                market_view: dict[str, object] = {
                    key: values.get(key)
                    for key in (
                        "market_source_id",
                        "market_observed_at",
                        "market_available_at",
                        "market_valid_until",
                        "security_state",
                        "reference_price",
                        "lower_limit_price",
                        "upper_limit_price",
                        "price_boundary_mode",
                        "session_state",
                    )
                }
                market_view["market_session"] = values.get("session_state")
                market_view["trade_date"] = values.get("trading_date")
                if purpose == _CLOSE_MARKET_PURPOSE:
                    snapshot_kind = market_values.get("price_observation_kind")
                    provenance = result.market_receipt.get("provenance")
                    if type(provenance) is not dict:
                        raise ValueError("盘后来源回执缺少来源凭据")
                    retained_bundle = cast(dict[str, object], provenance).get(
                        "retained_market_bundle"
                    )
                    if type(retained_bundle) is not dict:
                        raise ValueError("盘后来源回执缺少保留行情包")
                    policy = cast(dict[str, object], retained_bundle).get("policy")
                    if type(policy) is not dict:
                        raise ValueError("盘后来源回执缺少价格规则")
                    price_rule = cast(dict[str, object], policy).get("price_rule")
                    if type(snapshot_kind) is not str or type(price_rule) is not str:
                        raise ValueError("盘后来源回执类型无效")
                    market_view["snapshot_kind"] = snapshot_kind
                    market_view["price_rule"] = price_rule
                payload["market"] = market_view
                payload["market_qualification"] = result.market_receipt["qualification"]
                if purpose == _LOCAL_MARKET_PURPOSE:
                    payload["market_notice"] = (
                        "新浪报告状态；价界按明确配置推导，仅用于本地模拟。"
                        "可用时点为本地接收完成时间，不是新浪发布时间"
                    )
    else:
        payload["order_id"] = result.order_id
    return payload
