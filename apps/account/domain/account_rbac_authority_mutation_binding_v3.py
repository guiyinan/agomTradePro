"""Pure Account RBAC mutation authority, epoch, and binding evidence v3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    canonical_utc_z,
    domain_hash,
    validate_account_authority_raw_source_fixed_header_v3,
)
from apps.account.domain.account_rbac_authority_source_v3 import (
    ACCOUNT_RBAC_AUTHORITY_ROLES,
)

EPOCH_ARTIFACT_TYPE = "account_rbac_authority_source_epoch_v3"
EPOCH_SCHEMA = "account.rbac_authority_source_epoch.v3"
BINDING_ARTIFACT_TYPE = "account_rbac_authority_mutation_binding_v3"
BINDING_SCHEMA = "account.rbac_authority_mutation_binding.v3"
MUTATION_KINDS = frozenset({"bootstrap", "role_change", "revoke", "reactivate"})
AUTHORITY_STATES = frozenset({"current", "revoked"})


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


def _digest(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _optional_digest(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _digest(value, name)


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be an exact timezone-aware datetime")
    return value


def _role(value: object, name: str) -> str:
    if type(value) is not str or value not in ACCOUNT_RBAC_AUTHORITY_ROLES:
        raise ValueError(f"{name} must be an exact canonical Account role")
    return value


def _optional_role(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _role(value, name)


def _seal(target: object, name: str, domain: str, payload: dict[str, object]) -> None:
    expected = domain_hash(domain, payload)
    observed = getattr(target, name)
    if observed == "":
        object.__setattr__(target, name, expected)
    elif _digest(observed, name) != expected:
        raise ValueError(f"{name} is invalid")


@dataclass(frozen=True, slots=True)
class AccountRbacAuthorityProfileStateRefV3:
    """Reference one exact observed Profile state used as the mutation subject."""

    profile_id: str
    profile_version: str
    profile_content_hash: str
    rbac_role: str
    user_id: int
    subject_actor_id: str
    observed_at: datetime
    identity_hash: str = ""
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Validate the exact Profile identity, role, observation, and seals."""

        _token(self.profile_id, "profile_id")
        _token(self.profile_version, "profile_version")
        _digest(self.profile_content_hash, "profile_content_hash")
        _role(self.rbac_role, "rbac_role")
        _positive(self.user_id, "user_id")
        _token(self.subject_actor_id, "subject_actor_id")
        _aware(self.observed_at, "observed_at")
        _seal(
            self,
            "identity_hash",
            "account-rbac-mutation-v3/profile-identity",
            self._identity_payload(),
        )
        _seal(
            self,
            "content_hash",
            "account-rbac-mutation-v3/profile-content",
            self._content_payload(),
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "subject_actor_id": self.subject_actor_id,
            "user_id": self.user_id,
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "observed_at": canonical_utc_z(self.observed_at),
            "profile_content_hash": self.profile_content_hash,
            "rbac_role": self.rbac_role,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical Profile-state reference."""

        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class AccountRbacAuthorityHumanOperatorRefV3:
    """Reference one exact distinct authenticated human administrator authority."""

    principal_id: str
    user_id: int
    actor_id: str
    is_authenticated: bool
    is_active: bool
    is_staff: bool
    is_superuser: bool
    rbac_role: str
    authentication_source_id: str
    authentication_source_version: str
    authentication_source_content_hash: str
    user_source_id: str
    user_source_version: str
    user_source_content_hash: str
    rbac_source_id: str
    rbac_source_version: str
    rbac_source_content_hash: str
    observed_at: datetime
    valid_until: datetime
    identity_hash: str = ""
    authority_hash: str = ""

    def __post_init__(self) -> None:
        """Validate exact administrator facts, source triplet, clock, and seals."""

        for name in (
            "principal_id",
            "actor_id",
            "authentication_source_id",
            "authentication_source_version",
            "user_source_id",
            "user_source_version",
            "rbac_source_id",
            "rbac_source_version",
        ):
            _token(getattr(self, name), name)
        _positive(self.user_id, "user_id")
        for name in ("is_authenticated", "is_active", "is_staff", "is_superuser"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")
        if (
            not self.is_authenticated
            or not self.is_active
            or not self.is_staff
            or self.rbac_role != "admin"
        ):
            raise ValueError("human mutation operator must be an exact active staff admin")
        for name in (
            "authentication_source_content_hash",
            "user_source_content_hash",
            "rbac_source_content_hash",
        ):
            _digest(getattr(self, name), name)
        if not _aware(self.observed_at, "observed_at") < _aware(self.valid_until, "valid_until"):
            raise ValueError("operator authority clock is invalid")
        _seal(
            self,
            "identity_hash",
            "account-rbac-mutation-v3/operator-identity",
            self._identity_payload(),
        )
        _seal(
            self,
            "authority_hash",
            "account-rbac-mutation-v3/operator-authority",
            self._authority_payload(),
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "actor_id": self.actor_id,
            "principal_id": self.principal_id,
            "user_id": self.user_id,
        }

    def _authority_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "authentication_source_content_hash": self.authentication_source_content_hash,
            "authentication_source_id": self.authentication_source_id,
            "authentication_source_version": self.authentication_source_version,
            "is_active": self.is_active,
            "is_authenticated": self.is_authenticated,
            "is_staff": self.is_staff,
            "is_superuser": self.is_superuser,
            "observed_at": canonical_utc_z(self.observed_at),
            "rbac_role": self.rbac_role,
            "rbac_source_content_hash": self.rbac_source_content_hash,
            "rbac_source_id": self.rbac_source_id,
            "rbac_source_version": self.rbac_source_version,
            "user_source_content_hash": self.user_source_content_hash,
            "user_source_id": self.user_source_id,
            "user_source_version": self.user_source_version,
            "valid_until": canonical_utc_z(self.valid_until),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical human-operator reference."""

        return {
            **self._authority_payload(),
            "identity_hash": self.identity_hash,
            "authority_hash": self.authority_hash,
        }


@dataclass(frozen=True, slots=True)
class AccountRbacAuthorityMutationIssuerV3:
    """Identify the fixed service that records a human-authorized mutation."""

    service_id: str
    role: str = "account_rbac_authority_mutation_issuer"
    kind: str = "service"
    is_automated: bool = True
    identity_hash: str = ""

    def __post_init__(self) -> None:
        """Validate fixed non-human service semantics and identity seal."""

        _token(self.service_id, "service_id")
        if (type(self.role), type(self.kind), type(self.is_automated)) != (str, str, bool) or (
            self.role,
            self.kind,
            self.is_automated,
        ) != ("account_rbac_authority_mutation_issuer", "service", True):
            raise ValueError("RBAC mutation issuer semantics are fixed")
        _seal(
            self,
            "identity_hash",
            "account-rbac-mutation-v3/issuer-identity",
            self._identity_payload(),
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "is_automated": self.is_automated,
            "kind": self.kind,
            "role": self.role,
            "service_id": self.service_id,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical service-issuer payload."""

        return {**self._identity_payload(), "identity_hash": self.identity_hash}


@dataclass(frozen=True, slots=True)
class AccountRbacAuthoritySourceEpochV3:
    """Identify one initial or explicitly reactivated raw authority source epoch."""

    epoch_id: str
    target_user_id: int
    subject_actor_id: str
    source_id: str
    epoch_sequence: int
    opened_at: datetime
    previous_epoch_content_hash: str | None = None
    terminal_authority_source_content_hash: str | None = None
    terminal_mutation_binding_content_hash: str | None = None
    root_claim_hash: str = ""
    identity_hash: str = ""
    content_hash: str = ""

    def __post_init__(self) -> None:
        """Validate initial/reactivation XOR, exact continuity references, and seals."""

        _token(self.epoch_id, "epoch_id")
        _positive(self.target_user_id, "target_user_id")
        _token(self.subject_actor_id, "subject_actor_id")
        _token(self.source_id, "source_id")
        _positive(self.epoch_sequence, "epoch_sequence")
        _aware(self.opened_at, "opened_at")
        links = (
            self.previous_epoch_content_hash,
            self.terminal_authority_source_content_hash,
            self.terminal_mutation_binding_content_hash,
        )
        if self.epoch_sequence == 1:
            if any(value is not None for value in links):
                raise ValueError("initial epoch cannot carry reactivation links")
        elif any(value is None for value in links):
            raise ValueError("reactivation epoch requires all terminal continuity links")
        for name, value in zip(
            (
                "previous_epoch_content_hash",
                "terminal_authority_source_content_hash",
                "terminal_mutation_binding_content_hash",
            ),
            links,
            strict=True,
        ):
            _optional_digest(value, name)
        _seal(self, "root_claim_hash", "account-rbac-mutation-v3/epoch-root", self._root_payload())
        _seal(
            self,
            "identity_hash",
            "account-rbac-mutation-v3/epoch-identity",
            self._identity_payload(),
        )
        _seal(
            self, "content_hash", "account-rbac-mutation-v3/epoch-content", self._content_payload()
        )

    @property
    def epoch_kind(self) -> str:
        """Return the closed initial/reactivation epoch kind."""

        return "initial" if self.epoch_sequence == 1 else "reactivation"

    def _root_payload(self) -> dict[str, object]:
        return {
            "epoch_id": self.epoch_id,
            "source_id": self.source_id,
            "subject_actor_id": self.subject_actor_id,
            "target_user_id": self.target_user_id,
        }

    def _identity_payload(self) -> dict[str, object]:
        return {**self._root_payload(), "epoch_sequence": self.epoch_sequence}

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "opened_at": canonical_utc_z(self.opened_at),
            "previous_epoch_content_hash": self.previous_epoch_content_hash,
            "root_claim_hash": self.root_claim_hash,
            "terminal_authority_source_content_hash": self.terminal_authority_source_content_hash,
            "terminal_mutation_binding_content_hash": self.terminal_mutation_binding_content_hash,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical source-epoch payload."""

        return {
            **self._content_payload(),
            "epoch_kind": self.epoch_kind,
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class AccountRbacAuthorityMutationBindingV3:
    """Bind one human-authorized Profile transition to one immutable raw source."""

    mutation_id: str
    mutation_kind: str
    epoch: AccountRbacAuthoritySourceEpochV3
    old_subject: AccountRbacAuthorityProfileStateRefV3 | None
    subject: AccountRbacAuthorityProfileStateRefV3
    operator: AccountRbacAuthorityHumanOperatorRefV3
    issuer: AccountRbacAuthorityMutationIssuerV3
    source_version: str
    old_authority_state: str | None
    new_authority_state: str
    old_rbac_role: str | None
    new_rbac_role: str
    authority_source_identity_hash: str
    authority_source_content_hash: str
    authority_source_record_seal: str
    observed_at: datetime
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime
    binding_chain: AccountAuthorityRawSourceChainV3
    authority_source_chain: AccountAuthorityRawSourceChainV3
    identity_hash: str = ""
    transition_seal: str = ""
    old_subject_seal: str = ""
    subject_seal: str = ""
    operator_seal: str = ""
    issuer_seal: str = ""
    source_binding_seal: str = ""
    clock_seal: str = ""
    binding_chain_seal: str = ""
    authority_source_chain_seal: str = ""
    fixed_authority_seal: str = ""
    record_seal: str = ""
    content_hash: str = ""
    owner: str = "account"
    artifact_type: str = BINDING_ARTIFACT_TYPE
    schema: str = BINDING_SCHEMA
    permission: str = "attestation_only"
    status: str = "inactive"
    must_not_execute: bool = True
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        """Validate authority separation, state transition, dual chains, clocks, and seals."""

        validate_account_authority_raw_source_fixed_header_v3(
            owner=self.owner,
            artifact_type=self.artifact_type,
            schema=self.schema,
            permission=self.permission,
            status=self.status,
            must_not_execute=self.must_not_execute,
            execution_allowed=self.execution_allowed,
            expected_artifact_type=BINDING_ARTIFACT_TYPE,
            expected_schema=BINDING_SCHEMA,
        )
        _token(self.mutation_id, "mutation_id")
        if type(self.mutation_kind) is not str or self.mutation_kind not in MUTATION_KINDS:
            raise ValueError("mutation_kind is invalid")
        for value, expected, name in (
            (self.epoch, AccountRbacAuthoritySourceEpochV3, "epoch"),
            (self.subject, AccountRbacAuthorityProfileStateRefV3, "subject"),
            (self.operator, AccountRbacAuthorityHumanOperatorRefV3, "operator"),
            (self.issuer, AccountRbacAuthorityMutationIssuerV3, "issuer"),
            (self.binding_chain, AccountAuthorityRawSourceChainV3, "binding_chain"),
            (
                self.authority_source_chain,
                AccountAuthorityRawSourceChainV3,
                "authority_source_chain",
            ),
        ):
            if type(value) is not expected:
                raise TypeError(f"{name} has a substituted type")
            value.__post_init__()
        if self.old_subject is not None:
            if type(self.old_subject) is not AccountRbacAuthorityProfileStateRefV3:
                raise TypeError("old_subject has a substituted type")
            self.old_subject.__post_init__()
        if (self.subject.user_id, self.subject.subject_actor_id) != (
            self.epoch.target_user_id,
            self.epoch.subject_actor_id,
        ):
            raise ValueError("subject differs from source epoch")
        if (
            self.operator.user_id == self.subject.user_id
            or self.operator.actor_id == self.subject.subject_actor_id
            or (
                self.old_subject is not None
                and (
                    self.operator.user_id == self.old_subject.user_id
                    or self.operator.actor_id == self.old_subject.subject_actor_id
                )
            )
        ):
            raise ValueError("human operator must be distinct from mutation subject")
        if self.old_subject is not None and (
            self.old_subject.user_id != self.subject.user_id
            or self.old_subject.subject_actor_id != self.subject.subject_actor_id
            or self.old_subject.profile_id != self.subject.profile_id
            or self.old_subject.profile_version == self.subject.profile_version
            or self.old_subject.profile_content_hash == self.subject.profile_content_hash
        ):
            raise ValueError("old and new Profile references are not an exact CAS transition")
        _token(self.source_version, "source_version")
        self._validate_transition()
        for name in (
            "authority_source_identity_hash",
            "authority_source_content_hash",
            "authority_source_record_seal",
        ):
            _digest(getattr(self, name), name)
        self._validate_clock()
        self._validate_roots()
        self._apply_seals()

    def _validate_transition(self) -> None:
        old_state = self.old_authority_state
        if old_state is not None and (
            type(old_state) is not str or old_state not in AUTHORITY_STATES
        ):
            raise ValueError("old_authority_state is invalid")
        if (
            type(self.new_authority_state) is not str
            or self.new_authority_state not in AUTHORITY_STATES
        ):
            raise ValueError("new_authority_state is invalid")
        old_role = _optional_role(self.old_rbac_role, "old_rbac_role")
        new_role = _role(self.new_rbac_role, "new_rbac_role")
        if self.subject.rbac_role != new_role:
            raise ValueError("subject Profile role differs from new role")
        expected = {
            "bootstrap": (None, "current"),
            "role_change": ("current", "current"),
            "revoke": ("current", "revoked"),
            "reactivate": ("revoked", "current"),
        }[self.mutation_kind]
        if (old_state, self.new_authority_state) != expected:
            raise ValueError("mutation state transition is invalid")
        if self.mutation_kind == "bootstrap":
            if (
                old_role is not None
                or self.old_subject is not None
                or self.epoch.epoch_kind != "initial"
            ):
                raise ValueError("bootstrap requires no old role and the initial epoch")
        elif old_role is None or self.old_subject is None:
            raise ValueError("non-bootstrap mutation requires an old role")
        elif self.old_subject.rbac_role != old_role:
            raise ValueError("old Profile role differs from old mutation role")
        if self.mutation_kind == "role_change" and old_role == new_role:
            raise ValueError("role_change must change the canonical role")
        if self.mutation_kind == "reactivate" and self.epoch.epoch_kind != "reactivation":
            raise ValueError("reactivate requires a new reactivation epoch")
        if (
            self.mutation_kind != "reactivate"
            and self.mutation_kind != "bootstrap"
            and self.epoch.opened_at > self.observed_at
        ):
            raise ValueError("mutation observation predates its epoch")

    def _validate_clock(self) -> None:
        observed = _aware(self.observed_at, "observed_at")
        issued = _aware(self.issued_at, "issued_at")
        recorded = _aware(self.recorded_at, "recorded_at")
        valid = _aware(self.valid_until, "valid_until")
        profile_observed = _aware(self.subject.observed_at, "subject.observed_at")
        if self.old_subject is not None:
            old_profile_observed = _aware(self.old_subject.observed_at, "old_subject.observed_at")
            if old_profile_observed > profile_observed:
                raise ValueError("new Profile observation precedes old Profile observation")
        if not (
            self.epoch.opened_at <= profile_observed <= observed
            and self.operator.observed_at <= observed <= issued <= recorded < valid
            and valid <= self.operator.valid_until
        ):
            raise ValueError("mutation binding clock continuity is invalid")

    def _validate_roots(self) -> None:
        binding_root = root_claim_hash_for_account_rbac_authority_mutation_binding_v3(
            self.epoch.target_user_id, self.epoch.subject_actor_id
        )
        if self.mutation_kind == "bootstrap":
            if self.binding_chain.root_claim_hash != binding_root:
                raise ValueError("bootstrap binding root claim is invalid")
        elif self.binding_chain.root_claim_hash is not None:
            raise ValueError("non-bootstrap binding cannot restart the binding chain")
        if self.mutation_kind in {"bootstrap", "reactivate"}:
            if self.authority_source_chain.root_claim_hash is None:
                raise ValueError("new raw authority-source chain requires a root claim")
        elif self.authority_source_chain.root_claim_hash is not None:
            raise ValueError("same-epoch source successor cannot restart its chain")

    def _apply_seals(self) -> None:
        old_subject_payload: dict[str, object] = (
            {"old_subject": None} if self.old_subject is None else self.old_subject.to_payload()
        )
        payloads = {
            "identity_hash": self._identity_payload(),
            "transition_seal": self._transition_payload(),
            "old_subject_seal": old_subject_payload,
            "subject_seal": self.subject.to_payload(),
            "operator_seal": self.operator.to_payload(),
            "issuer_seal": self.issuer.to_payload(),
            "source_binding_seal": self._source_payload(),
            "clock_seal": self._clock_payload(),
            "binding_chain_seal": self._binding_chain_payload(),
            "authority_source_chain_seal": self._source_chain_payload(),
            "fixed_authority_seal": self._fixed_payload(),
        }
        for name, payload in payloads.items():
            _seal(self, name, f"account-rbac-mutation-v3/{name}", payload)
        _seal(self, "record_seal", "account-rbac-mutation-v3/record", self._record_payload())
        _seal(
            self,
            "content_hash",
            "account-rbac-mutation-v3/content",
            {**self._record_payload(), "record_seal": self.record_seal},
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "artifact_type": self.artifact_type,
            "epoch_identity_hash": self.epoch.identity_hash,
            "mutation_id": self.mutation_id,
            "owner": self.owner,
            "schema": self.schema,
            "source_id": self.epoch.source_id,
            "source_version": self.source_version,
        }

    def _transition_payload(self) -> dict[str, object]:
        return {
            "mutation_kind": self.mutation_kind,
            "new_authority_state": self.new_authority_state,
            "new_rbac_role": self.new_rbac_role,
            "old_authority_state": self.old_authority_state,
            "old_rbac_role": self.old_rbac_role,
        }

    def _source_payload(self) -> dict[str, object]:
        return {
            "authority_source_content_hash": self.authority_source_content_hash,
            "authority_source_identity_hash": self.authority_source_identity_hash,
            "authority_source_record_seal": self.authority_source_record_seal,
            "source_id": self.epoch.source_id,
            "source_version": self.source_version,
        }

    def _clock_payload(self) -> dict[str, object]:
        return {
            "issued_at": canonical_utc_z(self.issued_at),
            "observed_at": canonical_utc_z(self.observed_at),
            "recorded_at": canonical_utc_z(self.recorded_at),
            "valid_until": canonical_utc_z(self.valid_until),
        }

    def _binding_chain_payload(self) -> dict[str, object]:
        return {
            "root_claim_hash": self.binding_chain.root_claim_hash,
            "supersedes_content_hash": self.binding_chain.supersedes_content_hash,
        }

    def _source_chain_payload(self) -> dict[str, object]:
        return {
            "root_claim_hash": self.authority_source_chain.root_claim_hash,
            "supersedes_content_hash": self.authority_source_chain.supersedes_content_hash,
        }

    def _fixed_payload(self) -> dict[str, object]:
        return {
            "artifact_type": self.artifact_type,
            "execution_allowed": self.execution_allowed,
            "must_not_execute": self.must_not_execute,
            "owner": self.owner,
            "permission": self.permission,
            "schema": self.schema,
            "status": self.status,
        }

    def _record_payload(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in (
                "identity_hash",
                "transition_seal",
                "old_subject_seal",
                "subject_seal",
                "operator_seal",
                "issuer_seal",
                "source_binding_seal",
                "clock_seal",
                "binding_chain_seal",
                "authority_source_chain_seal",
                "fixed_authority_seal",
            )
        }

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return exact PIT knowability without selecting an older fallback."""

        return self.recorded_at <= _aware(as_of, "as_of")

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical nested mutation binding payload."""

        return {
            "mutation_id": self.mutation_id,
            "mutation_kind": self.mutation_kind,
            "epoch": self.epoch.to_payload(),
            "old_subject": None if self.old_subject is None else self.old_subject.to_payload(),
            "subject": self.subject.to_payload(),
            "operator": self.operator.to_payload(),
            "issuer": self.issuer.to_payload(),
            "source_version": self.source_version,
            "old_authority_state": self.old_authority_state,
            "new_authority_state": self.new_authority_state,
            "old_rbac_role": self.old_rbac_role,
            "new_rbac_role": self.new_rbac_role,
            **self._source_payload(),
            **self._clock_payload(),
            "binding_chain": self._binding_chain_payload(),
            "authority_source_chain": self._source_chain_payload(),
            **self._record_payload(),
            "record_seal": self.record_seal,
            "content_hash": self.content_hash,
            **self._fixed_payload(),
        }


def root_claim_hash_for_account_rbac_authority_mutation_binding_v3(
    user_id: int, subject_actor_id: str
) -> str:
    """Return the candidate-independent global binding-chain root for one subject."""

    _positive(user_id, "user_id")
    _token(subject_actor_id, "subject_actor_id")
    value = domain_hash(
        "account-rbac-mutation-v3/binding-root",
        {"subject_actor_id": subject_actor_id, "user_id": user_id},
    )
    if not isinstance(value, str):
        raise TypeError("binding root hash must be text")
    return value


def validate_account_rbac_authority_source_epoch_v3_successor(
    previous: AccountRbacAuthoritySourceEpochV3,
    successor: AccountRbacAuthoritySourceEpochV3,
    *,
    terminal_authority_source_content_hash: str,
    terminal_mutation_binding_content_hash: str,
) -> None:
    """Validate one explicit reactivation epoch against exact terminal evidence."""

    if (
        type(previous) is not AccountRbacAuthoritySourceEpochV3
        or type(successor) is not AccountRbacAuthoritySourceEpochV3
    ):
        raise TypeError("previous and successor must be exact RBAC source epochs v3")
    previous.__post_init__()
    successor.__post_init__()
    _digest(terminal_authority_source_content_hash, "terminal_authority_source_content_hash")
    _digest(terminal_mutation_binding_content_hash, "terminal_mutation_binding_content_hash")
    if (successor.target_user_id, successor.subject_actor_id) != (
        previous.target_user_id,
        previous.subject_actor_id,
    ):
        raise ValueError("reactivation epoch changed its subject")
    if successor.epoch_sequence != previous.epoch_sequence + 1:
        raise ValueError("reactivation epoch sequence must advance exactly once")
    if successor.epoch_id == previous.epoch_id or successor.source_id == previous.source_id:
        raise ValueError("reactivation epoch identity must advance")
    if successor.opened_at <= previous.opened_at:
        raise ValueError("reactivation epoch clock must advance")
    if (
        successor.previous_epoch_content_hash,
        successor.terminal_authority_source_content_hash,
        successor.terminal_mutation_binding_content_hash,
    ) != (
        previous.content_hash,
        terminal_authority_source_content_hash,
        terminal_mutation_binding_content_hash,
    ):
        raise ValueError("reactivation epoch terminal continuity differs")


def validate_account_rbac_authority_mutation_binding_v3_successor(
    previous: AccountRbacAuthorityMutationBindingV3,
    successor: AccountRbacAuthorityMutationBindingV3,
) -> None:
    """Validate binding continuity and the distinct raw-source chain continuity."""

    if (
        type(previous) is not AccountRbacAuthorityMutationBindingV3
        or type(successor) is not AccountRbacAuthorityMutationBindingV3
    ):
        raise TypeError("previous and successor must be exact RBAC mutation bindings v3")
    previous.__post_init__()
    successor.__post_init__()
    if successor.binding_chain.supersedes_content_hash != previous.content_hash:
        raise ValueError("binding successor does not bind exact previous binding")
    if successor.old_subject != previous.subject:
        raise ValueError("successor does not bind exact previous Profile state")
    if (
        successor.old_authority_state != previous.new_authority_state
        or successor.old_rbac_role != previous.new_rbac_role
    ):
        raise ValueError("successor old state does not continue predecessor new state")
    if not previous.recorded_at < successor.observed_at:
        raise ValueError("successor observation must follow predecessor recording")
    if successor.mutation_kind == "reactivate":
        validate_account_rbac_authority_source_epoch_v3_successor(
            previous.epoch,
            successor.epoch,
            terminal_authority_source_content_hash=previous.authority_source_content_hash,
            terminal_mutation_binding_content_hash=previous.content_hash,
        )
        if successor.authority_source_chain.root_claim_hash is None:
            raise ValueError("reactivation must start the new raw-source chain")
    else:
        if successor.epoch != previous.epoch:
            raise ValueError("non-reactivation successor changed source epoch")
        if (
            successor.authority_source_chain.supersedes_content_hash
            != previous.authority_source_content_hash
        ):
            raise ValueError("raw-source successor does not bind exact previous source content")


def select_exact_account_rbac_authority_mutation_binding_v3(
    history: tuple[AccountRbacAuthorityMutationBindingV3, ...],
    *,
    mutation_id: str,
    source_version: str,
    expected_content_hash: str,
    as_of: datetime,
) -> AccountRbacAuthorityMutationBindingV3 | None:
    """Select only one exact PIT binding and never fall back to another version."""

    if type(history) is not tuple:
        raise TypeError("history must be an exact tuple")
    _token(mutation_id, "mutation_id")
    _token(source_version, "source_version")
    _digest(expected_content_hash, "expected_content_hash")
    cutoff = _aware(as_of, "as_of")
    matches: list[AccountRbacAuthorityMutationBindingV3] = []
    for value in history:
        if type(value) is not AccountRbacAuthorityMutationBindingV3:
            raise TypeError("history contains a substituted binding")
        value.__post_init__()
        if (value.mutation_id, value.source_version, value.content_hash) == (
            mutation_id,
            source_version,
            expected_content_hash,
        ) and value.recorded_at <= cutoff:
            matches.append(value)
    if len(matches) > 1:
        raise ValueError("exact mutation binding is ambiguous")
    return matches[0] if matches else None


__all__ = [
    "AccountRbacAuthorityHumanOperatorRefV3",
    "AccountRbacAuthorityMutationBindingV3",
    "AccountRbacAuthorityMutationIssuerV3",
    "AccountRbacAuthorityProfileStateRefV3",
    "AccountRbacAuthoritySourceEpochV3",
    "root_claim_hash_for_account_rbac_authority_mutation_binding_v3",
    "select_exact_account_rbac_authority_mutation_binding_v3",
    "validate_account_rbac_authority_mutation_binding_v3_successor",
    "validate_account_rbac_authority_source_epoch_v3_successor",
]
