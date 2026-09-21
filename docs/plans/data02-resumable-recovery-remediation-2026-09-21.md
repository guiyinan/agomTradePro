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

## 剩余阶段

1. 新增独立、可查询的 batch-item/failure evidence，完整保存 symbol、domain、attempt、outcome、
   last completed phase、retry target、stop reason、authority/source 和 Publication head。
2. 把 provider 身份校验移动到 fact mutation 之前，或把规范化、fact 写入与校验纳入同一可回滚事务，
   证明 duplicate/missing/substituted 结果不会留下残余事实。
3. 增加 policy identity/hash 绑定的四 Publication 数值容差对账，冻结 denominator/universe 并输出
   字段、单位、绝对/相对偏差及 breach 证据。

## 回归范围

- `tests/unit/data_center/test_core_data_backfill_task.py`
- `tests/unit/data_center/test_core_data_backfill_command.py`
- `tests/unit/data_center/test_market_publication_refresh.py`
- `tests/component/data_center/test_core_data_backfill_control_plane.py`
- Celery/current-data 合同、增量/全量 mypy、架构与治理检查。

## 风险与回滚点

- 新 checkpoint 增加 `universe_hash`，非零 offset 的旧调用在未提供哈希时按设计 fail closed；从 offset 0
  重启即可取得新哈希，禁止人工伪造或沿用不同候选的 hash。
- 幂等键绑定 universe hash，同一参数但不同资产范围不会覆盖同一 durable batch。
- 回滚本阶段代码只恢复旧 offset 行为，不改变已写 facts；生产部署与真实 backfill 仍是独立授权门。
