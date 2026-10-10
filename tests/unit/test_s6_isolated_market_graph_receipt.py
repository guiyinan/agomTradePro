"""Contracts for plan-bound, fail-closed S6 market graph receipts."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from scripts import s6_isolated_market_graph_receipt as receipt

_DATASETS = (
    "equity.price.bar",
    "equity.quote.snapshot",
    "equity.valuation.fact",
)
_ATTEMPT_ID = "a" * 32
_RUN_ID = str(UUID("11111111-1111-4111-8111-111111111111"))
_ACTIVATION_ID = str(uuid5(NAMESPACE_URL, f"agomtradepro:current-market-activation:{_RUN_ID}"))


def _context() -> dict[str, str]:
    """Return a validated disposable S6 runtime identity."""

    return {
        "candidate_sha": "b" * 40,
        "attempt_id": _ATTEMPT_ID,
        "attempt_plan_sha256": "c" * 64,
        "database": "agom_release_rehearsal_" + "d" * 32,
        "postgres_container": "agom-s6-postgres-" + "1" * 32,
        "redis_container": "agom-s6-redis-" + "2" * 32,
        "postgres_container_id": "e" * 64,
        "redis_container_id": "f" * 64,
        "network": "agom-s6-network-" + "1" * 32,
        "network_id": "2" * 64,
        "execution_image_id": "sha256:" + "3" * 64,
    }


def _payload() -> dict[str, object]:
    """Build a deterministic receipt payload for the reader boundary."""

    payload: dict[str, object] = {
        "schema": "release.s6-isolated-market-graph-refresh.v1",
        "outcome": "success",
        **_context(),
        "task_name": "data_center.refresh_full_market_publications",
        "task_id": f"s6-market-refresh-{_ATTEMPT_ID}",
        "task_attempt_id": "4" * 32,
        "task_result_sha256": "5" * 64,
        "task_result": {
            "outcome": "success",
            "requested": 3,
            "succeeded": 3,
            "failed": 0,
            "stored": 9,
            "publication_run_id": _RUN_ID,
        },
        "run_id": _RUN_ID,
        "activation_id": _ACTIVATION_ID,
        "target_trade_date": "2026-10-09",
        "source_time_min": "2026-10-09T08:00:00+00:00",
        "source_time_max": "2026-10-10T08:00:00+00:00",
        "pointers": [],
        "publications": [],
        "member_hashes": dict.fromkeys(_DATASETS, "6" * 64),
        "fact_hashes": dict.fromkeys(_DATASETS, "7" * 64),
    }
    payload["receipt_sha256"] = receipt._sha256(payload)
    return payload


def test_uuid_values_project_to_canonical_text() -> None:
    """Publication UUID primary keys remain representable in JSON evidence."""

    value = UUID("12345678-1234-5678-1234-567812345678")

    assert receipt._iso(value) == str(value)


def test_json_scope_blocks_project_recursively_and_reject_invalid_values() -> None:
    """JSON publication metadata remains stable and rejects non-JSON evidence."""

    assert receipt._iso({"blocks": [{"code": "missing", "count": 1}], "ratio": 0.5}) == {
        "blocks": [{"code": "missing", "count": 1}],
        "ratio": 0.5,
    }
    assert receipt._iso(("scope", {"enabled": True})) == ["scope", {"enabled": True}]

    for invalid in ({1: "invalid-key"}, {"not_finite": float("nan")}, object()):
        with pytest.raises(
            receipt.MarketGraphReceiptError, match="S6_GRAPH_REFRESH_EVIDENCE_INVALID"
        ):
            receipt._iso(invalid)


def test_publication_header_hashes_must_match_recomputed_graph() -> None:
    """A valid graph has one activation/run and matching member/publication seals."""

    pointers: list[dict[str, object]] = []
    publications: list[dict[str, object]] = []
    member_hashes = dict.fromkeys(_DATASETS, "8" * 64)
    publication_hashes = dict.fromkeys(_DATASETS, "9" * 64)
    for index, dataset in enumerate(_DATASETS, start=1):
        publication_id = str(UUID(int=index))
        publication = {
            "dataset_key": dataset,
            "publication_id": publication_id,
            "publication_key": "current",
            "publication_hash": publication_hashes[dataset],
            "member_manifest_hash": member_hashes[dataset],
            "member_count": 1,
            "coverage_requested_count": 3,
            "coverage_eligible_count": 1,
            "coverage_selected_count": 1,
            "coverage_missing_count": 2,
            "scope_blocks": [{"reason": "bounded_evidence_gap", "count": 2}],
            "members_sealed_at": datetime(2026, 10, 10, tzinfo=UTC),
            "published_at": datetime(2026, 10, 10, tzinfo=UTC),
            "run_id": _RUN_ID,
            "state": "published",
            "must_not_use_for_decision": False,
        }
        publications.append(publication)
        pointers.append(
            {
                "dataset_key": dataset,
                "publication_id": publication_id,
                "publication_hash": publication_hashes[dataset],
                "activation_id": _ACTIVATION_ID,
            }
        )

    receipt._validate_publication_hash_bindings(
        pointers=pointers,
        publications=publications,
        member_hashes=member_hashes,
        publication_hashes=publication_hashes,
        run_id=_RUN_ID,
    )

    mismatches = (
        ("member_manifest_hash", "0" * 64, _RUN_ID),
        ("publication_hash", "0" * 64, _RUN_ID),
        ("pointer_publication_hash", "0" * 64, _RUN_ID),
        ("run_id", "2" * 32, _RUN_ID),
    )
    for field, value, expected_run_id in mismatches:
        changed_pointers = [dict(item) for item in pointers]
        changed_publications = [dict(item) for item in publications]
        if field == "pointer_publication_hash":
            changed_pointers[0]["publication_hash"] = value
        else:
            changed_publications[0][field] = value
        with pytest.raises(receipt.MarketGraphReceiptError, match="S6_GRAPH_REFRESH_GRAPH_INVALID"):
            receipt._validate_publication_hash_bindings(
                pointers=changed_pointers,
                publications=changed_publications,
                member_hashes=member_hashes,
                publication_hashes=publication_hashes,
                run_id=expected_run_id,
            )


def test_task_target_date_helper_rejects_a_result_ahead_of_live_graph() -> None:
    """The helper cannot bless a provider result that disagrees with current pointers."""

    with pytest.raises(receipt.MarketGraphReceiptError, match="S6_GRAPH_REFRESH_GRAPH_INVALID"):
        receipt._validate_task_target_date({"target_trade_date": "2026-10-10"}, date(2026, 10, 9))


def test_read_rechecks_plan_bound_current_graph_and_source_time_bounds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Export-time verification compares the receipt with a fresh graph projection."""

    path = tmp_path / "current-market-graph-refresh.json"
    payload = _payload()
    receipt.write_success_receipt(path, payload)
    path.chmod(0o400)
    monkeypatch.setattr(
        receipt,
        "capture_current_market_graph",
        lambda *, context, task_id: payload,
    )

    assert receipt.read_and_validate_refresh_receipt(path, context=_context()) == payload

    changed = dict(payload)
    changed["source_time_min"] = "2026-10-09T08:30:00+00:00"
    monkeypatch.setattr(
        receipt,
        "capture_current_market_graph",
        lambda *, context, task_id: changed,
    )
    with pytest.raises(receipt.MarketGraphReceiptError, match="S6_GRAPH_REFRESH_RECEIPT_MISMATCH"):
        receipt.read_and_validate_refresh_receipt(path, context=_context())


def test_receipt_reader_rejects_wrong_attempt_and_writable_file(tmp_path: Path) -> None:
    """Receipt bytes must be immutable and exactly bound to the planned runtime."""

    path = tmp_path / "current-market-graph-refresh.json"
    receipt.write_success_receipt(path, _payload())
    with pytest.raises(receipt.MarketGraphReceiptError, match="S6_GRAPH_REFRESH_IDENTITY_INVALID"):
        receipt._context_fields({**_context(), "database": "production"})

    path.chmod(0o600)
    with pytest.raises(receipt.MarketGraphReceiptError, match="S6_GRAPH_REFRESH_RECEIPT_INVALID"):
        receipt.read_and_validate_refresh_receipt(path, context=_context())


def test_success_writer_rejects_failure_or_tampered_success_receipts(tmp_path: Path) -> None:
    """A failure-shaped or tampered payload never becomes a success receipt."""

    path = tmp_path / "current-market-graph-refresh.json"
    for mutation in ("outcome", "hash"):
        payload = _payload()
        if mutation == "outcome":
            payload["outcome"] = "failed"
        else:
            payload["receipt_sha256"] = "0" * 64
        with pytest.raises(
            receipt.MarketGraphReceiptError, match="S6_GRAPH_REFRESH_RECEIPT_INVALID"
        ):
            receipt.write_success_receipt(path, payload)
        assert not path.exists()
