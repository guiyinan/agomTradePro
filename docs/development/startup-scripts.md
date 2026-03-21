# AgomTradePro 启动脚本使用指南

## 快速开始

最简单的启动方式：

```batch
start.bat
```

这将显示菜单，选择你需要启动的模式。

---

## 脚本文件说明

### 根目录脚本

| 脚本 | 用途 | 说明 |
|------|------|------|
| `start.bat` | 主启动菜单 | 推荐新用户使用 |
| `scripts/dev.bat` | 快速开发启动 | SQLite 模式，最简单 |
| `scripts/docker-dev.bat` | Docker 完整环境 | PostgreSQL + Redis + Celery |
| `scripts/stop-dev.bat` | 停止所有服务 | 停止 Docker 容器和后台进程 |
| `scripts/start-dev.ps1` | PowerShell 版本 | 功能同 docker-dev.bat |
| `scripts/stop-dev.ps1` | PowerShell 版本 | 功能同 stop-dev.bat |
| `scripts/package-portable-project.ps1` | 便携打包 | 打包到上层目录，默认排除缓存、数据库、VPS/bundle 文件 |
| `venv.bat` | 激活虚拟环境 | 仅激活 venv，不启动服务 |

### 已废弃的脚本（保留用于兼容）

| 脚本 | 状态 | 替代方案 |
|------|------|----------|
| `run.bat` | 已废弃 | 使用 `scripts/dev.bat` |
| `start_all.bat` | 已废弃 | 使用 `scripts/docker-dev.bat` |
| `stop_all.bat` | 已废弃 | 使用 `scripts/stop-dev.bat` |
| `start-dev.ps1`（根目录）| 已废弃 | 使用 `scripts/start-dev.ps1` |

---

## 启动模式详解

### 模式 1: 快速开发（SQLite）

**适用场景：** 日常开发、功能调试

**启动方式：**
```batch
# 方式1：通过菜单
start.bat
# 选择 [1]

# 方式2：直接运行
scripts\dev.bat

# 方式3：指定端口
scripts\dev.bat 8001
```

**特点：**
- 无需 Docker
- 使用 SQLite 数据库
- 无后台进程
- 单窗口运行

**缺点：**
- 不支持 Celery 异步任务
- 并发性能有限

---

### 模式 2: Docker 完整环境

**适用场景：** 完整功能测试、生产环境模拟

**启动方式：**
```batch
# 方式1：通过菜单
start.bat
# 选择 [2]

# 方式2：直接运行
scripts\docker-dev.bat

# 方式3：指定端口
scripts\docker-dev.bat 8001

# 方式4：禁用 Celery
scripts\docker-dev.bat --no-celery --no-beat
```

**特点：**
- PostgreSQL 数据库（生产级）
- Redis 缓存
- Celery Worker（异步任务）
- Celery Beat（定时任务）

**要求：**
- Docker Desktop 已安装并运行

---

### 模式 3: 激活虚拟环境

**适用场景：** 手动执行管理命令

**启动方式：**
```batch
# 方式1：通过菜单
start.bat
# 选择 [4]

# 方式2：直接运行
venv.bat
```

**常用命令：**
```batch
# 数据库迁移
python manage.py makemigrations
python manage.py migrate

# 创建管理员
python manage.py createsuperuser

# Django Shell
python manage.py shell

# 收集静态文件
python manage.py collectstatic

# 运行测试
pytest tests/
```

---

## 停止服务

### 停止 Docker 环境的所有服务

```batch
scripts\stop-dev.bat
```

这将：
1. 停止 PostgreSQL 和 Redis 容器
2. 停止 Celery Worker 和 Beat 进程
3. 清理临时文件

**注意：** Django 服务器需要在主窗口按 Ctrl+C 停止。

---

## 便携打包

适用场景：把项目拷到另一台 Windows 电脑上，尽快重新跑起来。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package-portable-project.ps1
```

无参数执行时会进入交互式向导。

默认行为：

- 输出到项目上层目录
- 文件名：`项目名-时间戳.7z` 或 `项目名-时间戳.zip`
- 自动排除虚拟环境、缓存、日志、`dist/`、本地数据库、`.env`
- 自动排除 VPS bundle / 远端部署脚本

可选参数：

```powershell
# 强制 zip
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package-portable-project.ps1 -Format zip

# 包含 .env 和本地 SQLite
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package-portable-project.ps1 -IncludeEnv -IncludeDatabase

# 只看排除列表，不实际打包
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package-portable-project.ps1 -DryRun
```

---

## 常见问题

### Q: Docker 启动失败？

```batch
# 检查 Docker 状态
docker --version
docker ps

# 重启 Docker Desktop
# 然后重新运行
scripts\docker-dev.bat
```

### Q: PostgreSQL 连接失败？

```batch
# 检查容器状态
docker ps | findstr postgres

# 查看容器日志
docker logs agomtradepro_postgres_dev

# 重启容器
docker restart agomtradepro_postgres_dev
```

### Q: 如何切换回 SQLite？

编辑 `.env` 文件，注释掉 `DATABASE_URL`：
```ini
# DATABASE_URL=postgresql://...
```

或使用 `scripts/dev.bat` 启动（默认 SQLite）。

### Q: 端口被占用？

```batch
# 使用其他端口启动
scripts\dev.bat 8001
scripts\docker-dev.bat 8001
```

---

## 目录结构

```
AgomTradePro/
├── start.bat                 # 主启动菜单（推荐）
├── scripts/
│   ├── dev.bat              # 快速开发启动
│   ├── docker-dev.bat       # Docker 完整环境
│   ├── stop-dev.bat         # 停止所有服务
│   ├── start-dev.ps1        # PowerShell 版本
│   └── stop-dev.ps1         # PowerShell 版本
├── venv.bat                  # 激活虚拟环境
├── docker-compose-dev.yml   # Docker 服务配置
└── .env                      # 环境配置（从 .env.example 复制）
```
