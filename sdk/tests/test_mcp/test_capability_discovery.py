"""Focused tests for the token-bounded MCP capability discovery surface."""

from __future__ import annotations

import asyncio

import pytest

from agomtradepro.exceptions import ConnectionError as SDKConnectionError
from agomtradepro.exceptions import ServerError
from agomtradepro.exceptions import TimeoutError as SDKTimeoutError
from agomtradepro.exceptions import raise_for_status as raise_http_for_status
from agomtradepro_mcp.registry.dispatcher import (
    CAPABILITY_SEARCH_MAX_RESULTS,
    CapabilityDispatcher,
)
from agomtradepro_mcp.registry.loader import CapabilityRegistryLoader


def _build_dispatcher() -> CapabilityDispatcher:
    """Build a read-only dispatcher for discovery tests."""

    return CapabilityDispatcher(
        registry=CapabilityRegistryLoader().build_registry(),
        legacy_tool_caller=lambda _name, _arguments: None,
    )


def test_search_expands_chinese_portfolio_query() -> None:
    dispatcher = _build_dispatcher()

    matches = dispatcher.search(query="查看当前持仓", limit=10)

    keys = {match["capability_key"] for match in matches}
    assert "account.read.account_positions" in keys


def test_search_expands_chinese_macro_query() -> None:
    dispatcher = _build_dispatcher()

    matches = dispatcher.search(query="宏观象限", limit=10)

    keys = {match["capability_key"] for match in matches}
    assert "system.read.regime.current" in keys


def test_search_clamps_result_limit_and_keeps_discovery_payload_compact() -> None:
    dispatcher = _build_dispatcher()

    matches = dispatcher.search(query="", limit=10_000)

    assert len(matches) == CAPABILITY_SEARCH_MAX_RESULTS
    assert all("legacy_tool_names" not in match for match in matches)
    assert all("audit_tags" not in match for match in matches)
    assert all("idempotency_argument_name" not in match for match in matches)


def test_full_schema_keeps_governance_metadata() -> None:
    dispatcher = _build_dispatcher()

    schema = dispatcher.get_schema("system.read.regime.current")

    assert "legacy_tool_names" in schema
    assert "audit_tags" in schema
    assert "idempotency_argument_name" in schema


def test_core_search_reports_effective_bounded_limit(core_only_mcp_server) -> None:
    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_search",
            {"query": "", "limit": 10_000},
        )
    )

    structured = result[1]
    assert structured["limit"] == CAPABILITY_SEARCH_MAX_RESULTS
    assert structured["returned_count"] == CAPABILITY_SEARCH_MAX_RESULTS


def test_bootstrap_returns_domain_index_instead_of_capability_samples(
    core_only_mcp_server,
) -> None:
    result = asyncio.run(core_only_mcp_server.call_tool("agom_bootstrap", {}))

    structured = result[1]
    assert structured["capability_domains"]
    assert structured["discovery"]["search_max_limit"] == CAPABILITY_SEARCH_MAX_RESULTS
    assert "capabilities" not in structured


def test_initialize_instructions_keep_context_reads_on_demand() -> None:
    from agomtradepro_mcp.server import _build_welcome_message

    instructions = _build_welcome_message()

    assert "Do not preload resources or the capability catalog" in instructions
    assert "Only for investment research" in instructions
    assert "terminal.search.user_actions" in instructions
    assert (
        "Read agomtradepro://regime/current and agomtradepro://policy/status first"
        not in instructions
    )


def test_dispatcher_preserves_bounded_upstream_business_block() -> None:
    registry = CapabilityRegistryLoader().build_registry()

    def fail(_name: str, _arguments: dict[str, object]) -> None:
        raise ServerError(
            status_code=503,
            response={
                "code": "decision_runtime_blocked",
                "message": "Decision runtime is blocked pending fresh evidence.",
                "blocked_reason": "decision_runtime_blocked",
                "must_not_use_for_decision": True,
                "internal_members": ["must-not-leak"],
            },
        )

    dispatcher = CapabilityDispatcher(registry=registry, legacy_tool_caller=fail)
    result = dispatcher.call(capability_key="system.read.regime.current", arguments={})

    assert result["error"] == {
        "code": "decision_runtime_blocked",
        "message": "Decision runtime is blocked pending fresh evidence.",
        "upstream_status_code": 503,
        "blocked_reason": "decision_runtime_blocked",
        "must_not_use_for_decision": True,
    }
    assert "must-not-leak" not in str(result)


@pytest.mark.parametrize(
    ("exception", "code", "message"),
    [
        (SDKTimeoutError(), "transport_timeout", "上游服务请求超时，请稍后重试。"),
        (SDKConnectionError(), "transport_connection_failed", "上游服务连接失败，请稍后重试。"),
    ],
)
def test_dispatcher_distinguishes_transport_failures(
    exception: Exception,
    code: str,
    message: str,
) -> None:
    """网络失败保持独立业务码，不能退化为 HTTP unknown。"""

    registry = CapabilityRegistryLoader().build_registry()

    def fail(_name: str, _arguments: dict[str, object]) -> None:
        raise exception

    dispatcher = CapabilityDispatcher(registry=registry, legacy_tool_caller=fail)
    result = dispatcher.call(capability_key="system.read.regime.current", arguments={})

    assert result["error"]["code"] == code
    assert result["error"]["message"] == message
    assert "unknown" not in result["error"]["message"]


def test_dispatcher_preserves_business_metadata_and_redacts_sensitive_values() -> None:
    """业务阻断保留白名单字段，内部敏感内容不进入公开 envelope。"""

    registry = CapabilityRegistryLoader().build_registry()

    def fail(_name: str, _arguments: dict[str, object]) -> None:
        response = {
            "code": "decision_runtime_blocked",
            "message": "决策运行时被阻断，等待新证据。",
            "blocked_reason": "mcp_audit_evidence_pending",
            "must_not_use_for_decision": True,
            "observed_at": "2026-09-24T16:15:00+00:00",
            "freshness_status": "stale",
            "trace_id": "trace-123",
            "changed_at": "2026-09-24T16:10:00+00:00",
            "release_ref": "a" * 40,
            "next_action": "等待管理员完成核查",
            "responsible_role": "系统管理员",
            "internal_trace": "token=secret-value SELECT password FROM users",
        }
        raise ServerError(status_code=503, response=response)

    dispatcher = CapabilityDispatcher(registry=registry, legacy_tool_caller=fail)
    result = dispatcher.call(capability_key="system.read.regime.current", arguments={})

    assert result["error"] == {
        "code": "decision_runtime_blocked",
        "message": "决策运行时被阻断，等待新证据。",
        "upstream_status_code": 503,
        "blocked_reason": "mcp_audit_evidence_pending",
        "must_not_use_for_decision": True,
        "observed_at": "2026-09-24T16:15:00+00:00",
        "freshness_status": "stale",
        "trace_id": "trace-123",
        "changed_at": "2026-09-24T16:10:00+00:00",
        "release_ref": "a" * 40,
        "next_action": "等待管理员完成核查",
        "responsible_role": "系统管理员",
    }
    assert "secret-value" not in str(result)
    assert "SELECT" not in str(result)


def test_raise_for_status_keeps_upstream_code_and_safe_reason() -> None:
    """SDK HTTP errors carry the upstream business code before MCP dispatch."""

    with pytest.raises(ServerError) as raised:
        raise_http_for_status(
            503,
            {
                "code": "mcp_audit_evidence_write_failed",
                "message": "MCP 审计证据写入失败，最终验收被阻断。",
                "blocked_reason": "mcp_audit_evidence_write_failed",
                "must_not_use_for_decision": True,
            },
        )

    assert raised.value.code == "mcp_audit_evidence_write_failed"
    assert raised.value.status_code == 503
    assert raised.value.response["blocked_reason"] == "mcp_audit_evidence_write_failed"


def test_dispatcher_preserves_decision_runtime_block_reason_contract() -> None:
    """生产阻断字段名必须穿透 SDK 和 MCP，不能退化为通用 HTTP 503。"""

    registry = CapabilityRegistryLoader().build_registry()

    def fail(_name: str, _arguments: dict[str, object]) -> None:
        raise_http_for_status(
            503,
            {
                "status": "blocked",
                "block_reason_code": "decision_runtime_blocked",
                "block_reason": "MCP 审计证据写入失败，最终验收被阻断。",
                "must_not_use_for_decision": True,
            },
        )

    dispatcher = CapabilityDispatcher(registry=registry, legacy_tool_caller=fail)
    result = dispatcher.call(capability_key="system.read.regime.current", arguments={})

    assert result["error"] == {
        "code": "decision_runtime_blocked",
        "message": "MCP 审计证据写入失败，最终验收被阻断。",
        "upstream_status_code": 503,
        "blocked_reason": "MCP 审计证据写入失败，最终验收被阻断。",
        "must_not_use_for_decision": True,
    }
