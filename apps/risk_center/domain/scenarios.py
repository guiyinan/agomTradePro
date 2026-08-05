"""Pure domain contracts and calculations for governed stress scenarios."""

from __future__ import annotations

import hashlib
import json
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import cast


class ScenarioType(str, Enum):
    """Stable scenario calculation types."""

    HISTORICAL_WINDOW = "historical_window"
    ROLLING_EXTREME = "rolling_extreme"
    PARAMETRIC_SHOCK = "parametric_shock"
    MACRO_PATH = "macro_path"

    @classmethod
    def for_parameters(cls, parameters: object) -> ScenarioType:
        """Return the type owned by one validated parameter object."""

        if isinstance(parameters, HistoricalWindowParameters):
            return cls.HISTORICAL_WINDOW
        if isinstance(parameters, RollingExtremeParameters):
            return cls.ROLLING_EXTREME
        if isinstance(parameters, ParametricShockParameters):
            return cls.PARAMETRIC_SHOCK
        if isinstance(parameters, MacroPathParameters):
            return cls.MACRO_PATH
        raise ValueError("unsupported scenario parameters")


class ScenarioRevisionStatus(str, Enum):
    """Immutable revision lifecycle labels."""

    CANDIDATE = "candidate"
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class ScenarioDefinitionStatus(str, Enum):
    """Definition availability states."""

    ACTIVE = "active"
    RETIRED = "retired"


class ScenarioSourceType(str, Enum):
    """Origin of an immutable scenario revision."""

    HUMAN = "human"
    AI_MCP = "ai_mcp"
    SEED = "seed"
    DETECTOR = "detector"
    LEGACY_CODE_MIGRATION = "legacy_code_migration"


class RollingMetric(str, Enum):
    """Supported rolling-window selection metrics."""

    CUMULATIVE_RETURN = "cumulative_return"
    REALIZED_VOLATILITY = "realized_volatility"


class RollingDirection(str, Enum):
    """Supported rolling-window ordering directions."""

    MINIMUM = "minimum"
    MAXIMUM = "maximum"


class ShockUnit(str, Enum):
    """Finite shock units; arbitrary expressions are intentionally absent."""

    PERCENT = "percent"
    BASIS_POINTS = "basis_points"
    ABSOLUTE = "absolute"
    CORRELATION = "correlation"


class ProbabilitySource(str, Enum):
    """Keep subjective probabilities separate from model inference."""

    SUBJECTIVE = "subjective"
    MODEL_INFERRED = "model_inferred"


def _require_nonblank(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} is required")


def _require_aware(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite decimal")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be a finite decimal")
    return parsed


def _parse_date(value: object, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _strict_mapping(
    value: object,
    *,
    context: str,
    required: set[str],
    optional: set[str] | None = None,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    normalized = cast(Mapping[str, object], value)
    keys = {str(key) for key in normalized}
    missing = required - keys
    if missing:
        raise ValueError(f"{context} missing fields: {', '.join(sorted(missing))}")
    unknown = keys - required - (optional or set())
    if unknown:
        raise ValueError(f"{context} unknown fields: {', '.join(sorted(unknown))}")
    return normalized


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{field_name} must be an array")
    return cast(Sequence[object], value)


@dataclass(frozen=True)
class HistoricalWindowParameters:
    """Parameters for replaying a published historical window."""

    start_date: date
    end_date: date
    source: str
    event_description: str

    def __post_init__(self) -> None:
        _require_nonblank("historical source", self.source)
        _require_nonblank("historical event_description", self.event_description)
        if self.end_date < self.start_date:
            raise ValueError("historical end_date cannot precede start_date")


@dataclass(frozen=True)
class RollingExtremeParameters:
    """Parameters for selecting a recent extreme rolling window."""

    lookback_days: int
    window_days: int
    selection_indicator: str
    selection_metric: RollingMetric
    direction: RollingDirection
    recalculation_frequency: str

    def __post_init__(self) -> None:
        if isinstance(self.lookback_days, bool) or self.lookback_days <= 0:
            raise ValueError("rolling lookback_days must be positive")
        if isinstance(self.window_days, bool) or self.window_days <= 0:
            raise ValueError("rolling window_days must be positive")
        if self.window_days > self.lookback_days:
            raise ValueError("rolling window_days cannot exceed lookback_days")
        _require_nonblank("rolling selection_indicator", self.selection_indicator)
        _require_nonblank("rolling recalculation_frequency", self.recalculation_frequency)
        if self.recalculation_frequency not in {"daily", "weekly", "monthly"}:
            raise ValueError("rolling recalculation_frequency is unsupported")


@dataclass(frozen=True)
class ParametricShock:
    """One finite, typed shock applied to a portfolio exposure."""

    target_kind: str
    target: str
    shock_kind: str
    magnitude: Decimal
    unit: ShockUnit
    horizon_days: int

    def __post_init__(self) -> None:
        for field_name, value in (
            ("shock target_kind", self.target_kind),
            ("shock target", self.target),
            ("shock shock_kind", self.shock_kind),
        ):
            _require_nonblank(field_name, value)
        if self.target_kind not in {"asset", "asset_class", "factor"}:
            raise ValueError("shock target_kind is unsupported")
        if not self.magnitude.is_finite():
            raise ValueError("shock magnitude must be finite")
        if self.horizon_days <= 0:
            raise ValueError("shock horizon_days must be positive")
        if self.unit is ShockUnit.CORRELATION and not Decimal("-1") <= self.magnitude <= Decimal(
            "1"
        ):
            raise ValueError("correlation shock magnitude must be in [-1, 1]")
        if self.unit is ShockUnit.PERCENT and self.shock_kind == "return" and self.magnitude < -1:
            raise ValueError("return shock cannot be below -100%")


@dataclass(frozen=True)
class ParametricShockParameters:
    """A finite list of explicit portfolio shocks."""

    shocks: tuple[ParametricShock, ...]
    correlation_assumption: str

    def __post_init__(self) -> None:
        if not self.shocks:
            raise ValueError("parametric scenario requires at least one shock")
        _require_nonblank("correlation_assumption", self.correlation_assumption)
        identities = {(item.target_kind, item.target, item.shock_kind) for item in self.shocks}
        if len(identities) != len(self.shocks):
            raise ValueError("parametric scenario contains duplicate shocks")


@dataclass(frozen=True)
class MacroPathNode:
    """One dated value in a bounded macro driver path."""

    path_date: date
    value: Decimal

    def __post_init__(self) -> None:
        if not self.value.is_finite():
            raise ValueError("macro path node value must be finite")


@dataclass(frozen=True)
class MacroDriverPath:
    """A discrete macro state backed by an observable proxy and path."""

    driver_key: str
    state: str
    proxy_indicator: str
    unit: str
    nodes: tuple[MacroPathNode, ...]

    def __post_init__(self) -> None:
        for field_name, value in (
            ("macro driver_key", self.driver_key),
            ("macro state", self.state),
            ("macro proxy_indicator", self.proxy_indicator),
            ("macro unit", self.unit),
        ):
            _require_nonblank(field_name, value)
        if not self.nodes:
            raise ValueError("macro driver requires path nodes")
        dates = [item.path_date for item in self.nodes]
        if dates != sorted(dates) or len(dates) != len(set(dates)):
            raise ValueError("macro path nodes must use unique ascending dates")


@dataclass(frozen=True)
class AssetImpactAssumption:
    """Explicit, explainable portfolio impact for a macro scenario."""

    target_kind: str
    target: str
    cumulative_return: Decimal
    rationale: str

    def __post_init__(self) -> None:
        if self.target_kind not in {"asset", "asset_class", "factor"}:
            raise ValueError("macro impact target_kind is unsupported")
        _require_nonblank("macro impact target", self.target)
        _require_nonblank("macro impact rationale", self.rationale)
        if not self.cumulative_return.is_finite() or self.cumulative_return < -1:
            raise ValueError("macro impact cumulative_return must be finite and at least -1")


@dataclass(frozen=True)
class MacroPathParameters:
    """Typed conditional macro path with explicit probability semantics."""

    drivers: tuple[MacroDriverPath, ...]
    probability: Decimal
    probability_source: ProbabilitySource
    asset_impacts: tuple[AssetImpactAssumption, ...]
    invalidation_conditions: tuple[str, ...]
    review_date: date

    def __post_init__(self) -> None:
        if not self.drivers:
            raise ValueError("macro scenario requires at least one driver")
        if len({item.driver_key for item in self.drivers}) != len(self.drivers):
            raise ValueError("macro scenario contains duplicate drivers")
        if not Decimal("0") <= self.probability <= Decimal("1"):
            raise ValueError("macro probability must be in [0, 1]")
        if not self.asset_impacts:
            raise ValueError("macro scenario requires asset impacts")
        if not self.invalidation_conditions or any(
            not item.strip() for item in self.invalidation_conditions
        ):
            raise ValueError("macro scenario requires invalidation conditions")


ScenarioParameters = (
    HistoricalWindowParameters
    | RollingExtremeParameters
    | ParametricShockParameters
    | MacroPathParameters
)


@dataclass(frozen=True)
class ScenarioDefinition:
    """Stable identity for a governed scenario across immutable revisions."""

    scenario_key: str
    name: str
    category: str
    owner: str
    status: ScenarioDefinitionStatus = ScenarioDefinitionStatus.ACTIVE
    description: str = ""
    legacy_aliases: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        for field_name, value in (
            ("scenario_key", self.scenario_key),
            ("scenario name", self.name),
            ("scenario category", self.category),
            ("scenario owner", self.owner),
        ):
            _require_nonblank(field_name, value)
        if any(not alias.strip() for alias in self.legacy_aliases):
            raise ValueError("legacy aliases cannot be blank")
        if len(self.legacy_aliases) != len(set(self.legacy_aliases)):
            raise ValueError("legacy aliases must be unique")
        _require_aware("ScenarioDefinition.created_at", self.created_at)


def _json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def stable_content_hash(payload: Mapping[str, object]) -> str:
    """Return the canonical SHA-256 digest for JSON-safe business content."""

    encoded = json.dumps(
        _json_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ScenarioRevision:
    """Immutable, typed content revision for one scenario definition."""

    revision_id: str
    scenario_key: str
    version: int
    status: ScenarioRevisionStatus
    scenario_type: ScenarioType
    parameters: ScenarioParameters
    assumptions: tuple[str, ...]
    source_type: ScenarioSourceType
    created_by: str
    change_reason: str
    based_on_version: int | None = None
    source_evidence: tuple[dict[str, object], ...] = ()
    effective_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    def __post_init__(self) -> None:
        for field_name, value in (
            ("revision_id", self.revision_id),
            ("scenario_key", self.scenario_key),
            ("created_by", self.created_by),
            ("change_reason", self.change_reason),
        ):
            _require_nonblank(field_name, value)
        if self.version < 1:
            raise ValueError("scenario revision version must be positive")
        if self.based_on_version is not None and not 0 < self.based_on_version < self.version:
            raise ValueError("based_on_version must be positive and below version")
        expected_type = ScenarioType.for_parameters(self.parameters)
        if self.scenario_type is not expected_type:
            raise ValueError("scenario_type does not match typed parameters")
        if any(not item.strip() for item in self.assumptions):
            raise ValueError("scenario assumptions cannot be blank")
        _require_aware("ScenarioRevision.created_at", self.created_at)
        if self.effective_at is not None:
            _require_aware("ScenarioRevision.effective_at", self.effective_at)
        expected_hash = calculate_scenario_revision_hash(self)
        if self.content_hash and self.content_hash != expected_hash:
            raise ValueError("scenario revision content_hash mismatch")
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_hash)


def calculate_scenario_revision_hash(revision: ScenarioRevision) -> str:
    """Seal only business content, excluding revision identity and workflow metadata."""

    return stable_content_hash(
        {
            "scenario_key": revision.scenario_key,
            "scenario_type": revision.scenario_type,
            "parameters": revision.parameters,
            "assumptions": revision.assumptions,
            "source_evidence": revision.source_evidence,
        }
    )


@dataclass(frozen=True)
class ScenarioSet:
    """Stable identity for a purpose-specific set of scenarios."""

    set_key: str
    name: str
    purpose: str
    owner: str
    applicable_asset_scope: tuple[str, ...] = ()
    status: ScenarioDefinitionStatus = ScenarioDefinitionStatus.ACTIVE

    def __post_init__(self) -> None:
        for field_name, value in (
            ("set_key", self.set_key),
            ("set name", self.name),
            ("set purpose", self.purpose),
            ("set owner", self.owner),
        ):
            _require_nonblank(field_name, value)


@dataclass(frozen=True)
class ScenarioSetMember:
    """One scenario revision and its explicitly sourced probability."""

    scenario_revision_id: str
    probability: Decimal
    probability_source: ProbabilitySource
    sort_order: int

    def __post_init__(self) -> None:
        _require_nonblank("scenario_revision_id", self.scenario_revision_id)
        if not Decimal("0") <= self.probability <= Decimal("1"):
            raise ValueError("scenario member probability must be in [0, 1]")
        if self.sort_order < 0:
            raise ValueError("scenario member sort_order cannot be negative")


@dataclass(frozen=True)
class ScenarioSetRevision:
    """Immutable probability-bearing revision of a scenario set."""

    revision_id: str
    set_key: str
    version: int
    status: ScenarioRevisionStatus
    members: tuple[ScenarioSetMember, ...]
    driver_axes: tuple[str, ...]
    created_by: str
    change_reason: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    content_hash: str = ""

    def __post_init__(self) -> None:
        for field_name, value in (
            ("set revision_id", self.revision_id),
            ("set_key", self.set_key),
            ("set created_by", self.created_by),
            ("set change_reason", self.change_reason),
        ):
            _require_nonblank(field_name, value)
        if self.version < 1 or not self.members:
            raise ValueError("scenario set revision requires version and members")
        member_ids = [item.scenario_revision_id for item in self.members]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("scenario set revision contains duplicate members")
        if sum((item.probability for item in self.members), Decimal("0")) != Decimal("1"):
            raise ValueError("scenario set member probabilities must sum to 1")
        if any(not axis.strip() for axis in self.driver_axes):
            raise ValueError("scenario set driver axes cannot be blank")
        _require_aware("ScenarioSetRevision.created_at", self.created_at)
        for field_name, value in (
            ("effective_from", self.effective_from),
            ("effective_to", self.effective_to),
        ):
            if value is not None:
                _require_aware(field_name, value)
        if self.effective_from and self.effective_to and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be after effective_from")
        expected_hash = stable_content_hash(
            {
                "set_key": self.set_key,
                "members": self.members,
                "driver_axes": self.driver_axes,
                "effective_from": self.effective_from,
                "effective_to": self.effective_to,
            }
        )
        if self.content_hash and self.content_hash != expected_hash:
            raise ValueError("scenario set content_hash mismatch")
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_hash)


@dataclass(frozen=True)
class ScenarioActivation:
    """Auditable pointer to the active set revision in one scope."""

    activation_id: str
    environment: str
    purpose: str
    scenario_set_revision_id: str
    activated_by: str
    reason: str
    activated_at: datetime
    previous_activation_id: str | None = None
    correlation_id: str = ""

    def __post_init__(self) -> None:
        for field_name, value in (
            ("activation_id", self.activation_id),
            ("environment", self.environment),
            ("purpose", self.purpose),
            ("scenario_set_revision_id", self.scenario_set_revision_id),
            ("activated_by", self.activated_by),
            ("activation reason", self.reason),
        ):
            _require_nonblank(field_name, value)
        _require_aware("activated_at", self.activated_at)


@dataclass(frozen=True)
class ScenarioRunEvidence:
    """Immutable inputs and output digest for one reproducible scenario run."""

    run_id: str
    scenario_revision_id: str
    portfolio_snapshot_id: str
    portfolio_snapshot_hash: str
    as_of_time: datetime
    data_evidence_ids: tuple[str, ...]
    result_hash: str
    allocation_policy_version: str
    code_version: str
    scenario_set_revision_id: str | None = None
    must_not_use_for_decision: bool = False
    blocked_reason: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        for field_name, value in (
            ("run_id", self.run_id),
            ("scenario_revision_id", self.scenario_revision_id),
            ("portfolio_snapshot_id", self.portfolio_snapshot_id),
            ("portfolio_snapshot_hash", self.portfolio_snapshot_hash),
            ("allocation_policy_version", self.allocation_policy_version),
            ("code_version", self.code_version),
        ):
            _require_nonblank(field_name, value)
        _require_aware("ScenarioRunEvidence.as_of_time", self.as_of_time)
        _require_aware("ScenarioRunEvidence.created_at", self.created_at)
        if self.must_not_use_for_decision:
            _require_nonblank("blocked_reason", self.blocked_reason)
        else:
            if not self.data_evidence_ids or any(
                not item.strip() for item in self.data_evidence_ids
            ):
                raise ValueError("decision-usable run requires data evidence")
            if len(self.result_hash) != 64:
                raise ValueError("decision-usable run requires a SHA-256 result_hash")


@dataclass(frozen=True)
class PortfolioExposure:
    """Minimal risk exposure consumed by pure scenario calculations."""

    asset_code: str
    weight: Decimal
    attributes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _require_nonblank("PortfolioExposure.asset_code", self.asset_code)
        if not self.weight.is_finite() or self.weight < 0 or self.weight > 1:
            raise ValueError("PortfolioExposure.weight must be in [0, 1]")


@dataclass(frozen=True)
class HistoricalReturnPoint:
    """One source-observed daily return."""

    observed_on: date
    value: Decimal

    def __post_init__(self) -> None:
        if not self.value.is_finite() or self.value < -1:
            raise ValueError("historical return must be finite and at least -1")


@dataclass(frozen=True)
class AssetReturnSeries:
    """Ordered return observations for one portfolio asset."""

    asset_code: str
    points: tuple[HistoricalReturnPoint, ...]

    def __post_init__(self) -> None:
        _require_nonblank("AssetReturnSeries.asset_code", self.asset_code)
        dates = [item.observed_on for item in self.points]
        if dates != sorted(dates) or len(dates) != len(set(dates)):
            raise ValueError("return series dates must be unique and ascending")


@dataclass(frozen=True)
class ScenarioImpact:
    """Deterministic scenario result before persistence and explanation."""

    scenario_revision_id: str
    initial_value: Decimal
    final_value: Decimal
    total_return: Decimal
    max_drawdown: Decimal
    recovery_periods: int
    volatility: Decimal
    var_95: Decimal
    var_99: Decimal
    period_start: date | None
    period_end: date | None
    result_hash: str


def scenario_parameters_to_dict(parameters: ScenarioParameters) -> dict[str, object]:
    """Serialize validated scenario parameters to a stable JSON projection."""

    result = _json_value(parameters)
    if not isinstance(result, dict):
        raise ValueError("scenario parameters did not serialize to an object")
    return cast(dict[str, object], result)


def scenario_parameters_from_mapping(
    scenario_type: ScenarioType,
    payload: Mapping[str, object],
) -> ScenarioParameters:
    """Parse persistence JSON through a strict type-specific whitelist."""

    if scenario_type is ScenarioType.HISTORICAL_WINDOW:
        data = _strict_mapping(
            payload,
            context="historical parameters",
            required={"start_date", "end_date", "source", "event_description"},
        )
        return HistoricalWindowParameters(
            start_date=_parse_date(data["start_date"], "start_date"),
            end_date=_parse_date(data["end_date"], "end_date"),
            source=str(data["source"]),
            event_description=str(data["event_description"]),
        )
    if scenario_type is ScenarioType.ROLLING_EXTREME:
        data = _strict_mapping(
            payload,
            context="rolling parameters",
            required={
                "lookback_days",
                "window_days",
                "selection_indicator",
                "selection_metric",
                "direction",
                "recalculation_frequency",
            },
        )
        return RollingExtremeParameters(
            lookback_days=int(str(data["lookback_days"])),
            window_days=int(str(data["window_days"])),
            selection_indicator=str(data["selection_indicator"]),
            selection_metric=RollingMetric(str(data["selection_metric"])),
            direction=RollingDirection(str(data["direction"])),
            recalculation_frequency=str(data["recalculation_frequency"]),
        )
    if scenario_type is ScenarioType.PARAMETRIC_SHOCK:
        data = _strict_mapping(
            payload,
            context="parametric parameters",
            required={"shocks", "correlation_assumption"},
        )
        shocks: list[ParametricShock] = []
        for raw_shock in _sequence(data["shocks"], "shocks"):
            shock = _strict_mapping(
                raw_shock,
                context="parametric shock",
                required={
                    "target_kind",
                    "target",
                    "shock_kind",
                    "magnitude",
                    "unit",
                    "horizon_days",
                },
            )
            shocks.append(
                ParametricShock(
                    target_kind=str(shock["target_kind"]),
                    target=str(shock["target"]),
                    shock_kind=str(shock["shock_kind"]),
                    magnitude=_decimal(shock["magnitude"], "shock magnitude"),
                    unit=ShockUnit(str(shock["unit"])),
                    horizon_days=int(str(shock["horizon_days"])),
                )
            )
        return ParametricShockParameters(
            shocks=tuple(shocks),
            correlation_assumption=str(data["correlation_assumption"]),
        )
    data = _strict_mapping(
        payload,
        context="macro parameters",
        required={
            "drivers",
            "probability",
            "probability_source",
            "asset_impacts",
            "invalidation_conditions",
            "review_date",
        },
    )
    drivers: list[MacroDriverPath] = []
    for raw_driver in _sequence(data["drivers"], "drivers"):
        driver = _strict_mapping(
            raw_driver,
            context="macro driver",
            required={"driver_key", "state", "proxy_indicator", "unit", "nodes"},
        )
        nodes: list[MacroPathNode] = []
        for raw_node in _sequence(driver["nodes"], "macro nodes"):
            node = _strict_mapping(
                raw_node,
                context="macro node",
                required={"path_date", "value"},
            )
            nodes.append(
                MacroPathNode(
                    path_date=_parse_date(node["path_date"], "path_date"),
                    value=_decimal(node["value"], "macro node value"),
                )
            )
        drivers.append(
            MacroDriverPath(
                driver_key=str(driver["driver_key"]),
                state=str(driver["state"]),
                proxy_indicator=str(driver["proxy_indicator"]),
                unit=str(driver["unit"]),
                nodes=tuple(nodes),
            )
        )
    impacts: list[AssetImpactAssumption] = []
    for raw_impact in _sequence(data["asset_impacts"], "asset_impacts"):
        impact = _strict_mapping(
            raw_impact,
            context="macro asset impact",
            required={"target_kind", "target", "cumulative_return", "rationale"},
        )
        impacts.append(
            AssetImpactAssumption(
                target_kind=str(impact["target_kind"]),
                target=str(impact["target"]),
                cumulative_return=_decimal(impact["cumulative_return"], "macro cumulative_return"),
                rationale=str(impact["rationale"]),
            )
        )
    return MacroPathParameters(
        drivers=tuple(drivers),
        probability=_decimal(data["probability"], "macro probability"),
        probability_source=ProbabilitySource(str(data["probability_source"])),
        asset_impacts=tuple(impacts),
        invalidation_conditions=tuple(
            str(item) for item in _sequence(data["invalidation_conditions"], "invalidation")
        ),
        review_date=_parse_date(data["review_date"], "review_date"),
    )


def _validate_exposures(exposures: tuple[PortfolioExposure, ...]) -> None:
    if not exposures:
        raise ValueError("scenario calculation requires portfolio exposures")
    codes = [item.asset_code for item in exposures]
    if len(codes) != len(set(codes)):
        raise ValueError("portfolio exposures contain duplicate assets")
    if sum((item.weight for item in exposures), Decimal("0")) > 1:
        raise ValueError("portfolio exposure weights cannot exceed 1")


def _aggregate_returns(
    exposures: tuple[PortfolioExposure, ...],
    series: tuple[AssetReturnSeries, ...],
    *,
    start: date | None = None,
    end: date | None = None,
) -> list[tuple[date, Decimal]]:
    series_by_code = {item.asset_code: item for item in series}
    if any(item.asset_code not in series_by_code for item in exposures):
        raise ValueError("historical market data is missing a portfolio asset")
    maps: dict[str, dict[date, Decimal]] = {}
    common_dates: set[date] | None = None
    for exposure in exposures:
        points = {
            point.observed_on: point.value
            for point in series_by_code[exposure.asset_code].points
            if (start is None or point.observed_on >= start)
            and (end is None or point.observed_on <= end)
        }
        if not points:
            raise ValueError("historical market data has no observations in the requested window")
        maps[exposure.asset_code] = points
        common_dates = set(points) if common_dates is None else common_dates & set(points)
    if not common_dates:
        raise ValueError("historical market data has no common observation dates")
    return [
        (
            observed_on,
            sum(
                (
                    exposure.weight * maps[exposure.asset_code][observed_on]
                    for exposure in exposures
                ),
                Decimal("0"),
            ),
        )
        for observed_on in sorted(common_dates)
    ]


def _cumulative_return(returns: Sequence[Decimal]) -> Decimal:
    value = Decimal("1")
    for item in returns:
        value *= Decimal("1") + item
    return value - Decimal("1")


def _select_rolling_window(
    values: list[tuple[date, Decimal]], parameters: RollingExtremeParameters
) -> list[tuple[date, Decimal]]:
    bounded = values[-parameters.lookback_days :]
    if len(bounded) < parameters.window_days:
        raise ValueError("rolling scenario has insufficient observations")
    candidates = [
        bounded[index : index + parameters.window_days]
        for index in range(len(bounded) - parameters.window_days + 1)
    ]

    def metric(candidate: list[tuple[date, Decimal]]) -> Decimal:
        returns = [item[1] for item in candidate]
        if parameters.selection_metric is RollingMetric.CUMULATIVE_RETURN:
            return _cumulative_return(returns)
        return Decimal(str(statistics.pstdev(float(item) for item in returns)))

    return (min if parameters.direction is RollingDirection.MINIMUM else max)(
        candidates, key=metric
    )


def _matches(exposure: PortfolioExposure, target_kind: str, target: str) -> bool:
    if target_kind == "asset":
        return exposure.asset_code == target
    return dict(exposure.attributes).get(target_kind) == target


def _shock_return(shock: ParametricShock) -> Decimal:
    if shock.shock_kind not in {"return", "price", "spread_return"}:
        return Decimal("0")
    if shock.unit is ShockUnit.PERCENT:
        return shock.magnitude
    if shock.unit is ShockUnit.BASIS_POINTS:
        return shock.magnitude / Decimal("10000")
    if shock.unit is ShockUnit.ABSOLUTE:
        return shock.magnitude
    return Decimal("0")


def _impact_result(
    revision_id: str,
    initial_value: Decimal,
    dated_returns: list[tuple[date | None, Decimal]],
) -> ScenarioImpact:
    returns = [item[1] for item in dated_returns]
    total_return = _cumulative_return(returns)
    equity = [initial_value]
    for item in returns:
        equity.append(equity[-1] * (Decimal("1") + item))
    peak = equity[0]
    max_drawdown = Decimal("0")
    recovery = 0
    longest_recovery = 0
    for value in equity[1:]:
        if value > peak:
            peak = value
            recovery = 0
        else:
            drawdown = (peak - value) / peak if peak else Decimal("0")
            max_drawdown = max(max_drawdown, drawdown)
            recovery += 1
            longest_recovery = max(longest_recovery, recovery)
    volatility = (
        Decimal(str(statistics.stdev(float(item) for item in returns)))
        if len(returns) > 1
        else Decimal("0")
    )
    ordered = sorted(returns)

    def historical_var(confidence: Decimal) -> Decimal:
        index = int((Decimal("1") - confidence) * len(ordered))
        return ordered[min(index, len(ordered) - 1)]

    period_dates = [item[0] for item in dated_returns if item[0] is not None]
    payload: dict[str, object] = {
        "scenario_revision_id": revision_id,
        "initial_value": initial_value,
        "returns": tuple(returns),
        "final_value": equity[-1],
        "total_return": total_return,
        "period_start": period_dates[0] if period_dates else None,
        "period_end": period_dates[-1] if period_dates else None,
    }
    return ScenarioImpact(
        scenario_revision_id=revision_id,
        initial_value=initial_value,
        final_value=equity[-1],
        total_return=total_return,
        max_drawdown=max_drawdown,
        recovery_periods=longest_recovery,
        volatility=volatility,
        var_95=historical_var(Decimal("0.95")),
        var_99=historical_var(Decimal("0.99")),
        period_start=cast(date | None, payload["period_start"]),
        period_end=cast(date | None, payload["period_end"]),
        result_hash=stable_content_hash(payload),
    )


def evaluate_scenario(
    revision: ScenarioRevision,
    *,
    exposures: tuple[PortfolioExposure, ...],
    initial_value: Decimal,
    return_series: tuple[AssetReturnSeries, ...],
) -> ScenarioImpact:
    """Evaluate any supported scenario without I/O or external dependencies."""

    _validate_exposures(exposures)
    if not initial_value.is_finite() or initial_value <= 0:
        raise ValueError("scenario initial_value must be positive and finite")
    parameters = revision.parameters
    if isinstance(parameters, HistoricalWindowParameters):
        returns = _aggregate_returns(
            exposures,
            return_series,
            start=parameters.start_date,
            end=parameters.end_date,
        )
        return _impact_result(revision.revision_id, initial_value, list(returns))
    if isinstance(parameters, RollingExtremeParameters):
        returns = _aggregate_returns(exposures, return_series)
        selected = _select_rolling_window(returns, parameters)
        return _impact_result(revision.revision_id, initial_value, list(selected))
    if isinstance(parameters, ParametricShockParameters):
        total = sum(
            (
                exposure.weight
                * sum(
                    (
                        _shock_return(shock)
                        for shock in parameters.shocks
                        if _matches(exposure, shock.target_kind, shock.target)
                    ),
                    Decimal("0"),
                )
                for exposure in exposures
            ),
            Decimal("0"),
        )
        return _impact_result(revision.revision_id, initial_value, [(None, total)])
    total = sum(
        (
            exposure.weight
            * sum(
                (
                    impact.cumulative_return
                    for impact in parameters.asset_impacts
                    if _matches(exposure, impact.target_kind, impact.target)
                ),
                Decimal("0"),
            )
            for exposure in exposures
        ),
        Decimal("0"),
    )
    return _impact_result(revision.revision_id, initial_value, [(None, total)])


__all__ = [
    "AssetImpactAssumption",
    "AssetReturnSeries",
    "HistoricalReturnPoint",
    "HistoricalWindowParameters",
    "MacroDriverPath",
    "MacroPathNode",
    "MacroPathParameters",
    "ParametricShock",
    "ParametricShockParameters",
    "PortfolioExposure",
    "ProbabilitySource",
    "RollingDirection",
    "RollingExtremeParameters",
    "RollingMetric",
    "ScenarioActivation",
    "ScenarioDefinition",
    "ScenarioDefinitionStatus",
    "ScenarioImpact",
    "ScenarioRevision",
    "ScenarioRevisionStatus",
    "ScenarioRunEvidence",
    "ScenarioSet",
    "ScenarioSetMember",
    "ScenarioSetRevision",
    "ScenarioSourceType",
    "ScenarioType",
    "ShockUnit",
    "calculate_scenario_revision_hash",
    "evaluate_scenario",
    "scenario_parameters_from_mapping",
    "scenario_parameters_to_dict",
    "stable_content_hash",
]
