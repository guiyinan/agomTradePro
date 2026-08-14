"""Capture and read Account actor-authority source v3 evidence."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
    root_claim_hash_for_actor_authority_source_v3,
    validate_account_owner_assignment_actor_authority_source_v3_successor,
)


class AccountOwnerAssignmentActorAuthoritySourceV3Unavailable(ValueError):
    """An exact-current authority input is unavailable."""


class AccountOwnerAssignmentActorAuthoritySourceV3Conflict(ValueError):
    """A winner, input, or predecessor changed concurrently."""


class AccountOwnerAssignmentActorAuthoritySourceV3Corruption(ValueError):
    """A provider or repository substituted authority evidence."""


def _token(value: object, name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")


def _digest(value: object, name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be an exact timezone-aware datetime")
    return value


@dataclass(frozen=True, slots=True)
class ExactCurrentAuthenticationContextV3:
    """Consumer-owned secret-free authentication-context projection."""

    context_id: str
    context_version: str
    identity_hash: str
    content_hash: str
    principal_id: str
    user_id: int
    is_authenticated: bool
    authenticated_at: datetime
    recorded_at: datetime
    valid_until: datetime
    owner: str = "account"
    artifact_type: str = "account_authentication_context_v3"

    def __post_init__(self) -> None:
        _projection(self, "account_authentication_context_v3")
        _token(self.principal_id, "principal_id")
        _positive(self.user_id, "user_id")
        if type(self.is_authenticated) is not bool:
            raise TypeError("is_authenticated must be an exact boolean")
        _clock(self.authenticated_at, self.recorded_at, self.valid_until)


@dataclass(frozen=True, slots=True)
class ExactCurrentAccountUserAuthorityV3:
    """Consumer-owned exact Account user-status projection."""

    source_id: str
    source_version: str
    identity_hash: str
    content_hash: str
    user_id: int
    actor_id: str
    is_active: bool
    is_staff: bool
    is_superuser: bool
    recorded_at: datetime
    valid_until: datetime
    owner: str = "account"
    artifact_type: str = "account_user_authority_v3"

    def __post_init__(self) -> None:
        _projection(self, "account_user_authority_v3")
        _positive(self.user_id, "user_id")
        _token(self.actor_id, "actor_id")
        for name in ("is_active", "is_staff", "is_superuser"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")
        _clock(self.recorded_at, self.recorded_at, self.valid_until)


@dataclass(frozen=True, slots=True)
class ExactCurrentAccountRbacAuthorityV3:
    """Consumer-owned exact Account RBAC-role projection."""

    source_id: str
    source_version: str
    identity_hash: str
    content_hash: str
    user_id: int
    rbac_role: str
    recorded_at: datetime
    valid_until: datetime
    owner: str = "account"
    artifact_type: str = "account_rbac_authority_v3"

    def __post_init__(self) -> None:
        _projection(self, "account_rbac_authority_v3")
        _positive(self.user_id, "user_id")
        _token(self.rbac_role, "rbac_role")
        _clock(self.recorded_at, self.recorded_at, self.valid_until)


def _projection(
    value: (
        ExactCurrentAuthenticationContextV3
        | ExactCurrentAccountUserAuthorityV3
        | ExactCurrentAccountRbacAuthorityV3
    ),
    artifact_type: str,
) -> None:
    if value.owner != "account" or value.artifact_type != artifact_type:
        raise ValueError("authority projection ownership is invalid")
    for name in (
        ("source_id", "source_version")
        if hasattr(value, "source_id")
        else (
            "context_id",
            "context_version",
        )
    ):
        _token(getattr(value, name), name)
    _digest(value.identity_hash, "identity_hash")
    _digest(value.content_hash, "content_hash")


def _positive(value: object, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be an exact positive integer")


def _clock(start: datetime, recorded: datetime, end: datetime) -> None:
    if not _aware(start, "start") <= _aware(recorded, "recorded_at") < _aware(end, "valid_until"):
        raise ValueError("authority projection clock is invalid")


@dataclass(frozen=True, slots=True)
class CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command:
    """Select three exact-current authority inputs using IDs and hashes only."""

    source_id: str
    source_version: str
    principal_id: str
    user_id: int
    authentication_context_id: str
    authentication_context_version: str
    expected_authentication_context_content_hash: str
    user_source_id: str
    user_source_version: str
    expected_user_source_content_hash: str
    rbac_source_id: str
    rbac_source_version: str
    expected_rbac_source_content_hash: str

    def __post_init__(self) -> None:
        for name in (
            "source_id",
            "source_version",
            "principal_id",
            "authentication_context_id",
            "authentication_context_version",
            "user_source_id",
            "user_source_version",
            "rbac_source_id",
            "rbac_source_version",
        ):
            _token(getattr(self, name), name)
        _positive(self.user_id, "user_id")
        for name in (
            "expected_authentication_context_content_hash",
            "expected_user_source_content_hash",
            "expected_rbac_source_content_hash",
        ):
            _digest(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class GetExactAccountOwnerAssignmentActorAuthoritySourceV3Command:
    source_id: str
    source_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.source_id, "source_id")
        _token(self.source_version, "source_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command:
    source_id: str
    source_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        GetExactAccountOwnerAssignmentActorAuthoritySourceV3Command(
            self.source_id, self.source_version, self.expected_content_hash, self.as_of
        )


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentActorAuthoritySourceV3Recorder:
    service_id: str
    role: str = "account_actor_authority_attestor"
    kind: str = "service"
    is_automated: bool = True

    def __post_init__(self) -> None:
        _token(self.service_id, "service_id")
        if (self.role, self.kind, self.is_automated) != (
            "account_actor_authority_attestor",
            "service",
            True,
        ):
            raise ValueError("actor authority recorder is fixed")


@dataclass(frozen=True, slots=True)
class PersistedAccountOwnerAssignmentActorAuthoritySourceV3:
    source: AccountOwnerAssignmentActorAuthoritySourceV3
    recorded_by: AccountOwnerAssignmentActorAuthoritySourceV3Recorder

    def __post_init__(self) -> None:
        if type(self.source) is not AccountOwnerAssignmentActorAuthoritySourceV3:
            raise TypeError("source must be an exact actor authority source v3")
        self.source.__post_init__()
        if type(self.recorded_by) is not AccountOwnerAssignmentActorAuthoritySourceV3Recorder:
            raise TypeError("recorded_by must be an exact authority recorder")
        self.recorded_by.__post_init__()


@dataclass(frozen=True, slots=True)
class ExactCurrentActorAuthorityInputBundleV3:
    """One consumer-owned atomic projection of authentication, user, and RBAC sources."""

    context: ExactCurrentAuthenticationContextV3
    user: ExactCurrentAccountUserAuthorityV3
    rbac: ExactCurrentAccountRbacAuthorityV3

    def __post_init__(self) -> None:
        if type(self.context) is not ExactCurrentAuthenticationContextV3:
            raise TypeError("context must be an exact authentication-context projection")
        if type(self.user) is not ExactCurrentAccountUserAuthorityV3:
            raise TypeError("user must be an exact user-authority projection")
        if type(self.rbac) is not ExactCurrentAccountRbacAuthorityV3:
            raise TypeError("rbac must be an exact RBAC-authority projection")
        self.context.__post_init__()
        self.user.__post_init__()
        self.rbac.__post_init__()


class ExactActorAuthorityInputBundleProviderV3(Protocol):
    """Read all three owner sources atomically at one exact cutoff."""

    def get_exact_current(
        self,
        *,
        authentication_context_id: str,
        authentication_context_version: str,
        expected_authentication_context_content_hash: str,
        user_source_id: str,
        user_source_version: str,
        expected_user_source_content_hash: str,
        rbac_source_id: str,
        rbac_source_version: str,
        expected_rbac_source_content_hash: str,
        as_of: datetime,
    ) -> ExactCurrentActorAuthorityInputBundleV3 | None: ...


class AccountOwnerAssignmentActorAuthoritySourceV3Repository(Protocol):
    """Persist immutable authority-source winners and logical chains."""

    def atomic(self) -> AbstractContextManager[None]: ...
    def now(self) -> datetime: ...
    def get_winner(
        self, *, source_id: str, source_version: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentActorAuthoritySourceV3 | None: ...
    def get_current_head(
        self, *, source_id: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentActorAuthoritySourceV3 | None: ...
    def get_exact_by_hash(
        self, *, source_id: str, source_version: str, expected_content_hash: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentActorAuthoritySourceV3 | None: ...
    def append(
        self,
        record: PersistedAccountOwnerAssignmentActorAuthoritySourceV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentActorAuthoritySourceV3: ...


@dataclass(frozen=True, slots=True)
class _Inputs:
    context: ExactCurrentAuthenticationContextV3
    user: ExactCurrentAccountUserAuthorityV3
    rbac: ExactCurrentAccountRbacAuthorityV3


class CaptureAccountOwnerAssignmentActorAuthoritySourceV3:
    """Capture one same-cutoff first winner with double-read and predecessor CAS."""

    def __init__(
        self,
        *,
        input_bundle_provider: ExactActorAuthorityInputBundleProviderV3,
        repository: AccountOwnerAssignmentActorAuthoritySourceV3Repository,
        recorder: AccountOwnerAssignmentActorAuthoritySourceV3Recorder,
        validity_period: timedelta,
    ) -> None:
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._inputs = input_bundle_provider
        self._repository = repository
        self._recorder = recorder
        self._validity_period = validity_period

    def execute(
        self, command: CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command
    ) -> AccountOwnerAssignmentActorAuthoritySourceV3:
        if type(command) is not CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command:
            raise TypeError("command must be an exact authority capture command")
        command.__post_init__()
        with self._repository.atomic():
            cutoff = _aware(self._repository.now(), "repository clock")
            winner = self._repository.get_winner(
                source_id=command.source_id, source_version=command.source_version, as_of=cutoff
            )
            if winner is not None:
                source = _record(winner).source
                if not _matches(source, command) or source.recorded_at > cutoff:
                    raise AccountOwnerAssignmentActorAuthoritySourceV3Conflict(
                        "authority identity has another winner"
                    )
                return source
            first = self._read(command, cutoff)
            try:
                final = self._read(command, cutoff)
            except AccountOwnerAssignmentActorAuthoritySourceV3Unavailable as error:
                raise AccountOwnerAssignmentActorAuthoritySourceV3Conflict(
                    "authority inputs changed"
                ) from error
            if first != final:
                raise AccountOwnerAssignmentActorAuthoritySourceV3Conflict(
                    "authority inputs changed"
                )
            recorded_at = _aware(self._repository.now(), "repository clock")
            if recorded_at < cutoff:
                raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
                    "repository clock moved backwards"
                )
            try:
                recorded = self._read(command, recorded_at)
            except AccountOwnerAssignmentActorAuthoritySourceV3Unavailable as error:
                raise AccountOwnerAssignmentActorAuthoritySourceV3Conflict(
                    "authority inputs changed before recording"
                ) from error
            if recorded != final:
                raise AccountOwnerAssignmentActorAuthoritySourceV3Conflict(
                    "authority inputs changed before recording"
                )
            head_raw = self._repository.get_current_head(
                source_id=command.source_id, as_of=recorded_at
            )
            head = _record(head_raw).source if head_raw is not None else None
            candidate = self._candidate(command, final, cutoff, recorded_at, head)
            persisted = _record(
                self._repository.append(
                    PersistedAccountOwnerAssignmentActorAuthoritySourceV3(
                        candidate, self._recorder
                    ),
                    expected_predecessor_hash=head.content_hash if head else None,
                    recorded_at=recorded_at,
                )
            ).source
            if persisted != candidate:
                raise AccountOwnerAssignmentActorAuthoritySourceV3Conflict(
                    "authority first winner differs"
                )
            return persisted

    def _read(
        self, command: CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command, cutoff: datetime
    ) -> _Inputs:
        return _read_inputs(self._inputs, command, cutoff)

    def _candidate(
        self,
        command: CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command,
        inputs: _Inputs,
        issued_at: datetime,
        recorded_at: datetime,
        head: AccountOwnerAssignmentActorAuthoritySourceV3 | None,
    ) -> AccountOwnerAssignmentActorAuthoritySourceV3:
        context, user, rbac = inputs.context, inputs.user, inputs.rbac
        if head is not None and (
            head.principal_id != command.principal_id
            or head.user_id != command.user_id
            or head.authentication_context_identity_hash != context.identity_hash
            or head.actor_id != user.actor_id
        ):
            raise AccountOwnerAssignmentActorAuthoritySourceV3Conflict(
                "new session cannot extend authority chain"
            )
        state = (
            "revoked"
            if not context.is_authenticated
            else ("deactivated" if not user.is_active else "current")
        )
        source_recorded_at = max(context.recorded_at, user.recorded_at, rbac.recorded_at)
        source_valid_until = min(context.valid_until, user.valid_until, rbac.valid_until)
        ttl = issued_at + self._validity_period
        candidate = AccountOwnerAssignmentActorAuthoritySourceV3(
            source_id=command.source_id,
            source_version=command.source_version,
            principal_id=command.principal_id,
            user_id=command.user_id,
            authentication_context_id=context.context_id,
            authentication_context_version=context.context_version,
            authentication_context_identity_hash=context.identity_hash,
            authentication_context_content_hash=context.content_hash,
            user_source_id=user.source_id,
            user_source_version=user.source_version,
            user_source_content_hash=user.content_hash,
            rbac_source_id=rbac.source_id,
            rbac_source_version=rbac.source_version,
            rbac_source_content_hash=rbac.content_hash,
            actor_id=user.actor_id,
            is_authenticated=context.is_authenticated,
            is_active=user.is_active,
            is_staff=user.is_staff,
            is_superuser=user.is_superuser,
            rbac_role=rbac.rbac_role,
            authority_state=state,
            principal_authenticated_at=context.authenticated_at,
            principal_valid_until=context.valid_until,
            source_recorded_at=source_recorded_at,
            source_valid_until=source_valid_until,
            issued_at=issued_at,
            recorded_at=recorded_at,
            ttl_valid_until=ttl,
            valid_until=min(context.valid_until, source_valid_until, ttl),
            root_claim_hash=(
                None
                if head
                else root_claim_hash_for_actor_authority_source_v3(
                    source_id=command.source_id,
                    principal_id=command.principal_id,
                    user_id=command.user_id,
                    authentication_context_identity_hash=context.identity_hash,
                    actor_id=user.actor_id,
                )
            ),
            supersedes_content_hash=head.content_hash if head else None,
        )
        if head is not None:
            try:
                validate_account_owner_assignment_actor_authority_source_v3_successor(
                    head, candidate
                )
            except (TypeError, ValueError) as error:
                raise AccountOwnerAssignmentActorAuthoritySourceV3Conflict(
                    "authority successor is invalid"
                ) from error
        return candidate


def _read_inputs(
    provider: ExactActorAuthorityInputBundleProviderV3,
    command: CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command,
    cutoff: datetime,
) -> _Inputs:
    bundle = provider.get_exact_current(
        authentication_context_id=command.authentication_context_id,
        authentication_context_version=command.authentication_context_version,
        expected_authentication_context_content_hash=command.expected_authentication_context_content_hash,
        user_source_id=command.user_source_id,
        user_source_version=command.user_source_version,
        expected_user_source_content_hash=command.expected_user_source_content_hash,
        rbac_source_id=command.rbac_source_id,
        rbac_source_version=command.rbac_source_version,
        expected_rbac_source_content_hash=command.expected_rbac_source_content_hash,
        as_of=cutoff,
    )
    if bundle is None:
        raise AccountOwnerAssignmentActorAuthoritySourceV3Unavailable(
            "exact-current authority input is unavailable"
        )
    try:
        bundle.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
            "authority input is corrupt"
        ) from error
    context, user, rbac = bundle.context, bundle.user, bundle.rbac
    if (
        (context.context_id, context.context_version, context.content_hash)
        != (
            command.authentication_context_id,
            command.authentication_context_version,
            command.expected_authentication_context_content_hash,
        )
        or (user.source_id, user.source_version, user.content_hash)
        != (
            command.user_source_id,
            command.user_source_version,
            command.expected_user_source_content_hash,
        )
        or (rbac.source_id, rbac.source_version, rbac.content_hash)
        != (
            command.rbac_source_id,
            command.rbac_source_version,
            command.expected_rbac_source_content_hash,
        )
        or context.principal_id != command.principal_id
        or context.user_id != command.user_id
        or user.user_id != command.user_id
        or rbac.user_id != command.user_id
    ):
        raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
            "authority selector substitution"
        )
    return _Inputs(context, user, rbac)


class GetExactAccountOwnerAssignmentActorAuthoritySourceV3:
    """Read one immutable authority-source version at a PIT cutoff."""

    def __init__(self, repository: AccountOwnerAssignmentActorAuthoritySourceV3Repository) -> None:
        self._repository = repository

    def execute(
        self, command: GetExactAccountOwnerAssignmentActorAuthoritySourceV3Command
    ) -> AccountOwnerAssignmentActorAuthoritySourceV3 | None:
        if type(command) is not GetExactAccountOwnerAssignmentActorAuthoritySourceV3Command:
            raise TypeError("command must be an exact authority PIT command")
        command.__post_init__()
        raw = self._repository.get_exact_by_hash(
            source_id=command.source_id,
            source_version=command.source_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if raw is None:
            return None
        source = _record(raw).source
        if (source.source_id, source.source_version, source.content_hash) != (
            command.source_id,
            command.source_version,
            command.expected_content_hash,
        ):
            raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
                "exact selector substitution"
            )
        return source if source.is_knowable_at(command.as_of) else None


class GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3:
    """Return an exact version only when it is the live final authority head."""

    def __init__(
        self,
        *,
        input_bundle_provider: ExactActorAuthorityInputBundleProviderV3,
        repository: AccountOwnerAssignmentActorAuthoritySourceV3Repository,
    ) -> None:
        self._inputs = input_bundle_provider
        self._repository = repository
        self._exact = GetExactAccountOwnerAssignmentActorAuthoritySourceV3(repository)

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command
    ) -> AccountOwnerAssignmentActorAuthoritySourceV3 | None:
        if type(command) is not GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command:
            raise TypeError("command must be an exact authority current command")
        command.__post_init__()
        source = self._exact.execute(
            GetExactAccountOwnerAssignmentActorAuthoritySourceV3Command(
                command.source_id,
                command.source_version,
                command.expected_content_hash,
                command.as_of,
            )
        )
        if source is None or not source.is_temporally_current_at(command.as_of):
            return None
        selector = CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command(
            source.source_id,
            source.source_version,
            source.principal_id,
            source.user_id,
            source.authentication_context_id,
            source.authentication_context_version,
            source.authentication_context_content_hash,
            source.user_source_id,
            source.user_source_version,
            source.user_source_content_hash,
            source.rbac_source_id,
            source.rbac_source_version,
            source.rbac_source_content_hash,
        )
        try:
            inputs = _read_inputs(self._inputs, selector, command.as_of)
        except AccountOwnerAssignmentActorAuthoritySourceV3Unavailable:
            return None
        if (
            inputs.context.identity_hash != source.authentication_context_identity_hash
            or inputs.user.actor_id != source.actor_id
            or inputs.user.is_active != source.is_active
            or inputs.user.is_staff != source.is_staff
            or inputs.user.is_superuser != source.is_superuser
            or inputs.rbac.rbac_role != source.rbac_role
            or inputs.context.is_authenticated != source.is_authenticated
        ):
            return None
        head = self._repository.get_current_head(source_id=source.source_id, as_of=command.as_of)
        return source if head is not None and _record(head).source == source else None


def _record(value: object) -> PersistedAccountOwnerAssignmentActorAuthoritySourceV3:
    if type(value) is not PersistedAccountOwnerAssignmentActorAuthoritySourceV3:
        raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
            "repository record type substitution"
        )
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentActorAuthoritySourceV3Corruption(
            "repository record is corrupt"
        ) from error
    return value


def _matches(
    source: AccountOwnerAssignmentActorAuthoritySourceV3,
    command: CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command,
) -> bool:
    return (
        source.source_id,
        source.source_version,
        source.principal_id,
        source.user_id,
        source.authentication_context_id,
        source.authentication_context_version,
        source.authentication_context_content_hash,
        source.user_source_id,
        source.user_source_version,
        source.user_source_content_hash,
        source.rbac_source_id,
        source.rbac_source_version,
        source.rbac_source_content_hash,
    ) == (
        command.source_id,
        command.source_version,
        command.principal_id,
        command.user_id,
        command.authentication_context_id,
        command.authentication_context_version,
        command.expected_authentication_context_content_hash,
        command.user_source_id,
        command.user_source_version,
        command.expected_user_source_content_hash,
        command.rbac_source_id,
        command.rbac_source_version,
        command.expected_rbac_source_content_hash,
    )


__all__ = [
    "AccountOwnerAssignmentActorAuthoritySourceV3Conflict",
    "AccountOwnerAssignmentActorAuthoritySourceV3Corruption",
    "AccountOwnerAssignmentActorAuthoritySourceV3Recorder",
    "AccountOwnerAssignmentActorAuthoritySourceV3Repository",
    "AccountOwnerAssignmentActorAuthoritySourceV3Unavailable",
    "CaptureAccountOwnerAssignmentActorAuthoritySourceV3",
    "CaptureAccountOwnerAssignmentActorAuthoritySourceV3Command",
    "ExactActorAuthorityInputBundleProviderV3",
    "ExactCurrentAccountRbacAuthorityV3",
    "ExactCurrentAccountUserAuthorityV3",
    "ExactCurrentActorAuthorityInputBundleV3",
    "ExactCurrentAuthenticationContextV3",
    "GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3",
    "GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3Command",
    "GetExactAccountOwnerAssignmentActorAuthoritySourceV3",
    "GetExactAccountOwnerAssignmentActorAuthoritySourceV3Command",
    "PersistedAccountOwnerAssignmentActorAuthoritySourceV3",
]
