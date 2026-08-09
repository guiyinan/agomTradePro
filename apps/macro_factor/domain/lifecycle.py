"""Hash-chained append-only retirement lifecycle for R3 run artifacts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import cast

from apps.macro_factor.domain.entities import (
    ExternalMacroFactorResearchResult,
    FactorLifecycleStatus,
    RetirementEvidence,
)

from ._runner_support import (
    canonical_json,
    decimal_text,
    hash_payload,
    require_aware,
    require_positive,
    require_sha256,
    require_token,
    utc_text,
)
from .dated_outputs import DatedMacroFactorOutput
from .run_artifacts import ReproducibleMacroFactorRunArtifact

RETIREMENT_OWNER_ATTESTATION_MEDIA_TYPE = (
    "application/vnd.agom.macro-factor.retirement-attestation+json"
)


@dataclass(frozen=True)
class RetirementOwnerAttestation:
    """Canonical bytes signed off by the governed retirement-policy owner."""

    attestation_id: str
    owner_ref: str
    artifact_id: str
    artifact_hash: str
    retirement_event_id: str
    policy_version: str
    retirement_evidence_hash: str
    issued_at: datetime
    artifact_bytes: bytes
    attestation_hash: str
    media_type: str = RETIREMENT_OWNER_ATTESTATION_MEDIA_TYPE

    @classmethod
    def create(
        cls,
        *,
        attestation_id: str,
        owner_ref: str,
        artifact_id: str,
        artifact_hash: str,
        retirement_event_id: str,
        policy_version: str,
        retirement_evidence_hash: str,
        issued_at: datetime,
    ) -> RetirementOwnerAttestation:
        """Create canonical owner-attestation bytes and their digest."""

        payload = cls._payload(
            attestation_id=attestation_id,
            owner_ref=owner_ref,
            artifact_id=artifact_id,
            artifact_hash=artifact_hash,
            retirement_event_id=retirement_event_id,
            policy_version=policy_version,
            retirement_evidence_hash=retirement_evidence_hash,
            issued_at=issued_at,
        )
        artifact_bytes = canonical_json(payload).encode("utf-8")
        return cls(
            attestation_id=attestation_id,
            owner_ref=owner_ref,
            artifact_id=artifact_id,
            artifact_hash=artifact_hash,
            retirement_event_id=retirement_event_id,
            policy_version=policy_version,
            retirement_evidence_hash=retirement_evidence_hash,
            issued_at=issued_at,
            artifact_bytes=artifact_bytes,
            attestation_hash=hashlib.sha256(artifact_bytes).hexdigest(),
        )

    @staticmethod
    def _payload(
        *,
        attestation_id: str,
        owner_ref: str,
        artifact_id: str,
        artifact_hash: str,
        retirement_event_id: str,
        policy_version: str,
        retirement_evidence_hash: str,
        issued_at: datetime,
    ) -> dict[str, str]:
        return {
            "attestation_id": attestation_id,
            "owner_ref": owner_ref,
            "artifact_id": artifact_id,
            "artifact_hash": artifact_hash,
            "retirement_event_id": retirement_event_id,
            "policy_version": policy_version,
            "retirement_evidence_hash": retirement_evidence_hash,
            "issued_at": utc_text(issued_at),
        }

    def __post_init__(self) -> None:
        for value, name in (
            (self.attestation_id, "attestation_id"),
            (self.owner_ref, "owner_ref"),
            (self.retirement_event_id, "retirement_event_id"),
            (self.policy_version, "policy_version"),
        ):
            require_token(value, f"RetirementOwnerAttestation.{name}")
        require_sha256(self.artifact_id, "RetirementOwnerAttestation.artifact_id")
        require_sha256(self.artifact_hash, "RetirementOwnerAttestation.artifact_hash")
        require_sha256(
            self.retirement_evidence_hash,
            "RetirementOwnerAttestation.retirement_evidence_hash",
        )
        require_sha256(self.attestation_hash, "RetirementOwnerAttestation.attestation_hash")
        require_aware(self.issued_at, "RetirementOwnerAttestation.issued_at")
        if self.media_type != RETIREMENT_OWNER_ATTESTATION_MEDIA_TYPE:
            raise ValueError("retirement owner attestation media_type is invalid")
        expected_bytes = canonical_json(
            self._payload(
                attestation_id=self.attestation_id,
                owner_ref=self.owner_ref,
                artifact_id=self.artifact_id,
                artifact_hash=self.artifact_hash,
                retirement_event_id=self.retirement_event_id,
                policy_version=self.policy_version,
                retirement_evidence_hash=self.retirement_evidence_hash,
                issued_at=self.issued_at,
            )
        ).encode("utf-8")
        if self.artifact_bytes != expected_bytes:
            raise ValueError("retirement owner attestation canonical bytes mismatch")
        if hashlib.sha256(self.artifact_bytes).hexdigest() != self.attestation_hash:
            raise ValueError("retirement owner attestation hash mismatch")


class MacroFactorLifecycleEventType(str, Enum):  # noqa: UP042 -- preserve string semantics
    """Append-only lifecycle event types for one run artifact."""

    RECORDED = "recorded"
    RETIRED = "retired"


@dataclass(frozen=True)
class MacroFactorLifecycleEvent:
    """Hash-chained lifecycle event; source rows are never updated."""

    event_id: str
    artifact_id: str
    artifact_hash: str
    factor_version: str
    event_type: MacroFactorLifecycleEventType
    sequence: int
    occurred_at: datetime
    recorded_at: datetime
    policy_version: str
    policy_hash: str
    reason_codes: tuple[str, ...]
    evidence_hash: str
    previous_event_hash: str | None
    owner_attestation_id: str | None
    owner_attestation_hash: str | None
    owner_attestation_owner_ref: str | None
    owner_attestation_media_type: str | None
    owner_attestation_content_length: int | None
    owner_attestation_issued_at: datetime | None
    owner_attestation_bytes: bytes | None = field(repr=False)
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        require_token(self.event_id, "MacroFactorLifecycleEvent.event_id")
        require_token(self.factor_version, "MacroFactorLifecycleEvent.factor_version")
        require_token(self.policy_version, "MacroFactorLifecycleEvent.policy_version")
        if not isinstance(self.event_type, MacroFactorLifecycleEventType):
            raise ValueError("MacroFactorLifecycleEvent.event_type is invalid")
        require_sha256(self.artifact_id, "MacroFactorLifecycleEvent.artifact_id")
        require_sha256(self.artifact_hash, "MacroFactorLifecycleEvent.artifact_hash")
        require_aware(self.occurred_at, "MacroFactorLifecycleEvent.occurred_at")
        require_aware(self.recorded_at, "MacroFactorLifecycleEvent.recorded_at")
        require_positive(self.sequence, "MacroFactorLifecycleEvent.sequence")
        if self.recorded_at < self.occurred_at:
            raise ValueError("lifecycle event recorded_at cannot precede occurred_at")
        if self.event_type is MacroFactorLifecycleEventType.RECORDED:
            if (
                self.sequence != 1
                or self.previous_event_hash is not None
                or self.owner_attestation_id is not None
                or self.owner_attestation_hash is not None
                or self.owner_attestation_owner_ref is not None
                or self.owner_attestation_media_type is not None
                or self.owner_attestation_content_length is not None
                or self.owner_attestation_issued_at is not None
                or self.owner_attestation_bytes is not None
            ):
                raise ValueError("recorded lifecycle event must be the chain root")
        elif (
            self.sequence <= 1
            or self.previous_event_hash is None
            or self.owner_attestation_id is None
            or self.owner_attestation_hash is None
            or self.owner_attestation_owner_ref is None
            or self.owner_attestation_media_type is None
            or self.owner_attestation_content_length is None
            or self.owner_attestation_issued_at is None
            or self.owner_attestation_bytes is None
        ):
            raise ValueError("retirement lifecycle event requires chain and owner attestation")
        if self.previous_event_hash is not None:
            require_sha256(self.previous_event_hash, "LifecycleEvent.previous_event_hash")
        require_sha256(self.policy_hash, "MacroFactorLifecycleEvent.policy_hash")
        require_sha256(self.evidence_hash, "MacroFactorLifecycleEvent.evidence_hash")
        if self.owner_attestation_id is not None:
            require_token(
                self.owner_attestation_id,
                "MacroFactorLifecycleEvent.owner_attestation_id",
            )
        if self.owner_attestation_hash is not None:
            issued_at = cast(datetime, self.owner_attestation_issued_at)
            require_sha256(
                self.owner_attestation_hash,
                "MacroFactorLifecycleEvent.owner_attestation_hash",
            )
            require_token(
                self.owner_attestation_owner_ref or "",
                "MacroFactorLifecycleEvent.owner_attestation_owner_ref",
            )
            require_aware(
                issued_at,
                "MacroFactorLifecycleEvent.owner_attestation_issued_at",
            )
            if (
                type(self.owner_attestation_content_length) is not int
                or self.owner_attestation_content_length <= 0
                or self.owner_attestation_content_length != len(self.owner_attestation_bytes or b"")
            ):
                raise ValueError("lifecycle owner attestation content length mismatch")
            RetirementOwnerAttestation(
                attestation_id=self.owner_attestation_id or "",
                owner_ref=self.owner_attestation_owner_ref or "",
                artifact_id=self.artifact_id,
                artifact_hash=self.artifact_hash,
                retirement_event_id=self.event_id,
                policy_version=self.policy_version,
                retirement_evidence_hash=self.evidence_hash,
                issued_at=issued_at,
                artifact_bytes=self.owner_attestation_bytes or b"",
                attestation_hash=self.owner_attestation_hash,
                media_type=self.owner_attestation_media_type or "",
            )
        if not self.reason_codes:
            raise ValueError("MacroFactorLifecycleEvent.reason_codes cannot be empty")
        for reason_code in self.reason_codes:
            require_token(reason_code, "MacroFactorLifecycleEvent.reason_code")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("MacroFactorLifecycleEvent.reason_codes must be unique")
        if not all((self.research_only, self.must_not_use_for_decision, self.must_not_execute)):
            raise ValueError("macro-factor lifecycle events must remain research-only and blocked")

    @property
    def canonical_payload(self) -> dict[str, object]:
        """Return stable chain content."""

        return {
            "event_id": self.event_id,
            "artifact_id": self.artifact_id,
            "artifact_hash": self.artifact_hash,
            "factor_version": self.factor_version,
            "event_type": self.event_type.value,
            "sequence": self.sequence,
            "occurred_at": utc_text(self.occurred_at),
            "recorded_at": utc_text(self.recorded_at),
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "reason_codes": list(self.reason_codes),
            "evidence_hash": self.evidence_hash,
            "previous_event_hash": self.previous_event_hash,
            "owner_attestation": (
                None
                if self.owner_attestation_id is None
                else {
                    "id": self.owner_attestation_id,
                    "hash": self.owner_attestation_hash,
                    "owner_ref": self.owner_attestation_owner_ref,
                    "media_type": self.owner_attestation_media_type,
                    "content_length": self.owner_attestation_content_length,
                    "issued_at": utc_text(cast(datetime, self.owner_attestation_issued_at)),
                }
            ),
            "research_only": self.research_only,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "must_not_execute": self.must_not_execute,
        }

    @property
    def canonical_json(self) -> str:
        """Return canonical JSON for persistence."""

        return canonical_json(self.canonical_payload)

    @property
    def content_hash(self) -> str:
        """Seal this lifecycle chain link."""

        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()


def retirement_policy_hash(result: ExternalMacroFactorResearchResult) -> str:
    """Seal the existing retirement policy without redefining its semantics."""

    policy = result.retirement_policy
    return hash_payload(
        {
            "policy_version": policy.policy_version,
            "owner_ref": policy.owner_ref,
            "evaluation_frequency": policy.evaluation_frequency,
            "retire_on_any": policy.retire_on_any,
            "rules": [
                {
                    "rule_id": rule.rule_id,
                    "metric_name": rule.metric_name,
                    "operator": rule.operator.value,
                    "threshold": decimal_text(rule.threshold),
                    "consecutive_windows": rule.consecutive_windows,
                    "observation_window": rule.observation_window,
                    "rationale": rule.rationale,
                }
                for rule in sorted(policy.rules, key=lambda item: item.rule_id)
            ],
        }
    )


def create_root_lifecycle_event(
    artifact: ReproducibleMacroFactorRunArtifact,
    source_result: ExternalMacroFactorResearchResult,
) -> MacroFactorLifecycleEvent:
    """Create the deterministic recorded root for a new run artifact."""

    return MacroFactorLifecycleEvent(
        event_id=f"record-{artifact.artifact_id}",
        artifact_id=artifact.artifact_id,
        artifact_hash=artifact.content_hash,
        factor_version=artifact.factor_version,
        event_type=MacroFactorLifecycleEventType.RECORDED,
        sequence=1,
        occurred_at=artifact.produced_at,
        recorded_at=artifact.produced_at,
        policy_version=source_result.retirement_policy.policy_version,
        policy_hash=retirement_policy_hash(source_result),
        reason_codes=("run_recorded",),
        evidence_hash=artifact.content_hash,
        previous_event_hash=None,
        owner_attestation_id=None,
        owner_attestation_hash=None,
        owner_attestation_owner_ref=None,
        owner_attestation_media_type=None,
        owner_attestation_content_length=None,
        owner_attestation_issued_at=None,
        owner_attestation_bytes=None,
    )


def append_retirement_event(
    *,
    artifact: ReproducibleMacroFactorRunArtifact,
    source_result: ExternalMacroFactorResearchResult,
    retirement: RetirementEvidence,
    owner_attestation: RetirementOwnerAttestation,
    previous_event: MacroFactorLifecycleEvent,
    recorded_at: datetime,
) -> MacroFactorLifecycleEvent:
    """Append retirement after validating the existing R3 retirement contract."""

    require_aware(recorded_at, "recorded_at")
    if source_result.result_id != artifact.source_result_id or (
        source_result.content_hash != artifact.source_result_hash
    ):
        raise ValueError("retirement source result does not match run artifact")
    if previous_event.artifact_id != artifact.artifact_id or (
        previous_event.artifact_hash != artifact.content_hash
    ):
        raise ValueError("retirement previous event does not match run artifact")
    if previous_event.event_type is MacroFactorLifecycleEventType.RETIRED:
        raise ValueError("macro-factor run is already retired")
    if retirement.retired_at < artifact.produced_at:
        raise ValueError("retirement cannot predate run artifact")
    replace(
        source_result,
        lifecycle_status=FactorLifecycleStatus.RETIRED,
        retirement_evidence=retirement,
    )
    if recorded_at < retirement.retired_at:
        raise ValueError("retirement recorded_at cannot predate retired_at")
    if (
        owner_attestation.owner_ref != source_result.retirement_policy.owner_ref
        or owner_attestation.artifact_id != artifact.artifact_id
        or owner_attestation.artifact_hash != artifact.content_hash
        or owner_attestation.retirement_event_id != retirement.event_id
        or owner_attestation.policy_version != retirement.policy_version
        or owner_attestation.retirement_evidence_hash != retirement.evidence_hash
    ):
        raise ValueError("retirement owner attestation does not match evidence")
    if not retirement.retired_at <= owner_attestation.issued_at <= recorded_at:
        raise ValueError("retirement owner attestation timeline is invalid")
    return MacroFactorLifecycleEvent(
        event_id=retirement.event_id,
        artifact_id=artifact.artifact_id,
        artifact_hash=artifact.content_hash,
        factor_version=artifact.factor_version,
        event_type=MacroFactorLifecycleEventType.RETIRED,
        sequence=previous_event.sequence + 1,
        occurred_at=retirement.retired_at,
        recorded_at=recorded_at,
        policy_version=retirement.policy_version,
        policy_hash=retirement_policy_hash(source_result),
        reason_codes=retirement.reason_codes,
        evidence_hash=retirement.evidence_hash,
        previous_event_hash=previous_event.content_hash,
        owner_attestation_id=owner_attestation.attestation_id,
        owner_attestation_hash=owner_attestation.attestation_hash,
        owner_attestation_owner_ref=owner_attestation.owner_ref,
        owner_attestation_media_type=owner_attestation.media_type,
        owner_attestation_content_length=len(owner_attestation.artifact_bytes),
        owner_attestation_issued_at=owner_attestation.issued_at,
        owner_attestation_bytes=owner_attestation.artifact_bytes,
    )


class MacroFactorOutputResearchStatus(str, Enum):  # noqa: UP042 -- preserve string semantics
    """Research-read status; every state remains decision/execution blocked."""

    AVAILABLE_FOR_RESEARCH = "available_for_research"
    STALE = "stale"
    RETIRED = "retired"


def validate_lifecycle_chain(
    artifact_id: str,
    artifact_hash: str,
    events: tuple[MacroFactorLifecycleEvent, ...],
) -> None:
    """Validate sequence, artifact identity, and every prior-event hash."""

    if not events or events[0].event_type is not MacroFactorLifecycleEventType.RECORDED:
        raise ValueError("lifecycle chain requires a recorded root")
    previous: MacroFactorLifecycleEvent | None = None
    retired_count = 0
    for expected_sequence, event in enumerate(events, 1):
        if event.sequence != expected_sequence:
            raise ValueError("lifecycle sequence is not contiguous")
        if event.artifact_id != artifact_id or event.artifact_hash != artifact_hash:
            raise ValueError("lifecycle event does not match artifact")
        if previous is None:
            if event.previous_event_hash is not None:
                raise ValueError("lifecycle root cannot reference a predecessor")
        elif event.previous_event_hash != previous.content_hash:
            raise ValueError("lifecycle hash chain is broken")
        if event.event_type is MacroFactorLifecycleEventType.RETIRED:
            retired_count += 1
        previous = event
    if retired_count > 1:
        raise ValueError("lifecycle chain cannot retire more than once")


def assess_output_research_status(
    output: DatedMacroFactorOutput,
    events: tuple[MacroFactorLifecycleEvent, ...],
    *,
    assessed_at: datetime,
) -> MacroFactorOutputResearchStatus:
    """Apply exact expiry and retirement while never authorizing a decision."""

    require_aware(assessed_at, "assessed_at")
    validate_lifecycle_chain(output.artifact_id, output.artifact_hash, events)
    if any(
        event.event_type is MacroFactorLifecycleEventType.RETIRED
        and event.occurred_at <= assessed_at
        for event in events
    ):
        return MacroFactorOutputResearchStatus.RETIRED
    if assessed_at >= output.valid_until:
        return MacroFactorOutputResearchStatus.STALE
    return MacroFactorOutputResearchStatus.AVAILABLE_FOR_RESEARCH


__all__ = [
    "MacroFactorLifecycleEvent",
    "MacroFactorLifecycleEventType",
    "MacroFactorOutputResearchStatus",
    "RETIREMENT_OWNER_ATTESTATION_MEDIA_TYPE",
    "RetirementOwnerAttestation",
    "append_retirement_event",
    "assess_output_research_status",
    "create_root_lifecycle_event",
    "retirement_policy_hash",
    "validate_lifecycle_chain",
]
