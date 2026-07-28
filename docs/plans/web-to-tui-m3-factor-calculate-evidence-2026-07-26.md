# Web → TUI M3 Factor Calculate Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-factor-calculate-w31`；覆盖因子计算 1 个 route template。
- canonical screen：`research.asset-lab`。新增“按配置计算因子分数”和“解释个股因子分数”
  两个动作，分别接入 `/api/factor/calculate-config/` 与
  `/api/factor/explain-config/`。
- TUI 只接收 `config_id`、交易日、返回数量和证券代码等有界标量字段；旧页面允许直接
  编辑的 `factor_weights` 原始 JSON 未进入用户界面。
- 两个 owner API 在 Interface 层使用 DRF serializer 校验，再委托既有
  `calculate_scores_for_config` / `explain_stock_for_config` Application service；
  TUI 没有直接接触 ORM 或复制金融计算逻辑。
- Classic 页面增加准确的 TUI deep link，兼容期内保留；Factor 共享 layout 仍被
  manage 与 portfolios 两个页面消费，不在本 wave 提前转入 M5。

## 验证与风险

- 新增 TUI 与 Factor API 定向测试：`5 passed`。
- TUI information architecture：`6 passed`。
- Factor API edges 全量与上述 TUI/IA 组合运行显示 `27 passed`；测试进程完成后命令
  包装器超时，另以定向命令取得正常退出码。
- `ruff` 通过；production metadata / owner API mypy：
  `0 regressions`、`0 legacy errors`。
- live-server 配置选择、计算成功/失败、个股解释、空结果和长结果 UAT 尚未完成；
  Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。
