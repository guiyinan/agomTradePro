# AgomSAAF 三机架构方案：VPS FRP 转发 + 本地 Docker 运行 + C 端 AI Agent/MCP

## 1. 目标

你要的运行模式可以落成下面这套结构：

1. A 机（Linux VPS）放在公网，负责暴露统一入口。
2. B 机（Windows + WSL2 + Docker）实际运行 AgomSAAF 系统。
3. C 机（Windows）运行 AI Agent，通过 MCP/SDK/HTTP 调 A 暴露出来的地址，间接操作 B 上的系统。

这套方案的核心价值是：

- 系统算力和数据留在本地 B。
- 公网只暴露 A，不直接暴露 B。
- C 不需要直连 B，只需要访问 A 的公网地址。

## 2. 推荐拓扑

```text
+-------------------+        HTTPS / Token Auth        +-------------------+
| C: Windows        | --------------------------------> | A: Linux VPS      |
| AI Agent / MCP    |                                   | Nginx + frps      |
+-------------------+                                   +---------+---------+
                                                                  |
                                                                  | FRP tunnel
                                                                  v
                                                        +---------+---------+
                                                        | B: Windows + WSL2 |
                                                        | Docker + frpc     |
                                                        | AgomSAAF          |
                                                        +-------------------+
```

推荐流量链路：

1. C 访问 `https://<A的域名或公网IP>/`
2. A 上 `nginx` 负责 TLS/反向代理
3. `nginx` 转到 A 本机 `frps` 暴露的 HTTP 端口
4. `frps` 通过隧道把流量转给 B 上 `frpc`
5. B 上 `frpc` 再转给 Docker 中的 AgomSAAF Web 服务

## 3. 推荐职责分工

### A 机：公网入口层

只做入口和转发，不跑 AgomSAAF 主应用。

建议职责：

- `frps`：接受来自 B 的内网穿透连接
- `nginx`：HTTPS 终止、域名接入、基础访问控制
- `ufw` 或 `iptables`：只开放必要端口
- `fail2ban`：可选，防爆破

### B 机：应用运行层

这里是真正跑业务系统的机器。

建议职责：

- Docker Desktop
- WSL2（Ubuntu）
- Docker Compose
- AgomSAAF Web / Worker / DB 等容器
- `frpc`：把本地 Web 服务注册到 A

### C 机：操作者/Agent 层

只做调用，不承载服务。

建议职责：

- Claude Code / 其他 AI Agent
- Python 3.11+
- AgomSAAF SDK / MCP Server
- 浏览器、Postman、curl 等调试工具

## 4. 每台机器需要安装什么

## 4.1 A 机（Linux VPS）

必装：

- `frp` 服务端：`frps`
- `nginx`
- `systemd`
- `curl`
- `ufw` 或 `iptables`

建议安装：

- `certbot` 或其他证书工具
- `fail2ban`
- `htop`
- `jq`

建议开放端口：

- `22`：SSH
- `80`：HTTP（用于证书签发和跳转）
- `443`：HTTPS
- `7000`：`frps` 控制端口，仅允许 B 的出口 IP 访问更好

不建议直接暴露：

- Django 容器端口
- Docker Remote API
- `frps` dashboard 管理端口

## 4.2 B 机（Windows + WSL2 + Docker）

Windows 侧必装：

- Windows 11 或较新版本 Windows 10
- Docker Desktop
- WSL2
- Git
- Python 3.11+（可选，但建议装，方便本地脚本和 SDK）

WSL2 侧必装：

- Ubuntu
- `docker` / `docker compose`（如果走 Docker Desktop 集成，可直接复用）
- `git`
- `curl`
- `jq`
- `frpc`

仓库与运行环境：

- AgomSAAF 仓库代码
- `.env` 或部署环境变量
- Docker Compose 所需镜像

建议本地服务绑定方式：

- AgomSAAF Web 只监听 `127.0.0.1` 或 Docker 内网
- 不要把业务端口直接映射到公网网卡
- `frpc` 只转发本地反向代理或容器暴露出的内部端口

## 4.3 C 机（Windows）

必装：

- Python 3.11+
- Git
- Claude Code / Claude Desktop / 你的 AI Agent 运行环境

如果要用本仓库 MCP：

- 在 [sdk/README.md](../../sdk/README.md) 的方式安装 SDK
- 使用 [docs/mcp/mcp-deployment.md](../mcp/mcp-deployment.md) 配 MCP

可选工具：

- Postman
- `curl`
- `uv` 或 `pipx`

## 5. 推荐网络与端口设计

推荐统一用 HTTPS，对外只暴露 A 的 `443`。

示例：

```text
A (公网)
- 443   -> nginx
- 80    -> certbot/跳转
- 7000  -> frps bind_port

B (本地)
- 18000 -> 本地 nginx 或 docker 映射出的 AgomSAAF Web
- frpc  -> 主动连 A:7000

Docker
- app container 内部端口: 8000
```

推荐映射关系：

```text
C -> https://agomsaaf.example.com
  -> A/nginx :443
  -> A/frps local vhost_http_port
  -> B/frpc
  -> B/docker app :8000
```

## 6. 推荐的 FRP 组织方式

建议用 `frps + frpc` 的 HTTP/HTTPS 转发模式，不建议一开始用太多复杂插件。

### A 机 `frps`

建议职责：

- 监听控制端口，例如 `7000`
- 暴露 `vhostHTTPPort`，例如 `8080`
- 可选暴露 `vhostHTTPSPort`，但更推荐 HTTPS 在 `nginx` 终止

### B 机 `frpc`

建议映射一个服务：

- 名称：`agomsaaf-web`
- 类型：`http`
- 本地地址：`127.0.0.1`
- 本地端口：`18000` 或你实际映射端口

实践上，B 最稳的做法是：

1. Docker 中 AgomSAAF 暴露到 `127.0.0.1:18000`
2. `frpc` 把 `127.0.0.1:18000` 发布到 A
3. A 上 `nginx` 对外提供域名和 HTTPS

这样职责最清楚，排障也最简单。

## 7. MCP / AI Agent 接入方式

你的 C 机 AI Agent 不需要知道 B 的存在，只需要把 A 当成后端地址。

### 方案 A：C 上跑 MCP，本质上经 A 调后端

这是最推荐的方式。

在 C 上配置：

```json
{
  "mcpServers": {
    "agomsaaf": {
      "command": "python",
      "args": ["-m", "agomsaaf_mcp.server"],
      "cwd": "D:/githv/agomSAAF/sdk",
      "env": {
        "AGOMSAAF_BASE_URL": "https://agomsaaf.example.com",
        "AGOMSAAF_API_TOKEN": "your_token_here"
      }
    }
  }
}
```

说明：

- `AGOMSAAF_BASE_URL` 应该填 A 暴露出去的公网地址
- 不是 B 的局域网地址
- 也不是 Docker 容器地址

### 方案 B：C 上直接用 SDK / REST API

适合脚本、自动化任务、定时任务。

```python
from agomsaaf import AgomSAAFClient

client = AgomSAAFClient(
    base_url="https://agomsaaf.example.com",
    api_token="your_token_here",
)
```

## 8. 建议的访问域名

强烈建议配一个域名，而不是长期直接用公网 IP。

推荐：

- `agomsaaf.example.com` 指向 A

这样有几个好处：

- HTTPS 证书更容易管
- C 机 MCP 配置更稳定
- 后续切换 A 或 B 时，客户端不用改

## 9. 安全建议

这个架构能用，但要注意边界，不然会把本地 B 暴露成公网入口。

必须做的事：

1. A 对外只开放 `80/443/22`，以及 `frps` 控制端口
2. B 不做公网入站映射
3. API 必须启用 Token 认证
4. `nginx` 上限制请求体大小、超时、基础速率
5. Token 不要写死到仓库文档和脚本里
6. `frps` 设置 `token` 或更强认证
7. Django `ALLOWED_HOSTS`、CSRF、反向代理头要正确配置

建议做的事：

1. A 只允许 C 的出口 IP 访问管理类路径
2. 给 `/admin/`、`/account/admin/tokens/` 增加二次限制
3. 日志分层保存：A 的接入日志、B 的应用日志
4. 如果是长期生产，用域名 + HTTPS + WAF/CDN 更稳

## 10. 运维与启动顺序

建议启动顺序：

1. A 启动 `frps`
2. A 启动 `nginx`
3. B 启动 Docker Desktop / WSL2
4. B 启动 AgomSAAF 容器
5. B 启动 `frpc`
6. C 用浏览器或 SDK 验证 `https://<A地址>/api/health/`
7. C 再启动 MCP / Agent

## 11. 故障定位顺序

当 C 调不通时，按这个顺序查：

1. C 能否打开 A 的 `https://域名/api/health/`
2. A 上 `nginx` 是否正常
3. A 上 `frps` 是否在线、是否看到 B 的连接
4. B 上 `frpc` 是否已连接 A
5. B 上 Docker 容器是否健康
6. B 本机 `127.0.0.1:18000` 是否能返回页面/API

## 12. 结论与推荐决策

这套方案可以做，而且适合你当前的目标。

推荐最终定稿为：

1. A 只做 `nginx + frps` 公网入口
2. B 只做 `Docker + AgomSAAF + frpc` 业务运行
3. C 只做 `AI Agent + MCP/SDK` 调用端
4. C 始终访问 A 的域名，不直接碰 B
5. 优先使用 HTTPS 域名，不建议长期裸 IP

如果后面你要继续推进，我建议下一步直接补两份落地文件：

1. `A` 的 `frps.toml` + `nginx` 示例配置
2. `B` 的 `frpc.toml` + Docker 端口映射示例

这样你就可以按机器逐台部署，而不是只停留在概念架构。

## 13. 配套落地文档

已经补充：

1. [vps-a-frps-nginx-setup.md](../deployment/vps-a-frps-nginx-setup.md)
2. [b-local-frpc-docker-setup.md](../deployment/b-local-frpc-docker-setup.md)
