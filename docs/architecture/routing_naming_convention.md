# 路由命名规范 (Routing Naming Convention)

> **版本**: v1.2
> **创建日期**: 2026-02-18
> **更新日期**: 2026-02-18
> **负责**: backend-dev, ui-ux-designer
> **状态**: 已发布
> **基线数据**: ~410 个 API 端点

---

## 1. 概述

本文档定义 AgomTradePro 项目的统一路由命名规范，确保前后端协作的一致性，降低维护成本。

**基线数据**（来源：`tests/uat/reports/baseline-api-analysis-2026-02-18.md`）：
- API 路由总数量：~410 条
- 当前规范覆盖率：~100%（已符合规范）
- 需要迁移的路由：0 条

### 1.1 核心原则

1. **清晰分层**: 用户可见路由与 API 路由严格分离
2. **稳定语义**: 用户可见入口路由保持语义稳定，不含版本号或技术标识
3. **API 前缀规范**: API 路由必须包含 `/api/` 前缀（位置可变）
4. **向后兼容**: 存量路由保持稳定，优先文档化而非强制迁移
5. **新模块规范**: 新开发的模块严格遵循统一规范

---

## 2. 路由分类

### 2.1 用户可见入口路由 (Page Routes)

**定义**: 用户在浏览器地址栏看到并可能收藏的 URL

**命名规则**:
- 使用 kebab-case (小写字母 + 连字符)
- 语义化命名，反映业务功能
- 不包含技术标识（如 `v1`、`legacy`、`ajax` 等）
- 不包含 `/api/` 前缀

**URL 结构**:
```
/{module}/{resource}/{action}/
```

**示例**:
```python
# 正确
path('dashboard/', views.dashboard_view, name='dashboard')
path('my-accounts/', views.my_accounts_page, name='my-accounts')
path('my-accounts/<int:account_id>/', views.my_account_detail_page, name='my-account-detail')
path('strategy/create/', views.strategy_create, name='strategy-create')

# 错误
path('dashboard/legacy/', views.dashboard_view, name='dashboard-legacy')  # 不应包含 legacy
path('api/dashboard/', views.dashboard_view, name='api-dashboard')      # 页面路由不应有 /api/
path('strategy/v1/create/', views.strategy_create, name='strategy-create-v1')  # 用户路由不应有版本号
```

### 2.2 具体实现路由 (Implementation Routes)

**定义**: 包含版本号或内部标识的技术实现路由

**命名规则**:
- 仅在必要时使用（如 HTMX 端点、流式响应等）
- 使用版本号标识实现代际
- 推荐放在 `/api/` 下以明确标识为技术端点

**URL 结构**:
```
/api/{module}/v{version}/{resource}/
```

**示例**:
```python
# HTMX 端点
path('api/v1/summary/', views.dashboard_summary_v1, name='api-v1-summary')
path('api/v1/regime-quadrant/', views.regime_quadrant_v1, name='api-v1-regime-quadrant')

# 流式响应
path('api/server-logs/stream/', views.server_logs_stream, name='api-server-logs-stream')
```

### 2.3 API 路由 (API Routes)

**定义**: 供前端 JavaScript 或外部系统调用的数据接口

**命名规则**:
- **必须**包含 `/api/` 前缀（位置可变）
- 使用 RESTful 风格
- 使用复数形式表示资源集合
- 使用 DRF Router 自动生成标准 REST 端点

**可接受的 URL 结构**:

```
# 模式一：全局 API 前缀（推荐用于新模块）
/api/{module}/{resource}/
/api/{module}/{resource}/{id}/
/api/{module}/{resource}/{id}/{action}/

# 模式二：模块级 API 路径（存量模块可接受）
/{module}/api/{resource}/
/{module}/api/{resource}/{id}/
/{module}/api/{resource}/{id}/{action}/
```

**示例**:
```python
# 模式一：全局 API 前缀（推荐）
# core/urls.py 中定义
path('api/alpha/', include('apps.alpha.interface.urls'))
# 生成: /api/alpha/scores/, /api/alpha/coverage/

# 模式二：模块级 API 路径（存量模块）
# apps/account/interface/urls.py 中定义
path('api/portfolios/', PortfolioViewSet.as_view(), name='portfolio-list')
# 生成: /api/account/portfolios/ (canonical API 挂载)
```

**规范说明**:
- **新模块**: 必须使用模式一（全局 `/api/` 前缀）
- **存量模块**: 可保持模式二（模块级 `/api/` 路径），优先文档化而非强制迁移
- **核心 API**: 健康检查、文档等使用全局 `/api/` 前缀

---

## 3. 路由分层清晰度

### 3.1 页面路由与 API 路由边界

| 特性 | 页面路由 | API 路由 |
|------|---------|----------|
| URL 前缀 | 无 `/api/` | 必须有 `/api/` |
| 返回内容 | HTML 完整页面 | JSON 数据 |
| 命名风格 | kebab-case | RESTful 资源名 |
| 视图类型 | TemplateView / 函数视图 | APIView / ViewSet |
| 用户可见 | 是 | 否（开发者工具可见） |

### 3.2 路由名称规范

**格式**: `{module}:{action}` 或 `{app_name}:{name}`

```python
# 页面路由命名
path('dashboard/', views.dashboard_view, name='dashboard')           # core:dashboard
path('my-accounts/', views.my_accounts_page, name='my-accounts')    # simulated_trading:my-accounts

# API 路由命名
path('api/accounts/', AccountListAPIView.as_view(), name='account-list')  # simulated_trading:account-list
path('api/alpha/scores/', views.get_stock_scores, name='get_stock_scores')  # alpha:get_stock_scores
```

---

## 4. 命名冲突解决策略

### 4.1 `/dashboard/` 与 legacy dashboard 问题

**现状**: `apps/dashboard/interface/urls.py` 中存在：
```python
path('', views.dashboard_entry, name='index'),
path('legacy/', views.dashboard_view, name='legacy'),
```

**问题**:
- `dashboard_entry` 是新实现，`dashboard_view` 是旧实现
- 用户不应看到 `legacy` 这样的技术标识
- 两个路由功能相同，造成混淆

**解决方案**:

1. **立即行动**: 将 `dashboard_entry` 设为唯一用户入口
   ```python
   path('', views.dashboard_entry, name='index'),  # 用户入口
   path('internal/legacy/', views.dashboard_view, name='internal-legacy'),  # 内部调试用
   ```

2. **后续计划**: 完全移除 `legacy` 实现，仅保留 `dashboard_entry`

3. **临时兼容**: 如需保留旧实现，使用内部路径
   ```python
   path('__internal/legacy/', views.dashboard_view, name='internal-legacy')
   ```

### 4.2 路由别名使用规范

**适用场景**:
- 重定向到新路由
- 保持向后兼容的旧 URL

**规范**:
```python
# 正确：使用 RedirectView 处理旧 URL
path('old-dashboard/', RedirectView.as_view(url='/dashboard/', permanent=True), name='old-dashboard-redirect')

# 错误：两个不同视图指向同一功能
path('dashboard/', views.new_dashboard, name='dashboard')
path('dashboard/v1/', views.old_dashboard, name='dashboard-v1')  # 不应同时暴露给用户
```

---

## 5. 实施计划

### 5.1 存量路由梳理清单

#### 核心路由 (core/urls.py)

| 路由 | 类型 | 状态 | 说明 |
|------|------|------|------|
| `/` | 页面 | 规范 | 首页入口 |
| `/health/` | API | 需调整 | 应改为 `/api/health/` |
| `/policy/dashboard/` | 页面 | 需调整 | 应迁移到 `/policy/` 下 |
| `/asset-analysis/screen/` | 页面 | 需调整 | 应迁移到 `/asset-analysis/` 下 |
| `/decision/workspace/` | 页面 | 需调整 | 应迁移到 `/decision/` 下 |
| `/ops/` | 页面 | 规范 | 运营中心 |
| `/docs/` | 页面 | 规范 | 文档页面 |
| `/admin/` | 页面 | 规范 | Django Admin |

#### Dashboard 路由

| 路由 | 类型 | 状态 | 说明 |
|------|------|------|------|
| `/dashboard/` | 页面 | 规范 | 主入口 |
| legacy dashboard path | 页面 | 已治理 | 不再作为用户可见入口 |
| `/dashboard/position/<code>/` | HTMX | 需调整 | 应改为 `/api/dashboard/position/` |
| `/api/dashboard/allocation/` | API | 规范 | canonical dashboard API |
| `/api/dashboard/v1/*` | API | 规范 | 版本化 API |
| `/dashboard/alpha/*` | HTMX | 需调整 | 应改为 `/api/dashboard/alpha/*` |

#### 模块路由状态

| 模块 | API 前缀 | 页面路由 | 状态 |
|------|----------|----------|------|
| `alpha` | `/api/alpha/` | 无 | 规范 |
| `regime` | `/api/regime/` | `/regime/dashboard/` | 已调整 |
| `strategy` | `/api/strategy/` | `/strategy/` | 规范 |
| `simulated_trading` | `/api/simulated-trading/` | `/simulated-trading/*` | 规范 |
| `policy` | `/api/policy/` | `policy/api` | 规范 |
| `factor` | `/api/factor/` | `factor/api` | 规范 |
| `rotation` | `/api/rotation/` | `rotation/api` | 规范 |
| `hedge` | `/api/hedge/` | `hedge/api` | 规范 |

### 5.2 迁移步骤

#### Phase 1: 核心路由规范化 (P0)

1. **调整健康检查路由**
   ```python
   # 修改前
   path('health/', health_view, name='health'),

   # 修改后
   path('api/health/', health_view, name='health'),
   ```

2. **收敛 dashboard legacy 路由**
   ```python
   # 修改前
   path('legacy/', views.dashboard_view, name='legacy'),

   # 修改后
   # 方案A: 移除
   # 方案B: 改为内部路径
   path('__internal/legacy/', views.dashboard_view, name='internal-legacy'),
   ```

3. **调整 HTMX 端点到 API 路由**
   ```python
   # 修改前
   path('position/<str:asset_code>/', views.position_detail_htmx, name='position_detail'),

   # 修改后
   path('api/dashboard/position/<str:asset_code>/', views.position_detail_htmx, name='api_position_detail'),
   ```

#### Phase 2: 模块路由规范化 (P1)

1. **统一 API 路由结构**
   - 目标结构: `/api/{module}/{resource}/`
   - 现有兼容别名: `/regime/api/`，canonical 为 `/api/regime/`

2. **调整模块页面路由**
   - 将嵌套在 core 中的页面路由迁移到各模块

#### Phase 3: 文档更新 (P1)

1. 更新 `docs/testing/api/API_REFERENCE.md`
2. 更新 OpenAPI 规范
3. 更新前端调用代码

### 5.3 影响范围评估

| 变更类型 | 影响范围 | 风险等级 | 缓解措施 |
|---------|----------|----------|----------|
| API 路由加 `/api/` 前缀 | 前端 AJAX 调用 | 中 | 保持旧路由重定向 |
| 移除 legacy 路由 | 用户书签 | 低 | 提前公告 + 重定向 |
| HTMX 端点迁移 | 前端模板 | 中 | 全局查找替换 |

---

## 6. 大规模迁移策略

> **基线数据**: ~410 个 API 端点需要从 `/{module}/api/` 模式迁移到 `/api/{module}/` 模式

### 6.1 迁移原则

1. **分批迁移**: 按模块分批进行，每次迁移一个模块
2. **双路由过渡**: 新旧路由并存一个版本周期
3. **向后兼容**: 使用 RedirectView 保持旧路由可用
4. **测试先行**: 每个模块迁移前后运行测试验证

### 6.2 迁移模式

#### 模式一：双路由过渡（推荐）

```python
# 旧路由（标记为 deprecated，保留兼容）
path('account/api/portfolios/', OldPortfolioAPIView.as_view(), name='old-account-portfolios'),

# 新路由（推荐使用）
path('api/account/portfolios/', PortfolioAPIView.as_view(), name='account-portfolios'),
```

#### 模式二：直接替换（仅限新功能）

对于新开发的 API 端点，直接使用规范模式：
```python
path('api/new-feature/', NewFeatureAPIView.as_view(), name='new-feature')
```

### 6.3 模块迁移优先级

基于基线分析，建议按以下优先级迁移：

| 优先级 | 模块 | API 端点数 | 风险等级 | 说明 |
|--------|------|-----------|----------|------|
| P0 | account | ~45 | 高 | 用户核心功能，需优先处理 |
| P1 | simulated_trading | ~30 | 高 | 交易功能，影响大 |
| P1 | strategy | ~25 | 中 | 策略系统 |
| P2 | regime | ~15 | 低 | 只读 API |
| P2 | policy | ~20 | 中 | 政策管理 |
| P3 | 其他模块 | ~275 | 中低 | 按需处理 |

### 6.4 迁移实施步骤

#### Step 1: 模块路由分析

```bash
# 分析模块的 API 路由
python scripts/analyze_module_routes.py --module account
```

输出：
- 当前 API 路由清单
- 需要迁移的路由列表
- 前端调用点清单

#### Step 2: 后端路由迁移

1. 在模块的 `urls.py` 中添加新路由
2. 保留旧路由并添加 deprecation 警告
3. 运行测试验证功能正常

```python
# apps/account/interface/urls.py

# 新路由（推荐）
path('api/portfolios/', PortfolioAPIView.as_view(), name='api-portfolios'),

# 旧路由（兼容）
path('api/portfolios/', lambda r: HttpResponseDeprecated(
    "This endpoint is deprecated. Use /api/account/portfolios/ instead.",
    status=301
), name='old-portfolios'),
```

#### Step 3: 前端调用更新

搜索并替换前端调用：
```bash
# 搜索所有调用点
grep -r "account/api/" templates/ static/js/

# 替换为新路由
# fetch('/api/account/portfolios/')
```

#### Step 4: 测试验证

```bash
# 运行 API 合规性测试
pytest tests/uat/test_api_naming_compliance.py -v

# 运行模块测试
pytest tests/account/ -v
```

#### Step 5: 移除旧路由

经过一个稳定版本后，移除旧路由：
```python
# 移除旧路由
# path('account/api/portfolios/', ...)  # 已删除
```

### 6.5 回滚计划

如果迁移出现问题：

1. **立即回滚**: 从 git 恢复到迁移前的版本
2. **启用旧路由**: 临时恢复旧路由，标记为 deprecated
3. **分析问题**: 使用日志分析失败原因
4. **修复后重试**: 解决问题后重新迁移

---

## 7. 验收标准

1. 所有 API 路由包含 `/api/` 前缀（位置可以是全局或模块级）
2. 用户可见路由不含 `legacy`、`v1` 等技术标识
3. 文档与实际路由一致
4. 无功能重复的冗余路由
5. 新模块严格遵循全局 `/api/` 前缀规范
6. 前后端团队都认可该规范

---

## 8. 附录

### 7.1 路由检查脚本

使用 `scripts/scan_urls_api.py` 检查路由规范性：

```bash
python scripts/scan_urls_api.py
```

### 8.2 相关文档

- [API 参考文档](../../testing/api/API_REFERENCE.md)
- [开发快速参考](../../development/quick-reference.md)
- [UI/UX 改进 PRD](../../plans/ui-ux-improvement-prd-2026-02-18.md)
- [API 路由基线分析报告](../../tests/uat/reports/baseline-api-analysis-2026-02-18.md)
- [API 路由治理计划](../../fixes/api-routing-governance-plan-2026-02-18.md)

---

**维护**: backend-dev
**最后更新**: 2026-02-18 (v1.2 - 采用务实的双模式规范)
