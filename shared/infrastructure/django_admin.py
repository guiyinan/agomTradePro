"""Runtime-safe generic bases for strongly typed Django Admin classes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Generic, TypeVar

from django import forms
from django.contrib import admin
from django.db.models import Model

AdminModelT = TypeVar("AdminModelT", bound=Model)

if TYPE_CHECKING:

    class TypedModelAdmin(admin.ModelAdmin[AdminModelT], Generic[AdminModelT]):
        """Expose django-stubs' generic ModelAdmin contract to type checkers."""

    class TypedModelForm(forms.ModelForm[AdminModelT], Generic[AdminModelT]):
        """Expose django-stubs' generic ModelForm contract to type checkers."""

else:

    class TypedModelAdmin(admin.ModelAdmin, Generic[AdminModelT]):
        """Keep ModelAdmin subscriptable without requiring django-stubs at runtime."""

    class TypedModelForm(forms.ModelForm, Generic[AdminModelT]):
        """Keep ModelForm subscriptable without requiring django-stubs at runtime."""


__all__ = ["TypedModelAdmin", "TypedModelForm"]
