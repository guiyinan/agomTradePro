"""Exact PIT reads and private append persistence for R1 trial evidence."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.equity.application.forecast_baseline_evaluation import ResearchTrialEvidence
from apps.equity.application.forecast_baseline_materialize import (
    EvidenceIdentity,
    VersionRef,
)
from apps.research.application.r1_forecast_trial_evidence import (
    R1ForecastTrialEvidenceClock,
    R1ForecastTrialEvidenceUnavailable,
)
from apps.research.domain.r1_forecast_trial_evidence import (
    PersistedR1ForecastTrialEvidence,
)
from apps.research.infrastructure.r1_forecast_trial_evidence_codec import (
    R1ForecastTrialEvidenceCodecError,
    decode_r1_forecast_trial_evidence,
    encode_r1_forecast_trial_evidence,
)
from apps.research.infrastructure.r1_forecast_trial_evidence_models import (
    R1ForecastTrialEvidenceLedgerModel,
    _claim_r1_forecast_trial_evidence_insert,
)


class R1ForecastTrialEvidenceConflict(R1ForecastTrialEvidenceUnavailable):
    """One immutable identity or seal already has another winner."""


class R1ForecastTrialEvidenceCorruption(R1ForecastTrialEvidenceUnavailable):
    """Stored headers, canonical payload, or cardinality is corrupt."""


class DjangoR1ForecastTrialEvidenceClock:
    """Django timezone-backed trusted clock bound to one database alias."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database transaction identity."""

        return f"django:{self._using}"

    def now(self) -> datetime:
        """Return the trusted server timestamp."""

        return timezone.now()


class DjangoR1ForecastTrialEvidenceRepository:
    """Read-only exact repository with future-cutoff and live-seal checks."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R1ForecastTrialEvidenceClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoR1ForecastTrialEvidenceClock(using=using)

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact database transaction identity."""

        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        evidence_id: str,
        evidence_version: str,
        as_of: datetime,
    ) -> PersistedR1ForecastTrialEvidence | None:
        """Return one exact knowable/active receipt, never a latest fallback."""

        _require_token(evidence_id, "evidence_id")
        _require_token(evidence_version, "evidence_version")
        self._require_pit_cutoff(as_of)
        rows = list(
            R1ForecastTrialEvidenceLedgerModel._default_manager.using(self._using).filter(
                evidence_id=evidence_id,
                evidence_version=evidence_version,
            )
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise R1ForecastTrialEvidenceCorruption(
                "multiple R1 trial evidence rows match one exact identity"
            )
        evidence = _restore_model(rows[0])
        if not (
            evidence.definition.activated_at <= as_of
            and evidence.recorded_at <= as_of < evidence.definition.valid_until
        ):
            return None
        return evidence

    def _require_pit_cutoff(self, as_of: datetime) -> None:
        _require_aware(as_of, "as_of")
        try:
            now = self._clock.now()
            _require_aware(now, "clock.now")
        except R1ForecastTrialEvidenceUnavailable:
            raise
        except Exception as error:
            raise R1ForecastTrialEvidenceUnavailable(
                "R1 trial evidence trusted clock is unavailable"
            ) from error
        if as_of > now:
            raise R1ForecastTrialEvidenceUnavailable("future R1 trial evidence cutoff is forbidden")


class DjangoResearchTrialEvidenceProvider:
    """Narrow exact adapter implementing Equity's R1 Research evidence port."""

    __slots__ = ("_repository",)

    def __init__(self, repository: DjangoR1ForecastTrialEvidenceRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        """Return the read repository UoW identity."""

        return self._repository.unit_of_work_key

    def get_trial(
        self,
        trial_ref: VersionRef,
        *,
        as_of: datetime,
    ) -> ResearchTrialEvidence | None:
        """Project one exact persisted receipt or explicit absence for R1 BLOCKED."""

        try:
            if type(trial_ref) is not VersionRef:
                raise TypeError("trial reference type differs")
            VersionRef.__post_init__(trial_ref)
        except (AttributeError, TypeError, ValueError) as error:
            raise R1ForecastTrialEvidenceUnavailable(
                "R1 trial evidence reference is invalid"
            ) from error
        evidence = self._repository.get_exact(
            evidence_id=trial_ref.stable_id,
            evidence_version=trial_ref.version,
            as_of=as_of,
        )
        return None if evidence is None else _to_equity_evidence(evidence)


class _DjangoR1ForecastTrialEvidenceStore:
    """Private append store with exact winner and one atomic transaction."""

    __slots__ = ("_token", "_using")

    def __init__(self, *, using: str = "default") -> None:
        self._using = using
        self._token = object()

    @property
    def unit_of_work_key(self) -> str:
        """Return the database transaction identity."""

        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        """Open one exact database transaction."""

        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using):
            yield

    def append(
        self, evidence: PersistedR1ForecastTrialEvidence
    ) -> PersistedR1ForecastTrialEvidence:
        """Append or return the exact idempotent winner."""

        validated = decode_r1_forecast_trial_evidence(encode_r1_forecast_trial_evidence(evidence))
        definition = validated.definition
        rows = list(
            R1ForecastTrialEvidenceLedgerModel._default_manager.using(self._using).filter(
                Q(
                    evidence_id=validated.evidence_id,
                    evidence_version=validated.evidence_version,
                )
                | Q(
                    definition_id=definition.definition_id,
                    definition_version=definition.definition_version,
                )
                | Q(content_hash=validated.content_hash)
            )
        )
        if len(rows) > 1:
            raise R1ForecastTrialEvidenceConflict(
                "multiple rows collide with one R1 trial evidence append"
            )
        if rows:
            winner = _restore_model(rows[0])
            if winner == validated:
                return winner
            raise R1ForecastTrialEvidenceConflict(
                "R1 trial evidence identity already has another winner"
            )
        values = _model_values(validated)
        try:
            with _claim_r1_forecast_trial_evidence_insert(self._token):
                R1ForecastTrialEvidenceLedgerModel._default_manager.using(self._using).create(
                    **values
                )
        except IntegrityError as error:
            raise R1ForecastTrialEvidenceConflict(
                "R1 trial evidence append lost an immutable race"
            ) from error
        return validated


def _private_r1_forecast_trial_evidence_store(
    *, using: str = "default"
) -> _DjangoR1ForecastTrialEvidenceStore:
    """Return the private append capability for test-only composition."""

    return _DjangoR1ForecastTrialEvidenceStore(using=using)


def _model_values(evidence: PersistedR1ForecastTrialEvidence) -> dict[str, object]:
    definition = evidence.definition
    return {
        "evidence_id": evidence.evidence_id,
        "evidence_version": evidence.evidence_version,
        "definition_id": definition.definition_id,
        "definition_version": definition.definition_version,
        "definition_content_hash": definition.content_hash,
        "baseline_spec_id": definition.baseline_spec_id,
        "baseline_spec_version": definition.baseline_spec_version,
        "baseline_spec_content_hash": definition.baseline_spec_content_hash,
        "baseline_artifact_id": definition.baseline_artifact_id,
        "baseline_artifact_version": definition.baseline_artifact_version,
        "baseline_artifact_content_hash": definition.baseline_artifact_content_hash,
        "baseline_spec_approved_at": evidence.baseline_spec_approved_at,
        "activated_at": definition.activated_at,
        "recorded_at": evidence.recorded_at,
        "forecast_origin_at": evidence.forecast_origin_at,
        "valid_until": definition.valid_until,
        "canonical_payload": encode_r1_forecast_trial_evidence(evidence),
        "content_hash": evidence.content_hash,
        "research_only": evidence.research_only,
        "must_not_use_for_decision": evidence.must_not_use_for_decision,
        "must_not_execute": evidence.must_not_execute,
    }


_HEADER_FIELDS = (
    "evidence_id",
    "evidence_version",
    "definition_id",
    "definition_version",
    "definition_content_hash",
    "baseline_spec_id",
    "baseline_spec_version",
    "baseline_spec_content_hash",
    "baseline_artifact_id",
    "baseline_artifact_version",
    "baseline_artifact_content_hash",
    "baseline_spec_approved_at",
    "activated_at",
    "recorded_at",
    "forecast_origin_at",
    "valid_until",
    "content_hash",
    "research_only",
    "must_not_use_for_decision",
    "must_not_execute",
)


def _restore_model(
    model: R1ForecastTrialEvidenceLedgerModel,
) -> PersistedR1ForecastTrialEvidence:
    try:
        evidence = decode_r1_forecast_trial_evidence(model.canonical_payload)
    except R1ForecastTrialEvidenceCodecError as error:
        raise R1ForecastTrialEvidenceCorruption(
            "R1 trial evidence canonical payload is corrupt"
        ) from error
    expected = _model_values(evidence)
    if any(getattr(model, field_name) != expected[field_name] for field_name in _HEADER_FIELDS):
        raise R1ForecastTrialEvidenceCorruption(
            "R1 trial evidence header differs from its canonical payload"
        )
    return evidence


def _to_equity_evidence(
    evidence: PersistedR1ForecastTrialEvidence,
) -> ResearchTrialEvidence:
    definition = evidence.definition
    return ResearchTrialEvidence(
        identity=EvidenceIdentity(
            evidence.evidence_id,
            evidence.evidence_version,
            evidence.content_hash,
        ),
        owner=definition.owner,
        capability=definition.capability,
        purpose=definition.purpose,
        status=definition.status,
        split_spec_hash=definition.split_spec_hash,
        parameter_hash=definition.parameter_hash,
        baseline_spec_ref=VersionRef(
            definition.baseline_spec_id,
            definition.baseline_spec_version,
        ),
        baseline_spec_content_hash=definition.baseline_spec_content_hash,
        expected_period_ends=definition.expected_period_ends,
        metric_codes=definition.metric_codes,
        calendar_schedule_hash=definition.calendar_schedule_hash,
        evaluation_policy=definition.evaluation_policy,
        baseline_spec_approved_at=evidence.baseline_spec_approved_at,
        forecast_origin_at=evidence.forecast_origin_at,
        activated_at=definition.activated_at,
        recorded_at=evidence.recorded_at,
        valid_until=definition.valid_until,
    )


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise R1ForecastTrialEvidenceUnavailable(f"{field_name} is invalid")


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise R1ForecastTrialEvidenceUnavailable(f"{field_name} must be aware")


__all__ = [
    "DjangoR1ForecastTrialEvidenceClock",
    "DjangoR1ForecastTrialEvidenceRepository",
    "DjangoResearchTrialEvidenceProvider",
    "R1ForecastTrialEvidenceConflict",
    "R1ForecastTrialEvidenceCorruption",
]
