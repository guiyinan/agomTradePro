"""Compose explicit raw daily-limit capture without publishing or scheduling it."""

from __future__ import annotations

from apps.data_center.application.price_limit_capture import (
    CaptureExactPriceLimitUseCase,
    ReadRetainedPriceLimitUseCase,
)
from apps.data_center.infrastructure.provider_adapters import TushareUnifiedProviderAdapter
from apps.data_center.infrastructure.provider_state_repositories import ProviderConfigRepository
from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository


def build_price_limit_capture_use_case() -> CaptureExactPriceLimitUseCase:
    """Use current provider configuration and the existing credential/raw owners."""
    return CaptureExactPriceLimitUseCase(
        ProviderConfigRepository(), TushareUnifiedProviderAdapter, RawLandingRepository()
    )


def build_retained_price_limit_reader() -> ReadRetainedPriceLimitUseCase:
    """Build an exact offline reader with no provider configuration dependency."""
    return ReadRetainedPriceLimitUseCase(RawLandingRepository())
