"""T3B Policy event lifecycle contracts for failure and destructive boundaries."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from django.db import DatabaseError, IntegrityError

from apps.policy.application import event_use_cases as module
from apps.policy.application.event_use_cases import (
    CreatePolicyEventInput,
    CreatePolicyEventUseCase,
    DeletePolicyEventUseCase,
    GetCurrentPolicyUseCase,
    GetPolicyHistoryUseCase,
    UpdatePolicyEventUseCase,
)
from apps.policy.domain.entities import PolicyEvent, PolicyLevel
from core.exceptions import DataFetchError, ExternalServiceError

TARGET_DATE = date(2026, 7, 24)


def _input() -> CreatePolicyEventInput:
    return CreatePolicyEventInput(
        event_date=TARGET_DATE,
        level=PolicyLevel.P2,
        title="Policy intervention",
        description="Evidence-backed intervention",
        evidence_url="https://evidence.test/policy",
    )


def _event(level: PolicyLevel = PolicyLevel.P2) -> PolicyEvent:
    return PolicyEvent(
        event_date=TARGET_DATE,
        level=level,
        title="Policy intervention",
        description="Evidence-backed intervention",
        evidence_url="https://evidence.test/policy",
    )


@pytest.mark.parametrize(
    ("exception", "expected_fragment"),
    [
        (DataFetchError("source offline"), "source offline"),
        (DatabaseError("database offline"), "Failed to fetch policy level"),
    ],
)
def test_current_policy_query_converts_expected_data_failures(
    exception: Exception,
    expected_fragment: str,
) -> None:
    """Current-policy reads expose data failures without returning a stale level."""
    result = GetCurrentPolicyUseCase(
        SimpleNamespace(get_current_policy_level=lambda day: (_ for _ in ()).throw(exception))
    ).execute()
    assert result.success is False
    assert result.policy_level is None
    assert expected_fragment in (result.error or "")


@pytest.mark.parametrize(
    ("exception", "expected_prefix"),
    [
        (DataFetchError("source offline"), "数据处理错误"),
        (IntegrityError("duplicate"), "数据一致性错误"),
        (DatabaseError("database offline"), "数据库错误"),
        (RuntimeError("unexpected"), "系统错误"),
    ],
)
def test_create_policy_event_classifies_persistence_failures(
    exception: Exception,
    expected_prefix: str,
) -> None:
    """Creation reports the correct failure class and never claims persistence."""
    store = SimpleNamespace(
        get_latest_event=lambda before_date=None: (_ for _ in ()).throw(exception),
        save_event=lambda event: pytest.fail("save must not run after lookup failure"),
    )
    result = CreatePolicyEventUseCase(store).execute(_input())
    assert result.success is False
    assert result.event is None
    assert result.errors[0].startswith(expected_prefix)


def test_policy_event_alert_boundary_handles_absent_external_and_runtime_failures() -> None:
    """Alert delivery is optional and cannot roll back a persisted policy event."""
    use_case = CreatePolicyEventUseCase(SimpleNamespace())
    assert use_case._send_alert(_event(), PolicyLevel.P1) is False

    use_case.alert_service = SimpleNamespace(
        send_alert=lambda **kwargs: (_ for _ in ()).throw(
            ExternalServiceError("notification timeout")
        )
    )
    assert use_case._send_alert(_event(), PolicyLevel.P1) is False

    use_case.alert_service = SimpleNamespace(
        send_alert=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("notification malformed"))
    )
    assert use_case._send_alert(_event(), PolicyLevel.P1) is False


def test_policy_history_generic_store_returns_explicit_empty_history() -> None:
    """A non-Django store does not fabricate range data or policy statistics."""
    result = GetPolicyHistoryUseCase(SimpleNamespace()).execute(
        date(2026, 7, 1),
        TARGET_DATE,
        level=PolicyLevel.P2,
    )
    assert result.events == []
    assert result.total_count == 0
    assert result.level_stats == {"total": 0, "by_level": {}}


def test_update_policy_event_rejects_mismatch_missing_records_and_repository_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Updates require an exact event identity and preserve repository failures."""

    class _DjangoRepo:
        def __init__(self) -> None:
            self.existing: dict[str, object] | None = None
            self.save_error: Exception | None = None

        def get_existing_for_update(
            self,
            *,
            event_id: int | None,
            event_date: date,
        ) -> dict[str, object] | None:
            return self.existing

        def save_event(self, event: PolicyEvent, **kwargs: object) -> PolicyEvent:
            if self.save_error is not None:
                raise self.save_error
            return event

    monkeypatch.setattr(module, "DjangoPolicyRepository", _DjangoRepo)
    repo = _DjangoRepo()
    use_case = UpdatePolicyEventUseCase(repo)

    repo.existing = {"id": 7, "event_date": date(2026, 7, 23)}
    mismatch = use_case.execute(
        event_id=7,
        event_date=TARGET_DATE,
        level=PolicyLevel.P2,
        title="updated",
        description="updated",
        evidence_url="https://evidence.test",
    )
    assert "不匹配" in mismatch.errors[0]

    repo.existing = None
    missing_id = use_case.execute(
        event_id=99,
        event_date=TARGET_DATE,
        level=PolicyLevel.P2,
        title="updated",
        description="updated",
        evidence_url="https://evidence.test",
    )
    assert missing_id.errors == ["未找到 ID=99 的事件"]
    missing_date = use_case.execute(
        event_id=None,
        event_date=TARGET_DATE,
        level=PolicyLevel.P2,
        title="updated",
        description="updated",
        evidence_url="https://evidence.test",
    )
    assert "未找到日期" in missing_date.errors[0]

    repo.existing = {"id": 7, "event_date": TARGET_DATE}
    repo.save_error = DatabaseError("update locked")
    failed = use_case.execute(
        event_id=7,
        event_date=TARGET_DATE,
        level=PolicyLevel.P2,
        title="updated",
        description="updated",
        evidence_url="https://evidence.test",
    )
    assert failed.errors == ["更新失败: update locked"]


def test_delete_policy_event_covers_identity_date_and_unsupported_store_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deletion is exact by ID, explicit by date, and rejects unsupported stores."""

    class _DjangoRepo:
        id_result = False
        date_result = False

        def delete_event_by_id(self, event_id: int) -> bool:
            return self.id_result

        def get_events_by_date(self, event_date: date) -> list[PolicyEvent]:
            return [_event(), _event(PolicyLevel.P1)]

        def delete_event(self, event_date: date) -> bool:
            return self.date_result

    monkeypatch.setattr(module, "DjangoPolicyRepository", _DjangoRepo)
    repo = _DjangoRepo()
    use_case = DeletePolicyEventUseCase(repo)
    assert use_case.execute(event_id=7) == (False, "未找到 ID=7 的事件")
    repo.id_result = True
    assert use_case.execute(event_id=7) == (True, "事件 ID=7 已删除")
    assert use_case.execute(event_date=TARGET_DATE) == (
        False,
        f"未找到日期为 {TARGET_DATE} 的事件",
    )
    repo.date_result = True
    assert use_case.execute(event_date=TARGET_DATE) == (
        True,
        f"已删除 {TARGET_DATE} 的 2 个事件（警告：按日期删除）",
    )
    assert use_case.execute() == (False, "必须提供 event_date 或 event_id")
    assert DeletePolicyEventUseCase(SimpleNamespace()).execute(event_id=1) == (
        False,
        "当前仓储不支持删除操作",
    )
