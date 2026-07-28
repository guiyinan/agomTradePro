# Web → TUI M2 Qlib 配置与训练 Wave 证据（2026-07-26）

## 范围

- Wave：`M2-config-center-qlib-w6`
- Owner：`config_center`
- Classic 入口：`/settings/config-center/qlib/`
- TUI 入口：`/tui/?screen=system.qlib-center&action=config_center.qlib_runtime`
- 兼容策略：Classic 页面保留迁移提示和精确 deep link；未满足兼容期退出门槛前不删除模板或路由。

## 任务闭环

专用管理员 screen `system.qlib-center` 承接以下既有 owner API：

- 读取、更新 Qlib Runtime 配置；
- 列出、解析成员并保存 Alpha/Qlib 模型 Universe；
- 列出并保存训练模板；
- 列出、查看训练运行记录并触发训练。

首屏 P0 展示运行条件，P1 展示模型 Universe 与最近训练记录。Runtime 更新、Universe 保存、训练模板保存和触发训练均要求显式确认，后端继续执行管理员授权。

Qlib runtime bundle 还保证在小型/自定义 registry 中至少保留一个自带 P0 Universe action，避免依赖完整 published graph 的 Runtime action 时产生无 P0 panel 的无效 screen。

## 关键实现

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

## 验证

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

## 未验证风险与回滚点

- 通用 workbench 已有结构化表单、确认对话框和响应渲染的浏览器契约；本 wave 的真实 live-server 管理员写入 UAT 尚待 M2 合并前统一执行。
- Classic 页面仍处于兼容窗口，M5 删除受至少 14 天、稳定版本、访问量和无 P0/P1 阻断门槛约束。
- 回滚单位为专用 screen/action patch、IA runtime screen 登记、Classic banner 和矩阵记录；owner API 未在本 wave 改动。
