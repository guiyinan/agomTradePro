"""Safety regressions for public share application use cases."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError

from apps.share.application.use_cases import (
    ShareAccessUseCases,
    ShareLinkUseCases,
    ShareSnapshotUseCases,
)


def _share_repository() -> Mock:
    repository = Mock()
    repository.user_exists.return_value = True
    repository.account_belongs_to_owner.return_value = True
    repository.share_link_short_code_exists.return_value = False
    return repository


@pytest.mark.parametrize(
    ("field_name", "overrides"),
    [
        ("title", {"title": "   "}),
        ("theme", {"theme": "unknown"}),
        ("share_level", {"share_level": "private"}),
        ("max_access_count", {"max_access_count": 0}),
        ("max_access_count", {"max_access_count": True}),
        ("expires_at", {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}),
        ("expires_at", {"expires_at": datetime.now()}),
        ("short_code", {"short_code": "../secret"}),
    ],
)
def test_create_rejects_invalid_public_contract_before_persistence(
    field_name: str,
    overrides: dict[str, object],
) -> None:
    repository = _share_repository()
    use_case = ShareLinkUseCases(repository=repository)
    arguments: dict[str, object] = {
        "owner_id": 1,
        "account_id": 2,
        "title": "Public result",
        "short_code": "PUBLIC12",
    }
    arguments.update(overrides)

    with pytest.raises(ValidationError) as exc_info:
        use_case.create_share_link(**arguments)

    assert field_name in str(exc_info.value)
    repository.create_share_link.assert_not_called()


@pytest.mark.parametrize(
    ("field_name", "payload"),
    [
        ("summary_payload", {"value": float("nan")}),
        ("performance_payload", {"value": float("inf")}),
        ("decision_payload", {"value": object()}),
    ],
)
def test_snapshot_rejects_invalid_json_before_persistence(
    field_name: str,
    payload: dict[str, object],
) -> None:
    repository = _share_repository()
    use_case = ShareSnapshotUseCases(repository=repository)
    payloads: dict[str, dict[str, object]] = {
        "summary_payload": {},
        "performance_payload": {},
        "positions_payload": {},
        "transactions_payload": {},
        "decision_payload": {},
    }
    payloads[field_name] = payload

    with pytest.raises(ValidationError) as exc_info:
        use_case.create_snapshot(share_link_id=1, **payloads)

    assert field_name in str(exc_info.value)
    repository.create_snapshot.assert_not_called()


def test_snapshot_rejects_reverse_source_range_before_persistence() -> None:
    repository = _share_repository()
    use_case = ShareSnapshotUseCases(repository=repository)

    with pytest.raises(ValidationError, match="结束日期"):
        use_case.create_snapshot(
            share_link_id=1,
            summary_payload={},
            performance_payload={},
            positions_payload={},
            transactions_payload={},
            decision_payload={},
            source_range_start=date(2026, 7, 27),
            source_range_end=date(2026, 7, 1),
        )

    repository.create_snapshot.assert_not_called()


def test_access_log_rejects_unknown_result_status() -> None:
    repository = _share_repository()
    use_case = ShareAccessUseCases(repository=repository)

    with pytest.raises(ValidationError, match="result_status"):
        use_case.log_access(
            share_link_id=1,
            ip_address="127.0.0.1",
            result_status="granted",
        )

    repository.log_access.assert_not_called()


@pytest.mark.parametrize("limit", [0, -1, 1001, True])
def test_access_logs_reject_invalid_limit(limit: int) -> None:
    repository = _share_repository()
    use_case = ShareAccessUseCases(repository=repository)

    with pytest.raises(ValidationError, match="limit"):
        use_case.get_access_logs(share_link_id=1, limit=limit)

    repository.get_access_logs.assert_not_called()
