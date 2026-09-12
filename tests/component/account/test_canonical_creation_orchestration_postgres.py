"""Public production orchestration against actual PostgreSQL creation ledgers."""

from dataclasses import replace
from datetime import timedelta

import pytest
from django.db import connections
from django.utils import timezone

from apps.account.application.canonical_account_creation_replay import (
    CanonicalAccountCreationReplayConflict,
)
from apps.account.infrastructure import (
    canonical_account_creation_consumption_repository as consumption,
)
from apps.simulated_trading.application.canonical_account_creation_row import (
    CanonicalAccountCreationRowConflict,
    CanonicalAccountCreationRowUnavailable,
)
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from core.integration import canonical_account_creation as orchestration
from tests.component.account.creation_chain_postgres_fixture import CREATION_LEDGER_MODELS
from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    _new_user,
)
from tests.unit.simulated_trading.test_canonical_account_creation_request import _request
from tests.unit.simulated_trading.test_creation_composition import _settings

pytest_plugins = (
    "tests.component.account.test_current_account_ownership_postgres",
    "tests.component.account.creation_chain_postgres_fixture",
)


def _reject_default(execute, sql, params, many, context):
    raise AssertionError("canonical creation orchestration queried default")


def _counts(alias):
    return [model._base_manager.using(alias).count() for model in CREATION_LEDGER_MODELS]


def test_actual_create_replay_content_conflicts_and_expired_source_replay(
    creation_chain_alias, monkeypatch
):
    alias = creation_chain_alias
    user, _ = _new_user(alias)
    request = replace(_request(), user_id=user.pk)
    settings = _settings()
    with connections["default"].execute_wrapper(_reject_default):
        first = orchestration.create_canonical_account(
            request=request, using=alias, settings=settings
        )
        assert not first.replayed
        replay = orchestration.create_canonical_account(
            request=request, using=alias, settings=settings
        )
        assert (
            replay.replayed and replay.account == first.account and replay.binding == first.binding
        )
        with pytest.raises(CanonicalAccountCreationReplayConflict):
            orchestration.create_canonical_account(
                request=replace(request, initial_capital=2000.0), using=alias, settings=settings
            )
        with pytest.raises(CanonicalAccountCreationRowConflict):
            orchestration.create_canonical_account(
                request=replace(request, request_key="different-key"),
                using=alias,
                settings=settings,
            )
        future = timezone.now() + timedelta(days=1)
        assert first.binding.creation_root.physical_observation.valid_until < future
        monkeypatch.setattr(
            consumption.DjangoCanonicalAccountCreationConsumptionClock, "now", lambda self: future
        )
        expired_replay = orchestration.create_canonical_account(
            request=request, using=alias, settings=settings
        )
        assert expired_replay.replayed and expired_replay.binding == first.binding
        assert expired_replay.account.account_id == first.account.account_id
        SimulatedAccountModel.objects.using(alias).filter(pk=first.account.account_id).update(
            is_active=False
        )
        with pytest.raises(CanonicalAccountCreationRowUnavailable):
            orchestration.create_canonical_account(request=request, using=alias, settings=settings)
        assert SimulatedAccountModel.objects.using(alias).count() == 1
        assert _counts(alias) == [1, 1, 1, 1, 1, 1, 0, 1]


def test_late_binding_failure_rolls_back_every_stage_then_same_request_can_retry(
    creation_chain_alias, monkeypatch
):
    alias = creation_chain_alias
    user, _ = _new_user(alias)
    request = replace(_request(), user_id=user.pk)
    settings = _settings()
    original_factory = orchestration.build_canonical_account_creation_stages
    seen = []

    class FailBinding:
        def execute(self, command):
            seen.append(_counts(alias))
            assert SimulatedAccountModel.objects.using(alias).count() == 1
            raise RuntimeError("injected late binding failure")

    def failing_factory(**kwargs):
        return replace(original_factory(**kwargs), bind=FailBinding())

    monkeypatch.setattr(orchestration, "build_canonical_account_creation_stages", failing_factory)
    with connections["default"].execute_wrapper(_reject_default):
        with pytest.raises(RuntimeError, match="injected late binding failure"):
            orchestration.create_canonical_account(request=request, using=alias, settings=settings)
        assert seen == [[1, 1, 1, 1, 1, 0, 0, 0]]
        assert _counts(alias) == [0] * 8
        assert SimulatedAccountModel.objects.using(alias).count() == 0
        monkeypatch.setattr(
            orchestration, "build_canonical_account_creation_stages", original_factory
        )
        completed = orchestration.create_canonical_account(
            request=request, using=alias, settings=settings
        )
        assert not completed.replayed
        assert _counts(alias) == [1, 1, 1, 1, 1, 1, 0, 1]
