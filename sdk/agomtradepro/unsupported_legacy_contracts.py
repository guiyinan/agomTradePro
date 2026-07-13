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
        contract_key="realtime.delete.price_alert",
        title="Realtime Price Alert CRUD",
        owner_app="realtime",
        legacy_tool_names=(
            "list_price_alerts",
            "create_price_alert",
            "delete_price_alert",
        ),
        sdk_methods=(
            "list_alerts",
            "create_alert",
            "get_alert",
            "delete_alert",
        ),
        suspected_paths=(
            "/api/realtime/alerts/",
            "/api/realtime/alerts/{id}/",
        ),
        reason=(
            "Realtime price alert CRUD is unavailable in the current server build."
        ),
        evidence=(
            "apps/realtime/interface/ does not expose /api/realtime/alerts/ routes.",
            "apps.realtime.infrastructure.models does not provide a PriceAlert model.",
            "SDK and raw MCP compatibility paths are fail-fast only until a real canonical API exists.",
        ),
        governance_rule=(
            "Do not treat this legacy SDK/MCP surface as a governed replacement candidate "
            "until a real realtime alert API is implemented."
        ),
    ),
    UnsupportedLegacyContract(
        contract_key="realtime.price_subscription",
        title="Realtime Price Push Subscription",
        owner_app="realtime",
        legacy_tool_names=(),
        sdk_methods=(
            "subscribe_price",
            "unsubscribe_price",
            "get_subscriptions",
        ),
        suspected_paths=(
            "/api/realtime/subscriptions/",
            "/api/realtime/subscriptions/unsubscribe/",
        ),
        reason=(
            "Realtime push subscriptions have no WebSocket or polling execution chain "
            "in the current server build."
        ),
        evidence=(
            "No canonical subscription model or WebSocket consumer exists.",
            "Persisting an asset-code list alone would not deliver realtime updates.",
        ),
        governance_rule=(
            "Do not expose storage-only placeholder routes as a working push subscription API."
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
