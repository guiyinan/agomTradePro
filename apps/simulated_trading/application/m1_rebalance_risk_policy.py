"""Owner publication orchestration and source mapping for M1 risk revisions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol, cast

from apps.risk_center.application.m1_rebalance_risk_policy import (
    M1RiskPolicyApplication,
    M1RiskPolicyIdempotencyContext,
    M1RiskPolicyOperation,
    M1RiskPolicyPublishCommand,
    M1RiskPolicyRevision,
    M1RiskSourceSnapshot,
)
from apps.risk_center.domain.m1_rebalance_risk_policy import (
    AccountType,
    M1RiskCondition,
    RiskSourceLimitField,
)
from apps.strategy.application.execution_gateway import InspectionSelection


class M1RiskPolicyOwnerDenied(PermissionError):
    """The authenticated user does not own the requested active simulated account."""


class M1RiskPolicyAccountSourceReader(Protocol):
    """Read an account's real owner and current legacy risk columns."""

    def read_owner_source(self, *, account_id: int) -> M1RiskPolicyAccountSource | None:
        """Return exact source facts or None when the account row cannot be read."""
        ...


class StrategyM1RiskSourceReader(Protocol):
    """Public Strategy Application query used to bind the selected source content."""

    def get_owner_inspection_selection(
        self,
        account_id: int,
        owner_user_id: int,
        strategy_id: int | None = None,
    ) -> InspectionSelection:
        """Return current rule content only when its strategy belongs to this owner."""
        ...


@dataclass(frozen=True, slots=True)
class M1RiskPolicyAccountSource:
    """Owner and exact legacy risk values read from the simulated-account row."""

    account_id: int
    owner_user_id: int | None
    account_type: str
    is_active: bool
    max_single_position_pct: Decimal | None
    max_total_position_pct: Decimal | None
    stop_loss_pct: Decimal | None
    invalid_limit_fields: tuple[RiskSourceLimitField, ...] = ()

    def __post_init__(self) -> None:
        """Reject invalid persisted identity and leave nullable limits untouched."""

        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be an exact positive integer")
        if self.owner_user_id is not None and (
            type(self.owner_user_id) is not int or self.owner_user_id <= 0
        ):
            raise ValueError("owner_user_id must be a positive integer or None")
        if self.account_type not in {"simulated", "real"}:
            raise ValueError("account_type is unsupported")
        if type(self.is_active) is not bool:
            raise TypeError("is_active must be an exact bool")
        for value in (
            self.max_single_position_pct,
            self.max_total_position_pct,
            self.stop_loss_pct,
        ):
            if value is not None and (
                type(value) is not Decimal
                or not value.is_finite()
                or value < Decimal("0")
                or value > Decimal("100")
            ):
                raise ValueError("account limits must be finite Decimal percentages or None")
        allowed_fields = {
            "max_single_position_pct",
            "max_total_position_pct",
            "stop_loss_pct",
        }
        if type(self.invalid_limit_fields) is not tuple or any(
            type(field_name) is not str or field_name not in allowed_fields
            for field_name in self.invalid_limit_fields
        ):
            raise ValueError("invalid_limit_fields must contain supported exact field names")
        if len(self.invalid_limit_fields) != len(set(self.invalid_limit_fields)):
            raise ValueError("invalid_limit_fields cannot contain duplicates")


@dataclass(frozen=True, slots=True)
class OwnerM1RiskPolicyPublishRequest:
    """Validated explicit owner fields accepted by the publication use case."""

    strategy_id: int | None
    effective_from: datetime
    effective_until: datetime
    reason: str
    max_single_position: M1RiskCondition
    max_total_position: M1RiskCondition
    max_stop_loss: M1RiskCondition


class PublishOwnerM1RiskPolicyRevisionUseCase:
    """Authorize account ownership, bind live sources, and publish a new M1 policy."""

    def __init__(
        self,
        *,
        account_source_reader: M1RiskPolicyAccountSourceReader,
        strategy_source_reader: StrategyM1RiskSourceReader,
        risk_policy_application: M1RiskPolicyApplication,
    ) -> None:
        """Inject own-app source readers and the public RiskCenter Application."""

        self._account_source_reader = account_source_reader
        self._strategy_source_reader = strategy_source_reader
        self._risk_policy_application = risk_policy_application

    def execute(
        self,
        *,
        account_id: int,
        authenticated_actor_id: int,
        request: OwnerM1RiskPolicyPublishRequest,
        idempotency: M1RiskPolicyIdempotencyContext,
    ) -> M1RiskPolicyRevision:
        """Publish only when the real request actor owns the current account row."""

        if type(authenticated_actor_id) is not int or authenticated_actor_id <= 0:
            raise M1RiskPolicyOwnerDenied("A real authenticated owner is required.")
        account_source = self._account_source_reader.read_owner_source(account_id=account_id)
        if (
            account_source is None
            or account_source.account_type != "simulated"
            or account_source.is_active is not True
            or account_source.owner_user_id != authenticated_actor_id
        ):
            raise M1RiskPolicyOwnerDenied("Only the active simulated-account owner may publish.")
        if request.strategy_id is not None and (
            type(request.strategy_id) is not int or request.strategy_id <= 0
        ):
            raise M1RiskPolicyOwnerDenied("The selected Strategy identity is invalid.")
        strategy_selection = self._strategy_source_reader.get_owner_inspection_selection(
            account_id,
            authenticated_actor_id,
            request.strategy_id,
        )
        source_snapshot = build_m1_risk_source_snapshot(
            account_source=account_source,
            strategy_selection=strategy_selection,
        )
        command = M1RiskPolicyPublishCommand(
            account_id=account_id,
            actor_user_id=authenticated_actor_id,
            effective_from=request.effective_from,
            effective_until=request.effective_until,
            reason=request.reason,
            max_single_position=request.max_single_position,
            max_total_position=request.max_total_position,
            max_stop_loss=request.max_stop_loss,
            source_snapshot=source_snapshot,
        )
        return self._risk_policy_application.publish.execute(
            command=command,
            idempotency=idempotency,
        )


@dataclass(frozen=True, slots=True)
class OwnerM1RiskPolicyRevokeRequest:
    """Owner-supplied reason required for append-only policy revocation."""

    reason: str


class RevokeOwnerM1RiskPolicyRevisionUseCase:
    """Verify the current account owner and append a real revocation audit event."""

    def __init__(
        self,
        *,
        account_source_reader: M1RiskPolicyAccountSourceReader,
        risk_policy_application: M1RiskPolicyApplication,
    ) -> None:
        """Inject the live owner source and public RiskCenter revoke operation."""

        self._account_source_reader = account_source_reader
        self._risk_policy_application = risk_policy_application

    def execute(
        self,
        *,
        account_id: int,
        risk_policy_version: str,
        authenticated_actor_id: int,
        request: OwnerM1RiskPolicyRevokeRequest,
        idempotency: M1RiskPolicyIdempotencyContext,
    ) -> M1RiskPolicyRevision:
        """Append revocation only when the authenticated request is the real owner."""

        if type(authenticated_actor_id) is not int or authenticated_actor_id <= 0:
            raise M1RiskPolicyOwnerDenied("A real authenticated owner is required.")
        account_source = self._account_source_reader.read_owner_source(account_id=account_id)
        if (
            account_source is None
            or account_source.account_type != "simulated"
            or account_source.owner_user_id != authenticated_actor_id
        ):
            raise M1RiskPolicyOwnerDenied("Only the account owner may revoke this policy.")
        return self._risk_policy_application.revoke.execute(
            account_id=account_id,
            risk_policy_version=risk_policy_version,
            actor_user_id=authenticated_actor_id,
            reason=request.reason,
            idempotency=idempotency,
        )


def build_m1_risk_policy_idempotency_context(
    *,
    account_id: int,
    actor_user_id: int,
    operation: M1RiskPolicyOperation,
    idempotency_key: str,
    request_payload: Mapping[str, object],
    resource_id: str | None = None,
) -> M1RiskPolicyIdempotencyContext:
    """Hash a canonical JSON request under its real owner/account/operation scope."""

    if type(account_id) is not int or account_id <= 0:
        raise ValueError("idempotency account_id must be a positive integer")
    if type(actor_user_id) is not int or actor_user_id <= 0:
        raise ValueError("idempotency actor_user_id must be a positive integer")
    if type(operation) is not str or operation not in {"publish", "revoke"}:
        raise ValueError("idempotency operation is unsupported")
    if (
        type(idempotency_key) is not str
        or not idempotency_key
        or len(idempotency_key) > 192
        or any(character.isspace() for character in idempotency_key)
    ):
        raise ValueError("Idempotency-Key must be non-empty, bounded, and whitespace-free")
    if type(request_payload) is not dict or any(type(key) is not str for key in request_payload):
        raise ValueError("idempotency payload must be an exact JSON object")
    if resource_id is not None and (type(resource_id) is not str or not resource_id):
        raise ValueError("idempotency resource_id must be a non-empty string or None")
    try:
        canonical_body = json.dumps(
            {"resource_id": resource_id, "request_payload": request_payload},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        canonical_scope = json.dumps(
            ["m1-risk-policy-request.v1", operation, account_id, actor_user_id, idempotency_key],
            separators=(",", ":"),
            ensure_ascii=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("idempotency payload is not canonical JSON") from error
    return M1RiskPolicyIdempotencyContext(
        account_id=account_id,
        actor_user_id=actor_user_id,
        operation=operation,
        identity_sha256=hashlib.sha256(canonical_scope.encode("utf-8")).hexdigest(),
        request_sha256=hashlib.sha256(canonical_body.encode("utf-8")).hexdigest(),
    )


def build_m1_risk_source_snapshot(
    *,
    account_source: M1RiskPolicyAccountSource,
    strategy_selection: InspectionSelection,
) -> M1RiskSourceSnapshot:
    """Map exact live values into the shared RiskCenter snapshot contract."""

    state = strategy_selection.validated_selection_state
    account_type: AccountType = (
        cast(AccountType, account_source.account_type)
        if account_source.account_type in {"simulated", "real"}
        else "unknown"
    )
    return M1RiskSourceSnapshot(
        account_id=account_source.account_id,
        account_owner_user_id=account_source.owner_user_id,
        account_type=account_type,
        account_is_active=account_source.is_active,
        account_max_single_position_pct=account_source.max_single_position_pct,
        account_max_total_position_pct=account_source.max_total_position_pct,
        account_stop_loss_pct=account_source.stop_loss_pct,
        strategy_selection_state=state,
        strategy_id=(strategy_selection.strategy_id if state == "configured" else None),
        strategy_version=(strategy_selection.strategy_version if state == "configured" else None),
        strategy_max_single_position_pct=(
            _percentage_decimal(strategy_selection.max_position_pct)
            if state == "configured"
            else None
        ),
        strategy_max_total_position_pct=(
            _percentage_decimal(strategy_selection.max_total_position_pct)
            if state == "configured"
            else None
        ),
        strategy_stop_loss_pct=(
            _percentage_decimal(strategy_selection.stop_loss_pct) if state == "configured" else None
        ),
        position_rule_id=(strategy_selection.position_rule_id if state == "configured" else None),
        position_rule_source_json=(
            strategy_selection.position_rule_source_json if state == "configured" else None
        ),
        account_invalid_limit_fields=account_source.invalid_limit_fields,
        strategy_invalid_limit_fields=tuple(
            cast(RiskSourceLimitField, field_name)
            for field_name in strategy_selection.risk_source_invalid_fields
        ),
    )


def unknown_m1_risk_source_snapshot(*, account_id: int) -> M1RiskSourceSnapshot:
    """Represent an unavailable live source without filling any risk values."""

    return M1RiskSourceSnapshot(
        account_id=account_id,
        account_owner_user_id=None,
        account_type="unknown",
        account_is_active=None,
        account_max_single_position_pct=None,
        account_max_total_position_pct=None,
        account_stop_loss_pct=None,
        strategy_selection_state="unavailable",
        strategy_id=None,
        strategy_version=None,
        strategy_max_single_position_pct=None,
        strategy_max_total_position_pct=None,
        strategy_stop_loss_pct=None,
        position_rule_id=None,
        position_rule_source_json=None,
    )


def _percentage_decimal(value: float | int | None) -> Decimal | None:
    """Convert a stored Strategy percentage without defaulting or float math."""

    if value is None:
        return None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not decimal_value.is_finite() or not Decimal("0") <= decimal_value <= Decimal("100"):
        return None
    return decimal_value


__all__: tuple[str, ...] = (
    "M1RiskPolicyAccountSource",
    "M1RiskPolicyAccountSourceReader",
    "M1RiskPolicyOwnerDenied",
    "OwnerM1RiskPolicyPublishRequest",
    "OwnerM1RiskPolicyRevokeRequest",
    "PublishOwnerM1RiskPolicyRevisionUseCase",
    "RevokeOwnerM1RiskPolicyRevisionUseCase",
    "StrategyM1RiskSourceReader",
    "build_m1_risk_source_snapshot",
    "build_m1_risk_policy_idempotency_context",
    "unknown_m1_risk_source_snapshot",
)
