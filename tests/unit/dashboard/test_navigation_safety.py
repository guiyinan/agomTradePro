"""Safety coverage for Dashboard Decision Workspace deep links."""

import pytest

from apps.dashboard.application.navigation import build_decision_workspace_url


def test_decision_workspace_url_preserves_canonical_parameter_order() -> None:
    assert build_decision_workspace_url(
        source="dashboard-workflow",
        security_code=" 000001.sz ",
        step=4,
        account_id="21",
        action="watch",
    ) == (
        "/decision/workspace/?source=dashboard-workflow&security_code=000001.SZ"
        "&step=4&account_id=21&action=WATCH"
    )


@pytest.mark.parametrize("value", [True, 0, -1, "", "abc", "1.5", "2147483648"])
def test_invalid_account_id_is_omitted_without_breaking_other_parameters(
    value: object,
) -> None:
    url = build_decision_workspace_url(
        source="dashboard-exit",
        security_code="000001.SZ",
        account_id=value,
    )

    assert url == ("/decision/workspace/?source=dashboard-exit&security_code=000001.SZ")


@pytest.mark.parametrize("value", [True, 0, -1, "", "abc", "1.5", 101])
def test_invalid_step_is_omitted(value: object) -> None:
    assert (
        build_decision_workspace_url(
            security_code="000001.SZ",
            step=value,
        )
        == "/decision/workspace/?security_code=000001.SZ"
    )


def test_invalid_tokens_are_omitted_instead_of_entering_navigation() -> None:
    assert (
        build_decision_workspace_url(
            source="dashboard\nsecret",
            security_code="bad code",
            action="sell\r\nnext",
        )
        == "/decision/workspace/"
    )
