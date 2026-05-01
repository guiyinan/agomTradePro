"""Decision data reliability bridges used by non-owning modules."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from apps.data_center.application.dtos import DecisionReliabilityRepairRequest
from apps.data_center.application.interface_services import make_decision_repair_use_case


def refresh_pulse_macro_inputs(
    *,
    target_date: date,
    macro_indicator_codes: Sequence[str],
    asset_codes: Sequence[str],
) -> dict[str, Any]:
    """Repair the macro and quote inputs that Pulse depends on."""

    report = make_decision_repair_use_case(user=None).execute(
        DecisionReliabilityRepairRequest(
            target_date=target_date,
            portfolio_id=None,
            asset_codes=[str(code).strip().upper() for code in asset_codes if code],
            macro_indicator_codes=[
                str(code).strip().upper() for code in macro_indicator_codes if code
            ],
            strict=False,
            repair_pulse=False,
            repair_alpha=False,
        )
    )
    return report.to_dict()
