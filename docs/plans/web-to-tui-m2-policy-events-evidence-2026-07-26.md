# Web → TUI M2 Policy Events Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M2-policy-events-w19`；Classic routes：政策事件列表、政策事件创建、
  政策工作台，共 3 个 route templates。
- TUI 新增 9 个 curated action：事件列表/详情/创建、工作台 bootstrap/详情，
  以及批准、拒绝、回滚、临时豁免；复用既有
  `policy.queue_summary` 与 `policy.workbench_items` 作为 P0 入口。
- 事件创建 API 与 Classic 页面统一为 staff-only；普通认证用户继续按既有
  协作模型查看工作台并执行审核动作。
- P0 待处理表格发布原生详情和批准 row action。拒绝、回滚、豁免必须填写
  理由，因此保留为完整确认表单，避免无理由一键写入。
- 事件列表保留日期范围、政策档位、说明和证据链接；详情保留来源、AI 分析、
  闸门状态、审核记录与资产范围。

## 验证与风险

- Policy API、页面权限、TUI metadata 与 IA 合计 `29 passed`。
- ruff、增量 mypy、inventory 与 static contract 均通过。
- 真实 live-server 日期筛选→详情→批准/拒绝→回滚/豁免 UAT 待 M2 合并前
  补齐。
- Policy RSS 源、关键词、Reader 和抓取日志共 6 个 route templates 留给
  下一独立 wave；本 wave 没有混入外部采集配置。
