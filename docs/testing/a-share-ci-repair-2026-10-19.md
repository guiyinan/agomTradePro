# A 股开发 CI 有限修复

本批针对 `98dcea40` 实际 CI 失败，基于 `d6b5930180a18b79d628371dffe7f95cc465c940` 的纯代码导出，仅覆盖 18 个 Python 源/测试文件、收紧后的依赖预算与三份官方生成投影。未提交的 ASH03 成交保全、SDK/MCP/TUI、估值、现金和成本知识状态均不在本批候选中。

## 修复结果

- Simulated Trading 通过现有 Core runtime port 读取配置，保留截止点、profile/snapshot 身份、版本、哈希、时钟与前后重读。名义类型检查改为结构化只读 Protocol，实际字段校验保留；不声称这一检查方式未变化。
- Account 通过中立的 owner-scoped Signal lookup 注册端口解除冷启动耦合。Signal 未安装时拒绝查询；Signal 正常安装时仍校验归属。空或非字符串资产代码在价格查询与写仓前拒绝。
- Critical wrapper 显式复用执行器固定时钟夹具；SQLite schema-editor 测试使用事务模式；fake position 明确声明可卖量知识；token purpose 先验证类型再分类未知字符串。
- 官方工具重建 Data Center architecture inventory、entrypoint inventory 和 module map。模块图为 44/209；依赖预算扫描为 205 条，原 206 上限收紧为 205，Account outbound 12→11、Signal inbound 10→9。没有提高预算或类型债务。

## 实际验证

本地 Python **3.13.5**：134 单元调用、27 SQLite/边界调用、1 架构循环保护，共 **156 个唯一节点**、162 次调用，均通过且无跳过；测试进程应用 socket/DNS 拦截计数为 0。六个 position-use-case 单元节点在两组中重复，未重复计算唯一节点。

9 个生产文件增量 mypy 为 0 regression/0 legacy，全量生产 mypy 债务为 0。Black/isort/Ruff、真实架构规则与审计扫描、循环依赖、88 个 freshness 合同、官方 module-map 检查、全治理和两份 Data Center 投影一致性检查通过。

保留真实失败：初始 candidate 的空资产代码类型错误与对应两个初始运行反例；最终增加非字符串反例；依赖减少后旧预算触发 stale 保护。前者经边界校验修复，后者按实际下降收紧；没有覆盖失败记录或增加豁免。架构 delta 的输入来自纯导出的精确差异，执行的是原生产规则/审计扫描器。

[逐文件哈希、命令与结果](../../artifacts/a-share-usability/ci-repair/finite-ci-repair-2026-10-19.json)；[独立静态复核](a-share-ci-repair-static-review-2026-10-19.md)。JUnit 原件随同保存。

## 边界与回滚

本批没有业务 schema 变更，不执行数据回填、真实账户启用或下单。回退需要将本批代码、依赖预算和生成投影作为同一变更恢复并重新检查，不能只恢复预算来掩盖依赖回归。Python 3.11 和实际修复提交 SHA 的远端 CI/RC/S6 尚待运行，本地验证不是发布资格；ASH03 的其余消费者缺口继续开放。
