# AgomTradePro API 数据结构与适配器映射指南

## 1. 当前 API 数据结构

### 1.1 统一的响应格式

所有 API 返回统一的 JSON 格式：

```json
{
  "success": true/false,
  "message": "操作结果描述",
  "data": { ... },
  "error": "错误信息（可选）"
}
```

### 1.2 核心数据结构

#### MacroIndicator 数据结构（数据库记录）

```python
{
    "id": 123,
    "code": "CN_GDP",              # 指标代码
    "value": 1500.0,               # 展示值（原始单位）
    "unit": "亿元",                # 展示单位（原始单位）
    "storage_value": 150000000000.0,  # 存储值（元）
    "storage_unit": "元",          # 存储单位（元）
    "reporting_period": "2024-01-01",  # 报告期
    "period_type": "Q",            # 期间类型（D/W/M/Q/H/Y）
    "period_type_display": "季",   # 期间类型显示
    "observed_at": "2024-01-01",   # 观测日（兼容旧API）
    "published_at": "2024-01-20",  # 发布日
    "source": "akshare",           # 数据源
    "revision_number": 1,          # 修订版本号
    "publication_lag_days": 20     # 发布延迟天数
}
```

#### 指标列表数据结构

```python
{
    "code": "CN_GDP",
    "name": "GDP",
    "name_en": "GDP",
    "category": "增长",
    "unit": "亿元",          # 展示单位（原始单位）
    "description": "国内生产总值",
    "latest_value": 1500.0,  # 最新展示值
    "latest_date": "2024-01-01",
    "period_type": "Q",
    "threshold_bullish": 6.0,
    "threshold_bearish": 5.0,
    "avg_value": 120000000000.0,  # 平均值（存储值，用于趋势分析）
    "max_value": 150000000000.0,
    "min_value": 100000000000.0
}
```

### 1.3 主要 API 接口

| API | 方法 | 功能 | 数据结构 |
|-----|------|------|---------|
| `/api/macro/table/` | GET | 获取表格数据（分页） | `MacroIndicator[]` |
| `/api/macro/indicator-data/` | GET | 获取单个指标数据 | `MacroIndicator[]` |
| `/api/macro/record/<id>/` | GET/PUT/DELETE | 单条记录 CRUD | `MacroIndicator` |
| `/api/macro/records/batch-delete/` | POST | 批量删除 | `{success, message, deleted_count}` |
| `/api/macro/supported-indicators/` | GET | 获取支持的指标列表 | `{code, name, unit}[]` |
| `/api/macro/fetch/` | POST | 手动触发数据抓取 | `{success, message, synced_count}` |
| `/api/macro/quick-sync/` | POST | 快速同步 | `{success, message, results}` |

## 2. 适配器映射机制

### 2.1 映射流程图

```
┌─────────────────┐
│  API 请求       │
│  indicator_code │  "CN_GDP"
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ FailoverAdapter │  主适配器（容错切换）
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  遍历子适配器列表                  │
│  1. AKShareAdapter                  │
│  2. TushareAdapter                  │
│  ...                                │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────┐
│ supports()?     │  检查是否支持该指标
└────────┬────────┘
         │
    Yes  │  No
    ┌────┴────┐
    │         ▼
    │   ┌─────────────────┐
    │   │ 下一个适配器     │
    │   └─────────────────┘
    ▼
┌─────────────────┐
│ fetch()         │  调用具体 fetcher
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  AKShareAdapter.fetch()            │
│  - 判断 indicator_code              │
│  - 路由到对应的 fetcher            │
│  - 返回 List[MacroDataPoint]        │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Fetcher (如 EconomicFetcher)       │
│  - 调用数据源 API (akshare)         │
│  - 解析返回的 DataFrame             │
│  - 转换为 MacroDataPoint 列表       │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────┐
│ MacroDataPoint  │
│ - code          │  "CN_GDP"
│ - value         │  1500 (原始值)
│ - observed_at   │  2024-01-01
│ - source        │  "akshare"
│ - original_unit │  "亿元" (原始单位)
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  单位转换 (Application Layer)       │
│  - 货币类转换为"元"                 │
│  - 记录 original_unit               │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────┐
│ MacroIndicator  │  数据库存储
│ - value         │  150000000000 (元)
│ - unit          │  "元"
│ - original_unit │  "亿元"
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  API 响应 (Interface Layer)        │
│  - 转换回展示值（原始单位）         │
│  - 返回统一格式的 JSON              │
└─────────────────────────────────────┘
```

### 2.2 适配器结构

#### AKShareAdapter (主要适配器)

```python
class AKShareAdapter(BaseMacroAdapter):
    source_name = "akshare"

    # 支持的指标代码映射
    SUPPORTED_INDICATORS = {
        "CN_PMI": "PMI",
        "CN_CPI": "CPI",
        "CN_GDP": "GDP",
        # ... 更多指标
    }

    def fetch(self, indicator_code, start_date, end_date):
        # 根据指标代码路由到对应的 fetcher
        if indicator_code == "CN_GDP":
            return self.economic_fetcher.fetch_gdp(start_date, end_date)
        elif indicator_code == "CN_PMI":
            return self.base_fetcher.fetch_pmi(start_date, end_date)
        # ... 更多路由逻辑
```

#### Fetcher 分类

| Fetcher | 职责 | 指标示例 |
|---------|------|---------|
| `BaseIndicatorFetcher` | 基础指标 | PMI, CPI, PPI, M2 |
| `EconomicIndicatorFetcher` | 经济活动 | GDP, 工业增加值, 社零 |
| `TradeIndicatorFetcher` | 贸易数据 | 进口, 出口, 贸易差额 |
| `FinancialIndicatorFetcher` | 金融数据 | SHIBOR, LPR, 新增信贷, 外汇储备 |
| `OtherIndicatorFetcher` | 其他指标 | 失业率, 房价, 油价 |

#### FailoverAdapter (容错适配器)

```python
class FailoverAdapter(MacroAdapterProtocol):
    """
    按优先级尝试多个数据源
    主数据源失败时自动切换备用源
    """
    def __init__(self, adapters, validate_consistency=True, tolerance=0.01):
        self.adapters = adapters  # [AKShareAdapter, TushareAdapter, ...]

    def fetch(self, indicator_code, start_date, end_date):
        # 逐个尝试适配器
        for adapter in self.adapters:
            if adapter.supports(indicator_code):
                try:
                    data = adapter.fetch(indicator_code, start_date, end_date)
                    if data:
                        return data  # 成功则返回
                except Exception as e:
                    continue  # 失败则尝试下一个
        raise DataSourceUnavailableError("所有数据源都失败")
```

## 3. 当前存在的问题与改进建议

### 3.1 当前问题

1. **硬编码路由逻辑**：`fetch()` 方法中使用大量 `if-elif` 判断
2. **可扩展性差**：添加新指标需要修改多处代码
3. **缺乏配置化**：指标与 fetcher 的映射关系硬编码在代码中
4. **返回数据结构不统一**：不同 API 可能有细微差异

### 3.2 改进建议

#### 建议 1：配置化指标映射

创建指标配置表，替代硬编码：

```python
# apps/macro/infrastructure/models.py

class IndicatorMappingConfig(models.Model):
    """指标映射配置"""
    indicator_code = models.CharField(max_length=50)  # CN_GDP
    data_source = models.CharField(max_length=20)     # akshare
    fetcher_type = models.CharField(max_length=50)    # economic
    fetch_method = models.CharField(max_length=50)    # fetch_gdp
    original_unit = models.CharField(max_length=50)    # 亿元
    is_currency = models.BooleanField(default=False)
    priority = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
```

#### 建议 2：动态路由

使用配置表动态路由：

```python
class AKShareAdapter(BaseMacroAdapter):
    def fetch(self, indicator_code, start_date, end_date):
        # 从数据库获取配置
        config = IndicatorMappingConfig.objects.filter(
            indicator_code=indicator_code,
            data_source=self.source_name,
            is_active=True
        ).order_by('-priority').first()

        if not config:
            raise DataSourceUnavailableError(f"未配置指标: {indicator_code}")

        # 动态调用 fetcher 方法
        fetcher = self._get_fetcher(config.fetcher_type)
        method = getattr(fetcher, config.fetch_method)
        return method(start_date, end_date)
```

#### 建议 3：统一的 API 响应格式

创建统一的响应封装：

```python
# apps/macro/interface/dto.py

@dataclass
class ApiResponse:
    """统一 API 响应格式"""
    success: bool
    message: str = ""
    data: Any = None
    error: Optional[str] = None

    def to_dict(self):
        return asdict(self)

    @classmethod
    def success_response(cls, data=None, message="操作成功"):
        return cls(success=True, message=message, data=data)

    @classmethod
    def error_response(cls, message, error=None):
        return cls(success=False, message=message, error=error)
```

#### 建议 4：API 版本控制

支持多版本 API：

```
/api/v1/macro/indicator/{code}/
/api/v2/macro/indicator/{code}/  # 支持更多参数，返回更多字段
```

## 4. 添加新指标的完整流程

### 4.1 当前方式（硬编码）

```python
# 1. 在 AKShareAdapter.SUPPORTED_INDICATORS 添加映射
SUPPORTED_INDICATORS = {
    ...
    "CN_NEW_INDICATOR": "新指标名称",
}

# 2. 在 fetch() 方法添加路由
def fetch(self, indicator_code, start_date, end_date):
    ...
    elif indicator_code == "CN_NEW_INDICATOR":
        return self.xxx_fetcher.fetch_new_indicator(start_date, end_date)

# 3. 创建 fetcher 方法
def fetch_new_indicator(self, start_date, end_date):
    df = self.ak.macro_china_xxx()
    # 解析并返回 MacroDataPoint 列表
```

### 4.2 推荐方式（配置化）

```python
# 1. 通过 Django Admin 或 API 添加配置
IndicatorMappingConfig.objects.create(
    indicator_code="CN_NEW_INDICATOR",
    data_source="akshare",
    fetcher_type="economic",
    fetch_method="fetch_new_indicator",
    original_unit="亿元",
    is_currency=True,
    priority=10
)

# 2. 在对应的 fetcher 中实现方法（只需一次）
class EconomicIndicatorFetcher(BaseFetcher):
    def fetch_new_indicator(self, start_date, end_date):
        df = self.ak.macro_china_xxx()
        # 解析并返回 MacroDataPoint 列表
```

## 5. API 调用示例

### 5.1 获取指标数据

```bash
# 获取 GDP 数据（返回展示值：亿元）
GET /api/macro/indicator-data/?code=CN_GDP&limit=10

# 响应
{
  "success": true,
  "data": [
    {
      "id": 123,
      "code": "CN_GDP",
      "value": 1500.0,        # 展示值（亿元）
      "unit": "亿元",         # 展示单位
      "storage_value": 150000000000.0,  # 存储值（元）
      "storage_unit": "元",
      "reporting_period": "2024-01-01",
      "period_type": "Q",
      ...
    }
  ],
  "count": 10
}
```

### 5.2 手动触发数据抓取

```bash
# 抓取 GDP 数据
POST /api/macro/fetch/
Content-Type: application/json

{
  "indicators": ["CN_GDP"],
  "start_date": "2024-01-01",
  "end_date": "2024-12-31"
}

# 响应
{
  "success": true,
  "synced_count": 4,
  "skipped_count": 0,
  "errors": []
}
```

### 5.3 获取支持的指标列表

```bash
GET /api/macro/supported-indicators/

# 响应
{
  "success": true,
  "data": [
    {
      "code": "CN_GDP",
      "name": "GDP",
      "category": "增长",
      "unit": "亿元",
      "latest_value": 1500.0,
      "latest_date": "2024-01-01"
    },
    ...
  ],
  "count": 50
}
```

## 6. 总结

### 当前状态

| 方面 | 状态 |
|-----|------|
| 数据结构统一 | ✅ 已实现（通过 `_format_indicator_for_display`） |
| 单位转换 | ✅ 已实现（存储元，展示原始单位） |
| 适配器映射 | ⚠️ 硬编码，扩展性较差 |
| 配置化 | ⚠️ 部分实现（IndicatorUnitConfig） |
| API 响应格式 | ⚠️ 基本统一，但有改进空间 |

### 下一步优化建议

1. **短期**：完善 IndicatorUnitConfig，支持单位配置覆盖
2. **中期**：实现 IndicatorMappingConfig，配置化指标映射
3. **长期**：API 版本控制，支持向后兼容的升级
