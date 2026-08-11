"""Immutable Data Center contracts for R1 evaluation actual evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

_QUALITIES = frozenset({"verified", "estimated", "unknown"})


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    return "0" if text in {"-0", ""} else text


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a non-blank token")
    return value


def _require_text(value: object, field_name: str, *, maximum: int = 40) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be non-blank text")
    return value


def _require_sha256(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"{field_name} must be a sha256 digest")
    return value.lower()


def _require_aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _require_count(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _require_ratio(value: object, field_name: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite() or value < 0 or value > 1:
        raise ValueError(f"{field_name} must be a finite Decimal in [0, 1]")
    return value


def _require_safety_flags(values: tuple[object, ...]) -> None:
    if any(type(value) is not bool or value is not True for value in values):
        raise ValueError("evaluation actual evidence cannot grant decision authority")


@dataclass(frozen=True, slots=True)
class ActualEvidenceIdentity:
    """Exact stable identifier, version and content digest."""

    stable_id: str
    version: str
    content_hash: str

    def __post_init__(self) -> None:
        _require_token(self.stable_id, "evidence stable_id")
        _require_token(self.version, "evidence version")
        _require_sha256(self.content_hash, "evidence content_hash")

    def validated_copy(self) -> ActualEvidenceIdentity:
        """Reconstruct this identity to defeat frozen-object mutation."""

        return ActualEvidenceIdentity(
            stable_id=self.stable_id,
            version=self.version,
            content_hash=self.content_hash,
        )

    @property
    def identity_tuple(self) -> tuple[str, str, str]:
        """Return the canonical identity tuple."""

        return self.stable_id, self.version, self.content_hash.lower()


@dataclass(frozen=True, slots=True)
class ExpectedActualMemberRule:
    """Expected period/metric key and its canonical member/vintage identities."""

    period_end: date
    metric_code: str
    member: ActualEvidenceIdentity
    vintage: ActualEvidenceIdentity

    def __post_init__(self) -> None:
        if type(self.period_end) is not date:
            raise ValueError("expected period_end must be a date")
        _require_token(self.metric_code, "expected metric_code")
        if type(self.member) is not ActualEvidenceIdentity:
            raise TypeError("expected member must be an exact evidence identity")
        if type(self.vintage) is not ActualEvidenceIdentity:
            raise TypeError("expected vintage must be an exact evidence identity")
        self.member.validated_copy()
        self.vintage.validated_copy()

    def validated_copy(self) -> ExpectedActualMemberRule:
        """Return a recursively revalidated rule."""

        return ExpectedActualMemberRule(
            period_end=self.period_end,
            metric_code=self.metric_code,
            member=self.member.validated_copy(),
            vintage=self.vintage.validated_copy(),
        )

    @property
    def key(self) -> tuple[date, str]:
        """Return the expected period/metric key."""

        return self.period_end, self.metric_code


@dataclass(frozen=True, slots=True)
class EvaluationActualCoveragePolicy:
    """Versioned completeness policy; R1 may choose the strict 1/0/0/0 form."""

    require_verified: bool
    minimum_coverage_ratio: Decimal
    maximum_missing_count: int
    maximum_estimated_count: int
    maximum_unknown_count: int

    def __post_init__(self) -> None:
        if type(self.require_verified) is not bool:
            raise ValueError("require_verified must be a bool")
        _require_ratio(self.minimum_coverage_ratio, "minimum_coverage_ratio")
        _require_count(self.maximum_missing_count, "maximum_missing_count")
        _require_count(self.maximum_estimated_count, "maximum_estimated_count")
        _require_count(self.maximum_unknown_count, "maximum_unknown_count")

    def validated_copy(self) -> EvaluationActualCoveragePolicy:
        """Return a live-validated policy copy."""

        return EvaluationActualCoveragePolicy(
            require_verified=self.require_verified,
            minimum_coverage_ratio=self.minimum_coverage_ratio,
            maximum_missing_count=self.maximum_missing_count,
            maximum_estimated_count=self.maximum_estimated_count,
            maximum_unknown_count=self.maximum_unknown_count,
        )


@dataclass(frozen=True, slots=True)
class EvaluationActualSourceDefinition:
    """Data Center-owned, versioned definition of an evaluation actual source."""

    source_id: str
    source_version: str
    source_content_hash: str
    owner: str
    dataset: str
    subject_code: str
    industry_code: str
    calendar: ActualEvidenceIdentity
    knowledge_scope: str
    expected_members: tuple[ExpectedActualMemberRule, ...]
    coverage_policy: EvaluationActualCoveragePolicy
    registered_at: datetime
    valid_until: datetime
    research_only: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    @classmethod
    def create(
        cls,
        *,
        source_id: str,
        source_version: str,
        owner: str,
        dataset: str,
        subject_code: str,
        industry_code: str,
        calendar: ActualEvidenceIdentity,
        knowledge_scope: str,
        expected_members: tuple[ExpectedActualMemberRule, ...],
        coverage_policy: EvaluationActualCoveragePolicy,
        registered_at: datetime,
        valid_until: datetime,
    ) -> EvaluationActualSourceDefinition:
        """Order, hash and construct one authoritative source definition."""

        ordered = tuple(sorted(expected_members, key=lambda item: item.key))
        payload = _definition_payload(
            source_id=source_id,
            source_version=source_version,
            owner=owner,
            dataset=dataset,
            subject_code=subject_code,
            industry_code=industry_code,
            calendar=calendar,
            knowledge_scope=knowledge_scope,
            expected_members=ordered,
            coverage_policy=coverage_policy,
            registered_at=registered_at,
            valid_until=valid_until,
            research_only=True,
            must_not_publish_current=True,
            must_not_use_for_decision=True,
            must_not_execute=True,
        )
        return cls(
            source_id=source_id,
            source_version=source_version,
            source_content_hash=_hash_payload(payload),
            owner=owner,
            dataset=dataset,
            subject_code=subject_code,
            industry_code=industry_code,
            calendar=calendar,
            knowledge_scope=knowledge_scope,
            expected_members=ordered,
            coverage_policy=coverage_policy,
            registered_at=registered_at,
            valid_until=valid_until,
        )

    def __post_init__(self) -> None:
        for field_name, value in (
            ("source_id", self.source_id),
            ("source_version", self.source_version),
            ("owner", self.owner),
            ("dataset", self.dataset),
            ("subject_code", self.subject_code),
            ("industry_code", self.industry_code),
            ("knowledge_scope", self.knowledge_scope),
        ):
            _require_token(value, field_name)
        if self.owner != "data_center":
            raise ValueError("evaluation actual source owner must be data_center")
        _require_sha256(self.source_content_hash, "source_content_hash")
        if type(self.calendar) is not ActualEvidenceIdentity:
            raise TypeError("calendar must be an exact evidence identity")
        self.calendar.validated_copy()
        if type(self.expected_members) is not tuple:
            raise TypeError("expected_members must be an exact tuple")
        if any(type(item) is not ExpectedActualMemberRule for item in self.expected_members):
            raise TypeError("expected member rules must use exact types")
        validated_rules = tuple(item.validated_copy() for item in self.expected_members)
        keys = tuple(item.key for item in validated_rules)
        member_ids = tuple(item.member.identity_tuple[:2] for item in validated_rules)
        vintage_ids = tuple(item.vintage.identity_tuple[:2] for item in validated_rules)
        if (
            not keys
            or keys != tuple(sorted(keys))
            or len(keys) != len(set(keys))
            or len(member_ids) != len(set(member_ids))
            or len(vintage_ids) != len(set(vintage_ids))
        ):
            raise ValueError("expected actual member rules must be ordered and unique")
        if type(self.coverage_policy) is not EvaluationActualCoveragePolicy:
            raise TypeError("coverage_policy must be exact")
        self.coverage_policy.validated_copy()
        _require_aware(self.registered_at, "registered_at")
        _require_aware(self.valid_until, "valid_until")
        if self.registered_at >= self.valid_until:
            raise ValueError("source definition validity interval is invalid")
        _require_safety_flags(
            (
                self.research_only,
                self.must_not_publish_current,
                self.must_not_use_for_decision,
                self.must_not_execute,
            )
        )
        if self.source_content_hash.lower() != _hash_payload(_definition_payload_from_domain(self)):
            raise ValueError("source definition content hash mismatch")

    @property
    def identity(self) -> ActualEvidenceIdentity:
        """Return the complete source identity."""

        return ActualEvidenceIdentity(
            self.source_id,
            self.source_version,
            self.source_content_hash,
        )

    def validated_copy(self) -> EvaluationActualSourceDefinition:
        """Reconstruct the definition and compare its live content seal."""

        rebuilt = EvaluationActualSourceDefinition.create(
            source_id=self.source_id,
            source_version=self.source_version,
            owner=self.owner,
            dataset=self.dataset,
            subject_code=self.subject_code,
            industry_code=self.industry_code,
            calendar=self.calendar.validated_copy(),
            knowledge_scope=self.knowledge_scope,
            expected_members=tuple(item.validated_copy() for item in self.expected_members),
            coverage_policy=self.coverage_policy.validated_copy(),
            registered_at=self.registered_at,
            valid_until=self.valid_until,
        )
        if rebuilt != self:
            raise ValueError("source definition changed after sealing")
        return rebuilt


@dataclass(frozen=True, slots=True)
class PersistedEvaluationActualSourceDefinition:
    """Append-only owner definition plus Data Center ledger knowledge time."""

    definition: EvaluationActualSourceDefinition
    ledger_recorded_at: datetime
    record_hash: str = field(init=False)

    @classmethod
    def create(
        cls,
        *,
        definition: EvaluationActualSourceDefinition,
        ledger_recorded_at: datetime,
    ) -> PersistedEvaluationActualSourceDefinition:
        """Seal one validated definition at the trusted ledger clock."""

        if type(definition) is not EvaluationActualSourceDefinition:
            raise TypeError("persisted source definition must use the exact type")
        return cls(
            definition=definition.validated_copy(),
            ledger_recorded_at=ledger_recorded_at,
        )

    def __post_init__(self) -> None:
        if type(self.definition) is not EvaluationActualSourceDefinition:
            raise TypeError("persisted source definition must be exact")
        self.definition.validated_copy()
        _require_aware(self.ledger_recorded_at, "ledger_recorded_at")
        if not (
            self.definition.registered_at <= self.ledger_recorded_at < self.definition.valid_until
        ):
            raise ValueError("source definition ledger clock is outside validity")
        object.__setattr__(
            self,
            "record_hash",
            _hash_payload(
                {
                    "schema": "data-center.evaluation-actual-source-record.v1",
                    "source": list(self.definition.identity.identity_tuple),
                    "ledger_recorded_at": _utc_text(self.ledger_recorded_at),
                }
            ),
        )

    def validated_copy(self) -> PersistedEvaluationActualSourceDefinition:
        """Rebuild this record and verify its live server-time seal."""

        rebuilt = PersistedEvaluationActualSourceDefinition.create(
            definition=self.definition.validated_copy(),
            ledger_recorded_at=self.ledger_recorded_at,
        )
        if rebuilt.record_hash.lower() != self.record_hash.lower():
            raise ValueError("source definition record hash mismatch")
        return rebuilt


@dataclass(frozen=True, slots=True)
class CanonicalEvaluationActualFact:
    """Canonical exact fact/member/vintage candidate returned by its owner."""

    dataset: str
    subject_code: str
    industry_code: str
    period_end: date
    metric_code: str
    value: Decimal
    unit: str
    source_fact: ActualEvidenceIdentity
    revision_number: int
    effective_at: datetime
    available_at: datetime
    member: ActualEvidenceIdentity | None
    vintage: ActualEvidenceIdentity | None
    quality: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("dataset", self.dataset),
            ("subject_code", self.subject_code),
            ("industry_code", self.industry_code),
            ("metric_code", self.metric_code),
            ("quality", self.quality),
        ):
            _require_token(value, f"actual fact {field_name}")
        if type(self.period_end) is not date:
            raise ValueError("actual fact period_end must be a date")
        if type(self.value) is not Decimal or not self.value.is_finite():
            raise ValueError("actual fact value must be a finite Decimal")
        _require_text(self.unit, "actual fact unit")
        if type(self.source_fact) is not ActualEvidenceIdentity:
            raise TypeError("source_fact must be an exact evidence identity")
        self.source_fact.validated_copy()
        if type(self.revision_number) is not int or self.revision_number <= 0:
            raise ValueError("revision_number must be positive")
        _require_aware(self.effective_at, "actual fact effective_at")
        _require_aware(self.available_at, "actual fact available_at")
        if self.available_at < self.effective_at:
            raise ValueError("actual fact cannot be available before effective time")
        if self.member is not None:
            if type(self.member) is not ActualEvidenceIdentity:
                raise TypeError("member must be an exact evidence identity")
            self.member.validated_copy()
        if self.vintage is not None:
            if type(self.vintage) is not ActualEvidenceIdentity:
                raise TypeError("vintage must be an exact evidence identity")
            self.vintage.validated_copy()
        if self.quality not in _QUALITIES:
            raise ValueError("actual fact quality is unsupported")

    def validated_copy(self) -> CanonicalEvaluationActualFact:
        """Return a recursively live-validated fact candidate."""

        return CanonicalEvaluationActualFact(
            dataset=self.dataset,
            subject_code=self.subject_code,
            industry_code=self.industry_code,
            period_end=self.period_end,
            metric_code=self.metric_code,
            value=self.value,
            unit=self.unit,
            source_fact=self.source_fact.validated_copy(),
            revision_number=self.revision_number,
            effective_at=self.effective_at,
            available_at=self.available_at,
            member=None if self.member is None else self.member.validated_copy(),
            vintage=None if self.vintage is None else self.vintage.validated_copy(),
            quality=self.quality,
        )

    @property
    def key(self) -> tuple[date, str]:
        """Return the period/metric selection key."""

        return self.period_end, self.metric_code


@dataclass(frozen=True, slots=True)
class CanonicalEvaluationActualGraph:
    """Complete result of one canonical fact/member owner query."""

    source_definition: ActualEvidenceIdentity
    as_of_time: datetime
    knowledge_scope: str
    facts: tuple[CanonicalEvaluationActualFact, ...]

    def __post_init__(self) -> None:
        if type(self.source_definition) is not ActualEvidenceIdentity:
            raise TypeError("graph source_definition must be exact")
        self.source_definition.validated_copy()
        _require_aware(self.as_of_time, "graph as_of_time")
        _require_token(self.knowledge_scope, "graph knowledge_scope")
        if type(self.facts) is not tuple:
            raise TypeError("graph facts must be an exact tuple")
        if any(type(item) is not CanonicalEvaluationActualFact for item in self.facts):
            raise TypeError("graph facts must use exact types")
        tuple(item.validated_copy() for item in self.facts)

    def validated_copy(self) -> CanonicalEvaluationActualGraph:
        """Return a recursively live-validated graph."""

        return CanonicalEvaluationActualGraph(
            source_definition=self.source_definition.validated_copy(),
            as_of_time=self.as_of_time,
            knowledge_scope=self.knowledge_scope,
            facts=tuple(item.validated_copy() for item in self.facts),
        )


@dataclass(frozen=True, slots=True)
class MaterializedEvaluationActualManifest:
    """Server-produced actual manifest retained as an append-only owner receipt."""

    manifest_id: str
    manifest_version: str
    manifest_content_hash: str
    source_definition: ActualEvidenceIdentity
    owner: str
    dataset: str
    subject_code: str
    industry_code: str
    calendar: ActualEvidenceIdentity
    as_of_time: datetime
    produced_at: datetime
    valid_until: datetime
    knowledge_scope: str
    is_verified: bool
    coverage_ratio: Decimal
    missing_count: int
    estimated_count: int
    unknown_count: int
    facts: tuple[CanonicalEvaluationActualFact, ...]
    selected_versions_hash: str
    research_only: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True
    receipt_hash: str = field(init=False)

    @classmethod
    def materialize(
        cls,
        *,
        manifest_id: str,
        manifest_version: str,
        definition: EvaluationActualSourceDefinition,
        graph: CanonicalEvaluationActualGraph,
        produced_at: datetime,
    ) -> MaterializedEvaluationActualManifest:
        """Validate owner evidence and calculate completeness before sealing."""

        if type(definition) is not EvaluationActualSourceDefinition:
            raise TypeError("materialization definition must use the exact type")
        if type(graph) is not CanonicalEvaluationActualGraph:
            raise TypeError("materialization graph must use the exact type")
        definition = definition.validated_copy()
        graph = graph.validated_copy()
        _require_aware(produced_at, "manifest produced_at")
        if graph.source_definition != definition.identity:
            raise ValueError("actual graph source definition was substituted")
        if graph.knowledge_scope != definition.knowledge_scope:
            raise ValueError("actual graph knowledge scope was substituted")
        if not (
            definition.registered_at <= graph.as_of_time <= produced_at < definition.valid_until
        ):
            raise ValueError("actual graph or production clock is outside source validity")

        expected = {item.key: item for item in definition.expected_members}
        facts = tuple(sorted(graph.facts, key=lambda item: item.key))
        fact_keys = tuple(item.key for item in facts)
        if len(fact_keys) != len(set(fact_keys)) or any(key not in expected for key in fact_keys):
            raise ValueError("actual graph contains duplicate or unexpected keys")
        source_ids = tuple(item.source_fact.identity_tuple[:2] for item in facts)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("actual source fact identities are not unique")
        for fact in facts:
            rule = expected[fact.key]
            if fact.member is None:
                raise ValueError("canonical actual manifest member is unavailable")
            if fact.vintage is None:
                raise ValueError("canonical actual vintage is unavailable")
            if (
                fact.dataset != definition.dataset
                or fact.subject_code != definition.subject_code
                or fact.industry_code != definition.industry_code
                or fact.member != rule.member
                or fact.vintage != rule.vintage
                or fact.available_at > graph.as_of_time
            ):
                raise ValueError("canonical actual fact/member/vintage was substituted")

        missing_count = len(set(expected) - set(fact_keys))
        estimated_count = sum(item.quality == "estimated" for item in facts)
        unknown_count = sum(item.quality == "unknown" for item in facts)
        coverage_ratio = Decimal(len(fact_keys)) / Decimal(len(expected))
        is_verified = (
            missing_count == 0
            and estimated_count == 0
            and unknown_count == 0
            and all(item.quality == "verified" for item in facts)
        )
        policy = definition.coverage_policy
        if (
            (policy.require_verified and not is_verified)
            or coverage_ratio < policy.minimum_coverage_ratio
            or missing_count > policy.maximum_missing_count
            or estimated_count > policy.maximum_estimated_count
            or unknown_count > policy.maximum_unknown_count
        ):
            raise ValueError("actual graph fails the versioned completeness policy")

        selected_versions_hash = _selected_versions_hash(facts)
        content_hash = _hash_payload(
            _manifest_content_payload(
                manifest_id=manifest_id,
                manifest_version=manifest_version,
                source_definition=definition.identity,
                owner=definition.owner,
                dataset=definition.dataset,
                subject_code=definition.subject_code,
                industry_code=definition.industry_code,
                calendar=definition.calendar,
                as_of_time=graph.as_of_time,
                produced_at=produced_at,
                valid_until=definition.valid_until,
                knowledge_scope=definition.knowledge_scope,
                is_verified=is_verified,
                coverage_ratio=coverage_ratio,
                missing_count=missing_count,
                estimated_count=estimated_count,
                unknown_count=unknown_count,
                facts=facts,
                selected_versions_hash=selected_versions_hash,
            )
        )
        return cls(
            manifest_id=manifest_id,
            manifest_version=manifest_version,
            manifest_content_hash=content_hash,
            source_definition=definition.identity,
            owner=definition.owner,
            dataset=definition.dataset,
            subject_code=definition.subject_code,
            industry_code=definition.industry_code,
            calendar=definition.calendar,
            as_of_time=graph.as_of_time,
            produced_at=produced_at,
            valid_until=definition.valid_until,
            knowledge_scope=definition.knowledge_scope,
            is_verified=is_verified,
            coverage_ratio=coverage_ratio,
            missing_count=missing_count,
            estimated_count=estimated_count,
            unknown_count=unknown_count,
            facts=facts,
            selected_versions_hash=selected_versions_hash,
        )

    def __post_init__(self) -> None:
        for field_name, value in (
            ("manifest_id", self.manifest_id),
            ("manifest_version", self.manifest_version),
            ("owner", self.owner),
            ("dataset", self.dataset),
            ("subject_code", self.subject_code),
            ("industry_code", self.industry_code),
            ("knowledge_scope", self.knowledge_scope),
        ):
            _require_token(value, field_name)
        if self.owner != "data_center":
            raise ValueError("materialized actual owner must be data_center")
        _require_sha256(self.manifest_content_hash, "manifest_content_hash")
        if type(self.source_definition) is not ActualEvidenceIdentity:
            raise TypeError("manifest source_definition must be exact")
        if type(self.calendar) is not ActualEvidenceIdentity:
            raise TypeError("manifest calendar must be exact")
        self.source_definition.validated_copy()
        self.calendar.validated_copy()
        _require_aware(self.as_of_time, "manifest as_of_time")
        _require_aware(self.produced_at, "manifest produced_at")
        _require_aware(self.valid_until, "manifest valid_until")
        if not self.as_of_time <= self.produced_at < self.valid_until:
            raise ValueError("materialized actual clocks are invalid")
        if type(self.is_verified) is not bool:
            raise ValueError("manifest is_verified must be a bool")
        _require_ratio(self.coverage_ratio, "manifest coverage_ratio")
        _require_count(self.missing_count, "manifest missing_count")
        _require_count(self.estimated_count, "manifest estimated_count")
        _require_count(self.unknown_count, "manifest unknown_count")
        if type(self.facts) is not tuple:
            raise TypeError("manifest facts must be an exact tuple")
        if any(type(item) is not CanonicalEvaluationActualFact for item in self.facts):
            raise TypeError("materialized facts must use exact types")
        validated_facts = tuple(item.validated_copy() for item in self.facts)
        if any(item.member is None or item.vintage is None for item in validated_facts):
            raise ValueError("materialized manifest cannot retain incomplete identities")
        keys = tuple(item.key for item in validated_facts)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("materialized facts must be ordered and unique")
        _require_sha256(self.selected_versions_hash, "selected_versions_hash")
        if self.selected_versions_hash.lower() != _selected_versions_hash(validated_facts):
            raise ValueError("selected versions hash mismatch")
        _require_safety_flags(
            (
                self.research_only,
                self.must_not_publish_current,
                self.must_not_use_for_decision,
                self.must_not_execute,
            )
        )
        if self.manifest_content_hash.lower() != _hash_payload(
            _manifest_content_payload_from_domain(self)
        ):
            raise ValueError("materialized manifest content hash mismatch")
        object.__setattr__(
            self,
            "receipt_hash",
            _hash_payload(
                {
                    "schema": "data-center.evaluation-actual-manifest-receipt.v1",
                    "manifest": list(self.identity.identity_tuple),
                    "source_definition": list(self.source_definition.identity_tuple),
                    "produced_at": _utc_text(self.produced_at),
                    "valid_until": _utc_text(self.valid_until),
                    "selected_versions_hash": self.selected_versions_hash.lower(),
                    "research_only": self.research_only,
                    "must_not_publish_current": self.must_not_publish_current,
                    "must_not_use_for_decision": self.must_not_use_for_decision,
                    "must_not_execute": self.must_not_execute,
                }
            ),
        )

    @property
    def identity(self) -> ActualEvidenceIdentity:
        """Return the complete manifest identity."""

        return ActualEvidenceIdentity(
            self.manifest_id,
            self.manifest_version,
            self.manifest_content_hash,
        )

    def validated_copy(self) -> MaterializedEvaluationActualManifest:
        """Rebuild this receipt and verify every live seal."""

        rebuilt = MaterializedEvaluationActualManifest(
            manifest_id=self.manifest_id,
            manifest_version=self.manifest_version,
            manifest_content_hash=self.manifest_content_hash,
            source_definition=self.source_definition.validated_copy(),
            owner=self.owner,
            dataset=self.dataset,
            subject_code=self.subject_code,
            industry_code=self.industry_code,
            calendar=self.calendar.validated_copy(),
            as_of_time=self.as_of_time,
            produced_at=self.produced_at,
            valid_until=self.valid_until,
            knowledge_scope=self.knowledge_scope,
            is_verified=self.is_verified,
            coverage_ratio=self.coverage_ratio,
            missing_count=self.missing_count,
            estimated_count=self.estimated_count,
            unknown_count=self.unknown_count,
            facts=tuple(item.validated_copy() for item in self.facts),
            selected_versions_hash=self.selected_versions_hash,
            research_only=self.research_only,
            must_not_publish_current=self.must_not_publish_current,
            must_not_use_for_decision=self.must_not_use_for_decision,
            must_not_execute=self.must_not_execute,
        )
        if rebuilt.receipt_hash.lower() != self.receipt_hash.lower():
            raise ValueError("materialized manifest receipt hash mismatch")
        return rebuilt


def _identity_payload(identity: ActualEvidenceIdentity) -> list[str]:
    return list(identity.validated_copy().identity_tuple)


def _definition_payload_from_domain(
    definition: EvaluationActualSourceDefinition,
) -> dict[str, object]:
    return _definition_payload(
        source_id=definition.source_id,
        source_version=definition.source_version,
        owner=definition.owner,
        dataset=definition.dataset,
        subject_code=definition.subject_code,
        industry_code=definition.industry_code,
        calendar=definition.calendar,
        knowledge_scope=definition.knowledge_scope,
        expected_members=definition.expected_members,
        coverage_policy=definition.coverage_policy,
        registered_at=definition.registered_at,
        valid_until=definition.valid_until,
        research_only=definition.research_only,
        must_not_publish_current=definition.must_not_publish_current,
        must_not_use_for_decision=definition.must_not_use_for_decision,
        must_not_execute=definition.must_not_execute,
    )


def _definition_payload(
    *,
    source_id: str,
    source_version: str,
    owner: str,
    dataset: str,
    subject_code: str,
    industry_code: str,
    calendar: ActualEvidenceIdentity,
    knowledge_scope: str,
    expected_members: tuple[ExpectedActualMemberRule, ...],
    coverage_policy: EvaluationActualCoveragePolicy,
    registered_at: datetime,
    valid_until: datetime,
    research_only: bool,
    must_not_publish_current: bool,
    must_not_use_for_decision: bool,
    must_not_execute: bool,
) -> dict[str, object]:
    return {
        "schema": "data-center.evaluation-actual-source-definition.v1",
        "source": [source_id, source_version, owner],
        "scope": [dataset, subject_code, industry_code, knowledge_scope],
        "calendar": _identity_payload(calendar),
        "expected_members": [
            {
                "period_end": item.period_end.isoformat(),
                "metric_code": item.metric_code,
                "member": _identity_payload(item.member),
                "vintage": _identity_payload(item.vintage),
            }
            for item in expected_members
        ],
        "coverage_policy": {
            "require_verified": coverage_policy.require_verified,
            "minimum_coverage_ratio": _decimal_text(coverage_policy.minimum_coverage_ratio),
            "maximum_missing_count": coverage_policy.maximum_missing_count,
            "maximum_estimated_count": coverage_policy.maximum_estimated_count,
            "maximum_unknown_count": coverage_policy.maximum_unknown_count,
        },
        "registered_at": _utc_text(registered_at),
        "valid_until": _utc_text(valid_until),
        "research_only": research_only,
        "must_not_publish_current": must_not_publish_current,
        "must_not_use_for_decision": must_not_use_for_decision,
        "must_not_execute": must_not_execute,
    }


def _fact_payload(fact: CanonicalEvaluationActualFact) -> dict[str, object]:
    if fact.member is None or fact.vintage is None:
        raise ValueError("canonical fact lacks member or vintage identity")
    return {
        "scope": [fact.dataset, fact.subject_code, fact.industry_code],
        "key": [fact.period_end.isoformat(), fact.metric_code],
        "value": _decimal_text(fact.value),
        "unit": fact.unit,
        "source_fact": _identity_payload(fact.source_fact),
        "revision_number": fact.revision_number,
        "effective_at": _utc_text(fact.effective_at),
        "available_at": _utc_text(fact.available_at),
        "member": _identity_payload(fact.member),
        "vintage": _identity_payload(fact.vintage),
        "quality": fact.quality,
    }


def _selected_versions_hash(facts: tuple[CanonicalEvaluationActualFact, ...]) -> str:
    identities = []
    for fact in facts:
        if fact.member is None or fact.vintage is None:
            raise ValueError("selected version identity is incomplete")
        identities.append(
            (
                *fact.member.identity_tuple,
                *fact.source_fact.identity_tuple,
                *fact.vintage.identity_tuple,
            )
        )
    return _hash_payload(
        {
            "schema": "r1-actual-selected-versions.v1",
            "versions": [list(item) for item in sorted(identities)],
        }
    )


def _manifest_content_payload_from_domain(
    manifest: MaterializedEvaluationActualManifest,
) -> dict[str, object]:
    return _manifest_content_payload(
        manifest_id=manifest.manifest_id,
        manifest_version=manifest.manifest_version,
        source_definition=manifest.source_definition,
        owner=manifest.owner,
        dataset=manifest.dataset,
        subject_code=manifest.subject_code,
        industry_code=manifest.industry_code,
        calendar=manifest.calendar,
        as_of_time=manifest.as_of_time,
        produced_at=manifest.produced_at,
        valid_until=manifest.valid_until,
        knowledge_scope=manifest.knowledge_scope,
        is_verified=manifest.is_verified,
        coverage_ratio=manifest.coverage_ratio,
        missing_count=manifest.missing_count,
        estimated_count=manifest.estimated_count,
        unknown_count=manifest.unknown_count,
        facts=manifest.facts,
        selected_versions_hash=manifest.selected_versions_hash,
    )


def _manifest_content_payload(
    *,
    manifest_id: str,
    manifest_version: str,
    source_definition: ActualEvidenceIdentity,
    owner: str,
    dataset: str,
    subject_code: str,
    industry_code: str,
    calendar: ActualEvidenceIdentity,
    as_of_time: datetime,
    produced_at: datetime,
    valid_until: datetime,
    knowledge_scope: str,
    is_verified: bool,
    coverage_ratio: Decimal,
    missing_count: int,
    estimated_count: int,
    unknown_count: int,
    facts: tuple[CanonicalEvaluationActualFact, ...],
    selected_versions_hash: str,
) -> dict[str, object]:
    return {
        "schema": "data-center.evaluation-actual-manifest.v1",
        "manifest": [manifest_id, manifest_version, owner],
        "source_definition": _identity_payload(source_definition),
        "scope": [dataset, subject_code, industry_code, knowledge_scope],
        "calendar": _identity_payload(calendar),
        "clocks": [_utc_text(as_of_time), _utc_text(produced_at), _utc_text(valid_until)],
        "completeness": [
            is_verified,
            _decimal_text(coverage_ratio),
            missing_count,
            estimated_count,
            unknown_count,
        ],
        "facts": [_fact_payload(item) for item in facts],
        "selected_versions_hash": selected_versions_hash.lower(),
    }


__all__ = [
    "ActualEvidenceIdentity",
    "CanonicalEvaluationActualFact",
    "CanonicalEvaluationActualGraph",
    "EvaluationActualCoveragePolicy",
    "EvaluationActualSourceDefinition",
    "ExpectedActualMemberRule",
    "MaterializedEvaluationActualManifest",
    "PersistedEvaluationActualSourceDefinition",
]
