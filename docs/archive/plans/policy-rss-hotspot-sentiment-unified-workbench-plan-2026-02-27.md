# Policy + RSS + Hotspot/Sentiment 一体化工作台实施方案

## 1. 背景与目标

当前系统在用户体验与流程完整性上存在割裂：

- `RSS 抓取`、`政策事件管理`、`审核动作`、`闸门生效`分散在多个页面。
- 用户无法快速确认“这条信息是否已入闸、为什么入闸、影响了什么”。
- 政策风险与市场热点/情绪信息混在同一认知层面，缺少清晰边界。

本方案目标：

1. 建立统一工作台，覆盖“抓取 -> 分类/评分 -> 审核 -> 生效 -> 约束 -> 追踪”全链路。
2. 实现双闸并行机制：
   - 政策闸门（Policy Gate）：P0-P3，反映宏观政策风险。
   - 热点情绪闸门（Market Heat/Sentiment Gate）：反映全资产热点与情绪风险。
3. 热点情绪风险触发“风控提醒 + 仓位上限”，不直接改写政策档位。
4. 阈值与规则全部可配置（数据库），不硬编码。

---

## 2. 需求规格（用户与业务）

## 2.1 用户角色

- 运营/研究员：查看抓取结果，处理审核队列，维护规则。
- 风控/投委：查看当前闸门状态与约束，执行豁免或回滚。
- 开发/运维：监控任务健康、失败率、队列积压。

## 2.2 用户核心诉求

1. 单页面完成操作，不跨页来回切换。
2. 每条事件状态透明：待审核/已生效/已拒绝/已回滚。
3. 每次风险触发都可解释：来源、分数、阈值、规则版本、影响对象。
4. 发生误判时可撤销、可回滚。
5. 能区分宏观政策风险与个股/个券热点情绪风险。

## 2.3 业务约束（已定）

- 双闸并行：热点情绪闸门不直接修改 P0-P3。
- 政策当前档位口径：只计算“已生效”的政策事件。
- 热点情绪覆盖范围：全资产。
- 热点情绪触发动作：风控提醒 + 仓位上限。
- 阈值配置：数据库可配置，支持按资产类配置。
- 审核时限：P2/P3 2 小时，其他 24 小时。

---

## 3. 业务模型与状态机

## 3.1 双闸定义

### Policy Gate（政策闸门）

- 输入：政策类事件（policy）
- 输出：P0/P1/P2/P3
- 生效口径：`auto_approved` 或 `manual_approved` 且 `gate_effective=True`

### Market Heat/Sentiment Gate（热点情绪闸门）

- 输入：hotspot/sentiment/individual/sector 等事件
- 双分制输出：
  - `heat_score`: 0~100
  - `sentiment_score`: -1.0~1.0
- 映射等级：L0/L1/L2/L3（风险由低到高）
- 动作：按资产类下发风险提醒与仓位上限

## 3.2 统一事件状态机

- `ingested`：抓取入库完成（原始事件）
- `pending_review`：待人工审核
- `auto_approved`：满足自动生效规则
- `manual_approved`：人工审核通过
- `rejected`：人工审核拒绝
- `effective`：生效状态（可由 auto/manual approved 转入）
- `rolled_back`：已回滚

说明：

- `effective` 为业务可见状态，可由字段派生或显式记录。
- `rejected/rolled_back` 必须保留原因和操作人。

---

## 4. 信息架构与交互设计

## 4.1 新增统一入口

- 页面：`/policy/workbench/`
- 导航命名：`政策与市场风险工作台`

## 4.2 页面分区

1. 顶部概览卡
- 当前政策档位
- 全局热度分
- 全局情绪分
- 待审核数
- SLA 超时数
- 任务健康状态（最近抓取时间、最近失败）

2. 主工作区（表格 + 侧栏）
- Tab1：待审核队列
- Tab2：已生效事件流
- Tab3：约束矩阵（按资产类）

3. 快捷动作区
- 立即抓取全部
- 指定源抓取
- 批量通过/拒绝
- 自动分配审核
- 临时豁免（带时效）

## 4.3 用户关键操作路径

1. 抓取后进入待审核 -> 审核通过 -> 生效 -> 约束生效可见
2. 高风险自动生效 -> 用户可查看原因并可回滚
3. SLA 超时项置顶红标 -> 快速处理

---

## 5. 数据模型设计

## 5.1 新增配置模型

### `PolicyIngestionConfig`（单例或版本化）

- `auto_approve_enabled` (bool)
- `auto_approve_min_level` (char, default `P2`)
- `auto_approve_threshold` (decimal)
- `p23_sla_hours` (int, default 2)
- `normal_sla_hours` (int, default 24)
- `version` / `updated_by` / `updated_at`

### `SentimentGateConfig`（按资产类）

- `asset_class` (stock/bond/fund/sector/other)
- `heat_l1/l2/l3_threshold`
- `sentiment_l1/l2/l3_threshold`
- `max_position_cap` (decimal)
- `enabled` (bool)
- `version` / `updated_by` / `updated_at`

## 5.2 扩展事件模型（建议在 PolicyLog 上最小扩展）

- `event_type` (`policy|hotspot|sentiment|mixed`)
- `asset_class` (可空)
- `asset_scope` (json, 受影响资产/行业/标的列表)
- `heat_score` (float, nullable)
- `sentiment_score` (float, nullable)
- `gate_level` (`L0-L3`, nullable)
- `gate_effective` (bool, default false)
- `effective_at` (datetime, nullable)
- `effective_by` (fk user, nullable)
- `rollback_reason` (text, nullable)

## 5.3 审计模型（新增）

`GateActionAuditLog`：

- `event_id`
- `action` (`approve|reject|auto_effective|override|rollback`)
- `operator`
- `before_state` (json)
- `after_state` (json)
- `reason`
- `rule_version`
- `created_at`

---

## 6. 服务与业务规则实现

## 6.1 抓取与分类编排

在 `FetchRSSUseCase` 增加：

1. 事件类型判定（policy/hotspot/sentiment）
2. 热点情绪打分（Heat/Sentiment）
3. 依据 `PolicyIngestionConfig` 与 `SentimentGateConfig` 判定生效路径
4. 写入统一状态机字段

## 6.2 生效规则

### 政策闸门生效条件

- 规则 A：自动生效
  - `level in [P2, P3]` 且 `ai_confidence >= auto_approve_threshold`
- 规则 B：人工生效
  - 审核通过

### 热点情绪闸门生效条件

- 根据资产类阈值映射 `L0-L3`
- 达到 `L2/L3` 时触发：
  - 风险提醒
  - 对应资产类 `max_position_cap` 约束

## 6.3 当前政策档位查询口径修正

`DjangoPolicyRepository.get_current_policy_level()` 改为：

- 仅查询 `gate_effective=True AND event_type=policy`
- 按 `event_date DESC, effective_at DESC` 取最新

---

## 7. API 设计（统一工作台）

## 7.1 读接口

- `GET /api/policy/workbench/summary/`
  - 返回双闸状态、任务健康、待审核数、超时数

- `GET /api/policy/workbench/items/`
  - 支持筛选：`event_type/status/source/asset_class/level/gate_level/date_range`

- `GET /api/policy/sentiment-gate/state/`
  - 返回按资产类的当前约束与触发原因

## 7.2 写接口

- `POST /api/policy/workbench/items/{id}/approve/`
- `POST /api/policy/workbench/items/{id}/reject/`
- `POST /api/policy/workbench/items/{id}/override/`（临时豁免）
- `POST /api/policy/workbench/items/{id}/rollback/`
- `POST /api/policy/workbench/fetch/`（all/source_id）

## 7.3 配置接口

- `GET/PUT /api/policy/ingestion-config/`
- `GET/PUT /api/policy/sentiment-gate-config/`

---

## 8. 前端工程实现

## 8.1 页面与组件

- 新模板：`core/templates/policy/workbench.html`
- 组件建议：
  - `GateSummaryCards`
  - `ReviewQueueTable`
  - `EffectiveTimeline`
  - `ConstraintMatrix`
  - `TaskHealthPanel`

## 8.2 关键交互

- 审核弹窗显示：原文、分类、分数、阈值命中、建议动作
- 批量操作支持：通过/拒绝/分配
- SLA 超时项固定置顶并红色标签
- 所有关键动作二次确认并强制填写原因（拒绝/回滚/豁免）

## 8.3 兼容策略

- 保留旧页面 URL：`/policy/events/`、`/policy/rss/reader/` 等
- 在旧页面顶部增加跳转横幅至 `/policy/workbench/`

---

## 9. 调度与运行保障

在 `CELERY_BEAT_SCHEDULE` 新增：

1. `policy-fetch-rss-sources`：每 6 小时
2. `policy-review-auto-assign`：每 15 分钟
3. `policy-sla-monitor`：每 10 分钟
4. `policy-gate-refresh`：每 5 分钟（重算约束快照）

运行可观测性：

- 工作台展示最近任务执行时间、状态、失败摘要
- 提供失败重试入口（手动触发）

---

## 10. 测试计划与验收标准

## 10.1 测试用例

1. 高置信 P2/P3 自动生效，进入政策闸门口径。
2. 低置信政策进入待审核，不影响当前政策档位。
3. 热点高热负面情绪触发资产类仓位上限，不影响 P 档位。
4. 修改资产类阈值后，无需重启即可生效。
5. 审核通过/拒绝/回滚均生成审计日志。
6. SLA 超时监控准确。
7. 工作台与旧页面关键数据一致。

## 10.2 验收指标

- 用户在工作台单页完成核心流程的成功率 >= 95%
- 待审核平均处理时长下降 >= 30%
- “找不到是否生效”反馈下降 >= 80%
- 抓取失败可见率与可追踪率 100%

---

## 11. 上线与回滚方案

## 11.1 上线步骤（一次性切换）

1. 发布模型迁移与后端接口。
2. 发布工作台前端与导航切换。
3. 开启定时任务并验证任务健康。
4. 灰度观察 1 个交易日后全量启用自动生效。

## 11.2 回滚策略

- 开关关闭自动生效（保留人工审核）
- 保留工作台只读模式
- 回滚约束到最近稳定版本

---

## 12. 里程碑与工期建议

### M1（2-3 天）
- 模型/迁移/配置模型/API 骨架

### M2（3-4 天）
- 双闸评分与生效规则、审计日志、仓储口径修正

### M3（3-4 天）
- 工作台页面与交互、批量审核、约束矩阵

### M4（1-2 天）
- 联调、回归、上线与监控

总计：约 9-13 个工作日

---

## 13. 风险与缓解

1. 误判风险：保留人工审核、回滚、豁免。
2. 任务稳定性：工作台展示健康状态，失败可重试。
3. 性能风险：列表分页 + 索引 + 异步重算。
4. 认知负担：双闸分区展示，避免信息混杂。

---

## 14. 交付清单

1. 统一工作台页面与 API
2. 双闸模型与规则引擎
3. 配置管理（DB 可调）
4. 审计与回滚机制
5. 任务调度与运行监控
6. 测试报告与验收记录

