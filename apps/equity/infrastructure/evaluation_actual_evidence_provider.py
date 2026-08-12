"""Equity-side projection of Data Center evaluation actual evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, cast

from apps.data_center.application.evaluation_actual_manifest import (
    EvaluationActualCorruption,
    EvaluationActualUnavailable,
)
from apps.data_center.domain.evaluation_actual_manifest import (
    CanonicalEvaluationActualFact,
    MaterializedEvaluationActualManifest,
)
from apps.equity.application.forecast_baseline_evaluation import (
    EvaluationActualManifestSnapshot,
)
from apps.equity.application.forecast_baseline_materialize import (
    EvidenceIdentity,
    ManifestSelectedVersionEvidence,
    VersionRef,
)
from apps.equity.domain.forecast_baseline_evidence import ActualFactObservation
from core.integration.r1_evaluation_actual import (
    build_r1_evaluation_actual_repository,
)


class _EvaluationActualReadRepository(Protocol):
    @property
    def unit_of_work_key(self) -> str: ...

    def get_manifest(
        self, *, manifest_id: str, manifest_version: str, as_of: datetime
    ) -> MaterializedEvaluationActualManifest | None: ...


class DjangoEvaluationActualEvidenceProvider:
    """Implement Equity's exact actual port over a Data Center read repository."""

    __slots__ = ("_repository",)

    def __init__(
        self,
        repository: object | None = None,
        *,
        using: str = "default",
    ) -> None:
        self._repository = cast(
            _EvaluationActualReadRepository,
            repository or build_r1_evaluation_actual_repository(using=using),
        )

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact repository UoW identity."""

        return self._repository.unit_of_work_key

    def get_actual_manifest(
        self,
        manifest_ref: VersionRef,
        *,
        as_of: datetime,
    ) -> EvaluationActualManifestSnapshot | None:
        """Project one strict Data Center receipt into Equity evidence."""

        try:
            if type(manifest_ref) is not VersionRef:
                raise TypeError
            VersionRef.__post_init__(manifest_ref)
        except (AttributeError, TypeError, ValueError) as error:
            raise EvaluationActualUnavailable(
                "evaluation actual manifest reference is invalid"
            ) from error
        manifest = self._repository.get_manifest(
            manifest_id=manifest_ref.stable_id,
            manifest_version=manifest_ref.version,
            as_of=as_of,
        )
        return None if manifest is None else _to_equity_snapshot(manifest)


def _to_equity_snapshot(
    manifest: MaterializedEvaluationActualManifest,
) -> EvaluationActualManifestSnapshot:
    manifest = manifest.validated_copy()
    observations = tuple(_to_equity_fact(manifest, item) for item in manifest.facts)
    selections = tuple(
        sorted(
            (
                ManifestSelectedVersionEvidence(
                    member=EvidenceIdentity(
                        item.member.stable_id,
                        item.member.version,
                        item.member.content_hash,
                    ),
                    upstream_fact=EvidenceIdentity(
                        item.source_fact.stable_id,
                        item.source_fact.version,
                        item.source_fact.content_hash,
                    ),
                    vintage=EvidenceIdentity(
                        item.vintage.stable_id,
                        item.vintage.version,
                        item.vintage.content_hash,
                    ),
                )
                for item in manifest.facts
                if item.member is not None and item.vintage is not None
            ),
            key=lambda item: (
                item.member.stable_id,
                item.member.version,
                item.member.content_hash,
                item.upstream_fact.stable_id,
                item.upstream_fact.version,
                item.upstream_fact.content_hash,
                item.vintage.stable_id,
                item.vintage.version,
                item.vintage.content_hash,
            ),
        )
    )
    if len(selections) != len(manifest.facts):
        raise EvaluationActualCorruption("materialized actual nested identities are incomplete")
    return EvaluationActualManifestSnapshot(
        identity=EvidenceIdentity(
            manifest.manifest_id,
            manifest.manifest_version,
            manifest.manifest_content_hash,
        ),
        owner=manifest.owner,
        dataset=manifest.dataset,
        subject_code=manifest.subject_code,
        industry_code=manifest.industry_code,
        calendar=EvidenceIdentity(
            manifest.calendar.stable_id,
            manifest.calendar.version,
            manifest.calendar.content_hash,
        ),
        as_of_time=manifest.as_of_time,
        produced_at=manifest.produced_at,
        knowledge_scope=manifest.knowledge_scope,
        is_verified=manifest.is_verified,
        coverage_ratio=manifest.coverage_ratio,
        missing_count=manifest.missing_count,
        estimated_count=manifest.estimated_count,
        unknown_count=manifest.unknown_count,
        selected_versions=selections,
        selected_versions_hash=manifest.selected_versions_hash,
        actuals=observations,
    )


def _to_equity_fact(
    manifest: MaterializedEvaluationActualManifest,
    fact: CanonicalEvaluationActualFact,
) -> ActualFactObservation:
    if fact.member is None or fact.vintage is None:
        raise EvaluationActualCorruption(
            "materialized actual member or vintage identity is unavailable"
        )
    return ActualFactObservation.create(
        subject_code=fact.subject_code,
        industry_code=fact.industry_code,
        dataset=fact.dataset,
        period_end=fact.period_end,
        metric_code=fact.metric_code,
        value=fact.value,
        unit=fact.unit,
        source_fact_id=fact.source_fact.stable_id,
        source_fact_version=fact.source_fact.version,
        source_fact_content_hash=fact.source_fact.content_hash,
        revision_number=fact.revision_number,
        effective_at=fact.effective_at,
        available_at=fact.available_at,
        vintage_id=fact.vintage.stable_id,
        vintage_version=fact.vintage.version,
        vintage_content_hash=fact.vintage.content_hash,
        pit_manifest_id=manifest.manifest_id,
        pit_manifest_hash=manifest.manifest_content_hash,
        manifest_member_id=fact.member.stable_id,
        manifest_member_version=fact.member.version,
        manifest_member_content_hash=fact.member.content_hash,
        calendar_id=manifest.calendar.stable_id,
        calendar_version=manifest.calendar.version,
        calendar_content_hash=manifest.calendar.content_hash,
    )


__all__ = ["DjangoEvaluationActualEvidenceProvider"]
