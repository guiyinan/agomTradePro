"""Create-only application flow for one isolated exchange-calendar catalog key."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from apps.data_center.application.calendar_capture_configuration import (
    CALENDAR_CAPTURE_CAPABILITY,
    CALENDAR_CAPTURE_PROVIDER,
    CALENDAR_CAPTURE_VALIDATOR_KEY,
)
from apps.data_center.domain.contracts import (
    DataOwnerRegistration,
    DatasetContract,
    ProviderBinding,
    PublicationPolicy,
)
from apps.data_center.domain.control_plane import CalendarNullableMemberCodecVersion
from core.exceptions import ValidationError

_CALENDAR_DATASET_KEY = "data_center.exchange_calendar_snapshot"


class CalendarCatalogBootstrapError(ValidationError):
    """A calendar catalog candidate is invalid or conflicts with existing history."""

    def __init__(self, reason_code: str, message: str) -> None:
        """Keep a stable machine-readable reason for operator preview and audit."""

        self.reason_code = reason_code
        super().__init__(message=message, code=reason_code)


@dataclass(frozen=True, slots=True)
class CalendarCatalogBootstrapRows:
    """The four existing Data Center domain rows for one calendar dataset."""

    contract: DatasetContract
    binding: ProviderBinding
    policy: PublicationPolicy
    owner: DataOwnerRegistration

    def __post_init__(self) -> None:
        """Reject mismatched catalog identities before repository access."""

        validate_calendar_catalog_bootstrap_rows(self)


@dataclass(frozen=True, slots=True)
class CalendarCatalogBootstrapResult:
    """A read-only preview or create-only outcome for one catalog identity."""

    outcome: Literal["ready", "created", "already_configured"]
    reason_code: str
    dataset_key: str
    contract_version: str
    schema_version: str
    policy_version: str


class CalendarCatalogBootstrapRepositoryPort(Protocol):
    """Read or atomically create the four rows without synchronizing other keys."""

    def preview(self, rows: CalendarCatalogBootstrapRows) -> CalendarCatalogBootstrapResult:
        """Report whether the exact key is absent, fully present, or conflicting."""

    def create_if_absent(
        self, rows: CalendarCatalogBootstrapRows
    ) -> CalendarCatalogBootstrapResult:
        """Create all four rows in one transaction or return an exact replay."""


def validate_calendar_catalog_bootstrap_rows(rows: CalendarCatalogBootstrapRows) -> None:
    """Validate the calendar-specific binding and shared version identity."""

    if type(rows) is not CalendarCatalogBootstrapRows:
        raise CalendarCatalogBootstrapError(
            "CALENDAR_CATALOG_REQUEST_INVALID", "calendar catalog rows must use the typed bundle"
        )
    contract = rows.contract
    binding = rows.binding
    policy = rows.policy
    owner = rows.owner
    if (
        type(contract) is not DatasetContract
        or type(binding) is not ProviderBinding
        or type(policy) is not PublicationPolicy
        or type(owner) is not DataOwnerRegistration
    ):
        raise CalendarCatalogBootstrapError(
            "CALENDAR_CATALOG_REQUEST_INVALID", "calendar catalog bundle contains invalid rows"
        )
    for value in (contract, binding, policy, owner):
        value.__post_init__()
    key = contract.key
    if key.value != _CALENDAR_DATASET_KEY:
        raise CalendarCatalogBootstrapError(
            "CALENDAR_CATALOG_DATASET_UNSUPPORTED", "only the exchange-calendar dataset is allowed"
        )
    if not contract.calendar_response_max_age_seconds:
        raise CalendarCatalogBootstrapError(
            "CALENDAR_CATALOG_RESPONSE_AGE_REQUIRED",
            "calendar response-age limit must be explicit and positive",
        )
    if binding.dataset != key or policy.dataset != key or owner.dataset_key != key.value:
        raise CalendarCatalogBootstrapError(
            "CALENDAR_CATALOG_IDENTITY_MISMATCH",
            "contract, provider, policy, and owner rows must share one exact dataset identity",
        )
    if not binding.enabled or (
        binding.provider,
        binding.capability,
        binding.validator_key,
    ) != (
        CALENDAR_CAPTURE_PROVIDER,
        CALENDAR_CAPTURE_CAPABILITY,
        CALENDAR_CAPTURE_VALIDATOR_KEY,
    ):
        raise CalendarCatalogBootstrapError(
            "CALENDAR_CATALOG_BINDING_UNSUPPORTED",
            "calendar binding must match the configured Tushare full-date capture contract",
        )
    if (
        policy.policy_version == "legacy"
        or policy.member_codec_version is not CalendarNullableMemberCodecVersion.V1
    ):
        raise CalendarCatalogBootstrapError(
            "CALENDAR_CATALOG_POLICY_UNVERSIONED",
            "calendar policy must bind the supported versioned nullable-member codec",
        )
    if not owner.active:
        raise CalendarCatalogBootstrapError(
            "CALENDAR_CATALOG_OWNER_INACTIVE", "calendar data owner registration must be active"
        )


class CreateCalendarCatalogBootstrapUseCase:
    """Expose a preview-by-default and explicit create-only calendar UOW."""

    def __init__(self, repository: CalendarCatalogBootstrapRepositoryPort) -> None:
        """Inject the repository that owns the atomic no-overwrite boundary."""

        self._repository = repository

    def preview(self, rows: CalendarCatalogBootstrapRows) -> CalendarCatalogBootstrapResult:
        """Return readiness without creating or updating any catalog record."""

        validate_calendar_catalog_bootstrap_rows(rows)
        return self._repository.preview(rows)

    def execute(self, rows: CalendarCatalogBootstrapRows) -> CalendarCatalogBootstrapResult:
        """Create the four calendar rows or return exact content without saving again."""

        validate_calendar_catalog_bootstrap_rows(rows)
        return self._repository.create_if_absent(rows)


__all__ = [
    "CalendarCatalogBootstrapError",
    "CalendarCatalogBootstrapRepositoryPort",
    "CalendarCatalogBootstrapResult",
    "CalendarCatalogBootstrapRows",
    "CreateCalendarCatalogBootstrapUseCase",
    "validate_calendar_catalog_bootstrap_rows",
]
