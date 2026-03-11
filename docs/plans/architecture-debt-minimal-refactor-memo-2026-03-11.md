# 架构技术债最小治理备忘录

> 日期：2026-03-11
> 范围：第一阶段最小治理 + 第二阶段蓝图
> 原则：不改 public API、不做数据迁移、不做大规模跨 app 重命名

## 1. 背景

当前代码与文档存在偏差。依赖文档仍把“循环依赖”列为禁止项，但代码里已经出现多组双向跨模块引用，主要集中在：

- `macro ↔ regime`
- `strategy ↔ simulated_trading`
- `events ↔ alpha_trigger / decision_rhythm`
- `dashboard` 聚合逻辑过重

这类问题还没有到必须整体重写的程度，但已经开始影响：

- 模块独立演进能力
- 回归测试稳定性
- 改动面控制
- 文档与代码一致性

## 2. 本次备忘录目标

本轮目标不是做完整架构翻修，而是先用最小代价把高风险技术债收住。

具体目标：

1. 拆掉最危险的双向跨模块依赖
2. 保持现有 HTTP API、SDK、MCP、页面路由不变
3. 不引入数据库 schema 迁移
4. 为后续完整重构留出稳定边界
5. 让依赖文档重新和代码现实对齐

## 3. 非目标

本轮明确不做：

- 全量清理所有跨 app import
- 一次性把所有 app 改成严格六边形架构
- public API 破坏性变更
- 大规模路由调整
- 模板或前端页面重写
- migration squash 或数据模型重构
- SDK / MCP 接口变更

## 4. 现状证据

### 4.1 `macro ↔ regime`

- `macro` 任务层直接引用 `regime` 计算/通知链路
  - `apps/macro/application/tasks.py`
- `regime` 当前状态解析和 use case 又直接依赖 `macro` repository/model
  - `apps/regime/application/current_regime.py`
  - `apps/regime/application/use_cases.py`

判断：

- 这是当前最需要优先拆开的核心循环
- 本质问题不是“数据流互通”，而是“应用编排双向知道对方”

### 4.2 `strategy ↔ simulated_trading`

- `simulated_trading` 直接调用 `strategy` 执行器与规则模型
  - `apps/simulated_trading/application/auto_trading_engine.py`
  - `apps/simulated_trading/application/daily_inspection_service.py`
- `strategy` 又直接读取 `simulated_trading` 账户/仓位模型
  - `apps/strategy/infrastructure/providers.py`
  - `apps/strategy/interface/views.py`

判断：

- 这是第二个需要优先治理的强耦合点
- 当前边界已经从“策略生成决策、模拟盘执行决策”退化为双方互相知道内部实现

### 4.3 `events ↔ alpha_trigger / decision_rhythm`

- `events` 在初始化阶段直接导入业务 handler
  - `apps/events/application/event_bus_initializer.py`
- `alpha_trigger` / `decision_rhythm` 又直接依赖事件实体或事件服务
  - `apps/alpha_trigger/application/use_cases.py`
  - `apps/decision_rhythm/application/use_cases.py`

判断：

- 这更像“事件编排边界泄漏”
- 严重性低于前两组，但应该在同一轮顺手收口

### 4.4 `dashboard`

- `dashboard` 已经成为胖聚合模块
  - `apps/dashboard/interface/views.py`
  - `apps/dashboard/application/use_cases.py`

判断：

- `dashboard` 不一定是核心循环源头，但会放大跨模块耦合
- 本轮只做逻辑下沉，不做页面重构

## 5. 第一阶段：最小治理方案

第一阶段的策略是“只拆边界，不改业务结果”。

### 5.1 拆 `macro -> regime` 的反向编排依赖

目标：

- `macro` 只负责数据采集与入库
- `regime` 只负责环境判定
- “同步宏观数据后刷新 regime” 由独立编排入口负责

实施方式：

1. 从 `apps/macro/application/tasks.py` 移除对 `apps.regime.application.tasks` 的直接依赖
2. 新增独立编排入口，建议放在：
   - `apps/regime/application/orchestration.py`
3. 提供稳定内部函数，例如：
   - `sync_macro_then_refresh_regime(...)`
4. 旧 Celery 任务名尽量保留，由旧任务包装新编排入口

本轮接受的妥协：

- `regime` 继续读取 `macro` repository
- 重点先消除 `macro` 对 `regime` 的反向编排依赖

完成标准：

- `macro` 不再直接 import `regime task`
- 宏观同步后仍可刷新 regime
- 调度链路不变

### 5.2 为 `strategy` 和 `simulated_trading` 提取中间边界

目标：

- 两个 app 不再直接穿透对方的核心执行器和 ORM 模型

实施方式：

1. 在 `strategy` 侧新增执行门面：
   - `apps/strategy/application/execution_gateway.py`
   - 对外暴露 `execute_strategy_for_account(...)`
2. 在 `simulated_trading` 侧新增只读快照门面：
   - `apps/simulated_trading/application/account_snapshot_service.py`
   - 对外暴露 `get_account_positions_snapshot(...)`
3. 调整依赖方向：
   - `simulated_trading` 改调 `strategy.execution_gateway`
   - `strategy` 改读 `simulated_trading.account_snapshot_service`

受影响优先文件：

- `apps/simulated_trading/application/auto_trading_engine.py`
- `apps/simulated_trading/application/daily_inspection_service.py`
- `apps/strategy/infrastructure/providers.py`
- `apps/strategy/interface/views.py`

本轮接受的妥协：

- facade 内部仍可暂时使用现有 repository/ORM
- 但跨 app 访问必须通过 facade 进入

完成标准：

- 不再出现 `simulated_trading -> StrategyExecutor` 直接依赖
- 不再出现 `strategy -> simulated_trading ORM` 直接依赖
- 自动交易、日检、策略页面行为不变

### 5.3 收口 `events` 的业务订阅注册

目标：

- `events` 只提供事件契约和总线
- 业务模块自己注册订阅者

实施方式：

1. 保留 `events` 中的：
   - `DomainEvent`
   - `EventType`
   - `EventBus`
   - event store
2. 把订阅注册移到业务模块侧：
   - `apps/alpha_trigger/application/event_subscribers.py`
   - `apps/decision_rhythm/application/event_subscribers.py`
3. `events` 不再显式 import 业务 handler

本轮不做：

- 重写整个事件系统
- 引入外部消息中间件
- 修改事件查询与回放接口

完成标准：

- `apps/events/application/event_bus_initializer.py` 不再依赖具体业务 handler
- 事件消费路径保持可用

### 5.4 下沉 `dashboard` 聚合逻辑

目标：

- `dashboard` 只做展示聚合，不再在 view 中直接串大量跨模块读取

实施方式：

1. 将聚合逻辑从 view 下沉到 application/query service
2. 推荐新增：
   - `apps/dashboard/application/overview_queries.py`
   - `apps/dashboard/application/decision_panel_queries.py`
   - `apps/dashboard/application/market_summary_queries.py`
3. 优先治理以下摘要块：
   - 账户摘要
   - 决策节奏摘要
   - alpha/beta 状态摘要
   - macro/regime 摘要

约束：

- 不改现有 URL
- 不重写模板
- 如果 dashboard 要读别的模块数据，优先走对方 facade/query service

完成标准：

- `apps/dashboard/interface/views.py` 中跨 app 直接 import 数量明显下降
- 页面输出保持一致

## 6. 第一阶段实施顺序

不能并行乱改，按以下顺序执行：

1. `macro/regime` 编排边界
2. `strategy/simulated_trading` facade
3. `events` 订阅注册收口
4. `dashboard` 聚合下沉
5. 依赖文档更新
6. 回归测试和人工验收

原因：

- 先拆核心循环，收益最大
- `dashboard` 依赖前面新增的 facade，适合放后面
- 文档要最后和代码一起收敛

## 7. 对外接口与兼容性要求

第一阶段必须保持：

- HTTP API 不变
- 页面 URL 不变
- DRF serializer 输入输出不变
- SDK / MCP 接口不变
- 旧 Celery 任务名尽量保留

第一阶段允许新增的仅限内部接口：

- `sync_macro_then_refresh_regime(...)`
- `execute_strategy_for_account(...)`
- `get_account_positions_snapshot(...)`
- `register_alpha_trigger_subscribers(...)`
- `register_decision_rhythm_subscribers(...)`
- `dashboard` 各类 query service

内部类型约束：

- 跨 app facade 返回 dataclass 或 `TypedDict`
- 不直接返回对方 app ORM 实例
- 只暴露最小必要字段

## 8. 测试与验收

### 8.1 单元测试

- `macro` 同步逻辑不再直接依赖 `regime task`
- `regime` 仍能从宏观数据仓储完成状态计算
- `strategy.execution_gateway` 正确包装原执行器
- `simulated_trading.account_snapshot_service` 返回稳定 DTO
- 事件订阅注册能完成且不重复注册
- `dashboard` query service 对空数据、部分数据、异常数据有稳定输出

### 8.2 集成测试

- 宏观同步后刷新 regime 主链路可用
- 自动交易仍能调用策略执行并写入结果
- 模拟盘日检仍能拿到策略和 regime 信息
- `decision_rhythm` / `alpha_trigger` 事件链路保持可用
- `dashboard` 概览页或关键摘要接口保持 200

### 8.3 人工验收

- 手动跑一次 macro sync，确认 regime 可刷新
- 打开 dashboard，确认关键卡片仍展示
- 跑一次 simulated trading 日检，确认无 ImportError / AttributeError
- 发布一条事件，确认 handler 仍被消费

## 9. 风险与缓解

### 风险 1：链路编排迁移后，Celery 调度遗漏

缓解：

- 旧任务保留为薄包装器
- 为主链路补集成测试

### 风险 2：facade 提取后字段不全

缓解：

- 先按现有调用点反推最小字段集
- 对 facade 补单测和调用方回归测试

### 风险 3：事件订阅迁移后漏注册

缓解：

- 增加注册断言测试
- 启动阶段输出订阅清单日志

### 风险 4：dashboard 治理过程中继续偷读 ORM

缓解：

- 在代码评审规则中写明：新增跨 app 访问必须走 facade/query service

## 10. 第二阶段：完整蓝图

第二阶段不属于本轮交付，但需要在备忘录中定义清楚方向。

终局目标：

- 跨 app 写操作统一通过 application facade / use case 进入
- 跨 app 读操作统一通过 query facade / read model 进入
- 事件系统只负责契约和总线，不反向依赖业务模块
- `dashboard` 只消费聚合 DTO
- `macro` 只提供数据，`regime` 只负责判定，编排独立
- `strategy` 负责策略决策，`simulated_trading` 负责账户执行和结果快照

建议后续继续新增的稳定边界：

- `apps/regime/application/orchestration.py`
- `apps/strategy/application/execution_gateway.py`
- `apps/simulated_trading/application/account_snapshot_service.py`
- `apps/alpha_trigger/application/event_subscribers.py`
- `apps/decision_rhythm/application/event_subscribers.py`
- `apps/dashboard/application/*_queries.py`

第二阶段可以继续做的事项：

- 为 facade 补全 DTO 类型
- 为 dashboard 建统一 read model
- 加 import-linter 或自定义依赖守卫
- 自动生成依赖图并与文档比对
- 把高频跨 app 读请求进一步从 ORM 直读迁到 query object

## 11. 文档与治理规则更新

本轮完成后应同步更新：

- `docs/development/module-dependency-graph.md`

更新要求：

- 不再笼统写“无循环依赖”
- 改为如实记录当前治理前提和目标状态
- 明确以下规则：
  - 禁止 `macro -> regime task` 直接依赖
  - 禁止 `simulated_trading -> strategy executor` 直接依赖
  - 禁止 `strategy -> simulated_trading ORM` 直接依赖
  - 禁止 `events -> 业务 handler` 直接依赖
  - 禁止 `dashboard view -> 跨 app ORM/model` 持续扩散

## 12. 受影响文件清单

- `apps/macro/application/tasks.py`
- `apps/regime/application/current_regime.py`
- `apps/regime/application/use_cases.py`
- `apps/simulated_trading/application/auto_trading_engine.py`
- `apps/simulated_trading/application/daily_inspection_service.py`
- `apps/strategy/infrastructure/providers.py`
- `apps/strategy/interface/views.py`
- `apps/events/application/event_bus_initializer.py`
- `apps/decision_rhythm/application/use_cases.py`
- `apps/alpha_trigger/application/use_cases.py`
- `apps/dashboard/interface/views.py`
- `apps/dashboard/application/use_cases.py`
- `docs/development/module-dependency-graph.md`

## 13. 结论

这个问题属于中高优先级技术债。

不需要停下所有功能开发做全面重写，但也不适合继续放着不管。最合理的做法是：

1. 先用第一阶段最小方案拆掉核心耦合
2. 保持外部接口完全稳定
3. 用 facade / orchestrator / subscriber registration 把边界收住
4. 再进入第二阶段的完整蓝图

本备忘录默认作为后续实现和代码评审的边界依据。
