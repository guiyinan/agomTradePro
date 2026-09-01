# 数据中台唯一真源与数据可靠性架构重构计划（2026-08-02）

> 状态：实施中（M0-M4 控制面、D0/D1/D4-D7 本地关键消费者和 D2/D3/D8-D9 的本地 Publication-only 端口已收口；D4-D9 published Query Port 与 REST 已增加同一 Publication 的 member-bound fact_pk 过滤；Dataset Catalog/owner registry 已持久化并可幂等初始化，Provider×dataset health 和 A-share composite publication gate 已接入；本地 PostgreSQL 空库迁移图已验证；生产观察窗口、PostgreSQL 生产预算/M9-M10 尚未完成）
> 级别：架构级 / 数据级 / 生产级重构  
> 适用版本：0.8.0 之后的下一条独立主线  
> 目标：所有外部事实数据及所有业务计算输入统一经过 Data Center；系统只有一个可发布的数据真源、一套可靠性语义和一条可审计的数据链路，并能在生产默认 90 GiB、运行时可调整的容量策略下持续运行  
> 执行原则：先阻断错误数据，再建立契约；先扩展后切换；先影子对账再退役旧链；禁止长期双写

## 2026-08-15 旧计划收口映射

`admin-settings` 已归档；Config Center 的生产 profile、真实数据观察、回填和 M9/M10 门禁仍属于本工作流的 `DATA-01/02/03`。归档仅移除 Classic 设置页的重复实施叙事，不代表配置生产切换或观察窗口通过。

## 实施记录（2026-08-02，第一批）

本批次只处理“契约、边界和高风险语义”，不进行 VPS 部署、生产切读、旧表删除或破坏性迁移。

已落地：

- `apps/data_center/domain/contracts.py` 增加 `DataEnvelope`、`SourceEvidence`、`QualityAssessment`、`FetchResult`、`SyncOutcome`、`PublicationDecision`、`DatasetContract`、`ProviderBinding` 和 `PublicationPolicy`，并对缺失值、零产出、时间顺序、证据和冲突执行 fail-closed 校验。
- `governance/dataset_contracts.json`、`governance/provider_bindings.json`、`governance/publication_policies.json` 覆盖 D0-D9；`scripts/check_data_center_catalog_contracts.py` 在缺任何一项时失败。
- `apps/data_center/application/public.py` 建立宏观、资产、行情、报价、财务、估值、Provider 配置和显示名的 Application Public Port；Regime、Pulse、Filter、Factor、Setup Wizard、Audit、Dashboard 等生产读取已切到该端口。
- Provider SDK transport 收口至 `apps/data_center/infrastructure`；shared Tushare/AKShare bridge 变为迁移 tombstone，Data Center 外部 SDK 越界清单为 0。
- Provider Registry 接受 `FetchResult` 和 dataset-specific validator；stale、blocked、空结果会继续 failover。
- Alpha、equity 基本面/估值、财务/估值 gateway 不再把缺失事实补成 `0.0`；筛选和估值分析对关键缺失数据阻断或跳过。
- Data Center 同步用例在 `stored=0` 时发布 `noop`，并修正健康状态/审计结果；补充 deterministic architecture inventory 和 ratchet guard。
- Agent Runtime 宏观快照、Regime/Pulse 等 current-data 入口保留源观测时间，未用请求时间包装历史事实。

本批机器证据：

- `python scripts/data_center_architecture_inventory.py`：`provider_imports_outside_data_center=0`、`external_http_imports_for_review=7`、`cross_app_orm_imports=61`、`legacy_fact_references=178`、`current_surface_references=2795`、`data_write_task_decorators=50`、`runtime_parameter_references=49`。
- `python scripts/check_data_center_catalog_contracts.py`：`validated=10 datasets`。
- `python scripts/verify_architecture.py --include-audit --format text`：修复 naive datetime 后应保持 boundary/audit 0 violation；`check_current_data_contracts.py` 通过 25 个 surface，`check_celery_task_contracts.py` 通过 13 个 task。

已验证的最小回归包：

- Data Center contracts/registry/architecture/inventory/catalog guard：通过。
- Provider adapter/gateway：76 passed；Alpha + equity context/provider：47 passed；Pulse + Regime：79 + 59 passed；Filter：22 passed；Factor：83 passed；equity screener/analyzer/edge：35 passed；Audit high-frequency validator edge：4 passed；Setup Wizard boundary：2 passed。

未完成及明确风险：

- `apps/macro/infrastructure/data_center_fact_repository.py` 已完成迁移为仅依赖 Data Center Application Public Port 的兼容适配器；不再导入 Data Center ORM，旧 ratchet 例外已删除。其 `MacroIndicator` 转换和历史 CRUD 形状仍因 macro 应用/维护脚本兼容性保留，属于待退役的适配层而非生产 ORM 真源。
- `apps/data_center/apps.py` 的 PIT 回调已迁入 `apps.data_center.application.pit_provider`；其他非 PIT 的跨领域 registry 仍按 owner 保留在 `core.integration`，不属于 Data Center Provider 入口。
- Raw Landing/Schema Fingerprint/Quarantine、SyncRun/Batch/Checkpoint、CanonicalPublication 持久化、Config Center Definition/Profile/Revision/Snapshot 模型、StorageBudget/Retention/Archive/容量故障注入尚未实施。
- D0-D9 的生产数据画像、legacy/canonical shadow reconciliation、PostgreSQL 全链路、VPS/备份/恢复、M9 旧表清理和 M10 生产证据均未验证；因此本计划不能标记为完成，也不触发部署。

## 实施记录（2026-08-02，第二批）

本批次继续只做本地架构与可验证代码，不部署 VPS、不切生产读、不删除旧表。

已落地：

- Data Center 新增 `SyncRunModel`、`SyncBatchModel`、`SyncCheckpointModel`、`QuarantineRecordModel`、`CanonicalPublicationModel`、`PublicationMemberModel`、`CoverageSnapshotModel`，并提供 Domain 不变量、幂等仓储、发布 supersede 和 current/as_of 查询端口；迁移为 `0050_canonicalpublicationmodel_coveragesnapshotmodel_and_more.py`。
- 新增 Raw Landing/Schema Fingerprint：红脱敏校验、payload/schema hash、保留期、解析版本、运行关联；Raw Audit 增加请求参数 hash、响应 hash、schema fingerprint、脱敏和保留字段；迁移为 `0051_rawauditmodel_ingested_run_id_and_more.py`。
- D0-D9 类型化事实表补充 `contract_version`、`schema_version`、`source_record_id`、`raw_payload_hash`、`quality_status`、`revision_number`、`ingested_run_id` 等统一证据列；迁移为 `0052_capitalflowfactmodel_contract_version_and_more.py`。
- `apps/macro/infrastructure/data_center_fact_repository.py` 已改为只依赖 `apps.data_center.application.public` 的兼容 facade；ORM 读写投影下沉到 Data Center infrastructure，宏观新增写入不再经过 macro 旧表。
- PIT provider registry 从 `core.integration` 收回 `apps.data_center.application.pit_provider`，backtest/research/decision-rhythm 只依赖 Data Center PIT Application Port；架构扫描保持 boundary/audit 0 violation。
- Config Center 新增 RuntimeConfigDefinition/Profile/Value/Revision/Snapshot、StorageBudgetPolicy、StorageBudgetQueryPort、StoragePressureGuard、初始化命令和 runtime desired-state reconcile；无 active policy 时 readiness/写入侧 fail closed，容量使用实际磁盘与配置容量的较小值。
- Data Center 新增 RetentionPolicy、StorageHold、ArchiveManifest 的 Domain/Model/Repository；归档必须有 checksum/verified_at，保留清理遇到 active hold 时阻断。
- `sync_equity_financial` 和 equity fundamentals 写入入口改为 Data Center FinancialFact/ValuationFact canonical repository；旧 equity 事实表仅保留迁移期只读兼容。
- 新增 `governance/storage_budget_contracts.json`、`governance/runtime_desired_state.json` 及对应 deterministic guards；`production-90g` 只作为显式初始化 profile，不作为运行逻辑 fallback。

第二批机器证据：

- `pytest tests/component/infrastructure/test_repositories.py -q`：47 passed；`pytest tests/component/macro/test_data_center_fact_crud_contracts.py -q`：2 passed。
- `pytest tests/unit/data_center/test_control_plane.py -q`：5 passed；控制面迁移在 SQLite 测试库创建并通过幂等/current 阻断断言。
- `pytest tests/unit/data_center/test_runtime_reconcile.py tests/unit/data_center/test_raw_landing.py tests/unit/config_center/test_runtime_config_control_plane.py -q`：8 passed；随后完整 `test_runtime_config_control_plane.py`：6 passed，含 Config Center/StorageBudget 数据库 round-trip。
- TUI Config Center 运行配置治理 P0 panel 已接入；`pytest tests/unit/test_tui_workbench.py -q -k 'config_center_screen or config_center_exposes_alpha_universe_actions or config_center_admin'`：4 passed。
- `pytest tests/unit/data_center/test_retention_control_plane.py -q`：2 passed，覆盖 archive verified 与 active hold 阻断。
- `python manage.py check`、`python manage.py makemigrations --check --dry-run`、`python scripts/check_storage_budget_contract.py`、`python scripts/check_runtime_desired_state.py` 均通过。
- `python scripts/check_mypy_regression.py ...`：新增/修改生产文件无 mypy regression；`python scripts/verify_architecture.py --include-audit --format text`：boundary/audit 0 violation。
- 第二批复采 inventory：`provider_imports_outside_data_center=0`、`cross_app_orm_imports=60`、`legacy_fact_references=173`、`current_surface_references=2815`、`data_write_task_decorators=50`、`runtime_parameter_references=49`；`check_current_data_contracts.py` 25 surfaces、`check_celery_task_contracts.py` 13 tasks 均通过。

仍未完成：

- 全部 current/latest 入口尚未强制只读 Publication；目前已提供明确的 `get_published_*` gate，但既有历史/维护端口仍保持兼容。
- D0-D9 生产数据画像、shadow reconciliation、PostgreSQL 约束/P95、Retention/Hold/Archive 实际任务、非默认容量 profile 故障注入、CI nodeid 真执行、VPS/备份/恢复和旧表删除均未完成；不触发部署。

## 实施记录（2026-08-02，第三批）

本批次仍只做本地代码、SDK/MCP 入口和可回归的控制面，不部署 VPS、不 push、不切生产读、不删除旧表。

已落地：

- Runtime Config Application 增加 side-effect-free impact preview、同环境 active profile 自动 supersede、版本递增 rollback 端口，并把 critical/bootstrap 缺失、profile_id 错配和重复 definition key 统一 fail closed。
- Retention 新增有界 `cleanup_expired_raw_payloads_task`：默认 dry-run，只有 active RetentionPolicy、StoragePressureGuard 非 blocked、verified archive 和无 active hold 才允许执行删除；任务已登记 Celery contract 并覆盖 invalid/blocked/partial/success。
- RawAudit 与 RawPayload 均拒绝未脱敏写入；Raw Landing 提供 oldest-first bounded retention candidate/delete port；基金 NAV 保留明确标注的 D6 迁移期 shadow mirror，canonical Data Center 读取优先，旧表只作兼容回退。
- Data Center API 增加显式 `mode=published` Publication gate（macro、price、quote、fund NAV、financial、valuation）；SDK 转发 `mode/publication_key`，MCP equity research snapshot 对核心分区默认请求 published，缺少 publication 时返回空证据并 `must_not_use_for_decision=true`，不再展示非空旧值。
- TUI operator config-center governance summary 增加 typed Runtime Profile/StorageBudgetPolicy P0 阻断提示；治理摘要不读取或展示 secret value。
- `governance/current_data_contracts.json` 新增 publication-gated API/SDK/MCP contract，防止入口回退到未发布事实。

第三批机器证据：

- `pytest tests/unit/config_center/test_runtime_config_control_plane.py tests/unit/data_center/test_retention_control_plane.py tests/unit/data_center/test_retention_tasks.py tests/unit/fund/test_t4b_use_case_and_adapter_contracts.py -q`：24 passed。
- `pytest sdk/tests/test_sdk/test_data_center_module.py sdk/tests/test_mcp/test_equity_research_snapshot_registry.py -q`：33 passed；`pytest tests/api/test_data_center_route_cleanup.py -q -k 'published_price_history_blocks_without_publication'`：1 passed。
- `pytest tests/unit/data_center/test_raw_landing.py tests/component/infrastructure/test_repositories.py -q`：49 passed；TUI Config Center targeted：4 passed；Alpha Qlib boundary/edge：42 passed；Terminal agent：13 passed；SDK client：22 passed；internal SSL：6 passed。
- `python scripts/check_celery_task_contracts.py`：14 tasks；`python scripts/check_current_data_contracts.py`：26 surfaces；`python scripts/data_center_architecture_inventory.py --write`：`provider_imports_outside_data_center=0`、`cross_app_orm_imports=60`、`legacy_fact_references=171`、`current_surface_references=2824`、`data_write_task_decorators=51`、`runtime_parameter_references=49`；storage/desired-state guards 均通过。
- `python scripts/verify_architecture.py --include-audit --format text`：boundary/audit 0 violation；目标生产文件 ruff 与 mypy regression 0。

仍未完成：

- D0-D9 全部消费者还没有强制切换到 Publication-only 读；目前已把决策型 API/SDK/MCP 研究入口设为显式 published 模式，历史/维护端口和部分业务聚合仍保留迁移兼容面。
- Retention 目前是有界 raw payload 任务，事实表分区/rollup、Raw/Quarantine 全量归档、真实 beat schedule 和恢复演练尚未完成。
- 完整 `pytest tests/unit/test_tui_workbench.py -q` 在 SQLite 测试库 migration/setup 阶段超时；配置中心相关定向用例已通过，需在 CI/干净测试库中完成全量 nodeid 证据。
- PostgreSQL 真实 migration/P95/锁预算、生产数据画像、shadow reconciliation、非默认容量 profile 故障注入、VPS/备份/恢复、CI nodeid 真实执行、旧表删除均未完成；不触发部署。

## 实施记录（2026-08-02，第四批）

本批次继续只做本地消费者收口和阻断性护栏，不部署、不 push、不删除旧表。

已落地：

- 业务 App 不再直接 import `apps.data_center.infrastructure`；Alpha ETF、Realtime、Equity market/stock-info、Fund 入口统一经 Data Center Application Public Port，新增 architecture rule 防止回归。
- D4/D5 Equity 读取改为只走 canonical FinancialFact/ValuationFact/PriceBar；旧 `FinancialDataModel`、`ValuationModel` 已退出 Admin，仅保留模型、历史迁移和迁移期测试用途；`StockDailyModel` 仍是冻结只读 Admin。legacy-fact access guard 阻断业务新增读写。
- D6 Fund NAV 读取和写入移除旧 `FundNetValueModel` fallback/shadow mirror；旧 NAV Admin 设为只读，净值性能测试改用 canonical facts。
- Provider health snapshot 补齐 `dataset_key`，Capability 与 Dataset Contract 有稳定映射；Retention 增加每日 dry-run preview beat schedule，仍需 active policy/archive/hold/StoragePressure gate 才可执行删除。
- Sector membership 增加 canonical `list_current` port，Sector repository 优先使用 Data Center membership；Sentiment news repository provider 改走 Public Port。
- `governance/data_center_legacy_access_contracts.json`、`scripts/check_data_center_legacy_fact_access.py` 和 CI guard 已接入，防止 D1/D4/D5/D6 旧事实路径重新增长。

第四批机器证据：

- `python scripts/check_data_center_legacy_fact_access.py`：通过；`python scripts/verify_architecture.py --include-audit --format text`：7 条 boundary、20 条 audit 均 0 violation。
- `pytest tests/component/test_equity_repository_daily.py -q --no-migrations --timeout=30`：4 passed；`pytest apps/equity/tests/test_stock_context_repository.py -q --no-migrations --timeout=30`：9 passed。
- `pytest tests/integration/test_equity_asset_analysis.py -q --no-migrations --timeout=30`：22 passed；`pytest tests/integration/test_equity_integration.py -q --no-migrations --timeout=30`：7 passed。
- `pytest tests/component/test_fund_repository_data_center.py tests/unit/fund/test_fund_adapter_contracts.py tests/unit/fund/test_t4b_use_case_and_adapter_contracts.py -q --no-migrations --timeout=30`：28 passed；`pytest tests/integration/test_fund_integration.py -q --no-migrations --timeout=30`：10 passed。
- `pytest tests/unit/equity/test_t5_infrastructure_adapter_contracts.py -q --no-migrations --timeout=30`：15 passed；provider health/domain：13 passed；legacy guard：1 passed。
- 变更生产文件 ruff/mypy regression 通过；Django check 通过。

仍未完成：

- D7/D8/D9 的所有业务聚合尚未达到旧模型零读写；Sector 仍保留维护投影 fallback，News/CapitalFlow 全入口 Publication-only 仍需继续收口。
- 完整 D0-D9 shadow reconciliation、覆盖/查询 P95、PostgreSQL migration/锁预算、非默认容量故障注入、CI nodeid 全量执行、VPS/备份/恢复和 M9 旧表删除仍未完成。

## 实施记录（2026-08-02，第五批）

本批次继续只做本地 canonical cutover、业务消费者收口和 fail-closed 护栏；不部署、不 push、不删除旧表。

已落地：

- D0 AssetMaster 成为 Equity/Factor/Account 冷启动、股票名称解析、股票 universe 的唯一生产读写入口；旧 `StockInfoModel` 仅保留模型、历史迁移、冻结 Admin 和迁移期测试用途。Asset-master backfill 不再从业务旧表读取，而是通过 Data Center Public Port 刷新 canonical 记录。
- Factor integration/repository 的股票名称、行业和 universe 查询改走 `get_asset_repository_port()`；`bootstrap_cold_start` 与 `bootstrap_mcp_cold_start` 的 readiness/seed 改为 canonical AssetMaster upsert/list。
- D7 Sector Membership 的 repository、Tushare/AKShare constituents adapter 改为只读写 Data Center `SectorMembershipFact`；旧 `SectorConstituentModel` 仅保留只读 Admin、模型/迁移和测试，旧 fallback 已删除。
- Data Center Sector Constituents API 增加 `mode=published` gate；缺少当前 Publication 时返回空数据、`must_not_use_for_decision=true` 与稳定阻断原因。D8/D9 API 已保留同一显式 gate 语义。
- legacy-access guard 扩大至 `StockInfoModel`、`SectorConstituentModel`，并接入 CI，禁止新增业务读写绕回旧投影。

第五批机器证据：

- `python scripts/data_center_architecture_inventory.py --write`：`provider_imports_outside_data_center=0`、`cross_app_orm_imports=56`、`legacy_fact_references=148`、`current_surface_references=2824`、`data_write_task_decorators=51`、`runtime_parameter_references=49`。
- `python scripts/check_data_center_legacy_fact_access.py`：通过；`python scripts/verify_architecture.py --include-audit --format text`：7 条 boundary、20 条 audit 均 0 violation。
- `pytest apps/equity/tests/test_stock_context_repository.py -q --no-migrations --timeout=30`：11 passed；`pytest tests/component/test_asset_name_resolver.py -q --no-migrations --timeout=30`：11 passed；Factor infrastructure/application：16 passed；Account initialization：13 passed。
- `pytest tests/unit/sector -q --no-migrations --timeout=30`：32 passed；`pytest tests/api/test_data_center_route_cleanup.py -q --no-migrations --timeout=30`：31 passed；Data Center backfill/source registry：28 passed。
- `pytest tests/unit/alpha -q --no-migrations --timeout=30`：119 passed；其中 Simple Alpha 的 canonical-fact/quote fallback contract 已改为 Public Port mock，覆盖 missing fail-closed 语义。

仍未完成及风险：

- D2/D3/D8/D9 的所有内部业务聚合尚未证明均为 Publication-only；历史/维护 Query Port 仍保留，Publication 观察窗口和生产 publication 记录未在本地 SQLite 以外验证。
- 完整 D0-D9 shadow reconciliation、覆盖与查询 P95、PostgreSQL migration/锁预算、非默认容量 profile 故障注入、CI nodeid 全量执行、VPS/备份/恢复和 M9 旧表删除仍未完成；本批不触发部署。

## 实施记录（2026-08-02，第六批）

本批次继续只做本地可验证的消费者切读、旧宏观链路清理和治理护栏；不部署 VPS、不 push、不切生产、不删除旧表。

已落地：

- D3 旧 `MacroIndicator` ORM 不再被生产命令或接口 serializer 读取；`migrate_usd_data` 改为通过 Data Center Public Port 读取/批量写回 canonical `MacroFact`，保留备份确认、dry-run、手动汇率和全批次 fail-closed 语义。legacy-access guard 改为只追踪真实 legacy-model import，避免把同名 Domain 实体误报为 ORM 访问。
- D2/D3 当前业务消费者收口：Alpha quote momentum/health、Pulse price/quote/macro 输入、Regime latest/current macro 读取统一使用 `get_published_*` 端口；显式日期/as_of 的历史查询继续使用历史端口，避免把回放语义改成 current。
- D7/D8/D9 新增 sector membership、market news、capital-flow 的 Publication-only Query Port；缺少 active Publication 时先返回空 rows、`must_not_use_for_decision=true` 和 `canonical_publication_missing`，不会先查询事实表。Sector 当前映射和 Sentiment 新闻聚合均 fail closed。
- M3 增加纯 Domain shadow reconciliation 分类（same、expected_difference、data_missing、semantic_conflict、code_defect）及 Query Budget（查询数/P95）契约；新增 `data_center_query_budgets` deterministic guard 和 3 个 D7-D9 预算登记。
- runtime config inventory 的 49 条环境参数引用增加显式 `environment_bootstrap` 分类；未分类引用由 guard 阻断，避免将 env/settings 隐形 fallback 冒充 Config Center 真源。
- CI fast feedback 增加 legacy/query-budget/runtime-config guards；nightly PostgreSQL job 增加 publication/query-budget/runtime-profile nodeid 执行步骤。仅提交 CI 规则，不代表本地已拥有 PostgreSQL 或生产数据证据。

第六批机器证据：

- `python scripts/data_center_architecture_inventory.py --write`：`provider_imports_outside_data_center=0`、`cross_app_orm_imports=56`、`legacy_fact_references=144`、`current_surface_references=2834`、`data_write_task_decorators=51`、`runtime_parameter_references=49`。
- `python scripts/check_data_center_legacy_fact_access.py`、`python scripts/check_data_center_query_budgets.py`、`python scripts/check_runtime_config_coverage.py`、`python scripts/check_current_data_contracts.py`：全部通过；current-data surface 为 28，query budgets 为 3，runtime refs 为 49 条且全部有分类。
- `python manage.py check`、`python manage.py makemigrations --check --dry-run`、`python scripts/verify_architecture.py --include-audit --format text`：分别为 Django 0 issues、No changes detected、boundary 0/audit 0。
- `python scripts/check_governance_consistency.py --baseline governance/governance_baseline.json`：0 violation；同时把 `apps/data_center/infrastructure/models.py` 的既有 1,746 行体量登记为 P1 split-model-registry remediation（仅锁定继续增长，不视为已拆分）。
- 受影响本地定向回归：Publication/reconciliation/config/macro command/Alpha/Pulse 共 33 passed；Regime 60 passed；Sector/Sentiment 77 passed；Data Center API 31 passed；SDK/MCP 33 passed；Alpha 全量 119 passed；新增/修改生产文件 ruff、black、isort 和 mypy regression 全部通过。
- PostgreSQL CI evidence 的 nodeid 已登记但尚未在本地执行；完整 TUI workbench 全量 migration/setup 超时仍保留为未验证风险，配置中心定向用例已通过。

本批明确未完成：

- 生产 PostgreSQL migration/索引锁预算、D0-D9 真实行数/覆盖率/最新观测时间画像、legacy/canonical shadow export 和至少 2/3 个调度观察窗口；本地 SQLite 只能证明代码契约，不能替代生产验收。
- M9 旧表、旧 admin、历史迁移和 maintenance Query Port 仍保留，等待生产零访问窗口、verified backup/restore 和独立 release；不以静态 guard 通过冒充删表完成。
- VPS/备份/恢复、真实容量水位与 WAL/Redis/Raw 预算、M10 生产切读均未执行；遵守用户“先不部署”的约束。

## 实施记录（2026-08-03，第七批）

本批次针对迁移证据和 CI 执行链路收口；仍不部署、不 push、不连接 VPS、不删除旧表。

已落地：

- 删除无生产调用方的 `core/integration/data_center_business_sources.py` 反向业务桥；Data Center 不再保留这条依赖倒置入口。架构边界与 legacy-access guard 复扫通过，历史基线中的 B4 关闭。
- 新增 `scripts/check_migration_graph.py`，使用 Django `MigrationExecutor` 检查当前数据库全部 migration leaves，拒绝以 `django_migrations` 总行数代替“迁移完成”判断。
- nightly PostgreSQL job 在空库迁移后执行 `MigrationExecutor` 零未应用校验；从已迁移服务库复制独立测试库，critical 套件使用 `--reuse-db --no-migrations`，迁移完整性测试单独保留 migration modules，避免测试库重复迁移并保持迁移回归真实有效。
- 本地一次性 PostgreSQL 16 容器已完成全量迁移（约 11 分钟），`scripts/check_migration_graph.py` 返回 `unapplied=0`；临时容器仅用于本地证据，未触碰现有 home-lab 容器。

第七批机器证据：

- `python scripts/check_migration_graph.py`：`Migration graph verified: unapplied=0`。
- `pytest tests/unit/data_center/test_published_query_ports.py tests/unit/data_center/test_reconciliation_and_query_budget.py tests/unit/config_center/test_runtime_config_control_plane.py -q --reuse-db --no-migrations --timeout=180`：19 passed（PostgreSQL）。
- PostgreSQL critical 套件业务断言 20 passed；本机 Docker Desktop 在 Django transaction teardown 的大批量 `TRUNCATE` 上超过 600 秒，导致进程退出 1；迁移完整性用例本身已在 migration modules 开启时通过，未将本地慢速 teardown 误报为业务失败。
- `ruff check scripts/check_migration_graph.py`、`python -m py_compile scripts/check_migration_graph.py`：通过。

仍未完成及风险：

- CI 迁移链路已修复并待下一次 GitHub Actions 实际运行确认；本地 Windows Docker 的 PostgreSQL flush 性能不能替代 Linux runner 证据。
- D0-D9 生产数据画像、legacy/canonical shadow reconciliation、PostgreSQL 生产索引/P95/锁预算、备份恢复、至少 2/3 个生产调度观察窗口、M9 旧表清理与 M10 生产切读仍未完成。
- 按用户当前指令不部署、不 push；生产证据和破坏性迁移必须在单独授权、verified backup/restore 和 release 窗口后执行。

## 实施记录（2026-08-03，第八批）

本批次补齐运行时 Catalog 和数据集级可靠性边界；仍只做本地代码与可重复验证，不部署、不 push、不连接 VPS、不删除旧表。

已落地：

- 新增 `DatasetContractModel`、`DatasetProviderBindingModel`、`DatasetPublicationPolicyModel` 和 `DataOwnerRegistrationModel`，迁移为 `0054_dataownerregistrationmodel_datasetcontractmodel_and_more.py`；通过 Application Protocol、Repository 和 Public Port 访问，治理 JSON 只作为可审计投影，不再是运行时唯一真源。
- 新增 `initialize_data_center_catalog` 幂等初始化命令及 `check_data_center_runtime_catalog.py`，校验 active contract、provider binding、publication policy 和 owner registry 与治理投影的集合一致性；nightly PostgreSQL 链路已接入迁移后初始化/校验步骤。
- 所有数据域 owner 登记补齐 `acceptance_owner`；Provider Health 的主键扩展为 `provider × dataset_key`（保留旧配置兼容读写），避免同一 Provider 不同数据集共享错误健康状态。
- realtime A-share breadth 改为四个指标逐项通过 Canonical Publication 后才读取事实；任一 publication 缺失即返回稳定的 `canonical_publication_missing` 阻断，不把非空旧事实包装成当前数据。

第八批机器证据：

- 本地 SQLite 完成从现有开发库到最新 migration，Catalog 初始化重复执行两次均输出 `contracts=10, bindings=12, policies=10, owners=10`；运行时 Catalog checker 通过。
- `pytest tests/unit/test_data_center_catalog_contracts.py tests/unit/data_center/test_catalog_runtime.py tests/unit/data_center/test_provider_capability_health.py tests/unit/data_center/test_a_share_behavior_query_service.py tests/api/test_realtime_api.py -q --no-migrations --reuse-db --timeout=180`：20 passed；Provider/phase3/use-case 回归：45 passed。
- 变更生产文件 `check_mypy_regression.py`：19 files、0 regression；ruff/black/isort 通过；Django check、迁移 dry-run、architecture boundary/audit、current-data、Celery、legacy-fact、catalog、governance consistency 全部通过。

仍未完成及风险：

- 本地运行时 Catalog 和 SQLite round-trip 不能替代生产 PostgreSQL profile、真实行数/覆盖率、P95/锁预算和调度观察窗口；CI nightly 仍需下一次实际运行确认。
- Provider Health 仍保留旧 `health_metrics` 兼容投影，待所有生产配置迁移并完成观察窗口后才能删除；其他 current 查询仍有维护/历史兼容端口，尚未证明 D0-D9 全部只依赖 Publication。
- 生产 shadow reconciliation、verified backup/restore、M9 旧表清理与 M10 生产切读继续保持未完成；遵守用户“先不部署”约束。

## 实施记录（2026-08-03，第九批）

本批次把 shadow reconciliation 从纯内存分类推进为可追溯的 Data Center 证据链；仍不部署、不 push、不连接 VPS。

已落地：

- 新增 `ReconciliationEvidence` Domain 契约、`ReconciliationEvidenceModel`（迁移 `0055_reconciliationevidencemodel.py`）、Repository、Application UseCase 和 Public Port，持久化 dataset、legacy/canonical snapshot hash、观察时间、分类计数及逐自然键差异。
- 新增只读 Admin 展示和 `record_data_center_reconciliation` maintenance command：读取两个 JSON 快照、计算稳定 SHA-256、执行 same/expected/missing/conflict/code-defect 分类并写入证据；正常业务 current 查询仍只读 Publication，不会触发旧表 shadow 读取。

第九批机器证据：

- `pytest tests/unit/data_center/test_reconciliation_evidence.py -q --no-migrations --reuse-db --timeout=180`：4 passed，覆盖时区阻断、数据库 round-trip、同 evidence_id 幂等和 JSON command hash。
- `python manage.py migrate --noinput` 已在本地 SQLite 应用 `0055`；`python manage.py check`、迁移 dry-run、ruff/black/isort 通过。

仍未完成及风险：

- 当前 command 只消费维护导出的 JSON 快照；生产 D0-D9 导出、至少 2/3 个调度观察窗口、差异 owner/期限登记和自动告警尚未接入，不能把本地 evidence 当作生产 shadow 通过。
- PostgreSQL relation/P95/锁预算、容量画像、备份恢复、M9/M10 和全入口 Publication-only 仍未完成；按约束不触发部署。

## 实施记录（2026-08-03，第十批）

本批次补齐容量画像的本地证据链，并修复 Storage Budget 初始化命令无法启动的参数冲突；仍不部署、不 push。

已落地：

- 新增 `StorageCapacityObservation` Domain、`StorageCapacityObservationModel`（迁移 `config_center.0007_storagecapacityobservationmodel.py`）、Repository、Application Service 和只读 filesystem/database observer，记录 active policy、effective capacity、usage ratio、pressure state、SQLite/PostgreSQL relation sizes 与 metadata。
- 新增 `collect_storage_capacity_profile` 命令；无 active StorageBudgetPolicy 时 fail closed，观测结果通过 Config Center Application Port 写入，不读取代码级容量 fallback。
- 修复 `initialize_storage_budget` 使用 Django 保留 `--version` 参数导致 parser 冲突的问题，统一改用 `--policy-version`。

第十批机器证据：

- 本地 SQLite 应用 `config_center.0007` 后，显式激活 development policy 并执行 `collect_storage_capacity_profile` 成功写入 observation；容量压力按 active policy 正确计算为 `emergency`，未伪造 healthy。
- `pytest tests/unit/config_center/test_capacity_observations.py tests/unit/config_center/test_runtime_config_control_plane.py -q --no-migrations --reuse-db --timeout=180`：13 passed；容量相关 ruff/black/isort 通过。

仍未完成及风险：

- 本地 filesystem/SQLite 画像不能替代生产 PostgreSQL relation、TOAST/WAL、Docker/Redis/backup/logs 全盘画像；真实生产 policy、增长率和 12 个月预测仍待授权环境采集。
- 容量 observation 尚未接入真实 beat/task monitor、故障注入和 readiness 观察窗口；PostgreSQL rollback/备份恢复、M9/M10 及 D0-D9 全入口收口继续未完成。
- 最新 `0055`/`0007` 变更的临时 PostgreSQL 全量迁移在本机 15 分钟预算内未完成，容器已清理；不把这次 timeout 当作通过，仍保留此前独立 PostgreSQL `unapplied=0` 证据，待 CI/Linux runner 重跑。

## 实施记录（2026-08-03，第十一批）

本批次继续推进 D4/D5 的 current Publication-only 查询面，并把 PostgreSQL 容量观测接入 nightly 迁移链路；不部署、不 push。

已落地：

- 新增 `query_published_financial_facts` / `query_published_valuation_facts` 及对应 Public Port；缺少 D4/D5 active Publication 时在读取事实表前 fail closed，并返回稳定 publication evidence。
- `governance/current_data_contracts.json` 新增 D4/D5 publication-only surface 与精确测试 nodeid；nightly PostgreSQL job 在 Catalog 初始化后显式激活 `nightly-ci` StorageBudgetPolicy 并记录容量 observation。

第十一批机器证据：

- `pytest tests/unit/data_center/test_published_query_ports.py -q --no-migrations --reuse-db --timeout=180`：5 passed；`python scripts/check_current_data_contracts.py`：29 surfaces。

仍未完成及风险：

- D4/D5 内部 Alpha/Factor 历史/批量端口仍保留兼容语义，尚未完成全消费者切读和生产 publication 观察；不能以新增 Public Port 代替全域退出条件。
- nightly PostgreSQL capacity step 尚未在 GitHub Actions 实际运行；本机最新全量迁移 timeout 仍是未验证项。

## 实施记录（2026-08-03，第十二批）

本批次修正 SDK Publication-only 参数传播缺口，避免 SDK 表面支持 `mode/publication_key`、实际请求却丢失 gate 参数；不部署、不 push。

已落地：

- `sdk/agomtradepro/modules/data_center.py` 的 News 和 Sector Constituents 查询现在显式转发 `mode` 与 `publication_key`；此前 News 参数被忽略、Sector 方法没有参数入口。
- SDK contract test 增加 D7 gate 传播断言，防止 REST 已阻断而 SDK 静默降级到未发布读取。

第十二批机器证据：

- `pytest sdk/tests/test_sdk/test_data_center_module.py -q --timeout=180`：30 passed；SDK 模块 ruff/black 通过。

仍未完成及风险：

- MCP/Terminal/TUI 与 REST 的全数据域 publication_id/reliability 一致性仍需跨入口快照测试；生产 publication 数据和观察窗口尚未具备。

## 实施记录（2026-08-03，第十三批）

本批次修正“新建 Publication 洗白旧观测”的可靠性缺口；仍只做本地代码与契约测试，不部署、不 push、不连接 VPS。

已落地：

- `CanonicalPublicationRepository` 增加按 publication 读取最早成员 `observed_at` 的端口；Publication gate 对真实仓储按 Dataset Contract 的 `freshness_seconds` 校验成员观测时间，而不是把 `published_at` 或请求时间当作数据新鲜度。
- Publication 缺少成员观测、成员时间为 naive 或超过 freshness budget 时，所有 published query ports 统一返回空 rows、`must_not_use_for_decision=true`、`freshness_status` 和稳定阻断原因；不会继续查询事实仓储。
- `governance/dataset_contracts.json` 为 D0-D9 的 current/publication 数据集补齐显式 freshness budget，Catalog 初始化后以持久化 Dataset Contract 为运行时阈值；缺少 active contract 或阈值时 fail closed。
- D4/D5 current-data contract 登记 `canonical_publication_stale` 与精确回归 nodeid，防止后续修改删除旧观测阻断测试。

第十三批机器证据：

- `pytest tests/unit/data_center/test_published_query_ports.py tests/unit/data_center/test_a_share_behavior_query_service.py -q --no-migrations --reuse-db --timeout=180`：13 passed，覆盖新 Publication + 旧成员观测、freshness policy 缺失、观测缺失/naive、缺失 Publication、各类 published port fail-closed。
- 本批 freshness gate 已通过 ruff/black/isort、5 个生产文件 mypy regression、architecture/current-data/governance 全量门禁。

仍未完成及风险：

- 本地 fake/SQLite 的 freshness 证据不能替代生产成员观测完整性、真实 Dataset Contract 阈值、全 D0-D9 入口快照一致性和至少 2/3 个调度观察窗口。
- 最新 `0055`/`0007` 在临时 PostgreSQL 全量迁移的 15 分钟预算内未完成，不能据此宣称最新迁移链路通过；生产 PostgreSQL 画像、备份恢复、M9/M10 和 VPS 部署仍保持未执行。

## 实施记录（2026-08-03，第十四批）

本批次消除 MCP 研究快照的两个旁路：Publication gate 不再因 SDK/测试 double 不支持 `mode` 而降级，且 gate 阻断元数据不再被误判为“有证据”；不部署、不 push。

已落地：

- MCP `_published_read` 强制传递 `mode="published"`，移除捕获 `TypeError` 后重试未 gated 读取的兼容旁路。
- 研究分区先识别 `must_not_use_for_decision`，再计算 rows/evidence；空 rows + `publication_id`/freshness 元数据不会被包装成 fresh，required 分区会阻断整个快照并保留稳定 `blocked_reason_code`。
- current-data contract 新增精确测试，锁定“门禁元数据不是事实证据”和所有研究读取必须带 published mode。

第十四批机器证据：

- `pytest sdk/tests/test_mcp/test_equity_research_snapshot_registry.py -q --timeout=180`：5 passed，覆盖 mode 传播、全局 readiness、旧观测 Publication 阻断元数据和可选分区缺失。
- 本批 SDK/MCP 文件已通过 ruff/black/isort、current-data 和 SDK/MCP 定向回归；MCP 运行时真实生产数据仍未验证。

仍未完成及风险：

- 真实 MCP 接入页、远端 API 的生产 publication/member 观测和 2026-07 当前数据尚未在本批验证；本地 fake 不能替代 VPS/生产验收。
- 全 D0-D9 跨入口 publication_id/reliability 快照、PostgreSQL 最新迁移、备份恢复、生产观察窗口、M9/M10 仍未完成，按用户要求不部署。

## 实施记录（2026-08-03，第十五批）

本批次把成员观测 freshness gate 接到 REST 层，覆盖 SDK/MCP 实际调用的 API 地址；不部署、不 push。

已落地：

- REST `_published_gate` 复用 Application freshness gate；Publication 存在但成员观测 stale、缺失、naive 或 freshness policy 未验证时，接口在进入 financial/valuation/price/quote/news/flow use case 前统一返回空数据和阻断证据。
- REST blocked payload 保留 `publication_id`、`observed_at`、`age_seconds`、`max_age_seconds`、`freshness_status` 和 `blocked_reason`，SDK/MCP 不会因“有 publication_id”而误判为可用事实。
- API current-data contract 登记 `canonical_publication_stale` 及“查询前阻断”精确测试，锁定 MCP 接入页使用的真实 REST 链路。

第十五批机器证据：

- `pytest tests/api/test_data_center_route_cleanup.py -q -k 'published' --no-migrations --reuse-db --timeout=180`：3 passed；新增 stale financial REST test 已证明在进入 financial use case 前阻断。
- freshness gate、MCP 防旁路和 REST 入口已完成完整定向回归：Data Center/API `45 passed`，SDK/MCP `35 passed`；变更文件的 architecture、mypy、current-data、catalog 和 governance guards 通过。

仍未完成及风险：

- 真实运行时还需要在 MCP 接入页地址上用生产数据验证 `publication_id`、成员观测、source 和 reliability 一致；本地 monkeypatch 只验证阻断顺序和响应契约。
- PostgreSQL 最新 migration timeout、生产数据画像、备份恢复、观察窗口、全 D0-D9 切读、M9/M10 仍未完成；按用户要求不部署。

## 实施记录（2026-08-03，第十六批）

本批次补齐最新迁移链路的本地 PostgreSQL 证据；使用一次性 `agomtradepro-canonical-pg-v2` 临时容器（55434 端口、tmpfs），不触碰现有 home-lab 容器、不部署、不 push，完成后已删除容器。

第十六批机器证据：

- 空 PostgreSQL 16 从 356 个未应用 migration 完整迁移到当前代码最新 leaf；`python scripts/check_migration_graph.py` 返回 `unapplied=0`。
- PostgreSQL 上执行 `initialize_data_center_catalog` 与 `check_data_center_runtime_catalog.py`：`contracts=10, bindings=12, owners=10`，运行时 Catalog 校验通过。
- 显式激活 `nightly-ci` 90 GiB StorageBudgetPolicy 并执行 `collect_storage_capacity_profile`，成功持久化 observation；实际临时文件系统小于配置容量，状态为 `emergency`，证明 effective capacity/阻断语义没有伪造 healthy。
- PostgreSQL 定向回归：Data Center/Config Center `27 passed`；控制面、Catalog、Reconciliation、A-share/API `50 passed`；SDK/MCP `35 passed`。
- 执行 `data_center.0055` reverse 到 `0054`（预期 `unapplied=1`）再 forward 回 `0055`，最终 migration graph 再次 `unapplied=0`，完成本地 rollback/reapply rehearsal。

仍未完成及风险：

- 这是空库/受控数据的 PostgreSQL 证据，不是生产行数、索引/P95/WAL、备份恢复或外部 Provider 全链路证据；临时容器已清理，不能替代生产验收。
- 生产数据画像、D0-D9 真实 shadow reconciliation、至少 2/3 个调度观察窗口、verified backup/restore、M9/M10 和 VPS 部署仍未执行。

## 实施记录（2026-08-03，第十七批）

本批次把 retention 的运行结果从“仅 Celery 返回值”升级为 Data Center 持久化审计证据；不部署、不 push。

已落地：

- 新增纯 Domain `RetentionRun`，记录 policy version、dry-run/执行模式、outcome、候选/计划/删除/hold/block 计数、字节数、cutoff、时间和原因。
- 新增独立 `RetentionRunModel`（迁移 `0056_retentionrunmodel.py`）与 Repository；模型放在独立 `retention_models.py`，避免继续增大既有超大 `infrastructure/models.py`。
- `RetentionCleanupUseCase` 和 `cleanup_expired_raw_payloads_task` 在 policy 缺失、noop、blocked、partial、success 等路径均保存 run evidence；RawPayload size 纳入 planned/deleted bytes。
- 追加 retention task fake/SQLite 回归和数据库 round-trip，Celery contract、architecture、mypy、legacy guard、governance 均通过。

第十七批机器证据：

- `pytest tests/unit/data_center/test_retention_tasks.py tests/unit/data_center/test_retention_control_plane.py -q --reuse-db --no-migrations --timeout=180`：7 passed。
- `python manage.py makemigrations --check --dry-run`：No changes detected；`python manage.py check`：0 issues；`python scripts/check_celery_task_contracts.py`：14 tasks；治理 baseline 0 violation。

仍未完成及风险：

- `RetentionRun` 只记录本地有界 Raw cleanup；分区/rollup、外部归档上传与抽样恢复、真实 beat 观察窗口、全库 usage forecast 仍未实现。
- 最新 `0056` 的 PostgreSQL 空库和 reverse/reapply 证据在下一批补齐；生产 PostgreSQL、备份恢复、D0-D9 真实 shadow、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第十八批）

本批次完成 `0056 RetentionRun` 的隔离 PostgreSQL 安装与回滚演练；临时容器已清理，不部署、不 push。

第十八批机器证据：

- PostgreSQL 16 空库从 356 个未应用 migration 完整迁移到 `data_center.0056_retentionrunmodel`，`python scripts/check_migration_graph.py` 返回 `unapplied=0`。
- PostgreSQL Catalog/runtime catalog 校验通过：`contracts=10, bindings=12, owners=10`；`nightly-ci` 90 GiB policy 与容量 observation 成功写入，实际 tmpfs 容量不足时正确报告 `emergency`。
- PostgreSQL retention/config 回归：9 passed；完成 `0056` reverse 到 `0055`（预期 `unapplied=1`）再 forward，最终 `unapplied=0`。

仍未完成及风险：

- PostgreSQL 证据仍是空库/受控样本；尚未覆盖生产规模 relation/index/WAL/P95、custom-format backup/restore、真实 Provider 回填和调度观察窗口。
- Retention 分区/rollup、外部 archive restore、全 D0-D9 业务切读、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第十九批）

本批次补齐宏观与 A 股综合行为 Publication-only 入口的 freshness gate；不部署、不 push。

已落地：

- `query_published_macro_fact_series` 从“只要有 publication 就放行”改为复用统一成员观测 freshness gate；缺失、过期、naive 或无契约时均返回空 rows 和阻断证据，不读取事实仓储。
- A 股上涨/下跌/涨停/跌停综合行为逐组件执行 `macro.fact` freshness gate，响应保留 `publication_gates`、`stale_fields`、`blocked_fields` 和稳定阻断原因，避免单一 publication 或旧事实掩盖组件过期。
- `governance/current_data_contracts.json` 增加宏观 freshness marker 及宏观/A 股 stale 回归 nodeid。

第十九批机器证据：

- `pytest tests/unit/data_center/test_published_query_ports.py tests/unit/data_center/test_a_share_behavior_query_service.py -q --no-migrations --reuse-db --timeout=180`：15 passed。
- `pytest tests/unit/pulse/test_data_provider_guardrails.py tests/unit/regime -q --no-migrations --reuse-db --timeout=180`：60 passed。
- `python scripts/check_current_data_contracts.py`：29 surfaces；变更文件 ruff/black/isort 与 `check_mypy_regression.py` 通过。

仍未完成及风险：

- 该批只收口本地 Application/业务适配器 freshness 语义；生产 publication/member 观测、D0-D9 全入口快照、备份恢复、P95/WAL、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第二十批）

本批次把 Dashboard 的 `latest` 宏观值切到 Data Center Publication-only port，防止网页/仪表盘绕过 MCP/REST 已有的 freshness gate；不部署、不 push。

已落地：

- `DashboardApplicationGateway.get_latest_macro_indicator_value` 改为调用 `get_published_macro_fact_series(..., limit=1)`，对阻断、空 rows、非数值和非有限值统一返回 `None`，不再直接读取裸 latest fact。
- current-data manifest 登记 Dashboard source marker 和 stale publication 回归，形成跨入口防回归护栏。

第二十批机器证据：

- `pytest tests/unit/dashboard/test_data_center_publication_gate.py tests/unit/dashboard/test_t5_query_edge_contracts.py -q --no-migrations --reuse-db --timeout=180`：18 passed。
- `pytest apps/dashboard/tests/test_alpha_context_repository.py tests/component/test_dashboard_regression_guardrails.py tests/unit/dashboard/test_t5_dashboard_use_case_edge_contracts.py -q --no-migrations --reuse-db --timeout=180`：31 passed。
- `python scripts/check_current_data_contracts.py`：29 surfaces；变更文件 ruff/black/isort 通过。

仍未完成及风险：

- Dashboard 只收口当前宏观摘要入口；生产 publication/member 观测、全 D0-D9 入口快照、备份恢复、P95/WAL、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第二十一批）

本批次收紧 MCP 通用 Data Center 读取入口：默认 `mode="published"`，历史研究必须显式选择 historical；不部署、不 push。

已落地：

- `data_center_get_quotes`、`data_center_get_price_history`、`data_center_get_macro_series`、`data_center_get_news`、`data_center_get_capital_flows` 及 core fallback 均默认传递 `mode="published"` 与 `publication_key`。
- 工具文案明确历史研究需要显式 historical，避免 MCP 调用者以“latest/current”名义获得未发布旧值。
- MCP 测试 fixture 固定后端身份，避免 RBAC 审计测试因外部 profile 网络请求挂起；新增 fallback 默认 published 断言。
- current-data manifest 登记 MCP 工具与 fallback marker。

第二十一批机器证据：

- `pytest sdk/tests/test_mcp/test_data_center_tools.py -q --timeout=60`：25 passed（本机工具注册/重载耗时约 168 秒）。
- `pytest sdk/tests/test_mcp/test_core_registry_owner_data_center_01.py sdk/tests/test_mcp/test_t5_owner_fallback_contracts.py -q --timeout=60`：20 passed。
- `pytest sdk/tests/test_mcp/test_core_registry_read_matrix_data_center.py -q --timeout=60`：9 passed。
- `python scripts/check_current_data_contracts.py`：29 surfaces；MCP 变更文件 ruff/black/isort 通过。

仍未完成及风险：

- SDK 直接调用若不显式传 `mode` 仍保留兼容的 historical 默认；本批已保证 MCP 用户面和 fallback 不再静默使用该默认，SDK 默认值统一仍需单独兼容性批次。
- 生产 publication/member 观测、全 D0-D9 入口快照、备份恢复、P95/WAL、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第二十二批）

本批次完成 SDK Data Center 读取方法的默认语义收口：未显式指定时统一请求 `published`，历史读取必须显式传 `mode="historical"`；不部署、不 push。

已落地：

- SDK `get_macro_series`、`get_price_history`、`get_latest_quotes`、`get_fund_nav`、`get_financials`、`get_valuations`、`get_sector_constituents`、`get_news`、`get_capital_flows` 默认 `mode="published"`。
- 清理 capital-flow SDK 重复 mode/publication 参数写入，避免请求契约出现重复键路径。
- SDK endpoint、MCP generic read、equity snapshot 与 realtime delegation 回归保持一致。

第二十二批机器证据：

- `pytest sdk/tests/test_sdk/test_data_center_module.py -q --timeout=60`：30 passed。
- `pytest sdk/tests/test_sdk/test_realtime_module.py sdk/tests/test_mcp/test_equity_research_snapshot_registry.py sdk/tests/test_mcp/test_data_center_tools.py -q --timeout=60`：38 passed。
- SDK MCP fallback/core read matrix：此前第二十一批 15 + 20 + 9 passed；current-data 29 surfaces、MCP 工具格式/契约门禁通过。

仍未完成及风险：

- SDK 的 historical 模式仍可被调用者显式选择，这是回测/维护所需的受控兼容面；生产决策入口必须继续使用 published gate。
- 生产 publication/member 观测、全 D0-D9 入口快照、备份恢复、P95/WAL、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第二十三批）

本批次在一次性 PostgreSQL 16 容器中完成 custom-format backup/restore 演练；容器使用 tmpfs，已停止并删除，不触碰现有 home-lab 容器、不部署、不 push。

第二十三批机器证据：

- 空 PostgreSQL 16 从零迁移到当前代码最新 leaf，`django_migrations=357`；Data Center Catalog 初始化为 contracts=10、bindings=12、policies=10、owners=10，并显式激活 `backup-test` StorageBudgetPolicy。
- `pg_dump --format=custom --compress=6 --no-owner --no-acl` 生成非空备份，大小 `1,591,366` bytes，SHA-256：`0ae76e5d06835e03f45b9715c1c5e6ccc1a7171c537f27a0224d2efc148be44c`；`pg_restore --list` 可读。
- 恢复到同容器独立 `agomtradepro_restore` 数据库，`pg_restore --exit-on-error` 成功；恢复库核对 `django_migrations=357`、`data_center_dataset_contract=10`、`config_center_storage_budget_policy=1`。

仍未完成及风险：

- 这是空库/治理样本的本地恢复证据，不是生产 custom-format 备份、VPS 外部下载、SHA 交叉核对、恢复时长/SLO 或真实数据行数证据；因此仍禁止 M9 破坏性迁移。
- 生产 publication/member 观测、D0-D9 全入口快照、P95/WAL、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第二十四批）

本批次收口 Equity 财务/估值兼容入口，补上 REST、SDK、MCP 之间的 Publication mode 传播和 stale fail-closed 证据；不部署、不 push。

已落地：

- 新增 Data Center Application `get_decision_publication_gate`，为 Equity REST 入口合并 publication 与成员观测 freshness gate；缺失、过期或未验证时在进入事实查询/估值用例前返回空结果、`status=blocked`、`must_not_use_for_decision=true` 和稳定阻断原因。
- Equity financial-history 与 valuation API 增加显式 `mode`/`publication_key`；`historical` 保留为历史查询兼容语义，`published` 才执行当前 Publication gate，并把 publication evidence 透传给 SDK/调用方。
- SDK Equity financials/valuation 方法保留 `mode`/`publication_key` 参数；MCP `get_stock_financials`、`get_stock_valuation` 以及 legacy valuation fallback 默认使用 `published`，历史研究必须显式传 `mode="historical"`。
- 将 Equity API 边界测试数据迁移为 canonical `FinancialFactModel`，不再用已冻结的旧 `FinancialDataModel` 投影验证 D4/D5 生产读取；同步登记 `current_data_contracts.json` 与架构 inventory。

第二十四批机器证据：

- `pytest tests/api/test_equity_api_edges.py -q --no-migrations --reuse-db --timeout=180`：39 passed。
- `pytest sdk/tests/test_sdk/test_equity_module.py -q`：14 passed；`pytest sdk/tests/test_mcp/test_core_registry_owner_equity.py sdk/tests/test_mcp/test_equity_hedge_tools.py -q --timeout=60`：15 passed；`pytest sdk/tests/test_mcp/test_sdk_alignment_read_registry.py -q --timeout=60`：21 passed。
- `python scripts/check_current_data_contracts.py`：29 surfaces；`check_governance_consistency.py`、`verify_architecture.py`、`check_data_center_legacy_fact_access.py`、`check_data_center_catalog_contracts.py` 均通过；`check_mypy_regression.py`：4 个生产文件 0 regression；`python manage.py check`：0 issues；变更文件 ruff/black/isort 通过。

仍未完成及风险：

- 本批只证明本地 REST/SDK/MCP 的阻断顺序和参数契约；真实 MCP 接入页、VPS 生产 publication/member 观测、2026-07 当前数据、跨入口 publication/reliability 快照仍未验证。
- SDK Equity 直接调用不传 `mode` 仍保留 historical 兼容默认；MCP 用户面已强制默认 published，后续如要改变 SDK 兼容默认必须单独评估并登记迁移批次。
- PostgreSQL 生产数据画像、P95/WAL、真实备份恢复、M9/M10 和 VPS 仍未执行，按用户要求不部署。

## 实施记录（2026-08-03，第二十五批）

本批次修正 Valuation legacy formal adapter 的缺失值语义，防止缺失价格字段被序列化成 `0` 并污染决策证据；不部署、不 push。

已落地：

- `AssetAnalysisValuationSource` 对缺失的 fair value、entry/target/stop-loss 字段保留 `None`，由既有 `ValuationPayloadPolicy` 继续执行正值、质量和 freshness 校验；不再把未知值伪造成零值。
- 新增 current-data contract 与回归测试，锁定 legacy adapter 的 missing-field 语义。

第二十五批机器证据：

- `pytest tests/unit/valuation/test_asset_valuation_service.py tests/unit/valuation/test_asset_valuation_service_safety.py -q --no-migrations --reuse-db --timeout=120`：17 passed。
- `python scripts/check_current_data_contracts.py`：30 surfaces；变更文件 ruff/black/isort 通过。

仍未完成及风险：

- 本批只修正一个 legacy valuation compatibility source 的响应语义；生产 publication/member 观测、全 D0-D9 影子对账、PostgreSQL 规模性能、备份恢复、旧表删除和 M9/M10 仍未完成。

## 实施记录（2026-08-03，第二十六批）

本批次将 `apps/valuation` 的 canonical valuation fact 读取切换到 Data Center Publication-only Port，并修正远端行情缓存的可选成交量语义；不部署、不 push。

已落地：

- `DataCenterValuationFactSource` 不再直接取 `ValuationFactRepository`；改用 `get_published_valuation_facts`，对缺失/过期/阻断 Publication 返回空事实，避免 stale valuation 旁路进入决策服务。
- 保留 `start/end` as-of 窗口过滤与 `valuation_fact_date/fetched_at/extra` 证据字段，fresh published rows 才能进入既有 valuation policy。
- 远端历史行情写入 canonical `PriceBar` 时，缺失的可选 `volume/amount` 保留为 `None`，不再写成零值。
- current-data contract 扩展 valuation source 的 Publication gate 与 missing-value 回归标记。

第二十六批机器证据：

- `pytest tests/unit/valuation/test_asset_valuation_service.py tests/unit/valuation/test_asset_valuation_service_safety.py -q --no-migrations --reuse-db --timeout=120`：19 passed。
- `pytest tests/component/test_equity_repository_daily.py -q --no-migrations --reuse-db --timeout=120`：5 passed；变更文件 ruff/black/isort 通过。
- `python scripts/check_current_data_contracts.py`：30 surfaces。

仍未完成及风险：

- 估值服务在 valuation facts 被阻断时仍可按既有契约回退到显式标注的 canonical current-price fallback；这不是 valuation fact 的替代证据，生产 UI/MCP 仍需展示 fallback/blocked 语义。
- 生产 publication/member 观测、全 D0-D9 影子对账、PostgreSQL 规模性能、备份恢复、旧表删除和 M9/M10 仍未完成。

## 实施记录（2026-08-03，第二十七批）

本批次补齐财务事实历史读取的 as-of 边界，消除 Alpha/Factor 在回放或历史评分中取到未来财务期末数据的后视偏差；不部署、不 push。

已落地：

- Data Center FinancialFact repository、Application Query Port 和 Public Port 增加可选 `end/as_of` 过滤，并在 ORM 查询层执行 `period_end__lte=end`。
- Alpha Simple provider 和 Factor adapter 按 `trade_date` 显式请求财务 facts，历史计算不再先取未界定的最新 100/200 行再自行猜测期末。
- current-data contract 登记 repository as-of marker 和 Alpha 回归 nodeid；不改变显式 current Publication gate 的语义。

第二十七批机器证据：

- `pytest tests/component/data_center/test_core_fact_bulk_upserts.py tests/unit/alpha/test_t3b_provider_contracts.py -q --no-migrations --reuse-db --timeout=180`：13 passed。
- `python scripts/check_current_data_contracts.py`：31 surfaces；6 个生产文件 `check_mypy_regression.py`：0 regression；ruff/black/isort、legacy-access、governance、architecture 均通过。

仍未完成及风险：

- Alpha/Factor 仍保留历史 facts 的兼容读取，这是回放语义，不应被误改为 current published；生产 current 入口仍须走 Publication-only Port。
- 生产 publication/member 观测、全 D0-D9 影子对账、PostgreSQL 规模性能、备份恢复、旧表删除和 M9/M10 仍未完成。

## 实施记录（2026-08-03，第二十八批）

本批次为 Equity stock-pool 兼容入口增加显式 Publication mode，阻断 MCP/SDK 通过股票池接口看到 stale 财务/估值事实；不部署、不 push。

已落地：

- `/api/equity/pool/` 增加 `mode`/`publication_key`；显式 `mode=published` 时同时校验财务和估值 Publication freshness，缺失或过期在进入逐股事实读取前返回 `status=blocked`、空股票列表和 gate evidence。
- SDK `get_stock_pool`/`list_stocks` 传播 gate 参数并保留 blocked metadata；MCP `list_stocks` 和 legacy pool fallback 默认 `published`，历史研究必须显式传 `mode="historical"`。
- MCP capability schema、current-data manifest 和 API/SDK/MCP 回归均同步更新；默认历史 REST/SDK 兼容路径保持不变。

第二十八批机器证据：

- `pytest tests/api/test_equity_api_edges.py -q --no-migrations --reuse-db --timeout=180`：40 passed。
- `pytest sdk/tests/test_sdk/test_equity_module.py -q`：15 passed；`pytest sdk/tests/test_mcp/test_core_registry_owner_equity.py sdk/tests/test_mcp/test_equity_hedge_tools.py -q --timeout=60`：15 passed。
- `python scripts/check_current_data_contracts.py`：31 surfaces；pool/serializer mypy regression 0、Django check 0 issues、ruff/black/isort 通过。

仍未完成及风险：

- MCP 原始 `list_stocks` 为历史数组兼容返回，blocked metadata 主要通过 SDK envelope/Capability fallback 暴露；决策型全量查询仍应优先使用 `equity.read.research_snapshot`。
- 生产 publication/member 观测、全 D0-D9 影子对账、PostgreSQL 规模性能、备份恢复、旧表删除和 M9/M10 仍未完成。

## 实施记录（2026-08-03，第二十九批）

本批次补齐 Equity 估值详情中隐含的财务事实旁路：`published` 估值请求现在必须同时通过财务与估值 Publication freshness gate；不部署、不 push。

已落地：

- `/api/equity/valuation/{stock_code}/` 在进入 `AnalyzeValuationUseCase` 前同时校验 `equity.financial.fact` 与 `equity.valuation.fact`。
- 任一分区缺失、过期或未验证时返回 `status=blocked`、`must_not_use_for_decision=true`、稳定 `blocked_reason` 和两分区 `publication_gates`，用例不会执行。
- current-data contract 增加“估值详情因财务分区 stale 而阻断”的精确测试证据。

第二十九批机器证据：

- `pytest tests/api/test_equity_api_edges.py -q --no-migrations --reuse-db --timeout=180`：41 passed。
- `pytest tests/api/test_equity_api_edges.py -q --no-migrations --reuse-db --timeout=120 -k published_valuation`：2 passed。
- `check_mypy_regression.py apps/equity/interface/analysis_actions.py`：0 regression；ruff/black/isort 通过；Django check 保持 0 issues。

仍未完成及风险：

- 本批只修正 REST 估值详情的双分区阻断顺序；用例内部仍读取 canonical latest facts，尚未把 Publication member 选择绑定为同一快照事务。
- 生产 publication/member 观测、全 D0-D9 影子对账、PostgreSQL 规模性能、备份恢复、旧表删除和 M9/M10 仍未完成。

## 实施记录（2026-08-03，第三十批）

本批次修复 MCP Equity 兼容读取丢失 Publication 阻断证据的问题；保留 SDK 旧 list 返回兼容性，不部署、不 push。

已落地：

- SDK 新增 `get_financials_payload`、`get_stock_pool_payload` envelope 方法；原有 `get_financials`/`list_stocks` 继续返回历史 list，避免直接破坏现有 SDK 调用方。
- MCP `list_stocks` 与 `get_stock_financials` 默认请求 `published`，优先返回带 `status`、`publication_id`、`freshness_status`、`must_not_use_for_decision` 和 `blocked_reason` 的 envelope；旧 double 仍走明确兼容包装。
- `equity.read.financial_history` capability 增加 `mode`/`publication_key` 输入和 publication/freshness 输出字段；legacy financial fallback 默认 published 并保留阻断元数据。
- MCP pool/financial capability schema、current-data manifest 和回归测试同步更新。

第三十批机器证据：

- `pytest sdk/tests/test_sdk/test_equity_module.py sdk/tests/test_mcp/test_core_registry_owner_equity.py sdk/tests/test_mcp/test_equity_hedge_tools.py -q --disable-warnings --maxfail=1 --timeout=60`：32 passed；其中 raw MCP financial/pool blocked envelope 定向集 13 passed。
- `python scripts/check_current_data_contracts.py`：31 surfaces；ruff/black/isort 通过。
- 本地 SQLite 真实画像（`002156.SZ`/通富微电）当前无 canonical price/financial/valuation facts 和 current Publication；`get_published_financial_facts`、`get_published_valuation_facts` 均返回空 rows、`must_not_use_for_decision=true`、`blocked_reason=canonical_publication_missing`，证明空库不会伪造“最新”。

仍未完成及风险：

- 旧 SDK 直接 `get_financials`/`list_stocks` 仍是历史 list 兼容形状，调用方若主动绕过 MCP envelope 仍需自行选择 `mode=published` 并读取 API gate；MCP capability/工具用户面已不再静默丢失阻断信息。
- 生产 publication/member 观测、全 D0-D9 影子对账、PostgreSQL 规模性能、备份恢复、旧表删除和 M9/M10 仍未完成。

## 实施记录（2026-08-03，第三十一批）

本批次把 Equity 推荐/筛选入口接入财务与估值双 Publication gate；兼容 REST/SDK 默认 historical，MCP 用户面默认 published；不部署、不 push。

已落地：

- `/api/equity/screen/` 增加 `mode`/`publication_key`；`published` 请求在执行 `ScreenStocksUseCase` 前同时校验 `equity.financial.fact` 与 `equity.valuation.fact`。
- 任一分区 stale/missing/unverified 时返回空 `stock_codes/items`、`status=blocked`、`must_not_use_for_decision=true`、稳定阻断原因和 gate evidence，不执行筛选用例。
- SDK 新增 `get_recommendations_payload`，保留 `get_recommendations` 的旧 list 形状；MCP 推荐 raw tool 与 capability fallback 默认 published 并保留 envelope 元数据。
- Screen response schema、capability input/output、current-data contract 同步更新。

第三十一批机器证据：

- `pytest tests/api/test_equity_api_edges.py -q --no-migrations --reuse-db --timeout=180 -k 'screen or published_screen'`：10 passed。
- `pytest sdk/tests/test_sdk/test_sdk_alignment_read_candidates.py sdk/tests/test_mcp/test_sdk_alignment_read_registry.py -q --disable-warnings --maxfail=1 --timeout=60`：23 passed。
- `pytest sdk/tests/test_sdk/test_equity_module.py sdk/tests/test_sdk/test_sdk_alignment_read_candidates.py -q --disable-warnings --maxfail=1 --timeout=60`：20 passed。
- `pytest sdk/tests/test_mcp/test_equity_hedge_tools.py -q --disable-warnings --maxfail=1 --timeout=60`：15 passed，覆盖 raw MCP score/analysis blocked envelope。
- `check_current_data_contracts.py`：31 surfaces；`check_governance_consistency.py`、mypy、ruff/black/isort 通过。

仍未完成及风险：

- Screen 的 `published` 只在入口处校验 gate，底层筛选用例仍由 canonical repository 读取 latest facts，尚未把筛选批次绑定到单一 Publication member snapshot。
- 生产 publication/member 观测、全 D0-D9 影子对账、PostgreSQL 规模性能、备份恢复、旧表删除和 M9/M10 仍未完成。

## 实施记录（2026-08-03，第三十二批）

本批次收口评分、详情和组合分析的 Equity MCP 旁路，避免它们通过股票池/估值接口静默落到 historical 或丢失阻断状态；不部署、不 push。

已落地：

- SDK `get_stock_score`、`get_stock_detail`、`analyze_stock` 增加可选 `mode`/`publication_key`；旧 SDK 默认保持兼容，`analyze_stock` 不再把 `date` 误传给 `lookback_days`。
- MCP 原始工具和 capability fallback 的评分/分析读取默认 `published`；SDK 端透传 `publication_gates`、`must_not_use_for_decision` 和 `blocked_reason`。
- Equity score/analysis capability schema 登记 Publication 参数和可靠性输出字段，current-data contract 增加对应 markers。

第三十二批机器证据：

- `pytest tests/api/test_equity_api_edges.py -q --no-migrations --reuse-db --timeout=180`：42 passed。
- `pytest sdk/tests/test_sdk/test_equity_module.py sdk/tests/test_sdk/test_sdk_alignment_read_candidates.py -q --disable-warnings --maxfail=1 --timeout=60`：20 passed。
- `check_current_data_contracts.py`：31 surfaces；`check_governance_consistency.py`、mypy、ruff/black/isort 通过。

仍未完成及风险：

- 原始 SDK score/detail/analysis 兼容调用不传 mode 时仍允许 historical；仅 MCP/capability 用户面强制 published 默认。
- 生产 publication/member 观测、全 D0-D9 影子对账、PostgreSQL 规模性能、备份恢复、旧表删除和 M9/M10 仍未完成。

## 实施记录（2026-08-03，第三十三批）

本批次补齐 DCF 与综合估值计算的财务/估值事实双门禁，避免计算器绕过已收口的 Equity 详情与筛选 gate；不部署、不 push。

已落地：

- `CalculateDCFRequestSerializer`、`ComprehensiveValuationRequestSerializer` 增加 `mode`/`publication_key`，兼容默认 historical。
- `published` DCF/综合估值请求在进入对应 UseCase 前同时校验 `equity.financial.fact` 与 `equity.valuation.fact`；任一 stale/missing/unverified 返回空估值、`status=blocked`、`must_not_use_for_decision=true`、稳定原因和 gate evidence。
- 成功响应与 OpenAPI response serializer 同步发布 mode、publication key、gate evidence；current-data contract 增加计算器阻断 nodeid。

第三十三批机器证据：

- `pytest tests/api/test_equity_api_edges.py -q --no-migrations --reuse-db --timeout=180 -k 'valuation_calculators or dcf or comprehensive'`：4 passed。
- `check_mypy_regression.py`（2 个 Equity Interface 文件）：0 regression；ruff/black 通过。

仍未完成及风险：

- DCF/综合估值 UseCase 内部仍读取 canonical latest facts，尚未将事实读取绑定到同一 Publication member snapshot。
- Technical/Intraday 等价格图表接口仍需下一批审计其 current freshness 语义；生产 publication/member 观测、全 D0-D9 影子对账、PostgreSQL 规模性能、备份恢复、旧表删除和 M9/M10 仍未完成。

## 实施记录（2026-08-03，本地收口回归）

本地代码批次完成统一回归；仅验证本地 SQLite/SDK/MCP 和静态治理，不推送、不部署。

机器证据：

- `pytest tests/api/test_equity_api_edges.py -q --no-migrations --reuse-db --timeout=180`：44 passed。
- `pytest sdk/tests/test_sdk/test_equity_module.py sdk/tests/test_mcp/test_core_registry_owner_equity.py sdk/tests/test_mcp/test_equity_hedge_tools.py sdk/tests/test_mcp/test_sdk_alignment_read_registry.py -q --disable-warnings --maxfail=1 --timeout=60`：59 passed。
- `python manage.py check`：0 issues；`check_current_data_contracts.py`：31 surfaces；`check_governance_consistency.py`、`check_data_center_legacy_fact_access.py`、`verify_architecture.py` 均通过。
- 本地通富微电真实 SQLite 画像仍无 canonical facts/current Publication；published ports 明确返回 `canonical_publication_missing` 阻断，未把空数据包装成最新行情。

本地批次结论：

- Equity financial/valuation/screen/pool/DCF/comprehensive/score/analysis 的 REST/SDK/MCP 入口已补齐可追踪的 published gate 和 blocked metadata；历史兼容入口仍要求调用方显式选择 published 才能用于当前决策。
- 这不是全计划完成声明。生产 publication/member 观测、D0-D9 shadow reconciliation、PostgreSQL 生产容量/P95/WAL/锁预算、真实备份恢复、Retention/Archive 调度、CI Linux nodeid、M9 旧表清理、M10 生产切读和 VPS 部署仍未执行。

## 实施记录（2026-08-03，第三十五批）

本批次收口 Decision Rhythm 技术/基本面特征的 Publication freshness 旁路，并校正估值事实测试对 canonical Public Port 的契约；不部署、不 push。

已落地：

- `TechnicalFeatureProvider` 通过 `equity.price.bar` Publication gate 记录 `technical` freshness contract；`FundamentalFeatureProvider` 同时校验 `equity.financial.fact` 与 `equity.valuation.fact`，缺失/过期时只返回中性值并标记 `must_not_use_for_decision`。
- `CompositeFeatureProvider` 发布技术/基本面 freshness；推荐用例先读取技术/基本面，再收集 freshness，阻断信息不会因调用顺序丢失，最终方向进入 HOLD、置信度归零并保留原因码。
- 估值 provider component tests 改用 `get_published_valuation_facts` Public Port，移除对旧 `ValuationFactRepository` mock 的旁路依赖。
- current-data contract 增加技术/基本面 gate markers 和阻断/顺序回归 nodeid。

第三十五批机器证据：

- `pytest tests/component/test_feature_providers.py tests/unit/decision_rhythm/test_flow_feature_freshness.py tests/unit/test_unified_recommendation_use_cases.py -q --no-migrations --reuse-db --timeout=180`：57 passed。
- `pytest tests/unit/test_unified_recommendation_use_cases.py -q --no-migrations --reuse-db --timeout=180`：19 passed。
- 变更生产文件 mypy regression 0；ruff/black 通过；`check_current_data_contracts.py` 保持 31 surfaces。

仍未完成及风险：

- Decision Rhythm 的 technical/fundamental gate 目前是入口级 Publication freshness 证据，底层 repository 仍需后续绑定同一 Publication member snapshot，避免 gate 与读取之间出现更新竞态。
- 生产 publication/member 观测、D0-D9 shadow reconciliation、PostgreSQL 生产容量/P95/WAL/锁预算、真实备份恢复、Retention/Archive 调度、CI Linux nodeid、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第三十六批）

本批次收口 Dashboard Alpha 与 Alpha AI 的股票上下文旁路：当前用户面不再直接读取未发布的 latest 价格/财务/估值事实；名称展示单独走 AssetMaster 元数据，避免为展示名称触发外部回填。仍不部署、不 push。

已落地：

- 新增 `get_published_stock_context_map`，通过 Data Center Public Ports 分别读取 `equity.price.bar`、`equity.financial.fact`、`equity.valuation.fact`，按最新财务报告期聚合同期指标，并保留每个分区的 publication/freshness evidence。
- 缺失、stale、invalid 或未验证的分区不返回旧事实；上下文 row 发布 `must_not_use_for_decision`、`blocked_reason` 和 `publication_gates`，Alpha AI 遇阻断直接失败闭环并保留原 Alpha Top-N。
- Dashboard Alpha gateway 改用 published context；页面上下文透传可靠性证据。Alpha REST 名称 enrich 改用只读 AssetMaster 的 `get_stock_name_map`，不再因名称缺失触发远端行情/资产回填。
- 新增 `get_stock_master_rows`，明确与事实读取分离；current-data contract 增加 `equity.published_stock_context` surface。

第三十六批机器证据：

- `pytest tests/unit/equity/test_published_stock_context.py -q --disable-warnings --maxfail=1 --timeout=30`：2 passed。
- `pytest apps/alpha/tests/test_ai_filter.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=30`：9 passed。
- `pytest apps/alpha/tests/test_ai_filter.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=30`：9 passed；`pytest apps/dashboard/tests/test_alpha_context_repository.py tests/unit/equity/test_published_stock_context.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=60`：11 passed。
- `pytest apps/equity/tests/test_stock_context_repository.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=30`：pytest 输出 11 passed 后 teardown 超时，未把进程退出当作通过；其余定向测试正常退出。
- `ruff`、`black`、`isort`（变更文件）通过；`check_current_data_contracts.py`：32 surfaces。

仍未完成及风险：

- published context 目前按分区 Public Port 读取，尚未把多个分区绑定到同一 Publication member snapshot 事务；读取与 gate 之间仍存在小窗口竞态，后续需以 publication_id/member snapshot 做批量查询。
- 生产 publication/member 观测、D0-D9 shadow reconciliation、PostgreSQL 生产容量/P95/WAL/锁预算、真实备份恢复、Retention/Archive 调度、CI Linux nodeid、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第三十七批）

本批次补充 Equity 分时图的观测时间与可靠性投影，避免“最新分时”只返回点位而不说明源观察时间；仍不部署、不 push。

已落地：

- `GetIntradayChartResponse` 透传最后一个点的 `observed_at`、`freshness_status`、`must_not_use_for_decision` 和 `blocked_reason`。
- 分时点时间为 naive 或超过 5 个自然日时，不抹平为当前时间；响应标记 `unverified`/`stale`，但保留诊断图表数据，调用方不得把它当决策证据。
- Intraday serializer 与 current-data contract 同步登记；原有本地 quote snapshot 已有稀疏/过期拒绝逻辑继续生效。

第三十七批机器证据：

- `pytest tests/api/test_equity_api_edges.py -q --no-migrations --reuse-db --timeout=180 -k intraday`：4 passed。
- `check_current_data_contracts.py`、`ruff`、`black`、`isort`（变更文件）通过。

仍未完成及风险：

- 分时远端备用源仍由现有 Infrastructure failover 负责，尚未把 quote publication_id 绑定进分时点批量响应；因此它是带可靠性标记的诊断读，不是正式决策事实。
- 生产 publication/member 观测、D0-D9 shadow reconciliation、PostgreSQL 生产容量/P95/WAL/锁预算、真实备份恢复、Retention/Archive 调度、CI Linux nodeid、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第三十八批）

本批次并行审计发现并收口两个价格旁路：Equity 技术图表缺少观测时间投影，Rotation 当前价格/比较/相关性仍通过原始 PriceBar bridge 读取；仍不部署、不 push。

已落地：

- `GetTechnicalChartResponse` 增加 `observed_at`、`freshness_status`、`must_not_use_for_decision`、`blocked_reason`；技术图表保留 stale 诊断 candles，但不再暗示其可作为当前决策证据。
- `core.integration.price_history` 新增 published close-price bridge，先经 `get_published_price_bar_series`，Publication 缺失/stale 时返回空 prices 和阻断证据；历史回放仍使用原始 historical bridge。
- Rotation `RotationPriceDataService` 默认 `published`，为 historical/published 使用隔离缓存命名空间，避免历史回放污染 current；compare/correlation/generate signal 均通过新默认模式。
- current-data contract 增加 `equity.technical_chart`、`rotation.published_price_reads` 两个 surface；补充 fresh/stale/诊断和缓存隔离回归。

第三十八批机器证据：

- `pytest tests/unit/core/test_price_history.py -q --disable-warnings --maxfail=1 --timeout=30`：3 passed。
- `pytest tests/api/test_equity_api_edges.py -q --no-migrations --reuse-db --timeout=180 -k technical`：5 passed。
- `pytest tests/api/test_rotation_api_edges.py -q --no-migrations --reuse-db --timeout=180 -k 'compare or correlation'`：12 passed。
- `pytest tests/component/test_runtime_degradation_logging.py tests/component/test_mock_fallback_remediation.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=60`：13 passed。
- 变更生产文件 mypy regression 0；black/isort/ruff 通过；`check_current_data_contracts.py`：35 surfaces。
- `python scripts/data_center_architecture_inventory.py --write`：`provider_imports_outside_data_center=0`、`cross_app_orm_imports=56`、`legacy_fact_references=141`、`current_surface_references=2866`、`data_write_task_decorators=51`、`runtime_parameter_references=49`。

仍未完成及风险：

- Rotation Domain 内部仍以兼容的 `list[float] | None` 计算，但 asset detail、compare、correlation 和 signal response 已增加 `price_reliability`；blocked 时不再返回旧非空价格，published cache 也不会绕过二次 gate。
- Equity technical/intraday 当前仍是带可靠性标记的诊断读，尚未绑定到同一 Publication member snapshot；生产 publication/member 观测、D0-D9 shadow reconciliation、PostgreSQL 生产容量/P95/WAL/锁预算、真实备份恢复、Retention/Archive 调度、CI Linux nodeid、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第三十九批）

本批次修正 Publication freshness 的另一条洗白路径：Publication member 的抓取/重建时间较新时，旧的 `publication.as_of` 不得被忽略；仍不部署、不 push、不连接 VPS。

已落地：

- `_publication_gate` 现在同时约束最老 member `observed_at` 与 Publication `as_of`，取两者中更早的时点计算 freshness；旧知识边界会直接返回 `canonical_publication_stale`，不会进入事实表查询。
- 新增回归测试覆盖“member 被重新索引到当前时间、但 publication.as_of 仍停留在 2025”的场景，证明 SDK/MCP 走的 published Public Port 会 fail closed。

第三十九批机器证据：

- `pytest tests/unit/data_center/test_published_query_ports.py -q --no-migrations --timeout=30`：11 passed。
- `pytest sdk/tests/test_mcp/test_equity_research_snapshot_registry.py -q --no-migrations --timeout=30`：5 passed。
- `python scripts/check_current_data_contracts.py`：35 surfaces；`check_data_center_legacy_fact_access.py` 通过；`verify_architecture.py --include-audit --format text`：boundary/audit 0 violation。

仍未完成及风险：

- Publication gate 仍是读取前的控制面校验；底层事实查询尚未按同一 Publication member 的 `fact_pk` 做原子快照过滤，读取与 gate 之间仍存在竞态，需在后续批次完成 member-bound query port。
- 生产 publication/member 观测、D0-D9 shadow reconciliation、PostgreSQL 生产容量/P95/WAL/锁预算、Retention/Archive 调度、CI Linux nodeid、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第四十批）

本批次清理 Dashboard Alpha 名称回填的跨 App ORM 旁路；事实/行情仍由前序批次的 canonical published context 负责，未扩大到 Fund Holdings canonical 迁移。仍不部署、不 push、不连接 VPS。

已落地：

- `DashboardAlphaContextRepository` 不再直接 import/use `FundHoldingModel`，改调用 Fund Application 的 `resolve_fund_holding_names` facade；批量解析 aliases，异常时返回空上下文并记录类型化日志。
- 名称展示与事实读取保持分离：holding 名称只能作为兼容展示回填，不能触发外部数据抓取，也不会覆盖已存在的 AssetMaster 名称。
- 新增单元测试证明 Dashboard 通过 Fund Application Port 解析 legacy holding 名称；历史 API 回归仍覆盖“读取名称但不写 AssetMaster”。

第四十批机器证据：

- `pytest apps/dashboard/tests/test_alpha_context_repository.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=30`：10 passed。
- `pytest tests/api/test_dashboard_api_edges.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=30 -k legacy_holding_name`：1 passed，14 deselected。
- Dashboard 变更文件 mypy regression 0；ruff/black/isort 通过。

仍未完成及风险：

- Fund Holdings 仍是 Fund App 自有维护投影，尚无 Data Center FundHoldingFact/Publication Port；Alpha ETF 仍直接读写该旧模型，需独立 D6 holdings 子项目后再迁移，不能在本批次用不完整的 facade 假装已 canonicalize。
- 生产 publication/member 观测、D0-D9 shadow reconciliation、PostgreSQL 生产容量/P95/WAL/锁预算、Retention/Archive 调度、CI Linux nodeid、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第四十一批）

本批次把 Publication 的知识边界从 freshness gate 继续传递到 published 事实查询，阻止 publication 之后写入的行穿透到 current/latest 结果；仍不部署、不 push、不连接 VPS。

已落地：

- `publication.as_of` 进入所有 published query port 的行集上界：PriceBar、FinancialFact、ValuationFact、SectorMembership、CapitalFlow、News 均限制日期，Quote 限制 `snapshot_at`；请求区间与 publication 边界取交集，start 超过边界或未来新闻返回空结果。
- News repository 增加可选 end 日期过滤，保持历史读取默认行为不变；Public Port 继续在 gate 阻断时先返回空 rows。
- gate metadata 显式透传 `as_of`，让 REST/SDK/MCP 能审计事实知识边界，而不是只看到 published_at/observed_at。
- 新增 query-port 回归覆盖“member 新但 publication.as_of 旧”“publication 之后的价格/财务/估值/新闻/资金流行”“越界 quote snapshot”不会泄漏。

第四十一批机器证据：

- `pytest tests/unit/data_center/test_published_query_ports.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=30`：13 passed。
- `pytest tests/api/test_data_center_route_cleanup.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=30 -k published`：3 passed，29 deselected；`pytest tests/unit/data_center/test_a_share_behavior_query_service.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=30`：5 passed。
- `pytest sdk/tests/test_mcp/test_equity_research_snapshot_registry.py -q --no-migrations --disable-warnings --maxfail=1 --timeout=30`：5 passed。
- 变更生产文件 mypy regression 0；ruff/black/isort 通过。

仍未完成及风险：

- 当前按 publication.as_of 做日期上界，但尚未按同一 publication 的 `fact_pk` 成员集合做原子查询；如果同一日期存在多个来源/版本，仍需 member-bound query port 解决快照一致性。
- 生产 publication/member 观测、D0-D9 shadow reconciliation、PostgreSQL 生产容量/P95/WAL/锁预算、Retention/Archive 调度、CI Linux nodeid、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第四十二批）

本批次修正 Equity SDK financial history 的 published 旁路：gate 通过后不得再读取旧 Equity 财务投影；仍不部署、不 push、不连接 VPS。

已落地：

- `mode=published` 的 `/api/equity/financials/<stock>/` 先检查 Data Center `equity.financial.fact` gate，再通过 `get_published_financial_facts` 读取 canonical rows，并按 `(period_end, period_type)` 聚合为兼容的 period snapshots。
- canonical rows 缺失、二次 gate 阻断或 publication 不可用时返回空结果和 `must_not_use_for_decision=true`；`mode=historical` 保留显式历史兼容路径。
- published 响应透传 `publication_id`、`as_of/observed_at`、freshness 和阻断字段；回归测试断言 legacy `list_stock_financial_payloads` 不会被调用。

第四十二批机器证据：

- `pytest tests/api/test_equity_api_edges.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=30 -k 'financial_history or financials'`：4 passed，42 deselected。
- `pytest sdk/tests/test_sdk/test_equity_module.py -q --disable-warnings --maxfail=1 --timeout=30 -k financial`：1 passed，17 deselected。
- 变更生产文件 mypy regression 0；ruff/black/isort 通过。

仍未完成及风险：

- Equity DCF/comprehensive/analyze-valuation published 分支仍需额外纳入 `equity.price.bar` gate，不能只凭 financial/valuation gate 将旧 daily_prices/current_price 当作当前价格。
- 生产 publication/member 观测、D0-D9 shadow reconciliation、PostgreSQL 生产容量/P95/WAL/锁预算、Retention/Archive 调度、CI Linux nodeid、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第四十三批）

本批次补齐 Equity 筛选与估值计算器对当前价格的 Publication gate，防止 financial/valuation gate 通过后仍从旧 `daily_prices/current_price` 读取价格；仍不部署、不 push、不连接 VPS。

已落地：

- Equity `screen`、`analyze_valuation`、DCF、comprehensive valuation 的 `mode=published` 统一检查 `equity.financial.fact`、`equity.valuation.fact` 和 `equity.price.bar` 三个 gate。
- 任一价格 Publication 缺失、stale 或未验证时，先返回空/hold 阻断证据，不进入对应 UseCase；historical 模式仍保持显式兼容。
- 回归测试对估值详情、DCF、综合估值逐一 patch UseCase 为失败，证明 stale price 会在计算前阻断。

第四十三批机器证据：

- `pytest tests/api/test_equity_api_edges.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=30 -k 'published_valuation_reads_block_stale_price_publication or published_valuation_calculators_block_stale_publication or financial_history'`：9 passed，40 deselected。
- `apps/equity/interface/analysis_actions.py` mypy regression 0；ruff/black/isort 通过。
- `python scripts/data_center_architecture_inventory.py --write`：`cross_app_orm_imports=55`、`current_surface_references=2869`、`provider_imports_outside_data_center=0`；`check_current_data_contracts.py`：35 surfaces，治理/legacy/architecture guards 通过。

仍未完成及风险：

- 估值 UseCase 内部仍可在 historical 模式读取旧模型；published 当前只在入口 gate 阻断，尚未把同一 Publication member rows 注入 UseCase，仍需统一 member-bound query port。
- 生产 publication/member 观测、D0-D9 shadow reconciliation、PostgreSQL 生产容量/P95/WAL/锁预算、Retention/Archive 调度、CI Linux nodeid、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第四十四批）

本批次把 `publication.as_of` 从 Application Public Port 继续接到 REST Data Center 接口，覆盖 SDK/MCP 实际使用的 HTTP 地址；仍不部署、不 push、不连接 VPS。

已落地：

- REST published 读取在进入 Query UseCase 前，将 macro、price、fund NAV、financial、valuation、sector、news、capital flow 的查询上界与 publication `as_of` 取交集；请求范围完全落在边界之后时 fail closed，返回空数据和阻断原因。
- published quote 不再把超出 publication `as_of` 的 snapshot 或 realtime fallback 当作当前证据；缺少边界内 quote 时返回 `canonical_quote_missing_before_publication_as_of`。
- `QueryFinancialsUseCase`、`QueryNewsUseCase` 增加可选 end 边界，historical 旧调用保持原参数形状；capital-flow 路由剥离 gate 专用 `mode/publication_key` 后再做事实查询校验。
- REST 回归覆盖所有日期型 published view 的边界传递，以及 quote 越界不 fallback。

第四十四批机器证据：

- `pytest tests/api/test_data_center_route_cleanup.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=30`：34 passed。
- `apps/data_center/interface/api_views.py`、`apps/data_center/application/fact_query_use_cases.py` mypy regression 0；ruff/black/isort 通过。
- `python manage.py check`：0 issues；`python manage.py makemigrations --check --dry-run`：No changes detected。

仍未完成及风险：

- REST/Public Port 现在都受 `publication.as_of` 日期上界保护，但尚未按同一 Publication `fact_pk` 成员集合做原子快照过滤；同日多来源/版本仍需 member-bound query port。
- 生产 publication/member 观测、D0-D9 shadow reconciliation、PostgreSQL 生产容量/P95/WAL/锁预算、Retention/Archive 调度、CI Linux nodeid、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第四十五批）

本批次在不改变 REST 行为的前提下拆出 Publication guard，修复可靠性边界接入后 `api_views.py` 超过大文件门禁的问题；仍不部署、不 push、不连接 VPS。

已落地：

- 新增 `apps/data_center/interface/publication_guards.py`，集中承载 `as_of` 解析、日期交集、空交集 fail-closed 和 published gate；`api_views.py` 仅保留 wrapper，并显式传入其现有 Public Port patch seam。
- Data Center API view 非空行数从 1303 降至 1183，低于 1200 行门禁；current-data required markers 通过 wrapper 注释保持可追踪，未提高 `allowed_large_python_files` 豁免。
- REST 现有 publication/date-bound 回归与 Public Port 回归在拆分后保持全绿。

第四十五批机器证据：

- `pytest tests/api/test_data_center_route_cleanup.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=30`：34 passed。
- `pytest tests/unit/data_center/test_published_query_ports.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=30`：13 passed。
- `python scripts/check_current_data_contracts.py`：35 surfaces；`check_governance_consistency.py`：0 violations；`verify_architecture.py --include-audit --format text`：boundary/audit 0 violation。
- `apps/data_center/interface/api_views.py`、`publication_guards.py` mypy regression 0；ruff/black/isort 通过；大文件门禁 0 violation。

仍未完成及风险：

- guard 已拆出但仍是入口级控制面，事实查询尚未按同一 Publication `fact_pk` 成员集合做原子快照过滤；同日多来源/版本仍需 member-bound query port。
- 生产 publication/member 观测、D0-D9 shadow reconciliation、PostgreSQL 生产容量/P95/WAL/锁预算、Retention/Archive 调度、CI Linux nodeid、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第四十六批）

本批次修复 MCP Equity research snapshot 的空证据判定：`rows=[]` 不能因 publication 元数据非空而被视为已获取事实；仍不部署、不 push、不连接 VPS。

已落地：

- `_payload_has_evidence` 纳入 `rows` 容器判定；required section 只带 publication_id/freshness 等控制元数据、但没有事实行时标记 `missing`，整体快照 fail closed。
- 新增“fresh publication + empty rows”回归，覆盖通富微电中文名称经 MCP research snapshot 路由时的核心财务分区。

第四十六批机器证据：

- `pytest sdk/tests/test_mcp/test_equity_research_snapshot_registry.py -q --disable-warnings --maxfail=1 --timeout=30`：6 passed。
- SDK/MCP 变更文件 ruff/black/isort 通过。

仍未完成及风险：

- MCP 快照已阻断空 required rows，但仍依赖 REST/Public Port 提供真实 publication/member 一致性；同一 publication `fact_pk` 原子过滤、生产观察窗口、D0-D9 shadow reconciliation、PostgreSQL 生产容量/P95/WAL/锁预算、Retention/Archive 调度、CI Linux nodeid、M9/M10 和 VPS 仍未执行。

## 实施记录（2026-08-03，第四十七批）

本批次继续只做本地可靠性收口，不部署、不 push、不连接 VPS。重点是把“Publication gate 已通过”与“读取的事实行属于同一 Publication”分开，避免 gate 通过后又从全表挑到同日旧版本；同时阻断 realtime 旁路和尚未具备 member-snapshot 注入能力的 Equity 旧用例。

已落地：

- Publication repository/application port 暴露 `list_members(publication_id)`；D4/D5 行情、报价、财务、估值及 D7-D9 板块成员、新闻、资金流的 published Query Port 校验 `dataset_key/fact_table/natural_key/fact_pk`，并只向 canonical repository 传入该 Publication 的 `fact_pks`。成员缺失、错表、空主键或读取异常统一 fail closed；无成员读取能力的历史测试 fake 仅保留迁移兼容，不作为生产路径。
- PriceBar、QuoteSnapshot、FinancialFact、ValuationFact、SectorMembership、News、CapitalFlow repository 增加可选 `fact_pks` 过滤；同一 Publication 的行集合成为当前读取的原子边界，并保留 historical/maintenance 调用签名。
- Realtime 的 Tushare、AKShare cached fallback、Data Center provider 不再直接读取未发布的 latest QuoteSnapshot/PriceBar；统一通过 published/freshness Public Port，Publication 缺失、过期或异常返回 `None`，外部 AKShare spot 仍可继续 failover。历史日线只保留真实日末观测时间，不包装成请求时间。
- `mode=published` 的 Equity screen、Analyze Valuation、DCF、Comprehensive 在全局 gate fresh 但旧 UseCase 尚不能证明 member snapshot 时显式返回 `canonical_publication_member_snapshot_missing`，不再调用 legacy latest/context 查询；historical 模式保持原行为。这是安全阻断，不宣称这些旧计算器已经完成 member-aware 重写。

第四十七批机器证据：

- `pytest tests/unit/data_center/test_published_query_ports.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=60`：16 passed，覆盖 D4-D9 成员主键绑定和空成员阻断。
- `pytest tests/api/test_equity_api_edges.py -q -k "published_reads_block or published_valuation_calculators_block_stale or published_valuation_blocks_stale_publication or published_screen_blocks_stale" --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=120`：8 passed。
- `pytest tests/component/test_realtime_data_center_provider.py tests/unit/test_realtime_akshare_provider.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=120`：10 passed，覆盖 fresh quote、missing/stale publication 和 fallback。
- `pytest tests/api/test_data_center_route_cleanup.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=60`：34 passed；`pytest tests/unit/data_center/test_use_cases.py tests/unit/data_center/test_published_query_ports.py -q`：52 passed；SDK/MCP Data Center/Equity 回归 59 passed；Terminal/SDK client/internal SSL 41 passed。
- `python scripts/data_center_architecture_inventory.py --write`：`provider_imports_outside_data_center=0`、`cross_app_orm_imports=55`、`legacy_fact_references=141`、`current_surface_references=2879`、`data_write_task_decorators=51`、`runtime_parameter_references=49`；`check_current_data_contracts.py`：35 surfaces；`check_governance_consistency.py`、`verify_architecture.py --include-audit`、legacy/query-budget/Celery guards 均通过。
- `manage.py check`、`makemigrations --check --dry-run`：0 issues / No changes；14 个受影响生产文件 black/isort/ruff 和 mypy regression 0。

未完成及风险：

- 宏观 current Query Port、部分 D0-D3 组合和 Agent/Terminal/TUI 仍需逐入口核对 member-bound；Equity screen/估值旧 UseCase 目前安全阻断而非完成迁移，后续必须注入 canonical member snapshot 后再放开 published 计算。
- 真实 publication member 写入器、生产观察窗口、D0-D9 shadow reconciliation、PostgreSQL 生产容量/P95/WAL/锁预算、Retention/Archive 调度、CI Linux nodeid、M9/M10 和 VPS 仍未执行；本批不触发部署。
- `tests/component/infrastructure/test_repositories.py` 初次合并时暴露 `CN_PMI@test` 缺少 unit-rule fixture；已补齐测试级治理规则种子，当前组件回归为 47 passed。生产运行仍不允许对缺失 unit rule 静默回退。

## 实施记录（2026-08-03，第四十八批）

本批次继续只做本地查询边界与 CI 选择器收口，不部署、不 push、不连接 VPS。

已落地：

- `macro.fact` 与 `fund.nav` 纳入 Publication member-bound：Macro/Fund repository、Protocol、DTO、Query UseCase、Application Public Port 和 REST published route 均按同一 Publication 的 `fact_pk` 过滤；`publication.as_of` 同时作为上界，成员缺失/错表/空主键仍 fail closed。Historical 与旧 fake reader 保持兼容。
- CI 的 realtime 模块选择器补入 `tests/component/test_realtime_data_center_provider.py`，并补选择器单测，防止后续只跑 API 而漏掉 published/freshness provider 旁路。
- PostgreSQL/容量/Retention 审计确认本地控制面与契约可验证，但没有把 SQLite 或 Docker 中的其它 PostgreSQL 容器冒充 AgomTradePro 生产证据。

第四十八批机器证据：

- `pytest tests/unit/data_center/test_published_query_ports.py -q --no-migrations --reuse-db`：18 passed（含 macro/fund member-bound）；REST member wiring 定向 `published_views_bound_rows_to_publication_as_of`：1 passed；相关 10 个生产文件 mypy regression 0、ruff/black/isort 通过。
- `pytest tests/unit/ci/test_select_tests.py -q`：49 passed；realtime changed-module selection 明确包含 provider guard。
- 本地关键链路另行通过：critical safety 18 passed；Retention/Raw Landing/Storage/Query Budget/Backup contract/Repository retention safety 共 50+ 项通过；`check_storage_budget_contract.py`、`check_runtime_desired_state.py`、`check_current_data_contracts.py`、`check_governance_consistency.py`、`verify_architecture.py --include-audit`、Celery/legacy/query-budget guards 均通过。

未完成及风险：

- 真实 PostgreSQL migration/integration、P95、WAL/锁等待、pg_dump 隔离恢复与 rollback、真实 beat Retention/Archive 调度、非默认容量故障注入和 VPS 备份证据仍未验证；本地没有 AgomTradePro PostgreSQL 容器，且用户明确要求暂不部署。
- 生产 publication writer/backfill 尚未证明为 D0-D9 每个事实写入 `PublicationMember`；现有生产 publication 若没有成员会安全阻断，不能把“有数据”解释为“已发布”。

## 实施记录（2026-08-03，第四十九批）

本批次补齐 Dashboard 的 current quote 旁路，不部署、不 push、不连接 VPS。

已落地：

- `DashboardApplicationGateway.query_latest_quote` 从直接 `LatestQuoteUseCase` 读取改为 Data Center `get_published_quote_payloads`；missing/stale/memberless publication 返回 `None`，不会把 canonical 全表 latest quote 当成当前价格。
- Dashboard infrastructure 同时兼容 Public Port mapping 和历史测试 fake entity，保留源 `snapshot_at` 文本/日期，不用请求时间重写观测时间。
- 增加 Dashboard fresh/stale quote 回归，并把 current-data contract marker 绑定到该测试。

第四十九批机器证据：

- `pytest tests/unit/dashboard/test_data_center_publication_gate.py -q --no-migrations --reuse-db`：4 passed；Dashboard 两个生产文件 black/isort/ruff/mypy regression 0。
- current-data 35 surfaces、governance 0、architecture boundary/audit 0；inventory 仍为 `cross_app_orm_imports=55`、`current_surface_references=2882`、`provider_imports_outside_data_center=0`。

仍未完成：

- Dashboard 之外的 Equity stock repository、Agent/Terminal/TUI、Factor/Valuation 等维护/组合入口仍需逐项确认是否属于 current 语义；真实 publication writer/backfill 和 PostgreSQL/生产证据仍未完成。

## 实施记录（2026-08-03，Prompt Macro current gate 专项）

本专项收口 Prompt/Agent 的宏观 current/latest 旁路；显式 `as_of_date` 仍保留 point-in-time 历史语义，不部署、不 push。

已落地：

- `DataCenterMacroRepositoryAdapter` / `MacroRepositoryAdapter` 新增独立 `get_published_series` Public Port；Prompt `MacroDataAdapter` 的默认 current trend、`SERIES` 和摘要变化计算只接受 publication-gated rows，缺失或 stale publication 直接返回无证据的 `unknown`/空结果。
- 显式 `as_of_date` 继续走 `get_series(..., use_pit=True)`，不把历史回放改写成 current；源 `reporting_period`/`published_at` 仍由 Data Center fact 转换保留。
- PIT 序列和 publication series 在 Prompt 输出按 `reporting_period` 升序，latest/as-of 选择按观测日期取最大值，避免 newest-first 仓储结果被 `[-1]` 误读成旧值或反转趋势。
- `governance/current_data_contracts.json` 将 Prompt Macro adapter、published-series marker 及 missing/stale fail-closed component 回归纳入 D2/D3 contract。

机器证据（本地）：

- `pytest tests/unit/prompt/test_t5_macro_adapter_contracts.py -q`：11 passed。
- `pytest tests/component/test_prompt_macro_data_center.py tests/component/test_regime_data_center_macro_provider.py -q --no-migrations --reuse-db`：8 passed（含真实 Data Center adapter 的 PIT cutoff、latest/series 顺序、current publication 缺失/stale 阻断）。变更文件 ruff/black/isort 通过。

仍未完成及风险：

- 真实 MCP 接入页、生产 publication/member 观测和当前数据仍需在授权环境验证；本地 fake/SQLite 不能替代生产证据。
- PostgreSQL 生产画像、备份恢复、全入口 publication 快照、M9/M10 和 VPS 部署继续未执行。

## 实施记录（2026-08-03，Macro Public Port facade 收口）

本专项审计并收口宏观兼容 CRUD 适配层；不部署、不 push、不删除旧表。

已落地：

- `apps/data_center/application/public.py` 新增类型化 `MacroProjectionRepositoryProtocol`，`get_macro_projection_repository_port()` 不再返回裸 `object`。
- `apps/macro/infrastructure/data_center_fact_repository.py` 删除本地临时 Protocol/cast，改为直接消费 Data Center Application Public Port；文件不包含 `apps.data_center.infrastructure` 或 ORM import，canonical 读写继续由 Data Center infrastructure 承担。
- `tests/unit/test_data_center_architecture_guard.py` 删除宏观 facade 的 Data Center ORM ratchet 例外，并新增 Public Port 依赖断言；宏观 CRUD/读模型回归保持通过。

机器证据（本地）：

- `pytest tests/unit/test_data_center_architecture_guard.py tests/component/macro/test_data_center_fact_crud_contracts.py -q --no-migrations --reuse-db --timeout=120`：7 passed。
- `python scripts/check_mypy_regression.py apps/data_center/application/public.py apps/macro/infrastructure/data_center_fact_repository.py`：0 regression；目标文件 ruff/black/isort 通过。
- `python scripts/data_center_architecture_inventory.py --write`：`provider_imports_outside_data_center=0`、`cross_app_orm_imports=55`、`legacy_fact_references=143`、`current_surface_references=2885`；`check_data_center_legacy_fact_access.py`、`verify_architecture.py --include-audit` 和 governance consistency 均通过。

仍未完成及风险：

- `DataCenterMacroRepository`/`DataCenterMacroReadRepository` 仍是 macro domain 的兼容形状，生产与维护调用方尚未全部改成直接消费 Data Center `MacroFact` Public Port；在 macro Application/脚本完成 DTO 迁移前不得删除该适配器。
- 当前直接调用方已盘点为 macro `repository_provider`（应用组合根）及 7 个维护/回测脚本；测试 fixture 另有独立引用。删除适配器会改变 macro Application 现有 `MacroIndicator`/serialized-row 契约，需先完成 DTO 迁移和脚本切换。
- 真实 PostgreSQL/生产 publication、全 D0-D9 影子对账、M9/M10 和 VPS 仍未验证；本专项不触发部署。

## 实施记录（2026-08-03，Equity pool member-bound 收口）

本批次修复股票池 `published` 模式在 Publication gate 通过后仍读取未绑定 latest 财务/估值事实的旁路；历史模式保持兼容，不部署、不 push。

已落地：

- `apps/equity/interface/pool_actions.py` 的 `mode=published` 改为统一消费 `get_published_stock_context_map(..., include_price=False)`；不再调用 legacy `get_valuation_history` 或 `get_latest_financial_data`。
- `get_published_stock_context_map` 对 fresh gate 但无 publication member rows 的情况显式返回 `canonical_publication_members_missing`，股票池整体 `status=blocked`，不把空结果当成有效事实。
- 新增 member-bound pool API 回归，并将 source markers 与两个精确 nodeid 登记到 `data_center.publication_only_d4_d5` current-data contract。

机器证据（本地）：

- `pytest tests/api/test_equity_published_pool_member_bound.py tests/api/test_equity_api_edges.py -q --no-migrations --reuse-db --disable-warnings --maxfail=1 --timeout=120`：55 passed。
- `pytest tests/unit/equity/test_published_stock_context.py -q --no-migrations --reuse-db`：3 passed；`check_current_data_contracts.py`：35 surfaces；legacy-access、mypy、ruff/black/isort 均通过。

仍未完成及风险：

- `published` pool 目前按 Public Port 分区读取，尚未把财务/估值 rows 绑定到同一 Publication member snapshot 事务；生产 publication/member 观测、PostgreSQL 与 M9/M10 仍未验证。

## 实施记录（2026-08-03，current-data manifest runner 收口）

本批次把 current-data 治理清单从静态标记提升为可执行 pytest nodeid runner，并接入 nightly CI；本地只做收口验证，不部署、不 push。

已落地：

- 新增 `scripts/run_current_data_contract_tests.py`：先运行 manifest validator，再从 `required_tests` 解析并去重 nodeid；对测试类方法自动补全 pytest class nodeid，manifest 无效或无可执行 nodeid 时直接拒绝执行。
- 新增 runner 单元测试，覆盖去重、类方法 nodeid 解析和非法 manifest 阻断。
- `.github/workflows/nightly-tests.yml` 在数据库迁移后执行 runner，确保登记的 current-data evidence 在 CI 中实际收集/运行，而不是只由 source marker 扫描代替。

机器证据（本地）：

- `pytest tests/unit/test_current_data_contract_runner.py -q`：3 passed。
- runner 完整执行：149 个登记 nodeid 均可解析并执行，pytest 实际通过 188 个测试项；`check_current_data_contracts.py`：36 surfaces，治理一致性通过。

仍未完成及风险：

- 本地 Windows/SQLite 的完整执行不等于生产链路通过；仍需 Linux CI/受控 PostgreSQL 的独立证据。CI 实跑成功前，Definition of Done 中的“manifest nodeid 在 CI 实际执行”仍保持未完成。

## 实施记录（2026-08-03，Sentiment 新闻输入 publication 收口）

本批次将情绪指数的市场新闻输入切到 Data Center Publication/member-bound Public Port；历史回放保留显式兼容模式，不部署、不 push。

已落地：

- `get_market_news_for_sentiment` 默认 `mode="published"`，只消费 `get_published_market_news` 返回的已发布 member rows；缺失、过期或阻断 publication 时返回空证据，不再读取未绑定的 latest 新闻。
- 历史计算必须显式传 `mode="historical"`，继续使用日期边界的历史端口；新闻的 `published_at`/`fetched_at` 保留源时间，解析失败的行直接丢弃。
- `calculate_daily_sentiment_index` 增加显式新闻模式边界，非法模式在任务入口阻断；当前刷新任务保持 published 语义。
- current-data contract 将新闻源 marker、阻断和三个模式回归 nodeid 登记到 `sentiment.current` 与 D7-D9 contract。

机器证据（本地）：

- `pytest tests/unit/sentiment/test_news_publication_contract.py tests/unit/sentiment/test_current_sentiment_contract.py tests/unit/test_sentiment.py -q --no-migrations --reuse-db`：43 passed。
- `pytest tests/unit/sentiment/test_t4b_task_contracts.py tests/unit/sentiment/test_sentiment_operational_readiness.py -q --no-migrations --reuse-db`：15 passed；current-data 36 surfaces、Celery 14 tasks、mypy/architecture/legacy/governance 均通过。

仍未完成及风险：

- 新闻同步任务仍只负责 canonical facts 写入；publication writer/backfill 必须在受控调度中创建包含完整 members 的新版本后，published 情绪刷新才会产生可用输入。生产 publication 观测和 PostgreSQL 证据仍未完成。

## 实施记录（2026-08-03，Canonical Publication 原子 writer 收口）

本批次修复 publication writer 在成员逐条写入期间可能暴露半套快照的问题；不部署、不 push、不删除旧表。

已落地：

- `PublishCanonicalDatasetUseCase` 强制校验 coverage/publication 一致、selected/member 数量一致、成员 natural key/member id/fact 引用唯一、`as_of` 边界存在且所有 member `observed_at` 不晚于边界。
- `CanonicalPublicationRepository.publish_with_members` 以事务原子写入 candidate、members、coverage 并在完整校验后切换 published；任何成员写入失败都会回滚 candidate/member，旧 current publication 不受影响。
- 直接调用 repository `publish`/`save` 也要求完整 member 集合和时间边界，不能绕过 Application 校验发布半成品。
- current-data contract 新增 publication writer atomicity surface，覆盖重复 member 拒绝与事务回滚 nodeid。

机器证据（本地）：

- `pytest tests/unit/data_center/test_control_plane.py -q --no-migrations --reuse-db`：8 passed，含 member write failure 的 rollback 断言。
- `python scripts/check_current_data_contracts.py`：36 surfaces；`check_celery_task_contracts.py`：14 tasks；目标文件 ruff/black/isort/mypy regression 通过。

仍未完成及风险：

- 当前同步 use cases 尚未把每个 D0-D9 bulk upsert 自动编排成 publication candidate/member 写入和 coverage reconciliation；仍需在受控调度窗口接入 writer/backfill，并在 PostgreSQL 观察窗口验证 supersede/rollback。

## 实施记录（2026-08-03，Sector membership consumer member-bound 收口）

本批次修复 Sector policy-influence 聚合在 Publication gate 通过后仍读取全部 canonical membership rows 的旁路；provider/历史同步路径保持不变。

已落地：

- `DjangoSectorRepository.get_stock_sector_name_map` 现在读取当前 `sector.membership` publication 的 member fact PK 集合，再按同一集合查询 canonical membership；publication/member 缺失时返回空 mapping。
- Data Center `SectorMembershipRepositoryProtocol.list_current` 与 infrastructure repository 增加 `fact_pks` 绑定参数，避免“有 publication 但读到未选中事实”。
- current-data D7-D9 contract 增加 sector consumer marker 和精确 member-bound 回归 nodeid。

机器证据（本地）：

- `pytest tests/unit/sector -q --no-migrations --reuse-db`：32 passed。
- `check_current_data_contracts.py`：36 surfaces；Sector/Data Center 变更文件 ruff/black/isort、mypy regression 通过。

仍未完成及风险：

- Sector index/relative-strength 仍属于业务派生缓存，不是 D7 membership facts；其当前/历史读取需继续按数据产品契约区分。生产 publication/member 观测和 PostgreSQL 仍未验证。

## 实施记录（2026-08-03，本地 PostgreSQL 迁移重测）

本次只做本地 PostgreSQL 16 空库迁移验证，不接 VPS、不使用生产数据；临时容器已清理。

机器证据：

- `docker run postgres:16` 临时库启动成功，`pg_isready` 通过；`python manage.py migrate --noinput` 在 15 分钟预算内未完成，过程中已创建 184 张表，最终按超时终止。
- 未把该次迁移当作通过；PostgreSQL 全迁移/关键链路仍需 CI/Linux 或专门迁移性能修复后重新验证。

## 实施记录（2026-08-03，market.news 同步→Publication 与运行配置切换）

本批次只收口两个可独立验收的可靠性切口：新闻同步写入后的 canonical Publication，以及 Data Center failover 容差的 Config Center 运行时读取；不部署、不 push、不触碰生产数据。

已落地：

- `SyncNewsUseCase` 的正式 composition root 注入 `PublishNewsBatchUseCase`；事实写入后按稳定内容/Provider 标识解析精确持久化 fact，计算 `requested/eligible/selected/missing` coverage，以成员最大 `observed_at` 生成显式 `as_of`，并通过既有事务 writer 原子写入 Publication members、coverage 和 supersede 状态。
- `market.news` Publication 使用确定性 hash/UUID5，重复同步同一成员快照返回现有 current；成员缺失、coverage 低于 policy 或未来/无时区观测时间 fail closed。空 `external_id` 使用内容 hash，避免重试产生重复事实。
- 新增 `PublicationFactReference` ORM-free domain value object 与 News candidate query port；current-data manifest 登记 writer source/markers 和精确回归 nodeid。
- `data_center.provider.failover_tolerance` 增加 Config Center active profile/snapshot Public Port；profile 与 immutable snapshot 的 `profile_id/version` 不一致时返回 `None`，消费者只保留已登记的 DataProviderSettings compatibility fallback，并记录迁移状态。

机器证据（本地）：

- `pytest tests/unit/data_center/test_news_publication_sync.py tests/unit/data_center/test_macro_failover_adapter.py tests/unit/data_center/test_control_plane.py tests/unit/data_center/test_phase3_sync_use_cases.py --reuse-db --no-migrations`：29 passed；扩展 News/Query/Sentiment 回归：55 passed；Config Center active snapshot public-port：4 passed；memberless 同 hash 修复回归：5 passed。
- current-data runner：154 个登记 nodeid，实际 193 个测试项全部通过（`--reuse-db --no-migrations`）。
- `check_current_data_contracts.py`：36 surfaces；`check_runtime_config_coverage.py`：49 references；`check_celery_task_contracts.py`：14 tasks；`check_governance_consistency.py`：0 violations；`verify_architecture.py --include-audit`：boundary/audit 0；legacy fact access guard 通过。
- 9 个变更生产文件 mypy regression 为 0；变更文件 ruff/black/isort 通过。

仍未完成及风险：

- 本批只把 `market.news` 接入真实同步→Publication 主链，D0-D9 其他同步用例仍需按数据域分批接入 writer/backfill、checkpoint、覆盖对账和观察窗口；不能据此宣称全域 current 已完成。
- Config Center 目前仍有已登记的兼容来源，SystemSettings 全量退役和所有全局运行参数迁移尚未完成。
- PostgreSQL 最新 migration/性能、生产 publication/member 观察、备份恢复、M9/M10 旧表清理和 VPS 部署仍未验证；遵守“先不部署”约束。

## 实施记录（2026-08-04，market.capital_flow Publication 与 runtime definition 收口）

本批次继续只推进可验证的本地控制面和数据域切口，不部署、不 push、不接触生产数据。

已落地：

- `SyncCapitalFlowUseCase` 的正式 composition root 注入 `PublishCapitalFlowBatchUseCase`；capital-flow facts 写入后按 `(asset_code, flow_date, source)` 精确解析 canonical fact PK，生成成员绑定 Publication、coverage、确定性 hash/UUID5 和幂等重试路径。
- capital-flow member 的 `observed_at` 固定由源 `flow_date` 转换为 UTC 日界，不使用 `fetched_at` 包装旧数据；candidate 同时保留 source record、raw hash、quality 和 revision 证据。
- current-data manifest 增加 capital-flow writer/repository source markers 和 4 个精确测试 nodeid；D7-D9 的 capital-flow current 查询现在有实际同步→Publication 写入路径。
- Config Center 新增 `DEFAULT_RUNTIME_DEFINITIONS` 与 `initialize_runtime_definitions` 幂等初始化命令；active profile 校验通过同一 registered definition catalog，缺失/非法定义不被静默接受。

机器证据（本地）：

- `pytest tests/unit/config_center/test_runtime_definition_reconcile.py tests/unit/config_center/test_runtime_public.py tests/unit/data_center/test_capital_flow_publication_sync.py tests/unit/data_center/test_news_publication_sync.py tests/unit/data_center/test_macro_failover_adapter.py tests/unit/data_center/test_control_plane.py tests/unit/data_center/test_phase3_sync_use_cases.py tests/unit/data_center/test_published_query_ports.py --reuse-db --no-migrations`：61 passed。
- Capital-flow 扩展同步/查询/adapter 回归：84 passed；`python manage.py initialize_runtime_definitions` 成功幂等 reconcile。
- current-data runner：158 个登记 nodeid，实际 197 个测试项全部通过（`--reuse-db --no-migrations`）。
- `check_current_data_contracts.py`：36 surfaces；`check_runtime_config_coverage.py`：49 references；`check_celery_task_contracts.py`：14 tasks；`check_governance_consistency.py`：0 violations；`check_data_center_legacy_fact_access.py` 通过。
- 10 个变更生产文件 mypy regression 为 0；architecture boundary/audit 0；manage check、makemigrations check、ruff/black/isort 全部通过。

仍未完成及风险：

- 目前只完成 `market.news`、`market.capital_flow` 两个同步→Publication writer；quote、price bar、fund NAV、financial、valuation、sector membership 等同步任务仍需同样的受控 writer/backfill、checkpoint 和覆盖对账。
- runtime definition 目前只覆盖首个 failover key；全局运行参数、SystemSettings 退役和非默认 profile/无 active profile 的生产观察仍未完成。
- PostgreSQL 最新迁移/性能、生产 publication/member 观察、备份恢复、容量故障注入、旧表退役和 VPS 部署仍未验证；继续保持不部署。

## 实施记录（2026-08-04，fund.nav Publication 与 failover 开关定义收口）

本批次继续沿同一“事实写入后才能发布、配置必须有定义”原则推进，不部署、不 push、不接触生产数据。

已落地：

- `SyncFundNavUseCase` 的正式 composition root 注入 `PublishFundNavBatchUseCase`；按 `(fund_code, nav_date, source)` 解析精确 canonical fact PK，以源 `nav_date` 的 UTC 日界作为 `observed_at/as_of`，保留 raw hash/source record/quality/revision，并执行 coverage gate 与确定性幂等 Publication。
- `FundNavRepositoryProtocol` 和 infrastructure repository 增加 candidate port；current-data manifest 登记 fund NAV writer/repository markers 和 4 个精确回归 nodeid。
- `data_center.provider.enable_failover` 纳入 Config Center definition reconcile；failover adapter 优先读取 typed active snapshot，缺失/异常/非法值才回退已登记的 DataProviderSettings owner compatibility 值。

机器证据（本地）：

- `pytest tests/unit/config_center/test_runtime_definition_reconcile.py tests/unit/data_center/test_macro_failover_adapter.py tests/unit/data_center/test_fund_nav_publication_sync.py --reuse-db --no-migrations`：23 passed。
- current-data runner：162 个登记 nodeid，实际 201 个测试项全部通过（`--reuse-db --no-migrations`）。
- `check_current_data_contracts.py`：36 surfaces；runtime config coverage 49；governance consistency 0；architecture boundary/audit 0；12 个变更生产文件 mypy regression 0；ruff/black/isort、manage check、makemigrations check 通过。

仍未完成及风险：

- quote、price bar、financial、valuation、sector membership 等同步任务仍未全部接入 Publication writer/backfill；全域 checkpoint、覆盖对账、生产观察窗口和 CI/Linux PostgreSQL 证据仍缺失。
- Config Center 目前只覆盖两个 Data Center failover 参数，SystemSettings 全量退役、所有全局运行参数 owner/非默认 profile 验证仍未完成。
- PostgreSQL 最新迁移/性能、备份恢复、容量故障注入、旧表退役和 VPS 部署仍未验证；继续保持不部署。

## 实施记录（2026-08-04，equity.quote.snapshot Publication 收口）

本批次补齐实时报价快照的事实写入后发布路径，仍不部署、不 push、不接触生产数据。

已落地：

- `SyncQuoteUseCase` 的正式 composition root 注入 `PublishQuoteSnapshotBatchUseCase`；按 `(asset_code, snapshot_at, source)` 精确解析 canonical quote fact PK，生成成员绑定 Publication、coverage、确定性 hash/UUID5 和幂等重试路径。
- quote member 的 `observed_at/as_of` 固定使用源 `snapshot_at`；`fetched_at` 只保留为抓取证据，不被包装成实时观测时间。缺失 raw hash 时由持久化快照字段生成确定性证据 hash，并保留 source record、quality、revision 和 fact PK。
- current-data manifest 增加 quote writer/repository source markers 和 3 个精确回归 nodeid；报价同步现在具有实际同步→Publication 写入路径，供 published quote 查询使用。

机器证据（本地）：

- `pytest tests/unit/data_center/test_quote_snapshot_publication_sync.py --reuse-db --no-migrations`：3 passed；quote 既有同步/freshness/repository 扩展回归：35 passed。
- current-data runner：165 个登记 nodeid，实际 204 个测试项全部通过（`--reuse-db --no-migrations`）。
- `check_current_data_contracts.py`：36 surfaces；runtime config coverage 49；governance consistency 0；architecture boundary/audit 0；变更生产文件 mypy regression 0；ruff/black/isort、manage check、makemigrations check 通过。

仍未完成及风险：

- price bar、financial、valuation、sector membership 等同步任务仍未全部接入同等的 Publication writer/backfill；全域 checkpoint、覆盖对账、生产观察窗口和 CI/Linux PostgreSQL 证据仍缺失。
- 当前 quote policy 的 `fetched_at` 仍是事实表审计证据，Publication member 对外只发布不可伪造的 `observed_at`；若未来要求成员级抓取时间可查询，需要单独扩展契约，不能复用观测时间字段。
- PostgreSQL 最新迁移/性能、备份恢复、容量故障注入、旧表退役和 VPS 部署仍未验证；继续保持不部署。

## 实施记录（2026-08-04，price bar / sector membership Publication 与本地 PostgreSQL 迁移验证）

本批次继续只做本地可复现验证，不部署、不 push、不接触生产数据。

已落地：

- `SyncPriceUseCase` 注入 `PublishPriceBarBatchUseCase`；按 `(asset_code, bar_date, source)` 精确绑定 canonical price fact，使用源 `bar_date` UTC 日界作为 `observed_at/as_of`，并保留 source record、raw hash、quality、revision 与事实主键。
- `SyncSectorMembershipUseCase` 注入 `PublishSectorMembershipBatchUseCase`；按 `(asset_code, sector_code, effective_date)` 精确绑定 canonical membership fact，使用源 `effective_date` UTC 日界作为观测边界，执行已有 `sector.membership` coverage policy、成员绑定和幂等发布。
- 两条路径均在事实写入成功后才调用原子 Publication writer；current-data manifest 登记 writer/repository markers 和精确 nodeid，未把 `fetched_at` 洗白为业务观测时间。

机器证据（本地）：

- price bar + sector membership 定向回归：8 passed；current-data runner：173 个登记 nodeid，实际 212 个测试项全部通过（`--reuse-db --no-migrations`）。
- 临时 PostgreSQL 16 干净库：`python manage.py migrate --noinput` 全部 migration 成功；完成后计数为 357 migrations、47 apps、320 张 public 表；第二次 migrate 返回 `No migrations to apply`。
- 迁移耗时约 15 分 23 秒，说明 schema 完整性已验证但初始化性能仍需后续拆分/剖析；临时容器已销毁，未使用生产数据库。

仍未完成及风险：

- financial、valuation 以及其他非上述同步任务仍未全部接入受控 Publication writer/backfill；全域 checkpoint、覆盖对账、生产观察窗口、备份恢复和容量故障注入仍缺失。
- PostgreSQL 已有本地全迁移证据，但 15 分钟级初始化仍不满足生产运维窗口；尚未完成 Linux/CI 同构验证、增量迁移性能基线和生产备份恢复演练。
- Config Center 全局运行参数 owner、SystemSettings 全量退役、真实 MCP/生产数据观察和 VPS 部署仍未验证；继续保持不部署。

## 实施记录（2026-08-04，equity.financial.fact Publication 与 PIT available_at 收口）

本批次补齐 D4 财务事实的受控同步→Publication 链路，继续不部署、不 push、不接触生产数据。

已落地：

- `FinancialFact` domain entity 和 `FinancialFactRepository` 现在显式传递模型已有的 `available_at`；bulk upsert 不再丢失该 PIT 边界。
- Tushare/AKShare 仅在源记录带有公告/通知日期时转换为 UTC `available_at`；兼容网关只有 period end 时保持 `available_at=None`，不会把 `period_end` 或 `fetched_at` 冒充可用时间。
- `FinancialFactRepository.list_publication_candidates` 按 `(asset_code, period_end, period_type, metric_code, source)` 精确绑定 fact PK，并要求 `available_at`；缺失候选由 `PublishFinancialBatchUseCase` 稳定 fail closed，不能出现事实写入成功但无 Publication 却返回成功的假象。
- `SyncFinancialUseCase` 正式注入 writer；Publication 使用 available-at 作为 member `observed_at/as_of`，执行 coverage、未来时间阻断、确定性 hash/UUID5 和原子成员写入。current-data manifest 登记 source markers 与精确测试 nodeid。

机器证据（本地）：

- 财务 Publication、provider available-at、核心 upsert 和 sync failure matrix 定向回归：51 passed。
- current-data runner：182 个登记 nodeid，实际 221 个测试项全部通过（`--reuse-db --no-migrations`）。
- current-data manifest 36 surfaces；architecture boundary/audit 0；legacy fact access guard 通过；变更 9 个生产文件 mypy regression 0；ruff/black/isort、manage check、makemigrations check 通过。

仍未完成及风险：

- `equity.valuation.fact` 尚未接入同步→Publication writer；其 `available_at`/历史 PIT 查询语义仍需单独收口，不能用估值日期或抓取时间替代公告可用边界。
- financial 旧管理命令和 legacy equity 投影仍处于兼容期；只有 Data Center 正式同步入口具备 Publication 编排，旧入口迁移/零读写尚未完成。
- PostgreSQL 生产画像、Linux/CI 同构迁移性能、备份恢复、全域 checkpoint/覆盖对账、生产观察窗口、M9/M10 和 VPS 部署仍未验证；继续保持不部署。

## 实施记录（2026-08-04，equity.valuation.fact Publication 与 writer 文件边界收口）

本批次完成 D5 估值事实的同步→Publication 编排，并修复 Publication writer 单文件超长治理问题；继续不部署、不 push、不接触生产数据。

已落地：

- `ValuationFact` 与 repository 显式保留模型已有 `available_at`；candidate 严格按 `(asset_code, val_date, source)` 绑定 fact PK，`observed_at/as_of` 使用 `val_date` UTC 日界，绝不使用 `fetched_at`。
- `available_at` 若为未来或 naive 立即阻断；缺失时只标记 `available_at_unverified`，不伪造时间，符合估值 policy 的可选可用性语义。Publication 仍要求 source/observed_at/raw hash，并执行 coverage、未来观测阻断、确定性 hash/UUID5 和原子成员写入。
- `SyncValuationUseCase` 与 `SyncCurrentValuationBatchUseCase` 两个入口均注入同一 writer；补齐单资产和批量事实写入后的 Publication invocation 回归。
- 为满足 `large_python_file` 治理上限，将 valuation writer 拆至 `apps/data_center/application/valuation_publication.py`，共享 hash 拆至 `publication_utils.py`；manifest source markers 同步更新，主 `publication_sync.py` 回到 1200 行以内。

机器证据（本地）：

- valuation Publication / repository / 两个 sync 入口定向回归：8 passed；current-data runner：189 个登记 nodeid，实际 228 个测试项全部通过（`--reuse-db --no-migrations`）。
- current-data manifest 36 surfaces；architecture boundary/audit 0；large-file/legacy/governance guards 0；变更 10 个生产文件 mypy regression 0；ruff/black/isort、Celery contract、runtime config coverage、manage check、makemigrations check 全部通过。

仍未完成及风险：

- valuation provider 当前通常只给 `val_date`，缺失 `available_at` 时 Publication 会明确发布为未验证可用性；历史回放若需要严格 PIT，仍需把 available boundary 纳入 member/query contract，而不能静默补抓取时间。
- D0-D9 全域 checkpoint/backfill/coverage 对账、生产 publication/member 观察、PostgreSQL 生产规模性能、备份恢复、Retention/Archive 实际调度、CI Linux 同构、M9/M10 和 VPS 部署仍未验证；继续保持不部署。

## 实施记录（2026-08-04，macro.fact Publication 与 D0 同步入口收口）

本批次补齐 D0 宏观事实的同步→Publication 编排，继续不部署、不 push、不接触生产数据。

已落地：

- `MacroFactRepository.list_publication_candidates` 按 `(indicator_code, reporting_period, source, revision_number)` 精确解析 fact PK；只接受源 `published_at` 非空的行，并以其 UTC 日界作为 `observed_at`，缺失时不使用 `reporting_period` 或 `fetched_at` 替代。
- `PublishMacroBatchUseCase` 执行 macro policy（coverage 1.0、published-at evidence）、未来边界校验、确定性 hash/UUID5、幂等和原子 member 写入；无可发布候选时稳定 fail closed。
- `SyncMacroUseCase` 正式注入 writer；`SyncMacroBatchUseCase` 通过同一同步入口复用 Publication 编排；新增 macro source markers 与 5 个精确回归 nodeid。

机器证据（本地）：

- macro Publication/repository/sync 定向回归：5 passed；current-data runner：194 个登记 nodeid，实际 233 个测试项全部通过（`--reuse-db --no-migrations`）。
- current-data manifest 36 surfaces；architecture boundary/audit、legacy、large-file、governance guards 0；变更 11 个生产文件 mypy regression 0；ruff/black/isort、Celery contract、runtime config coverage、manage check、makemigrations check 全部通过。

仍未完成及风险：

- D0-D9 现在已有各主要事实域的本地 writer，但全域 checkpoint、backfill、coverage reconciliation、supersede/rollback 及生产调度观察仍未实施；“本地 writer 通过”不等于生产数据已发布。
- PostgreSQL 生产规模/P95/WAL/锁预算、备份恢复、Retention/Archive 实际调度、CI Linux 同构、真实 MCP/生产 publication 观察、M9/M10 和 VPS 部署仍未验证；继续保持不部署。

## 实施记录（2026-08-04，A 股核心回填 durable control plane 收口）

本批次只处理回填任务的可恢复执行证据，继续不部署、不 push、不接触生产数据。

已落地：

- `backfill_active_a_share_core_data_batch_task` 在输入、无剩余资产、Provider 缺失、市场日历阻断和正常批次五条出口统一生成稳定幂等键；以 UUID5 派生 `run_id`、`batch_id` 和 cursor checkpoint，Celery 重试会更新同一 `SyncRun`/`SyncBatch`，不会重复创建批次。
- 每个通过边界校验的执行出口都通过 Data Center composition getters 写入 `SyncRunRepository`、`SyncBatchRepository`、`SyncCheckpointRepository`；checkpoint 保留 `offset/next_offset/total_assets/complete`，并把失败原因、processed/failed 和窗口边界写入 durable control plane。非法输入严格在任何 Repository/Provider 访问前返回，仅保留内存中的兼容 checkpoint 形状。
- 任务返回契约保持 `success/outcome/requested/succeeded/failed/stored/checkpoint`，新增 `published`（仅在同步结果显式暴露 publication/member count 时计数，不用 stored_count 猜测），并保持 `failed/blocked/noop` 的标准业务 outcome。
- 单元测试增加重试幂等断言，并使用 fake repository fixture 验证写入调用，不让无 `django_db` 标记的快速测试隐式触碰 SQLite。

机器证据（本地）：

- `pytest tests/unit/data_center/test_core_data_backfill_task.py -q`：8 passed（含成功、部分失败、全失败、Provider 缺失、市场日历阻断、noop、非法输入和重试幂等）；`pytest tests/component/data_center/test_core_data_backfill_control_plane.py -q`：1 passed（真实 Django 测试库读取三张 control-plane 表）。
- `pytest tests/unit/data_center/test_control_plane.py -q`：9 passed，新增乱序 `published_at` 防回拨测试；`python scripts/check_data_center_query_budgets.py`：3 budgets validated（D0-D6 未填充未经测量的数字）。
- `python scripts/check_mypy_regression.py apps/data_center/application/tasks.py`：0 regressions；`ruff`、`black --check`、`isort --check-only`：通过。
- `python scripts/check_celery_task_contracts.py`：14 tasks / 4 governed files；`python scripts/verify_architecture.py --include-audit --format text`：boundary 0、audit 0。

仍未完成及风险：

- 当前只证明回填出口能写入 durable control plane，尚未在临时 PostgreSQL 中用真实 fake-provider 全链路运行一次回填并读取持久化 `run_id/batch_id/checkpoint`；生产回填、限速、锁/P95、coverage reconciliation、跨批 resume 观察仍未执行。
- 查询预算目前只登记 3 个 D7-D9 端口；D0-D6 尚无真实 PostgreSQL `CaptureQueriesContext`/重复采样 P95 基线，不能用合成数字冒充预算，后续需先建立可复现观测证据再登记。
- Publication repository 已增加 `published_at` 单调性护栏：乱序/同时间快照在 supersede 前 fail closed，不会把当前 Publication 回拨到旧数据；新增 control-plane 回归覆盖当前快照保持不变。
- 全域 Publication rollback（显式恢复旧版本）、legacy/canonical 对账、D0-D9 query budget、PostgreSQL 生产规模、备份恢复、Retention/Archive 实际调度、CI Linux 同构、真实 MCP/生产观察以及 M9/M10/VPS 仍保持未验证；继续不部署。

## 实施记录（2026-08-04，coverage evidence 与 retention fail-closed 收口）

本批次继续只做本地可验证的诊断和数据保留安全修复，不部署、不 push、不触碰生产数据。

已落地：

- active-A-share coverage 诊断不再把事实表 `distinct asset_code` 当成当前数据证据；price/valuation/financial 三个域新增当前 Publication、member_count、fact_pk 绑定覆盖、`as_of/published_at`、最早成员观测、freshness、`must_not_use_for_decision` 和稳定阻断原因。顶层 `status=ok` 必须同时满足事实覆盖、Universe 质量、三份 current Publication、成员绑定完整和 Dataset Contract freshness。
- coverage 诊断对缺 Publication、candidate/blocked 状态、memberless/错表/成员不完整、缺失或 naive 发布边界、`as_of > published_at`、成员观测晚于 `as_of`、缺 freshness policy 和 stale 观测全部 fail closed；保留原有事实覆盖字段供迁移期 UI 兼容，但新增 `published_*` 字段明确区分语义。
- Raw retention candidate 同时遵守 dataset retention policy 与单行 `RawPayload.retention_until`；Repository 使用同一操作时钟过滤 future deadline，Application 层对旧/不安全 candidate adapter 再做一次阻断，避免未来保留期数据被删除。
- `ArchiveManifestRepository.mark_verified` 拒绝 naive `verified_at`、空 checksum 以及 failed/deleted manifest 被直接提升为 verified；保留外部归档对象 checksum 校验由归档 worker 执行的边界。

机器证据（本地）：

- `pytest tests/component/data_center/test_repositories.py -q`：28 passed；`pytest tests/component/data_center/test_repositories.py -q --no-migrations --reuse-db -k diagnostic`：7 passed；`pytest tests/api/test_data_center_universe_config_api.py -q --no-migrations --reuse-db`：4 passed。
- `pytest tests/unit/data_center/test_retention_tasks.py tests/unit/data_center/test_raw_landing.py tests/unit/data_center/test_retention_control_plane.py -q`：13 passed。
- 变更生产文件 `ruff/black/isort`、`python scripts/check_mypy_regression.py`：0 regression；architecture boundary/audit 仍为 0。

仍未完成及风险：

- 当前仍没有实际 RetentionPolicy 初始化/真实 beat 执行、归档对象恢复和容量故障注入证据；默认 dry-run/无 active policy 的 fail-closed 是安全行为，不等于生产 retention 已运行。
- D0-D6 查询预算仍没有真实 PostgreSQL `CaptureQueriesContext`/重复采样 P95 基线，不能用本地 SQLite 或合成数字填充；全域 shadow reconciliation、PostgreSQL 生产规模、备份恢复、CI Linux、生产观察、显式 Publication rollback、旧链退役和 VPS release 仍未完成。

## 实施记录（2026-08-04，D1 影子对账与 D0-D6 查询观测工具收口）

本批次建立可复现的本地证据工具，但不把 fixture 或 SQLite 结果冒充生产基线；继续不部署、不 push、不接触生产数据。

已落地：

- `export_reconciliation_snapshot` 接收调用方注入的 legacy/canonical 快照，复用既有分类器输出 `same/expected_difference/data_missing/semantic_conflict/code_defect`，并对规范化 JSON 计算稳定 SHA-256。空键、归一化键冲突、NaN/Infinity 和非 JSON 值全部 fail closed；Application 层不导入 legacy/canonical ORM，也不自行发现或读取旧表。
- `record_data_center_reconciliation` 维护命令改用同一导出器，持久化两个快照 hash，并打印确定性的逐自然键分类证据，异常快照以 `CommandError` 阻断。
- 增加 D1 有界 fixture（同值、预期差异、缺失、代码缺陷）和机器可读证据测试；fixture 仅用于维护/验收，不代表生产对账已经执行。
- 新增 `scripts/measure_data_center_query_ports.py`，通过真实 Django `CaptureQueriesContext` 对 D0-D6 Public Port 重复采样，记录每次 query count/耗时/有限行数，查询数取样本最大值，P95 使用 inclusive 线性插值。缺少 Port 返回 `unmeasured`，调用异常返回 `error`，均不伪造零查询成功；默认不加载或写入 governance budget，仅在调用方显式传入 `QueryBudget` 时评估。报告不输出 raw SQL 或返回 payload。
- PostgreSQL critical CI job 已接入 current-data manifest、回填控制面、coverage/retention/对账相关测试；GitHub Actions 实际运行结果仍待授权环境取证。

机器证据（本地）：

- `pytest tests/unit/data_center/test_reconciliation_and_query_budget.py tests/unit/data_center/test_reconciliation_evidence.py tests/unit/data_center/test_query_port_measurement.py -q --reuse-db --no-migrations --disable-warnings --maxfail=1`：18 passed。
- 相关生产/工具文件 `ruff`、`black --check`、`isort --check-only` 通过；`python scripts/check_mypy_regression.py apps/data_center/application/reconciliation.py apps/data_center/management/commands/record_data_center_reconciliation.py`：0 regressions。
- 查询测量测试已用本地 SQLite 的真实 `CaptureQueriesContext` 验证 D0；没有将本地 SQLite 的 query/P95 数字写入 D0-D6 governance budget。

仍未完成及风险：

- D0-D6 仍缺真实 PostgreSQL/生产规模的重复采样、P95、锁等待、WAL、内存和容量基线；新增工具只是测量 harness，不等于预算已批准或性能已达标。
- 当前 shadow 对账只证明注入快照的确定性导出和命令输出，尚未接入 legacy/canonical 生产读取、全市场覆盖、连续交易日/周末窗口或差异 owner/期限闭环。
- PostgreSQL CI、备份恢复/rollback、Retention/Archive 实际调度与故障注入、全域 Publication rollback、旧链退役、生产观察和 VPS release 仍未验证；继续保持不部署。

## 实施记录（2026-08-04，Publication rollback 与 SystemSettings 字段治理收口）

本批次补齐两个本地控制面缺口：显式 Publication 恢复和遗留 SystemSettings 字段登记；不迁生产数据、不部署、不 push。

已落地：

- 新增 `RollbackCanonicalPublicationUseCase` 与 `CanonicalPublicationRepositoryPort.rollback`。恢复必须显式提供目标 `publication_id`、理由、操作者和 aware `observed_at`；目标必须是有完整成员/覆盖/时间证据的已 supersede 快照，且当前 scope 只能有一个已发布版本。切换在一个事务内完成，并写入 `PublicationRollbackModel` 审计记录。
- `CanonicalPublication.reinstated_at` 与历史查询边界保持分离：rollback 前的 `as_of` 仍返回原当前快照，只有 rollback 观察时间之后才返回恢复快照；当前读取只接受显式恢复后的已发布状态，不通过非空旧值自动回拨。Publication/成员/coverage 模型已拆出独立模块，避免控制面模型注册表继续突破大文件门禁；旧 `infrastructure.models` 导入路径保留兼容 re-export。
- `governance/runtime_config_contracts.json` 新增 `system_settings_field_contract`：静态 AST 扫描覆盖 `SystemSettingsModel` 全 48 个字段、7 组 owner/lifecycle/replacement 决策，其中 46 个兼容字段显式登记迁移替代物，2 个 metadata 字段标为 metadata。`scripts/check_system_settings_field_contract.py` 对缺失、未知、重复和兼容组缺 replacement 全部 fail closed，并已接入 fast-feedback CI。

机器证据（本地）：

- `pytest tests/unit/data_center/test_control_plane.py -q --reuse-db --no-migrations --disable-warnings --maxfail=1`：11 passed，覆盖恢复后的 current/historical 边界、审计字段、非 published/缺成员/时间不一致阻断和乱序发布护栏。
- `pytest tests/unit/config_center/test_system_settings_field_contract.py -q --disable-warnings --maxfail=1`：4 passed；`python scripts/check_system_settings_field_contract.py`：48 fields / 7 groups / compatibility=46；CI workflow YAML 解析通过。
- `python manage.py check`、`python manage.py makemigrations --check --dry-run`：无问题/No changes detected；相关生产文件 mypy regression 0，ruff/isort 通过；governance consistency、large-file guard：0 violations。

仍未完成及风险：

- rollback 目前是 Application/composition 控制面能力，尚未接入生产运维 API、审批/权限界面、真实 PostgreSQL 事务演练、备份恢复和 rollback runbook；本地 11 条测试不等于生产可操作性证据。
- SystemSettings 字段契约只阻止继续无登记增列，不改变旧 getter/fallback 行为，也未完成 48 字段逐组迁移、消费者切换、字段删除和全量 RuntimeConfigDefinition 覆盖。
- 全域 Publication rollback 的连续窗口观察、legacy/canonical 生产对账、PostgreSQL 生产规模、CI Linux 实跑、旧链退役和 VPS release 仍未完成；继续保持不部署。

## 实施记录（2026-08-04，Qlib Runtime Config 与 Retention/Storage 任务收口）

本批次继续只做本地控制面和任务契约，不初始化生产配置、不执行真实删除、不部署、不 push。

已落地：

- Config Center `DEFAULT_RUNTIME_DEFINITIONS` 新增 10 个 typed `alpha.qlib.*` 定义，覆盖 enabled、provider URI、region、model path、universe、feature/label、训练/推理队列和自动激活开关；`runtime_config_contracts.json` 登记 owner、fallback、consumer、bootstrap 和测试证据。
- 新增 `get_active_qlib_runtime_config`：只有 active profile 与同版本 immutable snapshot 完整、类型正确时才返回配置；缺字段、错误类型或无环境时返回 `None`，由 owner 明确走兼容路径，不在 Config Center 里补默认值。Config Center summary 优先 typed snapshot，缺失时保留带来源的 SystemSettings compatibility。
- Retention 增加 `plan_retention_task`（固定 dry-run）、`enforce_retention_task`（非 dry-run 必须显式 `confirm=True`）、`verify_archive_manifest_task`（checksum/object_count/size 显式比对后才 mark verified）和 `verify_storage_budget_task`（healthy/partial/blocked/failed 标准 outcome）；旧 cleanup 入口统一经过 storage/policy/archive/hold/row-deadline gates，异常 fail closed。
- `VerifyArchiveManifestUseCase` 与 `ArchiveManifestRepository.get` 形成可注入的外部归档证据边界；Celery contract manifest 从 14 扩展到 18 个 governed tasks，并登记新增任务的边界/成功/部分/阻断/失败测试。

机器证据（本地）：

- Config Center targeted unit：29 passed；component Config Center：20 passed；`python scripts/check_runtime_config_coverage.py`：49 refs；相关 ruff/black/isort、Django check、makemigrations check 通过。
- `pytest tests/unit/data_center/test_retention_tasks.py tests/unit/data_center/test_retention_control_plane.py tests/unit/data_center/test_raw_landing.py -q --reuse-db --no-migrations --disable-warnings --maxfail=1`：29 passed；Retention 相关生产文件 mypy regression 0、ruff/black/isort 通过。
- `python scripts/check_celery_task_contracts.py`：18 tasks / 4 governed files；未将本地 task 结果写成生产调度或容量证据。

仍未完成及风险：

- Qlib 仍保留 SystemSettings compatibility fallback，尚未完成所有消费者的 typed snapshot 强制切读、旧 getter/fallback 删除和生产 profile 初始化；本地路径存在性只用于诊断，不代表 Qlib 数据新鲜或生产可用。
- Retention/Archive/Storage 任务尚未接入正式 beat 调度、真实 PostgreSQL/外部归档对象、容量水位故障注入和恢复演练；`enforce` 仍需运维审批/授权，不会自动删除生产数据。
- 全域 D0-D9 legacy/canonical 对账、PostgreSQL 生产 P95/WAL/锁/容量、备份恢复、CI Linux 实跑、旧链退役和 VPS release 仍未完成；继续保持不部署。

## 实施记录（2026-08-04，架构清单刷新与临时 PostgreSQL 探针）

本批次只刷新机器清单并尝试独立临时 PostgreSQL 证据，不接触现有服务容器、VPS 或生产数据。

机器证据：

- `python scripts/data_center_architecture_inventory.py --write` 后清单校验通过：`provider_imports_outside_data_center=0`、`cross_app_orm_imports=55`、`legacy_fact_references=143`、`current_surface_references=3046`、`data_write_task_decorators=55`、`runtime_parameter_references=49`、`external_http_imports_for_review=7`。这些是静态源代码计数，不是生产数据画像。
- Docker CLI 曾返回 `postgres:16`，独立临时容器 `agomtradepro-codex-pg-20260804` 在 `127.0.0.1:55432` 监听并通过 TCP 探针；随后 Docker API/迁移进程出现无输出阻塞，未取得可信的 migration/backfill/Retention PostgreSQL 结果，临时容器已移除。不得把这次 TCP 可达性当作 PostgreSQL 集成通过证据。

结论与风险：

- 本地 PostgreSQL 端到端证据仍缺：空库迁移完成、Publication/member、A-share backfill durable control plane、Retention/Archive round-trip、查询/P95/锁/WAL 结果均未取得可复核输出；CI workflow wiring 也不等于 GitHub Actions 实跑。
- 生产 PostgreSQL、备份恢复、容量/水位故障注入、连续观察窗口、旧链退役和 VPS release 继续保持阻断；后续必须在稳定、授权的 PostgreSQL runner 中重跑并保存完整日志/版本/连接信息。

## 实施记录（2026-08-04，Equity HTTP 旁路退役）

- 确认 `StockInfoRepositoryMixin.get_stock_info` 已完全使用 Data Center Asset/Fact repositories，删除未被调用的 Eastmoney metadata HTTP 方法、请求导入、URL/字段常量和 secid helper；新增静态测试阻断该旁路回流。
- 架构 inventory 刷新后 `external_http_imports_for_review` 从 7 降为 6；`provider_imports_outside_data_center` 仍为 0。其余 6 个 HTTP 入口仍需逐调用点审计，不能因本次删除一条死代码就宣称外部数据接入已全量中台化。
- 证据：`pytest tests/unit/test_equity_http_bypass.py -q`：1 passed；ruff/isort、mypy regression 0；既有 `tests/unit/test_equity_structure.py` 的历史 module-size budget 仍独立失败（`analysis_actions.py` 726 > 550），未通过放宽预算掩盖。

## 实施记录（2026-08-04，Equity Interface 边界与 MCP freshness 收口）

本批次只做本地接口边界和可靠性护栏，不部署、不 push、不连接 VPS、不删除旧表。

已落地：

- 将 `EquityAnalysisActionsMixin` 的技术/分时图和综合估值动作分别拆到 `chart_actions.py`、`comprehensive_valuation_actions.py`；将股票池刷新动作拆到 `pool_refresh_actions.py`，主 owner 文件保持在结构预算内。拆分保留 `analysis_actions`、`pool_actions` 的既有 use-case/gate monkeypatch 兼容面，避免只为体量治理破坏 API 测试。
- `governance/current_data_contracts.json` 与架构 inventory 同步记录新的 owner 文件/marker；当前静态清单为 `provider_imports_outside_data_center=0`、`cross_app_orm_imports=55`、`legacy_fact_references=143`、`current_surface_references=3046`、`data_write_task_decorators=55`、`runtime_parameter_references=49`、`external_http_imports_for_review=6`。
- MCP equity research snapshot 在顶层或嵌套 `contract/publication/reliability` 元数据出现 `stale/blocked/missing/failed/unverified` 等不可用状态时统一 fail closed；不再因缺少 `must_not_use_for_decision` 布尔字段而把旧分区标成 fresh。完全没有可靠性元数据的响应仍由 Data Center Publication/query gate 负责，MCP 不自行猜测行日期。

机器证据：

- `pytest tests/unit/test_equity_structure.py -q`：4 passed；模块非空行数为 `analysis_actions=527`、`chart_actions=69`、`comprehensive_valuation_actions=117`、`pool_actions=245`、`pool_refresh_actions=124`。
- `pytest tests/api/test_equity_api_edges.py -q -k "published_valuation_calculators_block_stale_publication_before_use_case or published_reads_block_without_member_snapshot or refresh_pool_preserves_existing_pool"`：7 passed。
- `pytest sdk/tests/test_mcp/test_equity_research_snapshot_registry.py -q`：8 passed；`python scripts/check_current_data_contracts.py`：36 surfaces；ruff/black/isort 通过。

未完成及风险：

- 本批只修复 owner 边界和入口级 fail-closed 语义，不代表 D0-D9 全量消费者已经切换到 Publication-only，也不代表剩余 6 个外部 HTTP 入口已经完成逐调用点审计。
- PostgreSQL 生产画像/P95/锁/WAL、备份恢复、Retention/Archive 实跑、CI Linux 实际 nodeid、连续观察窗口、旧链退役和 VPS release 仍未完成；按用户约束继续不部署。

## 实施记录（2026-08-04，CI 回归契约收口）

本批次响应新 SHA 的 GitHub Actions 结果，只修复可归因、可本地验证的回归；不把全域 module-cycle 债务改成 allowlist，不部署、不连接 VPS。

已落地：

- MCP `equity.read.pool_catalog` fallback 改为直接调用 SDK `get_stock_pool_payload`，保留 `mode/publication_key`，使 read-evidence guard 能识别真实 SDK 调用；同步补充 SDK publication 参数契约测试。
- 财务源 gateway 测试更新为当前可靠性语义：NaN、Infinity、非法和缺失值保持 `None`，稀疏 FinancialFact 不再断言为零；同步命令测试改为 canonical `list_active_stock_codes` 与 `FinancialFactRepository.bulk_upsert`，移除已退役的 `StockInfoModel`/`FinancialDataModel` patch。
- Data Center Application 查询/同步 owner 进一步拆分：`price_query_use_cases.py` 与 `sync_news_capital_use_cases.py`，并把新 owner 登记到结构预算测试；TUI Config Center 测试显式 stub typed runtime profile/StorageBudget，并断言新增 P0 治理行。

本批本地证据：

- `python scripts/check_mcp_read_evidence.py`：199 个 read-like manifest、187 个 SDK contract 通过；MCP/SDK 定向 32 passed。
- 财务 gateway/同步命令：20 passed；Data Center use-case structure 与 TUI operator：9 passed；Data Center sync/news failure matrix：18 passed。
- 生产变更文件 ruff/black/isort/mypy regression 通过（mypy 0 regression）。

CI 观察结论：

- Security Scan 已通过；上一轮 Consistency 的 MCP read-evidence 失败已在本批本地复现并修复。
- Architecture Layer Guard 仍因更早批次形成的真实跨 App 依赖债务失败：`alpha ↔ data_center`、`config_center ↔ data_center`、`data_center ↔ equity/fund`，以及 `data_center` 反向调用业务 query service。该问题不能靠放宽 `governance/module_cycle_allowlist.json` 掩盖，需另开依赖收口批次。
- CI Fast Feedback 还需在新 SHA 上重跑；在 module-cycle、PostgreSQL/CI 实际 nodeid、生产数据画像、备份恢复和旧链退役未通过前，VPS 仍不可部署。

## 实施记录（2026-08-04，Module-cycle 依赖债务清零）

本批次按真实 import 证据拆除全部四个双向边，不修改 allowlist 来掩盖循环：

- Alpha price coverage command 归属迁至 `apps/alpha/management/commands`；同步服务仍由 Data Center infrastructure 持有，但 Alpha cache 读取改走既有 `core.integration.alpha_cache` app-neutral bridge，避免 Data Center 直接依赖 Alpha。
- Asset-master backfill 的 legacy business source 读取改成显式 `AssetMasterSourceProvider`，由 `core.integration.asset_master_sources` 在 composition boundary 组装；Data Center service 默认不再 import `asset_analysis/equity/fund/rotation`。
- Config Center ↔ Data Center 通过 `core.integration.config_center_runtime`、`core.integration.data_center_readiness` Protocol/registry 和 Data Center read facade 解耦；runtime settings、storage pressure、macro failover、decision readiness 均不再直接跨 App import。
- `governance/module_cycle_allowlist.json` 更新为实际清零后的精确 v18 基线，未加入任何 allowed pair/cycle。

机器证据：

- `python scripts/check_module_cycles.py --allowlist-file governance/module_cycle_allowlist.json --fail-on-cycles --format text`：`edge_count=200`、`bidirectional_pairs=0`、`cycle_components=0`、预算/stale/allowlist 全 0。
- `python scripts/verify_architecture.py --include-audit --format text`：boundary 0、audit 0；module-cycle guard 测试 1 passed。
- Alpha coverage/asset backfill/management boundary：12 passed；cross-app read ports、macro failover、decision readiness：20 passed；Config/Data 相关补充回归与消费者回归已通过。

这次修复解决的是静态依赖债务，不等于 PostgreSQL 生产画像、备份恢复、VPS 观察窗口或旧链删除已经完成；后续仍受生产硬门禁约束。

## 实施记录（2026-08-04，生产切换前置审计与备份证据）

本批次按“先备份、再审计、后切换”的生产硬门禁执行；未停旧写、未切读、未删除旧表或旧适配器。

已取得证据：

- `scripts/backup-vps-postgres.ps1 -DownloadLatest` 成功下载并校验远端最新 PostgreSQL custom-format 归档：`118099931` bytes，SHA-256 为 `6233245c8c6b246200f32fb5296bf9de3724bbb9baa9b603e94c03ebfb8d5d42`；远端 `pg_restore --list` 通过。备份客户端增加 SFTP prefetch，保留尺寸和 SHA-256 双重校验。
- VPS 容器状态、PostgreSQL/Redis/Celery 健康；`python manage.py check --deploy` 通过。
- 远端 `audit_macro_fact_consistency --strict`：`indicator_count=63`、`fact_count=29147`、`canonical_legacy_conflict_count=529`、`cross_source_conflict_count=1`；未治理冲突和配置源缺失均为 0，但 canonical/legacy 差异尚未清零。
- 远端 active A-share coverage（5,533 assets）显示：price `fresh=5504/sparse=26/stale=3`；valuation `fresh=415/sparse=5118`；financial `fresh=5533`；quote `sparse=5533`。这不是全量消费者切换所需的 fresh/complete 证据。

切换结论：

- 当前不能停旧写、强制全量 Publication-only 切读或删除旧链：估值/报价覆盖不足，且 shadow reconciliation、PostgreSQL P95/锁/WAL、连续观察窗口和 rollback drill 仍未完成。
- `ready` 的核心探针只证明当前决策样本可用，不等于 D0-D9 全量生产数据就绪；Alpha workspace 仍报告滞后 warning。
- 下一阶段必须先完成 D0-D9 覆盖回填与 legacy/canonical 对账，保存至少行情 3 个交易日+周末、宏观 2 个调度周期的观察证据，再执行停旧写、切读和 M9 清理。

## 实施记录（2026-08-15，DATA-01 backup evidence refresh）

生产 PostgreSQL 备份按当前运维脚本重新取得并验证：`scripts/backup-vps-postgres.ps1` 成功完成远端 custom-format 归档、`pg_restore --list`、原子下载和本地 SHA-256 校验。归档为 `/opt/agomtradepro/backups/database/postgres-20260815T030811Z.dump`，本地副本为 `backups/vps-postgres/postgres-20260815T030811Z.dump`，大小 `139057048` bytes，SHA-256 为 `a8f005eb3a461f28d21689ecef6d5aee89b59a353d06944b79e08c82662839cc`。

这只刷新了 DATA-01 的 backup evidence，不代表生产恢复、维护态/回滚演练或 Data Center canonical 切换已通过。下一项可在不连接生产、不改变 registry 状态的前提下做 DATA-02 software-preflight：使用一次性本地 PostgreSQL 与 fake provider 跑真实回填控制面编排，核对 `run_id/batch_id/checkpoint/outcome` 和重试幂等；生产回填、全量 coverage、legacy reconciliation 与 M9/M10 仍保持锁定。

## 实施记录（2026-08-15，DATA-02 control-plane PostgreSQL preflight contract）

为 DATA-02 补充了 PostgreSQL-only 的控制面预演用例，仍复用真实回填任务、composition repository 和三张 `SyncRun`/`SyncBatch`/`SyncCheckpoint` 表；fake provider 只作为测试输入，不写入生产或 registry：

- 首次成功批次与相同参数重试必须保持一组稳定的 `run_id/batch_id/checkpoint`，不产生第二批次。
- 单一 price provider 失败必须持久化 `partial`，并保持 `requested/succeeded/failed/stored`、错误列表和 checkpoint 状态一致。
- 本机默认 SQLite 仅作结构性回归：`python -m pytest tests/component/data_center/test_core_data_backfill_control_plane.py -q --confcutdir=tests/component/data_center --no-migrations --reuse-db` 得到 `1 passed, 2 skipped`；新增用例因非 PostgreSQL 明确跳过。回填任务单元回归 `python -m pytest tests/unit/data_center/test_core_data_backfill_task.py -q --confcutdir=tests/unit` 得到 `8 passed`。
- PostgreSQL-only 用例尚未在本机或生产运行；它们需要 CI 的一次性 PostgreSQL 服务，不能把 SQLite skip 当成并发、锁、真实 PostgreSQL 事务或生产回填证据。

因此这只是 DATA-02 的 software-preflight contract，不改变 `DATA-01=awaiting`、`DATA-02=waiting`，不解锁生产回填、legacy/canonical reconciliation、coverage、M9/M10 或任何破坏性操作。

## 实施记录（2026-08-04，Tushare 不可用时的 AKShare 回填验证）

本批次不修改旧链、不伪造估值；在已验证 PostgreSQL 备份之后，使用同一套可恢复的核心 A 股回填入口显式指定 `source=akshare`，验证暂时不依赖 Tushare 时系统仍能运行。

已取得证据：

- 本地和 VPS 的 Tushare Relay 探针均返回 HTTP 403 `invalid_api_key`；VPS 数据库中的 Tushare provider 已是 `unified_relay`、目标地址正确，故本批次不再重试无效授权。
- `docker exec agomtradepro-web-1 python manage.py backfill_active_a_share_core_data --batch-size 20 --max-batches 5 --source akshare --history-days 756 --financial-periods 8` 通过；处理 offset `0→100`（首个 20 条为前一轮的幂等重跑），5 个 batch 均为 `outcome=success`，每批 quote/valuation/price/financial 均 `failed=0`、`succeeded=20`、估值 `stored=20`。
- 各批写入计数合计：估值至少 100 条、行情快照 100 条、历史价格约 50,000 条、财务事实约 7,995 条；系统返回 `checkpoint.next_offset=100`，可从该 offset 继续。
- 样本 `000001.SZ` 的最新估值 `val_date=2026-08-04`，保留有效 PE/PB/市值，来源链路为 AKShare 的 Tencent fallback；没有用请求时间覆盖观测日期。
- 回填控制面未报告 `partial/failed/blocked`，未发现零产出成功；AKShare 适配器日志显示东方财富失败时继续降级腾讯并成功返回历史数据。
- VPS on-demand `ensure_valuations("000404.SZ", 2025-08-04..2026-08-04)` 从稀疏覆盖补水为 `status=fresh`、`points_count=368`、`coverage_end=2026-08-04`、`hydrated=true`；质量证据保留 `errors=["tushare: no records"]`，最终返回源为 AKShare/Tencent fallback。
- 本地护栏复核通过：`check_data_center_legacy_fact_access.py`；`check_current_data_contracts.py`（36 surfaces）；`check_celery_task_contracts.py`（18 tasks / 4 governed files）；`verify_architecture.py --include-audit`（boundary 0、audit 0）。

仍未完成：

- 这只是受控回填进度，不代表 5,533 个资产已经覆盖完成；此前覆盖审计仍显示 valuation `fresh=415/sparse=5118`、quote `sparse=5533`，需要从 offset 100 继续并重新采集覆盖证据。
- Tushare provider 尚未从生产配置删除；本批次只绕过 Tushare，不执行全量切读、停旧写、观察窗口或旧表清理。Publication-only、shadow reconciliation、PostgreSQL 性能/恢复和 M9/M10 门禁仍保持未通过。

## 实施记录（2026-08-04，VPS M0 容量画像）

本批次只读采集生产容量证据，不运行清理或 Docker prune。

- VPS 根文件系统 `145G total / 48G used / 97G available (34%)`；Docker images `11.86GB`（7 images，约 `9.08GB` 可回收），build cache `5.708GB`，Redis `5.65MB` / `256MB maxmemory`。
- PostgreSQL 数据库当前约 `1,377MB`；最大关系为 `data_center_price_bar 824MB`、`data_center_financial_fact 173MB`、`task_monitor_taskexecutionmodel 129MB`、`policy_log 72MB`、`data_center_valuation_fact 55MB`。
- Web 容器 `/app/backups/database` 仍有 `58` 个备份文件、约 `2,943,396,798` bytes；这违反“VPS 最多一个 in-flight/不超过 24 小时”的目标，但由于尚未逐份完成外部校验，当前只登记风险，不删除任何文件。
- 该画像补足 M0 的磁盘、PostgreSQL、Docker、Redis 和备份基线；仍缺 WAL/TOAST/索引锁预算、按 Dataset 增长预测、外部隔离恢复和 retention 故障注入。

## 实施记录（2026-08-04，AKShare 核心回填进度与估值口径拆分）

- 继续从 durable checkpoint 执行 `source=akshare` 回填，已验证 offset `0→400 / 5533`（offset 340 的 partial 已单独重试成功）；当前 PostgreSQL 中 `val_date=2026-08-04` 的估值快照覆盖为 440 个资产，未出现零产出成功。
- 直接 PostgreSQL 计数显示 `data_center_valuation_fact` 有 5,536 个资产记录；`val_date >= 2026-08-03` 的当前估值覆盖为 440 个资产，来源包括 `akshare` 和其腾讯 fallback。`000404.SZ` on-demand 已补到 2026-08-04 并保持 fresh。
- active coverage 审计（lookback 365）为 price `fresh=5504/sparse=26/stale=3`、valuation `fresh=416/sparse=5117`、financial `fresh=5533`、quote `sparse=5533`。这说明“当前估值快照覆盖”和“365 天估值历史覆盖”是两个不同门槛；AKShare/Tencent 能补当前值，但不能据此宣称全市场日频估值历史已经完整。
- 估值历史口径仍 fail-closed：不能把单日当前快照重复包装成 365 天历史，也不能用旧值覆盖观测日期。后续若要关闭历史估值缺口，需要可授权的 Tushare 官方 IP 或其他具备历史估值契约的 Provider，并完成跨源对账。

## 实施记录（2026-08-04，partial checkpoint 不跳过失败资产）

- offset `300→400` 回填中出现一次真实 `outcome=partial`：`000903.SZ` 财务同步失败，其他 19 个资产成功。旧管理命令会继续把 offset 推到 400，存在跳过失败资产的风险。
- 修复管理命令：`outcome=partial` 与 `failed/blocked` 一样立即停止，保留当前 batch 的 `checkpoint.offset` 供重试；新增回归测试，相关 task/command 9 tests passed，ruff/mypy regression 通过。提交：`bd5a74ca`。
- 在生产旧命令下从 offset 340 手动重试该 batch 已成功（20/20，`failed=0`），当前可安全从 offset 360 继续；本地修复尚未部署 VPS。

## 实施记录（2026-08-04，VPS 版本漂移阻断）

- VPS `showmigrations data_center --plan` 当前只到 `0049_quotesnapshot_fetched_at`；本地 canonical 控制面要求的 `0050`–`0057`（Publication/Coverage、Raw/Schema、Retention/Archive、Dataset Contract、Reconciliation、Rollback）尚未部署或迁移。
- 因此 VPS PostgreSQL 不存在 `data_center_sync_run`、`data_center_sync_batch`、`data_center_sync_checkpoint`；生产旧镜像上回填命令的 checkpoint 不能作为本地 durable control-plane 证据。
- 本轮已终止由 SSH 读超时遗留的 offset 380/400/420/440 回填进程，并复核 web 容器内无 `backfill_active_a_share_core_data` 进程；未执行删除、prune 或破坏性迁移。
- 生产切换前必须先部署包含 0050–0057 的镜像并完成 PostgreSQL 迁移/回滚演练，再用修复后的 partial-stop command 继续回填；在此之前不再在旧镜像上启动长批任务。
- `scripts/deploy_vps_verify.py` 新增 canonical schema gate，要求 0050–0057 引入的 Publication/Coverage、Sync/Quarantine、Raw/Schema、Retention/Archive、Dataset Contract/Binding/Policy、Reconciliation、Rollback 表全部存在，并要求 `django_migrations` 已记录 `0057_publicationrollbackmodel`；本地 verifier 21 tests passed，VPS 只读探针以 exit=1 列出缺失项。提交前不允许把旧镜像判为可切换。

## 实施记录（2026-08-04，本地 canonical schema 尾部迁移）

- 核对本地默认数据库为 SQLite；`data_center` 原先只应用到 0055，代码所需的 0056 `RetentionRunModel` 与 0057 `PublicationRollbackModel` 尚未落库。
- 只在本地执行 `python manage.py migrate data_center --noinput`，0056/0057 均成功；随后 `showmigrations` 显示 0050–0057 全部 `[X]`，canonical schema 19 张控制面/目录表 `missing=[]`。
- `python manage.py check` 与 `python manage.py makemigrations --check --dry-run` 均通过。该证据不代表 VPS 已迁移，也不授权生产写入。

## 实施记录（2026-08-04，部署入口统一 canonical schema gate）

- 将 0050–0057 的 19 张控制面/目录表和 `0057_publicationrollbackmodel` marker 收敛到 `apps/data_center/infrastructure/canonical_schema_contract.py`；新增 `manage.py verify_canonical_schema --json` 作为部署期唯一 schema 检查入口。
- `remote_build_deploy_vps.py` 与 legacy `deploy-on-vps.sh` 均在迁移后、`check --deploy` 前执行该命令；旧镜像、手工建表但未登记 migration 的数据库都会 fail closed。
- 回归证据：canonical contract/deploy verifier/remote deploy 共 37 tests passed；ruff、mypy regression 通过；本地命令输出 `ok=true, missing_tables=[], missing_migrations=[]`。

## 实施记录（2026-08-04，Celery manifest 实际 nodeid 执行）

- 新增 `scripts/run_celery_task_contract_tests.py`，从 `governance/celery_task_contracts.json` 解析每个任务的 required case，解析嵌套 pytest class 并执行去重后的真实 nodeid；manifest 违规时先拒绝运行。
- `.github/workflows/nightly-tests.yml` 在 PostgreSQL 准备后执行该 runner；静态 `check_celery_task_contracts.py` 不再是唯一证据。
- 本地实际执行 54 个登记 nodeid，结果 `56 passed in 2.91s`（参数化用例展开）；runner 单测、ruff 和 manifest guard 均通过。

## 实施记录（2026-08-04，宏观 shadow audit 自然键修复）

- 修复 `audit_macro_fact_consistency`：canonical/legacy revision 与跨源序列现在按 `source + period_type + reporting_period` 分组；同一日期的日频与月频事实不再被错误比较。跨源冲突示例同时输出 `period_type`，避免把不同频率当成同一序列。
- 新增回归用例覆盖同 source、同日期、不同 `period_type` 的事实；本地该组件 15 tests passed，ruff 与 mypy regression 通过。提交：`e2dda7e6`。
- 该修复尚未部署 VPS；生产现有 529 条 canonical/legacy conflict 仍需在新代码部署后重采并区分剩余真实差异，不能直接把旧计数视为修复完成。

## 实施记录（2026-08-04，AKShare-only on-demand 回归）

- 新增 `test_ensure_valuations_hydrates_from_akshare_when_tushare_is_inactive`，验证没有 active Tushare provider 时 on-demand 估值同步会跳过 Tushare、继续调用 AKShare，并保留 `tushare: provider not active` 作为可审计错误，不把降级结果包装成无来源成功。
- `pytest tests/unit/test_data_center_on_demand.py -q --no-migrations --timeout=60`：7 passed。
- 该证据只证明本地 AKShare-only 降级语义；不改变当前 provider 配置，也不替代 VPS canonical migration、全量覆盖或生产切换门禁。

## 实施记录（2026-08-04，AKShare failover binding 补齐）

本批次只补齐运行时 Dataset Catalog 的无 Tushare failover 声明，不切换本地或生产 Provider，不部署、不 push。

已落地：

- `equity.price.bar`、`equity.financial.fact`、`equity.valuation.fact` 在 `governance/provider_bindings.json` 增加 AKShare 二级 binding；各 binding 复用对应 Dataset Contract 的 freshness/validator，不降低 Publication/available-at 门禁。
- Catalog runtime bootstrap/verification 现在稳定报告 `bindings=15`；回归断言三个关键 D4/D5/行情数据集均存在 AKShare fallback，避免“适配器支持但治理路由未登记”的配置漂移。

机器证据（本地）：

- `pytest tests/unit/data_center/test_catalog_runtime.py tests/unit/test_data_center_catalog_contracts.py -q --no-migrations --reuse-db`：5 passed。
- `python scripts/check_data_center_catalog_contracts.py`：`validated=10 datasets`。
- `python manage.py initialize_data_center_catalog` 与 `python scripts/check_data_center_runtime_catalog.py`：`contracts=10, bindings=15, owners=10`。

仍未完成及风险：

- 这是路由/治理声明和本地 Catalog round-trip，不代表 AKShare 对全市场历史财务/估值的覆盖已达生产门槛；当前真实覆盖缺口、publication writer/backfill、PostgreSQL 生产证据、观察窗口和 VPS release 仍保持未完成。
- 本地运行库的 Tushare provider 仍为 active；如需临时无 Tushare 运行，应通过受控配置停用 Tushare 并显式验证 AKShare 产出，不能直接编辑治理 JSON 代替运行时切换。

## 实施记录（2026-08-04，macro Publication key 与查询端口对齐）

本批次修复一个会让宏观同步“已写入但当前查询找不到”的发布键错配；不部署、不 push、不触碰生产数据。

已落地：

- `SyncMacroUseCase` 发布 `macro.fact` 时显式使用 `indicator_code` 作为 `publication_key`；宏观 published Query Port 默认也按 `indicator_code` 查找，写入与读取现在使用同一 Publication scope。
- 回归测试捕获同步调用的 `publication_key`，防止后续恢复通用 `current` 默认值而再次造成空/阻断的当前宏观读。

机器证据（本地）：

- `pytest tests/unit/data_center/test_macro_publication_sync.py -q --no-migrations --reuse-db`：5 passed。
- 变更文件 ruff、mypy regression 通过；该修复不改变 historical/PIT 查询语义。

仍未完成及风险：

- 生产已有宏观 Publication 需要在新代码部署后重采/核对；本地单元测试不能证明 VPS 的旧 Publication key 已迁移。

## 实施记录（2026-08-04，Agent Runtime 宏观 freshness 旁路收口）

本批次修复 Agent Runtime 运维/上下文摘要仍从“最新 canonical fact”读取宏观时间、绕过 Publication freshness gate 的旁路；不部署、不 push。

已落地：

- 新增 `list_latest_published_macro_indicator_payloads` / `list_latest_published_macro_values` Public Port：先以 active Indicator Catalog 有界发现指标，再逐项复用宏观 Publication/member/freshness gate；未发布、过期、空成员或空 rows 不进入当前摘要。
- `DjangoContextSnapshotRepository.fetch_data_freshness_summary` 改用 published macro port；无可用发布证据时报告 `macro=unavailable`/degraded，而不是把旧事实日期包装成健康。
- current-data contract 登记 Agent Runtime source/marker 与精确回归，防止后续重新调用 legacy cache-warmup port。

机器证据（本地）：

- Data Center published/query、Agent Runtime context safety：36 passed；组件 context snapshot：2 passed。
- `python scripts/check_current_data_contracts.py`：36 surfaces；current-data runner 收集 199 个登记 nodeid、238 个测试项并全部通过（在干净 detached worktree 执行）。
- 变更文件 ruff、mypy regression、architecture/audit 通过；未改变 historical/PIT 宏观端口。
- 架构 inventory 刷新通过：`provider_imports_outside_data_center=0`、`cross_app_orm_imports=55`、`legacy_fact_references=143`、`current_surface_references=3051`；该清单仍是静态源代码盘点，不替代生产数据画像。

仍未完成及风险：

- Agent Runtime 其它 regime/policy/portfolio 运维摘要属于业务状态，不是外部事实 Publication；生产 PostgreSQL publication/member 数据、观察窗口、全入口快照和 VPS release 仍未验证。

## 实施记录（2026-08-04，宏观 scalar Public Port 旁路清理）

本批次继续清理“名字含 latest 但直接读事实表”的兼容端口；不部署、不 push。

已落地：

- `get_latest_macro_indicator_value` 不再调用裸 `MacroFactRepository.get_latest`，改为复用 `query_published_macro_fact_series`，Publication 缺失、stale、memberless 或非有限值统一返回 `None`。
- current-data contract 新增 scalar port marker/test，锁定公共兼容入口也不能绕过 Publication gate。

机器证据（本地）：

- 目标文件 ruff、`check_mypy_regression.py`、`py_compile` 通过；宏观 published/query 回归已扩展。
- 当前工作区另有未提交的 Strategy/Risk Center 改动存在语法错误（`apps/strategy/infrastructure/models.py:635`），导致全局 current-data checker/pytest setup 暂时不能在该脏工作区复跑；该外部改动未被本批次触碰或提交。

仍未完成及风险：

- 需要在工作区其它未提交改动恢复可解析后重跑本端到端 pytest/current-data runner；生产 Publication 数据、观察窗口和 VPS release 仍未验证。

## 实施记录（2026-08-04，TUI Provider 启用状态切换）

本批次补齐无 Tushare 运行所需的用户面切换入口；不修改当前运行库状态、不部署、不 push。

已落地：

- TUI Data Center 的 `provider-update` 动作新增布尔 `is_active` 字段；管理员可以停用 Tushare，让已登记的 AKShare/QMT 等来源继续参与 failover，若无可用来源则由既有 gate 阻断。
- 操作说明明确停用语义，不展示密钥或实现细节；既有 Provider API 已支持该字段，TUI 不再只能改密钥/优先级而无法安全停用来源。

机器证据（本地）：

- `pytest tests/unit/terminal/test_tui_data_center_tushare_config.py -q`：3 passed；TUI metadata 变更 ruff 通过。

仍未完成及风险：

- 当前本地数据库的 Tushare Provider 仍保持 active；本批次只补齐可审计的切换入口，没有替用户改变本地或 VPS 配置。

## 1. 结论先行

当前系统的四层架构方向没有错，真正需要从根上重构的是“数据所有权、可靠性契约和发布链路”。

现有 Data Center 已经具备 Provider 配置、主数据、事实表、同步、查询、健康度、Raw Audit 等骨架，但系统仍允许以下情况同时存在：

1. Data Center 事实表与 macro、equity 等旧事实表并行，业务代码可以任选一套读取。
2. Data Center 的 Provider Adapter 仍通过 core/integration/data_center_business_sources.py 反向调用业务模块能力，数据所有权名义上在中台，实际仍散落在业务 App。
3. shared/domain/reliability.py 已定义 ReliabilityContract，但多数数据实体和查询响应没有把它作为不可分割的类型契约，可靠性仍常以松散 dict 字段追加。
4. 缺失值在若干财务、估值和行情适配链路中被转换为 0.0，导致“未知”被伪造成“真实零值”。
5. Provider Registry 当前主要以“未抛异常、非 None、非空列表”判断成功，尚未把 freshness、字段语义、单位、覆盖率和跨源冲突作为统一的接受条件。
6. 同步任务可以在 stored_count=0 时返回 status=success，而健康度记录器又把零产出记为 degraded；任务结果和健康状态存在双重语义。
7. REST、SDK、MCP、Terminal、Agent Runtime 和业务聚合层仍可能分别拼装 current/latest 语义，导致同一事实在不同入口得到不同可靠性结论。
8. 现有 CI 治理已经登记 25 个 current-data contract 和 13 个关键 Celery task，但登记与标记扫描不能替代自动发现、真实 nodeid 执行和 PostgreSQL 全链路验证。

因此，本计划不再把问题定义为“补几个数据源或修几个 stale 判断”，而是执行一次数据架构再收口：

- Data Center 是外部事实数据生命周期的唯一 owner。
- 业务 App 不再持久化或直接抓取同一类外部事实。
- 所有可用于决策的数据必须先经过版本化 Dataset Contract、标准化、质量门、跨源仲裁和发布。
- 业务 App 只通过 Data Center Application 层的类型化查询端口获取输入。
- 账户、订单、持仓、策略配置、领域决策结果仍归原业务 App，不迁入 Data Center。

## 2. “所有数据走数据中台”的精确定义

“所有数据”不能被误解为“把系统全部 Django Model 都搬到一个 App”。本计划采用以下所有权边界。

| 数据类别 | 所有权 | 是否必须经过 Data Center | 说明 |
| --- | --- | --- | --- |
| 外部 Provider 原始响应 | Data Center | 是 | 统一抓取、脱敏、哈希、审计和保留策略 |
| 证券、基金、指数、指标、发布方等主数据 | Data Center | 是 | 唯一代码、别名、单位、日历和语义目录 |
| 宏观、行情、净值、财务、估值、板块、新闻、资金流事实 | Data Center | 是 | 唯一标准事实存储和发布入口 |
| 跨 App 复用的外部衍生事实 | Data Center | 是 | 必须登记 dataset_key、来源输入、算法版本和 lineage |
| Regime、Pulse、Alpha、估值结论、策略信号 | 对应业务 App | 输入必须经过 | 领域算法和结果仍由业务 owner 管理；输入证据必须来自中台 |
| 账户、组合、持仓、订单、成交、审计流水 | account / portfolio / broker_execution / audit | 否 | 属于用户与交易领域，不是市场数据中台事实 |
| 运行时配置、权限、Prompt、Agent 会话 | 对应 owner App | 否 | 不纳入数据事实中台 |
| 面向 SDK/MCP/TUI 的事实响应 | Data Center 或业务聚合 App | 底层事实必须经过 | 不允许入口自行查旧表、直连 Provider 或重算 freshness |

硬规则：

- 任何业务计算只要依赖宏观、市场、证券、财务、估值、新闻或资金流输入，就必须通过 Data Center Application Query Port。
- 任何跨 App 复用的派生数据集必须登记 Data Product Contract；不得靠另一个 App 直接 import 其 ORM Model。
- Data Center 不接管领域决策逻辑，也不得 import 业务 App 的 infrastructure。
- shared 只保留无业务语义的技术组件；不得继续作为外部数据 SDK 的隐形入口。

## 3. 与现有计划的关系

本计划不是重复造中台，而是对“中台已完成”的第二阶段纠偏和最终验收。

| 文档 | 本计划与其关系 |
| --- | --- |
| [data-mid-plat-260405.md](../archive/plans/data-mid-plat-260405.md) | 归档为第一阶段建设历史；其中“Phase 1-6 已完成”只代表骨架和主要入口曾完成迁移，不再作为唯一真源验收证据 |
| [production-data-reliability-full-remediation-2026-08-01.md](production-data-reliability-full-remediation-2026-08-01.md) | 继续承担生产事故 P0/P1/P2 整改；其维护阻断、时间保真、全市场回填和无证据阻断是本计划的前置安全底座 |
| [provider-abstraction-convergence-2026-07-18.md](../archive/plans/provider-abstraction-convergence-2026-07-18.md) | Provider 抽象治理并入本计划 M2，不再只以文件拆分或协议存在作为完成标准 |
| [critical-reliability-test-closure-2026-07-22.md](critical-reliability-test-closure-2026-07-22.md) | 测试分层与 PostgreSQL 验收并入 M0、M9、M10 |
| [data-freshness-contract-guard.md](../development/data-freshness-contract-guard.md) | 作为 current/latest/realtime 语义的最低要求，本计划会把它扩展到所有 Dataset Contract |
| [celery-task-contract-guard.md](../development/celery-task-contract-guard.md) | 作为批量写入任务的最低要求，本计划会增加同步运行、批次、断点和发布状态 |

若本计划与早期“已完成”描述冲突，以本计划的机器清单、退出条件和生产证据为准；不回写历史文档来掩盖曾经的架构状态。

## 4. 当前基线与根因

### 4.1 已确认的结构性问题

| 编号 | 当前证据 | 根因 | 风险 |
| --- | --- | --- | --- |
| B1 | apps/agent_runtime/infrastructure/context_snapshot_repository.py 仍读取 apps/macro/infrastructure/models.py 的 MacroIndicator | 宏观事实存在双真源 | Agent Runtime 与 Data Center 可看到不同“最新宏观数据” |
| B2 | apps/alpha/infrastructure/adapters/simple_adapter.py 和 apps/alpha/infrastructure/repositories.py 仍读取 equity.ValuationModel / FinancialDataModel | Alpha 直接依赖旧事实表 | 估值、财务的日期、单位和 freshness 无法统一 |
| B3 | apps/equity/infrastructure/fundamentals_repository.py 同时支持 Data Center 与旧 equity 模型，并把多项缺失值写成 0.0 | 兼容层长期化，数据类型没有表达 missing | 缺失值进入排序、筛选和估值后被当作真实低值 |
| B4 | core/integration/data_center_business_sources.py 被 Data Center Application/Infrastructure 调用 | 依赖倒置失败 | Data Center 名义拥有 Provider，实际反向依赖业务实现 |
| B5 | shared/infrastructure/tushare_client.py 仍直接 import tushare | 外部 SDK 入口没有完全归一 | 静态约束存在例外，未来可再次绕过中台 |
| B6 | ProviderRegistry.call_with_failover 只校验 None/空列表 | Fetch Result 没有标准证据与接受策略 | 旧值、错单位、错字段但非空时会截断 failover |
| B7 | sync_use_cases.py 多个域在 stored_count=0 时返回 success | Outcome 不是一等类型 | Task Monitor、告警与运维判断可能互相矛盾 |
| B8 | FinancialFact、ValuationFact、PriceBar 等表的证据字段不统一 | 事实表在不同阶段独立演化 | 无法做统一 lineage、质量门和跨域 readiness |
| B9 | ReliabilityContract 主要只在 config_center 被显式采用 | 可靠性是外围元数据，不是数据载体的一部分 | 序列化、缓存或聚合时容易丢失和洗白 |
| B10 | current-data 与 Celery guard 主要验证登记、源码标记和函数存在 | 静态治理与真实执行脱节 | 清单可以绿，但声明的行为不一定在 CI 中被执行 |

### 4.2 语义事故说明了什么

Data Center 近期迁移 0041、0044、0045、0047 曾修正以下类别的问题：

- 家庭储蓄子集被错误标记为人民币存款。
- 商品、外汇代理指标语义不匹配。
- 解析失败被制造为 0% 失业率。
- 发电量、用电量、钢铁开工率和航运指数代理关系混淆。

这些不是单纯 Parser Bug，而是上游 endpoint、字段、单位、频率、经济含义和替代关系没有被版本化契约约束。修完某个字段但不建立 Dataset Contract，同类问题还会换一个 Provider 或指标再次出现。

### 4.3 执行前必须重采的机器基线

以下数字只作为 2026-08-02 的初始观察，M0 必须用脚本重新生成并入库为证据：

- governance/current_data_contracts.json 当前登记 25 个 current-data surface。
- governance/celery_task_contracts.json 当前登记 13 个关键任务，覆盖 4 个 source file。
- 文本扫描至少发现 1 个 Data Center 之外的外部数据 SDK 入口：shared/infrastructure/tushare_client.py。
- 已确认 Macro、Financial、Valuation、StockDaily 存在仍被业务代码使用的遗留表。
- 2026-08-01 生产整改计划记录的核心覆盖率约 5.7% 只是事故时点基线，不能直接作为本计划开工时的现状。

M0 生成的基线至少包括：

1. 外部 SDK import 清单。
2. 业务 App 对 Data Center Application 的依赖清单。
3. 所有跨 App ORM 读取清单。
4. 所有 legacy fact table 的读写调用点。
5. 所有 current/latest/realtime/summary surface。
6. 所有数据写入型 Celery task、命令、beat schedule 和启动脚本。
7. 每个 canonical dataset 的行数、自然键重复数、覆盖率、最新观测时间、最早观测时间、source 分布和质量分布。

## 5. 目标架构

### 5.1 总体数据流

~~~mermaid
flowchart LR
    subgraph P["外部 Provider"]
        P1["Tushare"]
        P2["AKShare"]
        P3["EastMoney"]
        P4["QMT"]
        P5["其他受管来源"]
    end

    subgraph DC["Data Center 数据面"]
        A["Provider Adapter"]
        R["Raw Landing 与请求审计"]
        C["Dataset Contract 校验"]
        Q["Quarantine 与质量问题"]
        N["标准化与单位转换"]
        X["跨源对账与仲裁"]
        F["类型化事实表"]
        U["Canonical Publication"]
        V["版本化 Read Model"]
        G["Application Query Ports"]
    end

    subgraph CP["Data Center 控制面"]
        D["Dataset Catalog"]
        B["Provider Binding"]
        S["Sync Run / Batch / Checkpoint"]
        H["能力级健康与 SLO"]
        E["Schedule / Catalog Reconciler"]
        DR["Decision Readiness"]
    end

    subgraph CON["消费者"]
        BA["业务 Application"]
        API["REST"]
        SDK["SDK / MCP"]
        TUI["Terminal / TUI / Agent"]
    end

    P1 --> A
    P2 --> A
    P3 --> A
    P4 --> A
    P5 --> A
    A --> R --> C
    C -->|通过| N --> X --> F --> U --> V --> G
    C -->|失败| Q
    X -->|冲突| Q
    D --> C
    B --> A
    S --> A
    H --> X
    E --> S
    U --> DR
    H --> DR
    G --> BA
    G --> API
    BA --> SDK
    BA --> TUI
~~~

关键点：

- Raw Landing 不是业务查询源。
- 类型化事实表可以保留多个 Provider 的标准化事实，但 current/latest 查询只能读取经过 Canonical Publication 选定的版本。
- 选源是一次可审计的发布行为，不是在每个消费者里临时 order_by("-date").first()。
- Data Center 控制面定义契约、调度、健康和 readiness，不反向 import 业务 App。
- 业务聚合由业务 Application 完成，但每个事实分区必须保留 Data Center 的 evidence 和 reliability。

### 5.2 目标四层边界

#### Domain

只使用标准库，新增或收敛以下不可变值对象：

- DatasetKey
- DatasetContractVersion
- NaturalKey
- SourceEvidence
- ObservationTime
- QualityAssessment
- ReliabilityContract
- DataEnvelope[T]
- FetchOutcome
- SyncOutcome
- PublicationDecision
- ConflictEvidence

所有值对象使用 frozen dataclass；Domain 不知道 Django、Pandas、Provider SDK 或 HTTP 存在。

#### Application

只负责用例编排和端口定义：

- IngestDatasetUseCase
- ValidateAndNormalizeBatchUseCase
- ReconcileSourcesUseCase
- PublishCanonicalDatasetUseCase
- QueryAssetMasterUseCase
- QueryMarketDataUseCase
- QueryMacroDataUseCase
- QueryFundamentalDataUseCase
- QueryReferenceDataUseCase
- QueryNewsAndFlowUseCase
- AuditCoverageUseCase
- ReconcileRuntimeCatalogUseCase
- ResumeSyncRunUseCase

Application 不 import ORM Model、Repository 实现、core/integration 或业务 App infrastructure。

#### Infrastructure

只在本层实现：

- Provider SDK / HTTP Gateway。
- Schema 解析和 Provider Binding。
- Django ORM Model 与 Repository。
- PostgreSQL 批量写入、索引、锁、分区和查询优化。
- Raw Payload 脱敏、压缩、哈希和保留。
- Celery、Redis 和外部网络 I/O 的具体适配。

#### Interface

只做参数校验和输出格式化：

- REST / TUI 管理接口。
- 显式同步操作只允许 POST 或任务命令。
- GET 只读，不隐式抓取、不写数据库、不创建 schedule。
- API 输出直接序列化 Application DTO，不自行重算 freshness。

### 5.3 目标目录

目标不是一次性移动全部文件，而是在迁移阶段逐步收敛到以下结构：

~~~text
apps/data_center/
├── domain/
│   ├── evidence.py
│   ├── dataset_contracts.py
│   ├── facts.py
│   ├── reliability.py
│   ├── sync.py
│   ├── rules.py
│   └── protocols.py
├── application/
│   ├── ingestion/
│   ├── publication/
│   ├── query/
│   ├── operations/
│   ├── dtos.py
│   └── public.py
├── infrastructure/
│   ├── providers/
│   ├── parsers/
│   ├── repositories/
│   ├── models/
│   ├── raw_landing/
│   └── runtime/
├── interface/
└── composition.py
~~~

约束：

- public.py 是业务 App 唯一允许依赖的稳定 Application Facade；不得成为巨型实现文件。
- composition.py 只组装 Data Center 内部具体实现。
- 业务 App 在自己的 composition root 注入 Data Center Public Port。
- providers 按 provider / dataset binding 拆分，不再通过 core/integration 调回业务模块。
- 当前大文件只在对应迁移阶段拆分，不允许为了目录整洁先做无行为收益的大搬家。

## 6. 统一数据证据契约

### 6.1 DataEnvelope

每一条对业务可见的数据必须由 DataEnvelope[T] 承载，至少包含：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| dataset_key | 是 | 稳定数据集标识，如 equity.quote.snapshot |
| contract_version | 是 | Dataset Contract 版本 |
| schema_version | 是 | Payload / canonical schema 版本 |
| value | 否 | 真实值；missing 时允许为空 |
| natural_key | 是 | 数据集自然键 |
| observed_at | 视数据集 | 源观测时间或事实日期 |
| published_at | 视数据集 | 上游发布或公告时间 |
| available_at | 视数据集 | Point-in-Time 可用时间 |
| fetched_at | 是 | 系统抓取时间 |
| source | 是 | 实际 Provider |
| source_capability | 是 | 精确能力，不只使用宽泛域名 |
| unit | 视字段 | Canonical 单位 |
| original_unit | 视字段 | 上游原始单位 |
| raw_audit_id / payload_hash | 是 | 可回溯原始响应 |
| quality | 是 | 结构、范围、完整性和一致性判定 |
| reliability | 是 | fresh/stale/missing/partial/conflict/maintenance/failed |
| publication_id | 当前数据必填 | 当前发布版本 |
| must_not_use_for_decision | 是 | 决策阻断 |
| block_reason_code | 阻断时必填 | 稳定机器码 |
| block_reason | 阻断时必填 | 用户可读原因 |

### 6.2 时间语义

| 数据集 | 事实时间 | 发布/可用时间 | 抓取时间 | 禁止行为 |
| --- | --- | --- | --- | --- |
| 日线 | bar_date | 通常为已完成交易日 | fetched_at | 用请求时间包装成实时 |
| 实时行情 | observed_at / snapshot_at | 可选 | fetched_at | 用 fetched_at 替代观测时间 |
| 宏观 | reporting_period | published_at / available_at | fetched_at | 只按 reporting_period 推断当时已知 |
| 财务 | period_end | announced_at / available_at | fetched_at | 用报告期代替披露期 |
| 估值 | val_date / observed_at | 可选 | fetched_at | 无日期值参与 current 排序 |
| 基金净值 | nav_date | published_at | fetched_at | 把最近一条等同今日净值 |
| 新闻 | published_at | published_at | fetched_at | 以抓取时间替代发布时间 |
| 板块成员 | effective_date | announced_at 可选 | fetched_at | 忽略 expiry_date |

通用约束：

- 所有 datetime 必须 timezone-aware。
- fetched_at 不得早于 observed_at；能在数据库约束的字段必须增加 CheckConstraint。
- date 与 datetime 不混用；交易日事实使用 date，盘中观测使用 datetime。
- latest 只表示排序最新，fresh 由 Dataset Freshness Policy 计算。
- 历史回测只可读取 available_at 不晚于回测时点的数据版本。

### 6.3 缺失值与零值

这是本次重构的 P0 语义规则：

1. None、空字段、NaN、解析失败、Provider 未返回必须保持 missing，不得使用 or 0.0。
2. 0 只有在 Dataset Field Contract 明确允许且上游确实返回 0 时才是合法事实。
3. 估值倍数、价格、净值等不可执行零值直接进入 quarantine。
4. 财务指标缺失时，筛选、排序、打分必须显式选择“排除、降权或阻断”，不能把它当成最低值。
5. estimated 必须附带估算方法、输入 lineage、算法版本和置信说明。
6. 任一关键分区 missing 时，聚合响应最多为 partial，不能被顶层 reliable=true 洗白。

第一批必须修复的调用点：

- apps/equity/infrastructure/fundamentals_repository.py
- apps/equity/infrastructure/financial_source_gateway.py
- apps/equity/infrastructure/valuation_source_gateways.py
- apps/alpha/infrastructure/adapters/simple_adapter.py
- apps/data_center/infrastructure/_provider_adapter_akshare.py

### 6.4 质量与可靠性分离

不得只保留一个模糊的 reliability 分数：

- Quality：值本身是否满足 schema、类型、单位、范围、自然键、完整性和跨字段规则。
- Freshness：相对业务时点是否新鲜。
- Source Health：Provider + dataset 能力近期是否稳定。
- Coverage：目标 universe / 时间范围覆盖度。
- Conflict：多个可比来源是否超出容差。
- Decision Usability：以上维度汇总后的 fail-closed 结论。

存储时记录静态质量和来源证据；查询时结合交易日历、当前时间、覆盖要求和运行状态计算动态可靠性。

## 7. Dataset Contract 与 Provider Binding

### 7.1 Runtime 唯一真源

新增版本化 Dataset Contract Runtime 模型，建议拆为：

- DatasetContractModel：数据集身份、owner、频率、关键级别、当前版本。
- DatasetFieldContractModel：字段语义、类型、单位、可空性、范围、零值策略。
- ProviderDatasetBindingModel：Provider endpoint、参数、字段映射、原始单位、优先级和可比组。
- FreshnessPolicyModel：交易日历、最大延迟、发布时间 lag、周末/节假日规则。
- ReconciliationPolicyModel：跨源容差、仲裁规则、冲突动作。
- PublicationPolicyModel：发布门槛、覆盖下限、关键字段和例外策略。

这些运行时规则存数据库，并通过 Data Center Admin / API 管理；业务代码不得新增单位、字段映射或阈值硬编码。

仓库中的 migration / seed 只负责可重复初始化。governance 文件是 CI 和范围证据投影，不代替运行时数据库真源。

### 7.2 Dataset Contract 必备字段

| 维度 | 字段 |
| --- | --- |
| 身份 | dataset_key、display_name、owner、domain_family |
| 版本 | contract_version、schema_version、effective_from、supersedes |
| 上游 | provider、endpoint / method、capability_key、license_scope |
| 语义 | business_meaning、frequency、calendar、dimensions |
| 字段 | source_field、canonical_field、type、nullable、unit、original_unit |
| 时间 | observed_field、published_field、available_field、timezone |
| 质量 | range、cross_field_rules、required_fields、zero_policy |
| 新鲜度 | expected_lag、max_age、latest_completed_session_rule |
| 对账 | comparable_provider_group、tolerance、conflict_action |
| 发布 | criticality、coverage_threshold、publication_policy |
| 运维 | rate_limit、batch_size、timeout、retry_policy、retention |

### 7.3 能力粒度

现有 DataCapability 的宏观、历史价格、实时行情、财务等大类可以保留为 family，但 Provider 健康和路由必须使用精确 capability_key，例如：

- equity.identity
- equity.daily
- equity.quote
- equity.daily_basic
- equity.income
- equity.balance_sheet
- equity.cash_flow
- equity.fina_indicator
- fund.nav
- macro.china.pmi
- macro.china.cpi
- sector.membership
- news.equity
- capital_flow.equity

“Provider 支持 FINANCIAL”不再自动推导它支持所有财务报表、所有市场和所有报告期。

### 7.4 当前配置中心现状判断

系统已经有 apps/config_center，但它目前是“部分配置 owner + 配置发现页”，还不是全系统统一的运行时配置真源。

已存在：

| 能力 | 当前实现 | 判断 |
| --- | --- | --- |
| 全局单例设置 | config_center.SystemSettingsModel，物理表 system_settings | 已可持久化，但字段持续膨胀，混合审批、协议、备份、Decision State、Qlib、Alpha 和代码映射 |
| Qlib Runtime | SystemSettingsModel 中的显式字段 | 有 Application UseCase/API，但仍有 getter 内代码 fallback |
| Qlib 训练模板 | QlibTrainingProfileModel | 适合继续作为复杂类型化配置 |
| Alpha Universe | AlphaUniverseConfigModel | 适合继续作为领域配置 |
| 配置摘要 | ConfigCenterSummaryService | 主要负责发现/摘要；不是统一解析器 |
| Data Center 配置 | ProviderConfig、DataProviderSettings、ProductionCoverageUniverse、IndicatorCatalog 等 | 由 Data Center 自己持久化 |
| Risk、估值、策略、筛选、交易成本等 | 分布在各业务 App | 领域 owner 正确，但缺少统一登记、版本和入口 |
| Repository JSON | config/tui 与 governance 下的 JSON | 属于 UI/CI 投影，不是生产运行时配置真源 |
| 环境变量与 settings 默认值 | core/settings 中存在大量 env default 和模块常量 | 部分是启动配置，部分其实是应迁移的运行参数 |

已确认的缺口：

1. config_center 中不存在 RuntimeConfigDefinition / Value / Profile / Revision / Snapshot 这一类统一注册表。
2. SystemSettingsModel 是 pk=1 的大单例，不适合继续无限增加容量、保留、日志、任务、Provider、策略等字段。
3. SystemSettingsModel.get_settings_for_read、Qlib getter、DataProviderSettings.load_for_read 等位置允许在没有持久化配置时返回代码默认值；关键配置可能“看似有值，实际没配置”。
4. DjangoConfigCenterSummaryRepository 直接 import Data Center infrastructure models；统一入口依赖了其他 App 的 ORM，而不是对方 Application Facade。
5. 配置中心能力矩阵明确写着“配置中心负责发现、摘要、跳转，权限、审计、版本由原模块负责”，说明当前尚未形成统一控制面。
6. 初步扫描 core/settings 发现数十处带 default 的 env 参数；并非全部应迁移，但必须逐项分类。

结论：

- 现在有统一配置中心的雏形和数据库表。
- 现在没有一个可以承接 Storage、Retention、Backup、Log、Readiness 等全局参数的版本化通用配置模型。
- 现在没有可作为运行时真源的统一 JSON；也不建议新建一个巨型 runtime.json。

### 7.5 统一配置中心的目标形态

采用“中央控制面 + 领域类型化 owner”的联邦式配置架构：

~~~mermaid
flowchart LR
    subgraph CC["Config Center 控制面"]
        CAT["配置目录与 Schema"]
        PROF["环境/Profile"]
        VAL["全局运行参数"]
        REV["版本、审计与回滚"]
        SNAP["Resolved Snapshot"]
        API["统一 Application API / TUI"]
    end

    subgraph OWN["领域配置 Owner"]
        DC["Data Center Dataset / Provider / Retention"]
        RC["Risk Center Policy"]
        ST["Strategy / Filter / Valuation"]
        AC["Account / Trading Cost"]
    end

    subgraph CON["运行消费者"]
        TASK["Celery / Scheduler"]
        READY["Readiness / Task Monitor"]
        WEB["REST / SDK / MCP / TUI"]
    end

    CAT --> PROF --> VAL --> SNAP
    VAL --> REV
    DC --> API
    RC --> API
    ST --> API
    AC --> API
    CAT --> API
    SNAP --> TASK
    SNAP --> READY
    API --> WEB
~~~

统一含义：

- 一个配置目录。
- 一个面向管理员的 TUI 主入口和一组稳定 Application API。
- 一套类型、单位、范围、敏感性、owner、版本、审计和激活规则。
- 一个 resolved snapshot/hash，任务和决策证据可记录所用配置版本。
- 所有参数都能查到“谁拥有、存在哪里、谁消费、如何生效、能否回滚”。

不统一的内容：

- 不把所有配置强行搬到一个物理表。
- 不让 config_center 直接 import 其他 App ORM。
- 不把运行状态、监控指标、任务结果伪装成配置。
- 不把密钥明文放进通用 JSON。

### 7.6 Config Center 自有模型

新增以下类型化模型；具体命名可在实现阶段调整，但职责不得合并成一个无约束 JSON：

#### RuntimeConfigDefinitionModel

配置定义目录：

- key：全局唯一稳定键，例如 storage.capacity.configured_gib。
- namespace：storage、backup、logging、readiness、runtime 等。
- owner_app：物理和业务 owner。
- value_type：bool、int、decimal、string、duration、bytes、percentage、enum、typed_json。
- unit：GiB、seconds、days、ratio 等。
- constraints：最小值、最大值、枚举、JSON Schema。
- criticality：bootstrap、critical、normal、experimental。
- secret：是否只能保存 secret_ref。
- reload_mode：immediate、next_task、restart_required。
- description / user_impact。
- is_deprecated / replacement_key。

#### RuntimeConfigProfileModel

一组可发布配置：

- profile_key：production-default、development、production-90g 等。
- environment。
- version。
- status：draft、validating、active、superseded、rejected。
- based_on_profile。
- content_hash。
- created_by / activated_by。
- created_at / activated_at。
- change_reason / release_ref。

#### RuntimeConfigValueModel

- profile + definition 唯一约束。
- value_json 作为物理通用载体，但必须先由 value_type 和 constraints 校验。
- secret_ref，敏感值只保存引用。
- source：setup、admin、import、migration、environment_projection。
- validation_status / validation_error。

Application / Domain 消费端不得接收裸 value_json；必须转换成类型化 DTO 或值对象。

#### RuntimeConfigRevisionModel

不可变审计：

- profile/version。
- before_hash / after_hash。
- 变更键清单。
- before / after 的脱敏投影。
- actor、reason、changed_at、release_ref。
- validation evidence。

#### RuntimeConfigSnapshotModel

激活后生成不可变 resolved snapshot：

- profile/version/hash。
- resolved_values 的脱敏投影。
- generated_at。
- effective_from。
- validation report。
- consumer acknowledgement。

任务启动时记录 snapshot_id/hash；长任务中途不切换配置。

### 7.7 配置所有权矩阵

统一入口不改变正确的领域归属：

| 参数类别 | Runtime 物理 owner | Config Center 职责 |
| --- | --- | --- |
| 全局容量、磁盘水位、备份暂存、日志总额、任务明细保留 | config_center | 定义、存储、版本、激活、审计、统一查询 |
| Decision maintenance / blocked 状态 | 独立运行状态模型，建议仍在 config_center | 状态切换和审计；不得混入 Config Value |
| Dataset Contract、字段语义、单位、Provider Binding | data_center | 注册目录、统一展示和跳转；修改调用 Data Center Application |
| Dataset Retention / Archive Policy | data_center | 统一入口、版本摘要和 impact preview；物理规则由 Data Center 执行 |
| Provider 凭据、endpoint、优先级 | data_center / secret store | 统一入口；密钥只显示掩码和 secret_ref |
| Risk Floor、账户风险策略 | risk_center | 统一目录；读写调用 Risk Center Application |
| 估值修复、Beta Gate、筛选、策略、因子权重 | 对应业务 App | 统一发现、版本摘要和跳转；不搬 ORM |
| 账户偏好、交易成本、个人覆盖范围 | account / portfolio 等 | 统一发现；保持账户权限边界 |
| Qlib Runtime / Profile | config_center | 继续由 Config Center 自有 |
| SECRET_KEY、DATABASE_URL、加密主密钥、启动端口 | 部署环境 / secret store | 只登记存在性和来源；不写数据库值 |
| TUI schema、治理清单、CI baseline | Git JSON | 只登记版本/hash；不是 runtime value |
| Provider Health、磁盘使用量、任务运行结果 | Data Center / Task Monitor / Operational Readiness | 作为 observed state 展示，不作为 desired config 存储 |

硬约束：

- “统一配置”首先是统一控制面和契约，不是统一物理表。
- 复杂领域配置必须保留类型化 Model、约束和 Repository。
- Config Center 调用 owner Application Facade；禁止直接 import owner infrastructure Model。
- owner App 不得反向依赖 Config Center Infrastructure，只依赖 Application Query Port。

### 7.8 配置解析与生效

配置来源优先级固定为：

1. 启动必需且数据库尚不可用的 bootstrap / secret 配置。
2. Config Center 当前 active profile 中的全局运行参数。
3. owner App 当前 active 的类型化领域配置。
4. 请求级、账户级合法覆盖；仅适用于 Definition 明确允许的 key。

禁止使用顺序：

- DB 缺配置后回退 Python 字面量。
- DB 缺配置后回退 settings 默认值。
- 不同消费者各自解释同一个 key。
- 环境变量长期覆盖 DB 而界面不显示。

关键配置不存在、类型错误或 owner 不可用时：

- critical 配置 fail closed。
- normal 配置返回 config_missing 并由 readiness 决定是否阻断。
- experimental 配置可以禁用功能，但必须披露来源。

配置生命周期：

1. 创建 draft profile。
2. 按 Definition 做类型和范围校验。
3. 调用 owner Application 执行跨字段/业务校验。
4. 生成 impact preview：受影响任务、数据集、入口和是否需要重启。
5. 原子激活并生成 snapshot/hash。
6. 发布 ConfigChanged Domain Event。
7. 消费者按 reload_mode 生效并回报 acknowledgement。
8. 异常时回滚上一 active profile，不手工改表。

### 7.9 配置 JSON 的边界

JSON 只允许三种用途：

1. governance/runtime_config_contracts.json：机器登记 key、owner、消费者、测试和代码位置，供 CI 防遗漏。
2. config export/import：从数据库生成的脱敏、带 schema_version/hash 的 profile 快照，用于环境迁移和审计。
3. 复杂 typed_json 值：必须绑定 Definition、JSON Schema 和 Domain DTO。

JSON 禁止作为：

- 生产唯一真源。
- 密钥载体。
- 无版本、无 owner、无校验的自由 dict。
- 启动时覆盖数据库但不留下审计的旁路。

Repository 内的 TUI/governance JSON 继续由 Git 管理；运行参数默认由 PostgreSQL 管理。

### 7.10 第一批统一收口参数

第一批先处理容易散落、跨多个模块消费、且影响生产安全的运维参数：

| Namespace | 参数组 |
| --- | --- |
| storage.capacity | configured_capacity、effective capacity 策略、子预算比例 |
| storage.watermark | green/yellow/orange/red/critical/emergency 比例与最小空闲 |
| storage.retention | Raw、Quarantine、Task、Health、Log 的默认窗口 |
| storage.backup | max_inflight_count、max_age_hours、staging_budget、外部保留策略 |
| storage.maintenance | partition threshold、batch size、WAL budget、维护水位 |
| logging | 应用文件日志总额、单文件大小、数量和保留天数 |
| task_monitor | success/failed 明细保留、rollup 窗口和 cleanup batch |
| readiness | storage blocked 条件、严格模式与告警提前量 |

第二批：

- Provider 全局 failover、timeout、retry、rate limit。
- Dataset freshness / coverage / reconciliation / retention。
- Qlib、Alpha 和统一 universe 选择。
- Decision readiness 的受管资产与 freshness。

第三批只做“目录统一”，不强行搬表：

- Risk Center。
- Beta Gate。
- 估值修复。
- Filter / Strategy / Factor。
- Account / Portfolio / Trading Cost。

### 7.11 SystemSettingsModel 收敛

立即冻结 SystemSettingsModel 新增无关字段。

拆分顺序：

1. 容量、日志、备份保留等新参数直接进入 Runtime Config 模型，不进入 SystemSettingsModel。
2. 将现有 Qlib Runtime 字段迁到 qlib runtime profile；训练模板仍保留类型化表。
3. benchmark_code_map、asset_proxy_code_map 迁到 Data Center 主数据/Reference Policy，Config Center 提供统一入口。
4. decision_runtime_* 迁到独立 DecisionRuntimeStateModel，因为它是 observed/controlled state，不是普通配置。
5. backup SMTP/password 使用 secret_ref；邮件策略进入 backup namespace。
6. 用户协议、风险提示等系统内容迁到明确的 system_content namespace 或独立内容表。
7. 所有消费者切换后，SystemSettingsModel 进入只读兼容，再在后续 release 删除过期字段。

不得新建另一个更大的 singleton 代替它。

### 7.12 配置迁移门禁

M0 新增机器清单，至少登记：

- config_key / namespace。
- current_source：DB field、domain model、env、settings、constant、JSON、Celery kwargs。
- owner_app。
- consumers。
- value_type / unit / constraint。
- criticality。
- fallback 行为。
- target_source。
- migration_state。
- tests。

CI 规则：

- 新增运行参数必须登记 runtime_config_contracts。
- 新增 env default、Model default、模块常量和 Celery schedule kwargs 时，必须声明 bootstrap / runtime / domain / static 分类。
- critical runtime 配置不得在消费者中存在字面量 fallback。
- Config Center 不得直接 import 其他 App infrastructure。
- 同一个 config_key 不得存在两个 active owner。
- profile export/import 必须验证 schema、hash、secret redaction 和版本。
- 至少使用两个非默认 profile 运行契约测试，证明配置驱动而非硬编码。

配置中心完成标准：

- 管理员能在一个 TUI 主任务中搜索全部配置并看到 owner、来源、生效版本、消费者和风险。
- 全局运行参数可在统一入口 draft、校验、预览、激活、审计和回滚。
- 领域参数通过 owner Application 在统一入口操作，权限和业务校验不丢失。
- 任一关键任务和决策结果能记录 config_snapshot_id/hash。
- 删除 Config Center 数据库或取消 active critical profile 时，系统 fail closed，不使用隐形默认值。

## 8. 存储架构

### 8.1 不采用一个巨型通用事实表

保留按数据域类型化的事实表，避免 EAV 带来的类型弱化、索引困难和查询不可控。通过抽象基础模型或 Repository 约定统一证据列，而不是把所有值塞进一个 JSON value。

目标表分为四层：

1. Raw：RawRequestAudit、RawPayload、SchemaFingerprint。
2. Standard Fact：AssetMaster、MacroFact、PriceBar、QuoteSnapshot、FundNav、FinancialFact、ValuationFact、SectorMembership、News、CapitalFlow。
3. Quality：DataQualityIssue、QuarantineRecord、ConflictSet。
4. Publication：CanonicalPublication、PublicationMember、CoverageSnapshot。

### 8.2 所有事实表的公共证据列

- dataset_key
- contract_version
- schema_version
- source
- source_record_id
- observed_at 或对应事实日期
- published_at / available_at，适用时
- fetched_at
- raw_payload_hash
- quality_status
- revision_number
- ingested_run_id

不得把关键语义长期塞入 extra JSON；extra 只保存 Provider 特有、非决策关键且已脱敏的信息。

### 8.3 重点模型整改

| 现有模型 | 目标整改 |
| --- | --- |
| MacroFactModel | 保留 reporting_period / published_at / revision；补 contract、available_at、publication 与统一 lineage |
| PriceBarModel | 补 schema、quality、run、publication；自然键和可执行价格约束继续保留 |
| QuoteSnapshotModel | fetched_at 改为强语义字段；增加 fetched_at ≥ snapshot_at 数据库约束和来源观测校验 |
| FinancialFactModel | 增加 announced_at / available_at、报表口径、修订、质量、contract 和 lineage |
| ValuationFactModel | 增加 quality、contract、run、publication；可空指标保持 None，不补 0 |
| FundNavFactModel | 增加 published_at、quality、contract、publication |
| SectorMembershipFactModel | 增加 source 到自然键或明确 canonical 发布选择，补 contract 和 lineage |
| NewsFactModel | 空 external_id 不得造成错误去重；增加内容哈希、发布证据和来源许可标记 |
| CapitalFlowFactModel | 明确金额单位、流量口径、字段可比组、quality 和 contract |
| RawAuditModel | 拆出请求参数哈希、响应哈希、schema fingerprint、脱敏状态、保留期和解析版本 |

### 8.4 Canonical Publication

标准事实表允许保留多个 Provider 的合格事实。消费者不得自行选最新来源，而由发布层记录：

- dataset_key 与自然键范围。
- 被选中的 source fact / revision。
- 选源策略版本。
- 质量、新鲜度、覆盖和冲突结论。
- 发布者或自动任务。
- published_at、superseded_at。
- must_not_use_for_decision 和阻断原因。

current/latest 查询只读当前有效 Publication；历史研究可按 publication_id 或 as_of 查询，保证可复现。

## 9. 采集、同步与发布状态机

### 9.1 状态机

~~~mermaid
stateDiagram-v2
    [*] --> Requested
    Requested --> Fetching
    Fetching --> Received
    Fetching --> Failed
    Received --> Validating
    Validating --> Quarantined
    Validating --> Normalized
    Normalized --> Reconciling
    Reconciling --> Conflict
    Reconciling --> Stored
    Stored --> Publishing
    Publishing --> Published
    Publishing --> Blocked
    Failed --> Retrying
    Retrying --> Fetching
    Quarantined --> [*]
    Conflict --> [*]
    Published --> [*]
    Blocked --> [*]
~~~

### 9.2 运行模型

新增或收敛：

- SyncRun：一次用户、beat、CLI 或系统触发。
- SyncBatch：一个 Provider / dataset / universe slice。
- SyncCheckpoint：可恢复游标。
- SyncItemFailure：失败自然键、错误码、是否可重试。
- PublicationRun：从合格事实到 canonical publication 的独立过程。

统一计数：

- requested
- fetched
- validated
- quarantined
- succeeded
- failed
- stored
- published
- unchanged

统一 outcome：

| Outcome | 条件 |
| --- | --- |
| success | 所有请求项成功，且满足预期存储/发布规则 |
| partial | 部分项成功，部分项失败或隔离 |
| noop | 合法执行但无变更；必须有稳定原因 |
| blocked | 维护、依赖能力、配额、契约或 readiness 主动阻断 |
| failed | 全部失败、契约失败或关键写入失败 |

stored=0 不得默认 success；若上游无新版本且已证明数据未变化，可返回 noop/unchanged。

### 9.3 幂等、事务与性能

- 幂等键至少包含 dataset_key、contract_version、provider、自然键范围、请求窗口。
- 重试不得生成重复事实或重复 Publication。
- 单批事务，不使用覆盖 5,000+ 证券的超长事务。
- 使用 bulk_create / bulk_update / PostgreSQL upsert；禁止逐证券 N+1 查询。
- 大 QuerySet 使用 iterator 和固定 chunk。
- 每一批记录 checkpoint、写入数、失败样本和耗时。
- 并发使用租约或数据库锁，避免同一 dataset/window 重复跑。
- 写事实与发布分开：事实写成功不等于可用于决策。

### 9.4 读写分离

- GET 永远只读已发布数据。
- 缺失或 stale 时返回可靠性阻断，不在请求线程抓取和持久化。
- 用户显式请求刷新使用 POST，返回 run_id 和 202/任务状态。
- 后台缓存不能改变 observed_at、publication_id 或 reliability。
- Redis 丢失只影响性能，不得改变事实选择和决策结论。

### 9.5 Runtime Desired State

Provider Catalog、Celery Beat Schedule、MCP Capability Catalog 和 TUI metadata 均属于派生运行态，必须具备：

- 版本化 desired-state 真源。
- 幂等 reconcile 命令。
- 启动/部署时确定性同步。
- 漂移检测和告警。
- 发布前后数量、哈希和 owner 对账。

不得依靠某次手工 management command 的历史执行结果维持生产正确性。

## 10. Provider、Failover 与健康度

### 10.1 标准 FetchResult

Provider 不再直接返回 list 或 None，而返回类型化 FetchResult[T]：

- provider_name
- dataset_key / capability_key
- request_window
- rows
- source_observed_range
- fetched_at
- schema_fingerprint
- raw_audit_id
- outcome
- warnings
- retryable_error

Registry 只有在 Dataset Acceptance Policy 通过后才能 record_success。

### 10.2 Failover 规则

按以下顺序执行：

1. Provider 是否声明并通过 runtime 验证支持该精确能力。
2. 请求是否成功。
3. Schema fingerprint 是否可识别。
4. 必填字段、类型、单位和自然键是否通过。
5. 时间范围和 freshness 是否满足请求。
6. 覆盖是否满足阈值。
7. 与可比来源偏差是否在 Dataset Contract 容差内。
8. 满足后才可返回；否则继续后续 Provider。

结果处理：

- 非空但 stale：继续 failover。
- 非空但错单位/错语义：quarantine，继续 failover。
- 多源差异超阈值：标记 conflict，不静默选择。
- 所有源失败：返回 failed 或 missing，并 fail closed。
- 次级来源成功：明确发布 fallback_source 和主源失败证据。

### 10.3 健康度维度

Provider Health 按 provider + dataset_key 记录：

- last_attempt_at
- last_usable_success_at
- last_failure_at
- last_observed_at
- last_output_count
- last_published_count
- coverage_ratio
- schema_failure_count
- stale_result_count
- conflict_count
- consecutive_failures
- latency P50/P95
- rate-limit state
- circuit state

“连接测试通过”只能表示 reachable，不能表示 healthy。表为空、长期未发布、零产出或持续 stale 时不得显示健康。

## 11. 对外查询与消费者契约

### 11.1 稳定 Public Ports

不建立一个无限膨胀的 UnifiedDataService；按数据职责提供小型端口：

- AssetMasterQueryPort
- MarketDataQueryPort
- MacroDataQueryPort
- FundamentalDataQueryPort
- FundDataQueryPort
- ReferenceDataQueryPort
- NewsFlowQueryPort
- CoverageAndReliabilityQueryPort

每个端口返回 DataEnvelope 或包含多个 DataEnvelope 的类型化响应。消费者不能拿裸 ORM、Pandas DataFrame 或 Provider 原始 dict。

### 11.2 入口一致性

同一个用户问题的数据链路必须是：

Data Center Public Port → 业务 Application 聚合 → REST DTO → SDK/MCP/Terminal/TUI。

禁止：

- MCP Handler 自己查 ORM。
- SDK 与 REST 使用不同 freshness 规则。
- Terminal 在无结构化证据时补造价格、日期、来源或估值。
- Dashboard 为了展示自行 fallback 到旧表。
- Agent Runtime 单独查询 MacroIndicator、ValuationModel 等 legacy 表。

复合查询例如 equity.read.research_snapshot 由 equity/ai_capability Application 编排，但行情、历史、估值、财务、新闻和资金流分区必须来自 Data Center Public Port，并原样保留每个分区的 evidence。

### 11.3 缓存

- Cache key 包含 dataset_key、contract_version、publication_id、查询参数和权限范围。
- TTL 只是缓存寿命，不等于 freshness。
- 缓存值必须包含完整 reliability 和 source time。
- 新 Publication 产生时按 publication_id 自然失效，不使用“更新时间改成 now”刷新语义。

## 12. 数据域迁移矩阵

| 顺序 | 数据域 | 当前主要债务 | 目标真源 | 主要消费者 | 硬退出条件 |
| --- | --- | --- | --- | --- | --- |
| D0 | Asset Master / Alias | 多处代码归一和业务模型身份并存 | Data Center AssetMaster / Alias Publication | 全系统 | 所有外部事实都能解析到唯一资产；无孤儿代码 |
| D1 | Price Bar | Data Center 与 equity.StockDailyModel 并存 | Data Center PriceBar Publication | realtime、backtest、alpha、factor、account、portfolio | 旧表零读写；OHLC/日期/复权/覆盖对账通过 |
| D2 | Quote Snapshot | 观测时间与抓取时间曾混淆 | Data Center Quote Publication | realtime、account、simulated_trading、valuation | GET 只读；时间保真；交易日 freshness 通过 |
| D3 | Macro | Data Center MacroFact 与 macro.MacroIndicator 并存 | Data Center Macro Publication | regime、pulse、policy、agent_runtime | canonical/legacy 全量对账；旧表零读写 |
| D4 | Financial | equity.FinancialDataModel 与 Data Center 并存 | Data Center Financial Publication | equity、alpha、factor、valuation、research | 缺失不再补 0；PIT 时间完整；批量查询无 N+1 |
| D5 | Valuation | equity.ValuationModel 与 Data Center 并存 | Data Center Valuation Publication | equity、alpha、valuation、research | source/date/unit 一致；旧任务迁移；旧表零读写 |
| D6 | Fund NAV | 多入口 fallback 语义需统一 | Data Center FundNav Publication | fund、account、asset_analysis、backtest | 最新净值不冒充实时；覆盖和发布日可解释 |
| D7 | Sector Membership | 成分与行业归属来源可能散落 | Data Center Sector Publication | sector、rotation、hedge、factor | effective/expiry 时点正确；无静默代理 |
| D8 | News | external_id、覆盖和许可口径不一 | Data Center News Publication | sentiment、events、equity、agent | 去重、时区、来源和缺失能力明确 |
| D9 | Capital Flow | 字段口径和覆盖能力不稳定 | Data Center CapitalFlow Publication | equity、pulse、rotation、sentiment | 单位、口径、日期和 capability 可审计 |

## 13. 消费者迁移矩阵

| App / 入口 | 迁移动作 | 不允许保留的行为 |
| --- | --- | --- |
| macro | 停止作为外部宏观事实 owner；仅保留宏观业务规则或兼容 facade | 写 MacroIndicator、直连 Provider |
| regime / pulse / policy | 注入 MacroDataQueryPort；保留 observed/published/available time | 用计算时间替代源时间 |
| equity | 财务、估值、日线 Repository 改为 Data Center Port；领域实体字段支持 None + Reliability | 双写旧模型、缺失补 0 |
| alpha / factor | 批量读取 Data Center read model；一次查询取齐 universe 数据 | per-stock ORM N+1、读 equity 旧模型 |
| valuation | 市价和基本面统一走 Data Center；估值算法仍归 valuation | 自建行情 fallback |
| realtime | 只读 Quote/Price Publication；轮询写入调用 Data Center ingest | 自存另一份事实真源、GET 写入 |
| account / portfolio / simulated_trading / broker_execution | 通过 MarketDataQueryPort 获取可执行价格并检查决策可用性 | 用 stale/missing 价格成交 |
| fund / asset_analysis | NAV、价格、主数据统一走中台 | 业务 Adapter 直连外部源 |
| sector / rotation / hedge | 成分、行情、资金流统一走中台 | 静默使用不等价代理数据 |
| sentiment / events | 新闻事实走中台，情感分析结果仍归 sentiment | 把抓取时间当新闻发布时间 |
| backtest / audit / research | 使用 publication_id / as_of 重放 | 查询当前最新版重写历史 |
| dashboard | 只消费业务 Application DTO | 为展示绕过可靠性门 |
| agent_runtime / terminal | 删除 legacy snapshot 查询，统一使用业务 Application / Data Center evidence | 无证据自由生成金融事实 |
| ai_capability / SDK / MCP | 同一能力只映射到一个 Application handler | 独立 ORM、独立 freshness、目录漂移 |

每迁移一个 App，必须同时删除旧读路径、旧写路径和对应测试 fixture。只新增 Data Center 路径但保留旧 fallback 不算完成。

## 14. 遗留链路退役清单

以下为首批明确退役对象；M0 自动盘点后只允许增加，不允许无证据移除。

| 对象 | 处置 | 删除前置 |
| --- | --- | --- |
| apps/macro/infrastructure/models.py::MacroIndicator | 迁移、只读、最终删表 | Macro Publication 对账、所有消费者切换 |
| equity.FinancialDataModel | 迁移、停止写入、最终删表 | 财务 PIT/单位/覆盖对账 |
| equity.ValuationModel | 迁移、停止写入、最终删表 | 估值日期/指标/覆盖对账 |
| equity.StockDailyModel | 迁移、停止写入、最终删表 | PriceBar 复权与交易日对账 |
| apps/equity/management/commands/sync_equity_financial.py | 替换为 Data Center 显式同步入口 | 新任务具备完整 outcome/checkpoint |
| apps/equity/application/tasks_valuation_sync.py 中外部事实同步 | 迁到 Data Center ingestion；保留业务校验编排时重命名 | Celery 契约与消费者切换 |
| apps/alpha/infrastructure/adapters/simple_adapter.py 的旧表访问 | 改为批量 Data Center Port | 性能、结果影子对账 |
| apps/alpha/infrastructure/repositories.py 的 ValuationModel 访问 | 删除 | 新 read model 和查询预算通过 |
| apps/agent_runtime/infrastructure/context_snapshot_repository.py 的 MacroIndicator 读取 | 删除 | Agent 上下文统一 facade |
| core/integration/data_center_business_sources.py | 删除 | Provider 实现全部原生归 data_center infrastructure |
| shared/infrastructure/tushare_client.py | 移入 Data Center Provider 私有实现或删除 | 所有调用点收口、静态 guard 生效 |
| apps/data_center/infrastructure/legacy_sdk_bridge.py | 逐调用点退役 | SDK/MCP 改走稳定 Application API |
| apps/data_center/models.py 兼容 re-export | 最终删除 | 全仓 import 使用正确层路径 |

退役采用 expand/contract：

1. 新增 canonical 结构和写入。
2. 历史数据回填。
3. 影子双读对账；不允许业务自行二选一。
4. 按 dataset feature flag 切读。
5. 停止旧写。
6. 旧表只读冻结并持续监测零访问。
7. 至少跨一个独立发布阶段后再删代码和表。

长期双写不允许超过对应数据域的迁移阶段；延期必须登记 owner、原因、到期条件和阻断级别。

## 15. 分阶段执行计划

### M0：冻结边界与机器清单

目标：先让架构债不能继续增长。

交付：

- [x] 新增 governance/data_ownership_contracts.json，登记 dataset_key、owner、canonical store、消费者和迁移状态。
- [x] 新增 governance/runtime_config_contracts.json，登记 config_key、namespace、current source、owner、消费者、类型、fallback 和迁移状态。
- [x] 新增数据接入静态扫描：Data Center Infrastructure 之外禁止外部 Provider SDK/HTTP 数据适配器。
- [x] 新增 legacy model 访问清单和差异门禁。
- [x] 自动发现 current/latest/realtime/summary surface 与数据写入任务，未登记即失败（当前先生成 deterministic inventory，未登记即失败的全量 CI 阶段仍待补）。
- 生成 PostgreSQL 数据画像和 legacy/canonical 对账基线。
- [x] 为每个数据域指定 Data Platform owner、Business owner 和验收 owner。
- 冻结新的业务侧 Provider Adapter、事实表和直连 ORM。
- 冻结 SystemSettingsModel 无边界增列；新增 env default、模块级运行参数和 Celery 配置常量必须先分类登记。

测试与证据：

- 清单脚本在 clean repository 可重复生成相同结果。
- 已知 B1-B10 全部能被清单或 guard 捕获。
- 当前生产 P0 fail-closed 和 decision maintenance 可用。

退出条件：

- 数据集、消费者、读写点、任务、schedule、路由和运行参数机器清单覆盖率 100%。
- 新增绕过路径在 CI 中失败。
- 未开始任何 destructive migration。

回滚：只删除新增清单/guard；不改变运行行为。

### M1：统一 Domain 契约与 Dataset Catalog

目标：让数据、证据和可靠性成为一个不可拆分的类型。

交付：

- [x] 建立 DataEnvelope、SourceEvidence、QualityAssessment、SyncOutcome、PublicationDecision。
- [x] 将 shared/domain/reliability.py 收敛为 Data Center 可复用的纯 Domain 契约；全仓只保留一个 ReliabilityStatus 定义，并由 reliability ownership guard 固定状态集合与稳定阻断码边界。
- [x] 建立 Dataset Contract / Field Contract / Provider Binding / Freshness / Reconciliation / Publication Policy 模型（Domain 类型 + 版本化清单 + `0054` 持久化 Catalog/幂等初始化）。
- [x] 在 Config Center 建立 RuntimeConfigDefinition / Profile / Value / Revision / Snapshot，以及 owner Application registration（首批 data-center/storage owner；全域 owner registry 仍需扩展）。
- 以 storage / backup / logging / task_monitor / readiness 作为首批 active runtime profile。
- 通过 migration 和幂等初始化命令导入现有 IndicatorCatalog、IndicatorUnitRule 和 Provider 配置。
- 定义稳定 block_reason_code 字典。
- [x] 为旧 DTO 提供短期只读适配器；新 Public Port 的 reliability 由 Data Center 契约承载（旧入口仍有裸 dict 兼容面）。

测试：

- 值对象不变量、时区、时间顺序、缺失/零值、状态机。
- Dataset Contract 版本升级和回滚。
- Config profile 类型/范围/跨字段校验、原子激活、版本回滚和 snapshot hash。
- 使用至少两个非默认 capacity profile 证明消费者不依赖代码 fallback。
- SQLite 开发兼容 + PostgreSQL 约束测试。
- mypy 保证 DataEnvelope 泛型在 Application 边界不退化为 Any。

退出条件：

- D0-D9 每个数据域均有 active Dataset Contract。
- 生产有 active global runtime profile；critical key 缺失时 fail closed。
- 每个 current-data DTO 都能生成统一 ReliabilityContract。
- 旧字段兼容有明确删除里程碑。

回滚：保留旧查询；回滚新 Catalog active version，不删除表。

### M2：原生 Provider 与受控采集面

目标：切断 Data Center 对业务实现和 shared Provider Client 的反向依赖。

交付：

- 在 apps/data_center/infrastructure/providers 下建立原生 Provider Gateway。
- [x] 将 core/integration/data_center_business_sources.py 的首批 Tushare/AKShare/资产回填能力迁入或替换；完整桥退役仍未完成。
- [x] 移除 Data Center Application 对 `core.integration.data_center_business_sources` 和 `core.integration` PIT registry 的 import。
- [x] 将 shared/infrastructure/tushare_client.py 私有化到 Data Center。
- [x] Provider Registry 已能接受 `FetchResult`；既有 adapter 的裸 list 兼容面仍需按 D0-D9 收口。
- [x] 建立 Raw Landing、Schema Fingerprint、Quarantine、SyncRun/Batch/Checkpoint。
- [x] Provider Health 升级为 provider + dataset_key（本地运行时已接入；旧配置兼容投影待生产观察窗口后删除）。
- [x] Beat、Provider Catalog、MCP Catalog 使用 deterministic desired-state reconcile contract（实际部署 reconcile 尚未接入）。

测试：

- 冻结的真实响应 fixture 覆盖字段增删、列名变化、空表、错单位、错类型。
- 超时、限流、401/403、空集、部分批次、重复投递和 checkpoint 恢复。
- stale 主源继续 failover；冲突不发布。
- Raw Payload 脱敏和保留策略。

退出条件：

- Data Center 不再 import 任何业务 App infrastructure 或 core/integration 数据桥。
- Data Center 之外无外部 Provider SDK 运行入口。
- 所有采集任务发布完整 outcome 和计数。

回滚：按 Provider Binding 切回旧 Adapter，但 decision gate 保持阻断；不得回退到静默不可靠数据。

### M3：Canonical Publication 与统一查询面

目标：从“表里最新一条”升级为“被质量门正式发布的一条”。

交付：

- [x] CanonicalPublication、PublicationMember、CoverageSnapshot。
- [x] D0-D9 的 Publication Policy（治理投影与 `DatasetPublicationPolicyModel` active rows 均有校验）。
- Publication、SyncRun 和关键查询响应记录 runtime config snapshot_id/hash。
- [x] 小型 Public Query Ports 和版本化 DTO。
- [x] as_of / publication_id / current 三种明确查询模式（published gate 已提供；全入口强制切换未完成）。
- [x] shadow read 通过 `ReconciliationEvidence` 记录 legacy 与 canonical 差异，不影响用户响应（生产导出/观察窗口仍待完成）。
- 查询预算、索引和批量接口。

测试：

- 同自然键多来源、多修订和冲突仲裁。
- 未发布事实不可出现在 current。
- as_of 不读取未来 available_at。
- Cache 不改变 source time 或 reliability。
- QuerySet N+1 和 P95 基线。

退出条件：

- 所有 current 查询均可只依赖 Publication。
- 所有差异都有稳定分类：相同、预期差异、数据缺失、语义冲突、代码缺陷。
- 未切业务消费者，不删除旧表。

回滚：feature flag 将查询恢复旧路径；保留影子记录。

### M4：资产、行情与净值迁移

范围：D0、D1、D2、D6。

交付：

- Asset Master/Alias 全量对齐。
- PriceBar、QuoteSnapshot、FundNav 补齐统一证据列和约束。
- realtime、account、portfolio、simulated_trading、broker_execution、backtest、fund、asset_analysis 切换。
- StockDailyModel 进入只读冻结。
- GET 行情路径彻底无写副作用。

测试：

- A 股、ETF、指数、基金、BSE、停牌、新股、退市边界。
- OHLC、复权、volume/amount 单位和交易日历。
- 周末、节假日、盘前、盘中、盘后 freshness。
- 可执行价格强约束；missing/stale 不得成交。
- 全市场批量性能和连接占用。

退出条件：

- 目标 universe 的价格/净值覆盖达到各 Dataset Contract 阈值。
- 所有消费者零 legacy read。
- 连续至少 3 个交易日及 1 个周末/节假日边界影子对账通过。

回滚：按 dataset flag 恢复读路径；旧表保持只读，维护阻断按质量结果决定。

### M5：宏观数据迁移

范围：D3。

交付：

- MacroFact、IndicatorCatalog、IndicatorUnitRule、PublisherCatalog 成为唯一 runtime 真源。
- MacroIndicator 历史数据按指标、周期、来源、修订映射。
- regime、pulse、policy、agent_runtime 全部改走 MacroDataQueryPort。
- 对 canonical/legacy 冲突生成可解释报告，不靠覆盖写消失。
- 发布期、可用期和修订用于 Point-in-Time 查询。

测试：

- 单位归一、月份/季度/年度 period、发布时间 lag、修订。
- 0041/0044/0045/0047 同类语义回归样例。
- HP/Kalman 业务算法输入只取 as_of 可用数据。
- 至少覆盖两个实际调度周期的影子对账。

退出条件：

- MacroIndicator 零读写。
- 所有受管指标有契约、Provider Binding 和发布证据。
- Regime/Pulse/Agent 对同一 as_of 得到同一事实版本。

回滚：恢复旧读 flag；不回写旧表；继续 fail closed。

### M6：财务、估值与个股研究迁移

范围：D4、D5。

交付：

- equity FinancialDataModel / ValuationModel 历史回填。
- FinancialFact 增加 announced_at / available_at；ValuationFact 增加质量和 publication。
- equity Domain 实体将真正可缺失指标改为 T | None，并携带 reliability。
- 删除所有 missing → 0.0 转换。
- alpha/factor 使用批量 FundamentalDataQueryPort，消除 per-stock N+1。
- 财务/估值外部同步任务迁入 Data Center；equity 只保留领域分析任务。
- equity.read.research_snapshot 使用同一 publication 证据。

测试：

- 报告期、公告期、TTM、修订、合并/母公司口径。
- PE/PB/PS/股息率空值、负值、零值和异常范围。
- 5,000+ 证券批量查询与打分。
- REST/SDK/MCP/Terminal 同一证券事实一致。
- 通富微电固定业务样例按上游证据动态验收，不写死价格。

退出条件：

- FinancialDataModel / ValuationModel 零读写。
- 缺失指标不再参与数值排名。
- 核心 A 股 universe 覆盖达到契约门槛；例外逐证券登记。
- 四入口 reliability 完全一致。

回滚：按 financial/valuation dataset flag 恢复旧读；decision readiness 根据缺失保持阻断。

### M7：板块、新闻与资金流迁移

范围：D7、D8、D9。

交付：

- sector/rotation/hedge 使用 ReferenceDataQueryPort。
- sentiment/events/equity 使用 NewsFlowQueryPort。
- 建立新闻内容哈希、来源许可、发布时间和去重规则。
- 建立资金流字段口径、单位和可比 Provider 组。
- 不支持的 Provider 能力返回 unsupported/missing，不伪造成全覆盖。

测试：

- 成分生效/失效日期和历史回放。
- 新闻重复、空 external_id、时区和抓取延迟。
- 资金流字段映射、单位、空值、负值和跨源偏差。
- 部分覆盖的聚合可靠性。

退出条件：

- 业务 App 无外部 Adapter。
- 不完整数据不会使顶层响应变 fresh。
- 能力与许可限制在用户响应中可见。

回滚：按 dataset flag 切回已验证旧路径；若旧路径不可靠则维持 blocked。

### M8：跨入口收口与派生数据产品

目标：同一事实只解释一次。

交付：

- REST 是外部稳定契约；SDK/MCP 调用同一 API/Application handler。
- Terminal/TUI 只消费发布 DTO。
- Config Center TUI 成为配置搜索、diff、impact preview、激活和回滚的唯一管理员主入口。
- Data Center、Risk Center、估值、策略等配置通过各自 Application Facade 注册，不由 Config Center 直接读取其 ORM。
- Agent Runtime 删除旧事实快照 Repository。
- 跨 App 复用的派生数据登记 Data Product Descriptor：owner、输入 publication_id、算法版本、as_of、可靠性。
- Capability Catalog 与运行 handler 做确定性对账。

测试：

- 契约快照和 schema compatibility。
- 中文证券名称、代码、别名和复合查询。
- 无工具、超时、权限失败、关键证据缺失时无金融事实生成。
- 每个入口的 publication_id、observed_at、source 和阻断原因一致。

退出条件：

- SDK/MCP/Terminal/TUI 无独立事实查询实现。
- 所有跨入口差异测试为零。

回滚：回退入口版本，不回退数据事实与质量门。

2026-08-13 M8 Equity research snapshot 四入口收口：

- 归并 owner 从 MCP runtime handler 上移到 `apps/equity/application/research_snapshot.py`；identity、quote、history、valuation、financial、news、capital flow 与 strict readiness 均由注入端口读取，核心分区 stale/blocked/empty/exception 统一 fail closed，optional 缺失只产生 `partial`。
- 顶层 composition 只使用 Data Center publication-only Public Port 与 core strict readiness；新增 authenticated GET REST 和 SDK 方法，MCP 由 7 次独立调用改为一次 SDK 调用，Agent 继续走同一 capability，四入口不再各自解释 freshness。
- current-data machine contract 已把 Application/REST/SDK/MCP/Agent 链和精确测试登记为 46 个 surface 之一；纯 Application + SDK/MCP 聚合 `39 passed`，architecture boundary/audit 0。
- 明确未完成：当前本机没有项目声明的 Django 5.2 + DRF + Celery 完整 runtime，专属 API tests 已写但未执行；本批只完成 Equity snapshot 这一复合查询，不代表 M8 全域 SDK/MCP/Terminal/TUI 已退出全部独立事实实现，也不代表 Evidence integrated。

### M9：遗留停止与破坏性清理

目标：消灭双真源，而不是隐藏它。

交付：

- 旧事实表写入 feature flag 永久关闭。
- PostgreSQL 访问日志/埋点证明一个完整观察窗口内零读写。
- 删除旧 Adapter、Repository、command、task、bridge、兼容 import。
- 删除已迁移的 SystemSettingsModel 过期字段、关键配置代码 fallback 和 Config Center 对其他 App infrastructure 的直接 import。
- 删除过期测试 fixture 和文档。
- 在独立 release 中执行删表 migration；不与切读同一发布。
- 收紧 architecture_rules、mypy debt 和 dependency baseline。

测试：

- 从空 PostgreSQL 建库到最新 migration。
- 从生产前一版本升级到最新 migration。
- migration rollback rehearsal。
- 全仓 import、URL、Celery task name、beat schedule 和 capability catalog 扫描。

退出条件：

- 无 legacy table、bridge 或 Provider bypass。
- 生产至少一个完整观察窗口零旧访问。
- 破坏性 migration 有已验证备份与恢复时长证据。

回滚：删表前使用 verified PostgreSQL backup；代码保留前一镜像。删表后若回滚，先恢复数据库再回滚代码。

### M10：生产重建、验收与持续治理

目标：以生产事实证明架构完成。

步骤：

1. 启用 decision maintenance，保持基础站点可用。
2. 创建 PostgreSQL custom-format 备份，下载并核对 SHA-256。
3. 记录 Git SHA、镜像、migration、表行数、contract/catalog hash。
4. 部署 schema expand 与新代码。
5. 激活并校验目标 Runtime Config Profile，记录 snapshot hash；reconcile Provider、Schedule、MCP Capability、TUI metadata。
6. 按 D0-D9 顺序执行幂等 backfill。
7. 执行 canonical/legacy shadow reconciliation。
8. 逐 dataset 切换 read flag；任务与发布证据绑定同一 config snapshot。
9. 运行全市场质量、入口一致性、性能和故障注入验收。
10. strict decision readiness 全绿后解除维护。
11. 观察窗口结束后进入 M9 破坏性清理。

退出条件见第 22 节 Definition of Done。任一 P0 数据集失败时保持维护或 blocked，不允许用降低阈值换取上线。

## 16. CI 与架构护栏

### 16.1 新增静态门禁

1. apps/data_center/infrastructure/providers 之外禁止 import tushare、akshare、xtquant、efinance、baostock 及等价外部数据 SDK。
2. Data Center 禁止 import apps/*/infrastructure 和 core/integration/data_center_business_sources。
3. 业务 App 禁止 import apps/data_center/infrastructure。
4. 业务 App 对市场/宏观/财务事实的跨 App 调用只能指向 apps/data_center/application/public.py 或明确的 Application Port。
5. 禁止新增 MacroIndicator、FinancialDataModel、ValuationModel、StockDailyModel 读写。
6. 禁止数值字段使用 value or 0、value or 0.0 处理 missing；允许点必须有显式零值契约和局部豁免说明。
7. 禁止 GET handler 调用 sync、fetch、bulk_upsert、save 或 create。
8. Data Center 新增 shared_task 未登记 celery_task_contracts 直接失败。
9. current/latest/realtime/summary surface 自动发现后未登记 current_data_contracts 直接失败。
10. Storage Guard、Retention、Backup、Readiness 和 Task Monitor 禁止自行定义 90/58/68/74 等容量常量；除部署初始化投影和文档外，所有容量值必须来自 StorageBudgetQueryPort。
11. 新增 env default、Model default、模块常量或 Celery kwargs 形式的运行参数，未登记 runtime_config_contracts 或未声明 bootstrap/static 分类时失败。
12. Config Center 禁止 import 其他 App infrastructure；领域配置统一入口必须调用 owner Application Facade。

### 16.2 强化动态门禁

- current-data manifest 必须登记可执行 pytest nodeid，CI 直接运行，不只检查函数名存在。
- celery manifest 的非法输入、全成功、部分失败、全部失败、零产出、阻断用例按适用矩阵真实执行。
- 关键数据链路必须在 PostgreSQL job 运行，不以 SQLite 通过代替。
- Provider fixture 保存 schema fingerprint；未知变化使契约测试失败。
- 每个迁移阶段运行 migration drift、reverse migration 和空库安装。
- 自动比较 REST/SDK/MCP/Terminal 的 schema 与 reliability。
- 使用 60/90/120 GiB fake policy 运行同一组容量测试，证明预算、水位和阻断行为由配置驱动。
- 无 active StorageBudgetPolicy、策略非法或实际磁盘小于 configured capacity 时，验证 fail-closed 和 effective capacity 下调。
- 每日 canary 只验证证据一致性，不把外网暂时失败误判为代码回归；外网失败必须转为受控 blocked。

### 16.3 现有治理文件

每个阶段同步更新：

- governance/current_data_contracts.json
- governance/celery_task_contracts.json
- governance/architecture_rules.json
- governance/governance_baseline.json
- 新增 governance/data_ownership_contracts.json
- 新增 governance/data_provider_contracts.json 或同等机器投影
- 新增 governance/runtime_config_contracts.json

机器动态数字只写 governance 真源；计划文档不复制会频繁变化的最终数量。

## 17. 测试与验收矩阵

| 层级 | 必测内容 | 环境 |
| --- | --- | --- |
| Domain Unit | 时间、单位、missing/zero、质量、可靠性、仲裁、状态机 | 无 Django |
| Adapter Contract | 真实响应 fixture、schema drift、空值、列变体、错误码 | 离线 fixture |
| Repository | 自然键、约束、批量 upsert、as_of、索引、事务 | PostgreSQL 为主 |
| Migration | 空库、旧版本升级、回滚、数据迁移计数 | PostgreSQL |
| Application | success/partial/noop/blocked/failed、checkpoint、幂等 | Django + fake Provider |
| Integration | Provider → Raw → Standard → Publication → Query | PostgreSQL + fake/受控 Provider |
| Differential | legacy 与 canonical 按自然键/时间/单位对账 | 影子环境 |
| Contract | REST/SDK/MCP/Terminal schema 与 evidence 一致 | 本地服务 |
| E2E | 证券研究、Regime、Pulse、交易价格、回测 as_of | staging / 生产维护态 |
| Fault Injection | 超时、限流、空集、stale、错 schema、冲突、Redis/Celery/DB 故障 | staging |
| Performance | 全市场 backfill、批量查询、readiness、P95、锁和内存 | PostgreSQL 生产规模 |
| Live Canary | 小样本上游对账、观测时间、coverage、catalog drift | 生产只读 |

属性测试建议覆盖：

- 任意合法单位转换可重复执行且不二次放大。
- 任意 missing 输入不会变成数值零。
- 任意非 fresh 状态必然 must_not_use_for_decision=true。
- 任意 fetched_at 早于 observed_at 的事实无法进入 canonical。
- 任意 as_of 查询不会看到 available_at 晚于 as_of 的版本。
- 任意重试不会增加相同自然键、source、revision 的重复行。

每阶段最低验证命令：

~~~text
python scripts/check_current_data_contracts.py
python scripts/check_celery_task_contracts.py
python scripts/check_mypy_regression.py <changed-production-python-files>
python scripts/check_mypy_debt_ceiling.py
python manage.py makemigrations --check --dry-run
python manage.py check
python manage.py check --deploy
pytest <本阶段精确 nodeids> -q
~~~

涉及 terminal / TUI / MCP / SDK / deploy 时，还必须运行项目规定的固定最小回归包。

## 18. 数据 SLO、监控与 Readiness

每个 Dataset Contract 独立定义 SLO，不使用一个全局 freshness 阈值。

### 18.1 SLO 维度

- Freshness：距最近应完成观测/发布的延迟。
- Coverage：目标 universe / 时间区间覆盖率。
- Completeness：关键字段完整率。
- Validity：通过 schema 和范围校验的比例。
- Consistency：可比来源差异率。
- Lineage：可回溯 raw payload / publication 的比例。
- Availability：Query Port 成功率与延迟。
- Recoverability：失败任务可从 checkpoint 恢复的比例。

### 18.2 告警分级

| 级别 | 条件 | 动作 |
| --- | --- | --- |
| P0 | 当前可执行价格错误、时间戳洗白、证据缺失仍发布、跨源严重冲突 | 自动 decision blocked，立即告警 |
| P1 | 核心覆盖跌破门槛、关键 Provider 全部失败、publication 长期不推进 | 对受影响数据域阻断，启动恢复 |
| P2 | 单 Provider degraded、非核心数据 partial、schema 预警 | 告警和计划修复，不洗白 |
| P3 | 性能趋势、配额接近、Raw 保留容量 | 运维排期 |

/api/ready/ 继续只表示基础服务可用；/api/decision-ready/ 汇总 Publication、SLO、Provider、维护态和业务关键分区。一个关键分区失败时不得被平均分数抵消。

## 19. 生产默认 90 GiB 的可配置容量与可持续运行计划

### 19.1 容量约束与设计结论

正式 PostgreSQL 上线时默认创建 production-90g 容量策略档，初始 configured_capacity 为 90 GiB。90 GiB 是部署/初始化配置默认值，不是写死在 Python、Django Model、Celery Task、Docker Compose 或监控规则中的常量。

所有运行组件必须通过同一个 StorageBudgetQueryPort 读取 active StorageBudgetPolicy；禁止各模块自行使用 90、58、68、74 等字面量计算水位。

初始化与修改规则：

1. 首次生产初始化由 Setup/部署配置向初始化用例显式传入容量；生产部署模板默认建议 90 GiB，但可在执行前覆盖。
2. StorageBudgetPolicyModel 不设置不可修改的 default=90；初始化完成后数据库记录是 runtime 唯一真源。
3. 后续通过 Config Center TUI / Application API 修改，并记录旧值、新值、操作者、原因、版本和生效时间。
4. 修改总容量时，所有子预算、水位、预测和任务阻断阈值由策略比例重新计算，无需改代码或重新构建镜像。
5. 文件系统探针每次计算 effective_capacity_bytes；有效上限取 configured_capacity_bytes 与实际可支配容量中的较小值。

production-90g 默认策略需要同时容纳：

- PostgreSQL 表、索引、TOAST、系统目录。
- PostgreSQL WAL、排序临时文件、迁移和索引维护的瞬时空间。
- Raw Payload、Quarantine 和导出中间文件。
- Redis AOF/RDB、Celery 结果、应用证据和日志。
- 当前及上一个 Docker 镜像、容器可写层、构建残留。
- 一份正在生成或等待下载的 PostgreSQL 备份。
- 操作系统和紧急恢复所需的安全余量。

如果 90 GiB 实际只是当前剩余空间而不是挂载点总容量，M0 仍以 active policy 的 90 GiB 作为初始配置；若文件系统实测可支配空间更小，effective capacity 自动下调。文中 GiB 用于展示 production-90g 默认策略的投影；若服务商标称 90 GB 但系统实测不足 90 GiB，所有子预算和水位按实际字节同比缩小。

架构结论：

1. 90 GiB 足以长期承载个人投研平台的主数据、日线、宏观、财务、估值和有限历史，但不可能无限保留全市场 Tick、全市场高频快照、全部新闻正文、所有 Provider 原始响应和多份同机全量备份。
2. VPS 只保存当前决策需要的热数据、有限历史窗口和紧凑的永久审计元数据。
3. 高体量原始数据采用有限保留；需要长期历史时输出到 VPS 之外的冷存储。
4. current 查询、决策证据和业务交易记录优先于广覆盖新闻、原始响应、高频历史和大规模回填。
5. 系统必须在磁盘真正耗尽前自动降级和阻断，不能依靠人工看到 df 已满后再抢救。

### 19.2 当前已确认的容量缺口

| 当前实现 | 状态 | 风险 | 规划动作 |
| --- | --- | --- | --- |
| docker/docker-compose.vps.yml 已为主要容器配置 json-file max-size / max-file | 已有基础保护 | 只能限制 Docker stdout/stderr，不能覆盖应用文件日志和数据卷 | 纳入统一 Storage Usage Snapshot，保留现有上限 |
| Redis 已配置 256 MB maxmemory 和 allkeys-lru | 已有内存保护 | AOF/RDB 大小和重写峰值仍需计入磁盘 | 监测 redis_data 与 AOF rewrite 临时空间 |
| core/settings/production.py 默认 LOG_TO_FILE=false | 默认风险较低 | 开启后两个 100 MB × 10 文件 handler 以及 Celery 文件日志可能叠加 | 统一日志总预算，不只限制单文件 |
| core/settings/base.py 的 database-daily-backup 默认 keep_days=14 | 不适合 90 GiB | 14 份同机全量备份可比生产库本身更大 | 改为 VPS 最多 1 份 in-flight，校验下载后删除 |
| backup_database_task 在 VPS 本地生成 PostgreSQL gzip SQL | 可用但不受总量控制 | 备份生成失败、半成品或清理延迟会吃完磁盘 | 写前检查空间、原子临时文件、单份上限、外部确认后清理 |
| scripts/backup-vps-postgres.py 支持 custom format、校验、下载和远端清理 | 可复用 | prune 默认关闭，仍可能累计 | 生产 runbook 强制远端最多 1 份且不超过 24 小时 |
| DjangoMaintenanceStatusReader 只对数据库 NAME 是本地文件时统计大小 | PostgreSQL 盲区 | Task Monitor 在正式生产库下看不到数据库真实大小 | 改用 pg_database_size、pg_total_relation_size 和文件系统 probe |
| RawAudit、QuoteSnapshot、News 等缺少统一保留策略 | 未闭环 | 高增长表会无限膨胀 | Dataset Retention Policy + 分区 + 自动回收 |

### 19.3 production-90g 默认预算投影

以下数字是 active policy 为 90 GiB 时的默认投影，不是散落在代码中的固定常量。Runtime 保存总容量、子预算比例、最小空闲比例和水位比例；M0 根据真实每行字节、索引比例和备份压缩率调整策略记录，但各子项之和不得超过 effective capacity。

| 类别 | 上限 | 说明 |
| --- | ---: | --- |
| 操作系统、Caddy、当前/上一 Docker 镜像与容器层 | 10 GiB | 只保留当前和可回滚上一版本；禁止 VPS 保留构建缓存 |
| PostgreSQL 持久热集群 | 36 GiB | 包含全系统表、索引、TOAST、catalog 和可复用 bloat 余量 |
| PostgreSQL WAL、临时文件、迁移/索引维护峰值 | 10 GiB | 不作为可长期占用空间 |
| Raw、Quarantine、导出暂存 | 4 GiB | 达配额立即按策略回收或阻断低优先级采集 |
| 单份 PostgreSQL 备份 in-flight | 10 GiB | 下载并校验后删除；超过此值必须采用流式或外部备份 |
| Redis、Celery、应用日志、readiness evidence | 3 GiB | 统一总量，不允许多个轮转器各自无限增长 |
| static、media、配置与小型运行资产 | 2 GiB | 用户上传另行按 owner 配额 |
| 永久紧急空闲空间 | 15 GiB | 不分配给任何常态数据，用于故障恢复和维护峰值 |
| **合计** | **90 GiB** | 任一子项超支必须从同类别回收，不能借用紧急余量常态运行 |

PostgreSQL 36 GiB 的初始内部预算：

| PostgreSQL 数据类别 | 上限 | 说明 |
| --- | ---: | --- |
| Data Center catalog、publication、sync、quality、lineage | 3.5 GiB | 元数据长期保留，明细运行记录分级清理 |
| 日线 PriceBar | 8 GiB | 全核心 universe 的有限热历史 |
| Latest Quote 与短期 QuoteSnapshot | 1.5 GiB | 全市场只保留最新值和收盘事实；盘中历史限范围、限时 |
| Macro 与 Sector | 1.5 GiB | 体量小，保留全部 canonical 修订和成员历史 |
| Financial Fact | 5 GiB | canonical 财务事实和修订优先永久保留 |
| Valuation Fact | 6 GiB | 日频窗口有限，旧数据归档或降采样 |
| Fund NAV | 2.5 GiB | 研究 universe 长窗口，非核心 universe 短窗口 |
| News 与 Capital Flow | 3 GiB | 正文、原始响应短保留；聚合和紧凑元数据长保留 |
| 非 Data Center 业务表 | 3 GiB | account、portfolio、audit、auth、配置和其他业务状态 |
| PostgreSQL 内部可复用 bloat 余量 | 2 GiB | 用于 vacuum 复用；不是新增业务配额 |
| **合计** | **36 GiB** | 子预算通过运行时配置管理 |

预算规则：

- 子预算是硬 ceiling，不代表预留；未使用空间仍属于全局紧急余量。
- 任何新 Dataset 上线前必须给出预计 rows/day、bytes/row、index ratio、hot days 和最大 GiB。
- 如果一个数据集达到自身配额，优先归档、降采样或暂停该数据集，不能自动挤占其他核心数据。
- 交易、持仓和审计数据不因 Data Center 超额而自动删除。

### 19.4 文件系统水位与自动动作

水位读取底层挂载点实际 used/available，不能只看 PostgreSQL database_size 或 Docker volume 声称的逻辑大小。任务使用 active policy 中的比例和最小空闲值；下表绝对值只是 production-90g 默认策略的显示投影。

| 状态 | 策略触发条件 | 90 GiB 默认投影 | 自动动作 |
| --- | --- | ---: | --- |
| green | used_ratio 小于 65% | 小于约 58 GiB | 正常同步；每天执行到期清理；更新增长预测 |
| yellow | used_ratio 65%-75% | 约 58-68 GiB | 告警；立即清理已过期 Raw、日志、旧备份和成功任务明细；禁止启动非必要全量导出 |
| orange | used_ratio 75%-82% | 约 68-74 GiB | 暂停 P3 采集和历史大回填；强制转移/删除 in-flight 备份；执行可安全 drop 的到期分区 |
| red | used_ratio 82%-83.33% | 约 74-75 GiB | 暂停 P2/P3；只允许 P0 业务写入和最小 P1 增量；禁止镜像构建、REINDEX、VACUUM FULL 和大 migration |
| critical | used_ratio 大于等于 83.33%，或 available 低于 emergency_reserve | 大于等于约 75 GiB，或 available 小于 15 GiB | 紧急余量已被侵占；停止所有 Data Center 批量写入；进入 storage blocked；decision readiness 失败；只允许查询、外部备份、清理和受控恢复 |
| filesystem emergency | used_ratio 大于等于 90%，或 available 低于 emergency_floor | 大于等于约 81 GiB，或 available 小于 9 GiB | 全局 decision maintenance；停止 Celery ingest；禁止在 VPS 创建新备份；必须人工处置 |

优先级：

- P0：账户、订单、成交、持仓和不可丢审计写入。
- P1：维持当前决策所需的资产身份、最新行情、核心宏观和最小财务增量。
- P2：估值/财务全市场补历史、长期日线、基金广覆盖。
- P3：全市场盘中快照、广覆盖新闻、Raw 成功响应、非关键报表和实验数据。

磁盘压力下按 P3 → P2 → P1 顺序停止。若 P1 被迫停止，对应 current 数据会变 stale，decision readiness 必须自动阻断，不能继续发布旧值。

### 19.5 数据保留矩阵

保留规则同时受“时间窗口”和“字节配额”限制；先触发者生效。达到配额时必须先尝试压缩、归档或降采样，不能静默删除仍声明受支持的历史。

| 数据集 | VPS 热保留默认 | 长期保留内容 | 超限动作 |
| --- | --- | --- | --- |
| Asset Master / Alias / Dataset Contract / Provider Binding | 永久 | 全部有效版本与必要审计 | supersede 旧运行版本；不删被 Publication 引用版本 |
| Canonical Publication | 元数据永久 | publication_id、选择策略、自然键范围、source、hash、可靠性 | 大 payload 不复制，只保留引用 |
| Macro Fact | canonical 全历史与修订永久 | reporting/published/available time、单位、来源 | 原始响应按 Raw 策略清理 |
| PriceBar 日线 | 核心 universe 10 年或 8 GiB | 日线 canonical、复权语义、publication | 更旧年度分区先冷归档；无冷存储时缩短产品承诺并显式披露 |
| 全市场 Latest Quote | 每资产/来源只保留当前一行 | 当前观测时间、抓取时间、source | 采用 upsert current 表，不做无限 append |
| QuoteSnapshot 盘中 | 仅持仓、自选、基准；原始 7 个交易日 | 5 分钟 rollup 最多 20 个交易日；决策引用保存紧凑 evidence | 全市场盘中 append 默认关闭；到期 partition drop |
| 全市场收盘快照 | 每交易日 1 条并归入日线事实 | PriceBar | QuoteSnapshot 不重复长期保存 |
| Financial Fact | canonical 事实与修订永久，目标 5 GiB | period_end、announced/available、口径、revision | 先删重复 source 非发布版本的 Raw；canonical 不自动删 |
| Valuation Fact | 日频 5 年或 6 GiB | 更旧数据保留月末/季末 rollup 或外部归档 | 年度 partition 归档后 drop |
| Fund NAV | 持仓/自选/研究 universe 10 年；其他 active fund 3 年或 latest | canonical NAV 与发布日期 | 先收缩非核心 universe 历史 |
| Sector Membership | 全历史永久 | effective/expiry/source | 只清理重复或无效 Raw |
| News Raw / 正文 | 成功响应 7 天；失败/隔离 30 天；正文最长 14 天 | URL、标题、发布时间、内容 hash、来源许可 | 正文先删；不影响紧凑新闻事实 |
| News 规范化元数据 | 180 天明细 | 日级情绪/事件聚合长期保留；关键事件引用保留 | 归档或删除非引用明细 |
| Capital Flow | 全市场日频 2 年；持仓/自选可 5 年 | 更旧月度 rollup 最多 5 年 | 日频旧分区归档或 drop |
| Raw 成功响应 | 7 天或 Raw 总额 4 GiB | hash、schema fingerprint、行数、时间范围永久 | 按最旧、非引用、P3 顺序清理 |
| Raw 失败 / Quarantine | 30 天 | 错误码、schema fingerprint、修复结论长期聚合 | 明细到期清理 |
| 决策关联 Raw | 最长 90 天 | 永久保存紧凑 Decision Evidence 与 raw hash，不永久复制大响应 | 超期删除 payload，保留过期标记 |
| SyncRun / Task Monitor 成功明细 | 14 天 | 日级成功率、计数、耗时聚合 2 年 | 明细批量/分区清理 |
| partial / failed / blocked 任务明细 | 90 天 | 失败类别和恢复证据聚合 | 关闭事件后按策略清理 |
| Provider Health 原始采样 | 90 天 | 日级 P50/P95、成功率、coverage 2 年 | rollup 验证后删原始 |
| 应用与 Celery 文件日志 | 14 天且总额不超过 1 GiB | 事故日志按 evidence 显式保留 | 轮转并按总额二次清理 |
| Docker 容器日志 | 保持 compose max-size/max-file | 不长期保留 | 由 Docker 自动轮转 |
| PostgreSQL 备份 | VPS 最多 1 份且不超过 24 小时 | 外部位置执行 7 日 / 4 周 / 12 月保留策略 | 本地 SHA-256 验证后删除 VPS 备份 |

说明：

- “永久”只适用于紧凑 canonical 事实、配置和审计元数据，不代表永久保留完整 Provider 响应。
- 研究/交易引用不通过保留整批 Raw 实现，而保存紧凑 Decision Evidence：publication_id、输入事实自然键、值、时间、source、contract_version 和 hash。
- 如果未配置 VPS 外冷存储，系统仍可持续运行，但高体量数据只承诺上述热窗口，不承诺无限历史。

### 19.6 热、温、冷三层

#### 热层：VPS PostgreSQL

只包含当前业务和常用查询需要的数据：

- 当前与有限历史 canonical fact。
- 活跃 Publication。
- 热窗口内的质量、运行和 Provider 证据。
- 业务交易与审计记录。

查询 API 不跨越 VPS 到冷存储，避免 current 请求因本地电脑或外部对象存储离线而失败。

#### 温层：VPS 压缩短期文件

只允许：

- 单份 in-flight 数据库备份。
- 待上传归档分区。
- 短期 Raw 压缩文件。
- 失败恢复 checkpoint。

每个温层对象必须有 created_at、expires_at、size_bytes、owner 和 cleanup state；无 owner 文件视为泄漏。

#### 冷层：VPS 之外

可以是用户本地电脑、NAS 或受控对象存储。冷归档至少包含：

- dataset_key 与 contract_version。
- partition key / 日期范围。
- row_count。
- source 和 publication 范围。
- 原始与压缩字节数。
- SHA-256。
- schema fingerprint。
- created_at、加密和保存位置。
- restore 验证结果。

冷归档推荐使用压缩、列式、可校验格式保存事实分区；数据库完整恢复仍使用 PostgreSQL custom-format backup。两者不能互相替代。

只有在外部对象上传完成、SHA-256 一致、行数和日期范围验证、抽样读取成功后，才允许删除 VPS 热分区。

### 19.7 PostgreSQL 表设计、索引与分区

#### 分区候选

满足以下任一条件才进入分区评估：

- 单表预计超过 500 万行。
- 单表总大小超过 2 GiB。
- 存在稳定时间列且需要周期性删除。
- 单次历史清理会触发大规模 DELETE 和 bloat。

优先候选：

- QuoteSnapshot：按日或月。
- RawAudit / RawPayload：按日或月。
- NewsFact：按月。
- CapitalFlowFact：按年或月。
- PriceBar / ValuationFact：达到阈值后按年。
- Sync/Provider 原始明细：按月。

不对 AssetMaster、Catalog、Macro 等小表盲目分区。

实现约束：

- 使用新的可回滚 Django migration 或明确的 PostgreSQL migration 方案，不编辑已应用 migration。
- 先建新分区表、双写仅限 ingestion 边界、回填与影子对账，再切换。
- 到期数据优先 DROP PARTITION，避免数百万行 DELETE。
- 无法分区的表使用固定批次按主键/日期删除，每批提交并记录 checkpoint。

#### 索引预算

- 每个索引必须对应真实 filter/order/join 查询。
- 定期读取 pg_stat_user_indexes，候选未使用索引需经完整观察窗口确认后删除。
- 避免 unique constraint 与手工相同前缀索引重复。
- 超大追加时间表优先评估 BRIN 时间索引，核心 point lookup 保留 B-tree 复合索引。
- PostgreSQL cluster 的索引总大小目标不超过表数据大小的 40%；超过时必须逐表解释。

#### Vacuum 与维护空间

- 普通 VACUUM 回收空间供 PostgreSQL 重用，但通常不会把文件还给操作系统；容量面板必须区分 reusable bloat 与 filesystem free。
- VACUUM FULL 需要额外磁盘并产生长锁，yellow 以上禁止执行。
- REINDEX CONCURRENTLY 会临时持有新旧两份索引，yellow 以上禁止执行。
- 大 backfill 监控 WAL 增长，按批次提交；超过 WAL 预算自动暂停。
- 删除分区后验证 relation size、WAL 和查询计划，不用“DELETE 成功条数”冒充实际腾出磁盘。

### 19.8 容量测量与预测

新增 Storage Usage Snapshot，至少每小时记录：

- 文件系统 total / used / available。
- PostgreSQL database、schema、table、index、TOAST 大小。
- dead tuple、live tuple、relation bloat 估计。
- pg_wal 实际大小。
- Redis volume、AOF/RDB 大小。
- Docker images、containers、volumes、build cache 大小。
- backup、Raw、logs、media、var/evidence 目录大小。
- 每个 Dataset 当日 row count、bytes 和增长量。

每个高增长 Dataset 计算：

~~~text
平均每行总字节 = pg_total_relation_size / 估算有效行数
日增长字节 = 日新增行数 × 平均每行总字节
30 日增长斜率 = 当前大小 - 30 日前大小
到达水位天数 = 水位剩余字节 / max(日增长斜率, 最小正值)
建议热窗口 = Dataset 字节配额 / P90 日增长字节
~~~

告警：

- 预计 30 天内到 orange：P2。
- 预计 14 天内到 red：P1。
- 预计 7 天内到 critical：P0。
- 任一 Dataset 7 天增长超过自身配额 10%：P1。
- 备份压缩后大小超过 10 GiB 或增长率连续三次异常：P1，改用流式/外部备份并重新评估热库上限。

容量预测必须基于实测 relation size，不能使用 Python 对象大小或简单行数猜测。

### 19.9 自动保留与清理控制面

新增或收敛以下运行时对象，并保持 desired config 与 observed state 分离：

- config_center.StorageBudgetPolicyModel：configured_capacity_bytes、策略版本、各子预算比例、水位比例、emergency_reserve_ratio、emergency_floor_ratio 和是否 active。
- data_center.DatasetRetentionPolicyModel：dataset_key、priority、hot_days、max_bytes、rollup、archive_required、delete_order。
- task_monitor / operational_readiness 的 StorageUsageSnapshotModel：容量 observed state 时间序列，不作为配置。
- data_center.RetentionHoldModel：因交易、研究、事故或合规原因禁止清理的数据范围。
- data_center.ArchiveManifestModel：外部归档、hash、行数、范围和 restore 结果。
- data_center.RetentionRunModel：计划、dry-run、实际删除/归档、字节和 outcome。

全局容量规则以 Config Center active profile 为唯一真源；Dataset 生命周期规则由 Data Center 类型化表拥有，并注册到 Config Center 统一入口。Task Monitor / Operational Readiness 通过 Config Center StorageBudgetQueryPort 读取 desired policy，通过自己的只读端口读取 observed usage，不复制阈值。Model、settings、task 和 compose 中均不得设置独立的 90 GiB fallback。

容量策略切换必须原子化：新策略校验通过后再激活，旧策略保留审计版本；无 active policy 时生产 storage readiness 必须 blocked，不能在代码里悄悄回退到 90。

建议任务：

| 任务 | 周期 | 行为 |
| --- | --- | --- |
| collect_storage_usage_task | 每小时 | 只读采集整盘、PostgreSQL、Docker、Redis 和目录大小 |
| forecast_storage_capacity_task | 每日 | 计算 7/30/90 日趋势和到水位天数 |
| plan_retention_task | 每日 | 生成 dry-run 候选、预计回收字节和 hold 冲突 |
| enforce_retention_task | 每日低峰 | 只执行已到期、无 hold 的策略；分区优先 |
| rollup_operational_metrics_task | 每日 | 先聚合再清理原始健康/任务明细 |
| verify_storage_budget_task | 每次 backfill/backup/deploy 前后 | 超水位则阻断下一批 |
| audit_archive_restore_task | 每月 | 抽样恢复冷归档和数据库备份 |

这些任务都必须登记 governance/celery_task_contracts.json，并覆盖 success、partial、noop、blocked、failed、零产出和非法策略。

### 19.10 安全清理流程

任何自动删除必须经过：

1. 读取 active Retention Policy 和当前水位。
2. 生成候选自然键/分区、行数、逻辑字节和预计实际回收字节。
3. 排除 active Publication、Retention Hold、未完成审计和未过最小窗口的数据。
4. 若 archive_required，先生成外部归档并校验 manifest。
5. dry-run 证据持久化。
6. 使用 partition drop 或固定批次删除。
7. 验证行数、时间范围、Publication 引用完整性和查询可用性。
8. 记录实际回收字节；区分“可供 PostgreSQL 重用”和“已归还文件系统”。
9. 发布标准 outcome。

禁止：

- 使用无日期/无自然键条件的全表 delete。
- 清理任务跟随 CASCADE 删除业务决策、订单或审计记录。
- 未验证外部归档就删除 archive_required 数据。
- 因磁盘告警直接删除最新 canonical 数据。
- 在 red/critical 水位运行 VACUUM FULL、REINDEX 或生成第二份备份。

### 19.11 备份策略

VPS 本地备份不是持久备份，只是传输暂存。

目标流程：

1. 备份前 verify_storage_budget，预计生成文件后仍必须低于 red。
2. 使用 PostgreSQL custom format 和压缩。
3. VPS 同时只允许一个 .partial 或一个完整 dump。
4. 在 VPS 执行 pg_restore --list 和 SHA-256。
5. 下载到 VPS 之外。
6. 本地再次校验 size 和 SHA-256。
7. 至少定期执行隔离恢复，而不是只验证文件头。
8. 本地确认成功后立即删除 VPS dump；最长不超过 24 小时。

外部保留默认：

- 最近 7 个日备份。
- 最近 4 个周备份。
- 最近 12 个月备份。

该保留发生在 VPS 之外，不计入 90 GiB。现有 database-daily-backup 的 keep_days=14 必须在容量治理阶段调整；在调整前不得同时启用另一套每日全量备份，避免重复。

若一次 compressed dump 超过 10 GiB：

- 禁止继续在 VPS 累积。
- 优先采用流式传输或直接写外部目标。
- 重新评估 PostgreSQL 36 GiB 热库预算和可压缩率。
- 不以删除唯一已验证外部备份换取空间。

### 19.12 Docker、Redis 与日志

- VPS 只保留当前和上一个可回滚 Web 镜像；部署成功并通过观察后清理更旧镜像和 build cache。
- 禁止 docker system prune --volumes 作为常规容量动作；volume 删除必须逐个验证 owner，PostgreSQL/Redis volume 永不由通用 prune 删除。
- 保留现有 json-file max-size/max-file，并将所有容器日志总量纳入 3 GiB 预算。
- LOG_TO_FILE=true 时应用文件日志总额不得超过 1 GiB；避免 console + 两份文件 handler 重复保存相同高频日志。
- Redis maxmemory 继续限制为 256 MB 级别；监控 AOF rewrite 临时文件，定期验证持久化文件体积。
- Celery Result Backend 设置有限 TTL；Task Monitor 业务证据按第 19.5 节在 PostgreSQL 聚合后清理。
- readiness evidence、导出文件和失败诊断包必须具备过期时间和 owner。

### 19.13 与 M0-M10 的集成

| 阶段 | 容量治理交付 |
| --- | --- |
| M0 | 采集整盘、PostgreSQL relation、WAL、Docker、Redis、backup、logs 的真实基线；生成 12 个月预测 |
| M1 | 建立可版本化 Storage Budget / Dataset Retention / Hold / Archive Contract，并由部署配置初始化 production-90g profile |
| M2 | StoragePressureGuard 接入所有 ingest、backfill、backup；新增 usage/forecast/retention 任务 |
| M3 | Publication 引用和 Retention Hold 防止被误删 |
| M4 | Quote/Price/Nav 的 upsert、短保留、rollup 和首批分区 |
| M5 | Macro 永久 canonical + Raw 短保留 |
| M6 | Financial 永久 canonical、Valuation 有限日频窗口 |
| M7 | News 正文短保留、Capital Flow rollup |
| M8 | Decision Evidence 替代长期保存大 Raw Payload |
| M9 | 旧表和旧备份清理，释放双真源占用 |
| M10 | production-90g 默认策略及可变容量策略的峰值演练、外部恢复和 critical 水位故障注入 |

### 19.14 容量验收标准

- [ ] M0 能解释文件系统至少 95% 已用空间的 owner。
- [ ] production-90g 默认策略下，常态清理后整盘使用量小于约 58 GiB；其他容量策略按 green ratio 计算。
- [ ] production-90g 默认策略下，一次正常增量同步 + 一份 in-flight 备份的峰值小于约 68 GiB；其他策略不得越过 yellow 上界。
- [ ] production-90g 默认策略下，一次受控全市场 backfill 的 WAL/临时峰值小于约 74 GiB；其他策略不得越过 orange 上界。
- [ ] 紧急可用空间满足 active policy 的 emergency_reserve；低于 emergency_floor 时绝不显示 ready。
- [ ] PostgreSQL 持久热集群不超过 active policy 的 PostgreSQL 子预算；production-90g 默认投影为 36 GiB。
- [ ] Raw/Quarantine 不超过 active policy 子预算；VPS 备份最多 1 份。
- [ ] 所有预计超过 2 GiB 或 500 万行的时间表有分区/批量清理决策。
- [ ] 每个 Dataset 有 max_bytes 和 hot window，且达到配额时有确定动作。
- [ ] 30 天稳态观察后，到 orange 的预测天数大于 365 天，或增长被稳定 retention 截平。
- [ ] yellow/orange/red/critical 故障注入能按优先级停止任务。
- [ ] critical 状态下 current 查询仍可只读返回，但 decision readiness 明确 storage blocked。
- [ ] 冷归档抽样恢复、数据库备份隔离恢复和 hash 验证通过。
- [ ] 删除任务不会破坏 Publication、Decision Evidence、交易和审计引用。
- [ ] Task Monitor 能显示 PostgreSQL、索引、WAL、Docker volume、备份和日志，不再只显示 SQLite 文件大小。
- [ ] 将 active capacity 从 90 GiB 改为 60 GiB 和 120 GiB 时，水位、子预算、预测和任务阻断无需改代码即可同步变化。
- [ ] 无 active StorageBudgetPolicy 时，生产 readiness 为 blocked；不存在代码级 90 GiB fallback。

达到以上标准，才能认为系统在 production-90g 默认策略以及其他受管容量策略下具备可持续运行能力。仅配置 cron 删除文件或偶尔执行 Docker prune 不算容量治理完成。

## 20. 生产切换与回滚设计

### 20.1 硬门禁

- 未验证 PostgreSQL backup 与 SHA-256：禁止 destructive migration。
- 未启用 decision maintenance：禁止清理或重建 current 数据。
- 未完成 shadow reconciliation：禁止切读。
- 未完成一个观察窗口的零旧访问证明：禁止删旧表。
- 未运行 PostgreSQL migration / integration：禁止宣称生产就绪。
- 任一 P0 数据集 status 非 fresh：禁止解除对应决策入口阻断。
- 生产切换、回填和备份的预测峰值将使整盘进入 red：禁止开始。

### 20.2 回滚层级

| 层级 | 场景 | 回滚动作 |
| --- | --- | --- |
| R1 查询 | 新 read model 结果异常 | dataset read flag 切回旧路径，保留 blocked 规则 |
| R2 Provider | 新 Adapter 失败 | Provider Binding 切回上一个受验证版本 |
| R3 发布 | 错误 canonical selection | supersede Publication，恢复前一 publication_id |
| R4 代码 | 应用回归 | 部署上一镜像/Git SHA |
| R5 数据库 | 迁移或回填破坏数据 | 进入维护，恢复 verified PostgreSQL backup |

回滚不等于恢复对不可靠旧数据的放行。若旧路径同样无法证明可靠，系统必须继续 blocked。

## 21. 组织方式、提交切分与建议工期

### 21.1 Owner

| 角色 | 责任 |
| --- | --- |
| Data Platform Owner | Dataset Contract、Provider、事实表、Publication、同步和 SLO |
| Business App Owner | 消费端口、领域语义、派生结果和业务回归 |
| Reliability Owner | freshness、conflict、readiness、故障注入和事故复盘 |
| Operations Owner | PostgreSQL backup、容量预算、保留/归档、部署、调度、告警、回滚 |
| Test Owner | nodeid 清单、PostgreSQL 集成、E2E 和证据包 |

同一人可以兼任，但每个阶段必须显式写 owner，不能以“团队”代替。

### 21.2 分支与提交

遵守“一条大主线 + 一个小收口”：

1. dev/docs-data-center-canonical-plan：计划、清单 schema、ADR。
2. dev/refactor-data-contract-foundation：Domain 契约与 Catalog。
3. dev/refactor-data-ingestion-control-plane：Provider、Raw、SyncRun。
4. dev/refactor-data-publication-query：Publication 与 Query Ports。
5. 每个 D0-D9 数据域使用独立 dev/refactor-* 分支或独立 commit 组。
6. dev/test-data-platform-guardrails：CI、PostgreSQL、故障注入。
7. dev/ops-data-center-cutover：部署脚本、runbook、证据，不与业务实现混成一个 commit。

任何一个批次跨 Python、模板/JS、配置、文档中的 3 类以上时继续拆分。

### 21.3 粗略工程量

以下只用于排资源，不是验收承诺；假设 1 名主开发 + 1 名兼职复核、Provider 无重大许可变化：

| 阶段 | 估算 |
| --- | --- |
| M0-M1 | 2-3 工程周 |
| M2-M3 | 3-4 工程周 |
| M4-M6 | 4-6 工程周 |
| M7-M8 | 2-3 工程周 |
| M9-M10 | 2-3 工程周 |

单人串行预计 12-16 个日历周；两人按数据域并行但保持一个架构 owner 时预计 8-12 周。若生产回填、Provider 配额或历史语义冲突扩大，工期以退出条件为准，不以日期强行切换。

## 22. Definition of Done

### 22.1 架构

- [x] Data Center Infrastructure 是唯一外部数据接入位置（静态 provider import 清单为 0；运行生产画像未完成）。
- [x] Data Center 不反向 import 业务 infrastructure 或 core/integration 数据桥。
- [x] 业务 App 不直接读 Data Center ORM，只使用 Application Public Port（生产代码已清除，测试 fixture 例外保留）。
- [ ] 全仓无同类外部事实双真源。
- [x] shared 无外部金融数据 Provider Client。
- [ ] Config Center 拥有全局运行参数的 Definition/Profile/Value/Revision/Snapshot，并提供统一 TUI/Application 入口。
- [ ] 领域配置均登记 owner，并通过 owner Application Facade 接入；Config Center 无跨 App ORM。
- [ ] SystemSettingsModel 不再继续膨胀，过期字段和关键代码 fallback 已完成迁移/退役。

### 22.2 数据

- [ ] D0-D9 全部有版本化 Dataset Contract、Provider Binding、质量和发布策略。
- [ ] 每条决策事实可回溯到 raw hash、Provider、contract_version 和 publication_id。
- [x] missing 不再被转换为 0（本批涉及的财务/估值/宏观路径；全仓审计仍需继续）。
- [ ] current/latest 只返回有效 Publication。
- [ ] as_of 查询不产生后视偏差。
- [ ] legacy/canonical 差异全部关闭或登记为有 owner、有期限的例外。

### 22.3 可靠性

- [ ] fresh/stale/missing/partial/conflict/maintenance/failed 语义跨入口一致。
- [ ] observed/published/available/fetched 时间沿链路保真。
- [x] stale 主源继续 failover。
- [x] 跨源冲突不静默发布（Publication UseCase/Provider Registry；全 D0-D9 生产切读未完成）。
- [ ] 关键证据缺失时所有决策入口 fail closed。

### 22.4 任务与运维

- [ ] 所有数据写入任务具备边界校验、幂等、checkpoint 和标准 outcome。
- [x] stored=0 不再无条件 success。
- [x] Provider、Schedule、MCP Catalog 可确定性 reconcile contract（实际生产 reconcile 尚未接入）。
- [ ] 覆盖、新鲜度、健康、冲突和发布进度可监控。
- [ ] PostgreSQL 备份、恢复和 rollback drill 有真实生产证据；GitHub Nightly 已提供当前候选的 PostgreSQL custom backup/隔离 restore/schema 对比子证据，生产维护态 rollback 仍未演练。
- [ ] 整盘、PostgreSQL、WAL、Docker、Redis、Raw、备份和日志纳入同一 active StorageBudgetPolicy 水位控制。
- [ ] Retention、Rollup、Archive、Hold 与 StoragePressureGuard 实际运行并通过故障注入。
- [ ] VPS 不保留超过 1 份或 24 小时的完整数据库备份。

### 22.5 消费者

- [ ] macro、regime、pulse、equity、alpha、factor、valuation、realtime、fund、sector、rotation、hedge、sentiment、backtest、account、portfolio、agent_runtime 等均完成迁移。
- [ ] REST、SDK、MCP、Terminal、TUI 同一事实的 publication_id 和 reliability 一致。
- [ ] 旧表、旧 Adapter、旧 Bridge、旧 task 和旧 fixture 已删除。

### 22.6 测试与治理

- [x] current-data 与 Celery manifest 中的 pytest nodeid 在 CI 实际执行（当前候选 `578064409b8269e440ba7edbf9c480aa7d9917ff` 的 Nightly run `32276242287` artifact：current-data `349 passed`、Celery `220 passed`）。
- [x] 核心链路在 PostgreSQL 通过（同一 run 的 `Critical Reliability (PostgreSQL)` job 成功；保留 1 个明确的 SQLite fallback concurrency skip）。
- [ ] Provider schema drift、故障注入、性能和全市场回填通过。
- [ ] runtime_config_contracts 覆盖所有受管运行参数，非默认 profile 和无 active profile 测试通过。
- [x] 新增绕过路径被 CI 拒绝（architecture/current-data/celery/catalog guards）。
- [ ] governance baseline、文档、runbook 和数据字典同步更新。

只有上述全部完成，才可以写“所有数据已走数据中台”。“已有 Data Center App”“接口能返回数据”或“单元测试通过”均不等于完成。

## 23. 风险登记

| 风险 | 预警信号 | 缓解 | 回滚触发 |
| --- | --- | --- | --- |
| Data Center 变成上帝模块 | public.py、models.py、tasks.py 再次急剧膨胀 | 按数据职责拆 Port/Repository；业务算法留原 App | 出现跨业务决策逻辑 |
| Config Center 变成无类型上帝表 | 所有领域参数塞入一个 JSON、owner 校验消失 | 中央目录 + 联邦 owner；复杂配置保留类型化表 | 出现跨领域 ORM 或裸 value_json 消费 |
| 配置双真源 | DB、env、settings 和模块常量对同一 key 给出不同值 | runtime_config_contracts、resolved snapshot、禁止隐形 fallback | 同一任务节点解析出不同 snapshot hash |
| 循环依赖回流 | Data Center import core/integration 或业务 infrastructure | CI import graph + composition root | 新增 app 级 cycle |
| 双写长期化 | 同一数据域两个任务持续写 | 每域到期门、访问遥测 | 差异无法解释 |
| 语义映射错误 | Provider 非空但跨源差异大 | Dataset Contract + fixture + quarantine | conflict 超阈值 |
| 回填压垮 PostgreSQL | 锁等待、连接耗尽、长事务 | chunk、bulk、checkpoint、限速 | P95/锁超过预算 |
| Provider 配额不足 | 429、覆盖停滞 | 能力级调度、退避、备用源 | 核心覆盖无法达标 |
| Cache 洗白时间 | observed_at 随读取变化 | 缓存完整 Envelope；publication key | 入口时间不一致 |
| SQLite 假绿 | 本地过、PostgreSQL 失败 | 关键测试强制 PostgreSQL | migration/integration 失败 |
| Raw Payload 泄密或膨胀 | Token 入库、容量异常 | 脱敏、压缩、分级保留、权限 | 检测到敏感字段 |
| 破坏性迁移不可逆 | 删表与切读同发布 | 分发布、backup、恢复演练 | 无恢复证据 |
| active 容量策略被数据/备份/WAL 吃满 | 可用空间下降、到水位天数缩短、备份异常增长 | 运行时预算、水位阻断、分区清理、VPS 外备份 | 进入 red 或预计峰值越线 |

## 24. 默认决策与待 ADR 项

为避免执行时反复摇摆，先采用以下默认值；如需修改，必须新增 ADR：

1. 类型化事实表 + Canonical Publication，不采用巨型 EAV。
2. Raw 成功响应默认保留 7 天，失败/隔离 30 天，决策关联 payload 最长 90 天；长期只保留 hash、schema fingerprint、行数、范围和关键审计元数据。
3. 旧表切读后至少跨一个独立发布阶段再删除。
4. 行情影子观察至少覆盖 3 个连续交易日和 1 个周末/节假日边界。
5. 宏观影子观察至少覆盖 2 个实际调度周期。
6. 财务/估值至少完成一次全 universe 回填、一次增量更新和一轮随机/边界样本上游对账。
7. 生产数据库唯一正式口径为 PostgreSQL；SQLite 只保证本地开发可启动，不作为可靠性验收环境。
8. 无法证明正确的数据默认 blocked，不使用估算或聊天模型补齐。
9. 正式上线默认初始化 production-90g 容量策略；90 GiB 只存在于部署/初始化配置和数据库策略记录，不在生产逻辑中硬编码。常态、紧急余量和水位均由 active policy 计算。
10. VPS 最多保留一个 in-flight 数据库备份且不超过 24 小时；长期备份必须位于 VPS 之外。
11. 生产运行参数默认以 PostgreSQL Config Center 为真源；JSON 只用于治理投影、脱敏导入导出和 typed_json，不作为旁路。
12. 全局运行参数由 Config Center 物理持有；领域语义配置保持 owner 类型化表，但必须注册并通过统一入口操作。

待 ADR：

- Canonical Publication 的 source-selection 算法版本策略。
- VPS 外冷归档介质、加密方式和离线时的恢复责任。
- PostgreSQL 分区的具体实现方式与首次切换步骤。
- Provider 许可对新闻/原始响应保留的限制。
- 跨 App 派生数据产品是由 Data Center 存快照，还是只登记 owner facade；默认按业务 owner 存储、Data Product Contract 统一发布证据。

## 25. 第一批可执行 Backlog

按以下顺序开工，未完成上一门禁不进入破坏性阶段：

### Batch A：只读盘点与冻结

- [x] 生成 data ownership / consumer / legacy / task / surface inventory（静态清单；生产数据画像仍未完成）。
- [x] 生成 runtime config inventory，逐项分类 DB、env、settings、constant、JSON 和 Celery kwargs（首批受管参数；覆盖率仍需继续扩展）。
- [ ] 冻结 SystemSettingsModel 无边界增列和未登记的运行参数默认值。
- [x] 新增 Provider SDK 和 legacy model 差异扫描。
- [ ] 重采生产数据画像与核心覆盖。
- [ ] 采集 PostgreSQL relation/index/TOAST/WAL、Docker、Redis、backup、Raw、logs 的容量基线。
- [ ] 计算各 Dataset bytes/row、日增长和 12 个月容量预测。
- [x] 建立本计划的阶段证据目录和 owner 表（`governance/data_ownership_contracts.json`）。

### Batch B：立即修正危险语义

- [x] 移除关键财务/估值/Alpha/筛选链路的 missing → 0.0。
- [x] stored=0 使用 noop/failed，而非无条件 success。
- [x] generic failover 接受标准 FetchResult 和 freshness validator。
- [x] ReliabilityContract 接入核心 Data Center DTO。

### Batch C：建立可迁移基础

- [x] Dataset Contract / Binding / Policy schema。
- [x] SyncRun / Batch / Checkpoint / Quarantine。
- [x] Canonical Publication。
- [x] Public Query Ports。
- [x] Storage Budget / Retention / Hold / Archive Manifest（模型、Domain、仓储和 guard 已落地；实际定时清理/归档任务仍待接入）。
- [x] RuntimeConfigDefinition / Profile / Value / Revision / Snapshot 与首批领域 owner registry。
- [x] Config Center 统一 TUI/Application 入口、impact preview、原子激活和回滚（TUI P0 阻断提示、preview/rollback API 已接入；真实生产观察窗口仍待补）。
- [x] production-90g 显式初始化命令、StorageBudgetQueryPort、策略变更审计和无 active policy 阻断。
- [x] StoragePressureGuard（已接入有界 raw cleanup task；真实 beat schedule、归档和恢复演练仍待补）。

### Batch D：按 D0-D9 迁移消费者

- [ ] 资产和行情。
- [ ] 宏观。
- [ ] 财务和估值。
- [ ] 基金净值。
- [ ] 板块、新闻和资金流。
- [ ] SDK/MCP/Terminal/TUI。

### Batch E：生产与清理

- [ ] 维护阻断、备份、回填、影子对账。
- [ ] 将 VPS 同机 14 日备份改为单份 in-flight + 外部校验后清理。
- [ ] 完成 production-90g 与至少一个非 90 GiB 策略的水位、分区清理和恢复故障注入。
- [ ] 切读、观察、停止旧写。
- [ ] 删除 SystemSettingsModel 已迁移字段、Config Center 跨 App ORM 和关键配置隐形 fallback。
- [ ] 删除旧链与旧表。
- [ ] 完整 CI、PostgreSQL、E2E、性能和 rollback evidence。

## 26. 阶段记录模板

每个 M 阶段必须在本计划下追加或新建 evidence 文档，至少记录：

~~~text
阶段：
Owner：
目标：
本批明确不做：
变更文件：
数据迁移：
旧链状态：
治理清单变化：
已运行测试及 nodeid：
PostgreSQL 证据：
数据画像与差异：
性能结果：
容量基线、峰值与到水位天数：
Retention / Archive / Hold 证据：
未验证风险：
回滚点：
退出条件逐项结论：
Git SHA / 镜像 / migration：
~~~

禁止只写“测试通过”或“已完成”。完成结论必须能够回溯到机器清单、测试报告、数据画像、生产任务 run_id 和发布版本。

## 27. 2026-08-04：Tushare 暂停运行冒烟证据

- 目标：验证在不构建 Tushare provider 的前提下，Data Center runtime registry 仍可启动并为当前支持的数据能力提供 AKShare provider。
- 方法：在干净 detached worktree（`43185f4b`）中注入仅包含 `source_type=akshare` 的 active provider 配置，调用 `ProviderRegistry.from_repository`，不发起外部数据请求。
- 结果：`AKSHARE_ONLY_REGISTRY_OK`；`macro`、`historical_price`、`realtime_quote`、`fund_nav`、`financial`、`valuation`、`sector_membership`、`news`、`capital_flow` 均只注册 AKShare，未出现 Tushare provider。
- 结论：代码路径支持暂时不用 Tushare；实际环境仍需在 TUI 的 Data Center Provider 页面将 Tushare 置为停用，并确认 AKShare 已启用后再执行同步/查询。当前未修改本地或 VPS 的 provider 状态，也未部署。
- 未验证风险：本次仅验证 provider 构建和能力路由，未替代真实 AKShare 网络可用性、生产 PostgreSQL 数据覆盖、影子对账或生产观察窗口；这些仍属于 Batch E 未完成项。

## 28. 2026-08-05：Macro TUI Publication-only 收口

- 目标：消除宏观 TUI overview/trend-filter 对未发布 `latest`/series 的旁路读取。
- 变更：`get_macro_data_page_snapshot(published_only=True)` 通过 Data Center Public Port 获取最新值并绑定当前 Publication member fact PK；宏观趋势过滤器在 composition root 中使用 `_PublishedMacroSeriesQuery`，无 Publication、过期 Publication 或成员缺失时 fail closed，并把阻断原因返回给 TUI。
- 治理：`governance/current_data_contracts.json` 新增 `macro.tui_publication` surface，登记 overview、trend-filter 的 Publication/freshness marker 与测试。
- 已运行测试：
  - `pytest tests/unit/macro/test_interface_services.py tests/api/test_macro_regime_tui_api.py -q --no-migrations --reuse-db --disable-warnings --timeout=180`：20 passed。
  - `pytest tests/unit/macro/test_composition.py tests/api/test_macro_regime_tui_api.py -q --no-migrations --reuse-db --disable-warnings --timeout=180`：16 passed。
  - `python scripts/check_current_data_contracts.py`：37 surface(s) OK。
  - `python scripts/verify_architecture.py --include-audit --format text`：boundary 0 / audit 0；`check_mypy_regression.py`：0；Ruff OK。
- 明确未做：Classic staff macro management page 继续保留 raw/historical 维护语义；本批未修改本地/VPS provider 状态、未部署、未执行生产 PostgreSQL 或观察窗口。
- 未验证风险：生产 Publication 覆盖、宏观同步任务实际创建完整成员快照、生产 TUI 网络链路和 PostgreSQL 性能仍未有证据。

## 29. 2026-08-05：Strategy 宏观 provider 旁路清理

- 目标：阻断策略脚本/AI 执行链通过 `IndicatorService` 读取未发布宏观 latest。
- 变更：`apps/strategy/infrastructure/providers.py` 的 `DjangoMacroDataProvider` 改用 `get_macro_indicator_value` 与 `list_latest_published_macro_values`，Publication 缺失/异常时分别返回 `None`/空映射，不再动态导入 `apps.macro.application.indicator_service`。
- 治理：把 Strategy provider 纳入 `data_center.publication_only_d2_d3` 的 source/marker/test 登记。
- 已运行测试：`pytest tests/unit/strategy/test_provider_edges.py tests/unit/strategy/test_external_providers.py -q --no-migrations --reuse-db --disable-warnings --timeout=180`：10 passed；current-data 37 surfaces；architecture boundary/audit 0；mypy 0；Ruff/Black OK。
- 明确未做：未修改 Strategy 其他业务配置、未修改本地/VPS provider 状态、未部署。
- 未验证风险：生产策略脚本实际调用、生产 Publication 覆盖和 PostgreSQL 性能仍待生产阶段证据。

## 30. 2026-08-05：证伪检查器宏观读取收口

- 目标：避免持仓/信号证伪任务把未发布宏观事实当作当前观测。
- 变更：`simulated_trading.application.position_invalidation_checker` 与 `signal.application.invalidation_checker` 改用 `get_published_macro_fact_series`，统一按 Publication member、freshness gate 读取；阻断或异常时返回空观测，保留 fail-closed 行为。
- 治理：将两个检查器及其 gate 测试加入 `data_center.publication_only_d2_d3`。
- 已运行测试：相关组件/单元测试 8 passed；current-data 37 surfaces；architecture boundary/audit 0；mypy 0；Ruff OK。
- 明确未做：未改动信号/持仓业务规则本身，未部署、未修改本地/VPS provider 状态。
- 未验证风险：生产 Celery 证伪任务的 Publication 覆盖与实际调度观测仍未完成。

## 31. 2026-08-05：基金默认当前净值 Publication gate

- 目标：基金净值 API 的默认“当前”读取不再直接消费 raw Data Center latest。
- 变更：无日期参数时由 `get_published_fund_nav_payload` 调用 `get_published_fund_nav_series`；返回 Publication/freshness contract，缺失或过期时以 409 阻断。显式日期区间继续保留历史研究读取语义。
- 治理：新增 `fund.current_nav` current-data surface 与 API gate 测试登记。
- 已运行测试：`pytest tests/api/test_fund_api_edges.py tests/component/test_fund_repository_data_center.py -q --no-migrations --reuse-db --disable-warnings --timeout=180`：37 passed；current-data 38 surfaces；architecture boundary/audit 0；mypy 0；Ruff/Black OK。后续补充 Public Port 查询异常的 fail-closed 单测。
- 明确未做：未修改基金历史区间的 raw/maintenance 语义，未部署、未修改本地/VPS provider 状态。
- 未验证风险：生产基金 Publication 覆盖、生产 PostgreSQL 性能和历史/当前模式的 E2E 证据仍待补齐。

## 32. 2026-08-05：Decision Rhythm 股票特征成员绑定

- 目标：消除技术面/基本面特征对 `DjangoStockRepository.get_all_stocks_with_fundamentals()` 的旧仓储旁路，确保推荐特征只使用对应证券的 canonical Publication member。
- 变更：`TechnicalFeatureProvider` 通过 `get_published_stock_context_map(..., include_financial=False, include_valuation=False)` 读取价格成员及 gate；`FundamentalFeatureProvider` 通过同一 Public Port 读取财务/估值成员和 `roe`，异常、缺失或过期均保留阻断证据并返回中性值。查询端口新增按需选择 financial/valuation 的参数，避免技术特征无关读取其他数据域。
- 治理：更新 `decision_rhythm.feature_freshness` marker/test 登记，覆盖 member-bound price、financial/valuation context。
- 已运行测试：`pytest tests/component/test_feature_providers.py`：35 passed；`pytest tests/unit/equity/test_published_stock_context.py`：4 passed；`pytest tests/unit/test_unified_recommendation_use_cases.py tests/unit/decision_rhythm/test_flow_feature_freshness.py`：23 passed。`check_current_data_contracts.py`：39 surfaces；architecture boundary/audit：0；mypy：0；Ruff：0。
- 明确未做：未改变技术评分的中性占位算法，未修改旧维护/历史研究接口，未部署、未修改本地/VPS provider 状态。
- 未验证风险：完整 Decision Rhythm 推荐链、生产 Publication 覆盖和 PostgreSQL 性能仍需后续批次证据；全量组件测试应在合并门禁中再次运行。

## 33. 2026-08-05：Decision Rhythm 资金流特征 quote Publication 收口

- 目标：阻断 `FlowFeatureProvider` 直接读取 Redis latest quote 的 current-data 旁路。
- 变更：资金流特征改用 `get_published_quote_payloads`，按 quote Publication/member gate 读取 `snapshot_at` 与 `volume`；保留 stale、future、naive、观察时间缺失、成交量缺失和 Publication 阻断证据，任何不可用状态返回中性分。
- 治理：`decision_rhythm.feature_freshness` 增加 quote Public Port/flow gate marker 和回归登记。
- 已运行测试：`pytest tests/unit/decision_rhythm/test_flow_feature_freshness.py`：5 passed；current-data 39 surfaces；architecture boundary/audit 0；mypy 0；Ruff 0。
- 明确未做：未改变资金流评分的 sigmoid 占位算法，未修改 Redis maintenance/cache 写入，未部署、未修改本地/VPS provider 状态。
- 未验证风险：生产 quote Publication 覆盖、Realtime 与 Decision Rhythm 的跨源观测一致性、PostgreSQL 性能仍待生产阶段证据。

## 34. 2026-08-05：Agent Runtime current context 旁路收口

- 目标：避免 Agent Runtime context snapshot 自行读取最新 `RegimeLog`/`PolicyLog`，绕过所属 Application 的 current/freshness 语义。
- 变更：regime summary 与 freshness summary 改用 `resolve_current_regime()`，透传 `observed_at`、`freshness_status`、`must_not_use_for_decision` 和 `blocked_reason`；policy summary 改用 `get_policy_status_payload()` 与 `get_recent_policy_event_summary()`，保留有效事件日期和状态信息。
- 治理：新增 `agent_runtime.current_context` current-data surface，登记 resolver/query marker 与回归测试。
- 已运行测试：`pytest tests/unit/agent_runtime/test_t5_context_snapshot_repository_contracts.py tests/unit/test_agent_runtime_context_snapshot_safety.py`：17 passed；`pytest tests/component/test_context_snapshot_repository.py`：2 passed；current-data 40 surfaces；architecture boundary/audit 0；mypy 0；Ruff 0。
- 明确未做：未改变 Agent Task/Proposal/Portfolio 等 operational ORM 汇总，未部署、未修改本地/VPS provider 状态。
- 未验证风险：Regime resolver 在生产调度下的耗时、政策 Application query 的生产数据覆盖和 PostgreSQL 性能仍待生产阶段证据。

## 35. 2026-08-05：Terminal Regime response freshness 字段补齐

- 目标：Terminal market-regime 响应的 `current_data_contract` 不仅给出阻断布尔值，还明确发布 freshness 状态。
- 变更：根据 `CurrentRegimeResult.observed_at/is_stale` 输出 `freshness_status`（`fresh/stale/unavailable`），保留 source observation、阻断原因和 `must_not_use_for_decision`。
- 治理：更新 `regime.current` 的 Terminal marker。
- 已运行测试：`pytest tests/unit/terminal/test_chat_router.py`：3 passed；current-data 40 surfaces；mypy 0；Ruff 0。
- 明确未做：未改变 Regime 计算、Policy 查询或 Terminal 文案路由，未部署、未修改本地/VPS provider 状态。
- 未验证风险：生产 Terminal/MCP 网络链路和客户端对新增 freshness 字段的兼容性仍待 E2E 证据。

## 36. 2026-08-05：统一价格服务 current Publication 收口

- 目标：阻断 Account、Simulated Trading、Valuation 共用的 `UnifiedPriceService` 对最新报价、最新收盘价和当前基金净值的 raw repository 旁路，避免停用 Tushare 后把未发布旧事实包装成可执行价格。
- 变更：current quote 改用 `get_published_quote_payloads` 并通过 `QueryLatestQuoteUseCase.build_response` 保留源 `snapshot_at/fetched_at`；close fallback 改用 `get_published_price_bar_series` 并绑定同一 Publication member；current fund NAV 改用 `get_published_fund_nav_series`，显式日期仍保留 historical repository 语义，注入的外部基金 adapter 不得绕过 current Publication gate。
- 变更：price-bar Public Port payload 增加 canonical `fetched_at`，便于 current 结果审计源抓取时间，不用请求时间覆盖事实时间。
- 治理：更新 `data_center.unified_price` 与 `data_center.close_and_nav_fallbacks` markers/tests，增加“Publication 阻断时不查 raw repository”和“adapter 不得绕过 Publication”的回归。
- 已运行测试：`pytest tests/unit/test_unified_price_service.py -q --no-migrations --reuse-db --disable-warnings --timeout=180`：27 passed；目标文件 Black/Ruff 通过（全局门禁需在外部 Risk/Strategy 未提交改动恢复可解析后复跑）。
- 明确未做：未修改 historical/PIT 查询、未改变 Tushare/AKShare provider 配置，未部署、未 push、未连接 VPS。
- 未验证风险：生产 Publication/member 覆盖、AKShare 全量 current 产出、PostgreSQL 性能和 Realtime 其他维护缓存链路仍待生产阶段证据。

## 37. 2026-08-05：Equity 分时 quote snapshot member-bound 收口

- 目标：消除 Equity 分时图直接读取 QuoteSnapshot 全表序列的旁路，使已持久化的分时点优先来自同一 `equity.quote.snapshot` Publication/member 快照。
- 变更：QuoteSnapshot repository/protocol 增加可选 `fact_pks` 过滤；新增 `query_published_quote_series` / `get_published_quote_series` Public Port，复用 Publication freshness、`as_of` 上界和成员主键过滤；Intraday repository 优先转换 member-bound rows，保留源 `snapshot_at`，Publication 缺失或点位稀疏时才进入明确标注的 AKShare 诊断 failover。
- 治理：`equity.intraday_chart` 增加 quote-series Public Port marker 与 repository 回归 nodeid；published quote member-bound 查询加入 D4/D5 查询端口回归。
- 已运行测试：`pytest tests/unit/data_center/test_published_query_ports.py tests/unit/test_equity_repository_intraday.py -q --no-migrations --reuse-db --disable-warnings --timeout=180`：30 passed；`python scripts/check_current_data_contracts.py`：39 surfaces；相关 4 个生产文件 mypy regression 0；Ruff/Black 通过。
- 架构清单刷新：`python scripts/data_center_architecture_inventory.py --write`：`provider_imports_outside_data_center=0`、`cross_app_orm_imports=53`、`legacy_fact_references=143`、`current_surface_references=3142`、`data_write_task_decorators=55`、`runtime_parameter_references=49`、`external_http_imports_for_review=6`。
- 明确未做：未把 AKShare 远端分时诊断 failover 伪装为 canonical Publication，未修改历史回放语义，未部署、未 push、未修改本地/VPS provider 状态。
- 未验证风险：生产 quote Publication 是否包含完整分时点集合、分时图 PostgreSQL 查询预算、生产观察窗口及旧 Realtime cache 清理仍待生产阶段证据。

## 38. 2026-08-05：Alpha quote momentum Publication 阻断收口

- 目标：确保 Alpha 简单因子在行情 Publication 缺失、过期或显式阻断时，不会因为 payload 仍携带旧 rows 而继续生成可执行的 quote momentum 分数。
- 变更：`SimpleAlphaProvider` 对 quote payload 的 `must_not_use_for_decision`、rows 类型和源 `snapshot_at` 做 fail-closed 校验；只接受带时区的源观测时间，不再由请求时间补造行情时间。健康检查同样忽略被阻断的 rows。
- 测试：新增 `test_simple_quote_fallback_rejects_rows_when_publication_is_blocked`；Alpha 集成测试改用 Publication Public Port fixture，避免把裸 `QuoteSnapshotModel` 当作 current 数据入口。
- 治理：`data_center.publication_only_d2_d3` 增加 Alpha 阻断 marker 与测试登记。
- 已运行测试：`pytest tests/unit/alpha/test_t3b_provider_contracts.py apps/alpha/tests/test_simple_adapter.py tests/unit/alpha/test_alpha_infrastructure_edges.py -q --no-migrations --reuse-db --disable-warnings --timeout=180`：19 passed；`python scripts/check_current_data_contracts.py`：39 surfaces；其余架构、mypy、inventory 门禁随本批提交前复跑。
- 明确未做：未改变 Alpha 的打分权重、基本面历史查询和 Qlib fallback，未修改 Tushare/AKShare provider 状态，未部署、未 push。
- 未验证风险：生产行情 Publication 的覆盖率、Alpha 端到端任务调度和 PostgreSQL 性能仍待生产阶段证据；Realtime 诊断 failover 仍按 §47 的明确边界保留。

## 39. 2026-08-05：Fund repository latest NAV Publication 收口

- 目标：消除 `DjangoFundRepository.get_latest_nav()` 对 Data Center raw latest 的 current-data 旁路，避免基金内部调用在没有 Tushare 或 Publication 失效时仍消费未验证净值。
- 变更：`get_latest_nav()` 改用 `get_published_fund_nav_series(publication_key="current", limit=1)`；缺少/过期/阻断 Publication、payload 结构错误或数值日期无效时 fail closed 返回 `None`。显式日期区间 `get_fund_nav()` 继续保留历史研究语义。
- 测试：组件测试验证 latest NAV 只调用 Publication port；新增带旧 rows 的阻断 Publication 测试并断言 raw repository 未被调用。
- 治理：`fund.current_nav` 纳入 Fund repository source/markers 与两条回归 nodeid。
- 已运行测试：`pytest tests/component/test_fund_repository_data_center.py tests/api/test_fund_api_edges.py -q --no-migrations --reuse-db --disable-warnings --timeout=180`：39 passed；`python scripts/check_current_data_contracts.py`：40 surfaces。
- 明确未做：未改变基金历史 NAV、业绩回测、同步写入和 provider failover，未修改 Tushare/AKShare provider 状态，未部署、未 push。
- 未验证风险：生产基金 Publication 成员覆盖、基金 current 调用方完整盘点和 PostgreSQL 性能仍待生产阶段证据。

## 40. 2026-08-05：Fund NAV 远程同步退出裸 Tushare fallback

- 目标：让基金历史 NAV 远程补数也遵守 Data Center provider registry 与 capability failover，停用 Tushare 后不再由 `DjangoFundRepository` 直接构造/调用 Tushare 基金适配器。
- 变更：新增 `sync_fund_nav_from_active_provider` Public Port，按 active provider priority 和 `DataCapability.FUND_NAV` 路由，零产出/异常时继续尝试后续 provider；基金仓储保留 `sync_fund_nav_from_tushare` 兼容方法名，但只委托该 Public Port，不再调用裸 Tushare fallback。
- 测试：新增 active capability failover、无 provider blocked、旧方法名委托 Data Center port 三条回归。
- 治理：将 provider-route marker 与测试加入 `fund.current_nav` contract，确保后续不得恢复直接 Tushare fallback。
- 已运行测试：`pytest tests/unit/data_center/test_public_fund_nav_sync_routing.py tests/component/test_fund_repository_data_center.py tests/api/test_fund_api_edges.py -q --no-migrations --reuse-db --disable-warnings --timeout=180`：42 passed；`check_mypy_regression.py`：2 files / 0 regression；`verify_architecture.py --include-audit`：boundary 0 / audit 0；current-data contracts：40 surfaces。
- 明确未做：基金 master list 的旧 Tushare 兼容同步、历史研究读取和 production provider 状态未在本批删除；未部署、未 push。
- 未验证风险：生产 AKShare fund NAV capability 的真实覆盖、provider registry active 配置和 Publication 产出仍需生产数据证据。

## 41. 2026-08-05：基金 master seed 在无 Tushare 时 fail closed

- 目标：避免基金本地 master 为空且 Tushare 未配置/不可用时，启动或研究准备流程因未捕获的 provider 异常直接失败。
- 变更：`ensure_fund_universe_seeded()` 捕获 provider seed 异常，记录不泄露凭据的错误类型并返回零产出；上层随后以空 universe/可行动错误处理，不伪造基金主数据。
- 测试：新增 provider unavailable → `0` 产出且不抛异常的组件回归；既有成功 seed/已有 master 分支保持覆盖。
- 治理：`fund.current_nav` contract 登记 master seed fail-closed marker/test。
- 已运行测试：`pytest tests/component/test_fund_repository_data_center.py -q --no-migrations --reuse-db --disable-warnings --timeout=180`：10 passed；Fund repository mypy regression 0；Ruff/Black 通过。
- 明确未做：基金 master 的最终 Data Center AssetMaster 迁移与旧 Tushare 显式同步入口退役仍待 D0/D6 后续批次；未部署、未 push。
- 未验证风险：生产空 master 的 readiness 阻断文案、AKShare master 覆盖和完整基金 universe 回填仍需数据画像/生产证据。

## 42. 2026-08-05：Equity current 估值读取切换 Publication

- 目标：消除 Equity fundamentals repository 在默认当前列表和股票上下文估值读取中的 raw valuation latest 旁路，避免 Publication 失效时继续消费旧估值事实。
- 变更：无 `as_of_date` 的 fundamentals 列表与股票上下文改用 `get_published_valuation_facts(publication_key="current")`；校验 Publication 阻断、成员事实日期、带时区的源抓取时间和数值字段，缺失/异常时 fail closed。显式历史日期查询继续保留 Data Center historical repository 语义。
- 测试：新增 Publication 阻断拒绝与 published valuation observation 保留组件回归。
- 治理：新增 `equity.current_valuation` current-data contract，登记 Equity repository/Public Port marker 与两条回归测试。
- 已运行测试：`pytest tests/component/test_equity_repository_data_center.py -q --no-migrations --reuse-db --disable-warnings --timeout=180`：5 passed；目标文件 Black/Ruff 通过；`check_mypy_regression.py`：0 regression；`check_current_data_contracts.py`：41 surfaces。
- 明确未做：未修改 Equity historical/PIT 读取、估值算法或 provider 写入，未部署、未 push。
- 未验证风险：生产 valuation Publication 成员覆盖、完整 Equity current 调用方盘点、PostgreSQL 查询预算和旧估值表零读写仍待后续批次证据。

## 43. 2026-08-05：Equity current 财务读取切换 Publication

- 目标：消除 Equity fundamentals repository 在默认当前列表和股票上下文财务读取中的 raw financial facts 旁路，避免 Publication 失效时继续消费旧财报指标。
- 变更：无 `as_of_date` 的 fundamentals 列表、股票上下文和 `get_latest_financial_data()` 改用 `get_published_financial_facts(publication_key="current")`；校验 Publication 阻断、成员期间、带时区的源抓取时间、期间类型和数值字段，缺失/异常时 fail closed。显式历史/回测查询继续保留 Data Center historical repository 语义。
- 测试：新增 Publication 阻断拒绝与 published financial observation 保留组件回归；复用同一事实组装逻辑，避免 current/historical 口径漂移。
- 治理：新增 `equity.current_financials` current-data contract，登记 Equity repository/Public Port marker 与两条回归测试。
- 已运行测试：`pytest tests/component/test_equity_repository_data_center.py -q --no-migrations --reuse-db --disable-warnings --timeout=180`：7 passed；目标文件 Black/Ruff 通过；`check_mypy_regression.py`：0 regression。
- 明确未做：未修改 Equity historical/PIT 读取、财务指标算法或 provider 写入，未部署、未 push。
- 未验证风险：生产 financial Publication 成员覆盖、完整 Equity current 调用方盘点、PostgreSQL 查询预算和旧财务表零读写仍待后续批次证据。

## 44. 2026-08-05：Equity current 价格上下文与资产评分切换 Publication

- 目标：消除 Equity stock context 与通用资产评分对最新日线价格 raw `get_latest()` 的旁路，避免无 Tushare 或价格 Publication 失效时把旧收盘包装为当前技术指标。
- 变更：新增 `_get_latest_price_bar(..., published_only=True)`，读取 `get_published_price_bar_series` 并严格解析 bar 日期、OHLCV、源抓取时间和复权类型；资产筛选/单资产评分均改用该 gate，应用层 `get_stock_context_map` 统一转到 `get_published_stock_context_map`。repository 的无 gate 方法仅保留历史/维护兼容语义。Publication 阻断、成员缺失或事实结构无效时返回空技术上下文，不回读 raw latest。
- 测试：新增 Publication 阻断拒绝与 published price observation 保留组件回归；资产仓储显式传递 `published_only=True`。
- 治理：新增 `equity.current_price_context` current-data contract，登记 Equity fundamentals/asset repository 与 Public Port marker/test。
- 已运行测试：目标组件回归将覆盖 9 tests；目标文件 Black/Ruff/mypy 及 current-data/architecture 门禁在本批提交前复跑。
- 明确未做：未修改 Equity historical/PIT 日线查询、技术指标算法或 provider 写入，未部署、未 push。
- 未验证风险：生产 price-bar Publication 成员覆盖、资产筛选大批量查询预算、旧价格表零读写和生产 PostgreSQL 性能仍待后续批次证据。

## 45. 2026-08-05：停用 Tushare 的本地可运行性烟测

- 目标：确认 Tushare 暂时不可用时，Django 启动检查和已收口的基金 canonical 读路径不会因 provider 初始化或旧 latest fallback 直接崩溃。
- 证据：在清空 `TUSHARE_TOKEN` 与 `TUSHARE_HTTP_URL` 的进程环境下运行 `python manage.py check`，结果为 `System check identified no issues (0 silenced)`；基金 Data Center repository 组件回归 `10 passed`。
- 语义：无 Tushare 不代表所有数据任务成功；缺少 active provider、Publication 或成员时按稳定 `blocked`/空结果 fail closed，历史本地事实仍可用于显式历史查询。
- 明确未做：未修改 provider 配置、未删除 Tushare 适配器、未部署/未 push；远端 VPS 和生产数据画像尚未验证。
- 未验证风险：生产 AKShare/其他 provider 的实际覆盖、基金 master 空库初始化、Publication 回填和全系统无 Tushare 端到端运行仍需后续证据。

## 46. 2026-08-05：Equity 估值分析用例绑定 mode/publication

- 目标：修复 REST Equity 估值、DCF、综合估值在接口层检查 `mode=published` 后，内部 use case 仍以 `hydrate=True` 读取历史/raw facts 的旁路。
- 变更：`AnalyzeValuationRequest`、`CalculateDCFRequest`、`ComprehensiveValuationRequest` 携带 `mode/publication_key`；接口将请求语义传入 use case。published 模式下，财务、估值历史和日线价格分别通过 Publication-bound repository 读取，阻断或成员缺失时不触发远端 hydration；historical 模式保留显式历史/维护语义。Publication valuation history 解析保留事实日期与带时区抓取时间，不使用请求时间补造。
- 测试：新增 published gate 参数转发单测；新增估值历史和日线 current 读取的 blocked/preserved component 回归。
- 治理：扩展 `data_center.publication_only_d4_d5` 与 `equity.current_price_context` marker/test，锁定接口 gate 与 use case 实际读路径一致。
- 已运行测试：`tests/unit/equity/test_use_cases.py`：10 passed；`tests/unit/equity/test_t5_equity_use_case_edge_contracts.py`：13 passed；`tests/component/test_equity_repository_data_center.py`：13 passed；`tests/api/test_equity_api_edges.py`：53 passed；变更生产文件 mypy 0、Ruff/Black 通过。
- 明确未做：未改动 historical explicit range、Technical chart mode、provider 写入和生产配置，未部署、未 push。
- 未验证风险：生产 Publication 是否包含足够长的估值历史成员、DCF/综合估值真实数据覆盖、PostgreSQL 查询预算与旧表零读写仍待后续批次。

## 47. 2026-08-05：Equity 技术图表绑定 price-bar Publication

- 目标：消除 `/api/equity/technical/{stock_code}/` 默认 `hydrate=True` 触发 Data Center/raw/远端行情旁路的问题；current 技术图表必须和其他 Equity current surface 一样 fail closed。
- 变更：技术图表请求新增 `mode` 与 `publication_key`，默认 `published`；published 模式只调用 `get_published_price_bar_series`，严格校验 OHLCV、带时区 `fetched_at` 和事实日期，重算指标后返回；Publication 阻断、结构无效或无成员时不回退 raw/远端数据。显式 `mode=historical` 才保留 hydration 与历史研究语义。
- 治理：扩展 `equity.technical_chart` current-data contract，登记接口传递、repository Publication marker 与 blocked/preserved 回归。
- 已运行验证：技术图表/Equity Data Center/API 定向回归 `82 passed`；补充组件+用例回归 `29 passed`；current-data `43 surfaces`、legacy fact guard、architecture boundary/audit `0`、变更 4 个生产文件 mypy regression `0`、Ruff 通过。Black 对 3 个变更文件执行格式化后复核通过。
- 明确未做：未修改 intraday、技术指标算法、历史模式、provider 写入和生产配置，未部署、未 push。

## 48. 2026-08-05：Equity SDK 默认 current 读取绑定 Publication

- 目标：避免 SDK 直接调用 `equity.get_stock_pool/get_stock_detail/get_stock_score/get_recommendations/get_financials/get_valuation` 时省略 `mode`，被服务端隐式解释为 historical，从而绕过 current Publication 语义。
- 变更：上述 SDK current/research 入口默认显式发送 `mode=published`、`publication_key=current`；需要历史研究时必须显式传 `mode=historical`。MCP 原有 published 显式调用保持不变。
- 治理：`data_center.publication_only_d4_d5` 增加 SDK 默认 published marker 与回归 nodeid。
- 已运行验证：SDK Equity/MCP 定向回归 `50 passed`；current-data `43 surfaces`；SDK module mypy `0`、Ruff/Black 通过。新增显式 historical mode 回归，确认历史语义仍需主动选择。
- 明确未做：未改变服务端 historical API、MCP tool schema、生产配置、部署或 VPS 数据。

## 49. 2026-08-05：Equity REST/UseCase 默认 current 读取切换 published

- 目标：完成 Equity current-facing REST 默认值的强制 Publication 语义，避免未携带 `mode` 的 pool、financials、valuation、DCF、comprehensive 请求落入 historical/raw 读取。
- 变更：Equity serializers 与估值 use-case request 默认统一为 `mode=published`；历史研究必须显式 `mode=historical`。补齐 API 旧历史 fixture 的显式 historical 参数，保留兼容语义但不再隐式触发。
- 治理：`data_center.publication_only_d4_d5` 登记 serializer/use-case 默认 published marker。
- 已运行验证：Equity API/use-case 定向回归 `77 passed`；current-data `43 surfaces`、legacy fact guard、architecture boundary/audit `0`、变更 2 个生产文件 mypy regression `0`、Ruff/Black 通过。

## 50. 2026-08-05：current-data manifest 实际 nodeid 执行证据

- 目标：把 current-data manifest 从“静态 marker 通过”推进到实际 pytest nodeid 执行，避免登记但未运行的假绿。
- 证据：`python scripts/run_current_data_contract_tests.py --pytest-arg=-q --pytest-arg=--reuse-db --pytest-arg=--disable-warnings --pytest-arg=--timeout=180` 收集并执行 237 个登记 nodeid，实际 `276 passed`，正常迁移模式完成；`--no-migrations` 曾出现 1 个依赖迁移 seed 的风险场景失败，已用正常迁移模式复核通过。
- 结论：current-data manifest 的本地可执行证据已补齐；这不替代 Linux CI、PostgreSQL 生产画像、Publication 覆盖和观察窗口证据。

## 51. 2026-08-05：治理门禁与 Risk 类型债务收口

- 证据：Celery task contracts（18 tasks/4 files）、runtime config coverage（49 references）、Data Center query budgets（3）、storage budget contract、runtime desired-state 均通过；全仓 `check_mypy_debt_ceiling.py` 修复后为 `0 errors in 0 files`。
- 修复：Risk scenario immutable model 的 Django `save(force_insert)` 类型契约、ScenarioSet effective datetime 类型收窄已修复并提交；Sector 新增模板模块的类型修复留在其 owner 的未提交工作区，不混入本批。
- 未完成：治理 consistency 当前仍等待新增 `fixed_income`/`macro_factor` 模块的 baseline 与大文件预算登记；这些是其他 agent 的未提交改动，未在本批强行纳入。
- 明确未做：未删除 historical API、未改变 Publication writer/provider、未部署或修改 VPS。

## 52. 2026-08-05：模块循环债务与治理基线同步收口

- 目标：消除新增场景治理适配器引入的 `account → risk_center → agent_runtime → account` 模块循环，并让新增业务模块、依赖边界和大文件治理在机器基线中可审计。
- 修复：Risk Center 的 Agent Proposal 网关改用 Django App Registry 按稳定模型标签解析冻结模型，不再静态依赖 Agent Runtime；场景治理仍通过 `AgentProposalGatewayProtocol` 保持可替换注入，事务与审计行为不变。
- 治理：`governance/module_cycle_allowlist.json` 更新为 `2026-08-05.v20`，登记 44 个模块、204 条无环依赖、fixed_income/macro_factor/research/risk_center/Policy news 的精确出入边界；不再保留 cycle component、bidirectional pair 或超预算边界。
- 基线：`governance/governance_baseline.json` 更新为 `2026-08-05.v206`，登记新增模块 shape、现有大文件 owner/remediation/review-by；不把大文件豁免当作完成声明，仍要求在 M6/M9/TUI 收口前拆分。
- 已运行验证：`python scripts/check_module_cycles.py --allowlist-file governance/module_cycle_allowlist.json --format text`：0 cycle、0 bidirectional、0 budget violation；`python scripts/check_governance_consistency.py --baseline governance/governance_baseline.json --format text`：0 violations；Risk repository Ruff/Black 通过。
- 明确未做：未删除旧事实表、未改变 provider 配置、未部署、未 push；大文件拆分、生产 PostgreSQL/备份恢复、Publication 覆盖和 M9/M10 仍未完成。

## 53. 2026-08-05：Policy RSS 外部接入下沉 Data Center

- 目标：完成 D8 的一个明确边界缺口，消除 `apps/policy` 直接 import `requests` 并自行解析 RSS 的外部事实旁路。
- 变更：新增 Data Center Infrastructure `rss_gateway`，统一负责 URL 校验、代理、超时/重试、feedparser 解析和抓取时间；缺少源发布时间的条目直接丢弃，不用请求时间洗白。Data Center Application Public Port 返回带 `published_at/fetched_at/source/external_id` 的 `NewsFact`，Policy 仅负责转换为分类/审核输入。
- 治理：外部 HTTP inventory 从 6 降为 5；`apps/policy/infrastructure/adapters/feedparser_adapter.py` 不再持有网络客户端或 feedparser runtime，业务 App 只依赖 Public Port。
- 已运行验证：RSS gateway + Policy adapter 回归 `18 passed`；`verify_architecture.py --include-audit`：boundary/audit 0；`check_data_center_legacy_fact_access.py`、`check_current_data_contracts.py` 通过；变更生产文件 mypy regression 0、Ruff/Black 通过。
- 明确未做：未删除 PolicyLog/RSS 配置维护投影，未改变 Policy AI 分类/审核流程，未部署、未 push；market.news 全量生产回填、Publication 覆盖和旧链 M9 清理仍未完成。

## 54. 2026-08-05：Config Center 摘要 Public Port 收口

- 目标：消除 Account 配置摘要仓储对 Config Center `SystemSettingsModel` 的直接 ORM 依赖，推进全局运行参数由 Config Center owner 统一提供。
- 变更：新增 `apps/config_center/application/public.py`，暴露系统设置、市场视觉 token、Qlib、Alpha provider/pool、benchmark 和 asset-proxy 的只读 Application Public Port；Config Center summary service/repository 补齐市场视觉 token 端口。
- `DjangoAccountConfigSummaryRepository` 改为调用 Config Center Public Port，保留账户摘要返回结构并继续追加 Data Center indicator catalog 计数；Account 不再直接 import Config Center ORM model。
- 已运行验证：Config Center public/跨 App bridge/运行时回归 `7 passed`；Account system-settings/runtime/model structure 回归 `13 passed`；变更文件 Ruff、Black、isort、mypy regression 通过；architecture boundary/audit 0、module-cycle 0、legacy-fact 0、current-data 43 surfaces 通过。
- 明确未做：未迁移 Account 账户注册、备份和管理写入流程中的 SystemSettings 维护 ORM；未删除兼容 re-export、未部署、未 push。
- 未验证风险：Config Center 全局 owner registry、SystemSettings 过期字段清理、生产 profile/rollback 与 PostgreSQL 证据仍未完成；全仓 governance consistency 受其他 agent 未提交的 `fixed_income` 大文件缺少 baseline 阻断，不能把该门禁结果记为通过。

## 55. 2026-08-05：Policy 通用新闻适配器退出直连 HTTP

- 目标：清除 D8 外部事实接入清单中 `apps/policy/infrastructure/adapters/news_adapter.py` 的直接 `requests` 依赖，避免通用政策新闻适配器绕过 Data Center transport/retry/observed-time 规则。
- 变更：Data Center RSS gateway 新增 bounded `probe_rss_feed` 与 Application `probe_rss_news_feed` Public Port；`NewsPolicyAdapter` 的可用性探测和新闻事实读取均经 Data Center，保留原 `session.get` 兼容注入面，并将 canonical `NewsFact` 映射为政策事件输入。
- 可靠性：新闻条目沿用 Data Center 源发布时间，缺失/超出日期窗口的条目不进入政策事件；适配器失败仍返回稳定的 `PolicyAdapterError`/不可用语义，不泄露凭据或底层异常。
- 已运行验证：RSS gateway + Policy adapter 回归 `19 passed`；变更文件 Ruff、Black、isort、mypy regression 通过；architecture boundary/audit 0、module-cycle 0、legacy-fact 0、current-data 43 surfaces；inventory external HTTP imports 从 5 降至 4。
- 明确未做：未删除 PolicyLog/RSS 配置维护投影，未改变 Policy AI 分类/审核工作流，未部署、未 push；生产 market.news backfill/publication 观察与 M9 旧链清理仍未完成。

## 56. 2026-08-05：治理 baseline 登记 fixed-income 大文件债务

- 目标：修复 CI 只剩的治理基线失败，让已提交的 research-only fixed-income 组合风险模块以机器可审计的 owner/remediation/review-by 方式纳入检查，而不是留下未登记债务。
- 变更：`governance/governance_baseline.json` 升级至 `2026-08-05.v207`，登记 `apps/fixed_income/domain/portfolio_risk.py` 当前 1238 个非空行、owner `fixed-income`、P1 拆分目标和 2026-09-30 review-by；不扩大业务能力或放宽行数上限。
- 计划语义：该登记只代表债务可追踪，不能把 research-only 代码、真实数据覆盖、Publication 证据或生产 readiness 解释为完成；后续拆分完成后必须移除该 allowance。

## 57. 2026-08-05：Equity AssetMaster 缺失时禁止事实反推

- 目标：阻断 Equity 股票信息读取在 AssetMaster 缺失时从 quote/price/valuation/financial latest 事实猜测证券身份的旁路，避免未发布市场事实承担 D0 主数据职责。
- 变更：`StockInfoRepositoryMixin.get_stock_info` 现在只返回 canonical AssetMaster 命中结果；删除按四类事实 `get_latest` 链式推断最小 `StockInfo` 的兼容路径。缺少 AssetMaster 时稳定返回 `None`，上层保持“未找到股票/blocked”语义。
- 治理与测试：`equity.published_stock_context` 增加 AssetMaster-only markers 和“存在未发布 price fact 仍不推断主数据”的 nodeid。
- 已运行验证：新增 Equity stock-context 回归、current-data manifest runner 与既有 Equity/Data Center 定向回归应在本批提交后复跑；未修改历史显式查询、canonical 写入或 provider 配置。

## 58. 2026-08-05：Alpha 市场温度计切换 current Application Port

- 目标：阻断 Alpha AI 二次筛选直接读取 `MarketThermometerSnapshotRepository.get_latest()` 的旁路，避免 stale/blocked 市场风险快照未经统一计算语义进入筛选 prompt。
- 变更：Data Center Public Port 新增 `get_current_market_thermometer_payload()`，复用 `load_market_thermometer_payload(use_personal_thresholds=False)` 的 freshness/blocked/fallback 逻辑；Alpha 保留 `get_latest_market_thermometer_snapshot_payload` 兼容别名，但实现只委托该 current port。
- 治理与测试：`data_center.market_thermometer` 合约新增 Public Port/Alpha marker 和兼容别名委托回归；Alpha 原有 monkeypatch 面不变。

## 59. 2026-08-05：当前摘要统一经 Data Center Public Port

- 目标：避免账户 sizing、宏观页和 realtime breadth 直接依赖 Data Center 内部 interface/query service，确保当前读入口统一经过可审计的 Application Public Port。
- 变更：新增带 `user_id`/`use_personal_thresholds` 显式参数的 `get_market_thermometer_payload` Public Port；账户、宏观页保留原本的用户阈值语义但改走该端口，Alpha 的非个人 current 端口复用同一实现。Realtime breadth 改用 `get_market_breadth_snapshot` Public Port。TUI 运维摘要仍保留其既有内部 interface 依赖，待下一批单独收口。
- 治理与测试：`data_center.market_thermometer` 与 `realtime.market_summary` 合约登记 Public Port、消费者 import marker 和精确回归 nodeid；定向回归 51 passed，current-data 43 surfaces、mypy regression 0、architecture boundary/audit 0。
- 明确未做：未改变市场温度计计算/阈值规则、历史查询、Publication writer/provider 配置、生产数据或部署；其余 maintenance/on-demand interface service 仍保留在 owner 内部边界。

## 60. 2026-08-05：已提交大文件治理债务登记

- 证据：clean HEAD 的治理门禁发现 `apps/data_center/domain/market_structure.py` 1327 行、`apps/sector/domain/industry_operating_template.py` 1372 行超过 1200 行上限，且此前没有精确 owner/remediation 登记。
- 收口：`governance_baseline.json` 升级至 `2026-08-05.v208`，为两个文件登记 P1 拆分目标、owner、review-by 和对应计划路径；不抬高全局行数上限，也不把登记解释为拆分完成。
- 边界：该治理提交只解决 CI 可审计债务，不改变市场结构/行业模板业务语义，不删除代码、不部署生产；拆分仍需各 owner 按独立研究能力批次实施。

## 61. 2026-08-05：决策 readiness/coverage Public Port 收口

- 目标：避免 Decision Rhythm 的健康检查直接导入 Data Center 内部 interface service，统一 current 决策 readiness 与 active-stock coverage 经过可审计 Public Port。
- 变更：Data Center Public Port 新增 `get_decision_data_readiness_payload` 与 `get_active_stock_fact_coverage_payload`；`DecisionDataHealthProvider` 改为使用 readiness Public Port。原有参数、阻断字段和 diagnostic coverage 语义不变。
- 治理与测试：新增 `data_center.public_current_read_ports` current-data contract，登记 Public Port/消费者 marker 与 3 条回归；定向回归和 clean worktree current-data runner 将覆盖该端口。
- 明确未做：未改动 Decision Rhythm 风险规则、资产 exposure resolver、历史/维护查询、Publication writer/provider 配置或生产部署；TUI 运维摘要的内部 readiness/coverage import 仍待其 owner 工作区干净后单独收口。

## 62. 2026-08-05：Decision Rhythm 资产 exposure 切换 canonical resolver Port

- 目标：消除 Decision Rhythm 资产暴露摘要对 Data Center DTO 和内部 resolver use case 的直接依赖，确保行业/资产类型上下文来自 canonical AssetMaster Public Port。
- 变更：新增 `resolve_asset_payload` Public Port，负责规范化代码、调用 Data Center resolver 并返回 plain payload；`DataCenterAssetExposureProvider` 只消费该端口，缺失资产继续显式保留空 exposure，不推断身份。
- 治理与测试：扩展 `data_center.public_current_read_ports` contract 与资产 exposure 回归；Decision Rhythm provider 定向测试与 current-data manifest 会验证 Public Port 委托。
- 明确未做：未修改 AssetMaster 写入/backfill、历史研究 resolver、行业分类算法或生产数据；TUI 内部 coverage/readiness 兼容 import 仍待独立 owner 批次。

## 63. 2026-08-05：Qlib Runtime 退出 SystemSettings 运行时 fallback

- 目标：完成 Qlib 配置迁移中的一个明确退出条件，运行时缺少完整 Config Center typed snapshot 时必须阻断，不再静默读取 `SystemSettingsModel` 的 Qlib 字段。
- 变更：`DjangoConfigCenterSummaryRepository.get_runtime_qlib_config()` 与系统摘要均只接受 active、版本匹配的 typed snapshot；缺失/失效返回 `status=blocked`、`must_not_use_for_decision=true` 和稳定 `runtime_config_snapshot_unavailable`。旧 `SystemSettingsModel` getter 仅保留迁移维护用途，未被运行时桥调用。
- 治理与测试：`runtime_config_contracts.json` 的 Qlib fallback 改为 `blocked`，新增缺失快照回归；后续仍需在受控环境初始化 production/非默认 profile 并验证所有 Qlib 调度链。
- 明确未做：未删除旧模型字段/迁移、未改变 Qlib 算法或训练参数，未初始化本地/生产 profile，未部署。

## 64. 2026-08-05：Retention preview 与 Storage Budget 接入正式 Beat

- 目标：把已具备 fail-closed 任务契约的 retention dry-run 和 storage pressure 检查接入统一 Celery Beat，避免只存在手工调用而没有运行调度。
- 变更：`core/settings/base.py` 为 D0-D9 十个 dataset 登记每日 `plan_retention_task` dry-run，统一保留 `expire_seconds`；新增每 15 分钟 `verify_storage_budget_task`。没有把 `enforce_retention_task` 放进自动调度，删除仍需显式确认和运维授权。
- 测试：Beat schedule 组件回归验证十个 dataset 全覆盖、均为 plan task 且无 destructive kwargs；Celery contracts 18 tasks、Django check 均通过。
- 明确未做：未执行真实删除、归档、PostgreSQL/VPS 数据清理或容量故障注入；实际生产调度结果仍需部署后 run_id/StorageBudget 证据。

## 65. 2026-08-05：Qlib 训练任务增加 typed runtime fail-closed

- 目标：防止 Qlib 训练任务在 Config Center typed snapshot 缺失时继续使用 POSIX 根目录下的 `models/qlib` 文件系统目录等代码默认值启动训练，绕过运行时配置可靠性门。
- 变更：`qlib_train_model` 在标记训练 run 前校验 typed runtime 的 `enabled`/阻断字段；快照缺失、失效或显式 blocked 时抛出稳定错误并把训练 run 标为失败，不写 Registry、不保存 artifact。
- 测试：成功/失败训练 fixture 显式注入可用 typed runtime；新增缺失快照阻断回归；Qlib training/runtime/task 定向回归 50 passed，最新变更 mypy/Ruff/Black/isort 通过。
- 明确未做：未改动 Qlib 模型算法、缓存前推、历史数据路径或 SystemSettings 迁移字段；推理任务及生产 profile 初始化仍需后续阶段证据。

## 66. 2026-08-05：Qlib 推理任务增加 typed runtime fail-closed

- 目标：阻断 Qlib 推理在读取本地日历、激活模型或刷新数据前绕过 Config Center typed snapshot，避免缺失运行时配置时继续探测默认/旧 provider URI 并以前推缓存伪装当前结果。
- 变更：`qlib_predict_scores` 在任何模型与本地数据访问前调用 Config Center runtime 读取和统一可用性校验；缺失、失效或显式 blocked 的 snapshot 稳定阻断任务，不进入 legacy calendar/model/cache 路径。可用运行时仅记录 `status/source` 元数据，不记录 URI 或凭据。
- 测试与治理：预测成功/刷新/缓存 fallback fixture 显式注入可用 typed runtime；新增“阻断发生在旧 runtime probe 之前”的回归；`runtime_config_contracts.json` 登记 inference gate consumer/test。Alpha/Qlib 定向回归 `30 passed`，Qlib integration 回归 `29 passed`；变更文件 mypy 0、Ruff/isort 通过，current-data 44 surfaces、runtime config coverage 49、governance consistency 0 violations。
- 明确未做：未改变 Qlib 模型算法、历史研究模式、缓存前推策略或 SystemSettings 迁移字段，未初始化 production/non-default profile，未部署。
- 未验证风险：Qlib inference 的 PostgreSQL 生产缓存覆盖、实际 typed profile 初始化、连续交易日/节假日 freshness 观察窗口和旧链 M9 清理仍待生产阶段证据。

## 67. 2026-08-05：Qlib 基础日历探测退出默认 provider URI

- 目标：防止 Qlib 日历探测、初始化检查或直接基础 runtime 调用绕过推理任务门，在 Config Center typed snapshot 缺失时继续访问 `~/.qlib/qlib_data/cn_data` 等默认路径。
- 变更：`apps/alpha/infrastructure/qlib_runtime_init.py::_get_qlib_data_latest_date` 在初始化 Qlib 前复用稳定的 typed runtime 可用性校验；blocked/缺失快照直接抛出 `runtime_config_snapshot_unavailable`，不执行 provider 初始化。
- 测试与治理：新增基础日历探测 blocked 回归；补充 `runtime_config_contracts.json` 的 infrastructure gate marker/test。Alpha runtime/management 定向回归 `35 passed`，Qlib integration `29 passed`；变更文件 mypy 0、Black/Ruff/isort 通过，runtime config coverage 49、current-data 44 surfaces；clean `cfef37ec` worktree 的 current-data manifest 实际执行 `245 nodeid / 284 passed`。
- 明确未做：未改变 Qlib 历史维护命令的显式参数语义、模型算法或 provider 写入，未初始化 production profile，未部署。
- 未验证风险：生产 Qlib provider URI 的 typed profile 初始化、数据目录覆盖、PostgreSQL 缓存性能和 M9 旧链清理仍待生产阶段证据。

## 68. 2026-08-05：TUI 运维摘要切换 Data Center Public Port

- 目标：完成前述 TUI 运维摘要的本地入口收口，避免用户可见治理队列直接依赖 Data Center 内部 `interface_services/query_services`，绕过稳定的 Application Public Port 边界。
- 变更：`apps/terminal/application/tui_operator_services.py` 的 coverage/readiness/market-thermometer 读取统一改用 `apps.data_center.application.public`；保留用户可见摘要字段和 freshness/blocking 语义不变。
- 治理与测试：`data_center.public_current_read_ports` 增加 TUI consumer marker 与精确回归节点；更新 TUI operator 测试以验证 Public Port 注入。
- 明确未做：未改变 TUI 文案、页面动作、Data Center 计算/写入、历史查询或生产配置，未部署。
- 未验证风险：生产 TUI 端到端渲染、Public Port 真实 publication 覆盖和 PostgreSQL 查询预算仍待生产阶段证据。

## 69. 2026-08-05：实盘下单风控报价绑定 Quote Publication

- 目标：避免 Broker Execution 的 live-order pre-trade risk 通过 Data Center 内部 `QueryLatestQuoteUseCase` 读取 raw latest quote；下单前的市场报价必须来自同一 canonical Quote Publication/member gate。
- 变更：新增 `get_published_latest_quote_payload` Public Port，保留 publication/member/freshness/blocked 证据；`CreateLiveOrderFromExecutionPlanUseCase` 的默认报价 provider 改为该端口，缺失或阻断时仍按风险违规 fail closed。
- 治理与测试：新增 `broker_execution.live_order_quote` current-data contract；Public Port blocked/member-row 和 Broker 默认 provider 回归共 `16 passed`，变更文件 mypy 0、Black/Ruff/isort 通过；current-data contracts `45 surfaces`。
- 明确未做：未改变显式注入的测试/维护报价 provider、订单状态机、QMT 写入或执行路由，未部署。
- 未验证风险：生产 Quote Publication 覆盖、真实下单 PostgreSQL 查询预算、QMT/VPS 生产链路与旧报价读取零访问仍待生产阶段证据。

## 70. 2026-08-05：Dashboard 资产身份切换 AssetMaster Public Port

- 目标：消除 Dashboard 资产上下文对 Data Center 内部 ResolveAsset use case 的直接依赖，使 current stock context 的证券身份只来自 canonical AssetMaster Public Port，不再让跨 App Interface 具体实现成为隐式边界。
- 变更：`DashboardApplicationGateway.resolve_asset()` 改用 `resolve_asset_payload`；Dashboard repository 同时兼容 Public Port mapping 与旧 DTO 形状，保持名称、行业和市场投影不变。
- 治理与测试：扩展 `equity.published_stock_context` 的 Dashboard Public Port marker，新增 AssetMaster Public Port 回归。
- 明确未做：未改变 AssetMaster 写入、legacy holding name 维护流程、Equity 历史查询或生产配置，未部署。
- 未验证风险：生产 AssetMaster 覆盖、Dashboard PostgreSQL 查询预算、旧身份投影零读写和 M9 清理仍待生产阶段证据。

## 71. 2026-08-05：Dashboard AssetMaster Public Port 回归收口

- 测试与治理：Dashboard Data Center publication/asset-port 定向回归 `5 passed`；变更的 Gateway/Repository 文件 mypy 0、Black/Ruff/isort 通过；current-data contracts `45 surfaces`。
- 备注：同一批未纳入本次改动的两个旧 Dashboard allocation guardrail 测试仍因既有 `AllocationPolicyUnavailableError` 失败；该问题与 AssetMaster Public Port 无调用关系，未将其伪装为本批通过，也未修改策略运行时配置。

## 72. 2026-08-05：Core readiness Data Center Public Port 收口

- 目标：避免 Core readiness/health checks 直接导入 Data Center interface/query services，确保决策数据 readiness、coverage 和 provider capability health 走稳定 Application Public Port。
- 变更：新增 `get_decision_provider_capability_health_payload` Public Port；`core.health_checks` 的三类决策检查统一切换到 Public Port，保留原 status/block_reason 投影。
- 治理与测试：`data_center.provider_capability_health` 增加 Core consumer marker/test；新增 readiness Public Port 回归。
- 明确未做：未改变健康检查阈值、provider health 记录器、发布器或生产配置，未部署。
- 未验证风险：生产 readiness API 的真实 provider health 覆盖、PostgreSQL 查询预算和运行时观察窗口仍待生产阶段证据。

## 73. 2026-08-05：Operational Readiness current 读取切换 Public Port

- 目标：消除 readiness 状态命令和 monitor 对 Data Center `interface_services/query_services` 的 current 决策数据与覆盖率旁路，使用户可见的 readiness 结果统一经过 Application Public Port。
- 变更：`build_current_decision_data()` 改为直接调用 `get_decision_data_readiness_payload` Public Port；`get_active_stock_fact_coverage_payload()` 的动态解析目标改为 `apps.data_center.application.public`，保留 payload 校验和错误脱敏语义。
- 治理与测试：扩展 `data_center.public_current_read_ports` marker/source/test；新增 Public Port 委托和动态模块目标回归，readiness 定向安全测试 `15 passed`，current-data 静态合同 `45 surfaces`。
- 明确未做：未改变 readiness 阈值、证据窗口、覆盖率计算、历史/维护查询、Publication writer/provider 配置或生产部署。
- 未验证风险：生产 readiness monitor 的真实 Publication 覆盖、PostgreSQL 查询预算、连续交易日观察窗口与旧链 M9 清理仍待生产阶段证据。

## 74. 2026-08-05：Readiness Public Port 循环依赖回归修复

- 发现：将 `status_services` 静态导入 Data Center Public Port 会形成 `data_center → task_monitor → operational_readiness → data_center` 循环；该失败由最新 HEAD clean worktree 的 module-cycle gate 捕获。
- 修复：保留 Public Port 目标不变，改为受类型校验的动态 Application Port 解析，并在 current-data contract marker 中锁定目标模块；不恢复任何 `interface_services/query_services` 读取。
- 证据：`check_module_cycles.py` 回到 0 cycle/0 bidirectional；最新 HEAD 全仓 mypy `0 errors in 0 files`、`manage.py check` 0 issues；current-data manifest `253 nodeid / 292 passed`。
- 明确未做：未改变 readiness 业务阈值、数据计算、历史/维护端口、生产配置或部署；生产 PostgreSQL/观察窗口和 M9 旧链退出仍未完成。

## 75. 2026-08-05：Macro TUI 趋势查询切换 Public Port

- 目标：消除宏观 TUI 趋势过滤器对 Data Center 内部 `make_query_macro_series_use_case` 的跨 App 直接依赖，确保趋势输入和宏观 overview 使用同一 Publication/member 语义。
- 变更：新增 `get_published_macro_series_response` Public Port；由 Data Center 内部完成 freshness gate、Publication member fact_pk 绑定和 fail-closed 响应，`apps/macro/composition.py` 仅调用该端口。
- 治理与测试：更新 `macro.tui_publication` source/markers；Public Port 的 member 绑定与缺失 Publication 阻断、Macro composition 委托及 TUI 回归共 `28 passed`；current-data `45 surfaces`、module-cycle 0、变更文件 mypy regression 0。
- 明确未做：未改变趋势算法、宏观历史/维护页面、Publication writer/provider 配置或生产部署；生产 Publication 覆盖、PostgreSQL 查询预算和 M9 旧链退出仍待完成。

## 76. 2026-08-05：Macro TUI overview selected series 统一 Public Port

- 目标：补齐宏观 TUI overview selected-series 的最后一条内部 Data Center query-use-case 旁路；当前 overview 与 trend filter 必须共享同一 Publication-bound response port。
- 变更：`get_macro_data_page_snapshot(published_only=True)` 的 selected history 改调用 `get_published_macro_series_response`；只有 Classic staff/historical maintenance 分支继续使用内部历史 query use case。
- 治理与测试：`macro.tui_publication` 更新 interface marker；宏观 interface/composition/API 回归 `22 passed`，current-data `45 surfaces`、mypy regression 0。
- 明确未做：未改变 Classic staff raw/historical 语义、趋势算法、Publication writer/provider 配置或生产部署；生产 query budget、Publication 覆盖和 M9 旧链退出仍待完成。

## 77. 2026-08-05：Regime V2 当前输入切换 Publication-only

- 目标：消除 Regime V2 当前决策链对 `get_*_series(... use_pit=True)` raw facts 的旁路，避免未发布或过期的非空事实进入 current Regime。
- 变更：`CalculateRegimeV2Request` 新增显式 `published_only` 选择；Regime Data Center adapter 在该模式下只调用 `get_published_series`，按映射后的 canonical indicator code 绑定 Publication member/freshness，CPI fallback 也继续走 Publication；历史回算默认保持 raw/PIT 语义。
- 消费者：`resolve_current_regime`、同步后当前计算和 Regime Navigator 均显式传 `published_only=True`；未声明 current 的计算 API 仍保留显式 historical/PIT 入口，避免把研究日期误解释为当前出版快照。
- 治理与测试：扩展 `data_center.publication_only_d2_d3` markers；Publication-only adapter 的 raw-read 禁止、缺失 Publication fail-closed、V2 全量 selector 传播和 current resolver selector 回归已登记。
- inventory：在不含外部未提交 portfolio 改动的 clean HEAD worktree 重新生成 `governance/data_center_architecture_inventory.json`，`current_surface_references=3218`，其余结构计数保持不变。
- 已运行验证：Regime/adapter 相关回归 `26 passed`；`tests/unit/regime` `60 passed`；current-data manifest 实际执行 `259 nodeid / 298 passed`；architecture boundary/audit 0、module-cycle 0、legacy fact guard 通过；`manage.py check` 0 issues；变更生产文件 mypy regression 0，Ruff/Black 通过。
- 明确未做：未修改 Regime 历史研究/PIT API、Publication writer/provider、生产数据、VPS 或部署；生产 Publication 覆盖、PostgreSQL 性能/备份恢复、连续交易日观察窗口和 M9 旧链清理仍未完成。

## 78. 2026-08-06：Signal/Alpha Trigger 指标摘要切换 Publication Port

- 目标：消除 Signal 管理页和 Alpha Trigger 页面通过 `apps.macro.application.indicator_service` 读取 raw latest 指标的 current-data 旁路。
- 变更：Data Center 新增 `list_published_macro_indicator_summaries` Public Port；按 canonical catalog 和每指标 Publication/member/freshness 结果生成前端摘要，保留 `observed_at`、`source`、`publication_id`、`freshness_status` 和阻断字段。Signal query/interface 与 Alpha Trigger 页面改用该端口；宏观历史/维护 IndicatorService 保留原语义。
- 治理与测试：扩展 `data_center.publication_only_d2_d3` consumer/marker/test 登记；Public Port、Signal、Alpha Trigger 定向回归 `24 passed`，变更文件 mypy/Ruff/Black 通过，current-data 静态合同和 legacy-fact guard 通过。
- inventory：在 clean HEAD worktree 重生成架构 inventory，`current_surface_references=3220`，其余结构计数保持不变。
- 依赖治理：新增的 Alpha Trigger → Data Center Public Port 合法边改已登记到 `module_cycle_allowlist.json` v21；更新精确 inbound/outbound/edge budgets 后 cycle audit 为 0 cycle、0 bidirectional、0 budget/stale violations。
- 明确未做：未改变历史指标统计、宏观维护写入、Publication writer/provider、生产数据、VPS 或部署；生产 publication 覆盖、PostgreSQL 查询预算、观察窗口和 M9 旧链清理仍未完成。

## 79. 2026-08-06：宏观页面指标元数据切换 canonical catalog Public Port

- 目标：消除宏观页面 Application 对 `apps.macro.application.indicator_service.IndicatorService` 的元数据依赖，避免 current TUI catalog 与旧 projection 维护服务形成隐式旁路。
- 变更：`get_supported_macro_indicators()` 与 `get_macro_data_page_snapshot()` 统一调用 `apps.data_center.application.public.get_macro_runtime_metadata()`；历史指标统计、单位维护和写入服务仍保留在宏观 owner 内，仅页面元数据读取切换到 Data Center canonical catalog。
- 治理与测试：`macro.tui_publication` 增加 `get_macro_runtime_metadata()` marker；宏观 interface/composition/TUI API 回归 `22 passed`，current-data contract `45 surface(s)`，Ruff/Black 通过。
- inventory：在包含已提交 portfolio canonical optimization 变更、且不含工作区未提交内容的 clean HEAD worktree 重生成架构 inventory，`current_surface_references=3249`，其余结构计数保持 `51/55/4/143/0/49`。
- 全局回归：current-data manifest 实际执行 `260 nodeid / 299 passed`；legacy-fact guard、mypy debt ceiling（`0 errors in 0 files`）、Celery task contracts（18 tasks）、runtime-config coverage（49 references）、storage budget、runtime desired-state 均通过。
- 明确未做：未改变宏观事实查询、历史维护接口、Publication writer/provider、生产数据、VPS 或部署；生产 catalog 覆盖、PostgreSQL 查询预算、观察窗口和 M9 旧链清理仍未完成。

## 80. 2026-08-06：Dashboard current 宏观健康读取强制 Publication-only

- 目标：阻断 Dashboard 首页宏观健康与 PMI/CPI 摘要经 `DashboardApplicationGateway → Regime query service` 的 raw latest/非 PIT 旁路；current 页面只能使用 canonical Publication members。
- 变更：Regime growth/inflation query helpers 增加 `published_only` 选择并完整传播到 adapter；Dashboard gateway 对 `use_pit=False` 的读取强制 `published_only=not use_pit`，显式 PIT 历史研究仍保持 raw/PIT 语义。
- 测试与治理：`data_center.publication_only_d2_d3` 登记 Dashboard gateway 和 Regime query markers；新增 current gateway selector 回归，Dashboard macro integration fixture 改为真实 Publication/member；selector/宏观回归 `14 passed`（含 1 个 component），mypy regression 0、Ruff/Black 通过，AllocationPolicyUnavailableError 的 2 个既有无关失败未修改。
- inventory：在不含工作区未提交 Equity 文件的 clean HEAD worktree 重生成架构 inventory，`current_surface_references=3251`，其余结构计数保持 `51/55/4/143/0/49`。
- 明确未做：未改变 Regime 算法、历史研究查询、Publication writer/provider、生产数据、VPS 或部署；生产 Publication 覆盖、PostgreSQL 查询预算、观察窗口和 M9 旧链清理仍未完成。

## 81. 2026-08-06：Sector current Regime 退出诊断快照旁路

- 目标：阻断 Sector rotation 在未显式指定 Regime 时直接使用 `get_latest_regime_diagnostic_payload()` 的旧持久化快照，避免 stale/blocked Regime 继续驱动当前板块权重。
- 变更：`AnalyzeSectorRotationUseCase` 改用统一 `resolve_current_regime()`；current Regime 为 `Unknown`、stale 或 `must_not_use_for_decision` 时稳定返回 `status=blocked`，只有可用 Publication 结果才进入板块分析。显式请求的历史/研究 Regime 仍保持原入口。
- 治理与测试：`regime.current` 登记 Sector consumer/markers/test；Sector fallback 回归 `7 passed`，新增 stale/blocked 不读取旧快照断言；变更文件 mypy regression 0，architecture boundary/audit 0，module-cycle 0。
- inventory：在不含工作区未提交 Equity 文件的 clean HEAD worktree 重生成架构 inventory，`current_surface_references=3257`，其余结构计数保持 `51/55/4/143/0/49`。
- 明确未做：未改变 Sector 派生指标、历史显式 Regime 参数、Publication writer/provider、生产数据、VPS 或部署；生产 Regime Publication 覆盖、观察窗口和 M9 旧链清理仍未完成。

## 82. 2026-08-06：Dashboard Regime 摘要与首页统一 current resolver

- 目标：清除 Dashboard 摘要查询和首页聚合在当前 Regime 不可用时回读旧 `get_latest_snapshot()` 的旁路，防止历史快照伪装成当前决策数据。
- 变更：`RegimeSummaryQuery` 与 `GetDashboardDataUseCase` 统一消费 `resolve_current_regime()`；成功路径保留 resolver 的 `observed_at`、动量和分布，stale/blocked 路径返回 `Unknown`、原始观测日、阻断 warning 和空决策分布，不再使用旧快照补值。`DashboardData.regime_date` 改为可空，避免无观测日期时用请求日洗白来源时间；保留 `regime_repo` 构造参数仅作兼容，不再调用其 snapshot API。
- 治理与测试：`regime.current` 登记 Dashboard queries/use case 的 resolver markers 和精确测试；Dashboard 定向回归 `18 passed`，页面级回归 `3 passed`；current-data manifest 实际执行 `264 nodeid / 303 passed`；current-data contracts `45 surfaces`、architecture boundary/audit 0、module-cycle 0、变更文件 mypy regression 0、Ruff/Black 通过。
- inventory：在不含工作区未提交 Equity 文件的 clean HEAD worktree 重生成架构 inventory，`current_surface_references=3280`，其余结构计数保持 `51/55/4/143/0/49`。
- 明确未做：未修改 Dashboard 历史/PIT 研究语义、Regime 算法、Publication writer/provider、生产数据、VPS 或部署；生产 Publication 覆盖、PostgreSQL 查询预算/备份恢复、连续交易日观察窗口和 M9 旧链清理仍未完成。

## 83. 2026-08-06：自动投顾与 Signal Regime payload 发布阻断证据

- 目标：阻断 Dashboard 自动投顾摘要和 Signal 页面把 `Unknown`/stale Regime 序列化为 `status=ok` 或无 freshness 证据的普通 payload。
- 变更：两个 current payload 统一发布 `status`、`observed_at`、`must_not_use_for_decision` 和稳定 `blocked_reason`；blocked 时清空决策分布，异常只返回 `regime_data_unavailable`，不再把底层异常文本写入用户响应。
- 治理与测试：`regime.current` 增加 Dashboard query service、Signal query service markers 和精确回归；自动投顾组件 `13 passed`，Signal query `2 passed`，current-data manifest 实际执行 `266 nodeid / 305 passed`，current-data contracts `45 surfaces`，变更文件 mypy/Ruff/Black 通过。
- inventory 与门禁：clean HEAD inventory 的 `current_surface_references=3288`，其余结构计数 `51/55/4/143/0/49`；clean HEAD governance consistency `0 violations`，architecture boundary/audit、module-cycle、legacy-fact、Celery task contracts（18 tasks）和 runtime-config coverage（49 references）均通过。根工作区 governance 仍会被其他 agent 未提交的 `apps/equity/domain/forecast_baseline_inputs.py` 1674 行触发，未纳入本轮。
- 明确未做：未改变 Signal 历史校验、推荐矩阵、Dashboard advisor 业务规则、Regime 算法、Publication writer/provider、生产数据、VPS 或部署；生产 Publication 覆盖、PostgreSQL 查询预算/备份恢复、观察窗口和 M9 旧链清理仍未完成。

## 84. 2026-08-06：Alpha/市场运行参数 typed projection 与账户代理读取收口

- 目标：为 Alpha provider/pool、市场颜色约定、benchmark map 和 asset-proxy map 建立可校验的 RuntimeConfigDefinition，并让 Config Center 摘要与账户回测代理读取在完整 typed snapshot 存在时优先使用同一快照，避免继续把旧 `SystemSettingsModel` getter 当作当前真源。
- 变更：新增 5 个 typed definitions 与 all-or-nothing `get_active_domain_runtime_config()`；Config Center summary/repository 统一读取完整 typed projection，快照缺失或不完整时才走已登记的 SystemSettings compatibility；Account `SystemSettingsRepository.get_runtime_asset_proxy_code()` 改走 Config Center Application Public Port，旧 asset-proxy getter 不再被该运行时消费者调用。
- 治理：`governance/runtime_config_contracts.json` 登记 5 个 key、owner、consumer、fallback 和精确测试；账户代理读取回归明确断言旧 singleton getter 未被调用。
- 测试：Config Center 定向回归 `16 passed`，Config Center component `3 passed`，Account repository/backtest 回归 `5 passed`；变更文件 Black/Ruff/mypy regression 通过；current-data manifest 实际执行 `266 nodeid / 305 passed`；runtime config coverage `49`、current-data contracts `45 surfaces`、architecture boundary `0`、module-cycle `0`、legacy-fact guard、Celery task contracts（18 tasks）和 governance consistency `0 violations`。
- 明确未做：仍保留 SystemSettings compatibility fallback；`ConfigCenterSettingsRepository.update_runtime_config()` 等旧管理写入流程尚未改成 typed profile activation，未执行全量字段迁移、生产 profile 初始化、PostgreSQL/备份恢复、观察窗口、M9 旧字段删除或 M10 生产切读；不部署、不 push。

## 85. 2026-08-06：Regime current cache warmup 与诊断命令退出 raw snapshot 旁路

- 目标：防止运维缓存预热和数据连接诊断把过期 Regime 持久化快照重新包装成当前状态，确保这两个 current/diagnostic 入口复用统一 freshness-aware resolver。
- 变更：`get_latest_regime_cache_payload()` 改为调用 `resolve_current_regime()`；stale/blocked/Unknown 结果不再写入 `regime:current`，fresh 结果保留源 `observed_at`、`freshness_status` 和阻断字段。`test_data_connections.test_regime_calculation()` 改用 `get_regime_current_payload()`，阻断时输出 warning，不再直接读 raw `get_latest_regime_diagnostic_payload()`。
- 治理与测试：新增 `regime.current_cache_warmup` current-data contract，current surface 增至 `46`；Regime freshness/management command 回归 `17 + 14 passed`，变更文件 Black/Ruff/mypy regression 通过，架构与 legacy guard 保持通过。
- 明确未做：未改变历史 Regime 查询、计算算法、Publication writer/provider、生产缓存、PostgreSQL、观察窗口、M9/M10 或部署；Config Center typed profile activation 与 SystemSettings 全量退役仍待继续。

## 86. 2026-08-06：Config Center Qlib/市场配置写入切换 typed Profile

- 目标：消除“读 typed snapshot、写回 `SystemSettingsModel`”的配置双真源，确保 Qlib/Alpha/市场运行参数的管理入口产生可审计的 Profile/Revision/Snapshot 前向版本。
- 变更：新增 `activate_runtime_profile_patch()`，按 active profile 携带已有值、以显式 compatibility bootstrap 补齐缺键、由请求 patch 覆盖并原子激活新版本；`ConfigCenterSettingsRepository.update_runtime_config()` 与 `update_system_governance()` 改为调用该端口，不再写 Qlib/Alpha/benchmark/asset-proxy/market-color 旧字段。Qlib 运行配置摘要在无 typed snapshot 时返回 blocked，而不是展示旧 singleton 默认值；Data Center provider settings 增加只读 Application Public Port，兼容导入只发生在激活事务中。
- 测试与治理：Config Center training/runtime 回归 `32 passed`，TUI/runtime 相关回归 `12 passed`；新增 typed update 回归断言旧 singleton 未写入；current-data manifest 实际执行 `268 nodeid / 307 passed`；变更文件 Black/Ruff/mypy regression 通过，runtime contract 登记 mutation consumers/tests。clean HEAD inventory 为 `current_surface_references=3291`，其余结构计数 `51/55/4/143/0/49`。
- 明确未做：账户审批、备份 SMTP、决策运行状态等其他 SystemSettings 字段仍处于兼容迁移；尚未在生产 profile 上初始化/激活、执行 PostgreSQL/备份恢复/观察窗口、M9 删除旧字段或部署；不 push、不部署。

## 87. 2026-08-06：Data Center Provider failover 管理写入接入 typed Profile

- 目标：消除 Provider 设置页更新 `enable_failover/failover_tolerance` 后仍只写 Data Center 旧 singleton、导致 typed failover consumer 看不到新值的双真源。
- 变更：新增 Config Center runtime write composition bridge；Data Center Provider 设置保存将 failover 两个值作为 typed patch 激活版本化 Profile，仅保留 `default_source` 在 Data Center 自有设置中；读取优先 active typed 值、无 profile 时才显式兼容旧设置。旧 singleton 的 failover 字段不再被管理写入覆盖。
- 测试与治理：新增 component 回归断言 typed 返回值与旧字段未被覆盖；Data Center interface/bridge/config-center 回归通过，current-data manifest 保持 `268 nodeid / 307 passed`、current contracts `46 surfaces`，runtime contract 补齐写入 consumer/test；clean HEAD inventory 保持 `current_surface_references=3291`，其余结构计数 `51/55/4/143/0/49`。
- 明确未做：未迁移 Data Center `default_source` 及其他 Provider 配置字段、生产 profile 初始化、PostgreSQL/备份恢复/观察窗口、M9/M10 或部署；不 push、不部署。

## 88. 2026-08-06：账户系统设置页运行时写入切换 Config Center Public Port

- 目标：消除 Classic 账户管理页仍直接给 `SystemSettingsModel` 写市场颜色、Alpha pool、benchmark map 和 asset-proxy map 的最后一条管理旁路，确保页面提交与 TUI/Config Center 使用同一 typed Profile。
- 变更：新增 Config Center `get_system_governance_settings` / `update_system_governance_settings` Application Public Port；账户设置上下文优先读取 typed governance 并使用 typed visual tokens，提交时把四项运行时字段交给 Config Center use case，以 actor 记录 Profile revision；旧 singleton 仅继续保存账户准入、协议和备注兼容字段。视图将管理员作为 actor 传入。
- 测试与治理：新增组件回归断言账户设置提交激活 typed market governance 且旧 singleton 五项运行时字段不变；Config Center runtime component `6 passed`，账户 repository/view 回归 `4 + 18 passed`，完整 current-data manifest `268 nodeid / 307 passed`，变更文件 Black/Ruff/isort 通过；runtime contract 为五个 Alpha/market keys 登记账户管理 mutation consumer/test，clean inventory `current_surface_references=3291`（结构计数 `51/55/4/143/0/49`）。
- 明确未做：未删除 SystemSettings 兼容字段、未迁移账户准入/备份/决策状态、未初始化生产 profile、未执行 PostgreSQL/备份恢复/观察窗口/M9/M10 或部署；不 push、不部署。

## 89. 2026-08-06：兼容 Django Admin 禁止 typed runtime 直写

- 目标：补齐 `SystemSettingsModel` Django Admin 这一条未受账户设置页改造覆盖的写入入口，避免管理员从 Classic Admin 直接提交 Qlib、Alpha、市场颜色、benchmark 或 asset-proxy 字段绕过 Config Center Profile。
- 变更：`SystemSettingsAdminForm` 排除全部 typed runtime fields；Admin fieldsets/list display 不再暴露旧运行时字段，改为只读迁移提示并引导 Config Center/TUI。账户准入、协议、备份和备注等兼容字段仍保持原有 Admin 流程。
- 测试与治理：新增 Admin 结构回归，断言 form 和 fieldsets 均不接受 typed runtime 字段；Admin import、Django check、Ruff/Black 通过；runtime contract 为 Alpha/market 定义登记该 guard test。
- 明确未做：未删除兼容模型字段、未改动 Config Center/TUI 管理页面、未迁移备份/决策状态字段、未初始化生产 profile、未执行 PostgreSQL/观察窗口/M9/M10 或部署；不 push、不部署。

## 90. 2026-08-06：Data Center Provider Admin 禁止 failover 旧链写入

- 目标：补齐 Data Center `DataProviderSettingsModel` Admin 入口，避免管理员直接修改旧 singleton 的 `enable_failover/failover_tolerance`，导致 failover adapter 读取 typed profile 与管理界面不一致。
- 变更：新增专用 Admin Form，仅保留 Data Center 自有 `default_source/description`；typed failover 开关、容差和迁移说明改为只读摘要，管理修改继续走 Provider API 的 Config Center runtime write port。
- 测试与治理：新增 Admin form/fieldset guard `2 passed`，Django check、Ruff/Black 通过；runtime contract 为两个 Data Center provider keys 登记 Admin guard test。
- 明确未做：未删除 DataProviderSettings 兼容字段、未迁移其他 Provider 配置/生产 profile、未执行 PostgreSQL/观察窗口/M9/M10 或部署；不 push、不部署。

## 91. 2026-08-06：只读配置路径禁止创建 SystemSettings 单例

- 目标：避免 readiness、备份下载 URL、账户管理上下文和账户设置/MCP 指引等只读路径调用带 `get_or_create()` 的 `SystemSettingsModel.get_settings()`，产生隐式 INSERT/修复性 UPDATE 并污染配置变更审计。
- 变更：上述只读入口统一改用 `get_settings_for_read()` 的 unsaved-default 语义；仍需保存账户注册策略或提交管理表单的写入流程保留显式 `get_settings()`。
- 测试与治理：新增 AST guard 覆盖 core encryption readiness、backup URL、Account admin/registration read paths；账户/备份/加密 readiness 回归 `25 + 3 passed`，变更文件 Black/Ruff/mypy 通过。
- 明确未做：未迁移账户注册策略、备份发送写入、决策运行状态或其他兼容字段、未初始化生产 profile、未执行 PostgreSQL/观察窗口/M9/M10 或部署；不 push、不部署。

## 92. 2026-08-06：Provider 设置 Public Read Port 禁止创建旧单例

- 目标：修复前一轮新增的 Data Center Provider 设置只读 Public Port 仍经 `DataProviderSettingsRepository.load()` 创建旧 singleton 的副作用，确保 typed failover 摘要读取本身不产生配置写入。
- 变更：Provider settings repository 新增 `load_for_read()` 并让 `load_provider_settings_payload()` 使用它；写入流程继续显式使用 `load()`/`save_default_source()`，domain Protocol 同步声明读写分离。
- 测试与治理：新增 Provider payload AST side-effect guard；typed failover component 回归与 guard `2 passed`，变更文件 Black/Ruff 通过。
- 明确未做：未删除 DataProviderSettings 兼容 singleton、未迁移 default_source/Provider credentials、未初始化生产 profile、未执行 PostgreSQL/观察窗口/M9/M10 或部署；不 push、不部署。

## 93. 2026-08-06：Qlib Alpha 健康检查退出默认数据目录

- 目标：阻断 Qlib Alpha provider 健康检查的本地日历探测在 typed runtime 缺失/blocked 时回退到 `~/.qlib/qlib_data/cn_data`，避免健康检查触碰未授权旧数据源并把结果误当作当前运行能力。
- 变更：`QlibAlphaProvider._get_latest_data_date()` 先校验 typed runtime `enabled`、`must_not_use_for_decision` 和非空 `provider_uri`，不满足时直接返回不可用，不导入/初始化 Qlib；可用配置只使用 typed URI/region。
- 测试与治理：Qlib provider freshness 回归 `11 passed`，新增 blocked 配置不调用 `qlib.init` 断言；runtime contract 将该 consumer/test 登记到 Alpha Qlib enabled/provider URI 定义，变更文件 Black/Ruff 通过。
- 明确未做：未改变 Qlib 模型/推理算法、缓存前推、显式维护命令或生产 profile，未执行 PostgreSQL/观察窗口/M9/M10 或部署；不 push、不部署。

## 94. 2026-08-06：Qlib 自建维护命令禁止 runtime 缺失时回退默认目录

- 目标：阻断 `build_qlib_data` 在 Config Center typed runtime 缺失/blocked 时通过 `_DEFAULT_PROVIDER_URI` 继续检查或写入本地默认 Qlib 目录。
- 变更：命令参数解析在无显式 `--provider-uri` 时先校验 typed runtime；缺失、disabled、blocked 或 URI 为空直接抛出稳定 `runtime_config_snapshot_unavailable`（ malformed URI 仍保留输入边界错误），只有显式维护 URI 才允许继续参数校验。
- 测试与治理：Qlib build safety/management command 回归 `26 passed`；新增缺失 runtime 不调用本地 inspection 断言，runtime contract 将命令 parser consumer/test 登记到 Alpha Qlib enabled/provider URI 定义。
- 明确未做：未改变显式维护 URI 的行为、Qlib builder/provider 算法或 Tushare 数据同步，未初始化生产 profile、未执行 PostgreSQL/观察窗口/M9/M10 或部署；不 push、不部署。

## 95. 2026-08-06：Qlib Admin 模型验证退出异常时默认路径回退

- 目标：避免 Qlib Admin 模型验证在 Config Center runtime 读取异常时回退 `QLIB_SETTINGS`/默认数据目录，防止诊断页误探测旧路径。
- 变更：`QlibModelRegistryAdmin._run_validation()` 的 runtime 异常分支现在清空数据路径并发布不可用检查结果，不再从旧 settings/default URI 补值；模型验证不会因读取异常触碰本地 Qlib 目录。
- 测试与治理：新增 AST guard 断言该验证函数不包含默认 Qlib 路径或旧 settings fallback；Admin guard `1 passed`，Ruff/Black 通过，runtime contract 将 Admin consumer/test 登记到 Alpha Qlib enabled/provider URI 定义。
- 明确未做：未改动模型导入存储根目录、Qlib 训练/推理算法、显式维护入口或生产 profile，未执行 PostgreSQL/观察窗口/M9/M10 或部署；不 push、不部署。

## 96. 2026-08-06：Data Center 默认 Provider 迁移 typed Profile

- 目标：消除 `DataProviderSettingsModel.default_source` 作为运行时主读写真源的旁路，使 Provider API、配置摘要和宏观 failover adapter 统一读取 Config Center typed snapshot。
- 变更：新增 `data_center.provider.default_source` enum runtime definition；Provider 设置保存将 source、failover 开关和容差作为同一 typed patch 版本化激活，不再回写旧 singleton 的 `default_source`；payload、配置摘要和 failover adapter 优先读取 typed source，只有 profile 缺失/非法时才使用已登记的 owner compatibility 值。Data Center Admin 移除 `default_source` 旧写字段，改为 typed source 只读摘要；domain 对 source choices 做显式校验。旧 repository/model 的 `load()`、`save_default_source()` 兼容写入入口一并移除，保留只读 compatibility projection。
- 测试与治理：补充 runtime definition、source resolver、Provider 保存 patch、Admin 只读切换和未知 source fail-closed 回归；`runtime_config_contracts.json` 登记 source consumer、fallback 和测试。
- 明确未做：未删除 DataProviderSettings 兼容列、未迁移 Provider credentials/其他 Data Center 参数、未初始化生产 profile、未执行 PostgreSQL/备份恢复/观察窗口/M9/M10 或部署；不 push、不部署。

## 97. 2026-08-06：Qlib Admin 模型存储根目录切换 typed Runtime

- 目标：补齐 Qlib Admin 模型上传这一条运行时路径，禁止在缺少 Config Center typed Qlib snapshot 时从 `QLIB_SETTINGS` 或 POSIX 根目录下的 `models/qlib` 文件系统目录猜测模型存储根目录。
- 变更：`QlibModelRegistryAdmin._model_root()` 只接受 typed runtime 的非空 `model_path`，blocked/缺失/不完整配置统一抛出 `runtime_config_snapshot_unavailable`；移除 Admin 侧旧 `_qlib_settings_mapping()` 读取边界，上传入口将该阻断转成表单错误，不创建 artifact 或模型记录。
- 测试与治理：更新模型导入/验证 fixture 显式注入 typed `model_path`；新增 blocked storage guard，`runtime_config_contracts.json` 为 `alpha.qlib.model_path` 登记 Admin consumer/test。
- 明确未做：未改动 Qlib 模型算法、训练/推理数据路径、模型激活策略、生产 profile 初始化、PostgreSQL/备份恢复/观察窗口/M9/M10 或部署；不 push、不部署。

## 98. 2026-08-06：Qlib Runtime 路径解析收敛到统一 typed 边界

- 根因：此前多个 Qlib 消费者在收到“enabled”后各自对缺失 `provider_uri/model_path` 做默认补值，形成同一配置缺失在不同入口产生不同结果的双真源旁路。
- 变更：`qlib_runtime_init._require_usable_qlib_runtime()` 成为统一 provider URI 可用性门；日历探测、预测、训练和 Alpha Service 注册均不再补 `~/.qlib/qlib_data/cn_data` 或 POSIX 根目录下的 `models/qlib` 文件系统目录；Qlib Provider 构造在缺少 typed path 时读取 typed runtime，仍不完整则 fail closed；维护命令移除无效默认 URI 常量。
- 测试与治理：补充 Provider typed-path 构造阻断、任务 fixture 显式路径和运行时边界回归；`runtime_config_contracts.json` 登记 provider/model path consumer/test。Qlib runtime/T3B 定向回归 `43 passed`，mypy/Ruff 通过。
- 明确未做：未删除 `core.settings.base.QLIB_SETTINGS` 兼容配置声明（仅保留模型/迁移兼容用途待后续 M9），未初始化生产 profile、未执行 PostgreSQL/备份恢复/观察窗口/M9/M10 或部署；不 push、不部署。

## 99. 2026-08-06：Qlib 运行入口一次登记并接入 CI 防漏门

- 目标：防止只修单个调用点而遗漏任务、Admin、readiness、TUI、维护命令或旧脚本旁路。
- 变更：新增 `governance/qlib_runtime_entrypoints.json`，登记 Config Center typed source、Alpha runtime/provider/task/service、维护命令、Admin、readiness、TUI 以及 legacy compatibility/script 入口，共 31 项；新增 `scripts/check_qlib_runtime_entrypoints.py` 校验文件/符号存在，并拒绝已标记 blocked 的消费者重新出现默认 Qlib 路径、`QLIB_SETTINGS` 或 `SystemSettingsModel.get_runtime_qlib_config`。CI fast-feedback 与 consistency workflow 均执行该 guard。
- 测试与治理：入口清单 guard `31 entries validated`；readiness 回归 `30 passed`，Qlib 集成 `29 passed`，Alpha/T3B/Qlib 定向回归 `44 passed`；后续新增 Qlib 入口必须先登记 inventory 再合并。
- 变更补充：历史 `scripts/train_qlib_model.py` 已收编为只转发 `manage.py train_qlib_model` 的 compatibility wrapper，不再直接读取 SystemSettings、初始化 Qlib 或写模型注册表。
- 明确未做：legacy `scripts/prepare_qlib_training_data.py`、`core.settings.base.QLIB_SETTINGS` 和 SystemSettings Qlib compatibility getter 尚未删除，生产 profile/实际数据目录/PostgreSQL/备份恢复/观察窗口/M9/M10 仍待受控阶段；不 push、不部署。

## 100. 2026-08-06：修复长驻进程 Qlib 旧绑定与显式维护目录混用

- 根因：此前 Qlib 推理、日历和 Provider freshness 各自用一次性布尔标记缓存 `qlib.init()`；运行时 Profile 切换 provider URI/region 后，Celery/长驻进程仍可能继续读旧 provider。`init_qlib_data --provider-uri` 还会用显式目录初始化，却调用无参数日历 helper 回读 typed runtime 目录，造成同一次维护任务的来源不一致。
- 变更：新增统一 `initialize_qlib_runtime(provider_uri, region)`，以规范化 provider URI + region 作为进程级绑定键，绑定变化时重新初始化；推理、训练、日历、Provider freshness 和维护命令统一复用该边界。数据刷新后由统一 reset 清掉绑定，保证新写入数据可见。维护命令的显式 provider override 改用 path-specific calendar helper，不再混用 typed runtime 日历。
- 治理：入口 inventory 从 31 项扩展为 47 项，补齐 application facade、runtime payload、Admin training、HTTP/page、cold-start、账户兼容 Admin 和训练 runtime start/stop 脚本；guard 新增生产源码 `get_runtime_qlib_config` 读取文件覆盖扫描，漏登记直接失败，并改为完整符号标记校验。
- 测试：Qlib runtime/command/provider 定向回归 `42 passed`，维护命令边界回归 `4 passed`，完整 Qlib integration `29 passed`，Qlib/config/readiness/task 组件联合回归 `75 passed`；current-data contracts `46 surface(s)`、入口 inventory `47 entries validated`、architecture boundary/audit 0、module-cycle 0、变更生产文件 mypy regression 0、governance consistency 0 violations。全仓 mypy ceiling 仍被工作区外部 Portfolio 变更的 2 条新增错误阻断，未纳入本次提交。
- 明确未做：未删除 `core.settings.base.QLIB_SETTINGS`、SystemSettings Qlib compatibility getter、显式维护脚本及训练 runtime 兼容工作区；未初始化生产 profile、未执行 PostgreSQL/备份恢复/观察窗口/M9/M10、未 push、未部署。

## 101. 2026-08-06：真实执行 current-data manifest 全量 nodeid

- 目标：把“manifest 已登记”与“CI 真实执行”分开验收，避免只验证函数名存在却没有运行证据。
- 证据：`python scripts/run_current_data_contract_tests.py --pytest-arg=-q --pytest-arg=--reuse-db --pytest-arg=--disable-warnings` 校验并执行登记的 `268` 个 nodeid，结果 `307 passed`。
- 当前门禁：`python scripts/check_current_data_contracts.py` 保持 `46 surface(s)`；执行 runner 会先拒绝 manifest/source/test/function 缺失，再启动 pytest。
- 明确未做：该证据仍是本地 SQLite/复用测试库执行，不替代 PostgreSQL、生产覆盖/对账、观察窗口、容量/备份恢复和 M9/M10；不 push、不部署。

## 102. 2026-08-06：数据库备份保留策略收编 typed runtime 入口

- 根因：`database-daily-backup`、`backup_database_task`、`DatabaseBackupService` 和管理命令各自携带 `keep_days=14` 默认值；同一 VPS 上的全量备份因此可能长期累积，且运行时配置无法审计/切换。直接让 task_monitor infrastructure import Config Center 又会形成 `config_center → data_center → task_monitor → config_center` 模块环。
- 变更：新增 `task_monitor.retention_days` bounded `RuntimeConfigDefinition`（1–3650 天）及 runtime contract；Celery beat 不再传递 14 天常量，任务/服务省略参数时经 `core.integration.runtime_settings` bridge 读取当前 typed snapshot；缺失、失效或异常在创建目录/文件前 fail closed。CLI `--keep` 保留为显式、可审计的运维覆盖，且仍经过同一范围校验。Config Center summary bridge 增加通用 typed value 读取，避免 task_monitor 反向依赖 Config Center app。
- 测试与门禁：备份/配置定向回归 `28 passed`；runtime config coverage `49`、governance consistency `0 violations`、Celery contracts `18 tasks`、Django check 0、architecture boundary/audit 0、module-cycle 0、current-data contracts `46 surfaces`、变更生产文件 mypy regression 0、Ruff 和 diff check 通过。
- 明确未做：未在生产 profile 写入实际保留天数、未执行外部备份/下载后清理、PostgreSQL 真实恢复/容量故障注入、M9/M10 或 VPS 部署；生产 profile 应由受控初始化把本地暂存窗口设为 1 天并配套外部保留策略，不能以代码默认替代运维证据；不 push、不部署。

## 103. 2026-08-06：账户准入与 MCP 治理入口收编 account runtime projection

- 根因：用户审批、首个管理员、默认 MCP、Token 明文、协议、风险提示和备注共 7 个字段仍由 `SystemSettingsModel` 在注册、MCP 指引、账户管理、Classic Admin 和 Config Center API 之间分别读写；即使市场/Qlib 已切到 Profile，这组字段仍会形成旧 singleton 双真源。
- 变更：新增 `account.*` 7 个 typed definitions 与 all-or-nothing account projection；Config Center `build/update_system_governance` 读写同一 Profile，`_legacy_runtime_values` 只负责显式 compatibility bootstrap。账户注册、MCP 指引、用户审批/默认 MCP、账户设置上下文统一经 Config Center governance projection；Classic SystemSettings Admin 移除这 7 个可写字段并保留迁移提示。兼容期字段 criticality 设为 `normal`，缺少 account projection 时整组回退旧 singleton，避免对已有未迁移 Profile 造成跨域激活阻断。
- 测试与门禁：runtime definition/Provider 组件 `14 passed`；Config Center/账户设置 API `41 passed`；账户/MCP 页面 `19 passed`；runtime config coverage `49`、governance consistency `0 violations`、Celery contracts `18 tasks`、Django check 0、architecture boundary/audit 0、module-cycle 0、current-data contracts `46 surfaces`、变更生产文件 mypy regression 0、Ruff/diff check 通过。
- 明确未做：未删除 `SystemSettingsModel` 账户兼容列、未将备份 SMTP/Decision Runtime 状态迁入 typed definitions、未初始化生产 account profile、未执行 PostgreSQL/备份恢复/观察窗口/M9/M10 或 VPS 部署；这些字段仍需按同一 projection/外部密钥策略分组收编；不 push、不部署。

## 104. 2026-08-06：SystemSettings 兼容入口全量盘点与剩余边界

- 已收编：Qlib/Alpha/market/provider runtime → typed Profile；`task_monitor.retention_days` → typed Profile；account 准入、MCP 默认值、Token 明文、协议/风险文案和备注 → typed account projection。对应读入口分别覆盖 provider/adapter、Celery/Admin/readiness/TUI、注册/MCP/账户管理/Config Center API。
- 已确认无需另造定义：Decision Runtime 六个状态字段的唯一 owner 是 `ConfigCenterSettingsRepository.get/set_decision_runtime_state`，`core.middleware.decision_gate`、`core.health_checks` 和 readiness guard 均通过 `GetDecisionRuntimeStateUseCase` 读取；后续只需在 M9 删除兼容列与迁移，不再增加第二个 runtime value。
- 尚未收编且必须成组处理：backup delivery 的邮箱、站点、SMTP 参数、启停/周期/链接 TTL、加密密码、下载令牌和发送状态仍由 `SystemSettingsModel` 供 `send_database_backup_email_task`、账户 backup repository、下载视图、`core.encryption_readiness` 和兼容 Admin 使用。其根因是配置、密钥引用、一次性 token 状态混在同一模型；在外部 secret-ref/backup delivery policy 与状态表落地前，不能只迁移其中几个字段。
- 兼容残留：`core.settings.base.QLIB_SETTINGS`、Qlib/SystemSettings getter、旧账户/备份字段和 legacy maintenance 脚本均已有 owner/guard 记录，但仍等待 profile 初始化、生产观察、备份恢复和 M9 破坏性清理。工作区另有未跟踪 research 方向文件，未纳入本专项提交；其新增 mypy 债务会使全仓 ceiling 保持阻断。

## 105. 2026-08-06：Decision Runtime state 独立持久化

- 根因：`decision_runtime_*` 是受控 observed state，却与普通账户/运行参数共存于 `SystemSettingsModel`；虽然已有 UseCase 统一读写，物理单例仍阻止独立审计、迁移和 M9 清理。
- 变更：新增 `DecisionRuntimeStateModel` 与 `0008_decisionruntimestatemodel`；Config Center repository 首次读取优先新表、无新行时读取旧 singleton 兼容值；写入只创建/更新新 state 行，不再回写旧字段。Middleware、health check、readiness 无需改调用方，继续通过 `GetDecisionRuntimeStateUseCase` 获得同一领域状态。
- 测试与门禁：Decision Runtime component `6 passed`，middleware/health `26 passed`；`makemigrations --check` 无差异，Django check、mypy 增量、architecture/cycle/governance 门禁随本批复核。
- 明确未做：未删除旧 `SystemSettingsModel.decision_runtime_*` 列；必须等生产零旧读观察、备份/恢复和独立 release 后再执行 M9 删除；不 push、不部署。

## 106. 2026-08-06：Backup delivery 策略、密钥引用与状态入口收编

- 根因：备份接收邮箱、站点、SMTP、启停/周期/链接 TTL、密码提示、加密密码、下载令牌和发送时间曾由 `SystemSettingsModel` 同时承载；Celery 任务、下载视图、账户管理仓储、加密 readiness 和兼容 Admin 各自读取/写入不同字段，导致策略、secret 和一次性状态无法独立审计。
- 变更：新增 `backup.*` typed runtime definitions（含 `secret_ref` 约束）与 all-or-nothing backup policy projection；Config Center 的 profile bootstrap 只保存 `system_settings.backup_*_encrypted` 引用，不保存明文。新增 `BackupDeliveryStateModel`/`0009_backupdeliverystatemodel`，首次读取兼容旧令牌/发送状态，首次写入只进入新状态表。备份任务、下载链接生成/消费、账户管理和 encryption readiness 统一经 Config Center owner port；兼容 Admin 保存策略时先激活 typed profile，密钥仅继续写入过渡加密列。
- 入口清单：`apps/account/application/tasks.py::send_database_backup_email_task`、`apps/account/infrastructure/backup_service.py`、`apps/account/infrastructure/account_interface_administration_repository.py::build_backup_download_payload`、`apps/account/infrastructure/repositories.py::SystemSettingsRepository.get_settings`、`core/encryption_readiness.py`、`apps/account/interface/admin.py::SystemSettingsAdminForm` 均已登记到 `governance/runtime_config_contracts.json` 的 `backup.delivery_policy` 组。
- 测试与门禁：runtime public/definition 单测通过；`makemigrations --check`、Django check、governance consistency、SystemSettings field contract、current-data contract guard、变更文件 mypy regression 和 Ruff 通过。组件测试新增 state fallback/写新 owner 证据及下载链路迁移断言；完整组件回归仍需在干净测试库执行。
- 明确未做：外部 secret store 尚未接入，当前两个 `secret_ref` 仍明确指向旧加密列；尚未删除旧 backup policy/state 列、尚未初始化生产 profile、尚未做 PostgreSQL 真实恢复/容量故障注入/观察窗口/M9/M10，也不 push、不部署。

## 107. 2026-08-06：Provider 凭据入口一次收编

- 根因：`data_center_provider_config.api_key/api_secret` 仍是明文字段；Provider API、Classic Admin、Setup Wizard、宏观 secrets loader、Tushare/基金/Alpha 运行入口和配置摘要虽大多经过 Data Center，但仓储 `save()`、Admin ModelForm 和摘要查询仍能直接读写旧列，导致同一凭据存在多个物理入口，无法审计 secret-ref，也无法在密钥不可用时稳定阻断。
- 入口盘点：新增 `governance/data_center_provider_credential_contracts.json`，登记 Application 写入 port、Provider repository、加密/迁移 store、presence-only summary、Provider API、Admin、旧宏观 input-only form、Setup Wizard、宏观 secrets projection、Tushare client 和宏观 Tushare adapter 共 11 个边界入口；运行时下游（Data Center registry/sync/reliability/connection-test、Tushare/EastMoney/QMT/FRED adapters、Fund/Equity/Alpha 维护命令）统一从 repository/public secrets projection 获取，不允许直接 ORM 取凭据。
- 物理收编：新增 `ProviderCredentialModel`（`data_center_provider_credential`），保存稳定 `data_center.provider.<id>.credentials` ref 及 `api_key_encrypted/api_secret_encrypted`；`ProviderConfigRepository` 成为唯一运行时解密/写入边界，旧 `ProviderConfigModel` 字段改为显式迁移期兼容投影，`to_domain()` 默认不再携带旧明文。
- 写入与迁移：Provider API、Setup Wizard 和 Admin 保存均经 repository/Application port；新凭据在缺少 `AGOMTRADEPRO_ENCRYPTION_KEY` 时 fail closed，不回退明文。新增 `manage.py encrypt_provider_credentials [--dry-run]`，用于受控加密旧行并清空旧列；已有加密记录在密钥暂不可用时的元数据更新不会被误删。
- 输出与防回归：Provider 响应只发布 `has_api_key/has_api_secret` 与 `credential_ref`，配置摘要只计算 presence；新增 `scripts/check_data_center_provider_credentials.py` 并接入 fast-feedback/consistency CI，阻断未登记的 `ProviderConfigModel` ORM 入口。迁移 `0062_providercredentialmodel` 已在本地数据库应用，`manage.py check`、makemigrations check、architecture/audit、module-cycle、mypy、Ruff/Black 和入口 guard 通过；新增凭据组件回归覆盖新写入、旧行迁移、无密钥阻断、加密记录保留和 Admin port（6 passed），Provider API 三条回归通过（3 passed）。
- 明确未做：外部 Vault/云 secret store 尚未接入；旧 `ProviderConfigModel.api_key/api_secret` 列、环境变量兼容和宏观 `DataSourceSecretsDTO` 投影仍待生产密钥迁移、备份恢复和 M9 观察后删除；未执行 PostgreSQL 生产容量/恢复、生产观察窗口、M9/M10 或部署，不 push、不部署。

## 108. 2026-08-06：刷新提交态架构 inventory，隔离工作区外部改动

- 发现：Provider 凭据收编及此前宏观/账户/Qlib 批次已经改变生产源码行号和 current-surface 数量，但 `governance/data_center_architecture_inventory.json` 仍停留在旧提交，直接在主工作区重生成还会把未提交的 fixed_income 研究文件混入清单。
- 处理：从当前 `HEAD=3b5ddeea` 建立隔离 clean worktree，只扫描已提交源码并重生成 inventory；提交态计数为 `cross_app_orm_imports=51`、`current_surface_references=3347`、`data_write_task_decorators=55`、`external_http_imports_for_review=4`、`legacy_fact_references=143`、`provider_imports_outside_data_center=0`、`runtime_parameter_references=49`。主工作区仍保留外部未提交 fixed_income 文件，不纳入本批。
- 证据：clean worktree 中 `python scripts/data_center_architecture_inventory.py --write` 成功生成清单；主工作区 inventory 与提交态一致，后续 CI checkout 不会因本批代码行号变化而使用过期基线。
- 明确未做：没有修改或提交 fixed_income 外部研究代码；生产数据画像、PostgreSQL/备份恢复、观察窗口、M9/M10 和部署仍未完成。

## 109. 2026-08-06：业务侧 Data Center 入口一次收编

- 目标：把最后一条业务应用直连 Data Center infrastructure 以及一组跨 App 直接引用 `application.interface_services` 的入口全部收回稳定 Public Port，避免后续继续从具体实现层拼接 provider/use case。
- 入口盘点：在生产源码（排除 Data Center owner 与测试 fixture）中扫描 `apps.data_center.infrastructure.*` 和 `apps.data_center.application.interface_services.*`，初始命中 Alpha 价格覆盖管理命令 1 条；收编后命中为 0。宏观同步、估值同步、Equity 按需查询、Pulse 修复、Regime provider 选择和 Sentiment 新闻任务等已全部改为 `apps.data_center.application.public` 的显式 factory/selector port。
- 变更：新增 `get_alpha_price_coverage_sync_service_port()` 与 Data Center composition factory；Alpha 管理命令保留同名 compatibility façade 供既有测试/运维 patch，但实际实例化只经 Public Port。Public Port 对同步/查询/修复/新闻/治理 payload factory 做延迟桥接，避免业务 App 重新导入 Data Center implementation。
- 防回归：`scripts/data_center_architecture_inventory.py` 新增 `direct_data_center_imports_outside_data_center` 清单与计数（测试 fixture 不作为生产入口）；`tests/unit/test_data_center_architecture_inventory.py` 固定断言为 0。后续新增业务侧 Data Center internal import 会让提交态 inventory/CI 直接失配，而不是静默增加入口。
- 证据：architecture boundary/audit 0、module-cycle 0、legacy fact guard 通过；provider credential guard 11 entries validated；Alpha command contract `2 passed`；本批变更文件 Ruff/Black 通过，目标回归此前 `48 passed` 保持通过。全文件 Alpha component 在当前工作区一次运行超过 120 秒无输出，拆分命令契约已通过，需在干净测试库另行补充完整组件证据。
- 明确未做：未修改 Alpha 业务算法、历史价格数据、Provider writer、生产 PostgreSQL/VPS、部署或 push；仍保留测试 fixture 对 Data Center infrastructure 的直接使用，以及 Data Center owner 内部 implementation imports。生产 profile、真实备份恢复、容量故障注入、观察窗口、M9/M10 旧链清理仍未完成。

## 110. 2026-08-06：Backup delivery secret owner 收编

- 根因：此前 `backup.archive_password`/`backup.smtp_password` 虽已登记为 typed `secret_ref`，但 profile 只保存引用，实际密文仍在 `SystemSettingsModel.backup_*_encrypted`；snapshot 又故意隐藏 secret 值，导致新 ref 无法解析时回退旧 singleton，形成隐蔽双真源。
- 变更：Config Center 新增 `ConfigCenterSecretModel`（`config_center_secret`）和 `ConfigCenterSecretStore`，复用 `FieldEncryptionService` 加密、按 stable ref 读写、无 `AGOMTRADEPRO_ENCRYPTION_KEY` 时新写入 fail closed；新增 `0010_configcentersecretmodel`。Runtime profile patch 增加显式 `secret_ref_patch`，active snapshot 只发布非 secret 值，secret ref 由匹配的 profile/value owner 读取。
- 消费者切换：Provider/Admin 之外的 backup delivery Admin、新策略写入、backup projection、archive 加密、SMTP connection、encryption readiness 统一经 Config Center secret public port；projection 仅在内存中构造兼容模型，不把新 secret 回写 `SystemSettingsModel`。新写入不再落 legacy encrypted columns。
- 迁移：新增 `manage.py migrate_backup_delivery_secrets [--dry-run]`；只在显式执行时读取旧加密列并通过 owner port 导入，已存在新 ref 不覆盖。dry-run 在本地无可解密旧值时输出 `unavailable`，不写入。
- 治理与证据：`runtime_config_contracts.json` 将两个 secret owner 改为 `config_center`，登记新表/store、迁移命令和回归；本地 migration、Django check、mypy regression 通过；secret store/cutover 回归 `3 passed`，既有 backup/runtime/Admin 回归 `19 passed`；无密钥新写入 fail closed，数据库行不含明文。
- 防回归：新增 `governance/backup_delivery_secret_contracts.json` 与 `scripts/check_backup_delivery_secret_ownership.py`，对生产源码扫描 legacy 加密列/ setter 直写，并接入 fast-feedback/consistency CI；当前 guard 输出 `legacy writes=0`，对应自测 `1 passed`。
- 明确未做：未执行真实生产密钥迁移、外部 Vault/云 KMS 接入、VPS/备份恢复演练或旧 `SystemSettingsModel` secret 列删除；旧列仅作为显式 migration/legacy projection 兼容，需在生产 profile 初始化、verified restore 和 M9 观察窗口后清理。

## 111. 2026-08-06：Core 运维入口退出 Data Center query-service 直连

- 入口盘点：除业务 App 外，`core/integration/price_history.py`、`warmup_cache` 和 `test_data_connections` 仍直接 import `apps.data_center.application.query_services`；这类运维/桥接入口不属于 Data Center owner，却会绕过 Public Port 清单。
- 变更：Public Port 新增历史 close、诊断摘要、macro coverage boundary；Core price bridge、cache warmup 和数据连接诊断均改走 Public Port。`list_latest_macro_values` 使用延迟 query-service bridge，保留既有测试 patch/维护兼容而不让 Core 再绑定内部模块。
- 防回归：architecture inventory 的 `direct_data_center_imports_outside_data_center` 扩展为同时捕获 `infrastructure`、`interface_services`、`query_services` 和 `read_facade`；提交态 clean inventory 重新生成后该计数保持 0。
- 证据：Core price/management contract 回归 `17 passed`，Public/Core Ruff 通过，`public.py` 与 price bridge mypy regression 0；全量 management-command mypy 在当前 Windows 环境超时，未把超时当作通过。
- 明确未做：未改变历史回放语义、诊断输出格式、生产数据或调度；旧脚本/测试 fixture 和 Data Center owner 内部 query-service imports 仍是明确兼容边界。PostgreSQL/生产观察、M9/M10 仍未完成。

## 112. 2026-08-06：Legacy Data Center 脚本入口一次登记

- 目标：把 `scripts/` 下仍直接触碰 Data Center adapter/query 实现的维护、调试、部署校验和开发 smoke 入口全部显式列账，避免生产源码清零后脚本继续形成未审计旁路。
- 入口清单：新增 `governance/data_center_legacy_entrypoints.json`，登记 6 个入口：宏观刷新、VPS 校验、历史回测、历史 seed、AKShare 同步和 adapter smoke。每项记录用途、Public/Application replacement、当前 compatibility/blocked-retirement 状态及 M9 retirement gate。
- 防回归：新增 `scripts/check_data_center_legacy_entrypoints.py`，AST 扫描所有 `scripts/**/*.py` 的 Data Center infrastructure/interface/query/read-facade import，要求每个直接入口在清单中存在、replacement/status 非空且文件存在；CI fast-feedback 与 consistency workflow 均执行该 guard。当前输出 `6 registered`，未登记新增入口会 fail closed。
- 证据：legacy entrypoint guard 与单测通过；本批只做入口收编和状态登记，没有伪装成已迁移，仍保留这些脚本直到生产零旧读、真实备份/恢复及 M9 破坏性清理条件满足。
- 明确未做：未删除或改写 legacy 脚本、未切换生产任务、未执行 PostgreSQL/备份恢复/观察窗口/M9/M10 或部署，不 push；脚本迁移须在后续单独阶段按用途逐项替换并补运行证据。

## 113. 2026-08-06：提交态 Data Center architecture inventory 接入 CI

- 根因：architecture inventory 虽有 deterministic artifact 和本地回归，但两条 CI workflow 未直接执行 `data_center_architecture_inventory.py` 的 stale 检查；新增业务代码可能只在本地被发现，无法在提交阶段阻断 cross-App ORM、legacy fact、current surface 或 Data Center internal import 增长。
- 变更：fast-feedback 与 consistency workflow 均新增 deterministic inventory gate。脚本在 clean checkout 中按提交源码重建 inventory，与 `governance/data_center_architecture_inventory.json` 不一致即失败；脚本/测试 fixture 入口由 §112 的 legacy-entrypoint guard 单独覆盖。
- 证据：本地提交态 inventory artifact 保持 `direct_data_center_imports_outside_data_center=0`、`provider_imports_outside_data_center=0`；当前工作区 inventory 命令因未提交的 fixed_income/research 外部文件报告 stale，未覆盖或重生成 artifact。
- 明确未做：未声称 legacy fact 已清零、未删除旧表/adapter/task/fixture、未执行 PostgreSQL/生产观察/备份恢复/M9/M10 或部署；CI gate 只防止基线继续漂移，不能替代生产迁移证据。

## 114. 2026-08-07：ReliabilityStatus 唯一真源与阻断码治理

- 根因：全仓实际只剩 `shared/domain/reliability.py::ReliabilityStatus` 一个类型定义，但计划没有机器证据；`block_reason_code` 仍由多个 current/readiness/MCP 边界以字符串发布，新增拼写或第二个状态枚举不会被 CI 阻断。
- 变更：新增 `governance/reliability_contracts.json`，固定 7 个 reliability 状态、14 个稳定阻断码及 9 个动态生成边界；`ReliabilityContract` 对非空阻断码执行稳定格式校验。新增 `check_reliability_contract_ownership.py`，扫描提交态生产 Python，拒绝第二个 `ReliabilityStatus`、状态集合漂移、未登记 literal reason 或未登记动态边界。
- 防回归：fast-feedback 与 consistency workflow 均执行 reliability guard；本地 guard 输出 `statuses=7; reasons=14`。扫描使用 Git 提交态文件清单，避免 Windows 全仓 `rglob` 的不稳定耗时；CI checkout 会覆盖所有待合并生产文件。
- 明确未做：本批没有把所有 legacy 裸 dict 一次改写成 `ReliabilityContract`，也不声称 D0-D9 跨入口语义已全部验收；生产入口一致性、PostgreSQL、观察窗口和 M9/M10 仍需后续证据。

## 115. 2026-08-07：StorageBudget 周期容量观测闭环

- 根因：`collect_storage_capacity_profile` 只能由人工运行，管理命令还直接组装 Infrastructure observer、压力规则与持久化，生产容量策略即使已配置也没有连续观测证据。
- 变更：Config Center Application 新增 policy-bound 容量观测编排和只读 observer port，由 `apps.py` composition root 注入 Infrastructure adapter；管理命令只调用 Application Public Port。新增每小时第 10 分钟执行的容量任务，按 `success/blocked/failed` 发布统一的 `requested/succeeded/failed/stored/blocked` 计数并持久化 observation。
- 治理与证据：Celery contract 扩展为 19 个任务、5 个受管文件；StorageBudget contract 登记 Public Port、任务与 hourly schedule。容量编排/任务回归 8 passed，Beat 回归 1 passed；Celery、architecture、Django check、Ruff/Black 和 8 个生产文件增量 mypy 均通过。
- 明确未做：未在生产 PostgreSQL/VPS 启动该调度，未取得 90 GiB production profile、连续容量趋势、告警投递或故障注入证据；本批不部署、不 push。

## 116. 2026-08-07：Backup secret owner 到任务消费者断链修复

- 根因：`SystemSettingsRepository.get_settings()` 先创建 legacy settings 实例，再从另一个投影实例逐字段复制 policy/state；Config Center secret 只临时投影到第二个实例的两个密文字段，复制时被遗漏，导致旧列清空后备份到期判断和 SMTP/archive 密钥读取失效。
- 变更：仓储把同一个 legacy-shaped read instance 直接交给 Config Center backup projection，policy、state 与两项临时 secret 在同一对象完成装配；投影仍不把新密钥回写旧数据库列。
- 证据：新增组件回归先通过 Config Center 写入 archive/SMTP secret，再确认两个旧密文列为空，同时仓储消费者仍能解析密钥并判定备份到期；目标组件 2 passed，增量 mypy 0，Ruff/Black 通过。
- 明确未做：未执行生产 secret migration、真实邮件/备份/恢复或旧列删除；破坏性字段清理仍受 M9 前置条件约束。

## 117. 2026-08-07：Legacy Data Center 脚本入口退役

- 根因：§112 只把 6 个脚本列账，没有消除内部 import；其中宏观刷新会先删除旧表却把新数据写入 canonical，旧回测还会在数据异常时伪造 Recovery 并使用模拟价格，属于会产生错误证据的活动入口。
- 变更：`refresh_macro_data`、`sync_akshare_data`、`seed_historical` 统一改为 `sync_macro_data` 薄包装，正式命令增加受验证的 `--start/--end/--list`；`test_adapters.py` 删除并由现有 adapter/failover 测试替代。VPS verifier 改调用 `verify_canonical_schema --json` 与 `healthcheck --json`，不再内嵌 Data Center ORM/schema 实现。
- 回测收口：新增正式 `run_backtest` management command，通过 Backtest Application façade 持久化执行；旧 runner 只转发命令，synthetic validator 改为 fail-closed tombstone。PIT 模式必须同时提供 canonical data manifest 与 decision snapshot，禁止把模拟价格、默认 Recovery 或无证据 PIT 包装成有效回测。
- 治理与证据：legacy guard 升级为 exact/status-aware，拒绝漏登记、陈旧条目、错误生命周期和 wrapper 再导入 Data Center internal；当前为 `0 direct, 4 compatibility wrappers`。目标回归 44 passed，3 个生产文件增量 mypy 0，Ruff/Black、Django check 与 diff-check 通过。
- 明确未做：4 个薄 wrapper 为命令兼容入口，尚未删除文件名；生产 backtest 数据覆盖、PostgreSQL/VPS 和 M9 破坏性清理仍未执行。

## 118. 2026-08-07：Data Center 全调用入口一次枚举

- 目标：把此前分散在 architecture/current-data/Celery/TUI/SDK/MCP 清单中的入口合成一个确定性视图，后续每类问题先定位 owner、状态和替代口，再决定迁移或退役，不再依赖人工全文搜索。
- 变更：新增 `data_center_entrypoint_inventory.py` 与 `governance/data_center_entrypoints.json`，静态枚举 REST、SDK、MCP、Terminal/TUI、Capability、management command、Celery task、Beat schedule、script、Application Public Port、compatibility façade 和 current-data surface；状态严格区分 `active_public / compatibility / adjacent_operational / candidate-review`，发现入口不会自动升级为已治理。
- 首次快照：共 547 个入口；`active_public=350`、`compatibility=118`、`adjacent_operational=66`、`candidate-review=13`。分类为 Beat 57、Capability 25、Celery 53、compatibility façade 93、current-data 46、management command 25、MCP 29、Public Port 91、REST 54、script 6、SDK 45、Terminal/TUI 23。
- 防回归与证据：fast-feedback 和 consistency CI 均执行 stale guard；默认重建校验通过，清单单测 3 passed，Ruff/Black 与 workflow YAML 解析通过。非 Data Center owner 的业务任务/调度明确标为 `adjacent_operational`，不再冒充迁移债务；13 个真实待审入口为 Macro 7 个任务、Realtime 1 个任务、对应 4 个 Beat 调度及 1 个未发布 TUI action。已登记 task 的短 decorator 名、治理/测量脚本不会再被误报为候选。不以本次枚举冒充消费者全切换。
- 首次合并态 architecture inventory 在干净 detached worktree 重建：`direct_data_center_imports_outside_data_center=0`、`provider_imports_outside_data_center=0`、`cross_app_orm_imports=51`、`legacy_fact_references=143`、`current_surface_references=3365`、`data_write_task_decorators=56`；当时主工作区未跟踪的 Research 开发文件未混入基线。
- 明确未做：该清单是静态调用面证据，不执行 Django、数据库或外网；它不能替代 D0-D9 跨入口字段一致性、PostgreSQL 性能、生产观察窗口、备份恢复和 M9/M10 验收。

## 119. 2026-08-07：Data Center Public Port 类型契约拆分

- 根因：合并态治理检查发现 `apps/data_center/application/public.py` 达到 1242 个非空行，超过 1200 行门禁；文件同时承载稳定调用函数和大型宏观投影 Protocol，是结构膨胀而非应登记的新基线。
- 变更：将 Alpha 价格覆盖与 Macro projection 的纯 Application Protocol 移到 `public_protocols.py`，`public.py` 继续原名导入/导出，既有调用路径和 Public Port API 不变。
- 证据：`public.py` 降至 1118 个非空行，新类型文件 133 行；目标回归 16 passed，两个生产文件增量 mypy 0，Ruff/Black 通过。未提高 `allowed_large_python_files` 或其他债务基线。
- 并行工作区说明：治理检查仍报告 Fixed Income/Research 的 3 个大文件候选，它们属于其他开发提交/未跟踪文件，本批未修改、未登记豁免，也未误提交。

## 120. 2026-08-07：合并态大文件治理债务清零

- 根因：并行提交把 `curve_relative_value.py`、`state_model_qualification.py` 和 `r4_promotion_repository.py` 分别推到 2092、1607、1242 个非空行，导致一致性门禁失败；这些不是可接受的“既有债务”，也不应通过抬高 baseline 放行。
- 变更：Fixed Income curve-relative-value 按 contracts/results/evaluator 拆为 804/631/689 行，原路径保留 68 行兼容导出；State Model 按 contracts/evaluation 拆为 892/746 行，原路径保留 47 行 façade；R4 repository 抽出 6 个 ORM value projection helper 到 172 行模块，主仓储降至 1100 行。
- 行为保持：Fixed Income 34 个类/函数 AST 定义对比 `missing=0/extra=0/changed=0`；State Model 原 `__all__` 与导入路径保持；R4 旧私有 helper 路径继续指向新实现。
- 证据：Fixed Income 20 passed、State Model 34 passed、R4 repository component 13 passed；9 个生产文件增量 mypy 0，Ruff/Black 通过；`check_governance_consistency.py` 最终 `large_python_files=0`、总 violations=0。未增加任何大文件豁免或债务基线。
- 并行边界：未跟踪的 R5 relative-value promotion 开发文件未纳入本批提交或测试结论。

## 121. 2026-08-07：全入口候选收编完成

- 根因：首次枚举的 13 个候选不是同一类遗漏。Macro 7 个任务和 Realtime 1 个任务缺 Celery 业务结果契约，对应 4 个 Beat 调度因此也无法证明受治理；PIT manifest 详情动作虽在 generated graph 中，却因 promotion 缺 Data Center 参数化动作路由而被 published graph 丢弃，并把字符串 `manifest_id` 错判成整数。
- 任务收编：8 个任务在 Celery 边界完成参数校验，统一发布 `success/outcome/requested/succeeded/failed/stored/blocked/count_unit/error`，明确 `success/partial/noop/blocked/failed`，零写入不再静默成功；Realtime 额外保留源报价时间并在任务边界拒绝缺失、未来或超过 300 秒的观测。Celery 治理扩展为 27 个任务、7 个源文件，任务和对应 Beat 均由精确测试证据反向登记。
- TUI 收编：compiler 增加 `param.api.get.api.data-center* -> api-library.data-center` 晋级规则，并为 PIT manifest 详情声明 `text/string` path field；generated/published 工件由 compiler 全量重建，目标动作成为 `approved:parameterized-promoted`。同一次确定性重建还发现并发布已有的 Data Center provider status 安全读入口，因此总数净增 1，不是人工追加 JSON。
- 最终快照：共 548 个入口；`active_public=356`、`compatibility=126`、`adjacent_operational=66`、`candidate-review=0`。分类为 Beat 57、Capability 25、Celery 53、compatibility façade 93、current-data 46、management command 25、MCP 29、Public Port 91、REST 54、script 6、SDK 45、Terminal/TUI 24。
- 证据：Macro 37 passed、Realtime 11 passed、TUI compiler 48 passed、入口清单 3 passed；Celery contract guard 为 27 tasks/7 files，current-data 46 surfaces、Reliability owner、mypy、Ruff/Black 均通过。最终 architecture inventory 为 Data Center 外部直连 0、Provider 外部直连 0、跨 App ORM 51、旧事实引用 143、current-surface 引用 3372、数据写任务 decorator 56。候选清零表示所有静态入口已有明确治理状态，不冒充 D0-D9 跨入口语义一致性、PostgreSQL 性能或生产观察窗口已经完成。

## 122. 2026-08-07：备份入口单一 owner 与可恢复格式收编

- 根因：每日全量备份同时由 Django Beat 和部署脚本安装的 VPS cron 持有，应用内 PostgreSQL 路径仍使用 plain SQL/gzip；这会形成重复全备、14 天累积、无峰值容量预检、无 `pg_restore --list` 和无稳定 SHA 证据。
- 单一 owner：每日数据库备份只由 Django Beat 的 `backup_database_task` 负责；远端部署脚本不再安装第二个 cron，并会移除历史 `vps-backup.sh` cron。`vps-backup.sh` 只保留为显式部署前恢复点，默认本地暂存 1 天，且新备份验证成功后只保留一份完整数据库工件。
- 边界澄清：账户侧每日 `send_database_backup_email_task` 只发送按策略到期的加密逻辑数据导出链接，真正导出发生在用户下载时；PostgreSQL 路径是 Django JSON，不具备灾备恢复语义。保留兼容 task path，但用户文案明确“数据携带、不能替代 custom-format 灾备”，不把它计作第二个恢复备份 owner。
- 可恢复性：应用 PostgreSQL 备份统一为 custom format，写入 `.partial`、校验非空、执行 `pg_restore --list` 后原子替换 `postgres-current.dump`；结果发布 format/size/SHA-256，并在成功替换后清理旧 plain SQL 与旧 timestamp dump。SQLite 继续使用 online backup、integrity check 和原子 gzip。
- 容量与任务契约：所有生成数据库工件的入口（Beat/Celery 与 `manage.py backup_database`）先执行同一个 Application capacity policy，再按“当前 filesystem used + database size”评估备份峰值；策略/证据缺失或 projected pressure 为 critical/emergency 时阻断，不创建工件。跨 App 调用经 `core.integration.config_center_runtime` composition bridge 注入 owner，避免 `config_center → data_center → task_monitor → config_center` 依赖环。备份与验证任务移入独立受管源文件，统一发布 `outcome/success/requested/succeeded/failed/stored/reason`；Celery contract 扩展为 29 tasks/8 files，PostgreSQL nightly job也执行完整 Celery manifest runner。
- 证据：备份任务/SQLite/PostgreSQL command/部署 owner 定向回归 15 passed，capacity/backup/management command 回归 10 passed，bridge/backup 回归 12 passed，Celery manifest 98 nodeids 实际执行为 107 passed；Celery contract guard、Django check、architecture boundary 0、module cycle 0、8 个生产文件增量 mypy 和 Ruff 通过。
- 明确未做：本批未连接生产、未执行真实 PostgreSQL dump→隔离 restore/RTO、未验证外部下载回执后删除，也未执行 M9/M10 或部署；这些仍需生产授权和恢复演练证据。

## 123. 2026-08-07：旧事实 inventory 去字符串误报并按语义归零

- 根因：architecture inventory 原先按行搜索 `MacroIndicator`、`CapitalFlowModel` 等裸字符串，把宏观 Domain dataclass、账户资本流水模型、类型标注与测试兼容名称都算作 legacy fact access，产生 143 条伪债务；该数字与模块限定的 legacy access guard 不一致。
- 变更：inventory 改为读取 `data_center_legacy_access_contracts.json`，按具体 legacy module、导入 symbol、alias、相对导入和模块属性引用解析；保留 owner model/admin/migration 的显式 allowed path，不再以类名同名判定旧链访问。新增回归分别证明 Domain `MacroIndicator`/本地 `CapitalFlowModel` 不误报，absolute/relative legacy ORM import 必须命中。
- 提交态清单：在提交 `a66ded94` 的隔离 clean worktree 中重建并复核，结果为 `legacy_fact_references=0`、Data Center internal 外部直连 0、Provider 外部直连 0、cross-App ORM 51、current-surface 3374、data task decorators 56；总入口仍为 548、candidate-review=0。主工作区并行 R5 文件没有混入治理基线。
- 语义边界：这里的 0 表示“当前生产源码没有未允许的 legacy fact ORM import/reference”，不表示旧表、兼容 façade、128 个 compatibility 入口已物理删除；M9 仍必须等待真实备份恢复、生产零访问证据与明确授权。

## 124. 2026-08-07：D4/D5 全消费者切读状态收口

- 根因：生产源码已无 `FinancialDataModel`/`ValuationModel` 业务引用，Equity context/API、Alpha、Factor、Valuation、TUI 与 MCP/AI capability 均通过 canonical repository、published Public Port 或 Equity canonical API 间接消费；但 ownership manifest 仍标记 `dual_read_legacy_pending_cutover`，旧两张表又继续出现在只读 Admin，形成“运行已切、控制面仍宣称双读”的状态漂移。
- 切读收口：D4 `equity.financial.fact` 与 D5 `equity.valuation.fact` 更新为 `canonical_read_with_legacy_audit`；旧财务/估值模型退出 Admin，不再提供人工读取入口。模型定义、历史迁移和测试 fixture 继续保留到 M9，以支持恢复与最终删表验证，不作为生产消费者。
- Lineage 修复：Equity compatibility DTO 写 canonical fact 时不再把 source 硬编码为 `equity_legacy_repo`。真实 provider 原样保留；空、unknown 或 legacy 标签统一归属 `equity_application_port`，原标签写入 `extra.upstream_source`；naive fetched time 不进入 canonical fact，改用 aware 采集时间，并保留合法 source observation time。
- 证据：新增 4 条 cutover 回归，覆盖 Admin 退役、D4/D5 canonical lineage、aware time 和 ownership 状态；两条 canonical context 关键回归证明 D4/D5 读取 canonical facts 且不会回落旧表。legacy fact access guard 继续要求生产业务访问为 0；基于当前提交主线加本批投影的隔离 inventory 为 548 entries/candidate 0、legacy fact 0、current surface 3378。
- 明确未做：未生成破坏性删表 migration、未清空旧表、未执行生产 PostgreSQL 备份恢复或 M9；本批只完成消费者与人工入口退役，不部署、不 push。

## 125. 2026-08-07：D0-D9 旧事实人工入口一次退役

- 根因：语义扫描已证明业务源码不再读取 D0/D1/D2/D3/D4/D5/D6 旧 ORM，D7 新闻、D8 资金流和 D9 发布目录本身只有 canonical fact；但 Fund NAV、Sector membership、Stock master/price 旧模型仍注册在 Admin，D2/D3/D6-D8 ownership 状态仍停留在“query port available”，控制面没有表达全消费者已经切读。
- Admin 退役：`StockInfoModel`、`StockDailyModel`、`FinancialDataModel`、`ValuationModel`、`FundNetValueModel`、`SectorConstituentModel` 全部退出 Admin。legacy access contract 同步移除 equity/fund/sector Admin 白名单，后续重新导入会被 guard 直接阻断。旧模型定义、迁移和测试 fixture 仍保留到 M9。
- 状态收口：D0 asset master、D1 price bar、D2 fund NAV、D3 macro、D4 financial、D5 valuation、D6 membership 统一为 `canonical_read_with_legacy_audit`；D1 quote 继续使用 reliability-guard 状态；没有旧事实投影的 D7 news、D8 capital flow 与 D9 publisher 明确为 `canonical_only`。
- 证据：Admin 回归枚举六个 retained legacy model 并断言均未注册；ownership 回归枚举所有 D0-D9 状态；legacy fact access guard 继续为 0。该状态只宣告消费者与人工入口切换完成，不等于生产旧表已经删除。
- 明确未做：不生成 destructive migration、不清空生产旧表、不执行 VPS 部署；M9 仍由真实 custom backup→restore、零访问证据和明确生产授权控制。

## 126. 2026-08-07：消费者、配置、调度与脚本入口全量收编

- 清单根因：§118 的 548 条清单覆盖外部调用面和 Public Port 定义，但没有冻结谁在调用 Public Port，也没有纳入 Django Admin、Runtime Config key、`SystemSettingsModel` 兼容引用、数据库 Beat writer 和非 Python 编排入口；因此不能作为“全量消费者已收编”的机器证据。
- 清单扩展：`data_center_entrypoint_inventory.py` 增加 canonical Application consumer、Admin、Runtime Config、SystemSettings compatibility、scheduler writer 与 script/workflow orchestration 六类扫描；management command 改为仓库级发现，Admin 改为全仓语义扫描，旧模型重新注册会进入 `candidate-review`。最终清单为 793 条：158 个 consumer import、45 个 runtime key、14 个 Admin、8 个数据库调度写入口、8 个编排入口，`candidate-review=0`。
- 旧脚本退役：删除 7 个直接查询旧 `macro_indicator` 的 debug 脚本、3 个已失效的 USD 迁移 Python 脚本和 1 个直接写旧表的 SQL；`setup_celery_beat.py` 改为 `init_scheduler_defaults` 薄 wrapper，不再直接写 `PeriodicTask` 或引用不存在的 task。legacy fact guard 扩展到 `scripts/sdk`、re-export、relative/module alias、dynamic model/import 和 Python/SQL/Shell/PowerShell/Batch/YAML raw SQL，旧表脚本以后无法绕过 CI。
- 破坏性入口收口：legacy `cleanup_expired_raw_payloads_task(dry_run=False)` 改为阻断；`enforce_retention_task` 在可信 archive reader + staging restore gate 落地前拒绝真实删除；caller-supplied checksum/count/size 不再能把 archive manifest 标记 verified；quote snapshot 全量 purge 命令保留名称但永久 fail-closed，并删除其 Application/Repository `delete_all` 旁路。
- Config Center 入口修复：注销 `SystemSettingsModel` Django Admin，避免 `ModelForm.save(commit=False)` 绕过 typed profile；备份邮件读取改用 `get_settings_for_read()`，不再因一次读创建旧 singleton。删除 3 个没有 definition/consumer 的幽灵 runtime key，`task_monitor.retention_days` 标记为 Config Center-only fail-closed，storage 四项更正为独立 `StorageBudgetPolicyModel` 真源并登记实际消费者。
- 验证：扩展后的入口/legacy/retention/purge/Admin 定向包 39 passed；legacy access guard 和 Celery task contract 均通过。该批只关闭漏网入口和危险删除旁路，不把 archive export/reader/staging restore、真实 PostgreSQL 恢复、生产观察窗口、M9/M10 或部署冒充为已完成。

## 127. 2026-08-07：二级命令边与调度 target 结构化收编

- 补漏根因：入口清单虽已列出 management command、Celery task、Beat 和数据库调度 writer，但未显式展开 `call_command()` 二级调用边；未声明 `name=` 的 Celery task 又只记录短函数名，Beat target 只存在于说明文本，机器无法完成 target 引用完整性核对。
- 收编变更：新增 `management_command_edge` 类别，静态展开 `init_scheduler_defaults` 的 8 个受管 setup command，并枚举其他 direct/dynamic `call_command()`；Celery 默认名统一投影为完整 module dotted path；Beat、Celery task 与数据库 scheduler writer 均新增结构化 `target`。scheduler writer 识别范围扩展到所有 `apps.*.application.*` task path，消除 valuation `tasks_valuation_sync` 被误记为 dynamic 的问题。
- 最终清单：857 个入口，其中二级命令边 60、scheduler writer target 12；`active_public=561`、`adjacent_operational=116`、`compatibility=180`、`candidate-review=0`。初始化兼容常量、`_run_command()` wrapper 与声明式 `init_steps[].command` 均已静态展开，不留 `dynamic-command` 占位。新增测试精确断言 8 个 scheduler setup edge、Celery 默认完整名、Retention Beat target 和 Equity valuation 三个数据库调度记录所引用的两个 canonical task。
- 边界：该清单证明静态入口和二级 dispatch 已有归属与机器可读 target，不代表外部 archive restore、生产 PostgreSQL 运行证据、M9/M10 或部署完成；真实删除继续 fail closed。

## 128. 2026-08-07：可信冷归档闭环落地并保持删除 fail-closed

- 根因：旧 `verify_archive_manifest_task` 接受调用方提供的 checksum/count/size，数据库中任一 dataset 级 verified manifest 即可能被当作删除授权；RawPayload 又可被 upsert 改写，无法证明待删记录与已归档字节完全相同。
- 可信链：新增加密 gzip JSONL 冷存储适配器，逐记录 Fernet 认证加密，写入 `.partial`、文件 fsync、原子 replace，POSIX 再执行目录 fsync；独立 inspect 与 staging restore 都完整重读、解密、重建 RawPayload，并验证 checksum、contract/schema、成员集合、完整记录摘要、覆盖区间、对象数和字节数。路径逃逸、symlink parent、错误密钥、截断工件、超大 header/record 均 fail closed。
- 精确证据：新增 immutable `ArchiveMemberModel` 与 append-only `ArchiveRestoreAuditModel`；manifest 持久化 format/encryption/key version、coverage、retention、restore outcome。旧 caller-verified manifest 在 `0063` 数据迁移中降级为 exported/not-tested，不伪造恢复证据。RawPayload 写入改为 create-or-identical，删除改为 full-record digest + deadline 的事务 CAS。
- 任务契约：新增 export、store-backed verify、带稳定 `operation_id` 的 staging restore 三个任务；重复成功校验不刷新 verified_at，失败 restore 的同 operation 重试不重复读坏工件，新 operation 可在修复后重试。Celery contract 为 31 tasks/9 files；原先把永久阻断测试登记成 `all_success` 的伪证据已删除。
- 删除边界：只有未过期 archive、精确成员、当前冷字节复核、最近完整 restore success 且 restore 不早于 verify 时才形成单条 coverage。`enforce_retention_task` 在 RetentionPlanMember/plan_run_id 精确计划证据落地前继续以 `retention_plan_member_gate_not_implemented` 阻断，当前批次不会执行真实删除。
- 验证：归档/Retention/Raw Landing/schema gate 定向包 63 passed；入口/任务专项另有 29 passed 与 ORM 精确覆盖 2 passed；15 个生产文件增量 mypy 0，Celery guard 与 `makemigrations --check` 通过。部署 schema gate 已要求 archive member、restore audit 和 `0063` marker。
- 未完成：未配置生产 archive mount/key、未执行真实 PostgreSQL/VPS restore/RTO、未加入正式归档/恢复 Beat，也未完成 RetentionPlanMember、M9/M10 或部署。

## 129. 2026-08-07：全入口从平面清单升级为可追踪调用图

- 二次审计发现：§127 的 857 条清单仍漏掉 67 个 typed Celery task、任务 dispatch、`PeriodicTask` AnnAssign/别名、同 task 多 schedule、DRF action、MCP core registrar、SDK client 暴露、动态 loader 和 TUI screen→action 关系；legacy MCP 默认关闭却被误标 active。
- 扫描器升级：支持 `typed_shared_task/_typed_shared_task/_celery_task` 及 alias，追踪 `.delay/.apply_async/.s/.si/signature/send_task`；解析 `call_command/execute_from_command_line` 常量、动态 import registry、Admin 多模型/custom site、数据库 Beat wrapper/default builder；重复 ID 在校验前不再被字典去重静默吞掉。
- 跨入口图：REST 记录 callback/DRF typed action，SDK 记录 HTTP method/route 和 `AgomTradeProClient.data_center` 暴露，MCP 区分默认启用 core tools 与默认关闭 legacy tools，并验证 Data Center capability shard 确实存在于 `OWNER_MANIFEST_MODULES` 且 handler 已接线；TUI 校验 generated/published endpoint、method、intent、schema，并记录 screen→action→endpoint。
- 最终机器快照：以两个精确提交组成的干净 detached worktree 重建为 989 entries，`active_public=561`、`adjacent_operational=217`、`compatibility=211`、`candidate-review=0`。其中 typed/普通 Celery task 122、dispatch edge 18、dynamic import edge 8、management command/edge 27/65、scheduler writer 16、REST 66、SDK 46、MCP 40、TUI 28；Decision Quote 同一 task 的四个独立 schedule 均被保留。共享工作区并行的 Market Structure/Research 未提交文件未混入基线。
- 验证：入口清单完整专项 12 passed；重复 ID、unresolved dynamic import、typed decorator、管理命令包装、三 schedule 同 target、Admin 多模型、HTTP/SDK/MCP/TUI/runtime target 均有合成或现仓断言。`candidate-review=0` 表示所有静态发现入口已有明确状态和下一跳，不表示 212 个 compatibility seam 已物理删除，也不替代生产运行证据。

## 130. 2026-08-07：Retention 精确计划成员与两阶段执行闭环

- 根因：旧 `plan_retention_task` 只记录汇总 `RetentionRun`，执行端若开放会重新查询一次候选集；dry-run 与真实删除之间的 payload、policy、hold、archive 状态无法绑定，因而只能永久以 `retention_plan_member_gate_not_implemented` 阻断。
- 精确计划：新增 immutable `RetentionPlan` / `RetentionPlanMember` Domain 契约与 `0064_retention_exact_plan_members`。计划按稳定 ordinal 冻结 payload ID/hash、完整 record digest、schema、源时间、row deadline、size、决策和唯一 archive ID，并用 canonical JSON SHA-256 覆盖全部不可变字段。计划头与成员在同一事务创建，`operation_id` 重试直接返回原快照，不重新扫描。
- 单次认领：`enforce_retention_task` 不再接受 dataset/limit 重新塑形，只接受 `plan_run_id + operation_id + confirm=true`；Repository 对计划行 `select_for_update`，同一 operation 终态重放不二次删除，不同 operation 无法并发认领。到期、policy ID/version 漂移、snapshot digest 漂移均整批 fail closed。
- 再验证与删除：执行只遍历计划时 `eligible` 的成员，计划时 held/blocked 后续即使条件改善也不会扩大；每条在删除前重新检查 dataset/plan/raw/archive 四级 hold、固定 archive ID 的数据库证据与当前冷字节、当前 RawPayload 完整 digest，再由 full-record CAS 删除。单项 drift 或 CAS 冲突记录 blocked，技术异常记录 failed，实际删除字节和计数单独持久化。
- 审计与 schema：计划 member 对 archive 使用 `PROTECT`，RawPayload 删除后仍保留证据；旧 `RetentionRunRepository` 从可覆盖 `update_or_create` 收紧为 create-or-identical。部署 schema gate 增加两张计划表和 `0064` marker。Celery manifest 为 plan/enforce 补齐 invalid、all-success、partial、zero-output/blocked、complete-failure 的精确测试节点。
- 本地证据：Domain/任务专项 37 passed，ORM 控制面 8 passed；Celery contract 31 tasks/9 files，10 个生产文件增量 mypy 0，Ruff 与 `makemigrations --check` 通过。真实删除没有加入 Beat，本批未连接生产、未部署。
- 仍需外部证据：正式启用定时 enforce 前，必须在 PostgreSQL job 验证两个 worker 并发 claim、policy/hold 与 enforce 竞争、事务异常恢复，并完成真实 archive mount/key 的 export→inspect→restore→plan→enforce 演练；这些不由 SQLite 单元证据替代。

## 131. 2026-08-07：PostgreSQL 原子删除、迁移与隔离恢复 CI 取证

- 再审计根因：首版 plan claim 能阻止两个 enforce worker 同时消费，却仍把 RawPayload 删除和 member evidence 写入放在两个事务；evidence 写失败会留下“数据已删、成员仍 pending”。普通 `select_for_update` 也锁不住当前不存在的 hold 行，无法阻止检查后并发 INSERT hold。
- 原子 UoW：新增统一 transaction advisory lock 协议，policy activate、hold create/release 与 member consume 对 dataset/plan/raw/archive 资源按稳定顺序取相同锁。Infrastructure UoW 在一个事务内锁 plan/member/raw/policy/archive，重查 active policy、四级 hold、固定 archive DB evidence 与完整 record digest，随后同时 CAS 删除 raw 并写 `member=deleted`；任一步异常全部回滚。Application 不再拼接跨事务删除。
- PostgreSQL 专项：新增 PG-only 双 worker claim、同 operation 并发建 plan、hold 先持锁再 enforce 三条真实并发测试；新增 `0063 -> 0064 -> reverse -> reapply` migration test，验证 plan/member unique、archive `PROTECT` 和 reverse/reapply。SQLite 明确 skip advisory-lock 测试，不冒充 PG 证据。
- 恢复取证：nightly PostgreSQL 16 通过应用唯一 owner 生成 custom dump；新 verifier 先 `pg_restore --list`，再恢复到受控随机前缀的隔离库。source/restore 逐表按稳定 JSON 行流式 SHA-256，比对行数与内容；schema SHA-256 覆盖 columns/type/null/default、constraints、indexes、sequence 定义和 last value，并再次检查 canonical table/migration marker。证据记录 dump SHA/size/TOC、restore 秒数、验证秒数、总时长和清理结果，失败也原子落盘；密码不进入 argv。
- CI 可下载证据：critical/current-data/Celery/retention/migration/concurrency 各自产出 JUnit，另保存 PostgreSQL/client version、migration plan 和 restore evidence JSON；artifact 不上传数据库 dump。入口图把 verifier 作为 active governance script 收编，更新为 990 entries、`active_public=562`、`candidate-review=0`。
- 本地证据：Retention task 28 passed、verifier unit 7 passed、ORM/UoW 10 passed、migration forward/reverse 1 passed；PG concurrency 3 条在 SQLite 按设计 skip。Ruff、增量 mypy、YAML 解析通过。
- 外部边界：以上仅完成可执行 CI 与证据产出定义；在 GitHub PostgreSQL job 实际绿灯并下载 artifact 前，不宣称 PG concurrency/restore DoD 已完成。它也不替代 VPS 生产规模 custom backup 下载、隔离恢复 RTO、host-key pinning、真实 archive key/mount 演练和 M9/M10。

## 132. 2026-08-07：运维、证据与人机入口全量收编

- 补漏根因：§129 的 990 项调用图只覆盖扫描器已经认识的 Python/HTTP/Celery/TUI 面；`pg_dump/pg_restore/dropdb/createdb`、通用 `manage.py migrate/backup_database`、Shell/PowerShell dispatch、migration test、workflow step、runbook 与 Agent Skill 都在盲区，因此原 `candidate-review=0` 不能证明运维入口完整。
- 扫描扩展：入口图新增 `operational_script / operational_dispatch_edge / workflow_step / test_evidence / migration_evidence / runbook / agent_skill` 七类；静态识别 PostgreSQL 备份恢复、Django migrate/backup/dumpdata/loaddata、`MigrationExecutor`、Windows ScheduledTask、Retention/Archive 任务及 StorageBudget 初始化、观测和容量门。任何新命中默认 `candidate-review`，不会按关键词自动批准。
- 生命周期真源：新增 `governance/data_center_operational_entrypoints.json`，显式登记 owner、状态和证据；增加 `retired_blocked`，用于已经退出批准生产路径但为审计/迁移仍保留文件的危险旧入口。该状态是治理级阻断和 dispatch 禁用依据，不冒充文件已经物理删除；最终 tombstone/删文件仍应独立提交。
- 分类纠偏：永久阻断真实删除的 `cleanup_expired_raw_payloads_task` 改记 compatibility，replacement 为 plan/enforce 两阶段任务；Task Monitor 的 `backup_database_task/verify_backup_task` 改记 adjacent owner，不再错误伪装成 Data Center 迁移缝。旧 Windows 自动备份、SQLite restore、动态 settings 迁移和旧 rollback 等 34 项被收入口账并标 `retired_blocked`。
- 最终快照：共 1182 项，`active_public=617`、`adjacent_operational=281`、`compatibility=250`、`retired_blocked=34`、`candidate-review=0`；其中新增运维/证据面 192 项。入口专项 17 passed，扩展 StorageBudget 迁移/测试发现后专项合计 26 passed，stale-check、Ruff 与 diff-check 通过。

## 133. 2026-08-07：真实 PostgreSQL 反向发现与 CI 时限校准

- 实测环境：本地一次性 PostgreSQL 16 空库执行全迁移图，首次迁移在工具十分钟外层超时后从已提交 migration 位置幂等续跑并完成；总耗时约 16 分钟。`0063 -> 0065 -> 0063 -> 0065` reverse/reapply 在真实 PostgreSQL 通过 1 项，约 537 秒；`serialized_rollback` 会触发无必要的全库反序列化，已移除。
- 并发证据：双 worker 不同 operation 抢单 plan、相同 operation 并发建 plan 重放同一快照、Hold 先锁再 consume 三个场景合并为一次事务数据库生命周期；线程连接显式关闭，测试清理范围限制为 Data Center App，真实 PG16 为 1 passed/约 146 秒。SQLite 仍按设计 skip，不冒充并发证据。
- 摘要字段根因：真实 PG 暴露 `raw_payload_record_digest()` 的 `sha256:` 前缀摘要长度为 71，而 0064 把 member hash/digest 列设为 64；SQLite 未执行 varchar 长度约束而漏报。新增 0065 把两列扩到 128，canonical schema marker、迁移测试和 restore fixture 同步跟进。
- StorageBudget 根因：策略声称按 `(policy_key, version)` 版本化，但模型同时把 `policy_key` 单列 unique，v2 永远无法写入。Config Center 0011 移除单列唯一，保留 key/version 唯一并新增全局单 active 条件唯一；v1 保存、v2 非激活保存、v2 activate/旧版本退役在 SQLite repository 回归和真实 PG migration 均通过。
- CI 校准：critical PostgreSQL job 从 35 分钟调为 90 分钟，migration test 单项 timeout 从 600 调为 900 秒；并发证据使用已迁移测试库、300 秒 teardown 预算。nightly StorageBudget 配置容量从错误的 1 GiB 改为 100 GiB，使 guard 继续以 runner 实际磁盘为较小硬上限，不再因为配置上限本身必然进入 emergency。隔离 restore 改用 custom-format 四 worker，并继续 `--exit-on-error / --no-owner / --no-acl`。
- 本地限制：主机 D 盘容量门为 healthy，但 Windows 宿主未安装 `pg_dump/pg_restore`，应用备份命令按设计 fail closed；因此本地 custom dump 由一次性 PostgreSQL client 容器生成，不能冒充“应用 owner 端到端已通过”。应用 owner 路径仍以 GitHub PostgreSQL artifact 为最终 CI 证据。

## 134. 2026-08-07：恢复快照假阴性根因与可诊断证据

- 真实失败：同一份 PostgreSQL custom dump 首次隔离恢复后返回 `postgres_restore_snapshot_mismatch`，但旧 evidence 只保存通用错误和耗时，未保存 source/restored 快照及差异；这类证据不能区分数据损坏、模式漂移或校验器假阴性，不能作为 M9 删除授权。
- 根因定位：隔离库与源库的 397 张表集合及精确行数、Data Center migration、326 个 sequence 的 `last_value + is_called` 全部一致；失败只来自 schema fingerprint。旧指纹错误纳入 `ordinal_position`，把源库历史 DROP COLUMN 留下的物理 attnum gap 当成 schema 差异；另外 PostgreSQL 将 dump 中的 CHECK expression 重新 parse 后，会把 `varchar[] -> text[]` 等价 cast 分布到数组元素，`pg_get_constraintdef()` 文本不同但约束语义相同。
- 修复：列指纹按稳定列名比较 type/null/default/identity/generated/collation，不比较无业务语义的物理 ordinal；CHECK constraint 对 PostgreSQL dump/reparse 的等价 varchar/text array cast 做稳定归一，同时仍比较表、约束名/类型与完整约束定义。schema 定义与 sequence 状态拆分，sequence 额外记录 `is_called`，避免“相同 last_value、下一次 nextval 不同”漏报。
- 快照一致性：source snapshot 改为单个 `REPEATABLE READ READ ONLY` transaction，并固定 UTC、DateStyle、IntervalStyle 与 search_path，避免逐表 READ COMMITTED 混合快照和会话文本差异。sequence 状态不是 MVCC，正式生产演练仍须停止 writer 或将 `pg_dump --snapshot` 与 source evidence 绑定；本轮本地静态源库证据不能替代该生产门禁。
- 失败可诊断：verifier 在比较前即持久化 source/restored snapshot、逐表 count/hash diff、migration 集合差异、schema hash 差异与 sequence 增删改；失败 evidence 不再只给通用错误。sequence 读取由 326 次 round trip 合并为一次查询，隔离恢复使用 4 worker，本地 restore 阶段由约 2442 秒降至约 468 秒。
- 入口治理收口：旧入口精确校验不再维护一份重复的 active script 硬编码排除表，而是从 `data_center_operational_entrypoints.json` 读取 `active_public` 运维脚本；因此恢复验证器只作为真实运维入口登记，不会因治理文本再次生成伪 dispatch edge。旧入口精确测试 4 passed，入口 stale-check 仍为 1182 项且无待审候选。
- 最终复核：修复后的真实 PostgreSQL source/restore 全量比较为空差异；397 张表逐行有序 JSON SHA-256、Data Center migrations、稳定 schema SHA-256 与 326 个 sequence 状态全部一致。source fingerprint 约 382 秒、restore fingerprint 约 306 秒；入口清单重建仍为 1182 项且 `candidate-review=0`，专项 40 passed。
- 明确边界：本地 dump 来自一次性 client 容器，尚未证明 `manage.py backup_database` owner 路径；dump 与随后 live-source snapshot 也未使用同一 exported snapshot。GitHub PostgreSQL job 实际绿灯、artifact 下载、VPS 生产规模 RTO、host-key pinning、真实 archive mount/key 与 writer quiescence 仍是生产切换/M9 的前置条件；本轮不部署。

## 135. 2026-08-07：全入口最终收编与双版本 CI 收口

- 入口边界根因：Alpha 价格覆盖命令同时消费 Data Center factory 与纯 Protocol；后者已拆到稳定的 `application.public_protocols`，但入口扫描器只承认 `application.public`，拆分大文件会让已治理消费者从清单中消失。扫描器现将两个模块都视为 canonical Application public boundary，并用精确测试固定 Protocol consumer；最终快照保持 1182 项，`active_public=617`、`adjacent_operational=281`、`compatibility=250`、`retired_blocked=34`、`candidate-review=0`。
- 大文件与可诊断性：不再向 1118 个非空行的 `public.py` 追加 re-export，消费者直接使用稳定 Protocol 边界，文件净缩减且 size guard 通过。全仓 mypy debt guard 在计数增长时同时打印精确源码行，避免只凭 `type-arg/union-attr` 汇总猜修；对应单测 5 passed。
- 类型环境根因：CI 自动解析到 `django-stubs 6.0.8` / `djangorestframework-stubs 3.17.1`，本地旧小版本未把 `UploadedFile` 声明为泛型，形成 Python 3.11 CI 独有错误。两项开发类型契约已在 `pyproject.toml` 精确锁定并同步生成 `requirements-dev.txt`；上传边界使用 `UploadedFile[bytes]`，同时通过 postponed annotations 避免 Django 运行时类不可下标。Django field choices 的显式 `None` 契约统一按空集合 fail closed。
- 旧链测试纠偏：Alpha strict-valuation component fixture 从已退役的 Equity `ValuationModel` 切到 canonical `ValuationFactModel`；Tushare quote fake 接受当前显式 gateway 配置；System Settings Admin 测试改为断言已退役路由继续返回 404，不为陈旧测试重新注册 legacy Admin。
- 本地证据：全仓生产 mypy 为 `0 errors in 0 files`；入口专项 17 passed，入口与 Tushare 完整性组合 32 passed，Strategy API/结构回归 36 passed，旧 Admin 退役回归 1 passed；module graph 为 208 edges、0 bidirectional、0 cycles，architecture delta 0 violations，changed-file size、Ruff、Black、isort 与 dependency projection 均通过。用户工作区的 R5 relative-value 测试改动未纳入任何提交。
- GitHub 证据：提交 `37c9b6af` 的 Architecture Layer Guard `31185957181`、Security Scan `31185957135`、Consistency Check `31185957215`、CI Fast Feedback `31185957203` 全部成功；Fast Feedback 内 Python 3.11、Python 3.13、incremental quality gates、no-database TDD 均成功。
- 明确边界：本节完成“静态发现入口全部有 owner/status/target、候选归零、CI 防回归”的验收，不把 250 个 compatibility seam 冒充物理删除，也不替代生产 writer quiescence、VPS 规模 RTO、archive mount/key、外部备份下载回执或 M9 destructive migration。本轮遵守用户指令不部署、不修改 VPS。

## 136. 2026-08-07：退役入口物理清除与动态表名防回归

- 根因：§135 虽已把 34 个危险入口标为 `retired_blocked`，标签本身不能阻止人工执行；旧 canary/rollback 脚本仍含真实操作代码，SQLite-only PowerShell 备份/恢复仍会被收进 VPS bundle。另有未登记的 `check_all_tables.py` 通过表名列表和 f-string 动态读取 `macro_indicator`，绕过了只识别字面 SQL 的旧 guard。
- 物理退役：删除 11 个过时运维脚本、2 份传播旧部署/恢复命令的 runbook，并从 bundle 打包、验包与当前部署文档断开 PowerShell 旧备份/恢复入口；旧 canary 三件套整体删除，当前部署只保留 Docker/VPS 验证链。Fund/Sector migration package 的 `__init__.py` 中两份误复制 `Migration` 类清为空 package marker，防止伪入口继续干扰审计。
- 配置死口：删除从未注册的 `SystemSettingsAdminForm/SystemSettingsModelAdmin` 及其独占 singleton presence seam；治理清单移除这些假消费者。删除无生产消费者的 `SystemSettingsModel` Qlib runtime getter、旧 `QLIB_SETTINGS` 和旧 asset-proxy class getter；Qlib 运行读取继续只经过 active typed Config Center snapshot，缺失时 fail closed。备份策略当前缺少可达的人机写入口被明确保留为后续产品缺口，不用死 Admin 伪装覆盖。
- 动态访问门禁：legacy fact guard 新增 table-selector AST 检测，表名被放入 `*table*` 选择变量后再动态拼 SQL 也会命中；模型 owner 文件仍作为定义/迁移保留白名单。健康检查中仅作为响应 key 的 `macro_indicator` 不误报。两个已经引用被删除 Admin class 的陈旧测试改为断言旧模型未注册，恢复可收集、可执行状态。
- 最终入口快照：共 1132 项，`active_public=617`、`adjacent_operational=272`、`compatibility=243`、`retired_blocked=0`、`candidate-review=0`。相对 §135 减少 50 项，来自真实文件、dispatch edge、runbook 与死兼容 symbol 删除，不是生命周期重分类。
- 本地证据：入口/Config Center/Qlib/旧 Admin 定向回归 50 passed，动态表名门禁 7 passed，Fund/Sector 陈旧 Admin 包 16 passed；固定 TUI/Terminal/SDK/SSL 回归 287 passed，入口与部署/备份专项 37 passed。legacy fact access guard、legacy script guard、Qlib inventory、PowerShell parser、Shell syntax、JSON、Ruff/Black、8 个生产文件增量 mypy、architecture 0 violation、module cycle 0、governance 0 violation、Django check 与 `makemigrations --check` 均通过。
- 明确边界：本批完成“所有可执行入口均已收编、已判退役入口不再可执行”的本地目标，但 7 张 retained legacy fact 表和 `SystemSettingsModel` 仍受数据物化、一致性、专用锁、备份恢复与 destructive migration preflight 约束。当前本地 Fund NAV 仍有 3 行新旧差异，且未做生产恢复取证；因此不生成删表 migration，不部署、不修改 VPS，也不把 243 个仍有消费者或外部兼容义务的入口冒充已删除。

## 137. 2026-08-07：入口清理触发的合并态治理债务收口

- 首轮远端反馈：Architecture 与 Security 通过；Consistency 和 Fast Feedback 同时发现 architecture inventory 未随已删除 runtime 参数重建。重建后 runtime parameter reference 从 52 降到 49，行号与删除内容同步，不抬高债务基线。
- 全量 guard 额外暴露两个此前未进入 AGENTS 人工目录的既有模块 `fixed_income/macro_factor`，以及 Fixed Income blocker 名中被运行时 mock guard 禁止的 `SYNTH*` 标记；目录清单补齐，blocker 改为稳定 `quote_age.unverifiable` 语义，不通过 guard 白名单掩盖。CI 新版 Ruff 进一步暴露 5 个 `str + Enum` 旧写法，统一迁到 Python 3.11 `StrEnum`，保持序列化值不变并清掉增量债务。
- 覆盖门根因：旧 workflow 对任意 `apps/<app>/domain` 改动都只执行 `tests/unit/domain/`，遗漏 `tests/unit/<app>/`，使已有完整 Fixed Income 测试不参与覆盖率。新增 app-aware runner，按 changed Domain module 自动加入共享和 App 自有测试目录；门槛仍为 70%，真实 `liquidity_premium.py` 覆盖为 73.7%，1597 passed。
- 治理计数：仓库提交态静态测试函数已从旧基线 9937 增至 11241；补充 Domain coverage runner 的 2 条精确回归后更新为 11243 / `v212`。共享工作区另有用户未提交的 R5 测试，局部实际计数会多 1，未纳入 baseline 或提交。
- 最终入口复扫：`governance/data_center_entrypoints.json` 共 1132 项，其中 `active_public=617`、`adjacent_operational=272`、`compatibility=243`，`candidate-review=0`、`retired_blocked=0`；架构库存同时确认 `legacy_fact_references=0`、`provider_imports_outside_data_center=0`，Qlib runtime inventory 44 项全部有效。旧脚本入口仅保留 4 个已登记 compatibility wrapper，无未登记 direct entrypoint。
- 验证：AGENTS module inventory 与 runtime mock guard 2 passed，governance consistency 为 0 violation；提交 `8084994b` 的 Architecture Layer Guard、Security Scan、Consistency Check、CI Fast Feedback 四条流水线全部通过。本批继续不部署。

## 138. 2026-08-08：SystemSettings 硬依赖断链与 Fund NAV 差异闭环

- 决策闸门根因：`DecisionRuntimeStateModel` 缺行时仍回退 `SystemSettingsModel.decision_runtime_*`，两边都缺时又继承 legacy `active` 默认，违反“关键状态缺失必须 fail closed”。运行读取现已只认 Config Center 独立状态表；缺行返回稳定 `blocked`，不创建旧 singleton、不读取旧列。`0013_materialize_decision_runtime_state` 只迁移具备显式状态证据的旧值，无旧行或无显式 active 证据时种入 blocked，并覆盖 forward/reverse/reapply migration 测试。
- Qlib 锁根因：训练准入虽已使用 typed Profile，但仍通过 `system_settings(pk=1)` 充当全局并发锁，导致配置字段全部迁完后旧表仍不能删除。新增 Config Center 自有 `QlibTrainingRunLockModel` 与 `0012` migration；PostgreSQL 使用专用行 `select_for_update`，SQLite 只提供开发/测试同进程锁。Application Protocol/UseCase 不再传入 settings repository，生产源码中 `acquire_system_settings_lock` 引用归零；PostgreSQL 条件并发测试已接入 Nightly job。
- Fund NAV 差异根因：本地 legacy 7648 行中有 3 个自然键未进入 `fund_legacy_repo` canonical projection：`000004/2025-01-14`、`000011/2025-10-27`、`000029/2025-01-07`；其余 7645 个共同键逐字段相等，canonical-only、重复键和数值冲突均为 0。新增 `fund.0004` 有界迁移，只在 legacy lineage 内执行冲突先阻断、缺行补齐、snapshot hash 复核和确定性 reconciliation evidence；不覆盖或误判其他 Provider source。修复后本地为 7648/7648、差异 0，migration lifecycle 测试覆盖零写入失败、修复、reverse 与幂等 reapply。
- compatibility 继续物理收缩：删除仓库内无源码、调度、打包和文档调用的 `scripts/debug/refresh_macro_data.py` 与 `scripts/sync_akshare_data.py`，canonical 替代统一为 `manage.py sync_macro_data`。仍有公开文档契约的 `run_backtest.py/seed_historical.py` 保留；旧 Retention task、Equity Celery alias 必须先确认生产 Beat/队列无旧 dotted name，25 个 legacy MCP raw tools 必须走明确 SDK 版本窗口，均不冒充死代码删除。
- 机器证据：Decision/Qlib 组合包 8 passed、PostgreSQL 条件 1 skipped；Decision migration 1 passed；Fund NAV migration lifecycle 与零修复 clean-evidence 共 2 passed、reconciliation evidence 4 passed；legacy wrapper/guard 9 passed；固定 TUI/Terminal/SDK/SSL 回归 287 passed。`makemigrations --check`、runtime config/SystemSettings/Qlib guards、Ruff/Black、增量 mypy、architecture 0 violation 均通过。入口库存重建为 1128 项：`active_public=618`、`adjacent_operational=270`、`compatibility=240`、`candidate-review=0`；架构库存继续保持 `legacy_fact_references=0`、`provider_imports_outside_data_center=0`。
- 明确边界：本批新增 Nightly PostgreSQL migration/concurrency nodeid，但在远端 workflow 实际绿灯和 artifact 取回前不宣称 PostgreSQL DoD 完成；未执行 VPS、生产 profile、真实 backup/restore、旧表 destructive migration 或部署。SystemSettings 其他 account/backup/secret projection 与 7 张 retained legacy fact 表仍按 M9 前置继续收口。

## 139. 2026-08-08：全入口二次枚举、真实兼容债务收编与 Nightly 根因修复

- 全入口复核：对 §138 的 1128 项逐项按 facade、runtime/SystemSettings、Celery/命令/脚本、MCP/SDK 分组复审。发现 50 项不是旧链，而是跨 App 正确消费 canonical Public Port 或受 Celery contract 治理的现役任务；扫描器现只把显式 alias、legacy registry、旧 singleton fallback 和有版本窗的外部入口标为 compatibility。删除死入口和薄包装后，确定性快照为 1124 项：`active_public=618`、`adjacent_operational=321`、`compatibility=185`、`candidate-review=0`、`retired_blocked=0`。
- 生产消费者收编：Data Center tasks、read facade、API/Admin/TUI/page views 与两个管理命令不再直接 import compatibility facade，14 个已有等价端口的调用统一切到 `apps.data_center.application.public`。删除无调用的 `query_services.get_latest_market_thermometer_snapshot_payload`；其余 facade 保留到实现搬入专用 private composition/query 模块，避免只删 wrapper 后让 `public -> legacy facade` 倒置继续存在。
- 物理退役：删除无正式调度/文档消费者的 `sync_equity_financial` management command，正式财务同步只保留 governed `sync_financial_data_task`；删除无独立契约的 `deploy-one-click.sh`，bundle 部署直接使用 `deploy-on-vps.sh --bundle`，并从两个打包脚本和 operational manifest 断开。仍保留的 185 项已精确归类为 facade 91、runtime key 39、MCP 30、SystemSettings 文件 10、Celery alias/legacy task 5、运维 dispatch 3、runbook 2、command wrapper 2、management command 1、operational script 1、SDK 1。
- 架构债务：入口回归暴露 Research R2 composition 直接 import 两个 Data Center infrastructure 模块；新增 Data Center-owned market-structure composition factory，Research 仅通过 composition boundary 获取 evidence reader/publication gate。`direct_data_center_imports_outside_data_center` 从 2 真正降到 0，不修改测试期望或债务基线掩盖。
- Nightly 根因：run `31202288832` 的通用 job 因 Decision Runtime fail-closed 后 API 测试未显式 admission，21 个 API 契约被统一 503；同时 `--no-migrations` 让依赖 migration seed 的 R2 scenario 测试缺行。API 测试现显式创建 active runtime，current-data Nightly 恢复真实 migrations；本地干净建库执行 268 个 nodeid、展开 307 tests 全部通过。PostgreSQL job 进一步发现 `0065` 反向缩列时 `sha256:` 摘要超过旧 64 字符限制；追加 `0066` 在旧 schema narrowing 前只归一已知 SHA-256 前缀，保留 64 位摘要，不修改已发布 migration。SQLite forward/reverse/reapply 1 passed；真实 PostgreSQL 仍以重跑 Nightly 为最终证据。
- 兼容剩余边界：Qlib 10 键已经无运行时 SystemSettings consumer，但仍需一次性数据物化、bootstrap 解耦和删列；Account/Alpha/Market/Backup 共 26 键仍有真实旧 singleton fallback，Provider 3 键仍回退另一旧设置表。4 个 Equity dotted alias 与 retention preview task 需生产 Beat/queue 只读取证；29 个 legacy MCP tools、Realtime SDK 方法和公开命令 wrapper 需明确外部版本窗。未取得相应证据前不把它们误删或标成已完成。
- 明确边界：本节只完成本地代码、清单和 CI 测试契约收编；不部署、不连接或修改 VPS、不执行生产数据物化、队列清理、真实生产备份恢复或 7 张 legacy fact 表/SystemSettings destructive migration。Nightly 修复提交后的 GitHub PostgreSQL/完整套件结果将在实际 run 成功后补记。

## 140. 2026-08-08：全入口收编后的可本地退役项收口

- Qlib 根因与切断：10 个 Qlib runtime key 的真实消费者已是 canonical-only/fail-closed，剩余风险是后续任意 profile patch 仍会从 `SystemSettingsModel` 回填旧 Qlib 字段。新增 append-only `0014_materialize_qlib_runtime_profile` 一次性把已有旧值物化到当前环境的 profile/value/snapshot/revision，已有 canonical 值优先，无旧 singleton 时不造默认快照；bootstrap 不再读取 `settings_obj.qlib_*`，10 项契约改为 `canonical_only_fail_closed`。SystemSettings 兼容字段因此从 46 降为 36。
- 任务体积根因：入口迁移让 `apps/data_center/application/tasks.py` 从 1006 增到 1008 个非空行，触发 1000 行增量硬门，而非业务测试失败。A 股核心数据回填批次编排已拆到 `core_data_backfill.py`，通过显式 services/ports 注入；Celery dotted name、参数校验、幂等键和旧测试 monkeypatch 边界保持不变，`tasks.py` 降到 788 行，新模块 300 行，不增加体积豁免或基线债务。
- 命令包装退役：`scripts/run_backtest.py` 只是 `manage.py run_backtest` 无损透传；`scripts/seed_historical.py` 的仓库内使用可由 `manage.py sync_macro_data --indicators ...` 完整表达，旧 `--check` 无消费者。在全仓源码、调度、打包、文档和测试迁移后删除两个 wrapper，legacy script guard 达到 `0 direct / 0 wrappers`。
- 机器快照：确定性入口清单为 1120 项，`active_public=628`、`adjacent_operational=319`、`compatibility=173`、`candidate-review=0`、`retired_blocked=0`；相对 §139，12 个 compatibility 减少由 10 个 Qlib 键完成真实切断和 2 个 wrapper 物理删除组成，不是重新贴标。架构清单继续为 Data Center infrastructure 外部直连 0、Provider 外部直连 0、legacy fact 引用 0、module cycle 0。
- 本地证据：Qlib migration/control-plane 8 passed，统一 migration/Qlib/backfill/wrapper/入口/架构包 49 passed；SystemSettings field contract、runtime config coverage、Qlib entrypoint、Celery task contract、current-data contract、Ruff/Black/isort、增量 mypy、全仓 mypy debt ceiling 与 governance consistency 通过。GitHub 标准 CI 和 Nightly 证据待本批提交后补验。

## 141. 2026-08-08：全入口一次收编与 Nightly 隐藏结构债务清零

- 入口总账再次从源码、HTTP/SDK/MCP/TUI、Celery/Beat、管理命令、脚本、运维证据和 current-data contract 全量重建；确定性快照仍为 1120 项：`active_public=628`、`adjacent_operational=319`、`compatibility=173`、`candidate-review=0`、`retired_blocked=0`。本批没有用重新贴标降低兼容数量；173 项均仍有真实消费者、外部契约或迁移义务。
- Nightly 全量单测暴露 23 个失败，归并为测试选择映射、Repository/任务文件体积、R5 时钟构造、状态模型跨 Python 异常、备份测试数据库污染、Dashboard 适配、Rotation reliability port 和 Terminal/TUI 连锁阻断八类根因。所有失败均按根因修复，没有提高行数预算、放宽架构门禁或全局开放测试数据库。
- 结构债务按 owner/facade 模式一次拆清：Data Center `macro_fact_repositories.py=449`、`market_data_repositories.py=4`、`fundamental_fact_repositories.py=5`、`market_breadth_repositories.py=270`；Equity fundamentals 为 656；AI capability use-cases 为 1139；Alpha tasks 为 1067。被首个断言短路遮住的 Market Data、Fundamental Fact 和 Market Breadth 超限也同步拆分，新增 owner 全部纳入结构预算与 current-data marker 真源。
- 运行契约修复包括：R5 active reader 缺省使用 timezone-aware UTC server clock；Rotation 对缺失、异常、空 reliability contract 统一 fail closed，但不再吞掉已经生成的业务信号；Dashboard 适配测试隔离数据库策略依赖；Python 3.11/后续版本均验证 content-addressed identity 不可覆盖；备份测试用局部 capacity stub 和可回滚 settings 修改，终止 `DATABASES` 污染导致的 `ATOMIC_REQUESTS` 连锁失败。
- 额外消除一处测试顺序债务：AI Capability HTTP client 显式建立 active decision-runtime gate，因此独立运行不再依赖前序测试偶然改变运行状态；生产迁移和中间件仍保持 fail closed。
- 本地证据：Nightly 精确/结构包 70 passed，跨 Data Center/Equity/AI/Alpha 扩大包 139 passed，全量 `tests/unit` 为 8952 passed；24 个变更生产文件增量 mypy 0，全仓 mypy debt 0；current-data 46 surfaces、Celery 31 tasks、Qlib 44 entries、Django check/migration check、Ruff/Black/isort、architecture delta、module cycle、changed-file size 与 governance consistency 全部通过。
- 边界：本批完成本地入口枚举、owner 收编、结构债务和 Nightly 单测债务清零；不部署、不连接或修改 VPS，不把 173 个 compatibility seam 冒充已退役，也不执行 retained legacy table 的 destructive migration。GitHub 标准 CI 与 Nightly 将在提交推送后补充远端证据。
- 仍保留的边界：Account/Alpha/Market/Backup 26 个键、Provider 3 个键和 10 个 SystemSettings 直接文件仍有真实运行兼容读；4 个 Equity alias、Retention preview task 需生产 Beat/queue 零引用证据，legacy MCP/SDK 需外部版本窗。本批不部署、不连接 VPS、不执行生产物化或 destructive migration。

## 142. 2026-08-09：全入口最终枚举、跨午夜市场日期修复与 Nightly 全绿

- 最终入口总账：确定性清单从全部 REST、SDK、MCP、TUI、Capability、Celery/Beat、管理命令、脚本、运维 dispatch、Public Port、compatibility façade 与 current-data surface 重新生成并由 CI 复核，共 1121 项；`active_public=629`、`adjacent_operational=319`、`compatibility=173`、`candidate-review=0`、`retired_blocked=0`。分类与状态没有人工重贴标，内部 `market_time` 纯 Domain 工具不冒充新入口；`query_published_*` 仍由既有 compatibility façade 归属，可靠性测试证据由 current-data contract 管理。
- 跨午夜根因：canonical publication 的 `as_of` 是 aware UTC instant，读侧却直接 `.date()` 截成 UTC 日；中国时间午夜后、UTC 午夜前会把 8 月 9 日估值/价格/净值等事实错误过滤成“尚未发生”。写侧又把 date-only 中国市场事实编码为 UTC 零点，使市场日语义与真实观测边界相差 8 小时。该缺陷只在 Asia/Shanghai 跨日后触发，因此旧测试白天通过、Nightly `31266108744` 在跨日后稳定复现 3 个 Integration 失败。
- 根修：Data Center Domain 新增唯一中国市场日期边界，date-only 事实统一映射为中国本地零点对应的 UTC instant；publication instant 统一投影回中国市场日期。估值、价格日线、基金净值、宏观、板块成员和资金流六类 publication candidate 全量切换；Integration 发布助手不再猜测字段优先级，所有调用方必须显式声明 `bar_date / val_date / available_at / published_at` 等源观测字段。naive datetime 在决策边界继续 fail closed。
- 契约与防回归：`data_center.publication_only_d4_d5` 登记 UTC→中国市场日投影与跨午夜测试；`data_center.publication_writer_atomicity` 更新六条旧 UTC-midnight marker，并登记中国市场日首时刻证据。current-data guard 为 46 surfaces、Celery 为 31 tasks；架构库存为 cross-App ORM 51、current surface references 3420、data-write decorators 58、runtime parameter references 49，Data Center infrastructure 外部直连 0、Provider 外部直连 0、legacy fact references 0。
- Nightly 逐根修复记录：`31249375507` 暴露 Domain 覆盖选择/ratchet 结构缺口；`31258833905` 暴露 Dashboard canonical fixture 陈旧；`31262272754` 在 PostgreSQL、Unit、Component、API/Migration、SQLite、Integration、App-local、SDK、MCP、E2E 均绿后，仅因静态测试精确计数 11256→11462 失败；`31266108744` 暴露上述跨午夜市场日期缺陷；`31272241933` 的所有功能层与 Guardrail 通过，最终精确覆盖率显示 Data Center Domain `843/968=87.0868%` 低于 87.1 门槛。未降低基线，补齐既有 Quarantine 合法 resolved lifecycle 缺失分支后越过 ratchet。
- 本地证据：跨日目标包 56 passed；完整 Integration 为 `1038 passed, 13 deselected`；Domain/Data Center 合并包 `2325 passed`，新 `market_time` 行覆盖 100%；8 个生产文件 mypy regression 0，全仓 mypy debt 0；Black/isort/Ruff、architecture boundary、architecture delta、module cycle、governance、current-data、Celery、完整入口与 architecture inventory 均通过。干净 detached worktree 的精确 governance Guardrail 1 passed，用户工作区 R5 未提交测试未进入基线或提交。
- GitHub 最终证据：提交 `c730f791` 的 Architecture `31272010917`、Fast `31272010903`、Consistency `31272010904`、Security `31272010902` 全绿；覆盖补证提交 `679a3d87` 的 Architecture `31275973597`、Fast `31275973593`、Consistency `31275973577`、Security `31275973554` 全绿。最终 Nightly `31276312734` 成功，PostgreSQL、current-data/Celery manifest、mypy、frontend、Unit、Component、API/Migration、SQLite critical、Integration、App-local、SDK、MCP、Django E2E、Guardrail、coverage ratchet、架构审计与 Playwright 全部通过。
- 明确边界：本节完成“所有静态入口有 owner/status、候选为零、跨午夜数据语义根修、完整 Nightly 全绿”的开发与 CI 验收；173 个 compatibility seam 仍按真实外部契约或迁移义务保留，不冒充物理退役。遵守用户指令，本轮未部署、未连接或修改 VPS、未执行生产数据物化、生产观察窗口或 destructive migration。

## 143. 2026-08-09：M9 剩余五组配置物化与运行旧链退役

- 范围冻结：本批只处理 Provider 3 键、Account 7 键、Alpha 2 键、Market 3 键、Backup 12 个 policy key + 2 个 secret ref，以及 Backup 4 个 delivery state 字段；不新增业务功能。Qlib 10 键继续沿用 `0014`，Decision state 继续沿用 `0013`。
- 一次性物化：新增 `0015_materialize_remaining_runtime_groups`，在一个事务中合并现有 active profile 与两个 legacy singleton。已有 canonical value/secret/state 永远优先；旧密文必须先验证解密，再按 Config Center `encrypted:v1` 格式重加密。不可恢复密文使整个迁移回滚；无 legacy row 的新安装不伪造 runtime profile。重复执行不创建新 revision/snapshot。
- 全消费者切换：Provider resolver、summary、Admin、repository/protocol/composition export 不再读取 `DataProviderSettingsModel`；Account/Alpha/Market/Backup 运行读写只认 typed profile、ConfigCenterSecret 和独立 state。删除 account 对 `SystemSettingsModel` 的跨 App re-export、备份 legacy secret 迁移命令和所有生产 singleton consumer；历史 model/columns 仅为 `0015` 与后续 rollback/destructive release 保留。
- 分组 fail-closed：Alpha 与 Market 投影独立解析，任一组缺失不再隐藏另一组；系统整体状态仍要求 Account/Alpha/Market 全部完整。Provider、Backup 或任意组缺失/partial/invalid 时发布稳定 `blocked` 与 `runtime_config_snapshot_unavailable`，不回退 `akshare/true/0.01` 或旧 singleton 默认。
- 治理强化：29 个 key 全部登记为 `canonical_only_fail_closed`、`fallback=blocked`、`materialization_required=true`；SystemSettings 48 个字段中运行兼容计数降为 0。门禁现在验证 migration 路径、consumer/test locator、重复 key 和 materialized field-group replacement；备份密钥旧写为 0。Nightly PostgreSQL migration 包新增 `0014` 与 `0015` 生命周期测试。
- 静态入口结果：确定性入口总账为 1108 项，`active_public=656`、`adjacent_operational=319`、`compatibility=133`、`candidate-review=0`；`system_settings_compatibility=0`。架构库存为 cross-App ORM 49、current surface 3432、data-write decorators 58、runtime parameter references 49，Data Center infrastructure 外部直连、Provider 外部直连、legacy fact 引用均为 0。
- 本地证据：`0015` lifecycle 2 passed；入口 inventory 17 passed；配置/Provider/Account/Backup/MCP 定向组合持续通过；current-data 46 surfaces、Celery 31 tasks、runtime config 40 definitions/29 materialized、SystemSettings field contract、secret owner、Django check/migration check、Ruff/Black/isort、architecture delta、module cycle 与 governance consistency 均通过。
- 发布边界：本批先保留历史列/表，不生成 destructive DeleteModel/RemoveField；原因是生产必须先执行 `0015` 并保留可恢复窗口。代码提交、GitHub CI、生产 PostgreSQL custom backup 下载校验和 VPS 部署证据在后续步骤补记；CI 全绿前不部署。

## 144. 2026-08-14：架构库存与治理 source snapshot 刷新

- 重新运行 `python scripts/data_center_architecture_inventory.py --write`，把治理清单与当前提交态源码重新对齐；随后以无写入模式再次运行同一脚本复核生成结果。
- 当前静态计数为：`approved_non_data_http_imports=4`、`cross_app_orm_imports=48`、`current_surface_references=4225`、`data_write_task_decorators=58`、`runtime_parameter_references=49`；`direct_data_center_imports_outside_data_center=0`、`provider_imports_outside_data_center=0`、`legacy_fact_references=0`、`external_http_imports_for_review=0`。
- 本地门禁复核：`check_governance_consistency.py`、`verify_architecture.py --include-audit --format text`、Data Center catalog/legacy-fact/current-data/Celery contract guards 均通过；本次只刷新 source inventory，不改变运行时数据、不回填生产表、不删除 retained legacy schema。
- 解释边界：`cross_app_orm_imports` 与 `current_surface_references` 是静态源码计数，不能替代 PostgreSQL 生产 snapshot、VPS 部署版本、备份/恢复、shadow reconciliation、writer quiescence 或 M9 destructive migration 证据；在这些证据齐备前，Data Center 生产切换与旧表删除继续保持 DENY。

## 145. 2026-08-20：当前候选 PostgreSQL Nightly 关键可靠性证据

- 当前候选 `dev/next-development@578064409b8269e440ba7edbf9c480aa7d9917ff` 的
  [Nightly run 32276242287](https://github.com/guiyinan/agomTradePro/actions/runs/32276242287)
  独立 `Critical Reliability (PostgreSQL)` job 成功；PostgreSQL `16.15` 空库全量迁移、
  migration plan、Data Center catalog、storage capacity profile、custom-format backup、
  隔离 restore 和 canonical verifier 均通过。
- restore artifact：`outcome=success`，dump `3,600,046` bytes，SHA-256
  `2b4c7e57e33aa797abfac49d7935d0f0276a0d9616cb123d131c180605a75a75`，`7,167` TOC entries，
  restore `3.208s`、逐表/schema verification `0.802s`、total `5.248s`；restore 前后 digest
  一致，missing/extra/changed 表、sequence、migration 均为空。
- PostgreSQL JUnit artifact 为 `critical 18`、`research migrations 8`、`publication/runtime 41`、
  `current-data 349`、`Celery 220`、`backfill/retention 61` 全部 passed；retention concurrency
  为 `3 passed + 1` 明确标记的 SQLite fallback skip（合计 `700 passed + 1 skipped`）。
- 该条只解除“GitHub PostgreSQL Nightly 实际运行取证”这一测试计划子项；生产 backup/restore、
  RTO/RPO、维护态 rollback、生产回填/reconciliation、shadow 对账、M9/M10 和旧表删除仍未完成，
  不改变 DATA-01/02/03 的生产 gate。

## 146. 2026-08-31：DATA-04 只读配置边界与 ASGI 连接生命周期

- successor-bound DATA-02 preview 暴露生产 PostgreSQL client saturation；只读运行证据将绝大多数 idle
  client 归因到 Daphne Web，增长周期约 30 秒，与 DB-backed Prometheus scrape 对齐，生产设置仍为
  `CONN_MAX_AGE=600`。该关联为高置信度根因，不冒充 post-fix 生产验收。
- production settings 现固定 `CONN_MAX_AGE=0`，正数环境变量不能重新启用 ASGI request-scoped
  persistent connection；如需复用连接，应由外部 transaction pool 承担。
- `ProductionCoverageUniverseConfigRepository.load()` 只做 exact singleton SELECT；缺行抛
  `MissingConfigError`，不再由 model `get_or_create` 自动播种。显式 repository `save()` 和完整 PUT
  才能初始化，PATCH/diagnostic/dry-run 在缺配置时 fail closed。
- 聚焦合同 `18 passed`；DATA-04 相关扩大回归 `69 passed`，另有与本批无关且 HEAD 已存在的
  `financial_fact_repository.py` 243/200 行结构门失败；mypy、current-data、架构、格式、Django、
  migration 和治理检查均通过。规范化证据为
  [`data04-asgi-db-select-only-preview-repository-closure-evidence-2026-08-31.json`](../testing/data04-asgi-db-select-only-preview-repository-closure-evidence-2026-08-31.json)，
  SHA-256=`aaaa675ed5bc078a916244de91bf2a335da5e2519883b312c2cc1dd0a034ea8d`。
- 本 checkpoint 没有终止生产连接、重启、部署、写事实或执行 backfill。只有 clean successor 部署后
  跨多个 scrape interval 的连接稳定性、database/readiness 恢复和 truly SELECT-only dry-run 通过，
  才能继续 DATA-02；任何候选变更同时触发 TUI-02 重新绑定和观察计时。

## 147. 2026-08-31：DATA-05 Financial availability owner 拆分

- 结构回归确认 `financial_fact_repository.py` 在 HEAD 上即为 243/200 行，属于真实 CI blocker；没有把
  该失败归因到 DATA-04，也没有通过提高预算、白名单或 debt baseline 掩盖。
- availability preview/backfill 移入 65/100 行的
  `financial_availability_repository.py`；`FinancialFactRepository` 继续由原模块导出并继承该行为，
  facade/import identity、publication selector 和 as-of read 均不变。原 owner 降至 189/200。
- `data_center.core_current_publication_rebuild` 注册新 source 和三项稳定 marker；结构/ORM `12 passed`，
  DATA-04/05 组合回归 `70 passed`，mypy、current-data、架构、格式、Django/migration 与治理全绿。
  证据为
  [`data05-financial-repository-owner-closure-evidence-2026-08-31.json`](../testing/data05-financial-repository-owner-closure-evidence-2026-08-31.json)，
  SHA-256=`7c535f2a1802561be3430a8a9a2149da4ab08b885f2ad672f96828209da8a56a`。
- 本 checkpoint 纯 repository 结构整改，没有生产读取、写入、重启、部署或回填；DATA-02/03
  production gate 与 DATA-04 clean-deploy/revalidation 前置保持不变。

## 148. 2026-08-31：DATA-06 隔离历史模拟 focus 激活

- 项目所有者授权采用历史数据 simulation-first 推进后，机器注册表将 `DATA-06` 设为唯一
  repository focus。盘点确认当前能力存在断点：restore verifier 能验证 custom dump，DATA-02
  recorder 能解析外部 SELECT-only snapshot，但没有一个 runner 在 disposable PostgreSQL 中完成
  restore → provider/network-free coverage/freshness/source-time/reconciliation → candidate-bound artifact →
  zero-residual cleanup。
- 工作区已有两个被 `.gitignore` 隔离且 SHA-256 sidecar 匹配的 2026-08-29 custom dump；本单元只允许
  使用已有不可变输入，不创建/下载生产备份。所有数据查询必须位于 repeatable-read read-only 事务，
  unsafe/non-local target、dump drift、写语句、schema 缺失、候选绑定缺失或 cleanup residue 均失败关闭。
- 本单元只证明历史备份上的候选离线行为和可重放 reconciliation；不连接生产、不调用 provider、不执行
  backfill/publication 写入、不建立 authority/profile、不启用 decision runtime，也不替代 DATA-02/03 的
  clean-deploy、current freshness、生产容量、真实回填/reconciliation 与 owner acceptance。

## 149. 2026-09-01：DATA-06 隔离历史模拟 repository exit

- 新增 Application 层纯分析合同、psycopg Infrastructure snapshot adapter 与独立 CLI runner。runner 只接受
  loopback PostgreSQL 和 `agom_data02_sim_*` disposable database，先校验 dump sidecar，再通过 PostgreSQL
  `REPEATABLE READ READ ONLY` 事务读取生产 coverage config、active Dataset Contract、四类最新事实与 current
  publication/member；provider 和外部网络不参与。unsafe target、dump drift、schema/contract ambiguity、naive/future
  observation、非只读事务及 cleanup residue 均 fail closed。
- 使用既有 `postgres-20260829T171523Z.dump` 完成两次真实本地恢复。最终绑定 dump SHA-256
  `18d208a5…6034f`、7,229 restore entries、Data Center migration head
  `0072_note_non_st_price_limit_scope`、5,533 个 active A-share；分析 artifact SHA-256
  `204d5706…20cd1`，数据库和外层 disposable container 复查均无残留。
- 历史数据没有被“测试通过”美化为可用：四类 Dataset Contract freshness 均读取成功但四类 gate 全为 `DENY`。
  Quote/Price/Valuation 的候选事实覆盖均为 `5,533/5,533`，Financial 仅 `1,923/5,533`；四类 current
  publication reconciliation 均失败，全部存在 stale observation。该结果把后续开发输入固定为真实覆盖、时效与
  publication rebuild 缺口，而不是 simulator 选择器缺失。
- 聚焦与相关回归 `57 passed`；3 个生产文件增量 mypy 与全仓 debt 均为 0；53 个 current-data surfaces、
  3,008-file architecture、Ruff/Black/isort、Django check 和 migration drift 全部通过。规范化证据为
  [`data06-isolated-historical-simulation-repository-closure-evidence-2026-09-01.json`](../testing/data06-isolated-historical-simulation-repository-closure-evidence-2026-09-01.json)，
  SHA-256=`e4883f46426b2b9082392371276a79ff4bbcab07e7a6c6022c02f8563d68579a`。
- DATA-06 仅关闭 repository capability，`production_claim=false`、`production_ready=false`。DATA-02 仍须 clean
  successor 部署、跨 scrape interval 的连接/readiness 稳定、candidate-bound production dry-run、已授权有界
  backfill 与生产 reconciliation；DATA-03 activation 和 TUI-02 候选观察不得继承本历史结果。

## 150. 2026-09-01：候选 CI corrective 顺序登记与 DATA-07 focus

- `53ddbff137c9a0c379c73c6f4c64244613e2741b` 推送后的 Fast Feedback 在 Python 3.11/3.13
  上均暴露同一测试合同失败：`test_t3a_akshare_provider_paths.py` 的 fake quote 未提供权威
  `market_gateway_entities.QuoteSnapshot.source` 字段，而生产 gateway 的返回类型和两条构造路径均保证该字段。
  该失败不能通过把生产 adapter 改成无类型对象兼容层来掩盖，应让测试 fixture 遵守正式 DTO 并断言实际
  source provenance 被传递。
- 项目所有者已明确授权登记 `DATA-07 -> TAR-07 -> GOV-02` 三个独立 corrective unit。`DATA-07`
  是当前唯一 repository focus；后两项保持 `waiting_dependency`，不得并行扩展代码，也不得混成一个提交。
- DATA-07 仅允许修改 Data Center provider-path 测试、对应结构化 evidence 及本计划/README/registry 回写。
  它不修改生产 adapter、provider、freshness、publication 或运行时行为，不连接生产、不调用外部数据源、
  不执行 backfill/部署/推送。exit gate 是原失败用例、相关 provider adapter 回归、治理与注册表勾稽全部通过。

## 151. 2026-09-01：DATA-07 fixture contract repository exit

- fake quote 现在显式提供正式 DTO 的 `source="eastmoney"`，并断言 Application 输出的 `source` 与
  `extra.actual_source` 均保持该 provenance。Sol/Luna 审查确认正式
  `AKShareEastMoneyGateway.get_quote_snapshots()` 返回 `list[QuoteSnapshot]`，两条正式构造路径都提供
  `source`，因此没有用 `getattr` 放宽生产 adapter 的类型边界。
- 原失败文件与同类 provider adapter 组合回归 `40 passed`；Ruff、Black、isort、active plan registry
  和 governance consistency 全绿。结构化证据为
  [`data07-akshare-quote-fixture-contract-closure-evidence-2026-09-01.json`](../testing/data07-akshare-quote-fixture-contract-closure-evidence-2026-09-01.json)，
  SHA-256=`13f91dc5d9a387bffe5549ac5d098d7f4680efcfa0fdddbc5530fffabd032b78`。
- DATA-07 只关闭候选 CI 的 Data fixture blocker，不宣称整条候选 CI 已绿；TAR inventory/HTTP ownership
  与 documentation route parser 仍由 `TAR-07`、`GOV-02` 分别关闭。无生产读写、外部网络、部署、push、
  runtime enablement 或生产结论。唯一 repository focus 已晋级 `TAR-07`。
