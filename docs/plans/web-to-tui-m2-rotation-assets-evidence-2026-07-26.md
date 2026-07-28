# Web → TUI M2 Rotation Assets Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M2-rotation-assets-w14`；Classic route：`/rotation/assets/`。
- TUI：`macro-regime.strategy` 的资产列表、详情、行情、创建、更新、软/硬删除、
  默认资产导入预览和确认导入。
- 管理 mutation 均为 admin audience、显式 effect 与确认；导入强制提供只读预览任务。
- Classic 页面和旧生成信号入口改为 staff-only；普通用户仍可通过认证 API 读取目录。
- TUI 表格支持 F8 导出，owner JSON/CSV 下载端点在兼容期继续保留。

## 验证与风险

- TUI 定向 `1 passed`（204 deselected）；IA `6 passed`。
- Classic staff 边界 `1 passed`；既有 Rotation API 已覆盖 CRUD、软删除和导入差异。
- ruff、增量 mypy、inventory/static contract 通过。
- 真实 live-server CRUD→预览→导入→导出 UAT 待 M2 合并前补齐；Classic 页暂留。
