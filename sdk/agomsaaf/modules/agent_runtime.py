"""
AgomSAAF SDK - Agent Runtime Module

WP-M2-03: Provides task lifecycle operations for the AI agent runtime.

Public methods:
- create_task
- get_task
- list_tasks
- resume_task
- cancel_task
- get_task_timeline
"""

from typing import Any, Dict, List, Optional

from .base import BaseModule


class AgentRuntimeModule(BaseModule):
    """
    Agent Runtime module.

    Manages AI agent task lifecycle: create, query, resume, cancel.
    """

    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/agent-runtime")

    def create_task(
        self,
        task_domain: str,
        task_type: str,
        input_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new agent task.

        Args:
            task_domain: Task domain (research/monitoring/decision/execution/ops)
            task_type: Task subtype (e.g., macro_portfolio_review)
            input_payload: JSON input payload for the task

        Returns:
            Dict with request_id and created task details

        Example:
            >>> client = AgomSAAFClient()
            >>> result = client.agent_runtime.create_task(
            ...     task_domain="research",
            ...     task_type="macro_portfolio_review",
            ...     input_payload={"focus": "regime_change"}
            ... )
            >>> print(result["task"]["id"])
        """
        body: Dict[str, Any] = {
            "task_domain": task_domain,
            "task_type": task_type,
            "input_payload": input_payload or {},
        }
        return self._post("tasks/", json=body)

    def get_task(self, task_id: int) -> Dict[str, Any]:
        """
        Get a single agent task by ID.

        Args:
            task_id: Task ID

        Returns:
            Dict with request_id and task details
        """
        return self._get(f"tasks/{task_id}/")

    def list_tasks(
        self,
        status: Optional[str] = None,
        task_domain: Optional[str] = None,
        task_type: Optional[str] = None,
        requires_human: Optional[bool] = None,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        List agent tasks with optional filters.

        Args:
            status: Filter by status
            task_domain: Filter by domain
            task_type: Filter by type (partial match)
            requires_human: Filter by requires_human flag
            search: Search in task_type and request_id
            limit: Results per page (default 50)
            offset: Pagination offset

        Returns:
            Dict with request_id, tasks list, and total_count
        """
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if status is not None:
            params["status"] = status
        if task_domain is not None:
            params["task_domain"] = task_domain
        if task_type is not None:
            params["task_type"] = task_type
        if requires_human is not None:
            params["requires_human"] = requires_human
        if search is not None:
            params["search"] = search
        return self._get("tasks/", params=params)

    def resume_task(
        self,
        task_id: int,
        target_status: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Resume a task from failed or needs_human state.

        Args:
            task_id: Task ID
            target_status: Target status (optional, defaults based on current state)
            reason: Reason for resuming

        Returns:
            Dict with request_id, updated task, and timeline_event_id
        """
        body: Dict[str, Any] = {}
        if target_status is not None:
            body["target_status"] = target_status
        if reason is not None:
            body["reason"] = reason
        return self._post(f"tasks/{task_id}/resume/", json=body)

    def cancel_task(self, task_id: int, reason: str) -> Dict[str, Any]:
        """
        Cancel a task.

        Args:
            task_id: Task ID
            reason: Reason for cancellation (required)

        Returns:
            Dict with request_id, cancelled task, and timeline_event_id
        """
        return self._post(f"tasks/{task_id}/cancel/", json={"reason": reason})

    def get_task_timeline(self, task_id: int) -> Dict[str, Any]:
        """
        Get timeline events for a task.

        Args:
            task_id: Task ID

        Returns:
            Dict with request_id and events list
        """
        return self._get(f"tasks/{task_id}/timeline/")

    def get_task_artifacts(self, task_id: int) -> Dict[str, Any]:
        """
        Get artifacts for a task.

        Args:
            task_id: Task ID

        Returns:
            Dict with request_id and artifacts list
        """
        return self._get(f"tasks/{task_id}/artifacts/")

    def get_needs_attention(self, limit: int = 20) -> Dict[str, Any]:
        """
        Get tasks that need human attention.

        Args:
            limit: Max results (default 20)

        Returns:
            Dict with request_id, tasks list, and total_count
        """
        return self._get("tasks/needs_attention/", params={"limit": limit})
