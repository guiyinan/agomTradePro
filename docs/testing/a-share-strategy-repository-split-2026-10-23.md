# 策略执行日志仓储拆分验收（2026-10-23）

本批完成职责拆分及适用本地检查。父提交 `51d1bdd9288a9c3ad733714b1b152fe2a1ecb3c7`；候选 `ash03-strategy-execution-log-owner-51d`，候选快照 SHA-256 `583ab1d6396bbfddfd4214cb78edebf7df34b965d1062b1f78b239d1eff964aa`。新提交 CI 与完整发布资格另验，生产验收保持 `null`。

从策略仓储抽出 `DjangoStrategyExecutionLogRepository`，旧 facade 继续导出同一类对象；类 AST、方法、日志名称与调用路径保持。原 facade 非空行数从 983 降至 869，原 950 行门槛不变，新 owner 上限 160 行。两个结构测试补充新 owner 的大小、身份和依赖方向约束；未改变交易、日志持久化或异常处理行为，没有模型迁移或新接口。

| 验证范围 | 实际结果 |
| --- | --- |
| 六个完整测试模块，PostgreSQL / SQLite 串行 | 各 47 passed，均零失败、错误、跳过及 HTTP 尝试；整批 352.538 秒 |
| Black / isort / Ruff | 四个候选 Python 文件通过 |
| 增量 mypy / 默认全库债务 | 两生产文件通过；债务为零，未调整基线 |
| 完整及增量架构（含 audit）、循环、治理 | 全部通过；增量命令同 HEAD 时实际读取暂存差异 |
| 原有增长门禁函数与结构预算 | 零违规，未放宽原上限 |
| 官方模块图生成 | `scripts/build_module_map.py` 通过；只更新模块图投影 |
| 隔离联合投影检查 | `scripts/check_data_center_governance_projections.py` 返回 0，157.362 秒；架构、入口和模块图均一致 |

六模块为结构测试、文件大小门禁、策略仓储生命周期、R9 选择状态、订单意图仓储和执行编排幂等测试。原生 PostgreSQL 使用专用测试库，SQLite 隔离；QA 前后 7,486 个 Python 输入一致，其中外部 ITA 文件只作保全输入。双库 receipt SHA-256 `226e162429905242de95fe647a8b2cb9b34c29ef750d3ceb7ca8c983b3f669ce`，冻结输入 SHA-256 `5165c25fa30a7537d804798ff42ee4312cbad09525be0aa080372a2930bf54e0`。

保留两次真实失败，不将它们改记通过：主 Source 联合检查超时，外层 255.136 秒、实际 child 预算 254.938 秒；随后隔离检查官方命令通过，但包装程序在恢复时错误要求原子替换后的 inode 等于旧 inode，整次包装以 exit 1 / `restoration_review_required` 结束，总计 206.141/900 秒。原 receipt SHA-256 `6a1032fe31240c762fea210d28130c4d50c9cb6bc8a44dd1da3ae39c5730fb22` 未修改。

Root 另行独立核验 10,403 个基线文件 SHA 全部恢复、三份投影 SHA 与 mode 全部恢复、额外 Python/未登记文件均零；三个 inode 的变化符合 R4 `stage_replace` 原子恢复行为。16 个自有/外部文件 pin 和原 Git index 未变，已退出 controller/child 的创建身份均无活动进程，核对精确 token 后释放锁。独立凭据 SHA-256 `04ec0e3f98bb61c81f06880caacdff203a2899db84c955f7168d392d46e07e5e`；没有重跑官方检查、重写原失败或修改 WORK 内容来制造通过。

全部候选、完整命令、日志、JUnit、输入映射、原失败与独立恢复凭据集中于本机单一索引 `artifacts/strategy-execution-log-repository-2026-10-23/INDEX.json`，SHA-256 `33df0cdd6ee8d46e41d4060401a8c81ea26a1e75be2122dbf37b8e18799e1adf`；原件仅本机可用。模块图 SHA-256 `fbe6b92c20075a8524f4ecb00909dac0d8c8917e86c8b3fe429e19ff9dde536a`。完整日志及重复源码不纳入 Git。

本批交付四个 Python 文件、模块图、本记录和主计划 §19.103，共七条路径。机械拆分保留现有异常处理和数据语义，不构成策略日志行为整改；固定旧候选的其他失败、完整 RC/S6、613 账户九项实际验收、M1 与 ASH-03 整单元仍待完成。未部署、未写生产配置/账本/订单，Goal 未完成。
