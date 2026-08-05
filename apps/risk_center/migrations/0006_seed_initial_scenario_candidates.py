"""Seed maintainable rolling, parametric, and macro scenario candidates."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, TypedDict, cast

from django.db import migrations

MIGRATION_REF = "risk_center.0006_seed_initial_scenario_candidates"
CREATED_BY = f"system:migration:{MIGRATION_REF}"
CREATED_AT = datetime(2026, 8, 4, tzinfo=UTC)
UUID_NAMESPACE = uuid.UUID("b29a713b-dfcb-4ae1-878e-11ded99a2b46")


class DriverSeedSpec(TypedDict):
    """Serializable seed shape for one observable macro driver."""

    driver_key: str
    state: str
    proxy_indicator: str
    unit: str
    start_value: str
    end_value: str


class ImpactSeedSpec(TypedDict):
    """Serializable seed shape for one explicit asset impact."""

    target_kind: str
    target: str
    cumulative_return: str
    rationale: str


class MacroScenarioSeedSpec(TypedDict):
    """Business content for one macro-path candidate."""

    scenario_key: str
    name: str
    description: str
    drivers: tuple[DriverSeedSpec, DriverSeedSpec]
    impacts: tuple[ImpactSeedSpec, ...]


class ScenarioSetSeedSpec(TypedDict):
    """Business content for one two-axis scenario set candidate."""

    set_key: str
    name: str
    purpose: str
    driver_axes: tuple[str, str]
    scenario_keys: tuple[str, str, str, str]


class HistoricalModelRecord(Protocol):
    """Minimal shape shared by historical ORM records in this migration."""

    pk: object


AI_CAPEX_STRONG: DriverSeedSpec = {
    "driver_key": "ai_capex_cycle",
    "state": "strong",
    "proxy_indicator": "data_center.macro.ai_capex_growth_yoy",
    "unit": "percent",
    "start_value": "15",
    "end_value": "18",
}
AI_CAPEX_WEAK: DriverSeedSpec = {
    "driver_key": "ai_capex_cycle",
    "state": "weak",
    "proxy_indicator": "data_center.macro.ai_capex_growth_yoy",
    "unit": "percent",
    "start_value": "2",
    "end_value": "-2",
}
OVERSEAS_MONEY_EASING: DriverSeedSpec = {
    "driver_key": "overseas_monetary_conditions",
    "state": "easing",
    "proxy_indicator": "data_center.macro.us_policy_rate",
    "unit": "percent",
    "start_value": "4.5",
    "end_value": "3.5",
}
OVERSEAS_MONEY_TIGHTENING: DriverSeedSpec = {
    "driver_key": "overseas_monetary_conditions",
    "state": "tightening",
    "proxy_indicator": "data_center.macro.us_policy_rate",
    "unit": "percent",
    "start_value": "5.25",
    "end_value": "5.5",
}
DOMESTIC_MONEY_EASING: DriverSeedSpec = {
    "driver_key": "domestic_monetary_conditions",
    "state": "easing",
    "proxy_indicator": "data_center.macro.cn_m2_growth_yoy",
    "unit": "percent",
    "start_value": "8.5",
    "end_value": "9",
}
DOMESTIC_MONEY_TIGHTENING: DriverSeedSpec = {
    "driver_key": "domestic_monetary_conditions",
    "state": "tightening",
    "proxy_indicator": "data_center.macro.cn_m2_growth_yoy",
    "unit": "percent",
    "start_value": "6.5",
    "end_value": "6",
}
CREDIT_EXPANSION: DriverSeedSpec = {
    "driver_key": "credit_impulse",
    "state": "expansion",
    "proxy_indicator": "data_center.macro.cn_credit_impulse",
    "unit": "index",
    "start_value": "1",
    "end_value": "1.5",
}
CREDIT_CONTRACTION: DriverSeedSpec = {
    "driver_key": "credit_impulse",
    "state": "contraction",
    "proxy_indicator": "data_center.macro.cn_credit_impulse",
    "unit": "index",
    "start_value": "-0.5",
    "end_value": "-1",
}


def _impact(target: str, value: str, rationale: str) -> ImpactSeedSpec:
    """Build one explicit asset-class impact seed."""

    return {
        "target_kind": "asset_class",
        "target": target,
        "cumulative_return": value,
        "rationale": rationale,
    }


MACRO_SCENARIOS: tuple[MacroScenarioSeedSpec, ...] = (
    {
        "scenario_key": "macro.ai_capex.strong_overseas_easing",
        "name": "AI资本开支强劲×海外货币宽松",
        "description": "AI资本开支保持强劲，同时海外货币条件转向宽松。",
        "drivers": (AI_CAPEX_STRONG, OVERSEAS_MONEY_EASING),
        "impacts": (
            _impact("global_equity_ai", "0.15", "盈利预期与贴现率同时改善。"),
            _impact("cn_equity", "0.06", "全球科技需求与流动性形成正向外溢。"),
            _impact("fixed_income_duration", "0.03", "海外宽松对久期资产提供支撑。"),
        ),
    },
    {
        "scenario_key": "macro.ai_capex.strong_overseas_tightening",
        "name": "AI资本开支强劲×海外货币收紧",
        "description": "AI资本开支保持强劲，但海外货币条件继续收紧。",
        "drivers": (AI_CAPEX_STRONG, OVERSEAS_MONEY_TIGHTENING),
        "impacts": (
            _impact("global_equity_ai", "0.05", "盈利增长部分抵消估值压缩。"),
            _impact("cn_equity", "-0.03", "外部流动性收紧压制风险偏好。"),
            _impact("fixed_income_duration", "-0.04", "利率上行对久期资产不利。"),
        ),
    },
    {
        "scenario_key": "macro.ai_capex.weak_overseas_easing",
        "name": "AI资本开支走弱×海外货币宽松",
        "description": "AI资本开支转弱，海外货币条件转向宽松。",
        "drivers": (AI_CAPEX_WEAK, OVERSEAS_MONEY_EASING),
        "impacts": (
            _impact("global_equity_ai", "-0.08", "需求下修主导，宽松仅缓冲估值压力。"),
            _impact("cn_equity", "0.02", "流动性改善部分抵消外需走弱。"),
            _impact("fixed_income_duration", "0.06", "增长走弱与宽松共同利多久期。"),
        ),
    },
    {
        "scenario_key": "macro.ai_capex.weak_overseas_tightening",
        "name": "AI资本开支走弱×海外货币收紧",
        "description": "AI资本开支转弱，同时海外货币条件继续收紧。",
        "drivers": (AI_CAPEX_WEAK, OVERSEAS_MONEY_TIGHTENING),
        "impacts": (
            _impact("global_equity_ai", "-0.18", "盈利下修与估值压缩叠加。"),
            _impact("cn_equity", "-0.1", "外需与全球风险偏好同步走弱。"),
            _impact("fixed_income_duration", "-0.05", "紧缩冲击暂时压过增长避险效应。"),
        ),
    },
    {
        "scenario_key": "macro.money_credit.easing_expansion",
        "name": "货币宽松×信用扩张",
        "description": "国内货币条件宽松，信用脉冲同步扩张。",
        "drivers": (DOMESTIC_MONEY_EASING, CREDIT_EXPANSION),
        "impacts": (
            _impact("cn_equity", "0.1", "流动性和信用需求共同改善。"),
            _impact("fixed_income_duration", "0.02", "宽松利好久期但信用扩张限制收益。"),
            _impact("credit", "0.05", "融资环境和偿付预期改善。"),
        ),
    },
    {
        "scenario_key": "macro.money_credit.easing_contraction",
        "name": "货币宽松×信用收缩",
        "description": "国内货币条件宽松，但信用脉冲继续收缩。",
        "drivers": (DOMESTIC_MONEY_EASING, CREDIT_CONTRACTION),
        "impacts": (
            _impact("cn_equity", "-0.03", "宽货币尚未传导为实体信用需求。"),
            _impact("fixed_income_duration", "0.07", "资产荒与增长压力利多久期。"),
            _impact("credit", "-0.04", "信用收缩抬升弱资质风险溢价。"),
        ),
    },
    {
        "scenario_key": "macro.money_credit.tightening_expansion",
        "name": "货币收紧×信用扩张",
        "description": "国内货币条件收紧，但信用脉冲仍在扩张。",
        "drivers": (DOMESTIC_MONEY_TIGHTENING, CREDIT_EXPANSION),
        "impacts": (
            _impact("cn_equity", "0.02", "信用需求支撑盈利但估值承压。"),
            _impact("fixed_income_duration", "-0.06", "货币收紧推升期限利率。"),
            _impact("credit", "0.01", "信用扩张缓冲无风险利率上行。"),
        ),
    },
    {
        "scenario_key": "macro.money_credit.tightening_contraction",
        "name": "货币收紧×信用收缩",
        "description": "国内货币条件收紧，信用脉冲同步收缩。",
        "drivers": (DOMESTIC_MONEY_TIGHTENING, CREDIT_CONTRACTION),
        "impacts": (
            _impact("cn_equity", "-0.12", "流动性与融资需求同时恶化。"),
            _impact("fixed_income_duration", "-0.02", "紧缩冲击与避险需求相互抵消。"),
            _impact("credit", "-0.08", "信用收缩和融资成本上升扩大风险溢价。"),
        ),
    },
)

SCENARIO_SETS: tuple[ScenarioSetSeedSpec, ...] = (
    {
        "set_key": "macro_matrix.ai_capex_x_overseas_monetary",
        "name": "AI资本开支×海外货币条件",
        "purpose": "forward_macro_stress",
        "driver_axes": ("ai_capex_cycle", "overseas_monetary_conditions"),
        "scenario_keys": (
            MACRO_SCENARIOS[0]["scenario_key"],
            MACRO_SCENARIOS[1]["scenario_key"],
            MACRO_SCENARIOS[2]["scenario_key"],
            MACRO_SCENARIOS[3]["scenario_key"],
        ),
    },
    {
        "set_key": "macro_matrix.monetary_x_credit",
        "name": "货币条件×信用脉冲",
        "purpose": "forward_macro_stress",
        "driver_axes": ("domestic_monetary_conditions", "credit_impulse"),
        "scenario_keys": (
            MACRO_SCENARIOS[4]["scenario_key"],
            MACRO_SCENARIOS[5]["scenario_key"],
            MACRO_SCENARIOS[6]["scenario_key"],
            MACRO_SCENARIOS[7]["scenario_key"],
        ),
    },
)

ROLLING_KEY = "rolling.cn_equity.20d_min_return_3y"
PARAMETRIC_KEY = "parametric.multi_asset.rate_equity_shock"
ALL_SCENARIO_KEYS = (ROLLING_KEY, PARAMETRIC_KEY) + tuple(
    item["scenario_key"] for item in MACRO_SCENARIOS
)
ALL_SET_KEYS = tuple(item["set_key"] for item in SCENARIO_SETS)


def _content_hash(payload: Mapping[str, object]) -> str:
    """Match the domain's stable hash for canonical JSON-safe content."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _missing_evidence(
    *,
    scenario_key: str,
    proxy_indicator: str,
) -> dict[str, object]:
    """Publish an explicit blocked placeholder without fabricating observation time."""

    return {
        "evidence_id": f"seed:{scenario_key}:{proxy_indicator}",
        "migration_ref": MIGRATION_REF,
        "proxy_indicator": proxy_indicator,
        "observed_at": None,
        "published_at": None,
        "observation_status": "missing",
        "freshness": "missing",
        "reliability": "blocked",
        "must_not_use_for_decision": True,
        "blocked_reason": "seed_candidate_requires_published_observation",
    }


def _scenario_hash(
    *,
    scenario_key: str,
    scenario_type: str,
    parameters: dict[str, object],
    assumptions: list[str],
    source_evidence: list[dict[str, object]],
) -> str:
    """Seal the same business fields as ``ScenarioRevision``."""

    return _content_hash(
        {
            "scenario_key": scenario_key,
            "scenario_type": scenario_type,
            "parameters": parameters,
            "assumptions": assumptions,
            "source_evidence": source_evidence,
        }
    )


def _assert_defaults(
    *,
    instance: object,
    defaults: Mapping[str, object],
    context: str,
) -> None:
    """Fail closed when a stable seed key collides with divergent content."""

    for field_name, expected in defaults.items():
        if getattr(instance, field_name) != expected:
            raise RuntimeError(f"scenario seed collision: {context}:{field_name}")


def _primary_key(instance: object) -> object:
    """Return a historical model primary key without importing runtime models."""

    return cast(HistoricalModelRecord, instance).pk


def _seed_revision(
    *,
    Definition: object,
    Revision: object,
    scenario_key: str,
    name: str,
    category: str,
    description: str,
    scenario_type: str,
    parameters: dict[str, object],
    assumptions: list[str],
    source_evidence: list[dict[str, object]],
) -> object:
    """Insert one deterministic candidate revision once."""

    definition_defaults = {
        "name": name,
        "category": category,
        "owner": "risk_center",
        "status": "active",
        "description": description,
        "legacy_aliases": [],
        "created_at": CREATED_AT,
    }
    definition, definition_created = Definition.objects.get_or_create(  # type: ignore[attr-defined]
        scenario_key=scenario_key,
        defaults=definition_defaults,
    )
    if not definition_created:
        _assert_defaults(
            instance=definition,
            defaults=definition_defaults,
            context=f"definition:{scenario_key}",
        )

    revision_defaults = {
        "revision_id": uuid.uuid5(UUID_NAMESPACE, f"scenario:{scenario_key}:v1"),
        "based_on_version": None,
        "status": "candidate",
        "scenario_type": scenario_type,
        "parameters": parameters,
        "assumptions": assumptions,
        "source_evidence": source_evidence,
        "source_type": "seed",
        "content_hash": _scenario_hash(
            scenario_key=scenario_key,
            scenario_type=scenario_type,
            parameters=parameters,
            assumptions=assumptions,
            source_evidence=source_evidence,
        ),
        "created_by": CREATED_BY,
        "change_reason": "Seed an inactive maintainable scenario candidate.",
        "effective_at": None,
        "created_at": CREATED_AT,
    }
    revision, revision_created = Revision.objects.get_or_create(  # type: ignore[attr-defined]
        definition_id=definition.pk,
        version=1,
        defaults=revision_defaults,
    )
    if not revision_created:
        _assert_defaults(
            instance=revision,
            defaults=revision_defaults,
            context=f"revision:{scenario_key}:1",
        )
    return revision


def _seed_rolling_and_parametric(Definition: object, Revision: object) -> None:
    """Insert one rolling and one parametric candidate."""

    rolling_evidence = [
        _missing_evidence(
            scenario_key=ROLLING_KEY,
            proxy_indicator="data_center.price_bar.000300.SH",
        )
    ]
    _seed_revision(
        Definition=Definition,
        Revision=Revision,
        scenario_key=ROLLING_KEY,
        name="沪深300近三年最差20日窗口",
        category="rolling_extreme",
        description="从最近756个交易日选择累计收益最低的20日窗口。",
        scenario_type="rolling_extreme",
        parameters={
            "lookback_days": 756,
            "window_days": 20,
            "selection_indicator": "000300.SH",
            "selection_metric": "cumulative_return",
            "direction": "minimum",
            "recalculation_frequency": "daily",
        },
        assumptions=[
            "Candidate requires point-in-time published daily bars before recalculation.",
            "Migration does not imply that the referenced price series is currently fresh.",
        ],
        source_evidence=rolling_evidence,
    )

    parametric_evidence = [
        _missing_evidence(
            scenario_key=PARAMETRIC_KEY,
            proxy_indicator="portfolio.snapshot.multi_asset_exposure",
        )
    ]
    _seed_revision(
        Definition=Definition,
        Revision=Revision,
        scenario_key=PARAMETRIC_KEY,
        name="多资产权益与利率联合冲击",
        category="parametric_shock",
        description="显式施加权益回撤与利率上行冲击，不执行任意公式。",
        scenario_type="parametric_shock",
        parameters={
            "shocks": [
                {
                    "target_kind": "asset_class",
                    "target": "cn_equity",
                    "shock_kind": "return",
                    "magnitude": "-0.15",
                    "unit": "percent",
                    "horizon_days": 20,
                },
                {
                    "target_kind": "factor",
                    "target": "duration",
                    "shock_kind": "yield_change",
                    "magnitude": "75",
                    "unit": "basis_points",
                    "horizon_days": 20,
                },
            ],
            "correlation_assumption": "Apply both finite shocks concurrently; no dynamic correlation model is inferred.",
        },
        assumptions=[
            "Candidate magnitudes are governance seeds and require human review before approval.",
            "Portfolio exposures must come from an immutable published snapshot.",
        ],
        source_evidence=parametric_evidence,
    )


def _macro_parameters(spec: MacroScenarioSeedSpec) -> dict[str, object]:
    """Build strict ``MacroPathParameters`` persistence JSON."""

    drivers = [
        {
            "driver_key": driver["driver_key"],
            "state": driver["state"],
            "proxy_indicator": driver["proxy_indicator"],
            "unit": driver["unit"],
            "nodes": [
                {"path_date": "2026-09-30", "value": driver["start_value"]},
                {"path_date": "2026-12-31", "value": driver["end_value"]},
            ],
        }
        for driver in spec["drivers"]
    ]
    return {
        "drivers": drivers,
        "probability": "0.25",
        "probability_source": "subjective",
        "asset_impacts": [dict(impact) for impact in spec["impacts"]],
        "invalidation_conditions": [
            "A published proxy observation contradicts the assumed state for two consecutive releases.",
            "Any required proxy remains missing at the review date.",
        ],
        "review_date": "2026-09-30",
    }


def _seed_macro_candidates(Definition: object, Revision: object) -> dict[str, object]:
    """Insert eight typed macro-path quadrant candidates."""

    revisions: dict[str, object] = {}
    for spec in MACRO_SCENARIOS:
        evidence = [
            _missing_evidence(
                scenario_key=spec["scenario_key"],
                proxy_indicator=driver["proxy_indicator"],
            )
            for driver in spec["drivers"]
        ]
        revision = _seed_revision(
            Definition=Definition,
            Revision=Revision,
            scenario_key=spec["scenario_key"],
            name=spec["name"],
            category="macro_path",
            description=spec["description"],
            scenario_type="macro_path",
            parameters=_macro_parameters(spec),
            assumptions=[
                "Candidate paths are subjective governance seeds, not forecasts.",
                "No published observation or freshness was fabricated by this migration.",
            ],
            source_evidence=evidence,
        )
        revisions[spec["scenario_key"]] = revision
    return revisions


def _seed_scenario_sets(
    *,
    ScenarioSet: object,
    SetRevision: object,
    SetMember: object,
    revisions: Mapping[str, object],
) -> None:
    """Insert two non-active two-axis set revisions with probabilities summing to one."""

    for spec in SCENARIO_SETS:
        set_defaults = {
            "name": spec["name"],
            "purpose": spec["purpose"],
            "owner": "risk_center",
            "applicable_asset_scope": [
                "cn_equity",
                "global_equity",
                "fixed_income",
                "credit",
            ],
            "status": "active",
            "created_at": CREATED_AT,
        }
        scenario_set, set_created = ScenarioSet.objects.get_or_create(  # type: ignore[attr-defined]
            set_key=spec["set_key"],
            defaults=set_defaults,
        )
        if not set_created:
            _assert_defaults(
                instance=scenario_set,
                defaults=set_defaults,
                context=f"set:{spec['set_key']}",
            )

        set_revision_id = uuid.uuid5(UUID_NAMESPACE, f"set:{spec['set_key']}:v1")
        member_hash_payload = [
            {
                "scenario_revision_id": str(_primary_key(revisions[key])),
                "probability": "0.25",
                "probability_source": "subjective",
                "sort_order": sort_order,
            }
            for sort_order, key in enumerate(spec["scenario_keys"])
        ]
        set_revision_defaults = {
            "revision_id": set_revision_id,
            "status": "candidate",
            "driver_axes": list(spec["driver_axes"]),
            "content_hash": _content_hash(
                {
                    "set_key": spec["set_key"],
                    "members": member_hash_payload,
                    "driver_axes": list(spec["driver_axes"]),
                    "effective_from": None,
                    "effective_to": None,
                }
            ),
            "created_by": CREATED_BY,
            "change_reason": "Seed an inactive two-axis macro scenario set candidate.",
            "effective_from": None,
            "effective_to": None,
            "created_at": CREATED_AT,
        }
        set_revision, set_revision_created = SetRevision.objects.get_or_create(  # type: ignore[attr-defined]
            scenario_set_id=scenario_set.pk,
            version=1,
            defaults=set_revision_defaults,
        )
        if not set_revision_created:
            _assert_defaults(
                instance=set_revision,
                defaults=set_revision_defaults,
                context=f"set-revision:{spec['set_key']}:1",
            )

        for sort_order, scenario_key in enumerate(spec["scenario_keys"]):
            member_defaults = {
                "probability": Decimal("0.25"),
                "probability_source": "subjective",
                "sort_order": sort_order,
                "created_at": CREATED_AT,
            }
            member, member_created = SetMember.objects.get_or_create(  # type: ignore[attr-defined]
                scenario_set_revision_id=set_revision.pk,
                scenario_revision_id=_primary_key(revisions[scenario_key]),
                defaults=member_defaults,
            )
            if not member_created:
                _assert_defaults(
                    instance=member,
                    defaults=member_defaults,
                    context=f"set-member:{spec['set_key']}:{scenario_key}",
                )


def seed_initial_scenario_candidates(apps: object, _schema_editor: object) -> None:
    """Insert all M4 candidates idempotently without creating an activation."""

    Definition = apps.get_model("risk_center", "StressScenarioDefinitionModel")  # type: ignore[attr-defined]
    Revision = apps.get_model("risk_center", "StressScenarioRevisionModel")  # type: ignore[attr-defined]
    ScenarioSet = apps.get_model("risk_center", "ScenarioSetModel")  # type: ignore[attr-defined]
    SetRevision = apps.get_model("risk_center", "ScenarioSetRevisionModel")  # type: ignore[attr-defined]
    SetMember = apps.get_model("risk_center", "ScenarioSetMemberModel")  # type: ignore[attr-defined]

    _seed_rolling_and_parametric(Definition, Revision)
    macro_revisions = _seed_macro_candidates(Definition, Revision)
    _seed_scenario_sets(
        ScenarioSet=ScenarioSet,
        SetRevision=SetRevision,
        SetMember=SetMember,
        revisions=macro_revisions,
    )


def unseed_initial_scenario_candidates(apps: object, _schema_editor: object) -> None:
    """Remove only deterministic rows owned by this exact migration."""

    Definition = apps.get_model("risk_center", "StressScenarioDefinitionModel")  # type: ignore[attr-defined]
    Revision = apps.get_model("risk_center", "StressScenarioRevisionModel")  # type: ignore[attr-defined]
    ScenarioSet = apps.get_model("risk_center", "ScenarioSetModel")  # type: ignore[attr-defined]
    SetRevision = apps.get_model("risk_center", "ScenarioSetRevisionModel")  # type: ignore[attr-defined]
    SetMember = apps.get_model("risk_center", "ScenarioSetMemberModel")  # type: ignore[attr-defined]

    set_revision_ids = [uuid.uuid5(UUID_NAMESPACE, f"set:{set_key}:v1") for set_key in ALL_SET_KEYS]
    scenario_revision_ids = [
        uuid.uuid5(UUID_NAMESPACE, f"scenario:{scenario_key}:v1")
        for scenario_key in ALL_SCENARIO_KEYS
    ]
    SetMember.objects.filter(
        scenario_set_revision_id__in=set_revision_ids,
        scenario_revision_id__in=scenario_revision_ids,
    ).delete()
    SetRevision.objects.filter(
        revision_id__in=set_revision_ids,
        created_by=CREATED_BY,
        version=1,
        status="candidate",
    ).delete()
    ScenarioSet.objects.filter(
        set_key__in=ALL_SET_KEYS,
        revisions__isnull=True,
    ).delete()
    Revision.objects.filter(
        revision_id__in=scenario_revision_ids,
        definition__scenario_key__in=ALL_SCENARIO_KEYS,
        version=1,
        source_type="seed",
        created_by=CREATED_BY,
    ).delete()
    Definition.objects.filter(
        scenario_key__in=ALL_SCENARIO_KEYS,
        revisions__isnull=True,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("risk_center", "0005_scenario_write_governance")]

    operations = [
        migrations.RunPython(
            seed_initial_scenario_candidates,
            unseed_initial_scenario_candidates,
        )
    ]
