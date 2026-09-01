"""Repository contracts for the bounded M5 Prometheus deployment."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker" / "docker-compose.vps.yml"
PROMETHEUS_PATH = ROOT / "monitoring" / "prometheus.vps.yml"
ALERTS_PATH = ROOT / "monitoring" / "alerts.yml"
CADDY_PATH = ROOT / "docker" / "Caddyfile.template"
ENV_EXAMPLE_PATH = ROOT / "deploy" / "prometheus-query.env.example"
PINNED_IMAGE = (
    "prom/prometheus:v3.5.0@"
    "sha256:63805ebb8d2b3920190daf1cb14a60871b16fd38bed42b857a3182bc621f4996"
)


def _yaml(path: Path) -> dict[str, object]:
    """Load one checked-in YAML mapping."""

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_prometheus_service_is_pinned_bounded_and_not_directly_published() -> None:
    """The VPS service must retain M5 data without exposing Prometheus itself."""

    compose = _yaml(COMPOSE_PATH)
    services = compose["services"]
    assert isinstance(services, dict)
    prometheus = services["prometheus"]
    assert isinstance(prometheus, dict)

    assert prometheus["image"] == f"${{PROMETHEUS_IMAGE:-{PINNED_IMAGE}}}"
    assert "ports" not in prometheus
    assert prometheus["command"] == [
        "--config.file=/etc/prometheus/prometheus.yml",
        "--storage.tsdb.path=/prometheus",
        "--storage.tsdb.retention.time=${PROMETHEUS_RETENTION_TIME:-21d}",
        "--storage.tsdb.retention.size=${PROMETHEUS_RETENTION_SIZE:-4GB}",
    ]
    assert prometheus["volumes"] == [
        "../monitoring/prometheus.vps.yml:/etc/prometheus/prometheus.yml:ro",
        "../monitoring/alerts.yml:/etc/prometheus/alerts.yml:ro",
        "prometheus_data:/prometheus",
    ]
    assert prometheus["depends_on"] == {"web": {"condition": "service_healthy"}}
    assert prometheus["healthcheck"]["test"] == [
        "CMD-SHELL",
        "wget --spider --quiet http://127.0.0.1:9090/-/ready || exit 1",
    ]
    volumes = compose["volumes"]
    assert isinstance(volumes, dict)
    assert "prometheus_data" in volumes


def test_vps_scrape_config_contains_only_the_deployed_django_target() -> None:
    """Unavailable exporters must not be represented as healthy scrape jobs."""

    config = _yaml(PROMETHEUS_PATH)

    assert config["rule_files"] == ["/etc/prometheus/alerts.yml"]
    assert config["scrape_configs"] == [
        {
            "job_name": "agomtradepro",
            "metrics_path": "/metrics/",
            "scheme": "http",
            "static_configs": [{"targets": ["web:8000"]}],
        }
    ]

    alerts = _yaml(ALERTS_PATH)
    groups = alerts["groups"]
    assert isinstance(groups, list)
    rule_names = {
        rule.get("alert")
        for group in groups
        for rule in group.get("rules", [])
        if isinstance(group, dict) and isinstance(rule, dict)
    }
    assert "PrometheusStorageBudgetNearLimit" in rule_names
    assert "DatabaseConnectionPoolExhausted" in rule_names
    assert "DatabaseConnectionObservationUnavailable" in rule_names


def test_database_connection_alerts_use_real_capacity_and_all_django_5xx() -> None:
    """Connection exhaustion and page-level failures must be observable."""

    alerts = _yaml(ALERTS_PATH)
    groups = alerts["groups"]
    assert isinstance(groups, list)
    rules = {
        rule["alert"]: rule
        for group in groups
        if isinstance(group, dict)
        for rule in group.get("rules", [])
        if isinstance(rule, dict) and isinstance(rule.get("alert"), str)
    }

    pool_expression = str(rules["DatabaseConnectionPoolExhausted"]["expr"])
    observation_expression = str(rules["DatabaseConnectionObservationUnavailable"]["expr"])
    http_expression = str(rules["High5xxRate"]["expr"])

    assert "db_connection_capacity" in pool_expression
    assert "db_connections_total" in pool_expression
    assert "> 0.8" in pool_expression
    assert "database_connection_observation_up" in observation_expression
    assert "django_http_responses_total_by_status_total" in http_expression
    assert "0.000001" in http_expression


def test_query_api_uses_tls_origin_auth_and_an_unusable_fallback_credential() -> None:
    """Caddy must expose only bounded read APIs behind basic authentication."""

    caddy = CADDY_PATH.read_text(encoding="utf-8")

    assert "@prometheus_query" in caddy
    assert "/internal/prometheus/api/v1/query_range" in caddy
    assert "/internal/prometheus/-/reload" not in caddy
    assert "basic_auth" in caddy
    assert "{$PROMETHEUS_QUERY_USER:monitoring_disabled}" in caddy
    assert "{$PROMETHEUS_QUERY_PASSWORD_HASH:$2b$14$" in caddy
    assert "uri strip_prefix /internal/prometheus" in caddy
    assert "reverse_proxy prometheus:9090" in caddy

    env_example = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    assert "PROMETHEUS_QUERY_USER=monitoring" in env_example
    assert "PROMETHEUS_QUERY_PASSWORD_HASH=" in env_example


def test_caddy_reads_query_credentials_from_an_optional_host_only_file() -> None:
    """The secret credential file stays outside Git and missing means deny."""

    compose = _yaml(COMPOSE_PATH)
    services = compose["services"]
    assert isinstance(services, dict)
    caddy = services["caddy"]
    assert isinstance(caddy, dict)

    assert caddy["env_file"] == [{"path": "../deploy/prometheus-query.env", "required": False}]
    assert caddy["depends_on"]["prometheus"] == {"condition": "service_healthy"}
