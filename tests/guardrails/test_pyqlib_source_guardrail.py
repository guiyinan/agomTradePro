from pathlib import Path

import pytest

from tests.support.pyqlib_guardrail import resolve_pyqlib_status


@pytest.mark.guardrail
def test_guardrail_imported_qlib_must_match_pyqlib_distribution():
    status = resolve_pyqlib_status(Path(__file__).resolve().parents[2])

    if not status.available and not status.misconfigured:
        pytest.skip("Microsoft pyqlib is not installed")

    assert status.available, status.reason
    assert status.module_file is not None
    assert status.version is not None
