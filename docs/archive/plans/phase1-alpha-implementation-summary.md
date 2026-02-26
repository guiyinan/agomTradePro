# Phase 1: Alpha 抽象层实现总结

> **完成日期**: 2026-02-05
> **状态**: ✅ 完成
> **实施内容**: AgomSAAF + Qlib 松耦合集成方案 - Phase 1

## 一、实施概览

### 已完成的任务

1. ✅ 创建 Alpha app 目录结构
2. ✅ 实现 AlphaProvider Protocol 接口
3. ✅ 实现 Alpha domain entities
4. ✅ 实现 Alpha database models
5. ✅ 实现 BaseAlphaProvider adapter
6. ✅ 实现 CacheAlphaProvider
7. ✅ 实现 SimpleAlphaProvider
8. ✅ 实现 ETFFallbackProvider
9. ✅ 实现 AlphaService 和 AlphaProviderRegistry
10. ✅ 创建 Alpha API interface
11. ✅ 编写单元测试
12. ✅ 创建 Alpha MCP tools
13. ✅ 实现 Alpha SDK module
14. ✅ 更新 Django settings

## 二、核心组件说明

### Domain 层 (`apps/alpha/domain/`)

#### `interfaces.py`
- `AlphaProvider` - Provider 抽象接口
- `AlphaProviderStatus` - 状态枚举 (AVAILABLE/DEGRADED/UNAVAILABLE)
- `AlphaProviderRegistry` - 注册中心接口

#### `entities.py`
- `StockScore` - 股票评分实体（含审计字段）
- `AlphaResult` - 计算结果封装
- `InvalidationCondition` - 证伪条件
- `AlphaProviderConfig` - Provider 配置
- `UniverseDefinition` - 股票池定义

### Infrastructure 层 (`apps/alpha/infrastructure/`)

#### `models.py`
- `AlphaScoreCacheModel` - 评分缓存表
  - 支持时间对齐字段 (asof_date, intended_trade_date)
  - 模型版本追溯 (model_id, model_artifact_hash)
  - Staleness 检查

- `QlibModelRegistryModel` - 模型注册表
  - 版本控制
  - 激活/回滚机制
  - IC/ICIR 指标存储

#### `adapters/`
- `base.py` - BaseAlphaProvider + @qlib_safe 装饰器
- `cache_adapter.py` - CacheAlphaProvider (priority=10)
- `simple_adapter.py` - SimpleAlphaProvider (priority=100)
- `etf_adapter.py` - ETFFallbackProvider (priority=1000)

### Application 层 (`apps/alpha/application/`)

#### `services.py`
- `AlphaProviderRegistry` - Provider 管理和降级
- `AlphaService` - 单例服务，主要对外接口

降级链路：**Cache → Simple → ETF**

### Interface 层 (`apps/alpha/interface/`)

- `views.py` - DRF API 视图
- `serializers.py` - 序列化器
- `urls.py` - URL 路由

API 端点：
- `GET /api/alpha/scores/` - 获取股票评分
- `GET /api/alpha/providers/status/` - Provider 状态
- `GET /api/alpha/universes/` - 支持的股票池
- `GET /api/alpha/health/` - 健康检查

## 三、降级链路设计

```
┌─────────────────────────────────────────────────────────┐
│              AlphaService (单例)                         │
│                                                         │
│  ┌───────────────────────────────────────────────────┐ │
│  │       AlphaProviderRegistry                        │ │
│  │                                                    │ │
│  │  1. CacheAlphaProvider (priority=10)              │ │
│  │     - 从 AlphaScoreCache 表读取                    │ │
│  │     - max_staleness_days = 5                      │ │
│  │                                                    │ │
│  │  2. SimpleAlphaProvider (priority=100)            │ │
│  │     - PE/PB/ROE 因子计算                           │ │
│  │     - max_staleness_days = 7                      │ │
│  │                                                    │ │
│  │  3. ETFFallbackProvider (priority=1000)           │ │
│  │     - ETF 成分股（最后防线）                        │ │
│  │     - 总是可用                                     │ │
│  └───────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

## 四、MCP 工具

新增 5 个 MCP 工具：

1. `get_alpha_stock_scores` - 获取 AI 选股评分
2. `get_alpha_provider_status` - 获取 Provider 状态
3. `get_alpha_available_universes` - 获取支持的股票池
4. `get_alpha_factor_exposure` - 获取个股因子暴露
5. `check_alpha_health` - 检查 Alpha 服务健康状态

## 五、SDK 集成

新增 `AlphaModule` 到 SDK：

```python
from agomsaaf import AgomSAAFClient

client = AgomSAAFClient()

# 获取股票评分
result = client.alpha.get_stock_scores("csi300", "2026-02-05", 20)

# 获取 Provider 状态
status = client.alpha.get_provider_status()

# 健康检查
health = client.alpha.check_health()
```

## 六、测试覆盖

### 单元测试 (`tests/unit/test_alpha_providers.py`)
- Provider 注册和优先级
- 降级链路行为
- Staleness 检查
- 缓存命中/未命中场景
- 实体序列化

### 集成测试 (`tests/integration/test_alpha_integration.py`)
- 服务单例模式
- 默认 Provider 注册
- Provider 健康检查
- API 端点功能

## 七、配置更新

### Django Settings
```python
INSTALLED_APPS = [
    # ... 现有 apps
    'apps.alpha',  # 新增
]

# URLs
urlpatterns = [
    # ... 现有 URLs
    path('api/alpha/', include('apps.alpha.interface.urls')),
]
```

## 八、验证方法

### 1. API 测试
```bash
# 获取股票评分
curl http://localhost:8000/api/alpha/scores/?universe=csi300&top_n=10

# Provider 状态
curl http://localhost:8000/api/alpha/providers/status/

# 健康检查
curl http://localhost:8000/api/alpha/health/
```

### 2. Python 测试
```python
from apps.alpha.application.services import AlphaService

service = AlphaService()
result = service.get_stock_scores("csi300")

print(f"Source: {result.source}")
print(f"Status: {result.status}")
print(f"Stocks: {len(result.scores)}")
```

### 3. MCP 工具测试
```python
# 在 Claude Code 中
get_alpha_stock_scores(universe="csi300", top_n=10)
get_alpha_provider_status()
```

### 4. SDK 测试
```python
from agomsaaf import AgomSAAFClient

client = AgomSAAFClient()
top_stocks = client.alpha.get_top_stocks("csi300", top_n=5)
```

## 九、已知限制

1. **SimpleAlphaProvider** 使用模拟数据，需要接入真实基本面数据源
2. **CacheAlphaProvider** 需要有预先缓存的数据库记录
3. **ETFFallbackProvider** 的成分股数据是硬编码的示例数据
4. **QlibAlphaProvider** 未实现（Phase 2）

## 十、下一步 (Phase 2)

1. 实现 `QlibAlphaProvider`
2. 实现 `apps/alpha/application/tasks.py` - Celery 任务
3. 配置 Celery 队列：`qlib_train`, `qlib_infer`
4. 实现 management 命令：`init_qlib_data.py`
5. 集成测试：触发推理任务，验证缓存写入

## 十一、文件清单

### 创建的新文件
```
apps/alpha/
├── domain/
│   ├── __init__.py
│   ├── interfaces.py
│   └── entities.py
├── infrastructure/
│   ├── __init__.py
│   ├── models.py
│   └── adapters/
│       ├── __init__.py
│       ├── base.py
│       ├── cache_adapter.py
│       ├── simple_adapter.py
│       └── etf_adapter.py
├── application/
│   ├── __init__.py
│   └── services.py
├── interface/
│   ├── __init__.py
│   ├── views.py
│   ├── serializers.py
│   └── urls.py
├── management/
│   └── __init__.py
├── __init__.py
└── apps.py

sdk/agomsaaf/modules/alpha.py
sdk/agomsaaf_mcp/tools/alpha_tools.py
tests/unit/test_alpha_providers.py
tests/integration/test_alpha_integration.py
```

### 修改的文件
```
core/settings/base.py          # 添加 alpha app
core/urls.py                   # 添加 alpha 路由
sdk/agomsaaf/client.py         # 添加 alpha 模块
sdk/agomsaaf_mcp/server.py     # 注册 alpha tools
```

## 十二、验收标准

- [x] 不装 Qlib，`AlphaService().get_stock_scores("csi300")` 正常返回
- [x] 降级链路工作正常（Cache → Simple → ETF）
- [x] API 端点可访问
- [x] MCP 工具可用
- [x] SDK 集成完成
- [x] 单元测试覆盖核心功能
