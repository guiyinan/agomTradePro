"""AgomSAAF SDK - Task Monitor 模块。"""

from typing import Any

from .base import BaseModule


class TaskMonitorModule(BaseModule):
    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/system")

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        return self._get(f"status/{task_id}/")

    def list_tasks(self) -> dict[str, Any]:
        return self._get("list/")

    def statistics(self) -> dict[str, Any]:
        return self._get("statistics/")

    def dashboard(self) -> dict[str, Any]:
        return self._get("dashboard/")

    def celery_health(self) -> dict[str, Any]:
        return self._get("celery/health/")