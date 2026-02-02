# Regime 算法切换备忘录 - V1 动量法 → V2 水平法

**日期**: 2026-02-01
**版本**: AgomSAAF V3.4
**状态**: 已完成

---

## 一、切换原因

### 问题描述

原系统使用 **V1 动量法**（基于 PMI/CPI 的变化趋势 Z-Score）判定 Regime，导致经济直觉上的错误：

```
实际数据（2026年1月）：
- PMI = 49.3（低于50，制造业收缩）
- CPI = 0.8%（低通胀）

经济直觉：Deflation（通缩）
原算法结果：Overheat（过热）❌

原因：PMI从49.0升到49.3（动量为正），CPI从-0.3%升到0.8%（动量为正）
```

### 核心问题

**动量 ≠ 水平**

| 维度 | 动量法 | 水平法 | 哪个更符合经济直觉？ |
|------|--------|--------|-------------------|
| PMI 49.3 | 相对于3个月前上升 | 仍低于50（收缩） | **水平法** |
| CPI 0.8% | 相对于3个月前上升 | 仍是低通胀 | **水平法** |

Regime 判定应该基于**绝对水平**（经济是否扩张/收缩），而非动量（变化趋势）。

---

## 二、V2 水平法判定规则

### 判定矩阵

| PMI | CPI | Regime | 说明 |
|-----|-----|--------|------|
| ≥ 50 | ≤ 2% | Recovery（复苏） | 经济扩张，通胀受控 |
| ≥ 50 | > 2% | Overheat（过热） | 经济扩张，通胀上升 |
| < 50 | > 2% | Stagflation（滞胀） | 经济收缩，通胀高企 |
| < 50 | ≤ 2% | Deflation（通缩） | 经济收缩，通胀低迷 |

### 默认阈值

```python
PMI 阈值：
  - 扩张：PMI ≥ 50
  - 收缩：PMI < 50

CPI 阈值：
  - 高通胀：CPI > 2%
  - 低通胀：CPI ≤ 2%
  - 通缩：CPI < 0%
```

---

## 三、代码修改清单

### 1. 首页切换到 V2

**文件**: `apps/dashboard/application/use_cases.py`

**修改内容**:
- 从 `CalculateRegimeUseCase` 切换到 `CalculateRegimeV2UseCase`
- 从 `CalculateRegimeRequest` 切换到 `CalculateRegimeV2Request`
- 处理 V2 响应结构差异（`result.regime.value` 而非 `snapshot.dominant_regime`）

```python
# 修改前
from apps.regime.application.use_cases import CalculateRegimeUseCase, CalculateRegimeRequest
regime_use_case = CalculateRegimeUseCase(macro_repo)
current_regime = regime_response.snapshot.dominant_regime

# 修改后
from apps.regime.application.use_cases import CalculateRegimeV2UseCase, CalculateRegimeV2Request
regime_use_case = CalculateRegimeV2UseCase(macro_repo)
current_regime = regime_response.result.regime.value
```

### 2. CPI 指标映射修复

**文件**: `apps/macro/infrastructure/repositories.py`

**修改内容**:
- 将 CPI 从 `"CN_CPI"`（指数形式）映射到 `"CN_CPI_NATIONAL_YOY"`（百分比形式）

```python
# 修改前
INFLATION_INDICATORS = {
    "CPI": "CN_CPI",  # ❌ 指数形式（值：100.8）
    ...
}

# 修改后
INFLATION_INDICATORS = {
    "CPI": "CN_CPI_NATIONAL_YOY",  # ✅ 百分比形式（值：0.008，即 0.8%）
    ...
}
```

### 3. 教学内容更新

**文件**: `core/templates/dashboard/teaching_modal.html`

**修改内容**:
- 更新 Regime 判定说明章节
- 将"动量 vs 水平判定"改为"V2 水平判定方法"
- 更新 Regime 计算器说明
- 移除对动量 Z-Score 的提及

### 4. 文档更新

**文件**: `docs/teaching/README.md`

**修改内容**:
- 更新教学章节大纲
- 更新算法说明备注

---

## 四、验证结果

### 当前数据（2026年1月）

| 指标 | 值 | 状态 |
|------|-----|------|
| PMI | 49.3 | contraction（收缩） |
| CPI | 0.8% | low（低通胀） |

### 新算法结果

```
Regime: Deflation（通缩）✅
置信度: 33.5%

概率分布:
  Recovery: 29.62%
  Overheat: 18.08%
  Stagflation: 18.76%
  Deflation: 33.53% ← 主导

趋势指标:
  PMI: 49.3, 动量=+0.30 (moderate, 上升)
  CPI: 0.8%, 动量=+1.10 (strong, 上升)

预测: 可能转向复苏或滞胀（取决于哪个先起）
```

### 对比旧算法

| 算法 | 结果 | 是否符合直觉 |
|------|------|--------------|
| 旧算法（动量） | Overheat（过热） | ❌ |
| 新算法（水平） | Deflation（通缩） | ✅ |

---

## 五、影响范围

### 功能模块

- ✅ 首页 (`/dashboard/`) - 已切换到 V2
- ✅ Regime 专用页面 (`/regime/dashboard/`) - 使用 V2
- ✅ 教学模块 (`/dashboard/` → 教学指南) - 已更新内容

### 数据一致性

- ✅ 首页和 Regime 页面现在使用相同的算法，结果一致
- ✅ CPI 数据使用正确的指标（百分比形式）

### 用户体验

- ✅ Regime 判定更符合经济直觉
- ✅ 教学内容与实际算法一致
- ✅ 用户不会在不同页面看到矛盾的 Regime 结果

---

## 六、最终统一状态 ✅

### 系统已完全统一

所有页面统一使用 **V2 水平判定法**，移除了所有 V1 相关代码和切换功能：

- ✅ 首页 (`/dashboard/`) - 使用 V2 水平法
- ✅ Regime 页面 (`/regime/dashboard/`) - 使用 V2 水平法
- ✅ 教学模块 - 已更新为 V2 内容
- ✅ 页面显示 - 移除了 "V1/V2" 切换按钮和版本号标签

### 用户体验优化

1. **移除算法切换按钮** - 页面上不再有切换按钮，避免用户困惑
2. **统一算法显示** - 显示 "水平判定法：PMI ≥ 50 为扩张，CPI > 2% 为高通胀"
3. **移除版本号标签** - 页面上不再显示 "V2" 这样的版本号
4. **简化界面** - 移除了 V1 相关的图表和 JavaScript 代码

### 当前状态验证（2026-02-01）

```
Regime: Recovery (复苏) ✅
PMI: 50.1 (≥50 → 扩张)
CPI: 0.8% (≤2% → 低通胀)
判定: 扩张 + 低通胀 = Recovery
```

---

## 七、维护说明

### 阈值配置

V2 算法的阈值可从数据库配置 (`regime_threshold_config` 表)：

```python
PMI 阈值：50（扩张/收缩分界线）
CPI 阈值：2%（高通胀/低通胀分界线）
```

### 数据同步

同步 CPI 百分比数据：
```bash
python manage.py sync_macro_data --source akshare --indicators CN_CPI_NATIONAL_YOY --years 3
```

---

## 八、参考资料

- V2 算法详细说明: `docs/regime/regime_logic_v2.md`
- V2 Domain 层实现: `apps/regime/domain/services_v2.py`
- V2 Use Case 实现: `apps/regime/application/use_cases.py` (CalculateRegimeV2UseCase)

---

*备忘录创建日期: 2026-02-01*
*AgomSAAF V3.4*
