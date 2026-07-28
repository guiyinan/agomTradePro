# Web → TUI M2 Signal Wave 证据（2026-07-26）

## 范围

- Wave：`M2-signal-management-w10`
- Owner：`signal`
- Classic route：`/signal/manage/`
- TUI：`/tui/?screen=research.signals&action=signal.list`
- 兼容策略：Classic 页面保留精确任务链接，M5 门槛满足前不删除。

## 任务闭环

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

## 验证

- `tests/api/test_signal_api_edges.py`：`20 passed`
  - 覆盖列表/详情、角色授权、审批/证伪、批量检查 API 与 Classic deep link。
- TUI Signal 定向用例：`1 passed`（200 deselected）
  - 覆盖普通用户只读、管理员动作、确认契约与必填证伪字段。
- IA：`6 passed`。
- inventory：`templates=195 route_pages=117 A=130 B=17 C=41 D=7`。
- static contracts：`407 rule(s), 5 source(s)`。
- ruff 与增量 mypy：通过，`0 regressions`。

## 未验证风险与回滚

- 真实 live-server 的创建→批准→批量检查→证伪状态刷新任务流待 M2 合并前
  统一 UAT。
- Classic 页面仍受至少 14 天、稳定版本、访问量和无 P0/P1 阻断门槛约束。
- 回滚单位为 Signal runtime actions、batch-check Interface action、Classic
  banner 与矩阵记录。
