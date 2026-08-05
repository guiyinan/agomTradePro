"""External authority evidence sealed into R1 baseline trial results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from .forecast_baseline_evidence import (
    ActualFactObservation,
    BaselinePITSelectedVersion,
    _decimal_text,
    _hash_payload,
    _require_aware,
    _require_sha256,
    _require_token,
    _utc_text,
)


class ActualRevisionRule(str, Enum):
    """Approved rule for selecting evaluation actual revisions."""

    FIRST_PUBLICATION = "first_publication"


class ActualVintageRule(str, Enum):
    """Approved vintage cutoff for evaluation actuals."""

    MANIFEST_AS_OF = "manifest_as_of"


class ForecastFreezeRule(str, Enum):
    """Owner-controlled forecast persistence deadline semantics."""

    PERSISTED_BY_DEADLINE = "persisted_by_deadline"


@dataclass(frozen=True)
class ForecastEvaluationPolicy:
    """Equity-approved forecast freeze and actual-selection authority."""

    policy_id: str
    policy_version: str
    policy_content_hash: str
    owner: str
    actual_dataset: str
    actual_knowledge_scope: str
    actual_revision_rule: ActualRevisionRule
    actual_vintage_rule: ActualVintageRule
    forecast_freeze_rule: ForecastFreezeRule
    forecast_knowledge_cutoff_at: datetime
    forecast_submission_deadline_at: datetime
    valid_until: datetime

    @classmethod
    def create(
        cls,
        *,
        policy_id: str,
        policy_version: str,
        owner: str,
        actual_dataset: str,
        actual_knowledge_scope: str,
        actual_revision_rule: ActualRevisionRule,
        actual_vintage_rule: ActualVintageRule,
        forecast_freeze_rule: ForecastFreezeRule,
        forecast_knowledge_cutoff_at: datetime,
        forecast_submission_deadline_at: datetime,
        valid_until: datetime,
    ) -> ForecastEvaluationPolicy:
        """Seal one exact owner-approved evaluation policy."""

        payload = _forecast_evaluation_policy_payload(
            policy_id=policy_id,
            policy_version=policy_version,
            owner=owner,
            actual_dataset=actual_dataset,
            actual_knowledge_scope=actual_knowledge_scope,
            actual_revision_rule=actual_revision_rule,
            actual_vintage_rule=actual_vintage_rule,
            forecast_freeze_rule=forecast_freeze_rule,
            forecast_knowledge_cutoff_at=forecast_knowledge_cutoff_at,
            forecast_submission_deadline_at=forecast_submission_deadline_at,
            valid_until=valid_until,
        )
        return cls(
            policy_id=policy_id,
            policy_version=policy_version,
            policy_content_hash=_hash_payload(payload),
            owner=owner,
            actual_dataset=actual_dataset,
            actual_knowledge_scope=actual_knowledge_scope,
            actual_revision_rule=actual_revision_rule,
            actual_vintage_rule=actual_vintage_rule,
            forecast_freeze_rule=forecast_freeze_rule,
            forecast_knowledge_cutoff_at=forecast_knowledge_cutoff_at,
            forecast_submission_deadline_at=forecast_submission_deadline_at,
            valid_until=valid_until,
        )

    def __post_init__(self) -> None:
        for field_name, value in (
            ("policy_id", self.policy_id),
            ("policy_version", self.policy_version),
            ("owner", self.owner),
            ("actual_dataset", self.actual_dataset),
            ("actual_knowledge_scope", self.actual_knowledge_scope),
        ):
            _require_token(value, f"forecast evaluation {field_name}")
        _require_sha256(self.policy_content_hash, "forecast evaluation policy_content_hash")
        _require_aware(
            self.forecast_knowledge_cutoff_at,
            "forecast knowledge cutoff",
        )
        _require_aware(
            self.forecast_submission_deadline_at,
            "forecast submission deadline",
        )
        _require_aware(self.valid_until, "forecast evaluation policy valid_until")
        if (
            self.owner != "equity"
            or self.actual_knowledge_scope != "public"
            or self.actual_revision_rule is not ActualRevisionRule.FIRST_PUBLICATION
            or self.actual_vintage_rule is not ActualVintageRule.MANIFEST_AS_OF
            or self.forecast_freeze_rule is not ForecastFreezeRule.PERSISTED_BY_DEADLINE
        ):
            raise ValueError("forecast evaluation policy is unsupported")
        if not (
            self.forecast_knowledge_cutoff_at
            <= self.forecast_submission_deadline_at
            < self.valid_until
        ):
            raise ValueError("forecast evaluation policy time window is invalid")
        expected_hash = _hash_payload(
            _forecast_evaluation_policy_payload(
                policy_id=self.policy_id,
                policy_version=self.policy_version,
                owner=self.owner,
                actual_dataset=self.actual_dataset,
                actual_knowledge_scope=self.actual_knowledge_scope,
                actual_revision_rule=self.actual_revision_rule,
                actual_vintage_rule=self.actual_vintage_rule,
                forecast_freeze_rule=self.forecast_freeze_rule,
                forecast_knowledge_cutoff_at=self.forecast_knowledge_cutoff_at,
                forecast_submission_deadline_at=self.forecast_submission_deadline_at,
                valid_until=self.valid_until,
            )
        )
        if self.policy_content_hash != expected_hash:
            raise ValueError("forecast evaluation policy content hash mismatch")


def _forecast_evaluation_policy_payload(
    *,
    policy_id: str,
    policy_version: str,
    owner: str,
    actual_dataset: str,
    actual_knowledge_scope: str,
    actual_revision_rule: ActualRevisionRule,
    actual_vintage_rule: ActualVintageRule,
    forecast_freeze_rule: ForecastFreezeRule,
    forecast_knowledge_cutoff_at: datetime,
    forecast_submission_deadline_at: datetime,
    valid_until: datetime,
) -> dict[str, object]:
    return {
        "schema": "r1-forecast-evaluation-policy.v1",
        "identity": [policy_id, policy_version, owner],
        "actual_selection": [
            actual_dataset,
            actual_knowledge_scope,
            actual_revision_rule.value,
            actual_vintage_rule.value,
        ],
        "forecast_freeze": [
            forecast_freeze_rule.value,
            _utc_text(forecast_knowledge_cutoff_at),
            _utc_text(forecast_submission_deadline_at),
        ],
        "valid_until": _utc_text(valid_until),
    }


@dataclass(frozen=True)
class ResearchTrialAuthorization:
    """Exact active Research registration authorizing one R1 valuation trial."""

    trial_id: str
    trial_version: str
    trial_content_hash: str
    owner: str
    capability: str
    purpose: str
    status: str
    split_spec_hash: str
    parameter_hash: str
    baseline_spec_id: str
    baseline_spec_version: str
    baseline_spec_content_hash: str
    expected_period_ends: tuple[date, ...]
    metric_codes: tuple[str, ...]
    calendar_schedule_hash: str
    evaluation_policy: ForecastEvaluationPolicy
    baseline_spec_approved_at: datetime
    forecast_origin_at: datetime
    activated_at: datetime
    recorded_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for field_name, value in (
            ("trial_id", self.trial_id),
            ("trial_version", self.trial_version),
            ("owner", self.owner),
            ("capability", self.capability),
            ("purpose", self.purpose),
            ("status", self.status),
            ("baseline_spec_id", self.baseline_spec_id),
            ("baseline_spec_version", self.baseline_spec_version),
        ):
            _require_token(value, f"research trial {field_name}")
        for field_name, value in (
            ("trial_content_hash", self.trial_content_hash),
            ("split_spec_hash", self.split_spec_hash),
            ("parameter_hash", self.parameter_hash),
            ("baseline_spec_content_hash", self.baseline_spec_content_hash),
            ("calendar_schedule_hash", self.calendar_schedule_hash),
        ):
            _require_sha256(value, f"research trial {field_name}")
        _require_aware(self.activated_at, "research trial activated_at")
        _require_aware(self.recorded_at, "research trial recorded_at")
        _require_aware(self.valid_until, "research trial valid_until")
        _require_aware(
            self.baseline_spec_approved_at,
            "research trial baseline_spec_approved_at",
        )
        _require_aware(self.forecast_origin_at, "research trial forecast_origin_at")
        if (
            self.owner != "research"
            or self.capability != "r1"
            or self.purpose != "valuation"
            or self.status != "running"
        ):
            raise ValueError("research trial authorization scope is invalid")
        if self.valid_until <= self.activated_at:
            raise ValueError("research trial authorization window is invalid")
        if not (
            self.baseline_spec_approved_at
            <= self.activated_at
            <= self.recorded_at
            <= self.forecast_origin_at
        ):
            raise ValueError("research trial was not registered before forecasting")
        if (
            not self.expected_period_ends
            or self.expected_period_ends != tuple(sorted(self.expected_period_ends))
            or len(self.expected_period_ends) != len(set(self.expected_period_ends))
        ):
            raise ValueError("research trial expected periods must be unique and ordered")
        if (
            not self.metric_codes
            or self.metric_codes != tuple(sorted(self.metric_codes))
            or len(self.metric_codes) != len(set(self.metric_codes))
        ):
            raise ValueError("research trial metric codes must be unique and ordered")
        for metric_code in self.metric_codes:
            _require_token(metric_code, "research trial metric code")


@dataclass(frozen=True)
class EvaluationActualManifest:
    """Independent, complete Data Center actual manifest for evaluation."""

    manifest_id: str
    manifest_version: str
    manifest_content_hash: str
    owner: str
    subject_code: str
    industry_code: str
    dataset: str
    calendar_id: str
    calendar_version: str
    calendar_content_hash: str
    as_of_time: datetime
    produced_at: datetime
    knowledge_scope: str
    is_verified: bool
    coverage_ratio: Decimal
    missing_count: int
    estimated_count: int
    unknown_count: int
    selected_versions: tuple[BaselinePITSelectedVersion, ...]
    selected_versions_hash: str
    members: tuple[ActualFactObservation, ...]
    seal_hash: str

    @classmethod
    def create(
        cls,
        *,
        manifest_id: str,
        manifest_version: str,
        manifest_content_hash: str,
        owner: str,
        subject_code: str,
        industry_code: str,
        dataset: str,
        calendar_id: str,
        calendar_version: str,
        calendar_content_hash: str,
        as_of_time: datetime,
        produced_at: datetime,
        knowledge_scope: str,
        is_verified: bool,
        coverage_ratio: Decimal,
        missing_count: int,
        estimated_count: int,
        unknown_count: int,
        selected_versions: tuple[BaselinePITSelectedVersion, ...],
        selected_versions_hash: str,
        members: tuple[ActualFactObservation, ...],
    ) -> EvaluationActualManifest:
        """Order and seal an independently versioned actual-fact manifest."""

        ordered_members = tuple(
            sorted(members, key=lambda item: (item.period_end, item.metric_code))
        )
        ordered_versions = tuple(sorted(selected_versions, key=lambda item: item.identity_tuple))
        payload = _evaluation_actual_manifest_payload(
            manifest_id=manifest_id,
            manifest_version=manifest_version,
            manifest_content_hash=manifest_content_hash,
            owner=owner,
            subject_code=subject_code,
            industry_code=industry_code,
            dataset=dataset,
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            calendar_content_hash=calendar_content_hash,
            as_of_time=as_of_time,
            produced_at=produced_at,
            knowledge_scope=knowledge_scope,
            is_verified=is_verified,
            coverage_ratio=coverage_ratio,
            missing_count=missing_count,
            estimated_count=estimated_count,
            unknown_count=unknown_count,
            selected_versions=ordered_versions,
            selected_versions_hash=selected_versions_hash,
            members=ordered_members,
        )
        return cls(
            manifest_id=manifest_id,
            manifest_version=manifest_version,
            manifest_content_hash=manifest_content_hash,
            owner=owner,
            subject_code=subject_code,
            industry_code=industry_code,
            dataset=dataset,
            calendar_id=calendar_id,
            calendar_version=calendar_version,
            calendar_content_hash=calendar_content_hash,
            as_of_time=as_of_time,
            produced_at=produced_at,
            knowledge_scope=knowledge_scope,
            is_verified=is_verified,
            coverage_ratio=coverage_ratio,
            missing_count=missing_count,
            estimated_count=estimated_count,
            unknown_count=unknown_count,
            selected_versions=ordered_versions,
            selected_versions_hash=selected_versions_hash,
            members=ordered_members,
            seal_hash=_hash_payload(payload),
        )

    def __post_init__(self) -> None:
        for field_name, value in (
            ("manifest_id", self.manifest_id),
            ("manifest_version", self.manifest_version),
            ("owner", self.owner),
            ("subject_code", self.subject_code),
            ("industry_code", self.industry_code),
            ("dataset", self.dataset),
            ("calendar_id", self.calendar_id),
            ("calendar_version", self.calendar_version),
            ("knowledge_scope", self.knowledge_scope),
        ):
            _require_token(value, f"actual manifest {field_name}")
        if self.owner != "data_center":
            raise ValueError("evaluation actual manifest owner must be data_center")
        if self.knowledge_scope != "public":
            raise ValueError("evaluation actual manifest must use public knowledge")
        _require_sha256(self.manifest_content_hash, "actual manifest_content_hash")
        _require_sha256(self.calendar_content_hash, "actual calendar_content_hash")
        _require_aware(self.as_of_time, "actual manifest as_of_time")
        _require_aware(self.produced_at, "actual manifest produced_at")
        if self.as_of_time > self.produced_at:
            raise ValueError("actual manifest cannot be produced before its as-of time")
        if self.is_verified is not True or self.coverage_ratio != Decimal("1"):
            raise ValueError("evaluation actual manifest must be complete and verified")
        for field_name, count in (
            ("missing_count", self.missing_count),
            ("estimated_count", self.estimated_count),
            ("unknown_count", self.unknown_count),
        ):
            if isinstance(count, bool) or count != 0:
                raise ValueError(f"actual manifest {field_name} must be zero")
        member_keys = tuple((item.period_end, item.metric_code) for item in self.members)
        member_ids = tuple(
            (item.manifest_member_id, item.manifest_member_version) for item in self.members
        )
        fact_ids = tuple((item.source_fact_id, item.source_fact_version) for item in self.members)
        vintage_ids = tuple((item.vintage_id, item.vintage_version) for item in self.members)
        if (
            not member_keys
            or member_keys != tuple(sorted(member_keys))
            or len(member_keys) != len(set(member_keys))
            or len(member_ids) != len(set(member_ids))
            or len(fact_ids) != len(set(fact_ids))
            or len(vintage_ids) != len(set(vintage_ids))
        ):
            raise ValueError("actual manifest member identities must be globally unique")
        if any(item.available_at > self.as_of_time for item in self.members):
            raise ValueError("actual manifest contains an unavailable member")
        if any(
            item.subject_code != self.subject_code
            or item.industry_code != self.industry_code
            or item.dataset != self.dataset
            or item.revision_number != 1
            or item.pit_manifest_id != self.manifest_id
            or item.pit_manifest_hash != self.manifest_content_hash
            or item.calendar_id != self.calendar_id
            or item.calendar_version != self.calendar_version
            or item.calendar_content_hash != self.calendar_content_hash
            for item in self.members
        ):
            raise ValueError("actual manifest member identity is inconsistent")
        member_versions = tuple(
            sorted(
                (
                    BaselinePITSelectedVersion(
                        selected_member_id=item.manifest_member_id,
                        selected_member_version=item.manifest_member_version,
                        selected_member_content_hash=item.manifest_member_content_hash,
                        source_fact_id=item.source_fact_id,
                        source_fact_version=item.source_fact_version,
                        source_fact_content_hash=item.source_fact_content_hash,
                        vintage_id=item.vintage_id,
                        vintage_version=item.vintage_version,
                        vintage_content_hash=item.vintage_content_hash,
                    )
                    for item in self.members
                ),
                key=lambda item: item.identity_tuple,
            )
        )
        selected_identity_tuples = tuple(item.identity_tuple for item in self.selected_versions)
        if (
            len(selected_identity_tuples) != len(set(selected_identity_tuples))
            or self.selected_versions != member_versions
        ):
            raise ValueError("actual selected versions do not exactly match members")
        _require_sha256(self.selected_versions_hash, "actual selected_versions_hash")
        selected_payload: dict[str, object] = {
            "schema": "r1-actual-selected-versions.v1",
            "versions": [list(item.identity_tuple) for item in self.selected_versions],
        }
        if self.selected_versions_hash != _hash_payload(selected_payload):
            raise ValueError("actual selected versions hash mismatch")
        _require_sha256(self.seal_hash, "actual manifest seal_hash")
        if self.seal_hash != _hash_payload(_evaluation_actual_manifest_payload_from_domain(self)):
            raise ValueError("actual manifest seal hash mismatch")


def _evaluation_actual_manifest_payload_from_domain(
    manifest: EvaluationActualManifest,
) -> dict[str, object]:
    return _evaluation_actual_manifest_payload(
        manifest_id=manifest.manifest_id,
        manifest_version=manifest.manifest_version,
        manifest_content_hash=manifest.manifest_content_hash,
        owner=manifest.owner,
        subject_code=manifest.subject_code,
        industry_code=manifest.industry_code,
        dataset=manifest.dataset,
        calendar_id=manifest.calendar_id,
        calendar_version=manifest.calendar_version,
        calendar_content_hash=manifest.calendar_content_hash,
        as_of_time=manifest.as_of_time,
        produced_at=manifest.produced_at,
        knowledge_scope=manifest.knowledge_scope,
        is_verified=manifest.is_verified,
        coverage_ratio=manifest.coverage_ratio,
        missing_count=manifest.missing_count,
        estimated_count=manifest.estimated_count,
        unknown_count=manifest.unknown_count,
        selected_versions=manifest.selected_versions,
        selected_versions_hash=manifest.selected_versions_hash,
        members=manifest.members,
    )


def _evaluation_actual_manifest_payload(
    *,
    manifest_id: str,
    manifest_version: str,
    manifest_content_hash: str,
    owner: str,
    subject_code: str,
    industry_code: str,
    dataset: str,
    calendar_id: str,
    calendar_version: str,
    calendar_content_hash: str,
    as_of_time: datetime,
    produced_at: datetime,
    knowledge_scope: str,
    is_verified: bool,
    coverage_ratio: Decimal,
    missing_count: int,
    estimated_count: int,
    unknown_count: int,
    selected_versions: tuple[BaselinePITSelectedVersion, ...],
    selected_versions_hash: str,
    members: tuple[ActualFactObservation, ...],
) -> dict[str, object]:
    return {
        "schema": "r1-evaluation-actual-manifest.v2",
        "manifest": [manifest_id, manifest_version, manifest_content_hash, owner],
        "scope": [subject_code, industry_code, dataset],
        "calendar": [calendar_id, calendar_version, calendar_content_hash],
        "semantics": [
            _utc_text(as_of_time),
            _utc_text(produced_at),
            knowledge_scope,
            is_verified,
            _decimal_text(coverage_ratio),
            missing_count,
            estimated_count,
            unknown_count,
        ],
        "selected_versions": [list(item.identity_tuple) for item in selected_versions],
        "selected_versions_hash": selected_versions_hash,
        "members": [
            [
                item.period_end.isoformat(),
                item.metric_code,
                item.manifest_member_id,
                item.manifest_member_version,
                item.manifest_member_content_hash,
                item.source_fact_id,
                item.source_fact_version,
                item.source_fact_content_hash,
                item.revision_number,
                item.vintage_id,
                item.vintage_version,
                item.vintage_content_hash,
                item.observation_hash,
            ]
            for item in members
        ],
    }


__all__ = [
    "ActualRevisionRule",
    "ActualVintageRule",
    "EvaluationActualManifest",
    "ForecastEvaluationPolicy",
    "ForecastFreezeRule",
    "ResearchTrialAuthorization",
]
