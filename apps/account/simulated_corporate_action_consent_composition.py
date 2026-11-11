"""Owner consent preparation tokens and read-only current consent metadata."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from datetime import datetime
from typing import cast

from django.contrib.sessions.models import Session
from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone
from rest_framework.request import Request

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.application.simulated_corporate_action_write_issuance import (
    SimulatedCorporateActionGrantConsent,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantBinding,
    SimulatedCorporateActionWriteGrantRecord,
    SimulatedCorporateActionWriteGrantSelector,
)
from apps.account.infrastructure.creation_authentication_transaction import (
    authenticated_creation_transaction,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_repository import (
    DjangoSimulatedCorporateActionWriteGrantRepository,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_seal import (
    SimulatedCorporateActionWriteGrantSeal,
    _issuer_key,
)
from apps.account.simulated_corporate_action_write_issuance_composition import (
    _session_consent_authenticator,
)
from core.exceptions import AuthenticationError


def _object(value: object) -> dict[str, object]:
    """Narrow one exact JSON object without permitting non-string keys."""
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ValueError("consent preparation object is invalid")
    return cast(dict[str, object], value)


def _text(value: object) -> str:
    """Require a literal string before constructing a typed consent entity."""
    if type(value) is not str:
        raise ValueError("consent preparation string is invalid")
    return value


def _integer(value: object) -> int:
    """Reject booleans and non-positive account identities."""
    if type(value) is not int or value <= 0:
        raise ValueError("consent preparation identity is invalid")
    return value


def _clock(value: object) -> datetime:
    """Parse an explicit aware ISO clock without substituting the request time."""
    result = datetime.fromisoformat(_text(value))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("consent preparation clock is invalid")
    return result


def _binding(value: object) -> SimulatedCorporateActionWriteGrantBinding:
    """Restore all selectors with no optional or caller-invented binding fields."""
    payload = _object(value)
    fields = {
        "account_namespace",
        "account_id",
        "owner_user_id",
        "tenant_id",
        "owner_id",
        "account_source_id",
        "account_source_version",
        "account_source_content_hash",
        "policy_id",
        "policy_version",
        "policy_content_hash",
    }
    if set(payload) != fields:
        raise ValueError("consent preparation binding fields are invalid")
    return SimulatedCorporateActionWriteGrantBinding(
        account_namespace=_text(payload["account_namespace"]),
        account_id=_text(payload["account_id"]),
        owner_user_id=_integer(payload["owner_user_id"]),
        tenant_id=_text(payload["tenant_id"]),
        owner_id=_text(payload["owner_id"]),
        account_source_id=_text(payload["account_source_id"]),
        account_source_version=_text(payload["account_source_version"]),
        account_source_content_hash=_text(payload["account_source_content_hash"]),
        policy_id=_text(payload["policy_id"]),
        policy_version=_text(payload["policy_version"]),
        policy_content_hash=_text(payload["policy_content_hash"]),
    )


def _pack(payload: dict[str, object], *, purpose: str) -> str:
    """Seal preparation data in a domain separate from grants and revocations."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    digest = hmac.new(_issuer_key(), purpose.encode() + b"\0" + body, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(body).decode() + "." + digest


def _unpack(token: str, *, purpose: str) -> dict[str, object]:
    """Verify the complete token before decoding selectors from its JSON boundary."""
    try:
        if type(token) is not str or len(token) > 16384:
            raise ValueError("consent preparation token is invalid")
        encoded, digest = token.rsplit(".", 1)
        body = base64.b64decode(encoded, altchars=b"-_", validate=True)
        expected = hmac.new(
            _issuer_key(), purpose.encode() + b"\0" + body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(digest, expected):
            raise ValueError("consent preparation seal is invalid")
        payload: object = json.loads(body)
        return _object(payload)
    except (ValueError, TypeError, UnicodeError, binascii.Error) as error:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "owner consent preparation is invalid or unavailable"
        ) from error


def prepare_simulated_action_consent_token(
    command: SimulatedCorporateActionGrantConsent, *, as_of: datetime
) -> str:
    """Prepare immutable terms for display; this token never grants write permission."""
    command.__post_init__()
    if as_of.tzinfo is None or as_of.utcoffset() is None or not as_of < command.valid_until:
        raise SimulatedCorporateActionWriteGrantUnavailable("consent preparation already expired")
    return _pack(
        {
            "grant_id": command.grant_id,
            "grant_version": command.grant_version,
            "physical_account_id": command.physical_account_id,
            "binding": command.expected_binding.to_payload(),
            "prepared_at": as_of.isoformat(),
            "valid_until": command.valid_until.isoformat(),
            "predecessor": command.expected_predecessor_content_hash,
        },
        purpose="account.simulated-action-consent-preparation.v1",
    )


def restore_simulated_action_consent_token(
    token: str,
    *,
    owner_user_id: int,
    physical_account_id: int,
    confirmed: bool,
    as_of: datetime,
) -> SimulatedCorporateActionGrantConsent:
    """Restore displayed terms after explicit confirmation, before real credential checks."""
    value = _unpack(token, purpose="account.simulated-action-consent-preparation.v1")
    try:
        if set(value) != {
            "grant_id",
            "grant_version",
            "physical_account_id",
            "binding",
            "prepared_at",
            "valid_until",
            "predecessor",
        }:
            raise ValueError("consent preparation fields are invalid")
        predecessor = value["predecessor"]
        result = SimulatedCorporateActionGrantConsent(
            grant_id=_text(value["grant_id"]),
            grant_version=_text(value["grant_version"]),
            physical_account_id=_integer(value["physical_account_id"]),
            expected_binding=_binding(value["binding"]),
            valid_until=_clock(value["valid_until"]),
            consent=confirmed,
            expected_predecessor_content_hash=None if predecessor is None else _text(predecessor),
        )
        if (
            result.physical_account_id != _integer(physical_account_id)
            or result.expected_binding.owner_user_id != _integer(owner_user_id)
            or not _clock(value["prepared_at"]) <= as_of < result.valid_until
        ):
            raise ValueError("consent preparation scope or clock changed")
        return result
    except (ValueError, TypeError) as error:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "owner consent preparation expired or differs from the current requester"
        ) from error


def read_current_simulated_action_consent_metadata(
    *, canonical_account_id: str, owner_user_id: int, as_of: datetime, using: str
) -> SimulatedCorporateActionWriteGrant | None:
    """Read unique signed consent metadata without granting a service authority context."""
    grants = DjangoSimulatedCorporateActionWriteGrantRepository(using=using).get_current_for_scope(
        "simulated", canonical_account_id, as_of=as_of
    )
    if not grants:
        return None
    if (
        len(grants) != 1
        or grants[0].binding.owner_user_id != owner_user_id
        or not SimulatedCorporateActionWriteGrantSeal().verify(grants[0])
    ):
        raise SimulatedCorporateActionWriteGrantUnavailable("owner consent metadata is ambiguous")
    return grants[0]


def prepare_simulated_action_withdrawal_token(
    grant: SimulatedCorporateActionWriteGrant, *, physical_account_id: int
) -> str:
    """Retain an exact withdrawal locator that remains usable after the grant expires."""
    grant.__post_init__()
    return _pack(
        {
            "grant_id": grant.grant_id,
            "grant_version": grant.grant_version,
            "identity_hash": grant.identity_hash,
            "content_hash": grant.content_hash,
            "binding": grant.binding.to_payload(),
            "physical_account_id": _integer(physical_account_id),
        },
        purpose="account.simulated-action-consent-withdrawal-locator.v1",
    )


def read_latest_simulated_action_withdrawal_metadata(
    *, canonical_account_id: str, owner_user_id: int, as_of: datetime, using: str
) -> SimulatedCorporateActionWriteGrantRecord | None:
    """Discover one's canonical historical target without granting Current authority.

    Withdrawal only removes permission. A former issuer MAC need not verify
    under today's rotated key; the immutable stored owner and exact selector
    remain mandatory, and the actual submission reauthenticates that owner.
    """
    records = DjangoSimulatedCorporateActionWriteGrantRepository(using=using).get_scope_records(
        "simulated", canonical_account_id, as_of=as_of
    )
    owned = tuple(
        record
        for record in records
        if record.grant.binding.owner_user_id == owner_user_id and record.revocation is None
    )
    return owned[-1] if owned else None


def read_authenticated_withdrawal_session_deadline(request: Request) -> datetime:
    """Use the real credential deadline for UI withdrawal preparation, without renewing a grant."""
    authenticator = _session_consent_authenticator(request)

    def reauthenticate() -> tuple[object, object]:
        """Repeat the selected browser backend and CSRF verification."""
        result = authenticator.authenticate(request)
        if result is None:
            raise AuthenticationError("Withdrawal preparation authentication expired")
        return result[0], result[1]

    session = getattr(request._request, "session", None)
    with authenticated_creation_transaction(
        using=DEFAULT_DB_ALIAS,
        mode="session",
        authenticated_user=request.user,
        session=session,
        token=None,
        reauthenticate=reauthenticate,
    ):
        key: object = getattr(session, "session_key", None)
        if type(key) is not str or not key:
            raise AuthenticationError("Withdrawal preparation session is missing")
        record = (
            Session.objects.using(DEFAULT_DB_ALIAS)
            .select_for_update()
            .filter(session_key=key)
            .first()
        )
        if record is None or record.expire_date <= timezone.now():
            raise AuthenticationError("Withdrawal preparation session expired")
        return record.expire_date


def restore_simulated_action_withdrawal_token(
    token: str, *, owner_user_id: int, physical_account_id: int
) -> SimulatedCorporateActionWriteGrantSelector:
    """Resolve only one's original withdrawal target; real Session/CSRF remains mandatory."""
    value = _unpack(token, purpose="account.simulated-action-consent-withdrawal-locator.v1")
    try:
        if set(value) != {
            "grant_id",
            "grant_version",
            "identity_hash",
            "content_hash",
            "binding",
            "physical_account_id",
        }:
            raise ValueError("withdrawal preparation fields are invalid")
        result = SimulatedCorporateActionWriteGrantSelector(
            grant_id=_text(value["grant_id"]),
            grant_version=_text(value["grant_version"]),
            identity_hash=_text(value["identity_hash"]),
            content_hash=_text(value["content_hash"]),
            binding=_binding(value["binding"]),
        )
        if _integer(value["physical_account_id"]) != _integer(
            physical_account_id
        ) or result.binding.owner_user_id != _integer(owner_user_id):
            raise ValueError("withdrawal target belongs to another account or owner")
        return result
    except (ValueError, TypeError) as error:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "withdrawal locator is invalid"
        ) from error
