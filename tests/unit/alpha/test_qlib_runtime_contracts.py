"""Deterministic contracts for the optional Qlib runtime boundary."""

from __future__ import annotations

import pickle
import sys
from datetime import date, datetime
from io import StringIO
from types import ModuleType, SimpleNamespace

import pandas as pd
import pytest
from django.contrib.admin.sites import AdminSite
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import CommandError

from apps.alpha import admin as alpha_admin
from apps.alpha.infrastructure import qlib_artifact_runtime as artifacts
from apps.alpha.infrastructure import qlib_prediction_runtime as prediction_runtime
from apps.alpha.infrastructure import qlib_runtime_init as runtime
from apps.alpha.infrastructure.adapters import qlib_adapter
from apps.alpha.infrastructure.adapters.qlib_adapter import QlibAlphaProvider
from apps.alpha.management.commands import train_qlib_model as train_command


class _Handler:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class _Dataset:
    def __init__(self, handler: object, segments: dict[str, object]) -> None:
        self.handler = handler
        self.segments = segments

    def prepare(self) -> None:
        return None

    def fetch(self, cols: list[str]) -> pd.DataFrame:
        dates = pd.to_datetime(["2026-07-20", "2026-07-21"])
        columns = [f"S{index:02d}" for index in range(12)]
        return pd.DataFrame(
            [[float(index) for index in range(12)]] * 2,
            index=dates,
            columns=columns,
        )


class _Model:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.fitted = False

    def fit(self, dataset: object) -> None:
        self.fitted = True

    def predict(self, dataset: object) -> pd.DataFrame:
        dates = pd.to_datetime(["2026-07-20", "2026-07-21"])
        columns = [f"S{index:02d}" for index in range(12)]
        return pd.DataFrame(
            [[float(index) for index in range(12)]] * 2,
            index=dates,
            columns=columns,
        )


def _install_fake_qlib(monkeypatch) -> None:
    qlib = ModuleType("qlib")
    qlib.__version__ = "test"
    qlib.init = lambda **kwargs: None
    handlers = ModuleType("qlib.contrib.data.handler")
    handlers.Alpha158 = _Handler
    handlers.Alpha360 = _Handler
    gbdt = ModuleType("qlib.contrib.model.gbdt")
    gbdt.LGBModel = _Model
    mlp = ModuleType("qlib.contrib.model.mlptron")
    mlp.MLPTPModel = _Model
    gru = ModuleType("qlib.contrib.model.pytorch_gru")
    gru.GRUModel = _Model
    lstm = ModuleType("qlib.contrib.model.pytorch_lstm")
    lstm.LSTMModel = _Model
    data = ModuleType("qlib.data")
    data.D = SimpleNamespace(
        instruments=lambda market: ["S00", "S01"],
        calendar=lambda **kwargs: pd.to_datetime(["2026-07-23", "2026-07-24"]),
        features=lambda **kwargs: pd.DataFrame(
            [[0.1, 0.2, 0.3, 0.4, 0.5]],
        ),
    )
    dataset = ModuleType("qlib.data.dataset")
    dataset.DatasetH = _Dataset
    modules = {
        "qlib": qlib,
        "qlib.contrib": ModuleType("qlib.contrib"),
        "qlib.contrib.data": ModuleType("qlib.contrib.data"),
        "qlib.contrib.data.handler": handlers,
        "qlib.contrib.model": ModuleType("qlib.contrib.model"),
        "qlib.contrib.model.gbdt": gbdt,
        "qlib.contrib.model.mlptron": mlp,
        "qlib.contrib.model.pytorch_gru": gru,
        "qlib.contrib.model.pytorch_lstm": lstm,
        "qlib.data": data,
        "qlib.data.dataset": dataset,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)


def test_qlib_training_and_evaluation_use_runtime_contract(monkeypatch) -> None:
    """Training selects the configured handler/model and evaluation returns real correlations."""
    assert runtime._normalize_qlib_feature_set_id("v1") == "alpha360"
    assert runtime._normalize_qlib_feature_set_id("v158") == "alpha158"
    with pytest.raises(ValueError, match="不支持"):
        runtime._normalize_qlib_feature_set_id("custom-unknown")

    _install_fake_qlib(monkeypatch)
    monkeypatch.setattr(
        artifacts,
        "_get_runtime_qlib_config",
        lambda: {"enabled": True, "provider_uri": ".", "region": "CN"},
    )
    if hasattr(artifacts._train_qlib_model, "_qlib_initialized"):
        delattr(artifacts._train_qlib_model, "_qlib_initialized")

    model = artifacts._train_qlib_model(
        "LGBModel",
        {
            "universe": "csi300",
            "start_date": "2026-01-01",
            "end_date": "2026-07-24",
            "feature_set_id": "alpha158",
            "model_params": {"learning_rate": 0.2},
        },
    )
    assert model.fitted is True
    assert model.kwargs["learning_rate"] == 0.2

    metrics = artifacts._evaluate_model_metrics(
        model,
        "csi300",
        {
            "start_date": "2026-01-01",
            "end_date": "2026-07-24",
            "feature_set_id": "alpha158",
        },
    )
    assert metrics["sample_count"] == 2
    assert metrics["ic"] == pytest.approx(1.0)

    with pytest.raises(ValueError, match="不支持"):
        artifacts._train_qlib_model(
            "UnknownModel",
            {"start_date": "2026-01-01", "end_date": "2026-07-24"},
        )

    class _FallbackDataset(_Dataset):
        def fetch(self, cols: list[str]) -> pd.DataFrame:
            raise RuntimeError("labels unavailable")

    sys.modules["qlib.data.dataset"].DatasetH = _FallbackDataset
    with pytest.raises(RuntimeError, match="labels unavailable"):
        artifacts._evaluate_model_metrics(
            model,
            "csi300",
            {"start_date": "2026-01-01", "end_date": "2026-07-24"},
        )


def test_runtime_helpers_normalize_resolve_and_explain_failures(monkeypatch, tmp_path) -> None:
    """Runtime metadata helpers normalize inputs and make fallback reasons explicit."""
    actual_latest_date = runtime._get_qlib_data_latest_date
    assert runtime._normalize_qlib_region("china")
    assert runtime._normalize_qlib_region("US")
    assert runtime._normalize_calendar_date(datetime(2026, 7, 24)) == date(2026, 7, 24)
    assert runtime._normalize_qlib_instrument_list(["000001.SZ", "sz000001", "", "000001.SZ"]) == [
        "SZ000001"
    ]
    assert runtime._parse_universe_list(None) == ["csi300"]
    assert runtime._parse_universe_list(" CSI300, CSI500 ") == ["csi300", "csi500"]
    assert runtime._cache_is_fresh_for_trade_date(None, date(2026, 7, 24)) is False
    row = SimpleNamespace(scores=[1], status="available", asof_date=date(2026, 7, 24))
    assert runtime._cache_is_fresh_for_trade_date(row, date(2026, 7, 24)) is True

    existing = tmp_path / "model.pkl"
    existing.write_bytes(b"model")
    assert (
        runtime._resolve_qlib_model_path(
            SimpleNamespace(model_path=str(existing)),
            {},
        )
        == existing
    )
    fallback_dir = tmp_path / "fallback"
    fallback_dir.mkdir()
    fallback = fallback_dir / "remote.pkl"
    fallback.write_bytes(b"model")
    assert (
        runtime._resolve_qlib_model_path(
            SimpleNamespace(model_path=r"C:\models\remote.pkl"),
            {"model_path": str(fallback_dir)},
        )
        == fallback
    )

    api = SimpleNamespace(instruments=lambda market: ["A", "", "B"])
    assert runtime._resolve_qlib_stock_list(api, "csi300") == ["A", "B"]
    with pytest.raises(RuntimeError, match="未找到股票池"):
        runtime._resolve_qlib_stock_list(
            SimpleNamespace(instruments=lambda market: []),
            "missing",
        )
    assert runtime._make_json_safe(
        {"path": existing, "date": date(2026, 7, 24), "values": (1, 2)}
    ) == {
        "path": str(existing),
        "date": "2026-07-24",
        "values": [1, 2],
    }

    monkeypatch.setattr(runtime, "_get_qlib_data_latest_date", lambda: None)
    assert "目录为空" in runtime._build_outdated_qlib_reason(date(2026, 7, 24))
    monkeypatch.setattr(
        runtime,
        "_get_qlib_data_latest_date",
        lambda: date(2026, 7, 1),
    )
    assert "请先同步" in runtime._build_outdated_qlib_reason(date(2026, 7, 24))
    assert "未安装" in runtime._build_qlib_runtime_failure_reason(
        ModuleNotFoundError("No module named 'qlib'", name="qlib")
    )

    _install_fake_qlib(monkeypatch)
    if hasattr(actual_latest_date, "_qlib_initialized"):
        delattr(actual_latest_date, "_qlib_initialized")
    monkeypatch.setattr(
        runtime,
        "_get_runtime_qlib_config",
        lambda: {"enabled": True, "provider_uri": ".", "region": "CN"},
    )
    assert actual_latest_date() == date(2026, 7, 24)
    assert runtime._resolve_qlib_handler_class("alpha158") is _Handler
    assert runtime._resolve_qlib_handler_class("alpha360") is _Handler

    dict_api = SimpleNamespace(
        instruments=lambda market: {"market": market},
        list_instruments=lambda instruments, **kwargs: ["S00", "S01"],
    )
    assert runtime._resolve_qlib_stock_list(dict_api, "csi300") == ["S00", "S01"]
    with pytest.raises(RuntimeError, match="不支持展开"):
        runtime._resolve_qlib_stock_list(
            SimpleNamespace(instruments=lambda market: {"market": market}),
            "csi300",
        )


def test_qlib_runtime_rebinds_when_provider_binding_changes() -> None:
    """Long-lived workers must not keep using a previous provider directory."""

    module = SimpleNamespace(init_calls=[])

    def _init(**kwargs: str) -> None:
        module.init_calls.append(kwargs)

    module.init = _init
    runtime._initialize_qlib_runtime(
        provider_uri="old-data",
        region="CN",
        qlib_module=module,
    )
    runtime._initialize_qlib_runtime(
        provider_uri="old-data",
        region="cn",
        qlib_module=module,
    )
    runtime._initialize_qlib_runtime(
        provider_uri="new-data",
        region="US",
        qlib_module=module,
    )

    assert module.init_calls == [
        {"provider_uri": "old-data", "region": "cn"},
        {"provider_uri": "new-data", "region": "us"},
    ]


def test_qlib_latest_date_blocks_without_typed_runtime_snapshot(monkeypatch) -> None:
    """Calendar probes must not fall back to the legacy/default provider URI."""
    _install_fake_qlib(monkeypatch)
    monkeypatch.setattr(
        runtime,
        "_get_runtime_qlib_config",
        lambda: {
            "enabled": False,
            "status": "blocked",
            "must_not_use_for_decision": True,
            "blocked_reason": "runtime_config_snapshot_unavailable",
        },
    )

    with pytest.raises(RuntimeError, match="runtime_config_snapshot_unavailable"):
        runtime._get_qlib_data_latest_date()


@pytest.mark.parametrize("top_n", [True, 0, 5001])
def test_qlib_prediction_rejects_invalid_top_n_before_runtime_access(top_n: int) -> None:
    """Invalid result limits fail before optional runtime dependencies are accessed."""
    with pytest.raises(ValueError, match="top_n must be between 1 and 5000"):
        prediction_runtime._execute_qlib_prediction(
            active_model=SimpleNamespace(),
            universe_id="csi300",
            trade_date=date(2026, 7, 24),
            top_n=top_n,
            outdated_reason_builder=lambda _: None,
        )


def test_qlib_prediction_fails_explicitly_when_runtime_is_disabled(monkeypatch) -> None:
    """A disabled runtime must not be mistaken for a successful empty prediction."""
    _install_fake_qlib(monkeypatch)
    monkeypatch.setattr(
        prediction_runtime,
        "_get_runtime_qlib_config",
        lambda: {"enabled": False},
    )

    with pytest.raises(RuntimeError, match="Qlib 未启用"):
        prediction_runtime._execute_qlib_prediction(
            active_model=SimpleNamespace(),
            universe_id="csi300",
            trade_date=date(2026, 7, 24),
            top_n=10,
            outdated_reason_builder=lambda _: None,
        )


def test_qlib_prediction_drops_nonfinite_scores_and_deduplicates_codes(
    monkeypatch,
    tmp_path,
) -> None:
    """Prediction output keeps the best finite score for each normalized stock code."""
    _install_fake_qlib(monkeypatch)
    model_path = tmp_path / "model.pkl"
    model_path.write_bytes(b"placeholder")
    prediction = pd.Series(
        [0.2, 0.8, float("inf"), float("nan")],
        index=["000001.SZ", "SZ000001", "000002.SZ", "000003.SZ"],
    )
    model = SimpleNamespace(predict=lambda dataset: prediction)
    monkeypatch.setattr(
        prediction_runtime,
        "_get_runtime_qlib_config",
        lambda: {"enabled": True, "provider_uri": ".", "region": "CN"},
    )
    monkeypatch.setattr(prediction_runtime, "_install_qlib_pandas_compat", lambda: None)
    monkeypatch.setattr(
        prediction_runtime,
        "_resolve_qlib_model_path",
        lambda active_model, qlib_config: model_path,
    )
    monkeypatch.setattr(
        prediction_runtime,
        "_resolve_qlib_stock_list",
        lambda data_api, universe_id, start_time, end_time: [
            "SZ000001",
            "SZ000002",
            "SZ000003",
        ],
    )
    monkeypatch.setattr(
        prediction_runtime,
        "_resolve_qlib_handler_class",
        lambda feature_set_id: _Handler,
    )
    monkeypatch.setattr(prediction_runtime.pickle, "load", lambda file_handle: model)
    if hasattr(prediction_runtime._execute_qlib_prediction, "_qlib_initialized"):
        delattr(prediction_runtime._execute_qlib_prediction, "_qlib_initialized")

    try:
        scores = prediction_runtime._execute_qlib_prediction(
            active_model=SimpleNamespace(feature_set_id="alpha158"),
            universe_id="csi300",
            trade_date=date(2026, 7, 24),
            top_n=10,
            outdated_reason_builder=lambda _: None,
        )
    finally:
        if hasattr(prediction_runtime._execute_qlib_prediction, "_qlib_initialized"):
            delattr(prediction_runtime._execute_qlib_prediction, "_qlib_initialized")

    assert scores == [
        {
            "code": "000001.SZ",
            "score": 0.8,
            "rank": 1,
            "factors": {},
            "source": "qlib",
            "confidence": 0.8,
            "asof_date": "2026-07-24",
            "intended_trade_date": "2026-07-24",
            "universe_id": "csi300",
        }
    ]


def test_qlib_prediction_batches_large_scopes(monkeypatch, tmp_path) -> None:
    """Large scopes are predicted in bounded batches instead of one huge DatasetH."""
    _install_fake_qlib(monkeypatch)
    model_path = tmp_path / "model.pkl"
    model_path.write_bytes(b"placeholder")
    calls: list[tuple[str, ...]] = []

    class _BatchModel:
        def predict(self, dataset: object) -> pd.Series:
            instruments = tuple(dataset.handler.kwargs["instruments"])
            calls.append(instruments)
            return pd.Series(
                [float(index) for index, _ in enumerate(instruments)],
                index=list(instruments),
            )

    model = _BatchModel()
    monkeypatch.setenv("QLIB_PREDICTION_BATCH_SIZE", "2")
    monkeypatch.setattr(
        prediction_runtime,
        "_get_runtime_qlib_config",
        lambda: {"enabled": True, "provider_uri": ".", "region": "CN"},
    )
    monkeypatch.setattr(prediction_runtime, "_install_qlib_pandas_compat", lambda: None)
    monkeypatch.setattr(
        prediction_runtime,
        "_resolve_qlib_model_path",
        lambda active_model, qlib_config: model_path,
    )
    monkeypatch.setattr(
        prediction_runtime,
        "_resolve_qlib_stock_list",
        lambda data_api, universe_id, start_time, end_time: [
            "SZ000001",
            "SZ000002",
            "SZ000003",
            "SZ000004",
            "SZ000005",
        ],
    )
    monkeypatch.setattr(prediction_runtime.pickle, "load", lambda file_handle: model)
    if hasattr(prediction_runtime._execute_qlib_prediction, "_qlib_initialized"):
        delattr(prediction_runtime._execute_qlib_prediction, "_qlib_initialized")

    try:
        scores = prediction_runtime._execute_qlib_prediction(
            active_model=SimpleNamespace(feature_set_id="alpha158"),
            universe_id="large-scope",
            trade_date=date(2026, 7, 24),
            top_n=5,
            outdated_reason_builder=lambda _: None,
        )
    finally:
        if hasattr(prediction_runtime._execute_qlib_prediction, "_qlib_initialized"):
            delattr(prediction_runtime._execute_qlib_prediction, "_qlib_initialized")

    assert calls == [
        ("SZ000001", "SZ000002"),
        ("SZ000003", "SZ000004"),
        ("SZ000005",),
    ]
    assert len(scores) == 5


@pytest.mark.parametrize("raw_value", ["0", "5001", "not-an-int"])
def test_qlib_prediction_batch_size_rejects_invalid_configuration(
    monkeypatch,
    raw_value: str,
) -> None:
    """An invalid operational batch size fails closed before Qlib allocation."""
    monkeypatch.setenv("QLIB_PREDICTION_BATCH_SIZE", raw_value)
    with pytest.raises(RuntimeError, match="QLIB_PREDICTION_BATCH_SIZE"):
        prediction_runtime._resolve_prediction_batch_size()


def test_qlib_pandas_compatibility_wrappers_preserve_selection_semantics(monkeypatch) -> None:
    """Compatibility shims fall back only for the known pandas index failures."""
    data = ModuleType("qlib.data")
    data.D = SimpleNamespace(features=lambda **kwargs: None)
    data_module = ModuleType("qlib.data.data")
    datasets: list[tuple[object, ...]] = []
    data_module.DatasetD = SimpleNamespace(
        dataset=lambda *args, **kwargs: datasets.append(args) or pd.DataFrame()
    )
    processor = ModuleType("qlib.data.dataset.processor")
    dataset_package = ModuleType("qlib.data.dataset")
    dataset_package.processor = processor
    utils = ModuleType("qlib.data.dataset.utils")
    utils.fetch_df_by_index = lambda *args, **kwargs: (_ for _ in ()).throw(
        KeyError("values are in the [index]")
    )
    utils.get_level_index = lambda df, level: df.index.names.index(level)
    paral = ModuleType("qlib.utils.paral")
    paral.datetime_groupby_apply = lambda *args, **kwargs: (_ for _ in ()).throw(
        TypeError("expected DatetimeIndex")
    )
    config = ModuleType("qlib.config")
    config.C = SimpleNamespace(kernels=4, joblib_backend="loky")
    data.dataset = dataset_package
    for name, module in {
        "qlib": ModuleType("qlib"),
        "qlib.data": data,
        "qlib.data.data": data_module,
        "qlib.data.dataset": dataset_package,
        "qlib.data.dataset.processor": processor,
        "qlib.data.dataset.utils": utils,
        "qlib.utils": ModuleType("qlib.utils"),
        "qlib.utils.paral": paral,
        "qlib.config": config,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    if hasattr(runtime._install_qlib_pandas_compat, "_installed"):
        delattr(runtime._install_qlib_pandas_compat, "_installed")

    runtime._install_qlib_pandas_compat()
    index = pd.MultiIndex.from_product(
        [pd.to_datetime(["2026-07-23", "2026-07-24"]), ["S00", "S01"]],
        names=["datetime", "instrument"],
    )
    frame = pd.DataFrame({"value": [1.0, 2.0, 3.0, 4.0]}, index=index)
    grouped = paral.datetime_groupby_apply(frame, "sum")
    assert len(grouped) == 2
    selected = utils.fetch_df_by_index(
        frame,
        ["S00"],
        "instrument",
    )
    assert set(selected.index.get_level_values("instrument")) == {"S00"}
    data.D.features(["S00"], ["$close"], "2026-07-24", "2026-07-24")
    assert datasets
    assert config.C.kernels == 1
    assert config.C.joblib_backend == "threading"


def test_qlib_adapter_health_queue_inline_factors_and_prediction(monkeypatch, tmp_path) -> None:
    """Provider health and local execution expose cache, queue, and model outcomes."""
    _install_fake_qlib(monkeypatch)
    model_file = tmp_path / "model.pkl"
    model_file.write_bytes(b"placeholder")
    provider = QlibAlphaProvider(provider_uri=str(tmp_path), model_path=str(tmp_path))
    monkeypatch.setattr(provider, "_get_active_model", lambda: {"model_path": str(model_file)})
    monkeypatch.setattr(provider, "_get_latest_data_date", lambda: date.today())
    monkeypatch.setattr(provider, "_has_recent_cache", lambda: True)
    assert provider.health_check().value == "available"

    monkeypatch.setattr(provider, "_has_recent_cache", lambda: False)
    assert provider.health_check().value == "degraded"
    monkeypatch.setattr(
        provider,
        "_get_latest_data_date",
        lambda: date.today().replace(year=date.today().year - 1),
    )
    assert provider.health_check().value == "degraded"
    monkeypatch.setattr(provider, "_get_active_model", lambda: None)
    assert provider.health_check().value == "unavailable"

    active_queues = {"worker": [{"name": "qlib_infer"}]}
    inspect = SimpleNamespace(active_queues=lambda: active_queues)
    monkeypatch.setattr(
        qlib_adapter.current_app.control,
        "inspect",
        lambda timeout: inspect,
    )
    assert provider._resolve_live_inference_queue() == "qlib_infer"
    active_queues["worker"] = [{"name": "celery"}]
    assert provider._resolve_live_inference_queue() == "celery"

    class _Result:
        id = "task-1"

        def get(self, propagate: bool) -> dict[str, int]:
            return {"count": 2}

        def failed(self) -> bool:
            return False

    from apps.alpha.application import tasks as alpha_tasks

    monkeypatch.setattr(alpha_tasks.qlib_predict_scores, "apply", lambda **kwargs: _Result())
    monkeypatch.setattr(qlib_adapter.cache, "add", lambda *args, **kwargs: True)
    monkeypatch.setattr(qlib_adapter.cache, "delete", lambda key: None)
    inline = provider._run_inline_infer_task(
        universe_id="csi300",
        intended_trade_date=date(2026, 7, 24),
        top_n=10,
    )
    assert inline == {"status": "completed", "result": {"count": 2}}
    monkeypatch.setattr(qlib_adapter.cache, "add", lambda *args, **kwargs: False)
    locked = provider._run_inline_infer_task(
        universe_id="csi300",
        intended_trade_date=date(2026, 7, 24),
        top_n=10,
    )
    assert locked["reason"] == "inline_inference_already_running"

    factors = provider.get_factor_exposure("S00", date(2026, 7, 24))
    assert factors["momentum_1d"] == pytest.approx(0.1)
    assert provider.get_universe_stocks("../missing") == []
    assert provider.get_universe_stocks("csi300") == ["S00", "S01"]

    provider._model = _Model()
    provider._active_model_info = {"feature_set_id": "alpha158"}
    predictions = provider.predict("csi300", date(2026, 7, 24))
    assert predictions
    assert all(isinstance(value, float) for value in predictions.values())
    provider._model = None
    assert provider.predict("csi300", date(2026, 7, 24)) == {}


def test_qlib_adapter_cache_trigger_and_model_loading_contract(monkeypatch, tmp_path) -> None:
    """Cached scores retain model evidence and task triggering is throttled."""
    provider = QlibAlphaProvider(provider_uri=str(tmp_path), model_path=str(tmp_path))
    active = {
        "artifact_hash": "hash",
        "model_type": "LGBModel",
        "ic": 0.2,
        "icir": 1.0,
    }
    monkeypatch.setattr(provider, "_get_active_model", lambda: active)
    cached = SimpleNamespace(
        scores=[
            {
                "code": "000001.SZ",
                "score": 0.8,
                "rank": 1,
                "factors": {},
                "confidence": 0.9,
            }
        ],
        asof_date=date(2026, 7, 23),
        intended_trade_date=date(2026, 7, 24),
        model_id="model",
        model_artifact_hash="hash",
        feature_set_id="v1",
        label_id="return_5d",
        data_version="2026-07-23",
        metrics_snapshot={"rank_ic": 0.18},
        scope_hash="scope",
        scope_label="portfolio",
        scope_metadata={"size": 1},
        created_at=datetime(2026, 7, 24),
        get_staleness_days=lambda: 3,
    )

    class _CacheQuery:
        def order_by(self, *args: str) -> _CacheQuery:
            return self

        def first(self) -> object:
            return cached

    from apps.alpha.infrastructure import models as alpha_models

    monkeypatch.setattr(
        alpha_models,
        "AlphaScoreCacheModel",
        SimpleNamespace(_default_manager=SimpleNamespace(filter=lambda **kwargs: _CacheQuery())),
    )
    result = provider._get_from_cache("csi300", date(2026, 7, 24), 10)
    assert result is not None
    assert result.status == "degraded"
    assert result.scores[0].model_artifact_hash == "hash"
    assert result.metadata["rank_ic"] == 0.18

    from apps.alpha.application import tasks as alpha_tasks

    monkeypatch.setattr(qlib_adapter.cache, "get", lambda key: "existing-task")
    assert provider._trigger_infer_task("csi300", date(2026, 7, 24), 10) == "queued"
    monkeypatch.setattr(qlib_adapter.cache, "get", lambda key: None)
    monkeypatch.setattr(provider, "_resolve_live_inference_queue", lambda: "qlib_infer")
    monkeypatch.setattr(
        alpha_tasks.qlib_predict_scores,
        "apply_async",
        lambda **kwargs: SimpleNamespace(id="task-2"),
    )
    stored: list[tuple[str, object]] = []
    monkeypatch.setattr(
        qlib_adapter.cache,
        "set",
        lambda key, value, timeout: stored.append((key, value)),
    )
    assert provider._trigger_infer_task("csi300", date(2026, 7, 24), 10) == "queued"
    assert stored[0][1] == "task-2"

    model_file = tmp_path / "loaded.pkl"
    model_file.write_bytes(pickle.dumps({"model": 1}))
    assert provider.load_model(str(model_file)) is True
    assert provider._model == {"model": 1}
    assert provider.load_model(str(tmp_path / "missing.pkl")) is False

    missing_provider = QlibAlphaProvider(
        provider_uri=str(tmp_path / "missing-data"),
        model_path=str(tmp_path),
    )
    assert missing_provider.health_check().value == "unavailable"


def test_train_command_routes_sync_and_async_through_canonical_task(monkeypatch) -> None:
    """CLI options become model-specific task config without a shadow training path."""
    command = train_command.Command(stdout=StringIO())
    captured_sync: dict[str, object] = {}
    monkeypatch.setattr(
        train_command.qlib_train_model,
        "run",
        lambda **kwargs: captured_sync.update(kwargs)
        or {"artifact_hash": "hash", "ic": 0.2, "icir": 1.1},
    )
    command.handle(
        **{
            "name": "model",
            "model_type": "LGBModel",
            "universe": "csi300",
            "start_date": "2026-01-01",
            "end_date": "2026-07-24",
            "feature_set_id": "alpha158",
            "label_id": "return_5d",
            "learning_rate": 0.1,
            "epochs": 50,
            "activate": True,
            "force": False,
            "async_mode": False,
            "model_path": "/models",
        }
    )
    sync_config = captured_sync["train_config"]
    assert isinstance(sync_config, dict)
    assert sync_config["model_params"] == {
        "learning_rate": 0.1,
        "num_boost_round": 50,
    }
    assert sync_config["feature_set_id"] == "alpha158"
    assert sync_config["activate"] is True

    captured_async: dict[str, object] = {}
    monkeypatch.setattr(
        train_command.qlib_train_model,
        "apply_async",
        lambda **kwargs: captured_async.update(kwargs) or SimpleNamespace(id="task-3"),
    )
    command.handle(
        **{
            "name": "neural-model",
            "model_type": "LSTMModel",
            "universe": None,
            "start_date": "2026-01-01",
            "end_date": "2026-07-24",
            "feature_set_id": None,
            "label_id": None,
            "learning_rate": 0.001,
            "epochs": 10,
            "activate": False,
            "force": False,
            "async_mode": True,
            "model_path": None,
        }
    )
    assert captured_async["queue"] == "qlib_train"
    async_kwargs = captured_async["kwargs"]
    assert isinstance(async_kwargs, dict)
    async_config = async_kwargs["train_config"]
    assert async_config["model_params"] == {"lr": 0.001, "n_epochs": 10}

    with pytest.raises(CommandError, match="不可覆盖"):
        command.handle(
            name="model",
            model_type="LGBModel",
            force=True,
        )

    parser = command.create_parser("manage.py", "train_qlib_model")
    parsed = parser.parse_args(["--name", "sample"])
    assert parsed.name == "sample"


def test_alpha_admin_forms_artifact_storage_and_validation(monkeypatch, tmp_path) -> None:
    """Admin import validates JSON and produces reproducible metadata before activation."""
    invalid_file = alpha_admin.QlibModelImportForm(
        data={
            "model_name": "sample",
            "model_type": "LGBModel",
            "universe": "csi300",
            "feature_set_id": "v1",
            "label_id": "return_5d",
            "data_version": "2026-07-24",
            "train_config": "[]",
        },
        files={"model_file": SimpleUploadedFile("model.txt", b"bad")},
    )
    assert invalid_file.is_valid() is False
    assert "model_file" in invalid_file.errors
    assert "train_config" in invalid_file.errors
    malformed = alpha_admin.QlibModelImportForm(
        data={
            "model_name": "sample",
            "model_type": "LGBModel",
            "universe": "csi300",
            "feature_set_id": "v1",
            "label_id": "return_5d",
            "data_version": "2026-07-24",
            "train_config": "{bad",
        },
        files={"model_file": SimpleUploadedFile("model.pkl", b"bad")},
    )
    assert malformed.is_valid() is False
    assert "JSON 解析失败" in str(malformed.errors["train_config"])
    unsafe_name = alpha_admin.QlibModelImportForm(
        data={
            "model_name": "../outside",
            "model_type": "LGBModel",
            "universe": "csi300",
            "feature_set_id": "v1",
            "label_id": "return_5d",
            "data_version": "2026-07-24",
            "train_config": "{}",
        },
        files={"model_file": SimpleUploadedFile("model.pkl", b"bad")},
    )
    assert unsafe_name.is_valid() is False
    assert "model_name" in unsafe_name.errors
    reserved_name = alpha_admin.QlibModelImportForm(
        data={
            "model_name": "NUL.pkl",
            "model_type": "LGBModel",
            "universe": "csi300",
            "feature_set_id": "v1",
            "label_id": "return_5d",
            "data_version": "2026-07-24",
            "train_config": "{}",
        },
        files={"model_file": SimpleUploadedFile("model.pkl", b"bad")},
    )
    assert reserved_name.is_valid() is False
    assert "model_name" in reserved_name.errors

    train_form = alpha_admin.QlibModelTrainForm(
        data={
            "model_name": "sample",
            "model_type": "LGBModel",
            "universe": "csi300",
            "start_date": "2026-01-01",
            "end_date": "2026-07-24",
            "feature_set_id": "v1",
            "label_id": "return_5d",
            "learning_rate": 0.1,
            "epochs": 2,
            "model_params": '{"loss": "mse"}',
            "extra_train_config": "{}",
        }
    )
    assert train_form.is_valid() is True
    assert train_form.cleaned_data["model_params"] == {"loss": "mse"}
    invalid_train = alpha_admin.QlibModelTrainForm(
        data={
            "model_name": "sample",
            "model_type": "LGBModel",
            "universe": "csi300",
            "start_date": "2026-01-01",
            "end_date": "2026-07-24",
            "feature_set_id": "v1",
            "label_id": "return_5d",
            "learning_rate": 0.1,
            "epochs": 2,
            "model_params": "[]",
            "extra_train_config": "{bad",
        }
    )
    assert invalid_train.is_valid() is False
    assert "model_params" in invalid_train.errors
    assert "extra_train_config" in invalid_train.errors

    monkeypatch.setattr(
        "core.integration.runtime_settings.get_runtime_qlib_config",
        lambda: {
            "enabled": True,
            "provider_uri": str(tmp_path),
            "model_path": str(tmp_path),
        },
    )
    admin_instance = alpha_admin.QlibModelRegistryAdmin(
        alpha_admin.QlibModelRegistryModel,
        AdminSite(),
    )
    payload = pickle.dumps({"model": "stable"})
    uploaded = SimpleUploadedFile("model.pkl", payload)
    digest = admin_instance._hash_uploaded_file(uploaded)
    stored = admin_instance._store_uploaded_model(uploaded, "sample", digest)
    with pytest.raises(ValueError, match="model_name"):
        admin_instance._store_uploaded_model(uploaded, "../outside", digest)
    admin_instance._write_metadata_files(
        stored,
        "sample",
        digest,
        "2026-07-24",
        {"source": "test"},
        {"ic": 0.2},
    )
    assert stored.read_bytes() == payload
    assert (stored.parent / "metrics.json").exists()
    assert admin_instance._model_root() == tmp_path
    assert admin_instance.artifact_hash_short(SimpleNamespace(artifact_hash=digest)).endswith("...")

    _install_fake_qlib(monkeypatch)
    monkeypatch.setattr(
        "core.integration.runtime_settings.get_runtime_qlib_config",
        lambda: {"enabled": True, "provider_uri": str(tmp_path)},
    )
    monkeypatch.setattr(
        alpha_admin,
        "_execute_qlib_prediction",
        lambda **kwargs: [{"code": "S00", "score": 0.5}],
    )
    result = admin_instance._run_validation(
        SimpleNamespace(
            model_path=str(stored),
            universe="csi300",
        )
    )
    assert result["passed"] is True, result
    assert result["sample_scores"][0]["code"] == "S00"

    monkeypatch.setattr(
        alpha_admin.pickle,
        "load",
        lambda _file: (_ for _ in ()).throw(ValueError("token=should-not-appear")),
    )
    failed_result = admin_instance._run_validation(
        SimpleNamespace(
            model_path=str(stored),
            universe="csi300",
        )
    )
    pickle_detail = next(
        check["detail"] for check in failed_result["checks"] if check["label"] == "pickle 加载"
    )
    assert "ValueError" in pickle_detail
    assert "should-not-appear" not in pickle_detail


def test_alpha_monitoring_tasks_publish_metrics_drift_reports_and_cleanup(monkeypatch) -> None:
    """Monitoring tasks derive metrics from repositories and keep cleanup auditable."""
    from apps.alpha.application import monitoring_tasks

    gauges: list[tuple[str, float, object]] = []
    metric_runtime = SimpleNamespace(
        registry=SimpleNamespace(
            set_gauge=lambda name, value, labels=None: gauges.append((name, value, labels))
        ),
        log_metrics=lambda: None,
        record_coverage=lambda scored, universe: gauges.append(
            ("alpha_coverage_ratio", scored / universe, None)
        ),
        record_ic_metrics=lambda current, history, window: gauges.append(("ic", current, window)),
        get_metrics_json=lambda: {"coverage": 0.5},
    )
    monkeypatch.setattr(monitoring_tasks, "get_alpha_metrics", lambda: metric_runtime)
    monkeypatch.setattr(
        monitoring_tasks,
        "get_alpha_runtime_alert_manager",
        lambda: SimpleNamespace(evaluate_all=lambda: ["IC drift"]),
    )
    assert monitoring_tasks.evaluate_alerts.run()["count"] == 1

    cache_rows = [
        SimpleNamespace(
            status="available",
            get_staleness_days=lambda: 1,
            universe_id="csi300",
            intended_trade_date=date(2026, 7, index + 1),
        )
        for index in range(20)
    ]
    cache_repo = SimpleNamespace(
        list_recent_provider_caches=lambda **kwargs: cache_rows[:2],
        get_latest_cache_for_universe=lambda **kwargs: SimpleNamespace(
            scores=[{"code": "S00"}],
            scope_metadata={"pool_size": 2},
            metrics_snapshot={},
        ),
        list_caches_for_model=lambda **kwargs: cache_rows,
        list_today_cache_rows=lambda today: [
            {"provider_source": "qlib", "status": "available"},
            {"provider_source": "qlib", "status": "degraded"},
        ],
        archive_before=lambda cutoff: {"archived_count": 3},
        cleanup_before=lambda cutoff: 4,
    )
    registry_repo = SimpleNamespace(
        get_active_model=lambda: SimpleNamespace(artifact_hash="hash"),
        count_activations_on=lambda today: 2,
    )
    monkeypatch.setattr(monitoring_tasks, "_cache_repository", cache_repo)
    monkeypatch.setattr(monitoring_tasks, "_registry_repository", registry_repo)
    updated = monitoring_tasks.update_provider_metrics.run()
    assert updated["status"] == "success"
    assert updated["coverage_universe_count"] == 2
    assert any(name == "alpha_coverage_ratio" for name, _, _ in gauges)

    monkeypatch.setattr(
        monitoring_tasks,
        "calculate_rolling_metrics",
        lambda **kwargs: [SimpleNamespace(ic=0.1 + index / 100) for index in range(20)],
    )
    drift = monitoring_tasks.calculate_ic_drift.run()
    assert drift["status"] == "success"
    assert drift["current_ic"] == pytest.approx(0.29)
    assert drift["historical_mean"] == pytest.approx(0.19)
    assert drift["history_count"] == 19

    report = monitoring_tasks.generate_daily_report.run()
    assert report["cache_records"] == 2
    assert report["provider_stats"]["qlib"] == {"count": 2, "available": 1}
    cleanup = monitoring_tasks.cleanup_old_metrics.run(30)
    assert cleanup["deleted_count"] == 4
    assert cleanup["archive"]["archived_count"] == 3
    with pytest.raises(ValueError, match="正整数"):
        monitoring_tasks.cleanup_old_metrics.run(0)


def test_alpha_queue_monitor_does_not_report_unknown_lag_as_zero(monkeypatch) -> None:
    """Celery inspect failures remain unavailable instead of publishing false zero lag."""
    from apps.alpha.application import monitoring_tasks

    recorded: list[tuple[str, int]] = []
    monkeypatch.setattr(
        monitoring_tasks,
        "get_alpha_metrics",
        lambda: SimpleNamespace(
            record_queue_lag=lambda queue, count: recorded.append((queue, count))
        ),
    )
    monkeypatch.setattr(
        monitoring_tasks,
        "current_app",
        SimpleNamespace(
            control=SimpleNamespace(
                inspect=lambda: SimpleNamespace(reserved=lambda: None),
            )
        ),
    )

    unavailable = monitoring_tasks.check_queue_lag.run()

    assert unavailable["status"] == "unavailable"
    assert unavailable["reason"] == "no_worker_response"
    assert recorded == []

    monkeypatch.setattr(
        monitoring_tasks,
        "current_app",
        SimpleNamespace(
            control=SimpleNamespace(
                inspect=lambda: SimpleNamespace(
                    reserved=lambda: {
                        "worker-1": [
                            {"delivery_info": {"routing_key": "qlib_infer"}},
                            {"delivery_info": {"routing_key": "other"}},
                        ]
                    }
                ),
            )
        ),
    )
    available = monitoring_tasks.check_queue_lag.run()

    assert available["status"] == "success"
    assert recorded == [("qlib_infer", 1), ("qlib_train", 0)]
