"""Payload provenance helpers for market thermometer components."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.data_center.domain.protocols import MacroFactRepositoryProtocol


def append_component_provenance(
    payload: dict[str, Any],
    *,
    macro_repo: MacroFactRepositoryProtocol,
    observed_at: date,
) -> None:
    """Add latest macro-fact provenance for each thermometer component."""

    provenance: list[dict[str, Any]] = []
    proxy_components: list[dict[str, Any]] = []
    for component in payload.get("components") or []:
        indicator_code = str(component.get("indicator_code") or "").strip()
        if not indicator_code:
            continue
        latest = macro_repo.get_series(indicator_code, end=observed_at, limit=1)
        if not latest:
            continue
        fact = latest[0]
        extra = dict(fact.extra or {})
        proxy = extra.get("proxy")
        verification_status = extra.get("verification_status")
        if proxy and not verification_status:
            verification_status = "proxy_source"
        item = {
            "component_key": component.get("component_key"),
            "indicator_code": indicator_code,
            "reporting_period": fact.reporting_period.isoformat(),
            "source": fact.source,
            "proxy": proxy,
            "verification_status": verification_status,
            "source_url": extra.get("source_url"),
        }
        provenance.append(item)
        if item["proxy"] or item["verification_status"] == "fallback_proxy":
            proxy_components.append(item)
    payload["component_data_provenance"] = provenance
    payload["proxy_components"] = proxy_components
