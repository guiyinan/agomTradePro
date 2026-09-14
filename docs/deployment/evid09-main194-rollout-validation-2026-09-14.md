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

## 尚待完成

- 新 scope 的真实限时生命周期与独立恢复验证。准备过程已拆为 READ COMMITTED 的直接
  Facade 读取和 REPEATABLE READ READ ONLY 的 19 项 ledger 快照；前者执行前拒绝业务 DML。
  2026-09-14 06:24:30–06:25:33 UTC 的 V5 实测远端 exit 0、本地 exit 1：本地证明重新编码
  使用字面反斜杠 n，而远端文件使用 LF，SHA 校验拒绝接受。完整生命周期没有启动。
- V3 原生所有者声明字段读取错误、V4 部署 identity 字段映射错误、V5 编码错误的实际失败
  记录均保留；修正不覆盖原始回执，也不降低哈希、事务或超时要求。
- 独立恢复将核对明确的 19 项 ledger、四个 roots 与 current/exact 观察，不能称为全库回滚证明。
- 部署前缺少完整 policy/catalog/current-metadata 快照，这部分保持未验证。
- DATA-02 provider 到原件存储、审计和事实元数据的接入，以及可信可用时间、原生来源身份
  和人工生产验收尚未完成。存储代码已部署不代表历史缺口已修复。

EVID-09 继续 active；本阶段不晋级 DATA-02、EVID-01/02 或人工验收状态。

## 下一阶段检查与回退边界

修正后的准备工具须用实际返回的三份证明重新编码并逐项核对 SHA，普通及 `-O` 控制均通过
后才启动完整生命周期。执行保持 2,100 秒子进程预算，结束后重新采集独立快照并核对 19 项
ledger 和四个 roots。当前风险是完整生命周期及独立恢复仍未实测；禁止自动重试未证明退出
的远端子进程。部署回退点仍为标准升级保留的上一 image 和已验证 PostgreSQL 备份，本阶段
没有执行数据库恢复。
