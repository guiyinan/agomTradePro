"""Strict selection for the separately configured calendar capture source."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.data_center.application.calendar_capture_configuration import (
    CALENDAR_CAPTURE_CAPABILITY,
    CALENDAR_CAPTURE_VALIDATOR_KEY,
    CalendarCaptureBindingCandidate,
    CalendarCaptureConfigurationCandidates,
    CalendarCaptureConfigurationError,
    CalendarCaptureContractCandidate,
    CalendarCapturePolicyCandidate,
    CalendarCaptureProviderCandidate,
    SelectCalendarCaptureConfigurationUseCase,
    resolve_calendar_capture_configuration,
)
from apps.data_center.domain.contracts import (
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    ProviderBinding,
    PublicationPolicy,
)
from apps.data_center.domain.control_plane import CalendarNullableMemberCodecVersion

KNOWN_AT = datetime(2026, 10, 17, 8, 0, tzinfo=UTC)
DATASET = DatasetKey("data_center.exchange_calendar_snapshot", "2.0", "1.0")
OLD = KNOWN_AT - timedelta(minutes=2)


def _contract(dataset: DatasetKey = DATASET) -> DatasetContract:
    return DatasetContract(
        key=dataset,
        owner="data-platform",
        frequency="calendar",
        decision_critical=True,
        fields=(DatasetFieldContract("calendar_date", "date", None, False, False),),
        calendar_response_max_age_seconds=900,
    )


def _policy(dataset: DatasetKey = DATASET) -> PublicationPolicy:
    return PublicationPolicy(
        dataset=dataset,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "fact_content_hash"),
        retention_days=3650,
        policy_version="calendar-v1",
        member_codec_version=CalendarNullableMemberCodecVersion.V1,
    )


def _binding(
    dataset: DatasetKey = DATASET,
    *,
    provider: str = "tushare",
    capability: str = CALENDAR_CAPTURE_CAPABILITY,
    validator_key: str = CALENDAR_CAPTURE_VALIDATOR_KEY,
) -> ProviderBinding:
    return ProviderBinding(
        dataset=dataset,
        provider=provider,
        capability=capability,
        priority=10,
        freshness_seconds=None,
        validator_key=validator_key,
        enabled=True,
    )


def _candidate_set() -> CalendarCaptureConfigurationCandidates:
    return CalendarCaptureConfigurationCandidates(
        contracts=(CalendarCaptureContractCandidate(_contract(), True, OLD, OLD),),
        policies=(CalendarCapturePolicyCandidate(_policy(), True, OLD, OLD),),
        bindings=(CalendarCaptureBindingCandidate(_binding(), True, OLD, OLD),),
        providers=(CalendarCaptureProviderCandidate(7, "tushare", True, OLD, OLD),),
    )


def test_selects_one_version_exact_capture_configuration() -> None:
    selected = resolve_calendar_capture_configuration(_candidate_set(), known_at=KNOWN_AT)

    assert selected.dataset == DATASET
    assert selected.calendar_response_max_age_seconds == 900
    assert selected.policy.identity == _policy().identity
    assert selected.provider_id == 7
    assert selected.validator_key == CALENDAR_CAPTURE_VALIDATOR_KEY


def test_rejects_active_same_dataset_contract_without_calendar_ttl() -> None:
    candidates = replace(
        _candidate_set(),
        contracts=(
            CalendarCaptureContractCandidate(_contract(), True, OLD, OLD),
            CalendarCaptureContractCandidate(
                replace(_contract(), calendar_response_max_age_seconds=None), True, OLD, OLD
            ),
        ),
    )

    with pytest.raises(CalendarCaptureConfigurationError) as raised:
        resolve_calendar_capture_configuration(candidates, known_at=KNOWN_AT)

    assert raised.value.code == "CALENDAR_CAPTURE_DATASET_AMBIGUOUS"


@pytest.mark.parametrize(
    ("dataset", "active"),
    [
        (DatasetKey("macro.unrelated_dataset", "1.0", "1.0"), True),
        (DATASET, False),
    ],
)
def test_ignores_unrelated_or_inactive_null_ttl_contract(dataset: DatasetKey, active: bool) -> None:
    candidates = replace(
        _candidate_set(),
        contracts=(
            CalendarCaptureContractCandidate(_contract(), True, OLD, OLD),
            CalendarCaptureContractCandidate(
                replace(_contract(dataset), calendar_response_max_age_seconds=None),
                active,
                OLD,
                OLD,
            ),
        ),
    )

    selected = resolve_calendar_capture_configuration(candidates, known_at=KNOWN_AT)

    assert selected.dataset == DATASET


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("contracts", (), "CALENDAR_CAPTURE_DATASET_MISSING"),
        (
            "contracts",
            (
                CalendarCaptureContractCandidate(
                    replace(_contract(), calendar_response_max_age_seconds=None),
                    True,
                    OLD,
                    OLD,
                ),
            ),
            "CALENDAR_CAPTURE_DATASET_MISSING",
        ),
        (
            "contracts",
            (
                CalendarCaptureContractCandidate(_contract(), True, OLD, OLD),
                CalendarCaptureContractCandidate(
                    _contract(DatasetKey("another.calendar", "1.0", "1.0")),
                    True,
                    OLD,
                    OLD,
                ),
            ),
            "CALENDAR_CAPTURE_DATASET_AMBIGUOUS",
        ),
        ("policies", (), "CALENDAR_CAPTURE_POLICY_MISSING"),
        (
            "policies",
            (
                CalendarCapturePolicyCandidate(_policy(), True, OLD, OLD),
                CalendarCapturePolicyCandidate(_policy(), True, OLD, OLD),
            ),
            "CALENDAR_CAPTURE_POLICY_AMBIGUOUS",
        ),
        (
            "policies",
            (
                CalendarCapturePolicyCandidate(
                    replace(_policy(), member_codec_version=None), True, OLD, OLD
                ),
            ),
            "CALENDAR_CAPTURE_POLICY_CODEC_UNSUPPORTED",
        ),
        (
            "policies",
            (
                CalendarCapturePolicyCandidate(
                    _policy(DatasetKey(DATASET.value, "1.0", "1.0")), True, OLD, OLD
                ),
            ),
            "CALENDAR_CAPTURE_POLICY_VERSION_MISMATCH",
        ),
        ("bindings", (), "CALENDAR_CAPTURE_BINDING_MISSING"),
        (
            "bindings",
            (
                CalendarCaptureBindingCandidate(_binding(), True, OLD, OLD),
                CalendarCaptureBindingCandidate(_binding(), True, OLD, OLD),
            ),
            "CALENDAR_CAPTURE_BINDING_AMBIGUOUS",
        ),
        (
            "bindings",
            (
                CalendarCaptureBindingCandidate(
                    _binding(validator_key="future.unregistered"), True, OLD, OLD
                ),
            ),
            "CALENDAR_CAPTURE_VALIDATOR_UNSUPPORTED",
        ),
        (
            "bindings",
            (
                CalendarCaptureBindingCandidate(
                    _binding(DatasetKey(DATASET.value, "1.0", "1.0")), True, OLD, OLD
                ),
            ),
            "CALENDAR_CAPTURE_BINDING_VERSION_MISMATCH",
        ),
        (
            "bindings",
            (CalendarCaptureBindingCandidate(_binding(capability="other"), True, OLD, OLD),),
            "CALENDAR_CAPTURE_BINDING_MISSING",
        ),
        (
            "bindings",
            (CalendarCaptureBindingCandidate(_binding(provider="akshare"), True, OLD, OLD),),
            "CALENDAR_CAPTURE_PROVIDER_UNSUPPORTED",
        ),
        ("providers", (), "CALENDAR_CAPTURE_PROVIDER_INSTANCE_MISSING"),
        (
            "providers",
            (
                CalendarCaptureProviderCandidate(7, "tushare", True, OLD, OLD),
                CalendarCaptureProviderCandidate(8, "tushare", True, OLD, OLD),
            ),
            "CALENDAR_CAPTURE_PROVIDER_INSTANCE_AMBIGUOUS",
        ),
    ],
)
def test_rejects_missing_ambiguous_or_unregistered_configuration(
    field: str,
    value: object,
    code: str,
) -> None:
    candidates = replace(_candidate_set(), **{field: value})

    with pytest.raises(CalendarCaptureConfigurationError) as raised:
        resolve_calendar_capture_configuration(candidates, known_at=KNOWN_AT)

    assert raised.value.code == code


def test_rejects_selected_metadata_not_known_by_caller_cutoff() -> None:
    candidates = replace(
        _candidate_set(),
        bindings=(
            CalendarCaptureBindingCandidate(_binding(), True, OLD, KNOWN_AT + timedelta(seconds=1)),
        ),
    )

    with pytest.raises(CalendarCaptureConfigurationError) as raised:
        resolve_calendar_capture_configuration(candidates, known_at=KNOWN_AT)

    assert raised.value.code == "CALENDAR_CAPTURE_METADATA_NOT_KNOWN"


def test_rejects_naive_knowledge_time() -> None:
    with pytest.raises(CalendarCaptureConfigurationError) as raised:
        resolve_calendar_capture_configuration(
            _candidate_set(), known_at=KNOWN_AT.replace(tzinfo=None)
        )

    assert raised.value.code == "CALENDAR_CAPTURE_KNOWLEDGE_TIME_INVALID"


def test_rejects_non_datetime_knowledge_time_before_repository_read() -> None:
    class Repository:
        """Count reads to prove malformed cutoffs fail before I/O."""

        calls = 0

        def load_candidates(self, *, using: str) -> CalendarCaptureConfigurationCandidates:
            self.calls += 1
            return _candidate_set()

    repository = Repository()
    selector = SelectCalendarCaptureConfigurationUseCase(repository)

    with pytest.raises(CalendarCaptureConfigurationError) as raised:
        selector.execute(known_at="2026-10-17T08:00:00Z")  # type: ignore[arg-type]

    assert raised.value.code == "CALENDAR_CAPTURE_KNOWLEDGE_TIME_INVALID"
    assert repository.calls == 0


def test_rejects_mutated_candidate_collection_at_selection_boundary() -> None:
    candidates = _candidate_set()
    object.__setattr__(candidates, "providers", list(candidates.providers))

    with pytest.raises(CalendarCaptureConfigurationError) as raised:
        resolve_calendar_capture_configuration(candidates, known_at=KNOWN_AT)

    assert raised.value.code == "CALENDAR_CAPTURE_CANDIDATES_INVALID"


def test_candidate_dtos_reject_invalid_types_at_the_infrastructure_boundary() -> None:
    """Persisted row adapters cannot smuggle malformed values into selection."""

    with pytest.raises(TypeError):
        CalendarCaptureContractCandidate(object(), True, OLD, OLD)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        CalendarCaptureContractCandidate(_contract(), 1, OLD, OLD)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        CalendarCapturePolicyCandidate(_policy(), 1, OLD, OLD)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        CalendarCaptureBindingCandidate(_binding(), 1, OLD, OLD)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        CalendarCaptureProviderCandidate(True, "tushare", True, OLD, OLD)
    with pytest.raises(ValueError):
        CalendarCaptureProviderCandidate(0, "tushare", True, OLD, OLD)
    with pytest.raises(ValueError):
        CalendarCaptureProviderCandidate(7, "", True, OLD, OLD)
    with pytest.raises(TypeError):
        CalendarCaptureProviderCandidate(7, "tushare", 1, OLD, OLD)  # type: ignore[arg-type]
