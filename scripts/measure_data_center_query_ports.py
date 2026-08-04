"""Measure Data Center public query ports with real Django query capture.

This module deliberately keeps measurements separate from governance.  It does
not invent or persist query budgets; callers may pass an explicit
``QueryBudget`` when they already have an approved contract.  Without one,
the output is observational evidence only.

The command is safe to run against a local SQLite or temporary PostgreSQL
database.  Every sample captures Django database queries and wall-clock
latency independently, then emits a JSON report suitable for attaching to a
review.  Raw SQL is intentionally omitted from the report so credentials or
provider payloads cannot accidentally become evidence artifacts.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import statistics
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

# ``python scripts/<name>.py`` places ``scripts/`` first on ``sys.path``;
# insert the repository root so the application package is importable both as
# a module and as a direct CLI.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.data_center.domain.reconciliation import QueryBudget, QueryBudgetResult


class QueryPortCall(Protocol):
    """Callable shape used by the measurement harness."""

    def __call__(self) -> object: ...


@dataclass(frozen=True)
class QueryPortSpec:
    """One public port invocation and its audit labels."""

    domain: str
    dataset_key: str
    port: str
    call: QueryPortCall | None
    arguments: Mapping[str, object]


@dataclass(frozen=True)
class QuerySample:
    """One isolated query-count/latency observation."""

    sample: int
    query_count: int
    elapsed_ms: float
    result_rows: int | None


@dataclass(frozen=True)
class QueryPortMeasurement:
    """Repeated-sample evidence for one query port.

    ``query_count`` is the maximum count across measured samples.  A maximum
    is intentionally conservative for N+1 detection; the full per-sample
    counts remain in ``samples`` for auditability.  ``p95_ms`` uses the
    inclusive linear percentile method and is ``None`` when no sample ran.
    """

    domain: str
    dataset_key: str
    port: str
    arguments: Mapping[str, object]
    status: str
    requested_samples: int
    warmup_samples: int
    samples: tuple[QuerySample, ...]
    query_count: int | None
    p95_ms: float | None
    error_type: str | None = None
    error_message: str | None = None
    budget_evaluation: Mapping[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe evidence without raw SQL or return payloads."""

        payload = asdict(self)
        payload["samples"] = [asdict(sample) for sample in self.samples]
        if self.budget_evaluation is not None:
            payload["budget_evaluation"] = dict(self.budget_evaluation)
        return cast(dict[str, object], payload)


def _validate_sample_count(value: int, *, name: str) -> int:
    if isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _percentile_95(values: Sequence[float]) -> float | None:
    """Return the inclusive linear P95, or ``None`` for an empty sequence."""

    if not values:
        return None
    if len(values) == 1:
        return round(float(values[0]), 6)
    # statistics.quantiles(..., inclusive) is deterministic and avoids a
    # third-party dependency in a diagnostic tool.
    return round(float(statistics.quantiles(values, n=100, method="inclusive")[94]), 6)


def _result_rows(value: object) -> int | None:
    """Extract a bounded row count without forcing another database query."""

    if isinstance(value, Mapping):
        rows = value.get("rows")
        # Only count concrete containers.  Calling ``len(QuerySet)`` would
        # evaluate it after CaptureQueriesContext has closed and hide a query
        # from the measured count.
        return len(rows) if isinstance(rows, (list, tuple)) else None
    return len(value) if isinstance(value, (list, tuple)) else None


def _budget_payload(result: QueryBudgetResult) -> dict[str, object]:
    """Serialize the existing QueryBudgetResult for JSON evidence."""

    return {
        "budget_key": result.budget_key,
        "query_count": result.query_count,
        "p95_ms": result.p95_ms,
        "passed": result.passed,
        "violations": list(result.violations),
    }


def measure_query_port(
    spec: QueryPortSpec,
    *,
    samples: int = 5,
    warmup: int = 1,
    budget: QueryBudget | None = None,
    connection_alias: str = "default",
) -> QueryPortMeasurement:
    """Measure ``spec`` with Django's real ``CaptureQueriesContext``.

    A missing callable is represented as ``unmeasured`` instead of being
    treated as zero queries.  Invocation errors are represented as ``error``
    with no fabricated percentile.  This distinction prevents an unavailable
    or incompatible public port from producing false green evidence.
    """

    requested_samples = _validate_sample_count(samples, name="samples")
    warmup_samples = _validate_sample_count(warmup, name="warmup")
    if requested_samples == 0:
        raise ValueError("samples must be greater than zero")
    if not spec.domain.strip() or not spec.dataset_key.strip() or not spec.port.strip():
        raise ValueError("query port labels must be non-empty")
    if spec.call is None:
        return QueryPortMeasurement(
            domain=spec.domain,
            dataset_key=spec.dataset_key,
            port=spec.port,
            arguments=dict(spec.arguments),
            status="unmeasured",
            requested_samples=requested_samples,
            warmup_samples=warmup_samples,
            samples=(),
            query_count=None,
            p95_ms=None,
            error_type="public_port_unavailable",
            error_message="No callable public-port adapter was supplied",
        )

    # Keep Django imports lazy so the pure percentile/serialization helpers
    # remain importable by static checks without configuring settings first.
    from django.db import connections
    from django.test.utils import CaptureQueriesContext

    connection = connections[connection_alias]
    call = spec.call
    observations: list[QuerySample] = []

    try:
        for _ in range(warmup_samples):
            with CaptureQueriesContext(connection):
                call()
        for sample_index in range(1, requested_samples + 1):
            started_ns = time.perf_counter_ns()
            with CaptureQueriesContext(connection) as queries:
                result = call()
            elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
            observations.append(
                QuerySample(
                    sample=sample_index,
                    query_count=len(queries),
                    elapsed_ms=round(elapsed_ms, 6),
                    result_rows=_result_rows(result),
                )
            )
    except Exception as exc:  # pragma: no cover - exercised by CLI failures
        return QueryPortMeasurement(
            domain=spec.domain,
            dataset_key=spec.dataset_key,
            port=spec.port,
            arguments=dict(spec.arguments),
            status="error",
            requested_samples=requested_samples,
            warmup_samples=warmup_samples,
            samples=tuple(observations),
            query_count=None,
            p95_ms=None,
            error_type=type(exc).__name__,
            error_message=str(exc)[:500],
        )

    query_count = max(sample.query_count for sample in observations)
    p95_ms = _percentile_95([sample.elapsed_ms for sample in observations])
    budget_evaluation: Mapping[str, object] | None = None
    if budget is not None:
        # Importing the application facade here keeps this script's normal
        # import path independent from Django settings while reusing the
        # canonical QueryBudget contract when explicitly requested.
        from apps.data_center.application.reconciliation import check_query_budget

        budget_evaluation = _budget_payload(
            check_query_budget(budget, query_count=query_count, p95_ms=p95_ms)
        )
    return QueryPortMeasurement(
        domain=spec.domain,
        dataset_key=spec.dataset_key,
        port=spec.port,
        arguments=dict(spec.arguments),
        status="measured",
        requested_samples=requested_samples,
        warmup_samples=warmup_samples,
        samples=tuple(observations),
        query_count=query_count,
        p95_ms=p95_ms,
        budget_evaluation=budget_evaluation,
    )


def _call_public(function_name: str, *args: object, **kwargs: object) -> object:
    """Resolve one Public Port lazily after Django has been configured."""

    public = importlib.import_module("apps.data_center.application.public")
    function = getattr(public, function_name, None)
    if not callable(function):
        raise AttributeError(f"Public Port is not callable: {function_name}")
    return function(*args, **kwargs)


def build_default_port_specs(
    *,
    asset_code: str = "600000.SH",
    fund_code: str = "000001",
    indicator_code: str = "CN_PMI_MANUFACTURING",
    sector_code: str = "BK0428",
) -> tuple[QueryPortSpec, ...]:
    """Build bounded D0-D6 public-port calls using caller-visible sample keys."""

    return (
        QueryPortSpec(
            domain="D0",
            dataset_key="asset.master",
            port="apps.data_center.application.public.list_active_stock_codes",
            call=lambda: _call_public("list_active_stock_codes"),
            arguments={},
        ),
        QueryPortSpec(
            domain="D1",
            dataset_key="equity.price.bar",
            port="apps.data_center.application.public.get_published_price_bar_series",
            call=lambda: _call_public("get_published_price_bar_series", asset_code, limit=1),
            arguments={"asset_code": asset_code, "limit": 1},
        ),
        QueryPortSpec(
            domain="D1",
            dataset_key="equity.quote.snapshot",
            port="apps.data_center.application.public.get_published_quote_payloads",
            call=lambda: _call_public("get_published_quote_payloads", [asset_code]),
            arguments={"asset_codes": [asset_code]},
        ),
        QueryPortSpec(
            domain="D2",
            dataset_key="fund.nav",
            port="apps.data_center.application.public.get_published_fund_nav_series",
            call=lambda: _call_public("get_published_fund_nav_series", fund_code, limit=1),
            arguments={"fund_code": fund_code, "limit": 1},
        ),
        QueryPortSpec(
            domain="D3",
            dataset_key="macro.fact",
            port="apps.data_center.application.public.get_published_macro_fact_series",
            call=lambda: _call_public("get_published_macro_fact_series", indicator_code, limit=1),
            arguments={"indicator_code": indicator_code, "limit": 1},
        ),
        QueryPortSpec(
            domain="D4",
            dataset_key="equity.financial.fact",
            port="apps.data_center.application.public.get_published_financial_facts",
            call=lambda: _call_public("get_published_financial_facts", asset_code, limit=1),
            arguments={"asset_code": asset_code, "limit": 1},
        ),
        QueryPortSpec(
            domain="D5",
            dataset_key="equity.valuation.fact",
            port="apps.data_center.application.public.get_published_valuation_facts",
            call=lambda: _call_public("get_published_valuation_facts", asset_code, limit=1),
            arguments={"asset_code": asset_code, "limit": 1},
        ),
        QueryPortSpec(
            domain="D6",
            dataset_key="sector.membership",
            port="apps.data_center.application.public.get_published_sector_memberships",
            call=lambda: _call_public("get_published_sector_memberships", sector_code),
            arguments={"sector_code": sector_code},
        ),
    )


def build_report(
    *,
    specs: Sequence[QueryPortSpec],
    samples: int,
    warmup: int,
    settings_module: str,
    connection_alias: str = "default",
) -> dict[str, object]:
    """Measure specs and return an auditable, non-governance report."""

    measurements = [
        measure_query_port(
            spec,
            samples=samples,
            warmup=warmup,
            connection_alias=connection_alias,
        )
        for spec in specs
    ]
    from django.db import connections

    connection = connections[connection_alias]
    return {
        "schema_version": "data-center-query-measurement.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "settings_module": settings_module,
        "connection_alias": connection_alias,
        "database_vendor": connection.vendor,
        "requested_samples": samples,
        "warmup_samples": warmup,
        "query_count_semantics": "maximum across measured samples",
        "p95_method": "statistics.quantiles(method='inclusive', n=100)[94]",
        "budget_source": "caller supplied only; no governance budgets loaded",
        "ports": [measurement.to_dict() for measurement in measurements],
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--settings",
        default=os.environ.get("DJANGO_SETTINGS_MODULE", "core.settings.development_sqlite"),
    )
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--asset-code", default="600000.SH")
    parser.add_argument("--fund-code", default="000001")
    parser.add_argument("--indicator-code", default="CN_PMI_MANUFACTURING")
    parser.add_argument("--sector-code", default="BK0428")
    parser.add_argument("--connection-alias", default="default")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON evidence path")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run local measurements and print JSON evidence."""

    args = _parse_args(argv)
    os.environ["DJANGO_SETTINGS_MODULE"] = args.settings
    import django

    django.setup()
    report = build_report(
        specs=build_default_port_specs(
            asset_code=args.asset_code,
            fund_code=args.fund_code,
            indicator_code=args.indicator_code,
            sector_code=args.sector_code,
        ),
        samples=args.samples,
        warmup=args.warmup,
        settings_module=args.settings,
        connection_alias=args.connection_alias,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
