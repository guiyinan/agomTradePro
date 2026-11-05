"""Typed public boundary for explicitly requested simulated rebalance journeys."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

from core.exceptions import AuthorizationError, BusinessLogicError, InvalidInputError

JourneyAction = Literal[
    "list", "create", "read", "review", "successor", "reconcile", "preview_order"
]


class RebalanceJourneyUnavailable(BusinessLogicError):
    """The configured journey service cannot supply verified plan information."""

    default_code = "REBALANCE_JOURNEY_UNAVAILABLE"
    default_message = "当前无法读取已验证的调仓计划，请稍后重试。"
    default_status_code = 503


class RebalanceJourneyAccessDenied(AuthorizationError):
    """The actor lacks the requested account or plan capability."""

    default_code = "REBALANCE_JOURNEY_ACCESS_DENIED"
    default_message = "当前账户不允许此项调仓操作。"


@dataclass(frozen=True, slots=True)
class RebalanceJourneyCommand:
    """Accept account, user intent and exact pins, never client financial facts."""

    action: JourneyAction
    user_id: int
    account_id: int
    plan_id: str | None = None
    plan_version: int | None = None
    revision_hash: str | None = None
    request_key: str | None = None
    target_weights: str | None = None
    reference_price_basis: Literal["market", "published_close"] = "market"
    order_ordinal: int | None = None
    order_content_hash: str | None = None
    plan_order_binding_id: str | None = None
    quantity: Decimal | None = None
    limit_price: Decimal | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        """Reject ambiguous identities and missing exact-version write bindings."""

        if any(type(value) is not int or value <= 0 for value in (self.user_id, self.account_id)):
            raise RebalanceJourneyAccessDenied()
        if self.action not in {
            "list",
            "create",
            "read",
            "review",
            "successor",
            "reconcile",
            "preview_order",
        }:
            raise InvalidInputError(code="REBALANCE_JOURNEY_ACTION_INVALID")
        if self.reference_price_basis not in {"market", "published_close"}:
            raise InvalidInputError(code="REBALANCE_JOURNEY_PRICE_BASIS_INVALID")
        if self.action not in {"list", "create"}:
            _token(self.plan_id, "REBALANCE_JOURNEY_PLAN_REQUIRED", 64)
            if type(self.plan_version) is not int or self.plan_version <= 0:
                raise InvalidInputError(code="REBALANCE_JOURNEY_VERSION_REQUIRED")
            if (
                type(self.revision_hash) is not str
                or len(self.revision_hash) != 64
                or any(c not in "0123456789abcdef" for c in self.revision_hash)
            ):
                raise InvalidInputError(code="REBALANCE_JOURNEY_HASH_REQUIRED")
        elif any(
            value is not None for value in (self.plan_id, self.plan_version, self.revision_hash)
        ):
            raise InvalidInputError(code="REBALANCE_JOURNEY_UNEXPECTED_PLAN_PINS")
        if self.action in {"create", "review", "successor", "preview_order"}:
            _token(self.request_key, "REBALANCE_JOURNEY_REQUEST_KEY_REQUIRED", 128)
        elif self.request_key is not None:
            raise InvalidInputError(code="REBALANCE_JOURNEY_UNEXPECTED_REQUEST_KEY")
        if self.action == "create" and (
            type(self.target_weights) is not str or not self.target_weights.strip()
        ):
            raise InvalidInputError(code="REBALANCE_JOURNEY_TARGET_REQUIRED")
        if self.target_weights is not None and (
            self.action not in {"create", "successor"} or type(self.target_weights) is not str
        ):
            raise InvalidInputError(code="REBALANCE_JOURNEY_UNEXPECTED_TARGET")
        order_values = (
            self.order_ordinal,
            self.order_content_hash,
            self.plan_order_binding_id,
            self.quantity,
            self.limit_price,
            self.reason,
        )
        if self.action == "preview_order":
            if type(self.order_ordinal) is not int or self.order_ordinal < 0:
                raise InvalidInputError(code="REBALANCE_JOURNEY_ORDER_REQUIRED")
            for digest in (self.order_content_hash, self.plan_order_binding_id):
                if (
                    type(digest) is not str
                    or len(digest) != 64
                    or any(c not in "0123456789abcdef" for c in digest)
                ):
                    raise InvalidInputError(code="REBALANCE_JOURNEY_ORDER_HASH_REQUIRED")
            for value in (self.quantity, self.limit_price):
                if type(value) is not Decimal or not value.is_finite() or value <= 0:
                    raise InvalidInputError(code="REBALANCE_JOURNEY_ORDER_INTENT_INVALID")
            if self.reason is not None and type(self.reason) is not str:
                raise InvalidInputError(code="REBALANCE_JOURNEY_REASON_INVALID")
        elif any(value is not None for value in order_values):
            raise InvalidInputError(code="REBALANCE_JOURNEY_UNEXPECTED_ORDER_FIELDS")


class RebalanceJourneyService(Protocol):
    """Compose verified plan, account, review and settlement owner services."""

    def execute(self, command: RebalanceJourneyCommand) -> dict[str, object]:
        """Return a JSON boundary payload after rechecking account scope."""
        ...


_service_factory: Callable[[str], RebalanceJourneyService] | None = None


def configure_rebalance_journey_service(
    factory: Callable[[str], RebalanceJourneyService],
) -> None:
    """Register a lazy composition factory without reading or changing an account."""

    global _service_factory
    _service_factory = factory


def run_rebalance_journey(
    command: RebalanceJourneyCommand, *, using: str = "default"
) -> dict[str, object]:
    """Run only the explicit user action through the configured owner boundary."""

    if type(command) is not RebalanceJourneyCommand:
        raise InvalidInputError(code="REBALANCE_JOURNEY_COMMAND_INVALID")
    command.__post_init__()
    if _service_factory is None:
        raise RebalanceJourneyUnavailable()
    return _service_factory(using).execute(command)


def _token(value: str | None, code: str, maximum: int) -> None:
    if type(value) is not str or not value or value.strip() != value or len(value) > maximum:
        raise InvalidInputError(code=code)
