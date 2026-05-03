"""
Dynamic indicator metadata and unit services backed by data_center.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.data_center.application.repository_provider import (
    get_indicator_catalog_repository,
    get_indicator_unit_rule_repository,
)
from apps.macro.application.repository_provider import get_macro_read_repository
from apps.macro.domain.entities import convert_currency_value

logger = logging.getLogger(__name__)


class UnitDisplayService:
    """Convert canonical storage values back to display values for UI."""

    read_repository = get_macro_read_repository()

    @staticmethod
    def convert_for_display(
        stored_value: float,
        storage_unit: str,
        original_unit: str,
    ) -> tuple[float, str]:
        if not original_unit:
            return stored_value, storage_unit
        if storage_unit == original_unit:
            return stored_value, original_unit
        converted_value, converted_unit = convert_currency_value(
            stored_value,
            storage_unit,
            original_unit,
        )
        if converted_unit == original_unit:
            return converted_value, converted_unit
        return stored_value, original_unit or storage_unit

    @classmethod
    def format_for_display(
        cls,
        stored_value: float,
        storage_unit: str,
        original_unit: str,
        precision: int = 2,
    ) -> str:
        display_value, display_unit = cls.convert_for_display(
            stored_value,
            storage_unit,
            original_unit,
        )
        return f"{display_value:.{precision}f} {display_unit}".strip()

    @classmethod
    def get_indicator_config(cls, indicator_code: str, source: str = None) -> dict | None:
        return cls.read_repository.get_indicator_unit_config(indicator_code, source)

    @classmethod
    def get_original_unit(cls, indicator_code: str, source: str = None) -> str:
        config = cls.get_indicator_config(indicator_code, source)
        if config:
            return str(config.get("original_unit", "") or "")
        return ""


class IndicatorUnitRuleService:
    """Dynamic unit lookup service backed by indicator unit rules."""

    @classmethod
    def _get_default_rule(cls, indicator_code: str) -> dict[str, Any] | None:
        repo = get_indicator_unit_rule_repository()
        rule = repo.resolve_active_rule(indicator_code)
        return rule.to_dict() if rule else None

    @classmethod
    def get_unit_for_indicator(cls, indicator_code: str) -> str:
        rule = cls._get_default_rule(indicator_code)
        if rule:
            return str(
                rule.get("display_unit")
                or rule.get("original_unit")
                or rule.get("storage_unit")
                or ""
            )
        return ""

    @classmethod
    def get_normalized_unit_and_value(cls, indicator_code: str, value: float) -> tuple[float, str]:
        rule = cls._get_default_rule(indicator_code)
        if not rule:
            return value, ""
        multiplier = float(rule.get("multiplier_to_storage") or 1.0)
        storage_unit = str(rule.get("storage_unit") or "")
        return value * multiplier, storage_unit


class IndicatorService:
    """Dynamic indicator metadata reader backed by data_center catalog."""

    read_repository = get_macro_read_repository()
    _LEVEL_UNITS = frozenset(
        {
            "元",
            "万元",
            "亿元",
            "万亿元",
            "万美元",
            "百万美元",
            "亿美元",
            "十亿美元",
            "元/g",
            "元/吨",
            "元/升",
        }
    )

    @classmethod
    def get_indicator_metadata_map(cls) -> dict[str, dict]:
        catalog_repo = get_indicator_catalog_repository()
        unit_rule_repo = get_indicator_unit_rule_repository()
        metadata: dict[str, dict] = {}
        for catalog in catalog_repo.list_all():
            rule = unit_rule_repo.resolve_active_rule(catalog.code)
            unit = ""
            if rule is not None:
                unit = rule.display_unit or rule.original_unit or rule.storage_unit
            metadata[catalog.code] = {
                "name": catalog.name_cn,
                "name_en": catalog.name_en or catalog.code,
                "category": catalog.category or "其他",
                "unit": unit,
                "description": catalog.description or "",
                **(catalog.extra or {}),
            }
        return metadata

    @classmethod
    def _classify_measure_kind(cls, code: str) -> str:
        metadata = cls.get_indicator_metadata_map().get(code, {})
        series_semantics = str(metadata.get("series_semantics") or "")
        if series_semantics in {"yoy_rate", "mom_rate", "rate"}:
            return "rate"
        if series_semantics == "index_level":
            return "index"
        if series_semantics in {
            "level",
            "monthly_level",
            "cumulative_level",
            "balance_level",
            "flow_level",
        }:
            return "level"

        if code.endswith(("_YOY", "_MOM", "_MOY")):
            return "rate"
        unit = metadata.get("unit", "")
        if unit == "指数":
            return "index"
        if unit in cls._LEVEL_UNITS:
            return "level"
        return "other"

    @classmethod
    def _is_safe_alias_fallback(cls, requested_code: str, candidate_code: str) -> bool:
        if requested_code == candidate_code:
            return True
        requested_kind = cls._classify_measure_kind(requested_code)
        candidate_kind = cls._classify_measure_kind(candidate_code)
        if (
            requested_kind != "other"
            and candidate_kind != "other"
            and requested_kind != candidate_kind
        ):
            return False
        return True

    @classmethod
    def _get_configured_code_candidates(
        cls,
        code: str,
        metadata_map: dict[str, dict[str, Any]],
    ) -> list[str]:
        metadata = metadata_map.get(code, {})
        configured: list[str] = [code]

        alias_of = metadata.get("alias_of_indicator_code")
        if isinstance(alias_of, str) and alias_of:
            configured.append(alias_of)

        compatible_codes = metadata.get("compatible_indicator_codes") or []
        if isinstance(compatible_codes, (list, tuple)):
            configured.extend(str(item) for item in compatible_codes if item)

        for candidate_code, candidate_metadata in metadata_map.items():
            if candidate_code == code:
                continue
            if candidate_metadata.get("alias_of_indicator_code") == code:
                configured.append(candidate_code)

        return configured

    @classmethod
    def get_code_candidates(cls, code: str) -> list[str]:
        metadata_map = cls.get_indicator_metadata_map()
        aliases = cls._get_configured_code_candidates(code, metadata_map)
        seen: set[str] = set()
        ordered: list[str] = []
        for item in aliases:
            if item and item not in seen:
                if not cls._is_safe_alias_fallback(code, item):
                    logger.warning("Blocked unsafe macro indicator fallback: %s -> %s", code, item)
                    continue
                seen.add(item)
                ordered.append(item)
        return ordered

    @classmethod
    def get_available_indicators(cls, include_stats: bool = True) -> list[dict]:
        metadata_map = cls.get_indicator_metadata_map()
        distinct_codes = cls.read_repository.list_distinct_codes()
        indicators: list[dict[str, Any]] = []

        for code in distinct_codes:
            latest = cls.read_repository.get_latest_indicator(code)
            if not latest:
                continue
            metadata = metadata_map.get(code, {})
            avg_value = max_value = min_value = None
            if include_stats:
                stats = cls.read_repository.get_indicator_stats(
                    code=code,
                    start_date=timezone.now().date() - timedelta(days=365),
                )
                avg_value = stats["avg_value"]
                max_value = stats["max_value"]
                min_value = stats["min_value"]

            indicators.append(
                {
                    "code": code,
                    "name": metadata.get("name", code),
                    "name_en": metadata.get("name_en", code),
                    "category": metadata.get("category", "其他"),
                    "unit": latest.get("display_unit") or metadata.get("unit", ""),
                    "description": metadata.get("description", ""),
                    "series_semantics": metadata.get("series_semantics", ""),
                    "paired_indicator_code": metadata.get("paired_indicator_code", ""),
                    "latest_value": float(latest.get("display_value", latest["value"])),
                    "latest_date": latest["reporting_period"].isoformat(),
                    "period_type": latest["period_type"],
                    "threshold_bullish": metadata.get("threshold_bullish"),
                    "threshold_bearish": metadata.get("threshold_bearish"),
                    "avg_value": avg_value,
                    "max_value": max_value,
                    "min_value": min_value,
                }
            )

        indicators.sort(key=lambda item: (item["category"], item["code"]))
        return indicators

    @classmethod
    def get_indicator_by_code(cls, code: str) -> dict | None:
        latest = cls.read_repository.get_latest_indicator(code)
        if not latest:
            return None
        metadata = cls.get_indicator_metadata_map().get(code, {})
        return {
            "code": code,
            "name": metadata.get("name", code),
            "name_en": metadata.get("name_en", code),
            "category": metadata.get("category", "其他"),
            "unit": latest.get("display_unit") or metadata.get("unit", ""),
            "description": metadata.get("description", ""),
            "series_semantics": metadata.get("series_semantics", ""),
            "paired_indicator_code": metadata.get("paired_indicator_code", ""),
            "latest_value": float(latest.get("display_value", latest["value"])),
            "latest_date": latest["reporting_period"].isoformat(),
            "period_type": latest["period_type"],
        }

    @classmethod
    def get_indicator_history(cls, code: str, periods: int = 12) -> list[dict]:
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=periods * 35)
        data_points = cls.read_repository.get_indicator_history(
            code,
            start_date=start_date,
            end_date=end_date,
            limit=periods,
        )
        return [
            {
                "date": d["reporting_period"].isoformat(),
                "value": float(d.get("display_value", d["value"])),
                "unit": d.get("display_unit") or d.get("original_unit") or d.get("unit") or "",
                "period_type": d["period_type"],
            }
            for d in data_points
        ]


def get_available_indicators_for_frontend(include_stats: bool = False) -> list[dict]:
    indicators = IndicatorService.get_available_indicators(include_stats=include_stats)
    if include_stats:
        return [
            {
                "code": ind["code"],
                "name": ind["name"],
                "category": ind["category"],
                "latest_value": ind["latest_value"],
                "suggested_threshold": ind.get("threshold_bullish")
                or ind.get("threshold_bearish")
                or ind.get("avg_value"),
            }
            for ind in indicators
        ]
    return [
        {
            "code": ind["code"],
            "name": ind["name"],
            "category": ind["category"],
            "latest_value": ind["latest_value"],
            "unit": ind["unit"],
        }
        for ind in indicators
    ]
