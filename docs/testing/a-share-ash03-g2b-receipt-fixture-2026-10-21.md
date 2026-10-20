# G2B4 收据测试夹具修正（2026-10-21）

d35a7eb2 的 Fast Feedback 在 Python 3.11/3.13 各出现同一失败：损坏收据未被拒绝。测试 helper 从规范快照重建收据，覆盖了调用方刻意设置的错误哈希，反例实际没有保存损坏数据。

本批恢复直接保存调用方 receipt 的语义，仅重绑新 Trade 主键；保留 V1/V2 字段、全部15个测试函数及断言。生产读取、哈希绑定和严格拒绝逻辑未改。修正后 RowReader27 与 RequestReader5 共32项，在 SQLite 与 PostgreSQL 各完整通过，均无失败、错误或跳过。格式检查和独立静态审查通过；测试文件未改变模块结构或 ORM，无新增生产 Python 类型检查范围。

原始失败日志、候选、JUnit和运行回执仅本机归档；具体摘要见[证据索引](a-share-ash03-g2b-receipt-fixture-2026-10-21.json)。新提交的 CI 需按实际结果另行取证，本地结果不代表完整 CI 或发布资格。首次 BUY writer 与后续 V4 pending、来源组合及恢复继续分批交付。
