"""Append-only models for policy-benchmark methodology bundle activation."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from django.db.models.signals import pre_delete

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_BENCHMARK_METHODOLOGY_ACTIVATION_UOW: ContextVar[object | None] = ContextVar(
    "active_portfolio_benchmark_methodology_activation_uow", default=None
)


@dataclass(frozen=True)
class _InsertClaim:
    token: object
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_BENCHMARK_METHODOLOGY_ACTIVATION_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "active_portfolio_benchmark_methodology_activation_claim", default=None
)


@contextmanager
def _activate_benchmark_methodology_activation_uow(token: object) -> Iterator[None]:
    """Activate this ledger's private unit-of-work token."""

    reset = _ACTIVE_BENCHMARK_METHODOLOGY_ACTIVATION_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_BENCHMARK_METHODOLOGY_ACTIVATION_UOW.reset(reset)


@contextmanager
def _claim_benchmark_methodology_activation_insert(
    *, token: object, model_type: type[models.Model], expected_values: Mapping[str, object]
) -> Iterator[None]:
    """Claim one exact repository-controlled insert."""

    if _ACTIVE_BENCHMARK_METHODOLOGY_ACTIVATION_UOW.get() is not token:
        raise ValidationError("Benchmark methodology activation insert requires its private UOW.")
    reset = _ACTIVE_BENCHMARK_METHODOLOGY_ACTIVATION_CLAIM.set(
        _InsertClaim(token, model_type, tuple(sorted(expected_values.items())))
    )
    try:
        yield
    finally:
        _ACTIVE_BENCHMARK_METHODOLOGY_ACTIVATION_CLAIM.reset(reset)


class BenchmarkMethodologyActivationQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject every bulk insertion, mutation, and raw deletion shortcut."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Benchmark methodology activations require exact repository appends.")

    def _update(self, values: list[tuple[object, object, object]]) -> NoReturn:
        raise ValidationError("Benchmark methodology activations cannot be updated.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("Benchmark methodology activations cannot be deleted.")


class BenchmarkMethodologyActivationManager(AppendOnlyManager[_ModelT]):
    """Expose strict append-only guards through every manager path."""

    def get_queryset(self) -> BenchmarkMethodologyActivationQuerySet[_ModelT]:
        return BenchmarkMethodologyActivationQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("Benchmark methodology activations require exact repository appends.")


class BenchmarkMethodologyActivationAppendOnlyModel(models.Model):
    """Permit only exact inserts claimed by this ledger's repository."""

    objects = BenchmarkMethodologyActivationManager()

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Permit only one exact repository-claimed insert."""

        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("Benchmark methodology activations are append-only.")
        self._require_claim()
        super().save(force_insert=force_insert, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Reject raw fixture and update bypasses."""

        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("Benchmark methodology activations are append-only.")
        self._require_claim()
        super().save_base(force_insert=force_insert, using=using)

    def _require_claim(self) -> None:
        claim = _ACTIVE_BENCHMARK_METHODOLOGY_ACTIVATION_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_BENCHMARK_METHODOLOGY_ACTIVATION_UOW.get()
            or claim.model_type is not type(self)
            or any(getattr(self, name) != expected for name, expected in claim.expected_values)
        ):
            raise ValidationError(
                "Benchmark methodology activation requires an exact insert claim."
            )

    def delete(
        self, using: object | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion."""

        raise ValidationError("Benchmark methodology activations cannot be deleted.")


class PortfolioPolicyBenchmarkMethodologyActivationSubjectModel(
    BenchmarkMethodologyActivationAppendOnlyModel
):
    """One immutable definition-and-five-source activation request."""

    subject_id = models.CharField(max_length=192)
    subject_version = models.CharField(max_length=192)
    subject_identity_hash = models.CharField(max_length=64, unique=True)
    definition_id = models.CharField(max_length=192)
    definition_version = models.CharField(max_length=192)
    definition_identity_hash = models.CharField(max_length=64)
    definition_content_hash = models.CharField(max_length=64)
    definition_recorded_at = models.DateTimeField()
    definition_valid_until = models.DateTimeField()
    methodology_count = models.PositiveSmallIntegerField()
    methodology_refs_hash = models.CharField(max_length=64)
    methodology_bundle_hash = models.CharField(max_length=64)
    corporate_action_ref_hash = models.CharField(max_length=64)
    cost_tax_ref_hash = models.CharField(max_length=64)
    fx_fixing_ref_hash = models.CharField(max_length=64)
    price_fixing_ref_hash = models.CharField(max_length=64)
    trading_calendar_ref_hash = models.CharField(max_length=64)
    requested_actor_id = models.CharField(max_length=192)
    requested_actor_user_id = models.PositiveBigIntegerField()
    requested_actor_role = models.CharField(max_length=192)
    requested_actor_kind = models.CharField(max_length=16)
    requested_actor_is_staff = models.BooleanField()
    requested_actor_authentication_source = models.CharField(max_length=16)
    requested_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    supersedes_activation_hash = models.CharField(max_length=64, null=True)
    clock_source = models.CharField(max_length=16)
    recorded_at = models.DateTimeField(db_index=True)
    persisted_at = models.DateTimeField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)

    class Meta(BenchmarkMethodologyActivationAppendOnlyModel.Meta):
        db_table = "portfolio_policy_benchmark_method_activation_subject"
        indexes = [
            models.Index(
                fields=("definition_id", "requested_at"),
                name="port_bench_meth_sub_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("subject_id", "subject_version"),
                name="port_bench_meth_sub_id_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(methodology_count=5)
                    & models.Q(requested_at=models.F("recorded_at"))
                    & models.Q(persisted_at=models.F("recorded_at"))
                    & models.Q(definition_valid_until=models.F("valid_until"))
                    & models.Q(definition_recorded_at__lte=models.F("requested_at"))
                    & models.Q(requested_at__lt=models.F("valid_until"))
                    & models.Q(requested_actor_kind="human")
                    & models.Q(requested_actor_is_staff=True)
                    & models.Q(requested_actor_authentication_source="server")
                    & models.Q(clock_source="server")
                ),
                name="port_bench_meth_sub_seal_ck",
            ),
        ]


class PortfolioPolicyBenchmarkMethodologyActivationModel(
    BenchmarkMethodologyActivationAppendOnlyModel
):
    """One immutable configuration-only methodology bundle activation."""

    subject_record = models.OneToOneField(
        PortfolioPolicyBenchmarkMethodologyActivationSubjectModel,
        on_delete=models.PROTECT,
        related_name="activation_record",
    )
    owner = models.CharField(max_length=32)
    capability = models.CharField(max_length=96)
    artifact_type = models.CharField(max_length=96)
    schema = models.CharField(max_length=128)
    permission = models.CharField(max_length=64)
    clock_source = models.CharField(max_length=16)
    activation_id = models.CharField(max_length=192)
    activation_version = models.CharField(max_length=192)
    activation_identity_hash = models.CharField(max_length=64, unique=True)
    subject_id = models.CharField(max_length=192)
    subject_version = models.CharField(max_length=192)
    subject_content_hash = models.CharField(max_length=64, unique=True)
    definition_id = models.CharField(max_length=192)
    definition_version = models.CharField(max_length=192)
    definition_identity_hash = models.CharField(max_length=64)
    definition_content_hash = models.CharField(max_length=64)
    methodology_refs_hash = models.CharField(max_length=64)
    methodology_bundle_hash = models.CharField(max_length=64)
    requested_actor_id = models.CharField(max_length=192)
    requested_actor_user_id = models.PositiveBigIntegerField()
    requested_actor_role = models.CharField(max_length=192)
    requested_actor_kind = models.CharField(max_length=16)
    requested_actor_is_staff = models.BooleanField()
    requested_actor_authentication_source = models.CharField(max_length=16)
    approved_actor_id = models.CharField(max_length=192)
    approved_actor_user_id = models.PositiveBigIntegerField()
    approved_actor_role = models.CharField(max_length=192)
    approved_actor_kind = models.CharField(max_length=16)
    approved_actor_is_staff = models.BooleanField()
    approved_actor_authentication_source = models.CharField(max_length=16)
    issued_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    predecessor_hash = models.CharField(max_length=64, null=True, unique=True)
    recorded_at = models.DateTimeField(db_index=True)
    persisted_at = models.DateTimeField()
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    ledger_header_hash = models.CharField(max_length=64, unique=True)

    class Meta(BenchmarkMethodologyActivationAppendOnlyModel.Meta):
        db_table = "portfolio_policy_benchmark_method_activation"
        indexes = [
            models.Index(
                fields=("definition_id", "issued_at"),
                name="port_bench_meth_act_pit_ix",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("activation_id", "activation_version"),
                name="port_bench_meth_act_id_uq",
            ),
            models.UniqueConstraint(
                fields=("definition_id",),
                condition=models.Q(predecessor_hash__isnull=True),
                name="port_bench_meth_act_root_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(owner="portfolio")
                    & models.Q(capability="policy_benchmark_methodology_bundle_activation")
                    & models.Q(artifact_type="policy_benchmark_methodology_bundle_activation")
                    & models.Q(schema="portfolio-policy-benchmark-methodology-bundle-activation.v1")
                    & models.Q(permission="benchmark_configuration_only")
                    & models.Q(clock_source="server")
                    & models.Q(issued_at=models.F("recorded_at"))
                    & models.Q(persisted_at=models.F("recorded_at"))
                    & models.Q(issued_at__lt=models.F("valid_until"))
                    & models.Q(requested_actor_kind="human")
                    & models.Q(requested_actor_is_staff=True)
                    & models.Q(requested_actor_authentication_source="server")
                    & models.Q(approved_actor_kind="human")
                    & models.Q(approved_actor_is_staff=True)
                    & models.Q(approved_actor_authentication_source="server")
                ),
                name="port_bench_meth_act_seal_ck",
            ),
            models.CheckConstraint(
                condition=~models.Q(approved_actor_id=models.F("requested_actor_id")),
                name="port_bench_meth_actor_sep_ck",
            ),
            models.CheckConstraint(
                condition=~models.Q(approved_actor_user_id=models.F("requested_actor_user_id")),
                name="port_bench_meth_user_sep_ck",
            ),
        ]


def _reject_benchmark_methodology_activation_delete(
    sender: type[models.Model],
    instance: models.Model,
    using: str,
    origin: object,
    **kwargs: object,
) -> None:
    """Reject collector, cascade, and protected-parent deletion paths."""

    del sender, instance, using, origin, kwargs
    raise ValidationError("Benchmark methodology activations cannot be deleted.")


for _model in (
    PortfolioPolicyBenchmarkMethodologyActivationSubjectModel,
    PortfolioPolicyBenchmarkMethodologyActivationModel,
):
    pre_delete.connect(
        _reject_benchmark_methodology_activation_delete,
        sender=_model,
        dispatch_uid=f"reject_{_model._meta.db_table}_delete",
        weak=False,
    )


__all__ = [
    "PortfolioPolicyBenchmarkMethodologyActivationModel",
    "PortfolioPolicyBenchmarkMethodologyActivationSubjectModel",
]
