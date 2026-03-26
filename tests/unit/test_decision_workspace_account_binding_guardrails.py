from pathlib import Path


def test_decision_workspace_templates_bind_simulated_accounts_and_portfolios():
    templates = [Path("core/templates/decision/workspace.html")]

    for template in templates:
        content = template.read_text(encoding="utf-8")

        assert "/api/simulated-trading/accounts/" in content
        assert "Array.isArray(data.accounts)" in content
        assert "acc.account_name" in content

        assert "/account/api/portfolios/?page_size=100" in content
        assert 'id="modal-portfolio-id"' in content

    main_workspace = templates[0].read_text(encoding="utf-8")
    assert "active_only=false" in main_workspace
    assert 'id="workspace-account-selector"' in main_workspace
    assert "handleWorkspaceAccountChange()" in main_workspace
    assert "initializeDecisionWorkspace" in main_workspace
    assert "refreshWorkspaceDecisionLists()" in main_workspace
    assert 'class="workspace-shell"' in main_workspace
    assert 'id="workspace-position-list"' in main_workspace
    assert "loadWorkspaceAccountSnapshot()" in main_workspace
    assert 'hx-include="#workspace-account-selector"' in main_workspace
    assert "account_id: getSelectedWorkspaceAccountId()" in main_workspace
    assert "initializeLegacyWorkspace" not in main_workspace
    assert "currentTab" not in main_workspace


def test_decision_workspace_step_templates_show_account_context_as_system_level():
    templates = [
        Path("core/templates/decision/steps/environment.html"),
        Path("core/templates/decision/steps/direction.html"),
        Path("core/templates/decision/steps/sector.html"),
    ]

    for template in templates:
        content = template.read_text(encoding="utf-8")
        assert "data-workspace-account-name" in content
        assert "系统级分析" in content
