"""Dormant read and persistence contracts for RBAC mutation binding v3."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.application.account_actor_authority_raw_source_primitives_v3 import (
    AccountActorAuthorityRawSourceV3Conflict,
    AccountActorAuthorityRawSourceV3Corruption,
    AccountActorAuthorityRawSourceV3Unavailable,
)
from apps.account.application.account_rbac_authority_source_v3 import (
    PersistedAccountRbacAuthoritySourceV3,
)
from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
)
from apps.account.domain.account_rbac_authority_mutation_binding_v3 import (
    MUTATION_KINDS,
    AccountRbacAuthorityHumanOperatorRefV3,
    AccountRbacAuthorityMutationBindingV3,
    AccountRbacAuthorityMutationIssuerV3,
    AccountRbacAuthorityProfileStateRefV3,
    AccountRbacAuthoritySourceEpochV3,
    root_claim_hash_for_account_rbac_authority_mutation_binding_v3,
    validate_account_rbac_authority_mutation_binding_v3_successor,
)
from apps.account.domain.account_rbac_authority_source_v3 import (
    AccountRbacAuthoritySourceV3,
)


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


def _digest(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be an exact timezone-aware datetime")
    return value


def _positive(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be an exact positive integer")
    return value


def _optional_token(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _token(value, name)


def _optional_digest(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _digest(value, name)


@dataclass(frozen=True, slots=True)
class AccountRbacAuthorityMutationBindingV3Identity:
    """Carry one UOW-issued mutation identity and its immutable source epoch."""

    mutation_id: str
    source_version: str
    epoch: AccountRbacAuthoritySourceEpochV3

    def __post_init__(self) -> None:
        """Validate the exact mutation token and nested epoch identity."""

        _token(self.mutation_id, "mutation_id")
        _token(self.source_version, "source_version")
        if type(self.epoch) is not AccountRbacAuthoritySourceEpochV3:
            raise TypeError("epoch must be an exact RBAC source epoch v3")
        self.epoch.__post_init__()


@dataclass(frozen=True, slots=True)
class AccountRbacAuthorityMutationBindingV3Command:
    """Select immutable binding inputs using only IDs, versions, and hashes."""

    mutation_id: str
    mutation_kind: str
    target_user_id: int
    new_profile_id: str
    new_profile_version: str
    expected_new_profile_content_hash: str
    operator_principal_id: str
    expected_operator_authority_hash: str
    expected_authority_source_content_hash: str
    old_profile_id: str | None = None
    old_profile_version: str | None = None
    expected_old_profile_content_hash: str | None = None

    def __post_init__(self) -> None:
        """Reject mutable facts, role aliases, clocks, and partial selectors."""

        for name in (
            "mutation_id",
            "new_profile_id",
            "new_profile_version",
            "operator_principal_id",
        ):
            _token(getattr(self, name), name)
        _positive(self.target_user_id, "target_user_id")
        if type(self.mutation_kind) is not str or self.mutation_kind not in MUTATION_KINDS:
            raise ValueError("mutation_kind is invalid")
        _digest(self.expected_new_profile_content_hash, "expected_new_profile_content_hash")
        _digest(self.expected_operator_authority_hash, "expected_operator_authority_hash")
        _digest(
            self.expected_authority_source_content_hash,
            "expected_authority_source_content_hash",
        )
        old_values = (
            self.old_profile_id,
            self.old_profile_version,
            self.expected_old_profile_content_hash,
        )
        if self.mutation_kind == "bootstrap":
            if any(value is not None for value in old_values):
                raise ValueError("bootstrap cannot select an old Profile")
        elif any(value is None for value in old_values):
            raise ValueError("non-bootstrap mutation requires a complete old Profile selector")
        _optional_token(self.old_profile_id, "old_profile_id")
        _optional_token(self.old_profile_version, "old_profile_version")
        _optional_digest(
            self.expected_old_profile_content_hash,
            "expected_old_profile_content_hash",
        )


class AccountRbacAuthorityMutationBindingV3UnitOfWork(Protocol):
    """Own one same-alias atomic binding write and every exact evidence read."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the one repository-owned, non-nestable transaction."""

        ...

    def now(self) -> datetime:
        """Return the authoritative aware server clock."""

        ...

    def get_winner(
        self,
        *,
        mutation_id: str,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> PersistedAccountRbacAuthorityMutationBindingV3 | None:
        """Return the first exact binding winner knowable at the PIT."""

        ...

    def get_current_head(
        self, *, source_id: str, as_of: datetime
    ) -> PersistedAccountRbacAuthorityMutationBindingV3 | None:
        """Return a source-epoch final head, including expired/terminal heads."""

        ...

    def get_terminal_head(
        self, *, target_user_id: int, as_of: datetime
    ) -> PersistedAccountRbacAuthorityMutationBindingV3 | None:
        """Return the terminal predecessor used to open a new reactivation epoch."""

        ...

    def resolve_identity(
        self,
        *,
        mutation_id: str,
        target_user_id: int,
    ) -> AccountRbacAuthorityMutationBindingV3Identity:
        """Resolve server-issued mutation/epoch identity without mutable reads."""

        ...

    def get_exact_profile(
        self,
        *,
        profile_id: str,
        profile_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AccountRbacAuthorityProfileStateRefV3 | None:
        """Return one exact immutable Profile reference by ID/version/hash."""

        ...

    def get_human_operator(
        self,
        *,
        principal_id: str,
        expected_authority_hash: str,
        as_of: datetime,
    ) -> AccountRbacAuthorityHumanOperatorRefV3 | None:
        """Return one exact human operator authority reference by ID/hash."""

        ...

    def get_exact_raw_source(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountRbacAuthoritySourceV3 | AccountRbacAuthoritySourceV3 | None:
        """Return one exact immutable RBAC raw source by ID/version/hash."""

        ...

    def get_current_raw_source(
        self,
        *,
        source_id: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountRbacAuthoritySourceV3 | AccountRbacAuthoritySourceV3 | None:
        """Return the exact-current raw source matching the requested hash."""

        ...

    def append(
        self,
        record: PersistedAccountRbacAuthorityMutationBindingV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountRbacAuthorityMutationBindingV3:
        """Append through exact predecessor CAS on the same alias/UOW."""

        ...


@dataclass(frozen=True, slots=True)
class _BindingInputs:
    """Immutable evidence captured after a winner miss."""

    identity: AccountRbacAuthorityMutationBindingV3Identity
    predecessor: AccountRbacAuthorityMutationBindingV3 | None
    old_subject: AccountRbacAuthorityProfileStateRefV3 | None
    subject: AccountRbacAuthorityProfileStateRefV3
    operator: AccountRbacAuthorityHumanOperatorRefV3
    authority_source: AccountRbacAuthoritySourceV3


class RecordAccountRbacAuthorityMutationBindingV3:
    """DORMANT winner-first writer for one immutable RBAC mutation binding."""

    def __init__(
        self,
        unit_of_work: AccountRbacAuthorityMutationBindingV3UnitOfWork,
        issuer: AccountRbacAuthorityMutationIssuerV3 | None = None,
    ) -> None:
        """Inject one typed UOW and the fixed non-human issuer evidence."""

        if issuer is None:
            issuer = AccountRbacAuthorityMutationIssuerV3(
                "account-rbac-authority-mutation-binding-v3"
            )
        if type(issuer) is not AccountRbacAuthorityMutationIssuerV3:
            raise TypeError("issuer must be an exact RBAC mutation issuer")
        issuer.__post_init__()
        self._unit_of_work = unit_of_work
        self._issuer = issuer

    def execute(
        self, command: AccountRbacAuthorityMutationBindingV3Command
    ) -> PersistedAccountRbacAuthorityMutationBindingV3:
        """Replay the first winner or append one complete binding atomically."""

        checked = _command(command)
        with self._unit_of_work.atomic():
            cutoff = _clock(self._unit_of_work.now(), "binding cutoff")
            identity = self._identity(checked)
            winner = self._unit_of_work.get_winner(
                mutation_id=checked.mutation_id,
                source_id=identity.epoch.source_id,
                source_version=identity.source_version,
                as_of=cutoff,
            )
            if winner is not None:
                return self._replay(winner, checked, identity, cutoff)

            predecessor = self._predecessor(checked, identity, cutoff)
            inputs = self._inputs(checked, identity, predecessor, cutoff)
            recorded_at = _clock(self._unit_of_work.now(), "binding recorded_at")
            if recorded_at < cutoff:
                raise AccountActorAuthorityRawSourceV3Corruption(
                    "binding repository clock moved backwards"
                )
            candidate = self._candidate(inputs, checked, cutoff, recorded_at)
            expected = PersistedAccountRbacAuthorityMutationBindingV3(candidate)
            persisted = _record(
                self._unit_of_work.append(
                    expected,
                    expected_predecessor_hash=(
                        None if predecessor is None else predecessor.content_hash
                    ),
                    recorded_at=recorded_at,
                )
            )
            if persisted != expected:
                raise AccountActorAuthorityRawSourceV3Conflict(
                    "RBAC mutation binding append winner differs"
                )
            post_winner = self._unit_of_work.get_winner(
                mutation_id=checked.mutation_id,
                source_id=identity.epoch.source_id,
                source_version=identity.source_version,
                as_of=recorded_at,
            )
            if _record(post_winner) != persisted:
                raise AccountActorAuthorityRawSourceV3Conflict(
                    "RBAC mutation binding winner verification failed"
                )
            post_head = self._unit_of_work.get_current_head(
                source_id=identity.epoch.source_id,
                as_of=recorded_at,
            )
            if _record(post_head) != persisted:
                raise AccountActorAuthorityRawSourceV3Conflict(
                    "RBAC mutation binding head verification failed"
                )
            return persisted

    def _identity(
        self, command: AccountRbacAuthorityMutationBindingV3Command
    ) -> AccountRbacAuthorityMutationBindingV3Identity:
        value = self._unit_of_work.resolve_identity(
            mutation_id=command.mutation_id,
            target_user_id=command.target_user_id,
        )
        if type(value) is not AccountRbacAuthorityMutationBindingV3Identity:
            raise AccountActorAuthorityRawSourceV3Corruption(
                "RBAC mutation binding identity substitution"
            )
        try:
            value.__post_init__()
        except (TypeError, ValueError) as error:
            raise AccountActorAuthorityRawSourceV3Corruption(
                "RBAC mutation binding identity is corrupt"
            ) from error
        epoch = value.epoch
        if (value.mutation_id, epoch.target_user_id) != (
            command.mutation_id,
            command.target_user_id,
        ):
            raise AccountActorAuthorityRawSourceV3Conflict("stable mutation/epoch identity differs")
        return value

    def _predecessor(
        self,
        command: AccountRbacAuthorityMutationBindingV3Command,
        identity: AccountRbacAuthorityMutationBindingV3Identity,
        cutoff: datetime,
    ) -> AccountRbacAuthorityMutationBindingV3 | None:
        raw: PersistedAccountRbacAuthorityMutationBindingV3 | None
        if command.mutation_kind == "reactivate":
            raw = self._unit_of_work.get_terminal_head(
                target_user_id=command.target_user_id,
                as_of=cutoff,
            )
        else:
            raw = self._unit_of_work.get_current_head(
                source_id=identity.epoch.source_id,
                as_of=cutoff,
            )
        if raw is None:
            if command.mutation_kind == "bootstrap":
                return None
            raise AccountActorAuthorityRawSourceV3Unavailable(
                "RBAC mutation binding predecessor is unavailable"
            )
        record = _record(raw)
        predecessor = record.binding
        if not predecessor.is_knowable_at(cutoff):
            raise AccountActorAuthorityRawSourceV3Corruption(
                "repository returned a future RBAC mutation predecessor"
            )
        if command.mutation_kind == "bootstrap":
            raise AccountActorAuthorityRawSourceV3Conflict(
                "bootstrap cannot follow an existing RBAC mutation head"
            )
        if command.mutation_kind == "reactivate":
            if predecessor.new_authority_state != "revoked":
                raise AccountActorAuthorityRawSourceV3Conflict(
                    "reactivation requires a revoked terminal predecessor"
                )
        elif predecessor.new_authority_state != "current":
            raise AccountActorAuthorityRawSourceV3Conflict("revoked RBAC mutation head is terminal")
        return predecessor

    def _inputs(
        self,
        command: AccountRbacAuthorityMutationBindingV3Command,
        identity: AccountRbacAuthorityMutationBindingV3Identity,
        predecessor: AccountRbacAuthorityMutationBindingV3 | None,
        cutoff: datetime,
    ) -> _BindingInputs:
        subject = _profile(
            self._unit_of_work.get_exact_profile(
                profile_id=command.new_profile_id,
                profile_version=command.new_profile_version,
                expected_content_hash=command.expected_new_profile_content_hash,
                as_of=cutoff,
            ),
            profile_id=command.new_profile_id,
            profile_version=command.new_profile_version,
            expected_content_hash=command.expected_new_profile_content_hash,
            cutoff=cutoff,
        )
        old_subject: AccountRbacAuthorityProfileStateRefV3 | None = None
        if command.mutation_kind != "bootstrap":
            old_profile_id = command.old_profile_id
            old_profile_version = command.old_profile_version
            old_profile_content_hash = command.expected_old_profile_content_hash
            if (
                type(old_profile_id) is not str
                or type(old_profile_version) is not str
                or type(old_profile_content_hash) is not str
            ):
                raise AccountActorAuthorityRawSourceV3Corruption(
                    "non-bootstrap old Profile selector is incomplete"
                )
            old_subject = _profile(
                self._unit_of_work.get_exact_profile(
                    profile_id=old_profile_id,
                    profile_version=old_profile_version,
                    expected_content_hash=old_profile_content_hash,
                    as_of=cutoff,
                ),
                profile_id=old_profile_id,
                profile_version=old_profile_version,
                expected_content_hash=old_profile_content_hash,
                cutoff=cutoff,
            )
            if predecessor is None or old_subject != predecessor.subject:
                raise AccountActorAuthorityRawSourceV3Conflict(
                    "old Profile reference does not bind the final predecessor"
                )
        operator = _operator(
            self._unit_of_work.get_human_operator(
                principal_id=command.operator_principal_id,
                expected_authority_hash=command.expected_operator_authority_hash,
                as_of=cutoff,
            ),
            principal_id=command.operator_principal_id,
            expected_authority_hash=command.expected_operator_authority_hash,
            cutoff=cutoff,
        )
        exact_source = _source(
            self._unit_of_work.get_exact_raw_source(
                source_id=identity.epoch.source_id,
                source_version=identity.source_version,
                expected_content_hash=command.expected_authority_source_content_hash,
                as_of=cutoff,
            ),
            source_id=identity.epoch.source_id,
            source_version=identity.source_version,
            expected_content_hash=command.expected_authority_source_content_hash,
            cutoff=cutoff,
        )
        current_source = _source(
            self._unit_of_work.get_current_raw_source(
                source_id=identity.epoch.source_id,
                expected_content_hash=command.expected_authority_source_content_hash,
                as_of=cutoff,
            ),
            source_id=identity.epoch.source_id,
            source_version=identity.source_version,
            expected_content_hash=command.expected_authority_source_content_hash,
            cutoff=cutoff,
        )
        if current_source != exact_source:
            raise AccountActorAuthorityRawSourceV3Conflict(
                "exact/current RBAC raw source changed during binding"
            )
        if (subject.user_id, subject.subject_actor_id) != (
            identity.epoch.target_user_id,
            identity.epoch.subject_actor_id,
        ):
            raise AccountActorAuthorityRawSourceV3Corruption(
                "new Profile reference differs from source epoch"
            )
        if (exact_source.user_id, exact_source.actor_id) != (
            subject.user_id,
            subject.subject_actor_id,
        ):
            raise AccountActorAuthorityRawSourceV3Corruption(
                "raw RBAC source differs from exact new Profile"
            )
        return _BindingInputs(identity, predecessor, old_subject, subject, operator, exact_source)

    def _candidate(
        self,
        inputs: _BindingInputs,
        command: AccountRbacAuthorityMutationBindingV3Command,
        issued_at: datetime,
        recorded_at: datetime,
    ) -> AccountRbacAuthorityMutationBindingV3:
        identity = inputs.identity
        predecessor = inputs.predecessor
        source = inputs.authority_source
        expected_state = {
            "bootstrap": "current",
            "role_change": "current",
            "revoke": "revoked",
            "reactivate": "current",
        }[command.mutation_kind]
        if source.authority_state != expected_state:
            raise AccountActorAuthorityRawSourceV3Conflict(
                "raw RBAC source state differs from mutation kind"
            )
        if source.rbac_role != inputs.subject.rbac_role:
            raise AccountActorAuthorityRawSourceV3Conflict(
                "raw RBAC source role differs from exact new Profile"
            )
        if predecessor is not None and command.mutation_kind == "reactivate":
            if identity.epoch.epoch_sequence <= predecessor.epoch.epoch_sequence:
                raise AccountActorAuthorityRawSourceV3Conflict(
                    "reactivation must open a new source epoch"
                )
        valid_until = min(source.clock.valid_until, inputs.operator.valid_until)
        if recorded_at >= valid_until:
            raise AccountActorAuthorityRawSourceV3Unavailable(
                "RBAC mutation binding expires before it can be recorded"
            )
        try:
            candidate = AccountRbacAuthorityMutationBindingV3(
                mutation_id=identity.mutation_id,
                mutation_kind=command.mutation_kind,
                epoch=identity.epoch,
                old_subject=inputs.old_subject,
                subject=inputs.subject,
                operator=inputs.operator,
                issuer=self._issuer,
                source_version=identity.source_version,
                old_authority_state=(
                    None if predecessor is None else predecessor.new_authority_state
                ),
                new_authority_state=source.authority_state,
                old_rbac_role=(None if predecessor is None else predecessor.new_rbac_role),
                new_rbac_role=inputs.subject.rbac_role,
                authority_source_identity_hash=source.identity_hash,
                authority_source_content_hash=source.content_hash,
                authority_source_record_seal=source.record_seal,
                observed_at=source.clock.observed_at,
                issued_at=issued_at,
                recorded_at=recorded_at,
                valid_until=valid_until,
                binding_chain=AccountAuthorityRawSourceChainV3(
                    root_claim_hash=(
                        root_claim_hash_for_account_rbac_authority_mutation_binding_v3(
                            identity.epoch.target_user_id,
                            identity.epoch.subject_actor_id,
                        )
                        if predecessor is None
                        else None
                    ),
                    supersedes_content_hash=(
                        None if predecessor is None else predecessor.content_hash
                    ),
                ),
                authority_source_chain=source.chain,
            )
        except (TypeError, ValueError) as error:
            raise AccountActorAuthorityRawSourceV3Corruption(
                "RBAC mutation binding candidate is corrupt"
            ) from error
        if predecessor is not None:
            try:
                validate_account_rbac_authority_mutation_binding_v3_successor(
                    predecessor, candidate
                )
            except (TypeError, ValueError) as error:
                raise AccountActorAuthorityRawSourceV3Conflict(
                    "RBAC mutation binding successor is invalid"
                ) from error
        return candidate

    def _replay(
        self,
        value: object,
        command: AccountRbacAuthorityMutationBindingV3Command,
        identity: AccountRbacAuthorityMutationBindingV3Identity,
        cutoff: datetime,
    ) -> PersistedAccountRbacAuthorityMutationBindingV3:
        record = _record(value)
        binding = record.binding
        if binding.recorded_at > cutoff:
            raise AccountActorAuthorityRawSourceV3Corruption(
                "repository returned a future RBAC mutation binding winner"
            )
        old = binding.old_subject
        if (
            binding.mutation_id,
            binding.mutation_kind,
            binding.epoch.epoch_id,
            binding.epoch.epoch_sequence,
            binding.epoch.source_id,
            binding.epoch.target_user_id,
            binding.source_version,
            binding.subject.profile_id,
            binding.subject.profile_version,
            binding.subject.profile_content_hash,
            binding.operator.principal_id,
            binding.operator.authority_hash,
            binding.authority_source_content_hash,
        ) != (
            command.mutation_id,
            command.mutation_kind,
            identity.epoch.epoch_id,
            identity.epoch.epoch_sequence,
            identity.epoch.source_id,
            command.target_user_id,
            identity.source_version,
            command.new_profile_id,
            command.new_profile_version,
            command.expected_new_profile_content_hash,
            command.operator_principal_id,
            command.expected_operator_authority_hash,
            command.expected_authority_source_content_hash,
        ):
            raise AccountActorAuthorityRawSourceV3Conflict(
                "RBAC mutation binding first winner differs"
            )
        if command.mutation_kind == "bootstrap":
            if old is not None:
                raise AccountActorAuthorityRawSourceV3Corruption(
                    "bootstrap winner unexpectedly carries an old Profile"
                )
        elif old is None or (
            old.profile_id,
            old.profile_version,
            old.profile_content_hash,
        ) != (
            command.old_profile_id,
            command.old_profile_version,
            command.expected_old_profile_content_hash,
        ):
            raise AccountActorAuthorityRawSourceV3Conflict(
                "RBAC mutation binding old Profile winner differs"
            )
        return record


def _clock(value: object, name: str) -> datetime:
    """Validate a UOW server clock and translate malformed clocks to corruption."""

    try:
        return _aware(value, name)
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption(str(error)) from error


def _command(value: object) -> AccountRbacAuthorityMutationBindingV3Command:
    """Validate an exact writer command and translate malformed input."""

    if type(value) is not AccountRbacAuthorityMutationBindingV3Command:
        raise TypeError("command must be an exact RBAC mutation binding v3 command")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "RBAC mutation binding command is corrupt"
        ) from error
    return value


def _profile(
    value: object,
    *,
    profile_id: str,
    profile_version: str,
    expected_content_hash: str,
    cutoff: datetime,
) -> AccountRbacAuthorityProfileStateRefV3:
    """Validate an exact Profile reference returned by the typed UOW."""

    if value is None:
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "exact RBAC Profile reference is unavailable"
        )
    if type(value) is not AccountRbacAuthorityProfileStateRefV3:
        raise AccountActorAuthorityRawSourceV3Corruption("Profile reference type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption("Profile reference is corrupt") from error
    if (
        value.profile_id,
        value.profile_version,
        value.profile_content_hash,
    ) != (profile_id, profile_version, expected_content_hash):
        raise AccountActorAuthorityRawSourceV3Corruption("Profile selector substitution")
    if value.observed_at > cutoff:
        raise AccountActorAuthorityRawSourceV3Corruption("Profile reference is from the future")
    return value


def _operator(
    value: object,
    *,
    principal_id: str,
    expected_authority_hash: str,
    cutoff: datetime,
) -> AccountRbacAuthorityHumanOperatorRefV3:
    """Validate the exact human operator authority returned by the typed UOW."""

    if value is None:
        raise AccountActorAuthorityRawSourceV3Unavailable(
            "human operator authority reference is unavailable"
        )
    if type(value) is not AccountRbacAuthorityHumanOperatorRefV3:
        raise AccountActorAuthorityRawSourceV3Corruption("operator reference type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption("operator reference is corrupt") from error
    if (value.principal_id, value.authority_hash) != (principal_id, expected_authority_hash):
        raise AccountActorAuthorityRawSourceV3Corruption("operator selector substitution")
    if value.observed_at > cutoff:
        raise AccountActorAuthorityRawSourceV3Corruption("operator reference is from the future")
    return value


def _source(
    value: object,
    *,
    source_id: str,
    source_version: str,
    expected_content_hash: str,
    cutoff: datetime,
) -> AccountRbacAuthoritySourceV3:
    """Validate either the pure source or its Application persisted wrapper."""

    source: AccountRbacAuthoritySourceV3
    if type(value) is PersistedAccountRbacAuthoritySourceV3:
        try:
            value.__post_init__()
        except (TypeError, ValueError) as error:
            raise AccountActorAuthorityRawSourceV3Corruption(
                "persisted RBAC raw source is corrupt"
            ) from error
        source = value.source
    elif type(value) is AccountRbacAuthoritySourceV3:
        source = value
    elif value is None:
        raise AccountActorAuthorityRawSourceV3Unavailable("exact RBAC raw source is unavailable")
    else:
        raise AccountActorAuthorityRawSourceV3Corruption("RBAC raw source type substitution")
    try:
        source.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption("RBAC raw source is corrupt") from error
    if (
        source.identity.source_id,
        source.identity.source_version,
        source.content_hash,
    ) != (source_id, source_version, expected_content_hash):
        raise AccountActorAuthorityRawSourceV3Corruption("RBAC raw source selector substitution")
    if not source.is_knowable_at(cutoff):
        raise AccountActorAuthorityRawSourceV3Corruption("RBAC raw source is from the future")
    return source


@dataclass(frozen=True, slots=True)
class AccountRbacAuthorityMutationBindingV3Selector:
    """ID/hash/PIT selector for one immutable mutation binding."""

    mutation_id: str
    source_id: str
    source_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        """Validate exact selector scalars and the aware PIT clock."""

        _token(self.mutation_id, "mutation_id")
        _token(self.source_id, "source_id")
        _token(self.source_version, "source_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class PersistedAccountRbacAuthorityMutationBindingV3:
    """Carry one exact Domain binding across the repository boundary."""

    binding: AccountRbacAuthorityMutationBindingV3

    def __post_init__(self) -> None:
        """Revalidate the immutable binding and reject type substitution."""

        if type(self.binding) is not AccountRbacAuthorityMutationBindingV3:
            raise TypeError("binding must be an exact RBAC mutation binding v3")
        self.binding.__post_init__()


class AccountRbacAuthorityMutationBindingV3Repository(Protocol):
    """Persist mutation bindings and their candidate-independent logical chains."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the repository-owned, same-alias non-nestable unit of work."""

        ...

    def now(self) -> datetime:
        """Return the repository's authoritative aware server clock."""

        ...

    def get_winner(
        self,
        *,
        mutation_id: str,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> PersistedAccountRbacAuthorityMutationBindingV3 | None:
        """Return the exact first winner knowable at the PIT cutoff."""

        ...

    def get_current_head(
        self, *, source_id: str, as_of: datetime
    ) -> PersistedAccountRbacAuthorityMutationBindingV3 | None:
        """Return the final source-epoch binding head, including terminal heads."""

        ...

    def get_exact_by_hash(
        self,
        *,
        mutation_id: str,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountRbacAuthorityMutationBindingV3 | None:
        """Return one exact historical binding at a recorded PIT."""

        ...

    def append(
        self,
        record: PersistedAccountRbacAuthorityMutationBindingV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountRbacAuthorityMutationBindingV3:
        """Append one binding through predecessor CAS; no capture orchestration."""

        ...


class GetExactAccountRbacAuthorityMutationBindingV3:
    """Read one exact historical binding without TTL or head fallback."""

    def __init__(self, repository: AccountRbacAuthorityMutationBindingV3Repository) -> None:
        """Store the injected repository contract."""

        self._repository = repository

    def execute(
        self, selector: AccountRbacAuthorityMutationBindingV3Selector
    ) -> AccountRbacAuthorityMutationBindingV3 | None:
        """Return the exact binding only when it is knowable at the PIT."""

        checked = _selector(selector)
        raw = self._repository.get_exact_by_hash(
            mutation_id=checked.mutation_id,
            source_id=checked.source_id,
            source_version=checked.source_version,
            expected_content_hash=checked.expected_content_hash,
            as_of=checked.as_of,
        )
        if raw is None:
            return None
        record = _record(raw)
        binding = record.binding
        if not binding.is_knowable_at(checked.as_of):
            raise AccountActorAuthorityRawSourceV3Corruption(
                "repository returned a future RBAC mutation binding"
            )
        if _binding_identity(binding) != (
            checked.mutation_id,
            checked.source_id,
            checked.source_version,
            checked.expected_content_hash,
        ):
            raise AccountActorAuthorityRawSourceV3Corruption(
                "RBAC mutation binding exact selector substitution"
            )
        return binding


class GetCurrentAccountRbacAuthorityMutationBindingV3:
    """Return an exact binding only while it is the final temporal head."""

    def __init__(self, repository: AccountRbacAuthorityMutationBindingV3Repository) -> None:
        """Store the injected repository contract."""

        self._repository = repository

    def execute(
        self, selector: AccountRbacAuthorityMutationBindingV3Selector
    ) -> AccountRbacAuthorityMutationBindingV3 | None:
        """Verify exact history, final-head equality, and current authority state."""

        checked = _selector(selector)
        exact = GetExactAccountRbacAuthorityMutationBindingV3(self._repository).execute(checked)
        if exact is None:
            return None
        if not (
            exact.new_authority_state == "current"
            and exact.recorded_at <= checked.as_of < exact.valid_until
        ):
            return None
        raw_head = self._repository.get_current_head(
            source_id=checked.source_id,
            as_of=checked.as_of,
        )
        if raw_head is None:
            return None
        head = _record(raw_head).binding
        if not head.is_knowable_at(checked.as_of):
            raise AccountActorAuthorityRawSourceV3Corruption(
                "repository returned a future RBAC mutation head"
            )
        if _binding_identity(head)[1] != checked.source_id:
            raise AccountActorAuthorityRawSourceV3Corruption(
                "RBAC mutation head source substitution"
            )
        if head != exact:
            if _binding_identity(head)[:3] == _binding_identity(exact)[:3]:
                raise AccountActorAuthorityRawSourceV3Corruption(
                    "RBAC mutation head substituted an exact logical version"
                )
            return None
        return exact


def _selector(value: object) -> AccountRbacAuthorityMutationBindingV3Selector:
    """Validate an exact selector and translate malformed values to Corruption."""

    if type(value) is not AccountRbacAuthorityMutationBindingV3Selector:
        raise AccountActorAuthorityRawSourceV3Corruption("RBAC binding selector substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "RBAC binding selector is corrupt"
        ) from error
    return value


def _record(value: object) -> PersistedAccountRbacAuthorityMutationBindingV3:
    """Validate an exact persisted wrapper and translate malformed values."""

    if type(value) is not PersistedAccountRbacAuthorityMutationBindingV3:
        raise AccountActorAuthorityRawSourceV3Corruption("RBAC binding record substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountActorAuthorityRawSourceV3Corruption(
            "RBAC binding record is corrupt"
        ) from error
    return value


def _binding_identity(
    binding: AccountRbacAuthorityMutationBindingV3,
) -> tuple[str, str, str, str]:
    """Project mutation/source/hash identity without a caller PIT clock."""

    return (
        binding.mutation_id,
        binding.epoch.source_id,
        binding.source_version,
        binding.content_hash,
    )


# Descriptive aliases keep the dormant contract discoverable without adding
# alternate orchestration paths or wiring a production entry point.
AccountRbacAuthorityMutationBindingV3Writer = RecordAccountRbacAuthorityMutationBindingV3
IssueAccountRbacAuthorityMutationBindingV3 = RecordAccountRbacAuthorityMutationBindingV3
IssueAccountRbacAuthorityMutationBindingV3Command = AccountRbacAuthorityMutationBindingV3Command
AccountRbacAuthorityMutationBindingIdentityV3 = AccountRbacAuthorityMutationBindingV3Identity


__all__ = [
    "AccountRbacAuthorityMutationBindingIdentityV3",
    "AccountRbacAuthorityMutationBindingV3Command",
    "AccountRbacAuthorityMutationBindingV3Identity",
    "AccountRbacAuthorityMutationBindingV3Repository",
    "AccountRbacAuthorityMutationBindingV3Selector",
    "AccountRbacAuthorityMutationBindingV3UnitOfWork",
    "AccountRbacAuthorityMutationBindingV3Writer",
    "GetCurrentAccountRbacAuthorityMutationBindingV3",
    "GetExactAccountRbacAuthorityMutationBindingV3",
    "IssueAccountRbacAuthorityMutationBindingV3",
    "IssueAccountRbacAuthorityMutationBindingV3Command",
    "PersistedAccountRbacAuthorityMutationBindingV3",
    "RecordAccountRbacAuthorityMutationBindingV3",
]
