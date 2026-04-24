# AgomTradePro 架构审计报告（修订版）

> **审计日期**: 2026-04-22
> **修订口径**: 基于当前仓库 HEAD 回写审计结论与整改计划
> **审计范围**: 代码架构、文档一致性、SDK/MCP 对齐、测试基础设施
> **审计方法**: 全量目录扫描 + 代表性模块深度抽样 + SDK/MCP 逐项核查

---

## 一、执行摘要

AgomTradePro 的四层 DDD 约束在 **Domain 层** 执行得较好，但系统性偏差仍集中在以下四个区域：

1. `core/` 承载了大量本应下沉到业务模块的决策、配置和页面聚合逻辑，仍是最大的历史架构债务。
2. 多个 App 的 `application/` 层仍直接触达 ORM 或 `infrastructure.models`，与“应用层不碰 ORM”的约束不一致。
3. 多个 App 的 `interface/` 层仍直接依赖 `infrastructure`，尚未完成 “Interface -> Application” 的边界收口。
4. `shared/` 虽已清理一批典型问题，但仍承载业务模型、业务规则与业务默认配置，尚未回归纯技术组件定位。

与初始审计相比，当前仓库状态已有三项关键变化：

1. `Architecture Layer Guard` 的新增代码扫描已覆盖 `apps + core + shared`，`core/` 不再是新增代码层面的完全监管盲区。
2. `shared/infrastructure/asset_name_resolver.py` 已迁出 `shared/`，转由 `apps/asset_analysis` 对外暴露。
3. `shared` 中已发现的 naive datetime 用法已改为 timezone-aware。

同时，初始审计中的一条结论已被复核推翻：

1. `decision_workflow.precheck()` **不是死路由**；`/api/decision-workflow/precheck/` 已注册在 `apps/decision_rhythm/interface/api_urls.py`。

---

## 二、版本 / 文档对齐状态

| 维度 | 代码实际 | AGENTS.md | VERSION.md | INDEX.md | README.md | 当前判断 |
|------|----------|-----------|------------|----------|-----------|----------|
| 版本号 | `0.7.0` (`core/version.py`) | `0.7.0` | `0.7.0` | `0.7.0` | — | 对齐 |
| 模块数 | `apps/` 下 35 目录 | 35 | 35 | 35 | badge: 35 | 对齐 |
| MCP 工具 | **实际 303 个**（`@server.tool()` 统计） | 302 | — | 302 | badge: 302 | **偏差 +1** |
| 构建日期 | `20260323` | — | `20260323` | — | — | 对齐 |
| 文档快照 | 当前文档修订于 `2026-04-22` | `2026-04-21` | `2026-04-21` | `2026-04-22` | — | **存在 1 天快照偏差** |

**结论**:

1. 版本号和模块数整体对齐。
2. MCP 工具数口径仍未统一，代码为 303，`AGENTS.md` / `INDEX.md` / `README.md` 仍是 302。
3. 文档快照并非完全一致，`INDEX.md` 已更新到 `2026-04-22`，`AGENTS.md` 和 `VERSION.md` 仍停留在 `2026-04-21`。

---

## 三、审计后已完成修复（截至当前 HEAD）

以下问题已在审计后回写到代码库，不再应被视为“现存问题”：

1. **`asset_name_resolver` 已迁出 `shared/`**
   - 原 `shared/infrastructure/asset_name_resolver.py` 已删除
   - 当前实现位于 `apps/asset_analysis/infrastructure/asset_name_resolver.py`
   - 对外统一入口位于 `apps/asset_analysis/application/asset_name_service.py`
2. **`shared` 的已知 naive datetime 已修复**
   - `shared/infrastructure/alerts.py`
   - `shared/infrastructure/alert_service.py`
   - 现已使用 timezone-aware 时间
3. **新增代码级的 `core/shared` 架构护栏已补上**
   - `Architecture Layer Guard` 现在扫描 `apps/**/*.py`、`core/**/*.py`、`shared/**/*.py`
   - `core` 新增 controller 级约束：禁止新增 `apps.*.infrastructure.*` import、`._default_manager`、`.objects.`
   - `shared` 新增约束：禁止新增 `from apps...` / `import apps...`

这些改动的性质是 **止血**，不是 **清债完成**。存量违规和设计归属问题仍然存在。

---

## 四、剩余核心债务

### P0-1: `core/` 仍承载大量业务逻辑

`core/` 目前仍不是纯 Django 项目装配层，而是事实上的聚合业务层。代表性区域包括：

1. `core/views.py`
   - 包含终端页、资产筛选页、文档页、管理台等业务页面聚合逻辑
   - 仍存在直接依赖 `apps.*.infrastructure.*` 和 ORM manager 的代码
2. `core/application/config_center.py`
   - 跨多个 App 聚合系统能力与配置摘要
   - 仍直接读取多个 App 的 ORM 模型与 `._default_manager`
3. `core/application/decision_context.py`
   - 承担决策漏斗编排职责
   - 仍直接依赖跨模块 `infrastructure.repositories`
4. `core/context_processors.py`
   - 仍混入跨模块告警规则与运行时汇总逻辑
5. `core/views_decision_funnel.py`、`core/api_views_decision_funnel.py`
   - 业务归属上应进入未来 `apps/decision/`

**当前判断**:  
`core/` 的“新增代码盲区”已部分堵住，但 **历史存量仍是全仓库最大架构债务**。

### P0-2: Application 层直接碰 ORM 仍是系统性问题

代表性问题仍集中在以下模块：

1. `dashboard`
   - `application/queries.py` 仍是跨模块 ORM 直达的典型集中区
   - 通过 `._default_manager` 读取多个 App 的数据
2. `alpha`
   - `application/services.py`、`tasks.py` 等处仍有 ORM 直达和 infrastructure import
3. `signal`
   - `application/services.py`、`invalidation_checker.py` 仍存在跨模块模型读取与动态导入绕过
4. `equity`
   - `application/config.py`、`tasks_valuation_sync.py` 仍有直接读取模型的情况
5. `regime`、`macro`、`data_center`、`account`
   - 仍存在程度不一的 application 层 infra 依赖

**当前判断**:  
“Application 层 ORM 直达是例外”这一目标尚未达成；在多个核心模块中，它仍是常见实现方式。

### P0-3: Interface 层直接依赖 Infrastructure 仍广泛存在

现阶段多个模块的 `interface/` 仍未彻底收口到 Application 边界。高风险区域主要包括：

1. `account`
2. `equity`
3. `signal`
4. `regime`
5. `macro`
6. `data_center`
7. `dashboard`
8. `terminal`

代表性问题包括：

1. `views.py` / `api_views.py` 直接 import `infrastructure.models`
2. `serializers.py` 直接依赖 repository / ORM model
3. 个别包内仍混有不应放在 `interface/__init__.py` 的管理命令或运行逻辑

**当前判断**:  
Interface 层“只做输入输出与编排入口”的约束尚未形成系统性执行。

### P0-4: `shared/` 仍承载业务语义

虽然 `asset_name_resolver` 已迁出 `shared/`，但 `shared/` 仍未回归纯技术组件定位。现存问题包括：

1. `shared/infrastructure/models.py`
   - 仍包含 10 个带明显业务语义的 Django 模型
2. `shared/domain/asset_eligibility.py`
   - 仍定义 Regime × 资产准入矩阵与业务规则
3. `shared/infrastructure/config_loader.py`
   - 仍保留业务默认配置和 fallback 逻辑
4. `shared/infrastructure/notification_service.py`
   - 仍存在 `shared -> apps` 的反向依赖
5. `shared/admin.py` 与 `shared/infrastructure/admin.py`
   - 仍有重复注册风险

**当前判断**:  
`shared/` 的一个典型反向依赖问题已清除，但 **shared 承载业务模型 / 业务规则 / 业务默认配置** 这一根本问题仍成立。

### P1-1: 业务模板仍大量滞留在 `core/templates/`

`core/templates/` 中仍保留大量属于业务模块的模板目录，包括但不限于：

1. `dashboard/`
2. `decision/`
3. `account/`
4. `terminal/`
5. `backtest/`
6. `share/`
7. `strategy/`
8. `data_center/`
9. `signal/`
10. `ai_provider/`

**当前判断**:  
模板归属问题不会直接触发 CI 失败，但会持续放大 `core/` 的聚合职责和路径耦合。

### P1-2: SDK / MCP / 文档口径仍有对齐缺口

| 项目 | 当前状态 | 判断 |
|------|----------|------|
| `decision_workflow.precheck()` 路由 | `/api/decision-workflow/precheck/` 已存在 | **初始审计结论不成立，已核实** |
| `share` API -> SDK | `apps/share/interface/api_urls.py` 存在 API，`sdk/agomtradepro/modules` 中无 `share` 模块 | **仍是缺口** |
| `ai_capability` API -> SDK | `apps/ai_capability/interface/api_views.py` 存在 API，SDK 中无 `ai_capability` 模块 | **仍是缺口** |
| `hedge.py` / `rotation.py` SDK 风格 | 仍未继承 `BaseModule`，保留孤立 `TYPE_CHECKING` 风格 | **仍是低优先级不一致项** |
| MCP 工具计数 | 代码 303，文档仍多处 302 | **仍是缺口** |

**当前判断**:  
SDK/MCP 对齐问题的重心应从“修死路由”切换为“补 SDK 覆盖 + 修正文档计数 + 统一模块风格”。

### P2-1: 测试基础设施与门禁仍偏保守

当前仍存在的主要问题：

1. `run_tests.py` 使用机器相关绝对路径，跨环境可移植性差
2. PR workflow 以 guardrails 和变更选测为主，缺少更强的 PR 级别回归门禁
3. Nightly / PR 的 Python 版本矩阵尚未完全收口到统一策略
4. SDK / MCP 独立测试覆盖仍不均衡
5. `tests/` 下仍有临时脚本、命名不一致和迁移测试覆盖不足的问题

**当前判断**:  
现有 CI 足以“防止继续恶化”，但还不足以“加速消化历史存量债务”。

---

## 五、当前 CI / 护栏状态评估

### 已修复的部分

1. `Architecture Layer Guard` 的新增行扫描已覆盖 `apps + core + shared`
2. `core` 新增 controller 级越层 import / ORM manager 使用已可在 PR 中被拦截
3. `shared` 新增 `apps.*` 依赖已可在 PR 中被拦截

### 仍未解决的部分

1. `scripts/verify_architecture.py` 与 versioned boundary rules 仍主要围绕 `apps/` 建模
2. CI 依旧以 **diff 新增行** 为主，存量违规默认不会 hard fail
3. `application` 层的 `._default_manager`、`importlib.import_module("...infrastructure.models")` 等绕过方式仍未被完整纳入护栏
4. 目前还没有稳定的“全量结构债报表 -> 持续收口”的治理闭环

**结论**:  
CI 状态应描述为 **“新增代码护栏已明显加强，但存量债务治理能力仍不足”**，而不是“架构门禁已完整覆盖四层边界”。

---

## 六、做得好的

1. **Domain 层隔离整体较好**
   - 审计样本中未见 Domain 层被 Django / pandas / numpy 污染的系统性问题
2. **SDK / MCP 覆盖面已具备规模**
   - 大部分核心业务模块已有 API + SDK + MCP 基础接入
3. **CI 护栏体系已有雏形**
   - Architecture Guard、Logic Guardrails、Consistency Check、Security Scan、Nightly、RC Gate 已形成组合门禁
4. **文档体系相对完整**
   - 项目拥有较强的文档化意识，适合承载分阶段清债
5. **测试规模具备基础**
   - 测试总量与层级覆盖已足以支撑“模块化渐进整改”路线

---

## 七、分阶段整改计划

### Phase 0：护栏收口（1-2 天）

目标：先让债务不再继续增长，并建立“存量可见、增量阻断、总量只降不升”的治理闭环。

1. 将 `scripts/verify_architecture.py` 从仅扫描 `apps/` 扩展为扫描 `apps/ + core/ + shared/`
2. 在 `governance/architecture_rules.json` 中新增 `core` 与 `shared` 的规则集
3. 在 CI 中增加“全量结构审计”任务，先以 report-only 形式输出违规清单 artifact
4. 将以下绕过方式纳入扫描：
   - `._default_manager`
   - `importlib.import_module("...infrastructure.models")`
   - 函数体内 `from ...infrastructure.models import ...`
5. 保持所有新 PR 为“新增违规 = 失败”
6. 基于当前仓库 HEAD 生成一次全量架构债 baseline，记录总量、Top rules、Top files、模块分布，并作为后续对比基线
7. 将 nightly 审计从“只出报表”升级为“报表 + 与 baseline 对比”，要求全仓库违规总量只能下降不能上升；新增模块级净增违规直接标红
8. 对已清零的模块逐步切换为 hard fail：一旦某模块 audit 违规归零，后续 PR 不允许在该模块重新引入同类问题

治理原则：

1. PR 继续执行增量 hard fail，避免新债进入主干
2. Nightly 负责全量盘点历史债，不要求一次性清零，但要求趋势单向收敛
3. 历史债治理以模块为单位建立“毕业机制”：清完一个模块，就把它从 baseline 管理升级为 hard fail 管理
4. 如果某次规则升级导致统计口径变化，必须同步重算 baseline，并在报告中记录重算日期与原因

验收标准：

1. `core/shared` 新增违规能在 PR 上直接报错
2. nightly 能产出全量违规报表
3. nightly 报表能明确显示“相对 baseline 的增减变化”，而不是只给绝对数量
4. 任一模块在完成整改后，可以单独开启“零新增且零回退”的 hard fail 门禁

### Phase 1：`shared/` 去业务语义化（3-5 天）

目标：把 `shared` 收缩回技术组件层。

1. 将 `shared/infrastructure/models.py` 的业务模型拆回 owning app
2. 将 `shared/domain/asset_eligibility.py` 迁入 `apps/regime/domain/`
3. 清理 `shared/infrastructure/config_loader.py` 中的业务默认配置
4. 合并 `shared/admin.py` 与 `shared/infrastructure/admin.py` 的重复注册
5. 保留短期迁移 shim，一个迭代周期后删除

验收标准：

1. `shared/` 不再包含业务 ORM 模型
2. `shared/` 不再定义 Regime / 资产准入类业务规则

### Phase 2：`core/` 模块化拆分（5-8 天）

目标：消除“第 36 个隐形业务模块”。

1. 新建 `apps/decision/`，承接决策漏斗相关 page / API / workflow / template
2. 新建 `apps/config_center/`，承接配置中心与系统能力目录聚合逻辑
3. 将 `core/views.py` 中其余页面按业务归属继续回迁：
   - `terminal_*` -> `apps/terminal/interface`
   - `asset_screen_*` -> `apps/asset_analysis/interface`
   - `docs_*` -> 文档 owning app
4. 将 `core/context_processors.py` 的告警业务规则下沉到 owning app query service / aggregator
5. 将 `core/urls.py` 收缩为 root-level include 与少量项目级入口

验收标准：

1. `core/application/` 清空或仅保留纯项目装配代码
2. `core/views.py` 不再直接 import `apps.*.infrastructure.*`

### Phase 3：重点 App 存量清债（2-3 周）

目标：把“局部合规”推进为“系统性合规”。

建议优先级：

1. `dashboard`
2. `account`
3. `alpha`
4. `signal`
5. `equity`
6. `regime` / `macro` / `data_center`

执行原则：

1. 每次只治理 1 个模块或 1 条链路，不做大爆炸式横扫
2. 每个模块整改必须同时补 architecture regression tests、API / 页面回归测试与文档同步
3. 通过 repository / query service 收口跨模块读，不把业务逻辑回填到 interface

验收标准：

1. 优先级模块的 `application/` 层零 ORM 直达
2. 优先级模块的 `interface/` 层零 `infrastructure` import

### Phase 4：模板、SDK/MCP、测试基础设施收尾（1 周）

目标：把架构整改收口到交付链路。

1. 将业务模板逐步迁出 `core/templates/`
2. 为 `config_center`、`decision`、`share`、`ai_capability` 补 SDK / MCP / API 对齐
3. 将 PR workflow 从“只跑 guardrails”升级为“结构检查 + 受影响模块单测 + 关键 API contract tests”
4. 清理 `tests/` 下临时脚本与命名不一致目录

验收标准：

1. 新增 API 均有 contract test
2. 模板目录与 owning app 归属一致

---

## 八、推荐拆账顺序

建议严格按以下顺序推进：

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

1. `shared` 和 `core` 是跨模块污染源，越晚处理，后续模块越容易反复返工
2. `dashboard` 是跨模块聚合中心，先治理它能显著降低其余模块的误用扩散

---

## 九、风险与控制

### 主要风险

1. 迁移 `shared/infrastructure/models.py` 会引发 migration、import path、admin 注册连锁变化
2. `core -> apps` 拆分会影响模板路径、URL name、前端 AJAX 调用、SDK / MCP 文档
3. `dashboard` 和 `account` 改造面较大，容易引入页面级回归

### 控制措施

1. 每个阶段单独 PR，禁止把“迁模型 + 迁视图 + 改 SDK”混在一个提交中
2. 对 URL、template、SDK API 建立迁移 shim，至少保留一个发布周期
3. 每完成一个模块，更新结构债看板，避免只改调用表层

---

## 十、核心矛盾总结

项目对外宣称严格四层 DDD，但当前更准确的描述应是：

1. **`core/` 的新增代码盲区已部分堵住，但历史存量仍是最大债务**
2. **Application 层 ORM 直达仍是多个核心模块中的常见实现方式**
3. **Interface 层直接依赖 Infrastructure 的问题仍未系统性收口**
4. **`shared/` 已消除一个典型反向依赖问题，但仍承载业务模型、业务规则和业务默认配置**
5. **规则已经比过去更严格，但执行仍偏向“防新增回退”，不是“全量结构清债”**

> **根因判断**: 四层架构规范是在项目中后期强化执行的，历史代码规模较大。当前门禁策略优先选择“先阻止继续恶化”，因此新增代码治理已有进展，但存量债务仍需要独立的阶段性整改工程。

---

## 十一、最终验收口径

整改完成后，不以“文档上是否写了四层”作为完成标准，而以以下口径验收：

1. 静态扫描无新增违规
2. 全量结构报表显示优先级模块存量违规清零
3. 关键页面 / API / SDK / MCP 回归通过
4. `core` 与 `shared` 不再承担业务模块职责

---

**审计人**: AgomTradePro Architecture Review  
**审计日期**: 2026-04-22  
**修订口径**: 当前仓库状态 + 已回写修复 + 后续整改总计划
