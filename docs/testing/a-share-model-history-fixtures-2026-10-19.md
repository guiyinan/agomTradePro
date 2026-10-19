# 行情历史 HTTP 夹具契约修正

本批只修改 `tests/api/test_equity_api_edges.py` 的两条历史行情 HTTP 用例及其共享 provider 替身，不修改生产代码。以 `cddd39816c8f7f1517e23cecbcb7b3060b32bc7c` 的源码为输入；本地实际测试库为独立原生 PostgreSQL，Python 3.13.5。

原回归包实际为 **475 passed / 2 failed**。两条失败发生在 provider 替身缺少当前协议要求的 `provider_id`，尚未到达股票池逻辑。补齐身份后，两条用例又实际失败在旧的隐式缓存写入预期；两轮失败均保留，不追认为通过。

历史技术分析和市场状态相关性入口仍显式请求 hydration。本批仅在这两条测试中提供明确的空 hydration 结果，再走真实 model-history fallback、规范化与 HTTP 输出；用目标资产全部20个持久字段的前后快照检查该受控 fallback 没有写入，保留原蜡烛图及相关性断言。它不证明所有历史 GET 只读，也不改变 hydration 授权或持久化行为。

修正后的两个 HTTP 节点及已有跨源一致性只读反例 **3 passed**；受影响 API 完整模块随后 **55 passed**。两组有重叠，不相加。本地回执来自同时含有尚未采用股票池候选的隔离组合副本，因此不能称为纯父版本验收；三路径提交后的独立源码验证按该 SHA 的实际 CI 另记。Black、isort、Ruff 通过；无生产 Python 改动，因此未新增生产类型检查，也不借此宣称原477项包重新执行通过。

源码、命令、JUnit、失败和静态复核原件见[精简证据索引](a-share-model-history-fixtures-evidence-2026-10-19.json)。归档仅本机可用。此批独立提交，不关闭 ASH03/ASH04，不构成 RC/S6、Owner 或生产验收。
