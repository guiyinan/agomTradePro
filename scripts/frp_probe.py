"""Validate the FRP egress templates and run a bounded read-only probe.

The probe is intentionally independent of Django and Docker lifecycle APIs. It
uses a caller-supplied HTTP proxy, performs only GET requests, rejects
redirects, limits response bodies, and never serializes proxy credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import ipaddress
import json
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import urlencode, urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VISITOR_CONFIG = REPO_ROOT / "deploy" / "frp" / "vps-visitor.toml.example"
DEFAULT_MAINLAND_CONFIG = REPO_ROOT / "deploy" / "frp" / "mainland-frpc.toml.example"
DEFAULT_COMPOSE_FILE = REPO_ROOT / "docker" / "docker-compose.vps.frp-egress.yml"
DEFAULT_IP_URL = "https://api.ipify.org?format=json"
DEFAULT_HISTORY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
DEFAULT_SYMBOL = "600000.SH"
DEFAULT_BEGIN = "20250101"
DEFAULT_END = "20251231"
FRPC_IMAGE = "ghcr.io/fatedier/frpc:v0.69.0"
MAX_TIMEOUT_SECONDS = 30.0
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_BODY_BYTES = 512 * 1024
MAX_BODY_BYTES = 2 * 1024 * 1024
TEMPLATE_PATTERN = re.compile(r"{{\s*\.Envs\.([A-Za-z_][A-Za-z0-9_]*)\s*}}")

TomlTable = dict[str, object]
JsonObject = dict[str, object]


class _HttpResponse(Protocol):
    """Subset of ``requests.Response`` consumed by the bounded probe."""

    status_code: int
    headers: Mapping[str, str]
    raw: object

    def close(self) -> None:
        """Release the response connection."""


class _HttpSession(Protocol):
    """Subset of ``requests.Session`` used to force the selected proxy."""

    trust_env: bool
    proxies: MutableMapping[str, str]
    headers: MutableMapping[str, str]

    def get(
        self,
        url: str,
        *,
        timeout: float,
        allow_redirects: bool,
        stream: bool,
    ) -> _HttpResponse:
        """Perform one bounded GET."""


@dataclass(frozen=True)
class ValidationIssue:
    """One deterministic config or topology validation finding."""

    code: str
    location: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class ValidationReport:
    """Validation output for one file and its referenced template variables."""

    role: str
    path: str
    template_variables: tuple[str, ...]
    issues: tuple[ValidationIssue, ...]

    @property
    def ok(self) -> bool:
        """Return whether no error-level issue was found."""

        return not any(issue.severity == "error" for issue in self.issues)


@dataclass(frozen=True)
class _FetchResult:
    """Bounded metadata retained for one HTTP GET."""

    name: str
    url: str
    status: int | None
    content_type: str | None
    body_bytes: int
    body_sha256: str
    transport_error: str | None
    body: bytes


def _build_session(proxy_url: str) -> _HttpSession:
    """Build a requests session that cannot bypass the selected proxy.

    ``trust_env=False`` prevents ambient ``NO_PROXY``/proxy variables from
    changing the route. Explicit per-scheme proxies then make the IP, raw, and
    hfq requests use the same visitor endpoint.
    """

    requests_module = importlib.import_module("requests")
    session = cast(_HttpSession, requests_module.Session())
    session.trust_env = False
    session.proxies.clear()
    session.proxies.update({"http": proxy_url, "https": proxy_url})
    session.headers.update(
        {
            "Accept": "application/json,text/plain;q=0.9,*/*;q=0.1",
            "Accept-Encoding": "identity",
            "User-Agent": "AgomTradePro-frp-readonly-probe/1.0",
        }
    )
    return session


def _request_exception_type() -> type[BaseException]:
    """Resolve requests' transport exception type without a static import."""

    requests_module = importlib.import_module("requests")
    exceptions = requests_module.exceptions
    candidate = exceptions.RequestException
    if isinstance(candidate, type) and issubclass(candidate, BaseException):
        return candidate
    return OSError


def _mapping(value: object) -> Mapping[str, object]:
    """Narrow a dynamic TOML/YAML value to a string-keyed mapping."""

    if isinstance(value, dict):
        return cast(Mapping[str, object], value)
    return {}


def _sequence(value: object) -> Sequence[object]:
    """Narrow a dynamic TOML/YAML value to a sequence."""

    if isinstance(value, list):
        return cast(Sequence[object], value)
    return ()


def _string(value: object) -> str | None:
    """Return a string value, excluding booleans and other scalar types."""

    return value if isinstance(value, str) else None


def _template_variables(text: str) -> tuple[str, ...]:
    """Return unique Go-template environment names in stable order."""

    return tuple(sorted(set(TEMPLATE_PATTERN.findall(text))))


def _matches_env_template(value: object, variable: str) -> bool:
    """Return whether a credential field is exactly one named env template."""

    if not isinstance(value, str):
        return False
    match = TEMPLATE_PATTERN.fullmatch(value)
    return match is not None and match.group(1) == variable


def _source_field_uses_env_template(source: str, field: str, variable: str) -> bool:
    """Return whether a TOML field uses the named env template in source."""

    field_pattern = re.compile(rf"^\s*{re.escape(field)}\s*=\s*(?P<value>[^#]+?)\s*$")
    for line in source.splitlines():
        match = field_pattern.match(line)
        if match is None:
            continue
        value = match.group("value").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        return _matches_env_template(value, variable)
    return False


def _render_template_for_validation(text: str, environment: Mapping[str, str]) -> str:
    """Render known template values without exposing them in diagnostics.

    The two example configs use a numeric template only for ``serverPort``;
    replacing that missing value with ``0`` keeps the document parseable so
    the validator can report the missing variable and invalid port separately.
    String templates are escaped for TOML but never returned to the caller.
    """

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = environment.get(name)
        if name == "FRP_SERVER_PORT":
            return value if value and value.isdigit() else "0"
        if value is None:
            return ""
        return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")

    return TEMPLATE_PATTERN.sub(replace, text)


def _load_toml(path: Path) -> tuple[TomlTable, tuple[str, ...], str | None, str | None]:
    """Load a TOML template and return its variables and parse error code."""

    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return {}, (), "config_read_error", None
    variables = _template_variables(source)
    rendered = _render_template_for_validation(source, os.environ)
    try:
        parsed = tomllib.loads(rendered)
    except tomllib.TOMLDecodeError:
        return {}, variables, "toml_parse_error", source
    return cast(TomlTable, parsed), variables, None, source


def _issue(
    code: str,
    location: str,
    message: str,
    *,
    severity: str = "error",
) -> ValidationIssue:
    """Construct a validation issue with a short non-sensitive message."""

    return ValidationIssue(code=code, location=location, message=message, severity=severity)


def _template_issues(
    variables: Sequence[str],
    environment: Mapping[str, str],
    *,
    role: str,
) -> list[ValidationIssue]:
    """Report required template values that are absent without their values."""

    required = {
        "FRP_SERVER_ADDR",
        "FRP_SERVER_PORT",
        "FRP_STCP_SECRET",
    }
    if role == "mainland":
        required.update({"FRP_HTTP_PROXY_USER", "FRP_HTTP_PROXY_PASSWORD"})
    return [
        _issue(
            "template_env_unset",
            f"template.{name}",
            "required environment value is not set",
            severity="warning",
        )
        for name in variables
        if name in required and not environment.get(name)
    ]


def _common_config_issues(
    config: Mapping[str, object],
    variables: Sequence[str],
    *,
    role: str,
) -> list[ValidationIssue]:
    """Validate settings shared by the visitor and mainland client."""

    issues: list[ValidationIssue] = _template_issues(variables, os.environ, role=role)
    unresolved_templates = {name for name in variables if not os.environ.get(name)}
    server_addr = _string(config.get("serverAddr"))
    if not server_addr and "FRP_SERVER_ADDR" not in unresolved_templates:
        issues.append(_issue("missing_server_addr", "serverAddr", "frps address is required"))
    server_port = config.get("serverPort")
    if (
        type(server_port) is not int or not 1 <= server_port <= 65535
    ) and "FRP_SERVER_PORT" not in unresolved_templates:
        issues.append(_issue("invalid_server_port", "serverPort", "must be between 1 and 65535"))

    auth = _mapping(config.get("auth"))
    if auth.get("method") != "token":
        issues.append(
            _issue("auth_method_not_token", "auth.method", "token authentication is required")
        )
    token_source = _mapping(auth.get("tokenSource"))
    if token_source.get("type") != "file":
        issues.append(
            _issue(
                "token_file_required",
                "auth.tokenSource.type",
                "file token source is required",
            )
        )
    token_file = _mapping(token_source.get("file")).get("path")
    if not isinstance(token_file, str) or not token_file.startswith("/"):
        issues.append(
            _issue(
                "token_file_not_absolute",
                "auth.tokenSource.file.path",
                "token file path must be an absolute host/container path",
            )
        )

    transport = _mapping(config.get("transport"))
    if transport.get("protocol") != "tcp":
        issues.append(
            _issue("transport_not_tcp", "transport.protocol", "STCP requires TCP transport")
        )
    tls = _mapping(transport.get("tls"))
    if tls.get("enable") is not True:
        issues.append(
            _issue("transport_tls_disabled", "transport.tls.enable", "TLS must stay enabled")
        )
    if "proxyURL" in transport:
        issues.append(
            _issue(
                "transport_proxy_misuse",
                "transport.proxyURL",
                "transport.proxyURL only proxies the frpc-to-frps control connection",
            )
        )
    return issues


def _secret_safety_issues(
    config: Mapping[str, object],
    template_variables: Sequence[str],
    source: str,
) -> list[ValidationIssue]:
    """Reject literal credentials while allowing Go environment templates."""

    issues: list[ValidationIssue] = []

    def walk(value: object, location: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_location = f"{location}.{key}" if location else str(key)
                if key == "token":
                    issues.append(
                        _issue(
                            "inline_auth_token",
                            child_location,
                            "credential must be read from a file",
                        )
                    )
                elif key in {"secretKey", "httpPassword", "password", "clientSecret"}:
                    template_name = {
                        "secretKey": "FRP_STCP_SECRET",
                        "httpPassword": "FRP_HTTP_PROXY_PASSWORD",
                    }.get(key)
                    rendered_from_template = (
                        template_name in template_variables
                        and _source_field_uses_env_template(source, str(key), template_name)
                        if template_name
                        else isinstance(child, str)
                        and TEMPLATE_PATTERN.fullmatch(child) is not None
                    )
                    if not rendered_from_template:
                        issues.append(
                            _issue(
                                "literal_secret",
                                child_location,
                                "secret must use an environment template",
                            )
                        )
                walk(child, child_location)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{location}[{index}]")

    walk(config, "")
    return issues


def _validate_toml_config(path: Path, *, role: str) -> ValidationReport:
    """Validate one visitor or mainland frpc TOML template."""

    config, variables, parse_error, source = _load_toml(path)
    issues: list[ValidationIssue] = []
    if parse_error is not None:
        issues.append(_issue(parse_error, str(path), "unable to parse TOML template"))
        return ValidationReport(role, str(path), variables, tuple(issues))
    if source is None:
        issues.append(_issue("config_read_error", str(path), "unable to read config template"))
        return ValidationReport(role, str(path), variables, tuple(issues))

    issues.extend(_common_config_issues(config, variables, role=role))
    issues.extend(_secret_safety_issues(config, variables, source))
    if role == "visitor":
        visitors = _sequence(config.get("visitors"))
        proxies = _sequence(config.get("proxies"))
        if len(visitors) != 1:
            issues.append(
                _issue("visitor_count", "visitors", "exactly one STCP visitor is required")
            )
        if proxies:
            issues.append(
                _issue("visitor_has_proxies", "proxies", "visitor config must not define proxies")
            )
        if visitors:
            visitor = _mapping(visitors[0])
            if visitor.get("name") != "egress_http_proxy_visitor":
                issues.append(_issue("visitor_name", "visitors[0].name", "unexpected visitor name"))
            if visitor.get("type") != "stcp":
                issues.append(
                    _issue("visitor_type", "visitors[0].type", "visitor type must be stcp")
                )
            if visitor.get("serverName") != "egress_http_proxy":
                issues.append(
                    _issue(
                        "visitor_server_name",
                        "visitors[0].serverName",
                        "unexpected STCP proxy name",
                    )
                )
            if visitor.get("enabled") is not True:
                issues.append(
                    _issue(
                        "visitor_disabled",
                        "visitors[0].enabled",
                        "profile config must enable visitor",
                    )
                )
            if visitor.get("bindAddr") != "0.0.0.0":
                issues.append(
                    _issue(
                        "visitor_bind_not_private_network",
                        "visitors[0].bindAddr",
                        "visitor must bind 0.0.0.0 inside the private Docker network",
                    )
                )
            if visitor.get("bindPort") != 18080:
                issues.append(
                    _issue(
                        "visitor_bind_port", "visitors[0].bindPort", "visitor port must be 18080"
                    )
                )
            if not _source_field_uses_env_template(source, "secretKey", "FRP_STCP_SECRET"):
                issues.append(
                    _issue(
                        "visitor_secret_template",
                        "visitors[0].secretKey",
                        "use FRP_STCP_SECRET template",
                    )
                )
    elif role == "mainland":
        proxies = _sequence(config.get("proxies"))
        visitors = _sequence(config.get("visitors"))
        if len(proxies) != 1:
            issues.append(
                _issue("proxy_count", "proxies", "exactly one mainland STCP proxy is required")
            )
        if visitors:
            issues.append(
                _issue(
                    "mainland_has_visitors", "visitors", "mainland config must not define visitors"
                )
            )
        if proxies:
            proxy = _mapping(proxies[0])
            if proxy.get("name") != "egress_http_proxy":
                issues.append(_issue("proxy_name", "proxies[0].name", "unexpected proxy name"))
            if proxy.get("type") != "stcp":
                issues.append(_issue("proxy_type", "proxies[0].type", "proxy type must be stcp"))
            if "remotePort" in proxy:
                issues.append(
                    _issue(
                        "stcp_remote_port",
                        "proxies[0].remotePort",
                        "STCP must not publish a remote port",
                    )
                )
            if "localIP" in proxy or "localPort" in proxy:
                issues.append(
                    _issue(
                        "stcp_local_endpoint",
                        "proxies[0]",
                        "plugin proxy must not use a local endpoint",
                    )
                )
            if not _source_field_uses_env_template(source, "secretKey", "FRP_STCP_SECRET"):
                issues.append(
                    _issue(
                        "proxy_secret_template",
                        "proxies[0].secretKey",
                        "use FRP_STCP_SECRET template",
                    )
                )
            plugin = _mapping(proxy.get("plugin"))
            if plugin.get("type") != "http_proxy":
                issues.append(
                    _issue(
                        "plugin_type",
                        "proxies[0].plugin.type",
                        "mainland plugin must be http_proxy",
                    )
                )
            for field in ("httpUser", "httpPassword"):
                if field in plugin:
                    template_name = (
                        f"FRP_HTTP_PROXY_{'USER' if field == 'httpUser' else 'PASSWORD'}"
                    )
                    if not _source_field_uses_env_template(source, field, template_name):
                        issues.append(
                            _issue(
                                "plugin_credential_template",
                                f"proxies[0].plugin.{field}",
                                "use an environment template",
                            )
                        )
    else:
        issues.append(_issue("unknown_config_role", "role", "role must be visitor or mainland"))
    return ValidationReport(role, str(path), variables, tuple(issues))


def _load_compose(path: Path) -> tuple[Mapping[str, object], str | None]:
    """Load compose YAML using PyYAML or Docker's read-only config renderer."""

    try:
        import yaml

        source = path.read_text(encoding="utf-8")
        value = yaml.safe_load(source)
        if isinstance(value, dict):
            return cast(Mapping[str, object], value), None
        return {}, "compose_root_not_mapping"
    except ModuleNotFoundError:
        command = [
            "docker",
            "compose",
            "-f",
            str(path),
            "config",
            "--format",
            "json",
            "--no-interpolate",
        ]
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=15)
            value = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return {}, "compose_parser_unavailable"
        if isinstance(value, dict):
            return cast(Mapping[str, object], value), None
        return {}, "compose_root_not_mapping"
    except (OSError, ValueError):
        return {}, "compose_read_error"


def _network_names(value: object) -> set[str]:
    """Return network names from either list or mapping compose syntax."""

    if isinstance(value, list):
        return {str(item) for item in value if isinstance(item, str)}
    if isinstance(value, dict):
        return {str(key) for key in value}
    return set()


def _contains_string(value: object, expected: str) -> bool:
    """Check a shallow compose string/list field without coercing secrets."""

    if isinstance(value, str):
        return value == expected or expected in value
    if isinstance(value, list):
        return any(_contains_string(item, expected) for item in value)
    return False


def _validate_compose(path: Path) -> ValidationReport:
    """Validate the opt-in visitor topology without starting Docker."""

    model, load_error = _load_compose(path)
    issues: list[ValidationIssue] = []
    if load_error is not None:
        issues.append(_issue(load_error, str(path), "unable to read compose topology"))
        return ValidationReport("compose", str(path), (), tuple(issues))
    services = _mapping(model.get("services"))
    visitor = _mapping(services.get("frpc_egress_visitor"))
    if not visitor:
        issues.append(
            _issue(
                "visitor_service_missing",
                "services.frpc_egress_visitor",
                "visitor service is required",
            )
        )
    profiles = _sequence(visitor.get("profiles"))
    if "frp-egress" not in profiles:
        issues.append(
            _issue(
                "profile_missing",
                "services.frpc_egress_visitor.profiles",
                "visitor must require frp-egress profile",
            )
        )
    if visitor.get("image") != FRPC_IMAGE:
        issues.append(
            _issue(
                "image_not_pinned",
                "services.frpc_egress_visitor.image",
                "official frpc image must be pinned to v0.69.0",
            )
        )
    visitor_environment = _mapping(visitor.get("environment"))
    for variable in ("FRP_SERVER_ADDR", "FRP_SERVER_PORT", "FRP_STCP_SECRET"):
        value = visitor_environment.get(variable)
        if not isinstance(value, str) or f"${{{variable}:?" not in value:
            issues.append(
                _issue(
                    "required_env_placeholder",
                    f"services.frpc_egress_visitor.environment.{variable}",
                    "profile connection values must use required Compose placeholders",
                )
            )
    if "ports" in visitor:
        issues.append(
            _issue(
                "public_port_published",
                "services.frpc_egress_visitor.ports",
                "visitor must not publish a host port",
            )
        )
    if "18080" not in {str(item) for item in _sequence(visitor.get("expose"))}:
        issues.append(
            _issue(
                "visitor_expose_missing",
                "services.frpc_egress_visitor.expose",
                "private visitor port 18080 must be exposed",
            )
        )
    if visitor.get("read_only") is not True:
        issues.append(
            _issue(
                "visitor_not_read_only",
                "services.frpc_egress_visitor.read_only",
                "visitor filesystem must be read-only",
            )
        )
    if "ALL" not in {str(item) for item in _sequence(visitor.get("cap_drop"))}:
        issues.append(
            _issue(
                "visitor_capabilities",
                "services.frpc_egress_visitor.cap_drop",
                "drop all Linux capabilities",
            )
        )
    if not _contains_string(visitor.get("command"), "/etc/frp/frpc.toml"):
        issues.append(
            _issue(
                "visitor_config_mount",
                "services.frpc_egress_visitor.command",
                "command must use mounted frpc.toml",
            )
        )
    if "docker.sock" in json.dumps(visitor, ensure_ascii=True):
        issues.append(
            _issue(
                "docker_socket_mounted",
                "services.frpc_egress_visitor",
                "Docker socket must not be mounted",
            )
        )

    visitor_networks = _network_names(visitor.get("networks"))
    if not {"frp_egress_private", "frp_egress_outbound"}.issubset(visitor_networks):
        issues.append(
            _issue(
                "visitor_networks",
                "services.frpc_egress_visitor.networks",
                "private and outbound networks are both required",
            )
        )
    for service_name in ("web", "celery_worker", "terminal_agent_worker", "celery_beat"):
        service = _mapping(services.get(service_name))
        if "frp_egress_private" not in _network_names(service.get("networks")):
            issues.append(
                _issue(
                    "app_network_missing",
                    f"services.{service_name}.networks",
                    "application service must reach private visitor network",
                )
            )
        region = _mapping(service.get("environment")).get("DATA_CENTER_DEPLOYMENT_REGION")
        if not isinstance(region, str) or "DATA_CENTER_DEPLOYMENT_REGION" not in region:
            issues.append(
                _issue(
                    "deployment_region_missing",
                    f"services.{service_name}.environment.DATA_CENTER_DEPLOYMENT_REGION",
                    "application service must carry the deployment region label",
                )
            )

    networks = _mapping(model.get("networks"))
    private_network = _mapping(networks.get("frp_egress_private"))
    outbound_network = _mapping(networks.get("frp_egress_outbound"))
    if private_network.get("internal") is not True:
        issues.append(
            _issue(
                "private_network_not_internal",
                "networks.frp_egress_private.internal",
                "private network must be internal",
            )
        )
    if outbound_network.get("internal") is True:
        issues.append(
            _issue(
                "outbound_network_internal",
                "networks.frp_egress_outbound.internal",
                "outbound network must permit frps access",
            )
        )
    secrets = _mapping(model.get("secrets"))
    if "frp_auth_token" not in secrets:
        issues.append(
            _issue(
                "auth_secret_missing",
                "secrets.frp_auth_token",
                "auth token must be a compose secret",
            )
        )
    return ValidationReport("compose", str(path), (), tuple(issues))


def validate_templates(
    *,
    visitor_config: Path = DEFAULT_VISITOR_CONFIG,
    mainland_config: Path = DEFAULT_MAINLAND_CONFIG,
    compose_file: Path = DEFAULT_COMPOSE_FILE,
) -> tuple[ValidationReport, ...]:
    """Validate all tracked FRP templates without running Docker."""

    return (
        _validate_toml_config(visitor_config, role="visitor"),
        _validate_toml_config(mainland_config, role="mainland"),
        _validate_compose(compose_file),
    )


def _redacted_url(url: str) -> str:
    """Return URL origin/path metadata with credentials and query removed."""

    parsed = urlsplit(url)
    host = parsed.hostname or ""
    port = ""
    try:
        if parsed.port is not None:
            port = f":{parsed.port}"
    except ValueError:
        port = ""
    return urlunsplit((parsed.scheme, f"{host}{port}", parsed.path or "/", "", ""))


def _proxy_metadata(proxy_url: str) -> JsonObject:
    """Describe a configured proxy without returning its URL or credentials."""

    parsed = urlsplit(proxy_url)
    host = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        port = None
    return {
        "configured": bool(host),
        "scheme": parsed.scheme,
        "host": host,
        "port": port,
        "credentials_redacted": bool(parsed.username or parsed.password),
    }


def _validate_proxy_url(proxy_url: str) -> str | None:
    """Return a stable validation error for a proxy URL, if any."""

    parsed = urlsplit(proxy_url)
    if parsed.scheme not in {"http", "https"}:
        return "proxy_scheme_unsupported"
    if not parsed.hostname:
        return "proxy_host_missing"
    if parsed.fragment or parsed.query:
        return "proxy_query_or_fragment_forbidden"
    try:
        if parsed.port is None or not 1 <= parsed.port <= 65535:
            return "proxy_port_invalid"
    except ValueError:
        return "proxy_port_invalid"
    return None


def _validate_target_url(
    url: str, *, allow_http: bool, allow_custom_host: bool, label: str
) -> str | None:
    """Validate a GET target and constrain defaults to known provider hosts."""

    parsed = urlsplit(url)
    if parsed.scheme != "https" and not (allow_http and parsed.scheme == "http"):
        return f"{label}_https_required"
    if not parsed.hostname:
        return f"{label}_host_missing"
    if parsed.username or parsed.password:
        return f"{label}_credentials_forbidden"
    try:
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return f"{label}_port_invalid"
    except ValueError:
        return f"{label}_port_invalid"
    if not allow_custom_host:
        allowed = {"api.ipify.org", "push2his.eastmoney.com"}
        if parsed.hostname.lower() not in allowed:
            return f"{label}_host_not_allowlisted"
    return None


def _limited_read(response: object, max_body_bytes: int) -> bytes:
    """Read at most the configured body limit from an HTTP response."""

    read = getattr(response, "read", None)
    if not callable(read):
        return b""
    body = read(max_body_bytes + 1)
    if not isinstance(body, bytes):
        return b""
    if len(body) > max_body_bytes:
        raise ValueError("response_body_limit_exceeded")
    return body


def _fetch(
    session: _HttpSession,
    *,
    name: str,
    url: str,
    timeout_seconds: float,
    max_body_bytes: int,
) -> _FetchResult:
    """Perform one GET and retain only bounded metadata plus body for parsing."""

    status: int | None = None
    content_type: str | None = None
    body = b""
    transport_error: str | None = None
    request_exception = _request_exception_type()
    try:
        response = session.get(
            url,
            timeout=timeout_seconds,
            allow_redirects=False,
            stream=True,
        )
        try:
            status = int(response.status_code)
            content_type = response.headers.get("Content-Type")
            body = _limited_read(response.raw, max_body_bytes)
        except ValueError:
            transport_error = "response_body_limit_exceeded"
        finally:
            response.close()
    except (OSError, TimeoutError, ValueError) as exc:
        transport_error = (
            str(exc) if str(exc) == "response_body_limit_exceeded" else type(exc).__name__
        )
    except request_exception:
        transport_error = request_exception.__name__
    return _FetchResult(
        name=name,
        url=_redacted_url(url),
        status=status,
        content_type=content_type,
        body_bytes=len(body),
        body_sha256=hashlib.sha256(body).hexdigest(),
        transport_error=transport_error,
        body=body,
    )


def _fetch_json_metadata(result: _FetchResult) -> JsonObject:
    """Serialize a response without copying its raw body."""

    return {
        "name": result.name,
        "url": result.url,
        "status": result.status,
        "content_type": result.content_type,
        "body_bytes": result.body_bytes,
        "body_sha256": result.body_sha256,
        "transport_error": result.transport_error,
    }


def _extract_ip(result: _FetchResult) -> str | None:
    """Extract and validate one public IP address from an ipify response."""

    if result.status != 200 or result.transport_error is not None:
        return None
    text = result.body.decode("utf-8", errors="replace").strip()
    value: object = text
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        value = parsed.get("ip")
    if not isinstance(value, str):
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def _history_metadata(result: _FetchResult) -> JsonObject:
    """Verify a bounded Eastmoney response contains K-line rows."""

    output = _fetch_json_metadata(result)
    if result.status != 200 or result.transport_error is not None:
        output["row_count"] = 0
        output["parse_error"] = "http_request_failed"
        return output
    try:
        parsed = json.loads(result.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        output["row_count"] = 0
        output["parse_error"] = "json_invalid"
        return output
    data = _mapping(parsed).get("data")
    rows = _sequence(_mapping(data).get("klines"))
    valid_rows = [row for row in rows if isinstance(row, str) and row]
    output["row_count"] = len(valid_rows)
    output["parse_error"] = None if valid_rows else "kline_rows_missing"
    if valid_rows:
        output["first_asof"] = valid_rows[0].split(",", 1)[0]
        output["last_asof"] = valid_rows[-1].split(",", 1)[0]
    else:
        output["first_asof"] = None
        output["last_asof"] = None
    return output


def _eastmoney_url(symbol: str, *, fqt: int, begin: str, end: str) -> str:
    """Build one bounded Eastmoney raw or hfq history GET."""

    raw = symbol.upper().replace("-", ".")
    if "." in raw:
        code, exchange = raw.split(".", 1)
    else:
        code, exchange = raw, "SH" if raw.startswith(("5", "6", "9")) else "SZ"
    market = "1" if exchange in {"SH", "SSE", "XSHG"} else "0"
    query = {
        "secid": f"{market}.{code}",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": str(fqt),
        "beg": begin,
        "end": end,
    }
    return f"{DEFAULT_HISTORY_URL}?{urlencode(query)}"


def blocked_external_report(reason: str, *, required_env: str | None = None) -> JsonObject:
    """Create a stable no-network report for unavailable external prerequisites."""

    report: JsonObject = {
        "schema_version": "frp-readonly-probe.v1",
        "collection_mode": "read_only",
        "probe_status": "blocked_external",
        "blocked_reason": reason,
        "side_effects": {
            "http_methods": ["GET"],
            "redirects_followed": False,
            "writes": False,
            "container_mutations": False,
            "credentials_exposed": False,
        },
    }
    if required_env is not None:
        report["required_env"] = required_env
    return report


def run_read_only_probe(
    proxy_url: str,
    *,
    ip_url: str = DEFAULT_IP_URL,
    raw_url: str | None = None,
    hfq_url: str | None = None,
    symbol: str = DEFAULT_SYMBOL,
    begin: str = DEFAULT_BEGIN,
    end: str = DEFAULT_END,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    allow_http: bool = False,
    allow_custom_host: bool = False,
    session_factory: Callable[[str], _HttpSession] | None = None,
) -> JsonObject:
    """Probe actual proxy egress IP and raw/hfq history using bounded GETs."""

    proxy_error = _validate_proxy_url(proxy_url)
    if proxy_error is not None:
        return blocked_external_report(proxy_error)
    timeout = min(max(float(timeout_seconds), 1.0), MAX_TIMEOUT_SECONDS)
    body_limit = min(max(int(max_body_bytes), 1024), MAX_BODY_BYTES)
    raw_target = raw_url or _eastmoney_url(symbol, fqt=0, begin=begin, end=end)
    hfq_target = hfq_url or _eastmoney_url(symbol, fqt=2, begin=begin, end=end)
    for label, target in (("ip", ip_url), ("raw", raw_target), ("hfq", hfq_target)):
        target_error = _validate_target_url(
            target,
            allow_http=allow_http,
            allow_custom_host=allow_custom_host,
            label=label,
        )
        if target_error is not None:
            return blocked_external_report(target_error)
    try:
        session = (
            session_factory(proxy_url) if session_factory is not None else _build_session(proxy_url)
        )
    except (ImportError, AttributeError):
        return blocked_external_report("requests_unavailable")
    ip_result = _fetch(
        session, name="outbound_ip", url=ip_url, timeout_seconds=timeout, max_body_bytes=body_limit
    )
    raw_result = _fetch(
        session,
        name="raw_history",
        url=raw_target,
        timeout_seconds=timeout,
        max_body_bytes=body_limit,
    )
    hfq_result = _fetch(
        session,
        name="hfq_history",
        url=hfq_target,
        timeout_seconds=timeout,
        max_body_bytes=body_limit,
    )
    ip_value = _extract_ip(ip_result)
    raw_metadata = _history_metadata(raw_result)
    hfq_metadata = _history_metadata(hfq_result)
    successful = (
        ip_value is not None
        and raw_metadata.get("parse_error") is None
        and hfq_metadata.get("parse_error") is None
    )
    transport_successes = sum(
        result.status == 200 and result.transport_error is None
        for result in (ip_result, raw_result, hfq_result)
    )
    return {
        "schema_version": "frp-readonly-probe.v1",
        "collection_mode": "read_only",
        "probe_status": (
            "success" if successful else ("partial" if transport_successes else "failed")
        ),
        "proxy": _proxy_metadata(proxy_url),
        "outbound_ip": ip_value,
        "requests": [
            _fetch_json_metadata(ip_result),
            raw_metadata,
            hfq_metadata,
        ],
        "side_effects": {
            "http_methods": ["GET"],
            "redirects_followed": False,
            "writes": False,
            "container_mutations": False,
            "credentials_exposed": False,
        },
    }


def _validation_json(report: ValidationReport) -> JsonObject:
    """Serialize validation output while retaining no source or secret value."""

    return {
        "role": report.role,
        "path": report.path,
        "ok": report.ok,
        "template_variables": list(report.template_variables),
        "issues": [asdict(issue) for issue in report.issues],
    }


def _print_json(payload: object) -> None:
    """Print stable machine-readable output."""

    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for validate and probe modes."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate FRP TOML and compose topology")
    validate.add_argument("--visitor-config", type=Path, default=DEFAULT_VISITOR_CONFIG)
    validate.add_argument("--mainland-config", type=Path, default=DEFAULT_MAINLAND_CONFIG)
    validate.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    validate.add_argument("--json", action="store_true", help="emit JSON")

    probe = subparsers.add_parser("probe", help="run bounded read-only proxy egress checks")
    probe.add_argument("--proxy-url-env", default="FRP_EGRESS_PROXY_URL")
    probe.add_argument(
        "--proxy-url",
        help="discouraged: prefer --proxy-url-env to keep credentials out of process arguments",
    )
    probe.add_argument("--ip-url", default=DEFAULT_IP_URL)
    probe.add_argument("--raw-url")
    probe.add_argument("--hfq-url")
    probe.add_argument("--symbol", default=DEFAULT_SYMBOL)
    probe.add_argument("--begin", default=DEFAULT_BEGIN)
    probe.add_argument("--end", default=DEFAULT_END)
    probe.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    probe.add_argument("--max-body-bytes", type=int, default=DEFAULT_MAX_BODY_BYTES)
    probe.add_argument("--allow-http", action="store_true")
    probe.add_argument("--allow-custom-host", action="store_true")
    probe.add_argument("--json", action="store_true", help="emit JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one validation or read-only probe command."""

    args = _build_parser().parse_args(argv)
    if args.command == "validate":
        reports = validate_templates(
            visitor_config=args.visitor_config,
            mainland_config=args.mainland_config,
            compose_file=args.compose_file,
        )
        validation_payload: JsonObject = {
            "schema_version": "frp-template-validation.v1",
            "status": (
                "invalid_config"
                if not all(report.ok for report in reports)
                else (
                    "blocked_external"
                    if any(
                        issue.code == "template_env_unset"
                        for report in reports
                        for issue in report.issues
                    )
                    else "ready"
                )
            ),
            "reports": [_validation_json(report) for report in reports],
        }
        if validation_payload["status"] == "blocked_external":
            validation_payload["blocked_reason"] = "template_environment_unset"
            validation_payload["required_env"] = sorted(
                {
                    issue.location.removeprefix("template.")
                    for report in reports
                    for issue in report.issues
                    if issue.code == "template_env_unset"
                }
            )
        if args.json:
            _print_json(validation_payload)
        else:
            print(f"status={validation_payload['status']}")
            for report in reports:
                print(f"{report.role}: {'ok' if report.ok else 'failed'} ({report.path})")
                for issue in report.issues:
                    print(f"  {issue.severity}: {issue.code} at {issue.location}")
        return (
            0
            if validation_payload["status"] == "ready"
            else 2 if validation_payload["status"] == "blocked_external" else 1
        )

    proxy_url = args.proxy_url or os.environ.get(args.proxy_url_env, "")
    payload: JsonObject
    if not proxy_url:
        payload = blocked_external_report("missing_proxy_url", required_env=args.proxy_url_env)
    else:
        payload = run_read_only_probe(
            proxy_url,
            ip_url=args.ip_url,
            raw_url=args.raw_url,
            hfq_url=args.hfq_url,
            symbol=args.symbol,
            begin=args.begin,
            end=args.end,
            timeout_seconds=args.timeout,
            max_body_bytes=args.max_body_bytes,
            allow_http=args.allow_http,
            allow_custom_host=args.allow_custom_host,
        )
    if args.json:
        _print_json(payload)
    else:
        print(f"status={payload.get('probe_status')}")
        if payload.get("blocked_reason"):
            print(f"blocked_reason={payload['blocked_reason']}")
        elif payload.get("outbound_ip"):
            print(f"outbound_ip={payload['outbound_ip']}")
        for item in _sequence(payload.get("requests")):
            response = _mapping(item)
            print(
                f"{response.get('name')}: status={response.get('status')} bytes={response.get('body_bytes')}"
            )
    return (
        0
        if payload.get("probe_status") == "success"
        else 2 if payload.get("probe_status") == "blocked_external" else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
