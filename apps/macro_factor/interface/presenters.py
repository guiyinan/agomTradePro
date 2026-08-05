"""Internal R3 presenter; no current, decision or activation route is registered."""

from __future__ import annotations

from apps.macro_factor.domain.entities import MacroFactorResearchAssessment


def present_macro_factor_assessment(
    assessment: MacroFactorResearchAssessment,
) -> dict[str, object]:
    """Expose reproducibility identifiers with an unconditional decision block."""

    record = assessment.record
    return {
        "status": assessment.status.value,
        "external_evidence_id": assessment.external_evidence_id,
        "factor_version": assessment.factor_version,
        "assessed_at": assessment.assessed_at.isoformat(),
        "blocked_reasons": [reason.value for reason in assessment.blocked_reasons],
        "pit_manifest_id": record.pit_manifest_id if record is not None else None,
        "pit_manifest_hash": record.pit_manifest_hash if record is not None else None,
        "code_version": record.code_version if record is not None else None,
        "parameter_version": record.parameter_version if record is not None else None,
        "content_hash": record.content_hash if record is not None else None,
        "lifecycle_status": (record.lifecycle_status.value if record is not None else "blocked"),
        "usage_scope": "research_only",
        "research_only": True,
        "decision_eligible": False,
        "must_not_use_for_decision": True,
    }


__all__ = ["present_macro_factor_assessment"]
