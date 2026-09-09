"""Bounded staff input contracts for egress endpoints and route rules."""

from typing import Any
from urllib.parse import urlsplit

from rest_framework import serializers


class EgressEndpointSerializer(serializers.Serializer[dict[str, Any]]):
    """Validate endpoint metadata while keeping credentials write-only."""

    name = serializers.CharField(max_length=120)
    region = serializers.CharField(max_length=40)
    protocol = serializers.ChoiceField(choices=("http", "https"))
    host = serializers.CharField(max_length=255)
    port = serializers.IntegerField(min_value=1, max_value=65535)
    username = serializers.CharField(
        max_length=4096, required=False, allow_blank=True, write_only=True, trim_whitespace=False
    )
    password = serializers.CharField(
        max_length=4096, required=False, allow_blank=True, write_only=True, trim_whitespace=False
    )
    enabled = serializers.BooleanField(required=False)
    concurrency_limit = serializers.IntegerField(min_value=1, max_value=512, default=4)
    clear_credentials = serializers.BooleanField(required=False)


class EgressRuleSerializer(serializers.Serializer[dict[str, Any]]):
    """Define provider/domain/region selectors and one optional exit."""

    provider_id = serializers.IntegerField(min_value=1)
    dataset_key = serializers.CharField(max_length=120)
    domain_pattern = serializers.CharField(max_length=253)
    deployment_region = serializers.CharField(max_length=40)
    strategy = serializers.ChoiceField(choices=("direct", "fixed", "direct_fallback"))
    fixed_egress_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    priority = serializers.IntegerField(min_value=1, max_value=1000000)
    enabled = serializers.BooleanField(required=False)


class EgressContextSerializer(serializers.Serializer[dict[str, Any]]):
    """Preview a request; target network safety remains enforced by the service."""

    provider_id = serializers.IntegerField(min_value=1)
    dataset_key = serializers.CharField(max_length=120)
    url = serializers.URLField(max_length=2048)
    deployment_region = serializers.CharField(max_length=40)

    def validate_url(self, value: str) -> str:
        """Reject embedded authentication or non-request fragments at the HTTP boundary."""
        parts = urlsplit(value)
        if parts.username is not None or parts.password is not None or parts.fragment:
            raise serializers.ValidationError("目标地址不能包含登录凭据或片段。")
        return value
