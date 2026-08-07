"""Strict Django persistence and PIT query for R7 sample policies."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.research.application.r7_sample_policy import (
    R7SamplePolicyConflict,
    R7SamplePolicyCorruption,
    R7SamplePolicyOwnerApproval,
    R7SamplePolicyUnavailable,
    RiskCenterR7SamplePolicyApprovalQuery,
)
from apps.research.domain.r7_sample_policy import (
    PersistedR7SamplePolicy,
    R7SamplePolicyAuthorization,
)
from apps.research.domain.scenario_probability_contracts import (
    ScenarioProbabilityResearchPolicy,
    ScenarioResearchScope,
)
from apps.research.domain.scenario_research_hashing import hash_components
from apps.research.infrastructure.r7_sample_policy_codec import (
    R7SamplePolicyCodecError,
    decode_persisted_r7_sample_policy,
    decode_r7_sample_policy_authorization,
    encode_persisted_r7_sample_policy,
    encode_r7_sample_policy_authorization,
)
from apps.research.infrastructure.r7_sample_policy_models import (
    R7SamplePolicyApprovalReceiptModel,
    R7SamplePolicyModel,
    _activate_r7_sample_policy_uow,
    _claim_r7_sample_policy_insert,
    _require_active_r7_sample_policy_uow,
)


class R7SamplePolicyClock(Protocol):
    """Authoritative repository clock."""

    def now(self) -> datetime:
        """Return a timezone-aware server time."""


class DjangoR7SamplePolicyClock:
    """Django timezone-backed server clock."""

    def now(self) -> datetime:
        return timezone.now()


def r7_sample_policy_approval_record_hash(
    authorization: R7SamplePolicyAuthorization,
    *,
    recorded_at: datetime,
) -> str:
    """Seal the external receipt to the Research server knowledge clock."""

    return hash_components(
        "r7-sample-policy-approval-record.v1",
        authorization.content_hash,
        recorded_at.isoformat(),
    )


class DjangoR7SamplePolicyRepository:
    """Public read-only exact/PIT policy repository."""

    __slots__ = ("_clock", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: R7SamplePolicyClock | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoR7SamplePolicyClock()

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def get_exact(
        self,
        *,
        policy_id: str,
        policy_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedR7SamplePolicy | None:
        """Restore by identity first so header/hash tampering cannot hide."""

        self._require_pit_cutoff(as_of)
        models = list(
            R7SamplePolicyModel._default_manager.using(self._using)
            .select_related("approval")
            .filter(
                Q(policy_id=policy_id, policy_version=policy_version)
                | Q(approval__policy_id=policy_id, approval__policy_version=policy_version)
                | Q(content_hash=expected_content_hash)
            )
        )
        if not models:
            return None
        records = tuple(self._restore(model) for model in models)
        matches = tuple(
            record
            for record in records
            if record.policy_id == policy_id
            and record.policy_version == policy_version
            and record.content_hash == expected_content_hash
        )
        if len(matches) > 1:
            raise R7SamplePolicyCorruption(
                "multiple R7 sample policies match one exact identity and content hash"
            )
        if not matches or matches[0].recorded_at > as_of:
            return None
        return matches[0]

    def get_active_record(
        self,
        *,
        scope: ScenarioResearchScope,
        as_of: datetime,
    ) -> PersistedR7SamplePolicy:
        """Return exactly one scope policy active and knowable at ``as_of``."""

        self._require_pit_cutoff(as_of)
        models = list(
            R7SamplePolicyModel._default_manager.using(self._using)
            .select_related("approval")
            .filter(
                Q(scope_content_hash=scope.content_hash)
                | Q(approval__scope_content_hash=scope.content_hash)
            )
        )
        if not models:
            raise R7SamplePolicyUnavailable(
                "no persisted approved R7 sample policy is active at the PIT cutoff"
            )
        records = tuple(self._restore(model) for model in models)
        active_records = tuple(
            record
            for record in records
            if record.scope == scope
            and record.recorded_at <= as_of
            and record.policy.is_active(as_of)
            and record.authorization.issued_at <= as_of < record.authorization.valid_until
        )
        if len(active_records) > 1:
            raise R7SamplePolicyCorruption(
                "multiple R7 sample policies are active for one exact scope"
            )
        if not active_records:
            raise R7SamplePolicyUnavailable(
                "no persisted approved R7 sample policy is active at the PIT cutoff"
            )
        return active_records[0]

    def _require_pit_cutoff(self, as_of: datetime) -> None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise R7SamplePolicyUnavailable("R7 sample policy as_of must be timezone-aware")
        now = self._clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise R7SamplePolicyCorruption("R7 sample policy server clock is naive")
        if as_of > now:
            raise R7SamplePolicyUnavailable("future R7 sample policy as_of is not permitted")

    def _restore(self, model: R7SamplePolicyModel) -> PersistedR7SamplePolicy:
        approval_model = model.approval
        try:
            authorization = decode_r7_sample_policy_authorization(approval_model.canonical_payload)
            record = decode_persisted_r7_sample_policy(model.canonical_payload)
        except R7SamplePolicyCodecError:
            raise
        if _authorization_headers(authorization) != _approval_model_headers(approval_model):
            raise R7SamplePolicyCorruption("R7 approval receipt header mismatch")
        expected_approval_record_hash = r7_sample_policy_approval_record_hash(
            authorization,
            recorded_at=approval_model.recorded_at,
        )
        if approval_model.record_hash != expected_approval_record_hash:
            raise R7SamplePolicyCorruption("R7 approval receipt record_hash mismatch")
        if record.authorization != authorization:
            raise R7SamplePolicyCorruption("R7 policy/approval payload substitution")
        if model.approval_id != approval_model.pk:
            raise R7SamplePolicyCorruption("R7 policy approval FK mismatch")
        if _record_headers(record) != _policy_model_headers(model):
            raise R7SamplePolicyCorruption("R7 sample policy header mismatch")
        if model.recorded_at != approval_model.recorded_at:
            raise R7SamplePolicyCorruption("R7 approval/policy knowledge clock mismatch")
        return record


class DjangoR7SamplePolicyProvider:
    """Concrete production provider for packet construction."""

    def __init__(self, repository: DjangoR7SamplePolicyRepository) -> None:
        self._repository = repository

    def get_active(
        self,
        *,
        scope: ScenarioResearchScope,
        evaluated_at: datetime,
    ) -> ScenarioProbabilityResearchPolicy:
        """Return only a strictly restored persisted approved policy."""

        return self._repository.get_active_record(scope=scope, as_of=evaluated_at).policy


class DjangoR7SamplePolicyAuthorizationProvider:
    """Concrete Research adapter for Risk Center's owner Application port."""

    def __init__(self, source: RiskCenterR7SamplePolicyApprovalQuery) -> None:
        self._source = source

    @property
    def unit_of_work_key(self) -> str:
        return self._source.unit_of_work_key

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
        """Read owner evidence only while the Research UoW is active."""

        _require_active_r7_sample_policy_uow()
        return self._source.get_exact(
            authorization_id=authorization_id,
            authorization_version=authorization_version,
            policy_id=policy_id,
            policy_version=policy_version,
            scope_content_hash=scope_content_hash,
            policy_definition_hash=policy_definition_hash,
            as_of=as_of,
        )


class _DjangoR7SamplePolicyStore:
    """Private write capability retained by the composition root."""

    __slots__ = ("_token", "_using")

    def __init__(self, *, using: str = "default") -> None:
        self._using = using
        self._token = object()

    @property
    def unit_of_work_key(self) -> str:
        return f"django:{self._using}"

    def atomic(self) -> AbstractContextManager[None]:
        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with transaction.atomic(using=self._using), _activate_r7_sample_policy_uow(self._token):
            yield

    def append(self, record: PersistedR7SamplePolicy) -> PersistedR7SamplePolicy:
        """Append approval then policy; any loser/error rolls both rows back."""

        if (
            R7SamplePolicyApprovalReceiptModel._default_manager.using(self._using)
            .filter(
                authorization_id=record.authorization.authorization_id,
                authorization_version=record.authorization.authorization_version,
            )
            .exists()
            or R7SamplePolicyModel._default_manager.using(self._using)
            .filter(policy_id=record.policy_id, policy_version=record.policy_version)
            .exists()
        ):
            raise R7SamplePolicyConflict("R7 sample policy identity already sealed")
        approval_values = _approval_values(record)
        with _claim_r7_sample_policy_insert(
            token=self._token,
            model_type=R7SamplePolicyApprovalReceiptModel,
            expected_values=approval_values,
        ):
            approval_model = R7SamplePolicyApprovalReceiptModel._default_manager.using(
                self._using
            ).create(**approval_values)
        policy_values = _policy_values(record)
        claim_values = {**policy_values, "approval_id": approval_model.pk}
        with _claim_r7_sample_policy_insert(
            token=self._token,
            model_type=R7SamplePolicyModel,
            expected_values=claim_values,
        ):
            R7SamplePolicyModel._default_manager.using(self._using).create(
                approval=approval_model,
                **policy_values,
            )
        return record


def _approval_values(record: PersistedR7SamplePolicy) -> dict[str, object]:
    item = record.authorization
    return {
        "authorization_id": item.authorization_id,
        "authorization_version": item.authorization_version,
        "owner_record_id": item.owner_record_id,
        "owner_record_version": item.owner_record_version,
        "owner_record_hash": item.owner_record_hash,
        "policy_id": item.policy_id,
        "policy_version": item.policy_version,
        "scope_content_hash": item.scope_content_hash,
        "policy_definition_hash": item.policy_definition_hash,
        "approved_by": item.approved_by,
        "issued_at": item.issued_at,
        "valid_until": item.valid_until,
        "recorded_at": record.recorded_at,
        "canonical_payload": encode_r7_sample_policy_authorization(item),
        "authorization_content_hash": item.content_hash,
        "record_hash": r7_sample_policy_approval_record_hash(
            item,
            recorded_at=record.recorded_at,
        ),
    }


def _policy_values(record: PersistedR7SamplePolicy) -> dict[str, object]:
    policy = record.policy
    return {
        "policy_id": record.policy_id,
        "policy_version": record.policy_version,
        "scope_content_hash": record.scope.content_hash,
        "policy_content_hash": policy.content_hash,
        "authorization_content_hash": record.authorization.content_hash,
        "activated_at": policy.activated_at,
        "valid_until": policy.valid_until,
        "sample_window_start": policy.sample_window_start,
        "sample_window_end": policy.sample_window_end,
        "forecast_horizon_seconds": Decimal(str(policy.forecast_horizon.total_seconds())),
        "censoring_lag_seconds": Decimal(str(policy.censoring_lag.total_seconds())),
        "censoring_rule_version": policy.censoring_rule_version,
        "minimum_forecasts_per_revision": policy.minimum_forecasts_per_revision,
        "minimum_resolved_outcomes_per_revision": (policy.minimum_resolved_outcomes_per_revision),
        "minimum_binary_class_observations": policy.minimum_binary_class_observations,
        "minimum_multiclass_groups": policy.minimum_multiclass_groups,
        "minimum_multiclass_class_observations": (policy.minimum_multiclass_class_observations),
        "minimum_historical_analogies": policy.minimum_historical_analogies,
        "minimum_path_probability_observations": (policy.minimum_path_probability_observations),
        "path_horizon_periods": policy.path_horizon_periods,
        "require_all_path_initial_states": policy.require_all_path_initial_states,
        "recorded_at": record.recorded_at,
        "canonical_payload": encode_persisted_r7_sample_policy(record),
        "content_hash": record.content_hash,
        "research_only": record.research_only,
        "must_not_use_for_decision": record.must_not_use_for_decision,
        "must_not_execute": record.must_not_execute,
    }


def _authorization_headers(
    value: R7SamplePolicyAuthorization,
) -> tuple[object, ...]:
    return (
        value.authorization_id,
        value.authorization_version,
        value.owner_record_id,
        value.owner_record_version,
        value.owner_record_hash,
        value.policy_id,
        value.policy_version,
        value.scope_content_hash,
        value.policy_definition_hash,
        value.approved_by,
        value.issued_at,
        value.valid_until,
        value.content_hash,
    )


def _approval_model_headers(
    value: R7SamplePolicyApprovalReceiptModel,
) -> tuple[object, ...]:
    return (
        value.authorization_id,
        value.authorization_version,
        value.owner_record_id,
        value.owner_record_version,
        value.owner_record_hash,
        value.policy_id,
        value.policy_version,
        value.scope_content_hash,
        value.policy_definition_hash,
        value.approved_by,
        value.issued_at,
        value.valid_until,
        value.authorization_content_hash,
    )


def _record_headers(value: PersistedR7SamplePolicy) -> tuple[object, ...]:
    policy = value.policy
    return (
        value.policy_id,
        value.policy_version,
        value.scope.content_hash,
        policy.content_hash,
        value.authorization.content_hash,
        policy.activated_at,
        policy.valid_until,
        policy.sample_window_start,
        policy.sample_window_end,
        Decimal(str(policy.forecast_horizon.total_seconds())),
        Decimal(str(policy.censoring_lag.total_seconds())),
        policy.censoring_rule_version,
        policy.minimum_forecasts_per_revision,
        policy.minimum_resolved_outcomes_per_revision,
        policy.minimum_binary_class_observations,
        policy.minimum_multiclass_groups,
        policy.minimum_multiclass_class_observations,
        policy.minimum_historical_analogies,
        policy.minimum_path_probability_observations,
        policy.path_horizon_periods,
        policy.require_all_path_initial_states,
        value.recorded_at,
        value.content_hash,
        value.research_only,
        value.must_not_use_for_decision,
        value.must_not_execute,
    )


def _policy_model_headers(value: R7SamplePolicyModel) -> tuple[object, ...]:
    return (
        value.policy_id,
        value.policy_version,
        value.scope_content_hash,
        value.policy_content_hash,
        value.authorization_content_hash,
        value.activated_at,
        value.valid_until,
        value.sample_window_start,
        value.sample_window_end,
        value.forecast_horizon_seconds,
        value.censoring_lag_seconds,
        value.censoring_rule_version,
        value.minimum_forecasts_per_revision,
        value.minimum_resolved_outcomes_per_revision,
        value.minimum_binary_class_observations,
        value.minimum_multiclass_groups,
        value.minimum_multiclass_class_observations,
        value.minimum_historical_analogies,
        value.minimum_path_probability_observations,
        value.path_horizon_periods,
        value.require_all_path_initial_states,
        value.recorded_at,
        value.content_hash,
        value.research_only,
        value.must_not_use_for_decision,
        value.must_not_execute,
    )


__all__ = [
    "DjangoR7SamplePolicyClock",
    "DjangoR7SamplePolicyAuthorizationProvider",
    "DjangoR7SamplePolicyProvider",
    "DjangoR7SamplePolicyRepository",
    "R7SamplePolicyClock",
    "r7_sample_policy_approval_record_hash",
]
