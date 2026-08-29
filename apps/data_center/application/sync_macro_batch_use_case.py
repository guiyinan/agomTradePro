"""Provider selection and governed failover for macro synchronization batches."""

from __future__ import annotations

from apps.data_center.application.dtos import (
    MacroFailoverDecision,
    SyncMacroBatchRequest,
    SyncMacroBatchResult,
    SyncMacroRequest,
    SyncResult,
)
from apps.data_center.application.sync_macro_use_cases import (
    MacroFailoverPolicy,
    MacroFailoverPolicyProvider,
    PreparedMacroSync,
    SyncMacroUseCase,
)
from apps.data_center.application.sync_use_cases import (
    RECOVERABLE_DATA_CENTER_EXCEPTIONS,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.enums import DataCapability
from apps.data_center.domain.protocols import (
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
)
from apps.data_center.domain.rules import macro_series_are_consistent


class SyncMacroBatchUseCase:
    """Select one configured macro provider and synchronize an indicator batch."""

    def __init__(
        self,
        provider_repo: ProviderConfigRepositoryProtocol,
        provider_registry: ProviderRegistryProtocol,
        sync_use_case: SyncMacroUseCase,
        *,
        failover_policy_provider: MacroFailoverPolicyProvider | None = None,
    ) -> None:
        self._provider_repo = provider_repo
        self._provider_registry = provider_registry
        self._sync_use_case = sync_use_case
        self._failover_policy_provider = failover_policy_provider

    def execute(self, request: SyncMacroBatchRequest) -> SyncMacroBatchResult:
        """Synchronize every requested indicator under one failover policy."""

        if request.source or self._failover_policy_provider is None:
            return self._execute_single_provider(request)
        policy = self._failover_policy_provider.get_policy()
        if not isinstance(policy, MacroFailoverPolicy):
            raise TypeError("macro failover policy provider returned an invalid policy")
        if not policy.enabled:
            return self._execute_single_provider(request)
        configs = self._list_provider_configs(None)
        if not configs:
            for indicator_code in request.indicator_codes:
                self._sync_use_case.exhaust_failover(
                    indicator_code=indicator_code,
                    start=request.start,
                    end=request.end,
                    from_provider="macro-provider-policy",
                    attempted_provider_names=(),
                    tolerance=policy.tolerance,
                )
            raise ValueError("No active macro provider configured")

        stored_count = 0
        errors: list[str] = []
        selected_provider = configs[0].name
        for indicator_code in request.indicator_codes:
            try:
                result = self._execute_indicator_with_failover(
                    request,
                    indicator_code=indicator_code,
                    configs=configs,
                    tolerance=policy.tolerance,
                )
            except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
                errors.append(f"{indicator_code}: {self._bounded_batch_error(exc)}")
                continue
            stored_count += result.stored_count
            selected_provider = result.provider_name

        return SyncMacroBatchResult(
            provider_name=selected_provider,
            stored_count=stored_count,
            errors=errors,
        )

    def _execute_single_provider(self, request: SyncMacroBatchRequest) -> SyncMacroBatchResult:
        """Preserve explicit-source and disabled-policy single-provider behavior."""

        config = self._select_provider(request.source)
        if config.id is None:
            raise ValueError(f"Provider has no persistent id: {config.name}")

        stored_count = 0
        errors: list[str] = []
        for indicator_code in request.indicator_codes:
            try:
                result = self._sync_use_case.execute(
                    SyncMacroRequest(
                        provider_id=config.id,
                        indicator_code=indicator_code,
                        start=request.start,
                        end=request.end,
                    )
                )
            except RECOVERABLE_DATA_CENTER_EXCEPTIONS as exc:
                errors.append(f"{indicator_code}: {self._bounded_batch_error(exc)}")
                continue
            stored_count += result.stored_count

        return SyncMacroBatchResult(
            provider_name=config.name,
            stored_count=stored_count,
            errors=errors,
        )

    def _execute_indicator_with_failover(
        self,
        request: SyncMacroBatchRequest,
        *,
        indicator_code: str,
        configs: list[ProviderConfig],
        tolerance: float,
    ) -> SyncResult:
        """Use two independent governed fallbacks before accepting a switch."""

        primary = configs[0]
        primary_request = self._request_for_config(request, indicator_code, primary)
        try:
            primary_prepared = self._sync_use_case.prepare(primary_request)
        except RECOVERABLE_DATA_CENTER_EXCEPTIONS:
            primary_prepared = None
        if primary_prepared is not None:
            primary_result = self._sync_use_case.commit(primary_prepared)
            if primary_prepared.facts:
                return primary_result

        candidates: list[PreparedMacroSync] = []
        for config in configs[1:]:
            try:
                prepared = self._sync_use_case.prepare(
                    self._request_for_config(request, indicator_code, config)
                )
            except RECOVERABLE_DATA_CENTER_EXCEPTIONS:
                continue
            if not prepared.facts:
                self._sync_use_case.commit(prepared)
                continue
            candidates.append(prepared)

        if len(candidates) < 2:
            if candidates:
                self._sync_use_case.block_failover(
                    candidates[0],
                    from_provider=primary.name,
                    tolerance=tolerance,
                    observed_deviation=None,
                    reason_code="failover_consistency_evidence_missing",
                    error_class="ConsistencyEvidenceUnavailable",
                )
            else:
                self._sync_use_case.exhaust_failover(
                    indicator_code=indicator_code,
                    start=request.start,
                    end=request.end,
                    from_provider=primary.name,
                    attempted_provider_names=tuple(config.name for config in configs),
                    tolerance=tolerance,
                )
            raise RuntimeError("macro_failover_consistency_evidence_missing")

        first_comparison: tuple[PreparedMacroSync, PreparedMacroSync, float | None] | None = None
        for index, candidate in enumerate(candidates[:-1]):
            for verifier in candidates[index + 1 :]:
                consistent, deviation = self._compare_prepared_macro_series(
                    candidate,
                    verifier,
                    tolerance=tolerance,
                )
                if first_comparison is None:
                    first_comparison = (candidate, verifier, deviation)
                if consistent and deviation is not None:
                    decision = MacroFailoverDecision(
                        from_provider=primary.name,
                        to_provider=candidate.provider_name,
                        verification_provider=verifier.provider_name,
                        tolerance=tolerance,
                        observed_deviation=deviation,
                        reason_code="primary_unavailable_fallback_verified",
                    )
                    return self._sync_use_case.commit(
                        candidate,
                        failover_decision=decision,
                        verification=verifier,
                    )

        comparison = first_comparison
        if comparison is None:
            raise RuntimeError("macro_failover_consistency_evidence_missing")
        candidate, verifier, deviation = comparison
        if deviation is None:
            reason_code = "failover_consistency_evidence_missing"
            error_class = "ConsistencyEvidenceUnavailable"
            public_error = "macro_failover_consistency_evidence_missing"
        else:
            reason_code = "failover_consistency_rejected"
            error_class = "ConsistencyError"
            public_error = "macro_failover_consistency_rejected"
        self._sync_use_case.block_failover(
            candidate,
            from_provider=primary.name,
            tolerance=tolerance,
            observed_deviation=deviation,
            reason_code=reason_code,
            error_class=error_class,
            verification=verifier,
        )
        raise RuntimeError(public_error)

    @staticmethod
    def _request_for_config(
        request: SyncMacroBatchRequest,
        indicator_code: str,
        config: ProviderConfig,
    ) -> SyncMacroRequest:
        """Bind one server-selected provider id to a batch indicator."""

        if config.id is None:
            raise ValueError("macro provider has no persistent id")
        return SyncMacroRequest(
            provider_id=config.id,
            indicator_code=indicator_code,
            start=request.start,
            end=request.end,
        )

    @staticmethod
    def _compare_prepared_macro_series(
        candidate: PreparedMacroSync,
        verifier: PreparedMacroSync,
        *,
        tolerance: float,
    ) -> tuple[bool, float | None]:
        """Compare canonical-unit observations at overlapping reporting dates."""

        candidate_values = {fact.reporting_period: fact.value for fact in candidate.facts}
        verifier_values = {fact.reporting_period: fact.value for fact in verifier.facts}
        return macro_series_are_consistent(
            candidate_values,
            verifier_values,
            tolerance=tolerance,
        )

    @staticmethod
    def _bounded_batch_error(error: BaseException) -> str:
        """Return only stable application reasons or an exception class token."""

        message = str(error)
        if message in {
            "macro_failover_consistency_evidence_missing",
            "macro_failover_consistency_rejected",
        }:
            return message
        return type(error).__name__

    def _select_provider(self, source: str | None) -> ProviderConfig:
        configs = self._list_provider_configs(source)
        if configs:
            return configs[0]
        suffix = f" for source {source!r}" if source else ""
        raise ValueError(f"No active macro provider configured{suffix}")

    def _list_provider_configs(self, source: str | None) -> list[ProviderConfig]:
        """Return active supported provider configs in canonical priority order."""

        requested = source.strip().lower() if source else ""
        configs = sorted(
            (config for config in self._provider_repo.list_all() if config.is_active),
            key=lambda config: config.priority,
        )
        selected: list[ProviderConfig] = []
        for config in configs:
            if requested and requested not in {config.name.lower(), config.source_type.lower()}:
                continue
            if config.id is None:
                continue
            provider = self._provider_registry.get_by_id(config.id)
            if provider is not None and provider.supports(DataCapability.MACRO):
                selected.append(config)
        return selected


__all__ = ["SyncMacroBatchUseCase"]
