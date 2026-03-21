# Mock/Fallback 数据整改计划

## Summary
目标是把“测试专用数据”和“业务运行时伪数据”彻底分层，优先消除会在真实业务链路里冒充真实结果的假数据，其次清理冷启动 seed 和硬编码默认值，最后补齐自动化守卫，避免后续再次混入。

按优先级分三阶段推进：先止血，再去存量，最后建防线。整改完成后的成功标准是：生产/准生产路径在缺少真实数据源时只能显式报错或返回“数据不可用”，不能再生成合成结果、零收益率结果或看似正常的 mock 指标。

## P0 立即整改
- 移除运行时假结果生成，重点处理 [apps/alpha/application/tasks.py](/D:/githv/agomTradePro/apps/alpha/application/tasks.py#L787)、[apps/alpha/management/commands/train_qlib_model.py](/D:/githv/agomTradePro/apps/alpha/management/commands/train_qlib_model.py#L341)、[apps/dashboard/application/queries.py](/D:/githv/agomTradePro/apps/dashboard/application/queries.py#L237)、[apps/rotation/infrastructure/adapters/price_adapter.py](/D:/githv/agomTradePro/apps/rotation/infrastructure/adapters/price_adapter.py#L191)。
- 处理原则统一为：业务路径禁止返回 synthetic/mock/random 数据；缺依赖或缺数据时返回明确错误、空态或降级状态对象，但不能伪造正常值。
- 收紧“隐性伪数据回退”，重点处理 [apps/sector/application/use_cases.py](/D:/githv/agomTradePro/apps/sector/application/use_cases.py#L237) 的零收益率 fallback。零值序列要改成显式 unavailable 状态，并把调用方页面/API 改成展示“数据不足”。
- 为上述高风险路径补日志和状态码规范。所有降级必须带统一标识，例如 `data_source=fallback`、`status=degraded`，禁止默认混入正常成功响应。

## P1 存量清理
- 清理和隔离冷启动 seed：重点梳理 [apps/account/management/commands/bootstrap_mcp_cold_start.py](/D:/githv/agomTradePro/apps/account/management/commands/bootstrap_mcp_cold_start.py#L1) 里的 `MCP_TEST_IND`、固定股票池、冷启动组合。
- 规则调整为：这类命令只能在本地/dev/test 环境运行；命令名、文档、日志要明确标注 `dev-only`；禁止被生产初始化流程或运维脚本误调用。
- 清理硬编码默认配置，重点处理 [shared/infrastructure/config_loader.py](/D:/githv/agomTradePro/shared/infrastructure/config_loader.py#L14)。配置不存在时，不再静默使用业务默认 ticker/threshold，而是区分：
  - 确属产品默认值的，迁移到受管配置表并在初始化时显式写入。
  - 仅用于历史兼容的，保留但打出高优先级告警，并限定不可用于生产。
- 复核 Regime 的 stale fallback 逻辑 [apps/regime/application/use_cases.py](/D:/githv/agomTradePro/apps/regime/application/use_cases.py#L791)。这类“复用上次真实结果”的降级可以保留，但要补前提约束、最大连续次数、前端可见标识，避免与 mock 混淆。

## P2 防回归建设
- 建一套“伪数据扫描规则”，纳入 CI。至少拦截这些模式进入业务代码：`MockModel`、`SYNTH`、`np.random.seed`、`random.seed`、`uniform(`、`gauss(`、`MCP_TEST_IND`、`Using mock data`。
- 扫描范围限定为 `apps/`、`core/`、`shared/` 的非测试目录；`tests/`、`fixtures/`、`factories/` 可豁免，但要保留目录级白名单，避免误伤。
- 增加断源测试。对 alpha 训练、dashboard 指标、rotation 价格、sector 大盘收益率、config loader 分别构造“真实源不可用”场景，断言结果必须是报错/空态/降级态，不能出现伪造数值。
- 增加环境守卫。凡是 seed/bootstrap/dev helper 命令，统一校验 settings/env；在 production 配置下直接拒绝执行。

## Public/API 行为变更
- 可能受影响的页面/API 不再在数据缺失时返回“看起来完整”的指标曲线、价格序列、收益率序列或模型分数。
- 相关接口需要统一补充降级字段，建议最少包含：`status`、`data_source`、`warning_message`。
- 前端展示改为空态或风险提示，不再默认渲染伪数据图表。

## Test Plan
- 单元测试：断言 mock/synthetic 生成函数被移除或在生产路径不可调用。
- 集成测试：模拟外部数据源失败，验证 API/查询层返回 degraded 或 unavailable，而不是合成值。
- 命令测试：在 production settings 下执行 cold start / seed 命令应直接失败；在 dev/test 下可运行。
- 静态扫描测试：新增规则后，用当前已发现样例做基线，确保高风险模式在业务目录中被拦截。
- 回归测试：验证真实数据存在时，现有成功路径与主要页面展示不退化。

## Assumptions
- `tests/fixtures/factories` 中的 mock 数据保留，不作为本轮清理对象；本轮只治理业务运行路径和初始化路径。
- Regime 的“上次真实结果降级复用”属于容灾能力，不按 mock 处理，但必须显式标识并受次数限制。
- 预定义 prompt/template、文档示例、表单 placeholder 不是本轮重点，除非它们会进入真实业务计算结果。
- 实施顺序默认按 P0 -> P1 -> P2；若资源有限，先完成 alpha、dashboard、rotation、sector 四条线的止血整改。
