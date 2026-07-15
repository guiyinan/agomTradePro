"""Consumer-owned gateway for Backtest audit report generation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_generator: Callable[..., Any] | None = None


def register_audit_report_generator(generator: Callable[..., Any]) -> None:
    """Register the owning Audit report generator."""

    global _generator
    _generator = generator


def generate_attribution_report_for_backtest(**kwargs: Any) -> Any:
    """Generate an attribution report through the registered Audit provider."""

    if _generator is None:
        raise RuntimeError("Audit report generator is not registered")
    return _generator(**kwargs)


__all__ = ["generate_attribution_report_for_backtest", "register_audit_report_generator"]
