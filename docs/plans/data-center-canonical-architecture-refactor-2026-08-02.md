# 数据中台唯一真源与数据可靠性架构重构计划（2026-08-02）

> 状态：实施中（M0-M4 控制面、D0/D1/D4-D7 本地关键消费者和 D2/D3/D8-D9 的本地 Publication-only 端口已收口；D4-D9 published Query Port 与 REST 已增加同一 Publication 的 member-bound fact_pk 过滤；Dataset Catalog/owner registry 已持久化并可幂等初始化，Provider×dataset health 和 A-share composite publication gate 已接入；本地 PostgreSQL 空库迁移图已验证；生产观察窗口、PostgreSQL 生产预算/M9-M10 尚未完成）
> 级别：架构级 / 数据级 / 生产级重构  
> 适用版本：0.8.0 之后的下一条独立主线  
> 目标：所有外部事实数据及所有业务计算输入统一经过 Data Center；系统只有一个可发布的数据真源、一套可靠性语义和一条可审计的数据链路，并能在生产默认 90 GiB、运行时可调整的容量策略下持续运行  
> 执行原则：先阻断错误数据，再建立契约；先扩展后切换；先影子对账再退役旧链；禁止长期双写  

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
- D4/D5 Equity 读取改为只走 canonical FinancialFact/ValuationFact/PriceBar；旧 `FinancialDataModel`、`ValuationModel`、`StockDailyModel` 仅保留模型、历史迁移、冻结 Admin 和迁移期测试用途，新增 legacy-fact access guard 阻断业务新增读写。
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
| [data-mid-plat-260405.md](data-mid-plat-260405.md) | 保留为第一阶段建设历史；其中“Phase 1-6 已完成”只代表骨架和主要入口曾完成迁移，不再作为唯一真源验收证据 |
| [production-data-reliability-full-remediation-2026-08-01.md](production-data-reliability-full-remediation-2026-08-01.md) | 继续承担生产事故 P0/P1/P2 整改；其维护阻断、时间保真、全市场回填和无证据阻断是本计划的前置安全底座 |
| [provider-abstraction-convergence-2026-07-18.md](provider-abstraction-convergence-2026-07-18.md) | Provider 抽象治理并入本计划 M2，不再只以文件拆分或协议存在作为完成标准 |
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
- 将 shared/domain/reliability.py 收敛为 Data Center 可复用的纯 Domain 契约，或明确 shared 只保存技术中立基础类型；全仓只保留一个 ReliabilityStatus 定义。
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
- [ ] PostgreSQL 备份、恢复和 rollback drill 有真实证据。
- [ ] 整盘、PostgreSQL、WAL、Docker、Redis、Raw、备份和日志纳入同一 active StorageBudgetPolicy 水位控制。
- [ ] Retention、Rollup、Archive、Hold 与 StoragePressureGuard 实际运行并通过故障注入。
- [ ] VPS 不保留超过 1 份或 24 小时的完整数据库备份。

### 22.5 消费者

- [ ] macro、regime、pulse、equity、alpha、factor、valuation、realtime、fund、sector、rotation、hedge、sentiment、backtest、account、portfolio、agent_runtime 等均完成迁移。
- [ ] REST、SDK、MCP、Terminal、TUI 同一事实的 publication_id 和 reliability 一致。
- [ ] 旧表、旧 Adapter、旧 Bridge、旧 task 和旧 fixture 已删除。

### 22.6 测试与治理

- [ ] current-data 与 Celery manifest 中的 pytest nodeid 在 CI 实际执行。
- [ ] 核心链路在 PostgreSQL 通过。
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
