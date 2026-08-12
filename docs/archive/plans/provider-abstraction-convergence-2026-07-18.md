# Provider / Adapter 抽象收敛阶段计划

更新时间：2026-07-19

## 阶段目标

将 Data Center 的 provider 构造、能力路由、failover、熔断与健康状态收敛到单一运行时注册表，并退役 Macro 自有的 Tushare / AKShare / failover 采集路径及兼容 re-export 链。

## 已完成

- 新增 canonical `ProviderRegistry`，支持 repository 构造、ID/名称查找、能力路由、failover、熔断和健康快照。
- 删除 `provider_factory.py`、`providers.py`、`registries/source_registry.py`，移除 Application 层伪 provider 与重复 capability 表。
- 将低层行情客户端协议改名为 `MarketGatewayProtocol`，明确 gateway 与 provider 的职责边界。
- 将 Macro source adapters/fetchers 迁入 Data Center `macro_sources/`。
- Macro 生产同步改为 `SyncMacroBatchUseCase -> SyncMacroUseCase -> ProviderRegistry` 单链路。
- 删除 Macro 的 adapter 双路径、provider/repository re-export 与 `data_center_compat.py`；canonical fact 投影仓储改为显式命名。
- 增加结构护栏，防止旧文件与旧符号回流。
- 将 `provider_adapters.py` 收缩为 26 行稳定导出面，实现按 base、Tushare、AKShare、specialized 四个 owner 拆分，全部低于 1200 行治理阈值并解除大文件豁免。
- 新增 `shared.numeric.safe_float` 作为外部数值解析唯一公共入口，迁移 App 内 15 处 `_safe_float` 及额外的重复公开实现；结构测试禁止 App 重新定义。

## 剩余项

- 在后续独立批次评估 Macro fact 投影仓储是否可进一步按读写职责拆分。
- 独立排查 Data Center 测试套件的共享状态污染；结构契约测试与行为测试混跑时存在顺序敏感、失败用例漂移的问题。

## 回归范围

- Data Center provider registry、provider adapters、同步用例与 API composition。
- Macro source fetchers、Tushare/AKShare adapter 契约、管理命令与 Application facade。
- Macro canonical fact 投影仓储及 Fund/Alpha 等跨模块消费者。
- 合并前补齐仓库最小回归包，并显式记录未验证项。

## 已验证

- 聚焦 provider / macro source / batch sync：86 项通过。
- Data Center / Macro / canonical fact projection / Fund / Alpha 扩大单元回归：369 项通过（composition root 移动后复跑）。
- Macro / Regime / Signal / Strategy / failover / Data Center API 集成目标：首次 46 项通过、2 项暴露测试 fake 契约缺口；修复后 Data Center API 文件 6 项通过，目标用例均已覆盖。
- 架构扫描：boundary violations 0，audit violations 0；对应 pytest 护栏 4 项通过。
- 固定最小回归包：253 项通过（TUI 218、Terminal 11、SDK 22、SSL redirect 2）。
- `makemigrations --check --dry-run`：无模型变更；Ruff 与 compileall 通过。
- 公共数值解析契约：16 项通过；迁移涉及的 Data Center/Macro/Task Monitor/Regime/Audit/Equity 行为回归：147 项通过。
- provider adapter 拆分后聚焦行为回归：24 项通过；结构契约单独执行，避免与已知污染套件混跑。
- Data Center 单元行为目录显式排除结构契约后：262 项通过；结构契约独立运行：4 项通过。
- 本批 6 个核心拆分文件在跳过依赖图并屏蔽第三方 stub/传递 `Any` 噪音后 mypy 通过；完整依赖图仍暴露 119 个文件、1185 个既有错误，归入类型债务主线。

## 未验证 / 已知非本批阻塞

- 本批结束时曾保留全仓静态测试计数漂移，未在 provider 主线内重写共享基线；后续 2026-07-19 仓库治理批次已统一核实当前工作树并重基线为 6969。
- Data Center 结构契约混入同一 pytest 进程时存在顺序敏感的共享状态污染；单独运行行为包和结构契约均可通过。隔离缺陷作为后续独立测试债务处理，不与本轮 provider 重构耦合。

## 风险与回滚点

- 风险：运行环境缺少 active provider 配置时，canonical batch 会 fail-closed，不再静默构造默认 adapter。
- 风险：外部脚本若仍引用已删除的 Macro Infrastructure 路径会立即导入失败；仓库内引用已全部迁移并由结构扫描约束。
- 回滚点：保留 Macro Application 的同步请求/响应契约；需要回滚时只替换 facade composition，不恢复旧 adapter/provider 多层结构。
