from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from apps.task_monitor.management.commands import (
    repair_personal_readiness_evidence as command_module,
)


def _accepted_payload(*, target_date: str) -> dict:
    return {
        "schema_version": "test",
        "status": "ok",
        "target_date": target_date,
        "generated_at": f"{target_date}T18:00:00+08:00",
        "inputs": {
            "user_id": None,
            "account_id": None,
            "max_qlib_staleness_days": 5,
            "run_workspace_refresh": True,
            "include_weekly_advisor": True,
            "persist_risk_report": True,
            "allow_unclosed_target_date": False,
            "trigger_source": "repair",
            "trigger_task_id": None,
            "trigger_task_name": command_module.REPAIR_TRIGGER_NAME,
        },
        "operation_context": {
            "mode": "formal",
            "target_date_closed": True,
            "allow_unclosed_target_date": False,
            "trigger_source": "repair",
            "trigger_task_id": None,
            "trigger_task_name": command_module.REPAIR_TRIGGER_NAME,
        },
        "summary": {
            "system_status": "ok",
            "qlib_status": "ok",
            "workspace_status": "ok",
            "target_count": 1,
        },
        "qlib": {
            "status": "ok",
            "check_only": True,
            "command": "build_qlib_data --check-only",
        },
        "system": {
            "status": "ok",
            "checks": {
                "decision_data": {
                    "status": "ok",
                    "readiness_status": "ok",
                    "must_not_use_for_decision": False,
                    "quotes": {
                        "510300.SH": {
                            "status": "ok",
                            "is_stale": False,
                            "freshness_status": "fresh",
                            "must_not_use_for_decision": False,
                        }
                    },
                },
                "alpha_workspace_consistency": {"status": "ok"},
            },
        },
        "workspace": {
            "status": "ok",
            "result": {
                "components": {
                    "regime_snapshot": {"status": "success"},
                    "pulse_snapshot": {"status": "success", "is_reliable": True},
                    "action_recommendation": {"status": "success"},
                }
            },
        },
        "accounts": [
            {
                "status": "ok",
                "account_id": 613,
                "risk_center_daily_report": {
                    "status": "ok",
                    "report_id": "risk-613",
                    "pre_trade_check": {"status": "ok"},
                    "post_investment_check": {"passed": True},
                },
                "auto_advisor": {"status": "ok"},
            }
        ],
    }


def test_repair_personal_readiness_evidence_archives_and_rewrites(monkeypatch, tmp_path):
    target_date = date(2026, 7, 7)
    json_path = tmp_path / "2026-07-07-personal-readiness.json"
    markdown_path = tmp_path / "2026-07-07-personal-readiness.md"
    json_path.write_text(
        json.dumps(
            {
                "schema_version": "test",
                "status": "ok",
                "target_date": "2026-07-07",
                "generated_at": "2026-07-08T12:00:00+08:00",
                "inputs": {
                    "user_id": None,
                    "account_id": None,
                    "max_qlib_staleness_days": 5,
                    "run_workspace_refresh": True,
                    "include_weekly_advisor": True,
                    "persist_risk_report": True,
                    "allow_unclosed_target_date": False,
                    "trigger_source": "scheduler",
                    "trigger_task_id": "task-1",
                    "trigger_task_name": "apps.task_monitor.application.tasks.run_personal_readiness_daily_task",
                },
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                    "trigger_source": "scheduler",
                    "trigger_task_id": "task-1",
                    "trigger_task_name": "apps.task_monitor.application.tasks.run_personal_readiness_daily_task",
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 1,
                },
                "qlib": {
                    "status": "ok",
                    "check_only": True,
                    "command": "build_qlib_data --check-only",
                },
                "system": {
                    "status": "ok",
                    "checks": {
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "ok",
                            "must_not_use_for_decision": False,
                            "quotes": {
                                "510300.SH": {
                                    "status": "ok",
                                    "is_stale": False,
                                    "freshness_status": "fresh",
                                    "must_not_use_for_decision": False,
                                }
                            },
                        },
                        "alpha_workspace_consistency": {"status": "warning"},
                    },
                },
                "workspace": {
                    "status": "ok",
                    "result": {
                        "components": {
                            "regime_snapshot": {"status": "success"},
                            "pulse_snapshot": {"status": "success", "is_reliable": True},
                            "action_recommendation": {"status": "success"},
                        }
                    },
                },
                "accounts": [
                    {
                        "status": "ok",
                        "account_id": 613,
                        "risk_center_daily_report": {
                            "status": "ok",
                            "report_id": "risk-613",
                            "pre_trade_check": {"status": "ok"},
                            "post_investment_check": {"passed": True},
                        },
                        "auto_advisor": {"status": "ok"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    markdown_path.write_text("# original evidence", encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_collect(**kwargs):
        captured.update(kwargs)
        return _accepted_payload(target_date=kwargs["target_date"].isoformat())

    monkeypatch.setattr(command_module, "collect_personal_readiness_evidence", fake_collect)

    payload = command_module.repair_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=target_date,
        reason="alpha_workspace_fix",
    )

    assert payload["status"] == "accepted"
    assert payload["original_acceptance"]["accepted"] is False
    assert payload["repaired_acceptance"]["accepted"] is True
    assert captured == {
        "target_date": target_date,
        "user_id": None,
        "account_id": None,
        "max_qlib_staleness_days": 5,
        "run_workspace_refresh": True,
        "include_weekly_advisor": True,
        "persist_risk_report": True,
        "allow_unclosed_target_date": False,
        "trigger_source": "repair",
        "trigger_task_id": None,
        "trigger_task_name": command_module.REPAIR_TRIGGER_NAME,
    }

    archived_json = Path(str(payload["archive"]["json"]))
    archived_markdown = Path(str(payload["archive"]["markdown"]))
    manifest_path = Path(str(payload["archive"]["manifest"]))
    assert archived_json.exists()
    assert archived_markdown.exists()
    assert manifest_path.exists()
    assert json.loads(archived_json.read_text(encoding="utf-8"))["system"]["checks"][
        "alpha_workspace_consistency"
    ]["status"] == "warning"
    repaired = json.loads(json_path.read_text(encoding="utf-8"))
    assert repaired["operation_context"]["trigger_source"] == "repair"
    assert repaired["repair_context"]["reason"] == "alpha_workspace_fix"
    assert repaired["repair_context"]["original_acceptance"]["accepted"] is False
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["repaired_acceptance"] == {
        "accepted": True,
        "reason": "accepted",
    }


def test_inspect_personal_readiness_evidence_suggests_historical_repair(tmp_path):
    evidence_path = tmp_path / "2026-07-07-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "test",
                "status": "ok",
                "target_date": "2026-07-07",
                "generated_at": "2026-07-08T12:00:00+08:00",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                    "trigger_source": "scheduler",
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 1,
                },
                "qlib": {
                    "status": "ok",
                    "check_only": True,
                    "command": "build_qlib_data --check-only",
                },
                "system": {
                    "status": "ok",
                    "checks": {
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "ok",
                            "must_not_use_for_decision": False,
                            "quotes": {
                                "510300.SH": {
                                    "status": "ok",
                                    "is_stale": False,
                                    "freshness_status": "fresh",
                                    "must_not_use_for_decision": False,
                                }
                            },
                        },
                        "alpha_workspace_consistency": {"status": "warning"},
                    },
                },
                "workspace": {
                    "status": "ok",
                    "result": {
                        "components": {
                            "regime_snapshot": {"status": "success"},
                            "pulse_snapshot": {"status": "success", "is_reliable": True},
                            "action_recommendation": {"status": "success"},
                        }
                    },
                },
                "accounts": [
                    {
                        "status": "ok",
                        "account_id": 613,
                        "risk_center_daily_report": {
                            "status": "ok",
                            "report_id": "risk-613",
                            "pre_trade_check": {"status": "ok"},
                            "post_investment_check": {"passed": True},
                        },
                        "auto_advisor": {"status": "ok"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    from apps.task_monitor.management.commands import inspect_personal_readiness_evidence as inspect_module

    payload = inspect_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 7),
    )

    assert payload["status"] == "blocked"
    assert payload["next_action"]["action"] == "repair_historical_evidence"
    assert (
        "python manage.py repair_personal_readiness_evidence --target-date 2026-07-07 --json"
        == payload["next_action"]["command"]
    )
