from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_alpha_trigger_list_route_is_canonical_everywhere() -> None:
    assert "/alpha-triggers/list/" not in _read("core/context_processors.py")
    assert "/alpha-triggers/list/" not in _read("docs/user/decision-platform-guide.md")
    assert "/alpha-triggers/" in _read("docs/user/decision-platform-guide.md")


def test_current_docs_do_not_reference_removed_policy_page_routes() -> None:
    content = _read("docs/testing/api/API_REFERENCE.md")
    assert "/policy/events/create/" not in content
    assert "/api/decision-workflow/check-beta-gate/" not in content
    assert "/api/decision-workflow/check-quota/" not in content
    assert "/api/decision-workflow/check-cooldown/" not in content
    development_content = _read("docs/development/decision-platform.md")
    assert "/api/decision-workflow/check-beta-gate/" not in development_content
    assert "/api/decision-workflow/check-quota/" not in development_content
    assert "/api/decision-workflow/check-cooldown/" not in development_content


def test_current_docs_use_canonical_market_data_and_decision_routes() -> None:
    content = _read("docs/testing/api/API_REFERENCE.md")
    development_content = _read("docs/development/unified-financial-datasource-registry.md")
    assert "`/market-data/providers/`" not in content
    assert "`/market-data/providers/`" not in development_content
    assert "/api/market-data/" not in content
    assert "/macro/datasources/" not in content
    assert "/macro/datasources/" not in development_content
    assert "/data-center/monitor/" in content
    assert "/data-center/monitor/" in development_content
    assert "/api/decision/workspace/recommendations/" in content
    assert "/api/decision/funnel/context/" in content
    assert "rotation_data_source" in content
    assert "rotation_is_stale" in content
    assert "rotation_warning_message" in content
    assert "rotation_signal_date" in content


def test_sdk_and_mcp_guides_use_current_token_and_profile_paths() -> None:
    for path in [
        "docs/sdk/quickstart.md",
        "docs/sdk/smoke_test.md",
        "docs/mcp/mcp_guide.md",
    ]:
        content = _read(path)
        assert "rest_framework.authtoken.models.Token" not in content
        assert "UserAccessTokenModel" in content

    mcp_guide = _read("docs/mcp/mcp_guide.md")
    assert "account/api/profile/" not in mcp_guide
    assert "/api/account/profile/" in mcp_guide


def test_sdk_and_mcp_guides_document_decision_funnel_freshness_metadata() -> None:
    for path in [
        "docs/sdk/quickstart.md",
        "docs/sdk/api_reference.md",
        "docs/mcp/mcp_guide.md",
        "sdk/README.md",
        "docs/development/api-mcp-sdk-alignment-2026-03-14.md",
    ]:
        content = _read(path)
        assert "rotation_data_source" in content
        assert "rotation_is_stale" in content
        assert "rotation_warning_message" in content
        assert "rotation_signal_date" in content


def test_mcp_guide_contains_canonical_funnel_context_example() -> None:
    content = _read("docs/mcp/mcp_guide.md")
    assert "Canonical response example for `decision_workflow_get_funnel_context`" in content
    assert '"step3_sectors"' in content
    assert '"step3_status": "fallback"' in content
    assert '"rotation_data_source": "stored_signal_fallback"' in content
    assert '"rotation_is_stale": true' in content
    assert "Interpretation rule for agents" in content


def test_live_docs_use_canonical_decision_workspace_entry_contract() -> None:
    for path in [
        "docs/mcp/mcp_guide.md",
        "docs/development/decision-unified-workflow.md",
        "docs/archive/completed/wp3/wp3-quick-integration.md",
    ]:
        content = _read(path)
        assert "/decision/workspace/?execute_request=" not in content
        assert "asset_code=${assetCode}&direction=${direction}" not in content

    mcp_guide = _read("docs/mcp/mcp_guide.md")
    assert "user_action_label" in mcp_guide
    assert "source`、`security_code`、`step`、`account_id`、`action`" in mcp_guide


def test_development_docs_include_api_change_sync_checklist() -> None:
    index_doc = _read("docs/INDEX.md")
    guardrails = _read("docs/development/engineering-guardrails.md")
    quick_reference = _read("docs/development/quick-reference.md")
    outsourcing_guidelines = _read("docs/development/outsourcing-work-guidelines.md")

    assert "API 改动同步门禁" in guardrails
    assert "是否已同步 SDK / MCP / OpenAPI / 文档 / 用户提示" in guardrails
    assert "python manage.py spectacular --file schema.yml" in guardrails
    assert "engineering-guardrails.md" in index_doc
    assert "API 改动同步检查" in index_doc
    assert "API 改动同步检查" in quick_reference
    assert "pytest -q tests/unit/test_docs_route_alignment.py" in quick_reference
    assert "API 改动附加门禁" in outsourcing_guidelines
    assert "SDK 调用层与示例文档" in outsourcing_guidelines
    assert "MCP 工具返回结构与示例文档" in outsourcing_guidelines
    assert "docs/development/engineering-guardrails.md" in outsourcing_guidelines
