"""Append-only zero-origin evidence for newly created simulated accounts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models, router
from django.db.models import Q
from django.utils import timezone

from .simulated_account_trade_models import SimulatedAccountModel

_ANCHOR_SCHEMA = "simulated-account-ownership-anchor.v1"
_ZERO_ORIGIN = "zero_origin"
_ZERO_SHARES = Decimal("0.000000")
_ACTIVE_UOW: ContextVar[object | None] = ContextVar(
    "simulated_account_ownership_anchor_uow",
    default=None,
)


@dataclass(frozen=True, slots=True)
class _InsertClaim:
    """Private capability for one exact anchor insert in its creation UOW."""

    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "simulated_account_ownership_anchor_insert_claim",
    default=None,
)


@contextmanager
def _activate_ownership_anchor_uow() -> Iterator[object]:
    """Activate a private non-nestable capability for a new-account anchor."""

    if _ACTIVE_UOW.get() is not None:
        raise ValidationError("模拟账户权属锚 UOW 不允许嵌套")
    token = object()
    reset = _ACTIVE_UOW.set(token)
    try:
        yield token
    finally:
        _ACTIVE_UOW.reset(reset)


@contextmanager
def _claim_ownership_anchor_insert(
    *,
    token: object,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Claim one exact zero-origin row inside the active account-creation UOW."""

    if _ACTIVE_UOW.get() is not token:
        raise ValidationError("模拟账户权属锚插入需要私有创建 UOW")
    if _ACTIVE_CLAIM.get() is not None:
        raise ValidationError("模拟账户权属锚插入声明不允许嵌套")
    claim = _InsertClaim(
        token=token,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items())),
    )
    reset = _ACTIVE_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_CLAIM.reset(reset)


def _require_insert_claim(model: models.Model) -> None:
    """Require exactly the values and model type claimed by the UOW."""

    claim = _ACTIVE_CLAIM.get()
    actual_values = tuple(
        sorted(
            (field.attname, getattr(model, field.attname))
            for field in model._meta.concrete_fields
            if not field.primary_key
        )
    )
    if (
        claim is None
        or claim.token is not _ACTIVE_UOW.get()
        or claim.model_type is not type(model)
        or claim.expected_values != actual_values
    ):
        raise ValidationError("模拟账户零起点锚插入需要精确的账户创建声明")
    _ACTIVE_CLAIM.set(None)


def _utc_text(value: datetime) -> str:
    """Return one canonical UTC timestamp for the immutable anchor payload."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def simulated_account_ownership_anchor_sha256(
    *,
    account_id: int,
    owner_user_id: int,
    anchor_id: str,
    account_created_at: datetime,
    observed_at: datetime,
    anchor_kind: str,
    quantity: Decimal,
) -> str:
    """Seal the exact account, owner, creation clock, and zero quantity."""

    payload: dict[str, object] = {
        "schema": _ANCHOR_SCHEMA,
        "account_id": account_id,
        "owner_user_id": owner_user_id,
        "anchor_id": anchor_id,
        "account_created_at": _utc_text(account_created_at),
        "observed_at": _utc_text(observed_at),
        "anchor_kind": anchor_kind,
        "quantity": format(quantity.quantize(_ZERO_SHARES), "f"),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class SimulatedAccountOwnershipAnchorQuerySet(
    models.QuerySet["SimulatedAccountOwnershipAnchorModel"]
):
    """Reject all mutation paths except the model's validated first insert."""

    def update(self, **kwargs: Any) -> int:
        """Keep the zero-origin evidence fields immutable after insertion."""

        del kwargs
        raise ValidationError("模拟账户零起点权属锚不可通过 QuerySet.update 修改")

    def bulk_create(
        self,
        objs: Iterable[SimulatedAccountOwnershipAnchorModel],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[SimulatedAccountOwnershipAnchorModel]:
        """Require inserts to pass the account binding and digest validator."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("模拟账户零起点权属锚不可通过 bulk_create 绕过校验")

    def bulk_update(
        self,
        objs: Iterable[SimulatedAccountOwnershipAnchorModel],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        """Reject bulk mutation of append-only evidence."""

        del objs, fields, batch_size
        raise ValidationError("模拟账户零起点权属锚不可通过 bulk_update 修改")

    def delete(self) -> tuple[int, dict[str, int]]:
        """Retain account-creation evidence permanently."""

        raise ValidationError("模拟账户零起点权属锚不可删除")


SimulatedAccountOwnershipAnchorManager = models.Manager.from_queryset(
    SimulatedAccountOwnershipAnchorQuerySet
)


class SimulatedAccountOwnershipAnchorModel(models.Model):
    """One account-wide zero-position fact written with a fresh simulated account."""

    ZERO_ORIGIN = _ZERO_ORIGIN

    account = models.OneToOneField(
        SimulatedAccountModel,
        on_delete=models.PROTECT,
        related_name="ownership_anchor",
    )
    owner_user_id = models.PositiveBigIntegerField()
    anchor_id = models.CharField(max_length=192, unique=True)
    anchor_kind = models.CharField(max_length=24, choices=((_ZERO_ORIGIN, "Zero origin"),))
    quantity = models.DecimalField(max_digits=20, decimal_places=6, default=_ZERO_SHARES)
    account_created_at = models.DateTimeField()
    evidence_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(default=timezone.now)

    objects = SimulatedAccountOwnershipAnchorManager()

    class Meta:
        base_manager_name = "objects"
        db_table = "simulated_account_ownership_anchor"
        ordering = ("account_id",)
        constraints = [
            models.CheckConstraint(
                condition=Q(owner_user_id__gt=0) & Q(anchor_kind=_ZERO_ORIGIN),
                name="sim_own_anchor_identity_ck",
            ),
            models.CheckConstraint(
                condition=Q(quantity=_ZERO_SHARES),
                name="sim_own_anchor_zero_ck",
            ),
            models.CheckConstraint(
                condition=Q(evidence_sha256__regex=r"^[0-9a-f]{64}$"),
                name="sim_own_anchor_hash_ck",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Insert once after verifying its private creation claim and account seal."""

        if self.pk is not None or kwargs.get("update_fields") is not None:
            raise ValidationError("模拟账户零起点权属锚不可更新或使用预置主键")
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        invalid_identity = (
            type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.owner_user_id) is not int
            or self.owner_user_id <= 0
            or type(self.anchor_id) is not str
            or not self.anchor_id
            or self.anchor_id != self.anchor_id.strip()
            or any(character.isspace() for character in self.anchor_id)
            or self.anchor_kind != _ZERO_ORIGIN
            or type(self.quantity) is not Decimal
            or self.quantity != _ZERO_SHARES
            or not _aware(self.account_created_at)
            or not _aware(self.created_at)
            or self.account_created_at > self.created_at
        )
        if invalid_identity:
            raise ValidationError("模拟账户零起点权属锚的身份、时钟或数量无效")
        account = (
            SimulatedAccountModel._base_manager.using(using)
            .only("id", "user_id", "account_type", "created_at")
            .filter(pk=self.account_id)
            .first()
        )
        if (
            account is None
            or account.account_type != "simulated"
            or account.user_id != self.owner_user_id
            or account.created_at != self.account_created_at
        ):
            raise ValidationError("模拟账户零起点权属锚与已保存账户身份不匹配")
        expected_anchor_id = f"simulated-account-zero-origin.v1:{self.account_id}"
        if self.anchor_id != expected_anchor_id:
            raise ValidationError("模拟账户零起点权属锚标识无效")
        expected_hash = simulated_account_ownership_anchor_sha256(
            account_id=self.account_id,
            owner_user_id=self.owner_user_id,
            anchor_id=self.anchor_id,
            account_created_at=self.account_created_at,
            observed_at=self.created_at,
            anchor_kind=self.anchor_kind,
            quantity=self.quantity,
        )
        if self.evidence_sha256 != expected_hash:
            raise ValidationError("模拟账户零起点权属锚摘要不匹配")
        _require_insert_claim(self)
        _require_empty_account_history(account_id=self.account_id, using=using)
        super().save(*args, **kwargs)

    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Prevent deletion of immutable ownership evidence."""

        del using, keep_parents
        raise ValidationError("模拟账户零起点权属锚不可删除")


def _aware(value: object) -> bool:
    """Return whether a timestamp is an aware datetime."""

    if type(value) is not datetime or value.tzinfo is None:
        return False
    try:
        return value.utcoffset() is not None
    except (OverflowError, TypeError, ValueError):
        return False


def _require_empty_account_history(*, account_id: int, using: str) -> None:
    """Require a fresh account to have no economic history before its anchor."""

    from .corporate_action_posting_models import CorporateActionPostingModel
    from .order_reservation_models import SimulatedOrderReservationModel
    from .simulated_account_trade_models import PositionModel, SimulatedTradeModel

    if any(
        model_type._base_manager.using(using).filter(account_id=account_id).exists()
        for model_type in (
            PositionModel,
            SimulatedTradeModel,
            SimulatedOrderReservationModel,
            CorporateActionPostingModel,
        )
    ):
        raise ValidationError("零起点锚写入前账户已有持仓或账本历史")


__all__: tuple[str, ...] = (
    "SimulatedAccountOwnershipAnchorModel",
    "_activate_ownership_anchor_uow",
    "_claim_ownership_anchor_insert",
    "simulated_account_ownership_anchor_sha256",
)
