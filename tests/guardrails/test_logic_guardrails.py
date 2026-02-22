from datetime import datetime, date
from pathlib import Path
import uuid

import pytest

from apps.policy.application.use_cases import FetchRSSUseCase
from apps.policy.domain.entities import PolicyEvent, PolicyLevel, RSSItem
from apps.policy.infrastructure.models import PolicyLog, RSSSourceConfigModel
from apps.policy.infrastructure.repositories import DjangoPolicyRepository


class _DummyAdapter:
    def __init__(self, items):
        self._items = items

    def fetch(self, _source_config):
        return self._items


class _DummyRSSRepo:
    def is_item_exists(self, link, guid):
        return False

    def get_active_keyword_rules(self, category=None):
        return []

    def save_fetch_log(self, **kwargs):
        return kwargs

    def update_source_last_fetch(self, source_id, status, error_msg=None):
        return (source_id, status, error_msg)


class _MatcherRaises:
    def __init__(self, _rules):
        pass

    def match(self, _item):
        raise RuntimeError("forced matcher failure")


@pytest.mark.guardrail
@pytest.mark.django_db
def test_guardrail_no_data_loss_when_processing_fails():
    """
    护栏：处理链路异常时，原始数据必须保留（两阶段入库）。
    """
    unique = uuid.uuid4().hex[:8]
    guid = f"guardrail-fail-{unique}"
    source = RSSSourceConfigModel.objects.create(
        name=f"guardrail-src-{unique}",
        url=f"https://source.example.com/{unique}.xml",
        category="other",
        parser_type="feedparser",
        extract_content=False,
        is_active=True,
    )

    use_case = FetchRSSUseCase(
        rss_repository=_DummyRSSRepo(),
        policy_repository=DjangoPolicyRepository(),
        ai_classifier=None,
    )
    use_case._matcher_class = _MatcherRaises
    use_case._adapter_factory = {
        "feedparser": _DummyAdapter([
            RSSItem(
                title=f"title-{unique}",
                link=f"https://example.com/{unique}",
                guid=guid,
                pub_date=datetime.now(),
                description="desc",
            )
        ])
    }

    result = use_case._fetch_single_source(source, force_refetch=False)
    assert result["new_events_count"] == 1

    saved = PolicyLog.objects.get(rss_item_guid=guid)
    assert saved.level == "PX"
    assert saved.processing_metadata.get("processing_stage") == "failed"
    assert saved.processing_metadata.get("saved_as_pending") is True


@pytest.mark.guardrail
def test_guardrail_regime_threshold_not_hardcoded_in_critical_path():
    """
    护栏：关键路径不能出现已知阈值硬编码回归。
    """
    content = Path("apps/regime/application/use_cases.py").read_text(encoding="utf-8")
    assert "spread_bp > 100" not in content
    assert "us_yield > 4.5" not in content


@pytest.mark.guardrail
@pytest.mark.django_db
def test_diagnostic_repository_should_not_merge_distinct_same_day_events():
    """
    诊断：同日不同政策事件不应互相覆盖。

    该用例是强约束：防止 save_event 退回“按日期覆盖”。
    """
    PolicyLog._default_manager.all().delete()
    repo = DjangoPolicyRepository()
    event_date = datetime.now().date()

    repo.save_event(
        PolicyEvent(
            event_date=event_date,
            level=PolicyLevel.P1,
            title="事件A",
            description="描述A",
            evidence_url="https://example.com/a",
        )
    )
    repo.save_event(
        PolicyEvent(
            event_date=event_date,
            level=PolicyLevel.P2,
            title="事件B",
            description="描述B",
            evidence_url="https://example.com/b",
        )
    )

    assert PolicyLog._default_manager.filter(event_date=event_date).count() == 2


@pytest.mark.guardrail
def test_guardrail_policy_routes_no_conflict():
    """
    护栏：Policy 路由中 events/ 不能同时被 HTML 和 API 使用。

    防止 API 请求返回 HTML 页面的路由冲突回归。
    """
    urls_content = Path("apps/policy/interface/urls.py").read_text(encoding="utf-8")
    lines = urls_content.split('\n')

    events_routes = []
    for i, line in enumerate(lines, 1):
        if 'path("events/"' in line or "path('events/'" in line:
            events_routes.append((i, line.strip()))

    # events/ 路由应该只出现一次（HTML 页面）
    assert len(events_routes) == 1, f"events/ 路由重复定义: {events_routes}"


@pytest.mark.guardrail
def test_guardrail_backtest_monthly_rebalance_december_boundary():
    """
    护栏：Backtest 月度调仓 12 月边界计算正确。

    12 月的下一个月应该是次年 1 月，不是同年 12 月。
    """
    from apps.backtest.domain.services import BacktestEngine
    from apps.backtest.domain.entities import BacktestConfig

    # 测试 12 月边界
    config = BacktestConfig(
        start_date=date(2024, 12, 1),
        end_date=date(2025, 2, 1),
        initial_capital=100000,
        rebalance_frequency="monthly",
        use_pit_data=True,
    )
    # 创建一个最小化的引擎实例，只测试日期生成
    engine = object.__new__(BacktestEngine)
    engine.config = config

    dates = engine._generate_rebalance_dates()

    # 应该包含 2025-01-01
    assert date(2025, 1, 1) in dates, f"12月边界错误，缺失 2025-01-01，实际: {dates}"


@pytest.mark.guardrail
def test_guardrail_audit_uses_correct_regime_names():
    """
    护栏：Audit 模块必须使用 Domain 层定义的 Regime 名称。

    正确名称: Recovery, Overheat, Stagflation, Deflation
    错误名称: GROWTH, REFLATION, RECESSION, STAGFLATION
    """
    audit_content = Path("apps/audit/application/use_cases.py").read_text(encoding="utf-8")

    # 检查不应出现的旧名称
    wrong_names = ["'GROWTH'", "'REFLATION'", "'RECESSION'", "'STAGFLATION'",
                   '"GROWTH"', '"REFLATION"', '"RECESSION"', '"STAGFLATION"']

    for wrong in wrong_names:
        assert wrong not in audit_content, f"Audit 使用了错误的 Regime 名称: {wrong}"


@pytest.mark.guardrail
@pytest.mark.django_db
def test_guardrail_policy_repository_has_delete_by_id():
    """
    护栏：Policy 仓储必须提供 delete_event_by_id 方法。

    防止按日期删除导致同日多事件误删。
    """
    from apps.policy.infrastructure.repositories import DjangoPolicyRepository

    repo = DjangoPolicyRepository()
    assert hasattr(repo, 'delete_event_by_id'), "DjangoPolicyRepository 缺少 delete_event_by_id 方法"


@pytest.mark.guardrail
@pytest.mark.django_db
def test_guardrail_policy_repository_has_get_events_by_date():
    """
    护栏：Policy 仓储必须提供 get_events_by_date 方法。

    防止同日多事件场景丢失数据。
    """
    from apps.policy.infrastructure.repositories import DjangoPolicyRepository

    repo = DjangoPolicyRepository()
    assert hasattr(repo, 'get_events_by_date'), "DjangoPolicyRepository 缺少 get_events_by_date 方法"


@pytest.mark.guardrail
def test_guardrail_regime_view_safe_data_source_access():
    """
    护栏：Regime 视图必须安全访问数据源配置。

    防止空表时 first().source_type 导致 AttributeError。
    """
    views_content = Path("apps/regime/interface/views.py").read_text(encoding="utf-8")

    # 不应出现不安全的链式访问模式
    unsafe_pattern = ".first().source_type if .exists()"
    assert unsafe_pattern not in views_content, "Regime 视图使用了不安全的数据源访问模式"


