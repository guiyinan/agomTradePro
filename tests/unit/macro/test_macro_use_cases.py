from datetime import date
from types import SimpleNamespace

from apps.macro.application.use_cases import (
    SyncMacroDataRequest,
    build_sync_macro_data_use_case,
)


class _FakeBatchUseCase:
    def __init__(self) -> None:
        self.request = None

    def execute(self, request):
        self.request = request
        return SimpleNamespace(stored_count=3, errors=[])


def test_build_sync_macro_data_use_case_delegates_to_canonical_batch(monkeypatch):
    batch = _FakeBatchUseCase()
    monkeypatch.setattr(
        "apps.data_center.application.interface_services.make_sync_macro_batch_use_case",
        lambda: batch,
    )

    use_case = build_sync_macro_data_use_case("akshare")
    response = use_case.execute(
        SyncMacroDataRequest(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 2, 1),
            indicators=["CN_PMI"],
        )
    )

    assert batch.request.source == "akshare"
    assert batch.request.indicator_codes == ["CN_PMI"]
    assert response.success is True
    assert response.synced_count == 3


def test_build_sync_macro_data_use_case_preserves_batch_errors(monkeypatch):
    batch = _FakeBatchUseCase()
    batch.execute = lambda request: SimpleNamespace(
        stored_count=0,
        errors=["CN_PMI: unavailable"],
    )
    monkeypatch.setattr(
        "apps.data_center.application.interface_services.make_sync_macro_batch_use_case",
        lambda: batch,
    )

    response = build_sync_macro_data_use_case().execute(
        SyncMacroDataRequest(
            start_date=date(2025, 1, 1),
            indicators=["CN_PMI"],
        )
    )

    assert response.success is False
    assert response.errors == ["CN_PMI: unavailable"]
