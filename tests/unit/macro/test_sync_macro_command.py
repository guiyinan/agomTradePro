from types import SimpleNamespace

from django.core.management import call_command

from apps.macro.management.commands import sync_macro_data as sync_macro_module


class _FakeSyncUseCase:
    def __init__(self, result) -> None:
        self.result = result
        self.request = None

    def execute(self, request):
        self.request = request
        return self.result


def test_sync_macro_command_uses_canonical_macro_sync_builder(monkeypatch, capsys):
    use_case = _FakeSyncUseCase(
        SimpleNamespace(success=True, synced_count=2, errors=[])
    )
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
            errors=["CN_PMI: unavailable"],
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
    assert "CN_PMI: unavailable" in captured.err
