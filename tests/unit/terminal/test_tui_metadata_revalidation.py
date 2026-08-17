"""TUI metadata registry revalidation contracts."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from apps.terminal.application.tui_metadata import TuiMetadataValidationError
from apps.terminal.infrastructure.models import TuiMetadataRegistryORM
from apps.terminal.infrastructure.tui_metadata_revalidation import (
    TuiMetadataRegistryRevalidationService,
    TuiMetadataRevalidationReport,
)
from apps.terminal.management.commands.revalidate_tui_metadata_registry import Command


class _FakeQuerySet:
    def __init__(self, records: list[Any]) -> None:
        self.records = records

    def order_by(self, *_fields: str) -> list[Any]:
        return sorted(self.records, key=lambda record: int(record.pk))


class _FakeRepository:
    def __init__(self, invalid_ids: set[int]) -> None:
        self.invalid_ids = invalid_ids

    def validate_and_normalize_runtime_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if int(payload["registry_id"]) in self.invalid_ids:
            raise TuiMetadataValidationError("invalid fixture")
        return {"registry_id": payload["registry_id"]}

    @staticmethod
    def payload_hash(payload: dict[str, Any]) -> str:
        return f"hash-{payload['registry_id']}"


def test_revalidation_scans_all_statuses_without_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every stored status is counted and invalid rows receive repair guidance."""

    records = [
        SimpleNamespace(
            pk=3,
            registry_key="default",
            status="archived",
            version="v3",
            payload={"registry_id": 3},
        ),
        SimpleNamespace(
            pk=1,
            registry_key="default",
            status="published",
            version="v1",
            payload={"registry_id": 1},
        ),
        SimpleNamespace(
            pk=2, registry_key="other", status="draft", version="v2", payload={"registry_id": 2}
        ),
        SimpleNamespace(
            pk=4,
            registry_key="default",
            status="rejected",
            version="v4",
            payload={"registry_id": 4},
        ),
    ]
    manager_type = type(TuiMetadataRegistryORM._default_manager)
    monkeypatch.setattr(
        manager_type,
        "all",
        lambda _manager: _FakeQuerySet(records),
    )

    report = TuiMetadataRegistryRevalidationService(
        repository=_FakeRepository({2}),
    ).run()

    assert report.outcome == "partial"
    assert report.recommendation == "repair_or_archive_invalid_rows_before_publish"
    assert report.dry_run is True
    assert report.writes_performed == 0
    assert report.total_count == 4
    assert report.valid_count == 3
    assert report.invalid_count == 1
    assert report.error_count == 0
    assert report.status_counts == {
        "archived": 1,
        "draft": 1,
        "published": 1,
        "rejected": 1,
    }
    assert [row.registry_id for row in report.rows] == [1, 2, 3, 4]
    assert report.rows[1].recommendation == "repair_or_archive_before_publish"
    assert report.rows[1].reason_code == "payload_contract_invalid"
    assert records[2].payload == {"registry_id": 2}


def test_revalidation_command_emits_stable_read_only_json() -> None:
    """The management command exposes the report and never adds a write mode."""

    report = TuiMetadataRevalidationReport(
        outcome="success",
        recommendation="no_action_required",
        dry_run=True,
        writes_performed=0,
        total_count=1,
        valid_count=1,
        invalid_count=0,
        error_count=0,
        status_counts={"published": 1},
        rows=(),
    )
    stdout = io.StringIO()
    command = Command(stdout=stdout)
    with patch(
        "apps.terminal.management.commands.revalidate_tui_metadata_registry.TuiMetadataRegistryRevalidationService.run",
        return_value=report,
    ):
        command.handle()

    payload = json.loads(stdout.getvalue())
    assert payload["dry_run"] is True
    assert payload["writes_performed"] == 0
    assert payload["outcome"] == "success"
    assert payload["counts"] == {"errors": 0, "invalid": 0, "total": 1, "valid": 1}
