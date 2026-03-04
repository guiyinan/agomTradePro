# API 路由清单 - AgomSAAF

> 生成日期：2026-03-04
> 目的：M0 基线证据包

---

## 1. 路由规范现状

### 1.1 规范定义
- **新规范**：`/api/{module}/{resource}/`
- **旧模式**：`/{module}/api/{resource}/`

### 1.2 并存情况
当前系统存在新旧路由并存，需要迁移：

| 模块 | 新规范路由 | 旧模式路由 | 状态 |
|------|-----------|-----------|------|
| account | `/api/account/` | `/account/api/` | 并存 |
| simulated_trading | `/api/simulated-trading/` | `/simulated-trading/api/` | 并存 |
| strategy | `/api/strategy/` | `/strategy/api/` | 并存 |
| regime | `/api/regime/` | `/regime/api/` | 并存 |
| policy | `/api/policy/` | `/policy/api/` | 并存 |
| signal | `/api/signal/` | `/signal/api/` | 并存 |
| macro | `/api/macro/` | `/macro/api/` | 并存 |
| filter | `/api/filter/` | `/filter/api/` | 并存 |
| backtest | `/api/backtest/` | `/backtest/api/` | 并存 |
| audit | `/api/audit/` | `/audit/api/` | 并存 |
| equity | `/api/equity/` | `/equity/api/` | 并存 |
| fund | `/api/fund/` | `/fund/api/` | 并存 |
| asset_analysis | `/api/asset-analysis/` | `/asset-analysis/api/` | 并存 |
| sector | `/api/sector/` | `/sector/api/` | 并存 |
| ai_provider | `/api/ai/` | `/ai/api/` | 并存 |
| prompt | `/api/prompt/` | `/prompt/api/` | 并存 |
| realtime | `/api/realtime/` | `/realtime/api/` | 并存 |
| factor | `/api/factor/` | `/factor/api/` | 并存 |
| rotation | `/api/rotation/` | `/rotation/api/` | 并存 |
| hedge | `/api/hedge/` | `/hedge/api/` | 并存 |
| sentiment | `/api/sentiment/` | `/sentiment/api/` | 并存 |
| alpha | `/api/alpha/` | - | 仅新规范 |
| task_monitor | `/api/system/` | - | 仅新规范 |

---

## 2. 核心路由（Core）

| 路径 | 方法 | 视图 | 说明 |
|------|------|------|------|
| `/` | GET | `index_view` | 首页 |
| `/api/health/` | GET | `health_view` | 健康检查 |
| `/chat-example/` | GET | `chat_example_view` | 聊天示例 |
| `/docs/` | GET | `docs_view` | 文档首页 |
| `/docs/<doc_slug>/` | GET | `docs_view` | 文档详情 |
| `/asset-analysis/screen/` | GET | `asset_screen_view` | 资产筛选 |
| `/decision/workspace/` | GET | `decision_workspace_view` | 决策工作台 |
| `/ops/` | GET | `ops_center_view` | 运维中心 |

---

## 3. API 文档路由

| 路径 | 方法 | 视图 | 说明 |
|------|------|------|------|
| `/api/schema/` | GET | `SpectacularAPIView` | OpenAPI Schema |
| `/api/docs/` | GET | `SpectacularSwaggerView` | Swagger UI |
| `/api/redoc/` | GET | `SpectacularRedocView` | ReDoc |

---

## 4. Account 模块

### 4.1 页面路由
| 路径 | 方法 | 视图 | 说明 |
|------|------|------|------|
| `/account/register/` | GET/POST | `register_view` | 注册 |
| `/account/login/` | GET/POST | `login_view` | 登录 |
| `/account/logout/` | POST | `logout_view` | 登出 |
| `/account/profile/` | GET | `profile_view` | 个人资料 |
| `/account/settings/` | GET | `settings_view` | 设置 |
| `/account/capital-flow/` | GET | `capital_flow_view` | 资金流向 |
| `/account/backtest/<id>/apply/` | POST | `apply_backtest_results_view` | 应用回测结果 |

### 4.2 管理员路由
| 路径 | 方法 | 视图 | 说明 |
|------|------|------|------|
| `/account/admin/users/` | GET | `user_management_view` | 用户管理 |
| `/account/admin/tokens/` | GET | `token_management_view` | Token管理 |
| `/account/admin/tokens/<id>/rotate/` | POST | `rotate_user_token_view` | 轮换Token |
| `/account/admin/tokens/<id>/revoke/` | POST | `revoke_user_token_view` | 撤销Token |
| `/account/admin/users/<id>/approve/` | POST | `approve_user_view` | 批准用户 |
| `/account/admin/users/<id>/reject/` | POST | `reject_user_view` | 拒绝用户 |
| `/account/admin/users/<id>/role/` | POST | `set_user_role_view` | 设置角色 |
| `/account/admin/users/<id>/reset/` | POST | `reset_user_status_view` | 重置状态 |
| `/account/admin/settings/` | GET | `system_settings_view` | 系统设置 |

### 4.3 API 路由
| 路径 | 方法 | 视图 | 说明 |
|------|------|------|------|
| `/account/api/profile/` | GET | `AccountProfileView` | 用户资料API |
| `/account/api/health/` | GET | `AccountHealthView` | 健康检查API |
| `/account/api/portfolios/` | GET/POST | `PortfolioViewSet` | 投资组合CRUD |
| `/account/api/positions/` | GET/POST | `PositionViewSet` | 持仓CRUD |
| `/account/api/transactions/` | GET/POST | `TransactionViewSet` | 交易CRUD |
| `/account/api/capital-flows/` | GET/POST | `CapitalFlowViewSet` | 资金流CRUD |
| `/account/api/assets/` | GET | `AssetMetadataViewSet` | 资产元数据 |
| `/account/api/volatility/` | GET | `portfolio_volatility_api_view` | 波动率API |
| `/account/api/categories/` | GET | `AssetCategoryViewSet` | 资产分类 |
| `/account/api/currencies/` | GET | `CurrencyViewSet` | 货币列表 |
| `/account/api/exchange-rates/` | GET | `ExchangeRateViewSet` | 汇率 |
| `/account/api/portfolios/<id>/allocation/` | GET | `PortfolioAllocationView` | 组合配置 |

---

## 5. Audit 模块

### 5.1 API 路由
| 路径 | 方法 | 视图 | 说明 |
|------|------|------|------|
| `/audit/api/reports/generate/` | POST | `GenerateAttributionReportView` | 生成归因报告 |
| `/audit/api/summary/` | GET | `AuditSummaryView` | 审计摘要 |
| `/audit/api/attribution-chart-data/<id>/` | GET | `AttributionChartDataView` | 归因图表数据 |
| `/audit/api/indicator-performance/<code>/` | GET | `IndicatorPerformanceDetailView` | 指标表现详情 |
| `/audit/api/indicator-performance-data/<id>/` | GET | `IndicatorPerformanceChartDataView` | 指标表现图表 |
| `/audit/api/validate-all-indicators/` | POST | `ValidateAllIndicatorsView` | 验证所有指标 |
| `/audit/api/update-threshold/` | POST | `UpdateThresholdView` | 更新阈值 |
| `/audit/api/threshold-validation-data/<id>/` | GET | `ThresholdValidationDataView` | 阈值验证数据 |
| `/audit/api/run-validation/` | POST | `RunValidationView` | 运行验证 |
| `/audit/api/operation-logs/` | GET | `OperationLogListView` | 操作日志列表 |
| `/audit/api/operation-logs/export/` | GET | `OperationLogExportView` | 导出日志 |
| `/audit/api/operation-logs/stats/` | GET | `OperationLogStatsView` | 日志统计 |
| `/audit/api/operation-logs/<id>/` | GET | `OperationLogDetailView` | 日志详情 |
| `/audit/api/internal/operation-logs/` | POST | `OperationLogIngestView` | 内部日志写入 |

### 5.2 页面路由
| 路径 | 方法 | 视图 | 说明 |
|------|------|------|------|
| `/audit/page/` | GET | `AuditPageView` | 审计页面 |
| `/audit/reports/` | GET | `AuditPageView` | 报告列表 |
| `/audit/reports/<id>/` | GET | `AttributionDetailView` | 报告详情 |
| `/audit/indicator-performance/` | GET | `IndicatorPerformancePageView` | 指标表现页 |
| `/audit/threshold-validation/` | GET | `ThresholdValidationPageView` | 阈值验证页 |
| `/audit/review/` | GET | `AuditPageView` | 审核页 |
| `/audit/operation-logs/` | GET | `OperationLogsAdminPageView` | 管理员日志页 |
| `/audit/my-logs/` | GET | `MyOperationLogsPageView` | 我的日志页 |

---

## 6. Policy 模块

### 6.1 API 路由（api_urls.py）
| 路径 | 方法 | 视图 | 说明 |
|------|------|------|------|
| `/api/policy/status/` | GET | `PolicyStatusView` | 政策状态 |
| `/api/policy/events/` | GET | `PolicyEventListView` | 事件列表 |
| `/api/policy/events/<date>/` | GET | `PolicyEventDetailView` | 事件详情 |
| `/api/policy/audit/queue/` | GET | `AuditQueueView` | 审核队列 |
| `/api/policy/audit/review/<id>/` | POST | `ReviewPolicyItemView` | 审核项 |
| `/api/policy/audit/bulk_review/` | POST | `BulkReviewView` | 批量审核 |
| `/api/policy/audit/auto_assign/` | POST | `AutoAssignAuditsView` | 自动分配 |
| `/api/policy/workbench/bootstrap/` | GET | `WorkbenchBootstrapView` | 工作台引导 |
| `/api/policy/workbench/fetch/` | POST | `WorkbenchFetchView` | 工作台获取 |
| `/api/policy/workbench/summary/` | GET | `WorkbenchSummaryView` | 工作台摘要 |
| `/api/policy/workbench/items/` | GET | `WorkbenchItemsView` | 工作台项目 |
| `/api/policy/workbench/items/<id>/` | GET | `WorkbenchItemDetailView` | 项目详情 |
| `/api/policy/workbench/items/<id>/approve/` | POST | `ApproveEventView` | 批准 |
| `/api/policy/workbench/items/<id>/reject/` | POST | `RejectEventView` | 拒绝 |
| `/api/policy/workbench/items/<id>/rollback/` | POST | `RollbackEventView` | 回滚 |
| `/api/policy/workbench/items/<id>/override/` | POST | `OverrideEventView` | 覆盖 |
| `/api/policy/sentiment-gate/state/` | GET | `SentimentGateStateView` | 情感门状态 |
| `/api/policy/ingestion-config/` | GET/PUT | `IngestionConfigView` | 采集配置 |
| `/api/policy/sentiment-gate-config/` | GET/PUT | `SentimentGateConfigView` | 情感门配置 |
| `/api/policy/rss/sources/` | CRUD | `RSSSourceConfigViewSet` | RSS源配置 |
| `/api/policy/rss/logs/` | GET | `RSSFetchLogViewSet` | RSS日志 |
| `/api/policy/rss/keywords/` | CRUD | `PolicyLevelKeywordViewSet` | 关键词 |

---

## 7. 其他模块路由概览

### 7.1 Regime 模块
- 路由文件：`apps/regime/interface/urls.py`
- 挂载：`/regime/` 和 `/api/regime/`

### 7.2 Macro 模块
- 路由文件：`apps/macro/interface/urls.py`
- 挂载：`/macro/` 和 `/api/macro/`

### 7.3 Signal 模块
- 路由文件：`apps/signal/interface/urls.py`
- 挂载：`/signal/` 和 `/api/signal/`

### 7.4 Backtest 模块
- 路由文件：`apps/backtest/interface/urls.py`
- 挂载：`/backtest/` 和 `/api/backtest/`

### 7.5 Filter 模块
- 路由文件：`apps/filter/interface/urls.py`
- 挂载：`/filter/` 和 `/api/filter/`

### 7.6 AI Provider 模块
- 路由文件：`apps/ai_provider/interface/urls.py`
- 挂载：`/ai/` 和 `/api/ai/`

### 7.7 Prompt 模块
- 路由文件：`apps/prompt/interface/urls.py`
- 挂载：`/prompt/` 和 `/api/prompt/`

### 7.8 Sector 模块
- 路由文件：`apps/sector/interface/urls.py`
- 挂载：`/sector/` 和 `/api/sector/`

### 7.9 Equity 模块
- 路由文件：`apps/equity/interface/urls.py`
- 挂载：`/equity/` 和 `/api/equity/`

### 7.10 Fund 模块
- 路由文件：`apps/fund/interface/urls.py`
- 挂载：`/fund/` 和 `/api/fund/`

### 7.11 Asset Analysis 模块
- 路由文件：`apps/asset_analysis/interface/urls.py`
- 挂载：`/asset-analysis/` 和 `/api/asset-analysis/`

### 7.12 Simulated Trading 模块
- 路由文件：`apps/simulated_trading/interface/urls.py`
- 挂载：`/simulated-trading/` 和 `/api/simulated-trading/`

### 7.13 Strategy 模块
- 路由文件：`apps/strategy/interface/urls.py`
- 挂载：`/strategy/` 和 `/api/strategy/`

### 7.14 Realtime 模块
- 路由文件：`apps/realtime/interface/urls.py`
- 挂载：`/realtime/` 和 `/api/realtime/`

### 7.15 Dashboard 模块
- 路由文件：`apps/dashboard/interface/urls.py`
- 挂载：`/dashboard/`

### 7.16 Events 模块
- 路由文件：`apps/events/interface/urls.py`
- 挂载：`/events/`

### 7.17 Decision Rhythm 模块
- 路由文件：`apps/decision_rhythm/interface/urls.py`
- 挂载：根路由

### 7.18 Beta Gate 模块
- 路由文件：`apps/beta_gate/interface/urls.py`
- 挂载：根路由

### 7.19 Alpha Trigger 模块
- 路由文件：`apps/alpha_trigger/interface/urls.py`
- 挂载：根路由

### 7.20 Alpha 模块
- 路由文件：`apps/alpha/interface/urls.py`
- 挂载：`/api/alpha/`（仅新规范）

### 7.21 Factor 模块
- 路由文件：`apps/factor/interface/urls.py` 和 `apps/factor/interface/api_urls.py`
- 挂载：`/factor/` 和 `/api/factor/`

### 7.22 Rotation 模块
- 路由文件：`apps/rotation/interface/urls.py` 和 `apps/rotation/interface/api_urls.py`
- 挂载：`/rotation/` 和 `/api/rotation/`

### 7.23 Hedge 模块
- 路由文件：`apps/hedge/interface/urls.py` 和 `apps/hedge/interface/api_urls.py`
- 挂载：`/hedge/` 和 `/api/hedge/`

### 7.24 Sentiment 模块
- 路由文件：`apps/sentiment/interface/urls.py` 和 `apps/sentiment/interface/api_urls.py`
- 挂载：`/sentiment/` 和 `/api/sentiment/`

### 7.25 Task Monitor 模块
- 路由文件：`apps/task_monitor/interface/urls.py`
- 挂载：`/api/system/`

---

## 8. 管理后台路由

| 路径 | 方法 | 视图 | 说明 |
|------|------|------|------|
| `/admin/` | GET | Django Admin | 管理后台 |
| `/admin/server-logs/` | GET | `server_logs_page` | 服务器日志页 |
| `/admin/server-logs/stream/` | GET | `server_logs_stream` | 日志流 |
| `/admin/server-logs/export/` | GET | `server_logs_export` | 日志导出 |
| `/admin/docs/manage/` | GET | `docs_manage` | 文档管理 |
| `/admin/docs/edit/` | GET/POST | `doc_edit` | 创建文档 |
| `/admin/docs/edit/<id>/` | GET/POST | `doc_edit` | 编辑文档 |
| `/admin/docs/delete/<id>/` | POST | `doc_delete` | 删除文档 |
| `/admin/docs/export/<id>/md/` | GET | `doc_export_markdown` | 导出MD |
| `/admin/docs/export/` | GET | `doc_export_all` | 全部导出 |
| `/admin/docs/import/` | POST | `doc_import` | 导入文档 |

---

## 9. 统计

- **总模块数**：28
- **URL配置文件**：33（28个urls.py + 5个api_urls.py）
- **新旧路由并存模块**：21
- **仅新规范模块**：2（alpha, task_monitor）
- **旧页面重定向**：3（policy-dashboard, sentiment-dashboard, sentiment-analyze）

---

## 10. 迁移建议

1. **Phase 1**：为旧路由添加 `Deprecation` Header
2. **Phase 2**：发布迁移文档和SDK升级说明
3. **Phase 3**：设置兼容期（如3个月）
4. **Phase 4**：下线旧路由

---

*此文档作为M0基线证据包的一部分，用于后续路由治理对比。*
