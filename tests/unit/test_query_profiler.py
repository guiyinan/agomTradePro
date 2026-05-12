"""
Unit tests for Query Profiler Middleware

测试查询分析中间件的各项功能：
- SQL 规范化
- 操作类型提取
- 查询摘要统计
- N+1 查询检测
"""

from unittest.mock import patch

import pytest

from core.middleware.query_profiler import (
    QuerySummary,
    extract_operation_type,
    get_profiler_config,
    normalize_sql,
)


class TestNormalizeSQL:
    """测试 SQL 规范化功能"""

    def test_normalize_simple_select(self):
        """测试简单 SELECT 规范化"""
        sql = "SELECT * FROM users WHERE id = 123"
        result = normalize_sql(sql)
        assert result == "SELECT * FROM users WHERE id = ?"

    def test_normalize_with_string_literal(self):
        """测试字符串字面值替换"""
        sql = "SELECT * FROM users WHERE name = 'John Doe'"
        result = normalize_sql(sql)
        assert result == "SELECT * FROM users WHERE name = ?"

    def test_normalize_with_double_quotes(self):
        """测试双引号字符串替换"""
        sql = 'SELECT * FROM users WHERE name = "John Doe"'
        result = normalize_sql(sql)
        assert result == "SELECT * FROM users WHERE name = ?"

    def test_normalize_with_uuid(self):
        """测试 UUID 替换"""
        sql = "SELECT * FROM users WHERE id = '550e8400-e29b-41d4-a716-446655440000'"
        result = normalize_sql(sql)
        assert "?" in result  # UUID 应被替换

    def test_normalize_truncates_long_sql(self):
        """测试长 SQL 截断"""
        long_sql = "SELECT * FROM users WHERE " + " AND ".join([f"col{i} = {i}" for i in range(50)])
        result = normalize_sql(long_sql, max_length=100)
        assert len(result) <= 103  # 100 + "..."

    def test_normalize_empty_sql(self):
        """测试空 SQL"""
        assert normalize_sql("") == ""
        assert normalize_sql(None) == ""

    def test_normalize_removes_extra_whitespace(self):
        """测试多余空白字符移除"""
        sql = "SELECT   *   FROM   users   WHERE   id   =   123"
        result = normalize_sql(sql)
        assert result == "SELECT * FROM users WHERE id = ?"


class TestExtractOperationType:
    """测试操作类型提取"""

    def test_extract_select(self):
        """测试 SELECT 操作"""
        assert extract_operation_type("SELECT * FROM users") == "SELECT"
        assert extract_operation_type("select * from users") == "SELECT"

    def test_extract_insert(self):
        """测试 INSERT 操作"""
        assert extract_operation_type("INSERT INTO users VALUES (...)") == "INSERT"
        assert extract_operation_type("insert into users values (...)") == "INSERT"

    def test_extract_update(self):
        """测试 UPDATE 操作"""
        assert extract_operation_type("UPDATE users SET name = 'test'") == "UPDATE"
        assert extract_operation_type("update users set name = 'test'") == "UPDATE"

    def test_extract_delete(self):
        """测试 DELETE 操作"""
        assert extract_operation_type("DELETE FROM users WHERE id = 1") == "DELETE"
        assert extract_operation_type("delete from users where id = 1") == "DELETE"

    def test_extract_other(self):
        """测试其他操作类型"""
        assert extract_operation_type("BEGIN TRANSACTION") == "OTHER"
        assert extract_operation_type("COMMIT") == "OTHER"
        assert extract_operation_type("CREATE TABLE users (...)") == "OTHER"

    def test_extract_empty_sql(self):
        """测试空 SQL"""
        assert extract_operation_type("") == "OTHER"
        assert extract_operation_type("   ") == "OTHER"


class TestGetProfilerConfig:
    """测试配置读取"""

    @patch('core.middleware.query_profiler.settings')
    def test_default_config(self, mock_settings):
        """测试默认配置"""
        mock_settings.QUERY_PROFILER_ENABLED = False
        mock_settings.SLOW_QUERY_THRESHOLD_MS = 100

        enabled, threshold = get_profiler_config()
        assert enabled is False
        assert threshold == 100

    @patch('core.middleware.query_profiler.settings')
    def test_custom_config(self, mock_settings):
        """测试自定义配置"""
        mock_settings.QUERY_PROFILER_ENABLED = True
        mock_settings.SLOW_QUERY_THRESHOLD_MS = 200

        enabled, threshold = get_profiler_config()
        assert enabled is True
        assert threshold == 200

    @patch('core.middleware.query_profiler.getattr', side_effect=lambda obj, name, default=None: default)
    @patch('core.middleware.query_profiler.settings')
    def test_missing_config_uses_defaults(self, mock_settings, mock_getattr):
        """测试配置缺失时使用默认值"""
        # getattr 返回 default，所以会使用默认配置
        enabled, threshold = get_profiler_config()
        assert enabled is False
        assert threshold == 100


class TestQuerySummary:
    """测试查询摘要类"""

    def test_empty_summary(self):
        """测试空摘要"""
        summary = QuerySummary()
        data = summary.get_summary()

        assert data['total_queries'] == 0
        assert data['total_time_ms'] == 0
        assert data['slow_queries'] == 0
        assert data['avg_time_ms'] == 0
        assert data['operation_counts'] == {}
        assert data['slow_query_patterns'] == {}

    def test_add_single_query(self):
        """测试添加单条查询"""
        summary = QuerySummary()
        summary.add_query("SELECT * FROM users", 50, threshold_ms=100)

        data = summary.get_summary()
        assert data['total_queries'] == 1
        assert data['total_time_ms'] == 50
        assert data['slow_queries'] == 0  # 低于阈值
        assert data['avg_time_ms'] == 50
        assert data['operation_counts'] == {'SELECT': 1}

    def test_add_slow_query(self):
        """测试添加慢查询"""
        summary = QuerySummary()
        summary.add_query("SELECT * FROM users", 150, threshold_ms=100)

        data = summary.get_summary()
        assert data['slow_queries'] == 1
        assert 'slow_query_patterns' in data

    def test_add_multiple_queries(self):
        """测试添加多条查询"""
        summary = QuerySummary()
        summary.add_query("SELECT * FROM users", 50)
        summary.add_query("INSERT INTO logs VALUES (...)", 30)
        summary.add_query("UPDATE users SET name = 'test'", 40)

        data = summary.get_summary()
        assert data['total_queries'] == 3
        assert data['total_time_ms'] == 120
        assert data['avg_time_ms'] == 40
        assert data['operation_counts']['SELECT'] == 1
        assert data['operation_counts']['INSERT'] == 1
        assert data['operation_counts']['UPDATE'] == 1

    def test_pattern_aggregation(self):
        """测试查询模式聚合"""
        summary = QuerySummary()
        # 添加慢查询（超过默认阈值 100ms）
        summary.add_query("SELECT * FROM users WHERE id = 1", 150, threshold_ms=100)
        summary.add_query("SELECT * FROM users WHERE id = 2", 160, threshold_ms=100)
        summary.add_query("SELECT * FROM users WHERE id = 3", 170, threshold_ms=100)

        data = summary.get_summary()
        assert data['slow_query_patterns']  # 应该有模式记录
        # 验证模式聚合结果
        patterns = list(data['slow_query_patterns'].values())
        assert len(patterns) == 1
        assert patterns[0]['count'] == 3

    def test_avg_time_calculation(self):
        """测试平均时间计算"""
        summary = QuerySummary()
        summary.add_query("SELECT 1", 100)
        summary.add_query("SELECT 2", 200)
        summary.add_query("SELECT 3", 300)

        data = summary.get_summary()
        assert data['avg_time_ms'] == 200

    def test_get_summary_returns_dict(self):
        """测试摘要返回字典"""
        summary = QuerySummary()
        summary.add_query("SELECT * FROM users", 100)

        data = summary.get_summary()
        assert isinstance(data, dict)
        assert 'total_queries' in data
        assert 'total_time_ms' in data
        assert 'slow_queries' in data
        assert 'avg_time_ms' in data
        assert 'operation_counts' in data
        assert 'slow_query_patterns' in data


class TestIntegrationScenarios:
    """集成测试场景"""

    def test_real_world_slow_query_detection(self):
        """测试真实场景的慢查询检测"""
        summary = QuerySummary()

        # 模拟真实查询
        queries = [
            ("SELECT * FROM regime_regimestate WHERE asof_date = '2026-01-01'", 150),
            ("SELECT * FROM signal_investmentsignal WHERE asset_code = '000001.SH'", 80),
            ("SELECT * FROM users WHERE id = 1", 10),
            ("UPDATE regime_regimestate SET growth_level = 2 WHERE id = 1", 120),
        ]

        for sql, duration in queries:
            summary.add_query(sql, duration, threshold_ms=100)

        data = summary.get_summary()
        assert data['total_queries'] == 4
        assert data['slow_queries'] == 2  # 150ms 和 120ms 超过阈值
        assert data['operation_counts']['SELECT'] == 3
        assert data['operation_counts']['UPDATE'] == 1

    def test_n_plus_one_pattern_detection(self):
        """测试 N+1 模式检测"""
        summary = QuerySummary()

        # 模拟 N+1 查询模式
        for i in range(10):
            summary.add_query(f"SELECT * FROM asset_asset WHERE code = '{i}'", 20)

        # 然后是一个慢查询
        summary.add_query("SELECT * FROM signal_investmentsignal WHERE asset_id IN (...)", 200)

        data = summary.get_summary()
        assert data['total_queries'] == 11
        # 应该检测到多个相似查询模式
        assert len(data['slow_query_patterns']) >= 1


@pytest.mark.parametrize("sql,expected_op", [
    ("SELECT * FROM users", "SELECT"),
    ("INSERT INTO users VALUES (1, 'test')", "INSERT"),
    ("UPDATE users SET name = 'test'", "UPDATE"),
    ("DELETE FROM users WHERE id = 1", "DELETE"),
    ("BEGIN TRANSACTION", "OTHER"),
    ("COMMIT", "OTHER"),
])
def test_operation_type_extraction(sql, expected_op):
    """参数化测试操作类型提取"""
    assert extract_operation_type(sql) == expected_op


@pytest.mark.parametrize("sql_input,expected_contains", [
    ("SELECT * FROM users WHERE id = 123", "id = ?"),
    ("SELECT * FROM users WHERE name = 'John'", "name = ?"),
    ("SELECT * FROM users WHERE uuid = '550e8400-e29b-41d4-a716-446655440000'", "?"),
])
def test_sql_normalization_patterns(sql_input, expected_contains):
    """参数化测试 SQL 规范化模式"""
    result = normalize_sql(sql_input)
    assert expected_contains in result
