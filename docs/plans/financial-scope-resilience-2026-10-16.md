# 财务发现与发布能力隔离整改

用户已于 2026-10-16 明确批准“局部失败、局部禁用、整体继续运行”。本计划替代此前等待业务口径确认的停止线，历史失败 attempt 仍禁止复用。

## 完成标准

1. 双份完整原文和 RawAudit 保留；缺失/占位日期的历史行显式隔离，不能补造时间。
2. 以两份响应均已完成的知识截止点选择最新已可用公告；未来公告留存但不得用于选择。
3. 每个冻结资产均有结果；网络/无可用公告只形成资产阻断，完整分母和成功项继续保留。身份、授权、审计、范围漂移等失败仍阻断整个验收。
4. 部分财务结果只能签发禁用 financial refresh 的能力报告，不能导入为 full-scope financial receipt。行情证据仍必须全部通过原门禁。
5. runner、bundle builder、validator、handoff 和部署验证消费相同能力边界；不能只修改 producer 或增加跳过参数。
6. 新契约版本/摘要、全部引用方、反例回归与静态门禁通过，再冻结新 SHA 执行 CI、official artifact 和 fresh S6；不拼接旧证据。

## 验证与回滚

本地实现已覆盖上述能力边界；联合回归 500 passed、13 skipped，额外的规范 JSON 回执篡改定向用例通过。
增量 mypy 与全库债务门禁均为 0，Black/isort/Ruff、current-data 74 surfaces、模块图与 Data Center 治理投影通过。
跳过项的 Linux/POSIX 与环境依赖行为仍须由 exact-SHA CI 和 fresh S6 实证；本地通过不是生产恢复完成。
后续为冻结新候选五组 CI、官方 Publication artifact 独立核验、fresh S6 能力验收及受限部署/UAT。

重点反例为：历史坏日期与有效公告并存、仅坏日期、最新公告尚不可用、双份漂移、网络耗尽、未知异常、原文缺失/篡改、重复资产、partial 冒充 full、财务失败不影响已验证行情。生产金融写入及独立 owner/reviewer 认证要求保持不变。

变更分为解析与结果隔离、能力回执及发布链路两项完整事项；本地验证不能代替真实 S6。未完成整改与新候选验收前不部署。回滚须以完整候选版本回滚，不得把新 schema 的证据交给旧 parser/validator。
