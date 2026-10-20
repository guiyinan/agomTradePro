# ASH-03 G2A：模拟成交回执持久化与只读重放

本批完成本地验收，作为 G1 后的独立开发提交。范围是保存事件/经济快照及不可变回执、校验完整成交链，并按账户所有者读取精确事件；尚未接通原子成交写入或用户部分成交流程。ASH-03 整单元仍未完成，registry 的 ASH-04 焦点和 ASH-07 前置保持原样。

## 实现范围

- Domain 验证成交数量、限价、冻结 Fee V2、累计费用和预留资源守恒；Application 通过注入端口读取事件、结算证明和已保存结果。
- 新增 append-only `SimulatedOrderFillReceiptModel`、0036 迁移及 V4 交易绑定；事件命名空间/ID、序号、源快照、经济快照、原计划和交易行互相绑定。校验和只证明一致性，不替代来源授权。
- 读取器先按 owner/account/order/event 精确查询。已保存事件可在账户停用或订单终态时重放；新事件仍要求可用账户及可验证的封存计划。读取无账本写入。
- 有任何成交回执或 V4 历史时拒绝反向删表；V0–V3 条件保留，并核对运行时模型与迁移状态一致。

## 实测结果

Python 3.13.5、原生 PostgreSQL 16 专用测试库，使用真实迁移。32 项 snapshot codec、216 项 Domain/Application/supporting codecs、77 项数据库组件测试均通过，各组零失败/错误/跳过。另 6 项迁移定向复验全部通过，已包含于最终77项，不重复累计。

全部14个生产文件通过增量 mypy，默认生产类型债务为0，未改债务基线。26个文件通过 Black/isort/Ruff；生产文件均低于1000非空行。官方模块地图、ORM 数据字典、测试分层及 Data Center 投影构建/检查、架构/循环依赖、新鲜度合同和治理一致性检查通过。

覆盖率为 branch 模式的综合覆盖率，逐文件验收；仅合并三个精确绑定的通过数据片段，失败的 PostgreSQL 运行未参与汇总。

| 文件 | 实测 | 最低要求 |
|---|---:|---:|
| `simulated_account_trade_models.py` | 96.13% | 60% |
| `models.py` | 77.89% | 60% |
| `order_fill_receipt_models.py` | 94.44% | 60% |
| `order_reservation_fill_row_reader.py` | 86.27% | 60% |
| `order_reservation_fill_request_reader.py` | 72.48% | 60% |
| `order_reservation_fill_settlement.py` | 92.31% | 90% |
| `order_reservation_fill_calendar.py` | 89.04% | 80% |
| `order_reservation_fill_calendar_codec.py` | 77.57% | 60% |
| `order_reservation_fill_binding_codec.py` | 87.88% | 60% |
| `domain/order_reservation_fill.py` | 94.92% | 90% |
| `order_reservation_fill_chain.py` | 100.00% | 90% |
| `application/order_reservation_fill.py` | 89.49% | 80% |
| `order_reservation_fill_snapshot_codec.py` | 85.99% | 60% |

## 失败与证据

保留旧 Domain 对数量、买卖限价及冻结费用四个跨字段反例的真实失败；不把缺模块或环境失败当作行为红测。较早 Application/calendar 测试稿没有有效的实现前行为红测记录，本批如实记录为当前源码的实现后验证。

集成中修复了迁移重复关键字和模型约束不一致；测试侧修正缺失的 ledger fixture、V2/V3 构造误标、内存/数据库状态混用及 Receipt→Reservation→Trade 清理顺序。覆盖率 append 和探针设置选择错误的原始失败也完整保留。

源码、命令、退出码、JUnit、覆盖率和逐文件摘要见[机器索引](a-share-ash03-g2-fill-receipt-reader-2026-10-20.json)。完整原件仅在本机 `artifacts/ash03-g2-fill-receipt-reader-2026-10-20/originals.zip`，SHA-256 `406635c3caac203f858d544cb45df787fdb4c537b4342c4316a8f0b3da20fa88`；尚未上传。G1 基线为 `26ed7080ab6d`，另同步已提交 peer 变更 `a1a50e8c1a18`，保留其 QMT 合同新增用例。

## 后续批次与回滚

下一批接入同一事务中的账本、hold 消耗、Trade 和 Receipt 写入，再补 V4 普通读取/汇总、待结算释放、合格来源组装及停机恢复。原第4–7组残项继续按原计划执行；本批测试不证明外部来源、券商成交、实盘、生产迁移或最终提交的 CI 已通过。

保留 G1 的持久预留保护；有历史行时禁止以反向删表回退。应用回退必须识别存量 hold 和 V4/回执历史，不能退回绕过预留或无法解释已有成交的写口。

## Security CI 后续修正

`44dc9ec062bc` 的 Security Scan `39368809971` 实际失败，命中两处 `generic-api-key`。独立审查确认它们分别是公开协议版本标识及测试订单幂等键，不具有认证用途。本批仅在 `.gitleaks.toml` 为这两行增加“精确完整行且精确路径”例外，保留生产/测试源码和协议字节、全部默认规则、扫描范围及 `.gitleaksignore`。

使用与 CI 一致的 Gitleaks 8.24.3，并核对官方下载包校验和：旧规则扫描原提交范围复现2处命中；新规则同范围及原文件分别为0。另在两个原文件加入仿真凭据、把两段公开文本复制到未获准路径，4处负控均被检出。原CI失败和本地输出仅本机归档 `artifacts/ash03-g2-fill-security-2026-10-20/originals.zip`，SHA-256 `b767161464cb0a3ed369b5ac72c7e5d6c3570f4a20f6e807e029d8d71f5ede31`。这项修正的实际提交CI仍待结果，不改写原提交失败或G2A验收边界。

## 跨后端终态读取夹具修正

`44dc9ec` 的 Fast Feedback `39368809935` 在 Python 3.11/3.13 均实际为 1失败、723通过、42跳过；失败来自 terminal-miss 测试把夹具中未持久化的部分成交对象用于取消更新。修正只在该测试先刷新数据库父行，并确认 active、成交/消耗/释放均为零，再据此计算取消；生产代码、数据库约束及终态/停用账户/错误所有者断言保持。

本机先复现原测试1失败、0错误、0跳过，再验证整个文件在 SQLite 和原生 PostgreSQL 16 各5通过、0失败/错误/跳过；这是同样5例的两后端验证，不计为10个唯一用例。Black/isort/Ruff通过，未改生产Python，不重复类型门禁。原CI失败、本机失败及最终输出仅本机归档 `artifacts/ash03-g2-terminal-reader-fixture-2026-10-20/originals.zip`，SHA-256 `f64ed21046c77fff0023bbd388a51bdb10c0d90f6a2b917832af2f86a7c7bfaa`。该修正仍未验证真实持久部分成交后的取消数值差异，G2B需独立覆盖。

安全修正提交 `d2ce8372` 的 Security `39370311949`、Architecture `39370311994`、Consistency `39370311924` 和 Fast `39370311920` 已实际通过；其双Python增量范围各74例未覆盖上述失败用例，不能替代本次修正验证。本次后续提交的实际CI仍待结果；不表示原子写入、用户部分成交流程、停机恢复、ASH-03整单元或Goal完成。
