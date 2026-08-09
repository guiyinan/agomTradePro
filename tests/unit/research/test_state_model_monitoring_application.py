"""ID/as-of-only R6 monitoring orchestration tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from apps.research.application.state_model_monitoring import (
    ActiveR6QualificationEvidence,
    EvaluateR6Monitoring,
    EvaluateR6MonitoringCommand,
)
from apps.research.domain.state_model_monitoring import (
    R6MonitoringAssessmentStatus,
    R6MonitoringBlockerCode,
    R6MonitoringMetricKey,
    R6MonitoringObservation,
    R6MonitoringPeriodCalendar,
    R6MonitoringPolicy,
)
from apps.research.domain.state_model_qualification_lifecycle import R6QualificationRef
from tests.unit.research.state_model_monitoring_factories import (
    NOW,
    QUALIFICATION_REF,
    active_qualification,
    healthy_metric_values,
    observation,
    period_calendar,
    policy,
)


class _ActiveProvider:
    def __init__(self, evidence: ActiveR6QualificationEvidence | None) -> None:
        self.evidence = evidence
        self.calls: list[tuple[R6QualificationRef, object]] = []

    def get_exact_active(self, *, qualification_ref, as_of):
        self.calls.append((qualification_ref, as_of))
        return self.evidence


class _PolicyProvider:
    def __init__(self, value: R6MonitoringPolicy | None) -> None:
        self.value = value
        self.calls = 0

    def get_exact(
        self,
        *,
        policy_id,
        policy_version,
        expected_policy_hash,
        qualification_ref,
        as_of,
    ):
        self.calls += 1
        return self.value


class _RawFactProvider:
    def __init__(self, values: tuple[R6MonitoringObservation, ...]) -> None:
        self.values = values
        self.calls = 0

    def list_exact(
        self,
        *,
        qualification_ref,
        policy_id,
        policy_version,
        expected_policy_hash,
        period_calendar_id,
        period_calendar_version,
        period_calendar_hash,
        as_of,
    ):
        self.calls += 1
        return self.values


class _PeriodCalendarProvider:
    def __init__(self, value: R6MonitoringPeriodCalendar | None) -> None:
        self.value = value
        self.calls = 0

    def get_exact(
        self,
        *,
        source_owner,
        calendar_id,
        calendar_version,
        expected_calendar_hash,
        as_of,
    ):
        self.calls += 1
        return self.value


def _command(*, expected_policy_hash: str | None = None) -> EvaluateR6MonitoringCommand:
    return EvaluateR6MonitoringCommand(
        qualification_ref=QUALIFICATION_REF,
        policy_id="r6-monitoring-policy",
        policy_version="v1",
        expected_policy_hash=expected_policy_hash or policy().content_hash,
        as_of=NOW,
    )


def test_application_rereads_exact_active_policy_and_raw_facts() -> None:
    """The command carries identity/cutoff only; all values come from owners."""

    monitoring_policy = policy()
    breached = healthy_metric_values()
    breached[R6MonitoringMetricKey.LOG_LOSS] = Decimal("0.5")
    active_provider = _ActiveProvider(active_qualification())
    policy_provider = _PolicyProvider(monitoring_policy)
    calendar_provider = _PeriodCalendarProvider(period_calendar())
    raw_provider = _RawFactProvider(
        (
            observation(
                sequence=1,
                monitoring_policy=monitoring_policy,
                values=breached,
            ),
            observation(
                sequence=2,
                monitoring_policy=monitoring_policy,
                values=breached,
            ),
        )
    )
    use_case = EvaluateR6Monitoring(
        active_qualification_provider=active_provider,
        policy_provider=policy_provider,
        period_calendar_provider=calendar_provider,
        raw_fact_provider=raw_provider,
    )

    assessment = use_case.execute(_command())

    assert assessment.status is R6MonitoringAssessmentStatus.RETIREMENT_REVIEW_REQUIRED
    assert assessment.automatic_retirement is False
    assert len(active_provider.calls) == 1
    assert policy_provider.calls == 1
    assert calendar_provider.calls == 1
    assert raw_provider.calls == 1
    assert set(EvaluateR6MonitoringCommand.__dataclass_fields__) == {
        "qualification_ref",
        "policy_id",
        "policy_version",
        "expected_policy_hash",
        "as_of",
    }


def test_missing_active_qualification_blocks_before_other_owner_reads() -> None:
    """No policy or facts are read when exact active qualification is absent."""

    policy_provider = _PolicyProvider(policy())
    calendar_provider = _PeriodCalendarProvider(period_calendar())
    raw_provider = _RawFactProvider(())
    use_case = EvaluateR6Monitoring(
        active_qualification_provider=_ActiveProvider(None),
        policy_provider=policy_provider,
        period_calendar_provider=calendar_provider,
        raw_fact_provider=raw_provider,
    )

    assessment = use_case.execute(_command())

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.ACTIVE_QUALIFICATION_MISSING in assessment.blockers
    assert policy_provider.calls == 0
    assert calendar_provider.calls == 0
    assert raw_provider.calls == 0


def test_missing_policy_blocks_before_raw_fact_read() -> None:
    """Raw facts cannot be interpreted without the exact injected policy."""

    raw_provider = _RawFactProvider(())
    calendar_provider = _PeriodCalendarProvider(period_calendar())
    use_case = EvaluateR6Monitoring(
        active_qualification_provider=_ActiveProvider(active_qualification()),
        policy_provider=_PolicyProvider(None),
        period_calendar_provider=calendar_provider,
        raw_fact_provider=raw_provider,
    )

    assessment = use_case.execute(_command())

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.POLICY_MISSING in assessment.blockers
    assert calendar_provider.calls == 0
    assert raw_provider.calls == 0


def test_same_identity_threshold_substitution_is_blocked_by_expected_hash() -> None:
    """A provider cannot swap thresholds behind an unchanged ID and version."""

    expected = policy()
    substituted_thresholds = tuple(
        (
            replace(item, breach_threshold=Decimal("0.7"))
            if item.metric_key is R6MonitoringMetricKey.TRANSITION_ACCURACY
            else item
        )
        for item in expected.thresholds
    )
    substituted = replace(expected, thresholds=substituted_thresholds)
    use_case = EvaluateR6Monitoring(
        active_qualification_provider=_ActiveProvider(active_qualification()),
        policy_provider=_PolicyProvider(substituted),
        period_calendar_provider=_PeriodCalendarProvider(period_calendar()),
        raw_fact_provider=_RawFactProvider(()),
    )

    assessment = use_case.execute(_command(expected_policy_hash=expected.content_hash))

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.POLICY_HASH_MISMATCH in assessment.blockers


def test_privately_mutated_policy_fails_content_seal_replay() -> None:
    """A stale policy hash cannot bless thresholds changed after construction."""

    expected = policy()
    substituted_thresholds = tuple(
        (
            replace(item, breach_threshold=Decimal("0.7"))
            if item.metric_key is R6MonitoringMetricKey.TRANSITION_ACCURACY
            else item
        )
        for item in expected.thresholds
    )
    object.__setattr__(expected, "thresholds", substituted_thresholds)
    use_case = EvaluateR6Monitoring(
        active_qualification_provider=_ActiveProvider(active_qualification()),
        policy_provider=_PolicyProvider(expected),
        period_calendar_provider=_PeriodCalendarProvider(period_calendar()),
        raw_fact_provider=_RawFactProvider(()),
    )

    assessment = use_case.execute(_command(expected_policy_hash=expected.content_hash))

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.POLICY_HASH_MISMATCH in assessment.blockers


def test_missing_exact_period_calendar_blocks_before_raw_fact_read() -> None:
    """Raw facts are not read when the policy-bound calendar is absent."""

    raw_provider = _RawFactProvider(())
    use_case = EvaluateR6Monitoring(
        active_qualification_provider=_ActiveProvider(active_qualification()),
        policy_provider=_PolicyProvider(policy()),
        period_calendar_provider=_PeriodCalendarProvider(None),
        raw_fact_provider=raw_provider,
    )

    assessment = use_case.execute(_command())

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.PERIOD_CALENDAR_MISSING in assessment.blockers
    assert raw_provider.calls == 0


def test_same_identity_replaced_period_calendar_is_blocked() -> None:
    """A provider cannot replace exact members behind one calendar ID/version."""

    canonical = period_calendar()
    substituted = replace(canonical, entries=canonical.entries[:-1])
    use_case = EvaluateR6Monitoring(
        active_qualification_provider=_ActiveProvider(active_qualification()),
        policy_provider=_PolicyProvider(policy()),
        period_calendar_provider=_PeriodCalendarProvider(substituted),
        raw_fact_provider=_RawFactProvider(()),
    )

    assessment = use_case.execute(_command())

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.PERIOD_CALENDAR_HASH_MISMATCH in assessment.blockers


def test_future_period_calendar_is_blocked() -> None:
    """An owner calendar first recorded after as-of cannot define known periods."""

    future = period_calendar()
    object.__setattr__(future, "recorded_at", NOW + timedelta(hours=1))
    use_case = EvaluateR6Monitoring(
        active_qualification_provider=_ActiveProvider(active_qualification()),
        policy_provider=_PolicyProvider(policy()),
        period_calendar_provider=_PeriodCalendarProvider(future),
        raw_fact_provider=_RawFactProvider(()),
    )

    assessment = use_case.execute(_command())

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.PERIOD_CALENDAR_FROM_FUTURE in assessment.blockers
    assert R6MonitoringBlockerCode.PERIOD_CALENDAR_HASH_MISMATCH in assessment.blockers


def test_privately_tampered_period_calendar_fails_content_seal_replay() -> None:
    """A stale manifest hash cannot hide removed canonical period members."""

    tampered = period_calendar()
    object.__setattr__(tampered, "entries", tampered.entries[:-1])
    use_case = EvaluateR6Monitoring(
        active_qualification_provider=_ActiveProvider(active_qualification()),
        policy_provider=_PolicyProvider(policy()),
        period_calendar_provider=_PeriodCalendarProvider(tampered),
        raw_fact_provider=_RawFactProvider(()),
    )

    assessment = use_case.execute(_command())

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.PERIOD_CALENDAR_HASH_MISMATCH in assessment.blockers


def test_active_projection_is_always_internal_and_content_bound() -> None:
    """Canonical active evidence cannot masquerade as decision authorization."""

    evidence = active_qualification()
    assert evidence.qualification_ref.assessment_hash == QUALIFICATION_REF.assessment_hash
    assert evidence.research_only is True
    assert evidence.must_not_use_for_decision is True
    assert evidence.must_not_replace_regime is True
