"""Production-facing governed-read projection contract for Macro Factor R3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.macro_factor.domain._runner_support import (
    hash_payload,
    require_aware,
    require_sha256,
    require_token,
    utc_text,
)
from apps.macro_factor.domain.dated_outputs import DatedMacroFactorOutput


@dataclass(frozen=True)
class R3GovernedReadProjection:
    """Exact production-facing read projection that remains research-only."""

    artifact_id: str
    artifact_hash: str
    output: DatedMacroFactorOutput
    regime_report_hash: str
    trial_id: str
    trial_hash: str
    decision_id: str
    decision_hash: str
    monitoring_assessment_hash: str
    read_as_of: datetime
    valid_until: datetime
    research_only: bool = True
    publishes_current: bool = False
    decision_authorized: bool = False
    execution_authorized: bool = False
    must_not_use_for_decision: bool = True
    must_not_execute: bool = True

    def __post_init__(self) -> None:
        for value, name in (
            (self.artifact_id, "artifact_id"),
            (self.artifact_hash, "artifact_hash"),
            (self.regime_report_hash, "regime_report_hash"),
            (self.trial_hash, "trial_hash"),
            (self.decision_hash, "decision_hash"),
            (self.monitoring_assessment_hash, "monitoring_assessment_hash"),
        ):
            require_sha256(value, f"R3GovernedReadProjection.{name}")
        require_token(self.trial_id, "R3GovernedReadProjection.trial_id")
        require_token(self.decision_id, "R3GovernedReadProjection.decision_id")
        require_aware(self.read_as_of, "R3GovernedReadProjection.read_as_of")
        require_aware(self.valid_until, "R3GovernedReadProjection.valid_until")
        if (
            self.output.artifact_id != self.artifact_id
            or self.output.artifact_hash != self.artifact_hash
        ):
            raise ValueError("R3 read output differs from the exact artifact")
        if self.read_as_of >= self.valid_until:
            raise ValueError("R3 governed read projection is not PIT-active")
        if not (
            self.research_only
            and not self.publishes_current
            and not self.decision_authorized
            and not self.execution_authorized
            and self.must_not_use_for_decision
            and self.must_not_execute
        ):
            raise ValueError("R3 governed read projection cannot authorize production behavior")

    @property
    def content_hash(self) -> str:
        """Return the exact read projection seal."""

        return hash_payload(
            {
                "schema": "macro-factor-r3-governed-read-projection.v1",
                "artifact": [self.artifact_id, self.artifact_hash],
                "output": [self.output.output_id, self.output.content_hash],
                "regime_report_hash": self.regime_report_hash,
                "trial": [self.trial_id, self.trial_hash],
                "decision": [self.decision_id, self.decision_hash],
                "monitoring_assessment_hash": self.monitoring_assessment_hash,
                "window": [utc_text(self.read_as_of), utc_text(self.valid_until)],
                "research_only": True,
                "publishes_current": False,
                "decision_authorized": False,
                "execution_authorized": False,
                "must_not_use_for_decision": True,
                "must_not_execute": True,
            }
        )


__all__ = ["R3GovernedReadProjection"]
