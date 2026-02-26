# 📑 AgomSAAF 项目需求与系统架构全手册 (V3.4 实施版)

> **版本说明**：
> - V3.0：基于 V2.5 进行实质性修订，解决金融逻辑定义缺失、数据源可及性、中国市场适配问题
> - V3.1：新增关键技术修正
>   - ⚠️ HP 滤波后视偏差警告与扩张窗口强制要求
>   - 🔧 Domain 与 Pandas 边界处理的计算协议模式
>   - 🛡️ 数据源 Failover 故障转移机制
>   - 🔐 统一密钥管理与安全配置规范
> - V3.2：新增数据质量与算法工程细节
>   - 🔍 数据源冲突检测与容差校验（DataReconciliator）
>   - 📊 Kalman 滤波完整工程实现（Domain 参数实体 + Infra 算法）
>   - ⚖️ HP vs Kalman 适用场景对比与推荐策略
> - V3.3：项目配置优化
>   - 📝 项目代号更正为 Agom Strategic Asset Allocation Framework
>   - 💾 初期使用 SQLite 简化开发，提供 PostgreSQL 迁移路径
> - V3.4：开发流程明确化
>   - 🖥️ 明确"本地无 Docker 开发 → 打包 Docker 部署"工作流
>   - 📦 完整 Dockerfile + docker-compose 生产配置
>   - 🗺️ 路线图标注各阶段开发/部署模式

---

## 1. 项目概览 (Project Overview)

* **项目代号**：AgomSAAF (Agom Strategic Asset Allocation Framework)
* **核心使命**：构建一套"环境准入"系统。其核心不在于预测价格，而在于通过宏观象限（Regime）与政策维度（Policy）的强过滤，确保投资者**"不在错误的世界里，用正确的逻辑下重注"**。
* **适用市场**：中国 A 股、港股、美股及全球主要债券市场
* **技术栈**：Django 5.x + SQLite（初期）/ PostgreSQL（生产） + Celery + Redis + Pandas

### 1.1 对外接入能力（SDK + MCP）

为支持自动化脚本与 AI Agent，系统提供两类对外接入层（位于 `sdk/` 目录）：

- **Python SDK**（`sdk/agomsaaf`）
  - 统一入口：`AgomSAAFClient`
  - 提供按业务模块分组的方法访问（含核心业务与治理模块）
  - 认证方式：DRF Token（`Authorization: Token <token>`）

- **MCP Server**（`sdk/agomsaaf_mcp`）
  - 面向 Claude Code 等 AI 工具调用场景
  - 工具能力映射 SDK 模块，并支持读写操作
  - 内置 RBAC 角色权限控制（`admin/owner/analyst/investment_manager/trader/risk/read_only`）

当前状态（2026-02-26）：
- SDK 扩展模块端点契约测试已覆盖主要 CRUD/动作路径
- MCP 工具注册、执行与 RBAC 测试已通过（本地测试 `98 passed`）
- OpenAI 兼容链路支持 `dual / responses_only / chat_only` 三种模式
- 说明：测试数字为当日快照，最终以最新 CI/本地执行结果为准

相关文档：
- `sdk/README.md`
- `docs/plans/sdk_mcp_coverage_matrix_20260226.md`
- `docs/testing/sdk-mcp-integration-test-plan.md`

---

## 2. 核心金融逻辑定义 (Financial Logic Specification)

> ⚠️ **本章是系统的"公理层"，所有代码实现必须严格遵循此处定义。**

### 2.1 Regime 象限定义

系统将宏观环境划分为四个象限，基于 **增长动量** 与 **通胀动量** 两个维度：

| 象限 | 增长动量 | 通胀动量 | 典型资产偏好 |
|------|----------|----------|--------------|
| **Recovery（复苏）** | ↑ 加速 | ↓ 减速 | 权益、可转债、铜 |
| **Overheat（过热）** | ↑ 加速 | ↑ 加速 | 商品、通胀挂钩债、能源股 |
| **Stagflation（滞胀）** | ↓ 减速 | ↑ 加速 | 现金、短债、黄金、防御股 |
| **Deflation（通缩）** | ↓ 减速 | ↓ 减速 | 长久期国债、高评级信用债 |

### 2.2 动量计算方法（当前实现）

> **📌 最新更新（2026-01-22）**：通胀指标动量计算优化
> 详细文档：`docs/regime_calculation_logic.md`

**当前实现**：直接使用原始数据计算动量，区分增长指标和通胀指标：

```
增长指标（PMI等）- 相对动量：
  growth_momentum = (current - past) / |past|
  示例：PMI 49.5 → 50.2，动量 = +1.4%

通胀指标（CPI、PPI）- 绝对差值动量：
  inflation_momentum = current - past  # 百分点差值
  示例：CPI 0.1% → 0.3%，动量 = +0.2pp（而非200%）
```

**关键改进**：
- ❌ **移除**了 HP/Kalman 滤波（避免后视偏差和扩张窗口复杂度）
- ✅ 增长指标使用相对动量（反映百分比变化）
- ✅ **通胀指标使用绝对差值动量**（避免低基数扭曲）
- ✅ 滚动 Z-score 标准化（60天窗口，最小24天）
- ✅ Sigmoid 概率转换（k=2.0）

---

**原设计方案（仅供参考，已不采用）**：

**问题**：原方案直接对原始数据计算二阶导，噪音敏感度极高。

**修正方案**：采用 **趋势提取 + 动量计算** 两步法：

```
Step 1: 趋势提取
  - 使用 HP 滤波（lambda=129600 for 月度数据）提取趋势项
  - 或使用 Kalman 滤波（适用于实时更新场景）

Step 2: 动量计算
  - growth_momentum = trend_growth[t] - trend_growth[t-3]  # 3个月变化
  - inflation_momentum = trend_inflation[t] - trend_inflation[t-3]

Step 3: 标准化
  - 将动量值标准化为 Z-score（基于过去 60 个月滚动窗口）
  - Z > 0.5 视为"加速"，Z < -0.5 视为"减速"，中间为"中性"
```

> ⚠️ **关键警告：HP 滤波的后视偏差陷阱**
>
> HP 滤波是**双向滤波器**（two-sided filter）。如果在 2025 年对 2015-2025 全量数据跑一次 HP 滤波，得到的 2018 年趋势值实际上包含了 2019-2025 的信息。这在回测中是**严重的前视偏差（Look-ahead Bias）**。
>
> **强制要求**：在 `RegimeCalculator` 的回测模式中，必须使用**扩张窗口（Expanding Window）**：
> - 计算 T 时刻的趋势，只能输入 [1, T] 的数据
> - 滤波器绝不能看到 T+1 及之后的数据
> - 这意味着每个时间点都需要重新跑一次滤波，计算成本更高但结果真实

```python
# 错误示范 ❌
def calculate_trend_wrong(full_series):
    # 一次性对全量数据滤波，2018年的值包含了2025年信息
    trend, cycle = hpfilter(full_series, lamb=129600)
    return trend

# 正确示范 ✅
def calculate_trend_correct(series, as_of_index):
    # 只用 [0, as_of_index] 的数据
    truncated = series[:as_of_index + 1]
    trend, cycle = hpfilter(truncated, lamb=129600)
    return trend[-1]  # 只返回最后一个点的趋势值
```

### 2.3 Kalman 滤波实现（推荐用于实时场景）

> **为什么推荐 Kalman 滤波**：与 HP 滤波不同，Kalman 滤波是**单向滤波器**（one-sided），天然没有后视偏差。每个时间点的估计只依赖当前及历史数据，非常适合实时动量计算。

**Domain 层：滤波参数实体定义**

```python
# apps/regime/domain/entities.py
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class KalmanFilterParams:
    """
    Kalman 滤波参数配置
    
    用于趋势提取的状态空间模型：
    - 状态方程: x[t] = F * x[t-1] + w,  w ~ N(0, Q)
    - 观测方程: y[t] = H * x[t] + v,    v ~ N(0, R)
    
    对于趋势提取，我们使用局部线性趋势模型：
    - 状态向量: [level, slope]
    - level[t] = level[t-1] + slope[t-1] + w1
    - slope[t] = slope[t-1] + w2
    - y[t] = level[t] + v
    """
    
    # 状态转移噪声（过程噪声）
    level_variance: float = 0.01      # level 变化的方差（越小趋势越平滑）
    slope_variance: float = 0.001     # slope 变化的方差（越小趋势变化越慢）
    
    # 观测噪声
    observation_variance: float = 1.0  # 观测误差方差（越大越信任趋势）
    
    # 初始状态
    initial_level: Optional[float] = None   # None 表示用第一个观测值
    initial_slope: float = 0.0              # 初始斜率
    initial_level_var: float = 10.0         # 初始 level 不确定性
    initial_slope_var: float = 1.0          # 初始 slope 不确定性
    
    @classmethod
    def for_monthly_macro(cls) -> "KalmanFilterParams":
        """月度宏观数据的推荐参数"""
        return cls(
            level_variance=0.05,
            slope_variance=0.005,
            observation_variance=0.5,
        )
    
    @classmethod
    def for_daily_price(cls) -> "KalmanFilterParams":
        """日度价格数据的推荐参数（噪音更大）"""
        return cls(
            level_variance=0.1,
            slope_variance=0.01,
            observation_variance=2.0,
        )

@dataclass(frozen=True)
class KalmanState:
    """Kalman 滤波器的当前状态（可持久化）"""
    level: float              # 当前水平估计
    slope: float              # 当前斜率估计
    level_variance: float     # level 估计的不确定性
    slope_variance: float     # slope 估计的不确定性
    level_slope_cov: float    # level 和 slope 的协方差
    
    def to_dict(self) -> dict:
        """序列化为字典，便于存储"""
        return {
            "level": self.level,
            "slope": self.slope,
            "level_variance": self.level_variance,
            "slope_variance": self.slope_variance,
            "level_slope_cov": self.level_slope_cov,
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> "KalmanState":
        return cls(**d)
```

**Infrastructure 层：Kalman 滤波器实现**

```python
# apps/shared/infrastructure/kalman_filter.py
import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass

from apps.regime.domain.entities import KalmanFilterParams, KalmanState

@dataclass
class KalmanFilterResult:
    """滤波结果"""
    filtered_levels: List[float]    # 滤波后的趋势值
    filtered_slopes: List[float]    # 滤波后的斜率（动量）
    final_state: KalmanState        # 最终状态（可用于增量更新）

class LocalLinearTrendFilter:
    """
    局部线性趋势 Kalman 滤波器
    
    特点：
    1. 单向滤波，无后视偏差
    2. 支持增量更新（来一个数据点更新一次）
    3. 可持久化状态，适合实时系统
    """
    
    def __init__(self, params: KalmanFilterParams):
        self.params = params
        
        # 状态转移矩阵 F: [level, slope] -> [level + slope, slope]
        self.F = np.array([
            [1.0, 1.0],
            [0.0, 1.0]
        ])
        
        # 观测矩阵 H: 只观测 level
        self.H = np.array([[1.0, 0.0]])
        
        # 过程噪声协方差 Q
        self.Q = np.array([
            [params.level_variance, 0.0],
            [0.0, params.slope_variance]
        ])
        
        # 观测噪声协方差 R
        self.R = np.array([[params.observation_variance]])
    
    def filter(
        self, 
        observations: List[float],
        initial_state: Optional[KalmanState] = None
    ) -> KalmanFilterResult:
        """
        对完整序列进行滤波
        
        Args:
            observations: 观测值序列
            initial_state: 初始状态（用于增量更新场景）
        
        Returns:
            KalmanFilterResult: 包含滤波后的趋势和动量
        """
        n = len(observations)
        if n == 0:
            raise ValueError("Empty observations")
        
        # 初始化状态
        if initial_state is not None:
            x = np.array([initial_state.level, initial_state.slope])
            P = np.array([
                [initial_state.level_variance, initial_state.level_slope_cov],
                [initial_state.level_slope_cov, initial_state.slope_variance]
            ])
        else:
            # 默认初始化
            x = np.array([
                self.params.initial_level if self.params.initial_level is not None else observations[0],
                self.params.initial_slope
            ])
            P = np.array([
                [self.params.initial_level_var, 0.0],
                [0.0, self.params.initial_slope_var]
            ])
        
        filtered_levels = []
        filtered_slopes = []
        
        for y in observations:
            # === 预测步骤 ===
            x_pred = self.F @ x
            P_pred = self.F @ P @ self.F.T + self.Q
            
            # === 更新步骤 ===
            # 计算卡尔曼增益
            S = self.H @ P_pred @ self.H.T + self.R  # 创新协方差
            K = P_pred @ self.H.T @ np.linalg.inv(S)  # 卡尔曼增益
            
            # 更新状态
            innovation = y - (self.H @ x_pred)[0]
            x = x_pred + (K @ np.array([[innovation]])).flatten()
            P = (np.eye(2) - K @ self.H) @ P_pred
            
            filtered_levels.append(x[0])
            filtered_slopes.append(x[1])
        
        final_state = KalmanState(
            level=x[0],
            slope=x[1],
            level_variance=P[0, 0],
            slope_variance=P[1, 1],
            level_slope_cov=P[0, 1]
        )
        
        return KalmanFilterResult(
            filtered_levels=filtered_levels,
            filtered_slopes=filtered_slopes,
            final_state=final_state
        )
    
    def update_single(
        self, 
        observation: float, 
        state: KalmanState
    ) -> Tuple[float, float, KalmanState]:
        """
        增量更新：处理单个新观测值
        
        适用于实时系统：来一个数据点，更新一次状态
        
        Returns:
            (filtered_level, filtered_slope, new_state)
        """
        x = np.array([state.level, state.slope])
        P = np.array([
            [state.level_variance, state.level_slope_cov],
            [state.level_slope_cov, state.slope_variance]
        ])
        
        # 预测
        x_pred = self.F @ x
        P_pred = self.F @ P @ self.F.T + self.Q
        
        # 更新
        S = self.H @ P_pred @ self.H.T + self.R
        K = P_pred @ self.H.T @ np.linalg.inv(S)
        
        innovation = observation - (self.H @ x_pred)[0]
        x_new = x_pred + (K @ np.array([[innovation]])).flatten()
        P_new = (np.eye(2) - K @ self.H) @ P_pred
        
        new_state = KalmanState(
            level=x_new[0],
            slope=x_new[1],
            level_variance=P_new[0, 0],
            slope_variance=P_new[1, 1],
            level_slope_cov=P_new[0, 1]
        )
        
        return x_new[0], x_new[1], new_state
```

**在 Regime 计算中使用 Kalman 滤波**：

```python
# apps/regime/domain/services.py
from dataclasses import dataclass
from typing import Protocol, List
from datetime import date

class TrendFilterProtocol(Protocol):
    """趋势滤波器协议（Domain 层定义）"""
    def extract_trend_and_momentum(
        self, 
        series: List[float]
    ) -> tuple[List[float], List[float]]:
        """返回 (趋势序列, 动量序列)"""
        ...

@dataclass
class RegimeCalculator:
    """Regime 计算器"""
    
    growth_filter: TrendFilterProtocol
    inflation_filter: TrendFilterProtocol
    
    def calculate(
        self,
        growth_series: List[float],
        inflation_series: List[float],
        as_of_date: date
    ) -> "RegimeSnapshot":
        # 提取趋势和动量
        growth_trend, growth_momentum = self.growth_filter.extract_trend_and_momentum(
            growth_series
        )
        inflation_trend, inflation_momentum = self.inflation_filter.extract_trend_and_momentum(
            inflation_series
        )
        
        # 取最新的动量值
        latest_growth_momentum = growth_momentum[-1] if growth_momentum else 0.0
        latest_inflation_momentum = inflation_momentum[-1] if inflation_momentum else 0.0
        
        # 计算 Z-score（这里简化处理）
        growth_z = self._to_zscore(latest_growth_momentum, growth_momentum)
        inflation_z = self._to_zscore(latest_inflation_momentum, inflation_momentum)
        
        # 计算模糊权重
        distribution = self._calculate_distribution(growth_z, inflation_z)
        
        return RegimeSnapshot(
            growth_momentum_z=growth_z,
            inflation_momentum_z=inflation_z,
            distribution=distribution,
            dominant_regime=max(distribution, key=distribution.get),
            confidence=self._calculate_confidence(distribution),
            observed_at=as_of_date
        )
```

**HP vs Kalman 对比表**：

| 特性 | HP 滤波 | Kalman 滤波 |
|------|---------|-------------|
| 后视偏差 | ⚠️ 有（需用扩张窗口规避） | ✅ 无（天然单向） |
| 计算复杂度 | O(n) 每次全量 | O(1) 增量更新 |
| 适用场景 | 历史回测 | 实时系统 |
| 参数调优 | 只有 λ | 需调 Q, R, 初始状态 |
| 状态持久化 | 不需要 | 需要（存储 KalmanState） |
| 边界效应 | 两端不稳定 | 开头不稳定（warm-up） |

**推荐策略**：
- **回测场景**：使用扩张窗口 HP 滤波（结果更平滑，便于可视化）
- **实时场景**：使用 Kalman 滤波（增量更新，无后视偏差）
- **生产系统**：两者并行，用 HP 结果校验 Kalman 结果的合理性

### 2.4 模糊权重计算

系统不输出单一标签，而是输出各象限的概率权重：

```python
def calculate_regime_distribution(growth_z: float, inflation_z: float) -> Dict[str, float]:
    """
    基于模糊逻辑计算象限权重
    使用 Sigmoid 函数实现平滑过渡
    """
    def sigmoid(x, k=2): 
        return 1 / (1 + exp(-k * x))
    
    p_growth_up = sigmoid(growth_z)
    p_inflation_up = sigmoid(inflation_z)
    
    return {
        "Recovery": p_growth_up * (1 - p_inflation_up),
        "Overheat": p_growth_up * p_inflation_up,
        "Stagflation": (1 - p_growth_up) * p_inflation_up,
        "Deflation": (1 - p_growth_up) * (1 - p_inflation_up),
    }
```

### 2.5 Policy 政策档位定义

| 档位 | 定义 | 触发条件示例 | 系统响应 |
|------|------|--------------|----------|
| **P0（常态）** | 无重大政策干预 | 默认状态 | 正常运行 Regime 逻辑 |
| **P1（预警）** | 政策信号出现，但尚未落地 | 央行官员鹰派/鸽派讲话、政治局会议定调 | 提升现金权重 5-10%，缩短久期 |
| **P2（干预）** | 实质性政策出台 | 降息/加息、降准、财政刺激方案公布 | 暂停 Regime 信号 24-48 小时，等待市场消化 |
| **P3（危机）** | 极端政策或市场熔断 | 熔断、汇率一次性调整、紧急救市 | 全仓转现金或对冲，人工接管 |

**关键约束**：
- P1-P3 状态由人工标注，系统仅记录和执行
- 每条 PolicyLog 必须关联证据 URL（新闻链接、官方公告）
- P2/P3 状态自动触发 Slack/邮件告警

### 2.6 准入矩阵（Eligibility Matrix）

定义每类资产在不同 Regime 下的适配性：

| 资产类别 | Recovery | Overheat | Stagflation | Deflation |
|----------|----------|----------|-------------|-----------|
| A股成长 | ✅ Preferred | ⚠️ Neutral | ❌ Hostile | ⚠️ Neutral |
| A股价值 | ✅ Preferred | ✅ Preferred | ⚠️ Neutral | ❌ Hostile |
| 中国国债 | ⚠️ Neutral | ❌ Hostile | ⚠️ Neutral | ✅ Preferred |
| 黄金 | ⚠️ Neutral | ✅ Preferred | ✅ Preferred | ⚠️ Neutral |
| 商品期货 | ⚠️ Neutral | ✅ Preferred | ❌ Hostile | ❌ Hostile |
| 现金 | ❌ Hostile | ⚠️ Neutral | ✅ Preferred | ⚠️ Neutral |

**权重转换规则**：
- ✅ Preferred：允许配置至策略上限（如 30%）
- ⚠️ Neutral：允许配置至中性权重（如 15%）
- ❌ Hostile：强制降至最低（如 0-5%），触发 Rejection 记录

### 2.7 证伪锚定（Invalidation Logic）

每条投资信号必须包含明确的证伪条件：

```python
@dataclass
class InvestmentSignal:
    asset_code: str
    direction: Literal["LONG", "SHORT", "NEUTRAL"]
    logic_desc: str  # 为什么看好/看空
    invalidation_logic: str  # 必填：什么情况下承认看错
    invalidation_threshold: Optional[float]  # 可选：量化阈值
    
    # 示例
    # logic_desc = "PMI 连续 3 月回升，制造业复苏确认"
    # invalidation_logic = "PMI 跌破 50 且连续 2 月低于前值"
    # invalidation_threshold = 49.5
```

---

## 3. 数据源架构 (Data Source Architecture)

### 3.1 中国市场数据源

| 数据源 | 用途 | 接口稳定性 | 成本 | 推荐度 |
|--------|------|------------|------|--------|
| **Tushare Pro** | A股行情、财务、指数 | ⭐⭐⭐⭐ | 付费（积分制） | ⭐⭐⭐⭐⭐ |
| **AKShare** | 宏观数据、期货、基金 | ⭐⭐⭐ | 免费 | ⭐⭐⭐⭐ |
| **Baostock** | A股历史行情 | ⭐⭐⭐⭐ | 免费 | ⭐⭐⭐ |
| **东方财富 Choice** | 全品类（机构级） | ⭐⭐⭐⭐⭐ | 高（年费制） | ⭐⭐⭐⭐ |
| **Wind** | 全品类（机构级） | ⭐⭐⭐⭐⭐ | 极高 | ⭐⭐⭐ |

**推荐组合**：Tushare Pro（行情主力） + AKShare（宏观补充） + 自建爬虫（政策事件）

### 3.2 数据源高可用设计

> ⚠️ **AKShare 稳定性警告**：AKShare 基于爬虫实现，源站改版即失效。生产环境必须有 Failover 机制。

**故障转移架构**：

```python
# apps/macro/infrastructure/adapters/base.py
from abc import ABC, abstractmethod
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)

class MacroAdapterProtocol(ABC):
    """宏观数据适配器协议"""
    
    @abstractmethod
    def fetch_pmi(self) -> List[MacroIndicator]: ...
    
    @abstractmethod
    def fetch_cpi(self) -> List[MacroIndicator]: ...
    
    @abstractmethod
    def is_available(self) -> bool:
        """健康检查"""
        ...

class FailoverAdapter(MacroAdapterProtocol):
    """故障转移适配器 - 按优先级尝试多个数据源"""
    
    def __init__(self, adapters: List[MacroAdapterProtocol]):
        self.adapters = adapters  # 按优先级排序
    
    def _try_fetch(self, method_name: str) -> List[MacroIndicator]:
        last_error = None
        for adapter in self.adapters:
            try:
                if not adapter.is_available():
                    logger.warning(f"{adapter.__class__.__name__} unavailable, skipping")
                    continue
                    
                method = getattr(adapter, method_name)
                result = method()
                
                if result:  # 成功获取数据
                    logger.info(f"Fetched via {adapter.__class__.__name__}")
                    return result
                    
            except Exception as e:
                last_error = e
                logger.error(f"{adapter.__class__.__name__} failed: {e}")
                continue
        
        # 所有数据源都失败
        raise DataSourceUnavailableError(
            f"All adapters failed for {method_name}. Last error: {last_error}"
        )
    
    def fetch_pmi(self) -> List[MacroIndicator]:
        return self._try_fetch("fetch_pmi")
    
    def fetch_cpi(self) -> List[MacroIndicator]:
        return self._try_fetch("fetch_cpi")
```

**备用数据源配置**：

| 指标 | 主数据源 | 备用数据源 1 | 备用数据源 2 |
|------|----------|--------------|--------------|
| PMI | AKShare | 网易财经爬虫 | 手动 CSV 导入 |
| CPI | AKShare | 国家统计局爬虫 | 聚合数据 API |
| 利率 | Tushare | 中国货币网爬虫 | AKShare |
| 指数行情 | Tushare | Baostock | Yahoo Finance |

**Celery 任务中的故障处理**：

```python
# apps/macro/application/tasks.py
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5分钟后重试
    autoretry_for=(DataSourceUnavailableError,)
)
def sync_macro_data(self):
    try:
        use_case = SyncMacroDataUseCase(
            adapter=FailoverAdapter([
                AKShareAdapter(),
                NeteaseCrawler(),
                ManualFallback(),
            ])
        )
        use_case.execute()
    except MaxRetriesExceededError:
        # 发送告警
        send_alert("Macro data sync failed after 3 retries")
        raise
```

### 3.3 数据质量校验与冲突解决

> ⚠️ **关键问题**：当备用数据源返回的数据与主数据源历史数据不一致时，默默切换会导致脏数据污染数据库。

**数据一致性校验器**：

```python
# apps/macro/infrastructure/validators.py
from dataclasses import dataclass
from typing import List, Optional
from datetime import date
import logging

logger = logging.getLogger(__name__)

@dataclass
class ReconciliationResult:
    is_consistent: bool
    max_deviation_pct: float
    conflicting_points: List[dict]
    recommendation: str  # "accept", "reject", "manual_review"

class DataReconciliator:
    """数据源一致性校验器"""
    
    # 各指标的容差阈值（百分比）
    TOLERANCE_THRESHOLDS = {
        "CN_PMI_MANUFACTURING": 0.5,   # PMI 容差 0.5%
        "CN_CPI_YOY": 1.0,             # CPI 容差 1%
        "CN_M2_YOY": 1.0,              # M2 容差 1%
        "SHIBOR_1W": 2.0,              # 利率容差 2%（基点波动大）
        "default": 1.0,                # 默认容差 1%
    }
    
    def __init__(self, existing_repo: "MacroRepository"):
        self.existing_repo = existing_repo
    
    def reconcile(
        self,
        new_data: List["MacroIndicator"],
        source_name: str
    ) -> ReconciliationResult:
        """
        校验新数据与已有数据的一致性
        
        逻辑：
        1. 找到新数据与已有数据的重叠时间段
        2. 计算每个重叠点的偏差百分比
        3. 如果最大偏差超过阈值，标记为不一致
        """
        conflicts = []
        max_deviation = 0.0
        
        for indicator in new_data:
            existing = self.existing_repo.get_by_code_and_date(
                code=indicator.code,
                observed_at=indicator.observed_at
            )
            
            if existing is None:
                continue  # 新数据点，无需校验
            
            # 计算偏差
            if existing.value == 0:
                deviation_pct = 100.0 if indicator.value != 0 else 0.0
            else:
                deviation_pct = abs(indicator.value - existing.value) / abs(existing.value) * 100
            
            threshold = self.TOLERANCE_THRESHOLDS.get(
                indicator.code, 
                self.TOLERANCE_THRESHOLDS["default"]
            )
            
            if deviation_pct > threshold:
                conflicts.append({
                    "code": indicator.code,
                    "date": indicator.observed_at,
                    "existing_value": existing.value,
                    "new_value": indicator.value,
                    "deviation_pct": round(deviation_pct, 2),
                    "threshold": threshold,
                    "existing_source": existing.source,
                    "new_source": source_name,
                })
            
            max_deviation = max(max_deviation, deviation_pct)
        
        # 判定结果
        if not conflicts:
            return ReconciliationResult(
                is_consistent=True,
                max_deviation_pct=max_deviation,
                conflicting_points=[],
                recommendation="accept"
            )
        elif len(conflicts) <= 2 and max_deviation < 5.0:
            # 少量小偏差，可能是修订值，接受但记录
            return ReconciliationResult(
                is_consistent=False,
                max_deviation_pct=max_deviation,
                conflicting_points=conflicts,
                recommendation="accept"  # 接受，但记录为新修订版本
            )
        else:
            # 大量或大幅偏差，需人工审核
            return ReconciliationResult(
                is_consistent=False,
                max_deviation_pct=max_deviation,
                conflicting_points=conflicts,
                recommendation="manual_review"
            )
```

**增强版 Failover 适配器**：

```python
# apps/macro/infrastructure/adapters/failover.py

class ReconciliationFailedError(Exception):
    """数据一致性校验失败"""
    pass

class FailoverAdapterWithReconciliation(MacroAdapterProtocol):
    """带数据一致性校验的故障转移适配器"""
    
    def __init__(
        self,
        adapters: List[MacroAdapterProtocol],
        reconciliator: DataReconciliator,
        alert_service: "AlertService"
    ):
        self.adapters = adapters
        self.reconciliator = reconciliator
        self.alert_service = alert_service
    
    def _try_fetch_with_reconciliation(
        self, 
        method_name: str
    ) -> List[MacroIndicator]:
        primary_adapter = self.adapters[0]
        
        # 尝试主数据源
        try:
            if primary_adapter.is_available():
                result = getattr(primary_adapter, method_name)()
                if result:
                    return result
        except Exception as e:
            logger.warning(f"Primary adapter failed: {e}")
        
        # 主数据源失败，尝试备用数据源
        for adapter in self.adapters[1:]:
            try:
                if not adapter.is_available():
                    continue
                
                result = getattr(adapter, method_name)()
                if not result:
                    continue
                
                # ⚠️ 关键：校验备用数据与已有数据的一致性
                reconciliation = self.reconciliator.reconcile(
                    new_data=result,
                    source_name=adapter.__class__.__name__
                )
                
                if reconciliation.recommendation == "accept":
                    if not reconciliation.is_consistent:
                        # 有小偏差，记录但接受
                        logger.warning(
                            f"Data deviation detected from {adapter.__class__.__name__}: "
                            f"max {reconciliation.max_deviation_pct}%"
                        )
                    return result
                
                elif reconciliation.recommendation == "manual_review":
                    # 大偏差，发送告警，不自动切换
                    self.alert_service.send_alert(
                        level="warning",
                        title="Data Source Conflict Detected",
                        message=f"""
                        Backup source {adapter.__class__.__name__} returned conflicting data.
                        Max deviation: {reconciliation.max_deviation_pct}%
                        Conflicts: {reconciliation.conflicting_points}
                        
                        Action required: Manual review before accepting this data.
                        """
                    )
                    # 继续尝试下一个备用源
                    continue
                    
            except Exception as e:
                logger.error(f"{adapter.__class__.__name__} failed: {e}")
                continue
        
        raise DataSourceUnavailableError(
            f"All adapters failed or returned inconsistent data for {method_name}"
        )
```

**数据修订版本管理**：

当检测到合理的数据修订（如官方修正值）时，保留历史版本：

```sql
-- 查询某指标的所有修订版本
SELECT code, observed_at, value, revision_number, source, created_at
FROM macro_indicator
WHERE code = 'CN_GDP_YOY' AND observed_at = '2024-03-01'
ORDER BY revision_number DESC;

-- revision_number = 1: 初值
-- revision_number = 2: 修订值
-- revision_number = 3: 终值
```

### 3.4 宏观指标数据源映射

| 指标 | 中国 | 美国 | 备注 |
|------|------|------|------|
| GDP 增速 | AKShare (`macro_china_gdp`) | FRED (`GDP`) | 季度，滞后 |
| PMI | AKShare (`macro_china_pmi`) | FRED (`NAPM`) | 月度，领先指标 |
| CPI | AKShare (`macro_china_cpi`) | FRED (`CPIAUCSL`) | 月度 |
| PPI | AKShare (`macro_china_ppi`) | FRED (`PPIACO`) | 月度 |
| M2 增速 | AKShare (`macro_china_money_supply`) | FRED (`M2SL`) | 月度 |
| 社融 | AKShare (`macro_china_shrzgm`) | N/A | 中国特有 |
| 利率（政策） | Tushare (`shibor`) | FRED (`FEDFUNDS`) | 日度 |
| 信用利差 | Tushare（中债估值） | FRED (`BAMLC0A0CM`) | 日度 |

### 3.5 Point-in-Time (PIT) 处理策略

**问题**：大多数免费数据源不提供历史发布时间戳。

**务实解决方案**：

```
层级 1：完美 PIT（仅限部分指标）
  - 使用 FRED ALFRED API 获取美国数据的历史修订
  - 中国数据：自建采集系统，每日定时抓取并记录时间戳

层级 2：模拟 PIT（主力方案）
  - 为每个指标定义"发布延迟"（publication_lag）
  - 例如：中国 PMI 通常在次月 1 日发布 → lag = 1 天
  - 例如：中国 GDP 通常在季后 15-20 天发布 → lag = 20 天
  - 回测时使用 observed_at + lag 作为可用日期

层级 3：承认前视（用于快速验证）
  - 在回测报告中明确标注"存在前视偏差"
  - 仅用于逻辑验证，不用于策略评估
```

**数据表结构**：

```sql
CREATE TABLE macro_indicator (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) NOT NULL,           -- 指标代码
    value DECIMAL(20, 6) NOT NULL,       -- 指标值
    observed_at DATE NOT NULL,           -- 指标所属期间
    published_at TIMESTAMP,              -- 实际发布时间（如有）
    publication_lag_days INT DEFAULT 0,  -- 发布延迟天数
    source VARCHAR(20) NOT NULL,         -- 数据源
    revision_number INT DEFAULT 1,       -- 修订版本号
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (code, observed_at, revision_number)
);
```

---

## 4. 系统架构：四层解耦设计

### 4.1 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                    Interface Layer (接口层)                      │
│         DRF API  │  Django Admin  │  CLI Tools  │  Alerts       │
├─────────────────────────────────────────────────────────────────┤
│                   Application Layer (应用层)                     │
│    Use Cases  │  Workflow Orchestration  │  Celery Tasks        │
├─────────────────────────────────────────────────────────────────┤
│                      Domain Layer (领域层)                       │
│    Entities  │  Rules  │  Services  │  Validators               │
│              【禁止依赖 Django/任何外部库】                        │
├─────────────────────────────────────────────────────────────────┤
│                 Infrastructure Layer (基础设施层)                │
│    ORM Models  │  Repositories  │  API Adapters  │  Cache       │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 层间依赖规则

```
Interface → Application → Domain ← Infrastructure
                              ↑
                              └── 依赖反转：Domain 定义接口，Infra 实现
```

**禁令清单**：
- ❌ Domain 层禁止导入 `django.*`、`pandas`、`requests`
- ❌ Application 层禁止直接操作 ORM Model
- ❌ Interface 层禁止包含业务逻辑
- ✅ Domain 层只能使用 Python 标准库 + `dataclasses` + `typing`

### 4.3 Domain 与 Pandas 的"边境线"处理

> **现实挑战**：计算 Z-score、HP 滤波和矩阵运算，纯 Python 循环会慢到无法接受。但让 Domain 依赖 Pandas 又破坏了架构纯洁性。

**折中方案：计算协议模式**

```python
# apps/shared/domain/interfaces.py
from typing import Protocol, List
from dataclasses import dataclass

@dataclass(frozen=True)
class TrendResult:
    """趋势计算结果（纯数据，无 Pandas 依赖）"""
    values: tuple[float, ...]
    z_scores: tuple[float, ...]

class TrendCalculatorProtocol(Protocol):
    """趋势计算协议 - Domain 定义，Infra 实现"""
    def calculate_hp_trend(
        self, 
        series: List[float], 
        lamb: float = 129600
    ) -> TrendResult: ...
    
    def calculate_z_scores(
        self,
        series: List[float],
        window: int = 60
    ) -> tuple[float, ...]: ...
```

```python
# apps/shared/infrastructure/calculators.py
import pandas as pd
import numpy as np
from statsmodels.tsa.filters.hp_filter import hpfilter
from ..domain.interfaces import TrendCalculatorProtocol, TrendResult

class PandasTrendCalculator(TrendCalculatorProtocol):
    """Pandas 实现的趋势计算器"""
    
    def calculate_hp_trend(
        self, 
        series: List[float], 
        lamb: float = 129600
    ) -> TrendResult:
        arr = np.array(series)
        trend, cycle = hpfilter(arr, lamb=lamb)
        
        # 计算趋势的 Z-score
        z_scores = (trend - trend.mean()) / trend.std()
        
        # 返回纯 Python 数据结构，不带 Pandas/Numpy 依赖
        return TrendResult(
            values=tuple(trend.tolist()),
            z_scores=tuple(z_scores.tolist())
        )
    
    def calculate_z_scores(
        self,
        series: List[float],
        window: int = 60
    ) -> tuple[float, ...]:
        s = pd.Series(series)
        rolling_mean = s.rolling(window=window, min_periods=24).mean()
        rolling_std = s.rolling(window=window, min_periods=24).std()
        z = (s - rolling_mean) / rolling_std
        return tuple(z.fillna(0).tolist())
```

**依赖注入示例**：

```python
# apps/regime/application/use_cases.py
class CalculateRegimeUseCase:
    def __init__(
        self,
        macro_repo: MacroRepositoryProtocol,
        trend_calculator: TrendCalculatorProtocol,  # 注入计算器
    ):
        self.macro_repo = macro_repo
        self.trend_calculator = trend_calculator
```

这样 Domain 层保持纯净（只依赖 Protocol），而高性能计算在 Infrastructure 层用 Pandas 实现。

---

## 5. 📂 项目目录结构

```text
AgomSAAF/
├── manage.py
├── pyproject.toml                # Poetry 依赖管理
├── docker-compose.yml            # 本地开发环境
├── .env.example                  # 环境变量模板（提交到 Git）
├── .env                          # 实际环境变量（不提交）
│
├── core/                         # Django 全局配置
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   └── celery.py
│
├── apps/
│   ├── macro/                    # 宏观数据采集 App
│   │   ├── domain/
│   │   │   ├── entities.py       # MacroIndicator, RegimeSnapshot
│   │   │   └── services.py       # HP滤波、动量计算、模糊权重
│   │   ├── application/
│   │   │   ├── use_cases.py      # SyncMacroDataUseCase
│   │   │   └── tasks.py          # Celery 定时采集任务
│   │   ├── infrastructure/
│   │   │   ├── models.py         # MacroIndicator ORM
│   │   │   ├── repositories.py   # MacroRepository
│   │   │   └── adapters/
│   │   │       ├── tushare_adapter.py
│   │   │       ├── akshare_adapter.py
│   │   │       └── fred_adapter.py
│   │   └── interface/
│   │       ├── views.py
│   │       ├── serializers.py
│   │       └── admin.py
│   │
│   ├── regime/                   # Regime 判定引擎 App
│   │   ├── domain/
│   │   │   ├── entities.py       # RegimeDistribution
│   │   │   ├── rules.py          # 象限判定规则
│   │   │   └── services.py       # 模糊逻辑引擎
│   │   ├── application/
│   │   │   └── use_cases.py      # CalculateRegimeUseCase
│   │   ├── infrastructure/
│   │   │   ├── models.py         # RegimeLog ORM
│   │   │   └── repositories.py
│   │   └── interface/
│   │       └── views.py
│   │
│   ├── policy/                   # 政策事件 App
│   │   ├── domain/
│   │   │   ├── entities.py       # PolicyEvent, PolicyLevel
│   │   │   └── rules.py          # P0-P3 响应规则
│   │   ├── application/
│   │   │   └── use_cases.py      # LogPolicyEventUseCase
│   │   ├── infrastructure/
│   │   │   └── models.py         # PolicyLog ORM
│   │   └── interface/
│   │       └── admin.py          # 人工标注界面
│   │
│   ├── signal/                   # 投资信号 App
│   │   ├── domain/
│   │   │   ├── entities.py       # InvestmentSignal
│   │   │   ├── rules.py          # 准入矩阵、证伪校验
│   │   │   └── validators.py     # 信号完整性验证
│   │   ├── application/
│   │   │   └── use_cases.py      # CreateSignalUseCase, ValidateSignalUseCase
│   │   ├── infrastructure/
│   │   │   └── models.py
│   │   └── interface/
│   │       └── admin.py          # 信号录入界面
│   │
│   ├── backtest/                 # 回测引擎 App
│   │   ├── domain/
│   │   │   ├── entities.py       # BacktestResult, TradeLog
│   │   │   └── services.py       # 回测核心逻辑
│   │   ├── application/
│   │   │   └── use_cases.py      # RunBacktestUseCase
│   │   └── infrastructure/
│   │       ├── models.py
│   │       └── price_repository.py
│   │
│   └── audit/                    # 事后审计 App
│       ├── domain/
│       │   ├── entities.py       # AuditReport, Attribution
│       │   └── services.py       # 归因分析逻辑
│       ├── application/
│       │   └── use_cases.py      # GenerateAuditReportUseCase
│       └── infrastructure/
│           └── models.py
│
├── shared/                       # 跨 App 共享组件
│   ├── domain/
│   │   ├── value_objects.py      # DateRange, Percentage, ZScore
│   │   └── interfaces.py         # Repository 抽象接口、计算器协议
│   ├── infrastructure/
│   │   ├── pandas_mixin.py       # to_dataframe() 通用实现
│   │   ├── calculators.py        # HP滤波、Z-score 等 Pandas 实现
│   │   └── cache.py              # Redis 缓存封装
│   └── config/
│       └── secrets.py            # 统一密钥管理（见下方说明）
│
├── scripts/
│   ├── init_db.py                # 初始化数据库
│   └── seed_historical.py        # 导入历史数据
│
└── tests/
    ├── unit/
    │   ├── test_regime_services.py
    │   └── test_eligibility_rules.py
    ├── integration/
    │   └── test_macro_sync.py
    └── fixtures/
        └── macro_sample.json
```

### 5.2 密钥与敏感配置管理

> ⚠️ **安全警告**：绝不能将 Token、API Key 硬编码在适配器中。

**环境变量模板** (`.env.example`)：

```bash
# Database (初期使用 SQLite，生产环境切换 PostgreSQL)
DATABASE_URL=sqlite:///db.sqlite3
# DATABASE_URL=postgres://user:password@localhost:5432/agomsaaf  # 生产环境

# Redis
REDIS_URL=redis://localhost:6379/0

# Data Source API Keys
TUSHARE_TOKEN=your_tushare_pro_token_here
FRED_API_KEY=your_fred_api_key_here

# Optional: 备用数据源
JUHE_API_KEY=
NETEASE_COOKIE=

# Alerting
SLACK_WEBHOOK_URL=
ALERT_EMAIL=

# Django
SECRET_KEY=your-secret-key-here
DEBUG=True
```

**统一密钥管理** (`shared/config/secrets.py`)：

```python
import os
from dataclasses import dataclass
from functools import lru_cache

@dataclass(frozen=True)
class DataSourceSecrets:
    tushare_token: str
    fred_api_key: str
    juhe_api_key: str | None = None

@dataclass(frozen=True)
class AppSecrets:
    data_sources: DataSourceSecrets
    slack_webhook: str | None = None
    alert_email: str | None = None

@lru_cache(maxsize=1)
def get_secrets() -> AppSecrets:
    """
    从环境变量加载密钥，启动时验证必填项
    """
    tushare_token = os.environ.get("TUSHARE_TOKEN")
    if not tushare_token:
        raise EnvironmentError("TUSHARE_TOKEN is required")
    
    return AppSecrets(
        data_sources=DataSourceSecrets(
            tushare_token=tushare_token,
            fred_api_key=os.environ.get("FRED_API_KEY", ""),
            juhe_api_key=os.environ.get("JUHE_API_KEY"),
        ),
        slack_webhook=os.environ.get("SLACK_WEBHOOK_URL"),
        alert_email=os.environ.get("ALERT_EMAIL"),
    )
```

**适配器中的正确用法**：

```python
# apps/macro/infrastructure/adapters/tushare_adapter.py
from shared.config.secrets import get_secrets

class TushareAdapter:
    def __init__(self, token: str | None = None):
        # 优先使用显式传入的 token（便于测试），否则从环境变量获取
        self._token = token or get_secrets().data_sources.tushare_token
        self.pro = ts.pro_api(self._token)
```

**Django Settings 集成** (`core/settings/base.py`)：

```python
import environ

env = environ.Env()
environ.Env.read_env()  # 读取 .env 文件

# 使用 django-environ 管理配置
DATABASES = {
    'default': env.db('DATABASE_URL')
}

CACHES = {
    'default': env.cache('REDIS_URL')
}
```

**Vibe Coding 提示**：当 AI 生成适配器代码时，如果它把 Token 写死在代码里，立即打回并提醒：
> "Token 必须通过 `get_secrets()` 获取，不能硬编码。请参考 `shared/config/secrets.py`。"

---

## 6. 核心模块详细设计

### 6.1 Domain 层核心 Entities

```python
# apps/macro/domain/entities.py
from dataclasses import dataclass
from datetime import date
from typing import Optional

@dataclass(frozen=True)
class MacroIndicator:
    """宏观指标值对象"""
    code: str
    value: float
    observed_at: date
    published_at: Optional[date] = None
    source: str = "unknown"

@dataclass(frozen=True)
class RegimeSnapshot:
    """Regime 状态快照"""
    growth_momentum_z: float      # 增长动量 Z-score
    inflation_momentum_z: float   # 通胀动量 Z-score
    distribution: dict            # 象限概率分布
    dominant_regime: str          # 主导象限
    confidence: float             # 置信度 (最大概率 - 次大概率)
    observed_at: date
    
    def is_high_confidence(self, threshold: float = 0.3) -> bool:
        return self.confidence >= threshold
```

```python
# apps/signal/domain/entities.py
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional

class SignalStatus(Enum):
    PENDING = "pending"       # 待审核
    APPROVED = "approved"     # 通过准入
    REJECTED = "rejected"     # 被拦截
    INVALIDATED = "invalidated"  # 已证伪
    EXPIRED = "expired"       # 已过期

class Eligibility(Enum):
    PREFERRED = "preferred"
    NEUTRAL = "neutral"
    HOSTILE = "hostile"

@dataclass
class InvestmentSignal:
    """投资信号实体"""
    id: Optional[str]
    asset_code: str
    asset_class: str
    direction: str  # LONG, SHORT, NEUTRAL
    logic_desc: str
    invalidation_logic: str
    invalidation_threshold: Optional[float]
    target_regime: str          # 预期 Regime
    created_at: date
    status: SignalStatus = SignalStatus.PENDING
    rejection_reason: Optional[str] = None
    
    def reject(self, reason: str) -> None:
        self.status = SignalStatus.REJECTED
        self.rejection_reason = reason
```

### 6.2 Domain 层核心 Rules

```python
# apps/signal/domain/rules.py
from typing import Dict
from .entities import Eligibility, InvestmentSignal

# 准入矩阵配置
ELIGIBILITY_MATRIX: Dict[str, Dict[str, Eligibility]] = {
    "a_share_growth": {
        "Recovery": Eligibility.PREFERRED,
        "Overheat": Eligibility.NEUTRAL,
        "Stagflation": Eligibility.HOSTILE,
        "Deflation": Eligibility.NEUTRAL,
    },
    "a_share_value": {
        "Recovery": Eligibility.PREFERRED,
        "Overheat": Eligibility.PREFERRED,
        "Stagflation": Eligibility.NEUTRAL,
        "Deflation": Eligibility.HOSTILE,
    },
    "china_bond": {
        "Recovery": Eligibility.NEUTRAL,
        "Overheat": Eligibility.HOSTILE,
        "Stagflation": Eligibility.NEUTRAL,
        "Deflation": Eligibility.PREFERRED,
    },
    "gold": {
        "Recovery": Eligibility.NEUTRAL,
        "Overheat": Eligibility.PREFERRED,
        "Stagflation": Eligibility.PREFERRED,
        "Deflation": Eligibility.NEUTRAL,
    },
    "commodity": {
        "Recovery": Eligibility.NEUTRAL,
        "Overheat": Eligibility.PREFERRED,
        "Stagflation": Eligibility.HOSTILE,
        "Deflation": Eligibility.HOSTILE,
    },
    "cash": {
        "Recovery": Eligibility.HOSTILE,
        "Overheat": Eligibility.NEUTRAL,
        "Stagflation": Eligibility.PREFERRED,
        "Deflation": Eligibility.NEUTRAL,
    },
}

def check_eligibility(asset_class: str, regime: str) -> Eligibility:
    """检查资产在当前 Regime 下的适配性"""
    if asset_class not in ELIGIBILITY_MATRIX:
        raise ValueError(f"Unknown asset class: {asset_class}")
    return ELIGIBILITY_MATRIX[asset_class].get(regime, Eligibility.NEUTRAL)

def should_reject_signal(signal: InvestmentSignal, current_regime: str) -> tuple[bool, str]:
    """
    判断是否应该拦截信号
    返回: (是否拦截, 拦截原因)
    """
    eligibility = check_eligibility(signal.asset_class, current_regime)
    
    if eligibility == Eligibility.HOSTILE and signal.direction == "LONG":
        return True, f"Asset class '{signal.asset_class}' is HOSTILE in {current_regime} regime"
    
    if eligibility == Eligibility.HOSTILE and signal.direction == "SHORT":
        # 在 Hostile 环境做空是合理的
        return False, ""
    
    return False, ""

def validate_invalidation_logic(signal: InvestmentSignal) -> tuple[bool, str]:
    """验证证伪逻辑是否完整"""
    if not signal.invalidation_logic or len(signal.invalidation_logic.strip()) < 10:
        return False, "Invalidation logic is too short or missing"
    
    # 检查是否包含可量化条件
    quantifiable_keywords = ["跌破", "突破", "低于", "高于", "连续", "超过", "<", ">", "≤", "≥"]
    has_quantifiable = any(kw in signal.invalidation_logic for kw in quantifiable_keywords)
    
    if not has_quantifiable and signal.invalidation_threshold is None:
        return False, "Invalidation logic should include quantifiable conditions or threshold"
    
    return True, ""
```

### 6.3 Infrastructure 层适配器示例

```python
# apps/macro/infrastructure/adapters/tushare_adapter.py
from typing import List, Optional
from datetime import date
import tushare as ts

from ...domain.entities import MacroIndicator

class TushareAdapter:
    """Tushare Pro 数据适配器"""
    
    def __init__(self, token: str):
        self.pro = ts.pro_api(token)
    
    def fetch_shibor(
        self, 
        start_date: date, 
        end_date: date,
        term: str = "1W"  # 1D, 1W, 1M, 3M, 6M, 9M, 1Y
    ) -> List[MacroIndicator]:
        """获取 SHIBOR 利率"""
        df = self.pro.shibor(
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d")
        )
        
        term_map = {"1D": "on", "1W": "1w", "1M": "1m", "3M": "3m"}
        col = term_map.get(term, "1w")
        
        return [
            MacroIndicator(
                code=f"SHIBOR_{term}",
                value=row[col],
                observed_at=date.fromisoformat(row["date"]),
                published_at=date.fromisoformat(row["date"]),  # SHIBOR 当日发布
                source="tushare"
            )
            for _, row in df.iterrows()
        ]
    
    def fetch_index_daily(
        self,
        ts_code: str,  # e.g., "000001.SH" 上证指数
        start_date: date,
        end_date: date
    ) -> List[dict]:
        """获取指数日线"""
        df = self.pro.index_daily(
            ts_code=ts_code,
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d")
        )
        return df.to_dict("records")
```

```python
# apps/macro/infrastructure/adapters/akshare_adapter.py
from typing import List
from datetime import date
import akshare as ak

from ...domain.entities import MacroIndicator

class AKShareAdapter:
    """AKShare 宏观数据适配器"""
    
    # 发布延迟配置（天）
    PUBLICATION_LAGS = {
        "china_pmi": 1,      # 次月1日发布
        "china_cpi": 10,     # 次月10日左右
        "china_ppi": 10,
        "china_gdp": 20,     # 季后20天左右
        "china_m2": 15,
    }
    
    def fetch_china_pmi(self) -> List[MacroIndicator]:
        """获取中国 PMI"""
        df = ak.macro_china_pmi()
        lag = self.PUBLICATION_LAGS["china_pmi"]
        
        return [
            MacroIndicator(
                code="CN_PMI_MANUFACTURING",
                value=row["制造业PMI"],
                observed_at=self._parse_month(row["月份"]),
                published_at=None,  # AKShare 不提供发布时间
                source="akshare"
            )
            for _, row in df.iterrows()
            if row["制造业PMI"] is not None
        ]
    
    def fetch_china_cpi(self) -> List[MacroIndicator]:
        """获取中国 CPI"""
        df = ak.macro_china_cpi()
        return [
            MacroIndicator(
                code="CN_CPI_YOY",
                value=row["同比增长"],
                observed_at=self._parse_month(row["月份"]),
                source="akshare"
            )
            for _, row in df.iterrows()
        ]
    
    def fetch_china_money_supply(self) -> List[MacroIndicator]:
        """获取中国货币供应量"""
        df = ak.macro_china_money_supply()
        results = []
        for _, row in df.iterrows():
            observed = self._parse_month(row["月份"])
            results.append(MacroIndicator(
                code="CN_M2_YOY",
                value=row["M2-同比(%)"],
                observed_at=observed,
                source="akshare"
            ))
            results.append(MacroIndicator(
                code="CN_M1_YOY", 
                value=row["M1-同比(%)"],
                observed_at=observed,
                source="akshare"
            ))
        return results
    
    def _parse_month(self, month_str: str) -> date:
        """解析 '2024年01月' 格式"""
        # 简化处理，实际需要更健壮的解析
        year = int(month_str[:4])
        month = int(month_str[5:7])
        return date(year, month, 1)
```

### 6.4 Application 层 Use Case 示例

```python
# apps/regime/application/use_cases.py
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from ..domain.entities import RegimeSnapshot
from ..domain.services import RegimeCalculator

class MacroRepositoryProtocol(Protocol):
    """宏观数据仓储接口（依赖反转）"""
    def get_growth_series(self, end_date: date, months: int) -> list[float]: ...
    def get_inflation_series(self, end_date: date, months: int) -> list[float]: ...

@dataclass
class CalculateRegimeInput:
    as_of_date: date
    use_pit: bool = True  # 是否使用 Point-in-Time 数据

@dataclass
class CalculateRegimeOutput:
    snapshot: RegimeSnapshot
    data_quality_warnings: list[str]

class CalculateRegimeUseCase:
    """计算当前 Regime 状态"""
    
    def __init__(
        self,
        macro_repo: MacroRepositoryProtocol,
        calculator: RegimeCalculator
    ):
        self.macro_repo = macro_repo
        self.calculator = calculator
    
    def execute(self, input: CalculateRegimeInput) -> CalculateRegimeOutput:
        warnings = []
        
        # 获取数据
        growth_series = self.macro_repo.get_growth_series(
            end_date=input.as_of_date, 
            months=60  # 需要 60 个月计算 Z-score
        )
        inflation_series = self.macro_repo.get_inflation_series(
            end_date=input.as_of_date,
            months=60
        )
        
        # 数据质量检查
        if len(growth_series) < 24:
            warnings.append("Insufficient growth data, results may be unreliable")
        if len(inflation_series) < 24:
            warnings.append("Insufficient inflation data, results may be unreliable")
        
        # 计算 Regime
        snapshot = self.calculator.calculate(
            growth_series=growth_series,
            inflation_series=inflation_series,
            as_of_date=input.as_of_date
        )
        
        return CalculateRegimeOutput(
            snapshot=snapshot,
            data_quality_warnings=warnings
        )
```

---

## 7. 回测框架设计

### 7.1 回测核心逻辑

```python
# apps/backtest/domain/services.py
from dataclasses import dataclass
from datetime import date
from typing import List, Dict

@dataclass
class BacktestConfig:
    start_date: date
    end_date: date
    initial_capital: float
    rebalance_frequency: str  # "monthly", "quarterly"
    use_pit_data: bool
    transaction_cost_bps: float = 10  # 交易成本 (基点)

@dataclass
class BacktestResult:
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    regime_accuracy: float  # Regime 判定准确率
    trade_logs: List[dict]
    regime_transitions: List[dict]
    
    # 归因分析
    return_from_regime_timing: float   # 来自择时的收益
    return_from_asset_selection: float # 来自选资产的收益

class BacktestEngine:
    """回测引擎"""
    
    def run(self, config: BacktestConfig, strategy) -> BacktestResult:
        """
        执行回测
        
        关键逻辑：
        1. 按 rebalance_frequency 遍历时间点
        2. 每个时间点：
           a. 使用 PIT 数据计算 Regime
           b. 应用准入矩阵确定可投资资产
           c. 生成目标持仓
           d. 计算交易成本
           e. 记录持仓和净值
        3. 计算绩效指标
        4. 执行归因分析
        """
        # 实现略
        pass
```

### 7.2 归因分析框架

```python
# apps/audit/domain/services.py
from dataclasses import dataclass
from enum import Enum

class LossSource(Enum):
    REGIME_MISJUDGMENT = "regime_misjudgment"  # Regime 判断错误
    ASSET_SELECTION = "asset_selection"         # 资产选择失误
    EXECUTION = "execution"                     # 执行问题
    BLACK_SWAN = "black_swan"                   # 不可预见事件

@dataclass
class AttributionResult:
    period_start: date
    period_end: date
    total_pnl: float
    
    # 拆解
    regime_timing_pnl: float      # 来自 Regime 择时
    asset_selection_pnl: float    # 来自资产选择
    interaction_pnl: float        # 交互项
    
    # 错误分析
    regime_predicted: str
    regime_actual: str
    loss_source: LossSource
    lesson_learned: str  # 可由 LLM 辅助生成

def analyze_attribution(
    predicted_regime: str,
    actual_regime: str,
    portfolio_return: float,
    benchmark_returns: Dict[str, float]  # 各象限基准收益
) -> AttributionResult:
    """
    归因分析
    
    逻辑：
    1. 如果 predicted == actual 但亏损 → 资产选择问题
    2. 如果 predicted != actual → Regime 判断问题
    3. 计算"如果判断正确"的假设收益，得出择时贡献
    """
    # 实现略
    pass
```

---

## 8. 技术约束与开发规范

### 8.1 代码规范

| 规范项 | 要求 |
|--------|------|
| Python 版本 | ≥ 3.11 |
| 类型标注 | 强制，使用 `mypy --strict` 检查 |
| 代码格式 | `black` + `isort` + `ruff` |
| 测试覆盖率 | Domain 层 ≥ 90%，其他层 ≥ 70% |
| 文档 | 所有 public 函数必须有 docstring |

### 8.2 测试策略

```
tests/
├── unit/           # 单元测试（不依赖外部服务）
│   ├── domain/     # 测试金融逻辑，最重要
│   └── application/
├── integration/    # 集成测试（需要数据库）
└── e2e/           # 端到端测试（需要全部服务）
```

**Domain 层测试示例**：

```python
# tests/unit/domain/test_regime_services.py
import pytest
from apps.regime.domain.services import RegimeCalculator

class TestRegimeCalculator:
    
    def test_recovery_regime_detection(self):
        """测试复苏象限识别"""
        calc = RegimeCalculator()
        
        # 模拟增长加速、通胀减速的数据
        growth_series = [100, 101, 103, 106, 110]  # 加速增长
        inflation_series = [5.0, 4.8, 4.5, 4.3, 4.0]  # 减速通胀
        
        result = calc.calculate(growth_series, inflation_series)
        
        assert result.dominant_regime == "Recovery"
        assert result.distribution["Recovery"] > 0.5
    
    def test_stagflation_regime_detection(self):
        """测试滞胀象限识别"""
        calc = RegimeCalculator()
        
        # 模拟增长减速、通胀加速
        growth_series = [110, 109, 107, 104, 100]
        inflation_series = [2.0, 2.5, 3.2, 4.0, 5.0]
        
        result = calc.calculate(growth_series, inflation_series)
        
        assert result.dominant_regime == "Stagflation"
```

### 8.3 环境配置

> **开发流程**：本地无 Docker 开发 → 验证通过 → 打包 Docker 部署

#### 阶段一：本地开发（无 Docker，推荐）

```bash
# 1. 克隆项目
git clone <repo_url>
cd AgomSAAF

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 TUSHARE_TOKEN 等

# 5. 初始化数据库（SQLite）
python manage.py migrate

# 6. 创建管理员账户
python manage.py createsuperuser

# 7. 启动开发服务器
python manage.py runserver

# 8. (可选) 另开终端启动 Celery Worker
# 注意：本地开发可以先不启动 Celery，手动触发任务测试
celery -A core worker -l info
```

**本地开发目录结构**：

```
AgomSAAF/
├── venv/                 # 虚拟环境（不提交）
├── db.sqlite3            # SQLite 数据库（不提交）
├── .env                  # 环境变量（不提交）
├── .env.example          # 环境变量模板（提交）
└── ...
```

**`.gitignore` 配置**：

```gitignore
# 环境
venv/
.env
*.sqlite3

# Python
__pycache__/
*.pyc
.mypy_cache/

# IDE
.vscode/
.idea/

# 其他
*.log
.DS_Store
```

#### 阶段二：打包 Docker 部署

当本地开发验证通过后，打包成 Docker 镜像部署：

**Dockerfile**：

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 收集静态文件（生产环境）
RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "core.wsgi:application", "--bind", "0.0.0.0:8000"]
```

**docker-compose.yml**（生产部署）：

```yaml
version: '3.8'
services:
  web:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data          # 数据持久化目录
      - sqlite_data:/app/db       # SQLite 持久化（初期）
    environment:
      - DATABASE_URL=sqlite:////app/db/db.sqlite3
      - REDIS_URL=redis://redis:6379/0
      - TUSHARE_TOKEN=${TUSHARE_TOKEN}
      - DEBUG=False
      - ALLOWED_HOSTS=${ALLOWED_HOSTS:-localhost}
    depends_on:
      - redis
    restart: unless-stopped
  
  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    restart: unless-stopped
  
  celery:
    build: .
    command: celery -A core worker -l info
    volumes:
      - ./data:/app/data
      - sqlite_data:/app/db
    environment:
      - DATABASE_URL=sqlite:////app/db/db.sqlite3
      - REDIS_URL=redis://redis:6379/0
      - TUSHARE_TOKEN=${TUSHARE_TOKEN}
    depends_on:
      - redis
    restart: unless-stopped
  
  celery-beat:
    build: .
    command: celery -A core beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    volumes:
      - ./data:/app/data
      - sqlite_data:/app/db
    environment:
      - DATABASE_URL=sqlite:////app/db/db.sqlite3
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
    restart: unless-stopped

volumes:
  sqlite_data:
  redis_data:
```

**部署命令**：

```bash
# 1. 构建镜像
docker-compose build

# 2. 首次启动前迁移数据库
docker-compose run --rm web python manage.py migrate

# 3. 启动所有服务
docker-compose up -d

# 4. 查看日志
docker-compose logs -f web

# 5. 进入容器调试
docker-compose exec web bash
```

#### 阶段三：生产环境升级（可选）

当数据量增大或并发需求增加时，切换到 PostgreSQL：

```yaml
# docker-compose.prod.yml - PostgreSQL 版本
version: '3.8'
services:
  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: agomsaaf
      POSTGRES_USER: agomsaaf
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped
  
  web:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgres://agomsaaf:${POSTGRES_PASSWORD}@db:5432/agomsaaf
      - REDIS_URL=redis://redis:6379/0
      - DEBUG=False
    depends_on:
      - db
      - redis
    restart: unless-stopped
  
  # ... 其他服务同上

volumes:
  postgres_data:
  redis_data:
```

**SQLite → PostgreSQL 迁移步骤**：

```bash
# 1. 导出 SQLite 数据
docker-compose exec web python manage.py dumpdata --natural-foreign --natural-primary > backup.json

# 2. 切换到 PostgreSQL 配置
docker-compose -f docker-compose.prod.yml up -d db
docker-compose -f docker-compose.prod.yml run --rm web python manage.py migrate

# 3. 导入数据
docker-compose -f docker-compose.prod.yml run --rm web python manage.py loaddata backup.json

# 4. 启动完整服务
docker-compose -f docker-compose.prod.yml up -d
```

---

## 9. 实施路线图 (Realistic Roadmap)

> **开发模式**：Phase 1-3 全程本地开发（无 Docker），Phase 4 打包 Docker 部署

### Phase 1: 基础搭建 (Week 1-2) 📍 本地开发

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| 项目初始化 | Django 项目骨架 + SQLite | `python manage.py runserver` 成功 |
| 开发环境 | venv + .env 配置 | 本地环境一键启动 |
| Domain 层 Entities | 所有核心数据类 | mypy 检查通过 |
| Tushare 适配器 | 可获取 SHIBOR、指数数据 | 单元测试通过 |
| AKShare 适配器 | 可获取 PMI、CPI、M2 | 单元测试通过 |

### Phase 2: 核心引擎 (Week 3-4) 📍 本地开发

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| Regime 计算服务 | HP/Kalman 滤波 + 动量计算 | 历史数据回归测试 |
| 模糊权重引擎 | 四象限概率输出 | 边界条件测试通过 |
| 准入规则引擎 | 准入矩阵 + 拦截逻辑 | 规则覆盖测试 |
| 数据库模型 | 所有 ORM Model | migrate 成功 |

### Phase 3: 回测验证 (Week 5-6) 📍 本地开发

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| 简易回测框架 | 月度再平衡回测 | 可跑通 2015-2024 |
| Regime 准确率验证 | 历史 Regime vs 实际市场 | 生成准确率报告 |
| 策略初步验证 | 准入过滤 vs 无过滤对比 | 验证过滤有效性 |

### Phase 4: 产品化与部署 (Week 7-8) 🐳 Docker 打包

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| Dockerfile | 生产镜像 | `docker build` 成功 |
| docker-compose | 完整服务编排 | `docker-compose up` 一键启动 |
| Admin 后台 | Policy 标注、Signal 录入 | 可完成完整工作流 |
| API 接口 | Regime 查询、Signal 提交 | OpenAPI 文档完整 |
| Celery 任务 | 每日数据同步 | 定时任务稳定运行 |
| 基础告警 | P2/P3 邮件通知 | 触发测试通过 |

### Phase 5: 持续迭代 (Week 9+)

- 🔄 **数据库升级**：SQLite → PostgreSQL（当并发/数据量需求增加时）
- 🌍 接入更多数据源（全球市场）
- 📊 完善归因分析模块
- 🤖 LLM 辅助投资逻辑审查（可选）
- 📈 前端可视化看板

---

## 10. 风险与缓解措施

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| **HP滤波后视偏差** | 回测结果虚高，实盘失效 | 强制使用扩张窗口，每个时间点重新计算趋势 |
| Tushare 限流 | 数据采集中断 | 本地缓存 + 增量更新 + 付费升级积分 |
| AKShare 接口变动 | 采集失败 | Failover 适配器 + 备用爬虫 + 手动 CSV 导入兜底 |
| Regime 判定滞后 | 错过转折点 | 加入领先指标（PMI）+ 高频监控 |
| 四层架构开发慢 | 进度延迟 | 先完成 Domain + Infra，Application/Interface 简化处理 |
| 历史数据前视偏差 | 回测失真 | 明确标注 + 使用模拟 PIT + 保守解读结果 |
| Token 泄露 | 安全事故 | 统一 secrets 管理 + 环境变量 + .gitignore |
| Domain 层性能瓶颈 | 计算超时 | 计算协议模式，Pandas 实现留在 Infra 层 |

---

## 11. 系统架构全景：模块关系与数据流

> **本章新增于 V3.5**：基于实际实现情况，理顺12个核心模块的关系、职责与数据流向，展现完整的投顾闭环。

### 11.1 十二个核心模块概览

| 模块 | 完成度 | 核心职责 | 关键实体 | 代码位置 |
|------|--------|---------|---------|---------|
| **macro** | 90% | 宏观数据采集与管理 | MacroIndicator, DataSourceConfig | apps/macro/ |
| **regime** | 85% | Regime象限判定引擎 | RegimeSnapshot, KalmanFilterParams | apps/regime/ |
| **policy** | 80% | 政策事件管理与RSS解析 | PolicyEvent, RSSSourceConfig | apps/policy/ |
| **signal** | 80% | 投资信号验证与准入控制 | InvestmentSignal, ValidationResult | apps/signal/ |
| **backtest** | 85% | 回测引擎与归因分析 | BacktestConfig, AttributionResult | apps/backtest/ |
| **filter** | 70% | HP/Kalman滤波器 | HPFilterParams, LocalLinearTrendFilter | apps/filter/ |
| **audit** | 60% | 事后审计与损失分析 | LossSource, ImprovementSuggestion | apps/audit/ |
| **account** | 75% | 用户账户与投资组合管理 | AssetMetadata, Position, Portfolio | apps/account/ |
| **ai_provider** | 70% | AI服务商管理与failover | AIProviderConfig, AIUsageRecord | apps/ai_provider/ |
| **prompt** | 50% | AI提示词模板管理 | PromptTemplate, PromptExecution | apps/prompt/ |
| **dashboard** | 50% | 可视化仪表盘 | RegimeChart, SignalTimeline | apps/dashboard/ |
| **shared** | 70% | 跨应用共享基础设施 | RiskParameterConfig, AlertService | shared/ |

说明：`sdk/agomsaaf` 与 `sdk/agomsaaf_mcp` 为系统对外接入层，独立于 `apps/` 业务模块统计口径。

### 11.2 模块职责与分层定位

#### 数据采集层
- **macro**: 宏观数据的唯一入口，支持多源（Tushare/AKShare）及Failover机制

#### 核心引擎层
- **regime**: Regime象限判定，输出四象限分布及置信度
- **filter**: 数据滤波服务，支持HP（扩张窗口）和Kalman滤波

#### 决策控制层
- **policy**: 政策档位（P0-P3）判定，具有信号否决权
- **signal**: 投资信号生成与多层验证（证伪逻辑、准入矩阵、政策档位）

#### 执行验证层
- **account**: 用户账户、持仓管理、风险偏好配置
- **backtest**: Point-in-Time回测引擎，模拟真实交易环境

#### 分析改进层
- **audit**: 事后审计，损失来源识别与改进建议

#### 支撑服务层
- **ai_provider**: AI服务统一管理
- **prompt**: 提示词模板库
- **dashboard**: 数据可视化

#### 基础设施层
- **shared**: 跨模块共享（配置、告警、规则引擎）

### 11.3 模块间依赖关系图

```
┌─────────────────────────────────────────────────────────────────┐
│                        数据采集层                                 │
│                                                                   │
│  ┌──────────┐        ┌──────────┐                               │
│  │  MACRO   │◄───────│  FILTER  │                               │
│  │ 宏观数据  │        │   滤波    │                               │
│  └────┬─────┘        └──────────┘                               │
└───────┼──────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                        核心引擎层                                 │
│                                                                   │
│  ┌──────────┐                                                    │
│  │  REGIME  │                                                    │
│  │ Regime判定│                                                    │
│  └────┬─────┘                                                    │
└───────┼──────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                        决策控制层                                 │
│                                                                   │
│  ┌──────────┐        ┌──────────┐                               │
│  │  POLICY  │───────►│  SIGNAL  │                               │
│  │ 政策管理  │  veto  │ 信号管理  │                               │
│  └────┬─────┘        └────┬─────┘                               │
│       │                   │                                      │
│       │    (AI Provider)  │                                      │
│       │    ┌──────────┐   │                                      │
│       └────│AI_PROVIDER│◄──┘                                     │
│            │  PROMPT   │                                         │
│            └──────────┘                                          │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                        执行验证层                                 │
│                                                                   │
│  ┌──────────┐        ┌──────────┐                               │
│  │ ACCOUNT  │◄───────│ BACKTEST │                               │
│  │ 账户管理  │        │ 回测引擎  │                               │
│  └────┬─────┘        └──────────┘                               │
└───────┼──────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                        分析改进层                                 │
│                                                                   │
│  ┌──────────┐                                                    │
│  │  AUDIT   │                                                    │
│  │ 事后审计  │                                                    │
│  └──────────┘                                                    │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                        可视化层                                   │
│                                                                   │
│  ┌──────────┐                                                    │
│  │DASHBOARD │                                                    │
│  │  仪表盘   │                                                    │
│  └──────────┘                                                    │
└─────────────────────────────────────────────────────────────────┘

横向支撑：SHARED（配置、告警、规则引擎、映射器）
```

### 11.4 完整数据流向图

```
[第1阶段：宏观数据采集]
    ↓
MACRO: Tushare/AKShare 多源数据抓取
    ↓ (Celery定时任务/手动触发)
MacroIndicator 数据库 (历史序列数据)
    ↓ (Failover机制 + 数据一致性校验，容差1%)

[第2阶段：数据滤波与趋势提取]
    ↓
FILTER: HP滤波（扩张窗口，避免后视偏差）/ Kalman滤波
    ↓ (趋势项提取，过滤噪声)
Trend Series (PMI趋势、CPI趋势等)

[第3阶段：Regime象限判定]
    ↓
REGIME: 动量计算 → Z-score → Sigmoid → 四象限分布
    ↓ (输出：Regime + 置信度 + 警告)
RegimeLog 数据库
    ↓ (置信度驱动的风控强度)
    │
    ├─ 置信度 ≥ 0.8: 高置信度，正常流程
    ├─ 0.3 ≤ 置信度 < 0.8: 中置信度，谨慎模式（仅PREFERRED资产）
    └─ 置信度 < 0.3: 低置信度，降级方案（使用上次Regime × 0.8置信度）

[第4阶段：政策事件监控] (并行流程)
    ↓
POLICY: RSS抓取 → AI分类（GPT/DeepSeek/Qwen）→ P0-P3档位判定
    ↓ (AI置信度 > 0.8 自动通过，否则人工审核)
PolicyLog 数据库
    ↓ (档位变化触发Django Signal)
    │
    ├─ P0 (常态): 无限制
    ├─ P1 (预警): 现金权重+5-10%
    ├─ P2 (干预): 暂停信号48小时，现金+20%
    └─ P3 (危机): 全仓转现金，人工接管

[第5阶段：投资信号生成与验证]
    ↓
SIGNAL: 信号输入 → 七层过滤机制
    ↓
    第1层：证伪逻辑完整性检查（validate_invalidation_logic）
    第2层：Regime准入矩阵过滤（check_eligibility）
           - PREFERRED（优选）→ 100分
           - NEUTRAL（中性）→ 50分
           - HOSTILE（敌对）→ 0分，直接拒绝
    第3层：置信度过滤（confidence < 0.3 拒绝NEUTRAL资产）
    第4层：政策档位控制（P2/P3档位否决）
    第5层：仓位限额计算（calculate_position_size）
           - 基础限额5%/10%/20% × 资产调整 × 地区调整 × 跨境调整
    第6层：组合风险评估（assess_portfolio_risk）
           - 集中度、分散度、总敞口检查
    第7层：资金可用性检查
    ↓ (结果：APPROVED / REJECTED + 详细原因)
InvestmentSignalModel 数据库
    │
    ├─ APPROVED → 执行流程
    ├─ REJECTED → 记录拒绝原因
    └─ 定期检查证伪条件 → INVALIDATED（证伪触发）

[第6阶段：账户与持仓管理]
    ↓
ACCOUNT: 账户管理 → 风险偏好匹配 → 仓位计算 → 持仓管理
    ↓
PositionModel 数据库 (持仓状态、盈亏、开平仓时间)
TransactionModel 数据库 (交易记录、手续费)
    ↓ (Regime变化 / 政策变化触发)
    │
    ├─ Regime匹配度分析（calculate_regime_match_score）
    ├─ HOSTILE资产平仓建议
    └─ 组合再平衡

[第7阶段：回测验证]
    ↓
BACKTEST: Point-in-Time回测引擎
    ↓ (考虑发布延迟：PMI+35天，GDP+60天)
    ↓ (BacktestEngine + PITDataProcessor)
BacktestResult 数据库
    ↓
    - 权益曲线（equity_curve）
    - 最大回撤（max_drawdown）
    - 夏普比率（sharpe_ratio）
    - 再平衡记录（rebalance_results）
    - 交易成本（transaction_costs）

[第8阶段：事后审计与改进]
    ↓
AUDIT: 归因分析 → 损失来源识别 → 改进建议生成
    ↓ (损失分解，AttributionAnalyzer)
    │
    ├─ REGIME_TIMING_ERROR (Regime判断错误)
    ├─ ASSET_SELECTION_ERROR (资产选择错误)
    ├─ POLICY_INTERVENTION (政策干预)
    ├─ MARKET_VOLATILITY (市场波动)
    └─ TRANSACTION_COST (交易成本)
    ↓
改进建议：
    - Regime错误 → 提高置信度阈值
    - 资产选择 → 优化准入矩阵
    - 市场波动 → 增加止损、降低杠杆

[第9阶段：可视化展示]
    ↓
DASHBOARD:
    - Regime变化曲线（时间序列图）
    - 政策事件时间线（事件标记）
    - 投资信号历史（APPROVED/REJECTED/INVALIDATED）
    - 投资组合表现（收益率、回撤曲线）
    - 风险指标监控（实时集中度、敞口、Regime匹配度）
```

### 11.5 闭环投顾流程（宏观→微观→执行→风控→复盘）

**完整闭环的七个阶段**：

```
┌─────────────────────────────────────────────────────────────────┐
│ 阶段1：宏观环境感知                                                │
│ MACRO (数据采集) → FILTER (趋势提取) → REGIME (象限判定)         │
│ 输出：当前宏观环境 + 置信度                                        │
│ 示例：Recovery (复苏), confidence=0.75                           │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ 阶段2：政策风险过滤                                                │
│ POLICY (政策事件监控) → AI分类 → P0-P3档位判定                   │
│ 输出：当前政策档位 + 风险等级 + 市场行动建议                        │
│ 示例：P1 (预警), 建议提升现金5-10%                                │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ 阶段3：投资信号生成（微观决策）                                     │
│ SIGNAL (信号输入) → 七层过滤 → APPROVED/REJECTED                │
│ 输出：通过验证的投资信号 + 拒绝原因（如有）                         │
│ 示例：沪深300 LONG信号通过，理由：复苏期+PREFERRED资产             │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ 阶段4：投资执行与风控                                              │
│ ACCOUNT (账户管理) → 风险偏好匹配 → 仓位计算 → 持仓管理           │
│ 风控监控：                                                        │
│   - 实时回撤监控（max_drawdown跟踪）                              │
│   - 集中度控制（前三大持仓占比）                                   │
│   - Regime匹配度分析（calculate_regime_match_score）             │
│   - HOSTILE资产预警                                              │
│ 输出：持仓建立、风险指标实时更新                                    │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ 阶段5：回测验证                                                    │
│ BACKTEST (Point-in-Time回测) → 性能评估 → 风险指标               │
│ 输出：收益曲线、最大回撤、夏普比率、交易明细                         │
│ 示例：年化收益15%，最大回撤-8%，夏普比率1.2                        │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ 阶段6：事后复盘                                                    │
│ AUDIT (归因分析) → 损失来源识别 → 改进建议                        │
│ 输出：策略优化方向 + 参数调整建议                                   │
│ 示例：60%损失来自Regime判断错误 → 建议提高置信度阈值至0.4          │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ 阶段7：循环迭代                                                    │
│ 改进建议 → 更新准入矩阵 / 调整置信度阈值 / 优化滤波参数            │
│ → 回到阶段1                                                       │
│                                                                   │
│ 可视化贯穿全程：DASHBOARD 提供实时监控和历史回顾                    │
└─────────────────────────────────────────────────────────────────┘
```

**关键特性**：
1. **双重过滤机制**: Regime象限过滤 + Policy档位过滤
2. **置信度驱动**: Regime置信度直接影响风控强度
3. **七层信号验证**: 从证伪逻辑到资金可用性的完整防线
4. **Point-in-Time回测**: 考虑数据发布延迟，避免前视偏差
5. **精确归因分析**: 损失来源分解到Regime判断、资产选择、政策干预等
6. **持续改进循环**: 审计结果直接反馈到参数优化

---

## 12. 风险管理体系

> **本章新增于 V3.5**：详细描述AgomSAAF的多层级风控机制，包括14项已实现功能和待增强的风控能力。

### 12.1 风控框架总览

AgomSAAF 的风险管理采用**多层级、全流程**的防御体系：

**设计理念**：
1. **层层过滤**：投资信号经过7层验证，确保每个环节都有风控把关
2. **置信度驱动**：Regime置信度直接影响风控强度（低置信度→高风控）
3. **政策联动**：政策档位（P0-P3）具有最高优先级，可否决所有信号
4. **实时监控**：持仓状态、回撤、集中度实时计算并预警
5. **事后归因**：损失来源精确分解，形成改进闭环

**风控覆盖范围**：
- ✅ 准入控制：Regime准入矩阵 + 政策档位过滤
- ✅ 仓位管理：风险偏好匹配 + 多维度调整因子
- ✅ 集中度控制：前三大持仓占比 + 地理分散度（HHI）
- ✅ 回撤监控：最大回撤计算 + 实时跟踪
- ✅ 平仓机制：HOSTILE资产预警 + Regime变化触发
- ✅ 证伪监控：信号证伪逻辑定期检查
- ✅ 事后审计：损失来源识别 + 改进建议生成

### 12.2 七层风控过滤机制

投资信号必须通过以下七道防线：

```
投资信号输入 (用户提交或AI生成)
    ↓
┌─────────────────────────────────────────────────────────────┐
│ 第1层：证伪逻辑完整性检查                                      │
│ - 验证证伪逻辑长度（≥10字符）                                 │
│ - 检查可量化关键词（跌破、突破、<、>、>=等）                  │
│ - 验证明确证伪模式                                           │
│ - 避免模糊表述（"可能"、"大概"等）                           │
│ → 实现：apps/signal/domain/rules.py:validate_invalidation_logic │
│ → 示例：❌ "大盘下跌时"（模糊）                               │
│         ✅ "PMI跌破50且连续2月低于前值"（明确、可量化）        │
└─────────────────────────────────────────────────────────────┘
    ↓ PASS
┌─────────────────────────────────────────────────────────────┐
│ 第2层：Regime准入矩阵过滤                                      │
│ - 检查资产在当前Regime下的适配度                              │
│ - PREFERRED（优选）：100分，优先配置                          │
│ - NEUTRAL（中性）：50分，适度配置                             │
│ - HOSTILE（敌对）：0分，直接拒绝                              │
│ → 实现：apps/signal/domain/rules.py:check_eligibility         │
│ → 配置：DEFAULT_ELIGIBILITY_MATRIX                           │
│ → 示例：Recovery环境下，成长股=PREFERRED，黄金=NEUTRAL        │
└─────────────────────────────────────────────────────────────┘
    ↓ PASS (非HOSTILE)
┌─────────────────────────────────────────────────────────────┐
│ 第3层：置信度过滤                                             │
│ - confidence ≥ 0.8: PREFERRED + NEUTRAL 都允许               │
│ - 0.3 ≤ confidence < 0.8: 仅 PREFERRED 允许                 │
│ - confidence < 0.3: 拒绝所有新信号，现有仓位转防御             │
│ → 实现：apps/signal/domain/rules.py:should_reject_signal     │
│ → 示例：置信度0.65（中）→ 仅允许PREFERRED资产                 │
└─────────────────────────────────────────────────────────────┘
    ↓ PASS
┌─────────────────────────────────────────────────────────────┐
│ 第4层：政策档位控制（最高优先级）                              │
│ - P0 (常态): 无限制                                          │
│ - P1 (预警): 提升现金权重5-10%                               │
│ - P2 (干预): 暂停信号24-48小时，现金+20%                     │
│ - P3 (危机): 拒绝所有信号，全仓转现金，人工接管                │
│ → 实现：apps/policy/domain/rules.py:get_policy_response      │
│ → 示例：档位升至P2 → 所有信号暂停48小时                       │
└─────────────────────────────────────────────────────────────┘
    ↓ PASS (P0/P1)
┌─────────────────────────────────────────────────────────────┐
│ 第5层：仓位限额计算                                           │
│ - 基础限额（风险偏好）：                                      │
│   - CONSERVATIVE（保守）: 单资产最大5%                        │
│   - MODERATE（稳健）: 单资产最大10%                           │
│   - AGGRESSIVE（激进）: 单资产最大20%                         │
│ - 资产类别调整：                                             │
│   - 衍生品：0.3x，商品：0.8x，债券：1.2x                      │
│ - 地区调整：                                                 │
│   - 新兴市场：0.7x，发达市场：1.0x                            │
│ - 跨境调整：                                                 │
│   - 直接境外：0.6x，QDII：0.8x                               │
│ → 实现：apps/account/domain/services.py:calculate_position_size │
│ → 示例：稳健型投资者，A股成长股 = 10% × 1.0 × 1.0 × 1.0 = 10% │
└─────────────────────────────────────────────────────────────┘
    ↓ PASS (仓位符合限额)
┌─────────────────────────────────────────────────────────────┐
│ 第6层：组合风险评估                                           │
│ - 集中度检查：                                               │
│   - 前三大持仓占比 > 70%: 高风险，拒绝                        │
│   - 前三大持仓占比 > 50%: 中风险，警告                        │
│ - 地理分散度（HHI指数）：                                     │
│   - HHI > 0.5: 集中度过高                                    │
│ - 总敞口：                                                   │
│   - 投资市值 / 账户资金 > 95%: 高风险                         │
│ → 实现：apps/account/domain/services.py:assess_portfolio_risk │
│ → 示例：前三大持仓65% → 中风险警告，但允许通过                 │
└─────────────────────────────────────────────────────────────┘
    ↓ PASS (组合风险可控)
┌─────────────────────────────────────────────────────────────┐
│ 第7层：资金可用性检查                                         │
│ - 计算所需资金 = 目标仓位 × 当前价格                          │
│ - 检查可用现金是否充足                                        │
│ - 考虑已有持仓占用资金                                        │
│ → 实现：apps/account/domain/services.py                       │
│ → 示例：需要10万元，可用现金12万 → 通过                       │
└─────────────────────────────────────────────────────────────┘
    ↓ PASS
┌─────────────────────────────────────────────────────────────┐
│ 最终结果：APPROVED / REJECTED + 详细原因                      │
│ - APPROVED → 进入执行流程                                    │
│ - REJECTED → 记录拒绝原因，通知用户                           │
└─────────────────────────────────────────────────────────────┘
```

### 12.3 已实现的14项风控功能

#### 12.3.1 准入控制

**1. Regime准入矩阵**
- **位置**: `apps/signal/domain/rules.py:12-50`
- **功能**: 定义每类资产在不同Regime下的适配度
- **配置表**: `RegimeEligibilityConfigModel`（支持后台动态配置）
- **准入规则示例**:
  ```python
  "a_share_growth": {
      "Recovery": "preferred",     # 复苏期优选成长股
      "Overheat": "neutral",
      "Stagflation": "hostile",    # 滞胀期敌对
      "Deflation": "neutral",
  }
  ```

**2. 证伪逻辑验证**
- **位置**: `apps/signal/domain/rules.py:84-181`
- **功能**: 强制要求每个投资信号包含可量化的证伪条件
- **验证规则**:
  - 长度 ≥ 10字符
  - 包含可量化关键词（跌破、突破、<、>、>=等）
  - 避免模糊表述（"可能"、"大概"等）

**3. 政策档位响应**
- **位置**: `apps/policy/domain/rules.py:15-171`
- **功能**: P0-P3四档位市场行动规则
- **响应矩阵**:
  | 档位 | 市场行动 | 现金调整 | 信号处理 | 人工审批 |
  |------|---------|---------|---------|---------|
  | P0 | 正常运行 | 0% | 正常 | 否 |
  | P1 | 提升现金 | +5-10% | 正常 | 否 |
  | P2 | 暂停信号 | +20% | 暂停24-48h | 是 |
  | P3 | 全仓转现金 | 100% | 人工接管 | 是 |

#### 12.3.2 仓位管理

**4. 仓位限额计算**
- **位置**: `apps/account/domain/services.py:99-182`
- **计算公式**:
  ```
  最终仓位 = 基础限额 × 资产调整因子 × 地区调整因子 × 跨境调整因子
  ```

**5. 集中度管理**
- **位置**: `apps/account/domain/services.py:358-415`
- **监控指标**:
  - 集中度比率（前三大持仓占比）
  - 地理分散度（HHI指数）
  - 总敞口（投资市值/账户资金）

**6. 账户风险偏好配置**
- **位置**: `apps/account/infrastructure/models.py:AccountProfileModel`
- **级别**: CONSERVATIVE / MODERATE / AGGRESSIVE

#### 12.3.3 实时监控

**7. 回撤监控**
- **位置**: `apps/backtest/domain/services.py:389-404`
- **功能**: 跟踪权益曲线，计算最大回撤

**8. Regime匹配度监控**
- **位置**: `apps/account/domain/services.py:184-266`
- **功能**: 计算持仓与当前Regime的匹配度

**9. 置信度驱动过滤**
- **位置**: 多个模块（regime, signal, backtest）
- **功能**: 根据Regime置信度动态调整风控强度

**10. 信号证伪监控**
- **位置**: `apps/signal/application/use_cases.py:CheckSignalInvalidationUseCase`
- **功能**: 定期检查信号证伪条件是否触发

#### 12.3.4 平仓与预警

**11. 平仓机制**
- **位置**: `apps/account/infrastructure/models.py:PositionModel`
- **触发条件**: 资产转HOSTILE、信号证伪、政策P3、匹配度过低

**12. 多层预警机制**
- **位置**: `shared/infrastructure/alert_service.py`
- **预警类型**: Regime低置信度、政策预警、集中度预警、回撤预警

#### 12.3.5 事后分析

**13. 回测归因分析**
- **位置**: `apps/audit/domain/services.py`
- **损失类型**: REGIME_TIMING_ERROR, ASSET_SELECTION_ERROR, POLICY_INTERVENTION, MARKET_VOLATILITY, TRANSACTION_COST

**14. 完整数据模型**
- **配置表**: RiskParameterConfigModel, RegimeEligibilityConfigModel, InvestmentRuleModel
- **功能**: 支持动态配置风控参数，无需修改代码

### 12.4 待增强的风控功能

**P0（高优先级）**:
1. 动态止损/止盈（移动止损、时间止损）
2. 波动率目标控制（年化波动率15%目标）
3. 交易成本实盘集成

**P1（中优先级）**:
4. 多维分类限额展开（投资风格、行业、币种）
5. 动态对冲策略执行（P2/P3档位自动对冲）
6. 压力测试（历史极端情景、VaR计算）

**P2（低优先级）**:
7. 机器学习优化（置信度阈值、准入矩阵权重）
8. 多账户风险聚合

---

## 附录 A: 关键指标代码清单

| 指标名称 | 代码 | 频率 | 数据源 | 发布延迟 |
|----------|------|------|--------|----------|
| 中国制造业 PMI | CN_PMI_MANUFACTURING | 月 | AKShare | 1天 |
| 中国 CPI 同比 | CN_CPI_YOY | 月 | AKShare | 10天 |
| 中国 PPI 同比 | CN_PPI_YOY | 月 | AKShare | 10天 |
| 中国 M2 同比 | CN_M2_YOY | 月 | AKShare | 15天 |
| SHIBOR 1周 | SHIBOR_1W | 日 | Tushare | 0天 |
| 上证指数 | 000001.SH | 日 | Tushare | 0天 |
| 美国 GDP | US_GDP | 季 | FRED | 30天 |
| 美联储基准利率 | US_FEDFUNDS | 日 | FRED | 0天 |

---

## 附录 B: Vibe Coding 提示词模板

当使用 AI 辅助编码时，可使用以下提示词模板：

```
你是一个 AgomSAAF 项目的开发者。请严格遵守以下约束：

1. 四层架构：Domain / Application / Infrastructure / Interface
2. Domain 层禁止导入 django、pandas、requests 等外部库
3. 所有金融逻辑必须基于 domain/entities.py 中定义的数据类
4. 使用 dataclass(frozen=True) 定义值对象
5. Repository 使用 Protocol 定义接口，在 Infrastructure 层实现

当前任务：{具体任务描述}

请参考项目结构：
{粘贴目录结构}

请先说明你的实现思路，然后给出代码。
```

---

**文档版本**: V3.0  
**最后更新**: 2026-02-26  
**维护者**: AgomSAAF Team
