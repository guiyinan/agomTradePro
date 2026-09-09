"""Pinned-server HTTPS transport and protected pairing for the same QMT Agent."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .api_client import AgentApiError

BASE = "/api/data-center/qmt-bridge/"


def validate_server_url(value: str) -> str:
    """Accept an exact HTTPS origin; loopback HTTP is reserved for local tests."""
    parsed = urllib.parse.urlsplit(value)
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or (
            parsed.scheme != "https"
            and not (
                parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
            )
        )
    ):
        raise ValueError("Server address must be an HTTPS origin without credentials or a path")
    return value.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        """Never forward pairing codes or machine tokens to a redirected server."""
        raise AgentApiError("Bridge server redirected the request; verify the bound server address")


def protect_token(value: str, *, decrypt: bool = False) -> str:
    """Use the current Windows user's DPAPI; pass secrets only through stdin."""
    if os.name != "nt":
        raise AgentApiError("Persistent bridge credentials require Windows DPAPI")
    script = (
        "$s=[Console]::In.ReadToEnd(); $v=ConvertTo-SecureString $s; "
        "$p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($v); "
        "try {[Console]::Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($p))} "
        "finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p)}"
        if decrypt
        else "$s=[Console]::In.ReadToEnd(); [Console]::Write(($s | ConvertTo-SecureString -AsPlainText -Force | ConvertFrom-SecureString))"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        input=value,
        text=True,
        capture_output=True,
        env={key: val for key, val in os.environ.items() if key.lower() != "psmodulepath"},
        timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode or not result.stdout.strip():
        raise AgentApiError("Windows credential protection failed")
    return result.stdout.strip()


class BridgeClient:
    """Separate market-data credential, same Agent package and outbound transport."""

    def __init__(self, server_url: str, binding_id: str = "", token: str = "") -> None:
        self.server_url = validate_server_url(server_url)
        self.binding_id = binding_id
        self.token = token
        self.opener = urllib.request.build_opener(_NoRedirect())

    def post(
        self, operation: str, payload: dict[str, Any], *, pairing: bool = False
    ) -> dict[str, Any]:
        """Send a bounded JSON request with destination-bound HMAC and fresh nonce."""
        if operation not in ("pair", "plan", "batches"):
            raise ValueError("Unknown bridge operation")
        path = BASE + ("pair/" if pairing else f"agent/v1/{operation}/")
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        headers = {"Content-Type": "application/json"}
        if not pairing:
            sent = datetime.now(UTC).isoformat()
            nonce = secrets.token_urlsafe(24)
            canonical = f"POST\n{path}\n{self.binding_id}\n{sent}\n{nonce}\n{hashlib.sha256(body).hexdigest()}"
            headers.update(
                {
                    "X-Bridge-Id": self.binding_id,
                    "Authorization": f"QmtBridge {self.token}",
                    "X-Sent-At": sent,
                    "X-Nonce": nonce,
                    "X-Signature": hmac.new(
                        self.token.encode(), canonical.encode(), hashlib.sha256
                    ).hexdigest(),
                }
            )
        request = urllib.request.Request(
            self.server_url + path, data=body, headers=headers, method="POST"
        )
        try:
            with self.opener.open(request, timeout=20) as response:
                result = json.loads(response.read(2_000_000))
        except urllib.error.HTTPError as exc:
            raise AgentApiError(
                f"Bridge request rejected ({exc.code}); inspect server binding status"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AgentApiError("Bridge server unavailable or response invalid") from exc
        if (
            not isinstance(result, dict)
            or result.get("success") is not True
            or not isinstance(result.get("data"), dict)
        ):
            raise AgentApiError("Invalid bridge acknowledgement")
        return dict(result["data"])

    def pair(self, code: str, agent_id: str, state_dir: Path, *, repair: bool = False) -> None:
        """Bind locally and persist only a DPAPI-encrypted token and public metadata."""
        target = state_dir / "bridge.json"
        previous: dict[str, Any] = {}
        if target.exists():
            if not repair:
                raise AgentApiError(
                    "Existing binding found; use --repair after server-side repair pairing"
                )
            previous = json.loads(target.read_text(encoding="utf-8"))
            if (
                previous.get("server_url") != self.server_url
                or previous.get("agent_id") != agent_id
            ):
                raise AgentApiError(
                    "Repair cannot change the bound server or Agent; use a separate state directory"
                )
        result = self.post("pair", {"pairing_code": code, "agent_id": agent_id}, pairing=True)
        if result.get("server_url") != self.server_url or result.get("agent_id") != agent_id:
            raise AgentApiError("Pairing response does not match the requested server/Agent")
        if previous and previous.get("binding_id") != result.get("binding_id"):
            raise AgentApiError("Repair cannot replace the binding owning the pending outbox")
        token = str(result.pop("token"))
        result["protected_token"] = protect_token(token)
        state_dir.mkdir(parents=True, exist_ok=True)
        temporary = state_dir / "bridge.json.new"
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
        temporary.replace(target)

    @classmethod
    def load(cls, state_dir: Path) -> BridgeClient:
        """Load the pinned server binding and decrypt its dedicated market credential."""
        data = json.loads((state_dir / "bridge.json").read_text(encoding="utf-8"))
        return cls(
            str(data["server_url"]),
            str(data["binding_id"]),
            protect_token(str(data["protected_token"]), decrypt=True),
        )
