"""Transport coverage for workbench requests to same-process Django views."""

from types import SimpleNamespace
from unittest.mock import patch

from django.http import HttpRequest, JsonResponse

from apps.terminal.infrastructure.tui_adapters import TuiInternalActionExecutor


def test_get_resolves_path_and_keeps_fixed_and_action_query_parameters() -> None:
    def account_list(request: HttpRequest) -> JsonResponse:
        return JsonResponse({"query": dict(request.GET)})

    with patch(
        "apps.terminal.infrastructure.tui_adapters.resolve",
        return_value=SimpleNamespace(func=account_list, args=(), kwargs={}),
    ) as resolve:
        result = TuiInternalActionExecutor().execute(
            method="GET",
            endpoint="/api/simulated-trading/accounts/?active_only=true&account_type=simulated",
            params={"page": 2},
            body={},
            user=SimpleNamespace(),
        )

    resolve.assert_called_once_with("/api/simulated-trading/accounts/")
    assert result == {
        "status_code": 200,
        "payload": {
            "query": {"active_only": ["true"], "account_type": ["simulated"], "page": ["2"]}
        },
    }
