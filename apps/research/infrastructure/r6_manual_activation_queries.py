"""Narrow read-only Django queries for the R6 manual-activation preflight."""

from __future__ import annotations

from datetime import datetime

from django.db.models import Q

from apps.research.application.state_model_monitoring import (
    ActiveR6QualificationEvidence,
)
from apps.research.application.state_model_qualification_lifecycle import (
    GetActiveR6Qualification,
)
from apps.research.domain.state_model_qualification_lifecycle import (
    R6QualificationRef,
)
from apps.research.infrastructure.state_model_qualification_models import (
    R6QualificationAssessmentModel,
)
from apps.research.infrastructure.state_model_qualification_repository import (
    DjangoR6QualificationClock,
    DjangoR6QualificationRepository,
)


class DjangoR6ActiveQualificationExactQuery:
    """Replay exact 0008 qualification promotion without retaining a write token."""

    __slots__ = ("_using",)

    def __init__(self, *, using: str = "default") -> None:
        if type(using) is not str or not using.strip():
            raise ValueError("R6 qualification query database alias is invalid")
        self._using = using

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared Django transaction identity."""

        return f"django:{self._using}"

    def get_exact_active(
        self,
        *,
        qualification_ref: R6QualificationRef,
        as_of: datetime,
    ) -> ActiveR6QualificationEvidence | None:
        """Return one exact active promotion and its persisted knowledge clock."""

        if type(qualification_ref) is not R6QualificationRef:
            raise TypeError("R6 qualification exact query ref type differs")
        R6QualificationRef.__post_init__(qualification_ref)
        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("R6 qualification exact query as_of must be timezone-aware")
        repository = DjangoR6QualificationRepository(using=self._using)
        assessment = GetActiveR6Qualification(
            repository=repository,
            clock=DjangoR6QualificationClock(),
        ).get_active(qualification_ref=qualification_ref, as_of=as_of)
        if assessment is None:
            return None
        candidates = tuple(
            R6QualificationAssessmentModel._default_manager.using(self._using).filter(
                Q(assessment_id=qualification_ref.assessment_id)
                | Q(content_hash=qualification_ref.assessment_hash),
                recorded_at__lte=as_of,
            )
        )
        matches = tuple(
            model
            for model in candidates
            if model.assessment_id == qualification_ref.assessment_id
            and model.content_hash == qualification_ref.assessment_hash
        )
        if len(matches) > 1:
            raise ValueError("R6 qualification exact query found multiple winners")
        if not matches:
            return None
        model = matches[0]
        if assessment.candidate_id is None or assessment.candidate_version is None:
            raise ValueError("R6 active qualification lacks candidate identity")
        return ActiveR6QualificationEvidence(
            qualification_ref=qualification_ref,
            candidate_id=assessment.candidate_id,
            candidate_version=assessment.candidate_version,
            assessed_at=assessment.assessed_at,
            known_at=model.recorded_at,
            research_only=assessment.research_only,
            must_not_use_for_decision=assessment.must_not_use_for_decision,
            must_not_replace_regime=assessment.must_not_replace_regime,
        )


__all__ = ["DjangoR6ActiveQualificationExactQuery"]
