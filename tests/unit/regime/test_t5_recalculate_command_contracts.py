"""Management command contracts for atomic Regime history recalculation."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.core.management.base import CommandError

from apps.regime.management.commands import recalculate_regime
from apps.regime.management.commands.recalculate_regime import Command


def _options(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "clear_cache_only": False,
        "skip_backup": False,
        "start_date": "2026-07-01",
        "end_date": "2026-07-02",
        "frequency": "daily",
    }
    values.update(overrides)
    return values


def test_handle_supports_clear_only_and_atomic_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recalculate_regime.CacheService, "invalidate_regime", lambda: False
    )
    command = Command()
    command.handle(**_options(clear_cache_only=True))

    snapshots = [SimpleNamespace(observed_at=date(2026, 7, 1))]
    monkeypatch.setattr(command, "_backup_existing_data", MagicMock(return_value=3))
    monkeypatch.setattr(
        command, "_calculate_regime_snapshots", MagicMock(return_value=snapshots)
    )
    repository = MagicMock()
    repository.replace_snapshots_in_range.return_value = 1
    monkeypatch.setattr(
        recalculate_regime, "DjangoRegimeRepository", lambda: repository
    )
    monkeypatch.setattr(
        recalculate_regime.CacheService, "invalidate_regime", lambda: True
    )

    command.handle(**_options())

    repository.replace_snapshots_in_range.assert_called_once_with(
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        snapshots=snapshots,
    )


def test_handle_rejects_invalid_range_and_empty_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recalculate_regime.CacheService, "invalidate_regime", lambda: True
    )
    command = Command()
    with pytest.raises(CommandError, match="start-date"):
        command.handle(
            **_options(
                start_date="2026-07-03",
                end_date="2026-07-02",
                skip_backup=True,
            )
        )

    monkeypatch.setattr(command, "_calculate_regime_snapshots", lambda *_args, **_kwargs: [])
    with pytest.raises(CommandError, match="No valid"):
        command.handle(**_options(skip_backup=True))


def test_backup_existing_data_handles_empty_and_writes_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    values = MagicMock(return_value=[])
    query = SimpleNamespace(order_by=lambda _field: SimpleNamespace(values=values))
    monkeypatch.setattr(
        recalculate_regime,
        "RegimeLog",
        SimpleNamespace(_default_manager=SimpleNamespace(all=lambda: query)),
    )
    command = Command()
    assert command._backup_existing_data() == 0

    records = [
        {
            "observed_at": date(2026, 7, 1),
            "dominant_regime": "Recovery",
            "confidence": 0.8,
        }
    ]
    values.return_value = records
    monkeypatch.chdir(tmp_path)
    assert command._backup_existing_data() == 1
    files = list((tmp_path / "management" / "backups").glob("*.json"))
    assert len(files) == 1
    assert "Recovery" in files[0].read_text(encoding="utf-8")


def test_calculate_snapshots_covers_success_no_data_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MagicMock()
    repository.get_available_dates.return_value = []
    monkeypatch.setattr(
        recalculate_regime, "MacroRepositoryAdapter", lambda: repository
    )
    command = Command()
    assert (
        command._calculate_regime_snapshots(
            date(2026, 7, 1), date(2026, 7, 2), frequency="daily"
        )
        == []
    )

    repository.get_available_dates.return_value = [date(2026, 7, 1)]
    result = SimpleNamespace()
    use_case = SimpleNamespace(
        execute=MagicMock(
            side_effect=[
                SimpleNamespace(success=True, result=result, error=None),
                SimpleNamespace(success=True, result=result, error=None),
            ]
        )
    )
    monkeypatch.setattr(
        recalculate_regime, "CalculateRegimeV2UseCase", lambda _repository: use_case
    )
    snapshot = SimpleNamespace(
        dominant_regime="Recovery",
        confidence=0.8,
        growth_momentum_z=1.0,
        inflation_momentum_z=-0.5,
    )
    monkeypatch.setattr(
        recalculate_regime,
        "build_regime_snapshot_from_v2_result",
        lambda **_kwargs: snapshot,
    )

    snapshots = command._calculate_regime_snapshots(
        date(2026, 7, 1), date(2026, 7, 2), frequency="daily"
    )
    assert snapshots == [snapshot, snapshot]

    use_case.execute.side_effect = [
        SimpleNamespace(success=False, result=None, error="insufficient data"),
        RuntimeError("provider down"),
    ]
    with pytest.raises(CommandError, match="2 dates"):
        command._calculate_regime_snapshots(
            date(2026, 7, 1), date(2026, 7, 2), frequency="daily"
        )


def test_add_arguments_registers_all_command_options() -> None:
    parser = MagicMock()
    Command().add_arguments(parser)
    assert parser.add_argument.call_count == 5
