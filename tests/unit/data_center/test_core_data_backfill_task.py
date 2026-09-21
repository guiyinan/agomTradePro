"""Active A-share core-data backfill task outcome contracts."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.data_center.application.backfill_control_plane import backfill_control_plane_ids
from apps.data_center.application.batch_identity import ProviderAssetIdentityError
from apps.data_center.application.tasks import (
    _publication_evidence_hash_from_result,
    backfill_active_a_share_core_data_batch_task,
)
from apps.data_center.domain.control_plane import (
    SyncItemAttempt,
    SyncItemAttemptPhase,
    SyncItemAttemptState,
)

AUTHORITY_HASH = "a" * 64
PUBLICATION_DATASETS = (
    "equity.quote.snapshot",
    "equity.price.bar",
    "equity.valuation.fact",
    "equity.financial.fact",
)


def _universe_hash(*asset_codes: str) -> str:
    payload = json.dumps(
        {
            "schema": "active-a-share-universe.v1",
            "asset_codes": sorted(asset_codes),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _publication_result(
    member_count: int,
    *,
    financial_member_count: int | None = None,
) -> SimpleNamespace:
    """Return exact four-Publication evidence for task tests."""

    member_counts = {
        dataset_key: (
            financial_member_count
            if dataset_key == "equity.financial.fact" and financial_member_count is not None
            else member_count
        )
        for dataset_key in PUBLICATION_DATASETS
    }
    datasets = [
        {
            "dataset_key": dataset_key,
            "publication_id": f"publication-{index}",
            "publication_hash": format(index + 1, "x") * 64,
            "member_count": member_counts[dataset_key],
            "covered_asset_count": member_count,
            "policy_identity": f"p2:{index + 1}:{format(index + 5, 'x') * 64}",
        }
        for index, dataset_key in enumerate(PUBLICATION_DATASETS)
    ]
    published_count = sum(member_counts.values())
    return SimpleNamespace(
        published_count=published_count,
        datasets=datasets,
        to_dict=lambda: {
            "published_count": published_count,
            "datasets": datasets,
        },
    )


def test_four_publication_evidence_allows_financial_member_count_to_differ() -> None:
    result = _publication_result(2, financial_member_count=5)

    digest = _publication_evidence_hash_from_result(result, expected_asset_count=2)

    assert len(digest) == 64
    assert result.published_count == 11


def test_four_publication_evidence_rejects_asset_coverage_drift() -> None:
    result = _publication_result(2, financial_member_count=5)
    result.datasets[-1]["covered_asset_count"] = 1

    with pytest.raises(ValueError, match="covered-asset-count"):
        _publication_evidence_hash_from_result(result, expected_asset_count=2)


@pytest.mark.parametrize("field_name", ["publication_id", "publication_hash"])
def test_four_publication_evidence_rejects_reused_identity(field_name: str) -> None:
    result = _publication_result(2, financial_member_count=5)
    result.datasets[-1][field_name] = result.datasets[0][field_name]

    with pytest.raises(ValueError, match=f"{field_name} evidence must be unique"):
        _publication_evidence_hash_from_result(result, expected_asset_count=2)


@pytest.fixture(autouse=True)
def _patch_current_authority(mocker):
    """Bind every successful task test to one server-issued authority."""

    return mocker.patch(
        "apps.data_center.application.tasks.preflight_data_reliability_audit_runtime",
        return_value=SimpleNamespace(
            actor_id="service:data02",
            tenant_id="tenant:production",
            owner_id="owner:production",
            authority_content_hash=AUTHORITY_HASH,
            authority_valid_until=datetime.now(UTC) + timedelta(hours=2),
        ),
    )


@pytest.fixture(autouse=True)
def _patch_control_plane_repositories(mocker):
    """Keep unit tests in-memory while exercising the durable save calls."""

    repositories = {name: mocker.Mock() for name in ("run", "batch", "checkpoint", "item_attempt")}
    snapshot = mocker.patch(
        "apps.data_center.application.tasks.persist_sync_control_plane_snapshot"
    )
    snapshot.side_effect = lambda run, batch, checkpoint: (
        repositories["run"].save(run),
        repositories["batch"].save(batch),
        repositories["checkpoint"].save(checkpoint),
    )

    def begin_item_attempt(**kwargs):
        run_id, batch_id = backfill_control_plane_ids(kwargs["idempotency_key"])
        return SyncItemAttempt(
            attempt_id=str(uuid4()),
            run_id=run_id,
            batch_id=batch_id,
            dataset_key="equity.core.backfill",
            asset_code=kwargs["asset_code"],
            phase=kwargs["phase"],
            attempt_number=1,
            state=SyncItemAttemptState.RUNNING,
            execution_token=kwargs["execution_token"],
            started_at=kwargs["started_at"],
            universe_hash=kwargs["universe_hash"],
            authority_content_hash=kwargs["authority_content_hash"],
        )

    repositories["item_attempt"].begin.side_effect = begin_item_attempt
    repositories["item_attempt"].finish.side_effect = lambda attempt, **kwargs: attempt
    repositories["item_attempt"].begin_many.side_effect = lambda *, asset_codes, **kwargs: [
        repositories["item_attempt"].begin(asset_code=asset_code, **kwargs)
        for asset_code in asset_codes
    ]
    repositories["item_attempt"].finish_many.side_effect = lambda attempts: [
        repositories["item_attempt"].finish(
            attempt,
            state=attempt.state,
            finished_at=attempt.finished_at,
            stored_count=attempt.stored_count,
            error_code=attempt.error_code,
            error_message=attempt.error_message,
            evidence_hash=attempt.evidence_hash,
        )
        for attempt in attempts
    ]
    mocker.patch(
        "apps.data_center.application.tasks.get_backfill_item_attempt_store",
        return_value=repositories["item_attempt"],
    )
    return repositories


def _patch_backfill_dependencies(
    mocker,
    *,
    stored_count=1,
    stored_count_by_asset=None,
    failure=None,
    publication_failure: bool = False,
    quote_asset_codes=None,
    valuation_succeeded_codes=None,
    valuation_returned_codes=None,
):
    mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill",
        return_value=["000001.SZ", "002156.SZ"],
    )
    mocker.patch(
        "apps.data_center.application.tasks.get_active_provider_id_by_source",
        return_value=7,
    )
    mocker.patch(
        "apps.data_center.application.tasks.latest_completed_cn_market_session",
        return_value=date(2026, 7, 31),
    )

    def _use_case(domain):
        use_case = mocker.Mock()

        def _execute(request):
            asset_code = getattr(request, "asset_code", "batch")
            if failure == (domain, asset_code):
                raise RuntimeError("provider failure")
            count = (
                len(request.asset_codes)
                if domain == "quote"
                else (stored_count_by_asset or {}).get((domain, asset_code), stored_count)
            )
            if domain == "quote":
                return SimpleNamespace(
                    stored_count=count,
                    stored_asset_codes=(
                        tuple(request.asset_codes)
                        if quote_asset_codes is None
                        else tuple(quote_asset_codes)
                    ),
                )
            return SimpleNamespace(stored_count=count)

        use_case.execute.side_effect = _execute
        if domain == "valuation":

            def _execute_current_batch(
                *,
                provider_id,
                asset_codes,
                as_of_date,
                require_exact_asset_codes=False,
            ):
                del provider_id, as_of_date
                assert require_exact_asset_codes is True
                succeeded = [code for code in asset_codes if failure != ("valuation", code)]
                count = len(succeeded) if stored_count else 0
                return SimpleNamespace(
                    stored_count=count,
                    succeeded_asset_codes=(
                        (
                            succeeded
                            if valuation_succeeded_codes is None
                            else tuple(valuation_succeeded_codes)
                        )
                        if stored_count
                        else []
                    ),
                    returned_asset_codes=(
                        tuple(succeeded)
                        if valuation_returned_codes is None
                        else tuple(valuation_returned_codes)
                    ),
                )

            use_case.execute.side_effect = _execute_current_batch
        return use_case

    mocker.patch(
        "apps.data_center.application.tasks.make_backfill_sync_quote_use_case",
        return_value=_use_case("quote"),
    )
    mocker.patch(
        "apps.data_center.application.tasks.make_backfill_sync_price_use_case",
        return_value=_use_case("price"),
    )
    mocker.patch(
        "apps.data_center.application.tasks." "make_backfill_sync_current_valuation_batch_use_case",
        return_value=_use_case("valuation"),
    )
    mocker.patch(
        "apps.data_center.application.tasks.make_backfill_sync_financial_use_case",
        return_value=_use_case("financial"),
    )
    coordinator = mocker.Mock()
    if publication_failure:
        coordinator.execute.side_effect = ValueError("full universe incomplete")
    else:
        coordinator.execute.return_value = _publication_result(2)
    factory = mocker.patch(
        "apps.data_center.application.tasks." "make_core_current_publication_rebuild_use_case",
        return_value=coordinator,
    )
    return factory, coordinator


def test_backfill_batch_rejects_invalid_input_before_repository_access(
    mocker,
    _patch_control_plane_repositories,
) -> None:
    universe = mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill"
    )

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=0)

    assert result["outcome"] == "failed"
    assert result["stage"] == "input"
    universe.assert_not_called()
    for repository in _patch_control_plane_repositories.values():
        repository.save.assert_not_called()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"source": ["tushare"]},
        {"operator": ["service:data02"]},
    ],
)
def test_backfill_batch_rejects_non_string_identities_before_repository_access(
    mocker,
    _patch_control_plane_repositories,
    kwargs,
) -> None:
    """Celery JSON values cannot be stringified into trusted identities."""

    universe = mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill"
    )

    result = backfill_active_a_share_core_data_batch_task.run(**kwargs)

    assert result["outcome"] == "failed"
    assert result["stage"] == "input"
    universe.assert_not_called()
    for repository in _patch_control_plane_repositories.values():
        repository.save.assert_not_called()


def test_backfill_batch_blocks_before_repository_access_without_current_authority(
    mocker,
    _patch_current_authority,
) -> None:
    """A missing canonical authority must stop before universe/provider reads."""

    from apps.audit.application.system_audit_composition import SystemAuditCompositionUnavailable

    _patch_current_authority.side_effect = SystemAuditCompositionUnavailable(
        "unavailable",
        reason_code="authority_unavailable",
    )
    universe = mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill"
    )

    result = backfill_active_a_share_core_data_batch_task.run()

    assert result == {
        "success": False,
        "outcome": "blocked",
        "stage": "authority",
        "blocked_reason": "system_audit_authority_unavailable",
        "must_not_use_for_decision": True,
        "requested": 0,
        "succeeded": 0,
        "failed": 0,
        "stored": 0,
        "published": 0,
        "checkpoint": {
            "offset": 0,
            "next_offset": 0,
            "total_assets": 0,
            "complete": False,
        },
    }
    universe.assert_not_called()


def test_backfill_batch_blocks_mismatched_operator_before_repository_access(
    mocker,
) -> None:
    """A caller label cannot replace the server-issued actor identity."""

    universe = mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill"
    )

    result = backfill_active_a_share_core_data_batch_task.run(operator="different:actor")

    assert result["outcome"] == "blocked"
    assert result["stage"] == "authority"
    assert result["blocked_reason"] == "operator_actor_mismatch"
    universe.assert_not_called()


def test_backfill_batch_blocks_authority_window_shorter_than_task_budget(
    mocker,
    _patch_current_authority,
) -> None:
    """The authority must cover the full hard task limit plus its safety margin."""

    _patch_current_authority.return_value.authority_valid_until = datetime.now(UTC) + timedelta(
        minutes=30
    )
    universe = mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill"
    )

    result = backfill_active_a_share_core_data_batch_task.run()

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "authority_window_too_short"
    universe.assert_not_called()


def test_backfill_batch_blocks_oversized_authority_checkpoint_before_repository_access(
    mocker,
    _patch_current_authority,
) -> None:
    """A valid authority cannot start writes if its durable cursor would overflow."""

    _patch_current_authority.return_value.actor_id = "actor:" + ("a" * 190)
    _patch_current_authority.return_value.tenant_id = "tenant:" + ("b" * 190)
    _patch_current_authority.return_value.owner_id = "owner:" + ("c" * 190)
    universe = mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill"
    )

    result = backfill_active_a_share_core_data_batch_task.run()

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "authority_checkpoint_too_large"
    universe.assert_not_called()


def test_backfill_batch_reports_all_success_with_checkpoint(mocker) -> None:
    factory, coordinator = _patch_backfill_dependencies(mocker)

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "success"
    assert result["requested"] == 2
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert result["stored"] == 8
    assert result["published"] == 8
    assert result["checkpoint"] == {
        "offset": 0,
        "next_offset": 2,
        "total_assets": 2,
        "complete": True,
        "universe_hash": mocker.ANY,
        "authority": {
            "actor_id": "service:data02",
            "tenant_id": "tenant:production",
            "owner_id": "owner:production",
            "content_hash": AUTHORITY_HASH,
            "valid_until": mocker.ANY,
        },
    }
    factory.assert_called_once_with(created_by="celery.core_data_backfill:service:data02")
    coordinator.execute.assert_called_once()


def test_backfill_batch_records_all_item_phase_attempts(
    mocker,
    _patch_control_plane_repositories,
) -> None:
    """Every write phase must have complete durable per-asset evidence."""

    _patch_backfill_dependencies(mocker)
    item_attempts = _patch_control_plane_repositories["item_attempt"]

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "success"
    assert [
        len(call.kwargs["asset_codes"]) for call in item_attempts.begin_many.call_args_list
    ] == [2, 2, 2, 2, 2]
    phases = [call.kwargs["phase"] for call in item_attempts.begin.call_args_list]
    assert phases == [
        SyncItemAttemptPhase.QUOTE,
        SyncItemAttemptPhase.QUOTE,
        SyncItemAttemptPhase.VALUATION,
        SyncItemAttemptPhase.VALUATION,
        SyncItemAttemptPhase.PRICE,
        SyncItemAttemptPhase.PRICE,
        SyncItemAttemptPhase.FINANCIAL,
        SyncItemAttemptPhase.FINANCIAL,
        SyncItemAttemptPhase.PUBLICATION,
        SyncItemAttemptPhase.PUBLICATION,
    ]
    assert all(
        call.kwargs["state"] is SyncItemAttemptState.SUCCEEDED
        for call in item_attempts.finish.call_args_list
    )
    assert len(item_attempts.finish.call_args_list) == 10
    publication_finishes = [
        call
        for call in item_attempts.finish.call_args_list
        if call.args[0].phase is SyncItemAttemptPhase.PUBLICATION
    ]
    assert {call.kwargs["stored_count"] for call in publication_finishes} == {1}
    assert all(len(call.kwargs["evidence_hash"]) == 64 for call in publication_finishes)


def test_backfill_batch_blocks_checkpoint_when_item_evidence_finish_fails(
    mocker,
    _patch_control_plane_repositories,
) -> None:
    """A provider write cannot advance the cursor without terminal item evidence."""

    _patch_backfill_dependencies(mocker)
    item_attempts = _patch_control_plane_repositories["item_attempt"]
    original_finish = item_attempts.finish.side_effect
    calls = 0

    def finish_with_first_failure(attempt, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("evidence unavailable")
        return original_finish(attempt, **kwargs)

    item_attempts.finish.side_effect = finish_with_first_failure

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "blocked"
    assert result["stage"] == "item_evidence"
    assert result["blocked_reason"] == "item_attempt_evidence_failed"
    assert result["checkpoint"]["next_offset"] == 0
    assert result["checkpoint"]["complete"] is False


def test_backfill_batch_rejects_duplicate_attempt_identity_before_provider_write(
    mocker,
    _patch_control_plane_repositories,
) -> None:
    """Malformed batch evidence blocks before the corresponding provider call."""

    _patch_backfill_dependencies(mocker)
    item_attempts = _patch_control_plane_repositories["item_attempt"]
    original_begin_many = item_attempts.begin_many.side_effect

    def begin_many_with_duplicate_identity(**kwargs):
        attempts = original_begin_many(**kwargs)
        attempts[1] = replace(attempts[1], attempt_id=attempts[0].attempt_id)
        return attempts

    item_attempts.begin_many.side_effect = begin_many_with_duplicate_identity

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "blocked"
    assert result["stage"] == "item_evidence"
    assert result["checkpoint"]["next_offset"] == 0


def test_backfill_batch_blocks_checkpoint_when_mixed_group_finish_fails(
    mocker,
    _patch_control_plane_repositories,
) -> None:
    """A failed item group must persist before a mixed provider batch can advance."""

    _patch_backfill_dependencies(mocker, failure=("price", "002156.SZ"))
    item_attempts = _patch_control_plane_repositories["item_attempt"]
    original_finish_many = item_attempts.finish_many.side_effect

    def finish_many_with_failed_price_rejection(attempts):
        if any(
            attempt.phase is SyncItemAttemptPhase.PRICE
            and attempt.state is SyncItemAttemptState.FAILED
            for attempt in attempts
        ):
            raise RuntimeError("failed item evidence unavailable")
        return original_finish_many(attempts)

    item_attempts.finish_many.side_effect = finish_many_with_failed_price_rejection

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "blocked"
    assert result["stage"] == "item_evidence"
    assert result["blocked_reason"] == "item_attempt_evidence_failed"
    assert result["checkpoint"]["next_offset"] == 0
    assert result["checkpoint"]["complete"] is False


def test_backfill_batch_persists_heterogeneous_terminal_counts_once_per_phase(
    mocker,
    _patch_control_plane_repositories,
) -> None:
    """Different per-asset row counts remain one atomic terminal phase write."""

    _patch_backfill_dependencies(
        mocker,
        stored_count_by_asset={
            ("price", "000001.SZ"): 3,
            ("price", "002156.SZ"): 7,
        },
    )
    item_attempts = _patch_control_plane_repositories["item_attempt"]

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "success"
    price_batches = [
        call.args[0]
        for call in item_attempts.finish_many.call_args_list
        if call.args[0][0].phase is SyncItemAttemptPhase.PRICE
    ]
    assert len(price_batches) == 1
    assert [attempt.stored_count for attempt in price_batches[0]] == [3, 7]


def test_backfill_resume_requires_frozen_universe_hash_before_repository_access(
    mocker,
) -> None:
    """A nonzero cursor cannot be interpreted against an unbound live universe."""

    universe = mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill"
    )

    result = backfill_active_a_share_core_data_batch_task.run(offset=1)

    assert result["outcome"] == "failed"
    assert result["stage"] == "input"
    assert "universe_hash" in result["error"]
    universe.assert_not_called()


def test_backfill_resume_requires_same_frozen_universe_before_provider_access(mocker) -> None:
    """A changed universe blocks the saved offset before any provider access."""

    _patch_backfill_dependencies(mocker)
    provider = mocker.patch("apps.data_center.application.tasks.get_active_provider_id_by_source")

    result = backfill_active_a_share_core_data_batch_task.run(
        offset=1,
        universe_hash="f" * 64,
    )

    assert result["outcome"] == "blocked"
    assert result["stage"] == "universe"
    assert result["blocked_reason"] == "universe_hash_mismatch"
    assert result["checkpoint"]["next_offset"] == 1
    assert result["checkpoint"]["complete"] is False
    assert result["checkpoint"]["universe_hash"] == "f" * 64
    assert result["checkpoint"]["observed_universe_hash"] != "f" * 64
    provider.assert_not_called()


def test_backfill_resume_accepts_exact_frozen_universe_hash(mocker) -> None:
    """The initial checkpoint hash is sufficient to resume the next exact slice."""

    _patch_backfill_dependencies(mocker)

    first = backfill_active_a_share_core_data_batch_task.run(batch_size=1)
    second = backfill_active_a_share_core_data_batch_task.run(
        offset=1,
        batch_size=1,
        universe_hash=first["checkpoint"]["universe_hash"],
    )

    assert first["checkpoint"]["complete"] is False
    assert second["outcome"] == "success"
    assert second["checkpoint"]["complete"] is True
    assert second["checkpoint"]["universe_hash"] == first["checkpoint"]["universe_hash"]


@pytest.mark.parametrize(
    "asset_codes",
    [
        ["", "002156.SZ"],
        ["000001.SZ", "000001.SZ"],
        [123, "002156.SZ"],
    ],
)
def test_backfill_blocks_invalid_active_universe_before_provider_access(
    mocker,
    asset_codes,
) -> None:
    """Blank or duplicate identities cannot define an offset-bearing universe."""

    mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill",
        return_value=asset_codes,
    )
    provider = mocker.patch("apps.data_center.application.tasks.get_active_provider_id_by_source")

    result = backfill_active_a_share_core_data_batch_task.run()

    assert result["outcome"] == "blocked"
    assert result["stage"] == "universe"
    assert result["blocked_reason"] == "invalid_active_universe"
    provider.assert_not_called()


def test_backfill_universe_hash_and_idempotency_ignore_query_order(
    mocker,
    _patch_control_plane_repositories,
) -> None:
    """Equivalent universes converge on one canonical hash and durable batch."""

    _patch_backfill_dependencies(mocker)
    mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill",
        side_effect=[
            ["002156.SZ", "000001.SZ"],
            ["000001.SZ", "002156.SZ"],
        ],
    )

    first = backfill_active_a_share_core_data_batch_task.run(batch_size=2)
    second = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert first["checkpoint"]["universe_hash"] == second["checkpoint"]["universe_hash"]
    batch_saves = _patch_control_plane_repositories["batch"].save.call_args_list
    assert batch_saves[-2].args[0].idempotency_key == batch_saves[-1].args[0].idempotency_key


def test_backfill_batch_persists_stable_run_batch_and_cursor_on_retry(
    mocker,
    _patch_control_plane_repositories,
) -> None:
    _patch_backfill_dependencies(mocker)

    first = backfill_active_a_share_core_data_batch_task.run(batch_size=2)
    second = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    run_saves = _patch_control_plane_repositories["run"].save.call_args_list
    batch_saves = _patch_control_plane_repositories["batch"].save.call_args_list
    checkpoint_saves = _patch_control_plane_repositories["checkpoint"].save.call_args_list
    assert len(run_saves) == len(batch_saves) == len(checkpoint_saves) == 2
    assert run_saves[0].args[0].run_id == run_saves[1].args[0].run_id
    assert batch_saves[0].args[0].batch_id == batch_saves[1].args[0].batch_id
    assert (
        batch_saves[0].args[0].idempotency_key
        == "equity.core.backfill:tushare:offset=0:window=2:"
        + batch_saves[0].args[0].idempotency_key.rsplit(":", 1)[-1]
    )
    assert batch_saves[0].args[0].requested == 2
    assert batch_saves[0].args[0].succeeded == 2
    assert batch_saves[0].args[0].stored == 8
    assert batch_saves[0].args[0].published == 8
    assert json.loads(checkpoint_saves[0].args[0].cursor_value) == first["checkpoint"]
    assert json.loads(checkpoint_saves[1].args[0].cursor_value) == second["checkpoint"]


def test_backfill_batch_idempotency_uses_canonical_validated_source(
    mocker,
    _patch_control_plane_repositories,
) -> None:
    """Equivalent accepted source spellings must converge on one durable batch."""

    _patch_backfill_dependencies(mocker)

    backfill_active_a_share_core_data_batch_task.run(batch_size=2, source=" TUSHARE ")
    backfill_active_a_share_core_data_batch_task.run(batch_size=2, source="tushare")

    batch_saves = _patch_control_plane_repositories["batch"].save.call_args_list
    assert batch_saves[0].args[0].idempotency_key == batch_saves[1].args[0].idempotency_key


def test_backfill_batch_reports_partial_failure(mocker) -> None:
    _factory, coordinator = _patch_backfill_dependencies(
        mocker,
        failure=("financial", "002156.SZ"),
    )

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "partial"
    assert result["success"] is True
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["domains"]["financial"]["failed"] == 1
    assert result["checkpoint"]["next_offset"] == 0
    assert result["checkpoint"]["complete"] is False
    coordinator.execute.assert_not_called()


def test_backfill_identity_mismatch_records_stable_failed_attempt_and_open_checkpoint(
    mocker,
    _patch_control_plane_repositories,
) -> None:
    _patch_backfill_dependencies(mocker)
    quote_sync = mocker.Mock()
    quote_sync.execute.side_effect = ProviderAssetIdentityError(
        "quote provider asset identities mismatch"
    )
    mocker.patch(
        "apps.data_center.application.tasks.make_backfill_sync_quote_use_case",
        return_value=quote_sync,
    )

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "partial"
    assert result["checkpoint"]["next_offset"] == 0
    assert result["checkpoint"]["complete"] is False
    assert result["errors"][0]["error"] == "provider_asset_identity_mismatch"
    assert any(
        call.kwargs.get("error_code") == "provider_asset_identity_mismatch"
        for call in _patch_control_plane_repositories["item_attempt"].finish.call_args_list
    )


@pytest.mark.parametrize(
    ("override", "failed_domain"),
    [
        ({"quote_asset_codes": ["000001.SZ", "000001.SZ"]}, "quote"),
        ({"valuation_succeeded_codes": ["000001.SZ", "000001.SZ"]}, "valuation"),
        ({"valuation_succeeded_codes": ["000001.SZ", "600000.SH"]}, "valuation"),
        ({"valuation_returned_codes": ["000001.SZ", "000001.SZ"]}, "valuation"),
    ],
)
def test_backfill_batch_rejects_duplicate_provider_asset_identities(
    mocker,
    override,
    failed_domain,
) -> None:
    """Count equality cannot hide a duplicate or substituted asset."""

    _factory, coordinator = _patch_backfill_dependencies(mocker, **override)

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "partial"
    assert result["domains"][failed_domain]["failed"] == 2
    coordinator.execute.assert_not_called()


def test_backfill_batch_keeps_checkpoint_open_when_authority_changes(
    mocker,
    _patch_current_authority,
) -> None:
    """A batch cannot advance its cursor under a different authority head."""

    _patch_backfill_dependencies(mocker)
    quote_factory = mocker.patch(
        "apps.data_center.application.tasks.make_backfill_sync_quote_use_case"
    )
    initial = _patch_current_authority.return_value
    changed = SimpleNamespace(
        actor_id=initial.actor_id,
        tenant_id=initial.tenant_id,
        owner_id=initial.owner_id,
        authority_content_hash="c" * 64,
        authority_valid_until=initial.authority_valid_until,
    )
    _patch_current_authority.side_effect = [initial, changed]

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "blocked"
    assert result["stage"] == "authority"
    assert result["checkpoint"]["complete"] is False
    assert result["checkpoint"]["next_offset"] == 0
    assert result["errors"][-1]["error"] == "authority_changed_or_expired"
    quote_factory.return_value.execute.assert_not_called()


def test_backfill_revalidates_authority_after_publication_attempt_setup(
    mocker,
    _patch_current_authority,
    _patch_control_plane_repositories,
) -> None:
    """Publication cannot start if authority drifts while item evidence is prepared."""

    _factory, coordinator = _patch_backfill_dependencies(mocker)
    mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill",
        return_value=["000001.SZ"],
    )
    initial = _patch_current_authority.return_value
    changed = SimpleNamespace(
        actor_id=initial.actor_id,
        tenant_id=initial.tenant_id,
        owner_id=initial.owner_id,
        authority_content_hash="c" * 64,
        authority_valid_until=initial.authority_valid_until,
    )
    _patch_current_authority.side_effect = [initial] * 6 + [changed]

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=1)

    assert result["outcome"] == "blocked"
    assert result["stage"] == "authority"
    assert result["checkpoint"]["next_offset"] == 0
    assert result["checkpoint"]["complete"] is False
    coordinator.execute.assert_not_called()
    publication_finishes = [
        call
        for call in _patch_control_plane_repositories["item_attempt"].finish.call_args_list
        if call.args[0].phase is SyncItemAttemptPhase.PUBLICATION
    ]
    assert len(publication_finishes) == 1
    assert publication_finishes[0].kwargs["state"] is SyncItemAttemptState.BLOCKED


def test_backfill_batch_reports_zero_output_as_complete_failure(mocker) -> None:
    _patch_backfill_dependencies(mocker, stored_count=0)

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "failed"
    assert result["success"] is False
    assert result["failed"] == 2
    assert result["checkpoint"]["next_offset"] == 0
    assert result["checkpoint"]["complete"] is False
    assert any(error["error"] == "zero_output" for error in result["errors"])


def test_backfill_batch_blocks_and_keeps_checkpoint_open_when_publication_fails(
    mocker,
) -> None:
    _factory, coordinator = _patch_backfill_dependencies(
        mocker,
        publication_failure=True,
    )

    result = backfill_active_a_share_core_data_batch_task.run(batch_size=2)

    assert result["outcome"] == "blocked"
    assert result["success"] is False
    assert result["stage"] == "publication"
    assert result["checkpoint"]["complete"] is False
    assert result["checkpoint"]["next_offset"] == 0
    assert result["published"] == 0
    assert any(
        error
        == {
            "domain": "publication",
            "asset_code": "universe",
            "error": "rebuild_failed",
        }
        for error in result["errors"]
    )
    coordinator.execute.assert_called_once()


def test_backfill_batch_reports_missing_provider_as_failure(mocker) -> None:
    mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill",
        return_value=["002156.SZ"],
    )
    mocker.patch(
        "apps.data_center.application.tasks.get_active_provider_id_by_source",
        return_value=None,
    )

    result = backfill_active_a_share_core_data_batch_task.run()

    assert result["outcome"] == "failed"
    assert result["stage"] == "provider"
    assert result["checkpoint"]["complete"] is False


def test_backfill_batch_blocks_when_market_session_is_unavailable(mocker) -> None:
    mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill",
        return_value=["002156.SZ"],
    )
    mocker.patch(
        "apps.data_center.application.tasks.get_active_provider_id_by_source",
        return_value=7,
    )
    mocker.patch(
        "apps.data_center.application.tasks.latest_completed_cn_market_session",
        return_value=None,
    )

    result = backfill_active_a_share_core_data_batch_task.run()

    assert result["outcome"] == "blocked"
    assert result["stage"] == "market_calendar"


def test_backfill_batch_returns_noop_after_checkpoint_completion(mocker) -> None:
    mocker.patch(
        "apps.data_center.application.tasks.list_active_stock_codes_for_backfill",
        return_value=["002156.SZ"],
    )

    result = backfill_active_a_share_core_data_batch_task.run(
        offset=1,
        universe_hash=_universe_hash("002156.SZ"),
    )

    assert result["outcome"] == "noop"
    assert result["checkpoint"]["complete"] is True
