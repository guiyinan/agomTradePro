# 关键可靠性测试补齐计划

> 日期：2026-07-22
> 状态：代码实施完成，本地 SQLite 与 GitHub PostgreSQL Nightly 已验证；真实 QMT 因券商外部 XtQuant 权限阻断
> 主线：测试与可靠性治理收口

## 目标

把现有分散测试收拢为可阻断发布的关键链路测试，重点保护：

```text
数据 → 决策快照 → 风险检查 → 订单审批 → Agent 执行 → 回报对账
```

初始首要缺口（已于实施阶段关闭）是增量测试选择器未映射 `broker_execution`、`operational_readiness`、`risk_center`、`portfolio`、`research`、`valuation`、`config_center`；当时这些模块发生变化只会选中通用护栏。当前映射、关键链路与 CI 门禁均已完成，后文保留历史实施证据。

## 实施内容

### 1. 修复测试选择器

- 为上述 7 个模块补齐单元、API、迁移和集成测试映射。
- 新增 `tests/critical/`，加入快速 CI、全量回归和 RC 测试集合。
- 未映射的新 App 必须保守回退到全量测试，禁止静默只跑通用护栏。
- 扩展选择器自测，要求所有生产 App 都有测试映射或明确豁免。
- 更新 RTM 检查，确保关键测试文件不能被误删。

### 2. 新增关键链路测试

在 `tests/critical/` 建立三个稳定、无外部网络依赖的测试组。

#### 决策与数据安全

- 数据缺失、过期或来自未来时，决策快照失败关闭。
- 被阻断时不得创建订单或产生执行副作用。
- PIT manifest 冻结后新增版本不改变历史结果，篡改必须被识别。

#### 风险与订单安全

- 服务端风险拒绝、账户或全局 kill switch、过期 Broker 快照均阻止审批或领单。
- 停止状态仍允许拒绝、撤单和对账等降风险操作。
- 重复创建、审批、Agent 事件和成交回报只产生一份持久化结果。
- 日限额、允许标的、账户授权在最终提交前再次检查。

#### Agent 与恢复安全

- 心跳过期或 QMT 断开后停止领单。
- 未知报单结果进入 `RECONCILIATION_REQUIRED`，不得盲目重试。
- P0 对账差异自动触发 kill switch，未完成处置前禁止恢复。
- Fake Agent 正常链路覆盖审批、领单、提交、部分或全部成交和幂等回放。

测试复用现有工厂和 Fake Agent，不复制已有 Domain 规则测试。

### 3. 补齐迁移与数据库验证

- 新增研究完整性迁移测试，覆盖：
  - `data_center 0039`
  - `decision_rhythm 0015–0016`
  - `signal 0009`
  - `prompt 0002`
  - `events 0005`
  - `portfolio 0001–0004`
  - `research 0001`
- 对有历史数据转换的迁移验证升级前后数据保留、默认值和关联关系。
- 对新表验证幂等唯一约束、外键和关键索引。
- Nightly 增加 PostgreSQL 服务，在空库执行完整迁移后运行 `tests/critical/` 和关键迁移测试；普通 PR 继续使用 SQLite 保持速度。

### 4. 接入 CI 与发布门禁

#### PR 快速 CI

- 根据模块映射运行对应测试。
- `tests/critical/` 使用 SQLite 和 Fake Agent。
- 不连接真实 QMT、Redis 或外部数据源。

#### Nightly

- 保留全量单元、API 和集成测试。
- 增加 PostgreSQL 关键链路测试。

#### RC Gate

- 增加独立的 `Critical Reliability` 阻断步骤。
- 任一关键链路、迁移或 PostgreSQL 测试失败即阻止发布。

#### 真实 QMT

- 不阻断普通提交。
- 实盘启用前必须运行现有 preflight 和只读探针并保存证据。
- 券商权限未开通时阻止实盘激活，不阻止代码合并。

## 验收标准

- 7 个缺失模块均能被增量选择器命中对应测试。
- 未映射 App 的选择器自测失败或保守回退全量测试。
- 关键链路至少覆盖正常、过期数据、风险拒绝、kill switch、重复请求、断线、未知结果和 P0 对账差异。
- SQLite PR 套件、PostgreSQL Nightly 套件、API 和迁移测试、架构扫描全部通过。
- 不修改生产 API、数据库业务语义或真实交易逻辑；本阶段仅补测试、测试选择器、CI 和配套治理文档。
- 阶段文档持续记录已完成项、未完成项、测试耗时、失败样例和真实 QMT 未验证事项。

## 分阶段实施与提交

1. `test: cover critical module test selection`
2. `test: add critical reliability chains`
3. `test: verify critical migrations on postgres`
4. `ci: enforce critical reliability gate`
5. `docs: document critical reliability closure`

每个阶段独立验证和提交，避免把测试实现、CI 改造和文档治理无边界混入同一批次。

## 当前进度

- [x] 完成现有护栏和关键测试盘点。
- [x] 确认采用分层验证：PR 使用 Fake Agent，Nightly 执行完整后端链路，真实 QMT 作为发布前现场验收。
- [x] 保存本阶段实施计划。
- [x] 补齐关键模块测试选择映射。
- [x] 新增关键链路测试。
- [x] 补齐关键迁移验证并配置 PostgreSQL Nightly 入口。
- [x] 接入 PR、Nightly 和 RC 门禁。
- [x] 在 GitHub Nightly 完成 PostgreSQL 实际运行取证（2026-08-20 历史 CI 候选 `578064409b8269e440ba7edbf9c480aa7d9917ff`，run `32276242287` 的 `Critical Reliability (PostgreSQL)` job 成功；SQLite fallback concurrency 的 1 个预期 skip 保留）。
- [x] 记录真实 QMT 发布前验证证据；当前结论为 `QMT_SERVER_NOT_ALLOWED`，保持实盘禁用。

## 2026-07-22 实施记录

### 已完成项

- `scripts/select_tests.py` 已补齐 `broker_execution`、`operational_readiness`、`risk_center`、`portfolio`、`research`、`valuation`、`config_center` 映射。
- 所有生产 App 都必须存在显式映射；未来新增但未映射的 `apps/*` 变更会保守回退全量测试，快速档也会保留 API、单元、迁移、关键可靠性和 App-local 范围。
- `tests/critical/` 已建立三个发布阻断测试组：
  - 决策与数据安全：缺失、过期、未来证据失败关闭，PIT manifest 冻结与篡改识别。
  - 风险与订单安全：服务端风险拒绝、账户与全局 kill switch、Broker 快照过期、最终提交重检、审批幂等、QMT 断连与心跳过期。
  - Agent 与恢复安全：未知报单结果、Agent 本地幂等、P0 对账自动停止、未处置差异阻止恢复、Fake Agent 审批到成交与事件回放。
- 新增研究完整性迁移测试，覆盖计划列出的 11 个迁移节点，验证应用记录、物理表、唯一约束、外键、关键索引，以及 `decision_rhythm` → `portfolio` 所有权转移时历史数据和默认值保留。
- PR 快速 CI 始终运行 `tests/critical/`，RTM 文件存在性检查已保护三组关键测试和迁移测试。
- Nightly 已增加 SQLite 关键集合步骤和独立 PostgreSQL 16 空库迁移/关键测试 Job。
- RC Gate 已增加独立 `Critical Reliability` 阻断步骤。

### 本地验证结果

| 验证项 | 结果 | 耗时/说明 |
|---|---:|---|
| 选择器自测 | 49 passed | 0.61s |
| `tests/critical/`（SQLite + Fake Agent） | 18 passed | 83.40s；首次测试库迁移约 72.76s |
| 研究完整性迁移测试 | 3 passed | 101.54s；历史所有权迁移重放约 15.46s |
| 7 模块权威单元/API/集成回归 | 133 passed | 163.76s；含 Broker、Risk、Config、Research、Portfolio、Valuation 与 Fake Agent |
| 架构工具与边界护栏 | 18 passed | 31.21s；新增生产代码违规 0，结构审计违规 0 |
| Ruff | passed | 新增/修改 Python 文件 |
| Black / isort | passed | 新增/修改 Python 文件 |
| GitHub Actions YAML 解析 | passed | PR、Nightly、RC 三份工作流 |
| 7 个模块选择器抽检 | passed | 均命中 `tests/critical/` 和关键迁移测试 |

### 失败样例与处置

- 首次迁移测试失败：`MigrationExecutor.project_state()` 不接受 `("portfolio", None)` 伪节点。迁移动作本身已完成；测试改为只用有效的 `decision_rhythm 0014` 节点读取迁移前状态，重跑通过。

### 未完成项与未验证风险

- GitHub PostgreSQL Job 已在 2026-08-20 历史 CI 候选上实际成功；这只证明 CI 空库迁移、关键链路和隔离恢复合同，不替代生产 PostgreSQL、维护态 rollback 或真实数据覆盖证据。
- 真实 QMT 不进入普通 CI。本阶段引用 `docs/operations/qmt-agent-runbook.md` 中 2026-07-22 的目标机证据：国金 QMT `2.1.19.0`、Python 3.11、`xtquant 250807.1.2` 隔离导入成功，但真实只读探针返回 `QMT_SERVER_NOT_ALLOWED`。本次收口不重复连接、不提交或撤销真实订单。
- 实盘激活前仍必须按 `docs/operations/qmt-agent-runbook.md` 运行 preflight 和只读探针；券商权限未开通或版本矩阵未记录时必须保持实盘禁用。

## 2026-08-20 实施记录：历史 CI 候选 PostgreSQL Nightly 实际取证

2026-08-20 历史 CI 候选 `dev/next-development@578064409b8269e440ba7edbf9c480aa7d9917ff` 的
[GitHub Actions Nightly run 32276242287](https://github.com/guiyinan/agomTradePro/actions/runs/32276242287)
中，独立 `Critical Reliability (PostgreSQL)` job 已成功完成。它不是只运行 SQLite 的
普通 job，而是在 PostgreSQL 16.15 空库上完成全量迁移和分层回归：

- 迁移图、Data Center catalog、storage capacity profile 与 applied migration plan 均通过；
- 应用自有 custom-format backup → 隔离库 restore → 逐表/sequence/schema 对比通过，artifact
  `outcome=success`，`7,167` 个 restore entries，dump `3,600,046` bytes，SHA-256
  `2b4c7e57e33aa797abfac49d7935d0f0276a0d9616cb123d131c180605a75a75`，restore `3.208s`，
  verification `0.802s`，total `5.248s`；
- JUnit artifact 计数：critical `18 passed`、research migration `8 passed`、publication/runtime
  `41 passed`、current-data `349 passed`、Celery contracts `220 passed`、backfill/retention
  `61 passed`、retention concurrency `3 passed + 1 expected SQLite fallback skip`，合计 `700 passed + 1 skipped`。

这条证据完成的是 CI PostgreSQL 迁移/关键可靠性测试与隔离恢复子门，不是生产数据库恢复或
RTO/RPO、维护态 rollback、全市场回填、生产 reconciliation、M9/M10 或真实 QMT 探针；这些
仍保持未完成和 fail-closed。

## 2026-09-03 DATA-10：Nightly 测试时钟与 canonical migration bytes

### 触发与根因

GitHub Actions Nightly run `33726889412` 在
`tests/api/test_pulse_api.py::test_pulse_history_api_contract` 失败：接口返回一条历史记录，而固定断言
要求至少两条。本地同一测试复现为 `count=1`。仓储按 `date.today() - months * 30 days` 计算窗口，
测试却固定写入 2026-03-24 与 2026-03-01；随着真实日期推进，后一行已经自然落出六个月窗口。

修复只修改测试夹具：在一次测试内捕获 `date.today()`，分别写入当日和前 30 日两条记录。这样仍
真实经过仓储的六个月过滤，不冻结生产时钟、不扩大查询窗口，也不改变 Pulse API、freshness 或
`must_not_use_for_decision` 语义。

首次完整执行 Nightly 的 API/Migration 原命令共收集 1,090 项，结果为 `1,088 passed / 2 failed`。
Pulse 文件的 16 项均通过；剩余两项是历史 migration hash guard 在 Windows 工作树直接读取 CRLF
bytes，而期望值绑定 Git 中 LF bytes。`git ls-files --eol` 对三份引用文件均证明 `i/lf w/crlf`；将
工作树 bytes 规范化为 LF 后，SHA-256 与三个期望值逐一完全一致：

- `fixed_income/0001_initial.py`：`201b740746c21cf86f22db535c849f0bce2edcca7b67da871c795ff7039103cf`
- `fixed_income/0002_seal_research_results.py`：`15d271e90ffcaf3ee5590cf065ad5ef9c839885c1b92884d98b2dbf1402edc92`
- `research/0005_r7_sample_policy_ledger.py`：`5bfdd5eabcc8e3318890a8622df48ca8805cd30745dc941a3553a1da204746ae`

两个 guard 现按仓库既有迁移测试约定将 CRLF/CR 规范化为 LF 后校验。历史 migration 文件本身未
修改，hash 期望值未更新，因而仍能检测任何真实内容漂移。

### 当前验证与退出门

- Pulse API 文件 + 两个 migration hash guard：`18 passed`。
- Black、isort、Ruff：通过。
- active-plan registry v47：41 units、唯一 focus `DATA-10`、0 violations。
- 首次完整本地 API/Migration：`1,088 passed / 2 failed`，两个失败均已按上述 canonical LF 根因修复。
- 第二次完整本地运行使用机器默认 Python 3.13.5，在 Django test-db model render 阶段发生 Windows
  原生 `access violation` 并异常终止；仓库约定的 `agomtradepro` Python 3.11 conda 环境在本机并不存在，
  因此该次运行既不记为测试失败，也不记为通过。
- 精确提交 `a03078fb51339a98e4c30a27255b9d3426e7f81d` 的 GitHub Python 3.11 Nightly run
  `33754275868` 中，独立 PostgreSQL job 完整成功；主 Unit Tests 为
  `13,867 passed / 1 failed / 1 skipped`。唯一失败是新增 DATA-10 后 closed-world registry test 仍断言
  `closure_unit_count == 40`，而机器注册表与 README 均已合法登记 41 units；该投影现已同步为 41，
  registry focused test 为 `8 passed`。
- 精确提交 `20e5421bb710e3e554ac9ed9ef7847b7a5c6dc4d` 的后续 Nightly run `33758054039`
  已使独立 PostgreSQL、full unit、component、API/migration 和 SQLite critical reliability 阶段全部
  成功。core integration 执行到 `1,037 passed / 4 failed / 13 deselected` 后停止，四项均为已有测试或
  历史快照没有满足当前合同：两条 Data Center API 测试缺少显式 audit composition，一条 Config
  Center 测试缺 critical runtime profile，历史 Web→TUI 基线图套用当前 IA 后则只剩 P1/P2 面板而
  丢失 P0。
- Data Center API 测试现在只替换 authority/config 装配，仍使用真实 Django system-audit event/outbox
  writer，并额外断言 `data.fetch.completed` 落库；Config Center 复用现有 fail-closed critical runtime
  seed。TUI repository 对历史 full-IA payload 过滤面板后，如只剩无 P0 的不完整面板组，则将其整体
  移除并把 dashboard journey 降级为有主动作的 workspace，随后仍执行完整 metadata validator；不会
  虚构 P0 action，也不会接受无效 payload。
- 最新本地验证：上述两条 audited API 节点 `2 passed`；三个受影响 integration 文件 `48 passed`；
  完整 `tests/unit/test_tui_workbench.py` 为 `309 passed`；TUI static/source/copy-density/presentation 四项
  门禁通过；增量 mypy 与全仓 debt ceiling 均为 0 errors；Black、isort、Ruff 通过。
- 按 Nightly 相同 marker 选择器执行完整 `tests/integration/`，结果为
  `1,041 passed / 13 deselected / 1 warning`（674.73s）。唯一 warning 是 Windows teardown 时测试数据库
  文件仍被进程占用；全部测试节点已成功，不把该清理 warning 隐瞒或误报成 Python 3.11 证据。
- 精确提交 `e4095270af5576e05cc4de4e3c4833a1f86cc703` 的 GitHub Python 3.11 Nightly run
  [`33820056980`](https://github.com/guiyinan/agomTradePro/actions/runs/33820056980) 中，独立 PostgreSQL
  job 完整成功；主 job 的 current-data、Celery、full mypy 与 frontend 阶段均成功，full unit 为
  `13,868 passed / 1 failed / 1 skipped`。唯一失败是本次修改
  `apps/terminal/infrastructure/tui_metadata_repository.py` 后，没有同时刷新 reviewed
  `config/tui/agomtui-runtime.manifest.json` 中该文件的规范化 SHA-256；后续阶段按 fail-closed 正确跳过。
- 已使用 canonical `npm run build:tui` 生成新的 runtime manifest source digest/build identity；生成过程对
  `static/js/tui-workbench.js` 没有 blob 内容变化。`npm run check:tui` 与
  `tests/unit/test_tui_runtime_manifest_contract.py` 均通过（`1 passed`）。这只修复代码发布投影，既不改变
  runtime 行为，也不冒充尚未执行的最终 Nightly。

`DATA-10` 继续保持 active，直到包含上述 integration corrective 与 runtime manifest 投影的精确最终提交
在 GitHub Python 3.11 Nightly 完整通过，再生成 content-addressed closure evidence、同步 registry/计划并
把 focus 置回 null。本单元不部署、不重启、不读写生产数据库、不修改候选、历史 migration、数据门或
TUI 观察窗口；当前回滚点为 Pulse/migration/registry 测试修复、三项 integration fixture、TUI legacy
normalization、runtime manifest 及对应治理投影。

## 2026-09-05 DATA-10：current-checkout candidate binding fail-closed

### Nightly 证据与根因

- 精确提交 `1d91884a3d509e6263674eaee774c0c23c758190` 的 GitHub Python 3.11 Nightly run
  [`33895590645`](https://github.com/guiyinan/agomTradePro/actions/runs/33895590645) 中，独立 PostgreSQL
  job 完整成功；主 job 的 current-data、Celery、full mypy 与 frontend 阶段均成功。
- full unit 为 `13,868 passed / 1 failed / 1 skipped`。唯一失败是
  `test_checked_in_evidence_is_explicitly_denied` 仍把已部署候选的旧 runtime binding 当成当前 checkout
  binding，错误期待 UAT、cleanup 与 rollback 三个 gate 继续通过；后续主 job 阶段按 fail-closed 跳过。
- canonical runtime manifest 已随当前开发分支的 server-side contract 更新，而生产仍运行候选
  `aa7127ff4d9f71555b0d0486314da5518bd2ac20` / release `20260901232812`。readiness checker 默认从当前
  matrix、graph 与 runtime manifest 重算 expected binding，因此旧候选证据在当前 checkout 上必须返回
  `binding=false`。这不是生产候选漂移，也不能通过改写 production cutover evidence 消除。

### 修复与当前退出门

- checked-in evidence 测试现明确断言 UAT `108/108`、cleanup 六 scope `108/108` 及 rollback evidence
  仍存在，但三者因候选 binding 不同均 fail-closed；当前 checkout 仅 `source_consistency` 与
  `execution_dependency` 两项通过，测试投影为 `2/10 DENY`。
- `tests/unit/test_web_to_tui_cutover_readiness.py` 整文件本地回归为 `37 passed`。生产候选的历史
  candidate-bound `5/10 DENY` 记录保持不变；没有修改
  `config/tui/migration/web_to_tui_cutover_evidence.v1.json`，也没有部署、重启、合并 main 或写生产。
- readiness、candidate consistency 与 runtime-manifest contract 合并聚焦回归为 `39 passed`；
  `npm run check:tui`、Black、isort、Ruff、active-plan registry v48、governance consistency、文档路由与
  SDK consistency 以及 `git diff --check` 全部通过。
- GitHub issue `#3` 保持 `P2`，并由失败 workflow 绑定到 run `33895590645`。`DATA-10` 继续 active，
  退出门仍是包含本测试修复与治理投影的精确后续提交在 GitHub Python 3.11 Nightly 完整成功。
