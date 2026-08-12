"""Django persistence and exact provider for authoritative R3 runner specs."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from typing import Protocol

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.macro_factor.domain.temporal_runner_spec import MacroFactorRunnerSpec
from apps.research.application.r3_macro_factor_runner_spec import (
    ExactMacroFactorRunnerSpecDefinitionProvider,
    MacroFactorRunnerSpecConflict,
    MacroFactorRunnerSpecCorruption,
    MacroFactorRunnerSpecUnavailable,
)
from apps.research.domain.r3_macro_factor_runner_spec import (
    PersistedMacroFactorRunnerSpecRecord,
)
from apps.research.infrastructure.r3_macro_factor_runner_spec_codec import (
    R3MacroFactorRunnerSpecCodecError,
    decode_persisted_macro_factor_runner_spec,
    encode_persisted_macro_factor_runner_spec,
)
from apps.research.infrastructure.r3_macro_factor_runner_spec_models import (
    R3MacroFactorRunnerSpecModel,
    _activate_r3_macro_factor_runner_spec_uow,
    _claim_r3_macro_factor_runner_spec_insert,
    _require_active_r3_macro_factor_runner_spec_uow,
)


class R3MacroFactorRunnerSpecClock(Protocol):
    """Trusted server clock used for PIT reads and ledger writes."""

    def now(self) -> datetime:
        """Return one timezone-aware server time."""


class DjangoR3MacroFactorRunnerSpecClock:
    """Django timezone-backed trusted server clock."""

    def now(self) -> datetime:
        return timezone.now()


class DjangoR3MacroFactorRunnerSpecDefinitionProvider:
    """UoW-bound adapter around one authoritative Research owner query."""

    __slots__ = ("_source",)

    def __init__(self, source: ExactMacroFactorRunnerSpecDefinitionProvider) -> None:
        self._source = source

    @property
    def unit_of_work_key(self) -> str:
        return self._source.unit_of_work_key

    def get_exact(
        self,
        *,
        spec_id: str,
        spec_version: int,
        as_of: datetime,
    ) -> MacroFactorRunnerSpec | None:
        """Reread the owner only inside the repository transaction."""

        _require_active_r3_macro_factor_runner_spec_uow()
        return self._source.get_exact(
            spec_id=spec_id,
            spec_version=spec_version,
            as_of=as_of,
        )


class DjangoR3MacroFactorRunnerSpecRepository:
    """Read-only exact/PIT repository with live codec and header validation."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R3MacroFactorRunnerSpecClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoR3MacroFactorRunnerSpecClock()

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        spec_id: str,
        spec_version: int,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedMacroFactorRunnerSpecRecord | None:
        """Restore by redundant anchors before applying the PIT cutoff."""

        self._require_pit_cutoff(as_of)
        models = list(
            R3MacroFactorRunnerSpecModel._default_manager.using(self._using).filter(
                Q(spec_id=spec_id, spec_version=spec_version)
                | Q(spec_content_hash=expected_content_hash)
            )
        )
        if not models:
            return None
        records = tuple(self._restore(model) for model in models)
        matches = tuple(
            record
            for record in records
            if record.spec.run_key == spec_id
            and record.spec.run_version == spec_version
            and record.spec.content_hash.lower() == expected_content_hash.lower()
        )
        if len(matches) > 1:
            raise MacroFactorRunnerSpecCorruption(
                "multiple R3 runner specs match one exact identity and hash"
            )
        if not matches or matches[0].ledger_recorded_at > as_of:
            return None
        return matches[0]

    def get_by_identity(
        self,
        *,
        spec_id: str,
        spec_version: int,
    ) -> PersistedMacroFactorRunnerSpecRecord | None:
        """Restore one exact identity for the Macro Factor provider port."""

        now = self._trusted_now()
        models = list(
            R3MacroFactorRunnerSpecModel._default_manager.using(self._using).filter(
                spec_id=spec_id,
                spec_version=spec_version,
            )
        )
        if not models:
            return None
        if len(models) != 1:
            raise MacroFactorRunnerSpecCorruption(
                "multiple R3 runner specs match one exact identity"
            )
        record = self._restore(models[0])
        if record.ledger_recorded_at > now:
            raise MacroFactorRunnerSpecUnavailable(
                "R3 runner spec is not yet knowable at the server clock"
            )
        return record

    def _require_pit_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise MacroFactorRunnerSpecUnavailable("R3 runner-spec as_of must be timezone-aware")
        if as_of > self._trusted_now():
            raise MacroFactorRunnerSpecUnavailable("future R3 runner-spec as_of is not permitted")

    def _trusted_now(self) -> datetime:
        try:
            now = self._clock.now()
        except Exception as error:
            raise MacroFactorRunnerSpecUnavailable(
                "R3 runner-spec trusted clock is unavailable"
            ) from error
        if now.tzinfo is None or now.utcoffset() is None:
            raise MacroFactorRunnerSpecCorruption("R3 runner-spec server clock is naive")
        return now

    @staticmethod
    def _restore(
        model: R3MacroFactorRunnerSpecModel,
    ) -> PersistedMacroFactorRunnerSpecRecord:
        return _restore_model(model)


class DjangoMacroFactorRunnerSpecProvider:
    """Concrete exact provider implementing the Macro Factor Application port."""

    __slots__ = ("_repository",)

    def __init__(self, repository: DjangoR3MacroFactorRunnerSpecRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        return self._repository.unit_of_work_key

    def get_spec(
        self,
        *,
        spec_id: str,
        spec_version: int,
    ) -> MacroFactorRunnerSpec | None:
        """Return only one strictly restored immutable spec identity."""

        record = self._repository.get_by_identity(
            spec_id=spec_id,
            spec_version=spec_version,
        )
        return None if record is None else record.spec.validated_copy()


class _DjangoR3MacroFactorRunnerSpecStore:
    """Private append capability with an exact UoW and insert token."""

    __slots__ = ("_token", "_using")

    def __init__(self, *, using: str = "default") -> None:
        self._using = using
        self._token = object()

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with (
            transaction.atomic(using=self._using),
            _activate_r3_macro_factor_runner_spec_uow(self._token),
        ):
            yield

    def append(
        self,
        record: PersistedMacroFactorRunnerSpecRecord,
    ) -> PersistedMacroFactorRunnerSpecRecord:
        """Append one exact spec while the repository UoW is active."""

        validated = record.validated_copy()
        existing_models = list(
            R3MacroFactorRunnerSpecModel._default_manager.using(self._using).filter(
                Q(spec_id=validated.spec.run_key, spec_version=validated.spec.run_version)
                | Q(spec_content_hash=validated.spec.content_hash)
                | Q(record_hash=validated.record_hash)
            )
        )
        if len(existing_models) > 1:
            raise MacroFactorRunnerSpecCorruption(
                "multiple persisted rows collide with one R3 runner-spec append"
            )
        if existing_models:
            existing = _restore_model(existing_models[0])
            if existing == validated:
                return existing
            raise MacroFactorRunnerSpecConflict(
                "R3 runner-spec identity already sealed with different evidence"
            )
        values = _record_values(validated)
        with _claim_r3_macro_factor_runner_spec_insert(
            token=self._token,
            expected_values=values,
        ):
            R3MacroFactorRunnerSpecModel._default_manager.using(self._using).create(**values)
        return validated


def _record_values(record: PersistedMacroFactorRunnerSpecRecord) -> dict[str, object]:
    spec = record.spec
    return {
        "spec_id": spec.run_key,
        "spec_version": spec.run_version,
        "factor_version": spec.factor_version,
        "target_code": spec.target.target_code,
        "expected_manifest_content_hash": spec.expected_manifest_content_hash,
        "spec_registered_at": spec.registered_at,
        "ledger_recorded_at": record.ledger_recorded_at,
        "first_selection_at": min(fold.selection_as_of for fold in spec.plan.outer_folds),
        "last_evaluation_at": max(fold.evaluation_as_of for fold in spec.plan.outer_folds),
        "calculated_at": spec.calculated_at,
        "canonical_payload": encode_persisted_macro_factor_runner_spec(record),
        "spec_content_hash": spec.content_hash,
        "record_hash": record.record_hash,
        "research_only": record.research_only,
        "must_not_publish_current": record.must_not_publish_current,
        "must_not_use_for_decision": record.must_not_use_for_decision,
        "must_not_execute": record.must_not_execute,
    }


def _record_headers(record: PersistedMacroFactorRunnerSpecRecord) -> tuple[object, ...]:
    values = _record_values(record)
    return tuple(values[key] for key in _HEADER_NAMES)


def _model_headers(model: R3MacroFactorRunnerSpecModel) -> tuple[object, ...]:
    return tuple(getattr(model, key) for key in _HEADER_NAMES)


_HEADER_NAMES = (
    "spec_id",
    "spec_version",
    "factor_version",
    "target_code",
    "expected_manifest_content_hash",
    "spec_registered_at",
    "ledger_recorded_at",
    "first_selection_at",
    "last_evaluation_at",
    "calculated_at",
    "spec_content_hash",
    "record_hash",
    "research_only",
    "must_not_publish_current",
    "must_not_use_for_decision",
    "must_not_execute",
)


def _restore_model(
    model: R3MacroFactorRunnerSpecModel,
) -> PersistedMacroFactorRunnerSpecRecord:
    try:
        record = decode_persisted_macro_factor_runner_spec(model.canonical_payload)
    except R3MacroFactorRunnerSpecCodecError as error:
        raise MacroFactorRunnerSpecCorruption(
            "R3 runner-spec canonical payload is invalid"
        ) from error
    if _record_headers(record) != _model_headers(model):
        raise MacroFactorRunnerSpecCorruption("R3 runner-spec ledger header mismatch")
    return record


__all__ = [
    "DjangoMacroFactorRunnerSpecProvider",
    "DjangoR3MacroFactorRunnerSpecClock",
    "DjangoR3MacroFactorRunnerSpecDefinitionProvider",
    "DjangoR3MacroFactorRunnerSpecRepository",
    "R3MacroFactorRunnerSpecClock",
]
