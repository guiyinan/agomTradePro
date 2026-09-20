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
| T7 / Research | 历史全 Domain 分支基线 4310/5032（85.6518%），达到 90% 至少 4529 条 | AUD-05 唯一仓库焦点释放后另起测试主线；同源全量 before/after 测量，不累加历史切片 |
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
