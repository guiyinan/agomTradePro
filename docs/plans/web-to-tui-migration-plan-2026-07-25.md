# Web 界面 → TUI 整体迁移计划（M0-M5）

> **文档日期**: 2026-07-25
> **最后修订**: 2026-07-28
> **状态**: 实施中；M0、M0-D、M1、M2、M3 与 M4 仓库实现已完成；M5 遥测、同任务错误率、机器 cutover gate、本地回滚演练与 108/108 主任务浏览器 UAT 已落地；候选稳定版本、14 日窗口、生产样本、缺陷窗口、生产 registry 备份与审批均未满足，当前禁止清理 Classic
> **适用对象**: 开发负责人 / 模块维护人 / AI 代理
> **主范围**: 以 M0 的 195 个 Django 模板为初始基线，持续盘点 `core/templates/` 与 `apps/*/templates/`，并把适合迁移的用户任务迁入 TUI 工作台（`/tui/`）；迁移期新增的共用兼容组件也必须进入同一台账
> **后端边界**: 默认保持业务语义不变；为补齐 TUI API 契约所需的 owner app 纵向切片允许纳入，但必须单独估算、提交和验收，不得把业务逻辑堆入 `terminal`
> **目标**: 普通用户与日常运维的主任务在 TUI 内完成；web 模板收敛为一份显式且可机器核对的保留清单；迁移全程可观测、可回滚、每批独立收口

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
6. **权限按角色和对象归属控制**。普通用户可以执行本人有权操作的 `write` action；`unsafe/admin` action 必须继续执行后端授权、确认、必要的重新认证与审计。前端隐藏不是权限边界。
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

### M2：第一批 A 类（表单/CRUD/配置）

| 项 | 内容 |
|---|---|
| 入口条件 | M0 完成；目标子批 API gap 已关闭；目标 screen/action 数量不突破 IA action-density 预算 |
| 范围 | account（资料/Token/用户管理/模拟账户）、policy（事件 CRUD、RSS 管理）、ai_provider（管理/配额/日志）、alpha_trigger、beta_gate、decision_rhythm 配额、rotation 配置、prompt、signal、backtest 配置；按“一个主任务 + 一个 owner app 子域”拆 wave，每个 wave 独立 commit 组和证据 |
| 单 wave 上限 | 默认不超过 3 个 route page 或 1 个复杂 CRUD 工作台；超出时必须在跟踪表说明无法继续拆分的原因 |
| 验收 | 每个目标 screen 满足设计标准；普通用户 write、admin/unsafe、确认、重新认证、对象归属与审计均有契约测试；写后刷新和 receipt 可见；旧页显示弃用提示与准确 deep link；最小回归包和该 app 的 API/浏览器任务测试全绿 |
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
| 在 DENY 状态下提前删除 Classic | CI 的 cleanup guard 固定放行 7 个已审 M0-D 基线；检测到任何新增 `deleted` 行时，必须属于 M5-B 且完整 checker 返回 ALLOW，否则 fail closed；任何人工叙述不得覆盖机器结果 |

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

## 9. 跟踪表

M2-M4 启动后按 wave 增行，不得只维护阶段汇总。

| 批次/wave | owner | 依赖 | 状态 | 规模（route/template/action） | graph/schema/runtime 证据 | 测试与 UAT | 未验证风险/回滚点 |
|---|---|---|---|---|---|---|---|
| M0 冻结与盘点 | terminal/governance | 计划批准 | 已完成 | 110 active route / 195 baseline template / 0 action | template manifest `e0057a7a…`；graph `92acf9e…`；runtime `agomtui-runtime-0.2.0+40a52d5a5e8f` | inventory 3 passed；证据见 `web-to-tui-m0-evidence-2026-07-26.md` | AgomTUI validator 的 R3 schema gap 已记录，M1 退出前必须关闭 |
| M0-D 死模板清理 | audit/account/data_center/macro | M0 定档 | 已完成 | 0 route / 7 deleted template / 0 action | 矩阵保留内容 hash、loader origin 与删除证据 | 93 passed（inventory、route、template、audit、data-center） | 删除提交 `d4d28e7168c83438eb708cddc4cf9e96ba616569` 已写入 7 条矩阵回滚记录 |
| M1 图表样板 | terminal/pulse + AgomTUI | M0、可移植性基线 | 已完成 | 1 route / 1 panel / 1 chart action | graph validator `f0946f38…`；runtime `agomtui-runtime-0.2.0+46a2e29a4e8d`；local registry matched | 上游 4 Python + 22 JS；下游 76 Python + 6 JS；三 viewport Playwright；证据见 `web-to-tui-m1-chart-evidence-2026-07-26.md` | M4 可复用 line chart；复杂图表按 M1 退出决策单独批准 |
| M2-W1 MCP 自助接入兼容切换 | account / ai_capability | M0、既有 MCP TUI 闭环 | 已完成 | 1 route / 1 retained compatibility template / 7 runtime actions | canonical screen `capability-router.self-service`；Classic 页发布准确 deep link | 8 focused tests；matrix check 通过 | Classic 页暂留以承接旧表单一次性 Token 展示；M5 再按访问量门槛移除 |
| M2-W2 MCP 管理员治理兼容切换 | account | M0、既有管理员 MCP API/TUI 闭环 | 已完成 | 1 route / 1 retained compatibility template / 6 runtime actions | canonical screen `capability-router.admin-access`；Classic 页发布准确 deep link | MCP API/TUI 既有契约 + Classic 定向集成测试；matrix check 通过 | Classic 页暂留兼容；退出仍受 14 日和访问量门槛约束 |
| M2-W3 用户准入治理 | account | M0、owner API gap | 已完成 | 1 route / 1 retained compatibility template / 5 runtime actions | runtime screen `identity-access.user-governance`；owner API 提供写后刷新回执 | 定向 API/页面/TUI 5 passed、IA 6 passed、TUI JS/Playwright 23 passed、mypy 0 regressions；完整证据见 `web-to-tui-m2-account-evidence-2026-07-26.md` | Classic 页暂留兼容；退出仍受 14 日和访问量门槛约束 |
| M2-W4 个人账户设置 | account | M0、profile/password/ledger API | 已完成 | 1 route / 1 retained compatibility template / 8 runtime actions | runtime screen `account.self-service`；新增 re-authenticated password owner API；通用 `password` field schema/runtime 双端兼容 | 定向 API/页面/TUI 3 passed、IA 6 passed、TUI JS/Playwright 24 passed、mypy 0 regressions | 真实 live-server 写入 UAT 待合并前补齐；Classic 页暂留兼容 |
| M2-W5 系统设置 | config_center / account compatibility | M0、config-center owner API | 已完成 | 1 route / 1 retained compatibility template / 2 runtime actions | runtime screen `system.settings`；config_center 显式 allowlist read/update API | 定向 Classic/API/TUI 3 passed、IA 6 passed、mypy 0 regressions | 真实 live-server 写入 UAT 待补；Classic 页暂留兼容 |
| M2-W6 Qlib 配置与训练 | config_center | M0、既有 Qlib owner API | 已完成 | 1 route / 1 retained compatibility template / 10 runtime actions | runtime screen `system.qlib-center`；Runtime/Universe/Profile/Run 任务归入专用管理员 screen | 上游页面/TUI 5 + IA 6 passed；下游 Python 70 + JS 6 passed；ruff/mypy/inventory/build 通过；证据见 `web-to-tui-m2-qlib-evidence-2026-07-26.md` | 真实 live-server 写入 UAT 待补；Classic 页暂留兼容 |
| M2-W7 Prompt 模板与链 | prompt | M0、owner CRUD/执行 API | 已完成 | 1 route / 1 retained compatibility template / 16 actions | runtime screen `prompt.workbench`；普通用户执行与管理员 CRUD 分层；模板 path ID 归一化；runtime bundle 自带 P0 reads；`screen + action + params` 深链按风险自动读取或定位表单 | Prompt API 24 + IA 6 + workbench 199 + JS 25 passed；固定其余包 11/22/2 passed；下游 JS 6 + Python 50 passed；ruff/mypy 通过；证据见 `web-to-tui-m2-prompt-evidence-2026-07-26.md` | 真实 live-server 创建→执行→日志 UAT 待补；Classic 页暂留兼容 |
| M2-W8 AI 服务商核心页 | ai_provider | M0、既有系统/个人 owner API | 已完成 | 3 routes / 3 retained compatibility templates / 14 scope-aware actions | `ai-ops.system-providers` 与 `ai-ops.providers`；补齐预算、故障切换、说明、扩展配置；API Key 使用 password；所有写入显式确认 | page 6 + API 16 + workbench 200 passed；static 407；ruff/mypy/inventory 通过；证据见 `web-to-tui-m2-ai-provider-evidence-2026-07-26.md` | 真实 live-server 创建/更新/连通性 UAT 待补；Classic 页暂留兼容 |
| M2-W9 AI 个人接入、配额与日志 | ai_provider | W8、个人日志筛选 gap | 已完成 | 3 routes / 3 retained compatibility templates / 14 role-aware actions | 个人服务商与日志归 `ai-ops.providers`，配额归 `ai-ops.user-quotas`，管理员日志归 `ai-ops.system-providers`；筛选参数保留且 owner 约束不变 | owner API + page 26 passed；TUI 定向 4、IA 6、上游 JS 25 passed；完整 workbench 200 passed；下游 JS/Python 6/70 passed；证据见 `web-to-tui-m2-ai-provider-evidence-2026-07-26.md` | 真实 live-server 日志筛选和配额写入 UAT 待补；Classic 页暂留兼容 |
| M2-W10 投资信号治理 | signal | M0、既有 Signal owner API、批量检查 gap | 已完成 | 1 route / 1 retained compatibility template / 8 runtime actions | `research.signals`；普通用户筛选，管理员创建/更新/审批/拒绝/证伪/删除/批量检查；所有 mutation 显式确认 | Signal API/page 20 + TUI 定向 1 + IA 6 passed；ruff/mypy/inventory/static 通过；证据见 `web-to-tui-m2-signal-evidence-2026-07-26.md` | 真实 live-server 创建→批准→批量检查→证伪 UAT 待补；Classic 页暂留兼容 |
| M2-W11 决策配额与趋势 | decision_rhythm | M0、既有配额 owner API、M1 portable chart | 已完成 | 2 routes / 2 retained compatibility templates / 4 runtime actions | `command-center.decision-flow`；认证用户查看配额/趋势，管理员更新/重置；补齐 Classic 与 API 权限边界；mutation 显式确认 | Decision Rhythm API 23 + guardrail 8 + TUI 定向 1 passed；ruff 通过；证据见 `web-to-tui-m2-decision-rhythm-evidence-2026-07-26.md` | 真实 live-server 筛选→趋势→更新→重置 UAT 待补；Classic 页暂留兼容 |
| M2-W12 回测研究闭环 | backtest / account | M0、既有 Backtest API、account 应用持仓 service | 已完成 | 3 routes / 3 retained compatibility templates / 7 runtime actions | `research.asset-lab`；统计/筛选/详情/运行/重跑/应用持仓/删除；完整 PIT/research 字段；补齐页面和 API 认证；mutation 显式确认 | Backtest API 原 7 + Classic 定向 1 + TUI 定向 1 + IA 6 passed；ruff/mypy 通过；证据见 `web-to-tui-m2-backtest-evidence-2026-07-26.md` | 完整 API 文件新增页用例首次因 fixture 无 session 失败，修正后通过；真实 live-server 全链路 UAT 待补；Classic 页暂留兼容 |
| M2-W13 Beta Gate 配置与测试 | beta_gate | M0、既有配置/评估/版本 API | 已完成 | 4 route templates / 5 route patterns / 4 retained compatibility templates / 8 runtime actions | `macro-regime.strategy`；认证用户评估/对比，管理员配置治理；不可变替代、软停用和回滚；补齐页面/API 权限；mutation 显式确认 | Beta Gate 权限定向 1 + TUI 定向 1 + IA 6 passed；ruff/mypy 通过；证据见 `web-to-tui-m2-beta-gate-evidence-2026-07-26.md` | 真实 live-server 创建→替代→测试→对比→回滚 UAT 待补；Classic 页暂留兼容 |
| M2-W14 轮动资产池治理 | rotation | M0、既有资产 CRUD/导入/行情 API | 已完成 | 1 complex route / 1 retained compatibility template / 8 runtime actions | `macro-regime.strategy`；读目录/行情，管理员 CRUD、预览后导入；原生 row actions 与表格导出 | Rotation page 1 + TUI 定向 1 + IA 6 passed；ruff/mypy/inventory/static 通过；证据见 `web-to-tui-m2-rotation-assets-evidence-2026-07-26.md` | live-server CRUD→预览→导入→导出 UAT 待补；Classic 页暂留 |
| M2-W15 轮动策略配置 | rotation | W14、既有配置 CRUD/启停/信号 API | 已完成 | 1 complex route / 1 retained compatibility template / 8 runtime actions | `macro-regime.strategy`；完整配置字段、管理员 CRUD/启停/信号生成、原生 row actions | Rotation permission 1 + TUI 定向 1 + IA 6 passed；ruff/mypy/inventory/static 通过；证据见 `web-to-tui-m2-rotation-configs-evidence-2026-07-26.md` | live-server 创建→编辑→启停→生成信号 UAT 待补；Classic 页暂留 |
| M2-W16 轮动信号与账户配置 | rotation | W15、既有信号与 user-scoped 账户配置 API | 已完成 | 2 routes / 2 retained compatibility templates / 11 runtime actions | `macro-regime.strategy`；信号质量/新鲜度/可执行性优先，账户配置 CRUD 与模板应用保持 owner scope | 跨用户隔离 1 + TUI 定向 1 + IA 6 passed；ruff/mypy/inventory/static 通过；证据见 `web-to-tui-m2-rotation-user-evidence-2026-07-26.md` | live-server 信号→账户配置→模板 UAT 待补；Classic 页暂留 |
| M2-W17 Alpha Trigger 读取与绩效 | alpha_trigger | M0、既有触发器/候选/绩效只读 API | 已完成 | 4 routes / 4 retained compatibility templates / 10 runtime actions | `research.signals`；curated 可操作候选作为 P0，保留证伪、风险、执行跟踪与绩效字段，原生 row detail | Alpha API 22 + TUI metadata 1 + TUI/IA 7 passed；ruff/mypy/inventory/static 通过；证据见 `web-to-tui-m2-alpha-trigger-read-evidence-2026-07-26.md` | 创建/编辑/证伪构建器仍有 mutation API gap；live-server UAT 待补；Classic 页暂留 |
| M2-W18 Alpha Trigger 生命周期与证伪 | alpha_trigger | W17、owner app mutation API gap | 已完成 | 3 routes / 3 retained compatibility templates / 9 runtime actions | `research.signals`；创建/编辑、Domain 状态转换、暂停/恢复/软取消、证伪检查、评估、候选生成与状态更新；全部显式确认 | API + Domain 49、TUI 生命周期 1、TUI/IA 7 passed；ruff/mypy/migration/inventory/static 通过；证据见 `web-to-tui-m2-alpha-trigger-lifecycle-evidence-2026-07-26.md` | live-server 全生命周期 UAT 待补；7 个 Alpha Classic route 均暂留兼容 |
| M2-W19 Policy 事件与审核 | policy | M0、既有事件与 workbench API | 已完成 | 3 routes / 3 retained compatibility templates / 9 curated runtime actions + 2 retained P0 actions | `policy.workbench`；事件查询/详情/管理员创建，工作台详情、批准/拒绝/回滚/豁免；理由必填动作保留完整确认表单 | Policy API/page/TUI/IA 29 passed；ruff/mypy/inventory/static 通过；证据见 `web-to-tui-m2-policy-events-evidence-2026-07-26.md` | live-server 审核全链路 UAT 待补；RSS 6 routes 下一 wave；Classic 页暂留 |
| M2-W20 Policy RSS 阅读与治理 | policy | W19、既有 RSS owner API、Reader API gap | 已完成 | 6 route templates / 8 route patterns / 6 retained compatibility templates / 15 runtime actions | `policy.workbench`；认证用户使用 bounded Reader，管理员治理 RSS 源、关键词与抓取日志；secret 字段使用 password 语义；抓取复用 task monitor | 定向 9 + Policy API 14 + RSS API 3 + Policy 集成契约 7 passed；ruff/mypy/inventory/static 通过；证据见 `web-to-tui-m2-policy-rss-evidence-2026-07-26.md` | live-server Reader→源/关键词 CRUD→抓取任务 UAT 待补；Classic 页暂留；2 个无独立路由的 Rotation 共享模板转 M5 随消费者清理 |
| M2 第一批 A 类 | 多 owner 分 wave | M0、API gap | 已完成（20 wave） | 43 route templates 已迁移并保留兼容入口 | 以各 wave 行为准 | 以各 wave 行为准 | M2 route-page backlog 清零；共享 layout/partial 不冒充独立任务，按消费者生命周期转入 M5 |
| M3-W21 Task Monitor 与 Readiness | task_monitor | M2、既有 Application page service、管理员 owner API gap | 已完成 | 2 routes / 2 retained compatibility templates / 10 runtime actions | `api-library.data-center`；有界计划任务目录、执行记录/详情/统计、Celery 健康、readiness 状态与调度、默认任务初始化；管理员写入显式确认 | Task Monitor API/page 20 + TUI/IA 7 + Workbench 212 passed；ruff/mypy/inventory/static 通过；证据见 `web-to-tui-m3-task-monitor-evidence-2026-07-26.md` | live-server 严格 readiness→调度更新→初始化 UAT 待补；Classic 页暂留 |
| M3-W22 文本情绪分析 | sentiment | M2、既有认证 owner API | 已完成 | 1 route / 1 retained compatibility template / 2 runtime actions | `research.signals`；5000 字 textarea、缓存开关、评分/置信度/分类/关键词结果与服务健康；分析 execute 显式确认 | Sentiment API/page/TUI/IA 17 passed；ruff/mypy 通过；证据见 `web-to-tui-m3-sentiment-evidence-2026-07-26.md` | live-server 分析成功/503 UAT 待补；Classic 页暂留 |
| M3-W23 旧 Terminal 命令配置退役 | terminal | M2、owner 已退役 legacy command API | 已完成 | 1 route redirected / 1 rollback template / 0 duplicate actions | 保留 staff 边界并跳转 `ai-ops.terminal + terminal.agent_chat`；不复活已明确 410 的命令 CRUD | legacy 410 + redirect 7 passed；ruff/mypy 通过；证据见 `web-to-tui-m3-terminal-config-evidence-2026-07-26.md` | live-browser redirect→chat UAT 待补；模板仅作 M5 前回滚工件 |
| M3-W24 多维资产筛选 | asset_analysis | M2、既有认证 owner API | 已完成 | 1 route / 1 retained compatibility template / 1 runtime action | `research.asset-lab`；仅发布后端真实支持的 equity/fund，保留 Regime/评分/风险过滤，原生 datagrid/export | Asset API 6 + TUI/IA 7 passed；ruff/mypy 通过；证据见 `web-to-tui-m3-asset-analysis-evidence-2026-07-26.md` | live-server equity/fund→空结果/错误→导出 UAT 待补；Classic 页暂留 |
| M3-W25 集中风控中心 | risk_center | M2、既有 owner API/runtime bundle | 已完成 | 1 route / 1 retained compatibility template / 12 existing runtime actions | `macro-regime.strategy`；全局底线、模板、账户策略、例外、交易前/投后检查、日报与确认写入；后端权限保持权威 | page/runtime/auto-advisor 7 passed；既有 Risk Center API 集成契约；证据见 `web-to-tui-m3-risk-center-evidence-2026-07-26.md` | live-server 风控全链路 UAT 待补；Classic staff 页暂留 |
| M3-W26 每日决策工作台 | decision / decision_rhythm | M2、既有 owner JSON API、证伪/刷新 TUI gap | 已完成 | 1 route / 1 retained compatibility template / 3 new + 既有决策 actions | `command-center.decision-flow`；汇总/推荐/冲突/计划/审批闭环，并补推荐刷新、系统证伪模板和 AI 证伪草稿；HTML Funnel partial 不冒充 JSON action | owner/page 11 + TUI/IA 7 + Workbench 214 passed；ruff/mypy/inventory/static 通过；证据见 `web-to-tui-m3-decision-workspace-evidence-2026-07-26.md` | live-server 全链路 UAT 和 telemetry 待补；7 个 HTML partial 转 M5 随消费者清理；Classic 页暂留 |
| M3-W27 Alpha 推理与 Qlib 数据运维 | alpha | M2、既有 staff/superuser owner API、模式覆盖 gap | 已完成 | 2 routes / 2 retained compatibility templates / 5 curated mutations + 2 reads | `research.signals`；staff 概览与 superuser 通用/组合/批量推理、Universe/组合数据刷新；复用 Alpha pool 真源 | owner API/page 59 + TUI/IA 8 passed；ruff/mypy 通过；证据见 `web-to-tui-m3-alpha-ops-evidence-2026-07-26.md` | live-server 202/409/Celery 状态 UAT 待补；共享 tabs 转 M5；Classic 页暂留 |
| M3-W28 Equity 估值修复配置 | equity | M2、既有 IsAdminUser 版本化配置 API | 已完成 | 1 complex route / 1 retained compatibility template / 8 runtime actions | `research.asset-lab`；版本列表/当前配置、完整 21 字段创建更新、激活/回滚/删除/清缓存；复用 Domain 默认值 | TUI/IA 7 + owner API 7 + route 1 passed；ruff/mypy 通过；证据见 `web-to-tui-m3-equity-config-evidence-2026-07-26.md` | live-server 全生命周期 UAT 待补；Classic 页暂留 |
| M3-W29 Equity 个股筛选 | equity | W28、既有 screen owner API、raw JSON 表单 gap | 已完成 | 1 complex route / 1 retained compatibility template / 1 runtime action | `research.asset-lab`；8 个扁平业务字段在 owner Interface 合并为 custom rule，8 列结果表；不把 Dashboard Alpha/data sync 虚报进本 wave | serializer/TUI/IA 8 + page/API 3 passed；ruff/mypy 通过；证据见 `web-to-tui-m3-equity-screen-evidence-2026-07-26.md` | live-server 空态/错误/长结果 UAT 待补；Dashboard Alpha 与数据修复由后续 owner wave 收口；Classic 页暂留 |
| M3-W30 Dashboard Alpha 排名与历史 | dashboard | W29、既有 Dashboard JSON/history API | 已完成 | 2 routes / 2 retained compatibility templates / 3 runtime actions | `research.signals`；通用/组合完整排名、五类历史筛选、用户范围 run 详情；显式 JSON 格式，不把 HTMX partial 冒充 API | TUI/IA 7 + owner page/API 7 passed；ruff/mypy 通过；证据见 `web-to-tui-m3-dashboard-alpha-evidence-2026-07-26.md` | live-server scope/隔离/长排名 UAT 待补；Dashboard partial 随主消费者收口；Classic 页暂留 |
| M3-W31 Factor 按配置计算与个股解释 | factor | W30、既有 Factor Application service、JSON owner API gap | 已完成 | 1 route / 1 retained compatibility template / 2 runtime actions | `research.asset-lab`；按已存配置 ID 计算和解释，只发布有界标量字段，不向用户暴露 `factor_weights` 原始 JSON | TUI/API 定向 5 + IA 6 passed；ruff/mypy 通过；证据见 `web-to-tui-m3-factor-calculate-evidence-2026-07-26.md` | live-server 计算/解释/空结果 UAT 待补；Factor layout 仍由后续两个页面消费；Classic 页暂留 |
| M3-W32 Factor 定义治理 | factor | W31、既有 Factor definition CRUD、输入领域约束 gap | 已完成 | 1 route / 1 retained compatibility template / 6 runtime actions | `research.asset-lab`；列表/详情/创建/局部更新/启停/删除，完整字段表单，Domain enum 选项与 owner serializer 同步校验 | owner/TUI 6 + IA 6 passed；ruff/mypy 通过；证据见 `web-to-tui-m3-factor-definitions-evidence-2026-07-26.md` | live-server CRUD/filter/冲突 UAT 待补；Factor layout 仍由 portfolios 消费；Classic 页暂留 |
| M3-W33 Factor 组合配置与逐项权重 | factor | W32、既有配置 CRUD/生成 API、raw JSON 权重 gap | 已完成 | 1 route / 1 retained compatibility template / 10 runtime actions | `research.asset-lab`；标量配置 CRUD、逐项设置/移除权重、启停和生成组合；三个选择集形成 Application 唯一真源 | owner/TUI/IA 17 + Workbench 221 passed；ruff/mypy/reverse/inventory/static 通过；证据见 `web-to-tui-m3-factor-portfolios-evidence-2026-07-26.md` | live-server 草稿→配权→启用→生成 UAT 待补；Factor layout 转 M5；Classic 页暂留 |
| M3-W34 Hedge 对冲治理 | hedge | W33、既有 Hedge owner API、角色可见性闭环 | 已完成 | 3 routes / 3 retained compatibility templates / 15 runtime actions | `macro-regime.strategy`；对冲对 CRUD/启停/有效性、快照/更新、告警/监控/解决；普通用户 7 个读算动作，管理员额外 8 个写动作 | owner API/IA 24 + TUI 1 passed；ruff/mypy 通过；证据见 `web-to-tui-m3-hedge-evidence-2026-07-26.md` | live-server 全链路 UAT 待补；Hedge layout/免责声明转 M5；Classic 页暂留 |
| M3-W35 Fund 基金研究 | fund | W34、既有 Fund owner API、嵌套 JSON TUI gap | 已完成 | 1 route / 1 retained compatibility template / 8 runtime actions | `research.asset-lab`；扁平多维筛选、排名、评分、风格、业绩、资料、净值与持仓；新增独立 typed TUI endpoint，不触碰旧嵌套契约 | owner API/TUI/IA 21 + Workbench 223 passed；ruff/mypy/inventory/static 通过；证据见 `web-to-tui-m3-fund-evidence-2026-07-26.md` | live-server 全链路 UAT 待补；AI 问答复用统一 Agent，不在 Fund 重复发布；Classic 页暂留 |
| M3-W36 Broker Execution 实盘执行与接入治理 | broker_execution | W35、既有 owner API、管理员接入 TUI gap | 已完成 | 1 shared route template / 7 route patterns / 33 runtime actions | `execution.accounts` / `execution.audit`；订单审批、对账、启停与 15 个接入治理动作；管理员 mutation 使用 preview/commit，凭证结果使用 `copyable_secret` | TUI/IA 9 + owner component 63 + Workbench 224 + inventory/static 5 passed；black/ruff/mypy/inventory/static 通过；证据见 `web-to-tui-m3-broker-execution-evidence-2026-07-26.md` | live-server Agent/QMT 与 preview/commit UAT 待补；手工交易 CSV 归 Audit owner；Classic 页暂留 |
| M3-W37 Simulated Trading 持仓、交易与巡检通知 | simulated_trading | W36、既有 owner API、通知 API gap | 已完成 | 3 routes / 3 retained compatibility templates / 4 runtime actions | `execution.accounts`；owner-scoped 持仓/交易、typed 通知 GET/PATCH；TUI 表格发布最多 8 个 P0 字段，邮箱使用有界列表 | TUI/API/IA 8 + owner API edge 10 + Workbench 225 + inventory/static 5 passed；black/ruff/mypy/inventory/static 通过；证据见 `web-to-tui-m3-simulated-trading-records-evidence-2026-07-26.md` | M4 图表页、live-server UAT 待补；Classic 页暂留 |
| M3-W38 Agent Runtime Operator | agent_runtime | W37、既有 Dashboard/Proposal API、跨用户列表与 operator visibility gap | 已完成 | 4 routes / 4 retained compatibility templates / 9 runtime actions | `ai-ops.terminal`；治理总览、任务/提案队列与详情、提交/批准/拒绝/执行；group-aware 可见性 + API 最终授权 | TUI/API/IA 8 + Dashboard/route 37 + Workbench 226 + inventory/static 5 passed；black/ruff/mypy/inventory/static 通过；证据见 `web-to-tui-m3-agent-runtime-operator-evidence-2026-07-26.md` | live-server 状态机/guardrail UAT 待补；2 partial 转 M5；Classic 页暂留 |
| M3-W39 Ops 导航与能力治理 | core / ai_capability | W38、既有 MCP TUI、语义批量 API 的 raw JSON gap | 已完成 | 4 routes / 4 retained compatibility templates / 4 new + 既有 MCP/自助 actions | `account.self-service` / `api-library.data-center` / `capability-router.mcp-center`；导航页按角色复用既有 screen；语义单条修正使用 typed flat adapter，apply 显式确认并审计；迁移提示 partial 已纳入冻结矩阵 | TUI/API/IA 8 + Semantic API 6 + owner pages 44 + Workbench 227 + inventory/static 5 passed；black/ruff/mypy/inventory/static 通过；证据见 `web-to-tui-m3-ops-hubs-evidence-2026-07-26.md` | live-server 角色跳转、Token/Prompt、MCP 开关和语义修正 UAT 待补；矩阵现为 196 templates / A131；Classic 页暂留 |
| M3-W40 Strategy 复合工作台 | strategy | W39、既有 owner REST API、版本语义与 raw condition JSON gap | 已完成 | 4 routes / 4 retained compatibility templates / 35 runtime actions | `macro-regime.strategy`；默认停用创建、版本化更新、四类可执行 typed 条件、脚本/AI/仓位配置、预览/执行/日志；owner scope + staff override；mutation 显式确认和审计 | TUI/IA 7 + typed API 2 + Strategy API 33 + page/structure 12 + Workbench 228 + inventory/static 5 passed；black/ruff/mypy/inventory/static 通过；证据见 `web-to-tui-m3-strategy-workbench-evidence-2026-07-26.md` | `technical` evaluator 未实现故不发布虚假创建动作；live-server 生命周期 UAT 待补；4 partial 转 M5；Classic 页暂留 |
| M3-W41 Audit 复盘、操作日志与决策链 | audit | W40、既有 owner-scoped 日志/决策链 API、HTML overview/report context gap | 已完成 | 6 routes / 6 retained compatibility templates / 10 runtime actions | `execution.audit`；新增认证限量概览与报告列表 read adapter；报告生成复用 preview/confirmed write；日志和决策链继续由 owner API按普通用户/管理员裁剪；管理员统计与 JSON 证据导出不向普通用户发布 | Audit API 9 + TUI/IA 1 + Classic 59 + Workbench 230 + inventory/static 5 passed；ruff/mypy 通过；证据见 `web-to-tui-m3-audit-review-evidence-2026-07-26.md` | live-server 权限/生成/导出 UAT 待补；Classic 页暂留 |
| M3-W42 Data Center 治理与数据运维 | data_center | W41、既有 admin owner API、HTML governance POST 与 nested thermometer config gap | 已完成 | 6 routes / 6 retained compatibility templates / 20 admin runtime actions | `api-library.data-center`；宏观治理 allow-list、Provider 列表/测试/健康、Publisher CRUD、Universe 配置/摘要、温度计配置/同步/重算与 CSV dry-run→确认导入；修正 Data Center 管理 read 的 audience | typed API/TUI 3 + owner 42 + Workbench 230 + inventory/static 5 passed；ruff/mypy 通过；证据见 `web-to-tui-m3-data-center-governance-evidence-2026-07-26.md` | live-server 管理全链路 UAT 待补；Classic 页暂留 |
| M3 第二批 A 类 | 多 owner 分 wave | M0、API gap | 已完成（22 wave） | 48 route templates 已迁移/重定向并保留兼容工件 | 以各 wave 行为准 | 全量 Workbench 230 + inventory/static 5 passed；M3 route-page backlog=0 | live-server UAT 与 telemetry 统一进入 M5 门禁；Classic 页暂留 |
| M4-W43 Audit 归因、指标绩效与阈值验证 | audit | M1 退出决策、W41 Audit 读写契约、既有 owner Application service | 已完成 | 3 routes / 3 retained compatibility templates / 12 runtime actions | `execution.audit`；schema/runtime 投影新增 `line`/`bar`/`pie` chart type；归因和指标使用 bar，阈值历史使用 line；管理员 preview/commit 写入继续由 owner API 授权并审计 | 定向 16 + owner 50 + Workbench 231 + inventory/static 5 passed；ruff/mypy 通过；证据见 `web-to-tui-m4-audit-analytics-evidence-2026-07-26.md` | live-server 图表/三 viewport/preview→commit UAT 待补；Classic 页暂留 |
| M4-W44 Audit 手动交易与决策分支复盘 | audit / account / backtest | W43、owner CSV 导入与回测用例、文本文件 runtime 边界 | 已完成 | 1 route / 1 retained compatibility template / 6 runtime actions | `execution.audit`；owner-scoped UTF-8 CSV preview/commit；四分支一次运行；通用 `table_chart` 同时投影净值曲线与指标表；Classic 保留 XLS/XLSX | 定向 5 + owner/inventory/static 27 + Workbench 233 passed；black/ruff/mypy 通过；证据见 `web-to-tui-m4-audit-manual-trade-evidence-2026-07-26.md` | live-server CSV、部分失败、三 viewport UAT 待补；XLS/XLSX 仍走 Classic；Classic 页暂留 |
| M4-W45 Account 资料与组合波动率 | account | W44、既有 Account profile API、波动率 Application use case | 已完成 | 1 route / 1 retained compatibility template / 3 runtime actions | `execution.accounts`；owner-scoped 资料、波动率摘要与 portable line chart；百分比边界舍入；无组合返回正常空态；账户/持仓复用 W37 | 定向 3 + owner/inventory/static 66 + Workbench 234 passed；black/ruff/mypy 通过；证据见 `web-to-tui-m4-account-overview-evidence-2026-07-26.md` | live-server 告警/空态/三 viewport UAT 待补；Classic 页暂留 |
| M4-W46 Dashboard 投资指挥摘要与组合图表 | dashboard | W45、既有 Dashboard Application facade、旧 allocation/performance auto action | 已完成 | 1 route / 1 retained compatibility template / 1 new + 2 replaced runtime actions | `command-center.overview`；P0 摘要；配置 pie、收益 line；复用既有 action key 消除同义任务；owner typed adapter | 定向 2 + owner/structure/inventory/static 33 + Workbench 235 passed；black/ruff/mypy 通过；证据见 `web-to-tui-m4-dashboard-overview-evidence-2026-07-26.md` | live-server pie/长序列/三 viewport UAT 待补；Classic 页暂留 |
| M4-W47 Macro / Regime 分析图表 | macro / regime | W46、既有 Macro snapshot / Regime dashboard 与 Navigator Application service、旧 Regime actions | 已完成 | 2 routes / 2 retained compatibility templates / 5 new + 2 replaced runtime actions | `macro-regime.overview`；Macro 指标目录/选中序列/风险时序；Regime 指定时点摘要、概率 pie、动量 line、联合历史 line；owner typed adapter；旧 Macro CRUD 不复活 | TUI API 7 + owner/root/route 77 + 定向 TUI 1 + Workbench 236 + inventory/static 5 passed；black/ruff/system check/mypy 通过；证据见 `web-to-tui-m4-macro-regime-analytics-evidence-2026-07-26.md` | live-server 指标切换/空态/长历史/三 viewport UAT 待补；Classic 页暂留 |
| M4-W48 Sentiment Dashboard | sentiment | W47、M3 文本分析与健康 action、canonical nested index API | 已完成 | 1 route / 1 retained compatibility template / 2 new + 2 reused runtime actions | `research.signals`；owner typed adapter 扁平化 index/source 对象；最新指数摘要与综合/新闻/政策三序列 line；输入越界明确 400 | API/TUI 13 + owner component 23 + 定向 TUI 1 + Workbench 236 + inventory/static 5 passed；black/ruff/system check/mypy 通过；证据见 `web-to-tui-m4-sentiment-dashboard-evidence-2026-07-26.md` | live-server 空态/长序列/tooltip/三 viewport UAT 待补；Classic 页暂留 |
| M4-W49 Macro 趋势滤波替代 | macro / filter | W48、Data Center canonical macro facts、共享扩张窗口 HP / 单向 Kalman、Filter 弃用契约 | 已完成 | 1 route / 1 retained compatibility template / 3 new runtime actions / 5 deprecated runtime actions pruned | `research.asset-lab`；Macro owner typed read adapter；原始值/长期趋势/周期/斜率 line；完整 freshness/decision-grade；只读不持久化；不新增 Filter 消费者 | Application/PIT 7 + TUI API 14 + Filter 兼容 37 + 定向 TUI 1 + Workbench 237 + inventory/static 5 passed；black/ruff/system check/mypy 通过；证据见 `web-to-tui-m4-macro-trend-filter-evidence-2026-07-26.md` | generated/published 旧 key 待后续治理批次删除；live-server 算法切换/空态/长序列/三 viewport UAT 待补；Classic 页暂留 |
| M4-W50 Equity 个股、股票池与估值修复图表 | equity | W49、既有 Equity owner API、池板块与百分位图表投影 gap | 已完成 | 3 routes / 3 retained compatibility templates / 13 runtime actions | `research.asset-lab`；估值、技术/日内/Regime 图表，股票池列表/板块 pie/确认刷新，估值修复列表/详情/百分位 line/确认扫描；只补两个向后兼容展示投影，不复制 Data Center/Pulse 任务 | owner API 45 + 定向 TUI 1 + Workbench 238 + inventory/static 5 passed；black/ruff/system check/mypy 通过；证据见 `web-to-tui-m4-equity-analytics-evidence-2026-07-26.md` | live-server 图表/刷新/扫描/空态/三 viewport UAT 待补；Classic 页暂留 |
| M4-W51 Simulated Trading 账户工作流 | simulated_trading / strategy | W50、既有 owner-scoped 账户/绩效/策略 API、IA P0 账户清单 gap | 已完成 | 4 routes / 4 retained compatibility templates / 10 new + 4 reused runtime actions | `execution.accounts`；账户列表/详情/创建/删除/批量删除、绩效、portable 净值 line、持仓/交易/巡检、策略选择与绑定；IA 增加 P0 账户清单；静态状态不冒充 runtime truth | owner API 56 + 定向 TUI/IA 7 + 固定其余回归 35 + Workbench 239 + inventory/static 5 passed；black/ruff/system check/mypy 通过；证据见 `web-to-tui-m4-simulated-accounts-evidence-2026-07-26.md` | 四页仅误引入未使用 Chart.js；live-server CRUD/绑定/净值/空态/三 viewport UAT 待补；Classic 页暂留 |
| M4 图表域 | 多 owner 分 wave | M1 退出决策 | 实现完成（9 wave） | 17/17 个 B 类 route template 已迁移，0 个 backlog | 以各 wave 行为准 | 当前全量 Workbench 239 + inventory/static 5 passed | M4 退出 live-server UAT 与 telemetry 统一进入 M5 门禁；Classic 页暂留 |
| M5 兼容期观测与清理收口 | terminal / governance + 各 owner | M4 实现完成、§3 量化退出门槛 | M5-A 取证中（机器判定 DENY，禁止清理） | 2026-07-28 生产仍运行不含当前矩阵的旧提交；候选尚未部署，观察未开始；复核日由机器窗口确定 | 有界 Classic/TUI telemetry、Classic Referer API 执行归因、14 日 task request 告警和机器 cutover gate 已实现；本地 reverse/restore + registry 回滚演练通过；cleanup guard 阻止 DENY 状态新增删除；registry 外部备份/校验/恢复工具和 payload-free attestation 生成器已落地；review snapshot 与 owner/reviewer 双签 attestation 工具已落地；完整浏览器套件 `15 passed`，累计覆盖 108/108 深链、71 个角色化直读 route、9 个参数化读取 route、策略/个人 AI 服务商生命周期、3 个 Policy 创建、5 个治理/筛选、11 个本地详情/生命周期 route 和 2 个受控外部 AI route；逐 route 旧 URL、兼容目标、角色边界、任务级空态和有界错误恢复完整套件 `8 passed`；33 个管理员/operator route、23 个纯登录 route、15 个 AI Provider/Simulated Trading/Strategy owner route、9 个 Audit/Risk Center/Ops/Signal/Terminal 混合边界 route、11 个共享研究 route 和最后 17 个业务后端授权 route 已共同完成 `permission` 108/108；列表、详情、图表空结果投影和浏览器渲染已完成 `empty_state` 108/108；真实 action runner HTTP 502/503、trace id、异常脱敏与原工作区恢复已完成 `error_state` 108/108；108 个 route 已由 3 个真实迁移提交补齐 rollback 映射 | 固定最小回归 278；M5 治理 74；rollback/registry integration 8；Workbench/compiler 290；TUI JS 28；metadata action smoke 380（ok 238 / needs input 142 / error 0）；inventory/static 通过；browser 15 passed；route closure 8 passed；empty projection 3 passed；error envelope 2 passed；Workbench 243 passed；Workbench browser 18 passed；owner/object permission 77 passed；特殊权限 73 passed；Audit 定向 5 passed；Capability Gateway 3 passed；共享研究契约 162 passed；最后权限两组 162 + 140 passed；矩阵证据快照 `bf7a6234…` | deep-link smoke 不冒充任务 UAT；gate 当前主任务 UAT `108/108`、逐 route 六类 scope 完全闭环 `108/108`、production telemetry `0/101`；生产 registry 备份尚未实际执行；并缺候选稳定版本、14 日完整窗口、P0/P1=0 证据与独立审批 |

> **2026-07-28 仓库收口复核**：提交差异架构扫描、工作树增量扫描和全仓架构扫描均为 0 boundary / 0 audit violations；迁移 inventory、telemetry catalog、cleanup guard、TUI runtime sync 与 `git diff --check` 通过。Equity / Task Monitor 第三方装饰器类型已在不改变运行时行为的前提下收窄，全仓 mypy 债务上限按真实下降收紧后复核通过（2108 errors / 478 files）。这些仓库检查不替代生产门禁，M5 仍保持 `DENY`。

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
- [ ] §8 保留清单以外的模板全部删除或迁入 TUI；剩余路径与 C 档精确文件清单一致
- [ ] 普通用户 8 步每日工作流与管理员治理任务全部在 TUI 内闭环，无 Classic 跳转依赖
- [ ] 每个迁移 route page 的主任务 UAT、权限、空态、错误态和旧 URL 策略均有证据
- [ ] TUI 全部契约/治理/JS/Playwright 检查绿，且 AGENTS.md 固定最小回归包绿
- [ ] 最终 graph 同时通过 AgomTradePro validator；涉及通用 schema/runtime 时也通过 AgomTUI 双端兼容门禁
- [ ] `legacy_screen_aliases` 完成清理，IA registry 无死别名
- [ ] 冻结条款从 AGENTS.md 移除，替换为"web 模板仅保留清单内可新增"的常态条款
- [ ] 发布与回滚证据包含 graph hash、schema version、runtime build id、registry generation 和对应 commit
- [ ] M5 唯一放行命令对最终候选版本返回 ALLOW，生产 registry 备份可恢复，owner 与独立 reviewer 的审批绑定同一证据快照
- [ ] 各 M5-B 清理 wave 完成约定的生产观察且没有触发停止线，所有低频例外均有 owner、独立 reviewer、到期日和复核结论
- [ ] 本计划归档至 `docs/archive/plans/` 并在 `docs/INDEX.md` 标记完成
