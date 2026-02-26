# API 路由治理计划

> **创建日期**: 2026-02-18
> **负责**: backend-dev
> **优先级**: P0
> **状态**: 执行中

---

## 1. 治理目标

1. 所有 API 路由必须有显式 `/api/` 前缀
2. 页面路由与 API 路由清晰分离
3. 统一命名风格（kebab-case）
4. 无功能重复的冗余路由

---

## 2. 存量路由梳理

### 2.1 核心路由 (core/urls.py)

| 路由 | 类型 | 状态 | 治理方案 |
|------|------|------|----------|
| `/health/` | API | 需调整 | 改为 `/api/health/` |
| `/policy/dashboard/` | 页面 | 需调整 | 保持（向后兼容） |
| `/asset-analysis/screen/` | 页面 | 需调整 | 保持（向后兼容） |
| `/decision/workspace/` | 页面 | 需调整 | 保持（向后兼容） |
| `/ops/` | 页面 | 规范 | 无需调整 |
| `/docs/` | 页面 | 规范 | 无需调整 |

### 2.2 Dashboard 路由

| 路由 | 类型 | 状态 | 治理方案 |
|------|------|------|----------|
| `/dashboard/legacy/` | 页面 | 需治理 | 改为 `__internal/legacy/` 或移除 |
| `/dashboard/position/<code>/` | HTMX/API | 需调整 | 改为 `/api/dashboard/position/` |
| `/dashboard/positions/` | HTMX/API | 需调整 | 改为 `/api/dashboard/positions/` |
| `/dashboard/api/allocation/` | API | 需调整 | 改为 `/api/dashboard/allocation/` |
| `/dashboard/api/performance/` | API | 需调整 | 改为 `/api/dashboard/performance/` |
| `/dashboard/api/v1/*` | API | 规范 | 保持 |
| `/dashboard/alpha/stocks/` | HTMX | 需调整 | 改为 `/api/dashboard/alpha/stocks/` |
| `/dashboard/api/provider-status/` | API | 规范 | 保持 |
| `/dashboard/api/coverage/` | API | 规范 | 保持 |
| `/dashboard/api/ic-trends/` | API | 规范 | 保持 |

### 2.3 模块路由状态

#### 需要治理的模块

| 模块 | 当前结构 | 目标结构 | 变更类型 |
|------|----------|----------|----------|
| `realtime` | `/realtime/prices/` | `/api/realtime/prices/` | 加 `/api/` 前缀 |
| `realtime` | `/realtime/poll/` | `/api/realtime/poll/` | 加 `/api/` 前缀 |
| `realtime` | `/realtime/health/` | `/api/realtime/health/` | 加 `/api/` 前缀 |
| `fund` | `/fund/multidim-screen/` | `/api/fund/multidim-screen/` | 加 `/api/` 前缀 |
| `events` | `/events/publish/` | `/api/events/publish/` | 加 `/api/` 前缀 |
| `events` | `/events/query/` | `/api/events/query/` | 加 `/api/` 前缀 |
| `events` | `/events/metrics/` | `/api/events/metrics/` | 加 `/api/` 前缀 |
| `events` | `/events/status/` | `/api/events/status/` | 加 `/api/` 前缀 |
| `events` | `/events/replay/` | `/api/events/replay/` | 加 `/api/` 前缀 |

#### 规范的模块

| 模块 | API 路由结构 | 状态 |
|------|-------------|------|
| `alpha` | `/api/alpha/*` | 规范 |
| `regime` | `/regime/api/*` | 需调整为 `/api/regime/*` |
| `strategy` | `/strategy/api/*` | 需调整为 `/api/strategy/*` |
| `simulated_trading` | `/simulated-trading/api/*` | 规范 |
| `policy` | `/policy/api/*` | 需调整为 `/api/policy/*` |
| `factor` | `/factor/api/*` | 规范 |
| `rotation` | `/rotation/api/*` | 规范 |
| `hedge` | `/hedge/api/*` | 规范 |
| `macro` | `/macro/api/*` | 规范 |
| `signal` | `/signal/api/*` | 需调整为 `/api/signal/*` |
| `equity` | `/equity/api/*` | 规范 |
| `backtest` | `/backtest/api/*` | 规范 |
| `audit` | `/audit/api/*` | 规范 |
| `account` | `/account/api/*` | 规范 |

---

## 3. 治理方案

### 3.1 Phase 1: 核心路由调整

#### core/urls.py

```python
# 修改前
path('health/', health_view, name='health'),

# 修改后
path('api/health/', health_view, name='health'),
```

#### apps/dashboard/interface/urls.py

```python
# 1. 移除 legacy 路由或改为内部路径
# 修改前
path('legacy/', views.dashboard_view, name='legacy'),

# 修改后（方案A：移除）
# 删除该行

# 修改后（方案B：内部路径）
path('__internal/legacy/', views.dashboard_view, name='internal-legacy'),

# 2. HTMX 端点迁移到 API 路由
# 修改前
path('position/<str:asset_code>/', views.position_detail_htmx, name='position_detail'),
path('positions/', views.positions_list_htmx, name='positions_list'),

# 修改后
path('api/dashboard/position/<str:asset_code>/', views.position_detail_htmx, name='api_position_detail'),
path('api/dashboard/positions/', views.positions_list_htmx, name='api_positions_list'),

# 3. 统一 API 命名
# 修改前
path('api/allocation/', views.allocation_chart_htmx, name='allocation_api'),
path('api/performance/', views.performance_chart_htmx, name='performance_api'),

# 修改后（保持规范，已是正确格式）
# 无需调整
```

### 3.2 Phase 2: 模块路由调整

#### apps/realtime/interface/urls.py

```python
# 修改前
path("prices/", RealtimePriceView.as_view(), name="price-list"),
path("prices/<str:asset_code>/", SingleAssetPriceView.as_view(), name="price-detail"),
path("poll/", PricePollingTriggerView.as_view(), name="trigger-poll"),
path("health/", HealthCheckView.as_view(), name="health-check"),

# 修改后
path("api/prices/", RealtimePriceView.as_view(), name="price-list"),
path("api/prices/<str:asset_code>/", SingleAssetPriceView.as_view(), name="price-detail"),
path("api/poll/", PricePollingTriggerView.as_view(), name="trigger-poll"),
path("api/health/", HealthCheckView.as_view(), name="health-check"),
```

#### apps/fund/interface/urls.py

```python
# 修改前
path('multidim-screen/', FundMultiDimScreenAPIView.as_view(), name='multidim_screen'),

# 修改后
path('api/multidim-screen/', FundMultiDimScreenAPIView.as_view(), name='multidim_screen'),
```

#### apps/events/interface/urls.py

```python
# 修改前
path('publish/', views.EventPublishView.as_view(), name='publish'),
path('query/', views.EventQueryView.as_view(), name='query'),
path('metrics/', views.EventMetricsView.as_view(), name='metrics'),
path('status/', views.EventBusStatusView.as_view(), name='status'),
path('replay/', views.EventReplayView.as_view(), name='replay'),

# 修改后
path('api/publish/', views.EventPublishView.as_view(), name='publish'),
path('api/query/', views.EventQueryView.as_view(), name='query'),
path('api/metrics/', views.EventMetricsView.as_view(), name='metrics'),
path('api/status/', views.EventBusStatusView.as_view(), name='status'),
path('api/replay/', views.EventReplayView.as_view(), name='replay'),
```

### 3.3 Phase 3: API 路由结构调整

对于以下模块，需要将 `/{module}/api/` 结构调整为 `/api/{module}/`：

- `regime`: `/regime/api/` → `/api/regime/`
- `strategy`: `/strategy/api/` → `/api/strategy/`
- `policy`: `/policy/api/` → `/api/policy/`
- `signal`: `/signal/api/` → `/api/signal/`

**注意**: 这些结构调整需要同时修改 `core/urls.py` 中的路由包含方式和模块的 `urls.py` 文件。

---

## 4. 影响范围评估

### 4.1 前端调用影响

需要搜索并更新的前端文件：
- 模板文件中的 AJAX 调用
- JavaScript 中的 fetch/axios 调用
- HTMX 属性中的 `hx-get`/`hx-post` 等

### 4.2 测试影响

需要更新的测试用例：
- API 测试中的 URL
- 集成测试中的端点

### 4.3 文档影响

需要更新的文档：
- `docs/testing/api/API_REFERENCE.md`
- `docs/testing/api/openapi.yaml`
- `docs/testing/api/openapi.json`

---

## 5. 执行步骤

### Step 1: 修改后端路由文件

### Step 2: 更新前端调用

### Step 3: 更新测试用例

### Step 4: 更新 API 文档

### Step 5: 运行测试验证

---

## 6. 向后兼容策略

对于需要保留旧 URL 的场景，使用 Django 的 `RedirectView`:

```python
from django.views.generic import RedirectView

# 旧 URL 重定向到新 URL
path('health/', RedirectView.as_view(url='/api/health/', permanent=True), name='health-redirect'),
```

---

**维护**: backend-dev
**最后更新**: 2026-02-18
