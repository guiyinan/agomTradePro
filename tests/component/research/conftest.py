"""Register shared PostgreSQL owner-authority fixtures before module imports."""

pytest_plugins = ("tests.component.account.test_owner_tenant_authority_v2_composition",)
