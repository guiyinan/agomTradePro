"""Explicit registry of focused Account ORM owner modules."""

from types import ModuleType

from . import account_actor_authority_raw_source_models_v3 as _actor_authority
from . import account_authority_generation_models as _authority_generation
from . import account_identity_raw_source_models as _identity_raw
from . import account_identity_snapshot_models as _identity_snapshot
from . import account_owner_assignment_actor_authority_source_v3_models as _owner_actor_authority
from . import account_owner_assignment_evidence_models as _owner_evidence
from . import account_owner_assignment_evidence_v2_models as _owner_evidence_v2
from . import account_owner_assignment_evidence_v3_models as _owner_evidence_v3
from . import account_owner_assignment_evidence_v4_models as _owner_evidence_v4
from . import account_owner_assignment_provenance_receipt_models as _owner_receipt
from . import account_owner_assignment_provenance_receipt_v2_models as _owner_receipt_v2
from . import account_owner_assignment_provenance_receipt_v3_models as _owner_receipt_v3
from . import account_owner_assignment_provenance_receipt_v4_models as _owner_receipt_v4
from . import account_owner_assignment_v5_models as _owner_assignment_v5
from . import account_rbac_authority_mutation_binding_v3_models as _rbac_mutation
from . import allocated_physical_account_row_observation_v3_models as _allocated_row
from . import canonical_account_creation_consumption_models as _creation_consumption
from . import canonical_account_creation_models as _creation
from . import canonical_account_ownership_reobservation_v1_models as _ownership_reobservation_v1
from . import classification_models as _classification
from . import documentation_models as _documentation
from . import identity_models as _identity
from . import owner_tenant_authority_v2_models as _owner_tenant_authority_v2
from . import owner_tenant_authority_v3_models as _owner_tenant_authority_v3
from . import physical_account_row_observation_models as _physical_row
from . import physical_account_row_observation_v2_models as _physical_row_v2
from . import portfolio_models as _portfolio
from . import simulated_corporate_action_write_grant_models as _simulated_action_write_grant
from . import single_owner_authority_policy_v1_models as _single_owner_policy
from . import trading_config_models as _trading_config

OWNER_MODULES: tuple[ModuleType, ...] = (
    _actor_authority,
    _authority_generation,
    _identity_raw,
    _identity_snapshot,
    _owner_actor_authority,
    _owner_evidence,
    _owner_evidence_v2,
    _owner_evidence_v3,
    _owner_evidence_v4,
    _owner_receipt,
    _owner_receipt_v2,
    _owner_receipt_v3,
    _owner_receipt_v4,
    _owner_assignment_v5,
    _rbac_mutation,
    _allocated_row,
    _creation_consumption,
    _creation,
    _ownership_reobservation_v1,
    _classification,
    _documentation,
    _identity,
    _physical_row,
    _physical_row_v2,
    _portfolio,
    _single_owner_policy,
    _simulated_action_write_grant,
    _owner_tenant_authority_v2,
    _owner_tenant_authority_v3,
    _trading_config,
)


__all__ = ("OWNER_MODULES",)
