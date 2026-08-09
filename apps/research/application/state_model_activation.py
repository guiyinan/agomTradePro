"""ID-only owner orchestration for separate R6 activation and rollback.

The use cases expose an auditable activation control-plane state only.  They do
not publish a current model, replace Regime, authorize a decision, or execute.
Phase B provides append-only persistence behind these ports.  Concrete
canonical owner adapters remain unavailable, so production mutation surfaces
stay inert and no consumer is connected.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol, TypeVar

from apps.research.application.state_model_monitoring import ActiveR6QualificationEvidence
from apps.research.domain.state_model_activation import (
    R6ActivationAction,
    R6ActivationApproval,
    R6ActivationApprovalOutcome,
    R6ActivationApprovalRef,
    R6ActivationAuthorization,
    R6ActivationAuthorizationRef,
    R6ActivationEvent,
    R6ActivationScopeRef,
    R6ActivationState,
    R6MonitoringActivationEvidence,
    R6MonitoringActivationRef,
    R6MonitoringActivationStatus,
    create_r6_activation_event,
    derive_r6_activation_state,
    validate_r6_activation_approval,
    validate_r6_activation_authorization,
    validate_r6_monitoring_activation_evidence,
)
from apps.research.domain.state_model_qualification_contracts import _canonical_hash
from apps.research.domain.state_model_qualification_lifecycle import R6QualificationRef

_T = TypeVar("_T")


class R6ActivationUnavailable(RuntimeError):
    """Canonical owner evidence or a trusted cutoff is unavailable."""


class R6ActivationCorruption(RuntimeError):
    """A stored activation prefix or returned winner failed exact replay."""


class R6ActivationConflict(RuntimeError):
    """An append race produced a different immutable event winner."""


class R6ActivationClock(Protocol):
    """Trusted server clock for writes and future-query rejection."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class _UnitOfWorkProvider(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return an explicit shared transaction identity."""


class R6ActivationApprovalProvider(Protocol):
    """Canonical Research owner of activation approvals."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def get_exact(
        self,
        *,
        approval_ref: R6ActivationApprovalRef,
        as_of: datetime,
    ) -> R6ActivationApproval | None:
        """Return one exact approval at the PIT cutoff."""


class R6ActivationQualificationProvider(Protocol):
    """Canonical active qualification owner boundary."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def get_exact_active(
        self,
        *,
        qualification_ref: R6QualificationRef,
        as_of: datetime,
    ) -> ActiveR6QualificationEvidence | None:
        """Return one exact active qualification projection."""


class R6ActivationMonitoringProvider(Protocol):
    """Canonical Research owner of persisted monitoring projections."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def get_exact(
        self,
        *,
        monitoring_ref: R6MonitoringActivationRef,
        as_of: datetime,
    ) -> R6MonitoringActivationEvidence | None:
        """Return one exact monitoring assessment projection."""


class R6ActivationAuthorizationProvider(Protocol):
    """Canonical owner of manual activation-stack transition authorization."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def get_exact(
        self,
        *,
        authorization_ref: R6ActivationAuthorizationRef,
        scope_ref: R6ActivationScopeRef,
        action: R6ActivationAction,
        subject: R6ActivationApprovalRef,
        rollback_target: R6ActivationApprovalRef | None,
        as_of: datetime,
    ) -> R6ActivationAuthorization | None:
        """Return one exact manual transition authorization."""


@dataclass(frozen=True)
class R6PersistedActivationEvent:
    """One restored event plus its sealed Research ledger-known clock."""

    event: R6ActivationEvent
    ledger_recorded_at: datetime

    def __post_init__(self) -> None:
        if type(self.event) is not R6ActivationEvent:
            raise ValueError("R6 persisted activation event type is invalid")
        self.event.__post_init__()
        _require_aware(
            self.ledger_recorded_at,
            "R6 persisted activation event ledger_recorded_at",
        )
        if self.event.recorded_at > self.ledger_recorded_at:
            raise ValueError("R6 persisted activation event predates its ledger clock")


class R6ActivationRepository(Protocol):
    """Append-only stream boundary implemented by Phase B persistence."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Enter the shared transaction boundary."""

    def load_stream(
        self,
        *,
        scope_ref: R6ActivationScopeRef,
        as_of: datetime,
    ) -> tuple[R6ActivationEvent, ...]:
        """Return the complete exact PIT prefix in canonical sequence order."""

    def get_by_authorization(
        self,
        *,
        authorization_ref: R6ActivationAuthorizationRef,
    ) -> R6PersistedActivationEvent | None:
        """Return the immutable winner for one authorization identity."""

    def append_event(
        self,
        *,
        authorization: R6ActivationAuthorization,
        event: R6ActivationEvent,
    ) -> R6ActivationEvent:
        """Atomically append an exact authorization/event pair or replay its winner."""


def _provider_uow_key(provider: _UnitOfWorkProvider, label: str) -> str:
    try:
        key = provider.unit_of_work_key
    except Exception as error:
        raise ValueError(f"{label}.unit_of_work_key is required") from error
    if not isinstance(key, str) or not key.strip():
        raise ValueError(f"{label}.unit_of_work_key must be non-blank")
    return key


def _require_shared_uow(
    providers: tuple[tuple[_UnitOfWorkProvider, str], ...],
) -> str:
    keys = tuple(_provider_uow_key(provider, label) for provider, label in providers)
    if len(set(keys)) != 1:
        raise ValueError("R6 activation owners use different units of work")
    return keys[0]


def _require_expected_uow(
    providers: tuple[tuple[_UnitOfWorkProvider, str], ...],
    *,
    expected_key: str,
) -> None:
    """Recheck every dynamic provider key against the construction-time identity."""

    try:
        current_key = _require_shared_uow(providers)
    except Exception as error:
        raise R6ActivationUnavailable("R6 activation unit of work is unavailable") from error
    if current_key != expected_key:
        raise R6ActivationUnavailable("R6 activation unit of work identity changed")


def _owner_call(label: str, call: Callable[[], _T]) -> _T:
    try:
        return call()
    except R6ActivationUnavailable:
        raise
    except Exception as error:
        raise R6ActivationUnavailable(f"R6 activation {label} is unavailable") from error


def _repository_call(label: str, call: Callable[[], _T]) -> _T:
    try:
        return call()
    except (R6ActivationConflict, R6ActivationCorruption, R6ActivationUnavailable):
        raise
    except Exception as error:
        raise R6ActivationCorruption(f"R6 activation {label} failed") from error


@contextmanager
def _repository_atomic(repository: R6ActivationRepository) -> Iterator[None]:
    """Normalize repository/UoW failures after the concrete context has rolled back."""

    context = _repository_call("transaction boundary", repository.atomic)
    try:
        with context:
            yield
    except (R6ActivationConflict, R6ActivationCorruption, R6ActivationUnavailable):
        raise
    except Exception as error:
        raise R6ActivationCorruption("R6 activation transaction failed") from error


def _require_aware(value: object, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise R6ActivationUnavailable(f"{label} must be timezone-aware")
    return value


def _trusted_now(clock: R6ActivationClock) -> datetime:
    try:
        return _require_aware(
            _owner_call("server clock", clock.now),
            "R6 activation server clock",
        )
    except R6ActivationUnavailable:
        raise
    except Exception as error:
        raise R6ActivationUnavailable("R6 activation server clock is unavailable") from error


@dataclass(frozen=True)
class ApplyR6ActivationCommand:
    """Identity-only transition command with no caller evidence or clocks."""

    scope_ref: R6ActivationScopeRef
    action: R6ActivationAction
    subject: R6ActivationApprovalRef
    rollback_target: R6ActivationApprovalRef | None
    authorization_ref: R6ActivationAuthorizationRef

    def __post_init__(self) -> None:
        if not isinstance(self.action, R6ActivationAction):
            raise ValueError("R6 activation command action is invalid")
        if (self.action is R6ActivationAction.ROLLBACK) != (self.rollback_target is not None):
            raise ValueError("only an R6 rollback command has a target")


_PROJECTION_MINT_TOKEN = object()


@dataclass(frozen=True, init=False)
class R6ActiveStateModelProjection:
    """Exact active control-plane projection with all consumers disabled."""

    scope_ref: R6ActivationScopeRef
    approval: R6ActivationApproval
    qualification: ActiveR6QualificationEvidence
    monitoring: R6MonitoringActivationEvidence
    head_event_hash: str
    research_only: bool = True
    must_not_use_for_decision: bool = True
    must_not_replace_regime: bool = True
    must_not_publish_current: bool = True
    must_not_execute: bool = True
    content_hash: str = field(init=False)

    def __init__(
        self,
        *,
        scope_ref: R6ActivationScopeRef,
        approval: R6ActivationApproval,
        qualification: ActiveR6QualificationEvidence,
        monitoring: R6MonitoringActivationEvidence,
        head_event_hash: str,
        _mint_token: object,
    ) -> None:
        if _mint_token is not _PROJECTION_MINT_TOKEN:
            raise ValueError("R6 active projection requires exact replay minting")
        for name, value in (
            ("scope_ref", scope_ref),
            ("approval", approval),
            ("qualification", qualification),
            ("monitoring", monitoring),
            ("head_event_hash", head_event_hash),
            ("research_only", True),
            ("must_not_use_for_decision", True),
            ("must_not_replace_regime", True),
            ("must_not_publish_current", True),
            ("must_not_execute", True),
        ):
            object.__setattr__(self, name, value)
        object.__setattr__(
            self,
            "content_hash",
            _canonical_hash(self, excluded_fields=frozenset({"content_hash"})),
        )
        self.__post_init__()

    def __post_init__(self) -> None:
        if type(self.scope_ref) is not R6ActivationScopeRef:
            raise ValueError("R6 active projection scope type is invalid")
        self.scope_ref.__post_init__()
        if type(self.approval) is not R6ActivationApproval:
            raise ValueError("R6 active projection approval type is invalid")
        validate_r6_activation_approval(self.approval)
        if type(self.qualification) is not ActiveR6QualificationEvidence:
            raise ValueError("R6 active projection qualification type is invalid")
        expected_qualification = ActiveR6QualificationEvidence(
            qualification_ref=self.qualification.qualification_ref,
            candidate_id=self.qualification.candidate_id,
            candidate_version=self.qualification.candidate_version,
            assessed_at=self.qualification.assessed_at,
            known_at=self.qualification.known_at,
            research_only=self.qualification.research_only,
            must_not_use_for_decision=self.qualification.must_not_use_for_decision,
            must_not_replace_regime=self.qualification.must_not_replace_regime,
        )
        if type(self.monitoring) is not R6MonitoringActivationEvidence:
            raise ValueError("R6 active projection monitoring type is invalid")
        validate_r6_monitoring_activation_evidence(self.monitoring)
        if (
            self.approval.scope_ref != self.scope_ref
            or self.qualification.content_hash != expected_qualification.content_hash
            or self.qualification.qualification_ref != self.approval.qualification_ref
            or self.qualification.content_hash != self.approval.active_qualification_hash
            or self.monitoring.ref != self.approval.monitoring_ref
            or self.monitoring.content_hash != self.approval.monitoring_evidence_hash
        ):
            raise ValueError("R6 active projection owner graph differs")
        if not (
            self.research_only is True
            and self.must_not_use_for_decision is True
            and self.must_not_replace_regime is True
            and self.must_not_publish_current is True
            and self.must_not_execute is True
        ):
            raise ValueError("R6 active projection cannot authorize a consumer")
        if (
            not isinstance(self.head_event_hash, str)
            or len(self.head_event_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.head_event_hash)
        ):
            raise ValueError("R6 active projection head hash is invalid")
        if (
            not isinstance(self.content_hash, str)
            or len(self.content_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.content_hash)
            or self.content_hash
            != _canonical_hash(self, excluded_fields=frozenset({"content_hash"}))
        ):
            raise ValueError("R6 active projection content seal is invalid")


def _validate_active_qualification(
    evidence: object,
    *,
    approval: R6ActivationApproval,
    as_of: datetime,
) -> ActiveR6QualificationEvidence:
    try:
        if type(evidence) is not ActiveR6QualificationEvidence:
            raise ValueError("qualification projection type differs")
        expected = ActiveR6QualificationEvidence(
            qualification_ref=evidence.qualification_ref,
            candidate_id=evidence.candidate_id,
            candidate_version=evidence.candidate_version,
            assessed_at=evidence.assessed_at,
            known_at=evidence.known_at,
            research_only=evidence.research_only,
            must_not_use_for_decision=evidence.must_not_use_for_decision,
            must_not_replace_regime=evidence.must_not_replace_regime,
        )
        if (
            not isinstance(evidence.content_hash, str)
            or evidence.content_hash != expected.content_hash
            or evidence.qualification_ref != approval.qualification_ref
            or evidence.content_hash != approval.active_qualification_hash
            or evidence.candidate_id != approval.candidate_id
            or evidence.candidate_version != approval.candidate_version
            or evidence.known_at > as_of
        ):
            raise ValueError("qualification projection was substituted")
    except Exception as error:
        raise R6ActivationUnavailable("R6 activation qualification is unavailable") from error
    return evidence


def _validate_monitoring(
    evidence: object,
    *,
    approval: R6ActivationApproval,
    as_of: datetime,
) -> R6MonitoringActivationEvidence:
    try:
        if type(evidence) is not R6MonitoringActivationEvidence:
            raise ValueError("monitoring projection type differs")
        validate_r6_monitoring_activation_evidence(evidence)
        if (
            evidence.ref != approval.monitoring_ref
            or evidence.content_hash != approval.monitoring_evidence_hash
            or evidence.qualification_ref != approval.qualification_ref
            or (evidence.policy_id, evidence.policy_version, evidence.policy_hash)
            != (
                approval.required_monitoring_policy_id,
                approval.required_monitoring_policy_version,
                approval.required_monitoring_policy_hash,
            )
            or (evidence.label_protocol_version, evidence.label_set_hash)
            != (
                approval.required_label_protocol_version,
                approval.required_label_set_hash,
            )
            or evidence.status is not R6MonitoringActivationStatus.HEALTHY
            or evidence.retirement_review_required
            or not evidence.is_active_at(as_of)
            or evidence.evaluated_at > as_of
            or as_of
            > evidence.evaluated_at + timedelta(seconds=approval.maximum_monitoring_age_seconds)
        ):
            raise ValueError("monitoring projection is unhealthy or stale")
    except Exception as error:
        raise R6ActivationUnavailable("R6 activation monitoring is unavailable") from error
    return evidence


def _load_current_owner_graph(
    *,
    approval_ref: R6ActivationApprovalRef,
    expected_scope_ref: R6ActivationScopeRef,
    as_of: datetime,
    approval_provider: R6ActivationApprovalProvider,
    qualification_provider: R6ActivationQualificationProvider,
    monitoring_provider: R6ActivationMonitoringProvider,
) -> tuple[
    R6ActivationApproval,
    ActiveR6QualificationEvidence,
    R6MonitoringActivationEvidence,
]:
    approval = _owner_call(
        "approval",
        lambda: approval_provider.get_exact(approval_ref=approval_ref, as_of=as_of),
    )
    try:
        if type(approval) is not R6ActivationApproval:
            raise ValueError("approval type differs")
        validate_r6_activation_approval(approval)
        exact_approval = approval.ref == approval_ref
        exact_scope = approval.scope_ref == expected_scope_ref
        active = approval.is_active_at(as_of)
    except Exception as error:
        raise R6ActivationUnavailable("R6 activation approval is unavailable") from error
    if (
        not exact_approval
        or not exact_scope
        or not active
        or approval.outcome is not R6ActivationApprovalOutcome.APPROVED
    ):
        raise R6ActivationUnavailable("R6 activation approval was substituted or rejected")
    qualification = _validate_active_qualification(
        _owner_call(
            "qualification",
            lambda: qualification_provider.get_exact_active(
                qualification_ref=approval.qualification_ref,
                as_of=as_of,
            ),
        ),
        approval=approval,
        as_of=as_of,
    )
    monitoring = _validate_monitoring(
        _owner_call(
            "monitoring",
            lambda: monitoring_provider.get_exact(
                monitoring_ref=approval.monitoring_ref,
                as_of=as_of,
            ),
        ),
        approval=approval,
        as_of=as_of,
    )
    try:
        if approval.decided_at < max(qualification.known_at, monitoring.recorded_at):
            raise ValueError("approval predates owner evidence")
    except Exception as error:
        raise R6ActivationUnavailable("R6 activation approval is unavailable") from error
    return approval, qualification, monitoring


def _mint_active_projection(
    *,
    state: R6ActivationState,
    scope_ref: R6ActivationScopeRef,
    approval: R6ActivationApproval,
    qualification: ActiveR6QualificationEvidence,
    monitoring: R6MonitoringActivationEvidence,
) -> R6ActiveStateModelProjection:
    """Mint a projection only from the exact replayed head and owner graph."""

    try:
        if (
            state.scope_ref != scope_ref
            or state.active_approval is None
            or state.active_approval != approval.ref
        ):
            raise ValueError("replayed state and active approval differ")
        return R6ActiveStateModelProjection(
            scope_ref=scope_ref,
            approval=approval,
            qualification=qualification,
            monitoring=monitoring,
            head_event_hash=state.head_event_hash,
            _mint_token=_PROJECTION_MINT_TOKEN,
        )
    except Exception as error:
        raise R6ActivationUnavailable("R6 active projection cannot be minted") from error


def _derive_state(
    events: tuple[R6ActivationEvent, ...],
    *,
    as_of: datetime,
) -> R6ActivationState | None:
    if not events:
        return None
    try:
        return derive_r6_activation_state(events, evaluated_at=as_of)
    except Exception as error:
        raise R6ActivationCorruption("R6 activation stream failed exact replay") from error


def _load_stream(
    repository: R6ActivationRepository,
    *,
    scope_ref: R6ActivationScopeRef,
    as_of: datetime,
) -> tuple[R6ActivationEvent, ...]:
    events = _repository_call(
        "stream read",
        lambda: repository.load_stream(scope_ref=scope_ref, as_of=as_of),
    )
    if not isinstance(events, tuple):
        raise R6ActivationCorruption("R6 activation stream is not a canonical tuple")
    return events


def _authorization_matches_command(
    authorization: R6ActivationAuthorization,
    command: ApplyR6ActivationCommand,
) -> bool:
    return (
        authorization.ref == command.authorization_ref
        and authorization.scope_ref == command.scope_ref
        and authorization.action is command.action
        and authorization.subject == command.subject
        and authorization.rollback_target == command.rollback_target
    )


def _event_matches_authorization(
    event: R6ActivationEvent,
    authorization: R6ActivationAuthorization,
) -> bool:
    try:
        if type(event) is not R6ActivationEvent:
            raise ValueError("winner type differs")
        event.__post_init__()
    except Exception as error:
        raise R6ActivationCorruption("R6 activation winner seal is invalid") from error
    return (
        event.event_id == authorization.event_id
        and event.event_version == authorization.event_version
        and event.scope_ref == authorization.scope_ref
        and event.action is authorization.action
        and event.subject == authorization.subject
        and event.rollback_target == authorization.rollback_target
        and event.authorization_id == authorization.authorization_id
        and event.authorization_version == authorization.authorization_version
        and event.authorization_hash == authorization.content_hash
        and event.sequence == authorization.expected_sequence
        and event.previous_event_hash == authorization.expected_previous_event_hash
        and event.reason_codes == authorization.reason_codes
    )


def _replay_existing_winner(
    *,
    repository: R6ActivationRepository,
    existing: R6ActivationEvent,
    authorization: R6ActivationAuthorization,
    ledger_recorded_at: datetime,
) -> R6ActivationEvent:
    """Require an idempotency winner to be the exact canonical prefix head."""

    history = _load_stream(
        repository,
        scope_ref=authorization.scope_ref,
        as_of=ledger_recorded_at,
    )
    state = _derive_state(history, as_of=ledger_recorded_at)
    if (
        state is None
        or not history
        or history[-1] != existing
        or state.sequence != existing.sequence
        or state.head_event_hash != existing.content_hash
    ):
        raise R6ActivationCorruption("R6 activation winner is not the canonical stream head")
    try:
        replayed = create_r6_activation_event(
            authorization=authorization,
            previous_events=history[:-1],
            applied_at=existing.occurred_at,
        )
    except Exception as error:
        raise R6ActivationCorruption(
            "R6 activation winner transition cannot be replayed"
        ) from error
    if replayed != existing:
        raise R6ActivationCorruption("R6 activation winner differs from exact replay")
    return existing


class ApplyR6Activation:
    """Apply one exact manual ACTIVATE/RETIRE/ROLLBACK transition."""

    def __init__(
        self,
        *,
        approval_provider: R6ActivationApprovalProvider,
        qualification_provider: R6ActivationQualificationProvider,
        monitoring_provider: R6ActivationMonitoringProvider,
        authorization_provider: R6ActivationAuthorizationProvider,
        repository: R6ActivationRepository,
        clock: R6ActivationClock,
    ) -> None:
        providers: tuple[tuple[_UnitOfWorkProvider, str], ...] = (
            (approval_provider, "approval_provider"),
            (qualification_provider, "qualification_provider"),
            (monitoring_provider, "monitoring_provider"),
            (authorization_provider, "authorization_provider"),
            (repository, "repository"),
        )
        self._expected_uow_key = _require_shared_uow(providers)
        self._uow_providers = providers
        self._approval_provider = approval_provider
        self._qualification_provider = qualification_provider
        self._monitoring_provider = monitoring_provider
        self._authorization_provider = authorization_provider
        self._repository = repository
        self._clock = clock

    def execute(self, command: ApplyR6ActivationCommand) -> R6ActivationEvent:
        """Resolve exact owner evidence, replay the stack, and append one event."""

        try:
            command.__post_init__()
        except Exception as error:
            raise R6ActivationUnavailable("R6 activation command is malformed") from error
        now = _trusted_now(self._clock)
        _require_expected_uow(
            self._uow_providers,
            expected_key=self._expected_uow_key,
        )
        with _repository_atomic(self._repository):
            _require_expected_uow(
                self._uow_providers,
                expected_key=self._expected_uow_key,
            )
            existing_record = _repository_call(
                "authorization winner read",
                lambda: self._repository.get_by_authorization(
                    authorization_ref=command.authorization_ref,
                ),
            )
            if existing_record is None:
                existing = None
                owner_as_of = now
            else:
                try:
                    if type(existing_record) is not R6PersistedActivationEvent:
                        raise ValueError("winner record type differs")
                    existing_record.__post_init__()
                    existing = existing_record.event
                    owner_as_of = existing.recorded_at
                except Exception as error:
                    raise R6ActivationCorruption("R6 activation winner is malformed") from error
                if existing_record.ledger_recorded_at > now:
                    raise R6ActivationCorruption("R6 activation winner contains future evidence")
            authorization = _owner_call(
                "authorization",
                lambda: self._authorization_provider.get_exact(
                    authorization_ref=command.authorization_ref,
                    scope_ref=command.scope_ref,
                    action=command.action,
                    subject=command.subject,
                    rollback_target=command.rollback_target,
                    as_of=owner_as_of,
                ),
            )
            try:
                if type(authorization) is not R6ActivationAuthorization:
                    raise ValueError("authorization type differs")
                validate_r6_activation_authorization(authorization)
            except Exception as error:
                raise R6ActivationUnavailable(
                    "R6 activation authorization is unavailable"
                ) from error
            if not _authorization_matches_command(
                authorization, command
            ) or not authorization.is_active_at(owner_as_of):
                raise R6ActivationUnavailable(
                    "R6 activation authorization was substituted or is inactive"
                )
            if existing_record is not None:
                existing = existing_record.event
                if not _event_matches_authorization(existing, authorization):
                    raise R6ActivationConflict("R6 activation authorization winner differs")
                _require_expected_uow(
                    self._uow_providers,
                    expected_key=self._expected_uow_key,
                )
                return _replay_existing_winner(
                    repository=self._repository,
                    existing=existing,
                    authorization=authorization,
                    ledger_recorded_at=existing_record.ledger_recorded_at,
                )
            history = _load_stream(
                self._repository,
                scope_ref=command.scope_ref,
                as_of=now,
            )
            state = _derive_state(history, as_of=now)
            current_graph: (
                tuple[
                    R6ActivationApproval,
                    ActiveR6QualificationEvidence,
                    R6MonitoringActivationEvidence,
                ]
                | None
            ) = None
            if command.action is R6ActivationAction.ACTIVATE:
                current_graph = _load_current_owner_graph(
                    approval_ref=command.subject,
                    expected_scope_ref=command.scope_ref,
                    as_of=now,
                    approval_provider=self._approval_provider,
                    qualification_provider=self._qualification_provider,
                    monitoring_provider=self._monitoring_provider,
                )
            elif command.action is R6ActivationAction.ROLLBACK:
                if (
                    state is None
                    or len(state.activation_stack) < 2
                    or state.active_approval != command.subject
                    or state.activation_stack[-2] != command.rollback_target
                ):
                    raise R6ActivationUnavailable(
                        "R6 activation rollback target is not exact stack[-2]"
                    )
                if command.rollback_target is None:  # pragma: no cover - command guard
                    raise R6ActivationUnavailable("R6 activation rollback target is absent")
                current_graph = _load_current_owner_graph(
                    approval_ref=command.rollback_target,
                    expected_scope_ref=command.scope_ref,
                    as_of=now,
                    approval_provider=self._approval_provider,
                    qualification_provider=self._qualification_provider,
                    monitoring_provider=self._monitoring_provider,
                )
            elif state is None or state.active_approval != command.subject:
                raise R6ActivationUnavailable(
                    "R6 activation retirement does not target the active approval"
                )
            if current_graph is not None:
                owner_recorded_at = max(
                    current_graph[0].recorded_at,
                    current_graph[2].recorded_at,
                )
                if (
                    authorization.issued_at < owner_recorded_at
                    or authorization.recorded_at < owner_recorded_at
                ):
                    raise R6ActivationUnavailable(
                        "R6 activation authorization predates exact owner evidence"
                    )
            try:
                event = create_r6_activation_event(
                    authorization=authorization,
                    previous_events=history,
                    applied_at=now,
                )
            except Exception as error:
                raise R6ActivationUnavailable("R6 activation transition is invalid") from error
            _require_expected_uow(
                self._uow_providers,
                expected_key=self._expected_uow_key,
            )
            winner = _repository_call(
                "event append",
                lambda: self._repository.append_event(
                    authorization=authorization,
                    event=event,
                ),
            )
            try:
                if type(winner) is not R6ActivationEvent:
                    raise ValueError("winner type differs")
                winner.__post_init__()
            except Exception as error:
                raise R6ActivationCorruption("R6 activation append winner is malformed") from error
            if winner != event:
                if winner.recorded_at > now:
                    raise R6ActivationCorruption(
                        "R6 activation append winner contains future evidence"
                    )
                if not _event_matches_authorization(winner, authorization):
                    raise R6ActivationConflict("R6 activation append winner differs")
                return _replay_existing_winner(
                    repository=self._repository,
                    existing=winner,
                    authorization=authorization,
                    ledger_recorded_at=now,
                )
            return winner


class GetActiveR6StateModel:
    """Resolve a PIT active approval only after full current owner revalidation."""

    def __init__(
        self,
        *,
        approval_provider: R6ActivationApprovalProvider,
        qualification_provider: R6ActivationQualificationProvider,
        monitoring_provider: R6ActivationMonitoringProvider,
        repository: R6ActivationRepository,
        clock: R6ActivationClock,
    ) -> None:
        providers: tuple[tuple[_UnitOfWorkProvider, str], ...] = (
            (approval_provider, "approval_provider"),
            (qualification_provider, "qualification_provider"),
            (monitoring_provider, "monitoring_provider"),
            (repository, "repository"),
        )
        self._expected_uow_key = _require_shared_uow(providers)
        self._uow_providers = providers
        self._approval_provider = approval_provider
        self._qualification_provider = qualification_provider
        self._monitoring_provider = monitoring_provider
        self._repository = repository
        self._clock = clock

    def get_active(
        self,
        *,
        scope_ref: R6ActivationScopeRef,
        as_of: datetime,
    ) -> R6ActiveStateModelProjection | None:
        """Return exact active control-plane evidence or fail-closed absence."""

        try:
            scope_ref.__post_init__()
        except Exception:
            return None
        try:
            cutoff = _require_aware(as_of, "R6 activation active as_of")
            now = _trusted_now(self._clock)
        except R6ActivationUnavailable:
            return None
        if cutoff > now:
            return None
        try:
            _require_expected_uow(
                self._uow_providers,
                expected_key=self._expected_uow_key,
            )
            with _repository_atomic(self._repository):
                _require_expected_uow(
                    self._uow_providers,
                    expected_key=self._expected_uow_key,
                )
                history = _load_stream(
                    self._repository,
                    scope_ref=scope_ref,
                    as_of=cutoff,
                )
                state = _derive_state(history, as_of=cutoff)
                if state is None or state.active_approval is None or state.scope_ref != scope_ref:
                    return None
                approval, qualification, monitoring = _load_current_owner_graph(
                    approval_ref=state.active_approval,
                    expected_scope_ref=scope_ref,
                    as_of=cutoff,
                    approval_provider=self._approval_provider,
                    qualification_provider=self._qualification_provider,
                    monitoring_provider=self._monitoring_provider,
                )
                _require_expected_uow(
                    self._uow_providers,
                    expected_key=self._expected_uow_key,
                )
                return _mint_active_projection(
                    state=state,
                    scope_ref=scope_ref,
                    approval=approval,
                    qualification=qualification,
                    monitoring=monitoring,
                )
        except (R6ActivationConflict, R6ActivationCorruption, R6ActivationUnavailable):
            return None
        except Exception:
            return None


__all__ = [
    "ApplyR6Activation",
    "ApplyR6ActivationCommand",
    "GetActiveR6StateModel",
    "R6ActivationApprovalProvider",
    "R6ActivationAuthorizationProvider",
    "R6ActivationClock",
    "R6ActivationConflict",
    "R6ActivationCorruption",
    "R6ActivationMonitoringProvider",
    "R6ActivationQualificationProvider",
    "R6ActivationRepository",
    "R6ActivationUnavailable",
    "R6ActiveStateModelProjection",
    "R6PersistedActivationEvent",
]
