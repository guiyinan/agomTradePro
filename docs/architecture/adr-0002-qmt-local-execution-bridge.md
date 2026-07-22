# ADR-0002：QMT 本地执行桥

- 状态：已接受
- 日期：2026-07-22
- Owner：`broker_execution`

## 决策

AgomTradePro 的实盘控制面运行在 VPS；QMT/MiniQMT 与 `xtquant` 只运行在用户受支持的 Windows 主机。两端通过 Agent 主动发起的 HTTPS 拉取契约通信，不开放本地入站端口，也不在 VPS 生产依赖中加入 `xtquant`。

VPS 以 `LiveOrder` 为订单生命周期真源。本地 Agent 只能领取已批准的 `READY` 订单，不能创建、修改或批准订单。Agent 在调用 QMT 前必须先向 VPS 确认 `SUBMITTING`，并在本地 SQLite 中持久化同一状态；提交结果不确定时进入 `RECONCILIATION_REQUIRED`，禁止自动重报。

人工订单动作采用 preview/commit，并以 `expected_version` 绑定用户看到的订单版本；审批摘要同时绑定来源建议/信号。Agent 提交确认前由 VPS 原子重查当前风控门禁。QMT callback 只负责唤醒和断线感知，委托/成交仍走统一查询归一化路径；撤单调用成功只表示请求受理，最终状态以券商事实为准。

Classic Web、TUI、正式 SDK 和 MCP 共享 `broker_execution` Application UseCase 与 canonical API。MCP 只发布固定 core tools 下的 governed capability，不增加 QMT raw tools，也不发布 Agent 心跳、拉单、回报和快照接口。

## 安全边界

- 人类身份复用项目 RBAC，并增加动作级能力和显式账户授权；
- Agent 使用独立的哈希凭证、scope、有效期、撤销、时间窗、nonce 和请求 HMAC；
- 高风险人工写操作必须 preview-first、显式确认、幂等并写只追加审计；
- `owner/investment_manager/trader/risk/admin` 可紧急停止，只有管理员可恢复；
- 停止状态阻断建单、批准后的领取和提交，但保留回报、撤单和对账；
- Agent Token、券商账户原值和 QMT 本地路径不进入普通页面、TUI 或 MCP 输出。

## 数据与恢复

服务端持久化 Agent、账户绑定、显式账户授权、订单、租约、券商事件、成交、资金/持仓快照、命令、对账、停止开关、凭证、nonce 和审计。订单租约短时有效；过期租约由维护任务回收。Agent 重启时先查询本地未决记录和 QMT 委托，再回传事实，不盲目重试。

## 结果

该方案不要求家庭网络公网 IP，VPS 与 QMT 依赖隔离，且能统一 Web/TUI/MCP 的权限、幂等和审计。代价是 Windows 主机必须在交易时段稳定运行，券商 QMT/`xtquant` 兼容性和真实仿真验收必须在目标环境单独完成。
