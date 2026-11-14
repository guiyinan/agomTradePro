"""Explicit Config Center routing for the ordinary-owner company-action workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from django.utils import timezone

from core.exceptions import BusinessLogicError
from core.integration.config_center_runtime import get_active_runtime_value

OWNER_CORPORATE_ACTION_WORKFLOW_RUNTIME_KEY = (
    "config_center.simulated_trading.corporate_action_workflow_runtime"
)
_SCHEMA = "simulated.corporate_action.owner_workflow_runtime.v1"
_FIELDS = frozenset(
    {
        "schema",
        "calendar_dataset_key",
        "statutory_provider_id",
        "statutory_body_store_root",
        "deployment_region",
    }
)


def _blocked() -> BusinessLogicError:
    """Keep missing routing distinct from source qualification or permission."""
    return BusinessLogicError(
        "Explicit owner workflow runtime is unavailable",
        code="CORPORATE_ACTION_WORKFLOW_CONFIGURATION_UNAVAILABLE",
    )


@dataclass(frozen=True, slots=True)
class OwnerCorporateActionWorkflowRuntime:
    """Routing only; no tax-law, market-data, custody or financial authority."""

    calendar_dataset_key: str
    statutory_provider_id: int
    statutory_body_store_root: Path
    deployment_region: str

    def __post_init__(self) -> None:
        """Require complete explicit identifiers and a safe native absolute store path."""
        for value in (self.calendar_dataset_key, self.deployment_region):
            if (
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > 256
                or any(ord(char) < 32 for char in value)
            ):
                raise ValueError("workflow routing text is invalid")
        if (
            type(self.statutory_provider_id) is not int
            or not 0 < self.statutory_provider_id < 2**63
        ):
            raise ValueError("workflow statutory provider is invalid")
        if (
            not isinstance(self.statutory_body_store_root, Path)
            or not self.statutory_body_store_root.is_absolute()
            or ".." in self.statutory_body_store_root.parts
        ):
            raise ValueError("workflow statutory store root is invalid")


def _decode(value: object) -> OwnerCorporateActionWorkflowRuntime:
    """Narrow one exact JSON package, without per-key defaults or partial fallback."""
    if type(value) is not dict or set(value) != _FIELDS:
        raise ValueError("workflow routing fields differ")
    payload = cast(dict[str, object], value)
    if payload["schema"] != _SCHEMA:
        raise ValueError("workflow routing schema differs")
    calendar = payload["calendar_dataset_key"]
    provider = payload["statutory_provider_id"]
    root = payload["statutory_body_store_root"]
    region = payload["deployment_region"]
    if (
        type(calendar) is not str
        or type(provider) is not int
        or type(root) is not str
        or type(region) is not str
    ):
        raise ValueError("workflow routing types differ")
    return OwnerCorporateActionWorkflowRuntime(calendar, provider, Path(root), region)


def read_owner_corporate_action_workflow_runtime(
    *,
    environment: str,
    as_of: datetime,
) -> OwnerCorporateActionWorkflowRuntime:
    """Read an unchanged active package; never infer missing service configuration."""
    try:
        if (
            type(environment) is not str
            or not environment
            or environment != environment.strip()
            or type(as_of) is not datetime
            or as_of.tzinfo is None
            or as_of.utcoffset() is None
            or as_of > timezone.now()
        ):
            raise ValueError("workflow configuration cutoff is invalid")
        before = _decode(
            get_active_runtime_value(
                environment=environment,
                definition_key=OWNER_CORPORATE_ACTION_WORKFLOW_RUNTIME_KEY,
                as_of=as_of,
            )
        )
        after = _decode(
            get_active_runtime_value(
                environment=environment,
                definition_key=OWNER_CORPORATE_ACTION_WORKFLOW_RUNTIME_KEY,
                as_of=as_of,
            )
        )
        if before != after or timezone.now() < as_of:
            raise ValueError("workflow routing changed during its read")
        return after
    except (TypeError, ValueError, OverflowError) as error:
        raise _blocked() from error
