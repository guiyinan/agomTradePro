"""Share the disposable owner authority schema fixtures across account tests."""

from tests.component.account.test_account_actor_authority_raw_source_publisher_postgres import (
    evid06_alias as evid06_alias,
)
from tests.component.account.test_account_owner_assignment_evidence_v4_repository import (
    assignment_alias as assignment_alias,
)
from tests.component.account.test_account_owner_assignment_provenance_receipt_v4_repository import (
    creation_alias as creation_alias,
)
from tests.component.account.test_account_owner_assignment_provenance_receipt_v4_repository import (
    receipt_alias as receipt_alias,
)
from tests.component.account.test_owner_tenant_authority_v2_composition import (
    owner_physical_alias as owner_physical_alias,
)
from tests.component.account.test_owner_tenant_authority_v2_repository import (
    owner_alias as owner_alias,
)
