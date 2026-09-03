# 生产数据可靠性完整修复与测试计划（2026-08-01）

> 历史实施状态（2026-08-01）：本地代码、迁移、治理契约和专项回归已完成；当时待提交、CI、生产备份、维护态切换、全量回填和生产验收。生产步骤完成前不得勾选 P1/P2 的上线验收项。
> 历史综合快照（截至 2026-08-31）：[`release-blocker-closure-execution-plan-2026-08-29.md`](release-blocker-closure-execution-plan-2026-08-29.md) 当时记录 `DATA-01` 已关闭、successor 上 PostgreSQL client 已耗尽，`DATA-04/05` repository 修复已完成但尚未部署，`DATA-02/03` 继续 fail-closed；该段不代表当前部署状态。
> 当前状态（2026-09-03）：registry v41 已确认 `DATA-04/05/06/07/08/09` repository closure 完成；候选 `aa7127ff4d9f71555b0d0486314da5518bd2ac20` / release `20260901232812` 已部署。`DATA-02` 仍为 `DENY`/`awaiting_production`，只读 dry-run 不写生产；`DATA-03` 继续依赖阻断。当前决策使用、回填/publication 切换和 owner 授权仍未通过。

## 1. 背景与问题定义

本计划源于对生产 MCP、Terminal Agent、数据中心、行情、估值、财务、宏观、轮动、对冲与 readiness 链路的专项核验。当前最严重的问题不是单个接口缺数据，而是系统允许以下状态同时存在：

- 数据源有新数据，但生产库覆盖率仅约 5.7%。
- 历史行情的源观测时间被请求时间覆盖，旧值被包装成“实时”。
- MCP 未命中工具时回退为通用聊天，模型可生成无证据价格、日期和来源。
- `/api/ready/` 只证明服务可用，不能证明投资决策数据可用。
- provider 健康度可在能力长期无成功、表为空时继续显示 healthy。
- 当前数据治理清单有静态登记，但部分测试证据不是可直接执行的 pytest nodeid，AST 门禁也漏掉了 snapshot 时间戳洗白。

以通富微电（002156.SZ）为代表的生产现象如下：上游 Tushare 中继已能返回 2026-07-31 行情、估值以及截至 2026Q1 的财务数据，但生产库只有最新价，历史、估值指标、财务、新闻和资金流均缺失；普通 MCP 路由没有检索到任何能力，随后由大模型生成了互相矛盾的旧价格、虚构的“交易所 Level-1 直连”来源和错误的新鲜度结论。这类结果不可用于金融决策。

## 2. 修复目标与验收原则

本次采用一次性生产切换，不以长期灰度方式释放不完整能力。站点在数据重建期间保持服务可用，但所有面向投资决策的入口进入维护阻断状态。

完成标准：

1. 任意 `current`、`latest`、`realtime`、`summary` 响应都保留真实源观测时间，并明确发布可靠性结论。
2. 无可靠证据时，系统稳定拒绝给出决策结论，不得由聊天模型补造价格、时间、来源、财务或估值。
3. MCP 接入页提供的地址能够正确处理中文证券名称、代码及“查询所有信息”等表达。
4. 活跃 A 股的行情、估值和财务核心数据完成全量覆盖；新闻与资金流采用受能力约束的按需/分层覆盖并明确披露。
5. `/api/ready/` 继续表示基础服务可用；新增严格的 decision readiness 表示数据是否可用于决策。
6. 数据重建、部分失败、零产出和阻断都具备规范化 Celery outcome、断点和可审计证据。
7. CI 能阻止时间戳洗白、虚假 current、缺失可靠性字段、不可执行测试证据和未登记关键任务再次进入主线。

### 2.1 生产证据采集与授权边界

`DATA-01/02/03` 不因进入 production 阶段而停止代理推进。代理应自动下载并校验已有生产备份、执行隔离 restore/rebuild、计算 RTO、盘点 schema/row/freshness/coverage、运行只读 reconciliation、分别探测 service readiness 与 decision readiness、跟踪 observation/candidate drift，并把原始来源时间、hash、候选身份和失败原因写入可复核报告。任何字段未知都保持 unknown/blocked，不得补造成功。

只有创建或清理远端备份、生产回填/删除/纠正、修改维护态、部署/切换和 live rollback 需要精确授权；容差例外、数据源取舍和解除维护由 owner 决定。授权动作完成后，其后置核验继续自动运行。若缺少机械 collector，应在对应 DATA unit 内补 collector 和回归，而不是把计划标成外部等待。

## 3. 统一可靠性契约

建立跨 API、SDK、MCP、Terminal 和内部服务共用的 `ReliabilityContract`。所有面向决策的数据面至少发布：

| 字段 | 语义 |
| --- | --- |
| `status` | `fresh / stale / missing / partial / conflict / maintenance / failed` |
| `observed_at` | 数据源实际观测时间，禁止用请求或序列化时间代替 |
| `fetched_at` | 系统抓取时间，只用于追踪传输和缓存延迟 |
| `source` | 实际数据来源及能力标识 |
| `freshness` | 基于交易日历和数据类型阈值计算的新鲜度结果 |
| `reliability` | 覆盖、完整性、冲突和来源健康度汇总 |
| `must_not_use_for_decision` | 是否禁止用于决策 |
| `block_reason_code` | 稳定、机器可读的阻断原因 |
| `block_reason` | 面向用户的阻断说明 |

约束：

- `latest` 只表示排序最新，不等于 `fresh`。
- `observed_at`、`snapshot_at`、`bar_date`、`as_of` 必须沿调用链保持不变。
- failover 得到非空但过期的数据时必须继续尝试后续来源。
- 顶层 `reliable=true` 不得掩盖任一关键组件缺失、过期或冲突。
- maintenance、missing、stale、conflict、failed 状态必须默认 fail closed。

## 4. 实施主线

### 4.1 决策维护状态与双 readiness

增加可持久化、可审计的决策维护状态，而不是依赖进程内变量：

- 状态：`active / maintenance / validating / blocked`。
- 字段：原因、操作者、开始时间、预期结束时间、变更时间、关联任务或发布版本。
- 维护期间站点和 `/api/ready/` 保持可用；MCP、Terminal、SDK 和决策 API 返回 `maintenance` 可靠性状态并拒绝投资结论。
- 保留 `/api/ready/` 作为负载均衡和运维基础可用性检查。
- 新增 `/api/decision-ready/`，严格检查维护状态、核心覆盖、关键 provider 能力、新鲜度、跨源冲突和关键业务面。
- 决策 readiness 失败时返回非 2xx 或明确的 unhealthy 状态，便于监控告警和发布门禁使用。

### 4.2 行情观测时间保真与只读语义

修复行情链路中的时间戳洗白：

- Tencent 等 gateway 返回的 `fetched_at / observed_at` 必须传递到实时价格对象和持久化快照。
- `QuoteSnapshot` 同时存储源观测时间和抓取时间；迁移时不推断旧脏数据为可靠观测。
- 历史日线使用 `trade_date/bar_date`，不得由 `timezone.now()` 包装成实时数据。
- GET 查询不得隐式持久化外部行情；读路径只读，缓存填充和数据写入改由显式命令或后台任务承担。
- 使用交易日历判断周末、节假日和最近已完成交易日，避免把周五收盘在周六误判为 stale，也避免把周六请求时间伪装成新行情。
- 对现存已污染的 `QuoteSnapshot` 在生产切换时全部删除并从可信来源重建。

### 4.3 MCP 个股全景查询与无证据阻断

增加面向用户任务的复合能力 `equity.read.research_snapshot`，接受证券名称、代码或别名，输出：

- 证券身份与代码解析证据；
- 最新可信行情和源观测时间；
- 历史行情覆盖区间；
- 估值指标及数据日期；
- 财务指标、报告期和披露期；
- 可用的资金流、新闻与事件；
- 每个分区的来源、新鲜度、缺失项和可靠性；
- 汇总 `must_not_use_for_decision` 与稳定阻断原因。

路由和生成约束：

- 中文名称、证券代码、“所有信息/全部信息/完整信息/全面分析”等表达必须进入证券研究能力检索。
- 低风险只读能力不要求额外确认；写操作和高风险计算仍保持权限与确认。
- 检索为空、工具失败、超时、401/403、关键证据缺失时，不允许回退到自由生成金融事实。
- 模型只能基于结构化 tool evidence 进行摘要；价格、日期、来源、估值、财务等事实必须能回溯到工具字段。
- 不得声称系统未提供的“交易所直连”“实时 Level-1”等来源。
- 针对同一问题的 MCP、Terminal Agent、SDK 和 REST 结果必须共享同一可靠性结论。

### 4.4 活跃 A 股核心数据全量回填

覆盖口径为生产激活的完整 A 股 universe，而非仅自选股或少量基准证券。

核心数据：

- 行情：证券身份、交易日线、最新已完成交易日快照。
- 估值：`daily_basic` 等可用估值指标。
- 财务：利润表、财务指标及报告期元数据。

分层数据：

- 新闻与资金流在 provider 能力、配额和历史可得性约束下按需/分批拉取。
- 无法全市场覆盖时不得将其计入核心 readiness 通过条件，但个股响应必须明确披露 `missing/unsupported`。

任务设计：

- 采用批量、幂等、可恢复的 Celery 编排；支持按市场、代码区间和 checkpoint 续跑。
- 每个任务校验边界参数，发布 `success / partial / noop / blocked / failed`。
- 统一记录 `requested / succeeded / failed / stored`，并保证计数单位一致。
- 部分失败不得显示成功；全部失败必须 `outcome=failed`；零写入必须解释原因。
- 限流、退避、超时、失败样本、最后成功时间和 provider 能力级健康度可观测。
- 使用 bulk write 和合理批次，避免 5,000+ 证券造成 N+1、长事务或内存峰值。

### 4.5 Provider 健康度与覆盖质量

provider 健康度从“连接可用”升级为能力级状态：

- 分别记录 identity、daily、daily_basic、income、fina_indicator、news、capital_flow 等能力。
- 同时考虑最近成功时间、最近失败、连续失败、产出条数、覆盖率和数据日期。
- 表为空、长期未成功或返回零产出时不得显示 healthy。
- 主源 stale/missing 时继续 failover；跨源偏差超过容差时进入 conflict 并告警，不能静默选择。
- 生产数据中心展示核心覆盖率、缺失证券数、最老/最新观测日期和回填进度。

### 4.6 宏观与其他决策面的统一收口

- 修正 regime/pulse 中使用计算时间替代源观测时间的问题。
- 统一 rotation、market summary 等交易日 freshness 规则。
- 对 sector、hedge、policy 等已有 stale/missing 阻断继续保留，并迁移到统一契约。
- 宏观 529 组 canonical/legacy 冲突需要可解释归并；总成交额约 37.47% 的跨源冲突维持 governed source 并生成告警证据。
- 任一组合响应中的部分数据不得由顶层可靠标记洗白。

## 5. 生产切换与回滚流程

一次性切换按以下顺序执行：

1. 在部署前启用决策维护状态；确认普通站点仍可访问，所有决策入口被阻断。
2. 使用 PostgreSQL custom format 创建生产备份，下载本地并校验远端/本地 SHA-256 一致。
3. 记录当前镜像、Git SHA、迁移状态和数据库行数，形成回滚基线。
4. 部署新代码，运行 migration、collectstatic、Django deploy check 和基础 `/api/ready/`。
5. 删除全部现存 `QuoteSnapshot` 脏数据；只删除计划明确授权的快照表，不触碰历史日线、财务、估值等其他表。
6. 执行全活跃 A 股身份、行情、估值和财务回填，按 checkpoint 持续追踪失败样本并重试。
7. 运行覆盖、时间戳保真、跨源一致性、MCP 全景查询和严格 decision readiness 验收。
8. 验收全部通过后退出维护状态；任一硬门禁失败则保持阻断并回滚代码或数据库。

回滚点：

- 代码：上一生产镜像和 Git SHA。
- 数据：已验证 custom-format PostgreSQL 备份。
- 状态：维护模式保持 fail closed，避免回滚过程中发布不完整结论。
- 恢复后重新运行基础和决策 readiness，不以容器启动成功作为恢复完成。

## 6. 测试矩阵

### 6.1 单元测试

- 源观测时间、抓取时间、交易日期分别保留。
- 周末/节假日/latest completed session 判定。
- fresh、stale、missing、partial、conflict、maintenance、failed 全状态。
- stale 主源继续 failover；偏差超阈值不静默切换。
- 中文名称、代码、别名和“全部信息”路由。
- 工具无结果、超时、401/403 时禁止生成金融事实。
- Celery 非法输入、全成功、部分失败、全部失败、零产出、业务阻断。

### 6.2 数据库与集成测试

- QuoteSnapshot migration、唯一性、索引和时区感知。
- GET 行情端点前后数据库行数不变。
- 显式同步任务幂等，重复执行不制造重复记录。
- 批量任务 checkpoint 可恢复，计数与真实写入一致。
- decision maintenance 在多进程/重启后仍生效。
- readiness 查询数和响应时间具备上限，避免全表扫描阻塞探针。

### 6.3 MCP/SDK/Terminal 契约测试

固定问题：

> 使用这个金融分析 MCP，查询关于通富微电的所有信息。

至少验证：

- MCP 接入页地址、SDK、Terminal Agent 和 REST 的证券身份一致。
- 最新价格与上游可信数据一致，`observed_at` 为真实源时间。
- 历史、估值、财务的覆盖与报告期一致。
- 新闻/资金流缺失时明确标注，不补造。
- 删除/禁用工具证据后，所有入口返回稳定阻断，不出现任意价格或虚构来源。
- 同一输入重复运行，事实字段稳定且可追踪。

### 6.4 全市场数据验收

- universe 数量达到治理下限，并与激活证券清单一致。
- 核心覆盖率默认要求 100%；因停牌、新股、退市边界等确有不可得情况时必须登记可审计例外，而不是降低分母。
- 无无效 OHLC、非正收盘价、未来日期、重复自然键、空证券名称。
- 估值全空、财务报告期异常、时间戳晚于抓取时间等均为硬失败。
- 对随机样本、边界证券和通富微电执行上游对账。

### 6.5 性能与故障注入

- MCP 个股全景查询、行情摘要和 decision readiness 设定 P95/超时预算。
- provider 超时、限流、返回空集、返回旧数据、字段漂移和部分批次失败。
- Redis/Celery 不可用、数据库只读、任务重启和重复投递。
- 5,000+ 证券回填的批次内存、数据库锁、事务时长和连接占用。

## 7. CI 与防复发门禁

- 更新 `governance/current_data_contracts.json`，登记所有新增/修改 current 数据面及 stale、fresh、fallback、observation-preservation 证据。
- 更新 `governance/celery_task_contracts.json`，登记全量回填和维护/校验任务。
- 强化 AST 门禁：识别 snapshot、quote、bar、history 等命名下用 `timezone.now()`、`datetime.now()` 覆盖源观测时间的模式。
- CI 必须直接执行治理清单中的完整 pytest nodeid；不再仅按函数名做存在性扫描。
- 增加 GET 只读副作用门禁、可靠性字段 schema 测试和模型自由生成禁令测试。
- 将通富微电全景查询加入生产 smoke/canary；价格不写死，按上游证据及时间戳一致性验收。
- 每日运行核心覆盖、新鲜度、provider 能力和决策 readiness 审计；失败自动阻断决策入口并告警。
- 固定运行 terminal/TUI/MCP/SDK/deploy 最小回归包和 Django migration/deploy checks。

## 8. 提交与交付切分

虽采用一次性生产发布，代码仍按可验证主题拆分提交：

1. `docs`: 本计划与验收口径。
2. `fix`: 观测时间保真、QuoteSnapshot schema 和 GET 只读。
3. `feat`: 统一可靠性契约、维护状态和双 readiness。
4. `fix`: MCP 证券研究路由、全景能力和无证据阻断。
5. `feat`: 全市场核心数据回填、checkpoint 与 provider 能力健康度。
6. `test/chore`: 治理清单、AST/CI 门禁、回归和生产 smoke。

所有提交合并后统一 push、盯 CI，CI 全绿后才进入备份和生产切换。

## 9. 阶段完成定义

### P0：不再发布虚假当前数据

- [x] 时间戳不再洗白。
- [x] GET 无隐式写入。
- [x] 无工具证据时 MCP/Agent fail closed。
- [x] 维护模式与 strict decision readiness 可用。

### P1：核心数据可完整支撑个股查询

- [ ] 活跃 A 股行情、估值、财务完成全量回填。
- [x] 个股全景能力在四个入口行为一致（2026-08-08：Equity Application 唯一归并；2026-08-14 在 Django 5.2.12 复跑 API/SDK/MCP/Agent 组合 `77 passed`，四入口实现与 runtime contract 均通过）。
- [ ] provider 能力健康度、覆盖和告警生效。

### P2：防复发与生产验收闭环

- [x] 治理清单、可执行 nodeid、AST 和副作用门禁生效。
- [ ] 全市场质量、性能、故障注入和固定样例测试通过。
- [ ] 生产备份、部署、重建、验收、解除维护或回滚流程实际演练完成。

本地已验证证据：

- 专项可靠性、MCP/SDK、provider、回填和治理单元测试：127 项通过。
- readiness、维护态、清理命令、实时链路与数据中心组件/API：71 项通过（首次发现并修复实时 fallback 缺失 `fetched_at`，针对性复测通过）。
- 实时实体、Redis 缓存、轮询、个股盘中仓储与 freshness 扩展回归：62 项通过。
- 固定最小回归包：TUI 246 项、Terminal/SDK/SSL 41 项通过。
- Django system check、迁移漂移检查、Ruff、Black、架构扫描、增量 mypy、当前数据 24 个 surface 契约和 12 个 Celery 任务契约通过。

### 2026-08-14：正式 Django runtime contract 复跑

- API：`python -m pytest tests/api/test_equity_research_snapshot_api.py -q --reuse-db --no-migrations`，`15 passed`。
- SDK/MCP/routing/evidence：`sdk/tests/test_sdk/test_equity_module.py`、`sdk/tests/test_mcp/test_equity_research_snapshot_registry.py`、`tests/unit/test_ai_capability/test_equity_research_routing.py`、`tests/unit/test_mcp_evidence_output_surfaces.py`，`36 passed`。
- Use case/gateway：`tests/unit/equity/test_research_snapshot_use_case.py`、`tests/unit/test_ai_capability/test_mcp_runtime_gateway_security.py`，`26 passed`。
- 合计 `77 passed`。这些用例使用 mock/fake 或 no-migrations 隔离环境，证明软件边界、路由一致性与 fail-closed 行为；不证明真实生产数据覆盖、PostgreSQL 规模/故障注入、owner definition、备份恢复或 readiness 解锁。

## 10. 明确非目标

- 本次不把新闻和资金流伪装成已实现的全市场历史覆盖。
- 不以降低 freshness/coverage 阈值换取 readiness 通过。
- 不用模型常识或搜索结果填补系统数据缺口。
- 不把基础服务存活等同于数据可用于投资决策。
- 不在未完成备份、维护阻断和回滚基线前删除生产快照。

## 实施记录（2026-08-15，DATA-01 production backup evidence）

本批次只完成 DATA-01 的生产备份子步骤；没有进入维护态，没有执行 destructive migration、回填、切读或清理旧链。

- 运行 `scripts/backup-vps-postgres.ps1` 成功创建并下载 PostgreSQL custom-format 归档。
- 远端归档：`/opt/agomtradepro/backups/database/postgres-20260815T030811Z.dump`。
- 本地归档：`backups/vps-postgres/postgres-20260815T030811Z.dump`；大小 `139057048` bytes。
- 远端 `pg_restore --list`、下载后的尺寸校验和本地 SHA-256 均通过；SHA-256：`a8f005eb3a461f28d21689ecef6d5aee89b59a353d06944b79e08c82662839cc`。
- 归档目录受 Git ignore 保护，未把生产数据库内容提交进仓库；未执行旧备份清理。

边界保持不变：备份证据不等于恢复演练。维护态切换、restore/rebuild 演练、受控回填与 reconciliation、性能/锁预算和最终解除维护或回滚仍未完成，`DATA-01` 继续保持 `awaiting_production`，不得据此解锁 `DATA-02/03` 或任何破坏性操作。

## 实施记录（2026-08-15，VPS candidate deployment evidence）

在上一候选部署后再次取得恢复点，`dev/next-development@96ce6ee43b06e6eb6ad51528ff8ee783a4bf0952` 已以 release `20260815144517` 部署到 `demo.agomtrade.pro`。本次只使用 `ACTION=upgrade`、`INCLUDE_SQLITE=0`、`WIPE_DOCKER=0`、`WIPE_VOLUMES=0`，保留现有 PostgreSQL/Redis volumes；部署前 custom-format PostgreSQL 备份为 `postgres-20260815-085317.dump`（140079790 bytes，SHA-256 `f72ea2cff4ff2c137425069a404936e6d24ed8a301533f49bdea943d0334535e`）。

- release manifest 为只读 `0444`，image ID `sha256:38c68ff15ed4ce09a0a29b15744ac46c5287a5817f418d97666d96a81ad37839`，OCI revision 与 40 位 source commit 完全一致。
- PostgreSQL migration `account.0037`–`0053`、`verify_canonical_schema`、Data Center catalog、`manage.py check --deploy`、collectstatic、AI capability sync 和 TUI registry publish/check 均通过；web/Celery/Caddy/Redis/PostgreSQL 健康，`pyqlib=0.9.7`，Celery `inspect ping` 为 `1 node online`。
- 公开 health 独立复核返回 `status=ok`。完整机器摘要见 [`docs/deployment/vps-deployment-evidence-2026-08-15.md`](../deployment/vps-deployment-evidence-2026-08-15.md)。

本次标准远端 `git-clone` 构建成功并独立核验 `pyqlib=0.9.7`，但本记录仍不证明全市场数据覆盖、shadow reconciliation、restore/rebuild、维护态回滚或 readiness 解锁。`DATA-02/03`、P1 全量回填和最终生产验收继续保持阻断。

## 实施记录（2026-08-15，latest candidate backup refresh）

最新候选 `dev/next-development@a76db97d4322fd7f6a2323f4f567873e8c53199c` 部署前再次生成并
验证 PostgreSQL custom-format 归档：远端
`/opt/agomtradepro/backups/database/postgres-20260815-093506.dump`，本地
`backups/vps-postgres/postgres-20260815-093506.dump`，大小 `140095243` bytes，SHA-256
`a1e7092aacc1241525ba52a083395f3d38bb0b88c7b8f6436b3ad508f4520bc0`。远端
`pg_restore --list`、SFTP 完整下载、尺寸与本地 SHA-256 均由
`scripts/backup-vps-postgres.ps1 -DownloadLatest` 校验通过；远端 prune 未启用。

这只刷新了 DATA-01 的恢复点，不是 restore/rebuild 或维护态回滚演练；没有执行 destructive
migration、回填、reconciliation、切读或清理旧链。`DATA-01` 继续 `awaiting_production`，
`DATA-02/03` 不因本次备份解锁。

## 实施记录（2026-08-15，latest candidate deployment and backup）

`dev/next-development@ae1e5e532e51b67731563b21b2224372752ee15b` 以 release
`20260815162419` 完成代码-only `-Upgrade` 部署，纳入 Account Physical v2 migration
state 修复（`0054`）和 DATA-02 控制面原子快照修复。远端 git-clone/provenance、迁移步骤、
canonical schema check 与服务启动通过；web healthy，Celery worker/beat、PostgreSQL、
Redis、RSSHub 运行；HTTPS health/ready 均 HTTP 200，Celery ping 为 1 node，TUI
publish/check 与 Qlib `pyqlib=0.9.7` 复核通过。部署报告保存在
`dist/remote-build-reports/remote-build-report-20260815162419.json`。

部署后再次下载并校验 PostgreSQL custom-format 恢复点：
`postgres-20260815-103019.dump`，`140112628` bytes，SHA-256
`46dd5003de2943ac23d8ab599c24454e3e770b7828b088857be355fa4f5a364d`；远端
`pg_restore --list`、SFTP 完整下载、尺寸与本地 SHA-256 均通过。

边界保持不变：`/api/ready/` 的 Alpha/Qlib provider、workspace recommendation 与市场
温度计 freshness warnings 仍存在；本次部署不证明 decision-data gate、TUI 角色化浏览器
UAT、DATA-01 restore/rebuild/维护态回滚、DATA-02 生产回填/coverage/reconciliation，
也不解除 AUD-01 durable publisher/authority/runtime wiring。

同日候选部署身份为 release `20260815152834`、image
`sha256:12c5ce84ecd2d072846bb7777e6e0345e3ed83e98333bdf80ca35108d2a5c385`，health/ready
与服务复核通过；ready 中 Alpha/Qlib 与 workspace freshness warnings 继续按数据合同保留，
不作为 decision-data gate 完成证据。

## 实施记录（2026-08-15，DATA-01 本地 restore/rebuild 尝试）

本批尝试使用已有严格脚本
`scripts/verify_postgres_backup_restore.py` 对部署后归档
`backups/vps-postgres/postgres-20260815-103019.dump` 做本地隔离恢复。脚本的
custom-format 校验、受控 `*_restore_verify_*` 数据库命名、恢复后表行数/内容 hash/规范
schema 与 Data Center migration 对比合同由
`tests/unit/test_verify_postgres_backup_restore.py` `10 passed` 覆盖。

实际恢复没有取得可采信结果：新的 `postgres:16-alpine`/`postgres:18.4` 临时容器均在
`initdb` bootstrap 阶段超时，随后已删除；改用现有本地 home-lab PostgreSQL 仅创建了
专用数据库 `agomtradepro_restore_source_20260815`，归档传输因 Docker Desktop API
长时间无响应超时，未执行 `pg_restore` 或快照比较。专用数据库和临时归档文件随后已按
精确名称清理；未连接或写入 VPS 数据库。

因此本记录只证明“恢复脚本合同可测试、恢复尝试被本机 Docker 阻断”，不产生
restore/rebuild、RTO 或回滚通过证据。`DATA-01` 继续 `awaiting_production`，维护态、
生产恢复/重建、回滚演练、回填和 reconciliation 仍未完成，也不解锁 `DATA-02/03`。

## 实施记录（2026-08-15，当前候选部署后 backup refresh）

当前候选 `dev/next-development@cf68dc1e972ecd6e0ae002e4d4f96ff07ef86542` 部署完成后，
运行 `scripts/backup-vps-postgres.ps1 -DownloadLatest` 下载并复核最新 PostgreSQL
custom-format 归档：

- 远端：`/opt/agomtradepro/backups/database/postgres-20260815-123539.dump`。
- 本地：`backups/vps-postgres/postgres-20260815-123539.dump`，大小 `140176474` bytes。
- 远端 `pg_restore --list`、SFTP 完整下载、尺寸和本地 SHA-256 均通过；SHA-256：
  `e1c0821543a36f19d2ea292d9c4fdc544003010579ccef5df9175d083a2e2e2f`。
- 远端 prune 未启用，未执行任何恢复、回填、切读或 destructive migration。

这只新增恢复点证据，不等于 restore/rebuild、RTO/RPO、维护态 rollback 或 reconciliation。
由于本机仍缺少 `pg_restore`/`psql` 客户端且此前 Docker 本地恢复链路超时，`DATA-01` 继续
`awaiting_production`，不解锁 `DATA-02/03`。

## 实施记录（2026-08-15，DATA-01 只读源快照与恢复工具链修复）

本批通过 VPS SSH 在 web 容器内以 `REPEATABLE READ READ ONLY` 取得生产源库快照：
public schema 共 `536` 张表，Data Center migrations `71` 项，schema 指纹为
`9306657014b2861f1095e2f4132f37074ebf7c0debb79d95d6d98d0d1c4291ab`；快照只读，
没有执行任何生产写入。随后用归档
`backups/vps-postgres/postgres-20260815-123539.dump` 在本机 home-lab 的临时库做恢复尝试。

恢复链路的两个实际限制已定位：从 stdin 使用 `pg_restore --jobs=4` 会被 PostgreSQL
明确拒绝（parallel restore from standard input is not supported）；改为单 worker 后，
Docker Desktop 上的 restore 进程超过 10 分钟仍未完成，隔离数据库随后由维护连接终止并删除；
另一次 `docker cp` 归档传输也因 Docker API 长时间无响应被停止。所有临时数据库均以
`agom_restore_verify_*` 前缀清理，未连接或写入 VPS。

为消除“主机没有 libpq 客户端”这一工具层阻断，`scripts/verify_postgres_backup_restore.py`
现在提供显式 `--pg-restore-container <image>` 后端：使用短生命周期 `.pgpass` 挂载，
密码不进入 Docker 参数；默认 host `pg_restore` 行为不变。契约回归由
`tests/unit/test_verify_postgres_backup_restore.py` `12 passed` 覆盖，但尚未取得实际
Docker restore/snapshot match，因此 `DATA-01` 仍为 `awaiting_production`，不解锁
`DATA-02/03`，也不宣称 RTO/RPO 或 rollback 证据完成。

## 实施记录（2026-08-15，DATA-02 control-plane atomic snapshot）

回填任务的 run、batch、checkpoint 现在由 Data Center composition root 在同一事务中提交；Application task 不直接持有 Django transaction。新增故障注入组件测试证明 checkpoint 持久化失败时三张控制面表全部回滚（`2 passed, 2 skipped`），任务单元 `8 passed`；architecture、增量 mypy、Celery contract、Black/isort 和 diff-check 均通过。

这只是本地控制面原子性证据，不是 PostgreSQL 并发/锁预算、生产回填、coverage/reconciliation 或 DATA-01 维护态/恢复演练。`DATA-01` 仍为 `awaiting_production`，因此 `DATA-02/03` 继续锁定。

## 实施记录（2026-08-15，当前候选部署后 backup refresh 20:07）

当前候选 `dev/next-development@11594964f589c5f0ec3bf6a541d61d471b79b67f` 部署后，
再次运行 `scripts/backup-vps-postgres.ps1 -DownloadLatest` 并完成远端与本地校验：

- 远端：`/opt/agomtradepro/backups/database/postgres-20260815-141446.dump`。
- 本地：`backups/vps-postgres/postgres-20260815-141446.dump`，大小 `140206603` bytes。
- 远端 `pg_restore --list`、SFTP 完整下载、尺寸和本地 SHA-256 均通过；SHA-256：
  `d3134e5c5551ec92c77724b6567d5db788e59129a3ca799ab0be9cfdad122249`。
- 远端 prune 未启用，未执行恢复、回填、切读或 destructive migration。

本条只新增一个可验证恢复点，不等于 restore/rebuild、RTO/RPO、维护态 rollback 或
reconciliation。由于本机隔离恢复仍受 Docker/客户端工具链约束，`DATA-01` 继续
`awaiting_production`，不解锁 `DATA-02/03`。

## 实施记录（2026-08-15，当前候选 backup refresh 失败）

针对当前候选 `dev/next-development@45281620a8739ee666a1b20e6c6511c0b8101111`，再次尝试
`scripts/backup-vps-postgres.ps1 -DownloadLatest`。远端归档
`/opt/agomtradepro/backups/database/postgres-20260815T154338Z.dump`（`140279578` bytes）
在 VPS 端 `pg_restore --list` 校验通过，但 Paramiko SFTP 在下载约 `4194304` bytes 后
收到 `Server connection dropped`；本地未生成完整归档或 SHA-256，残留 partial 已清理。

该次尝试不计为 backup evidence，也不更新可用恢复点。`DATA-01` 仍为 `awaiting_production`，
restore/rebuild、维护态 rollback、RTO/RPO、回填和 reconciliation 继续锁定。

## 实施记录（2026-08-16，DATA-01 SFTP 断线续传修复与恢复点刷新）

针对上一条在约 `4194304` bytes 处断线的问题，`scripts/backup-vps-postgres.py` 现以
bounded retry 保留 `.partial`，在每次新 SFTP/SSH 会话中从已写入偏移继续读取；只有精确尺寸和
SHA-256 校验后才原子替换目标文件，最终失败会清理 partial。新增断线恢复与重试耗尽测试，
`tests/unit/test_backup_vps_postgres.py` 为 `8 passed`，脚本 `py_compile`、Black、isort 和
`git diff --check` 均通过（本地环境没有 Ruff 模块）。

在当前候选 `dev/next-development@45281620a8739ee666a1b20e6c6511c0b8101111` 的 VPS 归档上，
重新运行 `scripts/backup-vps-postgres.ps1 -DownloadLatest` 成功：

- 远端：`/opt/agomtradepro/backups/database/postgres-20260815T154338Z.dump`。
- 本地：`backups/vps-postgres/postgres-20260815T154338Z.dump`，大小 `140279578` bytes。
- 远端 `pg_restore --list`、SFTP 完整下载、尺寸与本地 SHA-256 均通过；SHA-256：
  `eddb840c0c15d3041bf29a32471c8b6c03be0bd32a0ccf23d438647c46c2615e`。
- 远端 prune 未启用；本次只读取/下载恢复点，没有 restore、回填、切读或 destructive migration。

这修复并证明了 DATA-01 的“可验证备份下载”子步骤，但不等于 restore/rebuild、RTO/RPO、
维护态 rollback 或 reconciliation。`DATA-01` 继续 `awaiting_production`，不解锁 `DATA-02/03`。

## 实施记录（2026-08-16，VPS 隔离 restore rehearsal）

针对当前候选 `e167ab2fc748e4c93d2622f93fa8cc75442b2bb6` 的部署前归档，在 VPS PostgreSQL
容器内创建受控临时库 `agomtradepro_restore_verify_20260816_01`，以 `pg_restore` 完整恢复，
再由 web 容器按 `verify_postgres_backup_restore.py` 的全表快照合同比较源库与恢复库。归档
`/opt/agomtradepro/backups/database/postgres-20260815-184803.dump`（`140318641` bytes，
SHA-256 `4760a38fdfc7ef8570323cfb5dde92ab01eb933cd60d4f6dd08700fc34772752`）的
`pg_restore --list` 与实际 `pg_restore` 均返回 `0`。

- 恢复库与源库均为 `536` 张 public 表、`71` 项 Data Center migrations；schema SHA 均为
  `4390158a547a52f9c4cefa327b67d65680469b06c18491da65a10cb08a9934ce`。
- 当前源快照仍有 `10` 张表和 `4` 个 sequence 与归档恢复库不同；这是备份创建后生产源继续写入造成的
  live-source drift，不能被写成字节级快照一致。原始摘要保存在
  [`vps-restore-rehearsal-2026-08-16.json`](../deployment/vps-restore-rehearsal-2026-08-16.json)。
- 临时库在成功/失败路径均清理，复核后剩余同前缀临时库为 `0`；没有改动生产数据库、schema、迁移或业务行。

本条证明了 VPS 上实际 restore 与结构/schema 对比链路可运行，但不证明备份时点的内容一致、RTO/RPO、
维护态 rollback 或 reconciliation；`DATA-01` 仍为 `awaiting_production`，不解锁 `DATA-02/03`。

## 实施记录（2026-08-16，当前候选 backup 下载复核）

在不切换 release、不停止服务且不写生产数据库的前提下，再次运行
`scripts/backup-vps-postgres.ps1 -DownloadLatest`，复核当前候选
`e167ab2fc748e4c93d2622f93fa8cc75442b2bb6` 的既有 custom-format 归档：

- 远端：`/opt/agomtradepro/backups/database/postgres-20260815-184803.dump`。
- 本地：`backups/vps-postgres/postgres-20260815-184803.dump`，大小 `140318641` bytes。
- 远端 `pg_restore --list`、SFTP 完整下载、尺寸与本地 SHA-256 均通过；SHA-256：
  `4760a38fdfc7ef8570323cfb5dde92ab01eb933cd60d4f6dd08700fc34772752`。
- 远端 prune 未启用；没有恢复、回填、切读或 destructive migration。

该条只确认 DATA-01 的备份下载/校验子步骤，并与运行摘要
[`vps-runtime-verification-2026-08-16.json`](../deployment/vps-runtime-verification-2026-08-16.json)
保持同一候选绑定；不等于维护态 rollback、RTO/RPO 或 reconciliation。`DATA-01` 继续
`awaiting_production`，不解锁 `DATA-02/03`。

## 实施记录（2026-08-16，reconciliation evidence append-only hardening）

Data Center reconciliation evidence 现在使用 append-only immutable model；repository 以
`create` 写入，并且只接受同一 `evidence_id` 的 exact replay。不同快照不得再通过
`update_or_create` 覆写既有审计记录，而是稳定 fail closed。模型、repository 与 Data Center
architecture guard 聚合回归 `46 passed`，增量 mypy regression 为 `0`，`makemigrations --check`
无漂移。

该条只收紧本地 reconciliation 持久化/重放合同。当前 Django reconciliation DB 用例在本地
全仓测试运行时未取得稳定完成结果，因此不计为数据库 component 证据；生产 PostgreSQL
reconciliation、维护态 rollback、RTO/RPO 与 DATA-01 前置仍未完成，`DATA-01/02/03` 状态不变。

## 实施记录（2026-08-16，control-plane identity reuse guard）

Data Center 的 `SyncRunRepository`、`SyncBatchRepository` 与 `SyncCheckpointRepository`
现在在同一 stable key 重试时先逐字段核对不可变身份，再允许更新状态/计数；若同一
`run_id`、`idempotency_key` 或 cursor identity 被不同 dataset、provider、run 或 checkpoint
重用，立即 fail closed，不再让 `update_or_create` 静默改写控制面身份。并发唯一键插入仍在
savepoint 内处理，只有 exact identity 才允许继续。

- 新增身份重用回归；Data Center control-plane focused `identity_reuse` 通过，增量 mypy
  `0 regressions`，Black/isort/diff-check 通过。
- 该切片仅加强本地回填控制面的 idempotency/identity 合同；未连接生产数据库、未执行
  restore/backfill/reconciliation、未改变 `DATA-01/02/03` 状态，PostgreSQL 锁/并发与生产
  RTO/RPO 证据仍待取得。

## 实施记录（2026-08-16，restore evidence input immutability）

恢复工具现在把归档本身视为不可替换的证据输入：`scripts/verify_postgres_backup_restore.py`
在格式校验前记录 SHA-256，在校验完成和恢复完成后再次核对；归档在任一阶段被替换时分别以
`postgres_backup_changed_during_validation` 或 `postgres_backup_changed_during_restore` fail
closed，并把 before/after digest 写入 evidence JSON。`tests/unit/test_verify_postgres_backup_restore.py`
定向回归 `14 passed`，增量 mypy regression 为 `0`，Black 与 diff-check 通过。

同日按备份流程取得并下载当前 VPS custom-format 归档：

- 远端：`/opt/agomtradepro/backups/database/postgres-20260816-100924.dump`。
- 本地：`backups/vps-postgres/postgres-20260816-100924.dump`，大小 `140804438` bytes。
- 远端 `pg_restore --list`、SFTP 完整下载、尺寸和本地 SHA-256 均通过；SHA-256：
  `06e52b33c637c17cae4c9f0223246e0e09af84254717196d904f67044e7b2cba`。
- 远端 prune 未启用；没有 restore、回填、切读或 destructive migration。

该批完成的是恢复工具的输入工件一致性与新的可验证备份恢复点，不是 restore/rebuild、RTO/RPO、
维护态 rollback 或 reconciliation 通过证据；`DATA-01` 继续 `awaiting_production`，不解锁
`DATA-02/03`。

## 实施记录（2026-08-16，DATA-02 primary-key collision identity guard）

此前的控制面 identity guard 只在 stable natural key 命中时比较身份；当 caller 复用已有
`SyncBatch.batch_id` 或 `SyncCheckpoint.checkpoint_id`、但同时替换自然键时，数据库可能先抛出
原始唯一约束异常，未发布稳定的业务阻断原因。现将 lookup key 与显式 identity 合并为完整的
immutable identity；插入竞争失败后先按自然键、再按模型 primary key 精确复核，任何替换均以
`sync batch/checkpoint identity conflict` fail closed，不覆盖已有状态。

- 新增 batch id 与 idempotency key、checkpoint id 与 batch/cursor 自然键的 collision 回归；
  `tests/unit/data_center/test_control_plane.py`（`--reuse-db --no-migrations`）`12 passed`。
- 生产文件增量 mypy regression `0`，Black/isort、`py_compile` 和 `git diff --check` 通过；
  Ruff 模块未安装，未宣称 Ruff 证据。
- 本 slice 仅加强本地控制面冲突诊断与幂等合同；未连接生产数据库，未执行 restore/backfill/
  reconciliation、维护态 rollback 或 destructive migration。`DATA-01` 仍为
  `awaiting_production`，`DATA-02/03` 状态不变。

## 实施记录（2026-08-16，当前候选 PostgreSQL 备份下载复核）

针对当前候选 `443658d33159dd80a35b3001ae2c8505113e3fff` / release `20260816223921`，重新运行
`scripts/backup-vps-postgres.ps1 -DownloadLatest` 并完成远端格式校验、SFTP 完整下载、尺寸和本地
SHA-256 复核：

- 远端：`/opt/agomtradepro/backups/database/postgres-20260816-164649.dump`。
- 本地：`backups/vps-postgres/postgres-20260816-164649.dump`，大小 `140977814` bytes。
- SHA-256：`297d0dc67eb76ff394e2e6e2367a8ba0bc0a0d7ed90af8ce39d3b9f3d86d93b1`。
- 结构化记录：[`vps-postgres-backup-verification-2026-08-16-2348.json`](../deployment/vps-postgres-backup-verification-2026-08-16-2348.json)。
- 远端 prune 未启用；本次未执行 restore、回填、切读、destructive migration 或 rollback。

该条只确认 DATA-01 的当前恢复点可下载且可校验，不等于 restore/rebuild、维护态 rollback、
RTO/RPO、controlled backfill 或 reconciliation 通过证据。`DATA-01` 继续保持 `awaiting_production`，
不解锁 `DATA-02/03` 或任何破坏性操作。

## 实施记录（2026-08-19，DATA-01 最新恢复点下载与本机隔离 restore）

本批严格停在注册表允许自动收集的只读/隔离证据范围，没有创建或清理远端备份、没有进入
维护态，也没有连接生产数据库执行 DDL、恢复、回填或 rollback。

- `scripts/backup-vps-postgres.ps1 -DownloadLatest` 下载了 VPS 上已有的最新 custom-format
  归档 `/opt/agomtradepro/backups/database/postgres-20260819-044335.dump`；本地文件大小
  `141990139` bytes，SHA-256
  `b9177563a534fbc98951b6f9009814c78b8ebd5534b07509a6a97f80ed9cef0c` 与远端盘点值一致，
  本地 `pg_restore --list` exit `0`，remote prune 仍关闭。
- Windows Docker bind mount 会把临时 `.pgpass` 暴露为 group/world-readable，PostgreSQL 客户端
  因而拒绝密码文件并返回 `fe_sendauth: no password supplied`。恢复工具现把只读 secret mount
  复制到容器内临时路径、`chmod 0600` 后再 `exec pg_restore`；密码仍不进入 argv、日志或报告。
  `pg_restore` 失败报告同时新增 bounded、password-redacted stderr，保持 fail closed；专项回归
  `15 passed`，Ruff、Black、isort 通过。
- 在独立、最终已删除的本机 `postgres:16-alpine` disposable 容器中，使用已下载且重新校验的
  `postgres-20260816-164649.dump` 先建立同归档 source，再运行 canonical verifier 做第二次受控
  restore。证据文件为
  [`data01-local-isolated-restore-2026-08-19.json`](../deployment/data01-local-isolated-restore-2026-08-19.json)：
  `outcome=success`，archive entries `7152`，restore `595.930s`，verification `533.391s`，
  total `1693.029s`；536 张 public 表、71 项 Data Center migration 与 schema SHA
  `4390158a547a52f9c4cefa327b67d65680469b06c18491da65a10cb08a9934ce` 一致，table、migration、
  sequence 的 missing/extra/changed 均为 `0`，归档 restore 前后 SHA 保持
  `297d0dc67eb76ff394e2e6e2367a8ba0bc0a0d7ed90af8ce39d3b9f3d86d93b1`，验证库和容器均已清理。

上述 `595.930s` 只能称为本机 disposable `pg_restore` elapsed，不能冒充生产端到端 RTO/RPO；
最新 2026-08-19 恢复点与本机隔离演练使用的 2026-08-16 归档也分别记录，未伪装为同一候选。
VPS maintenance/writer quiescence、生产规模 restore、`vps-restore.sh` live rollback、受控回填与
reconciliation 仍需精确授权和 owner 验收。因此 `DATA-01` 继续 `awaiting_production`，
`DATA-02/03` 不解锁。

## 实施记录（2026-08-19，DATA-01 当前候选部署前备份与只读观测）

不可变候选 `29cdf14206239c4b36b0d31f07980ef8b5a26855` 的标准 code-only
`-Upgrade` 发布在切换前创建并验证 PostgreSQL/Redis 备份；PostgreSQL custom-format 恢复点为
`/opt/agomtradepro/backups/database/postgres-20260819-073827.dump`，manifest 为
`/opt/agomtradepro/backups/meta/manifest-20260819-073827.txt`。发布为 release
`20260819133110` 后，迁移报告 `No migrations to apply`，canonical schema 返回
`{"missing_migrations": [], "missing_tables": [], "ok": true}`，Web、PostgreSQL、Redis、
Celery worker/beat、Caddy 与 RSSHub 均运行，Web 容器 healthy，Celery ping 为一节点在线。

部署后独立 HTTPS 观测为 health 8/8、ready 3/3 HTTP `200`；readiness 保留行情超过
4 小时阈值的 `must_not_use_for_decision=true` 阻断，以及 `etf_net_flow` stale/degraded
披露。该步骤没有进入维护态、没有执行生产 restore/DDL、live rollback、回填或 reconciliation；
新备份也没有被清理。它补充的是当前候选的恢复点与短窗口运行证据，不是生产 RTO/RPO 或
恢复验收。因此 `DATA-01` 继续 `awaiting_production`，`DATA-02/03` 不解锁。

## 实施记录（2026-08-20，DATA-01 最新已有归档下载与格式复核）

按 `DATA-01` 的 `auto_collect` 范围重新盘点并下载 VPS 上已有的最新 custom-format
归档；没有创建新备份、没有 prune、没有进入维护态，也没有连接生产数据库执行 DDL、恢复、
回填或 rollback。

- 远端归档：`/opt/agomtradepro/backups/database/postgres-20260819-164435.dump`。
- 本地归档：`backups/vps-postgres/postgres-20260819-164435.dump`，大小
  `142059273` bytes。
- 远端脚本先执行 `pg_restore --list`，随后完成 SFTP 下载、尺寸比对和本地 SHA-256
  校验；远端与本地 SHA-256 均为
  `3269f238b1e141de49e723a1f84388c538572d503cd856e0791b735aab8e82a3`。
- 本机 PostgreSQL 18.4 容器再次执行 `pg_restore --list`，exit `0`；远端 prune
  保持关闭。

这条记录刷新了 DATA-01 的可复核恢复点，但不等于生产规模 restore、RTO/RPO、维护态
rollback、回填或 reconciliation。既有 2026-08-19 隔离 restore 证据仍绑定另一份
2026-08-16 归档；`DATA-01` 继续 `awaiting_production`，`DATA-02/03` 不解锁。

## 实施记录（2026-08-20，DATA-01 备份证据采集器合同）

本地新增 `scripts/backup-vps-postgres.py --evidence-output` 可选证据输出：在完整下载、
远端/本地 SHA-256 与尺寸复核之后，记录 custom-format 归档的远端采集时间、归档年龄、
`pg_restore --list` manifest SHA/条数、本地路径和 partial 拒绝标记。证据 JSON 使用
`data-backup-evidence.v1`、规范化 payload SHA-256、原子临时文件替换和同内容幂等重放；
已有不同内容的证据文件不会被覆盖，partial 归档、负年龄、尺寸/hash/manifest 无效均 fail closed。

- `tests/unit/test_backup_vps_postgres.py` focused `10 passed`；Ruff、Black、isort、增量
  mypy、`git diff --check` 均通过。
- VPS 只读交叉验收确认当前归档的远端 `pg_restore --list` exit `0`；但 SFTP 首个
  `1 MiB` 读取耗时约 `59.64s`，完整 `142 MiB` 下载未在本轮完成，故没有生成或宣称
  production `data-backup-evidence.v1`，并清理了本轮产生的临时 partial。
- 本 slice 没有创建、清理或恢复 VPS 备份，也没有写入生产数据库；现有归档与
  `backups/vps-postgres-data01/.postgres-20260819-164435.dump.partial` 均保留原状。

这只是 DATA-01 的本地证据格式与校验合同，不是生产备份新鲜度、restore/rebuild、RTO/RPO、
维护态 rollback、回填或 reconciliation 验收；`DATA-01` 继续 `awaiting_production`，
`DATA-02/03` 不解锁。

## 实施记录（2026-08-20，DATA-01 VPS 最新归档证据）

本批按 `DATA-01` 的自动收集范围，只读取并复核 VPS 上已有归档，没有创建新备份、没有
prune、没有进入维护态，也没有连接生产数据库执行 DDL、恢复、回填或 rollback。

- 远端归档：`/opt/agomtradepro/backups/database/postgres-20260820-110946.dump`；远端
  `pg_restore --list` exit `0`，manifest 为 `7182` entries，manifest SHA-256
  `170ca2cd663bd2f1e0f035807c03282e3f4b6e55a2d92dce93978e93973bc394`。
- 完整 SFTP 下载到 `backups/vps-postgres/postgres-20260820-110946.dump`，远端与本地
  大小均为 `142313231` bytes；远端与本地 SHA-256 均为
  `b3f5893f45b0f8aa316307e709450cace3b5c7798bdbe3976b1920f2670c6773`，partial 被拒绝。
- 结构化 envelope 为
  [`data-backup-evidence-2026-08-20.json`](../deployment/data-backup-evidence-2026-08-20.json)，
  schema=`data-backup-evidence.v1`，content hash
  `a7543e05229dc49cb24c44990f59d62200b8fbdd289f969852c1ef570996a518`；远端采集时间为
  `2026-08-20T10:05:39Z`，归档 mtime 为 `2026-08-20T09:10:50Z`。

这条记录只证明一个新的、可复核的 PostgreSQL custom-format 恢复点及其传输完整性；本机
没有可直接调用的 `pg_restore` 客户端，因此本次本地侧使用脚本完成 SHA/尺寸校验，格式列表
校验以 VPS 容器内 exit `0` 为准。它不等于生产规模 restore/rebuild、RTO/RPO、维护态 rollback、
controlled backfill 或 reconciliation；`DATA-01` 继续 `awaiting_production`，`DATA-02/03`
不解锁。

## 实施记录（2026-08-20，DATA-01 最新归档隔离 restore 验收）

本批在本机新建唯一命名的 `postgres:16-alpine` disposable 容器，先用同一归档预置隔离
source database，再运行 `scripts/verify_postgres_backup_restore.py` 做第二次受控 restore；
没有连接生产数据库、没有触碰 VPS 数据卷，恢复库与容器在证据写入后均已删除。

- 最新归档仍绑定 `/opt/agomtradepro/backups/database/postgres-20260820-110946.dump`，大小
  `142313231` bytes、SHA-256
  `b3f5893f45b0f8aa316307e709450cace3b5c7798bdbe3976b1920f2670c6773`；远端 manifest 为
  `7182` entries，manifest SHA-256 为
  `170ca2cd663bd2f1e0f035807c03282e3f4b6e55a2d92dce93978e93973bc394`。
- 第一次脚本尝试因隔离 source 预置尚未完成而先拍到空 source 快照，结果被明确丢弃；确认
  source 已含 `537` 张表、`data_center_price_bar=2784310` 行后重跑，避免把 harness race
  误记为归档差异。
- 第二次验证 `outcome=success`：`restore_entries=7167`，source/restore 均为 `537` 张
  public 表、`72` 项 Data Center migrations（最新 `0072_note_non_st_price_limit_scope`）、
  `458` 条 sequence；schema SHA 均为
  `f984042ea25fbc7686e2be98df619372133aef7b34d9f78b516a39caf53c6049`，table/migration/
  sequence/schema 差异全部为 `0/false`。隔离 `pg_restore` elapsed `2061.820s`，全表
  verification `1017.837s`，总耗时 `4866.916s`。
- 精简证据见 [`data01-local-isolated-restore-2026-08-20.json`](../deployment/data01-local-isolated-restore-2026-08-20.json)，
  完整 verifier report SHA-256 为
  `bf0bf9abd047054147f56be4c4233ec921c0abfc9f5ddf585c5dc79668530300`。

该条补齐的是“最新恢复点的本机隔离 restore/rebuild 自洽证据”，`2061.820s` 与
`4866.916s` 不能冒充生产 RTO/RPO；仍未执行 VPS maintenance、生产 restore/DDL、live
rollback、controlled backfill 或 reconciliation。`DATA-01` 保持 `awaiting_production`，
不解锁 `DATA-02/03` 或任何破坏性操作。

## 实施记录（2026-08-21，DATA-01 最新已有归档只读取证）

按 `DATA-01` 的 `auto_collect` 范围下载并复核 VPS 上已有的最新 custom-format 归档；本批
没有创建新备份、没有 prune、没有进入维护态，也没有连接生产数据库执行 DDL、restore、
回填或 rollback。

- 远端归档：`/opt/agomtradepro/backups/database/postgres-20260820-205307.dump`；远端
  `pg_restore --list` exit `0`，manifest `7182` entries，manifest SHA-256
  `aed4ea9f2591bea50d627de239e0b9ab31eb68e307bcd89f0814c236a912e890`。
- 完整 SFTP 下载到 `backups/vps-postgres/postgres-20260820-205307.dump`，远端与本地
  大小均 `142314979` bytes；远端与本地 SHA-256 均为
  `296311187d72cf6d327be61de55db3205fe139accdef05035c0ec2ed1b9980ac`，partial 被拒绝。
- 结构化 envelope 为
  [`data-backup-evidence-2026-08-21.json`](../deployment/data-backup-evidence-2026-08-21.json)，
  `schema=data-backup-evidence.v1`，content hash
  `3a59ff4608736a7445b9961020e78b0625c0924e7f2032d2c50a68200ac32e3a`；远端采集时间为
  `2026-08-20T20:28:39Z`，归档 mtime 为 `2026-08-20T18:53:58Z`。
- 下载后的归档在 disposable `postgres:16-alpine` 容器内再次执行 `pg_restore --list`，
  exit `0`；本地非注释 manifest 行计数为 `7167`，只作为格式自洽复核，不冒充完整隔离
  restore/RTO/RPO。

这条记录刷新了一个可复核的生产恢复点和传输完整性，但不等于生产规模 restore/rebuild、
RTO/RPO、维护态 rollback、controlled backfill 或 reconciliation；`DATA-01` 继续
`awaiting_production`，`DATA-02/03` 不解锁。

## 实施记录（2026-08-22，DATA-01 VPS 新建备份与结构化证据）

本批按已授权的生产备份范围运行仓库备份流程，创建一个新的 PostgreSQL custom-format
恢复点并下载到本地；未 prune 远端旧归档，未进入维护态，也未执行生产 restore、DDL、回填或
rollback。

- 远端归档：`/opt/agomtradepro/backups/database/postgres-20260821T195155Z.dump`；远端
  `pg_restore --list` exit `0`，manifest `7204` entries，manifest SHA-256
  `e761f7d394605238509885d28e8536c6115d1528c5b8a1c261dd929d753886b4`。
- 完整下载到
  `backups/vps-postgres/postgres-20260821T195155Z.dump`；远端与本地大小均
  `142507268` bytes，远端与本地 SHA-256 均为
  `8aadc5e9aff1f50c142b03dd219153c01b25d5110533195ec3670de36e44157e`，partial 归档被拒绝。
- 结构化 envelope 为
  [`data-backup-evidence-2026-08-22.json`](../deployment/data-backup-evidence-2026-08-22.json)，
  `schema=data-backup-evidence.v1`，content hash
  `4942f47d84dd52a18b5b7f7aabf1ab589f52150f51f1bfe0ac6ee0b689c05d5a`；采集时间、归档 mtime、
  远端/本地 hash、尺寸与 manifest 均封存于 envelope。

这条记录完成 DATA-01 的“新建并验证下载”子步骤，但不等于生产规模 restore/rebuild、RTO/RPO、
维护态 rollback、controlled backfill 或 reconciliation。`DATA-01` 继续 `awaiting_production`，
`DATA-02/03` 不解锁；下一步仍需在明确维护窗口内完成受控恢复/回滚演练及 owner 验收。

## 实施记录（2026-08-22，DATA-01 最新归档本机隔离 restore 验收）

本批没有连接生产数据库。为验证新恢复点可被完整恢复，在本机创建唯一命名的 disposable
`postgres:16-alpine` source 容器，将同一 custom-format 归档预置为 source，再由
`scripts/verify_postgres_backup_restore.py` 创建受控 restore 数据库执行第二次 `pg_restore`、
Repeatable Read 全表快照和 schema/迁移/sequence/逐表内容比较；restore 数据库和 source 容器
均在报告生成后清理。

- 归档绑定 `/opt/agomtradepro/backups/database/postgres-20260821T195155Z.dump` /
  `backups/vps-postgres/postgres-20260821T195155Z.dump`，大小 `142507268` bytes，SHA-256
  `8aadc5e9aff1f50c142b03dd219153c01b25d5110533195ec3670de36e44157e`；pg_restore client 为
  `postgres:16-alpine`，restore entries `7189`。
- `outcome=success`：source/restore 均为 `539` 张 public 表、`72` 项 Data Center migrations、
  `460` 条 sequence；schema SHA、逐表 row/content hash、migration 与 sequence 差异全部为 `0`
  （`missing/extra/changed=false/0`）。restore `1144.211s`、verification `945.14s`、total
  `3358.717s`。
- 完整报告见
  [`data01-local-isolated-restore-2026-08-22.json`](../deployment/data01-local-isolated-restore-2026-08-22.json)，
  报告 SHA-256 为 `33b7217d839b3036934ef0d3d2fbb45b61fd412af44ec354680e9a260b9c50a0`。

该条只补齐新恢复点的本机隔离 restore/rebuild 自洽证据；elapsed 不能冒充生产 RTO/RPO，仍未
执行 VPS maintenance、生产 restore/DDL、live rollback、controlled backfill 或 reconciliation。
`DATA-01` 继续 `awaiting_production`，`DATA-02/03` 不解锁。

## 实施记录（2026-08-23，DATA-01/02/03 current candidate read-only readiness recheck）

针对 `4cef9040cccc2127c3f8128c8d858bc7958df2a4` / release `20260822134658` 的 PostgreSQL
只读盘点显示：`data_center` 共 `59` 张 public 表、`3,653,282` 行，其中 `29` 张非空；
canonical publication 状态为 `47 published`、`2051 superseded`。但最新 `equity.core.backfill`
sync run 为 `blocked`（requested `2`、fetched/validated/stored/published 均为 `0`），最新
`fund.nav` reconciliation row 虽为 `is_clean=true`，也不足以代表全量 reconciliation。结构化
工件为 [`tar01-p0-readonly-ledger-inventory-2026-08-23-4cef9040.json`](../deployment/tar01-p0-readonly-ledger-inventory-2026-08-23-4cef9040.json)。
SHA-256 为 `7f4e859915e7e0a8399ee75558a12e660b34ef04000f29988291f59d47eaaa55`。

本轮没有创建新备份、进入维护态、执行生产 restore/DDL、backfill、reconciliation、rollback 或
切换；Data Center facts/publications 也没有被提升为决策证据。`DATA-01` 仍为
`awaiting_production`，`DATA-02/03` 继续 `waiting_dependency`；`/api/decision-ready/` 仍为
`503` 且 `must_not_use_for_decision=true`。

## 实施记录（2026-08-23，DATA-01 已有归档只读完整性复核）

本批没有创建新备份、没有重新部署 VPS、没有 prune、没有进入维护态，也没有执行生产
restore/DDL、回填、reconciliation 或 rollback。仅复核 VPS 上已存在的最新 custom-format
归档并保留本地忽略副本：

- 远端归档为 `/opt/agomtradepro/backups/database/postgres-20260822-075316.dump`，完整下载到
  `backups/vps-postgres/postgres-20260822-075316.dump`；两端大小均为 `142825371` bytes，
  两端 SHA-256 均为
  `f028ec2fe986be3c0f56f529e3fc44332ece472000c6e43f917d42b9ac2ffc55`。
- 远端 `pg_restore --list` exit `0`；本机没有 `pg_restore` 客户端，因此未把本地格式检查
  冒充通过。一个忽略的 `.partial` 临时文件仍在本地，但未被当作归档使用。
- 结构化工件为
  [`tar01-readonly-backup-observation-2026-08-23.json`](../deployment/tar01-readonly-backup-observation-2026-08-23.json)，
  `schema=tar01-readonly-backup-observation.v1`，content hash
  `715191dde263ebe59dc9c10f381f0926c94366b64daf5af55b48296a2e22fe77`；该观察绑定候选
  `4cef9040cccc2127c3f8128c8d858bc7958df2a4` / release `20260822134658`。

这条记录只证明现有恢复点的远端格式与传输完整性，不证明生产 restore/rebuild、RTO/RPO、
维护态 rollback、controlled backfill、reconciliation 或 owner/reviewer 验收。`DATA-01`
继续 `awaiting_production`，`DATA-02/03` 不解锁。

## 实施记录（2026-08-23，DATA-01 最新归档 data-backup-evidence.v1 复核）

本批严格按 `auto_collect` 只读取 VPS 上已有的最新 custom-format 归档；没有创建新备份、
prune、重新部署、维护态切换，也没有连接生产数据库执行 restore/DDL、回填、reconciliation
或 rollback。

- 远端归档为 `/opt/agomtradepro/backups/database/postgres-20260822-075316.dump`，完整下载到
  `backups/vps-postgres/postgres-20260822-075316.dump`；远端与本地大小均为 `142825371`
  bytes，SHA-256 均为
  `f028ec2fe986be3c0f56f529e3fc44332ece472000c6e43f917d42b9ac2ffc55`。
- 远端 `pg_restore --list` 已通过；manifest 为 `7204` entries，manifest SHA-256 为
  `7a75c9afffd87ed2aaa9bdade115a1898f5219075ded466f7e411ae3a18ddba7`；本地
  `postgres:16-alpine` 只读 `pg_restore --list` 复核得到同一计数与 digest。
- 结构化证据为 [`data-backup-evidence-2026-08-23.json`](../deployment/data-backup-evidence-2026-08-23.json)，
  `schema=data-backup-evidence.v1`，content hash
  `6566a9733e95ced40ae4fae0f4783d7029a881eed7bb6e0b1225b33347e17f38`；远端采集时间为
  `2026-08-23T09:45:28Z`，归档 mtime 为 `2026-08-22T05:54:05Z`，归档年龄 `100283s`。
- 备份脚本与 restore verifier 合计 `25 passed`；本地归档仅做格式列表验证，未把隔离
  restore 时间冒充生产 RTO/RPO。

这条记录补齐当前已有归档的 content-addressed 结构化证据和传输完整性；生产 restore/rebuild、
RTO/RPO、维护态 rollback、controlled backfill、reconciliation 与 owner/reviewer 验收仍缺。
因此 `DATA-01` 继续 `awaiting_production`，`DATA-02/03` 不解锁。

## 实施记录（2026-08-23，DATA-01 最新归档本地隔离 restore 验收）

为补齐上述只读格式复核与真正隔离 restore 之间的证据，本轮仅在本机
`agomtradepro-tar02-pg` disposable PostgreSQL 16 容器中操作：先将同一归档恢复为专用
source 基线，再由受控 verifier 恢复到第二个隔离库并逐表比较；两个临时数据库均已清理。
VPS、生产数据库、生产卷和部署均未访问或写入。

- 输入归档仍为 `/opt/agomtradepro/backups/database/postgres-20260822-075316.dump` 的本地副本
  `backups/vps-postgres/postgres-20260822-075316.dump`，大小 `142825371` bytes，SHA-256
  `f028ec2fe986be3c0f56f529e3fc44332ece472000c6e43f917d42b9ac2ffc55`；`pg_restore --list`
  可恢复条目 `7189`。
- 本地 source/restore 快照均为 `539` 张 public 表、`72` 个 Data Center migration、`460`
  个 sequence；逐表行内容 hash、表集合、migration 集合、sequence 值及 schema hash
  `47b7696d01371801a203560e830093712c6ace3bd94d8d6465699dab38857433` 均完全一致，
  `snapshot_difference` 的所有集合/变更字段为空。
- 结构化报告为 [`data01-latest-backup-restore-2026-08-23.json`](../deployment/data01-latest-backup-restore-2026-08-23.json)，
  SHA-256 `7b8ee34b226169545945b32292d9daf9c2ec1b1c059cecfeb9e9750a5258af8e`；本地 restore
  用时 `590.844s`、逐表验证 `536.518s`、总计 `1626.207s`，这些是本机容器耗时，不能
  冒充生产 RTO/RPO。

这一步把 `DATA-01` 的最新归档隔离恢复与精确一致性证据补齐，但没有执行生产 restore/rebuild、
维护态 rollback、RTO/RPO、controlled backfill、reconciliation 或 owner/reviewer 签署；
`DATA-01` 继续 `awaiting_production`，`DATA-02/03` 不解锁。

## 实施记录（2026-08-24，DATA-01 latest download 远端只读修复）

复核 `auto_collect` 契约时发现 `scripts/backup-vps-postgres.py --download-latest` 虽然不应
创建新归档，生成的远端脚本仍包含无条件的 `mkdir -p`/`chmod`，会在只读观察路径改变 VPS
文件系统。现已将 latest 模式拆为独立脚本：只读取既有 `postgres-*.dump`、运行
`pg_restore --list`、计算 hash/size/manifest 并输出 markers；默认 `prune=0` 时不含
`mkdir`、`chmod`、`pg_dump`、`mv` 或 `-delete`。用户明确指定正数 prune 时才生成删除块，
并保持 create 模式原有的建档/校验行为。

- `tests/unit/test_backup_vps_postgres.py` 回归 `11 passed`，新增静态合同断言 latest 脚本
  不含远端写操作；Ruff/Black/isort、增量 mypy 已通过。
- 本轮没有调用 VPS、没有下载/创建归档、没有 prune、没有维护态切换或生产写入。

这只修复 `auto_collect` 的远端只读边界，不构成生产备份、restore、RTO/RPO、rollback 或
owner/reviewer 验收；`DATA-01` 继续 `awaiting_production`，`DATA-02/03` 不解锁。

## 实施记录（2026-08-24，DATA-01 隔离 restore 证据 recorder 合同）

为让已完成的隔离恢复报告可以被重复、离线且 fail-closed 地验收，本轮新增纯
Application parser `apps/data_center/application/data01_restore_evidence.py` 与
`scripts/record_data01_restore_evidence.py`。recorder 只读取一份既有 JSON 快照，严格
校验 dump SHA-256 的 before/after/final 一致、source/restore 数据库身份不同、表/序列/
Data Center migrations/schema digest 逐项一致、差异集合为空、UTC 时间与时长合法；序列化
结果固定为 `production_claim=false`、`production_ready=false`、
`runtime_enablement=not_authorized`，并以 content-addressed、append-only 方式可选写入本地
证据目录。它不连接 PostgreSQL/VPS，不运行 `pg_restore`，不创建数据库，不进入维护态，也
不修改生产数据。

- 以本仓库提交的 [`data01-latest-backup-restore-2026-08-23.json`](../deployment/data01-latest-backup-restore-2026-08-23.json)
  dry-run 生成 artifact SHA-256 `dc705a787884f7ccfe781777654829e0243a5f4adca1d005783950ff2da4dd88`；
  仍绑定 `539` 张表、`460` 个序列、`72` 项迁移和既有隔离 restore 比较结果。
- `tests/unit/data_center/test_data01_restore_evidence.py` 回归 `7 passed`，并与既有
  backup/restore 合同合计 `17 passed`；Ruff/Black/isort、增量 mypy、mypy debt ceiling
  与治理检查均已通过。

这只是 DATA-01 的离线证据合同收口，不把本机 `590.844s` restore 或 `1626.207s` 总耗时
冒充生产 RTO/RPO；生产维护态 restore/rebuild、rollback、controlled backfill、
reconciliation、候选绑定与 owner/reviewer 签署仍缺，`DATA-01` 继续 `awaiting_production`，
`DATA-02/03` 不解锁。

## 实施记录（2026-08-24，DATA-02 只读 reconciliation recorder 合同）

为使受控回填前后的 canonical reconciliation 具备服务器侧可直接执行的离线采集入口，
输出 schema `data02-reconciliation-readonly.v1`，新增纯 Application parser
`apps/data_center/application/data02_reconciliation_evidence.py`
与 `scripts/record_data02_reconciliation_evidence.py`。输入必须来自外部已完成的
`select_only` 快照 envelope，包含同一 candidate 的 commit/version/OCI/matrix 身份、
legacy/canonical 两侧 source 与 UTC `observed_at`，以及严格排序的 expected/code-defect
自然键；parser 复用现有纯 `export_reconciliation_snapshot()`，保留
`same/expected_difference/data_missing/semantic_conflict/code_defect` 分类、两侧快照 hash
和观测时间，不把 unresolved 差异归零。

recorder 默认 dry-run；显式 `--write` 只在本地写 content-addressed append-only artifact。
它不连接 PostgreSQL/VPS、不执行 backfill、不写 Django reconciliation 表、不修改维护态，输出
固定 `production_claim=false`、`production_ready=false`、`runtime_enablement=not_authorized`。
定向回归 `19 passed`，Data Center entrypoint inventory 重新生成为 `1137` 项、
`candidate-review=0`；Ruff/Black/isort 与增量 mypy 通过。

这只补齐 DATA-02 的“外部 snapshot → reconciliation 报告”自动采集合同，不是生产回填、
coverage/freshness 全量验收，也不解除 DATA-01 前置、DATA-02/03 的生产状态、容差例外、
维护态切换、canonical 写入或 owner/reviewer 签署；没有部署 VPS 或写生产数据。

## 实施记录（2026-08-24，DATA-03 双 readiness 只读观察 recorder 合同）

为把 M9/M10 前允许自动采集的“双 readiness + canonical smoke”边界固化为可复核输入，
新增纯 Application parser
`apps/data_center/application/data03_readiness_evidence.py` 与服务器侧
`scripts/record_data03_readiness_evidence.py`，输出 schema
`data03-readiness-readonly.v1`。输入必须是外部已捕获的 `http_get_read_only` envelope，
每个样本重复封存 candidate 的 commit/version/OCI/matrix，并同时携带
`/api/ready/` 与 `/api/decision-ready/` 的 endpoint、HTTP status、服务端 timestamp、
checks 以及 decision 的 `must_not_use_for_decision`；canonical smoke checks 也要求显式
状态和 source time。parser 拒绝未知字段、未来时间、候选漂移、非单调 observation、
HTTP/status/gate 不一致、非有限 JSON 与未排序 smoke keys，并从原始响应只派生
service failure、decision blocker、check defect、smoke failure、source age 和 observation
duration，不把缺失字段补成成功。

recorder 默认 dry-run；显式 `--write` 只在服务器侧调用者指定的本地目录写
content-addressed append-only artifact。它不连接 VPS/HTTP/PostgreSQL，不执行 M9/M10
切换、不改变维护态、不写 production/readiness 表，报告固定
`production_claim=false`、`production_ready=false`、`runtime_enablement=not_authorized`。
`tests/unit/data_center/test_data03_readiness_evidence.py` 回归 `11 passed`，entrypoint
inventory 已刷新为 `1138` 项且 `candidate-review=0`。

本切片只完成“外部响应 → fail-closed 观察报告”的服务器端自动采集合同；没有新的外部
readiness/coverage/freshness/canonical smoke 数据，因此不宣称 DATA-03 观察窗口、M9/M10
切换或生产 readiness 通过。`DATA-03` 继续 `waiting_dependency`，仍需 DATA-02 受控
reconciliation、真实候选绑定、维护窗口和生产/数据 owner 批准后才能运行正式观察。

## 实施记录（2026-08-24，DATA-03 当前部署候选双 readiness 只读复核）

在不重新部署 VPS、不切换 release、不改变维护态或写入生产库的前提下，对当前受控候选
`94abd76e46eeef4a8e21853799c7d69bcd9bbe3b` / version `20260824133504` /
OCI `sha256:1c560b5fed14964a008c278a88d9f3e3b144444a172ecc239d06cedbd76d6a3e` /
matrix `6272ea6606ebbf3c0791e48d807b733cbc6d9a4ce7d945d95c5e3a16c22aea64` 执行一次低频
HTTPS `GET`。`/api/ready/`=`200/ok`，服务端 timestamp=`2026-08-24T07:59:30.063588Z`；
`/api/decision-ready/`=`503/blocked`，timestamp=`2026-08-24T07:59:34.242560Z`，
`must_not_use_for_decision=true`。`/api/health/` 返回 `200`；匿名
`/api/data-center/providers/` 返回 `403`，所以 `canonical.data-center` smoke 明确为
`unknown`，没有把未认证请求当成 canonical smoke 通过。

原始 envelope [`data03-readiness-http-get-2026-08-24-0757.json`](../deployment/data03-readiness-http-get-2026-08-24-0757.json)，
source payload SHA-256=`57ae566d61aa95c7848e8f5b8c1bbd0ae70f10bff6d9cdf43a580780ba728707`；经
`record_data03_readiness_evidence.py` dry-run 后显式写入，content-addressed report
[`8144f224cce8840a8284c64517fbf49b646e56d600235f976f7e423b4b35bf5a.json`](../deployment/data03-readiness/81/8144f224cce8840a8284c64517fbf49b646e56d600235f976f7e423b4b35bf5a.json)。
报告派生 `service_failure_count=0`、`decision_blocker_count=1`、`check_defect_count=17`、
`smoke_failure_count=1`、`max_source_age_seconds=4.178972`，并固定
`production_claim=false`、`production_ready=false`、`runtime_enablement=not_authorized`。

这次仅完成当前候选的双 readiness 只读刷新，不构成 DATA-03 observation window、全市场
coverage/freshness、M9/M10 切换、维护态操作、认证 canonical smoke 或 owner 签署；
`DATA-03` 继续 `waiting_dependency`，仍需 DATA-02 受控 reconciliation、认证 smoke、
维护窗口及生产/数据 owner 批准。

## 历史记录（2026-08-24，DATA-03 旧候选双 readiness 只读采样）

在不重新部署 VPS、不切换 release、不写生产库的前提下，对公开候选入口执行一次低频
HTTPS `GET` 采样，并将它绑定到此前只读 verifier 已确认的候选
`4cef9040cccc2127c3f8128c8d858bc7958df2a4` / version `20260822134658` /
OCI `sha256:cfaf17560df2f85cd8ba2f5db8226a9dd9fe1cce081f30175c2a08737b4908d8` /
matrix `6272ea6606ebbf3c0791e48d807b733cbc6d9a4ce7d945d95c5e3a16c22aea64`。本次公网响应
本身不暴露候选身份，身份来源和“不重新部署”的约束以既有候选 verifier 为准，不把本地
`dev/next-development` HEAD 冒充已部署版本。

- 原始只读 envelope 为 [`data03-readiness-http-get-2026-08-24-0015.json`](../deployment/data03-readiness-http-get-2026-08-24-0015.json)，source payload SHA-256=`1a1211d8bbd6dd029b50d554cfb4d012f01549447a486e1077414b965229c267`；`/api/ready/`=`200`（服务端 timestamp `2026-08-24T00:15:16.877442Z`，body SHA=`f9da6637332ab7e679addbdb6a88d223aae08a03e8871d8f5468e57c5da709a5`），`/api/decision-ready/`=`503 blocked`（timestamp `2026-08-24T00:15:22.810927Z`，body SHA=`fb75710cb112071419aab62ea1f9104be760f93393ec6e9fc251d4b5767bbd01`，`must_not_use_for_decision=true`）。
- `record_data03_readiness_evidence.py` 先 dry-run 后显式 `--write`，报告为
  [`2e48775c3400fd35407265123f43acf4f7d3302be8b1407d0f20448b7c6e0782.json`](../deployment/data03-readiness/2e/2e48775c3400fd35407265123f43acf4f7d3302be8b1407d0f20448b7c6e0782.json)，artifact SHA-256=`2e48775c3400fd35407265123f43acf4f7d3302be8b1407d0f20448b7c6e0782`；第二次显式写入返回 `written=false`，证明 content-addressed append-only 幂等。报告派生 `service_failure_count=0`、`decision_blocker_count=1`、`check_defect_count=3`、`smoke_failure_count=1`、`max_source_age_seconds=38.122558`，并固定 `production_claim=false`、`production_ready=false`、`runtime_enablement=not_authorized`。
- `/api/health/` 只读 smoke 为 `200`；匿名 `/api/data-center/providers/` 返回 `403`，因此
  `canonical.data-center` 明确记为 `unknown`，没有把未认证的 canonical smoke 当成通过。

这一步完成了一次候选绑定的双 readiness 只读观察和可复核 artifact，不构成 observation window、
全市场 coverage/freshness、M9/M10 切换、生产写入或决策解锁。`DATA-03` 继续
`waiting_dependency`；仍需 DATA-02 受控 reconciliation、认证 canonical smoke、维护窗口
及生产/数据 owner 批准后才能进入正式观察。

## 实施记录（2026-08-24，DATA-01 latest existing backup 只读刷新）

按 `DATA-01` 的 `auto_collect` 合同，仅通过 `scripts/backup-vps-postgres.py --download-latest`
发现并下载 VPS 上已经存在的最新 custom-format 归档；本次远端脚本只读取归档、运行
`pg_restore --list`、计算校验信息并返回 markers，未创建新备份、未执行 prune、未进入维护态，
也没有写入 PostgreSQL 或替换候选。最新归档为
`/opt/agomtradepro/backups/database/postgres-20260824-074227.dump`，远端/本地大小
`142813695` bytes，SHA-256=`7eb67da66bb6d3c550bc35f96abbc2c38ea403f776c56602316e83b912b4fd6d`；
远端 `pg_restore --list` 为 `7204` entries，manifest SHA-256=
`795d83b33400407596991f92523a5b15b2148bbf5e4e77fc52682194875f3886`，远端 mtime 为
`2026-08-24T05:43:16Z`，采集时间为 `2026-08-24T06:36:29Z`。

结构化 `data-backup-evidence.v1` 工件为
[`data-backup-evidence-2026-08-24.json`](../deployment/data-backup-evidence-2026-08-24.json)，
content hash=`423387ef6125233f4257694935beef0cea9c8543993803b3ef58bc896758e9f9`；远端/本地
SHA 与大小均匹配，partial archive 被拒绝。该工件只证明一个可下载、可列举的现有恢复点，
不把它绑定为生产 RTO/RPO 或维护窗口成功。

因此 `DATA-01` 仍为 `awaiting_production`：生产 restore/rebuild、维护态 rollback、RTO/RPO、
controlled backfill、reconciliation 与生产/数据 owner 签署尚未完成，`DATA-02/03` 不解锁。

## 实施记录（2026-08-24，DATA-01 最新归档本机隔离 restore 验收）

沿用同一 `--download-latest` 归档，在本地 disposable `postgres:16-alpine` 中先装载
source copy，再由 `scripts/verify_postgres_backup_restore.py` 创建受控命名的 restore 库，
执行 `pg_restore`、逐表内容 hash、schema、Data Center migration 与 sequence 对比。归档
`142813695` bytes、SHA-256=`7eb67da66bb6d3c550bc35f96abbc2c38ea403f776c56602316e83b912b4fd6d`，
`pg_restore --list` 非注释条目 `7189`；source/restore 均为 `539` 张 public 表、`72` 条
Data Center migration、`460` 条 sequence，schema SHA-256 均为
`47b7696d01371801a203560e830093712c6ace3bd94d8d6465699dab38857433`，missing/extra/changed
tables、migrations、sequences 与 schema 差异均为 `0`。restore 用时 `689.563s`，验证
`628.355s`，总计 `2214.035s`；完整 verifier report SHA-256 为
`0391884b5792150cdcefe74a9a41817c025a3d216e670dfbac18a47facd00f17`。

精简证据为 [`data01-local-isolated-restore-2026-08-24.json`](../deployment/data01-local-isolated-restore-2026-08-24.json)；
原始 verifier 报告随后通过 `record_data01_restore_evidence.py` dry-run、显式 `--write`、
再次幂等写入，canonical artifact 为
[`e7af4216ed86cdd63a62d84d5a38ef5bcc28ee255e82490611f673bb945ebe9d.json`](../deployment/data01-isolated-restore/e7/e7af4216ed86cdd63a62d84d5a38ef5bcc28ee255e82490611f673bb945ebe9d.json)，
artifact SHA-256=`e7af4216ed86cdd63a62d84d5a38ef5bcc28ee255e82490611f673bb945ebe9d`，
source payload SHA-256=`0391884b5792150cdcefe74a9a41817c025a3d216e670dfbac18a47facd00f17`，
`isolated_restore_verified=true`、`production_claim=false`。该 recorder 只读取已完成的
隔离报告，不连接 PostgreSQL/VPS。
restore 库、source copy 与容器内临时归档均已删除。该结果只证明最新归档在本地隔离环境中
自洽可恢复，耗时不能冒充生产 RTO/RPO；没有执行生产 restore/DDL、维护态 rollback、
controlled backfill 或 reconciliation，`DATA-01` 继续 `awaiting_production`，`DATA-02/03`
不解锁，生产/数据 owner 与 reviewer 签署仍缺。

## 2026-08-24：DATA-03 当前候选认证 canonical Data Center smoke

在不重新部署、不切换 release、不改变维护态或写入生产库的前提下，使用受控服务端
认证会话对同一候选 `94abd76e46eeef4a8e21853799c7d69bcd9bbe3b` / version
`20260824133504` / OCI `sha256:1c560b5fed14964a008c278a88d9f3e3b144444a172ecc239d06cedbd76d6a3e` /
matrix `6272ea6606ebbf3c0791e48d807b733cbc6d9a4ce7d945d95c5e3a16c22aea64` 做只读 smoke。
`/api/ready/` 为 `200/ok`（database、Redis、Celery、critical data 均为 `ok`，worker=1，
decision data=`warning`）；`/api/decision-ready/` 为 `503/blocked`，
`must_not_use_for_decision=true`，reason=`decision_runtime_blocked`。认证
`GET /api/data-center/providers/` 为 `200`，返回 2 条已脱敏 provider 记录；认证
`GET /api/data-center/providers/status/` 为 `200`，返回 15 条 capability 状态，其中 8 条
`must_not_use_for_decision=true`，状态含 `stale`/`degraded`，因此 provider-status smoke
按失败记录，未把接口可达误报为数据可用。

原始 envelope [`data03-readiness-authenticated-smoke-2026-08-24-1335.json`](../deployment/data03-readiness-authenticated-smoke-2026-08-24-1335.json)，
source payload SHA-256=`c1df5cf05b81b26cdba86d51acb9a74c4836b986548adae1f5177d6154f121f`；经
`record_data03_readiness_evidence.py --write` 生成 content-addressed report
[`55f20b1348564daf6dea93f23aecc229953954e6fcc1859f40180fbebea84d98.json`](../deployment/data03-readiness/55/55f20b1348564daf6dea93f23aecc229953954e6fcc1859f40180fbebea84d98.json)。
报告派生 `service_failure_count=0`、`decision_blocker_count=1`、`check_defect_count=2`、
`smoke_failure_count=1`，并固定 `production_claim=false`、`production_ready=false`、
`runtime_enablement=not_authorized`。

本次只新增一条候选绑定的认证只读 smoke 事实，不构成 DATA-02 reconciliation、全市场
coverage/freshness、M9/M10 切换、生产写入、维护窗口或 owner/reviewer 签署；
`DATA-03` 继续 `waiting_dependency`，decision-ready 继续 fail-closed。

## 实施记录（2026-08-24，DATA-02 当前候选 `fund.nav` SELECT-only reconciliation）

在不重新部署 VPS、不进入维护态、不执行 backfill、不写入 Django reconciliation 表的前提下，
通过 SSH 在当前候选容器内运行只读 ORM 查询，分别读取 `fund_net_value` 与
`data_center_fund_nav_fact(source=fund_legacy_repo)`。两侧均为 `7,648` 条，最大
`nav_date=2026-06-25`，服务端同一观测时点为 `2026-08-24T14:01:25.587369Z`；自然键和
`nav/acc_nav/daily_return` 经过现有 migration 同样的 Decimal canonicalization 后，两侧
snapshot hash 均为 `c733f38375b36029d9eb4920652c1fcb666966ef086463fb1eec91847ddbed92`。

原始候选绑定 envelope [`data02-reconciliation-candidate-2026-08-24.json`](../deployment/data02-reconciliation-candidate-2026-08-24.json)，
source payload SHA-256=`e0232b4587be7188103c4a1a51b3947a1da97baa7226c6a010896d10e2407b73`，绑定
commit=`94abd76e46eeef4a8e21853799c7d69bcd9bbe3b`、version=`20260824133504`、
OCI=`sha256:1c560b5fed14964a008c278a88d9f3e3b144444a172ecc239d06cedbd76d6a3e`、
matrix=`6272ea6606ebbf3c0791e48d807b733cbc6d9a4ce7d945d95c5e3a16c22aea64`。经
`record_data02_reconciliation_evidence.py` 先 dry-run、再显式 append-only 写入后，canonical
artifact 为 [`65935870cc4002c1e96fb0ab2473ee679b6b1540318aa72f2155a95d47db43dc.json`](../deployment/data02-reconciliation/65/65935870cc4002c1e96fb0ab2473ee679b6b1540318aa72f2155a95d47db43dc.json)，
artifact SHA-256=`65935870cc4002c1e96fb0ab2473ee679b6b1540318aa72f2155a95d47db43dc`。
报告分类为 `same=7648`、`expected_difference=0`、`data_missing=0`、
`semantic_conflict=0`、`code_defect=0`，`reconciliation_clean=true`。

这只证明 `fund.nav` 这一已选 dataset 在当前候选、当前只读快照边界内两侧一致；报告仍固定
`production_claim=false`、`production_ready=false`、`runtime_enablement=not_authorized`。
它不等于全 Data Center coverage/freshness、受控回填前后 reconciliation、维护窗口或
DATA-01 生产 restore/rollback，也不解除 DATA-02/03、decision-ready 或 owner/reviewer 签署门禁。

## 实施记录（2026-08-24，DATA-02 当前候选 coverage/freshness 只读复核）

在不重新部署 VPS、不进入维护态、不回填、不改 universe/config、也不写入生产库的前提下，
对当前受控候选 `94abd76e46eeef4a8e21853799c7d69bcd9bbe3b` / version `20260824133504` /
OCI `sha256:1c560b5fed14964a008c278a88d9f3e3b144444a172ecc239d06cedbd76d6a3e` /
matrix `6272ea6606ebbf3c0791e48d807b733cbc6d9a4ce7d945d95c5e3a16c22aea64` 执行认证
SELECT-only HTTP/ORM 观察。`active_a_share` universe 有 `5,533` 个 active stock，universe
quality=`ok`（BSE=331、SSE=2,310、SZSE=2,892；issues=[]）。price、valuation、financial
fact coverage 均为 `5,533/5,533`，但 canonical publication 仍阻断：price published
`0/5,533`，valuation publication 缺失，financial published `1/5,533`；三域均
`must_not_use_for_decision=true`。`/api/ready/`=`200` 但 decision-data=`warning`，
`/api/decision-ready/`=`503/blocked`，因此没有把 fact coverage 冒充为可决策数据。

结构化工件 [`data02-coverage-freshness-observation-2026-08-24-94abd76e.json`](../deployment/data02-coverage-freshness-observation-2026-08-24-94abd76e.json)，
SHA-256=`bf78a00e45357b6e61f46e1f96f68ee7fed4fac9648c90dca55387fe4f9fdfeb`；响应 body
hash、候选绑定、read-only/authentication 标记和 publication blockers 均封存。该证据只完成
当前候选的 coverage/freshness 观测，不构成 backfill/reconciliation、M9/M10、维护态切换、
容差例外、生产 ready、owner/reviewer 签署或 runtime enablement；`DATA-02` 继续
`waiting_dependency`，decision-ready 保持 fail-closed。

## 实施记录（2026-08-26，decision-ready 恢复依赖）

恢复路线已登记为 DATA-02/DATA-03 的生产依赖，不把它们伪装成 TAR-01 仓库完成项。当前候选
仍需真实的全 universe canonical publication、coverage/freshness、受控回填前后 reconciliation、
provider capability recovery 与 DATA-03 observation window；现有事实 coverage 不能替代
publication，`/api/ready/` 200 也不能替代 `/api/decision-ready/` 200。

本次只完成 SDK audit delivery identity 的本地修复，没有执行 backfill、provider refresh、
reconciliation 写入、维护态切换或任何生产数据修改。DATA-02/03 仍保持原状态，直到数据 owner
批准必要的生产写入并提供候选绑定的真实结果。

## 实施记录（2026-08-29，DATA-01 当前生产恢复点与隔离 restore 重绑定）

按 `DATA-01.auto_collect` 只读取并下载 2026-08-26 部署已生成的最新 custom-format 归档
`/opt/agomtradepro/backups/database/postgres-20260826-081700.dump`。远端 `pg_restore --list`、
完整 SFTP、远端/本地大小和 SHA-256 均通过：`144285484` bytes，SHA-256=
`dc000ab26dac4d32b553012c3db4a73a5f76d0f5d4af9a493dec4d6768c0d4fa`；远端 manifest 为
`7235` entries，manifest SHA-256=`224ac6d34551866f9f3c811200c8047d08a145e777590b7e0a32a620d6ebd106`，
mtime=`2026-08-26T06:18:21Z`。结构化工件为
[`data-backup-evidence-2026-08-29.json`](../deployment/data-backup-evidence-2026-08-29.json)，
content hash=`4ec617212c136f2e310a3d5106c6aaaddc2e3bccf58326a3bdee67d258a39563`。本轮使用
`--download-latest`，没有创建新备份、prune 或修改远端归档。

随后在既有专用 disposable `postgres:16-alpine` 容器内，以同一 immutable dump 建立 source
基线，再由 `verify_postgres_backup_restore.py` 创建受控前缀 restore 库，执行第二次 restore 与逐表
内容、schema、Data Center migrations 和 sequence 精确对账。verifier 非注释 restore entries=`7220`；
source/restore 均为 `541` 张 public 表、`72` 项 Data Center migration、`462` 个 sequences，schema
SHA-256 均为 `028087c07f0c1cbc2dc2949d1fab8e47bc92e9226d2965bb528766c4ec218d81`；
missing/extra/changed tables、migrations、sequences 和 schema 差异均为 0。dump 在格式校验前后和
restore 后 SHA 不变。第二次 restore=`635.523s`，验证=`547.292s`，verifier 总计=`1662.332s`。

原始报告为
[`data01-current-backup-restore-2026-08-29-45d7616d.json`](../deployment/data01-current-backup-restore-2026-08-29-45d7616d.json)，
SHA-256=`9ed7b83abfdf4b0bbdfebe08fd40393d9a328e617a97487c4fd9e6f528cc8305`；canonical
content-addressed 工件为
[`e13d10587add53aa1b6e53f3143f05f4de4cf30d7f8e465d833457da88016870.json`](../deployment/data01-isolated-restore/e1/e13d10587add53aa1b6e53f3143f05f4de4cf30d7f8e465d833457da88016870.json)，
artifact SHA 同文件名，`isolated_restore_verified=true`、`production_claim=false`、
`production_ready=false`、`runtime_enablement=not_authorized`。backup/restore/verifier recorder 聚焦
合同 `33 passed`。临时 source/restore 库和容器内临时 dump 已删除。

该证据证明 8 月 26 日恢复点可完整下载并在本地隔离环境自洽恢复，但本地耗时不能冒充生产 RTO/RPO；
没有进入生产维护态、执行生产 restore/live rollback、创建或清理远端备份、回填/reconciliation 或
人工签字。因此 `DATA-01` 继续 `awaiting_production`，其 live maintenance/rollback 与 owner 授权退出门
仍未满足，`DATA-02/03` 不解锁。

## 2026-08-29：新候选部署前 PostgreSQL 恢复点

在精确授权下为 release `20260829163806` 部署创建了新的 PostgreSQL custom-format backup：远端
`/opt/agomtradepro/backups/database/postgres-20260829T083336Z.dump`，本地
`backups/vps-postgres/postgres-20260829T083336Z.dump`。远端 `pg_restore --list`、SFTP 完整下载、
远端/本地大小和本地 SHA-256 均通过；归档为 `146273315` bytes，SHA-256=
`a5c77b8c6af13c5f61a3ca7e3fa9437b0bf23b03b049eb758abaf8ef94e2b30a`。未启用 retention prune，
没有删除历史 dump，也没有 restore 生产库。

该 backup 已作为 rollback point 写入
[`release-candidate-deployment-2026-08-29-09269c14.json`](../deployment/release-candidate-deployment-2026-08-29-09269c14.json)。
它完成了 DATA-01 的“创建、下载、格式和 hash 校验”切片，但新 dump 尚未完成本地 isolated restore
逐表/迁移/sequence 对账，也未进入 maintenance、production restore 或 live rollback。`DATA-01` 继续
`awaiting_production`；下一安全切片是对该 immutable dump 做本地隔离恢复，production maintenance/rollback
仍需 owner 精确授权。

## 2026-08-29：新候选预部署恢复点本地隔离 restore 验收

已在唯一命名的 disposable `postgres:16-alpine` 中将同一 immutable dump 建立为 source 基线，
再由 `verify_postgres_backup_restore.py` 创建受控前缀的第二个 restore 库完成精确对账。归档在格式
校验前、校验后和 restore 后 SHA-256 均为
`a5c77b8c6af13c5f61a3ca7e3fa9437b0bf23b03b049eb758abaf8ef94e2b30a`，大小
`146273315` bytes，非注释 restore entries=`7220`。source/restore 均为 `541` 张 public 表、
`72` 项 Data Center migrations 和 `462` 个 sequences，schema SHA-256 均为
`028087c07f0c1cbc2dc2949d1fab8e47bc92e9226d2965bb528766c4ec218d81`；missing/extra/changed
tables、migrations、sequences 与 schema 差异全部为零。

原始 verifier 报告
[`data01-current-backup-restore-2026-08-29-09269c14.json`](../deployment/data01-current-backup-restore-2026-08-29-09269c14.json)
为 `291178` bytes，SHA-256=`d7c438ebfdb239cba629c97e96a2e987a15b945abb3cd552501151a2f87020ca`；
第二次 restore=`719.811s`、verification=`586.979s`、总计=`1864.578s`。canonical recorder
生成
[`a8da9c326c130ec5be19acbc525382178c258075c6aa55531e86c560552bb121.json`](../deployment/data01-isolated-restore/a8/a8da9c326c130ec5be19acbc525382178c258075c6aa55531e86c560552bb121.json)，
artifact SHA 与文件名一致，`isolated_restore_verified=true`、`production_claim=false`、
`production_ready=false`、`runtime_enablement=not_authorized`。临时 restore 库、source 库和容器
均已删除。

该验收只证明新恢复点在本地隔离环境中传输、格式、schema 与数据自洽；本地耗时不能冒充生产
RTO/RPO。本轮没有进入生产 maintenance、执行 production restore/live rollback、prune、backfill、
reconciliation 或代替 owner 决策。`DATA-01` 继续 `awaiting_production`，下一真实门为生产 owner
选择维护窗口并精确授权 live maintenance/rollback rehearsal，`DATA-02/03` 不解锁。

## 2026-08-30：DATA-01 真实切换演练关闭与 DATA-02 原子发布候选

用户对 A1–A8 动作包给出继续执行授权后，在生产候选
`c826f741edc0f12f5e29fa5b0441b34a89f6dac5` 上新建并保留
`/opt/agomtradepro/backups/database/postgres-20260829T171523Z.dump`，下载文件为
`146743609` bytes，远端/本地 SHA-256 均为
`18d208a5124862a8993a19f2482a8116c64f8bc6eb930fa934e4db415a86034f`。dump 恢复到 sibling
`agomtradepro_restore_verify_d01c826f741` 后得到 `542` 张表、`72` 项 Data Center migration、
`463` 个 sequence 和 schema SHA-256
`d9f761e83e45cf5111af7b76ef546f99d52d3e7198489a03a458ba9e519ca447`。

隔离库完成 `0072 → 0071 → 0072` 往返；schema、业务表和 migration 名称集合一致，唯一差异是
Django 正常记录 forward migration 导致 `django_migrations` ledger id/sequence 从 `496` 增为
`497`。随后真实切换 Web 到 sibling 并切回原库：恢复库启动 `63s`、原库启动 `42s`、公网累计
不可用 `217s`；price/valuation/financial/publication/member/terminal-audit 六项关键计数切换前后
完全一致，WAL 前后均为 `3/EF274DF0`。切回后 health=`200`、Celery=`1`，原 decision runtime
`blocked` 状态恢复；临时库和临时秘密文件已删除，恢复点保留。对应四个 JSON 工件与 hash 见
[`发布阻塞清零综合实施方案 §13.1`](release-blocker-closure-execution-plan-2026-08-29.md#131-data-01-已关闭)。
据此 `DATA-01=completed`，但该结论不关闭 AUD-03，也不构成 DATA-02/03 或 decision-ready 通过。

DATA-02 候选新增 `CoreCurrentPublicationRebuildUseCase`、四个 repository latest-candidate selector、
dry-run-first 的 `rebuild_active_a_share_core_publications` 命令及 composition root。执行前严格校验
冻结 universe、dataset/table、aware/future observation time 和幂等性；price、valuation、financial
三类 publication 使用同一外层事务，任一失败整体回滚。常规单资产同步与 backfill 中间批次改为
fact-only，避免局部任务缩小全市场 current publication；完整 backfill 只有在最终批成功时才原子重建
三类 publication，失败发布 `blocked` 并保留 checkpoint。

本地定向证据为：application/command 单元测试 `22 passed`、repository selector component
`3 passed`、current-data guard `52 surfaces`、Celery guard `91 tasks`，相关生产 Python 增量 mypy
`0 issues`。下一步是部署精确候选后运行 publication dry-run，核对三类 candidate count、最新源观测
时间与缺口；只对真实 stale/history 缺口执行受控 provider refresh/backfill，完成逐数据集 reconciliation
后才允许进入 DATA-03。持久化 decision runtime 在此期间继续 `blocked`。

### 2026-08-30：DATA-02 当前事实修复与 DATA-03 激活硬门候选

在全量 Publication 候选之上新增 dry-run-first 的 `repair_active_a_share_current_facts`。执行链以 frozen active-A-share universe 为唯一范围，historical-price/financial 先做非零探针，quote 与 current valuation 按批精确覆盖；任一缺标的即在 Publication 前失败关闭。financial 只把已有真实 `report_date` 的 null `available_at` 写回，不用 fetched/request time 代替；price 只从最近已完成交易日且 15:00 后、OHLC 有效的真实 quote materialize。四份 current Publication 在统一事务内提交，局部同步全部 fact-only。

生产只读 provider preflight（未写 DB）验证：active universe=`5,533`，Tencent failover 返回=`5,533`，源 observation date 均为 `2026-08-28`，invalid/missing OHLC=`0`；EastMoney batch endpoint 的 502/断连被保留为显式 failover 证据。日频 price/valuation freshness 新增最近已收盘交易日语义，避免周末自然小时误判；realtime quote 继续使用更严格的实时/已完成 session 合同。

DATA-03 新增候选绑定的 `activate_decision_runtime_fail_closed`。普通 update use case 与通用 command 不再允许 `active`；激活必须完成三项非 runtime 严格预检、锁行 compare-and-set、精确 release/actor readback、三项立即复验，并在任一漂移时自动 re-block。此处只完成仓库实现与测试，`DATA-02` 尚待部署/生产 dry-run/执行/reconciliation，故 `DATA-03` 状态仍为 `waiting_dependency`。

## 2026-08-30：最终候选部署、DATA-02 生产 dry-run 与 typed Audit 阻塞

DATA-02/03 实现已随 commit `36b72d2fc01604afdb15d236a1e91d082fb62a5b` 部署为 release
`20260830071422`。默认 dry-run 保持 SELECT/provider-read 边界，没有写入事实或 Publication：active
A-share universe=`5,533`，financial null-availability 可安全修复 `288,409` 行、覆盖 `3,750`
个资产，unresolved/future=`0/0`；最近完成交易日 price 候选却为 eligible=`0`、invalid/stale=`5,533`。
现有 current Publication 的 quote/price/valuation 均为 `5,533/5,533` 但 stale，financial 为
`1,923/5,533`，缺 `3,610`。这证明代码路径和缺口规模，但没有满足 DATA-02 的 freshness、覆盖与
reconciliation exit gate。

执行前另创建并下载校验恢复点
`/opt/agomtradepro/backups/database/postgres-20260829T220625Z.dump`，大小 `146,646,151` bytes，
远端/本地 SHA-256 均为
`434903ac03c4fd6e4623682c65628f6b3f7be533a279b53fa063d692470e3d95`。随后生产仅运行幂等
`initialize_runtime_definitions`：三项 `audit.system_event.*` definition 已登记；active production
profile v2 仍缺 mode、outbox_enabled、authority_selector 三项值，七张 canonical Account authority
root/ledger 表均为 `0`。因此 typed audit composition 继续 fail closed，`repair_active_a_share_current_facts
--execute` 未运行，DATA-03 activation 也未尝试。

规范化 checkpoint 见
[`data02-audit-runtime-checkpoint-2026-08-30.json`](../deployment/data02-audit-runtime-checkpoint-2026-08-30.json)，
写前恢复点见
[`data02-audit-config-prewrite-backup-2026-08-30.json`](../deployment/data02-audit-config-prewrite-backup-2026-08-30.json)。
`DATA-02` 保持 `awaiting_production`，`DATA-03` 保持 `waiting_dependency`。唯一下一门是命名 production
owner 与独立 root/reviewer 提供并批准真实 selector/profile 值；自动化不得从 User/Profile/session
推导或创建替代 authority。typed writer 加载成功后，才可执行 A3、逐数据集 reconciliation，并在三项
readiness 全绿后调用 fail-closed activation wrapper。

## 2026-08-30：DATA-02 精确执行、停止与回滚契约

候选绑定的逐项授权包已经生成：
[`aud03-data02-production-authorization-preflight-2026-08-30-36b72d2f.json`](../deployment/aud03-data02-production-authorization-preflight-2026-08-30-36b72d2f.json)，
SHA-256=`25dc78fd5dfc627460761f7c7aa28c5fef08da8f3cd7ec8b62b81ac3665096d1`。
生产只读复核显示 active provider 为 Tushare Pro（priority `1`）和 AKShare Public（priority `10`）；
`default_source=akshare`、failover=`true`、tolerance=`0.01`，代码能力矩阵中二者都覆盖本工作流。
这只证明可选 provider 能力，不替代 owner 对本次 `--source` 的批准。

获批后唯一命令模板为：

```text
python manage.py repair_active_a_share_current_facts --execute --operator <approved-operator> --source <approved-source> --batch-size <approved-1-through-500>
```

`operator` 必须是非空单行且不超过 100 字符，`source` 不超过 50 字符，`batch-size` 范围为
`1..500`。执行前还必须明确接受现有恢复点
`/opt/agomtradepro/backups/database/postgres-20260829T220625Z.dump`（SHA-256=
`434903ac03c4fd6e4623682c65628f6b3f7be533a279b53fa063d692470e3d95`）作为本次写入回滚点，并先通过
Audit writer 与 exact authority preflight。

事务边界必须如实理解：historical-price/financial probes 以及 quote/valuation batches 会在最终
Publication 事务前写入 facts；后续失败可能留下部分新 facts，但既有 current Publication 在最终提交前
保持不变。四份 current Publication 仅在覆盖严格等于 `5,533`、时间戳/freshness 和审计回执都通过后
由同一外层事务一次切换，任一 Publication 失败则四份切换全部回滚。部分 facts 禁止 blanket delete；
只能保留 source identity 后，对精确受影响记录执行另行授权、证据绑定的 reconciliation/compensation。
成功切换后的 Publication 回滚也必须调用 canonical rollback use case，携带精确 target/previous identity
和 Audit evidence，不能把数据库备份或 profile 回退冒充业务 Publication rollback。

候选漂移、owner/root/reviewer 未批准、profile/snapshot hash 不一致、selector/head 不匹配、writer
preflight 失败、provider probe 零行、批次不完整、future/naive/stale observation、覆盖不等于 `5,533`、
审计/reconciliation 缺口或回滚点未接受，任一条件发生即停止。当前所有写阶段仍为
`not_authorized`；`DATA-02=awaiting_production`、`DATA-03=waiting_dependency` 不变。

## 2026-08-30：审核团队回传合同

审核说明已固化为
[closure-review-team-handoff-2026-08-30-36b72d2f.md](../deployment/closure-review-team-handoff-2026-08-30-36b72d2f.md)，
SHA-256=`4ba887ba3d7a81cf6c6e1349f08a082968626c9d647c55644b44852a4771dc36`；机器回传模板为
[aud03-data02-production-review-return-template-2026-08-30-36b72d2f.json](../deployment/aud03-data02-production-review-return-template-2026-08-30-36b72d2f.json)，
SHA-256=`bebe057503ef1d7196bd00f84ef3d71b3a2660dd0097283e68a40e71a490d6c7`。

适当的审核输出必须逐 phase 给出 `APPROVE/REJECT/DEFER`，并精确填入 operator、source、batch、
授权有效期、既有 backup 接受、partial-fact 风险确认和禁止 blanket delete/容差放宽/跨候选复用。
pre-execution 批准仅授权一次精确执行；5,533 coverage、四 Publication id/hash、Audit receipts 与
reconciliation 必须在真实执行后另签 post-execution acceptance。模板保持 `template_only=true`，
因此当前仍无生产写授权，DATA-02/DATA-03 状态不变。

## 2026-08-30 single-owner 回传处理

AUD/DATA 回传已通过 JSON、sidecar、候选和缺失证据核验，并在 single-owner 模式下登记为有效 `DEFER`。
项目所有者身份与 receipt 已满足，不再等待第二名 reviewer；DEFER 的技术原因仍是 production Audit
profile `mode_invalid`、三项 typed 值未形成、七张 authority root/ledger 表零行，以及 DATA-02 price
eligible=`0/5533`。下一步是按 owner receipt 建立真实 canonical authority/profile successor，再重跑只读
writer preflight；只有它通过后才执行已授权的有界 DATA-02 remediation，不能用签字跳过。

## 2026-08-31：DATA-04 ASGI 连接耗尽与 SELECT-only 预演整改

在 successor commit `80ea002bf910110621022a70e4f1ec5c1b704a56` / release
`20260830215638` 上重新绑定 DATA-02 dry-run 时，命令在形成 preview 前即被 PostgreSQL 拒绝：
`max_connections=100`、`superuser_reserved_connections=3`，公网 database health、service readiness
与 Audit health 均为 `503`，dependency-free liveness 仍为 `200`。只读进程/日志证据显示空闲 client
几乎都来自 Web 容器，并按约 30 秒持续增长；同一周期与 Prometheus 的 DB-backed `/metrics/`
scrape 对齐，而生产 Daphne/ASGI 设置仍为 `CONN_MAX_AGE=600`。这是高置信度根因关联，尚不是
修复部署后的生产证明。

源码复核还发现 `ProductionCoverageUniverseConfigModel.load()` 在 dry-run 读取路径使用
`get_or_create`，因此“预演”在 singleton 缺行时可能写库。`DATA-04` 将生产 ASGI
`CONN_MAX_AGE` 固定为 `0` 且拒绝正数环境覆盖；删除隐式建行 loader，repository `load()` 只执行
SELECT，缺配置抛出稳定 `MISSING_CONFIG`；只有显式 `save()` 或完整 PUT 可以初始化，PATCH 仍要求
已有配置。管理命令在缺配置时于 coordinator/provider 前失败关闭。

结构化 repository 证据为
[`data04-asgi-db-select-only-preview-repository-closure-evidence-2026-08-31.json`](../testing/data04-asgi-db-select-only-preview-repository-closure-evidence-2026-08-31.json)，
SHA-256=`aaaa675ed5bc078a916244de91bf2a335da5e2519883b312c2cc1dd0a034ea8d`。聚焦合同
`18 passed`；扩大相关回归中 DATA-04 行为 `69 passed`，唯一失败是 HEAD 本身已存在且未改动的
`financial_fact_repository.py` 243 行/预算 200 结构债务。增量/全量 mypy、53 个 current-data
surface、Black/isort/Ruff、3,005-file architecture、Django check、migration drift 与治理检查均通过。

该 exit 只关闭 repository 缺陷，不宣称线上数据库已恢复：本轮未终止 session、未重启容器、未部署、
未写生产或执行 backfill。`DATA-02` 现在依赖 `DATA-04`；下一生产门是另行授权部署 clean candidate，
验证多个 scrape 周期不再累积 Web idle client、恢复 database/readiness，再重跑真正无写入的
candidate-bound dry-run。任何 restart/deploy 都不得沿用旧 TUI 观察窗口的完成声明。

## 2026-08-31：DATA-05 financial repository owner 结构门关闭

DATA-04 扩大回归暴露 HEAD 上既有的确定性 CI 失败：
`financial_fact_repository.py` 有 243 个非空行，超过 200 行 owner budget；工作树修改前该文件与
HEAD 完全一致。该问题独立登记为 DATA-05，不回写或稀释 DATA-04 证据。

整改把 availability preview/backfill ORM 行为原样迁入独立
`financial_availability_repository.py` owner，通过 mixin 保持
`FinancialFactRepository` 的公开类、facade identity 和调用签名不变。原 owner 降至 189/200，
新 owner 为 65/100；没有抬预算或增加豁免。新文件同步登记到
`data_center.core_current_publication_rebuild` current-data source/marker 清单。

聚焦结构与 ORM 回归 `12 passed`，DATA-04/05 扩大相关回归由先前 69+1 收敛为 `70 passed`；
53-surface current-data、7 个生产文件增量 mypy、全仓 mypy debt、Black/isort/Ruff、3,006-file
architecture、Django/migration 与治理检查均通过。结构化证据为
[`data05-financial-repository-owner-closure-evidence-2026-08-31.json`](../testing/data05-financial-repository-owner-closure-evidence-2026-08-31.json)，
SHA-256=`7c535f2a1802561be3430a8a9a2149da4ab08b885f2ad672f96828209da8a56a`。
本单元没有读取或修改生产、重启、部署或执行回填，不改变 DATA-02 的生产 exit gate。

## 2026-08-31：DATA-06 隔离历史 DATA-02 simulation-first 开发

项目所有者授权先用历史数据模拟、再迭代开发。现有 restore verifier 与 DATA-02 reconciliation recorder
各自完整，但中间缺少从已验证 dump 的 disposable PostgreSQL 恢复库采集 SELECT-only coverage、freshness、
源观测时间和 legacy/canonical snapshot 的有界 runner。`DATA-06` 因此登记为唯一 repository focus。

范围冻结为：只接受已有 dump 与匹配 sidecar；只创建受控前缀的 disposable database；禁用 provider 与
network；在 repeatable-read read-only 事务中采集并输出 candidate-bound、content-addressed、
`production_claim=false`/`production_ready=false` 的本地 artifact；finally 必须证明零残留。任何 unsafe
target、输入漂移、写尝试、schema 缺失、未来/naive observation time、候选漂移或 cleanup residue 都失败
关闭。历史模拟不能代替 DATA-04 clean deploy、生产 DATA-02 backfill/reconciliation、current freshness、
authority/profile、live connection capacity 或 DATA-03 activation。

## 2026-09-01：DATA-06 隔离历史模拟能力完成

DATA-06 已实现并真实运行 restore-to-analysis 闭环：匹配 SHA sidecar 的既有 custom dump 只恢复到 loopback
`agom_data02_sim_*` database，所有分析位于 `REPEATABLE READ READ ONLY` 事务，无 provider/外部网络，finally
删除数据库并由外层 disposable PostgreSQL container 复查零残留。runner 输出 candidate/source-tree/dump 绑定、
content-addressed artifact，且固定 `production_claim=false`、`production_ready=false`。

最终历史快照包含 7,229 restore entries、72 个 Data Center migrations 和 5,533 个 active A-share。四类 active
Dataset Contract freshness policy 均存在，但 Quote/Price/Valuation/Financial 全部 stale；Financial 最新 evidence-safe
period 仅覆盖 1,923 个资产，另外三类事实覆盖完整；四类 current publication 均无法与候选事实精确 reconciliation，
因此总 gate 正确保持 `DENY`。这份结果只用于指导后续 backfill/publication repair，不是 production readiness。

聚焦/相关测试 `57 passed`，增量与全仓 mypy debt 为 0，53-surface current-data、3,008-file architecture、格式、
Django/migration 均通过。规范化证据
[`data06-isolated-historical-simulation-repository-closure-evidence-2026-09-01.json`](../testing/data06-isolated-historical-simulation-repository-closure-evidence-2026-09-01.json)
SHA-256=`e4883f46426b2b9082392371276a79ff4bbcab07e7a6c6022c02f8563d68579a`。机器注册表将 DATA-06 置为
`completed` 并清空 repository execution focus；下一步仍是 clean successor 部署、连接/readiness 稳定、生产 dry-run、
已授权有界 backfill 与 reconciliation，不能以历史 `DENY` artifact 启用 DATA-03 或继承 TUI-02 观察。

## 2026-09-02：DATA-02 successor production read-only checkpoint

PR #16 合并后的 immutable candidate `aa7127ff4d9f71555b0d0486314da5518bd2ac20` 已从独立 clean
worktree 部署为 release `20260901232812` / image
`sha256:55d2b1d8dd7078acc42aef72f0fa33e57035d30e5c2727b574dfd43aafd9519c`。部署前 PostgreSQL
custom-format dump 已创建、`pg_restore --list` 验证并下载；remote/local SHA-256 均为
`c9f7cf876bd79908aa66461e5d07b254104ba1013b134f669cb91bf8119b1caf`。部署后 migration pending=0，
三轮 35 秒间隔只读采样的 client backends 恒为 2、idle=1、remote client=1，没有 DATA-04 修复前的连接累积。

候选绑定的 [`data02-successor-production-readonly-checkpoint-2026-09-02-aa7127ff.json`](../deployment/data02-successor-production-readonly-checkpoint-2026-09-02-aa7127ff.json)
只运行 `repair_active_a_share_current_facts` 与 `rebuild_active_a_share_core_publications` dry-run，没有
`--execute`。5,533 资产中 completed-session price eligible=`0`、invalid=`5,533`；quote/price/valuation
虽覆盖 5,533，但全部 stale；financial availability 安全修复预览为 288,409 rows / 3,750 assets、
unresolved/future=0，而实际 financial fact 仅覆盖 1,923、缺 3,610。overall ready 正确保持 false。

因此 DATA-02 仍为 `awaiting_production`。下一门不是再跑历史模拟或重复只读 inventory，而是在已备份、
候选未漂移和 before/after recorder 生效的前提下，按有界批次执行生产 reconciliation；任何 tolerance waiver
仍由真实 data owner 决定。DATA-03 继续等待 DATA-02，不得用 service-ready=200 替代 decision-ready=503。

## 2026-09-02：DATA-02 successor checkpoint recorder contract

现有 successor checkpoint 缺少四个 core dataset 的 immutable `publication_id` 与
`publication_hash`，直接交给旧的双快照 reconciliation recorder 会因 schema 不同而失败，且不能证明
后续 before/after publication 没有发生 identity substitution。新增纯 Application
`apps/data_center/application/data02_successor_checkpoint.py` 与服务器端
`scripts/record_data02_successor_checkpoint.py`：只接受 candidate-bound、UTC、SELECT-only 的 successor
checkpoint，核对 5,533 asset partition、completed-session price 分布、连接增长、public probe digest、
dry-run exit code、side-effect flags 和四个 publication identity 的唯一性。默认只做 dry-run，显式写入仅为
本地 content-addressed append-only artifact。

当前签入的真实 checkpoint 在 publication identity 缺失处按预期 fail-closed；补充单元回归 `11 passed`，
Data Center entrypoint inventory 更新为 `1,152` 项且 `candidate-review=0`，增量 mypy 与全量 debt ceiling
均为 `0`，Black/isort/Ruff、active-plan 和 governance checks 全绿。本 slice 没有访问 VPS/数据库、执行
backfill、写入事实或切换 publication，不生成 synthetic production identity；`DATA-02` 仍保持
`awaiting_production`，待真实 owner 批准的 provider refresh/backfill 后用该 recorder 采集 before/after
reconciliation。

## 2026-09-03：DATA-02 successor recorder operator output

对已签入 checkpoint 的服务器端操作路径做了一个不改变数据契约的收口：
`scripts/record_data02_successor_checkpoint.py` 现在在 CLI 边界捕获
`Data02SuccessorCheckpointError`，以稳定的 `blocked` JSON 和退出码 `2` 返回
`reason_code=invalid_successor_checkpoint`，而不是把预期的校验阻断打印为完整 traceback。底层
parser 仍保持异常契约，缺少四个 immutable publication identity 仍然 fail-closed；有效报告的既有
输出字段、默认 dry-run、显式 append-only 写入和 `production_claim=false`/`runtime_enablement=not_authorized`
均不变。focused recorder 回归 `12 passed`，Black/isort/Ruff、增量 mypy 与 debt ceiling 均通过。

这只是服务器端工具可操作性修复，没有连接 VPS/数据库、写入生产、执行 backfill 或切换 publication，
也没有把失败 checkpoint 变成生产证据；`DATA-02` 继续 `awaiting_production`，仍等待真实 provider
refresh/backfill、before/after reconciliation 以及 data-owner 的容差决定。

## 2026-09-03：DATA-01 latest backup 隔离恢复复核

按 `DATA-01.auto_collect` 只选择并下载生产现有最新 custom-format dump
`postgres-20260901-174054.dump`，未创建新备份、未 prune、未进入维护态。远端 `pg_restore --list`、
完整 SFTP 下载、远端/本地大小 `147464528` bytes 与 SHA-256
`c9f7cf876bd79908aa66461e5d07b254104ba1013b134f669cb91bf8119b1caf` 一致；但采集时该恢复点约
`37.96h`，超过 VPS in-flight `<24h` 目标，后续刷新必须另行取得生产写授权。

同一不可变 dump 已在本机一次性 PostgreSQL 中完成两次恢复视图的全量比对：`7229` restore entries、
`542` 张表、Data Center `72` 条 migration、`463` 条 sequence 全部一致，schema SHA-256 为
`d9f761e83e45cf5111af7b76ef546f99d52d3e7198489a03a458ba9e519ca447`，changed/missing/extra
均为 `0`。restore/RTO 为 `1174.415s`，验证 `811.135s`，总耗时 `3183.388s`；第二恢复库和源容器
均已删除。原始报告为
[`data01-current-backup-restore-2026-09-03-b80c92f5.json`](../deployment/data01-current-backup-restore-2026-09-03-b80c92f5.json)，
content-addressed evidence 为
[`159558c981837b67ab3d2389c97c648047d1f671947ac087b7aa3db9c35cec19.json`](../deployment/data01-isolated-restore/15/159558c981837b67ab3d2389c97c648047d1f671947ac087b7aa3db9c35cec19.json)。

历史 `c826f741` live switchback 四件套同时重新按文件摘要索引；原始 migration roundtrip 的唯一差异仍是
`django_migrations` ledger/sequence bookkeeping，并由后续 classification artifact 证明 business tables、
migration name set 与 canonical schema 一致。它仍只证明历史 DATA-01 演练，不证明当前 M5 候选、当前
RPO 或 DATA-02 backfill 已通过。
