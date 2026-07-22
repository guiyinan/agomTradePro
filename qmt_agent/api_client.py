"""Signed HTTPS client for the Agent-only canonical contract."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import ssl
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from typing import Any

from .config import AgentConfig


class AgentApiError(RuntimeError):
    """Raised for an Agent contract or transport failure."""


class AgentApiClient:
    """Small stdlib-only client so the Agent stays independent from Django and SDK."""

    def __init__(self, config: AgentConfig, token: str) -> None:
        self.config = config
        self.token = token
        try:
            _credential_id, self.secret = token.split(".", 1)
        except ValueError as exc:
            raise ValueError("Malformed Agent token") from exc
        self.ssl_context = ssl.create_default_context()
        if not config.verify_tls:
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE

    def post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Send one JSON request with freshness, nonce, request ID, and HMAC."""

        body = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        sent_at = datetime.now(UTC).isoformat()
        nonce = secrets.token_urlsafe(24)
        request_id = str(uuid.uuid4())
        body_digest = hashlib.sha256(body).hexdigest()
        canonical = f"{sent_at}\n{nonce}\n{request_id}\n{body_digest}".encode()
        signature = hmac.new(
            self.secret.encode("utf-8"), canonical, hashlib.sha256
        ).hexdigest()
        request = urllib.request.Request(
            f"{self.config.server_url}/api/broker-execution/agent/v1/{endpoint.lstrip('/')}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Agent {self.token}",
                "Content-Type": "application/json",
                "X-Agent-Id": self.config.agent_id,
                "X-Request-Id": request_id,
                "X-Sent-At": sent_at,
                "X-Nonce": nonce,
                "X-Signature": signature,
            },
        )
        try:
            with urllib.request.urlopen(
                request, timeout=20, context=self.ssl_context
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AgentApiError(f"Agent API rejected request ({exc.code}): {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise AgentApiError(f"Agent API transport failed: {exc}") from exc
        if not result.get("success"):
            raise AgentApiError(str(result.get("error") or "Agent API failed"))
        return dict(result.get("data") or {})
