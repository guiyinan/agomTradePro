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
