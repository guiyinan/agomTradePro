#!/usr/bin/env python
"""
路由一致性校验脚本

检查所有模块路由是否符合规范：/api/{module}/{resource}/

退出码：
- 0: 所有路由符合规范
- 1: 存在不符合规范的路由

用法：
    python scripts/check_routes.py [--fix]

模式说明：
- 新规范: /api/{module}/... (正确的统一 API 路由格式)
- 旧模式: /{module}/api/... (需要迁移的旧格式)
- 页面路由: /{module}/... (页面路由，不参与 API 规范检查)
- 白名单: 特殊系统路由（如 /admin/、/static/ 等）
"""

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
路由一致性校验脚本

检查所有模块路由是否符合规范：/api/{module}/{resource}/

退出码：
- 0: 所有路由符合规范
- 1: 存在不符合规范的路由

用法：
    python scripts/check_routes.py [--fix]

模式说明：
- 新规范: /api/{module}/... (正确的统一 API 路由格式)
- 旧模式: /{module}/api/... (需要迁移的旧格式)
- 页面路由: /{module}/... (页面路由，不参与 API 规范检查)
- 白名单: 特殊系统路由（如 /admin/、/static/ 等）
"""

import argparse
import ast
import io
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# 设置标准输出编码为 UTF-8
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


# 路由规范模式
NEW_API_PATTERN = re.compile(r'^/api/[a-z][a-z_-]*/')  # /api/{module}/
OLD_API_PATTERN = re.compile(r'^/[a-z][a-z_-]*/api/')  # /{module}/api/

# 允许的特殊路由（白名单）
ROUTE_WHITELIST = {
    '/api/health/',
    '/api/ready/',
    '/api/debug/',
    '/api/schema/',
    '/api/docs/',
    '/api/redoc/',
    '/admin/',
    '/static/',
    '/media/',
    '/api/alpha/',  # Alpha 模块特殊路由
    '/api/system/',  # 系统模块
}

# 不需要检查的模块（只有页面路由的模块）
PAGE_ONLY_MODULES = {
    'dashboard',
    'decision_rhythm',
    'beta_gate',
    'alpha_trigger',
}


@dataclass
class RouteViolation:
    """路由违规记录"""
    module: str
    url_pattern: str
    file_path: str
    line_number: int
    violation_type: str  # 'old_api_format', 'missing_api_prefix', 'naming_mismatch'
    suggestion: str = ""


@dataclass
class RouteInfo:
    """路由信息"""
    module: str
    url_pattern: str
    file_path: str
    line_number: int
    is_page_route: bool = False
    is_api_route: bool = False
    mount_point: str = ""  # 在 core/urls.py 中的挂载点


class URLPatternExtractor(ast.NodeVisitor):
    """从 AST 中提取 URL 路由模式"""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.routes: list[dict] = []

    def visit_Call(self, node):
        """访问函数调用，查找 path() 调用"""
        if isinstance(node.func, ast.Name) and node.func.id == 'path':
            self._extract_path_info(node)
        self.generic_visit(node)

    def _extract_path_info(self, node):
        """从 path() 调用中提取信息"""
        if not node.args:
            return

        # 第一个参数是 URL 模式
        url_arg = node.args[0]
        if isinstance(url_arg, ast.Constant):
            url_pattern = url_arg.value
        else:
            return

        # 获取行号
        line_number = node.lineno

        self.routes.append({
            'pattern': url_pattern,
            'line': line_number,
        })


def extract_routes_from_file(file_path: str) -> list[dict]:
    """从文件中提取路由"""
    try:
        with open(file_path, encoding='utf-8') as f:
            content = f.read()

        tree = ast.parse(content, filename=file_path)
        extractor = URLPatternExtractor(file_path)
        extractor.visit(tree)
        return extractor.routes
    except Exception as e:
        print(f"Warning: Could not parse {file_path}: {e}", file=sys.stderr)
        return []


def extract_mount_points_from_core_urls() -> dict[str, list[str]]:
    """从 core/urls.py 提取模块挂载点信息"""
    core_urls_path = Path('core/urls.py')
    if not core_urls_path.exists():
        return {}

    mount_points = defaultdict(list)

    try:
        with open(core_urls_path, encoding='utf-8') as f:
            content = f.read()

        tree = ast.parse(content, filename=str(core_urls_path))

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == 'path':
                    if len(node.args) >= 2:
                        # 第一个参数是挂载点
                        url_arg = node.args[0]
                        if isinstance(url_arg, ast.Constant):
                            mount_pattern = url_arg.value
                        else:
                            continue

                        # 第二个参数是 include()
                        if len(node.args) >= 2:
                            include_arg = node.args[1]
                            if isinstance(include_arg, ast.Call):
                                if isinstance(include_arg.func, ast.Name) and include_arg.func.id == 'include':
                                    # 提取模块名
                                    if include_arg.args:
                                        module_ref = include_arg.args[0]
                                        if isinstance(module_ref, ast.Constant):
                                            module_path = module_ref.value
                                        elif isinstance(module_ref, ast.Tuple):
                                            # 处理 include(('apps.module.urls', 'namespace'), namespace='xxx') 格式
                                            if module_ref.elts and isinstance(module_ref.elts[0], ast.Constant):
                                                module_path = module_ref.elts[0].value
                                            else:
                                                continue
                                        else:
                                            continue

                                        # 从 apps.{module}.interface.urls 提取模块名
                                        if 'apps.' in module_path:
                                            parts = module_path.split('.')
                                            if len(parts) >= 2:
                                                module_name = parts[1]
                                                mount_points[module_name].append(mount_pattern)

    except Exception as e:
        print(f"Warning: Could not parse core/urls.py: {e}", file=sys.stderr)

    return dict(mount_points)


def is_whitelisted(url: str) -> bool:
    """检查 URL 是否在白名单中"""
    for prefix in ROUTE_WHITELIST:
        if url.startswith(prefix):
            return True
    return False


def check_route_pattern(url: str) -> tuple[bool, str, str]:
    """
    检查路由模式

    返回: (is_valid, reason, pattern_type)
    pattern_type: 'new_api', 'old_api', 'page', 'whitelist', 'other'
    """
    # 跳过白名单
    if is_whitelisted(url):
        return True, 'whitelist', 'whitelist'

    # 检查新规范 API 路由
    if NEW_API_PATTERN.match(url):
        return True, 'new_api_standard', 'new_api'

    # 检查旧模式 API 路由
    if OLD_API_PATTERN.match(url):
        return False, 'old_api_format', 'old_api'

    # 检查是否是页面路由（不以 /api/ 开头）
    if not url.startswith('/api/'):
        return True, 'page_route', 'page'

    # 其他情况
    return True, 'other', 'other'


def collect_all_routes() -> tuple[list[RouteInfo], dict[str, list[str]]]:
    """收集所有路由信息"""
    routes: list[RouteInfo] = []
    mount_points = extract_mount_points_from_core_urls()

    # 收集所有 urls.py 和 api_urls.py
    for urls_file in Path('apps').glob('*/interface/urls.py'):
        # 从路径中提取模块名
        # 路径格式: apps/{module}/interface/urls.py
        parts = urls_file.parts
        if 'apps' in parts:
            apps_idx = parts.index('apps')
            if apps_idx + 1 < len(parts):
                module_name = parts[apps_idx + 1]
            else:
                continue
        else:
            continue

        file_routes = extract_routes_from_file(str(urls_file))

        for route in file_routes:
            url_pattern = route['pattern']
            line_number = route['line']

            # 确定路由类型
            # 路由可能以 'api/...' 开头（旧格式）或直接是资源名
            is_api_route = (
                url_pattern.startswith('api/') or
                url_pattern.startswith('api-') or
                (url_pattern.startswith('/') and 'api/' in url_pattern)
            )
            is_page_route = not is_api_route and not url_pattern.startswith('api/')

            # 获取挂载点
            mount_list = mount_points.get(module_name, [])
            mount = mount_list[0] if mount_list else ""

            routes.append(RouteInfo(
                module=module_name,
                url_pattern=url_pattern,
                file_path=str(urls_file),
                line_number=line_number,
                is_page_route=is_page_route,
                is_api_route=is_api_route,
                mount_point=mount,
            ))

    # 收集 api_urls.py 文件
    for urls_file in Path('apps').glob('*/interface/api_urls.py'):
        # 从路径中提取模块名
        parts = urls_file.parts
        if 'apps' in parts:
            apps_idx = parts.index('apps')
            if apps_idx + 1 < len(parts):
                module_name = parts[apps_idx + 1]
            else:
                continue
        else:
            continue

        file_routes = extract_routes_from_file(str(urls_file))

        for route in file_routes:
            url_pattern = route['pattern']
            line_number = route['line']

            # api_urls.py 中的路由都是 API 路由
            # 查找对应的挂载点（可能是 /api/{module}/）
            mount = ""
            for mount_pattern in mount_points.get(module_name, []):
                if mount_pattern.startswith('/api/'):
                    mount = mount_pattern
                    break
            if not mount:
                mount_list = mount_points.get(module_name, [])
                mount = mount_list[0] if mount_list else ""

            routes.append(RouteInfo(
                module=module_name,
                url_pattern=url_pattern,
                file_path=str(urls_file),
                line_number=line_number,
                is_page_route=False,
                is_api_route=True,
                mount_point=mount,
            ))

    return routes, mount_points


def find_violations(routes: list[RouteInfo], mount_points: dict[str, list[str]]) -> list[RouteViolation]:
    """查找路由违规"""
    violations: list[RouteViolation] = []

    # 已有 api_urls.py 的模块 - 这些模块的 API 路由应该都在 api_urls.py 中
    modules_with_api_urls = set()
    for p in Path('apps').glob('*/interface/api_urls.py'):
        parts = p.parts
        if 'apps' in parts:
            apps_idx = parts.index('apps')
            if apps_idx + 1 < len(parts):
                modules_with_api_urls.add(parts[apps_idx + 1])

    for route in routes:
        url = route.url_pattern
        file_name = Path(route.file_path).name

        # 检查 1: 如果模块已有 api_urls.py，则 urls.py 中不应有 'api/' 开头的路由
        # （除非是注释标明为 legacy 的路由）
        if file_name == 'urls.py' and url.startswith('api/'):
            if route.module in modules_with_api_urls:
                violations.append(RouteViolation(
                    module=route.module,
                    url_pattern=url,
                    file_path=route.file_path,
                    line_number=route.line_number,
                    violation_type='duplicate_api_route',
                    suggestion="模块已有 api_urls.py，API 路由应移至 api_urls.py 以避免重复",
                ))
            # 注意: api_in_urls_file_suggested 不计入违规，仅作为建议
            # 因为模块可以只使用 urls.py，只要路由挂载到 /api/{module}/ 即可

        # 检查 2: 检查完整路由（挂载点 + 路由模式）是否是旧格式
        # 特别关注 /{module}/api/... 这种格式
        if route.mount_point and not route.mount_point.startswith('/api/'):
            full_url = route.mount_point.rstrip('/') + '/' + url.lstrip('/')
            if 'api/' in full_url and not full_url.startswith('/api/'):
                # 检查是否是 {module}/api/ 格式
                if OLD_API_PATTERN.match(full_url):
                    violations.append(RouteViolation(
                        module=route.module,
                        url_pattern=full_url,
                        file_path=route.file_path,
                        line_number=route.line_number,
                        violation_type='old_api_mount_format',
                        suggestion=f"旧格式 /{{module}}/api/... 应迁移到 /api/{route.module}/...",
                    ))

    return violations


def print_summary(routes: list[RouteInfo], violations: list[RouteViolation], mount_points: dict[str, list[str]]):
    """打印汇总信息"""
    # 统计
    total_routes = len(routes)
    page_routes = sum(1 for r in routes if r.is_page_route)
    api_routes = sum(1 for r in routes if r.is_api_route)
    total_violations = len(violations)

    # 按模块统计
    module_stats = defaultdict(lambda: {'page': 0, 'api': 0, 'violations': 0})
    for route in routes:
        module_stats[route.module]['page' if route.is_page_route else 'api'] += 1
    for v in violations:
        module_stats[v.module]['violations'] += 1

    print("\n" + "=" * 80)
    print("路由一致性校验报告")
    print("=" * 80)
    print(f"\n总计路由: {total_routes}")
    print(f"  - 页面路由: {page_routes}")
    print(f"  - API 路由: {api_routes}")
    print(f"  - 违规路由: {total_violations}")

    print("\n按模块统计:")
    print("-" * 80)
    print(f"{'模块':<25} {'页面路由':<10} {'API路由':<10} {'违规':<10} {'挂载点'}")
    print("-" * 80)

    for module in sorted(module_stats.keys()):
        stats = module_stats[module]
        mounts = mount_points.get(module, [])
        mount_str = ', '.join(mounts) if mounts else '未挂载'
        print(f"{module:<25} {stats['page']:<10} {stats['api']:<10} {stats['violations']:<10} {mount_str}")

    # 打印违规详情
    if violations:
        print("\n" + "=" * 80)
        print(f"违规路由详情 ({len(violations)} 条)")
        print("=" * 80)

        for v in violations:
            print(f"\n模块: {v.module}")
            print(f"  路由: {v.url_pattern}")
            print(f"  位置: {v.file_path}:{v.line_number}")
            print(f"  类型: {v.violation_type}")
            print(f"  建议: {v.suggestion}")


def print_fix_suggestions(violations: list[RouteViolation]):
    """打印修复建议"""
    if not violations:
        return

    print("\n" + "=" * 80)
    print("修复建议")
    print("=" * 80)

    # 按模块分组
    by_module: dict[str, list[RouteViolation]] = defaultdict(list)
    for v in violations:
        by_module[v.module].append(v)

    for module, module_violations in sorted(by_module.items()):
        print(f"\n## {module} 模块")

        # 检查是否有 api_urls.py
        api_urls_path = Path(f"apps/{module}/interface/api_urls.py")
        has_api_urls = api_urls_path.exists()

        print(f"  状态: {'已有 api_urls.py' if has_api_urls else '需要创建 api_urls.py'}")

        for v in module_violations:
            print(f"\n  违规路由: {v.url_pattern}")
            print(f"    文件: {v.file_path}:{v.line_number}")
            print(f"    修复: {v.suggestion}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='检查路由是否符合规范 /api/{module}/{resource}/'
    )
    parser.add_argument(
        '--fix',
        action='store_true',
        help='显示详细的修复建议'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='显示详细信息'
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='严格模式：任何违规立即失败（退出码1）'
    )
    args = parser.parse_args()

    # 收集路由
    print("正在收集路由...")
    routes, mount_points = collect_all_routes()

    # 查找违规
    violations = find_violations(routes, mount_points)

    # 打印汇总
    print_summary(routes, violations, mount_points)

    # 打印修复建议
    if args.fix and violations:
        print_fix_suggestions(violations)

    # 返回退出码
    if violations:
        print(f"\n发现 {len(violations)} 个路由违规")
        if args.strict:
            print("严格模式：检查失败")
            return 1
        return 1
    else:
        print("\n所有路由符合规范")
        return 0


if __name__ == '__main__':
    sys.exit(main())
