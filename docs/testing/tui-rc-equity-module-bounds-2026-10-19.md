# TUI RC：估值模块体积与元数据归属

`e9ea1c569103e1acb5b4ef32c65d563181ff2fd8` 的实际 CI 同时发现估值用例和 repository 超出既有体积限制，以及 DataCenter 投影过期。本批按职责将估值用例和四个纯发布事实映射器移至同 App 的独立模块，保留原入口显式导出及 repository 方法签名；不提高既有预算。

调整后非空行数为：原 use_cases 515 / 上限 1000，原 repository 723 / 上限 750，新映射器 176 / 上限 250。独立审查确认十个用例类、四个映射函数的可执行行为和签名保持一致。

- 共享源码的 150 项回归全部通过，无失败、错误或跳过；覆盖发布快照、估值 member、旧 API、TUI owner、模块体积和用例边界。
- 四个生产文件增量 mypy 与全量债务门禁通过；Black、isort、Ruff 通过。
- 三项 current-data 合同同步实际所有者。首轮漏掉 `equity.current_valuation` 两个已移动标记的真实失败原件保留；补齐后共享源码 89 项 freshness 检查通过。
- 三份结构投影均由官方脚本生成。完整私有 Git 源码叠加精确本批文件后，官方联合投影检查及 89 项 freshness 检查通过；其 architecture/modulemap 与共享结果逐字节相同，entrypoint 仅有该合同 source_files 从 6 到 7 的预期变化。150 项及类型门禁之后仅改动合同和 entrypoint JSON，生产代码及测试哈希未变。

日志、JUnit、失败原件、候选与逐文件哈希仅保存在本机 `C:/Users/muku/.codex/evidence-archives/agomTradePro/2026-10-19/equity-linecap150-types-and-official-projections/`；索引 SHA-256：`ef1e68aa207b3688c6b446ffcaa3c233e9cc6b216f11a9a64dfb6425a44f33c9`。此批不代表完整 Fast Feedback、M5、RC 或 S6 已通过。
