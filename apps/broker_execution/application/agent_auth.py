"""Authentication contract for local QMT Agent requests."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from .repository_provider import get_broker_execution_repository
from .use_case_errors import BrokerAgentAuthenticationError

MAX_CLOCK_SKEW = timedelta(minutes=5)


def build_agent_signature(
    *, secret: str, sent_at: str, nonce: str, request_id: str, body: bytes
) -> str:
    """Build the request HMAC shared by the server and local Agent."""

    body_digest = hashlib.sha256(body).hexdigest()
    canonical = f"{sent_at}\n{nonce}\n{request_id}\n{body_digest}".encode()
    return hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


class AuthenticateAgentRequestUseCase:
    """Validate Agent token, scope, freshness, signature, and replay nonce."""

    def __init__(self, repository=None) -> None:
        self.repository = repository or get_broker_execution_repository()

    def execute(
        self,
        *,
        headers: Mapping[str, Any],
        body: bytes,
        required_scope: str,
        source_ip: str = "",
    ) -> dict[str, Any]:
        """Return authenticated machine context or fail closed."""

        authorization = str(headers.get("Authorization") or "")
        token = authorization[6:].strip() if authorization.startswith("Agent ") else ""
        credential_id = token.split(".", 1)[0] if "." in token else ""
        agent_id = str(headers.get("X-Agent-Id") or "").strip()
        request_id = str(headers.get("X-Request-Id") or "").strip()
        try:
            return self._authenticate(
                headers=headers,
                body=body,
                required_scope=required_scope,
            )
        except BrokerAgentAuthenticationError as exc:
            failure_code = self._failure_code(exc)
            try:
                self.repository.record_agent_auth_failure(
                    credential_id=credential_id,
                    agent_id=agent_id,
                    request_id=request_id,
                    required_scope=required_scope,
                    source_ip=source_ip,
                    failure_code=failure_code,
                )
            except Exception:
                # Authentication must still fail closed if best-effort audit persistence fails.
                pass
            raise

    def _authenticate(
        self,
        *,
        headers: Mapping[str, Any],
        body: bytes,
        required_scope: str,
    ) -> dict[str, Any]:
        """Perform authentication after the outer audit boundary is established."""

        authorization = str(headers.get("Authorization") or "")
        if not authorization.startswith("Agent "):
            raise BrokerAgentAuthenticationError("Agent authorization is required")
        token = authorization[6:].strip()
        try:
            credential_id, secret = token.split(".", 1)
        except ValueError as exc:
            raise BrokerAgentAuthenticationError("Malformed Agent credential") from exc
        agent_id = str(headers.get("X-Agent-Id") or "").strip()
        request_id = str(headers.get("X-Request-Id") or "").strip()
        sent_at = str(headers.get("X-Sent-At") or "").strip()
        nonce = str(headers.get("X-Nonce") or "").strip()
        signature = str(headers.get("X-Signature") or "").strip().lower()
        if not all((credential_id, secret, agent_id, request_id, sent_at, nonce, signature)):
            raise BrokerAgentAuthenticationError("Incomplete Agent authentication headers")
        try:
            parsed_sent_at = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise BrokerAgentAuthenticationError("Invalid Agent timestamp") from exc
        if parsed_sent_at.tzinfo is None:
            raise BrokerAgentAuthenticationError("Agent timestamp must include timezone")
        if abs(datetime.now(UTC) - parsed_sent_at.astimezone(UTC)) > MAX_CLOCK_SKEW:
            raise BrokerAgentAuthenticationError("Agent timestamp is outside the allowed window")
        expected = build_agent_signature(
            secret=secret,
            sent_at=sent_at,
            nonce=nonce,
            request_id=request_id,
            body=body,
        )
        if not hmac.compare_digest(signature, expected):
            raise BrokerAgentAuthenticationError("Invalid Agent request signature")
        return self.repository.authenticate_agent(
            credential_id=credential_id,
            secret_hash=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
            agent_id=agent_id,
            required_scope=required_scope,
            nonce_hash=hashlib.sha256(nonce.encode("utf-8")).hexdigest(),
            request_id=request_id,
        )

    @staticmethod
    def _failure_code(exc: BrokerAgentAuthenticationError) -> str:
        """Map internal authentication errors to bounded, non-secret audit codes."""

        message = str(exc).lower()
        checks = (
            ("authorization", "authorization_missing"),
            ("malformed", "credential_malformed"),
            ("incomplete", "headers_incomplete"),
            ("timestamp", "timestamp_invalid"),
            ("allowed window", "timestamp_stale"),
            ("signature", "signature_invalid"),
            ("nonce", "nonce_replayed"),
            ("scope", "scope_denied"),
            ("expired", "credential_expired"),
            ("revoked", "credential_revoked"),
            ("identity", "agent_identity_invalid"),
            ("credential", "credential_invalid"),
        )
        return next((code for marker, code in checks if marker in message), "authentication_failed")
