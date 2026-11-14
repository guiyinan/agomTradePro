"""Account action result scope shared by TUI execution and projection."""

from __future__ import annotations

from collections.abc import Mapping

_SCOPED_ACCOUNT_ACTIONS: frozenset[str] = frozenset(
    {
        "simulated-trading.orders",
        "simulated-trading.order-fills",
        "simulated-trading.order-decisions",
        "simulated-trading.order-decision-apply",
        "simulated-trading.order-cancel",
        "simulated-trading.order-match",
        "simulated-trading.order-preview",
        "simulated-trading.order-confirm",
        "simulated-trading.order-by-key",
        "simulated-trading.order-entry-orders",
        "rebalance-plan.order-confirm",
        "rebalance-plan.order-by-key",
        "simulated-trading.holding-disclosures",
        "simulated-trading.corporate-action-consent-prepare",
        "simulated-trading.corporate-action-consent-confirm",
        "simulated-trading.corporate-action-consent-withdraw-prepare",
        "simulated-trading.corporate-action-consent-withdraw",
        "simulated-trading.corporate-action-workflow-read",
        "simulated-trading.corporate-action-workflow-events",
        "simulated-trading.corporate-action-workflow-audit-receipts",
        "simulated-trading.corporate-action-workflow-prepare",
        "simulated-trading.corporate-action-workflow-confirm",
        "simulated-trading.corporate-action-workflow-refresh",
    }
)


def requires_account_result_scope(action_key: str) -> bool:
    """Keep exact request scope, strict transport status and business outcomes."""

    return action_key in _SCOPED_ACCOUNT_ACTIONS


def continuation_public_account_fields(
    *,
    action_key: str,
    payload: Mapping[str, object],
    continuation_input: Mapping[str, object],
    requested_params: Mapping[str, object] | None,
) -> frozenset[str] | None:
    """Treat only a verified owner path as public, never its protected credential.

    A public account ID may equal an ordinary grant version. It is not a secret
    preparation token, but must match request, response and continuation exactly
    before the executor stores a handoff for this account.
    """
    if action_key not in {
        "simulated-trading.corporate-action-consent-prepare",
        "simulated-trading.corporate-action-consent-withdraw-prepare",
        "simulated-trading.corporate-action-workflow-prepare",
    }:
        return frozenset()
    account_id = payload.get("account_id")
    requested_id = requested_params.get("account_id") if requested_params is not None else None
    if (
        type(account_id) is not int
        or account_id <= 0
        or type(requested_id) not in {int, str}
        or str(requested_id) != str(account_id)
        or type(continuation_input.get("account_id")) is not str
        or continuation_input.get("account_id") != str(account_id)
    ):
        return None
    return frozenset({"account_id"})


def continuation_secret_values(
    action_key: str,
    payload: Mapping[str, object],
    continuation_input: Mapping[str, object],
    requested_params: Mapping[str, object] | None,
    field_map: Mapping[str, object],
    readback_scope: set[str],
) -> set[str] | None:
    """Exclude only validated public path/readback fields from credential leak checks."""
    public_fields = continuation_public_account_fields(
        action_key=action_key,
        payload=payload,
        continuation_input=continuation_input,
        requested_params=requested_params,
    )
    if public_fields is None:
        return None
    secrets: set[str] = set()
    for key, value in continuation_input.items():
        mapped = field_map.get(key)
        if type(value) is not str or type(mapped) is not str:
            return None
        if value and mapped not in readback_scope and mapped not in public_fields:
            secrets.add(value)
    return secrets
