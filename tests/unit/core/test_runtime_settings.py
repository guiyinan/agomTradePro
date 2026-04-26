from core.integration.runtime_settings import (
    get_runtime_macro_index_codes,
    get_runtime_macro_index_metadata_map,
    get_runtime_macro_publication_lags,
)


class _FakeAccountConfigSummaryService:
    def get_runtime_macro_index_metadata_map(self) -> dict[str, dict]:
        return {"TEST.INDEX": {"unit": "点", "name": "Test"}}

    def get_runtime_macro_index_codes(self) -> list[str]:
        return ["TEST.INDEX"]

    def get_runtime_macro_publication_lags(self) -> dict[str, dict]:
        return {"TEST.INDEX": {"days": 2, "description": "T+2"}}


def test_runtime_settings_bridge_macro_configuration(monkeypatch):
    monkeypatch.setattr(
        "core.integration.runtime_settings.get_account_config_summary_service",
        lambda: _FakeAccountConfigSummaryService(),
    )

    assert get_runtime_macro_index_metadata_map()["TEST.INDEX"]["unit"] == "点"
    assert get_runtime_macro_index_codes() == ["TEST.INDEX"]
    assert get_runtime_macro_publication_lags()["TEST.INDEX"]["days"] == 2
