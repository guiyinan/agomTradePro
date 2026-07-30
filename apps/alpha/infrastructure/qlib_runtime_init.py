"""Qlib initialization, compatibility, and runtime metadata helpers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from importlib import import_module
from pathlib import Path, PureWindowsPath
from typing import Any, TypeAlias, cast

from apps.alpha.infrastructure.qlib_builder import normalize_qlib_symbol
from apps.alpha.infrastructure.scientific_runtime import get_pandas
from core.integration.runtime_settings import get_runtime_qlib_config as _read_runtime_qlib_config

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def _normalize_qlib_region(region_value: object) -> str:
    """Normalize runtime region values for qlib.init()."""
    try:
        from qlib.constant import REG_CN, REG_US
    except Exception:
        REG_CN = "cn"
        REG_US = "us"

    value = str(region_value or "").strip()
    lowered = value.lower()
    if lowered in {"", "cn", "reg_cn", "china"}:
        return str(REG_CN)
    if lowered in {"us", "reg_us"}:
        return str(REG_US)
    return value


def _normalize_calendar_date(value: object) -> date | None:
    """Convert qlib calendar entries to Python dates."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    date_method = getattr(value, "date", None)
    if callable(date_method):
        converted = cast(Callable[[], object], date_method)()
        if isinstance(converted, date):
            return converted
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _normalize_qlib_instrument_code(raw_code: str) -> str:
    """Convert app-level stock codes into qlib instrument ids when needed."""
    normalized = str(raw_code or "").strip()
    if not normalized:
        return normalized
    if "." in normalized:
        return normalize_qlib_symbol(normalized)
    if normalized[:2].upper() in {"SH", "SZ", "BJ"}:
        return normalized.upper()
    return normalized


def _normalize_qlib_instrument_list(raw_codes: list[str] | tuple[str, ...]) -> list[str]:
    """Normalize and de-duplicate qlib instrument codes while keeping order."""
    normalized_codes: list[str] = []
    seen: set[str] = set()
    for raw_code in raw_codes:
        normalized_code = _normalize_qlib_instrument_code(str(raw_code))
        if not normalized_code or normalized_code in seen:
            continue
        normalized_codes.append(normalized_code)
        seen.add(normalized_code)
    return normalized_codes


def _install_qlib_pandas_compat() -> None:
    """Patch known qlib+pandas MultiIndex incompatibilities used by Alpha360 on local runtime."""
    if getattr(_install_qlib_pandas_compat, "_installed", False):
        return

    pd = cast(Callable[[], Any], get_pandas)()
    import qlib.data as qlib_data
    import qlib.data.data as qlib_data_module
    import qlib.data.dataset.processor as qlib_processor
    import qlib.data.dataset.utils as qlib_dataset_utils
    import qlib.utils.paral as qlib_paral
    from qlib.config import C

    original_datetime_groupby_apply = qlib_paral.datetime_groupby_apply
    original_fetch_df_by_index = qlib_dataset_utils.fetch_df_by_index

    def safe_datetime_groupby_apply(
        df: Any,
        apply_func: Any,
        axis: int = 0,
        level: str = "datetime",
        resample_rule: str = "ME",
        n_jobs: int = -1,
    ) -> Any:
        try:
            return original_datetime_groupby_apply(
                df,
                apply_func,
                axis=axis,
                level=level,
                resample_rule=resample_rule,
                n_jobs=1,
            )
        except TypeError as exc:
            if "DatetimeIndex" not in str(exc):
                raise
            if isinstance(apply_func, str):
                return getattr(df.groupby(axis=axis, level=level, group_keys=False), apply_func)()
            return df.groupby(level=level, group_keys=False).apply(apply_func)

    def safe_fetch_df_by_index(
        df: Any,
        selector: Any,
        level: str | None,
        fetch_orig: bool = True,
    ) -> Any:
        try:
            return original_fetch_df_by_index(df, selector, level, fetch_orig=fetch_orig)
        except KeyError as exc:
            if "are in the [index]" not in str(exc):
                raise
            if level is None or isinstance(selector, pd.MultiIndex):
                return df.loc(axis=0)[selector]
            level_idx = qlib_dataset_utils.get_level_index(df, level)
            level_values = df.index.get_level_values(level_idx)
            if isinstance(selector, slice):
                mask = pd.Series(True, index=df.index)
                if selector.start is not None:
                    mask &= level_values >= selector.start
                if selector.stop is not None:
                    mask &= level_values <= selector.stop
                return df[mask.to_numpy()]
            if isinstance(selector, list | tuple | set | pd.Index):
                return df[level_values.isin(list(selector))]
            return df[level_values == selector]

    def safe_features(
        instruments: Any,
        fields: Any,
        start_time: Any = None,
        end_time: Any = None,
        freq: str = "day",
        disk_cache: Any = None,
        inst_processors: Any = None,
    ) -> Any:
        return qlib_data_module.DatasetD.dataset(
            instruments,
            list(fields),
            start_time,
            end_time,
            freq,
            inst_processors=[] if inst_processors is None else inst_processors,
        )

    qlib_paral.datetime_groupby_apply = safe_datetime_groupby_apply
    qlib_processor.datetime_groupby_apply = safe_datetime_groupby_apply
    qlib_dataset_utils.fetch_df_by_index = safe_fetch_df_by_index
    qlib_processor.fetch_df_by_index = safe_fetch_df_by_index
    qlib_data.D.features = safe_features
    C.kernels = 1
    C.joblib_backend = "threading"
    _install_qlib_pandas_compat.__dict__["_installed"] = True


def _get_qlib_data_latest_date() -> date | None:
    """Inspect the local qlib dataset and return its latest trading date."""
    import qlib
    from qlib.data import D

    qlib_config = _get_runtime_qlib_config()
    provider_uri = qlib_config.get("provider_uri", "~/.qlib/qlib_data/cn_data")
    region = _normalize_qlib_region(qlib_config.get("region", "CN"))

    if not hasattr(_get_qlib_data_latest_date, "_qlib_initialized"):
        qlib.init(provider_uri=provider_uri, region=region)
        _get_qlib_data_latest_date.__dict__["_qlib_initialized"] = True

    calendar = D.calendar(start_time="2000-01-01", end_time="2100-12-31")
    if len(calendar) == 0:
        return None
    return _normalize_calendar_date(calendar[-1])


def _build_outdated_qlib_reason(trade_date: date) -> str | None:
    """Return a clear reason when local qlib data is too old for the requested trade date."""
    latest_data_date = _get_qlib_data_latest_date()
    if latest_data_date is None:
        return "本地 Qlib 数据目录为空，无法执行实时推理"
    if trade_date > latest_data_date + timedelta(days=10):
        return (
            f"本地 Qlib 数据最新交易日为 {latest_data_date.isoformat()}，"
            f"早于请求交易日 {trade_date.isoformat()}，请先同步 Qlib 数据"
        )
    return None


def _build_qlib_runtime_failure_reason(exc: Exception) -> str:
    """Return a user-facing reason when local qlib runtime inspection fails."""
    if isinstance(exc, ModuleNotFoundError) and getattr(exc, "name", None) == "qlib":
        return "Qlib 未安装，无法检查本地数据目录，请安装 pyqlib 或复用历史缓存"

    if "No module named 'qlib'" in str(exc):
        return "Qlib 未安装，无法检查本地数据目录，请安装 pyqlib 或复用历史缓存"

    return f"读取本地 Qlib 数据状态失败: {exc}"


def _get_runtime_qlib_config() -> dict[str, Any]:
    """Return runtime qlib config through config-center owned application service."""

    return _read_runtime_qlib_config()


def _parse_universe_list(raw_universes: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalize scheduled universe configuration."""
    if raw_universes is None:
        return ["csi300"]
    if isinstance(raw_universes, str):
        return [item.strip().lower() for item in raw_universes.split(",") if item.strip()]
    return [str(item).strip().lower() for item in raw_universes if str(item).strip()]


def _cache_is_fresh_for_trade_date(cache_row: Any | None, trade_date: date) -> bool:
    """Return whether one qlib cache row already satisfies same-day scoped inference."""
    if cache_row is None or not getattr(cache_row, "scores", None):
        return False
    return (
        getattr(cache_row, "status", "") == "available"
        and getattr(cache_row, "asof_date", None) == trade_date
    )


def _extract_model_filename(model_path: str) -> str:
    """Extract a model filename from either Windows or POSIX persisted paths."""
    return PureWindowsPath(model_path).name or Path(model_path).name


def _resolve_qlib_model_path(
    active_model: Any,
    qlib_config: dict[str, Any],
) -> Path:
    """Resolve persisted model paths across local and container deployments."""
    raw_model_path = str(active_model.model_path)
    model_path = Path(raw_model_path).expanduser()
    if model_path.exists():
        return model_path

    model_name = _extract_model_filename(raw_model_path)
    fallback_dir = qlib_config.get("model_path")
    if fallback_dir and model_name:
        fallback_path = Path(str(fallback_dir)).expanduser() / model_name
        if fallback_path.exists():
            return fallback_path

    return model_path


def _resolve_qlib_stock_list(
    data_api: Any,
    universe_id: str,
    start_time: str | None = None,
    end_time: str | None = None,
) -> list[str]:
    """Resolve a qlib universe config into a concrete instrument list."""
    instruments = data_api.instruments(market=universe_id)
    if not instruments:
        raise RuntimeError(f"未找到股票池: {universe_id}")

    if isinstance(instruments, dict):
        if not hasattr(data_api, "list_instruments"):
            raise RuntimeError(f"Qlib 数据接口不支持展开股票池: {universe_id}")
        stock_list = data_api.list_instruments(
            instruments,
            start_time=start_time,
            end_time=end_time,
            as_list=True,
        )
    else:
        stock_list = list(instruments)

    normalized = [str(stock).strip() for stock in stock_list if str(stock).strip()]
    if not normalized:
        if start_time or end_time:
            raise RuntimeError(
                f"股票池 {universe_id} 在 {start_time or '起始'} ~ {end_time or '结束'} 无可用成分股"
            )
        raise RuntimeError(f"股票池 {universe_id} 无可用成分股")

    return normalized


def _resolve_qlib_handler_class(feature_set_id: str | None) -> type[Any]:
    """Select the qlib data handler class that matches the model feature set."""
    try:
        handler_module = import_module("qlib.contrib.data.handler")
        alpha158 = cast(type[Any], vars(handler_module)["Alpha158"])
        alpha360 = cast(type[Any], vars(handler_module)["Alpha360"])
    except ModuleNotFoundError:

        class Alpha158Fallback:
            """Fallback handler marker used when pyqlib is not installed."""

        class Alpha360Fallback:
            """Fallback handler marker used when pyqlib is not installed."""

        alpha158 = Alpha158Fallback
        alpha360 = Alpha360Fallback

    normalized = _normalize_qlib_feature_set_id(feature_set_id)
    if normalized == "alpha158":
        return alpha158
    return alpha360


def _normalize_qlib_feature_set_id(feature_set_id: object) -> str:
    """Normalize supported aliases to the actual Qlib handler identifier."""

    normalized = str(feature_set_id or "alpha360").strip().lower()
    if normalized in {"alpha158", "158", "v158"}:
        return "alpha158"
    if normalized in {"alpha360", "360", "v360", "v1"}:
        return "alpha360"
    raise ValueError(f"不支持的 Qlib 特征集: {feature_set_id}")


def _make_json_safe(value: object) -> JsonValue:
    """Convert pandas/numpy/date/path values into JSON-safe payloads."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _make_json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_make_json_safe(item) for item in value]
    if hasattr(value, "isoformat") and not isinstance(value, str):
        try:
            isoformat_method = cast(Callable[[], object], cast(Any, value).isoformat)
            return _make_json_safe(isoformat_method())
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            item_method = cast(Callable[[], object], cast(Any, value).item)
            return _make_json_safe(item_method())
        except Exception:
            pass
    return str(value)


normalize_qlib_region = _normalize_qlib_region
normalize_calendar_date = _normalize_calendar_date
normalize_qlib_instrument_code = _normalize_qlib_instrument_code
normalize_qlib_instrument_list = _normalize_qlib_instrument_list
normalize_qlib_feature_set_id = _normalize_qlib_feature_set_id
install_qlib_pandas_compat = _install_qlib_pandas_compat
get_qlib_data_latest_date = _get_qlib_data_latest_date
build_outdated_qlib_reason = _build_outdated_qlib_reason
build_qlib_runtime_failure_reason = _build_qlib_runtime_failure_reason
get_runtime_qlib_config = _get_runtime_qlib_config
parse_universe_list = _parse_universe_list
cache_is_fresh_for_trade_date = _cache_is_fresh_for_trade_date
extract_model_filename = _extract_model_filename
resolve_qlib_model_path = _resolve_qlib_model_path
resolve_qlib_stock_list = _resolve_qlib_stock_list
resolve_qlib_handler_class = _resolve_qlib_handler_class
make_json_safe = _make_json_safe
