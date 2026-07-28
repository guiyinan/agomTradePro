"""Typed operational diagnostics contracts for investment signals."""

from datetime import datetime
from typing import TypedDict


class RecentSignalDiagnostic(TypedDict):
    """One recent signal row published to operational diagnostics."""

    asset_code: str
    direction: str
    status: str
    created_at: datetime


class SignalDiagnosticSummary(TypedDict):
    """Truthful status and evidence summary for investment signals."""

    total_count: int
    active_count: int
    invalidated_count: int
    closed_count: int
    recent_signals: list[RecentSignalDiagnostic]
    regime_match_available: bool
    regime_matched_count: int
