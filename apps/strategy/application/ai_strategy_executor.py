"""
AI 策略执行器 - Application 层

遵循项目架构约束：
- 复用系统内置的 AI 中台（Prompt 系统 + AI Provider）
- 支持三种审核模式（always/conditional/auto）
- 解析 AI 响应为信号列表
"""
import logging
import json
import time
from typing import List, Dict, Any, Optional
from datetime import datetime

from django.utils import timezone

from apps.strategy.domain.entities import (
    Strategy,
    SignalRecommendation,
    ActionType,
    AIConfig
)
from apps.strategy.domain.protocols import (
    MacroDataProviderProtocol,
    RegimeProviderProtocol,
    AssetPoolProviderProtocol,
    SignalProviderProtocol,
    PortfolioDataProviderProtocol
)

# 复用系统内置的 AI 中台
from apps.prompt.application.use_cases import (
    ExecutePromptUseCase,
    ExecuteChainUseCase,
    ExecutePromptRequest,
    ExecuteChainRequest
)
from apps.prompt.infrastructure.repositories import (
    DjangoPromptRepository,
    DjangoChainRepository,
    DjangoExecutionLogRepository
)
from apps.ai_provider.infrastructure.client_factory import AIClientFactory

logger = logging.getLogger(__name__)


# ========================================================================
# AI 响应解析器
# ========================================================================

class AIResponseParser:
    """
    AI 响应解析器

    将 AI 的响应解析为信号列表

    支持的响应格式：
    1. JSON 数组：[{"asset_code": "ASSET_CODE", "action": "buy", ...}, ...]
    2. JSON 对象：{"signals": [...], "reason": "..."}
    3. 纯文本：逐行解析
    """

    @staticmethod
    def parse_signals(
        ai_content: str,
        default_confidence: float = 0.5
    ) -> List[SignalRecommendation]:
        """
        解析 AI 响应为信号列表

        Args:
            ai_content: AI 响应内容
            default_confidence: 默认置信度

        Returns:
            信号推荐列表
        """
        signals = []

        # 1. 尝试解析为 JSON
        try:
            data = json.loads(ai_content)

            if isinstance(data, list):
                # JSON 数组格式
                for item in data:
                    signal = AIResponseParser._parse_signal_item(item, default_confidence)
                    if signal:
                        signals.append(signal)

            elif isinstance(data, dict):
                # JSON 对象格式
                if 'signals' in data and isinstance(data['signals'], list):
                    for item in data['signals']:
                        signal = AIResponseParser._parse_signal_item(item, default_confidence)
                        if signal:
                            signals.append(signal)
                else:
                    # 单个信号对象
                    signal = AIResponseParser._parse_signal_item(data, default_confidence)
                    if signal:
                        signals.append(signal)

            return signals

        except json.JSONDecodeError:
            # 2. 不是 JSON 格式，尝试逐行解析
            return AIResponseParser._parse_text_format(ai_content, default_confidence)

    @staticmethod
    def _parse_signal_item(
        item: Dict[str, Any],
        default_confidence: float
    ) -> Optional[SignalRecommendation]:
        """
        解析单个信号项

        Args:
            item: 信号数据字典
            default_confidence: 默认置信度

        Returns:
            SignalRecommendation 实例，如果解析失败返回 None
        """
        try:
            # 必填字段
            asset_code = item.get('asset_code')
            action_str = item.get('action', 'hold')

            if not asset_code:
                logger.warning(f"Signal missing asset_code: {item}")
                return None

            # 转换 action
            action_map = {
                'buy': ActionType.BUY,
                'sell': ActionType.SELL,
                'hold': ActionType.HOLD,
                'weight': ActionType.WEIGHT
            }
            action = action_map.get(action_str.lower(), ActionType.HOLD)

            # 解析权重
            weight = item.get('weight')
            if weight is not None:
                weight = float(weight)
                if not (0 <= weight <= 1):
                    weight = None

            # 解析置信度
            confidence = item.get('confidence', default_confidence)
            try:
                confidence = float(confidence)
                if not (0 <= confidence <= 1):
                    confidence = default_confidence
            except (ValueError, TypeError):
                confidence = default_confidence

            return SignalRecommendation(
                asset_code=asset_code,
                asset_name=item.get('asset_name', asset_code),
                action=action,
                weight=weight,
                quantity=item.get('quantity'),
                reason=item.get('reason', ''),
                confidence=confidence,
                metadata={
                    'source': 'ai_strategy',
                    'raw_data': item
                }
            )

        except Exception as e:
            logger.warning(f"Failed to parse signal item: {item}, error: {e}")
            return None

    @staticmethod
    def _parse_text_format(
        text: str,
        default_confidence: float
    ) -> List[SignalRecommendation]:
        """
        解析纯文本格式

        每行格式：asset_code,action,weight,reason

        Args:
            text: 纯文本内容
            default_confidence: 默认置信度

        Returns:
            信号推荐列表
        """
        signals = []

        for line in text.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # 解析 CSV 格式
            parts = line.split(',')
            if len(parts) >= 2:
                asset_code = parts[0].strip()
                action_str = parts[1].strip().lower()
                weight = float(parts[2].strip()) if len(parts) > 2 else None
                reason = ','.join(parts[3:]).strip() if len(parts) > 3 else ''

                action_map = {
                    'buy': ActionType.BUY,
                    'sell': ActionType.SELL,
                    'hold': ActionType.HOLD,
                    'weight': ActionType.WEIGHT
                }
                action = action_map.get(action_str, ActionType.HOLD)

                signals.append(SignalRecommendation(
                    asset_code=asset_code,
                    asset_name=asset_code,
                    action=action,
                    weight=weight,
                    reason=reason,
                    confidence=default_confidence,
                    metadata={'source': 'ai_strategy'}
                ))

        return signals


# ========================================================================
# AI 策略执行器
# ========================================================================

class AIStrategyExecutor:
    """
    AI 驱动策略执行器

    职责：
    1. 复用 Prompt 系统的 ExecutePromptUseCase/ExecuteChainUseCase
    2. 复用 AI Provider 系统的 OpenAICompatibleAdapter
    3. 支持三种审核模式
    4. 解析 AI 响应为信号列表
    """

    def __init__(
        self,
        macro_provider: MacroDataProviderProtocol,
        regime_provider: RegimeProviderProtocol,
        asset_pool_provider: AssetPoolProviderProtocol,
        signal_provider: SignalProviderProtocol,
        portfolio_provider: PortfolioDataProviderProtocol
    ):
        """
        初始化 AI 策略执行器

        Args:
            macro_provider: 宏观数据提供者
            regime_provider: Regime 提供者
            asset_pool_provider: 资产池提供者
            signal_provider: 信号提供者
            portfolio_provider: 投资组合数据提供者
        """
        self.macro_provider = macro_provider
        self.regime_provider = regime_provider
        self.asset_pool_provider = asset_pool_provider
        self.signal_provider = signal_provider
        self.portfolio_provider = portfolio_provider

        # 初始化 AI 中台组件
        self.ai_client_factory = AIClientFactory()

        # 初始化 Prompt 系统组件
        self.prompt_repository = DjangoPromptRepository()
        self.chain_repository = DjangoChainRepository()
        self.execution_log_repository = DjangoExecutionLogRepository()

        # 初始化用例
        self.execute_prompt_use_case = ExecutePromptUseCase(
            prompt_repository=self.prompt_repository,
            execution_log_repository=self.execution_log_repository,
            ai_client_factory=self.ai_client_factory,
            macro_adapter=None,  # 暂不使用
            regime_adapter=None   # 暂不使用
        )

        self.execute_chain_use_case = ExecuteChainUseCase(
            chain_repository=self.chain_repository,
            prompt_use_case=self.execute_prompt_use_case
        )

    def execute(
        self,
        strategy: Strategy,
        portfolio_id: int
    ) -> List[SignalRecommendation]:
        """
        执行 AI 驱动策略

        通过 AgentRuntime 执行，支持上下文注入和工具调用。

        Args:
            strategy: 策略实体（必须包含 ai_config）
            portfolio_id: 投资组合ID

        Returns:
            信号推荐列表

        Raises:
            ValueError: 策略配置无效或 AI 执行失败
        """
        if strategy.ai_config is None:
            raise ValueError("AI-driven strategy must have ai_config")

        ai_config = strategy.ai_config

        try:
            # 尝试通过 AgentRuntime 执行
            ai_response = self._execute_via_runtime(ai_config, portfolio_id)

            if ai_response is None:
                # 回退到旧路径
                context = self._prepare_context(portfolio_id)
                if ai_config.chain_config_id:
                    ai_response = self._execute_chain_strategy(ai_config, context)
                elif ai_config.prompt_template_id:
                    ai_response = self._execute_prompt_strategy(ai_config, context)
                else:
                    raise ValueError("AI strategy must have either prompt_template_id or chain_config_id")

            # 3. 解析 AI 响应为信号
            signals = AIResponseParser.parse_signals(
                ai_response,
                default_confidence=ai_config.confidence_threshold
            )

            # 4. 根据审核模式过滤信号
            filtered_signals = self._apply_approval_mode(
                signals,
                ai_config.approval_mode,
                ai_config.confidence_threshold
            )

            logger.info(
                f"AI strategy executed: {len(signals)} signals generated, "
                f"{len(filtered_signals)} signals after approval filter"
            )

            return filtered_signals

        except Exception as e:
            logger.error(f"AI strategy execution failed: {e}", exc_info=True)
            raise

    def _execute_via_runtime(
        self,
        ai_config: AIConfig,
        portfolio_id: int,
    ) -> Optional[str]:
        """
        通过 AgentRuntime 执行策略（新路径）。

        返回 AI 文本响应，如果 Runtime 不可用则返回 None 以回退到旧路径。
        """
        try:
            from apps.prompt.application.agent_runtime import AgentRuntime
            from apps.prompt.application.context_builders import (
                ContextBundleBuilder,
                MacroContextProvider,
                RegimeContextProvider,
                PortfolioContextProvider,
                SignalContextProvider,
                AssetPoolContextProvider,
            )
            from apps.prompt.application.tool_execution import create_agent_tool_registry
            from apps.prompt.domain.agent_entities import AgentExecutionRequest
            from apps.prompt.domain.services import TemplateRenderer
            from apps.prompt.infrastructure.adapters.macro_adapter import MacroDataAdapter
            from apps.prompt.infrastructure.adapters.regime_adapter import RegimeDataAdapter

            macro_adapter = MacroDataAdapter()
            regime_adapter = RegimeDataAdapter()

            tool_registry = create_agent_tool_registry(
                macro_adapter=macro_adapter,
                regime_adapter=regime_adapter,
                portfolio_provider=self.portfolio_provider,
                signal_provider=self.signal_provider,
                asset_pool_provider=self.asset_pool_provider,
            )

            context_builder = ContextBundleBuilder()
            context_builder.register_provider(MacroContextProvider(macro_adapter))
            context_builder.register_provider(RegimeContextProvider(regime_adapter))
            context_builder.register_provider(PortfolioContextProvider(self.portfolio_provider))
            context_builder.register_provider(SignalContextProvider(self.signal_provider))
            context_builder.register_provider(AssetPoolContextProvider(self.asset_pool_provider))

            runtime = AgentRuntime(
                ai_client_factory=self.ai_client_factory,
                tool_registry=tool_registry,
                context_builder=context_builder,
            )

            # 加载模板获取 system_prompt 和 user_input
            system_prompt = None
            user_input = None

            if ai_config.chain_config_id and not ai_config.prompt_template_id:
                # 链式策略需要多步骤编排，Runtime 不支持，回退到旧路径
                logger.info("Chain-based strategy, falling back to legacy execution path")
                return None

            if ai_config.prompt_template_id:
                template = self.prompt_repository.get_template_by_id(
                    ai_config.prompt_template_id
                )
                if template:
                    # Preserve legacy prompt semantics by rendering the template
                    # against the same prepared strategy context before handing it
                    # to the Runtime for tool-augmented execution.
                    render_context = self._prepare_context(portfolio_id)
                    user_input = TemplateRenderer().render_simple(
                        template.template_content,
                        render_context,
                    )
                    system_prompt = template.system_prompt
                else:
                    logger.warning(
                        "Prompt template %d not found, falling back",
                        ai_config.prompt_template_id,
                    )
                    return None

            if not user_input:
                # 无模板配置，回退到旧路径
                logger.info("No prompt template configured, falling back to legacy execution path")
                return None

            agent_request = AgentExecutionRequest(
                task_type="strategy",
                user_input=user_input,
                provider_ref=ai_config.ai_provider_id or 1,
                temperature=ai_config.temperature,
                max_tokens=ai_config.max_tokens,
                context_scope=["macro", "regime", "portfolio", "signals", "asset_pool"],
                context_params={"portfolio_id": portfolio_id},
                tool_names=[
                    "get_macro_summary", "get_macro_indicator", "get_regime_status",
                    "get_regime_distribution", "get_portfolio_snapshot",
                    "get_portfolio_positions", "get_portfolio_cash",
                    "get_valid_signals", "get_asset_pool",
                ],
                system_prompt=system_prompt,
                max_rounds=4,
            )

            response = runtime.execute(agent_request)

            if response.success and response.final_answer:
                logger.info(
                    "Strategy executed via AgentRuntime: turns=%d, tokens=%d",
                    response.turn_count, response.total_tokens,
                )
                return response.final_answer

            if not response.success:
                logger.warning(
                    "AgentRuntime strategy execution failed: %s, falling back",
                    response.error_message,
                )
            return None

        except ImportError:
            logger.info("AgentRuntime not available, using legacy execution path")
            return None
        except Exception as exc:
            logger.warning("AgentRuntime execution error: %s, falling back", exc)
            return None

    def _prepare_context(self, portfolio_id: int) -> Dict[str, Any]:
        """
        准备 AI 执行上下文

        Args:
            portfolio_id: 投资组合ID

        Returns:
            上下文字典
        """
        context = {
            'portfolio_id': portfolio_id,
            'timestamp': timezone.now().isoformat()
        }

        # 获取宏观数据
        try:
            if hasattr(self.macro_provider, 'get_all_indicators'):
                context['macro'] = self.macro_provider.get_all_indicators()
        except Exception as e:
            logger.warning(f"Failed to get macro data: {e}")

        # 获取 Regime
        try:
            context['regime'] = self.regime_provider.get_current_regime()
        except Exception as e:
            logger.warning(f"Failed to get regime data: {e}")

        # 获取资产池
        try:
            context['asset_pool'] = self.asset_pool_provider.get_investable_assets()
        except Exception as e:
            logger.warning(f"Failed to get asset pool: {e}")

        # 获取投资组合数据
        try:
            positions = self.portfolio_provider.get_positions(portfolio_id)
            cash = self.portfolio_provider.get_cash(portfolio_id)
            context['portfolio'] = {
                'positions': positions,
                'cash': cash
            }
        except Exception as e:
            logger.warning(f"Failed to get portfolio data: {e}")

        # 获取有效信号
        try:
            context['signals'] = self.signal_provider.get_valid_signals()
        except Exception as e:
            logger.warning(f"Failed to get signals: {e}")

        return context

    def _execute_prompt_strategy(
        self,
        ai_config: AIConfig,
        context: Dict[str, Any]
    ) -> str:
        """
        执行单个 Prompt 策略

        Args:
            ai_config: AI 配置
            context: 上下文数据

        Returns:
            AI 响应内容
        """
        # 构建 Prompt 执行请求
        request = ExecutePromptRequest(
            template_id=ai_config.prompt_template_id,
            placeholder_values=context,
            provider_ref=ai_config.ai_provider_id or 1,  # 默认使用第一个服务商
            model=None,  # 使用服务商默认模型
            temperature=ai_config.temperature,
            max_tokens=ai_config.max_tokens
        )

        # 执行 Prompt
        response = self.execute_prompt_use_case.execute(request)

        if not response.success:
            raise ValueError(f"Prompt execution failed: {response.error_message}")

        return response.content

    def _execute_chain_strategy(
        self,
        ai_config: AIConfig,
        context: Dict[str, Any]
    ) -> str:
        """
        执行链式策略

        Args:
            ai_config: AI 配置
            context: 上下文数据

        Returns:
            AI 响应内容（最终输出）
        """
        # 构建 Chain 执行请求
        request = ExecuteChainRequest(
            chain_id=ai_config.chain_config_id,
            placeholder_values=context,
            provider_ref=ai_config.ai_provider_id or 1
        )

        # 执行 Chain
        response = self.execute_chain_use_case.execute(request)

        if not response.success:
            raise ValueError(f"Chain execution failed: {response.error_message}")

        return response.final_output or ""

    def _apply_approval_mode(
        self,
        signals: List[SignalRecommendation],
        approval_mode: str,
        confidence_threshold: float
    ) -> List[SignalRecommendation]:
        """
        根据审核模式过滤信号

        Args:
            signals: 信号列表
            approval_mode: 审核模式（always/conditional/auto）
            confidence_threshold: 置信度阈值

        Returns:
            过滤后的信号列表
        """
        if approval_mode == 'auto':
            # 自动执行模式：返回所有信号
            return signals

        elif approval_mode == 'always':
            # 必须人工审核模式：标记所有信号为待审核
            # 在实际系统中，这些信号会被保存到待审核队列
            for signal in signals:
                signal.metadata['requires_approval'] = True
                signal.metadata['approval_status'] = 'pending'
            return signals

        elif approval_mode == 'conditional':
            # 条件审核模式：置信度高于阈值自动执行
            approved_signals = []
            pending_signals = []

            for signal in signals:
                if signal.confidence >= confidence_threshold:
                    # 高置信度：自动执行
                    signal.metadata['requires_approval'] = False
                    signal.metadata['approval_status'] = 'auto_approved'
                    approved_signals.append(signal)
                else:
                    # 低置信度：需要人工审核
                    signal.metadata['requires_approval'] = True
                    signal.metadata['approval_status'] = 'pending'
                    pending_signals.append(signal)

            # 记录待审核信号数量
            if pending_signals:
                logger.info(
                    f"{len(pending_signals)} signals require manual approval "
                    f"(confidence < {confidence_threshold})"
                )

            return approved_signals + pending_signals

        else:
            logger.warning(f"Unknown approval mode: {approval_mode}, returning all signals")
            return signals


# ========================================================================
# 待审核信号管理（辅助类）
# ========================================================================

class PendingApprovalQueue:
    """
    待审核信号队列管理

    管理需要人工审核的 AI 信号
    """

    def __init__(self):
        self._queue = {}  # {strategy_id: [signals]}

    def add_pending_signals(
        self,
        strategy_id: int,
        portfolio_id: int,
        signals: List[SignalRecommendation]
    ) -> None:
        """
        添加待审核信号到队列

        Args:
            strategy_id: 策略ID
            portfolio_id: 投资组合ID
            signals: 待审核信号列表
        """
        key = f"{strategy_id}:{portfolio_id}"

        if key not in self._queue:
            self._queue[key] = []

        self._queue[key].extend(signals)

    def get_pending_signals(
        self,
        strategy_id: int,
        portfolio_id: int
    ) -> List[SignalRecommendation]:
        """
        获取待审核信号

        Args:
            strategy_id: 策略ID
            portfolio_id: 投资组合ID

        Returns:
            待审核信号列表
        """
        key = f"{strategy_id}:{portfolio_id}"
        return self._queue.get(key, [])

    def approve_signal(
        self,
        strategy_id: int,
        portfolio_id: int,
        asset_code: str
    ) -> bool:
        """
        审核通过信号

        Args:
            strategy_id: 策略ID
            portfolio_id: 投资组合ID
            asset_code: 资产代码

        Returns:
            是否成功
        """
        key = f"{strategy_id}:{portfolio_id}"
        signals = self._queue.get(key, [])

        for signal in signals:
            if signal.asset_code == asset_code:
                signal.metadata['approval_status'] = 'approved'
                signal.metadata['requires_approval'] = False
                return True

        return False

    def reject_signal(
        self,
        strategy_id: int,
        portfolio_id: int,
        asset_code: str
    ) -> bool:
        """
        审核拒绝信号

        Args:
            strategy_id: 策略ID
            portfolio_id: 投资组合ID
            asset_code: 资产代码

        Returns:
            是否成功
        """
        key = f"{strategy_id}:{portfolio_id}"
        signals = self._queue.get(key, [])

        for signal in signals:
            if signal.asset_code == asset_code:
                signal.metadata['approval_status'] = 'rejected'
                return True

        return False
