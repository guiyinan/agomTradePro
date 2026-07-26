"""Boundary tests for Sentiment normalization and Share access policy."""

from datetime import UTC, date, datetime

import pytest

from apps.sentiment.domain.entities import SentimentCategory, SentimentIndex
from apps.sentiment.domain.rules import (
    categorize_sentiment_score,
    clamp_sentiment_score,
)
from apps.sentiment.domain.services import build_sentiment_result
from apps.share.domain.account_gateway import EmptyShareAccountGateway
from apps.share.domain.entities import (
    AccessResultStatus,
    ShareAccessLogEntity,
    ShareConfig,
    ShareLevel,
    ShareLinkEntity,
    ShareSnapshotEntity,
    ShareStatus,
    ShareTheme,
)
from apps.share.domain.services import (
    generate_short_code,
    hash_ip_address,
    hash_password,
    validate_short_code,
    verify_password,
)


@pytest.mark.parametrize(
    ("score", "category"),
    [
        (0.51, SentimentCategory.POSITIVE),
        (0.5, SentimentCategory.NEUTRAL),
        (-0.5, SentimentCategory.NEUTRAL),
        (-0.51, SentimentCategory.NEGATIVE),
    ],
)
def test_sentiment_category_exact_thresholds(score: float, category: SentimentCategory) -> None:
    """Sentiment classification preserves strict thresholds."""
    assert categorize_sentiment_score(score) == category


def test_sentiment_result_clamps_score_confidence_and_uses_aware_time() -> None:
    """External model values cannot escape Domain ranges."""
    positive = build_sentiment_result(
        text="good",
        sentiment_score=9,
        confidence=2,
        keywords=["growth"],
    )
    assert positive.sentiment_score == 3.0
    assert positive.confidence == 1.0
    assert positive.category == SentimentCategory.POSITIVE
    assert positive.analyzed_at.tzinfo is UTC

    analyzed_at = datetime(2026, 7, 24, tzinfo=UTC)
    negative = build_sentiment_result(
        text="bad",
        sentiment_score=-9,
        confidence=-1,
        analyzed_at=analyzed_at,
        error_message="degraded model",
    )
    assert clamp_sentiment_score(-9) == -3.0
    assert negative.confidence == 0.0
    assert negative.keywords == []
    assert negative.analyzed_at is analyzed_at
    assert negative.error_message == "degraded model"


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), float("-inf")])
def test_sentiment_domain_rejects_non_finite_financial_values(
    invalid_value: float,
) -> None:
    """NaN and infinities cannot masquerade as valid sentiment data."""

    with pytest.raises(ValueError, match="finite"):
        build_sentiment_result(
            text="invalid",
            sentiment_score=invalid_value,
            confidence=0.5,
        )
    with pytest.raises(ValueError, match="finite"):
        build_sentiment_result(
            text="invalid",
            sentiment_score=0.0,
            confidence=invalid_value,
        )
    with pytest.raises(ValueError, match="有限数值"):
        SentimentIndex(
            index_date=datetime(2026, 7, 24, tzinfo=UTC),
            composite_index=invalid_value,
        )


def test_sentiment_index_rejects_invalid_confidence_sector_and_counts() -> None:
    """Index metadata must preserve its documented financial invariants."""

    index_date = datetime(2026, 7, 24, tzinfo=UTC)
    with pytest.raises(ValueError, match="confidence_level"):
        SentimentIndex(index_date=index_date, confidence_level=float("nan"))
    with pytest.raises(ValueError, match=r"sector_sentiment\[technology\]"):
        SentimentIndex(
            index_date=index_date,
            sector_sentiment={"technology": float("inf")},
        )
    with pytest.raises(ValueError, match="news_count"):
        SentimentIndex(index_date=index_date, news_count=-1)


def _link(
    *,
    status: ShareStatus = ShareStatus.ACTIVE,
    expires_at: datetime | None = None,
    max_access_count: int | None = None,
    access_count: int = 0,
    password_hash: str | None = None,
) -> ShareLinkEntity:
    """Build an account share link with explicit visibility."""
    now = datetime(2026, 7, 24, tzinfo=UTC)
    return ShareLinkEntity(
        id=1,
        owner_id=10,
        account_id=20,
        short_code="Abc12345",
        title="Portfolio",
        subtitle=None,
        theme=ShareTheme.BLOOMBERG,
        share_level=ShareLevel.SNAPSHOT,
        status=status,
        password_hash=password_hash,
        expires_at=expires_at,
        max_access_count=max_access_count,
        access_count=access_count,
        last_snapshot_at=None,
        last_accessed_at=None,
        allow_indexing=False,
        show_amounts=False,
        show_positions=True,
        show_transactions=False,
        show_decision_summary=True,
        show_decision_evidence=False,
        show_invalidation_logic=True,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        (
            _link(status=ShareStatus.REVOKED),
            AccessResultStatus.REVOKED,
        ),
        (
            _link(status=ShareStatus.EXPIRED),
            AccessResultStatus.EXPIRED,
        ),
        (
            _link(status=ShareStatus.DISABLED),
            AccessResultStatus.NOT_FOUND,
        ),
        (
            _link(expires_at=datetime(2026, 7, 23, tzinfo=UTC)),
            AccessResultStatus.EXPIRED,
        ),
        (
            _link(max_access_count=3, access_count=3),
            AccessResultStatus.MAX_COUNT_EXCEEDED,
        ),
    ],
)
def test_share_link_rejection_reasons_are_explicit(
    link: ShareLinkEntity, expected: AccessResultStatus
) -> None:
    """Revocation, expiry, disablement, and quotas remain distinguishable."""
    assert link.is_accessible(datetime(2026, 7, 24, tzinfo=UTC)) == (
        False,
        expected,
    )


def test_active_share_link_publishes_password_and_visibility_contracts() -> None:
    """Active links expose only configured fields and inclusive expiry."""
    expires_at = datetime(2026, 7, 24, tzinfo=UTC)
    link = _link(expires_at=expires_at, password_hash="hash")
    assert link.is_accessible(expires_at) == (
        True,
        AccessResultStatus.SUCCESS,
    )
    assert link.requires_password() is True
    assert link.get_visibility_config() == {
        "amounts": False,
        "positions": True,
        "transactions": False,
        "decision_summary": True,
        "decision_evidence": False,
        "invalidation_logic": True,
    }
    assert _link(password_hash="").requires_password() is False


def test_share_snapshot_access_log_and_config_value_objects() -> None:
    """Snapshot emptiness, audit success, and config flags are deterministic."""
    now = datetime(2026, 7, 24, tzinfo=UTC)
    empty = ShareSnapshotEntity(
        id=None,
        share_link_id=1,
        snapshot_version=1,
        summary_payload={},
        performance_payload={},
        positions_payload={},
        transactions_payload={},
        decision_payload={},
        generated_at=now,
        source_range_start=None,
        source_range_end=None,
    )
    populated = ShareSnapshotEntity(
        **{
            **empty.__dict__,
            "summary_payload": {"as_of_date": date(2026, 7, 24).isoformat()},
        }
    )
    assert empty.is_empty() is True
    assert populated.is_empty() is False

    log = ShareAccessLogEntity(
        id=None,
        share_link_id=1,
        accessed_at=now,
        ip_hash="sha256",
        user_agent=None,
        referer=None,
        is_verified=True,
        result_status=AccessResultStatus.SUCCESS,
    )
    assert log.is_successful_access() is True

    config = ShareConfig(title="Portfolio", password="secret", show_amounts=True)
    assert config.requires_password() is True
    assert config.get_visibility_flags()["show_amounts"] is True
    assert ShareConfig(title="Portfolio", password="").requires_password() is False


def test_share_code_generation_and_validation_contract() -> None:
    """Generated public codes are alphanumeric and format validation is strict."""
    code = generate_short_code(12)
    assert len(code) == 12
    assert validate_short_code(code) is True
    assert validate_short_code("") is False
    assert validate_short_code("abc") is False
    assert validate_short_code("a" * 33) is False
    assert validate_short_code("abc-123") is False


@pytest.mark.parametrize(
    ("callable_", "args", "message"),
    [
        (hash_password, ("secret",), "make_password"),
        (verify_password, ("secret", "hash"), "check_password"),
        (hash_ip_address, ("127.0.0.1",), "hashlib"),
    ],
)
def test_share_crypto_placeholders_fail_toward_infrastructure(
    callable_: object, args: tuple[str, ...], message: str
) -> None:
    """Domain crypto placeholders cannot be mistaken for secure implementations."""
    with pytest.raises(NotImplementedError, match=message):
        callable_(*args)  # type: ignore[operator]


def test_empty_share_account_gateway_is_a_fail_closed_fallback() -> None:
    """Absent portfolio integration never leaks another owner's account."""
    gateway = EmptyShareAccountGateway()
    assert gateway.list_owner_accounts(1) == []
    assert gateway.get_owned_account(owner_id=1, account_id=2) is None
    assert gateway.list_owned_positions(owner_id=1, account_id=2) == []
    assert gateway.list_owned_trades(owner_id=1, account_id=2, limit=10) == []
    assert gateway.account_belongs_to_owner(owner_id=1, account_id=2) is False
