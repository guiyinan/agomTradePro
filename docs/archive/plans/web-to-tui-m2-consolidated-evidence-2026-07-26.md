# Web → TUI M2 合并证据（W1–W20，2026-07-26）

> **合并日期**: 2026-07-28
> **范围**: M2 已完成 wave 的实现、契约、验证与后续约束
> **来源**: 15 份原始 wave 证据无损合并；仅统一标题层级，原文件 SHA-256 见下表，完整历史保留在 Git

## 原始证据清单

| Wave | 原文件 | SHA-256 |
|---|---|---|
| W1/W2/W3/W4/W5 | `web-to-tui-m2-account-evidence-2026-07-26.md` | `262750bcea97580443b4d359b8e73f44d890b9e18395c3bc3144dab8d5efe51b` |
| W6 | `web-to-tui-m2-qlib-evidence-2026-07-26.md` | `b5404015aabcbddb5b1a14796cbeba4b91b9f0c9b7879ac7cf497fb77954ebb5` |
| W7 | `web-to-tui-m2-prompt-evidence-2026-07-26.md` | `234115ad11014403097fd387794b3f89c48b74cfeffca7ff92fe4b15a98ae695` |
| W8 | `web-to-tui-m2-ai-provider-evidence-2026-07-26.md` | `d1b933d123468cfef8cbf2859167b229eadd652d70772f7983a397f799f5b020` |
| W10 | `web-to-tui-m2-signal-evidence-2026-07-26.md` | `378cf67871112ca28dfc8bae7150c4fee245bb37c7494238cf1d66d090768e3f` |
| W11 | `web-to-tui-m2-decision-rhythm-evidence-2026-07-26.md` | `68ba2c5b9f90c04d1179f8750ba3c12ea9c80d6946d053616dd8399875ef83ee` |
| W12 | `web-to-tui-m2-backtest-evidence-2026-07-26.md` | `cd1d93b2221cd87419645b5cd167025664277fb687fe087756c530c61472c42a` |
| W13 | `web-to-tui-m2-beta-gate-evidence-2026-07-26.md` | `5cfae5fe1f6e375a6425cc097221564cebf2e0fcad01cb9c654a23e7de939e58` |
| W14 | `web-to-tui-m2-rotation-assets-evidence-2026-07-26.md` | `4d714bc0cba9de0e2a211853a24d10fdc9135f42917c2dc38bdb9ef05687e29f` |
| W15 | `web-to-tui-m2-rotation-configs-evidence-2026-07-26.md` | `438e2bf1337974371c33c3da9c22911e85d4f3def4e1e0d7bd3414d01472a7eb` |
| W16 | `web-to-tui-m2-rotation-user-evidence-2026-07-26.md` | `31b163a1419b2fbb200aa0f69c34120dc25f89d07eebeb523e35c8a7654bf42c` |
| W17 | `web-to-tui-m2-alpha-trigger-read-evidence-2026-07-26.md` | `142ea21f2e29f4816b1dbc0d86c75980a4d9f0f42729168d3306e32b6bc12339` |
| W18 | `web-to-tui-m2-alpha-trigger-lifecycle-evidence-2026-07-26.md` | `1dbf5735aa94a0f8c87d23783d5ecdef5c211dee327ea03a70d759ed1871046d` |
| W19 | `web-to-tui-m2-policy-events-evidence-2026-07-26.md` | `feb5c981b3bda01d0a4528fed9c9a9966ddabe146aa031b9dcdbe755e98954ea` |
| W20 | `web-to-tui-m2-policy-rss-evidence-2026-07-26.md` | `4f3838e210f2dabaeecac172ba40294ec738abc00072fb4b947eda458ba54806` |

## 合并正文

---

<!-- merged-from: web-to-tui-m2-account-evidence-2026-07-26.md; sha256: 262750bcea97580443b4d359b8e73f44d890b9e18395c3bc3144dab8d5efe51b -->

## Web → TUI M2 Account Waves 证据（2026-07-26）

### 范围

- M2-W1：个人 MCP 自助接入，目标 `capability-router.self-service`
- M2-W2：管理员 MCP 用户与令牌治理，目标 `capability-router.admin-access`
- M2-W3：用户审批、状态重置与角色治理，目标 `identity-access.user-governance`
- M2-W4：个人资料、密码、资金流水与交易成本，目标 `account.self-service`
- M2-W5：系统级准入、MCP、视觉、协议与映射设置，目标 `system.settings`

五个 Classic route page 继续保留兼容入口，均提供准确 TUI deep link；未提前执行 M5 删除。

### W3 纵向切片

- owner API：
  - `GET /api/account/admin/users/`
  - `POST /api/account/admin/users/<user_id>/approve/`
  - `POST /api/account/admin/users/<user_id>/reject/`
  - `POST /api/account/admin/users/<user_id>/reset/`
  - `POST /api/account/admin/users/<user_id>/role/`
- 权限：全部使用 DRF `IsAdminUser`；普通已认证用户返回 403。
- 写后回执：每次 mutation 返回 `success`、`message`、目标用户 ID 与刷新后的治理 payload。
- TUI：P0 用户队列、P1 治理回执；列表行提供批准、拒绝、重置入口，角色调整保留为显式 action 表单，避免从行数据误填目标角色。

### W4 纵向切片

- 复用 profile、capital-flow、trading-cost owner API，并新增 `POST /api/account/profile/password/`。
- 密码修改要求当前密码再次认证，并执行 Django 密码策略；错误当前密码返回 403。
- 通用 metadata/schema 新增 `input_type=password`，浏览器控件以 `type=password` 渲染且不把默认值写入 markup。
- Classic 账户设置页准确 deep link 到 `account.self-service`。

### W5 纵向切片

- 新增 config_center owner API：`GET/PUT /api/system/config-center/settings/`。
- 更新端点只接受显式 allowlist；用户协议、风险提示与两类运行时映射均保留结构化类型。
- 普通用户返回 403；管理员更新动作在 TUI 中要求确认。
- Classic 系统设置页准确 deep link 到 `system.settings`。

### 已验证

| 检查 | 结果 |
|---|---|
| 定向 API、权限、Classic deep link 与 TUI screen | 5 passed |
| 用户顺序任务：批准 → 改角色 → 重置 → 拒绝 | 通过 |
| 普通用户访问管理员 API | 403，通过 |
| IA registry / canonical runtime / dangling reference | 6 passed |
| TUI static source contracts | 407 rules / 5 sources，PASS |
| 浏览器任务：行操作 → mutation receipt → source panel refresh | TUI JS/Playwright 23 passed |
| W4 profile/password/TUI/Classic deep link | 3 passed |
| 通用密码控件 + 既有浏览器任务 | TUI JS/Playwright 24 passed |
| W5 Classic/API/TUI 定向契约 | 3 passed |
| Ruff | PASS |
| 增量 mypy（6 个生产 Python 文件） | 0 regressions |
| migration inventory refresh/check | 195 行；A=130、B=17、C=41、D=7，PASS |

### 尚待验证

- 真实 Django live-server 下的端到端浏览器写入；当前由真实 owner API 契约测试与 mock transport 的 Playwright 任务测试组合覆盖。
- AGENTS.md 固定 TUI 最小回归包将在 M2 account 子域收口时统一执行。
- Classic 入口删除受至少 14 天、稳定版本、访问量与回滚演练门槛约束；当前不能进入 M5。

### 回滚点

- owner API、TUI runtime screen/action、Classic compatibility banner 可按文件独立回滚。
- 删除 runtime screen 时必须同步移除 IA registry 项、identity-access 聚合与相关测试。

---

<!-- merged-from: web-to-tui-m2-qlib-evidence-2026-07-26.md; sha256: b5404015aabcbddb5b1a14796cbeba4b91b9f0c9b7879ac7cf497fb77954ebb5 -->

## Web → TUI M2 Qlib 配置与训练 Wave 证据（2026-07-26）

### 范围

- Wave：`M2-config-center-qlib-w6`
- Owner：`config_center`
- Classic 入口：`/settings/config-center/qlib/`
- TUI 入口：`/tui/?screen=system.qlib-center&action=config_center.qlib_runtime`
- 兼容策略：Classic 页面保留迁移提示和精确 deep link；未满足兼容期退出门槛前不删除模板或路由。

### 任务闭环

专用管理员 screen `system.qlib-center` 承接以下既有 owner API：

- 读取、更新 Qlib Runtime 配置；
- 列出、解析成员并保存 Alpha/Qlib 模型 Universe；
- 列出并保存训练模板；
- 列出、查看训练运行记录并触发训练。

首屏 P0 展示运行条件，P1 展示模型 Universe 与最近训练记录。Runtime 更新、Universe 保存、训练模板保存和触发训练均要求显式确认，后端继续执行管理员授权。

Qlib runtime bundle 还保证在小型/自定义 registry 中至少保留一个自带 P0 Universe action，避免依赖完整 published graph 的 Runtime action 时产生无 P0 panel 的无效 screen。

### 关键实现

- `apps/terminal/infrastructure/tui_metadata_runtime_injection_config_center.py`
  - 新增独立任务 screen 与 3 个 Universe action；
  - Universe 保存 action 增加写入 effect 与确认契约。
- `apps/terminal/infrastructure/tui_metadata_runtime_action_patch_config_center.py`
  - 将 7 个既有 Qlib 配置/训练 action 从泛化数据中心迁入专用 screen；
  - 为 3 个既有变更 action 增加确认契约。
- `config/tui/ia/tui_information_architecture.v1.json`
  - 把 `system.qlib-center` 登记为管理员 runtime screen。
- `apps/config_center/templates/config_center/qlib_center.html`
  - 增加兼容期提示与精确 TUI deep link。

### 验证

- `pytest tests/unit/terminal/test_tui_information_architecture.py -q -x`
  - `6 passed`
- `pytest tests/component/config_center/test_views.py -q -x`
  - `5 passed`
- `ruff check`（本 wave 修改的 Python 文件）
  - 通过
- `python scripts/check_mypy_regression.py`（4 个生产 Python 文件）
  - `0 regressions`
- `python scripts/web_template_migration_inventory.py --check`
  - `templates=195 route_pages=117 A=130 B=17 C=41 D=7`
- AgomTUI `sync_from_agomtradepro.py --apply/--check`
  - 所有通用 runtime/reference 文件一致，无额外漂移。
- AgomTUI Python packages（显式设置三个 `src` 目录的 `PYTHONPATH`）
  - `70 passed`
- AgomTUI `npm run check:runtime`、`npm run test:runtime-js`
  - build check 通过，`6 passed`
- 通用 task deep-link 契约
  - `screen + action + params` 已由浏览器用例验证；Qlib 兼容入口会直达并执行安全读取任务，写入/训练任务只定位而不会自动提交。

### 未验证风险与回滚点

- 通用 workbench 已有结构化表单、确认对话框和响应渲染的浏览器契约；本 wave 的真实 live-server 管理员写入 UAT 尚待 M2 合并前统一执行。
- Classic 页面仍处于兼容窗口，M5 删除受至少 14 天、稳定版本、访问量和无 P0/P1 阻断门槛约束。
- 回滚单位为专用 screen/action patch、IA runtime screen 登记、Classic banner 和矩阵记录；owner API 未在本 wave 改动。

---

<!-- merged-from: web-to-tui-m2-prompt-evidence-2026-07-26.md; sha256: 234115ad11014403097fd387794b3f89c48b74cfeffca7ff92fe4b15a98ae695 -->

## Web → TUI M2 Prompt 工作台 Wave 证据（2026-07-26）

### 范围

- Wave：`M2-prompt-workbench-w7`
- Owner：`prompt`
- Classic 入口：`/prompt/manage/`
- TUI 入口：`/tui/?screen=prompt.workbench&action=prompt-template.list`
- 兼容策略：Classic 页面保留迁移提示和精确 deep link，M5 门槛满足前不删除。

### 任务闭环

专用 `prompt.workbench` 把 16 个操作重组为一个复杂 CRUD 工作台：

- 模板：列表、分类、详情、新建、更新、删除和测试执行；
- 执行链：列表、执行模式、详情、新建、更新和删除；
- 记录：执行日志、最近日志和日志详情。

普通用户可查看模板/链并执行一次受确认约束的 AI 测试；模板和执行链的新增、更新、删除只对管理员展示，owner API 继续做最终授权。首屏 P0 是模板清单，P1 是执行链和最近执行记录。

该 runtime bundle 自带模板、执行链和最近记录的稳定只读 action，不依赖完整 published graph 才能满足 P0/default-action 契约；小型测试 registry、DB override 与重复 normalize/publish 也可保持有效。

### Owner API 收口

`PromptTemplateViewSet.execute` 现在以 URL path 中的模板 ID 为唯一真源，并在 Interface 层注入请求 DTO。调用者不再需要在路径和 JSON body 中重复提交同一 ID；对象存在性、认证和执行用例不变。

### 验证

- `pytest tests/unit/terminal/test_tui_information_architecture.py -q -x`
  - `6 passed`
- `pytest tests/api/test_prompt_api_edges.py -q`
  - `24 passed`
  - 覆盖 Classic deep link、普通用户/管理员 action 可见性、确认契约和 path-ID 执行。
- `ruff check`（本 wave 修改的 Python 文件）
  - 通过
- `python scripts/check_mypy_regression.py`（5 个生产 Python 文件）
  - `0 regressions`
- `python scripts/web_template_migration_inventory.py --check`
  - `templates=195 route_pages=117 A=130 B=17 C=41 D=7`
- AGENTS.md 固定最小回归包
  - `tests/unit/test_tui_workbench.py`: `199 passed`
  - `tests/unit/test_terminal_agent_service.py`: `11 passed`
  - `sdk/tests/test_sdk/test_client.py`: `22 passed`
  - `tests/unit/test_internal_ssl_redirect.py`: `2 passed`
- `npm run test:tui-js`
  - `25 passed`
  - 覆盖 `screen + action + params` 深链：安全只读在必填参数齐备时自动执行，写入任务只预填并聚焦，密码/文件参数不从 URL 注入。
- AgomTUI 同步验证
  - `sync_from_agomtradepro.py --apply` 与 `npm run check:runtime` 通过；
  - downstream runtime JS `6 passed`，core/compiler Python `50 passed`。

### 未验证风险与回滚点

- 通用 workbench 的结构化 JSON/list 字段、确认对话框和写后回执已有浏览器契约；本 wave 的真实 live-server 模板创建→执行→日志刷新任务流待 M2 合并前统一执行。
- Classic 页面仍受至少 14 天、稳定版本、旧入口占比和无 P0/P1 阻断的退出门槛约束。
- 回滚单位为 runtime screen/actions、read-action routing patch、path-ID Interface 归一化、Classic banner 与矩阵记录。

---

<!-- merged-from: web-to-tui-m2-ai-provider-evidence-2026-07-26.md; sha256: d1b933d123468cfef8cbf2859167b229eadd652d70772f7983a397f799f5b020 -->

## Web → TUI M2 AI Provider Wave 证据（2026-07-26）

### M2-ai-provider-core-w8

- Owner：`ai_provider`
- Classic route：`/ai/`、`/ai/detail/<provider_id>/`、
  `/ai/detail/<provider_id>/edit/`
- TUI screen：管理员使用 `ai-ops.system-providers`；个人服务商使用
  `ai-ops.providers`
- 兼容策略：三个 Classic 页面保留带任务参数的 scope-aware deep link，
  M5 退出门槛满足前不删除路由或模板。

### 任务闭环

管理员可在 `ai-ops.system-providers` 完成总体状态、列表、详情、创建、
更新、启停、连通性测试、用量检查和删除。普通用户在
`ai-ops.providers` 完成本人服务商的列表、详情、创建、更新、启停和
删除，owner API 继续执行对象归属与管理员权限校验。

本 wave 补齐了 Classic 编辑表单已有但 TUI 未声明的字段：

- 共用：故障切换、说明和结构化扩展配置；
- 系统服务商：每日和每月预算；
- API Key：统一使用 `password` input，不进入 URL 预填或可见 markup。

所有非 GET action 现在发布明确 `effect` 和
`confirmation_required=true`。带完整参数的 GET deep link 可以自动读取；
写入 deep link 只展开、预填非敏感字段并聚焦，不自动提交。

### 验证

- `tests/component/test_ai_provider_page_views.py`：`6 passed`
  - 覆盖管理员入口，以及个人/系统详情与编辑的 scope-aware deep link。
- `tests/api/test_ai_provider_api_edges.py`：`16 passed`
  - 覆盖系统/个人 owner API、对象归属、密钥掩码、配额与连通性。
- `tests/unit/test_tui_workbench.py`：`200 passed`
  - 覆盖 action 可见性、确认契约、完整字段集和密码字段。
- `python scripts/web_template_migration_inventory.py --check`
  - `templates=195 route_pages=117 A=130 B=17 C=41 D=7`
- `python scripts/check_tui_static_contracts.py`
  - `407 rule(s), 5 source(s)`
- `npm run test:tui-js`：`25 passed`。
- AgomTUI 同步、build check、runtime JS `6 passed`、Python `70 passed`。
- `ruff check`：通过。
- 增量 mypy：`0 regressions`。

### 未验证风险与回滚点

- 真实 live-server 的创建、更新、连通性测试与写后刷新 UAT 待 M2 合并前
  与其他 wave 一起执行。
- Classic 页面仍受至少 14 天、稳定版本、旧入口访问量和无 P0/P1 阻断
  门槛约束。
- 回滚单位为 AI Provider runtime metadata、通用 deep-link 行为、三个
  Classic banner 与矩阵记录；owner API 本 wave 未改变。

### M2-ai-provider-access-w9

- Classic route：`/ai/me/`、`/ai/quotas/`、`/ai/logs/`
- TUI screen：`ai-ops.providers`、`ai-ops.user-quotas`、
  `ai-ops.system-providers`
- 兼容策略：三个 Classic 页面保留 role-aware deep link，并把已验证的
  provider、status、limit 筛选参数带入 TUI。

个人服务商页对应 8 个本人 action；配额页对应列表、详情、单用户更新和
批量下发；日志页按角色分别进入 `ai-ops.my-ai-logs` 或新增的
`ai-ops.system-ai-logs`。个人日志 owner API 补上 `provider` 筛选参数，
并继续用当前用户约束查询，因此传入其他用户的 provider ID 只会得到空
结果，不会越权返回数据。

W9 验证：

- owner API + Classic 页面：`26 passed`；
- TUI AI Provider/角色可见性定向用例：`4 passed`（另有 196 deselected）；
- W8 完整 workbench 回归：`200 passed`。
- IA `6 passed`，上游 TUI JS `25 passed`，下游 JS/Python `6/70 passed`。

W9 的 live-server 日志筛选、单用户配额更新和批量下发 UAT 仍待 M2 合并
前统一执行。回滚单位为个人日志筛选参数、系统日志 action/panel、三个
Classic banner 与矩阵记录。

---

<!-- merged-from: web-to-tui-m2-signal-evidence-2026-07-26.md; sha256: 378cf67871112ca28dfc8bae7150c4fee245bb37c7494238cf1d66d090768e3f -->

## Web → TUI M2 Signal Wave 证据（2026-07-26）

### 范围

- Wave：`M2-signal-management-w10`
- Owner：`signal`
- Classic route：`/signal/manage/`
- TUI：`/tui/?screen=research.signals&action=signal.list`
- 兼容策略：Classic 页面保留精确任务链接，M5 门槛满足前不删除。

### 任务闭环

普通用户可在 `research.signals` 按状态、资产类别、方向和关键词筛选信号，
并继续使用既有活跃信号、统计和候选面板。管理员额外获得创建、更新、
批准、拒绝、证伪、删除和批量证伪检查任务。

创建 action 强制提交投资逻辑和量化证伪逻辑，owner serializer 继续校验
资产类别、方向、目标环境、文本长度和可量化关键字。资产类别没有复制成
TUI 硬编码枚举，而是以文本输入进入 owner API 的运行时目录校验。

所有管理员 mutation 都发布 `audience=admin`、明确 `effect` 和
`confirmation_required=true`。新增 `/api/signal/batch-check/` 只是把既有
Application 批量证伪用例暴露为受 `IsAdminUser` 保护的 owner API，没有
在 Interface 层复制业务规则。

### 验证

- `tests/api/test_signal_api_edges.py`：`20 passed`
  - 覆盖列表/详情、角色授权、审批/证伪、批量检查 API 与 Classic deep link。
- TUI Signal 定向用例：`1 passed`（200 deselected）
  - 覆盖普通用户只读、管理员动作、确认契约与必填证伪字段。
- IA：`6 passed`。
- inventory：`templates=195 route_pages=117 A=130 B=17 C=41 D=7`。
- static contracts：`407 rule(s), 5 source(s)`。
- ruff 与增量 mypy：通过，`0 regressions`。

### 未验证风险与回滚

- 真实 live-server 的创建→批准→批量检查→证伪状态刷新任务流待 M2 合并前
  统一 UAT。
- Classic 页面仍受至少 14 天、稳定版本、访问量和无 P0/P1 阻断门槛约束。
- 回滚单位为 Signal runtime actions、batch-check Interface action、Classic
  banner 与矩阵记录。

---

<!-- merged-from: web-to-tui-m2-decision-rhythm-evidence-2026-07-26.md; sha256: 68ba2c5b9f90c04d1179f8750ba3c12ea9c80d6946d053616dd8399875ef83ee -->

## Web → TUI M2 Decision Rhythm Wave 证据（2026-07-26）

### 范围

- Wave：`M2-decision-rhythm-w11`
- Owner：`decision_rhythm`
- Classic routes：`/decision-rhythm/quota/`、`/decision-rhythm/config/`
- TUI：
  - `/tui/?screen=command-center.decision-flow&action=decision-rhythm.quota-list`
  - `/tui/?screen=command-center.decision-flow&action=decision-rhythm.quota-update`
- 兼容策略：Classic 页面保留精确任务链接，M5 门槛满足前不删除。

### 任务闭环

`command-center.decision-flow` 新增配额列表和趋势面板。普通登录用户可按账户、
周期查看配额，并通过 M1 的 portable chart 查看 7 日或 30 日决策使用趋势。
管理员额外获得配额更新和用量重置任务。

四个稳定 runtime action 均调用 `decision_rhythm` owner API。更新和重置动作发布
`audience=admin`、明确 `effect=update` 和 `confirmation_required=true`，没有在
TUI runtime 复制配额业务规则。

本 wave 同时修复迁移核对中发现的权限漂移：

- 配额 Classic 页改为登录后可访问；
- 配置 Classic 页改为仅管理员可访问；
- 配额列表和趋势 API 要求认证；
- 配额更新与重置 API 仅允许管理员。

### 验证

- `tests/api/test_decision_rhythm_api_edges.py`：`23 passed`
  - 覆盖读写权限、管理员参数校验、重置作用域与 Classic 精确 deep link。
- `tests/guardrails/test_decision_rhythm_api_error_mapping.py`：`8 passed`。
- TUI Decision Rhythm 定向用例：`1 passed`（201 deselected）
  - 覆盖 datagrid、portable chart、管理员 audience 与确认契约。
- ruff：通过。

### 未验证风险与回滚

- 真实 live-server 的“筛选配额 → 查看趋势 → 更新 → 重置 → 面板刷新”任务流待
  M2 合并前统一 UAT。
- Classic 页面仍受至少 14 天、稳定版本、访问量和无 P0/P1 阻断门槛约束。
- 回滚单位为 Decision Rhythm runtime bundle、IA 面板、API/page 权限、Classic
  banner 与矩阵记录。

---

<!-- merged-from: web-to-tui-m2-backtest-evidence-2026-07-26.md; sha256: cd1d93b2221cd87419645b5cd167025664277fb687fe087756c530c61472c42a -->

## Web → TUI M2 Backtest Wave 证据（2026-07-26）

### 范围

- Wave：`M2-backtest-w12`
- Owner：`backtest`，应用持仓 mutation 由 `account` owner 承接
- Classic routes：`/backtest/`、`/backtest/create/`、`/backtest/<id>/`
- TUI：`research.asset-lab` 的 `backtest.summary`、`backtest.list`、
  `backtest.detail`、`backtest.run` 等任务
- 兼容策略：三张 Classic 页面保留精确任务 deep link，M5 门槛满足前不删除。

### 任务闭环

登录用户可查看统计和筛选后的回测列表，通过原生 row actions 查看详情、重跑或删除，
也可运行探索性/PIT 验证回测，并把结果按缩放因子应用到自己的持仓。运行表单覆盖
owner serializer 的可信度、数据清单、配置哈希、代码提交、引擎版本、研究试验和决策
快照字段，没有用简化表单丢失研究可复现性信息。

运行、重跑、应用持仓和删除均声明 effect 并要求确认。应用持仓补充
`/api/account/backtests/<id>/apply/` 路由，继续复用既有 account Application service；
TUI 不调用非 `/api/` 页面路径，也不复制持仓业务逻辑。

迁移核对同时关闭了历史认证漂移：三个 Classic 页面、Backtest ViewSet 和独立统计
入口现在均要求认证。

### 验证

- `tests/api/test_backtest_api_edges.py`：原 7 个用例通过；新增 Classic deep-link 用例
  `1 passed`，完整文件首次回归仅因测试客户端未建立 Django session 失败，修正 fixture
  后定向通过。
- TUI Backtest 定向用例：`1 passed`（202 deselected）。
- IA：`6 passed`。
- ruff 与增量 mypy：通过，`0 regressions`。

### 未验证风险与回滚

- 真实 live-server 的“创建 → 查看进度/详情 → 应用持仓 → 重跑/删除”任务流待 M2
  合并前统一 UAT。
- Backtest 历史存储仍采用既有共享研究结果口径；本 wave 不改变数据所有权模型。
- Classic 页面仍受至少 14 天、稳定版本、访问量和无 P0/P1 阻断门槛约束。
- 回滚单位为 Backtest runtime bundle、IA panel、认证装饰器/API permission、account
  API alias、Classic banner 与矩阵记录。

---

<!-- merged-from: web-to-tui-m2-beta-gate-evidence-2026-07-26.md; sha256: 5cfae5fe1f6e375a6425cc097221564cebf2e0fcad01cb9c654a23e7de939e58 -->

## Web → TUI M2 Beta Gate Wave 证据（2026-07-26）

### 范围

- Wave：`M2-beta-gate-w13`
- Owner：`beta_gate`
- Classic routes：配置列表、创建/编辑、资产测试、版本对比四类入口
- TUI：`macro-regime.strategy` 的配置目录、配置详情、创建、不可变替换、停用、
  资产测试、版本对比和回滚任务
- 兼容策略：Classic 页面保留精确任务 deep link，M5 门槛满足前不删除。

### 任务闭环

普通登录用户可以运行无持久化的批量 Beta Gate 评估并比较配置版本。管理员可查看
完整配置目录，创建配置，以不可变替代版本语义更新，软停用或回滚历史版本。
配置列表发布原生 row actions；所有管理 mutation 和资产评估均声明 effect 并要求确认。

迁移核对同时关闭了历史权限漂移：配置 Classic 页面和 JSON 建议 API 改为 staff-only，
测试/版本页面、决策历史和可见性宇宙改为 authenticated。

### 验证

- 新增权限定向 API/page 用例：`1 passed`。
- TUI Beta Gate 定向用例：`1 passed`（203 deselected）。
- IA：`6 passed`。
- ruff 与增量 mypy：通过，`0 regressions`。

### 未验证风险与回滚

- 真实 live-server 的“创建 → 替代版本 → 资产测试 → 对比 → 回滚/停用”任务流待
  M2 合并前统一 UAT。
- Classic 页面仍受至少 14 天、稳定版本、访问量和无 P0/P1 阻断门槛约束。
- 回滚单位为 Beta Gate runtime bundle、IA panel、页面/API 权限、Classic banner 与矩阵。

---

<!-- merged-from: web-to-tui-m2-rotation-assets-evidence-2026-07-26.md; sha256: 4d714bc0cba9de0e2a211853a24d10fdc9135f42917c2dc38bdb9ef05687e29f -->

## Web → TUI M2 Rotation Assets Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M2-rotation-assets-w14`；Classic route：`/rotation/assets/`。
- TUI：`macro-regime.strategy` 的资产列表、详情、行情、创建、更新、软/硬删除、
  默认资产导入预览和确认导入。
- 管理 mutation 均为 admin audience、显式 effect 与确认；导入强制提供只读预览任务。
- Classic 页面和旧生成信号入口改为 staff-only；普通用户仍可通过认证 API 读取目录。
- TUI 表格支持 F8 导出，owner JSON/CSV 下载端点在兼容期继续保留。

### 验证与风险

- TUI 定向 `1 passed`（204 deselected）；IA `6 passed`。
- Classic staff 边界 `1 passed`；既有 Rotation API 已覆盖 CRUD、软删除和导入差异。
- ruff、增量 mypy、inventory/static contract 通过。
- 真实 live-server CRUD→预览→导入→导出 UAT 待 M2 合并前补齐；Classic 页暂留。

---

<!-- merged-from: web-to-tui-m2-rotation-configs-evidence-2026-07-26.md; sha256: 438e2bf1337974371c33c3da9c22911e85d4f3def4e1e0d7bd3414d01472a7eb -->

## Web → TUI M2 Rotation Configs Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M2-rotation-configs-w15`；Classic route：`/rotation/configs/`。
- TUI：全局配置列表/详情/创建/更新/删除/启用/停用/生成信号。
- 表单覆盖 owner serializer 的资产池、策略参数、权重、换手率、回溯周期、
  象限配置、动量周期和 top_n，不使用简化 payload。
- 全局配置读操作要求认证；所有 mutation 与持久化信号生成要求管理员并显式确认。

### 验证与风险

- TUI 定向 `1 passed`（205 deselected）；IA `6 passed`。
- 管理员边界定向 `1 passed`；ruff、增量 mypy、inventory/static contract 通过。
- 真实 live-server 创建→编辑→启停→生成信号 UAT 待 M2 合并前补齐。
- Classic 页面暂留；账户级轮动配置继续作为独立 user-scoped wave。

---

<!-- merged-from: web-to-tui-m2-rotation-user-evidence-2026-07-26.md; sha256: 31b163a1419b2fbb200aa0f69c34120dc25f89d07eebeb523e35c8a7654bf42c -->

## Web → TUI M2 Rotation User Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M2-rotation-user-w16`；Classic routes：`/rotation/signals/`、
  `/rotation/account-configs/`。
- TUI 信号任务：列表、最新信号与详情；首屏保留数据质量、新鲜度、
  可执行性和阻断原因，避免用户把过期或低质量信号当成执行依据。
- TUI 账户任务：我的配置列表/详情/按账户查询/创建/更新/删除/应用模板，
  并提供模板列表；写操作均要求登录、显式确认并在写后刷新。
- 所有账户配置查询和 mutation 继续通过 owner API 按
  `request.user` 的账户范围过滤，不允许用路径 ID、请求体 account ID 或模板操作
  越权访问其他用户配置。

### 验证与风险

- TUI 定向 `1 passed`（206 deselected）；IA `6 passed`。
- 跨用户 mutation 隔离定向 `1 passed`；越权创建被验证为 `400/403`，
  越权更新、应用模板和删除均保持不可见语义。
- ruff、增量 mypy、inventory 与 static contract 均通过。
- 真实 live-server 信号筛选→查看质量→账户配置 CRUD→应用模板 UAT 待
  M2 合并前补齐。
- 两个 Classic 页面暂留兼容；后续移除仍受 M5 的 14 日稳定窗口、
  访问量与回滚门槛约束。

---

<!-- merged-from: web-to-tui-m2-alpha-trigger-read-evidence-2026-07-26.md; sha256: 142ea21f2e29f4816b1dbc0d86c75980a4d9f0f42729168d3306e32b6bc12339 -->

## Web → TUI M2 Alpha Trigger Read Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M2-alpha-trigger-read-w17`；Classic routes：触发器/候选总览、
  触发器详情、候选详情和绩效复核，共 4 个 route templates。
- TUI：发布 10 个稳定业务 action，覆盖触发器列表/活跃项/详情、
  候选列表/可操作项/观察列表/详情，以及触发器统计、候选统计和绩效。
- `research.signals` 的默认任务和 P0 panel 改为 curated
  `alpha-trigger.candidate-actionable`，候选行可原生进入详情；不再把自动生成的
  API action key 作为用户入口真源。
- 候选视图保留风险等级、预期收益和执行跟踪；触发器详情保留触发条件、
  证伪条件、有效期和生命周期状态。
- 7 个 Alpha Trigger Classic page 均补齐登录保护；本 wave 的 4 个页面发布
  精确 TUI 兼容入口。

### 验证与风险

- Alpha Trigger API `22 passed`；Classic 登录边界包含其中 `4 passed`。
- TUI metadata 定向 `1 passed`；TUI 页面定向与 IA 合计 `7 passed`。
- ruff、增量 mypy、inventory 与 static contract 均通过。
- 真实 live-server 候选筛选→行详情→触发器详情→绩效窗口 UAT 待 M2
  合并前补齐。
- 创建、编辑和证伪规则构建器保留在下一 lifecycle-authoring wave；其
  Classic 页面暂留，不能在 mutation API gap 关闭前宣称任务等价。

---

<!-- merged-from: web-to-tui-m2-alpha-trigger-lifecycle-evidence-2026-07-26.md; sha256: 1dbf5735aa94a0f8c87d23783d5ecdef5c211dee327ea03a70d759ed1871046d -->

## Web → TUI M2 Alpha Trigger Lifecycle Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M2-alpha-trigger-lifecycle-w18`；Classic routes：创建、编辑和
  证伪规则构建器，共 3 个 route templates。
- TUI：发布 9 个确认型 mutation，覆盖创建、编辑、暂停、恢复、软取消、
  证伪检查、触发评估、候选生成和候选状态更新。
- 原 Classic 页调用但后端缺失的 PATCH、暂停、恢复和 DELETE 契约已补齐；
  DELETE 使用 `CANCELLED` 软取消语义，保留审计历史。
- 生命周期允许关系下沉 Domain；Application 用例负责校验和编排；
  Infrastructure repository 持久化完整可编辑状态，Interface 只做输入输出。
- ORM 增加 `PAUSED` 状态及迁移
  `0004_alter_alphatriggermodel_status.py`；`makemigrations --check --dry-run`
  无漂移。
- 证伪条件以 typed JSON list 合并进创建/编辑任务，独立构建器不再成为
  完成主任务的必经页面；硬编码指标示例没有提升为运行时真源。

### 验证与风险

- Alpha Trigger API + Domain `49 passed`；新增生命周期/TUI 定向 `4 passed`。
- TUI 页面定向与 IA `7 passed`。
- ruff、增量 mypy、migration drift、inventory 与 static contract 均通过。
- 真实 live-server 创建→编辑→暂停→恢复→证伪检查→候选生成→软取消 UAT
  待 M2 合并前补齐。
- Alpha Trigger 7 个 Classic route templates 均已具备 TUI 任务等价入口，
  但仍受 M5 的 14 日稳定窗口、访问量和回滚门槛约束，当前不删除。

---

<!-- merged-from: web-to-tui-m2-policy-events-evidence-2026-07-26.md; sha256: feb5c981b3bda01d0a4528fed9c9a9966ddabe146aa031b9dcdbe755e98954ea -->

## Web → TUI M2 Policy Events Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M2-policy-events-w19`；Classic routes：政策事件列表、政策事件创建、
  政策工作台，共 3 个 route templates。
- TUI 新增 9 个 curated action：事件列表/详情/创建、工作台 bootstrap/详情，
  以及批准、拒绝、回滚、临时豁免；复用既有
  `policy.queue_summary` 与 `policy.workbench_items` 作为 P0 入口。
- 事件创建 API 与 Classic 页面统一为 staff-only；普通认证用户继续按既有
  协作模型查看工作台并执行审核动作。
- P0 待处理表格发布原生详情和批准 row action。拒绝、回滚、豁免必须填写
  理由，因此保留为完整确认表单，避免无理由一键写入。
- 事件列表保留日期范围、政策档位、说明和证据链接；详情保留来源、AI 分析、
  闸门状态、审核记录与资产范围。

### 验证与风险

- Policy API、页面权限、TUI metadata 与 IA 合计 `29 passed`。
- ruff、增量 mypy、inventory 与 static contract 均通过。
- 真实 live-server 日期筛选→详情→批准/拒绝→回滚/豁免 UAT 待 M2 合并前
  补齐。
- Policy RSS 源、关键词、Reader 和抓取日志共 6 个 route templates 留给
  下一独立 wave；本 wave 没有混入外部采集配置。

---

<!-- merged-from: web-to-tui-m2-policy-rss-evidence-2026-07-26.md; sha256: 4f3838e210f2dabaeecac172ba40294ec738abc00072fb4b947eda458ba54806 -->

## Web → TUI M2 Policy RSS Wave 证据（2026-07-26）

### 范围与闭环

- Wave：`M2-policy-rss-w20`；覆盖 RSS 源、源表单、关键词、关键词表单、抓取日志和
  Reader，共 6 个 route templates、8 个 Classic route patterns。
- `policy.workbench` 新增 15 个 runtime action：认证用户使用 Reader；管理员治理
  RSS 源、关键词和抓取日志，并可触发单源或全量抓取。
- 新增 `/api/policy/rss/reader/` 认证只读切片。接口复用 Policy Application
  page service，支持来源、档位、类别和分页筛选，单次最多返回 200 行，不把 ORM
  模型暴露到 Interface/Application 边界。
- RSS 源、关键词和抓取日志 Classic 页面统一为 staff-only；Reader 保持
  login-required，未把普通阅读任务错误提升为管理员任务。
- 源表单保留代理、RSSHub、解析器和分类字段；代理密码与 RSSHub access key
  使用 `password` 输入语义，不发布为输出列。抓取动作返回可追踪任务信息，并复用
  task monitor，不把 Classic 页内轮询脚本迁入 runtime metadata。
- 两个 Rotation 共享模板不对应独立 URL 或独立用户任务，已从 M2 route migration
  调整到 M5 `remove_with_consumer`；Classic Rotation 消费者保留期间不提前删除。

### 验证与风险

- 定向页面权限、Reader API、TUI metadata 与 IA：`9 passed`。
- Policy API 边界：`14 passed`。
- RSS API 边界：`3 passed`。
- Policy 集成契约：`7 passed`。
- ruff 与增量 mypy 通过；migration inventory 为
  `templates=195 route_pages=117 A=130 B=17 C=41 D=7`；TUI static contract
  `407 rule(s), 5 source(s)` 通过。
- 真实 live-server Reader 筛选、源/关键词 CRUD、密码回显保护、抓取任务跟踪 UAT
  尚未执行；6 个 Classic route templates 继续保留兼容入口，删除仍受 M5 的稳定期、
  访问量和回滚门槛约束。
