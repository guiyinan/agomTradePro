from types import SimpleNamespace

import pytest


@pytest.mark.django_db
def test_data_center_tui_governance_is_admin_only_and_allow_listed(
    client,
    django_user_model,
    monkeypatch,
):
    regular_user = django_user_model.objects.create_user(
        username="data_center_tui_user",
        password="password",
    )
    admin_user = django_user_model.objects.create_user(
        username="data_center_tui_admin",
        password="password",
        is_staff=True,
    )
    monkeypatch.setattr(
        "apps.data_center.interface.tui_views.load_macro_governance_payload",
        lambda: {"indicator_rows": [], "missing_sync_candidates": []},
    )
    observed_actions = []

    def fake_run(action):
        observed_actions.append(action)
        return {"success": True, "action": action}

    monkeypatch.setattr(
        "apps.data_center.interface.tui_views.run_macro_governance_action",
        fake_run,
    )

    client.force_login(regular_user)
    denied = client.get("/api/data-center/tui/governance/")
    assert denied.status_code == 403

    client.force_login(admin_user)
    overview = client.get("/api/data-center/tui/governance/")
    assert overview.status_code == 200
    assert overview.json()["snapshot"]["indicator_rows"] == []

    invalid = client.post(
        "/api/data-center/tui/governance/",
        {"action": "shell_command"},
        content_type="application/json",
    )
    assert invalid.status_code == 400

    executed = client.post(
        "/api/data-center/tui/governance/",
        {"action": "normalize_units"},
        content_type="application/json",
    )
    assert executed.status_code == 200
    assert observed_actions == ["normalize_units"]


@pytest.mark.django_db
def test_market_thermometer_tui_config_flattens_threshold_patch(
    client,
    django_user_model,
    monkeypatch,
):
    admin_user = django_user_model.objects.create_user(
        username="thermometer_tui_admin",
        password="password",
        is_staff=True,
    )
    current = {
        "short_window": 5,
        "medium_window": 20,
        "long_window": 60,
        "thresholds": {
            "warm_threshold": 40.0,
            "hot_threshold": 60.0,
            "overheat_threshold": 75.0,
            "extreme_threshold": 90.0,
        },
    }
    observed_updates = []

    class FakeUseCase:
        def get(self):
            return SimpleNamespace(to_dict=lambda: current)

        def update(self, **kwargs):
            observed_updates.append(kwargs)
            return SimpleNamespace(to_dict=lambda: {**current, **kwargs})

    monkeypatch.setattr(
        "apps.data_center.interface.tui_views.make_manage_market_thermometer_config_use_case",
        lambda: FakeUseCase(),
    )
    client.force_login(admin_user)

    rejected = client.patch(
        "/api/data-center/tui/market-thermometer/config/",
        {"thresholds": {"warm_threshold": 45}},
        content_type="application/json",
    )
    assert rejected.status_code == 400

    response = client.patch(
        "/api/data-center/tui/market-thermometer/config/",
        {"short_window": 8, "warm_threshold": 45.0},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert observed_updates == [
        {
            "short_window": 8,
            "thresholds": {
                "warm_threshold": 45.0,
                "hot_threshold": 60.0,
                "overheat_threshold": 75.0,
                "extreme_threshold": 90.0,
            },
        }
    ]
