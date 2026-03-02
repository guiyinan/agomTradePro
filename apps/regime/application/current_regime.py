"""
Unified current-regime resolver.

All business modules should use this resolver to avoid divergent regime chains.
"""

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from apps.macro.infrastructure.models import DataSourceConfig
from apps.macro.infrastructure.repositories import DjangoMacroRepository
from apps.regime.application.use_cases import CalculateRegimeV2Request, CalculateRegimeV2UseCase
from apps.regime.infrastructure.repositories import get_regime_repository


@dataclass
class CurrentRegimeResult:
    """Normalized current regime result for cross-module usage."""

    dominant_regime: str
    confidence: float
    observed_at: date
    data_source: str
    warnings: List[str]
    is_fallback: bool = False


def resolve_current_regime(
    *,
    as_of_date: Optional[date] = None,
    data_source: Optional[str] = None,
    use_pit: bool = True,
    skip_cache: bool = False,
) -> CurrentRegimeResult:
    """
    Resolve current regime via the unified V2 chain.

    Primary chain:
    - CalculateRegimeV2UseCase + use_pit=True + configured data source

    Fallback chain:
    - latest persisted regime snapshot
    """
    target_date = as_of_date or date.today()
    source = data_source or _get_default_source()

    use_case = CalculateRegimeV2UseCase(DjangoMacroRepository())
    response = use_case.execute(
        CalculateRegimeV2Request(
            as_of_date=target_date,
            use_pit=use_pit,
            growth_indicator="PMI",
            inflation_indicator="CPI",
            data_source=source,
            skip_cache=skip_cache,
        )
    )

    if response.success and response.result:
        return CurrentRegimeResult(
            dominant_regime=response.result.regime.value,
            confidence=float(response.result.confidence),
            observed_at=target_date,
            data_source=source,
            warnings=list(response.warnings or []),
            is_fallback=False,
        )

    latest = get_regime_repository().get_latest_snapshot()
    if latest:
        warnings = list(response.warnings or [])
        warnings.append("V2 实时计算失败，回退到历史快照")
        return CurrentRegimeResult(
            dominant_regime=latest.dominant_regime,
            confidence=float(latest.confidence or 0.0),
            observed_at=latest.observed_at,
            data_source=source,
            warnings=warnings,
            is_fallback=True,
        )

    warnings = list(response.warnings or [])
    if response.error:
        warnings.append(response.error)
    warnings.append("无可用 Regime 数据，返回 Unknown")
    return CurrentRegimeResult(
        dominant_regime="Unknown",
        confidence=0.0,
        observed_at=target_date,
        data_source=source,
        warnings=warnings,
        is_fallback=True,
    )


def _get_default_source() -> str:
    first_source = DataSourceConfig._default_manager.filter(is_active=True).order_by("priority").first()
    return first_source.source_type if first_source else "akshare"
