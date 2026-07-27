import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from apps.alpha import admin as alpha_admin
from apps.alpha.infrastructure.models import QlibModelRegistryModel


@pytest.mark.django_db
def test_alpha_admin_train_page_requires_superuser():
    staff_user = get_user_model().objects.create_user(
        username="alpha_staff_only",
        password="pass12345",
        is_staff=True,
        is_superuser=False,
    )

    client = Client()
    client.force_login(staff_user)
    response = client.get(reverse("admin:alpha_qlibmodelregistry_train"))

    assert response.status_code == 302
    assert response["Location"].endswith("/admin/")


@pytest.mark.django_db
def test_alpha_admin_pickle_import_requires_superuser_even_with_add_permission():
    """Model pickle import is never exposed to delegated model add permission."""

    staff_user = get_user_model().objects.create_user(
        username="alpha_model_importer",
        password="pass12345",
        is_staff=True,
        is_superuser=False,
    )
    staff_user.user_permissions.add(Permission.objects.get(codename="add_qlibmodelregistrymodel"))

    client = Client()
    client.force_login(staff_user)
    response = client.get(reverse("admin:alpha_qlibmodelregistry_import"))

    assert response.status_code == 302
    assert response["Location"].endswith("/admin/")


@pytest.mark.django_db
def test_alpha_admin_registry_mutations_require_superuser_even_with_model_permissions():
    """Delegated staff cannot rewrite model paths or delete registry audit rows."""

    staff_user = get_user_model().objects.create_user(
        username="alpha_model_editor",
        password="pass12345",
        is_staff=True,
        is_superuser=False,
    )
    staff_user.user_permissions.add(
        Permission.objects.get(codename="change_qlibmodelregistrymodel"),
        Permission.objects.get(codename="delete_qlibmodelregistrymodel"),
    )
    model = QlibModelRegistryModel._default_manager.create(
        model_name="protected-model",
        artifact_hash="b" * 64,
        model_type=QlibModelRegistryModel.MODEL_LGB,
        universe="csi300",
        train_config={"source": "test"},
        feature_set_id="v1",
        label_id="return_5d",
        data_version="2026-07-27",
        model_path="/models/qlib/protected-model/model.pkl",
    )
    client = Client()
    client.force_login(staff_user)

    change_response = client.post(
        reverse("admin:alpha_qlibmodelregistrymodel_change", args=[model.pk]),
        {"model_path": "/tmp/untrusted.pkl"},
    )
    delete_response = client.get(
        reverse("admin:alpha_qlibmodelregistrymodel_delete", args=[model.pk])
    )

    assert change_response.status_code == 403
    assert delete_response.status_code == 403


@pytest.mark.django_db
def test_alpha_admin_activation_requires_csrf_post_and_never_mutates_on_get(monkeypatch):
    """A validation GET remains read-only; activation requires an explicit CSRF POST."""

    superuser = get_user_model().objects.create_superuser(
        username="alpha_model_superuser",
        password="pass12345",
        email="alpha-superuser@example.com",
    )
    model = QlibModelRegistryModel._default_manager.create(
        model_name="safe-model",
        artifact_hash="a" * 64,
        model_type=QlibModelRegistryModel.MODEL_LGB,
        universe="csi300",
        train_config={"source": "test"},
        feature_set_id="v1",
        label_id="return_5d",
        data_version="2026-07-27",
        model_path="/models/qlib/safe-model/model.pkl",
    )
    monkeypatch.setattr(
        alpha_admin.QlibModelRegistryAdmin,
        "_run_validation",
        lambda _self, _model: {
            "passed": True,
            "checks": [],
            "sample_scores": [],
            "activation_message": "",
        },
    )
    client = Client(enforce_csrf_checks=True)
    client.force_login(superuser)
    validation_url = reverse(
        "admin:alpha_qlibmodelregistry_validate",
        args=[model.artifact_hash],
    )

    get_response = client.get(f"{validation_url}?activate=1")

    assert get_response.status_code == 200
    model.refresh_from_db()
    assert model.is_active is False

    csrf_token = client.cookies["csrftoken"].value
    post_response = client.post(
        validation_url,
        {"activate": "1", "csrfmiddlewaretoken": csrf_token},
    )

    assert post_response.status_code == 200
    model.refresh_from_db()
    assert model.is_active is True
