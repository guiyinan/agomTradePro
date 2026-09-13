"""Candidate-bound, policy-only activation application ports.

The application layer carries only validated Data Center domain values.  JSON
and database concerns stay at the management-command and infrastructure
boundaries respectively, so the activation workflow cannot accidentally reach
an ORM model, publication writer, or fact repository.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol

from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy
from core.exceptions import DataValidationError

CATALOG_FINGERPRINT_TABLES: Final[frozenset[str]] = frozenset(
    {
        "data_center_dataset_contract",
        "data_center_dataset_provider_binding",
        "data_center_data_owner_registration",
    }
)
SHA256_LENGTH: Final[int] = 64


class PublicationPolicyActivationError(DataValidationError):
    """Raised when an exact policy activation precondition is not proven."""

    default_message = "Publication policy activation preflight failed"
    default_code = "PUBLICATION_POLICY_ACTIVATION_ERROR"


def _require_token(value: object, field_name: str, *, max_length: int = 300) -> str:
    """Return a bounded canonical text token."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > max_length
        or any(character in value for character in ("\r", "\n"))
    ):
        raise PublicationPolicyActivationError(f"{field_name} must be a bounded single-line token")
    return value


def _require_sha256(value: object, field_name: str) -> str:
    """Return a lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise PublicationPolicyActivationError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class CatalogFingerprint:
    """Persisted row-set fingerprint captured by the activation preflight."""

    table_name: str
    row_count: int
    sha256: str

    def __post_init__(self) -> None:
        _require_token(self.table_name, "CatalogFingerprint.table_name", max_length=160)
        if self.table_name not in CATALOG_FINGERPRINT_TABLES:
            raise PublicationPolicyActivationError(
                f"unsupported catalog fingerprint table: {self.table_name}"
            )
        if type(self.row_count) is not int or self.row_count < 0:
            raise PublicationPolicyActivationError(
                "CatalogFingerprint.row_count must be non-negative"
            )
        _require_sha256(self.sha256, "CatalogFingerprint.sha256")


@dataclass(frozen=True, slots=True)
class PublishedCurrentMetadata:
    """Immutable identity metadata for one pre-existing current publication."""

    dataset_key: str
    publication_id: str
    policy_version: str
    publication_hash: str
    member_count: int
    as_of: str | None
    published_at: str | None
    must_not_use_for_decision: bool
    blocked_reason: str

    def __post_init__(self) -> None:
        for field_name in (
            "dataset_key",
            "publication_id",
            "policy_version",
            "publication_hash",
        ):
            _require_token(getattr(self, field_name), f"PublishedCurrentMetadata.{field_name}")
        if (
            type(self.blocked_reason) is not str
            or len(self.blocked_reason) > 300
            or any(character in self.blocked_reason for character in ("\r", "\n"))
        ):
            raise PublicationPolicyActivationError(
                "PublishedCurrentMetadata.blocked_reason must be single-line text"
            )
        if type(self.member_count) is not int or self.member_count < 0:
            raise PublicationPolicyActivationError(
                "PublishedCurrentMetadata.member_count must be non-negative"
            )
        if type(self.must_not_use_for_decision) is not bool:
            raise PublicationPolicyActivationError(
                "PublishedCurrentMetadata.must_not_use_for_decision must be bool"
            )
        for field_name in ("as_of", "published_at"):
            value = getattr(self, field_name)
            if value is not None:
                _require_token(value, f"PublishedCurrentMetadata.{field_name}")


@dataclass(frozen=True, slots=True)
class PublicationPolicyActivationExpectedState:
    """Typed contents of one immutable, read-only rollout preflight."""

    active_policies: tuple[PublicationPolicy, ...]
    active_contract_keys: tuple[DatasetKey, ...]
    unrelated_catalog_baseline: tuple[CatalogFingerprint, ...]
    published_current_metadata: tuple[PublishedCurrentMetadata, ...]
    candidate_policy_projection_sha256: str
    candidate_target_dataset_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.active_policies:
            raise PublicationPolicyActivationError("expected state has no active policies")
        if not self.active_contract_keys:
            raise PublicationPolicyActivationError("expected state has no active contracts")
        policy_keys = tuple(policy.dataset.value for policy in self.active_policies)
        contract_keys = tuple(key.value for key in self.active_contract_keys)
        if len(set(policy_keys)) != len(policy_keys):
            raise PublicationPolicyActivationError("expected state has duplicate active policies")
        if len(set(contract_keys)) != len(contract_keys):
            raise PublicationPolicyActivationError("expected state has duplicate active contracts")
        if set(policy_keys) != set(contract_keys):
            raise PublicationPolicyActivationError(
                "expected active policies and contracts cover different datasets"
            )
        baseline_tables = tuple(item.table_name for item in self.unrelated_catalog_baseline)
        if set(baseline_tables) != CATALOG_FINGERPRINT_TABLES or len(baseline_tables) != len(
            CATALOG_FINGERPRINT_TABLES
        ):
            raise PublicationPolicyActivationError(
                "expected state must contain all unrelated catalog fingerprints"
            )
        publication_keys = tuple(item.dataset_key for item in self.published_current_metadata)
        if len(set(publication_keys)) != len(publication_keys):
            raise PublicationPolicyActivationError(
                "expected state has duplicate current publications"
            )
        _require_sha256(
            self.candidate_policy_projection_sha256,
            "candidate_policy_projection_sha256",
        )
        target_keys = tuple(self.candidate_target_dataset_keys)
        if target_keys != tuple(sorted(set(target_keys))):
            raise PublicationPolicyActivationError(
                "candidate_target_dataset_keys must be unique and sorted"
            )
        for dataset_key in target_keys:
            _require_token(dataset_key, "candidate_target_dataset_keys[]", max_length=160)
        if not set(target_keys) <= set(policy_keys):
            raise PublicationPolicyActivationError(
                "candidate targets are absent from expected active policies"
            )


@dataclass(frozen=True, slots=True)
class PublicationPolicyActivationRequest:
    """Candidate manifest and expected state supplied to the use case."""

    expected_state: PublicationPolicyActivationExpectedState
    candidate_policies: tuple[PublicationPolicy, ...]
    candidate_manifest_sha256: str

    def __post_init__(self) -> None:
        _require_sha256(self.candidate_manifest_sha256, "candidate_manifest_sha256")
        if self.candidate_manifest_sha256 != self.expected_state.candidate_policy_projection_sha256:
            raise PublicationPolicyActivationError(
                "candidate policy projection SHA-256 differs from expected preflight"
            )
        if not self.candidate_policies:
            raise PublicationPolicyActivationError("candidate policy manifest is empty")
        expected_keys = {policy.dataset.value for policy in self.expected_state.active_policies}
        candidate_keys = tuple(policy.dataset.value for policy in self.candidate_policies)
        if len(set(candidate_keys)) != len(candidate_keys):
            raise PublicationPolicyActivationError(
                "candidate policy manifest has duplicate datasets"
            )
        if set(candidate_keys) != expected_keys:
            raise PublicationPolicyActivationError(
                "candidate policy manifest does not cover expected active datasets"
            )
        expected_contracts = {
            key.value: (key.contract_version, key.schema_version)
            for key in self.expected_state.active_contract_keys
        }
        for policy in self.candidate_policies:
            expected_version = expected_contracts.get(policy.dataset.value)
            if (
                expected_version is None
                or (
                    policy.dataset.contract_version,
                    policy.dataset.schema_version,
                )
                != expected_version
            ):
                raise PublicationPolicyActivationError(
                    f"candidate contract/schema mismatch for {policy.dataset.value}"
                )
        target_keys = tuple(
            sorted(
                policy.dataset.value
                for policy in self.candidate_policies
                if policy.uses_versioned_evidence
            )
        )
        if target_keys != self.expected_state.candidate_target_dataset_keys:
            raise PublicationPolicyActivationError(
                "candidate non-legacy target set differs from expected preflight"
            )

    @property
    def target_dataset_keys(self) -> tuple[str, ...]:
        """Return targets derived from candidate policy versions."""

        return self.expected_state.candidate_target_dataset_keys


@dataclass(frozen=True, slots=True)
class PublicationPolicyActivationResult:
    """Read-only preview or committed activation evidence."""

    preview: bool
    activated: bool
    target_dataset_keys: tuple[str, ...]
    active_policy_identities: tuple[tuple[str, str], ...]
    catalog_fingerprints: tuple[CatalogFingerprint, ...]
    published_current_metadata: tuple[PublishedCurrentMetadata, ...]

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-safe command output."""

        return {
            "mode": "preview" if self.preview else "execute",
            "activated": self.activated,
            "target_dataset_keys": list(self.target_dataset_keys),
            "active_policy_identities": [
                {"dataset_key": dataset_key, "identity": identity}
                for dataset_key, identity in self.active_policy_identities
            ],
            "catalog_fingerprints": [
                {
                    "table_name": item.table_name,
                    "row_count": item.row_count,
                    "sha256": item.sha256,
                }
                for item in self.catalog_fingerprints
            ],
            "published_current_metadata": [
                {
                    "dataset_key": item.dataset_key,
                    "publication_id": item.publication_id,
                    "policy_version": item.policy_version,
                    "publication_hash": item.publication_hash,
                    "member_count": item.member_count,
                    "as_of": item.as_of,
                    "published_at": item.published_at,
                    "must_not_use_for_decision": item.must_not_use_for_decision,
                    "blocked_reason": item.blocked_reason,
                }
                for item in self.published_current_metadata
            ],
        }


class PublicationPolicyActivationRepositoryProtocol(Protocol):
    """Infrastructure port for one guarded policy-only transition."""

    def preview(
        self, request: PublicationPolicyActivationRequest
    ) -> PublicationPolicyActivationResult:
        """Validate the candidate without changing persisted state."""

    def execute(
        self, request: PublicationPolicyActivationRequest
    ) -> PublicationPolicyActivationResult:
        """Validate and commit the candidate in one outer transaction."""


class ActivatePublicationPoliciesUseCase:
    """Expose preview and execute while keeping persistence behind a port."""

    def __init__(self, repository: PublicationPolicyActivationRepositoryProtocol) -> None:
        self._repository = repository

    def preview(
        self, request: PublicationPolicyActivationRequest
    ) -> PublicationPolicyActivationResult:
        """Run the complete read-only preflight."""

        return self._repository.preview(request)

    def execute(
        self, request: PublicationPolicyActivationRequest
    ) -> PublicationPolicyActivationResult:
        """Commit the exact candidate after the same preflight is rechecked."""

        return self._repository.execute(request)


__all__ = [
    "ActivatePublicationPoliciesUseCase",
    "CATALOG_FINGERPRINT_TABLES",
    "CatalogFingerprint",
    "PublicationPolicyActivationError",
    "PublicationPolicyActivationExpectedState",
    "PublicationPolicyActivationRepositoryProtocol",
    "PublicationPolicyActivationRequest",
    "PublicationPolicyActivationResult",
    "PublishedCurrentMetadata",
]
