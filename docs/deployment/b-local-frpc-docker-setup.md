# B 机部署指南：Windows + WSL2 + Docker 上配置 FRPC + AgomTradePro

## 1. 目标

B 机是真正运行 AgomTradePro 的机器。

职责：

- Docker 跑应用
- `frpc` 主动连接 A 机 `frps`
- 将本地 Web 服务通过隧道暴露给 A

## 2. 环境要求

Windows 侧建议安装：

- Windows 11 或更新版 Windows 10
- WSL2
- Docker Desktop
- Git
- Python 3.11+（建议）

WSL2 侧建议安装：

- Ubuntu
- `curl`
- `jq`
- `git`
- `frpc`

## 3. 推荐运行方式

推荐把仓库放在 WSL2 Linux 文件系统中运行，而不是放在 `/mnt/c/...` 下。

推荐路径：

```text
/home/<user>/agomTradePro
```

原因：

- Docker 挂载性能更稳定
- 文件 I/O 明显好于 Windows 挂载盘
- 少很多权限和换行符问题

## 4. Docker 端口建议

目标是把 AgomTradePro 映射到 B 本机回环地址，不直接暴露到局域网或公网。

推荐：

```text
127.0.0.1:18000 -> container:8000
```

这意味着：

- 本机可通过 `http://127.0.0.1:18000` 访问
- 外部不能直接访问 B 的这个端口
- `frpc` 再把这个端口转发到 A

## 5. Docker Compose 样例

如果你当前 Compose 已存在，只需要参考端口绑定思路，不一定照抄。

```yaml
services:
  web:
    build: .
    command: python manage.py runserver 0.0.0.0:8000
    ports:
      - "127.0.0.1:18000:8000"
    env_file:
      - .env
```

如果你是 `gunicorn` 或现有生产 compose，也保持同样原则：

- 容器内部监听 `0.0.0.0:8000`
- 宿主机只绑定 `127.0.0.1:18000`

## 6. Django 反代相关设置

当外部通过 A 的 HTTPS 访问时，B 上 Django 要信任反向代理头。

你需要确认：

- `ALLOWED_HOSTS` 包含 A 的域名
- `CSRF_TRUSTED_ORIGINS` 包含 `https://agomtradepro.example.com`
- 正确处理 `X-Forwarded-Proto`

典型目标：

```text
ALLOWED_HOSTS=agomtradepro.example.com,127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=https://agomtradepro.example.com
```

## 7. FRPC 配置样例

建议文件：`/opt/frp/frpc.toml`

```toml
serverAddr = "A_PUBLIC_IP_OR_DOMAIN"
serverPort = 7000

auth.method = "token"
auth.token = "CHANGE_ME_STRONG_RANDOM_TOKEN"

[[proxies]]
name = "agomtradepro-web"
type = "http"
localIP = "127.0.0.1"
localPort = 18000
customDomains = ["agomtradepro.example.com"]
```

说明：

- `serverAddr` 填 A 的公网 IP 或域名
- `auth.token` 必须和 A 的 `frps.toml` 一致
- `customDomains` 要和 A 的 `nginx` 域名一致

## 8. FRPC systemd 服务

如果 `frpc` 跑在 WSL2 Ubuntu 里，可以用 `systemd` 管理。

文件：`/etc/systemd/system/frpc.service`

```ini
[Unit]
Description=FRP Client
After=network.target

[Service]
Type=simple
ExecStart=/opt/frp/frpc -c /opt/frp/frpc.toml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable frpc
sudo systemctl start frpc
sudo systemctl status frpc
```

如果你的 WSL2 未启用 systemd，也可以先手动运行：

```bash
/opt/frp/frpc -c /opt/frp/frpc.toml
```

## 9. 本地启动顺序

建议顺序：

1. 启动 Windows
2. 启动 Docker Desktop
3. 进入 WSL2
4. 启动 AgomTradePro 容器
5. 确认 `http://127.0.0.1:18000/api/health/` 正常
6. 启动 `frpc`

## 10. 本地检查命令

应用检查：

```bash
curl http://127.0.0.1:18000/api/health/
docker ps
docker compose ps
```

端口检查：

```bash
ss -lntp | grep 18000
```

FRP 检查：

```bash
systemctl status frpc
journalctl -u frpc -n 100 --no-pager
```

## 11. 常见问题

### 1. C 端访问 A 返回 404 或 502

优先检查 B：

- `127.0.0.1:18000` 是否真的可访问
- `frpc.toml` 里的 `localPort` 是否正确
- Docker 端口是否只绑定到了别的地址

### 2. Docker 在 Windows 磁盘很慢

建议：

- 把代码移到 WSL2 Linux 文件系统
- 不要长期从 Windows 挂载盘路径映射到 WSL2 后运行

### 3. WSL 重启后 `frpc` 不自动拉起

说明：

- 你的 WSL2 可能没启用 `systemd`
- 或 Docker Desktop 先于 WSL 网络未稳定

可以先用脚本顺序启动，稳定后再做自启。

## 12. 推荐最终状态

B 机最终应该保持：

- Docker 只监听 `127.0.0.1:18000`
- `frpc` 主动连 A
- 不暴露任何公网入站端口

这样 B 才是“运行层”，不是“公网入口层”。
