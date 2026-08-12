"""Exact PIT repository for the independent Research R8 monitoring policy."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.fixed_income.domain.evidence import canonical_hash
from apps.portfolio.domain.governed_optimization_monitoring import (
    GovernedOptimizationMonitoringPolicy,
)
from apps.research.application.r8_monitoring_policy_registry import (
    R8MonitoringPolicyRegistryClock,
)
from apps.research.domain.r8_monitoring_policy_registry import (
    R8MonitoringPolicyDefinition,
    R8MonitoringPolicySourceReceipt,
)
from apps.research.infrastructure.r5_relative_value_monitoring_models import (
    _activate_r5_monitoring_uow,
    _claim_r5_monitoring_insert,
)
from apps.research.infrastructure.r8_monitoring_policy_codec import (
    R8MonitoringPolicyCodecError,
    decode_r8_monitoring_policy_definition,
    decode_r8_monitoring_policy_source_receipt,
    encode_r8_monitoring_policy_definition,
    encode_r8_monitoring_policy_source_receipt,
)
from apps.research.infrastructure.r8_monitoring_policy_models import (
    R8MonitoringPolicyRegistryModel,
)


class R8MonitoringPolicyRepositoryConflict(RuntimeError):
    """A stable Research policy identity already has another winner."""


class R8MonitoringPolicyRepositoryCorruption(RuntimeError):
    """A persisted policy header or strict payload was substituted."""


class DjangoR8MonitoringPolicyClock:
    """Trusted Django clock bound to one database alias identity."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared Research transaction identity."""

        return f"django:{self._using}"

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""

        return timezone.now()


class DjangoR8MonitoringPolicyRepository:
    """Public exact PIT policy provider with no write token."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the database alias identity used by Phase A."""

        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_policy_hash: str,
        as_of: datetime,
    ) -> GovernedOptimizationMonitoringPolicy | None:
        """Return one exact dedicated policy known and active at the cutoff."""

        _query(policy_id, policy_version, expected_policy_hash, as_of)
        rows = tuple(
            R8MonitoringPolicyRegistryModel._default_manager.using(self._using)
            .filter(ledger_recorded_at__lte=as_of)
            .filter(
                Q(policy_id=policy_id, policy_version=policy_version)
                | Q(policy_hash=expected_policy_hash)
            )
        )
        if not rows:
            return None
        restored = tuple(_owner_graph_from_model(item)[0].policy for item in rows)
        matches = tuple(
            item
            for item in restored
            if item.policy_id == policy_id
            and item.policy_version == policy_version
            and item.content_hash == expected_policy_hash
            and item.recorded_at <= as_of < item.valid_until
        )
        if len(rows) != 1 or len(matches) != 1:
            raise R8MonitoringPolicyRepositoryCorruption(
                "R8 monitoring policy identity is aliased or substituted"
            )
        return matches[0]


class _DjangoR8MonitoringPolicyStore(DjangoR8MonitoringPolicyRepository):
    """Private exact-append capability for owner registration tests."""

    __slots__ = ("_clock", "_token")

    def __init__(
        self,
        *,
        token: object,
        using: str,
        clock: R8MonitoringPolicyRegistryClock,
    ) -> None:
        super().__init__(using=using)
        self._token = token
        self._clock = clock

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one transaction and activate the private exact-insert claim."""

        with transaction.atomic(using=self._using), _activate_r5_monitoring_uow(self._token):
            yield

    def append(
        self,
        *,
        definition: R8MonitoringPolicyDefinition,
        source: R8MonitoringPolicySourceReceipt,
        ledger_recorded_at: datetime,
    ) -> GovernedOptimizationMonitoringPolicy:
        """Append or replay one exact independent policy winner."""

        if type(definition) is not R8MonitoringPolicyDefinition:
            raise TypeError("R8 monitoring policy definition type differs")
        if type(source) is not R8MonitoringPolicySourceReceipt:
            raise TypeError("R8 monitoring policy source type differs")
        exact_definition = R8MonitoringPolicyDefinition.validated_copy(definition)
        exact_source = R8MonitoringPolicySourceReceipt.validated_copy(source)
        _validate_append(exact_definition, exact_source, ledger_recorded_at)
        rows = self._collisions(exact_definition, exact_source)
        if rows:
            return _match_winner(rows, exact_definition, exact_source)
        values = _model_values(exact_definition, exact_source, ledger_recorded_at)
        model = R8MonitoringPolicyRegistryModel(**values)
        try:
            model.full_clean()
            with transaction.atomic(using=self._using):
                with _claim_r5_monitoring_insert(
                    token=self._token,
                    model_type=R8MonitoringPolicyRegistryModel,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError) as error:
            rows = self._collisions(exact_definition, exact_source)
            if not rows:
                raise R8MonitoringPolicyRepositoryConflict(
                    "R8 monitoring policy append has no exact winner"
                ) from error
            return _match_winner(rows, exact_definition, exact_source)
        return _owner_graph_from_model(model)[0].policy

    def _collisions(
        self,
        definition: R8MonitoringPolicyDefinition,
        source: R8MonitoringPolicySourceReceipt,
    ) -> tuple[R8MonitoringPolicyRegistryModel, ...]:
        policy = definition.policy
        return tuple(
            R8MonitoringPolicyRegistryModel._default_manager.using(self._using).filter(
                Q(policy_id=policy.policy_id, policy_version=policy.policy_version)
                | Q(policy_hash=policy.content_hash)
                | Q(definition_hash=definition.content_hash)
                | Q(
                    source_receipt_id=source.source_receipt_id,
                    source_receipt_version=source.source_receipt_version,
                )
                | Q(source_receipt_hash=source.content_hash)
            )
        )


def _build_r8_monitoring_policy_store(
    *,
    using: str = "default",
    clock: R8MonitoringPolicyRegistryClock | None = None,
) -> _DjangoR8MonitoringPolicyStore:
    """Build the private policy store without exporting its token."""

    trusted_clock = clock or DjangoR8MonitoringPolicyClock(using=using)
    return _DjangoR8MonitoringPolicyStore(
        token=object(),
        using=using,
        clock=trusted_clock,
    )


def _match_winner(
    rows: tuple[R8MonitoringPolicyRegistryModel, ...],
    definition: R8MonitoringPolicyDefinition,
    source: R8MonitoringPolicySourceReceipt,
) -> GovernedOptimizationMonitoringPolicy:
    if len(rows) != 1:
        raise R8MonitoringPolicyRepositoryConflict(
            "R8 monitoring policy has multiple collision candidates"
        )
    restored_definition, restored_source = _owner_graph_from_model(rows[0])
    if restored_definition != definition or restored_source != source:
        raise R8MonitoringPolicyRepositoryConflict(
            "R8 monitoring policy identity forks to different evidence"
        )
    return restored_definition.policy


def _validate_append(
    definition: R8MonitoringPolicyDefinition,
    source: R8MonitoringPolicySourceReceipt,
    ledger_recorded_at: datetime,
) -> None:
    _aware(ledger_recorded_at, "R8 monitoring policy ledger_recorded_at")
    policy = definition.policy
    if not (
        source.policy_id == policy.policy_id
        and source.policy_version == policy.policy_version
        and source.definition_hash == definition.content_hash
        and source.available_at <= ledger_recorded_at < source.valid_until
        and policy.recorded_at <= ledger_recorded_at < policy.valid_until
        and source.valid_until >= policy.valid_until
    ):
        raise R8MonitoringPolicyRepositoryConflict(
            "R8 monitoring policy owner graph or clocks differ"
        )


def _owner_graph_from_model(
    model: R8MonitoringPolicyRegistryModel,
) -> tuple[R8MonitoringPolicyDefinition, R8MonitoringPolicySourceReceipt]:
    try:
        definition = decode_r8_monitoring_policy_definition(model.definition_payload)
        source = decode_r8_monitoring_policy_source_receipt(model.source_payload)
    except (R8MonitoringPolicyCodecError, TypeError, ValueError) as error:
        raise R8MonitoringPolicyRepositoryCorruption(
            "R8 monitoring policy payload cannot be restored"
        ) from error
    values = _model_values(definition, source, model.ledger_recorded_at)
    if any(getattr(model, key) != expected for key, expected in values.items()):
        raise R8MonitoringPolicyRepositoryCorruption(
            "R8 monitoring policy headers differ from strict payloads"
        )
    return definition, source


def _model_values(
    definition: R8MonitoringPolicyDefinition,
    source: R8MonitoringPolicySourceReceipt,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    policy = definition.policy
    target = policy.target
    values: dict[str, object] = {
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "policy_hash": policy.content_hash,
        "definition_version": definition.definition_version,
        "definition_hash": definition.content_hash,
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "source_receipt_hash": source.content_hash,
        "target_result_id": target.result_id,
        "target_result_hash": target.result_hash,
        "target_receipt_id": target.receipt_id,
        "target_receipt_hash": target.receipt_hash,
        "calendar_id": policy.calendar_id,
        "calendar_version": policy.calendar_version,
        "calendar_hash": policy.calendar_hash,
        "source_available_at": source.available_at,
        "source_valid_until": source.valid_until,
        "policy_recorded_at": policy.recorded_at,
        "policy_valid_until": policy.valid_until,
        "ledger_recorded_at": ledger_recorded_at,
        "definition_payload": encode_r8_monitoring_policy_definition(definition),
        "source_payload": encode_r8_monitoring_policy_source_receipt(source),
        "research_only": True,
        "must_not_publish_current": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
    }
    values["ledger_header_hash"] = _header_hash(values)
    return values


def _header_hash(values: dict[str, object]) -> str:
    return canonical_hash(
        {
            "schema": "research-r8-monitoring-policy-ledger-header.v1",
            "values": {
                key: value
                for key, value in values.items()
                if key not in {"definition_payload", "source_payload"}
            },
        }
    )


def _query(
    policy_id: object,
    policy_version: object,
    expected_policy_hash: object,
    as_of: datetime,
) -> None:
    _token(policy_id, "R8 monitoring policy query policy_id")
    _token(policy_version, "R8 monitoring policy query policy_version")
    _hash(expected_policy_hash, "R8 monitoring policy query hash")
    _aware(as_of, "R8 monitoring policy query as_of")


def _token(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a non-empty exact string")
    return value


def _hash(value: object, label: str) -> str:
    text = _token(value, label)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _aware(value: datetime, label: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be an exact timezone-aware datetime")


__all__ = [
    "DjangoR8MonitoringPolicyRepository",
    "R8MonitoringPolicyRepositoryConflict",
    "R8MonitoringPolicyRepositoryCorruption",
]
