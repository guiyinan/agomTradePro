"""Cross-App transition-plan persistence contract-family rules."""

LEGACY_TRANSITION_PLAN_FAMILY = "decision_rhythm_legacy_v1"
CANONICAL_TRANSITION_PLAN_FAMILY = "portfolio_canonical_v1"


def require_legacy_transition_plan_family(family: str | None) -> None:
    """Allow unclassified historical rows or the explicit legacy family only."""

    if family not in (None, "", LEGACY_TRANSITION_PLAN_FAMILY):
        raise ValueError("legacy transition-plan path cannot consume canonical payload")


def require_canonical_transition_plan_family(family: str | None) -> None:
    """Require the explicit canonical family before decoding canonical payloads."""

    if family != CANONICAL_TRANSITION_PLAN_FAMILY:
        raise ValueError("canonical repository cannot consume a legacy transition plan")
