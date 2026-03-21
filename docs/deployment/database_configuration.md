# AgomTradePro 数据库配置文档

> 更新时间: 2026-01-31
> 数据库: PostgreSQL 15 on Docker

---

## 当前配置

### 端口分配

| 环境 | 主机端口 | 容器端口 | 说明 |
|------|----------|----------|------|
| 开发环境 | 5433 | 5432 | `docker-compose-dev.yml` |
| 生产环境 | 5433 | 5432 | `docker-compose.yml` |

### 连接信息

```
Host: localhost
Port: 5433
Database: agomtradepro
User: agomtradepro
Password: changeme (请修改)
```

### 连接字符串

```
# Django/DATABASE_URL
DATABASE_URL=postgres://agomtradepro:changeme@localhost:5433/agomtradepro

# psql 命令行
docker exec -it agomtradepro_postgres_dev psql -U agomtradepro -d agomtradepro

# Python/Django
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'agomtradepro',
        'USER': 'agomtradepro',
        'PASSWORD': 'changeme',
        'HOST': 'localhost',
        'PORT': 5433,
    }
}
```

---

## 配置文件清单

| 文件 | 状态 | 说明 |
|------|------|------|
| `.env` | ✅ 已更新 | DATABASE_URL=postgresql://...@localhost:5433/agomtradepro |
| `docker-compose-dev.yml` | ✅ 已更新 | 端口映射 5433:5432 |
| `docker-compose.yml` | ✅ 已更新 | 端口映射 5433:5432 |
| `core/settings/development.py` | ✅ 默认配置 | 使用 env.db() 读取 DATABASE_URL |
| `core/settings/production.py` | ✅ 默认配置 | 使用 env.db() 读取 DATABASE_URL |

---

## 启动步骤

### 1. 启动 PostgreSQL

#### Windows PowerShell

```powershell
cd .
docker compose -f docker-compose-dev.yml up -d
docker ps
```

#### Linux/macOS / Git Bash

```bash
cd .
docker compose -f docker-compose-dev.yml up -d
docker ps | grep agomtradepro
```

### 2. 验证连接

```bash
# 检查 PostgreSQL 健康状态
docker exec agomtradepro_postgres_dev pg_isready -U agomtradepro

# 连接数据库
docker exec -it agomtradepro_postgres_dev psql -U agomtradepro -d agomtradepro
```

### 3. 运行 Django 迁移（如需要）

#### Windows PowerShell

```powershell
$env:DATABASE_URL="postgres://agomtradepro:changeme@localhost:5433/agomtradepro"
python manage.py migrate
```

#### Linux/macOS (bash)

```bash
export DATABASE_URL="postgres://agomtradepro:changeme@localhost:5433/agomtradepro"
python manage.py migrate
```

---

## 端口冲突解决方案

如果 5433 端口也被占用，可以：

### 方案 A：修改为其他端口

```yaml
# docker-compose-dev.yml
ports:
  - "5434:5432"  # 改用 5434

# .env
DATABASE_URL=postgresql://agomtradepro:changeme@localhost:5434/agomtradepro
```

### 方案 B：停止占用端口的服务

#### Windows PowerShell

```powershell
netstat -ano | findstr :5433
docker stop <container_name>
```

#### Linux/macOS (bash)

```bash
lsof -i :5433
docker stop <container_name>
```

---

## 常用命令

### 数据库连接

```bash
# PostgreSQL 容器内
docker exec -it agomtradepro_postgres_dev psql -U agomtradepro -d agomtradepro

# 查看所有表
\dt

# 查看宏观数据
SELECT COUNT(*) FROM macro_indicator;
SELECT code, value, original_unit FROM macro_indicator LIMIT 10;

# 退出
\q
```

### 容器管理

```bash
# 查看日志
docker logs agomtradepro_postgres_dev --tail 50

# 重启容器
docker restart agomtradepro_postgres_dev

# 停止容器
docker compose -f docker-compose-dev.yml down

# 重新启动
docker compose -f docker-compose-dev.yml up -d
```

### 数据备份

```bash
# 导出数据
docker exec agomtradepro_postgres_dev pg_dump -U agomtradepro agomtradepro > backup_$(date +%Y%m%d).sql

# 导入数据
docker exec -i agomtradepro_postgres_dev psql -U agomtradepro agomtradepro < backup_file.sql
```

---

## 安全提醒

⚠️ **生产环境必须修改默认密码！**

```bash
# 生成随机密码
openssl rand -base64 32

# 更新 docker-compose.yml 的 POSTGRES_PASSWORD
# 更新 .env 的 DATABASE_URL
```
