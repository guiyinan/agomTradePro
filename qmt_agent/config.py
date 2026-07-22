"""Configuration loading for the standalone QMT Agent."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentConfig:
    """Validated local Agent configuration; the credential is loaded separately."""

    agent_id: str
    server_url: str
    qmt_userdata_path: Path
    broker_account_id: str
    broker_account_type: str
    system_account_id: int
    qmt_client_version: str = ""
    xtquant_version: str = ""
    poll_interval_seconds: float = 2.0
    lease_seconds: int = 30
    dry_run: bool = True
    log_dir: Path = Path("logs")
    state_dir: Path = Path("state")
    kill_switch_file: Path = Path("STOP")
    verify_tls: bool = True
    enforce_trading_session: bool = True
    trading_timezone: str = "Asia/Shanghai"
    allowed_trading_windows: tuple[str, ...] = ("09:30-11:30", "13:00-15:00")
    price_deviation_limit_pct: float = 0.03
    max_position_count: int = 20

    @classmethod
    def from_file(cls, path: str | Path) -> AgentConfig:
        """Load JSON or YAML without ever reading secrets from the config file."""

        source = Path(path)
        text = source.read_text(encoding="utf-8")
        if source.suffix.lower() == ".json":
            payload = json.loads(text)
        else:
            try:
                import yaml
            except ImportError as exc:
                raise RuntimeError("PyYAML is required for YAML Agent configuration") from exc
            payload = yaml.safe_load(text)
        if not isinstance(payload, dict):
            raise ValueError("Agent configuration must be an object")
        if any(key in payload for key in ("token", "secret", "credential")):
            raise ValueError("Agent secrets must not be stored in the configuration file")
        root = source.parent.resolve()

        def local_path(value: Any) -> Path:
            candidate = Path(str(value))
            return candidate if candidate.is_absolute() else root / candidate

        config = cls(
            agent_id=str(payload["agent_id"]),
            server_url=str(payload["server_url"]).rstrip("/"),
            qmt_userdata_path=local_path(payload["qmt_userdata_path"]),
            broker_account_id=str(payload["broker_account_id"]),
            broker_account_type=str(payload.get("broker_account_type", "STOCK")),
            system_account_id=int(payload["system_account_id"]),
            qmt_client_version=str(payload.get("qmt_client_version", "")).strip(),
            xtquant_version=str(payload.get("xtquant_version", "")).strip(),
            poll_interval_seconds=float(payload.get("poll_interval_seconds", 2)),
            lease_seconds=int(payload.get("lease_seconds", 30)),
            dry_run=bool(payload.get("dry_run", True)),
            log_dir=local_path(payload.get("log_dir", "logs")),
            state_dir=local_path(payload.get("state_dir", "state")),
            kill_switch_file=local_path(payload.get("kill_switch_file", "STOP")),
            verify_tls=bool(payload.get("verify_tls", True)),
            enforce_trading_session=bool(payload.get("enforce_trading_session", True)),
            trading_timezone=str(payload.get("trading_timezone", "Asia/Shanghai")),
            allowed_trading_windows=tuple(
                str(item) for item in payload.get(
                    "allowed_trading_windows", ["09:30-11:30", "13:00-15:00"]
                )
            ),
            price_deviation_limit_pct=float(
                payload.get("price_deviation_limit_pct", 0.03)
            ),
            max_position_count=int(payload.get("max_position_count", 20)),
        )
        config.validate()
        return config

    def validate(self) -> None:
        """Fail closed on unsafe or unsupported configuration."""

        if not self.agent_id or self.system_account_id <= 0:
            raise ValueError("agent_id and system_account_id are required")
        if self.broker_account_type.upper() != "STOCK":
            raise ValueError("The first QMT Agent release supports STOCK accounts only")
        if not self.server_url.startswith("https://") and not self.server_url.startswith(
            "http://127.0.0.1"
        ):
            raise ValueError("server_url must use HTTPS outside local tests")
        if not self.verify_tls and not self.server_url.startswith(
            ("http://127.0.0.1", "https://127.0.0.1", "https://localhost")
        ):
            raise ValueError("TLS verification can only be disabled for loopback tests")
        if not 0.5 <= self.poll_interval_seconds <= 60:
            raise ValueError("poll_interval_seconds must be between 0.5 and 60")
        if not 10 <= self.lease_seconds <= 120:
            raise ValueError("lease_seconds must be between 10 and 120")
        if not self.allowed_trading_windows:
            raise ValueError("allowed_trading_windows cannot be empty")
        if not 0 <= self.price_deviation_limit_pct <= 1:
            raise ValueError("price_deviation_limit_pct must be between 0 and 1")
        if not 1 <= self.max_position_count <= 1000:
            raise ValueError("max_position_count must be between 1 and 1000")


def load_agent_token() -> str:
    """Load the one-time issued token from a protected environment variable."""

    token = os.environ.get("AGOM_QMT_AGENT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("AGOM_QMT_AGENT_TOKEN is required")
    return token
