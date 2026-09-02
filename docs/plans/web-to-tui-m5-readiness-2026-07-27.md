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

> 当前候选状态（2026-09-03）：生产候选已绑定 `aa7127ff4d9f71555b0d0486314da5518bd2ac20` /
> release `20260901232812`，`TUI-01`/`TUI-03` 已完成，`TUI-02` 保持 `5/10 DENY`。2026-09-02
> 受控 web-only restart 已使此前 retained source 作废；当前等待重启后首个真实样本及新的精确
> 14 日窗口。下面的“当前证据”表是 2026-08-13 历史快照，仅供追溯，不代表当前候选。

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

### 2026-08-16 历史候选（非当前生产候选）

当时的 M5 实现已绑定并部署候选 `dev/next-development@e167ab2fc748e4c93d2622f93fa8cc75442b2bb6`，
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

快照必须使用 `web-to-tui-blocking-defect-snapshot.v2`，登记 candidate/source/window、
`created_or_open_during_candidate_window`、tracker system/project/HTTPS endpoint/query filter/
queried_by，以及每条 P0/P1 的 `id`、`priority`、`state`、`created_at`、`closed_at`；`queried_at`
必须是达到 retained binding 精确 eligible instant 后的 UTC timestamp。

观察窗口结束并把不含密钥的 Prometheus 快照存入仓库后，先 dry-run，再写入 evidence：

```bash
python scripts/build_web_to_tui_production_telemetry.py \
  --snapshot <repo-relative-production-snapshot.json>
python scripts/build_web_to_tui_production_telemetry.py \
  --snapshot <repo-relative-production-snapshot.json> --write-evidence
```

Prometheus 快照必须使用 `web-to-tui-production-telemetry-snapshot.v2`，且 `collected_at` 必须是
达到同一 exact eligible instant 后的 UTC timestamp；日期字符串不能通过。

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

### 2026-08-29 合并后 `main` source candidate 重新冻结

Qlib Python 3.11 修复提交 `86498b1f990b7e24184484b762d6de47e823de16` 已通过 `main` 四条
push CI；canonical evidence PR #10 经双套 push/PR CI、review 和 merge 后，新的
`origin/main@09269c14db1024584913081db49919085f34d008` 已冻结为 source candidate，明确取代
`07d96d6d…`。source binding 的 matrix、published graph、runtime manifest SHA 仍分别为
`e3027671d02d876c9f4b38b9d86395d45e26c0f2b344eb0646086be31869cd5d`、
`63be10ee25bb73c87861c18cc92355938fd7abc096c33852bf5f904d4db532a2`、
`bfa8eeb81da5165414a882f77f3333268847f217f858925a40597d720548e6fe`，runtime build 为
`agomtui-runtime-0.2.0+7b2efaff4f9a`。新 merge commit 自身的 Architecture、Security、
Consistency 与 CI Fast Feedback 也全部通过；Python version consistency、active registry 与 Web→TUI
migration inventory 均为绿色。

生产只读 verifier 仍识别到 `45d7616d3c38a86853104f93dbd3f13bd9a48838` / release
`20260826135953` / image
`sha256:c481bb88ac6547165bdebcd34573a6f0d69b042c93ce37136b8ea3b160a1ce66`，所以新 source 尚未
形成 candidate version、release ID 或 OCI identity。TLS、web、Django/migration/schema、TUI registry、
Qlib、Celery 均通过；公网 health/ready/audit=`200`，decision-ready=`503 blocked`。当前 readiness
继续 `DENY`：旧 cutover evidence 与新 source 不一致，108 项角色/任务 UAT、101 项 telemetry、
rollback、registry backup 和双签均未绑定。结构化 preflight 为
[`release-candidate-preflight-2026-08-29-09269c14.json`](../deployment/release-candidate-preflight-2026-08-29-09269c14.json)，
SHA-256=`466b06878229fdead920ad5cf31de5a09bcd18d79cb5a1321271fa432b095ff3`。

本 checkpoint 没有部署、重启、迁移、备份创建、生产写入、候选生产重绑、UAT 写回执、观察窗口、
cleanup、负载、fault injection 或 rollback。TUI-01 仍为 `awaiting_production`；下一步只能在精确授权后
对 `09269c14…` 做保留 PostgreSQL/Redis 的受控 code-only deployment，完成 image build、release/OCI
identity 与 post-deploy verifier 后，才能开始正式 candidate binding、角色 UAT 与第 0 天观察。

### 2026-08-29 当前候选部署复核（`09269c14` canonical rebind）

在精确授权下，部署前先创建并完整下载 PostgreSQL custom-format backup
`/opt/agomtradepro/backups/database/postgres-20260829T083336Z.dump`；远端 `pg_restore --list`、
SFTP 大小和本地 SHA-256 均通过，`146273315` bytes，SHA-256 为
`a5c77b8c6af13c5f61a3ca7e3fa9437b0bf23b03b049eb758abaf8ef94e2b30a`，没有执行 retention prune。
随后从 detached clean worktree 的
`09269c14db1024584913081db49919085f34d008` 执行 code-only source-upload `upgrade`，保留
PostgreSQL/Redis volumes、启用 Celery、禁用 SQLite 覆盖/Docker wipe/decision repair；部署为
release `20260829163806`、image
`sha256:08650701deaa8286c5818a9ed1ba15d96f740fcc646d38e56d0a979c413884da`。

完整 immutable binding 为 `web-to-tui-candidate-binding.v1`：candidate version
`20260829163806`、candidate commit `09269c14db1024584913081db49919085f34d008`、matrix SHA
`e3027671d02d876c9f4b38b9d86395d45e26c0f2b344eb0646086be31869cd5d`、graph SHA
`63be10ee25bb73c87861c18cc92355938fd7abc096c33852bf5f904d4db532a2`、schema
`tui-metadata.v3`、runtime version `0.2.0`、runtime build
`agomtui-runtime-0.2.0+7b2efaff4f9a`、runtime manifest SHA
`bfa8eeb81da5165414a882f77f3333268847f217f858925a40597d720548e6fe`。

部署事务应用 `audit.0013_systemauditdeliveryreceipt`，canonical schema check 通过，TUI registry
`30` 以 backend version `20260829163806` 发布且 active source hash 匹配。独立 verifier 绑定精确
commit，Caddy/TLS、health、容器、Django deploy check、migrations、canonical schema、TUI registry、
`pyqlib=0.9.7`/Python 3.11、release/OCI、backup、resources、Celery worker/beat/ping 全部通过，
未触发自动 rollback。结构化 deployment acceptance 为
[`release-candidate-deployment-2026-08-29-09269c14.json`](../deployment/release-candidate-deployment-2026-08-29-09269c14.json)，
SHA-256=`8e7646b373812739d621bc2afdac5a9ed648936d9e48d07f1618f2e18d7108d6`；M5 deployment preflight 为
[`web-to-tui-deployment-preflight-20260829163806.json`](../deployment/web-to-tui-deployment-preflight-20260829163806.json)，
SHA-256=`c28f3ebcaeeb51afa407596e6b587fb1a446636934ec62bf3c3d3c73036380d0`。

`web_to_tui_cutover_evidence.v1.json` 已只重绑 candidate commit/version、matrix/graph/runtime 和
deployment preflight；旧候选的 UAT、cleanup、defect、telemetry、rollback、registry backup 与审批
均保持空值，未继承历史通过项。公网 health/ready/audit 为 `200`，ready 的 decision-data 已为 `ok`；
但 decision-ready 仍为 `503 blocked`、`must_not_use_for_decision=true`，M5 readiness 继续 `DENY`。
TUI-01 仍为 `awaiting_production`；下一门是对这一精确候选取得 role UAT 与生产 write receipt 授权，
通过后才可启动 closing 14-day observation。未执行 load/chaos、registry restore、live rollback 或代签。

### 2026-08-29 release `20260829163806` 生产角色浏览器 UAT checkpoint

在精确授权下，先复核生产 `current`、容器 image 与 OCI revision，均继续绑定
`09269c14db1024584913081db49919085f34d008` / release `20260829163806` /
`sha256:08650701deaa8286c5818a9ed1ba15d96f740fcc646d38e56d0a979c413884da`，未发现候选漂移。
三个现有 UAT 角色账户均存在且启用；普通角色名下的账户 `626/627` 可用于参数化读取。固定套件的
route-page 解析测试通过，覆盖矩阵筛选出的 `108/108` 路由；最小权限动态 direct-read、operator/regular
边界与 `9/9` 参数化读取测试也通过。初始只读批次为 `6 passed / 2 failed`，有界重跑确认三个视口均
通过，桌面账户网格首次失败属于读取时延；但账户创建/补参/取消链路连续两次稳定失败：F9 面板内
目标表单存在，精确“创建”按钮仍无法在 30 秒内变为可点击，且两次均未产生生产写入。

普通 UAT 用户的策略 create/detail/update 已形成数据库写回执：`StrategyModel#8` 的版本为 `2`、描述
与更新值一致；浏览器在更新确认后仍停留“读取数据”超过固定 5 秒断言，因此 fixed test 失败。随后
仅按本次 run 的精确名称、owner 与主键删除 1 条，复核剩余为 0。个人 AI provider 生命周期 fixed
test 通过；`AIProviderConfig#16` 读回为 user scope、owner user `6`、`is_active=false`、更新描述一致，
未记录密钥内容，随后精确删除 1 条并复核剩余为 0。

结构化 checkpoint 为
[`web_to_tui_production_uat_checkpoint_20260829163806.v1.json`](../../config/tui/migration/evidence/web_to_tui_production_uat_checkpoint_20260829163806.v1.json)，
SHA-256=`970193d031be43c7d33934007a9a3389546ba95f3df670775c6c50c51fcd28ab`。报告保留四份 JUnit 的
hash、两张失败截图的 hash、候选/角色预检、写后 readback 与 exact cleanup receipt。未运行会激活
RSS/关键词、修改共享 quota、创建 pending approval proposal、触发 factor/backtest/provider 或外部
AI/Terminal Agent 的批次；未启用 queued runtime，未扩大流量、做 load/fault、maintenance 或 live
rollback，也未代替 role owner 判断业务结果。

因此当前证据是 material checkpoint，不是 canonical UAT pass：
`web_to_tui_cutover_evidence.v1.json` 的 `uat` 仍保持空，M5 readiness 保持 `DENY`，TUI-01 继续
`awaiting_production`。下一门是先修复并重新发布同候选族的账户 action 可达性与写后 loading
收敛缺陷，再以不会修改 authority/approval、不会触发外部/queued/load 的生产安全 suite 重跑；完整
recorder 无 failure/error/skip 且真实 role owner 确认前，不得晋级 TUI-01 或启动 14 日窗口。

### 2026-08-29 production-safe recorder 与 corrective repository exit

TUX-05 corrective 已将 fixed production-safe UAT 定义为独立 recorder profile，而不是对原 `15`
项 full/external-AI suite 做 skip。该 profile 精确选择 `10` 个参数化后 case：账户缺参/确认取消、
regular/operator/admin 边界、三个 viewport、矩阵 `108/108` route-page、最小权限 direct reads、
`9/9` 参数化 reads，以及普通用户自有 strategy/personal-provider 的 create/update/readback/confirmed
delete 生命周期。两条 controlled receipt 必须共享非空 run ID，并包含 entity type、PK、name、actor、
owner、confirmation、动作序列、写后 readback、60 秒 settlement SLO、exact cleanup 和
`residual_count=0`；任何敏感 key、缺失实体、重复/跨 run receipt 或 cleanup 残留都会使 recorder
fail closed。full profile 继续要求外部 AI，但显式清除 production-safe receipt sink，二者证据不能混写。

本地隔离 Chromium 最终 `10/10`、`0 skipped`、`162.75s`，两实体 create/update 分别在
`322/274ms` 与 `432/155ms` 收敛并 cleanup 为 0。首轮 `9/10` 不是被忽略：`research.signals`
显式 deep-link 与被动 dashboard reads 竞争既有 6-slot action gate，`signal.list` 收到 `503`；修复让
可直接运行的非沉浸式 dashboard deep-link 优先，不增加并发、不重试请求、不延长超时。账户 F9
action 可达与 confirmed mutation “操作完成”状态均有 Workbench 和真实浏览器回归；strategy/provider
delete 另补未渲染 template response adapter 回归。规范化本地证据为
[`tux05-corrective-repository-closure-evidence-2026-08-29.json`](../testing/tux05-corrective-repository-closure-evidence-2026-08-29.json)。

该结果只关闭 TUX-05 repository gate，不填充 canonical `uat`。TUI-01 下一门仍是 corrective commit
通过 CI/review/merge，从新 `main` 的独立 clean worktree 冻结并部署新候选，再由 candidate-bound
production-safe recorder 对真实生产角色重跑；外部 AI、queued runtime、authority/approval、active
RSS/shared quota、load/fault、maintenance/live rollback 继续不在本授权包内，真实 role owner 的业务
确认也不能由 recorder 代签。

### 2026-08-29 production read settlement corrective

新候选 `003cb58c258086012e1238c513a4b1c68b3ecf98` / release `20260829220843` 已按授权从独立 clean worktree 部署，migration graph 无待应用项且 `audit.0013` 保持 applied。candidate-bound production-safe recorder 执行 `10` 项、通过 `9` 项、跳过 `0` 项；唯一失败的 operator queue 在 Playwright 默认 `5s` 可见性断言刚超时后完成并渲染，失败截图可见命名 grid、`7` 行数据与“读取完成”。recorder 因此没有写 canonical UAT。

corrective 只为该生产读取角色断言使用既有 `60s` settlement ceiling；operator grid/完成态、regular 不可用提示和 grid=0 仍必须全部成立。修正后隔离本地 fixed profile 为 `10/10`，继续覆盖 `108/108` route-page、regular/operator/admin、参数化 reads、strategy/provider 两条同 run receipt 与 cleanup residual=`0`。没有增加 retry/concurrency，也没有改变 confirmed write 的 `60s` SLO。CI/review/merge、从新 main clean worktree 重部署及完整生产 recorder 通过前，TUI-01 保持 `awaiting_production`、canonical UAT 为空、M5 保持 `DENY`。

### 2026-08-30 当前候选部署复核（corrective production UAT closure）

PR #13 已通过 CI 与 Sol/Luna review 并合并为 `c826f741edc0f12f5e29fa5b0441b34a89f6dac5`。从该提交的独立 clean worktree 创建并双端校验 PostgreSQL backup `postgres-20260829T153008Z.dump`（`146649635` bytes，SHA-256 `40448647f6818b49f1a664fc601f0e9c8a2073c026a85b25875a451de80fe825`，未 prune），随后部署 release `20260829233430` / image `sha256:7fbf039a59294ba959bd5a0f31731a30d856df71e7c05c3aefeddd876769df14`。migration 0013 保持 applied、无待迁移或缺表，web/Celery/PostgreSQL/Redis 与公开 health/readiness 均通过，自动 rollback 未触发。

当前 immutable binding 为 `web-to-tui-candidate-binding.v1`：candidate version `20260829233430`、candidate commit `c826f741edc0f12f5e29fa5b0441b34a89f6dac5`、matrix SHA `e3027671d02d876c9f4b38b9d86395d45e26c0f2b344eb0646086be31869cd5d`、graph SHA `63be10ee25bb73c87861c18cc92355938fd7abc096c33852bf5f904d4db532a2`、schema `tui-metadata.v3`、runtime version `0.2.0`、runtime build `agomtui-runtime-0.2.0+1aa1996d160f`、runtime manifest SHA `8824e67064f5a572d346507cc3d7ab484282e45dd6e8a7b05f2682c7c1bad3a4`。

candidate-bound canonical production-safe recorder 以 run `tux05-production-20260829233430` 得到 `10/10`、`0 failed`、`0 skipped`、`108/108` routes；regular/operator/admin、参数化 reads 和三个 viewport 均通过。普通 UAT 用户自有 strategy/provider 各形成一条 create/update/readback/confirmed-delete receipt，四个 settlement 均低于 60 秒，两个 cleanup 均 `deleted=true`、`residual_count=0`。canonical UAT SHA-256 为 `90736bcb33268095218cd9467bb984fb8478db3d62044c5de1fd89736ae573c4`。

因此 TUX-05 corrective repository/production exit 完成，repository focus 回到 `null`；但 TUI-01 不晋级。`2026-08-30` readiness 仍为 `DENY`：14 日稳定窗口截至 `2026-09-12`，并且 108 路由 cleanup/rollback 矩阵、缺陷快照、101-task production telemetry、rollback drill、production registry backup、owner/reviewer attestations 与真实 role-owner 业务确认仍缺。external AI、queued runtime、authority/approval、流量扩大、load/fault、maintenance/live rollback 均未执行。

### 2026-08-30 最终候选 observation source preflight

本节精确绑定最终候选 commit `36b72d2fc01604afdb15d236a1e91d082fb62a5b`、release
`20260830071422` 与 image
`sha256:09f6491440a4bc16934ac5544c793a0b5b9d22c8ec6f8ab35d61693b0121c94b`；后续审核、
retained-source 证明、候选 re-attestation 和观察窗口均不得跨候选继承。

结构化 preflight
[`tui-m5-observation-source-preflight-2026-08-30-36b72d2f.json`](../deployment/tui-m5-observation-source-preflight-2026-08-30-36b72d2f.json)
（SHA-256=`b8b22c64f260d5a2d43de78a2ee30d30637ea741203d3173b1b28fe6fc660bcf`）确认：公网 exporter
可读且本次返回 `203` 条 TUI migration series，catalog 的 `101` 个 Classic-comparable task key
均有对应 TUI series；但是本次没有任何 Classic surface series。exporter 是当前进程累计值，不是
保留的 Prometheus query-range source。

当前 VPS 的 `8` 个运行容器、监听端口和进程中均未发现 Prometheus-compatible store，VPS compose
也未定义该 service；外部 query origin 与从 `2026-08-29` 开始的 retention 证明均未提供。正式
telemetry builder 又要求 exact `2026-08-29..2026-09-12` window、六条固定 PromQL、精确 101 task
coverage，且 `collected_at` 不得早于 `2026-09-12`；defect builder 对完整窗口有相同结束日约束。

进一步检查 web/host 环境变量名、Docker volumes、systemd、常见 monitoring agents、Caddy route 和
标准 Prometheus 路径也全部为空；它关闭了“VPS 上已有未登记本地 source”的可能性，但不能否定外部
SaaS 无 agent 直抓公网 exporter，后者仍须 operations 提供可验证入口与 retention。

因此当前不能生成 final telemetry/defect snapshot，也不能假设 9 月 12 日还能从瞬时 exporter 重建
14 天历史。下一门为 operations 提供现有外部 query origin、retention 证明和受审 tracker snapshot；
若没有，从首个获批 collector 留存样本重新计时。该结论保持 `stable_version_window`、
`blocking_defects`、`production_telemetry`、formal registry attestation 与 approvals 五门为 FAIL，
不把 exporter 可达性解释为 readiness。

同轮聚焦回归发现 `test_checked_in_evidence_is_explicitly_denied` 仍断言旧候选的空 UAT/cleanup/
rollback；该测试已改为核对当前真实 `5/10` gate 投影，同时继续严格断言最终 decision=`DENY` 和其余
五门失败。gate 计算实现、阈值和 checked-in evidence 均未放宽；三组聚焦测试最终 `48 passed`。

条件化 remediation 授权包
[`tui-m5-monitoring-remediation-preflight-2026-08-30-36b72d2f.json`](../deployment/tui-m5-monitoring-remediation-preflight-2026-08-30-36b72d2f.json)
（SHA-256=`c386ea4552df2af991c2ae824acbef79ccd7dc337bc139994145babdc89c1b76`）进一步固定了实现边界。
现有 Prometheus 配置的 `localhost` targets 与缺少 Prometheus/Alertmanager/exporter service 的 VPS
compose 不匹配，不能未经 repository review 直接挂载上线。若无既有外部 source，必须先显式分配
一个 bounded repository focus，完成 pinned image、volume/retention、network target、health/access、
rules/query 和 rollback 合同，再逐项授权生产部署。

collector 首个 retained sample 建立后，还需 fresh candidate deployment preflight；canonical observation
starter 以该 verification date 建立新 14 日窗口并清空不可继承证据。当前 package 的 owner、reviewer、
image digest、storage、retention、query access 和窗口重置接受值全部保持空值/`not_authorized`，不会把
preflight 当成实施批准。

### 2026-08-30 TUI operations 审核交接

TUI retained-source 与 monitoring-remediation 决策已经进入统一审核说明
[closure-review-team-handoff-2026-08-30-36b72d2f.md](../deployment/closure-review-team-handoff-2026-08-30-36b72d2f.md)，
SHA-256=`4ba887ba3d7a81cf6c6e1349f08a082968626c9d647c55644b44852a4771dc36`；机器回传模板为
[tui-m5-operations-review-return-template-2026-08-30-36b72d2f.json](../deployment/tui-m5-operations-review-return-template-2026-08-30-36b72d2f.json)，
SHA-256=`1cd479735fc9888e7e08d9f5badeb5d5c9ce216ededa4565bd31610666e93fd5`。

operations 必须在“提供既有 external retained source”与“授权 bounded repository + production
monitoring remediation”中二选一。前者必须证明从原窗口起点连续 retention、六条 PromQL、时钟同步和
无秘密导出；后者必须给出 pinned image digest、>14 日 retention、有界 storage/volume、受控 query
access、Alertmanager policy，并接受候选 re-attestation 与 canonical 14 日窗口重置。真实 role-owner
只能确认已经发生的 UAT，不能预签最终 cutover。模板本身不是批准；当前 focus、TUI-01/02 状态和
`5/10 DENY` 均不变。

### 2026-08-30 single-owner intake 与 TUI-03 repository exit

个人项目唯一真人所有者授权
[`personal-project-single-owner-authorization-2026-08-30-36b72d2f.json`](../deployment/personal-project-single-owner-authorization-2026-08-30-36b72d2f.json)
（SHA-256=`d9c6e9f4128603d0f2208e107a430db93332ec2db2e523886d5248bb63005fd7`）取消了第二名自然人和职责分离要求。
同一 owner 对既有 run `tui01-36b72d2f-20260830-01` 的 UAT 业务结果作出范围内 APPROVE；候选绑定、
`10/10`、`108/108`、两条 receipt、零残留、六类 cleanup 与隔离 rollback 已有机器证据，因此
`TUI-01=completed`。这项决定不预签 retained telemetry、defect 或最终 cutover。

不存在可证明的外部留存源后，`TUI-03` 作为唯一 repository unit 完成：Prometheus 固定为
`prom/prometheus:v3.5.0@sha256:63805ebb8d2b3920190daf1cb14a60871b16fd38bed42b857a3182bc621f4996`，
保留 `21d` 且上限 `4GB`，使用 `prometheus_data`，只抓取 `web:8000/metrics/`，加载现有 M5 rules，
自身不发布 host port；Caddy 只放行五类 read query API，并由 host-only bcrypt 文件认证。VPS bundle
和 local runtime bundle 投影同步。结构化证据
[`tui03-retained-monitoring-repository-closure-evidence-2026-08-30.json`](../testing/tui03-retained-monitoring-repository-closure-evidence-2026-08-30.json)
SHA-256=`8fda79136ae1a3a70afd22ce4b1134f69f5d4af44bd484786ea4fd2f9c9891a7`；聚焦回归 `48 passed`，
compose、promtool、Caddy、alerts、PowerShell、mypy 和 registry 均通过。

`TUI-03=completed`、repository focus 回到 `null`，`TUI-02=awaiting_production`。本 checkpoint 未部署、
未创建生产 volume/credential 或 retained sample，也没有重置/回填窗口；下一门是 clean successor
部署与 post-deploy target/retention/query 验证，再由 canonical starter 从首个可证明样本重新起算 14 日。

### 2026-08-30 23:38 当前候选部署复核：successor 与 TUI-02 Day 0

唯一真人所有者的后续授权已固化为
[`personal-project-single-owner-authorization-2026-08-30-80ea002b.json`](../deployment/personal-project-single-owner-authorization-2026-08-30-80ea002b.json)
（SHA-256=`f675c44647764c93292f223fc94a0f7ac3d5c89a1ad651d2d12a6ba1918300e1`），并取代旧候选授权。
同一 owner 可承担 owner、operations、root 与 reviewer 角色，不再要求第二名自然人；最终两个 role-bound
attestation 仍只能在完整技术快照形成后签发。

commit `80ea002bf910110621022a70e4f1ec5c1b704a56` 已以 source-upload `upgrade` 部署为 release
`20260830215638` / image
`sha256:54cb9646912c494d64c1eb664b6a3a8af772c36f5388d8456d669285398c39fc`，保留 PostgreSQL、Redis
和所有 volumes，自动失败回滚已 armed 且未触发。Prometheus `up=1`、`21d/4GB`、17 条 rules、0 unhealthy，
未认证 query=`401`、host-only credential 认证 query=`200`。canonical starter 据此建立
`2026-08-30..2026-09-13` 观察窗口，没有继承旧候选或补造历史。

完整 immutable binding 为 `web-to-tui-candidate-binding.v1`：candidate version `20260830215638`、
candidate commit `80ea002bf910110621022a70e4f1ec5c1b704a56`、matrix SHA
`e3027671d02d876c9f4b38b9d86395d45e26c0f2b344eb0646086be31869cd5d`、graph SHA
`63be10ee25bb73c87861c18cc92355938fd7abc096c33852bf5f904d4db532a2`、schema `tui-metadata.v3`、
runtime version `0.2.0`、runtime build `agomtui-runtime-0.2.0+1aa1996d160f`、runtime manifest SHA
`8824e67064f5a572d346507cc3d7ab484282e45dd6e8a7b05f2682c7c1bad3a4`。

正确生产域名为 `demo.agomtrade.pro`。首次 UAT 误用了 `demo.agom.trade.pro`，在 reachability 阶段即停止，
没有写 canonical UAT；恢复正式 Caddy 配置后，正确域名 TLS 验证通过且 health 连续三次为 `200`。
正式 run `tui02-80ea002b-20260830-01` 随后通过 `10/10`、`108/108`、regular/operator/admin、两条
strategy/provider receipt 和 exact cleanup residual=`0`。candidate cleanup 为 `8/8`、六类 scope
均 `108/108`，隔离 rollback PASS。误为未选中 fixture case 创建的六项精确测试记录已经按 PK/name/run
逐项删除并再次查询为全零。

生产 registry generation `30` 已写入 root-only bundle
`/opt/agomtradepro/backups/tui-registry/tui-registry-release-20260830215638-80ea002b-20260830T153412Z.json`，
SHA-256=`c3cc3a05dc509afad99262749d96f2c5c7b715754dd8c8b92ff69a1c86d48b8d`、mode=`0600`；sidecar
核验和 restore dry-run 均通过。它是 Day 0 recovery point，不冒充必须在观察期结束后导出的正式 attestation。

结构化汇总为
[`tui02-production-day0-checkpoint-2026-08-30-80ea002b.json`](../deployment/tui02-production-day0-checkpoint-2026-08-30-80ea002b.json)，
SHA-256=`1cff7915f03e3c12618ada5e4b02fd3d81741db16c121cd3aef362192a9e4d85`。当前 readiness 真实为
`5/10 DENY`：source、dependency、UAT、cleanup、rollback 已通过；稳定窗口、structured defects、
101-task telemetry、post-window registry attestation 与 final role-bound attestations待完成。`TUI-02=active`，
repository focus 仍为 `null`；2026-09-13 前只维持真实采样、候选漂移与健康停止线，不重复造最终快照。

### 2026-08-31 retained sample 精确时间门

生产只读 checkpoint
[`tui02-production-observation-checkpoint-2026-08-31-80ea002b.json`](../deployment/tui02-production-observation-checkpoint-2026-08-31-80ea002b.json)
（SHA-256=`db055a18e86d3b0da10a8612e92b75bf4ef5c2860d7ca34b21166f1efa3b0d2a`）确认候选未漂移、
Prometheus 未重启、persistent volume/`3w or 4GiB`/target/17 rules/authenticated query 全部健康；首个
retained raw sample 为 `2026-08-30T15:09:35.034000Z`。因此 exact eligible instant 是
`2026-09-13T15:09:35.034000Z`，不是 9 月 13 日零点。

repository guard 已改为 hash-bound retained binding，并把 telemetry/defect snapshot 升级到 v2：
`collected_at`、`queried_at` 必须是 UTC timestamp，readiness 会重放 snapshot builder、复核 checkpoint
SHA，并在 exact instant 前保持 stable/defect/telemetry 三门失败。当前仍为 `5/10 DENY`，没有因此
授权 cleanup、final backup、review 或 attestations。

### 2026-09-02 当前候选部署复核（`aa7127ff4` / `20260901232812`）

当前生产候选为 commit
`aa7127ff4d9f71555b0d0486314da5518bd2ac20`、release `20260901232812`，OCI image
`sha256:55d2b1d8dd7078acc42aef72f0fa33e57035d30e5c2727b574dfd43aafd9519c`。部署 preflight
[`web-to-tui-deployment-preflight-20260901232812.json`](../deployment/web-to-tui-deployment-preflight-20260901232812.json)
的 SHA-256 为 `e5b613548811f89cb06659eed976786a5fb7e97593626ce2529665ff2b6a8f89`，候选 commit、
release、OCI revision 一致；本次章节只引用已提交的只读/部署工件，不代表本轮重新部署。

immutable binding 为 `web-to-tui-candidate-binding.v1`：candidate version `20260901232812`、
candidate commit `aa7127ff4d9f71555b0d0486314da5518bd2ac20`、matrix SHA
`e3027671d02d876c9f4b38b9d86395d45e26c0f2b344eb0646086be31869cd5d`、graph SHA
`63be10ee25bb73c87861c18cc92355938fd7abc096c33852bf5f904d4db532a2`、schema `tui-metadata.v3`、
runtime version `0.2.0`、runtime build `agomtui-runtime-0.2.0+1aa1996d160f`、runtime manifest SHA
`8824e67064f5a572d346507cc3d7ab484282e45dd6e8a7b05f2682c7c1bad3a4`。

此前绑定的 retained source 为
[`tui02-production-observation-checkpoint-2026-09-02-aa7127ff.json`](../deployment/tui02-production-observation-checkpoint-2026-09-02-aa7127ff.json)，
SHA-256=`96d7031e0da8ba6a6d037d800fd8cd4add782b9f3369e93e0e6c645a051052c3`；它的首个真实样本
`2026-09-01T16:56:29.796000Z` 与 eligible `2026-09-15T16:56:29.796000Z` 已因后续 web
restart 作废，保留为历史证据而不再绑定。新的 reset artifact
[`tui02-production-observation-reset-2026-09-02-aa7127ff.json`](../deployment/tui02-production-observation-reset-2026-09-02-aa7127ff.json)
SHA-256=`78cc512926193b5fad05db1e34f053a852816700817e4cd357d5999c05dab004` 绑定同一 candidate，
记录 web start=`2026-09-02T15:38:21.178433901Z`、web/prometheus healthy、public health/ready=`200`
与 decision-ready=`503` fail-closed；cutover evidence 已清空 retained projection，等待重启后首个真实样本。

本地 retained checkpoint validator 已按 Git canonical LF 字节校验 JSON，Windows CRLF checkout 不再
把该有效 checkpoint 误判为缺失；这只是证据读取一致性修复，不改变 checkpoint 内容、候选绑定或生产门禁。

本候选 readiness 仍为 `5/10 DENY`：source consistency、execution dependency、route UAT、
cleanup readiness、isolated rollback 已有证据；稳定窗口因 reset 后尚无 retained source，
structured blocking-defect、101-task telemetry、post-window registry backup/review 与 sole-owner
role-bound attestations 尚未满足。reset 后只执行了上述一次受控 web-only restart 和只读探针，未部署
新镜像、未写库/改配置、未执行 load/chaos、live rollback 或决策门激活；`production_claim=false`、
`production_ready=false`、`runtime_enablement=not_authorized` 继续有效。新 retained sample 形成后，
其 exact eligible instant 将重新成为后续 v2 快照的最早时间门。
