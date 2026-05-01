"""Application services for policy interface consumers."""

from __future__ import annotations

from typing import Any

from .use_cases import (
    GetWorkbenchItemsUseCase,
    GetWorkbenchSummaryUseCase,
    WorkbenchItemsInput,
    WorkbenchSummaryInput,
)


class PolicyAdminInterfaceService:
    """Application-facing helpers for policy admin actions."""

    def __init__(self, admin_repo):
        self.admin_repo = admin_repo

    def mark_policy_logs_level(self, policy_log_ids: list[int], *, level: str) -> int:
        """Bulk update policy level for selected rows."""

        return self.admin_repo.bulk_update_policy_logs(policy_log_ids, level=level)

    def approve_policy_logs(self, policy_log_ids: list[int], *, reviewer_id: int) -> int:
        """Approve pending policy logs."""

        return self.admin_repo.approve_policy_logs(
            policy_log_ids,
            reviewer_id=reviewer_id,
        )

    def reject_policy_logs(
        self,
        policy_log_ids: list[int],
        *,
        reviewer_id: int,
        review_notes: str,
    ) -> int:
        """Reject pending policy logs."""

        return self.admin_repo.reject_policy_logs(
            policy_log_ids,
            reviewer_id=reviewer_id,
            review_notes=review_notes,
        )

    def set_policy_list_flags(
        self,
        policy_log_ids: list[int],
        *,
        is_whitelist: bool,
        is_blacklist: bool,
    ) -> int:
        """Update list flags for selected policy logs."""

        return self.admin_repo.bulk_update_policy_logs(
            policy_log_ids,
            is_whitelist=is_whitelist,
            is_blacklist=is_blacklist,
        )

    def get_policy_log_statistics(self) -> dict[str, Any]:
        """Return aggregate policy log statistics."""

        return self.admin_repo.get_policy_log_statistics()

    def has_rsshub_global_config(self) -> bool:
        """Return whether the RSSHub singleton exists."""

        return self.admin_repo.has_rsshub_global_config()

    def get_rsshub_global_config_id(self) -> int | None:
        """Return the RSSHub singleton primary key when present."""

        return self.admin_repo.get_rsshub_global_config_id()


class PolicyWorkbenchInterfaceService:
    """Application-facing helpers for policy workbench views."""

    def __init__(self, *, workbench_repo, interface_repo):
        self.workbench_repo = workbench_repo
        self.interface_repo = interface_repo

    def list_gate_configs(self) -> list[dict[str, Any]]:
        """Return serialized gate config rows."""

        return [
            {
                "asset_class": config.asset_class,
                "heat_l1_threshold": config.heat_l1_threshold,
                "heat_l2_threshold": config.heat_l2_threshold,
                "heat_l3_threshold": config.heat_l3_threshold,
                "sentiment_l1_threshold": config.sentiment_l1_threshold,
                "sentiment_l2_threshold": config.sentiment_l2_threshold,
                "sentiment_l3_threshold": config.sentiment_l3_threshold,
                "max_position_cap_l2": config.max_position_cap_l2,
                "max_position_cap_l3": config.max_position_cap_l3,
                "enabled": config.enabled,
                "version": config.version,
            }
            for config in self.workbench_repo.get_all_gate_configs()
        ]

    def upsert_gate_config(
        self,
        *,
        payload: dict[str, Any],
        updated_by_id: int,
    ) -> dict[str, Any]:
        """Create or update one gate config."""

        config, created = self.interface_repo.upsert_gate_config(
            payload=payload,
            updated_by_id=updated_by_id,
        )
        return {
            "success": True,
            "asset_class": config.asset_class,
            "version": config.version,
            "created": created,
        }

    def get_workbench_bootstrap(self) -> dict[str, Any]:
        """Return the aggregate bootstrap payload."""

        summary_output = GetWorkbenchSummaryUseCase(
            workbench_repo=self.workbench_repo
        ).execute(WorkbenchSummaryInput())
        items_output = GetWorkbenchItemsUseCase(
            workbench_repo=self.workbench_repo
        ).execute(WorkbenchItemsInput(tab="all", limit=50, offset=0))

        return {
            "success": True,
            "summary": summary_output.summary if summary_output.success else {},
            "default_list": items_output.items if items_output.success else [],
            "filter_options": self.interface_repo.get_workbench_filter_options(),
            "trend": self.interface_repo.get_trend_data(),
            "fetch_status": self.interface_repo.get_fetch_status(),
        }

    def get_workbench_item_detail(self, event_id: int) -> dict[str, Any] | None:
        """Return one serialized workbench item detail row."""

        return self.interface_repo.get_workbench_item_detail(event_id)


class PolicyPageInterfaceService:
    """Application-facing helpers for policy HTML page views."""

    def __init__(self, page_repo):
        self.page_repo = page_repo

    def list_rss_sources(self, *, category: str = "", is_active: str = "", search: str = ""):
        return self.page_repo.list_rss_sources(
            category=category,
            is_active=is_active,
            search=search,
        )

    def list_policy_keywords(self, *, level: str = "", is_active: str = ""):
        return self.page_repo.list_policy_keywords(
            level=level,
            is_active=is_active,
        )

    def list_rss_fetch_logs(self, *, source_id: str = "", status: str = ""):
        return self.page_repo.list_rss_fetch_logs(
            source_id=source_id,
            status=status,
        )

    def get_rss_fetch_log_summary(self, *, source_id: str = "", status: str = "") -> dict[str, Any]:
        return self.page_repo.get_rss_fetch_log_summary(
            source_id=source_id,
            status=status,
        )

    def list_rss_reader_items(
        self,
        *,
        source_id: str = "",
        level: str = "",
        category: str = "",
    ):
        return self.page_repo.list_rss_reader_items(
            source_id=source_id,
            level=level,
            category=category,
        )

    def get_rss_reader_summary(
        self,
        *,
        source_id: str = "",
        level: str = "",
        category: str = "",
    ) -> dict[str, Any]:
        return self.page_repo.get_rss_reader_summary(
            source_id=source_id,
            level=level,
            category=category,
        )

    def list_policy_events(
        self,
        *,
        level: str = "",
        start_date: str = "",
        end_date: str = "",
    ):
        return self.page_repo.list_policy_events(
            level=level,
            start_date=start_date,
            end_date=end_date,
        )

    def create_policy_event(self, payload: dict[str, Any]):
        return self.page_repo.create_policy_event(payload)

    def get_page_constants(self) -> dict[str, Any]:
        return self.page_repo.get_policy_page_constants()


class PolicyRssApiInterfaceService:
    """Application-facing helpers for policy RSS API views."""

    def __init__(self, api_repo):
        self.api_repo = api_repo

    def list_rss_source_configs(
        self,
        *,
        category: str = "",
        is_active: str | None = "",
        parser_type: str = "",
        search: str = "",
    ):
        return self.api_repo.list_rss_source_configs(
            category=category,
            is_active=is_active,
            parser_type=parser_type,
            search=search,
        )

    def get_rss_source_config(self, source_id: int):
        return self.api_repo.get_rss_source_config(source_id)

    def create_rss_source_config(self, payload: dict[str, Any]):
        return self.api_repo.create_rss_source_config(payload)

    def update_rss_source_config(self, source_id: int, payload: dict[str, Any]):
        return self.api_repo.update_rss_source_config(source_id, payload)

    def delete_rss_source_config(self, source_id: int) -> bool:
        return self.api_repo.delete_rss_source_config(source_id)

    def list_rss_fetch_logs(
        self,
        *,
        source_name: str = "",
        source_id: str = "",
        status: str = "",
    ):
        return self.api_repo.list_rss_fetch_logs(
            source_name=source_name,
            source_id=source_id,
            status=status,
        )

    def get_rss_fetch_log(self, log_id: int):
        return self.api_repo.get_rss_fetch_log(log_id)

    def list_policy_level_keywords(
        self,
        *,
        level: str = "",
        is_active: str | None = "",
        category: str = "",
    ):
        return self.api_repo.list_policy_level_keywords(
            level=level,
            is_active=is_active,
            category=category,
        )

    def get_policy_level_keyword(self, keyword_id: int):
        return self.api_repo.get_policy_level_keyword(keyword_id)

    def create_policy_level_keyword(self, payload: dict[str, Any]):
        return self.api_repo.create_policy_level_keyword(payload)

    def update_policy_level_keyword(self, keyword_id: int, payload: dict[str, Any]):
        return self.api_repo.update_policy_level_keyword(keyword_id, payload)

    def delete_policy_level_keyword(self, keyword_id: int) -> bool:
        return self.api_repo.delete_policy_level_keyword(keyword_id)
