import json
from io import StringIO

import pytest
from django.core.management import call_command

from apps.data_center.application.on_demand import DataQualityReport, EnsureDataResult
from apps.data_center.management.commands import audit_on_demand_coverage


class FakeCoverageService:
    def __init__(self):
        self.assess_calls = 0
        self.ensure_calls = 0

    def assess_price_bars(self, *args, **kwargs):
        self.assess_calls += 1
        return self._result("missing")

    def assess_valuations(self, *args, **kwargs):
        self.assess_calls += 1
        return self._result("missing")

    def assess_financials(self, *args, **kwargs):
        self.assess_calls += 1
        return self._result("missing")

    def assess_intraday(self, *args, **kwargs):
        self.assess_calls += 1
        return self._result("missing")

    def ensure_price_bars(self, *args, **kwargs):
        self.ensure_calls += 1
        return self._result("fresh")

    def ensure_valuations(self, *args, **kwargs):
        self.ensure_calls += 1
        return self._result("fresh")

    def ensure_financials(self, *args, **kwargs):
        self.ensure_calls += 1
        return self._result("fresh")

    def ensure_intraday(self, *args, **kwargs):
        self.ensure_calls += 1
        return self._result("fresh")

    def _result(self, status):
        return EnsureDataResult(
            asset_code="600031.SH",
            records=[],
            quality=DataQualityReport(status=status),
        )


@pytest.mark.django_db
def test_coverage_command_dry_run_does_not_hydrate(monkeypatch):
    fake_service = FakeCoverageService()
    monkeypatch.setattr(
        audit_on_demand_coverage,
        "make_on_demand_data_center_service",
        lambda: fake_service,
    )
    out = StringIO()

    call_command(
        "audit_on_demand_coverage",
        "--asset-code",
        "600031.SH",
        "--json",
        stdout=out,
    )

    payload = json.loads(out.getvalue())
    assert payload["mode"] == "dry_run"
    assert payload["asset_count"] == 1
    assert fake_service.assess_calls == 4
    assert fake_service.ensure_calls == 0


@pytest.mark.django_db
def test_coverage_command_hydrate_calls_ensure(monkeypatch):
    fake_service = FakeCoverageService()
    monkeypatch.setattr(
        audit_on_demand_coverage,
        "make_on_demand_data_center_service",
        lambda: fake_service,
    )
    out = StringIO()

    call_command(
        "audit_on_demand_coverage",
        "--asset-code",
        "600031.SH",
        "--hydrate",
        "--json",
        stdout=out,
    )

    payload = json.loads(out.getvalue())
    assert payload["mode"] == "hydrate"
    assert fake_service.assess_calls == 0
    assert fake_service.ensure_calls == 4
