"""Domain states for reconciling imported broker facts with local projections."""

from enum import StrEnum, unique


@unique
class BrokerReconciliationState(StrEnum):
    """Describe whether a broker transaction is included in the local baseline."""

    NOT_APPLICABLE = "not_applicable"
    LEGACY_UNVERIFIED = "legacy_unverified"
    AWAITING_BASELINE = "awaiting_baseline"
    PROJECTION_PENDING = "projection_pending"
    PROJECTION_BLOCKED = "projection_blocked"
    PROJECTED = "projected"
    ALREADY_IN_BASELINE = "already_in_baseline"
    # Parser-only sentinel: it is intentionally excluded from database choices.
    UNKNOWN = "unknown"
