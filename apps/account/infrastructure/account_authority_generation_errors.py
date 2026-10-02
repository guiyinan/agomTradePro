"""Stable failures for PostgreSQL Account authority generation fencing."""


class AccountAuthorityGenerationUnavailable(RuntimeError):
    """The generation proof or final fence cannot be trusted."""


class AccountAuthorityGenerationCoverageError(AccountAuthorityGenerationUnavailable):
    """The configured source-table trigger coverage or singleton row is incomplete."""


class AccountAuthorityGenerationChanged(AccountAuthorityGenerationUnavailable):
    """A source-ledger statement committed after the supplied proof was read."""


__all__ = [
    "AccountAuthorityGenerationChanged",
    "AccountAuthorityGenerationCoverageError",
    "AccountAuthorityGenerationUnavailable",
]
