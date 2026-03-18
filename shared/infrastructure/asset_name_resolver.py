"""
Asset Name Resolver - 资产名称解析服务

提供统一的资产代码到资产名称的解析功能，支持股票、基金、指数等多种资产类型。
"""

import hashlib
import json
import logging
from typing import Dict, List, Set

from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_PREFIX = "asset_names"
CACHE_TTL = 3600


class AssetNameResolver:
    """
    资产名称解析器。

    根据资产代码从数据库中查询对应的资产名称。
    支持股票、基金、指数等多种资产类型。
    """

    def resolve_asset_names(self, codes: List[str]) -> Dict[str, str]:
        """
        批量解析资产代码对应的名称。

        Args:
            codes: 资产代码列表

        Returns:
            Dict[str, str]: 资产代码到名称的映射，未找到的代码不会出现在结果中
        """
        code_set: Set[str] = {code for code in codes if code}
        if not code_set:
            return {}

        resolved: Dict[str, str] = {}

        resolved.update(self._resolve_stocks(code_set - set(resolved.keys())))
        resolved.update(self._resolve_funds(code_set - set(resolved.keys())))
        resolved.update(self._resolve_indices(code_set - set(resolved.keys())))

        return resolved

    def resolve_asset_name(self, code: str) -> str:
        """
        解析单个资产代码对应的名称。

        Args:
            code: 资产代码

        Returns:
            str: 资产名称，如果未找到则返回代码本身
        """
        if not code:
            return code

        result = self.resolve_asset_names([code])
        return result.get(code, code)

    def _resolve_stocks(self, codes: Set[str]) -> Dict[str, str]:
        """从股票信息表解析名称"""
        if not codes:
            return {}

        resolved: Dict[str, str] = {}
        try:
            from apps.equity.infrastructure.models import StockInfoModel

            rows = StockInfoModel._default_manager.filter(stock_code__in=list(codes)).values(
                "stock_code", "name"
            )
            for row in rows:
                if row["name"]:
                    resolved[row["stock_code"]] = row["name"]
        except Exception as e:
            logger.warning("Failed to resolve stock names: %s", e)

        return resolved

    def _resolve_funds(self, codes: Set[str]) -> Dict[str, str]:
        """从基金信息表解析名称"""
        if not codes:
            return {}

        resolved: Dict[str, str] = {}
        try:
            from apps.fund.infrastructure.models import FundInfoModel

            code_to_fund_code = {code: code.split(".")[0] for code in codes}
            rows = FundInfoModel._default_manager.filter(
                fund_code__in=list(set(code_to_fund_code.values()))
            ).values("fund_code", "fund_name")
            fund_name_map = {row["fund_code"]: row["fund_name"] for row in rows}
            for code, fund_code in code_to_fund_code.items():
                if fund_code in fund_name_map and fund_name_map[fund_code]:
                    resolved[code] = fund_name_map[fund_code]
        except Exception as e:
            logger.warning("Failed to resolve fund names: %s", e)

        return resolved

    def _resolve_indices(self, codes: Set[str]) -> Dict[str, str]:
        """从资产池条目表解析名称"""
        if not codes:
            return {}

        resolved: Dict[str, str] = {}
        try:
            from apps.asset_analysis.infrastructure.models import AssetPoolEntry

            rows = (
                AssetPoolEntry._default_manager.filter(asset_code__in=list(codes))
                .values("asset_code", "asset_name")
                .distinct()
            )
            for row in rows:
                if row["asset_name"]:
                    resolved[row["asset_code"]] = row["asset_name"]
        except Exception as e:
            logger.debug("Failed to resolve index names from AssetPoolEntry: %s", e)

        return resolved


def _build_cache_key(codes: List[str]) -> str:
    """构建缓存键"""
    sorted_codes = sorted(set(c for c in codes if c))
    codes_hash = hashlib.md5(json.dumps(sorted_codes).encode()).hexdigest()
    return f"{CACHE_PREFIX}:{codes_hash}"


def resolve_asset_names(codes: List[str]) -> Dict[str, str]:
    """
    批量解析资产代码对应的名称（带缓存）。

    Args:
        codes: 资产代码列表

    Returns:
        Dict[str, str]: 资产代码到名称的映射
    """
    code_set = {code for code in codes if code}
    if not code_set:
        return {}

    cache_key = _build_cache_key(list(code_set))

    try:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    except Exception as e:
        logger.warning("Cache get failed: %s", e)

    resolver = AssetNameResolver()
    result = resolver.resolve_asset_names(list(code_set))

    try:
        cache.set(cache_key, result, CACHE_TTL)
    except Exception as e:
        logger.warning("Cache set failed: %s", e)

    return result


def resolve_asset_name(code: str) -> str:
    """
    解析单个资产代码对应的名称。

    Args:
        code: 资产代码

    Returns:
        str: 资产名称，如果未找到则返回代码本身
    """
    if not code:
        return code

    result = resolve_asset_names([code])
    return result.get(code, code)


def enrich_with_asset_names(
    items: List[dict], code_field: str = "asset_code", name_field: str = "asset_name"
) -> List[dict]:
    """
    为字典列表批量添加资产名称字段。

    Args:
        items: 字典列表
        code_field: 代码字段名
        name_field: 名称字段名

    Returns:
        List[dict]: 添加了名称字段的字典列表
    """
    if not items:
        return items

    codes = [item.get(code_field) for item in items if item.get(code_field)]
    if not codes:
        return items

    name_map = resolve_asset_names(codes)

    for item in items:
        code = item.get(code_field)
        if code and not item.get(name_field):
            item[name_field] = name_map.get(code, code)

    return items
