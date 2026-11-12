"""Session/CSRF-bound issuance; ownership alone never grants service permission."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request

from apps.account.application.rbac import role_allows_by_matrix
from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantConflict,
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.application.simulated_corporate_action_write_issuance import (
    LockedSimulatedCorporateActionWriteScope,
    SimulatedCorporateActionGrantConsent,
    SimulatedCorporateActionWriteScopeLocker,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantRevocation,
    SimulatedCorporateActionWriteGrantSelector,
)
from apps.account.infrastructure.creation_authentication_transaction import (
    authenticated_creation_transaction,
)
from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.account.infrastructure.simulated_corporate_action_write_grant_repository import (
    DjangoSimulatedCorporateActionWriteGrantRepository,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_seal import (
    SimulatedCorporateActionWriteGrantSeal,
)
from core.exceptions import AuthenticationError, AuthorizationError


@contextmanager
def locked_simulated_action_trading_eligibility(*, user_id: int, using: str) -> Iterator[None]:
    """Preserve the trading RBAC denial both before work and before outer commit.

    Role eligibility does not supply consent, owner scope or a service grant.
    It only prevents this dedicated grant from bypassing existing read-only
    restrictions after a real credential or service transaction locks the user.
    """

    def verify() -> None:
        """Read locked current rows instead of a request's cached reverse relation."""
        user = (
            User.objects.using(using).select_for_update().filter(pk=user_id, is_active=True).first()
        )
        profile = (
            AccountProfileModel.objects.using(using)
            .select_for_update()
            .filter(user_id=user_id)
            .first()
        )
        if user is None or profile is None or type(profile.rbac_role) is not str:
            raise AuthorizationError("Current trading eligibility is unavailable")
        role = "admin" if user.is_superuser else profile.rbac_role
        if not role_allows_by_matrix(role, level="write", domain="trading"):
            raise AuthorizationError(
                "Current account role cannot authorize simulated service writes"
            )

    verify()
    yield
    verify()


@dataclass(frozen=True, slots=True)
class _IssueClock:
    instant: datetime

    def now(self) -> datetime:
        """Bind the immutable grant and its append to one real server instant."""
        return self.instant


def _session_consent_authenticator(request: Request) -> SessionAuthentication:
    """Require an explicit mutating request and the actual CSRF-enforcing backend."""
    if not isinstance(request, Request):
        raise AuthenticationError("A real Session-authenticated consent request is required")
    if request.method != "POST":
        raise AuthorizationError("Simulated service consent mutations require an explicit POST")
    authenticator = request.successful_authenticator
    if type(authenticator) is not SessionAuthentication:
        raise AuthenticationError("Simulated service consent requires Session authentication")
    return authenticator


def issue_authenticated_simulated_corporate_action_grant(
    request: Request,
    *,
    command: SimulatedCorporateActionGrantConsent,
    scope_locker: SimulatedCorporateActionWriteScopeLocker,
    using: str,
) -> SimulatedCorporateActionWriteGrant:
    """Authenticate current owner consent and seal one finite exact-source grant.

    The credential helper supplies identity only. The explicit consent, locked
    owner scope and server MAC are independent requirements. No API accepts
    issuer hashes, actor identities or consent timestamps from the caller.
    """
    if type(command) is not SimulatedCorporateActionGrantConsent:
        raise SimulatedCorporateActionWriteGrantUnavailable("grant consent type is invalid")
    command.__post_init__()
    authenticator = _session_consent_authenticator(request)
    if (
        not using
        or scope_locker.database_alias != using
        or not callable(getattr(scope_locker, "lock_owned_scope", None))
    ):
        raise SimulatedCorporateActionWriteGrantUnavailable("grant scope alias is invalid")

    def reauthenticate() -> tuple[object, object]:
        """Repeat the actual backend and CSRF checks before commit."""
        result = authenticator.authenticate(request)
        if result is None:
            raise AuthenticationError("Simulated service consent authentication expired")
        return result[0], result[1]

    issued_result: SimulatedCorporateActionWriteGrant | None = None

    def final_issuance_check() -> None:
        """Recheck exact current issuance after credentials and before atomic commit."""
        if issued_result is None:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "grant issuance did not produce a record"
            )
        checked_at = timezone.now()
        current = DjangoSimulatedCorporateActionWriteGrantRepository(using=using).get_current_grant(
            selector=issued_result.selector, as_of=checked_at
        )
        if (
            current is None
            or current.grant != issued_result
            or not SimulatedCorporateActionWriteGrantSeal().verify(issued_result)
            or not issued_result.is_active_at(checked_at)
        ):
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "grant issuance expired or changed before commit"
            )

    with (
        authenticated_creation_transaction(
            using=using,
            mode="session",
            authenticated_user=request.user,
            session=getattr(request._request, "session", None),
            token=None,
            reauthenticate=reauthenticate,
            before_commit=final_issuance_check,
        ) as requester,
        locked_simulated_action_trading_eligibility(user_id=requester.user_id, using=using),
    ):
        with scope_locker.lock_owned_scope(
            physical_account_id=command.physical_account_id,
            owner_user_id=requester.user_id,
            expected_binding=command.expected_binding,
            expected_grant_schema=command.grant_schema,
        ) as scope:
            if type(scope) is not LockedSimulatedCorporateActionWriteScope:
                raise SimulatedCorporateActionWriteGrantUnavailable("locked grant scope is invalid")
            scope.__post_init__()
            now = timezone.now()
            if (
                scope.physical_account_id != command.physical_account_id
                or scope.binding != command.expected_binding
                or scope.binding.owner_user_id != requester.user_id
                or scope.grant_schema != command.grant_schema
                or scope.terms_version != command.terms_version
                or scope.terms_sha256 != command.terms_sha256
                or (
                    command.grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
                    and (
                        scope.capabilities is None
                        or command.capabilities is None
                        or not set(command.capabilities).issubset(scope.capabilities)
                    )
                )
                or not now < command.valid_until <= scope.valid_until
            ):
                raise SimulatedCorporateActionWriteGrantUnavailable(
                    "grant consent differs from current locked scope or finite validity"
                )
            repository = DjangoSimulatedCorporateActionWriteGrantRepository(
                using=using, clock=_IssueClock(now)
            )
            current = repository.get_current_for_scope(
                scope.binding.account_namespace, scope.binding.account_id, as_of=now
            )
            seal = SimulatedCorporateActionWriteGrantSeal()
            if len(current) == 1:
                existing = current[0]
                if (
                    existing.grant_id == command.grant_id
                    and existing.grant_version == command.grant_version
                    and existing.schema == command.grant_schema
                    and existing.binding == scope.binding
                    and existing.valid_until == command.valid_until
                    and existing.capabilities == command.capabilities
                    and existing.terms_version == command.terms_version
                    and existing.terms_sha256 == command.terms_sha256
                    and existing.supersedes_content_hash
                    == command.expected_predecessor_content_hash
                    and existing.is_active_at(now)
                    and seal.verify(existing)
                ):
                    issued_result = existing
                    return existing
            if current and (
                len(current) != 1
                or current[0].binding.owner_user_id != requester.user_id
                or current[0].grant_id != command.grant_id
                or current[0].content_hash != command.expected_predecessor_content_hash
            ):
                raise SimulatedCorporateActionWriteGrantConflict(
                    "grant consent conflicts with the current account scope"
                )
            consent_facts: dict[str, object] = {
                "schema": "account.simulated-action-owner-consent.v1",
                "actor_id": requester.actor_id,
                "grant_id": command.grant_id,
                "grant_version": command.grant_version,
                "physical_account_id": scope.physical_account_id,
                "binding": scope.binding.to_payload(),
                "consented_at": now.isoformat(),
                "valid_until": command.valid_until.isoformat(),
            }
            consent_version = "1"
            if command.grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA:
                if command.capabilities is None:
                    raise SimulatedCorporateActionWriteGrantUnavailable(
                        "V2 consent capabilities are missing"
                    )
                consent_facts.update(
                    {
                        "schema": "account.simulated-action-owner-consent.v2",
                        "grant_schema": command.grant_schema,
                        "capabilities": [capability.value for capability in command.capabilities],
                        "terms_version": command.terms_version,
                        "terms_sha256": command.terms_sha256,
                        "predecessor_content_hash": command.expected_predecessor_content_hash,
                    }
                )
                consent_version = "2"
            consent_hash = hashlib.sha256(
                json.dumps(
                    consent_facts,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            grant = seal.seal(
                SimulatedCorporateActionWriteGrant(
                    grant_id=command.grant_id,
                    grant_version=command.grant_version,
                    binding=scope.binding,
                    consent_evidence_id=consent_hash,
                    consent_evidence_version=consent_version,
                    consent_evidence_hash=consent_hash,
                    issuer_evidence_id="pending",
                    issuer_evidence_version="1",
                    issuer_evidence_hash="0" * 64,
                    consented_at=now,
                    issued_at=now,
                    recorded_at=now,
                    valid_until=command.valid_until,
                    supersedes_content_hash=command.expected_predecessor_content_hash,
                    permission=(
                        SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION
                        if command.grant_schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
                        else SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION
                    ),
                    schema=command.grant_schema,
                    capabilities=command.capabilities,
                    terms_version=command.terms_version,
                    terms_sha256=command.terms_sha256,
                )
            )
            stored = repository.append_grant(
                grant,
                expected_predecessor_content_hash=command.expected_predecessor_content_hash,
            )
            issued_result = stored
            if stored != grant or not seal.verify(stored) or timezone.now() >= grant.valid_until:
                raise SimulatedCorporateActionWriteGrantUnavailable(
                    "grant issuer evidence or validity changed before commit"
                )
    return stored


def revoke_authenticated_simulated_corporate_action_grant(
    request: Request,
    *,
    selector: SimulatedCorporateActionWriteGrantSelector,
    revocation_id: str,
    revocation_version: str,
    using: str,
) -> SimulatedCorporateActionWriteGrantRevocation:
    """Withdraw one's own exact consent even after policy removal or grant expiry.

    Withdrawal needs a current real credential and stored owner identity. It
    does not require a still-live trading role, physical-source lease or policy:
    those restrictions must never prevent a user from removing permission.
    """
    if type(selector) is not SimulatedCorporateActionWriteGrantSelector:
        raise SimulatedCorporateActionWriteGrantUnavailable("withdrawal selector is invalid")
    selector.__post_init__()
    authenticator = _session_consent_authenticator(request)
    result: SimulatedCorporateActionWriteGrantRevocation | None = None

    def reauthenticate() -> tuple[object, object]:
        """Repeat the actual selected Session backend including CSRF checks."""
        authenticated = authenticator.authenticate(request)
        if authenticated is None:
            raise AuthenticationError("Owner withdrawal authentication expired")
        return authenticated[0], authenticated[1]

    def final_withdrawal_check() -> None:
        """Require the same exact durable withdrawal before the credential UOW commits."""
        if result is None:
            raise SimulatedCorporateActionWriteGrantUnavailable("withdrawal record is missing")
        current = DjangoSimulatedCorporateActionWriteGrantRepository(using=using).get_exact_record(
            selector=selector, as_of=timezone.now()
        )
        if (
            current is None
            or current.revocation != result
            or not SimulatedCorporateActionWriteGrantSeal().verify_revocation(result)
        ):
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "withdrawal record changed before commit"
            )

    with authenticated_creation_transaction(
        using=using,
        mode="session",
        authenticated_user=request.user,
        session=getattr(request._request, "session", None),
        token=None,
        reauthenticate=reauthenticate,
        before_commit=final_withdrawal_check,
    ) as requester:
        if selector.binding.owner_user_id != requester.user_id:
            raise AuthorizationError("Only the authenticated grant owner may withdraw consent")
        now = timezone.now()
        repository = DjangoSimulatedCorporateActionWriteGrantRepository(
            using=using, clock=_IssueClock(now)
        )
        current = repository.get_exact_record(selector=selector, as_of=now)
        if current is None or current.grant.binding.owner_user_id != requester.user_id:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "exact owner withdrawal target is unavailable"
            )
        seal = SimulatedCorporateActionWriteGrantSeal()
        if current.revocation is not None:
            result = current.revocation
            if (
                result.revocation_id != revocation_id
                or result.revocation_version != revocation_version
                or result.recorded_at > now
                or not seal.verify_revocation(result)
            ):
                raise SimulatedCorporateActionWriteGrantConflict(
                    "owner withdrawal conflicts with its immutable winner"
                )
            return result
        evidence = hashlib.sha256(
            json.dumps(
                {
                    "schema": "account.simulated-action-owner-withdrawal.v1",
                    "actor_id": requester.actor_id,
                    "grant_content_hash": current.grant.content_hash,
                    "revoked_at": now.isoformat(),
                    "revocation_id": revocation_id,
                    "revocation_version": revocation_version,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        result = seal.seal_revocation(
            SimulatedCorporateActionWriteGrantRevocation(
                revocation_id=revocation_id,
                revocation_version=revocation_version,
                grant_id=current.grant.grant_id,
                grant_version=current.grant.grant_version,
                grant_identity_hash=current.grant.identity_hash,
                grant_content_hash=current.grant.content_hash,
                revocation_evidence_id=evidence,
                revocation_evidence_version="1",
                revocation_evidence_hash=evidence,
                issuer_evidence_id="pending",
                issuer_evidence_version="1",
                issuer_evidence_hash="0" * 64,
                revoked_at=now,
                recorded_at=now,
            )
        )
        result = repository.append_revocation(result)
    return result
