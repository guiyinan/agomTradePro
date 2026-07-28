# Web → TUI M3 Equity Valuation Config Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-equity-config-w28`；覆盖估值修复配置 1 个复杂 route template。
- canonical screen：`research.asset-lab`。管理员可以查看版本列表和当前生效来源，并完成
  创建、更新、激活、回滚、删除未激活版本和清除运行时缓存。
- 创建/更新表单发布 owner serializer 支持的完整 21 个配置字段；默认值复用 Equity
  Domain 的 `DEFAULT_VALUATION_REPAIR_CONFIG`，不在 Terminal 创建第二套业务默认值。
- 所有 mutation 均标记为 admin risk、要求确认，实际 IsAdminUser、版本约束、权重与阈值
  校验、激活版本保护继续由 owner API 执行。
- Classic 页面增加当前配置的准确 deep link，兼容期内不删除。

## 验证与风险

- TUI metadata + IA：`7 passed`。
- Equity 配置 owner API：`7 passed`；canonical Equity/Fund route contract：`1 passed`。
- `ruff` 通过；production metadata mypy：0 regressions、0 legacy errors。
- live-server 创建→编辑→激活→回滚→删除保护→清缓存 UAT 尚未完成；错误率、旧入口访问量
  和回滚演练仍是 M5 硬门槛。
