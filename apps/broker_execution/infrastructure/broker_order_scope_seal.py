"""Domain-separated MACs for session-issued Broker scopes and opaque account references."""

import base64
import hmac

from apps.broker_execution.application.use_case_errors import BrokerExecutionConflictError
from apps.broker_execution.domain.broker_account_identity_snapshot import (
    KeyedBrokerAccountReferenceDigest,
)
from shared.config.secrets import get_secrets


def _mac(domain: bytes, message: bytes) -> str:
    configured = get_secrets(require_tushare_token=False).field_encryption_key
    try:
        key = base64.b64decode(configured or "", altchars=b"-_", validate=True)
    except ValueError as exc:
        raise BrokerExecutionConflictError("broker_scope_server_key_unavailable") from exc
    if len(key) != 32:
        raise BrokerExecutionConflictError("broker_scope_server_key_unavailable")
    return hmac.new(hmac.digest(key, domain, "sha256"), message, "sha256").hexdigest()


def owner_signature_mac(content_hash: str) -> str:
    """MAC the whole immutable receipt after server-side owner authentication."""
    return _mac(b"broker_execution/order-owner-signature/v1", content_hash.encode("ascii"))


class BrokerReferenceDigester:
    """Shared digest implementation for Broker snapshot issuance and current binding checks."""

    def digest(self, *, opaque_reference: bytes) -> KeyedBrokerAccountReferenceDigest:
        """Digest the broker's opaque account ID without persisting the raw reference."""
        return KeyedBrokerAccountReferenceDigest(
            "hmac-sha256",
            "broker-binding.v1",
            _mac(b"broker_execution/qmt-binding-reference/v1", opaque_reference),
        )
