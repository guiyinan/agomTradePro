"""Tencent source replay tests for retained valuation response bodies."""

from __future__ import annotations

import hashlib
import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
PREFIX = "_tencent_response_replay_test"
SAMPLE = ("000001.SZ", "600000.SH")
FINISHED = datetime(2026, 9, 24, 7, 0, 1, tzinfo=UTC)
NORMALIZED = datetime(2026, 9, 24, 7, 0, 3, tzinfo=UTC)


@pytest.fixture(scope="module")
def modules() -> object:
    """Load production replay modules under an isolated package namespace."""
    package = ModuleType(PREFIX)
    package.__path__ = [str(ROOT / "apps/data_center/infrastructure")]
    sys.modules[PREFIX] = package
    try:
        yield {
            name: importlib.import_module(f"{PREFIX}.{name}")
            for name in ("rehearsal_response_store", "rehearsal_response_replay")
        }
    finally:
        for name in tuple(sys.modules):
            if name == PREFIX or name.startswith(PREFIX + "."):
                del sys.modules[name]


def _body() -> bytes:
    """Return two genuine-shape Tencent quote assignments with billion-yuan values."""
    lines: list[str] = []
    for symbol, numeric, total, circulating in (
        ("sz", "000001", "1234.5", "987.6"),
        ("sh", "600000", "2345.6", "2100.1"),
    ):
        fields = [""] * 47
        fields[0] = "1"
        fields[1] = "测试证券"
        fields[2] = numeric
        fields[30] = "20260924150000"
        fields[39] = "10.5"
        fields[44] = circulating
        fields[45] = total
        fields[46] = "1.2"
        lines.append(f'v_{symbol}{numeric}="{"~".join(fields)}";')
    return ("\n".join(lines) + "\n").encode()


def _replay(modules: object, body: bytes | None = None):
    replay = modules["rehearsal_response_replay"]
    store = modules["rehearsal_response_store"]
    retained = _body() if body is None else body
    context = store.RehearsalResponseContext(
        candidate_sha="c" * 40,
        target_trade_date="2026-09-24",
        universe_sha256="a" * 64,
        provider_identities_sha256="b" * 64,
        provider_id=7,
        provider_source="akshare",
        endpoint_id="primary",
        dataset="equity.valuation.fact",
        sample_codes=SAMPLE,
        provider_format="tencent_quote_batch.v1",
    )
    response = replay.ReplayResponse(
        context,
        retained,
        hashlib.sha256(retained).hexdigest(),
        FINISHED,
        NORMALIZED,
    )
    contracts = (
        replay.ReplayUnitContract("total_mv", "亿元", "元", 100_000_000.0),
        replay.ReplayUnitContract("circ_mv", "亿元", "元", 100_000_000.0),
    )
    return replay.replay_retained_dataset([response], contracts)


def test_tencent_replay_converts_billion_yuan_and_uses_transport_completion(
    modules: object,
) -> None:
    """Replay preserves the source clock, converts units, and binds the raw batch hash."""
    result = _replay(modules)

    first = result["observations"][0]
    assert first["asset_code"] == "000001.SZ"
    assert first["source_observed_at"] == "2026-09-24T07:00:00+00:00"
    assert first["transport_received_at"] == FINISHED.isoformat()
    assert first["response_completed_at"] == NORMALIZED.isoformat()
    assert first["body_sha256"] == hashlib.sha256(_body()).hexdigest()
    assert first["units"] == [
        {
            "field": "total_mv",
            "raw": 1234.5,
            "canonical": 123_450_000_000.0,
            "raw_unit": "亿元",
            "canonical_unit": "元",
            "multiplier": 100_000_000.0,
        },
        {
            "field": "circ_mv",
            "raw": 987.6,
            "canonical": 98_760_000_000.0,
            "raw_unit": "亿元",
            "canonical_unit": "元",
            "multiplier": 100_000_000.0,
        },
    ]
    assert result["units_verified"] is True
    assert result["source_time_verified"] is True


def test_tencent_replay_rejects_tushare_market_cap_units(modules: object) -> None:
    """A stale 万元 contract cannot validate Tencent's 亿元 source values."""
    replay = modules["rehearsal_response_replay"]
    store = modules["rehearsal_response_store"]
    body = _body()
    context = store.RehearsalResponseContext(
        candidate_sha="c" * 40,
        target_trade_date="2026-09-24",
        universe_sha256="a" * 64,
        provider_identities_sha256="b" * 64,
        provider_id=7,
        provider_source="akshare",
        endpoint_id="primary",
        dataset="equity.valuation.fact",
        sample_codes=SAMPLE,
        provider_format="tencent_quote_batch.v1",
    )
    response = replay.ReplayResponse(context, body, hashlib.sha256(body).hexdigest(), FINISHED)
    wrong_units = (
        replay.ReplayUnitContract("total_mv", "万元", "元", 10_000.0),
        replay.ReplayUnitContract("circ_mv", "万元", "元", 10_000.0),
    )

    with pytest.raises(ValueError, match="REHEARSAL_REPLAY_UNIT_CONTRACT_MISMATCH"):
        replay.replay_retained_dataset([response], wrong_units)


def test_tencent_replay_rejects_body_digest_replacement(modules: object) -> None:
    """A mutated body cannot be replayed under the digest of the original response."""
    replay = modules["rehearsal_response_replay"]
    store = modules["rehearsal_response_store"]
    body = _body()
    context = store.RehearsalResponseContext(
        candidate_sha="c" * 40,
        target_trade_date="2026-09-24",
        universe_sha256="a" * 64,
        provider_identities_sha256="b" * 64,
        provider_id=7,
        provider_source="akshare",
        endpoint_id="primary",
        dataset="equity.valuation.fact",
        sample_codes=SAMPLE,
        provider_format="tencent_quote_batch.v1",
    )
    response = replay.ReplayResponse(
        context, body + b" ", hashlib.sha256(body).hexdigest(), FINISHED
    )
    contracts = (
        replay.ReplayUnitContract("total_mv", "亿元", "元", 100_000_000.0),
        replay.ReplayUnitContract("circ_mv", "亿元", "元", 100_000_000.0),
    )

    with pytest.raises(ValueError, match="REHEARSAL_RESPONSE_DIGEST_MISMATCH"):
        replay.replay_retained_dataset([response], contracts)
