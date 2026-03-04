#!/usr/bin/env python
"""
Slow Query Analysis Script

解析 Django 日志中的慢查询记录，生成统计报告。

使用示例:
    # 分析日志文件
    python scripts/analyze_slow_queries.py logs/django.log

    # 指定时间范围
    python scripts/analyze_slow_queries.py logs/django.log --start "2026-03-01 00:00:00" --end "2026-03-02 00:00:00"

    # 输出 JSON 格式
    python scripts/analyze_slow_queries.py logs/django.log --json

    # 只显示 Top 10
    python scripts/analyze_slow_queries.py logs/django.log --top 10

    # 按操作类型过滤
    python scripts/analyze_slow_queries.py logs/django.log --operation SELECT
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class SlowQuery:
    """慢查询记录"""
    timestamp: str
    sql: str
    sql_hash: int
    duration_ms: float
    threshold_ms: int
    operation: str
    trace_id: str
    request_path: str
    request_method: str


@dataclass
class QueryPattern:
    """查询模式统计"""
    pattern: str
    count: int = 0
    total_ms: float = 0
    avg_ms: float = 0
    max_ms: float = 0
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None

    def add(self, duration_ms: float, timestamp: str) -> None:
        """添加一次查询记录"""
        self.count += 1
        self.total_ms += duration_ms
        self.avg_ms = self.total_ms / self.count
        self.max_ms = max(self.max_ms, duration_ms)

        if self.first_seen is None:
            self.first_seen = timestamp
        self.last_seen = timestamp


@dataclass
class AnalysisReport:
    """分析报告"""
    total_slow_queries: int = 0
    operation_counts: dict[str, int] = field(default_factory=dict)
    patterns: dict[str, QueryPattern] = field(default_factory=dict)
    requests_with_slow_queries: int = 0
    total_slow_query_time_ms: float = 0

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'total_slow_queries': self.total_slow_queries,
            'operation_counts': self.operation_counts,
            'requests_with_slow_queries': self.requests_with_slow_queries,
            'total_slow_query_time_ms': round(self.total_slow_query_time_ms, 2),
            'top_patterns': [
                {
                    'pattern': pattern.pattern,
                    'count': pattern.count,
                    'total_ms': round(pattern.total_ms, 2),
                    'avg_ms': round(pattern.avg_ms, 2),
                    'max_ms': round(pattern.max_ms, 2),
                    'first_seen': pattern.first_seen,
                    'last_seen': pattern.last_seen,
                }
                for pattern in sorted(
                    self.patterns.values(),
                    key=lambda p: p.total_ms,
                    reverse=True
                )[:20]
            ]
        }


# 日志解析正则表达式
SLOW_QUERY_PATTERN = re.compile(
    r'.*?event=(?P<event>slow_query).*?'
    r'sql=(?P<sql>.*?)\s+'
    r'sql_hash=(?P<sql_hash>\d+).*?'
    r'duration_ms=(?P<duration_ms>[\d.]+).*?'
    r'threshold_ms=(?P<threshold_ms>\d+).*?'
    r'operation=(?P<operation>\w+).*?'
    r'trace_id=(?P<trace_id>[^\s]+).*?'
    r'request_path=(?P<request_path>[^\s]+).*?'
    r'request_method=(?P<request_method>\w+)'
)

# JSON 格式日志解析
JSON_LOG_PATTERN = re.compile(r'^\{.*\}$')


def parse_json_log(line: str) -> Optional[dict]:
    """解析 JSON 格式日志"""
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def parse_slow_query_from_json(data: dict) -> Optional[SlowQuery]:
    """从 JSON 日志解析慢查询"""
    if data.get('event') != 'slow_query':
        return None

    return SlowQuery(
        timestamp=data.get('asctime', data.get('timestamp', '')),
        sql=data.get('sql', ''),
        sql_hash=data.get('sql_hash', hash(data.get('sql', ''))),
        duration_ms=float(data.get('duration_ms', 0)),
        threshold_ms=int(data.get('threshold_ms', 100)),
        operation=data.get('operation', 'OTHER'),
        trace_id=data.get('trace_id', '-'),
        request_path=data.get('request_path', ''),
        request_method=data.get('request_method', ''),
    )


def parse_slow_query_from_text(line: str) -> Optional[SlowQuery]:
    """从文本日志解析慢查询"""
    # 尝试 JSON 解析
    if JSON_LOG_PATTERN.match(line.strip()):
        data = parse_json_log(line)
        if data:
            return parse_slow_query_from_json(data)

    # 尝试正则解析
    match = SLOW_QUERY_PATTERN.search(line)
    if not match:
        return None

    return SlowQuery(
        timestamp='',  # 文本格式可能没有时间戳
        sql=match.group('sql')[:500],
        sql_hash=int(match.group('sql_hash')),
        duration_ms=float(match.group('duration_ms')),
        threshold_ms=int(match.group('threshold_ms')),
        operation=match.group('operation'),
        trace_id=match.group('trace_id'),
        request_path=match.group('request_path'),
        request_method=match.group('request_method'),
    )


def normalize_sql_for_pattern(sql: str) -> str:
    """规范化 SQL 以便聚合模式"""
    from core.middleware.query_profiler import normalize_sql
    return normalize_sql(sql, max_length=150)


def analyze_log_file(
    log_path: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    operation_filter: Optional[str] = None,
) -> AnalysisReport:
    """
    分析日志文件

    Args:
        log_path: 日志文件路径
        start_time: 起始时间
        end_time: 结束时间
        operation_filter: 操作类型过滤（SELECT/INSERT/UPDATE/DELETE）

    Returns:
        分析报告
    """
    report = AnalysisReport()
    seen_traces = set()

    log_file = Path(log_path)
    if not log_file.exists():
        print(f"Error: Log file not found: {log_path}", file=sys.stderr)
        return report

    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            query = parse_slow_query_from_text(line)
            if not query:
                continue

            # 时间过滤
            if start_time and query.timestamp:
                try:
                    query_time = datetime.fromisoformat(query.timestamp)
                    if query_time < start_time:
                        continue
                except (ValueError, TypeError):
                    pass

            if end_time and query.timestamp:
                try:
                    query_time = datetime.fromisoformat(query.timestamp)
                    if query_time > end_time:
                        continue
                except (ValueError, TypeError):
                    pass

            # 操作类型过滤
            if operation_filter and query.operation != operation_filter.upper():
                continue

            # 更新统计
            report.total_slow_queries += 1
            report.total_slow_query_time_ms += query.duration_ms
            seen_traces.add(query.trace_id)

            # 操作类型统计
            report.operation_counts[query.operation] = (
                report.operation_counts.get(query.operation, 0) + 1
            )

            # 模式统计
            pattern_key = normalize_sql_for_pattern(query.sql)
            if pattern_key not in report.patterns:
                report.patterns[pattern_key] = QueryPattern(pattern=pattern_key)

            report.patterns[pattern_key].add(query.duration_ms, query.timestamp)

    report.requests_with_slow_queries = len(seen_traces)
    return report


def print_report(report: AnalysisReport, top_n: int = 20) -> None:
    """打印分析报告"""
    print("\n" + "=" * 60)
    print("           Slow Query Analysis Report")
    print("=" * 60)

    print(f"\n📊 Overall Statistics:")
    print(f"   Total slow queries:     {report.total_slow_queries:,}")
    print(f"   Total slow query time:  {report.total_slow_query_time_ms:.1f} ms")
    print(f"   Requests affected:      {report.requests_with_slow_queries:,}")
    print(f"   Avg per request:        {report.total_slow_query_time_ms / report.requests_with_slow_queries:.1f} ms" if report.requests_with_slow_queries > 0 else "")

    print(f"\n🔍 By Operation Type:")
    for op, count in sorted(report.operation_counts.items(), key=lambda x: x[1], reverse=True):
        percentage = (count / report.total_slow_queries * 100) if report.total_slow_queries > 0 else 0
        print(f"   {op:8s}: {count:6,d} ({percentage:5.1f}%)")

    print(f"\n🐌 Top {top_n} Slowest Query Patterns:")
    print("-" * 60)

    sorted_patterns = sorted(
        report.patterns.values(),
        key=lambda p: p.total_ms,
        reverse=True
    )[:top_n]

    for i, pattern in enumerate(sorted_patterns, 1):
        print(f"\n   #{i}. {pattern.pattern}")
        print(f"       Count:   {pattern.count:,}")
        print(f"       Total:   {pattern.total_ms:.1f} ms")
        print(f"       Average: {pattern.avg_ms:.1f} ms")
        print(f"       Max:     {pattern.max_ms:.1f} ms")
        if pattern.first_seen and pattern.last_seen:
            print(f"       Time:    {pattern.first_seen} ~ {pattern.last_seen}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description='Analyze slow queries from Django logs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/analyze_slow_queries.py logs/django.log
  python scripts/analyze_slow_queries.py logs/django.log --top 10
  python scripts/analyze_slow_queries.py logs/django.log --operation SELECT --json
  python scripts/analyze_slow_queries.py logs/django.log --start "2026-03-01" --end "2026-03-02"
        """
    )

    parser.add_argument(
        'log_file',
        help='Path to the log file'
    )
    parser.add_argument(
        '--start',
        help='Start time (ISO format or YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end',
        help='End time (ISO format or YYYY-MM-DD)'
    )
    parser.add_argument(
        '--operation',
        choices=['SELECT', 'INSERT', 'UPDATE', 'DELETE'],
        help='Filter by operation type'
    )
    parser.add_argument(
        '--top',
        type=int,
        default=20,
        help='Number of top patterns to show (default: 20)'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output in JSON format'
    )

    args = parser.parse_args()

    # 解析时间
    start_time = None
    end_time = None

    if args.start:
        try:
            start_time = datetime.fromisoformat(args.start)
        except ValueError:
            # 尝试 YYYY-MM-DD 格式
            start_time = datetime.strptime(args.start, '%Y-%m-%d')

    if args.end:
        try:
            end_time = datetime.fromisoformat(args.end)
        except ValueError:
            end_time = datetime.strptime(args.end, '%Y-%m-%d')
            end_time = end_time.replace(hour=23, minute=59, second=59)

    # 分析日志
    report = analyze_log_file(
        args.log_file,
        start_time=start_time,
        end_time=end_time,
        operation_filter=args.operation,
    )

    # 输出结果
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print_report(report, top_n=args.top)


if __name__ == '__main__':
    main()
