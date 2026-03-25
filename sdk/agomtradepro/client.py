"""
AgomTradePro SDK 核心客户端

提供与 AgomTradePro API 交互的主要接口。
"""

import time
from datetime import date
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import AuthConfig, ClientConfig, load_config
from .exceptions import (
    AgomTradeProAPIError,
    AuthenticationError,
    ConfigurationError,
    ConnectionError as SDKConnectionError,
    raise_for_status,
    ServerError,
    TimeoutError as SDKTimeoutError,
)
from .modules.account import AccountModule
from .modules.agent_context import AgentContextModule
from .modules.agent_proposal import AgentProposalModule
from .modules.agent_runtime import AgentRuntimeModule
from .modules.ai_provider import AIProviderModule
from .modules.alpha import AlphaModule
from .modules.alpha_trigger import AlphaTriggerModule
from .modules.asset_analysis import AssetAnalysisModule
from .modules.audit import AuditModule
from .modules.backtest import BacktestModule
from .modules.beta_gate import BetaGateModule
from .modules.dashboard import DashboardModule
from .modules.config_center import ConfigCenterModule
from .modules.decision_rhythm import DecisionRhythmModule
from .modules.equity import EquityModule
from .modules.events import EventsModule
from .modules.factor import FactorModule
from .modules.filter import FilterModule
from .modules.fund import FundModule
from .modules.hedge import HedgeModule
from .modules.macro import MacroModule
from .modules.market_data import MarketDataModule
from .modules.policy import PolicyModule
from .modules.prompt import PromptModule
from .modules.pulse import PulseModule
from .modules.realtime import RealtimeModule
from .modules.regime import RegimeModule
from .modules.rotation import RotationModule
from .modules.sector import SectorModule
from .modules.sentiment import SentimentModule
from .modules.signal import SignalModule
from .modules.simulated_trading import SimulatedTradingModule
from .modules.strategy import StrategyModule
from .modules.task_monitor import TaskMonitorModule
from .modules.decision_workflow import DecisionWorkflowModule


class AgomTradeProClient:
    """
    AgomTradePro 主客户端

    用法:
        client = AgomTradeProClient(
            base_url="http://localhost:8000",
            api_token="your_token"
        )

        # 访问模块
        regime = client.regime.get_current()
        signals = client.signal.list()
    """

    # 模块实例（延迟初始化）
    _regime: Optional[RegimeModule] = None
    _signal: Optional[SignalModule] = None
    _macro: Optional[MacroModule] = None
    _policy: Optional[PolicyModule] = None
    _backtest: Optional[BacktestModule] = None
    _account: Optional[AccountModule] = None
    _simulated_trading: Optional[SimulatedTradingModule] = None
    _equity: Optional[EquityModule] = None
    _factor: Optional[FactorModule] = None
    _fund: Optional[FundModule] = None
    _sector: Optional[SectorModule] = None
    _strategy: Optional[StrategyModule] = None
    _realtime: Optional[RealtimeModule] = None
    _rotation: Optional[RotationModule] = None
    _hedge: Optional[HedgeModule] = None
    _alpha: Optional[AlphaModule] = None
    _ai_provider: Optional[AIProviderModule] = None
    _prompt: Optional[PromptModule] = None
    _audit: Optional[AuditModule] = None
    _events: Optional[EventsModule] = None
    _decision_rhythm: Optional[DecisionRhythmModule] = None
    _beta_gate: Optional[BetaGateModule] = None
    _alpha_trigger: Optional[AlphaTriggerModule] = None
    _dashboard: Optional[DashboardModule] = None
    _config_center: Optional[ConfigCenterModule] = None
    _asset_analysis: Optional[AssetAnalysisModule] = None
    _sentiment: Optional[SentimentModule] = None
    _task_monitor: Optional[TaskMonitorModule] = None
    _filter: Optional[FilterModule] = None
    _market_data: Optional[MarketDataModule] = None
    _decision_workflow: Optional[DecisionWorkflowModule] = None
    _agent_runtime: Optional[AgentRuntimeModule] = None
    _agent_context: Optional[AgentContextModule] = None
    _agent_proposal: Optional[AgentProposalModule] = None
    _pulse: Optional[PulseModule] = None

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
        verify_ssl: Optional[bool] = None,
        config: Optional[ClientConfig] = None,
    ) -> None:
        """
        初始化客户端

        Args:
            base_url: API 基础 URL
            api_token: API Token（推荐）
            username: 用户名（如使用密码认证）
            password: 密码（如使用密码认证）
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            verify_ssl: 是否验证 SSL 证书
            config: 直接传入配置对象（优先级最高）
        """
        if config:
            self._config = config
        else:
            self._config = load_config(
                base_url=base_url,
                api_token=api_token,
                username=username,
                password=password,
                timeout=timeout,
                max_retries=max_retries,
                verify_ssl=verify_ssl,
            )

        # 验证配置
        try:
            self._config.validate()
        except Exception as e:
            raise ConfigurationError(f"Invalid configuration: {e}")

        # 初始化 HTTP session
        self._session = self._create_session()
        self._headers = self._build_headers()

    def _create_session(self) -> requests.Session:
        """
        创建配置好的 HTTP Session

        Returns:
            配置了重试策略的 Session 对象
        """
        session = requests.Session()
        # MCP/SDK should talk to the configured base_url directly instead of
        # silently inheriting OS/user proxy settings such as 127.0.0.1:10808.
        session.trust_env = False

        # 配置重试策略
        retry_strategy = Retry(
            total=self._config.max_retries,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _build_headers(self) -> dict[str, str]:
        """
        构建请求头

        Returns:
            包含认证信息的请求头
        """
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # API Token 认证
        if self._config.auth.api_token:
            token = self._config.auth.api_token.strip()
            # DRF TokenAuthentication expects "Token <key>".
            # Keep explicit scheme if caller already passed one.
            if token.lower().startswith("token ") or token.lower().startswith("bearer "):
                headers["Authorization"] = token
            else:
                headers["Authorization"] = f"Token {token}"

        return headers

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
    ) -> dict:
        """
        发送 HTTP 请求

        Args:
            method: HTTP 方法
            endpoint: API 端点（相对于 base_url）
            params: URL 查询参数
            data: 表单数据
            json: JSON 数据

        Returns:
            响应 JSON 数据

        Raises:
            AuthenticationError: 认证失败
            ValidationError: 数据验证失败
            NotFoundError: 资源未找到
            RateLimitError: 请求频率限制
            ServerError: 服务器错误
            AgomTradeProAPIError: 其他 API 错误
            ConnectionError: 网络连接失败
            TimeoutError: 请求超时
        """
        url = f"{self._config.base_url.rstrip('/')}/{endpoint.lstrip('/')}"

        try:
            response = self._session.request(
                method=method,
                url=url,
                headers=self._headers,
                params=params,
                data=data,
                json=json,
                timeout=self._config.timeout,
            )

            # 尝试解析 JSON 响应
            try:
                response_data = response.json()
            except ValueError:
                response_data = None

            # 根据状态码抛出异常
            raise_for_status(response.status_code, response_data)

            if isinstance(response_data, dict):
                # Some AgomTradePro endpoints return wrapped payload:
                # {"success": true, "data": {...}}.
                if "data" in response_data and isinstance(response_data.get("success"), bool):
                    return response_data["data"]
                return response_data
            return response_data or {}

        except requests.exceptions.Timeout:
            raise SDKTimeoutError(f"Request to {url} timed out")
        except requests.exceptions.ConnectionError as e:
            raise SDKConnectionError(f"Failed to connect to {url}: {e}")
        except AgomTradeProAPIError:
            raise
        except Exception as e:
            raise AgomTradeProAPIError(f"Unexpected error: {e}")

    # ========================================================================
    # 公共快捷方法
    # ========================================================================

    def get(
        self,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict:
        """
        发送 GET 请求

        Args:
            endpoint: API 端点
            params: URL 查询参数

        Returns:
            响应 JSON 数据
        """
        return self._request("GET", endpoint, params=params)

    def post(
        self,
        endpoint: str,
        data: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
    ) -> dict:
        """
        发送 POST 请求

        Args:
            endpoint: API 端点
            data: 表单数据
            json: JSON 数据

        Returns:
            响应 JSON 数据
        """
        return self._request("POST", endpoint, data=data, json=json)

    def put(
        self,
        endpoint: str,
        data: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
    ) -> dict:
        """
        发送 PUT 请求

        Args:
            endpoint: API 端点
            data: 表单数据
            json: JSON 数据

        Returns:
            响应 JSON 数据
        """
        return self._request("PUT", endpoint, data=data, json=json)

    def patch(
        self,
        endpoint: str,
        data: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
    ) -> dict:
        """
        发送 PATCH 请求

        Args:
            endpoint: API 端点
            data: 表单数据
            json: JSON 数据

        Returns:
            响应 JSON 数据
        """
        return self._request("PATCH", endpoint, data=data, json=json)

    def delete(
        self,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict:
        """
        发送 DELETE 请求

        Args:
            endpoint: API 端点
            params: URL 查询参数

        Returns:
            响应 JSON 数据
        """
        return self._request("DELETE", endpoint, params=params)

    # ========================================================================
    # 模块访问属性
    # ========================================================================

    @property
    def regime(self) -> RegimeModule:
        """Regime 判定模块"""
        if self._regime is None:
            self._regime = RegimeModule(self)
        return self._regime

    @property
    def signal(self) -> SignalModule:
        """投资信号模块"""
        if self._signal is None:
            self._signal = SignalModule(self)
        return self._signal

    @property
    def macro(self) -> MacroModule:
        """宏观数据模块"""
        if self._macro is None:
            self._macro = MacroModule(self)
        return self._macro

    @property
    def policy(self) -> PolicyModule:
        """政策事件模块"""
        if self._policy is None:
            self._policy = PolicyModule(self)
        return self._policy

    @property
    def backtest(self) -> BacktestModule:
        """回测引擎模块"""
        if self._backtest is None:
            self._backtest = BacktestModule(self)
        return self._backtest

    @property
    def account(self) -> AccountModule:
        """账户管理模块"""
        if self._account is None:
            self._account = AccountModule(self)
        return self._account

    @property
    def simulated_trading(self) -> SimulatedTradingModule:
        """模拟盘交易模块"""
        if self._simulated_trading is None:
            self._simulated_trading = SimulatedTradingModule(self)
        return self._simulated_trading

    @property
    def equity(self) -> EquityModule:
        """个股分析模块"""
        if self._equity is None:
            self._equity = EquityModule(self)
        return self._equity

    @property
    def factor(self) -> FactorModule:
        """因子选股模块"""
        if self._factor is None:
            self._factor = FactorModule(self)
        return self._factor

    @property
    def fund(self) -> FundModule:
        """基金分析模块"""
        if self._fund is None:
            self._fund = FundModule(self)
        return self._fund

    @property
    def sector(self) -> SectorModule:
        """板块分析模块"""
        if self._sector is None:
            self._sector = SectorModule(self)
        return self._sector

    @property
    def strategy(self) -> StrategyModule:
        """策略管理模块"""
        if self._strategy is None:
            self._strategy = StrategyModule(self)
        return self._strategy

    @property
    def realtime(self) -> RealtimeModule:
        """实时价格监控模块"""
        if self._realtime is None:
            self._realtime = RealtimeModule(self)
        return self._realtime

    @property
    def rotation(self) -> RotationModule:
        """资产轮动模块"""
        if self._rotation is None:
            self._rotation = RotationModule(self)
        return self._rotation

    @property
    def hedge(self) -> HedgeModule:
        """对冲组合模块"""
        if self._hedge is None:
            self._hedge = HedgeModule(self)
        return self._hedge

    @property
    def alpha(self) -> AlphaModule:
        """Alpha 信号抽象层模块"""
        if self._alpha is None:
            self._alpha = AlphaModule(self)
        return self._alpha

    @property
    def ai_provider(self) -> AIProviderModule:
        """AI Provider 管理模块"""
        if self._ai_provider is None:
            self._ai_provider = AIProviderModule(self)
        return self._ai_provider

    @property
    def prompt(self) -> PromptModule:
        """Prompt 管理模块"""
        if self._prompt is None:
            self._prompt = PromptModule(self)
        return self._prompt

    @property
    def audit(self) -> AuditModule:
        """审计模块"""
        if self._audit is None:
            self._audit = AuditModule(self)
        return self._audit

    @property
    def events(self) -> EventsModule:
        """事件总线模块"""
        if self._events is None:
            self._events = EventsModule(self)
        return self._events

    @property
    def decision_rhythm(self) -> DecisionRhythmModule:
        """决策频率模块"""
        if self._decision_rhythm is None:
            self._decision_rhythm = DecisionRhythmModule(self)
        return self._decision_rhythm

    @property
    def beta_gate(self) -> BetaGateModule:
        """Beta Gate 模块"""
        if self._beta_gate is None:
            self._beta_gate = BetaGateModule(self)
        return self._beta_gate

    @property
    def alpha_trigger(self) -> AlphaTriggerModule:
        """Alpha Trigger 模块"""
        if self._alpha_trigger is None:
            self._alpha_trigger = AlphaTriggerModule(self)
        return self._alpha_trigger

    @property
    def dashboard(self) -> DashboardModule:
        """Dashboard 模块"""
        if self._dashboard is None:
            self._dashboard = DashboardModule(self)
        return self._dashboard

    @property
    def config_center(self) -> ConfigCenterModule:
        """配置中心模块"""
        if self._config_center is None:
            self._config_center = ConfigCenterModule(self)
        return self._config_center

    @property
    def asset_analysis(self) -> AssetAnalysisModule:
        """资产分析模块"""
        if self._asset_analysis is None:
            self._asset_analysis = AssetAnalysisModule(self)
        return self._asset_analysis

    @property
    def sentiment(self) -> SentimentModule:
        """情绪分析模块"""
        if self._sentiment is None:
            self._sentiment = SentimentModule(self)
        return self._sentiment

    @property
    def task_monitor(self) -> TaskMonitorModule:
        """系统任务监控模块"""
        if self._task_monitor is None:
            self._task_monitor = TaskMonitorModule(self)
        return self._task_monitor

    @property
    def filter(self) -> FilterModule:
        """过滤模块"""
        if self._filter is None:
            self._filter = FilterModule(self)
        return self._filter

    @property
    def market_data(self) -> MarketDataModule:
        """市场数据统一接入层模块"""
        if self._market_data is None:
            self._market_data = MarketDataModule(self)
        return self._market_data

    @property
    def decision_workflow(self) -> DecisionWorkflowModule:
        """决策工作流模块"""
        if self._decision_workflow is None:
            self._decision_workflow = DecisionWorkflowModule(self)
        return self._decision_workflow

    @property
    def agent_runtime(self) -> AgentRuntimeModule:
        """Agent Runtime 任务管理模块"""
        if self._agent_runtime is None:
            self._agent_runtime = AgentRuntimeModule(self)
        return self._agent_runtime

    @property
    def agent_context(self) -> AgentContextModule:
        """Agent Context 上下文快照模块"""
        if self._agent_context is None:
            self._agent_context = AgentContextModule(self)
        return self._agent_context

    @property
    def agent_proposal(self) -> AgentProposalModule:
        """Agent Proposal 提案生命周期模块"""
        if self._agent_proposal is None:
            self._agent_proposal = AgentProposalModule(self)
        return self._agent_proposal

    @property
    def pulse(self) -> PulseModule:
        """Pulse 脉搏模块"""
        if self._pulse is None:
            self._pulse = PulseModule(self)
        return self._pulse

    # ========================================================================
    # 会话管理
    # ========================================================================

    def close(self) -> None:
        """关闭 HTTP Session"""
        if self._session:
            self._session.close()

    def __enter__(self) -> "AgomTradeProClient":
        """支持 with 语句"""
        return self

    def __exit__(self, *args: Any) -> None:
        """退出 with 语句时关闭会话"""
        self.close()
