"""Strict JSON codec for Portfolio R4 monitoring raw-fact receipts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from apps.portfolio.domain.r4_monitoring_raw_fact_receipt import (
    PortfolioR4MonitoringRawFactReceipt,
    PortfolioR4MonitoringRawMetric,
)


def encode_portfolio_r4_monitoring_raw_fact(
    value: PortfolioR4MonitoringRawFactReceipt,
) -> dict[str, object]:
    """Encode one exact receipt without weakening Decimal or clock values."""

    return {
        "schema": "portfolio-r4-monitoring-raw-fact-codec.v1",
        "observation_id": value.observation_id,
        "observation_version": value.observation_version,
        "period_id": value.period_id,
        "calendar_id": value.calendar_id,
        "calendar_version": value.calendar_version,
        "calendar_hash": value.calendar_hash,
        "period_start": value.period_start.isoformat(),
        "period_end": value.period_end.isoformat(),
        "active_decision_id": value.active_decision_id,
        "active_decision_version": value.active_decision_version,
        "active_decision_hash": value.active_decision_hash,
        "policy_id": value.policy_id,
        "policy_version": value.policy_version,
        "policy_hash": value.policy_hash,
        "portfolio_record_id": value.portfolio_record_id,
        "portfolio_record_hash": value.portfolio_record_hash,
        "portfolio_record_content_hash": value.portfolio_record_content_hash,
        "r3_attestation_content_hash": value.r3_attestation_content_hash,
        "observed_at": value.observed_at.isoformat(),
        "available_at": value.available_at.isoformat(),
        "owner_recorded_at": value.owner_recorded_at.isoformat(),
        "valid_until": value.valid_until.isoformat(),
        "pit_manifest_id": value.pit_manifest_id,
        "pit_manifest_hash": value.pit_manifest_hash,
        "evidence_ref": value.evidence_ref,
        "label_protocol_version": value.label_protocol_version,
        "observed_label_set_hash": value.observed_label_set_hash,
        "observed_data_schema_hash": value.observed_data_schema_hash,
        "metrics": [
            {
                "metric_key": item.metric_key,
                "unit": item.unit,
                "value": str(item.value),
            }
            for item in value.metrics
        ],
        "owner": value.owner,
        "research_only": value.research_only,
        "must_not_use_for_decision": value.must_not_use_for_decision,
        "must_not_publish_current": value.must_not_publish_current,
        "must_not_execute": value.must_not_execute,
        "content_hash": value.content_hash,
    }


def decode_portfolio_r4_monitoring_raw_fact(
    payload: object,
) -> PortfolioR4MonitoringRawFactReceipt:
    """Decode and live-revalidate one exact Portfolio owner receipt."""

    required = {
        "schema",
        "observation_id",
        "observation_version",
        "period_id",
        "calendar_id",
        "calendar_version",
        "calendar_hash",
        "period_start",
        "period_end",
        "active_decision_id",
        "active_decision_version",
        "active_decision_hash",
        "policy_id",
        "policy_version",
        "policy_hash",
        "portfolio_record_id",
        "portfolio_record_hash",
        "portfolio_record_content_hash",
        "r3_attestation_content_hash",
        "observed_at",
        "available_at",
        "owner_recorded_at",
        "valid_until",
        "pit_manifest_id",
        "pit_manifest_hash",
        "evidence_ref",
        "label_protocol_version",
        "observed_label_set_hash",
        "observed_data_schema_hash",
        "metrics",
        "owner",
        "research_only",
        "must_not_use_for_decision",
        "must_not_publish_current",
        "must_not_execute",
        "content_hash",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("Portfolio R4 raw-fact payload shape changed")
    if payload["schema"] != "portfolio-r4-monitoring-raw-fact-codec.v1":
        raise ValueError("Portfolio R4 raw-fact payload schema changed")
    metric_payloads = payload["metrics"]
    if not isinstance(metric_payloads, list):
        raise ValueError("Portfolio R4 raw-fact metrics are invalid")
    metrics: list[PortfolioR4MonitoringRawMetric] = []
    for item in metric_payloads:
        if not isinstance(item, dict) or set(item) != {"metric_key", "unit", "value"}:
            raise ValueError("Portfolio R4 raw metric payload changed")
        metrics.append(
            PortfolioR4MonitoringRawMetric(
                metric_key=str(item["metric_key"]),
                unit=str(item["unit"]),
                value=Decimal(str(item["value"])),
            )
        )
    value = PortfolioR4MonitoringRawFactReceipt(
        observation_id=str(payload["observation_id"]),
        observation_version=str(payload["observation_version"]),
        period_id=str(payload["period_id"]),
        calendar_id=str(payload["calendar_id"]),
        calendar_version=str(payload["calendar_version"]),
        calendar_hash=str(payload["calendar_hash"]),
        period_start=datetime.fromisoformat(str(payload["period_start"])),
        period_end=datetime.fromisoformat(str(payload["period_end"])),
        active_decision_id=str(payload["active_decision_id"]),
        active_decision_version=str(payload["active_decision_version"]),
        active_decision_hash=str(payload["active_decision_hash"]),
        policy_id=str(payload["policy_id"]),
        policy_version=str(payload["policy_version"]),
        policy_hash=str(payload["policy_hash"]),
        portfolio_record_id=str(payload["portfolio_record_id"]),
        portfolio_record_hash=str(payload["portfolio_record_hash"]),
        portfolio_record_content_hash=str(payload["portfolio_record_content_hash"]),
        r3_attestation_content_hash=str(payload["r3_attestation_content_hash"]),
        observed_at=datetime.fromisoformat(str(payload["observed_at"])),
        available_at=datetime.fromisoformat(str(payload["available_at"])),
        owner_recorded_at=datetime.fromisoformat(str(payload["owner_recorded_at"])),
        valid_until=datetime.fromisoformat(str(payload["valid_until"])),
        pit_manifest_id=str(payload["pit_manifest_id"]),
        pit_manifest_hash=str(payload["pit_manifest_hash"]),
        evidence_ref=str(payload["evidence_ref"]),
        label_protocol_version=str(payload["label_protocol_version"]),
        observed_label_set_hash=str(payload["observed_label_set_hash"]),
        observed_data_schema_hash=str(payload["observed_data_schema_hash"]),
        metrics=tuple(metrics),
        owner=str(payload["owner"]),
        research_only=payload["research_only"] is True,
        must_not_use_for_decision=payload["must_not_use_for_decision"] is True,
        must_not_publish_current=payload["must_not_publish_current"] is True,
        must_not_execute=payload["must_not_execute"] is True,
    )
    if value.content_hash.lower() != str(payload["content_hash"]).lower():
        raise ValueError("Portfolio R4 raw-fact content hash changed")
    return value


__all__ = [
    "decode_portfolio_r4_monitoring_raw_fact",
    "encode_portfolio_r4_monitoring_raw_fact",
]
