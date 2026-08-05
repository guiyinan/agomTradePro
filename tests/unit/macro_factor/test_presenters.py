"""Interface projection keeps every R3 result explicitly research-only."""

from apps.macro_factor.application.use_cases import AssessExternalMacroFactorResearch
from apps.macro_factor.domain.entities import MacroFactorAssessmentStatus
from apps.macro_factor.interface.presenters import present_macro_factor_assessment
from tests.unit.macro_factor.factories import complete_manifest, complete_result
from tests.unit.macro_factor.test_use_cases import (
    _command,
    _ExternalProvider,
    _ManifestProvider,
    _Repository,
)


def test_presenter_exposes_reproducibility_ids_without_current_or_decision_claim() -> None:
    assessment = AssessExternalMacroFactorResearch(
        external_result_provider=_ExternalProvider(complete_result()),
        pit_manifest_provider=_ManifestProvider(complete_manifest()),
        repository=_Repository(),
    ).execute(_command())

    payload = present_macro_factor_assessment(assessment)

    assert assessment.status is MacroFactorAssessmentStatus.ACCEPTED
    assert payload["usage_scope"] == "research_only"
    assert payload["must_not_use_for_decision"] is True
    assert payload["decision_eligible"] is False
    assert payload["factor_version"] == "macro-growth-v1"
    assert payload["pit_manifest_id"] == "pit-r3-growth-v1"
    assert len(str(payload["content_hash"])) == 64
