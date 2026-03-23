"""
脚本执行引擎 - Application 层

遵循项目架构约束：
- 通过依赖注入使用 Protocol 接口
- 使用 RestrictedPython 实现沙箱隔离
- 提供安全的脚本 API
"""
import ast
import logging
from typing import Any, Dict, List, Optional, Set

from RestrictedPython import compile_restricted
from RestrictedPython.Eval import default_guarded_getattr
from RestrictedPython.Guards import (
    full_write_guard,
    guarded_iter_unpack_sequence,
    guarded_unpack_sequence,
    safe_builtins,
    safer_getattr,
)


def safe_dict_getattr(obj, attr):
    """
    安全的字典属性访问

    用于处理脚本的字典访问（如 asset['total_score']）
    """
    if isinstance(obj, dict):
        try:
            return obj[attr]
        except (KeyError, TypeError):
            raise AttributeError(f"'dict' object has no attribute '{attr}'")
    return default_guarded_getattr(obj, attr)

from apps.strategy.domain.entities import ActionType, ScriptConfig, SignalRecommendation, Strategy
from apps.strategy.domain.protocols import (
    AssetPoolProviderProtocol,
    MacroDataProviderProtocol,
    PortfolioDataProviderProtocol,
    RegimeProviderProtocol,
    SignalProviderProtocol,
)

logger = logging.getLogger(__name__)


# ========================================================================
# 沙箱安全模式配置
# ========================================================================

class SecurityMode:
    """沙箱安全模式"""
    STRICT = "strict"        # 严格模式：只允许 math, datetime
    STANDARD = "standard"    # 标准模式：允许 math, datetime, statistics, itertools
    RELAXED = "relaxed"      # 宽松模式：允许 pandas, numpy 等数据处理模块（默认）


class SecurityConfig:
    """安全配置"""

    # 宽松模式配置（用户确认的默认值）
    RELAXED_ALLOWED_MODULES: set[str] = {
        'math', 'datetime', 'statistics', 'itertools',
        'pandas', 'numpy', 'collections', 'fractions',
        'decimal', 'random', 'typing'
    }

    # 标准模式配置
    STANDARD_ALLOWED_MODULES: set[str] = {
        'math', 'datetime', 'statistics', 'itertools',
        'collections', 'fractions', 'decimal', 'random', 'typing'
    }

    # 严格模式配置
    STRICT_ALLOWED_MODULES: set[str] = {'math', 'datetime'}

    # 始终禁止的模块（危险操作）
    FORBIDDEN_MODULES: set[str] = {
        'os', 'sys', 'subprocess', 'eval', 'exec',
        'importlib', 'types', 'pickle', 'shutil',
        'socket', 'urllib', 'requests', 'http',
        'json', 'yaml', 'marshal', 'codecs'
    }

    # 始终禁止的内置函数
    FORBIDDEN_BUILTINS: set[str] = {
        'open', 'file', '__import__', 'reload',
        'compile', 'eval', 'exec', 'exit', 'quit'
    }

    @classmethod
    def get_allowed_modules(cls, security_mode: str = SecurityMode.RELAXED) -> set[str]:
        """
        根据安全模式获取允许的模块列表

        Args:
            security_mode: 安全模式（strict/standard/relaxed）

        Returns:
            允许的模块集合
        """
        if security_mode == SecurityMode.STRICT:
            return cls.STRICT_ALLOWED_MODULES.copy()
        elif security_mode == SecurityMode.STANDARD:
            return cls.STANDARD_ALLOWED_MODULES.copy()
        else:  # RELAXED
            return cls.RELAXED_ALLOWED_MODULES.copy()

    @classmethod
    def is_module_allowed(cls, module_name: str, security_mode: str = SecurityMode.RELAXED) -> bool:
        """
        检查模块是否允许使用

        Args:
            module_name: 模块名称
            security_mode: 安全模式

        Returns:
            是否允许
        """
        # 检查是否在禁止列表中
        if module_name in cls.FORBIDDEN_MODULES:
            return False

        # 检查是否在允许列表中
        allowed_modules = cls.get_allowed_modules(security_mode)
        return module_name in allowed_modules


# ========================================================================
# 脚本 API（提供给沙箱内脚本使用的接口）
# ========================================================================

class ScriptAPI:
    """
    脚本 API 类

    提供给沙箱内脚本使用的安全接口
    """

    def __init__(
        self,
        macro_provider: MacroDataProviderProtocol,
        regime_provider: RegimeProviderProtocol,
        asset_pool_provider: AssetPoolProviderProtocol,
        signal_provider: SignalProviderProtocol,
        portfolio_provider: PortfolioDataProviderProtocol,
        portfolio_id: int
    ):
        """
        初始化脚本 API

        Args:
            macro_provider: 宏观数据提供者
            regime_provider: Regime 提供者
            asset_pool_provider: 资产池提供者
            signal_provider: 信号提供者
            portfolio_provider: 投资组合数据提供者
            portfolio_id: 投资组合ID
        """
        self.macro_provider = macro_provider
        self.regime_provider = regime_provider
        self.asset_pool_provider = asset_pool_provider
        self.signal_provider = signal_provider
        self.portfolio_provider = portfolio_provider
        self.portfolio_id = portfolio_id

    def get_macro_indicator(self, indicator_code: str) -> float | None:
        """
        获取宏观指标值

        Args:
            indicator_code: 指标代码（如 CN_PMI_MANUFACTURING）

        Returns:
            指标值，如果不存在返回 None

        示例：
        >>> pmi = get_macro_indicator('CN_PMI_MANUFACTURING')
        >>> if pmi and pmi > 50:
        ...     print('PMI 扩张')
        """
        try:
            return self.macro_provider.get_indicator(indicator_code)
        except Exception as e:
            logger.error(f"Failed to get macro indicator {indicator_code}: {e}")
            return None

    def get_all_macro_indicators(self) -> dict[str, float]:
        """
        获取所有宏观指标

        Returns:
            指标代码到值的映射

        示例：
        >>> macros = get_all_macro_indicators()
        >>> pmi = macros.get('CN_PMI_MANUFACTURING', 0)
        """
        try:
            return self.macro_provider.get_all_indicators()
        except Exception as e:
            logger.error(f"Failed to get all macro indicators: {e}")
            return {}

    def get_regime(self) -> dict[str, Any]:
        """
        获取当前 Regime 状态

        Returns:
            Regime 状态字典，包含：
            - dominant_regime: 主导 Regime (HG/HD/LG/LD)
            - confidence: 置信度
            - growth_momentum_z: 增长动量 Z-score
            - inflation_momentum_z: 通胀动量 Z-score

        示例：
        >>> regime = get_regime()
        >>> if regime['dominant_regime'] == 'HG':
        ...     print('高增长高通胀环境')
        """
        try:
            return self.regime_provider.get_current_regime()
        except Exception as e:
            logger.error(f"Failed to get regime: {e}")
            return {}

    def get_asset_pool(
        self,
        min_score: float = 60.0,
        limit: int = 50
    ) -> list[dict[str, Any]]:
        """
        获取可投资产池

        Args:
            min_score: 最低评分
            limit: 返回数量限制

        Returns:
            资产列表，每个资产包含：
            - asset_code: 资产代码
            - asset_name: 资产名称
            - total_score: 总评分
            - regime_score: Regime 评分
            - policy_score: 政策评分

        示例：
        >>> assets = get_asset_pool(min_score=70, limit=10)
        >>> for asset in assets:
        ...     print(f"{asset['asset_code']}: {asset['total_score']}")
        """
        try:
            return self.asset_pool_provider.get_investable_assets(min_score=min_score, limit=limit)
        except Exception as e:
            logger.error(f"Failed to get asset pool: {e}")
            return []

    def get_valid_signals(self) -> list[dict[str, Any]]:
        """
        获取有效信号列表

        Returns:
            信号列表，每个信号包含：
            - signal_id: 信号ID
            - asset_code: 资产代码
            - direction: 方向 (LONG/SHORT)
            - logic_desc: 逻辑描述
            - target_regime: 目标 Regime

        示例：
        >>> signals = get_valid_signals()
        >>> long_signals = [s for s in signals if s['direction'] == 'LONG']
        """
        try:
            return self.signal_provider.get_valid_signals()
        except Exception as e:
            logger.error(f"Failed to get valid signals: {e}")
            return []

    def get_portfolio_positions(self) -> list[dict[str, Any]]:
        """
        获取投资组合持仓

        Returns:
            持仓列表，每个持仓包含：
            - asset_code: 资产代码
            - asset_name: 资产名称
            - quantity: 持仓数量
            - avg_cost: 平均成本
            - market_value: 市值

        示例：
        >>> positions = get_portfolio_positions()
        >>> total_value = sum(p['market_value'] for p in positions)
        """
        try:
            return self.portfolio_provider.get_positions(self.portfolio_id)
        except Exception as e:
            logger.error(f"Failed to get portfolio positions: {e}")
            return []

    def get_portfolio_cash(self) -> float:
        """
        获取投资组合现金余额

        Returns:
            现金余额

        示例：
        >>> cash = get_portfolio_cash()
        >>> print(f"可用现金: {cash}")
        """
        try:
            return self.portfolio_provider.get_cash(self.portfolio_id)
        except Exception as e:
            logger.error(f"Failed to get portfolio cash: {e}")
            return 0.0

    def calculate_signal(
        self,
        asset_code: str,
        asset_name: str,
        action: str,
        weight: float | None = None,
        reason: str = "",
        confidence: float = 0.5
    ) -> dict[str, Any]:
        """
        生成交易信号

        Args:
            asset_code: 资产代码
            asset_name: 资产名称
            action: 操作类型（buy/sell/hold）
            weight: 目标权重（0-1）
            reason: 信号原因
            confidence: 置信度（0-1）

        Returns:
            信号字典

        示例：
        >>> calculate_signal(
        ...     'ASSET_CODE',
        ...     '上证指数',
        ...     'buy',
        ...     weight=0.3,
        ...     reason='PMI 扩张',
        ...     confidence=0.8
        ... )
        """
        return {
            'asset_code': asset_code,
            'asset_name': asset_name,
            'action': action,
            'weight': weight,
            'quantity': None,
            'reason': reason,
            'confidence': confidence,
            'metadata': {
                'source': 'script_strategy'
            }
        }


# ========================================================================
# 脚本执行环境（沙箱）
# ========================================================================

class ScriptExecutionEnvironment:
    """
    脚本执行环境（沙箱）

    职责：
    1. 使用 RestrictedPython 编译脚本
    2. 配置安全的执行环境（限制内置函数和模块）
    3. 提供脚本 API
    4. 捕获执行错误和异常
    """

    def __init__(self, security_mode: str = SecurityMode.RELAXED):
        """
        初始化脚本执行环境

        Args:
            security_mode: 安全模式（strict/standard/relaxed）
        """
        self.security_mode = security_mode
        self.allowed_modules = SecurityConfig.get_allowed_modules(security_mode)

    def _prepare_safe_globals(self, script_api: ScriptAPI) -> dict[str, Any]:
        """
        准备安全的全局变量

        Args:
            script_api: 脚本 API 实例

        Returns:
            安全的全局变量字典
        """
        # 基础内置函数（安全版本）
        safe_builtins_dict = {
            '__builtins__': {
                '_getattr_': safe_dict_getattr,  # 使用自定义的安全字典访问
                '_write_': full_write_guard,
                '_getiter_': iter,
                '_getitem_': safe_dict_getattr,  # 用于字典访问
                '_iter_unpack_sequence_': guarded_iter_unpack_sequence,
                '_unpack_sequence_': guarded_unpack_sequence,
                # 允许的基本函数
                'len': len,
                'range': range,
                'enumerate': enumerate,
                'zip': zip,
                'map': map,
                'filter': filter,
                'abs': abs,
                'min': min,
                'max': max,
                'sum': sum,
                'sorted': sorted,
                'any': any,
                'all': all,
                'print': print,  # 仅用于调试
                'bool': bool,
                'int': int,
                'float': float,
                'str': str,
                'list': list,
                'dict': dict,
                'tuple': tuple,
                'set': set,
                'frozenset': frozenset,
            }
        }

        # 添加允许的模块
        safe_globals_dict = safe_builtins_dict.copy()

        # 安全的 __import__ 函数（只允许白名单中的模块）
        def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
            """安全的导入函数"""
            # 获取根模块名
            module_name = name.split('.')[0] if name else None

            if module_name and not SecurityConfig.is_module_allowed(module_name, self.security_mode):
                raise ImportError(f"Module '{module_name}' is not allowed")

            # 使用原始的 __import__
            return __import__(name, globals, locals, fromlist, level)

        safe_globals_dict['__builtins__']['__import__'] = safe_import

        for module_name in self.allowed_modules:
            try:
                module = __import__(module_name)
                safe_globals_dict[module_name] = module
            except ImportError:
                logger.warning(f"Failed to import allowed module: {module_name}")

        # 添加脚本 API
        api_methods = {
            'get_macro_indicator': script_api.get_macro_indicator,
            'get_all_macro_indicators': script_api.get_all_macro_indicators,
            'get_regime': script_api.get_regime,
            'get_asset_pool': script_api.get_asset_pool,
            'get_valid_signals': script_api.get_valid_signals,
            'get_portfolio_positions': script_api.get_portfolio_positions,
            'get_portfolio_cash': script_api.get_portfolio_cash,
            'calculate_signal': script_api.calculate_signal,
        }

        safe_globals_dict.update(api_methods)

        return safe_globals_dict

    def _compile_script(self, script_code: str, script_name: str = "<script>") -> object:
        """
        编译脚本代码

        Args:
            script_code: 脚本代码
            script_name: 脚本名称（用于错误消息）

        Returns:
            编译后的代码对象

        Raises:
            SyntaxError: 脚本语法错误
            ValueError: 编译失败
        """
        try:
            # 使用 RestrictedPython 编译
            # 在新版本中，compile_restricted 直接返回 code 对象
            code = compile_restricted(
                script_code,
                filename=script_name,
                mode='exec'
            )

            # 检查返回结果
            # 如果是 code 对象，直接返回
            if isinstance(code, type(compile("", "", "exec"))):
                return code

            # 如果是带有 errors 属性的对象（旧版本兼容）
            if hasattr(code, 'errors') and code.errors:
                error_msg = "\n".join(code.errors)
                logger.error(f"Script compilation errors:\n{error_msg}")
                raise ValueError(f"Script compilation failed:\n{error_msg}")

            # 如果有 code 属性
            if hasattr(code, 'code'):
                return code.code

            return code

        except SyntaxError as e:
            logger.error(f"Script syntax error: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to compile script: {e}")
            raise

    def _validate_script_safety(self, script_code: str) -> None:
        """
        验证脚本安全性

        Args:
            script_code: 脚本代码

        Raises:
            ValueError: 如果脚本包含不安全的操作
        """
        try:
            tree = ast.parse(script_code)

            for node in ast.walk(tree):
                # 检查导入语句
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    module_name = None
                    if isinstance(node, ast.Import):
                        module_name = node.names[0].name.split('.')[0]
                    elif isinstance(node, ast.ImportFrom):
                        module_name = node.module.split('.')[0] if node.module else None

                    if module_name and not SecurityConfig.is_module_allowed(module_name, self.security_mode):
                        raise ValueError(
                            f"Module '{module_name}' is not allowed in {self.security_mode} mode. "
                            f"Allowed modules: {self.allowed_modules}"
                        )

        except SyntaxError:
            # 语法错误会在编译阶段捕获
            pass

    def execute(
        self,
        script_code: str,
        script_api: ScriptAPI,
        script_name: str = "<script>"
    ) -> list[dict[str, Any]]:
        """
        在沙箱中执行脚本

        Args:
            script_code: 脚本代码
            script_api: 脚本 API 实例
            script_name: 脚本名称

        Returns:
            信号列表

        Raises:
            ValueError: 脚本编译或执行失败
        """
        # 1. 验证脚本安全性
        self._validate_script_safety(script_code)

        # 2. 编译脚本
        code = self._compile_script(script_code, script_name)

        # 3. 准备安全的执行环境
        safe_globals = self._prepare_safe_globals(script_api)
        safe_locals = {'signals': []}  # 用于存储脚本生成的信号

        # 4. 执行脚本
        try:
            exec(code, safe_globals, safe_locals)

            # 5. 获取脚本生成的信号
            signals = safe_locals.get('signals', [])

            # 验证信号格式
            if not isinstance(signals, list):
                raise ValueError("Script must return a 'signals' list")

            for signal in signals:
                if not isinstance(signal, dict):
                    raise ValueError("Each signal must be a dictionary")
                if 'asset_code' not in signal or 'action' not in signal:
                    raise ValueError("Each signal must have 'asset_code' and 'action' fields")

            return signals

        except Exception as e:
            logger.error(f"Script execution failed: {e}", exc_info=True)
            raise ValueError(f"Script execution failed: {str(e)}")


# ========================================================================
# 脚本驱动策略执行器
# ========================================================================

class ScriptBasedStrategyExecutor:
    """
    脚本驱动策略执行器

    职责：
    1. 创建脚本 API
    2. 使用沙箱执行脚本
    3. 解析脚本结果为信号列表
    """

    def __init__(
        self,
        macro_provider: MacroDataProviderProtocol,
        regime_provider: RegimeProviderProtocol,
        asset_pool_provider: AssetPoolProviderProtocol,
        signal_provider: SignalProviderProtocol,
        portfolio_provider: PortfolioDataProviderProtocol,
        security_mode: str = SecurityMode.RELAXED
    ):
        """
        初始化脚本策略执行器

        Args:
            macro_provider: 宏观数据提供者
            regime_provider: Regime 提供者
            asset_pool_provider: 资产池提供者
            signal_provider: 信号提供者
            portfolio_provider: 投资组合数据提供者
            security_mode: 沙箱安全模式（strict/standard/relaxed）
        """
        self.macro_provider = macro_provider
        self.regime_provider = regime_provider
        self.asset_pool_provider = asset_pool_provider
        self.signal_provider = signal_provider
        self.portfolio_provider = portfolio_provider
        self.security_mode = security_mode

    def execute(
        self,
        strategy: Strategy,
        portfolio_id: int
    ) -> list[SignalRecommendation]:
        """
        执行脚本驱动策略

        Args:
            strategy: 策略实体（必须包含 script_config）
            portfolio_id: 投资组合ID

        Returns:
            信号推荐列表

        Raises:
            ValueError: 策略配置无效或脚本执行失败
        """
        if strategy.script_config is None:
            raise ValueError("Script-based strategy must have script_config")

        # 1. 创建脚本 API
        script_api = ScriptAPI(
            macro_provider=self.macro_provider,
            regime_provider=self.regime_provider,
            asset_pool_provider=self.asset_pool_provider,
            signal_provider=self.signal_provider,
            portfolio_provider=self.portfolio_provider,
            portfolio_id=portfolio_id
        )

        # 2. 创建沙箱执行环境
        env = ScriptExecutionEnvironment(security_mode=self.security_mode)

        # 3. 执行脚本
        try:
            raw_signals = env.execute(
                script_code=strategy.script_config.script_code,
                script_api=script_api,
                script_name=f"strategy_{strategy.strategy_id}"
            )

            # 4. 转换为 SignalRecommendation 实体
            signals = []
            for signal_data in raw_signals:
                try:
                    signal = SignalRecommendation(
                        asset_code=signal_data.get('asset_code', ''),
                        asset_name=signal_data.get('asset_name', ''),
                        action=ActionType(signal_data.get('action', 'hold')),
                        weight=signal_data.get('weight'),
                        quantity=signal_data.get('quantity'),
                        reason=signal_data.get('reason', ''),
                        confidence=signal_data.get('confidence', 0.5),
                        metadata=signal_data.get('metadata', {})
                    )
                    signals.append(signal)
                except (ValueError, KeyError) as e:
                    logger.warning(f"Invalid signal data: {signal_data}, error: {e}")
                    continue

            logger.info(f"Script execution succeeded: {len(signals)} signals generated")
            return signals

        except Exception as e:
            logger.error(f"Script strategy execution failed: {e}")
            raise
