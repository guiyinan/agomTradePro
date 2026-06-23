"""Compile-time Django contract export helpers for AgomTUI."""

from __future__ import annotations

import types as python_types
from dataclasses import MISSING, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Union, get_args, get_origin, get_type_hints

from django.apps import apps
from django.db import models
from django.utils import timezone
from django.utils.module_loading import import_string

DEFAULT_TUI_CONTRACT_APP_LABELS = ("terminal",)
DEFAULT_TUI_DOMAIN_CLASS_PATHS = (
    "apps.terminal.domain.entities.TerminalCommand",
    "apps.terminal.domain.entities.TerminalAuditEntry",
)


def export_tui_django_contract_manifest(
    *,
    app_labels: list[str] | None = None,
    model_paths: list[str] | None = None,
    domain_class_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Return one machine-readable contract manifest derived from Django code."""

    effective_app_labels = list(app_labels or DEFAULT_TUI_CONTRACT_APP_LABELS)
    effective_model_paths = list(model_paths or [])
    effective_domain_class_paths = list(
        domain_class_paths or DEFAULT_TUI_DOMAIN_CLASS_PATHS
    )
    model_classes = _resolve_model_classes(
        app_labels=effective_app_labels,
        model_paths=effective_model_paths,
    )
    return {
        "host_kind": "django",
        "generated_at": timezone.now().isoformat(),
        "app_labels": effective_app_labels,
        "models": [_serialize_model_contract(model_class) for model_class in model_classes],
        "aggregates": [
            _serialize_dataclass_contract(path)
            for path in effective_domain_class_paths
        ],
    }


def write_tui_django_contract_manifest(
    output_path: Path,
    *,
    app_labels: list[str] | None = None,
    model_paths: list[str] | None = None,
    domain_class_paths: list[str] | None = None,
    indent: int = 2,
) -> dict[str, Any]:
    """Write one JSON contract manifest to disk and return the payload."""

    payload = export_tui_django_contract_manifest(
        app_labels=app_labels,
        model_paths=model_paths,
        domain_class_paths=domain_class_paths,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        _dump_json(payload, indent=indent),
        encoding="utf-8",
    )
    return payload


def _resolve_model_classes(
    *,
    app_labels: list[str],
    model_paths: list[str],
) -> list[type[models.Model]]:
    if model_paths:
        resolved: list[type[models.Model]] = []
        for path in model_paths:
            model_class = import_string(path)
            if not issubclass(model_class, models.Model):
                raise TypeError(f"Resolved object is not a Django model: {path}")
            resolved.append(model_class)
        return resolved

    resolved = []
    for app_label in app_labels:
        app_config = apps.get_app_config(app_label)
        resolved.extend(list(app_config.get_models()))
    return resolved


def _serialize_model_contract(model_class: type[models.Model]) -> dict[str, Any]:
    model_meta = model_class._meta
    return {
        "app_label": str(model_meta.app_label),
        "model": str(model_meta.object_name),
        "module": f"{model_class.__module__}.{model_class.__name__}",
        "db_table": str(model_meta.db_table),
        "fields": [
            _serialize_model_field(field)
            for field in model_meta.get_fields()
            if _should_export_model_field(field)
        ],
    }


def _should_export_model_field(field: models.Field[Any, Any]) -> bool:
    if getattr(field, "auto_created", False) and not getattr(field, "concrete", False):
        return False
    return bool(getattr(field, "concrete", False) or getattr(field, "many_to_many", False))


def _serialize_model_field(field: models.Field[Any, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": str(field.name),
        "type": str(field.get_internal_type()),
        "null": bool(getattr(field, "null", False)),
        "blank": bool(getattr(field, "blank", False)),
        "primary_key": bool(getattr(field, "primary_key", False)),
        "unique": bool(getattr(field, "unique", False)),
        "db_index": bool(getattr(field, "db_index", False)),
        "editable": bool(getattr(field, "editable", True)),
    }
    verbose_name = str(getattr(field, "verbose_name", "") or "").strip()
    help_text = str(getattr(field, "help_text", "") or "").strip()
    if verbose_name and verbose_name != field.name:
        payload["verbose_name"] = verbose_name
    if help_text:
        payload["help_text"] = help_text
    max_length = getattr(field, "max_length", None)
    if max_length is not None:
        payload["max_length"] = int(max_length)
    decimal_places = getattr(field, "decimal_places", None)
    if decimal_places is not None:
        payload["decimal_places"] = int(decimal_places)
    max_digits = getattr(field, "max_digits", None)
    if max_digits is not None:
        payload["max_digits"] = int(max_digits)
    choices = list(getattr(field, "choices", []) or [])
    if choices:
        payload["choices"] = [
            {"value": _json_safe_scalar(value), "label": str(label)}
            for value, label in choices
        ]
    if getattr(field, "is_relation", False) and getattr(field, "related_model", None):
        related_model = field.related_model
        payload["related_model"] = (
            f"{related_model._meta.app_label}.{related_model.__name__}"
        )
    return payload


def _serialize_dataclass_contract(path: str) -> dict[str, Any]:
    cls = import_string(path)
    if not is_dataclass(cls):
        raise TypeError(f"Configured aggregate contract is not a dataclass: {path}")

    hints = get_type_hints(cls)
    payload_fields = []
    for dataclass_field in fields(cls):
        annotation = hints.get(dataclass_field.name, dataclass_field.type)
        normalized_type, required, options = _normalize_annotation(annotation)
        field_payload: dict[str, Any] = {
            "name": str(dataclass_field.name),
            "value_type": normalized_type,
            "required": required
            and dataclass_field.default is MISSING
            and dataclass_field.default_factory is MISSING,
        }
        if options:
            field_payload["options"] = options
        payload_fields.append(field_payload)

    return {
        "key": path,
        "entity": cls.__name__,
        "module": cls.__module__,
        "fields": payload_fields,
        "commands": [],
    }


def _normalize_annotation(annotation: Any) -> tuple[str, bool, list[Any]]:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin in (list, tuple, set):
        return "list", True, []
    if origin is dict:
        return "object", True, []
    if origin in (python_types.UnionType, Union):
        non_none_args = [arg for arg in args if arg is not type(None)]
        if len(non_none_args) == 1 and len(non_none_args) != len(args):
            value_type, _, options = _normalize_annotation(non_none_args[0])
            return value_type, False, options

    if isinstance(annotation, type):
        if issubclass(annotation, Enum):
            return (
                "string",
                True,
                [_json_safe_scalar(member.value) for member in annotation],
            )
        if annotation is bool:
            return "boolean", True, []
        if annotation is int:
            return "integer", True, []
        if annotation is float:
            return "float", True, []
        if annotation is Decimal:
            return "decimal", True, []
        if annotation is datetime:
            return "datetime", True, []
        if annotation is date:
            return "date", True, []
        if annotation in (dict,):
            return "object", True, []
        if annotation in (list, tuple, set):
            return "list", True, []
        if annotation is str:
            return "string", True, []

    return "string", True, []


def _json_safe_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _dump_json(payload: dict[str, Any], *, indent: int) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, indent=indent) + "\n"
