"""Application-boundary tests for ID-only rolling R4 execution."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime

from apps.portfolio.application.macro_risk_rolling_research import (
    R4RollingRunBlockerCode,
    R4RollingRunStatus,
    RunR4RollingStudy,
    RunR4RollingStudyCommand,
)
from apps.portfolio.domain.macro_risk_rolling_contracts import R4RollingStudyInput
from apps.portfolio.domain.r4_rolling_evidence import ExactR3PromotionAttestation
from tests.unit.portfolio.macro_risk_rolling_factories import (
    FACTOR_ARTIFACT_HASH,
    PROMOTION_DECISION_HASH,
    build_study,
    promotion_attestation,
)

EVALUATED_AT = datetime(2026, 3, 15, tzinfo=UTC)


class _StudyProvider:
    def __init__(self, study: R4RollingStudyInput | None) -> None:
        self.study = study
        self.calls: list[tuple[str, str, str, datetime]] = []

    def get_exact(
        self,
        *,
        study_id: str,
        study_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> R4RollingStudyInput | None:
        self.calls.append((study_id, study_version, expected_content_hash, as_of))
        return self.study


class _PromotionProvider:
    def __init__(self, attestation: ExactR3PromotionAttestation | None) -> None:
        self.attestation = attestation
        self.calls: list[tuple[str, str, str, str, str, str, str, datetime]] = []

    def get_exact(
        self,
        *,
        capability_key: str,
        artifact_id: str,
        artifact_version: str,
        artifact_content_hash: str,
        decision_id: str,
        decision_version: str,
        decision_content_hash: str,
        as_of: datetime,
    ) -> ExactR3PromotionAttestation | None:
        self.calls.append(
            (
                capability_key,
                artifact_id,
                artifact_version,
                artifact_content_hash,
                decision_id,
                decision_version,
                decision_content_hash,
                as_of,
            )
        )
        return self.attestation


def _command(study: R4RollingStudyInput) -> RunR4RollingStudyCommand:
    return RunR4RollingStudyCommand(
        study_id=study.study_id,
        study_version=study.study_version,
        expected_content_hash=study.content_hash,
        evaluated_at=EVALUATED_AT,
    )


def test_command_is_identity_only_and_exact_providers_receive_full_binding() -> None:
    study = build_study()
    study_provider = _StudyProvider(study)
    promotion_provider = _PromotionProvider(promotion_attestation())

    assessment = RunR4RollingStudy(study_provider, promotion_provider).execute(_command(study))

    assert {item.name for item in fields(RunR4RollingStudyCommand)} == {
        "study_id",
        "study_version",
        "expected_content_hash",
        "evaluated_at",
    }
    assert assessment.status is R4RollingRunStatus.COMPLETED_RESEARCH_ONLY
    assert assessment.blocker is None
    assert assessment.artifact is not None
    assert assessment.artifact.usage_scope == "research_only"
    assert assessment.artifact.must_not_use_for_decision is True
    assert assessment.artifact.must_not_execute is True
    assert study_provider.calls == [
        (study.study_id, study.study_version, study.content_hash, EVALUATED_AT)
    ]
    assert promotion_provider.calls == [
        (
            "macro_factor_r3",
            "r3-factor-main",
            "macro-factor-v7",
            FACTOR_ARTIFACT_HASH,
            "r3-promotion-7",
            "decision.v1",
            PROMOTION_DECISION_HASH,
            EVALUATED_AT,
        )
    ]


def test_missing_study_or_identity_substitution_fails_closed() -> None:
    study = build_study()
    missing = RunR4RollingStudy(
        _StudyProvider(None),
        _PromotionProvider(promotion_attestation()),
    ).execute(_command(study))
    assert missing.status is R4RollingRunStatus.BLOCKED
    assert missing.blocker is R4RollingRunBlockerCode.STUDY_UNAVAILABLE

    substituted = RunR4RollingStudy(
        _StudyProvider(build_study(study_id="substituted-study")),
        _PromotionProvider(promotion_attestation()),
    ).execute(_command(study))
    assert substituted.status is R4RollingRunStatus.BLOCKED
    assert substituted.blocker is R4RollingRunBlockerCode.STUDY_IDENTITY_MISMATCH


def test_missing_or_unavailable_r3_provider_is_a_stable_blocker() -> None:
    study = build_study()

    missing_provider = RunR4RollingStudy(_StudyProvider(study)).execute(_command(study))
    assert missing_provider.blocker is R4RollingRunBlockerCode.R3_PROMOTION_PROVIDER_MISSING

    unavailable = RunR4RollingStudy(
        _StudyProvider(study),
        _PromotionProvider(None),
    ).execute(_command(study))
    assert unavailable.blocker is R4RollingRunBlockerCode.R3_PROMOTION_UNAVAILABLE


def test_wrong_or_inactive_r3_attestation_is_rejected_before_evaluation() -> None:
    study = build_study()
    wrong = ExactR3PromotionAttestation.create(
        artifact_id="different-r3-artifact",
        artifact_version="macro-factor-v7",
        artifact_content_hash=FACTOR_ARTIFACT_HASH,
        decision_id="r3-promotion-7",
        decision_version="decision.v1",
        decision_content_hash=PROMOTION_DECISION_HASH,
        approved_at=datetime(2026, 1, 1, tzinfo=UTC),
        valid_until=datetime(2026, 4, 1, tzinfo=UTC),
    )
    assessment = RunR4RollingStudy(
        _StudyProvider(study),
        _PromotionProvider(wrong),
    ).execute(_command(study))

    assert assessment.status is R4RollingRunStatus.BLOCKED
    assert assessment.blocker is R4RollingRunBlockerCode.R3_PROMOTION_INVALID
    assert assessment.artifact is None
