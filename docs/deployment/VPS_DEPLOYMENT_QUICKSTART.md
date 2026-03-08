# VPS 快速部署指南

这份文档写给第一次把 bundle 部署到 Linux VPS 的人。

默认架构：
- VPS 上跑一套 docker compose（`web` + `redis` + `caddy` + 可选 `rsshub/celery`）。
- 外部访问走 `caddy`（容器内监听 `:80/:443`），宿主机映射端口用 `deploy/.env` 里配置（默认 HTTP `8000`）。
- 数据库默认 SQLite（容器 volume：`sqlite_data`），升级时会复用原有数据。

## 1. 打包并上传 bundle

### Windows PowerShell：本地打包

本机在项目根目录执行：

```powershell
pwsh ./scripts/package-for-vps.ps1
```

生成文件在 `dist/`，例如：
- `dist/agomsaaf-vps-bundle-YYYYmmddHHMMSS.tar.gz`

### 跨平台 Shell：上传到 VPS

上传到 VPS（示例）：

```bash
scp dist/agomsaaf-vps-bundle-*.tar.gz root@your-vps-ip:/root/
```

## 2. 在 VPS 上部署（推荐）

### Linux VPS Shell：登录并部署

登录 VPS：

```bash
ssh root@your-vps-ip
```

解压并运行部署脚本：

```bash
cd /root
tar -xzf agomsaaf-vps-bundle-*.tar.gz
cd agomsaaf-vps-bundle-*

# 交互式菜单（fresh/upgrade/restore/status/logs）
bash ./scripts/deploy-on-vps.sh --bundle /root/agomsaaf-vps-bundle-*.tar.gz
```

部署根目录默认是：
- `/opt/agomsaaf`

部署脚本会：
- 生成/更新 `deploy/.env`（必要时会生成随机 `SECRET_KEY`）
- 渲染 `docker/Caddyfile`
- `docker load` 导入镜像并启动服务
- 如果 bundle 带了 `backups/db.sqlite3`，会恢复到容器 volume
- 自动执行 `python manage.py migrate --noinput`
- 设置 `/opt/agomsaaf/current` 指向当前 release（便于回滚）

## 3. 配置端口（VPS 的 80 被占用时）

### Linux VPS Shell：修改并重启

不要改 `docker-compose.vps.yml` 的端口映射；端口靠 `deploy/.env` 配置：

- `CADDY_HTTP_PORT=8000`（HTTP 对外端口）
- `CADDY_HTTPS_PORT=8443`（可选，如果 443 被占用）

配置文件路径（在 VPS 上）：
- `/opt/agomsaaf/current/deploy/.env`

改完后重启：

```bash
docker compose -f /opt/agomsaaf/current/docker/docker-compose.vps.yml --env-file /opt/agomsaaf/current/deploy/.env restart caddy
```

## 4. 访问与验证

### Linux VPS Shell：健康检查

健康检查：

```bash
curl -fsS http://your-vps-ip:8000/api/health/
```

如果返回 HTTP 400 Bad Request，一般是 `ALLOWED_HOSTS` 没包含你的 IP/域名：
- 修改 `/opt/agomsaaf/current/deploy/.env` 里的 `ALLOWED_HOSTS`
- 然后重启 `web`：
  ```bash
  docker compose -f /opt/agomsaaf/current/docker/docker-compose.vps.yml --env-file /opt/agomsaaf/current/deploy/.env restart web
  ```

## 5. 常用维护命令

### Linux VPS Shell：日常运维

```bash
docker compose -f /opt/agomsaaf/current/docker/docker-compose.vps.yml --env-file /opt/agomsaaf/current/deploy/.env ps
docker compose -f /opt/agomsaaf/current/docker/docker-compose.vps.yml --env-file /opt/agomsaaf/current/deploy/.env logs -f --tail=200
docker compose -f /opt/agomsaaf/current/docker/docker-compose.vps.yml --env-file /opt/agomsaaf/current/deploy/.env restart
docker compose -f /opt/agomsaaf/current/docker/docker-compose.vps.yml --env-file /opt/agomsaaf/current/deploy/.env down
```

更完整的说明见：
- `docs/deployment/VPS_BUNDLE_DEPLOYMENT.md`
- `docs/deployment/VPS_DEPLOYMENT_RUNBOOK_141.11.211.21.md`
