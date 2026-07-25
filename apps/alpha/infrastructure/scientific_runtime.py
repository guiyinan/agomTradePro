"""Runtime accessors for scientific libraries used by Alpha workflows."""

from __future__ import annotations

from typing import Any


def get_numpy() -> Any:
    """Return the numpy module."""

    import numpy as np

    return np


def get_pandas() -> Any:
    """Return the pandas module."""

    import pandas as pd  # type: ignore[import-untyped]

    return pd
