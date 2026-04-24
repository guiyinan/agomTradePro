"""Share infrastructure repositories for interface/application consumers."""

from __future__ import annotations

from typing import Any

from django.db.models import Q

from apps.decision_rhythm.infrastructure.models import DecisionRequestModel
from apps.share.infrastructure.models import (
    ShareDisclaimerConfigModel,
    ShareLinkModel,
    ShareSnapshotModel,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel


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

        return ShareLinkModel._default_manager.select_related("owner").filter(id=share_link_id).first()

    def get_share_link_by_code(self, short_code: str):
        """Return one share link by public short code when available."""

        return ShareLinkModel._default_manager.select_related("owner").filter(short_code=short_code).first()

    def list_share_snapshots(self, *, share_link_id: int):
        """Return snapshots for one share link, newest first."""

        return ShareSnapshotModel._default_manager.filter(share_link_id=share_link_id).order_by("-snapshot_version")

    def increment_share_link_access_count(self, *, share_link_id: int) -> None:
        """Increment one share link access counter."""

        model = ShareLinkModel._default_manager.filter(id=share_link_id).first()
        if model is not None:
            model.increment_access_count()

    def list_owner_accounts(self, owner_id: int):
        """Return owner accounts ordered newest first."""

        return SimulatedAccountModel._default_manager.filter(user_id=owner_id).order_by("-created_at")

    def get_owned_account_for_snapshot(self, *, owner_id: int, account_id: int):
        """Return one owner account with positions/trades prefetched."""

        return (
            SimulatedAccountModel._default_manager.prefetch_related("positions", "trades")
            .filter(id=account_id, user_id=owner_id)
            .first()
        )

    def account_belongs_to_owner(self, *, owner_id: int, account_id: int) -> bool:
        """Return whether an account belongs to the given owner."""

        return SimulatedAccountModel._default_manager.filter(id=account_id, user_id=owner_id).exists()

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

        return {
            account.id: account.account_name
            for account in self.list_owner_accounts(owner_id)
        }
