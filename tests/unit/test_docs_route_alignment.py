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
    assert "/market-data/providers/" in content
    assert "/api/decision/workspace/recommendations/" in content
    assert "/api/decision/funnel/context/" in content


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
