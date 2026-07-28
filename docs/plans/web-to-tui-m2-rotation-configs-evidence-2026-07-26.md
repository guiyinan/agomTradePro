# Web → TUI M2 Rotation Configs Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M2-rotation-configs-w15`；Classic route：`/rotation/configs/`。
- TUI：全局配置列表/详情/创建/更新/删除/启用/停用/生成信号。
- 表单覆盖 owner serializer 的资产池、策略参数、权重、换手率、回溯周期、
  象限配置、动量周期和 top_n，不使用简化 payload。
- 全局配置读操作要求认证；所有 mutation 与持久化信号生成要求管理员并显式确认。

## 验证与风险

- TUI 定向 `1 passed`（205 deselected）；IA `6 passed`。
- 管理员边界定向 `1 passed`；ruff、增量 mypy、inventory/static contract 通过。
- 真实 live-server 创建→编辑→启停→生成信号 UAT 待 M2 合并前补齐。
- Classic 页面暂留；账户级轮动配置继续作为独立 user-scoped wave。
