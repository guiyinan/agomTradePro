"""
AgomTradePro SDK - Data Center 数据中台模块

提供统一 Provider 管理、标准事实表查询与同步入口。
"""

from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import urlsplit

from .base import BaseModule


def _validate_positive_identifier(value: object, field_name: str) -> None:
    """Reject identifiers that cannot be used in a staff API path."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _copy_egress_endpoint_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Copy an endpoint payload and translate safe credential field aliases.

    The MCP-facing names deliberately avoid looking like a loggable generic
    ``username``/``password`` pair.  The Django API keeps its established
    write-only field names, so translation happens at this SDK boundary.
    """

    request_payload = dict(payload)
    if "credential_username" in request_payload:
        request_payload["username"] = request_payload.pop("credential_username")
    if "credential_password" in request_payload:
        request_payload["password"] = request_payload.pop("credential_password")
    return request_payload


def _copy_egress_context(context: Mapping[str, Any], *, allow_empty: bool) -> dict[str, Any]:
    """Validate and copy a concrete provider request context.

    The server remains the source of truth for full serializer validation.  A
    small client-side check catches accidental path misuse and rejects target
    URLs containing credentials before they can reach a request transport.
    """

    if not isinstance(context, Mapping):
        raise ValueError("context must be a mapping")
    request_context = dict(context)
    if not request_context and allow_empty:
        return request_context

    required_fields = ("provider_id", "dataset_key", "url", "deployment_region")
    missing_field = next((key for key in required_fields if key not in request_context), None)
    if missing_field is not None:
        raise ValueError(f"context.{missing_field} is required")
    _validate_positive_identifier(request_context["provider_id"], "context.provider_id")

    for field_name in ("dataset_key", "deployment_region"):
        value = request_context[field_name]
        if not isinstance(value, str) or not value.strip() or "*" in value:
            raise ValueError(f"context.{field_name} must be a non-empty string")

    url = request_context["url"]
    if not isinstance(url, str) or not url.strip():
        raise ValueError("context.url must be a non-empty URL")
    try:
        parts = urlsplit(url.strip())
        hostname = parts.hostname
        _ = parts.port
    except ValueError:
        raise ValueError(
            "context.url must be an HTTP(S) URL without credentials or fragments"
        ) from None
    if (
        parts.scheme not in {"http", "https"}
        or not hostname
        or "*" in hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
    ):
        raise ValueError("context.url must be an HTTP(S) URL without credentials or fragments")
    return request_context


def _egress_results(response: Any, resource_name: str) -> list[dict[str, Any]]:
    """Extract and type-check the ``results`` list from an egress response."""

    results: object
    if isinstance(response, dict):
        results = response.get("results", [])
    else:
        results = response
    if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
        raise ValueError(f"{resource_name} response must contain a list of objects")
    return [dict(item) for item in results]


class DataCenterModule(BaseModule):
    """封装 `/api/data-center/` 下的统一数据中台端点。"""

    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/data-center")

    def list_egress_endpoints(self) -> list[dict[str, Any]]:
        """List staff-managed egress endpoint metadata without credentials."""

        response = self._get("egress/endpoints/")
        return _egress_results(response, "egress endpoint")

    def get_egress_endpoint(self, endpoint_id: int) -> dict[str, Any]:
        """Read one redacted egress endpoint by its positive numeric ID."""

        _validate_positive_identifier(endpoint_id, "endpoint_id")
        return cast(dict[str, Any], self._get(f"egress/endpoints/{endpoint_id}/"))

    def create_egress_endpoint(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create one egress endpoint, translating credential aliases safely."""

        request_payload = _copy_egress_endpoint_payload(payload)
        return cast(dict[str, Any], self._post("egress/endpoints/", json=request_payload))

    def update_egress_endpoint(
        self,
        endpoint_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch one egress endpoint while preserving omitted field semantics."""

        _validate_positive_identifier(endpoint_id, "endpoint_id")
        request_payload = _copy_egress_endpoint_payload(payload)
        return cast(
            dict[str, Any],
            self._patch(f"egress/endpoints/{endpoint_id}/", json=request_payload),
        )

    def test_egress_endpoint(
        self,
        endpoint_id: int,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a bounded test through one egress endpoint and return its outcome."""

        _validate_positive_identifier(endpoint_id, "endpoint_id")
        request_context = _copy_egress_context(
            context if context is not None else {}, allow_empty=True
        )
        return cast(
            dict[str, Any],
            self._post(f"egress/endpoints/{endpoint_id}/test/", json=request_context),
        )

    def list_egress_rules(self) -> list[dict[str, Any]]:
        """List staff-managed provider and domain routing rules."""

        response = self._get("egress/rules/")
        return _egress_results(response, "egress rule")

    def get_egress_rule(self, rule_id: int) -> dict[str, Any]:
        """Read one egress routing rule by its positive numeric ID."""

        _validate_positive_identifier(rule_id, "rule_id")
        return cast(dict[str, Any], self._get(f"egress/rules/{rule_id}/"))

    def create_egress_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create one provider/domain egress routing rule."""

        return cast(dict[str, Any], self._post("egress/rules/", json=dict(payload)))

    def update_egress_rule(self, rule_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """Patch one egress routing rule while retaining omitted values."""

        _validate_positive_identifier(rule_id, "rule_id")
        return cast(
            dict[str, Any],
            self._patch(f"egress/rules/{rule_id}/", json=dict(payload)),
        )

    def preview_egress_route(self, context: dict[str, Any]) -> dict[str, Any]:
        """Preview route selection for one concrete provider request context."""

        request_context = _copy_egress_context(context, allow_empty=False)
        return cast(dict[str, Any], self._post("egress/rules/preview/", json=request_context))

    def diagnose_egress_route(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run a bounded route diagnostic and preserve blocked outcomes."""

        request_context = _copy_egress_context(context, allow_empty=False)
        return cast(dict[str, Any], self._post("egress/diagnostics/", json=request_context))

    def list_providers(self) -> list[dict[str, Any]]:
        """Return the provider catalog exposed by the data center."""

        response = self._get("providers/")
        if isinstance(response, dict):
            return cast(list[dict[str, Any]], response.get("results", response.get("data", [])))
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
        """Return the provider health and availability records."""

        response = self._get("providers/status/")
        if isinstance(response, dict):
            return cast(list[dict[str, Any]], response.get("results", response.get("data", [])))
        return response

    def get_settings(self) -> dict[str, Any]:
        return self._get("settings/")

    def update_settings(self, payload: dict[str, Any], *, partial: bool = True) -> dict[str, Any]:
        if partial:
            return self._patch("settings/", json=payload)
        return self._put("settings/", json=payload)

    def list_publishers(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        """Return publisher catalog records with an optional active filter."""

        params = {"active_only": str(active_only).lower()} if active_only else None
        response = self._get("publishers/", params=params)
        if isinstance(response, dict):
            return cast(list[dict[str, Any]], response.get("results", response.get("data", [])))
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
        """Return indicator catalog records with an optional active filter."""

        params = {"active_only": str(active_only).lower()} if active_only else None
        response = self._get("indicators/", params=params)
        if isinstance(response, dict):
            return cast(list[dict[str, Any]], response.get("results", response.get("data", [])))
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
        """Return canonical unit rules for the selected indicator."""

        response = self._get(f"indicators/{indicator_code}/unit-rules/")
        if isinstance(response, dict):
            return cast(list[dict[str, Any]], response.get("results", response.get("data", [])))
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
        mode: str | None = "published",
        publication_key: str | None = None,
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
        if mode:
            params["mode"] = mode
        if publication_key:
            params["publication_key"] = publication_key
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
        mode: str | None = "published",
        publication_key: str | None = None,
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
        if mode:
            params["mode"] = mode
        if publication_key:
            params["publication_key"] = publication_key
        return self._get("prices/history/", params=params)

    def sync_prices(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("sync/prices/", json=payload)

    def get_latest_quotes(
        self,
        asset_code: str,
        *,
        strict_freshness: bool | None = None,
        max_age_hours: float | None = None,
        mode: str | None = "published",
        publication_key: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"asset_code": asset_code}
        if strict_freshness is not None:
            params["strict_freshness"] = str(strict_freshness).lower()
        if max_age_hours is not None:
            params["max_age_hours"] = max_age_hours
        if mode:
            params["mode"] = mode
        if publication_key:
            params["publication_key"] = publication_key
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
        mode: str | None = "published",
        publication_key: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"fund_code": fund_code}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if limit is not None:
            params["limit"] = limit
        if mode:
            params["mode"] = mode
        if publication_key:
            params["publication_key"] = publication_key
        return self._get("funds/nav/", params=params)

    def sync_fund_nav(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("sync/funds/nav/", json=payload)

    def get_financials(
        self,
        asset_code: str,
        limit: int | None = None,
        *,
        mode: str | None = "published",
        publication_key: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"asset_code": asset_code}
        if limit is not None:
            params["limit"] = limit
        if mode:
            params["mode"] = mode
        if publication_key:
            params["publication_key"] = publication_key
        return self._get("financials/", params=params)

    def sync_financials(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("sync/financials/", json=payload)

    def get_valuations(
        self,
        asset_code: str,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
        mode: str | None = "published",
        publication_key: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"asset_code": asset_code}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if limit is not None:
            params["limit"] = limit
        if mode:
            params["mode"] = mode
        if publication_key:
            params["publication_key"] = publication_key
        return self._get("valuations/", params=params)

    def sync_valuations(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("sync/valuations/", json=payload)

    def get_sector_constituents(
        self,
        sector_code: str,
        as_of: str | None = None,
        *,
        mode: str | None = "published",
        publication_key: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"sector_code": sector_code}
        if as_of:
            params["as_of"] = as_of
        if mode:
            params["mode"] = mode
        if publication_key:
            params["publication_key"] = publication_key
        return self._get("sectors/constituents/", params=params)

    def sync_sector_constituents(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("sync/sectors/constituents/", json=payload)

    def get_news(
        self,
        asset_code: str,
        limit: int | None = None,
        *,
        mode: str | None = "published",
        publication_key: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"asset_code": asset_code}
        if limit is not None:
            params["limit"] = limit
        if mode:
            params["mode"] = mode
        if publication_key:
            params["publication_key"] = publication_key
        return self._get("news/", params=params)

    def sync_news(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("sync/news/", json=payload)

    def get_capital_flows(
        self,
        asset_code: str,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
        mode: str | None = "published",
        publication_key: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"asset_code": asset_code}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if limit is not None:
            params["limit"] = limit
        if mode:
            params["mode"] = mode
        if publication_key:
            params["publication_key"] = publication_key
        return self._get("capital-flows/", params=params)

    def sync_capital_flows(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("sync/capital-flows/", json=payload)
