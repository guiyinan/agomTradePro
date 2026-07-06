from types import SimpleNamespace

from apps.signal.application.query_services import build_signal_management_context


def test_build_signal_management_context_uses_asset_analysis_name_service(monkeypatch):
    signal = SimpleNamespace(asset_code="000001.SZ", asset_name="")

    class StubSignalRepository:
        def list_signal_records(self, **kwargs):
            return [signal]

        def get_signal_management_metadata(self):
            return {
                "stats": {},
                "asset_classes": [],
                "directions": [],
            }

    monkeypatch.setattr(
        "apps.signal.application.query_services.DjangoSignalRepository",
        lambda: StubSignalRepository(),
    )
    monkeypatch.setattr(
        "apps.signal.application.query_services.resolve_asset_names",
        lambda asset_codes: {code: f"name:{code}" for code in asset_codes},
    )
    monkeypatch.setattr(
        "apps.signal.application.query_services.get_current_regime_payload",
        lambda: {"dominant_regime": "Recovery"},
    )
    monkeypatch.setattr(
        "apps.signal.application.query_services.get_recommended_assets_payload",
        lambda regime: {"recommended": [], "neutral": [], "hostile": []},
    )
    monkeypatch.setattr(
        "apps.signal.application.query_services.get_available_indicators_for_frontend",
        lambda: [],
    )
    monkeypatch.setattr(
        "apps.signal.application.query_services.get_eligibility_matrix",
        lambda: {},
    )

    context = build_signal_management_context()

    assert context["signals"][0].asset_name == "name:000001.SZ"
