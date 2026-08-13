"""Two-person activation contract for one policy-benchmark methodology bundle."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from .policy_benchmark_definition import (
    PolicyBenchmarkMethodologyRef,
    PortfolioPolicyBenchmarkDefinition,
)

POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_OWNER = "portfolio"
POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_CAPABILITY = (
    "policy_benchmark_methodology_bundle_activation"
)
POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_ARTIFACT_TYPE = (
    "policy_benchmark_methodology_bundle_activation"
)
POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_SCHEMA = (
    "portfolio-policy-benchmark-methodology-bundle-activation.v1"
)
POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_PERMISSION = "benchmark_configuration_only"
POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_CLOCK_SOURCE = "server"

_METHODOLOGY_TYPES = (
    "corporate_action_methodology",
    "cost_tax_methodology",
    "fx_fixing_methodology",
    "price_fixing_methodology",
    "trading_calendar_definition",
)


def _token(value: object, field_name: str, maximum: int = 192) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _digest(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _optional_digest(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _digest(value, field_name)


def _aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PolicyBenchmarkMethodologyActivationActor:
    """Server-authenticated human staff identity used by the two-person gate."""

    actor_id: str
    user_id: int
    role: str
    kind: str = "human"
    is_staff: bool = True
    authentication_source: str = "server"

    def __post_init__(self) -> None:
        _token(self.actor_id, "actor_id")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be an exact positive integer")
        _token(self.role, "role")
        if (
            self.kind != "human"
            or self.is_staff is not True
            or self.authentication_source != "server"
        ):
            raise ValueError("activation actor must be server-authenticated human staff")

    def to_payload(self) -> dict[str, object]:
        """Return the sealed server actor identity."""

        return {
            "actor_id": self.actor_id,
            "user_id": self.user_id,
            "role": self.role,
            "kind": self.kind,
            "is_staff": self.is_staff,
            "authentication_source": self.authentication_source,
        }


@dataclass(frozen=True, slots=True)
class PolicyBenchmarkMethodologyBundle:
    """One ordered, exact five-methodology bundle for a benchmark definition."""

    methodology_refs: tuple[PolicyBenchmarkMethodologyRef, ...]
    valid_until: datetime
    bundle_hash: str = ""

    @classmethod
    def from_definition(
        cls,
        definition: PortfolioPolicyBenchmarkDefinition,
    ) -> PolicyBenchmarkMethodologyBundle:
        """Create the complete ordered bundle from one exact definition."""

        if type(definition) is not PortfolioPolicyBenchmarkDefinition:
            raise TypeError("definition must be an exact PortfolioPolicyBenchmarkDefinition")
        PortfolioPolicyBenchmarkDefinition.__post_init__(definition)
        return cls(
            methodology_refs=(
                definition.corporate_action_ref,
                definition.cost_tax_ref,
                definition.fx_fixing_ref,
                definition.price_fixing_ref,
                definition.trading_calendar_ref,
            ),
            valid_until=definition.valid_until,
        )

    def __post_init__(self) -> None:
        if type(self.methodology_refs) is not tuple or len(self.methodology_refs) != 5:
            raise ValueError("methodology_refs must be one complete exact five-item tuple")
        for ref in self.methodology_refs:
            if type(ref) is not PolicyBenchmarkMethodologyRef:
                raise TypeError("methodology_refs must contain exact Domain references")
            PolicyBenchmarkMethodologyRef.__post_init__(ref)
            if ref.owner != POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_OWNER:
                raise ValueError("methodology reference owner must be portfolio")
        if tuple(ref.artifact_type for ref in self.methodology_refs) != _METHODOLOGY_TYPES:
            raise ValueError("methodology_refs must use the fixed complete order")
        _aware(self.valid_until, "bundle valid_until")
        if self.valid_until != min(ref.valid_until for ref in self.methodology_refs):
            raise ValueError("bundle valid_until must equal the methodology minimum")
        expected = _canonical_hash(self._bundle_payload())
        if not self.bundle_hash:
            object.__setattr__(self, "bundle_hash", expected)
        elif _digest(self.bundle_hash, "bundle_hash") != expected:
            raise ValueError("methodology bundle_hash is invalid")

    def _bundle_payload(self) -> dict[str, object]:
        return {
            "methodology_refs": [ref.to_payload() for ref in self.methodology_refs],
            "valid_until": _utc_text(self.valid_until),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the ordered bundle and its canonical digest."""

        return {**self._bundle_payload(), "bundle_hash": self.bundle_hash}


@dataclass(frozen=True, slots=True)
class PolicyBenchmarkMethodologyActivationSubject:
    """Immutable request for one exact definition and methodology bundle."""

    subject_id: str
    subject_version: str
    definition_id: str
    definition_version: str
    definition_identity_hash: str
    definition_content_hash: str
    definition_recorded_at: datetime
    definition_valid_until: datetime
    bundle: PolicyBenchmarkMethodologyBundle
    requested_by: PolicyBenchmarkMethodologyActivationActor
    requested_at: datetime
    valid_until: datetime
    supersedes_activation_hash: str | None = None
    content_hash: str = ""
    clock_source: str = POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_CLOCK_SOURCE

    @classmethod
    def create(
        cls,
        *,
        subject_id: str,
        subject_version: str,
        definition: PortfolioPolicyBenchmarkDefinition,
        requested_by: PolicyBenchmarkMethodologyActivationActor,
        requested_at: datetime,
        supersedes_activation_hash: str | None,
    ) -> PolicyBenchmarkMethodologyActivationSubject:
        """Seal a request for one complete, currently knowable definition."""

        if type(definition) is not PortfolioPolicyBenchmarkDefinition:
            raise TypeError("definition must be an exact PortfolioPolicyBenchmarkDefinition")
        PortfolioPolicyBenchmarkDefinition.__post_init__(definition)
        _aware(requested_at, "requested_at")
        if not definition.is_knowable_at(requested_at):
            raise ValueError("policy benchmark definition is not knowable at request time")
        return cls(
            subject_id=subject_id,
            subject_version=subject_version,
            definition_id=definition.definition_id,
            definition_version=definition.definition_version,
            definition_identity_hash=definition.identity_hash,
            definition_content_hash=definition.content_hash,
            definition_recorded_at=definition.recorded_at,
            definition_valid_until=definition.valid_until,
            bundle=PolicyBenchmarkMethodologyBundle.from_definition(definition),
            requested_by=requested_by,
            requested_at=requested_at,
            valid_until=definition.valid_until,
            supersedes_activation_hash=supersedes_activation_hash,
        )

    def __post_init__(self) -> None:
        for field_name in (
            "subject_id",
            "subject_version",
            "definition_id",
            "definition_version",
        ):
            _token(getattr(self, field_name), field_name)
        _digest(self.definition_identity_hash, "definition_identity_hash")
        _digest(self.definition_content_hash, "definition_content_hash")
        _optional_digest(self.supersedes_activation_hash, "supersedes_activation_hash")
        _aware(self.definition_recorded_at, "definition_recorded_at")
        _aware(self.definition_valid_until, "definition_valid_until")
        if type(self.bundle) is not PolicyBenchmarkMethodologyBundle:
            raise TypeError("bundle must be an exact PolicyBenchmarkMethodologyBundle")
        PolicyBenchmarkMethodologyBundle.__post_init__(self.bundle)
        if type(self.requested_by) is not PolicyBenchmarkMethodologyActivationActor:
            raise TypeError("requested_by must be an exact activation actor")
        PolicyBenchmarkMethodologyActivationActor.__post_init__(self.requested_by)
        _aware(self.requested_at, "requested_at")
        _aware(self.valid_until, "valid_until")
        if self.clock_source != POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_CLOCK_SOURCE:
            raise ValueError("activation subject clock_source is fixed to server")
        if self.definition_valid_until != self.bundle.valid_until:
            raise ValueError("definition and methodology bundle validity must agree")
        if self.valid_until != self.definition_valid_until:
            raise ValueError("subject validity must equal definition validity")
        if any(
            ref.recorded_at > self.definition_recorded_at for ref in self.bundle.methodology_refs
        ):
            raise ValueError("methodology reference is not knowable at definition recording")
        if not self.definition_recorded_at <= self.requested_at < self.valid_until:
            raise ValueError("activation subject clock window is invalid")
        expected = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)
        elif _digest(self.content_hash, "content_hash") != expected:
            raise ValueError("activation subject content_hash is invalid")

    def is_valid_at(self, as_of: datetime) -> bool:
        """Return whether the request is knowable and unexpired."""

        _aware(as_of, "as_of")
        return self.requested_at <= as_of < self.valid_until

    def _content_payload(self) -> dict[str, object]:
        return {
            "subject_id": self.subject_id,
            "subject_version": self.subject_version,
            "definition_id": self.definition_id,
            "definition_version": self.definition_version,
            "definition_identity_hash": self.definition_identity_hash,
            "definition_content_hash": self.definition_content_hash,
            "definition_recorded_at": _utc_text(self.definition_recorded_at),
            "definition_valid_until": _utc_text(self.definition_valid_until),
            "bundle": self.bundle.to_payload(),
            "requested_by": self.requested_by.to_payload(),
            "requested_at": _utc_text(self.requested_at),
            "valid_until": _utc_text(self.valid_until),
            "supersedes_activation_hash": self.supersedes_activation_hash,
            "clock_source": self.clock_source,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the exact definition-and-bundle activation request."""

        return {**self._content_payload(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class PolicyBenchmarkMethodologyBundleActivation:
    """Two-person configuration activation that grants no valuation or trade power."""

    activation_id: str
    activation_version: str
    subject: PolicyBenchmarkMethodologyActivationSubject
    approved_by: PolicyBenchmarkMethodologyActivationActor
    issued_at: datetime
    valid_until: datetime
    content_hash: str = ""
    owner: str = POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_OWNER
    capability: str = POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_CAPABILITY
    artifact_type: str = POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_ARTIFACT_TYPE
    schema: str = POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_SCHEMA
    permission: str = POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_PERMISSION
    clock_source: str = POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_CLOCK_SOURCE

    @classmethod
    def create(
        cls,
        *,
        activation_id: str,
        activation_version: str,
        subject: PolicyBenchmarkMethodologyActivationSubject,
        approved_by: PolicyBenchmarkMethodologyActivationActor,
        issued_at: datetime,
    ) -> PolicyBenchmarkMethodologyBundleActivation:
        """Issue the bundle activation after exact two-person checks."""

        if type(subject) is not PolicyBenchmarkMethodologyActivationSubject:
            raise TypeError("subject must be an exact methodology activation subject")
        return cls(
            activation_id=activation_id,
            activation_version=activation_version,
            subject=subject,
            approved_by=approved_by,
            issued_at=issued_at,
            valid_until=subject.valid_until,
        )

    def __post_init__(self) -> None:
        _token(self.activation_id, "activation_id")
        _token(self.activation_version, "activation_version")
        if type(self.subject) is not PolicyBenchmarkMethodologyActivationSubject:
            raise TypeError("subject must be an exact methodology activation subject")
        PolicyBenchmarkMethodologyActivationSubject.__post_init__(self.subject)
        if type(self.approved_by) is not PolicyBenchmarkMethodologyActivationActor:
            raise TypeError("approved_by must be an exact activation actor")
        PolicyBenchmarkMethodologyActivationActor.__post_init__(self.approved_by)
        if (
            self.approved_by.actor_id == self.subject.requested_by.actor_id
            or self.approved_by.user_id == self.subject.requested_by.user_id
        ):
            raise ValueError("methodology bundle activation forbids self approval")
        _aware(self.issued_at, "issued_at")
        _aware(self.valid_until, "valid_until")
        if self.valid_until != self.subject.valid_until:
            raise ValueError("activation validity must equal subject validity")
        if not self.subject.requested_at <= self.issued_at < self.valid_until:
            raise ValueError("activation issued outside its subject validity window")
        if (
            self.owner != POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_OWNER
            or self.capability != POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_CAPABILITY
            or self.artifact_type != POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_ARTIFACT_TYPE
            or self.schema != POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_SCHEMA
            or self.permission != POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_PERMISSION
            or self.clock_source != POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_CLOCK_SOURCE
        ):
            raise ValueError("methodology bundle activation authority is fixed")
        expected = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)
        elif _digest(self.content_hash, "content_hash") != expected:
            raise ValueError("methodology bundle activation content_hash is invalid")

    @property
    def must_not_execute(self) -> bool:
        """Remain true because bundle activation is never execution authority."""

        return True

    @property
    def activates_configuration_bundle(self) -> bool:
        """State that only the exact benchmark configuration bundle is activated."""

        return True

    @property
    def daily_valuation_authority(self) -> bool:
        """Remain false because daily valuation needs separate evidence and authority."""

        return False

    @property
    def broker_execution_authority(self) -> bool:
        """Remain false because this artifact cannot authorize broker execution."""

        return False

    def is_valid_at(self, as_of: datetime) -> bool:
        """Return whether this immutable activation is effective at a cutoff."""

        _aware(as_of, "as_of")
        return self.issued_at <= as_of < self.valid_until

    def _content_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "capability": self.capability,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "activation_id": self.activation_id,
            "activation_version": self.activation_version,
            "subject": self.subject.to_payload(),
            "approved_by": self.approved_by.to_payload(),
            "issued_at": _utc_text(self.issued_at),
            "valid_until": _utc_text(self.valid_until),
            "permission": self.permission,
            "clock_source": self.clock_source,
        }

    def to_payload(self) -> dict[str, object]:
        """Return activation data with explicit non-valuation/non-execution markers."""

        return {
            **self._content_payload(),
            "content_hash": self.content_hash,
            "activates_configuration_bundle": True,
            "daily_valuation_authority": False,
            "broker_execution_authority": False,
            "must_not_execute": True,
        }


def validate_policy_benchmark_methodology_activation_root(
    root: PolicyBenchmarkMethodologyBundleActivation,
) -> None:
    """Validate the first activation in a logical benchmark chain."""

    if type(root) is not PolicyBenchmarkMethodologyBundleActivation:
        raise TypeError("activation root must be an exact bundle activation")
    PolicyBenchmarkMethodologyBundleActivation.__post_init__(root)
    if root.subject.supersedes_activation_hash is not None:
        raise ValueError("activation root must not declare a predecessor")


def validate_policy_benchmark_methodology_activation_successor(
    previous: PolicyBenchmarkMethodologyBundleActivation,
    successor: PolicyBenchmarkMethodologyBundleActivation,
) -> None:
    """Validate one adjacent transition in a logical benchmark activation chain."""

    if (
        type(previous) is not PolicyBenchmarkMethodologyBundleActivation
        or type(successor) is not PolicyBenchmarkMethodologyBundleActivation
    ):
        raise TypeError("activation chain values must be exact bundle activations")
    PolicyBenchmarkMethodologyBundleActivation.__post_init__(previous)
    PolicyBenchmarkMethodologyBundleActivation.__post_init__(successor)
    if (
        previous.subject.definition_id != successor.subject.definition_id
        or previous.owner != successor.owner
        or previous.capability != successor.capability
        or previous.artifact_type != successor.artifact_type
    ):
        raise ValueError("activation successor changes its logical benchmark")
    if successor.subject.supersedes_activation_hash != previous.content_hash:
        raise ValueError("activation successor predecessor hash is invalid")
    if successor.subject.requested_at <= previous.issued_at:
        raise ValueError("activation successor request clock must advance")
    if successor.issued_at <= previous.issued_at:
        raise ValueError("activation successor issue clock must advance")


__all__ = [
    "POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_ARTIFACT_TYPE",
    "POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_CAPABILITY",
    "POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_CLOCK_SOURCE",
    "POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_OWNER",
    "POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_PERMISSION",
    "POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_SCHEMA",
    "PolicyBenchmarkMethodologyActivationActor",
    "PolicyBenchmarkMethodologyActivationSubject",
    "PolicyBenchmarkMethodologyBundle",
    "PolicyBenchmarkMethodologyBundleActivation",
    "validate_policy_benchmark_methodology_activation_root",
    "validate_policy_benchmark_methodology_activation_successor",
]
