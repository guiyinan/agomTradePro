"""
AgomTradePro SDK - Data Center 数据中台模块

提供统一 Provider 管理、标准事实表查询与同步入口。
"""

from typing import Any, Optional

from .base import BaseModule


class DataCenterModule(BaseModule):
    """封装 `/api/data-center/` 下的统一数据中台端点。"""

    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/data-center")

    def list_providers(self) -> list[dict[str, Any]]:
        response = self._get("providers/")
        if isinstance(response, dict):
            return response.get("results", response.get("data", []))
        return response

    def get_provider(self, provider_id: int) -> dict[str, Any]:
        return self._get(f"providers/{provider_id}/")

    def create_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("providers/", json=payload)

    def update_provider(
        self,
        provider_id: int,
        payload: dict[str, Any],
        *,
        partial: bool = True,
    ) -> dict[str, Any]:
        if partial:
            return self._patch(f"providers/{provider_id}/", json=payload)
        return self._put(f"providers/{provider_id}/", json=payload)

    def delete_provider(self, provider_id: int) -> dict[str, Any]:
        return self._delete(f"providers/{provider_id}/")

    def test_provider_connection(self, provider_id: int) -> dict[str, Any]:
        return self._post(f"providers/{provider_id}/test/", json={})

    def get_provider_status(self) -> list[dict[str, Any]]:
        response = self._get("providers/status/")
        if isinstance(response, dict):
            return response.get("results", response.get("data", []))
        return response

    def get_settings(self) -> dict[str, Any]:
        return self._get("settings/")

    def update_settings(self, payload: dict[str, Any], *, partial: bool = True) -> dict[str, Any]:
        if partial:
            return self._patch("settings/", json=payload)
        return self._put("settings/", json=payload)

    def list_publishers(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        params = {"active_only": str(active_only).lower()} if active_only else None
        response = self._get("publishers/", params=params)
        if isinstance(response, dict):
            return response.get("results", response.get("data", []))
        return response

    def get_publisher(self, publisher_code: str) -> dict[str, Any]:
        return self._get(f"publishers/{publisher_code}/")

    def create_publisher(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("publishers/", json=payload)

    def update_publisher(self, publisher_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"publishers/{publisher_code}/", json=payload)

    def delete_publisher(self, publisher_code: str) -> dict[str, Any]:
        return self._delete(f"publishers/{publisher_code}/")

    def list_indicators(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        params = {"active_only": str(active_only).lower()} if active_only else None
        response = self._get("indicators/", params=params)
        if isinstance(response, dict):
            return response.get("results", response.get("data", []))
        return response

    def get_indicator(self, indicator_code: str) -> dict[str, Any]:
        return self._get(f"indicators/{indicator_code}/")

    def create_indicator(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("indicators/", json=payload)

    def update_indicator(self, indicator_code: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._patch(f"indicators/{indicator_code}/", json=payload)

    def delete_indicator(self, indicator_code: str) -> dict[str, Any]:
        return self._delete(f"indicators/{indicator_code}/")

    def list_indicator_unit_rules(self, indicator_code: str) -> list[dict[str, Any]]:
        response = self._get(f"indicators/{indicator_code}/unit-rules/")
        if isinstance(response, dict):
            return response.get("results", response.get("data", []))
        return response

    def get_indicator_unit_rule(self, indicator_code: str, rule_id: int) -> dict[str, Any]:
        return self._get(f"indicators/{indicator_code}/unit-rules/{rule_id}/")

    def create_indicator_unit_rule(
        self,
        indicator_code: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._post(f"indicators/{indicator_code}/unit-rules/", json=payload)

    def update_indicator_unit_rule(
        self,
        indicator_code: str,
        rule_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._patch(f"indicators/{indicator_code}/unit-rules/{rule_id}/", json=payload)

    def delete_indicator_unit_rule(self, indicator_code: str, rule_id: int) -> dict[str, Any]:
        return self._delete(f"indicators/{indicator_code}/unit-rules/{rule_id}/")

    def resolve_asset(self, code: str, source_type: str | None = None) -> dict[str, Any]:
        params = {"code": code}
        if source_type:
            params["source_type"] = source_type
        return self._get("assets/resolve/", params=params)

    def get_macro_series(
        self,
        indicator_code: str,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"indicator_code": indicator_code}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if limit is not None:
            params["limit"] = limit
        if source:
            params["source"] = source
        return self._get("macro/series/", params=params)

    def sync_macro(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("sync/macro/", json=payload)

    def get_price_history(
        self,
        asset_code: str,
        start: str | None = None,
        end: str | None = None,
        freq: str | None = None,
        adjustment: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"asset_code": asset_code}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if freq:
            params["freq"] = freq
        if adjustment:
            params["adjustment"] = adjustment
        if limit is not None:
            params["limit"] = limit
        return self._get("prices/history/", params=params)

    def sync_prices(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("sync/prices/", json=payload)

    def get_latest_quotes(
        self,
        asset_code: str,
        *,
        strict_freshness: bool | None = None,
        max_age_hours: float | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"asset_code": asset_code}
        if strict_freshness is not None:
            params["strict_freshness"] = str(strict_freshness).lower()
        if max_age_hours is not None:
            params["max_age_hours"] = max_age_hours
        return self._get("prices/quotes/", params=params)

    def sync_quotes(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("sync/quotes/", json=payload)

    def repair_decision_data_reliability(
        self,
        *,
        target_date: str | None = None,
        portfolio_id: int | None = None,
        asset_codes: list[str] | None = None,
        macro_indicator_codes: list[str] | None = None,
        strict: bool = True,
        quote_max_age_hours: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"strict": strict}
        if target_date:
            payload["target_date"] = target_date
        if portfolio_id is not None:
            payload["portfolio_id"] = portfolio_id
        if asset_codes is not None:
            payload["asset_codes"] = asset_codes
        if macro_indicator_codes is not None:
            payload["macro_indicator_codes"] = macro_indicator_codes
        if quote_max_age_hours is not None:
            payload["quote_max_age_hours"] = quote_max_age_hours
        return self._post("decision-reliability/repair/", json=payload)

    def get_fund_nav(
        self,
        fund_code: str,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"fund_code": fund_code}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if limit is not None:
            params["limit"] = limit
        return self._get("funds/nav/", params=params)

    def sync_fund_nav(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("sync/funds/nav/", json=payload)

    def get_financials(self, asset_code: str, limit: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"asset_code": asset_code}
        if limit is not None:
            params["limit"] = limit
        return self._get("financials/", params=params)

    def sync_financials(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("sync/financials/", json=payload)

    def get_valuations(
        self,
        asset_code: str,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"asset_code": asset_code}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if limit is not None:
            params["limit"] = limit
        return self._get("valuations/", params=params)

    def sync_valuations(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("sync/valuations/", json=payload)

    def get_sector_constituents(
        self,
        sector_code: str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"sector_code": sector_code}
        if as_of:
            params["as_of"] = as_of
        return self._get("sectors/constituents/", params=params)

    def sync_sector_constituents(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("sync/sectors/constituents/", json=payload)

    def get_news(self, asset_code: str, limit: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"asset_code": asset_code}
        if limit is not None:
            params["limit"] = limit
        return self._get("news/", params=params)

    def sync_news(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("sync/news/", json=payload)

    def get_capital_flows(
        self,
        asset_code: str,
        period: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"asset_code": asset_code}
        if period:
            params["period"] = period
        if limit is not None:
            params["limit"] = limit
        return self._get("capital-flows/", params=params)

    def sync_capital_flows(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("sync/capital-flows/", json=payload)
