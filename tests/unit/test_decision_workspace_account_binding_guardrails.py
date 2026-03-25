from pathlib import Path


def test_decision_workspace_templates_bind_simulated_accounts_and_portfolios():
    templates = [
        Path("core/templates/decision/workspace.html"),
        Path("core/templates/decision/workspace_legacy.html"),
    ]

    for template in templates:
        content = template.read_text(encoding="utf-8")

        assert "/api/simulated-trading/accounts/" in content
        assert "Array.isArray(data.accounts)" in content
        assert "acc.account_name" in content

        assert "/account/api/portfolios/?page_size=100" in content
        assert 'id="modal-portfolio-id"' in content
