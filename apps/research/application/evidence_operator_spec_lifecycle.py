"""ID-only activation and exact/PIT reads for Evidence operator specs."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.evidence_operator_spec_lifecycle import (
    ActivatedEvidenceOperatorSpec,
    EvidenceOperatorSpecApprovalReceipt,
    EvidenceOperatorSpecDefinition,
)


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_hash(value: object, field_name: str) -> None:
    if type(value) is not str or len(value) != 64 or value != value.lower():
        raise ValueError(f"{field_name} must be a sha256 hex digest")
    try:
        int(value, 16)
    except ValueError as error:
        raise ValueError(f"{field_name} must be a sha256 hex digest") from error


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")


class EvidenceOperatorSpecUnavailable(ValueError):
    """An exact trusted definition, approval, or active record is unavailable."""


class EvidenceOperatorSpecConflict(ValueError):
    """An identity, winner, or supersession chain conflicts with sealed state."""


class EvidenceOperatorSpecCorruption(ValueError):
    """Persisted bytes or a provider reread no longer form the same graph."""


@dataclass(frozen=True)
class EvidenceOperatorSpecOwnerApproval:
    """External-owner Application projection; never caller-authored approval."""

    approval_id: str
    approval_version: str
    owner_record_id: str
    owner_record_version: str
    owner_record_hash: str
    operator_id: str
    operator_version: str
    definition_hash: str
    supersedes_activation_hash: str | None
    approved_by: str
    issued_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "approval_id",
            "approval_version",
            "owner_record_id",
            "owner_record_version",
            "operator_id",
            "operator_version",
            "approved_by",
        ):
            _require_token(getattr(self, field_name), field_name)
        for field_name in ("owner_record_hash", "definition_hash"):
            _require_hash(getattr(self, field_name), field_name)
        if self.supersedes_activation_hash is not None:
            _require_hash(self.supersedes_activation_hash, "supersedes_activation_hash")
        _require_aware(self.issued_at, "issued_at")
        _require_aware(self.valid_until, "valid_until")
        if self.issued_at >= self.valid_until:
            raise ValueError("owner approval validity window is invalid")

    def to_receipt(self) -> EvidenceOperatorSpecApprovalReceipt:
        """Materialize the fixed-authority Research receipt."""

        return EvidenceOperatorSpecApprovalReceipt.create(
            approval_id=self.approval_id,
            approval_version=self.approval_version,
            owner_record_id=self.owner_record_id,
            owner_record_version=self.owner_record_version,
            owner_record_hash=self.owner_record_hash,
            operator_id=self.operator_id,
            operator_version=self.operator_version,
            definition_hash=self.definition_hash,
            supersedes_activation_hash=self.supersedes_activation_hash,
            approved_by=self.approved_by,
            issued_at=self.issued_at,
            valid_until=self.valid_until,
        )


@dataclass(frozen=True)
class ActivateEvidenceOperatorSpecCommand:
    """Only caller-controlled mutation input: exact IDs, versions, and cutoff."""

    operator_id: str
    operator_version: str
    approval_id: str
    approval_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "operator_id",
            "operator_version",
            "approval_id",
            "approval_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        _require_aware(self.as_of, "as_of")


@dataclass(frozen=True)
class GetExactActivatedOperatorSpecCommand:
    """Exact historical activation query with an expected immutable hash."""

    operator_id: str
    operator_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.operator_id, "operator_id")
        _require_token(self.operator_version, "operator_version")
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_aware(self.as_of, "as_of")


@dataclass(frozen=True)
class GetActiveOperatorSpecCommand:
    """Fail-closed PIT query for one operator's active chain head."""

    operator_id: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.operator_id, "operator_id")
        _require_aware(self.as_of, "as_of")


class ExactEvidenceOperatorSpecDefinitionProvider(Protocol):
    """Trusted registry port for canonical definitions and supersession."""

    def get_exact(
        self,
        *,
        operator_id: str,
        operator_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecDefinition | None:
        """Return the exact definition known at the requested PIT cutoff."""


class RiskCenterEvidenceOperatorSpecApprovalQuery(Protocol):
    """External owner Application port for one exact approval record."""

    def get_exact(
        self,
        *,
        approval_id: str,
        approval_version: str,
        operator_id: str,
        operator_version: str,
        definition_hash: str,
        supersedes_activation_hash: str | None,
        as_of: datetime,
    ) -> EvidenceOperatorSpecOwnerApproval | None:
        """Return only an owner-audited approval matching the exact definition."""


class EvidenceOperatorSpecActivationStore(Protocol):
    """Private append graph and exact read capabilities in one Research UoW."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the all-or-nothing approval plus activation boundary."""

    def now(self) -> datetime:
        """Return the authoritative Research server clock."""

    def get_exact(
        self,
        *,
        operator_id: str,
        operator_version: str,
        as_of: datetime,
    ) -> ActivatedEvidenceOperatorSpec | None:
        """Restore an existing identity without requiring a caller hash."""

    def get_head(
        self,
        *,
        operator_id: str,
        as_of: datetime,
    ) -> ActivatedEvidenceOperatorSpec | None:
        """Restore the latest knowable chain head, active or expired."""

    def append_graph(
        self,
        record: ActivatedEvidenceOperatorSpec,
    ) -> ActivatedEvidenceOperatorSpec:
        """Atomically append the receipt and activation, or return its winner."""


class EvidenceOperatorSpecReadRepository(Protocol):
    """Public read-only exact and active PIT repository."""

    def get_exact_by_hash(
        self,
        *,
        operator_id: str,
        operator_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> ActivatedEvidenceOperatorSpec | None:
        """Return only the exact identity/hash knowable at the cutoff."""

    def get_active(
        self,
        *,
        operator_id: str,
        as_of: datetime,
    ) -> ActivatedEvidenceOperatorSpec:
        """Return one active head or fail closed when absent/ambiguous."""


class ActivateEvidenceOperatorSpec:
    """Coordinate trusted definition and external approval under one Research append."""

    def __init__(
        self,
        *,
        definition_provider: ExactEvidenceOperatorSpecDefinitionProvider,
        approval_query: RiskCenterEvidenceOperatorSpecApprovalQuery,
        store: EvidenceOperatorSpecActivationStore,
    ) -> None:
        self._definition_provider = definition_provider
        self._approval_query = approval_query
        self._store = store

    def execute(
        self,
        command: ActivateEvidenceOperatorSpecCommand,
    ) -> ActivatedEvidenceOperatorSpec:
        """Activate from IDs only, with final provider rereads before append."""

        with self._store.atomic():
            recorded_at = self._store.now()
            _require_aware(recorded_at, "Research server clock")
            if command.as_of > recorded_at:
                raise EvidenceOperatorSpecUnavailable("future as_of is not permitted")
            first_definition = self._read_definition(command)
            first_approval = self._read_approval(command, first_definition)
            head = self._store.get_head(
                operator_id=command.operator_id,
                as_of=recorded_at,
            )
            winner = self._store.get_exact(
                operator_id=command.operator_id,
                operator_version=command.operator_version,
                as_of=recorded_at,
            )
            final_definition = self._read_definition(command)
            final_approval = self._read_approval(command, final_definition)
            if first_definition != final_definition or first_approval != final_approval:
                raise EvidenceOperatorSpecCorruption(
                    "operator specification owner graph changed during activation"
                )
            receipt = final_approval.to_receipt()
            if winner is not None:
                if winner.definition != final_definition or winner.approval != receipt:
                    raise EvidenceOperatorSpecConflict(
                        "operator specification identity already has a different winner"
                    )
                return winner
            self._require_supersession(final_definition, head)
            record = ActivatedEvidenceOperatorSpec.create(
                definition=final_definition,
                approval=receipt,
                recorded_at=recorded_at,
            )
            persisted = self._store.append_graph(record)
            if persisted != record:
                raise EvidenceOperatorSpecConflict(
                    "concurrent operator specification winner differs from requested graph"
                )
            return persisted

    def _read_definition(
        self,
        command: ActivateEvidenceOperatorSpecCommand,
    ) -> EvidenceOperatorSpecDefinition:
        definition = self._definition_provider.get_exact(
            operator_id=command.operator_id,
            operator_version=command.operator_version,
            as_of=command.as_of,
        )
        if definition is None:
            raise EvidenceOperatorSpecUnavailable(
                "exact trusted operator specification definition is unavailable"
            )
        spec = definition.operator_spec
        if (
            spec.operator_id != command.operator_id
            or spec.operator_version != command.operator_version
        ):
            raise EvidenceOperatorSpecCorruption(
                "trusted operator specification identity does not match its query"
            )
        return definition

    def _read_approval(
        self,
        command: ActivateEvidenceOperatorSpecCommand,
        definition: EvidenceOperatorSpecDefinition,
    ) -> EvidenceOperatorSpecOwnerApproval:
        approval = self._approval_query.get_exact(
            approval_id=command.approval_id,
            approval_version=command.approval_version,
            operator_id=command.operator_id,
            operator_version=command.operator_version,
            definition_hash=definition.content_hash,
            supersedes_activation_hash=definition.supersedes_activation_hash,
            as_of=command.as_of,
        )
        if approval is None:
            raise EvidenceOperatorSpecUnavailable(
                "exact external-owner operator specification approval is unavailable"
            )
        if (
            approval.approval_id != command.approval_id
            or approval.approval_version != command.approval_version
            or approval.operator_id != command.operator_id
            or approval.operator_version != command.operator_version
            or approval.definition_hash != definition.content_hash
            or approval.supersedes_activation_hash != definition.supersedes_activation_hash
        ):
            raise EvidenceOperatorSpecCorruption(
                "external-owner approval identity does not match its query"
            )
        return approval

    @staticmethod
    def _require_supersession(
        definition: EvidenceOperatorSpecDefinition,
        head: ActivatedEvidenceOperatorSpec | None,
    ) -> None:
        expected = definition.supersedes_activation_hash
        if head is None and expected is not None:
            raise EvidenceOperatorSpecConflict("operator specification predecessor is missing")
        if head is not None and expected != head.content_hash:
            raise EvidenceOperatorSpecConflict(
                "operator specification does not supersede the exact current head"
            )


class GetExactActivatedOperatorSpec:
    """Expose only strict identity/hash/PIT reads."""

    def __init__(self, repository: EvidenceOperatorSpecReadRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactActivatedOperatorSpecCommand,
    ) -> ActivatedEvidenceOperatorSpec | None:
        """Return the exact activation when it was knowable at the cutoff."""

        return self._repository.get_exact_by_hash(
            operator_id=command.operator_id,
            operator_version=command.operator_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )


class GetActiveOperatorSpec:
    """Fail closed when there is no unique active activated spec."""

    def __init__(self, repository: EvidenceOperatorSpecReadRepository) -> None:
        self._repository = repository

    def execute(self, command: GetActiveOperatorSpecCommand) -> ActivatedEvidenceOperatorSpec:
        """Return the unique active chain head at the PIT cutoff."""

        return self._repository.get_active(
            operator_id=command.operator_id,
            as_of=command.as_of,
        )


__all__ = [
    "ActivateEvidenceOperatorSpec",
    "ActivateEvidenceOperatorSpecCommand",
    "EvidenceOperatorSpecActivationStore",
    "EvidenceOperatorSpecConflict",
    "EvidenceOperatorSpecCorruption",
    "EvidenceOperatorSpecOwnerApproval",
    "EvidenceOperatorSpecReadRepository",
    "EvidenceOperatorSpecUnavailable",
    "ExactEvidenceOperatorSpecDefinitionProvider",
    "GetActiveOperatorSpec",
    "GetActiveOperatorSpecCommand",
    "GetExactActivatedOperatorSpec",
    "GetExactActivatedOperatorSpecCommand",
    "RiskCenterEvidenceOperatorSpecApprovalQuery",
]
