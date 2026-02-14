# VPS 快速部署指南

## 一键部署（推荐）

```bash
# 1. 上传 bundle 到 VPS
scp agomsaaf-vps-bundle-20260212171836.tar.gz root@your-vps-ip:/root/

# 2. 登录 VPS
ssh root@your-vps-ip

# 3. 运行一键部署脚本
cd /root
tar -xzf agomsaaf-vps-bundle-20260212171836.tar.gz
cd agomsaaf-vps-bundle-20260212171836
chmod +x scripts/deploy-one-click.sh
./scripts/deploy-one-click.sh agomsaaf-vps-bundle-20260212171836.tar.gz
```

**一键脚本会自动完成**：
- ✅ 解压 bundle
- ✅ 生成随机 SECRET_KEY
- ✅ 询问域名配置
- ✅ 加载所有 Docker 镜像
- ✅ 生成 Caddyfile
- ✅ 启动所有服务
- ✅ 恢复数据库备份（如果有）
- ✅ 运行数据库迁移
- ✅ 创建当前部署软链接

---

## 手动部署（高级）

### 1. 上传打包文件到 VPS

```bash
# 方法 1: SCP 上传
scp agomsaaf-vps-bundle-20260212171836.tar.gz root@your-vps-ip:/root/

# 方法 2: 在 VPS 上直接下载（如果文件在可访问的 URL）
cd /root
wget http://your-url/agomsaaf-vps-bundle-20260212171836.tar.gz
```

## 2. 在 VPS 上解压

```bash
# 解压
tar -xzf agomsaaf-vps-bundle-20260212171836.tar.gz
cd agomsaaf-vps-bundle-20260212171836
```

## 3. 配置环境变量

```bash
# 复制环境变量模板
cp deploy/.env.vps.example .env

# 编辑 .env 文件（至少修改以下项）
vim .env
```

**必改配置**：
```bash
# 数据库密钥（随机生成）
SECRET_KEY=your-random-secret-key-here

# 数据库密码
POSTGRES_PASSWORD=your-db-password

# Redis 密码
REDIS_PASSWORD=your-redis-password

# 域名（如有）
DOMAIN=your-domain.com
```

## 4. 加载 Docker 镜像

```bash
# 加载所有镜像
docker load -i images/web.tar
docker load -i images/redis.tar
docker load -i images/caddy.tar
docker load -i images/rsshub.tar
```

## 5. 启动服务

```bash
# 使用 docker-compose 启动
docker compose -f docker/docker-compose.vps.yml up -d

# 查看服务状态
docker compose -f docker/docker-compose.vps.yml ps

# 查看日志
docker compose -f docker/docker-compose.vps.yml logs -f web
```

## 6. 初始化数据库（首次部署）

```bash
# 进入容器
docker compose -f docker/docker-compose.vps.yml exec web bash

# 运行迁移
python manage.py migrate

# 创建超级用户
python manage.py createsuperuser

# 退出容器
exit
```

## 7. 验证部署

```bash
# 检查健康状态
curl http://localhost:8000/health/

# 检查服务
docker compose -f docker/docker-compose.vps.yml ps
```

访问 `http://your-vps-ip:8000` 应该能看到应用。

## 常用维护命令

```bash
# 停止服务
docker compose -f docker/docker-compose.vps.yml down

# 重启服务
docker compose -f docker/docker-compose.vps.yml restart

# 查看日志
docker compose -f docker/docker-compose.vps.yml logs -f

# 备份数据
./scripts/vps-backup.sh

# 恢复数据
./scripts/vps-restore.sh
```

## 故障排查

| 问题 | 解决方案 |
|------|---------|
| 容器启动失败 | `docker compose logs web` 查看日志 |
| 数据库连接失败 | 检查 .env 中的数据库配置 |
| 端口被占用 | 修改 docker-compose.vps.yml 中的端口映射 |
| 静态文件 404 | `docker compose exec web python manage.py collectstatic` |

## 目录结构

```
agomsaaf-vps-bundle-xxxxxxxx/
├── images/          # Docker 镜像
├── backups/         # 数据备份
├── deploy/          # 部署配置
│   └── .env.vps.example
├── docker/          # Docker 配置
│   ├── Dockerfile.prod
│   ├── docker-compose.vps.yml
│   └── entrypoint.prod.sh
└── scripts/         # 维护脚本
    ├── deploy-on-vps.sh
    ├── vps-backup.sh
    └── vps-restore.sh
```
