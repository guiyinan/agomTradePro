"""TUI metadata publication fallback contracts."""

from __future__ import annotations

import logging

import pytest

from apps.terminal.application.tui_workbench import TuiWorkbenchService
from apps.terminal.infrastructure.models import TuiMetadataRegistryORM
from apps.terminal.infrastructure.tui_metadata_repository import (
    PublishedTuiMetadataRepository,
)


def test_invalid_database_publication_falls_back_with_structured_governance_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An invalid DB publication must not take the TUI catalog down."""

    class FakeQuerySet:
        def filter(self, **_: object) -> FakeQuerySet:
            return self

        def order_by(self, *_: str) -> FakeQuerySet:
            return self

        def first(self) -> object:
            return type(
                "InvalidPublication",
                (),
                {
                    "pk": 17,
                    "payload": {"schema_version": "tui-metadata.v3"},
                    "source_hash": "",
                    "updated_at": None,
                },
            )()

    manager_type = type(TuiMetadataRegistryORM._default_manager)
    monkeypatch.setattr(
        manager_type,
        "filter",
        lambda _manager, **_: FakeQuerySet(),
    )
    repository = PublishedTuiMetadataRepository()

    with caplog.at_level(logging.WARNING):
        catalog = TuiWorkbenchService(metadata_repository=repository).get_catalog()

    health = catalog["metadata_health"]
    assert health == {
        "status": "degraded",
        "source": "file",
        "reason_code": "database_payload_invalid",
        "message": "数据库中的 TUI 配置无法通过校验，当前使用文件版配置；请完成发布记录重校验。",
    }
    assert catalog["default_screen"] == "command-center.overview"
    warning = next(
        record
        for record in caplog.records
        if getattr(record, "event", "") == "tui_metadata_fallback"
    )
    assert warning.reason_code == "database_payload_invalid"
