import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.beta_gate.infrastructure.models import GateConfigModel, GateDecisionModel
from apps.events.infrastructure.event_store import StoredEventModel


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_user(db):
    return get_user_model().objects.create_user(
        username="beta_gate_user",
        password="testpass123",
        email="beta-gate@example.com",
    )


@pytest.fixture
def authenticated_client(api_client, auth_user):
    api_client.force_authenticate(user=auth_user)
    return api_client


@pytest.fixture
def staff_user(db):
    return get_user_model().objects.create_user(
        username="beta_gate_staff",
        password="testpass123",
        email="beta-gate-staff@example.com",
        is_staff=True,
    )


@pytest.fixture
def staff_client(api_client, staff_user):
    api_client.force_authenticate(user=staff_user)
    return api_client


@pytest.mark.django_db
def test_beta_gate_config_catalog_success_contract(authenticated_client):
    repository = type(
        "Repository",
        (),
        {"get_all_active": lambda self: []},
    )()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "apps.beta_gate.interface.views.get_beta_gate_config_repository",
            lambda: repository,
        )
        response = authenticated_client.get("/api/beta-gate/configs/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "success": True,
        "count": 0,
        "results": [],
    }


@pytest.mark.django_db
def test_beta_gate_api_root_contract(authenticated_client):
    response = authenticated_client.get("/api/beta-gate/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload["endpoints"]["configs"] == "/api/beta-gate/configs/"
    assert payload["endpoints"]["test"] == "/api/beta-gate/test/"


@pytest.mark.django_db
def test_beta_gate_decisions_reject_invalid_days(authenticated_client):
    response = authenticated_client.get("/api/beta-gate/decisions/?days=bad")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "days must be an integer"


@pytest.mark.django_db
def test_beta_gate_universe_rejects_invalid_limit(authenticated_client):
    response = authenticated_client.get("/api/beta-gate/universe/?limit=bad")

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "limit must be an integer"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("regime_confidence", "not-a-number"),
        ("regime_confidence", "NaN"),
        ("policy_level", 4),
    ),
)
def test_beta_gate_batch_evaluation_rejects_invalid_input(
    authenticated_client,
    field,
    value,
):
    payload = {
        "asset_codes": ["000001.SH"],
        "asset_class": "equity",
        "current_regime": "Recovery",
        "regime_confidence": 0.6,
        "policy_level": 0,
        "risk_profile": "balanced",
    }
    payload[field] = value

    response = authenticated_client.post(
        "/api/beta-gate/test/",
        payload,
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["success"] is False
    assert field in response.json()["errors"]


@pytest.mark.django_db
def test_beta_gate_batch_evaluation_rejects_unknown_fields(authenticated_client):
    response = authenticated_client.post(
        "/api/beta-gate/test/",
        {
            "asset_codes": ["000001.SH"],
            "asset_class": "equity",
            "current_regime": "Recovery",
            "regime_confidence": 0.6,
            "policy_level": 0,
            "risk_profile": "balanced",
            "config_id": "must-not-be-accepted",
        },
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["success"] is False
    assert "Unknown fields: config_id" in str(response.json()["errors"])


@pytest.mark.django_db
def test_beta_gate_batch_evaluation_uses_requested_profile_without_persistence(
    authenticated_client,
):
    GateConfigModel.objects.create(
        config_id="conservative-first",
        risk_profile=GateConfigModel.CONSERVATIVE,
        version=10,
        is_active=True,
        regime_constraints={
            "allowed_regimes": ["Recovery"],
            "min_confidence": 0.9,
        },
        policy_constraints={"max_allowed_level": 1, "veto_on_p3": True},
        portfolio_constraints={
            "max_total_position_pct": 80.0,
            "max_single_position_pct": 15.0,
        },
    )
    GateConfigModel.objects.create(
        config_id="aggressive-requested",
        risk_profile=GateConfigModel.AGGRESSIVE,
        version=1,
        is_active=True,
        regime_constraints={
            "allowed_regimes": ["Recovery"],
            "min_confidence": 0.3,
        },
        policy_constraints={"max_allowed_level": 2, "veto_on_p3": False},
        portfolio_constraints={
            "max_total_position_pct": 95.0,
            "max_single_position_pct": 25.0,
        },
    )
    before = {
        "configs": GateConfigModel.objects.count(),
        "decisions": GateDecisionModel.objects.count(),
        "events": StoredEventModel.objects.count(),
    }

    response = authenticated_client.post(
        "/api/beta-gate/test/",
        {
            "asset_codes": ["000001.SH", "000300.SH"],
            "asset_class": "equity",
            "current_regime": "Recovery",
            "regime_confidence": 0.5,
            "policy_level": 0,
            "risk_profile": "aggressive",
        },
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["config"] == {
        "config_id": "aggressive-requested",
        "risk_profile": "aggressive",
        "version": 1,
    }
    assert payload["query"] == {
        "asset_codes": ["000001.SH", "000300.SH"],
        "asset_class": "equity",
        "current_regime": "Recovery",
        "regime_confidence": 0.5,
        "policy_level": 0,
        "risk_profile": "aggressive",
    }
    assert payload["summary"] == {
        "total": 2,
        "passed": 2,
        "blocked": 0,
        "pass_rate": 1.0,
        "blocked_by_reason": {},
    }
    assert len(payload["results"]) == 2
    assert all(result["passed"] is True for result in payload["results"])
    assert {
        "configs": GateConfigModel.objects.count(),
        "decisions": GateDecisionModel.objects.count(),
        "events": StoredEventModel.objects.count(),
    } == before


@pytest.mark.django_db
def test_beta_gate_batch_evaluation_uses_stable_requested_profile_default(
    authenticated_client,
):
    response = authenticated_client.post(
        "/api/beta-gate/test/",
        {
            "asset_codes": ["000001.SH"],
            "asset_class": "equity",
            "current_regime": "Recovery",
            "regime_confidence": 0.6,
            "policy_level": 0,
            "risk_profile": "conservative",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["config"] == {
        "config_id": "default-conservative",
        "risk_profile": "conservative",
        "version": 1,
    }
    assert GateConfigModel.objects.count() == 0
    assert GateDecisionModel.objects.count() == 0
    assert StoredEventModel.objects.count() == 0


@pytest.mark.django_db
def test_beta_gate_version_compare_is_authenticated_and_read_only(
    authenticated_client,
):
    GateConfigModel.objects.create(
        config_id="balanced-v1",
        risk_profile=GateConfigModel.BALANCED,
        version=1,
        is_active=False,
        regime_constraints={"allowed_regimes": ["Recovery"]},
        policy_constraints={"max_allowed_level": 2},
        portfolio_constraints={"max_total_position_pct": 80.0},
    )
    GateConfigModel.objects.create(
        config_id="balanced-v2",
        risk_profile=GateConfigModel.BALANCED,
        version=2,
        is_active=True,
        regime_constraints={"allowed_regimes": ["Recovery", "Deflation"]},
        policy_constraints={"max_allowed_level": 1},
        portfolio_constraints={"max_total_position_pct": 70.0},
    )
    before = list(
        GateConfigModel.objects.order_by("config_id").values(
            "config_id",
            "version",
            "is_active",
            "effective_date",
            "updated_at",
        )
    )

    unauthenticated = APIClient().get(
        "/api/beta-gate/version/compare/?version1=balanced-v1&version2=balanced-v2"
    )
    response = authenticated_client.get(
        "/api/beta-gate/version/compare/?version1=balanced-v1&version2=balanced-v2"
    )

    assert unauthenticated.status_code in {401, 403}
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["config1"]["config_id"] == "balanced-v1"
    assert payload["config2"]["config_id"] == "balanced-v2"
    assert {item["field"] for item in payload["differences"]} >= {
        "is_active",
        "regime_constraints",
        "policy_constraints",
        "portfolio_constraints",
    }
    assert list(
        GateConfigModel.objects.order_by("config_id").values(
            "config_id",
            "version",
            "is_active",
            "effective_date",
            "updated_at",
        )
    ) == before


@pytest.mark.django_db
def test_beta_gate_rollback_rejects_unknown_config_id(staff_client):
    response = staff_client.post(
        "/api/beta-gate/config/rollback/not-real/",
        {"version": "bad"},
        format="json",
    )

    assert response.status_code == 404
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"] == "Config not-real not found"


@pytest.mark.django_db
def test_beta_gate_create_rejects_invalid_numeric_payload(staff_client):
    response = staff_client.post(
        "/api/beta-gate/configs/",
        {
            "risk_profile": "balanced",
            "min_confidence": "bad-float",
        },
        format="json",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    (
        "/api/beta-gate/configs/",
        "/api/beta-gate/config/rollback/not-real/",
    ),
)
def test_beta_gate_config_mutations_require_staff(authenticated_client, path):
    response = authenticated_client.post(
        path,
        {"risk_profile": "balanced"},
        format="json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_beta_gate_staff_create_increments_version_and_switches_profile_activation(
    staff_client,
):
    existing = GateConfigModel.objects.create(
        config_id="beta-existing",
        risk_profile=GateConfigModel.BALANCED,
        version=4,
        is_active=True,
        regime_constraints={"allowed_regimes": ["Recovery"]},
        policy_constraints={"max_allowed_level": 2},
        portfolio_constraints={
            "max_total_position_pct": 90.0,
            "max_single_position_pct": 20.0,
        },
    )

    response = staff_client.post(
        "/api/beta-gate/configs/",
        {
            "config_id": "beta-new",
            "risk_profile": "balanced",
            "allowed_regimes": ["Recovery", "Deflation"],
            "min_confidence": 0.6,
            "max_policy_level": 1,
            "veto_on_p3": True,
            "max_total_position": 80.0,
            "max_single_position": 15.0,
        },
        format="json",
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["success"] is True
    assert payload["result"]["config_id"] == "beta-new"
    assert payload["result"]["version"] == 5
    assert payload["result"]["is_active"] is True
    existing.refresh_from_db()
    assert existing.is_active is False
    created = GateConfigModel.objects.get(config_id="beta-new")
    assert created.risk_profile == GateConfigModel.BALANCED
    assert created.regime_constraints["min_confidence"] == 0.6


@pytest.mark.django_db
def test_beta_gate_patch_creates_replacement_version(staff_client):
    current = GateConfigModel.objects.create(
        config_id="beta-patch-source",
        risk_profile=GateConfigModel.BALANCED,
        version=3,
        is_active=True,
        regime_constraints={"allowed_regimes": ["Recovery"], "min_confidence": 0.3},
        policy_constraints={"max_allowed_level": 2, "veto_on_p3": True},
        portfolio_constraints={
            "max_total_position_pct": 90.0,
            "max_single_position_pct": 20.0,
        },
    )

    response = staff_client.patch(
        "/api/beta-gate/configs/beta-patch-source/",
        {"regime_constraints": {"min_confidence": 0.7}},
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()["result"]
    assert payload["replaces_config_id"] == "beta-patch-source"
    assert payload["version"] == 4
    assert payload["regime_constraints"]["min_confidence"] == 0.7
    current.refresh_from_db()
    assert current.is_active is False


@pytest.mark.django_db
def test_beta_gate_delete_soft_deactivates_config(staff_client):
    config = GateConfigModel.objects.create(
        config_id="beta-soft-delete",
        risk_profile=GateConfigModel.CONSERVATIVE,
        version=1,
        is_active=True,
        regime_constraints={},
        policy_constraints={},
        portfolio_constraints={},
    )

    response = staff_client.delete("/api/beta-gate/configs/beta-soft-delete/")

    assert response.status_code == 204
    config.refresh_from_db()
    assert config.is_active is False


@pytest.mark.django_db
def test_beta_gate_all_config_catalog_is_read_only(staff_client):
    GateConfigModel.objects.create(
        config_id="beta-history",
        risk_profile=GateConfigModel.CONSERVATIVE,
        version=3,
        is_active=False,
        regime_constraints={},
        policy_constraints={},
        portfolio_constraints={},
    )
    before = list(
        GateConfigModel.objects.values(
            "config_id",
            "version",
            "is_active",
        )
    )

    response = staff_client.get("/api/beta-gate/configs/?active_only=false")

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["results"][0]["config_id"] == "beta-history"
    assert list(
        GateConfigModel.objects.values(
            "config_id",
            "version",
            "is_active",
        )
    ) == before


@pytest.mark.django_db
def test_beta_gate_staff_rollback_activates_exact_config_for_same_profile(staff_client):
    current = GateConfigModel.objects.create(
        config_id="balanced-current",
        risk_profile=GateConfigModel.BALANCED,
        version=5,
        is_active=True,
        regime_constraints={},
        policy_constraints={},
        portfolio_constraints={},
    )
    target = GateConfigModel.objects.create(
        config_id="balanced-history",
        risk_profile=GateConfigModel.BALANCED,
        version=2,
        is_active=False,
        regime_constraints={},
        policy_constraints={},
        portfolio_constraints={},
    )
    other_profile = GateConfigModel.objects.create(
        config_id="conservative-current",
        risk_profile=GateConfigModel.CONSERVATIVE,
        version=6,
        is_active=True,
        regime_constraints={},
        policy_constraints={},
        portfolio_constraints={},
    )

    response = staff_client.post(
        "/api/beta-gate/config/rollback/balanced-history/",
        {},
        format="json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["result"]["config_id"] == "balanced-history"
    assert payload["result"]["version"] == 2
    assert payload["result"]["is_active"] is True
    current.refresh_from_db()
    target.refresh_from_db()
    other_profile.refresh_from_db()
    assert current.is_active is False
    assert target.is_active is True
    assert other_profile.is_active is True


@pytest.mark.django_db
def test_beta_gate_staff_rollback_rejects_active_or_expired_config(staff_client):
    active = GateConfigModel.objects.create(
        config_id="balanced-active",
        risk_profile=GateConfigModel.BALANCED,
        version=5,
        is_active=True,
        regime_constraints={},
        policy_constraints={},
        portfolio_constraints={},
    )
    expired = GateConfigModel.objects.create(
        config_id="balanced-expired",
        risk_profile=GateConfigModel.BALANCED,
        version=2,
        is_active=False,
        expires_at="2020-01-01",
        regime_constraints={},
        policy_constraints={},
        portfolio_constraints={},
    )

    active_response = staff_client.post(
        "/api/beta-gate/config/rollback/balanced-active/",
        {},
        format="json",
    )
    expired_response = staff_client.post(
        "/api/beta-gate/config/rollback/balanced-expired/",
        {},
        format="json",
    )

    assert active_response.status_code == 400
    assert active_response.json()["error"] == "Config balanced-active is already active"
    assert expired_response.status_code == 400
    assert expired_response.json()["error"] == "Config balanced-expired is expired"
    active.refresh_from_db()
    expired.refresh_from_db()
    assert active.is_active is True
    assert expired.is_active is False
