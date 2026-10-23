"""Application guards for direct temporary-target inspection requests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

from apps.simulated_trading.application import interface_services, temporary_target_access
from apps.simulated_trading.application.rebalance_plan_preview import (
    ReadOnlyRebalancePlanPreviewBuilder,
)
from apps.simulated_trading.domain.temporary_rebalance_targets import (
    TemporaryTargetValidationError,
)

_TARGET_TEXT = "600000.SH,50"
_UNUSED_PREVIEW_BUILDER = cast(ReadOnlyRebalancePlanPreviewBuilder, object())


def _account_row(
    *,
    account_id: object = 17,
    user_id: object = 23,
    active: object = True,
    account_type: object = "simulated",
) -> SimpleNamespace:
    """Return a small stand-in for the infrastructure-owned account row."""

    return SimpleNamespace(
        id=account_id,
        user_id=user_id,
        is_active=active,
        account_type=account_type,
    )


def _install_account_repository(
    monkeypatch: pytest.MonkeyPatch,
    account: object | None,
) -> tuple[Mock, Mock]:
    """Install an observable repository stub for the ownership boundary."""

    repository = Mock()
    repository.get_account_model_for_user.return_value = account
    provider = Mock(return_value=repository)
    monkeypatch.setattr(temporary_target_access, "get_simulated_account_repository", provider)
    return provider, repository


def _install_daily_service(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """Replace the inspection entry so negative cases prove no source or audit call occurs."""

    daily_service = Mock()
    monkeypatch.setattr(interface_services, "DailyInspectionService", daily_service)
    return daily_service


def _call_target_entry(
    *,
    account_id: object = 17,
    user_id: object = 23,
    strategy_id: object = None,
    auto_create_proposal: object = False,
    preview_builder: object = _UNUSED_PREVIEW_BUILDER,
    target_text: object = _TARGET_TEXT,
) -> dict[str, Any]:
    """Call the typed Application API while allowing malformed runtime inputs in tests."""

    return interface_services.run_daily_inspection(
        account_id=cast(int, account_id),
        inspection_date=None,
        strategy_id=cast(int | None, strategy_id),
        auto_create_proposal=cast(bool, auto_create_proposal),
        user_id=cast(int | None, user_id),
        preview_builder=cast(ReadOnlyRebalancePlanPreviewBuilder | None, preview_builder),
        temporary_target_weights=cast(str | None, target_text),
    )


@pytest.mark.parametrize("user_id", [None, 0, -1, True, "23", 23.0])
def test_temporary_targets_require_exact_positive_owner_id_before_repository(
    monkeypatch: pytest.MonkeyPatch,
    user_id: object,
) -> None:
    provider = Mock()
    monkeypatch.setattr(temporary_target_access, "get_simulated_account_repository", provider)
    daily_service = _install_daily_service(monkeypatch)

    with pytest.raises(TemporaryTargetValidationError) as error:
        _call_target_entry(user_id=user_id)

    assert error.value.reason_code == "TARGET_OWNER_REQUIRED"
    provider.assert_not_called()
    daily_service.run.assert_not_called()
    daily_service.run_and_create_proposal.assert_not_called()


def test_temporary_targets_require_exact_positive_account_id_before_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = Mock()
    monkeypatch.setattr(temporary_target_access, "get_simulated_account_repository", provider)
    daily_service = _install_daily_service(monkeypatch)

    with pytest.raises(TemporaryTargetValidationError) as error:
        _call_target_entry(account_id=True)

    assert error.value.reason_code == "TARGET_ACCOUNT_ID_INVALID"
    provider.assert_not_called()
    daily_service.run.assert_not_called()


@pytest.mark.parametrize(
    ("account", "reason_code"),
    [
        (None, "TARGET_ACCOUNT_NOT_OWNED"),
        (_account_row(user_id=24), "TARGET_ACCOUNT_NOT_OWNED"),
        (_account_row(account_id=18), "TARGET_ACCOUNT_NOT_OWNED"),
        (_account_row(active=False), "TARGET_ACCOUNT_INACTIVE"),
        (_account_row(account_type="real"), "TARGET_ACCOUNT_NOT_SIMULATED"),
        (_account_row(account_type=1), "TARGET_ACCOUNT_NOT_SIMULATED"),
        (_account_row(user_id=True), "TARGET_ACCOUNT_NOT_OWNED"),
    ],
)
def test_temporary_targets_reject_unowned_or_ineligible_account_before_inspection(
    monkeypatch: pytest.MonkeyPatch,
    account: object | None,
    reason_code: str,
) -> None:
    provider, repository = _install_account_repository(monkeypatch, account)
    daily_service = _install_daily_service(monkeypatch)

    with pytest.raises(TemporaryTargetValidationError) as error:
        _call_target_entry()

    assert error.value.reason_code == reason_code
    provider.assert_called_once_with()
    repository.get_account_model_for_user.assert_called_once_with(17, 23)
    daily_service.run.assert_not_called()
    daily_service.run_and_create_proposal.assert_not_called()


@pytest.mark.parametrize(
    ("strategy_id", "auto_create_proposal", "preview_builder", "reason_code"),
    [
        (31, False, _UNUSED_PREVIEW_BUILDER, "TARGET_STRATEGY_ID_FORBIDDEN"),
        (None, True, _UNUSED_PREVIEW_BUILDER, "TARGET_PROPOSAL_FORBIDDEN"),
        (None, False, None, "TARGET_PREVIEW_BUILDER_REQUIRED"),
    ],
)
def test_temporary_target_contract_rejects_incompatible_options_before_repository(
    monkeypatch: pytest.MonkeyPatch,
    strategy_id: int | None,
    auto_create_proposal: bool,
    preview_builder: ReadOnlyRebalancePlanPreviewBuilder | None,
    reason_code: str,
) -> None:
    provider = Mock()
    monkeypatch.setattr(temporary_target_access, "get_simulated_account_repository", provider)
    daily_service = _install_daily_service(monkeypatch)

    with pytest.raises(TemporaryTargetValidationError) as error:
        _call_target_entry(
            strategy_id=strategy_id,
            auto_create_proposal=auto_create_proposal,
            preview_builder=preview_builder,
        )

    assert error.value.reason_code == reason_code
    provider.assert_not_called()
    daily_service.run.assert_not_called()
    daily_service.run_and_create_proposal.assert_not_called()


def test_invalid_temporary_target_is_rejected_before_source_reads_and_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, repository = _install_account_repository(monkeypatch, _account_row())
    daily_service = _install_daily_service(monkeypatch)

    with pytest.raises(TemporaryTargetValidationError) as error:
        _call_target_entry(target_text="malformed row")

    assert error.value.reason_code == "TARGET_ROW_FORMAT_INVALID"
    provider.assert_called_once_with()
    repository.get_account_model_for_user.assert_called_once_with(17, 23)
    daily_service.run.assert_not_called()
    daily_service.run_and_create_proposal.assert_not_called()


def test_blank_temporary_target_keeps_the_existing_account_only_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = Mock()
    monkeypatch.setattr(temporary_target_access, "get_simulated_account_repository", provider)
    daily_service = _install_daily_service(monkeypatch)
    daily_service.run.return_value = {"report_id": 1}

    result = _call_target_entry(user_id=None, preview_builder=None, target_text="  ")

    assert result == {"report_id": 1}
    provider.assert_not_called()
    daily_service.run.assert_called_once()
    assert daily_service.run.call_args.kwargs["temporary_targets"] is None
    daily_service.run_and_create_proposal.assert_not_called()
