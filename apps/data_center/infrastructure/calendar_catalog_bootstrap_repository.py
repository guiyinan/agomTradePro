"""Atomic create-only persistence for the exchange-calendar catalog key."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from django.db import IntegrityError, transaction

from apps.data_center.application.calendar_catalog_bootstrap import (
    CalendarCatalogBootstrapError,
    CalendarCatalogBootstrapRepositoryPort,
    CalendarCatalogBootstrapResult,
    CalendarCatalogBootstrapRows,
)
from apps.data_center.domain.contracts import (
    DataOwnerRegistration,
    DatasetContract,
    ProviderBinding,
    PublicationPolicy,
)
from apps.data_center.infrastructure.catalog_models import (
    DataOwnerRegistrationModel,
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
)


@dataclass(frozen=True, slots=True)
class _ExistingCalendarCatalogRows:
    """All history for the single calendar key, including inactive records."""

    contracts: tuple[DatasetContractModel, ...]
    bindings: tuple[DatasetProviderBindingModel, ...]
    policies: tuple[DatasetPublicationPolicyModel, ...]
    owners: tuple[DataOwnerRegistrationModel, ...]

    @property
    def is_empty(self) -> bool:
        """Return whether no catalog history exists for the target key."""

        return not (self.contracts or self.bindings or self.policies or self.owners)


class DjangoCalendarCatalogBootstrapRepository(CalendarCatalogBootstrapRepositoryPort):
    """Create one complete calendar catalog bundle without touching other keys."""

    def __init__(self, using: str = "default") -> None:
        """Bind all reads and writes to one explicit database alias."""

        if not using.strip():
            raise ValueError("database alias is required")
        self._using = using

    def preview(self, rows: CalendarCatalogBootstrapRows) -> CalendarCatalogBootstrapResult:
        """Inspect target history read-only, refreshing a mixed cross-table view once."""

        state = self._read_state(rows.contract.key.value)
        if state.is_empty:
            return _result(rows, "ready", "CALENDAR_CATALOG_KEY_ABSENT")
        if _matches(state, rows):
            return _result(rows, "already_configured", "CALENDAR_CATALOG_EXACT_REPLAY")
        refreshed = self._read_state(rows.contract.key.value)
        if _matches(refreshed, rows):
            return _result(rows, "already_configured", "CALENDAR_CATALOG_EXACT_REPLAY")
        raise _conflict()

    def create_if_absent(
        self, rows: CalendarCatalogBootstrapRows
    ) -> CalendarCatalogBootstrapResult:
        """Atomically create missing rows or accept one complete exact replay."""

        try:
            with transaction.atomic(using=self._using):
                state = self._read_state(rows.contract.key.value)
                if state.is_empty:
                    created = self._create_rows(rows)
                    final_state = self._read_state(rows.contract.key.value)
                    if not _matches(final_state, rows):
                        raise _conflict()
                    if created:
                        return _result(rows, "created", "CALENDAR_CATALOG_CREATED")
                    return _result(rows, "already_configured", "CALENDAR_CATALOG_EXACT_REPLAY")
                if _matches(state, rows):
                    return _result(rows, "already_configured", "CALENDAR_CATALOG_EXACT_REPLAY")
                refreshed = self._read_state(rows.contract.key.value)
                if _matches(refreshed, rows):
                    return _result(rows, "already_configured", "CALENDAR_CATALOG_EXACT_REPLAY")
                raise _conflict()
        except IntegrityError as error:
            # A competing creator may have committed the same immutable content.
            # Re-read after rollback; any partial or changed state remains a conflict.
            state = self._read_state(rows.contract.key.value)
            if _matches(state, rows):
                return _result(rows, "already_configured", "CALENDAR_CATALOG_EXACT_REPLAY")
            raise _conflict() from error

    def _read_state(self, dataset_key: str) -> _ExistingCalendarCatalogRows:
        """Read every historical row for one key; callers refresh any mixed view."""

        return _ExistingCalendarCatalogRows(
            contracts=self._read_contracts(dataset_key),
            bindings=self._read_bindings(dataset_key),
            policies=self._read_policies(dataset_key),
            owners=self._read_owners(dataset_key),
        )

    def _read_contracts(self, dataset_key: str) -> tuple[DatasetContractModel, ...]:
        """Read all contract history for the one requested key."""

        return tuple(
            DatasetContractModel._default_manager.using(self._using)
            .filter(dataset_key=dataset_key)
            .order_by("pk")
        )

    def _read_bindings(self, dataset_key: str) -> tuple[DatasetProviderBindingModel, ...]:
        """Read all provider-binding history for the one requested key."""

        return tuple(
            DatasetProviderBindingModel._default_manager.using(self._using)
            .filter(dataset_key=dataset_key)
            .order_by("pk")
        )

    def _read_policies(self, dataset_key: str) -> tuple[DatasetPublicationPolicyModel, ...]:
        """Read all publication-policy history for the one requested key."""

        return tuple(
            DatasetPublicationPolicyModel._default_manager.using(self._using)
            .filter(dataset_key=dataset_key)
            .order_by("pk")
        )

    def _read_owners(self, dataset_key: str) -> tuple[DataOwnerRegistrationModel, ...]:
        """Read all ownership history for the one requested key."""

        return tuple(
            DataOwnerRegistrationModel._default_manager.using(self._using)
            .filter(dataset_key=dataset_key)
            .order_by("pk")
        )

    def _create_rows(self, rows: CalendarCatalogBootstrapRows) -> bool:
        """Create each exact identity without updating a row returned by a race."""

        contract = rows.contract
        dataset = contract.key
        contract_row, contract_created = DatasetContractModel._default_manager.db_manager(
            self._using
        ).get_or_create(
            dataset_key=dataset.value,
            contract_version=dataset.contract_version,
            schema_version=dataset.schema_version,
            defaults={
                "owner": contract.owner,
                "frequency": contract.frequency,
                "decision_critical": contract.decision_critical,
                "fields": _field_payload(contract),
                "freshness_seconds": contract.freshness_seconds,
                "execution_freshness_seconds": contract.execution_freshness_seconds,
                "calendar_response_max_age_seconds": contract.calendar_response_max_age_seconds,
                "comparable_group": contract.comparable_group or "",
                "active": True,
            },
        )
        binding = rows.binding
        binding_row, binding_created = DatasetProviderBindingModel._default_manager.db_manager(
            self._using
        ).get_or_create(
            dataset_key=dataset.value,
            contract_version=dataset.contract_version,
            schema_version=dataset.schema_version,
            provider=binding.provider,
            capability=binding.capability,
            defaults={
                "priority": binding.priority,
                "freshness_seconds": binding.freshness_seconds,
                "validator_key": binding.validator_key,
                "enabled": True,
            },
        )
        policy = rows.policy
        policy_row, policy_created = DatasetPublicationPolicyModel._default_manager.db_manager(
            self._using
        ).get_or_create(
            dataset_key=dataset.value,
            contract_version=dataset.contract_version,
            schema_version=dataset.schema_version,
            policy_version=policy.policy_version,
            defaults={
                "member_codec_version": (
                    policy.member_codec_version.value
                    if policy.member_codec_version is not None
                    else None
                ),
                "minimum_coverage_ratio": policy.minimum_coverage_ratio,
                "allow_partial": policy.allow_partial,
                "conflict_action": policy.conflict_action,
                "required_evidence": list(policy.required_evidence),
                "retention_days": policy.retention_days,
                "active": True,
            },
        )
        owner = rows.owner
        owner_row, owner_created = DataOwnerRegistrationModel._default_manager.db_manager(
            self._using
        ).get_or_create(
            dataset_key=owner.dataset_key,
            defaults={
                "data_platform_owner": owner.data_platform_owner,
                "business_owner": owner.business_owner,
                "acceptance_owner": owner.acceptance_owner,
                "active": True,
            },
        )
        created_flags = (contract_created, binding_created, policy_created, owner_created)
        if any(created_flags) and not all(created_flags):
            raise _conflict()
        if (
            contract_row.to_domain() != contract
            or not contract_row.active
            or binding_row.to_domain() != binding
            or not binding_row.enabled
            or policy_row.to_domain() != policy
            or not policy_row.active
            or owner_row.to_domain() != owner
        ):
            raise _conflict()
        return all((contract_created, binding_created, policy_created, owner_created))


def _field_payload(contract: DatasetContract) -> list[dict[str, object]]:
    """Serialize contract fields with the established catalog JSON shape."""

    return [
        {
            "name": field.name,
            "type": field.value_type,
            "unit": field.unit,
            "nullable": field.nullable,
            "zero_allowed": field.zero_allowed,
            "minimum": field.minimum,
            "maximum": field.maximum,
            **(
                {"source_contracts": [item.to_dict() for item in field.source_contracts]}
                if field.source_contracts
                else {}
            ),
        }
        for field in contract.fields
    ]


def _matches(state: _ExistingCalendarCatalogRows, rows: CalendarCatalogBootstrapRows) -> bool:
    """Require one full active set with exact domain content and no extra history."""

    if not (
        len(state.contracts) == 1
        and len(state.bindings) == 1
        and len(state.policies) == 1
        and len(state.owners) == 1
    ):
        return False
    try:
        return (
            _contract_row_matches(state.contracts[0], rows.contract)
            and _binding_row_matches(state.bindings[0], rows.binding)
            and _policy_row_matches(state.policies[0], rows.policy)
            and _owner_row_matches(state.owners[0], rows.owner)
        )
    except (TypeError, ValueError):
        return False


def _contract_row_matches(row: DatasetContractModel, contract: DatasetContract) -> bool:
    """Compare every persisted contract field and validate its Domain projection."""

    key = contract.key
    return (
        row.dataset_key == key.value
        and row.contract_version == key.contract_version
        and row.schema_version == key.schema_version
        and row.owner == contract.owner
        and row.frequency == contract.frequency
        and row.decision_critical is contract.decision_critical
        and row.fields == _field_payload(contract)
        and row.freshness_seconds == contract.freshness_seconds
        and row.execution_freshness_seconds == contract.execution_freshness_seconds
        and row.calendar_response_max_age_seconds == contract.calendar_response_max_age_seconds
        and row.comparable_group == (contract.comparable_group or "")
        and row.active is True
        and row.to_domain() == contract
    )


def _binding_row_matches(row: DatasetProviderBindingModel, binding: ProviderBinding) -> bool:
    """Compare every persisted provider binding field against the typed candidate."""

    key = binding.dataset
    return (
        row.dataset_key == key.value
        and row.contract_version == key.contract_version
        and row.schema_version == key.schema_version
        and row.provider == binding.provider
        and row.capability == binding.capability
        and row.priority == binding.priority
        and row.freshness_seconds == binding.freshness_seconds
        and row.validator_key == binding.validator_key
        and row.enabled is True
        and row.to_domain() == binding
    )


def _policy_row_matches(row: DatasetPublicationPolicyModel, policy: PublicationPolicy) -> bool:
    """Compare exact publication decision content, version, and activation state."""

    key = policy.dataset
    codec = policy.member_codec_version
    return (
        row.dataset_key == key.value
        and row.contract_version == key.contract_version
        and row.schema_version == key.schema_version
        and row.policy_version == policy.policy_version
        and row.member_codec_version == (codec.value if codec is not None else None)
        and row.minimum_coverage_ratio == policy.minimum_coverage_ratio
        and row.allow_partial is policy.allow_partial
        and row.conflict_action == policy.conflict_action
        and row.required_evidence == list(policy.required_evidence)
        and row.retention_days == policy.retention_days
        and row.active is True
        and row.to_domain() == policy
    )


def _owner_row_matches(row: DataOwnerRegistrationModel, owner: DataOwnerRegistration) -> bool:
    """Compare every persisted owner field against the typed candidate."""

    return (
        row.dataset_key == owner.dataset_key
        and row.data_platform_owner == owner.data_platform_owner
        and row.business_owner == owner.business_owner
        and row.acceptance_owner == owner.acceptance_owner
        and row.active is owner.active
        and row.to_domain() == owner
    )


def _result(
    rows: CalendarCatalogBootstrapRows,
    outcome: Literal["ready", "created", "already_configured"],
    reason_code: str,
) -> CalendarCatalogBootstrapResult:
    """Build the typed outcome using the candidate's exact version identity."""

    return CalendarCatalogBootstrapResult(
        outcome=outcome,
        reason_code=reason_code,
        dataset_key=rows.contract.key.value,
        contract_version=rows.contract.key.contract_version,
        schema_version=rows.contract.key.schema_version,
        policy_version=rows.policy.policy_version,
    )


def _conflict() -> CalendarCatalogBootstrapError:
    """Return the stable fail-closed result for any non-exact target history."""

    return CalendarCatalogBootstrapError(
        "CALENDAR_CATALOG_HISTORY_CONFLICT",
        "target calendar catalog history is partial, changed, or ambiguous",
    )


__all__ = ["DjangoCalendarCatalogBootstrapRepository"]
