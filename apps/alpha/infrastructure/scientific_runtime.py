"""Runtime accessors for scientific libraries used by Alpha workflows."""

from __future__ import annotations


def get_numpy():
    """Return the numpy module."""

    import numpy as np

    return np


def get_pandas():
    """Return the pandas module."""

    import pandas as pd

    return pd
