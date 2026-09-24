"""AgomTradePro SDK - Task Monitor 模块。"""

from typing import Any

from .base import BaseModule


class TaskMonitorModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/system")

    def get_task_status(self, task_id: str, *, diagnostics: bool = False) -> dict[str, Any]:
        """Read a task status, optionally including administrator diagnostics."""

        params = {"diagnostics": True} if diagnostics else None
        return self._get(f"status/{task_id}/", params=params)

    def list_tasks(
        self,
        *,
        task_name: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        failures_only: bool = False,
        diagnostics: bool = False,
    ) -> dict[str, Any]:
        """List task projections with optional filters and admin diagnostics."""

        params: dict[str, Any] = {}
        if task_name:
            params["task_name"] = task_name
        if status:
            params["status"] = status
        if limit is not None:
            params["limit"] = limit
        if failures_only:
            params["failures_only"] = True
        if diagnostics:
            params["diagnostics"] = True
        return self._get("list/", params=params or None)

    def statistics(self, task_name: str | None = None, days: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if task_name:
            params["task_name"] = task_name
        if days is not None:
            params["days"] = days
        return self._get("statistics/", params=params)

    def dashboard(self) -> dict[str, Any]:
        return self._get("dashboard/")

    def celery_health(self) -> dict[str, Any]:
        return self._get("celery/health/")
