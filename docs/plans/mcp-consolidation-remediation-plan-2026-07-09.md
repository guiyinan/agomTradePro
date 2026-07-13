# MCP 收口整改计划（2026-07-09）

> 目标：将 AgomTradePro MCP 从大规模平铺工具和 API 包装层，整改为统一注册、统一调用、统一治理、可审计的外部 Agent 操作协议。
> 关键约束：本计划不是把 `terminal agent` 从 MCP 切走，而是把它当前消费的 MCP surface 从散装 raw tools 收口为 `core tools + governed capabilities`。
> 执行口径（2026-07-10）：`terminal agent` 当前真实链路是 `terminal agent -> MCPServerStdio -> python -m agomtradepro_mcp.server`，因此整改目标是统一注册与统一调度，不是去 MCP 化。
> 治理数据口径（2026-07-12）：`governance/governance_baseline.json` 是动态治理数据唯一可写、唯一可判定的机器真源；本文只维护规则、字段解释、执行状态和证据入口，不维护 live 数字副本。
> 配套标准：[MCP 技术与开发标准](../mcp/mcp-technical-and-development-standard.md)

---

## 0. 当前执行状态

截至 `2026-07-09`，本计划已不是纯提案状态，已完成以下前置动作：

1. 已新增标准文档：`docs/mcp/mcp-technical-and-development-standard.md`
2. 已补充索引入口：`docs/INDEX.md`
3. 已生成 inventory 脚本：`scripts/generate_mcp_tool_inventory.py`
4. 已产出静态盘点结果：
   - `reports/mcp/mcp-tool-inventory-2026-07-09.json`
   - `reports/mcp/mcp-tool-classification-2026-07-09.md`
5. 已补充脚本单测：`tests/unit/test_generate_mcp_tool_inventory.py`
6. 前置静态 inventory 已完成并固化到：
   - `reports/mcp/mcp-tool-inventory-2026-07-09.json`
   - `reports/mcp/mcp-tool-classification-2026-07-09.md`
   - 相关 live 治理数量统一以 `governance/governance_baseline.json` 为机器唯一真源
7. 已落地 `sdk/agomtradepro_mcp/registry/` 初版骨架：
   - `manifest.py`
   - `loader.py`
   - `dispatcher.py`
   - `registry/modules/basic_read_capabilities.py`
8. 已落地 unsupported legacy contract 显式清单：
   - `sdk/agomtradepro/unsupported_legacy_contracts.py`
   - 已登记 contract 的实时数量读取 `governance/governance_baseline.json` 的 `mcp_governance.unsupported_legacy_contract_count`
   - 当前登记项包含：`realtime.delete.price_alert`
   - 对应 raw tools 由 inventory 与 unsupported contract registry 自动关联，本文不维护数量副本
9. 已落地 `sdk/agomtradepro_mcp/tools/core_tools.py`，统一入口工具固定为：
   - `agom_bootstrap`
   - `agom_capability_search`
   - `agom_capability_schema`
   - `agom_capability_call`
   - `agom_confirmation_resume`
   - `agom_workflow_start`
   - `agom_workflow_status`
10. 当前代码状态已进入 **default core-only + explicit legacy compatibility**：
   - 默认 server 顶层工具数读取 `governance/governance_baseline.json` 的 `mcp_governance.default_top_level_tool_count`
   - 默认仅暴露统一 core tools
   - 显式开启 `AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS=true` 时，仍可兼容当前 legacy tools；实时数量读取 `governance/governance_baseline.json` 的 `mcp_governance.legacy_capability_count`
11. `apps/ai_capability/application/use_cases.py` 已开始同步治理后的 MCP capability 条目：
   - catalog 现在可生成 `execution_target.type = "mcp_capability"` 的能力记录
   - 这些记录通过 `agom_capability_call` 调统一 dispatcher，而不是直连 raw tool
   - 当前已同步治理元数据：`replacement_for`、`idempotency`、`idempotency_argument_name`、`audit_tags`
12. 同步后的 legacy raw MCP tool 条目已默认降级为：
   - `enabled_for_terminal = false`
   - `enabled_for_chat = false`
   - `enabled_for_agent = false`
   - 仍保留治理可见性与兼容执行能力
   - 如存在 replacement，现已同步 `execution_target.replacement_capability_key`
13. `apps/agent_runtime/infrastructure/terminal_agent_service.py` 已进入受控切换：
   - 当 catalog 中存在 governed MCP capability 时，terminal agent 只暴露 core tools
   - 当 governed capability 尚未同步时，terminal agent 仍兼容 raw tool 路径
14. 普通站内 `web/chat` 路由已增加 source policy：
   - 若存在 builtin / terminal_command / api 候选，则不再让 `mcp_tool` 候选参与默认竞争
   - 若只剩 `mcp_tool` 候选，则默认回退到普通 chat，而不是直接走 MCP wrapper
15. server 侧已切到默认 `core-only` surface：
   - 默认 `AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS=false`
   - server 默认只暴露上述固定 core tool 集；实时数量读取 `mcp_governance.default_top_level_tool_count`
   - raw tool 兼容验证必须显式开启 legacy 开关
16. `apps/ai_capability` 已新增显式 `semantic_key`：
   - `CapabilityCatalogModel.semantic_key`
   - `CapabilityDefinition.semantic_key`
   - API collector / builtin / terminal_command / governed MCP capability 均开始写入该键
17. 路由层已开始按 `semantic_key` 去重：
   - `web/chat` 同一语义下优先保留 builtin / terminal_command / api
   - `terminal/agent` 同一语义下可优先保留 governed MCP capability
   - 无 `semantic_key` 的旧记录仍走兼容规则，不阻塞现有功能

### 0.1 执行硬约束（2026-07-10 校正版）

后续整改必须按以下解释执行，避免方向再次跑偏：

1. `terminal agent` 当前就是 MCP-backed runtime；整改目标是收口它消费的 MCP 面，不是去掉这条链路。
2. 普通站内 `web/chat`、页面控件、TUI 用户任务默认不应把 MCP 当成内部 API 平替；它们优先走 builtin / application facade / canonical API。
3. MCP 对外只保留少量稳定顶层入口，系统能力一律通过 `agom_capability_search/schema/call` 和 dispatcher 进入统一注册表。
4. 新增整改项不得再新增散装 `@server.tool()` 作为默认能力入口；如需兼容，只能走显式 `legacy` 开关。
5. 新迁移写能力必须同时落地 `manifest -> dispatcher -> preview-first -> confirmation -> idempotency -> audit_tags -> catalog replacement -> tests/docs` 整链路。
6. 文档中的“统一调用”含义固定为：Agent 猜能力键，而不是猜 raw tool 名、HTTP path、view 名或 SDK 私有方法名。

### 0.2 后续执行人的固定入口（2026-07-10）

本节用于避免后续整改再次回到“猜 tool / 猜 API / 猜 terminal 运行形态”的旧路径。后续执行人进入本计划时，默认从这里继续，不再重复做方向判断。

#### 0.2.0 大文件整改主线（2026-07-12 强制新增）

大文件整改与 capability 迁移并列为独立主线，不能再以“当前 large-file guard 未报错”视为完成。现有检查主要覆盖应用生产代码，`sdk/agomtradepro_mcp` 中的历史聚合文件仍存在扫描盲区；后续不得继续向这些聚合文件追加实现。

整改范围：

1. `sdk/agomtradepro_mcp/server.py`：拆除业务 fallback、write handler 和大规模静态映射，使其只承担 composition root 与启动职责。
2. `sdk/agomtradepro_mcp/registry/modules/basic_read_capabilities.py`：按 owner 拆分 read/compute manifest。
3. `sdk/agomtradepro_mcp/registry/modules/write_capabilities.py`：按 owner 拆分 workflow/write manifest。
4. registry、catalog、SDK endpoint 的巨型测试聚合文件：迁移为 owner focused shard，并让 evidence guard 递归识别分片。
5. `sdk/agomtradepro_mcp/tools/*`：legacy compatibility 保留 owner 文件，但单文件超过机器阈值时继续按任务域拆分，不得重新合并到 server。

固定执行顺序：

1. **先封增长**：所有新能力只允许进入 `registry/modules/<owner>_*_capabilities.py`、`registry/read_handlers/<owner>.py`、`registry/internal_handlers/<owner>.py` 和 focused tests；禁止修改两个历史 manifest 聚合文件来增加能力。
2. **扩展机器门禁**：让治理检查覆盖 `sdk/agomtradepro_mcp` 生产 Python，并将阈值、待拆债务与实际结果纳入 `governance/governance_baseline.json`；不得把新发现的大文件加入长期 allowance。
3. **先拆 manifests**：按 `owner_app + read/compute/write` 搬迁，loader 显式装配 owner shard；每批验证 capability key、schema、replacement、risk、confirmation、idempotency 和 audit metadata 完全不变。
4. **再拆 handlers**：把 `server.py` 中的 fallback 和 preview/commit handler 按 owner 搬入 handler package；server 只合并 owner registry，不再直接保存业务实现。
5. **再拆测试**：按 owner 建 focused API/SDK/registry/catalog shard，更新 read/write evidence guard 的受控扫描范围后再删除总测试中的重复证据。
6. **最后清债**：两个历史 manifest 聚合文件不再承载 manifest，`server.py` 达到机器阈值，临时兼容 import 被删除，机器基线中对应债务自动归零。

每个拆分批次的验收条件：

1. 默认 MCP surface 和 Terminal MCP-backed 链路不变。
2. manifest key、schema、executor、legacy replacement 和 catalog semantic key 不变。
3. core-only 与显式 legacy-on 回归均通过。
4. 全部 MCP 专项守卫、治理一致性、架构检查和 focused tests 通过。
5. 新旧模块不得双重注册；loader 中不得保留隐式 wildcard discovery。
6. 回滚只允许回滚当批 owner shard 的装配，不得恢复向巨型聚合文件继续追加的开发方式。

完成定义：MCP SDK 生产文件全部受机器 large-file 门禁约束；`server.py` 仅为 composition root；read/write manifests 与 handlers 均按 owner 分片；历史聚合文件清空或删除；测试证据按 owner 可独立运行；Markdown 不保存动态文件行数或债务数量。

#### 0.2.1 当前不可改口径

1. `terminal agent` 当前真实链路固定为 `terminal agent -> MCPServerStdio -> python -m agomtradepro_mcp.server`，整改目标是收口它消费的 MCP surface，不是去掉 MCP。
2. 普通站内 `web/chat`、页面控件、TUI 用户任务、内部 API 调用默认不经 MCP；它们优先走 builtin、Application Facade 或 canonical API。
3. MCP 顶层默认 surface 只允许维持标准定义的固定 core tool 集；实时数量读取 `mcp_governance.default_top_level_tool_count`，不得为了迁移方便重新放开散装 raw `@server.tool()`。
4. 没有证据链的候选能力不得进入默认迁移序列；所谓证据链，至少包括 raw tool 或受控 `internal_handler`、SDK 或 canonical API、focused contract/test evidence。

#### 0.2.2 唯一机器真源字段与验证入口

MCP 动态治理数据的机器唯一真源是 `governance/governance_baseline.json`。本节不再复制 live 数字，只说明字段口径、验证方式和当前批次状态；任何数量变化必须先更新机器基线并通过对应守卫，禁止只改文档。

适用范围包括 `README.md`、`README_EN.md`、`docs/SYSTEM_SPECIFICATION.md`、现行系统拓扑与模块依赖文档、`sdk/README.md`、`docs/INDEX.md`、开发快速参考、生成型 Module Ledger、MCP 指南、技术标准和本整改计划。上述文档只允许引用机器字段、生成产物和验证命令，不得维护“当前工具数、能力数、模块数、测试函数数”等动态数值副本。带明确日期的 inventory、Changelog、宣传素材和历史验收记录可以保留当时结果，但必须标明是历史快照，不得被描述为当前治理基线。

机器基线是唯一允许提交动态治理值的文件。任何文档、交接摘要、PR 描述或验收报告中的通过数量只能作为带时间戳的执行证据，不能成为 baseline fallback，也不能反向驱动机器基线更新。

整改进度清单可以保留 capability key、完成日期和验证证据，但不得再用“第 N 个”“已有 N 个”“累计 N 个”等文字维护实时数量；数量统一读取下表对应机器字段。

文档中的 `已完成`、`冻结`、`待整改` 只表达执行结论，不构成治理计数或验收真源。能力是否已纳入治理，必须由 registry manifest、catalog replacement、专项守卫和 `governance/governance_baseline.json` 共同判定；文档不得通过连续编号、完成项序号或人工汇总推导当前数量。

阶段号、执行顺序、风险等级编号和“默认顶层工具不超过 10”这类固定设计阈值只属于流程或技术标准，不属于动态治理数据。当前实际值仍只能读取 `governance/governance_baseline.json`，不得从计划表、完成清单、历史报告或固定阈值反推。

| 治理指标 | 机器真源字段 | 验证入口 |
| --- | --- | --- |
| 默认 top-level MCP tools | `mcp_governance.default_top_level_tool_count` | `python scripts/check_mcp_tool_budget.py` |
| governed manifests | `mcp_governance.governed_manifest_count` | `python scripts/check_mcp_manifest_schema.py` |
| governed read capabilities | `mcp_governance.governed_read_capability_count` | `python scripts/check_mcp_read_evidence.py` |
| governed write-like capabilities | `mcp_governance.governed_write_like_capability_count` | `python scripts/check_mcp_write_confirmation.py` |
| MCP catalog candidates | `mcp_governance.catalog_candidate_count` | `python scripts/check_mcp_catalog_dedup.py` |
| registered `@server.tool()` definitions | `mcp_tool_count` | `python scripts/check_governance_consistency.py --baseline governance/governance_baseline.json --format text` |
| legacy catalog capabilities | `mcp_governance.legacy_capability_count` | `python scripts/check_mcp_catalog_dedup.py` |
| replacement links | `mcp_governance.replacement_link_count` | `python scripts/check_mcp_catalog_dedup.py` |
| unsupported legacy contracts | `mcp_governance.unsupported_legacy_contract_count` | unsupported contract registry check |
| raw tool file surface | `mcp_governance.raw_tool_file_count` | `python scripts/check_mcp_no_raw_tools.py` |
| business modules | `business_module_count` | `python scripts/check_governance_consistency.py --baseline governance/governance_baseline.json --format text` |
| static test functions | `static_test_function_count` | `python scripts/check_governance_consistency.py --baseline governance/governance_baseline.json --format text` |
| module shape、架构债务、large-file 等其他 ratchet | `governance/governance_baseline.json` 对应字段 | `python scripts/check_governance_consistency.py --baseline governance/governance_baseline.json --format text` |

表中只登记字段和验证入口，不登记字段当前值。任何面向人的汇总都应在需要时由机器基线或守卫输出生成，不得手工维护第二份统计表。

唯一真源整改状态（2026-07-12）：**已完成并纳入持续守卫**。

- `governance/governance_baseline.json` 是动态治理数据唯一可写的机器基线。
- `docs/governance/SYSTEM_BASELINE.md` 已降级为叙事索引，不再承担数字真源或兜底真源职责。
- README、系统规格、架构文档、SDK/MCP 指南、文档索引、技术标准和本计划只引用机器字段、生成产物及验证命令。
- `scripts/check_governance_consistency.py` 已将上述现行文档及 `docs/governance/ARCHITECTURE_GUARDRAILS.md` 纳入守卫，缺失机器真源引用或重新复制当前治理数量都会产生 CI 违规。

当前批次状态备注：
   - `account.update.macro_sizing_config` 已完成 write 收口：legacy raw tool 继续兼容，governed capability 通过 Account SDK 读取 active 配置生成无写入 preview，确认后才以 canonical PATCH 创建并激活新版本；manifest 固定 staff role、confirmation、required idempotency 与 audit tags
   - Terminal Agent 的 capability 可见性与高风险意图匹配已从 `agent_runtime` 对 `ai_capability` Domain/Infrastructure 的直接依赖，改为由 Terminal composition root 注入 AI Capability Application Facade；Terminal 仍保持 MCP-backed，模块循环与依赖预算已恢复
   - Strategy 基础读取已新增 `strategy.read.catalog` 与 `strategy.read.detail`；canonical ViewSet 现由服务端 scoped queryset 保证普通用户仅能读取本人策略，staff/superuser 可读取全量，focused API 合同证明 catalog/detail 不写 Strategy 业务表
   - Strategy AI 配置读取已新增 `strategy.read.ai_config_catalog` 与 `strategy.read.ai_config_detail`；AI config queryset 通过关联 strategy owner 执行相同范围隔离，配置不存在时返回未配置结果而不创建默认记录
   - Strategy 仓位规则读取已新增 `strategy.read.position_rule_catalog` 与 `strategy.read.position_rule_detail`；独立 rule ViewSet 与按策略 detail 均执行 owner/staff scope，读取不触发规则评估、启停或写入
   - Strategy 仓位计算已新增 `strategy.compute.position_rule` 与 `strategy.compute.position_management`；两条 canonical POST 均复用 owner/staff scoped ViewSet 对象查询，只调用纯表达式计算服务，focused API 合同证明跨用户返回 404 且全部 Strategy 业务表计数不变
   - Strategy Script Config、Rule Condition、Assignment 在 canonical API 中存在但没有对应 raw MCP tool；按现行 read-evidence 标准继续冻结，不得仅因 SDK/API 存在就直接新增 manifest。Strategy performance、signals、positions 的 SDK 路径仍指向当前 ViewSet 不存在的 action，同样继续冻结
   - Equity 估值修复已新增 `equity.compute.valuation_repair_status`、`equity.compute.valuation_repair_history`、`equity.read.valuation_repair_config` 与 `equity.read.valuation_repair_config_catalog`；status/history 已移除运行时配置 cache miss 写入，history 保留 canonical provenance，config active/catalog 保持 staff-only 且无配置时不创建默认行
   - Dashboard Alpha 历史读取已新增 `dashboard.read.alpha_history` 与 `dashboard.read.alpha_history_detail`；列表和详情保持 authenticated user scope，详情跳过 Equity asset-name read-through backfill，并禁止从 legacy holding 向 AssetMaster 写入
   - `risk_center.read.post_investment_check`、`risk_center.read.daily_report`、`risk_center.read.daily_report_history`、`pulse.read.current`、`pulse.read.history`、`data_center.read.provider_status`、`data_center.read.macro_series`、`data_center.read.indicator_catalog`、`system.read.task_monitor.statistics`、`task_monitor.read.task_status`、`task_monitor.read.task_list`、`task_monitor.read.dashboard`、`task_monitor.read.celery_health`、`system.read.policy.status`、`regime.read.history` 与 `policy.read.events` 已完成 manifest、core-only fallback、focused API / SDK evidence、core registry、ai capability 与 governance guards 回归
   - `data_center.read.indicator_catalog` 的 governed fallback 已修正为 `indicators + total_count` 对象包裹；底层 SDK/raw MCP list 契约继续保持兼容
   - task monitor read family 的 input/output schema 已与 canonical API serializer 对齐；`ops.task_monitor_snapshot` 已改为零参数的 dashboard + celery health 工作流，不再错误调用必须提供 `task_name` 的 statistics capability
   - `regime.read.history` 与 `policy.read.events` 的 governed fallback 已统一为对象包裹；`policy.read.events` 现在显式要求 canonical API 必需的 `start_date/end_date`
   - policy SDK 已支持 canonical `events` envelope、P0-P3 到 gear 的语义映射与 client-side limit；policy events API 已修复 `PolicyLevel` 枚举通过 `validated_data` 泄漏导致的 JSON 500
   - `scripts/check_mcp_read_evidence.py` 已接入 CI，并对全部 governed read manifests 强制校验 raw tool、server fallback、focused SDK contract、core-only capability call 与 catalog replacement 证据
   - `signal.read.list`、`signal.read.detail` 与 `signal.check.eligibility` 已完成 manifest、core-only fallback、SDK endpoint contract、canonical API success contract、catalog replacement 和 read-evidence guard 收口
   - Signal SDK 已兼容 canonical API 的 `invalidation_description` 字段，并继续向 SDK/MCP 消费方投影稳定的 `invalidation_logic`
   - `signal.check.eligibility` 的 governed 输入只发布 canonical API 实际生效的 `asset_code` 与 `logic_desc`；legacy SDK 中不生效的可选 `target_regime` 不进入新契约
   - `realtime.read.price` 与 `realtime.read.price_batch` 已完成 manifest、core-only fallback、SDK endpoint contract、canonical API success contract、catalog replacement 和 read-evidence guard 收口
   - Realtime 批量报价 governed 输出统一使用 `prices + total_count` envelope，不继续把资产代码动态展开为顶层字段
   - `data_center.read.price_history` 已作为 canonical 历史价格能力完成收口，并统一替换 `data_center_get_price_history` 与 Realtime legacy `get_price_history`；新契约只接受 Data Center 的 `asset_code/start/end/freq/adjustment/limit`，不继承错误的 `period` 参数
   - `realtime.read.market_summary` 已完成 manifest、core-only fallback、SDK endpoint contract、canonical API success contract、catalog replacement 和 read-evidence guard 收口
   - `data_center.read.latest_quote` 已完成收口，保留 canonical quote 的 freshness、`must_not_use_for_decision`、blocking reason 与 provenance contract
   - `data_center.read.news` 已完成收口，输出固定为 `asset_code + total + data` canonical envelope
   - `data_center.read.publisher_catalog`、`data_center.read.publisher_detail`、`data_center.read.indicator_detail`、`data_center.read.indicator_unit_rules` 与 `data_center.read.indicator_unit_rule_detail` 已完成目录 catalog/detail/list 收口；publisher 与 unit-rule list 的 governed 输出统一使用对象 envelope
   - `account.read.macro_sizing_config`、`account.read.positions`、`account.read.portfolio_catalog`、`account.read.portfolio_detail`、`account.read.position_records`、`account.read.transaction_records`、`account.read.capital_flow_records`、`account.read.portfolio_statistics`、`account.read.trading_cost_configs` 与 `account.calculate.trading_cost` 已完成 Account read/calculate 收口；position list/records 已统一切到不会同步 unified ledger 的 read-only canonical endpoint，目录、详情和各类记录均使用命名对象 envelope，费用试算只执行纯计算
   - `agent_proposal.read.proposal_detail`、`beta_gate.read.config_catalog` 与 `filter.read.health` 已完成跨域小批次收口，分别复用 proposal detail、Beta Gate active config list 与 Filter health canonical GET
   - `sentiment.read.index`、`sentiment.read.recent` 与 `sentiment.read.health` 已完成 Sentiment read family 收口；governed 输入只发布 canonical `date`、`days` 和无参数健康检查，拒绝把 legacy 任意 `payload` 固化进新 schema
   - Sentiment 输出分别固定为单条 `SentimentIndexSerializer` 契约、`indices + total` envelope 和 `status/ai_provider_available/cache_count/latest_index_date` 健康契约
   - `events.read.query`、`events.read.metrics` 与 `events.read.status` 已完成 Events read family 收口；query 输入显式限定为 event type、correlation identity、时间范围和 bounded limit，metrics/status 保持零参数
   - `publish_event` 与 `replay_events` 不属于只读迁移范围，后续必须分别按 write 或 workflow 的 confirmation、idempotency 与 audit 标准治理
   - `audit.read.summary` 与 `audit.read.execution_links` 已完成 Audit 首批 read 收口；summary 显式区分 backtest、日期范围和 rolling 30-day default，execution links 继续依赖后端用户范围隔离
   - Audit summary 的半日期范围和 backtest/date 混用会在 governed fallback 中显式拒绝，不再静默退回 SDK 默认窗口
   - `list_portfolios` 与 `get_portfolio` 暂不迁移：legacy raw tool、SDK dataclass 与 canonical serializer 对 `cash/positions` 的输出语义不一致，必须先定义唯一组合摘要/detail 契约
   - `list_portfolios`、`get_portfolio`、`get_positions_detailed`、`get_transactions_detailed` 与 `get_capital_flows_detailed` 已完成迁移：raw tools 不再直接使用通用 HTTP client 拼装分页，而是统一调用正式 Account SDK；组合详情的 positions 与全部持仓读取走 `/api/account/positions/read-only/`，focused contract 证明不会创建统一账户、统一持仓或 ledger mapping
   - `get_sector_realtime_performance` 因 canonical endpoint 不存在继续冻结；`get_top_movers` 因底层通过 POST 触发实时价格快照、存在副作用，不得伪装为 governed read
   - `data_center_get_capital_flows` 的历史参数漂移已完成整改：persisted read 统一使用 `asset_code/start/end/limit`，`period` 仅保留在 provider sync 路径，并由 `data_center.read.capital_flows` 统一 replacement
   - `alpha_trigger.read.trigger_list`、`alpha_trigger.read.candidate_list`、`alpha_trigger.read.candidate_detail` 与 `alpha_trigger.read.performance` 已完成 canonical API success、正式 SDK endpoint、raw MCP、core-only fallback、catalog replacement 和 read-evidence 收口
   - Alpha Trigger 两条 list governed 输出分别固定为 `triggers + total_count` 和 `candidates + total_count`；legacy SDK/raw 继续保持裸数组兼容，candidate detail 在 governed fallback 中只返回 canonical `result` 对象
   - Alpha Trigger serializer 已改为兼容 Domain 实体不存在 `custom_data` 字段的真实模型，避免成功读取路径因 Interface 层字段漂移返回 500
   - Alpha Trigger performance governed 输入已从任意 payload 收紧为 `days/trigger_id`，canonical API 使用显式认证和严格 query serializer，输出固定为 `success/data/summary`；focused contract 已证明 trigger/candidate 记录与时间戳零变化
   - `get_trigger` 暂不迁移：当前只有 SDK/canonical API，没有对应 raw MCP tool；create/evaluate/invalidation/generate 按副作用能力分流，不得混入 read 批次
   - `decision_workflow_get_funnel_context` 已完成候选审计但暂不迁移：当不存在已落库 Rotation signal 时，canonical GET 仍可能通过 `generate_rotation_signal()` 生成并保存信号；同时 SDK 默认发送 `trade_id=unknown`，会把可选 Step 6 审计分支变成默认行为。必须先拆出稳定纯读 snapshot contract，或按 workflow 治理副作用
   - `equity.read.valuation_analysis` 已完成收口：raw、正式 SDK 与 canonical API 已统一为 `stock_code/lookback_days`，GET 显式认证并拒绝未知 query，Application 固定 `hydrate=False`；focused contract 证明 Data Center 与 Equity 相关事实表、镜像表记录和时间戳零变化，并证明 on-demand ensure 未调用
   - `sector.read.rotation_ranking` 已完成收口：canonical GET/POST analyze 已移除空数据惰性同步，显式 update-data 已收紧为 staff-only，未提供 regime 时只读取持久化快照，沪深 300 基准读取固定 `hydrate=False`；正式 SDK `get_rotation_ranking()`、`list_sectors` / `get_sector_recommendations` / `get_hot_sectors` compatibility alias、core-only fallback、catalog replacement 与 Sector 相关表零变化证据已闭合
   - `fund.compute.screen` 已完成 pure-compute 收口，同时修复既有 `fund.read.ranking` 的隐藏写入边界：两条 canonical 契约现在只读取持久化基金主数据、业绩快照、行业配置和偏好，screen 缺省 Regime 只读取最新持久化快照；播种、缺失业绩计算持久化和 Tushare/NAV 同步均被 fail-fast 证据禁止
   - `get_sector_stocks` 已作为跨模块 compatibility alias 收口到 `equity.read.pool_catalog`：它实际只委托 Equity 股票池的 sector filter，不新增重复 Sector capability；legacy `order_by` 因 canonical API 未实现，不进入 governed schema
   - `get_stock_financials` 因正式 SDK 仍直接返回空数组继续冻结，不得借估值分析的财务上下文投影伪造独立 financial history capability
   - `decision_rhythm.read.quota_list`、`decision_rhythm.read.request_list`、`decision_rhythm.read.request_detail` 与 `decision_rhythm.read.summary` 已完成 canonical API success、正式 SDK endpoint、raw MCP、core-only fallback、catalog replacement 和 read-evidence 收口
   - Decision Rhythm 两条 list governed 输出分别固定为 `quotas + total_count` 与 `requests + total_count`；request detail 和 summary 在 governed fallback 中只返回 canonical `result` 对象
   - Decision Rhythm summary 固定为零参数：legacy raw/SDK 虽允许传 `payload`，但 canonical API 当前不读取该参数，因此不得把 `days` 或任意 payload 固化进 governed schema
   - `list_cooldowns`、trend data、request statistics 与 quota by-period 当前缺 raw MCP tool，继续留在证据缺口池；quota reset 已按本计划完成 governed write 收口，其他状态变更路径继续按 write/workflow 治理
   - `regime.read.navigator` 已完成 canonical API success、正式 SDK endpoint、raw MCP、core-only fallback、catalog replacement 和 read-evidence 收口
   - Regime Navigator governed schema 固定为零参数，并将 canonical `success + data` envelope 归一化为 Navigator 业务对象；canonical API 的可选 `as_of_date` 不进入新契约，因为当前 raw tool/SDK 均未发布该参数
   - `BuildRegimeNavigatorUseCase -> CalculateRegimeV2UseCase` 已核验为读取宏观序列、阈值和资产指引配置后的纯计算链，不落库、不刷新、不写缓存、不触发任务
   - `get_action_recommendation` 的历史冻结条件已解除：canonical GET 现固定禁止 stale Pulse 刷新和 `ActionRecommendationLog` 持久化，并由独立 `regime.read.action_recommendation` 承担纯读合同
   - `explain_pulse_dimensions` 继续冻结：当前只有 raw MCP 内部硬编码文本，没有正式 SDK/canonical API/focused contract 证据
   - `regime.read.distribution` 已完成 canonical API success、正式 SDK endpoint、raw MCP、core-only fallback、catalog replacement 和 read-evidence 收口，governed 输出固定为 `distribution + total_count`
   - Regime distribution 的 canonical 第四象限名称已统一为 `Deflation`；SDK 继续兼容读取历史 `Repression`，但不会把过时标签发布进新契约
   - `regime.compute.calculate` 已完成 pure-compute 收口：canonical POST 只读取已持久化宏观事实与 Regime 阈值，严格拒绝未知字段，不保存 `RegimeLog`、不触发 provider sync/任务或业务 cache 写入；SDK 已改用真实 `use_pit/data_source` 契约并移除后端从未实现的 `use_kalman`
   - `get_recommended_assets` 继续冻结：当前只有 raw MCP 内部硬编码推荐表，没有正式 SDK/canonical API/focused contract
   - Config Center 直接读取子集已完成 governed 收口，覆盖能力目录、Qlib runtime、训练模板、Alpha universe 目录与成员、训练任务列表与详情；所有路径均保留 staff-only canonical permission
   - Config Center list governed 输出固定为命名 envelope，Qlib runtime 读取已消除 `SystemSettingsModel.get_settings()` 的冷启动隐式写入
   - `get_config_center_snapshot` 继续冻结：跨模块 summary 聚合在副作用证据逐条闭合前不得作为单一 read capability 发布
   - Rotation 直接读取子集已完成 governed 收口：`rotation.read.regime_catalog`、`rotation.read.template_catalog`、`rotation.read.account_config_list`、`rotation.read.account_config_detail`、`rotation.read.asset_catalog`、`rotation.read.asset_detail` 与 `rotation.read.latest_signal_list`
   - Rotation list 输出固定使用 `regimes/templates/configs/assets/signals + total_count` 命名 envelope；账户配置继续依赖 canonical API 的用户范围隔离，详情输入只允许 `config_id` 或 `account_id` 二选一
   - `get_rotation_recommendation` 继续冻结：无可用信号时会调用生成链并持久化新信号；`compare_assets` 已收口为 `rotation.compute.asset_comparison`，固定只发布 `asset_codes`，价格读取禁止回写进程缓存，计算链不解析 Regime、不保存 Rotation 记录；`get_correlation_matrix` 已完成纯计算证明并作为现有 Hedge capability 的 legacy alias 收口
   - `list_rotation_assets` 与 `get_asset_info` 继续冻结：两者进入带价格的 integration service，不得用本批次纯资产主数据 API 的证据替代实时行情路径证据
   - Asset Analysis 直接读取子集已完成 governed 收口：`asset_analysis.read.weight_config_catalog`、`asset_analysis.read.current_weight` 与 `asset_analysis.read.pool_summary`
   - 权重目录和当前权重保持 legacy raw/SDK 已证明的零参数契约；当前权重在数据库没有配置时只返回未持久化默认值，focused API contract 已证明读取前后不会创建 `WeightConfigModel`
   - 资产池摘要只发布 canonical API 实际执行的可选 `asset_type`，不继承 legacy raw tool 的任意 `payload`；输出固定为 `success + asset_type + summary`
   - `asset_multidim_screen` 与 `asset_pool_screen` 继续冻结：两者会进入跨模块上下文、评分和资产池构建链，且存在 POST/composite 语义，不能用三个直接 GET 的纯读证据替代
   - Equity 估值持久化读取子集已完成 governed 收口：`equity.read.valuation_repair_list`、`equity.read.valuation_freshness` 与 `equity.read.valuation_quality_latest`
   - valuation repair list 只读取持久化快照并归一化为 `repairs + total_count + query`；freshness 与 latest quality 只读取现有估值记录和质量快照，不触发 provider sync、repair scan、validation 或快照创建
   - `get_stock_valuation` 因 SDK `as_of_date` 与 canonical `lookback_days` 参数漂移继续冻结；repair status/history 需单独证明计算链纯读，score/detail/recommendation/composite analysis 需补唯一 canonical owner 或重新分类 POST/composite 语义
   - valuation scan/sync/validate 与配置 update/delete 等变更路径继续按 workflow/write 治理；valuation config draft creation 与 activation 已分别按 preview-first write 标准收口，rollback 作为 activation 的等价 alias 统一治理
   - Equity 当前股票池目录已完成 governed 收口：`equity.read.pool_catalog` 通过 authenticated canonical pool GET、正式 SDK 命名 envelope、raw `list_stocks` replacement、core-only fallback、catalog replacement 与 focused pure-read contract
   - 股票池能力只发布 `sector/min_score/limit`；SDK-only `max_score` 不进入 governed schema。默认链已证明 cache miss 不回填股票池缓存、估值/财务保持 `hydrate=False`、Regime V2 不保存快照，相关业务表计数在 GET 前后保持不变
   - `get_stock_detail` 继续作为同一股票池快照的 legacy 客户端查找，不拆成重复 capability；screen/recommendation/refresh 仍需按 pure calculation、workflow 或 write 分流
   - Dashboard Auto Advisor 外部只读能力已完成 governed 收口：`decision.read.advisor_sheet`、`dashboard.read.auto_advisor_console`、`dashboard.query.auto_advisor`、`dashboard.read.auto_advisor_weekly_report`、`dashboard.read.auto_advisor_weekly_report_history` 与 `dashboard.read.auto_advisor_notifications`
   - 动态 advisor-sheet 链已消除三类隐式写入：资产名称解析 cache miss 不再写缓存，手工组合读取不再自动同步统一账户/持仓/ledger mapping，风险 floor/template 缺失时只返回未持久化默认对象
   - focused API contract 已在同一业务表计数窗口内证明 decision sheet、console、query 与 weekly report GET 不新增账户、持仓、映射、推荐、配额、冷却、行情、风险配置、周报或通知记录；持久化历史读取继续保持 authenticated user scope
   - weekly report POST 继续按 workflow/write 治理；除已具备独立纯读证据的 equity curve、asset allocation 与 position catalog 外，Dashboard v1 页面聚合及内部 Alpha 视图继续保持 internal-only
   - Dashboard v1 页面聚合及内部 Alpha/持仓视图默认保持 internal-only；只有完成 canonical JSON、用户范围和 SQL 零写证明的独立任务能力才允许进入外部 governed registry
   - 机器基线只记录已通过当前守卫的验收状态，不记录“只入统计、未验收完成”的中间值

#### 0.2.3 当前默认续做顺序

1. 第一优先项：重新审计 raw-tool gap inventory 并锁定下一条证据链完整的候选。`alpha_trigger.read.performance`、`equity.read.valuation_analysis`、`sector.read.rotation_ranking` 与 `fund.compute.screen` 已完成，不得继续占用默认续做入口；`get_stock_financials` 因正式 SDK 为空实现继续冻结
   - `account.create.unified_account` 已完成收口，不再占用默认续做入口：legacy `create_account`、正式 Account SDK、canonical `/api/account/accounts/`、owner-scoped 名称冲突规则、real/simulated 创建合同、pure-read preview、confirmation、required idempotency、MCP lifecycle audit、catalog replacement 和 focused SDK/API/registry contract 已闭合
   - 统一账户创建与 `trading.create.simulated_account` 保持两个语义：前者允许 real/simulated 并走 Account canonical API，后者只创建模拟交易账户并保留模拟交易专用输入；不得为了减少 capability 数量错误合并
   - `account.create.position` 已完成收口，不再占用默认续做入口：legacy `create_position`、正式 Account SDK GET/POST、canonical owner/observer 权限、统一账本同资产合并、buy ledger entry、pure-read preview、confirmation、required idempotency、MCP lifecycle audit 与 catalog replacement 已闭合；该能力只维护内部持仓账本，不发送外部 broker order
   - Account 普通 positions/transactions/capital-flows 导入的 CSV/JSON transport 已统一到现有三个 governed capability：CSV raw tools 只解析 rows 后委托对应 JSON importer，不再形成重复 capability
   - `account.import.broker_trades` 已完成独立收口，不再占用默认续做入口：统一结构化 trades schema 同时替代 Broker preview/import 的 CSV/JSON legacy transport；canonical preview 保持 owner scope 且不写账户映射、批次、交易、持仓、统一成交或 execution link，确认后才通过正式 Account SDK 同步多账本与推荐匹配；成交级 `broker_trade_key` 去重与治理层 required idempotency 同时保留
   - `beta_gate.create.config` 已完成收口，不再占用默认续做入口：canonical config route 已确认注册，读取保持 authenticated，创建与 rollback mutation 均收紧为 staff-only；create preview 只通过正式 Beta Gate SDK 读取完整配置目录，拒绝重复 config ID，披露同风险档位 active 配置替换和全局版本递增，确认后才调用正式 SDK create
   - `beta_gate.rollback.config` 已作为独立能力完成收口：rollback 只按路径 `config_id` 激活既有配置并停用同风险档位当前 active，不创建新版本；已 active、已过期和不存在目标均在确认前或 canonical mutation 边界拒绝，legacy `rollback_beta_gate_config` 不再复用 create capability
   - `beta_gate.compute.config_comparison` 已完成收口：正式 SDK 已从错误 POST 修正为 canonical authenticated GET，并兼容归一化 legacy `from/to`、`version_a/version_b` 到 `version1/version2`；governed schema 只发布两个明确配置标识，不发布无参数 recent-version 目录语义
   - `beta_gate.compute.batch_evaluation` 已完成收口：canonical test API 使用严格 serializer，按请求 `risk_profile` 选择 active 配置，无持久化配置时只使用稳定的同档位内存默认配置；外部 schema 不发布旧 API 实际未生效且领域语义不完整的 `current_portfolio_value`，legacy `test_beta_gate` 已建立 replacement
   - `rotation.create.asset` 已完成收口，不再占用默认续做入口：global asset catalog 的 canonical create/update/delete/import-defaults 已收紧为 staff-only mutation，create preview 只通过正式 Rotation SDK 精确读取目标 code，active/inactive 重码均在确认前拒绝，commit 只调用正式 `create_asset()`；legacy replacement、required idempotency、MCP audit、catalog replacement 与 focused API/registry contract 已闭合
   - `rotation.update.asset` 已完成收口：只发布显式 partial-update 字段，preview 通过正式 SDK 读取当前记录并计算 changed fields，空更新和无变化在确认前拒绝，停用/恢复状态明确披露，commit 固定调用正式 PATCH；legacy replacement、required idempotency、audit 与 catalog regression 已闭合
   - `rotation.delete.asset` 已完成收口：governed 契约只允许默认软删除，preview 精确读取 active 资产并披露记录保留/no-hard-delete/no-trade 边界，inactive 目标在确认前拒绝，commit 只调用正式 SDK 默认 delete；legacy replacement、required idempotency、audit 与 catalog regression 已闭合
   - `rotation.import.default_assets` 已完成独立收口：默认资产清单只由服务端 `default_assets.py` 持有，staff-only canonical preview GET 纯读分类 `created/reactivated/updated/unchanged`，commit 只调用正式 SDK import；不得借用 create/update/delete 的 preview 或确认 token
   - canonical 名称冲突必须按 authenticated owner scope 校验；不同用户允许使用相同账户名，同一用户重复名称必须在 preview 和真实 mutation 前拒绝
   - real 账户默认关闭 auto trading，simulated 账户默认启用；preview 必须披露该状态和账户创建副作用，并明确不执行交易
   - `dashboard.create.auto_advisor_weekly_report` 已完成收口，不再占用默认续做入口：legacy `create_auto_advisor_weekly_report`、正式 Dashboard SDK、authenticated canonical GET/POST、无持久化周报与历史 preview、create/overwrite 判断、confirmation、required idempotency、MCP lifecycle audit、catalog replacement 和 focused SDK/API/registry contract 已闭合
   - 周报写能力必须显式提供 ISO 日期 `as_of`，禁止 confirmation 期间日期漂移；preview 只允许读取目标周报投影和用户范围内的持久化历史，commit 只允许调用正式 SDK POST
   - preview 必须披露周报 snapshot upsert、投资日记 snapshot、Dashboard notification 与 operation audit 副作用，并明确不执行交易
   - `risk_center.generate.daily_report` 已完成收口，不再占用默认续做入口：raw `generate_risk_center_daily_report`、正式 Risk Center SDK、canonical owner/staff scope、投后检查纯 preview、同日 create/overwrite 检测、confirmation、required idempotency、generated-by 与 MCP audit、catalog replacement 和 write-evidence 已闭合
   - governed schema 强制显式 `report_date`，不继承 raw tool 的“缺省为当天”行为，避免 preview 与 commit 跨午夜写入不同日期；preview 只调用正式 SDK `check_post_investment()` 与日期范围 `list_daily_reports()`，commit 只调用 `generate_daily_report()`
   - 统一 write-like 动作分类器已加入 `generate`，read/confirmation/preview/audit/evidence 守卫继续复用同一分类入口，不得把生成持久化报告误判为 read
   - `risk_center.update.account_policy` 已完成收口，不再占用默认续做入口：raw `upsert_account_risk_policy`、正式 Risk Center SDK、canonical owner/staff scope、focused create/update 与跨账户拒绝合同、pure-read preview、confirmation、required idempotency、双层 audit、catalog replacement 与 write-evidence 已闭合
   - preview 通过正式 SDK 读取调用方可见的策略目录判断 create/update；提供 `template_id` 时额外读取模板目录并在确认前拒绝不存在的模板；canonical `UpsertAccountRiskPolicyUseCase` 同样执行持久化模板存在性校验，避免 preview/commit 竞态或直接 API 调用把无效模板静默置空；commit 只调用正式 SDK `upsert_account_policy()`
   - `risk_center.update.floor` 已完成收口，不再占用默认续做入口：raw `update_risk_floor`、正式 Risk Center SDK、canonical staff-only UseCase、focused API mutation contract、pure-read preview、confirmation、required idempotency、audit、catalog replacement 与 write-evidence 已闭合
   - governed schema 要求非空 `reason`，只发布名称、风险百分比、强制止损与 hard exclusions 等安全更新字段，不发布可能让全局底线失活的 `is_active=false`；preview 只读取当前 floor 并在无实际变化时拒绝，commit 只调用正式 SDK `update_floor()`
   - `equity.create.valuation_repair_config` 已完成收口，不再占用默认续做入口：raw `create_valuation_repair_config`、正式 Equity SDK、canonical staff-only API、focused create success contract、pure-read preview、confirmation、required idempotency、audit、catalog replacement 与 write-evidence 已闭合
   - preview 只通过正式 SDK 读取 config catalog 和 active config，计算 latest persisted version、expected next version 与字段差异；不会创建草稿、清理配置缓存或修改 active 状态
   - commit 只调用正式 Equity SDK create 方法；治理层 `preview_only/idempotency_key` 不下传业务 SDK，canonical 创建结果保持递增版本、inactive draft 和 `created_by` 审计字段
   - `equity.activate.valuation_repair_config` 已完成收口，不再占用默认续做入口：正式 Equity SDK 已补精确 config detail 读取；preview 读取目标配置和当前 active 配置，披露停用旧配置、激活目标、更新时间与清理运行时缓存的副作用；commit 只调用正式 activate action
   - legacy `activate_valuation_repair_config` 与 `rollback_valuation_repair_config` 的 canonical 行为完全等价，统一 replacement 到同一个 activation capability，不另建重复 rollback 能力；目标已经 active 时必须在确认前拒绝无意义 mutation
   - 当前默认下一步重新固定为 raw-tool gap 审计；只有新的候选同时具备 raw tool、正式 SDK、真实 canonical owner、focused success contract 和可证明副作用边界时，才可更新为下一迁移项
   - `create_beta_gate_config` 的历史 route 缺失结论已由当前代码事实纠正：canonical config route、正式 SDK、staff-only mutation、focused API contract、registry preview/commit、catalog replacement 和治理守卫现已闭合；不得再把它列为冻结候选
   - 刚完成迁移：`prompt.create.template` 已通过 staff-only canonical mutation、active/inactive 全局名称唯一检查、正式 Prompt SDK 精确查询、无写入 preview、confirmation、required idempotency、audit、catalog replacement 与 write-evidence；下一默认入口不得继续停留在 `create_prompt_template`
   - Prompt governed schema 只发布真实模板字段；preview 同名时在确认前失败，commit 只调用正式 SDK create endpoint
   - 刚完成迁移：`policy.create.event` 已通过 authenticated read + staff-only canonical mutation、正式 Policy SDK、同日事件只读 preview、confirmation、required idempotency、audit、catalog replacement 与 write-evidence；下一默认入口不得继续停留在 `create_policy_event`
   - Policy governed schema 固定使用 canonical `event_date/level/title/description/evidence_url`，不发布 legacy `event_type/gear`；preview 明确披露 P2/P3 创建可能触发政策告警服务
   - 刚完成迁移：`account.update.macro_sizing_config` 已通过 raw tool、正式 Account SDK、staff-only canonical API、无写入 preview、confirmation、required idempotency、audit、catalog replacement 与 write-evidence；下一默认入口不得继续停留在宏观仓位配置更新
   - 该 governed 契约固定使用 partial PATCH 语义，只发布 canonical serializer 接受的配置字段；空变更必须在 handler 层拒绝，preview 只读取当前 active 版本，禁止创建相同配置版本
   - 刚完成迁移：`dashboard.read.alpha_history` 与 `dashboard.read.alpha_history_detail` 已通过 authenticated canonical GET、正式 SDK stable envelope、raw MCP、core-only fallback、catalog replacement、read-evidence 和 focused pure-read regression；下一默认入口不得继续停留在 Dashboard Alpha 历史读取
   - Dashboard Alpha history detail 必须继续跳过 Equity stock-context read-through backfill，并保持 legacy holding 名称仅用于响应投影、不写入 `AssetMasterModel`；Alpha candidates、decision-chain v1 与 refresh 路径仍按既有 internal-only 或 workflow 边界分流
   - 刚完成迁移：Equity valuation repair status/history 纯计算与 active config/config catalog staff-only 读取已通过 canonical API、正式 SDK、raw MCP、core-only fallback、catalog replacement、read-evidence 与 focused regression；下一默认入口不得继续停留在这四条路径
   - Equity repair status/history 必须继续保持 `use_cache=False`，config catalog 的 `limit` 只允许 SDK 本地截断；后续不得重新引入 cache miss 写入或伪 API 参数
   - 刚完成迁移：`strategy.compute.position_rule` 与 `strategy.compute.position_management` 已通过 owner/staff scoped canonical POST、纯计算业务表计数、正式 SDK endpoint、raw MCP、core-only fallback、catalog replacement 与 read-evidence；下一默认入口不得继续停留在 Strategy 仓位 evaluate
   - Strategy Script Config、Rule Condition、Assignment 缺 raw MCP tool，performance、signals、positions 缺真实 canonical action；这些路径继续冻结，不得为扩大迁移统计补猜测契约
   - 刚完成迁移：`decision.read.advisor_sheet`、`dashboard.read.auto_advisor_console`、`dashboard.query.auto_advisor`、`dashboard.read.auto_advisor_weekly_report`、`dashboard.read.auto_advisor_weekly_report_history` 与 `dashboard.read.auto_advisor_notifications` 已通过 raw tool、正式 SDK、canonical API 用户范围和纯读合同、core-only fallback、catalog replacement 与 read-evidence；下一默认入口不得继续停留在 Auto Advisor read family
   - Dashboard weekly report POST 继续按 workflow/write 分流；除已具备独立 canonical GET 与 SQL 零写证明的 equity curve、asset allocation 和 position catalog 外，其余 v1 页面聚合及内部 Alpha 视图继续保持 internal-only
   - 刚完成迁移：`equity.read.valuation_repair_list`、`equity.read.valuation_freshness` 与 `equity.read.valuation_quality_latest` 已通过 raw tool、正式 SDK、canonical API、core-only fallback、catalog replacement、read-evidence 和 focused regression；下一默认入口不得继续停留在 Equity 估值持久化读取
   - Equity 其余路径已按参数漂移、计算链纯读、POST/composite、workflow/write、staff 权限和 fallback 语义分流；证据未闭合前不得顺带迁移
   - 刚完成迁移：`equity.read.pool_catalog` 已通过真实默认读取链纯读计数、正式 SDK envelope、raw replacement、core-only fallback、catalog replacement 与 read-evidence；下一默认入口不得继续停留在 `list_stocks`
   - `get_stock_detail` 不另建重复 capability；Equity screen/recommendation/refresh 与其他 composite 路径继续按副作用证据分流
   - Sector `get_sector_stocks` 与 Equity 股票池属于同一语义，已共享 `equity.read.pool_catalog` replacement；不得再以“板块成分股”名义创建第二个 manifest
   - 刚完成迁移：`hedge.compute.correlation_matrix` 已通过 canonical POST 纯计算、价格 cache-write 禁止、业务表计数不变、正式 SDK、raw replacement、core-only fallback、catalog replacement 与 read-evidence；下一默认入口不得继续停留在 `get_hedge_correlation_matrix`
   - Rotation `get_correlation_matrix` 已确认为同一输入输出语义，不新增重复 capability；它现作为 `hedge.compute.correlation_matrix` 的第二个 legacy alias，由同一个 canonical owner、fallback 和 schema 统一替换
   - Rotation 兼容 POST 也已改为 `cache_result=False`，focused API contract 证明不写价格缓存且 Rotation 业务表计数不变
   - 刚完成迁移：`rotation.compute.asset_comparison` 已通过 canonical POST、正式 SDK、raw MCP、core-only fallback、catalog replacement、read-evidence 与 focused pure-compute contract；固定 1/3/6 月动量计算只发布真实生效的 `asset_codes`，legacy `lookback_days` 继续兼容但不进入 governed schema
   - Rotation 资产比较已证明不解析 Regime、不写价格缓存且全部 Rotation 业务表计数不变；下一默认入口不得继续停留在 `compare_assets`
   - Hedge 单对相关性计算会保存历史，不能与矩阵能力合并；effectiveness、monitoring 和 portfolio update 继续留在副作用审计池
   - 刚完成迁移：`asset_analysis.read.weight_config_catalog`、`asset_analysis.read.current_weight` 与 `asset_analysis.read.pool_summary` 已通过 raw tool、正式 SDK、canonical API、core-only fallback、catalog replacement、read-evidence 和固定 Terminal/TUI/SDK 回归；下一默认入口不得继续停留在 Asset Analysis 直接读取
   - `asset_multidim_screen` 与 `asset_pool_screen` 已形成明确冻结结论，必须先完成 pure calculation / workflow 副作用分类，不得混入下一批 direct read
   - 刚完成迁移：`regime.read.distribution` 已通过 raw tool、SDK、canonical API、core-only、catalog replacement 与 read-evidence 全链路；下一默认入口不得继续停留在 Regime distribution
   - `calculate_regime` 已重新分类并由 `regime.compute.calculate` 完成 raw tool、正式 SDK、canonical API、core-only fallback、catalog replacement 与 read-evidence 收口；`get_recommended_assets` 继续冻结，因为缺少 SDK/canonical API 证据
   - 刚完成迁移：`regime.read.navigator` 已通过 raw tool、SDK、canonical API、core-only、catalog replacement 与 read-evidence 全链路；下一默认入口不得继续停留在 Navigator
   - `get_action_recommendation` 已完成纯读拆分并迁入 `regime.read.action_recommendation`；`explain_pulse_dimensions` 仍因缺少 SDK/canonical API 证据冻结
   - 刚完成迁移：`audit.read.summary` 与 `audit.read.execution_links` 已通过 raw tool、SDK、canonical API、core-only、catalog replacement 与 read-evidence 全链路；下一默认入口不得继续停留在这两项
   - Audit attribution、indicator performance、threshold validation 等 SDK 读取当前缺少 raw MCP tool，继续留在证据缺口池
   - Sector rotation ranking 已完成：`GET /api/sector/rotation/` 与 POST analyze 不再惰性调用 `UpdateSectorDataUseCase`，`list_sectors`、`get_sector_recommendations`、`get_hot_sectors` 统一 replacement 到 `sector.read.rotation_ranking`；score/detail/analyze/performance 派生语义仍需独立 canonical contract，不得直接复用排名证据
   - 刚完成迁移：`fund.compute.screen` 已通过 authenticated 严格 canonical POST、正式 SDK、raw MCP、core-only fallback、catalog replacement、read-evidence 和 focused pure-compute contract；screen 缺省 Regime 只读取最新持久化快照
   - `fund.read.ranking` 已同步修复隐藏写入边界，与 screen 共同改用 `get_persisted_funds_with_performance()`；`fund.read.detail`、`fund.read.nav_history` 与 `fund.read.holdings` 继续保持原 governed 契约
   - Fund governed 契约只发布 canonical API 真正处理的参数：NAV 不发布当前 API 未执行的 legacy `limit`，holdings 不发布兼容别名 `as_of_date`
   - `get_fund_score` 继续冻结：当前没有 canonical score endpoint，SDK 只返回兼容失败 payload
   - `list_funds` 与 `get_fund_recommendations` 继续冻结：两者包含兼容过滤、代码归一化或额外详情请求，尚未定义唯一输出契约
   - `get_fund_performance` 已完成副作用审计并冻结为 workflow/write 候选：canonical POST 计算成功后会调用 `save_fund_performance()` 持久化 `FundPerformanceModel`，不得按 read 或 pure compute 迁移
   - `screen_funds` 已按 pure compute 完成 `fund.compute.screen` 收口；`list_funds`、recommendation、hot-fund、score 与其他分析路径继续冻结，不能借 screen/ranking 证据迁移
   - 刚完成迁移：`backtest.read.detail` 与 `backtest.read.list` 已通过 canonical API success、正式 SDK endpoint、raw MCP、core-only fallback、catalog replacement 和 read-evidence 全链路
   - Backtest list governed 输入只发布 canonical API 实际处理的 `status` 与 `limit`；legacy/SDK 的 `strategy_name` 当前会被 ViewSet 忽略，因此不得固化进新 schema
   - `get_backtest_equity_curve` 的历史冻结条件已解除：canonical DRF action 已补齐并在 owner scope 完成前固定 staff-only，现由 `backtest.read.equity_curve` 承担持久化纯读合同
   - Backtest run/delete/rerun/decision replay 继续留在 write/workflow 审计池，不得与本次只读详情/列表批次混迁
   - 刚完成迁移：`factor.read.definition_catalog` 与 `factor.read.config_catalog` 已通过 authenticated canonical GET、正式 SDK、raw MCP、core-only fallback、catalog replacement、focused pure-read contract 与 read-evidence 全链路
   - Factor definition governed 输出固定为 `factors + by_category + total_count`，config governed 输出固定为 `configs + total_count`；两条路径只读取 active definitions 或持久化 configs，不计算分数、不生成组合、不修改 activation
   - 刚完成迁移：`factor.compute.top_stocks` 已通过 canonical POST、正式 SDK、raw MCP、core-only fallback、catalog replacement、read-evidence 与 focused pure-compute contract；默认 `medium` 偏好现形成有效正权重，价格读取固定禁止回写进程缓存，相关业务表计数保持不变
   - 刚完成迁移：`factor.compute.stock_explanation` 已通过 canonical POST、正式 SDK focus contract、raw MCP、core-only fallback、catalog replacement、read-evidence 与 focused pure-compute contract；价格读取禁止回写进程缓存，Factor/Equity 相关业务表计数保持不变
   - Factor explanation 的 `value/growth/quality/balanced` 权重映射已收口到正式 SDK，canonical endpoint 已修复不存在 `StockInfoRepository` 导致成功请求始终返回 500 的缺陷；下一默认入口回到 raw-tool gap 审计
   - Factor 其余路径继续冻结：`FactorModule.get_portfolio()` 仍直接导入 `apps.factor.infrastructure.repositories`；create portfolio 等 POST/composite 路径必须先完成 workflow/write 副作用分类
   - 刚完成迁移：`alpha.read.provider_status`、`alpha.read.universe_catalog` 与 `alpha.read.health` 已通过 canonical API success、正式 SDK endpoint、raw MCP、core-only fallback、catalog replacement 和 read-evidence 全链路
   - Alpha 本批只接收零参数直接 GET；inference/Qlib-data overview 继续核验 staff role 与聚合输出契约，trigger/refresh 明确按 workflow/write 分流
   - `get_alpha_factor_exposure` 继续冻结：当前 SDK/raw 路径直接启动本地 Django `AlphaService`，不具备 canonical HTTP endpoint 证据
   - `get_alpha_stock_scores` 已完成副作用审计并冻结为 workflow 候选：canonical GET 的 Qlib cache miss 会投递推理任务并写 throttle cache，provider 降级或全失败会创建/更新 Alpha 告警，不得按 read-hint 直接迁移
   - 后续若保留“查询评分”语义，必须先提供严格 cached-only canonical GET；若保留现有自动推理/降级语义，则按 workflow 的 preview、confirmation、idempotency、audit 与状态查询整链治理
   - 刚完成迁移：`alpha_trigger.read.trigger_list`、`alpha_trigger.read.candidate_list` 与 `alpha_trigger.read.candidate_detail` 已通过 canonical API success、SDK endpoint、raw MCP、core-only、catalog replacement 与 read-evidence 全链路
   - Alpha Trigger list 契约保持零参数：trigger list 读取 active triggers，candidate list 读取 actionable candidates；canonical API 中未被 legacy SDK/raw 发布或未实际生效的过滤参数不进入 governed schema
   - Alpha Trigger trigger detail 因缺 raw tool 继续留在证据缺口池；performance 已确定为下一条候选，先补显式认证、严格 query contract、focused success 与纯读零变化证据；create/evaluate/invalidation/generate 继续按 write/workflow 副作用分类
   - 刚完成迁移：`decision_rhythm.read.quota_list`、`decision_rhythm.read.request_list`、`decision_rhythm.read.request_detail` 与 `decision_rhythm.read.summary` 已通过 canonical API success、SDK endpoint、raw MCP、core-only、catalog replacement 与 read-evidence 全链路
   - Decision Rhythm quota/request list 与 summary 保持零参数；canonical API 支持但 legacy raw/SDK 未发布的过滤参数，以及 summary 当前忽略的 payload，不进入 governed input schema
   - Decision Rhythm cooldown/trend/statistics/by-period 读取因缺 raw tool 继续冻结；quota reset 已完成 `decision.reset.quota` 收口，submit/execute/cancel 继续沿既有 governed write 链路
   - 刚完成迁移：`decision.read.recommendation_list` 与 `decision.read.transition_plan_detail` 已通过 raw MCP、正式 SDK、canonical API success、core-only fallback、catalog replacement 与 read-evidence 全链路
   - Decision recommendation list 将 canonical `success + data` 归一化为 `recommendations + total_count + page + page_size`；transition plan detail 将同类 envelope 归一化为已保存计划对象，两条路径均已证明只执行仓储和展示信息读取
   - `decision_workflow_get_funnel_context` 明确冻结：cache miss 时 `GetActionRecommendationUseCase(prefer_cached=True)` 会重新计算并持久化 `ActionRecommendationLog`，不能仅凭 GET method 或关闭 Pulse refresh 将其认定为 pure read
   - 刚完成迁移：`config_center.read.capability_catalog`、`config_center.read.qlib_runtime`、`config_center.read.qlib_training_profiles`、`config_center.read.alpha_universe_catalog`、`config_center.read.alpha_universe_members`、`config_center.read.qlib_training_runs` 与 `config_center.read.qlib_training_run_detail` 已通过 raw MCP、正式 SDK、canonical API success、core-only fallback、catalog replacement 与 read-evidence 全链路
   - Config Center list 输出统一使用 `capabilities/profiles/universes/runs + total_count` 命名 envelope；所有已迁移读取能力在 manifest 中声明 `required_roles=("staff",)`，canonical API 继续由 `IsAdminUser` 执行真实权限校验
   - Qlib runtime GET 已拆出严格只读设置访问：系统设置不存在时只构造未持久化默认对象，不再通过 `get_or_create` 产生隐式写入；focused test 会验证读取后数据库仍无设置行
   - `get_config_center_snapshot` 继续冻结：该路径聚合多个跨模块 summary builder，当前尚未逐条证明不存在刷新、缓存更新、外部状态探测或其他隐式副作用，不能因为入口是 GET 就整体提升为 governed read
   - 刚完成迁移：Rotation 象限目录、模板目录、账户配置列表/详情、资产主数据列表/详情与最新持久化信号已通过 raw MCP、正式 SDK、canonical API success、core-only fallback、catalog replacement 与 read-evidence 全链路
   - Rotation latest-signal governed fallback 只读取 `/api/rotation/signals/latest/` 的持久化结果，不调用 recommendation 或 generate-signal；账户配置详情会拒绝同时缺少或同时提供 `config_id/account_id`
   - Rotation recommendation、带价格资产与资产比较继续按副作用证据分流；相关性矩阵已作为现有 `hedge.compute.correlation_matrix` 的 legacy alias 收口，不得再次创建 Rotation 重复 capability
   - 刚完成项：`list_risk_center_daily_reports` 已正式收口为 `risk_center.read.daily_report_history`
   - 刚补齐闭环：`pulse.read.current`、`pulse.read.history`、`data_center.read.provider_status`、`data_center.read.macro_series`、`data_center.read.indicator_catalog`、task monitor 五条 read family、`system.read.policy.status`、`regime.read.history` 与 `policy.read.events` 已完成 core-only / catalog / SDK / integration 证据回归
   - 刚完成迁移：`signal.read.list`、`signal.read.detail` 与 `signal.check.eligibility` 已通过 read-evidence、SDK、API、core registry 和 catalog 回归；下一默认入口继续回到未迁移 legacy 候选审计
   - 刚完成迁移：`realtime.read.price` 与 `realtime.read.price_batch` 已通过同一证据链；价格预警 CRUD 仍保持 unsupported legacy contract，不得与本次价格读取迁移混同
   - 刚完成迁移：`data_center.read.price_history` 与 `realtime.read.market_summary` 已通过 raw tool、SDK、canonical API、core-only、catalog replacement 和 read-evidence 全链路；下一默认入口继续回到未迁移 legacy 候选审计
   - 刚完成迁移：`data_center.read.latest_quote` 与 `data_center.read.news` 已通过同一证据链；下一默认入口不得继续停留在这两项
   - 刚完成迁移：Data Center publisher catalog/detail、indicator detail 与 unit-rule detail/list read family 已完成 core-only、SDK、API、catalog replacement 与 read-evidence 回归
   - 刚完成迁移：Account 宏观仓位配置、组合目录/详情、持仓摘要/明细、交易明细、资金流水明细、组合统计、交易费率配置列表与纯费用试算已完成 core-only、SDK、API、catalog replacement 与 read-evidence 回归
   - 刚完成迁移：Agent Proposal detail、Beta Gate config catalog 与 Filter health 已通过同一证据链；下一默认入口继续从 inventory 中筛选未 replacement 的 read，不回头重复迁移这些能力
   - 刚完成迁移：Sentiment index、recent 和 health 已通过 raw tool、SDK、canonical API、core-only、catalog replacement 与 read-evidence 全链路；下一默认入口不得继续停留在 `get_sentiment_index`、`get_sentiment_recent` 或 `get_sentiment_health`
   - 刚完成迁移：Events query、metrics 和 status 已通过 raw tool、SDK、canonical API integration、core-only、catalog replacement 与 read-evidence 全链路；下一默认入口不得继续停留在 `query_events`、`get_event_metrics` 或 `get_event_bus_status`
   - Account 组合目录/detail 和三个 `*_detailed` 工具已解除冻结：新增独立稳定 envelope 和正式 SDK contract；不得再把它们列入 raw-tool gap。原 `/api/account/positions/` 仍承担统一账本兼容职责，但 governed read 与 legacy read compatibility 已切到严格无同步副作用的 `/api/account/positions/read-only/`
   - 明确冻结：`get_sector_realtime_performance` 在补齐 canonical endpoint 前不得迁移；`get_top_movers` 在改为无副作用的 cached GET 或重新定义 workflow/write 语义前不得迁移
   - 刚完成迁移：Sector rotation GET 已拆除空数据惰性更新，基准行情读取禁止 hydration；list/recommendation/hot-sector 同义 alias 已统一收口为 `sector.read.rotation_ranking`，score/detail/analyze/performance 继续按独立语义审计
   - `data_center.read.capital_flows` 已完成契约统一：persisted read 只发布 `asset_code/start/end/limit`，legacy `period` 继续仅用于 provider sync；严格 serializer、alias 解析、limit、纯读 API/SDK、core-only fallback、catalog replacement 与 read-evidence 已闭合
   - Fund persisted-only ranking/detail/NAV/holdings 与 pure-compute screen 已完成，不得继续挂在默认下一步；下一条默认入口回到 raw-tool gap 审计，确认新的证据闭合候选后再更新本文
   - Backtest detail/list 与 staff-only equity curve 已完成，不得继续挂在默认下一步；run/delete/rerun/replay 继续按 write/workflow 冻结结论分流，detail/list 的历史 owner scope 仍需单独整改
   - Factor definition/config catalog 与 top-stocks pure compute 已完成，不得继续挂在默认下一步；portfolio、解释和组合生成路径继续按架构违规或 POST/composite 结论分流
   - Alpha provider status/universe/health 与两条 staff-only 运维 overview 已完成，不得继续挂在默认下一步；trigger/refresh 与 factor exposure 按上述边界继续审计
   - `alpha.read.inference_ops_overview` 与 `alpha.read.qlib_data_ops_overview` 已完成 raw tool、正式 SDK、staff-only canonical API、真实默认链纯读合同、core-only fallback、catalog replacement 与 read-evidence 收口
   - Alpha inference overview 已改用非清理型 cache lock inspection；runtime Qlib 配置在 singleton 缺失时只构造未持久化默认对象，不再由 GET 冷启动写库
   - 刚完成迁移：Rotation `get_rotation_config` 已收口为 `rotation.read.config_detail`；raw tool 通过正式 SDK `get_all_configs()` 调用 authenticated canonical `GET /api/rotation/configs/`，focused API 已证明底层只读取持久化 `RotationConfigModel` 且计数不变
   - `rotation.read.config_detail` 只接受 `config_name`，输出固定为 `success + config + available_configs + error`；activate/deactivate/generate_signal 继续按 write/workflow 分流，不得借配置读取证据顺带迁移
   - Equity `get_stock_financials` 已明确冻结：正式 SDK 当前直接返回空数组，canonical API 只有 `financial-data/sync` POST，没有财务历史 GET owner；不得把空数组兼容结果提升为 governed read
2. 第二优先项：对新的默认候选沿固定步骤补 manifest、fallback、registry/catalog metadata 与 focused contract 回归
   - manifest：`sdk/agomtradepro_mcp/registry/modules/basic_read_capabilities.py`
   - core-only fallback：`sdk/agomtradepro_mcp/server.py`
   - registry/core-only tests：`sdk/tests/test_mcp/test_core_registry.py`
   - catalog metadata/replacement tests：`tests/unit/test_ai_capability/test_api_and_use_cases.py`
3. 第三优先项：执行最小验证集，并在数量变化时更新 `governance/governance_baseline.json`
   - 根据当前目标能力运行对应 focused API success contract
   - 根据当前目标能力运行对应 focused SDK endpoint contract
   - `python -m pytest sdk/tests/test_mcp/test_core_registry.py -q`
   - `python -m pytest tests/unit/test_ai_capability/test_api_and_use_cases.py -q`
   - `python -m pytest sdk/tests/test_mcp/test_tool_registration.py -q`
   - `python scripts/check_mcp_manifest_schema.py`
   - `python scripts/check_mcp_read_evidence.py`
   - `python scripts/check_mcp_catalog_dedup.py`
4. 第四优先项：继续冻结 `sync_prices` / `sync_quotes` 与其他缺 raw tool 证据的候选

#### 0.2.4 当前明确不要再做的事

1. 不要再把 `list_data_center_providers`、`list_ai_providers`、`get_ai_provider`、`list_ai_usage_logs`、`list_filters`、`get_filter` 写成“下一步”；这些项已完成。
2. 不要把 `sync_prices`、`sync_quotes` 提前写入默认迁移入口；在补齐 raw MCP tool 证据前，它们保持冻结。
3. 不要把“普通站内功能调用”重新包装成 MCP 作为内部 API 平替。
4. 不要新增新的 raw `@server.tool()` 作为治理迁移捷径。
5. 不要把 Sentiment legacy raw tool 的任意 `payload` 继续发布为 governed input；新契约只允许 canonical `date`、`days` 或无参数调用。
6. 不要把 `publish_event` 或 `replay_events` 伪装成 read；两者存在事件发布或重放副作用，必须进入 write/workflow 治理。

#### 0.2.5 当前批次完成定义

`list_prompt_templates`、`list_prompt_chains`、`get_risk_floor`、`list_risk_templates`、`get_effective_risk_policy`、`get_account_risk_policy`、`list_risk_exceptions`、`check_pre_trade_risk`、`check_post_investment_risk`、`get_risk_center_daily_report` 与 `list_risk_center_daily_reports` 已在本轮满足上述完成定义，并正式收口为 `prompt.read.template_catalog`、`prompt.read.chain_catalog`、`risk_center.read.floor`、`risk_center.read.template_catalog`、`risk_center.read.effective_policy`、`risk_center.read.account_policy`、`risk_center.read.exception_list`、`risk_center.read.pre_trade_check`、`risk_center.read.post_investment_check`、`risk_center.read.daily_report` 与 `risk_center.read.daily_report_history`。后续批次继续沿用完全相同的完成口径：

1. focused success contract 已补齐并通过。
2. governed manifest、core-only fallback、registry tests、catalog metadata tests 已全部落地。
3. 最小验证集通过：
   - `python -m pytest sdk/tests/test_sdk/test_extended_module_endpoints.py -q`
   - `python -m pytest sdk/tests/test_mcp/test_core_registry.py -q`
   - `python -m pytest tests/unit/test_ai_capability/test_api_and_use_cases.py -q`
   - `python -m pytest sdk/tests/test_mcp/test_tool_registration.py -q`
   - prompt 对应 focused API 契约测试
   - `python scripts/check_mcp_manifest_schema.py`
   - `python scripts/check_mcp_read_evidence.py`
   - `python scripts/check_mcp_catalog_dedup.py`
4. 动态统计只更新 `governance/governance_baseline.json`；`0.2.2` 只维护字段说明和验证入口，不复制 live 数字。

17. SDK/MCP 测试已完成 core-only / legacy-on 分层：
   - 默认 surface 测试按 core-only 运行
   - raw tool 兼容测试通过显式 `legacy-on` 夹具运行
   - focused regression 已覆盖 core registry、tool registration、terminal agent、ai capability 和主要 raw-tool compatibility suites
18. 已新增默认顶层工具预算护栏：
   - `scripts/check_mcp_tool_budget.py`
   - `tests/unit/test_check_mcp_tool_budget.py`
   - 当前默认 MCP top-level surface 已通过固定 core tool 集校验；实时数量读取 `mcp_governance.default_top_level_tool_count`
19. 已新增 manifest schema 护栏：
   - `scripts/check_mcp_manifest_schema.py`
   - `tests/unit/test_check_mcp_manifest_schema.py`
   - 当前 registry 数值口径统一读取 `governance/governance_baseline.json`
20. 已新增 raw `@server.tool()` 文件面冻结护栏：
   - `scripts/check_mcp_no_raw_tools.py`
   - `tests/unit/test_check_mcp_no_raw_tools.py`
   - 当前冻结面数量读取 `governance/governance_baseline.json` 的 `mcp_governance.raw_tool_file_count`
21. 已新增 catalog dedup / replacement 护栏：
   - `scripts/check_mcp_catalog_dedup.py`
   - `tests/unit/test_check_mcp_catalog_dedup.py`
   - 当前 dedup / replacement 数值口径统一读取 `governance/governance_baseline.json`
22. 已新增 write-confirmation 护栏：
   - `scripts/check_mcp_write_confirmation.py`
   - `tests/unit/test_check_mcp_write_confirmation.py`
   - 当前 write-confirmation 数值口径统一读取 `governance/governance_baseline.json`
23. 已新增 write-preview 护栏：
   - `scripts/check_mcp_write_preview.py`
   - `tests/unit/test_check_mcp_write_preview.py`
   - 当前 write-preview 数值口径统一读取 `governance/governance_baseline.json`
24. 已新增 write-audit 护栏：
   - `scripts/check_mcp_write_audit.py`
   - `tests/unit/test_check_mcp_write_audit.py`
   - 当前 write-audit 数值口径统一读取 `governance/governance_baseline.json`
   - 补充：已新增 write-evidence 护栏
   - `scripts/check_mcp_write_evidence.py`
   - `tests/unit/test_check_mcp_write_evidence.py`
   - 当前 write-evidence 数值口径统一读取 `governance/governance_baseline.json`
25. 已落地 governed write capability 样板：
   - `decision.create.execution_request`
   - 底层桥接 legacy `decision_workflow_preview_execution`
   - 首次调用固定走 preview（`create_request=false`）
   - 二次确认后才创建审批请求（`create_request=true`）
   - 当前已强制要求 `idempotency_key`
   - dispatcher 已支持同键 pending/completed replay 抑制
26. 已落地 governed write capability：
   - `account.import.positions`
   - 底层桥接 legacy `import_positions_json`
   - 首次调用固定走 preview（`dry_run=true`）
   - 二次确认后才执行真实导入（`dry_run=false`）
   - 当前已强制要求 `idempotency_key`
   - dispatcher 已支持同键 pending/completed replay 抑制
27. 已落地 governed write capability：
   - `account.import.transactions`
   - 底层桥接 legacy `import_transactions_json`
   - 首次调用固定走 preview（`dry_run=true`）
   - 二次确认后才执行真实导入（`dry_run=false`）
   - 当前已强制要求 `idempotency_key`
   - dispatcher 已支持同键 pending/completed replay 抑制
28. 已落地 governed write capability：
   - `account.import.capital_flows`
   - 底层桥接 legacy `import_capital_flows_json`
   - 首次调用固定走 preview（`dry_run=true`）
   - 二次确认后才执行真实导入（`dry_run=false`）
   - 当前已强制要求 `idempotency_key`
   - dispatcher 已支持同键 pending/completed replay 抑制
29. 已落地 governed write capability：
   - `agent_proposal.create.proposal`
   - 通过受控 `internal_handler` 先产出 proposal preview，再确认创建 proposal record
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 proposal create（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `create_agent_proposal` 建立 replacement 关系
30. 已落地 governed write capability：
   - `decision.submit.request_batch`
   - 通过受控 `internal_handler` 先产出批量提交 preview，再确认写入 decision rhythm workflow
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 batch submit（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `submit_batch_decision_request` 建立 replacement 关系
31. 已落地 governed write capability：
   - `decision.submit.request`
   - 通过受控 `internal_handler` 先产出单请求提交 preview，再确认写入 decision rhythm workflow
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 single request submit（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `submit_decision_request` 建立 replacement 关系
32. 已落地 governed write capability：
   - `decision.execute.request`
   - 通过受控 `internal_handler` 先读取当前 decision request status 与 execution payload summary，再确认执行 approved request
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 decision request execute（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `decision_execute_request` 建立 replacement 关系
33. 已落地 governed write capability：
   - `agent_proposal.execute.proposal`
   - 通过受控 `internal_handler` 先读取 proposal execution context，再确认执行 approved proposal
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 proposal execute（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `execute_agent_proposal` 建立 replacement 关系
34. 已落地 governed write capability：
   - `agent_proposal.approve.proposal`
   - 通过受控 `internal_handler` 先读取 proposal approval context，再确认把 submitted proposal 迁移到 approved
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 proposal approve（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `approve_agent_proposal` 建立 replacement 关系
35. 已落地 governed write capability：
   - `agent_proposal.reject.proposal`
   - 通过受控 `internal_handler` 先读取 proposal rejection context，再确认把 submitted proposal 迁移到 rejected
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 proposal reject（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `reject_agent_proposal` 建立 replacement 关系
36. 已落地 governed write capability：
   - `signal.create.signal`
   - 通过受控 `internal_handler` 先运行 signal eligibility preview，再确认创建 pending investment signal
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 signal create（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `create_signal` 建立 replacement 关系
37. 已落地 governed write capability：
   - `signal.approve.signal`
   - 通过受控 `internal_handler` 先读取当前 signal status，再确认把 pending signal 迁移到 approved
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 signal approve（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `approve_signal` 建立 replacement 关系
38. 已落地 governed write capability：
   - `signal.reject.signal`
   - 通过受控 `internal_handler` 先读取当前 signal status，再确认把 pending signal 迁移到 rejected
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 signal reject（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `reject_signal` 建立 replacement 关系
39. 已落地 governed write capability：
   - `signal.invalidate.signal`
   - 通过受控 `internal_handler` 先读取当前 signal status，再确认把 signal 迁移到 invalidated
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 signal invalidate（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `invalidate_signal` 建立 replacement 关系
40. 已落地 governed write capability：
   - `trading.submit.simulated_order`
   - 通过受控 `internal_handler` 先读取 simulated account / position context，再确认执行 simulated trading order
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 simulated order submit（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `execute_simulated_trade` 建立 replacement 关系
41. 已落地 governed write capability：
   - `decision.cancel.request`
   - 通过受控 `internal_handler` 先读取当前 decision request status，再确认取消 request 并终止后续执行链
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 decision request cancel（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `decision_cancel_request` 建立 replacement 关系
42. 已落地 governed write capability：
   - `trading.close.simulated_position`
   - 通过受控 `internal_handler` 先读取 simulated account / matched position context，再确认执行平仓
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 simulated position close（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `close_simulated_position` 建立 replacement 关系
43. 已落地 governed write capability：
   - `trading.reset.simulated_account`
   - 通过受控 `internal_handler` 先读取 simulated account summary，再确认重置账户资金与状态
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 simulated account reset（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `reset_simulated_account` 建立 replacement 关系
44. 已落地 governed write capability：
   - `trading.start.simulated_auto_trading`
   - 通过受控 `internal_handler` 先读取 trade date 与 account scope summary，再确认触发 simulated auto-trading
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 simulated auto-trading run（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `run_simulated_auto_trading` 建立 replacement 关系
45. 已落地 governed write capability：
   - `trading.run.simulated_daily_inspection`
   - 通过受控 `internal_handler` 先读取 account / inspection scope summary，再确认执行 simulated daily inspection
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 simulated daily inspection run（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `run_simulated_daily_inspection` 建立 replacement 关系
46. 已落地 governed write capability：
   - `strategy.execute.run`
   - 通过受控 `internal_handler` 先读取 strategy context 与执行日期，再确认执行 strategy run
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 strategy execute（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `execute_strategy` 建立 replacement 关系
47. 已落地 governed write capability：
   - `strategy.bind.portfolio`
   - 通过受控 `internal_handler` 先读取 portfolio / strategy context，再确认激活 strategy binding
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 strategy bind（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `bind_portfolio_strategy` 建立 replacement 关系
48. 已落地 governed write capability：
   - `strategy.unbind.portfolio`
   - 通过受控 `internal_handler` 先读取 portfolio context，再确认停用 active strategy binding
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 strategy unbind（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `unbind_portfolio_strategy` 建立 replacement 关系
49. 已落地 governed write capability：
   - `rotation.create.account_config`
   - 通过受控 `internal_handler` 先读取 account context，再确认创建 rotation account config
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 rotation config create（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `create_account_rotation_config` 建立 replacement 关系
50. 已落地 governed write capability：
   - `rotation.delete.account_config`
   - 通过受控 `internal_handler` 先读取 account rotation config context，再确认删除该配置
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 rotation config delete（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `delete_account_rotation_config` 建立 replacement 关系
51. 已落地 governed write capability：
   - `rotation.update.account_config`
   - 通过受控 `internal_handler` 先读取现有 account rotation config context，再确认更新配置字段
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 rotation config update（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `update_account_rotation_config` 建立 replacement 关系
52. 已落地 governed write capability：
   - `rotation.apply_template.account_config`
   - 通过受控 `internal_handler` 先读取现有 account rotation config 与 template context，再确认应用模板
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 rotation template apply（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `apply_rotation_template_to_account_config` 建立 replacement 关系
53. 已落地 governed write capability：
   - `strategy.create.position_rule`
   - 通过受控 `internal_handler` 先读取 strategy context，再确认创建 position rule
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 strategy position rule create（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `create_position_rule` 建立 replacement 关系
54. 已落地 governed write capability：
   - `strategy.update.position_rule`
   - 通过受控 `internal_handler` 先读取现有 position rule context，再确认更新 rule 字段
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 strategy position rule update（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `update_position_rule` 建立 replacement 关系
55. 已落地 governed write capability：
   - `strategy.create.ai_config`
   - 通过受控 `internal_handler` 先读取 strategy context，再确认创建 AI strategy config
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 AI strategy config create（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `create_ai_strategy_config` 建立 replacement 关系
56. 已落地 governed write capability：
   - `strategy.update.ai_config`
   - 通过受控 `internal_handler` 先读取现有 AI strategy config context，再确认更新 AI config 字段
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 AI strategy config update（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `update_ai_strategy_config` 建立 replacement 关系
57. 已落地 governed write capability：
   - `strategy.create.strategy`
   - 通过受控 `internal_handler` 先汇总 strategy definition payload，再确认创建 strategy
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 strategy create（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `create_strategy` 建立 replacement 关系
58. 已落地 governed write capability：
   - `account.create.trading_cost_config`
   - 通过受控 `internal_handler` 先读取 portfolio context，再确认创建 trading cost config
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 trading cost config create（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `create_trading_cost_config` 建立 replacement 关系
59. 已落地 governed write capability：
   - `account.update.trading_cost_config`
   - 通过受控 `internal_handler` 先读取现有 trading cost config context，再确认更新费率字段
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 trading cost config update（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `update_trading_cost_config` 建立 replacement 关系
60. 已落地 governed write capability：
   - `config_center.update.runtime_setting`
   - 通过受控 `internal_handler` 先读取当前 Qlib runtime config，再确认更新 runtime setting
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 runtime config update（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `update_qlib_runtime_config` 建立 replacement 关系
61. 已落地 governed write capability：
   - `config_center.update.data_center_provider`
   - 通过受控 `internal_handler` 先读取当前 provider config，再确认更新 provider 配置
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 provider config update（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `update_data_center_provider` 建立 replacement 关系
62. 已落地 governed write capability：
   - `data_center.update.publisher`
   - 通过受控 `internal_handler` 先读取当前 publisher catalog entry，再确认更新 publisher 元数据
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 publisher update（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `data_center_update_publisher` 建立 replacement 关系
63. 已落地 governed write capability：
   - `data_center.update.indicator`
   - 通过受控 `internal_handler` 先读取当前 indicator catalog entry，再确认更新指标目录元数据
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 indicator update（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `data_center_update_indicator` 建立 replacement 关系
64. 已落地 governed write capability：
   - `ai_provider.update.provider`
   - 通过受控 `internal_handler` 先读取当前 AI provider config，再确认更新提供商配置
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 provider config update（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `update_ai_provider` 建立 replacement 关系
65. 已落地 governed write capability：
   - `alpha_trigger.update.candidate_status`
   - 通过受控 `internal_handler` 先读取当前 alpha candidate，再确认更新候选状态
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 candidate status update（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `update_alpha_candidate_status` 建立 replacement 关系
66. 已落地 governed write capability：
   - `filter.update.filter`
   - 通过受控 `internal_handler` 先读取当前 filter config，并统一解析 `filter_id -> indicator_code` 后再确认更新配置
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 filter config update（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `update_filter` 建立 replacement 关系
67. 已落地 governed write capability：
   - `filter.delete.filter`
   - 通过受控 `internal_handler` 先读取当前 filter config，并统一解析 `filter_id -> indicator_code` 后再确认删除配置
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 filter config delete（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `delete_filter` 建立 replacement 关系
68. 已落地 governed write capability：
   - `ai_provider.create.provider`
   - 通过受控 `internal_handler` 先规范化待创建 provider payload，并预览创建摘要后再确认落库
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 provider create（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `create_ai_provider` 建立 replacement 关系
69. 已落地 governed write capability：
   - `config_center.create.data_center_provider`
   - 通过受控 `internal_handler` 先汇总待创建 data-center provider 配置，并预览创建摘要后再确认落库
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 provider create（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `create_data_center_provider` 建立 replacement 关系
70. 已落地 governed write capability：
   - `ai_provider.toggle.provider`
   - 通过受控 `internal_handler` 先读取当前 provider active 状态，并预览目标切换状态后再确认提交
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 provider toggle（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `toggle_ai_provider` 建立 replacement 关系
71. 已落地 governed write capability：
   - `trading.delete.simulated_account`
   - 通过受控 `internal_handler` 先读取当前 simulated account summary，并预览删除目标后再确认提交
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 simulated account delete（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `delete_simulated_account` 建立 replacement 关系
72. 已落地 governed write capability：
   - `trading.delete.simulated_account_batch`
   - 通过受控 `internal_handler` 先读取待删除账户批次，并显式暴露 partial-failure 风险后再确认提交
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 simulated account batch delete（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `batch_delete_simulated_accounts` 建立 replacement 关系
73. 已落地 governed write capability：
   - `trading.create.simulated_account`
   - 通过受控 `internal_handler` 先预览账户配置、默认风控参数与同名活跃账户命中数后再确认提交
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 simulated account create（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `create_simulated_account` 建立 replacement 关系
74. 已落地 governed write capability：
   - `policy.approve.workbench_event`
   - 通过受控 `internal_handler` 先读取当前 policy workbench event 摘要与 `audit_status`，再确认提交审批
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 workbench event approve（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `approve_workbench_event` 建立 replacement 关系
75. 已落地 governed write capability：
   - `policy.reject.workbench_event`
   - 通过受控 `internal_handler` 先读取当前 policy workbench event 摘要、`audit_status` 与驳回理由，再确认提交驳回
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 workbench event reject（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `reject_workbench_event` 建立 replacement 关系
76. 已落地 governed write capability：
   - `policy.rollback.workbench_event`
   - 通过受控 `internal_handler` 先读取当前 policy workbench event 摘要、`audit_status`、`gate_effective` 与回滚理由，再确认提交回滚
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 workbench event rollback（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `rollback_workbench_event` 建立 replacement 关系
77. 已落地 governed write capability：
   - `policy.override.workbench_event`
   - 通过受控 `internal_handler` 先读取当前 policy workbench event 摘要、当前档位、请求档位与豁免理由，再确认提交 override
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 workbench event override（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `override_workbench_event` 建立 replacement 关系
78. 已落地 governed write capability：
   - `data_center.create.publisher`
   - 通过受控 `internal_handler` 先汇总待创建 publisher catalog payload，并预览创建摘要后再确认落库
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 publisher create（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `data_center_create_publisher` 建立 replacement 关系
79. 已落地 governed write capability：
   - `data_center.delete.publisher`
   - 通过受控 `internal_handler` 先读取当前 publisher catalog entry，并预览待删除对象摘要后再确认删除
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 publisher delete（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `data_center_delete_publisher` 建立 replacement 关系
80. 已落地 governed write capability：
   - `filter.create.filter`
   - 通过受控 `internal_handler` 先真实执行一次 `save_results=false` 的滤波预演，并预览结果摘要后再确认持久化结果
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 filter run create（`preview_only=false`，commit 时 `save_results=true`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `create_filter` 建立 replacement 关系
81. 已落地 governed write capability：
   - `data_center.create.indicator`
   - 通过受控 `internal_handler` 先汇总待创建 indicator catalog payload，并预览创建摘要后再确认落库
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 indicator create（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `data_center_create_indicator` 建立 replacement 关系
82. 已落地 governed write capability：
   - `data_center.delete.indicator`
   - 通过受控 `internal_handler` 先读取当前 indicator catalog 条目，并预览删除目标摘要后再确认删除
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 indicator delete（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `data_center_delete_indicator` 建立 replacement 关系
83. 已落地 governed write capability：
   - `data_center.create.indicator_unit_rule`
   - 通过受控 `internal_handler` 先读取 indicator 上下文与现有 unit-rule 概况，并预览待创建规则摘要后再确认落库
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 indicator unit-rule create（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `data_center_create_indicator_unit_rule` 建立 replacement 关系
84. 已落地 governed write capability：
   - `data_center.delete.indicator_unit_rule`
   - 通过受控 `internal_handler` 先读取 indicator 上下文与当前 unit-rule 定义，并预览删除目标摘要后再确认删除
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 indicator unit-rule delete（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `data_center_delete_indicator_unit_rule` 建立 replacement 关系
85. 已落地 governed write capability：
   - `data_center.update.indicator_unit_rule`
   - 通过受控 `internal_handler` 先读取 indicator 上下文与当前 unit-rule 定义，并预览变更字段摘要后再确认更新
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 indicator unit-rule update（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 与 legacy `data_center_update_indicator_unit_rule` 建立 replacement 关系
86. 已落地 governed write capability：
   - `data_center.start.sync_job`
   - 当前已完成以下 governed 子路径：`job_kind=sync_macro`、`job_kind=sync_capital_flows`、`job_kind=sync_news`
   - 通过受控 `internal_handler` 先读取 provider + indicator / asset 上下文，并预览同步窗口或写入目标摘要后再确认执行
   - 首次调用固定走 preview（`preview_only=true`）
   - 二次确认后才执行真实 sync write（`preview_only=false`）
   - 当前已强制要求 `idempotency_key`
   - 当前已与 legacy `data_center_sync_macro`、`data_center_sync_capital_flows`、`data_center_sync_news` 建立 replacement 关系
87. 已落地 governed write audit chain：
   - dispatcher 现已对关键写生命周期输出统一审计事件
   - 已覆盖：`preview_staged`
   - 已覆盖：`confirmation_cancelled`
   - 已覆盖：`confirmation_completed`
   - 已覆盖：`idempotent_replay`
   - 已覆盖：`idempotency_conflict`
   - 审计载荷当前已包含参数摘要、确认状态、幂等键、影响对象摘要与 `request_id` 关联

因此，后续执行起点定义为：

- `Phase 0` 已部分完成，重点剩余项是“冻结新增 raw MCP tool”与“把 inventory 结果接入治理护栏”
- `Phase 1` 已达到“骨架落地 + 默认 surface 收口完成”的状态
- `Phase 2` 已进入“catalog 与 terminal 开始切换到 governed capability/core tools，默认 legacy-off 已落地”的状态
- `Phase 4` 已从“未开始”进入“preview-first confirmation + idempotency 样板已落地，其余写路径待批量迁移”的状态；实时数量读取 `mcp_governance.governed_write_like_capability_count`
- `Phase 5` 已从“未开始”进入“默认收口已完成、allowlist/精细兼容治理待继续”的状态
- 后续不应重复回头手工盘点同一批工具，除非 inventory 基线发生变化

### 0.1 当前基线结论

当前整改不是从零开始，而是从“默认 MCP 顶层 surface 已收口，但 capability 迁移与治理护栏尚未闭环”的状态继续推进：

1. `terminal agent` 当前已经是 MCP-backed，整改目标是收口其 MCP 工具面，而不是移除 MCP。
2. `apps/ai_capability` 已能同步 governed MCP capability，并通过 `agom_capability_call` 调统一 dispatcher。
3. governed write capability 的 `audit_tags` 当前也已同步进 catalog projection，并由 dedup guard 持续校验。
4. `web/chat` 已开始排除 `mcp_tool` wrapper 的默认竞争，但 `semantic_key` 的治理面仍未闭环。
5. `server.py` 默认行为已经切到 `core-only`，legacy raw tools 改为显式兼容模式。
6. 因此，下一批整改的最高优先级不再是切默认开关，而是继续做 capability 批量迁移和 CI 护栏。

### 0.2 下一批执行顺序

后续建议严格按以下顺序继续执行，避免又回到“默认 surface 扩张”或“带病迁移”的状态：

1. `realtime.delete.price_alert` 已完成真实契约核验，并确认当前 server build 不支持该能力：
   - 仓内没有 `/api/realtime/alerts/` interface 路由
   - `apps.realtime.infrastructure.models` 也没有 `PriceAlert` 实现
   - SDK/raw MCP 已改为显式 fail fast，不再继续探测不存在的 path
   - inventory 已可通过 `sdk/agomtradepro/unsupported_legacy_contracts.py` 与 `scripts/generate_mcp_tool_inventory.py` 自动关联并单独分流该 contract 对应的 raw tools；本文不记录实时数量
   - 因此该项暂不进入 governed replacement，直到产品侧先落地 canonical realtime alert API
2. 再从具备明确证据链的候选池里继续迁移下一个 governed write capability：
   - 必须同时具备 raw tool、SDK、canonical API 或 internal handler 的清晰映射
   - 不再按旧清单机械顺延
3. 并行继续治理护栏与目录治理：
   - 保持禁增 raw `@server.tool()`、manifest/schema、tool budget、write confirmation/preview/audit 护栏
   - 继续扩展 `semantic_key` 的人工校正、批量审计与冲突告警

### 0.3 当前阻塞点

当前主要阻塞已经从“默认行为切换”转移到“治理闭环与迁移深度”：

1. `semantic_key` 目前已可用于路由去重，但缺少人工治理台、审计视图和批量修正面。
2. CI 护栏脚本已落地，并已接入 GitHub Actions workflow；PR checklist 也已补齐。当前剩余缺口主要是首个远端稳定绿灯证据和更细粒度写路径门禁。
3. governed capability 的实时统计统一读取 `governance/governance_baseline.json`；第一批高频只读能力已从 `policy` / `task_monitor` 扩展到 `data_center.read.provider_catalog`、`ai_provider.read.provider_catalog`、`ai_provider.read.provider_detail`、`ai_provider.read.usage_logs`、`filter.read.indicator_catalog`、`filter.read.config_detail`、`prompt.read.template_catalog`、`prompt.read.chain_catalog`、`pulse.read.current`、`pulse.read.history`、`risk_center.read.floor`、`risk_center.read.template_catalog`、`risk_center.read.effective_policy`、`risk_center.read.account_policy`、`risk_center.read.exception_list`、`risk_center.read.pre_trade_check`、`risk_center.read.post_investment_check`、`risk_center.read.daily_report` 与 `risk_center.read.daily_report_history`，但跨域 read rollout 仍未完成。
4. 写能力已启动 preview / confirmation / idempotency 收口，governed write audit chain 也已落地；同时，`policy` workbench read family、`data_center.read.provider_catalog`、`ai_provider.read.provider_catalog`、`ai_provider.read.provider_detail`、`ai_provider.read.usage_logs`、`filter.read.indicator_catalog` 与 `filter.read.config_detail` 已作为 governed read 收口进 registry，当前剩余重点转为继续完成跨域 rollout，并重新审计下一批证据完整候选。
5. `realtime.delete.price_alert` 已完成契约核验，并确认属于当前 build 不支持的遗留错误契约：
   - `sdk/agomtradepro/modules/realtime.py` 与 raw tool 曾按 `DELETE /api/realtime/alerts/{id}/` 假定存在删除契约
   - 但当前仓内 `apps/realtime/interface/` 没有 `alerts` API，`apps.realtime.infrastructure.models` 也没有 `PriceAlert` 模型
   - 因此该项现已从“待治理迁移”改为“显式 unsupported legacy contract”，在真正的 canonical realtime alert API 落地前，不得进入 governed replacement
6. `filter.update.filter` 与 `filter.delete.filter` 已完成契约校正与 governed 迁移：
   - canonical API 已统一到 `GET/PATCH/DELETE /api/filter/config/{indicator_code}/`
   - SDK 已支持兼容传入 legacy `filter_id`，并在内部解析到 canonical `indicator_code`
   - 对应 preview / confirmation / replacement / catalog / 契约测试已补齐
7. 基于 `2026-07-10` 的代码事实，`config_center.create.data_center_provider`、`data_center.create.publisher`、`data_center.delete.publisher`、`data_center.create.indicator`、`data_center.delete.indicator`、`data_center.create.indicator_unit_rule`、`data_center.delete.indicator_unit_rule`、`filter.create.filter`、`ai_provider.create.provider`、`ai_provider.update.provider`、`ai_provider.toggle.provider`、`alpha_trigger.update.candidate_status`、`filter.update.filter`、`filter.delete.filter`、`trading.delete.simulated_account`、`trading.delete.simulated_account_batch`、`trading.create.simulated_account`、`policy.approve.workbench_event`、`policy.reject.workbench_event`、`policy.rollback.workbench_event`、`policy.override.workbench_event`、`policy.read.workbench.summary`、`policy.read.workbench.items`、`policy.read.sentiment_gate.state`、`data_center.read.provider_catalog`、`ai_provider.read.provider_catalog`、`ai_provider.read.provider_detail`、`ai_provider.read.usage_logs`、`filter.read.indicator_catalog`、`filter.read.config_detail`、`prompt.read.template_catalog`、`prompt.read.chain_catalog`、`pulse.read.current`、`pulse.read.history`、`risk_center.read.floor`、`risk_center.read.template_catalog`、`risk_center.read.effective_policy`、`risk_center.read.account_policy`、`risk_center.read.exception_list`、`risk_center.read.pre_trade_check`、`risk_center.read.post_investment_check`、`risk_center.read.daily_report` 与 `risk_center.read.daily_report_history` 已完成迁移并通过 focused regression 与 guards；`realtime.delete.price_alert` 已完成核验并被收口为 unsupported legacy contract，且已进入显式清单与 inventory 分流；`scripts/check_mcp_write_evidence.py` 也已落地到 CI。当前下一批优先项应改为“继续沿 raw-tool gap 审计结果筛出下一条证据链完整候选”，不再把已完成项继续留在默认入口。
   - 本轮同时修正了 `pulse history` 的 canonical 契约漂移：`/api/pulse/history/` 现已受控支持 `limit` 查询参数，并保持 `months` 兼容；避免 SDK/raw MCP 使用 `limit` 时继续偏离真实接口语义。
   - 本轮同时补齐 `data_center.read.provider_status` 的 read-like 完成证据：governed capability 默认输出使用 `providers + total_count` 对象包裹，底层 SDK/canonical API 仍保持原有 list 契约，避免破坏站内 API 兼容。
8. 本轮额外修复了 canonical `POST /api/simulated-trading/accounts/` 的 owner 绑定缺口：新建账户现会正确绑定 `request.user`，避免 governed create 样板建立在错误 owner 语义上。
9. 本轮同时完成 `policy.override` 契约校正：
   - canonical API / serializer / use case 真实语义为 `reason + new_level(optional)`
   - SDK 与 raw MCP tool 过去暴露的 `expires_in_hours` 已确认为历史漂移字段，不属于当前 canonical 契约
   - 当前 SDK/raw path 已统一到 `new_level`，并对 `expires_in_hours` 执行显式 fail-fast，避免继续把假字段制度化

---

## 1. 背景判断

当前 MCP 的主要问题不是“工具数量多”本身，而是职责边界混乱：

1. MCP 被用于包装 canonical API，形成第二套外部契约。
2. `sdk/agomtradepro_mcp/server.py` 直接注册大量模块工具，顶层工具列表过长。
3. AI Capability Catalog 同时管理 `api` 和 `mcp_tool`，同一业务语义可能以两种形态进入候选池。
4. MCP 风险治理部分依赖工具名推断，缺少显式能力 manifest。
5. 站内 `terminal agent` 当前明确通过 MCP 运行，而普通 Web/TUI/页面调用面与外部 MCP 的边界不够清晰。

### 1.1 当前代码事实校正

本整改计划以后续代码为准，必须先承认以下当前事实：

1. `apps/terminal/interface/api_views.py` 已将 legacy terminal command API 标记为 retired，并要求使用 “terminal agent chat endpoints backed by MCP/Agents”。
2. `apps/agent_runtime/infrastructure/terminal_agent_service.py` 当前通过 `MCPServerStdio` 启动 `python -m agomtradepro_mcp.server`。
3. `terminal agent` 的系统提示词明确要求 “Use MCP tools when they are available and necessary”。
4. 因此，`terminal agent` 不是“未来可能接 MCP”，而是**当前已经是 MCP-backed 运行面**。
5. 本计划的 terminal 目标不是“把 terminal 从 MCP 拔掉”，而是**把 terminal 所消费的 MCP 工具面从 legacy 散装 raw tools 收口为统一 core tools + capability registry**。

### 1.2 当前整改起点

截至本计划执行起点，仓库已完成以下基础动作：

1. 已新增 MCP 技术标准文档。
2. 已生成静态 MCP inventory 产物：
   - `reports/mcp/mcp-tool-inventory-2026-07-09.json`
   - `reports/mcp/mcp-tool-classification-2026-07-09.md`
3. 当前静态 inventory 口径确认：模块与 raw tool 盘点证据已由 `reports/mcp/mcp-tool-inventory-2026-07-09.json` 和 `reports/mcp/mcp-tool-classification-2026-07-09.md` 固化；相关 live 数量统一读取 `governance/governance_baseline.json`。

目标不是削弱 MCP，而是让 MCP 以更清晰的方式操作系统所有能力：

```text
External Agent
  -> small stable MCP tools
  -> capability registry
  -> dispatcher
  -> application facade / canonical API adapter / workflow executor
  -> audit
```

---

## 2. 整改总原则

1. 普通站内 AI 不默认走 MCP。
2. MCP 不做 API endpoint 的一比一替代。
3. MCP 顶层工具少而稳定。
4. 系统功能通过 capability registry 暴露。
5. 真实执行统一经过 dispatcher。
6. 写操作统一 dry-run、确认、幂等、审计。
7. legacy tools 只减不增。
8. `terminal agent` 保留 MCP-backed 运行形态，但只消费统一 core tools。
9. 整改期间不得破坏当前 `terminal agent -> MCPServerStdio -> agomtradepro_mcp.server` 的可用链路，除非 replacement 与回归验证已完成。

---

## 3. 目标架构

### 3.1 目标组件

| 组件 | 目标职责 |
| --- | --- |
| `core_tools.py` | 只注册 `agom_bootstrap/search/schema/call/confirm/workflow` |
| `registry/manifest.py` | 定义 `CapabilityManifest` 和 executor 引用 |
| `registry/loader.py` | 加载各模块 manifest，校验唯一性和 schema |
| `registry/dispatcher.py` | 统一执行身份、权限、风险、确认、调用和审计 |
| `registry/modules/*.py` | 各业务域贡献任务级 capability |
| `legacy/` | 兼容旧工具，默认关闭或降级展示 |
| `apps/ai_capability` | 同步 manifest 元数据，按 entrypoint 分流 |
| `apps/agent_runtime` | `terminal agent` 侧只感知 core tools，不再直接面向 raw tool flood |

### 3.2 目标 MCP tool 列表

整改完成后默认只暴露：

```text
agom_bootstrap
agom_capability_search
agom_capability_schema
agom_capability_call
agom_confirmation_resume
agom_workflow_start
agom_workflow_status
```

可选兼容：

```text
legacy_* tools
```

兼容工具必须通过配置显式打开。

### 3.3 Terminal 主链与统一调度接口

本次整改必须把 terminal 当前真实运行链路写死为标准主链，后续任何整改都不得再回到“模型直接猜大规模 raw tool 目录”的模式：

```text
terminal ui / terminal agent
  -> agent_runtime terminal_agent_service
  -> MCPServerStdio
  -> agomtradepro_mcp.server
  -> fixed core tool surface
     (live count: governance/governance_baseline.json#mcp_governance.default_top_level_tool_count)
  -> capability registry
  -> capability dispatcher
  -> application facade / canonical api adapter / workflow executor
  -> audit
```

统一调度接口口径如下：

1. `terminal agent` 不直接绑定 raw tool 名称，而是先经 `agom_capability_search` 发现能力。
2. 需要参数解释时，一律经 `agom_capability_schema` 读取 schema、风险和示例。
3. 真正执行时，一律经 `agom_capability_call(capability_key, arguments, context)` 进入 dispatcher。
4. 遇到写操作确认时，一律经 `agom_confirmation_resume` 完成二次确认。
5. 多步任务一律通过 `agom_workflow_start` / `agom_workflow_status` 跟踪，不允许模型自行拼接多段 raw tool 流程。

### 3.4 统一注册与统一调用的强约束

后续整改和新增能力必须满足以下硬约束，否则视为架构回退：

1. 新增系统能力时，只允许新增 manifest，不允许新增面向模型的散装 `@server.tool()`。
2. `terminal agent` 的 tool exposure 只允许出现标准定义的固定 core tool 集；具体业务能力必须通过 registry 间接发现。
3. raw tool 即使仍保留兼容执行价值，也只能作为 governed capability 的底层 bridge，不再作为默认模型入口。
4. 普通站内 AI、Web Chat、TUI、页面控件不得为了复用而倒流到 MCP；只有 `terminal agent` 和外部 Agent 走统一 MCP 调度面。
5. 所有新增写能力必须同时设计 preview、confirmation、idempotency、audit 四件套，不接受“先接进去以后再补治理”。

---

## 4. 分阶段计划

### 4.0 阶段状态总览

| Phase | 状态 | 当前结论 | 下一退出条件 |
| --- | --- | --- | --- |
| `Phase 0` | 部分完成 | inventory 与分类基线已产出 | 新增 raw tool 被 CI 或 checklist 阻断 |
| `Phase 1` | 已完成 | registry / dispatcher / core tools 已落地，默认 server surface 已切到 core-only | 第一批只读 capability 迁移启动 |
| `Phase 2` | 进行中 | governed capability、terminal 分流、语义去重已部分接通，默认 legacy-off 与测试闭环已完成 | semantic_key 治理面与更多 governed capability 完成 |
| `Phase 3` | 部分完成 | governed read capability 迁移已启动；实时数量读取 `mcp_governance.governed_read_capability_count` | 第一批高频只读能力迁移完成 |
| `Phase 4` | 部分完成 | preview-first confirmation + idempotency 写能力样板已落地，governed write lifecycle audit 已接入 dispatcher，write-evidence guard 已落地；实时数量读取 `mcp_governance.governed_write_like_capability_count` | 写能力批量迁移扩到更多 domains，并完成跨域 rollout |
| `Phase 5` | 部分完成 | legacy tools 已默认隐藏并支持显式兼容，replacement 映射已同步入 catalog | allowlist、replacement、remove 类工具治理完成 |
| `Phase 6` | 部分完成 | top-level budget、manifest schema、raw tool 文件面冻结、catalog dedup / replacement、write-confirmation / write-preview / write-audit 护栏已落地，并已接入 GitHub Actions consistency workflow；PR checklist 已补齐 | 剩余门禁主要收敛到更细粒度的写路径与治理台 |
| `Phase 7` | 进行中 | 标准文档、guide 已启动更新 | 文档、示例、回归与最终报告闭环 |

### Phase 0：冻结与盘点

周期：1-2 天
目标：停止继续扩散，建立现状清单。

任务：

1. 冻结新增散装 `@server.tool()`。
2. 扫描 `sdk/agomtradepro_mcp/tools/*`，生成当前 tool inventory。
3. 为每个 tool 标记 owner app、读写类型、是否 API wrapper、是否页面 wrapper、是否任务级。
4. 输出分类：`keep_task`、`aggregate`、`internal_only`、`legacy_compat`、`remove`。
5. 统计当前顶层 tool 数、写工具数、admin 工具数、无 schema 工具数。

验收：

1. 有机器生成的 inventory 文件。
2. 有人工复核后的分类表。
3. 新增 raw tool 的 PR 被拒绝或至少在 review checklist 中阻断。

当前状态（2026-07-10）：

1. inventory 与分类结果已完成。
2. 默认 MCP 顶层 surface 已完成收口。
3. 本阶段剩余唯一关键项是把“冻结新增 raw tool”变成 CI 或检查脚本硬门禁。

建议产物：

```text
reports/mcp/mcp-tool-inventory-2026-07-09.json
reports/mcp/mcp-tool-classification-2026-07-09.md
```

### Phase 1：统一 Manifest 与核心工具

周期：3-5 天
目标：建立新能力注册和统一调用骨架，不迁移全部业务。

任务：

1. 新增 `CapabilityManifest` 数据结构。
2. 新增 registry loader。
3. 新增 schema validator。
4. 新增 dispatcher skeleton。
5. 新增核心 MCP tools：
   - `agom_bootstrap`
   - `agom_capability_search`
   - `agom_capability_schema`
   - `agom_capability_call`
   - `agom_confirmation_resume`
6. 先迁移一批只读能力作为样板：
   - `system.read.policy.status`
   - `system.read.regime.current`
   - `system.read.task_monitor.statistics`

验收：

1. 默认核心工具可通过 MCP Inspector 调用。
2. `agom_capability_search` 能返回样板能力。
3. `agom_capability_call` 能调用样板能力。
4. 输出统一 envelope。
5. legacy tools 仍可通过兼容路径运行，不影响现有使用。
6. `terminal agent` 在本阶段仍能正常连通 MCP server，并允许与 core-tools cutover 并行推进，而不要求一次性切换完成。

当前状态（2026-07-10）：

1. `manifest.py`、`loader.py`、`dispatcher.py`、`core_tools.py` 已落地。
2. 当前已注册标准定义的统一 core tool 集；实时数量读取 `mcp_governance.default_top_level_tool_count`。
3. 样板 capability 已落地，当前实际样板键为：
   - `system.read.regime.current`
   - `regime.read.history`
   - `system.read.policy.status`
   - `policy.read.events`
   - `system.read.task_monitor.statistics`
   - `task_monitor.read.task_status`
   - `task_monitor.read.task_list`
   - `data_center.read.provider_status`
   - `data_center.read.macro_series`
   - `data_center.read.indicator_catalog`
   - `pulse.read.current`
   - `pulse.read.history`
   - `task_monitor.read.dashboard`
   - `task_monitor.read.celery_health`
4. 本阶段已完成默认 `core-only` 收口，后续只剩 capability 批量迁移。

### Phase 2：AI Capability Catalog 分流

周期：2-4 天
目标：普通站内 AI、`terminal agent` 与外部 MCP 分清入口。

任务：

1. 给 Catalog 增加或明确 `entrypoint_scope` 过滤策略。
2. `web_chat`、`tui`、普通 `terminal_workbench` 默认不把 `mcp_tool` 放入候选。
3. `terminal_agent` 继续允许 MCP-backed 能力，但只允许通过 core tools 暴露的治理后能力。
4. `mcp` entrypoint 只读取 MCP manifest 同步出的能力。
5. 对同一业务语义的 `api` 和 `mcp_tool` 做去重。
6. 同步命令 `sync_ai_capability_catalog` 改为以 manifest 为 MCP 元数据来源。
7. `apps/agent_runtime/infrastructure/terminal_agent_service.py` 的 tool filter 从 “auto-approved raw tools” 过渡到 “auto-approved core tools / capability tools”。
8. 固化 terminal 侧统一调度约束：
   - 搜索只走 `agom_capability_search`
   - 解释只走 `agom_capability_schema`
   - 执行只走 `agom_capability_call`
   - 确认只走 `agom_confirmation_resume`

验收：

1. 普通站内 chat 请求不会优先选到 MCP wrapper。
2. `terminal_agent` 仍能通过 MCP 能力执行系统操作。
3. MCP 能力仍可在 MCP entrypoint 搜索和调用。
4. Catalog 统计能区分 API 能力、Application 能力、MCP 外部能力。
5. `terminal agent` 面向模型暴露的可调用工具数量显著下降，不再直接暴露 legacy 散装 raw tools。

当前状态（2026-07-10）：

1. terminal 侧已经具备 governed capability 存在时只暴露 core tools 的逻辑。
2. `sync_mcp_tools` 已能同步 governed MCP capability，并把 raw tool 条目标记为默认禁用。
3. `web/chat` 已开始排除 `mcp_tool` wrapper 的默认竞争。
4. 本阶段已完成默认 `legacy-off` 与测试分层，剩余关键项如下：
   - 继续扩充 governed capability 覆盖面
   - 形成 `semantic_key` 人工治理面
   - 继续把 registry 治理元数据完整投影到 catalog / governance 面
   - 回归 terminal / catalog / MCP server 三条链路的新增迁移能力

### Phase 3：只读能力批量迁移

周期：5-8 天
目标：把高频只读查询从散装 tools 迁到 manifest。

优先域：

1. `regime`
2. `pulse`
3. `policy`
4. `data_center`
5. `portfolio/account read`
6. `dashboard read summaries`
7. `task_monitor`

迁移规则：

1. 一个业务问题对应一个 capability。
2. 多个旧工具如只是参数变体，合并为一个 capability。
3. 页面专用读取能力不迁移，改为 internal-only。
4. dashboard fragment 不迁移，改为更高层 summary capability。

验收：

1. 高频只读能力可通过 `agom_capability_call` 完成。
2. 旧只读 tools 标记 replacement。
3. 默认推荐文档不再引导使用旧工具。

### Phase 4：写能力与工作流迁移

周期：8-12 天
目标：把写操作纳入 dry-run、确认、幂等和审计。

优先域：

1. `decision_workflow`
2. `signal`
3. `account/portfolio write`
4. `simulated_trading`
5. `strategy`
6. `config_center`
7. `data_center sync`
8. `alpha/qlib ops`

任务：

1. 为每个写能力补 manifest 风险等级。
2. executor 支持 dry-run。
3. dispatcher 支持 confirmation token。
4. dispatcher 支持 idempotency key。
5. 审计记录补齐参数摘要、确认状态、影响对象。
6. 对高风险能力默认不允许自动执行。
7. preview / confirm / replay / conflict 四类写路径都必须产生可追溯审计事件。

验收：

1. 写能力首次调用只返回 preview。
2. 确认后才执行真实写入。
3. 缺少 idempotency key 的关键写操作被拒绝。
4. 审计记录可追溯 request_id。

当前状态（2026-07-10）：

1. 已落地的 governed write capabilities 如下；实时数量读取 `mcp_governance.governed_write_like_capability_count`：
   - `decision.create.execution_request`
   - `decision.submit.request`
   - `decision.submit.request_batch`
   - `decision.execute.request`
   - `decision.cancel.request`
   - `trading.submit.simulated_order`
   - `trading.close.simulated_position`
   - `trading.reset.simulated_account`
   - `trading.delete.simulated_account`
   - `trading.delete.simulated_account_batch`
   - `trading.create.simulated_account`
   - `policy.approve.workbench_event`
   - `policy.reject.workbench_event`
   - `policy.rollback.workbench_event`
   - `policy.override.workbench_event`
   - `trading.start.simulated_auto_trading`
   - `trading.run.simulated_daily_inspection`
   - `strategy.execute.run`
   - `strategy.bind.portfolio`
   - `strategy.unbind.portfolio`
   - `rotation.create.account_config`
   - `rotation.delete.account_config`
   - `rotation.update.account_config`
   - `rotation.apply_template.account_config`
   - `strategy.create.position_rule`
   - `strategy.update.position_rule`
   - `strategy.create.ai_config`
   - `strategy.update.ai_config`
   - `strategy.create.strategy`
   - `account.create.trading_cost_config`
   - `account.update.trading_cost_config`
   - `config_center.create.data_center_provider`
   - `config_center.update.runtime_setting`
   - `config_center.update.data_center_provider`
   - `data_center.create.publisher`
   - `data_center.delete.publisher`
   - `data_center.create.indicator`
   - `data_center.delete.indicator`
   - `data_center.create.indicator_unit_rule`
   - `data_center.delete.indicator_unit_rule`
   - `data_center.update.indicator_unit_rule`
   - `data_center.start.sync_job`
   - `data_center.update.publisher`
   - `data_center.update.indicator`
   - `filter.create.filter`
   - `ai_provider.create.provider`
   - `ai_provider.toggle.provider`
   - `ai_provider.update.provider`
   - `alpha_trigger.update.candidate_status`
   - `filter.update.filter`
   - `filter.delete.filter`
   - `account.import.positions`
   - `account.import.transactions`
   - `account.import.capital_flows`
   - `agent_proposal.create.proposal`
   - `agent_proposal.execute.proposal`
   - `agent_proposal.approve.proposal`
   - `agent_proposal.reject.proposal`
   - `signal.create.signal`
   - `signal.approve.signal`
   - `signal.reject.signal`
   - `signal.invalidate.signal`
2. dispatcher 已支持 confirmation staging 前先执行 preview，并在确认后用 commit args 继续执行。
3. 当前样板覆盖：
   - `decision_workflow_preview_execution`：`create_request=false -> true`
   - `import_positions_json`：`dry_run=true -> false`
   - `import_transactions_json`：`dry_run=true -> false`
   - `import_capital_flows_json`：`dry_run=true -> false`
   - `agent_proposal.create.proposal`：`preview_only=true -> false`
   - `decision.submit.request_batch`：`preview_only=true -> false`
   - `decision.submit.request`：`preview_only=true -> false`
   - `decision.execute.request`：`preview_only=true -> false`
   - `decision_cancel_request`：`preview_only=true -> false`
   - `execute_simulated_trade`：`preview_only=true -> false`
   - `close_simulated_position`：`preview_only=true -> false`
   - `reset_simulated_account`：`preview_only=true -> false`
   - `run_simulated_auto_trading`：`preview_only=true -> false`
   - `run_simulated_daily_inspection`：`preview_only=true -> false`
   - `execute_strategy`：`preview_only=true -> false`
   - `bind_portfolio_strategy`：`preview_only=true -> false`
   - `unbind_portfolio_strategy`：`preview_only=true -> false`
   - `create_account_rotation_config`：`preview_only=true -> false`
   - `delete_account_rotation_config`：`preview_only=true -> false`
   - `update_account_rotation_config`：`preview_only=true -> false`
   - `apply_rotation_template_to_account_config`：`preview_only=true -> false`
   - `create_position_rule`：`preview_only=true -> false`
   - `update_position_rule`：`preview_only=true -> false`
   - `create_ai_strategy_config`：`preview_only=true -> false`
   - `update_ai_strategy_config`：`preview_only=true -> false`
   - `create_strategy`：`preview_only=true -> false`
   - `create_trading_cost_config`：`preview_only=true -> false`
   - `update_trading_cost_config`：`preview_only=true -> false`
   - `update_qlib_runtime_config`：`preview_only=true -> false`
   - `data_center_create_publisher`：`preview_only=true -> false`
   - `data_center_delete_publisher`：`preview_only=true -> false`
   - `data_center_create_indicator`：`preview_only=true -> false`
   - `create_filter`：`save_results=false -> true`
   - `update_data_center_provider`：`preview_only=true -> false`
   - `data_center_update_publisher`：`preview_only=true -> false`
   - `data_center_update_indicator`：`preview_only=true -> false`
   - `agent_proposal.execute.proposal`：`preview_only=true -> false`
   - `agent_proposal.approve.proposal`：`preview_only=true -> false`
   - `agent_proposal.reject.proposal`：`preview_only=true -> false`
   - `signal.create.signal`：`preview_only=true -> false`
   - `signal.approve.signal`：`preview_only=true -> false`
   - `signal.reject.signal`：`preview_only=true -> false`
   - `signal.invalidate.signal`：`preview_only=true -> false`
   - `update_ai_provider`：`preview_only=true -> false`
   - `update_alpha_candidate_status`：`preview_only=true -> false`
   - `update_filter`：`preview_only=true -> false`
   - `delete_filter`：`preview_only=true -> false`
   - 六十二个缺失 `idempotency_key` 时直接拒绝
   - 六十二个同一 `idempotency_key` 的重复请求会命中 pending/completed replay 抑制
   - dispatcher 已产出统一写审计事件：`preview_staged`、`confirmation_cancelled`、`confirmation_completed`、`idempotent_replay`、`idempotency_conflict`
4. 当前所有 governed write 样板均已声明 scoped `audit_tags`，并已进入 CI 护栏。
5. 当前仍未完成：
   - 其他 write domains 的批量迁移
   - 幂等策略从首批账户/决策样板扩展到更多 write domains
   - governed write 审计从首批账户/决策样板扩展到更多 write domains / workflow executors
6. 下一批写整改顺序固定为：
   - `realtime.delete.price_alert` 已完成核验，并确认当前只保留 unsupported legacy contract，不进入 governed replacement
   - `trading.create.simulated_account`、`trading.delete.simulated_account`、`trading.delete.simulated_account_batch`、`policy.approve.workbench_event`、`policy.reject.workbench_event`、`policy.rollback.workbench_event` 与 `policy.override.workbench_event` 已完成迁移，当前已从单域生命周期样板推进到跨域审批/驳回/回滚/豁免四态样板
   - 下一优先级回到证据充分候选池，继续挑选下一条 raw tool / SDK / canonical API 或 internal handler 链条完整的 governed write
   - 未完成契约校正的域，不得把疑似失效 raw path 固化进 governed replacement

### Phase 5：Legacy Tools 收口

周期：5-8 天
目标：默认隐藏或停止注册旧工具。

任务：

1. 新增配置：
   - `AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS=false`
   - `AGOMTRADEPRO_MCP_LEGACY_ALLOWLIST=...`
2. `server.py` 默认只注册 core tools。
3. legacy tools 仅在显式开启时注册。
4. 对无法迁移但仍必要的工具标记 `legacy_compat`。
5. 删除 `remove` 类工具。

验收：

1. 默认 MCP 顶层 tools 不超过 10。
2. 显式开启 legacy 后旧工具仍可用于过渡。
3. 文档和启动欢迎信息只推荐新入口。
4. `terminal agent` 默认使用 core tools；legacy tools 仅在兼容开关打开时才进入它的 MCP surface。

### Phase 6：CI 护栏与质量门禁

周期：3-5 天
目标：防止重新失控。

任务：

1. 新增脚本检查 `@server.tool()` 只能出现在 core 或 legacy allowlist。
2. 新增 manifest schema 校验。
3. 新增 capability key 唯一性检查。
4. 新增风险确认检查。
5. 新增 Catalog 去重检查。
6. 新增 MCP tool 数量预算检查。
7. 更新 PR checklist。

验收：

1. CI 能阻止新增散装工具。
2. CI 能阻止无确认写能力。
3. CI 能阻止重复业务语义候选。
4. CI 能输出清晰错误信息和修复建议。

### Phase 7：文档、示例与验收回归

周期：2-4 天
目标：完成使用文档与回归闭环。

任务：

1. 更新 `docs/mcp/mcp_guide.md`。
2. 更新 `docs/mcp/mcp-deployment.md`。
3. 更新 SDK README。
4. 更新 MCP integration test plan。
5. 增加 Agent 使用示例：
   - 查询系统状态
   - 查询当前市场环境
   - 生成决策建议草案
   - dry-run 模拟调仓
   - 查询任务执行状态
6. 形成最终整改报告。
7. 补充 terminal agent 迁移说明，明确它当前是 MCP-backed，整改后仍是 MCP-backed，但只消费统一 core tools / capability tools。

验收：

1. 新文档只推荐统一入口。
2. 旧工具说明进入兼容章节。
3. MCP Inspector 验证通过。
4. 自动测试通过。
5. 形成整改前后对比。
6. terminal agent 迁移文档与实际运行形态一致。

---

## 5. 模块迁移策略

### 5.1 第一批：只读核心上下文

| 模块 | 目标能力 |
| --- | --- |
| `regime` | `system.read.regime.current`、`regime.read.history` |
| `pulse` | `pulse.read.current`、`pulse.read.history` |
| `policy` | `system.read.policy.status`、`policy.read.events`、`policy.read.workbench.bootstrap`、`policy.read.workbench.summary`、`policy.read.workbench.event_detail`、`policy.read.workbench.items`、`policy.read.sentiment_gate.state` |
| `task_monitor` | `system.read.task_monitor.statistics`、`task_monitor.read.celery_health` |
| `data_center` | `data_center.read.macro_series`、`data_center.read.indicator_catalog`、`data_center.read.provider_catalog` |
| `ai_provider` | `ai_provider.read.provider_catalog`、`ai_provider.read.provider_detail`、`ai_provider.read.usage_logs` |
| `filter` | `filter.read.indicator_catalog`、`filter.read.config_detail` |

### 5.2 第二批：账户与决策

| 模块 | 目标能力 |
| --- | --- |
| `account` | `portfolio.read.snapshot`、`portfolio.read.positions` |
| `decision_workflow` | `decision.read.context`、`decision.create.proposal` |
| `signal` | `signal.read.active`、`signal.create.investment_signal` |
| `audit` | `audit.read.decision_review` |

### 5.3 第三批：执行与运维

| 模块 | 目标能力 |
| --- | --- |
| `simulated_trading` | `trading.create.simulated_account`、`trading.dry_run.order`、`trading.submit.simulated_order`、`trading.close.simulated_position`、`trading.reset.simulated_account`、`trading.delete.simulated_account`、`trading.delete.simulated_account_batch`、`trading.start.simulated_auto_trading`、`trading.run.simulated_daily_inspection` |
| `strategy` | `strategy.read.catalog`、`strategy.read.detail`、`strategy.read.ai_config_catalog`、`strategy.read.ai_config_detail`、`strategy.read.position_rule_catalog`、`strategy.read.position_rule_detail`、`strategy.read.status`、`strategy.execute.run`、`strategy.bind.portfolio`、`strategy.unbind.portfolio`、`strategy.update.enabled_state`、`strategy.create.position_rule`、`strategy.update.position_rule`、`strategy.create.ai_config`、`strategy.update.ai_config`、`strategy.create.strategy` |
| `account` | `account.create.trading_cost_config`、`account.update.trading_cost_config` |
| `config_center` | `config_center.read.runtime_setting`、`config_center.update.runtime_setting`、`config_center.create.data_center_provider`、`config_center.update.data_center_provider` |
| `alpha` | `alpha.read.scores`、`alpha.start.inference` |
| `data_center` | `data_center.start.sync_job`、`data_center.create.publisher`、`data_center.delete.publisher`、`data_center.create.indicator`、`data_center.delete.indicator`、`data_center.create.indicator_unit_rule`、`data_center.delete.indicator_unit_rule`、`data_center.update.indicator_unit_rule`、`data_center.update.publisher`、`data_center.update.indicator` |
| `ai_provider` | `ai_provider.create.provider`、`ai_provider.update.provider`、`ai_provider.toggle.provider` |
| `alpha_trigger` | `alpha_trigger.update.candidate_status` |
| `filter` | `filter.update.filter`、`filter.delete.filter` |

---

## 6. 当前工具分类规则

### 6.1 保留为正式 capability

满足以下条件的旧工具可迁移为正式 capability：

1. 有明确业务任务语义。
2. 外部 Agent 可能自然使用。
3. 输入输出稳定。
4. 有 owner app。
5. 能给出风险等级和权限规则。

### 6.2 聚合

满足以下条件的旧工具应聚合：

1. 多个工具只是同一任务的不同参数变体。
2. 多个工具需要按固定顺序调用才能完成一个用户任务。
3. 工具名暴露了内部 API 或页面结构。

### 6.3 内部化

满足以下条件的旧工具不应继续暴露给 MCP：

1. 仅服务页面控件。
2. 仅服务 Dashboard 局部刷新。
3. 仅服务 TUI metadata 注入。
4. 仅服务调试。
5. 与外部 Agent 业务任务无关。

### 6.4 删除

满足以下条件的旧工具应删除：

1. 后端已无 canonical 能力。
2. 长期失败且无用户场景。
3. 被更高层 workflow 完全替代。
4. 安全风险大于收益。

---

## 7. 开发任务清单

### P0 必做

| 编号 | 任务 | 产物 | 验收 |
| --- | --- | --- | --- |
| P0-1 | 冻结新增 raw MCP tool | PR template / GitHub Actions MCP guards | 新 PR 不再新增散装工具 |
| P0-2 | 生成 tool inventory | JSON 报告 | 每个 tool 有 owner 和分类 | 已完成 |
| P0-3 | 新增技术标准文档 | `docs/mcp/mcp-technical-and-development-standard.md` | 文档进入索引 | 已完成 |
| P0-4 | 明确普通站内 AI 与 terminal agent 的边界 | Catalog 分流设计 | 设计评审通过 | 已完成（文档口径已校正，代码治理待进入 Phase 2） |

### P1 必做

| 编号 | 任务 | 产物 | 验收 |
| --- | --- | --- | --- |
| P1-1 | 实现 manifest 数据结构 | `registry/manifest.py` | 单测通过 |
| P1-2 | 实现 loader + validator | `registry/loader.py` | key/schema 校验通过 |
| P1-3 | 实现 dispatcher skeleton | `registry/dispatcher.py` | read 能力可调用 |
| P1-4 | 注册 core MCP tools | `tools/core_tools.py` | Inspector 可见 <= 10 个默认工具 |
| P1-5 | 迁移样板能力 | module manifests | 实时数量以 `governance/governance_baseline.json` 为准 |

当前进度说明（2026-07-10）：

1. `P1-1` 已完成。
2. `P1-2` 已完成。
3. `P1-3` 已完成。
4. `P1-5` 已完成，当前样板能力为：
   - `system.read.regime.current`
   - `regime.read.history`
   - `system.read.policy.status`
   - `policy.read.events`
   - `policy.read.workbench.bootstrap`
   - `policy.read.workbench.summary`
   - `policy.read.workbench.event_detail`
   - `policy.read.workbench.items`
   - `policy.read.sentiment_gate.state`
   - `system.read.task_monitor.statistics`
   - `task_monitor.read.task_status`
   - `task_monitor.read.task_list`
   - `data_center.read.provider_status`
   - `data_center.read.macro_series`
   - `data_center.read.indicator_catalog`
   - `data_center.read.provider_catalog`
   - `ai_provider.read.provider_catalog`
   - `ai_provider.read.provider_detail`
   - `ai_provider.read.usage_logs`
   - `filter.read.indicator_catalog`
   - `filter.read.config_detail`
   - `pulse.read.current`
   - `pulse.read.history`
   - `task_monitor.read.dashboard`
   - `task_monitor.read.celery_health`
   - write-like capability 的实时数量以 `governance/governance_baseline.json` 为准，当前最新配置生命周期样板为 `beta_gate.create.config` 与独立的 `beta_gate.rollback.config`
5. `P1-4` 已完成：core tools 已注册，默认 MCP 顶层 surface 已收口；实时工具数统一读取 `governance/governance_baseline.json`。

### P2 必做

| 编号 | 任务 | 产物 | 验收 |
| --- | --- | --- | --- |
| P2-1 | Catalog entrypoint 分流 | `apps/ai_capability` | 普通站内 chat 不选 MCP wrapper，terminal agent 走治理后 MCP capabilities |
| P2-2 | MCP manifest 同步 Catalog | sync command | MCP 能力 metadata 可见 |
| P2-3 | API/MCP 候选去重 | governance service | 同一语义不重复竞争 |
| P2-4 | legacy 开关 | server config | 默认隐藏旧工具 |
| P2-5 | legacy 测试兼容夹具 | test fixtures | raw tool 回归测试显式开启 legacy 模式 |

当前进度说明（2026-07-09）：

1. `P2-2` 已部分完成：
   - `sync_mcp_tools` 已能把 registry manifest 同步为 governed MCP capability 记录
   - 这些记录的 `execution_target.type` 为 `mcp_capability`
2. `P2-1` 已部分完成：
   - terminal agent 已优先切到 core tools + governed capability 路径
   - 普通站内 `web/chat` 已开始默认排除 MCP wrapper
   - 但更完整的 `semantic_key` 治理面仍需继续补齐
3. `P2-4` 已完成：
   - server 默认已切到 `legacy-off`
   - 默认顶层 surface 只暴露 core tools
   - legacy raw tool 如存在 replacement，已同步 `replacement_capability_key`
4. `P2-3` 已部分完成：
   - 普通站内 `web/chat` 不再默认让 MCP wrapper 进入候选竞争
   - `semantic_key` 已落地，路由层已开始按语义键做显式去重
   - 但“语义键治理台 / 人工校正表 / 批量审计工具”仍未形成独立治理面
5. `P2-5` 已完成：
   - 依赖 raw tool 默认可见的测试已显式切换到 `legacy-on`
   - default core-only 与 legacy compatibility 已拆分验证

### P3 必做

| 编号 | 任务 | 产物 | 验收 |
| --- | --- | --- | --- |
| P3-1 | 迁移第一批只读能力 | manifests + tests | 高频 read 能力通过 |
| P3-2 | 迁移写能力确认流程 | dispatcher confirmation | write 首次只 preview |
| P3-3 | 增加幂等 | idempotency store | 重试不重复写入 |
| P3-4 | 完整审计 | audit repository | request_id 可追溯 |
| P3-5 | CI 护栏 | scripts/tests | 阻止 raw tool 回归 |

### 当前推荐执行批次

这是后续继续整改时应优先执行的一批，不建议跳步：

1. `Batch C`：
   - 补第一批只读 capability manifest
   - 优先迁移 `regime`、`policy`、`task_monitor`、`data_center`
2. `Batch D`：
   - 继续补 CI 护栏脚本
   - 当前已落地：tool budget、manifest schema、raw tool 文件面冻结、catalog dedup / replacement、write-confirmation、write-preview、write-audit
   - 待补：更细粒度的写路径专用审计和跨域 rollout
3. `Batch E`：
   - 建立 `semantic_key` 人工治理面
   - 补语义冲突审计、人工校正和批量修正工具
4. `Batch F`：
   - 开始写能力 preview / confirmation / idempotency 统一迁移
   - 优先覆盖高风险能力和 workflow executor
5. `Batch G`：
   - 扩大统一写审计模板覆盖面
   - 保持 `preview_staged`、`confirmation_cancelled`、`confirmation_completed`、`idempotent_replay`、`idempotency_conflict` 五类事件口径一致

### 当前续做入口（2026-07-10，已按最新代码事实校正）

为避免后续继续整改时再从头判题，下一轮默认从以下入口继续：

1. `policy.read.workbench.items`、`policy.read.sentiment_gate.state`、`data_center.read.provider_catalog`、`ai_provider.read.provider_catalog`、`ai_provider.read.provider_detail`、`ai_provider.read.usage_logs`、`filter.read.indicator_catalog` 与 `filter.read.config_detail` 已于 `2026-07-10` 完成 governed read 迁移并通过最小验证集。
   - 当前治理统计以 `governance/governance_baseline.json` 为准；默认续做入口以 `0.2.3` 为准。
   - `policy` workbench read family 当前已扩展为 `bootstrap`、`summary`、`event_detail`、`items` 四段 governed read，并补齐了 `sentiment_gate.state`；`data_center` 侧已补上 `provider_catalog`，`ai_provider` 侧已补上 `provider_catalog`、`provider_detail` 与 `usage_logs`，`filter` 侧已补上 `indicator_catalog` 与 `config_detail`。
   - 同轮已修正 `sdk/agomtradepro/modules/policy.py` 中 `get_workbench_items()` 的 SDK 契约，使其按 canonical API 发送 `limit/offset`，不再错误发送 `page/page_size`。
2. `data_center.start.sync_job` 已于 `2026-07-10` 完成 `sync_macro`、`sync_capital_flows`、`sync_news` governed 子路径迁移并通过最小验证集。
   - `data_center.start.sync_job` 当前已形成统一 governed sync workflow 入口；在 `sync_prices`、`sync_quotes` 未补齐 raw MCP tool 证据前，不再继续假定它们可以顺延进入同一整改批次。
3. `ai_provider.read.provider_catalog`、`ai_provider.read.provider_detail` 与 `ai_provider.read.usage_logs` 已完成完整闭环。
   - 已完成项：manifest、core-only fallback、registry / catalog metadata、focused API 契约、SDK endpoint contract、tool registration 回归与全部 governance guards。
   - 当前这三条能力已正式计入上面的已验证统计口径，不再保留“待验证”状态。
4. unsupported legacy contract 清单化与治理面隔离已于 `2026-07-10` 落地首个显式样板。
   - `sdk/agomtradepro/unsupported_legacy_contracts.py` 维护机器可读 contract 清单，实时数量读取 `governance/governance_baseline.json`。
   - `scripts/generate_mcp_tool_inventory.py` 当前会把 `realtime.delete.price_alert` 对应的 raw tools 标记为 `unsupported_legacy_contract`，不再混入普通 governed 候选语义；实时数量由机器基线维护。
5. 新增 write 候选的证据门禁已于 `2026-07-10` 落地。
   - `scripts/check_mcp_write_evidence.py` 当前会对全部 governed write-like manifests 校验 raw tool、server execution path 与核心契约测试证据；实时数量统一读取 `governance/governance_baseline.json`。
   - `.github/workflows/consistency-check.yml` 已接入该门禁，后续新增 write migration 不再允许绕过证据链进入 CI。
6. 第一优先项已改为沿 raw-tool gap 审计结果继续推进，并筛出下一条证据链完整候选。
   - 进入下一批迁移前，必须先通过已落地的“raw tool + SDK + canonical API 或 internal handler + 现有契约测试”证据门禁。
   - `policy.read.workbench.items`、`policy.read.sentiment_gate.state`、`data_center.read.provider_catalog`、`ai_provider.read.provider_catalog`、`ai_provider.read.provider_detail`、`ai_provider.read.usage_logs`、`filter.read.indicator_catalog`、`filter.read.config_detail`、`prompt.read.template_catalog`、`prompt.read.chain_catalog`、`risk_center.read.floor`、`risk_center.read.template_catalog`、`risk_center.read.effective_policy`、`risk_center.read.account_policy`、`risk_center.read.exception_list`、`risk_center.read.pre_trade_check`、`risk_center.read.post_investment_check`、`risk_center.read.daily_report`、`risk_center.read.daily_report_history`、`data_center.create.publisher`、`data_center.delete.publisher`、`filter.create.filter`、`data_center.create.indicator`、`data_center.delete.indicator`、`data_center.create.indicator_unit_rule`、`data_center.delete.indicator_unit_rule`、`data_center.update.indicator_unit_rule` 与 `data_center.start.sync_job`（`sync_macro`、`sync_capital_flows`、`sync_news`）已于 `2026-07-10` 完成迁移并通过 registry / catalog / guard / focused regression；默认续做入口不再停留在 `list_data_center_providers`、`list_ai_providers`、`get_ai_provider`、`list_ai_usage_logs`、`list_filters`、`get_filter`、`list_prompt_templates`、`list_prompt_chains`、`get_risk_floor`、`list_risk_templates`、`get_effective_risk_policy`、`get_account_risk_policy`、`list_risk_exceptions`、`check_pre_trade_risk`、`check_post_investment_risk`、`get_risk_center_daily_report` 或 `list_risk_center_daily_reports`，同时继续冻结 `sync_prices` / `sync_quotes`。
   - 本轮新增完成项为 `data_center.read.price_history` 与 `realtime.read.market_summary`；`get_sector_realtime_performance` 与 `get_top_movers` 已形成明确冻结结论，不进入默认迁移序列。
   - 后续同批新增 `data_center.read.latest_quote`、`data_center.read.news` 与 `data_center.read.capital_flows`；资金流 persisted read 已统一为 `asset_code/start/end/limit`，不再接受 legacy `period`。
   - Data Center catalog detail read family 已新增 `publisher_catalog`、`publisher_detail`、`indicator_detail`、`indicator_unit_rules` 与 `indicator_unit_rule_detail`，后续执行人不应重复把对应 raw tools 列为待迁移项。
   - Data Center 当前 raw read 已实现“已治理或显式冻结”；`data_center_get_capital_flows` 已由 `data_center.read.capital_flows` replacement，不再属于冻结入口。
   - Sentiment read family 已新增 `sentiment.read.index`、`sentiment.read.recent` 与 `sentiment.read.health`；对应 legacy raw tools 已建立 replacement，后续执行人不应再把它们列为默认迁移候选。
   - Events read family 已新增 `events.read.query`、`events.read.metrics` 与 `events.read.status`；`publish_event` 已收口为 `events.publish.event`，`replay_events` 因 canonical handler 目标缺失继续冻结。
   - Audit 首批 read 已新增 `audit.read.summary` 与 `audit.read.execution_links`；其余只有 SDK/API、缺 raw tool 的 Audit 读取不得顺带迁移。
   - Decision Workspace 首批 pure read 已新增 `decision.read.recommendation_list` 与 `decision.read.transition_plan_detail`；`decision_workflow_get_funnel_context` 因 cache miss 会写入 ActionRecommendationLog，继续冻结。
   - Unified Account / Simulated Trading 直接读取子集已新增 `account.read.account_list`、`account.read.account_detail`、`account.read.account_positions`、`account.read.account_performance` 与 `simulated_trading.read.daily_inspection_list`。这批能力使用独立受控 fallback ref，避免 legacy-on 模式绕过统一 envelope；canonical API 继续执行认证与账户所有权校验。
   - Unified Account list 只发布 `active_only` 与可选 `account_type`，不继承 canonical view 未执行的 legacy `limit`，也不把语义不精确的 legacy `status` 固化进新契约。Performance 明确要求日期成对提供，并用 `basic/date_range` 区分基础摘要和区间报告。
   - Legacy Portfolio 读取已新增 `account.read.portfolio_catalog`、`account.read.portfolio_detail`、`account.read.position_records`、`account.read.transaction_records` 与 `account.read.capital_flow_records`；`account.read.positions` 同步改用 read-only position SDK。三个 JSON export raw tools 只是同一 records 数据的对象包装，已作为 legacy aliases 并入对应 records capability，不新增重复 export capability。Portfolio 与 position 读取继续允许有效 observer grant，transaction/capital-flow 继续保持 owner-scoped canonical permission。
   - `/api/account/positions/read-only/` 只查询 persisted legacy projection，不调用 `_ensure_portfolio_ledger_synced()`、`UnifiedPositionService` 或 mapping bootstrap；API side-effect contract 会在读取前后比较统一账户、统一持仓与 ledger mapping，禁止后续把读取重新退化成迁移触发器。
   - `export_positions_csv`、`export_transactions_csv`、`export_capital_flows_csv` 与 `export_account_bundle_json` 继续保留在 legacy compatibility / local formatting 审计池：CSV 文本不是新的业务能力契约，整包导出属于跨资源 composite，不能借单项 records 证据直接合并。
   - Policy RSS 同步抓取已新增 `policy.start.rss_fetch`。Canonical workbench fetch 已收紧为 staff-only 严格输入；指定停用源在网络与写入前失败。Governed preview 只通过正式 Policy SDK 读取 source catalog/detail，并披露外部 RSS/AI、raw log、event、fetch log、source status、告警和部分成功风险；确认后 commit 才调用正式同步 fetch endpoint。Legacy `trigger_rss_fetch` 已建立 replacement，并满足 confirmation、required idempotency、MCP lifecycle audit、API/SDK/registry/catalog 与全部 write guards。
   - Audit 阈值验证已新增 `audit.start.threshold_validation`。原 `RunValidationView` 已拆入独立 validation API 模块并收紧为 staff-only 严格日期合同，移除动态一年默认；新增 canonical preview 只读取 active threshold 配置，不运行指标分析、不读取宏观/Regime 历史、不写 validation summary 或 performance report。确认后 commit 才调用正式 Audit SDK 的同步 run endpoint。Legacy `run_audit_validation` 已建立 replacement，并满足 confirmation、required idempotency、MCP lifecycle audit、API 零写预览/权限/输入、SDK、registry replay、catalog 与全部 write guards。
   - Raw `validate_all_indicators` 已确认是阈值验证的动态日期重复入口，不新增 governed capability。它已作为 `audit.start.threshold_validation` 的 legacy alias 建立 replacement；旧 `/api/audit/validate-all-indicators/` route 复用同一个 staff-only strict `RunValidationView`，legacy-on 不能再绕过统一权限和日期合同。
   - Audit 指标阈值更新已新增 `audit.update.threshold_levels`。Canonical preview/commit 已拆入独立 threshold-config API 模块并统一为 staff-only 严格合同；预览只读取精确 active config，披露 current/target/changed fields，配置不存在、无变化、非法上下限均在确认前失败。确认后 commit 只通过正式 Audit SDK 更新 `level_low/level_high`，legacy `update_audit_threshold` 已建立 replacement，并满足 confirmation、required idempotency、MCP lifecycle audit、API/SDK/registry/catalog 与全部 write guards。
   - Audit 归因报告生成已新增 `audit.create.attribution_report`。Canonical preview/commit 已拆入独立 attribution-report API 模块并统一为 staff-only 严格 `backtest_id` 合同；不存在或未完成回测会在外部行情访问和写入前失败。预览只读取回测元数据及既有报告数量，并披露历史行情访问、报告及子记录写入、重复报告与部分写入风险。确认后 commit 才通过正式 Audit SDK 同步生成，legacy `generate_audit_report` 已建立 replacement，并满足 confirmation、required idempotency、MCP lifecycle audit、API/SDK/registry/catalog 与全部 write guards。
   - Config Center 聚合摘要已新增 `config_center.read.snapshot`。Canonical API 保持 staff-only，Account、Config Center 与 Data Center summary repository 的 singleton 缺失分支已改为 unsaved in-memory defaults，Qlib summary 已修复 actor 透传；focused SQL contract 证明整次 snapshot 请求无 INSERT/UPDATE/DELETE。Controlled fallback 只调用正式 SDK `get_snapshot()`，legacy `get_config_center_snapshot` 已建立 replacement，并具备 medium-risk read audit tags、SDK/core-only/catalog/read-evidence 回归。
   - Alpha 批量评分缓存导入已新增 `alpha.import.score_cache`。Canonical preview 与 commit 共享严格批次 serializer 和精确 upsert target，preview 只读取目标并证明无 SQL 写入，system scope 保持 staff-only；internal handler 分别只调用正式 SDK preview/upload 方法，不下传治理参数。Legacy `upload_alpha_scores` 已建立 replacement，并具备 confirmation、required idempotency、MCP lifecycle audit、API/SDK/registry/catalog 与全部 write guards。
   - 本轮 raw-tool gap 复核冻结 `get_alpha_stock_scores`、`get_stock_detail`、`list_rotation_assets`、`get_asset_info`、`get_recommended_assets` 与 `get_sector_score`：它们分别存在混合 provider/task 链、SDK 本地 pool 扫描、动态价格聚合、raw 硬编码、忽略参数或缺真实 canonical endpoint。后续不得把这些入口误 alias 到 persisted catalog/detail，也不得只补 manifest 制造伪收口。
   - 本批 large-file growth 已按职责拆分收口，没有提高 machine baseline allowance：Account legacy read projection 归入 `AccountReadRepository`，AI Capability 的 MCP runtime gateway 与 catalog projection 独立成模块，Terminal 用户 AI 配额 metadata 独立成 bundle；实际检查结果只读取 `governance/governance_baseline.json`。
   - MCP 大文件继续按 owner 分片：Audit validation/update internal handlers 已迁出 `server.py`，Audit write manifests 已迁出总写清单，新增 registry 与 catalog 测试使用独立 focused shard；write-evidence guard 已改为扫描受控 handler/test 目录，避免门禁反向迫使代码回填巨型文件。
   - Config Center snapshot 同步建立独立 read handler、manifest、registry 与 catalog shard；read-evidence guard 已改为扫描受控 focused test 目录和 split handler import alias，后续 governed read 不得再扩大 `server.py` 或两个历史巨型测试文件。
   - MCP 历史 manifest 聚合文件已按 owner 拆入显式 `registry/modules/owners/` 分片，loader 直接装配受控 owner 模块；原 read/write 聚合文件只保留兼容汇总，不再承载 manifest 实现。`server.py` 中的业务 fallback 与 preview/commit handler 已按 owner 迁入 `registry/runtime_handlers/owners/`，server 只保留 composition、外部 owner adapter、dispatcher 和 resource/prompt 装配。Read/write evidence guard 已改为递归扫描受控 handler 分片，正式 SDK 与 MCP SDK 也已纳入机器 large-file 门禁，未增加任何 allowance。
   - MCP core registry 与 AI Capability API/use-case 的历史巨型测试聚合已拆为 owner/focused shards；共享 fixture/helper 进入非测试 support 模块，跨 owner read matrix 进一步按 owner 拆分参数 case。MCP、SDK endpoint 与 AI Capability focused test roots 已纳入同一机器 large-file ratchet，evidence guard 可继续从分片测试定位全部 read/write 证据。
   - Hedge 单对有效性已新增 `hedge.compute.effectiveness`。Canonical pair action 现在固定以 `cache_price_reads=False` 执行，只读取持久化 pair 与既有价格数据，不写价格缓存、correlation history、portfolio snapshot、alert 或 performance。Controlled fallback 只调用正式 SDK，输出统一包含 `is_effective`，legacy `check_hedge_effectiveness` 与 `is_my_hedge_still_working` 已共享 replacement，并具备 API/SDK/core-only/catalog/read-evidence 回归。
   - Dashboard 权益曲线已新增 `dashboard.read.equity_curve`。Controlled fallback 只调用正式 SDK `equity_curve_v1()`，输出固定为 `range/has_history/series`；canonical GET 没有 cache decorator，focused SQL contract 证明请求不执行数据库 mutation。Legacy `get_dashboard_equity_curve_v1` 已建立 replacement，并具备 SDK/core-only/catalog/read-evidence 回归。Dashboard summary/regime/signal 的缓存写入证据尚未分离，继续冻结；positions 的历史契约分裂已由独立 JSON route 解决。
   - Regime 与 Pulse 联合行动建议已新增 `regime.read.action_recommendation`。Use case 增加显式 refresh/persist 控制，canonical GET 固定 `refresh_pulse_if_stale=False`、`persist_result=False`，不再刷新 Pulse 或写 `ActionRecommendationLog`；默认用例行为仍保留给非 GET 的显式生成场景。Controlled fallback 只调用正式 Pulse SDK 的 canonical Regime endpoint，完整保留 decision-safety contract；legacy `get_action_recommendation` 已建立 replacement，并具备 API SQL 零写、use-case、SDK/core-only/catalog/read-evidence 回归。
   - Backtest 持久化权益曲线已新增 `backtest.read.equity_curve`。Canonical detail action 只读取既有 JSON curve，并在 Backtest owner scope 完成前固定 staff-only；普通用户返回 403，focused SQL contract 证明无数据库 mutation。正式 SDK 新增稳定 envelope 方法，legacy list-only 方法继续兼容；`get_backtest_equity_curve` 已建立 replacement，并具备 SDK/core-only/catalog/read-evidence 回归。Run/delete/rerun/replay 与 detail/list owner scope 债务不属于本能力完成范围。
   - `get_alpha_factor_exposure` 复核后继续冻结：SDK 与 raw tool 都直接启动本地 Django `AlphaService`/provider，不走 canonical HTTP，Qlib/simple/ETF provider 的数据访问边界也未形成统一无副作用合同；补齐 canonical owner API 前不得仅加 manifest。
   - Dashboard 用户资产配置已新增 `dashboard.read.asset_allocation`。Canonical JSON endpoint 只读取 authenticated user 的模拟账户及持仓，并在内存中按资产类别聚合；zero-argument capability 不扩张 `account_id` 过滤。Controlled fallback 只调用正式 SDK `allocation()`，输出固定为 `allocation/total_market_value`；legacy `get_dashboard_allocation` 已建立 replacement，并具备 API SQL 零写、SDK/core-only/catalog/read-evidence 回归。
   - Dashboard 用户持仓目录已新增 `dashboard.read.position_catalog`。原 `/api/dashboard/positions/` 继续保留 HTMX/redirect 产品语义，新 `/api/dashboard/positions/data/` 提供 authenticated JSON；正式 SDK `positions()` 已切换到新 route。Zero-argument capability 聚合当前用户全部模拟账户并保留 account metadata，不调用 dashboard backfill 或 ledger sync。Legacy `get_dashboard_positions` 已建立 replacement，并具备 API discovery/SQL 零写、SDK/core-only/catalog/read-evidence 回归。
   - Data Center Provider 连通性测试已按实际副作用收口为 `data_center.run.provider_connection_test`，不得按 read 治理。Canonical POST 保持 staff-only，真实探测会访问外部 provider、执行解析路径并持久化 provider health metadata；Application workflow 在返回和持久化前按 provider credential 精确脱敏，provider create/detail/update 响应只返回安全字段及 credential presence flags。Governed preview 只通过正式 SDK 读取安全 provider metadata，明确披露外部访问、解析和健康状态写入，不执行探测、不写 health metadata、不同步 market facts；确认后 commit 才调用正式 SDK test endpoint。Legacy `test_data_center_provider_connection` 已建立 replacement，并满足 confirmation、required idempotency、MCP lifecycle audit、API/SDK/registry/catalog 与全部 write guards。
   - 本批继续执行大文件 ratchet：Provider capability 映射与 connection workflow 已从历史 `data_center/application/use_cases.py` 拆入独立 Application 模块，机器 allowance 随实际缩减而下调；新增 API、registry 和 catalog 测试均进入 focused shard，未提高任何大文件豁免。
   - 下一候选审计确认 `get_dashboard_summary_v1`、`get_dashboard_regime_quadrant_v1` 与 `get_dashboard_signal_status_v1` 继续冻结。三条 canonical V1 view 均复用完整 `GetDashboardDataUseCase.execute()`；该链在 profile 或 portfolio 缺失时会创建默认记录，还会执行 AI insight 生成，summary/regime view 另有 response-cache 写入。不得只移除 `cached_api` 就按 pure read 迁移；必须先拆出 user-scoped strict read projection，禁止默认对象创建、AI/外部调用、cache write 和其他隐式刷新，再分别补 API SQL/外部调用证据。
   - `get_trade_history`、equity curve、valuation、benchmark 及其他只有 SDK/API、缺 raw MCP 证据的扩展读取继续冻结，不得借本批账户读取验收结果顺带迁移。
   - Strategy 基础 strategy catalog/detail、AI config catalog/detail、position rule catalog/detail 与两条 position evaluate 纯计算已完成 owner/staff scoped governed 收口；script config、rule condition、assignment 缺 raw MCP tool，performance、signals、positions 等 SDK 方法仍指向当前 ViewSet 未实现的 action，因此这些剩余路径继续冻结。
   - Equity valuation repair list、freshness、latest quality snapshot、status/history 纯计算及 active config/config catalog 已完成 governed 收口；其他 Equity 路径继续按参数漂移、canonical owner、workflow/write 与副作用证据冻结。
   - Hedge 直接读取子集已新增 `hedge.read.pair_catalog`、`hedge.read.pair_detail`、`hedge.read.alert_list` 与 `hedge.read.portfolio_state`。四条能力只读取持久化 pair、active alert 和 latest snapshot，不触发 effectiveness、correlation 或 portfolio refresh。
   - Hedge 多资产相关性矩阵已新增 `hedge.compute.correlation_matrix`：该能力通过 raw tool、正式 SDK、canonical POST、core-only fallback、catalog replacement 与 focused pure-calculation contract。
   - 矩阵链只读取持久化 price bars 或现有缓存，并显式以 `cache_result=False` 禁止成功价格读取回写 cache；API 计数合同证明不创建相关性历史、告警或组合快照。
   - 单对 `calculate_correlation` 仍会保存 `CorrelationHistoryModel`，不得使用矩阵纯计算证据迁移；effectiveness、monitoring、portfolio update 以及 raw-only explanation/recommendation 继续按实际副作用或缺 canonical owner 分流。
   - Asset Analysis 直接读取子集已新增 `asset_analysis.read.weight_config_catalog`、`asset_analysis.read.current_weight` 与 `asset_analysis.read.pool_summary`。当前权重的无配置降级只构造默认值，不创建数据库行；资产池摘要只读取持久化统计。
   - `asset_multidim_screen`、`asset_pool_screen` 及其任意 payload/composite 路径继续冻结，必须先证明评分上下文构建、资产筛选和池构建链的副作用分类。
   - Equity 估值持久化读取子集已新增 `equity.read.valuation_repair_list`、`equity.read.valuation_freshness` 与 `equity.read.valuation_quality_latest`。repair list 输出固定为 `repairs + total_count + query`；freshness 与 latest quality 不执行同步、扫描、验证或快照创建。
   - `get_stock_valuation`、repair status/history、score/detail/recommendation/composite analysis、scan/sync/validate 和 valuation config family 已按参数漂移、纯读证据、canonical owner、workflow/write、staff 权限与 fallback 语义分别冻结。
   - Dashboard Auto Advisor read family 已新增 `decision.read.advisor_sheet`、`dashboard.read.auto_advisor_console`、`dashboard.query.auto_advisor`、`dashboard.read.auto_advisor_weekly_report`、`dashboard.read.auto_advisor_weekly_report_history` 与 `dashboard.read.auto_advisor_notifications`。动态读取不会写名称缓存、同步手工组合 ledger、持久化风险默认配置或生成周报输出记录。
   - Dashboard weekly report POST 继续按 workflow/write 治理；除已治理的 `dashboard.read.equity_curve`、`dashboard.read.asset_allocation` 与 `dashboard.read.position_catalog` 外，内部 v1/Alpha 聚合继续保持 internal-only。
   - Factor 直接目录读取已新增 `factor.read.definition_catalog` 与 `factor.read.config_catalog`。两条能力复用 authenticated canonical GET 和正式 SDK，只执行 definitions/configs 仓储读取并返回命名对象 envelope。
   - Factor top-stocks 已新增 `factor.compute.top_stocks`。该能力复用 authenticated canonical POST 和正式 SDK，只读取 active definitions、股票主数据及 Data Center 已有估值、财务、价格事实；默认偏好已修正为有效正权重，价格读取以 `cache_price_results=False` 禁止回写进程缓存，focused contract 证明不新增 exposure、holding、config 或股票记录。
   - Factor portfolio SDK 直连 Infrastructure 与 create-portfolio 等写入路径继续冻结，不得借 top-stocks 或 stock-explanation 的纯计算证据顺带迁移。
7. unsupported legacy contract 要继续单独维护，不与 governed replacement 候选池混放。
   - 当前明确样板是 `realtime.delete.price_alert`：它是显式 unsupported legacy contract，不是待迁移 capability。

### 当前推荐下一批整改顺序（2026-07-12，按最新续做入口重排）

上一轮已完成多域 governed read/write 收口，最新补齐 Unified Account、Hedge、Asset Analysis、Equity 估值持久化读取、Dashboard Auto Advisor read family、Factor definition/config catalog、top-stocks pure compute、`beta_gate.create.config`、`data_center.read.capital_flows`、`alpha_trigger.read.performance`、`equity.read.valuation_analysis`、`sector.read.rotation_ranking`、`fund.compute.screen`、`policy.start.rss_fetch`、`audit.start.threshold_validation`、`audit.update.threshold_levels`、`audit.create.attribution_report` 与 `config_center.read.snapshot`，并修正 `fund.read.ranking` 的 persisted-only 边界；`realtime.delete.price_alert` 仍作为 unsupported legacy contract 与普通候选分流。当前新的下一轮整改动作，按优先级从上到下执行；原则是继续只迁移证据链完整的能力，避免把错误 raw path 继续制度化：

| 顺序 | 优先迁移目标 capability / 动作 | 当前 raw tool / 语义来源 | 迁移原因 | 最低验收 |
| --- | --- | --- | --- | --- |
| 1 | 审计下一条未治理 raw 能力 | raw-tool gap inventory | `get_stock_valuation` 已统一为 `equity.read.valuation_analysis` 并完成纯读证据，不得继续作为候选；`get_stock_financials` 是空 SDK 实现 | 只选择同时具备 raw/internal handler、正式 SDK、canonical contract 和 focused evidence 的能力；证据不完整则冻结 |
| 2 | 冻结 `sync_prices` / `sync_quotes` 直至补齐 raw MCP tool 证据 | SDK `sync_prices()` / `sync_quotes()` + canonical API | 这两个子路径虽已有 SDK 与 canonical API，但当前缺少 raw MCP tool，不满足现行 write-evidence gate；必须先补证据或继续冻结，不能直接进入 governed 迁移 | 证据 review 结论入文档，并在补齐前保持“不进入下一优先项” |
| 3 | 没有 raw tool 的候选继续留在审计池，不进入默认迁移 | 如 `provider_usage_stats` / `overall_stats` / `get_template` 一类仅有 SDK/API 的路径 | 现行治理标准要求 external MCP 能力保留 raw tool 证据或受控 internal handler 证据；缺口未补齐前，不得为了推进数字继续制度化错误入口 | 在补齐证据前保持“不可进入默认续做入口” |
| 4 | 冻结无 canonical endpoint 或带隐式副作用的伪 read | `get_sector_realtime_performance` / `get_top_movers` | 前者没有真实 endpoint；后者通过 POST 触发快照刷新。两者都不满足 governed read 语义 | 补齐 GET contract，或显式改为 workflow/write 并满足确认、幂等和审计标准 |
| 5 | 审计 Data Center 下一条未治理 raw 能力 | raw-tool gap inventory | `data_center_get_capital_flows` 已统一为 `data_center.read.capital_flows`，不得继续占用默认入口 | 从 inventory 重新选择同时具备 raw/internal handler、正式 SDK、canonical contract 和 focused evidence 的候选 |
| 6 | 继续冻结 Factor 剩余路径 | `FactorModule.get_portfolio()` / Factor create actions | Backtest equity curve canonical action 已完成；Factor portfolio 仍由 SDK 直接导入 Infrastructure Repository，组合生成属于未治理写入路径 | Factor portfolio 先修复 SDK/Application 架构，create 路径完成 preview/confirmation/idempotency/audit 后再审计 |
| 7 | 分流 Alpha 剩余路径 | trigger / refresh / factor exposure | 两条 staff-only ops overview 已完成；trigger/refresh 有任务副作用；factor exposure 直接启动本地 Django service | trigger/refresh 按 workflow/write 治理；factor exposure 先补 canonical HTTP owner 与 focused contract |
| 8 | 分流 Alpha Trigger 剩余路径 | trigger detail / create / evaluate / invalidation / generate | trigger detail 缺 raw tool；performance 已完成只读收口；其余路径存在创建、状态更新或候选生成副作用 | 分别补齐 raw/internal-handler 证据，或按 write/workflow 完成 confirmation、idempotency、preview 和 audit |
| 9 | 分流 Decision Rhythm 剩余路径 | cooldown / trend / statistics / quota by-period | 这些读取只有 SDK/API、缺 raw MCP tool | 补齐 raw/internal-handler 证据后再迁移；不得借用已完成的 quota reset 写证据 |
| 10 | 冻结 Decision Funnel 聚合上下文 | raw `decision_workflow_get_funnel_context` + SDK `get_funnel_context()` + canonical GET | 无已落库 Rotation signal 时仍可能生成并保存新信号；SDK 默认 `trade_id=unknown` 还会默认进入可选 Step 6 分支，不是稳定纯读合同 | 拆分只读 snapshot 与生成 workflow，移除默认伪 trade ID，分别补纯读或 confirmation/idempotency/audit 证据 |

`policy.read.workbench.items`、`policy.read.sentiment_gate.state`、`data_center.read.provider_catalog`、`ai_provider.read.provider_catalog`、`ai_provider.read.provider_detail`、`ai_provider.read.usage_logs`、`filter.read.indicator_catalog`、`filter.read.config_detail`、`prompt.read.template_catalog`、`prompt.read.chain_catalog`、`risk_center.read.floor`、`risk_center.read.template_catalog`、`risk_center.read.effective_policy`、`risk_center.read.account_policy`、`risk_center.read.exception_list`、`risk_center.read.pre_trade_check`、`risk_center.read.post_investment_check`、`risk_center.read.daily_report`、`risk_center.read.daily_report_history`、`data_center.create.publisher`、`data_center.delete.publisher`、`filter.create.filter`、`data_center.create.indicator`、`data_center.delete.indicator`、`data_center.create.indicator_unit_rule`、`data_center.delete.indicator_unit_rule`、`data_center.update.indicator_unit_rule` 与 `data_center.start.sync_job`（`sync_macro`、`sync_capital_flows`、`sync_news`）已于 `2026-07-10` 完成迁移，当前下一执行人不应再把默认续做入口停留在任何已完成项，而应先回到 raw-tool gap 审计，重新筛出下一条证据链完整的候选。

以下条目是无序执行证据，不是完成数量清单；不得按条目数推导当前 governed、legacy 或 replacement 规模：

- `policy` workbench read family 当前高频上下文已经扩到 `bootstrap`、`summary`、`event_detail`、`items`，且 `sentiment_gate.state` 已形成配套 read 样板，继续停留在同一小域的边际收益会变低。
- `list_data_center_providers`、`list_ai_providers`、`get_ai_provider`、`list_ai_usage_logs`、`list_filters` 与 `get_filter` 已经完成 governed read 收口并计入当前已验证基线，不应继续占用默认续做入口。
- `list_prompt_templates`、`list_prompt_chains` 与 `get_risk_floor` 已完成 governed replacement，并通过 focused success contract、registry/catalog 回归与全部 governance guards。
- `list_risk_templates` 已完成 focused success contract 对齐，并通过 risk center integration、SDK、registry、catalog 与 governance guards，已不再占用默认续做入口。
- `get_effective_risk_policy` 已完成 focused success contract、SDK endpoint contract、registry/catalog 回归与 governance guards，已不再占用默认续做入口。
- `get_account_risk_policy` 已完成 focused integration、SDK endpoint contract、registry/catalog 回归与 governance guards，已不再占用默认续做入口。
- `list_risk_exceptions` 已完成 focused list success contract、SDK endpoint contract、registry/catalog 回归与 governance guards，已不再占用默认续做入口。
- `check_pre_trade_risk` 已完成 focused integration、现有 SDK contract、registry/catalog 回归与 governance guards，已不再占用默认续做入口。
- `check_post_investment_risk` 已完成 focused integration、现有 SDK contract、registry/catalog 回归与 governance guards，已不再占用默认续做入口。
- `get_risk_center_daily_report` 已完成 integration history/exact-report 契约覆盖、现有 SDK contract、registry/catalog 回归与 governance guards，已不再占用默认续做入口。
- `list_risk_center_daily_reports` 已完成 manifest、fallback、SDK contract、registry/catalog 与 governance guards 回归，并正式收口为 `risk_center.read.daily_report_history`，因此不应继续占用默认续做入口。
- `list_prompt_logs`、`get_template` 一类路径当前仍只有 SDK/API，没有 raw tool；补齐证据前不能进入默认迁移项。
- `sync_prices`、`sync_quotes` 虽然已有 SDK / canonical API，但当前缺少对应 raw MCP tool 证据，按现行 write-evidence gate 不能直接写进“下一优先项”。
- `decision_workflow_list_recommendations` 与 `decision_workflow_get_transition_plan` 已分别收口为 `decision.read.recommendation_list`、`decision.read.transition_plan_detail`，不应继续占用默认续做入口。
- `decision_workflow_get_funnel_context` 的 GET 链路在 action recommendation cache miss 时会写入 `ActionRecommendationLog`；拆出 cached-only read 或完成 workflow/write 治理前必须保持冻结。
- Config Center 能力目录、Qlib runtime、训练模板、Alpha universe 目录与成员、训练任务列表与详情已完成 staff-only governed read 收口，不应继续占用默认续做入口。
- `get_config_center_snapshot` 仍是跨模块聚合入口；在每个 summary builder 的纯读证据闭合前保持冻结，不得用本批次直接读取能力的验收结果替代 snapshot 自身证据。
- Rotation 象限、模板、账户配置、资产主数据和最新持久化信号已完成 governed read 收口，不应继续占用默认续做入口。
- Rotation recommendation、带价格资产和资产比较仍需单独证明生成、行情、缓存和 POST 计算副作用；Rotation 相关性矩阵已证明禁止缓存写入，并作为 `hedge.compute.correlation_matrix` 的 legacy alias 收口，不得再创建重复 capability。
- Unified Account / Simulated Trading 的账户目录、详情、持仓、绩效和日更巡检列表已完成 governed read 收口；后续执行人不得再把对应 legacy aliases 作为独立迁移目标。
- Strategy 基础目录/详情、AI config 目录/按策略详情、position rule 目录/按策略详情及两条 position evaluate 纯计算已分别完成 governed 收口：普通用户 canonical queryset 只返回本人 strategy 及关联配置/规则，staff/superuser 可读全量，跨用户读取与计算返回 404，SDK 不再发送 API 未执行的 `status/limit` 伪过滤。Script config、rule condition、assignment 当前缺 raw MCP tool；performance、signals、positions 仍须补真实 DRF action，完成前继续冻结。
- Hedge pair catalog/detail、active alerts、latest persisted portfolio state 与纯计算 correlation matrix 已完成 governed 收口。单对 correlation、effectiveness、monitor/update 及 raw-only explanation/recommendation 必须继续按持久化副作用、workflow/write 或缺 canonical owner 分流。
- Asset Analysis 权重目录、当前生效权重和资产池摘要已完成 governed read 收口；多维筛选和资产池筛选仍属于 POST/composite 计算链，不能因同域直接 GET 已验收就自动迁移。
- Equity valuation repair list、freshness、latest quality snapshot、status/history 纯计算及 active config/config catalog 已完成 governed 收口；实时计算不写运行时配置缓存，history 保留 canonical provenance，配置读取保持 staff-only 且不持久化默认值。其他 Equity 路径继续按已记录的参数漂移、canonical owner、workflow/write 与副作用结论冻结。
- Dashboard Auto Advisor decision sheet、console、deterministic query、weekly report GET、周报历史与通知记录已完成 user-scoped governed read 收口；名称缓存、手工组合 ledger 同步和风险默认配置冷启动写入已从读取链消除。weekly report POST 与内部页面聚合继续按 workflow/write 或 internal-only 分流。
- Decision Rhythm quota reset 已完成 `decision.reset.quota` governed write 收口。canonical endpoint 已改为 admin-only，并返回账户与实际重置周期；正式 SDK quota list 支持按 `account_id/period` 精确读取且响应包含账户字段。governed preview 只读取目标配额，commit 只调用正式 SDK reset endpoint；legacy `reset_decision_quota` 已建立 replacement，并满足 confirmation、required idempotency、staff role、audit 与 write-evidence。
- Factor definition/config catalog、`factor.compute.top_stocks` 与 `factor.compute.stock_explanation` 已完成 governed 收口；两条纯计算路径均已证明禁止价格缓存回写且业务表计数不变。`FactorModule.get_portfolio()` 的 SDK 直连 Infrastructure 问题和 create portfolio 等 POST/composite 路径仍需独立整改，不得把本批证据扩大解释为整个 Factor family 已完成。
- Prompt template creation 已完成 `prompt.create.template` governed write 收口。Canonical mutation 保持 staff-only，模板名称在 inactive 记录中仍被保留；preview 通过正式 SDK 精确查询同名模板且不写入，commit 只调用正式创建接口，legacy `create_prompt_template` 已建立 replacement。
- Policy event creation 已完成 `policy.create.event` governed write 收口。Canonical GET 保持 authenticated，POST/PUT/DELETE 改为 staff-only；governed schema 使用 canonical 字段，preview 只读取同日事件并披露告警副作用，commit 只调用正式 Policy SDK，legacy `create_policy_event` 已建立 replacement。
- Equity valuation repair config draft creation 已完成 `equity.create.valuation_repair_config` governed write 收口。Canonical config API 保持 staff-only；preview 只调用正式 Equity SDK 的 config catalog 与 active config 读取，计算下一持久化版本和字段差异且不写入；commit 只调用正式 SDK create，创建结果保持 inactive draft，legacy `create_valuation_repair_config` 已建立 replacement。
- Equity valuation repair config activation 已完成 `equity.activate.valuation_repair_config` governed write 收口。正式 SDK 提供按 ID 精确读取目标配置；preview 同时读取目标与当前 active 配置并披露唯一 active 切换、effective time 更新和 runtime cache 清理，commit 只调用正式 activate action。Legacy activate/rollback 因 canonical 行为等价，共用同一 replacement。
- Equity valuation repair config 的 update、delete 与独立 clear-cache 路径继续冻结。Canonical API 虽存在对应 mutation，但正式 SDK 尚未提供 update/delete/clear-cache 方法，raw MCP 也没有对应工具；按现行 write-evidence gate，不得为了迁移补造 raw `@server.tool()` 或仅凭 API 存在发布 governed replacement。
- Sentiment 全局缓存清理已完成 `sentiment.clear.cache` governed write 收口。Canonical `POST /api/sentiment/cache/clear/` 已从默认 authenticated 权限收紧为 `IsAdminUser`；preview 只通过正式 Sentiment SDK `health()` 读取当前 `cache_count`，不得删除记录；确认后 commit 只调用正式 SDK `clear_cache()`。Legacy `clear_sentiment_cache` 已建立 replacement，并满足 staff role、confirmation、required idempotency、audit、write-evidence 与实际持久化删除授权测试。
- Risk Center 风险例外创建已完成 `risk_center.create.exception` governed write 收口。Canonical mutation 继续由 `CreateRiskExceptionUseCase._require_staff()` 执行真实 staff 权限校验，manifest 的 staff role 不替代服务端授权。Governed schema 要求 `field_name`、`allowed_value`、`reason` 和 timezone-aware ISO 8601 `expires_at`，并允许可选正整数 `account_id` 与 `is_active`。preview 只通过正式 Risk Center SDK `list_exceptions()` 读取目标账户范围内的现有例外，返回同字段冲突摘要且不得创建记录；确认后 commit 只调用正式 SDK `create_exception()`，不下传 `preview_only/idempotency_key`。Legacy `create_risk_exception` 已建立 replacement，并满足 confirmation、required idempotency、audit 和 focused SDK/API/registry contract。
- Risk Center 全局风险底线更新已完成 `risk_center.update.floor` governed write 收口。Canonical mutation 继续由 `UpdateRiskFloorUseCase` 执行真实 staff 权限校验并由 repository 写入 `RiskPolicyAuditModel`；manifest 的 staff role 和 MCP audit 不替代这两层服务端控制。Governed schema 要求非空 `reason`，只发布 canonical floor 的安全参数更新，不发布 `is_active`；preview 仅通过正式 Risk Center SDK `get_floor()` 读取当前值，展示字段差异、默认 floor 首次持久化影响并拒绝无变化请求。确认后 commit 只调用正式 SDK `update_floor()`，不下传 `preview_only/idempotency_key`。Legacy `update_risk_floor` 已建立 replacement，并满足 confirmation、required idempotency、audit 和 focused SDK/API/registry contract。
- Risk Center 账户级风险策略 upsert 已完成 `risk_center.update.account_policy` governed write 收口。Canonical mutation 继续由 `UpsertAccountRiskPolicyUseCase` 执行账户 owner/staff scope，普通用户可以维护本人账户但跨账户调用返回 403；repository 继续按账户唯一键执行 create/update 并分别写入业务审计。Governed schema 要求正整数 `account_id`、非空 `reason` 和至少一个策略字段。preview 只通过正式 SDK `list_account_policies()` 读取调用方可见策略，判断 create/update 并拒绝无变化；提供 `template_id` 时额外调用 `list_templates()` 验证模板存在。Canonical UseCase 也必须在真实 mutation 前重新验证持久化模板，避免 preview/commit 竞态和直接 API 绕过。确认后 commit 只调用正式 SDK `upsert_account_policy()`，不下传 `preview_only/idempotency_key`。Legacy `upsert_account_risk_policy` 已建立 replacement，并满足 confirmation、required idempotency、MCP lifecycle audit、canonical business audit 和 focused SDK/API/registry contract。
- Risk Center 日报生成已完成 `risk_center.generate.daily_report` governed write 收口。Canonical POST 继续由有效策略查询执行账户 owner/staff scope，底层按 `account_id + report_date` 唯一键 upsert，并记录 `generated_by`。Governed schema 必须显式提供 ISO 日期 `report_date`、正整数 `account_id` 与非负 `account_equity`，禁止使用会在确认期间漂移的隐式当天默认。preview 只通过正式 SDK `check_post_investment()` 生成无持久化风险评估，并以 `start_date=end_date=report_date` 查询历史判断 create/overwrite，披露现有 report、预计状态、违规数和持仓数。确认后 commit 只调用正式 SDK `generate_daily_report()`，不下传 `preview_only/idempotency_key`。Legacy `generate_risk_center_daily_report` 已建立 replacement，并满足 confirmation、required idempotency、MCP lifecycle audit、canonical generated-by attribution 和 focused SDK/API/registry contract。`generate` 必须由所有 MCP 守卫通过统一 write-like 分类器识别。
- Dashboard Auto Advisor 周报持久化已完成 `dashboard.create.auto_advisor_weekly_report` governed write 收口。Governed schema 必须显式提供非空 `account_id`、ISO 日期 `as_of` 与治理层 `idempotency_key`，禁止使用 confirmation 期间可能漂移的运行时日期默认。preview 只能通过正式 Dashboard SDK 调用 weekly report GET 和用户范围内的 history GET，判断目标日期是 create 或 overwrite，并披露 report snapshot upsert、investment diary snapshot、Dashboard notification 与 operation audit；preview 不得调用 POST、创建记录或执行交易。确认后 commit 只能调用正式 SDK `create_auto_advisor_weekly_report(account_id, as_of)`，不得下传 `preview_only/idempotency_key`。Legacy `create_auto_advisor_weekly_report` 已建立 replacement，并满足 confirmation、required idempotency、MCP lifecycle audit、focused SDK endpoint、canonical persistence-output contract、core registry create/overwrite 回归和 catalog metadata contract。
- 统一账户创建已完成 `account.create.unified_account` governed write 收口。该能力与 `trading.create.simulated_account` 不得合并：统一账户能力通过 Account canonical API 创建 authenticated owner 的 real 或 simulated 账户，模拟交易能力只处理模拟交易账户及其专用风险输入。Governed schema 必须要求 `account_name/account_type/initial_capital`，并允许 canonical `max_position_pct/stop_loss_pct/commission_rate/slippage_rate`；所有边界必须在 preview 前按 serializer 规则校验。preview 只能调用正式 Account SDK `list_accounts(account_type, active_only=False)`，按当前用户范围检查同名冲突，不得调用 POST；同一用户重复名称必须拒绝，不同用户可使用相同名称。Canonical UseCase 必须在 mutation 前再次执行 owner-scoped 名称校验，禁止全局名称查询导致跨用户阻塞或多结果异常。real 账户默认 `auto_trading_enabled=false`，simulated 账户默认 `true`，preview 必须披露该状态和 no-trade 边界。commit 只能调用正式 Account SDK `create_account()`，不得下传 `preview_only/idempotency_key`，并满足 confirmation、required idempotency、MCP lifecycle audit、legacy `create_account` replacement 与 focused API/SDK/registry/catalog regression。
- Rotation 全局资产主数据创建已完成 `rotation.create.asset` governed write 收口。Canonical `AssetClassViewSet` 保持 authenticated read，并将 create/update/partial update/delete/import-defaults 全部收紧为 staff-only mutation；普通认证用户无法修改全局资产目录。Governed create schema 固定使用 canonical `code/name/category/description/underlying_index/currency/is_active` 字段和模型边界。preview 只调用正式 Rotation SDK `get_asset(code)`，代码不存在时返回全局目录创建摘要，active 或 inactive 重码均拒绝，不读取价格、不生成信号、不导入默认资产、不执行交易。确认后 commit 只调用正式 SDK `create_asset(payload)`，不下传 `preview_only/idempotency_key`。Legacy `create_rotation_asset` 已建立 replacement，并满足 staff role、confirmation、required idempotency、MCP lifecycle audit、focused API 权限/创建合同、registry preview/commit/duplicate 回归与 catalog metadata contract。该能力不覆盖 `rotation.update.asset`、`rotation.delete.asset` 或 `rotation.import.default_assets`，三者均按独立 capability 治理。
- Rotation 全局资产主数据更新已完成 `rotation.update.asset` governed write 收口。Governed schema 要求 `asset_code`，只发布 canonical 可更新字段，不允许任意 payload、code 主键修改或 legacy `partial` 开关。preview 只调用正式 Rotation SDK `get_asset(asset_code)`，规范化请求后计算真实 changed fields；没有字段或没有有效差异时直接拒绝，不进入确认态。preview 明确返回当前/目标 active 状态以及停用或恢复影响，不读取价格、不生成信号、不导入默认资产、不执行交易。确认后 commit 固定调用 `update_asset(asset_code, updates, partial=True)`，不下传 `preview_only/idempotency_key`。Canonical PATCH 继续由 `IsAdminUser` 执行真实授权，legacy `update_rotation_asset` 已建立 replacement，并满足 staff role、confirmation、required idempotency、MCP lifecycle audit、focused PATCH/reactivation API contract、registry preview/commit/no-change 回归与 catalog metadata contract。该能力不覆盖 `rotation.delete.asset` 或 `rotation.import.default_assets`，两者均按独立 capability 治理。
- Rotation 全局资产主数据删除已完成 `rotation.delete.asset` governed write 收口。该能力严格定义为软删除，只发布 `asset_code`，不允许 `hard` 或任意 query 参数。preview 只调用正式 Rotation SDK `get_asset(asset_code)`，active 资产才可进入确认态，inactive 资产直接拒绝；摘要明确披露目标变为 inactive、数据库记录继续保留、不会物理删除、不会读取价格、不会生成信号且不会执行交易。确认后 commit 只调用正式 SDK `delete_asset(asset_code)` 默认路径，不下传 `preview_only/idempotency_key`。Canonical DELETE 继续由 `IsAdminUser` 执行真实授权，legacy `delete_rotation_asset` 已建立 replacement，并满足 staff role、confirmation、required idempotency、MCP lifecycle audit、focused soft-delete API contract、registry preview/commit/inactive 回归与 catalog metadata contract。Canonical `?hard=true` 仍是 staff-only 内部管理能力，不进入 governed Agent 契约；`rotation.import.default_assets` 继续按独立 capability 治理。
- Rotation 服务端默认资产导入已完成 `rotation.import.default_assets` governed write 收口。默认资产列表唯一来源为 `apps/rotation/infrastructure/default_assets.py`，MCP 不复制或接受调用方自定义默认清单。新增 staff-only canonical preview GET，通过 Application facade 和 repository 纯读比较服务端默认项与当前数据库，逐项分类 `created/reactivated/updated/unchanged` 并返回 changed fields；focused API contract 证明 preview 不改变记录数、active 状态或字段值，POST 实际结果与 preview 分类一致。正式 SDK 新增 `preview_default_asset_import()`，governed preview 只调用该方法并校验非负计数与 items 数组；确认后 commit 只调用 `import_default_assets()`，不下传 `preview_only/idempotency_key`。实际导入结果继续保留兼容字段 `existing`，并明确返回 `updated` 与 `unchanged`。Legacy `import_default_rotation_assets` 已建立 replacement，并满足 staff role、confirmation、required idempotency、MCP lifecycle audit、SDK endpoint、registry preview/commit 与 catalog metadata contract；该能力不读取价格、不生成信号且不执行交易。
- Account 持仓创建或加仓已完成 `account.create.position` governed write 收口。Governed schema 固定要求 `portfolio_id/asset_code/quantity/price`，并在 preview 前校验 portfolio、资产代码长度和有限正数边界；不允许 Agent 下传 source、分类、币种或地区等任意账本字段。preview 只调用正式 Account SDK `get_positions(portfolio_id, asset_code)`，按现有持仓计算 create/increase、结果数量、加权平均成本和执行价市值，不调用 POST。摘要明确披露确认后会写统一账本、同资产加仓时复用原持仓并新增 buy ledger entry，但不会发送外部券商订单。确认后 commit 只调用正式 SDK `create_position()`，不调用 raw tool且不下传 `preview_only/idempotency_key`。Canonical API 继续执行 authenticated owner scope，observer 无权创建；focused API contract 证明首次创建写入统一账本和 buy 流水，第二次同资产写入复用持仓 ID、更新数量/加权成本并追加第二条 buy 流水。Legacy `create_position` 已建立 replacement，并满足 confirmation、required idempotency、MCP lifecycle audit、SDK GET/POST endpoint、registry preview/commit 与 catalog metadata contract。
- Account 普通批量导入的 transport alias 已完成去重收口。代码审计确认 `import_positions_csv`、`import_transactions_csv`、`import_capital_flows_csv` 只使用 `csv.DictReader` 将文本转换为 rows，随后直接调用各自 JSON importer，继承同一 `mode/dry_run`、规范化、差异预览和真实 mutation 路径。因此不新增 capability：三个 CSV raw tools 分别与对应 JSON raw tool共同 replacement 到 `account.import.positions`、`account.import.transactions`、`account.import.capital_flows`。统一 capability 继续只发布结构化 rows，不发布第二套 `csv_text` schema；registry regression 固定 executor 仍为 JSON importer，catalog regression 证明 JSON/CSV legacy projection 使用相同 semantic key、replacement key 且默认不向 Terminal 启用。`import_broker_trades_csv/json` 不属于 transport-only alias：其 canonical 链会按 broker trade key 去重并同步交易、持仓和推荐匹配，因此由 `account.import.broker_trades` 按独立 write 语义治理。
- Broker 成交导入已完成 `account.import.broker_trades` governed write 收口。新能力只接收有界结构化 trades，不向 Agent 发布 CSV 文本或文件路径；正式 Account SDK 负责统一转换并调用 canonical multipart preview/import endpoint。Canonical Interface 将 owner 校验失败明确映射为 403，focused API contract 证明跨用户与有效 observer 均不能预览或提交。Preview 只解析文件、执行字段规范化并读取已有 `broker_trade_key`，对 import batch、Account transaction、legacy position、real-account mapping、统一 position/trade 和 recommendation execution link 全部保持零写入；无可导入行时不进入确认态。Preview 摘要完整披露确认后可能创建 portfolio ledger mapping、写 import batch、同步统一持仓与 legacy projection、记录 Account transaction 和 unified buy/sell trade、更新推荐采用状态并写 execution link，以及逐行错误可能导致部分成功，同时明确不会发送外部券商委托。确认后 commit 只调用正式 Account SDK `import_broker_trades()`，四个 legacy preview/import CSV/JSON tool 共同 replacement 到同一 semantic key。成交级 `broker_trade_key` 唯一约束继续负责业务去重，但不能替代 confirmation token、参数冲突检测和 lifecycle replay，因此 governed capability 仍要求 high-risk confirmation、独立 required idempotency、MCP audit、SDK endpoint、owner/observer API、registry preview/commit 和 catalog replacement 回归。
- Beta Gate 配置创建已完成 `beta_gate.create.config` governed write 收口。Canonical `/api/beta-gate/configs/` 已作为正式 route 保持 authenticated list/detail，并通过 `IsAdminUser` 限制 create mutation；rollback endpoint 同样收紧为 staff-only，但不与 create 合并。创建 schema 只发布 risk profile、Regime/Policy/组合约束和可选 config ID，并按 canonical serializer 校验枚举、置信度、政策档位、仓位边界及单仓不得高于总仓。Preview 只调用正式 Beta Gate SDK `list_configs(active_only=False)`，读取完整历史目录，拒绝 active 或 inactive 重复 ID，计算预期全局下一版本并披露同风险档位 active 配置将被停用；preview 不创建配置、不修改 active 状态、不改变既有决策且不执行交易。确认后 commit 只调用正式 SDK `create_config(payload)`，repository 在事务内分配全局递增版本并停用同风险档位旧 active 配置。Legacy `create_beta_gate_config` 已建立 replacement，并满足 staff role、confirmation、required idempotency、MCP lifecycle audit、SDK endpoint contract、focused API 权限/版本/只读目录合同、registry preview/commit/duplicate 回归与 catalog metadata contract。Rollback 由 `beta_gate.rollback.config` 独立治理。
- Beta Gate 历史配置回滚已完成 `beta_gate.rollback.config` governed write 收口。Canonical rollback route 固定以路径 `config_id` 为唯一目标，不再允许请求体 `version` 覆盖路径语义；mutation 使用 `IsAdminUser`，不存在目标返回 404，已 active 或已过期目标返回 400 且不改变任何配置。成功回滚只激活既有持久化记录、停用同风险档位当前 active 并更新目标 `effective_date`，不会创建新版本、修改既有 Gate decisions 或执行交易，其他风险档位 active 配置保持不变。Config list/detail 响应补充 `is_expired`，detail 同时返回 `effective_date/expires_at`，供正式 SDK preview 使用。Governed preview 只调用正式 Beta Gate SDK `get_config(config_id)` 与默认 active `list_configs()`，返回目标、当前 active、版本和 active 切换摘要；确认后 commit 只调用 `rollback_config(config_id)`，不下传治理参数。Legacy `rollback_beta_gate_config` 已建立 replacement，并满足 staff role、confirmation、required idempotency、MCP lifecycle audit、现有 SDK endpoint contract、focused API 权限/精确目标/过期拒绝/同档位切换合同、registry preview/commit/expired 回归与 catalog metadata contract。
- Beta Gate 持久化配置版本对比已完成 `beta_gate.compute.config_comparison` governed pure compute 收口。代码审计确认 canonical `BetaGateConfigQueryService.compare_versions()` 只按 config ID 或数值版本读取两条 `GateConfigModel`，把 JSON constraints 解析为对象并在内存中比较固定字段，不保存配置、不切换 active、不写 Gate decisions、不发布事件。Canonical `/api/beta-gate/version/compare/` 已显式使用 `IsAuthenticated`。正式 Beta Gate SDK 原先错误地 POST 到只实现 GET 的 endpoint，现改为 GET，并将 legacy `from/to`、`version_a/version_b` 兼容归一化为 canonical `version1/version2` query；focused SDK contract 固定真实 method/path/params。Governed schema 必须同时提供两个非空且有界的配置标识，只返回 `config1/config2/differences`，不发布 canonical 无参数时的 recent-version 目录分支，避免与 `beta_gate.read.config_catalog` 重叠。Controlled fallback 只调用正式 SDK `version_compare()`；legacy `compare_beta_gate_version` 已建立 replacement，并满足 authenticated API、配置表零变化、SDK GET、core-only capability-call、catalog replacement 与 read-evidence regression。批量评估由 `beta_gate.compute.batch_evaluation` 独立治理。
- Beta Gate 批量资产评估已完成 `beta_gate.compute.batch_evaluation` governed pure compute 收口。Canonical `/api/beta-gate/test/` 已显式要求认证，并使用严格 `BetaGateTestSerializer`：只接受有界、去重的 `asset_codes`，非空 `asset_class`，四象限 `current_regime`，有限且位于 `[0,1]` 的 `regime_confidence`，`P0-P3` 对应的 `policy_level` 和 canonical 小写 `risk_profile`；未知字段直接返回 400。旧接口虽然声明 `current_portfolio_value`，实际从未传入批量 UseCase，且当前领域评估器缺少新仓位与总资产两个必要输入，因此 governed schema 不发布该伪参数。配置选择器改为 `get_by_risk_profile()`，不再读取第一条 active 配置；缺少持久化配置时使用请求风险档位对应的内存默认配置，并固定 `default-<risk_profile>` 标识，不写配置表。响应固定返回 `config/query/results/summary`，便于审计实际选择的配置和规范化输入。Focused API contract 证明请求 aggressive 时不会误用排序靠前的 conservative 配置，且调用前后 `GateConfigModel`、`GateDecisionModel` 和 `StoredEventModel` 数量完全不变；UseCase 未注入 event bus，也未调用 decision repository、Celery 或交易链。Controlled fallback 只规范化输入并调用正式 SDK `test_gate(payload)`；legacy `test_beta_gate` 已建立 replacement，并满足 authenticated API、SDK POST endpoint、core-only capability-call、catalog replacement、manifest schema、read-evidence 和 dedup regression。
- 通用领域事件发布已完成 `events.publish.event` governed workflow/write 收口。Canonical publish API 已收紧为 staff-only 并使用严格 serializer；Application 与 Celery 链都固定为持久化成功后才通知 event bus，重复 `event_id` 或 append 失败不会再次执行订阅者。Governed schema 要求显式 event type、对象 payload、带时区 occurred_at 和 required idempotency；preview 只做本地规范化并披露持久化、同步通知及 subscriber-defined 跨模块写风险，不调用 SDK、数据库或 event bus。确认后 commit 只调用正式 Events SDK `publish_event()`，并把 `idempotency_key` 作为 canonical `event_id`，同时依赖 dispatcher replay 与数据库唯一约束抑制重复副作用。Legacy `publish_event` 已建立 replacement，并通过 focused API 权限/未知字段/持久化失败/重复副作用合同、SDK endpoint、registry preview/commit/replay、catalog metadata 和全部 write guards。
- `replay_events` 已完成下一候选契约审计并继续冻结。虽然 raw MCP、Events SDK 和 `/api/events/replay/` route 均存在，但 Interface 固定传入 `target_handler=None`，底层 replay handler 随后调用空对象的 `can_handle()` 并逐事件吞掉异常，最终可能返回成功但实际重放数为零。该路径不具备真实 subscriber/handler 目标、权限白名单、preview、副作用合同或 focused invocation evidence，不能发布 governed workflow；解冻前必须先补 canonical handler identity、staff 权限、目标白名单、confirmation、required idempotency、audit 和部分失败语义。

- `data_center.read.capital_flows` 已完成 governed persisted read 收口。Canonical GET 使用 authenticated 严格 serializer，只接受 `asset_code/start/end/limit`，拒绝未知参数、非法日期、反向区间和 legacy `period`；Repository 支持 alias 解析、日期过滤、倒序和数据库层 limit。Focused API contract 证明返回稳定 `asset_code/query/total/data` envelope，且查询前后 `CapitalFlowFactModel` 记录与 `fetched_at` 不变。正式 SDK、legacy compatibility tool 和 controlled fallback 已统一同一参数合同，fallback 只调用正式 Data Center SDK；legacy `data_center_get_capital_flows` 已建立 replacement，并通过 core-only capability-call、catalog、manifest 与 read-evidence 回归。

`data_center.start.sync_job` 的已落地证据检查入口固定如下：

1. raw tool：`sdk/agomtradepro_mcp/tools/data_center_tools.py`
2. SDK：`sdk/agomtradepro/modules/data_center.py`
3. canonical API：`apps/data_center/interface/api_views.py`、`apps/data_center/interface/api_urls.py`
4. SDK / MCP 现有回归：`sdk/tests/test_mcp/test_data_center_tools.py`、`sdk/tests/test_sdk/test_data_center_module.py`
5. 当前 `sync_macro`、`sync_capital_flows`、`sync_news` 已完成受控迁移。
6. `sync_prices`、`sync_quotes` 在补齐 raw MCP tool 证据之前，不得写入下一轮默认续做入口。

后续执行时不得偏离以下口径：

1. 不得把 `terminal agent` 从 MCP 主链上拆掉；当前真实链路仍然是 `terminal agent -> MCPServerStdio -> agomtradepro_mcp.server`。
2. 不得为了迁移方便再新增 raw `@server.tool()` 暴露面。
3. 不得把普通站内 Web/TUI/API 调用重新倒流到 MCP；MCP 仍只服务外部 Agent 和 `terminal agent` 的统一调度面。
4. 若候选能力的 canonical API / SDK 契约不闭环，必须先做契约核验，不得硬写 governed replacement。

下一批 read capability 的固定实施步骤：

1. 在 `sdk/agomtradepro_mcp/registry/modules/<owner>_read_capabilities.py` 新增 manifest，并声明 `legacy_tool_names`、`executor_ref`、`owner_app`、`input_schema`、`output_schema`；禁止继续扩大 `basic_read_capabilities.py`。
2. 在 `sdk/agomtradepro_mcp/registry/read_handlers/<owner>.py` 增加 controlled fallback，由 `server.py` 仅装配 owner registry，保证 `core-only` 模式仍经统一 dispatcher，禁止把业务 fallback 写回 server。
3. 在 `sdk/tests/test_mcp/test_<owner>_*_registry.py` 增加 registry 可见性与 `agom_capability_call` 回归，禁止继续扩大总 registry 测试。
4. 在 `tests/unit/test_ai_capability/test_mcp_<owner>_*_catalog.py` 校验 catalog metadata、legacy replacement / target sync 与 discovery 子集。
5. 在 `sdk/tests/test_sdk/test_<owner>_*_module.py` 增加 SDK endpoint contract，确保 SDK path 与 canonical API 保持一致，禁止继续扩大总 endpoint 参数化文件。
6. 如该能力已有 API 契约测试，则补充或运行对应 focused regression，并回写结果到本文档。
7. 执行以下最小验证集并回写结果到本文档：
   - `python -m pytest sdk/tests/test_sdk/test_extended_module_endpoints.py -q`
   - `python -m pytest sdk/tests/test_mcp/test_core_registry.py tests/unit/test_ai_capability/test_api_and_use_cases.py -q`
   - 根据当前目标能力运行对应 focused API 契约测试；若候选路径缺少 success contract，必须先补 focused contract，再进入 governed replacement。当前默认下一条固定为“先完成 raw-tool gap 审计并锁定新的证据链完整候选”
   - `python -m pytest sdk/tests/test_mcp/test_tool_registration.py -q`
   - `python scripts/check_mcp_manifest_schema.py`
   - `python scripts/check_mcp_read_evidence.py`
   - `python scripts/check_mcp_catalog_dedup.py`
8. 每迁移完一个批次，只有实际数量变化时才更新 `governance/governance_baseline.json`；不得在本文复制一份 live 数字。
9. 如果目标 raw tool 对应的 API/SDK 契约存在疑点，必须先补“契约核验”子任务：
   - 核对 SDK path、HTTP method、ViewSet action、serializer 和现有契约测试是否一致
   - 契约未闭环前，不得新增 governed replacement manifest
   - 不允许为了推进迁移而把不存在或不稳定的 raw path 写入标准文档

下一批 write capability 的固定实施步骤：

1. 在 `sdk/agomtradepro_mcp/registry/modules/<owner>_write_capabilities.py` 新增 manifest，并声明 `idempotency=required`、`requires_confirmation=true`、`audit_tags`、`replacement_for`；禁止继续扩大 `write_capabilities.py`。
2. 在 `sdk/agomtradepro_mcp/registry/internal_handlers/<owner>.py` 增加 preview/commit handler，由 server 只装配 owner registry，禁止把业务 handler 写回 `server.py`。
3. 在 `sdk/tests/test_mcp/test_<owner>_*_registry.py` 增加 preview / confirmation / replay / conflict 回归。
4. 在 `tests/unit/test_ai_capability/test_mcp_<owner>_*_catalog.py` 校验 catalog replacement、governed metadata、execution target 同步。
5. 执行以下最小验证集并回写结果到本文档：
   - `python -m pytest sdk/tests/test_mcp/test_core_registry.py tests/unit/test_ai_capability/test_api_and_use_cases.py -q`
   - `python scripts/check_mcp_manifest_schema.py`
   - `python scripts/check_mcp_write_confirmation.py`
   - `python scripts/check_mcp_write_evidence.py`
   - `python scripts/check_mcp_write_preview.py`
   - `python scripts/check_mcp_write_audit.py`
   - `python scripts/check_mcp_catalog_dedup.py`
6. 每迁移完一个批次，只有实际数量变化时才更新 `governance/governance_baseline.json`；不得在本文复制一份 live 数字。
7. 如果目标 raw tool 对应的 API/SDK 契约存在疑点，必须先补“契约核验”子任务：
   - 核对 SDK path、HTTP method、ViewSet action、serializer 和现有契约测试是否一致
   - 契约未闭环前，不得新增 governed replacement manifest
   - 不允许为了推进迁移而把不存在或不稳定的 raw path 写入标准文档
8. `Batch G`：
   - 把已落地的 governed write 审计模板扩展到更多 write domains
   - 保持 preview staged、confirmation cancelled、confirmation completed、idempotent replay、idempotency conflict 五类事件口径一致
   - 形成后续写能力批量迁移的统一审计模板

每个批次的最低验收口径：

1. `Batch C`：第一批高频只读能力能通过 `agom_capability_call` 跑通。
2. `Batch D`：PR/CI 对 raw tool 回归、replacement 缺失、MCP dedup 破坏、无确认写 manifest 形成硬阻断。
3. `Batch E`：同一业务语义的 API / MCP / terminal capability 冲突可被显式发现与治理。
4. `Batch F`：高风险写能力默认先 preview，再确认执行，并具备幂等与审计链路。
5. `Batch G`：写能力的 preview、确认、重放、冲突四类结果均能被统一审计检索到。

---

## 8. 验收命令建议

基础检查：

```bash
python manage.py check
pytest tests/unit/test_ai_capability*.py -q
pytest sdk/tests/test_mcp -q
```

默认 `legacy-off` 收口后的 focused regression：

```bash
python -m pytest sdk/tests/test_mcp/test_core_registry.py -q -s
python -m pytest sdk/tests/test_mcp/test_tool_registration.py -q -s
python -m pytest tests/unit/test_terminal_agent_service.py -q -s
python -m pytest tests/unit/test_ai_capability/test_api_and_use_cases.py -q -s
```

新增专项检查建议：

```bash
python scripts/check_mcp_tool_budget.py
python scripts/check_mcp_manifest_schema.py
python scripts/check_mcp_catalog_dedup.py
python scripts/check_mcp_no_raw_tools.py
python scripts/check_mcp_write_confirmation.py
python scripts/check_mcp_write_preview.py
```

人工验收：

```bash
npx @modelcontextprotocol/inspector python -m agomtradepro_mcp
```

验收场景：

1. 调用 `agom_bootstrap` 查看身份和规则。
2. 搜索 “当前市场环境”。
3. 查看 `system.read.regime.current` schema。
4. 调用 `system.read.regime.current`。
5. 调用一个写能力并确认只返回 preview。
6. 使用确认 token 继续执行。
7. 在审计中按 `request_id` 查到调用记录。

---

## 9. 风险与处理

| 风险 | 影响 | 处理 |
| --- | --- | --- |
| 外部用户仍依赖旧工具名 | 迁移破坏兼容 | legacy 开关 + replacement 映射 + 两个版本过渡 |
| 统一 dispatcher 初期能力不足 | 新入口覆盖不全 | 先迁移高频只读和关键写能力，旧工具兼容 |
| Catalog 分流影响站内 chat | 站内体验变化 | 先只改变候选过滤，不改最终回答协议 |
| 写操作确认流程增加复杂度 | Agent 调用多一步 | 统一 `agom_confirmation_resume`，返回清晰 next_actions |
| manifest 维护成本上升 | 开发负担增加 | 用生成脚本和 schema 测试降低人工成本 |
| legacy 兼容路径长期无人验证 | 兼容回退失效 | 保留显式 `legacy-on` 回归测试，不依赖默认 surface |

---

## 10. 最终完成定义

整改完成必须同时满足：

1. 默认 MCP 顶层工具数不超过 10。
2. legacy 散装工具不再默认平铺给 Agent。
3. 外部 Agent 仍可通过统一能力调用覆盖已批准系统功能。
4. 普通站内 AI 默认不经 MCP 调系统能力，`terminal agent` 则通过统一 core tools 调 MCP capabilities。
5. MCP 不再作为 API endpoint 的一比一替代层。
6. 所有能力有 manifest、schema、风险、权限、审计。
7. 所有写能力有 dry-run / confirmation / idempotency 策略。
8. CI 能阻止新增散装 MCP tool。
9. 文档、测试、启动欢迎信息均只推荐统一入口。
10. `terminal agent` 继续可用，但只通过收口后的 core tools / capability tools 调系统能力。
11. MCP SDK 生产 Python 已纳入机器 large-file 门禁，`server.py` 只承担 composition root，manifest、handler 与 focused tests 已按 owner 拆分，历史巨型聚合文件不再存在或不再承载实现。
