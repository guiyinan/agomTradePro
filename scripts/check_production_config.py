#!/usr/bin/env python3
"""
生产配置安全审计脚本

检查生产环境配置是否符合安全基线。

用法：
    python scripts/check_production_config.py [--env production]

检查项：
- SECRET_KEY: 不为空且不包含不安全模式
- DEBUG: 必须为 False
- ALLOWED_HOSTS: 不能为空
- CORS_ALLOW_ALL_ORIGINS: 必须为 False
- SECURE_SSL_REDIRECT: 必须为 True
- SESSION_COOKIE_SECURE: 必须为 True
- CSRF_COOKIE_SECURE: 必须为 True
"""
import argparse
import os
import sys
from pathlib import Path
from typing import NamedTuple

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def load_settings(env_name: str = "production") -> tuple[object, list[str]]:
    """
    Load Django settings safely, returning both the settings object and any errors.

    Returns:
        Tuple of (settings_module, errors)
    """
    errors = []

    # Set the appropriate settings module
    if env_name == 'development':
        os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings.development'
    else:
        os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings.production'

    try:
        import django
        from django.core.exceptions import ImproperlyConfigured

        django.setup()
        from django.conf import settings
        return settings, errors
    except ImproperlyConfigured as e:
        errors.append(str(e))
        # Return a minimal settings object for partial checking
        from types import SimpleNamespace
        return SimpleNamespace(
            SECRET_KEY='',
            DEBUG=False,
            ALLOWED_HOSTS=[],
            CORS_ALLOW_ALL_ORIGINS=False,
            SECURE_SSL_REDIRECT=False,
            SESSION_COOKIE_SECURE=False,
            CSRF_COOKIE_SECURE=False,
            SECURE_BROWSER_XSS_FILTER=False,
            SECURE_CONTENT_TYPE_NOSNIFF=False,
            SECURE_HSTS_SECONDS=0,
            SECURE_REFERRER_POLICY='',
        ), errors
    except Exception as e:
        errors.append(f"Unexpected error loading settings: {e}")
        from types import SimpleNamespace
        return SimpleNamespace(
            SECRET_KEY='',
            DEBUG=False,
            ALLOWED_HOSTS=[],
            CORS_ALLOW_ALL_ORIGINS=False,
            SECURE_SSL_REDIRECT=False,
            SESSION_COOKIE_SECURE=False,
            CSRF_COOKIE_SECURE=False,
            SECURE_BROWSER_XSS_FILTER=False,
            SECURE_CONTENT_TYPE_NOSNIFF=False,
            SECURE_HSTS_SECONDS=0,
            SECURE_REFERRER_POLICY='',
        ), errors


class SecurityCheck(NamedTuple):
    """Security check result."""
    name: str
    passed: bool
    message: str
    severity: str = "ERROR"  # ERROR, WARNING


# Insecure patterns that indicate development/default keys
INSECURE_PATTERNS = [
    'django-insecure',
    'change-this',
    'dev-only',
    'test-only',
    'xxx',
    'example',
    'placeholder',
]


def check_secret_key() -> SecurityCheck:
    """检查 SECRET_KEY"""
    secret_key = getattr(settings, 'SECRET_KEY', '')

    if not secret_key:
        return SecurityCheck(
            name="SECRET_KEY",
            passed=False,
            message="SECRET_KEY is empty",
            severity="ERROR"
        )

    secret_key_lower = secret_key.lower()
    for pattern in INSECURE_PATTERNS:
        if pattern in secret_key_lower:
            return SecurityCheck(
                name="SECRET_KEY",
                passed=False,
                message=f"Contains insecure pattern '{pattern}'",
                severity="ERROR"
            )

    if len(secret_key) < 50:
        return SecurityCheck(
            name="SECRET_KEY",
            passed=False,
            message=f"Too short ({len(secret_key)} characters, minimum 50)",
            severity="ERROR"
        )

    return SecurityCheck(
        name="SECRET_KEY",
        passed=True,
        message=f"OK ({len(secret_key)} characters)",
        severity="INFO"
    )


def check_debug() -> SecurityCheck:
    """检查 DEBUG 设置"""
    debug = getattr(settings, 'DEBUG', True)

    if debug:
        return SecurityCheck(
            name="DEBUG",
            passed=False,
            message="DEBUG is True (must be False in production)",
            severity="ERROR"
        )

    return SecurityCheck(
        name="DEBUG",
        passed=True,
        message="OK (False)",
        severity="INFO"
    )


def check_allowed_hosts() -> SecurityCheck:
    """检查 ALLOWED_HOSTS"""
    allowed_hosts = getattr(settings, 'ALLOWED_HOSTS', [])

    if not allowed_hosts:
        return SecurityCheck(
            name="ALLOWED_HOSTS",
            passed=False,
            message="ALLOWED_HOSTS is empty",
            severity="ERROR"
        )

    # Check for wildcard (security risk)
    if '*' in allowed_hosts:
        return SecurityCheck(
            name="ALLOWED_HOSTS",
            passed=False,
            message="Contains wildcard '*' (security risk)",
            severity="WARNING"
        )

    # Check for localhost-only configurations (not suitable for production)
    localhost_only = all(
        host in ['127.0.0.1', 'localhost', '::1']
        for host in allowed_hosts
    )
    if localhost_only:
        return SecurityCheck(
            name="ALLOWED_HOSTS",
            passed=False,
            message="Only contains localhost addresses (add your production domains)",
            severity="WARNING"
        )

    return SecurityCheck(
        name="ALLOWED_HOSTS",
        passed=True,
        message=f"OK ({len(allowed_hosts)} hosts)",
        severity="INFO"
    )


def check_cors() -> SecurityCheck:
    """检查 CORS 配置"""
    cors_allow_all = getattr(settings, 'CORS_ALLOW_ALL_ORIGINS', False)

    if cors_allow_all:
        return SecurityCheck(
            name="CORS_ALLOW_ALL_ORIGINS",
            passed=False,
            message="CORS_ALLOW_ALL_ORIGINS is True (security risk)",
            severity="ERROR"
        )

    return SecurityCheck(
        name="CORS_ALLOW_ALL_ORIGINS",
        passed=True,
        message="OK (False)",
        severity="INFO"
    )


def check_ssl() -> SecurityCheck:
    """检查 SSL 相关配置"""
    checks = []
    all_passed = True
    messages = []

    # SECURE_SSL_REDIRECT
    ssl_redirect = getattr(settings, 'SECURE_SSL_REDIRECT', False)
    if ssl_redirect:
        messages.append("SECURE_SSL_REDIRECT=True")
    else:
        all_passed = False
        messages.append("SECURE_SSL_REDIRECT=False (should be True)")

    # SESSION_COOKIE_SECURE
    session_secure = getattr(settings, 'SESSION_COOKIE_SECURE', False)
    if session_secure:
        messages.append("SESSION_COOKIE_SECURE=True")
    else:
        all_passed = False
        messages.append("SESSION_COOKIE_SECURE=False (should be True)")

    # CSRF_COOKIE_SECURE
    csrf_secure = getattr(settings, 'CSRF_COOKIE_SECURE', False)
    if csrf_secure:
        messages.append("CSRF_COOKIE_SECURE=True")
    else:
        all_passed = False
        messages.append("CSRF_COOKIE_SECURE=False (should be True)")

    return SecurityCheck(
        name="SSL Security",
        passed=all_passed,
        message=", ".join(messages),
        severity="INFO" if all_passed else "ERROR"
    )


def check_additional_security() -> list[SecurityCheck]:
    """检查额外的安全配置"""
    results = []

    # SECURE_BROWSER_XSS_FILTER
    xss_filter = getattr(settings, 'SECURE_BROWSER_XSS_FILTER', False)
    results.append(SecurityCheck(
        name="SECURE_BROWSER_XSS_FILTER",
        passed=xss_filter,
        message="OK" if xss_filter else "Not set (recommended for production)",
        severity="INFO" if xss_filter else "WARNING"
    ))

    # SECURE_CONTENT_TYPE_NOSNIFF
    nosniff = getattr(settings, 'SECURE_CONTENT_TYPE_NOSNIFF', False)
    results.append(SecurityCheck(
        name="SECURE_CONTENT_TYPE_NOSNIFF",
        passed=nosniff,
        message="OK" if nosniff else "Not set (recommended for production)",
        severity="INFO" if nosniff else "WARNING"
    ))

    # SECURE_HSTS_SECONDS
    hsts_seconds = getattr(settings, 'SECURE_HSTS_SECONDS', 0)
    results.append(SecurityCheck(
        name="SECURE_HSTS_SECONDS",
        passed=hsts_seconds > 0,
        message=f"OK ({hsts_seconds}s)" if hsts_seconds > 0 else "Not set (recommended for HTTPS)",
        severity="INFO" if hsts_seconds > 0 else "WARNING"
    ))

    # SECURE_REFERRER_POLICY
    referrer_policy = getattr(settings, 'SECURE_REFERRER_POLICY', '')
    results.append(SecurityCheck(
        name="SECURE_REFERRER_POLICY",
        passed=bool(referrer_policy),
        message=f"OK ({referrer_policy})" if referrer_policy else "Not set",
        severity="INFO"
    ))

    return results


def run_audit(env_name: str = "production") -> int:
    """运行所有审计检查"""
    print(f"Production Configuration Security Audit ({env_name})")
    print("=" * 60)

    # Load settings
    settings_obj, load_errors = load_settings(env_name)

    results: list[SecurityCheck] = []

    # Report any loading errors first
    for error in load_errors:
        if 'SECRET_KEY' in error:
            results.append(SecurityCheck(
                name="SECRET_KEY",
                passed=False,
                message="Not configured or insecure",
                severity="ERROR"
            ))
        elif 'environment variable' in error:
            print(f"ERROR: {error}")
            print()
            print("Cannot continue audit. Please fix the above errors.")
            return 1

    # Core security checks (using loaded settings)
    # Re-import check functions to use the loaded settings
    global settings
    settings = settings_obj

    results.append(check_secret_key())
    results.append(check_debug())
    results.append(check_allowed_hosts())
    results.append(check_cors())
    results.append(check_ssl())

    # Additional security checks
    results.extend(check_additional_security())

    # Print results
    passed_count = 0
    warning_count = 0
    error_count = 0

    for result in results:
        if result.passed:
            status_symbol = "OK"
            passed_count += 1
        elif result.severity == "WARNING":
            status_symbol = "WARN"
            warning_count += 1
        else:
            status_symbol = "FAIL"
            error_count += 1

        print(f"{status_symbol}: {result.name}: {result.message}")

    # Print summary
    print("=" * 60)
    print(f"Summary: {passed_count}/{len(results)} checks passed")

    if warning_count > 0:
        print(f"Warnings: {warning_count}")

    if error_count > 0:
        print(f"Errors: {error_count}")
        print()
        print("Security issues detected. Please fix before deploying to production.")
        return 1

    if warning_count > 0:
        print()
        print("Some warnings detected. Review before deploying to production.")
        return 0

    print()
    print("All security checks passed!")
    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Audit production Django configuration for security issues"
    )
    parser.add_argument(
        '--env',
        default='production',
        choices=['development', 'production'],
        help='Django settings environment to check (default: production)'
    )

    args = parser.parse_args()
    return run_audit(args.env)


if __name__ == '__main__':
    sys.exit(main())
