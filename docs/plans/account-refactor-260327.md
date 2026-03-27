# 统一真实仓/模拟仓到账户类型账本，并同步对齐 API / 文档 / MCP / SDK

## Summary
- 统一目标账本为 `apps.simulated_trading` 现有账户体系：账户级 `account_type=real|simulated`，不再长期维护 `apps/account` 与 `apps/simulated_trading` 两套持仓/交易账本。
- `apps/account` 继续承担账户聚合、观察员权限、账户配置与对外入口职责，但其持仓/交易读写改为调用统一账本服务。
- 这次改造必须把 API、OpenAPI、文档、SDK、MCP、对齐检查脚本一起纳入交付，不允许只改后端模型和接口。
- 迁移采用“先修 bug、再双栈兼容、最后切主”的方式，避免一次性断裂。

## Implementation Changes
### 1. 统一账本与领域边界
- 以 `apps.simulated_trading.infrastructure.models.SimulatedAccountModel` 作为统一投资账户模型，语义上视为 `InvestmentAccount`，`account_type` 为唯一真实/模拟区分。
- 以 `apps.simulated_trading` 的 `PositionModel`、`SimulatedTradeModel` 作为统一持仓/交易账本；本次不做物理表改名。
- 新增统一应用层接口，如 `InvestmentAccountRepository`、`PositionLedgerRepository`、`TradeLedgerRepository`，由 `account` API、`simulated_trading` API、策略执行、MCP/SDK 共用。
- `apps/account` 的旧 `PortfolioModel/PositionModel/TransactionModel` 进入迁移期只读/导流状态，不再新增写入路径。

### 2. 真实仓与模拟仓的统一行为
- 差异放在账户层，不放在持仓字段层。
- `account_type=simulated`：持仓变化只能通过交易事件生成，保留自动交易、巡检、回测落地等链路。
- `account_type=real`：允许手工校准或外部同步，但必须走统一 use case，自动重算 `market_value`、`unrealized_pnl`、`unrealized_pnl_pct`、关闭状态、关闭时间和可卖数量。
- 平仓统一走 close use case，必须同时写交易账本与持仓状态，禁止接口层仅改 `is_closed`。

### 3. 当前真实仓 bug 先修
- 移除 `apps/account` 持仓更新对 `ModelSerializer.save()` 的直接依赖；改为统一 update use case。
- 修复当前真实仓 PATCH/PUT 修改 `shares/avg_cost/current_price` 时派生字段不重算的问题。
- 修复真实仓 close 接口只改 `is_closed/closed_at`、不写交易账本的问题。
- 为真实仓更新和平仓补契约测试，明确成功后字段联动结果。

### 4. API 统一策略
- 保留两类 canonical 路由作为迁移期入口：
  - `/api/account/*`：账户域、观察员读写、真实仓聚合入口
  - `/api/simulated-trading/*`：交易执行、模拟盘自动交易入口
- 两套路由底层都改用统一账本服务，禁止双写和规则漂移。
- `/api/account/positions/*` 改为“统一持仓视图”，默认面向 `real` 账户或按权限可访问账户查询。
- `/api/simulated-trading/accounts/{id}/positions/` 继续保留，但数据来自同一账本，响应字段口径与统一持仓模型对齐。
- 旧 `/{module}/api/*` 兼容入口继续存在，但仅作为历史兼容，不作为 SDK/MCP 契约。

### 5. API / OpenAPI / 文档 / SDK / MCP 对齐
- 将本次统一后的持仓/账户 canonical 契约写入 `docs/development/api-mcp-sdk-alignment-2026-03-14.md`，新增“账户账本统一”章节，明确：
  - 真实/模拟是账户属性，不是两套持仓系统
  - SDK/MCP 只能走 canonical `/api/...` 路径
  - `/account/api/*` 仅兼容，不是对外契约
- 更新 `sdk/README.md`、`docs/INDEX.md`、相关 API 文档，消除“真实仓走 account、模拟仓走另一套独立账本”的表述。
- 重新生成并校验 OpenAPI：
  - `schema.yml`
  - `docs/testing/api/openapi.yaml`
  - `docs/testing/api/openapi.json`
- `core/schema.py` 保持“只暴露 canonical /api/*”规则，同时保证新的 unified account/position 路径 operationId 稳定。
- SDK 改造要求：
  - `sdk/agomtradepro/modules/account.py` 改为调用统一后的 `/api/account/*` 契约
  - `sdk/agomtradepro/modules/simulated_trading.py` 保留执行型接口，但读取账户/持仓时与统一账本字段对齐
  - 如有重复能力，优先保留一个主接口，另一个仅作兼容封装
- MCP 改造要求：
  - `sdk/agomtradepro_mcp` 中所有账户/持仓相关工具统一复用 SDK 主模块，不允许单独拼旧路径
  - 明确工具语义：`account_get_positions` / `get_simulated_positions` 是不同入口、同一账本，不是两套数据源
  - MCP 默认资源摘要、默认组合/账户读取逻辑统一改到新 canonical 接口，移除对旧 `/account/api/positions/` 文本拼装依赖
- 对齐护栏必须扩展：
  - 更新 `scripts/check_doc_route_sdk_consistency.py`
  - 增加统一账本相关静态规则，检查文档、SDK、OpenAPI、MCP 工具是否仍引用废弃语义或旧路由
  - 为 SDK endpoint tests 和 MCP tool execution tests 增加账户/持仓统一场景

### 6. 数据迁移与兼容顺序
- Phase 1：修复真实仓更新/平仓链 bug，并引入统一应用层服务，不动外部契约。
- Phase 2：把 `/api/account/positions/*` 与 `/api/simulated-trading/accounts/*/positions/` 切到统一服务，保持响应兼容。
- Phase 3：执行数据迁移，将旧 `account` 账本数据迁入统一账户/持仓/交易表；迁移脚本需幂等、可回放、可校验。
- Phase 4：更新 OpenAPI、SDK、MCP、文档、对齐脚本与测试基线，完成外部契约收口。
- Phase 5：旧 `apps/account` 账本写路径下线，仅保留迁移期只读与兼容查询；最终再单独安排模型废弃/删除。

## Public Interfaces / Contract Changes
- `account_type=real|simulated` 成为所有账户、持仓、交易读取的统一过滤维度。
- `/api/account/positions/{id}/` 的更新语义从“裸字段更新”改为“校准持仓”，成功响应必须反映重算后的派生字段。
- `/api/account/positions/{id}/close/` 的语义改为标准账本平仓，必须写交易记录。
- SDK 与 MCP 只认 `/api/account/*`、`/api/simulated-trading/*` canonical 路径；文档里任何 `/account/api/*` 只能标兼容。
- OpenAPI 中账户/持仓 operationId、schema 字段名、路径参数名保持稳定，避免 SDK/MCP 生成或手写适配再次漂移。

## Test Plan
- 真实仓更新：改 `shares`、`avg_cost`、`current_price` 后，派生字段、关闭状态、时间字段完全一致。
- 真实仓平仓：生成交易记录、更新持仓状态、写入 `closed_at`，观察员仍不可写。
- 模拟仓买卖：只能通过交易事件改仓，不能通过 PATCH 持仓绕过账本。
- 权限：拥有者/观察员在统一账本下的 200/403/404 语义与现状保持一致。
- API 契约：`Content-Type`、状态码、字段结构对 `/api/account/*` 与 `/api/simulated-trading/*` 分别回归。
- OpenAPI：重新生成 schema 后无新增错误；canonical `/api/*` 收录完整，兼容旧路由不进 schema。
- SDK：`account` 与 `simulated_trading` 模块 endpoint tests 全量通过，且不再引用非 canonical 路径。
- MCP：账户/持仓相关工具注册、执行、RBAC、默认资源摘要全部通过。
- 对齐脚本：文档、路由、SDK、MCP 不一致时能报错，防止回归。
- 数据迁移：旧 `account` 持仓、交易、快照迁入后数量、成本、市值、来源、时间和关联关系一致。

## Assumptions
- 本次不接入真实券商直连；`real` 账户先按“手工录入/手工校准/外部同步导入”处理。
- 本次不做物理表重命名；先统一语义和代码路径，再决定后续数据库命名收敛。
- 迁移期允许同时保留 `/api/account/*` 与 `/api/simulated-trading/*` 两套外部入口，但底层必须是同一账本服务。
- 文档、SDK、MCP、OpenAPI、对齐脚本和测试属于本次改造的必做项，不作为后续补丁处理。
