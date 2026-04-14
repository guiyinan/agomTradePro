# 工程护栏与评审规矩

> 生效日期：2026-02-22  
> 适用范围：Policy / Regime / Audit / Sentiment / Backtest 及所有新模块

## 目标

避免以下问题重复出现：

1. 阈值和关键参数硬编码，导致配置失效。
2. 外部数据处理链路失败时数据丢失。
3. 宽泛异常吞错，掩盖真实故障。
4. 测试依赖环境初始数据，导致不稳定或误报。

## 强制规则

### 0) 四层架构红线（必须满足）

1. 唯一允许依赖方向：`Interface -> Application -> Domain`，`Infrastructure -> Domain`。
2. 禁止反向依赖：`Domain -> Application/Infrastructure/Interface`、`Application -> Interface`。
3. Domain 层禁止导入任何 `django.*`、ORM Model、`pandas/numpy/requests` 等外部库。
4. Application 层禁止直接导入 ORM Model；必须通过 Domain Protocol + Repository 访问数据。
5. Interface 层禁止写业务规则；只允许参数校验、调用 UseCase、返回 DTO/Response。
6. Infrastructure 层禁止承载业务决策；仅实现 Repository/Adapter/网关细节。

### 0.1) 四层架构门禁命令（PR 必跑）

1. Domain 禁用依赖扫描：  
   `rg -n "from django|import django|import pandas|import numpy|import requests" apps/*/domain -S`
2. Application 直连 ORM 扫描：  
   `rg -n "from .*infrastructure\\.models|\\.objects\\." apps/*/application -S`
3. Interface 越层调用扫描：  
   `rg -n "from .*infrastructure\\.|from .*domain\\.(services|rules)" apps/*/interface -S`
4. 版本化边界校验：  
   `python scripts/verify_architecture.py --rules-file governance/architecture_rules.json --format text`
5. 模块账本生成：  
   `python scripts/verify_architecture.py --rules-file governance/architecture_rules.json --write-ledger docs/development/module-ledger.md`

### 0.2) 架构账本与边界基线

1. 边界规则单一来源：`governance/architecture_rules.json`
2. 自动校验入口：`scripts/verify_architecture.py`
3. 生成产物：`docs/development/module-ledger.md`
4. 当前固化范围：
   - `regime -> macro` 运行时实现导入禁令
   - `strategy -> simulated_trading ORM` 禁令
   - `simulated_trading -> strategy ORM` 禁令
   - `events -> downstream handlers/models` 禁令
   - `account interface -> simulated_trading ORM / migrate_account_ledger` 禁令

### 1) 配置唯一来源（Single Source of Truth）

1. 所有业务阈值必须通过 `ConfigHelper + ConfigKeys` 读取。
2. 默认值只允许作为“配置缺失兜底”，不得在业务分支中重复写字面量阈值。
3. 同一阈值在代码中出现第二处时，必须解释为何不是复用配置键。

### 2) 外部数据处理采用两阶段入库

1. 阶段1：先持久化原始记录（`pending/raw` 状态）。
2. 阶段2：再进行解析、分类、提取、打标，并回写同一条记录。
3. 阶段2失败时，必须保留阶段1记录并写入失败元数据（错误、阶段、时间）。

### 2.1) 事件唯一键与更新策略

1. 仓储层禁止默认“按日期覆盖”更新事件。
2. 事件更新必须基于明确标识：
   - RSS 场景：`rss_item_guid`；
   - 通用场景：`event_date + title + evidence_url`；
   - 人工更新场景：显式 `id`。
3. 只有在明确的迁移/补录脚本中，才允许按日期批量修订。

### 3) 异常处理分层

1. 业务层禁止无说明 `except Exception` 直接吞错并返回成功。
2. 可恢复异常必须记录结构化上下文（模块、输入摘要、错误类型、trace id）。
3. 不可恢复异常必须上抛到统一错误边界并触发告警。

### 4) 测试必须环境无关

1. 集成测试不得假设数据库天然为空。
2. 用例应通过 fixture 主动清理或构建自己的测试数据基线。
3. 对“配置生效”与“失败兜底”必须有回归测试。
4. 诊断类测试（guardrails）默认纳入 CI，不允许长期 `xfail` 漂移。
5. 当前 CI 工作流：
   - `.github/workflows/logic-guardrails.yml`
   - `.github/workflows/architecture-layer-guard.yml`
6. `scripts/select_tests.py` 的全量回退与模块映射，必须覆盖 `apps/*/tests/` 下的 app-local tests，不得只跑 `tests/unit|integration|guardrails`。
7. `tests/api/` 与 `tests/migrations/` 属于正式 CI 入口，nightly / RC 不得漏跑。
8. 高变更模块的 diff-based selector 必须显式带上对应 API 边界测试，不得只依赖集成测试兜底；当前至少包含 `account / ai_provider / alpha / alpha_trigger / audit / backtest / beta_gate / dashboard / data_center / decision_rhythm（含 workspace_execution / workspace_recommendations） / equity / events / factor / hedge / macro / policy / regime / simulated_trading / strategy / prompt / realtime / rotation / sentiment / signal / task_monitor / terminal`。
9. 凡是使用 `@pytest.mark.qlib` 的测试，`import qlib` 必须解析到官方 `pyqlib` distribution；若解析到仓库内同名目录或非 `pyqlib` 包，测试应直接失败而不是继续运行或静默跳过。
10. Guardrail 必跑命令：
   `pytest -q tests/guardrails/test_logic_guardrails.py tests/integration/policy/test_policy_integration.py tests/unit/policy/test_fetch_rss_use_case.py tests/unit/regime/test_config_threshold_regression.py`
11. 所有 diff-based CI 门禁必须兼容 force-push / rewritten history；若 `github.event.before` 对应提交在 runner 中不可达，必须自动退回到 `HEAD^..HEAD`，不能把 Git `128` 误判成架构失败。
12. 凡是 diff-based CI 可能选中 `tests/unit/`、`tests/integration/` 或 app-local tests 的工作流，依赖安装阶段必须包含 `pip install -e sdk/`；否则 `agomtradepro` / `agomtradepro_mcp` 包不会进入 import path，测试会在 collection 阶段直接失败。
13. 单元测试若覆盖 fallback 语义，必须与当前产品契约一致地区分 `available / degraded / unavailable`；当实现允许降级可用时，不得继续把该场景断言为硬失败。
14. 纯映射/序列化类辅助函数的单元测试不得强制依赖可选运行时包；若只验证 handler 选择、字段转换等纯逻辑，应允许在缺少 `pyqlib` 等可选依赖时仍可运行。

### 5) API 改动同步门禁

1. 任何 API 改动，只要影响以下任一项，必须同步更新：
   - HTTP 路径、方法、query/body 参数
   - 响应字段、状态码、错误口径
   - SDK 模块调用与示例
   - MCP 工具返回与示例
   - OpenAPI 产物（`schema.yml`、`docs/testing/api/openapi.yaml`、`docs/testing/api/openapi.json`）
   - 用户可见提示文案（页面 / HTMX partial / Agent 输出说明）
2. 如果 API 新增“降级 / 回退 / stale / fallback”语义，前端必须显式提示用户，MCP/SDK 文档必须说明解释规则。
3. 合入前至少执行一次以下同步命令：
   - `python manage.py spectacular --file schema.yml`
   - `python manage.py spectacular --file docs/testing/api/openapi.yaml`
   - `python manage.py spectacular --format openapi-json --file docs/testing/api/openapi.json`
4. 合入前至少执行一次以下护栏测试：
   - `pytest -q tests/unit/test_docs_route_alignment.py`
   - `pytest sdk/tests/test_mcp/test_tool_execution.py -q`
   - 若改动 SDK 路径或参数契约，再执行 `pytest sdk/tests/test_sdk/test_extended_module_endpoints.py -q`

## 代码评审清单（PR Checklist）

1. 是否存在新增硬编码阈值/魔法数字？
2. 是否复用已有 `ConfigKeys`？
3. 外部数据链路是否先入库后处理？
4. 失败时是否保留原始数据并可追溯？
5. 是否新增了覆盖关键分支的测试（成功、失败、边界）？
6. 测试是否依赖环境预置数据？
7. 若修改 API，是否已同步 SDK / MCP / OpenAPI / 文档 / 用户提示？
8. 若存在 fallback/stale 语义，前端与 Agent 文案是否明确暴露该状态？

## 发布门禁（Release Gate）

合入前至少满足：

1. 关键回归集通过：Policy/Regime/Audit/Backtest 相关单测与集成测试。
2. 本文 PR Checklist 全项勾选。
3. 关键参数变更已在配置中心登记，并附默认值与回滚策略。
