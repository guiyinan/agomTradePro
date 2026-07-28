# Web → TUI M2 Account Waves 证据（2026-07-26）

## 范围

- M2-W1：个人 MCP 自助接入，目标 `capability-router.self-service`
- M2-W2：管理员 MCP 用户与令牌治理，目标 `capability-router.admin-access`
- M2-W3：用户审批、状态重置与角色治理，目标 `identity-access.user-governance`
- M2-W4：个人资料、密码、资金流水与交易成本，目标 `account.self-service`
- M2-W5：系统级准入、MCP、视觉、协议与映射设置，目标 `system.settings`

五个 Classic route page 继续保留兼容入口，均提供准确 TUI deep link；未提前执行 M5 删除。

## W3 纵向切片

- owner API：
  - `GET /api/account/admin/users/`
  - `POST /api/account/admin/users/<user_id>/approve/`
  - `POST /api/account/admin/users/<user_id>/reject/`
  - `POST /api/account/admin/users/<user_id>/reset/`
  - `POST /api/account/admin/users/<user_id>/role/`
- 权限：全部使用 DRF `IsAdminUser`；普通已认证用户返回 403。
- 写后回执：每次 mutation 返回 `success`、`message`、目标用户 ID 与刷新后的治理 payload。
- TUI：P0 用户队列、P1 治理回执；列表行提供批准、拒绝、重置入口，角色调整保留为显式 action 表单，避免从行数据误填目标角色。

## W4 纵向切片

- 复用 profile、capital-flow、trading-cost owner API，并新增 `POST /api/account/profile/password/`。
- 密码修改要求当前密码再次认证，并执行 Django 密码策略；错误当前密码返回 403。
- 通用 metadata/schema 新增 `input_type=password`，浏览器控件以 `type=password` 渲染且不把默认值写入 markup。
- Classic 账户设置页准确 deep link 到 `account.self-service`。

## W5 纵向切片

- 新增 config_center owner API：`GET/PUT /api/system/config-center/settings/`。
- 更新端点只接受显式 allowlist；用户协议、风险提示与两类运行时映射均保留结构化类型。
- 普通用户返回 403；管理员更新动作在 TUI 中要求确认。
- Classic 系统设置页准确 deep link 到 `system.settings`。

## 已验证

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

## 尚待验证

- 真实 Django live-server 下的端到端浏览器写入；当前由真实 owner API 契约测试与 mock transport 的 Playwright 任务测试组合覆盖。
- AGENTS.md 固定 TUI 最小回归包将在 M2 account 子域收口时统一执行。
- Classic 入口删除受至少 14 天、稳定版本、访问量与回滚演练门槛约束；当前不能进入 M5。

## 回滚点

- owner API、TUI runtime screen/action、Classic compatibility banner 可按文件独立回滚。
- 删除 runtime screen 时必须同步移除 IA registry 项、identity-access 聚合与相关测试。
