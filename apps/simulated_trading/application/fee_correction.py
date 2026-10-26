"""Application contracts for source-qualified simulated fee corrections.

No production source reader or actor-authority provider is registered in this
candidate. The explicit blocked adapters prevent a bare reference, owner
request, or current fee schedule from being treated as proof.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from apps.simulated_trading.domain.entities import SimulatedTrade
from apps.simulated_trading.domain.fee_correction import (
    CorrectableFeeComponents,
    FeeCorrectionCashEvent,
)
from core.exceptions import BusinessLogicError


def _valid_digest(value: object) -> bool:
    """Return whether a value is a lowercase SHA-256 digest."""

    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True, slots=True)
class FeeCorrectionRequest:
    """Untrusted local correction locator and stale-state expectation."""

    account_id: int
    trade_id: int
    idempotency_key: str
    expected_revision: int
    source_locator: str

    def __post_init__(self) -> None:
        """Reject malformed identifiers before invoking either verifier port."""

        if any(type(value) is not int or value <= 0 for value in (self.account_id, self.trade_id)):
            raise FeeCorrectionBlockedError(
                "fee correction identity is invalid", code="FEE_CORRECTION_INPUT_INVALID"
            )
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            raise FeeCorrectionBlockedError(
                "fee correction revision is invalid", code="FEE_CORRECTION_REVISION_CONFLICT"
            )
        if (
            type(self.idempotency_key) is not str
            or not self.idempotency_key
            or self.idempotency_key.strip() != self.idempotency_key
            or len(self.idempotency_key) > 128
            or any(character.isspace() for character in self.idempotency_key)
        ):
            raise FeeCorrectionBlockedError(
                "fee correction idempotency key is invalid", code="FEE_CORRECTION_INPUT_INVALID"
            )
        if (
            type(self.source_locator) is not str
            or not self.source_locator
            or self.source_locator.strip() != self.source_locator
            or len(self.source_locator) > 512
            or "://" in self.source_locator
            or self.source_locator.startswith(("/", "\\"))
            or "\\" in self.source_locator
        ):
            raise FeeCorrectionBlockedError(
                "fee correction source locator is invalid", code="FEE_CORRECTION_INPUT_INVALID"
            )


@dataclass(frozen=True, slots=True)
class VerifiedFeeCorrectionEvidence:
    """Verifier-produced evidence bound to one exact trade and predecessor."""

    account_id: int
    trade_id: int
    asset_code: str
    expected_revision: int
    expected_predecessor_id: int | None
    trade_snapshot_hash: str
    previous_fee_components: CorrectableFeeComponents
    revised_fee_components: CorrectableFeeComponents
    source_namespace: str
    source_record_id: str
    evidence_sha256: str
    source_payload_sha256: str
    verifier_identity: str
    source_observed_at: datetime
    verified_at: datetime

    def __post_init__(self) -> None:
        """Validate the typed source seal; this value must come from a verifier port."""

        if (
            type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.trade_id) is not int
            or self.trade_id <= 0
            or type(self.expected_revision) is not int
            or self.expected_revision < 0
            or (
                self.expected_predecessor_id is not None
                and (
                    type(self.expected_predecessor_id) is not int
                    or self.expected_predecessor_id <= 0
                )
            )
        ):
            raise FeeCorrectionBlockedError(
                "verified source identity is invalid", code="FEE_CORRECTION_SOURCE_INVALID"
            )
        if (
            type(self.asset_code) is not str
            or not self.asset_code
            or self.asset_code.strip() != self.asset_code
            or any(character.isspace() for character in self.asset_code)
            or type(self.source_namespace) is not str
            or not self.source_namespace
            or self.source_namespace.strip() != self.source_namespace
            or type(self.source_record_id) is not str
            or not self.source_record_id
            or self.source_record_id.strip() != self.source_record_id
            or type(self.verifier_identity) is not str
            or not self.verifier_identity
            or self.verifier_identity.strip() != self.verifier_identity
        ):
            raise FeeCorrectionBlockedError(
                "verified source locator is invalid", code="FEE_CORRECTION_SOURCE_INVALID"
            )
        if not all(
            _valid_digest(value)
            for value in (
                self.trade_snapshot_hash,
                self.evidence_sha256,
                self.source_payload_sha256,
            )
        ):
            raise FeeCorrectionBlockedError(
                "verified source digest is invalid", code="FEE_CORRECTION_SOURCE_INVALID"
            )
        if (
            type(self.previous_fee_components) is not CorrectableFeeComponents
            or type(self.revised_fee_components) is not CorrectableFeeComponents
            or type(self.source_observed_at) is not datetime
            or type(self.verified_at) is not datetime
            or self.source_observed_at.tzinfo is None
            or self.source_observed_at.utcoffset() is None
            or self.verified_at.tzinfo is None
            or self.verified_at.utcoffset() is None
            or self.source_observed_at > self.verified_at
        ):
            raise FeeCorrectionBlockedError(
                "verified source chronology or amounts are invalid",
                code="FEE_CORRECTION_SOURCE_INVALID",
            )
        self.previous_fee_components.__post_init__()
        self.revised_fee_components.__post_init__()


@dataclass(frozen=True, slots=True)
class VerifiedFeeCorrectionAuthorization:
    """Authority verifier result bound to the exact simulated account and actor."""

    account_id: int
    actor_user_id: int
    authority_identity: str
    authority_record_id: str
    authority_sha256: str
    policy_version: int
    policy_sha256: str
    policy_enabled: bool
    policy_allows_operator_attested_upload: bool
    policy_ledger_currency: str
    policy_valid_from: datetime | None
    policy_valid_until: datetime | None
    policy_updated_by_id: int | None
    principal_enabled: bool
    authorization_scope: str

    def __post_init__(self) -> None:
        """Require typed account/user identity and a verifiable authority digest."""

        if (
            type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.actor_user_id) is not int
            or self.actor_user_id <= 0
            or type(self.authority_identity) is not str
            or not self.authority_identity
            or self.authority_identity.strip() != self.authority_identity
            or type(self.authority_record_id) is not str
            or not self.authority_record_id
            or self.authority_record_id.strip() != self.authority_record_id
            or not _valid_digest(self.authority_sha256)
            or type(self.policy_version) is not int
            or self.policy_version <= 0
            or not _valid_digest(self.policy_sha256)
            or self.authority_sha256 != self.policy_sha256
            or type(self.policy_enabled) is not bool
            or self.policy_enabled is not True
            or type(self.policy_allows_operator_attested_upload) is not bool
            or self.policy_allows_operator_attested_upload is not True
            or type(self.policy_ledger_currency) is not str
            or len(self.policy_ledger_currency) != 3
            or any(character < "A" or character > "Z" for character in self.policy_ledger_currency)
            or type(self.principal_enabled) is not bool
            or self.principal_enabled is not True
            or (
                self.policy_updated_by_id is not None
                and (type(self.policy_updated_by_id) is not int or self.policy_updated_by_id <= 0)
            )
            or self.authorization_scope != "simulated_fee_correction:operator_attested_upload"
            or type(self.policy_valid_from) not in (datetime, type(None))
            or type(self.policy_valid_until) not in (datetime, type(None))
        ):
            raise FeeCorrectionBlockedError(
                "fee correction authority is invalid", code="FEE_CORRECTION_AUTHORITY_INVALID"
            )
        for policy_clock in (self.policy_valid_from, self.policy_valid_until):
            if policy_clock is not None and (
                policy_clock.tzinfo is None or policy_clock.utcoffset() is None
            ):
                raise FeeCorrectionBlockedError(
                    "fee correction policy validity must be timezone-aware",
                    code="FEE_CORRECTION_AUTHORITY_INVALID",
                )
        if (
            self.policy_valid_from is not None
            and self.policy_valid_until is not None
            and self.policy_valid_from >= self.policy_valid_until
        ):
            raise FeeCorrectionBlockedError(
                "fee correction policy validity window is empty",
                code="FEE_CORRECTION_AUTHORITY_INVALID",
            )


@dataclass(frozen=True, slots=True)
class FeeCorrectionReceipt:
    """One committed or idempotently replayed correction event."""

    event_id: int
    account_id: int
    trade_id: int
    revision: int
    payload_hash: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class FeeCorrectionCashPosting:
    """Cash event identity with its account-local immutable correction prefix."""

    event: FeeCorrectionCashEvent
    account_revision: int
    account_prefix_sha256: str

    def __post_init__(self) -> None:
        """Require a domain cash event and a positive account-local sequence."""

        if (
            type(self.event) is not FeeCorrectionCashEvent
            or type(self.account_revision) is not int
            or self.account_revision <= 0
            or not _valid_digest(self.account_prefix_sha256)
        ):
            raise FeeCorrectionBlockedError(
                "费用更正现金事件缺少账户内序号",
                code="FEE_CORRECTION_HISTORY_INVALID",
            )

    @property
    def event_id(self) -> int:
        """Return the opaque persistent event primary key."""

        return self.event.event_id

    @property
    def posting_date(self) -> date:
        """Return the financial posting date."""

        return self.event.posting_date

    @property
    def posted_at(self) -> datetime:
        """Return the aware posting time."""

        return self.event.posted_at

    @property
    def cash_delta(self) -> Decimal:
        """Return the exact signed cash correction."""

        return self.event.cash_delta


@dataclass(frozen=True, slots=True)
class FeeCorrectionAccountHistoryProjection:
    """As-of effective Trade rows plus separately posted correction cash events."""

    account_id: int
    as_of: datetime
    trades: tuple[SimulatedTrade, ...]
    cash_events: tuple[FeeCorrectionCashPosting, ...]


class FeeCorrectionHistoryRepositoryProtocol(Protocol):
    """Read complete correction history before applying output date filters."""

    def get_account_history(
        self,
        *,
        account_id: int,
        as_of: datetime,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> FeeCorrectionAccountHistoryProjection:
        """Return effective immutable Trade views and posting-date cash deltas."""
        ...


class FeeCorrectionEvidenceVerifierProtocol(Protocol):
    """Read and qualify a persisted local evidence binding for one request."""

    def verify(self, request: FeeCorrectionRequest) -> VerifiedFeeCorrectionEvidence | None:
        """Return a source-bound proof without remote calls, or ``None`` when absent."""
        ...


class FeeCorrectionAuthorityProtocol(Protocol):
    """Verify that the authenticated actor may correct this account's fee evidence."""

    def authorize(
        self,
        *,
        account_id: int,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> VerifiedFeeCorrectionAuthorization | None:
        """Read local policy/authority for a request principal or return ``None``.

        Implementations used by the protected repository boundary must verify
        local persisted policy and credential state. They must not make a
        network request while the simulated-account row is locked.
        """
        ...


class AuthenticatedFeeCorrectionPrincipalProtocol(Protocol):
    """Authenticated request principal passed by the Interface, never the body."""

    @property
    def is_authenticated(self) -> bool:
        """Return whether the principal is authenticated at the request boundary."""
        ...

    @property
    def pk(self) -> int | None:
        """Return the persisted user primary key, when present."""
        ...


class FeeCorrectionClockProtocol(Protocol):
    """Provide one aware posting clock for a correction transaction."""

    def now(self) -> datetime:
        """Return an aware timestamp."""
        ...


class FeeCorrectionRepositoryProtocol(Protocol):
    """Persist one exact fee correction with its cash and position effects."""

    def apply_fee_correction(
        self,
        *,
        request: FeeCorrectionRequest,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
        evidence: VerifiedFeeCorrectionEvidence,
        authorization: VerifiedFeeCorrectionAuthorization,
        clock: FeeCorrectionClockProtocol,
    ) -> FeeCorrectionReceipt:
        """Atomically append a correction after locking and revalidating its scope."""
        ...


class FeeCorrectionBlockedError(BusinessLogicError):
    """Use-case block for unavailable evidence, authority, or stale correction state."""


class _BlockedFeeCorrectionEvidenceVerifier:
    """Fail-closed verifier used when no actual source integration is configured."""

    def verify(self, request: FeeCorrectionRequest) -> VerifiedFeeCorrectionEvidence | None:
        """Never treat an unqualified locator or operator-supplied amount as source evidence."""

        del request
        return None


class _BlockedFeeCorrectionAuthority:
    """Fail-closed authorization used when no actor authority integration exists."""

    def authorize(
        self,
        *,
        account_id: int,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> VerifiedFeeCorrectionAuthorization | None:
        """Never authorize a write from a numeric user ID alone."""

        del account_id, principal
        return None


class ApplySimulatedFeeCorrectionUseCase:
    """Validate source and actor proofs before delegating the single atomic write."""

    def __init__(
        self,
        *,
        repository: FeeCorrectionRepositoryProtocol,
        evidence_verifier: FeeCorrectionEvidenceVerifierProtocol | None = None,
        authority: FeeCorrectionAuthorityProtocol | None = None,
        clock: FeeCorrectionClockProtocol,
    ) -> None:
        self._repository = repository
        self._evidence_verifier = (
            evidence_verifier
            if evidence_verifier is not None
            else _BlockedFeeCorrectionEvidenceVerifier()
        )
        self._authority = authority if authority is not None else _BlockedFeeCorrectionAuthority()
        self._clock = clock

    def execute(
        self,
        request: FeeCorrectionRequest,
        *,
        principal: AuthenticatedFeeCorrectionPrincipalProtocol,
    ) -> FeeCorrectionReceipt:
        """Apply one evidence-backed correction or fail closed without persistence."""

        request.__post_init__()
        principal_user_id = _authenticated_principal_user_id(principal)
        if principal_user_id is None:
            raise FeeCorrectionBlockedError(
                "费用更正需要有效的已认证账户主体",
                code="FEE_CORRECTION_PRINCIPAL_INVALID",
            )
        evidence = self._evidence_verifier.verify(request)
        if type(evidence) is not VerifiedFeeCorrectionEvidence:
            raise FeeCorrectionBlockedError(
                "没有可验证的独立费用来源证据，未应用更正",
                code="FEE_CORRECTION_SOURCE_UNAVAILABLE",
            )
        evidence.__post_init__()
        if (
            evidence.account_id != request.account_id
            or evidence.trade_id != request.trade_id
            or evidence.expected_revision != request.expected_revision
        ):
            raise FeeCorrectionBlockedError(
                "来源证据与请求范围或预期版本不匹配",
                code="FEE_CORRECTION_SOURCE_SCOPE_MISMATCH",
            )
        authorization = self._authority.authorize(
            account_id=request.account_id,
            principal=principal,
        )
        if type(authorization) is not VerifiedFeeCorrectionAuthorization:
            raise FeeCorrectionBlockedError(
                "没有可验证的账户费用更正权限，未应用更正",
                code="FEE_CORRECTION_AUTHORITY_UNAVAILABLE",
            )
        authorization.__post_init__()
        if (
            authorization.account_id != request.account_id
            or authorization.actor_user_id != principal_user_id
        ):
            raise FeeCorrectionBlockedError(
                "费用更正授权与请求身份不匹配",
                code="FEE_CORRECTION_AUTHORITY_SCOPE_MISMATCH",
            )
        return self._repository.apply_fee_correction(
            request=request,
            principal=principal,
            evidence=evidence,
            authorization=authorization,
            clock=self._clock,
        )


def _authenticated_principal_user_id(principal: object) -> int | None:
    """Narrow an Interface-provided authenticated principal without using body IDs."""

    if principal is None:
        return None
    authenticated = getattr(principal, "is_authenticated", None)
    user_id = getattr(principal, "pk", None)
    if (
        type(authenticated) is not bool
        or authenticated is not True
        or type(user_id) is not int
        or user_id <= 0
    ):
        return None
    return user_id


__all__ = [
    "ApplySimulatedFeeCorrectionUseCase",
    "AuthenticatedFeeCorrectionPrincipalProtocol",
    "FeeCorrectionAccountHistoryProjection",
    "FeeCorrectionAuthorityProtocol",
    "FeeCorrectionBlockedError",
    "FeeCorrectionCashPosting",
    "FeeCorrectionClockProtocol",
    "FeeCorrectionEvidenceVerifierProtocol",
    "FeeCorrectionHistoryRepositoryProtocol",
    "FeeCorrectionReceipt",
    "FeeCorrectionRepositoryProtocol",
    "FeeCorrectionRequest",
    "VerifiedFeeCorrectionAuthorization",
    "VerifiedFeeCorrectionEvidence",
]
