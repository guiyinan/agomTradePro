"""Safe user-facing projections for the calendar publication workbench."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.data_center.application.calendar_workbench import CalendarWorkbenchPreview
from apps.data_center.application.calendar_workbench_scope import (
    CalendarWorkbenchScopeContext,
    CalendarWorkbenchScopeMetadata,
    CalendarWorkbenchScopeMetadataStatus,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationCommit,
)
from apps.data_center.calendar_workbench_current_composition import (
    CalendarWorkbenchCurrentReadResult,
)

WORKBENCH_CONFIRM_ACTION_KEY = "data-center.calendar-workbench-confirm"


def present_calendar_workbench_preview(value: CalendarWorkbenchPreview) -> dict[str, object]:
    """Return readable source scope and keep the token outside visible data."""

    if type(value) is not CalendarWorkbenchPreview:
        raise TypeError("Calendar workbench preview must use its exact DTO")
    value.__post_init__()
    reference = value.preview.snapshot_reference
    return {
        "publication_status": "preview",
        "must_not_execute": True,
        "must_not_use_for_decision": True,
        "blocked_reason": "exchange_calendar_reference_only",
        "freshness": {
            "source_observed_at": None,
            "source_available_at": None,
            "source_time_status": "not_provided",
        },
        "reliability": "unpublished_publication_preview",
        "exchange": reference.exchange,
        "coverage_start": reference.coverage_start.isoformat(),
        "coverage_end": reference.coverage_end.isoformat(),
        "first_seen_at": _utc_text(value.preview.first_seen_at),
        "source_published_at": _optional_utc_text(value.preview.source_published_at),
        "previewed_at": _utc_text(value.preview.previewed_at),
        "response_expires_at": _utc_text(value.preview.response_expires_at),
        "message": "预览已准备，请在有效期内确认；该日历仅供参考，不可用于交易或投资决策。",
    }


def present_calendar_workbench_continuation(
    value: CalendarWorkbenchPreview,
) -> dict[str, object]:
    """Return machine-only in-memory handoff data for the TUI continuation."""

    if type(value) is not CalendarWorkbenchPreview:
        raise TypeError("Calendar workbench preview must use its exact DTO")
    value.__post_init__()
    return {
        "action_key": WORKBENCH_CONFIRM_ACTION_KEY,
        "input": {"confirmation_token": value.confirmation_token},
        "expires_at": _utc_text(value.preview.response_expires_at),
    }


def present_calendar_workbench_commit(
    value: CalendarFormalPublicationCommit,
) -> dict[str, object]:
    """Return a bounded publication outcome without IDs, hashes, seals, or Audit."""

    if type(value) is not CalendarFormalPublicationCommit:
        raise TypeError("Calendar workbench commit must use its exact DTO")
    value.__post_init__()
    record = value.record
    seal = record.seal
    transition_labels = {
        "first_publish": "日历已首次发布",
        "forward_publish": "日历版本已更新",
        "exact_current_replay": "当前日历版本已再次确认",
    }
    return {
        "publication_status": "published",
        "must_not_execute": True,
        "must_not_use_for_decision": True,
        "blocked_reason": "exchange_calendar_reference_only",
        "freshness": {
            "source_observed_at": None,
            "source_available_at": None,
            "source_time_status": "not_provided",
        },
        "reliability": "audited_calendar_reference",
        "exchange": seal.exchange,
        "coverage_start": seal.snapshot.coverage_start.isoformat(),
        "coverage_end": seal.snapshot.coverage_end.isoformat(),
        "transition_label": transition_labels[value.transition.value],
        "published_at": _utc_text(record.published_at),
        "first_seen_at": _utc_text(seal.snapshot_first_seen_at),
        "source_published_at": _optional_utc_text(seal.snapshot.source_published_at),
        "response_expires_at": _utc_text(record.window.response_expires_at),
        "checked_at": _utc_text(value.post_audit_checked_at),
        "message": "日历发布已完成，但当前数据仍仅供参考，不可用于交易或投资决策。",
    }


def present_calendar_workbench_scope(
    value: CalendarWorkbenchScopeContext,
) -> dict[str, object]:
    """Project selected non-secret metadata without asserting runtime readiness."""

    if type(value) is not CalendarWorkbenchScopeContext:
        raise TypeError("Calendar workbench scope must use its exact DTO")
    value.__post_init__()
    metadata = value.metadata
    return {
        "metadata_status": value.metadata_status.value,
        "blocked_reason": value.blocked_reason,
        "secret_runtime_status": value.secret_runtime_status.value,
        "current_pointer_status": value.current_pointer_status.value,
        "known_at": _utc_text(value.known_at),
        "metadata": None if metadata is None else _scope_metadata_payload(metadata),
        "message": _scope_message(value.metadata_status),
    }


def present_calendar_workbench_current(
    value: CalendarWorkbenchCurrentReadResult,
) -> dict[str, object]:
    """Project exact current days without exposing storage or Audit identities."""

    if type(value) is not CalendarWorkbenchCurrentReadResult:
        raise TypeError("Calendar workbench current read must use its exact DTO")
    value.__post_init__()
    if value.scope.metadata_status is CalendarWorkbenchScopeMetadataStatus.BLOCKED:
        return {
            "configuration_status": "blocked",
            "current_status": "blocked",
            "blocked_reason": value.scope.blocked_reason,
            "current": None,
            "message": "当前日历捕获配置不可用，已阻断当前日历读取，请管理员检查配置。",
        }
    current = value.current
    if current is None:
        return {
            "configuration_status": "metadata_selected",
            "current_status": "not_found",
            "blocked_reason": "CALENDAR_CURRENT_PUBLICATION_NOT_FOUND",
            "current": None,
            "message": "当前配置数据集没有已发布的参考日历。",
        }
    seal = current.record.seal
    return {
        "configuration_status": "metadata_selected",
        "current_status": "published",
        "blocked_reason": None,
        "current": {
            "publication_status": "published",
            "must_not_execute": True,
            "must_not_use_for_decision": True,
            "blocked_reason": "exchange_calendar_reference_only",
            "freshness": {
                "source_observed_at": None,
                "source_available_at": None,
                "source_time_status": "not_provided",
            },
            "reliability": "audited_calendar_reference",
            "exchange": value.exchange,
            "coverage_start": seal.snapshot.coverage_start.isoformat(),
            "coverage_end": seal.snapshot.coverage_end.isoformat(),
            "as_of": _utc_text(current.as_of),
            "first_seen_at": _utc_text(seal.snapshot_first_seen_at),
            "source_published_at": _optional_utc_text(seal.snapshot.source_published_at),
            "response_expires_at": _utc_text(current.record.window.response_expires_at),
            "calendar_days": [day.to_payload() for day in seal.snapshot.days],
        },
        "message": "当前发布日历仅供参考，不可用于交易或投资决策。",
    }


def _scope_metadata_payload(value: CalendarWorkbenchScopeMetadata) -> dict[str, object]:
    """Return the catalog's explicit non-secret calendar configuration projection."""

    value.__post_init__()
    return {
        "dataset_key": value.dataset_key,
        "contract_version": value.contract_version,
        "schema_version": value.schema_version,
        "calendar_response_max_age_seconds": value.calendar_response_max_age_seconds,
        "policy_identity": value.policy_identity,
        "policy_version": value.policy_version,
        "member_codec_version": value.member_codec_version.value,
        "provider_id": value.provider_id,
        "provider": value.provider,
        "capability": value.capability,
        "validator_key": value.validator_key,
    }


def _scope_message(status_value: CalendarWorkbenchScopeMetadataStatus) -> str:
    """Give users a bounded next step without claiming credentials were checked."""

    if status_value is CalendarWorkbenchScopeMetadataStatus.METADATA_SELECTED:
        return "日历捕获配置已读取；凭据、数据源运行状态和当前发布状态尚未检查。"
    return "未能选出唯一可用的日历捕获配置，请管理员检查数据集、策略和服务绑定。"


def _utc_text(value: datetime) -> str:
    """Encode a validated UTC instant in stable ISO-8601 form."""

    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _optional_utc_text(value: datetime | None) -> str | None:
    """Preserve an absent source-published time as unknown rather than inventing one."""

    return None if value is None else _utc_text(value)


__all__ = [
    "WORKBENCH_CONFIRM_ACTION_KEY",
    "present_calendar_workbench_commit",
    "present_calendar_workbench_continuation",
    "present_calendar_workbench_current",
    "present_calendar_workbench_preview",
    "present_calendar_workbench_scope",
]
