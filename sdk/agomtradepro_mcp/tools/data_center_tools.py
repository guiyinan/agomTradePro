"""AgomTradePro MCP Tools - Data Center tools."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from agomtradepro import AgomTradeProClient


def register_data_center_tools(server: FastMCP) -> None:
    @server.tool()
    def data_center_list_indicators(active_only: bool = False) -> list[dict[str, Any]]:
        """列出 data_center 指标目录及默认量纲规则摘要。"""
        client = AgomTradeProClient()
        return client.data_center.list_indicators(active_only=active_only)

    @server.tool()
    def data_center_list_publishers(active_only: bool = False) -> list[dict[str, Any]]:
        """列出 provenance publisher 代码表。"""
        client = AgomTradeProClient()
        return client.data_center.list_publishers(active_only=active_only)

    @server.tool()
    def data_center_get_publisher(publisher_code: str) -> dict[str, Any]:
        """读取单个 provenance publisher 定义。"""
        client = AgomTradeProClient()
        return client.data_center.get_publisher(publisher_code)

    @server.tool()
    def data_center_create_publisher(
        code: str,
        canonical_name: str,
        publisher_class: str,
        aliases: list[str] | None = None,
        canonical_name_en: str = "",
        country_code: str = "CN",
        website: str = "",
        is_active: bool = True,
        description: str = "",
    ) -> dict[str, Any]:
        """创建 provenance publisher 定义。"""
        client = AgomTradeProClient()
        return client.data_center.create_publisher(
            {
                "code": code,
                "canonical_name": canonical_name,
                "publisher_class": publisher_class,
                "aliases": aliases or [],
                "canonical_name_en": canonical_name_en,
                "country_code": country_code,
                "website": website,
                "is_active": is_active,
                "description": description,
            }
        )

    @server.tool()
    def data_center_update_publisher(
        publisher_code: str,
        canonical_name: str | None = None,
        publisher_class: str | None = None,
        aliases: list[str] | None = None,
        canonical_name_en: str | None = None,
        country_code: str | None = None,
        website: str | None = None,
        is_active: bool | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """更新 provenance publisher 定义。"""
        client = AgomTradeProClient()
        payload: dict[str, Any] = {}
        if canonical_name is not None:
            payload["canonical_name"] = canonical_name
        if publisher_class is not None:
            payload["publisher_class"] = publisher_class
        if aliases is not None:
            payload["aliases"] = aliases
        if canonical_name_en is not None:
            payload["canonical_name_en"] = canonical_name_en
        if country_code is not None:
            payload["country_code"] = country_code
        if website is not None:
            payload["website"] = website
        if is_active is not None:
            payload["is_active"] = is_active
        if description is not None:
            payload["description"] = description
        return client.data_center.update_publisher(publisher_code, payload)

    @server.tool()
    def data_center_delete_publisher(publisher_code: str) -> dict[str, Any]:
        """删除 provenance publisher 定义。"""
        client = AgomTradeProClient()
        return client.data_center.delete_publisher(publisher_code)

    @server.tool()
    def data_center_get_indicator(indicator_code: str) -> dict[str, Any]:
        """读取单个指标目录定义。"""
        client = AgomTradeProClient()
        return client.data_center.get_indicator(indicator_code)

    @server.tool()
    def data_center_create_indicator(
        code: str,
        name_cn: str,
        default_period_type: str = "M",
        name_en: str = "",
        description: str = "",
        category: str = "",
        is_active: bool = True,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """创建 data_center 指标目录项。"""
        client = AgomTradeProClient()
        return client.data_center.create_indicator(
            {
                "code": code,
                "name_cn": name_cn,
                "name_en": name_en,
                "description": description,
                "category": category,
                "default_period_type": default_period_type,
                "is_active": is_active,
                "extra": extra or {},
            }
        )

    @server.tool()
    def data_center_update_indicator(
        indicator_code: str,
        name_cn: str | None = None,
        name_en: str | None = None,
        description: str | None = None,
        category: str | None = None,
        default_period_type: str | None = None,
        is_active: bool | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """更新 data_center 指标目录项。"""
        client = AgomTradeProClient()
        payload: dict[str, Any] = {}
        if name_cn is not None:
            payload["name_cn"] = name_cn
        if name_en is not None:
            payload["name_en"] = name_en
        if description is not None:
            payload["description"] = description
        if category is not None:
            payload["category"] = category
        if default_period_type is not None:
            payload["default_period_type"] = default_period_type
        if is_active is not None:
            payload["is_active"] = is_active
        if extra is not None:
            payload["extra"] = extra
        return client.data_center.update_indicator(indicator_code, payload)

    @server.tool()
    def data_center_delete_indicator(indicator_code: str) -> dict[str, Any]:
        """删除 data_center 指标目录项。"""
        client = AgomTradeProClient()
        return client.data_center.delete_indicator(indicator_code)

    @server.tool()
    def data_center_list_indicator_unit_rules(indicator_code: str) -> list[dict[str, Any]]:
        """列出指定指标的量纲/单位规则。"""
        client = AgomTradeProClient()
        return client.data_center.list_indicator_unit_rules(indicator_code)

    @server.tool()
    def data_center_get_indicator_unit_rule(
        indicator_code: str,
        rule_id: int,
    ) -> dict[str, Any]:
        """读取指定指标的单条量纲规则。"""
        client = AgomTradeProClient()
        return client.data_center.get_indicator_unit_rule(indicator_code, rule_id)

    @server.tool()
    def data_center_create_indicator_unit_rule(
        indicator_code: str,
        dimension_key: str,
        storage_unit: str,
        display_unit: str,
        multiplier_to_storage: float,
        source_type: str = "",
        original_unit: str = "",
        is_active: bool = True,
        priority: int = 0,
        description: str = "",
    ) -> dict[str, Any]:
        """为指标创建量纲/单位规则。"""
        client = AgomTradeProClient()
        return client.data_center.create_indicator_unit_rule(
            indicator_code,
            {
                "source_type": source_type,
                "dimension_key": dimension_key,
                "original_unit": original_unit,
                "storage_unit": storage_unit,
                "display_unit": display_unit,
                "multiplier_to_storage": multiplier_to_storage,
                "is_active": is_active,
                "priority": priority,
                "description": description,
            },
        )

    @server.tool()
    def data_center_update_indicator_unit_rule(
        indicator_code: str,
        rule_id: int,
        source_type: str | None = None,
        dimension_key: str | None = None,
        original_unit: str | None = None,
        storage_unit: str | None = None,
        display_unit: str | None = None,
        multiplier_to_storage: float | None = None,
        is_active: bool | None = None,
        priority: int | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """更新指标量纲/单位规则。"""
        client = AgomTradeProClient()
        payload: dict[str, Any] = {}
        if source_type is not None:
            payload["source_type"] = source_type
        if dimension_key is not None:
            payload["dimension_key"] = dimension_key
        if original_unit is not None:
            payload["original_unit"] = original_unit
        if storage_unit is not None:
            payload["storage_unit"] = storage_unit
        if display_unit is not None:
            payload["display_unit"] = display_unit
        if multiplier_to_storage is not None:
            payload["multiplier_to_storage"] = multiplier_to_storage
        if is_active is not None:
            payload["is_active"] = is_active
        if priority is not None:
            payload["priority"] = priority
        if description is not None:
            payload["description"] = description
        return client.data_center.update_indicator_unit_rule(indicator_code, rule_id, payload)

    @server.tool()
    def data_center_delete_indicator_unit_rule(
        indicator_code: str,
        rule_id: int,
    ) -> dict[str, Any]:
        """删除指标量纲/单位规则。"""
        client = AgomTradeProClient()
        return client.data_center.delete_indicator_unit_rule(indicator_code, rule_id)

    @server.tool()
    def data_center_get_quotes(
        asset_code: str,
        strict_freshness: bool | None = None,
        max_age_hours: float | None = None,
    ) -> dict[str, Any]:
        """读取指定资产的最新行情快照，可选启用 freshness 严格模式。"""
        client = AgomTradeProClient()
        return client.data_center.get_latest_quotes(
            asset_code,
            strict_freshness=strict_freshness,
            max_age_hours=max_age_hours,
        )

    @server.tool()
    def data_center_get_price_history(
        asset_code: str,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """读取指定资产的历史价格。"""
        client = AgomTradeProClient()
        return client.data_center.get_price_history(asset_code, start=start, end=end, limit=limit)

    @server.tool()
    def data_center_get_macro_series(
        indicator_code: str,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """读取指定宏观指标的标准化时序。

        返回值会携带宏观 provenance 契约字段，用于区分：
        - `official` 官方数据
        - `authoritative_third_party` 其他权威数据
        - `derived` 系统衍生数据

        重点字段包括：
        - `provenance_class` / `provenance_label`
        - `publisher`
        - `publisher_code` / `publisher_codes`
        - `access_channel`
        - `derivation_method`
        - `upstream_indicator_codes`
        - `is_derived`
        - `decision_grade`
        - `must_not_use_for_decision`

        其中 `derived` 序列默认仅供研究，不可直接用于决策。
        """
        client = AgomTradeProClient()
        return client.data_center.get_macro_series(indicator_code, start=start, end=end, limit=limit)

    @server.tool()
    def data_center_sync_macro(
        provider_id: int,
        indicator_code: str,
        start: str,
        end: str,
    ) -> dict[str, Any]:
        """同步指定宏观指标到 data_center 宏观事实表。"""
        client = AgomTradeProClient()
        return client.data_center.sync_macro(
            {
                "provider_id": provider_id,
                "indicator_code": indicator_code,
                "start": start,
                "end": end,
            }
        )

    @server.tool()
    def data_center_repair_decision_data_reliability(
        target_date: str | None = None,
        portfolio_id: int | None = None,
        asset_codes: list[str] | None = None,
        macro_indicator_codes: list[str] | None = None,
        strict: bool = True,
        quote_max_age_hours: float | None = None,
    ) -> dict[str, Any]:
        """修复宏观、行情、Pulse 与 Alpha 的决策级数据新鲜度。"""
        client = AgomTradeProClient()
        return client.data_center.repair_decision_data_reliability(
            target_date=target_date,
            portfolio_id=portfolio_id,
            asset_codes=asset_codes,
            macro_indicator_codes=macro_indicator_codes,
            strict=strict,
            quote_max_age_hours=quote_max_age_hours,
        )

    @server.tool()
    def data_center_get_capital_flows(
        asset_code: str,
        period: str = "5d",
    ) -> dict[str, Any]:
        """读取指定资产的资金流数据。"""
        client = AgomTradeProClient()
        return client.data_center.get_capital_flows(asset_code, period=period)

    @server.tool()
    def data_center_sync_capital_flows(
        provider_id: int,
        asset_code: str,
        period: str = "5d",
    ) -> dict[str, Any]:
        """同步指定资产的资金流事实。"""
        client = AgomTradeProClient()
        return client.data_center.sync_capital_flows(
            {
                "provider_id": provider_id,
                "asset_code": asset_code,
                "period": period,
            }
        )

    @server.tool()
    def data_center_get_news(
        asset_code: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """读取指定资产的新闻事实。"""
        client = AgomTradeProClient()
        return client.data_center.get_news(asset_code, limit=limit)

    @server.tool()
    def data_center_sync_news(
        provider_id: int,
        asset_code: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """同步指定资产的新闻事实。"""
        client = AgomTradeProClient()
        return client.data_center.sync_news(
            {
                "provider_id": provider_id,
                "asset_code": asset_code,
                "limit": limit,
            }
        )

    @server.tool()
    def get_data_center_provider_status() -> list[dict[str, Any]]:
        """获取数据中台全部 Provider 的运行状态。"""
        client = AgomTradeProClient()
        return client.data_center.get_provider_status()
