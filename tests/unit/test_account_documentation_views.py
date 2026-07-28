"""Boundary tests for retained Account documentation admin views."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpRequest, HttpResponse, QueryDict
from django.test import RequestFactory

from apps.account.application.documentation_use_cases import DocumentationDTO
from apps.account.interface import documentation_views


def _staff_request(path: str, *, data: dict[str, object]) -> HttpRequest:
    request = RequestFactory().post(path, data=data)
    request.user = SimpleNamespace(is_active=True, is_staff=True)
    return request


def _json_body(response: HttpResponse) -> dict[str, object]:
    return json.loads(response.content.decode("utf-8"))


def test_doc_import_rejects_oversized_file_before_service_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(documentation_views, "_MAX_IMPORT_BYTES", 8)
    monkeypatch.setattr(
        documentation_views,
        "_service",
        lambda: (_ for _ in ()).throw(
            AssertionError("oversized uploads must not reach the service")
        ),
    )
    request = _staff_request(
        "/admin/docs/import/",
        data={
            "format": "json",
            "file": SimpleUploadedFile("docs.json", b"123456789"),
        },
    )

    response = documentation_views.doc_import(request)

    assert response.status_code == 413
    assert _json_body(response) == {"success": False, "error": "导入文件不能超过 5 MB"}


@pytest.mark.django_db
def test_doc_import_returns_stable_error_for_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        documentation_views,
        "_service",
        lambda: SimpleNamespace(import_json_text=json.loads),
    )
    request = _staff_request(
        "/admin/docs/import/",
        data={
            "format": "json",
            "file": SimpleUploadedFile("docs.json", b'{"secret":'),
        },
    )

    with caplog.at_level("WARNING"):
        response = documentation_views.doc_import(request)

    assert response.status_code == 400
    assert _json_body(response) == {"success": False, "error": "导入文件格式或内容无效"}
    assert "Expecting value: line 1 column 11" not in caplog.text


@pytest.mark.django_db
def test_doc_import_does_not_expose_service_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = SimpleNamespace(
        import_json_text=lambda raw_text: (_ for _ in ()).throw(
            RuntimeError("database-secret-token")
        )
    )
    monkeypatch.setattr(documentation_views, "_service", lambda: service)
    request = _staff_request(
        "/admin/docs/import/",
        data={
            "format": "json",
            "file": SimpleUploadedFile("docs.json", b"[]"),
        },
    )

    with caplog.at_level("ERROR"):
        response = documentation_views.doc_import(request)

    assert response.status_code == 503
    assert _json_body(response) == {"success": False, "error": "文档导入服务暂时不可用"}
    assert "RuntimeError" in caplog.text
    assert "database-secret-token" not in caplog.text


@pytest.mark.parametrize("value", [True, 1.0, "1.2", "１２", "2147483648"])
def test_parse_order_rejects_non_exact_or_out_of_range_values(value: object) -> None:
    with pytest.raises(ValueError, match="order"):
        documentation_views._parse_order(value)


def test_form_data_parser_accepts_bounded_signed_order() -> None:
    post_data = QueryDict(
        "title=Guide&slug=guide&content=Body&category=user_guide&summary=Summary&order=-2"
    )

    form_data = documentation_views._form_data_from_post(post_data)

    assert form_data.order == -2
    assert form_data.title == "Guide"


def test_csv_export_neutralizes_formula_cells() -> None:
    now = datetime(2026, 7, 28, tzinfo=UTC)
    doc = DocumentationDTO(
        id=1,
        title='=WEBSERVICE("https://example.invalid")',
        slug="safe-slug",
        category="user_guide",
        category_display="用户指南",
        content="@SUM(1,1)",
        summary="+cmd|' /C calc'!A0",
        order=1,
        is_published=True,
        created_at=now,
        updated_at=now,
    )

    response = documentation_views._export_csv([doc])
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))

    assert rows[1][0].startswith("'=")
    assert rows[1][3].startswith("'+")
    assert rows[1][6].startswith("'@")
