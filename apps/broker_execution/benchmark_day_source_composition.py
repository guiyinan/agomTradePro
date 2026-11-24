"""Read authenticated QMT balances for a specified account without certifying its unified ledger."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from django.core import signing
from django.db import connections
from django.utils import timezone

from apps.broker_execution.infrastructure.models import (
    BrokerAccountBindingModel,
    BrokerAccountSnapshotModel,
    BrokerAgentModel,
    BrokerPositionSnapshotModel,
)
from apps.broker_execution.snapshot_challenge import confirmed_sampling_lower_bound


@dataclass(frozen=True, slots=True)
class SignedPosition:
    """Exact stock quantity and marked value from a signed QMT close."""

    asset_code: str
    quantity: Decimal
    available_quantity: Decimal
    market_value: Decimal


@dataclass(frozen=True, slots=True)
class SignedBrokerBalances:
    """The exact authenticated account snapshot, including closed-world holdings."""

    account_id: int
    owner_user_id: int
    account_ref_hash: str
    snapshot_id: int
    credential_id: UUID
    agent_pk: int
    captured_at: datetime
    received_at: datetime
    max_snapshot_age_seconds: int
    currency: str
    cash_available: Decimal
    cash_frozen: Decimal
    total_asset: Decimal
    position_market_value: Decimal
    positions: tuple[SignedPosition, ...]
    content_hash: str
    signed_receipt: str
    sampling_challenge_at: datetime | None = None


def _amount(raw: object) -> Decimal:
    value = Decimal(str(raw))
    if (
        not value.is_finite()
        or value < 0
        or len(value.as_tuple().digits) > 24
        or abs(value.adjusted()) > 24
    ):
        raise ValueError("invalid broker balance")
    return value


def read_benchmark_broker_balances(
    *, snapshot_id: int, owner_user_id: int, account_id: int, using: str = "default"
) -> SignedBrokerBalances | None:
    """Read the exact signed QMT snapshot backing an independent custody reconciliation."""
    if not connections[using].in_atomic_block:
        raise RuntimeError("signed broker balances require the caller's transaction")
    binding = (
        BrokerAccountBindingModel.objects.using(using)
        .select_for_update()
        .filter(user_id=owner_user_id, account_id=account_id, is_active=True)
        .first()
    )
    if (
        binding is None
        or not binding.broker_account_ref
        or binding.broker_account_ref.casefold() == "fake"
    ):
        return None
    if (
        not BrokerAgentModel.objects.using(using)
        .select_for_update()
        .filter(pk=binding.agent_id, user_id=owner_user_id, is_active=True)
        .exists()
    ):
        return None
    snapshot = (
        BrokerAccountSnapshotModel.objects.using(using)
        .select_for_update()
        .filter(
            pk=snapshot_id, agent_id=binding.agent_id, user_id=owner_user_id, account_id=account_id
        )
        .first()
    )
    if snapshot is None or not isinstance(snapshot.payload, dict):
        return None
    evidence = snapshot.payload.get("authenticated_close")
    if not isinstance(evidence, str):
        return None
    try:
        receipt = signing.loads(evidence, salt="broker-execution.valuation-close.v1")
        original = receipt["body"]
        payload: dict[str, Any] = json.loads(original)
        close = payload["payload"]["valuation_close"]
        received = datetime.fromisoformat(receipt["received_at"])
        credential_id = UUID(receipt["credential_id"])
        positions = payload["positions"]
        sampling_challenge_at = confirmed_sampling_lower_bound(
            token=close.get("sampling_challenge"),
            agent_pk=binding.agent_id,
            account_id=account_id,
            credential_id=credential_id,
            received_at=received,
        )
        if (
            receipt["agent_pk"] != binding.agent_id
            or not receipt["request_id"]
            or not receipt["credential_id"]
            or type(payload["account_id"]) is not int
            or payload["account_id"] != account_id
            or close["source"] != "xtquant.stock"
            or close["broker_account_ref"] != binding.broker_account_ref
            or close["currency"] != "CNY"
            or close["positions_complete"] is not True
            or close["assets_complete"] is not True
            or datetime.fromisoformat(payload["captured_at"]) != snapshot.captured_at
            or not snapshot.captured_at <= received <= timezone.now()
            or not isinstance(positions, list)
        ):
            return None
        cash, frozen, value, total = (
            _amount(x)
            for x in (
                payload["cash_available"],
                close["cash_frozen"],
                close["position_market_value"],
                payload["total_asset"],
            )
        )
        if (
            cash != snapshot.cash_available
            or total != snapshot.total_asset
            or total <= 0
            or cash + frozen + value != total
        ):
            return None
        by_code: dict[str, SignedPosition] = {}
        for pos in positions:
            code = pos["asset_code"]
            if (
                not isinstance(code, str)
                or not code
                or len(code) > 32
                or code.strip().upper() != code
                or code in by_code
            ):
                return None
            item = SignedPosition(
                code,
                _amount(pos["quantity"]),
                _amount(pos["available_quantity"]),
                _amount(pos["payload"]["market_value"]),
            )
            if item.available_quantity > item.quantity or (
                item.quantity == 0 and item.market_value
            ):
                return None
            by_code[code] = item
        held = (
            BrokerPositionSnapshotModel.objects.using(using)
            .select_for_update()
            .filter(
                agent_id=binding.agent_id,
                user_id=owner_user_id,
                account_id=account_id,
                captured_at=snapshot.captured_at,
            )
            .order_by("asset_code")
        )
        exact = tuple(by_code[k] for k in sorted(by_code))
        stored = tuple(
            SignedPosition(
                r.asset_code, r.quantity, r.available_quantity, _amount(r.payload["market_value"])
            )
            for r in held
        )
        if exact != stored or sum((i.market_value for i in exact), Decimal(0)) != value:
            return None
    except (signing.BadSignature, KeyError, ValueError, TypeError, InvalidOperation, OverflowError):
        return None
    digest = hashlib.sha256(evidence.encode()).hexdigest()
    return SignedBrokerBalances(
        account_id,
        owner_user_id,
        hashlib.sha256(binding.broker_account_ref.encode()).hexdigest(),
        snapshot.pk,
        credential_id,
        binding.agent_id,
        snapshot.captured_at,
        received,
        binding.max_snapshot_age_seconds,
        close["currency"],
        cash,
        frozen,
        total,
        value,
        exact,
        digest,
        evidence,
        sampling_challenge_at,
    )
