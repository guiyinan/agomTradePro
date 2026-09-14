# EVID-09 Main 194183 部署复测阶段记录

本记录补充实际部署封存，不改变旧失败记录或单元退出门。部署证据见
[完整封存](evid09-standard-deployment-preservation-main194-2026-09-14.json)
及其 sidecar，SHA-256 为
`7ed729b4d9dc4ffa5ad10fa4dcd92a6819a2cbde4ec32d3faed8c17ba3a7c13d`。

## 已完成

- 标准 code-only 升级实际 exit 0、child reaped、原始输出完整，执行时段为
  2026-09-14 04:29:51 至 04:45:52 UTC。保留备份、自动回滚和 Celery，未恢复数据库。
- 实际 Source 为 `194183454fdef541a728ccce7e0a1520fe5ac860`，容器为
  `3abcb657cf7b9938b04e0321679ba6a4d3365f4c17a5ccd0db9cc318dab9c584`，image 为
  `sha256:2ec2969ba92f2d2f9c13520c29257890dd951f3aae79f6c63b7cb886cb1c6a4e`。
  新 runtime healthy、restart 0，全部 28 项 Git/release/live 哈希一致。
- 标准验证通过 HTTP/TLS、Django schema、TUI registry、pyqlib、worker/beat 与资源检查。
  实际备份为 153,124,405 字节，原始 manifest 与远端 dump SHA 一致。
  备份先于迁移命令的证据是同一原始终端流的第 133 与 136 行；迁移开始时间未发布。
- 四个旧 authority roots 的内容及 canonical payload 指纹、撤销记录在部署前后保持一致。
- 使用已批准的 admin/user 1，实际直接 Facade current 返回 None，historical exact
  返回原始 root 哈希。两项读取合计 32.769785 秒，business DML 为 0，rollback 完成。
  读取保留生产锁规则，在 READ COMMITTED 事务中执行；不能称为数据库 READ ONLY 事务。
- Versioned deployment loader 接受封存的 28 路径和 22 份原件；独立审计逐项核对原件 SHA
  和长度，并确认实际退出、备份顺序、roots 及真实 Facade 读取记录。

完整隔离 PostgreSQL 父链与物理解码计数属于另一次候选测量，见
[PR52](https://github.com/guiyinan/agomTradePro/pull/52)。该测量不提供本次生产读取的
物理解码计数，也不能据此计算生产配对优化比例。

## 完整生命周期实测与独立恢复

V6 真实准备 exit 0，并通过三份原始证明和两个事务阶段的独立审计。随后完整生命周期在
2026-09-14 06:33:16–06:59:03 UTC 执行，实际子进程 exit 1、reaped true，未触发 2,100 秒
监督器超时。前 19 步通过，第 20 步 `authority_successor_with_current` 触发 1,500 秒
生命周期硬 watchdog；第 21 步 rollback read 通过。不能据此验收完整生命周期。

实际性能瓶颈包括：`authority_current` 160.370 秒、25,038 次 SELECT；
`authority_with_current` 315.030 秒、50,075 次 SELECT。上述是本次真实阶段测量，
不包含生产物理解码计数，也不能与隔离 pytest 的不同测量范围直接计算优化百分比。

结束后重新执行独立 prepare，并在 07:01:41 UTC 完成独立恢复验证，实际 exit 0：
19 项完整行 ledger、四个 roots、绑定的 current/exact 观察和基线指纹均未改变。
验证排除 auth.User、django_session、日志、指标、序列和无关业务表；登录 session
发生在父事务之外，不能声称被回滚。完整失败及恢复封存见
[69 份原件索引](evid09-failed-main194-facade-lifecycle-2026-09-14.json)，SHA-256
`2476525d9b02830c70e5068a905b28569ff3dd2224ffc5a3e180ae01424e1ae8`。

## 尚待完成

- 新 scope 的完整生命周期仍未通过，下一步修复实际 Facade 查询放大路径。准备过程已拆为 READ COMMITTED 的直接
  Facade 读取和 REPEATABLE READ READ ONLY 的 19 项 ledger 快照；前者执行前拒绝业务 DML。
  2026-09-14 06:24:30–06:25:33 UTC 的 V5 实测远端 exit 0、本地 exit 1：本地证明重新编码
  使用字面反斜杠 n，而远端文件使用 LF，SHA 校验拒绝接受。完整生命周期没有启动。
- V3 原生所有者声明字段读取错误、V4 部署 identity 字段映射错误、V5 编码错误的实际失败
  记录均保留；修正不覆盖原始回执，也不降低哈希、事务或超时要求。
- 独立恢复已核对明确的 19 项 ledger、四个 roots 与 current/exact 观察，不能称为全库回滚证明。
- 部署前缺少完整 policy/catalog/current-metadata 快照，这部分保持未验证。
- DATA-02 provider 到原件存储、审计和事实元数据的接入，以及可信可用时间、原生来源身份
  和人工生产验收尚未完成。存储代码已部署不代表历史缺口已修复。

EVID-09 继续 active；本阶段不晋级 DATA-02、EVID-01/02 或人工验收状态。

## 下一阶段检查与回退边界

修正后的准备工具已用实际返回的三份证明逐项核对 SHA，普通及 `-O` 控制均通过。
后续优化须定位上述真实查询放大路径，补保持锁、时点及证伪规则的回归后再部署。
复测保持 1,500 秒生命周期和 2,100 秒子进程预算，结束后重新采集独立快照并核对 19 项
ledger 和四个 roots。当前风险是完整生命周期仍未通过；禁止自动重试未证明退出的远端
子进程。部署回退点仍为标准升级保留的上一 image 和已验证 PostgreSQL 备份，本阶段
没有执行数据库恢复。
