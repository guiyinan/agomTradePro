# ASH-07 模拟组合风险开发交付与剩余退出门

2026-11-03。业务提交 `4327cfa9349048369a46009864f8c6597817b8c7`；CI 修复提交 `850e4b5f90ecd51ac83d5e5419a50b59d21904bf`；生成治理补齐 `6ba594e347fc434f4436116c5eb0ef96485c1dc5`。ASH-07 与 Goal 保持 **active**；真实公开行业来源的允许正例尚未完成，不能据此关闭整单元。机器状态仍读取 registry，范围见主计划 §19.157。

已交付版本化行业/ETF 暴露与部分覆盖上界、量/额窗口容量、真实现金/持仓/有效预留/拟新增订单的保守投影；计划与三个普通模拟写入入口复用同一来源/政策/资源重验，未成交 SELL 不释放暴露或买力。沿用既有账本、RiskPolicyAudit 和 Scenario，保存原始报告及输入/结果快照；普通用户可从 TUI 选审批情景、确认分析、查看来源/限制并回放原报告。来源规范化入库命令默认 dry-run，原件 SHA 与结构校验不冒充供应商语义审核。

首轮新提交 CI 的四类失败已按实际原因修复：配置证据改用既有 Core 中立桥而非新增 App 依赖；静态扫描纳入已拆出的行操作源；测试中的非秘密标识改用已有情景别名/简短幂等键，未抑制安全扫描；补齐 SQLite seed 的事务方式、日志捕获及显式历史测试时钟。压力表单预检无效后可以立即纠正重试，只清除属于同一表单且等待期间未变化的 trigger；真实请求的防重复保护保持。

| 最终验证范围 | 实际结果 |
| --- | --- |
| R25 原生核心/政策/压力专项 | 163 passed；生产代码此后未变，按精确 SHA 复用。 |
| R26 前端完整组 | 213 passed；固定点击时钟验证立即纠正提交，迟到目录响应不能覆盖新账户。 |
| R28 SQLite 兼容事项 | 11 passed；复用同一 schema，使用保护规则要求的临时目录/PID 身份，未修改保护规则。 |
| R29 原生模型与普通用户 | 5 passed；含完整 TUI/session/CSRF/API → Scenario ORM 存证 → 同键原报告回放。确认前、只读 GET 和重放不新增财务写入。来源端口明确 synthetic，不能当真实源正例。 |
| R24 静态门禁 | 8 步通过：5 文件增量 mypy 0、全库债务 0、Ruff、架构、App 依赖边 206、模块图、TUI 静态契约及 104 项数据契约。生产文件 SHA 后续完全未变，未重复重测。 |

隔离环境未初始化 production coverage universe，独立后台 GET `/api/tui/operator/governance-queue/` 的精确 `MISSING_CONFIG`/503 拒绝被显式核验；其他 HTTP/console/page/network 错误仍失败。本记录不授予生产 readiness。

第二轮 HEAD `5e9d64ae` 的 Python 3.11/3.13 目标测试、NoDB TDD 和 TUI runtime 全部通过，聚合失败仅来自两份生成清单未同步。现已由生成器更新 Data Center architecture/entrypoint inventory，并精确登记现有压力分析 evidence POST；R30/R31 的其余适用一致性检查通过，未抬预算、放宽权限或重复业务测试。最终 HEAD CI 仍独立留存。

后续 CI 的唯一类型诊断来自既有 repair command 的 Kombu `import-untyped` 忽略在新版包中失效。已用同一具名异常的第三方类型边界兼容有/无类型声明的 Kombu，未改依赖或捕获行为。R33 单文件增量、全库债务 0 与相关静态门通过，4 项完全 mock 的 Alpha/队列边界测试通过；入口投影跟随更新并验证，未执行修复命令或重复组合业务 QA。候选身份与前序链见 JSON/原件索引。

当前原件索引 `.tmp/ash07-risk-20261103/integration/typing-boundary-validation-index.json`，SHA-256 `4f712ebc7b2ed964d71c4eb6ec93c011a8cf6402a30c91bb59cd3909f305aa99`。原有开发索引保持不变，并由新索引引用；逐次候选、命令、失败、JUnit、截图/诊断与复用边界均留在 `.tmp/ash07-risk-20261103/`，未声称上传远端。R24/R26/R27 的失败原件保留，没有把其整批拼成全绿。精简机器索引见[同名 JSON](a-share-ash07-portfolio-risk-2026-11-03.json)。新 HEAD 的 CI 独立查询并写入 JSON 指定的回执路径，不以本地结果替代。

后续官方来源复核已补足当日成员观测与版本依据：国证 `queryStockSylDetail` 的 116 条金融成员明细行自身带 `tradeDate=2026-11-03`，包括 600036/601398；标准原件明确“2019年修订”。可保守表示仅该日的 bounded 成员事实，不把 2026-06-15 批量调整日当逐股首次生效日。真实首次已知为 2026-11-03T13:59:36.774295Z。现有契约仍要求 source-origin `available_at/valid_until`；原件未提供，不能把政策年龄期限填成供应商失效期。需 Owner 选择保持该阻断，或批准独立的有限模拟接纳期限/可用性证明语义，保留供应商发布和失效字段 unknown。实际审批政策、来源 pin 与限制尚需运行态核验，单测阈值不作审批依据；真实源完整正向仍未通过。510050 Q3 前十 44.56% NAV、H1 74 名 94.78% NAV 的披露时点与残余上界不改写，不索要实仓或统一等待盘中。

REF-01/05 仅只读；REF-02/03 缺 REF-01 正式退出和串行交接，REF-04 缺 REF-03，REF-06 仅在确认具体安全缺陷并交接后才可能窄修。本批未实施 REF，不改变 Owner v297 的可持续性排序。ASH-08 整单执行/续办/重审批、ASH-06/09/12、实仓、自动下单、部署及同 SHA RC/S6 均未获本记录资格。

本轮来源复核只新增原件/候选草稿与审计，未运行 QA、准入写入、启用政策或写账本。代码候选 `3fdf52be1b9922dd121d33239de03905bec9f03c` 的七项适用 CI 均已完成 success；复核原件索引 `.tmp/ash07-risk-20261103/integration/source-qualification-followup-cnindex.json`，SHA-256 `88fd34b534e9fe501b7c550f6f1a4efadf8bb0b68ead3b760bb66f122f132ab8`。
