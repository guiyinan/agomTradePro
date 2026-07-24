"""Decision Rhythm domain service regression tests."""

from datetime import UTC, datetime, timedelta

from apps.decision_rhythm.domain.entities import (
    CooldownPeriod,
    DecisionPriority,
    DecisionQuota,
    DecisionRequest,
    QuotaPeriod,
)
from apps.decision_rhythm.domain.services import DecisionScheduler, RhythmManager
from apps.decision_rhythm.infrastructure.models import (
    CooldownPeriodModel,
    DecisionQuotaModel,
    DecisionResponseModel,
)


def _request(request_id: str, requested_at: datetime) -> DecisionRequest:
    """Build a deterministic request for scheduler tests."""
    return DecisionRequest(
        request_id=request_id,
        asset_code=f"{request_id}.SH",
        asset_class="equity",
        direction="BUY",
        priority=DecisionPriority.HIGH,
        requested_at=requested_at,
    )


def test_scheduler_uses_fifo_within_the_same_priority() -> None:
    """Older requests must not be starved by newer equal-priority work."""
    scheduler = DecisionScheduler()
    now = datetime.now(UTC)
    older = _request("older", now - timedelta(minutes=5))
    newer = _request("newer", now)

    assert scheduler.add_request(newer) is True
    assert scheduler.add_request(older) is True

    selected = scheduler.get_next()

    assert selected is older


def test_response_keeps_structured_quota_snapshot_and_aware_timestamps() -> None:
    """Approval responses preserve JSON quota details and timezone awareness."""
    request = DecisionRequest(
        request_id="request-1",
        asset_code="000001.SH",
        asset_class="equity",
        direction="BUY",
        priority=DecisionPriority.HIGH,
    )

    response = RhythmManager().submit_request(request, QuotaPeriod.WEEKLY)

    assert response.quota_status is not None
    assert response.quota_status["period"] == QuotaPeriod.WEEKLY.value
    assert request.requested_at.tzinfo is not None
    assert response.responded_at.tzinfo is not None


def test_orm_factories_generate_missing_business_ids() -> None:
    """Optional Domain IDs must not become NULL in required ORM fields."""
    quota_model = DecisionQuotaModel.from_domain(
        DecisionQuota(
            period=QuotaPeriod.DAILY,
            max_decisions=5,
            max_execution_count=3,
        )
    )
    cooldown_model = CooldownPeriodModel.from_domain(CooldownPeriod(asset_code="000001.SH"))

    assert quota_model.quota_id.startswith("quota_")
    assert cooldown_model.cooldown_id.startswith("cooldown_")


def test_response_mapper_uses_domain_request_business_id() -> None:
    """A response must expose the request business ID, not its database PK."""
    request = _request("request-business-id", datetime.now(UTC))
    response_model = DecisionResponseModel(
        request_id=42,
        approved=True,
        approval_reason="approved",
        quota_status={"period": QuotaPeriod.WEEKLY.value},
        responded_at=datetime.now(UTC),
    )

    response = response_model.to_domain(request)

    assert response.request_id == request.request_id
    assert response.quota_status == {"period": QuotaPeriod.WEEKLY.value}
