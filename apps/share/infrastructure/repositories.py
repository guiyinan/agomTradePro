"""Share infrastructure repositories for interface/application consumers."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from apps.decision_rhythm.infrastructure.models import DecisionRequestModel
from apps.share.domain.entities import ShareLevel, ShareLinkEntity, ShareStatus, ShareTheme
from apps.share.domain.interfaces import (
    ShareOwnedAccountSnapshot,
    ShareOwnedPositionSnapshot,
    ShareOwnedTradeSnapshot,
)
from apps.share.infrastructure.models import (
    ShareAccessLogModel,
    ShareDisclaimerConfigModel,
    ShareLinkModel,
    ShareSnapshotModel,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

UserModel = get_user_model()


class ShareInterfaceRepository:
    """Read/write helpers used by share interface services."""

    def get_share_link_queryset_for_owner(self, owner_id: int):
        """Return owner-scoped share links ordered newest first."""

        return (
            ShareLinkModel._default_manager.filter(owner_id=owner_id)
            .select_related("owner")
            .order_by("-created_at")
        )

    def get_share_link_for_owner(self, *, owner_id: int, share_link_id: int):
        """Return one owner-scoped share link when available."""

        return (
            ShareLinkModel._default_manager.select_related("owner")
            .filter(id=share_link_id, owner_id=owner_id)
            .first()
        )

    def get_share_link_by_id(self, share_link_id: int):
        """Return one share link by id when available."""

        return (
            ShareLinkModel._default_manager.select_related("owner").filter(id=share_link_id).first()
        )

    def get_share_link_by_code(self, short_code: str):
        """Return one share link by public short code when available."""

        return (
            ShareLinkModel._default_manager.select_related("owner")
            .filter(short_code=short_code)
            .first()
        )

    def list_share_snapshots(self, *, share_link_id: int):
        """Return snapshots for one share link, newest first."""

        return ShareSnapshotModel._default_manager.filter(share_link_id=share_link_id).order_by(
            "-snapshot_version"
        )

    def increment_share_link_access_count(self, *, share_link_id: int) -> None:
        """Increment one share link access counter."""

        model = ShareLinkModel._default_manager.filter(id=share_link_id).first()
        if model is not None:
            model.increment_access_count()

    def list_owner_accounts(self, owner_id: int):
        """Return owner accounts ordered newest first."""

        return SimulatedAccountModel._default_manager.filter(user_id=owner_id).order_by(
            "-created_at"
        )

    def get_owned_account_for_snapshot(self, *, owner_id: int, account_id: int):
        """Return one owner account with positions/trades prefetched."""

        account = SimulatedAccountModel._default_manager.filter(
            id=account_id, user_id=owner_id
        ).first()
        if account is None:
            return None
        return ShareOwnedAccountSnapshot(
            id=account.id,
            account_name=account.account_name,
            account_type=account.account_type,
            start_date=account.start_date,
            total_value=account.total_value,
            current_market_value=account.current_market_value,
            current_cash=account.current_cash,
            total_return=account.total_return,
            annual_return=account.annual_return,
            max_drawdown=account.max_drawdown,
            sharpe_ratio=account.sharpe_ratio,
            win_rate=account.win_rate,
            total_trades=account.total_trades,
        )

    def list_owned_account_positions_for_snapshot(
        self,
        *,
        owner_id: int,
        account_id: int,
    ) -> list[ShareOwnedPositionSnapshot]:
        """Return ordered positions for share snapshot generation."""

        account = (
            SimulatedAccountModel._default_manager.prefetch_related("positions")
            .filter(id=account_id, user_id=owner_id)
            .first()
        )
        if account is None:
            return []
        return [
            ShareOwnedPositionSnapshot(
                asset_code=position.asset_code,
                asset_name=position.asset_name,
                asset_type=position.asset_type,
                quantity=position.quantity,
                avg_cost=position.avg_cost,
                current_price=position.current_price,
                market_value=position.market_value,
                unrealized_pnl=position.unrealized_pnl,
                unrealized_pnl_pct=position.unrealized_pnl_pct,
                entry_reason=position.entry_reason,
                invalidation_description=position.invalidation_description,
            )
            for position in account.positions.all().order_by("-market_value")
        ]

    def list_owned_account_trades_for_snapshot(
        self,
        *,
        owner_id: int,
        account_id: int,
        limit: int = 20,
    ) -> list[ShareOwnedTradeSnapshot]:
        """Return ordered trades for share snapshot generation."""

        account = (
            SimulatedAccountModel._default_manager.prefetch_related("trades")
            .filter(id=account_id, user_id=owner_id)
            .first()
        )
        if account is None:
            return []
        return [
            ShareOwnedTradeSnapshot(
                asset_code=trade.asset_code,
                asset_name=trade.asset_name,
                action=trade.action,
                quantity=trade.quantity,
                price=trade.price,
                amount=trade.amount,
                reason=trade.reason,
                execution_time=trade.execution_time,
                status=trade.status,
            )
            for trade in account.trades.all().order_by("-execution_date", "-execution_time")[:limit]
        ]

    def account_belongs_to_owner(self, *, owner_id: int, account_id: int) -> bool:
        """Return whether an account belongs to the given owner."""

        return SimulatedAccountModel._default_manager.filter(
            id=account_id, user_id=owner_id
        ).exists()

    def list_decision_requests_for_account_assets(self, *, account_id: int, asset_codes: set[str]):
        """Return decision requests relevant to one account and asset set."""

        if not asset_codes:
            return []

        return list(
            DecisionRequestModel._default_manager.filter(asset_code__in=asset_codes)
            .filter(
                Q(unified_recommendation__account_id=str(account_id))
                | Q(unified_recommendation__account_id=account_id)
                | Q(execution_ref__account_id=account_id)
                | Q(execution_ref__account_id=str(account_id))
            )
            .select_related(
                "response",
                "feature_snapshot",
                "unified_recommendation",
                "unified_recommendation__feature_snapshot",
            )
            .order_by("-requested_at")[:12]
        )

    def get_share_disclaimer_config(self):
        """Return the singleton share disclaimer config."""

        return ShareDisclaimerConfigModel.get_solo()

    def has_share_disclaimer_config(self) -> bool:
        """Return whether the disclaimer config record already exists."""

        return ShareDisclaimerConfigModel._default_manager.exists()

    def update_share_disclaimer_config(
        self,
        *,
        is_enabled: bool,
        modal_enabled: bool,
        modal_title: str,
        modal_confirm_text: str,
        lines: list[str],
    ):
        """Persist the singleton share disclaimer config."""

        config = self.get_share_disclaimer_config()
        config.is_enabled = is_enabled
        config.modal_enabled = modal_enabled
        config.modal_title = modal_title
        config.modal_confirm_text = modal_confirm_text
        config.lines = lines
        config.save(
            update_fields=[
                "is_enabled",
                "modal_enabled",
                "modal_title",
                "modal_confirm_text",
                "lines",
                "updated_at",
            ]
        )
        return config

    def get_owner_account_name_map(self, owner_id: int) -> dict[int, str]:
        """Return account id to account name mapping for one owner."""

        return {account.id: account.account_name for account in self.list_owner_accounts(owner_id)}


class ShareApplicationRepository:
    """Repository implementation used by share application use cases."""

    def user_exists(self, owner_id: int) -> bool:
        """Return whether the share owner exists."""

        return UserModel._default_manager.filter(id=owner_id).exists()

    def account_belongs_to_owner(self, *, owner_id: int, account_id: int) -> bool:
        """Return whether the target account belongs to the owner."""

        return SimulatedAccountModel._default_manager.filter(
            id=account_id, user_id=owner_id
        ).exists()

    def share_link_short_code_exists(self, short_code: str) -> bool:
        """Return whether one public short code already exists."""

        return ShareLinkModel._default_manager.filter(short_code=short_code).exists()

    def create_share_link(self, **payload: Any) -> ShareLinkEntity:
        """Persist a new share link and return the resulting entity."""

        model = ShareLinkModel._default_manager.create(**payload)
        return self._to_share_link_entity(model)

    def get_share_link(self, share_link_id: int) -> ShareLinkEntity | None:
        """Return one share link entity by id when available."""

        model = ShareLinkModel._default_manager.filter(id=share_link_id).first()
        if model is None:
            return None
        return self._to_share_link_entity(model)

    def get_share_link_by_code(self, short_code: str) -> ShareLinkEntity | None:
        """Return one share link entity by public short code when available."""

        model = ShareLinkModel._default_manager.filter(short_code=short_code).first()
        if model is None:
            return None
        return self._to_share_link_entity(model)

    def list_share_links(
        self,
        *,
        owner_id: int | None = None,
        account_id: int | None = None,
        status: str | None = None,
        share_level: str | None = None,
    ) -> list[ShareLinkEntity]:
        """Return share links filtered by the provided criteria."""

        queryset = ShareLinkModel._default_manager.all()
        if owner_id is not None:
            queryset = queryset.filter(owner_id=owner_id)
        if account_id is not None:
            queryset = queryset.filter(account_id=account_id)
        if status is not None:
            queryset = queryset.filter(status=status)
        if share_level is not None:
            queryset = queryset.filter(share_level=share_level)
        return [self._to_share_link_entity(model) for model in queryset]

    def update_share_link_fields(
        self,
        *,
        share_link_id: int,
        updates: dict[str, Any],
    ) -> ShareLinkEntity | None:
        """Persist field updates and return the refreshed share link entity."""

        model = ShareLinkModel._default_manager.filter(id=share_link_id).first()
        if model is None:
            return None
        for field_name, value in updates.items():
            setattr(model, field_name, value)
        model.save(update_fields=list(updates.keys()))
        return self._to_share_link_entity(model)

    def revoke_share_link(self, *, share_link_id: int, owner_id: int) -> bool:
        """Mark one owner-scoped share link as revoked."""

        updated = ShareLinkModel._default_manager.filter(
            id=share_link_id,
            owner_id=owner_id,
        ).update(status=ShareStatus.REVOKED.value)
        return updated > 0

    def delete_share_link(self, *, share_link_id: int, owner_id: int) -> bool:
        """Delete one owner-scoped share link."""

        deleted, _ = ShareLinkModel._default_manager.filter(
            id=share_link_id,
            owner_id=owner_id,
        ).delete()
        return deleted > 0

    def create_snapshot(
        self,
        *,
        share_link_id: int,
        summary_payload: dict[str, Any],
        performance_payload: dict[str, Any],
        positions_payload: dict[str, Any],
        transactions_payload: dict[str, Any],
        decision_payload: dict[str, Any],
        source_range_start=None,
        source_range_end=None,
    ) -> int | None:
        """Persist a snapshot and return its id when the share link exists."""

        share_link = ShareLinkModel._default_manager.filter(id=share_link_id).first()
        if share_link is None:
            return None

        last_version = (
            ShareSnapshotModel._default_manager.filter(share_link_id=share_link_id)
            .order_by("-snapshot_version")
            .values_list("snapshot_version", flat=True)
            .first()
        )
        next_version = (last_version + 1) if last_version is not None else 1
        snapshot = ShareSnapshotModel._default_manager.create(
            share_link=share_link,
            snapshot_version=next_version,
            summary_payload=summary_payload or {},
            performance_payload=performance_payload or {},
            positions_payload=positions_payload or {},
            transactions_payload=transactions_payload or {},
            decision_payload=decision_payload or {},
            source_range_start=source_range_start,
            source_range_end=source_range_end,
        )
        share_link.last_snapshot_at = timezone.now()
        share_link.save(update_fields=["last_snapshot_at"])
        return snapshot.id

    def get_latest_snapshot(self, share_link_id: int) -> dict[str, Any] | None:
        """Return the latest share snapshot payload when available."""

        snapshot = (
            ShareSnapshotModel._default_manager.filter(share_link_id=share_link_id)
            .order_by("-snapshot_version")
            .first()
        )
        if snapshot is None:
            return None
        return {
            "id": snapshot.id,
            "snapshot_version": snapshot.snapshot_version,
            "summary": snapshot.summary_payload,
            "performance": snapshot.performance_payload,
            "positions": snapshot.positions_payload,
            "transactions": snapshot.transactions_payload,
            "decisions": snapshot.decision_payload,
            "generated_at": snapshot.generated_at,
            "source_range_start": snapshot.source_range_start,
            "source_range_end": snapshot.source_range_end,
        }

    def log_access(
        self,
        *,
        share_link_id: int,
        ip_hash: str,
        user_agent: str | None = None,
        referer: str | None = None,
        result_status: str = "success",
        is_verified: bool = False,
    ) -> int:
        """Persist one access log entry and return its id."""

        log = ShareAccessLogModel._default_manager.create(
            share_link_id=share_link_id,
            ip_hash=ip_hash,
            user_agent=user_agent,
            referer=referer,
            is_verified=is_verified,
            result_status=result_status,
        )
        return log.id

    def get_access_logs(
        self,
        *,
        share_link_id: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return access log rows ordered newest first."""

        logs = ShareAccessLogModel._default_manager.filter(share_link_id=share_link_id).order_by(
            "-accessed_at"
        )[:limit]
        return [
            {
                "id": log.id,
                "accessed_at": log.accessed_at,
                "ip_hash": log.ip_hash,
                "user_agent": log.user_agent,
                "referer": log.referer,
                "is_verified": log.is_verified,
                "result_status": log.result_status,
            }
            for log in logs
        ]

    def get_access_stats(self, *, share_link_id: int) -> dict[str, int]:
        """Return aggregate access statistics for one share link."""

        logs = ShareAccessLogModel._default_manager.filter(share_link_id=share_link_id)
        return {
            "total_accesses": logs.count(),
            "successful_accesses": logs.filter(result_status="success").count(),
            "unique_visitors": logs.values("ip_hash").distinct().count(),
        }

    @staticmethod
    def _to_share_link_entity(model: ShareLinkModel) -> ShareLinkEntity:
        """Convert one ORM model into the corresponding domain entity."""

        return ShareLinkEntity(
            id=model.id,
            owner_id=model.owner_id,
            account_id=model.account_id,
            short_code=model.short_code,
            title=model.title,
            subtitle=model.subtitle,
            theme=ShareTheme(model.theme),
            share_level=ShareLevel(model.share_level),
            status=ShareStatus(model.status),
            password_hash=model.password_hash,
            expires_at=model.expires_at,
            max_access_count=model.max_access_count,
            access_count=model.access_count,
            last_snapshot_at=model.last_snapshot_at,
            last_accessed_at=model.last_accessed_at,
            allow_indexing=model.allow_indexing,
            show_amounts=model.show_amounts,
            show_positions=model.show_positions,
            show_transactions=model.show_transactions,
            show_decision_summary=model.show_decision_summary,
            show_decision_evidence=model.show_decision_evidence,
            show_invalidation_logic=model.show_invalidation_logic,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
