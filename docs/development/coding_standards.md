# AgomTradePro 编码规范

## 1. 宏观数据单位规范

### 1.1 单位字段

所有宏观数据必须包含以下单位相关字段：
- `unit`: 存储单位（货币类统一为"元"，其他类为原始单位）
- `original_unit`: 原始单位（数据源返回的单位，用于展示）

### 1.2 核心设计原则

**存储层统一：** 涉及货币的数据，无论是人民币还是外币，都必须统一转换为"元"层级存储。

**展示层可读：** 展示时将存储值（元）转换回原始单位（如亿元、万亿元），提高可读性。

**配置化干预：** 支持通过 `IndicatorUnitConfig` 模型人工配置各指标的原始单位。

### 1.3 数据流转过程

```
┌─────────────────┐
│  数据源返回      │
│  原始值+原始单位 │  e.g., 1500亿元
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  MacroDataPoint │
│  - value        │  1500
│  - original_unit│  "亿元"
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  单位转换        │
│  (货币类→元)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  MacroIndicator │
│  - value        │  150000000000
│  - unit         │  "元"
│  - original_unit│  "亿元"
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  数据库存储      │
│  统一为"元"      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  展示层转换      │
│  元→原始单位     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  API/前端展示    │
│  1500亿元        │
└─────────────────┘
```

### 1.4 支持的单位转换

| 原始单位 | 存储单位 | 转换因子 | 示例 |
|---------|---------|---------|------|
| 万元 | 元 | ×10,000 | 100万元 → 1,000,000元 |
| 亿元 | 元 | ×100,000,000 | 1500亿元 → 150,000,000,000元 |
| 万亿元 | 元 | ×1,000,000,000,000 | 3万亿元 → 3,000,000,000,000,000元 |
| 万亿美元 | 元 | ×10,000,000,000,000 | 3.2万亿美元 → 32,000,000,000,000,000元 |
| 亿美元 | 元 | ×1,000,000,000 | 100亿美元 → 100,000,000,000元 |
| 百万美元 | 元 | ×1,000,000 | 500百万美元 → 500,000,000元 |
| 十亿美元 | 元 | ×1,000,000,000 | 10十亿美元 → 10,000,000,000元 |

**注意：** 美元转人民币时，本项目简化处理，假设美元和人民币使用相同的"元"单位层级。如果需要精确转换，应在外汇模块中处理汇率。

### 1.5 非货币类单位

非货币类指标不进行单位转换，存储单位和原始单位相同：

| 单位 | 用途 | 示例指标 |
|-----|------|---------|
| % | 百分比（利率、通胀率、增长率等） | PMI、CPI、M2、SHIBOR、LPR |
| 指数 | 指数类 | 制造业PMI、非制造业PMI |
| 点 | 股票指数点数 | 上证指数、深证成指 |
| 元 | 金额（已标准化） | 国债期货 |
| 元/g | 元/克 | 黄金期货 |
| 元/吨 | 元/吨 | 铜期货 |
| (空) | 无单位（汇率等） | USD/CNY |

## 2. 实现细节

### 2.1 Domain 层 (apps/macro/domain/entities.py)

```python
# 单位转换因子定义
UNIT_CONVERSION_FACTORS: Dict[str, float] = {
    '元': 1,
    '万元': 10000,
    '亿元': 100000000,
    '万亿元': 1000000000000,
    '百万美元': 1000000,
    '亿美元': 100000000,
    '十亿美元': 1000000000,
}

def normalize_currency_unit(value: float, unit: str) -> tuple[float, str]:
    """将货币类数据统一转换为"元"层级"""
    if unit in UNIT_CONVERSION_FACTORS:
        factor = UNIT_CONVERSION_FACTORS[unit]
        return (value * factor, "元")
    return (value, unit)

@dataclass(frozen=True)
class MacroIndicator:
    """宏观指标值对象"""
    code: str
    value: float
    reporting_period: date
    period_type: PeriodType = PeriodType.DAY
    unit: str = ""  # 存储单位（货币类为"元"）
    original_unit: str = ""  # 原始单位（用于展示）
    published_at: Optional[date] = None
    source: str = "unknown"
```

### 2.2 Infrastructure 层 (apps/macro/infrastructure/models.py)

```python
class IndicatorUnitConfig(models.Model):
    """指标单位配置 ORM 模型

    用于人工配置各指标的原始单位，支持优先级配置。
    """
    indicator_code = models.CharField(max_length=50)
    source = models.CharField(max_length=20)  # akshare, tushare, manual
    original_unit = models.CharField(max_length=50)
    is_currency = models.BooleanField(default=False)
    priority = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

class MacroIndicator(models.Model):
    """宏观指标 ORM 模型"""
    code = models.CharField(max_length=50)
    value = models.DecimalField(max_digits=20, decimal_places=6)
    unit = models.CharField(max_length=50, default="")  # 存储单位
    original_unit = models.CharField(max_length=50, default="")  # 原始单位
    reporting_period = models.DateField()
    period_type = models.CharField(max_length=10)
    # ... 其他字段
```

### 2.3 Application 层 (apps/macro/application/indicator_service.py)

```python
class UnitDisplayService:
    """单位展示服务"""

    @staticmethod
    def convert_for_display(
        stored_value: float,
        storage_unit: str,
        original_unit: str
    ) -> tuple[float, str]:
        """
        将存储值转换为展示值

        Args:
            stored_value: 存储的值（货币类为元）
            storage_unit: 存储单位（货币类为"元"）
            original_unit: 原始单位（用于展示）

        Returns:
            tuple: (展示值, 展示单位)

        Examples:
            >>> # GDP: 存储为元，展示为亿元
            >>> UnitDisplayService.convert_for_display(150000000000, "元", "亿元")
            (1500.0, "亿元")
        """
        from ..domain.entities import UNIT_CONVERSION_FACTORS

        # 如果存储单位和原始单位相同，直接返回
        if storage_unit == original_unit:
            return (stored_value, original_unit)

        # 如果存储单位是"元"，需要转换回原始单位
        if storage_unit == "元" and original_unit in UNIT_CONVERSION_FACTORS:
            factor = UNIT_CONVERSION_FACTORS[original_unit]
            display_value = stored_value / factor
            return (display_value, original_unit)

        # 其他情况，直接返回
        return (stored_value, original_unit)

    @classmethod
    def get_indicator_config(cls, indicator_code: str, source: str = None) -> Optional[IndicatorUnitConfig]:
        """获取指标的单位配置（支持人工干预）"""
        queryset = IndicatorUnitConfig.objects.filter(
            indicator_code=indicator_code,
            is_active=True
        )

        if source:
            config = queryset.filter(source=source).first()
            if config:
                return config

        # 返回优先级最高的配置
        return queryset.order_by('-priority').first()

class IndicatorUnitService:
    """指标单位服务"""

    INDICATOR_UNITS: Dict[str, str] = {
        'CN_GDP': '亿元',
        'CN_FX_RESERVES': '万亿美元',
        'CN_NEW_CREDIT': '万亿元',
        # ... 更多指标
    }

    @classmethod
    def get_normalized_unit_and_value(cls, indicator_code: str, value: float) -> tuple[float, str]:
        """获取标准化后的单位和值（货币类自动转换为元）"""
        from ..domain.entities import normalize_currency_unit

        original_unit = cls.get_unit_for_indicator(indicator_code)

        # 如果是货币类单位，进行转换
        if original_unit in ['万亿元', '亿元', '万元', '万亿美元', '亿美元', '百万美元', '十亿美元']:
            normalized_value, normalized_unit = normalize_currency_unit(value, original_unit)
            return (normalized_value, normalized_unit)

        return (value, original_unit)
```

### 2.4 数据采集流程 (apps/macro/application/use_cases.py)

```python
# 数据同步时自动应用单位转换
for dp in new_points:
    # 确定原始单位
    original_unit_to_use = dp.original_unit or (
        dp.unit if dp.unit else IndicatorUnitService.get_unit_for_indicator(dp.code)
    )

    # 获取标准化后的单位和值（货币类自动转换为元）
    normalized_value, normalized_unit = IndicatorUnitService.get_normalized_unit_and_value(
        dp.code, dp.value
    )

    # 存储单位：货币类使用"元"，其他类使用原始单位
    if normalized_unit == "元":
        unit_to_save = "元"
        value_to_save = normalized_value
    else:
        unit_to_save = original_unit_to_use
        value_to_save = dp.value

    indicators_to_save.append(
        MacroIndicator(
            code=dp.code,
            value=value_to_save,  # 存储值（元）
            unit=unit_to_save,  # 存储单位（元）
            original_unit=original_unit_to_use,  # 原始单位（展示用）
            # ... 其他字段
        )
    )
```

### 2.5 适配器实现 (apps/macro/infrastructure/adapters/fetchers/)

适配器需要记录原始单位：

```python
# 示例：GDP 适配器（akshare 返回的是亿元）
def fetch_gdp(self, start_date: date, end_date: date) -> List[MacroDataPoint]:
    """获取中国 GDP 数据

    注意：akshare返回的GDP数据单位是"亿元"
    """
    df = self.ak.macro_china_gdp()

    data_points = []
    for _, row in df.iterrows():
        # 保持原始值，不进行转换
        original_value = float(row['value'])

        point = MacroDataPoint(
            code="CN_GDP",
            value=original_value,  # 原始值（亿元）
            observed_at=row['observed_at'].date(),
            source=self.source_name,
            original_unit="亿元"  # 记录原始单位
        )
        data_points.append(point)

    return data_points
```

### 2.6 API 展示层 (apps/macro/interface/views/table_api.py)

```python
def _format_indicator_for_display(item: MacroIndicator) -> dict:
    """将指标数据格式化为展示格式（原始单位）"""
    # 转换为展示值（原始单位）
    display_value, display_unit = UnitDisplayService.convert_for_display(
        float(item.value),
        item.unit,  # 存储单位（元）
        item.original_unit or item.unit  # 原始单位
    )

    return {
        'id': item.id,
        'code': item.code,
        'value': display_value,  # 展示值（原始单位）
        'unit': display_unit,  # 展示单位（原始单位）
        'storage_value': float(item.value),  # 存储值（元）
        'storage_unit': item.unit,  # 存储单位（元）
        # ... 其他字段
    }
```

## 3. 添加新指标时的步骤

### 3.1 在 IndicatorUnitService 中添加单位映射

```python
# apps/macro/application/indicator_service.py
class IndicatorUnitService:
    INDICATOR_UNITS: Dict[str, str] = {
        'NEW_INDICATOR_CODE': '万亿元',  # 原始单位
    }
```

### 3.2 在适配器中记录原始单位

```python
# 适配器实现
point = MacroDataPoint(
    code="NEW_INDICATOR_CODE",
    value=original_value,  # 保持原始值
    observed_at=observed_at,
    source=self.source_name,
    original_unit="万亿元"  # 记录原始单位
)
```

### 3.3（可选）人工配置单位覆盖

通过 Django Admin 或 API 配置 `IndicatorUnitConfig`：

```python
# 通过 Django Admin
IndicatorUnitConfig.objects.create(
    indicator_code='NEW_INDICATOR_CODE',
    source='manual',  # 手动配置优先级最高
    original_unit='亿元',  # 覆盖默认配置
    is_currency=True,
    priority=100
)
```

## 4. 数据库迁移

添加 `original_unit` 字段和 `IndicatorUnitConfig` 模型后，需要运行迁移：

```bash
# 生成迁移文件
python manage.py makemigrations macro

# 应用迁移
python manage.py migrate
```

## 5. 测试建议

### 5.1 单位转换测试

```python
import pytest
from apps.macro.domain.entities import normalize_currency_unit
from apps.macro.application.indicator_service import UnitDisplayService

def test_normalize_currency_unit():
    # 测试亿元转换
    value, unit = normalize_currency_unit(1500, "亿元")
    assert value == 150000000000
    assert unit == "元"

    # 测试万亿美元转换
    value, unit = normalize_currency_unit(3.2, "万亿美元")
    assert value == 32000000000000
    assert unit == "元"

    # 测试非货币单位（不转换）
    value, unit = normalize_currency_unit(50.5, "%")
    assert value == 50.5
    assert unit == "%"

def test_display_conversion():
    # 测试元转换为亿元（展示）
    display_value, display_unit = UnitDisplayService.convert_for_display(
        150000000000, "元", "亿元"
    )
    assert display_value == 1500.0
    assert display_unit == "亿元"
```

### 5.2 集成测试

```python
def test_macro_data_sync_with_unit_conversion():
    # 创建同步请求
    request = SyncMacroDataRequest(
        start_date=date(2024, 1, 1),
        indicators=["CN_GDP"]  # 亿元
    )

    # 执行同步
    response = use_case.execute(request)

    # 验证数据库中的值已转换为元
    indicator = MacroIndicator.objects.filter(code="CN_GDP").first()
    assert indicator.unit == "元"  # 存储单位
    assert indicator.original_unit == "亿元"  # 原始单位
    # 原始值（亿元）应已转换为元

    # 验证 API 返回展示值
    display_value, display_unit = UnitDisplayService.convert_for_display(
        float(indicator.value),
        indicator.unit,
        indicator.original_unit
    )
    assert display_unit == "亿元"  # 展示单位
```

## 6. 注意事项

1. **精度问题：** 使用 `DecimalField(max_digits=20, decimal_places=6)` 存储货币值，确保精度
2. **向后兼容：** 旧数据没有 `original_unit` 字段，系统会自动使用 `unit` 字段作为回退
3. **汇率处理：** 美元转人民币时，本项目简化处理。如需精确转换，应在外汇模块中处理
4. **性能考虑：** 展示层转换是实时的，如果数据量大，考虑使用缓存
5. **配置优先级：** 手动配置 > 指定数据源配置 > 默认配置

## 7. 常见问题

### Q1: 为什么不在数据库中直接存储原始值？

**A:** 统一存储为"元"有以下好处：
- 便于跨指标比较和计算
- 避免单位混淆
- 支持灵活的展示单位切换

### Q2: 如何覆盖默认单位配置？

**A:** 通过 Django Admin 或 API 创建 `IndicatorUnitConfig` 记录，设置 `source='manual'` 和较高的 `priority` 值。

### Q3: 前端如何显示值？

**A:** API 已经返回展示值（`value` 字段）和展示单位（`unit` 字段），前端直接使用即可。如果需要存储值，可以使用 `storage_value` 和 `storage_unit` 字段。

### Q4: 如何添加新的货币单位？

**A:** 在 `apps/macro/domain/entities.py` 的 `UNIT_CONVERSION_FACTORS` 中添加新的转换因子。
