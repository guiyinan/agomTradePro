# 生产收口执行记录（2026-09-20）

本轮由主代理带领 GPT-5.6 Luna（max）实现并独立复核。canonical unit 状态仍以
`governance/active_plan_registry.json` 为准；历史部署、语义批准、局部测试均不自动晋级生产单元。

## 实际基线与完成标准

开工分支基线为 `439468482f457884db17da47d7566a5aac295842`，工作树干净。
新工作分支为 `dev/fix-config-public-snapshot-hash`。registry 开工检查：53 units、0 violations；
governance consistency 各项 0 violations。空的本地 `agomtradepro` 目录已建立同名虚拟环境，
使用现有系统依赖（Python 3.13.5、Django 5.2.12、mypy 1.14.1），未修改依赖真源或投影。

[只读封存](../deployment/production-closure-baseline-revalidation-2026-09-20.json)及其 sidecar
保存当前生产响应摘要、实际候选/容器身份、READ ONLY runtime 查询、旧原件校验和文档哈希。
该封存没有执行 provider 请求、生产写入、部署、恢复、故障注入或审批。

- 生产实际 release 为 `20260920184626`，manifest source 为 `439468482…`；
  Web image 为 `sha256:ad885af0fbb5904f389cbe469403fd758901e0f4b62e88e0c8dab34e52315d71`。
- 2026-09-20 15:10 UTC：HTTPS health/ready=200，decision-ready=503。
- 15:13 UTC 的 PostgreSQL `REPEATABLE READ READ ONLY` 查询：唯一 active profile 为 v17，
  public snapshot 47 项、哈希有效，Audit loader 接受；mode=off、outbox=false、selector 缺失。
  full profile/revision hash 与 public snapshot hash 使用不同作用域是既有契约，不能强行等同。
- 09-19 原件及 manifest 已重新核对：资产范围已从历史 5,533 变为 5,565；三类 Publication
  已有记录。财报真实来源时间/四类 Publication 对账仍缺，不能用旧范围或三类成功关闭 DATA-02。

## 分项执行与恢复条件

| 项目 | 本轮事实与下一步 | 未完成条件 |
| --- | --- | --- |
| T0 / AUD-05 | **completed**：分离 full/public hash，拒绝损坏公共快照，精确绑定旧记录、原子追加 successor，验证回滚历史 scope/hash；[源码绑定证据](../testing/aud05-repository-closure-2026-09-20.json) | 仅仓库收口；未部署或激活生产配置，未替代 AUD-03 生产验收 |
| T1 / DATA-02 | 保留 v17 loader 有效但 audit off 的实际事实；先完成 AUD-05，再绑定真实服务身份/账户/租户与审计配置，形成精确候选和批次预检 | 本任务尚未收到长期服务身份及范围；财报原生披露/可用时间、四 Publication、逐字段容差对账未通过。不得伪造 identity 或放宽 1% failover 规则 |
| T2 / EVID-01/02 | 可准备真实 owner/root/reviewer 输入，执行仍按上游和生产 envelope；历史零行/过期计数不冒充本轮盘点 | 新 current authority、真实审批与 PG 并发验收未收到；需主体及范围输入，不能以测试 fixture 替代 |
| T3 / AUD-03 | loader 能接受 off 配置不构成 writer 验收 | writer、recovery、archive/restore、告警、owner/reviewer 签署仍缺，依赖未通过时不启动生产演练 |
| T4 / STRAT-01/02 | `APPROVE-STRAT-20260915-01` 与 R1–R8 八份批准定义的 Git LF 内容哈希通过；Windows CRLF raw 差异单列，未重写批准文件 | canonical dry-run、精确 scope/current-head、append-only registration 未完成；PIT/OOS 时间不得压缩 |
| T5 / TUI-02 | 实测部署/容器已漂移；旧探针返回 DENY。已有每日 09:00 heartbeat 已更新为先按官方 collector 重绑 | **旧 09-30 eligible_at 不再适用于当前候选**。须先获得新 deployment attestation 和真实首样本，再累计 14 日；structured defects、101-task telemetry、backup、双角色 attestation、ALLOW 仍缺 |
| T6 / TAR-05 | 未执行负载、chaos 或生产并发变更；维持 inline 并发=1 的治理要求 | 独立 staging 地址/身份、资源/查询图、非付费 provider 和 owner 容量决定未提供；随后才可跑 1/5/10/20 负载与 14 日真实 telemetry |
| T7 / Research | **DATA-17 completed**：完整同源分支 4576/5032（90.9380%），1158 passed；[原始证据](../testing/research-domain-90-closure-2026-09-21.json) | 仅本地完整 Research unit 范围；未改生产 Domain，未宣称 Nightly/PG/生产验收 |
| QMT / 下游 | QMT 等券商权限；DATA-03/EVID-03/STRAT-03/AI-01 按 registry 依赖保留未完成 | 权限未提供，未发订单；上游完成只解锁执行，不自动宣称下游 completed |

## TUI 漂移证据与回滚边界

Web 当前 started_at=`2026-09-20T11:07:43.394733155Z`，Prometheus 当前
started_at=`2026-09-20T11:07:59.353500085Z`。旧 probe 显式传入
`EVID09_TUI02_FIRST_SAMPLE_AT=2026-09-16T07:31:34.667000Z`，真实退出 1：
`DENY: Web candidate changed after first sample`。本地 `--require-allow` 也退出 1、2/10 DENY。
后者是本地 artifact 检查，不是实时连续观察证明。容器启动时刻不能冒充首个业务样本。

当前未擅自运行旧候选 reset 或给新候选补日期；官方绑定器需要新 deployment attestation、
干净工作树和真实 retained checkpoint。原 cutover artifact 留作历史，registry 与现有 heartbeat
必须明确它失效，避免 09-30 自动继承。未删除任何 A/B Classic 模板。

代码修复与生产部署分开验收；配置修复必须产生新 successor，不能编辑历史 v14/v17 或回退为
superseded v13。失败保持旧 active 和完整历史；后续生产 action 只按候选、输入、停止线和
具体恢复点执行。本轮没有数据库恢复、业务数据删除、付费模型调用或交易。

## 当前 retained source 补查

使用已核实的当前 image/source 对只读 collector 作内存参数替换后，受保护的 HTTPS range query 实际返回 **401**；没有取得可接受的新首样本。凭据仅在 VPS 内使用，未回传或修改。
因此还须恢复受保护查询的凭据/认证路径并得到真实 HTTP 200 样本，再执行官方绑定；不能以容器启动时间推算新的 14 日到期日。证据：`docs/deployment/production-closure-retained-source-denial-2026-09-20.json`。

## AUD-05 仓库收口（2026-09-21 本地时间）

SQLite 154 passed、2 个 PG-only tests skipped；独立 PostgreSQL 16.14 八项全部通过且无 skips。源码前后 SHA 一致。runtime Domain 行覆盖 250/252=99.2063%，分支 91/92=98.9130%；combined 99.1279%，三者不混用。

增量 mypy 和全量债务门禁均 0，Black/isort 通过，Ruff 新增诊断 0（保留四条既有 UP042 Enum 提示）；migration check 无变更。架构检查实际覆盖 8 个改动生产文件和 874 新增行，boundary/audit 均 0；早先零文件对比已明确排除。63 current-data surfaces 和治理检查通过。

初始 failing-first run 仅保留代理摘要，后补 raw baseline replay 如实标为 retrospective；没有伪造原始红灯日志或时间。PG 仅为本地隔离 Config Center 模型的事务/并发测试，不是生产 PG 或全应用 migration 验收。完整日志、JUnit、覆盖率、运行配方、失败尝试说明与独立复核已嵌入封存 JSON。


## DATA-17 / T7 完整 Research 仓库收口（2026-09-21）

独立分支 `dev/test-research-domain-branch-coverage` 新增三份行为测试。完整 before/after 从
1060 → 1158 tests passed；分支从 4310/5032 → 4576/5032（90.9380%），
行覆盖 13083/13546（96.5820%）。63 个 Domain 源文件、原有 130 个测试文件
及既有排除行均未变。独立复核与 Black/isort/Ruff、current-data、registry/governance 通过。

DATA-17 active → completed，DATA-15 未重开，其他生产状态没有自动晋级。完整日志、JUnit、coverage JSON、
源码哈希、复核与主动终止的非验收测量均保存在[封存清单](../testing/research-domain-90-closure-2026-09-21.json)
引用的原始 ZIP。未修改生产 Python，因此本条没有增量 mypy 适用文件；AUD-05 的生产 Python 门禁已单独验证。

## AUD-05 代码复核补强（2026-09-21）

复核修复了完整配置值被修改、缺行或重复后仍可能用于密钥引用读取及后继配置继承的问题。
Domain 统一验证 profile 身份与完整值哈希；激活事务在锁定旧值后重复验证，并核对候选完整哈希、
revision 前后哈希及公共投影。存在多个 active profile 或同版本多个 snapshot 时拒绝读取。
corrective 命令支持仅含 secret_ref_patch 的 envelope，拒绝未知字段，并将 JSON/文件错误转为 CommandError。

真实先失败测试日志已保留；最终 SQLite 184 passed、2 PG-only skips，隔离 PostgreSQL 18 passed、0 skips。
runtime Domain 行覆盖 261/263（99.2395%）、分支 99/100（99%）；双 mypy 0、Black/isort 通过，
Ruff 无新增诊断（四条历史 UP042 保留），无迁移变化。架构检查分别覆盖完整性改动 4 文件/72 新增行
和命令提交 1 文件/39 新增行，均无 boundary/audit 违规。current-data、registry/governance 通过。

Luna max 独立复核通过，原始日志、源码哈希、JUnit 和覆盖率见[复核封存](../testing/config-center-review-fixes-2026-09-21.json)。
registry v141 → v142；AUD-05 保持 completed，生产状态及 DATA-17 不变。仅完成仓库修复，未部署或访问生产。
PostgreSQL 为隔离 Config Center 测试设置，不能替代生产恢复或全应用 migration 验收。

## 2026-09-21 当前生产只读重验

生产仍绑定 `439468482f457884db17da47d7566a5aac295842`、release `20260920184626` 和
Web image `sha256:ad885af0fbb5904f389cbe469403fd758901e0f4b62e88e0c8dab34e52315d71`；
仓库 `dev/next-development` 的 AUD-05 补强尚未部署。实际 HTTPS 为 health/db/ready=200、
decision-ready=503，release identity 匿名访问为 403。VPS root-only 监控凭据的认证查询仍返回 401，
因此 TUI-02 没有新首样本，旧窗口继续失效。

同一 `REPEATABLE READ READ ONLY` 快照显示活动 A 股范围为 5,565。quote、price、valuation 的
current Publication 均为 5,565/5,565；financial current head 仍只有 80，as-of 为 2026-04-29。
四 Publication no-execute dry-run 明确拒绝 `financial source announced_at is required`。
DATA-02 repair no-execute dry-run 在盘中按设计拒绝“无最近已完成交易日”，须收盘后重新执行。

Authority 表内已有历史行，但最大 actor validity 为 2026-09-16，最大 owner validity 为 2026-09-13；
当前 actor leaf、owner leaf 和可配对 head 均为 0。生产 v17 仍为 audit mode=off、outbox=false，
authority selector 缺失。不能把历史计数当成当前权限，也不能延长旧时间或自动生成 selector。

本次没有部署、登录、provider 请求、生产写入、profile 激活或 Publication 切换。DATA-02、
EVID-01/02、AUD-03 保持 awaiting_production，TUI-02 保持 active。完整命令、探针源码、原始输出、
哈希和限制见[2026-09-21 封存](../deployment/production-closure-revalidation-2026-09-21.json)。

## DATA-02 写路径授权与批次身份加固（2026-09-21）

Luna Max 独立审查发现，独立四 Publication rebuild、自由填写的 `--operator`、长批次只在起点校验授权，
以及只核对 stored count 的 quote/valuation 批次仍可留下绕过空间。仓库现已统一通过 Audit Application
只读预检验证精确 current authority；两个 execute 命令把 operator 绑定到服务器签发的 actor，长刷新在
provider、可用时刻修复和最终 publication 边界重复校验，quote/valuation 同时核对精确资产集合。

聚焦回归 120 passed；12 个生产文件增量 mypy 为 0，Black/isort/Ruff、63 个 current-data surfaces、
3,212 文件架构全扫描和治理一致性均通过。结构化证据见
[DATA-02 授权与批次预检封存](../testing/data02-authority-and-batch-preflight-hardening-2026-09-21.json)。
registry v143 → v144，DATA-02 仍为 awaiting_production。此次没有部署、provider 请求、生产写入、
profile 激活或 Publication 切换；真实 current authority、财报来源时间、授权分批回填与四 Publication
容差对账仍是生产退出条件。

## DATA-02 可恢复任务与定时写入加固（2026-09-21）

继续审计发现，旧 `backfill_active_a_share_core_data` 命令、对应 Celery 批次任务和定时全市场刷新
没有完整继承上一轮 current-fact/rebuild 路径的授权边界。现已要求命令显式 `--execute`，并把
operator 精确绑定服务器签发 actor；两个后台任务在读取 universe/provider 前校验 current authority，
授权有效期必须覆盖 Celery 硬时限和安全余量。可恢复批次还把 authority hash 纳入幂等键和 checkpoint，
在推进 cursor 前复核同一 actor/tenant/owner/head；quote 与 valuation 同时验证 returned/succeeded
资产集合的规范化、唯一性和精确相等。

聚焦单元回归 `49 passed`，PostgreSQL control-plane 组件回归 `2 passed / 2 skipped`；生产 Python
增量 mypy、全量债务、Celery/current-data 合同、架构及治理门禁通过。结构化证据见
[DATA-02 后台写入加固封存](../testing/data02-background-writer-hardening-2026-09-21.json)，原始聚焦日志见
[测试日志](../testing/data02-background-writer-hardening-2026-09-21.txt)。registry v144 → v145，
DATA-02 仍为 awaiting_production。上一份 v144 证据对“all execute paths”的概括由本记录纠正；
它实际覆盖 current-fact refresh 与独立 rebuild，本轮才补齐可恢复及定时入口。

完整 failed-symbol 集合、逐项 retry outcome 和精确恢复阶段仍缺少耐久模型：现有 checkpoint
`cursor_value` 上限 500 字符，任务响应也会截断错误。资产 universe 还没有冻结哈希，quote/valuation
身份结果也在底层 fact 写入后才返回；当前门禁能阻止错误批次发布，但不能证明错误 fact 零残留。
因此不得仅凭批次数量关闭 DATA-02，下一独立仓库单元须先补这些证据，再执行任何获批生产批次。
本次未部署、未调用 provider、未写生产、未切换 Publication。

## DATA-02 冻结 universe 恢复绑定（2026-09-21）

可恢复 backfill 过去只保存 numeric offset；若 active universe 在批次间增删或排序改变，旧 offset
可能跳过或重复资产。现将完整 universe 规范化、拒绝空白/重复、排序后按 canonical JSON 计算
SHA-256。首批 checkpoint 和 durable idempotency identity 同时绑定该 hash；任何非零 offset 必须
携带上一 checkpoint 的精确小写 digest，live universe 不一致时在 provider lookup 前以
`universe_hash_mismatch` 阻断并保持原 offset。管理命令会自动把首批 hash 传给后续批次。

聚焦回归 `57 passed`；结构化证据见
[DATA-02 冻结 universe 恢复绑定](../testing/data02-frozen-universe-resume-binding-2026-09-21.json)，
分阶段整改见[恢复证据计划](../plans/data02-resumable-recovery-remediation-2026-09-21.md)。registry
v145 → v146，DATA-02 仍为 awaiting_production。完整 failure-item/retry 耐久化、provider 身份校验
的写前/事务回滚，以及四 Publication 数值容差对账仍未完成。本次没有生产访问或写入。

## DATA-02 item-attempt 耐久存储基础（2026-09-21）

现有 aggregate cursor 只有 500 字符，Celery 响应错误预览只保留前 20 项，不能充当完整失败资产
与重试历史。仓库现新增 `SyncItemAttempt` 领域状态机、独立受保护 ORM 表和 0079 additive migration，
以 `(batch_id, asset_code, phase, attempt_number)` 保证每次重试一行。仓储先锁定稳定 batch，再允许
RUNNING 插入；单个 attempt 只允许一次 RUNNING→终态转换，普通 save/queryset update、delete 与
bulk mutation 均被拒绝。显式 recovery 可把遗留 RUNNING 标记为 INTERRUPTED，下一次重试使用
单调递增 attempt number；25 项失败集合测试证明记录不受 20 项响应预览影响。

聚焦控制面回归 `22 passed`；结构化证据见
[DATA-02 item-attempt 耐久存储基础](../testing/data02-item-attempt-store-foundation-2026-09-21.json)。
registry v146 → v147，DATA-02 仍为 awaiting_production。本提交只建立 durable store；quote、
valuation、price、financial、publication 的 begin/finish 接线、稳定 execution token、并发 Celery
冲突与 PostgreSQL 组件证据仍是下一独立单元，不能据此启动生产回填或关闭 DATA-02。本次没有
部署、provider 调用、生产写入或 Publication 切换。

## DATA-02 item-attempt 当前 denominator 规模收口（2026-09-22）

生产只读证据确认当前 denominator 已从历史 5,533 变为 5,565。本轮没有使用生产资产代码或生产
数据库，而是在 loopback、易失性 tmpfs 的 PostgreSQL 16 夹具中按相同 cardinality 和 canonical
universe 编码执行五阶段 attempt 形状。quote、valuation、price、financial、publication 各 5,565 条，
共 27,825 条成功终态；recovery 另精确转换 5,565 条 stale RUNNING，并保留 1 条 fresh RUNNING。

首轮默认 ORM mixed `bulk_update` 在异质 `stored_count` 下超过任务预算。仓储保留 batch→attempt
锁顺序、不可变字段校验和 updated-count fail-closed，并为 PostgreSQL 使用单事务
`UPDATE ... FROM (VALUES ...)`；SQLite 保留 ORM 回退。最终测量用 1–17 的异质 stored count 强制
覆盖 mixed 路径，耗时 2,417.54 秒，低于 3,500/3,600 秒软硬预算。list、aggregate、recovery 分别
为 1、3、3 次 execute；新增 relation 31,547,392 bytes，最终 batch 6,225 行，EXPLAIN 使用
`dc_item_attempt_state_idx`。

该结果只关闭仓库 cardinality、批量原子性、查询和恢复规模门，`production_acceptance=false`。
四 Publication 的 policy-hash 数值容差对账、真实 current authority 和明确生产写授权仍未满足，
DATA-02 继续 `awaiting_production`。完整指标、检查日志、生产范围哈希绑定和 Luna Max 复核见
[DATA-02 规模封存](../testing/data02-item-attempt-scale-closure-2026-09-21.json)。本轮没有部署、
provider 调用、生产写入、Publication 切换或容差放宽。

## DATA-02 四 Publication 数值容差证据契约（2026-09-22）

仓库已增加纯 Domain 数值容差策略与离线 Application 证据解析器。证据输入必须是 `select_only`，
并同时绑定冻结 universe、四个 Publication 的 id/hash/完整成员、P2 publication policy identity、
逐字段 canonical unit、绝对/相对容差和实际偏差。每个 Publication member 的每个治理字段必须恰好
出现一次；Publication hash、current UUID、冻结资产集合以及 canonical/observed 数值快照 hash 都会
重算。成员还须通过既有 required-evidence、quality 和时间顺序规则；替换成员、重复 fact、复用
identity、篡改对账值或使用歧义 JSON 都会 fail closed。

本轮纠正了“四类 Publication member_count 必须相等”的错误假设。验收使用独立
`covered_asset_count` 对齐 denominator；financial 可为同一资产发布多个指标，因此其 member_count
可高于资产数。最终 rebuild evidence 仍要求四类资产覆盖完整、Publication id/hash 唯一且总成员数
与结果一致。

仓库内数值策略 registry 故意保持 `awaiting_owner_approval` 且 `policies=[]`。测试使用的合成阈值
仅验证算法，默认 recorder 在真实 data owner 提供逐字段/单位/阈值及 approval receipt 前拒绝生成
证据；它不再接受调用方传入其他 registry 路径。由此只关闭“可审计的离线对账契约”这一仓库缺口，
没有完成任何真实生产数值对账。

聚焦回归 81 项、入口清单 20 项、增量和全量 mypy、Django/迁移、Celery、current-data、完整架构
与治理检查均通过；完整证据见
[DATA-02 四 Publication 容差契约封存](../testing/data02-four-publication-tolerance-contract-2026-09-22.json)。
registry v151 → v152，DATA-02 继续 `awaiting_production`。剩余门为真实 owner 策略批准、真实 current
authority、明确生产写授权、真实 provider 回填及真实四 Publication snapshot 对账。本轮没有部署、
provider 调用、生产数据库写入、Publication 切换、策略批准或容差变更。

## 生产只读阻断复核（2026-09-22）

在 DATA-02 容差契约提交并推送后，本轮通过 SSH stdin 重新流式执行既有只读探针，未在 VPS 落盘
脚本。生产仍为 `439468482 / 20260920184626`，落后于 `dev/next-development`；health、health/db、
ready 为 200，decision-ready 按设计为 503，release identity 外部入口仍为 403。

数据库探针在单一 `REPEATABLE READ READ ONLY` 事务中执行并显式 `ROLLBACK`。active A-share
denominator 仍为 5,565；quote、price、valuation current Publication 各 5,565 members，financial
仍为 80。历史 authority 行仍存在，但 temporally current actor、owner、joined actor-owner 均为 0；
v17 仍为 `audit.system_event.mode=off`、`outbox_enabled=false`，authority selector 不存在。

收盘后的 repair dry-run 已越过此前“盘中没有最近已完成交易日”的阻断，但在 provider 边界前因
`financial source announced_at is required` 停止；独立四 Publication dry-run 在同一证据缺口停止。
两条命令都未传 `--execute`，报告 `mutations_performed=false`。因此 session 时点阻断已排除，真实
财报披露时间/来源证据、owner 批准的容差策略、当前 authority 和明确生产写授权仍是恢复条件。

受保护 Prometheus query 使用 VPS root-only 凭据执行，但 authenticated/unauthenticated 仍同时为
401，`DENY_STOP_LINES` 不变；TUI-02 不能绑定新候选或启动 14 日窗口。完整证据与 17 项原始成员见
[2026-09-22 生产只读复核](../deployment/production-closure-revalidation-2026-09-22.json)，原始归档见
[raw archive](../deployment/production-closure-revalidation-2026-09-22-raw.zip)。registry v152 → v153；
DATA-02、EVID-01/02、AUD-03 状态不变，TUI-02 继续 active。本轮没有部署、provider 调用、生产写入、
profile 激活、Publication 切换或凭据输出。

## 版本并存与退役治理（2026-09-22）

仓库审计确认，当前 `apps/` 与 `core/` 非 migration Python 源码中有 24 组 `_vN` 并存模块，
分属五个家族：owner-assignment evidence V2–V5、provenance receipt V2–V5、只读 mapping V2–V3、
owner-tenant authority V1–V3，以及 core Evidence scope V1–V3。其中 Evidence、provenance 和
owner-tenant authority 三个写链家族仍保留多个版本的写能力；旧版不能仅因有新版
就直接删除，因为 append-only 历史行、内容哈希和历史审计读取仍须可重放，但“保留读取”也不能
成为永久保留旧写入口的理由。

新增 `governance/versioned_surface_retirement.json` 作为版本退役台账，逐家族固定 preferred current
version、仍存在的 write surface、保留读取版本、精确模块集合、真实 blocker 和分层退出门。目标顺序
统一为：先完成当前版本生产验收，再证明旧写调用方为零并删除旧写入口，最后在生产行盘点、备份恢复
和历史 hash replay 通过后才考虑删除 codec、reader 或表。EVID-01/02 未完成时，这五个家族继续
fail-closed；它们完成后，检查器会主动失败并要求复核退役动作，不能让 blocker 文案无限续期。

`scripts/check_versioned_surface_retirement.py` 会从源码重算所有并存组。新增 V6、出现未登记家族、
版本集合漂移、blocker 不存在或 blocker 已全部完成但台账未复核，都会使 CI 失败。Classic Web 单列
为关联退役面：TUI-02 未完成且唯一 `--require-allow` 命令未返回 ALLOW 前，`deletion_allowed=false`，
没有删除任何 A/B 模板。本次仅建立治理门禁和退役顺序，没有把历史兼容层误标为死代码，也没有
改动生产运行路径、数据库或任何 authority 记录。

首轮 GPT-5.6 Luna Max 只读复核为 P0=0、P1=0。首轮只覆盖 `_vN` 文件名家族；后续扩大审计后发现，
无后缀 V1、同文件内 schema 版本和 composition 默认路由不在扫描范围。治理 v2 因此新增六个显式旧面：
owner-assignment evidence 与 provenance 的无后缀 V1 到 preferred V5、physical-account row V1/V2、
simulated-account row V1/V2、Regime V1/V2，以及 Audit Authority schema/route V1/V2/V3。检查器还会
自动发现并核对 23 组“无后缀文件 + `_vN` 文件”集合；新增、删除或改变版本集合而不更新台账会失败。
每个旧面固定精确文件、版本角色和源码 marker，文件消失或 marker 漂移同样会失败。

Audit Authority 的 preferred version 是 V3，但默认 composition 当前仍为 V1；台账如实记录该差异并绑定
EVID-01/02。Account Evidence/Provenance 的 preferred version 是 V5，而默认 Authority V1 composition
当前仍读取 V3；这些差异均未用静态治理改写运行时默认值。六个旧面各有 zero-runtime-callers、生产行盘点、备份恢复、
历史 hash replay 四类机器可读证明槽，当前 24 项全部为 `pending`。只有真实 artifact 存在时才能标为
`verified`。旧 writer 不能据静态搜索直接认定可删；Regime V1 还受 STRAT-02 真实 PIT/OOS 时间窗口约束。
本轮证据见[显式旧面覆盖封存](../testing/versioned-surface-retirement-coverage-2026-09-22.json)。

针对“登记了新版本但继续堆叠旧版本”的缺口，退役治理 v6 冻结全部并存、读取和写入版本集合。
24 组 `_vN`、23 组无后缀并存模块、family/legacy retained-read 及 write surface 都必须与封存集合精确
一致；单纯同步台账不能让 V6、额外 writer 或提前删除的旧 writer 静默通过。数量不变也不能用新版本
替换旧版本；同文件 schema/composition marker 同样进入保留地板。测试覆盖了“登记 V3 后新增并存/
写版本”“以 V3 等量替换 V2”和“文件仍保留但从 write_surface_versions 移除 V1”三类绕过，均
fail closed。封存集合只能在对应
生产 blocker、zero-runtime-caller、生产行盘点、备份恢复、历史 hash replay 和单独退役复核完成后收缩。
保留地板不与可变 inventory 共存于同一对象，而是封存在
`governance/versioned_surface_retention_floor.json`；检查器固定其规范化 SHA-256
`ca333ec649368d7ec5dc993289e67d4a1be4fd00fba79e56b4b47c574e4fa35b`。同步修改 inventory 与
floor 会触发 digest mismatch；退役必须以单独提交显式重绑封存摘要，不能伪装成普通版本登记。

Luna Max 复核确认当前没有任何 V3/V4 或 Classic A/B 模板具备删除资格：Evidence/Provenance 的 V3
仍是 active default、V5 是 preferred；Audit 默认 composition 仍走 Authority V1；24 个退役证明槽
全部 pending；Regime V1 仍受 STRAT-02 的真实 PIT/OOS 积累约束；Classic 仍受 TUI-02 和
`--require-allow` 约束。因此本轮只关闭继续增生和等量替换绕过，没有删除历史实现或改变运行时路由。
结构化证据见[版本增生预算与保留地板封存](../testing/versioned-surface-growth-budget-2026-09-22.json)。

2026-09-23 的扩展复核发现，只有单一版本文件的 composition route 不会进入并行 basename 分组，
其中 Provenance V4 issuer 曾因此未被台账和 marker floor 冻结。检查器现在单独发现全部 singleton
versioned composition route，并要求它们归属显式 legacy surface；当前四条 route 已全部登记，包含
Provenance V4 writer、Audit Authority V3 reader，以及 simulated/physical V2 read composition。
删除文件、修改稳定 builder marker 或新增未登记 singleton route 都会使 CI 失败。本轮只补治理覆盖，
没有改变 route、读写版本或生产状态；结构化证据见
[singleton composition 退役门禁封存](../testing/versioned-singleton-composition-retirement-guard-2026-09-23.json)。

## DATA-02 财务响应正文范围绑定（2026-09-22）

仓库已把成功 Tushare 财务响应的 scope 从固定 `caller_declared / row_count=0` 改为正文验证。
成功留存前必须从原始响应的 `ts_code`、`end_date` 列证明请求资产、财政期和实际行数；缺列、
跨资产或非法日期会 fail closed，且不会生成成功审计。验证结果随原始 body SHA、大小和 EOF UTC
写入同一个加密不可变原件，并能从 store/audit round-trip 恢复
`response_scope_basis=provider_body_verified`。供应商业务拒绝继续保留 caller-declared 失败原件。

聚焦回归 147 项通过，新增 Domain 分支覆盖率 97.2%；Black、isort、Ruff、4 个生产文件增量
mypy、全量 mypy 债务门禁和 64 个 current-data contracts 均通过。结构化证据见
[DATA-02 provider 正文范围封存](../testing/data02-financial-provider-body-scope-2026-09-22.json)。
registry v154 → v155，DATA-02 仍为 `awaiting_production`。本轮未访问 provider、未部署、未写生产、
未切换 Publication，也没有补造 `announced_at`、`available_at` 或来源行身份。

## DATA-02 财务来源证据写前门禁（2026-09-22）

财务同步现提供显式 select-only source-evidence probe。它只获取并规范化 provider facts，随后按请求
资产、自然键唯一性、真实公告时间和 available/fetched 时间顺序做有界分类；不会写 FinancialFact、
Publication 或同步审计。决策证据不再信任 `extra` 中的自由字符串或仅格式正确的 UUID，而是要求
`FinancialFactDecisionEvidence` 直接持有已留存的 typed artifact reference，并逐 fact 绑定正文 SHA-256、
provider-body verified 请求/响应资产与期间范围、native asset/period/row identity。source raw hash 与
artifact body hash、source record id 与 native row id 任一不一致均 fail closed。Application verifier 还会
只读检查加密正文确实存在，且 capture 对应的成功 RawAudit 能精确重建同一 reference；仅构造一个形状
正确的 typed object 也不能越过门禁。

`SyncFinancialRequest` 的门禁默认开启且不能关闭。严格 execute 对同一次 fetch 得到的内存 facts 先
执行同一门禁，再决定是否 bulk_upsert，避免 probe 通过后重新请求导致证据漂移。current-fact refresh
对每个请求资产运行 probe，并核对 provider id 与资产 identity；不完整或错配 witness 会在 price、
quote、valuation 和 financial 规范化写入前以
`FINANCIAL_SOURCE_EVIDENCE_REQUIRED` 阻断。probe 成功也不把
financial fact 写入量冒充探测结果，返回值分别记录 `financial_probe_fact_count` 与兼容字段
`financial_probe_stored_count=0`。DATA-02 resumable backfill、on-demand financial hydration 和 Equity
financial Celery task 均经过该门禁。resumable backfill 在任何 quote、valuation、price 或 financial
writer 前对整批资产执行 `prepare_for_write`，后续只消费同一 prepared batch；任一资产证据不足时整批
返回 `outcome=blocked`、零 stored、游标不前移，并把已创建的 financial item attempts 置为 BLOCKED。
Celery 全量遇到同一门禁时也返回稳定 `blocked_reason`，而非伪装成 provider 成功。

通过门禁的 typed binding 使用 `financial-fact-decision-evidence.v1` 严格 JSON projection 随
FinancialFact 原子写入；migration 0082 对历史行只写空 projection，不补造证据。repository 重读会
完整重建 artifact scope 与 native row binding，未知键、旧 schema、坏 hash 或空 provider 都拒绝；
同一 raw body 上已有 binding 不能被替换或删除。verified body scope、basis 与 capture id 同时投影到
既有 Publication evidence 字段，避免内存门禁通过而持久化 current 候选再次丢证。

底层 canonical `bulk_upsert` 也强制要求同一 typed binding，旧 Equity `save_financial_data` 因无法提供
真实 retained artifact 会明确拒写；不能再绕过 Application 门禁。普通与 current financial Publication
candidate 在生成引用前必须严格解码持久化 binding，历史空 projection 只读保留但不能进入新发布。

当前 Tushare/AKShare financial adapters 仍只有 date-only report information，且尚未构造上述 typed
fact-to-artifact binding，因此严格路径会按设计 fail closed。该仓库单元不构成 provider 可用、生产回填
或 DATA-02 完成证明；下一步仍须从真实源取得精确公告/可用时间和 native row identity，并在 adapter
中构造真实绑定，之后才能在当前 authority、owner 批准容差和明确生产写授权下执行真实回填与四
Publication 对账。

最终相关回归 208 项通过、8 个仅 PostgreSQL 可运行的用例在 SQLite 跳过；Domain 新增分支覆盖率为
100%。Black、isort、Ruff、17 个生产文件增量
mypy、全量 mypy、64 个 current-data contracts、92 个 Celery contracts，以及 3,221 个源码文件的
完整架构门禁均通过。
结构化证据见
[DATA-02 财务来源证据写前门禁封存](../testing/data02-financial-source-evidence-prewrite-gate-2026-09-22.json)。
registry v155 → v156，DATA-02 继续 `awaiting_production`。本轮没有访问 provider、部署、生产写入、
Publication 切换或 authority/tolerance 变更。

## DATA-02 Tushare 留存正文与来源行绑定（2026-09-22）

Tushare 的 opt-in 财务响应 handler 现在返回 typed payload/reference pair；unified relay、REST path 和
routed SDK 三条 transport 路径把同一个 `FinancialResponseArtifactRef` 带到 adapter。adapter 按实际
`ts_code`、`end_date`、`ann_date` 和 metric 构造稳定的 canonical provider-row coordinate，并将每个
FinancialFact 绑定到已加密留存的原始 body SHA-256、正文验证后的资产/期间范围和同一个 native row
identity。该坐标是从真实 provider row dimensions 派生的事实坐标，不宣称是供应商提供的 opaque id。

`ann_date` 只有日期，不能证明公告时刻或业务可用时刻；adapter 因此继续保持 `announced_at=None`、
`available_at=None`。端到端测试覆盖 capture、加密留存、审计、adapter 和严格同步，确认阻断原因只剩
`financial_source_evidence_incomplete` 与 `financial_available_at_missing`，且 FinancialFact writer
零调用。治理契约也已把旧的“report date becomes available_at”描述改成“date-only report date 不具备
availability 权威性”。AKShare 仍未提供同等级 artifact/row binding。

本轮只完成可追溯绑定，没有把 DATA-02 改为完成。恢复生产回填仍需可信且 timezone-aware 的公告/
可用时间来源、当前 authority、owner 批准的容差、明确生产写授权和真实四 Publication 对账。本轮未访问
provider、未部署、未写生产、未切换 Publication，也没有补造来源时间。结构化证据见
[DATA-02 Tushare 留存行绑定封存](../testing/data02-tushare-retained-row-binding-2026-09-22.json)。
registry v157 → v158，DATA-02 保持 `awaiting_production`。

## 当前候选生产只读重验（2026-09-22，repository 24fa0ed90）

复用已封存探针，经 SSH stdin 对生产执行 release/HTTPS、PostgreSQL `REPEATABLE READ READ ONLY`、
两个无 `--execute` 的 DATA-02 dry-run 和 protected monitoring 检查；探针未在 VPS 落盘。生产仍为
`439468482 / 20260920184626`，Web/Prometheus 容器 identity 未变，health、db health、ready 为 200，
decision-ready 为设计内 503。仓库候选 `24fa0ed9029b208d0f225b1d4a3941774c22930e` 尚未部署。

数据库 denominator 仍为 5,565；quote、price、valuation current Publication 各 5,565 members，
financial 仍为 80。当前盘中 repair preview 在 provider 访问前按 completed-session 门禁停止；这不覆盖
上一份收盘后已到达 `financial announced_at` 门禁的证据。独立四 Publication preview 仍明确拒绝缺失
financial `announced_at`。当前 actor、owner、joined authority heads 均为 0；v17 audit mode 仍为 off、
outbox=false，authority selector 未激活。protected monitoring 使用 root-only credential 与匿名请求均为
401，因此没有绑定 retained sample、候选 rebind 或新的 14 日窗口。

结构化报告见[候选绑定生产只读重验](../deployment/production-closure-revalidation-2026-09-22-24fa0ed90.json)，
原始探针、输出和哈希清单见同名 `-raw.zip`。registry v158 → v159；DATA-02、EVID-01/02、AUD-03
状态不变，TUI-02 继续 active。本轮没有部署、provider 调用、生产写入、profile 激活或 Publication 切换。

## DATA-02 历史财务知识截止门禁（2026-09-22）

Factor 与 Alpha 的历史财务读取不再把 `period_end <= trade_date` 当作“当日已知”。新增决策专用
Application Port `get_financial_facts_for_decision`，其 date-only 契约只适用于中国市场日开盘前：
知识截止为上海时区决策日 00:00 对应的精确 UTC 瞬间。Repository 除报告期上界外，同时要求真实
`announced_at`、`available_at` 非空且均不晚于截止时刻；不会用 `report_date`、`period_end` 或
`fetched_at` 补缺。raw 历史查询继续保留原报告期兼容语义，盘中或收盘决策必须另建接受 aware
datetime 的显式端口，不能放宽日期接口。

回归覆盖截止点相等纳入、晚 1 秒排除、较新报告尚不可知时回退旧合格报告、来源时间缺失、naive
cutoff，以及 Tushare、AKShare、Alpha 三条决策调用。Luna Max 最终只读复核为 P0=0、P1=0。
该单元关闭仓库后视偏差路径，但不证明生产 source-time 已补齐；现有生产旧行缺失真实公告/可用时间时
会按设计返回空，DATA-02 继续 `awaiting_production`。结构化证据见
[历史财务知识截止封存](../testing/data02-financial-decision-knowledge-cutoff-2026-09-22.json)。
本轮没有 provider 调用、部署、生产/本地业务数据写入或 Publication 切换。

## 候选 f9a96b611 生产只读重验（2026-09-22）

当前仓库候选 f9a96b611 相比生产 439468482 已领先 27 个 commit；生产仍运行
/opt/agomtradepro/releases/source-20260920184626，Web/Prometheus healthy 且无重启，
公网 health、db health、ready 为 200，decision-ready 按设计保持 503。冻结 A 股分母仍为
5,565；quote、price、valuation 的 current Publication 各有 5,565 members，financial 仍为 80。

本轮在收盘后执行两个无 --execute 的只读预检。repair 与独立四 Publication dry-run 均越过
session-time 门，并在 provider 调用前以 financial source announced_at is required fail closed。
current actor、owner、joined authority heads 仍为 0；v17 仍为 audit mode=off、outbox=false、
selector absent。受保护监控使用 root-only 凭据与匿名请求仍均返回 401，因此 TUI-02 不能重绑首样本。

结构化证据见[候选 f9a96b611 生产只读重验](../deployment/production-closure-revalidation-2026-09-22-f9a96b611.json)，
原始探针、输出及哈希清单见同名 -raw.zip。registry v161 → v162；DATA-02、EVID-01/02、
AUD-03 状态不变，TUI-02 继续 active。本轮没有部署、provider 调用、生产写入、profile 激活或
Publication 切换。

## DATA-02 successor 候选与全集范围绑定 v2（2026-09-22）

复核发现旧 successor recorder 把历史 `5,533` 写成代码常量，且仅校验 checkpoint 内部的计数自洽；
即使升级 schema，输入仍可同时替换 denominator 与 universe hash。现在 v2 parser 要求调用方独立固定
source commit、release id、image digest，以及 canonical universe schema、当前分母 `5,565` 和 SHA-256
`4b9bfd44941336ed45d302d4c0f1cb53b7bfce025cff377ffa14a5ae8f792c22`。候选三元组或全集三元组任一
替换都会在记录前 fail closed。

repair、completed-session price request 与四 Publication 的 asset count 共享该固定分母；完整 dataset 的
asset-code hash 必须等于固定全集 hash。每个 dataset 另带实际 `member_count`，顶层总数必须精确等于四项
之和，因此 financial 多指标成员不会再被错误等同于资产数。历史 v1/5,533 原件保持只读历史状态，
不会被自动升级为 v2 生产证据。

TDD red、25 项聚焦回归、类型与治理门禁以及 Luna Max 最终复核写入
[DATA-02 successor 范围绑定封存](../testing/data02-successor-scope-binding-v2-2026-09-22.json)。
registry v162 → v163，DATA-02 继续 `awaiting_production`。本轮没有连接 provider/VPS/数据库，没有部署、
生产写入、Publication 切换或 authority/tolerance 变更。

## DATA-02 successor readiness 派生门禁（2026-09-22）

后续审查发现 v2 recorder 虽已绑定候选和全集，但仍信任输入自报的 `financial.safe_to_execute` 与
`ready_without_provider_refresh`。历史 v1 原件本身就同时记录 288,409 条 missing/eligible financial
rows 和 `safe_to_execute=true`，证明该字段不能独立作为信任根。

parser 现在从五类财务阻断计数重新推导安全状态，并从财务安全、completed-session price 和四
Publication coverage 三项重新推导无需 provider refresh 的 readiness。`data02_execution_ready=true`
还必须绑定 `DATA-04 production revalidation=passed`。测试覆盖自报安全值、复合 readiness、价格与
Publication 已全绿但财务仍不安全、DATA-04 blocked，以及一致全绿预执行投影。

TDD red、30 项聚焦回归、类型与治理门禁及 Luna Max 复核封存在
[DATA-02 successor readiness 证据](../testing/data02-successor-derived-readiness-2026-09-22.json)。
registry v163 → v164，DATA-02 继续 `awaiting_production`；没有 provider/VPS/数据库访问、部署、生产
写入、Publication 切换或 authority/tolerance 变更。

## 候选 4e36b6604 生产只读重验（2026-09-22）

当前仓库候选 `4e36b6604` 比生产 `439468482 / 20260920184626` 领先 30 个 commit。生产 Web 与
Prometheus 容器仍 healthy 且无重启；公网 health、db health、ready 为 200，decision-ready 按设计为
503。冻结 A 股分母仍为 5,565，quote、price、valuation current Publication 各有 5,565 members，
financial 仍为 80。

两个无 `--execute` 的 DATA-02 预检均在 provider 调用前因 `financial source announced_at is required`
fail closed。temporally current actor、owner、joined authority heads 仍全部为 0；v17 audit mode=off、
outbox=false、selector absent。受保护监控的凭据请求与匿名请求仍均为 401，因此 TUI-02 不能绑定首样本。
当前 successor readiness、来源证据写前门禁与版本退役治理均尚未部署，不能用仓库绿灯替代生产验收。

结构化证据见[候选 4e36b6604 生产只读重验](../deployment/production-closure-revalidation-2026-09-22-4e36b6604.json)，
原始探针、输出和哈希清单见同名 `-raw.zip`。Luna Max 最终复核为 P0=0、P1=0。registry
v164 → v165；DATA-02、EVID-01/02、AUD-03 状态不变，TUI-02 继续 active。本轮没有部署、provider 调用、生产写入、profile 激活或
Publication 切换。

## DATA-02 财务来源时间原件绑定（2026-09-22）

后续代码审查发现，v1 `FinancialFactDecisionEvidence` 只证明 `fina_indicator` 财务正文存在，不能证明
调用方附加的 `announced_at` / `available_at` 来自独立来源。现在 decision evidence v2 额外绑定独立
source-time artifact、财务公告日、来源行标识与投影 SHA-256、受治理匹配契约 id/version/SHA-256，且
`matched_row_count` 必须严格等于 1。Application verifier 接收完整 decision evidence，同时读取财务与
来源时间两份留存正文和审计记录，
重新解析并重算匹配；直接 canonical repository 写入若未注入独立 verifier，同样在 DML 前拒绝。
普通和 current Publication 候选也会重新调用同一个完整 decision-evidence verifier；即使有人绕过
repository 直接写入一组内部自洽的 ORM 字段，没有独立复验器仍不能取得发布资格。

`available_at` 只接受 `provider_native_exact`，不把 response completion 当作 provider 时间。历史 v1 JSON
仍可读取，但不能进入 current Publication。Tushare 官方 `fina_indicator` 只有 date-only `ann_date`，官方
`anns_d` 是独立接口并提供可选 `rec_time`，没有可据此自动绑定财务期间的结构化关系；因此代码禁止按
同一资产/日期选择最早或最新公告。真实 provider contract、公告原件留存与唯一匹配实现尚不存在，当前
adapter 和 production composition 继续 fail-closed，DATA-02 保持 `awaiting_production`。

GPT-5.6 Luna Max 在发布复验修复前的最终审查为 P0=0、P1=1：typed witness 仍是声明式边界，且仓库
没有具体的双原件读取、审计核对与重算实现。本轮关闭了 Publication 绕过面，但不能把 verifier callback
测试替身当作真实实现；该 P1 将持续到 provider-specific source-time repository/verifier 落地并接入
composition 后才可关闭。

结构化证据见
[财务来源时间原件绑定封存](../testing/data02-financial-source-time-artifact-binding-2026-09-22.json)。
本轮没有 provider/VPS/数据库访问、部署、生产写入或 Publication 切换。

## DATA-02 财务来源时间 contract 注册门（2026-09-22）

继续修复 Luna Max 保留的 P1 时，先关闭 contract 声明面。新增的 Domain contract 必须以 canonical
SHA-256 绑定 provider、两个 dataset、endpoint、parser、时区、来源行和 timestamp 字段，并同时包含
资产、财政期末、公告日期三项 join 语义；因此当前公开字段缺少 period 关系的 Tushare `anns_d` 不能只按
`ts_code+ann_date` 注册成 exact contract。严格 JSON registry 只在 `status=active` 且存在非空、唯一、
内容哈希一致的 contract 时返回 exact lookup。

仓库 registry 当前仍为 `awaiting_owner_approval`、`contracts=[]`，所以没有新增正向来源时间路径。
这一阶段尚未实现 source-time encrypted-body reader、唯一且 content-hash 完整的 RawAudit 查询、具体 matcher
或 production composition 接线；P1 继续保留，DATA-02 继续 `awaiting_production`。本轮一次 SSH stdin
只读重验因远端未返回而被本地中止，随后公网 health/db/ready 为 200、decision-ready 重试为 503；没有
将这组不完整观测封存成生产候选验收，也没有执行 provider 或生产写入。

## DATA-02 双原件独立复验（2026-09-22）

上一节保留的具体实现 P1 已关闭。生产代码现在用一套共享 verifier 读取两份 authenticated encrypted
body，逐份核对长度/SHA-256，并要求 capture UUID 各自只有一条 canonical content-hash 完整的 RawAudit。
审计能力、provider、row count、完成时间、parser、payload size 和 typed artifact link 全部精确匹配；
两条 audit link 的 provider row id 必须相同，防止同名 provider 配置被混用。

同一个 verifier 已接入严格 financial sync、backfill、on-demand/current refresh、普通 Publication 与
current Publication。Luna Max 首轮终审发现 provider id equality 缺口后，新增红测证明原实现会误接受
7/8 两个不同 id；修复后 22 项聚焦测试和 48 项相关回归通过，最终复核 P0=0、P1=0。

仓库中的 contract registry 仍为 `awaiting_owner_approval`，provider matcher 表仍为空，因此本次接线不会
放行任何真实来源时间写入。DATA-02 状态保持 `awaiting_production`；仍需真实 owner-approved contract、
provider-specific matcher 与 source-time producer、current authority、生产写授权和四 Publication 对账。
结构化证据见
[双原件独立复验封存](../testing/data02-financial-source-time-independent-verifier-2026-09-22.json)。
本轮没有 provider/VPS/数据库访问、部署、生产写入或 Publication 切换。

## 候选 77531f42d 生产只读重验（2026-09-23）

当前仓库候选 `77531f42d` 比生产 `439468482 / 20260920184626` 领先 34 个 commit。生产 Web 与
Prometheus 容器仍 healthy 且无重启；公网 health、db health、ready 为 200，decision-ready 按设计为
503。冻结 A 股分母仍为 5,565，quote、price、valuation current Publication 各有 5,565 members，
financial 仍为 80。

两个无 `--execute` 的 DATA-02 预检均在 provider 调用前因 `financial source announced_at is required`
fail closed。temporally current actor、owner、joined authority heads 仍全部为 0；v17 audit mode=off、
outbox=false、selector absent。受保护监控的凭据请求与匿名请求仍均为 401，因此 TUI-02 不能绑定首样本。
已评审的 contract registry、双原件复验与 composition 接线尚未部署；registry 仍无 owner-approved
contract，matcher 表为空，不能把仓库绿灯当成生产验收。

结构化证据见
[候选 77531f42d 生产只读重验](../deployment/production-closure-revalidation-2026-09-23-77531f42d.json)，
原始探针、输出与哈希清单见同名 `-raw.zip`。registry v169 → v170；DATA-02、EVID-01/02、AUD-03
状态不变，TUI-02 继续 active。本轮只通过 SSH stdin 执行只读事务和无 execute 预检，没有部署、
provider 调用、生产写入、profile 激活或 Publication 切换。

## DATA-02 财务来源时间原件留存（2026-09-23）

双原件复验此前已经要求一份独立的 source-time body 与唯一 RawAudit，但仓库还没有生产方可调用的
留存边界。本轮以红测起步，新增 contract-neutral retainer：配置好的 encrypted body store 生成唯一
dataset/location/format/key/body-digest reference，Application 用例先读取完整 audit cardinality，再保存
原始字节并追加 canonical content-hash RawAudit。相同 capture 只有完整 reference、provider row id、
redacted request projection 和 audit 元数据全部一致时才能幂等重放；重复 audit 直接 fail closed。若正文
成功而 audit 追加失败，异常只暴露 opaque reference，reconciliation 可区分 verified orphan 与多审计歧义。
Luna Max 终审发现原先的 find-before-append 在并发下可能产生两条 audit；迁移 0083 增加 capture UUID
主键 claim，原子 repository 在 claim 事务内重新查询并只允许首个 writer 追加。并发完全相同请求复用同一
RawAudit，parser 或其他 canonical 内容漂移则拒绝。
最终只读复核为 P0=0、P1=0；保留的 P2 是生产接线只能使用 retainer facade，并在获准的 PostgreSQL
目标上重跑并发组件用例。

该路径不会构造 `FinancialSourceTimeWitness`，不会从 `ann_date`、`NOTICE_DATE`、period end、fetch time
或 response completion 推断 `announced_at/available_at`。owner-approved contract registry 仍为空，matcher
表仍为空，因此没有新增可放行的 provider 路径。30 项聚焦/相关测试（含双连接并发组件用例）、7 个
非 migration 生产文件增量 mypy、完整
mypy debt、Black/isort/Ruff 与 68 个 current-data surface 均通过。

GPT-5.6 Luna Max 同时复核版本化增生：本切片没有新增 `_vN` 平行模块；link/parser 中的 `v1` 是不可变
审计契约标识。Evidence/Provenance 的 V3/V4 路径仍有真实 runtime caller，Authority V3 是 preferred，
Audit 默认 composition 仍走 Authority V1，24 个 retirement proof 仍待完成；EVID-01/02、STRAT-02 和
TUI-02 分别约束 authority、Regime 与 Classic 清理。当前没有旧实现或 Classic A/B 模板满足删除条件。

结构化证据见
[财务来源时间原件留存封存](../testing/data02-financial-source-time-artifact-retention-2026-09-23.json)。
registry v170 → v171，DATA-02 保持 `awaiting_production`。本轮没有 provider/VPS/生产数据库访问、
部署、生产写入、Publication 切换、contract/matcher 激活或旧版删除。


## 候选 e59baf2ee8 生产只读重验（2026-09-23）

当前仓库候选 `e59baf2ee8` 比生产 `439468482 / 20260920184626` 领先 36 个 commit。生产 Web 与
Prometheus 容器仍 healthy 且无重启；公网 health、db health、ready 为 200，decision-ready 按设计为
503。冻结 A 股分母仍为 5,565，quote、price、valuation current Publication 各有 5,565 members，
financial 仍为 80。

两个无 `--execute` 的 DATA-02 预检继续在 provider 调用前因 `financial source announced_at is required`
fail closed。temporally current actor、owner、joined authority heads 仍全部为 0；v17 audit mode=off、
outbox=false、selector absent。受保护监控的凭据请求与匿名请求仍均为 401，因此 TUI-02 不能绑定首样本。
source-time retainer 与 capture claim migration 0083 尚未部署，contract registry 仍无 owner-approved
contract，matcher 表为空，不能把仓库绿灯当成生产验收。

结构化证据见
[候选 e59baf2ee8 生产只读重验](../deployment/production-closure-revalidation-2026-09-23-e59baf2ee8.json)，
原始探针、输出与哈希清单见同名 `-raw.zip`。registry v171 → v172；DATA-02、EVID-01/02、AUD-03
状态不变，TUI-02 继续 active。本轮只通过 SSH stdin 执行只读事务和无 execute 预检，没有部署、
provider 调用、生产写入、profile 激活或 Publication 切换。

## DATA-02 财务来源时间 owner 审批绑定（2026-09-23）

后续审查发现 contract registry v1 的激活条件只要求 `status=active`、非空合约和各合约内容哈希，
没有把真实 owner receipt 绑定到精确的合约集合。若未来人工只改 status，或者审批后替换、增删合约，
loader 无法证明当前集合就是被批准的集合。

registry v2 新增 typed approval，要求 UTC 整秒审批时间、owner 标识、receipt SHA-256 和
`contract_set_sha256`。集合摘要只接受已经逐项通过 Domain 校验且内容寻址的 contract digest，排序不影响
结果，增删或替换任一合约都会失配。JSON loader 另外要求 canonical `Z` 文本，frozen direct construction
要求 zero-offset UTC datetime 与整秒精度；pending 状态必须保持 `contracts=[]`、`approval=null`，active
缺失 approval 或 approval 指向其他集合时失败关闭。

仓库登记仍为 `awaiting_owner_approval`、空合约和空 approval，因此没有 provider 被授权，也没有新增
matcher 或 source-time producer。receipt digest 只证明登记值符合内容锚点格式，不证明签署人是真实当前
owner，也不代替 authority 时效核验。真实 contract、receipt、provider 原始样本、时区和唯一 join 语义仍需
业务主体提供后才能继续接线。

结构化证据见
[owner 审批与合约集合绑定封存](../testing/data02-financial-source-time-owner-approval-binding-2026-09-23.json)。
registry v172 → v173，DATA-02 保持 `awaiting_production`。本轮没有 provider/VPS/数据库访问、部署、
生产写入、Publication 切换或 contract 激活。

## DATA-02 财务来源时间 matcher 精确路由（2026-09-23）

继续审查 production composition 时发现，私有 matcher 表只以 `parser_version` 为键。两个 provider 或
两份受治理 contract 如果复用同一个 parser 标签，严格 registry 虽然已经选出正确 contract，composition
仍可能取得另一份 contract 的 matcher。

matcher 表现在只接受完整的 `FinancialSourceTimeContractIdentity`：provider、contract id、contract
version 与 contract SHA-256。parser、endpoint、时区、join 和 projection 已由 contract digest 绑定，
不再建立第二套原始字段键，也不加入运行时 ProviderConfig 行号。没有 parser-only fallback；遗留字符串键
只会 lookup miss 并失败关闭。synthetic 回归用相同 parser 标签的两个 contract 证明各自只命中自己的
matcher，未登记 contract 即使 parser 相同也返回空。

仓库 matcher 表仍为空，contract registry 仍为 pending，因此没有真实 provider 路径被激活。结构化证据见
[matcher 精确路由封存](../testing/data02-financial-source-time-exact-matcher-routing-2026-09-23.json)。
registry v173 → v174，DATA-02 保持 `awaiting_production`。本轮没有 provider/VPS/数据库访问、部署、
生产写入、Publication 切换或 contract/matcher 激活。

## 候选 67cfef48f0 生产只读重验（2026-09-23）

当前仓库候选 `67cfef48f0` 比生产 `439468482 / 20260920184626` 领先 40 个 commit。生产 Web 与
Prometheus 容器仍 healthy 且无重启；公网 health、db health、ready 为 200，decision-ready 按设计为
503。冻结 A 股分母仍为 5,565，quote、price、valuation current Publication 各有 5,565 members，
financial 仍为 80。

两个未传 `--execute` 的 DATA-02 预检继续在 provider 调用前因
`financial source announced_at is required` fail closed。temporally current actor、owner、joined
authority heads 仍全部为 0；v17 audit mode=off、outbox=false、selector absent。受保护监控使用
root-only 凭据与匿名请求仍均返回 401，因此 TUI-02 不能绑定首样本或启动新的观察窗口。

结构化证据见
[候选 67cfef48f0 生产只读重验](../deployment/production-closure-revalidation-2026-09-23-67cfef48f0.json)，
原始探针、输出与哈希清单见同名 `-raw.zip`。registry v174 → v175；DATA-02、EVID-01/02、AUD-03
状态不变，TUI-02 继续 active。本轮只通过 SSH stdin 执行只读事务和无 execute 预检，没有部署、
provider 调用、生产写入、profile 激活或 Publication 切换。

## DATA-02 审批时间直接构造收紧（2026-09-23）

Luna Max 复核发现，JSON loader 已拒绝带小数秒的审批时间，但 frozen approval 对象的直接构造只验证
UTC offset，没有拒绝非零微秒。直接构造现在也要求整秒，并增加 JSON `.000001Z` 与 Python datetime
微秒输入的回归；两条入口在 UTC 整秒语义上保持一致，同时保留 loader 独有的 canonical `Z` 文本约束。

结构化证据见
[审批时间直接构造封存](../testing/data02-financial-source-time-direct-approval-timestamp-2026-09-23.json)。
registry v175 → v176，DATA-02 保持 `awaiting_production`。仓库 contract registry 仍为 pending、空 contract、
空 approval；本轮没有 owner/provider 授权、生产访问、部署、生产写入或 Publication 切换。

## 候选 4e8c4ec7d9 生产只读重验（2026-09-23）

当前仓库候选 `4e8c4ec7d9` 比生产 `439468482 / 20260920184626` 领先 42 个 commit。生产 Web 与
Prometheus 容器仍 healthy 且无重启；公网 health、db health、ready 为 200，decision-ready 按设计为
503。冻结 A 股分母仍为 5,565，quote、price、valuation current Publication 各有 5,565 members，
financial 仍为 80。

两个未传 `--execute` 的 DATA-02 预检继续在 provider 调用前因
`financial source announced_at is required` fail closed。temporally current actor、owner、joined authority
heads 仍全部为 0；v17 audit mode=off、outbox=false、selector absent。受保护监控使用 root-only 凭据与
匿名请求仍均返回 401，因此 TUI-02 不能绑定首样本或启动新的观察窗口。

结构化证据见
[候选 4e8c4ec7d9 生产只读重验](../deployment/production-closure-revalidation-2026-09-23-4e8c4ec7d9.json)，
原始探针、输出与哈希清单见同名 `-raw.zip`。registry v176 → v177；DATA-02、EVID-01/02、AUD-03
状态不变，TUI-02 继续 active。本轮只通过 SSH stdin 执行只读事务和无 execute 预检，没有部署、
provider 调用、生产写入、profile 激活或 Publication 切换。

## 候选 fff17ee7b3 部署后生产只读重验（2026-09-23）

生产现已运行探针时仓库 HEAD `fff17ee7b3`，release `20260923130829`，Web OCI revision、镜像 tag、只读
manifest 与该提交一致。封存前 `dev/next-development` HEAD 并发推进到 `102012c05`，因此生产此时落后
1 个提交。公网 health、db health、ready 为 200，decision-ready 按设计为 503；
冻结 A 股分母仍为 5,565，quote、price、valuation current Publication 各有 5,565 members，financial
仍为 80。

两个未传 `--execute` 的 DATA-02 预检现在都在 publication candidate 查询边界拒绝缺少持久化 financial
decision evidence，没有进入 provider refresh 或写入。Actor/User/RBAC ledger 行数增至 34/23/23，但
actor 最新有效期已于 `2026-09-23T06:57:20.867754Z` 结束，temporally current actor、owner、joined
authority heads 仍全部为 0。v17 audit mode=off、outbox=false、selector absent。

受保护监控首次探针出现一次 `TimeoutError`；同一只读探针的留存重试完成，认证与匿名请求仍均返回 401，
因此不能绑定 TUI-02 首样本。结构化证据见
[候选 fff17ee7b3 部署后生产只读重验](../deployment/production-closure-revalidation-2026-09-23-fff17ee7b3.json)，
原始探针、首次超时、重试输出与哈希清单见同名 `-raw.zip`。

registry v177 → v178；DATA-02、EVID-01/02、AUD-03 状态不变，TUI-02 继续 active。部署关闭了
上一轮“候选尚未部署”门槛；新增 `102012c05` authority-renewal 候选尚未部署，真实 owner contract/receipt、retained provider sample、matcher/producer、approved
tolerances、current authority、生产写授权和真实四 Publication 对账仍缺失。本轮验证没有 provider 调用、
生产数据写入、profile 激活或 Publication 切换。

## 生产 revision a3c41d1eb0 只读重验（2026-09-24）

生产现运行 `a3c41d1eb0`，release `20260924145747`；探针采集时 `dev/next-development` HEAD 为
`d21202318`，最终封存时已推进到 `2b2235efb`，生产落后 8 个提交。公网 health、db health、ready 为 200，decision-ready 按设计为
503。A 股有效分母由 5,565 增至 5,569，但 quote、price、valuation current Publication 仍各有
5,565 members，financial 仍为 80，四 Publication 尚未覆盖新分母。

生产 profile v18 已激活并绑定 `release_ref=2a06333c1d92b2aca6e64a4497c6845d6e359759`。审计链路出现
实质进展：mode=`required`、outbox=`true`、authority selector 已设置，temporally current
actor、owner、joined heads 均为 1，有效期至 2026-10-01。该快照仍不能替代 EVID-01/02 与 AUD-03
要求的精确 PostgreSQL 并发、writer/recovery、archive-restore 和告警验收，相关状态暂不晋级。

两个未传 `--execute` 的 DATA-02 预检仍在 publication candidate 边界拒绝缺少持久化 financial
decision evidence，没有进入 provider refresh 或写入。受保护监控探针及留存重试均返回 `URLError`，
因此未取得可判定的认证状态，也不能绑定 TUI-02 首样本或启动观察窗口。

结构化证据见 [生产 revision a3c41d1eb0 只读重验](../deployment/production-closure-revalidation-2026-09-24-a3c41d1eb0.json)，原始探针、
输出和哈希清单见同名 `-raw.zip`。registry v178 → v179；DATA-02、EVID-01/02、AUD-03 状态不变，
TUI-02 继续 active。本轮只执行 SSH stdin 只读事务和无 execute 预检，没有 provider 调用、生产数据
写入、profile 激活或 Publication 切换。

## 生产 revision a6f591a418 只读重验（2026-09-25）

生产已推进到 `a6f591a418`，release `20260925023307`；探针采集时仓库 HEAD 为 `ff4d81a0c`，
最终封存时 `dev/next-development` HEAD 为 `f4de5dfa2d`，生产落后 41 个提交。公网 health、db health、ready 为 200，decision-ready 按设计为
503，release-identity 端点为 403。A 股有效分母仍为 5,569；quote、price、valuation current
Publication 已刷新到各 5,557 members，但仍比有效分母少 12，financial 仍只有 80。

生产 profile v18 继续绑定 `release_ref=2a06333c1d92b2aca6e64a4497c6845d6e359759`。audit
mode=`required`、outbox=`true`、authority selector 有效，temporally current actor、owner、joined heads
仍为 1/1/1，有效期至 2026-10-01。该快照仍不等于 EVID-01/02 与 AUD-03 的精确 PostgreSQL
并发、writer/recovery、archive-restore 和告警验收。

两个未传 `--execute` 的 DATA-02 预检均超过 180 秒观察上限，没有返回结构化结果。此次验证没有观察到
成功写入，也没有复现上一轮立即拒绝 financial decision evidence 的结果，因此把它记录为新的预检可操作性
阻塞，不能据此推断生产 gate 已放行。受保护监控首次为 `TimeoutError`，留存重试的凭据和匿名请求均为
401、`DENY_STOP_LINES`，TUI-02 仍不能绑定首样本或启动观察窗口。

结构化证据见 [生产 revision a6f591a418 只读重验](../deployment/production-closure-revalidation-2026-09-25-a6f591a418.json)，原始探针、
输出和哈希清单见同名 `-raw.zip`。registry v180 → v181；DATA-02、EVID-01/02、AUD-03 状态不变，
TUI-02 与 DATA-18 继续 active。验证 harness 没有直接调用 provider 或执行生产写入；由于两个 no-execute
子进程超时，其内部是否到达 provider/写路径未决。没有观察到 profile 激活或 Publication 切换。

## 生产 revision 9c77c51182 只读重验（2026-09-26）

生产已推进到 `9c77c51182`，release `20260925201025`；探针采集时 `dev/next-development` HEAD 为
`db5197f6f6`，生产落后 18 个提交。公网 health、db health、ready 为 200，decision-ready 按设计为
503，release-identity 为 403。A 股有效分母仍为 5,569；quote、price、valuation current Publication
仍各为 5,557，financial 仍为 80，覆盖与 freshness 没有推进。

生产 profile v19 已绑定部署 revision `9c77c51182`。audit mode=`required`、outbox=`true`、selector
有效；temporally current actor、owner、joined heads 从 1/1/1 增至 2/2/2，actor 有效期至
2026-10-09，owner authority 有效期至 2027-09-12。该变化证明当前身份可用性增加，但仍不能替代
EVID-01/02 与 AUD-03 所需的 PostgreSQL 并发、writer/recovery、archive-restore、告警和真实验收。

部署 revision 的 source-time contract 与 numeric tolerance registry 均仍为 `awaiting_owner_approval`、零条目，
approval 缺失，exact matcher registry 为空；本次也没有观察到 retained real provider sample 或显式生产写授权。

未传 `--execute` 的 repair 预检在交易时段以 `latest completed China market session is unavailable during
live trading` 结构化失败关闭，并报告没有写入。未传 `--execute` 的 Publication 预检仍超过 180 秒，
没有结构化结果，其内部是否到达 provider/写路径未决。受保护监控连续两次对凭据和匿名请求均返回 401、
`DENY_STOP_LINES`，TUI-02 仍不能绑定首样本或启动观察窗口。

结构化证据见 [生产 revision 9c77c51182 只读重验](../deployment/production-closure-revalidation-2026-09-26-9c77c51182.json)，原始探针、输出和哈希清单
见同名 `-raw.zip`。registry v181 → v182；DATA-02、EVID-01/02、AUD-03 状态不变，TUI-02 与
DATA-18 继续 active。本轮验证没有部署、profile 激活或 Publication 切换。
