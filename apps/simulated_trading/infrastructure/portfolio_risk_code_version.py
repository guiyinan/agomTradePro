"""Fingerprint the actual risk code used by retained simulation evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path

from core.exceptions import MissingConfigError


def portfolio_risk_code_version() -> str:
    """Hash relevant on-disk code instead of claiming an unrelated Git HEAD."""

    root = Path(__file__).resolve().parents[3]
    patterns = (
        ("apps/risk_center/domain", "*.py"),
        ("apps/risk_center/application", "portfolio_*.py"),
        ("apps/risk_center/application", "scenario_*.py"),
        ("apps/risk_center/infrastructure", "portfolio_*.py"),
        ("apps/risk_center/infrastructure", "retained_portfolio_*.py"),
        ("apps/risk_center/infrastructure", "configured_portfolio_*.py"),
        ("apps/risk_center/infrastructure", "scenario_*.py"),
        ("apps/simulated_trading/application", "portfolio_risk*.py"),
        ("apps/simulated_trading/infrastructure", "portfolio_risk*.py"),
    )
    files = {
        path
        for folder, pattern in patterns
        for path in (root / folder).glob(pattern)
        if path.name != "__init__.py"
    }
    files.update(
        root / name
        for name in (
            "apps/simulated_trading/application/execution_settlement_uow.py",
            "apps/simulated_trading/application/order_reservation.py",
            "apps/simulated_trading/application/owner_order_submission.py",
            "apps/simulated_trading/application/order_submission_market.py",
            "apps/simulated_trading/application/rebalance_resource_snapshot.py",
            "apps/simulated_trading/infrastructure/rebalance_resource_snapshot_repository.py",
            "apps/simulated_trading/infrastructure/execution_settlement_uow_repository.py",
            "apps/simulated_trading/infrastructure/order_reservation_repository.py",
            "apps/simulated_trading/infrastructure/order_reservation_fill_repository.py",
            "apps/simulated_trading/infrastructure/order_reservation_fill_chain_storage.py",
            "apps/simulated_trading/infrastructure/order_reservation_codec.py",
            "apps/simulated_trading/infrastructure/execution_settlement_position_validation.py",
            "apps/simulated_trading/infrastructure/execution_settlement_stop_loss_threshold.py",
            "apps/simulated_trading/domain/order_reservation.py",
            "apps/simulated_trading/portfolio_risk_composition.py",
            "apps/simulated_trading/portfolio_risk_close_snapshot_composition.py",
            "apps/risk_center/portfolio_risk_composition.py",
            "apps/risk_center/execution_settlement_composition.py",
            "apps/risk_center/application/close_snapshot_simulation.py",
            "apps/risk_center/application/execution_settlement_v3.py",
            "apps/data_center/application/sina_quote_capture.py",
            "apps/data_center/domain/sina_quote_capture.py",
            "apps/data_center/domain/market_time.py",
            "apps/simulated_trading/close_snapshot_submission_composition.py",
            "apps/simulated_trading/execution_settlement_composition.py",
            "apps/simulated_trading/execution_current_reference_composition.py",
            "apps/simulated_trading/domain/execution_current_reference.py",
            "apps/simulated_trading/domain/execution_settlement_calendar.py",
            "apps/simulated_trading/domain/execution_settlement_identity.py",
            "apps/simulated_trading/domain/execution_settlement_primitives.py",
            "apps/simulated_trading/owner_order_submission_composition.py",
            "apps/simulated_trading/local_daily_match_composition.py",
            "core/integration/config_center_runtime.py",
            "apps/config_center/application/runtime_value_evidence.py",
        )
    )
    digest = hashlib.sha256()
    try:
        for path in sorted(files, key=lambda value: value.relative_to(root).as_posix()):
            name = path.relative_to(root).as_posix().encode("utf-8")
            content = path.read_bytes()
            digest.update(len(name).to_bytes(8, "big"))
            digest.update(name)
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
    except OSError as error:
        raise MissingConfigError(code="PORTFOLIO_RISK_CODE_FINGERPRINT_UNAVAILABLE") from error
    return "sha256:" + digest.hexdigest()
