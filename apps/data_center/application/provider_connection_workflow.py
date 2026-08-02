"""Provider connection-test workflow and credential redaction."""

from __future__ import annotations

import dataclasses

from apps.data_center.application.provider_capabilities import SOURCE_TYPE_CAPABILITIES
from apps.data_center.domain.entities import ConnectionTestResult, ProviderConfig
from apps.data_center.domain.enums import DataCapability
from apps.data_center.domain.protocols import (
    ConnectionTesterProtocol,
    ProviderConfigRepositoryProtocol,
)


def _redact_text(value: str, secrets: tuple[str, ...]) -> str:
    redacted = value
    for secret in secrets:
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _redact_result(
    result: ConnectionTestResult,
    config: ProviderConfig,
) -> ConnectionTestResult:
    secrets = tuple(
        value
        for value in (
            str(config.api_key or "").strip(),
            str(config.api_secret or "").strip(),
        )
        if value
    )
    if not secrets:
        return result
    return dataclasses.replace(
        result,
        summary=_redact_text(result.summary, secrets),
        logs=[_redact_text(log, secrets) for log in result.logs],
    )


class RunProviderConnectionTestUseCase:
    """Run a real provider probe and persist its sanitized health result."""

    def __init__(
        self,
        repo: ProviderConfigRepositoryProtocol,
        tester: ConnectionTesterProtocol,
    ) -> None:
        self._repo = repo
        self._tester = tester

    def execute(self, provider_id: int) -> ConnectionTestResult | None:
        """Probe one provider, redact credentials, and persist health metadata."""
        config = self._repo.get_by_id(provider_id)
        if config is None:
            return None
        result = _redact_result(self._tester.test(config), config)
        self._persist_provider_health_probe(config, result)
        return result

    def _persist_provider_health_probe(
        self,
        config: ProviderConfig,
        result: ConnectionTestResult,
    ) -> None:
        extra_config = dict(config.extra_config or {})
        recorded_at = result.tested_at
        extra_config["provider_last_success_at"] = (
            recorded_at.isoformat()
            if result.success
            else extra_config.get("provider_last_success_at")
        )
        extra_config["provider_last_probe_at"] = recorded_at.isoformat()
        extra_config["provider_last_status"] = "healthy" if result.success else "degraded"
        extra_config["provider_last_error"] = "" if result.success else result.summary

        capability_metrics = dict(extra_config.get("health_metrics") or {})
        dataset_metrics = dict(extra_config.get("health_metrics_by_dataset") or {})
        for capability in SOURCE_TYPE_CAPABILITIES.get(config.source_type, ()):
            try:
                dataset_key = DataCapability(capability).dataset_key
            except ValueError:
                dataset_key = capability
            metric = dict(
                dataset_metrics.get(dataset_key) or capability_metrics.get(capability) or {}
            )
            if result.success:
                metric.update(
                    last_success_at=recorded_at.isoformat(),
                    consecutive_failures=0,
                    last_status="healthy",
                    last_error="",
                )
            else:
                metric.update(
                    consecutive_failures=int(metric.get("consecutive_failures", 0)) + 1,
                    last_failure_at=recorded_at.isoformat(),
                    last_status="degraded",
                    last_error=result.summary,
                )
            capability_metrics[capability] = metric
            dataset_metrics[dataset_key] = metric

        extra_config["health_metrics"] = capability_metrics
        extra_config["health_metrics_by_dataset"] = dataset_metrics
        self._repo.save(dataclasses.replace(config, extra_config=extra_config))
