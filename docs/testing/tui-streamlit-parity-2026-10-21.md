# TUI 仪表盘等价验收（2026-10-21）

本批基点为 `54cd6b8d411ec6a8ca58424330e94a7971f4ff3e`，对应本提交中的 TUI/API 补丁。Owner 已批准先补齐 TUI 验收，再退出 Streamlit；本页记录开发验证，不代表最终冻结 SHA 的完整 RC、S6 或生产 UAT。未部署、未启动观察 T0，TUI-02 尚未关闭。

## 行为与边界

- 宏观四象限显示四项真实概率、当前标记及增长/通胀轴说明；源观测日与查询截止日分开。过期、阻断或概率不完整时不展示可用于决策的当前分布。置信度明确使用百分数单位。
- 本人组合资产历史使用实际每日记录，支持近 30/90/180/365 天与全部历史，空历史保持为空。金额与收益率单位分开；后创建账户不进入早期收益率分母，未知或非正初始资金使收益率保持未知。
- 本人信号状态与最近最多五项已批准信号复用现有归属查询，与全局管理分开；保持认证、权限及原有接口字段。
- 保留 `/api/dashboard/v1/*`、登录保护的 `/dashboard/` 和 Classic 模板。本批尚未删除 Streamlit、修改依赖或创建 S6 测试身份。

## 实际验证

| 检查 | 结果与限制 |
| --- | --- |
| 第一轮选定回归 | 出现 metadata schema 与旧 mock 兼容问题后主动中断；没有完整终态 JUnit，不计通过 |
| 第二轮同选集 | 437 passed、3 failed；新面板预期及测试间缓存节流污染已修正，生产节流未放宽 |
| 第三轮同选集 | 440 passed、0 failure/error/skip，440 个精确 `(classname, name)` 身份，943.60 秒 |
| 宏观浏览器用例 | 2 passed；包含四项概率、小于 1 的百分数、窄屏与契约漂移关闭行为；使用合成浏览器夹具 |
| 后续方法拆分 | 为满足 1000 非空行增量门禁，将三个宏观方法移入专用 mixin；完整方法 AST、剩余类体与格式化前后 AST 等价；随后定向回归 3 passed |
| 类型与风格 | 修改的生产文件增量 mypy 通过；拆分后全库类型债务 0；Black/isort/Ruff 通过 |
| 合同及生成物 | current-data、TUI 静态合同、metadata 一致性、copy-density、presentation、迁移清单、模块图、架构审计及最终 runtime build/check 通过；统一 Data Center 投影检查通过 |
| 测试层级投影 | 从基点归档加本批七项测试文件覆盖，在私有源执行原 `scripts/test_tier_inventory.py --write --check`；排除共享树中两项外部未提交测试后生成通过 |

440 项完整回归发生在纯 AST 方法拆分之前，不冒称拆分后的完整重跑。第三轮选集为四个 API 文件（dashboard edges/performance parity/signal parity、regime edges）及四个 unit 文件（workbench、performance curve、signal parity、regime parity）。最终发布候选仍需绑定同一干净 SHA 完成全部必需 CI、累计 Manual Full Fast、独立 Publication PostgreSQL、完整正式 RC 与全新 S6。

## 本机原件索引

以下路径均为仓库内 Git 忽略的本机原件，未声称远端持有；完整日志和源码副本不提交 Git。除另列路径外，前缀为 `.tmp/tui-rc4-followup/`。

| 原件 | SHA-256 |
| --- | --- |
| `parity-regression-r1.log` | `d9af89f6c6ac9ce82878d5dad7c204af23109a72b7d166956567ed1dad98f12f` |
| `parity-regression-r2.log` | `339e3885ce3e2e5e09662aaa308dfc18e7fa6ee59d6a744acb55887ca30d22ea` |
| `parity-regression-r3.log` | `bf361cd6d06371ef80de1f7b43f41c518bdd7cad5bce87c1760091b4c5c42511` |
| `.tmp/tui-parity-qa-r3/junit.xml` | `d143848fd3abe61f5212ec51f5138d402994ea8e9e2fec24793632ea1a884602` |
| `regime-mixin-extract-r1/ast-proof.json` | `dbd067ac5895bab72d8605b7b5387849120d36371213ed74994ba1f84f9eed49` |
| `regime-mixin-extract-r1/format-proof.json` | `3e6125b724ca365186ef4c2f3b3247946c35e96933770f89b436db1c2d56a73b` |
| `parity-mypy-debt-after-extract-r3.log` | `def6c561b37227470bcda90c8450d9837ca85dd34af34d05e7d6af2afdf85ab1` |
| `parity-all-projections-r3.log` | `89b87be00e7c7a54e5ade8ea83ecf3953f8e032a5a367d7826ea8ca1931d37ec` |
| `parity-tier-candidate-source-r1/manifest.json` | `537421d46fa50547c1679de3b88c38bdd2054f85d18fb53f8e0079ad6d168144` |

保留失败和中断原件。合成账号及夹具只证明测试行为，不能替代生产逐项验收或独立人类复核；`production_manifest_review_satisfied=false`。后续百分比单位修正、侧车退出与依赖锁更新各自提交，A 股窗口按明确交接执行；新的有限基点必须显式登记，不能拼接不同 SHA 的资格证据。
