"""Domain-separated server provenance for Session-issued simulated write grants.

This cryptographic helper is not an authenticator. Issuance must run inside the
real credential and physically locked owner transaction. A public content hash
or an arbitrary grant repository append cannot manufacture this server MAC.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
from dataclasses import replace

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantRevocation,
)
from shared.config.secrets import get_secrets

_ISSUER_ID = "account.session-authenticated-simulated-action-owner"
_ISSUER_VERSION = "1"
_ISSUER_V2_VERSION = "2"
_ISSUER_V3_VERSION = "3"
_KEY_DOMAIN = b"account.simulated-corporate-action-owner-issuer.v1/key"
_CONTENT_DOMAIN = "account.simulated-corporate-action-owner-issuer.v1/grant"
_CONTENT_V2_DOMAIN = "account.simulated-corporate-action-owner-issuer.v2/grant"
_CONTENT_V3_DOMAIN = "account.simulated-corporate-action-owner-issuer.v3/grant"
_REVOCATION_DOMAIN = "account.simulated-corporate-action-owner-issuer.v1/revocation"


def _grant_seal_contract(grant: SimulatedCorporateActionWriteGrant) -> tuple[str, str]:
    """Select the immutable issuer-version and MAC domain for one grant schema."""

    if grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA:
        return _ISSUER_VERSION, _CONTENT_DOMAIN
    if grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA:
        return _ISSUER_V2_VERSION, _CONTENT_V2_DOMAIN
    if grant.schema == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA:
        return _ISSUER_V3_VERSION, _CONTENT_V3_DOMAIN
    raise SimulatedCorporateActionWriteGrantUnavailable(
        "simulated action issuer grant schema is unsupported"
    )


def _issuer_key() -> bytes:
    """Derive a separate MAC key from the configured application encryption key."""
    configured = get_secrets(require_tushare_token=False).field_encryption_key
    if not configured:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "simulated action issuer server key is not configured"
        )
    try:
        raw = base64.b64decode(configured.encode("ascii"), altchars=b"-_", validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error) as error:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "simulated action issuer server key is invalid"
        ) from error
    if len(raw) != 32:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "simulated action issuer server key is invalid"
        )
    return hmac.digest(raw, _KEY_DOMAIN, "sha256")


def _signed_payload(
    grant: SimulatedCorporateActionWriteGrant | SimulatedCorporateActionWriteGrantRevocation,
    *,
    domain: str = _CONTENT_DOMAIN,
) -> bytes:
    """Bind all immutable facts, excluding the MAC and its dependent public hashes."""
    payload = grant.to_payload()
    for name in ("issuer_evidence_hash", "identity_hash", "content_hash"):
        payload.pop(name)
    return json.dumps(
        {"domain": domain, "record": payload},
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class SimulatedCorporateActionWriteGrantSeal:
    """Seal authenticated issuer facts and verify them against the current server key."""

    def seal_revocation(
        self,
        revocation: SimulatedCorporateActionWriteGrantRevocation,
    ) -> SimulatedCorporateActionWriteGrantRevocation:
        """Seal an authenticated owner's exact withdrawal under a distinct MAC domain."""
        if type(revocation) is not SimulatedCorporateActionWriteGrantRevocation:
            raise SimulatedCorporateActionWriteGrantUnavailable("issuer revocation type is invalid")
        selected = replace(
            revocation,
            issuer_evidence_id=_ISSUER_ID,
            issuer_evidence_version=_ISSUER_VERSION,
            issuer_evidence_hash="0" * 64,
            content_hash="",
        )
        digest = hmac.new(
            _issuer_key(), _signed_payload(selected, domain=_REVOCATION_DOMAIN), "sha256"
        ).hexdigest()
        return replace(selected, issuer_evidence_hash=digest, content_hash="")

    def verify_revocation(self, revocation: SimulatedCorporateActionWriteGrantRevocation) -> bool:
        """Verify one owner withdrawal without treating it as positive write authority."""
        if type(revocation) is not SimulatedCorporateActionWriteGrantRevocation:
            return False
        try:
            revocation.__post_init__()
        except (TypeError, ValueError):
            return False
        if (
            revocation.issuer_evidence_id != _ISSUER_ID
            or revocation.issuer_evidence_version != _ISSUER_VERSION
        ):
            return False
        expected = hmac.new(
            _issuer_key(), _signed_payload(revocation, domain=_REVOCATION_DOMAIN), "sha256"
        ).hexdigest()
        return hmac.compare_digest(revocation.issuer_evidence_hash, expected)

    def seal(self, grant: SimulatedCorporateActionWriteGrant) -> SimulatedCorporateActionWriteGrant:
        """Seal facts supplied by the credential/owner transaction, without doing its checks."""
        if type(grant) is not SimulatedCorporateActionWriteGrant:
            raise SimulatedCorporateActionWriteGrantUnavailable("issuer grant type is invalid")
        issuer_version, domain = _grant_seal_contract(grant)
        selected = replace(
            grant,
            issuer_evidence_id=_ISSUER_ID,
            issuer_evidence_version=issuer_version,
            issuer_evidence_hash="0" * 64,
            content_hash="",
        )
        digest = hmac.new(
            _issuer_key(), _signed_payload(selected, domain=domain), "sha256"
        ).hexdigest()
        return replace(selected, issuer_evidence_hash=digest, content_hash="")

    def verify(self, grant: SimulatedCorporateActionWriteGrant) -> bool:
        """Reject plain stored facts, substituted scope or signatures from a replaced key.

        Only the currently configured key is used; there is no implicit fallback.
        Restoring an old key can restore its cryptographic validity, but cannot
        remove immutable revocation, finite expiry or current scope requirements.
        Permanent withdrawal belongs to the revocation ledger, not key rollback.
        """
        if type(grant) is not SimulatedCorporateActionWriteGrant:
            return False
        try:
            grant.__post_init__()
        except (TypeError, ValueError):
            return False
        try:
            issuer_version, domain = _grant_seal_contract(grant)
        except SimulatedCorporateActionWriteGrantUnavailable:
            return False
        if (
            grant.issuer_evidence_id != _ISSUER_ID
            or grant.issuer_evidence_version != issuer_version
        ):
            return False
        expected = hmac.new(
            _issuer_key(), _signed_payload(grant, domain=domain), "sha256"
        ).hexdigest()
        return hmac.compare_digest(grant.issuer_evidence_hash, expected)
