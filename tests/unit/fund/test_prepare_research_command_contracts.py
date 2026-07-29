"""Fund research preparation command contracts."""

from __future__ import annotations

from datetime import date
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management.base import CommandError

from apps.fund.management.commands import prepare_fund_research_data


def _options(**overrides: object) -> dict[str, object]:
    options: dict[str, object] = {
        "fund_codes": "000001,000002,000003",
        "fund_types": "",
        "max_funds": 30,
        "start_date": "2026-01-01",
        "end_date": "2026-07-24",
        "skip_info_sync": False,
        "allow_remote_nav_sync": False,
    }
    options.update(overrides)
    return options


def test_prepare_fund_research_reports_prepared_skipped_and_failed(monkeypatch) -> None:
    """One provider failure or missing NAV does not hide successfully prepared funds."""

    class _Repo:
        def ensure_fund_universe_seeded(self) -> int:
            return 5

        def get_or_build_fund_performance(self, **kwargs: object):
            code = kwargs["fund_code"]
            if code == "000003":
                raise RuntimeError("offline")
            if code == "000002":
                return None
            return SimpleNamespace(
                start_date=date(2026, 1, 1),
                end_date=date(2026, 7, 24),
                total_return=12.34,
            )

    monkeypatch.setattr(prepare_fund_research_data, "DjangoFundRepository", _Repo)
    output = StringIO()
    prepare_fund_research_data.Command(stdout=output).handle(**_options())
    text = output.getvalue()
    assert "Fund info sync completed: 5 rows" in text
    assert "Prepared funds: 1" in text
    assert "Skipped funds: 1" in text
    assert "Failed funds (1): 000003" in text


def test_prepare_fund_research_validates_dates_sync_and_universe(monkeypatch) -> None:
    """Invalid windows, provider failures, and empty universes become actionable errors."""
    monkeypatch.setattr(
        prepare_fund_research_data,
        "DjangoFundRepository",
        lambda: SimpleNamespace(),
    )
    with pytest.raises(CommandError, match="earlier"):
        prepare_fund_research_data.Command(stdout=StringIO()).handle(
            **_options(start_date="2026-07-24", end_date="2026-07-24")
        )
    command = prepare_fund_research_data.Command(stdout=StringIO())
    with pytest.raises(CommandError, match="fund research date is invalid"):
        command._parse_date("bad-date", default=date.today())

    class _BrokenRepo:
        def ensure_fund_universe_seeded(self) -> int:
            raise RuntimeError("master unavailable")

    monkeypatch.setattr(prepare_fund_research_data, "DjangoFundRepository", _BrokenRepo)
    with pytest.raises(CommandError, match="fund_master_sync_failed"):
        prepare_fund_research_data.Command(stdout=StringIO()).handle(**_options())

    class _EmptyRepo:
        def ensure_fund_universe_seeded(self) -> int:
            return 0

    monkeypatch.setattr(prepare_fund_research_data, "DjangoFundRepository", _EmptyRepo)
    monkeypatch.setattr(
        prepare_fund_research_data.Command,
        "_resolve_fund_codes",
        lambda self, options: [],
    )
    with pytest.raises(CommandError, match="No fund codes"):
        prepare_fund_research_data.Command(stdout=StringIO()).handle(**_options())


def test_fund_code_resolution_uses_explicit_codes_or_local_filters(monkeypatch) -> None:
    """Explicit input wins; otherwise type filters and a positive limit select local codes."""
    command = prepare_fund_research_data.Command(stdout=StringIO())
    assert command._resolve_fund_codes(_options(fund_codes=" 000001, 000002 ")) == [
        "000001",
        "000002",
    ]

    class _Query:
        def __init__(self) -> None:
            self.filters: list[dict[str, object]] = []

        def filter(self, **kwargs: object) -> _Query:
            self.filters.append(kwargs)
            return self

        def order_by(self, *args: object) -> _Query:
            return self

        def values_list(self, *args: object, **kwargs: object) -> list[str]:
            return ["000010", "000011"]

        def __getitem__(self, key: slice) -> _Query:
            return self

        def __iter__(self):
            return iter(["000010", "000011"])

    query = _Query()
    monkeypatch.setattr(
        prepare_fund_research_data,
        "FundInfoModel",
        SimpleNamespace(_default_manager=query),
    )
    with pytest.raises(CommandError, match="max-funds"):
        command._resolve_fund_codes(
            _options(fund_codes="", fund_types=" equity, bond ", max_funds=0)
        )

    resolved = command._resolve_fund_codes(
        _options(fund_codes="", fund_types=" equity, bond ", max_funds=1)
    )
    assert resolved == ["000010"]
    assert query.filters[-1] == {"fund_type__in": ["equity", "bond"]}
