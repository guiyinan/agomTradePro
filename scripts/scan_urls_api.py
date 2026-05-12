#!/usr/bin/env python
"""
Scan Django-resolved URLs and API endpoints, then probe them with GET.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

import django
import requests
from django.urls import URLPattern, URLResolver, get_resolver

# Ensure project root is importable when executing from scripts/.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class ProbeResult:
    path: str
    status: int
    ok: bool
    category: str
    elapsed_ms: int
    dynamic: bool
    error: str = ""


@dataclass(frozen=True)
class RouteItem:
    path: str
    dynamic: bool


CONVERTER_REPLACEMENTS = [
    (re.compile(r"<int:[^>]+>"), "1"),
    (re.compile(r"<slug:[^>]+>"), "sample-slug"),
    (re.compile(r"<uuid:[^>]+>"), "123e4567-e89b-12d3-a456-426614174000"),
    (re.compile(r"<path:[^>]+>"), "sample/path"),
    (re.compile(r"<str:[^>]+>"), "sample"),
    (re.compile(r"<[^>:]+>"), "sample"),
]


def normalize_route(route: str) -> str:
    value = route.strip()
    value = value.replace("^", "").replace("$", "").replace("\\Z", "")
    for pattern, replacement in CONVERTER_REPLACEMENTS:
        value = pattern.sub(replacement, value)
    value = value.replace("//", "/")
    value = value.lstrip("/")
    return value


def collect_paths(patterns: Iterable, prefix: str = "", dynamic_prefix: bool = False) -> set[RouteItem]:
    paths: set[RouteItem] = set()
    for entry in patterns:
        raw = getattr(entry.pattern, "_route", str(entry.pattern))
        route = normalize_route(raw)
        dynamic_here = dynamic_prefix or ("<" in raw) or ("(?P<" in raw)
        current_prefix = "/".join([part for part in [prefix, route] if part]).strip("/")

        if isinstance(entry, URLResolver):
            paths.update(collect_paths(entry.url_patterns, current_prefix, dynamic_here))
            continue

        if isinstance(entry, URLPattern):
            candidate = "/" + current_prefix if current_prefix else "/"
            candidate = candidate.replace("//", "/")
            if "drf_format_suffix" in candidate:
                continue
            if any(token in candidate for token in ["(?P<", "\\d", "[", "]", "("]):
                continue
            if candidate.startswith("/admin/jsi18n/"):
                continue
            paths.add(RouteItem(path=candidate, dynamic=dynamic_here))
    return paths


def classify_status(status: int, dynamic: bool) -> str:
    if 200 <= status < 300:
        return "ok"
    if status in (301, 302, 303, 307, 308):
        return "redirect"
    if status == 400:
        return "bad_request"
    if status in (401, 403):
        return "auth"
    if status == 404:
        return "not_found_dynamic" if dynamic else "not_found"
    if status == 405:
        return "method_not_allowed"
    if status >= 500:
        return "server_error"
    return "other"


def probe(base_url: str, route: RouteItem, timeout: int) -> ProbeResult:
    url = base_url.rstrip("/") + route.path
    t0 = time.time()
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=False)
        elapsed = int((time.time() - t0) * 1000)
        category = classify_status(resp.status_code, route.dynamic)
        ok = category in {
            "ok",
            "redirect",
            "auth",
            "method_not_allowed",
            "bad_request",
            "not_found_dynamic",
        }
        return ProbeResult(
            path=route.path,
            status=resp.status_code,
            ok=ok,
            category=category,
            elapsed_ms=elapsed,
            dynamic=route.dynamic,
        )
    except Exception as exc:
        elapsed = int((time.time() - t0) * 1000)
        return ProbeResult(
            path=route.path,
            status=0,
            ok=False,
            category="error",
            elapsed_ms=elapsed,
            dynamic=route.dynamic,
            error=str(exc),
        )


def write_report(results: list[ProbeResult], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    json_path = out_dir / f"url-api-scan-{timestamp}.json"
    txt_path = out_dir / f"url-api-scan-{timestamp}.txt"

    payload = [asdict(item) for item in results]
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    ok_count = sum(1 for r in results if r.ok)
    fail_count = len(results) - ok_count
    server_errors = [r for r in results if r.category == "server_error"]

    lines = [
        f"Total: {len(results)}",
        f"OK: {ok_count}",
        f"Fail: {fail_count}",
        f"ServerError(5xx): {len(server_errors)}",
        "",
        "Failures:",
    ]
    for item in [r for r in results if not r.ok]:
        lines.append(
            f"- {item.path} -> status={item.status} category={item.category} "
            f"elapsed={item.elapsed_ms}ms error={item.error}"
        )
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return txt_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan Django URLs and API endpoints")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--settings", default="core.settings.development")
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--output-dir", default="reports/url_scan")
    args = parser.parse_args()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", args.settings)
    django.setup()

    resolver = get_resolver()
    routes = sorted(collect_paths(resolver.url_patterns), key=lambda item: item.path)

    results = [probe(args.base_url, route, args.timeout) for route in routes]
    report_path = write_report(results, Path(args.output_dir))

    ok_count = sum(1 for r in results if r.ok)
    fail_count = len(results) - ok_count
    print(f"SCANNED={len(results)} OK={ok_count} FAIL={fail_count}")
    print(f"REPORT={report_path.as_posix()}")

    critical = any(r.category in {"server_error", "error"} for r in results)
    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(main())
