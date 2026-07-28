"""Typed serializers for TUI-specific backtest workflows."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from rest_framework import serializers


class DecisionReplayComparisonSerializer(serializers.Serializer[dict[str, Any]]):
    """Run all fixed manual decision replay branches."""

    portfolio_id = serializers.IntegerField(min_value=1)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    initial_capital = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
        min_value=Decimal("0"),
        default=Decimal("1000000.00"),
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Require a non-empty replay interval."""

        start_date = attrs.get("start_date")
        end_date = attrs.get("end_date")
        if isinstance(start_date, date) and isinstance(end_date, date) and start_date >= end_date:
            raise serializers.ValidationError("start_date must be before end_date")
        return attrs
