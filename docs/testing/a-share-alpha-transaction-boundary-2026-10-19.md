# Alpha 回滚前驱与 A 股读取测试隔离

2f5ec0becdaa1c9aeb98dd30cd4c5f9b81310e15 的实际 CI 双版本均为 **433 passed / 8 setup errors**，另有14项 subtest通过；四条独立工作流、无数据库 TDD 和增量质量成功，仍不能称该候选通过。先前 SQLite13/PostgreSQL13 的局部结果保留原范围。真实37目标选择集在 R1 前多运行了 Alpha 模型回滚事务测试，普通 flush/post_migrate 破坏了后续序列化恢复所需基线；最小三节点实际为 **1 passed / 2 errors**。

本批只给该 Alpha 测试导入已有单例保留 fixture，并将其唯一事务标记改为 serialized_rollback=True。其他四个普通数据库标记、所有测试主体和断言保持；AST 在排除这两个预期变化后与父版本完全相同。权限时钟仍检查原有单例和代际不倒退，不补造状态、不关闭触发器、不清空 ContentType，也不为纯单元测试强制建库。37目标全部七处事务标记经静态核对；这是已观察顺序的修复，不是对全库任意组合的证明。

本地pytest8.3.4与CI9.1.1对目录加子文件参数收集不同，最初390通过不等于441；去除唯一冗余子文件参数后，501逐nodeid核对441/441且双向差集为空。最终按等价36参数覆盖真实CI的完整37目标运行：**441 passed in 313.93s (0:05:13)**；原生PostgreSQL复用495相同冻结候选的 Alpha完整模块、R1、真实pool浏览器partial及Agent恢复链真实回执，未重复运行，为 **8 passed in 165.23s (0:02:45)**。新增文件的Black/isort/Ruff通过。完整所选测试及支持源与父版本逐项校验，除本候选外仅允许CRLF归一化差异；原件保留源码哈希、状态探针、首次CI失败、最小RED和脚本解析预检失败。没有生产代码、迁移、门控或债务基线变化。

实际采用后推送新独立提交，常规CI之外使用既有Fast Feedback的base_ref=165afa4135aeab08b855fed10cac425fce7a17bc验证累计组合，避免增量选择遗漏此次跨模块边界。新SHA结果在本文写入时待运行，不追认2f5通过。ASH03七组残项和ASH04退出门继续开放，published分析API正向member消费缺口由已协调TUX主线处理；没有部署或生产激活。[精简证据索引](a-share-alpha-transaction-boundary-evidence-2026-10-19.json)中的原件仅本机可用。
