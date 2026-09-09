# VPS Alpha 评分停更排查与修复（2026-09-09）

## 根因与证据

- Celery beat / worker 均存活，定时任务启用且持续投递；不是调度关闭。
- 配置的 Tushare 兼容行情服务实际返回 `token daily limit exceeded`。
- 账户评分池包含约 5,533 只股票；builder 将额度错误视为普通失败，每只股票重试三次并继续遍历。
- worker 日志多次出现 3,300 秒软超时及 3,600 秒硬超时，同一推理任务反复投递。
- Qlib 日历和实际评分源日期为 2026-09-04。两条计划日期为 09-07 / 09-08 的 csi300 缓存仍标为 available；09-09 执行日志把刷新失败、退回 09-04 数据后的推理记为 success。
- Data Center PriceBar 查询未发现 09-04 及以后可直接补齐的数据；未进行未经校验的数据源替换。

## 已完成

1. builder 识别额度耗尽，使用 TushareError 和稳定错误码 `TUSHARE_DAILY_QUOTA_EXHAUSTED`，不做无效重试；并发批次停止尚未发出的请求。日线、复权因子、指数及成分股查询传播该错误。
2. 推理入口在额度耗尽时返回 blocked、零写入和明确原因，避免继续推理、写缓存和触发下游推荐。
3. 其他刷新失败而回退旧日期时，缓存写为 degraded，任务报告 partial，并发布 stale / degraded / must_not_use_for_decision / qlib_source_data_stale，跳过下游推荐刷新。保留真实 asof_date。
4. 定向撤销六个已识别的阻塞或重复 Alpha 任务；未清空整个 broker。保留自动调度。
5. 仅热更新三个生产文件至 release、web、worker、beat 文件系统；重启 web 和 worker。未重建镜像、迁移数据库或替换数据卷。
6. 备份并修正两条本周旧源日期缓存的状态及质量元数据，未改动评分、asof_date 或 updated_at。

生产文件：

- `apps/alpha/infrastructure/qlib_builder.py`
- `apps/alpha/application/prediction_refresh_orchestration.py`
- `apps/alpha/application/tasks.py`

## 验证

- 修改前两个新增回归失败，修改后相关回归 40 passed：builder、prediction、task outcome。
- 无数据库启动的关键回归子集 21 passed。
- 增量 mypy：三个生产文件零错误、零回退。
- 全仓 mypy debt ceiling：零错误。
- Celery 任务契约：91 tasks / 21 exemptions / 23 governed files，通过。
- 当前数据新鲜度契约：54 surfaces，通过。
- Black、isort、Ruff 通过；远端 `manage.py check --deploy` 无问题（1 silenced）。
- 公网 HTTPS `/api/health/` 返回 200；修复前远端三个文件均与本地 HEAD 基线一致，定向发布校验通过。
- 最终容器均运行，web 健康；worker 检查无正在执行的任务，保留 4 个预取任务。`pyqlib=0.9.7`，错误的 `qlib` distribution 不存在。Qlib 日历仍为 2026-09-04。
- 真实 worker 探针任务 `cd30d09f-67b2-45fd-a591-799882de4436`：请求 2026-09-08，返回 `outcome=blocked`、`blocked_reason=tushare_daily_quota_exhausted`、`stored=0`。这是失败关闭验证，不是新评分生成成功。

## 回滚点

- 原始代码备份：VPS `/opt/agomtradepro/manual-file-backups/20260909145102`。
- 随后统一 tasks.py 换行的副本备份：`/opt/agomtradepro/manual-file-backups/20260909145215`；此备份已经包含修复，不作为原始代码回滚点。
- 两条缓存原状态与 metrics_snapshot：持久卷 `/app/data/alpha-score-status-backup-20260909.json`。
- 恢复代码时需同步 release / web / worker / beat，并重启加载代码的服务。缓存回滚仅按备份主键恢复状态与元数据，不覆盖源日期或评分。

## 未完成与未验证风险

- 上游每日额度仍耗尽，实际 Qlib 数据仍停在 2026-09-04；没有生成 09-08 的新评分，不宣称业务已恢复。
- 需要恢复当前行情服务额度，或在配置中心配置经过一致性校验的可用数据源，再执行数据同步和评分任务并验证源日期、覆盖范围及用户页面。
- 未证明额度恢复后的完整市场池刷新能够在当前服务限额内完成；批量行情获取、跨账户重复刷新消除需要结合实际服务限额另行验证，不能用增加重试或伪造日期代替。
- 未等待下一次定时周期。定时任务保持启用，未来触发仍会在额度不足时明确阻断。
- 本地工作树已有其他任务改动，未提交或发布无关文件；治理文件仅增补本次契约。

## 后续：TUI「更新清单」实测

用户定位：`screen:research.signals action:dashboard.alpha-ranking`。

- 通过 VPS 已登录浏览器实际操作；「更新清单」绑定只读 Alpha 清单查询，不会重新训练或推理。
- 展示数量从 10 改为 5，页面成功返回 5 条；从 5 改为 20，页面返回 10 条。没有复现按钮无法提交。
- 数据库确认最新 csi300 缓存计划日 09-08、源日期 09-04，实际仅存 10 个评分；09-07 缓存有 30 个评分，但不会被当成新的 09-08 结果。展示数量是查询上限，不能生成缓存中不存在的行。
- 用户页面显示评分日 2026-09-04、禁止用于决策为「是」。更新列表不会解除上游每日额度阻断。
- 检查后将当前浏览器展示数量恢复为 10；未将只读按钮改为隐式触发耗时推理。
