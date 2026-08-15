# Web 界面 → TUI 整体迁移计划（M0-M5）

> **文档日期**: 2026-07-25
> **最后修订**: 2026-08-14
> **状态**: 实施中；M0、M0-D、M1、M2、M3 与 M4 仓库实现已完成；M5 遥测、同任务错误率与机器 cutover gate 已落地，但历史 108/108 UAT、cleanup 和本地 rollback 未绑定当前 candidate graph/runtime snapshot，已于 2026-08-13 改判未通过；当日生产 preflight 虽确认 release 已更新且 health/ready 正常，但 OCI revision=`unknown` 且无 source manifest，仍无候选部署证明；14 日窗口、最终候选 UAT/回滚、生产样本、缺陷窗口、生产 registry 备份与审批均未满足，当前禁止清理 Classic
> **适用对象**: 开发负责人 / 模块维护人 / AI 代理
> **主范围**: 以 M0 的 195 个 Django 模板为初始基线，持续盘点 `core/templates/` 与 `apps/*/templates/`，并把适合迁移的用户任务迁入 TUI 工作台（`/tui/`）；迁移期新增的共用兼容组件也必须进入同一台账
> **后端边界**: 默认保持业务语义不变；为补齐 TUI API 契约所需的 owner app 纵向切片允许纳入，但必须单独估算、提交和验收，不得把业务逻辑堆入 `terminal`
> **目标**: 普通用户与日常运维的主任务在 TUI 内完成；web 模板收敛为一份显式且可机器核对的保留清单；迁移全程可观测、可回滚、每批独立收口

## 2026-08-15 计划归属收口

旧 `admin-settings`、`alpha-homepage` 与 `streamlit-dashboard` 计划已归档，不再形成平行实现线。其余工作统一归本计划的 `TUI-01/TUI-02`：

- 设置中心/管理控制台的保留页清理、角色化浏览器 UAT、候选绑定和 14 日观察；
- Alpha 首页/研究信号任务的 TUI 迁移与角色 affordance；
- Streamlit 仅作为兼容 sidecar 保留，不再推进独立 reverse-proxy/SSO/cutover。

本节只记录产品迁移归属；真实 owner/receipt、PIT/OOS 和执行授权仍由 Strategy/Evidence 门禁负责，M5 生产候选 gate 仍未解除。

## 1. 背景与动机

1. 现有 web 界面为 195 个 Django 模板、约 7.6 万行 HTML，其中 **114 个模板（58%）含无 `src` 的内联 `<script>`**。这部分逻辑既不被 Python 测试覆盖，也不在任何前端工程内，是当前最大的 UI 测试盲区。
2. TUI 体系已成熟：12 个 published screen + 6 个 runtime source（alias 归并后为 4 个 canonical retained runtime screen）、402 个 action、3 个分组、8 步每日工作流，且 screen 全部以 metadata（JSON）定义，受 schema v3 + 域校验器 + 静态契约 + Playwright 几何护栏的多层机器检查。把 UI 从模板换成 metadata，等于把"靠纪律维持的统一"换成"靠机器强制的统一"。
3. 四层架构红利：多数迁移只替换 Interface 层的渲染方式并复用既有 `/api/`；发现 API 缺口时，在数据所属 app 内按四层补齐纵向切片，保持金融规则和业务语义不变。
4. AGENTS.md 的 TUI 面向用户设计约束（`primary_task`、P0 首屏、`copyable_secret` 等）决定了**迁移不是逐页翻译，而是按用户任务重组信息架构**。

## 2. 现状基线（2026-07-25 快照）

### 2.1 模板分布

| 位置 | 数量 | 占比 |
|---|---:|---:|
| `core/templates/` | 135 | 69% |
| `apps/*/templates/` | 60 | 31% |
| 合计 | 195 | 100% |

### 2.2 M0 定档口径（互斥）

| 去向 | 基线数量 | 说明 |
|---|---:|---|
| A：迁入 TUI | 130 | 非图表重的 route page、layout 与 partial；进入 M2/M3 backlog |
| B：TUI + 图表补齐 | 17 | 检测到图表/Canvas 运行契约；进入 M4 backlog |
| C：明确保留 web | 41 | §8 的外部页、初始化页、Admin、基座、错误页、TUI shell 与 docs 页 |
| D：删除 | 7 | 已由 M0-D 删除并在矩阵保留原始 hash、loader/route 证据与回滚记录位 |
| 初始合计 | 195 | A/B/C/D 互斥；M0-D 后物理模板数为 188 |

当前矩阵为 **196 行**（A=131、B=17、C=41、D=7）：在 M0 的 195 行初始基线上，迁移期新增了 1 个共用兼容提示 partial，并已纳入冻结台账；扣除 7 个已删 D 档后，当前物理模板数为 189。矩阵记录 117 个历史 route page，其中 7 个 D 档已删除；剩余 110 个 active route page 中，108 个 A/B 页面已关联 Django resolver、目标 TUI screen/action 和主任务，另 2 个认证前登录/注册页按 C 档保留。初始 `api_gap=review_required` 仅表示需核对 owner app JSON 契约，不等同于已经确认缺少 API；其后续关闭状态以矩阵和各 wave 证据为准。

### 2.3 模板角色

M0 初始基线的 195 个文件不等于 195 个可独立访问的页面。M0 必须先为每个模板标记角色，后续新增模板沿用同一规则：

| `template_role` | 定义 | 是否必须有目标 screen |
|---|---|---|
| `route_page` | 由 URL/view 直接渲染的用户页面 | A/B 档必须有 |
| `layout` | `base.html` 等继承基座 | 否；跟随消费者或进入 C 档 |
| `partial_component` | include、fragment、组件或 tabs | 否；记录消费者与删除批次 |
| `admin` | Django Admin 定制模板 | 否；默认 C 档 |
| `shell` | TUI/Terminal 宿主模板 | 否；C 档 |
| `error` | 404/500 等错误页 | 否；C 档 |
| `external` | 分享、观察者、安装引导等外部/偶发流程 | 通常 C 档 |

### 2.4 TUI 能力缺口

以下是 2026-07-25 启动快照中的前置缺口，用于解释 M1/M4 的实施顺序；图表样板和 17 个 B 类 route template 的仓库实现现已完成，最终放行仍受 M5 的 live-server UAT 与生产门禁约束。

- schema v3 已声明 `chart` / `kpi_trend` / `table_chart` / `image` / `custom`（扩展 renderer 注册机制在 `frontend/agomtui-runtime/src/extensions.js`），但 **published graph 中没有任何生产级 chart 使用样例**——27 个 dashboard panel 全部为 detail / datagrid / regime_quadrant。
- 图表能力是 B 类页面（~25 个模板）迁移的前置条件，必须先建立生产样例（见 M1）。
- `GET /tui/` shell 页脚当前保留 "Classic 界面" 链接，作为迁移期兼容出口。

#### 2.4.1 TUI 可操作性缺口（P0 优先整改）

TUI 不能以“能读取列表/详情”作为主任务完成。凡是用户任务本身包含创建、编辑、删除、审批、绑定、切换或触发，TUI 必须提供用户可见、可填写、可提交的真实入口；仅把 `POST/PATCH/DELETE` action 放进后台元数据、让用户手填对象 ID，或只提供查看按钮，都不算任务闭环。

本项作为跨 M2/M3 的独立 `R0` 优先整改，不等待 M5 cutover：

- 第一批固定检查 `execution.accounts`、`ai-ops.providers`、`policy.workbench`、`research.signals`；优先复用已经存在的 owner-app API，不凭空新增 terminal 业务逻辑。
- 每个可变更列表必须在 IA registry 与 runtime injection 同时发布 `row_actions`；创建类操作必须有显式 create affordance（可填写表单的 dashboard prompt 或等价入口），编辑/删除/审批/绑定必须把行字段映射到 action 参数，禁止只展示泛化 action 菜单。
- 每个 mutation action 必须保留后端的权限、对象归属、确认/重新认证、审计语义，并声明写后 receipt/result 与受影响 panel refresh；前端隐藏不是权限边界。
- `config/tui/ia/tui_information_architecture.v1.json`、runtime injection、published graph/registry 与浏览器契约测试必须保持一致；静态 graph 中不存在而 runtime 才注入的写入口，必须列入 deferred/promotion 证据，不能冒充已完成。
- R0 的验收是“用户能完成主任务”，至少覆盖普通用户、owner/object 与 staff/admin 角色，以及空态、参数填写、确认、写后刷新/回执和错误恢复；只验证 action 存在或 GET smoke 不通过。

2026-08-14 本地 R0 复核已补上运行时通用门禁：归一化 runtime graph 共 887 个 action，其中 277 个为 write/admin；所有写入 action 都必须使用非 GET 方法并声明 `create/update/delete/toggle/approve/reject/execute` effect，缺少可见字段的动作只能来自显式登记的 8 个整批执行/默认导入命令；4 个 `POST/read` 预览/测试命令也必须显式登记且保留输入字段。`tests/unit/test_tui_actionability_contract.py` 为 `5 passed`，`npm run test:tui-js` 为 `33 passed`。这证明代码层不会把应填写/修改/创建的入口降级成只读卡片，但不替代最终候选上的角色化浏览器 UAT、写后回执和生产审计证据。

R1 行级编辑整改（2026-08-15）已在 Workbench 运行时完成：对 `POST/PUT/PATCH/DELETE` 且带可见字段的 `row_action`，点击后先定位并打开左侧 action form，按 `param_map` 填入行身份、按字段候选填入可用行值，用户修改并提交后才发送请求；无可见字段的审批/删除/切换/整批命令仍保持直接执行。用户治理列表新增 `identity-access.reject-user` 的拒绝原因表单与 `identity-access.set-user-role` 的角色编辑行入口，角色字段从当前行预填且允许修改。浏览器契约新增“点击编辑不立即 PATCH、修改后携带 ID+body 提交”测试，TUI JS 总计 `34 passed`；Python actionability contract 为 `9 passed`，并新增通用 runtime row-edit identity/form-context guard。剩余仍是最终候选角色化 UAT、写后回执/审计和生产证据，不把本地浏览器 harness 当作 M5 放行。

同日补齐权限 affordance 收口：`_screen_dashboard_panels` 现在以当前用户已通过权限过滤的 `visible_action_keys` 再投影 `row_actions`，普通用户不再看到无法执行的 Beta Gate、Rotation、Signal 等管理员写按钮；管理员行操作保持不变。`tests/unit/test_tui_workbench.py` 新增普通用户/管理员双向断言，定向回归 `2 passed`。该修复只收紧展示边界，不替代后端权限、角色化浏览器 UAT、写后 receipt/refresh 或 M5 生产证据。

2026-08-15 R1 direct-action 语义收口：Workbench 现在只在行操作存在可见 `body` 字段时打开表单；只有 path/query 行身份的 approve/delete/toggle/批量命令继续直接执行，避免把不可编辑的标识字段误显示为冗余表单。浏览器契约为 `22 passed`，`npm run build:tui`、`npm run check:tui` 通过；该本地语义修复仍不替代角色化浏览器 UAT、写后 receipt/refresh 或生产证据。

### 2.5 机器唯一真源

- IA registry：`config/tui/ia/tui_information_architecture.v1.json`
- 发布物：`config/tui/published/tui_operation_graph.published.json`（文件级基线）+ DB 表 `TuiMetadataRegistryORM`
- 运行时注入：`apps/terminal/infrastructure/tui_metadata_runtime_injection_*.py`
- 本计划不复制上述文件中的动态数字；screen/action 规模以真源文件为准。

### 2.6 前置依赖

- 用户面标准：`docs/development/tui-user-facing-design-standard.md`
- metadata 发布流程：`docs/development/tui-metadata-promotion-guide.md`
- Workbench 契约：`docs/development/tui-workbench.md`
- 双仓可移植性：`docs/plans/agomtui-portability-remediation-2026-07-21.md`
- IA 真源：`config/tui/ia/tui_information_architecture.v1.json`

M1/M4 如修改通用 schema、runtime 或 renderer，必须同步满足可移植性计划的双端 validator、business leakage、runtime sync 与 JS 回归门槛。AgomTradePro 产品专用逻辑只能进入 `frontend/agomtradepro-host/`；不得把业务 screen/action key 写入通用 runtime。

### 2.7 M5 判定真源与当前决策

- 映射真源：`docs/plans/web-to-tui-migration-matrix-2026-07-25.csv`。
- 切换证据真源：`config/tui/migration/web_to_tui_cutover_evidence.v1.json`；叙事证据只能解释该文件，不能覆盖机器字段。
- 唯一放行命令：`python scripts/check_web_to_tui_cutover_readiness.py --require-allow`。命令非零退出、证据缺失、字段未知或审批不完整时一律 **DENY（fail closed）**。
- 截至 2026-07-28，矩阵证据快照 SHA-256 为 `bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`，机器判定为 **DENY**：`source_consistency`、`route_task_uat`（108/108）、`route_cleanup_readiness`（六类 scope 108/108）与 `rollback_drill` 已通过；`stable_version_window`、`blocking_defects`、`production_telemetry`（0/101）、`production_registry_backup`、`cutover_approvals` 未通过。
- 2026-07-26 只作为历史上的预定观察基线；2026-07-28 只读生产 preflight 确认线上仍运行 `dev/next-development@2e399607977fea260436992952fae64565153213`，该提交不包含当前迁移矩阵，因此不能作为 M5 候选或回填观察起点。当前证据中的 `stable_version`、`candidate_commit`、`released_at`、`observation_end` 仍为空，稳定版本窗口尚未开始；最早复核日必须由真实候选部署后的机器窗口计算。
- 生产 preflight 证据见 `web-to-tui-m5-production-preflight-2026-07-28.md`。该文件只证明发布前生产健康和部署版本差异，不计入任何 cutover gate。
- 浏览器 108/108 deep-link smoke 只证明入口可解析和目标可定位，**不计入主任务 UAT**；只有按计划角色真实执行主路径并验证业务结果的用例才能计入 108 个 route page 的 UAT 分子。
- M5-B 将 A/B route 标为 `deleted` 后，该 route 仍保留在历史 UAT、逐 route 清理与 telemetry catalog 的必需集合中；删除 Classic 工件不能通过缩小分母抹掉既有证据责任。

## 3. 迁移总原则

1. **按任务重组，不按页面翻译**。每个目标 screen 必须满足 `docs/development/tui-user-facing-design-standard.md`：一个 screen 一个主任务、`user_experience` 五元组齐全、P0 首屏可见。不允许把某个 HTML 页面机械映射成同名 screen。
2. **每个模板有唯一 lifecycle 去向**。M0 产出全量迁移映射矩阵（195 个模板 → A/B/C/D 四档 + `template_role`）；只有 `route_page` 的 A/B 档必须填写目标 screen key，layout/partial 必须填写消费者和随迁/删除批次，不允许任何模板无归属。
3. **批准后冻结新 web 业务页面**。新业务能力默认只做 TUI screen。C 档保留流程、错误页、基座和 TUI shell 的必要维护不受限；确需新增 web 页面时，必须在 PR 中写明用户群、TUI 不适用原因、owner、保留期限并更新 §8，禁止借缺陷修复扩展新的 Classic 主任务。
4. **后端按 owner app 补齐**。迁移优先消费既有 `/api/` JSON 端点；端点缺失时，在数据所属 app 内按 Domain → Application → Infrastructure → Interface 的依赖方向补 Application UseCase、Repository 与 DRF 契约，单独提交和测试。**不得**在 `terminal` app 写领域逻辑，不得为 TUI 新开 HTML/HTMX 片段端点。
5. **单日一个主线**。每批迁移独立分支（`dev/feat-tui-migration-<批次>`）、独立 commit 组、独立可回滚；不得与 mypy 收口、部署修复、治理文档混在同一批次。
6. **权限按角色和对象归属控制**。普通用户可以执行本人有权操作的 `write` action；`unsafe/admin` action 必须继续执行后端授权、确认、必要的重新认证与审计。前端隐藏不是权限边界。任何依赖 mutation 的迁移任务不得以只读列表/详情替代，必须发布可见的 create/edit/delete/approve/bind 入口、对象归属字段、写后 receipt 与 affected-panel refresh；未满足者不得标记为 route parity 或 `ready_for_cutover`。
7. **兼容期双轨且有量化退出门槛**。已迁域的 web 页面在兼容期内保留，展示弃用提示并提供目标 TUI deep link。M5-A 观测可在实现完成后启动；只有连续一个稳定版本同时满足“核心任务 UAT 全过、完整窗口无 P0/P1 阻断缺陷、错误率无显著回退、旧入口访问量低于批准阈值、回滚观察期已满”后，才允许进入 M5-B 清理。
8. **旧 URL 有显式处置**。映射矩阵必须为每个 route page 指定 `redirect_to_tui`、`retain`、`remove_410` 或 `remove_404`；需要跳转时保留可安全映射的查询参数、用户上下文和目标 screen/action，不得让书签静默落到 TUI 首页。
9. **回滚单位是可验证子批**。每批记录 published graph hash、schema version、runtime build id、registry generation、代码 commit 和兼容矩阵。TUI 侧仅在旧 graph 与当前 runtime/schema 兼容时重发旧 baseline；否则同时回滚对应 runtime/schema。模板、路由和前端增量分别用独立 commit 回滚，不直接修改 DB payload。

兼容期默认退出阈值如下；如某个低频页面无法满足样本量，必须在跟踪表记录例外理由并由 owner/reviewer 双签，不得直接视为“无反馈即通过”。

| 门禁 | 默认门槛 | 证据与例外口径 |
|---|---|---|
| 稳定版本窗口 | 同一待切换版本及完整 Git commit 连续运行不少于 14 个完整自然日，且中途没有重置版本或发生需重新计时的 P0/P1 修复 | 2026-07-26 仅为历史预定基线；生产仍运行不含当前矩阵的旧提交，观察尚未开始。候选成功部署并写入机器证据后才起算，是否满窗只由机器字段判定 |
| 主任务 UAT | 108/108 个迁移 route page 按计划角色和主路径 100% 通过 | deep-link、页面渲染或 mocked execution 不计通过；参数读取、写流程和外部依赖任务必须有可复现 fixture/环境证据 |
| 逐 route 清理证据 | 108/108 个迁移 route page 的权限、空态、错误态、旧 URL 和回滚条件均完成审查 | 使用经 SHA-256 校验的独立证据文件登记精确 route 集合与六类 scope；每个 route 必须映射到本仓库可解析的回滚 commit，矩阵 owner/reviewer 和旧 URL 策略必须有效 |
| 阻断缺陷 | 整个稳定版本窗口内 P0/P1 新增和未关闭数量均为 0 | 必须记录缺陷系统查询区间、查询条件和快照；任何 P0/P1 都重置该门禁窗口 |
| 旧入口占比 | 同一任务 Classic task request ≤ Classic + TUI task request 的 5% | 分母只使用目录中可比较的同任务执行请求；样本不足 20 次不能自动通过，必须由 owner 与独立 reviewer 对该任务双签低频例外 |
| 运行错误 | 同一观察窗口内，TUI 对应任务错误率相对 Classic 不回退超过 0.5 个百分点 | Classic 与 TUI 各至少 20 次可比较 task request；不足时必须继续观测，低频例外不能豁免错误率门禁，也不得用全站流量稀释 |
| 生产遥测覆盖 | 101/101 个可比较任务都有合法任务记录，并满足样本门槛 | 样本必须来自有界 catalog key；跨源 Referer、未知 key 和非执行 deep-link 不得归入任务样本 |
| 回滚演练 | 完整演练一次 graph/runtime 与 route/template 的 wave 级回滚，并验证工作树、registry 与服务恢复 | 本地演练通过不等于生产 registry 已备份 |
| 生产 registry 备份 | 切换前取得生产 registry payload、generation、graph hash、schema/runtime 版本和 SHA-256，可独立恢复并验证 | 备份位置、保留期、恢复命令和验证人必须写入证据，敏感内容不得写入仓库 |
| 切换审批 | owner 与独立 reviewer 明确批准，且批准对象绑定同一候选版本和证据快照 | 低频例外不能由同一人兼任 owner 与 reviewer；候选版本或门禁证据变化后必须重新复核 |

> **门禁实现已收紧（2026-07-27）**：checker 只允许低频双签豁免旧入口占比；Classic 与 TUI 任一侧少于 20 个可比较 task request 时，错误率门禁仍为失败。对应回归明确验证低频例外不能绕过错误样本要求。

> **生产证据绑定已收紧（2026-07-27）**：候选版本必须同时绑定能在本仓库解析的完整 Git commit，格式合法但不存在的 object ID 不能启动稳定窗口；UAT、缺陷、生产遥测、回滚与 registry 备份均须指向仓库内可审计证据文件，并以实际文件 SHA-256 防替换。缺陷快照还必须包含查询条件和查询时间；遥测必须声明 production 环境和采集时间。生产 registry 备份不能再用非空路径占位，必须使用受限外部 locator、正 generation，并记录证据/payload/graph SHA-256、schema/runtime、恢复 dry-run、验证人和保留期，备份时间不得早于观察窗口结束，且须绑定候选版本、commit 与矩阵证据 SHA。owner/reviewer 审批也必须分别绑定同一三元组、经 SHA-256 校验的独立评审快照和观察窗口结束后的批准时间；任一字段缺失或摘要不匹配均 fail closed。

> **机器证据再验证已收紧（2026-07-28）**：readiness checker 不再只相信 cutover evidence 中的投影字段。候选 commit 必须属于当前分支且其提交内矩阵 SHA 与当前范围一致；逐 route rollback 映射必须逐值等于矩阵并指向当前分支祖先；缺陷和生产遥测必须是生成器可重新解析的结构化 JSON，checker 会从 issue/task 原始记录重建投影并要求精确相等。生产遥测分母统一从 `classic_routes.task_key` 推导为 101 个可比较任务，不再误用包含 TUI-only action 的全量 `tui_task_keys`。生产 registry 备份也必须由 `build_tui_registry_backup_evidence` 从仓库外 bundle/sidecar、当前 active generation/hash 与 restore payload 验证结果生成不含 payload 的 attestation，手填摘要或说明文档不再可用。最后的 review snapshot 只能在其余 8 个 gate 全通过时生成，owner/reviewer 必须用不同身份分别记录角色绑定 attestation；候选、gate 结果或摘要变化都会使旧签字失效。

## 4. 去向分类定义

| 档位 | 定义 | 迁移手段 |
|---|---|---|
| A：迁入 TUI | 表单/CRUD/列表/详情/工作台类页面 | API → action metadata → datagrid/detail panel；按角色和对象归属暴露 read/ai/write，unsafe/admin 继续执行后端权限、确认、验密与审计 |
| B：TUI + 图表补齐 | 图表重的分析/监控页 | 依赖 M1 建立的 `chart`/`kpi_trend`/`table_chart`/custom renderer 生产约定；迁不了的单个图表允许经 `host_slot`/`image` 降级 |
| C：保留 web | 外部/偶发流程、Admin、错误页、基座与 TUI shell | 不迁；纳入“web 保留清单”（§8），说明 owner、保留理由和复核日期 |
| D：删除 | 影子重复、无路由、无引用的死模板 | 通过 Django template loader origin、路由、继承/include、测试和运行证据确认后，在独立 M0-D 子批删除 |

## 5. 分批实施

### M0：冻结与全量盘点

| 项 | 内容 |
|---|---|
| 入口条件 | 本计划获批准；记录当前 template 清单 hash、published graph hash、schema version、runtime build id、两端 validator 与现有浏览器基线 |
| 范围 | 冻结新 web 业务页面（AGENTS.md 补临时约束）；按 §10 字段产出 195 个模板的全量映射矩阵；建立 URL/view/template 依赖图；用 Django template loader 确认 `core/templates/audit`、`core/templates/data_center` 等重复模板的实际解析 origin；定稿 §8；产出 ADR |
| M0-D 子批 | 只删除已经证明无路由、无 loader 命中、无继承/include、无邮件/任务/测试引用的 D 档模板；每个 owner app/目录独立 commit，不与 inventory 文档混提交 |
| 验收 | 映射矩阵精确覆盖 195 个模板；A/B/C/D 互斥且合计 195；所有 route page 均有关联 URL/view；C 档逐项有 owner 和理由；API 缺口形成 backlog；D 档删除通过定向路由、模板渲染与引用检查 |
| 回滚 | 撤销冻结条款与 ADR；M0-D 删除按独立 commit revert；映射矩阵保留为审计证据 |

### M1：图表能力样板（最大未知量，先行）

| 项 | 内容 |
|---|---|
| 入口条件 | M0 映射矩阵和 API 缺口已锁定；可移植性基线已记录；样板 API 已证明稳定、只读且有明确 payload 契约 |
| 范围 | 从 B 档按“API 就绪、只读、数据量可控、权限简单、能代表主要图表形态”选择 1 个端到端样板，候选为 `macro/data.html`；建立 `chart`/`kpi_trend`/`table_chart` view_model 约定，包括 series/rows shape、时间与单位、空态/错误态、颜色与文本语义、采样/分页、格式化和最大 payload；如需产品专用 `custom` renderer，只在 `frontend/agomtradepro-host` 注册；把通用约定写回设计标准与 schema `description` |
| 验收 | 样板通过 validate/smoke/promote/local publish-check；三种 viewport 无重叠/横向溢出；键盘可达、状态不只依赖颜色；空数据、部分失败、超大数据和时区格式测试通过；`npm run check:tui`、`npm run test:tui-js`、静态契约与 Playwright UAT 全绿；通用改动同时通过 AgomTUI 双端兼容门禁 |
| 退出决策 | 样板评审后明确 M4 可直接复用的 renderer、仍需新增的能力、允许的临时降级和禁止迁移的图表类型；未通过则不得启动 M4 |
| 回滚 | 样板 metadata、host adapter、通用 runtime/schema 分 commit；按记录的兼容矩阵回滚，不允许只重发与当前 runtime 不兼容的旧 graph |

### R0：TUI Actionability Remediation（P0，跨 M2/M3）

| 项 | 内容 |
|---|---|
| 入口条件 | 以当前 IA、runtime injection 与已存在的 owner-app write action 为基线；不等待 M5 生产 cutover，也不解除后端权限/确认/审计闸门 |
| 第一批 | `execution.accounts`：显式创建账户入口并保留账户行级详情/删除；`ai-ops.providers`：显式创建服务商入口，并在服务商行提供查看/编辑/切换/删除；随后补 `policy.workbench` 的审批/驳回与 `research.signals` 的候选/信号行级操作 |
| 实施边界 | 先改 IA registry 与 runtime metadata，再补 TUI metadata/浏览器回归；已有 API 缺口必须回 owner app 按四层补齐，不把业务逻辑塞进 `terminal`；静态 published graph 与 runtime-only action 的差异必须有 promotion/deferred 证据 |
| 验收 | 每个第一批 screen 至少有一个可见 create/edit/delete/approve/bind 入口；表单能填写真实字段，row action 参数来自行字段，写后刷新/回执可见；普通用户、owner/object、staff/admin 权限与确认/重新认证、错误态、空态均有可复现测试；`npm run check:tui`、`npm run test:tui-js`、TUI Workbench 定向 pytest 与浏览器主任务 UAT 全绿 |
| 当前进度 | **进行中**：已落地 `execution.accounts` 创建 prompt、`ai-ops.providers` 创建 prompt 与查看/编辑/切换/删除 row actions；本批继续落地 `policy.workbench` 创建与审核行操作、`research.signals` 创建与治理行操作；仍需核对静态 published graph promotion |
| 回滚 | IA、runtime injection、前端与测试分离提交；任何 action key、参数映射或权限回退均按 R0 子批回滚，不进入 M5-B 清理 |

#### R0 执行记录（2026-08-14）

- 已修改 `config/tui/ia/tui_information_architecture.v1.json`：`execution.accounts` 新增创建账户 dashboard prompt；`ai-ops.providers` 新增创建服务商 prompt，并为服务商列表绑定查看、编辑、启停、删除四个行级动作。动作均复用已有 runtime API，不新增 terminal 业务逻辑。
- 本批继续修改同一 IA：`policy.workbench` 新增创建政策事件 prompt，并为待审事件绑定查看、批准、拒绝、回滚、临时豁免行操作；`research.signals` 新增创建投资信号 prompt，并为活跃信号绑定编辑、批准、拒绝、证伪、删除行操作。拒绝/回滚/证伪的理由字段分别从行数据映射到可继续填写的理由输入，不绕过后端确认与权限。
- 已新增 `tests/unit/test_tui_actionability_contract.py`，验证 IA 行字段映射、create action 的 POST/effect，以及 runtime 注入后 canonical screen 的 action 绑定。
- 已验证：该定向 pytest `4 passed`；已有 Beta Gate/rotation/policy metadata 回归 `3 passed`；`npm run check:tui` 通过；`npm run test:tui-js` `31 passed`；Black、isort、`git diff --check` 通过。
- 未完成/未验证：静态 published graph 对 runtime-only write action 的 promotion 证据；模拟账户完整 Django 生命周期测试本轮运行超过 124 秒超时，不能视为通过；当前环境没有 `ruff` 可执行文件。

### M2：第一批 A 类（表单/CRUD/配置）

| 项 | 内容 |
|---|---|
| 入口条件 | M0 完成；目标子批 API gap 已关闭；目标 screen/action 数量不突破 IA action-density 预算；R0 已为本 wave 的 mutation 任务补齐可见 create/edit/delete/approve/bind 入口 |
| 范围 | account（资料/Token/用户管理/模拟账户）、policy（事件 CRUD、RSS 管理）、ai_provider（管理/配额/日志）、alpha_trigger、beta_gate、decision_rhythm 配额、rotation 配置、prompt、signal、backtest 配置；按“一个主任务 + 一个 owner app 子域”拆 wave，每个 wave 独立 commit 组和证据 |
| 单 wave 上限 | 默认不超过 3 个 route page 或 1 个复杂 CRUD 工作台；超出时必须在跟踪表说明无法继续拆分的原因 |
| 验收 | 每个目标 screen 满足设计标准；普通用户 write、admin/unsafe、确认、重新认证、对象归属与审计均有契约测试；写后刷新和 receipt 可见；列表行可直接进入对应 mutation，而不是让用户手填 ID；旧页显示弃用提示与准确 deep link；最小回归包和该 app 的 API/浏览器任务测试全绿 |
| 回滚 | 按 wave revert；metadata/runtime/API 依据兼容矩阵联动回滚 |

### M3：第二批 A 类（列表/详情/工作台）

| 项 | 内容 |
|---|---|
| 入口条件 | 同 M2；列表、详情、分页、筛选和复杂字段 payload 已形成稳定 API 契约 |
| 范围 | strategy（列表/详情/规则编辑器）、data_center 治理、ops 控制台、task_monitor、agent_runtime 任务/提案、equity 池/筛选/配置、decision 工作流页；沿用 M2 的 wave 上限 |
| 验收 | 同 M2；复杂表单显式声明 `multiline`/字段语义；分页、筛选、排序、长列表、并发冲突、任务进行中/失败/重试状态有测试；不得以 placeholder 或 raw JSON 凑数 |
| 回滚 | 同 M2 |

### M4：B 类图表域（依赖 M1）

| 项 | 内容 |
|---|---|
| 入口条件 | M1 退出决策通过；目标域所需 renderer 全部为已批准能力；API payload、单位、时区与数据量预算已锁定 |
| 范围 | dashboard、regime、macro、equity detail、simulated_trading 业绩、filter、sentiment、audit 归因/绩效图表页；每域先决定 chart、detail/datagrid 或批准的临时降级 |
| 验收 | 用户主任务（看环境、看净值、看归因）在 TUI 内闭环；图表与原页面关键数值同源且抽样勾稽一致；renderer 无业务名硬编码；空态、错误态、数据新鲜度、单位、时区、性能、键盘与三 viewport UAT 全绿 |
| 降级规则 | `host_slot`/`image` 只能作为有 owner、有到期日的临时例外；永久保留 web 必须重新定档 C 并更新 §8，不得用“单图迁不动”绕过完成定义 |
| 回滚 | 同 M2；通用 runtime/schema 改动按双仓兼容矩阵联动回滚 |

### M5：清理与收口

| 项 | 内容 |
|---|---|
| M5-A 观测 | 实现完成后启动双轨生产观测、任务级 UAT、缺陷窗口、生产 registry 备份和审批收集；该子阶段允许修复，不允许删除 Classic |
| M5-B 入口条件 | §2.7 的唯一放行命令返回 ALLOW；每个待删 route page 均满足 §3 量化门禁，且矩阵中有完整 UAT、遥测、回滚和旧 URL 处置证据 |
| M5-B 清理范围 | 按 owner/wave 删除兼容期满的模板及只为其服务的 view、route、菜单链接和孤儿静态资源；保留/增加必要的 TUI deep-link redirect 或显式 410；移除或收缩 "Classic 界面" 链接；清理已证明无消费者的 `legacy_screen_aliases` |
| 单 wave 上限 | 默认不超过 10 个 route page；每个 wave 独立 commit、独立 rollback manifest、独立验证。每个 wave 清理后至少观察 48 小时并覆盖 1 次对应定时任务周期；自然流量不足时补角色化生产 smoke，观察完成前不得继续下一 wave |
| M5-C 收口 | 全部清理 wave 完成后核对剩余模板与 §8，更新常态冻结规则、归档计划并关闭临时告警/兼容资产；任何仍在例外期的任务都会阻止归档 |
| 验收 | 剩余模板集合与 §8 机器核对一致；旧 URL 行为与矩阵一致；模板 loader、反向解析、浏览器书签/deep link、权限、全量测试、TUI JS 和 Playwright 回归全绿；无孤儿 view/route/static 引用 |
| 回滚与停止线 | 模板、view/route、redirect 和静态资源按 owner app 独立 commit；任一 wave 出现 P0/P1、错误率超阈值、权限回退或关键任务不可完成时立即停止后续 wave，并按 manifest 回滚该 wave |

#### M5-A 当前剩余工作（2026-07-28）

按以下顺序推进；前一项未形成可复现证据时，不得用后一项的结果替代：

1. **已关闭 5 条治理/筛选 UAT 缺口**：已取消会遮挡后续表单的整组 sticky 定位，未使用 Playwright `force=True`；覆盖决策配额配置、Beta Gate 配置创建、Beta Gate 资产测试、股票筛选和基金多维筛选 5 个 route page。
2. **已关闭 11 条本地详情/生命周期 UAT 缺口**：覆盖 Agent Runtime 2 条、Alpha Trigger 5 条、Audit 1 条、Backtest 2 条和 Factor 1 条；修复 Backtest `run_async` Interface/Application 契约并补回归。
3. **已关闭最后 2 条外部 AI 主任务 UAT**：使用一次性 Playwright SQLite 中加密保存的受控 DeepSeek Provider，真实完成 Sentiment 分析 1 条和 Terminal Agent chat/config 1 条；未使用 mocked execution，完整浏览器套件为 `15 passed`，主任务 UAT 达到 108/108。
4. **已关闭逐 route 权限证据**：108/108 route 已登记匿名认证、普通用户、owner/object、staff/admin 与特殊混合角色边界；完整 route closure 权限套件 `6 passed`，机器 gate 的 `permission` 为 108/108。
5. **已关闭逐 route 空态证据**：108/108 route 已按计划角色验证目标任务、任务级 `empty_state_hint` 和 `next_step_hint`；运行层统一把 screen 指引带入列表、详情和图表空结果，Workbench 浏览器实际渲染任务专属文案与后续引导。完整 route closure 套件现为 `7 passed`，机器 gate 的 `empty_state` 为 108/108。
6. **已关闭逐 route 错误态证据**：108/108 route 已通过真实 action runner HTTP 边界的受控异常取证；每条 route 均返回任务级有界错误、trace id、重试入口和原工作区恢复动作，内部异常文本不泄露。完整 route closure 套件为 `8 passed`，机器 gate 的 `error_state` 为 108/108。
7. **已关闭逐 route 回滚证据**：89 个 A 类 route、17 个 B 类 route 和 2 个由后端重定向/运行时承接的 route 已分别绑定到 3 个真实迁移提交；`build_web_to_tui_rollback_catalog.py` 验证完整 SHA、当前分支 ancestry 与矩阵/evidence 精确一致，返回 `routes=108 commits=3`。逐 route 六类 scope 因此达到 108/108；这不替代其余生产门禁。
8. **锁定候选版本和缺陷窗口**：把同一候选版本的 `stable_version`、`released_at`、`observation_end` 写入证据，绑定 P0/P1 查询区间与快照；任何重置条件都必须重新计算窗口。仓库已新增 `start_web_to_tui_observation.py`，只接受当前分支历史内、包含同一迁移矩阵且工作树干净的候选 commit；切换候选必须显式 `--replace`，并自动清空旧候选绑定的缺陷、遥测、生产备份和审批。`build_web_to_tui_defect_evidence.py` 只接受仓库内、绑定同一候选版本/commit/矩阵 SHA/精确窗口的受审 tracker 快照，并从 issue 生命周期分别推导窗口内 `new_p0/new_p1` 与 `open_p0/open_p1`；四项必须同时为 0，已关闭的新缺陷也不能从窗口证据中消失。2026-07-28 只读生产核查确认线上仍为 `dev/next-development@2e399607977fea260436992952fae64565153213`，该提交不包含当前迁移矩阵；当前尚未选定并部署候选版本，因此两个工具均未执行、观察窗口仍未开始，且不得从 2026-07-26 回填。详见 `web-to-tui-m5-production-preflight-2026-07-28.md`。
9. **补齐生产遥测**：由 `classic_routes.task_key` 推导的 101/101 个可比较任务均产生 catalog 内合法记录，并分别满足 Classic/TUI 错误样本要求；全量 `tui_task_keys` 中没有 Classic 对照的 TUI-only action 不进入分母。低频双签只能豁免旧入口占比样本，不得豁免错误率样本。仓库已新增 `build_web_to_tui_production_telemetry.py`，只接受仓库内、绑定同一候选版本/commit/矩阵 SHA/精确窗口的生产 Prometheus 快照，并锁定六条批准 PromQL、精确 task 集合、样本/占比/错误率门槛及快照 SHA；runtime 分类器只接纳已认证用户，匿名登录跳转和伪造 Referer 不进入样本。默认 dry-run，完整通过后才能 `--write-evidence`。当前尚无生产快照，覆盖仍为 0/101。
10. **完成生产 registry 保障**：使用 `backup_tui_registry` 在仓库外取得生产 registry JSON + SHA-256 sidecar；观察窗口结束后由 `build_tui_registry_backup_evidence` 验证 bundle 完整性、当前 active generation/hash、restore payload、候选绑定和保留期，生成不含 payload 的结构化 attestation 并同步 cutover evidence；实际恢复仍由 `restore_tui_registry_backup` 默认 dry-run/显式批准流程执行。工具与集成测试已落地，但生产执行仍未完成。
11. **冻结评审快照并完成双签**：其余 8 个 gate 全通过后，用 `build_web_to_tui_review_snapshot.py` 冻结候选、矩阵、108 route、101 task 和精确 gate 结果；owner 与独立 reviewer 再分别通过 `record_web_to_tui_cutover_approval.py` 生成角色绑定 attestation。两个身份必须不同，签署时间不得早于观察窗口和 review snapshot；工具只记录真实决定，不生成伪审批。当前尚无真实双签。
12. **最后执行唯一放行命令**：只有 `python scripts/check_web_to_tui_cutover_readiness.py --require-allow` 明确输出 ALLOW 且退出码为 0，才能创建 M5-B 清理 wave；人工说明、日历到期或单项测试通过都不能替代该结果。

## 6. 标准验证命令

以下命令从仓库根目录执行，默认已激活 `agomtradepro` 虚拟环境。每个 wave 合入前运行固定包；仅改文档的 M0 inventory commit 可在证据中说明不适用项，M0-D/M1-M5 不得省略相关门禁。

```bash
# TUI 最小回归包（AGENTS.md 固定）
pytest tests/unit/test_tui_workbench.py -q
pytest tests/unit/test_terminal_agent_service.py -q
pytest sdk/tests/test_sdk/test_client.py -q
pytest tests/unit/test_internal_ssl_redirect.py -q

# TUI 契约与治理
pytest tests/unit/terminal/test_tui_information_architecture.py -q
pytest tests/unit/terminal/test_tui_contract_guardrails.py -q
pytest tests/unit/test_tui_static_contracts.py -q
python scripts/check_tui_static_contracts.py
python scripts/check_mcp_tui_action_coverage.py

# Runtime/host 构建与 JS 测试
npm run check:tui
npm run test:tui-js

# metadata 全链（有 screen/action/panel 变更时）
python tui-metadata-compiler/scripts/validate_tui_metadata.py \
  config/tui/published/tui_operation_graph.published.json
python tui-metadata-compiler/scripts/smoke_tui_actions.py \
  --metadata-path config/tui/published/tui_operation_graph.published.json \
  --json-output reports/tui/migration-smoke.json \
  --fail-on-error

# M5 证据结构检查；执行任何 Classic 清理前必须追加 --require-allow
python scripts/build_web_to_tui_telemetry_catalog.py --check
# 候选版本部署且工作树干净后，先 dry-run，再显式写入 14 日观察窗口
python scripts/start_web_to_tui_observation.py \
  --stable-version <version> --candidate-commit <full-commit> \
  --released-at <YYYY-MM-DD>
python scripts/start_web_to_tui_observation.py \
  --stable-version <version> --candidate-commit <full-commit> \
  --released-at <YYYY-MM-DD> --write
# 观察窗口结束并取得仓库内 issue-tracker 快照后，先 dry-run 再写 evidence
python scripts/build_web_to_tui_defect_evidence.py \
  --snapshot <repo-relative-defect-snapshot.json> --require-clear
python scripts/build_web_to_tui_defect_evidence.py \
  --snapshot <repo-relative-defect-snapshot.json> --write-evidence --require-clear
# 观察窗口结束并取得仓库内生产 Prometheus 快照后，先 dry-run 再写 evidence
python scripts/build_web_to_tui_production_telemetry.py \
  --snapshot <repo-relative-production-snapshot.json>
python scripts/build_web_to_tui_production_telemetry.py \
  --snapshot <repo-relative-production-snapshot.json> --write-evidence
# 在生产执行 registry 外部备份后生成无 payload attestation（默认 dry-run）
python manage.py build_tui_registry_backup_evidence \
  --input <external-backup.json> \
  --location <artifact-or-s3-or-sftp-or-https-locator> \
  --verified-by <independent-reviewer> \
  --retention-until <YYYY-MM-DD> \
  --attestation-output <repo-relative-registry-attestation.json>
# 其余 8 个 gate 全通过后冻结 review snapshot，再分别记录真实双签
python scripts/build_web_to_tui_review_snapshot.py \
  --as-of <YYYY-MM-DD> \
  --snapshot-output <repo-relative-review-snapshot.json> --write-evidence
python scripts/record_web_to_tui_cutover_approval.py \
  --role owner --name <owner-identity> --approved-at <YYYY-MM-DD> \
  --attestation-output <repo-relative-owner-attestation.json> --write-evidence
python scripts/record_web_to_tui_cutover_approval.py \
  --role reviewer --name <independent-reviewer-identity> --approved-at <YYYY-MM-DD> \
  --attestation-output <repo-relative-reviewer-attestation.json> --write-evidence
# 在 owner/wave 安全提交形成并更新矩阵后，同步并复核精确 route→commit 证据
python scripts/build_web_to_tui_rollback_catalog.py --write-evidence
python scripts/build_web_to_tui_rollback_catalog.py
python scripts/check_web_to_tui_cutover_readiness.py
python scripts/check_web_to_tui_cleanup_guard.py
# 以下命令必须明确输出 ALLOW 且退出码为 0，才能执行 M5-B
python scripts/check_web_to_tui_cutover_readiness.py --require-allow

# 架构护栏
python scripts/check_architecture_delta.py \
  --rules-file governance/architecture_rules.json \
  --base-ref origin/main \
  --head-ref HEAD \
  --include-audit \
  --fail-on-audit-violations \
  --format text

# 全仓架构扫描（覆盖工作树及尚未纳入 HEAD 的生产文件）
python scripts/verify_architecture.py \
  --rules-file governance/architecture_rules.json \
  --include-audit \
  --fail-on-audit-violations \
  --format text

# 全仓 mypy 债务上限；只有真实债务下降时才允许另行执行 --write-baseline
python scripts/check_mypy_debt_ceiling.py

# 浏览器 smoke；每个 wave 还必须运行该 wave 新增的任务级 UAT
python scripts/run_live_server_pytest.py \
  --suite-name smoke \
  --port 8010 \
  --base-url http://127.0.0.1:8010 \
  --junitxml reports/quality/local-smoke.xml \
  --min-tests 10 \
  -- tests/playwright/tests/smoke -q --browser chromium
```

补充规则：

- `smoke_tui_actions.py` 只执行 `read/ai` action；新增 `write/unsafe/admin` action 必须由定向单元测试、API 契约测试和 Playwright 任务流覆盖。
- `smoke_tui_actions.py --fail-on-error` 必须使用已完整迁移的一次性数据库、持久化 staff 用户和同库 localhost 服务（MCP action 需要）；首装无 Regime/Pulse/AI Provider 时必须返回明确空态或需配置状态，不能依赖开发库历史数据，也不能把任意 4xx/5xx 加入忽略清单。
- 修改生产 Python 时，按变更文件运行 `python scripts/check_mypy_regression.py <changed-production-python-files>`；测试路径以 §10 映射矩阵登记的实际文件为准，不使用不存在的通用占位目录。
- `check_architecture_delta.py --base-ref origin/main --head-ref HEAD` 只审查已进入提交的增量；本地收口必须再运行 `verify_architecture.py` 全仓扫描，确保尚未提交或未跟踪的生产 Python 文件也纳入边界与审计规则。
- `check_mypy_debt_ceiling.py --write-baseline` 不是常规修复手段；仅当无新增错误且命令明确报告历史债务下降时才允许执行，写回后必须再次运行不带参数的检查确认新上限生效。
- 修改通用 runtime/schema 时，继续执行可移植性计划要求的 AgomTUI 下游 validator、runtime sync check 和 JS 测试，并把结果写入本计划跟踪表。
- 本地审核发布使用：

```bash
python tui-metadata-compiler/scripts/publish_tui_metadata.py \
  config/tui/published/tui_operation_graph.published.json \
  --approve \
  --generation-source mixed \
  --backend-version "local-dev" \
  --source-evidence-path config/tui/generated/tui_operation_evidence.generated.json \
  --review-note "Reviewed web-to-TUI migration wave"
```

- 发布后用同一脚本的 `--check --registry-key default` 校验 registry。正式生产发布统一走 `scripts/publish-tui-release.sh <release-version>`；禁止手改 DB payload，也不得把本地 `--approve` 命令当作生产发布流程。

## 7. 风险与控制

| 风险 | 控制 |
|---|---|
| 双维护期 web/TUI 漂移 | 冻结条款（M0）+ 按 wave 逐批 + 旧页弃用提示；C 档必要新增必须走例外审批并更新保留清单 |
| 图表能力不足导致 M4 烂尾 | M1 先行建样板并产出退出决策；临时降级必须有 owner/到期日，永久不迁需重新定档 C |
| 迁移变成逐页翻译、screen 质量退化 | 每批验收硬卡设计标准；IA 契约测试（`test_tui_information_architecture.py`）机器检查 |
| 缺失 API 导致 terminal app 长业务逻辑 | 原则 4：缺端点先在 owner app 按四层补，CI 架构护栏兜底 |
| 影子模板误删活页面 | M0 同时检查 URL/view、Django loader origin、继承/include、异步任务/邮件和测试；D 档放入独立 M0-D commit |
| 外部用户（分享/观察者）受影响 | §8 保留清单不动；M5 只删已迁域模板 |
| 普通用户写能力被误删 | 建立角色 × action risk × effect × 对象归属矩阵；write action 做确认、权限、写后刷新和审计测试 |
| 旧书签/深链断裂 | 每个 route page 预先定义 redirect/retain/410/404；Playwright 验证旧 URL 和参数映射 |
| graph 与 runtime/schema 回滚不兼容 | 每 wave 记录 graph hash、schema、runtime build、registry generation 和兼容矩阵；必要时联动回滚 |
| 双仓 schema/runtime 漂移 | M1/M4 通用变更执行 AgomTradePro + AgomTUI 双端 validator、sync check 与 business leakage 门禁 |
| 大批次难以验收和回滚 | M2/M3 默认每 wave 不超过 3 个 route page 或 1 个复杂 CRUD 工作台；跟踪表逐 wave 记录 owner 和证据 |
| 只验证“能渲染”未验证“能完成任务” | 每个 route page 至少有一个主任务 UAT，覆盖角色、空态、错误态、写操作、刷新、键盘和 console |
| 遥测归因错误或样本被全站流量稀释 | 只接受 telemetry catalog 中有界 task key；Classic 使用同源页面 Referer 归因入口/API 执行，TUI 使用真实 action execution；跨源/未知 key 丢弃并告警 |
| 在 DENY 状态下提前删除 Classic | CI cleanup guard 只固定放行 7 个已审 M0-D 基线；新增 `deleted` 必须重放变更前最终双签，并逐 M5-B wave 验证删除后 candidate binding、≤10 route、rollback manifest、≥48h 观察、定时周期、缺陷和错误率，否则 fail closed；任何人工叙述不得覆盖机器结果 |

2026-08-13 已增加独立 M5-C 最终库存模式 `python scripts/web_template_migration_inventory.py --require-finalized`。普通 `--check` 继续只验证迁移期 196 行冻结台账；最终模式另要求物理模板精确等于 41 个 C 档路径、A/B/D lifecycle 全为 `deleted`，并拒绝已删模板残留 view/route literal、仅由已删模板消费的静态资产、无活生产代码消费者或指向非 canonical screen 的 legacy alias。当前普通检查通过；最终模式按设计失败，原因包括 148 个 A/B 模板尚未完成 lifecycle。published graph 当前 32 个 legacy alias 中另有 11 个无活生产代码引用；检查器现会把 IA `published_screens`/`runtime_screens` 纳入 canonical target 集合，因此此前 `capability-router.gateway` → `capability-router.mcp-center` 的 dangling 误报已消除。11 个 dead alias 仍须在真实流量观察与各 wave 证明后清理，不能据静态扫描提前删除。

同日新增 `record_web_to_tui_cleanup_wave.py` 与结构化 schema，正式承接 M5-B 每波记录。recorder 从 immutable candidate Git snapshot 重算新增删除、连续 wave、route 数、catalog task 和 rollback commit；每次只允许新增一个 wave且 route page 为 1–10 个。它强制读取已提交的 production deployment preflight，并要求 source commit/OCI revision 精确等于删除候选；deployment attestation 必须在 candidate 之后、观察开始之前提交，48 小时窗口不得早于部署核验。telemetry、P0/P1 defect tracker 与 scheduled cycle 三类原始证据均按 exact schema 重算，caller 不能提交 `passed` 或自报日期。当前无 M5-B 删除候选，CLI 按设计返回 FAIL，不产生证据。

发布工具也已在仓库侧补齐 provenance：上传构建拒绝 dirty worktree 和 `unknown`/非完整 commit，clone 构建锁定 expected commit；两种路径均要求 OCI revision exact match，并生成只读 release manifest。deploy 会在任何服务启动或 `current` 切换前核验 manifest、image ID 与 revision。相关本地回归 `44 passed`。该代码尚未部署，当前生产快照仍无法证明候选身份，因此不能据此启动或回填 M5-A。

## 8. Web 保留清单（C 档，当前 41 个）

| 保留域 | 模板范围 | 数量 | 默认 owner | 保留理由 |
|---|---|---:|---|---|
| share 公开分享 | `core/templates/share/**` | 13 | share | 面向未登录外部访问者，需富展示与免责声明 |
| observer 门户 | `core/templates/account/observer_portal.html`、`core/templates/account/collaboration.html` | 2 | account | 面向非日常操作者 |
| 登录与注册 | `core/templates/account/login.html`、`core/templates/account/register.html` | 2 | account | 发生在认证前，不能依赖需要已认证会话的 TUI shell |
| setup_wizard | `apps/setup_wizard/templates/**` | 7 | setup_wizard | 一次性初始化流程，web 引导成本最低 |
| Django Admin 定制 | `core/templates/admin/**` | 9 | 对应模型 owner | Admin 生态本身是模板驱动，不宜迁 |
| 错误页与基座 | `core/templates/base.html`、`core/templates/base_auth.html`、`core/templates/404.html`、`core/templates/500.html` | 4 | core | 保留页面与错误页的共同基座 |
| TUI shell | `core/templates/terminal/tui_workbench.html`、`core/templates/terminal/index.html` | 2 | terminal | TUI 自身的宿主模板 |
| docs 页 | `core/templates/docs/**` | 2 | docs/core | 文档展示，低频 |
| 合计 | — | 41 | — | 必须逐文件核对，不允许用 glob 数量漂移 |

保留清单以外的模板最终去向只有 A/B/D 三种；M0 为每项补 `last_reviewed_at`。M5 完成时仓库模板集合必须与本表展开后的精确文件清单一致，数量和路径均由机器检查。

## 9. 里程碑跟踪与证据

> 2026-07-28 起，W1–W51 的已完成过程证据按 M2/M3/M4 里程碑合并；原文件名、
> SHA-256 和完整正文保留在合并文档中，Git 历史继续提供逐文件审计。M5 未完成，
> 继续使用独立门禁证据，避免把生产取证与已完成的实现 wave 混在一起。

| 里程碑 | Wave / 范围 | 状态 | 证据真源 |
|---|---|---|---|
| M0 / M0-D | 195 模板基线、矩阵、冻结与 7 个死模板清理 | 已完成 | `../archive/plans/web-to-tui-m0-evidence-2026-07-26.md` |
| M1 | 图表契约样板 | 已完成 | `../archive/plans/web-to-tui-m1-chart-evidence-2026-07-26.md` |
| R0 | TUI actionability：已有 write action 显性化、create/edit/delete/approve/bind 入口、写后刷新与回归 | 实施中；已落 `execution.accounts`、`ai-ops.providers`、`policy.workbench`、`research.signals` 元数据入口 | IA registry、runtime injection、TUI Workbench 定向测试与本节整改记录 |
| R1 | 行级编辑可用性：带可见 body 字段的 update/edit 行动作必须先打开可编辑表单，提交前不得发 PATCH/POST，并保留行身份与字段映射 | 本地 Workbench 已完成；除 `signal.update`、`beta-gate.config-update`、`rotation.asset-update`、`rotation.config-update`、`rotation.account-config-update`、`ai-ops.update-my-provider`、`data-center.provider-update` 外，用户治理的 `identity-access.reject-user`、`identity-access.set-user-role` 也已接入行级表单；角色化浏览器 UAT、写后 receipt/refresh 与生产审计仍未完成 | `frontend/tui-workbench/src/20-dashboard.js`、`apps/terminal/infrastructure/tui_metadata_runtime_injection_user_access.py`、`workbench-browser.test.mjs`、`tests/unit/test_tui_actionability_contract.py`；本地 Node/Python 回归见 `docs/plans/README.md` |
| M2 | W1–W20，配置、CRUD 与治理任务 | 已完成 | `../archive/plans/web-to-tui-m2-consolidated-evidence-2026-07-26.md` |
| M3 | W21–W42，长尾工作台与运维任务 | 已完成 | `../archive/plans/web-to-tui-m3-consolidated-evidence-2026-07-26.md` |
| M4 | W43–W51，图表与分析任务 | 已完成 | `../archive/plans/web-to-tui-m4-consolidated-evidence-2026-07-26.md` |
| M5 | 108-route UAT/closure、回滚与生产 cutover | M5-A DENY；2026-08-15 候选已部署并完成 provenance/health 复核，角色化 UAT、观察窗口和写后审计仍未完成 | [`docs/deployment/vps-deployment-evidence-2026-08-15.md`](../deployment/vps-deployment-evidence-2026-08-15.md) 与 `web-to-tui-m5-readiness-2026-07-27.md` |

### 2026-08-15 候选部署证据

`dev/next-development@96ce6ee43b06e6eb6ad51528ff8ee783a4bf0952` 已部署为后续 release `20260815144517`；image ID、OCI revision、只读 release manifest、health、Celery/Caddy、account `0037`–`0053` migrations 与 TUI registry active hash 均已在 [`VPS 候选部署证据`](../deployment/vps-deployment-evidence-2026-08-15.md) 中固定。本次使用标准 `git-clone` 构建并完成 `pyqlib=0.9.7` 身份校验，同时修复并部署 TUI AI provider failure guidance。该证据不是角色化浏览器 UAT、14 日观察或 M5 放行证据。M5-A 仍为 `DENY`，不得清理 Classic、回填 14 日窗口或宣称写入闭环完成。

随后当前候选 `dev/next-development@1835ce0ee42f220756066a21890bcec2b8f1f3e9` 已以
`20260815221000`、code-only、保留数据卷的 `-Upgrade` 模式部署；完整身份、health/ready、
迁移、TUI registry、Qlib、Celery 和备份证据已追加至同一 VPS 部署记录。该候选仍只建立
provenance，不自动开始 14 日窗口或角色化 UAT；M5-A 继续 `DENY`。

## 10. M0 映射矩阵契约

M0 的主产物固定为 `docs/plans/web-to-tui-migration-matrix-2026-07-25.csv`；本文只记录契约和阶段结果，不内嵌动态清单。该文件以 195 行为初始基线，当前因迁移期共用兼容 partial 增至 196 行；新增、删除或移动模板必须在同一改动中更新矩阵并通过 inventory check。每行至少包含：

| 字段组 | 必填字段 |
|---|---|
| 模板身份 | `template_path`、`template_role`、`owner_app`、`content_hash` |
| 实际入口 | `url_name`、`url_path_pattern`、`view_callable`、`http_methods`、`resolved_template_origin` |
| 依赖关系 | `extends`、`includes`、`consumers`、`related_static_assets`、`email_or_task_usage` |
| 用户契约 | `primary_task`、`audience`、`auth_required`、`permission_rule`、`write_effects` |
| 当前能力 | `current_api_endpoints`、`inline_script`、`upload_download`、`streaming_or_polling`、`api_gap` |
| 迁移去向 | `destination_class`、`target_screen_key`、`target_action_keys`、`target_panel_keys`、`wave` |
| 切换与回滚 | `legacy_url_policy`、`redirect_target`、`rollback_commit`、`graph_hash`、`compatibility_note` |
| 验收证据 | `unit_tests`、`api_contract_tests`、`playwright_uat`、`task_parity_status`、`observability_evidence` |
| 状态治理 | `status`、`owner`、`reviewer`、`last_reviewed_at`、`exception_expiry`、`notes` |

矩阵约束：

1. `template_path` 唯一，矩阵行数必须等于“当前物理模板数 + 已保留审计记录的 D 档删除数”，并与 inventory 脚本结果一致。
2. A/B/C/D 必须互斥且合计等于总数。
3. A/B `route_page` 必须有目标 screen、主任务、旧 URL 策略和 UAT。
4. C 档必须能展开匹配 §8 的路径、owner 与理由。
5. D 档必须有 loader origin/消费者检查证据和可恢复 commit。
6. API gap 未关闭、权限契约未确认或 UAT 未通过时，不得把状态标记为 `ready_for_cutover`。

## 11. 总完成定义

只有同时满足以下条件，本计划才算完成：

- [ ] §10 映射矩阵 A/B/C/D 互斥、合计与实际模板数一致，无悬空归属
- [ ] §8 保留清单以外的模板全部删除或迁入 TUI；`web_template_migration_inventory.py --require-finalized` 通过，剩余路径与 C 档精确文件清单一致
- [ ] 普通用户 8 步每日工作流与管理员治理任务全部在 TUI 内闭环，无 Classic 跳转依赖
- [ ] R0 actionability 通过：凡声明为表单/CRUD/治理/配置的迁移任务，均可在 TUI 内完成创建、填写、编辑、删除、审批、绑定或触发；不得仅以 GET/read smoke 或后台 action metadata 存在作为通过依据，并有行级参数映射、权限/确认、写后 receipt 与 affected-panel refresh 证据
- [ ] 每个迁移 route page 的主任务 UAT、权限、空态、错误态和旧 URL 策略均有证据
- [ ] TUI 全部契约/治理/JS/Playwright 检查绿，且 AGENTS.md 固定最小回归包绿
- [ ] 最终 graph 同时通过 AgomTradePro validator；涉及通用 schema/runtime 时也通过 AgomTUI 双端兼容门禁
- [ ] `legacy_screen_aliases` 完成清理，IA registry 无死别名
- [ ] 冻结条款从 AGENTS.md 移除，替换为"web 模板仅保留清单内可新增"的常态条款
- [ ] 发布与回滚证据包含 graph hash、schema version、runtime build id、registry generation 和对应 commit
- [ ] M5 唯一放行命令对最终候选版本返回 ALLOW，生产 registry 备份可恢复，owner 与独立 reviewer 的审批绑定同一证据快照
- [ ] 各 M5-B 清理 wave 完成约定的生产观察且没有触发停止线，所有低频例外均有 owner、独立 reviewer、到期日和复核结论
- [ ] 本计划归档至 `docs/archive/plans/` 并在 `docs/INDEX.md` 标记完成
