"""Application-facing helpers for share interface views."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, TypeVar

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from apps.share.application.repository_provider import get_share_interface_repository
from apps.share.application.use_cases import ShareSnapshotUseCases
from apps.share.domain.interfaces import (
    ShareDecisionRequest,
    ShareDecisionResponse,
    ShareDisclaimerConfigView,
    ShareLinkView,
    ShareOwnedAccountSnapshot,
    ShareOwnedPositionSnapshot,
    ShareSnapshotView,
)

_repo = get_share_interface_repository
logger = logging.getLogger(__name__)
T = TypeVar("T")

DECISION_STATUS_DISPLAY: dict[str, str] = {
    "pending": "待处理",
    "approved": "已批准",
    "rejected": "已拒绝",
    "executed": "已执行",
    "failed": "执行失败",
    "cancelled": "已取消",
}


def _normalize_portfolio_type(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"real", "live", "实盘", "实仓"}:
        return "real"
    return "simulated"


def _as_float(value: Decimal | float | int | str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _as_iso_datetime(value: date | datetime | time | None) -> str | None:
    if not value:
        return None
    return value.isoformat()


def _non_empty(*values: T | None) -> T | None:
    for value in values:
        if value not in (None, "", [], {}, ()):
            return value
    return None


def _direction_label(direction: str) -> str:
    mapping = {
        "BUY": "买入",
        "SELL": "卖出",
        "HOLD": "持有",
        "buy": "买入",
        "sell": "卖出",
        "hold": "持有",
    }
    return mapping.get(direction or "", direction or "观察")


def _asset_type_label(asset_type: str | None) -> str:
    mapping = {
        "equity": "股票",
        "fund": "基金",
        "bond": "债券",
        "cash": "现金",
    }
    return mapping.get((asset_type or "").strip().lower(), "其他")


def _decision_response(decision_request: ShareDecisionRequest) -> ShareDecisionResponse | None:
    try:
        return decision_request.response
    except ObjectDoesNotExist:
        return None


def _decision_status(
    decision_request: ShareDecisionRequest,
    response: ShareDecisionResponse | None,
) -> tuple[str, str]:
    if decision_request.execution_status == "executed":
        return "executed", DECISION_STATUS_DISPLAY["executed"]
    if decision_request.execution_status == "failed":
        return "failed", DECISION_STATUS_DISPLAY["failed"]
    if decision_request.execution_status == "cancelled":
        return "cancelled", DECISION_STATUS_DISPLAY["cancelled"]
    if response is not None:
        if response.approved:
            return "approved", DECISION_STATUS_DISPLAY["approved"]
        return "rejected", DECISION_STATUS_DISPLAY["rejected"]
    return "pending", DECISION_STATUS_DISPLAY["pending"]


def _build_decision_chain(
    account_id: int,
    asset_codes: set[str],
    positions_by_code: dict[str, ShareOwnedPositionSnapshot],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    decision_requests = _repo().list_decision_requests_for_account_assets(
        account_id=account_id,
        asset_codes=asset_codes,
    )
    if not decision_requests:
        return [], []

    decision_items: list[dict[str, Any]] = []
    evidence_items: list[dict[str, Any]] = []

    for decision_request in decision_requests:
        response = _decision_response(decision_request)
        recommendation = decision_request.unified_recommendation
        feature_snapshot = decision_request.feature_snapshot or (
            recommendation.feature_snapshot if recommendation else None
        )
        position = positions_by_code.get(decision_request.asset_code)
        status, status_display = _decision_status(decision_request, response)
        reason_codes = list(recommendation.reason_codes) if recommendation else []
        invalidation_logic = _non_empty(
            position.invalidation_description if position else None,
            (
                f"止损价 {float(recommendation.stop_loss_price):.4f}"
                if recommendation
                and recommendation.stop_loss_price
                and recommendation.stop_loss_price > Decimal("0")
                else None
            ),
        )

        item = {
            "title": f"{_direction_label(_non_empty(decision_request.direction, recommendation.side if recommendation else '') or '')} {decision_request.asset_code}",
            "status": status,
            "get_status_display": status_display,
            "description": _non_empty(
                decision_request.reason,
                response.approval_reason if response else None,
                response.rejection_reason if response else None,
                recommendation.human_rationale if recommendation else None,
            ),
            "rationale": _non_empty(
                recommendation.human_rationale if recommendation else None,
                response.approval_reason if response else None,
                response.rejection_reason if response else None,
                decision_request.reason,
            ),
            "asset_code": decision_request.asset_code,
            "created_at": _as_iso_datetime(decision_request.requested_at),
            "responded_at": _as_iso_datetime(response.responded_at) if response else None,
            "executed_at": _as_iso_datetime(decision_request.executed_at),
            "confidence": _non_empty(
                _as_float(recommendation.confidence if recommendation else None),
                _as_float(decision_request.expected_confidence),
            ),
            "reason_codes": reason_codes,
            "execution_target": decision_request.execution_target,
            "execution_status": decision_request.execution_status,
            "execution_ref": decision_request.execution_ref or {},
            "invalidation_logic": invalidation_logic,
        }
        decision_items.append(item)

        evidence_items.append(
            {
                "asset_code": decision_request.asset_code,
                "requested_at": _as_iso_datetime(decision_request.requested_at),
                "responded_at": _as_iso_datetime(response.responded_at) if response else None,
                "executed_at": _as_iso_datetime(decision_request.executed_at),
                "request_reason": decision_request.reason,
                "approval_reason": response.approval_reason if response else "",
                "rejection_reason": response.rejection_reason if response else "",
                "cooldown_status": response.cooldown_status if response else "",
                "quota_status": response.quota_status if response else None,
                "alternative_suggestions": response.alternative_suggestions if response else None,
                "reason_codes": reason_codes,
                "confidence": item["confidence"],
                "regime": _non_empty(
                    feature_snapshot.regime if feature_snapshot else None,
                    recommendation.regime if recommendation else None,
                ),
                "regime_confidence": _non_empty(
                    _as_float(feature_snapshot.regime_confidence if feature_snapshot else None),
                    _as_float(recommendation.regime_confidence if recommendation else None),
                ),
                "policy_level": _non_empty(
                    feature_snapshot.policy_level if feature_snapshot else None,
                    recommendation.policy_level if recommendation else None,
                ),
                "beta_gate_passed": _non_empty(
                    feature_snapshot.beta_gate_passed if feature_snapshot else None,
                    recommendation.beta_gate_passed if recommendation else None,
                ),
                "sentiment_score": _non_empty(
                    _as_float(feature_snapshot.sentiment_score if feature_snapshot else None),
                    _as_float(recommendation.sentiment_score if recommendation else None),
                ),
                "flow_score": _non_empty(
                    _as_float(feature_snapshot.flow_score if feature_snapshot else None),
                    _as_float(recommendation.flow_score if recommendation else None),
                ),
                "technical_score": _non_empty(
                    _as_float(feature_snapshot.technical_score if feature_snapshot else None),
                    _as_float(recommendation.technical_score if recommendation else None),
                ),
                "fundamental_score": _non_empty(
                    _as_float(feature_snapshot.fundamental_score if feature_snapshot else None),
                    _as_float(recommendation.fundamental_score if recommendation else None),
                ),
                "alpha_model_score": _non_empty(
                    _as_float(feature_snapshot.alpha_model_score if feature_snapshot else None),
                    _as_float(recommendation.alpha_model_score if recommendation else None),
                ),
                "entry_price_low": (
                    _as_float(recommendation.entry_price_low) if recommendation else None
                ),
                "entry_price_high": (
                    _as_float(recommendation.entry_price_high) if recommendation else None
                ),
                "target_price_low": (
                    _as_float(recommendation.target_price_low) if recommendation else None
                ),
                "target_price_high": (
                    _as_float(recommendation.target_price_high) if recommendation else None
                ),
                "stop_loss_price": (
                    _as_float(recommendation.stop_loss_price) if recommendation else None
                ),
                "position_pct": (
                    _as_float(recommendation.position_pct) if recommendation else None
                ),
                "execution_target": decision_request.execution_target,
                "execution_status": decision_request.execution_status,
                "execution_ref": decision_request.execution_ref or {},
                "invalidation_logic": invalidation_logic,
            }
        )

    return decision_items, evidence_items


def get_share_link_queryset(owner_id: int) -> Iterable[ShareLinkView]:
    """Return owner share links for API listing."""

    return _repo().get_share_link_queryset_for_owner(owner_id)


def get_share_link_model(share_link_id: int) -> ShareLinkView | None:
    """Return one share link model by id when available."""

    return _repo().get_share_link_by_id(share_link_id)


def get_public_share_link_model(short_code: str) -> ShareLinkView | None:
    """Return one share link model by short code when available."""

    return _repo().get_share_link_by_code(short_code)


def get_owner_share_link(owner_id: int, share_link_id: int) -> ShareLinkView | None:
    """Return one owner-scoped share link when available."""

    return _repo().get_share_link_for_owner(owner_id=owner_id, share_link_id=share_link_id)


def list_share_snapshots(share_link_id: int) -> Iterable[ShareSnapshotView]:
    """Return snapshots for one share link."""

    return _repo().list_share_snapshots(share_link_id=share_link_id)


def list_owner_share_accounts(owner_id: int) -> list[ShareOwnedAccountSnapshot]:
    """Return owner accounts for share management views."""

    return _repo().list_owner_accounts(owner_id)


def validate_share_account_access(*, account_id: int, owner_id: int) -> bool:
    """Return whether the share owner can access the target account."""

    return _repo().account_belongs_to_owner(owner_id=owner_id, account_id=account_id)


def increment_share_link_access_count(*, share_link_id: int) -> bool:
    """Atomically consume one allowed share-link access."""

    return _repo().increment_share_link_access_count(share_link_id=share_link_id)


def build_share_snapshot_from_account(*, share_link_id: int) -> int | None:
    """Generate a snapshot from the current simulated account state."""

    share_link = get_share_link_model(share_link_id)
    if share_link is None:
        return None

    account = _repo().get_owned_account_for_snapshot(
        owner_id=share_link.owner_id,
        account_id=share_link.account_id,
    )
    if account is None:
        return None

    positions = _repo().list_owned_account_positions_for_snapshot(
        owner_id=share_link.owner_id,
        account_id=share_link.account_id,
    )
    trades = _repo().list_owned_account_trades_for_snapshot(
        owner_id=share_link.owner_id,
        account_id=share_link.account_id,
        limit=20,
    )
    positions_by_code = {
        position.asset_code: position for position in positions if position.asset_code
    }
    asset_codes = {
        asset_code
        for asset_code in [
            *(position.asset_code for position in positions),
            *(trade.asset_code for trade in trades),
        ]
        if asset_code
    }

    total_assets = float(account.total_value or 0)
    market_value = float(account.current_market_value or 0)
    cash_value = float(account.current_cash or 0)
    current_position = round((market_value / total_assets) * 100, 2) if total_assets else 0.0
    allocation_by_type: dict[str, dict[str, Any]] = {}

    position_items: list[dict[str, Any]] = []
    for position in positions:
        asset_type = (position.asset_type or "").strip().lower() or "other"
        position_market_value = float(position.market_value or 0)
        weight = round((position_market_value / total_assets) * 100, 2) if total_assets else 0.0
        bucket = allocation_by_type.setdefault(
            asset_type,
            {
                "key": asset_type,
                "label": _asset_type_label(asset_type),
                "value": 0.0,
                "count": 0,
            },
        )
        bucket["value"] += position_market_value
        bucket["count"] += 1
        position_items.append(
            {
                "asset_code": position.asset_code,
                "asset_name": position.asset_name,
                "asset_type": asset_type,
                "asset_type_label": _asset_type_label(asset_type),
                "quantity": float(position.quantity or 0),
                "avg_cost": float(position.avg_cost or 0),
                "current_price": float(position.current_price or 0),
                "market_value": position_market_value,
                "pnl": float(position.unrealized_pnl or 0),
                "return_pct": float(position.unrealized_pnl_pct or 0),
                "weight": weight,
                "entry_reason": position.entry_reason,
                "invalidation_logic": position.invalidation_description,
            }
        )

    if cash_value > 0:
        allocation_by_type["cash"] = {
            "key": "cash",
            "label": _asset_type_label("cash"),
            "value": cash_value,
            "count": 1,
        }

    asset_allocation = [
        {
            **bucket,
            "pct": round((bucket["value"] / total_assets) * 100, 2) if total_assets else 0.0,
        }
        for bucket in sorted(
            allocation_by_type.values(),
            key=lambda item: item["value"],
            reverse=True,
        )
    ]

    transaction_items = [
        {
            "asset_code": trade.asset_code,
            "asset_name": trade.asset_name,
            "action": trade.action,
            "quantity": float(trade.quantity or 0),
            "price": float(trade.price or 0),
            "amount": float(trade.amount or 0),
            "reason": trade.reason,
            "created_at": _as_iso_datetime(trade.execution_time),
        }
        for trade in trades
    ]

    decision_items, evidence_items = _build_decision_chain(
        account.id, asset_codes, positions_by_code
    )
    if not decision_items:
        for trade in trades[:10]:
            if trade.reason:
                fallback_position = positions_by_code.get(trade.asset_code or "")
                decision_items.append(
                    {
                        "title": f"{'买入' if trade.action == 'buy' else '卖出'} {trade.asset_name or trade.asset_code}",
                        "status": "executed",
                        "get_status_display": DECISION_STATUS_DISPLAY["executed"],
                        "description": trade.reason,
                        "rationale": trade.reason,
                        "asset_code": trade.asset_code,
                        "created_at": _as_iso_datetime(trade.execution_time),
                        "execution_status": trade.status,
                        "invalidation_logic": (
                            fallback_position.invalidation_description
                            if fallback_position
                            else None
                        ),
                    }
                )

    summary_payload: dict[str, Any] = {
        "account_name": account.account_name,
        "portfolio_type": _normalize_portfolio_type(account.account_type),
        "current_position": current_position,
        "inception_date": account.start_date.isoformat() if account.start_date else None,
        "total_assets": total_assets,
        "cash_balance": cash_value,
    }
    performance_payload: dict[str, Any] = {
        "total_return": float(account.total_return or 0),
        "annualized_return": float(account.annual_return or 0),
        "max_drawdown": float(account.max_drawdown or 0),
        "sharpe_ratio": float(account.sharpe_ratio or 0),
        "win_rate": float(account.win_rate or 0),
        "return_7d": None,
        "return_30d": None,
        "benchmark_name": "沪深300",
        "chart_dates": [],
        "portfolio_values": [],
        "benchmark_values": [],
    }
    positions_payload: dict[str, Any] = {
        "items": position_items,
        "summary": {
            "total_value": market_value,
            "total_pnl": float(sum(float(position.unrealized_pnl or 0) for position in positions)),
            "cash_balance": cash_value,
            "total_assets": total_assets,
            "position_count": len(position_items),
            "asset_allocation": asset_allocation,
        },
        "position_count": len(position_items),
    }
    transactions_payload: dict[str, Any] = {
        "items": transaction_items,
        "total_trades": account.total_trades,
    }
    decision_payload: dict[str, Any] = {
        "items": decision_items,
        "evidence": evidence_items,
    }

    return ShareSnapshotUseCases().create_snapshot(
        share_link_id=share_link.id,
        summary_payload=summary_payload,
        performance_payload=performance_payload,
        positions_payload=positions_payload,
        transactions_payload=transactions_payload,
        decision_payload=decision_payload,
        source_range_start=account.start_date,
        source_range_end=timezone.now().date(),
    )


def get_live_share_snapshot(*, share_link_id: int) -> dict[str, Any] | None:
    """Best-effort refresh then return the latest share snapshot."""

    try:
        build_share_snapshot_from_account(share_link_id=share_link_id)
    except Exception:
        logger.warning("Unable to refresh share snapshot %s", share_link_id, exc_info=True)
    return ShareSnapshotUseCases().get_latest_snapshot(share_link_id)


def build_share_manage_context(
    *,
    owner_id: int,
    selected_account_id: int | None,
    edit_share_link_id: int | None,
) -> dict[str, Any]:
    """Build the share management page context."""

    accounts = list_owner_share_accounts(owner_id)
    edit_share_link = None
    resolved_selected_account_id = selected_account_id
    if edit_share_link_id:
        edit_share_link = get_owner_share_link(owner_id, edit_share_link_id)
        if edit_share_link is not None:
            resolved_selected_account_id = edit_share_link.account_id

    share_links = list(get_share_link_queryset(owner_id))
    account_name_map = _repo().get_owner_account_name_map(owner_id)
    for link in share_links:
        link.account_name = account_name_map.get(link.account_id, str(link.account_id))

    return {
        "accounts": accounts,
        "share_links": share_links,
        "selected_account_id": resolved_selected_account_id,
        "edit_share_link": edit_share_link,
    }


def get_share_disclaimer_config() -> ShareDisclaimerConfigView:
    """Return the share disclaimer config model."""

    return _repo().get_share_disclaimer_config()


def has_share_disclaimer_config() -> bool:
    """Return whether the disclaimer config record already exists."""

    return _repo().has_share_disclaimer_config()


def get_share_disclaimer_lines(portfolio_type: str) -> list[str]:
    """Return disclaimer lines, injecting simulated-account notice when needed."""

    config = get_share_disclaimer_config()
    lines = list(config.lines or [])
    if _normalize_portfolio_type(portfolio_type) == "simulated":
        lines = [
            *lines[:3],
            "本账户为模拟交易账户，非真实资金运作。",
            *lines[3:],
        ]
    return lines


def update_share_disclaimer_config(
    *,
    is_enabled: bool,
    modal_enabled: bool,
    modal_title: str,
    modal_confirm_text: str,
    lines: list[str],
) -> ShareDisclaimerConfigView:
    """Persist the share disclaimer config."""

    return _repo().update_share_disclaimer_config(
        is_enabled=is_enabled,
        modal_enabled=modal_enabled,
        modal_title=modal_title,
        modal_confirm_text=modal_confirm_text,
        lines=lines,
    )
