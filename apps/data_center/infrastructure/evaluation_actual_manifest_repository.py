"""Django persistence for Data Center-owned evaluation actual evidence."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.data_center.application.evaluation_actual_manifest import (
    EvaluationActualClock,
    EvaluationActualConflict,
    EvaluationActualCorruption,
    EvaluationActualUnavailable,
    ExactEvaluationActualGraphProvider,
    ExactEvaluationActualSourceDefinitionProvider,
)
from apps.data_center.domain.evaluation_actual_manifest import (
    CanonicalEvaluationActualGraph,
    EvaluationActualSourceDefinition,
    MaterializedEvaluationActualManifest,
    PersistedEvaluationActualSourceDefinition,
)
from apps.data_center.infrastructure.evaluation_actual_manifest_codec import (
    EvaluationActualCodecError,
    decode_materialized_evaluation_actual_manifest,
    decode_persisted_evaluation_actual_source_definition,
    encode_materialized_evaluation_actual_manifest,
    encode_persisted_evaluation_actual_source_definition,
)
from apps.data_center.infrastructure.evaluation_actual_manifest_models import (
    EvaluationActualManifestReceiptModel,
    EvaluationActualSourceDefinitionModel,
    _activate_evaluation_actual_uow,
    _claim_evaluation_actual_insert,
    _require_active_evaluation_actual_uow,
)


class DjangoEvaluationActualClock:
    """Django timezone-backed trusted clock."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity."""

        return f"django:{self._using}"

    def now(self) -> datetime:
        """Return the timezone-aware server time."""

        return timezone.now()


class DjangoEvaluationActualSourceDefinitionProvider:
    """UoW-bound adapter around an authoritative definition owner."""

    __slots__ = ("_source",)

    def __init__(self, source: ExactEvaluationActualSourceDefinitionProvider) -> None:
        self._source = source

    @property
    def unit_of_work_key(self) -> str:
        """Return the wrapped owner transaction identity."""

        return self._source.unit_of_work_key

    def get_exact(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> EvaluationActualSourceDefinition | None:
        """Read the owner only inside the repository UoW."""

        _require_active_evaluation_actual_uow()
        return self._source.get_exact(
            source_id=source_id,
            source_version=source_version,
            as_of=as_of,
        )


class DjangoEvaluationActualGraphProvider:
    """UoW-bound adapter around canonical exact fact/member reads."""

    __slots__ = ("_source",)

    def __init__(self, source: ExactEvaluationActualGraphProvider) -> None:
        self._source = source

    @property
    def unit_of_work_key(self) -> str:
        """Return the wrapped owner transaction identity."""

        return self._source.unit_of_work_key

    def get_exact(
        self,
        *,
        definition: EvaluationActualSourceDefinition,
        as_of: datetime,
    ) -> CanonicalEvaluationActualGraph | None:
        """Read canonical facts only inside the repository UoW."""

        _require_active_evaluation_actual_uow()
        return self._source.get_exact(definition=definition, as_of=as_of)


class DjangoEvaluationActualRepository:
    """Read-only exact/PIT repository with live codec and header checks."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: EvaluationActualClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoEvaluationActualClock(using=using)

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity."""

        return f"django:{self._using}"

    def get_source_definition(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> PersistedEvaluationActualSourceDefinition | None:
        """Return one exact live definition valid and knowable at ``as_of``."""

        self._require_pit_cutoff(as_of)
        rows = list(
            EvaluationActualSourceDefinitionModel._default_manager.using(self._using).filter(
                source_id=source_id, source_version=source_version
            )
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise EvaluationActualCorruption(
                "multiple evaluation actual source definitions match one identity"
            )
        record = _restore_source_model(rows[0])
        if not (
            record.ledger_recorded_at <= as_of
            and record.definition.registered_at <= as_of < record.definition.valid_until
        ):
            return None
        return record

    def get_manifest(
        self,
        *,
        manifest_id: str,
        manifest_version: str,
        as_of: datetime,
    ) -> MaterializedEvaluationActualManifest | None:
        """Return one exact receipt only after its production knowledge time."""

        self._require_pit_cutoff(as_of)
        rows = list(
            EvaluationActualManifestReceiptModel._default_manager.using(self._using)
            .select_related("source_definition")
            .filter(manifest_id=manifest_id, manifest_version=manifest_version)
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise EvaluationActualCorruption(
                "multiple evaluation actual manifests match one identity"
            )
        manifest = _restore_manifest_model(rows[0])
        if manifest.produced_at > as_of:
            return None
        return manifest

    def _require_pit_cutoff(self, as_of: datetime) -> None:
        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise EvaluationActualUnavailable("evaluation actual as_of must be timezone-aware")
        if as_of > self._trusted_now():
            raise EvaluationActualUnavailable("future evaluation actual as_of is forbidden")

    def _trusted_now(self) -> datetime:
        try:
            now = self._clock.now()
        except Exception as error:
            raise EvaluationActualUnavailable(
                "evaluation actual trusted clock is unavailable"
            ) from error
        if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
            raise EvaluationActualCorruption("evaluation actual trusted clock is naive")
        return now


class _DjangoEvaluationActualStore:
    """Private append store with an exact transaction and insert token."""

    __slots__ = ("_token", "_using")

    def __init__(self, *, using: str = "default") -> None:
        self._using = using
        self._token = object()

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Open the repository transaction and owner-query claim."""

        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with (
            transaction.atomic(using=self._using),
            _activate_evaluation_actual_uow(self._token),
        ):
            yield

    def append_source_definition(
        self,
        record: PersistedEvaluationActualSourceDefinition,
    ) -> PersistedEvaluationActualSourceDefinition:
        """Append a definition or return the exact idempotent winner."""

        validated = record.validated_copy()
        rows = list(
            EvaluationActualSourceDefinitionModel._default_manager.using(self._using).filter(
                Q(
                    source_id=validated.definition.source_id,
                    source_version=validated.definition.source_version,
                )
                | Q(source_content_hash=validated.definition.source_content_hash)
                | Q(record_hash=validated.record_hash)
            )
        )
        if len(rows) > 1:
            raise EvaluationActualCorruption(
                "multiple source rows collide with one definition append"
            )
        if rows:
            winner = _restore_source_model(rows[0])
            if winner == validated:
                return winner
            raise EvaluationActualConflict(
                "evaluation actual source identity already has another winner"
            )
        values = _source_values(validated)
        with _claim_evaluation_actual_insert(
            token=self._token,
            model_name=EvaluationActualSourceDefinitionModel._meta.label_lower,
            expected_values=values,
        ):
            EvaluationActualSourceDefinitionModel._default_manager.using(self._using).create(
                **values
            )
        return validated

    def append_manifest(
        self,
        manifest: MaterializedEvaluationActualManifest,
    ) -> MaterializedEvaluationActualManifest:
        """Append a materialization or return the exact idempotent winner."""

        validated = manifest.validated_copy()
        source_rows = list(
            EvaluationActualSourceDefinitionModel._default_manager.using(self._using).filter(
                source_id=validated.source_definition.stable_id,
                source_version=validated.source_definition.version,
            )
        )
        if len(source_rows) != 1:
            raise EvaluationActualUnavailable(
                "registered evaluation actual source definition is unavailable"
            )
        source_record = _restore_source_model(source_rows[0])
        if source_record.definition.identity != validated.source_definition:
            raise EvaluationActualCorruption(
                "materialized manifest source definition was substituted"
            )
        rows = list(
            EvaluationActualManifestReceiptModel._default_manager.using(self._using)
            .select_related("source_definition")
            .filter(
                Q(
                    manifest_id=validated.manifest_id,
                    manifest_version=validated.manifest_version,
                )
                | Q(manifest_content_hash=validated.manifest_content_hash)
                | Q(receipt_hash=validated.receipt_hash)
            )
        )
        if len(rows) > 1:
            raise EvaluationActualCorruption(
                "multiple receipt rows collide with one manifest append"
            )
        if rows:
            winner = _restore_manifest_model(rows[0])
            if winner == validated:
                return winner
            raise EvaluationActualConflict(
                "evaluation actual manifest identity already has another winner"
            )
        values = _manifest_values(validated, source_rows[0].pk)
        with _claim_evaluation_actual_insert(
            token=self._token,
            model_name=EvaluationActualManifestReceiptModel._meta.label_lower,
            expected_values=values,
        ):
            EvaluationActualManifestReceiptModel._default_manager.using(self._using).create(
                **values
            )
        return validated


def _source_values(
    record: PersistedEvaluationActualSourceDefinition,
) -> dict[str, object]:
    definition = record.definition
    policy = definition.coverage_policy
    return {
        "source_id": definition.source_id,
        "source_version": definition.source_version,
        "source_content_hash": definition.source_content_hash,
        "owner": definition.owner,
        "dataset": definition.dataset,
        "subject_code": definition.subject_code,
        "industry_code": definition.industry_code,
        "calendar_id": definition.calendar.stable_id,
        "calendar_version": definition.calendar.version,
        "calendar_content_hash": definition.calendar.content_hash,
        "knowledge_scope": definition.knowledge_scope,
        "require_verified": policy.require_verified,
        "minimum_coverage_ratio": policy.minimum_coverage_ratio,
        "maximum_missing_count": policy.maximum_missing_count,
        "maximum_estimated_count": policy.maximum_estimated_count,
        "maximum_unknown_count": policy.maximum_unknown_count,
        "registered_at": definition.registered_at,
        "valid_until": definition.valid_until,
        "ledger_recorded_at": record.ledger_recorded_at,
        "canonical_payload": encode_persisted_evaluation_actual_source_definition(record),
        "record_hash": record.record_hash,
        "research_only": definition.research_only,
        "must_not_publish_current": definition.must_not_publish_current,
        "must_not_use_for_decision": definition.must_not_use_for_decision,
        "must_not_execute": definition.must_not_execute,
    }


def _manifest_values(
    manifest: MaterializedEvaluationActualManifest,
    source_definition_pk: object,
) -> dict[str, object]:
    return {
        "source_definition_id": source_definition_pk,
        "manifest_id": manifest.manifest_id,
        "manifest_version": manifest.manifest_version,
        "manifest_content_hash": manifest.manifest_content_hash,
        "owner": manifest.owner,
        "dataset": manifest.dataset,
        "subject_code": manifest.subject_code,
        "industry_code": manifest.industry_code,
        "as_of_time": manifest.as_of_time,
        "produced_at": manifest.produced_at,
        "valid_until": manifest.valid_until,
        "knowledge_scope": manifest.knowledge_scope,
        "is_verified": manifest.is_verified,
        "coverage_ratio": manifest.coverage_ratio,
        "missing_count": manifest.missing_count,
        "estimated_count": manifest.estimated_count,
        "unknown_count": manifest.unknown_count,
        "selected_versions_hash": manifest.selected_versions_hash,
        "canonical_payload": encode_materialized_evaluation_actual_manifest(manifest),
        "receipt_hash": manifest.receipt_hash,
        "research_only": manifest.research_only,
        "must_not_publish_current": manifest.must_not_publish_current,
        "must_not_use_for_decision": manifest.must_not_use_for_decision,
        "must_not_execute": manifest.must_not_execute,
    }


_SOURCE_HEADER_NAMES = (
    "source_id",
    "source_version",
    "source_content_hash",
    "owner",
    "dataset",
    "subject_code",
    "industry_code",
    "calendar_id",
    "calendar_version",
    "calendar_content_hash",
    "knowledge_scope",
    "require_verified",
    "minimum_coverage_ratio",
    "maximum_missing_count",
    "maximum_estimated_count",
    "maximum_unknown_count",
    "registered_at",
    "valid_until",
    "ledger_recorded_at",
    "record_hash",
    "research_only",
    "must_not_publish_current",
    "must_not_use_for_decision",
    "must_not_execute",
)
_MANIFEST_HEADER_NAMES = (
    "manifest_id",
    "manifest_version",
    "manifest_content_hash",
    "owner",
    "dataset",
    "subject_code",
    "industry_code",
    "as_of_time",
    "produced_at",
    "valid_until",
    "knowledge_scope",
    "is_verified",
    "coverage_ratio",
    "missing_count",
    "estimated_count",
    "unknown_count",
    "selected_versions_hash",
    "receipt_hash",
    "research_only",
    "must_not_publish_current",
    "must_not_use_for_decision",
    "must_not_execute",
)


def _restore_source_model(
    model: EvaluationActualSourceDefinitionModel,
) -> PersistedEvaluationActualSourceDefinition:
    try:
        record = decode_persisted_evaluation_actual_source_definition(model.canonical_payload)
    except EvaluationActualCodecError as error:
        raise EvaluationActualCorruption(
            "evaluation actual source canonical payload is invalid"
        ) from error
    values = _source_values(record)
    if tuple(values[name] for name in _SOURCE_HEADER_NAMES) != tuple(
        getattr(model, name) for name in _SOURCE_HEADER_NAMES
    ):
        raise EvaluationActualCorruption("evaluation actual source header mismatch")
    return record


def _restore_manifest_model(
    model: EvaluationActualManifestReceiptModel,
) -> MaterializedEvaluationActualManifest:
    try:
        manifest = decode_materialized_evaluation_actual_manifest(model.canonical_payload)
    except EvaluationActualCodecError as error:
        raise EvaluationActualCorruption(
            "evaluation actual manifest canonical payload is invalid"
        ) from error
    if tuple(getattr(manifest, name) for name in _MANIFEST_HEADER_NAMES) != tuple(
        getattr(model, name) for name in _MANIFEST_HEADER_NAMES
    ):
        raise EvaluationActualCorruption("evaluation actual manifest header mismatch")
    source_record = _restore_source_model(model.source_definition)
    if source_record.definition.identity != manifest.source_definition:
        raise EvaluationActualCorruption("evaluation actual manifest source relation mismatch")
    return manifest


__all__ = [
    "DjangoEvaluationActualClock",
    "DjangoEvaluationActualGraphProvider",
    "DjangoEvaluationActualRepository",
    "DjangoEvaluationActualSourceDefinitionProvider",
]
