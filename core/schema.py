"""Project-level drf-spectacular schema helpers."""

from __future__ import annotations

import re
from typing import Any

from django.db import models
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import (
    OpenApiParameter,
    build_basic_type,
    build_parameter_type,
    build_serializer_context,
    follow_model_field_lookup,
    resolve_django_path_parameter,
    resolve_regex_path_parameter,
)
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework.generics import GenericAPIView
from rest_framework.serializers import Serializer
from rest_framework.views import APIView


class EmptyResponseSerializer(Serializer):
    """Fallback object schema for APIViews without explicit serializers."""


@extend_schema_field(OpenApiTypes.STR)
def _string_schema_hint(value: Any) -> str:
    """Provide a stable string hint for schema-only serializer method fields."""
    return str(value)


def api_only_endpoints_preprocessing_hook(endpoints: list[tuple]) -> list[tuple]:
    """Keep only canonical /api/ endpoints in the generated OpenAPI schema."""
    return [endpoint for endpoint in endpoints if endpoint[0].startswith("/api/")]


class AgomAutoSchema(AutoSchema):
    """Project-specific AutoSchema with better fallbacks for legacy views."""

    _INT_PATH_PARAMS = {
        "id",
        "account_id",
        "asset_id",
        "backtest_id",
        "category_id",
        "doc_id",
        "event_id",
        "grant_id",
        "indicator_id",
        "log_id",
        "portfolio_id",
        "position_id",
        "record_id",
        "report_id",
        "rule_id",
        "source_id",
        "summary_id",
        "token_id",
        "transaction_id",
        "user_id",
        "validation_id",
    }

    def get_operation_id(self) -> str:
        """Generate stable operation IDs from the full canonical API path."""
        normalized = self.path.strip("/") or "root"
        normalized = normalized.replace("-", "_").replace("/", "_")
        normalized = re.sub(r"{([^}]+)}", r"by_\1", normalized)
        normalized = re.sub(r"__+", "_", normalized).strip("_")
        method = self.method.lower()
        return f"{normalized}_{method}"

    def _get_serializer(self):  # type: ignore[override]
        """Fallback to a generic object schema instead of dropping APIViews."""
        view = self.view
        context = build_serializer_context(view)

        try:
            if isinstance(view, GenericAPIView):
                if view.__class__.get_serializer == GenericAPIView.get_serializer:
                    serializer_class = view.get_serializer_class()
                    if serializer_class is not None:
                        return serializer_class(context=context)
                return view.get_serializer(context=context)

            if isinstance(view, APIView):
                if callable(getattr(view, "get_serializer", None)):
                    return view.get_serializer(context=context)
                if callable(getattr(view, "get_serializer_class", None)):
                    serializer_class = view.get_serializer_class()
                    if serializer_class is not None:
                        return serializer_class(context=context)
                serializer_class = getattr(view, "serializer_class", None)
                if serializer_class is not None:
                    return serializer_class() if isinstance(serializer_class, type) else serializer_class
                return EmptyResponseSerializer
        except Exception:
            serializer_class = getattr(view, "serializer_class", None)
            if serializer_class is not None:
                try:
                    return serializer_class() if isinstance(serializer_class, type) else serializer_class
                except Exception:
                    pass
            return EmptyResponseSerializer

        return EmptyResponseSerializer

    def _resolve_path_parameters(self, variables):  # type: ignore[override]
        """Infer integer path params more aggressively to avoid string fallbacks."""
        parameters = []
        model = getattr(getattr(self.view, "queryset", None), "model", None)

        for variable in variables:
            schema = build_basic_type(OpenApiTypes.STR)
            description = ""

            resolved = resolve_django_path_parameter(
                self.path_regex,
                variable,
                self.map_renderers("format"),
            ) or resolve_regex_path_parameter(self.path_regex, variable)

            if resolved:
                schema = resolved["schema"]
            elif variable in self._INT_PATH_PARAMS:
                schema = build_basic_type(OpenApiTypes.INT)
            elif model is not None:
                try:
                    model_field_name = (
                        getattr(self.view, "lookup_field", variable)
                        if getattr(self.view, "lookup_url_kwarg", None) == variable
                        else variable
                    )
                    model_field = follow_model_field_lookup(model, model_field_name)
                    schema = self._map_model_field(model_field, direction=None)
                    if "description" not in schema and isinstance(model_field, models.Field) and model_field.primary_key:
                        description = f"Primary key of {model._meta.object_name}"
                except Exception:
                    pass

            parameters.append(
                build_parameter_type(
                    name=variable,
                    location=OpenApiParameter.PATH,
                    description=description,
                    schema=schema,
                )
            )

        return parameters
