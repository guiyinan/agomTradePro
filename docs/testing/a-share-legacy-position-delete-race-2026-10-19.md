# ASH03：关闭 legacy 持仓删除竞态

> 历史验收原件已迁出 Git；原路径、逐文件哈希和恢复方式见[归档索引](evidence-archive-2026-10-19.md)。历史结论与当时失败记录保持不变。

本次交付收敛一个有限并发缺陷：统一账本读取 closed legacy source 时，在既有 portfolio/account 锁内重新读取并校验源持仓；删除路径将统一持仓、映射和 legacy source 的删除纳入同一事务。已有有效映射仍幂等返回原统一持仓。生产修改只涉及两个 application 文件和一个 repository 文件；未增加模型、迁移、账本或外部来源。

验证分阶段记录，不能把不同快照的用例数相加。原生 PostgreSQL 两连接模块在 310 运行中 3 项通过、无失败、错误或跳过；309 的三文件增量 mypy 与完整 debt ceiling 均为 0。302 的五模块回归为 92 项中 90 通过、2 失败；308 的纯 ed03 基线复现了相同两项 owner-close 失败，并同时复现修复前的并发竞态。这两项 close 失败源于旧持仓没有可证明的可卖余额，和本次 closed-source/delete 分支不同。

Root 的 313 exact Git candidate `eb7659c8a9f2ba4210f89a38e7204147331317c8` 绑定五个 owned 文件及 base `2cd7f1efd8761c31edbda1d661e5358cebed7de9`；architecture delta、文件增长和 whitespace 三项回执均为 exit 0。298 的架构、循环依赖、current-data 与 module-map 结果也通过，但其服务文件字节属于较早格式化快照，作为辅助证据保留，不当作最终字节门禁。完整的每阶段日志、JUnit、结果回执、输入哈希、测试源和 review 见 artifact `artifacts/a-share-usability/ash03-legacy-position-delete-2026-10-19/` 的 `evidence-index.json`。

范围只覆盖这一删除/承接竞态。反向映射歧义、Owner M2/M3、券商对账以及 RC/S6 仍按各自阶段处理；本记录不代表整个 ASH03 已关闭。
Git 文本规范化核对：五个 Windows 验证文件与 Git LF blob 仅有 CRLF→LF 差异，逐字节规范化比较相等；Git blob 与 Source313 源码候选逐字节相等。各自 SHA-256 记录于 evidence-index 的 `git_text_normalization`，不将两种字节表示混称同一哈希。原始日志与输入仍按原字节保存。
