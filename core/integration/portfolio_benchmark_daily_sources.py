"""Compose Portfolio's immutable benchmark inputs from the Account, Broker and Data Center owners."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from rest_framework.request import Request

from apps.portfolio.application.benchmark_daily_sources import (
    BenchmarkDaySources,
    ClosingFixing,
    DayOwner,
    DayReconciliation,
)
from apps.portfolio.domain.benchmark_execution_approval import BenchmarkScope


class _OwnerSources:
    @contextmanager
    def signer(
        self, *, request: Request, using: str, before_commit: Callable[[], None]
    ) -> Iterator[int]:
        """Lock and reauthenticate the actual human session through the Account owner."""
        from apps.account.live_account_owner_composition import locked_account_owner_session

        with locked_account_owner_session(
            request=request, using=using, before_commit=before_commit
        ) as user:
            yield int(user.pk)

    def owner(
        self, *, namespace: str, account_id: str, user_id: int, using: str
    ) -> DayOwner | None:
        """Lock the real physical account and its exact single-owner authority."""
        from apps.account.live_account_owner_composition import read_live_account_owner

        owner = read_live_account_owner(
            account_namespace=namespace, account_id=account_id, owner_user_id=user_id, using=using
        )
        if owner is None:
            return None
        return DayOwner(
            BenchmarkScope(namespace, account_id, user_id, owner.tenant_id, owner.owner_id),
            owner.physical_row_pk,
            owner.identity_hash,
            owner.policy_hash,
            owner.valid_until,
        )

    def reconciliation(
        self, *, snapshot_id: int, owner: DayOwner, using: str
    ) -> DayReconciliation | None:
        """Read the exact complete Agent snapshot to compare with independent custody records."""
        from apps.broker_execution.benchmark_day_source_composition import (
            read_benchmark_broker_balances,
        )

        value = read_benchmark_broker_balances(
            snapshot_id=snapshot_id,
            owner_user_id=owner.scope.owner_user_id,
            account_id=owner.physical_id,
            using=using,
        )
        if value is None:
            return None
        return DayReconciliation(
            value.account_ref_hash,
            value.captured_at,
            value.received_at,
            value.max_snapshot_age_seconds,
            value.total_asset,
            value.cash_available,
            value.cash_frozen,
            value.position_market_value,
            value.currency,
            {
                p.asset_code: (p.quantity, p.available_quantity, p.market_value)
                for p in value.positions
            },
            value.content_hash,
            value.signed_receipt,
        )

    def historical_member(
        self, *, asset: str, day: date, at: datetime, issued_at: datetime, using: str
    ) -> str | None:
        """Read the exact past row in the current owner publication."""
        from apps.data_center.benchmark_history_composition import (
            read_current_benchmark_day_member_hash,
        )

        return read_current_benchmark_day_member_hash(
            asset=asset, day=day, at=at, issued_at=issued_at, using=using
        )

    def fixing(self, *, asset: str, day: date, at: datetime, using: str) -> ClosingFixing | None:
        """Only consume the decision-eligible exact equity closing row of the active publication."""
        from apps.data_center.benchmark_close_price_composition import (
            locked_benchmark_close_payload,
        )
        from apps.data_center.domain.market_time import cn_market_session_close_utc

        if using != "default":
            return None  # Public Data Center reads presently operate on its default database.
        payload = locked_benchmark_close_payload(asset=asset, day=day, at=at, using=using)
        if payload is None:
            return None
        rows = payload.get("rows")
        if (
            payload.get("must_not_use_for_decision") is not False
            or payload.get("blocked_reason")
            or payload.get("dataset_key") != "equity.price.bar"
            or payload.get("publication_key") != "current"
            or payload.get("asset_code") != asset
            or payload.get("freshness_scope") != "asset"
            or payload.get("freshness_status") not in ("fresh", "latest_completed_session")
            or not isinstance(rows, list)
            or len(rows) != 1
            or not isinstance(rows[0], dict)
            or not payload.get("policy_identity")
            or not payload.get("selected_source")
        ):
            return None
        row = rows[0]
        if (
            row.get("timestamp") != day.isoformat()
            or row.get("period") != "1d"
            or not row.get("source")
            or row.get("asset_code") != asset
        ):
            return None
        try:
            UUID(str(payload["publication_run_id"]))
            price = Decimal(str(row["close"]))
            observed = datetime.fromisoformat(str(payload["observed_at"]))
            published = datetime.fromisoformat(str(payload["published_at"]))
            as_of = datetime.fromisoformat(str(payload["as_of"]))
            fetched = datetime.fromisoformat(str(row["fetched_at"]))
            digest = str(payload["publication_hash"])
            if (
                len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                or not price.is_finite()
                or price <= 0
                or observed != cn_market_session_close_utc(day)
                or not fetched <= published <= at
                or not observed <= published <= at
                or not observed <= as_of <= at
            ):
                return None
        except (ValueError, InvalidOperation, KeyError, TypeError, OverflowError):
            return None
        from apps.data_center.benchmark_history_composition import read_benchmark_member_hash

        member = read_benchmark_member_hash(
            asset=asset, day=day, at=at, publication_hash=digest, expected_price=price, using=using
        )
        if member is None:
            return None
        return ClosingFixing(
            observed,
            published,
            price,
            digest,
            member_hash=member,
            asset_class=str(payload.get("benchmark_asset_class") or ""),
            venue=str(payload.get("benchmark_venue") or ""),
        )


def build_benchmark_day_sources() -> BenchmarkDaySources:
    """Return concrete owner readers. Economic inputs cannot select an alternative provider."""
    return _OwnerSources()
