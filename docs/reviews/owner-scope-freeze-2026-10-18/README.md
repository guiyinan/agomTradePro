# Owner 范围冻结与待签批包（2026-10-18）

决策编号：`OWNER-SCOPE-20261018-01`。本目录是 Owner 决定与审查证据，不维护第二套运行状态；执行状态仍由 `governance/active_plan_registry.json` 管理。

## 先交付的两份报告

1. [EVID 对人工调仓计划输出的影响与最小方案](report-01-evid-manual-plan.md)
2. [ASH-11 对 DATA-18 的依赖瘦身方案](report-02-data18-dependency.md)

两份报告均为静态核查与方案。本轮没有实施接口、权限、数据契约或交易逻辑变更，没有执行生产访问、回填、激活或下单。

## 已生效的 Owner 决定

- [范围、延期、归档、ASH-02 退出线与里程碑](owner-decision.md)
- [登记变更清单与兼容问题](registry-change-plan.json)
- `registry-history.json` 保存核查时登记表完整原件、原始摘要及各 next_gate 的原文；它是历史快照，不能代表最新运行状态。
- `report-source-manifest.json` 记录两份报告与决策页所核对源码/政策的原始和 Git LF 摘要，方便对照后续变更。

Owner 已在本聊天对技术审批第 1、2 项均选择 A，批准状态兼容修改、同步 ASH/TUX 和协调落盘。两线程已收到范围决定；ASH 明确交出治理窗口后，13 项处置已写入登记表 v276（79 单元、未改依赖、未新增单元），最终检查及保护对象核验见 `registry-application-proof.json`。

`status-compatibility.patch` 与 `status-compatibility-validation.json` 保存隔离补丁及红绿结果。`registry-application-base.json` 保存包含 C3c 提交后登记变更的历史原文；`registry-candidate.json` 保存该次落盘候选证据，不是当前状态真源。技术审批与业务方案批准分别记录；后续第 3～8 项已批准 A～F 的方案、定义或明确登记范围，见 [approval-log.md](approval-log.md)。授权范围内自动准备、核验并在满足门禁时执行，不重复请批；这些批准没有自动完成实现、真实材料核验、具体候选签字或生产写入。

## 六页集中签批

| 页 | 事项 | 状态 |
| --- | --- | --- |
| [A](decision-a-authority-root.md) | EVID-01/02 真实 single-owner authority root | 方案已批准；无自动到期；生产登记未执行 |
| [B](decision-b-independent-review.md) | 个人项目独立复核定义 | 定义已批准；具体候选复核及签字未发生 |
| [C](decision-c-financial-availability.md) | 财报日期精度与下一交易日开盘可用 | C2 方案已批准；日历/cutoff/兼容及生效边界待验证 |
| [D](decision-d-publication-tolerances.md) | 四类 Publication 数值容差 | D1 零容差方案已批准；具体字段矩阵未完成 |
| [E](decision-e-controlled-backfill.md) | 受控回填生产写入范围 | E1 已批准；范围内自动准备/核验/执行，具体参数须明确 |
| [F](decision-f-strategy-registration.md) | STRAT-01 规范登记 | 规范登记及配置扩展获批；真实自动下单默认关，用户须在系统主动开启 |

每页包含选项、推荐值、风险和回滚。签批应写明页编号、所选选项、必要的实名/范围附件、签署日期；本目录的推荐值不构成批准。

## 周发布

[周发布与首次部署计划要求](weekly-release-policy.md)。每 40 分钟进度汇报继续；发布改为每周一次，首次部署必须先提交明确候选与回滚计划供 Owner 确认。当前没有可供签字的冻结部署候选，未合并 main、未部署。
