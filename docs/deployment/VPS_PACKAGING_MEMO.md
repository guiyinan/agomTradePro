# VPS 打包与升级备忘（2026-02-11）

## 1. 目标

将打包流程固定为“优先升级代码，不误带本机数据”，并提高低内存机器上的构建成功率。

## 2. 已落地改进

1. 打包交互优化（`scripts/package-for-vps.ps1`）
- 无参数执行进入快速向导。
- 默认不打包 SQLite 数据（可选 `-IncludeSqliteData`）。
- 默认不打包 Redis 快照（需显式 `-RedisContainer`）。

2. 构建兼容性增强
- BuildKit 失败后自动回退 legacy builder。
- `-DisableBuildKit` 可强制 legacy 模式。
- 修复了 legacy 模式下 Dockerfile 路径与临时构建上下文不一致的问题。
- 新增 Linux wheelhouse 缓存机制（`.cache/pip-wheels/linux-py311`，按 `requirements-prod.txt` 哈希复用）。
- `-RefreshWheelCache` 可强制刷新缓存，`-SkipWheelCache` 可跳过缓存准备。

3. 生产依赖分层
- 新增 `requirements-prod.txt`（仅运行时依赖）。
- 新增 `requirements-dev.txt`（开发/测试依赖，基于 prod 扩展）。
- `requirements.txt` 改为开发聚合入口（引用 dev）。

4. 生产 Dockerfile 收敛
- `docker/Dockerfile.prod` 与 `docker/Dockerfile.prod.mirror` 均改为安装 `requirements-prod.txt`。
- 去除本地 `.cache/pip-wheels` 注入，避免 Windows 轮子污染 Linux 构建。
- 去掉构建阶段命令回显噪音（`set -eu`）。

5. 验包能力补齐
- 新增 `scripts/verify-vps-bundle.ps1`：
  - tar 完整性检查
  - 必需文件检查
  - manifest 校验
  - 可选 docker load 冒烟
- 打包脚本会将该脚本打入 bundle。

## 3. 推荐升级流程（生产）

1. 本地打包（默认只打代码包）
```powershell
pwsh ./scripts/package-for-vps.ps1
```

2. 本地验包
```powershell
pwsh ./scripts/verify-vps-bundle.ps1 -Bundle ./dist/agomsaaf-vps-bundle-<tag>.tar.gz -NoDockerLoad
```

3. 上传到 VPS 后执行升级
```bash
bash ./scripts/deploy-on-vps.sh --bundle /tmp/agomsaaf-vps-bundle-<tag>.tar.gz --action upgrade
```

4. 升级前建议先备份
```bash
bash /opt/agomsaaf/current/scripts/vps-backup.sh --target-dir /opt/agomsaaf/current --backup-dir /opt/agomsaaf/backups --keep-days 14
```

## 4. 仍需关注的风险

1. 迁移回滚风险
- 升级后数据库 schema 前移，回滚旧镜像可能不兼容。

2. Docker Desktop 资源限制
- 若出现 `returned a non-zero code: 137`，通常是构建时 OOM，被系统杀掉。

3. Redis 恢复策略
- 当前有 `dump.rdb` 路径，若后续启用复杂 AOF 策略，建议单独做“Redis 恢复模式”开关（RDB-only / AOF+RDB）。

## 5. 后续建议（下一迭代）

1. 给 `verify-vps-bundle.ps1` 增加 `--compose-smoke`（临时项目名启动 `redis+web` 并检查健康）。
2. 为打包与部署脚本增加统一 `--non-interactive` 模式，便于 CI/CD。
3. 将“升级前自动备份 + 失败回滚指引”固化为一键脚本。
