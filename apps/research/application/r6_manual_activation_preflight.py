"""Read-only R6 preflight for a later manual activation review."""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Protocol

from apps.research.application.state_model_monitoring import (
    ActiveR6QualificationEvidence,
)
from apps.research.domain.state_model_activation import (
    R6ActivationApprovalRef,
    R6ActivationScope,
    R6MonitoringActivationEvidence,
    R6MonitoringActivationStatus,
    validate_r6_activation_scope,
    validate_r6_monitoring_activation_evidence,
)
from apps.research.domain.state_model_qualification_lifecycle import (
    R6QualificationRef,
)


class R6ManualActivationUnavailable(RuntimeError):
    """The request or its shared read boundary cannot be trusted."""


class R6ManualActivationPreflightStatus(StrEnum):
    """The only states published by this non-authoritative boundary."""

    ELIGIBLE_FOR_MANUAL_ACTIVATION_REVIEW = "eligible_for_manual_activation_review"
    BLOCKED = "blocked"


class R6ManualActivationBlockerCode(StrEnum):
    """Stable fail-closed outcomes that never grant activation authority."""

    SCOPE_OWNER_UNAVAILABLE = "scope_owner_unavailable"
    ACTIVE_QUALIFICATION_UNAVAILABLE = "active_qualification_unavailable"
    MONITORING_ASSESSMENT_UNAVAILABLE = "monitoring_assessment_unavailable"
    LATEST_MONITORING_BREACHED = "latest_monitoring_breached"
    LATEST_MONITORING_REQUIRES_RETIREMENT_REVIEW = "latest_monitoring_requires_retirement_review"
    LATEST_MONITORING_BLOCKED = "latest_monitoring_blocked"
    ACTIVATION_ALREADY_PRESENT = "activation_already_present"
    OWNER_GRAPH_SUBSTITUTED = "owner_graph_substituted"
    OWNER_GRAPH_CHANGED_DURING_PREFLIGHT = "owner_graph_changed_during_preflight"
    OWNER_PROVIDER_UNAVAILABLE = "owner_provider_unavailable"
    UNIT_OF_WORK_CHANGED = "unit_of_work_changed"


def _require_token(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 300
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{label} must be a bounded non-blank token")
    return value


def _require_aware(value: object, label: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def _require_hash(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise ValueError(f"{label} must be a SHA-256 digest")
    return value.lower()


@dataclass(frozen=True)
class EvaluateR6ManualActivationPreflightCommand:
    """Scope/PIT-only request; no assessment, health, or event is accepted."""

    scope_id: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.scope_id, "R6 manual activation scope_id")
        _require_aware(self.as_of, "R6 manual activation as_of")


@dataclass(frozen=True)
class R6ManualActivationPreflightResult:
    """Research-only review eligibility with no activation or consumer authority."""

    scope_id: str
    as_of: datetime
    status: R6ManualActivationPreflightStatus
    blocker_codes: tuple[R6ManualActivationBlockerCode, ...]
    scope_hash: str | None
    qualification_hash: str | None
    monitoring_hash: str | None
    active_approval_hash: str | None
    research_only: bool = True
    must_not_publish_current: bool = True
    must_not_use_for_decision: bool = True
    must_not_replace_regime: bool = True
    must_not_execute: bool = True
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_token(self.scope_id, "R6 manual activation result scope_id")
        _require_aware(self.as_of, "R6 manual activation result as_of")
        if type(self.status) is not R6ManualActivationPreflightStatus:
            raise TypeError("R6 manual activation result status differs")
        if type(self.blocker_codes) is not tuple or self.blocker_codes != tuple(
            sorted(set(self.blocker_codes), key=lambda item: item.value)
        ):
            raise ValueError("R6 manual activation blockers are not canonical")
        if any(type(item) is not R6ManualActivationBlockerCode for item in self.blocker_codes):
            raise TypeError("R6 manual activation blocker type differs")
        if (self.status is R6ManualActivationPreflightStatus.BLOCKED) != bool(self.blocker_codes):
            raise ValueError("R6 manual activation status and blockers differ")
        for label, value in (
            ("scope_hash", self.scope_hash),
            ("qualification_hash", self.qualification_hash),
            ("monitoring_hash", self.monitoring_hash),
            ("active_approval_hash", self.active_approval_hash),
        ):
            if value is not None:
                _require_hash(value, f"R6 manual activation result {label}")
        if not (
            self.research_only
            and self.must_not_publish_current
            and self.must_not_use_for_decision
            and self.must_not_replace_regime
            and self.must_not_execute
        ):
            raise ValueError("R6 manual activation result safety boundary differs")
        object.__setattr__(self, "content_hash", _result_hash(self))


def _result_hash(result: R6ManualActivationPreflightResult) -> str:
    payload = {
        "schema": "research-r6-manual-activation-preflight-result.v1",
        "scope_id": result.scope_id,
        "as_of": result.as_of.astimezone(UTC).isoformat(),
        "status": result.status.value,
        "blockers": [item.value for item in result.blocker_codes],
        "scope_hash": result.scope_hash,
        "qualification_hash": result.qualification_hash,
        "monitoring_hash": result.monitoring_hash,
        "active_approval_hash": result.active_approval_hash,
        "research_only": True,
        "must_not_publish_current": True,
        "must_not_use_for_decision": True,
        "must_not_replace_regime": True,
        "must_not_execute": True,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


class R6ManualActivationScopeProvider(Protocol):
    """Canonical owner of one exact existing activation scope."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared read transaction identity."""

    def get_exact(self, *, scope_id: str, as_of: datetime) -> R6ActivationScope | None:
        """Return an owner-defined scope without accepting caller scope content."""


class R6ManualActivationQualificationProvider(Protocol):
    """Server-selecting reader for the latest promoted qualification."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared read transaction identity."""

    def get_latest_active(
        self,
        *,
        scope: R6ActivationScope,
        as_of: datetime,
    ) -> ActiveR6QualificationEvidence | None:
        """Return the canonical active winner selected for this exact scope."""


class R6ManualActivationMonitoringProvider(Protocol):
    """Server-selecting latest-complete R6 monitoring reader."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared read transaction identity."""

    def get_latest_complete(
        self,
        *,
        scope: R6ActivationScope,
        qualification: ActiveR6QualificationEvidence,
        as_of: datetime,
    ) -> R6MonitoringActivationEvidence | None:
        """Return the latest complete period, never caller-selected health."""


class R6ManualActivationStateProvider(Protocol):
    """Read the existing activation stream without exposing events to callers."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared read transaction identity."""

    def get_active_approval_ref(
        self,
        *,
        scope: R6ActivationScope,
        as_of: datetime,
    ) -> R6ActivationApprovalRef | None:
        """Return the derived active stack head or explicit absence."""


class R6ManualActivationUnitOfWork(Protocol):
    """One shared read transaction and trusted database clock."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the shared read transaction."""

    def server_now(self) -> datetime:
        """Read authoritative time from inside the transaction."""


@dataclass(frozen=True)
class _OwnerGraph:
    scope: R6ActivationScope | None
    qualification: ActiveR6QualificationEvidence | None
    monitoring: R6MonitoringActivationEvidence | None
    active_approval: R6ActivationApprovalRef | None


class EvaluateR6ManualActivationPreflight:
    """Double-read owner evidence and emit only manual-review eligibility."""

    def __init__(
        self,
        *,
        scope_provider: R6ManualActivationScopeProvider,
        qualification_provider: R6ManualActivationQualificationProvider,
        monitoring_provider: R6ManualActivationMonitoringProvider,
        activation_state_provider: R6ManualActivationStateProvider,
        unit_of_work: R6ManualActivationUnitOfWork,
    ) -> None:
        self._scope_provider = scope_provider
        self._qualification_provider = qualification_provider
        self._monitoring_provider = monitoring_provider
        self._activation_state_provider = activation_state_provider
        self._unit_of_work = unit_of_work
        try:
            keys = self._current_uow_keys()
        except Exception as error:
            raise R6ManualActivationUnavailable(
                "R6 manual activation unit of work is unavailable"
            ) from error
        if len(set(keys)) != 1:
            raise R6ManualActivationUnavailable(
                "R6 manual activation owners use different unit of work identities"
            )
        self._expected_uow_key = keys[0]

    def execute(
        self,
        command: EvaluateR6ManualActivationPreflightCommand,
    ) -> R6ManualActivationPreflightResult:
        """Evaluate a stable PIT graph without writes or consumer side effects."""

        self._require_command(command)
        try:
            with self._unit_of_work.atomic():
                self._require_unchanged_uow()
                server_now = _require_aware(
                    self._unit_of_work.server_now(),
                    "R6 manual activation server_now",
                )
                self._require_unchanged_uow()
                if command.as_of > server_now:
                    raise R6ManualActivationUnavailable(
                        "R6 manual activation command uses a future as_of"
                    )
                first = self._read_graph(command)
                self._require_unchanged_uow()
                second = self._read_graph(command)
                self._require_unchanged_uow()
        except R6ManualActivationUnavailable:
            raise
        except _UnitOfWorkChanged:
            return self._blocked(command, R6ManualActivationBlockerCode.UNIT_OF_WORK_CHANGED)
        except Exception:
            return self._blocked(
                command,
                R6ManualActivationBlockerCode.OWNER_PROVIDER_UNAVAILABLE,
            )
        if first != second:
            return self._blocked(
                command,
                R6ManualActivationBlockerCode.OWNER_GRAPH_CHANGED_DURING_PREFLIGHT,
            )
        return self._evaluate(command, second)

    def _read_graph(
        self,
        command: EvaluateR6ManualActivationPreflightCommand,
    ) -> _OwnerGraph:
        self._require_unchanged_uow()
        scope = _copy_scope(
            self._scope_provider.get_exact(scope_id=command.scope_id, as_of=command.as_of)
        )
        self._require_unchanged_uow()
        if scope is None:
            return _OwnerGraph(None, None, None, None)
        qualification = _copy_qualification(
            self._qualification_provider.get_latest_active(
                scope=scope,
                as_of=command.as_of,
            )
        )
        self._require_unchanged_uow()
        if qualification is None:
            return _OwnerGraph(scope, None, None, None)
        monitoring = _copy_monitoring(
            self._monitoring_provider.get_latest_complete(
                scope=scope,
                qualification=qualification,
                as_of=command.as_of,
            )
        )
        self._require_unchanged_uow()
        if monitoring is None:
            return _OwnerGraph(scope, qualification, None, None)
        active_approval = _copy_approval_ref(
            self._activation_state_provider.get_active_approval_ref(
                scope=scope,
                as_of=command.as_of,
            )
        )
        self._require_unchanged_uow()
        return _OwnerGraph(scope, qualification, monitoring, active_approval)

    def _evaluate(
        self,
        command: EvaluateR6ManualActivationPreflightCommand,
        graph: _OwnerGraph,
    ) -> R6ManualActivationPreflightResult:
        scope = graph.scope
        qualification = graph.qualification
        monitoring = graph.monitoring
        if scope is None:
            return self._blocked(command, R6ManualActivationBlockerCode.SCOPE_OWNER_UNAVAILABLE)
        if qualification is None:
            return self._blocked(
                command,
                R6ManualActivationBlockerCode.ACTIVE_QUALIFICATION_UNAVAILABLE,
                graph=graph,
            )
        if monitoring is None:
            return self._blocked(
                command,
                R6ManualActivationBlockerCode.MONITORING_ASSESSMENT_UNAVAILABLE,
                graph=graph,
            )
        if not (
            scope.scope_id == command.scope_id
            and qualification.assessed_at <= qualification.known_at <= command.as_of
            and monitoring.qualification_ref == qualification.qualification_ref
            and monitoring.label_protocol_version == scope.label_protocol_version
            and monitoring.evaluated_at <= monitoring.recorded_at <= command.as_of
            and monitoring.is_active_at(command.as_of)
        ):
            return self._blocked(
                command,
                R6ManualActivationBlockerCode.OWNER_GRAPH_SUBSTITUTED,
                graph=graph,
            )
        if graph.active_approval is not None:
            return self._blocked(
                command,
                R6ManualActivationBlockerCode.ACTIVATION_ALREADY_PRESENT,
                graph=graph,
            )
        blocker_by_status = {
            R6MonitoringActivationStatus.BREACHED: (
                R6ManualActivationBlockerCode.LATEST_MONITORING_BREACHED
            ),
            R6MonitoringActivationStatus.RETIREMENT_REVIEW_REQUIRED: (
                R6ManualActivationBlockerCode.LATEST_MONITORING_REQUIRES_RETIREMENT_REVIEW
            ),
            R6MonitoringActivationStatus.BLOCKED: (
                R6ManualActivationBlockerCode.LATEST_MONITORING_BLOCKED
            ),
        }
        blocker = blocker_by_status.get(monitoring.status)
        if blocker is not None:
            return self._blocked(command, blocker, graph=graph)
        return R6ManualActivationPreflightResult(
            scope_id=command.scope_id,
            as_of=command.as_of,
            status=(R6ManualActivationPreflightStatus.ELIGIBLE_FOR_MANUAL_ACTIVATION_REVIEW),
            blocker_codes=(),
            scope_hash=scope.content_hash,
            qualification_hash=qualification.content_hash,
            monitoring_hash=monitoring.content_hash,
            active_approval_hash=None,
        )

    @staticmethod
    def _blocked(
        command: EvaluateR6ManualActivationPreflightCommand,
        blocker: R6ManualActivationBlockerCode,
        *,
        graph: _OwnerGraph | None = None,
    ) -> R6ManualActivationPreflightResult:
        return R6ManualActivationPreflightResult(
            scope_id=command.scope_id,
            as_of=command.as_of,
            status=R6ManualActivationPreflightStatus.BLOCKED,
            blocker_codes=(blocker,),
            scope_hash=None if graph is None or graph.scope is None else graph.scope.content_hash,
            qualification_hash=(
                None
                if graph is None or graph.qualification is None
                else graph.qualification.content_hash
            ),
            monitoring_hash=(
                None if graph is None or graph.monitoring is None else graph.monitoring.content_hash
            ),
            active_approval_hash=(
                None
                if graph is None or graph.active_approval is None
                else graph.active_approval.approval_hash
            ),
        )

    @staticmethod
    def _require_command(command: object) -> None:
        try:
            if type(command) is not EvaluateR6ManualActivationPreflightCommand:
                raise TypeError
            EvaluateR6ManualActivationPreflightCommand.__post_init__(command)
        except (AttributeError, TypeError, ValueError) as error:
            raise R6ManualActivationUnavailable(
                "R6 manual activation command is malformed"
            ) from error

    def _current_uow_keys(self) -> tuple[str, ...]:
        values: tuple[object, ...] = (
            self._scope_provider.unit_of_work_key,
            self._qualification_provider.unit_of_work_key,
            self._monitoring_provider.unit_of_work_key,
            self._activation_state_provider.unit_of_work_key,
            self._unit_of_work.unit_of_work_key,
        )
        return tuple(_exact_uow_key(value) for value in values)

    def _require_unchanged_uow(self) -> None:
        try:
            keys = self._current_uow_keys()
        except Exception as error:
            raise _UnitOfWorkChanged from error
        if any(value != self._expected_uow_key for value in keys):
            raise _UnitOfWorkChanged


class _UnitOfWorkChanged(RuntimeError):
    pass


def _exact_uow_key(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise TypeError("R6 manual activation unit_of_work_key must be an exact string")
    return value


def _copy_scope(value: object) -> R6ActivationScope | None:
    if value is None:
        return None
    if type(value) is not R6ActivationScope:
        raise TypeError("R6 manual activation scope provider returned another type")
    validate_r6_activation_scope(value)
    copied = R6ActivationScope(
        scope_id=value.scope_id,
        scope_version=value.scope_version,
        purpose=value.purpose,
        label_protocol_version=value.label_protocol_version,
        research_only=value.research_only,
        must_not_use_for_decision=value.must_not_use_for_decision,
        must_not_replace_regime=value.must_not_replace_regime,
        must_not_publish_current=value.must_not_publish_current,
        must_not_execute=value.must_not_execute,
    )
    if copied != value:
        raise ValueError("R6 manual activation scope was substituted")
    return copied


def _copy_qualification(value: object) -> ActiveR6QualificationEvidence | None:
    if value is None:
        return None
    if type(value) is not ActiveR6QualificationEvidence:
        raise TypeError("R6 manual activation qualification provider returned another type")
    qualification_ref = _copy_qualification_ref(value.qualification_ref)
    copied = ActiveR6QualificationEvidence(
        qualification_ref=qualification_ref,
        candidate_id=value.candidate_id,
        candidate_version=value.candidate_version,
        assessed_at=value.assessed_at,
        known_at=value.known_at,
        research_only=value.research_only,
        must_not_use_for_decision=value.must_not_use_for_decision,
        must_not_replace_regime=value.must_not_replace_regime,
    )
    if copied != value:
        raise ValueError("R6 manual activation qualification was substituted")
    return copied


def _copy_monitoring(value: object) -> R6MonitoringActivationEvidence | None:
    if value is None:
        return None
    if type(value) is not R6MonitoringActivationEvidence:
        raise TypeError("R6 manual activation monitoring provider returned another type")
    validate_r6_monitoring_activation_evidence(value)
    qualification_ref = _copy_qualification_ref(value.qualification_ref)
    copied = R6MonitoringActivationEvidence(
        assessment_id=value.assessment_id,
        assessment_hash=value.assessment_hash,
        qualification_ref=qualification_ref,
        policy_id=value.policy_id,
        policy_version=value.policy_version,
        policy_hash=value.policy_hash,
        label_protocol_version=value.label_protocol_version,
        label_set_hash=value.label_set_hash,
        status=value.status,
        evaluated_at=value.evaluated_at,
        recorded_at=value.recorded_at,
        valid_until=value.valid_until,
        owner=value.owner,
        evidence_ref=value.evidence_ref,
        retirement_review_required=value.retirement_review_required,
        research_only=value.research_only,
        must_not_use_for_decision=value.must_not_use_for_decision,
        must_not_replace_regime=value.must_not_replace_regime,
        must_not_publish_current=value.must_not_publish_current,
        must_not_execute=value.must_not_execute,
    )
    if copied != value:
        raise ValueError("R6 manual activation monitoring was substituted")
    return copied


def _copy_qualification_ref(value: object) -> R6QualificationRef:
    if type(value) is not R6QualificationRef:
        raise TypeError("R6 manual activation qualification ref type differs")
    R6QualificationRef.__post_init__(value)
    return R6QualificationRef(value.assessment_id, value.assessment_hash)


def _copy_approval_ref(value: object) -> R6ActivationApprovalRef | None:
    if value is None:
        return None
    if type(value) is not R6ActivationApprovalRef:
        raise TypeError("R6 manual activation state provider returned another type")
    R6ActivationApprovalRef.__post_init__(value)
    return R6ActivationApprovalRef(
        value.approval_id,
        value.approval_version,
        value.approval_hash,
    )


__all__ = [
    "EvaluateR6ManualActivationPreflight",
    "EvaluateR6ManualActivationPreflightCommand",
    "R6ManualActivationBlockerCode",
    "R6ManualActivationMonitoringProvider",
    "R6ManualActivationPreflightResult",
    "R6ManualActivationPreflightStatus",
    "R6ManualActivationQualificationProvider",
    "R6ManualActivationScopeProvider",
    "R6ManualActivationStateProvider",
    "R6ManualActivationUnavailable",
    "R6ManualActivationUnitOfWork",
]
