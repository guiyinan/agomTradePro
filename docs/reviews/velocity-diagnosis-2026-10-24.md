# 推进效率诊断：基建吞吐挤压业务燃尽（2026-10-24）

> 历史材料说明（2026-11-02）：保留原观察与建议，不作为当前 CI、执行焦点或施工授权。未找到本文三项建议的独立处置记录；后续行动以当前注册表、主计划及 Owner 后续显式授权为准。

> 目的：向 Owner 呈报"打转"现象的量化证据，并请求三项处置决定。本文只诊断、不改代码、不改 registry、不改变任何单元状态或焦点。
> 观察窗口：2026-10-20 → 2026-10-24，分支 `dev/next-development`。

## 1. 现象与量化证据

### 1.1 业务提交占比持续走低

最近 4 天共 109 个提交，其中仅 35 个触及 `apps/` 业务代码，74 个为纯基建（tests/ci/docs）。业务提交逐日递减：

| 日期 | 触及核心业务 app（simulated_trading/account/risk_center/portfolio）的提交数 |
| --- | --- |
| 10-20 | 5 |
| 10-21 | 10 |
| 10-22 | 4 |
| 10-23 | 4 |

`tests/` 是被改动最多的目录（153 处文件触及），超过 `apps/`（136 处）。

### 1.2 nightly 套件反复诊断无收敛标准

`.github/workflows/nightly-tests.yml` 在 4 天内被 5 个提交连续修改：`diagnose component suite capacity` → `trace stalled nightly test finalization` → `avoid watchdog dumps during postgres cleanup` → `allow bounded nightly reporting diagnosis` → `isolate nightly component workers`；工作树中仍有第 6 版未提交修改。未见"修到何种状态即停止诊断"的退出标准。

### 1.3 长期半开环

以下文件自 2026-10-20 起持续处于"已修改未提交"状态，跨多个工作窗口未落地：

- `.github/workflows/ci-publication-postgres.yml`
- `.github/workflows/nightly-tests.yml`
- `docs/INDEX.md`
- `scripts/prepare_s6_candidate_source_snapshot.py`
- `tests/unit/ci/test_publication_postgres_workflow.py`

另观察到命令笔误垃圾文件反复出现（`({status`、`e.txt`、`o.txt`，均为 0–110 字节的 shell 重定向/Python SyntaxError 产物），来源命令未修复。

### 1.4 外部 CVE 反复打断发布门禁

Security Scan 一周内两次转红，均为新披露公告命中既有依赖（10-21 `pip-audit=8` 经 Streamlit 退役解决；10-23 `AUDIT_COUNT=5` 命中 dev 依赖）。每次均需主线带宽处置。

## 2. 非打转部分（单向门，不回退）

以下成果本周真实关闭，不回退：

- ASH-03 §7 第 1 组（订单预留与四种现金状态）关闭，G1 验收；
- 第 2 组底座、原子成交写入、首笔 BUY、V4 到期释放、读取兼容、写邻居保护（G2A/G2B1–G2B7）本地验收；
- M1 只读调仓预览及 owner 范围临时目标预览交付，普通用户正向旅程本地通过（`production_m1_acceptance=false` 保持）；
- Streamlit 退役及 Security Scan 修复；
- 有界并行与 M1 先行机制落地（registry v288）。

## 3. 诊断

自我强化循环：治理门禁要求高 → CI/测试基建抖动 → 带宽被基建吸收 → 业务燃尽变慢 → 缺口迟不关 → 更多诊断与加固。最近 48 小时该循环明显。基建工作并非全无价值（第 3 组停机恢复需要稳定的双库证据链），但当前比例（约 2/3 提交为非业务）已显著挤压关键路径。

## 4. 请求 Owner 决定的三项处置

### 4.1 冻结 nightly 诊断

- 建议动作：为 nightly 套件稳定性写明退出标准（例如：连续 3 次定时运行无新失败模式，且已知失败均有登记 issue/待办），达标前只登记不新增诊断机制；工作树中的第 6 版修改随下一业务批次提交或还原。
- 验收：退出标准写入本诊断或 nightly 运行说明；后续 nightly 相关提交必须引用该标准。

### 4.2 清账半开环

- 建议动作：§1.3 所列 5 个长期未提交文件在下一个 Git 窗口内逐案处理——完成则提交（附实际验证），未完成则说明原因并还原，不留第三种状态。同时定位并修复生成 `e.txt`/`o.txt`/`({status` 的笔误命令。
- 验收：`git status` 不再含超过 24 小时的未说明修改；新垃圾文件为零。

### 4.3 依赖扫描例外策略

- 建议动作：为非生产 dev 依赖的新披露 CVE 建立登记例外流程（记录 CVE、影响面、处置期限），使其不即时阻断主线与发布候选；生产依赖维持 fail-closed。
- 验收：例外清单入库（建议 governance/ 下新增登记文件），Security Scan 对登记项不再 fail，超期未处置自动升级。

## 5. 边界

- 本文不修改任何计划、registry、单元状态或执行焦点；三项处置均需 Owner 批准后由相应主线执行。
- 未运行测试、未触碰生产代码；所有数字来自本机 `git log`/`gh run list` 只读查询，查询时刻 2026-10-24 上午。
