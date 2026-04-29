from apps.macro.application.interface_services import get_supported_macro_indicators


class _FakeAdapter:
    SUPPORTED_INDICATORS = {
        "CN_GDP": "GDP",
        "CN_M2": "M2",
    }


class _FakeSyncUseCase:
    def __init__(self):
        self.adapters = {"akshare": _FakeAdapter()}


def test_get_supported_macro_indicators_prefers_indicator_metadata(monkeypatch):
    monkeypatch.setattr(
        "apps.macro.application.interface_services.build_sync_macro_data_use_case",
        lambda source="akshare": _FakeSyncUseCase(),
    )
    monkeypatch.setattr(
        "apps.macro.application.interface_services.IndicatorService.get_indicator_metadata_map",
        classmethod(
            lambda cls: {
                "CN_GDP": {"name": "GDP（国内生产总值累计值）"},
                "CN_M2": {"name": "M2（广义货币供应量余额）"},
            }
        ),
    )

    indicators = get_supported_macro_indicators()

    assert indicators == [
        {"code": "CN_GDP", "name": "GDP（国内生产总值累计值）"},
        {"code": "CN_M2", "name": "M2（广义货币供应量余额）"},
    ]
