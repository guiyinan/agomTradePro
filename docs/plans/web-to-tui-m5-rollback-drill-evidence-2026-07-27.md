# Web → TUI M5 回滚演练证据（2026-07-27）

## 结论

本地隔离回滚演练通过。演练覆盖 M0–M4 单体 published graph/runtime bundle，
并以最后一批 `M4-simulated-accounts-w51` 的 route/template 文件作为代表 wave：

1. 在临时目录落地当前候选文件；
2. 对真实 Git 差异执行 reverse patch；
3. 删除该 wave 新增的 TUI adapter/runtime injection；
4. 逐文件核对恢复后的 pre-migration baseline；
5. 使用当前 runtime/schema 验证旧 graph；
6. 正向重放 patch 并恢复新增文件；
7. 逐文件核对候选状态；
8. 在 pytest 隔离数据库中执行 registry
   `候选发布 → 旧 graph 回滚发布 → 候选恢复发布`。

演练未修改工作树、开发数据库或生产 registry，也没有删除任何 Classic 页面。

## 可重复命令

```bash
python scripts/drill_web_to_tui_rollback.py
pytest tests/integration/test_web_to_tui_rollback_drill.py -q
```

## 演练快照

| 项目 | 结果 |
|---|---|
| 代表 wave | `M4-simulated-accounts-w51` |
| baseline commit | `7e706d07caacca8b3e56a486d8c0b6b6ed2cdf37` |
| baseline raw graph hash | `249ebc246b57374b9bd450704861feff358ae1977698580c982b8469afe44db0` |
| candidate raw graph hash | `18e5db1eea91ac547c5c9008ea32b7148d1f62ae171c709e7754f2fef3387a4e` |
| baseline contract | `tui-metadata.v3`，12 screens，402 static actions |
| candidate contract | `tui-metadata.v3`，12 screens，407 static actions |
| reverse patch + baseline 核对 | 通过，0.298 秒 |
| forward restore + candidate 核对 | 通过，0.223 秒 |
| 整体本地文件演练 | 通过，20.510 秒 |
| registry publish/rollback/restore | `1 passed`，85.41 秒 |
| 工作树变化 | 无 |

候选 graph 比 baseline 多 5 个静态 actions，其中包含为 immersive 今日总览补齐的
`dashboard.overview-summary` compiler-approved action；其余新增能力继续由 runtime
injections、action/screen patch 与 IA 共同注入。账户 P0 持仓已切换到纯只读 action，
会同步账本的旧 action 已从该 screen 删除。本次演练同时核对了这些文件以及 W51 的
Classic route templates 和 API route 注册。

## 文件范围

已反向/正向应用真实差异的 tracked 文件：

- `apps/simulated_trading/interface/api_urls.py`
- `apps/terminal/infrastructure/tui_metadata_runtime_action_patch_execution.py`
- `apps/terminal/infrastructure/tui_metadata_runtime_screen_patch_execution.py`
- `config/tui/ia/tui_information_architecture.v1.json`
- `config/tui/published/tui_operation_graph.published.json`
- `core/templates/simulated_trading/account_detail.html`
- `core/templates/simulated_trading/dashboard.html`
- `core/templates/simulated_trading/my_account_detail.html`
- `core/templates/simulated_trading/my_accounts.html`

已执行删除/恢复并核对内容的新增文件：

- `apps/simulated_trading/interface/tui_serializers.py`
- `apps/simulated_trading/interface/tui_views.py`
- `apps/terminal/infrastructure/tui_metadata_runtime_injection_simulated_trading.py`

## 仍未解除的 M5 门禁

本证据只把“wave 级 graph/runtime 与 route/template 回滚演练”从未完成改为本地演练
通过，不等于 M5 删除授权。以下条件仍必须满足：

- 候选稳定版本运行不少于 14 个自然日；
- 生产 Classic/TUI 对照样本达到阈值并通过 5% 与 0.5 个百分点门槛；
- 计划内角色与主路径 live-server UAT 100%；
- 完整观察窗口内 P0/P1 阻断缺陷为 0；
- 正式清理前再次确认 production registry 备份、owner 与 reviewer。
