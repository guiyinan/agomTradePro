# Architecture Audit Backlog (2026-04-22)

## 当前快照

- 扫描基线：2026-04-22
- Boundary violations：`0`
- Audit violations（2026-04-22 全量基线）：`214`
- Audit violations（2026-04-24 全量复扫）：`22`
- Audit violations（2026-04-24 终态复扫）：`0`

### 最终验证（2026-04-24）

- `python scripts\verify_architecture.py --rules-file governance\architecture_rules.json --format text --include-audit`
  结果：Boundary `0` / Audit `0`
- `python scripts\check_architecture_delta.py --include-audit --fail-on-audit-violations --format text`
  结果：Boundary `0` / Audit `0`
- `python manage.py check`
  结果：通过

### 本轮已闭环（2026-04-24）

- `apps/account/interface/authentication.py`
  已完成：MultiTokenAuthentication 改走 account application repository provider，不再直接 import token model / ORM manager；补了认证回归测试。
- `apps/account/interface/admin.py`
  已完成：account admin 改用 Django app registry + account interface repository，不再直接 import infrastructure models；系统设置单例判断不再在 interface 层直连 ORM manager。
- `apps/account/interface/transaction_api_views.py`
  已完成：交易/资金流水查询与 portfolio ownership 校验改走 account application interface services，不再在 interface 层拼用户 portfolio queryset。
- `apps/policy/interface/admin.py`
  已完成：policy admin 改用 Django app registry，不再直接 import policy infrastructure models。
- `apps/policy/interface/workbench_api_views.py`
  已复核：当前已无 interface -> infrastructure 违规 import，保留现状。

### 本轮已闭环（2026-04-24，清零收口）

- `apps/agent_runtime/interface/serializers.py`
  已完成：sanitization 依赖改走 shared helper / app registry，interface 不再 import `shared.infrastructure`。
- `apps/ai_capability/interface/api_views.py`
  已完成：capability list / route / public detail 装配统一收口到 application service，清掉 interface 对 repository 的直接依赖；并补齐列表接口收口后的衔接回归。
- `apps/ai_capability/interface/views.py`
  已完成：页面层改走 application interface service，不再直接 import capability catalog model。
- `apps/alpha/interface/views.py`
  已完成：alpha 页面查询与上下文拼装改走 application interface service，不再直连 alpha infrastructure model。
- `apps/backtest/interface/serializers.py`
  已完成：serializer 改为 app registry / payload 装配，不再直接 import backtest infrastructure model。
- `apps/dashboard/interface/serializers.py`
  已完成：serializer 改为 app registry / payload 装配，不再直接 import dashboard infrastructure model。
- `apps/equity/interface/__init__.py`
  已完成：bootstrap config 相关 shared model 访问下沉到 application/infrastructure provider，interface 初始化不再直接 import `shared.infrastructure.models`。
- `apps/events/interface/views.py`
  已完成：事件统计与页面摘要改走 application use case，不再直接依赖 event store。
- `apps/hedge/interface/serializers.py`
  已完成：serializer 改为 app registry / payload 装配，不再直接 import hedge infrastructure model。
- `apps/macro/interface/forms.py`
  已完成：数据源配置表单改为 application/query service 驱动，不再直接 import data_center infrastructure model。
- `apps/policy/interface/forms.py`
  已完成：表单改为 app registry / application helper 驱动，不再直接 import policy infrastructure model。
- `apps/policy/interface/serializers.py`
  已完成：serializer 脱离 policy/shared infrastructure 直连，统一改走 shared sanitization helper 与 app registry。
- `apps/pulse/interface/api_views.py`
  已完成：pulse history 查询改走 application query service，不再直接 import pulse repository。
- `apps/realtime/interface/__init__.py`
  已完成：regime repository 获取改走 regime application provider，不再直接 import regime infrastructure repository。
- `apps/realtime/interface/views.py`
  已完成：market summary / health check 保持 application use case 驱动，并补齐 mock 场景兼容，避免 interface 层重新回落到 infrastructure 依赖。
- `apps/signal/interface/serializers.py`
  已完成：serializer 改走 shared sanitization helper 与 payload serializer，不再直接 import `shared.infrastructure`。
- `apps/simulated_trading/interface/__init__.py`
  已完成：AI provider / prompt 依赖改为 application provider 获取，interface 初始化不再直接 import 其他 app 的 infrastructure。
- `apps/task_monitor/interface/views.py`
  已完成：dashboard/health 数据获取改走 task_monitor application provider，不再直接 import task_monitor infrastructure repository。
- `apps/alpha/application/interface_services.py`
  已补漏：Qlib cache upsert 改走 alpha repository/provider，避免 application 层残留 ORM manager 直连。
- `apps/equity/application/interface_services.py`
  已补漏：bootstrap config upsert 下沉到 equity infrastructure repository，避免 application 层残留 `shared.infrastructure.models` / `_default_manager` 触点。

### 本轮已闭环（2026-04-23）

- `apps/audit/interface/views.py`：`7 -> 0`
- `apps/backtest/interface/views.py`：`7 -> 0`
- `apps/asset_analysis/interface/pool_views.py`：`6 -> 0`
- `apps/fund/interface/views.py`：`6 -> 0`
- `apps/account/interface/portfolio_api_views.py`：`5 -> 0`
- `apps/account/interface/views.py`：`5 -> 0`
- `apps/rotation/interface/views.py`：`5 -> 0`
- `apps/rotation/interface/serializers.py`：`1 -> 0`
- `apps/rotation/application/use_cases.py`：`5 -> 0`
- `apps/dashboard/interface/views.py`：`5 -> 0`
- `apps/simulated_trading/interface/views.py`：`5 -> 0`
- `apps/audit/application/health_check.py`：`4 -> 0`
- `apps/events/application/tasks.py`：`4 -> 0`
- `apps/realtime/application/price_polling_service.py`：`3 -> 0`
- `apps/terminal/application/services.py`：`2 -> 0`
- `apps/regime/application/use_cases.py`：`2 -> 0`
- `apps/regime/application/navigator_use_cases.py`：`2 -> 0`
- `apps/dashboard/application/use_cases.py`：`2 -> 0`
- `apps/equity/application/tasks_valuation_sync.py`：`3 -> 0`
- `apps/agent_runtime/application/services/timeline_service.py`：`2 -> 0`
- `apps/sentiment/application/services.py`：`2 -> 0`
- `apps/macro/application/tasks.py`：`2 -> 0`
- `apps/data_center/application/registry_factory.py`：`2 -> 0`
- `apps/equity/application/config.py`：`2 -> 0`
- `apps/ai_capability/application/use_cases.py`：`2 -> 0`
- `apps/agent_runtime/application/facades/ops.py`：`6 -> 0`
- `apps/agent_runtime/application/facades/monitoring.py`：`5 -> 0`
- `apps/agent_runtime/application/facades/decision.py`：`4 -> 0`
- `apps/agent_runtime/application/facades/execution.py`：`4 -> 0`
- `apps/agent_runtime/application/facades/research.py`：`4 -> 0`
- `apps/signal/application/invalidation_checker.py`：`5 -> 0`
- `apps/agent_runtime/application/services/audit_service.py`：`1 -> 0`
- `apps/ai_provider/application/use_cases.py`：`1 -> 0`
- `apps/audit/application/use_cases.py`：`3 -> 0`
- `apps/equity/application/use_cases.py`：`1 -> 0`
- `apps/asset_analysis/interface/views.py`：`4 -> 0`
- `apps/signal/interface/views.py`：`4 -> 0`
- `apps/signal/interface/api_views.py`：`1 -> 0`
- `apps/signal/interface/serializers.py`：`3 -> 0`
- `apps/sentiment/interface/views.py`：`3 -> 0`
- `apps/macro/interface/views/helpers.py`：`2 -> 0`
- `apps/macro/interface/views/fetch_api.py`：`1 -> 0`
- `apps/regime/interface/api_views.py`：`3 -> 0`
- `apps/regime/interface/views.py`：`3 -> 0`
- `apps/regime/interface/serializers.py`：`1 -> 0`
- `apps/account/interface/permissions.py`：`2 -> 0`
- `apps/account/interface/backup_views.py`：`2 -> 0`
- `apps/terminal/interface/api_views.py`：`3 -> 0`
- `apps/terminal/interface/serializers.py`：`1 -> 0`
- `apps/terminal/interface/views.py`：`1 -> 0`
- `apps/ai_provider/interface/admin.py`：`2 -> 0`
- `apps/equity/interface/serializers.py`：`2 -> 0`
- `apps/sector/interface/views.py`：`2 -> 0`
- `apps/agent_runtime/interface/page_views.py`：`19 -> 0`
- `apps/agent_runtime/interface/views.py`：`2 -> 0`
- `apps/agent_runtime/interface/serializers.py`：`1 -> 0`
- `apps/account/interface/classification_api_views.py`：`3 -> 0`
- `apps/account/interface/classification_serializers.py`：`1 -> 0`
- `apps/account/interface/serializers.py`：`2 -> 0`
- `apps/account/interface/observer_api_views.py`：`4 -> 0`
- `apps/account/interface/profile_api_views.py`：`7 -> 0`
- `apps/share/interface/admin.py`：`2 -> 0`
- `apps/share/interface/views.py`：`3 -> 0`
- `apps/share/interface/serializers.py`：`1 -> 0`
- `apps/macro/interface/views/page_views.py`：`10 -> 0`
- `apps/macro/interface/views/table_api.py`：`7 -> 0`
- `apps/factor/interface/views.py`：`7 -> 0`
- `apps/factor/interface/serializers.py`：`1 -> 0`
- `apps/hedge/interface/views.py`：`7 -> 0`
- `apps/strategy/interface/views.py`：`18 -> 0`
- `apps/strategy/interface/serializers.py`：`1 -> 0`
- `apps/filter/interface/views.py`：`1 -> 0`
- `apps/filter/interface/api_views.py`：`1 -> 0`

### 审计规则分布（2026-04-22 基线）

- `apps_interface_no_infrastructure_imports`: `141`
- `apps_application_no_orm_manager_access`: `42`
- `apps_application_no_infrastructure_model_imports`: `31`

## 收口结论

- 2026-04-24 终态复扫已清零，当前 `Boundary violations` 与 `Audit violations` 均为 `0`。
- 历史问题主要来自老 `views.py` / `serializers.py` / `forms.py` 把输入输出、上下文拼装、repository 装配和 ORM 访问揉在一起；本轮已统一沉到 application service / repository provider。
- 后续防回潮依赖两层守门：全量 `verify_architecture.py --include-audit`，以及增量 `check_architecture_delta.py --include-audit --fail-on-audit-violations`。

## 模块热点（2026-04-24 终态复扫）

- 当前剩余热点：`0`
- 所有模块剩余审计项均为 `0`

## 文件级待办单

### P0: 先清 Application 大户

- [x] `apps/policy/application/use_cases.py` (`20 -> 0`)
  已完成：RSS 原始落库、审核队列、人工审核、自动分配、工作台摘要/列表查询全部改走 repository。
- [x] `apps/alpha/application/tasks.py` (`9 -> 0`)
  已完成：Qlib runtime config 改走 account application service；激活模型读取、registry 写入、cache upsert 改走 alpha repository/provider。
- [x] `apps/simulated_trading/application/unified_position_service.py` (`8 -> 0`)
  已完成：持仓增改删和买卖记录全部改走 simulated_trading repository/provider，去掉 application 层 ORM 直连。
- [x] `apps/alpha/application/services.py` (`7 -> 0`)
  已完成：固定 provider / qlib config 改走 account application service；告警创建与更新改走 alpha alert repository。
- [x] `apps/policy/application/hedging_use_cases.py` (`6 -> 0`)
  已完成：对冲记录读写改走 policy hedge repository，持仓权重和实时价格改走 account/realtime provider。
- [x] `apps/signal/application/invalidation_checker.py` (`5 -> 0`)
  已完成：删除 Application 层 ORM fallback，证伪扫描和计数统一回到 signal repository。
- [x] `apps/agent_runtime/application/facades/ops.py` (`6 -> 0`)
  已完成：事件总量、AI provider 活跃数、审计更新时间全部改走 `context_snapshot_repository`。
- [x] `apps/agent_runtime/application/facades/monitoring.py` (`5 -> 0`)
  已完成：价格预警和情绪新鲜度改走 `context_snapshot_repository`。
- [x] `apps/agent_runtime/application/facades/decision.py` (`4 -> 0`)
  已完成：决策 quota 与待审批信号统计改走 `context_snapshot_repository`。
- [x] `apps/agent_runtime/application/facades/execution.py` (`4 -> 0`)
  已完成：持仓摘要和模拟账户统计改走 `context_snapshot_repository`。
- [x] `apps/agent_runtime/application/facades/research.py` (`4 -> 0`)
  已完成：Regime 历史数和带证伪逻辑信号统计改走 `context_snapshot_repository`。

### P1: 再清 Interface 大户

- [x] `apps/beta_gate/interface/views.py` (`14 -> 0`)
  已完成：表单持久化、版本查询/回滚、最近决策、AI JSON 建议和 ViewSet repository 获取全部改走 application query service/provider；`GateConfigForm` 改为纯 interface 表单。
- [x] `apps/alpha_trigger/interface/views.py` (`12 -> 0`)
  已完成：API ViewSet 改走 application provider；页面上下文、性能统计、宏观指标、Policy、Decision execution_ref 查询改走 application query service。
- [x] `apps/equity/interface/views.py` (`9 -> 0`)
  已完成：`EquityViewSet`、股票池刷新/读取、多维度筛选、估值修复配置 ViewSet 全部改走 equity application provider；interface 不再直接 import equity/regime/signal infrastructure。
- [x] `apps/data_center/interface/api_views.py` (`8 -> 0`)
  已完成：provider config/status/settings、asset/macro/price/quote/fund/financial/valuation/sector/news/capital-flow 查询，以及各类 sync 入口全部改走 data_center application interface services；interface 不再直接 import data_center infrastructure。
- [x] `apps/audit/interface/views.py` (`7 -> 0`)
  已完成：API、页面上下文、失败计数器、Prometheus 指标和操作日志入口全部改走 audit application interface services。
- [x] `apps/backtest/interface/views.py` (`7 -> 0`)
  已完成：页面上下文、回测运行依赖构造、统计/详情/删除入口全部改走 backtest application interface services。
- [x] `apps/asset_analysis/interface/pool_views.py` (`6 -> 0`)
  已完成：池页上下文、股票/基金筛选与汇总统计改走 asset_analysis application interface services。
- [x] `apps/fund/interface/views.py` (`6 -> 0`)
  已完成：页面上下文、基金筛选/风格/业绩/API 查询与多维度筛选入口全部改走 fund application interface services。
- [x] `apps/account/interface/portfolio_api_views.py` (`5 -> 0`)
  已完成：去除 account/audit infrastructure import，持仓平仓改走 account provider，审计记录改走 audit application interface services。
- [x] `apps/account/interface/views.py` (`5 -> 0`)
  已完成：注册脚手架、资料页/设置页、Token 管理、用户审批、系统设置与协作页全部改走 account application interface services。
- [x] `apps/dashboard/interface/views.py` (`5 -> 0`)
  已完成：Dashboard DTO 构造、模拟盘持仓 fallback、账户卡片查询全部改走 dashboard application interface services；模拟盘 ORM 查询下沉到 dashboard infrastructure repository。
- [x] `apps/rotation/interface/views.py` (`5 -> 0`)
  已完成：ViewSet QuerySet、默认资产导入/导出、页面上下文、信号生成、模板应用与账户级轮动配置查询全部改走 rotation application interface services；跨 App 账户读取改走 simulated_trading application query service。
- [x] `apps/rotation/interface/serializers.py` (`1 -> 0`)
  已完成：移除显式 `infrastructure.models` import，保持现有 DRF `ModelSerializer` API 契约不变。
- [x] `apps/simulated_trading/interface/views.py` (`5 -> 0`)
  已完成：账户页面上下文、删除汇总、巡检通知配置、自动交易引擎装配、巡检报告列表全部改走 simulated_trading application interface services；ORM 查询下沉到 simulated_trading repository，分享链接读取改走 share application query service。
- [x] `apps/asset_analysis/interface/views.py` (`4 -> 0`)
  已完成：多维筛选、权重列表、当前权重与评分上下文构造收口到 asset_analysis application interface services；interface 不再直接装配 asset_analysis/policy/sentiment/signal infrastructure repository。
- [x] `apps/signal/interface/views.py` (`4 -> 0`)
  已完成：信号管理页、信号创建/状态变更/删除、unified signal pending/by_asset/execute 全部改走 signal application query services；interface 不再直接 import signal model/repository。
- [x] `apps/signal/interface/api_views.py` (`1 -> 0`)
  已完成：`SignalViewSet` 改为 application query service 驱动，详情/列表/更新/审批/校验/统计与健康检查不再直接 import signal infrastructure model。
- [x] `apps/signal/interface/serializers.py` (`3 -> 0`)
  已完成：`InvestmentSignalSerializer` / `UnifiedSignalSerializer` 改为 payload serializer，创建/更新改走 application query service；interface 不再直接 import signal/shared infrastructure。
- [x] `apps/sentiment/interface/views.py` (`3 -> 0`)
  已完成：情感分析、指数查询、健康检查、缓存清理与页面上下文全部改走 sentiment application interface services；interface 不再直接 import ai_provider/sentiment infrastructure repository 或 model。
- [x] `apps/macro/interface/views/helpers.py` (`2 -> 0`)
  已完成：macro repository / sync use case 装配改走 macro application provider / interface service，interface helper 不再直接 import macro infrastructure repository 或 adapter。
- [x] `apps/macro/interface/views/fetch_api.py` (`1 -> 0`)
  已完成：supported indicators 查询改走 macro helper -> application interface service，interface API 不再直接 import `AKShareAdapter`。
- [x] `apps/equity/interface/serializers.py` (`2 -> 0`)
  已完成：估值修复配置 serializers 改为纯 payload/request serializer，不再直接 import equity infrastructure model。
- [x] `apps/sector/interface/views.py` (`2 -> 0`)
  已完成：板块分析与数据更新页的 repo/adapter 获取改走 sector application provider，interface 不再直接 import sector infrastructure。
- [x] `apps/terminal/interface/views.py` (`1 -> 0`)
  已完成：`TerminalConfigView` 页面上下文改走 terminal application interface service，interface 不再直接 import terminal infrastructure model。
- [x] `apps/agent_runtime/interface/page_views.py` (`19 -> 0`)
  已完成：operator task/proposal 列表与详情页的查询、汇总、筛选和上下文拼装改走 agent_runtime application interface services + operator repository，interface 页面层不再直接 import agent_runtime infrastructure models。
- [x] `apps/agent_runtime/interface/views.py` (`2 -> 0`)
  已完成：task/proposal/dashboard API 的对象查找、时间线、附件、needs-attention 与 dashboard 查询统一改走 agent_runtime application interface services；interface API 层不再直接访问 agent_runtime ORM manager。
- [x] `apps/agent_runtime/interface/serializers.py` (`1 -> 0`)
  已完成：serializer 层移除对 `agent_runtime.infrastructure.models` 的直接 import，改用 Django app registry 解析模型，保持现有 `ModelSerializer` API 契约不变。
- [x] `apps/filter/interface/views.py` (`1 -> 0`)
  已完成：dashboard 页面的 filter repository 获取改走 filter application provider，并保留兼容测试 patch 点。
- [x] `apps/filter/interface/api_views.py` (`1 -> 0`)
  已完成：API ViewSet 的 filter repository 获取改走 filter application provider，并保留兼容测试 patch 点。
- [x] `apps/regime/interface/api_views.py` (`3 -> 0`)
  已完成：current/calculate/history/distribution/health 全部改走 regime application interface services；interface 不再直接 import regime repository/model/macro adapter。
- [x] `apps/regime/interface/views.py` (`3 -> 0`)
  已完成：dashboard 数据源选择、V2 判定上下文与清缓存入口全部收口到 regime application interface services；interface 不再直接 import regime macro gateway / adapter / shared cache service。
- [x] `apps/regime/interface/serializers.py` (`1 -> 0`)
  已完成：`RegimeLogSerializer` 改为 payload serializer，interface 不再直接 import `RegimeLog` model。
- [x] `apps/account/interface/permissions.py` (`2 -> 0`)
  已完成：观察员授权校验与可访问组合查询下沉到 account application/interface repository，`permissions.py` 不再直接 import account infrastructure model 或 ORM manager。
- [x] `apps/account/interface/backup_views.py` (`2 -> 0`)
  已完成：备份下载 token 校验、系统配置读取与归档生成收口到 account application/interface repository，interface 不再直接 import backup service 或 settings model。
- [x] `apps/account/interface/classification_api_views.py` (`3 -> 0`)
  已完成：资产分类、币种、汇率与 allocation API 的查询/写入全部改走 account application interface services + classification repository，`classification_api_views.py` 不再直接 import account infrastructure model 或在接口层拼 ORM 查询。
- [x] `apps/account/interface/classification_serializers.py` (`1 -> 0`)
  已完成：分类/汇率 serializers 移除对 account infrastructure model 的直接 import，改用 Django app registry 保持现有 `ModelSerializer` 契约。
- [x] `apps/account/interface/serializers.py` (`2 -> 0`)
  已完成：observer grant 的用户查找、去重校验与创建下沉到 account application/interface repository，交易费配置 serializer 也移除内联 infrastructure model import。
- [x] `apps/account/interface/observer_api_views.py` (`4 -> 0`)
  已完成：observer grant 列表、详情、持仓 payload、授权更新/撤销全部改走 account application interface services / repository；interface 不再直接访问 observer grant / portfolio ORM manager。
- [x] `apps/account/interface/profile_api_views.py` (`7 -> 0`)
  已完成：profile 读取/更新、健康检查、用户搜索、资产元数据和 trading cost config 全部改走 account application interface services / repository；interface 不再直接访问 account infrastructure manager。
- [x] `apps/terminal/interface/api_views.py` (`3 -> 0`)
  已完成：`TerminalCommandViewSet` 改为纯 application use case / repository provider 驱动，CRUD、执行、可用命令、按分类查询与审计入口不再直接 import terminal infrastructure model / repository。
- [x] `apps/terminal/interface/serializers.py` (`1 -> 0`)
  已完成：`TerminalCommand*Serializer` 改为 payload/request serializer，interface 不再直接 import `TerminalCommandORM`。
- [x] `apps/ai_provider/interface/admin.py` (`2 -> 0`)
  已完成：admin 注册改用 Django app registry 解析模型，API key 脱敏逻辑收口到 ai_provider application helper，interface 不再直接 import ai_provider infrastructure model / repository。
- [x] `apps/share/interface/views.py` (`3 -> 0`)
  已完成：分享链接管理 API、公开快照访问、分享页管理上下文、刷新入口与免责声明配置全部改走 share application interface services + repository；interface 不再直接 import share / simulated_trading / decision_rhythm infrastructure。
- [x] `apps/share/interface/serializers.py` (`1 -> 0`)
  已完成：share serializers 移除对 share infrastructure model 的直接 import，改用 Django app registry；账户归属校验下沉到 share application interface service。
- [x] `apps/share/interface/admin.py` (`2 -> 0`)
  已完成：admin 注册改用 Django app registry 解析模型，免责声明单例存在性判断下沉到 share application interface service / repository，interface 不再直接 import share infrastructure 或直连 ORM manager。
- [x] `apps/macro/interface/views/page_views.py` (`10 -> 0`)
  已完成：宏观数据页面快照、指标列表、统计摘要、数据控制台上下文全部改走 macro application interface services；页面层不再直接 import macro repository 或访问 `MacroIndicator` manager。
- [x] `apps/macro/interface/views/table_api.py` (`7 -> 0`)
  已完成：指标表格查询、详情、单条增删改和批量删除全部改走 macro application interface services；interface API 不再直接 import `MacroIndicator` model。
- [x] `apps/factor/interface/views.py` (`7 -> 0`)
  已完成：factor API ViewSet、页面上下文和页面动作全部改走 factor application interface services / repository provider，interface 不再直接 import factor infrastructure model / repository / service。
- [x] `apps/factor/interface/serializers.py` (`1 -> 0`)
  已完成：factor serializers 改为纯 payload serializer，彻底移除 interface 对 factor infrastructure model 的依赖。
- [x] `apps/hedge/interface/views.py` (`7 -> 0`)
  已完成：hedge ViewSet、页面上下文和页面动作全部改走 hedge application interface services / repository provider，interface 不再直接 import hedge infrastructure model / repository / service。
- [x] `apps/strategy/interface/views.py` (`18 -> 0`)
  已完成：strategy ViewSet queryset、页面列表上下文、规则替换、脚本配置读取、执行入口、绑定/解绑入口全部改走 strategy application interface services / repository provider；interface 不再直接 import strategy infrastructure model / provider / repository 或访问 ORM manager。
- [x] `apps/strategy/interface/serializers.py` (`1 -> 0`)
  已完成：strategy serializers 移除对 strategy infrastructure model 的直接 import，改用 Django app registry 保持现有 DRF `ModelSerializer` 契约；兼容 re-export 改成 lazy import，避免 Django app 初始化时的 `AppRegistryNotReady`。

### P2: 第二梯队 Application 清理

- [x] `apps/audit/application/health_check.py` (`4 -> 0`)
  已完成：审计表可访问性和操作日志总数统计改走 `DjangoAuditRepository.count_operation_logs()`，移除 Application 层对 `OperationLogModel` 与 manager 的直接访问。
- [x] `apps/events/application/tasks.py` (`4 -> 0`)
  已完成：旧事件清理下沉到 `DatabaseEventStore.cleanup_old_events()`，旧快照清理下沉到 `SnapshotStore.cleanup_old_snapshots()`，Celery task 不再直接访问 event store ORM Model/manager。
- [x] `apps/rotation/application/use_cases.py` (`5 -> 0`)
  已完成：配置页与信号页的数据查询改走 `RotationInterfaceRepository`，移除 Application 层对 rotation ORM Model 和 manager 的直接访问。
- [x] `apps/audit/application/use_cases.py` (`3 -> 0`)
  已完成：移除废弃的 `IndicatorPerformanceModel` / `IndicatorThresholdConfigModel` / `ValidationSummaryModel` / `MacroIndicator` / `RegimeLog` 顶层 import；相关测试改为 mock repository 契约，不再绑定违规实现细节。
- [x] `apps/realtime/application/price_polling_service.py` (`3 -> 0`)
  已完成：持仓价格与账户总值更新下沉到 simulated_trading repository，轮询服务只编排价格获取、缓存写入和更新结果 DTO。
- [x] `apps/terminal/application/services.py` (`2 -> 0`)
  已完成：Terminal runtime settings 的 singleton ORM 读取下沉到 terminal runtime settings repository，application service 不再直接访问 Django app registry / ORM manager。
- [x] `apps/regime/application/navigator_use_cases.py` (`2 -> 0`)
  已完成：Navigator 资产配置读取改走 pulse application query service，行动建议/历史查询持久化改走 regime application repository provider，application 不再直连 pulse ORM 或直接 new navigator repository。
- [x] `apps/regime/application/use_cases.py` (`2 -> 0`)
  已完成：V2 阈值配置读取改走 `DjangoRegimeRepository.get_active_threshold_config_values()`，移除 application 层对 threshold ORM model/manager 的直接访问。
- [x] `apps/dashboard/application/use_cases.py` (`2 -> 0`)
  已完成：Dashboard overview/macro/AI provider/investment rule 读取统一下沉到 dashboard infrastructure read model，并补 `dashboard` application repository provider / interface services 收口，移除 application 层对 account/ai_provider/regime ORM model/manager 的直接访问。
- [x] `apps/prompt/application/use_cases.py` (`1 -> 0`)
  已完成：移除 application 层对 `infrastructure.models` 的遗留未使用 import。

### P3: 尾项清理

- [x] `apps/equity/application/tasks_valuation_sync.py` (`3 -> 0`)
  已完成：财务数据同步任务改走 `DjangoStockRepository.list_active_stock_codes(stock_codes=...)`，移除 application 层对 `StockInfoModel` 与 manager 的直接访问。
- [x] `apps/agent_runtime/application/services/timeline_service.py` (`2 -> 0`)
  已完成：timeline 事件写入下沉到 `AgentTimelineRepository`，`TimelineEventWriterService` 改为 repository 注入式编排，移除 application 层对 timeline ORM model/manager 的直接访问。
- [x] `apps/sentiment/application/services.py` (`2 -> 0`)
  已完成：AI 失败告警写入改走 `SentimentAlertRepository`，移除 application 层对 `SentimentAlertModel` 与 manager 的直接访问。
- [x] `apps/macro/application/tasks.py` (`2 -> 0`)
  已完成：旧宏观数据清理统计改走 `DjangoMacroRepository.count_records_before_date()`，移除 application 层对 `MacroIndicator` 与 manager 的直接访问。
- [x] `apps/data_center/application/registry_factory.py` (`2 -> 0`)
  已完成：数据源注册表构建改走 `ProviderConfigRepository.list_active()`，移除 application 层对 `ProviderConfigModel.objects` 的直接访问。
- [x] `apps/equity/application/config.py` (`2 -> 0`)
  已完成：估值修复配置与摘要读取改走 `ValuationRepairConfigRepository`，移除 application 层对 `ValuationRepairConfigModel` 的直接访问。
- [x] `apps/ai_capability/application/use_cases.py` (`2 -> 0`)
  已完成：fallback chat prompt 改走 terminal runtime settings repository，API dispatch 的用户装配改走 ai_capability execution support repository，移除 application 层对 singleton settings model 和 auth user manager 的直接访问。
- [x] `apps/agent_runtime/application/services/audit_service.py` (`1 -> 0`)
  已完成：审计日志用户名解析改走 `AgentRuntimeUserRepository` / repository provider，移除 application service 内的 `User.objects.get()`。
- [x] `apps/ai_provider/application/use_cases.py` (`1 -> 0`)
  已完成：用户 fallback quota 列表改走 `AIUserFallbackQuotaRepository.list_active_users()`，移除 application use case 对 auth user manager 的直接访问。
- [x] `apps/equity/application/use_cases.py` (`1 -> 0`)
  已完成：市场基准代码读取改走 account application config summary service，移除 application use case 对 `SystemSettingsModel` 的直接 import。
- [x] 当前扫描下 `apps/*/application/` 直接 ORM/model import 触点已清零
- [ ] 每清完一组，补对应 unit test / contract test
- [ ] 每轮结束重新跑扫描，更新本单

## 建议的分批顺序

### Batch 1

- [x] `policy/application/use_cases.py`
- [x] `policy/application/hedging_use_cases.py`
- [x] `signal/application/invalidation_checker.py`

说明：这一批同属 policy/signal 语义域，repository/provider 可以复用，收益最大。

### Batch 2

- [x] `alpha/application/tasks.py`
- [x] `alpha/application/services.py`
- [x] `simulated_trading/application/unified_position_service.py`

说明：先把 application 层大文件拆干净，再回头清 interface，会减少重复抽象。

### Batch 3

- [x] `beta_gate/interface/views.py`
- [x] `alpha_trigger/interface/views.py`
- [x] `equity/interface/views.py`
- [x] `prompt/interface/views.py`

说明：这批主要是 interface 直连 infrastructure，整改模式相对统一。

### Batch 4

- [x] `data_center/interface/api_views.py`
- [x] `audit/interface/views.py`
- [x] `backtest/interface/views.py`
- [x] `asset_analysis/interface/pool_views.py`
- [x] `fund/interface/views.py`

## 每批整改完成标准

- [ ] 不新增新的 architecture violations
- [ ] 目标文件的 audit count 清零或显著下降
- [ ] `python manage.py check` 通过
- [ ] 相关 `pytest` 通过
- [ ] `python scripts/verify_architecture.py --rules-file governance/architecture_rules.json --format text --include-audit` 通过并记录最新数字

## 备注

- 当前主矛盾已经不是 boundary 违规，而是 audit 历史债清理顺序。
- 优先拆 application 大户，可以顺带降低后续 interface 整改难度。
- `prompt/interface/views.py`、`prompt/interface/serializers.py`、`prompt/interface/__init__.py` 与 `prompt/application/use_cases.py` 已全部清零。
- 当前前排已从 `account/policy` 尾项切换为 `equity/interface/__init__.py`、`policy/interface/forms.py + serializers.py`、`ai_capability/interface/api_views.py + views.py`、`realtime/interface/__init__.py + views.py`、`simulated_trading/interface/__init__.py` 这几簇。
- 后续每轮整改建议只盯 `1-3` 个热点文件，做完即重扫，避免大范围扩散。
