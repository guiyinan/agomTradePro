"""AgomTradePro SDK - Audit 模块。"""

from datetime import date, timedelta
from typing import Any

from .base import BaseModule


class AuditModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/audit")

    def generate_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("reports/generate/", json=payload)

    def get_summary(
        self,
        backtest_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if backtest_id is not None:
            params["backtest_id"] = backtest_id
        elif start_date and end_date:
            params["start_date"] = start_date
            params["end_date"] = end_date
        else:
            end = date.today()
            start = end - timedelta(days=30)
            params["start_date"] = start.isoformat()
            params["end_date"] = end.isoformat()
        return self._get("summary/", params=params)

    def get_attribution_chart_data(self, report_id: int) -> dict[str, Any]:
        return self._get(f"attribution-chart-data/{report_id}/")

    def indicator_performance(self, indicator_code: str) -> dict[str, Any]:
        return self._get(f"indicator-performance/{indicator_code}/")

    def indicator_performance_chart(self, validation_id: int) -> dict[str, Any]:
        return self._get(f"indicator-performance-data/{validation_id}/")

    def validate_all_indicators(self) -> dict[str, Any]:
        end = date.today()
        start = end - timedelta(days=30)
        return self._post(
            "validate-all-indicators/",
            json={
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )

    def update_threshold(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("update-threshold/", json=payload)

    def threshold_validation_data(self, summary_id: int) -> dict[str, Any]:
        return self._get(f"threshold-validation-data/{summary_id}/")

    def run_validation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("run-validation/", json=payload)
