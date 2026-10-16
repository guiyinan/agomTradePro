"""No-argument workbench scope metadata selection without secrets or current reads."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from inspect import signature

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
)
from apps.data_center.application.calendar_publication_operations import CalendarOperationsClock
from apps.data_center.application.calendar_workbench_scope import (
    CalendarWorkbenchCurrentPointerStatus,
    CalendarWorkbenchScopeMetadataStatus,
    CalendarWorkbenchSecretRuntimeStatus,
    ReadCalendarWorkbenchScopeContextUseCase,
)
from apps.data_center.domain.contracts import (
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    ProviderBinding,
    PublicationPolicy,
)
from apps.data_center.domain.control_plane import CalendarNullableMemberCodecVersion
from core.exceptions import DataValidationError

KNOWN_AT = datetime(2026, 10, 17, 8, 0, tzinfo=UTC)
DATASET = DatasetKey("data_center.exchange_calendar_snapshot", "2.0", "1.0")
OLD = KNOWN_AT - timedelta(minutes=2)


def _candidate_set() -> CalendarCaptureConfigurationCandidates:
    """Build one exact selector candidate without any credential-bearing data."""

    contract = DatasetContract(
        key=DATASET,
        owner="data-platform",
        frequency="calendar",
        decision_critical=True,
        fields=(DatasetFieldContract("calendar_date", "date", None, False, False),),
        calendar_response_max_age_seconds=900,
    )
    policy = PublicationPolicy(
        dataset=DATASET,
        minimum_coverage_ratio=1.0,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("source", "fact_content_hash"),
        retention_days=3650,
        policy_version="calendar-v1",
        member_codec_version=CalendarNullableMemberCodecVersion.V1,
    )
    binding = ProviderBinding(
        dataset=DATASET,
        provider="tushare",
        capability=CALENDAR_CAPTURE_CAPABILITY,
        priority=10,
        freshness_seconds=None,
        validator_key=CALENDAR_CAPTURE_VALIDATOR_KEY,
        enabled=True,
    )
    return CalendarCaptureConfigurationCandidates(
        contracts=(CalendarCaptureContractCandidate(contract, True, OLD, OLD),),
        policies=(CalendarCapturePolicyCandidate(policy, True, OLD, OLD),),
        bindings=(CalendarCaptureBindingCandidate(binding, True, OLD, OLD),),
        providers=(CalendarCaptureProviderCandidate(7, "tushare", True, OLD, OLD),),
    )


class _Clock:
    """Provide a deterministic server time and expose how often it was read."""

    def __init__(self, value: object = KNOWN_AT) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return self.value  # type: ignore[return-value]


class _CandidateRepository:
    """Return exact metadata candidates and record the selector's repository read."""

    def __init__(self, candidates: CalendarCaptureConfigurationCandidates) -> None:
        self.candidates = candidates
        self.calls = 0
        self.aliases: list[str] = []

    def load_candidates(self, *, using: str) -> CalendarCaptureConfigurationCandidates:
        self.calls += 1
        self.aliases.append(using)
        return self.candidates


def _use_case(
    candidates: CalendarCaptureConfigurationCandidates,
    clock: CalendarOperationsClock,
) -> tuple[ReadCalendarWorkbenchScopeContextUseCase, _CandidateRepository]:
    """Assemble the scope query around the already-shared selector port."""

    repository = _CandidateRepository(candidates)
    selector = SelectCalendarCaptureConfigurationUseCase(repository)
    return ReadCalendarWorkbenchScopeContextUseCase(selector=selector, clock=clock), repository


def test_no_argument_scope_projects_metadata_without_claiming_runtime_or_current() -> None:
    assert tuple(signature(ReadCalendarWorkbenchScopeContextUseCase.execute).parameters) == (
        "self",
    )
    clock = _Clock()
    use_case, repository = _use_case(_candidate_set(), clock)

    context = use_case.execute()

    assert context.metadata_status is CalendarWorkbenchScopeMetadataStatus.METADATA_SELECTED
    assert context.metadata is not None
    assert context.metadata.dataset_key == DATASET.value
    assert context.metadata.contract_version == DATASET.contract_version
    assert context.metadata.schema_version == DATASET.schema_version
    assert context.metadata.calendar_response_max_age_seconds == 900
    assert context.metadata.policy_identity == _candidate_set().policies[0].policy.identity
    assert context.metadata.policy_version == "calendar-v1"
    assert context.metadata.member_codec_version == CalendarNullableMemberCodecVersion.V1
    assert context.metadata.provider_id == 7
    assert context.metadata.provider == "tushare"
    assert context.metadata.capability == CALENDAR_CAPTURE_CAPABILITY
    assert context.metadata.validator_key == CALENDAR_CAPTURE_VALIDATOR_KEY
    assert context.blocked_reason is None
    assert context.secret_runtime_status is CalendarWorkbenchSecretRuntimeStatus.NOT_CHECKED
    assert context.current_pointer_status is CalendarWorkbenchCurrentPointerStatus.NOT_SCOPED
    assert context.known_at == KNOWN_AT
    assert not hasattr(context, "current_publication")
    assert not hasattr(context.metadata, "api_key")
    assert not hasattr(context.metadata, "api_secret")
    assert not hasattr(context.metadata, "http_url")
    assert repository.calls == 1
    assert repository.aliases == ["default"]
    assert clock.calls == 1


@pytest.mark.parametrize(
    ("candidates", "expected_code"),
    [
        (
            replace(_candidate_set(), contracts=()),
            "CALENDAR_CAPTURE_DATASET_MISSING",
        ),
        (
            replace(
                _candidate_set(),
                providers=(
                    CalendarCaptureProviderCandidate(7, "tushare", True, OLD, OLD),
                    CalendarCaptureProviderCandidate(8, "tushare", True, OLD, OLD),
                ),
            ),
            "CALENDAR_CAPTURE_PROVIDER_INSTANCE_AMBIGUOUS",
        ),
        (
            replace(
                _candidate_set(),
                contracts=(
                    CalendarCaptureContractCandidate(
                        replace(
                            _candidate_set().contracts[0].contract,
                            calendar_response_max_age_seconds=None,
                        ),
                        False,
                        OLD,
                        OLD,
                    ),
                ),
            ),
            "CALENDAR_CAPTURE_DATASET_MISSING",
        ),
    ],
)
def test_typed_selector_blocks_preserve_reason_without_inventing_current_absence(
    candidates: CalendarCaptureConfigurationCandidates,
    expected_code: str,
) -> None:
    use_case, repository = _use_case(candidates, _Clock())

    context = use_case.execute()

    assert context.metadata_status is CalendarWorkbenchScopeMetadataStatus.BLOCKED
    assert context.metadata is None
    assert context.blocked_reason == expected_code
    assert context.secret_runtime_status is CalendarWorkbenchSecretRuntimeStatus.NOT_CHECKED
    assert context.current_pointer_status is CalendarWorkbenchCurrentPointerStatus.NOT_SCOPED
    assert repository.calls == 1


@pytest.mark.parametrize(
    "clock_value",
    [
        KNOWN_AT.replace(tzinfo=None),
        KNOWN_AT.astimezone(timezone(timedelta(hours=8))),
        "2026-10-17T08:00:00Z",
    ],
)
def test_invalid_clock_is_rejected_before_configuration_repository_read(
    clock_value: object,
) -> None:
    clock = _Clock(clock_value)
    use_case, repository = _use_case(_candidate_set(), clock)

    with pytest.raises(DataValidationError) as raised:
        use_case.execute()

    assert raised.value.code == "CALENDAR_WORKBENCH_SCOPE_CLOCK_INVALID"
    assert repository.calls == 0
    assert clock.calls == 1


def test_untyped_repository_failure_is_not_converted_to_blocked_context() -> None:
    class FailingRepository:
        """Raise a non-configuration failure from the selector port."""

        def load_candidates(self, *, using: str) -> CalendarCaptureConfigurationCandidates:
            raise RuntimeError("repository failure")

    use_case = ReadCalendarWorkbenchScopeContextUseCase(
        selector=SelectCalendarCaptureConfigurationUseCase(FailingRepository()),
        clock=_Clock(),
    )

    with pytest.raises(RuntimeError, match="repository failure"):
        use_case.execute()


def test_configuration_error_is_the_only_selector_exception_mapped_to_blocked() -> None:
    class MissingConfigurationRepository:
        """Raise an existing stable typed configuration failure."""

        def load_candidates(self, *, using: str) -> CalendarCaptureConfigurationCandidates:
            raise CalendarCaptureConfigurationError(
                "calendar metadata unavailable", code="CALENDAR_CAPTURE_CATALOG_UNAVAILABLE"
            )

    use_case = ReadCalendarWorkbenchScopeContextUseCase(
        selector=SelectCalendarCaptureConfigurationUseCase(MissingConfigurationRepository()),
        clock=_Clock(),
    )

    context = use_case.execute()

    assert context.metadata_status is CalendarWorkbenchScopeMetadataStatus.BLOCKED
    assert context.blocked_reason == "CALENDAR_CAPTURE_CATALOG_UNAVAILABLE"
    assert context.metadata is None
