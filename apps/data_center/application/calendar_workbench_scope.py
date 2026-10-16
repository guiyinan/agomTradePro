"""Read safe calendar configuration metadata for the workbench's initial scope panel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from apps.data_center.application.calendar_capture_configuration import (
    CalendarCaptureConfiguration,
    CalendarCaptureConfigurationError,
    SelectCalendarCaptureConfigurationUseCase,
)
from apps.data_center.application.calendar_publication_operations import CalendarOperationsClock
from apps.data_center.domain.control_plane import CalendarNullableMemberCodecVersion
from core.exceptions import DataValidationError


class CalendarWorkbenchScopeMetadataStatus(StrEnum):
    """Describe whether a single active capture configuration was selected."""

    METADATA_SELECTED = "metadata_selected"
    BLOCKED = "blocked"


class CalendarWorkbenchSecretRuntimeStatus(StrEnum):
    """State whether external credentials and provider runtime were examined."""

    NOT_CHECKED = "not_checked"


class CalendarWorkbenchCurrentPointerStatus(StrEnum):
    """State whether a specific exchange current pointer was queried."""

    NOT_SCOPED = "not_scoped"


@dataclass(frozen=True, slots=True)
class CalendarWorkbenchScopeMetadata:
    """Safe, version-exact catalog metadata with no credential or current data."""

    dataset_key: str
    contract_version: str
    schema_version: str
    calendar_response_max_age_seconds: int
    policy_identity: str
    policy_version: str
    member_codec_version: CalendarNullableMemberCodecVersion
    provider_id: int
    provider: str
    capability: str
    validator_key: str

    def __post_init__(self) -> None:
        """Validate the small projection before it is returned to an interface."""

        for field_name, value in (
            ("dataset_key", self.dataset_key),
            ("contract_version", self.contract_version),
            ("schema_version", self.schema_version),
            ("policy_identity", self.policy_identity),
            ("policy_version", self.policy_version),
            ("provider", self.provider),
            ("capability", self.capability),
            ("validator_key", self.validator_key),
        ):
            if type(value) is not str or not value or value.strip() != value:
                raise ValueError(f"Calendar workbench metadata {field_name} is invalid")
        if (
            type(self.calendar_response_max_age_seconds) is not int
            or self.calendar_response_max_age_seconds < 1
        ):
            raise ValueError("Calendar workbench metadata TTL is invalid")
        if type(self.member_codec_version) is not CalendarNullableMemberCodecVersion:
            raise TypeError("Calendar workbench metadata member codec is invalid")
        if self.member_codec_version is not CalendarNullableMemberCodecVersion.V1:
            raise ValueError("Calendar workbench metadata member codec is unsupported")
        if type(self.provider_id) is not int or self.provider_id < 1:
            raise ValueError("Calendar workbench metadata provider ID is invalid")

    @classmethod
    def from_configuration(
        cls,
        configuration: CalendarCaptureConfiguration,
    ) -> CalendarWorkbenchScopeMetadata:
        """Project only non-secret fields from the existing typed selector result."""

        if type(configuration) is not CalendarCaptureConfiguration:
            raise TypeError("Calendar workbench scope requires selected capture metadata")
        configuration.__post_init__()
        member_codec_version = configuration.policy.member_codec_version
        if member_codec_version is not CalendarNullableMemberCodecVersion.V1:
            raise ValueError("Calendar workbench selector returned an unsupported member codec")
        return cls(
            dataset_key=configuration.dataset.value,
            contract_version=configuration.dataset.contract_version,
            schema_version=configuration.dataset.schema_version,
            calendar_response_max_age_seconds=(configuration.calendar_response_max_age_seconds),
            policy_identity=configuration.policy.identity,
            policy_version=configuration.policy.policy_version,
            member_codec_version=member_codec_version,
            provider_id=configuration.provider_id,
            provider=configuration.binding.provider,
            capability=configuration.binding.capability,
            validator_key=configuration.validator_key,
        )


@dataclass(frozen=True, slots=True)
class CalendarWorkbenchScopeContext:
    """Separate metadata selection from unverified capture runtime and current state."""

    metadata_status: CalendarWorkbenchScopeMetadataStatus
    metadata: CalendarWorkbenchScopeMetadata | None
    blocked_reason: str | None
    secret_runtime_status: CalendarWorkbenchSecretRuntimeStatus
    current_pointer_status: CalendarWorkbenchCurrentPointerStatus
    known_at: datetime

    def __post_init__(self) -> None:
        """Enforce that this no-argument context makes no execution or current claim."""

        if type(self.metadata_status) is not CalendarWorkbenchScopeMetadataStatus:
            raise TypeError("Calendar workbench metadata status is invalid")
        if self.metadata is not None and type(self.metadata) is not CalendarWorkbenchScopeMetadata:
            raise TypeError("Calendar workbench metadata projection is invalid")
        if self.metadata is not None:
            self.metadata.__post_init__()
        if self.metadata_status is CalendarWorkbenchScopeMetadataStatus.METADATA_SELECTED:
            if self.metadata is None or self.blocked_reason is not None:
                raise ValueError("Selected calendar metadata requires one unblocked projection")
        elif (
            self.metadata is not None
            or type(self.blocked_reason) is not str
            or not self.blocked_reason
        ):
            raise ValueError("Blocked calendar metadata requires only a stable reason")
        if self.secret_runtime_status is not CalendarWorkbenchSecretRuntimeStatus.NOT_CHECKED:
            raise ValueError("Calendar scope context cannot claim credential or runtime validation")
        if self.current_pointer_status is not CalendarWorkbenchCurrentPointerStatus.NOT_SCOPED:
            raise ValueError("Calendar scope context has no exchange-scoped current pointer")
        _require_utc(self.known_at, "known_at")


class ReadCalendarWorkbenchScopeContextUseCase:
    """Return active calendar metadata without secrets, network, or current-pointer reads."""

    def __init__(
        self,
        *,
        selector: SelectCalendarCaptureConfigurationUseCase,
        clock: CalendarOperationsClock,
    ) -> None:
        """Bind the existing configuration selector and the server knowledge clock."""

        self._selector = selector
        self._clock = clock

    def execute(self) -> CalendarWorkbenchScopeContext:
        """Select current metadata at server time with no caller-supplied scope fields."""

        known_at = self._read_known_at()
        try:
            configuration = self._selector.execute(known_at=known_at)
        except CalendarCaptureConfigurationError as error:
            return CalendarWorkbenchScopeContext(
                metadata_status=CalendarWorkbenchScopeMetadataStatus.BLOCKED,
                metadata=None,
                blocked_reason=error.code,
                secret_runtime_status=CalendarWorkbenchSecretRuntimeStatus.NOT_CHECKED,
                current_pointer_status=CalendarWorkbenchCurrentPointerStatus.NOT_SCOPED,
                known_at=known_at,
            )
        try:
            metadata = CalendarWorkbenchScopeMetadata.from_configuration(configuration)
        except (AttributeError, TypeError, ValueError) as error:
            raise DataValidationError(
                "Calendar scope selector returned invalid metadata",
                code="CALENDAR_WORKBENCH_SCOPE_SELECTION_INVALID",
            ) from error
        return CalendarWorkbenchScopeContext(
            metadata_status=CalendarWorkbenchScopeMetadataStatus.METADATA_SELECTED,
            metadata=metadata,
            blocked_reason=None,
            secret_runtime_status=CalendarWorkbenchSecretRuntimeStatus.NOT_CHECKED,
            current_pointer_status=CalendarWorkbenchCurrentPointerStatus.NOT_SCOPED,
            known_at=known_at,
        )

    def _read_known_at(self) -> datetime:
        """Validate one explicit server UTC instant before the selector can read."""

        value = self._clock.now()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise DataValidationError(
                "Calendar scope requires a timezone-aware UTC server clock",
                code="CALENDAR_WORKBENCH_SCOPE_CLOCK_INVALID",
            )
        return value


def _require_utc(value: object, field_name: str) -> None:
    """Require an exact timezone-aware UTC instant for scope metadata."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be a timezone-aware UTC instant")


__all__ = [
    "CalendarWorkbenchCurrentPointerStatus",
    "CalendarWorkbenchScopeContext",
    "CalendarWorkbenchScopeMetadata",
    "CalendarWorkbenchScopeMetadataStatus",
    "CalendarWorkbenchSecretRuntimeStatus",
    "ReadCalendarWorkbenchScopeContextUseCase",
]
