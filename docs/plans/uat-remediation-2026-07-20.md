# UAT 整改记录（2026-07-20）

## 阶段目标

复核外部团队针对 `https://demo.agomtrade.pro` 的 UAT 结果，修复能够由代码和测试明确复现的问题，并把必须在生产发布后完成的数据回填、调度恢复和验收动作从代码整改中分离出来。

本批次只收口 UAT 已有证据指向的缺陷，不把数据源扩建、全模块调度重构和历史数据治理混入同一批改动。

## 已确认并完成的代码整改

| UAT 问题 | 根因 | 整改 |
|---|---|---|
| PostgreSQL 备份任务失败 | 生产镜像只有 `libpq5`，没有提供 `pg_dump` 的 PostgreSQL client | 两个生产 Dockerfile 通过 PGDG 安装并在构建期校验 `postgresql-client-16`，与生产 PostgreSQL 16 锁定 |
| Regime history 翻页重复 | API 接收不到 `page`，repository 也没有 offset/count | 增加 `page` 校验、offset 查询和分页元数据 |
| Regime current/calculate 的 Z 分数恒为 0 | Interface payload 写死为 `0.0` | 从 V2 趋势计算结果或持久化快照返回真实 Z 分数 |
| Regime 历史存在 `HG` 等非法值 | 模型无 canonical 选择约束和数据库约束 | 数据迁移将四个 legacy code 映射为 canonical regime，并添加数据库 check constraint；未知值阻止迁移，避免静默误映射 |
| Regime 历史重算可能产生缺口或先删后失败 | 旧命令使用旧计算链并在计算前删除历史 | 改用 V2/PIT 链路；默认生成连续日历日；先完整计算，任何日期失败即中止，成功后才原子替换指定范围 |
| Policy 日期区间查询遇单条历史坏 URL 时 500 | 输出阶段错误地使用输入校验 serializer，重新校验 legacy URL | 输出改为 instance serialization；保留原始审计值但不再令整段查询失败 |
| `/api/dashboard/*` Token 请求被 302 到登录页 | API 函数使用 session-only `login_required` | 为 Dashboard API 统一启用 Session、Internal Token、Multi Token 认证；页面路由仍保持 session 登录 |
| `510300.SH` 价格约放大 10 倍 | EastMoney quote 字段统一按 `/100` 解码，忽略 `f59` 精度 | 按返回的 `f59` 动态缩放价格字段；股票、ETF、指数均按各自精度解析 |
| Pulse 维度 `indicator_count=0` 与读数矛盾 | 从持久化日志重建快照时计数写死为 0 | 按维度重新统计未过期指标，语义与 Domain 计算一致 |
| 月度 Rotation 信号隔天即 stale | stale 被定义为 `signal_date < today` | 按 daily/weekly/monthly/quarterly 的调仓周期边界判断 stale，API serializer 与推荐服务共用 Domain 规则 |
| Regime history 非法分页参数返回 500 | DRF `ValidationError` 被通用异常分支吞掉 | 单独映射为公开 400 契约，不再把校验异常包装成 500 |
| Rotation 周期边界在 UTC/Asia-Shanghai 间漂移 | Infrastructure 使用 `date.today()`，Interface 使用 `timezone.localdate()` | Rotation Infrastructure 统一使用 Django local business date，并增加跨月边界测试 |
| Rotation signal list N+1 | Serializer 访问 `config`，基础 queryset 未联表 | 基础列表和 latest 查询统一 `select_related("config")`；latest 使用相关子查询一次选出每配置最新信号 |
| V2 趋势缺失仍显示 Z=0 | `getattr(..., 0.0)` 把不可用数据静默伪装为中性值 | API 返回 `null` 并附明确 warning；持久化路径拒绝缺少 PMI/CPI 趋势的结果 |

## 前置单位治理提交

本轮 UAT 修复建立在以下已合入的 Data Center 单位治理提交之上：

- `04613c91`：补齐投资者账户单位元数据。
- `85ce8203`：治理 ETF 规模流量单位及迁移规则。

对应 `0038` 迁移现已增加重复执行幂等验证，并补充“万元 ETF fact 经真实归一化器转换后写入 canonical store”的覆盖。

## 生产发布后的必做动作

以下动作会改变生产环境，本次本地整改没有代替执行：

1. 发布新生产镜像并运行迁移，确认 legacy Regime code 已转换且 constraint 生效。
2. 先执行并验证一次 PostgreSQL 备份：`python manage.py backup_database`；确认文件存在、大小非零、验证任务通过，再恢复定时备份验收。
3. 按需要的历史范围执行 Regime 回填，例如：

   ```text
   python manage.py recalculate_regime --start-date=2025-01-01 --end-date=2026-07-20 --frequency=daily
   ```

   命令会先导出 Regime JSON 备份，再全量计算，最后原子替换；不要使用 `--skip-backup` 进行首次生产回填。
4. 重新同步被旧精度逻辑污染的 ETF quote/cache；仅发布解析修复不会自动改写已经持久化的 `45.89`。
5. 重新调用 Policy range、Dashboard Token、Regime current/history、Pulse current、Rotation latest API 做生产 smoke test。

## 尚未完成：独立运维/数据主线

UAT 中以下现象得到报告证据支持，但不是本批次可安全自动修正的单点代码缺陷：

- sentiment、sector、fund、realtime、hedge、asset-analysis、backtest、simulated-trading 等数据为空或长期未更新。
- equity 估值与全市场价格覆盖率过低。
- `CN_UNEMPLOYMENT`、`CN_INDUSTRIAL_PROFIT` 无数据，社融、零售、LPR 等序列缺点或落后。
- GDP `published_at`、FAI 派生同比值需要按 provider 原始响应和指标目录 lag 规则逐条审计。
- Tushare capability 长期未成功仍显示 healthy，需要先确定统一 freshness SLA，再修改健康状态语义。
- Rotation 历史断裂需要恢复或补建生产调度；`expected_return=59.4%` 是当前日收益均值乘 252 的年化结果，量级可疑但尚无证据证明公式或输入错误，不能仅凭数值截断。
- Signal 只有 UAT 数据、Share 快照陈旧、审批长期挂起、Terminal legacy 路由发布、AI capability key 双写，分别属于生产数据、治理和 Terminal/MCP 收口主线。

仓库当前 scheduler defaults 并未覆盖上述所有模块；这部分应单独建立“生产数据流水线恢复”阶段，逐模块明确 owner、频率、freshness SLA、首次回填范围、失败告警和回滚点，不能只把 readiness 保持绿色视为业务数据可用。

## 回归范围与完成标准

本批代码整改的完成标准：

- 新增缺陷测试全部通过。
- Regime migration graph 无遗漏，`makemigrations --check` 无新变更。
- 相关 Python 文件通过 Black、isort、Ruff，Git diff 无空白错误。
- 生产动作未执行前，不宣称 UAT 的历史数据和调度问题已经在 demo 环境恢复。

## 风险与回滚点

- Regime migration 遇到四个已知 legacy code 之外的值会主动失败；应先审计该值，禁止临时映射到任一业务象限。
- Regime 回填任一日期计算失败都会保留原历史；修复数据源后再重跑。
- `daily` 多年历史回填需逐日执行 PIT 计算，可能耗时数小时；管理命令 help 已提示先以限定日期范围验证。
- Dashboard API 未认证请求由原 302 变为 DRF 401/403，这是 API 契约修正；Dashboard 页面登录跳转不变。
- EastMoney 精度修复依赖 provider 的 `f59`；字段缺失时保留原 `/100` 兼容路径。
- Rotation stale 规则按配置周期生效；daily 或未知频率仍采用逐日失效的保守策略。
