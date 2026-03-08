# AgomSAAF Docker 部署文档

## 概述

本文档介绍如何在 Windows 环境下使用 Docker 部署 AgomSAAF 项目的开发环境。

**架构说明**：
- Django 应用运行在本地（便于开发和调试）
- PostgreSQL 和 Redis 运行在 Docker 容器中
- 使用 `docker-compose-dev.yml` 配置

## 快速开始

### 适用平台

- Windows 专用：`Docker Desktop`、`deploy-docker-dev.ps1`、`migrate-to-postgres.ps1`
- 跨平台命令：`docker compose`、`python manage.py ...`、`docker exec ...`

### 前置要求

1. **Docker Desktop for Windows**
   - 下载：https://www.docker.com/products/docker-desktop/
   - 安装后启动 Docker Desktop

2. **Python 虚拟环境（Windows PowerShell）**
   ```powershell
   agomsaaf/Scripts/Activate.ps1
   ```

### 一键部署

运行 PowerShell 部署脚本（自动检测代理、启动服务）：

```powershell
cd .
.\scripts\deploy-docker-dev.ps1
```

**脚本功能**：
- ✅ 检查 Docker 是否运行
- ✅ 自动创建 .env 配置文件
- ✅ 检测代理速度（直连 vs 127.0.0.1:10808）
- ✅ 检查端口占用（5432, 6379）
- ✅ 启动 PostgreSQL 和 Redis 容器
- ✅ 等待服务就绪

### 首次部署后操作

#### Windows PowerShell

```powershell
# 1. 激活虚拟环境
agomsaaf/Scripts/Activate.ps1

# 2. 运行数据库迁移
python manage.py migrate

# 3. 创建超级用户（可选）
python manage.py createsuperuser

# 4. 启动 Django 开发服务器
python manage.py runserver
```

#### 跨平台 Shell

```bash
# Windows Git Bash / WSL / Linux / macOS
source agomsaaf/Scripts/activate 2>/dev/null || source agomsaaf/bin/activate
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## 服务地址与端口

| 服务 | 地址 | 说明 |
|-----|------|-----|
| Django Web | http://localhost:8000 | 主应用 |
| Admin 后台 | http://localhost:8000/admin/ | 管理界面 |
| API 文档 | http://localhost:8000/api/docs/ | Swagger UI |
| PostgreSQL | localhost:5432 | 数据库 |
| Redis | localhost:6379 | 缓存/消息队列 |

## 初始账号密码

### PostgreSQL 数据库

```
主机: localhost:5432
数据库: agomsaaf
用户: agomsaaf
密码: changeme（请在 .env 中修改）
```

### Django 超级用户

需手动创建：

```powershell
python manage.py createsuperuser
```

## 数据持久化

### Docker Volume 位置

| 数据类型 | Volume 名称 | 说明 |
|---------|------------|-----|
| PostgreSQL 数据 | postgres_dev_data | 数据库文件 |
| Redis 数据 | redis_dev_data | Redis 持久化 |

### 查看卷位置

```powershell
docker volume inspect agomsaaf_dev_postgres_dev_data
docker volume inspect agomsaaf_dev_redis_dev_data
```

### 备份到本地目录（可选）

如需将数据持久化到本地目录，修改 `docker-compose-dev.yml`：

```yaml
services:
  postgres:
    volumes:
      - ./data/postgres:/var/lib/postgresql/data  # 本地目录
```

## 数据备份与恢复

### PostgreSQL 备份

```powershell
# 备份到 SQL 文件
docker exec agomsaaf_postgres_dev pg_dump -U agomsaaf agomsaaf > backup.sql

# 备份到带时间戳的文件
docker exec agomsaaf_postgres_dev pg_dump -U agomsaaf agomsaaf > "backup-$(Get-Date -Format 'yyyyMMdd-HHmmss').sql"
```

### PostgreSQL 恢复

```powershell
# 从 SQL 文件恢复
Get-Content backup.sql | docker exec -i agomsaaf_postgres_dev psql -U agomsaaf -d agomsaaf
```

### SQLite → PostgreSQL 迁移

如果你之前使用 SQLite，可以使用迁移脚本：

```powershell
.\scripts\migrate-to-postgres.ps1
```

**迁移步骤**：
1. 备份 SQLite 数据（排除 contenttypes 和 auth.permission）
2. 启动 Docker 容器
3. 执行 migrate 创建表结构
4. 使用 loaddata 恢复数据

## 常用运维命令

### Docker 容器管理

#### Windows PowerShell

```powershell
# 启动服务
docker compose -f docker-compose-dev.yml up -d

# 停止服务
docker compose -f docker-compose-dev.yml down

# 重启服务
docker compose -f docker-compose-dev.yml restart

# 查看服务状态
docker compose -f docker-compose-dev.yml ps

# 查看日志（所有服务）
docker compose -f docker-compose-dev.yml logs -f

# 查看特定服务日志
docker compose -f docker-compose-dev.yml logs -f postgres
docker compose -f docker-compose-dev.yml logs -f redis
```

#### 跨平台 Shell

```bash
docker compose -f docker-compose-dev.yml up -d
docker compose -f docker-compose-dev.yml down
docker compose -f docker-compose-dev.yml restart
docker compose -f docker-compose-dev.yml ps
docker compose -f docker-compose-dev.yml logs -f
docker compose -f docker-compose-dev.yml logs -f postgres
docker compose -f docker-compose-dev.yml logs -f redis
```

### 数据库操作

```powershell
# 连接到 PostgreSQL
docker exec -it agomsaaf_postgres_dev psql -U agomsaaf -d agomsaaf

# 查看数据库列表
docker exec agomsaaf_postgres_dev psql -U agomsaaf -d agomsaaf -c "\l"

# 查看表列表
docker exec agomsaaf_postgres_dev psql -U agomsaaf -d agomsaaf -c "\dt"

# 重置数据库（危险操作！）
docker compose -f docker-compose-dev.yml down -v
docker compose -f docker-compose-dev.yml up -d
python manage.py migrate
```

### Redis 操作

```powershell
# 连接到 Redis
docker exec -it agomsaaf_redis_dev redis-cli

# 清空所有缓存
docker exec agomsaaf_redis_dev redis-cli FLUSHALL

# 查看信息
docker exec agomsaaf_redis_dev redis-cli INFO
```

### Celery 开发（Windows 兼容）

**注意**：Celery 在 Windows 上不支持多进程（prefork pool），需要使用 solo pool：

```powershell
# 启动 Celery Worker（Windows 模式）
celery -A core worker -l info --pool=solo --concurrency=1

# 启动 Celery Beat（定时任务）
celery -A core beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

或者使用 Django management command：

```powershell
python manage.py celery_worker_windows
python manage.py celery_beat
```

## 环境配置

### .env 文件说明

```env
# 数据库配置
POSTGRES_PASSWORD=changeme                    # PostgreSQL 密码（请修改）
DATABASE_URL=postgresql://agomsaaf:changeme@localhost:5432/agomsaaf

# Redis 配置
REDIS_URL=redis://localhost:6379/0

# Django 配置
SECRET_KEY=django-insecure-change-this        # 密钥（生产环境请更换）
DEBUG=True                                    # 调试模式
ALLOWED_HOSTS=localhost,127.0.0.1             # 允许的主机
```

### 生成新的 SECRET_KEY

```powershell
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## 故障排查

### Docker 相关

**问题：Docker 未运行**
```
解决方案：启动 Docker Desktop
```

**问题：端口被占用**
```powershell
# 查看端口占用
netstat -ano | findstr "5432"
netstat -ano | findstr "6379"

# 解决方案：关闭占用端口的服务或修改 docker-compose-dev.yml 中的端口映射
```

**问题：容器启动失败**
```powershell
# 查看容器日志
docker-compose -f docker-compose-dev.yml logs postgres
docker-compose -f docker-compose-dev.yml logs redis

# 重置并重新创建
docker-compose -f docker-compose-dev.yml down -v
docker-compose -f docker-compose-dev.yml up -d
```

### 数据库连接

**问题：无法连接到 PostgreSQL**

1. 检查容器是否运行：
   ```powershell
   docker ps | findstr postgres
   ```

2. 测试连接：
   ```powershell
   docker exec agomsaaf_postgres_dev pg_isready -U agomsaaf
   ```

3. 检查 .env 配置：
   ```env
   DATABASE_URL=postgresql://agomsaaf:changeme@localhost:5432/agomsaaf
   ```

### 代理设置

如果直连 Docker Hub 很慢，可以配置代理：

1. 打开 Docker Desktop
2. 进入 **Settings** → **Resources** → **Proxies**
3. 启用 **Manual proxy configuration**
4. 设置代理地址：`127.0.0.1:10808`
5. 点击 **Apply & Restart**

### Celery Windows 问题

**问题：Celery 在 Windows 上报错**

Celery 默认使用 prefork pool（多进程），在 Windows 上不支持。

**解决方案**：使用 solo pool

```powershell
# 错误方式
celery -A core worker -l info

# 正确方式（Windows）
celery -A core worker -l info --pool=solo
```

或在 `core/settings/` 中添加：

```python
import os
if os.name == 'nt':  # Windows
    CELERY_WORKER_POOL = 'solo'
```

## 完整版部署

如果你需要部署完整版（Django 也在 Docker 中运行），使用：

```powershell
docker-compose -f docker-compose.yml up -d
```

完整版包含：
- Nginx 反向代理
- Django Gunicorn 服务
- Celery Worker + Beat
- PostgreSQL + Redis

详见 `docker-compose.yml` 配置。

## 附录

### 目录结构

```
AgomSAAF/
├── docker-compose.yml           # 完整版配置
├── docker-compose-dev.yml       # 开发版配置（仅数据库）
├── .env                         # 环境变量
├── .env.example                 # 环境变量模板
├── scripts/
│   ├── deploy-docker-dev.ps1    # 一键部署脚本
│   └── migrate-to-postgres.ps1  # 数据迁移脚本
└── docs/
    └── DOCKER_DEPLOYMENT.md     # 本文档
```

### 有用的 Docker 命令

```powershell
# 清理未使用的镜像
docker image prune -a

# 清理未使用的卷
docker volume prune

# 查看容器资源使用
docker stats

# 进入容器 shell
docker exec -it agomsaaf_postgres_dev sh
docker exec -it agomsaaf_redis_dev sh
```

### 联系与支持

如有问题，请查看：
- 项目文档：`docs/` 目录
- Django 文档：https://docs.djangoproject.com/
- Docker 文档：https://docs.docker.com/

