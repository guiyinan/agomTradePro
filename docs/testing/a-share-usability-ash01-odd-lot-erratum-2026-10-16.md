# ASH-01 零股测试勘误

2026-10-16 复核发现，首轮盘点测试把“持有并可卖 150 股，卖出其中完整的 50 股零股余数”错误判为非法。该断言与交易所说明不符；首轮日志中这条测试通过，只证明旧实现拒绝了该订单，不能证明拒绝行为正确。

依据是上交所[《关于进一步明确竞价交易申报数量及前端控制有关事项的通知》](https://www.sse.com.cn/lawandrules/guide/stock/jyglywznylc/tz/c/c_20230209_5716007.shtml)，上证函〔2014〕301 号，发布日期 2014-06-27。官方附件以 299 股余额说明：99 股可以单独卖出，也可以和整手合并为 199 股或 299 股卖出；198 股或 298 股会拆分零股余数，不能据此放行。150 股中的完整 50 股余数因此可以一次卖出。本文只据此更正已核对的上交所规则用例，不推定所有板块和交易所规则相同。

原始证据完整保留：

- [原测试快照](a-share-usability-ash01-settlement-test-original-2026-10-16.py.txt)：SHA-256 `679b8eaabea86e5df9c253c225bfa958e5a2ad6187579da4ff68e8dcbb248099`。
- [原始运行日志](a-share-usability-ash01-red-2026-10-16.txt)：SHA-256 `73690f765407517d6bc9fa26d6984a485396f2cc5143511baf2dff08c9f41535`，当时结果为 3 failed / 1 passed。
- [原盘点摘要](a-share-usability-ash01-inventory-2026-10-16.json) 保持当时内容与 hash，不用后来的测试替换历史运行证据。

[当前测试](../../tests/unit/simulated_trading/test_ash01_settlement_regressions.py) 将错误断言替换为 150 股卖出完整 50 股余数成功、剩余 100 股，并另设 150 股卖出 25 股必须拒绝且无写入的用例。原有新仓 T+1、加仓 T+1、完整 150 股清仓三个测试保留。更正后的首次运行单独保存在 [新日志](a-share-usability-ash01-corrected-red-2026-10-16.txt)，[更正时测试快照](a-share-usability-ash01-corrected-test-2026-10-16.py.txt)保留该次源码原字节，对应摘要见 [勘误检查点](a-share-usability-ash01-corrected-checkpoint-2026-10-16.json)。这次更正没有修改生产成交逻辑。上述原件禁用 Git 换行转换，以保持跨平台读取后的原始 hash。

执行约束中的 `SELLABLE_BALANCE_TO_ZERO` 继续保持“全部可卖余额归零”的原窄语义；它不能代替上述完整零股余数规则。后续新增明确模式并分别测试，不改变旧枚举含义。受限股份、证据不完整或无法证明余额口径时，不据此开启零股例外。
