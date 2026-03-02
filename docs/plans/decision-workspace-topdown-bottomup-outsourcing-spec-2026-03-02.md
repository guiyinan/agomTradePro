# 决策面板 Top-down + Bottom-up 融合改造

- 文档类型: 外包实施规格 + 开发计划 + 验收清单
- 版本: v1.0
- 日期: 2026-03-02
- 适用范围: `/decision/workspace/` 主流程及其依赖的 `alpha_trigger / decision_rhythm / regime / policy / beta_gate / asset_analysis` 链路

## 1. 背景与目标

当前系统已经有两个方向的能力，但仍是“并排展示”为主，尚未形成统一决策闭环。

- Top-down: Macro/Regime/Policy/Beta Gate 已存在
- Bottom-up: Alpha、舆情、价格、交易、财务/估值等能力分散存在
- 现状问题:
  - 推荐对象来源不统一，主链路可解释性不足
  - 决策工作台没有把多维证据融合为一个统一建议对象
  - 审批与执行虽有能力，但前端主流程未完整落到统一接口
  - 同证券在不同列表/阶段出现重复，根因在后端聚合规则不统一

本次目标是建设“模型分数主导、规则约束兜底”的统一决策链路:

1. 自上而下与自下而上在同一推荐对象内融合
2. 决策工作台只展示“账户 + 证券 + 方向”唯一可执行建议
3. 去执行必须经过审批模态（带价格区间、仓位、评论）
4. 执行完成后状态闭环回写，支持复盘与后续模型校准

## 2. 范围定义

## 2.1 In Scope

1. 统一推荐聚合层（新）
2. 决策工作台改造为统一推荐读取
3. 审批预览/批准/拒绝链路统一（复用并规范现有 API）
4. 后端聚合去重与冲突分流
5. 推荐对象/审批对象的数据模型补齐
6. 文档、测试、迁移脚本

## 2.2 Out of Scope

1. 新引入外部付费数据源
2. 全量替换现有 Alpha 模型训练体系
3. 实盘交易网关新增供应商适配

## 3. 统一业务流程（目标态）

1. 数据汇聚: 拉取/读取 Regime、Policy、Beta Gate、舆情、价格交易、财务、Alpha 分数
2. 推荐生成: 生成统一推荐对象 `UnifiedRecommendation`
3. 后端聚合: 按 `account_id + security_code + side` 去重
4. 冲突处理: 同账户同证券同时 BUY/SELL 进入冲突队列，不直接可执行
5. 工作台呈现: 展示“待决策建议 / 待执行审批 / 冲突待处理”
6. 发起审批: 点击“去执行”打开审批模态，确认参数 + 评论
7. 执行落地: 批准后进入执行接口，写入执行结果
8. 状态回写: recommendation/request/candidate 全链路状态一致
9. 复盘反馈: 记录 feature snapshot 与结果标签

## 4. 核心设计

## 4.1 推荐引擎策略

采用“模型分数主导 + 规则约束兜底”。

- 综合分计算（默认）:
  - `composite_score = 0.40*alpha_model + 0.15*sentiment + 0.15*flow + 0.15*technical + 0.15*fundamental`
- Hard Gate（必须通过）:
  - Beta Gate 不通过 -> 直接过滤
  - Regime/Policy 明确禁止 -> 直接过滤
- 风险惩罚项（扣分）:
  - 冷却期不足、配额紧张、波动超阈值

## 4.1.1 参数治理要求（强制）

模型参数必须“可视、可配置、可审计”，禁止在业务代码中硬编码生产参数。

1. 必须提供参数配置载体（二选一，推荐同时支持）:
- 数据库配置表（推荐，支持在线修改和审计）
- 配置文件（如 YAML/JSON，作为本地与离线回退）
2. 必须提供参数管理入口:
- 后台管理页或专用配置页可查看当前生效参数
- 展示参数版本、生效时间、最后修改人、变更说明
3. 必须提供默认参数初始化:
- 通过初始化脚本（management command）或启动初始化程序写入默认参数
- 默认参数缺失时系统自动回退到“内置默认参数集（只用于兜底，不作为主配置）”
4. 必须支持按环境隔离:
- 至少区分 dev/test/prod 参数集
5. 必须支持热更新或可控刷新:
- 参数变更后在可控窗口内生效（实时或按刷新周期）
6. 必须有审计日志:
- 记录参数变更前后值、操作者、时间、理由

默认权重参数（v1 初始值）:
- `alpha_model_weight=0.40`
- `sentiment_weight=0.15`
- `flow_weight=0.15`
- `technical_weight=0.15`
- `fundamental_weight=0.15`
- `gate_penalty_cooldown=0.10`
- `gate_penalty_quota=0.10`
- `gate_penalty_volatility=0.10`

说明:
- 上述默认值可在初始化后通过配置页修改
- 业务代码中仅允许保留“兜底默认值常量”，不得作为主要运行参数来源

## 4.2 统一推荐对象（新增）

新增领域对象与持久化模型 `UnifiedRecommendation`，最低字段:

- 标识: `recommendation_id, account_id, security_code, side`
- Top-down: `regime, regime_confidence, policy_level, beta_gate_passed`
- Bottom-up: `sentiment_score, flow_score, technical_score, fundamental_score, alpha_model_score`
- 综合: `composite_score, confidence, reason_codes, human_rationale`
- 交易参数: `fair_value, entry_low/high, target_low/high, stop_loss, position_pct, suggested_qty, max_capital`
- 溯源: `source_signal_ids, source_candidate_ids, feature_snapshot_id`
- 状态: `recommendation_status (NEW/REVIEWING/APPROVED/REJECTED/EXECUTED/FAILED)`

## 4.3 去重与冲突规则（后端根因修复）

1. 聚合键: `account_id + security_code + side`
2. 同键多来源:
  - 合并 reason/source，保留最高置信/最近快照
3. 同证券方向冲突:
  - 不落可执行区，入 `conflict_queue`
4. 页面不得依赖前端去重作为主逻辑

## 5. API 规格（新增/改造）

## 5.1 新增

1. `GET /api/decision/workspace/recommendations/?account_id={id}`
- 返回统一聚合建议列表

2. `POST /api/decision/workspace/recommendations/refresh/`
- 手动触发重算（异步任务）

3. `GET /api/decision/workspace/conflicts/?account_id={id}`
- 返回冲突建议

## 5.2 统一审批执行链路

1. `POST /api/decision/execute/preview/`
- 入参主键: `recommendation_id`
- 出参: 估值区间、仓位建议、风险检查、审批请求 ID

2. `POST /api/decision/execute/approve/`
- 必填: `approval_request_id, reviewer_comments, execution_params`

3. `POST /api/decision/execute/reject/`
- 必填: `approval_request_id, reviewer_comments`

## 5.3 兼容

- `POST /api/decision-rhythm/submit/` 保留为 legacy 兼容接口（一个版本周期），内部转调新链路

## 6. 数据模型与迁移

## 6.1 新增模型

1. `DecisionFeatureSnapshotModel`
- 保存打分输入快照，支持回放与审计

2. `UnifiedRecommendationModel`
- 保存统一推荐对象与状态

3. `DecisionModelParamConfigModel`
- 保存推荐模型参数（按环境/版本）
- 字段至少包含: `param_key, param_value, env, version, is_active, updated_by, updated_reason, updated_at`

4. `DecisionModelParamAuditLogModel`
- 保存参数变更审计日志（前后值、操作者、时间、备注）

## 6.2 扩展模型

1. `ExecutionApprovalRequestModel`
- 新增: `recommendation_id, execution_params_json, reviewer_comments`

2. `DecisionRequestModel`
- 新增: `recommendation_id, feature_snapshot_id`

## 6.3 数据迁移

1. 历史 pending request 尝试映射 `recommendation_id`
2. 映射失败标记 `LEGACY_UNMAPPED`
3. 所有 regime 读取统一走单一 resolver，旧口径字段不再新增写入

## 7. 前端改造（决策工作台）

## 7.1 页面结构

1. 待决策建议（统一推荐）
2. 待执行审批（已批准未执行）
3. 冲突待处理

## 7.2 交互规则

1. 点击“去执行”必须打开审批模态，不允许直接 confirm 后执行
2. 审批模态必须显示:
- 请求/推荐标识
- 方向与置信度
- 公允价值、入场/目标/止损区间
- 建议仓位、数量、最大资金
- 风险检查结果
- 评论输入（必填）
3. 执行中按钮状态可恢复，不允许永久“提交中”

## 8. 代码落位（必须遵守）

1. 聚合与评分编排: `apps/decision_rhythm/application/`
2. 推荐领域对象: `apps/decision_rhythm/domain/`
3. 推荐存储与查询: `apps/decision_rhythm/infrastructure/`
4. 工作台 API: `apps/decision_rhythm/interface/api_views.py`
5. 工作台模板: `core/templates/decision/workspace.html`
6. 页面上下文/入口: `core/views.py`

## 9. 开发里程碑（一次性交付）

## M1: 统一推荐后端骨架（第 1-2 周）

1. DTO/实体/模型建好
2. 推荐聚合服务可跑通
3. 新 API 空返回+mock 返回联调

交付件:
- migration 文件
- API 文档草稿
- 单测首批
- 默认参数初始化脚本（例如 `python manage.py init_decision_model_params`）

## M2: 多维评分 + Gate 融合（第 3-4 周）

1. 接入 top-down + bottom-up 特征
2. 综合分计算与 hard gate 生效
3. 去重与冲突分流落库

交付件:
- 可回放特征快照
- 推荐列表真实数据
- 规则与权重配置说明

## M3: 前端工作台与审批闭环（第 5-6 周）

1. 工作台读取统一建议 API
2. 审批模态完整参数展示
3. approve/reject/execute 全链路打通

交付件:
- 页面交互录屏
- E2E 用例
- 状态流转图

## M4: 回归、灰度、收口（第 7-8 周）

1. 兼容 legacy 接口
2. 性能优化与观测补齐
3. 文档/测试/迁移手册完成

交付件:
- 回归报告
- 灰度开关与回滚方案
- 最终 PR 清单

## 10. 强制验收标准（你可直接据此验收）

## 10.1 功能验收

1. 同账户同证券同方向只出现一条可执行建议
2. 同证券 Buy/Sell 冲突进入冲突区
3. “去执行”必须弹审批模态并显示完整交易参数
4. 批准/拒绝必须写入评论并可追溯
5. 执行成功后状态在 recommendation/request/candidate 三处一致

## 10.2 数据一致性验收

1. 决策页 Regime 与 Regime 页面口径一致
2. 审批记录的 regime_source 与统一 resolver 输出一致
3. feature snapshot 可回放到生成时的推荐分数
4. 推荐模型参数来自配置中心/配置表，不来自业务硬编码

## 10.3 测试验收

1. 单元测试:
- 去重规则
- 冲突分流
- Gate 拦截
- 综合分稳定性
- 参数读取与回退逻辑（配置存在/缺失/非法值）
- 参数热更新或刷新生效逻辑
2. 集成测试:
- recommendation -> preview -> approve/reject -> execute
- 参数变更后推荐结果按预期变化
3. E2E:
- 工作台主流程完整走通
- 参数管理页面可查看、修改、留痕

## 10.4 性能验收

1. `GET /api/decision/workspace/recommendations/` P95 < 500ms（非重算）
2. 重算任务支持批量处理（指标按测试环境基线给出报告）

## 11. 提交与交付规范（外包必须遵守）

1. 每个里程碑单独 PR，不允许超大混合 PR
2. 每个 PR 必须包含:
- 需求点映射
- 变更文件清单
- 测试截图/日志
- 回滚说明
- 参数变更说明（默认参数、初始化方式、生效范围、回退策略）
3. 禁止引入新旧两套路由并行长期共存
4. 禁止仅前端去重掩盖后端重复根因

## 12. 风险与预案

1. 风险: 历史数据口径不一致导致迁移失败
- 预案: 标记 `LEGACY_UNMAPPED`，不阻断主链路
2. 风险: 评分特征缺失
- 预案: 降级权重 + 风险标签，不返回空白关键字段
3. 风险: 执行接口状态竞争
- 预案: 状态机 + 幂等 key + 行级锁

## 13. 文档更新清单（交付必需）

1. `docs/api/decision-workspace-v2.md`（新增）
2. `docs/development/decision-unified-workflow.md`（新增）
3. `docs/testing/decision-workspace-v2-acceptance.md`（新增）
4. `docs/INDEX.md`（更新索引）

## 14. 外包完成后验收方式

外包提交代码后按以下顺序验收:

1. 静态审查: 变更是否符合本规格的模块边界
2. 接口验收: API 入参与返回结构是否齐全
3. 页面验收: 主流程交互是否符合审批闭环
4. 数据验收: 去重、冲突、状态一致性
5. 回归验收: 旧接口兼容是否满足过渡要求

---

该文档即为外包执行与验收唯一基准。如实现与本文冲突，以本文为准。
