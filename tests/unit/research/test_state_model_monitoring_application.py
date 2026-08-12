"""ID/as-of-only R6 monitoring orchestration tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from apps.research.application.state_model_monitoring import (
    ActiveR6QualificationEvidence,
    EvaluateR6Monitoring,
    EvaluateR6MonitoringCommand,
    R6MonitoringUnavailable,
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
    unit_of_work_key = "test:r6-monitoring"

    def __init__(self, evidence: ActiveR6QualificationEvidence | None) -> None:
        self.evidence = evidence
        self.calls: list[tuple[R6QualificationRef, object]] = []

    def get_exact_active(self, *, qualification_ref, as_of):
        self.calls.append((qualification_ref, as_of))
        return self.evidence


class _PolicyProvider:
    unit_of_work_key = "test:r6-monitoring"

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
    unit_of_work_key = "test:r6-monitoring"

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
    unit_of_work_key = "test:r6-monitoring"

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


class _Clock:
    def __init__(self, value=NOW) -> None:
        self.value = value

    def now(self):
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
        clock=_Clock(),
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
        clock=_Clock(),
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
        clock=_Clock(),
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
        clock=_Clock(),
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
        clock=_Clock(),
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
        clock=_Clock(),
    )

    assessment = use_case.execute(_command())

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.PERIOD_CALENDAR_MISSING in assessment.blockers
    assert raw_provider.calls == 0


def test_same_identity_replaced_period_calendar_is_blocked() -> None:
    """A provider cannot replace exact members behind one calendar ID/version."""

    canonical = period_calendar()
    substituted = replace(
        canonical,
        valid_until=canonical.entries[-2].period_end,
        entries=canonical.entries[:-1],
    )
    use_case = EvaluateR6Monitoring(
        active_qualification_provider=_ActiveProvider(active_qualification()),
        policy_provider=_PolicyProvider(policy()),
        period_calendar_provider=_PeriodCalendarProvider(substituted),
        raw_fact_provider=_RawFactProvider(()),
        clock=_Clock(),
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
        clock=_Clock(),
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
        clock=_Clock(),
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
    assert len(evidence.content_hash) == 64


def test_future_as_of_is_rejected_before_any_owner_read() -> None:
    """A caller cannot advance the PIT boundary beyond the trusted server clock."""

    active_provider = _ActiveProvider(active_qualification())
    use_case = EvaluateR6Monitoring(
        active_qualification_provider=active_provider,
        policy_provider=_PolicyProvider(policy()),
        period_calendar_provider=_PeriodCalendarProvider(period_calendar()),
        raw_fact_provider=_RawFactProvider(()),
        clock=_Clock(),
    )

    with pytest.raises(R6MonitoringUnavailable, match="future"):
        use_case.execute(replace(_command(), as_of=NOW + timedelta(microseconds=1)))

    assert active_provider.calls == []


def test_tampered_active_projection_is_blocked_before_policy_read() -> None:
    """The live projection carries an independent seal beyond its qualification ref."""

    active = active_qualification()
    object.__setattr__(active, "candidate_version", "substituted-v2")
    policy_provider = _PolicyProvider(policy())
    use_case = EvaluateR6Monitoring(
        active_qualification_provider=_ActiveProvider(active),
        policy_provider=policy_provider,
        period_calendar_provider=_PeriodCalendarProvider(period_calendar()),
        raw_fact_provider=_RawFactProvider(()),
        clock=_Clock(),
    )

    assessment = use_case.execute(_command())

    assert assessment.status is R6MonitoringAssessmentStatus.BLOCKED
    assert R6MonitoringBlockerCode.ACTIVE_QUALIFICATION_INVALID in assessment.blockers
    assert policy_provider.calls == 0


def test_provider_exception_is_normalized_as_unavailable() -> None:
    """Owner implementation failures never leak as arbitrary exceptions."""

    class FailingActiveProvider(_ActiveProvider):
        def get_exact_active(self, *, qualification_ref, as_of):
            raise OSError("owner offline")

    use_case = EvaluateR6Monitoring(
        active_qualification_provider=FailingActiveProvider(None),
        policy_provider=_PolicyProvider(policy()),
        period_calendar_provider=_PeriodCalendarProvider(period_calendar()),
        raw_fact_provider=_RawFactProvider(()),
        clock=_Clock(),
    )

    with pytest.raises(R6MonitoringUnavailable, match="qualification owner"):
        use_case.execute(_command())


@pytest.mark.parametrize("malformed_owner", ("active", "policy", "calendar", "facts"))
def test_malformed_owner_results_are_normalized_as_unavailable(
    malformed_owner: str,
) -> None:
    """Wrong owner result types cannot escape attribute or live-seal validation."""

    active_provider = _ActiveProvider(active_qualification())
    policy_provider = _PolicyProvider(policy())
    calendar_provider = _PeriodCalendarProvider(period_calendar())
    raw_provider = _RawFactProvider(())
    if malformed_owner == "active":
        active_provider.evidence = object()  # type: ignore[assignment]
    elif malformed_owner == "policy":
        policy_provider.value = object()  # type: ignore[assignment]
    elif malformed_owner == "calendar":
        calendar_provider.value = object()  # type: ignore[assignment]
    else:
        raw_provider.values = (object(),)  # type: ignore[assignment]
    use_case = EvaluateR6Monitoring(
        active_qualification_provider=active_provider,
        policy_provider=policy_provider,
        period_calendar_provider=calendar_provider,
        raw_fact_provider=raw_provider,
        clock=_Clock(),
    )

    with pytest.raises(R6MonitoringUnavailable, match="owner"):
        use_case.execute(_command())


@pytest.mark.parametrize("malformed_owner", ("policy", "calendar", "observation"))
def test_non_string_owner_content_hash_is_normalized_as_unavailable(
    malformed_owner: str,
) -> None:
    """Frozen owner objects cannot leak a non-string ``content_hash`` to Domain."""

    monitoring_policy = policy()
    calendar = period_calendar()
    facts = (
        observation(sequence=1, monitoring_policy=monitoring_policy),
        observation(sequence=2, monitoring_policy=monitoring_policy),
    )
    if malformed_owner == "policy":
        object.__setattr__(monitoring_policy, "content_hash", object())
    elif malformed_owner == "calendar":
        object.__setattr__(calendar, "content_hash", object())
    else:
        object.__setattr__(facts[0], "content_hash", object())
    use_case = EvaluateR6Monitoring(
        active_qualification_provider=_ActiveProvider(active_qualification()),
        policy_provider=_PolicyProvider(monitoring_policy),
        period_calendar_provider=_PeriodCalendarProvider(calendar),
        raw_fact_provider=_RawFactProvider(facts),
        clock=_Clock(),
    )

    with pytest.raises(R6MonitoringUnavailable, match="owner"):
        use_case.execute(_command())


def test_missing_or_mismatched_owner_uow_key_is_rejected() -> None:
    """All canonical providers must attest one explicit transaction boundary."""

    class MissingKeyActiveProvider:
        def get_exact_active(self, *, qualification_ref, as_of):
            return active_qualification()

    with pytest.raises(ValueError, match="unit_of_work_key"):
        EvaluateR6Monitoring(
            active_qualification_provider=MissingKeyActiveProvider(),
            policy_provider=_PolicyProvider(policy()),
            period_calendar_provider=_PeriodCalendarProvider(period_calendar()),
            raw_fact_provider=_RawFactProvider(()),
            clock=_Clock(),
        )

    mismatched = _RawFactProvider(())
    mismatched.unit_of_work_key = "test:attacker"
    with pytest.raises(ValueError, match="different units of work"):
        EvaluateR6Monitoring(
            active_qualification_provider=_ActiveProvider(active_qualification()),
            policy_provider=_PolicyProvider(policy()),
            period_calendar_provider=_PeriodCalendarProvider(period_calendar()),
            raw_fact_provider=mismatched,
            clock=_Clock(),
        )
