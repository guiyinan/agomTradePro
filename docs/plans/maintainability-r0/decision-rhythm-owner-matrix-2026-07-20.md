# R0 Decision Rhythm Owner 矩阵

> 状态：已冻结
> R3 第一阶段：只拆无状态 Domain/Application/composition
> ORM 决策：所有现有模型暂留 `decision_rhythm` app identity，R3 第一阶段不做 state migration

## 1. 文件族归属

| 当前文件/能力族 | 目标 owner | 第一阶段动作 |
|---|---|---|
| `rhythm_entities.py`、`rhythm_services.py`、quota/cooldown/request/response 用例与仓储 | `decision_rhythm` | 原位保留，作为 quota/cooldown 内核 |
| `advisor_*`、`exit_advisors.py`、advisor sheet/API | `advisor` | 迁无状态服务与 facade；旧 import 代理 |
| `decision_execution_use_cases.py`、approval/execution API | `advisor` | 归顾问执行编排；旧 URL 与 import 保持 |
| `recommendation_entities.py`、`unified_services.py`、recommendation use cases/repositories/API | `recommendation` | 迁移；旧 import 代理 |
| `model_param_*` | `recommendation` | 作为推荐模型配置；ORM identity 暂留旧 app |
| `transition_entities.py`、transition plan/workspace/today queue | `recommendation` | 作为统一推荐到执行计划的 workspace 能力 |
| `decision_workspace_use_cases.py`、workspace services/workflows | `recommendation` | 迁移 composition；不改 API path |
| `valuation_entities.py`、`valuation_services.py`、valuation API | `valuation` | 迁纯估值规则；旧 import 代理 |
| `feature_providers.py` 中估值计算 | `valuation` Domain + Application Protocol | 禁止目标 app 直接 import 其他 app Infrastructure |
| `feature_providers.py` 其余推荐特征聚合 | `recommendation` Infrastructure | 通过 Protocol 注入估值能力 |
| `consistency_snapshots.py`、workspace snapshot task | `recommendation` | 新实现由 recommendation owner；旧 task alias 保留 |
| quota/cooldown event handlers/subscribers | `decision_rhythm` | 保持事件 source/handler identity |
| `global_alert_service.py` | `recommendation` facade | 旧配置入口兼容 |

## 2. ORM 模型冻结

| 模型 | 逻辑 owner | R3 第一阶段物理 owner | db_table |
|---|---|---|---|
| DecisionQuotaModel | decision_rhythm | decision_rhythm | `decision_quota` |
| CooldownPeriodModel | decision_rhythm | decision_rhythm | `cooldown_period` |
| DecisionRequestModel | decision_rhythm | decision_rhythm | `decision_request` |
| DecisionResponseModel | decision_rhythm | decision_rhythm | `decision_response` |
| DecisionFeatureSnapshotModel | recommendation | decision_rhythm | `decision_feature_snapshot` |
| UnifiedRecommendationModel | recommendation | decision_rhythm | `decision_unified_recommendation` |
| DecisionExecutionLinkModel | advisor | decision_rhythm | `decision_execution_link` |
| DecisionModelParamConfigModel | recommendation | decision_rhythm | `decision_model_param_config` |
| DecisionModelParamAuditLogModel | recommendation | decision_rhythm | `decision_model_param_audit_log` |
| PortfolioTransitionPlanModel | recommendation | decision_rhythm | `decision_portfolio_transition_plan` |
| ValuationSnapshotModel | valuation | decision_rhythm | `decision_valuation_snapshot` |
| InvestmentRecommendationModel | valuation | decision_rhythm | `decision_investment_recommendation` |
| ExecutionApprovalRequestModel | advisor | decision_rhythm | `decision_execution_approval_request` |

所有模型继续显式 `app_label="decision_rhythm"`。ContentType、默认权限、历史 migration 和 FK 字符串不变。若未来物理迁移模型，必须另立 expand/contract state migration，不与无状态拆分混合。

## 3. API、task 与事件身份

- 现有 `/api/decision-rhythm/**`、`/api/decision/**`、`/api/decision/workspace/**`、`/api/decision/execute/**`、`/api/valuation/**` 路径全部保持。
- URL namespace `decision_rhythm` 和现有 route name 全部保持；目标 app 通过 composition/facade 提供实现。
- `apps.decision_rhythm.application.tasks.refresh_decision_workspace_snapshots` 保留兼容 task；新 owner 如新增 task name，静态/数据库调度切换另批处理。
- EventType 不改；`decision_rhythm.DecisionRhythmEventHandler` 与 `decision_rhythm.CooldownEventHandler` 身份保持。
- dashboard、terminal、agent_runtime 三个外部消费者只切换到稳定 Application facade，不直接 import 新 app Infrastructure。
