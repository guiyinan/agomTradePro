from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.core import signing

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.infrastructure.order_history_repository import (
    _CURSOR_SALT,
    _cursor_state,
    _encode_cursor,
)

_READ_AT = datetime(2026, 10, 29, 8, 15, tzinfo=UTC)
_CUTOFF = _READ_AT - timedelta(minutes=1)


def _cursor(
    *,
    kind: str = "orders",
    user_id: int = 42,
    account_id: int = 31,
    order_id: int | None = None,
    last_pk: int = 12,
    cutoff: datetime = _CUTOFF,
) -> str:
    """Build a signed cursor for one exact owner scope."""

    return _encode_cursor(
        kind=kind,
        user_id=user_id,
        account_id=account_id,
        order_id=order_id,
        last_pk=last_pk,
        membership_cutoff=cutoff,
    )


def test_signed_orders_cursor_round_trips_membership_cutoff_and_last_id() -> None:
    state = _cursor_state(
        cursor=_cursor(),
        kind="orders",
        user_id=42,
        account_id=31,
        order_id=None,
        read_at=_READ_AT,
    )

    assert state.last_pk == 12
    assert state.membership_cutoff == _CUTOFF


@pytest.mark.parametrize(
    ("kind", "user_id", "account_id", "order_id"),
    [
        ("fills", 42, 31, None),
        ("orders", 43, 31, None),
        ("orders", 42, 32, None),
        ("fills", 42, 31, 12),
    ],
)
def test_signed_cursor_cannot_be_replayed_for_another_route_or_owner_scope(
    kind: str,
    user_id: int,
    account_id: int,
    order_id: int | None,
) -> None:
    with pytest.raises(SimulatedTradeExecutionInputError):
        _cursor_state(
            cursor=_cursor(),
            kind=kind,
            user_id=user_id,
            account_id=account_id,
            order_id=order_id,
            read_at=_READ_AT,
        )


def test_signed_fill_cursor_is_bound_to_exact_public_order_number() -> None:
    token = _cursor(kind="fills", order_id=71)

    state = _cursor_state(
        cursor=token,
        kind="fills",
        user_id=42,
        account_id=31,
        order_id=71,
        read_at=_READ_AT,
    )

    assert state.last_pk == 12
    with pytest.raises(SimulatedTradeExecutionInputError):
        _cursor_state(
            cursor=token,
            kind="fills",
            user_id=42,
            account_id=31,
            order_id=72,
            read_at=_READ_AT,
        )


def test_tampered_cursor_and_future_membership_cutoff_are_rejected() -> None:
    token = _cursor()
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    with pytest.raises(SimulatedTradeExecutionInputError):
        _cursor_state(
            cursor=tampered,
            kind="orders",
            user_id=42,
            account_id=31,
            order_id=None,
            read_at=_READ_AT,
        )

    future = _cursor(cutoff=_READ_AT + timedelta(seconds=1))
    with pytest.raises(SimulatedTradeExecutionInputError):
        _cursor_state(
            cursor=future,
            kind="orders",
            user_id=42,
            account_id=31,
            order_id=None,
            read_at=_READ_AT,
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "version": 1,
            "kind": "orders",
            "user_id": True,
            "account_id": 31,
            "order_id": None,
            "last_pk": 12,
            "membership_cutoff": _CUTOFF.isoformat(),
        },
        {
            "version": 1,
            "kind": "orders",
            "user_id": 42,
            "account_id": 31,
            "order_id": None,
            "last_pk": 12,
            "membership_cutoff": _CUTOFF.replace(tzinfo=None).isoformat(),
        },
        {
            "version": 1,
            "kind": "orders",
            "user_id": 42,
            "account_id": 31,
            "order_id": None,
            "last_pk": 12,
            "membership_cutoff": _CUTOFF.isoformat(),
            "extra": "reject",
        },
    ],
)
def test_signed_payload_still_requires_exact_json_shape_and_types(
    payload: dict[str, object],
) -> None:
    token = signing.dumps(payload, salt=_CURSOR_SALT, compress=False)

    with pytest.raises(SimulatedTradeExecutionInputError):
        _cursor_state(
            cursor=token,
            kind="orders",
            user_id=42,
            account_id=31,
            order_id=None,
            read_at=_READ_AT,
        )
