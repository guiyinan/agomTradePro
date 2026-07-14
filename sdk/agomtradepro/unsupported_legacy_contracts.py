"""Explicit inventory of legacy SDK/MCP contracts that are unsupported in the current build."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class UnsupportedLegacyContract:
    """Structured metadata for one explicitly unsupported legacy contract."""

    contract_key: str
    title: str
    owner_app: str
    legacy_tool_names: tuple[str, ...]
    sdk_methods: tuple[str, ...]
    suspected_paths: tuple[str, ...]
    reason: str
    evidence: tuple[str, ...]
    governance_rule: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)

    def build_error_message(self) -> str:
        """Return the user-facing fail-fast message for this unsupported contract."""
        path_summary = ", ".join(f"`{path}`" for path in self.suspected_paths)
        return (
            f"Unsupported legacy contract `{self.contract_key}`: {self.reason} "
            f"Legacy endpoints {path_summary} are not exposed by the canonical interface. "
            f"{self.governance_rule}"
        )


UNSUPPORTED_LEGACY_CONTRACTS: tuple[UnsupportedLegacyContract, ...] = (
    UnsupportedLegacyContract(
        contract_key="events.replay",
        title="Domain Event Replay",
        owner_app="events",
        legacy_tool_names=("replay_events",),
        sdk_methods=("replay_events",),
        suspected_paths=("/api/events/replay/",),
        reason=(
            "The canonical replay endpoint has no concrete target subscriber and can "
            "swallow per-event failures while returning an empty successful result."
        ),
        evidence=(
            "EventReplayView currently invokes the replay use case without a target handler.",
            "The replay loop requires can_handle()/handle() on a real subscriber.",
            "No staff-scoped subscriber allow-list or partial-failure contract exists.",
        ),
        governance_rule=(
            "Do not expose event replay until a concrete target identity, allow-list, "
            "preview, confirmation, idempotency, audit, and partial-failure contract exist."
        ),
    ),
)

_BY_KEY = {contract.contract_key: contract for contract in UNSUPPORTED_LEGACY_CONTRACTS}
_BY_TOOL_NAME = {
    tool_name: contract
    for contract in UNSUPPORTED_LEGACY_CONTRACTS
    for tool_name in contract.legacy_tool_names
}


def list_unsupported_legacy_contracts() -> tuple[UnsupportedLegacyContract, ...]:
    """Return all explicitly unsupported legacy contracts."""
    return UNSUPPORTED_LEGACY_CONTRACTS


def get_unsupported_legacy_contract(contract_key: str) -> UnsupportedLegacyContract:
    """Return one unsupported legacy contract by key."""
    return _BY_KEY[contract_key]


def get_unsupported_legacy_contract_for_tool(
    tool_name: str,
) -> UnsupportedLegacyContract | None:
    """Return the unsupported contract record for one legacy raw tool name, if any."""
    return _BY_TOOL_NAME.get(tool_name)
