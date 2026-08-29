# Web → TUI M5 Readiness 判定（2026-07-27）

## 当前结论

**M5 清理判定：DENY。**

> 2026-08-21 执行依赖纠偏：`TUI-01` 现在显式依赖 `TAR-03`。Terminal Agent 的
> Worker、事件恢复与 TUI/SDK 状态闭环会改变最终 release surface，因此
> `2f4554b5192191970a3ccbc98420388881725079` / `20260820211526` 上已经启动的观察只作为
> 非关闭性 production soak 保留，不得用于解除 M5。只有 `TAR-03` 退出、最终候选冻结并
> 重新绑定 canonical cutover evidence 后，才启动具备关闭资格的 14 日窗口、角色 UAT、
> telemetry、rollback、registry restore 与双签。

> 2026-08-13 代码复核修正：此前仓内 108/108 UAT、108/108 cleanup 与本地 rollback
> 仅绑定旧 Markdown 摘要，未绑定最终 candidate commit、当前 matrix、published graph、
> schema、runtime version/build 和 runtime manifest，不能再记为通过。readiness 已改为对三类
> 证据要求完全一致的 candidate binding；当前旧证据均显示 `binding=false` 并失败关闭。
> 本节以下 7 月 27/28 的“通过”叙述保留为历史执行记录，不再代表当前候选 gate 状态。

M0–M4 的仓库实现已完成，迁移矩阵中的 17 个 B 类 route template 已全部迁入
TUI，B 类 backlog 为 0；但这不等于获得 Classic 删除授权。2026-07-28 只读生产
preflight 确认线上仍运行 `dev/next-development@2e399607977fea260436992952fae64565153213`，
该提交不包含当前迁移矩阵。2026-07-26 因而只能视为历史预定基线，不能回填为当前候选
观察起点。当前机器证据尚未绑定候选稳定版本及其起止时间，稳定窗口尚未开始；最早复审日
必须由真实候选部署后的机器窗口计算。证据见
`web-to-tui-m5-production-preflight-2026-07-28.md`。

2026-08-13 再次只读 preflight 已确认生产 release 更新为 `source-20260813002655`，因此上段
`2e399607…` 只保留为 7 月 28 日历史事实；但当前镜像 OCI revision 为 `unknown`，release 又无
`.git`/source manifest，仍无法绑定任何候选 commit。公开 health/ready 均为 200/ok 不改变
此结论。见 `web-to-tui-m5-production-preflight-2026-08-13.md`。

## 退出门槛快照

| 门槛 | 当前证据 | 判定 |
|---|---|---|
| 至少 1 个稳定版本且不少于 14 个自然日 | 当前 release 为 `source-20260813002655`，但 OCI revision=`unknown` 且无 source manifest，不能绑定候选；`stable_version`、`candidate_commit`、`released_at`、`observation_end` 尚未建立 | 未通过 |
| 计划内角色与主路径 UAT 100% | 历史覆盖为 108/108，但未绑定当前 candidate graph/runtime snapshot | 未通过；须对最终候选重跑并结构化回写 |
| 逐 route 清理条件 100% | 历史六类 scope 为 108/108，但缺当前 candidate binding；cleanup recorder 尚待补齐 | 未通过 |
| P0/P1 阻断缺陷为 0 | 尚无覆盖完整兼容窗口的缺陷报表 | 未通过 |
| 旧入口占比 ≤ 5% 或低频例外双签 | 已实现矩阵驱动的有界 Classic/TUI 同任务指标与 14 日 PromQL；尚无生产样本 | 未通过 |
| TUI 错误率不高于基线 0.5 个百分点 | 已把 Classic 同源 API execution 通过受审 Referer 归入固定 task，并实现 task request 对照和最小样本告警；101 个 comparable task 当前无生产窗口数据 | 未通过 |
| wave 级 graph/runtime 与 route/template 回滚演练 | 旧本地演练未绑定当前 candidate graph/runtime/build，且当前静态 drill baseline 已漂移 | 未通过；须修复并重跑最终候选演练 |
| 生产 registry 可校验备份 | 仓库外备份/恢复工具与集成测试已完成，但尚无绑定候选版本、commit、矩阵 SHA、外部 locator、完整性摘要和恢复验证的生产证据 | 未通过 |
| owner 与独立 reviewer 切换审批 | 尚无绑定候选版本、commit、矩阵 SHA 和经摘要校验评审快照的双签 | 未通过 |

## 当前已通过的实现门禁

### 2026-08-13：candidate binding 与 observation 防回填加固

- 新增统一 candidate binding：稳定版本/完整 commit、matrix SHA、published graph SHA、
  schema version、runtime version/build ID 与 runtime manifest SHA 必须完全一致。
- readiness 现在对 UAT、cleanup、rollback 和 production registry backup 重新核对当前 binding；
  仓内旧证据实测全部因 `binding=false` 为 FAIL，不再产生旧证据假阳性。
- observation 启动不再接受 caller 提交 `released_at/as_of`；只能读取仓库内 HEAD 已提交且
  byte-exact 的 production deployment preflight，核验 production release/source commit、OCI
  image/revision、health/readiness 200/ok 响应摘要及时区感知单调时钟。health/verification 必须在
  30 分钟内、部署不超过 24 小时，窗口从 `verified_at` 当日开始，不能回填证明前时段。
- 更换候选会清空 UAT、cleanup、defects、telemetry、rollback/backup、review snapshot 与审批。
- observation 合成测试 `15 passed`；candidate/readiness 相关全组在本机受慢速/临时目录权限影响
  未取得一次完整结束证明，但旧证据实际 readiness 输出已确认 DENY。
- UAT/cleanup/rollback candidate recorder 已实现：固定执行套件并重解析 JUnit，任何
  failure/error/skip 都拒绝写入；rollback 只接受 drill v2 exact binding，CLI 不接受自报
  `passed`。结构报告有独立 JSON Schema，专属测试 `5 passed`。
- 当前 cutover candidate 未建立，candidate recorder 实测按设计 FAIL 且不写 evidence，readiness
  仍安全 DENY。M5-B wave recorder 已补齐，但当前没有删除候选、部署 attestation 或 48h 原始
  生产记录，不能用 candidate cleanup report 冒充每波生产观察。

### 2026-08-13：candidate-bound rollback drill v2

- 删除易漂移的静态 baseline/new-path 清单；从代表 wave 的 migration anchor 唯一新增提交
  自动推导 baseline parent，candidate/ref 先解析为 immutable commit。
- patch、artifact manifest、graph/schema contract、runtime manifest 和矩阵 rollback commit 全部从同一
  candidate Git snapshot 重建；工作树不作为候选证据读取。
- 真实本地隔离 reverse/forward 演练通过：31 artifacts（3 added / 18 modified / 10 unchanged），
  graph actions `402 → 430`，runtime manifest 18 files 逐一验摘要，回滚与恢复后内容精确。
- 针对测试 `3 passed, 1 skipped`；skip 为当前环境缺 Django 的 registry publish/rollback/restore 往返用例。
  本地代表 wave 不替代生产 registry 备份/恢复、真实部署或全量 wave 验收，cutover 仍 DENY。

### 2026-08-13：M5-C 最终库存门禁

- `web_template_migration_inventory.py --require-finalized` 已与迁移期普通 `--check` 分离；普通检查语义不变。
- 最终模式精确要求 41 个 C 档物理模板，A/B/D 全部 `deleted`，并扫描已删模板的活 view/route literal、孤儿静态资产及 published legacy alias 的 canonical target 与生产代码消费者。
- 当前普通检查通过（196 行，A=131/B=17/C=41/D=7）；最终模式按设计 DENY，148 个 A/B 模板尚未完成 lifecycle。32 个 alias 中另有 11 个没有活生产代码引用；检查器已纳入 IA `published_screens`/`runtime_screens`，因此 `capability-router.gateway` → `capability-router.mcp-center` 不再被误报为 dangling。11 个 dead alias 仍须真实流量观察与逐 wave 证明后清理。
- 门禁专属测试 `10 passed`；当前机器缺 Django runtime，历史 inventory rebuild 的 Django resolver 用例未纳入本次专属测试。静态引用扫描不替代生产流量证明，真实 alias 删除仍须进入逐波观察与回滚证据。

### 2026-08-13：M5-B cleanup wave recorder

- recorder 从 candidate Git snapshot 重算每波新增删除、连续 wave、1–10 route、telemetry task coverage 与 rollback commit，不接受 caller 自报 scope 或 `passed`。
- 必须提供已提交的 production deployment preflight；stable version、source commit 与 OCI revision 均精确绑定删除候选，attestation commit 位于 candidate 之后且不晚于观察开始。
- candidate observation 必须发生在 deployment verification 之后且不少于 48 小时；telemetry、P0/P1 tracker 与 scheduled cycle 原始记录分别按 exact schema 重算，窗口/候选/任务集合不一致即失败。
- 三个 wave artifact 先写 SHA，cutover evidence 原子替换失败时回收本次 artifact；专属测试 `14 passed`，strict mypy、Black、isort、schemas、compile 与 diff check 通过。
- 当前仓库没有 M5-B 删除候选和对应生产证据，真实 CLI 保持 FAIL；本实现只关闭 recorder 缺口，不代表任何 wave 已观察或获准删除。

### 2026-08-13：发布 provenance fail-closed

- source-upload 拒绝 dirty worktree 和非完整 Git SHA；git-clone 在构建前后锁定并复核 exact candidate commit。
- 构建强制 OCI revision 等于源码 commit，并生成只读 exact-schema release manifest；deploy 在任何服务启动或 `current` 切换前复核 manifest、image ID 与 OCI revision。
- 相关本地回归 `44 passed`，strict mypy、格式、编译和三个生成 shell 的语法检查通过；Ruff 未安装。
- 代码整改尚未部署，当前生产仍是本页所述 OCI revision=`unknown`/无 manifest 状态。它不能替代真实候选部署、deployment attestation 或观察窗口，readiness 继续 `DENY`。

### 2026-08-14：后端 TUI contract 纳入 release provenance

- `scripts/build-tui-runtime.mjs` 现在把 declarative IA、Application metadata、IA loader、metadata repository/signals 以及全部 `tui_metadata_runtime_*.py` 纳入 runtime manifest 的逐文件 SHA-256。可写 action 只要改变后端 IA/runtime contract，manifest/build hash 就会变化，候选证据无法继续复用旧绑定。
- `tests/unit/test_tui_runtime_manifest_contract.py` 固定关键 IA、policy/signal/account self-service injection 与 server-side loader 覆盖，并逐文件重算 manifest digest；本地 `21 passed`（含 observation/candidate recorder）。`npm run build:tui` 已重新生成 manifest，2026-08-14 提交前 `npm run check:tui` 复核通过。
- 这只是本地 provenance/候选绑定收口，不是部署或观察窗口证据。当前生产仍为 revision=`unknown`、无合格 manifest、无 attestation，真实候选部署、14 日窗口、telemetry、backup 与双签继续 `DENY`。

- M4：17/17 个 B 类 route template 已迁移，0 backlog；完整 TUI Workbench 加操作组
  非 sticky 回归现为 `240 passed`。
- AGENTS.md 固定其余三组最小回归：`35 passed`；IA 与归一化幂等：
  `7 passed`；inventory/static：`5 passed`；完整 Workbench `240 passed`。
- 迁移矩阵：196 行、117 个历史 route page，A/B/C/D 互斥校验通过。
- Django system check、ruff、增量 mypy 与全仓 architecture verify 通过。
- `web_to_tui_migration_events_total` 使用受审 route/action/screen 目录限制标签基数；
  14 日 Classic 占比、样本量和 execution 错误率 recording rules/alerts 已实现。
- M5 回滚演练通过：旧 graph 与当前 `tui-metadata.v3` 兼容；真实 patch 在临时目录
  完成 reverse/restore；pytest registry 发布/回滚/恢复为 `1 passed`。
- M5 浏览器套件 `15 passed`：覆盖账户读/详情、缺参、确认取消、operator/普通用户
  权限边界、3 个 viewport、108/108 migrated route 深链、71 个角色化直读 route、9 个
  参数化读取 route、策略和个人 AI 服务商创建→详情→更新、Policy 管理员创建，以及
  决策配额/Beta Gate/股票与基金筛选确认流程、Agent/Alpha/Audit/Backtest/Factor
  本地详情与生命周期，以及通过本地加密 Provider 真实执行的 Sentiment 与 Terminal
  Agent 外部 AI 主任务；并验证账户 P0 持仓读取不再同步创建默认账户。人工复核 console
  error 为 0。证据见
  `web-to-tui-m5-browser-uat-evidence-2026-07-27.md`。
- M5 机器 gate 已落地：`check_web_to_tui_cutover_readiness.py` 同时校验矩阵/catalog
  SHA、108 个 route UAT、101 个 production telemetry task、稳定窗口、P0/P1、低频
  双签、回滚、registry 备份和独立审批。当前输出为 `DENY`，不是待办文字推断。
- 2026-07-28 生产 preflight 通过公开健康/就绪探针和只读 SSH 核对了 release、Git commit、
  OCI revision 与容器状态：生产运行面健康，但部署版本仍为不含当前迁移矩阵的旧提交。
  该证据明确阻止观察窗口回填，不替代任何生产 cutover gate。
- 候选观察窗口启动器已落地：`start_web_to_tui_observation.py` 会把候选版本绑定到可解析且
  属于当前分支历史的完整 commit，并要求该 commit 内的迁移矩阵与当前矩阵一致、工作树干净；
  默认只 dry-run，显式 `--write` 才写入 14 日窗口。切换候选必须使用 `--replace`，旧候选
  的缺陷、生产遥测、生产 registry 备份、评审快照和审批会被清空，不能跨版本复用。
- 阻断缺陷 evidence 生成器已落地：`build_web_to_tui_defect_evidence.py` 只接受仓库内、绑定
  同一候选版本/完整 commit/矩阵 SHA/精确窗口的 GitHub/Jira/Linear 快照，并要求固定
  `created_or_open_during_candidate_window` 查询范围、无凭证 HTTPS 来源、查询人和快照 SHA。
  工具从 issue 生命周期分别推导 `new_p0/new_p1` 与 `open_p0/open_p1`；四项必须同时为 0，
  窗口内新增后关闭的缺陷仍阻断，不能只看结束时 open 数。默认 dry-run，真实非零快照可写入
  留痕，但 `--require-clear` 和 readiness 必须失败。当前没有候选缺陷快照。
- 生产遥测 evidence 生成器已落地：`build_web_to_tui_production_telemetry.py` 只接受仓库内
  经复核的 production Prometheus 快照，并要求候选版本、完整 commit、矩阵 SHA、精确 14 日
  窗口和 `classic_routes.task_key` 推导出的 101 个可比较任务完全一致；TUI-only action 不进入
  生产门禁分母。六条 PromQL、整数计数、5% Classic 占比、两侧各
  20 个 task request、0.5 个百分点错误率回退和低频独立双签均 fail closed；默认 dry-run，
  显式 `--write-evidence` 才更新 cutover evidence。runtime 分类器同时排除匿名登录跳转、
  匿名 TUI shell 和伪造 Referer 的公共 API 请求，只让已认证任务流量进入门禁。当前没有
  生产快照，仍为 0/101。
- 生产证据已改为强绑定：候选版本必须带可在本仓库解析的完整 commit；UAT、回滚、缺陷与遥测必须有
  仓库内证据及与实际文件一致的 SHA-256，缺陷/遥测还要求查询或采集时间；registry 备份
  必须带证据/payload/graph SHA-256、generation、schema/runtime、恢复验证、验证人和
  保留期，并绑定候选版本、commit 与矩阵 SHA；owner 与独立 reviewer 的批准还必须绑定
  经 SHA-256 校验的同一评审快照。占位字符串、摘要不匹配、过期审批、路径穿越或缺失
  证据文件、虚构 commit、本地占位 locator 或非正 generation 均不能放行，对应
  fail-closed 单测 `29 passed`；同时覆盖候选提交内矩阵、结构化快照重建、逐 route 清理
  scope/回滚映射、备份 attestation/保留期与观察窗口结束后审批时序。
- 2026-07-28 checker 再次收紧：候选 commit 还必须属于当前分支并实际包含当前矩阵；108 条
  route rollback mapping 必须逐值等于矩阵，不再只验 SHA 可解析；缺陷与遥测 gate 会重新解析
  JSON 快照并调用生成器重建 evidence，摘要匹配的 Markdown、手工改写计数或跨候选快照均不能通过。
- `build_web_to_tui_review_snapshot.py` 只在其余 8 个 gate 全通过时冻结精确 gate 结果，并清空
  旧签字；`record_web_to_tui_cutover_approval.py` 分别生成 owner/reviewer 角色绑定 attestation，
  强制不同身份、候选/矩阵/快照摘要一致和窗口结束后签署。Checker 会重建 review snapshot 并
  逐份核对 attestation；工具只记录真实审批，不能代替或伪造审批人决定。
- 2026-08-13 修复 cleanup guard 的 SHA 不可达循环：不再把删除后 matrix 交给变更前的
  full readiness，而是先从 pre-cleanup candidate Git blobs 重放 final review snapshot 与外部
  owner/reviewer attestations，再逐 M5-B wave 重建删除后 matrix/catalog/graph/runtime binding。
- 每波强制精确删除范围、≤10 route、物理删除、legacy URL policy、独立复核、rollback manifest
  和串行 commit lineage；外部 SHA observation ledger 还必须覆盖≥48 小时及至少一次定时周期，
  P0/P1 全 0，基线/候选请求各≥20，错误率回退≤0.5 个百分点；前波完成观察后才能开始后波，
  最后一波必须绑定当前 snapshot。caller 自写 `passed=true` 会因 exact schema 失败。
- cleanup guard 针对测试 `15 passed`；当前尚无正式 cleanup wave/rollback manifest/observation
  ledger recorder，因此真实新删除仍保持 DENY。
- A/B route 即使在 M5-B 标为 `deleted`，仍保留在 108-route UAT/清理范围和 telemetry
  catalog 中；对应回归证明删除状态不能缩小证据分母或绕过历史任务监测。
- 逐 route 兼容面首批证据 `2 passed`：展开 108 route 的 118 个 URL pattern，验证匿名认证
  边界、模板继承/include 后的审核 TUI 目标和 Terminal 精确重定向；修复 5 个匿名 200、
  2 个认证前对象查询及 7 个手写提示漂移。当前只关闭 `legacy_url`，不冒充完整权限/状态证据。
- Registry 备份/恢复命令已落地：备份只能写到仓库外并原子生成 JSON + SHA-256 sidecar；
  恢复默认 dry-run，显式批准时还要求匹配当前 active source hash，并记录 rollback ancestry。
  `build_tui_registry_backup_evidence` 会再次验证 bundle/sidecar、当前 active generation/hash、
  restore payload、候选窗口和保留期，只把不含 payload 的结构化 attestation 写入仓库；checker
  要求 attestation 与 cutover projection 精确相等。这只证明工具可用，不代表已经取得生产备份。
- Published metadata 收口为 12 screens / 399 actions；删除 8 个无 screen/panel/矩阵消费者且
  缺少必填参数的旧 auto action。全新迁移 SQLite + staff 用户 + 同库 localhost 下，read/AI
  action smoke 为 `380 total / 238 ok / 142 needs_input / 0 error`；Regime、Pulse 首装空态返回
  200，AI Provider 未配置返回受控 503，不再依赖历史开发数据冒充通过。

## 机器判定快照

```text
Web-to-TUI M5 cutover: DENY (as of 2026-07-28)
PASS source_consistency
FAIL stable_version_window: commit=missing_or_source_mismatch
PASS route_task_uat: covered=108/108; evidence=true
PASS route_cleanup_readiness: covered=108/108; scope_counts=empty_state:108,error_state:108,legacy_url:108,permission:108,primary_task:108,rollback:108; scopes=true; rollback=true; rollback_matrix=true; lifecycle=true; evidence=true
FAIL blocking_defects: evidence=false; structured_snapshot=false
FAIL production_telemetry: covered=0/101; production_evidence=false; structured_snapshot=false
PASS rollback_drill
FAIL production_registry_backup: evidence=false; structured_attestation=false; integrity=false; restore_verified=false
FAIL cutover_approvals: owner=missing; reviewer=missing; snapshot=false; attestations=false
```

日常一致性检查：

```bash
python scripts/check_web_to_tui_cutover_readiness.py
```

release owner 明确选定并部署包含当前矩阵的干净候选提交后，先执行 dry-run，再显式开始观察：

```bash
python scripts/start_web_to_tui_observation.py \
  --stable-version <version> --candidate-commit <full-commit> \
  --released-at <YYYY-MM-DD>
python scripts/start_web_to_tui_observation.py \
  --stable-version <version> --candidate-commit <full-commit> \
  --released-at <YYYY-MM-DD> --write
```

当前 M5 实现已绑定并部署候选 `dev/next-development@e167ab2fc748e4c93d2622f93fa8cc75442b2bb6`，
release 为 `20260816004134`；完整 provenance、健康、迁移和 TUI registry 证据见
`docs/deployment/vps-deployment-evidence-2026-08-15.md`。这只建立了候选身份，不自动开始观察窗口；
该命令仍必须 fail closed，不能用当前 `HEAD`、本地文档状态或旧生产版本冒充稳定候选。

该候选的静态 binding 为 `web-to-tui-candidate-binding.v1`：matrix SHA
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`，published graph SHA
`fc4c19fbb0fc90e931a16223fffd9a4bd782e380afb86893a499874e6b644c84`，runtime schema
`tui-metadata.v3` / version `0.2.0` / build
`agomtui-runtime-0.2.0+a2553996be22`，manifest SHA
`a3c59ed3453610fc708355bbf7d290eb92e23f699333cf36cbdf19a6769ec854`。这些值只用于
候选身份一致性校验，不代表角色化生产 UAT、写后回执或观察窗口已经完成。

观察窗口结束并把不含密钥的 issue-tracker 快照存入仓库后，先 dry-run，再写入 evidence：

```bash
python scripts/build_web_to_tui_defect_evidence.py \
  --snapshot <repo-relative-defect-snapshot.json> --require-clear
python scripts/build_web_to_tui_defect_evidence.py \
  --snapshot <repo-relative-defect-snapshot.json> --write-evidence --require-clear
```

快照必须使用 `web-to-tui-blocking-defect-snapshot.v1`，登记 candidate/source/window、
`created_or_open_during_candidate_window`、tracker system/project/HTTPS endpoint/query filter/
queried_by，以及每条 P0/P1 的 `id`、`priority`、`state`、`created_at`、`closed_at`。

观察窗口结束并把不含密钥的 Prometheus 快照存入仓库后，先 dry-run，再写入 evidence：

```bash
python scripts/build_web_to_tui_production_telemetry.py \
  --snapshot <repo-relative-production-snapshot.json>
python scripts/build_web_to_tui_production_telemetry.py \
  --snapshot <repo-relative-production-snapshot.json> --write-evidence
```

逐 route rollback 证据必须由矩阵中的真实 commit 生成，不得手工复制占位值：

```bash
# owner/wave commit 写入矩阵后执行；本轮已实际运行
python scripts/build_web_to_tui_rollback_catalog.py --write-evidence
python scripts/build_web_to_tui_rollback_catalog.py
```

该工具要求 40 位 commit 在本仓库存在且是当前 `HEAD` 的祖先，并要求 evidence 中的
108 条映射与矩阵完全一致。本轮真实运行返回
`Web-to-TUI rollback catalog: PASS - routes=108 commits=3`；89 个 A 类模板、17 个 B 类
模板及 2 个由后端重定向/运行时实现承接的 route 均绑定到对应迁移提交，没有生成或写入
任何伪造提交。

只有总门禁命令 `python scripts/check_web_to_tui_cutover_readiness.py --require-allow`
成功退出，才允许进入 Classic 清理。

## 到期前允许与禁止的动作

允许：在获得明确发布授权后选定并部署候选稳定版本，再按上述启动器绑定观察窗口；采集按任务
区分的 Classic/TUI 访问量与错误率、登记 P0/P1 缺陷、在预生产复核 graph/runtime 与
route/template 回滚、为 Classic 入口占比低频任务准备 owner/reviewer 双签例外。该例外不能豁免
Classic/TUI 两侧各 20 个 task request 的错误率样本要求。

禁止：删除兼容模板、view、route、菜单或共享 partial；把矩阵
`observability_evidence` 改为完成；移除 Classic 出口；归档本计划；将 M5 或总完成
定义标记为完成。

## 下次评审输入

候选部署并完成机器计算的 14 日窗口后重新评审时，必须提供稳定版本标识、完整 commit 与时间窗、逐任务 UAT
报告、覆盖权限/空态/错误态/旧 URL/回滚的 108/108 route 清理证据、带查询条件/时间/SHA-256 的 P0/P1 缺陷快照、带 production 采集证明的旧入口占比和
Classic/TUI 错误率对照、可校验且已 dry-run 恢复的生产 registry 备份、回滚演练记录，
以及绑定同一版本/commit/矩阵 SHA 的 owner 与独立 reviewer 审批和所有低频例外双签。
任一项缺失，M5 继续保持 DENY。

### 2026-08-15 当前候选部署复核

`20260815230537` 为 code-only、保留数据卷、Celery enabled 的 `-Upgrade` 发布；source commit、
OCI/image、release manifest、health/ready、migrations、canonical schema、TUI registry、Qlib
和 Celery ping 均已复核。候选仍未完成角色化浏览器 UAT、写后 receipt/refresh、生产 registry backup、
14 日 telemetry/defect window、rollback drill 与 owner/reviewer 双签，因此 M5-A 继续 `DENY`，
不得据此清理 Classic 或宣称 TUI production write closure。

同日 `python scripts/check_web_to_tui_cutover_readiness.py --json` 的机器快照仍为
`decision=DENY`：source consistency 已通过（matrix/catalog/evidence SHA
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded` 一致），但
`stable_version_window` 未绑定版本/commit、`route_task_uat` 与 cleanup 尚未绑定候选、
production telemetry 为 `0/101`、production registry backup/restore 与 owner/reviewer
attestations 均缺失。该快照只证明门禁按设计拒绝提前 cutover，不替代生产观察或审批。

### 2026-08-15 23:05 当前候选部署复核

最新候选 `dev/next-development@45281620a8739ee666a1b20e6c6511c0b8101111` 已以
code-only、保留数据卷、Celery enabled 的 `-Upgrade` 发布为 `20260815230537`；远端已验证
`audit.0012_systemauditevent_scope`，Django check 0 issues、HTTPS health 200、容器健康、
TUI registry 与 release manifest/OCI/source 绑定一致。candidate binding 的 matrix/graph/runtime
hash 未漂移；该发布仍不提供角色化浏览器账号、写后 receipt/refresh、生产 14 日 telemetry、
registry backup/restore、rollback drill 或 owner/reviewer 双签，因此 M5 继续 `DENY`。

### 2026-08-16 00:41 当前候选部署复核

最新候选 `dev/next-development@e167ab2fc748e4c93d2622f93fa8cc75442b2bb6` 已以
code-only、保留数据卷、Celery enabled 的 `-Upgrade` 发布为 `20260816004134`；远端验证
release manifest/OCI/source 绑定、`audit.0012_systemauditevent_scope`、Django check、HTTPS
health/ready、容器健康、TUI registry、Qlib 与 Celery ping 均通过；部署前 PostgreSQL 归档
`postgres-20260815-184803.dump` 的尺寸、SHA-256 和 `pg_restore --list` 也通过。

该候选的完整 runtime binding 为 `web-to-tui-candidate-binding.v1`：matrix SHA
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`，published graph SHA
`fc4c19fbb0fc90e931a16223fffd9a4bd782e380afb86893a499874e6b644c84`，schema
`tui-metadata.v3` / runtime `0.2.0` / build `agomtui-runtime-0.2.0+a2553996be22`，
manifest SHA `a3c59ed3453610fc708355bbf7d290eb92e23f699333cf36cbdf19a6769ec854`。

该候选仅替换当前身份绑定，不代表角色化浏览器 UAT、写后 receipt/refresh、生产 14 日
telemetry/defect、registry backup/restore、rollback drill 或 owner/reviewer 双签完成；因此
M5-A 继续 `DENY`，不得据此清理 Classic 或宣称 TUI production write closure。`/api/ready/`
仍原样保留 Alpha/Qlib provider、workspace、Alpha rank 与 market thermometer warnings。

### 2026-08-16 观察窗口起点

使用已提交的 `docs/deployment/web-to-tui-deployment-preflight-20260816004134.json`，
`python scripts/start_web_to_tui_observation.py --write` 严格校验并绑定当前候选，写入
`config/tui/migration/web_to_tui_cutover_evidence.v1.json` 的观察窗口
`2026-08-15..2026-08-29`；deployment attestation SHA-256 为
`a8bd41a0372bf587239fafc33c4c2e478c6a94a02cce4be8cb3cfa98ed7dd3b`。候选切换时按设计清空
未在该候选上重新验证的 UAT、cleanup、telemetry、defect、rollback 和 registry backup
区块；截至当前 readiness 仍为 `DENY`（UAT `0/108`、telemetry `0/101`、rollback/backup/
审批均缺失）。观察起点不等于角色化生产 UAT、写后回执、稳定窗口完成或 cutover 授权。

### 2026-08-16 00:46 当前候选部署复核

最新候选 `dev/next-development@516f4e228699231831222613ffe56b9f6b5f0713` 已以
code-only、保留数据卷、Celery enabled 的 `-Upgrade` 发布为 `20260816082603`；远端验证
release manifest/OCI/source 绑定、`account.0054`、Django deploy check、HTTPS
health/ready、容器健康、TUI registry、Qlib 与 Celery ping 均通过。部署报告为
`dist/remote-build-reports/remote-build-report-20260816082603.json`，image ID 为
`sha256:6bb3bec1d83b165c902654d031d636fc60374567aa4afec2cc927dd055832d8a`。

本次只读部署观测在 `2026-08-16T00:44:32Z` 复核：HTTPS `/api/health/` 与 `/api/ready/`
均返回 `200`；`/api/ready/` 仍报告 Alpha/Qlib provider degraded、workspace recommendation
stale、Alpha rank source stale 与 market thermometer partial-stale warnings。该候选的
结构化部署 preflight 为
`docs/deployment/web-to-tui-deployment-preflight-20260816082603.json`，只绑定代码身份和
运行启动，不包含角色化浏览器账号、写后 receipt/refresh、14 日 telemetry、registry
backup/restore、rollback 或 owner/reviewer 双签；M5-A 继续 `DENY`。

### 2026-08-16 01:09 当前候选部署复核

最新候选 `dev/next-development@6c4086231a19005c750c856e78613b766bfd3609` 已以
code-only、保留数据卷、Celery enabled 的 `-Upgrade` 发布为 `20260816085250`；远端验证
release manifest/OCI/source 绑定、`account.0054`、Django deploy check、HTTPS
health/ready、容器健康、TUI registry、Qlib 与 Celery ping 均通过。部署报告为
`dist/remote-build-reports/remote-build-report-20260816085250.json`，image ID 为
`sha256:1d84d3db8d991eee385e4bfcf9160d0271cc8262924555c23346ade28a091c89`。

本次只读部署观测在 `2026-08-16T01:09:24Z` 复核：HTTPS `/api/health/` 与 `/api/ready/`
均返回 `200`；`/api/ready/` 仍报告 Alpha/Qlib provider degraded、workspace recommendation
stale、Alpha rank source stale 与 market thermometer partial-stale warnings。该候选的
结构化部署 preflight 为
`docs/deployment/web-to-tui-deployment-preflight-20260816085250.json`，只绑定代码身份和
运行启动，不包含角色化浏览器账号、写后 receipt/refresh、14 日 telemetry、registry
backup/restore、rollback 或 owner/reviewer 双签；M5-A 继续 `DENY`。candidate binding 仍为
`web-to-tui-candidate-binding.v1`：matrix `bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、
graph `fc4c19fbb0fc90e931a16223fffd9a4bd782e380afb86893a499874e6b644c84`、schema
`tui-metadata.v3`、runtime `0.2.0`、build `agomtui-runtime-0.2.0+a2553996be22`、manifest
`a3c59ed3453610fc708355bbf7d290eb92e23f699333cf36cbdf19a6769ec854`。

### 2026-08-16 01:09 观察窗口重置

`python scripts/start_web_to_tui_observation.py --write --replace` 已读取并校验已提交的
`docs/deployment/web-to-tui-deployment-preflight-20260816085250.json`，绑定候选
`20260816085250/6c4086231a19005c750c856e78613b766bfd3609`，deployment attestation SHA-256 为
`254b1dabe85181cd90120a1d872ed6668a69583fca9c8f2c3f20fb5859acd486`，新窗口为
`2026-08-16..2026-08-30`。候选切换按设计清空未在该候选上重新验证的 UAT、cleanup、telemetry、
defect、rollback 与 registry backup 区块；截至当前机器 readiness 仍 `DENY`（UAT `0/108`、
telemetry `0/101`、rollback/backup/审批均缺失）。观察起点不等于角色化生产 UAT、写后回执、
稳定窗口完成或 cutover 授权。

### 2026-08-16 03:31 当前候选部署复核

最新候选 `dev/next-development@7fe4b2ef60f9ef838b5ab76e639f3c1c8e42580a` 已以
code-only、保留数据卷、Celery enabled 的 `-Upgrade` 发布为 `20260816112017`；远端验证
release manifest/OCI/source 绑定、`account.0054`、Django deploy check、HTTPS
health/ready、容器健康、TUI registry、Qlib 与 Celery ping 均通过。部署报告为
`dist/remote-build-reports/remote-build-report-20260816112017.json`，image ID 为
`sha256:8037ddee4996b9564e5f73f4ca79ea341c7d252fc88ed2bc09612d4947794978`。

本次只读部署观测在 `2026-08-16T03:31:51Z` 复核：HTTPS `/api/health/` 与 `/api/ready/`
均返回 `200`；health response SHA 为
`0ff5991805be87e18c7cca2e939c931fcac5b2466d18c5c08184a4c230ea993c`，ready response SHA 为
`bfb1b7b5ba14495d7ecf637060792cbd916a11f29e8c5c714f68192ff74ca372`。`/api/ready/` 仍报告
Alpha/Qlib provider degraded、workspace recommendation stale 与 Alpha rank source stale；
这些数据新鲜度警告没有被部署成功掩盖。结构化运行摘要见
`docs/deployment/vps-runtime-verification-2026-08-16-1120.json`。

该候选的 candidate binding 为 `web-to-tui-candidate-binding.v1`：matrix
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、published graph
`c01ccb8096642ca8916eb55d641ee73355832f8a90bce548756a50c865bc466e`、schema
`tui-metadata.v3` / runtime `0.2.0` / build `agomtui-runtime-0.2.0+972e3f3e689a`、
manifest `9088808a993a22e0bcd8c0c6c0d78df36ba11784071e8bad7ad52cc2cf0e7039`。该发布只绑定
代码、图谱和运行启动，不包含角色化浏览器账号、写后 receipt/refresh、14 日 telemetry、
registry backup/restore、rollback 或 owner/reviewer 双签；M5-A 继续 `DENY`。

### 2026-08-16 13:35 当前候选部署复核

最新候选 `dev/next-development@b051c369e97732ea10f7293d923aa8882a3a691c` 已以
code-only、保留 PostgreSQL/Redis 数据卷、Celery enabled 的 `-Upgrade` 发布为
`20260816131435`。部署报告为
`dist/remote-build-reports/remote-build-report-20260816131435.json`，OCI image ID 为
`sha256:e65b8ef05fb3cdd3417830dbe7c233fedbab4e7254f45440cc8cd23159cb00cb`。独立
`deploy_vps_verify.py` 已复核 release/source/image 绑定、Django check、迁移与 canonical schema、
TUI registry、HTTPS/Caddy、Qlib、Celery worker/beat 与 ping。

只读观测时间为 `2026-08-16T05:35:56Z`：HTTPS `/api/health/` 与 `/api/ready/` 均返回
`200`；health response SHA 为
`00ba29755f44ba617967d1f6665543870d80432d61daf5db45f58b53556d9eb0`，ready response SHA 为
`f7534f8dd768c453aca2bfb28a5ab804809c0cbcc1e77ae7aff1d5ab0831ca20`。Caddy domain 为
`demo.agomtrade.pro` 且 TLS certificate 有效；ready 仍明确报告
`alpha_qlib_provider_degraded`、`workspace_recommendations_stale`、`workspace_alpha_rank_source_stale`。
结构化运行摘要见 `docs/deployment/vps-runtime-verification-2026-08-16-1335.json`。

该候选的 candidate binding 为 `web-to-tui-candidate-binding.v1`：matrix
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、published graph
`c45ab376e2297ab235ed08621663bfe721b6a5c254fcc2097b7a2201deae0e98`、schema
`tui-metadata.v3` / runtime `0.2.0` / build `agomtui-runtime-0.2.0+1b3dd9b98ae5`、
manifest `c8a565dc9580b7bf40b68c9d7f495529df6258e7b78c0f4e0f2b486871991659`。该发布只证明
当前代码/运行身份与只读健康观测，不包含角色化浏览器账号、写后 receipt/refresh、14 日
telemetry、registry backup/restore、rollback 或 owner/reviewer 双签；M5-A 继续 `DENY`。

### 2026-08-16 15:34 当前候选部署复核

最新候选 `dev/next-development@e29e15b09b47e07d9724b9cbc750ae2882310693` 已以
code-only、保留 PostgreSQL/Redis 数据卷、Celery enabled 的 `-Upgrade` 发布为
`20260816151607`。部署报告为
`dist/remote-build-reports/remote-build-report-20260816151607.json`，OCI image ID 为
`sha256:7663b1a13f0f6ca61b36cc3f8a673b25b08480b6a0c8c5d62c9eed840a7e40ae`。独立
`deploy_vps_verify.py` 已复核 release/source/image 绑定、Django check、迁移与 canonical schema、
TUI registry、HTTPS/Caddy、Qlib、Celery worker/beat 与 ping。

只读观测时间为 `2026-08-16T07:34:17Z`：HTTPS `/api/health/` 与 `/api/ready/` 均返回
`200`；health response SHA 为
`e09691a05aefead4e9d1b0e17c00e3340ebfe8e8ec32caff35ebd0f4d6e4ba06`，ready response SHA 为
`91df358a1f19328ab1087a433941076469454a6270887c6339502a03283e5afc`。Caddy domain 为
`demo.agomtrade.pro` 且 TLS certificate 有效；ready 仍明确报告
`alpha_qlib_provider_degraded`、`workspace_recommendations_stale`、`workspace_alpha_rank_source_stale`。
结构化运行摘要见 `docs/deployment/vps-runtime-verification-2026-08-16-1534.json`。

该候选的 candidate binding 仍为 `web-to-tui-candidate-binding.v1`：matrix
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、published graph
`42a20ddb5bca62cbdb6a9ff1eda2ced91515354662e406428a2a6c40840390ba`、schema
`tui-metadata.v3` / runtime `0.2.0` / build `agomtui-runtime-0.2.0+8e5b1ff43be5`、
manifest `98494ca640c4f4dfb6f1e8b08778d669228d4dc1a85947b582a33e1c8036ee6c`。本次只证明
当前代码/运行身份与只读健康观测；没有登录或业务写入，角色化浏览器 UAT、写后 receipt/refresh、
14 日 telemetry、registry backup/restore、rollback 或 owner/reviewer 双签仍缺，M5-A 继续 `DENY`。

### 2026-08-16 16:24 当前候选部署复核

最新候选 `dev/next-development@07d5d1d338c70ebc1d347663b48b09b38335fce5` 已以
code-only、保留 PostgreSQL/Redis 数据卷、Celery enabled 的 `-Upgrade` 发布为
`20260816160127`。远端 release manifest 显示 release dir
`/opt/agomtradepro/releases/source-20260816160127`，OCI image ID 为
`sha256:57fbe5504cbec2a2c9c072b3434460aceae5a9b74cd0fc83f5d7be6dba7dab56`；
preflight 见 `docs/deployment/web-to-tui-deployment-preflight-20260816160127.json`。

只读观测时间为 `2026-08-16T08:24:05Z`：HTTPS `/api/health/` 与 `/api/ready/`
均返回 `200`；health response SHA 为
`513084211e3334448dbfcae2f0af9b1d14b406c51e0eb6e8d539b26e34bae00f`，ready response SHA 为
`5177675f73c49b6ce76e223d4c0764d0424e0cbf586852c93c1c4eb66398731a`。迁移、canonical schema、
Django deploy check、TUI registry、release identity、Celery ping 与 Qlib module 复核通过；
结构化运行摘要见 `docs/deployment/vps-runtime-verification-2026-08-16-1624.json`。

`/api/ready/` 仍报告 `alpha_qlib_provider_degraded`、`workspace_recommendations_stale`、
`workspace_alpha_rank_source_stale` 与 `market_thermometer_partial_stale`。本次只证明
代码/运行身份与只读健康观测；没有登录或业务写入，角色化浏览器 UAT、写后 receipt/refresh、
14 日 telemetry/defect、registry backup/restore、rollback 或 owner/reviewer 双签仍缺，
M5-A 继续 `DENY`。PostgreSQL custom-format archive 仅完成 SHA 与 `pg_restore --list` 可读性
检查，没有 restore/rebuild、RTO/RPO 或 rollback drill。

该候选的 candidate binding 为 `web-to-tui-candidate-binding.v1`：matrix
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、published graph
`42a20ddb5bca62cbdb6a9ff1eda2ced91515354662e406428a2a6c40840390ba`、schema
`tui-metadata.v3` / runtime `0.2.0` / build `agomtui-runtime-0.2.0+8e5b1ff43be5`、
manifest `98494ca640c4f4dfb6f1e8b08778d669228d4dc1a85947b582a33e1c8036ee6c`。该候选仅
重置并开始 `2026-08-16..2026-08-30` 观察窗口，不跨候选继承任何 UAT 或 telemetry 结果。

### 2026-08-16 17:21 当前候选部署复核

最新候选 `dev/next-development@fc145423c4de04cae20c3a6a2e94780505aa5938` 已以
code-only、保留 PostgreSQL/Redis 数据卷、Celery enabled 的 `-Upgrade` 发布为
`20260816170851`。远端 release manifest 显示 release dir
`/opt/agomtradepro/releases/source-20260816170851`，OCI image ID 为
`sha256:04d08b5d3e1b1032abfbbefbeb4d9df0f4a6f8c33c706981056c1f36031112eb`；
preflight 见 `docs/deployment/web-to-tui-deployment-preflight-20260816170851.json`，
SHA `8639dc3a443e67fd44d51bc74b0f574b93f8a62493078167b1f63d0a2a2b5c7a`。

只读观测时间为 `2026-08-16T09:21:08Z`：HTTPS `/api/health/` 与 `/api/ready/`
均返回 `200`；health response SHA 为
`374ce1945abfd549b08ce103c5155004f5f83317b08a4e9b5ac16e7ed3b6a469`，ready response SHA 为
`7874fdb8c615d532d0da953a4d2f7df0d3d6511e0d3d8c6fb717706bda2f7007`。迁移、canonical schema、
Django deploy check、TUI registry、release identity、Celery ping 与 Qlib module 复核通过；
结构化运行摘要见 `docs/deployment/vps-runtime-verification-2026-08-16-1721.json`。

首次部署预备份钩子返回空错误且未切换运行容器；随后独立下载并校验
`/opt/agomtradepro/backups/database/postgres-20260816-110120.dump`（`140820006` bytes，
SHA `43f7b2fb8d0d565831021a1cd0a8fb7adda2809954c3df343597c8f884452565`，远端
`pg_restore --list` `7167` entries），再重试成功。`/api/ready/` 仍报告
`alpha_qlib_provider_degraded`、`workspace_recommendations_stale`、
`workspace_alpha_rank_source_stale` 与 `market_thermometer_partial_stale`。

本次只证明当前代码/运行身份与只读健康观测；没有登录或业务写入，角色化浏览器 UAT、写后
receipt/refresh、14 日 telemetry、registry backup/restore、rollback 或 owner/reviewer 双签
仍缺，M5-A 继续 `DENY`。PostgreSQL archive 仅完成 SHA 与 `pg_restore --list` 检查，没有
restore/rebuild、RTO/RPO 或 rollback drill。候选 binding 的 matrix/graph/runtime manifest
与上一候选相同，仅 source commit/release/image 更新；观察窗口从该候选重新开始，不跨候选
继承 UAT 或 telemetry。
该候选完整 binding 为：version `web-to-tui-candidate-binding.v1`、candidate version
`20260816170851`、candidate commit `fc145423c4de04cae20c3a6a2e94780505aa5938`、matrix
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、graph
`42a20ddb5bca62cbdb6a9ff1eda2ced91515354662e406428a2a6c40840390ba`、schema `tui-metadata.v3`、
runtime `0.2.0`、build `agomtui-runtime-0.2.0+8e5b1ff43be5`、manifest
`98494ca640c4f4dfb6f1e8b08778d669228d4dc1a85947b582a33e1c8036ee6c`。

### 2026-08-16 18:11 当前候选部署复核

候选 `dev/next-development@5a13125bb84eb1b20e623d7c1388a0d7632294cb` 已以 code-only、保留
PostgreSQL/Redis 数据卷、Celery enabled 的 `-Upgrade` 发布为 `20260816181141`。release dir
为 `/opt/agomtradepro/releases/source-20260816181141`，OCI image ID 为
`sha256:1add6e57714a6ee41e3a3153a46e0c6e578f29a8374ea18e91cb53b65a7e2632`；preflight 为
`docs/deployment/web-to-tui-deployment-preflight-20260816181141.json`，SHA
`b449240339413578c0aaea9d2868f4f826e4454d51c9d5dcb607a87aefd343a2`。

只读观测截至 `2026-08-16T10:29:06Z`：HTTPS `/api/health/` 与 `/api/ready/` 均为 `200`；
health SHA `bacab80cf37e6f8c94189606184a9d3a040ec8e56cf820b1e768cda207522fb3`，ready SHA
`a3afe4e633840aadb84d0c730004c9f40ba114531ef8fc4d130db306ae1e5ed4`。迁移、canonical schema、
Django check、TUI registry、Celery ping、Qlib module 与容器健康复核通过；结构化摘要见
`docs/deployment/vps-runtime-verification-2026-08-16-1811.json`。部署前备份钩子成功创建
`/opt/agomtradepro/backups/database/postgres-20260816-121912.dump`；本次仅记录远端路径，未把
未取得的尺寸/SHA 当作证据。

该候选完整 binding 为：version `web-to-tui-candidate-binding.v1`、candidate version
`20260816181141`、candidate commit `5a13125bb84eb1b20e623d7c1388a0d7632294cb`、matrix
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、graph
`42a20ddb5bca62cbdb6a9ff1eda2ced91515354662e406428a2a6c40840390ba`、schema `tui-metadata.v3`、
runtime `0.2.0`、build `agomtui-runtime-0.2.0+8e5b1ff43be5`、manifest
`98494ca640c4f4dfb6f1e8b08778d669228d4dc1a85947b582a33e1c8036ee6c`。观察窗口需随该候选重新
绑定为 `2026-08-16..2026-08-30`，不跨候选继承 UAT 或 telemetry。

`/api/ready/` 仍保留 `alpha_qlib_provider_degraded`、`workspace_recommendations_stale`、
`workspace_alpha_rank_source_stale` 与 `market_thermometer_partial_stale`；本次没有登录、
角色化浏览器 UAT 或业务写入。写后 receipt/refresh、14 日 telemetry、registry backup/restore、
rollback 与 owner/reviewer 双签仍缺，M5-A 继续 `DENY`；AUD-01/EVID-01 authority/publisher
门禁不因代码部署解除。

### 2026-08-16 22:39 当前候选部署复核

候选 `dev/next-development@443658d33159dd80a35b3001ae2c8505113e3fff` 已以 code-only、保留
PostgreSQL/Redis 数据卷、Celery enabled 的 `-Upgrade` 发布为 `20260816223921`。release dir
为 `/opt/agomtradepro/releases/source-20260816223921`，OCI image ID 为
`sha256:c5930a8eb13a8ff4d09880698ceab2d9ee4758b48e8e8cdf1adbb61607b56f73`；preflight 为
`docs/deployment/web-to-tui-deployment-preflight-20260816223921.json`，SHA
`f7d03e0184cccfae22b231c9187de8e05a931d9e15b51e061bbc21fbece4aa67`。

只读观测截至 `2026-08-16T14:58:08Z`：HTTPS `/api/health/` 与 `/api/ready/` 均为 `200`；
health SHA `cd2a7891e4df7b35f9878d245df36f39c567ef36507d2a58928abe076f06da78`，ready SHA
`59c346cf007900a025101deaf1c6a58a64ecb5963081a8352ee092c00e409b41`。迁移、canonical schema、
Django check、TUI registry、release identity、Celery ping、Qlib module 与容器健康复核通过；
结构化摘要见 `docs/deployment/vps-runtime-verification-2026-08-16-2258.json`。部署前
PostgreSQL custom-format archive 由成功的 pre-deploy hook 创建于
`/opt/agomtradepro/backups/database/postgres-20260816-164649.dump`；本次未执行 restore/rebuild、
RTO/RPO 或 rollback drill。当前候选的 EVID-01 authority inventory 仍为
`blocked_zero_seed_authority`，12 个 authority/evidence 表均为 `0` 行，摘要见
`docs/deployment/evid-01-authority-inventory-2026-08-16-2258.json`。

该候选完整 binding 为：version `web-to-tui-candidate-binding.v1`、candidate version
`20260816223921`、candidate commit `443658d33159dd80a35b3001ae2c8505113e3fff`、matrix
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、graph
`42a20ddb5bca62cbdb6a9ff1eda2ced91515354662e406428a2a6c40840390ba`、schema `tui-metadata.v3`、
runtime `0.2.0`、build `agomtui-runtime-0.2.0+8e5b1ff43be5`、manifest
`98494ca640c4f4dfb6f1e8b08778d669228d4dc1a85947b582a33e1c8036ee6c`。观察窗口需随该候选
重新绑定为 `2026-08-16..2026-08-30`，不跨候选继承 UAT 或 telemetry。

`/api/ready/` 仍保留 `alpha_qlib_provider_degraded`、`workspace_recommendations_stale`、
`workspace_alpha_rank_source_stale` 与 `market_thermometer_partial_stale`；本次没有登录、
角色化浏览器 UAT 或业务写入。写后 receipt/refresh、14 日 telemetry、registry backup/restore、
rollback 与 owner/reviewer 双签仍缺，M5-A 继续 `DENY`；AUD-01/EVID-01 authority/publisher
门禁不因代码部署解除。

### 2026-08-17 当前候选运行观测

当前 `dev/next-development@3ceafaf193e87626be7458531c66e96b11f7df84` 已发布为
`20260817002134`，release manifest/runtime identity 与 source commit 一致，web healthy，
`/api/health/` HTTP 200，迁移与 canonical schema 检查通过，TUI registry check、Qlib identity、
Celery worker/beat 与 ping 均通过。结构化部署报告为
`dist/remote-build-reports/remote-build-report-20260817002134.json`；该产物被忽略，不作为
源码证据提交。

本次仍是 code-only、保留 PostgreSQL/Redis 数据卷的只读运行观测，没有登录、角色化浏览器 UAT、
写后 receipt/refresh、14 日 telemetry、registry backup/restore、rollback 或 owner/reviewer
双签。M5-A、AUD-01/EVID-01 等门禁状态不因部署成功改变；ready 中既有 Alpha/Qlib 与 workspace
freshness warnings 仍需后续数据/生产证据处理。

### 2026-08-17 13:15 当前候选部署复核

本节仅记录仓库侧 runtime manifest 重新生成后的候选绑定，不代表新增 VPS 部署或生产 UAT。
现有已部署 release `20260816223921`、OCI 与健康检查证据保持不变；本次只同步 source-side
TUI IA/actionability 变更产生的 runtime identity，M5-A 继续 `DENY`。

该候选 binding 仍为 `web-to-tui-candidate-binding.v1`：candidate version
`20260816223921`、candidate commit `443658d33159dd80a35b3001ae2c8505113e3fff`、matrix
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、graph
`42a20ddb5bca62cbdb6a9ff1eda2ced91515354662e406428a2a6c40840390ba`、schema `tui-metadata.v3`、
runtime `0.2.0`、build `agomtui-runtime-0.2.0+21ef64c7a7e5`、manifest
`ade5109f97ee15d78987e1f63fe511f23ad2043f49aa43f1a2051da71687e378`。未新增登录、角色化
浏览器 UAT、写后 receipt/refresh、14 日 telemetry、backup/restore、rollback 或双签证据。

### 2026-08-18 本地候选证据章节一致性守卫

本地一致性测试现在以 `config/tui/migration/web_to_tui_cutover_evidence.v1.json` 中的
不可变 candidate binding 为准，并在 readiness/deployment 文档中选择同时包含完整
candidate、matrix、graph 与 runtime binding 的匹配章节；较新的 TAR 或普通 VPS 观测不会
被误当作 M5 当前候选。`tests/unit/test_web_to_tui_candidate_consistency.py` 为 `1 passed`，
TUI focused 回归合计 `29 passed`。这只是证据章节选择与静态绑定守卫，不更新候选、不新增
VPS preflight，也不改变 M5 的生产 gate；角色化浏览器 UAT、写后 receipt/refresh、14 日
telemetry、backup/restore、rollback 与 owner/reviewer 双签仍缺，readiness 继续 `DENY`。

### 2026-08-19 20:58 当前候选部署复核

候选 `dev/next-development@f3881a04cf0b5d5bff5d2b7e5a6bf25d523667e2` 已以 code-only、保留
PostgreSQL/Redis 数据卷、Celery enabled 的 `-Upgrade` 发布为 `20260820043710`。部署 preflight
为 `docs/deployment/web-to-tui-deployment-preflight-20260820043710.json`，其 SHA-256 为
`3e61aebc84527501a7f2154c9288d48353e51e39280a1cb5f6c6fff264978f4f`；OCI image 为
`sha256:ac621fb9cd594045e211e5a4e7cc16c11fea10ca8c34fb5bea148572b4347dc5`，source/image
identity 与 verifier 一致。公网只读探测 `/api/health/`、`/api/ready/`、`/api/` 均 `5/5` 返回
`200`；未认证 `/api/terminal/runs/` 返回 `403`，`/api/regime/current/` 仍为
`503 decision_runtime_blocked`，fail-closed 保持。

该候选完整 binding 为：version `web-to-tui-candidate-binding.v1`、candidate version
`20260820043710`、candidate commit `f3881a04cf0b5d5bff5d2b7e5a6bf25d523667e2`、matrix
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、graph
`5a2234c84d4156001a8bde73a7fe9a5c86534b77a6e87da68764043b55d7b597`、schema `tui-metadata.v3`、
runtime `0.2.0`、build `agomtui-runtime-0.2.0+b00df1fa9186`、manifest
`7d2d059828553fec11b83df19e09698a1025fd818c103c630d2f432d6550000f`。候选替换后观察窗口
重新从 `2026-08-19` 起算，不跨候选继承 UAT 或 telemetry。

本次只完成候选身份、部署、短窗口只读健康与认证边界复核；没有登录、角色化浏览器 UAT、
业务写后 receipt/refresh、14 日 telemetry、registry backup/restore、rollback 或
owner/reviewer 双签，M5-A/TUI-01 继续 `DENY`。

### 2026-08-20 independent role/browser UAT on the newer TUI cleanup release

Against the active HTTPS deployment `dev/next-development@05970a925f0b348574a1805c243d7d9140d3e243`
(`/opt/agomtradepro/releases/source-20260820091752`), dedicated operator and regular users
completed isolated browser acceptance: operator queue visibility versus regular denial, strategy
create/detail/update/readback, personal AI provider create/detail/update/readback (including the
explicit sensitive API-key prompt), confirmation cancel, parameterized primary reads, and the
least-privileged direct-read matrix all passed. The two controlled strategy/provider rows were
deleted by exact selectors after the run and verified absent. The test-only UAT change keeps
credentials out of URL prefill and uses an inert run-scoped placeholder only in the browser
prompt.

This evidence is intentionally independent of the formal M5 candidate binding, which still names
`f3881a04...` / release `20260820043710`; it does not rebind the registry or readiness gate. It
does not cover 14-day telemetry, write-receipt/refresh audit, registry backup/restore, live
rollback, capacity/chaos, external AgomTUI portability or owner/reviewer sign-off. M5-A and
TUI-01/TUI-02 remain `DENY`/`awaiting` as recorded by the registry.

### 2026-08-20 post-fix role/browser acceptance on `28e0c2608`

The active HTTPS deployment was advanced to `dev/next-development@28e0c2608eea1c0a4aed51c3a54eed80220db503`,
release `20260820114848`, using code-only `-Upgrade` with PostgreSQL/Redis volumes preserved and
Celery enabled. The built-in and independent expected-commit verifiers exited `0`; Caddy/TLS,
health, containers, Django/migrations/schema, TUI registry, Qlib, backup, worker/beat and Celery
ping were green. The deployment report is
`dist/remote-build-reports/remote-build-report-20260820114848.json`.

The browser acceptance also verified the bounded deep-link form fix: after layout, a create/update
form is scrolled into the action panel viewport and focused rather than remaining below the
scroll container. With dedicated operator/regular users and a unique run suffix, the final HTTPS
Playwright selection passed `3/3`: queue role boundary, strategy create/detail/update/readback,
and user-owned AI-provider create/detail/update/readback. Controlled rows were removed by exact
owner/name selectors and the post-cleanup query returned zero matches. A prior reused fixture
suffix was rejected as duplicate test data and is not counted as final acceptance.

This evidence is tied to the active release only; it does not rebind the formal M5 candidate,
which remains `f3881a04...` / `20260820043710`. The M5-A/TUI-01 gate still requires write
receipt/refresh evidence, 14-day telemetry, registry backup/restore, live rollback,
owner/reviewer approval and the remaining external/capacity dependencies. Those requirements
remain `DENY`/`awaiting` rather than being inferred from this short browser window.

### 2026-08-20 21:15 当前候选部署复核

候选 `dev/next-development@2f4554b5192191970a3ccbc98420388881725079` 的 code-only
deployment preflight 为 `docs/deployment/web-to-tui-deployment-preflight-20260820211526.json`，
SHA-256 `637f646d92e646fb8d27e444bda4b967c109b8350fda26be50603afaadb39223`；记录的 release 为
`20260820211526`，OCI image 为
`sha256:74d094b6e606ee79a6e73ffd49364a3787c611511432d5194dc9902b2ec17696`，health/readiness
只读探测均为 `200`。该记录补齐 cutover evidence 中已有候选的 deployment 身份，不能被
解释成新的部署或 M5 关闭授权。

完整 candidate binding 为 `web-to-tui-candidate-binding.v1`：candidate version
`20260820211526`、candidate commit `2f4554b5192191970a3ccbc98420388881725079`、matrix
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、graph
`5a2234c84d4156001a8bde73a7fe9a5c86534b77a6e87da68764043b55d7b597`、schema
`tui-metadata.v3`、runtime `0.2.0`、build `agomtui-runtime-0.2.0+7bc2ca13ee9d`、manifest
`7da3c92633c8f71767687a7fe4b67fed5b8f4445a6c60106dc5a43f3c1771165`。

本节只修复候选身份在 readiness 文档中的证据链，不新增角色化浏览器 UAT、写后
receipt/refresh、14 日 telemetry、registry backup/restore、rollback 或 owner/reviewer
双签；当前 M5 readiness 仍为 `DENY`，不得执行 cleanup 或 cutover。

### 2026-08-24 当前机器 readiness 只读快照

重新运行 `python scripts/check_web_to_tui_cutover_readiness.py --json`，结果仍为
`decision=DENY`（`as_of=2026-08-24`）。source consistency 与 execution dependency 通过；
stable candidate/version window、`108` 路由/任务 UAT、cleanup scope、`101` 项 production
telemetry、rollback drill、production registry backup 以及 owner/reviewer attestations
均明确未通过。原始机器快照为
[`web-to-tui-readiness-observation-2026-08-24.json`](../deployment/web-to-tui-readiness-observation-2026-08-24.json)，
SHA-256=`f60e19b683f7f31d900dd1964403d8bbd162f27398991757878b8b319dd037b5`。

这是只读仓库 gate 的当前事实，不是生产 UAT 或候选重绑：没有部署 VPS、没有创建备份、
没有执行 cleanup/rollback、没有写生产或调整 M5 gate；`TUI-01` 继续 `awaiting_production`，
`TUX-02`/`TUX-04` 继续按 registry 暂停，B/S、CLI/API 仍只向服务器提交请求，用户不安装
本地 Agent、模型或 provider 软件。

### 2026-08-29 `main` 源候选冻结与生产只读 preflight

将已通过合并后四条 GitHub Actions 的 `origin/main@07d96d6cdc24262e7cc6eb2f4a7e57308f962d70`
冻结为新的 **source candidate**。该提交的 matrix SHA 为
`e3027671d02d876c9f4b38b9d86395d45e26c0f2b344eb0646086be31869cd5d`，published graph SHA 为
`63be10ee25bb73c87861c18cc92355938fd7abc096c33852bf5f904d4db532a2`，runtime manifest SHA 为
`bfa8eeb81da5165414a882f77f3333268847f217f858925a40597d720548e6fe`，runtime build 为
`agomtui-runtime-0.2.0+7b2efaff4f9a`。尚未部署，因此 candidate version、release ID、OCI image
identity 与 observation 起点保持 unavailable，不得用源代码冻结冒充生产候选绑定。

VPS 只读 verifier 证明当前生产仍运行 `45d7616d3c38a86853104f93dbd3f13bd9a48838`、image
`sha256:c481bb88ac6547165bdebcd34573a6f0d69b042c93ce37136b8ea3b160a1ce66`，与新 source
candidate 不同；Caddy/TLS、web、Django deploy check、迁移、canonical Data Center schema、TUI
registry、`pyqlib=0.9.7`、Celery worker/beat/ping 均通过。公网 `/api/health/`、`/api/ready/`、
`/api/audit/health/` 为 `200`，匿名 `/api/tui/` 为预期 `403`；`/api/decision-ready/` 保持
`503 blocked`、`must_not_use_for_decision=true`。原始预检汇总为
[`release-candidate-preflight-2026-08-29-07d96d6d.json`](../deployment/release-candidate-preflight-2026-08-29-07d96d6d.json)，
SHA-256=`a739324bf672fe68b15f60c4a767c3075444ed97d2d9859d6ff4a736244061d8`。

当前 `python scripts/check_web_to_tui_cutover_readiness.py --json --as-of 2026-08-29` 仍为
`DENY`；旧 evidence matrix、候选与当前 source 不一致，UAT、telemetry、rollback、registry
backup 和双签均未绑定。部署前另发现 `python scripts/check_python_version_consistency.py`
因 `docker/Dockerfile.qlib-train` 仍为 Python 3.10 而失败，违反 Python 3.11 runtime policy。
因此本轮没有部署、重启、迁移、备份创建、生产写入、候选重绑或观察窗口启动；TUI-01 继续
`awaiting_production`。下一步必须先获得有界 repository remediation 授权，修复该版本门禁、
通过 CI 并合并后重新冻结 `main`，再申请精确的 code-only 生产部署。

### 2026-08-29 Qlib 训练镜像 Python 3.11 repository remediation

经授权完成有界修复：`docker/Dockerfile.qlib-train` 已从 `python:3.10-slim` 升级为
`python:3.11-slim`，Qlib 训练运行时文档同步收敛到 Python 3.11，并新增回归测试锁定
Python 基础镜像、`pyqlib` distribution、`libgomp1` 和 Docker context 临时目录排除规则。
Python 版本一致性门禁、Compose config、Dockerfile BuildKit `--check` 均通过；聚焦测试
`45 passed`。隔离 `python:3.11-slim` 容器实际运行 Python 3.11.14，成功安装
`pyqlib=0.9.7` 的 CPython 3.11 wheel，`qlib` 模块落在 Python 3.11 site-packages，错误的
`qlib` distribution 不存在。

结构化修复证据见
[`release-candidate-remediation-2026-08-29-py311.json`](../deployment/release-candidate-remediation-2026-08-29-py311.json)，
SHA-256=`1156d941e429e79262bef23ab327d3492033e436bc8c741e1cf0d1bbcb45437d`。完整依赖安装在当前
Docker Desktop 中因 exit `137` 未完成；完整仓库 context build 因本地未跟踪数据超过
`1.04 GB` 被中止，两项均如实保留为后续 CI/受控构建验证风险。Python 3.11 repository
阻断已在工作树内修复，但 `07d96d6d…` 不再可作为最终部署候选；仍须提交、CI、review、合并并
重新冻结新的 `main`。本轮未访问生产、未部署、未重绑候选或启动观察窗口，M5 readiness 继续
`DENY`，TUI-01 继续 `awaiting_production`。
