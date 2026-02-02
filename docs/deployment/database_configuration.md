# AgomSAAF 数据库配置文档

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
Database: agomsaaf
User: agomsaaf
Password: changeme (请修改)
```

### 连接字符串

```
# Django/DATABASE_URL
DATABASE_URL=postgres://agomsaaf:changeme@localhost:5433/agomsaaf

# psql 命令行
docker exec -it agomsaaf_postgres_dev psql -U agomsaaf -d agomsaaf

# Python/Django
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'agomsaaf',
        'USER': 'agomsaaf',
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
| `.env` | ✅ 已更新 | DATABASE_URL=postgresql://...@localhost:5433/agomsaaf |
| `docker-compose-dev.yml` | ✅ 已更新 | 端口映射 5433:5432 |
| `docker-compose.yml` | ✅ 已更新 | 端口映射 5433:5432 |
| `core/settings/development.py` | ✅ 默认配置 | 使用 env.db() 读取 DATABASE_URL |
| `core/settings/production.py` | ✅ 默认配置 | 使用 env.db() 读取 DATABASE_URL |

---

## 启动步骤

### 1. 启动 PostgreSQL

```bash
# 进入项目目录
cd D:/githv/agomSAAF

# 启动 PostgreSQL 和 Redis
docker compose -f docker-compose-dev.yml up -d

# 检查状态
docker ps | grep agomsaaf
```

### 2. 验证连接

```bash
# 检查 PostgreSQL 健康状态
docker exec agomsaaf_postgres_dev pg_isready -U agomsaaf

# 连接数据库
docker exec -it agomsaaf_postgres_dev psql -U agomsaaf -d agomsaaf
```

### 3. 运行 Django 迁移（如需要）

```bash
# 设置环境变量（如果使用本地 Python）
export DATABASE_URL="postgres://agomsaaf:changeme@localhost:5433/agomsaaf"

# 运行迁移
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
DATABASE_URL=postgresql://agomsaaf:changeme@localhost:5434/agomsaaf
```

### 方案 B：停止占用端口的服务

```bash
# 查找占用端口的进程
netstat -ano | findstr :5433

# 停止对应的服务
docker stop <container_name>
```

---

## 常用命令

### 数据库连接

```bash
# PostgreSQL 容器内
docker exec -it agomsaaf_postgres_dev psql -U agomsaaf -d agomsaaf

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
docker logs agomsaaf_postgres_dev --tail 50

# 重启容器
docker restart agomsaaf_postgres_dev

# 停止容器
docker compose -f docker-compose-dev.yml down

# 重新启动
docker compose -f docker-compose-dev.yml up -d
```

### 数据备份

```bash
# 导出数据
docker exec agomsaaf_postgres_dev pg_dump -U agomsaaf agomsaaf > backup_$(date +%Y%m%d).sql

# 导入数据
docker exec -i agomsaaf_postgres_dev psql -U agomsaaf agomsaaf < backup_file.sql
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
