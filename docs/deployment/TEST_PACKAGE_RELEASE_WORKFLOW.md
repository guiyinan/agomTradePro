# AgomTradePro 标准工作流：测试 -> 打包 -> 发布

Last updated: 2026-02-17

## 1. 目标与原则

- 目标：每次发布都可复现、可验证、可回滚。
- 原则：
  - 先测后发：未通过测试门禁，不允许打包。
  - 先验包后发：未通过 bundle 校验，不允许发布。
  - 先备份后升级：生产升级前必须做备份。
  - 可回滚：每次发布都保留可回退版本信息。

## 2. 适用范围

- 本地开发环境（Windows + `start.bat`）
- VPS bundle 发布流程（`scripts/package-for-vps.ps1` + `scripts/deploy-on-vps.sh`）

## 3. 发布门禁（必须通过）

1. 代码门禁
- 工作区无未确认改动（`git status` 清晰）
- 目标分支已同步（`main` 或发布分支）

2. 运行门禁
- 本地自动 URL/API 巡检通过（`start.bat` 选 `6`）
- 关键页面无 5xx（报告 `FAIL=0`）

3. 打包门禁
- `package-for-vps.ps1` 成功产出 bundle
- `verify-vps-bundle.ps1` 校验通过

4. 发布门禁
- 生产备份成功
- 升级后健康检查通过

## 4. 标准执行步骤

### Step A. 本地测试（强制）

平台：Windows PowerShell

1. 启动自动巡检
```powershell
start.bat
```
选择 `6`：`Quick Start + URL/API Scan`

2. 检查报告
- 路径：`reports/url_scan/url-api-scan-*.txt`
- 发布要求：`ServerError(5xx)=0` 且 `FAIL=0`

3. 可选补充测试（建议）
```powershell
python manage.py check
```

### Step B. 打包（强制）

平台：Windows PowerShell

1. 交互打包（推荐）
```powershell
pwsh ./scripts/package-for-vps.ps1
```

2. 非交互打包（CI/批处理）
```powershell
pwsh ./scripts/package-for-vps.ps1 -Tag <yyyyMMddHHmmss> -SkipData -SkipRedisData
```

说明：
- 默认不带 SQLite/Redis 数据。
- 生产升级通常只发代码包。

### Step C. 验包（强制）

平台：Windows PowerShell

```powershell
pwsh ./scripts/verify-vps-bundle.ps1 -Bundle ./dist/agomtradepro-vps-bundle-<tag>.tar.gz -NoDockerLoad
```

通过标准：
- tar 完整
- manifest 可解析且校验通过
- 关键文件齐全（compose、deploy 脚本、镜像 tar 等）

### Step D. 发布到 VPS（强制）

#### D1. 升级前备份（在 VPS 上）

平台：Linux VPS Shell

```bash
bash /opt/agomtradepro/current/scripts/vps-backup.sh \
  --target-dir /opt/agomtradepro/current \
  --backup-dir /opt/agomtradepro/backups \
  --keep-days 14
```

#### D2. 上传并执行升级

方式 1（推荐，本地一键）

平台：Windows PowerShell

```powershell
python ./scripts/deploy-bundle-to-vps.py `
  --host 141.11.211.21 `
  --user root `
  --action upgrade `
  --password-file "$HOME\\.agomtradepro\\vps.pass"
```

方式 2（手工 SSH 到 VPS）

平台：Linux VPS Shell

```bash
bash /opt/agomtradepro/current/scripts/deploy-on-vps.sh \
  --bundle /tmp/agomtradepro-vps-bundle-<tag>.tar.gz \
  --target-dir /opt/agomtradepro \
  --action upgrade
```

### Step E. 发布后验证（强制）

平台：Linux VPS Shell

1. 健康检查
```bash
curl -fsS http://141.11.211.21:8000/api/health/
```

2. 服务检查
```bash
cd /opt/agomtradepro/current
docker compose -f docker/docker-compose.vps.yml --env-file deploy/.env ps
```

3. 日志检查（确认无新增 5xx）
```bash
cd /opt/agomtradepro/current
docker compose -f docker/docker-compose.vps.yml --env-file deploy/.env logs --tail=200 web
```

## 5. 回滚流程（标准）

触发条件：
- 健康检查失败
- 关键页面/API 持续 5xx
- 业务验证失败且无法快速热修

回滚步骤：

1. 切回上一发布目录（如果保留 release 目录/软链接）
平台：Linux VPS Shell

```bash
ln -sfn /opt/agomtradepro/releases/<previous_release> /opt/agomtradepro/current
```

2. 重启服务
```bash
cd /opt/agomtradepro/current
docker compose -f docker/docker-compose.vps.yml --env-file deploy/.env up -d
```

3. 如需数据库回滚，使用备份脚本恢复（按备份时间点执行）

## 6. Hotfix 流程（线上紧急修复）

适用：小范围模板/配置/单文件修复，需要快速恢复。

标准做法：
- 先在本地修复并提交。
- 基于当前 `WEB_IMAGE` 构建增量镜像（只覆盖变更文件）。
- 更新 `deploy/.env` 的 `WEB_IMAGE` 并 `up -d web`。
- 修复完成后，必须回归主线：下一个正式 bundle 要包含该修复。

## 7. 职责分工建议

- 开发负责人：保证本地门禁通过、提交可追踪。
- 发布执行人：打包、验包、备份、升级、验证。
- 复核人（可同一人）：核对版本号、镜像 tag、健康检查结果。

## 8. 发布记录模板（每次发布必填）

```text
Release Tag:
Git Commit:
Bundle Path:
WEB_IMAGE:
Backup Path:
Deploy Time:
Health Check Result:
Smoke Result:
Rollback Needed: Yes/No
Notes:
```

## 9. 当前项目约定（重要）

- 本地自动巡检入口：`start.bat` 选 `6`
- URL/API 报告目录：`reports/url_scan/`
- 默认生产入口：`http://141.11.211.21:8000`
- 生产部署根目录：`/opt/agomtradepro/current`
