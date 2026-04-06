from datetime import date

from apps.alpha.management.commands.build_qlib_data import (
    _build_qlib_blocker_message,
)


def test_build_qlib_blocker_message_requires_tushare_token_for_stale_data() -> None:
    message = _build_qlib_blocker_message(
        date(2020, 9, 25),
        target_date=date(2026, 4, 6),
        has_tushare_token=True,
    )

    assert message is not None
    assert "2020-09-25" in message
    assert "python manage.py build_qlib_data" in message


def test_build_qlib_blocker_message_requires_token_when_missing() -> None:
    message = _build_qlib_blocker_message(
        date(2020, 9, 25),
        target_date=date(2026, 4, 6),
        has_tushare_token=False,
    )

    assert message is not None
    assert "Tushare Token" in message


def test_build_qlib_blocker_message_returns_none_when_data_is_fresh() -> None:
    message = _build_qlib_blocker_message(
        date(2026, 4, 4),
        target_date=date(2026, 4, 6),
        has_tushare_token=False,
    )

    assert message is None
