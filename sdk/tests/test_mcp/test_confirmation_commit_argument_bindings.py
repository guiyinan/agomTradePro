"""Regression tests for frozen MCP preview-to-commit argument bindings."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import pytest

from agomtradepro_mcp.registry.dispatcher import CapabilityDispatcher
from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader
from agomtradepro_mcp.registry.manifest import CapabilityManifest, CapabilityManifestValidationError


def _manifest(bindings: object = None) -> CapabilityManifest:
    """Build a test manifest with an optional integer-array binding."""
    mapping = {"account_ids": "resolved_account_ids"} if bindings is None else cast(Any, bindings)
    return CapabilityManifest(
        capability_key="test.freeze_scope",
        title="Freeze scope",
        summary="Preview then confirm a scope.",
        description="Test-only binding manifest.",
        owner_app="test",
        risk_level="high",
        executor_kind="internal_handler",
        executor_ref="freeze_scope",
        input_schema={
            "type": "object",
            "properties": {
                "account_ids": {"type": ["array", "null"], "items": {"type": "integer"}},
                "idempotency_key": {"type": "string"},
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "resolved_account_ids": {"type": "array", "items": {"type": "integer"}},
            },
        },
        requires_confirmation=True,
        confirmation_preview_arguments={"preview_only": True},
        confirmation_commit_arguments={"preview_only": False},
        confirmation_commit_argument_bindings=mapping,
        idempotency="required",
    )


def _fingerprint_manifest() -> CapabilityManifest:
    """Build a manifest with the two bounded preview fingerprint bindings."""

    manifest = _manifest({})
    inputs = deepcopy(manifest.input_schema)
    outputs = deepcopy(manifest.output_schema)
    input_properties = inputs["properties"]
    output_properties = outputs["properties"]
    fingerprint_schema = {"type": "string", "minLength": 1, "maxLength": 128}
    for field_name in ("expected_fact_set_fingerprint", "expected_balance_fingerprint"):
        input_properties[field_name] = deepcopy(fingerprint_schema)
        output_properties[field_name] = deepcopy(fingerprint_schema)
    return replace(
        manifest,
        input_schema=inputs,
        output_schema=outputs,
        confirmation_commit_argument_bindings={
            "expected_fact_set_fingerprint": "expected_fact_set_fingerprint",
            "expected_balance_fingerprint": "expected_balance_fingerprint",
        },
    )


def _fingerprint_dispatcher(
    preview_values: dict[str, Any],
    committed: list[dict[str, Any]],
) -> CapabilityDispatcher:
    """Create a dispatcher that freezes exactly two preview-derived strings."""

    manifest = _fingerprint_manifest()

    def _call(_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments.get("preview_only") is True:
            return deepcopy(preview_values)
        committed.append(deepcopy(arguments))
        return {"success": True}

    return CapabilityDispatcher(
        registry={manifest.capability_key: manifest},
        legacy_tool_caller=lambda _name, _arguments: {},
        internal_handler_caller=_call,
        audit_logger=_audit(),
        role_provider=lambda: "staff",
    )


def _audit() -> object:
    """Return an inert audit logger for dispatcher contract tests."""
    return type(
        "_Audit",
        (),
        {"log_governed_capability_event": staticmethod(lambda **_kwargs: "test-audit")},
    )()


def _account(account_id: int, *, auto_enabled: bool = True) -> dict[str, Any]:
    """Return one canonical account-list row."""
    return {
        "account_id": account_id,
        "account_name": f"Sim {account_id}",
        "account_type": "simulated",
        "is_active": True,
        "auto_trading_enabled": auto_enabled,
    }


def _scope_dispatcher(
    envelope: object, monkeypatch: pytest.MonkeyPatch
) -> tuple[CapabilityDispatcher, dict[str, Any], Any]:
    """Run the real scope handler behind a dispatcher with an in-memory SDK envelope."""
    import agomtradepro
    import agomtradepro_mcp.registry.runtime_handlers.owners.simulated_trading as runtime_module
    from agomtradepro_mcp.registry.runtime_handlers.owners.simulated_trading import (
        _internal_handler_trading_start_simulated_auto_trading,
    )

    fake_client = SimpleNamespace(
        simulated_trading=SimpleNamespace(
            list_accounts_envelope=lambda **_kwargs: envelope,
            get_account=lambda account_id: _account(account_id),
        )
    )
    monkeypatch.setattr(agomtradepro, "AgomTradeProClient", lambda: fake_client)
    manifest = _manifest()
    dispatcher = CapabilityDispatcher(
        registry={manifest.capability_key: manifest},
        legacy_tool_caller=lambda _name, _arguments: {},
        internal_handler_caller=lambda _name, arguments: _internal_handler_trading_start_simulated_auto_trading(
            **arguments
        ),
        audit_logger=_audit(),
        role_provider=lambda: "staff",
    )
    response = dispatcher.call(
        capability_key=manifest.capability_key,
        arguments={"account_ids": None, "idempotency_key": "frozen-scope"},
    )
    return dispatcher, response, runtime_module


def _dispatcher(preview_value: object, committed: list[dict[str, Any]]) -> CapabilityDispatcher:
    """Create a small dispatcher for preview/request mutation isolation."""

    def _call(_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments.get("preview_only") is True:
            return {"resolved_account_ids": preview_value}
        committed.append(deepcopy(arguments))
        return {"success": True}

    manifest = _manifest()
    return CapabilityDispatcher(
        registry={manifest.capability_key: manifest},
        legacy_tool_caller=lambda _name, _arguments: {},
        internal_handler_caller=_call,
        audit_logger=_audit(),
        role_provider=lambda: "staff",
    )


def test_fingerprint_bindings_freeze_preview_values_into_commit() -> None:
    """Both non-empty preview fingerprints are bound without exposing mutable state."""

    fact_value = "fact-set-v1"
    balance_value = "balance-v1"
    committed: list[dict[str, Any]] = []
    dispatcher = _fingerprint_dispatcher(
        {
            "expected_fact_set_fingerprint": fact_value,
            "expected_balance_fingerprint": balance_value,
        },
        committed,
    )
    preview = dispatcher.call(
        capability_key="test.freeze_scope",
        arguments={"idempotency_key": "fingerprint-context"},
    )
    assert preview["status"] == "confirmation_required"
    preview["preview_result"]["expected_fact_set_fingerprint"] = "caller-edit"
    result = dispatcher.resume_confirmation(
        confirmation_token=preview["confirmation_token"], approve=True
    )
    assert result["status"] == "completed"
    assert committed[0]["expected_fact_set_fingerprint"] == fact_value
    assert committed[0]["expected_balance_fingerprint"] == balance_value
    assert committed[0]["preview_only"] is False


@pytest.mark.parametrize("invalid_value", ["", None, 7])
def test_empty_or_untyped_preview_fingerprints_fail_before_confirmation(
    invalid_value: object,
) -> None:
    """The string binding rejects empty and non-string context before storing a token."""

    committed: list[dict[str, Any]] = []
    dispatcher = _fingerprint_dispatcher(
        {
            "expected_fact_set_fingerprint": invalid_value,
            "expected_balance_fingerprint": "balance-v1",
        },
        committed,
    )
    response = dispatcher.call(
        capability_key="test.freeze_scope",
        arguments={"idempotency_key": "invalid-fingerprint"},
    )
    assert response["status"] == "error"
    assert response["error"]["code"] == "capability_preview_failed"
    assert "confirmation_token" not in response


def test_loader_rejects_unbounded_fingerprint_bindings() -> None:
    """Only the exact bounded fingerprint schema can drive a commit argument."""

    manifest = _fingerprint_manifest()
    input_schema = deepcopy(manifest.input_schema)
    input_schema["properties"]["expected_fact_set_fingerprint"]["maxLength"] = 4096
    invalid = replace(manifest, input_schema=input_schema)
    with pytest.raises(CapabilityManifestValidationError):
        CapabilityRegistryLoader(module_paths=()).validate_manifests([invalid])


def test_preview_and_request_mutation_cannot_change_pending_commit() -> None:
    """Returned preview edits and caller edits cannot mutate frozen pending IDs."""
    committed: list[dict[str, Any]] = []
    dispatcher = _dispatcher([7, 8], committed)
    request: dict[str, Any] = {"account_ids": None, "idempotency_key": "scope-1"}
    preview = dispatcher.call(capability_key="test.freeze_scope", arguments=request)
    assert preview["status"] == "confirmation_required"
    preview["preview_result"]["resolved_account_ids"][:] = [999]
    request["account_ids"] = [99]
    result = dispatcher.resume_confirmation(
        confirmation_token=preview["confirmation_token"], approve=True
    )
    assert result["status"] == "completed"
    assert committed[0]["account_ids"] == [7, 8]
    assert committed[0]["preview_only"] is False
    manifest = dispatcher._registry["test.freeze_scope"]
    assert "confirmation_commit_argument_bindings" not in dispatcher.get_schema(
        manifest.capability_key
    )
    assert "confirmation_commit_argument_bindings" not in manifest.to_discovery_dict()
    assert "confirmation_commit_argument_bindings" not in manifest.to_summary_dict()


@pytest.mark.parametrize("preview_value", [None, (), "8", [8, True], [None]])
def test_invalid_derived_values_fail_before_token_or_pending(preview_value: object) -> None:
    """Wrong derived list type or elements cannot create a pending confirmation."""
    dispatcher = _dispatcher(preview_value, [])
    response = dispatcher.call(
        capability_key="test.freeze_scope",
        arguments={"account_ids": None, "idempotency_key": "invalid-scope"},
    )
    assert response["status"] == "error"
    assert response["error"]["code"] == "capability_preview_failed"
    assert "confirmation_token" not in response
    assert dispatcher._pending_confirmations == {}
    assert dispatcher._idempotency_records == {}


@pytest.mark.parametrize(
    "envelope",
    [
        {},
        {"success": True, "accounts": []},
        {"success": True, "count": 0},
        {"success": False, "count": 0, "accounts": []},
        {"success": True, "count": True, "accounts": []},
        {"success": True, "count": 1, "accounts": []},
        {"success": True, "count": 2, "accounts": [_account(7), _account(7)]},
        {"success": True, "count": 1, "accounts": [{**_account(7), "auto_trading_enabled": None}]},
        {"success": True, "count": 1, "accounts": [{**_account(7), "account_id": True}]},
    ],
    ids=[
        "missing",
        "missing-count",
        "missing-accounts",
        "failed",
        "bool-count",
        "count-mismatch",
        "duplicate",
        "bad-eligibility",
        "bool-id",
    ],
)
def test_bad_envelope_or_row_fails_without_token(
    envelope: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every list row and count is validated before pending state is stored."""
    dispatcher, response, _runtime = _scope_dispatcher(envelope, monkeypatch)
    assert response["status"] == "error"
    assert response["error"]["code"] == "capability_preview_failed"
    assert "confirmation_token" not in response
    assert dispatcher._pending_confirmations == {}
    assert dispatcher._idempotency_records == {}


def test_complete_large_source_freezes_only_resolved_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """A complete >10,000-row source is allowed when the resolved commit set fits."""
    rows = [_account(i, auto_enabled=False) for i in range(1_000, 21_000)]
    rows.extend([_account(7), _account(8)])
    envelope: dict[str, Any] = {"success": True, "count": len(rows), "accounts": rows}
    dispatcher, preview, runtime_module = _scope_dispatcher(envelope, monkeypatch)
    assert preview["status"] == "confirmation_required"
    assert preview["preview_result"]["resolved_account_ids"] == [7, 8]
    summary = preview["preview_result"]["account_scope_summary"]
    assert summary["source_account_count"] == 20_002
    assert summary["resolved_account_count"] == 2
    committed: list[dict[str, Any]] = []
    monkeypatch.setattr(
        runtime_module,
        "_call_registered_tool",
        lambda _name, arguments: committed.append(deepcopy(arguments)) or {"success": True},
    )
    rows.append(_account(30_000))
    result = dispatcher.resume_confirmation(
        confirmation_token=preview["confirmation_token"], approve=True
    )
    assert result["status"] == "completed"
    assert committed[0] == {"trade_date": None, "account_ids": [7, 8]}


def test_real_owner_manifest_freezes_default_scope_against_later_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A None scope commits the accounts resolved by the real preview only."""
    import agomtradepro
    from agomtradepro_mcp.registry.dispatcher import CapabilityDispatcher
    from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader
    from agomtradepro_mcp.registry.runtime_handlers.owners import (
        simulated_trading as runtime_module,
    )
    from agomtradepro_mcp.registry.runtime_handlers.registry import OWNER_GOVERNED_HANDLERS

    loader = CapabilityRegistryLoader(
        module_paths=(
            "agomtradepro_mcp.registry.modules.owners.simulated_trading_write_capabilities",
        )
    )
    manifest = next(
        item
        for item in loader.load_manifests()
        if item.capability_key == "trading.start.simulated_auto_trading"
    )
    accounts = [_account(7), _account(8)]

    def list_accounts(**_kwargs: object) -> list[dict[str, Any]]:
        return deepcopy(accounts)

    def list_accounts_envelope(**_kwargs: object) -> dict[str, Any]:
        rows = deepcopy(accounts)
        return {"success": True, "count": len(rows), "accounts": rows}

    fake_client = SimpleNamespace(
        simulated_trading=SimpleNamespace(
            list_accounts=list_accounts,
            list_accounts_envelope=list_accounts_envelope,
            get_account=lambda account_id: _account(account_id),
        )
    )
    monkeypatch.setattr(agomtradepro, "AgomTradeProClient", lambda: fake_client)
    committed: list[dict[str, Any]] = []
    monkeypatch.setattr(
        runtime_module,
        "_call_registered_tool",
        lambda _name, arguments: committed.append(deepcopy(arguments)) or {"success": True},
    )
    handler = OWNER_GOVERNED_HANDLERS[manifest.executor_ref]
    dispatcher = CapabilityDispatcher(
        registry={manifest.capability_key: manifest},
        legacy_tool_caller=lambda _name, _arguments: {},
        internal_handler_caller=lambda _name, arguments: handler(**arguments),
        audit_logger=_audit(),
        role_provider=lambda: "staff",
    )

    preview = dispatcher.call(
        capability_key=manifest.capability_key,
        arguments={"trade_date": None, "account_ids": None, "idempotency_key": "real-frozen-scope"},
    )
    assert preview["status"] == "confirmation_required"
    accounts.append(_account(9))
    result = dispatcher.resume_confirmation(
        confirmation_token=preview["confirmation_token"],
        approve=True,
    )

    assert result["status"] == "completed"
    assert committed[0] == {"trade_date": None, "account_ids": [7, 8]}


def test_loader_rejects_unknown_fields_and_callable_values() -> None:
    """Only plain mappings to known optional integer arrays are accepted."""
    loader = CapabilityRegistryLoader(module_paths=())
    for manifest in (
        _manifest({"unknown": "resolved_account_ids"}),
        _manifest({"account_ids": "unknown"}),
        _manifest({"account_ids": lambda _value: [7]}),
    ):
        with pytest.raises(CapabilityManifestValidationError):
            loader.validate_manifests([manifest])
