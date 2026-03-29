"""Static guardrails for high-risk write paths."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_high_risk_write_paths_use_transactions() -> None:
    strategy_views = _read("apps/strategy/interface/views.py")
    beta_gate_views = _read("apps/beta_gate/interface/views.py")
    regime_views = _read("apps/regime/infrastructure/views.py")
    account_views = _read("apps/account/interface/views.py")

    assert "with transaction.atomic()" in strategy_views
    assert "with transaction.atomic()" in beta_gate_views
    assert "transaction.on_commit" in regime_views
    assert "with transaction.atomic()" in account_views


def test_prompt_force_reload_no_longer_deletes_before_recreate() -> None:
    prompt_command = _read("apps/prompt/interface/__init__.py")

    assert "existing_orm.delete()" not in prompt_command
    assert "repository.update_template" in prompt_command
    assert "repository.update_chain" in prompt_command


def test_unique_active_constraints_exist_for_config_models() -> None:
    beta_gate_models = _read("apps/beta_gate/infrastructure/models.py")
    regime_models = _read("apps/regime/infrastructure/models.py")

    assert "beta_gate_one_active_per_profile" in beta_gate_models
    assert "regime_single_active_threshold" in regime_models
