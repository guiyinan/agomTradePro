# Web → TUI M3 Asset Analysis Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-asset-analysis-w24`；覆盖多维资产筛选 1 个认证 route template。
- `research.asset-lab` 新增 `asset-analysis.pool-screen`：资产类型通过 path 绑定，
  Regime、评分区间和风险等级通过 typed body fields 传递，结果用 datagrid 展示。
- 复用 `/api/asset-analysis/screen/<asset_type>/` owner API。后端当前只支持
  `equity` 和 `fund`，TUI 不发布 Classic 页中会稳定报错的 bond/wealth/commodity
  标签。
- API 默认筛选 investable/watch/candidate 资产池；返回仍保留完整 context、
  pool summary 和各评分维度。首屏列按用户优先级限制为 8 列，其余字段仍在响应中。
- Classic 手写 CSV 导出由 TUI 原生 datagrid export 替代；页面发布精确 deep link
  并在稳定期继续保留。

## 验证与风险

- Asset Analysis owner API：`6 passed`。
- TUI metadata 与 IA：`7 passed`；首次验证发现 datagrid 超过 8 列，按 schema
  门禁压缩为 8 个核心列后通过。
- ruff 通过；metadata 与 registry 增量 mypy 为 `0 regressions`。
- 真实 live-server equity/fund 筛选、空结果、错误和导出 UAT 尚未执行；Classic
  路由删除仍受 M5 稳定期、访问量和回滚门槛约束。
