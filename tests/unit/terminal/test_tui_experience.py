"""Task navigation and diagnostic authority contracts, independent of databases."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.terminal.application.tui_errors import TuiScreenNotFoundError
from apps.terminal.application.tui_experience import (
    project_experience,
    validate_experience,
)
from apps.terminal.application.tui_metadata import TuiMetadataValidationError, validate_tui_metadata
from apps.terminal.application.tui_workbench import TuiWorkbenchService
from tests.unit.test_tui_workbench import FakeMetadataRepository, _metadata_payload


def experience():
    return {
        "home_screen_key": "command-center.overview",
        "default_mode": "task",
        "modes": [
            {
                "key": "task",
                "label": "任务模式",
                "entries": [
                    {
                        "key": "today",
                        "kind": "screen",
                        "label": "今日关注",
                        "description": "选择任务",
                        "screen_key": "command-center.overview",
                    },
                ],
            },
            {"key": "professional", "label": "专业模式", "entries": []},
        ],
        "utilities": [
            {
                "key": "resume",
                "kind": "resume",
                "label": "继续上次任务",
                "description": "重新检查权限",
            },
            {
                "key": "admin",
                "kind": "screen",
                "label": "系统治理",
                "description": "管理",
                "screen_key": "admin.screen",
            },
        ],
    }


def test_projection_filters_destinations_without_mutating_shared_source():
    source = experience()
    original = deepcopy(source)
    result = project_experience(
        source,
        all_screen_keys=frozenset({"command-center.overview", "admin.screen"}),
        visible_screen_keys=frozenset({"command-center.overview"}),
    )
    assert [entry["key"] for entry in result["utilities"]] == ["resume"]
    result["modes"][0]["entries"].clear()
    assert source == original


@pytest.mark.parametrize("change", ["unknown", "duplicate", "mode", "extra", "resume_target"])
def test_experience_rejects_invalid_or_dangling_configuration(change):
    payload = experience()
    if change == "unknown":
        payload["home_screen_key"] = "missing"
    if change == "duplicate":
        payload["utilities"][1]["key"] = "resume"
    if change == "mode":
        payload["default_mode"] = "debug"
    if change == "extra":
        payload["utilities"][0]["execute"] = True
    if change == "resume_target":
        payload["utilities"][0]["screen_key"] = "admin.screen"
    with pytest.raises(ValueError):
        validate_experience(payload, frozenset({"command-center.overview", "admin.screen"}))


@pytest.mark.parametrize(
    "identity,allowed",
    [
        ({}, False),
        ({"pk": 1, "is_authenticated": True, "is_active": True}, False),
        ({"pk": 1, "is_authenticated": True, "is_active": True, "is_staff": True}, True),
        ({"pk": 1, "is_authenticated": True, "is_active": True, "rbac_role": "admin"}, True),
        ({"pk": 1, "is_authenticated": True, "is_active": False, "is_staff": True}, False),
        ({"pk": 1, "is_authenticated": False, "is_staff": True}, False),
        ({"is_authenticated": True, "is_active": True, "is_staff": True}, False),
    ],
)
def test_catalog_and_execution_share_trusted_diagnostic_authority(identity, allowed):
    owner_result = {
        "outcome": "partial",
        "stored": None,
        "counts_unavailable": True,
        "confirmed_trade_count": 2,
    }

    class Executor:
        def execute(self, **kwargs):
            return {"status_code": 200, "payload": owner_result}

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(), action_executor=Executor()
    )
    user = SimpleNamespace(**identity)
    catalog = service.get_catalog(user=user)
    assert catalog["diagnostics"]["raw_response_allowed"] is allowed
    envelope = service.run_action(action_key="sample.list", params={}, user=user)
    assert envelope["debug"]["raw_available"] is allowed
    assert envelope["debug"]["raw_response"] == (owner_result if allowed else None)
    assert envelope["outcome"] == "partial"


def test_action_policy_denies_raw_even_for_authorized_admin():
    metadata = _metadata_payload()
    metadata["actions"][0]["raw_debug"] = False

    class Executor:
        def execute(self, **kwargs):
            return {"status_code": 200, "payload": {"value": 1}}

    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(metadata), action_executor=Executor()
    )
    result = service.run_action(
        action_key="sample.list",
        params={},
        user=SimpleNamespace(pk=1, is_authenticated=True, is_active=True, is_staff=True),
    )
    assert result["debug"] == {"raw_available": False, "raw_response": None}


def test_diagnostic_authority_revocation_is_checked_on_each_execution():
    class Executor:
        def execute(self, **kwargs):
            return {"status_code": 200, "payload": {"value": 1}}

    user = SimpleNamespace(
        pk=1,
        is_authenticated=True,
        is_active=True,
        account_profile=SimpleNamespace(rbac_role="admin"),
    )
    service = TuiWorkbenchService(
        metadata_repository=FakeMetadataRepository(), action_executor=Executor()
    )
    assert service.get_catalog(user=user)["diagnostics"]["raw_response_allowed"] is True
    assert (
        service.run_action(action_key="sample.list", params={}, user=user)["debug"]["raw_available"]
        is True
    )
    user.account_profile.rbac_role = "user"
    assert service.get_catalog(user=user)["diagnostics"]["raw_response_allowed"] is False
    result = service.run_action(
        action_key="sample.list", params={"mode": "debug", "role": "admin"}, user=user
    )
    assert result["debug"] == {"raw_available": False, "raw_response": None}


def test_explicit_unknown_bootstrap_never_silently_opens_home():
    service = TuiWorkbenchService(metadata_repository=FakeMetadataRepository())
    with pytest.raises(TuiScreenNotFoundError):
        service.get_bootstrap(requested_screen="unknown.screen")


def test_metadata_validation_rejects_unknown_experience_reference():
    metadata = _metadata_payload()
    metadata["experience"] = experience()
    with pytest.raises(TuiMetadataValidationError, match="unknown screen"):
        validate_tui_metadata(metadata)


def test_metadata_home_must_match_bootstrap_default():
    metadata = _metadata_payload()
    other = deepcopy(metadata["screens"][0])
    other["key"] = "other.screen"
    metadata["screens"].append(other)
    metadata["experience"] = experience()
    metadata["experience"]["home_screen_key"] = "other.screen"
    metadata["experience"]["utilities"] = []
    with pytest.raises(TuiMetadataValidationError, match="default_screen"):
        validate_tui_metadata(metadata)


def test_runtime_cache_token_tracks_experience_helper(monkeypatch):
    from pathlib import Path

    from apps.terminal.infrastructure.tui_metadata_repository import PublishedTuiMetadataRepository

    token = PublishedTuiMetadataRepository._runtime_contract_token
    token.cache_clear()
    original = Path.read_bytes
    try:
        first = token()

        def changed(path):
            data = original(path)
            return (
                data + b"\n# changed experience contract"
                if path.name == "tui_experience.py"
                else data
            )

        monkeypatch.setattr(Path, "read_bytes", changed)
        token.cache_clear()
        assert token() != first
    finally:
        token.cache_clear()


def test_action_metadata_failure_retains_bounded_response(monkeypatch):
    from rest_framework.test import APIRequestFactory, force_authenticate

    from apps.terminal.interface import api_views
    from tests.unit.test_tui_workbench import FakeAuditRepository

    class MissingMetadata:
        def load_published(self, registry_key="default"):
            raise FileNotFoundError("private missing metadata path")

    monkeypatch.setattr(api_views, "get_tui_metadata_repository", MissingMetadata)
    monkeypatch.setattr(api_views, "get_terminal_audit_repository", FakeAuditRepository)

    def unexpected_executor():
        pytest.fail("metadata must be checked before executor setup")

    monkeypatch.setattr(api_views, "get_tui_action_executor", unexpected_executor)
    request = APIRequestFactory().post(
        "/api/tui/actions/sample.list/run/", {"params": {}}, format="json"
    )
    force_authenticate(request, SimpleNamespace(pk=1, is_authenticated=True, is_active=True))
    response = api_views.TuiWorkbenchActionRunView.as_view()(request, action_key="sample.list")
    response.render()
    assert response.status_code == 502
    assert response.data["error_code"] == "tui_action_unavailable"
    assert response.data["recovery_actions"] == []
    assert b"private missing" not in response.content


@pytest.mark.parametrize(
    "screen_key,expected,code",
    [
        ("unknown.screen", 404, "tui_screen_not_found"),
        ("admin.screen", 403, "tui_screen_forbidden"),
    ],
)
def test_bootstrap_http_preserves_explicit_route_error(monkeypatch, screen_key, expected, code):
    from rest_framework.test import APIRequestFactory, force_authenticate

    from apps.terminal.interface import api_views

    metadata = _metadata_payload()
    admin_screen = deepcopy(metadata["screens"][0])
    admin_screen.update(key="admin.screen", audience="admin")
    metadata["screens"].append(admin_screen)
    monkeypatch.setattr(
        api_views, "get_tui_metadata_repository", lambda: FakeMetadataRepository(metadata)
    )
    request = APIRequestFactory().get("/api/tui/bootstrap/", {"screen_key": screen_key})
    force_authenticate(request, SimpleNamespace(pk=1, is_authenticated=True, is_active=True))
    response = api_views.TuiWorkbenchBootstrapView.as_view()(request)
    response.render()
    assert response.status_code == expected
    assert response["Content-Type"].startswith("application/json")
    assert response.data["error_code"] == code
    assert "screen" not in response.data
    assert response.data["recovery_actions"][0]["screen_key"] == metadata["default_screen"]


def test_non_mcp_forbidden_screen_recovers_to_canonical_home(monkeypatch):
    from rest_framework.test import APIRequestFactory, force_authenticate

    from apps.terminal.interface import api_views

    metadata = _metadata_payload()
    admin_screen = deepcopy(metadata["screens"][0])
    admin_screen.update(key="admin.screen", audience="admin")
    metadata["screens"].append(admin_screen)
    monkeypatch.setattr(
        api_views, "get_tui_metadata_repository", lambda: FakeMetadataRepository(metadata)
    )
    request = APIRequestFactory().get("/api/tui/screens/admin.screen/")
    force_authenticate(request, SimpleNamespace(pk=1, is_authenticated=True, is_active=True))
    response = api_views.TuiWorkbenchScreenView.as_view()(request, screen_key="admin.screen")
    assert response.status_code == 403
    assert response.data["recovery_actions"] == [
        {"label": "返回首页", "screen_key": metadata["default_screen"]}
    ]
