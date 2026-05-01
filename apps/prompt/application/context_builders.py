"""
Context Builders - 上下文构建层。

为 AgentRuntime 提供标准化的上下文数据构建能力。
每个 ContextProvider 负责一个业务域的数据摘要和原始数据提取。
"""

import json
import logging
from datetime import UTC, datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

from ..domain.context_entities import ContextBundle, ContextPolicy, ContextSection

logger = logging.getLogger(__name__)

RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    ImportError,
    LookupError,
    OSError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
    json.JSONDecodeError,
)


class ContextProvider(Protocol):
    """上下文提供者协议。"""

    @property
    def domain_name(self) -> str:
        """域名称。"""
        ...

    def build_summary(self, params: dict[str, Any]) -> Any:
        """构建摘要数据。"""
        ...

    def build_raw_data(self, params: dict[str, Any]) -> Any:
        """构建原始数据。"""
        ...

    def build_section(self, params: dict[str, Any]) -> ContextSection:
        """构建完整上下文段。"""
        ...


class MacroContextProvider:
    """宏观数据上下文提供者。"""

    domain_name: str = "macro"

    def __init__(self, macro_adapter: Any = None):
        self._adapter = macro_adapter

    def build_summary(self, params: dict[str, Any]) -> Any:
        """构建宏观数据摘要。"""
        if not self._adapter:
            return "宏观数据不可用"
        try:
            as_of_date = params.get("as_of_date")
            indicators = params.get("indicators")
            return self._adapter.get_macro_summary(as_of_date=as_of_date, indicators=indicators)
        except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
            logger.warning("MacroContextProvider.build_summary failed: %s", exc)
            return "宏观数据获取失败"

    def build_raw_data(self, params: dict[str, Any]) -> Any:
        """构建宏观数据原始数据。"""
        if not self._adapter:
            return {}
        try:
            return self._adapter.get_all_indicators(as_of_date=params.get("as_of_date"))
        except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
            logger.warning("MacroContextProvider.build_raw_data failed: %s", exc)
            return {}

    def build_section(self, params: dict[str, Any]) -> ContextSection:
        """构建宏观上下文段。"""
        return ContextSection(
            name=self.domain_name,
            summary=self.build_summary(params),
            raw_data=self.build_raw_data(params),
            references={"source": "macro_adapter"},
            generated_at=datetime.now(UTC).isoformat(),
        )


class RegimeContextProvider:
    """Regime 上下文提供者。"""

    domain_name: str = "regime"

    def __init__(self, regime_adapter: Any = None):
        self._adapter = regime_adapter

    def build_summary(self, params: dict[str, Any]) -> Any:
        """构建 Regime 摘要。"""
        if not self._adapter:
            return "Regime 数据不可用"
        try:
            as_of_date = params.get("as_of_date")
            status = self._adapter.get_current_regime(as_of_date)
            return status
        except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
            logger.warning("RegimeContextProvider.build_summary failed: %s", exc)
            return "Regime 数据获取失败"

    def build_raw_data(self, params: dict[str, Any]) -> Any:
        """构建 Regime 原始数据。"""
        if not self._adapter:
            return {}
        try:
            data = {}
            as_of_date = params.get("as_of_date")
            data["current"] = self._adapter.get_current_regime(as_of_date)
            try:
                data["distribution"] = self._adapter.get_regime_distribution(as_of_date)
            except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
                logger.debug(
                    "RegimeContextProvider.build_raw_data distribution degraded: %s",
                    exc,
                )
            return data
        except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
            logger.warning("RegimeContextProvider.build_raw_data failed: %s", exc)
            return {}

    def build_section(self, params: dict[str, Any]) -> ContextSection:
        return ContextSection(
            name=self.domain_name,
            summary=self.build_summary(params),
            raw_data=self.build_raw_data(params),
            references={"source": "regime_adapter"},
            generated_at=datetime.now(UTC).isoformat(),
        )


class PortfolioContextProvider:
    """投资组合上下文提供者。"""

    domain_name: str = "portfolio"

    def __init__(self, portfolio_provider: Any = None):
        self._provider = portfolio_provider

    def build_summary(self, params: dict[str, Any]) -> Any:
        """构建投资组合摘要。"""
        if not self._provider:
            return "投资组合数据不可用"
        try:
            portfolio_id = params.get("portfolio_id")
            if not portfolio_id:
                return "未指定投资组合"
            positions = self._provider.get_positions(portfolio_id)
            cash = self._provider.get_cash(portfolio_id)
            position_count = len(positions) if isinstance(positions, list) else 0
            return {
                "portfolio_id": portfolio_id,
                "position_count": position_count,
                "cash": cash,
            }
        except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
            logger.warning("PortfolioContextProvider.build_summary failed: %s", exc)
            return "投资组合数据获取失败"

    def build_raw_data(self, params: dict[str, Any]) -> Any:
        if not self._provider:
            return {}
        try:
            portfolio_id = params.get("portfolio_id")
            if not portfolio_id:
                return {}
            return {
                "positions": self._provider.get_positions(portfolio_id),
                "cash": self._provider.get_cash(portfolio_id),
            }
        except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
            logger.warning("PortfolioContextProvider.build_raw_data failed: %s", exc)
            return {}

    def build_section(self, params: dict[str, Any]) -> ContextSection:
        return ContextSection(
            name=self.domain_name,
            summary=self.build_summary(params),
            raw_data=self.build_raw_data(params),
            references={"source": "portfolio_provider"},
            generated_at=datetime.now(UTC).isoformat(),
        )


class SignalContextProvider:
    """信号上下文提供者。"""

    domain_name: str = "signals"

    def __init__(self, signal_provider: Any = None):
        self._provider = signal_provider

    def build_summary(self, params: dict[str, Any]) -> Any:
        if not self._provider:
            return "信号数据不可用"
        try:
            signals = self._provider.get_valid_signals()
            if isinstance(signals, list):
                return {
                    "active_signal_count": len(signals),
                    "signals": [
                        {
                            "asset_code": getattr(s, "asset_code", str(s)),
                            "direction": getattr(s, "direction", "unknown"),
                        }
                        for s in signals[:10]  # 摘要只取前10条
                    ],
                }
            return {"active_signal_count": 0, "signals": []}
        except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
            logger.warning("SignalContextProvider.build_summary failed: %s", exc)
            return "信号数据获取失败"

    def build_raw_data(self, params: dict[str, Any]) -> Any:
        if not self._provider:
            return []
        try:
            return self._provider.get_valid_signals()
        except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
            logger.warning("SignalContextProvider.build_raw_data failed: %s", exc)
            return []

    def build_section(self, params: dict[str, Any]) -> ContextSection:
        return ContextSection(
            name=self.domain_name,
            summary=self.build_summary(params),
            raw_data=self.build_raw_data(params),
            references={"source": "signal_provider"},
            generated_at=datetime.now(UTC).isoformat(),
        )


class AssetPoolContextProvider:
    """资产池上下文提供者。"""

    domain_name: str = "asset_pool"

    def __init__(self, asset_pool_provider: Any = None):
        self._provider = asset_pool_provider

    def build_summary(self, params: dict[str, Any]) -> Any:
        if not self._provider:
            return "资产池数据不可用"
        try:
            assets = self._provider.get_investable_assets()
            if isinstance(assets, list):
                return {
                    "investable_asset_count": len(assets),
                    "sample": [getattr(a, "code", str(a)) for a in assets[:10]],
                }
            return {"investable_asset_count": 0, "sample": []}
        except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
            logger.warning("AssetPoolContextProvider.build_summary failed: %s", exc)
            return "资产池数据获取失败"

    def build_raw_data(self, params: dict[str, Any]) -> Any:
        if not self._provider:
            return []
        try:
            return self._provider.get_investable_assets()
        except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
            logger.warning("AssetPoolContextProvider.build_raw_data failed: %s", exc)
            return []

    def build_section(self, params: dict[str, Any]) -> ContextSection:
        return ContextSection(
            name=self.domain_name,
            summary=self.build_summary(params),
            raw_data=self.build_raw_data(params),
            references={"source": "asset_pool_provider"},
            generated_at=datetime.now(UTC).isoformat(),
        )


class ContextBundleBuilder:
    """
    上下文包构建器。

    根据 scope 列表构建 ContextBundle，自动聚合各域 provider 的数据。
    """

    def __init__(self):
        self._providers: dict[str, Any] = {}

    def register_provider(self, provider: Any) -> None:
        """注册上下文提供者。"""
        name = getattr(provider, "domain_name", None)
        if name:
            self._providers[name] = provider

    def build(
        self,
        scope: list[str],
        params: dict[str, Any] | None = None,
        policy: str = ContextPolicy.SUMMARY_PLUS_SELECTED_RAW.value,
    ) -> ContextBundle:
        """
        按 scope 构建 ContextBundle。

        Args:
            scope: 域列表，如 ["macro", "regime", "portfolio"]
            params: 构建参数
            policy: 上下文注入策略

        Returns:
            ContextBundle
        """
        params = params or {}
        bundle = ContextBundle(
            scope=scope,
            policy=policy,
            generated_at=datetime.now(UTC).isoformat(),
        )

        for domain_name in scope:
            provider = self._providers.get(domain_name)
            if not provider:
                logger.warning("No context provider for domain: %s", domain_name)
                bundle.add_section(
                    ContextSection(
                        name=domain_name,
                        summary=f"{domain_name} 数据不可用（无 provider）",
                        raw_data=None,
                        generated_at=datetime.now(UTC).isoformat(),
                    )
                )
                continue

            try:
                section = provider.build_section(params)
                bundle.add_section(section)
            except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
                logger.error("Context provider '%s' failed: %s", domain_name, exc, exc_info=True)
                bundle.add_section(
                    ContextSection(
                        name=domain_name,
                        summary=f"{domain_name} 数据构建失败: {exc}",
                        raw_data=None,
                        generated_at=datetime.now(UTC).isoformat(),
                    )
                )

        return bundle
