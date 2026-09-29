"""Transactional generation row for Account authority source ledgers."""

from __future__ import annotations

from django.db import models


class AccountAuthorityGenerationModel(models.Model):
    """One global MVCC generation advanced by source-ledger statement triggers."""

    singleton = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    generation = models.PositiveBigIntegerField(default=0)

    class Meta:
        app_label = "account"
        db_table = "account_authority_generation"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(singleton=1),
                name="acct_auth_gen_singleton_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(generation__gte=0),
                name="acct_auth_gen_nonnegative_ck",
            ),
        ]


__all__ = ["AccountAuthorityGenerationModel"]
