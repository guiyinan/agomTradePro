"""ID/as-of-only orchestration for the research-only R7 family lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeVar

from apps.research.domain.r7_research_result_lifecycle import (
    R7ResultLifecycleEvent,
)
from apps.research.domain.r7_research_result_persistence import (
    PersistedR7ResearchResult,
)
from apps.research.domain.r7_result_family_lifecycle import (
    R7FamilyLifecycleAction,
    R7FamilyLifecycleAuthorization,
    R7FamilyLifecycleEvent,
    R7FamilyResultOwnerEvidence,
    R7LocalLifecycleStreamAttestation,
    R7ResultFamilyIdentity,
    create_r7_family_lifecycle_event,
    derive_r7_family_lifecycle_state,
)
from apps.research.domain.scenario_research_hashing import require_token

_T = TypeVar("_T")


class R7FamilyLifecycleUnavailable(RuntimeError):
    """An exact owner fact, clock, or shared transaction is unavailable."""


class R7FamilyLifecycleConflict(RuntimeError):
    """An owner instruction cannot follow the canonical family head."""


class R7FamilyLifecycleCorruption(RuntimeError):
    """A returned or persisted family object failed exact live replay."""


@dataclass(frozen=True)
class R7ResultFamilyRef:
    """Identifier-only reference to one result family."""

    family_id: str
    family_version: str

    def __post_init__(self) -> None:
        require_token(self.family_id, "R7 family ref family_id", maximum=192)
        require_token(self.family_version, "R7 family ref family_version", maximum=192)


@dataclass(frozen=True)
class R7FamilyResultIdRef:
    """Identifier-only reference to one persisted R7 result."""

    result_id: str
    result_version: str

    def __post_init__(self) -> None:
        require_token(self.result_id, "R7 family result ref result_id", maximum=192)
        require_token(self.result_version, "R7 family result ref result_version", maximum=192)


@dataclass(frozen=True)
class R7FamilyAuthorizationRef:
    """Identifier-only reference to one Research-owned family authorization."""

    authorization_id: str
    authorization_version: str

    def __post_init__(self) -> None:
        require_token(
            self.authorization_id,
            "R7 family authorization ref authorization_id",
            maximum=192,
        )
        require_token(
            self.authorization_version,
            "R7 family authorization ref authorization_version",
            maximum=192,
        )


@dataclass(frozen=True)
class ApplyR7FamilyLifecycleCommand:
    """Caller-supplied identities and cutoff, never owner evidence or hashes."""

    family_ref: R7ResultFamilyRef
    action: R7FamilyLifecycleAction
    subject_ref: R7FamilyResultIdRef
    rollback_target_ref: R7FamilyResultIdRef | None
    authorization_ref: R7FamilyAuthorizationRef
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.family_ref) is not R7ResultFamilyRef:
            raise ValueError("R7 family command family ref is invalid")
        self.family_ref.__post_init__()
        if type(self.action) is not R7FamilyLifecycleAction:
            raise ValueError("R7 family command action is invalid")
        if type(self.subject_ref) is not R7FamilyResultIdRef:
            raise ValueError("R7 family command subject ref is invalid")
        self.subject_ref.__post_init__()
        if self.rollback_target_ref is not None:
            if type(self.rollback_target_ref) is not R7FamilyResultIdRef:
                raise ValueError("R7 family command rollback target is invalid")
            self.rollback_target_ref.__post_init__()
        if (self.action is R7FamilyLifecycleAction.ROLLBACK) != (
            self.rollback_target_ref is not None
        ):
            raise ValueError("only an R7 family rollback command has a target")
        if type(self.authorization_ref) is not R7FamilyAuthorizationRef:
            raise ValueError("R7 family command authorization ref is invalid")
        self.authorization_ref.__post_init__()
        _require_aware(self.as_of, "R7 family command as_of")


@dataclass(frozen=True)
class R7FamilyOwnerSourceGraph:
    """Complete authoritative sources used to derive one owner projection."""

    result: PersistedR7ResearchResult
    local_lifecycle_stream: tuple[R7ResultLifecycleEvent, ...]
    local_lifecycle_attestation: R7LocalLifecycleStreamAttestation
    evaluated_at: datetime
    evidence: R7FamilyResultOwnerEvidence

    @classmethod
    def from_owner_graph(
        cls,
        *,
        result: PersistedR7ResearchResult,
        local_lifecycle_stream: tuple[R7ResultLifecycleEvent, ...],
        local_lifecycle_attestation: R7LocalLifecycleStreamAttestation,
        evaluated_at: datetime,
    ) -> R7FamilyOwnerSourceGraph:
        """Rebuild, validate, and retain the source graph for persistence."""

        evidence = R7FamilyResultOwnerEvidence.from_owner_graph(
            result=result,
            complete_local_lifecycle_stream=local_lifecycle_stream,
            local_lifecycle_attestation=local_lifecycle_attestation,
            evaluated_at=evaluated_at,
        )
        return cls(
            result=result,
            local_lifecycle_stream=local_lifecycle_stream,
            local_lifecycle_attestation=local_lifecycle_attestation,
            evaluated_at=evaluated_at,
            evidence=evidence,
        )

    def __post_init__(self) -> None:
        rebuilt = R7FamilyResultOwnerEvidence.from_owner_graph(
            result=self.result,
            complete_local_lifecycle_stream=self.local_lifecycle_stream,
            local_lifecycle_attestation=self.local_lifecycle_attestation,
            evaluated_at=self.evaluated_at,
        )
        if rebuilt != self.evidence:
            raise ValueError("R7 family owner source graph differs from its evidence")


class _UnitOfWorkProvider(Protocol):
    @property
    def unit_of_work_key(self) -> str:
        """Return one explicit transaction identity."""


class ExactR7FamilyResultProvider(Protocol):
    """Canonical owner port for immutable R7 research results."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def get_exact(
        self,
        *,
        result_ref: R7FamilyResultIdRef,
        as_of: datetime,
    ) -> PersistedR7ResearchResult | None:
        """Return one exact result known at the historical cutoff."""


class ExactR7LocalLifecycleProvider(Protocol):
    """Canonical owner port for complete result-local lifecycle streams."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def load_complete(
        self,
        *,
        result_ref: R7FamilyResultIdRef,
        as_of: datetime,
    ) -> tuple[R7ResultLifecycleEvent, ...]:
        """Return the complete exact result-local prefix at the cutoff."""

    def get_attestation(
        self,
        *,
        result_ref: R7FamilyResultIdRef,
        as_of: datetime,
    ) -> R7LocalLifecycleStreamAttestation | None:
        """Return the authoritative head/count/stream seal for that prefix."""


class ExactR7FamilyAuthorizationProvider(Protocol):
    """Canonical Research owner port for family transition authorizations."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def get_exact(
        self,
        *,
        authorization_ref: R7FamilyAuthorizationRef,
        family_ref: R7ResultFamilyRef,
        action: R7FamilyLifecycleAction,
        subject_ref: R7FamilyResultIdRef,
        rollback_target_ref: R7FamilyResultIdRef | None,
        as_of: datetime,
    ) -> R7FamilyLifecycleAuthorization | None:
        """Return one exact owner instruction without latest fallback."""


class R7FamilyLifecycleRepository(Protocol):
    """Append-only family stream boundary; no active/current consumer surface."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared transaction identity."""

    def atomic(self) -> AbstractContextManager[None]:
        """Enter the shared owner/read/write transaction."""

    def server_now(self) -> datetime:
        """Return one authoritative server clock."""

    def load_complete(
        self,
        *,
        family_ref: R7ResultFamilyRef,
        as_of: datetime,
    ) -> tuple[R7FamilyLifecycleEvent, ...]:
        """Return the complete exact family prefix at the cutoff."""

    def get_by_authorization(
        self,
        *,
        authorization_ref: R7FamilyAuthorizationRef,
    ) -> R7FamilyLifecycleEvent | None:
        """Return the immutable event winner for an authorization identity."""

    def append(
        self,
        *,
        authorization: R7FamilyLifecycleAuthorization,
        event: R7FamilyLifecycleEvent,
        subject_source: R7FamilyOwnerSourceGraph,
        rollback_target_source: R7FamilyOwnerSourceGraph | None,
    ) -> R7FamilyLifecycleEvent:
        """Append one exact pair or return its exact first winner."""


def _require_aware(value: object, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def _provider_key(provider: _UnitOfWorkProvider, label: str) -> str:
    try:
        key = provider.unit_of_work_key
    except Exception as error:
        raise R7FamilyLifecycleUnavailable(f"{label} unit of work is unavailable") from error
    if type(key) is not str or not key.strip():
        raise R7FamilyLifecycleUnavailable(f"{label} unit of work is invalid")
    return key


def _shared_uow(providers: tuple[tuple[_UnitOfWorkProvider, str], ...]) -> str:
    keys = tuple(_provider_key(provider, label) for provider, label in providers)
    if len(set(keys)) != 1:
        raise R7FamilyLifecycleUnavailable("R7 family owners use different units of work")
    return keys[0]


def _owner_call(label: str, call: Callable[[], _T]) -> _T:
    try:
        return call()
    except R7FamilyLifecycleUnavailable:
        raise
    except Exception as error:
        raise R7FamilyLifecycleUnavailable(f"R7 family {label} is unavailable") from error


def _repository_call(label: str, call: Callable[[], _T]) -> _T:
    try:
        return call()
    except (
        R7FamilyLifecycleUnavailable,
        R7FamilyLifecycleConflict,
        R7FamilyLifecycleCorruption,
    ):
        raise
    except Exception as error:
        raise R7FamilyLifecycleCorruption(f"R7 family {label} failed") from error


@contextmanager
def _atomic(repository: R7FamilyLifecycleRepository) -> Iterator[None]:
    context = _repository_call("transaction boundary", repository.atomic)
    try:
        with context:
            yield
    except (
        R7FamilyLifecycleUnavailable,
        R7FamilyLifecycleConflict,
        R7FamilyLifecycleCorruption,
    ):
        raise
    except Exception as error:
        raise R7FamilyLifecycleCorruption("R7 family transaction failed") from error


class ApplyR7FamilyLifecycle:
    """Apply one exact manual transition without publishing an active consumer."""

    def __init__(
        self,
        *,
        result_provider: ExactR7FamilyResultProvider,
        local_lifecycle_provider: ExactR7LocalLifecycleProvider,
        authorization_provider: ExactR7FamilyAuthorizationProvider,
        repository: R7FamilyLifecycleRepository,
    ) -> None:
        self._result_provider = result_provider
        self._local_lifecycle_provider = local_lifecycle_provider
        self._authorization_provider = authorization_provider
        self._repository = repository
        self._providers: tuple[tuple[_UnitOfWorkProvider, str], ...] = (
            (result_provider, "R7 result owner"),
            (local_lifecycle_provider, "R7 local lifecycle owner"),
            (authorization_provider, "R7 family authorization owner"),
            (repository, "R7 family repository"),
        )
        self._expected_uow_key = _shared_uow(self._providers)

    def execute(
        self,
        command: ApplyR7FamilyLifecycleCommand,
    ) -> R7FamilyLifecycleEvent:
        """Reread all owner facts in one UoW and append a server-clocked event."""

        self._validate_command(command)
        self._require_expected_uow()
        with _atomic(self._repository):
            self._require_expected_uow()
            authorization = self._load_authorization(command, as_of=command.as_of)
            existing = _repository_call(
                "idempotent lookup",
                lambda: self._repository.get_by_authorization(
                    authorization_ref=command.authorization_ref
                ),
            )
            if existing is not None:
                self._validate_existing(existing, authorization, command)
                self._require_expected_uow()
                return existing
            now = self._server_now()
            if command.as_of > now:
                raise R7FamilyLifecycleUnavailable("future R7 family cutoff is unavailable")
            stream = self._load_family_stream(command.family_ref, now)
            if not authorization.is_active_at(now):
                raise R7FamilyLifecycleUnavailable("R7 family authorization is inactive")
            subject_source = self._load_owner_evidence(
                command.subject_ref,
                as_of=authorization.issued_at,
            )
            target_source = (
                None
                if command.rollback_target_ref is None
                else self._load_owner_evidence(
                    command.rollback_target_ref,
                    as_of=authorization.issued_at,
                )
            )
            subject = subject_source.evidence
            target = None if target_source is None else target_source.evidence
            self._validate_owner_graph(command, authorization, subject, target)
            self._require_expected_uow()
            event_now = self._server_now()
            if event_now < now:
                raise R7FamilyLifecycleUnavailable("R7 family server clock moved backwards")
            current_subject_source = self._load_owner_evidence(
                command.subject_ref,
                as_of=event_now,
            )
            current_target_source = (
                None
                if command.rollback_target_ref is None
                else self._load_owner_evidence(
                    command.rollback_target_ref,
                    as_of=event_now,
                )
            )
            current_subject = current_subject_source.evidence
            current_target = (
                None if current_target_source is None else current_target_source.evidence
            )
            self._validate_current_owner_state(
                command,
                current_subject,
                current_target,
                at=event_now,
            )
            self._validate_owner_graph(
                command,
                authorization,
                current_subject,
                current_target,
            )
            self._require_same_owner_graph(subject, current_subject)
            if target is not None and current_target is not None:
                self._require_same_owner_graph(target, current_target)
            elif target != current_target:
                raise R7FamilyLifecycleUnavailable(
                    "R7 family rollback target changed after authorization"
                )
            self._require_expected_uow()
            stream = self._load_family_stream(command.family_ref, event_now)
            final_authorization = self._load_authorization(command, as_of=event_now)
            if final_authorization != authorization:
                raise R7FamilyLifecycleUnavailable("R7 family authorization changed before append")
            final_subject_source = self._load_owner_evidence(
                command.subject_ref,
                as_of=event_now,
            )
            final_target_source = (
                None
                if command.rollback_target_ref is None
                else self._load_owner_evidence(
                    command.rollback_target_ref,
                    as_of=event_now,
                )
            )
            final_subject = final_subject_source.evidence
            final_target = None if final_target_source is None else final_target_source.evidence
            self._validate_owner_graph(
                command,
                final_authorization,
                final_subject,
                final_target,
            )
            self._require_same_owner_graph(current_subject, final_subject)
            if current_target is not None and final_target is not None:
                self._require_same_owner_graph(current_target, final_target)
            elif current_target != final_target:
                raise R7FamilyLifecycleUnavailable(
                    "R7 family rollback target changed before append"
                )
            self._require_expected_uow()
            try:
                event = create_r7_family_lifecycle_event(
                    previous_events=stream,
                    authorization=authorization,
                    subject_evidence=subject,
                    rollback_target_evidence=target,
                    occurred_at=event_now,
                    recorded_at=event_now,
                )
            except Exception as error:
                raise R7FamilyLifecycleConflict(
                    "R7 family transition conflicts with the canonical head"
                ) from error
            self._require_expected_uow()
            winner = _repository_call(
                "append",
                lambda: self._repository.append(
                    authorization=authorization,
                    event=event,
                    subject_source=subject_source,
                    rollback_target_source=target_source,
                ),
            )
            self._validate_winner(winner, event)
            self._require_expected_uow()
            return winner

    @staticmethod
    def _validate_command(command: ApplyR7FamilyLifecycleCommand) -> None:
        try:
            if type(command) is not ApplyR7FamilyLifecycleCommand:
                raise TypeError("command type differs")
            command.__post_init__()
        except Exception as error:
            raise R7FamilyLifecycleUnavailable("R7 family command is invalid") from error

    def _require_expected_uow(self) -> None:
        if _shared_uow(self._providers) != self._expected_uow_key:
            raise R7FamilyLifecycleUnavailable("R7 family unit of work identity changed")

    def _server_now(self) -> datetime:
        try:
            return _require_aware(
                _repository_call("server clock", self._repository.server_now),
                "R7 family server clock",
            )
        except R7FamilyLifecycleCorruption as error:
            raise R7FamilyLifecycleUnavailable("R7 family server clock is unavailable") from error
        except Exception as error:
            raise R7FamilyLifecycleUnavailable("R7 family server clock is unavailable") from error

    def _load_authorization(
        self,
        command: ApplyR7FamilyLifecycleCommand,
        *,
        as_of: datetime,
    ) -> R7FamilyLifecycleAuthorization:
        value = _owner_call(
            "authorization",
            lambda: self._authorization_provider.get_exact(
                authorization_ref=command.authorization_ref,
                family_ref=command.family_ref,
                action=command.action,
                subject_ref=command.subject_ref,
                rollback_target_ref=command.rollback_target_ref,
                as_of=as_of,
            ),
        )
        try:
            if type(value) is not R7FamilyLifecycleAuthorization:
                raise TypeError("authorization type differs")
            value.__post_init__()
            subject = _id_ref(value.subject_ref.result_id, value.subject_ref.result_version)
            target = (
                None
                if value.rollback_target_ref is None
                else _id_ref(
                    value.rollback_target_ref.result_id,
                    value.rollback_target_ref.result_version,
                )
            )
            if (
                value.authorization_id != command.authorization_ref.authorization_id
                or value.authorization_version != command.authorization_ref.authorization_version
                or _family_ref(value.family) != command.family_ref
                or value.action is not command.action
                or subject != command.subject_ref
                or target != command.rollback_target_ref
                or value.recorded_at > as_of
            ):
                raise ValueError("authorization differs")
        except Exception as error:
            raise R7FamilyLifecycleUnavailable("R7 family authorization was substituted") from error
        return value

    def _load_owner_evidence(
        self,
        result_ref: R7FamilyResultIdRef,
        *,
        as_of: datetime,
    ) -> R7FamilyOwnerSourceGraph:
        result = _owner_call(
            "result",
            lambda: self._result_provider.get_exact(
                result_ref=result_ref,
                as_of=as_of,
            ),
        )
        local_stream = _owner_call(
            "local lifecycle",
            lambda: self._local_lifecycle_provider.load_complete(
                result_ref=result_ref,
                as_of=as_of,
            ),
        )
        attestation = _owner_call(
            "local lifecycle attestation",
            lambda: self._local_lifecycle_provider.get_attestation(
                result_ref=result_ref,
                as_of=as_of,
            ),
        )
        try:
            if type(result) is not PersistedR7ResearchResult:
                raise TypeError("result type differs")
            if (result.result_id, result.result_version) != (
                result_ref.result_id,
                result_ref.result_version,
            ):
                raise ValueError("result identity differs")
            if type(local_stream) is not tuple:
                raise TypeError("local stream type differs")
            if type(attestation) is not R7LocalLifecycleStreamAttestation:
                raise TypeError("local lifecycle attestation type differs")
            return R7FamilyOwnerSourceGraph.from_owner_graph(
                result=result,
                local_lifecycle_stream=local_stream,
                local_lifecycle_attestation=attestation,
                evaluated_at=as_of,
            )
        except Exception as error:
            raise R7FamilyLifecycleUnavailable(
                "R7 family result owner graph is unavailable"
            ) from error

    @staticmethod
    def _validate_owner_graph(
        command: ApplyR7FamilyLifecycleCommand,
        authorization: R7FamilyLifecycleAuthorization,
        subject: R7FamilyResultOwnerEvidence,
        target: R7FamilyResultOwnerEvidence | None,
    ) -> None:
        try:
            subject.validate_live()
            if target is not None:
                target.validate_live()
            if (
                _family_ref(subject.family) != command.family_ref
                or subject.family != authorization.family
                or subject.result_ref != authorization.subject_ref
                or subject.local_lifecycle_attestation.content_hash
                != authorization.subject_owner_attestation_hash
                or (None if target is None else target.result_ref)
                != authorization.rollback_target_ref
                or (None if target is None else target.local_lifecycle_attestation.content_hash)
                != authorization.rollback_target_owner_attestation_hash
                or (target is not None and target.family != authorization.family)
            ):
                raise ValueError("owner graph differs")
        except Exception as error:
            raise R7FamilyLifecycleUnavailable("R7 family owner graph was substituted") from error

    def _load_family_stream(
        self,
        family_ref: R7ResultFamilyRef,
        as_of: datetime,
    ) -> tuple[R7FamilyLifecycleEvent, ...]:
        stream = _repository_call(
            "stream load",
            lambda: self._repository.load_complete(
                family_ref=family_ref,
                as_of=as_of,
            ),
        )
        try:
            if type(stream) is not tuple:
                raise TypeError("stream type differs")
            if stream:
                state = derive_r7_family_lifecycle_state(stream, evaluated_at=as_of)
                if _family_ref(state.family) != family_ref:
                    raise ValueError("family differs")
        except Exception as error:
            raise R7FamilyLifecycleCorruption("R7 family lifecycle stream is invalid") from error
        return stream

    @staticmethod
    def _require_same_owner_graph(
        expected: R7FamilyResultOwnerEvidence,
        actual: R7FamilyResultOwnerEvidence,
    ) -> None:
        """Compare all stable result and local-lifecycle fields across rereads."""

        if _owner_graph_binding(actual) != _owner_graph_binding(expected):
            raise R7FamilyLifecycleUnavailable("R7 family owner graph changed before append")

    @staticmethod
    def _validate_current_owner_state(
        command: ApplyR7FamilyLifecycleCommand,
        subject: R7FamilyResultOwnerEvidence,
        target: R7FamilyResultOwnerEvidence | None,
        *,
        at: datetime,
    ) -> None:
        """Block activation if current owner state retired or expired meanwhile."""

        try:
            if (
                _family_ref(subject.family) != command.family_ref
                or _id_ref(
                    subject.result_ref.result_id,
                    subject.result_ref.result_version,
                )
                != command.subject_ref
                or (
                    None
                    if target is None
                    else _id_ref(
                        target.result_ref.result_id,
                        target.result_ref.result_version,
                    )
                )
                != command.rollback_target_ref
            ):
                raise ValueError("current owner identity differs")
            if command.action is R7FamilyLifecycleAction.PROMOTE and not subject.is_activatable_at(
                at
            ):
                raise ValueError("current subject cannot activate")
            if command.action is R7FamilyLifecycleAction.ROLLBACK and (
                target is None or not target.is_activatable_at(at)
            ):
                raise ValueError("current rollback target cannot activate")
        except Exception as error:
            raise R7FamilyLifecycleUnavailable(
                "R7 family current owner state cannot activate"
            ) from error

    @staticmethod
    def _validate_existing(
        existing: object,
        authorization: R7FamilyLifecycleAuthorization,
        command: ApplyR7FamilyLifecycleCommand,
    ) -> None:
        try:
            if type(existing) is not R7FamilyLifecycleEvent:
                raise TypeError("event type differs")
            existing.validate_live()
            if (
                _family_ref(existing.family) != command.family_ref
                or existing.authorization != authorization
                or command.as_of > existing.recorded_at
            ):
                raise ValueError("winner is not canonical")
        except Exception as error:
            raise R7FamilyLifecycleCorruption("R7 family idempotent winner is invalid") from error

    @staticmethod
    def _validate_winner(
        winner: object,
        expected: R7FamilyLifecycleEvent,
    ) -> None:
        try:
            if type(winner) is not R7FamilyLifecycleEvent:
                raise TypeError("winner type differs")
            winner.validate_live()
            if winner != expected:
                raise ValueError("winner differs")
        except Exception as error:
            raise R7FamilyLifecycleConflict(
                "R7 family append produced a different winner"
            ) from error


def _family_ref(value: R7ResultFamilyIdentity) -> R7ResultFamilyRef:
    value.__post_init__()
    return R7ResultFamilyRef(value.family_id, value.family_version)


def _id_ref(result_id: str, result_version: str) -> R7FamilyResultIdRef:
    return R7FamilyResultIdRef(result_id, result_version)


def _owner_graph_binding(value: R7FamilyResultOwnerEvidence) -> tuple[object, ...]:
    """Return every stable owner field; evaluated_at is a query cutoff only."""

    value.validate_live()
    return (
        value.family,
        value.result_ref,
        value.result_recorded_at,
        value.local_lifecycle_status,
        value.local_lifecycle_sequence,
        value.local_lifecycle_head_hash,
        value.local_lifecycle_event_count,
        value.local_lifecycle_stream_hash,
        value.local_lifecycle_attestation,
        value.local_promoted_at,
        value.local_retired_at,
        value.evidence_valid_until,
        value.research_only,
        value.publishes_model_probability,
        value.publishes_probability_current,
        value.produces_decision,
        value.executes_orders,
        value.must_not_use_for_decision,
        value.must_not_execute,
    )


__all__ = [
    "ApplyR7FamilyLifecycle",
    "ApplyR7FamilyLifecycleCommand",
    "ExactR7FamilyAuthorizationProvider",
    "ExactR7FamilyResultProvider",
    "ExactR7LocalLifecycleProvider",
    "R7FamilyAuthorizationRef",
    "R7FamilyLifecycleConflict",
    "R7FamilyLifecycleCorruption",
    "R7FamilyLifecycleRepository",
    "R7FamilyLifecycleUnavailable",
    "R7FamilyOwnerSourceGraph",
    "R7FamilyResultIdRef",
    "R7ResultFamilyRef",
]
