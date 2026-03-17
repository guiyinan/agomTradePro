import json
from types import SimpleNamespace

from django.test import RequestFactory

from apps.regime.interface.views import regime_dashboard_view


class _FakeSources:
    def filter(self, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def exists(self):
        return True

    def first(self):
        return SimpleNamespace(source_type="akshare")


def test_regime_dashboard_view_handles_invalid_raw_data_values(monkeypatch):
    fake_response = SimpleNamespace(
        success=True,
        result=SimpleNamespace(
            regime=SimpleNamespace(value="Recovery"),
            growth_level=50.1,
            inflation_level=2.3,
            confidence=0.85,
            distribution={"Recovery": 0.6, "Expansion": 0.4},
        ),
        raw_data={
            "growth": [
                {"date": "2026-01", "value": "50.2"},
                {"date": "2026-02", "value": None},
                {"date": "2026-03", "value": ""},
                {"date": "2026-04", "value": "bad"},
            ],
            "inflation": [
                {"date": "2026-01", "value": "2.1"},
                {"date": "2026-02", "value": "N/A"},
            ],
        },
        warnings=[],
        error=None,
    )

    class _FakeUseCase:
        def __init__(self, repository):
            self.repository = repository

        def execute(self, request_obj):
            return fake_response

    # DjangoDataSourceConfig is instantiated as a class; provide a dummy class
    class _FakeDataSourceConfig:
        pass

    monkeypatch.setattr(
        "apps.regime.interface.views.DjangoDataSourceConfig",
        _FakeDataSourceConfig,
    )
    monkeypatch.setattr("apps.regime.interface.views.MacroRepositoryAdapter", lambda: object())
    # _get_available_sources() calls DjangoMacroSourceConfigGateway
    monkeypatch.setattr(
        "apps.regime.interface.views._get_available_sources",
        lambda: [SimpleNamespace(source_type="akshare")],
    )
    monkeypatch.setattr("apps.regime.interface.views.CalculateRegimeV2UseCase", _FakeUseCase)
    monkeypatch.setattr(
        "apps.regime.interface.views.render",
        lambda request, template_name, context: context,
    )

    request = RequestFactory().get("/regime/")
    context = regime_dashboard_view(request)

    assert context["error"] is None
    assert context["regime_result"] is not None
    assert json.loads(context["regime_result"]["growth_values"]) == [50.2, 0.0, 0.0, 0.0]
    assert json.loads(context["regime_result"]["inflation_values"]) == [2.1, 0.0]
