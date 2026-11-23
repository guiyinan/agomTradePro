"""Frozen settings shared by the CAL-03 validation commands."""

import hashlib
import json
from datetime import time
from pathlib import Path

from apps.research.application.calendar_validation import ValidationDesign
from apps.research.domain.institutional_event_study import (
    SampleGateSpec,
    StudyClock,
    WalkForwardPolicy,
)

SPEC_SHA256 = "29a44d0cd2670dd2a72853494d21271c9765d6584dafa4998e1df3c2a6edfe71"


def load_validation_design(spec_path: Path) -> ValidationDesign:
    """Load the byte-verified CAL-03 design shared by the offline validation runners."""
    raw = spec_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SPEC_SHA256:
        raise ValueError("Unexpected frozen CAL-03 specification")
    doc = json.loads(raw)
    split = doc["temporal_split"]
    gates = doc["sample_gates"]
    controls = doc["controls"]["six_periods"]
    clock = doc["knowledge_cutoff"]
    policy = WalkForwardPolicy(
        split["minimum_history"]["consecutive_calendar_years"],
        split["minimum_history"]["complete_daily_rows_per_target"],
        split["first_training_window_years"],
        split["validation_trading_days_per_fold"],
        split["minimum_walk_forward_folds"],
        split["total_oos_trading_days"],
        split["purge"]["minimum_separation_trading_days"],
        split["embargo"]["trading_days"],
        gates["target_expected_session_coverage_min"],
    )
    return ValidationDesign(
        tuple(t["code"] for t in doc["targets"]["broad_indices"]),
        StudyClock(
            clock["timezone"],
            time.fromisoformat(clock["local_time"]),
            tuple(doc["primary_endpoint"]["horizons_trading_days"]),
        ),
        policy,
        SampleGateSpec(
            policy.minimum_coverage,
            gates["distinct_events_total_min"],
            gates["training_events_min"],
            gates["validation_events_total_min"],
            gates["oos_events_total_min"],
        ),
        tuple(controls["categories"]),
        controls["reference_category"],
        ("quiet", "active"),
        "system_known",
        1.0,
        10,
        0.95,
    )
