# AgomTradePro 循环依赖与架构债全量整改方案

> 日期: 2026-04-26  
> 状态: 待执行  
> 适用范围: `apps/`, `core/`, `shared/`, `governance/`, `.github/workflows/`, `AGENTS.md`  
> 执行策略: 全量重构、一次迁完、CI 防回流

---

## 1. 背景与结论

本方案基于 2026-04-26 对当前仓库的静态导入图复核。复核结论如下:

1. 用户指出的 8 组循环依赖均存在。
2. 全量静态导入图中，app 级双向依赖不止 8 组，实际扫描到更多历史循环。
3. 当前 CI 主要防止新增越层违规，对历史循环依赖、模块职责错位和 repository 级耦合拦截不足。
4. `account`、`shared`、`data_center`、`macro -> account` 是本轮整改的关键根因区域。

本轮不再只做局部 import 修补，而是按模块所有权重划、依赖方向重建、CI hard fail 三条线并行推进。

---

## 2. 已确认的 8 组循环依赖

| # | 循环对 | 复核结论 | 优先级 | 主要修复方向 |
|---|---|---|---|---|
| 1 | `account` <-> `simulated_trading` | 存在 | P0 | 拆出 `portfolio`，通过 facade 解耦 |
| 2 | `data_center` <-> `fund` | 存在 | P0 | data_center 改为 provider registry，fund 注册 provider |
| 3 | `data_center` <-> `alpha` | 存在 | P0 | alpha price coverage 与 pool refresh 从 data_center 反向调用中移出 |
| 4 | `data_center` <-> `realtime` | 存在 | P0 | realtime 注册 quote provider，data_center 不 import realtime use case |
| 5 | `fund` <-> `asset_analysis` | 存在 | P1 | asset_analysis 只定义 scorer protocol/registry |
| 6 | `terminal` <-> `ai_capability` | 存在 | P1 | ai_capability 不再读取 terminal repository/settings |
| 7 | `simulated_trading` <-> `share` | 存在 | P1 | share 使用通用 ShareTargetRef，不 import 业务 ORM |
| 8 | `macro` <-> `account` | 存在 | P0 | `SystemSettingsModel` 迁出 account |

注意: 这些循环依赖是静态导入图意义上的架构循环，不等同于每次启动都会触发 Python circular import error。但它们会造成模块无法独立演进、测试边界不清、CI 护栏误判和后续重构反复回流。

---

## 3. 目标状态

### 3.1 架构目标

1. `shared/` 只保留技术组件、Protocol、纯算法、基础工具，不再包含 Django Model 或业务规则。
2. `account` 只负责账户身份、用户 profile、登录后账户偏好和 token。
3. `portfolio` 负责组合、持仓、交易流水、净值快照、交易成本、宏观仓位参数。
4. `rbac` 负责角色、授权、观察者权限、跨模块访问判断。
5. `config_center` 负责全局运行时配置、系统设置、数据源 token 运行时开关。
6. `data_center` 只负责统一数据协议、provider registry、标准化存储和查询，不反向 import 业务模块实现。
7. `asset_analysis` 只定义通用评分协议和聚合流程，不 import `fund/equity` 的具体 repository。
8. 全仓库 app 级循环依赖最终为 0，并由 CI hard fail 防回流。

### 3.2 非目标

1. 不改变用户可见 API 路径，除非原路径本身错误或无法维护。
2. 不在本轮重写业务算法。
3. 不把所有小模块机械合并；只合并职责确实过薄且依赖方向反复倒挂的模块。
4. 不保留长期 import shim；迁移分支内一次性修正调用路径。

---

## 4. 模块所有权调整

### 4.1 新增模块

#### `apps/config_center`

职责:

1. 承接 `SystemSettingsModel`。
2. 提供 `RuntimeSettingsQueryService` 和 `ConfigCenterFacade`。
3. 统一给 `macro`、`alpha`、`equity`、`backtest`、`factor` 等模块提供运行时配置。
4. 承接配置摘要相关 repository 和 admin。

禁止:

1. 不承接组合、持仓、交易规则。
2. 不 import 业务模块 infrastructure。

#### `apps/portfolio`

职责:

1. 承接 `PortfolioModel`、`PositionModel`、`TransactionModel`。
2. 承接 `PortfolioDailySnapshotModel`、`PositionSignalLogModel`、`CapitalFlowModel`。
3. 承接 `TransactionCostConfigModel` 和投资组合层配置。
4. 提供 `PortfolioFacade` 给 `simulated_trading`、`share`、`dashboard` 调用。

禁止:

1. 不承接用户身份认证。
2. 不直接 import `simulated_trading` ORM。

#### `apps/rbac`

职责:

1. 承接角色、观察者授权、权限判断。
2. 提供 `AccessPolicyService`。
3. 给 interface 层提供统一权限查询入口。

禁止:

1. 不承接 portfolio 业务数据。
2. 不承接 Django auth 自身模型。

### 4.2 合并模块

以下合并作为本轮全量重构的目标，但必须排在 P0 循环断链之后执行:

1. `filter` -> `macro.filtering`
2. `alpha_trigger` -> `alpha.triggering`
3. `beta_gate` -> `strategy.beta_gate`

合并要求:

1. 保持旧 API route name 可用，至少在本分支内同步更新模板、SDK、MCP 和测试。
2. 删除旧模块前必须确认 migrations、admin、urls、tests 全部迁移。
3. 合并后 CI 中禁止旧模块新增代码。

---

## 5. shared 模型迁移表

`shared/infrastructure/models.py` 中 10 个 Django Model 一次性迁出。

| 原模型 | 目标模块 | 物理表策略 |
|---|---|---|
| `AssetConfigModel` | `apps.asset_analysis.infrastructure.models` | 保留 `asset_config` |
| `IndicatorConfigModel` | `apps.macro.infrastructure.models` | 保留原表 |
| `RegimeEligibilityConfigModel` | `apps.regime.infrastructure.models` | 保留原表 |
| `RiskParameterConfigModel` | `apps.regime.infrastructure.models` | 保留原表 |
| `FilterParameterConfigModel` | `apps.filter.infrastructure.models`，后续随 filter 合入 macro | 保留原表 |
| `TransactionCostConfigModel` | `apps.portfolio.infrastructure.models` | 保留原表 |
| `HedgingInstrumentConfigModel` | `apps.hedge.infrastructure.models` | 保留原表 |
| `StockScreeningRuleConfigModel` | `apps.equity.infrastructure.models` | 保留原表 |
| `SectorPreferenceConfigModel` | `apps.sector.infrastructure.models` | 保留原表 |
| `FundTypePreferenceConfigModel` | `apps.fund.infrastructure.models` | 保留原表 |

迁移原则:

1. 使用 Django `SeparateDatabaseAndState` 调整模型状态，不优先执行真实表 rename。
2. 迁移后删除 `shared/admin.py` 和 `shared/infrastructure/admin.py` 中这些模型的注册。
3. `shared` app 可保留，但不能再包含业务模型。
4. 所有引用点必须改为目标 owning app 的 application service 或 infrastructure repository。

---

## 6. 8 组循环依赖断链方案

### 6.1 `account` <-> `simulated_trading`

现状:

1. `account` 引用 `simulated_trading` 的 performance views、unified position service、price provider 和 ORM。
2. `simulated_trading` 反向引用 account ORM。

整改:

1. 将组合、持仓、交易流水迁到 `portfolio`。
2. `account` 的 interface 不再 include `simulated_trading` views。
3. `simulated_trading` 通过 `PortfolioFacade` 查询持仓和写入交易结果。
4. performance API 归 `simulated_trading` 或 `portfolio` 明确一方，不再互相兼容调用。

验收:

1. `account` 对 `simulated_trading` import 数为 0。
2. `simulated_trading` 对 `account` import 数为 0。
3. 账户、组合、模拟盘 performance 回归测试通过。

### 6.2 `data_center` <-> `fund`

现状:

1. `data_center` import fund adapter/model。
2. `fund` import data_center use case、provider factory、repository。

整改:

1. `data_center.domain.protocols` 定义 `FundNavProviderProtocol`。
2. `fund.apps.FundConfig.ready()` 注册 fund provider factory。
3. `data_center` 只从 registry 取 provider，不 import `apps.fund.*`。
4. `fund` 只调用 data_center application facade，不直接 import data_center infrastructure repository。

验收:

1. `data_center -> fund` import 为 0。
2. `fund -> data_center.infrastructure` import 为 0。
3. 基金 NAV 查询和同步测试通过。

### 6.3 `data_center` <-> `alpha`

现状:

1. `data_center` 的 interface services 和管理命令调用 alpha pool resolver、alpha tasks、alpha models。
2. `alpha` adapter/repository 反向依赖 data_center。

整改:

1. alpha price coverage sync 移入 `alpha.application` 或 `alpha.infrastructure`。
2. data reliability repair 不直接调 alpha task，改发 domain event 或调用 `AlphaRefreshFacade`。
3. `AlphaRefreshFacade` 依赖 data_center application facade 获取行情覆盖，不碰 data_center infrastructure。

验收:

1. `data_center -> alpha` import 为 0。
2. `alpha -> data_center.infrastructure` import 为 0。
3. alpha refresh、price coverage、qlib task smoke test 通过。

### 6.4 `data_center` <-> `realtime`

现状:

1. `data_center` import realtime price polling use case。
2. `realtime` import data_center gateway/repository。

整改:

1. realtime 注册 `RealtimeQuoteProvider`。
2. data_center latest quote fallback 从 registry 获取 provider。
3. realtime 只调用 data_center application facade 或 provider protocol。

验收:

1. `data_center -> realtime` import 为 0。
2. `realtime -> data_center.infrastructure` import 为 0。
3. latest quote fallback 测试通过。

### 6.5 `fund` <-> `asset_analysis`

现状:

1. fund 使用 asset_analysis domain service。
2. asset_analysis 反向 import fund scorer/repository。

整改:

1. `asset_analysis` 只提供 `AssetScorerProtocol` 和 `AssetScorerRegistry`。
2. fund 在 app ready 阶段注册 fund scorer。
3. asset_analysis 通过 registry 调度 scorer，不 import fund。

验收:

1. `asset_analysis -> fund` import 为 0。
2. fund screen API 和 asset pool screen API 通过。

### 6.6 `terminal` <-> `ai_capability`

现状:

1. terminal API 调用 ai_capability facade。
2. ai_capability use case 读取 terminal repository/settings。

整改:

1. terminal 可以依赖 ai_capability。
2. ai_capability 不再 import terminal。
3. terminal runtime settings 迁到 `config_center` 或由 terminal 暴露 application query service。
4. ai_capability 只依赖 config_center 或 terminal application protocol，不依赖 terminal infrastructure。

验收:

1. `ai_capability -> terminal` import 为 0。
2. terminal chat、capability routing、MCP 开关测试通过。

### 6.7 `simulated_trading` <-> `share`

现状:

1. simulated_trading application 调用 share query service。
2. share repository/test import simulated_trading ORM。

整改:

1. share 定义 `ShareTargetRef(app_label, object_type, object_id)`。
2. simulated_trading 不调用 share。
3. share 通过 target resolver registry 获取摘要，不 import 业务 ORM。
4. simulated_trading 注册自己的 share target resolver。

验收:

1. `simulated_trading -> share` import 为 0。
2. `share -> simulated_trading.infrastructure` import 为 0。
3. 分享详情和模拟盘分享测试通过。

### 6.8 `macro` <-> `account`

现状:

1. macro application/infrastructure 读取 account config summary 和 `SystemSettingsModel`。
2. account 冷启动命令反向读取 macro model。

整改:

1. `SystemSettingsModel` 迁入 `config_center`。
2. macro 使用 `RuntimeSettingsQueryService` 获取 macro index codes 和 publication lag。
3. 冷启动命令迁入 `setup_wizard` 或各 owning app 自有 management command。

验收:

1. `macro -> account` import 为 0。
2. `account -> macro.infrastructure` import 为 0。
3. macro sync、publication lag、cold start 测试通过。

---

## 7. CI 与治理规则

### 7.1 新增循环依赖检测脚本

新增:

```text
scripts/check_module_cycles.py
```

能力:

1. AST 扫描 `apps/**/*.py`。
2. 解析绝对 import 和相对 import。
3. 构建 app 级导入图。
4. 输出双向依赖和完整 cycle chain。
5. 支持 JSON 报告写入 `reports/architecture/module-cycles.json`。

参数:

```bash
python scripts/check_module_cycles.py --format text
python scripts/check_module_cycles.py --format json --write-report reports/architecture/module-cycles.json
python scripts/check_module_cycles.py --fail-on-cycles
python scripts/check_module_cycles.py --allowlist-file governance/module_cycle_allowlist.json
```

执行策略:

1. 第一阶段 report-only，生成当前 baseline。
2. 整改完成后删除 allowlist，开启 `--fail-on-cycles`。
3. 后续 PR 新增任何 app 级循环直接失败。

### 7.2 扩展架构规则

更新:

```text
governance/architecture_rules.json
```

新增规则:

1. `data_center_no_business_adapter_imports`
2. `macro_no_account_dependency`
3. `shared_no_django_models`
4. `apps_application_no_infrastructure_repository_imports`
5. `account_no_simulated_trading_dependency`
6. `simulated_trading_no_account_dependency`

规则策略:

1. 已清零的规则 hard fail。
2. 未清零的历史规则先纳入 audit baseline。
3. 本轮整改完成后，8 组循环相关规则全部切 hard fail。

### 7.3 更新 GitHub Actions

更新:

```text
.github/workflows/architecture-layer-guard.yml
```

新增任务:

1. 在 `layer-guard` job 中运行 module cycle check。
2. 在 `structure-audit-report` job 中写出 `module-cycles.json`。
3. 上传 architecture artifact 时包含 cycle report。

验收:

1. CI artifact 包含 architecture audit、module ledger、module cycles 三类报告。
2. 整改完成后 CI 对循环依赖 hard fail。

---

## 8. AGENTS.md 更新规则

根目录 `AGENTS.md` 需要新增以下规则。

### 8.1 循环依赖零容忍

新增代码不得引入 app 级循环依赖。任何跨 app 调用必须满足单向依赖，或通过 protocol、facade、registry、domain event 解耦。

### 8.2 模块归属

1. 全局运行时配置归 `config_center`。
2. 投资组合、持仓、交易流水归 `portfolio`。
3. 用户身份、账号 profile、token 归 `account`。
4. 角色、授权、观察者权限归 `rbac`。
5. 数据 provider 协议和统一查询归 `data_center`。
6. 业务 provider 实现归 owning app，并向 `data_center` 注册。
7. `shared` 禁止 Django Model、业务规则和业务默认配置。

### 8.3 data_center 方向规则

`data_center` 不得 import `fund`、`alpha`、`realtime`、`equity`、`macro`、`sector` 等业务模块的 infrastructure adapter/model。业务模块必须通过 registry 注册 provider。

### 8.4 Application 层收口

Application 层不得直接 import 具体 infrastructure repository。必须通过:

1. 构造函数注入 Protocol。
2. application-level provider/factory。
3. owning app 暴露的 facade/query service。

---

## 9. 执行阶段

### Phase 0: 文档与 CI 先行

交付:

1. 本方案文档。
2. `check_module_cycles.py`。
3. CI cycle report。
4. `AGENTS.md` 新规则。

验收:

1. 当前 8 组循环能被脚本识别。
2. CI 能产出 cycle report。
3. 文档索引已更新。

### Phase 1: 配置和 shared 迁移

交付:

1. 新增 `config_center`。
2. 迁出 `SystemSettingsModel`。
3. 迁出 `shared` 10 个业务模型。
4. 删除 shared admin 中的业务模型注册。

验收:

1. `macro -> account` 消除。
2. `shared` 无 Django Model。
3. 配置相关测试通过。

### Phase 2: account 拆分

交付:

1. 新增 `portfolio`。
2. 新增 `rbac`。
3. 迁出组合、持仓、交易流水、授权模型。
4. `simulated_trading` 改用 `PortfolioFacade`。

验收:

1. `account <-> simulated_trading` 消除。
2. 账户、组合、模拟盘测试通过。

### Phase 3: data_center 反向依赖清理

交付:

1. 新增 provider registry。
2. fund/alpha/realtime/equity/macro/sector 注册 provider。
3. data_center 删除业务模块 adapter/model import。

验收:

1. `data_center <-> fund/alpha/realtime` 消除。
2. 数据同步和查询测试通过。

### Phase 4: asset_analysis、terminal、share 解耦

交付:

1. `AssetScorerRegistry`。
2. terminal/ai_capability settings 解耦。
3. `ShareTargetRef` 和 target resolver registry。

验收:

1. `fund <-> asset_analysis` 消除。
2. `terminal <-> ai_capability` 消除。
3. `simulated_trading <-> share` 消除。

### Phase 5: 模块合并与 hard fail

交付:

1. `filter` 合入 `macro.filtering`。
2. `alpha_trigger` 合入 `alpha.triggering`。
3. `beta_gate` 合入 `strategy.beta_gate`。
4. 删除 cycle allowlist。
5. CI 开启全量 cycle hard fail。

验收:

1. app 级循环依赖为 0。
2. 新增越层违规为 0。
3. 关键 API、SDK、MCP、页面回归通过。

---

## 10. 验收命令

基础检查:

```bash
python manage.py check
python manage.py makemigrations --check
python manage.py migrate --plan
python scripts/verify_architecture.py --rules-file governance/architecture_rules.json --format text --include-audit
python scripts/check_module_cycles.py --format text --fail-on-cycles
```

重点测试:

```bash
pytest tests/unit/account tests/unit/simulated_trading -q
pytest tests/unit/data_center tests/unit/fund tests/unit/alpha tests/unit/realtime -q
pytest tests/unit/macro tests/unit/equity tests/unit/portfolio tests/unit/config_center -q
pytest tests/integration -q
```

回归重点:

1. 登录、账户设置、权限判断。
2. 组合、持仓、交易流水。
3. 模拟盘下单、净值、performance。
4. 数据中台 provider 同步与查询。
5. macro 指标同步和 publication lag。
6. terminal chat 和 ai capability routing。
7. share 创建和详情页。

---

## 11. 风险与控制

### 11.1 主要风险

1. Django model app_label 迁移可能影响 content type、admin、测试 fixture。
2. `SystemSettingsModel` 被多个模块读取，迁移会触发广泛 import 修改。
3. data_center provider registry 改造会影响多数据源 failover。
4. account 拆分会影响页面 URL、权限、portfolio API。
5. 一次迁完会造成 PR 大、回归面广。

### 11.2 控制措施

1. 物理表名优先保持不变。
2. 每个 Phase 单独 commit，便于 review 和回滚。
3. 每迁一个模型，同步 admin、repository、tests、docs。
4. 所有公共 API route name 改动必须配 contract test。
5. CI 先 report-only，整改完成后再 hard fail。

---

## 12. 最终完成标准

整改完成必须同时满足:

1. 8 组确认循环依赖全部为 0。
2. 全仓库 app 级循环依赖为 0。
3. `shared/` 无 Django Model、无业务规则、无 `apps.*` 依赖。
4. `account` 不再承接 portfolio、settings、rbac 职责。
5. `data_center` 不再 import 业务模块 adapter/model。
6. Application 层不直接 import concrete infrastructure repository。
7. Interface 层不直接 import infrastructure。
8. CI 对循环依赖和新增越层违规 hard fail。
9. 关键业务回归测试通过。
10. `AGENTS.md`、架构文档、模块账本、治理 baseline 同步更新。

