# FRP regional egress templates

These files implement the bounded deployment side of the regional egress
plan. They do not start a container, modify a VPS, or configure the Django
application.

The pinned client image is the official `ghcr.io/fatedier/frpc:v0.69.0` image.
The version is deliberately fixed; before enabling the profile, record the
existing `frps` version and run the read-only checks below. The current
environment has only confirmed that a mainland `frps` exists; its address,
version, authentication, and permission to create the `egress_http_proxy`
proxy remain operator supplied.

## Topology

```text
web / celery_worker -> http://frpc_egress_visitor:18080
                              |
                    STCP visitor over frps
                              |
         mainland frpc -> http_proxy plugin -> provider
```

`docker/docker-compose.vps.frp-egress.yml` adds `frp_egress_private` (marked
`internal`) for the web/worker-to-visitor path and a separate outbound bridge
for the visitor's connection to `frps`. The visitor has no `ports` mapping and
there is no public proxy port. The service is under the opt-in
`frp-egress` profile, so the normal VPS compose invocation leaves it stopped.
The main application route must remain disabled until a reviewed egress rule
is enabled in the application configuration.

The normal VPS invocation uses `docker/docker-compose.vps.yml` alone. Loading
this override is an explicit FRP configuration action and therefore requires
`FRP_SERVER_ADDR`, `FRP_SERVER_PORT`, and `FRP_STCP_SECRET` even when the
profile is not started; the profile controls sidecar startup, while Compose
still parses the override.

The override also sets `DATA_CENTER_DEPLOYMENT_REGION` on web, worker, beat,
and terminal-agent services. Set it to the operator's stable node label (the
default is `overseas_vps`) when evaluating the `equity.price.bar` runtime
configuration. This label records routing context; it does not enable the
egress route by itself.

## Configure without storing credentials in Git

On the VPS, copy `vps-visitor.toml.example` to a host-only path and set these
values in the deployment environment or secret manager:

```text
FRP_SERVER_ADDR=<existing-frps-address>
FRP_SERVER_PORT=<existing-frps-bind-port>
FRP_STCP_SECRET=<dedicated-stcp-secret>
FRP_AUTH_TOKEN_FILE=<0400-file-with-frps-auth-token>
FRP_VISITOR_CONFIG_FILE=<host-only-copy-of-vps-visitor.toml>
DATA_CENTER_DEPLOYMENT_REGION=overseas_vps
```

After the config has been reviewed, recreate the application services together
with the visitor so their private-network attachments are present:

```bash
docker compose -f docker/docker-compose.vps.yml \
  -f docker/docker-compose.vps.frp-egress.yml \
  --profile frp-egress up -d web celery_worker terminal_agent_worker \
  celery_beat frpc_egress_visitor
```

The mainland host uses `mainland-frpc.toml.example` and supplies
`FRP_SERVER_ADDR`, `FRP_SERVER_PORT`, `FRP_STCP_SECRET`, `FRP_HTTP_PROXY_USER`,
`FRP_HTTP_PROXY_PASSWORD`, and the same `FRP_AUTH_TOKEN_FILE` through its
host-only environment/secret manager. Remove the `httpUser` and
`httpPassword` lines when the upstream proxy intentionally has no
credentials. The STCP proxy uses frp's default same-user restriction; keep
that default unless the frps user policy is explicitly reviewed.

Run config/topology validation before starting anything:

```bash
python scripts/frp_probe.py validate \
  --visitor-config deploy/frp/vps-visitor.toml.example \
  --mainland-config deploy/frp/mainland-frpc.toml.example \
  --compose-file docker/docker-compose.vps.frp-egress.yml
```

The command reports template references without printing their values. For a
complete configuration, every required FRP value must be present. If the
example templates still have unset environment references, validation returns
`blocked_external` with exit code 2; malformed TOML/topology returns
`invalid_config` with exit code 1. For a running visitor, the read-only probe
gets its proxy URL from an environment
variable so credentials do not appear in shell history:

```bash
FRP_EGRESS_PROXY_URL=http://frpc_egress_visitor:18080 \
python scripts/frp_probe.py probe --json
```

The probe performs at most one GET to the configured public-IP endpoint and
one GET for each of raw and hfq Eastmoney history. It rejects redirects,
limits response bytes, verifies that the IP is a valid address, and reports
row counts and body hashes without copying response bodies or proxy
credentials into the result. Missing proxy settings, invalid external
prerequisites, or unreachable dependencies produce `blocked_external` with a
stable reason and exit code 2. A successful probe is evidence only for the
tested host, symbol, and time window; it does not enable an application route.

The probe uses the same HTTP proxy URL for raw and hfq requests. It does not
fall back to direct egress, mutate environment variables, restart containers,
or call any write endpoint.

`docker compose ps` only shows whether the frpc process is running. Treat the
read-only probe as the operational check: it must report the actual outbound
IP and successful raw/hfq responses before a reviewed route is enabled.

The FRP configuration follows the official [environment template and
verification guidance](https://gofrp.org/en/docs/features/common/configure/),
[STCP visitor example](https://gofrp.org/en/docs/examples/stcp/), and
[HTTP proxy plugin reference](https://gofrp.org/en/docs/reference/client-plugin/).
The official image's `/usr/bin/frpc` entrypoint is why the compose command
contains only `-c /etc/frp/frpc.toml`.
