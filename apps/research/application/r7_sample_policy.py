"""ID-only Application contracts for approved R7 sample policies."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.research.domain.r7_sample_policy import (
    PersistedR7SamplePolicy,
    validate_r7_sample_policy_scope_coherence,
)
from apps.research.domain.scenario_probability_contracts import (
    ScenarioProbabilityResearchPolicy,
    ScenarioResearchScope,
)
from apps.research.domain.scenario_research_hashing import require_sha256, require_token


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class R7SamplePolicyConflict(ValueError):
    """The requested policy or authorization identity was already sealed."""


class R7SamplePolicyCorruption(ValueError):
    """Persisted R7 policy bytes no longer match their immutable headers."""


class R7SamplePolicyUnavailable(ValueError):
    """No exact approved policy was knowable and active at the PIT cutoff."""


@dataclass(frozen=True)
class R7SamplePolicyOwnerApproval:
    """Owner-owned projection before Research binds it to a policy definition."""

    authorization_id: str
    authorization_version: str
    owner_record_id: str
    owner_record_version: str
    owner_record_hash: str
    policy_id: str
    policy_version: str
    scope_content_hash: str
    policy_definition_hash: str
    approved_by: str
    issued_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for field_name, value in (
            ("authorization_id", self.authorization_id),
            ("authorization_version", self.authorization_version),
            ("owner_record_id", self.owner_record_id),
            ("owner_record_version", self.owner_record_version),
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
            ("approved_by", self.approved_by),
        ):
            require_token(value, field_name, maximum=192)
        require_sha256(self.owner_record_hash, "owner_record_hash")
        require_sha256(self.scope_content_hash, "scope_content_hash")
        require_sha256(self.policy_definition_hash, "policy_definition_hash")
        _require_aware(self.issued_at, "owner approval issued_at")
        _require_aware(self.valid_until, "owner approval valid_until")
        if self.valid_until <= self.issued_at:
            raise ValueError("owner approval valid_until must follow issued_at")


@dataclass(frozen=True)
class R7SamplePolicyRegistrationDraft:
    """Trusted definition source; caller-owned approval fields are ignored."""

    policy_id: str
    policy_version: str
    scope: ScenarioResearchScope
    policy_definition: ScenarioProbabilityResearchPolicy

    def __post_init__(self) -> None:
        require_token(self.policy_id, "policy_id", maximum=192)
        require_token(self.policy_version, "policy_version", maximum=192)
        if self.policy_definition.policy_version != self.policy_version:
            raise ValueError("R7 sample policy draft version mismatch")
        validate_r7_sample_policy_scope_coherence(
            scope=self.scope,
            policy=self.policy_definition,
        )


class ExactR7SamplePolicyDefinitionProvider(Protocol):
    """Read one versioned policy definition from a trusted registry."""

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        as_of: datetime,
    ) -> R7SamplePolicyRegistrationDraft | None:
        """Return only the requested definition known at the PIT cutoff."""


class ExactR7SamplePolicyAuthorizationProvider(Protocol):
    """Read an exact external-owner approval; never infer caller approval."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the transaction boundary used for owner rereads."""

    def get_exact(
        self,
        *,
        authorization_id: str,
        authorization_version: str,
        policy_id: str,
        policy_version: str,
        scope_content_hash: str,
        policy_definition_hash: str,
        as_of: datetime,
    ) -> R7SamplePolicyOwnerApproval | None:
        """Return only the owner projection for the requested approval identity."""


class RiskCenterR7SamplePolicyApprovalQuery(Protocol):
    """Risk Center Application port for immutable approved-owner evidence."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the owner database transaction boundary."""

    def get_exact(
        self,
        *,
        authorization_id: str,
        authorization_version: str,
        policy_id: str,
        policy_version: str,
        scope_content_hash: str,
        policy_definition_hash: str,
        as_of: datetime,
    ) -> R7SamplePolicyOwnerApproval | None:
        """Rebuild one approved sample-policy projection from owner audit state."""


class R7SamplePolicyRepository(Protocol):
    """Read-only exact/PIT query port for Research-owned policy records."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the opaque database transaction key."""

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedR7SamplePolicy | None:
        """Return one exact record only after its server knowledge time."""

    def get_active_record(
        self,
        *,
        scope: ScenarioResearchScope,
        as_of: datetime,
    ) -> PersistedR7SamplePolicy:
        """Return the unique approved policy active at the exact PIT cutoff."""


class R7SamplePolicyRegistrationWriter(Protocol):
    """Private composition-root writer accepting only identifiers and cutoff."""

    def register(
        self,
        command: RegisterR7SamplePolicyCommand,
    ) -> PersistedR7SamplePolicy:
        """Reread trusted definition and owner receipt, then append atomically."""


@dataclass(frozen=True)
class RegisterR7SamplePolicyCommand:
    """ID/version/cutoff-only registration command."""

    policy_id: str
    policy_version: str
    authorization_id: str
    authorization_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        for field_name, value in (
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
            ("authorization_id", self.authorization_id),
            ("authorization_version", self.authorization_version),
        ):
            require_token(value, field_name, maximum=192)
        _require_aware(self.as_of, "as_of")


@dataclass(frozen=True)
class GetExactR7SamplePolicyCommand:
    """Exact historical query with no latest/current fallback."""

    policy_id: str
    policy_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        require_token(self.policy_id, "policy_id", maximum=192)
        require_token(self.policy_version, "policy_version", maximum=192)
        require_sha256(self.expected_content_hash, "expected_content_hash")
        _require_aware(self.as_of, "as_of")


class RegisterR7SamplePolicy:
    """Expose only the safe ID-only writer at the Application boundary."""

    def __init__(self, writer: R7SamplePolicyRegistrationWriter) -> None:
        self._writer = writer

    def execute(
        self,
        command: RegisterR7SamplePolicyCommand,
    ) -> PersistedR7SamplePolicy:
        """Register one exact external-owner-approved sample policy."""

        return self._writer.register(command)


class GetExactR7SamplePolicy:
    """Read a strictly restored persisted policy by exact identity/hash."""

    def __init__(self, repository: R7SamplePolicyRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactR7SamplePolicyCommand,
    ) -> PersistedR7SamplePolicy | None:
        """Return the exact policy if it was knowable at ``as_of``."""

        return self._repository.get_exact(
            policy_id=command.policy_id,
            policy_version=command.policy_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )


class R7SamplePolicyAtomicStore(Protocol):
    """Private infrastructure capability consumed only by composition."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the opaque transaction key."""

    def atomic(self) -> AbstractContextManager[None]:
        """Activate one all-or-nothing append boundary."""

    def append(self, record: PersistedR7SamplePolicy) -> PersistedR7SamplePolicy:
        """Append one exact approval/policy graph."""


__all__ = [
    "ExactR7SamplePolicyAuthorizationProvider",
    "ExactR7SamplePolicyDefinitionProvider",
    "GetExactR7SamplePolicy",
    "GetExactR7SamplePolicyCommand",
    "PersistedR7SamplePolicy",
    "R7SamplePolicyAtomicStore",
    "R7SamplePolicyConflict",
    "R7SamplePolicyCorruption",
    "R7SamplePolicyOwnerApproval",
    "RiskCenterR7SamplePolicyApprovalQuery",
    "R7SamplePolicyRegistrationDraft",
    "R7SamplePolicyRegistrationWriter",
    "R7SamplePolicyRepository",
    "R7SamplePolicyUnavailable",
    "RegisterR7SamplePolicy",
    "RegisterR7SamplePolicyCommand",
]
