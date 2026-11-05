"""Validation contract for server-owned TUI artifact downloads."""

from __future__ import annotations

from typing import Any

import pytest

from apps.terminal.application.tui_metadata import validate_tui_metadata
from apps.terminal.application.tui_metadata_filter_validation import (
    TuiMetadataValidationError,
)


def _payload(download: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": "test",
        "default_screen": "system.download",
        "groups": [{"key": "system", "label": "系统"}],
        "modules": [
            {"key": "system", "label": "系统", "group": "system", "summary": "系统"}
        ],
        "screens": [
            {
                "key": "system.download",
                "label": "下载",
                "module_key": "system",
                "group": "system",
                "summary": "下载安装包",
                "view_type": "detail",
                "audience": "admin",
                "default_action_key": "system.read-download",
                "dashboard_panels": [
                    {
                        "key": "package",
                        "title": "安装包",
                        "kind": "detail",
                        "action_key": "system.read-download",
                        "user_priority": "p0",
                        "download": download,
                    }
                ],
            }
        ],
        "actions": [
            {
                "key": "system.read-download",
                "label": "读取安装包信息",
                "endpoint": "/api/system/package/",
                "method": "GET",
                "intent": "read_package",
                "risk": "read",
                "audience": "admin",
                "screen_key": "system.download",
                "module_key": "system",
                "view_type": "detail",
            }
        ],
    }


def test_tui_panel_accepts_fixed_owner_api_download() -> None:
    payload = _payload({"url": "/api/system/package/download/", "label": "下载安装包"})

    normalized = validate_tui_metadata(payload)

    assert normalized["screens"][0]["dashboard_panels"][0]["download"]["label"] == "下载安装包"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/package.zip",
        "/media/package.zip",
        "/api/system/../secret/",
        "/api/system/download/?path=secret",
    ],
)
def test_tui_panel_rejects_external_or_unbounded_download_paths(url: str) -> None:
    payload = _payload({"url": url, "label": "下载"})

    with pytest.raises(TuiMetadataValidationError):
        validate_tui_metadata(payload)
