"""Security boundaries for legacy Macro application orchestration."""

import logging
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from apps.macro.application.data_management import (
    DeleteDataRequest,
    DeleteDataUseCase,
    FetchDataRequest,
    FetchDataUseCase,
)
from apps.macro.application.use_cases import (
    GetLatestMacroDataRequest,
    GetLatestMacroDataUseCase,
    SyncMacroDataRequest,
    SyncMacroDataUseCase,
)


def test_fetch_failure_does_not_publish_upstream_error_details(caplog):
    sync_use_case = MagicMock()
    sync_use_case.execute.side_effect = RuntimeError(
        "postgresql://admin:raw-secret@example.test/prod"
    )

    with caplog.at_level(logging.WARNING):
        response = FetchDataUseCase(sync_use_case, MagicMock()).execute(FetchDataRequest())

    assert response.success is False
    assert response.message == "数据获取失败"
    assert response.errors == ["macro_data_fetch_failed"]
    assert "raw-secret" not in caplog.text
    assert "postgresql://" not in caplog.text


def test_delete_failure_does_not_publish_repository_error_details(caplog):
    repository = MagicMock()
    repository.delete_by_conditions.side_effect = RuntimeError(
        "redis://default:raw-secret@example.test:6379/0"
    )

    with caplog.at_level(logging.WARNING):
        response = DeleteDataUseCase(repository).execute(DeleteDataRequest())

    assert response.success is False
    assert response.message == "macro_data_delete_failed"
    assert "raw-secret" not in caplog.text
    assert "redis://" not in caplog.text


def test_sync_rejects_dynamic_adapter_payload_and_redacts_error(caplog):
    repository = MagicMock()
    adapter = MagicMock()
    adapter.supports.return_value = True
    adapter.fetch.return_value = {
        "password": "raw-secret",
        "value": 50.0,
    }

    with caplog.at_level(logging.WARNING):
        response = SyncMacroDataUseCase(
            repository=repository,
            adapters={"unsafe": adapter},
        ).execute(
            SyncMacroDataRequest(
                start_date=date(2026, 1, 1),
                indicators=["CN_PMI"],
            )
        )

    assert response.success is False
    assert response.errors == ["CN_PMI: macro_indicator_sync_failed"]
    repository.save_indicators_batch.assert_not_called()
    assert "raw-secret" not in caplog.text


def test_latest_lookup_failure_is_isolated_without_exception_details(caplog):
    repository = MagicMock()
    repository.get_latest_observation_date.side_effect = RuntimeError(
        "postgresql://admin:raw-secret@example.test/prod"
    )

    with caplog.at_level(logging.WARNING):
        response = GetLatestMacroDataUseCase(repository).execute(
            GetLatestMacroDataRequest(indicator_codes=["CN_PMI"])
        )

    assert response.data == {"CN_PMI": None}
    assert response.missing == ["CN_PMI"]
    assert "raw-secret" not in caplog.text
    assert "postgresql://" not in caplog.text


def test_failed_sync_response_is_normalized_before_reaching_caller():
    sync_use_case = MagicMock()
    sync_use_case.execute.return_value = SimpleNamespace(
        success=False,
        synced_count=0,
        errors=["https://user:raw-secret@example.test/api"],
    )

    response = FetchDataUseCase(sync_use_case, MagicMock()).execute(FetchDataRequest())

    assert response.errors == ["macro_data_sync_failed"]
    assert "raw-secret" not in response.message
