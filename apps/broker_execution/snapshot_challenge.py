"""Server-clock challenge for ordering a subsequent authenticated QMT account observation."""

import secrets
from datetime import datetime
from uuid import UUID

from django.core import signing
from django.utils import timezone

from apps.broker_execution.domain.connection_freshness import HEARTBEAT_FRESHNESS

_SALT = "broker-execution.account-sampling-challenge.v1"


def issue_snapshot_challenge(*, agent_pk: int, account_id: int, credential_id: UUID) -> str:
    """Issue a short-lived lower bound using the server clock and an unpredictable nonce."""
    return signing.dumps(
        [
            agent_pk,
            account_id,
            str(credential_id),
            timezone.now().isoformat(),
            secrets.token_urlsafe(16),
        ],
        salt=_SALT,
    )


def confirmed_sampling_lower_bound(
    *, token: object, agent_pk: int, account_id: int, credential_id: UUID, received_at: datetime
) -> datetime | None:
    """Only the server's authenticated challenge clock can establish sample causality."""
    if type(token) is not str or not 0 < len(token) <= 2048:
        return None
    try:
        claims = signing.loads(token, salt=_SALT)
        if (
            not isinstance(claims, list)
            or len(claims) != 5
            or claims[:3] != [agent_pk, account_id, str(credential_id)]
        ):
            return None
        issued_at = datetime.fromisoformat(claims[3])
        if (
            issued_at.utcoffset() is None
            or not received_at - HEARTBEAT_FRESHNESS <= issued_at <= received_at
        ):
            return None
    except (TypeError, ValueError, signing.BadSignature):
        return None
    return issued_at
