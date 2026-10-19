# A 股开发 CI 第二批：浏览器准备与测试清理

> 历史验收原件已迁出 Git；原路径、逐文件哈希和恢复方式见[归档索引](evidence-archive-2026-10-19.md)。历史结论与当时失败记录保持不变。

本批针对 `9656229b8c2634cca20504f64807c03bba1a1153` 的实际远端失败。该 SHA 的 Architecture、Consistency、Publication PostgreSQL、Security 与工程仪表盘工作流通过；Fast Feedback 的两个 Python 版本均为 5279 passed、327 skipped、1 failed、3 errors，不能称为全绿。

## 有限整改范围

- 选中的 Account 组件旅程在 Python Chromium 安装之前运行，而原安装还受 TUI 改动标志限制。既有安装步骤移到全部运行测试之前；普通运行验证不再依赖 TUI 标志。纯文档仍沿用原 runtime job 选择规则。安装命令和版本来源保持不变。
- 浏览器旅程的事务清理会删除由迁移创建的 authority singleton，后续 0026 迁移验证因此缺行。复用既有 PostgreSQL 测试清理 helper，增加 SQLite 隔离库校验，并在该浏览器模块显式启用。只从 flush 表清单排除 singleton 表，正常业务清理继续；真实清理前后读取同一既有行，禁止重新补种、关闭触发器或删除时钟。
- PostgreSQL 保留原显式 TEST.NAME、源库不同及实际数据库身份校验。SQLite 只接受 Django 指定的内存测试库，或显式 TEST.NAME 与实际目标相同、不同于源库、位于系统临时测试目录且文件名精确绑定当前 PID 的文件库。

业务生产 Python、账本 schema、账户启用和订单均不在本批范围。ASH03 未提交的现金、成本、接口及前端实现不进入候选。

## 分阶段验证与交接

1. 保留失败工作流 `39150269037` 原始日志。新增工作流顺序反例实际失败在安装索引 8 晚于首个 pytest 索引 5；修复后该反例通过。
2. 从已提交 Git 对象重建隔离目录，核对全部 11865 个文件的真实 blob。Windows archive 的 CRLF 转换逐文件按 Git blob 证明后规范化；初次原字节校验失败记录保留。随后仅接入独立文档提交 `112f07d93f8325ff74bd3c088d593b8edd96893e` 和四个有限修复路径。
3. 在该目录运行连续 SQLite 浏览器与迁移测试，并以专用本机 PostgreSQL 测试库验证迁移及清理保护；绑定输入哈希、命令、原始 JUnit 与真实终态。最终本地结果：SQLite 连续浏览器及迁移 5 项、PostgreSQL 迁移 3 项、PostgreSQL 浏览器 3 项通过，共 11 次执行、7 个唯一节点，失败、错误与跳过均为 0。SQLite 清理时钟为 0→0 三次，PostgreSQL 为 3→25、25→47、47→69，均来自真实 singleton 查询。当前数据契约 88 面、模块地图 44 模块/209 边、完整治理一致性、架构和入口投影检查均通过；前后输入哈希一致。
4. 本地验证完成后精确提交并推送本批，检查新 SHA 的实际远端 CI。失败则修复；不以旧 SHA、局部通过、缺浏览器或跳过测试替代。

当前尚未部署、合并 main 或赋予发布资格。回退是恢复本批 workflow 与测试支持代码并重新运行检查，不涉及业务数据回滚；回退后仍需处理原浏览器准备和 singleton 清理问题。

## 可核对证据与限制

- [原始 JUnit 与命令、输入哈希、终态汇总](evidence-archive-2026-10-19.md#原件定位 "原件：artifacts/a-share-usability/ci-browser-isolation/evidence.json")。三个原始 JUnit 位于同目录。
- [静态复核](a-share-ci-browser-isolation-static-review-2026-10-19.md)：修复 SQLite 文件测试库保护后，无未解决 P1/P2。
- 本地版本为 Python 3.13.5。曾误用禁止全部 Python 网络的单元测试围栏，导致三项浏览器初始化错误；记录保留，改用仅允许本机的 Python 围栏，并保留浏览器精确同源限制后复测通过，外部网络尝试为零。另保留初次治理 helper 路径错误和工作流顺序 RED。
- 这是本地有限检查的证据，新提交的双 Python 远端 CI 仍须实际完成。未执行部署、main 合并、券商下单或完整发布验收。
