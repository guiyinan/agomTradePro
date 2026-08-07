"""Research-only promotion contract for published R2 market-structure evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from apps.data_center.domain.market_structure import (
    MARKET_STRUCTURE_CALENDAR_DATASET,
    MARKET_STRUCTURE_TAXONOMY_DATASET,
    ImmutableMarketStructureEvidence,
    MarketStructureResearchStatus,
)
from apps.fixed_income.domain.evidence import (
    canonical_hash,
    require_aware,
    require_sha256,
    require_token,
)


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


@dataclass(frozen=True)
class R2MarketStructurePromotionRef:
    """Exact ID/version reference used by caller-safe commands."""

    stable_id: str
    version: str

    def __post_init__(self) -> None:
        require_token(self.stable_id, "R2 promotion stable_id", maximum=200)
        require_token(self.version, "R2 promotion version", maximum=100)

    def to_payload(self) -> dict[str, str]:
        return {"stable_id": self.stable_id, "version": self.version}


@dataclass(frozen=True)
class R2MarketStructurePromotionScope:
    """Stable semantic scope for one descriptive R2 research lineage."""

    group_code: str
    group_revision: int
    method_version: str
    policy_code: str
    policy_version: int
    scope_id: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        group_code: str,
        group_revision: int,
        method_version: str,
        policy_code: str,
        policy_version: int,
    ) -> R2MarketStructurePromotionScope:
        payload = {
            "group_code": group_code,
            "group_revision": group_revision,
            "method_version": method_version,
            "policy_code": policy_code,
            "policy_version": policy_version,
            "schema": "research-r2-market-structure-promotion-scope.v1",
        }
        digest = canonical_hash(payload)
        return cls(
            group_code=group_code,
            group_revision=group_revision,
            method_version=method_version,
            policy_code=policy_code,
            policy_version=policy_version,
            scope_id=f"r2-ms-scope-{digest}",
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        for value, label in (
            (self.group_code, "group_code"),
            (self.method_version, "method_version"),
            (self.policy_code, "policy_code"),
            (self.scope_id, "scope_id"),
        ):
            require_token(value, f"R2 promotion scope {label}", maximum=200)
        if self.group_revision <= 0 or self.policy_version <= 0:
            raise ValueError("R2 promotion scope versions must be positive")
        require_sha256(self.content_hash, "R2 promotion scope content_hash")
        expected_hash = canonical_hash(
            {
                "group_code": self.group_code,
                "group_revision": self.group_revision,
                "method_version": self.method_version,
                "policy_code": self.policy_code,
                "policy_version": self.policy_version,
                "schema": "research-r2-market-structure-promotion-scope.v1",
            }
        )
        if self.scope_id != f"r2-ms-scope-{expected_hash}" or self.content_hash != expected_hash:
            raise ValueError("R2 promotion scope identity or hash mismatch")

    def to_payload(self) -> dict[str, object]:
        return {
            "content_hash": self.content_hash,
            "group_code": self.group_code,
            "group_revision": self.group_revision,
            "method_version": self.method_version,
            "policy_code": self.policy_code,
            "policy_version": self.policy_version,
            "scope_id": self.scope_id,
        }


@dataclass(frozen=True)
class R2MarketStructureEvidenceSeal:
    """Minimal exact seal over one Data Center-owned published R2 result."""

    evidence_key: str
    evidence_version: int
    evidence_hash: str
    input_hash: str
    output_hash: str
    scope: R2MarketStructurePromotionScope
    as_of_time: datetime
    publication_ids: tuple[str, ...]
    publication_hashes: tuple[str, ...]
    publication_datasets: tuple[str, ...]
    content_hash: str

    @classmethod
    def from_evidence(
        cls,
        evidence: ImmutableMarketStructureEvidence,
    ) -> R2MarketStructureEvidenceSeal:
        if evidence.status is not MarketStructureResearchStatus.AVAILABLE:
            raise ValueError("R2 promotion evidence must be available")
        if (
            not evidence.research_only
            or not evidence.must_not_use_for_decision
            or not evidence.must_not_execute
        ):
            raise ValueError("R2 promotion evidence safety flags were weakened")
        publications = evidence.governance_publications
        datasets = tuple(sorted({item.dataset_key for item in publications}))
        if datasets != tuple(
            sorted(
                (
                    MARKET_STRUCTURE_CALENDAR_DATASET,
                    MARKET_STRUCTURE_TAXONOMY_DATASET,
                )
            )
        ):
            raise ValueError("R2 promotion evidence lacks exact taxonomy/calendar Publication")
        publication_pairs = tuple(
            sorted({(item.publication_id, item.publication_hash) for item in publications})
        )
        scope = R2MarketStructurePromotionScope.create(
            group_code=evidence.group_code,
            group_revision=evidence.group_revision,
            method_version=evidence.method_version,
            policy_code=evidence.policy_code,
            policy_version=evidence.policy_version,
        )
        values: dict[str, object] = {
            "as_of_time": _utc_iso(evidence.as_of_time),
            "evidence_hash": evidence.evidence_hash,
            "evidence_key": evidence.evidence_key,
            "evidence_version": evidence.evidence_version,
            "input_hash": evidence.input_hash,
            "output_hash": evidence.output_hash,
            "publication_datasets": datasets,
            "publication_hashes": tuple(item[1] for item in publication_pairs),
            "publication_ids": tuple(item[0] for item in publication_pairs),
            "schema": "research-r2-market-structure-evidence-seal.v1",
            "scope": scope.to_payload(),
        }
        return cls(
            evidence_key=evidence.evidence_key,
            evidence_version=evidence.evidence_version,
            evidence_hash=evidence.evidence_hash,
            input_hash=evidence.input_hash,
            output_hash=evidence.output_hash,
            scope=scope,
            as_of_time=evidence.as_of_time,
            publication_ids=tuple(item[0] for item in publication_pairs),
            publication_hashes=tuple(item[1] for item in publication_pairs),
            publication_datasets=datasets,
            content_hash=canonical_hash(values),
        )

    def __post_init__(self) -> None:
        require_token(self.evidence_key, "R2 evidence seal key", maximum=128)
        if self.evidence_version <= 0:
            raise ValueError("R2 evidence seal version must be positive")
        for value, label in (
            (self.evidence_hash, "evidence_hash"),
            (self.input_hash, "input_hash"),
            (self.output_hash, "output_hash"),
            (self.content_hash, "content_hash"),
        ):
            require_sha256(value, f"R2 evidence seal {label}")
        require_aware(self.as_of_time, "R2 evidence seal as_of_time")
        if (
            not self.publication_ids
            or len(self.publication_ids) != len(self.publication_hashes)
            or tuple(sorted(set(self.publication_ids))) != self.publication_ids
        ):
            raise ValueError("R2 evidence seal Publication identities are invalid")
        for value in self.publication_hashes:
            require_sha256(value, "R2 evidence seal publication_hash")
        if tuple(sorted(set(self.publication_datasets))) != self.publication_datasets:
            raise ValueError("R2 evidence seal Publication datasets are invalid")

    @property
    def reference(self) -> R2MarketStructurePromotionRef:
        return R2MarketStructurePromotionRef(self.evidence_key, str(self.evidence_version))

    def to_payload(self) -> dict[str, object]:
        return {
            "as_of_time": _utc_iso(self.as_of_time),
            "content_hash": self.content_hash,
            "evidence_hash": self.evidence_hash,
            "evidence_key": self.evidence_key,
            "evidence_version": self.evidence_version,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "publication_datasets": self.publication_datasets,
            "publication_hashes": self.publication_hashes,
            "publication_ids": self.publication_ids,
            "scope": self.scope.to_payload(),
        }


@dataclass(frozen=True)
class R2MarketStructurePromotionPolicy:
    """Owner-approved, pre-registered policy for descriptive evidence only."""

    policy_id: str
    policy_version: str
    scope: R2MarketStructurePromotionScope
    required_publication_datasets: tuple[str, ...]
    owner_approval_ref: str
    owner_approval_hash: str
    registered_at: datetime
    active_from: datetime
    valid_until: datetime
    content_hash: str
    research_only: bool = True
    structure_description_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        policy_version: str,
        scope: R2MarketStructurePromotionScope,
        owner_approval_ref: str,
        owner_approval_hash: str,
        registered_at: datetime,
        active_from: datetime,
        valid_until: datetime,
    ) -> R2MarketStructurePromotionPolicy:
        required = tuple(
            sorted(
                (
                    MARKET_STRUCTURE_CALENDAR_DATASET,
                    MARKET_STRUCTURE_TAXONOMY_DATASET,
                )
            )
        )
        payload: dict[str, object] = {
            "active_from": _utc_iso(active_from),
            "must_not_execute": True,
            "must_not_use_for_decision": True,
            "owner_approval_hash": owner_approval_hash,
            "owner_approval_ref": owner_approval_ref,
            "policy_version": policy_version,
            "registered_at": _utc_iso(registered_at),
            "required_publication_datasets": required,
            "research_only": True,
            "schema": "research-r2-market-structure-promotion-policy.v1",
            "scope": scope.to_payload(),
            "structure_description_only": True,
            "valid_until": _utc_iso(valid_until),
        }
        digest = canonical_hash(payload)
        return cls(
            policy_id=f"r2-ms-policy-{digest}",
            policy_version=policy_version,
            scope=scope,
            required_publication_datasets=required,
            owner_approval_ref=owner_approval_ref,
            owner_approval_hash=owner_approval_hash,
            registered_at=registered_at,
            active_from=active_from,
            valid_until=valid_until,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        require_token(self.policy_id, "R2 promotion policy_id", maximum=200)
        require_token(self.policy_version, "R2 promotion policy_version", maximum=100)
        require_token(self.owner_approval_ref, "R2 promotion owner approval ref", maximum=300)
        require_sha256(self.owner_approval_hash, "R2 promotion owner approval hash")
        require_sha256(self.content_hash, "R2 promotion policy content_hash")
        for value, label in (
            (self.registered_at, "registered_at"),
            (self.active_from, "active_from"),
            (self.valid_until, "valid_until"),
        ):
            require_aware(value, f"R2 promotion policy {label}")
        if not self.registered_at <= self.active_from < self.valid_until:
            raise ValueError("R2 promotion policy clocks are invalid")
        expected_datasets = tuple(
            sorted(
                (
                    MARKET_STRUCTURE_CALENDAR_DATASET,
                    MARKET_STRUCTURE_TAXONOMY_DATASET,
                )
            )
        )
        if self.required_publication_datasets != expected_datasets:
            raise ValueError("R2 promotion policy must require taxonomy and calendar Publication")
        if not all(
            (
                self.research_only,
                self.structure_description_only,
                self.must_not_use_for_decision,
                self.must_not_execute,
            )
        ):
            raise ValueError("R2 promotion policy safety flags cannot be weakened")
        expected_hash = canonical_hash(
            {
                "active_from": _utc_iso(self.active_from),
                "must_not_execute": self.must_not_execute,
                "must_not_use_for_decision": self.must_not_use_for_decision,
                "owner_approval_hash": self.owner_approval_hash,
                "owner_approval_ref": self.owner_approval_ref,
                "policy_version": self.policy_version,
                "registered_at": _utc_iso(self.registered_at),
                "required_publication_datasets": self.required_publication_datasets,
                "research_only": self.research_only,
                "schema": "research-r2-market-structure-promotion-policy.v1",
                "scope": self.scope.to_payload(),
                "structure_description_only": self.structure_description_only,
                "valid_until": _utc_iso(self.valid_until),
            }
        )
        if self.policy_id != f"r2-ms-policy-{expected_hash}" or self.content_hash != expected_hash:
            raise ValueError("R2 promotion policy identity or hash mismatch")

    def is_active_at(self, as_of: datetime) -> bool:
        require_aware(as_of, "R2 promotion policy as_of")
        return self.active_from <= as_of < self.valid_until

    @property
    def reference(self) -> R2MarketStructurePromotionRef:
        return R2MarketStructurePromotionRef(self.policy_id, self.policy_version)

    def to_payload(self) -> dict[str, object]:
        return {
            "active_from": _utc_iso(self.active_from),
            "content_hash": self.content_hash,
            "must_not_execute": self.must_not_execute,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "owner_approval_hash": self.owner_approval_hash,
            "owner_approval_ref": self.owner_approval_ref,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "registered_at": _utc_iso(self.registered_at),
            "required_publication_datasets": self.required_publication_datasets,
            "research_only": self.research_only,
            "scope": self.scope.to_payload(),
            "structure_description_only": self.structure_description_only,
            "valid_until": _utc_iso(self.valid_until),
        }


class R2MarketStructurePromotionDecisionOutcome(str, Enum):
    """Derived promotion outcome."""

    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class R2MarketStructureDecisionAuthorization:
    """Exact Research owner receipt for one policy/evidence evaluation."""

    authorization_id: str
    authorization_version: str
    policy_ref: R2MarketStructurePromotionRef
    policy_content_hash: str
    evidence_ref: R2MarketStructurePromotionRef
    evidence_content_hash: str
    scope_id: str
    scope_content_hash: str
    issued_at: datetime
    decided_at: datetime
    decision_recorded_at: datetime
    valid_until: datetime
    owner_receipt_hash: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        authorization_version: str,
        policy: R2MarketStructurePromotionPolicy,
        evidence: R2MarketStructureEvidenceSeal,
        issued_at: datetime,
        decided_at: datetime,
        decision_recorded_at: datetime,
        valid_until: datetime,
        owner_receipt_hash: str,
    ) -> R2MarketStructureDecisionAuthorization:
        payload: dict[str, object] = {
            "authorization_version": authorization_version,
            "decided_at": _utc_iso(decided_at),
            "decision_recorded_at": _utc_iso(decision_recorded_at),
            "evidence_content_hash": evidence.content_hash,
            "evidence_ref": evidence.reference.to_payload(),
            "issued_at": _utc_iso(issued_at),
            "owner_receipt_hash": owner_receipt_hash,
            "policy_content_hash": policy.content_hash,
            "policy_ref": policy.reference.to_payload(),
            "schema": "research-r2-market-structure-decision-authorization.v1",
            "scope_content_hash": policy.scope.content_hash,
            "scope_id": policy.scope.scope_id,
            "valid_until": _utc_iso(valid_until),
        }
        digest = canonical_hash(payload)
        return cls(
            authorization_id=f"r2-ms-decision-auth-{digest}",
            authorization_version=authorization_version,
            policy_ref=policy.reference,
            policy_content_hash=policy.content_hash,
            evidence_ref=evidence.reference,
            evidence_content_hash=evidence.content_hash,
            scope_id=policy.scope.scope_id,
            scope_content_hash=policy.scope.content_hash,
            issued_at=issued_at,
            decided_at=decided_at,
            decision_recorded_at=decision_recorded_at,
            valid_until=valid_until,
            owner_receipt_hash=owner_receipt_hash,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        require_token(self.authorization_id, "R2 decision authorization_id", maximum=200)
        require_token(
            self.authorization_version,
            "R2 decision authorization_version",
            maximum=100,
        )
        require_token(self.scope_id, "R2 decision authorization scope_id", maximum=200)
        for value, label in (
            (self.policy_content_hash, "policy_content_hash"),
            (self.evidence_content_hash, "evidence_content_hash"),
            (self.scope_content_hash, "scope_content_hash"),
            (self.owner_receipt_hash, "owner_receipt_hash"),
            (self.content_hash, "content_hash"),
        ):
            require_sha256(value, f"R2 decision authorization {label}")
        for clock_value, label in (
            (self.issued_at, "issued_at"),
            (self.decided_at, "decided_at"),
            (self.decision_recorded_at, "decision_recorded_at"),
            (self.valid_until, "valid_until"),
        ):
            require_aware(clock_value, f"R2 decision authorization {label}")
        if not self.issued_at <= self.decided_at <= self.decision_recorded_at < self.valid_until:
            raise ValueError("R2 decision authorization clocks are invalid")

    @property
    def reference(self) -> R2MarketStructurePromotionRef:
        return R2MarketStructurePromotionRef(
            self.authorization_id,
            self.authorization_version,
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "authorization_id": self.authorization_id,
            "authorization_version": self.authorization_version,
            "content_hash": self.content_hash,
            "decided_at": _utc_iso(self.decided_at),
            "decision_recorded_at": _utc_iso(self.decision_recorded_at),
            "evidence_content_hash": self.evidence_content_hash,
            "evidence_ref": self.evidence_ref.to_payload(),
            "issued_at": _utc_iso(self.issued_at),
            "owner_receipt_hash": self.owner_receipt_hash,
            "policy_content_hash": self.policy_content_hash,
            "policy_ref": self.policy_ref.to_payload(),
            "scope_content_hash": self.scope_content_hash,
            "scope_id": self.scope_id,
            "valid_until": _utc_iso(self.valid_until),
        }


@dataclass(frozen=True)
class R2MarketStructurePromotionDecision:
    """Derived, exact and permanently non-decision R2 promotion result."""

    decision_id: str
    decision_version: str
    outcome: R2MarketStructurePromotionDecisionOutcome
    policy: R2MarketStructurePromotionPolicy
    evidence: R2MarketStructureEvidenceSeal
    authorization: R2MarketStructureDecisionAuthorization
    decided_at: datetime
    recorded_at: datetime
    valid_until: datetime
    reason_codes: tuple[str, ...]
    content_hash: str
    research_only: bool = True
    structure_description_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        require_token(self.decision_id, "R2 promotion decision_id", maximum=200)
        require_token(self.decision_version, "R2 promotion decision_version", maximum=100)
        require_sha256(self.content_hash, "R2 promotion decision content_hash")
        if self.policy.scope != self.evidence.scope:
            raise ValueError("R2 promotion decision crosses semantic scopes")
        authorization = self.authorization
        if (
            authorization.policy_ref != self.policy.reference
            or authorization.policy_content_hash != self.policy.content_hash
            or authorization.evidence_ref != self.evidence.reference
            or authorization.evidence_content_hash != self.evidence.content_hash
            or authorization.scope_id != self.policy.scope.scope_id
            or authorization.scope_content_hash != self.policy.scope.content_hash
        ):
            raise ValueError("R2 promotion decision authorization was substituted")
        if (
            authorization.decided_at != self.decided_at
            or authorization.decision_recorded_at != self.recorded_at
            or not self.decided_at <= self.recorded_at < self.valid_until
            or self.valid_until != min(self.policy.valid_until, authorization.valid_until)
        ):
            raise ValueError("R2 promotion decision clocks were substituted")
        expected_outcome = (
            R2MarketStructurePromotionDecisionOutcome.APPROVED
            if self.evidence.publication_datasets == self.policy.required_publication_datasets
            and self.policy.is_active_at(self.decided_at)
            else R2MarketStructurePromotionDecisionOutcome.REJECTED
        )
        if self.outcome is not expected_outcome:
            raise ValueError("R2 promotion decision outcome was not derived")
        expected_reasons = (
            ("r2_market_structure_published_evidence_approved",)
            if expected_outcome is R2MarketStructurePromotionDecisionOutcome.APPROVED
            else ("r2_market_structure_promotion_policy_failed",)
        )
        if self.reason_codes != expected_reasons:
            raise ValueError("R2 promotion decision reasons were not derived")
        if not all(
            (
                self.research_only,
                self.structure_description_only,
                self.must_not_use_for_decision,
                self.must_not_execute,
            )
        ):
            raise ValueError("R2 promotion decision safety flags cannot be weakened")

    @property
    def reference(self) -> R2MarketStructurePromotionRef:
        return R2MarketStructurePromotionRef(self.decision_id, self.decision_version)

    def is_active_at(self, as_of: datetime) -> bool:
        require_aware(as_of, "R2 promotion decision as_of")
        return self.recorded_at <= as_of < self.valid_until

    def to_payload(self) -> dict[str, object]:
        return {
            "authorization": self.authorization.to_payload(),
            "content_hash": self.content_hash,
            "decided_at": _utc_iso(self.decided_at),
            "decision_id": self.decision_id,
            "decision_version": self.decision_version,
            "evidence": self.evidence.to_payload(),
            "must_not_execute": self.must_not_execute,
            "must_not_use_for_decision": self.must_not_use_for_decision,
            "outcome": self.outcome.value,
            "policy": self.policy.to_payload(),
            "reason_codes": self.reason_codes,
            "recorded_at": _utc_iso(self.recorded_at),
            "research_only": self.research_only,
            "structure_description_only": self.structure_description_only,
            "valid_until": _utc_iso(self.valid_until),
        }


def create_r2_market_structure_promotion_decision(
    *,
    policy: R2MarketStructurePromotionPolicy,
    evidence: R2MarketStructureEvidenceSeal,
    authorization: R2MarketStructureDecisionAuthorization,
) -> R2MarketStructurePromotionDecision:
    """Derive the only allowed decision from exact owner evidence."""

    outcome = (
        R2MarketStructurePromotionDecisionOutcome.APPROVED
        if evidence.publication_datasets == policy.required_publication_datasets
        and policy.is_active_at(authorization.decided_at)
        else R2MarketStructurePromotionDecisionOutcome.REJECTED
    )
    reasons = (
        ("r2_market_structure_published_evidence_approved",)
        if outcome is R2MarketStructurePromotionDecisionOutcome.APPROVED
        else ("r2_market_structure_promotion_policy_failed",)
    )
    decision_version = "r2-market-structure-promotion-decision.v1"
    valid_until = min(policy.valid_until, authorization.valid_until)
    payload: dict[str, object] = {
        "authorization": authorization.to_payload(),
        "decided_at": _utc_iso(authorization.decided_at),
        "decision_version": decision_version,
        "evidence": evidence.to_payload(),
        "must_not_execute": True,
        "must_not_use_for_decision": True,
        "outcome": outcome.value,
        "policy": policy.to_payload(),
        "reason_codes": reasons,
        "recorded_at": _utc_iso(authorization.decision_recorded_at),
        "research_only": True,
        "schema": "research-r2-market-structure-promotion-decision.v1",
        "structure_description_only": True,
        "valid_until": _utc_iso(valid_until),
    }
    digest = canonical_hash(payload)
    return R2MarketStructurePromotionDecision(
        decision_id=f"r2-ms-decision-{digest}",
        decision_version=decision_version,
        outcome=outcome,
        policy=policy,
        evidence=evidence,
        authorization=authorization,
        decided_at=authorization.decided_at,
        recorded_at=authorization.decision_recorded_at,
        valid_until=valid_until,
        reason_codes=reasons,
        content_hash=digest,
    )


class R2MarketStructureLifecycleAction(str, Enum):
    """Caller-safe lifecycle actions."""

    PROMOTE = "promote"
    RETIRE = "retire"
    ROLLBACK = "rollback"


class R2MarketStructureLifecycleEventType(str, Enum):
    """Persisted lifecycle event types."""

    PROMOTED = "promoted"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True)
class R2MarketStructureLifecycleAuthorization:
    """Exact owner authorization for one lifecycle transition."""

    authorization_id: str
    authorization_version: str
    scope_id: str
    scope_content_hash: str
    action: R2MarketStructureLifecycleAction
    decision_ref: R2MarketStructurePromotionRef
    decision_content_hash: str
    rollback_target_ref: R2MarketStructurePromotionRef | None
    rollback_target_content_hash: str
    issued_at: datetime
    occurred_at: datetime
    event_recorded_at: datetime
    valid_until: datetime
    reason_codes: tuple[str, ...]
    owner_receipt_hash: str
    content_hash: str

    @property
    def reference(self) -> R2MarketStructurePromotionRef:
        return R2MarketStructurePromotionRef(
            self.authorization_id,
            self.authorization_version,
        )

    def __post_init__(self) -> None:
        require_token(self.authorization_id, "R2 lifecycle authorization_id", maximum=200)
        require_token(
            self.authorization_version,
            "R2 lifecycle authorization_version",
            maximum=100,
        )
        require_token(self.scope_id, "R2 lifecycle scope_id", maximum=200)
        for value, label in (
            (self.scope_content_hash, "scope_content_hash"),
            (self.decision_content_hash, "decision_content_hash"),
            (self.owner_receipt_hash, "owner_receipt_hash"),
            (self.content_hash, "content_hash"),
        ):
            require_sha256(value, f"R2 lifecycle authorization {label}")
        if self.rollback_target_ref is None:
            if self.rollback_target_content_hash:
                raise ValueError("R2 lifecycle non-rollback cannot bind a target hash")
        else:
            require_sha256(
                self.rollback_target_content_hash,
                "R2 lifecycle rollback_target_content_hash",
            )
        if (self.action is R2MarketStructureLifecycleAction.ROLLBACK) != (
            self.rollback_target_ref is not None
        ):
            raise ValueError("R2 lifecycle rollback target/action mismatch")
        for clock_value, label in (
            (self.issued_at, "issued_at"),
            (self.occurred_at, "occurred_at"),
            (self.event_recorded_at, "event_recorded_at"),
            (self.valid_until, "valid_until"),
        ):
            require_aware(clock_value, f"R2 lifecycle authorization {label}")
        if not self.issued_at <= self.occurred_at <= self.event_recorded_at < self.valid_until:
            raise ValueError("R2 lifecycle authorization clocks are invalid")
        if not self.reason_codes or tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("R2 lifecycle reasons must be unique and ordered")

    def to_payload(self) -> dict[str, object]:
        return {
            "action": self.action.value,
            "authorization_id": self.authorization_id,
            "authorization_version": self.authorization_version,
            "content_hash": self.content_hash,
            "decision_content_hash": self.decision_content_hash,
            "decision_ref": self.decision_ref.to_payload(),
            "event_recorded_at": _utc_iso(self.event_recorded_at),
            "issued_at": _utc_iso(self.issued_at),
            "occurred_at": _utc_iso(self.occurred_at),
            "owner_receipt_hash": self.owner_receipt_hash,
            "reason_codes": self.reason_codes,
            "rollback_target_content_hash": self.rollback_target_content_hash,
            "rollback_target_ref": (
                None if self.rollback_target_ref is None else self.rollback_target_ref.to_payload()
            ),
            "scope_content_hash": self.scope_content_hash,
            "scope_id": self.scope_id,
            "valid_until": _utc_iso(self.valid_until),
        }


def create_r2_market_structure_lifecycle_authorization(
    *,
    authorization_version: str,
    scope: R2MarketStructurePromotionScope,
    action: R2MarketStructureLifecycleAction,
    decision: R2MarketStructurePromotionDecision,
    rollback_target: R2MarketStructurePromotionDecision | None,
    issued_at: datetime,
    occurred_at: datetime,
    event_recorded_at: datetime,
    valid_until: datetime,
    reason_codes: tuple[str, ...],
    owner_receipt_hash: str,
) -> R2MarketStructureLifecycleAuthorization:
    """Create a hash-sealed owner transition authorization."""

    target_ref = None if rollback_target is None else rollback_target.reference
    target_hash = "" if rollback_target is None else rollback_target.content_hash
    payload: dict[str, object] = {
        "action": action.value,
        "authorization_version": authorization_version,
        "decision_content_hash": decision.content_hash,
        "decision_ref": decision.reference.to_payload(),
        "event_recorded_at": _utc_iso(event_recorded_at),
        "issued_at": _utc_iso(issued_at),
        "occurred_at": _utc_iso(occurred_at),
        "owner_receipt_hash": owner_receipt_hash,
        "reason_codes": reason_codes,
        "rollback_target_content_hash": target_hash,
        "rollback_target_ref": None if target_ref is None else target_ref.to_payload(),
        "schema": "research-r2-market-structure-lifecycle-authorization.v1",
        "scope_content_hash": scope.content_hash,
        "scope_id": scope.scope_id,
        "valid_until": _utc_iso(valid_until),
    }
    digest = canonical_hash(payload)
    return R2MarketStructureLifecycleAuthorization(
        authorization_id=f"r2-ms-lifecycle-auth-{digest}",
        authorization_version=authorization_version,
        scope_id=scope.scope_id,
        scope_content_hash=scope.content_hash,
        action=action,
        decision_ref=decision.reference,
        decision_content_hash=decision.content_hash,
        rollback_target_ref=target_ref,
        rollback_target_content_hash=target_hash,
        issued_at=issued_at,
        occurred_at=occurred_at,
        event_recorded_at=event_recorded_at,
        valid_until=valid_until,
        reason_codes=reason_codes,
        owner_receipt_hash=owner_receipt_hash,
        content_hash=digest,
    )


@dataclass(frozen=True)
class R2MarketStructureLifecycleEvent:
    """One immutable event in a scope-local promotion stack."""

    event_id: str
    event_version: str
    scope_id: str
    scope_content_hash: str
    stream_id: str
    sequence: int
    event_type: R2MarketStructureLifecycleEventType
    decision_ref: R2MarketStructurePromotionRef
    decision_content_hash: str
    rollback_target_ref: R2MarketStructurePromotionRef | None
    rollback_target_content_hash: str
    authorization: R2MarketStructureLifecycleAuthorization
    previous_event_hash: str
    occurred_at: datetime
    recorded_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        require_token(self.event_id, "R2 lifecycle event_id", maximum=200)
        require_token(self.event_version, "R2 lifecycle event_version", maximum=100)
        require_token(self.scope_id, "R2 lifecycle event scope_id", maximum=200)
        require_token(self.stream_id, "R2 lifecycle stream_id", maximum=300)
        if self.sequence <= 0:
            raise ValueError("R2 lifecycle sequence must be positive")
        for value, label in (
            (self.scope_content_hash, "scope_content_hash"),
            (self.decision_content_hash, "decision_content_hash"),
            (self.content_hash, "content_hash"),
        ):
            require_sha256(value, f"R2 lifecycle event {label}")
        if self.previous_event_hash:
            require_sha256(self.previous_event_hash, "R2 lifecycle previous_event_hash")
        if self.sequence == 1 and self.previous_event_hash:
            raise ValueError("R2 lifecycle root cannot reference a previous event")
        if self.sequence > 1 and not self.previous_event_hash:
            raise ValueError("R2 lifecycle non-root requires a previous event hash")
        if (self.event_type is R2MarketStructureLifecycleEventType.ROLLED_BACK) != (
            self.rollback_target_ref is not None
        ):
            raise ValueError("R2 lifecycle event rollback target mismatch")
        if self.rollback_target_ref is None:
            if self.rollback_target_content_hash:
                raise ValueError("R2 lifecycle non-rollback target hash is invalid")
        else:
            require_sha256(
                self.rollback_target_content_hash,
                "R2 lifecycle rollback target hash",
            )
        require_aware(self.occurred_at, "R2 lifecycle occurred_at")
        require_aware(self.recorded_at, "R2 lifecycle recorded_at")
        if self.occurred_at > self.recorded_at:
            raise ValueError("R2 lifecycle occurred_at exceeds recorded_at")
        expected_action = {
            R2MarketStructureLifecycleEventType.PROMOTED: R2MarketStructureLifecycleAction.PROMOTE,
            R2MarketStructureLifecycleEventType.RETIRED: R2MarketStructureLifecycleAction.RETIRE,
            R2MarketStructureLifecycleEventType.ROLLED_BACK: R2MarketStructureLifecycleAction.ROLLBACK,
        }[self.event_type]
        authorization = self.authorization
        if (
            authorization.action is not expected_action
            or authorization.scope_id != self.scope_id
            or authorization.scope_content_hash != self.scope_content_hash
            or authorization.decision_ref != self.decision_ref
            or authorization.decision_content_hash != self.decision_content_hash
            or authorization.rollback_target_ref != self.rollback_target_ref
            or authorization.rollback_target_content_hash != self.rollback_target_content_hash
            or authorization.occurred_at != self.occurred_at
            or authorization.event_recorded_at != self.recorded_at
        ):
            raise ValueError("R2 lifecycle authorization/event mismatch")

    def to_payload(self) -> dict[str, object]:
        return {
            "authorization": self.authorization.to_payload(),
            "content_hash": self.content_hash,
            "decision_content_hash": self.decision_content_hash,
            "decision_ref": self.decision_ref.to_payload(),
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "event_version": self.event_version,
            "occurred_at": _utc_iso(self.occurred_at),
            "previous_event_hash": self.previous_event_hash,
            "recorded_at": _utc_iso(self.recorded_at),
            "rollback_target_content_hash": self.rollback_target_content_hash,
            "rollback_target_ref": (
                None if self.rollback_target_ref is None else self.rollback_target_ref.to_payload()
            ),
            "scope_content_hash": self.scope_content_hash,
            "scope_id": self.scope_id,
            "sequence": self.sequence,
            "stream_id": self.stream_id,
        }


def create_r2_market_structure_lifecycle_event(
    *,
    history: tuple[R2MarketStructureLifecycleEvent, ...],
    decision: R2MarketStructurePromotionDecision,
    authorization: R2MarketStructureLifecycleAuthorization,
    rollback_target: R2MarketStructurePromotionDecision | None,
) -> R2MarketStructureLifecycleEvent:
    """Create a transition only after replaying the complete scope stack."""

    derive_r2_market_structure_active_stack(history)
    sequence = len(history) + 1
    previous_hash = history[-1].content_hash if history else ""
    event_type = {
        R2MarketStructureLifecycleAction.PROMOTE: R2MarketStructureLifecycleEventType.PROMOTED,
        R2MarketStructureLifecycleAction.RETIRE: R2MarketStructureLifecycleEventType.RETIRED,
        R2MarketStructureLifecycleAction.ROLLBACK: R2MarketStructureLifecycleEventType.ROLLED_BACK,
    }[authorization.action]
    target_ref = None if rollback_target is None else rollback_target.reference
    target_hash = "" if rollback_target is None else rollback_target.content_hash
    if authorization.scope_id != decision.policy.scope.scope_id:
        raise ValueError("R2 lifecycle decision crosses authorization scope")
    if authorization.decision_ref != decision.reference:
        raise ValueError("R2 lifecycle authorization references another decision")
    if authorization.decision_content_hash != decision.content_hash:
        raise ValueError("R2 lifecycle decision hash was substituted")
    if authorization.rollback_target_ref != target_ref:
        raise ValueError("R2 lifecycle rollback target reference was substituted")
    if authorization.rollback_target_content_hash != target_hash:
        raise ValueError("R2 lifecycle rollback target hash was substituted")
    event_version = "r2-market-structure-lifecycle-event.v1"
    stream_id = f"research:r2:market-structure:{authorization.scope_id}"
    payload: dict[str, object] = {
        "authorization": authorization.to_payload(),
        "decision_content_hash": decision.content_hash,
        "decision_ref": decision.reference.to_payload(),
        "event_type": event_type.value,
        "event_version": event_version,
        "occurred_at": _utc_iso(authorization.occurred_at),
        "previous_event_hash": previous_hash,
        "recorded_at": _utc_iso(authorization.event_recorded_at),
        "rollback_target_content_hash": target_hash,
        "rollback_target_ref": None if target_ref is None else target_ref.to_payload(),
        "schema": "research-r2-market-structure-lifecycle-event.v1",
        "scope_content_hash": authorization.scope_content_hash,
        "scope_id": authorization.scope_id,
        "sequence": sequence,
        "stream_id": stream_id,
    }
    digest = canonical_hash(payload)
    event = R2MarketStructureLifecycleEvent(
        event_id=f"r2-ms-lifecycle-{digest}",
        event_version=event_version,
        scope_id=authorization.scope_id,
        scope_content_hash=authorization.scope_content_hash,
        stream_id=stream_id,
        sequence=sequence,
        event_type=event_type,
        decision_ref=decision.reference,
        decision_content_hash=decision.content_hash,
        rollback_target_ref=target_ref,
        rollback_target_content_hash=target_hash,
        authorization=authorization,
        previous_event_hash=previous_hash,
        occurred_at=authorization.occurred_at,
        recorded_at=authorization.event_recorded_at,
        content_hash=digest,
    )
    derive_r2_market_structure_active_stack((*history, event))
    return event


def derive_r2_market_structure_active_stack(
    events: tuple[R2MarketStructureLifecycleEvent, ...],
) -> tuple[R2MarketStructurePromotionRef, ...]:
    """Replay one complete event stream and return the active decision stack."""

    stack: list[R2MarketStructurePromotionRef] = []
    previous_hash = ""
    scope_id = events[0].scope_id if events else ""
    stream_id = events[0].stream_id if events else ""
    for expected_sequence, event in enumerate(events, start=1):
        if (
            event.sequence != expected_sequence
            or event.previous_event_hash != previous_hash
            or event.scope_id != scope_id
            or event.stream_id != stream_id
        ):
            raise ValueError("R2 lifecycle stream is forked or discontinuous")
        if event.event_type is R2MarketStructureLifecycleEventType.PROMOTED:
            if event.decision_ref in stack:
                raise ValueError("R2 lifecycle cannot promote an already active decision")
            stack.append(event.decision_ref)
        elif event.event_type is R2MarketStructureLifecycleEventType.RETIRED:
            if not stack or stack[-1] != event.decision_ref:
                raise ValueError("R2 lifecycle can retire only the active top decision")
            stack.pop()
        else:
            if (
                len(stack) < 2
                or stack[-1] != event.decision_ref
                or stack[-2] != event.rollback_target_ref
            ):
                raise ValueError("R2 lifecycle rollback target must be stack[-2]")
            stack.pop()
        previous_hash = event.content_hash
    return tuple(stack)


__all__ = [
    "R2MarketStructureDecisionAuthorization",
    "R2MarketStructureEvidenceSeal",
    "R2MarketStructureLifecycleAction",
    "R2MarketStructureLifecycleAuthorization",
    "R2MarketStructureLifecycleEvent",
    "R2MarketStructureLifecycleEventType",
    "R2MarketStructurePromotionDecision",
    "R2MarketStructurePromotionDecisionOutcome",
    "R2MarketStructurePromotionPolicy",
    "R2MarketStructurePromotionRef",
    "R2MarketStructurePromotionScope",
    "create_r2_market_structure_lifecycle_event",
    "create_r2_market_structure_lifecycle_authorization",
    "create_r2_market_structure_promotion_decision",
    "derive_r2_market_structure_active_stack",
]
