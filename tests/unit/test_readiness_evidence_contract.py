"""Contract tests for shared readiness evidence normalization."""

from apps.task_monitor.management.readiness_evidence_contract import (
    classify_evidence_payload,
    decision_quote_freshness_status,
    workspace_core_status,
)


def test_classify_evidence_payload_preserves_legacy_acceptance() -> None:
    classification = classify_evidence_payload({})

    assert classification == {
        "formal_evidence": None,
        "evidence_mode": "legacy_without_operation_context",
        "acceptance_candidate": True,
        "trigger_source": None,
        "trigger_task_id": None,
        "trigger_task_name": None,
    }


def test_classify_evidence_payload_preserves_formal_task_provenance() -> None:
    classification = classify_evidence_payload(
        {
            "operation_context": {
                "mode": "formal",
                "target_date_closed": True,
                "allow_unclosed_target_date": False,
                "trigger_source": "scheduler",
                "trigger_task_id": "task-1",
                "trigger_task_name": (
                    "apps.task_monitor.application.tasks." "run_personal_readiness_daily_task"
                ),
            }
        }
    )

    assert classification["formal_evidence"] is True
    assert classification["acceptance_candidate"] is True
    assert classification["trigger_source"] == "scheduler"
    assert classification["trigger_task_id"] == "task-1"
    assert classification["trigger_task_name"].startswith("apps.task_monitor")


def test_quote_and_workspace_classifiers_keep_existing_status_semantics() -> None:
    quote_status = decision_quote_freshness_status(
        {
            "quotes": {
                "000001.SH": {
                    "status": "ok",
                    "freshness_status": "latest_completed_session",
                    "is_stale": False,
                }
            }
        }
    )
    workspace_status = workspace_core_status(
        {
            "regime_snapshot": {"status": "success"},
            "pulse_snapshot": {"status": "success", "is_reliable": True},
            "action_recommendation": {"status": "success"},
        }
    )

    assert quote_status == "ok"
    assert workspace_status == "ok"
