# AgomSAAF Dockerfile
# 多阶段构建，优化镜像大小

# 阶段1: 构建阶段
FROM python:3.11-slim as builder

WORKDIR /app

# 安装构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖到临时目录
RUN pip install --no-cache-dir --user -r requirements.txt


# 阶段2: 运行阶段
FROM python:3.11-slim

WORKDIR /app

# 从构建阶段复制已安装的包
COPY --from=builder /root/.local /root/.local

# 确保 Python 能找到安装的包
ENV PATH=/root/.local/bin:$PATH

# 安装运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY . .

# 创建 static 目录
RUN mkdir -p staticfiles

# 收集静态文件
RUN python manage.py collectstatic --noinput --clear

# 创建非 root 用户
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/ || exit 1

# 启动命令
CMD ["gunicorn", "core.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120"]
