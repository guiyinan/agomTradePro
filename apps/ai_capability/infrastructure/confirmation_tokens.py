"""Signed, expiring confirmation ids for capability execution."""

from __future__ import annotations

from typing import Any

from django.core import signing


class DjangoConfirmationCodec:
    """Use Django signing to prevent capability or parameter tampering."""

    SALT = "agomtradepro.ai-capability.confirmation.v1"
    MAX_AGE_SECONDS = 300

    def issue(self, payload: dict[str, Any]) -> str:
        """Return a signed confirmation id."""

        return signing.dumps(dict(payload), salt=self.SALT, compress=True)

    def verify(self, confirmation_id: str) -> dict[str, Any]:
        """Verify one confirmation id and return its payload."""

        try:
            payload = signing.loads(
                confirmation_id,
                salt=self.SALT,
                max_age=self.MAX_AGE_SECONDS,
            )
        except signing.BadSignature as exc:
            raise ValueError("Confirmation id is invalid or expired.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Confirmation id payload is invalid.")
        return payload
