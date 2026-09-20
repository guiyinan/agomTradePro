"""Shared data cannot be read while another build/prediction owns its directory."""

import pytest

from apps.alpha.infrastructure.qlib_runtime_lock import qlib_runtime_lock
from core.exceptions import DataFetchError


def test_runtime_lock_rejects_overlap_and_releases_on_error(tmp_path):
    with pytest.raises(ValueError):
        with qlib_runtime_lock(tmp_path):
            with pytest.raises(DataFetchError) as caught:
                with qlib_runtime_lock(tmp_path):
                    pytest.fail("overlapping Qlib operation")
            assert caught.value.code == "MODEL_MARKET_REFRESH_BUSY"
            raise ValueError("build failed")
    with qlib_runtime_lock(tmp_path):
        pass
