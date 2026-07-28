"""Strict query serializers for Agent Runtime operator TUI endpoints."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.agent_runtime.domain.entities import (
    ApprovalStatus,
    ProposalStatus,
    RiskLevel,
    TaskDomain,
    TaskStatus,
)


class OperatorTaskListQuerySerializer(serializers.Serializer[Any]):
    """Validate operator task queue filters."""

    status = serializers.ChoiceField(
        choices=tuple(item.value for item in TaskStatus),
        required=False,
        allow_blank=True,
    )
    task_domain = serializers.ChoiceField(
        choices=tuple(item.value for item in TaskDomain),
        required=False,
        allow_blank=True,
    )
    search = serializers.CharField(max_length=100, required=False, allow_blank=True)
    attention = serializers.BooleanField(required=False, default=False)


class OperatorProposalListQuerySerializer(serializers.Serializer[Any]):
    """Validate operator proposal queue filters."""

    status = serializers.ChoiceField(
        choices=tuple(item.value for item in ProposalStatus),
        required=False,
        allow_blank=True,
    )
    approval_status = serializers.ChoiceField(
        choices=tuple(item.value for item in ApprovalStatus),
        required=False,
        allow_blank=True,
    )
    risk_level = serializers.ChoiceField(
        choices=tuple(item.value for item in RiskLevel),
        required=False,
        allow_blank=True,
    )
    search = serializers.CharField(max_length=100, required=False, allow_blank=True)
