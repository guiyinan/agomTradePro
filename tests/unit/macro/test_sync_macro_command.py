from datetime import date
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.macro.management.commands import sync_macro_data as sync_macro_module


class _FakeSyncUseCase:
    def __init__(self, result) -> None:
        self.result = result
        self.request = None

    def execute(self, request):
        self.request = request
        return self.result


def test_sync_macro_command_uses_canonical_macro_sync_builder(monkeypatch, capsys):
    use_case = _FakeSyncUseCase(SimpleNamespace(success=True, synced_count=2, errors=[]))
    captured_source = {}

    def _build(source):
        captured_source["value"] = source
        return use_case

    monkeypatch.setattr(sync_macro_module, "build_sync_macro_data_use_case", _build)

    call_command(
        "sync_macro_data",
        source="akshare",
        indicators=["CN_GDP_YOY", "CN_PMI"],
        years=1,
    )

    assert captured_source["value"] == "akshare"
    assert use_case.request.indicators == ["CN_GDP_YOY", "CN_PMI"]
    assert use_case.request.force_refresh is True
    assert "成功保存 2 条" in capsys.readouterr().out


def test_sync_macro_command_reports_canonical_batch_errors(monkeypatch, capsys):
    use_case = _FakeSyncUseCase(
        SimpleNamespace(
            success=False,
            synced_count=0,
            errors=["postgresql://operator:secret@db.internal/macro"],
        )
    )
    monkeypatch.setattr(
        sync_macro_module,
        "build_sync_macro_data_use_case",
        lambda source: use_case,
    )

    call_command(
        "sync_macro_data",
        source="akshare",
        indicators=["CN_PMI"],
        years=1,
    )

    captured = capsys.readouterr()
    assert "macro_sync_failed" in captured.err
    assert "operator:secret" not in captured.err


def test_sync_macro_command_uses_explicit_validated_date_range(monkeypatch):
    use_case = _FakeSyncUseCase(SimpleNamespace(success=True, synced_count=1, errors=[]))
    monkeypatch.setattr(
        sync_macro_module,
        "build_sync_macro_data_use_case",
        lambda _source: use_case,
    )

    call_command(
        "sync_macro_data",
        source="akshare",
        indicators=["CN_PMI"],
        start="2020-01-01",
        end="2024-12-31",
    )

    assert use_case.request.start_date == date(2020, 1, 1)
    assert use_case.request.end_date == date(2024, 12, 31)


def test_sync_macro_command_lists_canonical_catalog_without_sync(monkeypatch, capsys):
    monkeypatch.setattr(
        sync_macro_module,
        "list_macro_indicator_codes",
        lambda: ["CN_PMI", "CN_CPI", "CN_PMI"],
    )
    monkeypatch.setattr(
        sync_macro_module,
        "build_sync_macro_data_use_case",
        lambda _source: (_ for _ in ()).throw(AssertionError("sync must not run")),
    )

    call_command("sync_macro_data", list_indicators=True)

    assert capsys.readouterr().out.splitlines() == ["CN_CPI", "CN_PMI"]


@pytest.mark.parametrize(
    ("options", "error_code"),
    [
        ({"source": "unknown", "indicators": ["CN_PMI"], "years": 1}, "macro_source_invalid"),
        ({"source": "akshare", "indicators": ["CN_PMI"], "years": 0}, "macro_years_invalid"),
        (
            {"source": "akshare", "indicators": ["CN_PMI", "CN_PMI"], "years": 1},
            "macro_indicators_invalid",
        ),
        (
            {
                "source": "akshare",
                "indicators": ["CN_PMI"],
                "years": 1,
                "start": "2024-01-01",
            },
            "macro_date_range_incomplete",
        ),
        (
            {
                "source": "akshare",
                "indicators": ["CN_PMI"],
                "years": 1,
                "start": "2024-02-01",
                "end": "2024-01-01",
            },
            "macro_date_range_invalid",
        ),
    ],
)
def test_sync_macro_command_rejects_invalid_direct_call_options(options, error_code):
    with pytest.raises(CommandError, match=error_code):
        sync_macro_module.Command().handle(**options)
