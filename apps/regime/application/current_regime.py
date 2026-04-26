"""
Unified current-regime resolver.

All business modules should use this resolver to avoid divergent regime chains.

重构说明 (2026-03-11):
- 移除对 macro 模块的直接导入
- 改为依赖注入 MacroDataProviderProtocol (从 domain/protocols.py 导入)
- 添加 set_providers() 支持测试注入
- 保持 API 完全兼容
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

from apps.regime.application.use_cases import CalculateRegimeV2Request, CalculateRegimeV2UseCase
from apps.regime.domain.protocols import MacroDataProviderProtocol
from apps.regime.infrastructure.providers import get_regime_repository


@dataclass
class CurrentRegimeResult:
    """Normalized current regime result for cross-module usage."""

    dominant_regime: str
    confidence: float
    observed_at: date
    data_source: str
    warnings: list[str]
    distribution: dict[str, float] | None = None
    is_fallback: bool = False


# 全局提供者 (延迟初始化)
_macro_data_provider: MacroDataProviderProtocol | None = None


def set_macro_data_provider(provider: MacroDataProviderProtocol) -> None:
    """
    设置宏观数据提供者 (用于依赖注入)

    允许测试代码注入 mock 提供者。

    Args:
        provider: MacroDataProviderProtocol 实例

    Example:
        >>> # 在测试中
        >>> mock_provider = MockMacroDataProvider()
        >>> set_macro_data_provider(mock_provider)
        >>> result = resolve_current_regime()
    """
    global _macro_data_provider
    _macro_data_provider = provider


def get_macro_data_provider() -> MacroDataProviderProtocol:
    """
    获取当前的宏观数据提供者

    如果未设置，延迟创建默认的 Django 实现。

    Returns:
        MacroDataProviderProtocol 实例
    """
    global _macro_data_provider
    if _macro_data_provider is None:
        # 延迟导入避免循环依赖，使用 Infrastructure 层的实现
        from apps.regime.infrastructure.macro_data_provider import (
            get_default_macro_data_provider,
        )
        _macro_data_provider = get_default_macro_data_provider()

    return _macro_data_provider


def resolve_current_regime(
    *,
    as_of_date: date | None = None,
    data_source: str | None = None,
    use_pit: bool = True,
    skip_cache: bool = False,
) -> CurrentRegimeResult:
    """
    Resolve current regime via the unified V2 chain.

    Primary chain:
    - CalculateRegimeV2UseCase + use_pit=True + configured data source

    Fallback chain:
    - latest persisted regime snapshot

    重构说明 (2026-03-11):
    - 通过 MacroDataProviderProtocol 获取数据
    - 使用 MacroRepositoryAdapter 适配器转换接口
    - 完全解耦 macro 模块直接导入
    """
    target_date = as_of_date or date.today()

    # 通过提供者获取数据 - 使用适配器模式
    provider = get_macro_data_provider()

    # 创建适配器，将 Provider 接口适配为 Repository 接口
    from apps.regime.infrastructure.macro_data_provider import MacroRepositoryAdapter
    macro_repo = MacroRepositoryAdapter(provider)

    # 使用默认数据源
    source = data_source or "akshare"

    use_case = CalculateRegimeV2UseCase(macro_repo)
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
            distribution=dict(response.result.distribution or {}),
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
            distribution=dict(latest.distribution or {}),
            is_fallback=True,
        )

    warnings = list(response.warnings or [])
    if response.error:
        warnings.append(response.error)
    warnings.append("无可用 Regime 数据,返回 Unknown")
    return CurrentRegimeResult(
        dominant_regime="Unknown",
        confidence=0.0,
        observed_at=target_date,
        data_source=source,
        warnings=warnings,
        distribution=None,
        is_fallback=True,
    )
