# 生产数据可靠性完整修复与测试计划（2026-08-01）

> 实施状态（2026-08-01）：本地代码、迁移、治理契约和专项回归已完成；待提交、CI、生产备份、维护态切换、全量回填和生产验收。生产步骤完成前不得勾选 P1/P2 的上线验收项。

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

同日候选部署身份为 release `20260815152834`、image
`sha256:12c5ce84ecd2d072846bb7777e6e0345e3ed83e98333bdf80ca35108d2a5c385`，health/ready
与服务复核通过；ready 中 Alpha/Qlib 与 workspace freshness warnings 继续按数据合同保留，
不作为 decision-data gate 完成证据。

## 实施记录（2026-08-15，DATA-02 control-plane atomic snapshot）

回填任务的 run、batch、checkpoint 现在由 Data Center composition root 在同一事务中提交；Application task 不直接持有 Django transaction。新增故障注入组件测试证明 checkpoint 持久化失败时三张控制面表全部回滚（`2 passed, 2 skipped`），任务单元 `8 passed`；architecture、增量 mypy、Celery contract、Black/isort 和 diff-check 均通过。

这只是本地控制面原子性证据，不是 PostgreSQL 并发/锁预算、生产回填、coverage/reconciliation 或 DATA-01 维护态/恢复演练。`DATA-01` 仍为 `awaiting_production`，因此 `DATA-02/03` 继续锁定。
