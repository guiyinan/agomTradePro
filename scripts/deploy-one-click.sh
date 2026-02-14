#!/usr/bin/env sh
# AgomSAAF VPS 一键部署脚本
# 用法: ./deploy-one-click.sh [bundle-file.tar.gz]

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { printf "${GREEN}[INFO]${NC} %s\n" "$*"; }
log_warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$*" >&2; }
log_error() { printf "${RED}[ERROR]${NC} %s\n" "$*" >&2; }

# 检测 docker compose 命令
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    log_error "docker compose 未安装"
    exit 1
fi

# 获取 bundle 文件路径
BUNDLE="${1:-$(ls -t agomsaaf-vps-bundle-*.tar.gz 2>/dev/null | head -1)}"

if [ -z "$BUNDLE" ]; then
    log_error "未找到 bundle 文件！"
    echo "用法: $0 [bundle-file.tar.gz]"
    echo "或确保当前目录有 agomsaaf-vps-bundle-*.tar.gz 文件"
    exit 1
fi

if [ ! -f "$BUNDLE" ]; then
    log_error "Bundle 文件不存在: $BUNDLE"
    exit 1
fi

log_info "使用 bundle: $BUNDLE"

# 检查是否为 root
if [ "$EUID" -ne 0 ]; then
    log_warn "建议使用 root 用户运行（部分操作需要权限）"
fi

# 解压目录
EXTRACT_DIR="./agomsaaf-deploy"
RELEASE_NAME=$(basename "$BUNDLE" .tar.gz)
DEPLOY_DIR="$EXTRACT_DIR/$RELEASE_NAME"

log_info "解压 bundle..."
rm -rf "$EXTRACT_DIR"
mkdir -p "$EXTRACT_DIR"
tar -xzf "$BUNDLE" -C "$EXTRACT_DIR"

if [ ! -d "$DEPLOY_DIR" ]; then
    log_error "解压失败，目录不存在: $DEPLOY_DIR"
    exit 1
fi

cd "$DEPLOY_DIR"
log_info "工作目录: $DEPLOY_DIR"

# 检查并配置 .env
if [ ! -f deploy/.env ]; then
    log_info "创建 .env 配置文件..."
    cp deploy/.env.vps.example deploy/.env

    # 生成随机 SECRET_KEY
    if command -v python >/dev/null 2>&1; then
        SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || echo "")
        if [ -z "$SECRET_KEY" ]; then
            SECRET_KEY=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 50 | head -n 1)
        fi
    else
        SECRET_KEY=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 50 | head -n 1)
    fi

    sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET_KEY|" deploy/.env
    log_info "已生成随机 SECRET_KEY"

    # 询问域名
    printf "${YELLOW}请输入域名 (留空则仅 HTTP): ${NC}"
    read -r DOMAIN
    if [ -n "$DOMAIN" ]; then
        sed -i "s|^DOMAIN=.*|DOMAIN=$DOMAIN|" deploy/.env
        log_info "已设置域名: $DOMAIN"
    fi
fi

# 检查 SECRET_KEY 是否已更改
SECRET_KEY=$(grep '^SECRET_KEY=' deploy/.env | cut -d '=' -f2-)
if [ "$SECRET_KEY" = "change-this-to-a-strong-secret" ] || [ -z "$SECRET_KEY" ]; then
    log_error "请先编辑 deploy/.env 文件，设置 SECRET_KEY"
    log_info "运行: vim deploy/.env"
    exit 1
fi

# 加载 Docker 镜像
log_info "加载 Docker 镜像..."
for image_tar in images/*.tar; do
    if [ -f "$image_tar" ]; then
        log_info "  加载 $(basename "$image_tar")..."
        docker load -i "$image_tar" >/dev/null 2>&1
    fi
done

# 自动检测 web 镜像版本
DETECTED_IMAGE=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep '^agomsaaf-web:' | head -n 1 || true)
if [ -n "$DETECTED_IMAGE" ]; then
    sed -i "s|^WEB_IMAGE=.*|WEB_IMAGE=$DETECTED_IMAGE|" deploy/.env
    log_info "自动检测镜像: $DETECTED_IMAGE"
fi

# 生成 Caddyfile
DOMAIN=$(grep '^DOMAIN=' deploy/.env | cut -d '=' -f2-)
if [ -n "$DOMAIN" ]; then
    SITE_ADDR="$DOMAIN"
else
    SITE_ADDR=":80"
fi

sed "s|__SITE_ADDRESS__|$SITE_ADDR|g" docker/Caddyfile.template > docker/Caddyfile
log_info "已生成 Caddyfile"

# 停止旧容器（如果存在）
log_info "停止旧容器..."
$COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env down 2>/dev/null || true

# 启动服务
log_info "启动服务..."
$COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env up -d

# 等待容器启动
log_info "等待容器启动..."
sleep 10

# 检查容器状态
$COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env ps

# 恢复数据库备份（如果存在）
if [ -f backups/db.sqlite3 ]; then
    log_info "恢复 SQLite 数据库..."
    sleep 5  # 等待 web 容器完全启动
    WEB_CID=$($COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env ps -q web)
    if [ -n "$WEB_CID" ]; then
        docker cp backups/db.sqlite3 "$WEB_CID:/app/data/db.sqlite3"
        $COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env restart web
        log_info "SQLite 数据库已恢复"
    fi
fi

# 运行数据库迁移
log_info "运行数据库迁移..."
sleep 3
$COMPOSE -f docker/docker-compose.vps.yml --env-file deploy/.env exec -T web python manage.py migrate --noinput || true

# 创建符号链接（方便管理）
CURRENT_LINK="/opt/agomsaaf-current"
mkdir -p /opt/agomsaaf
rm -f "$CURRENT_LINK"
ln -sf "$(pwd)" "$CURRENT_LINK"
log_info "当前部署链接: $CURRENT_LINK"

# 完成
echo ""
log_info "=================="
log_info "部署完成！"
echo ""
echo "访问地址:"
if [ -n "$DOMAIN" ]; then
    echo "  https://$DOMAIN"
else
    VPS_IP=$(hostname -I | awk '{print $1}')
    echo "  http://$VPS_IP:80"
    echo "  http://$VPS_IP:8000 (直接访问 Django)"
fi
echo ""
echo "常用命令:"
echo "  查看日志: $COMPOSE -f $CURRENT_LINK/docker/docker-compose.vps.yml --env-file deploy/.env logs -f"
echo "  重启服务: $COMPOSE -f $CURRENT_LINK/docker/docker-compose.vps.yml --env-file deploy/.env restart"
echo "  停止服务: $COMPOSE -f $CURRENT_LINK/docker/docker-compose.vps.yml --env-file deploy/.env down"
echo ""
echo "如需创建超级用户:"
echo "  $COMPOSE -f $CURRENT_LINK/docker/docker-compose.vps.yml --env-file deploy/.env exec web python manage.py createsuperuser"
echo ""
