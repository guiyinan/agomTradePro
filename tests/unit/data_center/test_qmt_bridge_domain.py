"""Validate source observations even when callers bypass HTTP serialization."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from apps.data_center.domain.qmt_bridge import BridgeBatch, BridgeSample


@pytest.mark.parametrize("price", ["NaN", "Infinity", "0", "-1"])
def test_bridge_domain_rejects_invalid_prices(price):
    with pytest.raises(ValueError):
        BridgeSample("510300.SH", datetime.now(UTC), Decimal(price)).validate()


def test_bridge_domain_rejects_batch_mismatch_and_duplicate_observations():
    now = datetime.now(UTC)
    sample = BridgeSample("510300.SH", now-timedelta(seconds=1), Decimal("3.5"))
    for kind, samples in (("bar", (sample,)), ("quote", (sample, sample))):
        with pytest.raises(ValueError):
            BridgeBatch(str(uuid4()), kind, now, samples).validate(now)


def test_bridge_domain_rejects_inconsistent_ohlc_and_future_observation():
    now = datetime.now(UTC)
    with pytest.raises(ValueError):
        BridgeSample("510300.SH", now, Decimal("5"), high=Decimal("4"), low=Decimal("3")).validate()
    with pytest.raises(ValueError):
        BridgeBatch(str(uuid4()), "quote", now, (
            BridgeSample("510300.SH", now+timedelta(seconds=1), Decimal("3")),)).validate(now)
