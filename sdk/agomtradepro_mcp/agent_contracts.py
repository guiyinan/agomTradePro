"""Load versioned, non-hardcoded Agent contracts and MCP prompt playbooks."""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_CONTRACT_PATH = Path(__file__).resolve().parent / "prompts" / "agent_contracts.json"


class AgentContractConfigurationError(ValueError):
    """Raised when the configured Agent contract bundle is invalid."""


class AgentContractStore:
    """Read and validate the active Agent contract bundle from JSON configuration."""

    def __init__(self, config_path: str | Path | None = None) -> None:
        configured = config_path or os.getenv("AGOMTRADEPRO_MCP_AGENT_CONTRACT_PATH")
        self.config_path = Path(configured) if configured else DEFAULT_CONTRACT_PATH

    def _load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AgentContractConfigurationError(
                f"Unable to load Agent contract configuration: {self.config_path}"
            ) from exc

        if payload.get("schema_version") != 1:
            raise AgentContractConfigurationError("Unsupported Agent contract schema_version")
        for key in ("contract", "playbooks", "prompts"):
            if not isinstance(payload.get(key), dict):
                raise AgentContractConfigurationError(
                    f"Agent contract field must be an object: {key}"
                )
        contract = payload["contract"]
        for key in ("contract_id", "version", "status", "structured_reasoning"):
            if not contract.get(key):
                raise AgentContractConfigurationError(f"Agent contract field is required: {key}")
        return payload

    @staticmethod
    def _checksum(value: Any) -> str:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get_contract(self, task_type: str | None = None) -> dict[str, Any]:
        """Return the active contract plus checksum and optional task overlay."""

        payload = self._load()
        contract = deepcopy(payload["contract"])
        contract["content_sha256"] = self._checksum(payload["contract"])
        normalized_task = str(task_type or "").strip()
        overlays = contract.pop("task_overlays", {})
        if normalized_task and normalized_task in overlays:
            contract["task_overlay"] = deepcopy(overlays[normalized_task])
        return contract

    def list_playbooks(self) -> dict[str, Any]:
        """Return compact metadata for all configured workflow playbooks."""

        payload = self._load()
        playbooks = [
            {
                "playbook_key": key,
                "title": value.get("title", key),
                "summary": value.get("summary", ""),
            }
            for key, value in sorted(payload["playbooks"].items())
        ]
        return {
            "version": payload["contract"]["version"],
            "content_sha256": self._checksum(payload["playbooks"]),
            "playbooks": playbooks,
        }

    def get_playbook(self, playbook_key: str) -> dict[str, Any]:
        """Return one configured workflow playbook."""

        payload = self._load()
        playbook = payload["playbooks"].get(playbook_key)
        if playbook is None:
            raise KeyError(playbook_key)
        result = deepcopy(playbook)
        result["playbook_key"] = playbook_key
        result["version"] = payload["contract"]["version"]
        result["content_sha256"] = self._checksum(playbook)
        return result

    def render_prompt(
        self,
        prompt_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> str:
        """Render a named Prompt from the configured template and declared arguments."""

        payload = self._load()
        definition = payload["prompts"].get(prompt_name)
        if definition is None:
            raise KeyError(prompt_name)
        template = definition.get("template")
        if not isinstance(template, str) or not template.strip():
            raise AgentContractConfigurationError(f"Prompt template is empty: {prompt_name}")

        values = {key: str(value) for key, value in (arguments or {}).items()}
        required = definition.get("arguments", [])
        missing = [name for name in required if name not in values]
        if missing:
            raise AgentContractConfigurationError(
                f"Missing prompt arguments for {prompt_name}: {', '.join(missing)}"
            )
        try:
            return template.format_map(values)
        except KeyError as exc:
            raise AgentContractConfigurationError(
                f"Undeclared prompt placeholder in {prompt_name}: {exc.args[0]}"
            ) from exc

    def render_agent_contract_prompt(self, task_type: str = "general") -> str:
        """Render the structured Agent operating contract as prompt text."""

        return json.dumps(
            {
                "instruction": "Follow this contract and return decision_summary, not hidden chain-of-thought.",
                "requested_task_type": task_type,
                "contract": self.get_contract(task_type),
            },
            ensure_ascii=False,
            indent=2,
        )


AGENT_CONTRACT_STORE = AgentContractStore()
