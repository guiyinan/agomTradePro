"""Config Center models for operator-managed outbound egress endpoints."""

from __future__ import annotations

from django.db import models


class EgressEndpointModel(models.Model):
    """One proxy endpoint whose credentials are stored by Config Center."""

    PROTOCOL_CHOICES = (
        ("http", "HTTP proxy"),
        ("https", "HTTPS proxy"),
    )

    name = models.CharField(max_length=120)
    region = models.CharField(max_length=40, db_index=True)
    protocol = models.CharField(max_length=12, choices=PROTOCOL_CHOICES, default="http")
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField()
    username_secret_ref = models.CharField(max_length=300, blank=True, default="")
    password_secret_ref = models.CharField(max_length=300, blank=True, default="")
    enabled = models.BooleanField(default=False, db_index=True)
    concurrency_limit = models.PositiveIntegerField(default=4)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "config_center_egress_endpoint"
        ordering = ("name", "id")

    def __str__(self) -> str:
        return f"{self.name} ({self.region})"


__all__ = ["EgressEndpointModel"]
