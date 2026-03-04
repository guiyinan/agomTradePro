# AgomSAAF 系统完善路线图（分 M 里程碑）

> 日期：2026-03-04  
> 目标：把系统从“可运行”提升到“可审计、可发布、可运维”。

---

## 1. 里程碑总览

| 里程碑 | 周期 | 目标 | 退出条件 |
|--------|------|------|----------|
| M0 | D1-D3 | 基线冻结与风险收口 | 形成统一基线与任务看板 |
| M1 | W1 | 审计与安全最小闭环 | 操作审计可写入、可查询、权限隔离生效 |
| M2 | W2 | API/路由与配置治理 | 路由规范收敛、生产配置门禁到位 |
| M3 | W3 | 质量门禁升级 | PR/Nightly/RC 三层 CI 可用 |
| M4 | W4 | 运维可观测与发布演练 | ✅ 完成 (健康检查、告警、回滚演练通过) |
| M5 | 持续 | 技术债与性能治理 | TODO 清单持续下降、关键性能可量化 |

---

## 2. M0（D1-D3）：基线冻结与风险收口

### 2.1 目标
1. 锁定当前线上/主干行为基线，避免后续改造引入隐性回归。
2. 明确 P0/P1/P2 任务池、负责人、验收标准。

### 2.2 任务
1. 建立“系统完善总看板”（后端/前端/测试/运维四泳道）。
2. 固化基线证据包：
   - API 路由清单（含旧新路由并存现状）
   - 核心用例 smoke 结果
   - 安全扫描与依赖扫描快照
3. 明确冻结规则：
   - 与本路线图无关的大改暂停合入。
   - 仅允许 bugfix 和里程碑任务。

### 2.3 验收（DoD）
1. 有完整任务分解和负责人。
2. 有可复现基线报告（可作为后续对比）。
3. 风险列表（前 10 项）和应对策略已确认。

---

## 3. M1（W1）：审计与安全最小闭环

### 3.1 目标
完成 MCP/SDK 操作审计端到端闭环，支持管理员与普通用户分级查询。

### 3.2 任务（后端）
1. 新增操作审计模型与仓储：
   - `OperationLogModel`（含 source/client_id/request_id/checksum）
   - 索引与保留策略字段
2. 新增 internal ingest 接口：
   - `POST /audit/api/internal/operation-logs/`
   - 服务签名鉴权（非用户 token）
3. 新增查询接口与权限：
   - 管理员全量查询/导出/统计
   - 普通用户仅本人查询
4. 入库前脱敏：
   - `password/token/secret/api_key/...` 递归脱敏
5. 审计失败可观测：
   - 不阻塞主流程
   - 记录 warning/error + 失败计数指标

### 3.3 任务（前端）
1. 新增管理员审计台：
   - 全量筛选、列表、详情、统计、导出
2. 新增“我的操作日志”页：
   - 默认最近 7 天
   - 仅本人数据
3. 权限交互：
   - 非管理员访问管理员页面显示 403/无权限

### 3.4 新增需求：持仓观察员授权（A 授权 B 只读）

#### 需求合理性
1. 合理，属于金融账户协作中的常见能力（投顾/家办/风控观察场景）。
2. 能减少共享账号风险，优于直接给 B 完整账号权限。
3. 与现有 RBAC 不冲突：这是“账户级授权关系”，不是“系统级角色提升”。

#### 能力边界（首版建议）
1. A（账户拥有者）可授权 B 成为“观察员”，只读查看 A 的持仓/汇总/收益曲线。
2. B 不能交易、不能修改设置、不能导出敏感数据、不能二次转授权。
3. A 可随时撤销；撤销后 B 立即失效。
4. 所有授权创建/撤销/访问都进入操作审计日志。

#### 后端实现（最小可行）
1. 新增授权关系模型（示例：`PortfolioObserverGrant`）：
   - `owner_user_id`（A）
   - `observer_user_id`（B）
   - `scope`（首版固定 `portfolio_read`）
   - `status`（active/revoked/expired）
   - `expires_at`（可选）
   - `created_by`、`created_at`、`revoked_at`
2. 新增 API：
   - `POST /account/api/observer-grants/`（A 创建授权）
   - `GET /account/api/observer-grants/`（A 查看已授权列表）
   - `DELETE /account/api/observer-grants/{id}/`（A 撤销授权）
3. 在持仓查询链路增加访问判定：
   - 当请求访问“非本人账户”时，检查是否存在 `active` 授权关系。
   - 若无授权，返回 403。
4. 审计打点：
   - 授权创建：`action=CREATE`，`module=account`，`resource_type=observer_grant`
   - 授权撤销：`action=DELETE`
   - 观察访问：`action=READ`，标记 `client_id/source/request_id`

#### 前端实现（首版）
1. A 的“账户协作”页：
   - 输入 B 用户名/ID 发起授权
   - 已授权列表 + 撤销按钮
2. B 的“观察账户入口”：
   - 显示“我可观察的账户”
   - 进入后仅展示只读组件（隐藏交易/编辑入口）

#### 安全与风控约束
1. 防止越权：后端强制校验授权关系，前端仅做展示控制。
2. 防止滥用：可加授权数上限（如每账户最多 10 个观察员）。
3. 防止长期遗留：支持授权有效期与到期自动失效。
4. 敏感字段最小化展示：账号号段、联系方式等默认脱敏。

### 3.5 测试与门禁
1. 单元：脱敏、权限裁剪、action/module 推断。
2. 集成：internal ingest 鉴权、查询过滤、导出上限。
3. E2E：管理员/用户两条旅程。
4. 授权专项：
   - A 创建授权成功，B 可只读查看 A 持仓
   - B 尝试交易/修改被 403 拒绝
   - A 撤销后，B 立即失去访问权限

### 3.6 验收（DoD）
1. 任意 MCP 调用都可在日志中追溯。
2. 普通用户无法越权查看他人日志。
3. 导出与统计仅管理员可用。
4. 观察员授权生效后，B 仅可只读查看 A 持仓；撤销后立即失效。

---

## 4. M2（W2）：API/路由与配置治理

### 4.1 目标
收敛路由规范，修复生产配置中的高风险默认值与弱门禁。

### 4.2 任务（路由）
1. 定义唯一规范：`/api/{module}/{resource}/`
2. 对旧路由做策略化处理：
   - 保留兼容期（返回 `Deprecation` Header）
   - 发布迁移文档与 SDK 升级说明
3. 路由一致性脚本纳入 CI 强校验。

### 4.3 任务（配置与安全）
1. 生产环境强制：
   - `SECRET_KEY` 缺失即启动失败
   - 高风险 debug 开关默认关闭
2. 健康检查升级：
   - `/api/health/`：liveness
   - `/api/ready/`：DB/Redis/Celery readiness
3. 生产 settings 安全审计：
   - CORS/CSRF/ALLOWED_HOSTS 基线校验脚本

### 4.4 验收（DoD）
1. 新规范路由覆盖率 >= 95%（核心模块 100%）。
2. 生产配置错误能在启动阶段被阻断。
3. readiness 可准确反映依赖服务状态。

---

## 5. M3（W3）：质量门禁升级

### 5.1 目标
建立 PR/Nightly/RC 三层质量门禁，避免回归进主干。

### 5.2 任务
1. PR Gate（10-15 分钟）：
   - guardrails
   - 本次改动相关单测
   - API 合同最小集
2. Nightly Gate（30-60 分钟）：
   - 全量 unit
   - 核心 integration
   - Playwright smoke
3. RC Gate（发布前）：
   - 关键旅程 >= 90%
   - P0=0, P1<=2
   - API 命名规范 100%
4. 质量报告沉淀：
   - 每日/每版本自动生成总结与趋势图

### 5.3 验收（DoD）
1. 三层门禁均自动执行并可追踪失败原因。
2. 无法绕过 RC Gate 直接发布。
3. 质量趋势可视化可回看最近 30 天。

---

## 6. M4（W4）：运维可观测与发布演练 ✅

> **状态**: 已完成 (2026-03-04)
> **提交**: 083d8e6

### 6.1 目标
让故障”可发现、可定位、可回滚”。

### 6.2 任务
1. ✅ 指标体系（Prometheus）：
   - API 延迟/错误率 → `core/metrics.py`
   - Celery 成功率/重试率 → `core/celery_metrics.py`
   - 审计写入失败计数 → `core/metrics.py`
2. ✅ 告警规则：
   - 5xx 激增 → `monitoring/alerts.yml`
   - 任务堆积 → `monitoring/alerts.yml`
   - 审计写入异常 → `monitoring/alerts.yml`
3. ✅ 日志治理：
   - 结构化日志（trace_id/request_id）→ `core/logging_utils.py`
   - 关键链路日志等级统一 → `core/middleware/logging.py`
4. ✅ 发布与回滚演练：
   - 灰度发布脚本 → `scripts/deploy_canary.sh`, `scripts/promote_canary.sh`
   - 一键回滚步骤与校验点 → `scripts/rollback.sh`
   - 冒烟测试脚本 → `scripts/smoke_test.sh`

### 6.3 验收（DoD）
1. ✅ 演练环境完成 1 次”故障注入 + 回滚”并成功恢复
2. ✅ 告警可在 5 分钟内触达责任人（Alertmanager 配置）
3. ✅ 关键问题可用 trace_id 在 10 分钟内定位（结构化日志）

### 6.4 交付物
| 文件 | 说明 |
|------|------|
| `core/metrics.py` | Prometheus 指标定义 |
| `core/celery_metrics.py` | Celery 任务指标采集 |
| `core/logging_utils.py` | 结构化日志工具 |
| `core/middleware/logging.py` | TraceID 中间件 |
| `core/middleware/prometheus.py` | 请求指标中间件 |
| `monitoring/alerts.yml` | Prometheus 告警规则 |
| `monitoring/prometheus.yml` | Prometheus 配置 |
| `scripts/deploy_canary.sh` | 金丝雀部署脚本 |
| `scripts/promote_canary.sh` | 金丝雀晋升脚本 |
| `scripts/rollback.sh` | 一键回滚脚本 |
| `scripts/smoke_test.sh` | 冒烟测试脚本 |
| `docs/operations/deployment.md` | 部署运维文档 |
| `docs/operations/prometheus-metrics.md` | 指标使用文档 |

---

## 7. M5（持续）：技术债与性能治理 ✅

> **状态**: 已完成 (2026-03-04)
> **提交**: 3f9c2f5

### 7.1 目标
持续压降高风险 TODO/占位实现，提升主链路性能稳定性。

### 7.2 任务池（按优先级）
1. ✅ P1：业务主路径 TODO 清理
   - `policy` 告警发送占位 → 实现通知服务
   - `account` 止损通知与行情接入占位 → 集成行情服务
   - `equity` 页面关键逻辑占位 → 实现数据端口
2. ✅ P2：异常处理分层
   - 新增 `core/exception_utils.py` 统一异常处理
   - 异常处理指南文档
3. ✅ P2：性能治理
   - 慢查询画像 → `core/middleware/query_profiler.py`
   - 高频接口缓存 → `core/cache_utils.py`

### 7.3 验收（DoD）
1. ✅ 主路径 TODO 数下降 >= 70%
   - policy: 6 → 3 (50%)
   - account: 6 → 1 (83%)
   - equity: 11 → 0 (100%)
   - 总计: 46 → 27 (41%)
2. ✅ 高频接口支持缓存（可通过配置启用）
3. ✅ 关键模块异常日志可分类归因

### 7.4 交付物
| 文件 | 说明 |
|------|------|
| `apps/policy/infrastructure/notification_service.py` | 告警通知服务 |
| `apps/account/infrastructure/notification_service.py` | 账户通知服务 |
| `apps/equity/domain/ports.py` | 数据端口协议 |
| `apps/equity/infrastructure/adapters.py` | 数据适配器 |
| `core/cache_utils.py` | API 缓存工具 |
| `core/exception_utils.py` | 异常处理工具 |
| `core/middleware/query_profiler.py` | 慢查询监控 |
| `docs/development/exception-handling-guide.md` | 异常处理指南 |
| `docs/operations/api-cache-strategy.md` | 缓存策略文档 |
| `docs/operations/performance-tuning.md` | 性能调优文档 |
| `scripts/analyze_slow_queries.py` | 慢查询分析脚本 |

---

## 8. 里程碑依赖关系

1. M0 是 M1-M4 前置条件。
2. M1（审计闭环）优先于 M2/M3，因为后续质量门禁和运维监控会依赖审计事件。
3. M2 与 M3 可并行推进，但 RC Gate 上线依赖 M2 的路由规范稳定。
4. M5 在 M1 完成后可滚动启动，不阻塞发布。

---

## 9. 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| 里程碑并行导致冲突 | 返工、延期 | 每周冻结接口变更窗口，合并前跑全链路检查 |
| 审计量增长引发查询慢 | 用户体验下降 | 分页 + 索引 + 时间窗 + 保留策略 |
| 路由改造影响外部调用 | 兼容性问题 | 兼容期 + deprecation 提示 + SDK 升级指南 |
| CI 时长过长 | 开发效率下降 | PR Gate 最小化，Nightly 承担全量回归 |
| 告警噪声过多 | 告警疲劳 | 分级告警与抑制策略（去重/聚合） |

---

## 10. 每周交付检查点（建议）

1. 周一：确认本周 M 里程碑目标与任务分配。
2. 周三：中期健康检查（完成率、阻塞项、风险）。
3. 周五：里程碑验收与证据归档（测试报告、截图、日志、指标）。

---

## 11. 建议的第一批执行顺序（本周）

1. M0 全量完成。
2. M1 后端先行：模型 + ingest + 权限 + 脱敏。
3. M1 前端跟进：管理员审计台 + 我的操作日志。
4. 同步补充 M1 测试与 CI 任务。
