from __future__ import annotations

import json
from datetime import date
from hashlib import sha256

import pytest
from django.core.management import CommandError

from apps.task_monitor.management import auto_advisor_weekly_scheduler_status as weekly_module
from apps.task_monitor.management.commands import (
    inspect_personal_readiness_evidence as command_module,
)


def _fresh_decision_quotes(*, freshness_status: str = "fresh"):
    return {
        "510300.SH": {
            "status": "ok",
            "is_stale": False,
            "freshness_status": freshness_status,
            "must_not_use_for_decision": False,
        },
        "000300.SH": {
            "status": "ok",
            "is_stale": False,
            "freshness_status": freshness_status,
            "must_not_use_for_decision": False,
        },
    }


def _qlib_ok_evidence():
    return {
        "status": "ok",
        "check_only": True,
        "command": "build_qlib_data --check-only",
    }


def test_inspect_personal_readiness_evidence_accepts_formal_ok_payload(tmp_path):
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "test",
                "status": "ok",
                "target_date": "2026-07-01",
                "generated_at": "2026-07-01T16:00:00+08:00",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 1,
                },
                "qlib": _qlib_ok_evidence(),
                "system": {
                    "status": "ok",
                    "checks": {
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "ok",
                            "must_not_use_for_decision": False,
                            "quotes": _fresh_decision_quotes(),
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
                        "account_id": 101,
                        "risk_center_daily_report": {
                            "status": "ok",
                            "report_id": "risk-2026-07-01-101",
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

    payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 1),
    )

    assert payload["status"] == "accepted"
    assert payload["acceptance"]["accepted"] is True
    assert payload["acceptance"]["reason"] == "accepted"
    assert payload["evidence"]["target_date"] == "2026-07-01"
    raw = evidence_path.read_bytes()
    assert payload["file"]["path"] == str(evidence_path)
    assert payload["file"]["size_bytes"] == len(raw)
    assert payload["file"]["sha256"] == sha256(raw).hexdigest()
    assert payload["blockers"] == []
    assert payload["observations"] == []
    assert payload["next_action"]["action"] == "continue_window"


def test_inspect_personal_readiness_evidence_accepts_latest_completed_session_quotes(tmp_path):
    evidence_path = tmp_path / "2026-07-06-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "test",
                "status": "ok",
                "target_date": "2026-07-06",
                "generated_at": "2026-07-07T08:50:00+08:00",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 1,
                },
                "qlib": _qlib_ok_evidence(),
                "system": {
                    "status": "ok",
                    "checks": {
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "ok",
                            "must_not_use_for_decision": False,
                            "quotes": _fresh_decision_quotes(
                                freshness_status="latest_completed_session"
                            ),
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
                        "account_id": 101,
                        "risk_center_daily_report": {
                            "status": "ok",
                            "report_id": "risk-2026-07-06-101",
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

    payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 6),
    )

    assert payload["status"] == "accepted"
    assert payload["acceptance"]["accepted"] is True
    assert payload["blockers"] == []


def test_inspect_personal_readiness_evidence_reports_risk_persistence_observation(tmp_path):
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "test",
                "status": "ok",
                "target_date": "2026-07-01",
                "generated_at": "2026-07-01T16:00:00+08:00",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 1,
                },
                "qlib": _qlib_ok_evidence(),
                "system": {
                    "status": "ok",
                    "checks": {
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "ok",
                            "must_not_use_for_decision": False,
                            "quotes": _fresh_decision_quotes(),
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
                        "account_id": 101,
                        "risk_center_daily_report": {
                            "status": "ok",
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

    payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 1),
    )

    assert payload["status"] == "accepted"
    assert payload["blockers"] == []
    observations = {item["component"]: item for item in payload["observations"]}
    assert observations["risk_center_daily_report_persistence"] == {
        "component": "risk_center_daily_report_persistence",
        "account_id": 101,
        "status": "missing",
        "reason": "account 101 risk report is ok but has no persisted report_id",
    }
    assert payload["follow_up_actions"] == [
        {
            "component": "risk_center_daily_report_persistence",
            "action": "verify_scheduled_risk_report_persistence",
            "reason": (
                "risk reports are accepted but not persisted; final readiness "
                "acceptance requires report_id coverage"
            ),
            "target_date": "2026-07-01",
            "account_ids": [101],
            "command": "python manage.py show_personal_readiness_status --json --strict-monitor",
        }
    ]


def test_inspect_personal_readiness_evidence_reports_weekly_persistence_observation(
    monkeypatch,
    tmp_path,
):
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "test",
                "status": "ok",
                "target_date": "2026-07-01",
                "generated_at": "2026-07-01T16:00:00+08:00",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 1,
                },
                "qlib": _qlib_ok_evidence(),
                "system": {
                    "status": "ok",
                    "checks": {
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "ok",
                            "must_not_use_for_decision": False,
                            "quotes": _fresh_decision_quotes(),
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
                        "account_id": 101,
                        "risk_center_daily_report": {
                            "status": "ok",
                            "report_id": "risk-2026-07-01-101",
                            "pre_trade_check": {"status": "ok"},
                            "post_investment_check": {"passed": True},
                        },
                        "auto_advisor": {
                            "status": "ok",
                            "weekly_report": {
                                "status": "ok",
                                "week": {"as_of": "2026-07-01"},
                            },
                            "weekly_report_persistence": {
                                "status": "warning",
                                "reason": "no persisted weekly report found for 2026-07-01",
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 1),
    )

    assert payload["status"] == "accepted"
    observations = {item["component"]: item for item in payload["observations"]}
    assert observations["auto_advisor_weekly_persistence"]["status"] == "not_due"
    assert observations["auto_advisor_weekly_persistence"]["account_id"] == 101
    assert (
        observations["auto_advisor_weekly_persistence"]["reason"]
        == "weekly_report_not_scheduled_for_target_date"
    )
    assert observations["auto_advisor_weekly_persistence"]["scheduled_for"] is None
    assert (
        observations["auto_advisor_weekly_persistence"]["next_scheduled_for"]
        == "2026-07-03T17:30:00+08:00"
    )
    assert payload["follow_up_actions"] == []

    monkeypatch.setattr(
        weekly_module,
        "EXPECTED_AUTO_ADVISOR_WEEKLY_DAY_OF_WEEK",
        "wed",
    )
    payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 1),
    )

    observations = {item["component"]: item for item in payload["observations"]}
    assert observations["auto_advisor_weekly_persistence"]["status"] == "warning"
    assert payload["follow_up_actions"] == [
        {
            "component": "auto_advisor_weekly_persistence",
            "action": "verify_scheduled_weekly_report_persistence",
            "reason": (
                "weekly advisor output is present but persistence proof is "
                "missing or warning; final readiness acceptance requires "
                "scheduled weekly report persistence"
            ),
            "target_date": "2026-07-01",
            "account_ids": [101],
            "command": "python manage.py show_personal_readiness_status --json --strict-monitor",
        }
    ]


def test_inspect_personal_readiness_evidence_resolves_weekly_warning_with_current_db_proof(
    monkeypatch,
    tmp_path,
):
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "test",
                "status": "ok",
                "target_date": "2026-07-01",
                "generated_at": "2026-07-01T16:10:00+08:00",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 1,
                },
                "qlib": _qlib_ok_evidence(),
                "system": {
                    "status": "ok",
                    "checks": {
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "ok",
                            "must_not_use_for_decision": False,
                            "quotes": _fresh_decision_quotes(),
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
                        "user_id": 7,
                        "status": "ok",
                        "account_id": 101,
                        "risk_center_daily_report": {
                            "status": "ok",
                            "report_id": "risk-2026-07-01-101",
                            "pre_trade_check": {"status": "ok"},
                            "post_investment_check": {"passed": True},
                        },
                        "auto_advisor": {
                            "status": "ok",
                            "weekly_report": {
                                "status": "ok",
                                "week": {"as_of": "2026-07-01"},
                            },
                            "weekly_report_persistence": {
                                "status": "warning",
                                "reason": "no persisted weekly report found for 2026-07-01",
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        weekly_module,
        "EXPECTED_AUTO_ADVISOR_WEEKLY_DAY_OF_WEEK",
        "wed",
    )
    monkeypatch.setattr(
        command_module,
        "_load_current_post_evidence_persistence_if_target_matches",
        lambda *, output_dir, target_date: {
            "status": "ok",
            "target_date": target_date,
            "auto_advisor_weekly_report": {
                "status": "ok",
                "records": [
                    {
                        "user_id": 7,
                        "account_id": 101,
                        "report_id": 88,
                        "matched_notification_count": 1,
                        "delivered_notification_count": 1,
                        "ok": True,
                    }
                ],
            },
        },
    )

    payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 1),
    )

    observations = {item["component"]: item for item in payload["observations"]}
    weekly_observation = observations["auto_advisor_weekly_persistence"]
    assert weekly_observation["status"] == "resolved_after_evidence"
    assert weekly_observation["historical_status"] == "warning"
    assert weekly_observation["reason"] == "post_evidence_weekly_report_persisted"
    assert weekly_observation["report_id"] == 88
    assert weekly_observation["delivered_notification_count"] == 1
    assert payload["follow_up_actions"] == []


def test_inspect_personal_readiness_evidence_explains_qlib_blocker(tmp_path):
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "status": "warning",
                "target_date": "2026-07-01",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "warning",
                    "workspace_status": "ok",
                    "target_count": 1,
                },
                "system": {
                    "status": "ok",
                    "checks": {
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "ok",
                            "must_not_use_for_decision": False,
                            "quotes": _fresh_decision_quotes(),
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
                "qlib": {
                    "status": "warning",
                    "error": "qlib stale",
                },
                "accounts": [
                    {
                        "status": "ok",
                        "account_id": 101,
                        "risk_center_daily_report": {
                            "status": "ok",
                            "report_id": "risk-2026-07-01-101",
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

    payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 1),
    )

    assert payload["status"] == "blocked"
    assert payload["acceptance"]["accepted"] is False
    assert payload["acceptance"]["reason"] == "overall status is warning"
    blocker_components = {blocker["component"] for blocker in payload["blockers"]}
    assert "summary.qlib_status" in blocker_components
    assert "qlib" in blocker_components
    assert payload["next_action"]["action"] == "refresh_qlib_then_rerun"
    assert "build_qlib_data --target-date 2026-07-01" in payload["next_action"]["command"]


def test_inspect_personal_readiness_evidence_reports_degradation_observations(
    monkeypatch,
    tmp_path,
):
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "test",
                "status": "ok",
                "target_date": "2026-07-01",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 1,
                },
                "qlib": _qlib_ok_evidence(),
                "system": {
                    "status": "ok",
                    "checks": {
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "ok",
                            "must_not_use_for_decision": False,
                            "quotes": _fresh_decision_quotes(),
                            "market_thermometer": {
                                "data_source": "degraded",
                                "stale_components": ["etf_net_flow"],
                                "proxy_components": [
                                    {
                                        "component_key": "etf_net_flow",
                                        "indicator_code": "CN_A_ETF_NET_FLOW",
                                        "reporting_period": "2026-07-01",
                                        "source": "data_center_consensus",
                                        "proxy": "tushare_etf_share_size_delta",
                                        "verification_status": "fallback_proxy",
                                    }
                                ],
                            },
                            "skipped_latest_market_thermometer": {
                                "observed_at": "2026-07-01",
                                "status": "blocked",
                                "blocked_reason": "valid components below threshold",
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
                            "macro_sync": {
                                "status": "success",
                                "synced_count": 11,
                                "skipped_count": 54,
                            },
                            "rotation_signals": {
                                "status": "success",
                                "successful": 3,
                                "skipped": 3,
                                "failed": 0,
                            },
                        },
                    },
                },
                "accounts": [
                    {
                        "status": "ok",
                        "account_id": 101,
                        "risk_center_daily_report": {
                            "status": "ok",
                            "report_id": "risk-2026-07-01-101",
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
    monkeypatch.setattr(
        command_module,
        "_load_current_decision_data_if_needed",
        lambda *, payload: None,
    )

    payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 1),
    )

    assert payload["status"] == "accepted"
    assert payload["acceptance"]["accepted"] is True
    assert payload["blockers"] == []
    observations = {item["component"]: item for item in payload["observations"]}
    assert observations["workspace.macro_sync"]["status"] == "degraded"
    assert "skipped 54" in observations["workspace.macro_sync"]["reason"]
    assert observations["workspace.rotation_signals"]["status"] == "degraded"
    assert "skipped 3" in observations["workspace.rotation_signals"]["reason"]
    assert observations["decision_data.market_thermometer"]["status"] == "degraded"
    assert "etf_net_flow" in observations["decision_data.market_thermometer"]["reason"]
    proxy_observation = observations["decision_data.market_thermometer_proxy"]
    assert proxy_observation["status"] == "audited_proxy"
    assert proxy_observation["proxy_component_count"] == 1
    assert "etf_net_flow:tushare_etf_share_size_delta" in proxy_observation["reason"]
    assert proxy_observation["proxy_components"][0]["verification_status"] == "fallback_proxy"
    assert observations["decision_data.skipped_latest_market_thermometer"]["status"] == "blocked"
    assert "2026-07-01" in observations["decision_data.skipped_latest_market_thermometer"]["reason"]
    assert payload["follow_up_actions"] == [
        {
            "component": "workspace.macro_sync",
            "action": "repair_decision_data_reliability",
            "reason": (
                "macro sync skipped inputs; repair decision-grade data before "
                "the next formal readiness run"
            ),
            "target_date": "2026-07-01",
            "command": (
                "python manage.py repair_decision_data_reliability "
                "--target-date 2026-07-01 --strict"
            ),
        },
        {
            "component": "decision_data.market_thermometer",
            "action": "refresh_market_thermometer",
            "reason": (
                "market thermometer evidence is degraded or skipped; sync inputs "
                "and recalculate the snapshot"
            ),
            "target_date": "2026-07-01",
            "command": (
                "python manage.py calculate_market_thermometer "
                "--as-of-date 2026-07-01 --json"
            ),
        },
    ]

    monkeypatch.setattr(
        command_module,
        "_load_current_decision_data_if_needed",
        lambda *, payload: {
            "market_thermometer": {
                "status": "ok",
                "observed_at": "2026-07-01",
                "data_source": "calculated",
                "must_not_use_for_decision": False,
                "stale_components": [],
                "missing_components": [],
                "valid_component_count": 6,
                "proxy_components": [
                    {
                        "component_key": "etf_net_flow",
                        "proxy": "tushare_etf_share_size_delta",
                    }
                ],
            }
        },
    )

    resolved_payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 1),
    )
    resolved_observations = {
        item["component"]: item for item in resolved_payload["observations"]
    }
    assert (
        resolved_observations["decision_data.market_thermometer"]["status"]
        == "resolved_after_evidence"
    )
    assert (
        resolved_observations["decision_data.skipped_latest_market_thermometer"][
            "status"
        ]
        == "resolved_after_evidence"
    )
    assert resolved_payload["follow_up_actions"] == [
        {
            "component": "workspace.macro_sync",
            "action": "repair_decision_data_reliability",
            "reason": (
                "macro sync skipped inputs; repair decision-grade data before "
                "the next formal readiness run"
            ),
            "target_date": "2026-07-01",
            "command": (
                "python manage.py repair_decision_data_reliability "
                "--target-date 2026-07-01 --strict"
            ),
        }
    ]


def test_inspect_personal_readiness_evidence_suppresses_repaired_macro_sync_follow_up(
    tmp_path, monkeypatch
):
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "target_date": "2026-07-01",
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 0,
                },
                "operation_context": {
                    "mode": "formal",
                    "trigger_source": "scheduler",
                    "target_date_closed": True,
                },
                "system": {
                    "checks": {
                        "qlib": _qlib_ok_evidence(),
                        "workspace_core": {"status": "ok"},
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "ok",
                            "must_not_use_for_decision": False,
                            "quotes": _fresh_decision_quotes(),
                            "market_thermometer": {
                                "status": "ok",
                                "data_source": "calculated",
                                "stale_components": [],
                                "missing_components": [],
                            },
                        },
                    },
                },
                "workspace": {
                    "status": "ok",
                    "result": {
                        "components": {
                            "macro_sync": {
                                "status": "success",
                                "synced_count": 4,
                                "skipped_count": 51,
                            },
                        },
                    },
                },
                "accounts": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        command_module,
        "_resolve_current_macro_sync_resolution",
        lambda *, target_date: {
            "status": "ready",
            "decision_grade": "decision_safe",
            "indicator_count": 6,
        },
    )

    payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 1),
    )

    observations = {item["component"]: item for item in payload["observations"]}
    assert observations["workspace.macro_sync"]["status"] == "resolved_after_evidence"
    assert observations["workspace.macro_sync"]["current_status"] == {
        "status": "ready",
        "decision_grade": "decision_safe",
        "indicator_count": 6,
    }
    assert payload["follow_up_actions"] == []


def test_inspect_personal_readiness_evidence_suggests_account_repair(tmp_path):
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "target_date": "2026-07-01",
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 0,
                },
                "accounts": [],
            }
        ),
        encoding="utf-8",
    )

    payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        path=evidence_path,
    )

    assert payload["status"] == "blocked"
    assert payload["acceptance"]["reason"] == "target_count is zero"
    blocker_components = {blocker["component"] for blocker in payload["blockers"]}
    assert "summary.target_count" in blocker_components
    assert "accounts" in blocker_components
    observation_components = {item["component"] for item in payload["observations"]}
    assert "operation_context" in observation_components
    assert payload["next_action"]["action"] == "repair_accounts_then_rerun"
    assert "--repair-accounts" in payload["next_action"]["command"]


def test_inspect_personal_readiness_evidence_blocks_formal_missing_pre_trade(tmp_path):
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "test",
                "status": "ok",
                "target_date": "2026-07-01",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 1,
                },
                "qlib": _qlib_ok_evidence(),
                "system": {
                    "status": "ok",
                    "checks": {
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "ok",
                            "must_not_use_for_decision": False,
                            "quotes": _fresh_decision_quotes(),
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
                        "account_id": 101,
                        "risk_center_daily_report": {"status": "ok"},
                        "auto_advisor": {"status": "ok"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 1),
    )

    assert payload["status"] == "blocked"
    assert payload["acceptance"]["accepted"] is False
    assert payload["acceptance"]["reason"] == ("account 101 pre-trade risk status is missing")
    blockers = {item["component"]: item for item in payload["blockers"]}
    assert blockers["risk_center_pre_trade_check"]["status"] is None


def test_inspect_personal_readiness_evidence_blocks_formal_missing_decision_data(tmp_path):
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "test",
                "status": "ok",
                "target_date": "2026-07-01",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 1,
                },
                "qlib": _qlib_ok_evidence(),
                "system": {
                    "status": "ok",
                    "checks": {
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
                        "account_id": 101,
                        "risk_center_daily_report": {
                            "status": "ok",
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

    payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 1),
    )

    assert payload["status"] == "blocked"
    assert payload["acceptance"]["accepted"] is False
    assert payload["acceptance"]["reason"] == "decision_data readiness evidence is missing"
    blockers = {item["component"]: item for item in payload["blockers"]}
    assert blockers["decision_data"]["status"] == "missing"


def test_inspect_personal_readiness_evidence_blocks_formal_missing_qlib_evidence(
    tmp_path,
):
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "test",
                "status": "ok",
                "target_date": "2026-07-01",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 1,
                },
                "system": {
                    "status": "ok",
                    "checks": {
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "ok",
                            "must_not_use_for_decision": False,
                            "quotes": _fresh_decision_quotes(),
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
                        "account_id": 101,
                        "risk_center_daily_report": {
                            "status": "ok",
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

    payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 1),
    )

    assert payload["status"] == "blocked"
    assert payload["acceptance"]["accepted"] is False
    assert payload["acceptance"]["reason"] == "qlib readiness evidence is missing"
    blockers = {item["component"]: item for item in payload["blockers"]}
    assert blockers["qlib"]["status"] == "missing"


def test_inspect_personal_readiness_evidence_blocks_formal_missing_quote_freshness(
    tmp_path,
):
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "test",
                "status": "ok",
                "target_date": "2026-07-01",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 1,
                },
                "qlib": _qlib_ok_evidence(),
                "system": {
                    "status": "ok",
                    "checks": {
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "ok",
                            "must_not_use_for_decision": False,
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
                        "account_id": 101,
                        "risk_center_daily_report": {
                            "status": "ok",
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

    payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 1),
    )

    assert payload["status"] == "blocked"
    blockers = {item["component"]: item for item in payload["blockers"]}
    assert blockers["decision_data.quotes"]["status"] == "missing"


def test_inspect_personal_readiness_evidence_blocks_formal_missing_alpha_workspace(
    tmp_path,
):
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "test",
                "status": "ok",
                "target_date": "2026-07-01",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 1,
                },
                "qlib": _qlib_ok_evidence(),
                "system": {
                    "status": "ok",
                    "checks": {
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "ok",
                            "must_not_use_for_decision": False,
                            "quotes": _fresh_decision_quotes(),
                        }
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
                        "account_id": 101,
                        "risk_center_daily_report": {
                            "status": "ok",
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

    payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 1),
    )

    assert payload["status"] == "blocked"
    assert payload["acceptance"]["accepted"] is False
    assert payload["acceptance"]["reason"] == ("alpha_workspace_consistency evidence is missing")
    blockers = {item["component"]: item for item in payload["blockers"]}
    assert blockers["alpha_workspace_consistency"]["status"] == "missing"


def test_inspect_personal_readiness_evidence_blocks_formal_missing_workspace_core(
    tmp_path,
):
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "test",
                "status": "ok",
                "target_date": "2026-07-01",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 1,
                },
                "qlib": _qlib_ok_evidence(),
                "system": {
                    "status": "ok",
                    "checks": {
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "ok",
                            "must_not_use_for_decision": False,
                            "quotes": _fresh_decision_quotes(),
                        },
                        "alpha_workspace_consistency": {"status": "ok"},
                    },
                },
                "accounts": [
                    {
                        "status": "ok",
                        "account_id": 101,
                        "risk_center_daily_report": {
                            "status": "ok",
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

    payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 1),
    )

    assert payload["status"] == "blocked"
    assert payload["acceptance"]["accepted"] is False
    assert payload["acceptance"]["reason"] == "workspace core evidence status is missing"
    blockers = {item["component"]: item for item in payload["blockers"]}
    assert blockers["workspace.core"]["status"] == "missing"


def test_inspect_personal_readiness_evidence_blocks_formal_missing_post_investment(
    tmp_path,
):
    evidence_path = tmp_path / "2026-07-01-personal-readiness.json"
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "test",
                "status": "ok",
                "target_date": "2026-07-01",
                "operation_context": {
                    "mode": "formal",
                    "target_date_closed": True,
                    "allow_unclosed_target_date": False,
                },
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 1,
                },
                "qlib": _qlib_ok_evidence(),
                "system": {
                    "status": "ok",
                    "checks": {
                        "decision_data": {
                            "status": "ok",
                            "readiness_status": "ok",
                            "must_not_use_for_decision": False,
                            "quotes": _fresh_decision_quotes(),
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
                        "account_id": 101,
                        "risk_center_daily_report": {
                            "status": "ok",
                            "pre_trade_check": {"status": "ok"},
                        },
                        "auto_advisor": {"status": "ok"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = command_module.inspect_personal_readiness_evidence(
        output_dir=tmp_path,
        target_date=date(2026, 7, 1),
    )

    assert payload["status"] == "blocked"
    assert payload["acceptance"]["accepted"] is False
    assert payload["acceptance"]["reason"] == ("account 101 post-investment risk passed is None")
    blockers = {item["component"]: item for item in payload["blockers"]}
    assert blockers["risk_center_post_investment_check"]["status"] is None


def test_inspect_personal_readiness_evidence_uses_latest_file_by_default(tmp_path):
    old_path = tmp_path / "2026-06-30-personal-readiness.json"
    old_path.write_text(
        json.dumps({"status": "error", "target_date": "2026-06-30"}),
        encoding="utf-8",
    )
    latest_path = tmp_path / "2026-07-01-personal-readiness.json"
    latest_path.write_text(
        json.dumps(
            {
                "status": "ok",
                "target_date": "2026-07-01",
                "summary": {
                    "system_status": "ok",
                    "qlib_status": "ok",
                    "workspace_status": "ok",
                    "target_count": 1,
                },
                "accounts": [
                    {
                        "status": "ok",
                        "account_id": 101,
                        "risk_center_daily_report": {"status": "ok"},
                        "auto_advisor": {"status": "ok"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = command_module.inspect_personal_readiness_evidence(output_dir=tmp_path)

    assert payload["path"] == str(latest_path)
    assert payload["evidence"]["target_date"] == "2026-07-01"


def test_inspect_personal_readiness_evidence_rejects_missing_file(tmp_path):
    with pytest.raises(CommandError, match="evidence file does not exist"):
        command_module.inspect_personal_readiness_evidence(
            output_dir=tmp_path,
            target_date=date(2026, 7, 1),
        )
