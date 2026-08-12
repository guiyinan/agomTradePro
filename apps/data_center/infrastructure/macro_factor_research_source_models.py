"""Append-only ORM ledgers for canonical R3 macro-factor source definitions."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, TypeVar, cast

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_UOW: ContextVar[object | None] = ContextVar(
    "active_macro_factor_source_uow",
    default=None,
)


@dataclass(frozen=True, slots=True)
class _InsertClaim:
    token: object
    model_name: str
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_macro_factor_source_insert_claim",
    default=None,
)


@contextmanager
def _activate_macro_factor_source_uow(token: object) -> Iterator[None]:
    reset = _ACTIVE_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_UOW.reset(reset)


def _require_active_macro_factor_source_uow(token: object) -> None:
    if _ACTIVE_UOW.get() is not token:
        raise ValidationError("macro-factor source repository UoW is inactive")


@contextmanager
def _claim_macro_factor_source_insert(
    *,
    token: object,
    model_name: str,
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    if _ACTIVE_UOW.get() is not token:
        raise ValidationError("macro-factor source insert requires its repository UoW")
    claim = _InsertClaim(
        token=token,
        model_name=model_name,
        expected_values=tuple(sorted(expected_values.items())),
    )
    reset = _ACTIVE_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_CLAIM.reset(reset)


class MacroFactorSourceQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject mutation and all unclaimed bulk insert paths."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("macro-factor source evidence requires repository appends")

    def _update(self, values: object) -> NoReturn:
        raise ValidationError("macro-factor source evidence cannot be updated")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("macro-factor source evidence cannot be deleted")

    def _insert(
        self,
        objs: Iterable[_ModelT],
        fields: Iterable[object],
        returning_fields: Iterable[object] | None = None,
        raw: bool = False,
        using: str | None = None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> list[tuple[object, ...]]:
        items = list(objs)
        if (
            not items
            or raw
            or on_conflict is not None
            or update_fields is not None
            or unique_fields is not None
            or (using is not None and using != self.db)
        ):
            raise ValidationError("macro-factor source private insert is forbidden")
        for item in items:
            _require_insert_claim(item)
        insert = cast(
            Callable[..., list[tuple[object, ...]]],
            getattr(super(), "_insert"),  # noqa: B009 -- typed Django private boundary
        )
        return insert(
            items,
            fields,
            returning_fields=returning_fields,
            raw=False,
            using=using,
            on_conflict=None,
            update_fields=None,
            unique_fields=None,
        )

    def _batched_insert(
        self,
        objs: list[_ModelT],
        fields: list[object],
        batch_size: int | None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> NoReturn:
        raise ValidationError("macro-factor source private bulk insert is forbidden")


class MacroFactorSourceManager(AppendOnlyManager[_ModelT]):
    """Expose identical append-only guards through all managers."""

    def get_queryset(self) -> MacroFactorSourceQuerySet[_ModelT]:
        return MacroFactorSourceQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("macro-factor source evidence requires repository appends")


class MacroFactorSourceAppendOnlyModel(models.Model):
    """Base model enforcing repository-only inserts and immutable rows."""

    objects = MacroFactorSourceManager()

    class Meta:
        abstract = True

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("macro-factor source evidence is append-only")
        _require_insert_claim(self)
        super().save(force_insert=force_insert, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("macro-factor source evidence is append-only")
        _require_insert_claim(self)
        super().save_base(
            raw=False,
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError("macro-factor source evidence cannot be deleted")


class MacroFactorResearchSourceDefinitionModel(MacroFactorSourceAppendOnlyModel):
    """Canonical definition header and trusted registration receipt."""

    source_id = models.CharField(max_length=192)
    source_version = models.CharField(max_length=192)
    source_content_hash = models.CharField(max_length=64, unique=True)
    manifest_calendar_version = models.CharField(max_length=64, unique=True)
    owner = models.CharField(max_length=32, default="data_center")
    target_code = models.CharField(max_length=192, db_index=True)
    candidate_asset_codes = models.JSONField()
    calendar_id = models.CharField(max_length=192)
    calendar_version = models.CharField(max_length=192)
    calendar_content_hash = models.CharField(max_length=64)
    source_contract_id = models.CharField(max_length=192)
    source_contract_version = models.CharField(max_length=192)
    source_contract_hash = models.CharField(max_length=64)
    knowledge_scope = models.CharField(max_length=32)
    require_verified = models.BooleanField()
    minimum_coverage_ratio = models.DecimalField(max_digits=20, decimal_places=12)
    maximum_missing_count = models.PositiveIntegerField()
    maximum_estimated_count = models.PositiveIntegerField()
    maximum_unknown_count = models.PositiveIntegerField()
    registered_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    ledger_recorded_at = models.DateTimeField(db_index=True)
    canonical_payload = models.JSONField()
    record_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_publish_current = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_macro_factor_source"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["source_id", "source_version"],
                name="dc_mfsrc_identity_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(owner="data_center")
                    & models.Q(knowledge_scope="public")
                    & models.Q(registered_at__lte=models.F("ledger_recorded_at"))
                    & models.Q(ledger_recorded_at__lt=models.F("valid_until"))
                    & models.Q(minimum_coverage_ratio__gte=0)
                    & models.Q(minimum_coverage_ratio__lte=1)
                ),
                name="dc_mfsrc_sem_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    research_only=True,
                    must_not_publish_current=True,
                    must_not_use_for_decision=True,
                    must_not_execute=True,
                ),
                name="dc_mfsrc_safe_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["source_id", "source_version", "ledger_recorded_at"],
                name="dc_mfsrc_pit_idx",
            )
        ]


class MacroFactorResearchCalendarPeriodModel(MacroFactorSourceAppendOnlyModel):
    """One exact period member under a source-definition calendar."""

    source_definition = models.ForeignKey(
        MacroFactorResearchSourceDefinitionModel,
        on_delete=models.PROTECT,
        related_name="macro_factor_calendar_periods",
    )
    row_id = models.CharField(max_length=192)
    period_id = models.CharField(max_length=192)
    kind = models.CharField(max_length=32)
    observation_date = models.DateField()
    target_period_start = models.DateField()
    target_period_end = models.DateField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_macro_factor_calendar_period"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["source_definition", "row_id"],
                name="dc_mfsrc_period_row_uq",
            ),
            models.UniqueConstraint(
                fields=["source_definition", "period_id"],
                name="dc_mfsrc_period_id_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(kind__in=["historical", "inference"])
                    & models.Q(target_period_start__lte=models.F("target_period_end"))
                    & models.Q(observation_date__lte=models.F("target_period_end"))
                ),
                name="dc_mfsrc_period_sem_ck",
            ),
        ]


class MacroFactorResearchMemberRuleModel(MacroFactorSourceAppendOnlyModel):
    """One exact target/proxy fact identity and decoding rule."""

    source_definition = models.ForeignKey(
        MacroFactorResearchSourceDefinitionModel,
        on_delete=models.PROTECT,
        related_name="macro_factor_member_rules",
    )
    period = models.ForeignKey(
        MacroFactorResearchCalendarPeriodModel,
        on_delete=models.PROTECT,
        related_name="macro_factor_member_rules",
    )
    row_id = models.CharField(max_length=192)
    role = models.CharField(max_length=32)
    member_code = models.CharField(max_length=192)
    dataset_key = models.CharField(max_length=64, db_index=True)
    business_key = models.CharField(max_length=255, db_index=True)
    value_field = models.CharField(max_length=192)
    unit_field = models.CharField(max_length=192)
    expected_unit = models.CharField(max_length=192)
    value_encoding = models.CharField(max_length=32)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64)
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_macro_factor_member_rule"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["source_definition", "row_id", "role", "member_code"],
                name="dc_mfsrc_member_sem_uq",
            ),
            models.UniqueConstraint(
                fields=["source_definition", "dataset_key", "business_key"],
                name="dc_mfsrc_member_fact_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(role__in=["target", "proxy"])
                    & models.Q(value_encoding__in=["decimal_text.v1", "json_number.v1"])
                ),
                name="dc_mfsrc_member_sem_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["source_definition", "row_id"],
                name="dc_mfsrc_member_row_idx",
            )
        ]


def _require_insert_claim(model: models.Model) -> None:
    claim = _ACTIVE_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_UOW.get()
        or claim.model_name != model._meta.label_lower
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("macro-factor source evidence requires an exact insert claim")


@receiver(pre_delete, sender=MacroFactorResearchSourceDefinitionModel, weak=False)
@receiver(pre_delete, sender=MacroFactorResearchCalendarPeriodModel, weak=False)
@receiver(pre_delete, sender=MacroFactorResearchMemberRuleModel, weak=False)
def _reject_macro_factor_source_collector_delete(
    *,
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object | None,
    **kwargs: object,
) -> NoReturn:
    """Reject collector, cascade, and related-manager deletion paths."""

    raise ValidationError("macro-factor source evidence cannot be deleted")


__all__ = [
    "MacroFactorResearchCalendarPeriodModel",
    "MacroFactorResearchMemberRuleModel",
    "MacroFactorResearchSourceDefinitionModel",
]
