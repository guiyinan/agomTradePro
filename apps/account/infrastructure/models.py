"""Compatibility exports from explicit, focused Account ORM owner modules."""

from typing import TYPE_CHECKING

from ._model_owner_registry import OWNER_MODULES as _OWNER_MODULES

if TYPE_CHECKING:
    from .account_actor_authority_raw_source_models_v3 import *  # noqa: F403
    from .account_authority_generation_models import *  # noqa: F403
    from .account_identity_raw_source_models import *  # noqa: F403
    from .account_identity_snapshot_models import *  # noqa: F403
    from .account_owner_assignment_actor_authority_source_v3_models import *  # noqa: F403
    from .account_owner_assignment_evidence_models import *  # noqa: F403
    from .account_owner_assignment_evidence_v2_models import *  # noqa: F403
    from .account_owner_assignment_evidence_v3_models import *  # noqa: F403
    from .account_owner_assignment_evidence_v4_models import *  # noqa: F403
    from .account_owner_assignment_provenance_receipt_models import *  # noqa: F403
    from .account_owner_assignment_provenance_receipt_v2_models import *  # noqa: F403
    from .account_owner_assignment_provenance_receipt_v3_models import *  # noqa: F403
    from .account_owner_assignment_provenance_receipt_v4_models import *  # noqa: F403
    from .account_owner_assignment_v5_models import *  # noqa: F403
    from .account_rbac_authority_mutation_binding_v3_models import *  # noqa: F403
    from .allocated_physical_account_row_observation_v3_models import *  # noqa: F403
    from .canonical_account_creation_consumption_models import *  # noqa: F403
    from .canonical_account_creation_models import *  # noqa: F403
    from .canonical_account_ownership_reobservation_v1_models import *  # noqa: F403
    from .classification_models import *  # noqa: F403
    from .documentation_models import *  # noqa: F403
    from .identity_models import *  # noqa: F403
    from .owner_tenant_authority_v2_models import *  # noqa: F403
    from .owner_tenant_authority_v3_models import *  # noqa: F403
    from .physical_account_row_observation_models import *  # noqa: F403
    from .physical_account_row_observation_v2_models import *  # noqa: F403
    from .portfolio_models import *  # noqa: F403
    from .simulated_corporate_action_write_grant_models import *  # noqa: F403
    from .single_owner_authority_policy_v1_models import *  # noqa: F403
    from .trading_config_models import *  # noqa: F403

__all__: list[str] = []
for _owner_module in _OWNER_MODULES:
    for _export_name in _owner_module.__all__:
        globals()[_export_name] = getattr(_owner_module, _export_name)
        __all__.append(_export_name)

del _owner_module, _export_name
