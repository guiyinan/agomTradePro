# Web → TUI M2 Beta Gate Wave 证据（2026-07-26）

## 范围

- Wave：`M2-beta-gate-w13`
- Owner：`beta_gate`
- Classic routes：配置列表、创建/编辑、资产测试、版本对比四类入口
- TUI：`macro-regime.strategy` 的配置目录、配置详情、创建、不可变替换、停用、
  资产测试、版本对比和回滚任务
- 兼容策略：Classic 页面保留精确任务 deep link，M5 门槛满足前不删除。

## 任务闭环

普通登录用户可以运行无持久化的批量 Beta Gate 评估并比较配置版本。管理员可查看
完整配置目录，创建配置，以不可变替代版本语义更新，软停用或回滚历史版本。
配置列表发布原生 row actions；所有管理 mutation 和资产评估均声明 effect 并要求确认。

迁移核对同时关闭了历史权限漂移：配置 Classic 页面和 JSON 建议 API 改为 staff-only，
测试/版本页面、决策历史和可见性宇宙改为 authenticated。

## 验证

- 新增权限定向 API/page 用例：`1 passed`。
- TUI Beta Gate 定向用例：`1 passed`（203 deselected）。
- IA：`6 passed`。
- ruff 与增量 mypy：通过，`0 regressions`。

## 未验证风险与回滚

- 真实 live-server 的“创建 → 替代版本 → 资产测试 → 对比 → 回滚/停用”任务流待
  M2 合并前统一 UAT。
- Classic 页面仍受至少 14 天、稳定版本、访问量和无 P0/P1 阻断门槛约束。
- 回滚单位为 Beta Gate runtime bundle、IA panel、页面/API 权限、Classic banner 与矩阵。
