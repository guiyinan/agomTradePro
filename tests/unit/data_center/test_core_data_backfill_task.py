"""Active A-share core-data backfill task outcome contracts."""

import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from apps.data_center.application.tasks import (
    backfill_active_a_share_core_data_batch_task,
)

AUTHORITY_HASH = "a" * 64


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

    repositories = {name: mocker.Mock() for name in ("run", "batch", "checkpoint")}
    snapshot = mocker.patch(
        "apps.data_center.application.tasks.persist_sync_control_plane_snapshot"
    )
    snapshot.side_effect = lambda run, batch, checkpoint: (
        repositories["run"].save(run),
        repositories["batch"].save(batch),
        repositories["checkpoint"].save(checkpoint),
    )
    return repositories


def _patch_backfill_dependencies(
    mocker,
    *,
    stored_count=1,
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
            count = len(request.asset_codes) if domain == "quote" else stored_count
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

            def _execute_current_batch(*, provider_id, asset_codes, as_of_date):
                del provider_id, as_of_date
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
        coordinator.execute.return_value = SimpleNamespace(published_count=6)
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
    assert result["published"] == 6
    assert result["checkpoint"] == {
        "offset": 0,
        "next_offset": 2,
        "total_assets": 2,
        "complete": True,
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
    assert batch_saves[0].args[0].published == 6
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

    result = backfill_active_a_share_core_data_batch_task.run(offset=1)

    assert result["outcome"] == "noop"
    assert result["checkpoint"]["complete"] is True
