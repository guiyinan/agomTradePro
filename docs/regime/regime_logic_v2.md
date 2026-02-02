# Regime 判定逻辑 V2.0 - 基于水平的判定方法

## 问题背景

### 原有问题

原有系统使用**动量**（Momentum，即变化率）的 Z-score 来判定 Regime，导致经济直觉上的错误：

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

## 新版判定逻辑 (V2.0)

### 核心原则

1. **PMI > 50** → 经济扩张
2. **PMI < 50** → 经济收缩
3. **CPI > 阈值** → 高通胀
4. **CPI < 阈值** → 低通胀/通缩

### 判定矩阵

| PMI | CPI | Regime | 说明 |
|-----|-----|--------|------|
| > 50 | < 2% | Recovery（复苏） | 经济扩张，通胀受控 |
| > 50 | > 2% | Overheat（过热） | 经济扩张，通胀上升 |
| < 50 | > 2% | Stagflation（滞胀） | 经济收缩，通胀高企 |
| < 50 | < 2% | Deflation（通缩） | 经济收缩，通胀低迷 |

### 默认阈值

```python
PMI 阈值：
  - 扩张：PMI > 50
  - 收缩：PMI < 50

CPI 阈值：
  - 高通胀：CPI > 2%
  - 低通胀：CPI < 1%
  - 通缩：CPI < 0%
```

---

## 代码实现

### 新增文件

1. **`apps/regime/domain/services_v2.py`** - 新版 Domain 服务
2. **`apps/regime/infrastructure/models.py`** - 阈值配置模型
3. **`tests/unit/domain/test_regime_services_v2.py`** - 测试用例

### 核心类

#### RegimeType (枚举)

```python
class RegimeType(Enum):
    RECOVERY = "Recovery"      # 复苏：增长↑，通胀↓
    OVERHEAT = "Overheat"      # 过热：增长↑，通胀↑
    STAGFLATION = "Stagflation" # 滞胀：增长↓，通胀↑
    DEFLATION = "Deflation"    # 通缩：增长↓，通胀↓
```

#### RegimeCalculatorV2 (计算器)

```python
class RegimeCalculatorV2:
    def __init__(self, config: Optional[ThresholdConfig] = None):
        self.config = config or ThresholdConfig()

    def calculate(
        self,
        pmi_series: List[float],
        cpi_series: List[float],
        as_of_date: date
    ) -> RegimeCalculationResult:
        # 1. 基于水平判定 Regime
        # 2. 计算概率分布
        # 3. 计算趋势指标（用于预测）
        # 4. 生成预测
```

#### RegimeCalculationResult (结果)

```python
@dataclass(frozen=True)
class RegimeCalculationResult:
    regime: RegimeType              # 主导 Regime
    confidence: float                # 置信度
    growth_level: float              # PMI 当前值
    inflation_level: float           # CPI 当前值
    growth_state: str                # 'expansion', 'contraction'
    inflation_state: str             # 'high', 'low', 'deflation'
    distribution: Dict[str, float]   # 四象限概率分布
    trend_indicators: List[TrendIndicator]  # 趋势指标
    warnings: List[str]              # 警告信息
    prediction: Optional[str]        # 趋势预测
```

---

## 趋势预测指标

### 动量计算

动量不再用于判定 Regime，而是作为**趋势预测**的辅助指标：

```python
@dataclass(frozen=True)
class TrendIndicator:
    indicator_code: str    # 指标代码 (PMI, CPI)
    current_value: float   # 当前值
    momentum: float        # 动量值（变化量）
    momentum_z: float      # 动量 Z-score
    direction: str         # 'up', 'down', 'neutral'
    strength: str         # 'weak', 'moderate', 'strong'
```

### 预测逻辑

基于当前 Regime 和动量方向，预测未来可能的变化：

| 当前 Regime | PMI 趋势 | CPI 趋势 | 预测 |
|-------------|----------|----------|------|
| Deflation | ↑ | - | 可能转向复苏 |
| Overheat | ↓ | ↓ | 可能开始降温 |
| Deflation | ↑ | ↑ | 可能转向滞胀或复苏 |

---

## 阈值配置

### 数据库模型

```python
class RegimeThresholdConfig(models.Model):
    """Regime 阈值配置"""
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

class RegimeIndicatorThreshold(models.Model):
    """指标阈值配置"""
    config = models.ForeignKey(RegimeThresholdConfig, ...)
    indicator_code = models.CharField(max_length=50)  # PMI, CPI
    level_low = models.FloatField()    # 低水平阈值
    level_high = models.FloatField()   # 高水平阈值
```

### 默认配置

```python
ThresholdConfig(
    pmi_expansion=50.0,      # PMI > 50 为扩张
    cpi_high=2.0,           # CPI > 2% 为高通胀
    cpi_low=1.0,            # CPI < 1% 为低通胀
    cpi_deflation=0.0,      # CPI < 0 为通缩
    momentum_weight=0.3,    # 趋势权重
)
```

---

## 验证结果

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

## 前端展示改进

### 需要展示的信息

1. **当前 Regime 状态**
   - 主导 Regime（带颜色标识）
   - 置信度（进度条）
   - PMI 和 CPI 当前值

2. **四象限分布**
   - 雷达图或饼图
   - 各象限概率

3. **趋势指标**
   - PMI 和 CPI 的动量方向（↑↓→）
   - 动量强度（weak/moderate/strong）
   - 趋势图（折线图）

4. **预测提示**
   - 基于趋势的预测文字
   - 可能的 Regime 转换提示

5. **配置面板**
   - 阈值调整界面
   - 实时预览调整后的结果

### 前端组件建议

```typescript
interface RegimeDashboardProps {
  currentRegime: {
    type: RegimeType;
    confidence: number;
    growthLevel: number;  // PMI
    inflationLevel: number;  // CPI
    growthState: string;
    inflationState: string;
  };
  distribution: Record<string, number>;
  trendIndicators: TrendIndicator[];
  prediction: string | null;
}

// 组件
<RegimeCard />
<DistributionChart />
<TrendIndicators />
<PredictionAlert />
<ThresholdConfig />
```

---

## 迁移指南

### 从旧算法迁移

1. **更新 Domain 服务引用**
```python
# 旧
from apps.regime.domain.services import RegimeCalculator

# 新
from apps.regime.domain.services_v2 import RegimeCalculatorV2
```

2. **运行数据库迁移**
```bash
python manage.py migrate
```

3. **初始化默认阈值**
```bash
python manage.py init_regime_thresholds
```

4. **重新计算历史数据**
```bash
python manage.py recalculate_regime --use-v2
```

---

## 测试覆盖率

| 测试类型 | 通过/总数 | 覆盖率 |
|----------|-----------|--------|
| Regime 判定 | 4/4 | 100% |
| 概率分布 | 1/3 | 33% |
| 动量计算 | 4/4 | 100% |
| 计算器集成 | 3/4 | 75% |
| 预测功能 | 2/2 | 100% |
| **总计** | **15/19** | **79%** |

---

## 参考资料

- 经济周期理论：NBER Business Cycle Dating
- PMI 指标解读：ISM Manufacturing PMI
- 通胀目标制：各国央行通胀目标（通常 2%）
- 滞胀的经济学解释：1970s Oil Shocks
