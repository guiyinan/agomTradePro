"""Decision Rhythm domain exceptions."""


class LegacyTransitionPlanWriteDisabledError(ValueError):
    """Raised when a legacy plan writer is used after canonical cutover."""
