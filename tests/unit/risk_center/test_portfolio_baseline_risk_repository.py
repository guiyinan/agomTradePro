"""Database contract tests for explicit, read-only baseline row resolution."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.risk_center.application.portfolio_baseline_risk import (
    PortfolioBaselinePolicyReadResult,
)
from apps.risk_center.infrastructure.models import (
    AccountRiskPolicyModel,
    GlobalRiskFloorModel,
    RiskExceptionModel,
    RiskTemplateModel,
)
from apps.risk_center.infrastructure.portfolio_baseline_risk_repository import (
    DjangoPortfolioBaselinePolicyReader,
)


def _seed(
    account_id: int = 71,
) -> tuple[GlobalRiskFloorModel, RiskTemplateModel, AccountRiskPolicyModel]:
    floor = GlobalRiskFloorModel.objects.create(
        name="test floor",
        is_active=True,
        max_total_position_pct=0.7,
        max_single_position_pct=0.7,
        min_cash_pct=0.1,
        hard_exclusions=["FLOOR"],
    )
    template = RiskTemplateModel.objects.create(
        key=f"baseline-test-{account_id}",
        name="test template",
        risk_profile=RiskTemplateModel.MODERATE,
        is_active=True,
        max_total_position_pct=0.8,
        max_single_position_pct=0.5,
        min_cash_pct=0.2,
        hard_exclusions=["TEMPLATE"],
    )
    account = AccountRiskPolicyModel.objects.create(
        account_id=account_id,
        template=template,
        risk_profile=RiskTemplateModel.MODERATE,
        is_active=True,
        max_total_position_pct=None,
        max_single_position_pct=None,
        min_cash_pct=None,
        hard_exclusions=[],
    )
    return floor, template, account


def _as_of_after_writes() -> datetime:
    return timezone.now() + timedelta(seconds=5)


def _exception(
    *,
    account_id: int | None,
    field_name: str = "max_total_position_pct",
    allowed_value: object = 0.95,
    expires_at: datetime | None = None,
) -> RiskExceptionModel:
    actor = get_user_model().objects.create_user(
        username=f"risk-reader-{RiskExceptionModel.objects.count()}"
    )
    return RiskExceptionModel.objects.create(
        account_id=account_id,
        field_name=field_name,
        allowed_value=allowed_value,
        reason="explicit test authorization",
        created_by=actor,
        expires_at=expires_at or timezone.now() + timedelta(days=1),
        is_active=True,
    )


@pytest.mark.django_db
def test_missing_floor_returns_typed_unknown_without_creating_defaults() -> None:
    reader = DjangoPortfolioBaselinePolicyReader(using="default")
    before = (
        GlobalRiskFloorModel.objects.count(),
        RiskTemplateModel.objects.count(),
        AccountRiskPolicyModel.objects.count(),
    )

    result = reader.read_baseline_policy(account_id=71, as_of=_as_of_after_writes())

    after = (
        GlobalRiskFloorModel.objects.count(),
        RiskTemplateModel.objects.count(),
        AccountRiskPolicyModel.objects.count(),
    )
    assert result.policy is None
    assert result.reason_codes == ("PORTFOLIO_BASELINE_FLOOR_MISSING_OR_AMBIGUOUS",)
    assert before == after == (0, 0, 0)


@pytest.mark.django_db
def test_multiple_active_floors_block_before_account_or_template_resolution() -> None:
    GlobalRiskFloorModel.objects.create(name="floor one", is_active=True)
    GlobalRiskFloorModel.objects.create(name="floor two", is_active=True)

    result = DjangoPortfolioBaselinePolicyReader(using="default").read_baseline_policy(
        account_id=71,
        as_of=_as_of_after_writes(),
    )

    assert result.policy is None
    assert result.reason_codes == ("PORTFOLIO_BASELINE_FLOOR_MISSING_OR_AMBIGUOUS",)
    assert AccountRiskPolicyModel.objects.count() == 0


@pytest.mark.django_db
def test_fallback_template_resolution_rejects_multiple_active_profile_rows() -> None:
    GlobalRiskFloorModel.objects.create(name="floor", is_active=True)
    RiskTemplateModel.objects.create(
        key="fallback-one", name="one", risk_profile=RiskTemplateModel.MODERATE
    )
    RiskTemplateModel.objects.create(
        key="fallback-two", name="two", risk_profile=RiskTemplateModel.MODERATE
    )
    AccountRiskPolicyModel.objects.create(
        account_id=71,
        template=None,
        risk_profile=RiskTemplateModel.MODERATE,
        is_active=True,
    )

    result = DjangoPortfolioBaselinePolicyReader(using="default").read_baseline_policy(
        account_id=71,
        as_of=_as_of_after_writes(),
    )

    assert result.policy is None
    assert result.reason_codes == ("PORTFOLIO_BASELINE_TEMPLATE_MISSING_OR_AMBIGUOUS",)


@pytest.mark.django_db
def test_no_template_and_no_profile_candidate_is_unknown() -> None:
    GlobalRiskFloorModel.objects.create(name="floor", is_active=True)
    AccountRiskPolicyModel.objects.create(account_id=71, is_active=True)

    result = DjangoPortfolioBaselinePolicyReader(using="default").read_baseline_policy(
        account_id=71,
        as_of=_as_of_after_writes(),
    )

    assert result.policy is None
    assert result.reason_codes == ("PORTFOLIO_BASELINE_TEMPLATE_MISSING_OR_AMBIGUOUS",)


@pytest.mark.django_db
def test_baseline_values_use_explicit_rows_and_stable_whole_binding_digest() -> None:
    _, template, _ = _seed()
    reader = DjangoPortfolioBaselinePolicyReader(using="default")
    as_of = _as_of_after_writes()

    first = reader.read_baseline_policy(account_id=71, as_of=as_of)
    same = reader.read_baseline_policy(account_id=71, as_of=as_of)

    assert isinstance(first, PortfolioBaselinePolicyReadResult)
    assert first.policy is not None and same.policy is not None
    assert first.reason_codes == same.reason_codes == ()
    # The existing resolver applies the active global upper-bound floor first.
    assert first.policy.max_total_weight == Decimal("0.7")
    assert first.policy.max_single_weight == Decimal("0.5")
    assert first.policy.min_cash_weight == Decimal("0.2")
    assert first.policy.hard_exclusions == ("FLOOR", "TEMPLATE")
    assert first.policy.content_sha256 == same.policy.content_sha256
    assert first.policy.known_at == max(
        template.created_at,
        template.updated_at,
        GlobalRiskFloorModel.objects.get().updated_at,
        AccountRiskPolicyModel.objects.get().updated_at,
    )

    template.min_cash_pct = 0.25
    template.save(update_fields=("min_cash_pct", "updated_at"))
    changed = reader.read_baseline_policy(account_id=71, as_of=_as_of_after_writes())

    assert changed.policy is not None
    assert changed.policy.min_cash_weight == Decimal("0.25")
    assert changed.policy.content_sha256 != first.policy.content_sha256


@pytest.mark.django_db
def test_active_scoped_exception_relaxes_only_its_matching_floor_and_changes_digest() -> None:
    _seed()
    reader = DjangoPortfolioBaselinePolicyReader(using="default")
    baseline = reader.read_baseline_policy(account_id=71, as_of=_as_of_after_writes())
    active = _exception(account_id=71, allowed_value=0.75)
    qualified = reader.read_baseline_policy(account_id=71, as_of=_as_of_after_writes())

    assert active.pk is not None
    assert baseline.policy is not None and qualified.policy is not None
    assert baseline.policy.max_total_weight == Decimal("0.7")
    assert qualified.policy.max_total_weight == Decimal("0.75")
    assert qualified.policy.content_sha256 != baseline.policy.content_sha256
    assert qualified.policy.effective_until == active.expires_at


@pytest.mark.django_db
def test_expired_and_other_account_exceptions_do_not_change_current_binding() -> None:
    _seed()
    reader = DjangoPortfolioBaselinePolicyReader(using="default")
    as_of = _as_of_after_writes()
    baseline = reader.read_baseline_policy(account_id=71, as_of=as_of)
    _exception(
        account_id=72,
        expires_at=as_of + timedelta(days=1),
    )
    _exception(
        account_id=71,
        expires_at=as_of - timedelta(seconds=1),
    )
    later = as_of + timedelta(seconds=2)
    current = reader.read_baseline_policy(account_id=71, as_of=later)

    assert baseline.policy is not None and current.policy is not None
    assert current.policy.max_total_weight == baseline.policy.max_total_weight
    assert current.policy.content_sha256 == baseline.policy.content_sha256
    assert current.policy.effective_until is None


@pytest.mark.django_db
def test_duplicate_active_account_and_global_exceptions_block_as_ambiguous() -> None:
    _seed()
    _exception(account_id=None, allowed_value=0.9)
    _exception(account_id=71, allowed_value=0.95)

    result = DjangoPortfolioBaselinePolicyReader(using="default").read_baseline_policy(
        account_id=71,
        as_of=_as_of_after_writes(),
    )

    assert result.policy is None
    assert result.reason_codes == ("PORTFOLIO_BASELINE_SOURCE_INVALID_OR_AMBIGUOUS",)


@pytest.mark.django_db
def test_future_source_clock_blocks_and_invalid_alias_returns_typed_reason() -> None:
    _seed()
    before_writes = timezone.now() - timedelta(seconds=1)
    future = DjangoPortfolioBaselinePolicyReader(using="default").read_baseline_policy(
        account_id=71,
        as_of=before_writes,
    )
    missing_alias = DjangoPortfolioBaselinePolicyReader(
        using="not-configured"
    ).read_baseline_policy(
        account_id=71,
        as_of=_as_of_after_writes(),
    )

    assert future.policy is None
    assert future.reason_codes == ("PORTFOLIO_BASELINE_SOURCE_AFTER_CUTOFF",)
    assert missing_alias.policy is None
    assert missing_alias.reason_codes == ("PORTFOLIO_BASELINE_DATABASE_UNAVAILABLE",)


@pytest.mark.django_db
def test_invalid_source_value_is_typed_unknown_not_a_fallback_limit() -> None:
    floor, _, _ = _seed()
    floor.max_total_position_pct = 1.01
    floor.save(update_fields=("max_total_position_pct", "updated_at"))

    result = DjangoPortfolioBaselinePolicyReader(using="default").read_baseline_policy(
        account_id=71,
        as_of=_as_of_after_writes(),
    )

    assert result.policy is None
    assert result.reason_codes == ("PORTFOLIO_BASELINE_SOURCE_INVALID_OR_AMBIGUOUS",)
