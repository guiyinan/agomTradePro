# Web → TUI M2 Prompt 工作台 Wave 证据（2026-07-26）

## 范围

- Wave：`M2-prompt-workbench-w7`
- Owner：`prompt`
- Classic 入口：`/prompt/manage/`
- TUI 入口：`/tui/?screen=prompt.workbench&action=prompt-template.list`
- 兼容策略：Classic 页面保留迁移提示和精确 deep link，M5 门槛满足前不删除。

## 任务闭环

专用 `prompt.workbench` 把 16 个操作重组为一个复杂 CRUD 工作台：

- 模板：列表、分类、详情、新建、更新、删除和测试执行；
- 执行链：列表、执行模式、详情、新建、更新和删除；
- 记录：执行日志、最近日志和日志详情。

普通用户可查看模板/链并执行一次受确认约束的 AI 测试；模板和执行链的新增、更新、删除只对管理员展示，owner API 继续做最终授权。首屏 P0 是模板清单，P1 是执行链和最近执行记录。

该 runtime bundle 自带模板、执行链和最近记录的稳定只读 action，不依赖完整 published graph 才能满足 P0/default-action 契约；小型测试 registry、DB override 与重复 normalize/publish 也可保持有效。

## Owner API 收口

`PromptTemplateViewSet.execute` 现在以 URL path 中的模板 ID 为唯一真源，并在 Interface 层注入请求 DTO。调用者不再需要在路径和 JSON body 中重复提交同一 ID；对象存在性、认证和执行用例不变。

## 验证

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

## 未验证风险与回滚点

- 通用 workbench 的结构化 JSON/list 字段、确认对话框和写后回执已有浏览器契约；本 wave 的真实 live-server 模板创建→执行→日志刷新任务流待 M2 合并前统一执行。
- Classic 页面仍受至少 14 天、稳定版本、旧入口占比和无 P0/P1 阻断的退出门槛约束。
- 回滚单位为 runtime screen/actions、read-action routing patch、path-ID Interface 归一化、Classic banner 与矩阵记录。
