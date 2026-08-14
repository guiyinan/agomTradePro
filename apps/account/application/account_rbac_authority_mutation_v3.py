"""Dormant atomic Application writer contract for Account RBAC mutations v3."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Conflict,
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Recorder,
)
from apps.account.application.account_rbac_authority_source_v3 import (
    PersistedAccountRbacAuthoritySourceV3,
)
from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceClockV3,
    AccountAuthorityRawSourceIdentityV3,
)
from apps.account.domain.account_rbac_authority_source_v3 import (
    ACCOUNT_RBAC_AUTHORITY_ROLES,
    AccountRbacAuthoritySourceV3,
    root_claim_hash_for_account_rbac_authority_source_v3,
    validate_account_rbac_authority_source_v3_successor,
)

_VALIDITY_PERIOD = timedelta(minutes=5)
_RECORDER = AccountActorAuthorityRawSourceV3Recorder("account-rbac-authority-mutation-v3")


def _token(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")
    return value


def _positive(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be an exact positive integer")
    return value


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise AccountActorAuthorityRawSourceV3Corruption(f"{name} must be aware")
    return value


def _role(value: object, name: str) -> str:
    if type(value) is not str or value not in ACCOUNT_RBAC_AUTHORITY_ROLES:
        raise ValueError(f"{name} must be an exact canonical Account role")
    return value


@dataclass(frozen=True, slots=True)
class SetAccountRbacAuthorityRoleV3Command:
    """Identify one canonical role mutation without client facts or clocks."""

    target_user_id: int
    mutation_id: str
    rbac_role: str

    def __post_init__(self) -> None:
        """Validate exact mutation identity and the closed seven-role vocabulary."""
        _positive(self.target_user_id, "target_user_id")
        _token(self.mutation_id, "mutation_id")
        _role(self.rbac_role, "rbac_role")


@dataclass(frozen=True, slots=True)
class AccountRbacAuthorityMutationIdentityV3:
    """Carry the UOW-issued stable source identity for one mutation ID."""

    source_id: str
    source_version: str

    def __post_init__(self) -> None:
        """Validate exact source identity tokens."""
        _token(self.source_id, "source_id")
        _token(self.source_version, "source_version")


@dataclass(frozen=True, slots=True)
class AccountRbacAuthorityProfileStateV3:
    """Project one exact locked Profile authority state."""

    user_id: int
    actor_id: str
    rbac_role: str

    def __post_init__(self) -> None:
        """Validate exact Profile identity and canonical role."""
        _positive(self.user_id, "user_id")
        _token(self.actor_id, "actor_id")
        _role(self.rbac_role, "rbac_role")


@dataclass(frozen=True, slots=True)
class AccountRbacAuthorityMutationObservationV3:
    """Return the exact committed Profile state and server observation clock."""

    state: AccountRbacAuthorityProfileStateV3
    observed_at: datetime

    def __post_init__(self) -> None:
        """Validate exact nested state and aware server observation time."""
        if type(self.state) is not AccountRbacAuthorityProfileStateV3:
            raise TypeError("state must be an exact RBAC Profile state")
        self.state.__post_init__()
        _aware(self.observed_at, "observed_at")


class AccountRbacAuthorityMutationV3UnitOfWork(Protocol):
    """Own one same-alias transaction spanning Profile mutation and raw-ledger append."""

    def atomic(self) -> AbstractContextManager[None]: ...
    def now(self) -> datetime: ...
    def resolve_source_identity(
        self, *, target_user_id: int, mutation_id: str
    ) -> AccountRbacAuthorityMutationIdentityV3: ...
    def get_winner(
        self, *, source_id: str, source_version: str, as_of: datetime
    ) -> PersistedAccountRbacAuthoritySourceV3 | None: ...
    def get_current_head(
        self, *, source_id: str, as_of: datetime
    ) -> PersistedAccountRbacAuthoritySourceV3 | None: ...
    def lock_profile(self, *, user_id: int) -> AccountRbacAuthorityProfileStateV3 | None: ...
    def compare_and_set_profile(
        self, *, expected: AccountRbacAuthorityProfileStateV3, new_rbac_role: str
    ) -> AccountRbacAuthorityMutationObservationV3: ...
    def append(
        self,
        record: PersistedAccountRbacAuthoritySourceV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountRbacAuthoritySourceV3: ...


class SetAccountRbacAuthorityRoleV3:
    """Use one shared UOW to mutate Profile and append its exact immutable source."""

    def __init__(self, unit_of_work: AccountRbacAuthorityMutationV3UnitOfWork) -> None:
        self._uow = unit_of_work

    def execute(
        self, command: SetAccountRbacAuthorityRoleV3Command
    ) -> AccountRbacAuthoritySourceV3:
        """Return exact replay or atomically record one current-role mutation."""
        if type(command) is not SetAccountRbacAuthorityRoleV3Command:
            raise TypeError("command must be an exact RBAC mutation command")
        command.__post_init__()
        with self._uow.atomic():
            identity = self._identity(command)
            cutoff = _aware(self._uow.now(), "cutoff")
            winner = self._uow.get_winner(
                source_id=identity.source_id, source_version=identity.source_version, as_of=cutoff
            )
            if winner is not None:
                return self._replay(winner, command, identity)
            head_record = self._head(identity.source_id, cutoff)
            head = head_record.source if head_record else None
            profile = self._profile(command.target_user_id)
            if head is not None:
                if head.authority_state != "current":
                    raise AccountActorAuthorityRawSourceV3Conflict("RBAC head is terminal")
                if (head.user_id, head.actor_id, head.rbac_role) != (
                    profile.user_id,
                    profile.actor_id,
                    profile.rbac_role,
                ):
                    raise AccountActorAuthorityRawSourceV3Conflict(
                        "locked Profile differs from RBAC head"
                    )
            observation = self._observation(
                self._uow.compare_and_set_profile(
                    expected=profile, new_rbac_role=command.rbac_role
                ),
                command,
                profile.actor_id,
            )
            recorded_at = _aware(self._uow.now(), "recorded_at")
            if observation.observed_at > recorded_at:
                raise AccountActorAuthorityRawSourceV3Corruption(
                    "observation is later than recording"
                )
            final_head = self._head(identity.source_id, recorded_at)
            if final_head != head_record:
                raise AccountActorAuthorityRawSourceV3Conflict("RBAC head changed")
            candidate = self._candidate(identity, observation, recorded_at, head)
            persisted = _record(
                self._uow.append(
                    PersistedAccountRbacAuthoritySourceV3(candidate, _RECORDER),
                    expected_predecessor_hash=head.content_hash if head else None,
                    recorded_at=recorded_at,
                )
            )
            if persisted.source != candidate:
                raise AccountActorAuthorityRawSourceV3Conflict("append winner differs")
            post_winner = self._uow.get_winner(
                source_id=identity.source_id,
                source_version=identity.source_version,
                as_of=recorded_at,
            )
            post_head = self._head(identity.source_id, recorded_at)
            post_profile = self._profile(command.target_user_id)
            if (
                _record(post_winner) != persisted
                or post_head != persisted
                or post_profile != observation.state
            ):
                raise AccountActorAuthorityRawSourceV3Conflict(
                    "post-mutation exact verification failed"
                )
            return candidate

    def _identity(
        self, command: SetAccountRbacAuthorityRoleV3Command
    ) -> AccountRbacAuthorityMutationIdentityV3:
        value = self._uow.resolve_source_identity(
            target_user_id=command.target_user_id, mutation_id=command.mutation_id
        )
        if type(value) is not AccountRbacAuthorityMutationIdentityV3:
            raise AccountActorAuthorityRawSourceV3Corruption("identity type substitution")
        value.__post_init__()
        return value

    def _replay(
        self,
        raw: object,
        command: SetAccountRbacAuthorityRoleV3Command,
        identity: AccountRbacAuthorityMutationIdentityV3,
    ) -> AccountRbacAuthoritySourceV3:
        source = _record(raw).source
        if (
            source.identity.source_id,
            source.identity.source_version,
            source.user_id,
            source.rbac_role,
            source.authority_state,
        ) != (
            identity.source_id,
            identity.source_version,
            command.target_user_id,
            command.rbac_role,
            "current",
        ):
            raise AccountActorAuthorityRawSourceV3Conflict("mutation winner differs")
        return source

    def _profile(self, user_id: int) -> AccountRbacAuthorityProfileStateV3:
        value = self._uow.lock_profile(user_id=user_id)
        if type(value) is not AccountRbacAuthorityProfileStateV3:
            raise AccountActorAuthorityRawSourceV3Corruption(
                "Profile state is unavailable or substituted"
            )
        value.__post_init__()
        if value.user_id != user_id:
            raise AccountActorAuthorityRawSourceV3Corruption("Profile user substituted")
        return value

    def _head(
        self, source_id: str, as_of: datetime
    ) -> PersistedAccountRbacAuthoritySourceV3 | None:
        raw = self._uow.get_current_head(source_id=source_id, as_of=as_of)
        if raw is None:
            return None
        record = _record(raw)
        if record.source.identity.source_id != source_id:
            raise AccountActorAuthorityRawSourceV3Corruption("head source substituted")
        return record

    def _observation(
        self, value: object, command: SetAccountRbacAuthorityRoleV3Command, actor_id: str
    ) -> AccountRbacAuthorityMutationObservationV3:
        if type(value) is not AccountRbacAuthorityMutationObservationV3:
            raise AccountActorAuthorityRawSourceV3Corruption(
                "mutation observation type substituted"
            )
        value.__post_init__()
        if (value.state.user_id, value.state.actor_id, value.state.rbac_role) != (
            command.target_user_id,
            actor_id,
            command.rbac_role,
        ):
            raise AccountActorAuthorityRawSourceV3Conflict("mutation observation differs")
        return value

    def _candidate(
        self,
        identity: AccountRbacAuthorityMutationIdentityV3,
        observation: AccountRbacAuthorityMutationObservationV3,
        recorded_at: datetime,
        head: AccountRbacAuthoritySourceV3 | None,
    ) -> AccountRbacAuthoritySourceV3:
        state = observation.state
        candidate = AccountRbacAuthoritySourceV3(
            identity=AccountAuthorityRawSourceIdentityV3(
                identity.source_id, identity.source_version
            ),
            clock=AccountAuthorityRawSourceClockV3(
                observation.observed_at, recorded_at, recorded_at + _VALIDITY_PERIOD
            ),
            chain=AccountAuthorityRawSourceChainV3(
                root_claim_hash=(
                    root_claim_hash_for_account_rbac_authority_source_v3(
                        source_id=identity.source_id, user_id=state.user_id, actor_id=state.actor_id
                    )
                    if head is None
                    else None
                ),
                supersedes_content_hash=head.content_hash if head else None,
            ),
            user_id=state.user_id,
            actor_id=state.actor_id,
            rbac_role=state.rbac_role,
            authority_state="current",
        )
        if head is not None:
            try:
                validate_account_rbac_authority_source_v3_successor(head, candidate)
            except (TypeError, ValueError) as error:
                raise AccountActorAuthorityRawSourceV3Conflict(
                    "RBAC successor is invalid"
                ) from error
        return candidate


def _record(value: object) -> PersistedAccountRbacAuthoritySourceV3:
    if type(value) is not PersistedAccountRbacAuthoritySourceV3:
        raise AccountActorAuthorityRawSourceV3Corruption("record type substitution")
    value.__post_init__()
    return value


__all__ = [
    "AccountRbacAuthorityMutationIdentityV3",
    "AccountRbacAuthorityMutationObservationV3",
    "AccountRbacAuthorityMutationV3UnitOfWork",
    "AccountRbacAuthorityProfileStateV3",
    "SetAccountRbacAuthorityRoleV3",
    "SetAccountRbacAuthorityRoleV3Command",
]
