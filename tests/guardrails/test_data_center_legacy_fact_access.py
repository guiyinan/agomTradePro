"""Guard the retired D1/D4/D5 equity fact models from new business access."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_legacy_fact_access_guard_passes() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "scripts/check_data_center_legacy_fact_access.py"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
