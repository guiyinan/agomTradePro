"""Fail-closed Application tests for the R3 external-evidence boundary."""

from datetime import UTC, datetime

from apps.macro_factor.application.use_cases import (
    AssessExternalMacroFactorResearch,
    AssessExternalMacroFactorResearchCommand,
)
from apps.macro_factor.domain.entities import (
    MacroFactorAssessmentStatus,
    MacroFactorBlockerCode,
    PITManifestEvidence,
)
from tests.unit.macro_factor.factories import (
    ASSESSED_AT,
    complete_manifest,
    complete_result,
    with_manifest_hash,
)


class _ExternalProvider:
    def __init__(self, result: object | None) -> None:
        self.result = result

    def get_external_result(self, evidence_id: str):  # type: ignore[no-untyped-def]
        assert evidence_id == "external-lasso-selection-v1"
        return self.result


class _ManifestProvider:
    def __init__(self, manifest: PITManifestEvidence | None) -> None:
        self.manifest = manifest

    def get_manifest(self, manifest_id: str) -> PITManifestEvidence | None:
        assert manifest_id == "pit-r3-growth-v1"
        return self.manifest


class _Repository:
    def __init__(self) -> None:
        self.records: list[object] = []

    def add(self, record):  # type: ignore[no-untyped-def]
        self.records.append(record)
        return record

    def get(self, result_id: str):  # type: ignore[no-untyped-def]
        return next(
            (record for record in self.records if record.result_id == result_id),
            None,
        )


def _command() -> AssessExternalMacroFactorResearchCommand:
    return AssessExternalMacroFactorResearchCommand(
        external_evidence_id="external-lasso-selection-v1",
        expected_manifest_id="pit-r3-growth-v1",
        assessed_at=ASSESSED_AT,
    )


def test_complete_external_evidence_is_persisted_but_never_decision_eligible() -> None:
    repository = _Repository()
    use_case = AssessExternalMacroFactorResearch(
        external_result_provider=_ExternalProvider(complete_result()),
        pit_manifest_provider=_ManifestProvider(complete_manifest()),
        repository=repository,
    )

    assessment = use_case.execute(_command())

    assert assessment.status is MacroFactorAssessmentStatus.ACCEPTED
    assert assessment.blocked_reasons == ()
    assert assessment.record is not None
    assert assessment.record.factor_version == "macro-growth-v1"
    assert assessment.record.research_only is True
    assert assessment.record.must_not_use_for_decision is True
    assert len(repository.records) == 1


def test_no_pit_data_fails_closed_without_persistence() -> None:
    repository = _Repository()
    use_case = AssessExternalMacroFactorResearch(
        external_result_provider=_ExternalProvider(complete_result()),
        pit_manifest_provider=_ManifestProvider(None),
        repository=repository,
    )

    assessment = use_case.execute(_command())

    assert assessment.status is MacroFactorAssessmentStatus.BLOCKED
    assert assessment.blocked_reasons == (MacroFactorBlockerCode.PIT_MANIFEST_MISSING,)
    assert assessment.record is None
    assert assessment.must_not_use_for_decision is True
    assert repository.records == []


def test_missing_external_calculation_fails_closed() -> None:
    repository = _Repository()
    use_case = AssessExternalMacroFactorResearch(
        external_result_provider=_ExternalProvider(None),
        pit_manifest_provider=_ManifestProvider(complete_manifest()),
        repository=repository,
    )

    assessment = use_case.execute(_command())

    assert assessment.blocked_reasons == (MacroFactorBlockerCode.EXTERNAL_RESULT_MISSING,)
    assert repository.records == []


def test_unverified_or_incomplete_manifest_fails_closed() -> None:
    complete = complete_manifest()
    manifest_coverage = complete.coverage_ratio / 2
    manifest = PITManifestEvidence.create(
        manifest_id=complete.manifest_id,
        manifest_hash=complete.manifest_hash,
        as_of_time=complete.as_of_time,
        knowledge_scope=complete.knowledge_scope,
        calendar_id=complete.calendar_id,
        calendar_version=complete.calendar_version,
        calendar_hash=complete.calendar_hash,
        inference_periods=complete.inference_periods,
        slices=complete.slices,
        is_verified=False,
        coverage_ratio=manifest_coverage,
        missing_count=1,
        estimated_count=complete.estimated_count,
        unknown_count=complete.unknown_count,
    )
    assert manifest_coverage < 1
    repository = _Repository()
    use_case = AssessExternalMacroFactorResearch(
        external_result_provider=_ExternalProvider(complete_result()),
        pit_manifest_provider=_ManifestProvider(manifest),
        repository=repository,
    )

    assessment = use_case.execute(_command())

    assert MacroFactorBlockerCode.PIT_MANIFEST_UNVERIFIED in assessment.blocked_reasons
    assert MacroFactorBlockerCode.PIT_MANIFEST_SCOPE_INCOMPLETE in assessment.blocked_reasons
    assert repository.records == []


def test_manifest_hash_mismatch_and_future_evidence_fail_closed() -> None:
    result = with_manifest_hash(complete_result(), "8" * 64)
    complete = complete_manifest()
    future_manifest = PITManifestEvidence.create(
        manifest_id=complete.manifest_id,
        manifest_hash=complete.manifest_hash,
        as_of_time=datetime(2026, 7, 4, 9, tzinfo=UTC),
        knowledge_scope=complete.knowledge_scope,
        calendar_id=complete.calendar_id,
        calendar_version=complete.calendar_version,
        calendar_hash=complete.calendar_hash,
        inference_periods=complete.inference_periods,
        slices=complete.slices,
        coverage_ratio=complete.coverage_ratio,
        missing_count=complete.missing_count,
        estimated_count=complete.estimated_count,
        unknown_count=complete.unknown_count,
        is_verified=complete.is_verified,
    )
    repository = _Repository()
    assessment = AssessExternalMacroFactorResearch(
        external_result_provider=_ExternalProvider(result),
        pit_manifest_provider=_ManifestProvider(future_manifest),
        repository=repository,
    ).execute(_command())

    assert MacroFactorBlockerCode.PIT_MANIFEST_MISMATCH in assessment.blocked_reasons
    assert MacroFactorBlockerCode.PIT_MANIFEST_FROM_FUTURE in assessment.blocked_reasons
    assert repository.records == []
