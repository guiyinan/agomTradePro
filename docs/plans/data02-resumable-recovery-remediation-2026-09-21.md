# DATA-02 可恢复批次证据整改计划（2026-09-21）

## 目标

让 DATA-02 分批回填在资产范围变化、部分失败、进程中断和重试时保留可验证的恢复语义，且任何
Publication 只引用经过同一授权、同一冻结 universe 和完整成功批次产生的事实。

## 已完成阶段

1. current-fact、独立 rebuild、可恢复 Celery 和定时全市场入口均绑定 canonical current authority。
2. 后台写边界重复校验同一 authority head；partial/failed/blocked checkpoint 不推进 offset。
3. quote/valuation returned 与 succeeded 身份不精确时禁止进入 Publication。
4. 本阶段把规范化、去重后的 active A-share universe 固化为 SHA-256；任何非零 offset 必须携带
   上一 checkpoint 的同一哈希，查询顺序不影响哈希或幂等身份，范围漂移在 provider 访问前阻断。
5. 独立 `SyncItemAttempt` 证据表已接入 quote、valuation、price、financial 与最终四 Publication
   阶段；每个 phase 先写 RUNNING，再执行 provider/Publication 边界，并仅允许一次终态转换。
6. quote/current valuation/single valuation 的 provider 身份检查已移动到真实 repository 写入前；
   独立 PostgreSQL 证明 substituted/missing/duplicate 响应不改变既有事实，也不触发 Publication。
7. PostgreSQL 条件唯一约束保证同一 batch/asset/phase 只有一个 RUNNING attempt；begin、finish、
   recovery 并发已用独立 backend 验证。迁移 0081 先检查历史重复并明确 fail closed，再创建条件索引。

## 剩余阶段

1. 用冻结 universe 执行 5,533/当前生产 denominator 规模测试，量化 attempt 写入、恢复查询和最终
   聚合的时间、行数与存储开销；若超过任务预算，再做有界批量优化。
2. 增加 policy identity/hash 绑定的四 Publication 数值容差对账，冻结 denominator/universe 并输出
   字段、单位、绝对/相对偏差及 breach 证据。
3. 取得真实 current production authority 与明确生产写授权后，执行分批 provider 回填；未获得前保持
   `awaiting_production`，不得把本地 PostgreSQL 证据当作生产验收。

## 回归范围

- `tests/unit/data_center/test_core_data_backfill_task.py`
- `tests/unit/data_center/test_core_data_backfill_command.py`
- `tests/unit/data_center/test_market_publication_refresh.py`
- `tests/component/data_center/test_core_data_backfill_control_plane.py`
- `tests/component/data_center/test_data02_postgres_closure.py`
- Celery/current-data 合同、增量/全量 mypy、架构与治理检查。

## 风险与回滚点

- 新 checkpoint 增加 `universe_hash`，非零 offset 的旧调用在未提供哈希时按设计 fail closed；从 offset 0
  重启即可取得新哈希，禁止人工伪造或沿用不同候选的 hash。
- 幂等键绑定 universe hash，同一参数但不同资产范围不会覆盖同一 durable batch。
- 回滚本阶段代码只恢复旧 offset 行为，不改变已写 facts；生产部署与真实 backfill 仍是独立授权门。
- 0081 在检测到历史重复 RUNNING scope 时明确中止；必须先保留并处置冲突证据，禁止迁移脚本静默
  删除、合并或改写 append-only attempt 历史。
