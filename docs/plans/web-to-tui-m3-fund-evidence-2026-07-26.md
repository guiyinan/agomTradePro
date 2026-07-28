# Web → TUI M3 Fund Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-fund-w35`；覆盖基金研究 Dashboard 1 个 route template。
- canonical screen：`research.asset-lab`。发布多维筛选、排名、单基金评分、风格分析、
  区间业绩、基金资料、净值历史和持仓 8 个动作。
- 为 TUI 新增 `/api/fund/tui-multidim-screen/` typed owner 端点，只接收基金类型、投资
  风格、最小规模、Regime、政策档位、情绪指数和返回数量等扁平字段；Interface 组装
  owner Application service 所需上下文，不向用户暴露旧 `filters/context` 原始 JSON。
- 旧 Dashboard 的 `/api/fund/multidim-screen/` 嵌套契约保持不变，兼容页不受影响；
  新 serializer/view 独立成文件，避免把旧文件的历史类型债务带入增量基线。
- Regime 选项取 `RegimeType` Domain enum；计算型 POST 显式确认。Classic Dashboard
  增加准确 TUI deep link，兼容期内保留。

## 验证与风险

- Fund API、TUI metadata 与 information architecture：`21 passed`。
- 完整 TUI Workbench：`223 passed`。
- `ruff` 通过；5 个新增/修改 production 文件 mypy：
  `0 regressions`、`0 legacy errors`。
- live-server 多维筛选、排名、404/空态、长净值与持仓、业绩计算 UAT 尚未完成；
  Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。
