# ASH98 有限 CI 批次静态复核 29

结论：基于 `.tmp/c98/overlay-28.json` 和完整归档 `.tmp/c98/s` 的静态复核，9 个生产文件的有限改动未发现真实 P1/P2 阻断，也未发现需要扩成新治理或架构工作的缺口。overlay 标注 base `d6b5930180a18b79d628371dffe7f95cc465c940`，包含 18 个源文件、3 个官方生成投影和 1 个 module-cycle policy；`contains_ash03_feature_wip` 为 `false`。本结论只针对该有限 CI 批次，不是 B1 或生产资格判断。

Signal 归属路径是单向且 fail closed 的：Account 应用和持仓仓储依赖 `core.integration.owned_signal_asset_code` 的 app-neutral Protocol；Signal 的 application-owned 查询从 Signal repository 取快照后核对 `user_id`，`SignalConfig.ready()` 注册该 callback。没有 callback、无归属信号、错误用户和缺失行都会得到 `None`；用例在价格读取前拒绝，实际 `PositionRepository.create_position_from_signal()` 在写入前再次核验。注册本身只保存 callback，不触发查询。未见 Account 到 Signal Infrastructure 的新增 import 或启动环。

有一个非阻断的窄类型债务：`CreatePositionFromSignalUseCase` 仍保留可选 `SignalSnapshotRepositoryProtocol`，其返回值是 `dict[str, Any]`，仅用于注入分支；该分支核对 owner，随后真实 PositionRepository 仍会再次核对。当前归档中没有生产构造点，调用点只出现在测试。默认生产分支使用有类型的 asset-code registry，所以这不是本批次的 P1/P2；后续若增加生产注入点，应将该 seam 收窄成明确 DTO。

Config Center runtime seam 位于 `core.integration.config_center_runtime`，只暴露 app-neutral Protocol 和精确 `None`/DTO 返回类型；Simulated Trading composition 没有新增 Config Center Infrastructure 依赖。当前参考选择会校验 profile 与 snapshot 版本、环境、哈希、时间和完整 selector，并在读取固定快照后重读 profile/snapshot；无 profile、无选择、缺 identity 或 timezone 时，trade use case 遇到缺少 exact identity/calendar 会阻断。runtime `None` 没有变成默认值或猜测值。

Token 与 selector 的 purpose 检查顺序和类型语义正确：Calendar token 先要求 `purpose` 是精确字符串，再比较常量；selector 对 `purpose` 同样要求精确 `str` 后再比较。JSON 对象键集合精确、重复键/浮点/非规范 JSON 被拒绝，日期、UTC 时间、digest、actor/session/database binding 都有明确窄化。执行日历的可空 runtime timezone map 在缺失时返回 unavailable/block，不静默使用系统时区；值最终还会经 `CalendarPublicationReference` 校验为有效 ZoneInfo。

启动路径保持轻量：新 Signal 注册不查数据库；Simulated Trading current-reference factory 构造 reader、Risk reader 与默认库 repository，不在 factory 中读取 selector、行情、calendar 或账本。代码有意限制此路径为 Django default database；trade reader 与 UOW 都使用默认 alias，文件 docstring 也明示这一点。

预算没有抬高。归档中的 cycle policy 从前像 v25 的 206 app-import-edge 降为 v26 的 205；Account outbound 上限从 12 降至 11，Signal inbound 上限从 10 降至 9；双向 allowlist 和 cycle components 仍为空。治理 baseline 未列入 overlay 的 source list，未看到通过该批次提高测试规模、模块规模或 mypy 债务基线的变更。

验证边界：我只读了归档源码、overlay 与旧 cycle-policy 前像，没有执行项目导入、QA、测试、数据库或 Git。Root 提供的 133 unit、9-file mypy、full mypy、architecture/cycle、26 SQLite 和治理检查结果作为外部运行记录引用，未在此独立重跑；projection 最终检查状态以 Root 最终记录为准。

---

# ASH98 静态复核补充 32

核对 `.tmp/c98/overlay-32.json`、其列出的归档后像和 `pre-source-32` 前像。overlay 声明只新增拒绝非字符串资产标识的守卫及对应反例；两个后像 SHA 与 overlay 中记录一致，逐行差异也仅涉及这两处。

在 `apps/account/application/use_cases.py` 中，共同守卫现在要求 `asset_code` 是非空 `str`，位置早于行情服务调用。因此旧注入快照中 `dict[str, Any]` 的非字符串 `asset_code` 会在进入价格查询前被拒绝；守卫也让后续价格调用获得收窄后的字符串值。测试把参数类型标为 `object`，覆盖 `None`、空串和整数 `1`，并断言价格查询与持仓写入都未调用。

兼容 Protocol 仍声明 `get_signal_snapshot(...) -> dict[str, Any] | None`，所以映射整体的 `Any` 注解债务仍在；本次只证明资产标识在价格边界前已做运行时收窄，没有改变 Protocol 或引入新的生产注入点。前像/后像 SHA-256：`use_cases.py` 为 `05817DE5…13C8D43` → `0E043ADB…B098F637F`；测试为 `931F6D2E…ECC09183` → `CC1B1DC0…502F7D83`。本次只读静态核对，未运行项目导入、QA、测试、数据库或 Git。
