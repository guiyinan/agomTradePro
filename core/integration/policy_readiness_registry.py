"""App-neutral registry for Policy cold-start readiness."""

from __future__ import annotations

from collections.abc import Callable

_checker: Callable[[], bool] | None = None


def register_policy_readiness_checker(checker: Callable[[], bool]) -> None:
    """Register the Policy-owned readiness checker."""

    global _checker
    _checker = checker


def policy_readiness_is_satisfied() -> bool:
    """Return whether required Policy sources are ready."""

    return bool(_checker and _checker())


__all__ = ["policy_readiness_is_satisfied", "register_policy_readiness_checker"]
