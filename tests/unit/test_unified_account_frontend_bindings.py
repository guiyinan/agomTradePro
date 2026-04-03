from pathlib import Path


def test_strategy_detail_uses_canonical_account_list_endpoint():
    content = Path("core/templates/strategy/detail.html").read_text(encoding="utf-8")

    assert "/api/account/accounts/" in content
    assert "/api/simulated-trading/accounts/" not in content
    assert "account.account_name" in content


def test_dashboard_main_workflow_uses_canonical_account_shape():
    content = Path("static/js/main-workflow.js").read_text(encoding="utf-8")

    assert "/api/account/accounts/" in content
    assert "/api/simulated-trading/accounts/" not in content
    assert "data.accounts || data.results || []" in content
    assert "account.account_name || account.name" in content
    assert "account.account_id || account.id" in content
