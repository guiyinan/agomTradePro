"""Compose the maintenance HTTP entry points for financial availability Owner events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.contrib.auth.models import AbstractBaseUser
from django.db import DEFAULT_DB_ALIAS
from django.http import HttpRequest
from django.utils import timezone

from apps.data_center.application.financial_availability_governance import (
    append_and_apply_financial_availability_governance,
    append_financial_availability_revoke,
)
from apps.data_center.application.financial_availability_governance_ports import (
    FinancialAvailabilityGovernanceRepositoryPort,
    FinancialAvailabilityOwnerEventRepositoryPort,
    FinancialAvailabilityPermissionAuthorizerPort,
    FinancialAvailabilitySessionRequestProof,
)
from apps.data_center.domain.financial_availability_governance import (
    FinancialAvailabilityGovernanceRecord,
    FinancialAvailabilityOwnerEventIdentity,
)
from apps.data_center.infrastructure.financial_availability_governance_authority import (
    DjangoFinancialAvailabilityPermissionAuthorizer,
)
from core.exceptions import AuthorizationError, DataValidationError


def apply_financial_availability_governance_from_request(
    request: HttpRequest,
    record: FinancialAvailabilityGovernanceRecord,
    *,
    reason: str,
    records: FinancialAvailabilityGovernanceRepositoryPort,
    owner_events: FinancialAvailabilityOwnerEventRepositoryPort,
) -> tuple[FinancialAvailabilityGovernanceRecord, FinancialAvailabilityOwnerEventIdentity]:
    """Derive C2 Owner proof from Django's real authenticated request and apply.

    The request body cannot supply an actor, session selector, alias, timestamp,
    or permission boolean. The serializer must first produce the exact typed
    record. Infrastructure reloads and locks the real database session, User,
    Permission and grants before standard ``has_perm`` checks.
    """

    proof = _proof_from_authenticated_request(request)
    _require_default_request_alias(proof.database_alias, records.database_alias)
    if owner_events.database_alias != DEFAULT_DB_ALIAS:
        raise DataValidationError(
            "C2 Owner event repository is not on the authenticated database.",
            code="FIN_AVAILABILITY_CURRENT_ALIAS_MISMATCH",
        )
    authorizer: FinancialAvailabilityPermissionAuthorizerPort = (
        DjangoFinancialAvailabilityPermissionAuthorizer(using=DEFAULT_DB_ALIAS)
    )
    source_known_at = _require_utc(records.now(), "server source cutoff")
    return append_and_apply_financial_availability_governance(
        record,
        proof=proof,
        reason=reason,
        source_known_at=source_known_at,
        records=records,
        owner_events=owner_events,
        authorizer=authorizer,
    )


def revoke_financial_availability_governance_from_request(
    request: HttpRequest,
    record: FinancialAvailabilityGovernanceRecord,
    apply_event: FinancialAvailabilityOwnerEventIdentity,
    *,
    reason: str,
    records: FinancialAvailabilityGovernanceRepositoryPort,
    owner_events: FinancialAvailabilityOwnerEventRepositoryPort,
) -> FinancialAvailabilityOwnerEventIdentity:
    """Append a C2 revoke from the same real request/session authorization path."""

    proof = _proof_from_authenticated_request(request)
    _require_default_request_alias(proof.database_alias, records.database_alias)
    if owner_events.database_alias != DEFAULT_DB_ALIAS:
        raise DataValidationError(
            "C2 Owner event repository is not on the authenticated database.",
            code="FIN_AVAILABILITY_CURRENT_ALIAS_MISMATCH",
        )
    authorizer: FinancialAvailabilityPermissionAuthorizerPort = (
        DjangoFinancialAvailabilityPermissionAuthorizer(using=DEFAULT_DB_ALIAS)
    )
    return append_financial_availability_revoke(
        record,
        apply_event,
        proof=proof,
        reason=reason,
        records=records,
        owner_events=owner_events,
        authorizer=authorizer,
    )


def _proof_from_authenticated_request(
    request: HttpRequest,
) -> FinancialAvailabilitySessionRequestProof:
    """Extract only the live request's authenticated Django User and session key."""

    if not isinstance(request, HttpRequest):
        raise AuthorizationError("C2 Owner writes require a real Django HttpRequest.")
    user = request.user
    if not isinstance(user, AbstractBaseUser):
        raise AuthorizationError("C2 Owner request has no authenticated Django User.")
    try:
        user_id = user.pk
        user_alias = user._state.db
        session_key = request.session.session_key
        authenticated = user.is_authenticated
    except (AttributeError, TypeError) as error:
        raise AuthorizationError("C2 Owner request has no persisted session identity.") from error
    if (
        authenticated is not True
        or type(user_id) is not int
        or user_id <= 0
        or type(user_alias) is not str
        or not user_alias
        or type(session_key) is not str
        or not session_key
    ):
        raise AuthorizationError("C2 Owner request has no persisted authenticated session.")
    request_at = timezone.now()
    return FinancialAvailabilitySessionRequestProof(
        user_id=user_id,
        session_key=session_key,
        request_authenticated_at=request_at.astimezone(UTC),
        request_user_database_alias=user_alias,
        database_alias=user_alias,
    )


def _require_default_request_alias(request_alias: str, repository_alias: str) -> None:
    """Prevent default-authenticated Users from being relabeled onto another DB."""

    if request_alias != DEFAULT_DB_ALIAS or repository_alias != DEFAULT_DB_ALIAS:
        raise AuthorizationError(
            "C2 HTTP authorization and configuration must use the default database alias."
        )


def _require_utc(value: object, name: str) -> datetime:
    """Require a trusted server-sampled aware UTC instant."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise DataValidationError(
            f"{name} must be an aware UTC datetime.",
            code="FIN_AVAILABILITY_CURRENT_CLOCK_INVALID",
        )
    return value.astimezone(UTC)
