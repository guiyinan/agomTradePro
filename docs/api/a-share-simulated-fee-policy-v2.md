# 普通模拟费用 V2：精确适用范围与版本管理

新结算成交入口只接受明确的 `SimulatedFeePolicyV2`。它复用既有 FeeConfig，不新增费用账本；历史配置的七个版本字段保持 NULL，不自动升级，不初始化真实费率。当前旧普通买卖与自动模拟入口尚未切换，实际成交导入也不进入本估算路径。

## 适用范围与精度

每个政策包含完整、有限且无重复的交易 case 集合。case 必须精确声明 `asset_type/market/board/side`，并分别声明佣金、过户费、印花税、滑点为 `APPLIES` 或 `NOT_APPLICABLE`。不存在匹配、重复匹配、未知值或通配符时拒绝交易；不能把未知交易所解释为四项费用全零。代码后缀不自动成为执行 market，board 也不从代码推断。

当前唯一账户范围为显式 `ALL_SIMULATED_ACCOUNTS`。配置名称中的 VIP、低佣或普通字样不构成账户适用依据；账户专属收费方案尚未实现。FeeConfig 原 `asset_type` 仍保留，新的完整 case 才是本入口适用性的判断依据。

七项数值继续保留 FeeConfig 实际 FloatField 的 binary64 值，用 `Decimal.from_float` 读取，不据此声称恢复最初录入的十进制原文。外层政策 hash 绑定原 V1 数值快照、完整 case、身份、版本、账户范围、有效窗、首次记录时刻及固定估算/舍入口径。计算目的为 `NORMAL_SIM_ESTIMATED`，精度来源为 `DATABASE_BINARY64`，分项按 `ROUND_HALF_EVEN` 到分后汇总；它不是券商实收费用。

未知数值不默认零。外部 manifest 只接受有限 JSON 数字，拒绝 bool、数值字符串、NaN/Infinity、无法表示的超大整数与重复键。Application 再核对仓储返回的精确 Decimal 与预期 binary64 值，不能转回 float 后比较，从而掩盖不同 Decimal 的差异。

## 版本与时间

政策使用 `policy_id/policy_version` 和半开窗 `[effective_from, valid_until)`；现有 FeeConfig `created_at` 同时提供首次系统记录时刻。读取要求 `created_at <= as_of` 且仍在有效窗内，不能用当前创建的新配置冒充更早已知版本。记录时刻达到或晚于失效时刻的政策没有可用窗口，创建时拒绝。

同身份、同内容重放返回原行和原记录时间；同身份不同内容拒绝。两个政策只要共享一个完整交易 case，其有效窗就不能相交；相邻半开窗可以接续。没有“最具体匹配优先”或自动 latest 选择。

新严格行固定 `is_default=false/is_active=false`，避免被旧默认费率读取误选。新 reader 按严格版本与时间窗选择，旧 active/default 标志不承担启停严格政策的含义。本切片不支持提前退役或原地修正；后续退役需要独立契约。不要把修改旧标志当成严格版本已撤回的证明。

## 操作入口

操作员准备完整 JSON manifest，schema 为 `simulated-fee-policy-command.v1`。必须提供七项数值、旧配置名称与资产类型、政策身份/版本、显式账户范围、两个带时区时间、全部交易 case 和 description，不提供业务默认映射或费率。

```powershell
python manage.py create_simulated_fee_policy_v2 --manifest <policy.json> --database <alias>
python manage.py create_simulated_fee_policy_v2 --manifest <policy.json> --database <alias> --apply
```

第一条只校验 manifest 并预览，不调用写入仓储；不证明目标库、重叠检查或最终创建一定通过。第二条才在指定 alias 上创建或精确重放，冲突与存储不可用以明确命令错误返回。没有后台初始化、启动种子或真实生产配置写入。

Admin 继续维护旧配置，新严格版本只读展示。新保存 handler 要求用户已认证且具有持久主键；严格行的模型保存/删除和批量更新/删除另有保护，不能仅依赖 UI。特别是封版前 `post_save` 留存的旧实例也必须按数据库当前状态拒绝删除。批量操作在最终 SQL 中限制旧 NULL 版本，保留 Django 删除信号及 Collector 行为。普通 ORM 保护不等同于数据库原生不可变触发器，直接 SQL/基础 QuerySet 绕过不属于被授予的版本管理入口，读取仍须重验内容 hash。

## 并发、成交与历史重放

writer 要求自己拥有外层事务。PostgreSQL 使用有界事务 advisory locks 串行化政策身份和全部排序后的精确 case，要求 READ COMMITTED；SQLite 在任何重叠读取前取得写保留。无法建立该边界、调用方已有事务或写锁不可用时明确拒绝，不冒充安全写入。

创建只在同一未提交事务内生成一个新的非默认旧结构 shell、取得真实 PK/created_at，再封存严格元数据。该私有最终写入只作用于本次新 shell；不是把历史旧配置任意升级为严格版本的公共入口。

新成交在账户/持仓锁内重新验证政策和时间，成交、现金、费用、股份及快照一起提交。成交表继续使用原 `fee_schedule_snapshot/hash` 保存带 schema 的 V2 外层快照，不再建第二快照字段。原无 schema 的 V1 payload/hash/公式保留用于历史收据验证；历史重放按原 execution time 验证，不要求旧政策在重放请求时仍有效，也不重新扣费。

## 迁移与验收边界

`simulated_trading.0025_fee_policy_v2_contract` 仅对 FeeConfig 加七项可空元数据、身份唯一性及完整/时间窗约束和索引。旧 0024 保持不变。反向迁移会删除严格元数据，旧费用值保留，但无法仅靠降级后的行重建原版本。

费用版本合同通过仍不代表三交易所具体费制已经配置、正式日历已发布或普通消费者可以切换。联合验收还需真实来源/映射、正式日历、V3 规则和完整成交旅程；实际导入费用保留原实收信息，不估算补齐或重复扣款。
