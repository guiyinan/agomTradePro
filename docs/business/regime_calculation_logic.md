# Regime（经济周期）计算逻辑

## 统一口径说明（2026-03-02）

当前系统中“获取当前 Regime”的业务链路已统一为同一入口：

- 统一入口：`apps/regime/application/current_regime.py::resolve_current_regime`
- 统一算法：`CalculateRegimeV2UseCase`（水平判定）
- 统一参数：`PMI + CPI + use_pit=True + DataSourceConfig 默认数据源`
- 统一降级：实时计算失败时，回退到最新快照；若快照也无数据返回 `Unknown`

已标注弃用（兼容保留，不再用于业务主流程）：

- `apps/regime/application/use_cases.py::GetCurrentRegimeUseCase`
- `apps/regime/application/use_cases.py::CalculateRegimeUseCase`（旧版 V1，保留给历史回算/兼容命令）

## 概述

Regime 模块通过增长动量和通胀动量判定当前经济周期所处的象限：

| 象限 | 增长动量 | 通胀动量 | 投资策略 |
|------|---------|---------|----------|
| **复苏 Recovery** | 高 | 低 | 增配权益、减配现金 |
| **过热 Overheat** | 高 | 高 | 增配商品、减配债券 |
| **滞胀 Stagflation** | 低 | 高 | 现金为王、防御为主 |
| **通缩 Deflation** | 低 | 低 | 增配债券、减配商品 |

---

## 计算流程

### 1. 动量计算（Momentum）

#### 增长指标（PMI等）- 相对动量

```python
momentum = (current - past) / |past|
```

- **适用指标**：PMI、工业增加值、社会零售等绝对值指标
- **数学含义**：相对变化率
- **示例**：PMI 从 49.5 → 50.2，动量 = (50.2-49.5)/49.5 = **+1.4%**

#### 通胀指标（CPI、PPI）- 绝对差值动量

```python
momentum = current - past  # 百分点差值
```

- **适用指标**：CPI、PPI、GDP平减指数等百分比数据
- **数学含义**：百分点差值，避免低基数扭曲
- **示例**：
  - CPI 从 0.1% → 0.3%，动量 = **+0.2pp**（而非 200%）
  - CPI 从 2.0% → 2.5%，动量 = **+0.5pp**

> **重要说明**：通胀指标使用绝对差值的原因：
> - CPI 等比率指标在低通胀时期（如 0.1%）基数很小
> - 使用相对动量会产生巨大扭曲（如 0.1%→0.3% 显示为 200% 动量）
> - 使用百分点差值更符合经济直觉（通胀上升 0.2pp 是温和的）

---

### 2. Z-Score 标准化

```python
z = (momentum - μ) / σ
# μ, σ 是过去60期的滚动均值和标准差（最小24期）
```

**数学含义**：
- 消除量纲差异，使 PMI 和 CPI 动量可比
- 衡量当前动量相对于历史的"异常程度"
- z = +1.5 表示"比历史平均水平高 1.5 个标准差"

---

### 3. Sigmoid 概率转换

```python
P = 1 / (1 + exp(-2 × z))
```

| Z-score | P(向上) | 含义 |
|---------|--------|------|
| -2.0 | 12% | 强烈向下 |
| -1.0 | 27% | 向下 |
| 0.0 | 50% | 中性 |
| +1.0 | 73% | 向上 |
| +2.0 | 88% | 强烈向上 |

---

### 4. 四象限概率分布

```python
P_Recovery    = P_growth_up × (1 - P_inflation_up)
P_Overheat   = P_growth_up × P_inflation_up
P_Stagflation = (1 - P_growth_up) × P_inflation_up
P_Deflation  = (1 - P_growth_up) × (1 - P_inflation_up)
```

**主导象限**：概率最高的象限
**置信度**：主导象限的概率值

---

## 关键参数配置

```python
# apps/regime/domain/services.py - RegimeCalculator

MOMENTUM_PERIOD = 3          # 动量周期：3个月
ZSCORE_WINDOW = 60           # Z-score窗口：60天
ZSCORE_MIN_PERIODS = 24      # 最小计算期：24天
SIGMOID_K = 2.0              # Sigmoid陡峭度参数
USE_ABSOLUTE_INFLATION_MOMENTUM = True  # 通胀使用绝对差值动量
```

---

## 代码架构

### Domain 层 (`apps/regime/domain/`)

**services.py** - 纯业务逻辑：
- `calculate_momentum()` - 增长指标相对动量
- `calculate_absolute_momentum()` - 通胀指标绝对差值动量
- `calculate_rolling_zscore()` - 滚动 Z-score
- `calculate_regime_distribution()` - 四象限概率计算
- `RegimeCalculator` - 计算器编排

**entities.py** - 数据实体：
- `RegimeSnapshot` - Regime 快照

### Application 层 (`apps/regime/application/`)

**use_cases.py** - 用例编排：
- `CalculateRegimeUseCase` - 计算 Regime（带容错、缓存）
- 支持指标映射、数据前值填充、降级方案

---

## 与原设计的差异

### 原设计（regime.txt）

```
原始数据 → HP滤波 → 去趋势周期值
                ↓
            3月差分 → 动量
                ↓
            滚动标准化 → Z-Score
                ↓
            正态CDF转换 → 四象限判定
```

### 当前实现

```
原始数据 → 3月差分 → 动量（区分增长/通胀算法）
                ↓
            滚动标准化 → Z-Score
                ↓
            Sigmoid转换 → 四象限判定
```

**简化说明**：
- ❌ 移除了 HP 滤波（避免后视偏差，扩张窗口计算复杂）
- ✅ 直接计算 3 个月动量（更敏感、更及时）
- ✅ 通胀指标使用绝对差值（避免低基数扭曲）
- ✅ 使用 Sigmoid 替代正态 CDF（计算更简单）

---

## 示例计算

### 场景：2024年中国经济

**数据**：
- PMI：49.2 → 49.8 → 50.1 → **50.3**（逐步回升）
- CPI：0.1% → 0.2% → 0.2% → **0.3%**（低位温和上升）

**动量计算**：
- PMI 动量：(50.3 - 49.2) / 49.2 = **+2.2%**（相对动量）
- CPI 动量：0.3 - 0.1 = **+0.2pp**（绝对差值）

**Z-Score**（假设）：
- PMI Z: **+0.8**（温和回升）
- CPI Z: **+0.3**（低位上升，但历史波动大）

**概率转换**（k=2.0）：
- P_growth_up = 1/(1+exp(-2×0.8)) = **83%**
- P_inflation_up = 1/(1+exp(-2×0.3)) = **55%**

**四象限分布**：
- Recovery = 83% × 45% = **37%**
- Overheat = 83% × 55% = **46%** ← 主导
- Stagflation = 17% × 55% = 9%
- Deflation = 17% × 45% = 8%

**结论**：Overheat（过热），置信度 46%

> **经济解读**：增长温和回升 + 通胀低位企稳 = 边际过热
> 但需注意：46% 置信度不算高，形势接近复苏/过热边界

---

## 常见问题

### Q1: 为什么通胀 0.3% 还算"过热"？

A: Regime 判定基于**动量方向**而非绝对水平：
- CPI 虽然只有 0.3%（绝对水平低）
- 但从 0.1% 上升到 0.3%（动量为正）
- 配合 PMI 回升，就进入"过热"象限
- **投资含义**：这是从通缩向温和通胀的过渡期，资产配置需要相应调整

### Q2: 什么时候会切换象限？

A: 取决于动量变化：
- 过热 → 复苏：通胀动量转负（CPI 回落）
- 过热 → 滞胀：增长动量转负（PMI 回落）
- 通常需要 2-3 个月的趋势确认

### Q3: Z-score 窗口为什么是 60 天？

A: 权衡灵敏度和稳定性：
- 太短（如 30 天）：噪音大，容易误判
- 太长（如 120 天）：反应慢，滞后严重
- 60 天 = 约 2 个月，捕捉中期趋势

---

## 更新日志

### 2026-01-22 - 通胀动量算法优化

**问题**：使用相对动量计算 CPI 导致低通胀时期数据扭曲
- CPI 0.1% → 0.3% 显示为 200% 动量
- 错误判定为"高通胀动量"

**解决方案**：对通胀指标使用绝对差值动量
- 新增 `calculate_absolute_momentum()` 函数
- CPI 0.1% → 0.3% = +0.2pp 动量（合理）
- `RegimeCalculator` 增加 `use_absolute_inflation_momentum` 参数（默认 True）

**影响**：
- 通胀低位时期（CPI < 1%）的判定更准确
- 过热/复苏象限切换更符合经济直觉
