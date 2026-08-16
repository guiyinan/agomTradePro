from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

SOURCE_COMMIT = "7fe4b2ef60f9a5c044911f9d5026303177bd18aa"
OTHER_COMMIT = "8ae5c3fa71a0b6d155a220ae6137414288ce29bb"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _build_identity(*, source_commit: str = SOURCE_COMMIT) -> dict[str, object]:
    return {
        "schema_version": 1,
        "app_version": "0.8.0",
        "source_commit": source_commit,
    }


def _release_manifest(*, source_commit: str = SOURCE_COMMIT) -> dict[str, object]:
    return {
        "version": 1,
        "release_tag": "20260816112017",
        "source_commit": source_commit,
        "image_tag": "agomtradepro-web:20260816112017",
        "image_id": f"sha256:{'a' * 64}",
        "build_started_at": "2026-08-16T11:18:00Z",
        "build_finished_at": "2026-08-16T11:20:17Z",
        "source_mode": "git-clone",
    }


@pytest.mark.django_db
def test_release_identity_api_returns_verified_identity_for_staff(
    client,
    django_user_model,
    tmp_path: Path,
) -> None:
    build_path = tmp_path / "build-identity.json"
    manifest_path = tmp_path / "release-manifest.json"
    _write_json(build_path, _build_identity())
    _write_json(manifest_path, _release_manifest())
    admin = django_user_model.objects.create_user(
        username="release-admin",
        password="test-password",
        is_staff=True,
    )
    client.force_login(admin)

    with override_settings(
        AGOM_BUILD_IDENTITY_PATH=build_path,
        AGOM_RELEASE_MANIFEST_PATH=manifest_path,
    ):
        response = client.get("/api/operational-readiness/release-identity/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"] == {
        "status": "verified",
        "status_label": "已核验",
        "app_version": "0.8.0",
        "release_tag": "20260816112017",
        "source_commit": SOURCE_COMMIT,
        "short_commit": SOURCE_COMMIT[:12],
        "image_tag": "agomtradepro-web:20260816112017",
        "image_id": f"sha256:{'a' * 64}",
        "build_started_at": "2026-08-16T11:18:00Z",
        "build_finished_at": "2026-08-16T11:20:17Z",
        "source_mode": "git-clone",
        "runtime_match": True,
        "must_not_trust_for_release": False,
        "blocked_reason": None,
    }


@pytest.mark.django_db
def test_release_identity_api_is_staff_only(client, django_user_model) -> None:
    user = django_user_model.objects.create_user(
        username="release-reader",
        password="test-password",
    )
    client.force_login(user)

    response = client.get("/api/operational-readiness/release-identity/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_release_identity_api_fails_closed_on_commit_mismatch(
    client,
    django_user_model,
    tmp_path: Path,
) -> None:
    build_path = tmp_path / "build-identity.json"
    manifest_path = tmp_path / "release-manifest.json"
    _write_json(build_path, _build_identity())
    _write_json(manifest_path, _release_manifest(source_commit=OTHER_COMMIT))
    admin = django_user_model.objects.create_user(
        username="release-mismatch-admin",
        password="test-password",
        is_staff=True,
    )
    client.force_login(admin)

    with override_settings(
        AGOM_BUILD_IDENTITY_PATH=build_path,
        AGOM_RELEASE_MANIFEST_PATH=manifest_path,
    ):
        response = client.get("/api/operational-readiness/release-identity/")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "mismatch"
    assert payload["status_label"] == "版本不匹配"
    assert payload["runtime_match"] is False
    assert payload["must_not_trust_for_release"] is True
    assert payload["blocked_reason"] == "运行镜像与发布清单对应的 Git 提交不一致。"


@pytest.mark.django_db
def test_release_identity_api_reports_missing_evidence_without_fabricating_commit(
    client,
    django_user_model,
    tmp_path: Path,
) -> None:
    admin = django_user_model.objects.create_user(
        username="release-missing-admin",
        password="test-password",
        is_staff=True,
    )
    client.force_login(admin)

    with override_settings(
        AGOM_BUILD_IDENTITY_PATH=tmp_path / "missing-build.json",
        AGOM_RELEASE_MANIFEST_PATH=tmp_path / "missing-manifest.json",
    ):
        response = client.get("/api/operational-readiness/release-identity/")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "unavailable"
    assert payload["source_commit"] is None
    assert payload["runtime_match"] is None
    assert payload["must_not_trust_for_release"] is True


def test_release_identity_command_asserts_expected_commit(tmp_path: Path) -> None:
    build_path = tmp_path / "build-identity.json"
    manifest_path = tmp_path / "release-manifest.json"
    _write_json(build_path, _build_identity())
    _write_json(manifest_path, _release_manifest())
    stdout = StringIO()

    with override_settings(
        AGOM_BUILD_IDENTITY_PATH=build_path,
        AGOM_RELEASE_MANIFEST_PATH=manifest_path,
    ):
        call_command(
            "show_release_identity",
            expected_commit=SOURCE_COMMIT,
            as_json=True,
            stdout=stdout,
        )
        with pytest.raises(CommandError, match="does not match expected commit"):
            call_command(
                "show_release_identity",
                expected_commit=OTHER_COMMIT,
                as_json=True,
            )

    assert json.loads(stdout.getvalue())["status"] == "verified"
