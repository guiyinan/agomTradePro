# A 机部署指南：Linux VPS 上配置 FRPS + Nginx

## 1. 目标

A 机只做公网入口，不运行 AgomSAAF 主应用。

职责：

- `frps` 接收来自 B 的隧道连接
- `nginx` 暴露公网域名和 HTTPS
- 将外部请求转发到 `frps` 的 HTTP 虚拟主机端口

## 2. 机器要求

建议系统：

- Ubuntu 22.04 LTS 或 Debian 12

建议安装：

- `frps`
- `nginx`
- `certbot`
- `ufw`
- `curl`
- `jq`

## 3. 端口规划

建议：

- `22`：SSH
- `80`：HTTP
- `443`：HTTPS
- `7000`：FRP 控制端口
- `8080`：FRPS `vhostHTTPPort`，仅本机使用更好

说明：

- 公网入口优先走 `443`
- `8080` 最好只让本机 `nginx` 访问
- `7000` 最好在防火墙层限制来源

## 4. 安装示例

Ubuntu/Debian：

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx ufw curl jq
```

`frp` 建议从官方发布包安装，放在 `/opt/frp/`。

目录建议：

```text
/opt/frp/
  frps
  frps.toml
```

## 5. FRPS 配置样例

文件建议：`/opt/frp/frps.toml`

```toml
bindPort = 7000

# B 机 frpc 连接时要用同一个 token
auth.method = "token"
auth.token = "CHANGE_ME_STRONG_RANDOM_TOKEN"

# HTTP 类型代理会先落到这里，再由 nginx 转发
vhostHTTPPort = 8080

# 可选：日志
log.to = "/var/log/frps.log"
log.level = "info"
log.maxDays = 7

# 可选：限制端口池，减少误用
# allowPorts = [
#   { start = 18000, end = 18099 }
# ]
```

注意：

- `auth.token` 必须换成高强度随机值
- 这里不建议直接让 `frps` 暴露 HTTPS
- HTTPS 终止统一交给 `nginx`

## 6. FRPS systemd 服务

文件：`/etc/systemd/system/frps.service`

```ini
[Unit]
Description=FRP Server
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/frp
ExecStart=/opt/frp/frps -c /opt/frp/frps.toml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable frps
sudo systemctl start frps
sudo systemctl status frps
```

## 7. Nginx 站点配置样例

假设域名是 `agomsaaf.example.com`。

文件：`/etc/nginx/sites-available/agomsaaf.conf`

```nginx
server {
    listen 80;
    server_name agomsaaf.example.com;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name agomsaaf.example.com;

    ssl_certificate /etc/letsencrypt/live/agomsaaf.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/agomsaaf.example.com/privkey.pem;

    client_max_body_size 20m;
    proxy_read_timeout 300s;
    proxy_connect_timeout 60s;
    proxy_send_timeout 300s;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host $host;
    }
}
```

启用：

```bash
sudo ln -s /etc/nginx/sites-available/agomsaaf.conf /etc/nginx/sites-enabled/agomsaaf.conf
sudo nginx -t
sudo systemctl reload nginx
```

## 8. 证书签发

```bash
sudo certbot --nginx -d agomsaaf.example.com
```

如果首次还没启用 HTTPS server 段，也可以先只开 80，再签发后补 443 配置。

## 9. 防火墙建议

以 `ufw` 为例：

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 7000/tcp
sudo ufw enable
sudo ufw status
```

更稳的做法：

- `7000/tcp` 只允许 B 的出口 IP
- `8080/tcp` 不对公网开放

## 10. 健康检查

检查服务：

```bash
systemctl status frps
systemctl status nginx
ss -lntp | grep -E ':(80|443|7000|8080)'
```

外部检查：

```bash
curl -I http://agomsaaf.example.com
curl -I https://agomsaaf.example.com
```

等 B 机 `frpc` 连上后，再检查：

```bash
curl -H "Host: agomsaaf.example.com" http://127.0.0.1:8080/api/health/
curl https://agomsaaf.example.com/api/health/
```

## 11. 常见问题

### 1. 域名能打开但 502

优先检查：

- `frps` 是否启动
- B 的 `frpc` 是否连接成功
- B 本机应用端口是否真的监听

### 2. 证书正常但 API 返回 Host 错误

检查 Django：

- `ALLOWED_HOSTS`
- 反代头配置
- `CSRF_TRUSTED_ORIGINS`

### 3. `frpc` 能连上，但页面不通

大概率是：

- B 上本地端口填错
- Docker 只监听容器内，没有映射到宿主机

## 12. 推荐最终状态

A 上最终保留：

- `nginx`
- `frps`
- HTTPS 域名

不要在 A 上再跑一套 AgomSAAF，避免职责混乱。
