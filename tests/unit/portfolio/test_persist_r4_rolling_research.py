"""Unit coverage for the ID-only R4 rolling persistence boundary."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta

from apps.portfolio.application.persist_r4_rolling_research import (
    PersistR4RollingBlockerCode,
    PersistR4RollingResearch,
    PersistR4RollingResearchCommand,
    PersistR4RollingStatus,
)
from apps.portfolio.application.r4_rolling_research_record import (
    R4RollingResearchDraft,
    R4RollingResearchRecord,
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
RECORDED_AT = EVALUATED_AT + timedelta(minutes=1)
VALID_UNTIL = datetime(2026, 3, 31, tzinfo=UTC)


class StudyProvider:
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


class PromotionProvider:
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


class Writer:
    def __init__(self) -> None:
        self.calls: list[R4RollingResearchDraft] = []

    def append(self, draft: R4RollingResearchDraft) -> R4RollingResearchRecord:
        self.calls.append(draft)
        return R4RollingResearchRecord.from_server_clock(
            draft=draft,
            server_recorded_at=RECORDED_AT,
        )


def _command(study: R4RollingStudyInput) -> PersistR4RollingResearchCommand:
    return PersistR4RollingResearchCommand(
        study_id=study.study_id,
        study_version=study.study_version,
        expected_study_content_hash=study.content_hash,
        evaluated_at=EVALUATED_AT,
        producer_code_version="git:r4-code-v1",
        dependency_lock_hash="a" * 64,
        valid_until=VALID_UNTIL,
    )


def test_persist_command_is_id_only_and_reloads_both_authoritative_providers() -> None:
    study = build_study()
    study_provider = StudyProvider(study)
    promotion_provider = PromotionProvider(promotion_attestation())
    writer = Writer()

    assessment = PersistR4RollingResearch(
        study_provider,
        promotion_provider,
        writer,
    ).execute(_command(study))

    assert {field.name for field in fields(PersistR4RollingResearchCommand)} == {
        "study_id",
        "study_version",
        "expected_study_content_hash",
        "evaluated_at",
        "producer_code_version",
        "dependency_lock_hash",
        "valid_until",
    }
    assert assessment.status is PersistR4RollingStatus.RECORDED_RESEARCH_ONLY
    assert assessment.blocker is None
    assert assessment.record is not None
    assert assessment.record.recorded_at == RECORDED_AT
    assert len(writer.calls) == 1
    assert writer.calls[0].study is study
    assert writer.calls[0].promotion_attestation == promotion_attestation()
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


def test_missing_or_substituted_study_never_reaches_writer() -> None:
    study = build_study()
    writer = Writer()
    missing = PersistR4RollingResearch(
        StudyProvider(None),
        PromotionProvider(promotion_attestation()),
        writer,
    ).execute(_command(study))
    substituted = PersistR4RollingResearch(
        StudyProvider(build_study(study_id="substituted")),
        PromotionProvider(promotion_attestation()),
        writer,
    ).execute(_command(study))

    assert missing.blocker is PersistR4RollingBlockerCode.STUDY_UNAVAILABLE
    assert substituted.blocker is PersistR4RollingBlockerCode.STUDY_IDENTITY_MISMATCH
    assert writer.calls == []


def test_missing_or_non_exact_r3_attestation_never_reaches_writer() -> None:
    study = build_study()
    writer = Writer()
    unavailable = PersistR4RollingResearch(
        StudyProvider(study),
        PromotionProvider(None),
        writer,
    ).execute(_command(study))
    wrong = ExactR3PromotionAttestation.create(
        artifact_id="wrong-r3-artifact",
        artifact_version="macro-factor-v7",
        artifact_content_hash=FACTOR_ARTIFACT_HASH,
        decision_id="r3-promotion-7",
        decision_version="decision.v1",
        decision_content_hash=PROMOTION_DECISION_HASH,
        approved_at=datetime(2026, 1, 1, tzinfo=UTC),
        valid_until=datetime(2026, 4, 1, tzinfo=UTC),
    )
    invalid = PersistR4RollingResearch(
        StudyProvider(study),
        PromotionProvider(wrong),
        writer,
    ).execute(_command(study))

    assert unavailable.blocker is PersistR4RollingBlockerCode.R3_PROMOTION_UNAVAILABLE
    assert invalid.blocker is PersistR4RollingBlockerCode.R3_PROMOTION_INVALID
    assert writer.calls == []
