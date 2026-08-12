"""Exact PIT repository for canonical R6 scope-to-qualification bindings."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.fixed_income.domain.evidence import canonical_hash
from apps.research.application.r6_scope_qualification_registry import (
    R6ScopeQualificationRegistryClock,
)
from apps.research.domain.r6_scope_qualification_registry import (
    R6ScopeQualificationBindingDefinition,
    R6ScopeQualificationSourceReceipt,
)
from apps.research.domain.state_model_activation import (
    R6ActivationScope,
    validate_r6_activation_scope,
)
from apps.research.domain.state_model_qualification_lifecycle import (
    R6QualificationRef,
)
from apps.research.infrastructure.r6_scope_qualification_codec import (
    R6ScopeQualificationCodecError,
    decode_r6_scope_qualification_definition,
    decode_r6_scope_qualification_source,
    encode_r6_scope_qualification_definition,
    encode_r6_scope_qualification_source,
)
from apps.research.infrastructure.r6_scope_qualification_models import (
    R6ScopeQualificationRegistryModel,
    _activate_r6_scope_binding_uow,
    _claim_r6_scope_binding_insert,
)


class R6ScopeQualificationRepositoryConflict(RuntimeError):
    """A stable binding identity already has another exact winner."""


class R6ScopeQualificationRepositoryCorruption(RuntimeError):
    """A persisted binding header or strict payload was substituted."""


class DjangoR6ScopeQualificationClock:
    """Trusted Django clock bound to one database alias."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        _using(using)
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared Research transaction identity."""

        return f"django:{self._using}"

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""

        return timezone.now()


class DjangoR6ScopeQualificationRegistryRepository:
    """Public scope and qualification-ref queries with no write token."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        _using(using)
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the database alias identity used by the preflight."""

        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        scope_id: str,
        as_of: datetime,
    ) -> R6ActivationScope | None:
        """Return the unique latest active owner-defined scope at a PIT cutoff."""

        _token(scope_id, "R6 binding query scope_id")
        _aware(as_of, "R6 binding query as_of")
        winner = self._latest_for_scope(scope_id=scope_id, as_of=as_of)
        return None if winner is None else winner.scope

    def get_latest_active_ref(
        self,
        *,
        scope: R6ActivationScope,
        as_of: datetime,
    ) -> R6QualificationRef | None:
        """Return the exact qualification ref for the server-selected scope."""

        if type(scope) is not R6ActivationScope:
            raise TypeError("R6 binding query scope type differs")
        validate_r6_activation_scope(scope)
        _aware(as_of, "R6 binding query as_of")
        winner = self._latest_for_scope(scope_id=scope.scope_id, as_of=as_of)
        if winner is None:
            return None
        if winner.scope != scope:
            raise R6ScopeQualificationRepositoryCorruption(
                "R6 binding scope changed between exact reads"
            )
        return R6QualificationRef(
            winner.qualification_ref.assessment_id,
            winner.qualification_ref.assessment_hash,
        )

    def get_exact_binding(
        self,
        *,
        binding_id: str,
        binding_version: str,
        expected_definition_hash: str,
        as_of: datetime,
    ) -> R6ScopeQualificationBindingDefinition | None:
        """Return one hash-bound binding known and active at the cutoff."""

        _token(binding_id, "R6 binding query binding_id")
        _token(binding_version, "R6 binding query binding_version")
        _hash(expected_definition_hash, "R6 binding query definition hash")
        _aware(as_of, "R6 binding query as_of")
        rows = tuple(
            R6ScopeQualificationRegistryModel._default_manager.using(self._using)
            .filter(ledger_recorded_at__lte=as_of)
            .filter(
                Q(binding_id=binding_id, binding_version=binding_version)
                | Q(definition_hash=expected_definition_hash)
            )
        )
        if not rows:
            return None
        graphs = tuple(_owner_graph_from_model(item) for item in rows)
        matches = tuple(
            definition
            for definition, source in graphs
            if definition.binding_id == binding_id
            and definition.binding_version == binding_version
            and definition.content_hash == expected_definition_hash
            and definition.effective_at <= as_of < definition.valid_until
            and source.available_at <= as_of < source.valid_until
        )
        if len(rows) != 1 or len(matches) != 1:
            raise R6ScopeQualificationRepositoryCorruption(
                "R6 binding exact identity is aliased or substituted"
            )
        return matches[0]

    def _latest_for_scope(
        self,
        *,
        scope_id: str,
        as_of: datetime,
    ) -> R6ScopeQualificationBindingDefinition | None:
        rows = tuple(
            R6ScopeQualificationRegistryModel._default_manager.using(self._using).filter(
                scope_id=scope_id,
                ledger_recorded_at__lte=as_of,
                effective_at__lte=as_of,
                definition_valid_until__gt=as_of,
                source_available_at__lte=as_of,
                source_valid_until__gt=as_of,
            )
        )
        if not rows:
            return None
        graphs = tuple(_owner_graph_from_model(item) for item in rows)
        candidates = tuple(
            definition
            for definition, source in graphs
            if definition.scope.scope_id == scope_id
            and definition.effective_at <= as_of < definition.valid_until
            and source.available_at <= as_of < source.valid_until
        )
        if not candidates:
            raise R6ScopeQualificationRepositoryCorruption(
                "R6 binding PIT headers differ from payload windows"
            )
        latest_effective_at = max(item.effective_at for item in candidates)
        winners = tuple(item for item in candidates if item.effective_at == latest_effective_at)
        if len(winners) != 1:
            raise R6ScopeQualificationRepositoryCorruption(
                "R6 binding latest PIT rank has multiple winners"
            )
        return winners[0]


class _DjangoR6ScopeQualificationStore(DjangoR6ScopeQualificationRegistryRepository):
    """Private exact append capability for owner registration tests."""

    __slots__ = ("_clock", "_token")

    def __init__(
        self,
        *,
        token: object,
        using: str,
        clock: R6ScopeQualificationRegistryClock,
    ) -> None:
        super().__init__(using=using)
        self._token = token
        self._clock = clock

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Open one transaction and activate the exact-insert capability."""

        with transaction.atomic(using=self._using), _activate_r6_scope_binding_uow(self._token):
            yield

    def append(
        self,
        *,
        definition: R6ScopeQualificationBindingDefinition,
        source: R6ScopeQualificationSourceReceipt,
        ledger_recorded_at: datetime,
    ) -> R6ScopeQualificationBindingDefinition:
        """Append or replay one exact owner graph winner."""

        exact_definition = R6ScopeQualificationBindingDefinition.validated_copy(definition)
        exact_source = R6ScopeQualificationSourceReceipt.validated_copy(source)
        _validate_append(exact_definition, exact_source, ledger_recorded_at)
        rows = self._collisions(exact_definition, exact_source)
        if rows:
            return _match_winner(rows, exact_definition, exact_source)
        values = _model_values(exact_definition, exact_source, ledger_recorded_at)
        model = R6ScopeQualificationRegistryModel(**values)
        try:
            model.full_clean()
            with transaction.atomic(using=self._using):
                with _claim_r6_scope_binding_insert(
                    token=self._token,
                    expected_values=values,
                ):
                    model.save(force_insert=True, using=self._using)
        except (IntegrityError, ValidationError) as error:
            rows = self._collisions(exact_definition, exact_source)
            if not rows:
                raise R6ScopeQualificationRepositoryConflict(
                    "R6 binding append has no exact winner"
                ) from error
            return _match_winner(rows, exact_definition, exact_source)
        restored_definition, restored_source = _owner_graph_from_model(model)
        if restored_definition != exact_definition or restored_source != exact_source:
            raise R6ScopeQualificationRepositoryConflict(
                "R6 binding append did not round-trip exactly"
            )
        return restored_definition

    def _collisions(
        self,
        definition: R6ScopeQualificationBindingDefinition,
        source: R6ScopeQualificationSourceReceipt,
    ) -> tuple[R6ScopeQualificationRegistryModel, ...]:
        scope = definition.scope
        return tuple(
            R6ScopeQualificationRegistryModel._default_manager.using(self._using).filter(
                Q(
                    binding_id=definition.binding_id,
                    binding_version=definition.binding_version,
                )
                | Q(definition_hash=definition.content_hash)
                | Q(scope_id=scope.scope_id, scope_version=scope.scope_version)
                | Q(scope_hash=scope.content_hash)
                | Q(
                    source_receipt_id=source.source_receipt_id,
                    source_receipt_version=source.source_receipt_version,
                )
                | Q(source_receipt_hash=source.content_hash)
            )
        )


def _build_r6_scope_qualification_store(
    *,
    using: str = "default",
    clock: R6ScopeQualificationRegistryClock | None = None,
) -> _DjangoR6ScopeQualificationStore:
    """Build the private store without exporting its capability token."""

    trusted_clock = clock or DjangoR6ScopeQualificationClock(using=using)
    return _DjangoR6ScopeQualificationStore(
        token=object(),
        using=using,
        clock=trusted_clock,
    )


def _match_winner(
    rows: tuple[R6ScopeQualificationRegistryModel, ...],
    definition: R6ScopeQualificationBindingDefinition,
    source: R6ScopeQualificationSourceReceipt,
) -> R6ScopeQualificationBindingDefinition:
    if len(rows) != 1:
        raise R6ScopeQualificationRepositoryConflict("R6 binding has multiple collision candidates")
    restored_definition, restored_source = _owner_graph_from_model(rows[0])
    if restored_definition != definition or restored_source != source:
        raise R6ScopeQualificationRepositoryConflict(
            "R6 binding identity forks to different evidence"
        )
    return restored_definition


def _validate_append(
    definition: R6ScopeQualificationBindingDefinition,
    source: R6ScopeQualificationSourceReceipt,
    ledger_recorded_at: datetime,
) -> None:
    _aware(ledger_recorded_at, "R6 binding ledger_recorded_at")
    if not (
        source.binding_id == definition.binding_id
        and source.binding_version == definition.binding_version
        and source.definition_hash == definition.content_hash
        and definition.effective_at <= ledger_recorded_at < definition.valid_until
        and source.available_at <= ledger_recorded_at < source.valid_until
        and source.valid_until >= definition.valid_until
    ):
        raise R6ScopeQualificationRepositoryConflict("R6 binding owner graph or clocks differ")


def _owner_graph_from_model(
    model: R6ScopeQualificationRegistryModel,
) -> tuple[
    R6ScopeQualificationBindingDefinition,
    R6ScopeQualificationSourceReceipt,
]:
    try:
        definition = decode_r6_scope_qualification_definition(model.definition_payload)
        source = decode_r6_scope_qualification_source(model.source_payload)
    except (R6ScopeQualificationCodecError, TypeError, ValueError) as error:
        raise R6ScopeQualificationRepositoryCorruption(
            "R6 binding payload cannot be restored"
        ) from error
    values = _model_values(definition, source, model.ledger_recorded_at)
    if any(getattr(model, key) != expected for key, expected in values.items()):
        raise R6ScopeQualificationRepositoryCorruption(
            "R6 binding headers differ from strict payloads"
        )
    return definition, source


def _model_values(
    definition: R6ScopeQualificationBindingDefinition,
    source: R6ScopeQualificationSourceReceipt,
    ledger_recorded_at: datetime,
) -> dict[str, object]:
    scope = definition.scope
    qualification_ref = definition.qualification_ref
    values: dict[str, object] = {
        "binding_id": definition.binding_id,
        "binding_version": definition.binding_version,
        "definition_version": definition.definition_version,
        "definition_hash": definition.content_hash,
        "scope_id": scope.scope_id,
        "scope_version": scope.scope_version,
        "scope_hash": scope.content_hash,
        "qualification_id": qualification_ref.assessment_id,
        "qualification_hash": qualification_ref.assessment_hash,
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "source_receipt_hash": source.content_hash,
        "effective_at": definition.effective_at,
        "definition_valid_until": definition.valid_until,
        "source_available_at": source.available_at,
        "source_valid_until": source.valid_until,
        "ledger_recorded_at": ledger_recorded_at,
        "definition_payload": encode_r6_scope_qualification_definition(definition),
        "source_payload": encode_r6_scope_qualification_source(source),
        "research_only": True,
        "must_not_publish_current": True,
        "must_not_use_for_decision": True,
        "must_not_replace_regime": True,
        "must_not_execute": True,
    }
    values["ledger_header_hash"] = canonical_hash(
        {
            "schema": "research-r6-scope-qualification-ledger-header.v1",
            "values": {
                key: value
                for key, value in values.items()
                if key not in {"definition_payload", "source_payload"}
            },
        }
    )
    return values


def _using(value: object) -> str:
    return _token(value, "R6 binding database alias")


def _token(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a non-empty exact string")
    return value


def _hash(value: object, label: str) -> str:
    text = _token(value, label)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _aware(value: object, label: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be an exact timezone-aware datetime")


__all__ = [
    "DjangoR6ScopeQualificationClock",
    "DjangoR6ScopeQualificationRegistryRepository",
    "R6ScopeQualificationRepositoryConflict",
    "R6ScopeQualificationRepositoryCorruption",
]
