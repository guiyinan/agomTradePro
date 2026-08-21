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
