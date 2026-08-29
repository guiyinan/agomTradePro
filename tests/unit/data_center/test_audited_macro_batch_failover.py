"""RED contracts for verified macro-provider failover orchestration."""

from __future__ import annotations

from datetime import UTC, date, datetime

from apps.data_center.application.dtos import SyncMacroBatchRequest, SyncMacroRequest, SyncResult
from apps.data_center.application.sync_use_cases import (
    MacroFailoverPolicy,
    PreparedMacroSync,
    SyncMacroBatchUseCase,
)
from apps.data_center.domain.entities import MacroFact, ProviderConfig
from apps.data_center.domain.enums import DataCapability

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _config(provider_id: int, name: str, priority: int) -> ProviderConfig:
    return ProviderConfig(
        id=provider_id,
        name=name,
        source_type="tushare",
        is_active=True,
        priority=priority,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )


def _fact(source: str, value: float = 2.1) -> MacroFact:
    return MacroFact(
        indicator_code="CN_CPI",
        reporting_period=date(2026, 8, 1),
        value=value,
        unit="%",
        source=source,
        published_at=date(2026, 8, 3),
        fetched_at=NOW,
    )


class _Provider:
    def supports(self, capability: DataCapability) -> bool:
        return capability is DataCapability.MACRO


class _ProviderRepository:
    def __init__(self, configs: list[ProviderConfig] | None = None) -> None:
        self.configs = (
            configs
            if configs is not None
            else [
                _config(1, "primary", 1),
                _config(2, "fallback-a", 2),
                _config(3, "verifier", 3),
            ]
        )

    def list_all(self) -> list[ProviderConfig]:
        return list(self.configs)


class _Registry:
    def get_by_id(self, provider_id: int) -> _Provider | None:
        return (
            _Provider()
            if any(config.id == provider_id for config in _ProviderRepository().configs)
            else None
        )


class _PreparedSync:
    def __init__(
        self,
        configs: dict[int, ProviderConfig],
        failures: set[str],
        values: dict[str, float] | None = None,
    ) -> None:
        self.configs = configs
        self.failures = failures
        self.values = values or {}
        self.commits: list[tuple[PreparedMacroSync, object, PreparedMacroSync | None]] = []
        self.blocks: list[dict[str, object]] = []
        self.exhaustions: list[dict[str, object]] = []
        self.execute_calls = 0

    def prepare(self, request: SyncMacroRequest) -> PreparedMacroSync:
        config = self.configs[request.provider_id]
        if config.name in self.failures:
            raise RuntimeError(f"{config.name} unavailable")
        return PreparedMacroSync(
            config=config,
            provider_name=config.name,
            indicator_code=request.indicator_code,
            request_params={"indicator_code": request.indicator_code},
            facts=(_fact(config.name, self.values.get(config.name, 2.1)),),
            started_at=NOW,
        )

    def commit(
        self,
        prepared: PreparedMacroSync,
        *,
        failover_decision: object = None,
        verification: PreparedMacroSync | None = None,
    ) -> SyncResult:
        self.commits.append((prepared, failover_decision, verification))
        return SyncResult("macro", prepared.provider_name, len(prepared.facts), "success")

    def block_failover(
        self,
        prepared: PreparedMacroSync,
        *,
        from_provider: str,
        tolerance: float,
        observed_deviation: float | None,
        reason_code: str,
        error_class: str,
        verification: PreparedMacroSync | None = None,
    ) -> None:
        self.blocks.append(
            {
                "prepared": prepared,
                "from_provider": from_provider,
                "tolerance": tolerance,
                "observed_deviation": observed_deviation,
                "reason_code": reason_code,
                "error_class": error_class,
                "verification": verification,
            }
        )

    def exhaust_failover(
        self,
        *,
        indicator_code: str,
        start: date,
        end: date,
        from_provider: str,
        attempted_provider_names: tuple[str, ...],
        tolerance: float,
    ) -> None:
        self.exhaustions.append(
            {
                "indicator_code": indicator_code,
                "start": start,
                "end": end,
                "from_provider": from_provider,
                "attempted_provider_names": attempted_provider_names,
                "tolerance": tolerance,
            }
        )

    def execute(self, _request: SyncMacroRequest) -> SyncResult:
        self.execute_calls += 1
        return SyncResult("macro", "primary", 1, "success")


class _PolicyProvider:
    def __init__(self, policy: MacroFailoverPolicy) -> None:
        self.policy = policy

    def get_policy(self) -> MacroFailoverPolicy:
        return self.policy


def _batch(
    sync: _PreparedSync,
    policy: MacroFailoverPolicy,
    *,
    configs: list[ProviderConfig] | None = None,
) -> SyncMacroBatchUseCase:
    return SyncMacroBatchUseCase(
        provider_repo=_ProviderRepository(configs),
        provider_registry=_Registry(),
        sync_use_case=sync,
        failover_policy_provider=_PolicyProvider(policy),
    )


def _request(source: str | None = None) -> SyncMacroBatchRequest:
    return SyncMacroBatchRequest(
        indicator_codes=["CN_CPI"],
        start=date(2026, 8, 1),
        end=date(2026, 8, 27),
        source=source,
    )


def test_primary_failure_commits_verified_fallback_with_exact_decision() -> None:
    configs = {
        1: _config(1, "primary", 1),
        2: _config(2, "fallback-a", 2),
        3: _config(3, "verifier", 3),
    }
    sync = _PreparedSync(configs, {"primary"})

    result = _batch(sync, MacroFailoverPolicy(enabled=True, tolerance=0.01)).execute(_request())

    assert result.stored_count == 1
    assert len(sync.commits) == 1
    _, decision, verification = sync.commits[0]
    assert decision.from_provider == "primary"
    assert decision.to_provider == "fallback-a"
    assert decision.verification_provider == "verifier"
    assert decision.observed_deviation == 0.0
    assert verification is not None


def test_single_fallback_without_independent_verification_blocks_without_commit() -> None:
    sync = _PreparedSync(
        {
            1: _config(1, "primary", 1),
            2: _config(2, "fallback-a", 2),
            3: _config(3, "verifier", 3),
        },
        {"primary", "verifier"},
    )

    _batch(sync, MacroFailoverPolicy(enabled=True, tolerance=0.01)).execute(_request())

    assert sync.commits == []
    assert sync.blocks[0]["reason_code"] == "failover_consistency_evidence_missing"
    assert sync.blocks[0]["observed_deviation"] is None
    assert sync.exhaustions == []


def test_all_provider_preparations_failed_records_exhaustion_before_batch_error() -> None:
    sync = _PreparedSync(
        {
            1: _config(1, "primary", 1),
            2: _config(2, "fallback-a", 2),
            3: _config(3, "verifier", 3),
        },
        {"primary", "fallback-a", "verifier"},
    )

    result = _batch(sync, MacroFailoverPolicy(enabled=True, tolerance=0.01)).execute(_request())

    assert result.stored_count == 0
    assert len(result.errors) == 1
    assert sync.blocks == []
    assert sync.exhaustions == [
        {
            "indicator_code": "CN_CPI",
            "start": date(2026, 8, 1),
            "end": date(2026, 8, 27),
            "from_provider": "primary",
            "attempted_provider_names": ("primary", "fallback-a", "verifier"),
            "tolerance": 0.01,
        }
    ]


def test_empty_results_from_every_provider_record_exhaustion() -> None:
    sync = _PreparedSync(
        {
            1: _config(1, "primary", 1),
            2: _config(2, "fallback-a", 2),
            3: _config(3, "verifier", 3),
        },
        set(),
    )
    sync.values = {"primary": 2.1, "fallback-a": 2.1, "verifier": 2.1}
    original_prepare = sync.prepare

    def prepare_empty(request: SyncMacroRequest) -> PreparedMacroSync:
        prepared = original_prepare(request)
        return PreparedMacroSync(
            config=prepared.config,
            provider_name=prepared.provider_name,
            indicator_code=prepared.indicator_code,
            request_params=prepared.request_params,
            facts=(),
            started_at=prepared.started_at,
        )

    sync.prepare = prepare_empty  # type: ignore[method-assign]

    result = _batch(sync, MacroFailoverPolicy(enabled=True, tolerance=0.01)).execute(_request())

    assert result.stored_count == 0
    assert len(result.errors) == 1
    assert len(sync.commits) == 3
    assert len(sync.exhaustions) == 1
    assert sync.exhaustions[0]["attempted_provider_names"] == (
        "primary",
        "fallback-a",
        "verifier",
    )


def test_no_active_provider_records_exhaustion_for_each_requested_indicator() -> None:
    sync = _PreparedSync({}, set())
    request = SyncMacroBatchRequest(
        indicator_codes=["CN_CPI", "CN_PPI"],
        start=date(2026, 8, 1),
        end=date(2026, 8, 27),
    )

    try:
        _batch(
            sync,
            MacroFailoverPolicy(enabled=True, tolerance=0.01),
            configs=[],
        ).execute(request)
    except ValueError as error:
        assert str(error) == "No active macro provider configured"
    else:
        raise AssertionError("missing provider configuration must fail closed")

    assert [item["indicator_code"] for item in sync.exhaustions] == ["CN_CPI", "CN_PPI"]
    assert all(
        item["from_provider"] == "macro-provider-policy" and item["attempted_provider_names"] == ()
        for item in sync.exhaustions
    )


def test_fallback_disagreement_above_tolerance_blocks_without_commit() -> None:
    sync = _PreparedSync(
        {
            1: _config(1, "primary", 1),
            2: _config(2, "fallback-a", 2),
            3: _config(3, "verifier", 3),
        },
        {"primary"},
        {"fallback-a": 2.1, "verifier": 2.5},
    )

    _batch(sync, MacroFailoverPolicy(enabled=True, tolerance=0.01)).execute(_request())

    assert sync.commits == []
    assert sync.blocks[0]["reason_code"] == "failover_consistency_rejected"


def test_disabled_policy_preserves_legacy_selected_provider_execute() -> None:
    sync = _PreparedSync({1: _config(1, "primary", 1)}, {"primary"})

    _batch(sync, MacroFailoverPolicy(enabled=False, tolerance=0.01)).execute(_request())

    assert sync.execute_calls == 1
    assert sync.commits == []


def test_explicit_source_preserves_requested_provider_without_automatic_fallback() -> None:
    sync = _PreparedSync({1: _config(1, "primary", 1)}, {"primary"})

    _batch(sync, MacroFailoverPolicy(enabled=True, tolerance=0.01)).execute(_request("primary"))

    assert sync.execute_calls == 1
    assert sync.commits == []
