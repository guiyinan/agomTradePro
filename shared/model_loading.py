"""Pure technical helpers for resolving Django model classes."""

from importlib import import_module
from typing import Type

from django.apps import apps as django_apps
from django.db.models import Model


def resolve_model(app_label: str, model_name: str, fallback_module: str | None = None) -> Type[Model]:
    """Resolve a Django model from app registry, with optional import fallback."""
    try:
        return django_apps.get_model(app_label, model_name)
    except LookupError:
        if fallback_module is None:
            raise
        module = import_module(fallback_module)
        return getattr(module, model_name)
