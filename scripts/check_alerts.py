#!/usr/bin/env python
"""检查告警规则是否正确配置"""
import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("WARNING: pyyaml not installed, install with: pip install pyyaml")
    sys.exit(2)


def check_alerts(alerts_file: Path) -> tuple[bool, list[str], list[str]]:
    """
    检查告警规则配置文件。

    Returns:
        (is_valid, missing_alerts, found_alerts)
    """
    if not alerts_file.exists():
        return False, [], [f"ERROR: {alerts_file} not found"]

    errors = []

    try:
        with open(alerts_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return False, [], [f"ERROR: Invalid YAML: {e}"]

    if not config:
        return False, [], ["ERROR: Empty configuration file"]

    required_alerts = [
        'High5xxRate',
        'CeleryTaskBacklog',
        'AuditWriteFailure'
    ]

    optional_alerts = [
        'HighAPILatency',
        'DataCollectionFailure',
        'QlibInferenceFailure',
        'DatabaseConnectionPoolExhausted',
        'RedisConnectionFailure',
        'DiskSpaceLow'
    ]

    found_alerts = []
    groups = config.get('groups', [])

    if not groups:
        errors.append("ERROR: No groups defined in alerts.yml")

    for group in groups:
        rules = group.get('rules', [])
        for rule in rules:
            alert_name = rule.get('alert')
            if alert_name:
                found_alerts.append(alert_name)

                # 验证告警规则必需字段
                if not rule.get('expr'):
                    errors.append(f"ERROR: Alert '{alert_name}' missing 'expr' field")
                if not rule.get('for'):
                    errors.append(f"ERROR: Alert '{alert_name}' missing 'for' field")
                if not rule.get('labels'):
                    errors.append(f"ERROR: Alert '{alert_name}' missing 'labels' field")
                if not rule.get('annotations'):
                    errors.append(f"ERROR: Alert '{alert_name}' missing 'annotations' field")

    missing = set(required_alerts) - set(found_alerts)

    if missing:
        errors.append(f"ERROR: Missing required alerts: {missing}")

    is_valid = len(errors) == 0

    return is_valid, missing, found_alerts, errors


def check_prometheus(prometheus_file: Path) -> tuple[bool, list[str]]:
    """
    检查 Prometheus 配置文件。

    Returns:
        (is_valid, errors)
    """
    if not prometheus_file.exists():
        return False, [f"ERROR: {prometheus_file} not found"]

    try:
        with open(prometheus_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return False, [f"ERROR: Invalid YAML: {e}"]

    errors = []

    # 检查全局配置
    global_config = config.get('global', {})
    if not global_config.get('scrape_interval'):
        errors.append("WARNING: No scrape_interval defined in global config")

    # 检查告警规则文件引用
    rule_files = config.get('rule_files', [])
    if not rule_files:
        errors.append("ERROR: No rule_files defined in prometheus.yml")
    elif 'alerts.yml' not in rule_files:
        errors.append("WARNING: alerts.yml not referenced in rule_files")

    # 检查抓取配置
    scrape_configs = config.get('scrape_configs', [])
    if not scrape_configs:
        errors.append("ERROR: No scrape_configs defined")

    required_jobs = ['agomtradepro', 'celery']
    found_jobs = [job.get('job_name') for job in scrape_configs]
    missing_jobs = set(required_jobs) - set(found_jobs)

    if missing_jobs:
        errors.append(f"WARNING: Missing recommended scrape jobs: {missing_jobs}")

    is_valid = not any(e.startswith("ERROR") for e in errors)

    return is_valid, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check AgomTradePro monitoring configuration")
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed output'
    )
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    alerts_file = project_root / 'monitoring' / 'alerts.yml'
    prometheus_file = project_root / 'monitoring' / 'prometheus.yml'

    print(f"Checking: {alerts_file.relative_to(project_root)}")
    alerts_valid, missing, found, errors = check_alerts(alerts_file)

    if errors:
        for error in errors:
            print(f"  {error}")

    if alerts_valid:
        print("  OK: All required alerts configured")
        if args.verbose:
            print(f"  Found alerts: {', '.join(sorted(found))}")
    else:
        print(f"  FAILED: {len(errors)} error(s) found")

    print()

    print(f"Checking: {prometheus_file.relative_to(project_root)}")
    prom_valid, prom_errors = check_prometheus(prometheus_file)

    for error in prom_errors:
        print(f"  {error}")

    if prom_valid:
        print("  OK: Prometheus configuration is valid")
    else:
        print(f"  FAILED: Prometheus configuration has errors")

    print()

    if alerts_valid and prom_valid:
        print("SUCCESS: All monitoring checks passed")
        return 0
    else:
        print("FAILED: Some checks failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
