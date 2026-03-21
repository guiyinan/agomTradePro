# 数据库配置指南 (Windows + Docker)

## 概述

本项目使用 PostgreSQL 作为主数据库，Redis 作为缓存和消息队列。在 Windows 本地开发中，推荐通过 Docker Desktop 运行这些服务。

## 适用平台

- Windows PowerShell：`.env` 初始化、虚拟环境激活、Docker Desktop、本地迁移
- 跨平台命令：`docker exec`、`psql`、容器健康检查

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Windows 主机                              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Docker Desktop (WSL2)                       │  │
│  │  ┌─────────────────────┐  ┌─────────────────────┐       │  │
│  │  │  PostgreSQL         │  │  Redis              │       │  │
│  │  │  - agomtradepro_postgres_dev  │  - agomtradepro_redis_dev  │       │  │
│  │  │  - Port: 5432      │  │  - Port: 6379       │       │  │
│  │  │  - Volume: data    │  │  - Volume: data     │       │  │
│  │  └─────────────────────┘  └─────────────────────┘       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  Django (.env) → localhost:5432 (PostgreSQL)                  │
│              → localhost:6379 (Redis)                         │
└────────────────────────────────────────────────────────────────┘
```

## 环境变量配置

### 配置原则

⚠️ **重要安全原则**：
- ✅ 敏感信息必须存储在 `.env` 文件中
- ✅ `.env` 文件必须在 `.gitignore` 中
- ✅ 提供 `.env.example` 作为模板
- ❌ 严禁将密码硬编码到代码中
- ❌ 严禁将 `.env` 提交到 git

### 配置流程

```
.env.example (模板, 提交到 git)
    ↓ 开发者复制并修改
.env (实际配置, 不提交到 git)
    ↓ Django 读取
Django Settings
```

### .env.example 模板

```env
# Django
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database - PostgreSQL
# 格式: postgresql://用户名:密码@主机:端口/数据库名
DATABASE_URL=postgresql://agomtradepro:your-password-here@localhost:5432/agomtradepro

# Redis
REDIS_URL=redis://localhost:6379/0

# Data Source API Keys
TUSHARE_TOKEN=
FRED_API_KEY=

# AI Provider API Keys (可选)
OPENAI_API_KEY=
DASHSCOPE_API_KEY=
```

### 开发环境配置

当前 `.env` 配置（仅用于本地开发）：

```env
# Database
DATABASE_URL=postgresql://agomtradepro:changeme@localhost:5432/agomtradepro

# Redis
REDIS_URL=redis://localhost:6379/0
```

## Docker 服务状态

### PostgreSQL

| 项目 | 值 |
|------|-----|
| 容器名 | agomtradepro_postgres_dev |
| 镜像 | postgres:15-alpine |
| 状态 | Up 3 days (healthy) |
| 端口 | 5432 → 0.0.0.0:5432 |
| Volume | agomtradepro_postgres_dev_data |
| 持久化 | ✅ |

连接参数:
| 参数 | 值 |
|------|-----|
| 用户名 | agomtradepro |
| 密码 | changeme |
| 主机 | localhost |
| 端口 | 5432 |
| 数据库 | agomtradepro |

### Redis

| 项目 | 值 |
|------|-----|
| 容器名 | agomtradepro_redis_dev |
| 镜像 | redis:7-alpine |
| 状态 | Up 3 days (healthy) |
| 端口 | 6379 → 0.0.0.0:6379 |
| Volume | agomtradepro_redis_dev_data |
| 持久化 | ✅ |

连接参数:
| 参数 | 值 |
|------|-----|
| 主机 | localhost |
| 端口 | 6379 |
| 数据库 | 0 |

## Django 配置

### development.py

已配置为从 `.env` 读取数据库连接：

```python
# core/settings/development.py
DATABASES = {
    'default': env.db('DATABASE_URL', default='sqlite:///db.sqlite3')
}

# Celery (使用 Redis)
CELERY_BROKER_URL = env('REDIS_URL', default=None)
CELERY_RESULT_BACKEND = env('REDIS_URL', default=None)
```

## 快速上手

### 1. 初始化项目

```powershell
# 复制环境变量模板
copy .env.example .env

# 编辑 .env，设置密码
notepad .env
```

### 2. 启动 Docker 容器

#### Windows PowerShell

```powershell
# 检查容器状态
docker ps -a --filter "name=agomtradepro"

# 如果未运行，启动容器
docker start agomtradepro_postgres_dev
docker start agomtradepro_redis_dev
```

### 3. 运行迁移

```powershell
# 激活虚拟环境
agomtradepro/Scripts/Activate.ps1

# 创建数据库表
python manage.py migrate

# 创建超级用户
python manage.py createsuperuser
```

### 4. 验证连接

#### Windows PowerShell

```powershell
# 测试数据库连接
python manage.py check --database default

# 测试 Redis 连接
python manage.py shell -c "from django.core.cache import cache; cache.set('test', 'ok'); print(cache.get('test'))"
```

## 数据迁移（从 SQLite）

如果之前使用 SQLite，需要迁移数据到 PostgreSQL：

```powershell
# 1. 临时切换到 SQLite
# 编辑 core/settings/development.py，改为 SQLite

# 2. 导出 SQLite 数据
python manage.py dumpdata --exclude contenttypes --exclude auth.Permission -o sqlite_backup.json

# 3. 切换回 PostgreSQL
# 编辑 core/settings/development.py，改回 env.db('DATABASE_URL')

# 4. 导入到 PostgreSQL
python manage.py loaddata sqlite_backup.json
```

## 常用操作

### PostgreSQL

#### 进入容器

```bash
docker exec -it agomtradepro_postgres_dev sh
```

#### 连接数据库

```bash
# 通过容器
docker exec -it agomtradepro_postgres_dev psql -U agomtradepro -d agomtradepro

# 使用 psql 客户端
psql -h localhost -p 5432 -U agomtradepro -d agomtradepro
```

#### 备份与恢复

```powershell
# 备份整个数据库
docker exec agomtradepro_postgres_dev pg_dump -U agomtradepro agomtradepro > backup.sql

# 恢复数据库
docker exec -i agomtradepro_postgres_dev psql -U agomtradepro agomtradepro < backup.sql
```

### Redis

#### 连接 Redis

```powershell
# 通过容器
docker exec -it agomtradepro_redis_dev redis-cli

# 使用 redis-cli
redis-cli -h localhost -p 6379
```

#### 常用命令

```powershell
# 测试连接
redis-cli ping

# 查看所有键
redis-cli keys "*"

# 清空数据库
redis-cli flushdb
```

### Volume 管理

#### 查看卷内容

```powershell
# PostgreSQL Volume
docker run --rm --mount source=agomtradepro_postgres_dev_data,target=/data,type=volume alpine ls -la /data

# Redis Volume
docker run --rm --mount source=agomtradepro_redis_dev_data,target=/data,type=volume alpine ls -la /data
```

#### 备份卷数据

```powershell
# PostgreSQL 卷备份
docker run --rm --mount source=agomtradepro_postgres_dev_data,target=/data,type=volume alpine sh -c "cd /data && tar czf - ." > postgres_backup.tar.gz

# Redis 卷备份
docker run --rm --mount source=agomtradepro_redis_dev_data,target=/data,type=volume alpine sh -c "cd /data && tar czf - ." > redis_backup.tar.gz
```

## 数据持久化说明

### Windows Docker Volume 存储机制

在 Windows 上，Docker Desktop 运行在 WSL2 虚拟机中：

```
Windows 文件系统
  └── C:\Users\<用户>\AppData\Local\Docker\wsl\data\ext4.vhdx
       └── WSL2 虚拟机
            └── /var/lib/docker/volumes/
                 ├── agomtradepro_postgres_dev_data/_data
                 └── agomtradepro_redis_dev_data/_data
```

### 访问数据的三种方式

1. **通过 Docker 容器** (推荐)
   ```powershell
   docker exec -it agomtradepro_postgres_dev sh
   ```

2. **通过 WSL2**
   ```powershell
   wsl
   ls /var/lib/docker/volumes/agomtradepro_postgres_dev_data/_data
   ```

3. **备份到 Windows 文件系统**
   ```powershell
   docker exec agomtradepro_postgres_dev pg_dump -U agomtradepro agomtradepro > backup.sql
   ```

## 安全配置建议

### 开发环境

⚠️ 当前配置仅适用于本地开发：

- 密码使用默认值 `changeme`
- DEBUG=True
- 允许的主机限制为 localhost

### 生产环境

✅ 生产环境必须修改：

```env
# .env (生产环境)
SECRET_KEY=<强随机密钥>
DEBUG=False
ALLOWED_HOSTS=yourdomain.com

# 使用强密码
DATABASE_URL=postgresql://agomtradepro:<强密码>@<数据库主机>:5432/agomtradepro

# Redis 配置密码
REDIS_URL=redis://:<密码>@<Redis主机>:6379/0
```

### 密码生成

```powershell
# 生成强密码 (Python)
python -c "import secrets; print(secrets.token_urlsafe(32))"

# 生成 SECRET_KEY
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## 故障排查

### PostgreSQL 连接失败

```powershell
# 检查容器状态
docker ps | findstr postgres

# 检查端口映射
docker port agomtradepro_postgres_dev

# 查看容器日志
docker logs agomtradepro_postgres_dev
```

### Redis 连接失败

```powershell
# 检查容器状态
docker ps | findstr redis

# 测试连接
redis-cli ping

# 查看容器日志
docker logs agomtradepro_redis_dev
```

### 密码认证失败

检查 `.env` 中的密码与容器环境变量是否一致：

```powershell
# 查看容器环境变量
docker inspect agomtradepro_postgres_dev | findstr POSTGRES
```

### 数据丢失

Volume 数据不会随容器删除而丢失，但如果 Volume 被删除则无法恢复：

```powershell
# 查看 Volume
docker volume ls | findstr agomtradepro

# ⚠️ 危险操作 - 会永久删除数据
# docker volume rm agomtradepro_postgres_dev_data
```

## 生产环境部署

### 推荐方案

1. **云数据库** (推荐)
   - AWS RDS
   - Azure Database for PostgreSQL
   - Google Cloud SQL

2. **独立数据库服务器**
   - 独立的 PostgreSQL 服务器
   - 配置主从复制

3. **容器化部署**
   - 使用 docker-compose
   - 配置持久化卷
   - 设置强密码

### docker-compose 示例

```yaml
version: '3.8'
services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis_data:/data
    ports:
      - "6379:6379"

volumes:
  postgres_data:
  redis_data:
```

## 参考资料

- [Docker Volumes](https://docs.docker.com/storage/volumes/)
- [PostgreSQL 官方文档](https://www.postgresql.org/docs/)
- [Redis 官方文档](https://redis.io/docs/)
- [Django 数据库配置](https://docs.djangoproject.com/en/5.0/ref/settings/#databases)
- [Django-environ](https://django-environ.readthedocs.io/)
