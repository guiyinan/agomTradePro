"""
Context Builders - 上下文构建层。

为 AgentRuntime 提供标准化的上下文数据构建能力。
每个 ContextProvider 负责一个业务域的数据摘要和原始数据提取。
"""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from ..domain.context_entities import ContextBundle, ContextPolicy, ContextSection

logger = logging.getLogger(__name__)
_DOMAIN_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SENSITIVE_CONTEXT_KEY_PATTERN = re.compile(
    r"(?:^|[_-])(api[_-]?key|authorization|cookie|credential|password|secret|session|token)(?:$|[_-])",
    re.IGNORECASE,
)

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


def _validate_context_params(params: dict[str, Any]) -> dict[str, Any]:
    """Detach and validate bounded, credential-free JSON context parameters."""

    if len(params) > 100 or any(
        not isinstance(key, str) or len(key) > 128 or "\x00" in key for key in params
    ):
        raise ValueError("context params exceed bounded key limits")
    stack: list[tuple[object, int]] = [(params, 0)]
    visited = 0
    while stack:
        value, depth = stack.pop()
        visited += 1
        if visited > 10_000 or depth > 20:
            raise ValueError("context params exceed structural limits")
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str) or _SENSITIVE_CONTEXT_KEY_PATTERN.search(key):
                    raise ValueError("context params contain invalid or sensitive keys")
                stack.append((child, depth + 1))
        elif isinstance(value, list | tuple):
            stack.extend((child, depth + 1) for child in value)
    try:
        encoded = json.dumps(params, ensure_ascii=False, allow_nan=False)
    except (RecursionError, TypeError, ValueError) as exc:
        raise ValueError("context params must contain finite JSON values") from exc
    if len(encoded.encode("utf-8")) > 1_048_576:
        raise ValueError("context params exceed the 1 MiB limit")
    return cast(dict[str, Any], json.loads(encoded))


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

    def __init__(self, macro_adapter: Any = None) -> None:
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
            logger.warning(
                "MacroContextProvider.build_summary failed error_type=%s",
                type(exc).__name__,
            )
            return "宏观数据获取失败"

    def build_raw_data(self, params: dict[str, Any]) -> Any:
        """构建宏观数据原始数据。"""
        if not self._adapter:
            return {}
        try:
            return self._adapter.get_all_indicators(as_of_date=params.get("as_of_date"))
        except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
            logger.warning(
                "MacroContextProvider.build_raw_data failed error_type=%s",
                type(exc).__name__,
            )
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

    def __init__(self, regime_adapter: Any = None) -> None:
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
            logger.warning(
                "RegimeContextProvider.build_summary failed error_type=%s",
                type(exc).__name__,
            )
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
                    "RegimeContextProvider.build_raw_data distribution degraded error_type=%s",
                    type(exc).__name__,
                )
            return data
        except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
            logger.warning(
                "RegimeContextProvider.build_raw_data failed error_type=%s",
                type(exc).__name__,
            )
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

    def __init__(self, portfolio_provider: Any = None) -> None:
        self._provider = portfolio_provider

    def build_summary(self, params: dict[str, Any]) -> Any:
        """构建投资组合摘要。"""
        if not self._provider:
            return "投资组合数据不可用"
        try:
            portfolio_id = params.get("portfolio_id")
            if (
                isinstance(portfolio_id, bool)
                or not isinstance(portfolio_id, int)
                or portfolio_id <= 0
            ):
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
            logger.warning(
                "PortfolioContextProvider.build_summary failed error_type=%s",
                type(exc).__name__,
            )
            return "投资组合数据获取失败"

    def build_raw_data(self, params: dict[str, Any]) -> Any:
        if not self._provider:
            return {}
        try:
            portfolio_id = params.get("portfolio_id")
            if (
                isinstance(portfolio_id, bool)
                or not isinstance(portfolio_id, int)
                or portfolio_id <= 0
            ):
                return {}
            return {
                "positions": self._provider.get_positions(portfolio_id),
                "cash": self._provider.get_cash(portfolio_id),
            }
        except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
            logger.warning(
                "PortfolioContextProvider.build_raw_data failed error_type=%s",
                type(exc).__name__,
            )
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

    def __init__(self, signal_provider: Any = None) -> None:
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
                            "asset_code": getattr(s, "asset_code", "unknown"),
                            "direction": getattr(s, "direction", "unknown"),
                        }
                        for s in signals[:10]  # 摘要只取前10条
                    ],
                }
            return {"active_signal_count": 0, "signals": []}
        except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
            logger.warning(
                "SignalContextProvider.build_summary failed error_type=%s",
                type(exc).__name__,
            )
            return "信号数据获取失败"

    def build_raw_data(self, params: dict[str, Any]) -> Any:
        if not self._provider:
            return []
        try:
            return self._provider.get_valid_signals()
        except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
            logger.warning(
                "SignalContextProvider.build_raw_data failed error_type=%s",
                type(exc).__name__,
            )
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

    def __init__(self, asset_pool_provider: Any = None) -> None:
        self._provider = asset_pool_provider

    def build_summary(self, params: dict[str, Any]) -> Any:
        if not self._provider:
            return "资产池数据不可用"
        try:
            assets = self._provider.get_investable_assets()
            if isinstance(assets, list):
                return {
                    "investable_asset_count": len(assets),
                    "sample": [getattr(a, "code", "unknown") for a in assets[:10]],
                }
            return {"investable_asset_count": 0, "sample": []}
        except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
            logger.warning(
                "AssetPoolContextProvider.build_summary failed error_type=%s",
                type(exc).__name__,
            )
            return "资产池数据获取失败"

    def build_raw_data(self, params: dict[str, Any]) -> Any:
        if not self._provider:
            return []
        try:
            return self._provider.get_investable_assets()
        except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
            logger.warning(
                "AssetPoolContextProvider.build_raw_data failed error_type=%s",
                type(exc).__name__,
            )
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

    def __init__(self) -> None:
        self._providers: dict[str, ContextProvider] = {}

    def register_provider(self, provider: ContextProvider) -> None:
        """注册上下文提供者。"""
        name = provider.domain_name
        if _DOMAIN_NAME_PATTERN.fullmatch(name) is None:
            raise ValueError("context provider domain_name has invalid format")
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
        if not isinstance(scope, list) or not 1 <= len(scope) <= 20:
            raise ValueError("context scope must contain between 1 and 20 domains")
        if len(scope) != len(set(scope)) or any(
            not isinstance(name, str) or _DOMAIN_NAME_PATTERN.fullmatch(name) is None
            for name in scope
        ):
            raise ValueError("context scope contains invalid or duplicate domains")
        valid_policies = {item.value for item in ContextPolicy}
        if policy not in valid_policies:
            raise ValueError("context policy is invalid")
        params = _validate_context_params(dict(params or {}))
        bundle = ContextBundle(
            scope=list(scope),
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
                if section.name != domain_name:
                    raise ValueError("context provider returned a mismatched domain")
                bundle.add_section(section)
            except RECOVERABLE_CONTEXT_BUILD_EXCEPTIONS as exc:
                logger.error(
                    "Context provider failed domain=%s error_type=%s",
                    domain_name,
                    type(exc).__name__,
                )
                bundle.add_section(
                    ContextSection(
                        name=domain_name,
                        summary=f"{domain_name} 数据构建失败",
                        raw_data=None,
                        generated_at=datetime.now(UTC).isoformat(),
                    )
                )

        return bundle
