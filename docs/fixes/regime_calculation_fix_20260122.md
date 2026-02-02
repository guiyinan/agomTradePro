# Regime Calculation 问题诊断与修复方案

**日期:** 2026-01-22
**状态:** 问题已识别，修复方案已制定

---

## 问题描述

PostgreSQL 数据库中的 Regime 计算结果不正确，主要表现为：
- 通胀 Z 分数异常高（+2.07, +2.25）
- 导致一些不正确的 Regime 分类

### 问题示例

| 日期 | 增长 Z | 通胀 Z | 分类 | 问题 |
|------|--------|--------|------|------|
| 2025-12-01 | +0.43 | **+2.07** | Overheat | 通胀 Z 过高 |
| 2025-11-01 | -0.05 | **+2.25** | Stagflation | 通胀 Z 过高 |
| 2025-10-01 | -0.14 | +0.57 | Stagflation | 正常 |
| 2025-09-01 | +0.23 | -0.68 | Recovery | 正常 |

---

## 根本原因分析

### 1. 数据量不足

```
总 CPI 记录: 35 条
配置参数:
  - zscore_window: 60
  - zscore_min_periods: 24

实际可计算的 Z-score: 35 - 24 + 1 = 12 个
```

### 2. 参数配置不匹配

当前配置是为**至少 60 个月**的数据设计的：
```python
RegimeCalculator(
    momentum_period=3,
    zscore_window=60,      # ❌ 需要 60 条数据
    zscore_min_periods=24, # ❌ 需要至少 24 条才开始计算
    ...
)
```

### 3. 统计学问题

由于数据量有限，滚动窗口的统计特性导致：

```
CPI 动量值的统计特征:
  - 均值: -0.0029 (接近 0)
  - 标准差: 0.5326 (很小!)
  - 当前值: +1.1

Z-score = (1.1 - 0) / 0.5326 = 2.07 ← 这是统计学异常，不是经济信号!
```

当大部分动量值都很小时，突然出现 +1.1 的变化会被判定为极端值。

---

## 修复方案

### 方案 A: 调整默认参数（推荐）

修改 `RegimeCalculator` 的默认参数以适应有限数据：

```python
# apps/regime/domain/services.py

class RegimeCalculator:
    def __init__(
        self,
        momentum_period: int = 3,
        zscore_window: int = 24,      # 从 60 降低到 24
        zscore_min_periods: int = 12,  # 从 24 降低到 12
        sigmoid_k: float = 2.0,
        use_absolute_inflation_momentum: bool = True
    ):
```

**优点:**
- 适用于有限数据（20-40 条记录）
- 更稳定，减少极端 Z-score
- 不需要修改数据结构

**缺点:**
- 当数据增长到 60+ 条时，可能需要再次调整

### 方案 B: 动态参数

根据数据量动态调整参数：

```python
def get_calculator_for_data(data_length: int) -> RegimeCalculator:
    """根据数据量返回合适的计算器配置"""
    if data_length >= 60:
        # 足够数据，使用标准配置
        return RegimeCalculator(
            zscore_window=60,
            zscore_min_periods=24
        )
    elif data_length >= 36:
        # 中等数据量
        return RegimeCalculator(
            zscore_window=data_length // 2,
            zscore_min_periods=data_length // 3
        )
    else:
        # 数据量不足，使用最小配置
        return RegimeCalculator(
            zscore_window=max(12, data_length),
            zscore_min_periods=max(6, data_length // 2)
        )
```

### 方案 C: 固定阈值法

不使用 Z-score，而是使用固定阈值：

```python
def classify_momentum(momentum_value: float) -> float:
    """使用固定阈值分类，避免 Z-score 的极端值"""
    if momentum_value > 0.5:
        return 1.5  # 高
    elif momentum_value > 0.1:
        return 0.5  # 中
    elif momentum_value > -0.1:
        return 0.0  # 中性
    elif momentum_value > -0.5:
        return -0.5  # 低
    else:
        return -1.5  # 很低
```

---

## 推荐实施步骤

### 第一步：修复默认参数

修改 `apps/regime/domain/services.py` 第 237-244 行：

```python
def __init__(
    self,
    momentum_period: int = 3,
    zscore_window: int = 24,      # 修改: 60 → 24
    zscore_min_periods: int = 12,  # 修改: 24 → 12
    sigmoid_k: float = 2.0,
    use_absolute_inflation_momentum: bool = True
):
```

### 第二步：重新计算 Regime 数据

```bash
python manage.py recalculate_regime --use-corrected-params
```

### 第三步：验证结果

检查新的 Z-score 是否在合理范围内（-2 到 +2 之间）

---

## 验证脚本

使用以下脚本验证修复效果：

```bash
python verify_regime_fix.py
```

该脚本会：
1. 对比修复前后的 Z-score
2. 检查 Z-score 是否在合理范围内
3. 验证 Regime 分类是否更合理

---

## 相关文件

- `apps/regime/domain/services.py` - RegimeCalculator 类定义
- `apps/regime/application/use_cases.py` - CalculateRegimeUseCase
- `apps/regime/management/commands/recalculate_regime.py` - 重新计算命令

---

## 附录：数据统计

### 当前数据库状态

```
macro_indicator 表:
  - CN_CPI: 35 条记录
  - CN_PMI: 35 条记录
  - CN_PPI: 5 条记录
  - CN_SHIBOR: 123 条记录

regime_log 表:
  - 总记录: 13 条
  - 日期范围: 2024-12-01 至 2025-12-01
```

### CPI 动量分析（最近 10 个月）

| 月份 | CPI 指数 | 3月动量 |
|------|----------|---------|
| 2025-03 | 99.9 | -0.20 |
| 2025-04 | 99.9 | -0.60 |
| 2025-05 | 99.9 | +0.60 |
| 2025-06 | 100.1 | +0.20 |
| 2025-07 | 100.0 | +0.10 |
| 2025-08 | 99.6 | -0.30 |
| 2025-09 | 99.7 | -0.40 |
| 2025-10 | 100.2 | +0.20 |
| 2025-11 | 100.7 | **+1.10** ← 触发高 Z-score |
| 2025-12 | 100.8 | **+1.10** ← 触发高 Z-score |
