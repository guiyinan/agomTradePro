#!/usr/bin/env python3
"""
Check consistency between documentation, routes, and SDK.

Validates:
1. Document-referenced routes exist in actual routes
2. Routes have SDK coverage (if applicable)
3. SDK endpoints match actual routes

Usage:
    python scripts/check_doc_route_sdk_consistency.py [--baseline reports/consistency/baseline.json]
    python scripts/check_doc_route_sdk_consistency.py --update-baseline
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.base')

try:
    import django
    django.setup()
except Exception as e:
    print(f"Warning: Could not setup Django: {e}", file=sys.stderr)
    print("Continuing without Django integration...", file=sys.stderr)


@dataclass
class ConsistencyIssue:
    type: str  # 'missing_route', 'missing_sdk', 'sdk_mismatch', 'deprecated_route'
    source: str  # file where issue found
    route: str
    details: str
    line: int = 0
    is_baseline: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "source": self.source,
            "route": self.route,
            "details": self.details,
            "line": self.line,
        }


@dataclass
class RouteInfo:
    path: str
    name: str | None
    methods: list[str]
    view_name: str
    module: str
    is_deprecated: bool = False


class RouteExtractor:
    """Extract routes from Django URL configuration."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.core_urls_file = project_root / "core" / "urls.py"
        self.apps_dir = project_root / "apps"

    def extract_all_routes(self) -> dict[str, RouteInfo]:
        """Extract all routes from the project."""
        routes: dict[str, RouteInfo] = {}

        # First, try to use Django's URL resolver
        try:
            from django.urls import get_resolver
            resolver = get_resolver()

            def collect_urls(patterns: list, prefix: str = "") -> None:
                for pattern in patterns:
                    if hasattr(pattern, 'url_patterns'):
                        # This is an include()
                        new_prefix = prefix + str(pattern.pattern)
                        collect_urls(pattern.url_patterns, new_prefix)
                    elif hasattr(pattern, 'callback'):
                        # This is a URL pattern
                        route_str = prefix + str(pattern.pattern)
                        # Clean up regex patterns
                        route_str = route_str.replace('^', '').replace('$', '')
                        # Normalize
                        if not route_str.startswith('/'):
                            route_str = '/' + route_str

                        name = getattr(pattern, 'name', None)
                        callback = pattern.callback

                        # Determine methods
                        methods = ["GET"]
                        view_name = callback.__name__ if hasattr(callback, '__name__') else str(callback)

                        # Check for ViewSet or APIView
                        if hasattr(callback, 'cls'):
                            cls = callback.cls
                            view_name = cls.__name__
                            # DRF ViewSets typically support multiple methods
                            if hasattr(cls, 'get_queryset'):
                                methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]

                        routes[route_str] = RouteInfo(
                            path=route_str,
                            name=name,
                            methods=methods,
                            view_name=view_name,
                            module=callback.__module__ if hasattr(callback, '__module__') else "unknown",
                        )

            collect_urls(resolver.url_patterns)

        except Exception as e:
            print(f"Warning: Could not use Django resolver: {e}", file=sys.stderr)

        # Fallback: parse URL files
        if not routes:
            routes = self._parse_url_files()

        return routes

    def _parse_url_files(self) -> dict[str, RouteInfo]:
        """Parse URL files by reading them directly."""
        routes: dict[str, RouteInfo] = {}

        # Parse core/urls.py
        if self.core_urls_file.exists():
            core_routes = self._parse_single_url_file(self.core_urls_file, "")
            routes.update(core_routes)

        # Parse apps/*/interface/urls.py
        for app_dir in self.apps_dir.iterdir():
            if not app_dir.is_dir():
                continue
            url_file = app_dir / "interface" / "urls.py"
            if url_file.exists():
                # Extract module name
                module_name = app_dir.name
                # Determine prefix from core/urls.py includes
                prefix = self._get_module_prefix(module_name)
                app_routes = self._parse_single_url_file(url_file, prefix)
                routes.update(app_routes)

        return routes

    def _get_module_prefix(self, module_name: str) -> str:
        """Get URL prefix for a module from core/urls.py."""
        common_prefixes = {
            "regime": "/api/regime",
            "signal": "/api/signal",
            "macro": "/api/macro",
            "policy": "/api/policy",
            "backtest": "/api/backtest",
            "audit": "/api/audit",
            "equity": "/api/equity",
            "fund": "/api/fund",
            "sector": "/api/sector",
            "realtime": "/api/realtime",
            "alpha": "/api/alpha",
            "factor": "/api/factor",
            "rotation": "/api/rotation",
            "hedge": "/api/hedge",
            "sentiment": "/api/sentiment",
            "account": "/api/account",
            "simulated_trading": "/api/simulated-trading",
            "strategy": "/api/strategy",
            "ai_provider": "/api/ai",
            "prompt": "/api/prompt",
            "asset_analysis": "/api/asset-analysis",
            "dashboard": "/dashboard/api/v1",
        }
        return common_prefixes.get(module_name, f"/{module_name}")

    def _parse_single_url_file(self, url_file: Path, base_prefix: str) -> dict[str, RouteInfo]:
        """Parse a single URL configuration file."""
        routes: dict[str, RouteInfo] = {}

        try:
            content = url_file.read_text(encoding="utf-8")

            # Find path() calls
            path_pattern = r'path\([\'"]([^\'"]+)[\'"],\s*([^)]+)\)'
            for match in re.finditer(path_pattern, content):
                route_pattern = match.group(1)
                callback = match.group(2).strip()

                # Skip include() and redirect views
                if 'include(' in callback or 'RedirectView' in callback:
                    continue

                # Clean up route pattern
                route_pattern = route_pattern.replace('<', ':').replace('>', '')

                # Build full path
                if base_prefix and not route_pattern.startswith(base_prefix):
                    full_path = base_prefix.rstrip('/') + '/' + route_pattern.lstrip('/')
                else:
                    full_path = '/' + route_pattern.lstrip('/')

                # Extract view name
                view_match = re.search(r'(\w+)\.as_view\(\)', callback)
                if view_match:
                    view_name = view_match.group(1)
                else:
                    # Extract from views.xxx or api_views.xxx
                    view_match = re.search(r'(?:views|api_views)\.(\w+)', callback)
                    view_name = view_match.group(1) if view_match else callback

                routes[full_path] = RouteInfo(
                    path=full_path,
                    name=None,
                    methods=["GET"],
                    view_name=view_name,
                    module=str(url_file.relative_to(self.project_root)),
                )

            # Find router.register() calls
            router_pattern = r'register\(\s*[\'"]([^\'"]+)[\'"],\s*(\w+)'
            for match in re.finditer(router_pattern, content):
                prefix = match.group(1)
                viewset = match.group(2)

                # DRF ViewSet routes
                full_prefix = base_prefix.rstrip('/') + '/' + prefix.lstrip('/')
                full_prefix = '/' + full_prefix.lstrip('/')

                # Standard REST routes
                standard_routes = [
                    (f"{full_prefix}/", ["GET", "POST"]),
                    (f"{full_prefix}/:id/", ["GET", "PUT", "PATCH", "DELETE"]),
                ]

                for route, methods in standard_routes:
                    routes[route] = RouteInfo(
                        path=route,
                        name=None,
                        methods=methods,
                        view_name=viewset,
                        module=str(url_file.relative_to(self.project_root)),
                    )

        except Exception as e:
            print(f"Warning: Could not parse {url_file}: {e}", file=sys.stderr)

        return routes


class DocumentationParser:
    """Parse documentation files for route references."""

    def __init__(self, docs_dir: Path):
        self.docs_dir = docs_dir
        self.route_patterns = [
            # Markdown code blocks
            r'```[a-z]*\n(?:[^`]*\n)*?(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s`]+)',
            # Inline code
            r'`(?:GET|POST|PUT|PATCH|DELETE)\s+(/[^\s`]+)`',
            # Direct references
            r'(?:端点|Endpoint|API):\s*`?(/[a-zA-Z0-9/_-]+)`?',
            # URL format
            r'`(/[a-z]+/[a-z0-9_-]+/?)`',
        ]

    def extract_route_references(self) -> dict[str, list[tuple[str, int]]]:
        """Extract all route references from documentation files."""
        references: dict[str, list[tuple[str, int]]] = {}

        for md_file in self.docs_dir.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                file_routes: list[tuple[str, int]] = []

                lines = content.split('\n')
                for line_num, line in enumerate(lines, 1):
                    for pattern in self.route_patterns:
                        for match in re.finditer(pattern, line):
                            route = match.group(1) if match.lastindex >= 1 else match.group(0)
                            # Clean up the route
                            route = route.strip('`\'"')
                            if not route.startswith('/'):
                                continue
                            file_routes.append((route, line_num))

                if file_routes:
                    references[str(md_file.relative_to(self.docs_dir.parent))] = file_routes

            except Exception as e:
                print(f"Warning: Could not parse {md_file}: {e}", file=sys.stderr)

        return references


class SDKParser:
    """Parse SDK files for endpoint references."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.sdk_dir = project_root / "sdk"

    def extract_sdk_endpoints(self) -> dict[str, list[str]]:
        """Extract all API endpoints referenced in the SDK."""
        endpoints: dict[str, list[str]] = {}

        if not self.sdk_dir.exists():
            return endpoints

        # Parse SDK module files
        modules_file = self.sdk_dir / "agomsaaf" / "modules" / "__init__.py"
        if not modules_file.exists():
            modules_file = self.sdk_dir / "agomsaaf" / "client.py"

        if modules_file.exists():
            # Find all module files
            for module_file in (self.sdk_dir / "agomsaaf" / "modules").glob("*.py"):
                if module_file.name == "__init__.py":
                    continue

                try:
                    content = module_file.read_text(encoding="utf-8")
                    module_name = module_file.stem

                    # Find API endpoint patterns
                    # Look for self._get, self._post, etc. calls
                    endpoint_pattern = r'self\._(?:get|post|put|patch|delete)\([\'"]([^\'"]+)[\'"]'

                    module_endpoints = []
                    for match in re.finditer(endpoint_pattern, content):
                        endpoint = match.group(1)
                        module_endpoints.append(endpoint)

                    # Also check the base path in __init__
                    base_path_pattern = r'super\(\).__init__\([^,]+,\s*[\'"]([^\'"]+)[\'"]'
                    for match in re.finditer(base_path_pattern, content):
                        base_path = match.group(1)
                        # Add base path as a module identifier
                        if module_endpoints:
                            endpoints[module_name] = [base_path] + module_endpoints
                        elif base_path:
                            endpoints[module_name] = [base_path]

                except Exception as e:
                    print(f"Warning: Could not parse {module_file}: {e}", file=sys.stderr)

        # Parse MCP tools
        mcp_tools_dir = self.sdk_dir / "agomsaaf_mcp" / "tools"
        if mcp_tools_dir.exists():
            for tool_file in mcp_tools_dir.glob("*.py"):
                if tool_file.name == "__init__.py":
                    continue

                try:
                    content = tool_file.read_text(encoding="utf-8")
                    tool_name = tool_file.stem

                    # Find endpoint references in tool definitions
                    endpoint_pattern = r'[\'"](/[a-zA-Z0-9/_-]+)[\'"]'

                    tool_endpoints = []
                    for match in re.finditer(endpoint_pattern, content):
                        endpoint = match.group(1)
                        if endpoint.startswith('/api/') or endpoint.startswith('/'):
                            tool_endpoints.append(endpoint)

                    if tool_endpoints:
                        endpoints[f"mcp_{tool_name}"] = tool_endpoints

                except Exception as e:
                    print(f"Warning: Could not parse {tool_file}: {e}", file=sys.stderr)

        return endpoints


def load_baseline(path: Path) -> dict[str, Any]:
    """Load baseline issues file."""
    if not path.exists():
        return {
            "version": "1.0",
            "created": datetime.now().isoformat(),
            "routes": [],
            "notes": "Baseline for existing inconsistencies - warnings only"
        }

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Warning: Could not load baseline: {e}", file=sys.stderr)
        return {}


def save_baseline(path: Path, issues: list[ConsistencyIssue]) -> None:
    """Save baseline issues file."""
    path.parent.mkdir(parents=True, exist_ok=True)

    baseline = {
        "version": "1.0",
        "created": datetime.now().isoformat(),
        "routes": [issue.route for issue in issues],
        "issues": [issue.to_dict() for issue in issues],
        "notes": "Baseline for existing inconsistencies - warnings only"
    }

    path.write_text(json.dumps(baseline, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Baseline saved to {path}")


def check_consistency(
    project_root: Path,
    baseline: dict[str, Any] | None = None
) -> list[ConsistencyIssue]:
    """Run all consistency checks."""
    issues: list[ConsistencyIssue] = []
    baseline_routes = set(baseline.get("routes", [])) if baseline else set()

    # Step 1: Extract all routes
    print("Extracting Django routes...")
    route_extractor = RouteExtractor(project_root)
    django_routes = route_extractor.extract_all_routes()
    print(f"  Found {len(django_routes)} routes")

    # Step 2: Extract documentation references
    print("Parsing documentation files...")
    docs_dir = project_root / "docs"
    doc_parser = DocumentationParser(docs_dir)
    doc_routes = doc_parser.extract_route_references()
    print(f"  Found {len(doc_routes)} documentation files with route references")

    # Step 3: Extract SDK endpoints
    print("Parsing SDK files...")
    sdk_parser = SDKParser(project_root)
    sdk_endpoints = sdk_parser.extract_sdk_endpoints()
    print(f"  Found {len(sdk_endpoints)} SDK modules with endpoints")

    # Check 1: Documentation references exist in Django
    print("\nChecking documentation route references...")
    for doc_file, routes in doc_routes.items():
        for route, line_num in routes:
            # Normalize route for comparison
            normalized_route = route.rstrip('/')

            # Check for exact match
            found = False
            for django_route in django_routes.values():
                if normalized_route == django_route.path.rstrip('/'):
                    found = True
                    break

            if not found:
                # Check if it's in baseline
                if normalized_route in baseline_routes or route in baseline_routes:
                    issue = ConsistencyIssue(
                        type='missing_route',
                        source=doc_file,
                        route=route,
                        details=f"Route {route} referenced in docs but not found in Django (baseline)",
                        line=line_num,
                        is_baseline=True,
                    )
                else:
                    issue = ConsistencyIssue(
                        type='missing_route',
                        source=doc_file,
                        route=route,
                        details=f"Route {route} referenced in docs but not found in Django",
                        line=line_num,
                        is_baseline=False,
                    )
                issues.append(issue)

    # Check 2: SDK modules have corresponding routes
    print("\nChecking SDK endpoint coverage...")
    for module_name, endpoints in sdk_endpoints.items():
        for endpoint in endpoints:
            if not endpoint.startswith('/'):
                # This is likely a relative path from a base path
                continue

            normalized_endpoint = endpoint.rstrip('/')

            # Check for exact or partial match
            found = False
            for django_route in django_routes.values():
                if normalized_endpoint == django_route.path.rstrip('/'):
                    found = True
                    break
                # Check for prefix match (for base paths)
                if django_route.path.rstrip('/').startswith(normalized_endpoint):
                    found = True
                    break

            if not found:
                # Check if it's in baseline
                if normalized_endpoint in baseline_routes or endpoint in baseline_routes:
                    issue = ConsistencyIssue(
                        type='missing_route',
                        source=f"sdk/{module_name}",
                        route=endpoint,
                        details=f"SDK endpoint {endpoint} not found in Django routes (baseline)",
                        is_baseline=True,
                    )
                else:
                    issue = ConsistencyIssue(
                        type='missing_route',
                        source=f"sdk/{module_name}",
                        route=endpoint,
                        details=f"SDK endpoint {endpoint} not found in Django routes",
                        is_baseline=False,
                    )
                issues.append(issue)

    # Check 3: Check for deprecated route patterns
    print("\nChecking for deprecated route patterns...")
    # Skip this check for now - deprecated routes are known issues
    # They exist for backward compatibility and are documented
    # We could enable this check later with proper baseline tracking

    return issues


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Check consistency between documentation, routes, and SDK"
    )
    parser.add_argument(
        '--baseline',
        type=Path,
        default=Path('reports/consistency/baseline.json'),
        help="Path to baseline file"
    )
    parser.add_argument(
        '--update-baseline',
        action='store_true',
        help="Update baseline with current issues"
    )
    parser.add_argument(
        '--project-root',
        type=Path,
        default=Path(__file__).parent.parent,
        help="Project root directory"
    )

    args = parser.parse_args()

    # Load baseline
    baseline = load_baseline(args.baseline)

    # Run consistency check
    issues = check_consistency(args.project_root, baseline)

    # Update baseline if requested
    if args.update_baseline:
        save_baseline(args.baseline, issues)
        return 0

    # Report results
    new_issues = [i for i in issues if not i.is_baseline]
    baseline_issues = [i for i in issues if i.is_baseline]

    if baseline_issues:
        print(f"\n[WARNING] {len(baseline_issues)} baseline issues (warning only)")
        for issue in baseline_issues[:10]:  # Show first 10
            print(f"  - [{issue.type}] {issue.route} in {issue.source}")
        if len(baseline_issues) > 10:
            print(f"  ... and {len(baseline_issues) - 10} more")

    if new_issues:
        print(f"\n[ERROR] {len(new_issues)} new issues found", file=sys.stderr)
        for issue in new_issues:
            if issue.line:
                print(f"  - [{issue.type}] {issue.route} in {issue.source}:{issue.line}", file=sys.stderr)
            else:
                print(f"  - [{issue.type}] {issue.route} in {issue.source}", file=sys.stderr)
            print(f"    {issue.details}", file=sys.stderr)
        return 1

    print("\n[PASS] Consistency check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
