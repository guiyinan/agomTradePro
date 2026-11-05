"""Permission, integrity and metadata contracts for the QMT bridge download."""

from __future__ import annotations

import hashlib

import pytest
from django.contrib.auth.models import User
from django.test import Client

from qmt_agent import __version__


def _user(username: str, *, admin: bool = False) -> User:
    user = User.objects.create_user(
        username=username,
        password="test123",
        is_staff=admin,
        is_superuser=admin,
    )
    profile = user.account_profile
    profile.rbac_role = "admin" if admin else "owner"
    profile.approval_status = "approved"
    profile.save(update_fields=["rbac_role", "approval_status", "updated_at"])
    return user


@pytest.mark.django_db
def test_qmt_bridge_download_is_admin_only_and_returns_exact_package(
    tmp_path, settings,
) -> None:
    package_path = tmp_path / f"agom-qmt-agent-windows-{__version__}.zip"
    content = b"TEST_FIXTURE_ONLY_ZIP_CONTENT"
    package_path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    package_path.with_name(package_path.name + ".sha256").write_text(
        f"{digest}  {package_path.name}\n", encoding="utf-8"
    )
    settings.QMT_AGENT_PACKAGE_PATH = str(package_path)
    admin = _user("qmt-package-admin", admin=True)
    owner = _user("qmt-package-owner")
    client = Client()

    unauthenticated = client.get("/api/broker-execution/qmt-bridge/download/")
    assert unauthenticated.status_code in {401, 403}

    client.force_login(owner)
    forbidden = client.get("/api/broker-execution/qmt-bridge/download/")
    assert forbidden.status_code == 403

    client.force_login(admin)
    onboarding = client.get("/api/broker-execution/qmt-onboarding/")
    assert onboarding.status_code == 200
    data = onboarding.json()["data"]
    assert data["package_available"] is True
    assert data["package_version"] == __version__
    assert data["package_filename"] == package_path.name
    assert data["package_size_bytes"] == len(content)
    assert data["package_sha256"] == digest
    assert "setup-builtin-python.ps1" in data["builtin_setup_command"]

    response = client.get("/api/broker-execution/qmt-bridge/download/")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    assert response["X-QMT-Package-SHA256"] == digest
    assert response["X-Content-Type-Options"] == "nosniff"
    assert package_path.name in response["Content-Disposition"]
    assert b"".join(response.streaming_content) == content


@pytest.mark.django_db
def test_missing_qmt_bridge_package_is_bounded_and_marked_unavailable(
    tmp_path, settings,
) -> None:
    settings.QMT_AGENT_PACKAGE_PATH = str(tmp_path / "missing.zip")
    admin = _user("qmt-package-missing-admin", admin=True)
    client = Client()
    client.force_login(admin)

    response = client.get("/api/broker-execution/qmt-bridge/download/")

    assert response.status_code == 404
    onboarding = client.get("/api/broker-execution/qmt-onboarding/").json()["data"]
    assert onboarding["package_available"] is False
    assert onboarding["package_sha256"] == ""
