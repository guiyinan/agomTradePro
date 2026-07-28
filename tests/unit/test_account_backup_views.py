"""Boundary tests for the token-authenticated backup download view."""

from __future__ import annotations

import pytest
from django.http import FileResponse, Http404
from django.test import RequestFactory

from apps.account.interface import backup_views


def test_backup_download_rejects_unbounded_token_before_service_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backup_views, "_MAX_BACKUP_TOKEN_LENGTH", 8)
    monkeypatch.setattr(
        backup_views,
        "build_backup_download_payload",
        lambda token: (_ for _ in ()).throw(
            AssertionError("invalid tokens must not reach the backup service")
        ),
    )

    with pytest.raises(Http404, match="无效或已过期"):
        backup_views.admin_db_backup_download_view(
            RequestFactory().get("/admin/db-backup/token/"),
            "x" * 9,
        )


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"content": b"", "filename": "backup.agbk", "content_type": "application/octet-stream"},
        {
            "content": b"archive",
            "filename": "../backup.agbk",
            "content_type": "application/octet-stream",
        },
        {"content": b"archive", "filename": "backup.agbk", "content_type": "text/html"},
    ],
)
def test_backup_download_rejects_malformed_archive_payload(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    monkeypatch.setattr(
        backup_views,
        "build_backup_download_payload",
        lambda token: payload,
    )

    with pytest.raises(Http404, match="备份文件不可用"):
        backup_views.admin_db_backup_download_view(
            RequestFactory().get("/admin/db-backup/token/"),
            "signed-token",
        )


def test_backup_download_returns_valid_binary_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        backup_views,
        "build_backup_download_payload",
        lambda token: {
            "content": b"archive",
            "filename": "backup.agbk",
            "content_type": "application/octet-stream",
        },
    )

    response = backup_views.admin_db_backup_download_view(
        RequestFactory().get("/admin/db-backup/token/"),
        "signed-token",
    )

    assert isinstance(response, FileResponse)
    assert response.status_code == 200
    assert response["Content-Type"] == "application/octet-stream"
    response.close()
