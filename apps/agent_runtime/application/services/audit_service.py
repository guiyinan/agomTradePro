"""
Audit Service for Agent Runtime.

This service provides audit logging for task operations.
It integrates with the existing audit infrastructure.

WP-M1-06: Security And Audit Hook
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from django.utils import timezone as django_timezone

logger = logging.getLogger(__name__)


class AgentRuntimeAuditService:
    """
    Audit service for Agent Runtime operations.

    Records operation logs for:
    - Task creation
    - Task resume
    - Task cancellation
    - State transitions

    This service is designed to be non-blocking - audit failures
    should not affect the main workflow.
    """

    def __init__(self):
        """Initialize the audit service."""
        self._enabled = True

    def log_task_created(
        self,
        task_id: int,
        request_id: str,
        task_domain: str,
        task_type: str,
        user_id: int | None = None,
        input_payload: dict[str, Any] | None = None,
        ip_address: str | None = None,
        source: str = "API",
    ) -> str | None:
        """
        Log a task creation event.

        Args:
            task_id: The created task ID
            request_id: The request trace ID
            task_domain: Task domain (research/monitoring/decision/execution/ops)
            task_type: Task subtype
            user_id: User ID if authenticated
            input_payload: Task input payload
            ip_address: Client IP address
            source: Source of the operation (API/SDK/MCP)

        Returns:
            Log ID if successful, None otherwise
        """
        return self._log_operation(
            request_id=request_id,
            user_id=user_id,
            source=source,
            operation_type="DATA_MODIFY",
            module="agent_runtime",
            action="CREATE",
            resource_type="agent_task",
            resource_id=str(task_id),
            request_params={
                "task_domain": task_domain,
                "task_type": task_type,
                "input_payload": input_payload or {},
            },
            response_payload={"task_id": task_id, "status": "draft"},
            response_status=201,
            response_message=f"Task {task_id} created successfully",
            ip_address=ip_address,
        )

    def log_task_resumed(
        self,
        task_id: int,
        request_id: str,
        from_status: str,
        to_status: str,
        reason: str | None = None,
        user_id: int | None = None,
        ip_address: str | None = None,
        source: str = "API",
    ) -> str | None:
        """
        Log a task resume event.

        Args:
            task_id: The resumed task ID
            request_id: The request trace ID
            from_status: Previous status
            to_status: New status
            reason: Reason for resuming
            user_id: User ID if authenticated
            ip_address: Client IP address
            source: Source of the operation

        Returns:
            Log ID if successful, None otherwise
        """
        return self._log_operation(
            request_id=request_id,
            user_id=user_id,
            source=source,
            operation_type="DATA_MODIFY",
            module="agent_runtime",
            action="UPDATE",
            resource_type="agent_task",
            resource_id=str(task_id),
            request_params={
                "from_status": from_status,
                "to_status": to_status,
                "reason": reason,
            },
            response_payload={"task_id": task_id, "new_status": to_status},
            response_status=200,
            response_message=f"Task {task_id} resumed from {from_status} to {to_status}",
            ip_address=ip_address,
        )

    def log_task_cancelled(
        self,
        task_id: int,
        request_id: str,
        from_status: str,
        reason: str,
        user_id: int | None = None,
        ip_address: str | None = None,
        source: str = "API",
    ) -> str | None:
        """
        Log a task cancellation event.

        Args:
            task_id: The cancelled task ID
            request_id: The request trace ID
            from_status: Previous status
            reason: Reason for cancellation
            user_id: User ID if authenticated
            ip_address: Client IP address
            source: Source of the operation

        Returns:
            Log ID if successful, None otherwise
        """
        return self._log_operation(
            request_id=request_id,
            user_id=user_id,
            source=source,
            operation_type="DATA_MODIFY",
            module="agent_runtime",
            action="DELETE",
            resource_type="agent_task",
            resource_id=str(task_id),
            request_params={
                "from_status": from_status,
                "reason": reason,
            },
            response_payload={"task_id": task_id, "status": "cancelled"},
            response_status=200,
            response_message=f"Task {task_id} cancelled: {reason}",
            ip_address=ip_address,
        )

    def log_state_transition(
        self,
        task_id: int,
        request_id: str,
        from_status: str,
        to_status: str,
        trigger: str,
        user_id: int | None = None,
        ip_address: str | None = None,
        source: str = "SYSTEM",
    ) -> str | None:
        """
        Log a state transition event.

        Args:
            task_id: The task ID
            request_id: The request trace ID
            from_status: Previous status
            to_status: New status
            trigger: What triggered the transition
            user_id: User ID if authenticated
            ip_address: Client IP address
            source: Source of the operation

        Returns:
            Log ID if successful, None otherwise
        """
        return self._log_operation(
            request_id=request_id,
            user_id=user_id,
            source=source,
            operation_type="DATA_MODIFY",
            module="agent_runtime",
            action="UPDATE",
            resource_type="agent_task",
            resource_id=str(task_id),
            request_params={
                "from_status": from_status,
                "to_status": to_status,
                "trigger": trigger,
            },
            response_payload={"task_id": task_id, "new_status": to_status},
            response_status=200,
            response_message=f"Task {task_id} transitioned: {from_status} -> {to_status}",
            ip_address=ip_address,
        )

    def _log_operation(
        self,
        request_id: str,
        user_id: int | None,
        source: str,
        operation_type: str,
        module: str,
        action: str,
        resource_type: str,
        resource_id: str,
        request_params: dict[str, Any],
        response_payload: dict[str, Any],
        response_status: int,
        response_message: str,
        ip_address: str | None = None,
    ) -> str | None:
        """
        Internal method to log an operation.

        This method is designed to be non-blocking - if logging fails,
        it logs the error but does not raise an exception.

        Args:
            request_id: The request trace ID
            user_id: User ID if authenticated
            source: Source of the operation (API/SDK/MCP/SYSTEM)
            operation_type: Type of operation
            module: Module name
            action: Action type (CREATE/READ/UPDATE/DELETE)
            resource_type: Type of resource
            resource_id: Resource identifier
            request_params: Request parameters
            response_payload: Response data
            response_status: HTTP-style status code
            response_message: Human-readable message
            ip_address: Client IP address

        Returns:
            Log ID if successful, None otherwise
        """
        if not self._enabled:
            return None

        try:
            from apps.audit.application.use_cases import (
                LogOperationRequest,
                LogOperationUseCase,
            )
            from apps.audit.infrastructure.repositories import DjangoAuditRepository

            # Get username if user_id is provided
            username = "anonymous"
            if user_id:
                try:
                    from django.contrib.auth.models import User
                    user = User.objects.get(id=user_id)
                    username = user.username
                except Exception:
                    username = f"user_{user_id}"

            # Create the use case and request
            audit_repo = DjangoAuditRepository()
            use_case = LogOperationUseCase(audit_repo)

            request = LogOperationRequest(
                request_id=request_id,
                user_id=user_id,
                username=username,
                source=source,
                operation_type=operation_type,
                module=module,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                request_params=request_params,
                response_payload=response_payload,
                response_status=response_status,
                response_message=response_message,
                ip_address=ip_address,
            )

            # Execute the use case
            response = use_case.execute(request)

            if response.success:
                logger.debug(f"Logged operation: {operation_type} for task {resource_id}")
                return response.log_id
            else:
                logger.warning(f"Failed to log operation: {response.error}")
                return None

        except Exception as e:
            # Log error but don't block the main workflow
            logger.error(f"Audit logging failed: {e}")
            return None

    def enable(self) -> None:
        """Enable audit logging."""
        self._enabled = True

    def disable(self) -> None:
        """Disable audit logging."""
        self._enabled = False


# Singleton instance
_audit_service: AgentRuntimeAuditService | None = None


def get_audit_service() -> AgentRuntimeAuditService:
    """
    Get the singleton AgentRuntimeAuditService instance.

    Returns:
        The shared AgentRuntimeAuditService instance
    """
    global _audit_service
    if _audit_service is None:
        _audit_service = AgentRuntimeAuditService()
    return _audit_service
