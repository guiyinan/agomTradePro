# 架构技术债整改方案（2026-04-22）

> 状态：Proposed
> 基线来源：`docs/architecture-audit-report-2026-04-22.md` + 代码核查
> 目标：将“文档上严格四层 DDD”收敛为“代码上可持续执行的四层 DDD”

---

## 1. 核查结论

本轮核查后，以下问题成立：

1. `core/` 确实是当前最大的架构监管盲区，存在大量跨模块直达 `infrastructure` 和 ORM 的代码。
2. 多个 App 的 `application/` 层存在直接 import `infrastructure.models`、`._default_manager`、`.objects`、`importlib` 绕过等问题。
3. 多个 App 的 `interface/` 层直接依赖 `infrastructure`，与 AgomTradePro 的四层约束不一致。
4. `shared/` 中仍存在反向依赖 `apps/` 以及承载业务语义模型的问题。
5. 现有 CI 护栏偏向“新增行防回退”，不足以消化历史存量债务。

本轮额外核实后，以下结论不成立，不纳入本计划主债项：

1. `decision_workflow.precheck()` 不是死路由。
   实际路由已注册在 `apps/decision_rhythm/interface/api_urls.py` 的 `/api/decision-workflow/precheck/`。

---

## 2. 本轮已完成

1. 将 `shared/infrastructure/asset_name_resolver.py` 迁移到 `apps/asset_analysis/`，对外通过 `apps.asset_analysis.application.asset_name_service` 暴露，消除了该项 `shared -> apps` 反向依赖。
2. 扩展 CI `Architecture Layer Guard`，使其开始扫描 `core/**/*.py` 和 `shared/**/*.py` 的新增违规代码。
3. 为 `core` 新增 controller 级禁令：
   - 禁止新增 `apps.*.infrastructure.*` import
   - 禁止新增 `._default_manager`
   - 禁止新增 `.objects.`
4. 为 `shared` 新增禁令：
   - 禁止新增 `from apps...` / `import apps...`
5. 修复 `shared` 中已发现的 naive datetime 用法。

这些修复的意义是“先止血”，不是“债务已清零”。

---

## 3. 整改目标

整改完成时，系统应达到以下验收标准：

1. `core/` 只保留 Django 项目装配职责：settings、root urls、health/readiness、少量纯项目级 glue code。
2. `shared/` 只保留技术性组件，不再承载业务规则、业务模型、业务默认配置。
3. `apps/*/application/` 不再直接 import `infrastructure.models`，不再使用 `._default_manager`、`.objects`、动态 import ORM 模型。
4. `apps/*/interface/` 不再直接依赖 `infrastructure`，统一经由 Application use case / query service / dependency builder。
5. CI 同时具备“防新增回退”和“持续消化存量债务”的能力。

---

## 4. 分阶段实施

### Phase 0：护栏收口（1-2 天）

目标：先让债务不再继续增长。

1. 将 `scripts/verify_architecture.py` 从仅扫描 `apps/` 扩展为扫描 `apps/ + core/ + shared/`。
2. 在 `governance/architecture_rules.json` 中新增 `core` 与 `shared` 的规则集，避免规则只存在于 workflow 脚本里。
3. 在 CI 中增加一条“全量结构审计”任务：
   - 可以先做 report-only
   - 输出模块级违规清单 artifact
4. 将以下绕过方式纳入扫描：
   - `._default_manager`
   - `importlib.import_module("...infrastructure.models")`
   - 函数体内 `from ...infrastructure.models import ...`
5. 所有新 PR 保持“新增违规 = 失败”。

验收标准：

1. `core/shared` 新增违规能在 PR 上直接报错。
2. nightly 能产出全量违规报表。

### Phase 1：`shared/` 去业务语义化（3-5 天）

目标：把 `shared` 收缩回技术组件层。

1. 迁移 `shared/infrastructure/models.py` 的 10 个业务模型回归所属模块。
   建议归属：
   - `AssetConfigModel`、`RegimeEligibilityConfigModel` -> `apps/regime`
   - `IndicatorConfigModel` -> `apps/macro`
   - `HedgingInstrumentConfigModel` -> `apps/hedge`
   - `SectorPreferenceConfigModel` -> `apps/rotation`
   - 其余按业务语义拆回 owning app
2. 迁移 `shared/domain/asset_eligibility.py` 到 `apps/regime/domain/`。
3. 清理 `shared/infrastructure/config_loader.py` 中业务默认配置，迁移到 owning app 的 infrastructure/config 或初始化数据脚本。
4. 合并 `shared/admin.py` 与 `shared/infrastructure/admin.py` 的重复注册。
5. 对外暴露统一迁移 shim，给 1 个迭代窗口完成调用替换后删除。

验收标准：

1. `shared/` 不再包含业务 ORM 模型。
2. `shared/` 不再定义 Regime/资产准入类业务规则。

### Phase 2：`core/` 模块化拆分（5-8 天）

目标：消除第 36 个隐形业务模块。

1. 新建 `apps/decision/`，承接：
   - `core/application/decision_context.py`
   - `core/views_decision_funnel.py`
   - `core/api_views_decision_funnel.py`
   - `core/templates/decision/`
   - 与决策漏斗相关的 page/api/query workflow
2. 新建 `apps/config_center/`，承接：
   - `core/application/config_center.py`
   - `settings_center_view`
   - `admin_console_view`
   - 配置中心相关模板与聚合 summary 构造
3. `core/views.py` 中剩余页面按业务归属继续迁移：
   - `terminal_*` -> `apps/terminal/interface`
   - `asset_screen_*` -> `apps/asset_analysis/interface`
   - `docs_*` -> 文档 owning app
4. `core/context_processors.py` 中告警业务规则下沉到 owning app 的 query service 或 dedicated alert aggregator。
5. `core/urls.py` 只保留 root-level include 和纯项目级入口。

验收标准：

1. `core/application/` 目录清空或只保留纯项目装配代码。
2. `core/views.py` 不再直接 import `apps.*.infrastructure.*`。

### Phase 3：存量 App 分批清债（按模块并行，2-3 周）

目标：从“局部干净”变成“系统性干净”。

建议优先级如下：

1. `dashboard`
   - 先拆 `application/queries.py`
   - 把跨模块读模型下沉到各 owning app repository / query service
2. `account`
   - 优先清理 `interface/` 对 `simulated_trading.infrastructure` 的直连
3. `alpha`
   - 清理 `application/services.py`、`tasks.py` 中的 ORM 直达
4. `signal`
   - 清理 `application/services.py`、`invalidation_checker.py`
   - 去掉动态 import ORM 模型的绕过逻辑
5. `equity`
   - 清理 `config.py`、`tasks_valuation_sync.py`
6. `regime`、`macro`、`data_center`
   - 处理剩余 application 层 infra import

实施规则：

1. 每次只治理 1 个模块或 1 条链路，不做大爆炸式横扫。
2. 每个模块整改都必须同时补：
   - architecture regression tests
   - API/页面回归测试
   - 文档同步
3. 能通过 repository/query service 收口的，不把业务逻辑塞回 interface。

验收标准：

1. 优先级模块的 `application/` 层零 ORM 直达。
2. 优先级模块的 `interface/` 层零 `infrastructure` import。

### Phase 4：模板、SDK/MCP、测试基础设施收尾（1 周）

目标：把架构整改收口到交付链路。

1. 将错放在 `core/templates/` 的业务模板迁回各自模块。
2. 为配置中心、决策工作流、分享、AI Capability 补 SDK/MCP/API 对齐检查。
3. 把 PR workflow 从“只跑 guardrails”升级为：
   - 结构检查
   - 受影响模块单测
   - 关键 API contract tests
4. 清理 `tests/` 下临时脚本与命名不一致目录。

验收标准：

1. 新增 API 都有 contract test。
2. 模板目录与 owning app 一致。

---

## 5. 推荐拆账顺序

为了避免边整改边返工，建议严格按下面顺序推进：

1. 护栏
2. `shared`
3. `core/config_center`
4. `core/decision`
5. `dashboard`
6. `account`
7. `alpha`
8. `signal`
9. `equity`
10. 其他尾项

原因：

1. `shared` 和 `core` 是跨模块污染源，越晚处理，后续模块越容易反复改。
2. `dashboard` 是跨模块聚合中心，拆完后会自然降低其他模块被误用的概率。

---

## 6. 风险与控制

主要风险：

1. 迁移 `shared/infrastructure/models.py` 会触发 migration、import path、admin 注册的连锁变化。
2. `core -> apps` 拆分会影响模板路径、URL name、前端 AJAX 调用、SDK/MCP 文档。
3. `dashboard` 和 `account` 改造面大，容易引入页面级回归。

控制措施：

1. 每个阶段单独 PR，禁止把“迁模型 + 迁视图 + 改 SDK”混成一个提交。
2. 对 URL、template、SDK API 建立迁移 shim，至少保留一个发布周期。
3. 每完成一个模块，更新结构债看板，避免只改最表层调用点。

---

## 7. 建议的提交粒度

推荐按以下 commit/PR 粒度推进：

1. `refactor: expand architecture guard to core and shared`
2. `refactor: move shared business models back to owning apps`
3. `refactor: extract decision module from core`
4. `refactor: extract config center module from core`
5. `refactor: remove dashboard application orm access`
6. `refactor: remove account interface infrastructure imports`

---

## 8. 最终判定口径

整改完成后，不以“文档上是否写了四层”作为完成标准，而以以下口径验收：

1. 静态扫描无新增违规。
2. 全量结构报表显示优先级模块存量违规清零。
3. 关键页面/API/SDK/MCP 回归通过。
4. `core` 与 `shared` 不再承担业务模块职责。

