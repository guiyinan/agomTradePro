# Web → TUI M2 Decision Rhythm Wave 证据（2026-07-26）

## 范围

- Wave：`M2-decision-rhythm-w11`
- Owner：`decision_rhythm`
- Classic routes：`/decision-rhythm/quota/`、`/decision-rhythm/config/`
- TUI：
  - `/tui/?screen=command-center.decision-flow&action=decision-rhythm.quota-list`
  - `/tui/?screen=command-center.decision-flow&action=decision-rhythm.quota-update`
- 兼容策略：Classic 页面保留精确任务链接，M5 门槛满足前不删除。

## 任务闭环

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

## 验证

- `tests/api/test_decision_rhythm_api_edges.py`：`23 passed`
  - 覆盖读写权限、管理员参数校验、重置作用域与 Classic 精确 deep link。
- `tests/guardrails/test_decision_rhythm_api_error_mapping.py`：`8 passed`。
- TUI Decision Rhythm 定向用例：`1 passed`（201 deselected）
  - 覆盖 datagrid、portable chart、管理员 audience 与确认契约。
- ruff：通过。

## 未验证风险与回滚

- 真实 live-server 的“筛选配额 → 查看趋势 → 更新 → 重置 → 面板刷新”任务流待
  M2 合并前统一 UAT。
- Classic 页面仍受至少 14 天、稳定版本、访问量和无 P0/P1 阻断门槛约束。
- 回滚单位为 Decision Rhythm runtime bundle、IA 面板、API/page 权限、Classic
  banner 与矩阵记录。
