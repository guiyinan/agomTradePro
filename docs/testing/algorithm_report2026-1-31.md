# AgomSAAF 系统算法评估报告

> 生成时间: 2026-01-31
> 分析范围: AgomSAAF 项目核心算法实现
> 架构版本: 四层架构规范 V1.0

---

## 1. 项目概述

AgomSAAF (Agom Strategic Asset Allocation Framework) 是一个宏观环境准入系统，通过 Regime（增长/通胀象限）和 Policy（政策档位）过滤，确保投资者不在错误的宏观环境中下注。

### 核心设计原则

1. **严格四层架构**: Domain → Application → Infrastructure → Interface
2. **Domain 层纯函数**: 只使用 Python 标准库，无外部依赖
3. **金融逻辑隔离**: 所有业务规则集中在 Domain 层
4. **依赖注入**: Application 层通过接口使用 Domain 层服务

---

## 2. Regime 判定算法

### 2.1 文件位置

| 层级 | 文件路径 |
|------|----------|
| Domain | `apps/regime/domain/services.py` |
| Application | `apps/regime/application/use_cases.py` |
| Entities | `apps/regime/domain/entities.py` |

### 2.2 算法流程

```
原始数据 → 动量计算 → Z-score标准化 → Sigmoid转换 → 四象限分布
```

#### 步骤 1: 动量计算

增长指标（PMI）使用**相对动量**：
```python
momentum = (current_value - past_value) / abs(past_value)
```

通胀指标（CPI）使用**绝对差值动量**：
```python
momentum = current_value - past_value  # 百分点差值
```

#### 步骤 2: Z-score 标准化

```python
z_score = (value - rolling_mean) / rolling_std
```

#### 步骤 3: Sigmoid 概率转换

```python
p_up = 1 / (1 + exp(-k * z_score))  # k=2.0
```

#### 步骤 4: 四象限分布计算

```python
P(复苏)    = P(增长↑) × P(通胀↓)
P(过热)    = P(增长↑) × P(通胀↑)
P(滞胀)    = P(增长↓) × P(通胀↑)
P(通缩)    = P(增长↓) × P(通胀↓)
```

### 2.3 核心参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| momentum_period | 3 | 动量计算周期（月） |
| zscore_window | 24 | Z-score 滚动窗口 |
| zscore_min_periods | 12 | Z-score 最小计算周期 |
| sigmoid_k | 2.0 | Sigmoid 斜率参数 |
| use_absolute_inflation_momentum | True | 通胀使用绝对动量 |

### 2.4 输出结构

```python
@dataclass(frozen=True)
class RegimeSnapshot:
    growth_momentum_z: float           # 增长动量 Z-score
    inflation_momentum_z: float        # 通胀动量 Z-score
    distribution: Dict[str, float]     # 四象限概率分布
    dominant_regime: str               # 主导 Regime
    confidence: float                  # 置信度 (0-1)
    observed_at: date                  # 观测日期
```

### 2.5 关键特性

1. **模糊权重分布**: 不是硬分类，而是输出四个象限的概率分布
2. **置信度量化**: 评估判定的确定性
3. **容错机制**: 数据不足时使用前值填充或降级方案

---

## 3. Policy 过滤算法

### 3.1 文件位置

| 层级 | 文件路径 |
|------|----------|
| Domain | `apps/policy/domain/rules.py` |
| Entities | `apps/policy/domain/entities.py` |

### 3.2 政策档位定义

| 档位 | 名称 | 市场行动 | 现金调整 | 暂停信号 | 人工审批 | 告警 |
|------|------|----------|----------|----------|----------|------|
| P0 | 常态 | 正常运行 | 0% | 否 | 否 | 否 |
| P1 | 预警 | 提升现金 | +10% | 否 | 否 | 否 |
| P2 | 干预 | 暂停信号 | +20% | 48小时 | 是 | 是 |
| P3 | 危机 | 人工接管 | +100% | 无限期 | 是 | 是 |

### 3.3 响应规则

```python
POLICY_RESPONSE_RULES: Dict[PolicyLevel, PolicyResponse] = {
    PolicyLevel.P0: PolicyResponse(cash_adjustment=0.0, pause_duration_hours=0),
    PolicyLevel.P1: PolicyResponse(cash_adjustment=0.1, pause_duration_hours=0),
    PolicyLevel.P2: PolicyResponse(cash_adjustment=0.2, pause_duration_hours=48),
    PolicyLevel.P3: PolicyResponse(cash_adjustment=1.0, pause_duration_hours=None),
}
```

---

## 4. 投资信号证伪算法

### 4.1 文件位置

| 层级 | 文件路径 |
|------|----------|
| Domain | `apps/signal/domain/invalidation.py` |
| Application | `apps/signal/application/invalidation_checker.py` |
| Parser | `apps/signal/domain/parser.py` |

### 4.2 证伪条件结构

```python
@dataclass(frozen=True)
class InvalidationCondition:
    indicator_code: str           # 指标代码
    indicator_type: IndicatorType # 宏观/市场/自定义
    operator: ComparisonOperator  # < / <= / > / >= / ==
    threshold: float              # 阈值
    duration: Optional[int]       # 持续期数
    compare_with: Optional[str]   # prev_value (与前值比较)

@dataclass(frozen=True)
class InvalidationRule:
    conditions: List[InvalidationCondition]
    logic: LogicOperator  # AND / OR
```

### 4.3 证伪逻辑评估

```python
def evaluate_rule(rule: InvalidationRule, indicator_values: Dict[str, IndicatorValue]):
    for condition in rule.conditions:
        # 1. 获取指标值
        # 2. 处理 compare_with (如与前值比较)
        # 3. 执行比较操作
        # 4. 检查持续期
        is_met = evaluate_condition(condition, indicator_value)

    # 根据 logic (AND/OR) 判断整体结果
    if rule.logic == AND:
        is_invalidated = all(results)
    else:
        is_invalidated = any(results)

    return InvalidationCheckResult(...)
```

### 4.4 自然语言解析

支持将自然语言转换为结构化规则：

| 输入示例 | 解析结果 |
|----------|----------|
| "PMI 跌破 50 且 CPI 大于 3" | `AND(PMI<50, CPI>3)` |
| "PMI 连续2期跌破 50" | `PMI<50, duration=2` |

---

## 5. 宏观数据处理算法

### 5.1 文件位置

| 层级 | 文件路径 |
|------|----------|
| Entities | `apps/macro/domain/entities.py` |

### 5.2 单位转换系统

支持货币单位统一转换为"元"层级：

| 原始单位 | 转换系数 | 目标单位 |
|----------|----------|----------|
| 万元 | ×10,000 | 元 |
| 亿元 | ×100,000,000 | 元 |
| 万亿元 | ×1,000,000,000,000 | 元 |
| 万美元 | ×1,000,000 | 元 |
| 亿美元 | ×1,000,000,000 | 元 |

**非货币类单位**:
- `%` - 百分比（利率、通胀率、增长率等）
- `指数` - 指数类（PMI等）
- `点` - 股票指数点数
- `元/g` - 元/克（黄金期货）
- `元/吨` - 元/吨（铜期货）

### 5.3 数据类型

```python
@dataclass(frozen=True)
class MacroIndicator:
    code: str                    # 指标代码
    value: float                  # 统一存储为"元"或原始单位
    reporting_period: date        # 报告期
    period_type: PeriodType       # D/W/M/Q/Y
    unit: str                     # 存储单位
    original_unit: str            # 原始单位（用于展示）
    published_at: Optional[date]  # 实际发布日期
    source: str                   # 数据源
```

---

## 6. 回测算法

### 6.1 文件位置

| 层级 | 文件路径 |
|------|----------|
| Domain | `apps/backtest/domain/services.py` |
| Entities | `apps/backtest/domain/entities.py` |

### 6.2 回测引擎流程

```python
class BacktestEngine:
    def run(self) -> BacktestResult:
        # 1. 生成再平衡日期
        rebalance_dates = self._generate_rebalance_dates()

        # 2. 按时间步进
        for rebalance_date in rebalance_dates:
            # 2.1 获取当前 Regime
            regime_data = self.get_regime(rebalance_date)

            # 2.2 计算目标权重（应用准入规则）
            target_weights = self._calculate_target_weights(regime, confidence)

            # 2.3 执行再平衡
            self._rebalance(rebalance_date, target_weights)

            # 2.4 记录权益曲线
            self._equity_curve.append((rebalance_date, portfolio_value))

        # 3. 计算绩效指标
        return BacktestResult(...)
```

### 6.3 Point-in-Time 数据处理

```python
class PITDataProcessor:
    """确保回测时只使用当时已经发布的数据，避免未来函数"""

    def is_data_available(self, observed_at, indicator_code, as_of_date) -> bool:
        published_at = observed_at + publication_lag
        return published_at <= as_of_date
```

### 6.4 绩效指标计算

| 指标 | 计算公式 |
|------|----------|
| 年化收益 | `(1 + total_return)^(1/years) - 1` |
| 夏普比率 | `(annualized_mean - risk_free_rate) / annualized_std` |
| 最大回撤 | `max((peak - value) / peak)` |

---

## 7. 资产准入矩阵算法

### 7.1 文件位置

| 层级 | 文件路径 |
|------|----------|
| Shared Domain | `shared/domain/asset_eligibility.py` |

### 7.2 准入等级定义

```python
class Eligibility(Enum):
    PREFERRED = "preferred"  # 优选
    NEUTRAL = "neutral"      # 中性
    HOSTILE = "hostile"      # 敌对
```

### 7.3 默认准入矩阵

| 资产类别 | Recovery | Overheat | Stagflation | Deflation |
|----------|----------|----------|-------------|-----------|
| a_share_growth | PREFERRED | NEUTRAL | HOSTILE | NEUTRAL |
| a_share_value | PREFERRED | PREFERRED | NEUTRAL | HOSTILE |
| china_bond | NEUTRAL | HOSTILE | NEUTRAL | PREFERRED |
| gold | NEUTRAL | PREFERRED | PREFERRED | NEUTRAL |
| commodity | NEUTRAL | PREFERRED | HOSTILE | HOSTILE |
| cash | HOSTILE | NEUTRAL | PREFERRED | NEUTRAL |

### 7.4 信号拒绝逻辑

```python
def should_reject_signal(asset_class, current_regime, policy_level, confidence):
    eligibility = check_eligibility(asset_class, current_regime)

    # 拒绝条件 1: 资产在当前 Regime 下为 HOSTILE
    if eligibility == HOSTILE:
        return True, "资产在当前环境下不适宜"

    # 拒绝条件 2: 政策档位为 P3
    if policy_level >= 3:
        return True, "政策档位为 P3，完全退出"

    # 拒绝条件 3: 低置信度 + NEUTRAL 资产
    if confidence < 0.3 and eligibility == NEUTRAL:
        return True, "置信度较低且资产仅为 NEUTRAL"

    return False, None, eligibility
```

---

## 8. 资产配置矩阵算法

### 8.1 文件位置

| 层级 | 文件路径 |
|------|----------|
| Strategy Domain | `apps/strategy/domain/allocation_matrix.py` |

### 8.2 配置矩阵结构

16种配置：4种 Regime × 4种风险偏好

```python
ALLOCATION_MATRIX: Dict[RegimeType, Dict[RiskProfile, AllocationTarget]] = {
    RegimeType.RECOVERY: {
        RiskProfile.AGGRESSIVE: AllocationTarget(
            allocation=AssetAllocation(equity=0.70, fixed_income=0.15, commodity=0.05, cash=0.10),
            reasoning="复苏期权益资产表现优异，激进型可高配股票",
            expected_return=0.12,
            expected_volatility=0.18,
            sharpe_ratio=0.67
        ),
        # ... 其他风险偏好
    },
    # ... 其他 Regime
}
```

### 8.3 Policy 档位调整

```python
POLICY_EQUITY_ADJUSTMENT = {
    PolicyLevel.P0: 1.0,  # 正常：不调整
    PolicyLevel.P1: 0.8,  # 轻度限制：权益仓位×0.8
    PolicyLevel.P2: 0.6,  # 中度限制：权益仓位×0.6
    PolicyLevel.P3: 0.3,  # 极度限制：权益仓位×0.3
}
```

---

## 9. Kalman 滤波算法

### 9.1 文件位置

| 层级 | 文件路径 |
|------|----------|
| Infrastructure | `shared/infrastructure/kalman_filter.py` |
| Domain Entities | `apps/regime/domain/entities.py` |

### 9.2 局部线性趋势滤波器

```python
class LocalLinearTrendFilter:
    def __init__(self, level_variance=0.01, slope_variance=0.001, observation_variance=1.0):
        # 状态转移矩阵 F
        self.F = [[1.0, 1.0], [0.0, 1.0]]

        # 观测矩阵 H
        self.H = [[1.0, 0.0]]

        # 过程噪声协方差 Q
        self.Q = [[level_variance, 0.0], [0.0, slope_variance]]

        # 观测噪声协方差 R
        self.R = [[observation_variance]]

    def filter(self, observations: List[float]) -> KalmanFilterResult:
        # 预测-更新循环
        for y in observations:
            x_pred = F @ x
            P_pred = F @ P @ F.T + Q
            K = P_pred @ H.T @ inv(H @ P_pred @ H.T + R)
            x = x_pred + K @ (y - H @ x_pred)
            P = (I - K @ H) @ P_pred
            # ...
```

### 9.3 月度宏观数据参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| level_variance | 0.05 | 水平方差 |
| slope_variance | 0.005 | 斜率方差 |
| observation_variance | 0.5 | 观测方差 |

---

## 10. HP 滤波算法

### 10.1 文件位置

| 层级 | 文件路径 |
|------|----------|
| Infrastructure | `shared/infrastructure/calculators.py` |

### 10.2 扩张窗口 HP 滤波

```python
def calculate_expanding_hp_trend(series, lamb=129600, min_length=12):
    """
    扩张窗口 HP 滤波（避免后视偏差）

    对于每个时刻 t，只用 [0, t] 的数据进行滤波
    """
    trend_values = []
    for t in range(len(series)):
        if t < min_length:
            trend_values.append(series[t])
        else:
            # 只用 [0, t] 的数据进行滤波
            truncated = series[:t+1]
            trend, _ = hpfilter(truncated, lamb=lamb)
            trend_values.append(trend[-1])

    return TrendResult(values=trend_values, z_scores=...)
```

### 10.3 Lambda 参数选择

| 数据频率 | Lambda 参数 |
|----------|-------------|
| 年度 | 1600 |
| 季度 | 14400 |
| 月度 | 129600 |

---

## 11. 波动率控制算法

### 11.1 文件位置

| 层级 | 文件路径 |
|------|----------|
| Account Domain | `apps/account/domain/services.py` |

### 11.2 波动率计算

```python
def calculate_volatility(returns, window_days=30, annualize=True):
    daily_vol = stdev(returns[-window_days:])
    annualized_vol = daily_vol * sqrt(252) if annualize else daily_vol
    return VolatilityMetrics(...)
```

### 11.3 波动率目标控制

```python
def assess_volatility_adjustment(current_volatility, target_volatility, tolerance=0.2, max_reduction=0.5):
    volatility_ratio = current_volatility / target_volatility
    should_reduce = volatility_ratio > (1 + tolerance)

    if should_reduce:
        suggested_multiplier = min(target_volatility / current_volatility, 1.0 - max_reduction)
    else:
        suggested_multiplier = 1.0

    return VolatilityAdjustmentResult(...)
```

---

## 12. 止损止盈算法

### 12.1 固定止损

```python
stop_price = entry_price * (1 + stop_loss_pct)
should_trigger = current_price <= stop_price
```

### 12.2 移动止损

```python
stop_price = highest_price * (1 - trailing_pct)
should_trigger = current_price <= stop_price
```

### 12.3 时间止损

```python
holding_days = (current_time - opened_at).days
should_trigger = holding_days >= max_holding_days
```

### 12.4 分批止盈

```python
for i, level in enumerate(partial_levels):
    if unrealized_pnl_pct >= level:
        return TakeProfitCheckResult(partial_level=i+1, ...)
```

---

## 13. 归因分析算法

### 13.1 文件位置

| 层级 | 文件路径 |
|------|----------|
| Audit Domain | `apps/audit/domain/services.py` |

### 13.2 收益分解（Brinson 模型）

```python
def _decompose_pnl(performances: List[PeriodPerformance]):
    """
    分解收益来源：
    - 择时收益：正确判断 Regime 带来的收益
    - 选资产收益：在正确 Regime 下选择最优资产带来的收益
    - 交互收益：择时和选资产的交互作用
    """
    timing_pnl = sum(perf.portfolio_return * 0.3 for perf in performances if perf.portfolio_return > 0)
    selection_pnl = sum(excess_return * 0.5 for perf in performances if excess_return > 0)
    interaction_pnl = total_return - timing_pnl - selection_pnl
    return timing_pnl, selection_pnl, interaction_pnl
```

---

## 14. 基金/股票筛选算法

### 14.1 基金筛选

```python
def screen_by_regime(all_funds, preferred_types, preferred_styles, min_scale, max_count):
    for fund_info, fund_perf, sector_alloc in all_funds:
        # 1. 基金类型过滤
        if fund_info.fund_type not in preferred_types:
            continue

        # 2. 投资风格过滤
        if fund_info.investment_style not in preferred_styles:
            continue

        # 3. 计算评分
        score = _calculate_fund_score(fund_info, fund_perf)

    return matched_funds_sorted_by_score[:max_count]
```

### 14.2 股票筛选

```python
def screen(all_stocks, rule: StockScreeningRule):
    for stock_info, financial, valuation in all_stocks:
        # 1. 行业偏好
        if stock_info.sector not in rule.sector_preference:
            continue

        # 2. 财务指标
        if financial.roe < rule.min_roe:
            continue

        # 3. 估值指标
        if valuation.pe > rule.max_pe:
            continue

        # 4. 计算评分
        score = growth_score * 0.4 + profitability_score * 0.4 + valuation_score * 0.2

    return sorted_stocks_by_score[:max_count]
```

---

## 15. 缓存服务

### 15.1 文件位置

| 层级 | 文件路径 |
|------|----------|
| Infrastructure | `shared/infrastructure/cache_service.py` |

### 15.2 Regime 缓存机制

```python
class CacheService:
    @staticmethod
    def get_regime(as_of_date, growth_indicator, inflation_indicator):
        """获取缓存的 Regime 数据"""
        key = f"regime:{as_of_date}:{growth_indicator}:{inflation_indicator}"
        return redis_client.get(key)

    @staticmethod
    def set_regime(as_of_date, growth_indicator, inflation_indicator, data, ttl=3600):
        """缓存 Regime 计算结果（默认1小时）"""
        key = f"regime:{as_of_date}:{growth_indicator}:{inflation_indicator}"
        redis_client.setex(key, ttl, json.dumps(data))
```

---

## 16. 关键参数汇总表

### 16.1 Regime 计算参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| momentum_period | 3 | 动量计算周期（月） |
| zscore_window | 24 | Z-score 滚动窗口 |
| zscore_min_periods | 12 | Z-score 最小计算周期 |
| sigmoid_k | 2.0 | Sigmoid 斜率参数 |

### 16.2 Kalman 滤波参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| level_variance | 0.05 | 水平方差（月度宏观数据） |
| slope_variance | 0.005 | 斜率方差 |
| observation_variance | 0.5 | 观测方差 |

### 16.3 HP 滤波参数

| 数据频率 | Lambda 参数 |
|----------|-------------|
| 年度 | 1600 |
| 季度 | 14400 |
| 月度 | 129600 |

### 16.4 风险控制参数

| 参数 | 保守型 | 稳健型 | 激进型 |
|------|--------|--------|--------|
| 单一资产最大仓位 | 5% | 10% | 20% |
| 目标波动率 | 10% | 15% | 20% |

---

## 17. 架构合规性检查

### Domain 层约束

| 约束 | 要求 | 状态 |
|------|------|------|
| 外部库依赖 | 只使用 Python 标准库 | ✅ 合规 |
| 数据结构 | 使用 `@dataclass(frozen=True)` | ✅ 合规 |
| 业务逻辑 | 所有金融逻辑在此层 | ✅ 合规 |

### Application 层约束

| 约束 | 要求 | 状态 |
|------|------|------|
| 依赖方式 | 通过 Protocol 接口依赖注入 | ✅ 合规 |
| 业务逻辑 | 只做编排，不含业务规则 | ✅ 合规 |
| ORM 访问 | 禁止直接使用 Django Model | ✅ 合规 |

### Infrastructure 层约束

| 约束 | 要求 | 状态 |
|------|------|------|
| 外部库 | 可使用 Django、Pandas、NumPy | ✅ 合规 |
| 接口实现 | 实现 Domain 层定义的 Protocol | ✅ 合规 |
| 数据适配 | API 适配器、数据仓储 | ✅ 合规 |

### Interface 层约束

| 约束 | 要求 | 状态 |
|------|------|------|
| 业务逻辑 | 只做输入验证和输出格式化 | ✅ 合规 |
| 框架依赖 | 可使用 DRF、Django View | ✅ 合规 |

---

## 18. 文件路径索引

### Regime 模块
- Domain Services: `apps/regime/domain/services.py`
- Domain Entities: `apps/regime/domain/entities.py`
- Application Use Cases: `apps/regime/application/use_cases.py`
- Application Tasks: `apps/regime/application/tasks.py`

### Signal 模块
- Invalidation Rules: `apps/signal/domain/invalidation.py`
- Signal Rules: `apps/signal/domain/rules.py`
- Signal Entities: `apps/signal/domain/entities.py`
- Indicators: `apps/signal/domain/indicators.py`
- Parser: `apps/signal/domain/parser.py`
- Invalidation Checker: `apps/signal/application/invalidation_checker.py`

### Policy 模块
- Policy Rules: `apps/policy/domain/rules.py`
- Policy Entities: `apps/policy/domain/entities.py`

### Macro 模块
- Macro Entities: `apps/macro/domain/entities.py`

### Backtest 模块
- Backtest Services: `apps/backtest/domain/services.py`
- Backtest Entities: `apps/backtest/domain/entities.py`

### Account 模块
- Account Services: `apps/account/domain/services.py`

### Shared 模块
- Asset Eligibility: `shared/domain/asset_eligibility.py`
- Kalman Filter: `shared/infrastructure/kalman_filter.py`
- Calculators: `shared/infrastructure/calculators.py`
- Cache Service: `shared/infrastructure/cache_service.py`

### Strategy 模块
- Allocation Matrix: `apps/strategy/domain/allocation_matrix.py`

### Equity 模块
- Equity Services: `apps/equity/domain/services.py`

### Fund 模块
- Fund Services: `apps/fund/domain/services.py`

### Audit 模块
- Audit Services: `apps/audit/domain/services.py`

---

## 19. 算法流程图

### 19.1 完整投资决策流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           投资决策流程                                  │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │   采集宏观数据           │
                    │   - PMI, CPI, M2        │
                    │   - SHIBOR, 债券收益率   │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   Regime 判定           │
                    │   - 动量计算             │
                    │   - Z-score 标准化      │
                    │   - 四象限分布           │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴───────────┐
                                ▼
                    ┌─────────────────────────┐
                    │   Policy 过滤           │
                    │   - 政策档位判定         │
                    │   - 准入等级检查         │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   信号生成与证伪         │
                    │   - 生成投资信号         │
                    │   - 评估证伪条件         │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   资产配置               │
                    │   - 配置矩阵选择         │
                    │   - 波动率控制           │
                    │   - 止损止盈             │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   事后审计               │
                    │   - 归因分析             │
                    │   - 绩效评估             │
                    └─────────────────────────┘
```

### 19.2 Regime 判定流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Regime 判定流程                                 │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │   输入：宏观数据         │
                    │   - 增长指标 (PMI)       │
                    │   - 通胀指标 (CPI)       │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   动量计算              │
                    │   - 相对动量 (PMI)       │
                    │   - 绝对动量 (CPI)       │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   Z-score 标准化        │
                    │   - 滚动窗口均值         │
                    │   - 滚动窗口标准差       │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   Sigmoid 转换          │
                    │   - P(增长↑)             │
                    │   - P(通胀↑)             │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   四象限概率分布         │
                    │   - P(复苏)              │
                    │   - P(过热)              │
                    │   - P(滞胀)              │
                    │   - P(通缩)              │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   输出：RegimeSnapshot   │
                    │   - dominant_regime      │
                    │   - distribution         │
                    │   - confidence           │
                    └─────────────────────────┘
```

### 19.3 投资信号证伪流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       投资信号证伪流程                                   │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────┐
                    │   输入：投资信号         │
                    │   - asset_code           │
                    │   - logic_desc           │
                    │   - invalidation_logic   │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   解析证伪规则           │
                    │   - 自然语言解析         │
                    │   - 结构化条件提取       │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   获取指标数据           │
                    │   - 宏观指标             │
                    │   - 市场指标             │
                    │   - 自定义指标           │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   评估证伪条件           │
                    │   - 比较操作             │
                    │   - 持续期检查           │
                    │   - 前值比较             │
                    └───────────┬─────────────┘
                                │
                    ┌───────────┴───────────┐
                                ▼
                    ┌─────────────────────────┐
                    │   逻辑组合 (AND/OR)      │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   输出：证伪结果         │
                    │   - is_invalidated       │
                    │   - matched_conditions   │
                    │   - failed_conditions    │
                    └─────────────────────────┘
```

---

## 20. 数据源配置

### 20.1 Tushare Pro

| 数据类型 | API 函数 | 说明 |
|----------|----------|------|
| SHIBOR | `pro.shibor()` | 上海银行间同业拆放利率 |
| 指数日线 | `pro.index_daily()` | 指数日线行情 |
| 国债收益率 | `pro.bz()` | 中债国债收益率曲线 |

### 20.2 AKShare

| 数据类型 | AKShare 函数 | 说明 |
|----------|--------------|------|
| PMI | `ak.macro_china_pmi()` | 制造业/非制造业PMI |
| CPI | `ak.macro_china_cpi()` | 居民消费价格指数 |
| PPI | `ak.macro_china_ppi()` | 工业生产者出厂价格指数 |
| M2 | `ak.macro_china_money_supply()` | 货币供应量 |

---

## 21. 总结

AgomSAAF 系统的算法实现具有以下特点：

1. **严格分层架构**: 所有算法逻辑按照四层架构规范组织，Domain 层不含任何外部依赖
2. **模糊概率分布**: Regime 判定输出概率分布而非硬分类，提供更丰富的决策信息
3. **证伪机制完备**: 投资信号支持多条件、支持持续期检查、支持前值比较的证伪规则
4. **风控全面**: 波动率控制、止损止盈、Policy 档位等多重风控机制
5. **回测严谨**: Point-in-Time 数据处理，避免未来函数

---

**报告生成时间**: 2026-01-31
**系统版本**: AgomSAAF V1.0
