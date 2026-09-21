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
8. 以当前精确 denominator 5,565 完成 cardinality-equivalent PostgreSQL 规模测量：五阶段共
   27,825 条成功 attempt，另恢复 5,565 条 stale attempt 并保留 1 条 fresh RUNNING sentinel。
   实测发现异质终态的 ORM CASE 更新超出任务预算，现改为 PostgreSQL 单事务
   `UPDATE ... FROM (VALUES ...)`，最终全流程 2,417.54 秒，低于 3,500/3,600 秒预算。
   该夹具使用易失性 tmpfs，只关闭仓库行形状、原子性、查询与恢复规模门，不构成生产容量验收。
9. 四 Publication 数值容差证据契约已实现：它绑定冻结 denominator/universe、Publication
   id/hash/member、P2 publication policy identity、字段、canonical unit、绝对/相对容差及偏差，
   并校验每个 member 的每个治理字段恰好对账一次。`covered_asset_count` 与 `member_count` 分离，
   因此 financial 的多指标成员数可以大于资产数。离线 recorder 只消费 `select_only` JSON，默认
   策略 registry 保持 `awaiting_owner_approval` 且无策略，真实 owner 批准前按设计 fail closed。
   Parser 复用 Publication 成员级 evidence/quality/time 规则，重算 current Publication UUID、完整成员
   hash、冻结资产集合 hash 和 canonical/observed 数值快照 hash，并拒绝重复 fact 或歧义 JSON。

## 剩余阶段

1. 由真实 data owner 批准四类数据逐字段、单位、绝对/相对容差并提供可验证 receipt；不得把测试
   fixture 的合成阈值写入治理 registry。
2. 取得真实 current production authority 与明确生产写授权后，执行分批 provider 回填并对真实四
   Publication snapshot 运行数值对账；未获得前保持 `awaiting_production`，不得把本地 PostgreSQL
   证据当作生产验收。

## 回归范围

- `tests/unit/data_center/test_core_data_backfill_task.py`
- `tests/unit/data_center/test_core_data_backfill_command.py`
- `tests/unit/data_center/test_market_publication_refresh.py`
- `tests/unit/data_center/test_current_publication_rebuild.py`
- `tests/unit/data_center/test_numeric_tolerance.py`
- `tests/unit/data_center/test_data02_publication_tolerance_evidence.py`
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
