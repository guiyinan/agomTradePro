#!/usr/bin/env python
"""Fail-closed tombstone for the retired synthetic backtest validator."""

from __future__ import annotations

from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> None:
    """Reject the synthetic validator and identify the governed replacement."""

    del argv
    raise SystemExit(
        "scripts/validate_backtest.py was retired because it depended on synthetic "
        "prices and fallback regimes. Use `python manage.py run_backtest --help` "
        "and the persisted Backtest Application result/audit instead."
    )


if __name__ == "__main__":
    main()
