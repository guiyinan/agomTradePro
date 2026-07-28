# Web → TUI M2 Backtest Wave 证据（2026-07-26）

## 范围

- Wave：`M2-backtest-w12`
- Owner：`backtest`，应用持仓 mutation 由 `account` owner 承接
- Classic routes：`/backtest/`、`/backtest/create/`、`/backtest/<id>/`
- TUI：`research.asset-lab` 的 `backtest.summary`、`backtest.list`、
  `backtest.detail`、`backtest.run` 等任务
- 兼容策略：三张 Classic 页面保留精确任务 deep link，M5 门槛满足前不删除。

## 任务闭环

登录用户可查看统计和筛选后的回测列表，通过原生 row actions 查看详情、重跑或删除，
也可运行探索性/PIT 验证回测，并把结果按缩放因子应用到自己的持仓。运行表单覆盖
owner serializer 的可信度、数据清单、配置哈希、代码提交、引擎版本、研究试验和决策
快照字段，没有用简化表单丢失研究可复现性信息。

运行、重跑、应用持仓和删除均声明 effect 并要求确认。应用持仓补充
`/api/account/backtests/<id>/apply/` 路由，继续复用既有 account Application service；
TUI 不调用非 `/api/` 页面路径，也不复制持仓业务逻辑。

迁移核对同时关闭了历史认证漂移：三个 Classic 页面、Backtest ViewSet 和独立统计
入口现在均要求认证。

## 验证

- `tests/api/test_backtest_api_edges.py`：原 7 个用例通过；新增 Classic deep-link 用例
  `1 passed`，完整文件首次回归仅因测试客户端未建立 Django session 失败，修正 fixture
  后定向通过。
- TUI Backtest 定向用例：`1 passed`（202 deselected）。
- IA：`6 passed`。
- ruff 与增量 mypy：通过，`0 regressions`。

## 未验证风险与回滚

- 真实 live-server 的“创建 → 查看进度/详情 → 应用持仓 → 重跑/删除”任务流待 M2
  合并前统一 UAT。
- Backtest 历史存储仍采用既有共享研究结果口径；本 wave 不改变数据所有权模型。
- Classic 页面仍受至少 14 天、稳定版本、访问量和无 P0/P1 阻断门槛约束。
- 回滚单位为 Backtest runtime bundle、IA panel、认证装饰器/API permission、account
  API alias、Classic banner 与矩阵记录。
