# 数据字典（Data Dictionary）

> 本文件由 `python scripts/build_data_dictionary.py` 自动生成，禁止手工编辑。 模型变更后请重新运行该命令，并通过 `python scripts/check_data_dictionary.py` 校验。

本文档是 `governance/data_dictionary.json` 的人读渲染，两者由同一份扫描数据生成，禁止单独维护。

## 概览

- App 数：42
- 模型数：597
- 字段数：9301

口径说明：仅覆盖 `apps/*/infrastructure/` 下的 `models.py`、`models/` 包与 `*_models.py`；字段为类体内显式赋值的 Django 字段，继承字段不展开，动态字段与隐式自增主键不在投影内。

## account

### AccountAuthorityGenerationModel

- 来源文件：`apps/account/infrastructure/account_authority_generation_models.py`
- 数据表：`account_authority_generation`
- 说明：One global MVCC generation advanced by source-ledger statement triggers.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `singleton` | `PositiveSmallIntegerField` |  |  | 1 |  |  |
| `generation` | `PositiveBigIntegerField` |  |  | 0 |  |  |

### AccountIdentityRawSourceModel

- 来源文件：`apps/account/infrastructure/account_identity_raw_source_models.py`
- 数据表：`account_identity_raw_source_ledger`
- 说明：One immutable actor-bound Account raw identity source ledger record.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `source_id` | `CharField` |  |  |  |  |  |
| `source_version` | `CharField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `owner_user_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `assignment_state` | `CharField` |  |  |  |  |  |
| `assignment_evidence_owner` | `CharField` | 是 |  |  |  |  |
| `assignment_evidence_artifact_type` | `CharField` | 是 |  |  |  |  |
| `assignment_evidence_id` | `CharField` | 是 |  |  |  |  |
| `assignment_evidence_version` | `CharField` | 是 |  |  |  |  |
| `assignment_evidence_content_hash` | `CharField` | 是 |  |  |  |  |
| `row_source_owner` | `CharField` |  |  |  |  |  |
| `row_source_artifact_type` | `CharField` |  |  |  |  |  |
| `row_source_id` | `CharField` |  |  |  |  |  |
| `row_source_version` | `CharField` |  |  |  |  |  |
| `row_source_content_hash` | `CharField` |  |  |  |  |  |
| `observed_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `row_source_valid_until` | `DateTimeField` |  |  |  |  |  |
| `ttl_valid_until` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `account_type` | `CharField` |  |  |  |  |  |
| `is_active` | `BooleanField` |  |  |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 | 是 |  |  |  |
| `root_claim_hash` | `CharField` | 是 | 是 |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `blocker_codes` | `JSONField` |  |  |  |  |  |
| `captured_actor_id` | `CharField` |  |  |  |  |  |
| `captured_actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `captured_actor_role` | `CharField` |  |  |  |  |  |
| `captured_actor_kind` | `CharField` |  |  |  |  |  |
| `captured_actor_is_staff` | `BooleanField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `actor_binding_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### AccountIdentitySnapshotModel

- 来源文件：`apps/account/infrastructure/account_identity_snapshot_models.py`
- 数据表：`account_identity_snapshot_ledger`
- 说明：One immutable actor-bound Account identity snapshot ledger record.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `source_id` | `CharField` |  |  |  |  |  |
| `source_version` | `CharField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `owner_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `account_type` | `CharField` |  |  |  |  |  |
| `is_active` | `BooleanField` |  |  |  |  |  |
| `provenance_kind` | `CharField` |  |  |  |  |  |
| `legacy_default_user_assignment` | `BooleanField` |  |  |  |  |  |
| `underlying_source_id` | `CharField` |  |  |  |  |  |
| `underlying_source_version` | `CharField` |  |  |  |  |  |
| `underlying_source_content_hash` | `CharField` |  |  |  |  |  |
| `underlying_source_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `underlying_source_valid_until` | `DateTimeField` |  |  |  |  |  |
| `ttl_valid_until` | `DateTimeField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `reclaim_receipt_owner` | `CharField` | 是 |  |  |  |  |
| `reclaim_receipt_artifact_type` | `CharField` | 是 |  |  |  |  |
| `reclaim_receipt_id` | `CharField` | 是 |  |  |  |  |
| `reclaim_receipt_version` | `CharField` | 是 |  |  |  |  |
| `reclaim_receipt_content_hash` | `CharField` | 是 |  |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 | 是 |  |  |  |
| `root_claim_hash` | `CharField` | 是 | 是 |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `blocker_codes` | `JSONField` |  |  |  |  |  |
| `issued_actor_id` | `CharField` |  |  |  |  |  |
| `issued_actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `issued_actor_role` | `CharField` |  |  |  |  |  |
| `issued_actor_kind` | `CharField` |  |  |  |  |  |
| `issued_actor_is_staff` | `BooleanField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `actor_binding_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### AccountOwnerAssignmentActorAuthoritySourceV3Model

- 来源文件：`apps/account/infrastructure/account_owner_assignment_actor_authority_source_v3_models.py`
- 数据表：`account_actor_authority_source_v3_ledger`
- 说明：Complete immutable projection of one Domain authority-source version.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `root_lock` | `ForeignKey` |  |  |  |  | AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel |
| `predecessor` | `OneToOneField` | 是 |  |  | self | self |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `must_not_execute` | `BooleanField` |  |  |  |  |  |
| `execution_allowed` | `BooleanField` |  |  |  |  |  |
| `source_id` | `CharField` |  |  |  |  |  |
| `source_version` | `CharField` |  |  |  |  |  |
| `principal_id` | `CharField` |  |  |  |  |  |
| `user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `authentication_context_id` | `CharField` |  |  |  |  |  |
| `authentication_context_version` | `CharField` |  |  |  |  |  |
| `authentication_context_identity_hash` | `CharField` |  |  |  |  |  |
| `authentication_context_content_hash` | `CharField` |  |  |  |  |  |
| `user_source_id` | `CharField` |  |  |  |  |  |
| `user_source_version` | `CharField` |  |  |  |  |  |
| `user_source_content_hash` | `CharField` |  |  |  |  |  |
| `rbac_source_id` | `CharField` |  |  |  |  |  |
| `rbac_source_version` | `CharField` |  |  |  |  |  |
| `rbac_source_content_hash` | `CharField` |  |  |  |  |  |
| `actor_id` | `CharField` |  |  |  |  |  |
| `is_authenticated` | `BooleanField` |  |  |  |  |  |
| `is_active` | `BooleanField` |  |  |  |  |  |
| `is_staff` | `BooleanField` |  |  |  |  |  |
| `is_superuser` | `BooleanField` |  |  |  |  |  |
| `rbac_role` | `CharField` |  |  |  |  |  |
| `authority_state` | `CharField` |  |  |  |  |  |
| `principal_authenticated_at` | `DateTimeField` |  |  |  |  |  |
| `principal_valid_until` | `DateTimeField` |  |  |  |  |  |
| `source_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `source_valid_until` | `DateTimeField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ttl_valid_until` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `root_claim_hash` | `CharField` | 是 | 是 |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 | 是 |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `principal_seal` | `CharField` |  |  |  |  |  |
| `authentication_context_seal` | `CharField` |  |  |  |  |  |
| `user_seal` | `CharField` |  |  |  |  |  |
| `rbac_seal` | `CharField` |  |  |  |  |  |
| `facts_seal` | `CharField` |  |  |  |  |  |
| `clock_seal` | `CharField` |  |  |  |  |  |
| `chain_seal` | `CharField` |  |  |  |  |  |
| `fixed_authority_seal` | `CharField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `recorded_by_service_id` | `CharField` |  |  |  |  |  |
| `recorded_by_role` | `CharField` |  |  |  |  |  |
| `recorded_by_kind` | `CharField` |  |  |  |  |  |
| `recorded_by_is_automated` | `BooleanField` |  |  |  |  |  |
| `recorder_binding_seal` | `CharField` |  |  |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### AccountOwnerAssignmentActorAuthoritySourceV3RootLockModel

- 来源文件：`apps/account/infrastructure/account_owner_assignment_actor_authority_source_v3_models.py`
- 数据表：`account_actor_authority_source_v3_root_lock`
- 说明：Candidate-independent serialization row for an empty source chain.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `source_id` | `CharField` |  | 是 |  |  |  |
| `root_claim_hash` | `CharField` |  | 是 |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### _GuardedModel

- 来源文件：`apps/account/infrastructure/account_owner_assignment_actor_authority_source_v3_models.py`
- 抽象模型：是

### AccountOwnerAssignmentAppendOnlyModel

- 来源文件：`apps/account/infrastructure/account_owner_assignment_evidence_models.py`
- 抽象模型：是
- 说明：Permit only one exact repository-claimed insert.

### AccountOwnerAssignmentEvidenceModel

- 来源文件：`apps/account/infrastructure/account_owner_assignment_evidence_models.py`
- 数据表：`account_owner_assignment_evidence`
- 说明：One immutable approved evidence record in a logical assignment chain.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `subject` | `OneToOneField` |  |  |  |  | AccountOwnerAssignmentSubjectModel |
| `subject_content_hash` | `CharField` |  | 是 |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `evidence_id` | `CharField` |  |  |  |  |  |
| `evidence_version` | `CharField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `assignment_state` | `CharField` |  |  |  |  |  |
| `assigned_owner_user_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `row_observation_owner` | `CharField` |  |  |  |  |  |
| `row_observation_artifact_type` | `CharField` |  |  |  |  |  |
| `row_observation_id` | `CharField` |  |  |  |  |  |
| `row_observation_version` | `CharField` |  |  |  |  |  |
| `row_observation_content_hash` | `CharField` |  |  |  |  |  |
| `provenance_kind` | `CharField` |  |  |  |  |  |
| `provenance_ref_owner` | `CharField` |  |  |  |  |  |
| `provenance_ref_artifact_type` | `CharField` |  |  |  |  |  |
| `provenance_ref_id` | `CharField` |  |  |  |  |  |
| `provenance_ref_version` | `CharField` |  |  |  |  |  |
| `provenance_ref_content_hash` | `CharField` |  |  |  |  |  |
| `claimant_actor_id` | `CharField` |  |  |  |  |  |
| `claimant_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `claimant_role` | `CharField` |  |  |  |  |  |
| `claimant_kind` | `CharField` |  |  |  |  |  |
| `claimant_is_staff` | `BooleanField` |  |  |  |  |  |
| `approved_actor_id` | `CharField` |  |  |  |  |  |
| `approved_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `approved_role` | `CharField` |  |  |  |  |  |
| `approved_kind` | `CharField` |  |  |  |  |  |
| `approved_is_staff` | `BooleanField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `approved_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 |  |  |  |  |
| `root_claim_hash` | `CharField` | 是 |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `blocker_codes` | `JSONField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### AccountOwnerAssignmentSubjectModel

- 来源文件：`apps/account/infrastructure/account_owner_assignment_evidence_models.py`
- 数据表：`account_owner_assignment_subject`
- 说明：Complete immutable row/provenance/claimant registration first winner.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `evidence_id` | `CharField` |  |  |  |  |  |
| `evidence_version` | `CharField` |  |  |  |  |  |
| `subject_identity_hash` | `CharField` |  | 是 |  |  |  |
| `row_owner` | `CharField` |  |  |  |  |  |
| `row_artifact_type` | `CharField` |  |  |  |  |  |
| `row_observation_id` | `CharField` |  |  |  |  |  |
| `row_observation_version` | `CharField` |  |  |  |  |  |
| `row_content_hash` | `CharField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `row_observed_at` | `DateTimeField` |  |  |  |  |  |
| `row_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `row_valid_until` | `DateTimeField` |  |  |  |  |  |
| `row_binding_hash` | `CharField` |  | 是 |  |  |  |
| `receipt_owner` | `CharField` |  |  |  |  |  |
| `receipt_artifact_type` | `CharField` |  |  |  |  |  |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `receipt_content_hash` | `CharField` |  |  |  |  |  |
| `provenance_kind` | `CharField` |  |  |  |  |  |
| `assignment_state` | `CharField` |  |  |  |  |  |
| `assigned_owner_user_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `receipt_account_namespace` | `CharField` |  |  |  |  |  |
| `receipt_account_id` | `CharField` |  |  |  |  |  |
| `receipt_underlying_namespace` | `CharField` |  |  |  |  |  |
| `receipt_underlying_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `receipt_row_id` | `CharField` |  |  |  |  |  |
| `receipt_row_version` | `CharField` |  |  |  |  |  |
| `receipt_row_content_hash` | `CharField` |  |  |  |  |  |
| `receipt_claimant_actor_id` | `CharField` |  |  |  |  |  |
| `receipt_claimant_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `receipt_claimant_role` | `CharField` |  |  |  |  |  |
| `receipt_claimant_kind` | `CharField` |  |  |  |  |  |
| `receipt_claimant_is_staff` | `BooleanField` |  |  |  |  |  |
| `receipt_issued_at` | `DateTimeField` |  |  |  |  |  |
| `receipt_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `receipt_valid_until` | `DateTimeField` |  |  |  |  |  |
| `provenance_binding_hash` | `CharField` |  | 是 |  |  |  |
| `claimant_actor_id` | `CharField` |  |  |  |  |  |
| `claimant_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `claimant_role` | `CharField` |  |  |  |  |  |
| `claimant_kind` | `CharField` |  |  |  |  |  |
| `claimant_is_staff` | `BooleanField` |  |  |  |  |  |
| `requested_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### AccountOwnerAssignmentEvidenceV2Model

- 来源文件：`apps/account/infrastructure/account_owner_assignment_evidence_v2_models.py`
- 数据表：`account_owner_assignment_evidence_v2_ledger`
- 说明：One independent staff approval over an exact registered subject.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `subject` | `OneToOneField` |  |  |  |  | AccountOwnerAssignmentSubjectV2Model |
| `subject_content_hash` | `CharField` |  | 是 |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `evidence_id` | `CharField` |  |  |  |  |  |
| `evidence_version` | `CharField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `assignment_state` | `CharField` |  |  |  |  |  |
| `assigned_owner_user_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `approved_actor_id` | `CharField` |  |  |  |  |  |
| `approved_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `approved_role` | `CharField` |  |  |  |  |  |
| `approved_kind` | `CharField` |  |  |  |  |  |
| `approved_is_staff` | `BooleanField` |  |  |  |  |  |
| `approved_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `approval_valid_until` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 |  |  |  |  |
| `account_root_claim_hash` | `CharField` | 是 |  |  |  |  |
| `underlying_root_claim_hash` | `CharField` | 是 |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `blocker_codes` | `JSONField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `subject_binding_seal` | `CharField` |  |  |  |  |  |
| `approver_binding_seal` | `CharField` |  |  |  |  |  |
| `mapping_binding_seal` | `CharField` |  |  |  |  |  |
| `fixed_authority_seal` | `CharField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### AccountOwnerAssignmentSubjectV2Model

- 来源文件：`apps/account/infrastructure/account_owner_assignment_evidence_v2_models.py`
- 数据表：`account_owner_assignment_subject_v2_ledger`
- 说明：One immutable registration winner containing both canonical upstreams.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `subject_id` | `CharField` |  |  |  |  |  |
| `subject_version` | `CharField` |  |  |  |  |  |
| `physical_observation_id` | `CharField` |  |  |  |  |  |
| `physical_observation_version` | `CharField` |  |  |  |  |  |
| `physical_identity_hash` | `CharField` |  |  |  |  |  |
| `physical_content_hash` | `CharField` |  |  |  |  |  |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `receipt_identity_hash` | `CharField` |  |  |  |  |  |
| `receipt_content_hash` | `CharField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `requested_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `upstream_binding_seal` | `CharField` |  |  |  |  |  |
| `fixed_authority_seal` | `CharField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### _AppendOnlyAccountOwnerAssignmentEvidenceV2Model

- 来源文件：`apps/account/infrastructure/account_owner_assignment_evidence_v2_models.py`
- 抽象模型：是
- 说明：Private claimed-insert and append-only behavior shared by both tables.

### AccountOwnerAssignmentEvidenceV3Model

- 来源文件：`apps/account/infrastructure/account_owner_assignment_evidence_v3_models.py`
- 数据表：`account_owner_assignment_evidence_v3_ledger`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `subject` | `OneToOneField` |  |  |  |  | AccountOwnerAssignmentSubjectV3Model |
| `subject_content_hash` | `CharField` |  | 是 |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `evidence_id` | `CharField` |  |  |  |  |  |
| `evidence_version` | `CharField` |  |  |  |  |  |
| `assignment_state` | `CharField` |  |  |  |  |  |
| `assigned_owner_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `claimant_actor_id` | `CharField` |  |  |  |  |  |
| `claimant_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `approved_actor_id` | `CharField` |  |  |  |  |  |
| `approved_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `approved_role` | `CharField` |  |  |  |  |  |
| `approved_kind` | `CharField` |  |  |  |  |  |
| `approved_is_staff` | `BooleanField` |  |  |  |  |  |
| `subject_requested_at` | `DateTimeField` |  |  |  |  |  |
| `subject_valid_until` | `DateTimeField` |  |  |  |  |  |
| `approved_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `approval_valid_until` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `account_root_claim_hash` | `CharField` |  | 是 |  |  |  |
| `underlying_root_claim_hash` | `CharField` |  | 是 |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `blocker_codes` | `JSONField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `subject_binding_seal` | `CharField` |  |  |  |  |  |
| `approver_binding_seal` | `CharField` |  |  |  |  |  |
| `mapping_binding_seal` | `CharField` |  |  |  |  |  |
| `fixed_authority_seal` | `CharField` |  |  |  |  |  |
| `header_seal` | `CharField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### AccountOwnerAssignmentSubjectV3Model

- 来源文件：`apps/account/infrastructure/account_owner_assignment_evidence_v3_models.py`
- 数据表：`account_owner_assignment_subject_v3_ledger`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `receipt` | `OneToOneField` |  |  |  | account.AccountOwnerAssignmentProvenanceReceiptV3Model | account.AccountOwnerAssignmentProvenanceReceiptV3Model |
| `binding` | `ForeignKey` |  |  |  | account.CanonicalAccountCreationBindingV2Model | account.CanonicalAccountCreationBindingV2Model |
| `creation_root` | `ForeignKey` |  |  |  | account.AllocatedPhysicalAccountRowObservationV3Model | account.AllocatedPhysicalAccountRowObservationV3Model |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `subject_id` | `CharField` |  |  |  |  |  |
| `subject_version` | `CharField` |  |  |  |  |  |
| `receipt_ref_id` | `CharField` |  |  |  |  |  |
| `receipt_ref_version` | `CharField` |  |  |  |  |  |
| `binding_ref_id` | `CharField` |  |  |  |  |  |
| `binding_ref_version` | `CharField` |  |  |  |  |  |
| `creation_root_ref_id` | `CharField` |  |  |  |  |  |
| `creation_root_ref_version` | `CharField` |  |  |  |  |  |
| `receipt_identity_hash` | `CharField` |  |  |  |  |  |
| `receipt_content_hash` | `CharField` |  |  |  |  |  |
| `binding_identity_hash` | `CharField` |  |  |  |  |  |
| `binding_content_hash` | `CharField` |  |  |  |  |  |
| `creation_root_identity_hash` | `CharField` |  |  |  |  |  |
| `creation_root_content_hash` | `CharField` |  |  |  |  |  |
| `binding_account_claim_hash` | `CharField` |  |  |  |  |  |
| `binding_underlying_claim_hash` | `CharField` |  |  |  |  |  |
| `physical_observation_content_hash` | `CharField` |  |  |  |  |  |
| `physical_source_content_hash` | `CharField` |  |  |  |  |  |
| `physical_raw_observation_content_hash` | `CharField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `assigned_owner_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `physical_row_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `claimant_actor_id` | `CharField` |  |  |  |  |  |
| `claimant_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `claimant_role` | `CharField` |  |  |  |  |  |
| `claimant_kind` | `CharField` |  |  |  |  |  |
| `claimant_is_staff` | `BooleanField` |  |  |  |  |  |
| `receipt_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `receipt_valid_until` | `DateTimeField` |  |  |  |  |  |
| `creation_root_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `creation_root_valid_until` | `DateTimeField` |  |  |  |  |  |
| `requested_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `blocker_codes` | `JSONField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `upstream_binding_seal` | `CharField` |  |  |  |  |  |
| `claimant_binding_seal` | `CharField` |  |  |  |  |  |
| `fixed_authority_seal` | `CharField` |  |  |  |  |  |
| `header_seal` | `CharField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### _AppendOnlyEvidenceV3Model

- 来源文件：`apps/account/infrastructure/account_owner_assignment_evidence_v3_models.py`
- 抽象模型：是

### AccountOwnerAssignmentEvidenceV4Model

- 来源文件：`apps/account/infrastructure/account_owner_assignment_evidence_v4_models.py`
- 数据表：`account_owner_assignment_evidence_v4_ledger`
- 说明：A root assignment with exact subject and authenticated approval-source parents.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `subject` | `OneToOneField` |  |  |  |  | AccountOwnerAssignmentSubjectV4Model |
| `actor_source` | `ForeignKey` |  |  |  | account.AccountOwnerAssignmentActorAuthoritySourceV3Model | account.AccountOwnerAssignmentActorAuthoritySourceV3Model |
| `evidence_id` | `CharField` |  |  |  |  |  |
| `evidence_version` | `CharField` |  |  |  |  |  |
| `assignment_state` | `CharField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `account_claim_hash` | `CharField` |  | 是 |  |  |  |
| `underlying_claim_hash` | `CharField` |  | 是 |  |  |  |
| `approved_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `approval_valid_until` | `DateTimeField` |  |  |  |  |  |

### AccountOwnerAssignmentSubjectV4Model

- 来源文件：`apps/account/infrastructure/account_owner_assignment_evidence_v4_models.py`
- 数据表：`account_owner_assignment_subject_v4_ledger`
- 说明：One registered subject with an exact durable Receipt V4 parent.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `receipt` | `OneToOneField` |  |  |  | account.AccountOwnerAssignmentProvenanceReceiptV4Model | account.AccountOwnerAssignmentProvenanceReceiptV4Model |
| `subject_id` | `CharField` |  |  |  |  |  |
| `subject_version` | `CharField` |  |  |  |  |  |
| `requested_at` | `DateTimeField` |  |  |  |  |  |

### _AssignmentV4Model

- 来源文件：`apps/account/infrastructure/account_owner_assignment_evidence_v4_models.py`
- 抽象模型：是

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |

### AccountOwnerAssignmentProvenanceReceiptModel

- 来源文件：`apps/account/infrastructure/account_owner_assignment_provenance_receipt_models.py`
- 数据表：`account_owner_assignment_provenance_receipt_ledger`
- 说明：One immutable actor-bound Account provenance receipt ledger record.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `provenance_kind` | `CharField` |  |  |  |  |  |
| `assignment_state` | `CharField` |  |  |  |  |  |
| `assigned_owner_user_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `row_observation_owner` | `CharField` |  |  |  |  |  |
| `row_observation_artifact_type` | `CharField` |  |  |  |  |  |
| `row_observation_id` | `CharField` |  |  |  |  |  |
| `row_observation_version` | `CharField` |  |  |  |  |  |
| `row_observation_identity_hash` | `CharField` |  |  |  |  |  |
| `row_observation_content_hash` | `CharField` |  |  |  |  |  |
| `row_observation_valid_until` | `DateTimeField` |  |  |  |  |  |
| `claimant_actor_id` | `CharField` |  |  |  |  |  |
| `claimant_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `claimant_role` | `CharField` |  |  |  |  |  |
| `claimant_kind` | `CharField` |  |  |  |  |  |
| `claimant_is_staff` | `BooleanField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 |  |  |  |  |
| `root_claim_hash` | `CharField` | 是 |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `blocker_codes` | `JSONField` |  |  |  |  |  |
| `issuer_actor_id` | `CharField` |  |  |  |  |  |
| `issuer_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `issuer_role` | `CharField` |  |  |  |  |  |
| `issuer_kind` | `CharField` |  |  |  |  |  |
| `issuer_is_staff` | `BooleanField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `row_binding_hash` | `CharField` |  |  |  |  |  |
| `issuer_binding_hash` | `CharField` |  | 是 |  |  |  |
| `record_header_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### AccountOwnerAssignmentProvenanceReceiptV2Model

- 来源文件：`apps/account/infrastructure/account_owner_assignment_provenance_receipt_v2_models.py`
- 数据表：`account_owner_assignment_provenance_receipt_v2_ledger`
- 说明：One immutable actor-bound receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `provenance_kind` | `CharField` |  |  |  |  |  |
| `assignment_state` | `CharField` |  |  |  |  |  |
| `assigned_owner_user_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `row_observation_owner` | `CharField` |  |  |  |  |  |
| `row_observation_artifact_type` | `CharField` |  |  |  |  |  |
| `row_observation_schema` | `CharField` |  |  |  |  |  |
| `row_observation_id` | `CharField` |  |  |  |  |  |
| `row_observation_version` | `CharField` |  |  |  |  |  |
| `row_observation_identity_hash` | `CharField` |  |  |  |  |  |
| `row_observation_content_hash` | `CharField` |  |  |  |  |  |
| `row_observation_supersedes_content_hash` | `CharField` | 是 |  |  |  |  |
| `row_observation_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `row_observation_valid_until` | `DateTimeField` |  |  |  |  |  |
| `source_content_hash` | `CharField` |  |  |  |  |  |
| `raw_observation_content_hash` | `CharField` |  |  |  |  |  |
| `row_is_active` | `BooleanField` |  |  |  |  |  |
| `row_is_present` | `BooleanField` |  |  |  |  |  |
| `row_is_tombstone` | `BooleanField` |  |  |  |  |  |
| `row_user_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `claimant_actor_id` | `CharField` |  |  |  |  |  |
| `claimant_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `claimant_role` | `CharField` |  |  |  |  |  |
| `claimant_kind` | `CharField` |  |  |  |  |  |
| `claimant_is_staff` | `BooleanField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 |  |  |  |  |
| `root_claim_hash` | `CharField` | 是 |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `blocker_codes` | `JSONField` |  |  |  |  |  |
| `issuer_actor_id` | `CharField` |  |  |  |  |  |
| `issuer_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `issuer_role` | `CharField` |  |  |  |  |  |
| `issuer_kind` | `CharField` |  |  |  |  |  |
| `issuer_is_staff` | `BooleanField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `row_binding_seal` | `CharField` |  |  |  |  |  |
| `actor_binding_seal` | `CharField` |  |  |  |  |  |
| `fixed_authority_seal` | `CharField` |  |  |  |  |  |
| `header_seal` | `CharField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### AccountOwnerAssignmentProvenanceReceiptV3Model

- 来源文件：`apps/account/infrastructure/account_owner_assignment_provenance_receipt_v3_models.py`
- 数据表：`account_owner_assignment_provenance_receipt_v3_ledger`
- 说明：One immutable receipt with exact Binding-v2 and predecessor foreign keys.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `binding` | `ForeignKey` |  |  |  | account.CanonicalAccountCreationBindingV2Model | account.CanonicalAccountCreationBindingV2Model |
| `predecessor` | `OneToOneField` | 是 |  |  | self | self |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `provenance_kind` | `CharField` |  |  |  |  |  |
| `assignment_state` | `CharField` |  |  |  |  |  |
| `assigned_owner_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `binding_ref_id` | `CharField` |  |  |  |  |  |
| `binding_ref_version` | `CharField` |  |  |  |  |  |
| `binding_identity_hash` | `CharField` |  |  |  |  |  |
| `binding_content_hash` | `CharField` |  |  |  |  |  |
| `binding_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `allocation_identity_hash` | `CharField` |  |  |  |  |  |
| `creation_root_content_hash` | `CharField` |  |  |  |  |  |
| `creation_root_identity_hash` | `CharField` |  |  |  |  |  |
| `creation_root_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `creation_root_valid_until` | `DateTimeField` |  |  |  |  |  |
| `allocation_content_hash` | `CharField` |  |  |  |  |  |
| `account_claim_hash` | `CharField` |  |  |  |  |  |
| `underlying_claim_hash` | `CharField` |  |  |  |  |  |
| `physical_observation_content_hash` | `CharField` |  |  |  |  |  |
| `physical_source_content_hash` | `CharField` |  |  |  |  |  |
| `physical_raw_observation_content_hash` | `CharField` |  |  |  |  |  |
| `physical_row_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `claimant_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `claimant_actor_id` | `CharField` |  |  |  |  |  |
| `claimant_role` | `CharField` |  |  |  |  |  |
| `claimant_kind` | `CharField` |  |  |  |  |  |
| `claimant_is_staff` | `BooleanField` |  |  |  |  |  |
| `issuer_actor_id` | `CharField` |  |  |  |  |  |
| `issuer_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `issuer_role` | `CharField` |  |  |  |  |  |
| `issuer_kind` | `CharField` |  |  |  |  |  |
| `issuer_is_staff` | `BooleanField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `blocker_codes` | `JSONField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `binding_seal` | `CharField` |  |  |  |  |  |
| `claimant_seal` | `CharField` |  |  |  |  |  |
| `actor_binding_seal` | `CharField` |  |  |  |  |  |
| `chain_seal` | `CharField` |  |  |  |  |  |
| `fixed_authority_seal` | `CharField` |  |  |  |  |  |
| `header_seal` | `CharField` |  |  |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |
| `root_claim_hash` | `CharField` | 是 | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### AccountOwnerAssignmentProvenanceReceiptV4Model

- 来源文件：`apps/account/infrastructure/account_owner_assignment_provenance_receipt_v4_models.py`
- 数据表：`account_owner_assignment_provenance_receipt_v4_ledger`
- 说明：One immutable receipt envelope referencing three durable evidence parents.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `binding` | `ForeignKey` |  |  |  | account.CanonicalAccountCreationBindingV2Model | account.CanonicalAccountCreationBindingV2Model |
| `policy` | `ForeignKey` |  |  |  | account.SingleOwnerAuthorityPolicyV1Model | account.SingleOwnerAuthorityPolicyV1Model |
| `actor_source` | `ForeignKey` |  |  |  | account.AccountOwnerAssignmentActorAuthoritySourceV3Model | account.AccountOwnerAssignmentActorAuthoritySourceV3Model |
| `predecessor` | `OneToOneField` | 是 |  |  | self | self |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |

### AccountOwnerAssignmentEvidenceV5Model

- 来源文件：`apps/account/infrastructure/account_owner_assignment_v5_models.py`
- 数据表：`account_owner_assignment_evidence_v5_ledger`
- 说明：One inactive append-only approval with exact Subject V5 and actor source.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `subject` | `OneToOneField` |  |  |  |  | AccountOwnerAssignmentSubjectV5Model |
| `actor_source` | `ForeignKey` |  |  |  | account.AccountOwnerAssignmentActorAuthoritySourceV3Model | account.AccountOwnerAssignmentActorAuthoritySourceV3Model |
| `predecessor` | `OneToOneField` | 是 |  |  | self | self |
| `evidence_id` | `CharField` |  |  |  |  |  |
| `evidence_version` | `CharField` |  |  |  |  |  |
| `assignment_state` | `CharField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `account_claim_hash` | `CharField` |  |  |  |  |  |
| `underlying_claim_hash` | `CharField` |  |  |  |  |  |
| `approved_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `approval_valid_until` | `DateTimeField` |  |  |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 | 是 |  |  |  |

### AccountOwnerAssignmentProvenanceReceiptV5Model

- 来源文件：`apps/account/infrastructure/account_owner_assignment_v5_models.py`
- 数据表：`account_owner_assignment_provenance_receipt_v5_ledger`
- 说明：One immutable receipt binding policy, Binding V2, and re-observation V1.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `policy` | `ForeignKey` |  |  |  | account.SingleOwnerAuthorityPolicyV1Model | account.SingleOwnerAuthorityPolicyV1Model |
| `binding` | `ForeignKey` |  |  |  | account.CanonicalAccountCreationBindingV2Model | account.CanonicalAccountCreationBindingV2Model |
| `reobservation` | `ForeignKey` |  |  |  | account.CanonicalAccountOwnershipReobservationV1Model | account.CanonicalAccountOwnershipReobservationV1Model |
| `predecessor` | `OneToOneField` | 是 |  |  | self | self |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `assigned_owner_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 | 是 |  |  |  |

### AccountOwnerAssignmentSubjectV5Model

- 来源文件：`apps/account/infrastructure/account_owner_assignment_v5_models.py`
- 数据表：`account_owner_assignment_subject_v5_ledger`
- 说明：One immutable subject with exact V5 receipt and canonical graph parents.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `receipt` | `OneToOneField` |  |  |  |  | AccountOwnerAssignmentProvenanceReceiptV5Model |
| `binding` | `ForeignKey` |  |  |  | account.CanonicalAccountCreationBindingV2Model | account.CanonicalAccountCreationBindingV2Model |
| `reobservation` | `ForeignKey` |  |  |  | account.CanonicalAccountOwnershipReobservationV1Model | account.CanonicalAccountOwnershipReobservationV1Model |
| `subject_id` | `CharField` |  |  |  |  |  |
| `subject_version` | `CharField` |  |  |  |  |  |
| `requested_at` | `DateTimeField` |  |  |  |  |  |

### _AssignmentV5Model

- 来源文件：`apps/account/infrastructure/account_owner_assignment_v5_models.py`
- 抽象模型：是

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |

### AccountRbacAuthorityMutationBindingV3Model

- 来源文件：`apps/account/infrastructure/account_rbac_authority_mutation_binding_v3_models.py`
- 数据表：`account_rbac_mutation_binding_v3_ledger`
- 说明：Complete immutable mutation binding with scalar projections and seals.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `epoch` | `ForeignKey` |  |  |  |  | AccountRbacAuthorityMutationEpochV3AnchorModel |
| `authority_source` | `OneToOneField` |  |  |  | account.AccountRbacAuthoritySourceV3Model | account.AccountRbacAuthoritySourceV3Model |
| `predecessor` | `OneToOneField` | 是 |  |  | self | self |
| `mutation_id` | `CharField` |  | 是 |  |  |  |
| `mutation_kind` | `CharField` |  |  |  |  |  |
| `source_id` | `CharField` |  |  |  |  |  |
| `source_version` | `CharField` |  |  |  |  |  |
| `old_authority_state` | `CharField` | 是 |  |  |  |  |
| `new_authority_state` | `CharField` |  |  |  |  |  |
| `old_rbac_role` | `CharField` | 是 |  |  |  |  |
| `new_rbac_role` | `CharField` |  |  |  |  |  |
| `old_profile_id` | `CharField` | 是 |  |  |  |  |
| `old_profile_version` | `CharField` | 是 |  |  |  |  |
| `old_profile_content_hash` | `CharField` | 是 |  |  |  |  |
| `old_profile_identity_hash` | `CharField` | 是 |  |  |  |  |
| `old_profile_observed_at` | `DateTimeField` | 是 |  |  |  |  |
| `old_subject_actor_id` | `CharField` | 是 |  |  |  |  |
| `old_user_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `old_subject_seal` | `CharField` | 是 |  |  |  |  |
| `profile_id` | `CharField` |  |  |  |  |  |
| `profile_version` | `CharField` |  |  |  |  |  |
| `profile_content_hash` | `CharField` |  |  |  |  |  |
| `profile_identity_hash` | `CharField` |  |  |  |  |  |
| `profile_observed_at` | `DateTimeField` |  |  |  |  |  |
| `subject_actor_id` | `CharField` |  |  |  |  |  |
| `user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `subject_seal` | `CharField` |  |  |  |  |  |
| `operator_principal_id` | `CharField` |  |  |  |  |  |
| `operator_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `operator_actor_id` | `CharField` |  |  |  |  |  |
| `operator_is_authenticated` | `BooleanField` |  |  |  |  |  |
| `operator_is_active` | `BooleanField` |  |  |  |  |  |
| `operator_is_staff` | `BooleanField` |  |  |  |  |  |
| `operator_is_superuser` | `BooleanField` |  |  |  |  |  |
| `operator_rbac_role` | `CharField` |  |  |  |  |  |
| `operator_authentication_source_id` | `CharField` |  |  |  |  |  |
| `operator_authentication_source_version` | `CharField` |  |  |  |  |  |
| `operator_authentication_source_content_hash` | `CharField` |  |  |  |  |  |
| `operator_user_source_id` | `CharField` |  |  |  |  |  |
| `operator_user_source_version` | `CharField` |  |  |  |  |  |
| `operator_user_source_content_hash` | `CharField` |  |  |  |  |  |
| `operator_rbac_source_id` | `CharField` |  |  |  |  |  |
| `operator_rbac_source_version` | `CharField` |  |  |  |  |  |
| `operator_rbac_source_content_hash` | `CharField` |  |  |  |  |  |
| `operator_observed_at` | `DateTimeField` |  |  |  |  |  |
| `operator_valid_until` | `DateTimeField` |  |  |  |  |  |
| `operator_identity_hash` | `CharField` |  |  |  |  |  |
| `operator_authority_hash` | `CharField` |  |  |  |  |  |
| `issuer_service_id` | `CharField` |  |  |  |  |  |
| `issuer_role` | `CharField` |  |  |  |  |  |
| `issuer_kind` | `CharField` |  |  |  |  |  |
| `issuer_is_automated` | `BooleanField` |  |  |  |  |  |
| `issuer_identity_hash` | `CharField` |  |  |  |  |  |
| `authority_source_identity_hash` | `CharField` |  |  |  |  |  |
| `authority_source_content_hash` | `CharField` |  |  |  |  |  |
| `authority_source_record_seal` | `CharField` |  |  |  |  |  |
| `observed_at` | `DateTimeField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `binding_root_claim_hash` | `CharField` | 是 | 是 |  |  |  |
| `binding_supersedes_content_hash` | `CharField` | 是 | 是 |  |  |  |
| `source_root_claim_hash` | `CharField` | 是 | 是 |  |  |  |
| `source_supersedes_content_hash` | `CharField` | 是 | 是 |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `transition_seal` | `CharField` |  |  |  |  |  |
| `operator_seal` | `CharField` |  |  |  |  |  |
| `issuer_seal` | `CharField` |  |  |  |  |  |
| `source_binding_seal` | `CharField` |  |  |  |  |  |
| `clock_seal` | `CharField` |  |  |  |  |  |
| `binding_chain_seal` | `CharField` |  |  |  |  |  |
| `authority_source_chain_seal` | `CharField` |  |  |  |  |  |
| `fixed_authority_seal` | `CharField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `must_not_execute` | `BooleanField` |  |  |  |  |  |
| `execution_allowed` | `BooleanField` |  |  |  |  |  |

### AccountRbacAuthorityMutationEpochV3AnchorModel

- 来源文件：`apps/account/infrastructure/account_rbac_authority_mutation_binding_v3_models.py`
- 数据表：`account_rbac_mutation_epoch_v3_anchor`
- 说明：Candidate-independent owner-issued RBAC source epoch anchor.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `epoch_id` | `CharField` |  | 是 |  |  |  |
| `target_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `subject_actor_id` | `CharField` |  |  |  |  |  |
| `source_id` | `CharField` |  | 是 |  |  |  |
| `epoch_sequence` | `PositiveBigIntegerField` |  |  |  |  |  |
| `opened_at` | `DateTimeField` |  |  |  |  |  |
| `previous_epoch` | `OneToOneField` | 是 |  |  | self | self |
| `previous_epoch_content_hash` | `CharField` | 是 |  |  |  |  |
| `terminal_authority_source_content_hash` | `CharField` | 是 |  |  |  |  |
| `terminal_mutation_binding_content_hash` | `CharField` | 是 |  |  |  |  |
| `root_claim_hash` | `CharField` |  | 是 |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### AccountRbacAuthorityProfileV3AnchorModel

- 来源文件：`apps/account/infrastructure/account_rbac_authority_mutation_binding_v3_models.py`
- 数据表：`account_rbac_profile_v3_anchor`
- 说明：Candidate-independent lock for a future exact Profile authority chain.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `profile_id` | `CharField` |  | 是 |  |  |  |
| `user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `subject_actor_id` | `CharField` |  |  |  |  |  |
| `root_claim_hash` | `CharField` |  | 是 |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### AccountRbacAuthorityProfileV3VersionModel

- 来源文件：`apps/account/infrastructure/account_rbac_authority_mutation_binding_v3_models.py`
- 数据表：`account_rbac_profile_v3_version`
- 说明：Append-only exact Profile projection used by old/new mutation refs.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `anchor` | `ForeignKey` |  |  |  |  | AccountRbacAuthorityProfileV3AnchorModel |
| `predecessor` | `OneToOneField` | 是 |  |  | self | self |
| `profile_id` | `CharField` |  |  |  |  |  |
| `profile_version` | `CharField` |  |  |  |  |  |
| `profile_content_hash` | `CharField` |  |  |  |  |  |
| `user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `subject_actor_id` | `CharField` |  |  |  |  |  |
| `rbac_role` | `CharField` |  |  |  |  |  |
| `observed_at` | `DateTimeField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `root_claim_hash` | `CharField` | 是 | 是 |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 | 是 |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### _GuardedRbacMutationModel

- 来源文件：`apps/account/infrastructure/account_rbac_authority_mutation_binding_v3_models.py`
- 抽象模型：是

### AllocatedPhysicalAccountRowObservationV3Model

- 来源文件：`apps/account/infrastructure/allocated_physical_account_row_observation_v3_models.py`
- 数据表：`account_allocated_physical_row_observation_v3_ledger`
- 说明：One immutable service-projected allocated Physical-v3 creation root.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `observation_id` | `CharField` |  |  |  |  |  |
| `observation_version` | `CharField` |  |  |  |  |  |
| `allocation_id` | `CharField` |  |  |  |  |  |
| `allocation_version` | `CharField` |  |  |  |  |  |
| `allocation_identity_hash` | `CharField` |  | 是 |  |  |  |
| `allocation_content_hash` | `CharField` |  | 是 |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `physical_observation_id` | `CharField` |  |  |  |  |  |
| `physical_observation_version` | `CharField` |  |  |  |  |  |
| `physical_identity_hash` | `CharField` |  | 是 |  |  |  |
| `physical_content_hash` | `CharField` |  | 是 |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ttl_valid_until` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `identity_anchor_kind` | `CharField` |  |  |  |  |  |
| `owner_assignment_state` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `recorded_by_service_id` | `CharField` |  |  |  |  |  |
| `recorded_by_role` | `CharField` |  |  |  |  |  |
| `recorded_by_kind` | `CharField` |  |  |  |  |  |
| `recorded_by_is_automated` | `BooleanField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `identity_claim_hash` | `CharField` |  | 是 |  |  |  |
| `allocation_claim_hash` | `CharField` |  | 是 |  |  |  |
| `account_claim_hash` | `CharField` |  | 是 |  |  |  |
| `underlying_claim_hash` | `CharField` |  | 是 |  |  |  |
| `physical_claim_hash` | `CharField` |  | 是 |  |  |  |
| `root_claim_hash` | `CharField` |  | 是 |  |  |  |
| `allocation_binding_seal` | `CharField` |  |  |  |  |  |
| `physical_binding_seal` | `CharField` |  |  |  |  |  |
| `projector_binding_seal` | `CharField` |  |  |  |  |  |
| `fixed_authority_seal` | `CharField` |  |  |  |  |  |
| `clock_seal` | `CharField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### CanonicalAccountCreationBindingV2Model

- 来源文件：`apps/account/infrastructure/canonical_account_creation_consumption_models.py`
- 数据表：`canonical_account_creation_binding_v2_ledger`
- 说明：One immutable durable Binding-v2 backed by a unified consumption claim.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `consumption_claim` | `OneToOneField` |  |  |  |  | CanonicalAccountCreationConsumptionClaimModel |
| `consumption_claim_content_hash` | `CharField` |  | 是 |  |  |  |
| `allocation` | `ForeignKey` |  |  |  |  | CanonicalAccountCreationAllocationModel |
| `allocation_identity_hash` | `CharField` |  | 是 |  |  |  |
| `allocation_content_hash` | `CharField` |  | 是 |  |  |  |
| `creation_root` | `OneToOneField` |  |  |  |  | AllocatedPhysicalAccountRowObservationV3Model |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `binding_id` | `CharField` |  |  |  |  |  |
| `binding_version` | `CharField` |  |  |  |  |  |
| `creation_root_observation_id` | `CharField` |  |  |  |  |  |
| `creation_root_observation_version` | `CharField` |  |  |  |  |  |
| `creation_root_identity_hash` | `CharField` |  | 是 |  |  |  |
| `creation_root_content_hash` | `CharField` |  | 是 |  |  |  |
| `physical_observation_content_hash` | `CharField` |  | 是 |  |  |  |
| `physical_source_content_hash` | `CharField` |  | 是 |  |  |  |
| `physical_raw_observation_content_hash` | `CharField` |  | 是 |  |  |  |
| `account_namespace_claim` | `CharField` |  |  |  |  |  |
| `account_id_claim` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace_claim` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id_claim` | `PositiveBigIntegerField` |  |  |  |  |  |
| `recorded_service_id` | `CharField` |  |  |  |  |  |
| `recorded_role` | `CharField` |  |  |  |  |  |
| `recorded_kind` | `CharField` |  |  |  |  |  |
| `recorded_is_automated` | `BooleanField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `account_claim_hash` | `CharField` |  | 是 |  |  |  |
| `underlying_claim_hash` | `CharField` |  | 是 |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `binding_state` | `CharField` |  |  |  |  |  |
| `owner_assignment_state` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `consumption_claim_binding_seal` | `CharField` |  |  |  |  |  |
| `allocation_binding_seal` | `CharField` |  |  |  |  |  |
| `creation_root_binding_seal` | `CharField` |  |  |  |  |  |
| `physical_binding_seal` | `CharField` |  |  |  |  |  |
| `recorder_binding_seal` | `CharField` |  |  |  |  |  |
| `fixed_authority_seal` | `CharField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### CanonicalAccountCreationConsumptionClaimModel

- 来源文件：`apps/account/infrastructure/canonical_account_creation_consumption_models.py`
- 数据表：`canonical_account_creation_consumption_claim_ledger`
- 说明：One cross-generation claim that permanently consumes creation anchors.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `claim_id` | `CharField` |  |  |  |  |  |
| `claim_version` | `CharField` |  |  |  |  |  |
| `allocation` | `OneToOneField` |  |  |  |  | CanonicalAccountCreationAllocationModel |
| `allocation_identity_hash` | `CharField` |  | 是 |  |  |  |
| `allocation_content_hash` | `CharField` |  | 是 |  |  |  |
| `consumer_generation` | `CharField` |  |  |  |  |  |
| `consumer_owner` | `CharField` |  |  |  |  |  |
| `consumer_artifact_type` | `CharField` |  |  |  |  |  |
| `consumer_schema` | `CharField` |  |  |  |  |  |
| `consumer_id` | `CharField` |  |  |  |  |  |
| `consumer_version` | `CharField` |  |  |  |  |  |
| `consumer_identity_hash` | `CharField` |  | 是 |  |  |  |
| `consumer_content_hash` | `CharField` |  | 是 |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `physical_v2_content_hash` | `CharField` |  | 是 |  |  |  |
| `physical_v3_root_content_hash` | `CharField` | 是 |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `knowledge_at` | `DateTimeField` | 是 |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `allocation_binding_seal` | `CharField` |  |  |  |  |  |
| `consumer_binding_seal` | `CharField` |  |  |  |  |  |
| `fixed_authority_seal` | `CharField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### _AppendOnlyCanonicalAccountCreationConsumptionModel

- 来源文件：`apps/account/infrastructure/canonical_account_creation_consumption_models.py`
- 抽象模型：是

### CanonicalAccountCreationAllocationModel

- 来源文件：`apps/account/infrastructure/canonical_account_creation_models.py`
- 数据表：`canonical_account_creation_allocation_ledger`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `allocation_id` | `CharField` |  |  |  |  |  |
| `allocation_version` | `CharField` |  |  |  |  |  |
| `canonical_account_namespace` | `CharField` |  |  |  |  |  |
| `canonical_account_id` | `CharField` |  |  |  |  |  |
| `requested_row_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `requested_raw_account_type` | `CharField` |  |  |  |  |  |
| `intended_underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `request_fingerprint_hash` | `CharField` |  |  |  |  |  |
| `requester_actor_id` | `CharField` |  |  |  |  |  |
| `requester_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `requester_role` | `CharField` |  |  |  |  |  |
| `requester_kind` | `CharField` |  |  |  |  |  |
| `requester_is_authenticated` | `BooleanField` |  |  |  |  |  |
| `allocated_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `recorded_service_id` | `CharField` |  |  |  |  |  |
| `recorded_role` | `CharField` |  |  |  |  |  |
| `recorded_kind` | `CharField` |  |  |  |  |  |
| `recorded_is_automated` | `BooleanField` |  |  |  |  |  |
| `intended_purpose` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `requester_binding_seal` | `CharField` |  |  |  |  |  |
| `recorder_binding_seal` | `CharField` |  |  |  |  |  |
| `fixed_authority_seal` | `CharField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### CanonicalAccountCreationBindingModel

- 来源文件：`apps/account/infrastructure/canonical_account_creation_models.py`
- 数据表：`canonical_account_creation_binding_ledger`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `consumption_claim` | `OneToOneField` | 是 |  |  | account.CanonicalAccountCreationConsumptionClaimModel | account.CanonicalAccountCreationConsumptionClaimModel |
| `allocation` | `OneToOneField` |  |  |  |  | CanonicalAccountCreationAllocationModel |
| `allocation_content_hash` | `CharField` |  | 是 |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `binding_id` | `CharField` |  |  |  |  |  |
| `binding_version` | `CharField` |  |  |  |  |  |
| `physical_observation_id` | `CharField` |  |  |  |  |  |
| `physical_observation_version` | `CharField` |  |  |  |  |  |
| `physical_identity_hash` | `CharField` |  |  |  |  |  |
| `physical_content_hash` | `CharField` |  | 是 |  |  |  |
| `account_namespace_claim` | `CharField` |  |  |  |  |  |
| `account_id_claim` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace_claim` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id_claim` | `PositiveBigIntegerField` |  |  |  |  |  |
| `recorded_service_id` | `CharField` |  |  |  |  |  |
| `recorded_role` | `CharField` |  |  |  |  |  |
| `recorded_kind` | `CharField` |  |  |  |  |  |
| `recorded_is_automated` | `BooleanField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `account_claim_hash` | `CharField` |  | 是 |  |  |  |
| `underlying_claim_hash` | `CharField` |  | 是 |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `binding_state` | `CharField` |  |  |  |  |  |
| `owner_assignment_state` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `allocation_binding_seal` | `CharField` |  |  |  |  |  |
| `physical_binding_seal` | `CharField` |  |  |  |  |  |
| `recorder_binding_seal` | `CharField` |  |  |  |  |  |
| `fixed_authority_seal` | `CharField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### _AppendOnlyCanonicalAccountCreationModel

- 来源文件：`apps/account/infrastructure/canonical_account_creation_models.py`
- 抽象模型：是

### CanonicalAccountOwnershipReobservationV1Model

- 来源文件：`apps/account/infrastructure/canonical_account_ownership_reobservation_v1_models.py`
- 数据表：`canonical_account_ownership_reobservation_v1_ledger`
- 说明：One immutable Binding-v2 and Physical-v2 re-observation record.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `binding` | `ForeignKey` |  |  |  |  | CanonicalAccountCreationBindingV2Model |
| `current_physical` | `ForeignKey` |  |  |  |  | PhysicalAccountRowObservationV2Model |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `observation_id` | `CharField` |  |  |  |  |  |
| `observation_version` | `CharField` |  |  |  |  |  |
| `binding_identity_hash` | `CharField` |  |  |  |  |  |
| `binding_content_hash` | `CharField` |  |  |  |  |  |
| `current_physical_identity_hash` | `CharField` |  |  |  |  |  |
| `current_physical_content_hash` | `CharField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |

### AssetCategoryModel

- 来源文件：`apps/account/infrastructure/classification_models.py`
- 数据表：`asset_category`
- 说明：资产分类模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `code` | `CharField` |  | 是 |  | 分类代码 |  |
| `name` | `CharField` |  |  |  | 分类名称 |  |
| `parent` | `ForeignKey` | 是 |  |  | 父分类 | self |
| `level` | `IntegerField` |  |  | 1 | 层级 |  |
| `path` | `CharField` |  |  |  | 分类路径 |  |
| `description` | `TextField` |  |  |  | 描述 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `sort_order` | `IntegerField` |  |  | 0 | 排序 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### AssetMetadataModel

- 来源文件：`apps/account/infrastructure/classification_models.py`
- 数据表：`asset_metadata`
- 说明：资产元数据表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `asset_code` | `CharField` |  | 是 |  | 资产代码 |  |
| `name` | `CharField` |  |  |  | 资产名称 |  |
| `description` | `TextField` |  |  |  | 描述 |  |
| `asset_class` | `CharField` |  |  |  | 资产大类 |  |
| `region` | `CharField` |  |  |  | 地区 |  |
| `cross_border` | `CharField` |  |  | domestic | 跨境标识 |  |
| `style` | `CharField` |  |  | unknown | 投资风格 |  |
| `sector` | `CharField` |  |  |  | 行业板块 |  |
| `sub_class` | `CharField` |  |  |  | 子类 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### CurrencyModel

- 来源文件：`apps/account/infrastructure/classification_models.py`
- 数据表：`currency`
- 说明：币种模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `code` | `CharField` |  | 是 |  | 币种代码 |  |
| `name` | `CharField` |  |  |  | 币种名称 |  |
| `symbol` | `CharField` |  |  |  | 货币符号 |  |
| `is_base` | `BooleanField` |  |  | False | 是否基准货币 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `precision` | `IntegerField` |  |  | 2 | 小数位数 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### ExchangeRateModel

- 来源文件：`apps/account/infrastructure/classification_models.py`
- 数据表：`exchange_rate`
- 说明：汇率模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `from_currency` | `ForeignKey` |  |  |  | 源币种 | CurrencyModel |
| `to_currency` | `ForeignKey` |  |  |  | 目标币种 | CurrencyModel |
| `rate` | `DecimalField` |  |  |  | 汇率 |  |
| `effective_date` | `DateField` |  |  |  | 生效日期 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### DocumentationModel

- 来源文件：`apps/account/infrastructure/documentation_models.py`
- 数据表：`documentation`
- 说明：文档表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `title` | `CharField` |  |  |  | 标题 |  |
| `slug` | `SlugField` |  | 是 |  | URL标识 |  |
| `category` | `CharField` |  |  | user_guide | 分类 |  |
| `content` | `TextField` |  |  |  | 内容（Markdown） |  |
| `summary` | `TextField` |  |  |  | 摘要 |  |
| `order` | `IntegerField` |  |  | 0 | 排序（数字越小越靠前） |  |
| `is_published` | `BooleanField` |  |  | True | 是否发布 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### AccountProfileModel

- 来源文件：`apps/account/infrastructure/identity_models.py`
- 数据表：`account_profile`
- 说明：用户账户配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `OneToOneField` |  |  |  | 用户 | User |
| `display_name` | `CharField` |  |  |  | 显示名称 |  |
| `initial_capital` | `DecimalField` |  |  | Decimal('1000000.00') | 初始资金 |  |
| `risk_tolerance` | `CharField` |  |  | moderate | 风险偏好 |  |
| `rbac_role` | `CharField` |  |  | owner | 系统统一角色（与 MCP 对齐） |  |
| `mcp_enabled` | `BooleanField` |  |  | True | 关闭后，该用户所有 MCP/SDK Token 将立即失效 |  |
| `target_volatility` | `FloatField` |  |  | 0.15 | 年化波动率目标，如0.15表示15% |  |
| `volatility_tolerance` | `FloatField` |  |  | 0.2 | 超过目标波动率多少比例触发降仓，如0.2表示20% |  |
| `max_volatility_reduction` | `FloatField` |  |  | 0.5 | 波动率超标时最大降仓比例，如0.5表示最多降50% |  |
| `user_agreement_accepted` | `BooleanField` |  |  | False | 用户协议已接受 |  |
| `risk_warning_acknowledged` | `BooleanField` |  |  | False | 风险提示已确认 |  |
| `agreement_accepted_at` | `DateTimeField` | 是 |  |  | 协议接受时间 |  |
| `agreement_ip_address` | `GenericIPAddressField` | 是 |  |  | 协议接受IP |  |
| `approval_status` | `CharField` |  |  | pending | 审批状态 |  |
| `approved_at` | `DateTimeField` | 是 |  |  | 批准时间 |  |
| `approved_by` | `ForeignKey` | 是 |  |  | 审批人 | User |
| `rejection_reason` | `TextField` |  |  |  | 拒绝原因 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### PortfolioObserverGrantModel

- 来源文件：`apps/account/infrastructure/identity_models.py`
- 数据表：`portfolio_observer_grant`
- 说明：投资组合观察员授权表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `id` | `UUIDField` |  |  | uuid.uuid4 | 授权ID |  |
| `owner_user_id` | `ForeignKey` |  |  |  | 账户拥有者 | User |
| `observer_user_id` | `ForeignKey` |  |  |  | 观察员 | User |
| `scope` | `CharField` |  |  | portfolio_read | 授权范围 |  |
| `status` | `CharField` |  |  | active | 状态 |  |
| `expires_at` | `DateTimeField` | 是 |  |  | 过期时间 |  |
| `created_by` | `ForeignKey` | 是 |  |  | 创建者 | User |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `revoked_at` | `DateTimeField` | 是 |  |  | 撤销时间 |  |
| `revoked_by` | `ForeignKey` | 是 |  |  | 撤销者 | User |

### UserAccessTokenModel

- 来源文件：`apps/account/infrastructure/identity_models.py`
- 数据表：`user_access_token`
- 说明：支持多 Token 的 MCP/SDK 访问凭证。

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  | 所属用户 | User |
| `name` | `CharField` |  |  | default | 例如：Claude Desktop / Local SDK / VPS Script |  |
| `key` | `CharField` |  | 是 |  | Token Key |  |
| `key_encrypted` | `TextField` |  |  |  | 用于按系统配置决定是否允许明文查看 |  |
| `created_by` | `ForeignKey` | 是 |  |  | 创建人 | User |
| `access_level` | `CharField` |  |  | ACCESS_LEVEL_READ_WRITE | 只读 Token 仅允许 GET/HEAD/OPTIONS；读写 Token 仍需通过账号角色鉴权。 |  |
| `last_used_at` | `DateTimeField` | 是 |  |  | 最后使用时间 |  |
| `revoked_at` | `DateTimeField` | 是 |  |  | 撤销时间 |  |
| `is_active` | `BooleanField` |  |  | True | 是否有效 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### OwnerTenantAuthorityV1Model

- 来源文件：`apps/account/infrastructure/owner_tenant_authority_v1_models.py`
- 数据表：`account_owner_tenant_authority_v1`
- 说明：One immutable authority root, renewal, or revocation row.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `authority_id` | `CharField` |  |  |  |  |  |
| `authority_version` | `CharField` |  |  |  |  |  |
| `tenant_id` | `CharField` |  |  |  |  |  |
| `owner_id` | `CharField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `actor_id` | `CharField` |  |  |  |  |  |
| `actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `assignment_evidence_id` | `CharField` |  |  |  |  |  |
| `assignment_evidence_version` | `CharField` |  |  |  |  |  |
| `assignment_evidence_content_hash` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `approved_actor_id` | `CharField` |  |  |  |  |  |
| `approved_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `approved_role` | `CharField` |  |  |  |  |  |
| `approved_kind` | `CharField` |  |  |  |  |  |
| `approved_is_staff` | `BooleanField` |  |  |  |  |  |
| `approved_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 |  |  |  |  |
| `predecessor` | `OneToOneField` | 是 |  |  | self | self |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `authority_owner` | `CharField` |  |  |  |  |  |
| `authority_artifact_type` | `CharField` |  |  |  |  |  |
| `authority_schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### OwnerTenantAuthorityV2Model

- 来源文件：`apps/account/infrastructure/owner_tenant_authority_v2_models.py`
- 数据表：`account_owner_tenant_authority_v2_ledger`
- 说明：Immutable active root decision over one complete assignment graph.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `authority_id` | `CharField` |  |  |  |  |  |
| `authority_version` | `CharField` |  |  |  |  |  |
| `assignment` | `OneToOneField` |  |  |  | account.AccountOwnerAssignmentEvidenceV4Model | account.AccountOwnerAssignmentEvidenceV4Model |
| `assignment_evidence_id` | `CharField` |  |  |  |  |  |
| `assignment_evidence_version` | `CharField` |  |  |  |  |  |
| `assignment_evidence_content_hash` | `CharField` |  | 是 |  |  |  |
| `policy` | `ForeignKey` |  |  |  | account.SingleOwnerAuthorityPolicyV1Model | account.SingleOwnerAuthorityPolicyV1Model |
| `policy_identifier` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_content_hash` | `CharField` |  |  |  |  |  |
| `tenant_id` | `CharField` |  |  |  |  |  |
| `owner_id` | `CharField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `actor_id` | `CharField` |  |  |  |  |  |
| `actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `actor_source` | `ForeignKey` |  |  |  | account.AccountOwnerAssignmentActorAuthoritySourceV3Model | account.AccountOwnerAssignmentActorAuthoritySourceV3Model |
| `approved_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### OwnerTenantAuthorityV2RevocationModel

- 来源文件：`apps/account/infrastructure/owner_tenant_authority_v2_models.py`
- 数据表：`account_owner_tenant_authority_v2_revocation_ledger`
- 说明：Immutable explicit revocation event linked to one authority root.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `authority` | `OneToOneField` |  |  |  |  | OwnerTenantAuthorityV2Model |
| `actor_source` | `ForeignKey` |  |  |  | account.AccountOwnerAssignmentActorAuthoritySourceV3Model | account.AccountOwnerAssignmentActorAuthoritySourceV3Model |
| `authority_content_hash` | `CharField` |  | 是 |  |  |  |
| `policy_content_hash` | `CharField` |  |  |  |  |  |
| `revoked_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `reason` | `CharField` |  |  |  |  |  |

### _OwnerTenantAuthorityV2Model

- 来源文件：`apps/account/infrastructure/owner_tenant_authority_v2_models.py`
- 抽象模型：是
- 说明：Shared immutable fields and save/delete guards for both ledgers.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |

### OwnerTenantAuthorityV3Model

- 来源文件：`apps/account/infrastructure/owner_tenant_authority_v3_models.py`
- 数据表：`account_owner_tenant_authority_v3_ledger`
- 说明：Immutable active root or successor over one complete Evidence v5 graph.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `authority_id` | `CharField` |  |  |  |  |  |
| `authority_version` | `CharField` |  |  |  |  |  |
| `assignment` | `ForeignKey` |  |  |  | account.AccountOwnerAssignmentEvidenceV5Model | account.AccountOwnerAssignmentEvidenceV5Model |
| `assignment_evidence_id` | `CharField` |  |  |  |  |  |
| `assignment_evidence_version` | `CharField` |  |  |  |  |  |
| `assignment_evidence_content_hash` | `CharField` |  |  |  |  |  |
| `policy` | `ForeignKey` |  |  |  | account.SingleOwnerAuthorityPolicyV1Model | account.SingleOwnerAuthorityPolicyV1Model |
| `policy_identifier` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_content_hash` | `CharField` |  |  |  |  |  |
| `tenant_id` | `CharField` |  |  |  |  |  |
| `owner_id` | `CharField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `actor_id` | `CharField` |  |  |  |  |  |
| `actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `actor_source` | `ForeignKey` |  |  |  | account.AccountOwnerAssignmentActorAuthoritySourceV3Model | account.AccountOwnerAssignmentActorAuthoritySourceV3Model |
| `approved_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 |  |  |  |  |
| `predecessor` | `OneToOneField` | 是 |  |  | self | self |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### OwnerTenantAuthorityV3RevocationModel

- 来源文件：`apps/account/infrastructure/owner_tenant_authority_v3_models.py`
- 数据表：`account_owner_tenant_authority_v3_revocation_ledger`
- 说明：Immutable explicit revocation event linked to one v3 authority row.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `authority` | `OneToOneField` |  |  |  |  | OwnerTenantAuthorityV3Model |
| `actor_source` | `ForeignKey` |  |  |  | account.AccountOwnerAssignmentActorAuthoritySourceV3Model | account.AccountOwnerAssignmentActorAuthoritySourceV3Model |
| `authority_content_hash` | `CharField` |  | 是 |  |  |  |
| `policy_content_hash` | `CharField` |  |  |  |  |  |
| `revoked_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `reason` | `CharField` |  |  |  |  |  |

### _OwnerTenantAuthorityV3Model

- 来源文件：`apps/account/infrastructure/owner_tenant_authority_v3_models.py`
- 抽象模型：是
- 说明：Shared immutable fields and save/delete guards for both ledgers.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |

### PhysicalAccountRowObservationModel

- 来源文件：`apps/account/infrastructure/physical_account_row_observation_models.py`
- 数据表：`account_physical_row_observation_ledger`
- 说明：One immutable actor-bound Account physical-row ledger record.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `observation_id` | `CharField` |  |  |  |  |  |
| `observation_version` | `CharField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `raw_source_owner` | `CharField` |  |  |  |  |  |
| `raw_source_artifact_type` | `CharField` |  |  |  |  |  |
| `raw_source_id` | `CharField` |  |  |  |  |  |
| `raw_source_version` | `CharField` |  |  |  |  |  |
| `raw_source_content_hash` | `CharField` |  |  |  |  |  |
| `row_user_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `account_type` | `CharField` |  |  |  |  |  |
| `is_active` | `BooleanField` |  |  |  |  |  |
| `row_created_at` | `DateTimeField` |  |  |  |  |  |
| `row_updated_at` | `DateTimeField` |  |  |  |  |  |
| `observed_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `raw_source_valid_until` | `DateTimeField` |  |  |  |  |  |
| `ttl_valid_until` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `owner_assignment_state` | `CharField` |  |  |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 |  |  |  |  |
| `root_claim_hash` | `CharField` | 是 |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `blocker_codes` | `JSONField` |  |  |  |  |  |
| `captured_actor_id` | `CharField` |  |  |  |  |  |
| `captured_actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `captured_actor_role` | `CharField` |  |  |  |  |  |
| `captured_actor_kind` | `CharField` |  |  |  |  |  |
| `captured_actor_is_staff` | `BooleanField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `raw_row_hash` | `CharField` |  |  |  |  |  |
| `raw_source_binding_hash` | `CharField` |  | 是 |  |  |  |
| `actor_binding_hash` | `CharField` |  | 是 |  |  |  |
| `record_header_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### PhysicalAccountRowObservationV2Model

- 来源文件：`apps/account/infrastructure/physical_account_row_observation_v2_models.py`
- 数据表：`account_physical_row_observation_v2_ledger`
- 说明：One immutable service-recorded Account v2 ledger record.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `observation_id` | `CharField` |  |  |  |  |  |
| `observation_version` | `CharField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `row_user_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `raw_account_type` | `CharField` |  |  |  |  |  |
| `is_active` | `BooleanField` |  |  |  |  |  |
| `row_created_at` | `DateTimeField` |  |  |  |  |  |
| `row_updated_at` | `DateTimeField` |  |  |  |  |  |
| `is_present` | `BooleanField` |  |  |  |  |  |
| `is_tombstone` | `BooleanField` |  |  |  |  |  |
| `source_owner` | `CharField` |  |  |  |  |  |
| `source_artifact_type` | `CharField` |  |  |  |  |  |
| `source_schema` | `CharField` |  |  |  |  |  |
| `source_id` | `CharField` |  |  |  |  |  |
| `source_version` | `CharField` |  |  |  |  |  |
| `source_identity_hash` | `CharField` |  |  |  |  |  |
| `source_content_hash` | `CharField` |  |  |  |  |  |
| `source_supersedes_content_hash` | `CharField` | 是 |  |  |  |  |
| `source_observed_at` | `DateTimeField` |  |  |  |  |  |
| `source_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `source_valid_until` | `DateTimeField` |  |  |  |  |  |
| `source_ttl_valid_until` | `DateTimeField` |  |  |  |  |  |
| `source_effective_valid_until` | `DateTimeField` |  |  |  |  |  |
| `raw_observation_owner` | `CharField` |  |  |  |  |  |
| `raw_observation_artifact_type` | `CharField` |  |  |  |  |  |
| `raw_observation_schema` | `CharField` |  |  |  |  |  |
| `raw_observation_id` | `CharField` |  |  |  |  |  |
| `raw_observation_version` | `CharField` |  |  |  |  |  |
| `raw_observation_identity_hash` | `CharField` |  |  |  |  |  |
| `raw_observation_content_hash` | `CharField` |  |  |  |  |  |
| `raw_observation_supersedes_content_hash` | `CharField` | 是 |  |  |  |  |
| `raw_observation_observed_at` | `DateTimeField` |  |  |  |  |  |
| `raw_observation_valid_until` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ttl_valid_until` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `owner_assignment_state` | `CharField` |  |  |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 |  |  |  |  |
| `root_claim_hash` | `CharField` | 是 |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `recorded_by_id` | `CharField` |  |  |  |  |  |
| `recorded_by_service_name` | `CharField` |  |  |  |  |  |
| `recorded_by_role` | `CharField` |  |  |  |  |  |
| `recorded_by_kind` | `CharField` |  |  |  |  |  |
| `recorded_by_is_automated` | `BooleanField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `raw_binding_seal` | `CharField` |  |  |  |  |  |
| `source_binding_seal` | `CharField` |  |  |  |  |  |
| `row_seal` | `CharField` |  |  |  |  |  |
| `clock_seal` | `CharField` |  |  |  |  |  |
| `recorder_binding_seal` | `CharField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### BrokerTradeImportBatchModel

- 来源文件：`apps/account/infrastructure/portfolio_models.py`
- 数据表：`broker_trade_import_batch`
- 说明：One manual broker trade import attempt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  | 用户 | User |
| `portfolio` | `ForeignKey` |  |  |  | 投资组合 | PortfolioModel |
| `broker_name` | `CharField` |  |  | manual | 券商名称 |  |
| `source_filename` | `CharField` |  |  |  | 文件名 |  |
| `file_hash` | `CharField` |  |  |  | 文件哈希 |  |
| `status` | `CharField` |  |  | previewed | 状态 |  |
| `total_rows` | `IntegerField` |  |  | 0 | 总行数 |  |
| `imported_rows` | `IntegerField` |  |  | 0 | 导入行数 |  |
| `skipped_rows` | `IntegerField` |  |  | 0 | 跳过行数 |  |
| `error_rows` | `IntegerField` |  |  | 0 | 错误行数 |  |
| `errors` | `JSONField` |  |  | list | 错误详情 |  |
| `preview_rows` | `JSONField` |  |  | list | 预览行 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### CapitalFlowModel

- 来源文件：`apps/account/infrastructure/portfolio_models.py`
- 数据表：`capital_flow`
- 说明：资金流水表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  | 用户 | User |
| `portfolio` | `ForeignKey` |  |  |  | 投资组合 | PortfolioModel |
| `flow_type` | `CharField` |  |  |  | 流水类型 |  |
| `amount` | `DecimalField` |  |  |  | 金额 |  |
| `flow_date` | `DateField` |  |  |  | 流水日期 |  |
| `notes` | `TextField` |  |  |  | 备注 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### PortfolioDailySnapshotModel

- 来源文件：`apps/account/infrastructure/portfolio_models.py`
- 数据表：`portfolio_daily_snapshot`
- 说明：投资组合日快照表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `portfolio` | `ForeignKey` |  |  |  | 投资组合 | PortfolioModel |
| `snapshot_date` | `DateField` |  |  |  | 快照日期 |  |
| `total_value` | `DecimalField` |  |  |  | 总资产 |  |
| `cash_balance` | `DecimalField` |  |  | 0 | 现金余额 |  |
| `invested_value` | `DecimalField` |  |  | 0 | 投资市值 |  |
| `position_count` | `IntegerField` |  |  | 0 | 持仓数量 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### PortfolioModel

- 来源文件：`apps/account/infrastructure/portfolio_models.py`
- 数据表：`portfolio`
- 说明：投资组合表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  | 用户 | User |
| `name` | `CharField` |  |  | 默认组合 | 组合名称 |  |
| `base_currency` | `ForeignKey` | 是 |  |  | 基准货币 | CurrencyModel |
| `is_active` | `BooleanField` |  |  | True | 是否激活 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### PositionModel

- 来源文件：`apps/account/infrastructure/portfolio_models.py`
- 数据表：`position`
- 说明：持仓记录表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `portfolio` | `ForeignKey` |  |  |  | 投资组合 | PortfolioModel |
| `asset_code` | `CharField` |  |  |  | 资产代码 |  |
| `category` | `ForeignKey` | 是 |  |  | 资产分类 | AssetCategoryModel |
| `currency` | `ForeignKey` | 是 |  |  | 币种 | CurrencyModel |
| `asset_class` | `CharField` |  |  |  | 资产大类 |  |
| `region` | `CharField` |  |  |  | 地区 |  |
| `cross_border` | `CharField` |  |  |  | 跨境标识 |  |
| `shares` | `FloatField` |  |  |  | 持仓数量 |  |
| `avg_cost` | `DecimalField` |  |  |  | 平均成本价 |  |
| `current_price` | `DecimalField` | 是 |  |  | 当前市价 |  |
| `market_value` | `DecimalField` |  |  | 0 | 市值 |  |
| `unrealized_pnl` | `DecimalField` |  |  | 0 | 未实现盈亏 |  |
| `unrealized_pnl_pct` | `FloatField` |  |  | 0 | 未实现盈亏百分比 |  |
| `source` | `CharField` |  |  | manual | 来源 |  |
| `source_id` | `IntegerField` | 是 |  |  | 来源ID |  |
| `is_closed` | `BooleanField` |  |  | False | 是否已平仓 |  |
| `opened_at` | `DateTimeField` |  |  |  | 开仓时间 |  |
| `closed_at` | `DateTimeField` | 是 |  |  | 平仓时间 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### PositionSignalLogModel

- 来源文件：`apps/account/infrastructure/portfolio_models.py`
- 数据表：`position_signal_log`
- 说明：持仓信号关联表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `signal_id` | `IntegerField` |  |  |  | 信号ID |  |
| `position` | `ForeignKey` |  |  |  | 持仓 | PositionModel |
| `executed_at` | `DateTimeField` |  |  |  | 执行时间 |  |
| `notes` | `TextField` |  |  |  | 备注 |  |

### TransactionModel

- 来源文件：`apps/account/infrastructure/portfolio_models.py`
- 数据表：`transaction`
- 说明：交易记录表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `portfolio` | `ForeignKey` |  |  |  | 投资组合 | PortfolioModel |
| `position` | `ForeignKey` | 是 |  |  | 关联持仓 | PositionModel |
| `action` | `CharField` |  |  |  | 交易方向 |  |
| `asset_code` | `CharField` |  |  |  | 资产代码 |  |
| `shares` | `FloatField` |  |  |  | 交易数量 |  |
| `price` | `DecimalField` |  |  |  | 成交价格 |  |
| `notional` | `DecimalField` |  |  |  | 成交金额 |  |
| `commission` | `DecimalField` |  |  | 0 | 手续费 |  |
| `slippage` | `DecimalField` |  |  | 0 | 滑点成本 |  |
| `stamp_duty` | `DecimalField` |  |  | 0 | 印花税 |  |
| `transfer_fee` | `DecimalField` |  |  | 0 | 过户费 |  |
| `commission_known` | `BooleanField` | 是 |  | None | 手续费已采集 |  |
| `slippage_known` | `BooleanField` | 是 |  | None | 滑点已采集 |  |
| `stamp_duty_known` | `BooleanField` | 是 |  | None | 印花税已采集 |  |
| `transfer_fee_known` | `BooleanField` | 是 |  | None | 过户费已采集 |  |
| `estimated_cost` | `DecimalField` | 是 |  |  | 预估成本 |  |
| `estimated_cost_ratio` | `FloatField` | 是 |  |  | 预估成本比例 |  |
| `cost_variance` | `DecimalField` | 是 |  |  | 实际成本 - 预估成本 |  |
| `cost_variance_pct` | `FloatField` | 是 |  |  | 成本差异百分比 |  |
| `traded_at` | `DateTimeField` |  |  |  | 交易时间 |  |
| `notes` | `TextField` |  |  |  | 备注 |  |
| `broker_name` | `CharField` |  |  |  | 券商名称 |  |
| `external_trade_id` | `CharField` |  |  |  | 外部成交编号 |  |
| `broker_trade_key` | `CharField` | 是 | 是 |  | 券商成交去重键 |  |
| `raw_payload` | `JSONField` |  |  | dict | 原始导入行 |  |
| `import_batch` | `ForeignKey` | 是 |  |  | 导入批次 | BrokerTradeImportBatchModel |
| `broker_reconciliation_state` | `CharField` |  |  | BrokerReconciliationState.NOT_APPLICABLE.value | 券商成交核对状态 |  |
| `broker_reconciliation_details` | `JSONField` |  |  | dict | 券商成交核对详情 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### SingleOwnerAuthorityPolicyV1Model

- 来源文件：`apps/account/infrastructure/single_owner_authority_policy_v1_models.py`
- 数据表：`account_single_owner_authority_policy_v1`
- 说明：One immutable policy root or one immutable policy successor row.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `tenant_id` | `CharField` |  |  |  |  |  |
| `owner_id` | `CharField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `owner_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `authorization_content_hash` | `CharField` |  |  |  |  |  |
| `observed_at` | `DateTimeField` |  |  |  |  |  |
| `valid_from` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `mode` | `CharField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `expected_previous_content_hash` | `CharField` | 是 |  |  |  |  |
| `predecessor` | `OneToOneField` | 是 |  |  | self | self |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### InvestmentRuleModel

- 来源文件：`apps/account/infrastructure/trading_config_models.py`
- 数据表：`investment_rule`
- 说明：投资规则配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` | 是 |  |  | 用户（null表示全局默认规则） | User |
| `name` | `CharField` |  |  |  | 规则名称 |  |
| `rule_type` | `CharField` |  |  |  | 规则类型 |  |
| `priority` | `IntegerField` |  |  | 100 | 优先级（数字越小越优先） |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `conditions` | `JSONField` |  |  | dict | 触发条件 |  |
| `advice_template` | `TextField` |  |  |  | 建议模板 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### MacroSizingConfigModel

- 来源文件：`apps/account/infrastructure/trading_config_models.py`
- 说明：宏观感知仓位系数配置持久化模型。

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `regime_tiers_json` | `JSONField` |  |  |  | 格式：[{"min_confidence": 0.6, "factor": 1.0}, ...]，按 min_confidence 降序 |  |
| `pulse_tiers_json` | `JSONField` |  |  |  | 格式：[{"min_composite": 0.3, "max_composite": 99, "factor": 1.0}, ...] |  |
| `warning_factor` | `FloatField` |  |  | 0.5 | Pulse 转折预警时的系数覆盖值（0.0-1.0），优先于 pulse_tiers |  |
| `market_temperature_cold_factor` | `FloatField` |  |  | 1.0 | 市场温度 cold 分段对应的仓位系数。 |  |
| `market_temperature_warm_factor` | `FloatField` |  |  | 1.0 | 市场温度 warm 分段对应的仓位系数。 |  |
| `market_temperature_hot_factor` | `FloatField` |  |  | 0.9 | 市场温度 hot 分段对应的仓位系数。 |  |
| `market_temperature_overheat_factor` | `FloatField` |  |  | 0.75 | 市场温度 overheat 分段对应的仓位系数。 |  |
| `market_temperature_extreme_factor` | `FloatField` |  |  | 0.35 | 市场温度 extreme 分段对应的仓位系数。 |  |
| `block_new_position_on_extreme` | `BooleanField` |  |  | True | 当市场温度进入 extreme 时是否阻断新增仓位建议。 |  |
| `drawdown_tiers_json` | `JSONField` |  |  |  | 格式：[{"min_drawdown": 0.15, "factor": 0.0}, ...]，按 min_drawdown 降序 |  |
| `version` | `PositiveIntegerField` |  |  | 1 |  |  |
| `is_active` | `BooleanField` |  |  | True |  |  |
| `description` | `TextField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### StopLossConfigModel

- 来源文件：`apps/account/infrastructure/trading_config_models.py`
- 数据表：`stop_loss_config`
- 说明：止损配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `position` | `OneToOneField` |  |  |  | 关联持仓 | PositionModel |
| `stop_loss_type` | `CharField` |  |  | fixed | 止损类型 |  |
| `stop_loss_pct` | `FloatField` |  |  |  | 如 0.10 表示 10% 止损 |  |
| `trailing_stop_pct` | `FloatField` | 是 |  |  | 移动止损时使用，如 0.10 |  |
| `max_holding_days` | `IntegerField` | 是 |  |  | 时间止损时使用 |  |
| `highest_price` | `DecimalField` | 是 |  |  | 持仓期间最高价 |  |
| `highest_price_updated_at` | `DateTimeField` | 是 |  |  | 最高价更新时间 |  |
| `status` | `CharField` |  |  | active | 状态 |  |
| `activated_at` | `DateTimeField` |  |  |  | 激活时间 |  |
| `triggered_at` | `DateTimeField` | 是 |  |  | 触发时间 |  |
| `notes` | `TextField` |  |  |  | 备注 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### StopLossTriggerModel

- 来源文件：`apps/account/infrastructure/trading_config_models.py`
- 数据表：`stop_loss_trigger`
- 说明：止损触发记录表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `position` | `ForeignKey` |  |  |  | 关联持仓 | PositionModel |
| `trigger_type` | `CharField` |  |  |  | 触发类型 |  |
| `trigger_price` | `DecimalField` |  |  |  | 触发价格 |  |
| `trigger_time` | `DateTimeField` |  |  |  | 触发时间 |  |
| `trigger_reason` | `TextField` |  |  |  | 触发原因 |  |
| `pnl` | `DecimalField` |  |  |  | 盈亏金额 |  |
| `pnl_pct` | `FloatField` |  |  |  | 盈亏百分比 |  |
| `notes` | `TextField` |  |  |  | 备注 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### TakeProfitConfigModel

- 来源文件：`apps/account/infrastructure/trading_config_models.py`
- 数据表：`take_profit_config`
- 说明：止盈配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `position` | `OneToOneField` |  |  |  | 关联持仓 | PositionModel |
| `take_profit_pct` | `FloatField` |  |  |  | 如 0.20 表示 +20% |  |
| `partial_profit_levels` | `JSONField` | 是 |  |  | 如 [0.10, 0.20, 0.30] 表示在10%, 20%, 30%时各止盈一部分 |  |
| `is_active` | `BooleanField` |  |  | True | 是否激活 |  |
| `notes` | `TextField` |  |  |  | 备注 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### TradingCostConfigModel

- 来源文件：`apps/account/infrastructure/trading_config_models.py`
- 数据表：`trading_cost_config`
- 说明：交易费率配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `portfolio` | `OneToOneField` |  |  |  | 投资组合 | PortfolioModel |
| `commission_rate` | `FloatField` |  |  | 0.00025 | 默认万2.5，如 0.00025 |  |
| `min_commission` | `FloatField` |  |  |  | 单笔佣金不足此金额按此收取 |  |
| `stamp_duty_rate` | `FloatField` |  |  | 0.001 | 卖出时收取，默认千1，如 0.001 |  |
| `transfer_fee_rate` | `FloatField` |  |  | 2e-05 | 沪市股票双向收取，默认万0.2，如 0.00002 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### TransactionCostConfigModel

- 来源文件：`apps/account/infrastructure/trading_config_models.py`
- 数据表：`transaction_cost_config`
- 说明：交易成本配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `market` | `CharField` |  |  |  | 市场 |  |
| `asset_class` | `CharField` |  |  |  | 资产类别 |  |
| `commission_rate` | `FloatField` |  |  | 0.0003 | 如 0.0003 表示万分之三 |  |
| `slippage_rate` | `FloatField` |  |  | 0.0002 | 如 0.0002 表示万分之二 |  |
| `stamp_duty_rate` | `FloatField` |  |  | 0.001 | 仅卖出时收取，如 0.001 表示千分之一 |  |
| `transfer_fee_rate` | `FloatField` |  |  | 1e-05 | 如 0.00001 表示万分之一 |  |
| `min_commission` | `DecimalField` |  |  |  | 单笔交易最低佣金（元） |  |
| `cost_warning_threshold` | `FloatField` |  |  | 0.005 | 成本占交易额比例超过此值时预警，如 0.005 表示 0.5% |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `notes` | `TextField` |  |  |  | 备注 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |


## agent_runtime

### AgentArtifactModel

- 来源文件：`apps/agent_runtime/infrastructure/models.py`
- 数据表：`agent_artifact`
- 说明：AgentArtifact ORM Model - stores task artifacts.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `request_id` | `CharField` |  |  |  | Trace id |  |
| `task` | `ForeignKey` |  |  |  | Linked task | AgentTaskModel |
| `artifact_type` | `CharField` |  |  |  | Type of artifact |  |
| `artifact_name` | `CharField` |  |  |  | Artifact name |  |
| `artifact_data` | `JSONField` | 是 |  |  | Artifact content |  |
| `file_path` | `CharField` | 是 |  |  | Path to file if stored externally |  |
| `content_type` | `CharField` |  |  | application/json | MIME type |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### AgentContextSnapshotModel

- 来源文件：`apps/agent_runtime/infrastructure/models.py`
- 数据表：`agent_context_snapshot`
- 说明：AgentContextSnapshot ORM Model - context aggregation for tasks.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `request_id` | `CharField` |  |  |  | Trace id |  |
| `task` | `OneToOneField` |  |  |  | Linked task | AgentTaskModel |
| `domain` | `CharField` |  |  |  | Task domain |  |
| `snapshot_data` | `JSONField` |  |  | dict | Aggregated context data |  |
| `generated_at` | `DateTimeField` | 是 |  |  | Snapshot generation time |  |
| `data_freshness` | `JSONField` | 是 |  |  | Data freshness metrics |  |
| `decision_input_snapshot_id` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### AgentExecutionRecordModel

- 来源文件：`apps/agent_runtime/infrastructure/models.py`
- 数据表：`agent_execution_record`
- 说明：AgentExecutionRecord ORM Model - records execution results.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `request_id` | `CharField` |  |  |  | Trace id |  |
| `task` | `ForeignKey` | 是 |  |  | Linked task (optional for standalone approved capabilities) | AgentTaskModel |
| `proposal` | `ForeignKey` | 是 |  |  | Linked proposal | AgentProposalModel |
| `execution_status` | `CharField` |  |  | pending | Execution result status |  |
| `execution_output` | `JSONField` | 是 |  |  | Execution output data |  |
| `started_at` | `DateTimeField` | 是 |  |  | Execution start time |  |
| `completed_at` | `DateTimeField` | 是 |  |  | Execution completion time |  |
| `error_details` | `JSONField` | 是 |  |  | Error details if failed |  |
| `prompt_version_id` | `CharField` |  |  |  |  |  |
| `model_version` | `CharField` |  |  |  |  |  |
| `output_schema_version` | `CharField` |  |  |  |  |  |
| `eval_baseline_id` | `CharField` |  |  |  |  |  |
| `decision_input_snapshot_id` | `CharField` |  |  |  |  |  |
| `actual_tokens` | `PositiveIntegerField` |  |  | 0 |  |  |
| `actual_cost` | `DecimalField` |  |  | 0 |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### AgentGuardrailDecisionModel

- 来源文件：`apps/agent_runtime/infrastructure/models.py`
- 数据表：`agent_guardrail_decision`
- 说明：FROZEN: AgentGuardrailDecision ORM Model.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `request_id` | `CharField` |  |  |  | Trace id |  |
| `task` | `ForeignKey` | 是 |  |  | Linked task (optional) | AgentTaskModel |
| `proposal` | `ForeignKey` | 是 |  |  | Linked proposal (optional) | AgentProposalModel |
| `decision` | `CharField` |  |  | GuardrailDecision.ALLOWED.value | Guardrail decision |  |
| `reason_code` | `CharField` |  |  |  | Stable machine-readable reason |  |
| `message` | `TextField` |  |  |  | Human-readable summary |  |
| `evidence` | `JSONField` |  |  | dict | Supporting data |  |
| `requires_human` | `BooleanField` |  |  | False | Convenience flag |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### AgentHandoffModel

- 来源文件：`apps/agent_runtime/infrastructure/models.py`
- 数据表：`agent_handoff`
- 说明：AgentHandoff ORM Model - records task handoffs between agents/humans.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `request_id` | `CharField` |  |  |  | Trace id |  |
| `task` | `ForeignKey` |  |  |  | Linked task | AgentTaskModel |
| `from_agent` | `CharField` |  |  |  | Source agent identifier |  |
| `to_agent` | `CharField` |  |  |  | Target agent identifier |  |
| `handoff_reason` | `TextField` |  |  |  | Reason for handoff |  |
| `handoff_payload` | `JSONField` | 是 |  |  | Context payload for handoff |  |
| `handoff_status` | `CharField` |  |  | pending | Handoff status |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### AgentProposalModel

- 来源文件：`apps/agent_runtime/infrastructure/models.py`
- 数据表：`agent_proposal`
- 说明：FROZEN: AgentProposal ORM Model.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `request_id` | `CharField` |  | 是 |  | Trace id |  |
| `schema_version` | `CharField` |  |  | v1 | Schema version |  |
| `task` | `ForeignKey` | 是 |  |  | Linked task | AgentTaskModel |
| `proposal_type` | `CharField` |  |  |  | Type of proposal (e.g., rebalance, signal_write) |  |
| `status` | `CharField` |  |  | ProposalStatus.DRAFT.value | Proposal status |  |
| `risk_level` | `CharField` |  |  | RiskLevel.MEDIUM.value | Risk level assessment |  |
| `approval_required` | `BooleanField` |  |  | True | Server-evaluated approval requirement |  |
| `approval_status` | `CharField` |  |  | ApprovalStatus.PENDING.value | Current approval status |  |
| `approval_reason` | `TextField` | 是 |  |  | Human/system explanation |  |
| `proposal_payload` | `JSONField` |  |  | dict | Execution payload |  |
| `created_by` | `ForeignKey` | 是 |  |  | User id | settings.AUTH_USER_MODEL |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### AgentTaskModel

- 来源文件：`apps/agent_runtime/infrastructure/models.py`
- 数据表：`agent_task`
- 说明：FROZEN: AgentTask ORM Model.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `request_id` | `CharField` |  | 是 |  | Stable request trace id |  |
| `schema_version` | `CharField` |  |  | v1 | Schema version |  |
| `task_domain` | `CharField` |  |  |  | Task domain: research/monitoring/decision/execution/ops |  |
| `task_type` | `CharField` |  |  |  | Task subtype |  |
| `status` | `CharField` |  |  | TaskStatus.DRAFT.value | Current task status |  |
| `input_payload` | `JSONField` |  |  | dict | JSON input payload |  |
| `current_step` | `CharField` | 是 |  |  | Current step key |  |
| `last_error` | `JSONField` | 是 |  |  | Structured error payload |  |
| `requires_human` | `BooleanField` |  |  | False | Whether human intervention is needed |  |
| `created_by` | `ForeignKey` | 是 |  |  | User id if authenticated | settings.AUTH_USER_MODEL |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### AgentTaskStepModel

- 来源文件：`apps/agent_runtime/infrastructure/models.py`
- 数据表：`agent_task_step`
- 说明：AgentTaskStep ORM Model - represents a step in task execution.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `request_id` | `CharField` |  |  |  | Trace id |  |
| `task` | `ForeignKey` |  |  |  | Linked task | AgentTaskModel |
| `step_key` | `CharField` |  |  |  | Step identifier |  |
| `step_name` | `CharField` |  |  |  | Human readable step name |  |
| `step_index` | `IntegerField` |  |  | 0 | Order index |  |
| `status` | `CharField` |  |  | pending | Step status |  |
| `started_at` | `DateTimeField` | 是 |  |  | Step start time |  |
| `completed_at` | `DateTimeField` | 是 |  |  | Step completion time |  |
| `error_message` | `TextField` | 是 |  |  | Error if failed |  |
| `output_data` | `JSONField` | 是 |  |  | Step output |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### AgentTimelineEventModel

- 来源文件：`apps/agent_runtime/infrastructure/models.py`
- 数据表：`agent_timeline_event`
- 说明：FROZEN: AgentTimelineEvent ORM Model.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `request_id` | `CharField` |  |  |  | Trace id |  |
| `task` | `ForeignKey` |  |  |  | Linked task | AgentTaskModel |
| `proposal` | `ForeignKey` | 是 |  |  | Linked proposal (optional) | AgentProposalModel |
| `event_type` | `CharField` |  |  |  | Event type from frozen enum |  |
| `event_source` | `CharField` |  |  | EventSource.SYSTEM.value | Source of event (api/sdk/mcp/system/human) |  |
| `step_index` | `IntegerField` | 是 |  |  | Step sequence number |  |
| `event_payload` | `JSONField` |  |  | dict | Event details |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### TerminalAgentRunEventModel

- 来源文件：`apps/agent_runtime/infrastructure/models.py`
- 数据表：`agent_terminal_run_event`
- 说明：Short replayable event stream for one queued run.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `run` | `ForeignKey` |  |  |  |  | TerminalAgentRunModel |
| `event_id` | `CharField` |  | 是 |  |  |  |
| `sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `event_type` | `CharField` |  |  |  |  |  |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `data` | `JSONField` |  |  | dict |  |  |

### TerminalAgentRunExecutionModel

- 来源文件：`apps/agent_runtime/infrastructure/models.py`
- 数据表：`agent_terminal_run_execution`
- 说明：Durable execution result metadata for one queued run.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `run` | `OneToOneField` |  |  |  |  | TerminalAgentRunModel |
| `started_at` | `DateTimeField` | 是 |  |  |  |  |
| `heartbeat_at` | `DateTimeField` | 是 |  |  |  |  |
| `cancel_requested_at` | `DateTimeField` | 是 |  |  |  |  |
| `finished_at` | `DateTimeField` | 是 |  |  |  |  |
| `error_code` | `CharField` | 是 |  |  |  |  |
| `result_ref` | `CharField` | 是 |  |  |  |  |
| `result_payload` | `JSONField` | 是 |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### TerminalAgentRunModel

- 来源文件：`apps/agent_runtime/infrastructure/models.py`
- 数据表：`agent_terminal_run`
- 说明：Durable owner-scoped dispatch ledger for a queued Terminal Agent run.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `run_id` | `CharField` |  | 是 |  |  |  |
| `task` | `ForeignKey` |  |  |  |  | AgentTaskModel |
| `actor_user` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `client_request_id` | `CharField` |  |  |  |  |  |
| `request_digest` | `CharField` |  |  |  |  |  |
| `runtime_mode` | `CharField` |  |  |  |  |  |
| `dispatch_status` | `CharField` |  |  | TerminalRunStatus.QUEUED.value |  |  |
| `accepted_at` | `DateTimeField` |  |  |  |  |  |
| `deadline_at` | `DateTimeField` |  |  |  |  |  |
| `claimed_by` | `CharField` | 是 |  |  |  |  |
| `claimed_at` | `DateTimeField` | 是 |  |  |  |  |
| `heartbeat_at` | `DateTimeField` | 是 |  |  |  |  |
| `cancel_requested_at` | `DateTimeField` | 是 |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |


## ai_capability

### CapabilityCatalogModel

- 来源文件：`apps/ai_capability/infrastructure/models.py`
- 数据表：`ai_capability_catalog`
- 说明：System-level capability catalog for AI routing.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `capability_key` | `CharField` |  | 是 |  | Unique capability identifier (e.g., builtin.system_status) |  |
| `source_type` | `CharField` |  |  |  | Source type: builtin, terminal_command, mcp_tool, api |  |
| `source_ref` | `CharField` |  |  |  | Reference to original source (e.g., tool name, API path) |  |
| `name` | `CharField` |  |  |  | Human-readable capability name |  |
| `summary` | `TextField` |  |  |  | Short summary for AI routing |  |
| `description` | `TextField` |  |  |  | Detailed description |  |
| `route_group` | `CharField` |  |  | RouteGroup.TOOL.value | Routing group: builtin, tool, read_api, write_api, unsafe_api |  |
| `category` | `CharField` |  |  | general | Capability category |  |
| `semantic_key` | `CharField` |  |  |  | Optional semantic key for API/MCP capability de-duplication |  |
| `collected_semantic_key` | `CharField` |  |  |  | Semantic key collected from the source before manual override |  |
| `tags` | `JSONField` |  |  | list | List of tags for search |  |
| `when_to_use` | `JSONField` |  |  | list | List of usage scenarios |  |
| `when_not_to_use` | `JSONField` |  |  | list | List of non-usage scenarios |  |
| `examples` | `JSONField` |  |  | list | List of example queries |  |
| `input_schema` | `JSONField` |  |  | dict | JSON Schema for input parameters |  |
| `execution_kind` | `CharField` |  |  | ExecutionKind.SYNC.value | Execution type: sync, async, streaming |  |
| `execution_target` | `JSONField` |  |  | dict | Execution target configuration |  |
| `risk_level` | `CharField` |  |  | RiskLevel.SAFE.value | Risk level: safe, low, medium, high, critical |  |
| `requires_mcp` | `BooleanField` |  |  | False | Requires MCP permission |  |
| `requires_confirmation` | `BooleanField` |  |  | False | Requires user confirmation before execution |  |
| `enabled_for_routing` | `BooleanField` |  |  | True | Enabled for AI routing |  |
| `enabled_for_terminal` | `BooleanField` |  |  | True | Enabled for terminal entrypoint |  |
| `enabled_for_chat` | `BooleanField` |  |  | True | Enabled for chat entrypoint |  |
| `enabled_for_agent` | `BooleanField` |  |  | True | Enabled for agent entrypoint |  |
| `visibility` | `CharField` |  |  | Visibility.PUBLIC.value | Visibility level: public, internal, admin, hidden |  |
| `auto_collected` | `BooleanField` |  |  | False | Automatically collected from source |  |
| `review_status` | `CharField` |  |  | ReviewStatus.AUTO.value | Review status: auto, pending, approved, rejected |  |
| `priority_weight` | `FloatField` |  |  | 1.0 | Priority weight for scoring (higher = more important) |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |
| `last_synced_at` | `DateTimeField` | 是 |  |  | Last synchronization timestamp |  |

### CapabilityRoutingLogModel

- 来源文件：`apps/ai_capability/infrastructure/models.py`
- 数据表：`ai_capability_routing_log`
- 说明：Log of capability routing decisions and executions.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `entrypoint` | `CharField` |  |  |  | Entrypoint: terminal, chat, agent |  |
| `user` | `ForeignKey` | 是 |  |  |  | settings.AUTH_USER_MODEL |
| `session_id` | `CharField` |  |  |  |  |  |
| `raw_message` | `TextField` |  |  |  |  |  |
| `retrieved_candidates` | `JSONField` |  |  | list | List of retrieved capability keys |  |
| `selected_capability_key` | `CharField` | 是 |  |  |  |  |
| `confidence` | `FloatField` |  |  | 0.0 |  |  |
| `decision` | `CharField` |  |  | CapabilityDecision.CHAT.value |  |  |
| `fallback_reason` | `TextField` |  |  |  |  |  |
| `execution_result` | `TextField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### CapabilitySemanticAuditModel

- 来源文件：`apps/ai_capability/infrastructure/models.py`
- 数据表：`ai_capability_semantic_audit`
- 说明：Immutable evidence row for one semantic governance correction.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `batch_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `idempotency_key` | `CharField` |  |  |  |  |  |
| `capability_key` | `CharField` |  |  |  |  |  |
| `action` | `CharField` |  |  |  |  |  |
| `old_collected_value` | `CharField` |  |  |  |  |  |
| `old_effective_value` | `CharField` |  |  |  |  |  |
| `new_effective_value` | `CharField` |  |  |  |  |  |
| `reason` | `TextField` |  |  |  |  |  |
| `operator` | `ForeignKey` | 是 |  |  |  | settings.AUTH_USER_MODEL |
| `request_fingerprint` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### CapabilitySemanticOverrideModel

- 来源文件：`apps/ai_capability/infrastructure/models.py`
- 数据表：`ai_capability_semantic_override`
- 说明：Current operator-owned semantic-key override for one capability.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `capability_key` | `CharField` |  | 是 |  |  |  |
| `semantic_key` | `CharField` |  |  |  |  |  |
| `reason` | `TextField` |  |  |  |  |  |
| `is_active` | `BooleanField` |  |  | True |  |  |
| `updated_by` | `ForeignKey` | 是 |  |  |  | settings.AUTH_USER_MODEL |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### CapabilitySyncLogModel

- 来源文件：`apps/ai_capability/infrastructure/models.py`
- 数据表：`ai_capability_sync_log`
- 说明：Log of capability synchronization operations.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `sync_type` | `CharField` |  |  |  |  |  |
| `started_at` | `DateTimeField` |  |  |  |  |  |
| `finished_at` | `DateTimeField` | 是 |  |  |  |  |
| `total_discovered` | `IntegerField` |  |  | 0 |  |  |
| `created_count` | `IntegerField` |  |  | 0 |  |  |
| `updated_count` | `IntegerField` |  |  | 0 |  |  |
| `disabled_count` | `IntegerField` |  |  | 0 |  |  |
| `error_count` | `IntegerField` |  |  | 0 |  |  |
| `summary_payload` | `JSONField` |  |  | dict |  |  |


## ai_provider

### AIProviderConfig

- 来源文件：`apps/ai_provider/infrastructure/models.py`
- 数据表：`ai_provider_config`
- 说明：AI提供商配置 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | `CharField` |  |  |  | 配置名称（唯一标识） |  |
| `scope` | `CharField` |  |  | system | 配置归属范围（system/user） |  |
| `owner_user` | `ForeignKey` | 是 |  |  | 当 scope=user 时对应的拥有者 | settings.AUTH_USER_MODEL |
| `provider_type` | `CharField` |  |  |  | 提供商类型 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `priority` | `IntegerField` |  |  | 10 | 优先级（数字越小越优先，用于failover） |  |
| `base_url` | `URLField` |  |  |  | API Base URL（如 https://api.openai.com/v1） |  |
| `api_key` | `CharField` |  |  |  | API Key (plaintext, deprecated - use api_key_encrypted) |  |
| `api_key_encrypted` | `TextField` |  |  |  | API Key (encrypted at rest) |  |
| `default_model` | `CharField` |  |  | gpt-3.5-turbo | 默认模型名称 |  |
| `api_mode` | `CharField` |  |  | dual | OpenAI API 模式：dual/responses_only/chat_only |  |
| `fallback_enabled` | `BooleanField` |  |  | True | dual 模式下是否允许从 Responses 回退到 Chat Completions |  |
| `daily_budget_limit` | `DecimalField` | 是 |  |  | 每日预算限制（美元） |  |
| `monthly_budget_limit` | `DecimalField` | 是 |  |  | 每月预算限制（美元） |  |
| `extra_config` | `JSONField` |  |  | dict | 额外配置参数 |  |
| `description` | `TextField` |  |  |  | 描述 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |
| `last_used_at` | `DateTimeField` | 是 |  |  | 最后使用时间 |  |

### AIUserFallbackQuota

- 来源文件：`apps/ai_provider/infrastructure/models.py`
- 数据表：`ai_user_fallback_quota`
- 说明：User-scoped quota for consuming system fallback providers.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `OneToOneField` |  |  |  |  | settings.AUTH_USER_MODEL |
| `daily_limit` | `DecimalField` | 是 |  |  | 每日系统兜底额度（美元） |  |
| `monthly_limit` | `DecimalField` | 是 |  |  | 每月系统兜底额度（美元） |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用用户系统兜底额度 |  |
| `admin_note` | `TextField` |  |  |  | 管理员备注 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### AppendOnlyUsageEvidenceMixin

- 来源文件：`apps/ai_provider/infrastructure/models.py`
- 抽象模型：是
- 说明：Reject mutation and deletion of inserted usage evidence.


## alpha

### AlphaAlertModel

- 来源文件：`apps/alpha/infrastructure/models.py`
- 数据表：`alpha_alert`
- 说明：Alpha 告警 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `alert_type` | `CharField` |  |  |  | 告警类型 |  |
| `severity` | `CharField` |  |  | SEVERITY_WARNING | 严重程度 |  |
| `title` | `CharField` |  |  |  | 告警标题 |  |
| `message` | `TextField` |  |  |  | 告警详情 |  |
| `metadata` | `JSONField` | 是 |  |  | 元数据 |  |
| `is_resolved` | `BooleanField` |  |  | False | 是否已解决 |  |
| `resolved_at` | `DateTimeField` | 是 |  |  | 解决时间 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### AlphaMonitoringArchiveModel

- 来源文件：`apps/alpha/infrastructure/models.py`
- 数据表：`alpha_monitoring_archive`
- 说明：Long-term archive for Alpha monitoring cleanup summaries.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `archive_key` | `CharField` |  | 是 |  |  |  |
| `archive_type` | `CharField` |  |  | ARCHIVE_SCORE_CACHE_CLEANUP |  |  |
| `cutoff_date` | `DateField` |  |  |  |  |  |
| `row_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `payload` | `JSONField` |  |  | dict |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### AlphaScoreCacheModel

- 来源文件：`apps/alpha/infrastructure/models.py`
- 数据表：`alpha_score_cache`
- 说明：Alpha 评分缓存 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `universe_id` | `CharField` |  |  |  | 股票池标识 |  |
| `scope_hash` | `CharField` | 是 |  |  | 账户驱动股票池 scope hash |  |
| `scope_label` | `CharField` | 是 |  |  | 账户驱动股票池展示名称 |  |
| `scope_metadata` | `JSONField` | 是 |  |  | 账户驱动股票池元数据 |  |
| `intended_trade_date` | `DateField` |  |  |  | 计划交易日期 |  |
| `provider_source` | `CharField` |  |  |  | 提供者来源 |  |
| `asof_date` | `DateField` |  |  |  | 信号真实生成日期 |  |
| `model_id` | `CharField` | 是 |  |  | 模型标识 |  |
| `model_artifact_hash` | `CharField` | 是 |  |  | 模型文件哈希 |  |
| `feature_set_id` | `CharField` | 是 |  |  | 特征集标识 |  |
| `label_id` | `CharField` | 是 |  |  | 标签标识 |  |
| `data_version` | `CharField` | 是 |  |  | 数据版本 |  |
| `scores` | `JSONField` |  |  |  | 评分结果 [{code, score, rank, factors, confidence}, ...] |  |
| `status` | `CharField` |  |  | STATUS_AVAILABLE | 状态 |  |
| `metrics_snapshot` | `JSONField` | 是 |  |  | 指标快照 |  |
| `user` | `ForeignKey` | 是 |  |  | 上传用户（None=系统级） | settings.AUTH_USER_MODEL |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### QlibModelRegistryModel

- 来源文件：`apps/alpha/infrastructure/models.py`
- 数据表：`qlib_model_registry`
- 说明：Qlib 模型注册表 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `model_name` | `CharField` |  |  |  | 模型名称 |  |
| `artifact_hash` | `CharField` |  | 是 |  | 模型文件哈希 |  |
| `model_type` | `CharField` |  |  |  | 模型类型 |  |
| `universe` | `CharField` |  |  |  | 股票池 |  |
| `train_config` | `JSONField` |  |  |  | 训练配置 |  |
| `feature_set_id` | `CharField` |  |  |  | 特征集标识 |  |
| `label_id` | `CharField` |  |  |  | 标签标识 |  |
| `data_version` | `CharField` |  |  |  | 数据版本 |  |
| `ic` | `DecimalField` | 是 |  |  | IC 值 |  |
| `icir` | `DecimalField` | 是 |  |  | ICIR 值 |  |
| `rank_ic` | `DecimalField` | 是 |  |  | Rank IC 值 |  |
| `model_path` | `CharField` |  |  |  | 模型文件路径 |  |
| `is_active` | `BooleanField` |  |  | False | 是否激活 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `activated_at` | `DateTimeField` | 是 |  |  | 激活时间 |  |
| `activated_by` | `CharField` | 是 |  |  | 激活者 |  |


## alpha_trigger

### AlphaCandidateModel

- 来源文件：`apps/alpha_trigger/infrastructure/models.py`
- 数据表：`alpha_candidate`
- 说明：Alpha 候选 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `candidate_id` | `CharField` |  | 是 |  | 候选唯一标识符 |  |
| `trigger_id` | `CharField` |  |  |  | 触发器 ID |  |
| `asset_code` | `CharField` |  |  |  | 资产代码 |  |
| `asset_class` | `CharField` |  |  |  | 资产类别 |  |
| `direction` | `CharField` |  |  | LONG | 方向 |  |
| `strength` | `CharField` |  |  | MODERATE | 信号强度 |  |
| `confidence` | `FloatField` |  |  | 0.5 | 置信度 (0-1) |  |
| `status` | `CharField` |  |  | WATCH | 状态 |  |
| `thesis` | `TextField` |  |  |  | 投资论点 |  |
| `entry_zone` | `JSONField` |  |  | dict | 入场区域 |  |
| `exit_zone` | `JSONField` |  |  | dict | 出场区域 |  |
| `time_horizon` | `IntegerField` |  |  | 90 | 时间窗口（天） |  |
| `expected_return` | `FloatField` | 是 |  |  | 预期收益率 |  |
| `risk_level` | `CharField` |  |  | MEDIUM | 风险等级 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |
| `status_changed_at` | `DateTimeField` | 是 |  |  | 状态变更时间 |  |
| `promoted_to_signal_at` | `DateTimeField` | 是 |  |  | 提升为信号的时间 |  |
| `custom_data` | `JSONField` |  |  | dict | 自定义数据 |  |
| `last_decision_request_id` | `CharField` |  |  |  | 最后决策请求 ID |  |
| `last_execution_status` | `CharField` |  |  |  | 最后执行状态 |  |

### AlphaTriggerModel

- 来源文件：`apps/alpha_trigger/infrastructure/models.py`
- 数据表：`alpha_trigger`
- 说明：Alpha 触发器 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `trigger_id` | `CharField` |  | 是 |  | 触发器唯一标识符 |  |
| `trigger_type` | `CharField` |  |  | MOMENTUM_SIGNAL | 触发器类型 |  |
| `asset_code` | `CharField` |  |  |  | 资产代码 |  |
| `asset_class` | `CharField` |  |  |  | 资产类别 |  |
| `direction` | `CharField` |  |  | LONG | 方向 |  |
| `trigger_condition` | `JSONField` |  |  | dict | 触发条件 |  |
| `invalidation_conditions` | `JSONField` |  |  | list | 证伪条件列表 |  |
| `strength` | `CharField` |  |  | MODERATE | 信号强度 |  |
| `confidence` | `FloatField` |  |  | 0.5 | 置信度 (0-1) |  |
| `status` | `CharField` |  |  | ACTIVE | 状态 |  |
| `thesis` | `TextField` |  |  |  | 投资论点 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `triggered_at` | `DateTimeField` | 是 |  |  | 触发时间 |  |
| `invalidated_at` | `DateTimeField` | 是 |  |  | 证伪时间 |  |
| `expires_at` | `DateTimeField` | 是 |  |  | 过期时间 |  |
| `source_signal_id` | `CharField` |  |  |  | 源信号 ID |  |
| `related_regime` | `CharField` |  |  |  | 相关 Regime |  |
| `related_policy_level` | `IntegerField` | 是 |  |  | 相关 Policy 档位 |  |
| `custom_data` | `JSONField` |  |  | dict | 自定义数据 |  |


## asset_analysis

### AssetAnalysisAlert

- 来源文件：`apps/asset_analysis/infrastructure/models.py`
- 数据表：`asset_analysis_alert`
- 说明：资产分析告警表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `severity` | `CharField` |  |  |  | 严重程度 |  |
| `alert_type` | `CharField` |  |  |  | 告警类型 |  |
| `title` | `CharField` |  |  |  | 告警标题 |  |
| `message` | `TextField` |  |  |  | 告警消息 |  |
| `asset_type` | `CharField` | 是 |  |  | 相关资产类型 |  |
| `asset_code` | `CharField` | 是 |  |  | 相关资产代码 |  |
| `context` | `JSONField` |  |  | dict | 存储额外的调试信息 |  |
| `stack_trace` | `TextField` | 是 |  |  | 堆栈跟踪 |  |
| `is_resolved` | `BooleanField` |  |  | False | 是否已解决 |  |
| `resolved_at` | `DateTimeField` | 是 |  |  | 解决时间 |  |
| `resolved_by` | `IntegerField` | 是 |  |  | 解决人ID |  |
| `resolution_notes` | `TextField` | 是 |  |  | 解决备注 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### AssetConfigModel

- 来源文件：`apps/asset_analysis/infrastructure/models.py`
- 数据表：`asset_config`
- 说明：资产类别配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `asset_class` | `CharField` |  | 是 |  | 资产类别代码 |  |
| `display_name` | `CharField` |  |  |  | 显示名称 |  |
| `ticker_symbol` | `CharField` |  |  |  | 如 000300.SH |  |
| `data_source` | `CharField` |  |  | tushare | 数据源 |  |
| `category` | `CharField` |  |  |  | 资产分类 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `description` | `TextField` |  |  |  | 描述 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### AssetPoolConfig

- 来源文件：`apps/asset_analysis/infrastructure/models.py`
- 数据表：`asset_pool_config`
- 说明：资产池配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | `CharField` |  | 是 |  | 配置名称 |  |
| `description` | `TextField` | 是 |  |  | 配置描述 |  |
| `pool_type` | `CharField` |  |  |  | 资产池类型 |  |
| `asset_category` | `CharField` |  |  |  | 资产类别 |  |
| `min_total_score` | `FloatField` |  |  | 60.0 | 最低综合评分 |  |
| `min_regime_score` | `FloatField` |  |  | 50.0 | 最低Regime评分 |  |
| `min_policy_score` | `FloatField` |  |  | 50.0 | 最低Policy评分 |  |
| `max_total_score` | `FloatField` |  |  | 30.0 | 最高综合评分（禁投） |  |
| `max_regime_score` | `FloatField` |  |  | 40.0 | 最高Regime评分（禁投） |  |
| `max_policy_score` | `FloatField` |  |  | 40.0 | 最高Policy评分（禁投） |  |
| `watch_min_score` | `FloatField` |  |  | 30.0 | 观察池最低分 |  |
| `watch_max_score` | `FloatField` |  |  | 60.0 | 观察池最高分 |  |
| `max_volatility` | `FloatField` | 是 |  |  | 最大波动率 |  |
| `max_drawdown` | `FloatField` | 是 |  |  | 最大回撤 |  |
| `min_market_cap` | `FloatField` | 是 |  |  | 最小市值（元） |  |
| `max_pe_ratio` | `FloatField` | 是 |  |  | 最大PE |  |
| `max_pb_ratio` | `FloatField` | 是 |  |  | 最大PB |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### AssetPoolEntry

- 来源文件：`apps/asset_analysis/infrastructure/models.py`
- 数据表：`asset_pool_entry`
- 说明：资产池条目表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `asset_category` | `CharField` |  |  |  | 资产类别 |  |
| `asset_code` | `CharField` |  |  |  | 资产代码 |  |
| `asset_name` | `CharField` |  |  |  | 资产名称 |  |
| `pool_type` | `CharField` |  |  |  | 资产池类型 |  |
| `total_score` | `FloatField` |  |  |  | 综合评分 |  |
| `regime_score` | `FloatField` |  |  |  | Regime评分 |  |
| `policy_score` | `FloatField` |  |  |  | Policy评分 |  |
| `sentiment_score` | `FloatField` |  |  |  | Sentiment评分 |  |
| `signal_score` | `FloatField` |  |  |  | Signal评分 |  |
| `entry_date` | `DateField` |  |  |  | 入池日期 |  |
| `entry_reason` | `CharField` | 是 |  |  | 入池原因 |  |
| `exit_date` | `DateField` | 是 |  |  | 出池日期 |  |
| `exit_reason` | `CharField` | 是 |  |  | 出池原因 |  |
| `is_active` | `BooleanField` |  |  | True | 是否活跃 |  |
| `risk_level` | `CharField` |  |  | 未知 | 风险等级 |  |
| `volatility` | `FloatField` | 是 |  |  | 波动率 |  |
| `max_drawdown` | `FloatField` | 是 |  |  | 最大回撤 |  |
| `sector` | `CharField` | 是 |  |  | 行业 |  |
| `market_cap` | `FloatField` | 是 |  |  | 市值（元） |  |
| `pe_ratio` | `FloatField` | 是 |  |  | PE倍数 |  |
| `pb_ratio` | `FloatField` | 是 |  |  | PB倍数 |  |
| `context` | `JSONField` |  |  | dict | 上下文信息 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### AssetScoreCache

- 来源文件：`apps/asset_analysis/infrastructure/models.py`
- 数据表：`asset_score_cache`
- 说明：资产评分缓存表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `asset_type` | `CharField` |  |  |  | 资产类型 |  |
| `asset_code` | `CharField` |  |  |  | 资产代码 |  |
| `asset_name` | `CharField` |  |  |  | 资产名称 |  |
| `score_date` | `DateField` |  |  |  | 评分日期 |  |
| `regime` | `CharField` |  |  |  | Regime |  |
| `policy_level` | `CharField` |  |  |  | 政策档位 |  |
| `sentiment_index` | `FloatField` |  |  |  | 情绪指数 |  |
| `regime_score` | `FloatField` |  |  | 0.0 | Regime 得分 |  |
| `policy_score` | `FloatField` |  |  | 0.0 | Policy 得分 |  |
| `sentiment_score` | `FloatField` |  |  | 0.0 | Sentiment 得分 |  |
| `signal_score` | `FloatField` |  |  | 0.0 | Signal 得分 |  |
| `total_score` | `FloatField` |  |  | 0.0 | 综合得分 |  |
| `rank` | `IntegerField` |  |  | 0 | 排名 |  |
| `allocation_percent` | `FloatField` |  |  | 0.0 | 推荐比例(%) |  |
| `risk_level` | `CharField` |  |  | 未知 | 风险等级 |  |
| `custom_scores` | `JSONField` |  |  | dict | 自定义得分 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### AssetScoringLog

- 来源文件：`apps/asset_analysis/infrastructure/models.py`
- 数据表：`asset_scoring_log`
- 说明：资产评分日志表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `asset_type` | `CharField` |  |  |  | 资产类型 |  |
| `request_source` | `CharField` |  |  |  | 如: fund_dashboard, equity_screen, api_call |  |
| `user_id` | `IntegerField` | 是 |  |  | 用户ID |  |
| `regime` | `CharField` |  |  |  | Regime |  |
| `policy_level` | `CharField` |  |  |  | 政策档位 |  |
| `sentiment_index` | `FloatField` |  |  |  | 情绪指数 |  |
| `active_signals_count` | `IntegerField` |  |  | 0 | 激活信号数 |  |
| `weight_config_name` | `CharField` |  |  |  | 权重配置名称 |  |
| `regime_weight` | `FloatField` |  |  |  | Regime 权重 |  |
| `policy_weight` | `FloatField` |  |  |  | Policy 权重 |  |
| `sentiment_weight` | `FloatField` |  |  |  | Sentiment 权重 |  |
| `signal_weight` | `FloatField` |  |  |  | Signal 权重 |  |
| `filters` | `JSONField` |  |  | dict | 筛选条件 |  |
| `total_assets` | `IntegerField` |  |  | 0 | 总资产数 |  |
| `scored_assets` | `IntegerField` |  |  | 0 | 已评分资产数 |  |
| `filtered_assets` | `IntegerField` |  |  | 0 | 筛选后资产数 |  |
| `execution_time_ms` | `IntegerField` | 是 |  |  | 执行时间(毫秒) |  |
| `cache_hit` | `BooleanField` |  |  | False | 是否命中缓存 |  |
| `status` | `CharField` |  |  | success | 状态 |  |
| `error_message` | `TextField` | 是 |  |  | 错误信息 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### WeightConfigModel

- 来源文件：`apps/asset_analysis/infrastructure/models.py`
- 数据表：`asset_weight_config`
- 说明：多维度评分权重配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | `CharField` |  | 是 |  | 如: default, policy_crisis, sentiment_extreme |  |
| `description` | `TextField` | 是 |  |  | 配置描述 |  |
| `regime_weight` | `FloatField` |  |  | 0.4 | Regime 权重 |  |
| `policy_weight` | `FloatField` |  |  | 0.25 | Policy 权重 |  |
| `sentiment_weight` | `FloatField` |  |  | 0.2 | Sentiment 权重 |  |
| `signal_weight` | `FloatField` |  |  | 0.15 | Signal 权重 |  |
| `asset_type` | `CharField` | 是 |  |  | 为空表示通用配置 |  |
| `market_condition` | `CharField` | 是 |  |  | 如: crisis, extreme_sentiment |  |
| `is_active` | `BooleanField` |  |  | True | 是否激活 |  |
| `priority` | `IntegerField` |  |  | 0 | 数字越大优先级越高 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |


## audit

### AttributionReport

- 来源文件：`apps/audit/infrastructure/models.py`
- 数据表：`audit_attribution_report`
- 说明：归因分析报告（详细版本）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `backtest` | `ForeignKey` |  |  |  | 关联回测 | BacktestResultModel |
| `period_start` | `DateField` |  |  |  | 分析起始日期 |  |
| `period_end` | `DateField` |  |  |  | 分析结束日期 |  |
| `attribution_method` | `CharField` |  |  | heuristic | 使用的归因分析方法 |  |
| `regime_timing_pnl` | `FloatField` |  |  |  | 因 Regime 判断正确/错误产生的收益/损失 |  |
| `asset_selection_pnl` | `FloatField` |  |  |  | 因资产选择正确/错误产生的收益/损失 |  |
| `interaction_pnl` | `FloatField` |  |  |  | 择时与选股的交互作用 |  |
| `total_pnl` | `FloatField` |  |  |  | 总收益 |  |
| `regime_accuracy` | `FloatField` |  |  |  | 实际 Regime 与预测 Regime 的匹配度（0-1） |  |
| `regime_predicted` | `CharField` |  |  |  | 预测 Regime |  |
| `regime_actual` | `CharField` | 是 |  |  | 实际 Regime |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### AuditReport

- 来源文件：`apps/audit/infrastructure/models.py`
- 数据表：`audit_report`
- 说明：审计报告（已存在，保持不变）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `period_start` | `DateField` |  |  |  |  |  |
| `period_end` | `DateField` |  |  |  |  |  |
| `total_pnl` | `FloatField` |  |  |  |  |  |
| `regime_timing_pnl` | `FloatField` |  |  |  |  |  |
| `asset_selection_pnl` | `FloatField` |  |  |  |  |  |
| `interaction_pnl` | `FloatField` |  |  |  |  |  |
| `regime_predicted` | `CharField` |  |  |  |  |  |
| `regime_actual` | `CharField` |  |  |  |  |  |
| `lesson_learned` | `TextField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### ConfidenceConfigModel

- 来源文件：`apps/audit/infrastructure/models.py`
- 数据表：`audit_confidence_config`
- 说明：置信度配置（Phase 4）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `day_0_coefficient` | `FloatField` |  |  | 0.6 | 数据发布当天的置信度系数 |  |
| `day_7_coefficient` | `FloatField` |  |  | 0.5 | 数据发布1周后的置信度系数 |  |
| `day_14_coefficient` | `FloatField` |  |  | 0.4 | 数据发布2周后的置信度系数 |  |
| `day_30_coefficient` | `FloatField` |  |  | 0.3 | 数据发布1个月后的置信度系数 |  |
| `daily_data_bonus` | `FloatField` |  |  | 0.2 | 有日度数据支持时的置信度加成 |  |
| `weekly_data_bonus` | `FloatField` |  |  | 0.1 | 有周度数据支持时的置信度加成 |  |
| `daily_consistency_bonus` | `FloatField` |  |  | 0.1 | 日度数据与月度数据一致时的加成 |  |
| `base_confidence` | `FloatField` |  |  | 0.5 | 默认的基础置信度 |  |
| `daily_persist_threshold` | `IntegerField` |  |  | 10 | 日度信号持续多少天后采用日度信号 |  |
| `hybrid_weight_daily` | `FloatField` |  |  | 0.3 | 混合模式中日度信号的权重 |  |
| `hybrid_weight_monthly` | `FloatField` |  |  | 0.7 | 混合模式中月度信号的权重 |  |
| `decay_threshold` | `FloatField` |  |  | 0.2 | F1分数低于此值视为衰减 |  |
| `decay_penalty` | `FloatField` |  |  | 0.5 | 衰减后权重乘以该系数 |  |
| `improvement_threshold` | `FloatField` |  |  | 0.1 | F1提升超过此值给予奖励 |  |
| `improvement_bonus` | `FloatField` |  |  | 1.2 | 改进后权重乘以该系数 |  |
| `description` | `TextField` |  |  |  | 说明 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### ExperienceSummary

- 来源文件：`apps/audit/infrastructure/models.py`
- 数据表：`audit_experience_summary`
- 说明：经验总结

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `report` | `ForeignKey` |  |  |  | 归因报告 | AttributionReport |
| `lesson` | `TextField` |  |  |  | 从本次回测中学到的教训 |  |
| `recommendation` | `TextField` |  |  |  | 针对性的改进措施 |  |
| `priority` | `CharField` |  |  | MEDIUM | 优先级 |  |
| `is_applied` | `BooleanField` |  |  | False | 是否已应用 |  |
| `applied_at` | `DateTimeField` | 是 |  |  | 应用时间 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### IndicatorPerformanceModel

- 来源文件：`apps/audit/infrastructure/models.py`
- 数据表：`audit_indicator_performance`
- 说明：指标表现历史记录

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `indicator_code` | `CharField` |  |  |  | 指标代码 |  |
| `validation_run_id` | `CharField` | 是 |  |  | 验证运行ID |  |
| `evaluation_period_start` | `DateField` |  |  |  | 评估起始日期 |  |
| `evaluation_period_end` | `DateField` |  |  |  | 评估结束日期 |  |
| `true_positive_count` | `IntegerField` |  |  | 0 | 真阳性数 |  |
| `false_positive_count` | `IntegerField` |  |  | 0 | 假阳性数 |  |
| `true_negative_count` | `IntegerField` |  |  | 0 | 真阴性数 |  |
| `false_negative_count` | `IntegerField` |  |  | 0 | 假阴性数 |  |
| `precision` | `FloatField` | 是 |  |  | 精确率 |  |
| `recall` | `FloatField` | 是 |  |  | 召回率 |  |
| `f1_score` | `FloatField` | 是 |  |  | F1 分数 |  |
| `accuracy` | `FloatField` | 是 |  |  | 准确率 |  |
| `lead_time_mean` | `FloatField` |  |  | 0.0 | 平均领先时间(月) |  |
| `lead_time_std` | `FloatField` |  |  | 0.0 | 领先时间标准差 |  |
| `pre_2015_correlation` | `FloatField` | 是 |  |  | 2015年前相关性 |  |
| `post_2015_correlation` | `FloatField` | 是 |  |  | 2015年后相关性 |  |
| `stability_score` | `FloatField` |  |  | 0.0 | 稳定性分数 |  |
| `decay_rate` | `FloatField` |  |  | 0.0 | 信号衰减率 |  |
| `signal_strength` | `FloatField` |  |  | 0.0 | 信号强度 |  |
| `recommended_action` | `CharField` | 是 |  |  | 建议操作 |  |
| `recommended_weight` | `FloatField` |  |  | 0.0 | 建议权重 |  |
| `confidence_level` | `FloatField` |  |  | 0.0 | 置信度 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### IndicatorThresholdConfigModel

- 来源文件：`apps/audit/infrastructure/models.py`
- 数据表：`audit_indicator_threshold_config`
- 说明：指标阈值配置（所有阈值从数据库读取，不硬编码）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `indicator_code` | `CharField` |  | 是 |  | 指标代码 |  |
| `indicator_name` | `CharField` |  |  |  | 指标名称 |  |
| `level_low` | `FloatField` | 是 |  |  | 低水平阈值（如 PMI < 50 为收缩） |  |
| `level_high` | `FloatField` | 是 |  |  | 高水平阈值（如 PMI > 50 为扩张） |  |
| `base_weight` | `FloatField` |  |  | 1.0 | 指标的基础权重（0-1） |  |
| `min_weight` | `FloatField` |  |  | 0.0 | 最小权重 |  |
| `max_weight` | `FloatField` |  |  | 1.0 | 最大权重 |  |
| `decay_threshold` | `FloatField` |  |  | 0.2 | F1 分数低于此值视为衰减 |  |
| `decay_penalty` | `FloatField` |  |  | 0.5 | 衰减惩罚系数 |  |
| `improvement_threshold` | `FloatField` |  |  | 0.1 | 改进阈值 |  |
| `improvement_bonus` | `FloatField` |  |  | 1.2 | 改进奖励系数 |  |
| `action_thresholds` | `JSONField` |  |  | dict | {"keep_min_f1": 0.6, "reduce_min_f1": 0.4, "remove_max_f1": 0.3} |  |
| `validation_periods` | `JSONField` |  |  | list | [{"name": "刚兑时期", "start": "2005-01-01", "end": "2017-12-31"}] |  |
| `category` | `CharField` |  |  |  | 如 growth, inflation, sentiment |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `description` | `TextField` |  |  |  | 说明 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### LossAnalysis

- 来源文件：`apps/audit/infrastructure/models.py`
- 数据表：`audit_loss_analysis`
- 说明：损失归因分析

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `report` | `ForeignKey` |  |  |  | 归因报告 | AttributionReport |
| `loss_source` | `CharField` |  |  |  | 损失来源 |  |
| `impact` | `FloatField` |  |  |  | 该因素造成的收益/损失 |  |
| `impact_percentage` | `FloatField` |  |  |  | 占总损失的百分比 |  |
| `description` | `TextField` |  |  |  | 损失产生的具体原因和情境 |  |
| `improvement_suggestion` | `TextField` |  |  |  | 改进建议 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### OperationLogModel

- 来源文件：`apps/audit/infrastructure/models.py`
- 数据表：`audit_operation_log`
- 说明：MCP/SDK 操作审计日志

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `id` | `UUIDField` |  |  | uuid.uuid4 | 日志ID |  |
| `request_id` | `CharField` |  |  |  | 用于关联请求链路 |  |
| `user_id` | `IntegerField` | 是 |  |  | 用户ID |  |
| `username` | `CharField` |  |  | anonymous | 用户名 |  |
| `ip_address` | `GenericIPAddressField` | 是 |  |  | IP地址 |  |
| `user_agent` | `CharField` |  |  |  | User Agent |  |
| `source` | `CharField` |  |  | MCP | MCP/SDK/API |  |
| `client_id` | `CharField` |  |  |  | 客户端ID |  |
| `operation_type` | `CharField` |  |  |  | MCP_CALL/API_ACCESS/DATA_MODIFY |  |
| `module` | `CharField` |  |  |  | signal/policy/backtest/... |  |
| `action` | `CharField` |  |  |  | CREATE/READ/UPDATE/DELETE/EXECUTE |  |
| `resource_type` | `CharField` |  |  |  | 资源类型 |  |
| `resource_id` | `CharField` | 是 |  |  | 资源ID |  |
| `mcp_tool_name` | `CharField` | 是 |  |  | MCP工具名 |  |
| `mcp_client_id` | `CharField` |  |  |  | MCP客户端ID |  |
| `mcp_role` | `CharField` |  |  |  | MCP角色 |  |
| `sdk_version` | `CharField` |  |  |  | SDK版本 |  |
| `request_method` | `CharField` |  |  | MCP | 请求方法 |  |
| `request_path` | `CharField` |  |  |  | 请求路径 |  |
| `request_params` | `JSONField` |  |  | dict | 已脱敏 |  |
| `response_payload` | `JSONField` | 是 |  |  | 结构化响应内容，已脱敏 |  |
| `response_text` | `TextField` |  |  |  | 完整或截断后的文本响应 |  |
| `response_status` | `IntegerField` |  |  | 200 | 响应状态码 |  |
| `response_message` | `TextField` |  |  |  | 响应消息 |  |
| `error_code` | `CharField` |  |  |  | 错误代码 |  |
| `exception_traceback` | `TextField` |  |  |  | 异常堆栈 |  |
| `timestamp` | `DateTimeField` |  |  |  | 时间戳 |  |
| `duration_ms` | `IntegerField` | 是 |  |  | 耗时(ms) |  |
| `checksum` | `CharField` |  |  |  | SHA-256 |  |

### ValidationSummaryModel

- 来源文件：`apps/audit/infrastructure/models.py`
- 数据表：`audit_validation_summary`
- 说明：验证摘要

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `validation_run_id` | `CharField` |  | 是 |  | 验证运行ID |  |
| `run_date` | `DateTimeField` |  |  |  | 运行日期 |  |
| `evaluation_period_start` | `DateField` |  |  |  | 评估起始日期 |  |
| `evaluation_period_end` | `DateField` |  |  |  | 评估结束日期 |  |
| `total_indicators` | `IntegerField` |  |  | 0 | 总指标数 |  |
| `approved_indicators` | `IntegerField` |  |  | 0 | 通过指标数 |  |
| `rejected_indicators` | `IntegerField` |  |  | 0 | 拒绝指标数 |  |
| `pending_indicators` | `IntegerField` |  |  | 0 | 待定指标数 |  |
| `avg_f1_score` | `FloatField` | 是 |  |  | 平均F1分数 |  |
| `avg_stability_score` | `FloatField` | 是 |  |  | 平均稳定性分数 |  |
| `overall_recommendation` | `TextField` |  |  |  | 总体建议 |  |
| `status` | `CharField` |  |  | pending | 状态 |  |
| `is_shadow_mode` | `BooleanField` |  |  | False | 是否为影子模式 |  |
| `error_message` | `TextField` |  |  |  | 错误信息 |  |

### SystemAuditEventModel

- 来源文件：`apps/audit/infrastructure/system_audit_models.py`
- 数据表：`audit_system_event`
- 说明：Canonical event ledger row; no update/delete path is public.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `schema_version` | `CharField` |  |  |  |  |  |
| `category` | `CharField` |  |  |  |  |  |
| `event_type` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `scope_tenant_id` | `CharField` | 是 |  |  |  |  |
| `scope_owner_id` | `CharField` | 是 |  |  |  |  |
| `write_policy` | `CharField` |  |  |  |  |  |
| `outcome` | `CharField` |  |  |  |  |  |
| `severity` | `CharField` |  |  |  |  |  |
| `reason_codes` | `JSONField` |  |  |  |  |  |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `observed_at` | `DateTimeField` | 是 |  |  |  |  |
| `actor_type` | `CharField` |  |  |  |  |  |
| `actor_id` | `CharField` |  |  |  |  |  |
| `actor_display` | `CharField` | 是 |  |  |  |  |
| `source_app` | `CharField` |  |  |  |  |  |
| `source_component` | `CharField` |  |  |  |  |  |
| `source_surface` | `CharField` |  |  |  |  |  |
| `correlations` | `JSONField` |  |  |  |  |  |
| `resource_type` | `CharField` | 是 |  |  |  |  |
| `resource_id` | `CharField` | 是 |  |  |  |  |
| `resource_version` | `CharField` | 是 |  |  |  |  |
| `dataset_key` | `CharField` | 是 |  |  |  |  |
| `provider_key` | `CharField` | 是 |  |  |  |  |
| `capability` | `CharField` | 是 |  |  |  |  |
| `publication_id` | `CharField` | 是 |  |  |  |  |
| `evidence_refs` | `JSONField` |  |  |  |  |  |
| `detail_schema` | `CharField` |  |  |  |  |  |
| `detail` | `JSONField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `stream_id` | `CharField` |  |  |  |  |  |
| `sequence_no` | `PositiveBigIntegerField` |  |  |  |  |  |
| `predecessor_hash` | `CharField` | 是 |  |  |  |  |
| `idempotency_key` | `CharField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  |  |  |  |  |
| `content_hash` | `CharField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### SystemAuditOutboxModel

- 来源文件：`apps/audit/infrastructure/system_audit_outbox_models.py`
- 数据表：`audit_system_outbox`
- 说明：One immutable event payload awaiting controlled dispatch.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `outbox_id` | `UUIDField` |  |  | uuid4 |  |  |
| `event_id` | `CharField` |  | 是 |  |  |  |
| `idempotency_key` | `CharField` |  | 是 |  |  |  |
| `payload` | `JSONField` |  |  |  |  |  |
| `payload_hash` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  | STATUS_PENDING |  |  |
| `attempt_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `available_at` | `DateTimeField` |  |  |  |  |  |
| `claimed_at` | `DateTimeField` | 是 |  |  |  |  |
| `claimed_by` | `CharField` | 是 |  |  |  |  |
| `claim_token` | `CharField` | 是 |  |  |  |  |
| `delivered_at` | `DateTimeField` | 是 |  |  |  |  |
| `last_error_code` | `CharField` | 是 |  |  |  |  |
| `last_error_at` | `DateTimeField` | 是 |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |


## backtest

### BacktestResultModel

- 来源文件：`apps/backtest/infrastructure/models.py`
- 数据表：`backtest_result`
- 说明：回测结果模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` | 是 |  |  | NULL表示系统/测试数据 | User |
| `name` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  | pending |  |  |
| `error_message` | `TextField` | 是 |  |  |  |  |
| `start_date` | `DateField` |  |  |  |  |  |
| `end_date` | `DateField` |  |  |  |  |  |
| `initial_capital` | `DecimalField` |  |  |  |  |  |
| `rebalance_frequency` | `CharField` |  |  |  |  |  |
| `use_pit_data` | `BooleanField` |  |  | False |  |  |
| `transaction_cost_bps` | `FloatField` |  |  | 10.0 |  |  |
| `data_manifest_id` | `CharField` | 是 |  |  |  |  |
| `pit_coverage` | `JSONField` |  |  | dict |  |  |
| `trust_status` | `CharField` |  |  | legacy_unverified |  |  |
| `config_hash` | `CharField` |  |  |  |  |  |
| `code_commit` | `CharField` |  |  |  |  |  |
| `engine_version` | `CharField` |  |  |  |  |  |
| `research_trial_id` | `CharField` | 是 |  |  |  |  |
| `decision_snapshot_id` | `CharField` | 是 |  |  |  |  |
| `final_capital` | `DecimalField` | 是 |  |  |  |  |
| `total_return` | `FloatField` | 是 |  |  |  |  |
| `annualized_return` | `FloatField` | 是 |  |  |  |  |
| `max_drawdown` | `FloatField` | 是 |  |  |  |  |
| `sharpe_ratio` | `FloatField` | 是 |  |  |  |  |
| `equity_curve` | `JSONField` |  |  | list |  |  |
| `regime_history` | `JSONField` |  |  | list |  |  |
| `trades` | `JSONField` |  |  | list |  |  |
| `warnings` | `JSONField` |  |  | list |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |
| `completed_at` | `DateTimeField` | 是 |  |  |  |  |
| `used_signals` | `ManyToManyField` |  |  |  | 记录回测使用了哪些投资信号 | signal.InvestmentSignalModel |
| `signal_configs` | `JSONField` |  |  | list | 记录每个信号的配置参数，如权重、准入条件等 |  |

### BacktestTradeModel

- 来源文件：`apps/backtest/infrastructure/models.py`
- 数据表：`backtest_trade`
- 说明：回测交易记录模型（可选，用于更详细的交易分析）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `backtest` | `ForeignKey` |  |  |  |  | BacktestResultModel |
| `trade_date` | `DateField` |  |  |  |  |  |
| `asset_class` | `CharField` |  |  |  |  |  |
| `action` | `CharField` |  |  |  |  |  |
| `shares` | `FloatField` |  |  |  |  |  |
| `price` | `DecimalField` |  |  |  |  |  |
| `notional` | `DecimalField` |  |  |  |  |  |
| `cost` | `DecimalField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |


## beta_gate

### GateConfigModel

- 来源文件：`apps/beta_gate/infrastructure/models.py`
- 数据表：`beta_gate_config`
- 说明：闸门配置 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `config_id` | `CharField` |  | 是 |  | 配置唯一标识符 |  |
| `risk_profile` | `CharField` |  |  | BALANCED | 风险画像 |  |
| `version` | `IntegerField` |  |  | 1 | 配置版本号 |  |
| `is_active` | `BooleanField` |  |  | True | 是否激活 |  |
| `regime_constraints` | `JSONField` |  |  | dict | Regime 约束配置 |  |
| `policy_constraints` | `JSONField` |  |  | dict | Policy 约束配置 |  |
| `portfolio_constraints` | `JSONField` |  |  | dict | 组合约束配置 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |
| `effective_date` | `DateField` |  |  | timezone.now | 生效日期 |  |
| `expires_at` | `DateField` | 是 |  |  | 过期日期（可选） |  |

### GateDecisionModel

- 来源文件：`apps/beta_gate/infrastructure/models.py`
- 数据表：`beta_gate_decision`
- 说明：闸门决策 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `decision_id` | `CharField` |  | 是 |  | 决策唯一标识符 |  |
| `asset_code` | `CharField` |  |  |  | 资产代码 |  |
| `asset_class` | `CharField` |  |  |  | 资产类别 |  |
| `status` | `CharField` |  |  |  | 决策状态 |  |
| `current_regime` | `CharField` |  |  |  | 当前 Regime |  |
| `policy_level` | `IntegerField` |  |  |  | Policy 档位 |  |
| `regime_confidence` | `FloatField` |  |  |  | Regime 置信度 |  |
| `evaluation_details` | `JSONField` |  |  | dict | 评估详情 |  |
| `evaluated_at` | `DateTimeField` |  |  |  | 评估时间 |  |

### VisibilityUniverseSnapshotModel

- 来源文件：`apps/beta_gate/infrastructure/models.py`
- 数据表：`beta_gate_universe_snapshot`
- 说明：可见性宇宙快照 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot_id` | `CharField` |  | 是 |  | 快照唯一标识符 |  |
| `regime_snapshot_id` | `CharField` |  |  |  | Regime 快照 ID |  |
| `policy_snapshot_id` | `CharField` |  |  |  | Policy 快照 ID |  |
| `current_regime` | `CharField` |  |  |  | 当前 Regime |  |
| `policy_level` | `IntegerField` |  |  |  | Policy 档位 |  |
| `regime_confidence` | `FloatField` |  |  |  | Regime 置信度 |  |
| `risk_profile` | `CharField` |  |  | GateConfigModel.BALANCED | 风险画像 |  |
| `visible_asset_categories` | `JSONField` |  |  | list | 可见资产类别列表 |  |
| `visible_strategies` | `JSONField` |  |  | list | 可见策略列表 |  |
| `hard_exclusions` | `JSONField` |  |  | list | 硬排除列表 |  |
| `watch_list` | `JSONField` |  |  | list | 观察列表 |  |
| `as_of` | `DateField` |  |  | timezone.now | 截止日期 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |


## broker_execution

### BrokerAccountIdentitySnapshotModel

- 来源文件：`apps/broker_execution/infrastructure/broker_account_identity_snapshot_models.py`
- 数据表：`broker_execution_account_identity_snapshot`
- 说明：One immutable actor-bound inactive Broker account identity snapshot.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `authority_scope` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `snapshot_id` | `CharField` |  |  |  |  |  |
| `snapshot_version` | `CharField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `broker_account_namespace` | `CharField` |  |  |  |  |  |
| `broker_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `owner_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `account_source_owner` | `CharField` |  |  |  |  |  |
| `account_source_artifact_type` | `CharField` |  |  |  |  |  |
| `account_source_id` | `CharField` |  |  |  |  |  |
| `account_source_version` | `CharField` |  |  |  |  |  |
| `account_source_content_hash` | `CharField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `account_source_owner_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `account_type` | `CharField` |  |  |  |  |  |
| `is_active` | `BooleanField` |  |  |  |  |  |
| `account_source_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `account_source_valid_until` | `DateTimeField` |  |  |  |  |  |
| `binding_revision` | `PositiveBigIntegerField` |  |  |  |  |  |
| `binding_owner_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `binding_content_hash` | `CharField` |  |  |  |  |  |
| `agent_id` | `CharField` |  |  |  |  |  |
| `agent_version` | `CharField` |  |  |  |  |  |
| `agent_owner_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `agent_content_hash` | `CharField` |  |  |  |  |  |
| `qmt_digest_algorithm` | `CharField` |  |  |  |  |  |
| `qmt_digest_key_id` | `CharField` |  |  |  |  |  |
| `qmt_digest` | `CharField` |  |  |  |  |  |
| `broker_account_category` | `CharField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ttl_valid_until` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `supersedes_snapshot_hash` | `CharField` | 是 | 是 |  |  |  |
| `root_claim_hash` | `CharField` | 是 | 是 |  |  |  |
| `actor_id` | `CharField` |  |  |  |  |  |
| `actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `actor_kind` | `CharField` |  |  |  |  |  |
| `actor_is_staff` | `BooleanField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### BrokerAccountAccessModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_account_access`
- 说明：Explicitly grant a non-owner user access to one live account.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `account_id` | `PositiveIntegerField` |  |  |  |  |  |
| `can_approve` | `BooleanField` |  |  | False |  |  |
| `can_trade` | `BooleanField` |  |  | False |  |  |
| `granted_by` | `ForeignKey` | 是 |  |  |  | settings.AUTH_USER_MODEL |
| `is_active` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### BrokerAccountBindingModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_account_binding`
- 说明：Bind one owned system account to one local broker Agent.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `account_id` | `PositiveIntegerField` |  |  |  |  |  |
| `agent` | `ForeignKey` |  |  |  |  | BrokerAgentModel |
| `broker_account_ref` | `CharField` |  |  |  |  |  |
| `broker_account_mask` | `CharField` |  |  |  |  |  |
| `account_type` | `CharField` |  |  | STOCK |  |  |
| `auto_execution_enabled` | `BooleanField` |  |  | False |  |  |
| `max_single_order_amount` | `DecimalField` |  |  | 0 |  |  |
| `daily_order_amount_limit` | `DecimalField` |  |  | 0 |  |  |
| `max_position_count` | `PositiveIntegerField` |  |  | 20 |  |  |
| `max_snapshot_age_seconds` | `PositiveIntegerField` |  |  | 120 |  |  |
| `price_deviation_limit_pct` | `DecimalField` |  |  | Decimal('0.03') |  |  |
| `allowed_trading_windows` | `JSONField` |  |  | default_trading_windows |  |  |
| `enforce_trading_session` | `BooleanField` |  |  | True |  |  |
| `allowed_symbols` | `JSONField` |  |  | list |  |  |
| `is_active` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### BrokerAccountSnapshotModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_account_snapshot`
- 说明：Persisted broker cash/asset snapshot used by reconciliation and readiness.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `agent` | `ForeignKey` |  |  |  |  | BrokerAgentModel |
| `account_id` | `PositiveIntegerField` |  |  |  |  |  |
| `captured_at` | `DateTimeField` |  |  |  |  |  |
| `cash_available` | `DecimalField` |  |  | 0 |  |  |
| `total_asset` | `DecimalField` |  |  | 0 |  |  |
| `payload` | `JSONField` |  |  | dict |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### BrokerAgentCredentialModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_agent_credential`
- 说明：Hashed, scoped credential for one local Agent; raw secrets are never stored.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `credential_id` | `UUIDField` |  | 是 | uuid.uuid4 |  |  |
| `agent` | `ForeignKey` |  |  |  |  | BrokerAgentModel |
| `secret_hash` | `CharField` |  |  |  |  |  |
| `scopes` | `JSONField` |  |  | list |  |  |
| `allowed_account_ids` | `JSONField` |  |  | list |  |  |
| `expires_at` | `DateTimeField` |  |  |  |  |  |
| `revoked_at` | `DateTimeField` | 是 |  |  |  |  |
| `created_by` | `ForeignKey` | 是 |  |  |  | settings.AUTH_USER_MODEL |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### BrokerAgentModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_agent`
- 说明：Persisted health projection for one local QMT Agent.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `agent_id` | `CharField` |  | 是 |  |  |  |
| `user` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `display_name` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  | STATUS_OFFLINE |  |  |
| `qmt_connected` | `BooleanField` |  |  | False |  |  |
| `agent_version` | `CharField` |  |  |  |  |  |
| `last_heartbeat_at` | `DateTimeField` | 是 |  |  |  |  |
| `health_snapshot` | `JSONField` |  |  | dict |  |  |
| `is_active` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### BrokerAgentNonceModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_agent_nonce`
- 说明：Short-lived replay guard for signed Agent requests.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `credential` | `ForeignKey` |  |  |  |  | BrokerAgentCredentialModel |
| `nonce_hash` | `CharField` |  |  |  |  |  |
| `request_id` | `CharField` |  |  |  |  |  |
| `seen_at` | `DateTimeField` |  |  |  |  |  |

### BrokerCommandModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_command`
- 说明：Server-to-Agent command such as cancel, pause, resume, or full sync.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `agent` | `ForeignKey` |  |  |  |  | BrokerAgentModel |
| `command_id` | `UUIDField` |  | 是 | uuid.uuid4 |  |  |
| `command_type` | `CharField` |  |  |  |  |  |
| `account_id` | `PositiveIntegerField` |  |  | 0 |  |  |
| `payload` | `JSONField` |  |  | dict |  |  |
| `status` | `CharField` |  |  | pending |  |  |
| `leased_at` | `DateTimeField` | 是 |  |  |  |  |
| `completed_at` | `DateTimeField` | 是 |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### BrokerExecutionAlertModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_alert`
- 说明：Deduplicated operational alert with automatic-stop evidence.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `account_id` | `PositiveIntegerField` |  |  |  |  |  |
| `fingerprint` | `CharField` |  | 是 |  |  |  |
| `code` | `CharField` |  |  |  |  |  |
| `severity` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  | open |  |  |
| `title` | `CharField` |  |  |  |  |  |
| `message` | `TextField` |  |  |  |  |  |
| `payload` | `JSONField` |  |  | dict |  |  |
| `occurrence_count` | `PositiveIntegerField` |  |  | 1 |  |  |
| `auto_stop_applied` | `BooleanField` |  |  | False |  |  |
| `first_seen_at` | `DateTimeField` |  |  |  |  |  |
| `last_seen_at` | `DateTimeField` |  |  |  |  |  |

### BrokerExecutionAuditModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_audit`
- 说明：Append-only audit event for broker-execution actions.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` | 是 |  |  |  | settings.AUTH_USER_MODEL |
| `actor` | `ForeignKey` | 是 |  |  |  | settings.AUTH_USER_MODEL |
| `actor_type` | `CharField` |  |  | user |  |  |
| `action` | `CharField` |  |  |  |  |  |
| `account_id` | `PositiveIntegerField` |  |  | 0 |  |  |
| `resource_type` | `CharField` |  |  |  |  |  |
| `resource_id` | `CharField` |  |  |  |  |  |
| `before` | `JSONField` |  |  | dict |  |  |
| `after` | `JSONField` |  |  | dict |  |  |
| `reason` | `TextField` |  |  |  |  |  |
| `request_id` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### BrokerExecutionDailyReportModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_daily_report`
- 说明：Daily execution, reconciliation, and safety summary per account.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `account_id` | `PositiveIntegerField` |  |  |  |  |  |
| `report_date` | `DateField` |  |  |  |  |  |
| `status` | `CharField` |  |  | ok |  |  |
| `metrics` | `JSONField` |  |  | dict |  |  |
| `summary` | `JSONField` |  |  | dict |  |  |
| `generated_at` | `DateTimeField` |  |  |  |  |  |

### BrokerExecutionIdempotencyModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_idempotency`
- 说明：Persist one governed write result for safe request replay.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `action` | `CharField` |  |  |  |  |  |
| `idempotency_key` | `CharField` |  |  |  |  |  |
| `request_digest` | `CharField` |  |  |  |  |  |
| `response_payload` | `JSONField` |  |  | dict |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### BrokerFillModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_fill`
- 说明：Normalized immutable broker fill fact.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `order` | `ForeignKey` |  |  |  |  | LiveOrderModel |
| `agent` | `ForeignKey` |  |  |  |  | BrokerAgentModel |
| `broker_account_ref` | `CharField` |  |  |  |  |  |
| `broker_trade_id` | `CharField` |  |  |  |  |  |
| `quantity` | `DecimalField` |  |  |  |  |  |
| `price` | `DecimalField` |  |  |  |  |  |
| `amount` | `DecimalField` |  |  |  |  |  |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `payload` | `JSONField` |  |  | dict |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### BrokerOrderEventModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_order_event`
- 说明：Append-only normalized broker event attached to an order.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `agent` | `ForeignKey` |  |  |  |  | BrokerAgentModel |
| `order` | `ForeignKey` |  |  |  |  | LiveOrderModel |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_type` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `payload` | `JSONField` |  |  | dict |  |  |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `received_at` | `DateTimeField` |  |  |  |  |  |

### BrokerPositionSnapshotModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_position_snapshot`
- 说明：Persisted broker position snapshot used by pre-submit checks.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `agent` | `ForeignKey` |  |  |  |  | BrokerAgentModel |
| `account_id` | `PositiveIntegerField` |  |  |  |  |  |
| `asset_code` | `CharField` |  |  |  |  |  |
| `quantity` | `DecimalField` |  |  | 0 |  |  |
| `available_quantity` | `DecimalField` |  |  | 0 |  |  |
| `captured_at` | `DateTimeField` |  |  |  |  |  |
| `payload` | `JSONField` |  |  | dict |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### LiveOrderModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_live_order`
- 说明：Canonical VPS-side live-order lifecycle record.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `account_id` | `PositiveIntegerField` |  |  |  |  |  |
| `agent` | `ForeignKey` | 是 |  |  |  | BrokerAgentModel |
| `client_order_id` | `UUIDField` |  | 是 | uuid.uuid4 |  |  |
| `asset_code` | `CharField` |  |  |  |  |  |
| `market` | `CharField` |  |  | CN |  |  |
| `side` | `CharField` |  |  |  |  |  |
| `order_type` | `CharField` |  |  | LIMIT |  |  |
| `quantity` | `DecimalField` |  |  |  |  |  |
| `limit_price` | `DecimalField` | 是 |  |  |  |  |
| `estimated_amount` | `DecimalField` |  |  | 0 |  |  |
| `status` | `CharField` |  |  | WAITING_APPROVAL |  |  |
| `source_recommendation_ids` | `JSONField` |  |  | list |  |  |
| `source_signal_ids` | `JSONField` |  |  | list |  |  |
| `risk_policy_version` | `CharField` |  |  |  |  |  |
| `risk_snapshot` | `JSONField` |  |  | dict |  |  |
| `approval_mode` | `CharField` |  |  | manual |  |  |
| `approval_digest` | `CharField` |  |  |  |  |  |
| `approved_by` | `ForeignKey` | 是 |  |  |  | settings.AUTH_USER_MODEL |
| `approved_at` | `DateTimeField` | 是 |  |  |  |  |
| `expires_at` | `DateTimeField` | 是 |  |  |  |  |
| `submitted_at` | `DateTimeField` | 是 |  |  |  |  |
| `broker_order_id` | `CharField` |  |  |  |  |  |
| `filled_quantity` | `DecimalField` |  |  | 0 |  |  |
| `average_fill_price` | `DecimalField` | 是 |  |  |  |  |
| `failure_code` | `CharField` |  |  |  |  |  |
| `failure_message` | `TextField` |  |  |  |  |  |
| `version` | `PositiveIntegerField` |  |  | 1 |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### OrderLeaseModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_order_lease`
- 说明：Exclusive short lease allowing one Agent to submit one READY order.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `order` | `OneToOneField` |  |  |  |  | LiveOrderModel |
| `agent` | `ForeignKey` |  |  |  |  | BrokerAgentModel |
| `lease_token_hash` | `CharField` |  |  |  |  |  |
| `leased_at` | `DateTimeField` |  |  |  |  |  |
| `expires_at` | `DateTimeField` |  |  |  |  |  |
| `released_at` | `DateTimeField` | 是 |  |  |  |  |

### ReconciliationDifferenceModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_reconciliation_difference`
- 说明：One immutable four-dimensional reconciliation difference.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `run` | `ForeignKey` |  |  |  |  | ReconciliationRunModel |
| `dimension` | `CharField` |  |  |  |  |  |
| `difference_key` | `CharField` |  |  |  |  |  |
| `severity` | `CharField` |  |  | P1 |  |  |
| `expected` | `JSONField` |  |  | dict |  |  |
| `actual` | `JSONField` |  |  | dict |  |  |
| `reason` | `TextField` |  |  |  |  |  |
| `status` | `CharField` |  |  | open |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### ReconciliationRunModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_reconciliation_run`
- 说明：One persisted reconciliation batch and its unresolved differences.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `account_id` | `PositiveIntegerField` |  |  |  |  |  |
| `run_key` | `CharField` | 是 | 是 |  |  |  |
| `status` | `CharField` |  |  | pending |  |  |
| `order_difference_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `fill_difference_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `cash_difference_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `position_difference_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `summary` | `JSONField` |  |  | dict |  |  |
| `started_at` | `DateTimeField` |  |  |  |  |  |
| `completed_at` | `DateTimeField` | 是 |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### TradingControlModel

- 来源文件：`apps/broker_execution/infrastructure/models.py`
- 数据表：`broker_execution_trading_control`
- 说明：Account-scoped kill switch; account ID zero represents the user global switch.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `account_id` | `PositiveIntegerField` |  |  | 0 |  |  |
| `kill_switch_active` | `BooleanField` |  |  | False |  |  |
| `reason` | `TextField` |  |  |  |  |  |
| `changed_by` | `ForeignKey` | 是 |  |  |  | settings.AUTH_USER_MODEL |
| `changed_at` | `DateTimeField` |  |  |  |  |  |

### BrokerOrderApprovalArtifactModel

- 来源文件：`apps/broker_execution/infrastructure/order_approval_artifact_models.py`
- 数据表：`broker_execution_order_approval_artifact`
- 说明：One immutable Broker-owned order approval artifact first winner.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `artifact_id` | `UUIDField` |  |  |  |  |  |
| `artifact_version` | `CharField` |  |  |  |  |  |
| `client_order_id` | `UUIDField` |  |  |  |  |  |
| `account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `order_version` | `PositiveIntegerField` |  |  |  |  |  |
| `approval_digest` | `CharField` |  |  |  |  |  |
| `approved_actor_id` | `CharField` |  |  |  |  |  |
| `approved_actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `approved_actor_role` | `CharField` |  |  |  |  |  |
| `approved_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### BrokerPlanOrderBindingModel

- 来源文件：`apps/broker_execution/infrastructure/plan_order_binding_models.py`
- 数据表：`broker_execution_plan_order_binding`
- 说明：One immutable inactive exact Plan-to-Order binding seal.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `blocker_codes` | `JSONField` |  |  |  |  |  |
| `binding_id` | `CharField` |  |  |  |  |  |
| `binding_version` | `CharField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `portfolio_plan_owner` | `CharField` |  |  |  |  |  |
| `portfolio_plan_artifact_type` | `CharField` |  |  |  |  |  |
| `portfolio_plan_id` | `CharField` |  |  |  |  |  |
| `portfolio_plan_version` | `PositiveBigIntegerField` |  |  |  |  |  |
| `portfolio_plan_content_hash` | `CharField` |  |  |  |  |  |
| `portfolio_plan_valid_until` | `DateTimeField` |  |  |  |  |  |
| `portfolio_account_id` | `CharField` |  |  |  |  |  |
| `portfolio_receipt_owner` | `CharField` |  |  |  |  |  |
| `portfolio_receipt_capability` | `CharField` |  |  |  |  |  |
| `portfolio_receipt_id` | `CharField` |  |  |  |  |  |
| `portfolio_receipt_version` | `CharField` |  |  |  |  |  |
| `portfolio_receipt_content_hash` | `CharField` |  |  |  |  |  |
| `portfolio_receipt_valid_until` | `DateTimeField` |  |  |  |  |  |
| `portfolio_subject_id` | `CharField` |  |  |  |  |  |
| `portfolio_subject_version` | `CharField` |  |  |  |  |  |
| `portfolio_subject_content_hash` | `CharField` |  |  |  |  |  |
| `plan_order_ordinal` | `PositiveBigIntegerField` |  |  |  |  |  |
| `plan_order_payload_json` | `TextField` |  |  |  |  |  |
| `plan_order_content_hash` | `CharField` |  |  |  |  |  |
| `broker_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `order_artifact_owner` | `CharField` |  |  |  |  |  |
| `order_artifact_type` | `CharField` |  |  |  |  |  |
| `order_artifact_id` | `UUIDField` |  |  |  |  |  |
| `order_artifact_version` | `CharField` |  |  |  |  |  |
| `order_artifact_identity_hash` | `CharField` |  |  |  |  |  |
| `order_artifact_content_hash` | `CharField` |  |  |  |  |  |
| `order_artifact_valid_until` | `DateTimeField` |  |  |  |  |  |
| `order_approval_digest` | `CharField` |  |  |  |  |  |
| `order_version` | `PositiveBigIntegerField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `supersedes_binding_hash` | `CharField` | 是 | 是 |  |  |  |
| `root_claim_hash` | `CharField` | 是 | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `canonical_row_byte_hash` | `CharField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### BrokerPortfolioAccountBindingModel

- 来源文件：`apps/broker_execution/infrastructure/portfolio_broker_account_binding_models.py`
- 数据表：`broker_execution_portfolio_account_binding`
- 说明：One immutable inactive cross-namespace binding assertion.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `binding_id` | `CharField` |  |  |  |  |  |
| `binding_version` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `blocker_codes` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `broker_account_namespace` | `CharField` |  |  |  |  |  |
| `broker_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `portfolio_account_namespace` | `CharField` |  |  |  |  |  |
| `portfolio_account_id` | `CharField` |  |  |  |  |  |
| `owner_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `account_type` | `CharField` |  |  |  |  |  |
| `source_accounts_active` | `BooleanField` |  |  |  |  |  |
| `broker_source_owner` | `CharField` |  |  |  |  |  |
| `broker_source_artifact_type` | `CharField` |  |  |  |  |  |
| `broker_source_id` | `CharField` |  |  |  |  |  |
| `broker_source_version` | `CharField` |  |  |  |  |  |
| `broker_source_content_hash` | `CharField` |  |  |  |  |  |
| `portfolio_source_owner` | `CharField` |  |  |  |  |  |
| `portfolio_source_artifact_type` | `CharField` |  |  |  |  |  |
| `portfolio_source_id` | `CharField` |  |  |  |  |  |
| `portfolio_source_version` | `CharField` |  |  |  |  |  |
| `portfolio_source_content_hash` | `CharField` |  |  |  |  |  |
| `actor_id` | `CharField` |  |  |  |  |  |
| `actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `actor_role` | `CharField` |  |  |  |  |  |
| `actor_kind` | `CharField` |  |  |  |  |  |
| `actor_is_staff` | `BooleanField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `supersedes_binding_hash` | `CharField` | 是 | 是 |  |  |  |
| `root_claim_hash` | `CharField` | 是 | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### BrokerPreRiskExecutionScopeModel

- 来源文件：`apps/broker_execution/infrastructure/pre_risk_execution_scope_models.py`
- 数据表：`broker_execution_pre_risk_scope`
- 说明：One immutable inactive pre-Risk scope in a single logical order chain.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_version` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `broker_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `portfolio_account_id` | `CharField` |  |  |  |  |  |
| `plan_id` | `CharField` |  |  |  |  |  |
| `plan_version` | `PositiveIntegerField` |  |  |  |  |  |
| `plan_content_hash` | `CharField` |  |  |  |  |  |
| `portfolio_receipt_id` | `CharField` |  |  |  |  |  |
| `portfolio_receipt_version` | `CharField` |  |  |  |  |  |
| `portfolio_receipt_content_hash` | `CharField` |  |  |  |  |  |
| `order_artifact_id` | `UUIDField` |  |  |  |  |  |
| `order_artifact_version` | `CharField` |  |  |  |  |  |
| `order_artifact_content_hash` | `CharField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `supersedes_scope_hash` | `CharField` | 是 | 是 |  |  |  |
| `root_claim_hash` | `CharField` | 是 | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R8BrokerMonitoringAppendOnlyModel

- 来源文件：`apps/broker_execution/infrastructure/r8_monitoring_reconciliation_models.py`
- 抽象模型：是
- 说明：Reject every unclaimed insert and all mutation/deletion paths.

### R8BrokerMonitoringPeriodReceiptModel

- 来源文件：`apps/broker_execution/infrastructure/r8_monitoring_reconciliation_models.py`
- 数据表：`broker_execution_r8_monitoring_period_receipt`
- 说明：One immutable complete Broker reconciliation period receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `definition_id` | `CharField` |  |  |  |  |  |
| `definition_version` | `CharField` |  |  |  |  |  |
| `definition_hash` | `CharField` |  |  |  |  |  |
| `definition_payload` | `JSONField` |  |  |  |  |  |
| `source_receipt_id` | `CharField` |  |  |  |  |  |
| `source_receipt_version` | `CharField` |  |  |  |  |  |
| `source_receipt_hash` | `CharField` |  |  |  |  |  |
| `source_receipt_payload` | `JSONField` |  |  |  |  |  |
| `result_id` | `CharField` |  |  |  |  |  |
| `result_hash` | `CharField` |  |  |  |  |  |
| `portfolio_receipt_id` | `CharField` |  |  |  |  |  |
| `portfolio_receipt_version` | `CharField` |  |  |  |  |  |
| `portfolio_receipt_hash` | `CharField` |  |  |  |  |  |
| `calendar_id` | `CharField` |  |  |  |  |  |
| `calendar_version` | `CharField` |  |  |  |  |  |
| `calendar_hash` | `CharField` |  |  |  |  |  |
| `period_id` | `CharField` |  |  |  |  |  |
| `period_start_at` | `DateTimeField` |  |  |  |  |  |
| `period_end_at` | `DateTimeField` |  |  |  |  |  |
| `planning_reference_id` | `CharField` |  |  |  |  |  |
| `planning_reference_version` | `CharField` |  |  |  |  |  |
| `planning_reference_hash` | `CharField` |  |  |  |  |  |
| `reconciliation_manifest_id` | `CharField` |  |  |  |  |  |
| `reconciliation_manifest_version` | `CharField` |  |  |  |  |  |
| `reconciliation_manifest_hash` | `CharField` |  |  |  |  |  |
| `source_observed_at` | `DateTimeField` |  |  |  |  |  |
| `source_available_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `total_cost_amount` | `DecimalField` |  |  |  |  |  |
| `total_cost_notional` | `DecimalField` |  |  |  |  |  |
| `adverse_slippage_amount` | `DecimalField` |  |  |  |  |  |
| `adverse_slippage_notional` | `DecimalField` |  |  |  |  |  |
| `reconciliation_break_count` | `PositiveBigIntegerField` |  |  |  |  |  |
| `reconciliation_comparison_count` | `PositiveBigIntegerField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |


## config_center

### BackupDeliveryStateModel

- 来源文件：`apps/config_center/infrastructure/backup_delivery_models.py`
- 数据表：`config_center_backup_delivery_state`
- 说明：Singleton state for one active backup-download link and send marker.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `state_id` | `PositiveSmallIntegerField` |  |  | 1 |  |  |
| `last_sent_at` | `DateTimeField` | 是 |  |  |  |  |
| `download_token_digest` | `CharField` |  |  |  |  |  |
| `download_token_expires_at` | `DateTimeField` | 是 |  |  |  |  |
| `download_token_consumed_at` | `DateTimeField` | 是 |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### StorageCapacityObservationModel

- 来源文件：`apps/config_center/infrastructure/capacity_models.py`
- 数据表：`config_center_storage_capacity_observation`
- 说明：Filesystem/database capacity snapshot used by readiness and planning.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `observation_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `environment` | `CharField` |  |  |  |  |  |
| `observed_at` | `DateTimeField` |  |  |  |  |  |
| `filesystem_total_bytes` | `PositiveBigIntegerField` |  |  |  |  |  |
| `filesystem_used_bytes` | `PositiveBigIntegerField` |  |  |  |  |  |
| `filesystem_free_bytes` | `PositiveBigIntegerField` |  |  |  |  |  |
| `database_size_bytes` | `PositiveBigIntegerField` |  |  |  |  |  |
| `relation_sizes` | `JSONField` |  |  | dict |  |  |
| `policy_key` | `CharField` |  |  |  |  |  |
| `configured_capacity_bytes` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `effective_capacity_bytes` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `usage_ratio` | `FloatField` | 是 |  |  |  |  |
| `pressure_state` | `CharField` |  |  |  |  |  |
| `source` | `CharField` |  |  |  |  |  |
| `metadata` | `JSONField` |  |  | dict |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### DecisionRuntimeStateModel

- 来源文件：`apps/config_center/infrastructure/decision_runtime_models.py`
- 数据表：`config_center_decision_runtime_state`
- 说明：Singleton controlled state kept separate from ordinary runtime values.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `state_id` | `PositiveSmallIntegerField` |  |  | 1 |  |  |
| `status` | `CharField` |  |  | DecisionRuntimeStatus.BLOCKED.value |  |  |
| `reason` | `TextField` |  |  |  |  |  |
| `changed_at` | `DateTimeField` | 是 |  |  |  |  |
| `changed_by` | `CharField` |  |  |  |  |  |
| `release_ref` | `CharField` |  |  |  |  |  |
| `expected_resume_at` | `DateTimeField` | 是 |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### EgressEndpointModel

- 来源文件：`apps/config_center/infrastructure/egress_models.py`
- 数据表：`config_center_egress_endpoint`
- 说明：One proxy endpoint whose credentials are stored by Config Center.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | `CharField` |  |  |  |  |  |
| `region` | `CharField` |  |  |  |  |  |
| `protocol` | `CharField` |  |  | http |  |  |
| `host` | `CharField` |  |  |  |  |  |
| `port` | `PositiveIntegerField` |  |  |  |  |  |
| `username_secret_ref` | `CharField` |  |  |  |  |  |
| `password_secret_ref` | `CharField` |  |  |  |  |  |
| `enabled` | `BooleanField` |  |  | False |  |  |
| `concurrency_limit` | `PositiveIntegerField` |  |  | 4 |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### AlphaUniverseConfigModel

- 来源文件：`apps/config_center/infrastructure/models.py`
- 数据表：`config_center_alpha_universe_config`
- 说明：Configurable Alpha/Qlib stock universe.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `universe_id` | `CharField` |  | 是 |  | Universe ID |  |
| `name` | `CharField` |  |  |  | 名称 |  |
| `source_type` | `CharField` |  |  | SOURCE_MANUAL | 来源类型 |  |
| `stock_codes` | `JSONField` |  |  | list | 股票代码清单 |  |
| `filters` | `JSONField` |  |  | dict | Data Center 过滤条件 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `description` | `TextField` |  |  |  | 说明 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### QlibTrainingProfileModel

- 来源文件：`apps/config_center/infrastructure/models.py`
- 数据表：`config_center_qlib_training_profile`
- 说明：Reusable Qlib training template.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `profile_key` | `CharField` |  | 是 |  | 模板键 |  |
| `name` | `CharField` |  |  |  | 模板名称 |  |
| `model_name` | `CharField` |  |  |  | 模型名称 |  |
| `model_type` | `CharField` |  |  |  | 模型类型 |  |
| `universe` | `CharField` |  |  |  | 股票池 |  |
| `start_date` | `DateField` | 是 |  |  | 训练开始日期 |  |
| `end_date` | `DateField` | 是 |  |  | 训练结束日期 |  |
| `feature_set_id` | `CharField` |  |  |  | 特征集标识 |  |
| `label_id` | `CharField` |  |  |  | 标签标识 |  |
| `learning_rate` | `FloatField` | 是 |  |  | 学习率 |  |
| `epochs` | `PositiveIntegerField` | 是 |  |  | 训练轮数 |  |
| `model_params` | `JSONField` |  |  | dict | 模型参数 |  |
| `extra_train_config` | `JSONField` |  |  | dict | 附加训练配置 |  |
| `activate_after_train` | `BooleanField` |  |  | False | 训练完成后自动激活 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `notes` | `TextField` |  |  |  | 备注 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### QlibTrainingRunLockModel

- 来源文件：`apps/config_center/infrastructure/models.py`
- 数据表：`config_center_qlib_training_run_lock`
- 说明：Singleton lock row for cross-worker Qlib training run admission.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `lock_key` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### QlibTrainingRunModel

- 来源文件：`apps/config_center/infrastructure/models.py`
- 数据表：`config_center_qlib_training_run`
- 说明：Tracked Qlib training execution.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `run_id` | `UUIDField` |  | 是 | uuid.uuid4 |  |  |
| `profile` | `ForeignKey` | 是 |  |  | 训练模板 | config_center.QlibTrainingProfileModel |
| `status` | `CharField` |  |  | STATUS_PENDING | 状态 |  |
| `requested_by` | `ForeignKey` | 是 |  |  | 发起人 | settings.AUTH_USER_MODEL |
| `requested_at` | `DateTimeField` |  |  | timezone.now | 发起时间 |  |
| `started_at` | `DateTimeField` | 是 |  |  | 开始时间 |  |
| `finished_at` | `DateTimeField` | 是 |  |  | 结束时间 |  |
| `celery_task_id` | `CharField` |  |  |  | Celery Task ID |  |
| `model_name` | `CharField` |  |  |  | 模型名称 |  |
| `model_type` | `CharField` |  |  |  | 模型类型 |  |
| `resolved_train_config` | `JSONField` |  |  | dict | 最终训练配置 |  |
| `result_model_name` | `CharField` |  |  |  | 结果模型名 |  |
| `result_artifact_hash` | `CharField` |  |  |  | 结果 Artifact Hash |  |
| `result_metrics` | `JSONField` |  |  | dict | 结果指标 |  |
| `registry_result` | `JSONField` |  |  | dict | 注册结果 |  |
| `error_message` | `TextField` |  |  |  | 错误信息 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### RuntimeConfigDefinitionModel

- 来源文件：`apps/config_center/infrastructure/models.py`
- 数据表：`config_center_runtime_config_definition`
- 说明：Registry definition for one typed runtime configuration key.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `key` | `CharField` |  | 是 |  |  |  |
| `namespace` | `CharField` |  |  |  |  |  |
| `owner_app` | `CharField` |  |  |  |  |  |
| `value_type` | `CharField` |  |  |  |  |  |
| `unit` | `CharField` |  |  |  |  |  |
| `constraints` | `JSONField` |  |  | dict |  |  |
| `criticality` | `CharField` |  |  | RuntimeConfigCriticality.NORMAL.value |  |  |
| `secret` | `BooleanField` |  |  | False |  |  |
| `reload_mode` | `CharField` |  |  | RuntimeConfigReloadMode.NEXT_TASK.value |  |  |
| `description` | `TextField` |  |  |  |  |  |
| `user_impact` | `TextField` |  |  |  |  |  |
| `is_deprecated` | `BooleanField` |  |  | False |  |  |
| `replacement_key` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### RuntimeConfigProfileModel

- 来源文件：`apps/config_center/infrastructure/models.py`
- 数据表：`config_center_runtime_config_profile`
- 说明：Versioned desired-state profile.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `profile_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `profile_key` | `CharField` |  |  |  |  |  |
| `environment` | `CharField` |  |  |  |  |  |
| `version` | `PositiveIntegerField` |  |  |  |  |  |
| `status` | `CharField` |  |  | RuntimeProfileStatus.DRAFT.value |  |  |
| `based_on_profile` | `CharField` |  |  |  |  |  |
| `content_hash` | `CharField` |  |  |  |  |  |
| `created_by` | `CharField` |  |  | system |  |  |
| `activated_by` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  | timezone.now |  |  |
| `activated_at` | `DateTimeField` | 是 |  |  |  |  |
| `change_reason` | `TextField` |  |  |  |  |  |
| `release_ref` | `CharField` |  |  |  |  |  |

### RuntimeConfigRevisionModel

- 来源文件：`apps/config_center/infrastructure/models.py`
- 数据表：`config_center_runtime_config_revision`
- 说明：Immutable profile-change audit entry.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `revision_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `profile_id` | `UUIDField` |  |  |  |  |  |
| `before_hash` | `CharField` |  |  |  |  |  |
| `after_hash` | `CharField` |  |  |  |  |  |
| `changed_keys` | `JSONField` |  |  | list |  |  |
| `before_projection` | `JSONField` |  |  | dict |  |  |
| `after_projection` | `JSONField` |  |  | dict |  |  |
| `actor` | `CharField` |  |  |  |  |  |
| `reason` | `TextField` |  |  |  |  |  |
| `changed_at` | `DateTimeField` |  |  | timezone.now |  |  |
| `release_ref` | `CharField` |  |  |  |  |  |
| `validation_evidence` | `JSONField` |  |  | dict |  |  |

### RuntimeConfigSnapshotModel

- 来源文件：`apps/config_center/infrastructure/models.py`
- 数据表：`config_center_runtime_config_snapshot`
- 说明：Resolved, immutable snapshot referenced by long-running work.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `profile_id` | `UUIDField` |  |  |  |  |  |
| `profile_key` | `CharField` |  |  |  |  |  |
| `profile_version` | `PositiveIntegerField` |  |  |  |  |  |
| `snapshot_hash` | `CharField` |  |  |  |  |  |
| `resolved_values` | `JSONField` |  |  | dict |  |  |
| `generated_at` | `DateTimeField` |  |  | timezone.now |  |  |
| `effective_from` | `DateTimeField` | 是 |  |  |  |  |
| `validation_report` | `JSONField` |  |  | dict |  |  |
| `consumer_acknowledgement` | `JSONField` |  |  | dict |  |  |

### RuntimeConfigValueModel

- 来源文件：`apps/config_center/infrastructure/models.py`
- 数据表：`config_center_runtime_config_value`
- 说明：Typed value belonging to one runtime configuration profile.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `value_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `profile_id` | `UUIDField` |  |  |  |  |  |
| `definition_key` | `CharField` |  |  |  |  |  |
| `value_json` | `JSONField` | 是 |  |  |  |  |
| `secret_ref` | `CharField` |  |  |  |  |  |
| `source` | `CharField` |  |  | admin |  |  |
| `validation_status` | `CharField` |  |  | valid |  |  |
| `validation_error` | `TextField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### SystemSettingsModel

- 来源文件：`apps/config_center/infrastructure/models.py`
- 数据表：`system_settings`
- 说明：Global singleton system settings.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `require_user_approval` | `BooleanField` |  |  | True | 关闭后新用户注册将自动批准 |  |
| `auto_approve_first_admin` | `BooleanField` |  |  | True | 系统无管理员时，首个注册的用户自动成为管理员并获得批准 |  |
| `default_mcp_enabled` | `BooleanField` |  |  | True | 新注册或新批准用户默认是否允许 MCP/SDK 访问，由管理员决定 |  |
| `market_color_convention` | `CharField` |  |  | cn_a_share | 统一控制涨跌、资金流入流出的语义颜色映射。 |  |
| `allow_token_plaintext_view` | `BooleanField` |  |  | True | 关闭后，生成后不再显示完整 Token，历史 Token 也不可明文查看 |  |
| `decision_runtime_status` | `CharField` |  |  | active | 非正常状态下所有决策入口必须阻断结论发布。 |  |
| `decision_runtime_reason` | `TextField` |  |  |  | 决策阻断原因 |  |
| `decision_runtime_changed_at` | `DateTimeField` | 是 |  |  | 决策状态变更时间 |  |
| `decision_runtime_changed_by` | `CharField` |  |  |  | 决策状态变更人 |  |
| `decision_runtime_release_ref` | `CharField` |  |  |  | 关联发布版本 |  |
| `decision_runtime_expected_resume_at` | `DateTimeField` | 是 |  |  | 预计恢复时间 |  |
| `user_agreement_content` | `TextField` |  |  |  | 用户注册时需要同意的协议内容，支持HTML |  |
| `risk_warning_content` | `TextField` |  |  |  | 用户注册时需要确认的风险提示内容，支持HTML |  |
| `notes` | `TextField` |  |  |  | 备注 |  |
| `benchmark_code_map` | `JSONField` |  |  | dict | 系统运行时使用的基准/默认指数代码映射 |  |
| `asset_proxy_code_map` | `JSONField` |  |  | dict | 资产类别到实际交易/价格代理代码的映射 |  |
| `backup_email` | `EmailField` |  |  |  | 启用后按周期发送数据库全量备份下载链接到该邮箱 |  |
| `backup_app_base_url` | `URLField` |  |  |  | 用于生成邮件中的绝对下载链接，如 https://example.com |  |
| `backup_mail_from_email` | `EmailField` |  |  |  | 留空则回退到系统默认发件人 |  |
| `backup_smtp_host` | `CharField` |  |  |  | SMTP 主机 |  |
| `backup_smtp_port` | `PositiveIntegerField` |  |  | 587 | SMTP 端口 |  |
| `backup_smtp_username` | `CharField` |  |  |  | SMTP 用户名 |  |
| `backup_smtp_use_tls` | `BooleanField` |  |  | True | SMTP 使用 TLS |  |
| `backup_smtp_use_ssl` | `BooleanField` |  |  | False | SMTP 使用 SSL |  |
| `backup_enabled` | `BooleanField` |  |  | False | 开启后系统会按设定周期发送备份下载链接 |  |
| `backup_interval_days` | `PositiveIntegerField` |  |  | 7 | 每隔多少天发送一次数据库备份下载链接 |  |
| `backup_link_ttl_days` | `PositiveIntegerField` |  |  | 3 | 邮件中的备份下载链接有效天数 |  |
| `backup_password_hint` | `CharField` |  |  |  | 可选，用于管理员识别当前使用的备份密码 |  |
| `backup_last_sent_at` | `DateTimeField` | 是 |  |  | 上次备份邮件发送时间 |  |
| `backup_download_token_digest` | `CharField` |  |  |  | 只存储不可逆指纹，用于撤销旧链接和单次消费校验 |  |
| `backup_download_token_expires_at` | `DateTimeField` | 是 |  |  | 当前备份下载令牌到期时间 |  |
| `backup_download_consumed_at` | `DateTimeField` | 是 |  |  | 当前备份下载令牌消费时间 |  |
| `qlib_enabled` | `BooleanField` |  |  | False | 开启后系统将使用 Qlib 进行量化分析 |  |
| `qlib_provider_uri` | `CharField` |  |  |  | Qlib 数据存储路径，如 D:/qlib_data/cn_data 或 /var/lib/qlib/cn_data |  |
| `qlib_region` | `CharField` |  |  | CN | 市场区域，如 CN（中国）、US（美国） |  |
| `qlib_model_path` | `CharField` |  |  |  | Qlib 模型存储路径，留空使用默认路径 |  |
| `qlib_default_universe` | `CharField` |  |  | csi300 | Qlib 默认股票池 |  |
| `qlib_default_feature_set_id` | `CharField` |  |  | v1 | Qlib 默认特征集标识 |  |
| `qlib_default_label_id` | `CharField` |  |  | return_5d | Qlib 默认标签标识 |  |
| `qlib_train_queue_name` | `CharField` |  |  | qlib_train | Qlib 训练队列名 |  |
| `qlib_infer_queue_name` | `CharField` |  |  | qlib_infer | Qlib 推理队列名 |  |
| `qlib_allow_auto_activate` | `BooleanField` |  |  | False | 训练触发未显式指定时，使用该全局默认值控制是否自动切换 active model。 |  |
| `alpha_fixed_provider` | `CharField` |  |  |  | 强制使用指定的 Provider（禁用自动降级），留空则启用自动降级 |  |
| `alpha_pool_mode` | `CharField` |  |  | ALPHA_POOL_MODE_STRICT_VALUATION | 控制首页 Alpha 和实时推理默认使用哪个候选股票集合 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### ConfigCenterSecretModel

- 来源文件：`apps/config_center/infrastructure/secret_models.py`
- 数据表：`config_center_secret`
- 说明：One encrypted value addressed by a stable Config Center reference.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `secret_ref` | `CharField` |  |  |  |  |  |
| `encrypted_value` | `TextField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### StorageBudgetPolicyModel

- 来源文件：`apps/config_center/infrastructure/storage_budget_models.py`
- 数据表：`config_center_storage_budget_policy`
- 说明：Runtime storage policy; no code-level capacity fallback is implied.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `policy_key` | `CharField` |  |  |  |  |  |
| `version` | `PositiveIntegerField` |  |  |  |  |  |
| `configured_capacity_bytes` | `PositiveBigIntegerField` |  |  |  |  |  |
| `raw_budget_ratio` | `FloatField` |  |  |  |  |  |
| `quarantine_budget_ratio` | `FloatField` |  |  |  |  |  |
| `database_budget_ratio` | `FloatField` |  |  |  |  |  |
| `logs_budget_ratio` | `FloatField` |  |  |  |  |  |
| `emergency_reserve_ratio` | `FloatField` |  |  |  |  |  |
| `warning_ratio` | `FloatField` |  |  |  |  |  |
| `critical_ratio` | `FloatField` |  |  |  |  |  |
| `active` | `BooleanField` |  |  | False |  |  |
| `created_by` | `CharField` |  |  | system |  |  |
| `activated_at` | `DateTimeField` | 是 |  |  |  |  |
| `change_reason` | `TextField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |


## dashboard

### AlphaRecommendationRunModel

- 来源文件：`apps/dashboard/infrastructure/models.py`
- 数据表：`dashboard_alpha_recommendation_run`
- 说明：首页 Alpha 候选评估运行快照。

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  |  | User |
| `portfolio_id` | `IntegerField` | 是 |  |  |  |  |
| `portfolio_name` | `CharField` |  |  |  |  |  |
| `trade_date` | `DateField` |  |  |  |  |  |
| `scope_hash` | `CharField` |  |  |  |  |  |
| `scope_label` | `CharField` |  |  |  |  |  |
| `scope_metadata` | `JSONField` |  |  | dict |  |  |
| `model_hash` | `CharField` |  |  |  |  |  |
| `source` | `CharField` |  |  |  |  |  |
| `provider_source` | `CharField` |  |  |  |  |  |
| `requested_trade_date` | `DateField` | 是 |  |  |  |  |
| `effective_asof_date` | `DateField` | 是 |  |  |  |  |
| `uses_cached_data` | `BooleanField` |  |  | False |  |  |
| `cache_reason` | `TextField` |  |  |  |  |  |
| `fallback_reason` | `TextField` |  |  |  |  |  |
| `meta` | `JSONField` |  |  | dict |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### AlphaRecommendationSnapshotModel

- 来源文件：`apps/dashboard/infrastructure/models.py`
- 数据表：`dashboard_alpha_recommendation_snapshot`
- 说明：单次运行中的逐票推荐快照。

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `run` | `ForeignKey` |  |  |  |  | AlphaRecommendationRunModel |
| `stock_code` | `CharField` |  |  |  |  |  |
| `stock_name` | `CharField` |  |  |  |  |  |
| `stage` | `CharField` |  |  |  |  |  |
| `gate_status` | `CharField` |  |  |  |  |  |
| `rank` | `IntegerField` |  |  | 0 |  |  |
| `alpha_score` | `FloatField` |  |  | 0.0 |  |  |
| `confidence` | `FloatField` |  |  | 0.0 |  |  |
| `source` | `CharField` |  |  |  |  |  |
| `buy_reasons` | `JSONField` |  |  | list |  |  |
| `no_buy_reasons` | `JSONField` |  |  | list |  |  |
| `invalidation_rule` | `JSONField` |  |  | dict |  |  |
| `risk_snapshot` | `JSONField` |  |  | dict |  |  |
| `suggested_position_pct` | `FloatField` |  |  | 0.0 |  |  |
| `suggested_notional` | `FloatField` |  |  | 0.0 |  |  |
| `suggested_quantity` | `FloatField` |  |  | 0.0 |  |  |
| `source_candidate_id` | `IntegerField` | 是 |  |  |  |  |
| `source_recommendation_id` | `IntegerField` | 是 |  |  |  |  |
| `extra_payload` | `JSONField` |  |  | dict |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### AutoAdvisorNotificationModel

- 来源文件：`apps/dashboard/infrastructure/models.py`
- 数据表：`dashboard_auto_advisor_notification`
- 说明：Stored notification/output item for auto-advisor reports.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  |  | User |
| `report` | `ForeignKey` | 是 |  |  |  | AutoAdvisorWeeklyReportModel |
| `account_id` | `IntegerField` |  |  |  |  |  |
| `channel` | `CharField` |  |  | CHANNEL_DASHBOARD |  |  |
| `title` | `CharField` |  |  |  |  |  |
| `message` | `TextField` |  |  |  |  |  |
| `payload` | `JSONField` |  |  | dict |  |  |
| `delivery_status` | `CharField` |  |  | STATUS_PENDING |  |  |
| `delivered_at` | `DateTimeField` | 是 |  |  |  |  |
| `read_at` | `DateTimeField` | 是 |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### AutoAdvisorWeeklyReportModel

- 来源文件：`apps/dashboard/infrastructure/models.py`
- 数据表：`dashboard_auto_advisor_weekly_report`
- 说明：Persisted weekly auto-advisor report and derived investment diary.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  |  | User |
| `account_id` | `IntegerField` |  |  |  |  |  |
| `account_name` | `CharField` |  |  |  |  |  |
| `report_date` | `DateField` |  |  |  |  |  |
| `week_start` | `DateField` |  |  |  |  |  |
| `week_end` | `DateField` |  |  |  |  |  |
| `status` | `CharField` |  |  | STATUS_READY |  |  |
| `payload` | `JSONField` |  |  | dict |  |  |
| `investment_diary` | `JSONField` |  |  | dict |  |  |
| `audit_log_id` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### DashboardAlertModel

- 来源文件：`apps/dashboard/infrastructure/models.py`
- 数据表：`dashboard_alert`
- 说明：仪表盘告警模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `alert_id` | `CharField` |  | 是 |  | 告警唯一标识符 |  |
| `name` | `CharField` |  |  |  | 告警名称 |  |
| `description` | `TextField` |  |  |  | 描述 |  |
| `metric` | `CharField` |  |  |  | 监控指标 |  |
| `condition` | `CharField` |  |  |  | 告警条件 |  |
| `severity` | `CharField` |  |  | AlertSeverity.WARNING.value | 告警级别 |  |
| `threshold` | `FloatField` | 是 |  |  | 阈值 |  |
| `notification_channels` | `JSONField` |  |  | list | 通知渠道 |  |
| `is_enabled` | `BooleanField` |  |  | True | 是否启用 |  |
| `cooldown` | `IntegerField` |  |  | 300 | 冷却时间（秒） |  |
| `last_triggered_at` | `DateTimeField` | 是 |  |  | 最后触发时间 |  |
| `trigger_count` | `IntegerField` |  |  | 0 | 触发次数 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### DashboardCardModel

- 来源文件：`apps/dashboard/infrastructure/models.py`
- 数据表：`dashboard_card`
- 说明：仪表盘卡片模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `card_id` | `CharField` |  | 是 |  | 卡片唯一标识符 |  |
| `card_type` | `CharField` |  |  |  | 卡片类型 |  |
| `title` | `CharField` |  |  |  | 卡片标题 |  |
| `description` | `TextField` |  |  |  | 描述 |  |
| `widget_config` | `JSONField` |  |  | dict | 组件配置 |  |
| `data_source` | `CharField` |  |  |  | 数据源 |  |
| `visibility_conditions` | `JSONField` |  |  | dict | 可见性条件 |  |
| `position` | `JSONField` |  |  | dict | 位置配置 |  |
| `size` | `JSONField` |  |  | dict | 尺寸配置 |  |
| `is_visible` | `BooleanField` |  |  | True | 是否可见 |  |
| `is_collapsible` | `BooleanField` |  |  | True | 是否可折叠 |  |
| `is_draggable` | `BooleanField` |  |  | True | 是否可拖动 |  |
| `is_resizable` | `BooleanField` |  |  | True | 是否可调整大小 |  |
| `dependencies` | `JSONField` |  |  | list | 依赖的卡片ID列表 |  |
| `display_order` | `IntegerField` |  |  | 0 | 显示顺序 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### DashboardConfigModel

- 来源文件：`apps/dashboard/infrastructure/models.py`
- 数据表：`dashboard_config`
- 说明：仪表盘配置模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `config_id` | `CharField` |  | 是 |  | 配置唯一标识符 |  |
| `name` | `CharField` |  |  |  | 配置名称 |  |
| `description` | `TextField` |  |  |  | 描述 |  |
| `layout_config` | `JSONField` |  |  | dict | 布局配置 |  |
| `card_configs` | `JSONField` |  |  | list | 卡片配置列表 |  |
| `is_default` | `BooleanField` |  |  | False | 是否默认配置 |  |
| `is_active` | `BooleanField` |  |  | True | 是否激活 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### DashboardSnapshotModel

- 来源文件：`apps/dashboard/infrastructure/models.py`
- 数据表：`dashboard_snapshot`
- 说明：仪表盘快照模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` |  |  |  | 关联用户 | User |
| `snapshot_data` | `JSONField` |  |  |  | 快照数据 |  |
| `captured_at` | `DateTimeField` |  |  |  | 捕获时间 |  |

### DashboardUserConfigModel

- 来源文件：`apps/dashboard/infrastructure/models.py`
- 数据表：`dashboard_user_config`
- 说明：用户仪表盘配置模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `OneToOneField` |  |  |  | 关联用户 | User |
| `dashboard_config` | `ForeignKey` | 是 |  |  | 仪表盘配置 | DashboardConfigModel |
| `hidden_cards` | `JSONField` |  |  | list | 隐藏的卡片ID列表 |  |
| `collapsed_cards` | `JSONField` |  |  | list | 折叠的卡片ID列表 |  |
| `card_order` | `JSONField` |  |  | list | 卡片顺序 |  |
| `custom_card_config` | `JSONField` |  |  | dict | 自定义卡片配置 |  |
| `theme` | `CharField` |  |  | light | 主题 |  |
| `refresh_enabled` | `BooleanField` |  |  | True | 是否启用自动刷新 |  |
| `refresh_interval` | `IntegerField` |  |  | 60 | 刷新间隔（秒） |  |
| `last_updated` | `DateTimeField` |  |  |  | 最后更新时间 |  |


## data_center

### ArchiveMemberModel

- 来源文件：`apps/data_center/infrastructure/archive_models.py`
- 数据表：`data_center_archive_member`
- 说明：One exact RawPayload member covered by an immutable archive.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `id` | `BigAutoField` |  |  |  |  |  |
| `archive` | `ForeignKey` |  |  |  | data_center.ArchiveManifestModel | data_center.ArchiveManifestModel |
| `payload_id` | `UUIDField` |  |  |  |  |  |
| `payload_hash` | `CharField` |  |  |  |  |  |
| `record_digest` | `CharField` |  |  |  |  |  |
| `schema_fingerprint` | `CharField` |  |  |  |  |  |
| `fetched_at` | `DateTimeField` |  |  |  |  |  |
| `size_bytes` | `PositiveBigIntegerField` |  |  | 0 |  |  |

### ArchiveRestoreAuditModel

- 来源文件：`apps/data_center/infrastructure/archive_models.py`
- 数据表：`data_center_archive_restore_audit`
- 说明：Append-only evidence from one isolated archive staging restore.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `audit_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `operation_key` | `CharField` |  | 是 |  |  |  |
| `archive` | `ForeignKey` |  |  |  | data_center.ArchiveManifestModel | data_center.ArchiveManifestModel |
| `outcome` | `CharField` |  |  |  |  |  |
| `observed_checksum` | `CharField` |  |  |  |  |  |
| `observed_object_count` | `PositiveBigIntegerField` |  |  | 0 |  |  |
| `observed_size_bytes` | `PositiveBigIntegerField` |  |  | 0 |  |  |
| `restored_object_count` | `PositiveBigIntegerField` |  |  | 0 |  |  |
| `restored_bytes` | `PositiveBigIntegerField` |  |  | 0 |  |  |
| `started_at` | `DateTimeField` |  |  |  |  |  |
| `finished_at` | `DateTimeField` |  |  |  |  |  |
| `reason` | `TextField` |  |  |  |  |  |

### CandidateRawAuditManifestMemberModel

- 来源文件：`apps/data_center/infrastructure/candidate_raw_audit_manifest_models.py`
- 数据表：`data_center_candidate_raw_audit_manifest_member`
- 说明：One stable ordered RawAudit reference stored under a manifest header.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `id` | `BigAutoField` |  |  |  |  |  |
| `manifest` | `ForeignKey` |  |  |  |  | CandidateRawAuditManifestModel |
| `ordinal` | `PositiveIntegerField` |  |  |  |  |  |
| `raw_audit` | `ForeignKey` |  |  |  | data_center.RawAuditModel | data_center.RawAuditModel |
| `raw_audit_version` | `CharField` |  |  |  |  |  |
| `raw_audit_content_hash` | `CharField` |  |  |  |  |  |
| `provider_name` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `run_id` | `UUIDField` |  |  |  |  |  |
| `ingested_run_id` | `UUIDField` |  |  |  |  |  |

### CandidateRawAuditManifestModel

- 来源文件：`apps/data_center/infrastructure/candidate_raw_audit_manifest_models.py`
- 数据表：`data_center_candidate_raw_audit_manifest`
- 说明：Immutable manifest header bound to one canonical publication candidate.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `manifest_id` | `UUIDField` |  |  | uuid4 |  |  |
| `manifest_version` | `CharField` |  |  |  |  |  |
| `publication` | `OneToOneField` |  |  |  | data_center.CanonicalPublicationModel | data_center.CanonicalPublicationModel |
| `publication_hash` | `CharField` |  |  |  |  |  |
| `run_id` | `UUIDField` |  |  |  |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `publication_key` | `CharField` |  |  |  |  |  |
| `task_attempt_id` | `CharField` |  |  |  |  |  |
| `raw_audit_count` | `PositiveIntegerField` |  |  |  |  |  |
| `raw_audit_hash` | `CharField` |  |  |  |  |  |
| `manifest_hash` | `CharField` |  | 是 |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### _CandidateManifestAppendOnlyModel

- 来源文件：`apps/data_center/infrastructure/candidate_raw_audit_manifest_models.py`
- 抽象模型：是
- 说明：Block row rewrites and deletes while allowing repository-owned inserts.

### DataOwnerRegistrationModel

- 来源文件：`apps/data_center/infrastructure/catalog_models.py`
- 数据表：`data_center_data_owner_registration`
- 说明：Dataset ownership, business accountability and acceptance owner.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `dataset_key` | `CharField` |  | 是 |  |  |  |
| `data_platform_owner` | `CharField` |  |  |  |  |  |
| `business_owner` | `CharField` |  |  |  |  |  |
| `acceptance_owner` | `CharField` |  |  |  |  |  |
| `active` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### DatasetContractModel

- 来源文件：`apps/data_center/infrastructure/catalog_models.py`
- 数据表：`data_center_dataset_contract`
- 说明：Versioned, active Dataset Contract runtime record.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `contract_version` | `CharField` |  |  |  |  |  |
| `schema_version` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `frequency` | `CharField` |  |  |  |  |  |
| `decision_critical` | `BooleanField` |  |  | False |  |  |
| `fields` | `JSONField` |  |  | list |  |  |
| `freshness_seconds` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `execution_freshness_seconds` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `calendar_response_max_age_seconds` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `comparable_group` | `CharField` |  |  |  |  |  |
| `active` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### DatasetProviderBindingModel

- 来源文件：`apps/data_center/infrastructure/catalog_models.py`
- 数据表：`data_center_dataset_provider_binding`
- 说明：Versioned provider routing row for one dataset contract.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `contract_version` | `CharField` |  |  |  |  |  |
| `schema_version` | `CharField` |  |  |  |  |  |
| `provider` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `priority` | `PositiveIntegerField` |  |  | 100 |  |  |
| `freshness_seconds` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `validator_key` | `CharField` |  |  |  |  |  |
| `enabled` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### DatasetPublicationPolicyModel

- 来源文件：`apps/data_center/infrastructure/catalog_models.py`
- 数据表：`data_center_dataset_publication_policy`
- 说明：Versioned publication gate for one dataset contract.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `contract_version` | `CharField` |  |  |  |  |  |
| `schema_version` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  | legacy |  |  |
| `member_codec_version` | `CharField` | 是 |  |  |  |  |
| `minimum_coverage_ratio` | `FloatField` |  |  |  |  |  |
| `allow_partial` | `BooleanField` |  |  | False |  |  |
| `conflict_action` | `CharField` |  |  |  |  |  |
| `required_evidence` | `JSONField` |  |  | list |  |  |
| `retention_days` | `PositiveIntegerField` |  |  |  |  |  |
| `active` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### EgressRequestAuditModel

- 来源文件：`apps/data_center/infrastructure/egress_models.py`
- 数据表：`data_center_egress_request_audit`
- 说明：Bounded audit evidence for each attempted egress transport.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `request_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `provider_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `target_host` | `CharField` |  |  |  |  |  |
| `deployment_region` | `CharField` |  |  |  |  |  |
| `rule_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `egress_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `attempt` | `PositiveSmallIntegerField` |  |  | 1 |  |  |
| `outcome` | `CharField` |  |  |  |  |  |
| `error_code` | `CharField` |  |  |  |  |  |
| `latency_ms` | `FloatField` | 是 |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### EgressRoutingRuleModel

- 来源文件：`apps/data_center/infrastructure/egress_models.py`
- 数据表：`data_center_egress_routing_rule`
- 说明：One provider/domain/region routing rule.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `provider_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `domain_pattern` | `CharField` |  |  |  |  |  |
| `deployment_region` | `CharField` |  |  |  |  |  |
| `strategy` | `CharField` |  |  |  |  |  |
| `fixed_egress_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `priority` | `PositiveIntegerField` |  |  | 100 |  |  |
| `enabled` | `BooleanField` |  |  | False |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### EvaluationActualAppendOnlyModel

- 来源文件：`apps/data_center/infrastructure/evaluation_actual_manifest_models.py`
- 抽象模型：是
- 说明：Base model enforcing repository-only inserts and immutable rows.

### EvaluationActualManifestReceiptModel

- 来源文件：`apps/data_center/infrastructure/evaluation_actual_manifest_models.py`
- 数据表：`data_center_evaluation_actual_manifest`
- 说明：Complete internally materialized actual-manifest receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `source_definition` | `ForeignKey` |  |  |  |  | EvaluationActualSourceDefinitionModel |
| `manifest_id` | `CharField` |  |  |  |  |  |
| `manifest_version` | `CharField` |  |  |  |  |  |
| `manifest_content_hash` | `CharField` |  | 是 |  |  |  |
| `owner` | `CharField` |  |  | data_center |  |  |
| `dataset` | `CharField` |  |  |  |  |  |
| `subject_code` | `CharField` |  |  |  |  |  |
| `industry_code` | `CharField` |  |  |  |  |  |
| `as_of_time` | `DateTimeField` |  |  |  |  |  |
| `produced_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `knowledge_scope` | `CharField` |  |  |  |  |  |
| `is_verified` | `BooleanField` |  |  |  |  |  |
| `coverage_ratio` | `DecimalField` |  |  |  |  |  |
| `missing_count` | `PositiveIntegerField` |  |  |  |  |  |
| `estimated_count` | `PositiveIntegerField` |  |  |  |  |  |
| `unknown_count` | `PositiveIntegerField` |  |  |  |  |  |
| `selected_versions_hash` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `receipt_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### EvaluationActualSourceDefinitionModel

- 来源文件：`apps/data_center/infrastructure/evaluation_actual_manifest_models.py`
- 数据表：`data_center_evaluation_actual_source`
- 说明：Canonical versioned owner definition and registration receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `source_id` | `CharField` |  |  |  |  |  |
| `source_version` | `CharField` |  |  |  |  |  |
| `source_content_hash` | `CharField` |  | 是 |  |  |  |
| `owner` | `CharField` |  |  | data_center |  |  |
| `dataset` | `CharField` |  |  |  |  |  |
| `subject_code` | `CharField` |  |  |  |  |  |
| `industry_code` | `CharField` |  |  |  |  |  |
| `calendar_id` | `CharField` |  |  |  |  |  |
| `calendar_version` | `CharField` |  |  |  |  |  |
| `calendar_content_hash` | `CharField` |  |  |  |  |  |
| `knowledge_scope` | `CharField` |  |  |  |  |  |
| `require_verified` | `BooleanField` |  |  |  |  |  |
| `minimum_coverage_ratio` | `DecimalField` |  |  |  |  |  |
| `maximum_missing_count` | `PositiveIntegerField` |  |  |  |  |  |
| `maximum_estimated_count` | `PositiveIntegerField` |  |  |  |  |  |
| `maximum_unknown_count` | `PositiveIntegerField` |  |  |  |  |  |
| `registered_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `record_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### ArchiveManifestModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_archive_manifest`
- 说明：Checksum-verified archive evidence.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `archive_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `object_count` | `PositiveBigIntegerField` |  |  | 0 |  |  |
| `size_bytes` | `PositiveBigIntegerField` |  |  | 0 |  |  |
| `location` | `CharField` |  |  |  |  |  |
| `checksum` | `CharField` |  |  |  |  |  |
| `state` | `CharField` |  |  | ArchiveState.PLANNED.value |  |  |
| `created_at` | `DateTimeField` |  |  | timezone.now |  |  |
| `verified_at` | `DateTimeField` | 是 |  |  |  |  |
| `retention_until` | `DateTimeField` | 是 |  |  |  |  |
| `contract_version` | `CharField` |  |  |  |  |  |
| `schema_version` | `CharField` |  |  |  |  |  |
| `format_version` | `CharField` |  |  | raw-payload-fernet-jsonl-gzip-v1 |  |  |
| `encryption_algorithm` | `CharField` |  |  |  |  |  |
| `encryption_key_ref` | `CharField` |  |  |  |  |  |
| `encryption_key_version` | `CharField` |  |  |  |  |  |
| `coverage_started_at` | `DateTimeField` | 是 |  |  |  |  |
| `coverage_ended_at` | `DateTimeField` | 是 |  |  |  |  |
| `restore_outcome` | `CharField` |  |  | ArchiveRestoreOutcome.NOT_TESTED.value |  |  |
| `last_restored_at` | `DateTimeField` | 是 |  |  |  |  |

### CapitalFlowFactModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_capital_flow_fact`
- 说明：Capital-flow data: main-force / retail net inflows per security per day.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `asset_code` | `CharField` |  |  |  |  |  |
| `flow_date` | `DateField` |  |  |  |  |  |
| `main_net` | `DecimalField` | 是 |  |  | Main-force net inflow (CNY) |  |
| `retail_net` | `DecimalField` | 是 |  |  | Retail net inflow (CNY) |  |
| `super_large_net` | `DecimalField` | 是 |  |  |  |  |
| `large_net` | `DecimalField` | 是 |  |  |  |  |
| `medium_net` | `DecimalField` | 是 |  |  |  |  |
| `small_net` | `DecimalField` | 是 |  |  |  |  |
| `source` | `CharField` |  |  |  |  |  |
| `fetched_at` | `DateTimeField` |  |  |  |  |  |
| `extra` | `JSONField` |  |  | dict |  |  |
| `contract_version` | `CharField` |  |  | 1.0 |  |  |
| `schema_version` | `CharField` |  |  | 1.0 |  |  |
| `source_record_id` | `CharField` |  |  |  |  |  |
| `raw_payload_hash` | `CharField` |  |  |  |  |  |
| `quality_status` | `CharField` |  |  | accepted |  |  |
| `revision_number` | `PositiveSmallIntegerField` |  |  | 1 |  |  |
| `ingested_run_id` | `UUIDField` | 是 |  |  |  |  |

### ExchangeCalendarSnapshotFactModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_exchange_calendar_snapshot_fact`
- 说明：Append-only complete daily calendar bound to one retained raw response.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `raw_payload` | `OneToOneField` |  |  |  |  | RawPayloadModel |
| `raw_payload_hash` | `CharField` |  | 是 |  |  |  |
| `exchange` | `CharField` |  |  |  |  |  |
| `coverage_start` | `DateField` |  |  |  |  |  |
| `coverage_end` | `DateField` |  |  |  |  |  |
| `days` | `JSONField` |  |  |  |  |  |
| `provider_name` | `CharField` |  |  |  |  |  |
| `raw_reference` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  |  |  |  |  |
| `first_seen_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `source_published_at` | `DateTimeField` | 是 |  |  |  |  |
| `record_digest` | `CharField` |  | 是 |  |  |  |

### FinancialSourceTimeAuditClaimModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_financial_source_time_audit_claim`
- 说明：Own the single RawAudit identity for one source-time capture UUID.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `capture_id` | `UUIDField` |  |  |  |  |  |
| `audit` | `OneToOneField` | 是 |  |  |  | RawAuditModel |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### InstrumentReferenceMappingModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_instrument_reference_mapping`
- 说明：Append-only versioned mapping content with first-knowledge seal.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `mapping_record_id` | `UUIDField` |  |  |  |  |  |
| `mapping_id` | `CharField` |  |  |  |  |  |
| `mapping_version` | `CharField` |  |  |  |  |  |
| `source_crosswalk_id` | `CharField` |  |  |  |  |  |
| `source_crosswalk_version` | `CharField` |  |  |  |  |  |
| `source_crosswalk_hash` | `CharField` |  |  |  |  |  |
| `content` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `record_digest` | `CharField` |  | 是 |  |  |  |

### InstrumentReferenceSnapshotModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_instrument_reference_snapshot`
- 说明：Append-only whole source batch with exact mapping and audit identities.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot_id` | `UUIDField` |  |  |  |  |  |
| `run_id` | `UUIDField` |  |  |  |  |  |
| `mapping_record` | `ForeignKey` |  |  |  |  | InstrumentReferenceMappingModel |
| `snapshot_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `record_digest` | `CharField` |  | 是 |  |  |  |
| `round_count` | `PositiveIntegerField` |  |  |  |  |  |
| `occurrence_count` | `PositiveIntegerField` |  |  |  |  |  |
| `record_count` | `PositiveIntegerField` |  |  |  |  |  |

### NewsFactModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_news_fact`
- 说明：News article associated with a stock or sector.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `asset_code` | `CharField` |  |  |  | Primary associated ticker (blank = market-wide news) |  |
| `title` | `CharField` |  |  |  |  |  |
| `summary` | `TextField` |  |  |  |  |  |
| `url` | `URLField` |  |  |  |  |  |
| `published_at` | `DateTimeField` |  |  |  |  |  |
| `source` | `CharField` |  |  |  |  |  |
| `external_id` | `CharField` |  |  |  | Provider article ID |  |
| `sentiment_score` | `FloatField` | 是 |  |  | Sentiment score in [-1, +1] |  |
| `extra` | `JSONField` |  |  | dict |  |  |
| `fetched_at` | `DateTimeField` |  |  |  |  |  |
| `contract_version` | `CharField` |  |  | 1.0 |  |  |
| `schema_version` | `CharField` |  |  | 1.0 |  |  |
| `source_record_id` | `CharField` |  |  |  |  |  |
| `raw_payload_hash` | `CharField` |  |  |  |  |  |
| `quality_status` | `CharField` |  |  | accepted |  |  |
| `revision_number` | `PositiveSmallIntegerField` |  |  | 1 |  |  |
| `ingested_run_id` | `UUIDField` | 是 |  |  |  |  |
| `available_at` | `DateTimeField` | 是 |  |  |  |  |

### QuarantineRecordModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_quarantine_record`
- 说明：Payload rejected by a Dataset Contract or reconciliation policy.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `quarantine_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `provider_name` | `CharField` |  |  |  |  |  |
| `natural_key` | `CharField` |  |  |  |  |  |
| `reason_code` | `CharField` |  |  |  |  |  |
| `reason` | `TextField` |  |  |  |  |  |
| `payload_hash` | `CharField` |  |  |  |  |  |
| `schema_fingerprint` | `CharField` |  |  |  |  |  |
| `payload` | `JSONField` |  |  | dict |  |  |
| `observed_at` | `DateTimeField` | 是 |  |  |  |  |
| `run_id` | `UUIDField` | 是 |  |  |  |  |
| `batch_id` | `UUIDField` | 是 |  |  |  |  |
| `resolution` | `CharField` |  |  | QuarantineResolution.OPEN.value |  |  |
| `quarantined_at` | `DateTimeField` |  |  |  |  |  |
| `resolved_at` | `DateTimeField` | 是 |  |  |  |  |
| `resolved_by` | `CharField` |  |  |  |  |  |

### RawAuditModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_raw_audit`
- 说明：Append-only log of every raw data fetch attempt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `provider_name` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  | DataCapability value (e.g. 'macro', 'historical_price') |  |
| `request_params` | `JSONField` |  |  | dict |  |  |
| `request_params_hash` | `CharField` |  |  |  |  |  |
| `response_payload_hash` | `CharField` |  |  |  |  |  |
| `schema_fingerprint` | `CharField` |  |  |  |  |  |
| `redacted` | `BooleanField` |  |  | True |  |  |
| `parser_version` | `CharField` |  |  |  |  |  |
| `payload_size_bytes` | `PositiveBigIntegerField` |  |  | 0 |  |  |
| `run_id` | `UUIDField` | 是 |  |  |  |  |
| `retention_until` | `DateTimeField` | 是 |  |  |  |  |
| `ingested_run_id` | `UUIDField` | 是 |  |  |  |  |
| `content_hash` | `CharField` | 是 |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `row_count` | `IntegerField` |  |  | 0 | Number of rows fetched |  |
| `latency_ms` | `FloatField` | 是 |  |  |  |  |
| `error_message` | `TextField` |  |  |  |  |  |
| `fetched_at` | `DateTimeField` |  |  |  |  |  |
| `extra` | `JSONField` |  |  | dict |  |  |

### RawPayloadModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_raw_payload`
- 说明：Hash-addressed, redacted raw provider payload.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `payload_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `provider_name` | `CharField` |  |  |  |  |  |
| `payload_hash` | `CharField` |  | 是 |  |  |  |
| `schema_fingerprint` | `CharField` |  |  |  |  |  |
| `payload` | `JSONField` |  |  | dict |  |  |
| `request_params` | `JSONField` |  |  | dict |  |  |
| `run_id` | `UUIDField` | 是 |  |  |  |  |
| `batch_id` | `UUIDField` | 是 |  |  |  |  |
| `content_type` | `CharField` |  |  | application/json |  |  |
| `parser_version` | `CharField` |  |  |  |  |  |
| `redacted` | `BooleanField` |  |  | True |  |  |
| `payload_size_bytes` | `PositiveBigIntegerField` |  |  | 0 |  |  |
| `fetched_at` | `DateTimeField` |  |  |  |  |  |
| `retention_until` | `DateTimeField` | 是 |  |  |  |  |

### RetentionPolicyModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_retention_policy`
- 说明：Versioned Data Center dataset retention rule.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `policy_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `version` | `PositiveIntegerField` |  |  |  |  |  |
| `retention_days` | `PositiveIntegerField` |  |  |  |  |  |
| `archive_after_days` | `PositiveIntegerField` | 是 |  |  |  |  |
| `archive_retention_days` | `PositiveIntegerField` | 是 |  |  |  |  |
| `priority` | `CharField` |  |  | normal |  |  |
| `active` | `BooleanField` |  |  | False |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### SchemaFingerprintModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_schema_fingerprint`
- 说明：Observed provider schema signature and evolution evidence.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `fingerprint` | `CharField` |  |  |  |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `provider_name` | `CharField` |  |  |  |  |  |
| `fields` | `JSONField` |  |  | list |  |  |
| `parser_version` | `CharField` |  |  |  |  |  |
| `first_seen_at` | `DateTimeField` |  |  |  |  |  |
| `last_seen_at` | `DateTimeField` |  |  |  |  |  |
| `sample_count` | `PositiveBigIntegerField` |  |  | 1 |  |  |

### SectorMembershipFactModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_sector_membership`
- 说明：Sector / index constituent membership record.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `asset_code` | `CharField` |  |  |  |  |  |
| `sector_code` | `CharField` |  |  |  | Industry / index code (e.g. 399300.SZ for CSI 300) |  |
| `sector_name` | `CharField` |  |  |  |  |  |
| `effective_date` | `DateField` |  |  |  |  |  |
| `expiry_date` | `DateField` | 是 |  |  | Null = currently active |  |
| `weight` | `DecimalField` | 是 |  |  | Weight in index (0–1) |  |
| `source` | `CharField` |  |  |  |  |  |
| `fetched_at` | `DateTimeField` |  |  |  |  |  |
| `contract_version` | `CharField` |  |  | 1.0 |  |  |
| `schema_version` | `CharField` |  |  | 1.0 |  |  |
| `source_record_id` | `CharField` |  |  |  |  |  |
| `raw_payload_hash` | `CharField` |  |  |  |  |  |
| `quality_status` | `CharField` |  |  | accepted |  |  |
| `revision_number` | `PositiveSmallIntegerField` |  |  | 1 |  |  |
| `ingested_run_id` | `UUIDField` | 是 |  |  |  |  |

### StorageHoldModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_storage_hold`
- 说明：Non-destructive deletion hold for a dataset, run or archive.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `hold_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `resource_type` | `CharField` |  |  |  |  |  |
| `resource_key` | `CharField` |  |  |  |  |  |
| `reason` | `TextField` |  |  |  |  |  |
| `created_by` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  | timezone.now |  |  |
| `expires_at` | `DateTimeField` | 是 |  |  |  |  |
| `released_at` | `DateTimeField` | 是 |  |  |  |  |

### SyncBatchModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_sync_batch`
- 说明：Bounded provider/dataset slice in a :class:`SyncRunModel`.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `batch_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `run_id` | `UUIDField` |  |  |  |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `provider_name` | `CharField` |  |  |  |  |  |
| `idempotency_key` | `CharField` |  | 是 |  |  |  |
| `state` | `CharField` |  |  | SyncItemState.PENDING.value |  |  |
| `requested` | `PositiveIntegerField` |  |  | 0 |  |  |
| `fetched` | `PositiveIntegerField` |  |  | 0 |  |  |
| `validated` | `PositiveIntegerField` |  |  | 0 |  |  |
| `quarantined` | `PositiveIntegerField` |  |  | 0 |  |  |
| `succeeded` | `PositiveIntegerField` |  |  | 0 |  |  |
| `failed` | `PositiveIntegerField` |  |  | 0 |  |  |
| `stored` | `PositiveIntegerField` |  |  | 0 |  |  |
| `published` | `PositiveIntegerField` |  |  | 0 |  |  |
| `window_start` | `DateField` | 是 |  |  |  |  |
| `window_end` | `DateField` | 是 |  |  |  |  |
| `started_at` | `DateTimeField` | 是 |  |  |  |  |
| `finished_at` | `DateTimeField` | 是 |  |  |  |  |
| `error_code` | `CharField` |  |  |  |  |  |
| `error_message` | `TextField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### SyncCheckpointModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_sync_checkpoint`
- 说明：Durable cursor for resuming a failed or interrupted batch.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `checkpoint_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `run_id` | `UUIDField` |  |  |  |  |  |
| `batch_id` | `UUIDField` |  |  |  |  |  |
| `cursor_name` | `CharField` |  |  |  |  |  |
| `cursor_value` | `CharField` |  |  |  |  |  |
| `state` | `CharField` |  |  | SyncItemState.SUCCEEDED.value |  |  |
| `processed` | `PositiveIntegerField` |  |  | 0 |  |  |
| `failed` | `PositiveIntegerField` |  |  | 0 |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `error_code` | `CharField` |  |  |  |  |  |

### SyncExecutionIdentityModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_sync_execution_identity`
- 说明：Durable, server-issued identity for one future sync execution.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `identity_hash` | `CharField` |  |  |  |  |  |
| `run_id` | `UUIDField` |  |  |  |  |  |
| `ingested_run_id` | `UUIDField` |  |  |  |  |  |
| `batch_id` | `UUIDField` |  |  |  |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `provider_name` | `CharField` |  |  |  |  |  |

### SyncRunModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_sync_run`
- 说明：One resumable dataset ingestion run.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `run_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `trigger` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  | SyncRunStatus.REQUESTED.value |  |  |
| `outcome` | `CharField` |  |  | blocked |  |  |
| `provider_name` | `CharField` |  |  |  |  |  |
| `contract_version` | `CharField` |  |  |  |  |  |
| `config_snapshot_hash` | `CharField` |  |  |  |  |  |
| `requested` | `PositiveIntegerField` |  |  | 0 |  |  |
| `fetched` | `PositiveIntegerField` |  |  | 0 |  |  |
| `validated` | `PositiveIntegerField` |  |  | 0 |  |  |
| `quarantined` | `PositiveIntegerField` |  |  | 0 |  |  |
| `succeeded` | `PositiveIntegerField` |  |  | 0 |  |  |
| `failed` | `PositiveIntegerField` |  |  | 0 |  |  |
| `stored` | `PositiveIntegerField` |  |  | 0 |  |  |
| `published` | `PositiveIntegerField` |  |  | 0 |  |  |
| `unchanged` | `PositiveIntegerField` |  |  | 0 |  |  |
| `started_at` | `DateTimeField` |  |  |  |  |  |
| `finished_at` | `DateTimeField` | 是 |  |  |  |  |
| `error_code` | `CharField` |  |  |  |  |  |
| `error_message` | `TextField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### ValuationFactModel

- 来源文件：`apps/data_center/infrastructure/fact_and_operational_models.py`
- 数据表：`data_center_valuation_fact`
- 说明：Daily valuation multiples snapshot (PE, PB, PS, etc.).

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `asset_code` | `CharField` |  |  |  |  |  |
| `val_date` | `DateField` |  |  |  |  |  |
| `pe_ttm` | `DecimalField` | 是 |  |  |  |  |
| `pe_static` | `DecimalField` | 是 |  |  |  |  |
| `pb` | `DecimalField` | 是 |  |  |  |  |
| `ps_ttm` | `DecimalField` | 是 |  |  |  |  |
| `market_cap` | `DecimalField` | 是 |  |  | Market cap in CNY |  |
| `float_market_cap` | `DecimalField` | 是 |  |  |  |  |
| `dv_ratio` | `DecimalField` | 是 |  |  | Dividend yield |  |
| `source` | `CharField` |  |  |  |  |  |
| `observed_at` | `DateTimeField` | 是 |  |  |  |  |
| `fetched_at` | `DateTimeField` |  |  | timezone.now |  |  |
| `extra` | `JSONField` |  |  | dict |  |  |
| `contract_version` | `CharField` |  |  | 1.0 |  |  |
| `schema_version` | `CharField` |  |  | 1.0 |  |  |
| `source_record_id` | `CharField` |  |  |  |  |  |
| `raw_payload_hash` | `CharField` |  |  |  |  |  |
| `quality_status` | `CharField` |  |  | accepted |  |  |
| `revision_number` | `PositiveSmallIntegerField` |  |  | 1 |  |  |
| `ingested_run_id` | `UUIDField` | 是 |  |  |  |  |
| `available_at` | `DateTimeField` | 是 |  |  |  |  |

### MacroFactorResearchCalendarPeriodModel

- 来源文件：`apps/data_center/infrastructure/macro_factor_research_source_models.py`
- 数据表：`data_center_macro_factor_calendar_period`
- 说明：One exact period member under a source-definition calendar.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `source_definition` | `ForeignKey` |  |  |  |  | MacroFactorResearchSourceDefinitionModel |
| `row_id` | `CharField` |  |  |  |  |  |
| `period_id` | `CharField` |  |  |  |  |  |
| `kind` | `CharField` |  |  |  |  |  |
| `observation_date` | `DateField` |  |  |  |  |  |
| `target_period_start` | `DateField` |  |  |  |  |  |
| `target_period_end` | `DateField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### MacroFactorResearchMemberRuleModel

- 来源文件：`apps/data_center/infrastructure/macro_factor_research_source_models.py`
- 数据表：`data_center_macro_factor_member_rule`
- 说明：One exact target/proxy fact identity and decoding rule.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `source_definition` | `ForeignKey` |  |  |  |  | MacroFactorResearchSourceDefinitionModel |
| `period` | `ForeignKey` |  |  |  |  | MacroFactorResearchCalendarPeriodModel |
| `row_id` | `CharField` |  |  |  |  |  |
| `role` | `CharField` |  |  |  |  |  |
| `member_code` | `CharField` |  |  |  |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `business_key` | `CharField` |  |  |  |  |  |
| `value_field` | `CharField` |  |  |  |  |  |
| `unit_field` | `CharField` |  |  |  |  |  |
| `expected_unit` | `CharField` |  |  |  |  |  |
| `value_encoding` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### MacroFactorResearchSourceDefinitionModel

- 来源文件：`apps/data_center/infrastructure/macro_factor_research_source_models.py`
- 数据表：`data_center_macro_factor_source`
- 说明：Canonical definition header and trusted registration receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `source_id` | `CharField` |  |  |  |  |  |
| `source_version` | `CharField` |  |  |  |  |  |
| `source_content_hash` | `CharField` |  | 是 |  |  |  |
| `manifest_calendar_version` | `CharField` |  | 是 |  |  |  |
| `owner` | `CharField` |  |  | data_center |  |  |
| `target_code` | `CharField` |  |  |  |  |  |
| `candidate_asset_codes` | `JSONField` |  |  |  |  |  |
| `calendar_id` | `CharField` |  |  |  |  |  |
| `calendar_version` | `CharField` |  |  |  |  |  |
| `calendar_content_hash` | `CharField` |  |  |  |  |  |
| `source_contract_id` | `CharField` |  |  |  |  |  |
| `source_contract_version` | `CharField` |  |  |  |  |  |
| `source_contract_hash` | `CharField` |  |  |  |  |  |
| `knowledge_scope` | `CharField` |  |  |  |  |  |
| `require_verified` | `BooleanField` |  |  |  |  |  |
| `minimum_coverage_ratio` | `DecimalField` |  |  |  |  |  |
| `maximum_missing_count` | `PositiveIntegerField` |  |  |  |  |  |
| `maximum_estimated_count` | `PositiveIntegerField` |  |  |  |  |  |
| `maximum_unknown_count` | `PositiveIntegerField` |  |  |  |  |  |
| `registered_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `record_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### MacroFactorSourceAppendOnlyModel

- 来源文件：`apps/data_center/infrastructure/macro_factor_research_source_models.py`
- 抽象模型：是
- 说明：Base model enforcing repository-only inserts and immutable rows.

### MarketThermometerConfigModel

- 来源文件：`apps/data_center/infrastructure/market_thermometer_models.py`
- 数据表：`data_center_market_thermometer_config`
- 说明：Singleton configuration for market thermometer scoring.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `short_window` | `PositiveIntegerField` |  |  | 5 |  |  |
| `medium_window` | `PositiveIntegerField` |  |  | 20 |  |  |
| `long_window` | `PositiveIntegerField` |  |  | 252 |  |  |
| `monthly_long_window` | `PositiveIntegerField` |  |  | 24 |  |  |
| `daily_stale_days` | `PositiveIntegerField` |  |  | 3 |  |  |
| `monthly_stale_days` | `PositiveIntegerField` |  |  | 45 |  |  |
| `min_valid_components` | `PositiveIntegerField` |  |  | 4 |  |  |
| `component_weights` | `JSONField` |  |  | dict | Component weights keyed by component_key |  |
| `warm_threshold` | `FloatField` |  |  | 35.0 |  |  |
| `hot_threshold` | `FloatField` |  |  | 60.0 |  |  |
| `overheat_threshold` | `FloatField` |  |  | 75.0 |  |  |
| `extreme_threshold` | `FloatField` |  |  | 85.0 |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### MarketThermometerSnapshotModel

- 来源文件：`apps/data_center/infrastructure/market_thermometer_models.py`
- 数据表：`data_center_market_thermometer_snapshot`
- 说明：One persisted market thermometer snapshot per observed date.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `observed_at` | `DateField` |  | 是 |  |  |  |
| `score` | `FloatField` |  |  |  |  |  |
| `band` | `CharField` |  |  |  |  |  |
| `change_5d` | `FloatField` | 是 |  |  |  |  |
| `change_20d` | `FloatField` | 是 |  |  |  |  |
| `components` | `JSONField` |  |  | list |  |  |
| `trigger_reasons` | `JSONField` |  |  | list |  |  |
| `stale_components` | `JSONField` |  |  | list |  |  |
| `missing_components` | `JSONField` |  |  | list |  |  |
| `valid_component_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `data_source` | `CharField` |  |  | calculated |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | False |  |  |
| `blocked_reason` | `TextField` |  |  |  |  |  |
| `calculated_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### MarketThermometerUserOverrideModel

- 来源文件：`apps/data_center/infrastructure/market_thermometer_models.py`
- 数据表：`data_center_market_thermometer_user_override`
- 说明：Per-user threshold override for market thermometer interpretation.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `OneToOneField` |  |  |  |  | settings.AUTH_USER_MODEL |
| `warm_threshold` | `FloatField` |  |  | 35.0 |  |  |
| `hot_threshold` | `FloatField` |  |  | 60.0 |  |  |
| `overheat_threshold` | `FloatField` |  |  | 75.0 |  |  |
| `extreme_threshold` | `FloatField` |  |  | 85.0 |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### AssetAliasModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_asset_alias`
- 说明：Cross-provider ticker alias table.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `asset` | `ForeignKey` |  |  |  |  | AssetMasterModel |
| `provider_name` | `CharField` |  |  |  | Provider identifier (e.g. 'akshare', 'wind') |  |
| `alias_code` | `CharField` |  |  |  | Provider-local ticker code |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### AssetMasterModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_asset_master`
- 说明：Security master table: one row per canonical ticker.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `code` | `CharField` |  | 是 |  | Canonical ticker (Tushare format, e.g. 600519.SH) |  |
| `name` | `CharField` |  |  |  | Full security name |  |
| `short_name` | `CharField` |  |  |  | Display short name |  |
| `asset_type` | `CharField` |  |  |  |  |  |
| `exchange` | `CharField` |  |  |  |  |  |
| `is_active` | `BooleanField` |  |  | True |  |  |
| `list_date` | `DateField` | 是 |  |  | IPO / listing date |  |
| `delist_date` | `DateField` | 是 |  |  |  |  |
| `sector` | `CharField` |  |  |  |  |  |
| `industry` | `CharField` |  |  |  |  |  |
| `currency` | `CharField` |  |  | CNY |  |  |
| `total_shares` | `DecimalField` | 是 |  |  | Total shares outstanding |  |
| `extra` | `JSONField` |  |  | dict | Provider-specific extras |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### DataProviderSettingsModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_provider_settings`
- 说明：Global provider behaviour settings — singleton row (pk=1).

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `default_source` | `CharField` |  |  | akshare | Default data source preference |  |
| `enable_failover` | `BooleanField` |  |  | True | Auto-switch to backup provider when primary fails |  |
| `failover_tolerance` | `FloatField` |  |  | 0.01 | Cross-provider consistency tolerance (0.01 = 1 %) |  |
| `description` | `TextField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### FinancialCapacityGovernanceRecordModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_financial_capacity_governance_record`
- 说明：Deployment-time, independently reviewed request ceilings; no records are seeded.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `approval_id` | `CharField` |  | 是 |  |  |  |
| `stage` | `CharField` |  |  |  |  |  |
| `record` | `JSONField` |  |  |  |  |  |
| `created_by` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### FinancialCapacityGovernanceRevocationModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_financial_capacity_governance_revocation`
- 说明：Append-only revocation event; an approval row is never reactivated in place.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `governance_record` | `OneToOneField` |  |  |  |  | FinancialCapacityGovernanceRecordModel |
| `revoked_by` | `CharField` |  |  |  |  |  |
| `revoked_at` | `DateTimeField` |  |  |  |  |  |

### FinancialCapacityOwnerApprovalEventModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_financial_capacity_owner_approval_event`
- 说明：Independent owner-auth event required before a ceiling can reach runtime.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `governance_record` | `OneToOneField` |  |  |  |  | FinancialCapacityGovernanceRecordModel |
| `event_id` | `CharField` |  | 是 |  |  |  |
| `approved_by` | `CharField` |  |  |  |  |  |
| `approved_at` | `DateTimeField` |  |  |  |  |  |
| `approval_receipt_sha256` | `CharField` |  |  |  |  |  |
| `record_sha256` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### FinancialFactModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_financial_fact`
- 说明：Financial statement fact (single line-item per row).

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `asset_code` | `CharField` |  |  |  |  |  |
| `period_end` | `DateField` |  |  |  | Period end date (e.g. 2024-12-31) |  |
| `period_type` | `CharField` |  |  |  |  |  |
| `metric_code` | `CharField` |  |  |  | Metric identifier (e.g. revenue, net_profit, total_assets) |  |
| `value` | `DecimalField` |  |  |  |  |  |
| `unit` | `CharField` |  |  |  |  |  |
| `source` | `CharField` |  |  |  |  |  |
| `report_date` | `DateField` | 是 |  |  | Date report was published |  |
| `fetched_at` | `DateTimeField` |  |  |  |  |  |
| `extra` | `JSONField` |  |  | dict |  |  |
| `decision_evidence` | `JSONField` |  |  | dict |  |  |
| `contract_version` | `CharField` |  |  | 1.0 |  |  |
| `schema_version` | `CharField` |  |  | 1.0 |  |  |
| `source_record_id` | `CharField` |  |  |  |  |  |
| `raw_payload_hash` | `CharField` |  |  |  |  |  |
| `quality_status` | `CharField` |  |  | accepted |  |  |
| `revision_number` | `PositiveSmallIntegerField` |  |  | 1 |  |  |
| `ingested_run_id` | `UUIDField` | 是 |  |  |  |  |
| `announced_at` | `DateTimeField` | 是 |  |  |  |  |
| `available_at` | `DateTimeField` | 是 |  |  |  |  |

### FinancialPublicationCapacityEvidenceModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_financial_capacity_slice_evidence`
- 说明：Append-only per-slice evidence stored outside the compact workflow header.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `workflow` | `ForeignKey` |  |  |  |  | FinancialPublicationCapacityWorkflowModel |
| `ordinal` | `PositiveIntegerField` |  |  |  |  |  |
| `evidence` | `JSONField` |  |  |  |  |  |
| `evidence_sha256` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### FinancialPublicationCapacityManifestItemModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_financial_capacity_manifest_item`
- 说明：One immutable ordinal in a frozen capacity workload manifest.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `workflow` | `ForeignKey` |  |  |  |  | FinancialPublicationCapacityWorkflowModel |
| `ordinal` | `PositiveIntegerField` |  |  |  |  |  |
| `asset_code` | `CharField` |  |  |  |  |  |
| `announcement_date` | `DateField` |  |  |  |  |  |
| `item_sha256` | `CharField` |  |  |  |  |  |

### FinancialPublicationCapacityWorkflowModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_financial_publication_capacity_workflow`
- 说明：Durable, revision-checked checkpoint for financial capacity workflows.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `workflow_id` | `CharField` |  |  |  |  |  |
| `approval_id` | `CharField` | 是 | 是 |  |  |  |
| `receipt_sha256` | `CharField` | 是 | 是 |  |  |  |
| `stage` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `revision` | `PositiveIntegerField` |  |  | 1 |  |  |
| `checkpoint` | `JSONField` |  |  |  |  |  |
| `started_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### FinancialScopeCapacityImportConsumptionModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_financial_scope_capacity_consumption`
- 说明：Append-only one-time link from a verified S6 import to formal workflow start.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `scope_import` | `OneToOneField` |  |  |  |  | FinancialScopeCapacityImportModel |
| `workflow_id` | `CharField` |  | 是 |  |  |  |
| `record_sha256` | `CharField` |  |  |  |  |  |
| `event_payload` | `JSONField` |  |  |  |  |  |
| `event_sha256` | `CharField` |  | 是 |  |  |  |
| `consumed_at` | `DateTimeField` |  |  |  |  |  |

### FinancialScopeCapacityImportModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_financial_scope_capacity_import`
- 说明：Append-only production ledger for validated S6 full-scope capacity evidence.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `import_id` | `UUIDField` |  | 是 | uuid4 |  |  |
| `environment` | `CharField` |  |  | production |  |  |
| `release_manifest_sha256` | `CharField` |  |  |  |  |  |
| `capacity_receipt_raw_sha256` | `CharField` |  |  |  |  |  |
| `scope_report_raw_sha256` | `CharField` |  |  |  |  |  |
| `scope_report_review_sha256` | `CharField` |  |  |  |  |  |
| `receipt_sha256` | `CharField` |  | 是 |  |  |  |
| `scope_pointer_sha256` | `CharField` |  | 是 |  |  |  |
| `candidate_sha` | `CharField` |  |  |  |  |  |
| `candidate_image_id` | `CharField` |  |  |  |  |  |
| `target_trade_date` | `DateField` |  |  |  |  |  |
| `release_universe_sha256` | `CharField` |  |  |  |  |  |
| `provider_identities_sha256` | `CharField` |  |  |  |  |  |
| `scope_manifest_sha256` | `CharField` |  |  |  |  |  |
| `financial_universe_sha256` | `CharField` |  |  |  |  |  |
| `financial_provider_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `financial_provider_identity_sha256` | `CharField` |  |  |  |  |  |
| `source_revision_sha256` | `CharField` |  |  |  |  |  |
| `evidence_ledger_sha256` | `CharField` |  |  |  |  |  |
| `artifact_ledger_sha256` | `CharField` |  |  |  |  |  |
| `owner_approval_id` | `CharField` |  |  |  |  |  |
| `owner_event_id` | `CharField` |  | 是 |  |  |  |
| `reviewer_approval_id` | `CharField` |  |  |  |  |  |
| `reviewer_event_id` | `CharField` |  | 是 |  |  |  |
| `production_ceiling_approval_id` | `CharField` |  |  |  |  |  |
| `production_ceiling_event_id` | `CharField` |  | 是 |  |  |  |
| `production_ceiling_record_sha256` | `CharField` |  |  |  |  |  |
| `record_payload` | `JSONField` |  |  |  |  |  |
| `record_sha256` | `CharField` |  | 是 |  |  |  |
| `imported_by` | `CharField` |  |  |  |  |  |
| `imported_at` | `DateTimeField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### FinancialScopeManifestCurrentPointerModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_financial_scope_manifest_current_pointer`
- 说明：Current reviewed scope report used as the financial capacity input authority.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `environment` | `CharField` |  | 是 |  |  |  |
| `report_payload` | `JSONField` |  |  |  |  |  |
| `report_sha256` | `CharField` |  |  |  |  |  |
| `owner_approval_id` | `CharField` |  |  |  |  |  |
| `owner_event_id` | `CharField` |  |  |  |  |  |
| `reviewer_approval_id` | `CharField` |  |  |  |  |  |
| `reviewer_event_id` | `CharField` |  |  |  |  |  |
| `revision` | `PositiveBigIntegerField` |  |  | 1 |  |  |
| `updated_by` | `CharField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### FundNavFactModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_fund_nav_fact`
- 说明：Fund NAV (net asset value) fact.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `fund_code` | `CharField` |  |  |  |  |  |
| `nav_date` | `DateField` |  |  |  |  |  |
| `nav` | `DecimalField` |  |  |  | Unit NAV |  |
| `acc_nav` | `DecimalField` | 是 |  |  | Accumulated NAV |  |
| `daily_return` | `DecimalField` | 是 |  |  | Daily return rate |  |
| `source` | `CharField` |  |  |  |  |  |
| `fetched_at` | `DateTimeField` |  |  |  |  |  |
| `extra` | `JSONField` |  |  | dict |  |  |
| `contract_version` | `CharField` |  |  | 1.0 |  |  |
| `schema_version` | `CharField` |  |  | 1.0 |  |  |
| `source_record_id` | `CharField` |  |  |  |  |  |
| `raw_payload_hash` | `CharField` |  |  |  |  |  |
| `quality_status` | `CharField` |  |  | accepted |  |  |
| `revision_number` | `PositiveSmallIntegerField` |  |  | 1 |  |  |
| `ingested_run_id` | `UUIDField` | 是 |  |  |  |  |
| `available_at` | `DateTimeField` | 是 |  |  |  |  |

### IndicatorCatalogModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_indicator_catalog`
- 说明：Catalogue of all known macro / economic indicator definitions.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `code` | `CharField` |  | 是 |  | Canonical indicator code (e.g. CN_GDP) |  |
| `name_cn` | `CharField` |  |  |  | 中文名称 |  |
| `name_en` | `CharField` |  |  |  |  |  |
| `description` | `TextField` |  |  |  |  |  |
| `default_unit` | `CharField` |  |  |  | e.g. 亿元, %, bps |  |
| `default_period_type` | `CharField` |  |  | M |  |  |
| `category` | `CharField` |  |  |  | e.g. growth, inflation, money, trade, financial |  |
| `is_active` | `BooleanField` |  |  | True |  |  |
| `extra` | `JSONField` |  |  | dict |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### IndicatorUnitRuleModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_indicator_unit_rule`
- 说明：Canonical unit-governance rules for macro indicators.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `indicator_code` | `CharField` |  |  |  | Matches IndicatorCatalogModel.code |  |
| `source_type` | `CharField` |  |  |  | Logical provider source type (e.g. akshare, tushare); blank = default rule |  |
| `dimension_key` | `CharField` |  |  |  | Dimension classification such as currency, rate, index, price |  |
| `original_unit` | `CharField` |  |  |  | Provider raw unit before normalization |  |
| `storage_unit` | `CharField` |  |  |  | Canonical storage unit persisted in MacroFactModel.unit |  |
| `display_unit` | `CharField` |  |  |  | Frontend display unit returned by macro query APIs |  |
| `multiplier_to_storage` | `DecimalField` |  |  | 1 | Multiply the raw value by this factor to get canonical storage value |  |
| `is_active` | `BooleanField` |  |  | True |  |  |
| `priority` | `IntegerField` |  |  | 0 |  |  |
| `description` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### MacroFactModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_macro_fact`
- 说明：Stored macro-economic data points (time-series rows).

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `indicator_code` | `CharField` |  |  |  | Matches IndicatorCatalogModel.code |  |
| `reporting_period` | `DateField` |  |  |  |  |  |
| `value` | `DecimalField` |  |  |  |  |  |
| `unit` | `CharField` |  |  |  |  |  |
| `source` | `CharField` |  |  |  | Provider name |  |
| `revision_number` | `SmallIntegerField` |  |  | 0 |  |  |
| `published_at` | `DateField` | 是 |  |  |  |  |
| `quality` | `CharField` |  |  | valid |  |  |
| `fetched_at` | `DateTimeField` |  |  |  |  |  |
| `contract_version` | `CharField` |  |  | 1.0 |  |  |
| `schema_version` | `CharField` |  |  | 1.0 |  |  |
| `source_record_id` | `CharField` |  |  |  |  |  |
| `raw_payload_hash` | `CharField` |  |  |  |  |  |
| `quality_status` | `CharField` |  |  | accepted |  |  |
| `ingested_run_id` | `UUIDField` | 是 |  |  |  |  |
| `available_at` | `DateTimeField` | 是 |  |  |  |  |
| `extra` | `JSONField` |  |  | dict |  |  |

### PriceBarModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_price_bar`
- 说明：Daily / intraday OHLCV price bar for a single security.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `asset_code` | `CharField` |  |  |  |  |  |
| `bar_date` | `DateField` |  |  |  |  |  |
| `freq` | `CharField` |  |  | 1d |  |  |
| `adjustment` | `CharField` |  |  | none |  |  |
| `open` | `DecimalField` |  |  |  |  |  |
| `high` | `DecimalField` |  |  |  |  |  |
| `low` | `DecimalField` |  |  |  |  |  |
| `close` | `DecimalField` |  |  |  |  |  |
| `volume` | `DecimalField` | 是 |  |  | Volume in shares |  |
| `amount` | `DecimalField` | 是 |  |  | Turnover amount in CNY |  |
| `source` | `CharField` |  |  |  |  |  |
| `fetched_at` | `DateTimeField` |  |  |  |  |  |
| `contract_version` | `CharField` |  |  | 1.0 |  |  |
| `schema_version` | `CharField` |  |  | 1.0 |  |  |
| `source_record_id` | `CharField` |  |  |  |  |  |
| `raw_payload_hash` | `CharField` |  |  |  |  |  |
| `quality_status` | `CharField` |  |  | accepted |  |  |
| `revision_number` | `PositiveSmallIntegerField` |  |  | 1 |  |  |
| `ingested_run_id` | `UUIDField` | 是 |  |  |  |  |

### ProductionCoverageUniverseConfigModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_production_coverage_universe_config`
- 说明：Singleton configuration for production coverage diagnostics universe.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `universe_id` | `CharField` |  |  | active_a_share | Logical universe identifier used by readiness diagnostics |  |
| `asset_type` | `CharField` |  |  | stock | AssetMaster asset_type included in coverage diagnostics |  |
| `exchanges` | `JSONField` |  |  | list | Included MarketExchange codes, e.g. SSE/SZSE/BSE |  |
| `include_inactive` | `BooleanField` |  |  | False | Include inactive/delisted assets in the coverage denominator |  |
| `min_active_asset_count` | `PositiveIntegerField` |  |  | 4000 |  |  |
| `min_star_market_count` | `PositiveIntegerField` |  |  | 200 |  |  |
| `min_chinext_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `min_bse_count` | `PositiveIntegerField` |  |  | 50 |  |  |
| `description` | `TextField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### ProviderConfigModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_provider_config`
- 说明：Configurable external data-provider entry.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | `CharField` |  | 是 |  | Provider name (unique identifier, e.g. 'tushare_main') |  |
| `source_type` | `CharField` |  |  |  | Underlying data source type |  |
| `is_active` | `BooleanField` |  |  | True | Whether this provider is enabled |  |
| `priority` | `IntegerField` |  |  | 100 | Dispatch priority — lower value = higher precedence |  |
| `http_url` | `URLField` |  |  |  | Custom HTTP URL (e.g. Tushare third-party proxy) |  |
| `api_endpoint` | `URLField` |  |  |  | Override API endpoint URL |  |
| `extra_config` | `JSONField` |  |  | dict | Provider-specific parameters |  |
| `description` | `TextField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### PublisherCatalogModel

- 来源文件：`apps/data_center/infrastructure/models.py`
- 数据表：`data_center_publisher_catalog`
- 说明：Canonical publisher / institution registry for provenance governance.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `code` | `CharField` |  | 是 |  | Stable publisher code such as PBOC, NBS, GACC |  |
| `canonical_name` | `CharField` |  |  |  | Canonical Chinese display name |  |
| `canonical_name_en` | `CharField` |  |  |  |  |  |
| `publisher_class` | `CharField` |  |  |  |  |  |
| `aliases` | `JSONField` |  |  | list | Known alias names |  |
| `country_code` | `CharField` |  |  | CN |  |  |
| `website` | `URLField` |  |  |  |  |  |
| `is_active` | `BooleanField` |  |  | True |  |  |
| `description` | `TextField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### ImmutableModelMixin

- 来源文件：`apps/data_center/infrastructure/pit_models.py`
- 抽象模型：是
- 说明：Reject updates so evidence records can only be appended.

### PriceLimitSnapshotFactModel

- 来源文件：`apps/data_center/infrastructure/price_limit_snapshot_models.py`
- 数据表：`data_center_price_limit_snapshot_fact`
- 说明：One exact Tushare limit response, linked to its immutable RawPayload.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot_id` | `UUIDField` |  |  |  |  |  |
| `raw_payload` | `OneToOneField` |  |  |  | data_center.RawPayloadModel | data_center.RawPayloadModel |
| `raw_payload_hash` | `CharField` |  | 是 |  |  |  |
| `asset_code` | `CharField` |  |  |  |  |  |
| `effective_trade_date` | `DateField` |  |  |  |  |  |
| `provider_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `provider_name` | `CharField` |  |  |  |  |  |
| `lower_limit_price` | `CharField` |  |  |  |  |  |
| `upper_limit_price` | `CharField` |  |  |  |  |  |
| `raw_reference` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `response_completed_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `record_digest` | `CharField` |  | 是 |  |  |  |

### CanonicalPublicationModel

- 来源文件：`apps/data_center/infrastructure/publication_rollback_models.py`
- 数据表：`data_center_canonical_publication`
- 说明：Versioned selection of canonical facts for a dataset scope.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `publication_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `publication_key` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `state` | `CharField` |  |  | PublicationState.CANDIDATE.value |  |  |
| `selected_source` | `CharField` |  |  |  |  |  |
| `publication_hash` | `CharField` |  |  |  |  |  |
| `member_manifest_hash` | `CharField` |  |  |  |  |  |
| `member_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `conflict_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `coverage_requested_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `coverage_eligible_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `coverage_selected_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `coverage_missing_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `coverage_conflict_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `as_of` | `DateTimeField` | 是 |  |  |  |  |
| `published_at` | `DateTimeField` | 是 |  |  |  |  |
| `superseded_at` | `DateTimeField` | 是 |  |  |  |  |
| `reinstated_at` | `DateTimeField` | 是 |  |  |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | False |  |  |
| `blocked_reason` | `TextField` |  |  |  |  |  |
| `created_by` | `CharField` |  |  | system |  |  |
| `run_id` | `UUIDField` | 是 |  |  |  |  |
| `scope_blocks` | `JSONField` |  |  | list |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |
| `members_sealed_at` | `DateTimeField` | 是 |  |  |  |  |

### CanonicalPublicationPointerModel

- 来源文件：`apps/data_center/infrastructure/publication_rollback_models.py`
- 数据表：`data_center_canonical_publication_pointer`
- 说明：One lockable current-publication scope row.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `pointer_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `publication_key` | `CharField` |  |  |  |  |  |
| `publication_id` | `UUIDField` | 是 |  |  |  |  |
| `publication_hash` | `CharField` |  |  |  |  |  |
| `activation_id` | `CharField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### CoverageSnapshotModel

- 来源文件：`apps/data_center/infrastructure/publication_rollback_models.py`
- 数据表：`data_center_coverage_snapshot`
- 说明：Immutable coverage evidence for a publication.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `coverage_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `publication_id` | `UUIDField` |  | 是 |  |  |  |
| `requested_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `eligible_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `selected_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `missing_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `conflict_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `generated_at` | `DateTimeField` |  |  |  |  |  |

### PublicationMemberModel

- 来源文件：`apps/data_center/infrastructure/publication_rollback_models.py`
- 数据表：`data_center_publication_member`
- 说明：Selected fact reference belonging to a canonical publication.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `member_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `publication_id` | `UUIDField` |  |  |  |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `natural_key` | `CharField` |  |  |  |  |  |
| `source` | `CharField` |  |  |  |  |  |
| `source_record_id` | `CharField` |  |  |  |  |  |
| `fact_table` | `CharField` |  |  |  |  |  |
| `fact_pk` | `CharField` |  |  |  |  |  |
| `observed_at` | `DateTimeField` | 是 |  |  |  |  |
| `raw_payload_hash` | `CharField` |  |  |  |  |  |
| `quality_status` | `CharField` |  |  | accepted |  |  |
| `revision_number` | `PositiveIntegerField` |  |  | 1 |  |  |
| `available_at` | `DateTimeField` | 是 |  |  |  |  |
| `fetched_at` | `DateTimeField` | 是 |  |  |  |  |
| `source_published_at` | `DateTimeField` | 是 |  |  |  |  |
| `raw_payload_scope` | `CharField` |  |  |  |  |  |
| `fact_content_hash` | `CharField` |  |  |  |  |  |

### PublicationRollbackModel

- 来源文件：`apps/data_center/infrastructure/publication_rollback_models.py`
- 数据表：`data_center_publication_rollback`
- 说明：Durable evidence for an explicit canonical publication rollback.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `rollback_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `target_publication_id` | `UUIDField` |  |  |  |  |  |
| `previous_publication_id` | `UUIDField` |  |  |  |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `publication_key` | `CharField` |  |  |  |  |  |
| `reason` | `TextField` |  |  |  |  |  |
| `operator` | `CharField` |  |  |  |  |  |
| `observed_at` | `DateTimeField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### QmtBridgeAuditModel

- 来源文件：`apps/data_center/infrastructure/qmt_bridge_models.py`
- 数据表：`data_center_qmt_bridge_audit`
- 说明：Append-only binding lifecycle audit, without credentials or local paths.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `binding` | `ForeignKey` |  |  |  |  | QmtBridgeBindingModel |
| `actor_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `action` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### QmtBridgeBatchModel

- 来源文件：`apps/data_center/infrastructure/qmt_bridge_models.py`
- 数据表：`data_center_qmt_bridge_batch`
- 说明：Immutable batch digest and durable receipt for retry safety.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `binding` | `ForeignKey` |  |  |  |  | QmtBridgeBindingModel |
| `batch_id` | `UUIDField` |  |  |  |  |  |
| `digest` | `CharField` |  |  |  |  |  |
| `receipt` | `JSONField` |  |  | dict |  |  |
| `payload` | `JSONField` |  |  | dict |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### QmtBridgeBindingModel

- 来源文件：`apps/data_center/infrastructure/qmt_bridge_models.py`
- 数据表：`data_center_qmt_bridge_binding`
- 说明：One local Agent paired to this server and an authenticated owner.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `owner` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `agent_id` | `CharField` |  |  |  |  |  |
| `server_url` | `URLField` |  |  |  |  |  |
| `provider` | `OneToOneField` | 是 |  |  | data_center.ProviderConfigModel | data_center.ProviderConfigModel |
| `assets` | `JSONField` |  |  | list |  |  |
| `pairing_hash` | `CharField` |  |  |  |  |  |
| `pairing_expires_at` | `DateTimeField` | 是 |  |  |  |  |
| `token_hash` | `CharField` |  |  |  |  |  |
| `token_expires_at` | `DateTimeField` | 是 |  |  |  |  |
| `paired_at` | `DateTimeField` | 是 |  |  |  |  |
| `enabled` | `BooleanField` |  |  | False |  |  |
| `revoked` | `BooleanField` |  |  | False |  |  |
| `poll_seconds` | `PositiveIntegerField` |  |  | 10 |  |  |
| `freshness_seconds` | `PositiveIntegerField` |  |  | 60 |  |  |
| `quote_volume_multiplier` | `DecimalField` | 是 |  |  |  |  |
| `bar_volume_multiplier` | `DecimalField` | 是 |  |  |  |  |
| `last_seen_at` | `DateTimeField` | 是 |  |  |  |  |
| `last_observed_at` | `DateTimeField` | 是 |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### QmtBridgeNonceModel

- 来源文件：`apps/data_center/infrastructure/qmt_bridge_models.py`
- 数据表：`data_center_qmt_bridge_nonce`
- 说明：Replay protection for signed machine requests.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `binding` | `ForeignKey` |  |  |  |  | QmtBridgeBindingModel |
| `nonce` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### QuoteSnapshotModel

- 来源文件：`apps/data_center/infrastructure/quote_snapshot_models.py`
- 数据表：`data_center_quote_snapshot`
- 说明：Intraday real-time quote snapshot.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `asset_code` | `CharField` |  |  |  |  |  |
| `snapshot_at` | `DateTimeField` |  |  |  |  |  |
| `fetched_at` | `DateTimeField` | 是 |  |  |  |  |
| `current_price` | `DecimalField` |  |  |  |  |  |
| `open` | `DecimalField` | 是 |  |  |  |  |
| `high` | `DecimalField` | 是 |  |  |  |  |
| `low` | `DecimalField` | 是 |  |  |  |  |
| `prev_close` | `DecimalField` | 是 |  |  |  |  |
| `volume` | `DecimalField` | 是 |  |  |  |  |
| `amount` | `DecimalField` | 是 |  |  |  |  |
| `bid` | `DecimalField` | 是 |  |  |  |  |
| `ask` | `DecimalField` | 是 |  |  |  |  |
| `change_pct` | `DecimalField` | 是 |  |  |  |  |
| `source` | `CharField` |  |  |  |  |  |
| `extra` | `JSONField` |  |  | dict |  |  |
| `contract_version` | `CharField` |  |  | 1.0 |  |  |
| `schema_version` | `CharField` |  |  | 1.0 |  |  |
| `source_record_id` | `CharField` |  |  |  |  |  |
| `raw_payload_hash` | `CharField` |  |  |  |  |  |
| `quality_status` | `CharField` |  |  | accepted |  |  |
| `revision_number` | `PositiveSmallIntegerField` |  |  | 1 |  |  |
| `ingested_run_id` | `UUIDField` | 是 |  |  |  |  |

### AssetGroupRevisionModel

- 来源文件：`apps/data_center/infrastructure/research_data_foundation_models.py`
- 数据表：`data_center_asset_group_revision`
- 说明：Versioned custom asset-group definition without embedded members.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `group_code` | `CharField` |  |  |  |  |  |
| `revision` | `PositiveIntegerField` |  |  |  |  |  |
| `name` | `CharField` |  |  |  |  |  |
| `source` | `CharField` |  |  |  |  |  |
| `effective_at` | `DateTimeField` |  |  |  |  |  |
| `effective_to` | `DateTimeField` | 是 |  |  |  |  |
| `description` | `TextField` |  |  |  |  |  |
| `is_active` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### InvestorFlowDefinitionModel

- 来源文件：`apps/data_center/infrastructure/research_data_foundation_models.py`
- 数据表：`data_center_investor_flow_definition`
- 说明：Versioned actor/measure/source definition with mandatory proxy labels.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `flow_code` | `CharField` |  |  |  |  |  |
| `definition_version` | `PositiveIntegerField` |  |  |  |  |  |
| `actor_code` | `CharField` |  |  |  |  |  |
| `actor_name` | `CharField` |  |  |  |  |  |
| `measure_kind` | `CharField` |  |  |  |  |  |
| `canonical_unit` | `CharField` |  |  |  |  |  |
| `frequency` | `CharField` |  |  |  |  |  |
| `source` | `CharField` |  |  |  |  |  |
| `effective_at` | `DateTimeField` |  |  |  |  |  |
| `effective_to` | `DateTimeField` | 是 |  |  |  |  |
| `is_proxy` | `BooleanField` |  |  | False |  |  |
| `proxy_target_actor_code` | `CharField` |  |  |  |  |  |
| `proxy_methodology_ref` | `CharField` |  |  |  |  |  |
| `description` | `TextField` |  |  |  |  |  |
| `is_active` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### OperatingMetricDefinitionModel

- 来源文件：`apps/data_center/infrastructure/research_data_foundation_models.py`
- 数据表：`data_center_operating_metric_definition`
- 说明：Versioned operating-metric taxonomy row; migrations provide no seed.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `metric_code` | `CharField` |  |  |  |  |  |
| `definition_version` | `PositiveIntegerField` |  |  |  |  |  |
| `name` | `CharField` |  |  |  |  |  |
| `canonical_unit` | `CharField` |  |  |  |  |  |
| `frequency` | `CharField` |  |  |  |  |  |
| `source` | `CharField` |  |  |  |  |  |
| `effective_at` | `DateTimeField` |  |  |  |  |  |
| `effective_to` | `DateTimeField` | 是 |  |  |  |  |
| `description` | `TextField` |  |  |  |  |  |
| `is_active` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### RetentionPlanMemberModel

- 来源文件：`apps/data_center/infrastructure/retention_models.py`
- 数据表：`data_center_retention_plan_member`
- 说明：Immutable plan evidence plus monotonic execution state for one payload.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `id` | `BigAutoField` |  |  |  |  |  |
| `plan` | `ForeignKey` |  |  |  |  | RetentionPlanModel |
| `ordinal` | `PositiveIntegerField` |  |  |  |  |  |
| `payload_id` | `UUIDField` |  |  |  |  |  |
| `payload_hash` | `CharField` |  |  |  |  |  |
| `record_digest` | `CharField` |  |  |  |  |  |
| `schema_fingerprint` | `CharField` |  |  |  |  |  |
| `fetched_at` | `DateTimeField` |  |  |  |  |  |
| `retention_until` | `DateTimeField` | 是 |  |  |  |  |
| `size_bytes` | `PositiveBigIntegerField` |  |  | 0 |  |  |
| `decision` | `CharField` |  |  |  |  |  |
| `archive` | `ForeignKey` | 是 |  |  | data_center.ArchiveManifestModel | data_center.ArchiveManifestModel |
| `execution` | `CharField` |  |  | RetentionMemberExecution.PENDING.value |  |  |
| `execution_reason` | `TextField` |  |  |  |  |  |
| `deleted_at` | `DateTimeField` | 是 |  |  |  |  |

### RetentionPlanModel

- 来源文件：`apps/data_center/infrastructure/retention_models.py`
- 数据表：`data_center_retention_plan`
- 说明：Exact bounded retention snapshot and its single enforcement claim.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `plan_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `operation_id` | `CharField` |  | 是 |  |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `policy_id` | `UUIDField` |  |  |  |  |  |
| `policy_version` | `PositiveIntegerField` |  |  |  |  |  |
| `requested` | `PositiveIntegerField` |  |  |  |  |  |
| `candidates` | `PositiveIntegerField` |  |  | 0 |  |  |
| `planned` | `PositiveIntegerField` |  |  | 0 |  |  |
| `held` | `PositiveIntegerField` |  |  | 0 |  |  |
| `blocked` | `PositiveIntegerField` |  |  | 0 |  |  |
| `bytes_planned` | `PositiveBigIntegerField` |  |  | 0 |  |  |
| `cutoff` | `DateTimeField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `expires_at` | `DateTimeField` |  |  |  |  |  |
| `snapshot_digest` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `enforce_operation_id` | `CharField` | 是 | 是 |  |  |  |
| `outcome` | `CharField` |  |  |  |  |  |
| `deleted` | `PositiveIntegerField` |  |  | 0 |  |  |
| `execution_blocked` | `PositiveIntegerField` |  |  | 0 |  |  |
| `failed` | `PositiveIntegerField` |  |  | 0 |  |  |
| `bytes_deleted` | `PositiveBigIntegerField` |  |  | 0 |  |  |
| `finished_at` | `DateTimeField` | 是 |  |  |  |  |
| `reason` | `TextField` |  |  |  |  |  |

### RetentionRunModel

- 来源文件：`apps/data_center/infrastructure/retention_models.py`
- 数据表：`data_center_retention_run`
- 说明：Append-only evidence for one bounded retention pass.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `run_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `policy_version` | `PositiveIntegerField` | 是 |  |  |  |  |
| `dry_run` | `BooleanField` |  |  | True |  |  |
| `outcome` | `CharField` |  |  |  |  |  |
| `requested` | `PositiveIntegerField` |  |  | 0 |  |  |
| `candidates` | `PositiveIntegerField` |  |  | 0 |  |  |
| `planned` | `PositiveIntegerField` |  |  | 0 |  |  |
| `deleted` | `PositiveIntegerField` |  |  | 0 |  |  |
| `held` | `PositiveIntegerField` |  |  | 0 |  |  |
| `blocked` | `PositiveIntegerField` |  |  | 0 |  |  |
| `bytes_planned` | `PositiveBigIntegerField` |  |  | 0 |  |  |
| `bytes_deleted` | `PositiveBigIntegerField` |  |  | 0 |  |  |
| `cutoff` | `DateTimeField` | 是 |  |  |  |  |
| `started_at` | `DateTimeField` |  |  |  |  |  |
| `finished_at` | `DateTimeField` |  |  |  |  |  |
| `reason` | `TextField` |  |  |  |  |  |

### SyncItemAttemptModel

- 来源文件：`apps/data_center/infrastructure/sync_item_attempt_models.py`
- 数据表：`data_center_sync_item_attempt`
- 说明：One durable, single-transition asset attempt in a sync batch.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `attempt_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `run_id` | `UUIDField` |  |  |  |  |  |
| `batch_id` | `UUIDField` |  |  |  |  |  |
| `dataset_key` | `CharField` |  |  |  |  |  |
| `asset_code` | `CharField` |  |  |  |  |  |
| `phase` | `CharField` |  |  |  |  |  |
| `attempt_number` | `PositiveIntegerField` |  |  |  |  |  |
| `state` | `CharField` |  |  |  |  |  |
| `execution_token` | `CharField` |  |  |  |  |  |
| `started_at` | `DateTimeField` |  |  |  |  |  |
| `finished_at` | `DateTimeField` | 是 |  |  |  |  |
| `stored_count` | `PositiveIntegerField` |  |  | 0 |  |  |
| `error_code` | `CharField` |  |  |  |  |  |
| `error_message` | `TextField` |  |  |  |  |  |
| `universe_hash` | `CharField` |  |  |  |  |  |
| `authority_content_hash` | `CharField` |  |  |  |  |  |
| `evidence_hash` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |


## decision_rhythm

### DecisionInputSnapshotModel

- 来源文件：`apps/decision_rhythm/infrastructure/input_snapshot_models.py`
- 数据表：`decision_input_snapshot`
- 说明：Append-only decision evidence package.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot_id` | `CharField` |  |  |  |  |  |
| `schema_version` | `CharField` |  |  | v1 |  |  |
| `as_of_time` | `DateTimeField` |  |  |  |  |  |
| `state_hash` | `CharField` |  | 是 |  |  |  |
| `pit_manifest_id` | `CharField` |  |  |  |  |  |
| `components` | `JSONField` |  |  | dict |  |  |
| `portfolio_snapshot_id` | `CharField` |  |  |  |  |  |
| `config_version` | `CharField` |  |  |  |  |  |
| `strategy_version` | `CharField` |  |  |  |  |  |
| `prompt_version` | `CharField` |  |  |  |  |  |
| `freshness` | `JSONField` |  |  | dict |  |  |
| `quality` | `JSONField` |  |  | dict |  |  |
| `must_not_use` | `BooleanField` |  |  | False |  |  |
| `missing_components` | `JSONField` |  |  | list |  |  |
| `creation_reason` | `CharField` |  |  |  |  |  |
| `correlation_id` | `CharField` |  |  |  |  |  |
| `caller` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### DecisionModelParamAuditLogModel

- 来源文件：`apps/decision_rhythm/infrastructure/model_param_models.py`
- 数据表：`decision_model_param_audit_log`
- 说明：决策模型参数审计日志 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `log_id` | `CharField` |  | 是 |  | 日志唯一标识符 |  |
| `param_key` | `CharField` |  |  |  | 参数键 |  |
| `old_value` | `TextField` |  |  |  | 旧值 |  |
| `new_value` | `TextField` |  |  |  | 新值 |  |
| `env` | `CharField` |  |  | dev | 环境 |  |
| `changed_by` | `CharField` |  |  |  | 变更人 |  |
| `change_reason` | `TextField` |  |  |  | 变更原因 |  |
| `changed_at` | `DateTimeField` |  |  |  | 变更时间 |  |

### DecisionModelParamConfigModel

- 来源文件：`apps/decision_rhythm/infrastructure/model_param_models.py`
- 数据表：`decision_model_param_config`
- 说明：决策模型参数配置 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `config_id` | `CharField` |  | 是 |  | 配置唯一标识符 |  |
| `param_key` | `CharField` |  |  |  | 参数键 |  |
| `param_value` | `TextField` |  |  |  | 参数值 |  |
| `param_type` | `CharField` |  |  | float | 参数类型 |  |
| `env` | `CharField` |  |  | dev | 环境 |  |
| `version` | `IntegerField` |  |  | 1 | 版本号 |  |
| `is_active` | `BooleanField` |  |  | True | 是否激活 |  |
| `description` | `TextField` |  |  |  | 参数描述 |  |
| `updated_by` | `CharField` |  |  |  | 最后修改人 |  |
| `updated_reason` | `TextField` |  |  |  | 变更说明 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### DecisionExecutionLinkModel

- 来源文件：`apps/decision_rhythm/infrastructure/recommendation_models.py`
- 数据表：`decision_execution_link`
- 说明：Link a manual account transaction to the system recommendation it followed.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `recommendation_id` | `CharField` |  |  |  | 关联的统一推荐 ID；manual_only 时为空 |  |
| `transaction_id` | `IntegerField` |  |  |  | account.TransactionModel ID |  |
| `transaction_source` | `CharField` |  |  | account_transaction | 成交来源：account.TransactionModel 或 simulated_trading.SimulatedTradeModel |  |
| `account_id` | `CharField` |  |  |  | 账户 ID |  |
| `security_code` | `CharField` |  |  |  | 证券代码 |  |
| `actual_action` | `CharField` |  |  |  | 实际动作 buy/sell |  |
| `match_method` | `CharField` |  |  | auto | 匹配方式 |  |
| `match_confidence` | `FloatField` |  |  | 0.0 | 匹配置信度 |  |
| `notes` | `TextField` |  |  |  | 备注 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### DecisionFeatureSnapshotModel

- 来源文件：`apps/decision_rhythm/infrastructure/recommendation_models.py`
- 数据表：`decision_feature_snapshot`
- 说明：决策特征快照 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot_id` | `CharField` |  | 是 |  | 快照唯一标识符 |  |
| `security_code` | `CharField` |  |  |  | 证券代码 |  |
| `snapshot_time` | `DateTimeField` |  |  |  | 快照时间 |  |
| `regime` | `CharField` |  |  |  | 当前 Regime 状态 |  |
| `regime_confidence` | `FloatField` |  |  | 0.0 | Regime 置信度 |  |
| `policy_level` | `CharField` |  |  |  | 政策档位 |  |
| `beta_gate_passed` | `BooleanField` |  |  | False | Beta Gate 是否通过 |  |
| `sentiment_score` | `FloatField` |  |  | 0.0 | 舆情分数 |  |
| `flow_score` | `FloatField` |  |  | 0.0 | 资金流向分数 |  |
| `technical_score` | `FloatField` |  |  | 0.0 | 技术面分数 |  |
| `fundamental_score` | `FloatField` |  |  | 0.0 | 基本面分数 |  |
| `alpha_model_score` | `FloatField` |  |  | 0.0 | Alpha 模型分数 |  |
| `extra_features` | `JSONField` |  |  | dict | 额外特征 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### UnifiedRecommendationModel

- 来源文件：`apps/decision_rhythm/infrastructure/recommendation_models.py`
- 数据表：`decision_unified_recommendation`
- 说明：统一推荐对象 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `recommendation_id` | `CharField` |  | 是 |  | 推荐唯一标识符 |  |
| `account_id` | `CharField` |  |  |  | 账户 ID |  |
| `security_code` | `CharField` |  |  |  | 证券代码 |  |
| `side` | `CharField` |  |  |  | 方向 |  |
| `regime` | `CharField` |  |  |  | 当前 Regime 状态 |  |
| `regime_confidence` | `FloatField` |  |  | 0.0 | Regime 置信度 |  |
| `policy_level` | `CharField` |  |  |  | 政策档位 |  |
| `beta_gate_passed` | `BooleanField` |  |  | False | Beta Gate 是否通过 |  |
| `sentiment_score` | `FloatField` |  |  | 0.0 | 舆情分数 |  |
| `flow_score` | `FloatField` |  |  | 0.0 | 资金流向分数 |  |
| `technical_score` | `FloatField` |  |  | 0.0 | 技术面分数 |  |
| `fundamental_score` | `FloatField` |  |  | 0.0 | 基本面分数 |  |
| `alpha_model_score` | `FloatField` |  |  | 0.0 | Alpha 模型分数 |  |
| `composite_score` | `FloatField` |  |  | 0.0 | 综合分数 |  |
| `confidence` | `FloatField` |  |  | 0.0 | 置信度 |  |
| `reason_codes` | `JSONField` |  |  | list | 原因代码列表 |  |
| `human_rationale` | `TextField` |  |  |  | 人类可读理由 |  |
| `fair_value` | `DecimalField` |  |  | Decimal('0') | 公允价值 |  |
| `entry_price_low` | `DecimalField` |  |  | Decimal('0') | 入场价格下限 |  |
| `entry_price_high` | `DecimalField` |  |  | Decimal('0') | 入场价格上限 |  |
| `target_price_low` | `DecimalField` |  |  | Decimal('0') | 目标价格下限 |  |
| `target_price_high` | `DecimalField` |  |  | Decimal('0') | 目标价格上限 |  |
| `stop_loss_price` | `DecimalField` |  |  | Decimal('0') | 止损价格 |  |
| `position_pct` | `FloatField` |  |  | 5.0 | 建议仓位比例 |  |
| `suggested_quantity` | `IntegerField` |  |  | 0 | 建议数量 |  |
| `max_capital` | `DecimalField` |  |  | Decimal('50000') | 最大资金量 |  |
| `source_signal_ids` | `JSONField` |  |  | list | 来源信号 ID 列表 |  |
| `source_candidate_ids` | `JSONField` |  |  | list | 来源候选 ID 列表 |  |
| `feature_snapshot` | `ForeignKey` | 是 |  |  | 关联的特征快照 | DecisionFeatureSnapshotModel |
| `status` | `CharField` |  |  | RecommendationStatus.NEW.value | 推荐状态 |  |
| `user_action` | `CharField` |  |  | UserDecisionAction.PENDING.value | 用户决策动作 |  |
| `user_action_note` | `TextField` |  |  |  | 用户决策备注 |  |
| `user_action_at` | `DateTimeField` | 是 |  |  | 用户动作时间 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### CooldownPeriodModel

- 来源文件：`apps/decision_rhythm/infrastructure/rhythm_models.py`
- 数据表：`cooldown_period`
- 说明：冷却期 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `cooldown_id` | `CharField` |  | 是 |  | 冷却期唯一标识符 |  |
| `asset_code` | `CharField` |  |  |  | 资产代码 |  |
| `last_decision_at` | `DateTimeField` | 是 |  |  | 最后决策时间 |  |
| `last_execution_at` | `DateTimeField` | 是 |  |  | 最后执行时间 |  |
| `min_decision_interval_hours` | `IntegerField` |  |  | 24 | 最小决策间隔（小时） |  |
| `min_execution_interval_hours` | `IntegerField` |  |  | 48 | 最小执行间隔（小时） |  |
| `same_asset_cooldown_hours` | `IntegerField` |  |  | 72 | 同资产冷却期（小时） |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### DecisionQuotaModel

- 来源文件：`apps/decision_rhythm/infrastructure/rhythm_models.py`
- 数据表：`decision_quota`
- 说明：决策配额 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `quota_id` | `CharField` |  | 是 |  | 配额唯一标识符 |  |
| `account_id` | `CharField` |  |  | default | 关联账户 ID，不同账户独立配额 |  |
| `period` | `CharField` |  |  |  | 配额周期 |  |
| `max_decisions` | `IntegerField` |  |  | 10 | 最大决策次数 |  |
| `max_execution_count` | `IntegerField` |  |  | 5 | 最大执行次数 |  |
| `used_decisions` | `IntegerField` |  |  | 0 | 已使用决策次数 |  |
| `used_executions` | `IntegerField` |  |  | 0 | 已使用执行次数 |  |
| `period_start` | `DateTimeField` | 是 |  |  | 周期开始时间 |  |
| `period_end` | `DateTimeField` | 是 |  |  | 周期结束时间 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### DecisionRequestModel

- 来源文件：`apps/decision_rhythm/infrastructure/rhythm_models.py`
- 数据表：`decision_request`
- 说明：决策请求 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `request_id` | `CharField` |  | 是 |  | 请求唯一标识符 |  |
| `asset_code` | `CharField` |  |  |  | 资产代码 |  |
| `asset_class` | `CharField` |  |  |  | 资产类别 |  |
| `direction` | `CharField` |  |  |  | 方向 |  |
| `priority` | `CharField` |  |  | DecisionPriority.MEDIUM.value | 优先级 |  |
| `trigger_id` | `CharField` |  |  |  | 触发器 ID |  |
| `reason` | `TextField` |  |  |  | 原因 |  |
| `expected_confidence` | `FloatField` |  |  | 0.0 | 预期置信度 |  |
| `quantity` | `IntegerField` | 是 |  |  | 数量 |  |
| `notional` | `FloatField` | 是 |  |  | 名义金额 |  |
| `requested_at` | `DateTimeField` |  |  |  | 请求时间 |  |
| `expires_at` | `DateTimeField` | 是 |  |  | 过期时间 |  |
| `candidate_id` | `CharField` |  |  |  | 关联的候选 ID |  |
| `execution_target` | `CharField` |  |  | ExecutionTarget.NONE.value | 执行目标 |  |
| `execution_status` | `CharField` |  |  | ExecutionStatus.PENDING.value | 执行状态 |  |
| `executed_at` | `DateTimeField` | 是 |  |  | 执行时间 |  |
| `execution_ref` | `JSONField` | 是 |  |  | 执行引用（如 trade_id, position_id 等） |  |
| `unified_recommendation` | `ForeignKey` | 是 |  |  | 关联的统一推荐 | UnifiedRecommendationModel |
| `feature_snapshot` | `ForeignKey` | 是 |  |  | 关联的特征快照 | DecisionFeatureSnapshotModel |

### DecisionResponseModel

- 来源文件：`apps/decision_rhythm/infrastructure/rhythm_models.py`
- 数据表：`decision_response`
- 说明：决策响应 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `response_id` | `CharField` |  | 是 |  | 响应唯一标识符 |  |
| `request` | `OneToOneField` |  |  |  | 关联的决策请求 | DecisionRequestModel |
| `approved` | `BooleanField` |  |  | False | 是否批准 |  |
| `approval_reason` | `TextField` |  |  |  | 批准原因 |  |
| `scheduled_at` | `DateTimeField` | 是 |  |  | 调度时间 |  |
| `estimated_execution_at` | `DateTimeField` | 是 |  |  | 预计执行时间 |  |
| `rejection_reason` | `TextField` |  |  |  | 拒绝原因 |  |
| `wait_until` | `DateTimeField` | 是 |  |  | 等待直到 |  |
| `quota_status` | `JSONField` | 是 |  |  | 配额状态 |  |
| `cooldown_status` | `TextField` |  |  |  | 冷却状态 |  |
| `alternative_suggestions` | `JSONField` | 是 |  |  | 替代建议 |  |
| `responded_at` | `DateTimeField` |  |  |  | 响应时间 |  |

### ExecutionApprovalRequestModel

- 来源文件：`apps/decision_rhythm/infrastructure/valuation_models.py`
- 数据表：`decision_execution_approval_request`
- 说明：执行审批请求 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `request_id` | `CharField` |  | 是 |  | 请求唯一标识符 |  |
| `recommendation` | `ForeignKey` | 是 |  |  | 关联的投资建议（legacy，unified 路径可为空） | InvestmentRecommendationModel |
| `account_id` | `CharField` |  |  |  | 账户 ID |  |
| `security_code` | `CharField` |  |  |  | 证券代码 |  |
| `side` | `CharField` |  |  |  | 方向 |  |
| `approval_status` | `CharField` |  |  | PENDING | 审批状态 |  |
| `suggested_quantity` | `IntegerField` |  |  |  | 建议数量 |  |
| `market_price_at_review` | `DecimalField` | 是 |  |  | 审批时的市场价格 |  |
| `price_range_low` | `DecimalField` |  |  |  | 价格区间下限 |  |
| `price_range_high` | `DecimalField` |  |  |  | 价格区间上限 |  |
| `stop_loss_price` | `DecimalField` |  |  |  | 止损价格 |  |
| `risk_check_results` | `JSONField` |  |  | dict | 风控检查结果 |  |
| `reviewer_comments` | `TextField` |  |  |  | 审批评论 |  |
| `regime_source` | `CharField` |  |  | UNKNOWN | Regime 来源标识 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `reviewed_at` | `DateTimeField` | 是 |  |  | 审批时间 |  |
| `executed_at` | `DateTimeField` | 是 |  |  | 执行时间 |  |
| `unified_recommendation` | `ForeignKey` | 是 |  |  | 关联的统一推荐 | UnifiedRecommendationModel |
| `transition_plan` | `ForeignKey` | 是 |  |  | 关联的账户级调仓计划 | portfolio.PortfolioTransitionPlanModel |
| `execution_params_json` | `JSONField` | 是 |  | dict | 执行参数 JSON（价格区间、仓位等） |  |

### InvestmentRecommendationModel

- 来源文件：`apps/decision_rhythm/infrastructure/valuation_models.py`
- 数据表：`decision_investment_recommendation`
- 说明：投资建议 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `recommendation_id` | `CharField` |  | 是 |  | 建议唯一标识符 |  |
| `security_code` | `CharField` |  |  |  | 证券代码 |  |
| `account_id` | `CharField` |  |  | default | 账户 ID |  |
| `side` | `CharField` |  |  |  | 方向 |  |
| `confidence` | `FloatField` |  |  | 0.0 | 置信度 (0-1) |  |
| `valuation_method` | `CharField` |  |  |  | 估值方法 |  |
| `fair_value` | `DecimalField` |  |  |  | 公允价值 |  |
| `entry_price_low` | `DecimalField` |  |  |  | 入场价格下限 |  |
| `entry_price_high` | `DecimalField` |  |  |  | 入场价格上限 |  |
| `target_price_low` | `DecimalField` |  |  |  | 目标价格下限 |  |
| `target_price_high` | `DecimalField` |  |  |  | 目标价格上限 |  |
| `stop_loss_price` | `DecimalField` |  |  |  | 止损价格 |  |
| `position_size_pct` | `FloatField` |  |  | 5.0 | 建议仓位比例 |  |
| `max_capital` | `DecimalField` |  |  | 50000 | 最大资金量 |  |
| `reason_codes` | `JSONField` |  |  | list | 原因代码列表 |  |
| `human_readable_rationale` | `TextField` |  |  |  | 人类可读的理由 |  |
| `valuation_snapshot` | `ForeignKey` | 是 |  |  | 关联的估值快照 | ValuationSnapshotModel |
| `source_recommendation_ids` | `JSONField` |  |  | list | 来源建议 ID 列表 |  |
| `status` | `CharField` |  |  | ACTIVE | 建议状态 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### ValuationSnapshotModel

- 来源文件：`apps/decision_rhythm/infrastructure/valuation_models.py`
- 数据表：`decision_valuation_snapshot`
- 说明：估值快照 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot_id` | `CharField` |  | 是 |  | 快照唯一标识符 |  |
| `security_code` | `CharField` |  |  |  | 证券代码 |  |
| `valuation_method` | `CharField` |  |  |  | 估值方法 |  |
| `fair_value` | `DecimalField` |  |  |  | 公允价值 |  |
| `entry_price_low` | `DecimalField` |  |  |  | 入场价格下限 |  |
| `entry_price_high` | `DecimalField` |  |  |  | 入场价格上限 |  |
| `target_price_low` | `DecimalField` |  |  |  | 目标价格下限 |  |
| `target_price_high` | `DecimalField` |  |  |  | 目标价格上限 |  |
| `stop_loss_price` | `DecimalField` |  |  |  | 止损价格 |  |
| `calculated_at` | `DateTimeField` |  |  |  | 计算时间 |  |
| `input_parameters` | `JSONField` |  |  | dict | 输入参数 |  |
| `version` | `IntegerField` |  |  | 1 | 版本号 |  |
| `is_legacy` | `BooleanField` |  |  | False | 是否为历史数据迁移 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |


## equity

### ForecastBaselineAppendOnlyModel

- 来源文件：`apps/equity/infrastructure/forecast_baseline_models.py`
- 抽象模型：是
- 说明：Reject every mutation or deletion of persisted R1 evidence.

### ForecastBaselineApprovalEvidenceModel

- 来源文件：`apps/equity/infrastructure/forecast_baseline_models.py`
- 数据表：`equity_forecast_baseline_approval_evidence`
- 说明：Canonical Equity-owned baseline approval evidence.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `approval_id` | `CharField` |  |  |  |  |  |
| `approval_version` | `CharField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `forecast_origin_at` | `DateTimeField` |  |  |  |  |  |
| `approved_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `payload_schema` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |

### ForecastBaselineArtifactModel

- 来源文件：`apps/equity/infrastructure/forecast_baseline_models.py`
- 数据表：`equity_forecast_baseline_artifact`
- 说明：Canonical immutable ForecastBaselineArtifact payload.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `spec` | `ForeignKey` |  |  |  |  | ForecastBaselineSpecModel |
| `artifact_id` | `CharField` |  |  |  |  |  |
| `artifact_version` | `CharField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `spec_evidence_id` | `CharField` |  |  |  |  |  |
| `spec_evidence_version` | `CharField` |  |  |  |  |  |
| `spec_evidence_content_hash` | `CharField` |  |  |  |  |  |
| `knowledge_as_of` | `DateTimeField` |  |  |  |  |  |
| `produced_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `payload_schema` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |

### ForecastBaselineSpecModel

- 来源文件：`apps/equity/infrastructure/forecast_baseline_models.py`
- 数据表：`equity_forecast_baseline_spec`
- 说明：Canonical immutable ForecastBaselineSpec payload.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `approval` | `ForeignKey` |  |  |  |  | ForecastBaselineApprovalEvidenceModel |
| `spec_id` | `CharField` |  |  |  |  |  |
| `spec_version` | `CharField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `approval_evidence_id` | `CharField` |  |  |  |  |  |
| `approval_evidence_version` | `CharField` |  |  |  |  |  |
| `approval_evidence_content_hash` | `CharField` |  |  |  |  |  |
| `approval_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `forecast_origin_at` | `DateTimeField` |  |  |  |  |  |
| `approved_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `payload_schema` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |

### ForecastBaselineTrialResultModel

- 来源文件：`apps/equity/infrastructure/forecast_baseline_models.py`
- 数据表：`equity_forecast_baseline_trial_result`
- 说明：Canonical immutable ForecastBaselineTrialResult payload.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `spec` | `ForeignKey` |  |  |  |  | ForecastBaselineSpecModel |
| `artifact` | `ForeignKey` |  |  |  |  | ForecastBaselineArtifactModel |
| `result_id` | `CharField` |  |  |  |  |  |
| `result_version` | `CharField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `spec_evidence_id` | `CharField` |  |  |  |  |  |
| `spec_evidence_version` | `CharField` |  |  |  |  |  |
| `spec_evidence_content_hash` | `CharField` |  |  |  |  |  |
| `artifact_evidence_id` | `CharField` |  |  |  |  |  |
| `artifact_evidence_version` | `CharField` |  |  |  |  |  |
| `artifact_evidence_content_hash` | `CharField` |  |  |  |  |  |
| `actual_manifest_id` | `CharField` |  |  |  |  |  |
| `actual_manifest_version` | `CharField` |  |  |  |  |  |
| `actual_manifest_content_hash` | `CharField` |  |  |  |  |  |
| `research_trial_id` | `CharField` |  |  |  |  |  |
| `research_trial_version` | `CharField` |  |  |  |  |  |
| `research_trial_content_hash` | `CharField` |  |  |  |  |  |
| `evaluated_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `payload_schema` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |

### FinancialDataModel

- 来源文件：`apps/equity/infrastructure/models.py`
- 数据表：`equity_financial_data`
- 说明：财务数据表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `stock_code` | `CharField` |  |  |  | 股票代码 |  |
| `report_date` | `DateField` |  |  |  | 报告期 |  |
| `report_type` | `CharField` |  |  |  | 报告类型 |  |
| `revenue` | `DecimalField` |  |  |  | 营业收入 |  |
| `net_profit` | `DecimalField` |  |  |  | 净利润 |  |
| `revenue_growth` | `FloatField` | 是 |  |  | 营收增长率 |  |
| `net_profit_growth` | `FloatField` | 是 |  |  | 净利润增长率 |  |
| `total_assets` | `DecimalField` |  |  |  | 总资产 |  |
| `total_liabilities` | `DecimalField` |  |  |  | 总负债 |  |
| `equity` | `DecimalField` |  |  |  | 股东权益 |  |
| `roe` | `FloatField` |  |  |  | 净资产收益率 |  |
| `roa` | `FloatField` | 是 |  |  | 总资产收益率 |  |
| `debt_ratio` | `FloatField` |  |  |  | 资产负债率 |  |
| `publish_date` | `DateField` | 是 |  |  | 发布日期 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### ScoringWeightConfigModel

- 来源文件：`apps/equity/infrastructure/models.py`
- 数据表：`equity_scoring_weight_config`
- 说明：股票筛选评分权重配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | `CharField` |  | 是 |  | 配置名称 |  |
| `description` | `CharField` |  |  |  | 配置描述 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `growth_weight` | `FloatField` |  |  | 0.4 | 成长性评分权重 |  |
| `profitability_weight` | `FloatField` |  |  | 0.4 | 盈利能力评分权重 |  |
| `valuation_weight` | `FloatField` |  |  | 0.2 | 估值评分权重 |  |
| `revenue_growth_weight` | `FloatField` |  |  | 0.5 | 营收增长率权重 |  |
| `profit_growth_weight` | `FloatField` |  |  | 0.5 | 净利润增长率权重 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### StockDailyModel

- 来源文件：`apps/equity/infrastructure/models.py`
- 数据表：`equity_stock_daily`
- 说明：个股日线数据表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `stock_code` | `CharField` |  |  |  | 股票代码 |  |
| `trade_date` | `DateField` |  |  |  | 交易日期 |  |
| `open` | `DecimalField` |  |  |  | 开盘价 |  |
| `high` | `DecimalField` |  |  |  | 最高价 |  |
| `low` | `DecimalField` |  |  |  | 最低价 |  |
| `close` | `DecimalField` |  |  |  | 收盘价 |  |
| `volume` | `BigIntegerField` |  |  |  | 成交量（手） |  |
| `amount` | `DecimalField` |  |  |  | 成交额（元） |  |
| `turnover_rate` | `FloatField` | 是 |  |  | 换手率（%） |  |
| `adj_factor` | `FloatField` |  |  | 1.0 | 复权因子 |  |
| `ma5` | `DecimalField` | 是 |  |  | 5日均线 |  |
| `ma20` | `DecimalField` | 是 |  |  | 20日均线 |  |
| `ma60` | `DecimalField` | 是 |  |  | 60日均线 |  |
| `macd` | `FloatField` | 是 |  |  | MACD |  |
| `macd_signal` | `FloatField` | 是 |  |  | MACD 信号线 |  |
| `macd_hist` | `FloatField` | 是 |  |  | MACD 柱状图 |  |
| `rsi` | `FloatField` | 是 |  |  | RSI（14日） |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### StockInfoModel

- 来源文件：`apps/equity/infrastructure/models.py`
- 数据表：`equity_stock_info`
- 说明：个股基本信息表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `stock_code` | `CharField` |  | 是 |  | 股票代码 |  |
| `name` | `CharField` |  |  |  | 股票名称 |  |
| `sector` | `CharField` |  |  |  | 所属行业 |  |
| `market` | `CharField` |  |  |  | 交易市场 |  |
| `list_date` | `DateField` |  |  |  | 上市日期 |  |
| `is_active` | `BooleanField` |  |  | True | 是否活跃 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### StockPoolSnapshot

- 来源文件：`apps/equity/infrastructure/models.py`
- 数据表：`equity_stock_pool_snapshot`
- 说明：股票池快照表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `stock_codes` | `JSONField` |  |  | list | 股票代码列表 |  |
| `regime` | `CharField` |  |  |  | 筛选时使用的 Regime |  |
| `as_of_date` | `DateField` |  |  |  | 数据截止日期 |  |
| `is_active` | `BooleanField` |  |  | True | 是否为当前活跃池 |  |
| `count` | `IntegerField` |  |  | 0 | 股票数量 |  |
| `avg_roe` | `FloatField` | 是 |  |  | 平均 ROE |  |
| `avg_pe` | `FloatField` | 是 |  |  | 平均 PE |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### StockScreeningRuleConfigModel

- 来源文件：`apps/equity/infrastructure/models.py`
- 数据表：`config_stock_screening_rule`
- 说明：个股筛选规则配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `regime` | `CharField` |  |  |  | Recovery/Overheat/Stagflation/Deflation |  |
| `rule_name` | `CharField` |  |  |  | 规则名称 |  |
| `min_roe` | `FloatField` |  |  | 0.0 | 最低 ROE（%） |  |
| `min_revenue_growth` | `FloatField` |  |  | 0.0 | 最低营收增长率（%） |  |
| `min_profit_growth` | `FloatField` |  |  | 0.0 | 最低净利润增长率（%） |  |
| `max_debt_ratio` | `FloatField` |  |  | 100.0 | 最高资产负债率（%） |  |
| `max_pe` | `FloatField` |  |  | 999.0 | 最高 PE |  |
| `max_pb` | `FloatField` |  |  | 999.0 | 最高 PB |  |
| `min_market_cap` | `DecimalField` |  |  | 0 | 最低市值（元） |  |
| `sector_preference` | `JSONField` |  |  | list | 偏好行业列表 |  |
| `max_count` | `IntegerField` |  |  | 50 | 最多返回个股数量 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `priority` | `IntegerField` |  |  | 0 | 优先级（数字越大优先级越高） |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### ValuationDataQualitySnapshotModel

- 来源文件：`apps/equity/infrastructure/models.py`
- 数据表：`equity_valuation_quality_snapshot`
- 说明：估值数据质量快照表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `as_of_date` | `DateField` |  | 是 |  | 数据日期 |  |
| `expected_stock_count` | `IntegerField` |  |  | 0 | 预期股票数 |  |
| `synced_stock_count` | `IntegerField` |  |  | 0 | 同步股票数 |  |
| `valid_stock_count` | `IntegerField` |  |  | 0 | 有效股票数 |  |
| `coverage_ratio` | `FloatField` |  |  | 0.0 | 覆盖率 |  |
| `valid_ratio` | `FloatField` |  |  | 0.0 | 有效率 |  |
| `missing_pb_count` | `IntegerField` |  |  | 0 | PB缺失数 |  |
| `invalid_pb_count` | `IntegerField` |  |  | 0 | PB非法数 |  |
| `missing_pe_count` | `IntegerField` |  |  | 0 | PE缺失数 |  |
| `jump_alert_count` | `IntegerField` |  |  | 0 | 跳变告警数 |  |
| `source_deviation_count` | `IntegerField` |  |  | 0 | 源偏差数 |  |
| `primary_source` | `CharField` |  |  | akshare | 主数据源 |  |
| `fallback_used_count` | `IntegerField` |  |  | 0 | 备源使用数 |  |
| `is_gate_passed` | `BooleanField` |  |  | False | 是否通过门禁 |  |
| `gate_reason` | `CharField` |  |  |  | 门禁原因 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### ValuationModel

- 来源文件：`apps/equity/infrastructure/models.py`
- 数据表：`equity_valuation`
- 说明：估值指标表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `stock_code` | `CharField` |  |  |  | 股票代码 |  |
| `trade_date` | `DateField` |  |  |  | 交易日期 |  |
| `pe` | `FloatField` | 是 |  |  | 市盈率（动态） |  |
| `pe_ttm` | `FloatField` | 是 |  |  | 市盈率（TTM） |  |
| `pb` | `FloatField` | 是 |  |  | 市净率 |  |
| `ps` | `FloatField` | 是 |  |  | 市销率 |  |
| `total_mv` | `DecimalField` |  |  |  | 总市值（元） |  |
| `circ_mv` | `DecimalField` |  |  |  | 流通市值（元） |  |
| `dividend_yield` | `FloatField` | 是 |  |  | 股息率（%） |  |
| `source_provider` | `CharField` |  |  | unknown | 数据提供方 |  |
| `source_updated_at` | `DateTimeField` | 是 |  |  | 源端更新时间 |  |
| `fetched_at` | `DateTimeField` |  |  | timezone.now | 抓取时间 |  |
| `pe_type` | `CharField` |  |  | dynamic | PE口径 |  |
| `is_valid` | `BooleanField` |  |  | True | 是否有效 |  |
| `quality_flag` | `CharField` |  |  | ok | 质量标记 |  |
| `quality_notes` | `CharField` |  |  |  | 质量说明 |  |
| `raw_payload_hash` | `CharField` |  |  |  | 原始载荷哈希 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### ValuationRepairConfigModel

- 来源文件：`apps/equity/infrastructure/models.py`
- 数据表：`equity_valuation_repair_config`
- 说明：估值修复策略参数配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `version` | `IntegerField` |  |  | 1 | 版本号 |  |
| `is_active` | `BooleanField` |  |  | False | 是否激活（生效中） |  |
| `effective_from` | `DateTimeField` | 是 |  |  | 生效时间 |  |
| `min_history_points` | `IntegerField` |  |  | 120 | 最小历史样本数 |  |
| `default_lookback_days` | `IntegerField` |  |  | 756 | 默认回看交易日数 |  |
| `confirm_window` | `IntegerField` |  |  | 20 | 修复确认窗口（交易日） |  |
| `min_rebound` | `FloatField` |  |  | 0.05 | 最小反弹幅度（百分位） |  |
| `stall_window` | `IntegerField` |  |  | 40 | 停滞检测窗口（交易日） |  |
| `stall_min_progress` | `FloatField` |  |  | 0.02 | 停滞最小进展阈值 |  |
| `target_percentile` | `FloatField` |  |  | 0.5 | 目标百分位 |  |
| `undervalued_threshold` | `FloatField` |  |  | 0.2 | 低估阈值 |  |
| `near_target_threshold` | `FloatField` |  |  | 0.45 | 接近目标阈值 |  |
| `overvalued_threshold` | `FloatField` |  |  | 0.8 | 高估阈值 |  |
| `pe_weight` | `FloatField` |  |  | 0.6 | PE 权重 |  |
| `pb_weight` | `FloatField` |  |  | 0.4 | PB 权重 |  |
| `confidence_base` | `FloatField` |  |  | 0.4 | 置信度基础值 |  |
| `confidence_sample_threshold` | `IntegerField` |  |  | 252 | 置信度样本数阈值 |  |
| `confidence_sample_bonus` | `FloatField` |  |  | 0.2 | 置信度样本数奖励 |  |
| `confidence_blend_bonus` | `FloatField` |  |  | 0.15 | 置信度 pe_pb_blend 奖励 |  |
| `confidence_repair_start_bonus` | `FloatField` |  |  | 0.15 | 置信度修复起点奖励 |  |
| `confidence_not_stalled_bonus` | `FloatField` |  |  | 0.1 | 置信度非停滞奖励 |  |
| `repairing_threshold` | `FloatField` |  |  | 0.1 | REPAIRING 阶段阈值 |  |
| `eta_max_days` | `IntegerField` |  |  | 999 | ETA 最大天数 |  |
| `change_reason` | `TextField` |  |  |  | 变更原因 |  |
| `created_by` | `CharField` |  |  |  | 创建人 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### ValuationRepairTrackingModel

- 来源文件：`apps/equity/infrastructure/models.py`
- 数据表：`equity_valuation_repair_tracking`
- 说明：估值修复跟踪表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `stock_code` | `CharField` |  |  |  | 股票代码 |  |
| `stock_name` | `CharField` |  |  |  | 股票名称 |  |
| `as_of_date` | `DateField` |  |  |  | 数据截止日期 |  |
| `repair_start_date` | `DateField` | 是 |  |  | 修复开始日期 |  |
| `repair_start_percentile` | `FloatField` | 是 |  |  | 修复起始分位数 |  |
| `current_phase` | `CharField` |  |  |  | 当前修复阶段 |  |
| `signal` | `CharField` |  |  | none | 交易信号 |  |
| `composite_percentile` | `FloatField` |  |  |  | 综合分位数 |  |
| `pe_percentile` | `FloatField` | 是 |  |  | PE分位数 |  |
| `pb_percentile` | `FloatField` |  |  |  | PB分位数 |  |
| `repair_progress` | `FloatField` | 是 |  |  | 修复进度(%) |  |
| `repair_speed_per_30d` | `FloatField` | 是 |  |  | 修复速度(每30天百分点) |  |
| `estimated_days_to_target` | `IntegerField` | 是 |  |  | 预计到达目标天数 |  |
| `is_stalled` | `BooleanField` |  |  | False | 是否停滞 |  |
| `stall_start_date` | `DateField` | 是 |  |  | 停滞开始日期 |  |
| `stall_duration_trading_days` | `IntegerField` |  |  | 0 | 停滞持续交易日数 |  |
| `repair_duration_trading_days` | `IntegerField` |  |  | 0 | 修复持续交易日数 |  |
| `lowest_percentile` | `FloatField` |  |  |  | 最低分位数 |  |
| `lowest_percentile_date` | `DateField` | 是 |  |  | 最低分位数日期 |  |
| `target_percentile` | `FloatField` |  |  | 0.5 | 目标分位数 |  |
| `composite_method` | `CharField` |  |  | pb_only | 综合分位数方法 |  |
| `confidence` | `FloatField` |  |  | 0.0 | 置信度 |  |
| `source_universe` | `CharField` |  |  | all_active | 来源股票池 |  |
| `is_active` | `BooleanField` |  |  | True | 是否活跃 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### EquityForecastAppendOnlyModel

- 来源文件：`apps/equity/infrastructure/operating_forecast_models.py`
- 抽象模型：是
- 说明：Reject mutation and deletion of forecast evidence records.

### OperatingForecastAssumptionModel

- 来源文件：`apps/equity/infrastructure/operating_forecast_models.py`
- 数据表：`equity_operating_forecast_assumption`
- 说明：One typed and reconstructible input for one scenario.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `forecast` | `ForeignKey` |  |  |  |  | OperatingForecastVersionModel |
| `scenario` | `CharField` |  |  |  |  |  |
| `assumption_key` | `CharField` |  |  |  |  |  |
| `value` | `DecimalField` |  |  |  |  |  |
| `unit` | `CharField` |  |  |  |  |  |
| `input_kind` | `CharField` |  |  |  |  |  |
| `rationale` | `CharField` |  |  |  |  |  |
| `observed_fact_version_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `human_assumption_ref` | `CharField` |  |  |  |  |  |
| `model_version` | `CharField` |  |  |  |  |  |
| `legacy_observed_metric_role` | `CharField` |  |  |  |  |  |
| `observed_metric_code` | `CharField` |  |  |  |  |  |
| `observed_fact_content_hash` | `CharField` |  |  |  |  |  |
| `observed_subject_type` | `CharField` |  |  |  |  |  |
| `observed_subject_code` | `CharField` |  |  |  |  |  |
| `fact_binding_complete` | `BooleanField` |  |  | False |  |  |

### OperatingForecastEvaluationModel

- 来源文件：`apps/equity/infrastructure/operating_forecast_models.py`
- 数据表：`equity_operating_forecast_evaluation`
- 说明：Quarterly actual comparison and immutable error metrics.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `forecast` | `ForeignKey` |  |  |  |  | OperatingForecastVersionModel |
| `subject_code` | `CharField` |  |  |  |  |  |
| `scenario` | `CharField` |  |  |  |  |  |
| `actual_period_end` | `DateField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `actual_fact_evidence` | `JSONField` |  |  | list |  |  |
| `forecast_revenue` | `DecimalField` |  |  |  |  |  |
| `forecast_net_profit` | `DecimalField` |  |  |  |  |  |
| `forecast_profit_margin_percent` | `DecimalField` |  |  |  |  |  |
| `actual_revenue` | `DecimalField` |  |  |  |  |  |
| `actual_net_profit` | `DecimalField` |  |  |  |  |  |
| `actual_profit_margin_percent` | `DecimalField` |  |  |  |  |  |
| `currency_unit` | `CharField` |  |  |  |  |  |
| `revenue_error` | `DecimalField` |  |  |  |  |  |
| `revenue_absolute_error` | `DecimalField` |  |  |  |  |  |
| `revenue_absolute_percentage_error` | `DecimalField` | 是 |  |  |  |  |
| `net_profit_error` | `DecimalField` |  |  |  |  |  |
| `net_profit_absolute_error` | `DecimalField` |  |  |  |  |  |
| `net_profit_absolute_percentage_error` | `DecimalField` | 是 |  |  |  |  |
| `profit_margin_error` | `DecimalField` |  |  |  |  |  |
| `profit_margin_absolute_error` | `DecimalField` |  |  |  |  |  |
| `content_hash` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### OperatingForecastFactReferenceModel

- 来源文件：`apps/equity/infrastructure/operating_forecast_models.py`
- 数据表：`equity_operating_forecast_fact_ref`
- 说明：Captured Data Center operating PIT fact identity and payload.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `forecast` | `ForeignKey` |  |  |  |  | OperatingForecastVersionModel |
| `pit_fact_version_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `dataset` | `CharField` |  |  |  |  |  |
| `business_key` | `CharField` |  |  |  |  |  |
| `metric_code` | `CharField` |  |  |  |  |  |
| `subject_type` | `CharField` |  |  |  |  |  |
| `subject_code` | `CharField` |  |  |  |  |  |
| `effective_at` | `DateTimeField` |  |  |  |  |  |
| `available_at` | `DateTimeField` |  |  |  |  |  |
| `source_record_id` | `CharField` |  |  |  |  |  |
| `pit_content_hash` | `CharField` |  |  |  |  |  |
| `value` | `DecimalField` |  |  |  |  |  |
| `unit` | `CharField` |  |  |  |  |  |

### OperatingForecastProjectionModel

- 来源文件：`apps/equity/infrastructure/operating_forecast_models.py`
- 数据表：`equity_operating_forecast_projection`
- 说明：Revenue, profit and derived margin output for one scenario.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `forecast` | `ForeignKey` |  |  |  |  | OperatingForecastVersionModel |
| `scenario` | `CharField` |  |  |  |  |  |
| `revenue` | `DecimalField` |  |  |  |  |  |
| `net_profit` | `DecimalField` |  |  |  |  |  |
| `cash_flow` | `DecimalField` | 是 |  |  |  |  |
| `profit_margin_percent` | `DecimalField` |  |  |  |  |  |
| `currency_unit` | `CharField` |  |  |  |  |  |

### OperatingForecastSensitivityModel

- 来源文件：`apps/equity/infrastructure/operating_forecast_models.py`
- 数据表：`equity_operating_forecast_sensitivity`
- 说明：Externally calculated sensitivity point for one projection.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `projection` | `ForeignKey` |  |  |  |  | OperatingForecastProjectionModel |
| `sensitivity_key` | `CharField` |  |  |  |  |  |
| `input_value` | `DecimalField` |  |  |  |  |  |
| `input_unit` | `CharField` |  |  |  |  |  |
| `output_value` | `DecimalField` |  |  |  |  |  |
| `output_unit` | `CharField` |  |  |  |  |  |
| `method_version` | `CharField` |  |  |  |  |  |
| `source_artifact_ref` | `CharField` |  |  |  |  |  |
| `source_artifact_hash` | `CharField` |  |  |  |  |  |
| `source_binding_complete` | `BooleanField` |  |  | False |  |  |

### OperatingForecastStageValueModel

- 来源文件：`apps/equity/infrastructure/operating_forecast_models.py`
- 数据表：`equity_operating_forecast_stage_value`
- 说明：One immutable node/value for each required financial stage.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `projection` | `ForeignKey` |  |  |  |  | OperatingForecastProjectionModel |
| `stage` | `CharField` |  |  |  |  |  |
| `node_key` | `CharField` |  |  |  |  |  |
| `value` | `DecimalField` |  |  |  |  |  |
| `unit` | `CharField` |  |  |  |  |  |

### OperatingForecastVersionModel

- 来源文件：`apps/equity/infrastructure/operating_forecast_models.py`
- 数据表：`equity_operating_forecast_version`
- 说明：Immutable header for one base/bull/bear forecast version.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `forecast_id` | `CharField` |  |  |  |  |  |
| `forecast_key` | `CharField` |  |  |  |  |  |
| `forecast_version` | `PositiveIntegerField` |  |  |  |  |  |
| `subject_code` | `CharField` |  |  |  |  |  |
| `industry_code` | `CharField` |  |  |  |  |  |
| `as_of_time` | `DateTimeField` |  |  |  |  |  |
| `target_period_end` | `DateField` |  |  |  |  |  |
| `horizon_quarters` | `PositiveSmallIntegerField` |  |  |  |  |  |
| `methodology_ref` | `CharField` |  |  |  |  |  |
| `created_by_ref` | `CharField` |  |  |  |  |  |
| `evidence_schema_version` | `PositiveSmallIntegerField` |  |  | 1 |  |  |
| `source_lineage_status` | `CharField` |  |  | OperatingForecastSourceLineageStatus.LEGACY_UNBOUND.value |  |  |
| `legacy_hash_recipe` | `CharField` |  |  | OperatingForecastLegacyHashRecipe.UNVERIFIED.value |  |  |
| `legacy_hash_status` | `CharField` |  |  | OperatingForecastLegacyHashStatus.UNVERIFIED.value |  |  |
| `template_code` | `CharField` |  |  |  |  |  |
| `template_version` | `PositiveIntegerField` | 是 |  |  |  |  |
| `template_content_hash` | `CharField` |  |  |  |  |  |
| `template_run_key` | `CharField` |  |  |  |  |  |
| `template_run_version` | `PositiveIntegerField` | 是 |  |  |  |  |
| `template_run_content_hash` | `CharField` |  |  |  |  |  |
| `valuation_consumable` | `BooleanField` |  |  | False |  |  |
| `promotion_decision_id` | `CharField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |


## events

### EventReplayRunModel

- 来源文件：`apps/events/infrastructure/models.py`
- 数据表：`event_replay_run`
- 说明：Durable idempotency and business-audit record for controlled replay.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `requester` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `target_key` | `CharField` |  |  |  |  |  |
| `normalized_request` | `JSONField` |  |  | dict |  |  |
| `request_fingerprint` | `CharField` |  |  |  |  |  |
| `idempotency_key` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  | running |  |  |
| `attempted` | `PositiveIntegerField` |  |  | 0 |  |  |
| `succeeded` | `PositiveIntegerField` |  |  | 0 |  |  |
| `skipped` | `PositiveIntegerField` |  |  | 0 |  |  |
| `failed` | `PositiveIntegerField` |  |  | 0 |  |  |
| `failures` | `JSONField` |  |  | list |  |  |
| `result` | `JSONField` |  |  | dict |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `started_at` | `DateTimeField` |  |  |  |  |  |
| `finished_at` | `DateTimeField` | 是 |  |  |  |  |

### FailedEventModel

- 来源文件：`apps/events/infrastructure/models.py`
- 数据表：`failed_event`
- 说明：失败事件 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `event_id` | `CharField` |  |  |  | 事件 ID |  |
| `event_type` | `CharField` |  |  |  | 事件类型 |  |
| `payload` | `JSONField` |  |  |  | 事件负载 |  |
| `metadata` | `JSONField` |  |  | dict | 事件元数据 |  |
| `handler_id` | `CharField` |  |  |  | 处理器 ID |  |
| `error_message` | `TextField` |  |  |  | 错误信息 |  |
| `error_traceback` | `TextField` |  |  |  | 错误堆栈 |  |
| `retry_count` | `IntegerField` |  |  | 0 | 重试次数 |  |
| `max_retries` | `IntegerField` |  |  | 3 | 最大重试次数 |  |
| `next_retry_at` | `DateTimeField` | 是 |  |  | 下次重试时间 |  |
| `last_retry_at` | `DateTimeField` | 是 |  |  | 最后重试时间 |  |
| `status` | `CharField` |  |  | PENDING | 状态 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |


## factor

### FactorDefinitionModel

- 来源文件：`apps/factor/infrastructure/models.py`
- 数据表：`factor_definition`
- 说明：Factor definition table

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `code` | `CharField` |  | 是 |  | 因子代码 |  |
| `name` | `CharField` |  |  |  | 因子名称 |  |
| `category` | `CharField` |  |  |  | 因子类别 |  |
| `description` | `TextField` |  |  |  | 因子描述 |  |
| `data_source` | `CharField` |  |  |  | 数据来源 |  |
| `data_field` | `CharField` |  |  |  | 数据字段 |  |
| `direction` | `CharField` |  |  | positive | 因子方向 |  |
| `update_frequency` | `CharField` |  |  | daily | 更新频率 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `min_data_points` | `IntegerField` |  |  | 20 | 最小数据点 |  |
| `allow_missing` | `BooleanField` |  |  | False | 允许缺失 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### FactorExposureModel

- 来源文件：`apps/factor/infrastructure/models.py`
- 数据表：`factor_exposure`
- 说明：Factor exposure table

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `stock_code` | `CharField` |  |  |  | 股票代码 |  |
| `trade_date` | `DateField` |  |  |  | 交易日期 |  |
| `factor_code` | `CharField` |  |  |  | 因子代码 |  |
| `factor_value` | `DecimalField` |  |  |  | 因子值 |  |
| `percentile_rank` | `DecimalField` |  |  |  | 百分位排名 |  |
| `z_score` | `DecimalField` |  |  |  | Z得分 |  |
| `normalized_score` | `DecimalField` |  |  | 0.0 | 标准化得分 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### FactorPerformanceModel

- 来源文件：`apps/factor/infrastructure/models.py`
- 数据表：`factor_performance`
- 说明：Factor performance tracking table

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `factor_code` | `CharField` |  |  |  | 因子代码 |  |
| `period_start` | `DateField` |  |  |  | 期间开始 |  |
| `period_end` | `DateField` |  |  |  | 期间结束 |  |
| `total_return` | `FloatField` |  |  |  | 总收益率 |  |
| `annual_return` | `FloatField` |  |  |  | 年化收益率 |  |
| `sharpe_ratio` | `FloatField` |  |  |  | 夏普比率 |  |
| `max_drawdown` | `FloatField` |  |  |  | 最大回撤 |  |
| `win_rate` | `FloatField` |  |  |  | 胜率 |  |
| `avg_rank` | `FloatField` |  |  |  | 平均排名 |  |
| `turnover_rate` | `FloatField` |  |  | 0.0 | 换手率 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### FactorPortfolioConfigModel

- 来源文件：`apps/factor/infrastructure/models.py`
- 数据表：`factor_portfolio_config`
- 说明：Factor portfolio configuration table

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | `CharField` |  | 是 |  | 配置名称 |  |
| `description` | `TextField` |  |  |  | 配置描述 |  |
| `factor_weights` | `JSONField` |  |  | dict | 因子权重 |  |
| `universe` | `CharField` |  |  | all_a | 股票池 |  |
| `min_market_cap` | `DecimalField` | 是 |  |  | 最小市值（亿） |  |
| `max_market_cap` | `DecimalField` | 是 |  |  | 最大市值（亿） |  |
| `max_pe` | `DecimalField` | 是 |  |  | 最大PE |  |
| `min_pe` | `DecimalField` | 是 |  |  | 最小PE |  |
| `max_pb` | `DecimalField` | 是 |  |  | 最大PB |  |
| `max_debt_ratio` | `FloatField` | 是 |  |  | 最大资产负债率（%） |  |
| `top_n` | `IntegerField` |  |  | 30 | 选股数量 |  |
| `rebalance_frequency` | `CharField` |  |  | monthly | 调仓频率 |  |
| `weight_method` | `CharField` |  |  | equal_weight | 权重方式 |  |
| `max_sector_weight` | `FloatField` |  |  | 0.4 | 最大行业权重 |  |
| `max_single_stock_weight` | `FloatField` |  |  | 0.05 | 最大单股权重 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### FactorPortfolioHoldingModel

- 来源文件：`apps/factor/infrastructure/models.py`
- 数据表：`factor_portfolio_holdings`
- 说明：Factor portfolio holdings table

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `config` | `ForeignKey` |  |  |  | 配置 | FactorPortfolioConfigModel |
| `trade_date` | `DateField` |  |  |  | 交易日期 |  |
| `stock_code` | `CharField` |  |  |  | 股票代码 |  |
| `stock_name` | `CharField` |  |  |  | 股票名称 |  |
| `weight` | `DecimalField` |  |  |  | 权重 |  |
| `factor_score` | `DecimalField` |  |  |  | 因子得分 |  |
| `rank` | `IntegerField` |  |  |  | 排名 |  |
| `sector` | `CharField` |  |  |  | 行业 |  |
| `factor_scores` | `JSONField` |  |  | dict | 因子得分明细 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |


## filter

### FilterConfig

- 来源文件：`apps/filter/infrastructure/models.py`
- 数据表：`filter_config`
- 说明：滤波器配置模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `id` | `BigAutoField` |  |  |  |  |  |
| `indicator_code` | `CharField` |  | 是 |  | 指标代码 |  |
| `hp_enabled` | `BooleanField` |  |  | True | 是否启用 HP 滤波 |  |
| `hp_lambda` | `DecimalField` |  |  | Decimal('129600') | HP 滤波 lambda 参数 |  |
| `kalman_enabled` | `BooleanField` |  |  | True | 是否启用 Kalman 滤波 |  |
| `kalman_level_variance` | `DecimalField` |  |  | Decimal('0.05') | Kalman 水平方差 |  |
| `kalman_slope_variance` | `DecimalField` |  |  | Decimal('0.005') | Kalman 斜率方差 |  |
| `kalman_observation_variance` | `DecimalField` |  |  | Decimal('0.5') | Kalman 观测方差 |  |
| `description` | `TextField` |  |  |  | 描述 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### FilterParameterConfigModel

- 来源文件：`apps/filter/infrastructure/models.py`
- 数据表：`filter_parameter_config`
- 说明：滤波参数配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `key` | `CharField` |  | 是 |  | 如 hp_monthly, kalman_macro 等 |  |
| `name` | `CharField` |  |  |  | 参数名称 |  |
| `filter_type` | `CharField` |  |  |  | 滤波类型 |  |
| `parameters` | `JSONField` |  |  |  | 如 {'lambda': 129600} 或 {'level_variance': 0.05} |  |
| `data_frequency` | `CharField` |  |  |  | D/W/M/Q/Y，留空表示不限 |  |
| `indicator_category` | `CharField` |  |  |  | growth/inflation/等 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `description` | `TextField` |  |  |  | 描述 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### FilterResultModel

- 来源文件：`apps/filter/infrastructure/models.py`
- 数据表：`filter_result`
- 说明：滤波结果 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `id` | `BigAutoField` |  |  |  |  |  |
| `indicator_code` | `CharField` |  |  |  | 指标代码 (e.g., PMI, CPI) |  |
| `date` | `DateField` |  |  |  | 数据日期 |  |
| `filter_type` | `CharField` |  |  |  | 滤波器类型 |  |
| `params` | `JSONField` |  |  | dict | 滤波参数 |  |
| `original_value` | `DecimalField` |  |  |  | 原始值 |  |
| `filtered_value` | `DecimalField` |  |  |  | 滤波后值（趋势） |  |
| `cycle_value` | `DecimalField` | 是 |  |  | 周期分量（原始-趋势） |  |
| `trend_slope` | `DecimalField` | 是 |  |  | 趋势斜率（仅 Kalman） |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### KalmanStateModel

- 来源文件：`apps/filter/infrastructure/models.py`
- 数据表：`kalman_filter_state`
- 说明：Kalman 滤波器状态持久化模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `id` | `BigAutoField` |  |  |  |  |  |
| `indicator_code` | `CharField` |  | 是 |  | 指标代码 |  |
| `level` | `DecimalField` |  |  |  | 水平值 |  |
| `slope` | `DecimalField` |  |  |  | 斜率值 |  |
| `level_variance` | `DecimalField` |  |  |  | 水平方差 |  |
| `slope_variance` | `DecimalField` |  |  |  | 斜率方差 |  |
| `level_slope_cov` | `DecimalField` |  |  |  | 水平-斜率协方差 |  |
| `params` | `JSONField` |  |  | dict | 使用的滤波参数 |  |
| `last_observed_date` | `DateField` |  |  |  | 最后观测日期 |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |


## fixed_income

### FixedIncomeResearchResultModel

- 来源文件：`apps/fixed_income/infrastructure/models.py`
- 数据表：`fixed_income_research_result`
- 说明：Append-only, non-executable result from one version-bound R5 calculation.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `result_id` | `CharField` |  |  |  |  |  |
| `bond_id` | `CharField` |  |  |  |  |  |
| `valuation_at` | `DateTimeField` |  |  |  |  |  |
| `settlement_date` | `DateField` |  |  |  |  |  |
| `method_version` | `CharField` |  |  |  |  |  |
| `input_hash` | `CharField` |  |  |  |  |  |
| `output_hash` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `payload` | `JSONField` |  |  |  |  |  |
| `publication_ids` | `JSONField` |  |  |  |  |  |
| `publication_evidence` | `JSONField` |  |  |  |  |  |
| `blocked_reasons` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### FixedIncomeR5InputReceiptModel

- 来源文件：`apps/fixed_income/infrastructure/relative_value_models.py`
- 数据表：`fixed_income_r5_input_receipt`
- 说明：Complete Phase-A input/policy graph and server knowledge receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  | fixed_income |  |  |
| `command_hash` | `CharField` |  |  |  |  |  |
| `assessment_id` | `CharField` |  | 是 |  |  |  |
| `input_set_id` | `CharField` |  |  |  |  |  |
| `input_set_version` | `CharField` |  |  |  |  |  |
| `input_set_hash` | `CharField` |  |  |  |  |  |
| `policy_set_id` | `CharField` |  |  |  |  |  |
| `policy_set_version` | `CharField` |  |  |  |  |  |
| `policy_set_hash` | `CharField` |  |  |  |  |  |
| `evaluated_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `evidence_clock_graph_hash` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### FixedIncomeR5ResultModel

- 来源文件：`apps/fixed_income/infrastructure/relative_value_models.py`
- 数据表：`fixed_income_r5_result`
- 说明：Complete four-child composite linked to one protected input receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `result_id` | `CharField` |  |  |  |  |  |
| `result_version` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  | fixed_income |  |  |
| `command_hash` | `CharField` |  |  |  |  |  |
| `receipt` | `ForeignKey` |  |  |  |  | FixedIncomeR5InputReceiptModel |
| `assessment_id` | `CharField` |  | 是 |  |  |  |
| `input_set_hash` | `CharField` |  |  |  |  |  |
| `policy_set_hash` | `CharField` |  |  |  |  |  |
| `input_hash` | `CharField` |  |  |  |  |  |
| `output_hash` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `evaluated_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `evidence_clock_graph_hash` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R5RelativeValueAppendOnlyModel

- 来源文件：`apps/fixed_income/infrastructure/relative_value_models.py`
- 抽象模型：是
- 说明：Permit only a claimed database-assigned-primary-key insert.


## fund

### FundHoldingModel

- 来源文件：`apps/fund/infrastructure/models.py`
- 数据表：`fund_holding`
- 说明：基金持仓表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `fund_code` | `CharField` |  |  |  | 基金代码 |  |
| `report_date` | `DateField` |  |  |  | 报告期 |  |
| `stock_code` | `CharField` |  |  |  | 股票代码 |  |
| `stock_name` | `CharField` |  |  |  | 股票名称 |  |
| `holding_amount` | `BigIntegerField` | 是 |  |  | 持有数量（股） |  |
| `holding_value` | `DecimalField` | 是 |  |  | 持有市值（元） |  |
| `holding_ratio` | `FloatField` | 是 |  |  | 占净值比例（%） |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### FundInfoModel

- 来源文件：`apps/fund/infrastructure/models.py`
- 数据表：`fund_info`
- 说明：基金基本信息表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `fund_code` | `CharField` |  | 是 |  | 基金代码 |  |
| `fund_name` | `CharField` |  |  |  | 基金名称 |  |
| `fund_type` | `CharField` |  |  |  | 股票型/债券型/混合型/指数型/货币型/QDII/商品型 |  |
| `investment_style` | `CharField` | 是 |  |  | 成长/价值/平衡/商品/稳健 |  |
| `setup_date` | `DateField` | 是 |  |  | 成立日期 |  |
| `management_company` | `CharField` | 是 |  |  | 管理人 |  |
| `custodian` | `CharField` | 是 |  |  | 托管人 |  |
| `fund_scale` | `DecimalField` | 是 |  |  | 基金规模（元） |  |
| `is_active` | `BooleanField` |  |  | True | 是否活跃 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### FundManagerModel

- 来源文件：`apps/fund/infrastructure/models.py`
- 数据表：`fund_manager`
- 说明：基金经理表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `fund_code` | `CharField` |  |  |  | 基金代码 |  |
| `manager_name` | `CharField` |  |  |  | 经理姓名 |  |
| `tenure_start` | `DateField` |  |  |  | 任职开始日期 |  |
| `tenure_end` | `DateField` | 是 |  |  | 任职结束日期 |  |
| `total_tenure_days` | `IntegerField` | 是 |  |  | 任期天数 |  |
| `fund_return` | `FloatField` | 是 |  |  | 任期期间基金收益率（%） |  |
| `is_current` | `BooleanField` |  |  | True | 是否在任 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### FundNetValueModel

- 来源文件：`apps/fund/infrastructure/models.py`
- 数据表：`fund_net_value`
- 说明：基金净值数据表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `fund_code` | `CharField` |  |  |  | 基金代码 |  |
| `nav_date` | `DateField` |  |  |  | 净值日期 |  |
| `unit_nav` | `DecimalField` |  |  |  | 单位净值 |  |
| `accum_nav` | `DecimalField` |  |  |  | 累计净值 |  |
| `daily_return` | `FloatField` | 是 |  |  | 日收益率（%） |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### FundPerformanceModel

- 来源文件：`apps/fund/infrastructure/models.py`
- 数据表：`fund_performance`
- 说明：基金业绩指标表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `fund_code` | `CharField` |  |  |  | 基金代码 |  |
| `start_date` | `DateField` |  |  |  | 计算起始日期 |  |
| `end_date` | `DateField` |  |  |  | 计算结束日期 |  |
| `total_return` | `FloatField` |  |  |  | 区间收益率（%） |  |
| `annualized_return` | `FloatField` | 是 |  |  | 年化收益率（%） |  |
| `volatility` | `FloatField` | 是 |  |  | 波动率（%） |  |
| `max_drawdown` | `FloatField` | 是 |  |  | 最大回撤（%） |  |
| `sharpe_ratio` | `FloatField` | 是 |  |  | 夏普比率 |  |
| `beta` | `FloatField` | 是 |  |  | 贝塔系数 |  |
| `alpha` | `FloatField` | 是 |  |  | 阿尔法（%） |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### FundSectorAllocationModel

- 来源文件：`apps/fund/infrastructure/models.py`
- 数据表：`fund_sector_allocation`
- 说明：基金行业配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `fund_code` | `CharField` |  |  |  | 基金代码 |  |
| `report_date` | `DateField` |  |  |  | 报告期 |  |
| `sector_name` | `CharField` |  |  |  | 行业名称 |  |
| `allocation_ratio` | `FloatField` |  |  |  | 配置比例（%） |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### FundTypePreferenceConfigModel

- 来源文件：`apps/fund/infrastructure/models.py`
- 数据表：`config_fund_type_preference`
- 说明：基金类型偏好配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `regime` | `CharField` |  |  |  | Recovery/Overheat/Stagflation/Deflation |  |
| `fund_type` | `CharField` |  |  |  | 基金类型 |  |
| `style` | `CharField` |  |  |  | 如：成长、价值、平衡、商品等 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `priority` | `IntegerField` |  |  | 0 | 优先级 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### ValidatedFundModel

- 来源文件：`apps/fund/infrastructure/models.py`
- 抽象模型：是
- 说明：Run model and database-constraint validation on every ORM save path.


## hedge

### CorrelationHistoryModel

- 来源文件：`apps/hedge/infrastructure/models.py`
- 数据表：`hedge_correlation_history`
- 说明：Correlation history table

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `asset1` | `CharField` |  |  |  | 资产1 |  |
| `asset2` | `CharField` |  |  |  | 资产2 |  |
| `calc_date` | `DateField` |  |  |  | 计算日期 |  |
| `window_days` | `IntegerField` |  |  |  | 窗口天数 |  |
| `correlation` | `FloatField` |  |  |  | 相关系数 |  |
| `covariance` | `FloatField` |  |  | 0.0 | 协方差 |  |
| `beta` | `FloatField` |  |  | 0.0 | Beta |  |
| `p_value` | `FloatField` |  |  | 0.0 | P值 |  |
| `standard_error` | `FloatField` |  |  | 0.0 | 标准误差 |  |
| `correlation_trend` | `CharField` |  |  | neutral | 相关性趋势 |  |
| `correlation_ma` | `FloatField` |  |  | 0.0 | 相关性均线 |  |
| `alert` | `TextField` |  |  |  | 告警信息 |  |
| `alert_type` | `CharField` |  |  |  | 告警类型 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### HedgeAlertModel

- 来源文件：`apps/hedge/infrastructure/models.py`
- 数据表：`hedge_alert`
- 说明：Hedge alert table

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `pair_name` | `CharField` |  |  |  | 对冲对名称 |  |
| `alert_date` | `DateField` |  |  |  | 告警日期 |  |
| `alert_type` | `CharField` |  |  |  | 告警类型 |  |
| `severity` | `CharField` |  |  | medium | 严重程度 |  |
| `message` | `TextField` |  |  |  | 告警信息 |  |
| `current_value` | `FloatField` |  |  | 0.0 | 当前值 |  |
| `threshold_value` | `FloatField` |  |  | 0.0 | 阈值 |  |
| `action_required` | `TextField` |  |  |  | 建议操作 |  |
| `action_priority` | `IntegerField` |  |  | 5 | 优先级 |  |
| `is_resolved` | `BooleanField` |  |  | False | 已解决 |  |
| `resolved_at` | `DateTimeField` | 是 |  |  | 解决时间 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### HedgePairModel

- 来源文件：`apps/hedge/infrastructure/models.py`
- 数据表：`hedge_pair`
- 说明：Hedge pair configuration table

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | `CharField` |  | 是 |  | 对冲对名称 |  |
| `long_asset` | `CharField` |  |  |  | 多头资产 |  |
| `hedge_asset` | `CharField` |  |  |  | 对冲资产 |  |
| `hedge_method` | `CharField` |  |  | beta | 对冲方法 |  |
| `target_long_weight` | `FloatField` |  |  | 0.7 | 目标多头权重 |  |
| `target_hedge_weight` | `FloatField` |  |  | 0.3 | 目标对冲权重 |  |
| `rebalance_trigger` | `FloatField` |  |  | 0.05 | 调仓触发阈值 |  |
| `correlation_window` | `IntegerField` |  |  | 60 | 相关性计算窗口（天） |  |
| `min_correlation` | `FloatField` |  |  | -0.3 | 最小相关性 |  |
| `max_correlation` | `FloatField` |  |  | -0.9 | 最大相关性 |  |
| `correlation_alert_threshold` | `FloatField` |  |  | 0.2 | 相关性告警阈值 |  |
| `max_hedge_cost` | `FloatField` |  |  | 0.05 | 最大对冲成本 |  |
| `beta_target` | `FloatField` | 是 |  |  | 目标Beta |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### HedgePerformanceModel

- 来源文件：`apps/hedge/infrastructure/models.py`
- 数据表：`hedge_performance`
- 说明：Hedge performance tracking table

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `pair_name` | `CharField` |  |  |  | 对冲对名称 |  |
| `period_start` | `DateField` |  |  |  | 期间开始 |  |
| `period_end` | `DateField` |  |  |  | 期间结束 |  |
| `total_return` | `FloatField` |  |  |  | 总收益率 |  |
| `annual_return` | `FloatField` |  |  |  | 年化收益率 |  |
| `sharpe_ratio` | `FloatField` |  |  |  | 夏普比率 |  |
| `volatility_reduction` | `FloatField` |  |  |  | 波动率降低（%） |  |
| `drawdown_reduction` | `FloatField` |  |  |  | 回撤降低（%） |  |
| `hedge_effectiveness` | `FloatField` |  |  |  | 对冲有效性 |  |
| `hedge_cost` | `FloatField` |  |  | 0.0 | 对冲成本 |  |
| `cost_benefit_ratio` | `FloatField` |  |  | 0.0 | 成本收益比 |  |
| `avg_correlation` | `FloatField` |  |  |  | 平均相关性 |  |
| `correlation_stability` | `FloatField` |  |  | 0.0 | 相关性稳定性 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### HedgePortfolioSnapshotModel

- 来源文件：`apps/hedge/infrastructure/models.py`
- 数据表：`hedge_portfolio_snapshots`
- 说明：Hedge portfolio snapshot table

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `pair` | `ForeignKey` |  |  |  | 对冲对 | HedgePairModel |
| `trade_date` | `DateField` |  |  |  | 交易日期 |  |
| `long_weight` | `FloatField` |  |  |  | 多头权重 |  |
| `hedge_weight` | `FloatField` |  |  |  | 对冲权重 |  |
| `hedge_ratio` | `FloatField` |  |  |  | 对冲比例 |  |
| `target_hedge_ratio` | `FloatField` |  |  | 0.0 | 目标对冲比例 |  |
| `current_correlation` | `FloatField` |  |  |  | 当前相关性 |  |
| `correlation_20d` | `FloatField` |  |  | 0.0 | 20日相关性 |  |
| `correlation_60d` | `FloatField` |  |  | 0.0 | 60日相关性 |  |
| `portfolio_beta` | `FloatField` |  |  | 0.0 | 组合Beta |  |
| `portfolio_volatility` | `FloatField` |  |  | 0.0 | 组合波动率 |  |
| `hedge_effectiveness` | `FloatField` |  |  | 0.0 | 对冲有效性 |  |
| `daily_return` | `FloatField` |  |  | 0.0 | 日收益率 |  |
| `unhedged_return` | `FloatField` |  |  | 0.0 | 未对冲收益 |  |
| `hedge_return` | `FloatField` |  |  | 0.0 | 对冲部位收益 |  |
| `value_at_risk` | `FloatField` |  |  | 0.0 | VaR |  |
| `max_drawdown` | `FloatField` |  |  | 0.0 | 最大回撤 |  |
| `rebalance_needed` | `BooleanField` |  |  | False | 需要调仓 |  |
| `rebalance_reason` | `TextField` |  |  |  | 调仓原因 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### HedgingInstrumentConfigModel

- 来源文件：`apps/hedge/infrastructure/models.py`
- 数据表：`hedging_instrument_config`
- 说明：对冲工具配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `instrument_code` | `CharField` |  | 是 |  | 工具代码 |  |
| `instrument_name` | `CharField` |  |  |  | 工具名称 |  |
| `instrument_type` | `CharField` |  |  |  | 工具类型 |  |
| `hedge_ratio` | `FloatField` |  |  | 1.0 | 如 0.95 表示需要对冲95%的敞口 |  |
| `underlying_index` | `CharField` |  |  |  | 如 000300.SH 表示沪深300 |  |
| `cost_bps` | `FloatField` |  |  | 5.0 | 如 5 表示 0.05% |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `notes` | `TextField` |  |  |  | 备注 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |


## macro

### ExchangeRateModel

- 来源文件：`apps/macro/infrastructure/models.py`
- 数据表：`macro_exchange_rate`
- 说明：汇率记录表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `from_currency` | `CharField` |  |  |  | 源货币 |  |
| `to_currency` | `CharField` |  |  |  | 目标货币 |  |
| `rate` | `DecimalField` |  |  |  | 汇率 |  |
| `effective_date` | `DateField` |  |  |  | 生效日期 |  |
| `source` | `CharField` |  |  | akshare | 数据来源 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### IndicatorConfigModel

- 来源文件：`apps/macro/infrastructure/models.py`
- 数据表：`indicator_config`
- 说明：宏观指标配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `code` | `CharField` |  | 是 |  | 指标代码 |  |
| `name` | `CharField` |  |  |  | 指标名称 |  |
| `name_en` | `CharField` |  |  |  | 英文名称 |  |
| `category` | `CharField` |  |  |  | 指标分类 |  |
| `unit` | `CharField` |  |  |  | 单位 |  |
| `threshold_bullish` | `FloatField` | 是 |  |  | 看涨阈值 |  |
| `threshold_bearish` | `FloatField` | 是 |  |  | 看跌阈值 |  |
| `data_source` | `CharField` |  |  | akshare | 数据源 |  |
| `fetch_frequency` | `CharField` |  |  | M | D=日, W=周, M=月, Q=季, Y=年 |  |
| `publication_lag_days` | `IntegerField` |  |  | 0 | 发布延迟天数 |  |
| `description` | `TextField` |  |  |  | 描述 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### MacroIndicator

- 来源文件：`apps/macro/infrastructure/models.py`
- 数据表：`macro_indicator`
- 说明：宏观指标 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `code` | `CharField` |  |  |  | 指标代码 |  |
| `value` | `FloatField` |  |  |  | 指标值 |  |
| `unit` | `CharField` |  |  |  | 存储单位（货币类统一为元） |  |
| `original_unit` | `CharField` |  |  |  | 原始单位（数据源返回的单位，用于展示） |  |
| `reporting_period` | `DateField` |  |  |  | 报告期（时点数据=观测日，期间数据=期末日） |  |
| `period_type` | `CharField` |  |  | D | 期间类型（D=日,W=周,M=月,Q=季,H=半,Y=年,3M=3月期,10Y=10年期等） |  |
| `published_at` | `DateField` | 是 |  |  | 实际发布时间 |  |
| `publication_lag_days` | `IntegerField` |  |  | 0 | 发布延迟天数 |  |
| `source` | `CharField` |  |  |  | 数据源 |  |
| `revision_number` | `IntegerField` |  |  | 1 | 修订版本号 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |


## macro_factor

### MacroFactorResearchResultModel

- 来源文件：`apps/macro_factor/infrastructure/models.py`
- 数据表：`macro_factor_research_result`
- 说明：Immutable external result that can never authorize a decision.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `result_id` | `CharField` |  |  |  |  |  |
| `factor_version` | `CharField` |  | 是 |  |  |  |
| `target_code` | `CharField` |  |  |  |  |  |
| `evidence_produced_at` | `DateTimeField` |  |  |  |  |  |
| `pit_manifest_id` | `CharField` |  |  |  |  |  |
| `pit_manifest_hash` | `CharField` |  |  |  |  |  |
| `code_version` | `CharField` |  |  |  |  |  |
| `parameter_version` | `CharField` |  |  |  |  |  |
| `external_evidence_id` | `CharField` |  |  |  |  |  |
| `lifecycle_status` | `CharField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### MacroFactorDatedOutputModel

- 来源文件：`apps/macro_factor/infrastructure/run_ledger_models.py`
- 数据表：`macro_factor_dated_output`
- 说明：One immutable current-state or forward-expectation research output.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `output_id` | `CharField` |  |  |  |  |  |
| `artifact` | `ForeignKey` |  |  |  |  | MacroFactorRunArtifactModel |
| `artifact_hash` | `CharField` |  |  |  |  |  |
| `factor_version` | `CharField` |  |  |  |  |  |
| `target_code` | `CharField` |  |  |  |  |  |
| `output_role` | `CharField` |  |  |  |  |  |
| `observation_date` | `DateField` |  |  |  |  |  |
| `target_period_start` | `DateField` |  |  |  |  |  |
| `target_period_end` | `DateField` |  |  |  |  |  |
| `horizon_periods` | `PositiveIntegerField` |  |  |  |  |  |
| `horizon_unit` | `CharField` |  |  |  |  |  |
| `knowledge_as_of` | `DateTimeField` |  |  |  |  |  |
| `produced_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `value` | `DecimalField` |  |  |  |  |  |
| `unit` | `CharField` |  |  |  |  |  |
| `pit_manifest_id` | `CharField` |  |  |  |  |  |
| `pit_manifest_hash` | `CharField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### MacroFactorLifecycleEventModel

- 来源文件：`apps/macro_factor/infrastructure/run_ledger_models.py`
- 数据表：`macro_factor_lifecycle_event`
- 说明：Immutable root or retirement link in one artifact lifecycle chain.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `event_id` | `CharField` |  |  |  |  |  |
| `artifact` | `ForeignKey` |  |  |  |  | MacroFactorRunArtifactModel |
| `artifact_hash` | `CharField` |  |  |  |  |  |
| `factor_version` | `CharField` |  |  |  |  |  |
| `event_type` | `CharField` |  |  |  |  |  |
| `sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_hash` | `CharField` |  |  |  |  |  |
| `reason_codes` | `JSONField` |  |  |  |  |  |
| `evidence_hash` | `CharField` |  |  |  |  |  |
| `previous_event_hash` | `CharField` | 是 |  |  |  |  |
| `owner_attestation_id` | `CharField` | 是 |  |  |  |  |
| `owner_attestation_hash` | `CharField` | 是 |  |  |  |  |
| `owner_attestation_owner_ref` | `CharField` | 是 |  |  |  |  |
| `owner_attestation_media_type` | `CharField` | 是 |  |  |  |  |
| `owner_attestation_content_length` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `owner_attestation_issued_at` | `DateTimeField` | 是 |  |  |  |  |
| `owner_attestation_bytes` | `BinaryField` | 是 |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### MacroFactorLifecycleStreamCommitModel

- 来源文件：`apps/macro_factor/infrastructure/run_ledger_models.py`
- 数据表：`macro_factor_lifecycle_stream_commit`
- 说明：Immutable cumulative anchor paired one-to-one with a lifecycle event.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `commit_id` | `CharField` |  |  |  |  |  |
| `artifact` | `ForeignKey` |  |  |  |  | MacroFactorRunArtifactModel |
| `event` | `OneToOneField` |  |  |  |  | MacroFactorLifecycleEventModel |
| `artifact_hash` | `CharField` |  |  |  |  |  |
| `event_hash` | `CharField` |  |  |  |  |  |
| `sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `event_count` | `PositiveIntegerField` |  |  |  |  |  |
| `head_event_hash` | `CharField` |  |  |  |  |  |
| `previous_commit_hash` | `CharField` | 是 |  |  |  |  |
| `stream_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### MacroFactorLifecycleStreamHeadModel

- 来源文件：`apps/macro_factor/infrastructure/run_ledger_models.py`
- 数据表：`macro_factor_lifecycle_stream_head`
- 说明：Repository-owned latest head that cannot silently regress with an append tail.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `artifact` | `OneToOneField` |  |  |  |  | MacroFactorRunArtifactModel |
| `artifact_hash` | `CharField` |  |  |  |  |  |
| `latest_sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `event_count` | `PositiveIntegerField` |  |  |  |  |  |
| `latest_event_hash` | `CharField` |  |  |  |  |  |
| `latest_commit_hash` | `CharField` |  |  |  |  |  |
| `stream_hash` | `CharField` |  |  |  |  |  |
| `content_hash` | `CharField` |  |  |  |  |  |
| `payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### MacroFactorRunArtifactModel

- 来源文件：`apps/macro_factor/infrastructure/run_ledger_models.py`
- 数据表：`macro_factor_run_artifact`
- 说明：Complete local manifest for one canonical external nested-CV run.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `artifact_id` | `CharField` |  |  |  |  |  |
| `run_key` | `CharField` |  |  |  |  |  |
| `run_version` | `PositiveIntegerField` |  |  |  |  |  |
| `factor_version` | `CharField` |  |  |  |  |  |
| `target_code` | `CharField` |  |  |  |  |  |
| `output_role` | `CharField` |  |  |  |  |  |
| `produced_at` | `DateTimeField` |  |  |  |  |  |
| `source_result` | `ForeignKey` |  |  |  |  | MacroFactorResearchResultModel |
| `source_result_hash` | `CharField` |  |  |  |  |  |
| `external_evidence_id` | `CharField` |  |  |  |  |  |
| `external_producer_ref` | `CharField` |  |  |  |  |  |
| `external_artifact_hash` | `CharField` |  |  |  |  |  |
| `external_artifact_media_type` | `CharField` |  |  |  |  |  |
| `external_artifact_content_length` | `PositiveBigIntegerField` |  |  |  |  |  |
| `external_artifact_bytes` | `BinaryField` |  |  |  |  |  |
| `request_hash` | `CharField` |  | 是 |  |  |  |
| `pit_manifest_id` | `CharField` |  |  |  |  |  |
| `pit_manifest_hash` | `CharField` |  |  |  |  |  |
| `dataset_hash` | `CharField` |  |  |  |  |  |
| `benchmark_version` | `CharField` |  |  |  |  |  |
| `benchmark_hash` | `CharField` |  |  |  |  |  |
| `fixed_fmp_version` | `CharField` |  |  |  |  |  |
| `fixed_fmp_hash` | `CharField` |  |  |  |  |  |
| `cost_model_version` | `CharField` |  |  |  |  |  |
| `cost_model_hash` | `CharField` |  |  |  |  |  |
| `split_contract_version` | `CharField` |  |  |  |  |  |
| `split_contract_hash` | `CharField` |  |  |  |  |  |
| `plan_hash` | `CharField` |  |  |  |  |  |
| `selection_protocol_version` | `CharField` |  |  |  |  |  |
| `selection_protocol_hash` | `CharField` |  |  |  |  |  |
| `metrics_protocol_version` | `CharField` |  |  |  |  |  |
| `metrics_protocol_hash` | `CharField` |  |  |  |  |  |
| `timing_policy_version` | `CharField` |  |  |  |  |  |
| `timing_policy_hash` | `CharField` |  |  |  |  |  |
| `code_version` | `CharField` |  |  |  |  |  |
| `dependency_lock_hash` | `CharField` |  |  |  |  |  |
| `parameter_version` | `CharField` |  |  |  |  |  |
| `parameter_hash` | `CharField` |  |  |  |  |  |
| `random_seed` | `PositiveBigIntegerField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |


## policy

### GateActionAuditLog

- 来源文件：`apps/policy/infrastructure/models.py`
- 数据表：`gate_action_audit_log`
- 说明：闸门操作审计日志

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `event` | `ForeignKey` |  |  |  | 关联事件 | PolicyLog |
| `action` | `CharField` |  |  |  | 操作类型 |  |
| `operator` | `ForeignKey` | 是 |  |  | 操作人 | User |
| `before_state` | `JSONField` |  |  | dict | 操作前的关键字段快照 |  |
| `after_state` | `JSONField` |  |  | dict | 操作后的关键字段快照 |  |
| `reason` | `TextField` |  |  |  | 拒绝/回滚/豁免时填写的原因 |  |
| `rule_version` | `CharField` |  |  |  | 执行时的规则版本号 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### HedgePositionModel

- 来源文件：`apps/policy/infrastructure/models.py`
- 数据表：`hedge_position`
- 说明：对冲持仓记录表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `portfolio` | `ForeignKey` |  |  |  | 投资组合 | account.PortfolioModel |
| `instrument_code` | `CharField` |  |  |  | 对冲工具代码 |  |
| `instrument_type` | `CharField` |  |  |  | 工具类型 |  |
| `hedge_ratio` | `FloatField` |  |  |  | 对冲比例 |  |
| `hedge_value` | `DecimalField` |  |  |  | 对冲金额 |  |
| `policy_level` | `CharField` |  |  |  | 触发政策档位 |  |
| `execution_price` | `DecimalField` | 是 |  |  | 执行价格 |  |
| `executed_at` | `DateTimeField` | 是 |  |  | 执行时间 |  |
| `status` | `CharField` |  |  | pending | 状态 |  |
| `opening_cost` | `DecimalField` | 是 |  |  | 开仓成本 |  |
| `closing_cost` | `DecimalField` | 是 |  |  | 平仓成本 |  |
| `total_cost` | `DecimalField` | 是 |  |  | 总成本 |  |
| `beta_before` | `FloatField` | 是 |  |  | 对冲前Beta |  |
| `beta_after` | `FloatField` | 是 |  |  | 对冲后Beta |  |
| `hedge_profit` | `DecimalField` | 是 |  |  | 对冲盈亏 |  |
| `notes` | `TextField` |  |  |  | 备注 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### InAppNotification

- 来源文件：`apps/policy/infrastructure/models.py`
- 数据表：`in_app_notification`
- 说明：站内通知模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `title` | `CharField` |  |  |  | 标题 |  |
| `content` | `TextField` |  |  |  | 内容 |  |
| `channel` | `CharField` |  |  | in_app | 通知渠道 |  |
| `priority` | `CharField` |  |  | normal | 优先级 |  |
| `recipient_username` | `CharField` | 是 |  |  | 留空表示全局通知 |  |
| `is_global` | `BooleanField` |  |  | False | 是否为全局通知（所有用户可见） |  |
| `is_read` | `BooleanField` |  |  | False | 已读 |  |
| `read_at` | `DateTimeField` | 是 |  |  | 读取时间 |  |
| `metadata` | `JSONField` |  |  | dict | 额外的结构化信息 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### PolicyAuditQueue

- 来源文件：`apps/policy/infrastructure/models.py`
- 数据表：`policy_audit_queue`
- 说明：政策审核队列

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `policy_log` | `OneToOneField` |  |  |  | 关联政策日志 | PolicyLog |
| `priority` | `CharField` |  |  | normal | 优先级 |  |
| `assigned_to` | `ForeignKey` | 是 |  |  | 分配给 | User |
| `assigned_at` | `DateTimeField` | 是 |  |  | 分配时间 |  |
| `due_date` | `DateTimeField` | 是 |  |  | 期望完成时间 |  |
| `auto_rejection_reason` | `TextField` |  |  |  | 自动拒绝原因 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### PolicyIngestionConfig

- 来源文件：`apps/policy/infrastructure/models.py`
- 数据表：`policy_ingestion_config`
- 说明：政策摄入配置（单例模式）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `singleton_id` | `AutoField` |  |  |  | 单例ID |  |
| `auto_approve_enabled` | `BooleanField` |  |  | False | 是否启用高置信度事件自动生效 |  |
| `auto_approve_min_level` | `CharField` |  |  | P2 | P2 表示 P2/P3 可自动生效，P0 表示所有档位 |  |
| `auto_approve_threshold` | `FloatField` |  |  | 0.85 | AI 置信度达到此阈值才可自动生效（0.0-1.0） |  |
| `p23_sla_hours` | `IntegerField` |  |  | 2 | P2/P3 事件审核超时时间 |  |
| `normal_sla_hours` | `IntegerField` |  |  | 24 | P0/P1 事件审核超时时间 |  |
| `version` | `IntegerField` |  |  | 1 | 配置版本 |  |
| `updated_by` | `ForeignKey` | 是 |  |  | 更新人 | User |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### PolicyLevelKeywordModel

- 来源文件：`apps/policy/infrastructure/models.py`
- 数据表：`policy_level_keywords`
- 说明：政策档位关键词规则ORM

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `level` | `CharField` |  |  |  | 政策档位 |  |
| `keywords` | `JSONField` |  |  |  | JSON数组格式的关键词列表 |  |
| `weight` | `IntegerField` |  |  | 1 | 权重 |  |
| `category` | `CharField` | 是 |  |  | 留空表示适用于所有RSS源分类 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### PolicyLog

- 来源文件：`apps/policy/infrastructure/models.py`
- 数据表：`policy_log`
- 说明：政策事件日志

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `event_date` | `DateField` |  |  |  |  |  |
| `level` | `CharField` |  |  |  |  |  |
| `title` | `CharField` |  |  |  |  |  |
| `description` | `TextField` |  |  |  |  |  |
| `evidence_url` | `URLField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `info_category` | `CharField` |  |  | macro | 信息分类 |  |
| `audit_status` | `CharField` |  |  | pending_review | 审核状态 |  |
| `ai_confidence` | `FloatField` | 是 |  |  | 0.0-1.0，高于阈值自动通过 |  |
| `reviewed_by` | `ForeignKey` | 是 |  |  | 审核人 | User |
| `reviewed_at` | `DateTimeField` | 是 |  |  | 审核时间 |  |
| `review_notes` | `TextField` |  |  |  | 审核备注 |  |
| `structured_data` | `JSONField` |  |  | dict |          {             "policy_subject": "政策主体",             "policy_object": "政策客体",             "effective_date": "YYYY-MM-DD",             "expiry_date": "YYYY-MM-DD",             "conditions": ["条件1", "条件2"],             "impact_scope": "national\|regional\|sector\|specific",             "affected_sectors": ["板块1", "板块2"],             "affected_stocks": ["股票代码1", "股票代码2"],             "sentiment": "positive\|negative\|neutral",             "sentiment_score": -1.0到1.0,             "keywords": ["关键词1", "关键词2"],             "summary": "政策摘要"         }          |  |
| `rss_source` | `ForeignKey` | 是 |  |  | RSS来源 | RSSSourceConfigModel |
| `rss_item_guid` | `CharField` |  |  |  | RSS条目GUID |  |
| `risk_impact` | `CharField` |  |  | unknown | 风险影响 |  |
| `is_blacklist` | `BooleanField` |  |  | False | 标记为黑名单的政策 |  |
| `is_whitelist` | `BooleanField` |  |  | False | 标记为白名单的政策 |  |
| `processing_metadata` | `JSONField` |  |  | dict |          {             "ai_model_used": "gpt-4",             "ai_processing_time_ms": 1234,             "ai_tokens_used": 1500,             "extraction_method": "ai\|keyword"         }          |  |
| `event_type` | `CharField` |  |  | policy | 区分政策事件与热点情绪事件 |  |
| `asset_class` | `CharField` | 是 |  |  | 按资产类约束 |  |
| `asset_scope` | `JSONField` |  |  | list | JSON数组，如 ['ASSET_CODE_1', 'ASSET_CODE_2'] |  |
| `heat_score` | `FloatField` | 是 |  |  | 0-100，数值越高热度越高 |  |
| `sentiment_score` | `FloatField` | 是 |  |  | -1.0 ~ +1.0，负值悲观，正值乐观 |  |
| `gate_level` | `CharField` | 是 |  |  | 热点情绪闸门等级 L0-L3 |  |
| `gate_effective` | `BooleanField` |  |  | False | 是否已审核通过并生效 |  |
| `effective_at` | `DateTimeField` | 是 |  |  | 生效时间 |  |
| `effective_by` | `ForeignKey` | 是 |  |  | 生效操作人 | User |
| `rollback_reason` | `TextField` |  |  |  | 回滚生效时填写的原因 |  |

### RSSFetchLog

- 来源文件：`apps/policy/infrastructure/models.py`
- 数据表：`rss_fetch_log`
- 说明：RSS抓取日志

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `source` | `ForeignKey` |  |  |  | RSS源 | RSSSourceConfigModel |
| `fetched_at` | `DateTimeField` |  |  |  | 抓取时间 |  |
| `status` | `CharField` |  |  |  | 状态 |  |
| `items_count` | `IntegerField` |  |  | 0 | 条目总数 |  |
| `new_items_count` | `IntegerField` |  |  | 0 | 新增条目数 |  |
| `error_message` | `TextField` |  |  |  | 错误信息 |  |
| `fetch_duration_seconds` | `FloatField` | 是 |  |  | 耗时(秒) |  |

### RSSHubGlobalConfig

- 来源文件：`apps/policy/infrastructure/models.py`
- 数据表：`rsshub_global_config`
- 说明：RSSHub 全局配置模型（单例模式）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `singleton_id` | `AutoField` |  |  |  | 单例ID |  |
| `base_url` | `URLField` |  |  | http://127.0.0.1:1200 | 本地 RSSHub 服务的基址，如 http://127.0.0.1:1200 |  |
| `access_key` | `CharField` |  |  |  | RSSHub 的 ACCESS_KEY，留空表示不使用鉴权 |  |
| `enabled` | `BooleanField` |  |  | False | 是否启用 RSSHub 全局配置 |  |
| `default_format` | `CharField` |  |  | rss | RSSHub 默认输出格式 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### RSSSourceConfigModel

- 来源文件：`apps/policy/infrastructure/models.py`
- 数据表：`rss_source_config`
- 说明：RSS源配置ORM

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | `CharField` |  | 是 |  | 源名称 |  |
| `url` | `URLField` |  |  |  | RSS URL |  |
| `category` | `CharField` |  |  | other | 分类 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `fetch_interval_hours` | `IntegerField` |  |  | 6 | 抓取间隔(小时) |  |
| `extract_content` | `BooleanField` |  |  | False | 是否从RSS链接中提取文章正文内容 |  |
| `proxy_enabled` | `BooleanField` |  |  | False | 启用代理 |  |
| `proxy_host` | `CharField` |  |  |  | 代理主机 |  |
| `proxy_port` | `IntegerField` | 是 |  |  | 代理端口 |  |
| `proxy_username` | `CharField` |  |  |  | 代理用户名 |  |
| `proxy_password` | `CharField` |  |  |  | 代理密码 |  |
| `proxy_type` | `CharField` |  |  | http | 代理类型 |  |
| `parser_type` | `CharField` |  |  | feedparser | 解析器类型 |  |
| `timeout_seconds` | `IntegerField` |  |  | 30 | 超时时间(秒) |  |
| `retry_times` | `IntegerField` |  |  | 3 | 重试次数 |  |
| `rsshub_enabled` | `BooleanField` |  |  | False | 是否使用 RSSHub 模式（启用后将忽略 URL 字段，使用路由路径） |  |
| `rsshub_route_path` | `CharField` |  |  |  | 如 /gov/csrc/news/c100028/common_xq_list.shtml，完整 URL 将自动构建为: 基址 + 路由 + key |  |
| `rsshub_use_global_config` | `BooleanField` |  |  | True | 是否使用全局 RSSHub 配置（基址和密钥）。取消勾选后可自定义配置。 |  |
| `rsshub_custom_base_url` | `URLField` |  |  |  | 仅在「不使用全局配置」时生效 |  |
| `rsshub_custom_access_key` | `CharField` |  |  |  | 仅在「不使用全局配置」时生效 |  |
| `rsshub_format` | `CharField` |  |  |  | 留空则使用全局配置的默认格式 |  |
| `last_fetch_at` | `DateTimeField` | 是 |  |  | 最后抓取时间 |  |
| `last_fetch_status` | `CharField` |  |  |  | 最后抓取状态 |  |
| `last_error_message` | `TextField` |  |  |  | 最后错误信息 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### SentimentGateConfig

- 来源文件：`apps/policy/infrastructure/models.py`
- 数据表：`sentiment_gate_config`
- 说明：热点情绪闸门配置（按资产类）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `asset_class` | `CharField` |  | 是 |  | 资产分类 |  |
| `heat_l1_threshold` | `FloatField` |  |  | 30.0 | 热度达到此值触发 L1 关注 |  |
| `heat_l2_threshold` | `FloatField` |  |  | 60.0 | 热度达到此值触发 L2 警戒 |  |
| `heat_l3_threshold` | `FloatField` |  |  | 85.0 | 热度达到此值触发 L3 严控 |  |
| `sentiment_l1_threshold` | `FloatField` |  |  | -0.3 | 情绪低于此值触发 L1 关注（如 -0.3） |  |
| `sentiment_l2_threshold` | `FloatField` |  |  | -0.6 | 情绪低于此值触发 L2 警戒 |  |
| `sentiment_l3_threshold` | `FloatField` |  |  | -0.8 | 情绪低于此值触发 L3 严控 |  |
| `max_position_cap_l2` | `FloatField` |  |  | 0.7 | L2 警戒时最大仓位比例（0.7 表示 70%） |  |
| `max_position_cap_l3` | `FloatField` |  |  | 0.3 | L3 严控时最大仓位比例（0.3 表示 30%） |  |
| `enabled` | `BooleanField` |  |  | True | 启用 |  |
| `version` | `IntegerField` |  |  | 1 | 配置版本 |  |
| `updated_by` | `ForeignKey` | 是 |  |  | 更新人 | User |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |


## portfolio

### _ImmutablePortfolioRecord

- 来源文件：`apps/portfolio/infrastructure/canonical_snapshot_models.py`
- 抽象模型：是
- 说明：Prevent ordinary model mutation or deletion of evidentiary records.

### GovernedOptimizationMonitoringAssessmentModel

- 来源文件：`apps/portfolio/infrastructure/governed_optimization_monitoring_models.py`
- 数据表：`portfolio_governed_optimization_monitoring_assessment`
- 说明：One immutable full monitoring owner graph and derived assessment.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `assessment_id` | `CharField` |  |  |  |  |  |
| `assessment_version` | `CharField` |  |  |  |  |  |
| `result` | `ForeignKey` |  |  |  |  | GovernedOptimizationResearchResultModel |
| `input_receipt` | `ForeignKey` |  |  |  |  | GovernedOptimizationInputReceiptModel |
| `result_hash` | `CharField` |  |  |  |  |  |
| `receipt_hash` | `CharField` |  |  |  |  |  |
| `promotion_event_id` | `CharField` |  |  |  |  |  |
| `promotion_event_hash` | `CharField` |  |  |  |  |  |
| `requested_policy_id` | `CharField` |  |  |  |  |  |
| `requested_policy_version` | `CharField` |  |  |  |  |  |
| `expected_policy_hash` | `CharField` |  |  |  |  |  |
| `calendar_id` | `CharField` |  |  |  |  |  |
| `calendar_version` | `CharField` |  |  |  |  |  |
| `calendar_hash` | `CharField` |  |  |  |  |  |
| `evaluated_at` | `DateTimeField` |  |  |  |  |  |
| `latest_owner_available_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `observation_count` | `PositiveIntegerField` |  |  |  |  |  |
| `observation_hashes` | `JSONField` |  |  |  |  |  |
| `upstream_promotions_payload` | `JSONField` |  |  |  |  |  |
| `policy_payload` | `JSONField` |  |  |  |  |  |
| `calendar_payload` | `JSONField` |  |  |  |  |  |
| `assessment_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `automatic_retirement` | `BooleanField` |  |  | False |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### GovernedOptimizationMonitoringAuditSnapshotModel

- 来源文件：`apps/portfolio/infrastructure/governed_optimization_monitoring_models.py`
- 数据表：`portfolio_governed_optimization_monitoring_audit_snapshot`
- 说明：Immutable manifest backing signed internal-audit cursors.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot_id` | `CharField` |  |  |  |  |  |
| `snapshot_version` | `CharField` |  |  |  |  |  |
| `as_of` | `DateTimeField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `entry_count` | `PositiveIntegerField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `internal_audit_only` | `BooleanField` |  |  | True |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### GovernedOptimizationMonitoringObservationModel

- 来源文件：`apps/portfolio/infrastructure/governed_optimization_monitoring_models.py`
- 数据表：`portfolio_governed_optimization_monitoring_observation`
- 说明：One immutable canonical monitoring-period observation graph.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `result` | `ForeignKey` |  |  |  |  | GovernedOptimizationResearchResultModel |
| `input_receipt` | `ForeignKey` |  |  |  |  | GovernedOptimizationInputReceiptModel |
| `assessment_id` | `CharField` |  |  |  |  |  |
| `observation_id` | `CharField` |  |  |  |  |  |
| `observation_version` | `CharField` |  |  |  |  |  |
| `result_hash` | `CharField` |  |  |  |  |  |
| `receipt_hash` | `CharField` |  |  |  |  |  |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_hash` | `CharField` |  |  |  |  |  |
| `calendar_id` | `CharField` |  |  |  |  |  |
| `calendar_version` | `CharField` |  |  |  |  |  |
| `calendar_hash` | `CharField` |  |  |  |  |  |
| `period_id` | `CharField` |  |  |  |  |  |
| `period_start_at` | `DateTimeField` |  |  |  |  |  |
| `period_end_at` | `DateTimeField` |  |  |  |  |  |
| `latest_owner_available_at` | `DateTimeField` |  |  |  |  |  |
| `portfolio_evidence_payload` | `JSONField` |  |  |  |  |  |
| `broker_evidence_payload` | `JSONField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `domain_observation_hash` | `CharField` |  |  |  |  |  |
| `content_hash` | `CharField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### GovernedOptimizationInputReceiptModel

- 来源文件：`apps/portfolio/infrastructure/optimization_research_models.py`
- 数据表：`portfolio_governed_optimization_input_receipt`
- 说明：Independent canonical receipt for all thirteen governed optimizer inputs.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  | portfolio |  |  |
| `input_set_id` | `CharField` |  | 是 |  |  |  |
| `input_set_version` | `CharField` |  |  |  |  |  |
| `contract_version` | `CharField` |  |  |  |  |  |
| `input_set_hash` | `CharField` |  | 是 |  |  |  |
| `portfolio_snapshot_id` | `CharField` |  |  |  |  |  |
| `portfolio_snapshot_hash` | `CharField` |  |  |  |  |  |
| `universe_hash` | `CharField` |  |  |  |  |  |
| `evidence_graph_hash` | `CharField` |  |  |  |  |  |
| `pit_manifest_set_hash` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `payload_count` | `PositiveSmallIntegerField` |  |  |  |  |  |
| `owner_binding_count` | `PositiveSmallIntegerField` |  |  |  |  |  |
| `promotion_count` | `PositiveSmallIntegerField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### GovernedOptimizationResearchResultModel

- 来源文件：`apps/portfolio/infrastructure/optimization_research_models.py`
- 数据表：`portfolio_governed_optimization_result`
- 说明：Immutable four-candidate research comparison result.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `result_id` | `CharField` |  |  |  |  |  |
| `input_receipt` | `ForeignKey` | 是 |  |  |  | GovernedOptimizationInputReceiptModel |
| `result_version` | `CharField` |  |  |  |  |  |
| `run_key` | `CharField` |  |  |  |  |  |
| `run_version` | `CharField` |  |  |  |  |  |
| `assembly_hash` | `CharField` |  |  |  |  |  |
| `problem_id` | `CharField` |  |  |  |  |  |
| `problem_hash` | `CharField` |  |  |  |  |  |
| `input_set_id` | `CharField` |  |  |  |  |  |
| `input_set_hash` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `selected_candidate` | `CharField` |  |  |  |  |  |
| `candidates` | `JSONField` |  |  | list |  |  |
| `problem_blockers` | `JSONField` |  |  | list |  |  |
| `evaluated_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### OptimizationAppendOnlyModel

- 来源文件：`apps/portfolio/infrastructure/optimization_research_models.py`
- 抽象模型：是
- 说明：Reject instance and manager mutation of evidentiary rows.

### OptimizationResearchLifecycleEventModel

- 来源文件：`apps/portfolio/infrastructure/optimization_research_models.py`
- 数据表：`portfolio_optimization_lifecycle_event`
- 说明：Immutable hash-chain event for one governed result.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `event_id` | `CharField` |  |  |  |  |  |
| `result` | `ForeignKey` |  |  |  |  | GovernedOptimizationResearchResultModel |
| `result_hash` | `CharField` |  |  |  |  |  |
| `event_type` | `CharField` |  |  |  |  |  |
| `sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `reason_codes` | `JSONField` |  |  | list |  |  |
| `previous_event_hash` | `CharField` | 是 |  |  |  |  |
| `promotion_attestation` | `JSONField` | 是 |  |  |  |  |
| `owner_attestation` | `JSONField` | 是 |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### OrderIntentModel

- 来源文件：`apps/portfolio/infrastructure/order_models.py`
- 数据表：`order_intent`
- 说明：Compatibility table now owned by the portfolio bounded context.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `intent_id` | `CharField` |  | 是 |  | 意图ID |  |
| `idempotency_key` | `CharField` |  | 是 |  | 幂等键 |  |
| `strategy` | `ForeignKey` |  |  |  | 策略 | strategy.StrategyModel |
| `portfolio` | `ForeignKey` |  |  |  | 投资组合 | simulated_trading.SimulatedAccountModel |
| `symbol` | `CharField` |  |  |  | 资产代码 |  |
| `side` | `CharField` |  |  |  | 方向 |  |
| `qty` | `PositiveIntegerField` |  |  |  | 数量 |  |
| `limit_price` | `FloatField` | 是 |  |  | 限价 |  |
| `time_in_force` | `CharField` |  |  | day | 订单时效 |  |
| `reason` | `TextField` |  |  |  | 原因 |  |
| `status` | `CharField` |  |  | draft | 状态 |  |
| `decision_json` | `JSONField` |  |  | dict | 决策快照 |  |
| `sizing_json` | `JSONField` |  |  | dict | 仓位快照 |  |
| `risk_snapshot_json` | `JSONField` |  |  | dict | 风控快照 |  |
| `created_at` | `DateTimeField` |  |  | timezone.now | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### PlanningPolicyActivationAppendOnlyModel

- 来源文件：`apps/portfolio/infrastructure/planning_policy_activation_models.py`
- 抽象模型：是
- 说明：Permit only exact inserts claimed by this ledger's repository.

### PortfolioPlanningPolicyActivationModel

- 来源文件：`apps/portfolio/infrastructure/planning_policy_activation_models.py`
- 数据表：`portfolio_planning_policy_activation`
- 说明：One immutable activation-chain record first winner.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `subject_record` | `OneToOneField` |  |  |  |  | PortfolioPlanningPolicyActivationSubjectModel |
| `owner` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `activation_id` | `CharField` |  |  |  |  |  |
| `activation_version` | `CharField` |  |  |  |  |  |
| `activation_identity_hash` | `CharField` |  | 是 |  |  |  |
| `subject_id` | `CharField` |  |  |  |  |  |
| `subject_version` | `CharField` |  |  |  |  |  |
| `subject_content_hash` | `CharField` |  | 是 |  |  |  |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `definition_identity_hash` | `CharField` |  |  |  |  |  |
| `definition_content_hash` | `CharField` |  |  |  |  |  |
| `requested_actor_id` | `CharField` |  |  |  |  |  |
| `requested_actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `requested_actor_role` | `CharField` |  |  |  |  |  |
| `approved_actor_id` | `CharField` |  |  |  |  |  |
| `approved_actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `approved_actor_role` | `CharField` |  |  |  |  |  |
| `approved_actor_kind` | `CharField` |  |  |  |  |  |
| `approved_actor_is_staff` | `BooleanField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `predecessor_hash` | `CharField` | 是 | 是 |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |

### PortfolioPlanningPolicyActivationSubjectModel

- 来源文件：`apps/portfolio/infrastructure/planning_policy_activation_models.py`
- 数据表：`portfolio_planning_policy_activation_subject`
- 说明：One immutable activation-request identity first winner.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `subject_id` | `CharField` |  |  |  |  |  |
| `subject_version` | `CharField` |  |  |  |  |  |
| `subject_identity_hash` | `CharField` |  | 是 |  |  |  |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `definition_identity_hash` | `CharField` |  |  |  |  |  |
| `definition_content_hash` | `CharField` |  |  |  |  |  |
| `definition_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `requested_actor_id` | `CharField` |  |  |  |  |  |
| `requested_actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `requested_actor_role` | `CharField` |  |  |  |  |  |
| `requested_actor_kind` | `CharField` |  |  |  |  |  |
| `requested_actor_is_staff` | `BooleanField` |  |  |  |  |  |
| `requested_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `supersedes_activation_hash` | `CharField` | 是 |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |

### PortfolioPlanningPolicyDefinitionModel

- 来源文件：`apps/portfolio/infrastructure/planning_policy_definition_models.py`
- 数据表：`portfolio_planning_policy_definition`
- 说明：One immutable Portfolio planning-policy definition first winner.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `buy_lot_size` | `PositiveIntegerField` |  |  |  |  |  |
| `fee_rate` | `CharField` |  |  |  |  |  |
| `slippage_rate` | `CharField` |  |  |  |  |  |
| `min_rebalance_value` | `CharField` |  |  |  |  |  |
| `max_asset_weight` | `CharField` |  |  |  |  |  |
| `max_volume_participation` | `CharField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |

### PortfolioPolicyBenchmarkCorporateActionModel

- 来源文件：`apps/portfolio/infrastructure/policy_benchmark_corporate_action_models.py`
- 数据表：`portfolio_policy_benchmark_corporate_action`
- 说明：One immutable corporate-action methodology first winner.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `methodology_id` | `CharField` |  |  |  |  |  |
| `methodology_version` | `CharField` |  |  |  |  |  |
| `security_identifier_namespace` | `CharField` |  |  |  |  |  |
| `timezone_name` | `CharField` |  |  |  |  |  |
| `business_date_cutoff_local` | `CharField` |  |  |  |  |  |
| `business_date_policy` | `CharField` |  |  |  |  |  |
| `non_business_date_policy` | `CharField` |  |  |  |  |  |
| `source_count` | `PositiveIntegerField` |  |  |  |  |  |
| `sources_hash` | `CharField` |  |  |  |  |  |
| `event_rule_count` | `PositiveIntegerField` |  |  |  |  |  |
| `event_rules_hash` | `CharField` |  |  |  |  |  |
| `source_failure_policy` | `CharField` |  |  |  |  |  |
| `missing_action_policy` | `CharField` |  |  |  |  |  |
| `unknown_event_type_policy` | `CharField` |  |  |  |  |  |
| `price_input_adjustment_basis` | `CharField` |  |  |  |  |  |
| `adjustment_application_policy` | `CharField` |  |  |  |  |  |
| `duplicate_event_policy` | `CharField` |  |  |  |  |  |
| `pre_adjusted_input_policy` | `CharField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |

### PortfolioPolicyBenchmarkCostTaxModel

- 来源文件：`apps/portfolio/infrastructure/policy_benchmark_cost_tax_models.py`
- 数据表：`portfolio_policy_benchmark_cost_tax`
- 说明：One immutable benchmark cost/tax methodology first winner.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `methodology_id` | `CharField` |  |  |  |  |  |
| `methodology_version` | `CharField` |  |  |  |  |  |
| `source_count` | `PositiveIntegerField` |  |  |  |  |  |
| `fee_source_count` | `PositiveIntegerField` |  |  |  |  |  |
| `tax_source_count` | `PositiveIntegerField` |  |  |  |  |  |
| `sources_hash` | `CharField` |  |  |  |  |  |
| `charge_rule_count` | `PositiveIntegerField` |  |  |  |  |  |
| `fee_rule_count` | `PositiveIntegerField` |  |  |  |  |  |
| `tax_rule_count` | `PositiveIntegerField` |  |  |  |  |  |
| `charge_rules_hash` | `CharField` |  |  |  |  |  |
| `business_date_policy` | `CharField` |  |  |  |  |  |
| `currency_basis_policy` | `CharField` |  |  |  |  |  |
| `currency_conversion_policy` | `CharField` |  |  |  |  |  |
| `missing_fx_policy` | `CharField` |  |  |  |  |  |
| `unknown_asset_policy` | `CharField` |  |  |  |  |  |
| `unknown_fee_policy` | `CharField` |  |  |  |  |  |
| `unknown_tax_policy` | `CharField` |  |  |  |  |  |
| `missing_source_policy` | `CharField` |  |  |  |  |  |
| `source_failure_policy` | `CharField` |  |  |  |  |  |
| `estimation_policy` | `CharField` |  |  |  |  |  |
| `silent_zero_policy` | `CharField` |  |  |  |  |  |
| `duplicate_charge_policy` | `CharField` |  |  |  |  |  |
| `cash_dividend_charge_policy` | `CharField` |  |  |  |  |  |
| `cash_dividend_payment_policy` | `CharField` |  |  |  |  |  |
| `corporate_action_charge_policy` | `CharField` |  |  |  |  |  |
| `already_net_amount_policy` | `CharField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |

### PortfolioPolicyBenchmarkDefinitionModel

- 来源文件：`apps/portfolio/infrastructure/policy_benchmark_definition_models.py`
- 数据表：`portfolio_policy_benchmark_definition`
- 说明：One immutable policy-benchmark definition first winner.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `definition_id` | `CharField` |  |  |  |  |  |
| `definition_version` | `CharField` |  |  |  |  |  |
| `base_currency` | `CharField` |  |  |  |  |  |
| `constituent_count` | `PositiveIntegerField` |  |  |  |  |  |
| `constituents_hash` | `CharField` |  |  |  |  |  |
| `methodology_refs_hash` | `CharField` |  |  |  |  |  |
| `valuation_timezone` | `CharField` |  |  |  |  |  |
| `valuation_cutoff` | `CharField` |  |  |  |  |  |
| `evaluation_window_days` | `PositiveIntegerField` |  |  |  |  |  |
| `max_price_age_seconds` | `PositiveIntegerField` |  |  |  |  |  |
| `max_fx_age_seconds` | `PositiveIntegerField` |  |  |  |  |  |
| `missing_price_policy` | `CharField` |  |  |  |  |  |
| `missing_fx_policy` | `CharField` |  |  |  |  |  |
| `blocker_codes_hash` | `CharField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |

### PortfolioPolicyBenchmarkFxFixingModel

- 来源文件：`apps/portfolio/infrastructure/policy_benchmark_fx_fixing_models.py`
- 数据表：`portfolio_policy_benchmark_fx_fixing`
- 说明：One immutable benchmark FX-fixing definition first winner.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `methodology_id` | `CharField` |  |  |  |  |  |
| `methodology_version` | `CharField` |  |  |  |  |  |
| `base_currency` | `CharField` |  |  |  |  |  |
| `quote_currency` | `CharField` |  |  |  |  |  |
| `currency_pair` | `CharField` |  |  |  |  |  |
| `fixing_convention` | `CharField` |  |  |  |  |  |
| `inverse_rate_allowed` | `BooleanField` |  |  |  |  |  |
| `timezone_name` | `CharField` |  |  |  |  |  |
| `valuation_cutoff_local` | `CharField` |  |  |  |  |  |
| `source_count` | `PositiveIntegerField` |  |  |  |  |  |
| `sources_hash` | `CharField` |  |  |  |  |  |
| `stale_after_seconds` | `PositiveIntegerField` |  |  |  |  |  |
| `triangulation_policy` | `CharField` |  |  |  |  |  |
| `triangulation_currency` | `CharField` | 是 |  |  |  |  |
| `source_failure_policy` | `CharField` |  |  |  |  |  |
| `missing_fx_policy` | `CharField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |

### BenchmarkMethodologyActivationAppendOnlyModel

- 来源文件：`apps/portfolio/infrastructure/policy_benchmark_methodology_activation_models.py`
- 抽象模型：是
- 说明：Permit only exact inserts claimed by this ledger's repository.

### PortfolioPolicyBenchmarkMethodologyActivationModel

- 来源文件：`apps/portfolio/infrastructure/policy_benchmark_methodology_activation_models.py`
- 数据表：`portfolio_policy_benchmark_method_activation`
- 说明：One immutable configuration-only methodology bundle activation.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `subject_record` | `OneToOneField` |  |  |  |  | PortfolioPolicyBenchmarkMethodologyActivationSubjectModel |
| `owner` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `clock_source` | `CharField` |  |  |  |  |  |
| `activation_id` | `CharField` |  |  |  |  |  |
| `activation_version` | `CharField` |  |  |  |  |  |
| `activation_identity_hash` | `CharField` |  | 是 |  |  |  |
| `subject_id` | `CharField` |  |  |  |  |  |
| `subject_version` | `CharField` |  |  |  |  |  |
| `subject_content_hash` | `CharField` |  | 是 |  |  |  |
| `definition_id` | `CharField` |  |  |  |  |  |
| `definition_version` | `CharField` |  |  |  |  |  |
| `definition_identity_hash` | `CharField` |  |  |  |  |  |
| `definition_content_hash` | `CharField` |  |  |  |  |  |
| `methodology_refs_hash` | `CharField` |  |  |  |  |  |
| `methodology_bundle_hash` | `CharField` |  |  |  |  |  |
| `requested_actor_id` | `CharField` |  |  |  |  |  |
| `requested_actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `requested_actor_role` | `CharField` |  |  |  |  |  |
| `requested_actor_kind` | `CharField` |  |  |  |  |  |
| `requested_actor_is_staff` | `BooleanField` |  |  |  |  |  |
| `requested_actor_authentication_source` | `CharField` |  |  |  |  |  |
| `approved_actor_id` | `CharField` |  |  |  |  |  |
| `approved_actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `approved_actor_role` | `CharField` |  |  |  |  |  |
| `approved_actor_kind` | `CharField` |  |  |  |  |  |
| `approved_actor_is_staff` | `BooleanField` |  |  |  |  |  |
| `approved_actor_authentication_source` | `CharField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `predecessor_hash` | `CharField` | 是 | 是 |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |

### PortfolioPolicyBenchmarkMethodologyActivationSubjectModel

- 来源文件：`apps/portfolio/infrastructure/policy_benchmark_methodology_activation_models.py`
- 数据表：`portfolio_policy_benchmark_method_activation_subject`
- 说明：One immutable definition-and-five-source activation request.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `subject_id` | `CharField` |  |  |  |  |  |
| `subject_version` | `CharField` |  |  |  |  |  |
| `subject_identity_hash` | `CharField` |  | 是 |  |  |  |
| `definition_id` | `CharField` |  |  |  |  |  |
| `definition_version` | `CharField` |  |  |  |  |  |
| `definition_identity_hash` | `CharField` |  |  |  |  |  |
| `definition_content_hash` | `CharField` |  |  |  |  |  |
| `definition_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `definition_valid_until` | `DateTimeField` |  |  |  |  |  |
| `methodology_count` | `PositiveSmallIntegerField` |  |  |  |  |  |
| `methodology_refs_hash` | `CharField` |  |  |  |  |  |
| `methodology_bundle_hash` | `CharField` |  |  |  |  |  |
| `corporate_action_ref_hash` | `CharField` |  |  |  |  |  |
| `cost_tax_ref_hash` | `CharField` |  |  |  |  |  |
| `fx_fixing_ref_hash` | `CharField` |  |  |  |  |  |
| `price_fixing_ref_hash` | `CharField` |  |  |  |  |  |
| `trading_calendar_ref_hash` | `CharField` |  |  |  |  |  |
| `requested_actor_id` | `CharField` |  |  |  |  |  |
| `requested_actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `requested_actor_role` | `CharField` |  |  |  |  |  |
| `requested_actor_kind` | `CharField` |  |  |  |  |  |
| `requested_actor_is_staff` | `BooleanField` |  |  |  |  |  |
| `requested_actor_authentication_source` | `CharField` |  |  |  |  |  |
| `requested_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `supersedes_activation_hash` | `CharField` | 是 |  |  |  |  |
| `clock_source` | `CharField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |

### PortfolioPolicyBenchmarkPriceFixingModel

- 来源文件：`apps/portfolio/infrastructure/policy_benchmark_price_fixing_models.py`
- 数据表：`portfolio_policy_benchmark_price_fixing`
- 说明：One immutable benchmark price-fixing definition first winner.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `methodology_id` | `CharField` |  |  |  |  |  |
| `methodology_version` | `CharField` |  |  |  |  |  |
| `price_identifier_namespace` | `CharField` |  |  |  |  |  |
| `price_field` | `CharField` |  |  |  |  |  |
| `adjustment_basis` | `CharField` |  |  |  |  |  |
| `venue` | `CharField` |  |  |  |  |  |
| `timezone_name` | `CharField` |  |  |  |  |  |
| `valuation_cutoff_local` | `CharField` |  |  |  |  |  |
| `source_count` | `PositiveIntegerField` |  |  |  |  |  |
| `sources_hash` | `CharField` |  |  |  |  |  |
| `stale_after_seconds` | `PositiveIntegerField` |  |  |  |  |  |
| `missing_price_policy` | `CharField` |  |  |  |  |  |
| `source_failure_policy` | `CharField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |

### PortfolioPolicyBenchmarkTradingCalendarModel

- 来源文件：`apps/portfolio/infrastructure/policy_benchmark_trading_calendar_models.py`
- 数据表：`portfolio_policy_benchmark_trading_calendar`
- 说明：One immutable benchmark trading-calendar definition first winner.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `methodology_id` | `CharField` |  |  |  |  |  |
| `methodology_version` | `CharField` |  |  |  |  |  |
| `market_calendar_code` | `CharField` |  |  |  |  |  |
| `timezone_name` | `CharField` |  |  |  |  |  |
| `coverage_start` | `DateField` |  |  |  |  |  |
| `coverage_end` | `DateField` |  |  |  |  |  |
| `day_count` | `PositiveIntegerField` |  |  |  |  |  |
| `valuation_day_count` | `PositiveIntegerField` |  |  |  |  |  |
| `membership_hash` | `CharField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |

### PortfolioPlanningPolicyModel

- 来源文件：`apps/portfolio/infrastructure/policy_models.py`
- 数据表：`portfolio_planning_policy`
- 说明：Immutable planning thresholds selected through an explicit active version.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `policy_id` | `CharField` |  |  |  |  |  |
| `version` | `CharField` |  | 是 |  |  |  |
| `status` | `CharField` |  |  | draft |  |  |
| `buy_lot_size` | `PositiveIntegerField` |  |  |  |  |  |
| `fee_rate` | `DecimalField` |  |  |  |  |  |
| `slippage_rate` | `DecimalField` |  |  |  |  |  |
| `min_rebalance_value` | `DecimalField` |  |  |  |  |  |
| `max_asset_weight` | `DecimalField` |  |  |  |  |  |
| `max_volume_participation` | `DecimalField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### PortfolioR4MonitoringRawFactReceiptModel

- 来源文件：`apps/portfolio/infrastructure/r4_monitoring_raw_fact_models.py`
- 数据表：`portfolio_r4_monitoring_raw_fact_receipt`
- 说明：One immutable Portfolio-owned observation receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `observation_id` | `CharField` |  |  |  |  |  |
| `observation_version` | `CharField` |  |  |  |  |  |
| `active_decision_id` | `CharField` |  |  |  |  |  |
| `active_decision_version` | `CharField` |  |  |  |  |  |
| `active_decision_hash` | `CharField` |  |  |  |  |  |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_hash` | `CharField` |  |  |  |  |  |
| `calendar_id` | `CharField` |  |  |  |  |  |
| `calendar_version` | `CharField` |  |  |  |  |  |
| `calendar_hash` | `CharField` |  |  |  |  |  |
| `period_id` | `CharField` |  |  |  |  |  |
| `source_owner` | `CharField` |  |  | portfolio |  |  |
| `definition_hash` | `CharField` |  |  |  |  |  |
| `source_receipt_id` | `CharField` |  |  |  |  |  |
| `source_receipt_version` | `CharField` |  |  |  |  |  |
| `source_receipt_hash` | `CharField` |  |  |  |  |  |
| `source_receipt_payload` | `JSONField` |  |  |  |  |  |
| `observed_at` | `DateTimeField` |  |  |  |  |  |
| `available_at` | `DateTimeField` |  |  |  |  |  |
| `owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R4RollingAppendOnlyModel

- 来源文件：`apps/portfolio/infrastructure/r4_rolling_research_models.py`
- 抽象模型：是
- 说明：Reject instance updates and deletions for every R4 ledger row.

### R4RollingResearchReceiptModel

- 来源文件：`apps/portfolio/infrastructure/r4_rolling_research_models.py`
- 数据表：`portfolio_r4_rolling_research_receipt`
- 说明：Immutable input/provenance receipt stamped by the Portfolio repository.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `record_version` | `CharField` |  |  |  |  |  |
| `study_id` | `CharField` |  |  |  |  |  |
| `study_version` | `CharField` |  |  |  |  |  |
| `study_content_hash` | `CharField` |  |  |  |  |  |
| `r3_promotion_attestation_hash` | `CharField` |  |  |  |  |  |
| `split_contract_hash` | `CharField` |  |  |  |  |  |
| `evaluated_at` | `DateTimeField` |  |  |  |  |  |
| `owner` | `CharField` |  |  | portfolio |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `producer_code_version` | `CharField` |  |  |  |  |  |
| `dependency_lock_hash` | `CharField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `study_payload` | `JSONField` |  |  |  |  |  |
| `promotion_attestation_payload` | `JSONField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R4RollingResearchResultModel

- 来源文件：`apps/portfolio/infrastructure/r4_rolling_research_models.py`
- 数据表：`portfolio_r4_rolling_research_result`
- 说明：Immutable factory-recomputed R4 rolling result and complete subhash ledger.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `record_id` | `CharField` |  |  |  |  |  |
| `receipt` | `ForeignKey` |  |  |  |  | R4RollingResearchReceiptModel |
| `artifact_hash` | `CharField` |  |  |  |  |  |
| `evidence_complete` | `BooleanField` |  |  |  |  |  |
| `eligible_for_research_comparison` | `BooleanField` |  |  |  |  |  |
| `subhashes` | `JSONField` |  |  | list |  |  |
| `artifact_payload` | `JSONField` |  |  |  |  |  |
| `record_hash` | `CharField` |  | 是 |  |  |  |
| `usage_scope` | `CharField` |  |  | research_only |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### PortfolioR5MonitoringRawFactReceiptModel

- 来源文件：`apps/portfolio/infrastructure/r5_monitoring_raw_fact_models.py`
- 数据表：`portfolio_r5_monitoring_raw_fact_receipt`
- 说明：Immutable complete fact, definition, and source receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `fact_id` | `CharField` |  |  |  |  |  |
| `fact_version` | `CharField` |  |  |  |  |  |
| `fact_hash` | `CharField` |  | 是 |  |  |  |
| `definition_hash` | `CharField` |  | 是 |  |  |  |
| `period_id` | `CharField` |  |  |  |  |  |
| `period_end` | `DateTimeField` |  |  |  |  |  |
| `calendar_id` | `CharField` |  |  |  |  |  |
| `calendar_version` | `CharField` |  |  |  |  |  |
| `calendar_hash` | `CharField` |  |  |  |  |  |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_hash` | `CharField` |  |  |  |  |  |
| `target_hash` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `decision_id` | `CharField` |  |  |  |  |  |
| `decision_version` | `CharField` |  |  |  |  |  |
| `lifecycle_hash` | `CharField` |  |  |  |  |  |
| `source_receipt_id` | `CharField` |  |  |  |  |  |
| `source_receipt_version` | `CharField` |  |  |  |  |  |
| `source_receipt_hash` | `CharField` |  | 是 |  |  |  |
| `source_available_at` | `DateTimeField` |  |  |  |  |  |
| `source_valid_until` | `DateTimeField` |  |  |  |  |  |
| `fact_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `fact_valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `fact_payload` | `JSONField` |  |  |  |  |  |
| `source_payload` | `JSONField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### PortfolioR5RelativeValueOutcomeModel

- 来源文件：`apps/portfolio/infrastructure/r5_relative_value_outcome_models.py`
- 数据表：`portfolio_r5_relative_value_outcome`
- 说明：One immutable realized outcome with string-only cross-owner references.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `outcome_id` | `CharField` |  |  |  |  |  |
| `outcome_version` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  | portfolio |  |  |
| `owner_record_id` | `CharField` |  |  |  |  |  |
| `owner_record_version` | `CharField` |  |  |  |  |  |
| `owner_record_hash` | `CharField` |  |  |  |  |  |
| `observation_id` | `CharField` |  |  |  |  |  |
| `fixed_income_result_id` | `CharField` |  |  |  |  |  |
| `fixed_income_result_version` | `CharField` |  |  |  |  |  |
| `fixed_income_result_record_hash` | `CharField` |  |  |  |  |  |
| `fixed_income_owner_seal_hash` | `CharField` |  |  |  |  |  |
| `selection_as_of` | `DateTimeField` |  |  |  |  |  |
| `outcome_observed_at` | `DateTimeField` |  |  |  |  |  |
| `outcome_available_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `target_gross_return` | `DecimalField` |  |  |  |  |  |
| `target_cost` | `DecimalField` |  |  |  |  |  |
| `benchmark_gross_return` | `DecimalField` |  |  |  |  |  |
| `benchmark_cost` | `DecimalField` |  |  |  |  |  |
| `target_maximum_drawdown` | `DecimalField` |  |  |  |  |  |
| `benchmark_maximum_drawdown` | `DecimalField` |  |  |  |  |  |
| `capacity_utilization` | `DecimalField` |  |  |  |  |  |
| `liquidity_breached` | `BooleanField` |  |  |  |  |  |
| `realized_credit_loss` | `DecimalField` |  |  |  |  |  |
| `command_hash` | `CharField` |  |  |  |  |  |
| `draft_hash` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R5OutcomeAppendOnlyModel

- 来源文件：`apps/portfolio/infrastructure/r5_relative_value_outcome_models.py`
- 抽象模型：是
- 说明：Permit only a claimed database-assigned-primary-key insert.

### R8MonitoringCalendarRegistryModel

- 来源文件：`apps/portfolio/infrastructure/r8_monitoring_calendar_models.py`
- 数据表：`portfolio_r8_monitoring_calendar_registry`
- 说明：One immutable complete calendar and its canonical source authorization.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `calendar_id` | `CharField` |  |  |  |  |  |
| `calendar_version` | `CharField` |  |  |  |  |  |
| `definition_hash` | `CharField` |  |  |  |  |  |
| `definition_payload` | `JSONField` |  |  |  |  |  |
| `source_receipt_id` | `CharField` |  |  |  |  |  |
| `source_receipt_version` | `CharField` |  |  |  |  |  |
| `source_receipt_hash` | `CharField` |  |  |  |  |  |
| `source_receipt_payload` | `JSONField` |  |  |  |  |  |
| `source_available_at` | `DateTimeField` |  |  |  |  |  |
| `source_valid_until` | `DateTimeField` |  |  |  |  |  |
| `source_evidence_ref` | `CharField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `first_period_start` | `DateTimeField` |  |  |  |  |  |
| `last_period_end` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `period_count` | `PositiveIntegerField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### PortfolioR8MonitoringFeedbackReceiptModel

- 来源文件：`apps/portfolio/infrastructure/r8_monitoring_feedback_models.py`
- 数据表：`portfolio_r8_monitoring_feedback_receipt`
- 说明：Immutable complete raw feedback definition and source receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `feedback_id` | `CharField` |  |  |  |  |  |
| `feedback_version` | `CharField` |  |  |  |  |  |
| `feedback_hash` | `CharField` |  | 是 |  |  |  |
| `definition_version` | `CharField` |  |  |  |  |  |
| `definition_hash` | `CharField` |  | 是 |  |  |  |
| `source_receipt_id` | `CharField` |  |  |  |  |  |
| `source_receipt_version` | `CharField` |  |  |  |  |  |
| `source_receipt_hash` | `CharField` |  | 是 |  |  |  |
| `source_owner` | `CharField` |  |  |  |  |  |
| `result_id` | `CharField` |  |  |  |  |  |
| `result_version` | `CharField` |  |  |  |  |  |
| `result_hash` | `CharField` |  |  |  |  |  |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `receipt_hash` | `CharField` |  |  |  |  |  |
| `calendar_id` | `CharField` |  |  |  |  |  |
| `calendar_version` | `CharField` |  |  |  |  |  |
| `calendar_hash` | `CharField` |  |  |  |  |  |
| `period_id` | `CharField` |  |  |  |  |  |
| `period_start_at` | `DateTimeField` |  |  |  |  |  |
| `period_end_at` | `DateTimeField` |  |  |  |  |  |
| `source_observed_at` | `DateTimeField` |  |  |  |  |  |
| `source_available_at` | `DateTimeField` |  |  |  |  |  |
| `source_valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `net_realized_pnl_after_flows` | `DecimalField` |  |  |  |  |  |
| `opening_portfolio_value` | `DecimalField` |  |  |  |  |  |
| `maximum_peak_to_trough_loss` | `DecimalField` |  |  |  |  |  |
| `peak_portfolio_value` | `DecimalField` |  |  |  |  |  |
| `absolute_traded_notional` | `DecimalField` |  |  |  |  |  |
| `average_portfolio_value` | `DecimalField` |  |  |  |  |  |
| `liquidity_consumed_notional` | `DecimalField` |  |  |  |  |  |
| `liquidity_budget_notional` | `DecimalField` |  |  |  |  |  |
| `position_exposure_notional` | `DecimalField` |  |  |  |  |  |
| `capacity_limit_notional` | `DecimalField` |  |  |  |  |  |
| `constraint_breach_count` | `PositiveBigIntegerField` |  |  |  |  |  |
| `constraint_evaluation_count` | `PositiveBigIntegerField` |  |  |  |  |  |
| `changed_label_count` | `PositiveBigIntegerField` |  |  |  |  |  |
| `comparable_label_count` | `PositiveBigIntegerField` |  |  |  |  |  |
| `aggregate_drift_distance` | `DecimalField` |  |  |  |  |  |
| `drift_normalization_bound` | `DecimalField` |  |  |  |  |  |
| `member_manifest_hash` | `CharField` |  |  |  |  |  |
| `raw_fact_manifest_hash` | `CharField` |  |  |  |  |  |
| `definition_payload` | `JSONField` |  |  |  |  |  |
| `source_payload` | `JSONField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### PortfolioTransitionPlanModel

- 来源文件：`apps/portfolio/infrastructure/transition_models.py`
- 数据表：`decision_portfolio_transition_plan`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `plan_id` | `CharField` |  | 是 |  | 计划唯一标识符 |  |
| `account_id` | `CharField` |  |  |  | 账户 ID |  |
| `source_recommendation_ids` | `JSONField` |  |  | list | 来源推荐 ID 列表 |  |
| `current_positions_snapshot` | `JSONField` |  |  | list | 当前持仓快照 |  |
| `target_positions_snapshot` | `JSONField` |  |  | list | 目标持仓快照 |  |
| `orders` | `JSONField` |  |  | list | 调仓订单快照 |  |
| `risk_contract` | `JSONField` |  |  | dict | 计划级风控契约 |  |
| `summary` | `JSONField` |  |  | dict | 计划摘要 |  |
| `status` | `CharField` |  |  | DRAFT | 计划状态 |  |
| `approval_request_id` | `CharField` |  |  |  | 关联审批请求 ID |  |
| `plan_contract_family` | `CharField` | 是 |  |  | Transition-plan payload contract family; NULL denotes unclassified legacy data |  |
| `idempotency_key` | `CharField` | 是 | 是 |  |  |  |
| `decision_snapshot_id` | `CharField` |  |  |  |  |  |
| `portfolio_snapshot_id` | `CharField` |  |  |  |  |  |
| `target_portfolio_id` | `CharField` |  |  |  |  |  |
| `expires_at` | `DateTimeField` | 是 |  |  |  |  |
| `immutable_payload_hash` | `CharField` |  |  |  |  |  |
| `plan_version` | `PositiveIntegerField` |  |  | 1 |  |  |
| `approved_at` | `DateTimeField` | 是 |  |  |  |  |
| `as_of` | `DateTimeField` |  |  |  | 计划快照时间 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### TransitionPlanInactiveApprovalAppendOnlyModel

- 来源文件：`apps/portfolio/infrastructure/transition_plan_inactive_approval_models.py`
- 抽象模型：是
- 说明：Permit only exact, repository-claimed inserts.

### TransitionPlanInactiveApprovalReceiptModel

- 来源文件：`apps/portfolio/infrastructure/transition_plan_inactive_approval_models.py`
- 数据表：`portfolio_transition_inactive_approval_receipt`
- 说明：One immutable inactive receipt for one registered subject.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `subject_record` | `OneToOneField` |  |  |  |  | TransitionPlanInactiveApprovalSubjectModel |
| `owner` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `receipt_identity_hash` | `CharField` |  | 是 |  |  |  |
| `subject_hash` | `CharField` |  | 是 |  |  |  |
| `subject_id` | `CharField` |  |  |  |  |  |
| `subject_version` | `CharField` |  |  |  |  |  |
| `subject_content_hash` | `CharField` |  |  |  |  |  |
| `plan_id` | `CharField` |  |  |  |  |  |
| `plan_version` | `PositiveIntegerField` |  |  |  |  |  |
| `plan_content_hash` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `decision_snapshot_id` | `CharField` |  |  |  |  |  |
| `requested_actor_id` | `CharField` |  |  |  |  |  |
| `requested_actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `requested_actor_role` | `CharField` |  |  |  |  |  |
| `approved_actor_id` | `CharField` |  |  |  |  |  |
| `approved_actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `approved_actor_role` | `CharField` |  |  |  |  |  |
| `plan_status_at_issue` | `CharField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### TransitionPlanInactiveApprovalSubjectModel

- 来源文件：`apps/portfolio/infrastructure/transition_plan_inactive_approval_models.py`
- 数据表：`portfolio_transition_inactive_approval_subject`
- 说明：One immutable exact-plan subject first winner.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `subject_id` | `CharField` |  |  |  |  |  |
| `subject_version` | `CharField` |  |  |  |  |  |
| `subject_identity_hash` | `CharField` |  | 是 |  |  |  |
| `plan_id` | `CharField` |  |  |  |  |  |
| `plan_version` | `PositiveIntegerField` |  |  |  |  |  |
| `plan_content_hash` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `decision_snapshot_id` | `CharField` |  |  |  |  |  |
| `requested_actor_id` | `CharField` |  |  |  |  |  |
| `requested_actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `requested_actor_role` | `CharField` |  |  |  |  |  |
| `requested_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |


## prompt

### PromptEvalAssertion

- 来源文件：`apps/prompt/infrastructure/eval_models.py`
- 数据表：`prompt_eval_assertion`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `run` | `ForeignKey` |  |  |  |  | PromptEvalRun |
| `case` | `ForeignKey` |  |  |  |  | PromptEvalCase |
| `assertion_type` | `CharField` |  |  |  |  |  |
| `passed` | `BooleanField` |  |  |  |  |  |
| `critical` | `BooleanField` |  |  | True |  |  |
| `details` | `JSONField` |  |  | dict |  |  |
| `latency_ms` | `PositiveIntegerField` |  |  | 0 |  |  |
| `tokens` | `PositiveIntegerField` |  |  | 0 |  |  |
| `cost` | `DecimalField` |  |  | 0 |  |  |

### PromptEvalCase

- 来源文件：`apps/prompt/infrastructure/eval_models.py`
- 数据表：`prompt_eval_case`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `case_id` | `CharField` |  |  |  |  |  |
| `dataset` | `ForeignKey` |  |  |  |  | PromptEvalDataset |
| `input_variables` | `JSONField` |  |  | dict |  |  |
| `expected_schema` | `JSONField` |  |  | dict |  |  |
| `allowed_tools` | `JSONField` |  |  | list |  |  |
| `assertions` | `JSONField` |  |  | list |  |  |

### PromptEvalDataset

- 来源文件：`apps/prompt/infrastructure/eval_models.py`
- 数据表：`prompt_eval_dataset`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `dataset_id` | `CharField` |  |  |  |  |  |
| `name` | `CharField` |  |  |  |  |  |
| `version` | `CharField` |  |  |  |  |  |
| `content_hash` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### PromptEvalRun

- 来源文件：`apps/prompt/infrastructure/eval_models.py`
- 数据表：`prompt_eval_run`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `run_id` | `CharField` |  |  |  |  |  |
| `prompt_version` | `ForeignKey` |  |  |  |  | PromptVersion |
| `dataset` | `ForeignKey` |  |  |  |  | PromptEvalDataset |
| `evaluation_type` | `CharField` |  |  |  |  |  |
| `provider` | `CharField` |  |  |  |  |  |
| `model` | `CharField` |  |  |  |  |  |
| `temperature` | `FloatField` |  |  | 0.0 |  |  |
| `status` | `CharField` |  |  | running |  |  |
| `max_cost` | `DecimalField` |  |  |  |  |  |
| `actual_cost` | `DecimalField` |  |  | 0 |  |  |
| `max_tokens` | `PositiveIntegerField` |  |  |  |  |  |
| `actual_tokens` | `PositiveIntegerField` |  |  | 0 |  |  |
| `max_cases` | `PositiveIntegerField` |  |  |  |  |  |
| `executed_cases` | `PositiveIntegerField` |  |  | 0 |  |  |
| `failure_summary` | `JSONField` |  |  | list |  |  |
| `started_at` | `DateTimeField` |  |  |  |  |  |
| `completed_at` | `DateTimeField` | 是 |  |  |  |  |

### PromptPromotionDecision

- 来源文件：`apps/prompt/infrastructure/eval_models.py`
- 数据表：`prompt_promotion_decision`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `decision_id` | `CharField` |  |  |  |  |  |
| `prompt_version` | `OneToOneField` |  |  |  |  | PromptVersion |
| `eval_run` | `ForeignKey` |  |  |  |  | PromptEvalRun |
| `decision` | `CharField` |  |  |  |  |  |
| `evidence` | `JSONField` |  |  | dict |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### PromptVersion

- 来源文件：`apps/prompt/infrastructure/eval_models.py`
- 数据表：`prompt_version`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `version_id` | `CharField` |  |  |  |  |  |
| `template` | `ForeignKey` |  |  |  | prompt.PromptTemplateORM | prompt.PromptTemplateORM |
| `version` | `CharField` |  |  |  |  |  |
| `content` | `TextField` |  |  |  |  |  |
| `system_prompt` | `TextField` |  |  |  |  |  |
| `required_variables` | `JSONField` |  |  | list |  |  |
| `output_schema` | `JSONField` |  |  | dict |  |  |
| `allowed_tools` | `JSONField` |  |  | list |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `status` | `CharField` |  |  | draft |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### AppendOnlyPromptEvidenceMixin

- 来源文件：`apps/prompt/infrastructure/models.py`
- 抽象模型：是
- 说明：Allow one insert and reject later mutation or deletion of Prompt evidence.

### ChainConfigORM

- 来源文件：`apps/prompt/infrastructure/models.py`
- 数据表：`chain_config`
- 说明：链式配置ORM模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | `CharField` |  | 是 |  | 链名称（唯一标识） |  |
| `category` | `CharField` |  |  |  | 分类 |  |
| `description` | `TextField` |  |  |  | 描述 |  |
| `steps` | `JSONField` |  |  | list | 步骤定义列表 |  |
| `execution_mode` | `CharField` |  |  | serial | 执行模式 |  |
| `aggregate_step` | `JSONField` | 是 |  |  | 汇总步骤配置 |  |
| `is_active` | `BooleanField` |  |  | True | 是否激活 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### PromptTemplateORM

- 来源文件：`apps/prompt/infrastructure/models.py`
- 数据表：`prompt_template`
- 说明：Prompt模板ORM模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | `CharField` |  | 是 |  | 模板名称（唯一标识） |  |
| `category` | `CharField` |  |  |  | 分类 |  |
| `version` | `CharField` |  |  | 1.0 | 版本号 |  |
| `template_content` | `TextField` |  |  |  | 模板内容（支持Jinja2语法） |  |
| `system_prompt` | `TextField` |  |  |  | 系统提示词 |  |
| `placeholders` | `JSONField` |  |  | list | 占位符定义列表 |  |
| `temperature` | `FloatField` |  |  | 0.7 | 温度参数（0.0-2.0） |  |
| `max_tokens` | `IntegerField` | 是 |  |  | 最大token数 |  |
| `description` | `TextField` |  |  |  | 描述 |  |
| `is_active` | `BooleanField` |  |  | True | 是否激活 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |
| `last_used_at` | `DateTimeField` | 是 |  |  | 最后使用时间 |  |


## pulse

### NavigatorAssetConfigModel

- 来源文件：`apps/pulse/infrastructure/models.py`
- 数据表：`navigator_asset_config`
- 说明：Regime Navigator 资产配置映射（存储在数据库中）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `regime_name` | `CharField` |  |  |  | Regime 名称 |  |
| `asset_weight_ranges` | `JSONField` |  |  |  | 格式: {"equity": [0.5, 0.7], "bond": [0.15, 0.3], "commodity": [0.05, 0.15], "cash": [0.05, 0.15]} |  |
| `risk_budget` | `FloatField` |  |  | 0.7 | 0-1 之间的值 |  |
| `recommended_sectors` | `JSONField` |  |  | list | 格式: ["消费", "科技", "金融"] |  |
| `benefiting_styles` | `JSONField` |  |  | list | 格式: ["成长", "中小盘"] |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### PulseIndicatorConfigModel

- 来源文件：`apps/pulse/infrastructure/models.py`
- 数据表：`pulse_indicator_config`
- 说明：Pulse 指标配置（存储在数据库中，可管理后台编辑）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `indicator_code` | `CharField` |  | 是 |  | 对应 macro 模块的指标代码，如 CN_TERM_SPREAD_10Y2Y |  |
| `indicator_name` | `CharField` |  |  |  | 指标名称 |  |
| `dimension` | `CharField` |  |  |  | 所属维度 |  |
| `frequency` | `CharField` |  |  | daily | 数据频率 |  |
| `weight` | `FloatField` |  |  | 1.0 | 维度内各指标的权重，默认等权=1.0 |  |
| `signal_type` | `CharField` |  |  | zscore | 信号类型 |  |
| `bullish_threshold` | `FloatField` |  |  | 1.0 | 超过此阈值判定为 bullish |  |
| `bearish_threshold` | `FloatField` |  |  | -1.0 | 低于此阈值判定为 bearish |  |
| `neutral_band` | `FloatField` |  |  | 0.5 | \|value\| < neutral_band 时判定为 neutral |  |
| `signal_multiplier` | `FloatField` |  |  | 0.4 | z_score → signal_score 的乘数。负值表示逆向指标。 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `description` | `TextField` |  |  |  | 说明 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### PulseIndicatorWeight

- 来源文件：`apps/pulse/infrastructure/models.py`
- 数据表：`pulse_indicator_weight`
- 说明：单个指标的权重配置（维度间或者维度内按需分配）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `config` | `ForeignKey` |  |  |  |  | PulseWeightConfig |
| `indicator_code` | `CharField` |  |  |  | 指标代码 |  |
| `dimension` | `CharField` |  |  |  | 维度 |  |
| `weight` | `FloatField` |  |  | 1.0 | 权重 |  |
| `is_enabled` | `BooleanField` |  |  | True | 是否启用 |  |

### PulseLog

- 来源文件：`apps/pulse/infrastructure/models.py`
- 数据表：`pulse_log`
- 说明：Pulse 脉搏快照日志

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `observed_at` | `DateField` |  | 是 |  | 观测日期 |  |
| `regime_context` | `CharField` |  |  |  | 当时的 Regime |  |
| `growth_score` | `FloatField` |  |  | 0.0 | 增长脉搏 |  |
| `inflation_score` | `FloatField` |  |  | 0.0 | 通胀脉搏 |  |
| `liquidity_score` | `FloatField` |  |  | 0.0 | 流动性脉搏 |  |
| `sentiment_score` | `FloatField` |  |  | 0.0 | 情绪脉搏 |  |
| `composite_score` | `FloatField` |  |  |  | 综合分数 |  |
| `regime_strength` | `CharField` |  |  |  | Regime 内强弱 |  |
| `transition_warning` | `BooleanField` |  |  | False | 转折预警 |  |
| `transition_direction` | `CharField` | 是 |  |  | 预警方向 |  |
| `indicator_readings` | `JSONField` |  |  | dict | 指标明细 |  |
| `transition_reasons` | `JSONField` |  |  | list | 预警原因 |  |
| `data_source` | `CharField` |  |  | calculated |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### PulseWeightConfig

- 来源文件：`apps/pulse/infrastructure/models.py`
- 数据表：`pulse_weight_config`
- 说明：Pulse 指标权重整体配置

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | `CharField` |  |  |  | 配置名称 |  |
| `is_active` | `BooleanField` |  |  | True | 是否激活 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |


## realtime

### PriceAlertModel

- 来源文件：`apps/realtime/infrastructure/models.py`
- 数据表：`realtime_price_alert`
- 说明：Durable owner-scoped price alert.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `asset_code` | `CharField` |  |  |  |  |  |
| `condition` | `CharField` |  |  |  |  |  |
| `threshold` | `DecimalField` |  |  |  |  |  |
| `status` | `CharField` |  |  | AlertStatus.ACTIVE.value |  |  |
| `message` | `CharField` |  |  |  |  |  |
| `triggered_price` | `DecimalField` | 是 |  |  |  |  |
| `triggered_at` | `DateTimeField` | 是 |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### PriceSubscriptionModel

- 来源文件：`apps/realtime/infrastructure/models.py`
- 数据表：`realtime_price_subscription`
- 说明：Durable owner-to-asset realtime subscription.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `asset_code` | `CharField` |  |  |  |  |  |
| `is_active` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |


## regime

### HistoricalAssignmentAppendOnlyModel

- 来源文件：`apps/regime/infrastructure/historical_assignment_models.py`
- 抽象模型：是
- 说明：Base model rejecting direct update/delete and unclaimed inserts.

### HistoricalRegimeAssignmentDefinitionModel

- 来源文件：`apps/regime/infrastructure/historical_assignment_models.py`
- 数据表：`regime_historical_assignment_definition`
- 说明：Regime owner definition and trusted registration receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `definition_id` | `CharField` |  |  |  |  |  |
| `definition_version` | `CharField` |  |  |  |  |  |
| `definition_content_hash` | `CharField` |  | 是 |  |  |  |
| `artifact_id` | `CharField` |  |  |  |  |  |
| `artifact_hash` | `CharField` |  |  |  |  |  |
| `pit_manifest_id` | `CharField` |  |  |  |  |  |
| `pit_manifest_hash` | `CharField` |  |  |  |  |  |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_content_hash` | `CharField` |  |  |  |  |  |
| `source_contract_id` | `CharField` |  |  |  |  |  |
| `source_contract_version` | `CharField` |  |  |  |  |  |
| `source_contract_hash` | `CharField` |  |  |  |  |  |
| `registered_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `record_hash` | `CharField` |  | 是 |  |  |  |
| `owner` | `CharField` |  |  | regime |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### HistoricalRegimeAssignmentReceiptModel

- 来源文件：`apps/regime/infrastructure/historical_assignment_models.py`
- 数据表：`regime_historical_assignment_receipt`
- 说明：Exhaustive derived assignments for one exact artifact and cutoff.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `definition` | `ForeignKey` |  |  |  |  | HistoricalRegimeAssignmentDefinitionModel |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `receipt_content_hash` | `CharField` |  | 是 |  |  |  |
| `artifact_id` | `CharField` |  |  |  |  |  |
| `artifact_hash` | `CharField` |  |  |  |  |  |
| `source_result_hash` | `CharField` |  |  |  |  |  |
| `pit_manifest_id` | `CharField` |  |  |  |  |  |
| `pit_manifest_hash` | `CharField` |  |  |  |  |  |
| `pit_as_of` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `assignment_count` | `PositiveIntegerField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `owner` | `CharField` |  |  | regime |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### ActionRecommendationLog

- 来源文件：`apps/regime/infrastructure/models.py`
- 数据表：`action_recommendation_log`
- 说明：联合行动建议历史记录

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `observed_at` | `DateField` |  |  |  | 观测日期 |  |
| `regime_name` | `CharField` |  |  |  | 当期 Regime |  |
| `pulse_strength` | `CharField` |  |  |  | Pulse 强弱 |  |
| `asset_weights` | `JSONField` |  |  | dict | 资产权重 |  |
| `risk_budget_pct` | `FloatField` |  |  |  | 风险预算 % |  |
| `recommended_sectors` | `JSONField` |  |  | list | 推荐板块 |  |
| `benefiting_styles` | `JSONField` |  |  | list | 受益风格 |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | False | 禁止用于决策 |  |
| `blocked_reason` | `TextField` |  |  |  | 阻断原因 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### RegimeEligibilityConfigModel

- 来源文件：`apps/regime/infrastructure/models.py`
- 数据表：`regime_eligibility_config`
- 说明：Regime 准入矩阵配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `id` | `BigAutoField` |  |  |  |  |  |
| `asset_class` | `CharField` |  |  |  | 资产类别 |  |
| `regime` | `CharField` |  |  |  | Recovery/Overheat/Stagflation/Deflation |  |
| `eligibility` | `CharField` |  |  |  | 准入状态 |  |
| `weight` | `FloatField` |  |  | 1.0 | 该资产在该 Regime 下的权重 |  |
| `adjustment_factor` | `FloatField` |  |  | 1.0 | 额外的权重调整系数 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `notes` | `TextField` |  |  |  | 备注 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### RegimeIndicatorThreshold

- 来源文件：`apps/regime/infrastructure/models.py`
- 数据表：`regime_regimeindicatorthreshold`
- 说明：指标阈值配置

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `config` | `ForeignKey` |  |  |  | 配置 | RegimeThresholdConfig |
| `indicator_code` | `CharField` |  |  |  | 指标代码 |  |
| `indicator_name` | `CharField` |  |  |  | 指标名称 |  |
| `level_low` | `FloatField` | 是 |  |  | 低水平阈值（如 PMI < 50 为收缩） |  |
| `level_high` | `FloatField` | 是 |  |  | 高水平阈值（如 PMI > 50 为扩张） |  |
| `description` | `TextField` |  |  |  | 说明 |  |

### RegimeLog

- 来源文件：`apps/regime/infrastructure/models.py`
- 数据表：`regime_log`
- 说明：Regime 判定日志

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `observed_at` | `DateField` |  | 是 |  |  |  |
| `growth_momentum_z` | `FloatField` |  |  |  |  |  |
| `inflation_momentum_z` | `FloatField` |  |  |  |  |  |
| `distribution` | `JSONField` |  |  |  |  |  |
| `dominant_regime` | `CharField` |  |  |  |  |  |
| `confidence` | `FloatField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### RegimeThresholdConfig

- 来源文件：`apps/regime/infrastructure/models.py`
- 数据表：`regime_regimethresholdconfig`
- 说明：Regime 阈值配置（主表）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | `CharField` |  |  |  | 配置名称 |  |
| `is_active` | `BooleanField` |  |  | True | 是否激活 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### RegimeTrendIndicator

- 来源文件：`apps/regime/infrastructure/models.py`
- 数据表：`regime_regimetrendindicator`
- 说明：趋势指标配置

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `config` | `ForeignKey` |  |  |  | 配置 | RegimeThresholdConfig |
| `indicator_code` | `CharField` |  |  |  | 指标代码 |  |
| `momentum_period` | `IntegerField` |  |  | 3 | 动量计算周期（月） |  |
| `trend_weight` | `FloatField` |  |  | 0.3 | 趋势权重（0-1），用于调整 Regime 判定 |  |

### RiskParameterConfigModel

- 来源文件：`apps/regime/infrastructure/models.py`
- 数据表：`risk_parameter_config`
- 说明：风险参数配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `key` | `CharField` |  | 是 |  | 如 position_p1, adjustment_recovery 等 |  |
| `name` | `CharField` |  |  |  | 参数名称 |  |
| `parameter_type` | `CharField` |  |  |  | 参数类型 |  |
| `value_float` | `FloatField` | 是 |  |  | 数值 |  |
| `value_string` | `CharField` |  |  |  | 字符串值 |  |
| `value_json` | `JSONField` | 是 |  |  | JSON 值 |  |
| `policy_level` | `CharField` |  |  |  | 如 P0, P1, P2, P3，留空表示全部适用 |  |
| `regime` | `CharField` |  |  |  | 留空表示全部适用 |  |
| `asset_class` | `CharField` |  |  |  | 留空表示全部适用 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `description` | `TextField` |  |  |  | 描述 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |


## research

### EvidenceAppendOnlyModel

- 来源文件：`apps/research/infrastructure/evidence_models.py`
- 抽象模型：是
- 说明：Permit only one exact insert claimed by the private repository token.

### EvidenceEnvelopeModel

- 来源文件：`apps/research/infrastructure/evidence_models.py`
- 数据表：`research_evidence_envelope`
- 说明：One immutable Evidence Envelope winner for an exact output version.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `output_owner` | `CharField` |  |  |  |  |  |
| `output_artifact_type` | `CharField` |  |  |  |  |  |
| `output_artifact_id` | `CharField` |  |  |  |  |  |
| `output_artifact_version` | `CharField` |  |  |  |  |  |
| `output_artifact_hash` | `CharField` |  |  |  |  |  |
| `operator_spec_id` | `CharField` |  |  |  |  |  |
| `operator_spec_version` | `CharField` |  |  |  |  |  |
| `operator_spec_hash` | `CharField` |  |  |  |  |  |
| `claim_kind` | `CharField` |  |  |  |  |  |
| `method_kind` | `CharField` |  |  |  |  |  |
| `research_family` | `CharField` |  |  |  |  |  |
| `governance_state` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `evaluated_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  |  |  |  |
| `must_not_execute` | `BooleanField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### EvidenceOperatorSpecModel

- 来源文件：`apps/research/infrastructure/evidence_models.py`
- 数据表：`research_evidence_operator_spec`
- 说明：One immutable canonical operator specification version.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `operator_id` | `CharField` |  |  |  |  |  |
| `operator_version` | `CharField` |  |  |  |  |  |
| `research_family` | `CharField` |  |  |  |  |  |
| `output_artifact_type` | `CharField` |  |  |  |  |  |
| `claim_kind` | `CharField` |  |  |  |  |  |
| `method_kind` | `CharField` |  |  |  |  |  |
| `activated_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### EvidenceScopeSourceV1Model

- 来源文件：`apps/research/infrastructure/evidence_models.py`
- 数据表：`research_evidence_scope_source_v1`
- 说明：Zero-seed append-only projection for the dormant scope-source contract.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `source_id` | `CharField` |  |  |  |  |  |
| `source_version` | `CharField` |  |  |  |  |  |
| `owner_id` | `CharField` |  |  |  |  |  |
| `tenant_id` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `actor_id` | `CharField` |  |  |  |  |  |
| `artifact_owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `artifact_id` | `CharField` |  |  |  |  |  |
| `artifact_version` | `CharField` |  |  |  |  |  |
| `artifact_content_hash` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `root_claim_hash` | `CharField` | 是 |  |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 |  |  |  |  |
| `predecessor` | `OneToOneField` | 是 |  |  | self | self |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `source_owner` | `CharField` |  |  |  |  |  |
| `source_artifact_type` | `CharField` |  |  |  |  |  |
| `source_schema` | `CharField` |  |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `must_not_execute` | `BooleanField` |  |  |  |  |  |
| `execution_allowed` | `BooleanField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### EvidenceScopeSourceV1ObservationModel

- 来源文件：`apps/research/infrastructure/evidence_models.py`
- 数据表：`research_evidence_scope_source_v1_observation`
- 说明：Zero-seed append-only storage for one owner/tenant observation DTO.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `observation_id` | `CharField` |  |  |  |  |  |
| `observation_version` | `CharField` |  |  |  |  |  |
| `owner_id` | `CharField` |  |  |  |  |  |
| `tenant_id` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `actor_id` | `CharField` |  |  |  |  |  |
| `artifact_owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `artifact_id` | `CharField` |  |  |  |  |  |
| `artifact_version` | `CharField` |  |  |  |  |  |
| `artifact_content_hash` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |

### EvidenceTrackRecordModel

- 来源文件：`apps/research/infrastructure/evidence_models.py`
- 数据表：`research_evidence_track_record`
- 说明：One immutable version-specific Track Record snapshot.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot_id` | `CharField` |  |  |  |  |  |
| `snapshot_version` | `CharField` |  |  |  |  |  |
| `artifact_owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `artifact_id` | `CharField` |  |  |  |  |  |
| `artifact_version` | `CharField` |  |  |  |  |  |
| `artifact_hash` | `CharField` |  |  |  |  |  |
| `target` | `CharField` |  |  |  |  |  |
| `horizon` | `CharField` |  |  |  |  |  |
| `sample_policy_id` | `CharField` |  |  |  |  |  |
| `sample_policy_version` | `CharField` |  |  |  |  |  |
| `evaluated_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### ActivatedEvidenceOperatorSpecModel

- 来源文件：`apps/research/infrastructure/evidence_operator_spec_lifecycle_models.py`
- 数据表：`research_activated_evidence_operator_spec`
- 说明：One immutable, externally approved operator spec activation version.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `approval` | `OneToOneField` |  |  |  |  | EvidenceOperatorSpecApprovalReceiptModel |
| `operator_id` | `CharField` |  |  |  |  |  |
| `operator_version` | `CharField` |  |  |  |  |  |
| `research_family` | `CharField` |  |  |  |  |  |
| `output_artifact_type` | `CharField` |  |  |  |  |  |
| `claim_kind` | `CharField` |  |  |  |  |  |
| `method_kind` | `CharField` |  |  |  |  |  |
| `definition_hash` | `CharField` |  | 是 |  |  |  |
| `supersedes_activation_hash` | `CharField` | 是 |  |  |  |  |
| `activated_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### EvidenceOperatorSpecApprovalReceiptModel

- 来源文件：`apps/research/infrastructure/evidence_operator_spec_lifecycle_models.py`
- 数据表：`research_evidence_operator_spec_approval`
- 说明：Research's immutable copy of one external-owner approval receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `approval_id` | `CharField` |  |  |  |  |  |
| `approval_version` | `CharField` |  |  |  |  |  |
| `owner_record_id` | `CharField` |  |  |  |  |  |
| `owner_record_version` | `CharField` |  |  |  |  |  |
| `owner_record_hash` | `CharField` |  |  |  |  |  |
| `operator_id` | `CharField` |  |  |  |  |  |
| `operator_version` | `CharField` |  |  |  |  |  |
| `definition_hash` | `CharField` |  |  |  |  |  |
| `supersedes_activation_hash` | `CharField` | 是 |  |  |  |  |
| `approved_by` | `CharField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `receipt_content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### DatasetSplitSpec

- 来源文件：`apps/research/infrastructure/models.py`
- 数据表：`research_dataset_split_spec`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `trial` | `OneToOneField` |  |  |  |  | ExperimentTrial |
| `training_window` | `JSONField` |  |  | dict |  |  |
| `validation_window` | `JSONField` |  |  | dict |  |  |
| `out_of_sample_window` | `JSONField` |  |  | dict |  |  |
| `walk_forward_windows` | `JSONField` |  |  | list |  |  |
| `embargo_days` | `PositiveIntegerField` |  |  | 0 |  |  |

### ExperimentTrial

- 来源文件：`apps/research/infrastructure/models.py`
- 数据表：`research_experiment_trial`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `trial_id` | `CharField` |  |  |  |  |  |
| `experiment` | `ForeignKey` |  |  |  |  | ResearchExperiment |
| `family` | `ForeignKey` |  |  |  |  | MultipleTestFamily |
| `status` | `CharField` |  |  | draft |  |  |
| `pit_manifest_id` | `CharField` |  |  |  |  |  |
| `backtest_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `backtest_trust_status` | `CharField` |  |  | exploratory |  |  |
| `code_commit` | `CharField` |  |  |  |  |  |
| `dependency_lock_hash` | `CharField` |  |  |  |  |  |
| `engine_version` | `CharField` |  |  |  |  |  |
| `parameters` | `JSONField` |  |  | dict |  |  |
| `parameter_hash` | `CharField` |  |  |  |  |  |
| `random_seed` | `BigIntegerField` |  |  |  |  |  |
| `benchmark_spec` | `JSONField` |  |  | dict |  |  |
| `cost_spec` | `JSONField` |  |  | dict |  |  |
| `slippage_spec` | `JSONField` |  |  | dict |  |  |
| `universe_spec` | `JSONField` |  |  | dict |  |  |
| `started_at` | `DateTimeField` | 是 |  |  |  |  |
| `completed_at` | `DateTimeField` | 是 |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### MetricObservation

- 来源文件：`apps/research/infrastructure/models.py`
- 数据表：`research_metric_observation`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `trial` | `ForeignKey` |  |  |  |  | ExperimentTrial |
| `metric_name` | `CharField` |  |  |  |  |  |
| `value` | `FloatField` |  |  |  |  |  |
| `sample_count` | `PositiveIntegerField` |  |  |  |  |  |
| `confidence_interval_low` | `FloatField` | 是 |  |  |  |  |
| `confidence_interval_high` | `FloatField` | 是 |  |  |  |  |
| `p_value` | `FloatField` | 是 |  |  |  |  |
| `q_value` | `FloatField` | 是 |  |  |  |  |
| `metadata` | `JSONField` |  |  | dict |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### MultipleTestFamily

- 来源文件：`apps/research/infrastructure/models.py`
- 数据表：`research_multiple_test_family`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `family_id` | `CharField` |  |  |  |  |  |
| `experiment` | `ForeignKey` |  |  |  |  | ResearchExperiment |
| `planned_trial_count` | `PositiveIntegerField` |  |  |  |  |  |
| `fdr_threshold` | `FloatField` |  |  | 0.05 |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### PromotionDecision

- 来源文件：`apps/research/infrastructure/models.py`
- 数据表：`research_promotion_decision`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `decision_id` | `CharField` |  |  |  |  |  |
| `trial` | `OneToOneField` |  |  |  |  | ExperimentTrial |
| `decision` | `CharField` |  |  |  |  |  |
| `evidence` | `JSONField` |  |  | dict |  |  |
| `decided_at` | `DateTimeField` |  |  |  |  |  |

### ResearchExperiment

- 来源文件：`apps/research/infrastructure/models.py`
- 数据表：`research_experiment`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `experiment_id` | `CharField` |  |  |  |  |  |
| `question` | `TextField` |  |  |  |  |  |
| `hypothesis` | `TextField` |  |  |  |  |  |
| `owner` | `ForeignKey` | 是 |  |  |  | settings.AUTH_USER_MODEL |
| `status` | `CharField` |  |  | draft |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### R1ForecastPromotionDecisionBundleModel

- 来源文件：`apps/research/infrastructure/r1_forecast_promotion_models.py`
- 数据表：`research_r1_promotion_decision_bundle`
- 说明：Atomic exact decision plus owner-receipt bundle.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `receipt` | `OneToOneField` |  |  |  |  | R1PromotionDecisionReceiptModel |
| `policy` | `ForeignKey` |  |  |  |  | R1ForecastPromotionPolicyModel |
| `equity_result` | `ForeignKey` |  |  |  |  | ForecastBaselineTrialResultModel |
| `decision_id` | `CharField` |  |  |  |  |  |
| `decision_version` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `purpose` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `outcome` | `CharField` |  |  |  |  |  |
| `decided_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `decision_content_hash` | `CharField` |  | 是 |  |  |  |
| `bundle_content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R1ForecastPromotionPolicyModel

- 来源文件：`apps/research/infrastructure/r1_forecast_promotion_models.py`
- 数据表：`research_r1_promotion_policy`
- 说明：Canonical Research policy bound to one semantic promotion scope.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `purpose` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `subject_code` | `CharField` |  |  |  |  |  |
| `industry_code` | `CharField` |  |  |  |  |  |
| `candidate_scenario` | `CharField` |  |  |  |  |  |
| `horizon_quarters` | `PositiveSmallIntegerField` |  |  |  |  |  |
| `calendar_schedule_hash` | `CharField` |  |  |  |  |  |
| `metric_codes` | `JSONField` |  |  |  |  |  |
| `approved_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `active_from` | `DateTimeField` |  |  |  |  |  |
| `active_until` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R1PromotionAppendOnlyModel

- 来源文件：`apps/research/infrastructure/r1_forecast_promotion_models.py`
- 抽象模型：是
- 说明：Permit only database-assigned primary-key inserts.

### R1PromotionDecisionReceiptModel

- 来源文件：`apps/research/infrastructure/r1_forecast_promotion_models.py`
- 数据表：`research_r1_promotion_decision_receipt`
- 说明：Stable Research receipt claim for one output decision identity.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `decision_id` | `CharField` |  |  |  |  |  |
| `decision_version` | `CharField` |  |  |  |  |  |
| `policy` | `ForeignKey` |  |  |  |  | R1ForecastPromotionPolicyModel |
| `equity_result` | `ForeignKey` |  |  |  |  | ForecastBaselineTrialResultModel |
| `policy_content_hash` | `CharField` |  |  |  |  |  |
| `result_content_hash` | `CharField` |  |  |  |  |  |
| `equity_result_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `equity_result_record_hash` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `purpose` | `CharField` |  |  |  |  |  |
| `decided_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `decision_valid_until` | `DateTimeField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R1PromotionLifecycleEventBundleModel

- 来源文件：`apps/research/infrastructure/r1_forecast_promotion_models.py`
- 数据表：`research_r1_promotion_lifecycle_bundle`
- 说明：Immutable scope-local event/hash-chain bundle.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `receipt` | `OneToOneField` |  |  |  |  | R1PromotionLifecycleReceiptModel |
| `decision` | `ForeignKey` |  |  |  |  | R1ForecastPromotionDecisionBundleModel |
| `rollback_target` | `ForeignKey` | 是 |  |  |  | R1ForecastPromotionDecisionBundleModel |
| `previous_event` | `ForeignKey` | 是 |  |  | self | self |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `stream_id` | `CharField` |  |  |  |  |  |
| `event_type` | `CharField` |  |  |  |  |  |
| `sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `reason_codes` | `JSONField` |  |  |  |  |  |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `previous_event_hash` | `CharField` |  |  |  |  |  |
| `event_content_hash` | `CharField` |  | 是 |  |  |  |
| `bundle_content_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R1PromotionLifecycleReceiptModel

- 来源文件：`apps/research/infrastructure/r1_forecast_promotion_models.py`
- 数据表：`research_r1_promotion_lifecycle_receipt`
- 说明：Stable owner authorization and server event-clock claim.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `authorization_id` | `CharField` |  |  |  |  |  |
| `authorization_version` | `CharField` |  |  |  |  |  |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `decision` | `ForeignKey` |  |  |  |  | R1ForecastPromotionDecisionBundleModel |
| `rollback_target` | `ForeignKey` | 是 |  |  |  | R1ForecastPromotionDecisionBundleModel |
| `owner` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `purpose` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `event_type` | `CharField` |  |  |  |  |  |
| `reason_codes` | `JSONField` |  |  |  |  |  |
| `reason_hash` | `CharField` |  |  |  |  |  |
| `authorization_issued_at` | `DateTimeField` |  |  |  |  |  |
| `authorization_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `authorization_valid_until` | `DateTimeField` |  |  |  |  |  |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `event_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `authorization_content_hash` | `CharField` |  | 是 |  |  |  |
| `evidence_content_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R1ForecastTrialEvidenceLedgerModel

- 来源文件：`apps/research/infrastructure/r1_forecast_trial_evidence_models.py`
- 数据表：`research_r1_forecast_trial_evidence`
- 说明：One immutable Research-owned preregistration receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `evidence_id` | `CharField` |  |  |  |  |  |
| `evidence_version` | `CharField` |  |  |  |  |  |
| `definition_id` | `CharField` |  |  |  |  |  |
| `definition_version` | `CharField` |  |  |  |  |  |
| `definition_content_hash` | `CharField` |  |  |  |  |  |
| `baseline_spec_id` | `CharField` |  |  |  |  |  |
| `baseline_spec_version` | `CharField` |  |  |  |  |  |
| `baseline_spec_content_hash` | `CharField` |  |  |  |  |  |
| `baseline_artifact_id` | `CharField` |  |  |  |  |  |
| `baseline_artifact_version` | `CharField` |  |  |  |  |  |
| `baseline_artifact_content_hash` | `CharField` |  |  |  |  |  |
| `baseline_spec_approved_at` | `DateTimeField` |  |  |  |  |  |
| `activated_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `forecast_origin_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R2MarketStructurePromotionDecisionModel

- 来源文件：`apps/research/infrastructure/r2_market_structure_promotion_models.py`
- 数据表：`research_r2_ms_promotion_decision`
- 说明：Immutable exact promotion decision graph.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `decision_id` | `CharField` |  |  |  |  |  |
| `decision_version` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_content_hash` | `CharField` |  |  |  |  |  |
| `evidence_key` | `CharField` |  |  |  |  |  |
| `evidence_version` | `PositiveIntegerField` |  |  |  |  |  |
| `evidence_content_hash` | `CharField` |  |  |  |  |  |
| `authorization_id` | `CharField` |  |  |  |  |  |
| `authorization_version` | `CharField` |  |  |  |  |  |
| `authorization_content_hash` | `CharField` |  | 是 |  |  |  |
| `outcome` | `CharField` |  |  |  |  |  |
| `decided_at` | `DateTimeField` |  |  |  |  |  |
| `semantic_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_receipt_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `TextField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `structure_description_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### R2MarketStructurePromotionLifecycleEventModel

- 来源文件：`apps/research/infrastructure/r2_market_structure_promotion_models.py`
- 数据表：`research_r2_ms_promotion_lifecycle`
- 说明：Immutable scope-local lifecycle event and authorization graph.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `stream_id` | `CharField` |  |  |  |  |  |
| `sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `event_type` | `CharField` |  |  |  |  |  |
| `decision_id` | `CharField` |  |  |  |  |  |
| `decision_version` | `CharField` |  |  |  |  |  |
| `decision_content_hash` | `CharField` |  |  |  |  |  |
| `rollback_target_id` | `CharField` |  |  |  |  |  |
| `rollback_target_version` | `CharField` |  |  |  |  |  |
| `rollback_target_content_hash` | `CharField` |  |  |  |  |  |
| `authorization_id` | `CharField` |  |  |  |  |  |
| `authorization_version` | `CharField` |  |  |  |  |  |
| `authorization_content_hash` | `CharField` |  | 是 |  |  |  |
| `previous_event_hash` | `CharField` |  |  |  |  |  |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `semantic_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_receipt_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `TextField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |

### R2MarketStructurePromotionPolicyModel

- 来源文件：`apps/research/infrastructure/r2_market_structure_promotion_models.py`
- 数据表：`research_r2_ms_promotion_policy`
- 说明：Immutable owner-approved policy receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `registered_at` | `DateTimeField` |  |  |  |  |  |
| `active_from` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_receipt_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `TextField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `structure_description_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### R2PromotionAppendOnlyModel

- 来源文件：`apps/research/infrastructure/r2_market_structure_promotion_models.py`
- 抽象模型：是
- 说明：Permit only repository-claimed inserts.

### R2ExplanatoryTrialAssessmentLedgerModel

- 来源文件：`apps/research/infrastructure/r2_market_structure_trial_monitoring_models.py`
- 数据表：`research_r2_explanatory_trial_assessment`
- 说明：Complete two-cycle trial owner graph and derived assessment.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `assessment_id` | `CharField` |  |  |  |  |  |
| `assessment_version` | `CharField` |  |  |  |  |  |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_hash` | `CharField` |  |  |  |  |  |
| `taxonomy_publication_id` | `CharField` |  |  |  |  |  |
| `taxonomy_publication_version` | `CharField` |  |  |  |  |  |
| `taxonomy_publication_hash` | `CharField` |  |  |  |  |  |
| `calendar_publication_id` | `CharField` |  |  |  |  |  |
| `calendar_publication_version` | `CharField` |  |  |  |  |  |
| `calendar_publication_hash` | `CharField` |  |  |  |  |  |
| `cycle_one_hash` | `CharField` |  |  |  |  |  |
| `cycle_two_hash` | `CharField` |  |  |  |  |  |
| `audit_outcome_id` | `CharField` |  |  |  |  |  |
| `audit_outcome_version` | `CharField` |  |  |  |  |  |
| `audit_outcome_hash` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `assessed_at` | `DateTimeField` |  |  |  |  |  |
| `owner_valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_as_predictive_signal` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `is_attested_ready` | `BooleanField` |  |  | False |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R2MonitoringAssessmentLedgerModel

- 来源文件：`apps/research/infrastructure/r2_market_structure_trial_monitoring_models.py`
- 数据表：`research_r2_monitoring_assessment`
- 说明：Manual-review-only assessment sealing one exact fact set.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `trial_assessment` | `ForeignKey` |  |  |  |  | R2ExplanatoryTrialAssessmentLedgerModel |
| `assessment_id` | `CharField` |  |  |  |  |  |
| `assessment_version` | `CharField` |  |  |  |  |  |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_hash` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `assessed_at` | `DateTimeField` |  |  |  |  |  |
| `owner_valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `fact_count` | `PositiveIntegerField` |  |  |  |  |  |
| `fact_manifest_hash` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `retirement_review_required` | `BooleanField` |  |  | False |  |  |
| `automatic_retirement` | `BooleanField` |  |  | False |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_as_predictive_signal` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R2MonitoringAuditSnapshotModel

- 来源文件：`apps/research/infrastructure/r2_market_structure_trial_monitoring_models.py`
- 数据表：`research_r2_monitoring_audit_snapshot`
- 说明：Immutable manifest for signed, stable internal-audit pagination.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot_id` | `CharField` |  |  |  |  |  |
| `snapshot_version` | `CharField` |  |  |  |  |  |
| `as_of` | `DateTimeField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `entry_count` | `PositiveIntegerField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `internal_audit_only` | `BooleanField` |  |  | True |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R2MonitoringObservationLedgerModel

- 来源文件：`apps/research/infrastructure/r2_market_structure_trial_monitoring_models.py`
- 数据表：`research_r2_monitoring_observation`
- 说明：Assessment-scoped immutable owner raw fact.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `monitoring_assessment` | `ForeignKey` |  |  |  |  | R2MonitoringAssessmentLedgerModel |
| `trial_assessment` | `ForeignKey` |  |  |  |  | R2ExplanatoryTrialAssessmentLedgerModel |
| `fact_id` | `CharField` |  |  |  |  |  |
| `fact_version` | `CharField` |  |  |  |  |  |
| `fact_content_hash` | `CharField` |  |  |  |  |  |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_hash` | `CharField` |  |  |  |  |  |
| `period_id` | `CharField` |  |  |  |  |  |
| `period_start` | `DateTimeField` |  |  |  |  |  |
| `period_end` | `DateTimeField` |  |  |  |  |  |
| `source_owner` | `CharField` |  |  |  |  |  |
| `owner_observed_at` | `DateTimeField` |  |  |  |  |  |
| `owner_available_at` | `DateTimeField` |  |  |  |  |  |
| `owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `owner_valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `row_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_as_predictive_signal` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R2TrialMonitoringAppendOnlyModel

- 来源文件：`apps/research/infrastructure/r2_market_structure_trial_monitoring_models.py`
- 抽象模型：是
- 说明：Permit only repository-claimed first inserts.

### R2MarketStructureTrialPolicyLedgerModel

- 来源文件：`apps/research/infrastructure/r2_market_structure_trial_policy_models.py`
- 数据表：`research_r2_trial_policy_registry`
- 说明：Complete canonical Phase-A policy with a trusted ledger knowledge time.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `taxonomy_publication_id` | `CharField` |  |  |  |  |  |
| `taxonomy_publication_version` | `CharField` |  |  |  |  |  |
| `taxonomy_publication_hash` | `CharField` |  |  |  |  |  |
| `taxonomy_artifact_hash` | `CharField` |  |  |  |  |  |
| `calendar_publication_id` | `CharField` |  |  |  |  |  |
| `calendar_publication_version` | `CharField` |  |  |  |  |  |
| `calendar_publication_hash` | `CharField` |  |  |  |  |  |
| `calendar_artifact_hash` | `CharField` |  |  |  |  |  |
| `policy_registered_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `selection_as_of` | `DateTimeField` |  |  |  |  |  |
| `active_from` | `DateTimeField` |  |  |  |  |  |
| `active_until` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `policy_content_hash` | `CharField` |  | 是 |  |  |  |
| `record_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R3MacroFactorRunnerSpecModel

- 来源文件：`apps/research/infrastructure/r3_macro_factor_runner_spec_models.py`
- 数据表：`research_r3_macro_factor_runner_spec`
- 说明：Canonical complete runner spec and Research server knowledge seal.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `spec_id` | `CharField` |  |  |  |  |  |
| `spec_version` | `PositiveIntegerField` |  |  |  |  |  |
| `factor_version` | `CharField` |  |  |  |  |  |
| `target_code` | `CharField` |  |  |  |  |  |
| `expected_manifest_content_hash` | `CharField` |  |  |  |  |  |
| `spec_registered_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `first_selection_at` | `DateTimeField` |  |  |  |  |  |
| `last_evaluation_at` | `DateTimeField` |  |  |  |  |  |
| `calculated_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `spec_content_hash` | `CharField` |  | 是 |  |  |  |
| `record_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R4PromotionAppendOnlyModel

- 来源文件：`apps/research/infrastructure/r4_promotion_models.py`
- 抽象模型：是
- 说明：Permit only database-assigned primary-key inserts.

### R4PromotionDecisionBundleModel

- 来源文件：`apps/research/infrastructure/r4_promotion_models.py`
- 数据表：`research_r4_promotion_decision_bundle`
- 说明：Atomic R4 decision plus its preclaimed Research receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `receipt` | `OneToOneField` |  |  |  |  | R4PromotionDecisionReceiptModel |
| `policy` | `ForeignKey` |  |  |  |  | R4PromotionPolicyModel |
| `decision_id` | `CharField` |  |  |  |  |  |
| `decision_version` | `CharField` |  |  |  |  |  |
| `trial_id` | `CharField` |  |  |  |  |  |
| `trial_version` | `CharField` |  |  |  |  |  |
| `trial_content_hash` | `CharField` |  |  |  |  |  |
| `policy_content_hash` | `CharField` |  |  |  |  |  |
| `portfolio_record_id` | `CharField` |  |  |  |  |  |
| `portfolio_record_hash` | `CharField` |  |  |  |  |  |
| `portfolio_owner_record_key` | `CharField` |  |  |  |  |  |
| `current_r3_content_hash` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `purpose` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `outcome` | `CharField` |  |  |  |  |  |
| `decided_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `decision_content_hash` | `CharField` |  | 是 |  |  |  |
| `bundle_content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R4PromotionDecisionReceiptModel

- 来源文件：`apps/research/infrastructure/r4_promotion_models.py`
- 数据表：`research_r4_promotion_decision_receipt`
- 说明：Stable server claim for one exact R4 decision identity.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `decision_id` | `CharField` |  |  |  |  |  |
| `decision_version` | `CharField` |  |  |  |  |  |
| `trial_id` | `CharField` |  |  |  |  |  |
| `trial_version` | `CharField` |  |  |  |  |  |
| `policy` | `ForeignKey` |  |  |  |  | R4PromotionPolicyModel |
| `policy_content_hash` | `CharField` |  |  |  |  |  |
| `portfolio_record_id` | `CharField` |  |  |  |  |  |
| `portfolio_record_hash` | `CharField` |  |  |  |  |  |
| `portfolio_owner_record_key` | `CharField` |  |  |  |  |  |
| `portfolio_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `current_r3_content_hash` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `purpose` | `CharField` |  |  |  |  |  |
| `decided_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `decision_valid_until` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R4PromotionLifecycleAuthorizationReceiptModel

- 来源文件：`apps/research/infrastructure/r4_promotion_models.py`
- 数据表：`research_r4_promotion_lifecycle_auth_receipt`
- 说明：Stable Research authorization and server event-clock receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `authorization_id` | `CharField` |  |  |  |  |  |
| `authorization_version` | `CharField` |  |  |  |  |  |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `decision` | `ForeignKey` |  |  |  |  | R4PromotionDecisionBundleModel |
| `rollback_target` | `ForeignKey` | 是 |  |  |  | R4PromotionDecisionBundleModel |
| `decision_content_hash` | `CharField` |  |  |  |  |  |
| `rollback_target_content_hash` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `purpose` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `event_type` | `CharField` |  |  |  |  |  |
| `reason_codes` | `JSONField` |  |  |  |  |  |
| `reason_hash` | `CharField` |  |  |  |  |  |
| `authorization_issued_at` | `DateTimeField` |  |  |  |  |  |
| `authorization_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `authorization_valid_until` | `DateTimeField` |  |  |  |  |  |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `event_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `authorization_content_hash` | `CharField` |  | 是 |  |  |  |
| `evidence_content_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R4PromotionLifecycleEventModel

- 来源文件：`apps/research/infrastructure/r4_promotion_models.py`
- 数据表：`research_r4_promotion_lifecycle_event`
- 说明：Immutable scope-local R4 lifecycle event and hash-chain bundle.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `receipt` | `OneToOneField` |  |  |  |  | R4PromotionLifecycleAuthorizationReceiptModel |
| `decision` | `ForeignKey` |  |  |  |  | R4PromotionDecisionBundleModel |
| `rollback_target` | `ForeignKey` | 是 |  |  |  | R4PromotionDecisionBundleModel |
| `previous_event` | `ForeignKey` | 是 |  |  | self | self |
| `decision_content_hash` | `CharField` |  |  |  |  |  |
| `rollback_target_content_hash` | `CharField` |  |  |  |  |  |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `stream_id` | `CharField` |  |  |  |  |  |
| `event_type` | `CharField` |  |  |  |  |  |
| `sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `reason_codes` | `JSONField` |  |  |  |  |  |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `previous_event_hash` | `CharField` |  |  |  |  |  |
| `event_content_hash` | `CharField` |  | 是 |  |  |  |
| `bundle_content_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R4PromotionPolicyModel

- 来源文件：`apps/research/infrastructure/r4_promotion_models.py`
- 数据表：`research_r4_promotion_policy`
- 说明：Canonical pre-registered Research R4 promotion policy.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `purpose` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `study_family_id` | `CharField` |  |  |  |  |  |
| `target_method` | `CharField` |  |  |  |  |  |
| `universe_policy_id` | `CharField` |  |  |  |  |  |
| `factor_policy_id` | `CharField` |  |  |  |  |  |
| `split_policy_id` | `CharField` |  |  |  |  |  |
| `cost_semantics_id` | `CharField` |  |  |  |  |  |
| `approved_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `active_from` | `DateTimeField` |  |  |  |  |  |
| `active_until` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R4MonitoringAppendOnlyModel

- 来源文件：`apps/research/infrastructure/r4_promotion_monitoring_models.py`
- 抽象模型：是
- 说明：Permit only one repository-claimed database-keyed insert.

### R4MonitoringAssessmentLedgerModel

- 来源文件：`apps/research/infrastructure/r4_promotion_monitoring_models.py`
- 数据表：`research_r4_monitoring_assessment`
- 说明：Immutable assessment plus its complete exact owner graph.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `active_decision` | `ForeignKey` |  |  |  |  | R4PromotionDecisionBundleModel |
| `assessment_id` | `CharField` |  | 是 |  |  |  |
| `active_decision_stable_id` | `CharField` |  |  |  |  |  |
| `active_decision_version` | `CharField` |  |  |  |  |  |
| `active_decision_hash` | `CharField` |  |  |  |  |  |
| `requested_policy_id` | `CharField` |  |  |  |  |  |
| `requested_policy_version` | `CharField` |  |  |  |  |  |
| `expected_policy_hash` | `CharField` |  |  |  |  |  |
| `policy_hash` | `CharField` |  |  |  |  |  |
| `period_calendar_id` | `CharField` |  |  |  |  |  |
| `period_calendar_version` | `CharField` |  |  |  |  |  |
| `period_calendar_hash` | `CharField` |  |  |  |  |  |
| `portfolio_record_content_hash` | `CharField` |  |  |  |  |  |
| `r3_attestation_content_hash` | `CharField` |  |  |  |  |  |
| `evaluated_at` | `DateTimeField` |  |  |  |  |  |
| `active_decision_owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `portfolio_owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `r3_owner_known_at` | `DateTimeField` |  |  |  |  |  |
| `policy_owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `calendar_owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `latest_observation_owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `observation_count` | `PositiveIntegerField` |  |  |  |  |  |
| `metric_result_count` | `PositiveIntegerField` |  |  |  |  |  |
| `observation_hashes` | `JSONField` |  |  |  |  |  |
| `blockers` | `JSONField` |  |  |  |  |  |
| `review_reason_codes` | `JSONField` |  |  |  |  |  |
| `active_decision_payload` | `JSONField` |  |  |  |  |  |
| `portfolio_result_payload` | `JSONField` |  |  |  |  |  |
| `r3_attestation_payload` | `JSONField` |  |  |  |  |  |
| `policy_payload` | `JSONField` |  |  |  |  |  |
| `period_calendar_payload` | `JSONField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `label_drift_detected` | `BooleanField` |  |  |  |  |  |
| `data_drift_detected` | `BooleanField` |  |  |  |  |  |
| `retirement_review_required` | `BooleanField` |  |  |  |  |  |
| `automatic_retirement` | `BooleanField` |  |  | False |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R4MonitoringAuditSnapshotModel

- 来源文件：`apps/research/infrastructure/r4_promotion_monitoring_models.py`
- 数据表：`research_r4_monitoring_audit_snapshot`
- 说明：Immutable manifest for stable signed internal-audit pagination.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot_id` | `CharField` |  |  |  |  |  |
| `snapshot_version` | `CharField` |  |  |  |  |  |
| `as_of` | `DateTimeField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `entry_count` | `PositiveIntegerField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `internal_audit_only` | `BooleanField` |  |  | True |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R4MonitoringObservationLedgerModel

- 来源文件：`apps/research/infrastructure/r4_promotion_monitoring_models.py`
- 数据表：`research_r4_monitoring_observation`
- 说明：Immutable canonical owner raw observation.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `active_decision` | `ForeignKey` |  |  |  |  | R4PromotionDecisionBundleModel |
| `observation_id` | `CharField` |  |  |  |  |  |
| `observation_version` | `CharField` |  |  |  |  |  |
| `active_decision_stable_id` | `CharField` |  |  |  |  |  |
| `active_decision_version` | `CharField` |  |  |  |  |  |
| `active_decision_hash` | `CharField` |  |  |  |  |  |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_hash` | `CharField` |  |  |  |  |  |
| `period_calendar_id` | `CharField` |  |  |  |  |  |
| `period_calendar_version` | `CharField` |  |  |  |  |  |
| `period_calendar_hash` | `CharField` |  |  |  |  |  |
| `period_id` | `CharField` |  |  |  |  |  |
| `period_start` | `DateTimeField` |  |  |  |  |  |
| `period_end` | `DateTimeField` |  |  |  |  |  |
| `source_owner` | `CharField` |  |  |  |  |  |
| `portfolio_record_id` | `CharField` |  |  |  |  |  |
| `portfolio_record_hash` | `CharField` |  |  |  |  |  |
| `portfolio_record_content_hash` | `CharField` |  |  |  |  |  |
| `r3_attestation_content_hash` | `CharField` |  |  |  |  |  |
| `observed_at` | `DateTimeField` |  |  |  |  |  |
| `available_at` | `DateTimeField` |  |  |  |  |  |
| `owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `pit_manifest_id` | `CharField` |  |  |  |  |  |
| `pit_manifest_hash` | `CharField` |  |  |  |  |  |
| `evidence_ref` | `CharField` |  |  |  |  |  |
| `label_protocol_version` | `CharField` |  |  |  |  |  |
| `observed_label_set_hash` | `CharField` |  |  |  |  |  |
| `observed_data_schema_hash` | `CharField` |  |  |  |  |  |
| `metric_count` | `PositiveIntegerField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R4MonitoringCalendarLedgerModel

- 来源文件：`apps/research/infrastructure/r4_promotion_monitoring_owner_models.py`
- 数据表：`research_r4_monitoring_period_calendar`
- 说明：One immutable Research-owned canonical monitoring calendar.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `source_owner` | `CharField` |  |  |  |  |  |
| `calendar_id` | `CharField` |  |  |  |  |  |
| `calendar_version` | `CharField` |  |  |  |  |  |
| `definition_hash` | `CharField` |  |  |  |  |  |
| `source_receipt_id` | `CharField` |  |  |  |  |  |
| `source_receipt_version` | `CharField` |  |  |  |  |  |
| `source_receipt_hash` | `CharField` |  |  |  |  |  |
| `source_receipt_payload` | `JSONField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_from` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `entry_count` | `PositiveIntegerField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R4MonitoringPolicyLedgerModel

- 来源文件：`apps/research/infrastructure/r4_promotion_monitoring_owner_models.py`
- 数据表：`research_r4_monitoring_policy`
- 说明：One immutable Research-owned monitoring policy.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `active_decision_id` | `CharField` |  |  |  |  |  |
| `active_decision_version` | `CharField` |  |  |  |  |  |
| `active_decision_hash` | `CharField` |  |  |  |  |  |
| `definition_hash` | `CharField` |  |  |  |  |  |
| `source_receipt_id` | `CharField` |  |  |  |  |  |
| `source_receipt_version` | `CharField` |  |  |  |  |  |
| `source_receipt_hash` | `CharField` |  |  |  |  |  |
| `source_receipt_payload` | `JSONField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `active_from` | `DateTimeField` |  |  |  |  |  |
| `active_until` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R5MonitoringCalendarRegistryModel

- 来源文件：`apps/research/infrastructure/r5_monitoring_owner_models.py`
- 数据表：`research_r5_monitoring_calendar_registry`
- 说明：Immutable exact R5 monitoring calendar plus source receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `calendar_id` | `CharField` |  |  |  |  |  |
| `calendar_version` | `CharField` |  |  |  |  |  |
| `calendar_hash` | `CharField` |  | 是 |  |  |  |
| `definition_hash` | `CharField` |  | 是 |  |  |  |
| `source_receipt_id` | `CharField` |  |  |  |  |  |
| `source_receipt_version` | `CharField` |  |  |  |  |  |
| `source_receipt_hash` | `CharField` |  | 是 |  |  |  |
| `source_available_at` | `DateTimeField` |  |  |  |  |  |
| `source_valid_until` | `DateTimeField` |  |  |  |  |  |
| `calendar_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `calendar_valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `calendar_payload` | `JSONField` |  |  |  |  |  |
| `source_payload` | `JSONField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### R5MonitoringPolicyRegistryModel

- 来源文件：`apps/research/infrastructure/r5_monitoring_owner_models.py`
- 数据表：`research_r5_monitoring_policy_registry`
- 说明：Immutable exact R5 monitoring policy plus source receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_hash` | `CharField` |  | 是 |  |  |  |
| `definition_hash` | `CharField` |  | 是 |  |  |  |
| `source_receipt_id` | `CharField` |  |  |  |  |  |
| `source_receipt_version` | `CharField` |  |  |  |  |  |
| `source_receipt_hash` | `CharField` |  | 是 |  |  |  |
| `source_available_at` | `DateTimeField` |  |  |  |  |  |
| `source_valid_until` | `DateTimeField` |  |  |  |  |  |
| `policy_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `policy_valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `policy_payload` | `JSONField` |  |  |  |  |  |
| `source_payload` | `JSONField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### R5MonitoringAppendOnlyModel

- 来源文件：`apps/research/infrastructure/r5_relative_value_monitoring_models.py`
- 抽象模型：是
- 说明：Permit only one repository-claimed database-keyed insert.

### R5MonitoringAssessmentLedgerModel

- 来源文件：`apps/research/infrastructure/r5_relative_value_monitoring_models.py`
- 数据表：`research_r5_monitoring_assessment`
- 说明：Immutable assessment plus its complete exact owner graph.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `assessment_id` | `CharField` |  | 是 |  |  |  |
| `assessment_version` | `CharField` |  |  |  |  |  |
| `active_decision` | `ForeignKey` |  |  |  |  | R5PromotionDecisionBundleModel |
| `lifecycle_event` | `ForeignKey` |  |  |  |  | R5PromotionLifecycleEventModel |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_hash` | `CharField` |  |  |  |  |  |
| `active_decision_stable_id` | `CharField` |  |  |  |  |  |
| `active_decision_version` | `CharField` |  |  |  |  |  |
| `active_decision_hash` | `CharField` |  |  |  |  |  |
| `active_lifecycle_hash` | `CharField` |  |  |  |  |  |
| `fixed_income_result_id` | `CharField` |  |  |  |  |  |
| `fixed_income_result_version` | `CharField` |  |  |  |  |  |
| `fixed_income_result_hash` | `CharField` |  |  |  |  |  |
| `fixed_income_owner_seal_hash` | `CharField` |  |  |  |  |  |
| `requested_policy_id` | `CharField` |  |  |  |  |  |
| `requested_policy_version` | `CharField` |  |  |  |  |  |
| `expected_policy_hash` | `CharField` |  |  |  |  |  |
| `calendar_id` | `CharField` |  |  |  |  |  |
| `calendar_version` | `CharField` |  |  |  |  |  |
| `calendar_hash` | `CharField` |  |  |  |  |  |
| `evaluated_at` | `DateTimeField` |  |  |  |  |  |
| `active_owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `fixed_income_owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `policy_owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `calendar_owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `latest_fact_owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `fact_count` | `PositiveIntegerField` |  |  |  |  |  |
| `fact_hashes` | `JSONField` |  |  |  |  |  |
| `active_lifecycle_payload` | `JSONField` |  |  |  |  |  |
| `fixed_income_payload` | `JSONField` |  |  |  |  |  |
| `policy_payload` | `JSONField` |  |  |  |  |  |
| `calendar_payload` | `JSONField` |  |  |  |  |  |
| `assessment_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `automatic_retirement` | `BooleanField` |  |  | False |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R5MonitoringAuditSnapshotModel

- 来源文件：`apps/research/infrastructure/r5_relative_value_monitoring_models.py`
- 数据表：`research_r5_monitoring_audit_snapshot`
- 说明：Immutable manifest backing signed internal-audit cursors.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot_id` | `CharField` |  |  |  |  |  |
| `snapshot_version` | `CharField` |  |  |  |  |  |
| `as_of` | `DateTimeField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `entry_count` | `PositiveIntegerField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `internal_audit_only` | `BooleanField` |  |  | True |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R5MonitoringObservationLedgerModel

- 来源文件：`apps/research/infrastructure/r5_relative_value_monitoring_models.py`
- 数据表：`research_r5_monitoring_observation`
- 说明：Immutable assessment-scoped canonical Portfolio raw fact.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `assessment` | `ForeignKey` |  |  |  |  | R5MonitoringAssessmentLedgerModel |
| `active_decision` | `ForeignKey` |  |  |  |  | R5PromotionDecisionBundleModel |
| `lifecycle_event` | `ForeignKey` |  |  |  |  | R5PromotionLifecycleEventModel |
| `fact_id` | `CharField` |  |  |  |  |  |
| `fact_version` | `CharField` |  |  |  |  |  |
| `domain_fact_hash` | `CharField` |  |  |  |  |  |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_hash` | `CharField` |  |  |  |  |  |
| `target_hash` | `CharField` |  |  |  |  |  |
| `calendar_id` | `CharField` |  |  |  |  |  |
| `calendar_version` | `CharField` |  |  |  |  |  |
| `calendar_hash` | `CharField` |  |  |  |  |  |
| `period_id` | `CharField` |  |  |  |  |  |
| `period_start` | `DateTimeField` |  |  |  |  |  |
| `period_end` | `DateTimeField` |  |  |  |  |  |
| `source_owner` | `CharField` |  |  |  |  |  |
| `source_owner_id` | `CharField` |  |  |  |  |  |
| `source_owner_version` | `CharField` |  |  |  |  |  |
| `source_owner_hash` | `CharField` |  |  |  |  |  |
| `source_observed_at` | `DateTimeField` |  |  |  |  |  |
| `observed_at` | `DateTimeField` |  |  |  |  |  |
| `available_at` | `DateTimeField` |  |  |  |  |  |
| `owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `observed_label_hash` | `CharField` |  |  |  |  |  |
| `observed_data_schema_hash` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R5PromotionAppendOnlyModel

- 来源文件：`apps/research/infrastructure/r5_relative_value_promotion_models.py`
- 抽象模型：是
- 说明：Permit only claimed inserts with database-assigned primary keys.

### R5PromotionArtifactModel

- 来源文件：`apps/research/infrastructure/r5_relative_value_promotion_models.py`
- 数据表：`research_r5_promotion_artifact`
- 说明：Typed immutable ledger shared only by exact policy and trial artifacts.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `artifact_kind` | `CharField` |  |  |  |  |  |
| `stable_id` | `CharField` |  |  |  |  |  |
| `version` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `purpose` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `semantic_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `active_from` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_receipt_hash` | `CharField` |  | 是 |  |  |  |
| `command_hash` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### R5PromotionDecisionAuthorizationModel

- 来源文件：`apps/research/infrastructure/r5_relative_value_promotion_models.py`
- 数据表：`research_r5_promotion_decision_auth`
- 说明：Exact Research authorization receipt persisted with its child decision.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `authorization_id` | `CharField` |  |  |  |  |  |
| `authorization_version` | `CharField` |  |  |  |  |  |
| `policy` | `ForeignKey` |  |  |  |  | R5PromotionArtifactModel |
| `trial` | `ForeignKey` |  |  |  |  | R5PromotionArtifactModel |
| `owner` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `purpose` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `decided_at` | `DateTimeField` |  |  |  |  |  |
| `decision_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `decision_valid_until` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_receipt_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |

### R5PromotionDecisionBundleModel

- 来源文件：`apps/research/infrastructure/r5_relative_value_promotion_models.py`
- 数据表：`research_r5_promotion_decision_bundle`
- 说明：Derived decision child bound one-to-one to its exact authorization.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `authorization` | `OneToOneField` |  |  |  |  | R5PromotionDecisionAuthorizationModel |
| `policy` | `ForeignKey` |  |  |  |  | R5PromotionArtifactModel |
| `trial` | `ForeignKey` |  |  |  |  | R5PromotionArtifactModel |
| `decision_id` | `CharField` |  |  |  |  |  |
| `decision_version` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `purpose` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `outcome` | `CharField` |  |  |  |  |  |
| `decided_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_receipt_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `decision_content_hash` | `CharField` |  | 是 |  |  |  |
| `bundle_content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### R5PromotionLifecycleAuthorizationModel

- 来源文件：`apps/research/infrastructure/r5_relative_value_promotion_models.py`
- 数据表：`research_r5_promotion_lifecycle_auth`
- 说明：Exact lifecycle authorization evidence persisted with its event child.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `evidence_id` | `CharField` |  |  |  |  |  |
| `evidence_version` | `CharField` |  |  |  |  |  |
| `authorization_id` | `CharField` |  |  |  |  |  |
| `authorization_version` | `CharField` |  |  |  |  |  |
| `decision` | `ForeignKey` |  |  |  |  | R5PromotionDecisionBundleModel |
| `rollback_target` | `ForeignKey` | 是 |  |  |  | R5PromotionDecisionBundleModel |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `event_type` | `CharField` |  |  |  |  |  |
| `reason_codes` | `JSONField` |  |  |  |  |  |
| `reason_hash` | `CharField` |  |  |  |  |  |
| `authorization_issued_at` | `DateTimeField` |  |  |  |  |  |
| `authorization_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `authorization_valid_until` | `DateTimeField` |  |  |  |  |  |
| `receipt_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `event_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_receipt_hash` | `CharField` |  | 是 |  |  |  |
| `authorization_content_hash` | `CharField` |  | 是 |  |  |  |
| `evidence_content_hash` | `CharField` |  | 是 |  |  |  |
| `event_content_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |

### R5PromotionLifecycleEventModel

- 来源文件：`apps/research/infrastructure/r5_relative_value_promotion_models.py`
- 数据表：`research_r5_promotion_lifecycle_event`
- 说明：Immutable scope-local lifecycle event and self-linked hash chain.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `authorization` | `OneToOneField` |  |  |  |  | R5PromotionLifecycleAuthorizationModel |
| `decision` | `ForeignKey` |  |  |  |  | R5PromotionDecisionBundleModel |
| `rollback_target` | `ForeignKey` | 是 |  |  |  | R5PromotionDecisionBundleModel |
| `previous_event` | `ForeignKey` | 是 |  |  | self | self |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `stream_id` | `CharField` |  |  |  |  |  |
| `event_type` | `CharField` |  |  |  |  |  |
| `sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `reason_codes` | `JSONField` |  |  |  |  |  |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_receipt_hash` | `CharField` |  | 是 |  |  |  |
| `previous_event_hash` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `event_content_hash` | `CharField` |  | 是 |  |  |  |
| `bundle_content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### R6ScopeQualificationRegistryModel

- 来源文件：`apps/research/infrastructure/r6_scope_qualification_models.py`
- 数据表：`research_r6_scope_qualification_registry`
- 说明：Immutable definition/source row with no public create authority.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `binding_id` | `CharField` |  |  |  |  |  |
| `binding_version` | `CharField` |  |  |  |  |  |
| `definition_version` | `CharField` |  |  |  |  |  |
| `definition_hash` | `CharField` |  | 是 |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_version` | `CharField` |  |  |  |  |  |
| `scope_hash` | `CharField` |  | 是 |  |  |  |
| `qualification_id` | `CharField` |  |  |  |  |  |
| `qualification_hash` | `CharField` |  |  |  |  |  |
| `source_receipt_id` | `CharField` |  |  |  |  |  |
| `source_receipt_version` | `CharField` |  |  |  |  |  |
| `source_receipt_hash` | `CharField` |  | 是 |  |  |  |
| `effective_at` | `DateTimeField` |  |  |  |  |  |
| `definition_valid_until` | `DateTimeField` |  |  |  |  |  |
| `source_available_at` | `DateTimeField` |  |  |  |  |  |
| `source_valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `definition_payload` | `JSONField` |  |  |  |  |  |
| `source_payload` | `JSONField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_replace_regime` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### R7HistoricalAnalogyCandidateModel

- 来源文件：`apps/research/infrastructure/r7_analogy_path_owner_models.py`
- 数据表：`research_r7_analogy_candidate`
- 说明：One immutable normalized candidate projection under an analogy receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `receipt` | `ForeignKey` |  |  |  |  | R7HistoricalAnalogyReceiptModel |
| `candidate_id` | `CharField` |  |  |  |  |  |
| `candidate_version` | `CharField` |  |  |  |  |  |
| `candidate_hash` | `CharField` |  |  |  |  |  |
| `window_start` | `DateTimeField` |  |  |  |  |  |
| `window_end` | `DateTimeField` |  |  |  |  |  |
| `decision_cutoff` | `DateTimeField` |  |  |  |  |  |
| `manifest_id` | `CharField` |  |  |  |  |  |
| `manifest_version` | `CharField` |  |  |  |  |  |
| `manifest_hash` | `CharField` |  |  |  |  |  |
| `manifest_reference_hash` | `CharField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `candidate_payload` | `JSONField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### R7HistoricalAnalogyDefinitionModel

- 来源文件：`apps/research/infrastructure/r7_analogy_path_owner_models.py`
- 数据表：`research_r7_analogy_definition`
- 说明：One immutable historical-analogy owner definition.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `definition_id` | `CharField` |  |  |  |  |  |
| `definition_version` | `CharField` |  |  |  |  |  |
| `definition_hash` | `CharField` |  | 是 |  |  |  |
| `scope_hash` | `CharField` |  |  |  |  |  |
| `study_version` | `CharField` |  |  |  |  |  |
| `feature_definition_version` | `CharField` |  |  |  |  |  |
| `similarity_method_version` | `CharField` |  |  |  |  |  |
| `activated_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `definition_payload` | `JSONField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### R7HistoricalAnalogyReceiptModel

- 来源文件：`apps/research/infrastructure/r7_analogy_path_owner_models.py`
- 数据表：`research_r7_analogy_receipt`
- 说明：One complete immutable analogy raw-source receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `definition` | `ForeignKey` |  |  |  |  | R7HistoricalAnalogyDefinitionModel |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `receipt_hash` | `CharField` |  | 是 |  |  |  |
| `scope_hash` | `CharField` |  |  |  |  |  |
| `query_manifest_id` | `CharField` |  |  |  |  |  |
| `query_manifest_version` | `CharField` |  |  |  |  |  |
| `query_manifest_hash` | `CharField` |  |  |  |  |  |
| `query_manifest_reference_hash` | `CharField` |  |  |  |  |  |
| `query_as_of` | `DateTimeField` |  |  |  |  |  |
| `source_available_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `definition_valid_until` | `DateTimeField` |  |  |  |  |  |
| `receipt_payload` | `JSONField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### R7ScenarioPathDefinitionModel

- 来源文件：`apps/research/infrastructure/r7_analogy_path_owner_models.py`
- 数据表：`research_r7_path_definition`
- 说明：One immutable path expected-membership and shock definition.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `definition_id` | `CharField` |  |  |  |  |  |
| `definition_version` | `CharField` |  |  |  |  |  |
| `definition_hash` | `CharField` |  | 是 |  |  |  |
| `scope_hash` | `CharField` |  |  |  |  |  |
| `study_version` | `CharField` |  |  |  |  |  |
| `source_version` | `CharField` |  |  |  |  |  |
| `sample_definition_version` | `CharField` |  |  |  |  |  |
| `activated_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `definition_payload` | `JSONField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### R7ScenarioPathMemberModel

- 来源文件：`apps/research/infrastructure/r7_analogy_path_owner_models.py`
- 数据表：`research_r7_path_member`
- 说明：One immutable normalized sample or shock member under a path receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `receipt` | `ForeignKey` |  |  |  |  | R7ScenarioPathReceiptModel |
| `member_kind` | `CharField` |  |  |  |  |  |
| `member_key` | `CharField` |  |  |  |  |  |
| `member_version` | `CharField` |  |  |  |  |  |
| `member_hash` | `CharField` |  |  |  |  |  |
| `period_index` | `PositiveIntegerField` |  |  |  |  |  |
| `resolution` | `CharField` |  |  |  |  |  |
| `from_scenario_revision_id` | `UUIDField` | 是 |  |  |  |  |
| `to_scenario_revision_id` | `UUIDField` | 是 |  |  |  |  |
| `observed_at` | `DateTimeField` | 是 |  |  |  |  |
| `source_available_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `member_payload` | `JSONField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### R7ScenarioPathReceiptModel

- 来源文件：`apps/research/infrastructure/r7_analogy_path_owner_models.py`
- 数据表：`research_r7_path_receipt`
- 说明：One complete immutable path raw-source receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `definition` | `ForeignKey` |  |  |  |  | R7ScenarioPathDefinitionModel |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `receipt_hash` | `CharField` |  | 是 |  |  |  |
| `scope_hash` | `CharField` |  |  |  |  |  |
| `pit_manifest_id` | `CharField` |  |  |  |  |  |
| `pit_manifest_version` | `CharField` |  |  |  |  |  |
| `pit_manifest_hash` | `CharField` |  |  |  |  |  |
| `pit_manifest_reference_hash` | `CharField` |  |  |  |  |  |
| `pit_as_of` | `DateTimeField` |  |  |  |  |  |
| `source_available_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `definition_valid_until` | `DateTimeField` |  |  |  |  |  |
| `receipt_payload` | `JSONField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### R7MonitoringAppendOnlyModel

- 来源文件：`apps/research/infrastructure/r7_post_promotion_monitoring_models.py`
- 抽象模型：是
- 说明：Permit only a repository-claimed insert inside its private UoW.

### R7MonitoringAssessmentLedgerModel

- 来源文件：`apps/research/infrastructure/r7_post_promotion_monitoring_models.py`
- 数据表：`research_r7_monitoring_assessment`
- 说明：Immutable complete assessment bound to authoritative result/lifecycle rows.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `assessment_id` | `CharField` |  | 是 |  |  |  |
| `assessment_version` | `CharField` |  |  |  |  |  |
| `result` | `ForeignKey` |  |  |  |  | R7ResearchResultModel |
| `lifecycle_head` | `ForeignKey` |  |  |  |  | R7ResultLifecycleEventModel |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_hash` | `CharField` |  |  |  |  |  |
| `result_stable_id` | `CharField` |  |  |  |  |  |
| `result_version` | `CharField` |  |  |  |  |  |
| `result_hash` | `CharField` |  |  |  |  |  |
| `lifecycle_attestation_id` | `CharField` |  |  |  |  |  |
| `lifecycle_attestation_version` | `CharField` |  |  |  |  |  |
| `lifecycle_attestation_hash` | `CharField` |  |  |  |  |  |
| `lifecycle_head_hash` | `CharField` |  |  |  |  |  |
| `calendar_id` | `CharField` |  |  |  |  |  |
| `calendar_version` | `CharField` |  |  |  |  |  |
| `calendar_hash` | `CharField` |  |  |  |  |  |
| `period_id` | `CharField` |  |  |  |  |  |
| `period_version` | `CharField` |  |  |  |  |  |
| `period_hash` | `CharField` |  |  |  |  |  |
| `realization_owner_id` | `CharField` |  |  |  |  |  |
| `realization_owner_version` | `CharField` |  |  |  |  |  |
| `realization_owner_hash` | `CharField` |  |  |  |  |  |
| `evaluated_at` | `DateTimeField` |  |  |  |  |  |
| `policy_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `result_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `lifecycle_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `calendar_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `realization_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `owner_valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `observation_count` | `PositiveIntegerField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `automatic_retirement` | `BooleanField` |  |  | False |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R7MonitoringAuditSnapshotModel

- 来源文件：`apps/research/infrastructure/r7_post_promotion_monitoring_models.py`
- 数据表：`research_r7_monitoring_audit_snapshot`
- 说明：Immutable manifest backing signed internal-audit cursors.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot_id` | `CharField` |  |  |  |  |  |
| `snapshot_version` | `CharField` |  |  |  |  |  |
| `as_of` | `DateTimeField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `entry_count` | `PositiveIntegerField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `internal_audit_only` | `BooleanField` |  |  | True |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R7MonitoringObservationLedgerModel

- 来源文件：`apps/research/infrastructure/r7_post_promotion_monitoring_models.py`
- 数据表：`research_r7_monitoring_observation`
- 说明：Immutable assessment-scoped Forecast Ledger realization member.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `assessment` | `ForeignKey` |  |  |  |  | R7MonitoringAssessmentLedgerModel |
| `result` | `ForeignKey` |  |  |  |  | R7ResearchResultModel |
| `lifecycle_head` | `ForeignKey` |  |  |  |  | R7ResultLifecycleEventModel |
| `observation_index` | `PositiveIntegerField` |  |  |  |  |  |
| `observation_id` | `CharField` |  |  |  |  |  |
| `observation_version` | `CharField` |  |  |  |  |  |
| `observation_hash` | `CharField` |  |  |  |  |  |
| `prediction_hash` | `CharField` |  |  |  |  |  |
| `member_hash` | `CharField` |  |  |  |  |  |
| `period_id` | `CharField` |  |  |  |  |  |
| `period_hash` | `CharField` |  |  |  |  |  |
| `published_at` | `DateTimeField` |  |  |  |  |  |
| `horizon_end` | `DateTimeField` |  |  |  |  |  |
| `available_at` | `DateTimeField` |  |  |  |  |  |
| `owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R7ResearchResultAuditSnapshotModel

- 来源文件：`apps/research/infrastructure/r7_research_result_lifecycle_models.py`
- 数据表：`research_r7_result_audit_snapshot`
- 说明：Immutable materialized result/lifecycle graph for stable audit paging.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot_id` | `CharField` |  |  |  |  |  |
| `snapshot_version` | `CharField` |  |  |  |  |  |
| `as_of` | `DateTimeField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `entry_count` | `PositiveIntegerField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `internal_audit_only` | `BooleanField` |  |  | True |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R7ResultLifecycleAuthorizationModel

- 来源文件：`apps/research/infrastructure/r7_research_result_lifecycle_models.py`
- 数据表：`research_r7_result_lifecycle_authorization`
- 说明：Exact Research-owner authorization persisted with redundant anchors.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `result` | `ForeignKey` |  |  |  |  | R7ResearchResultModel |
| `result_key` | `CharField` |  |  |  |  |  |
| `result_version` | `CharField` |  |  |  |  |  |
| `result_content_hash` | `CharField` |  |  |  |  |  |
| `authorization_id` | `CharField` |  |  |  |  |  |
| `authorization_version` | `CharField` |  |  |  |  |  |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `action` | `CharField` |  |  |  |  |  |
| `expected_sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `reason_codes` | `JSONField` |  |  |  |  |  |
| `evidence_ref` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `promotes_internal_research_record_only` | `BooleanField` |  |  | True |  |  |
| `publishes_model_probability` | `BooleanField` |  |  | False |  |  |
| `produces_decision` | `BooleanField` |  |  | False |  |  |
| `executes_orders` | `BooleanField` |  |  | False |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R7ResultLifecycleEventModel

- 来源文件：`apps/research/infrastructure/r7_research_result_lifecycle_models.py`
- 数据表：`research_r7_result_lifecycle_event`
- 说明：Immutable result-local event bound one-to-one to its authorization.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `result` | `ForeignKey` |  |  |  |  | R7ResearchResultModel |
| `authorization_record` | `OneToOneField` |  |  |  |  | R7ResultLifecycleAuthorizationModel |
| `result_key` | `CharField` |  |  |  |  |  |
| `result_version` | `CharField` |  |  |  |  |  |
| `result_content_hash` | `CharField` |  |  |  |  |  |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `authorization_id` | `CharField` |  |  |  |  |  |
| `authorization_version` | `CharField` |  |  |  |  |  |
| `authorization_hash` | `CharField` |  |  |  |  |  |
| `action` | `CharField` |  |  |  |  |  |
| `sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `previous_event_hash` | `CharField` | 是 |  |  |  |  |
| `reason_codes` | `JSONField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `promotes_internal_research_record_only` | `BooleanField` |  |  | True |  |  |
| `publishes_model_probability` | `BooleanField` |  |  | False |  |  |
| `produces_decision` | `BooleanField` |  |  | False |  |  |
| `executes_orders` | `BooleanField` |  |  | False |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### _ClaimedAppendOnlyLifecycleModel

- 来源文件：`apps/research/infrastructure/r7_research_result_lifecycle_models.py`
- 抽象模型：是
- 说明：Shared claim enforcement for both immutable lifecycle tables.

### R7ResearchResultModel

- 来源文件：`apps/research/infrastructure/r7_research_result_models.py`
- 数据表：`research_r7_research_result`
- 说明：Canonical complete R7 evidence graph and deterministic result packet.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `sample_policy` | `ForeignKey` |  |  |  |  | R7SamplePolicyModel |
| `result_id` | `CharField` |  |  |  |  |  |
| `result_version` | `CharField` |  |  |  |  |  |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_record_hash` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `evaluated_at` | `DateTimeField` |  |  |  |  |  |
| `evidence_graph_hash` | `CharField` |  |  |  |  |  |
| `input_receipt_hash` | `CharField` |  | 是 |  |  |  |
| `calibration_hash` | `CharField` |  |  |  |  |  |
| `historical_analogy_hash` | `CharField` |  |  |  |  |  |
| `path_research_hash` | `CharField` |  |  |  |  |  |
| `analogy_evidence_hash` | `CharField` | 是 |  |  |  |  |
| `path_evidence_hash` | `CharField` | 是 |  |  |  |  |
| `forecast_observation_count` | `PositiveIntegerField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `trains_probability_model` | `BooleanField` |  |  | False |  |  |
| `publishes_model_probability` | `BooleanField` |  |  | False |  |  |
| `produces_decision` | `BooleanField` |  |  | False |  |  |
| `executes_orders` | `BooleanField` |  |  | False |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R7FamilyAppendOnlyModel

- 来源文件：`apps/research/infrastructure/r7_result_family_lifecycle_models.py`
- 抽象模型：是
- 说明：Permit only one repository-claimed database-keyed insert.

### R7FamilyLifecycleAuditSnapshotModel

- 来源文件：`apps/research/infrastructure/r7_result_family_lifecycle_models.py`
- 数据表：`research_r7_family_lifecycle_audit_snapshot`
- 说明：Immutable signed-audit manifest materialization.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot_id` | `CharField` |  |  |  |  |  |
| `snapshot_version` | `CharField` |  |  |  |  |  |
| `family_id` | `CharField` |  |  |  |  |  |
| `family_version` | `CharField` |  |  |  |  |  |
| `family_hash` | `CharField` |  |  |  |  |  |
| `as_of` | `DateTimeField` |  |  |  |  |  |
| `total_count` | `PositiveIntegerField` |  |  |  |  |  |
| `manifest_hash` | `CharField` |  |  |  |  |  |
| `payload_schema_version` | `CharField` |  |  |  |  |  |
| `payload` | `JSONField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |

### R7FamilyLifecycleAuthorizationModel

- 来源文件：`apps/research/infrastructure/r7_result_family_lifecycle_models.py`
- 数据表：`research_r7_family_lifecycle_authorization`
- 说明：Owner authorization receipt; never an authorization provider itself.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `authorization_id` | `CharField` |  |  |  |  |  |
| `authorization_version` | `CharField` |  |  |  |  |  |
| `family_id` | `CharField` |  |  |  |  |  |
| `family_version` | `CharField` |  |  |  |  |  |
| `family_hash` | `CharField` |  |  |  |  |  |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `action` | `CharField` |  |  |  |  |  |
| `expected_sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `expected_previous_event_id` | `CharField` | 是 |  |  |  |  |
| `expected_previous_event_version` | `CharField` | 是 |  |  |  |  |
| `expected_previous_event_hash` | `CharField` | 是 |  |  |  |  |
| `subject_result` | `ForeignKey` |  |  |  |  | R7ResearchResultModel |
| `subject_result_id_value` | `CharField` |  |  |  |  |  |
| `subject_result_version` | `CharField` |  |  |  |  |  |
| `subject_result_hash` | `CharField` |  |  |  |  |  |
| `subject_local_lifecycle_head` | `ForeignKey` |  |  |  |  | R7ResultLifecycleEventModel |
| `subject_owner_attestation_hash` | `CharField` |  |  |  |  |  |
| `rollback_target_result` | `ForeignKey` | 是 |  |  |  | R7ResearchResultModel |
| `rollback_target_result_id_value` | `CharField` | 是 |  |  |  |  |
| `rollback_target_result_version` | `CharField` | 是 |  |  |  |  |
| `rollback_target_result_hash` | `CharField` | 是 |  |  |  |  |
| `rollback_target_local_lifecycle_head` | `ForeignKey` | 是 |  |  |  | R7ResultLifecycleEventModel |
| `rollback_target_owner_attestation_hash` | `CharField` | 是 |  |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `payload_schema_version` | `CharField` |  |  |  |  |  |
| `payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `row_hash` | `CharField` |  | 是 |  |  |  |

### R7FamilyLifecycleEventModel

- 来源文件：`apps/research/infrastructure/r7_result_family_lifecycle_models.py`
- 数据表：`research_r7_family_lifecycle_event`
- 说明：Canonical family event bound to exact local result evidence.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `authorization_row` | `OneToOneField` |  |  |  |  | R7FamilyLifecycleAuthorizationModel |
| `family_id` | `CharField` |  |  |  |  |  |
| `family_version` | `CharField` |  |  |  |  |  |
| `family_hash` | `CharField` |  |  |  |  |  |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `action` | `CharField` |  |  |  |  |  |
| `sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `subject_result` | `ForeignKey` |  |  |  |  | R7ResearchResultModel |
| `subject_local_lifecycle_head` | `ForeignKey` |  |  |  |  | R7ResultLifecycleEventModel |
| `rollback_target_result` | `ForeignKey` | 是 |  |  |  | R7ResearchResultModel |
| `rollback_target_local_lifecycle_head` | `ForeignKey` | 是 |  |  |  | R7ResultLifecycleEventModel |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `previous_event_hash` | `CharField` | 是 |  |  |  |  |
| `payload_schema_version` | `CharField` |  |  |  |  |  |
| `payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `row_hash` | `CharField` |  | 是 |  |  |  |

### R7FamilyLifecycleStreamCommitModel

- 来源文件：`apps/research/infrastructure/r7_result_family_lifecycle_models.py`
- 数据表：`research_r7_family_lifecycle_stream_commit`
- 说明：Third-party completeness anchor for each authorization/event pair.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `authorization_row` | `OneToOneField` |  |  |  |  | R7FamilyLifecycleAuthorizationModel |
| `event_row` | `OneToOneField` |  |  |  |  | R7FamilyLifecycleEventModel |
| `family_id` | `CharField` |  |  |  |  |  |
| `family_version` | `CharField` |  |  |  |  |  |
| `family_hash` | `CharField` |  |  |  |  |  |
| `sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `authorization_id` | `CharField` |  |  |  |  |  |
| `authorization_version` | `CharField` |  |  |  |  |  |
| `authorization_hash` | `CharField` |  |  |  |  |  |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `event_hash` | `CharField` |  |  |  |  |  |
| `subject_result_hash` | `CharField` |  |  |  |  |  |
| `subject_local_lifecycle_head_hash` | `CharField` |  |  |  |  |  |
| `rollback_target_result_hash` | `CharField` | 是 |  |  |  |  |
| `rollback_target_local_lifecycle_head_hash` | `CharField` | 是 |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |

### R7SamplePolicyAppendOnlyModel

- 来源文件：`apps/research/infrastructure/r7_sample_policy_models.py`
- 抽象模型：是
- 说明：Permit only an exact claimed insert with a database-assigned key.

### R7SamplePolicyApprovalReceiptModel

- 来源文件：`apps/research/infrastructure/r7_sample_policy_models.py`
- 数据表：`research_r7_sample_policy_approval`
- 说明：Research copy of one exact external-owner authorization receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `authorization_id` | `CharField` |  |  |  |  |  |
| `authorization_version` | `CharField` |  |  |  |  |  |
| `owner_record_id` | `CharField` |  |  |  |  |  |
| `owner_record_version` | `CharField` |  |  |  |  |  |
| `owner_record_hash` | `CharField` |  |  |  |  |  |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `policy_definition_hash` | `CharField` |  |  |  |  |  |
| `approved_by` | `CharField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `authorization_content_hash` | `CharField` |  | 是 |  |  |  |
| `record_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R7SamplePolicyModel

- 来源文件：`apps/research/infrastructure/r7_sample_policy_models.py`
- 数据表：`research_r7_sample_policy`
- 说明：Canonical scope-bound R7 sample policy and immutable safety seal.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `approval` | `OneToOneField` |  |  |  |  | R7SamplePolicyApprovalReceiptModel |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `policy_content_hash` | `CharField` |  | 是 |  |  |  |
| `authorization_content_hash` | `CharField` |  |  |  |  |  |
| `activated_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `sample_window_start` | `DateTimeField` |  |  |  |  |  |
| `sample_window_end` | `DateTimeField` |  |  |  |  |  |
| `forecast_horizon_seconds` | `DecimalField` |  |  |  |  |  |
| `censoring_lag_seconds` | `DecimalField` |  |  |  |  |  |
| `censoring_rule_version` | `CharField` |  |  |  |  |  |
| `minimum_forecasts_per_revision` | `PositiveIntegerField` |  |  |  |  |  |
| `minimum_resolved_outcomes_per_revision` | `PositiveIntegerField` |  |  |  |  |  |
| `minimum_binary_class_observations` | `PositiveIntegerField` |  |  |  |  |  |
| `minimum_multiclass_groups` | `PositiveIntegerField` |  |  |  |  |  |
| `minimum_multiclass_class_observations` | `PositiveIntegerField` |  |  |  |  |  |
| `minimum_historical_analogies` | `PositiveIntegerField` |  |  |  |  |  |
| `minimum_path_probability_observations` | `PositiveIntegerField` |  |  |  |  |  |
| `path_horizon_periods` | `PositiveIntegerField` |  |  |  |  |  |
| `require_all_path_initial_states` | `BooleanField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R8MonitoringPolicyRegistryModel

- 来源文件：`apps/research/infrastructure/r8_monitoring_policy_models.py`
- 数据表：`research_r8_monitoring_policy_registry`
- 说明：Immutable dedicated policy definition and source receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_hash` | `CharField` |  | 是 |  |  |  |
| `definition_version` | `CharField` |  |  |  |  |  |
| `definition_hash` | `CharField` |  | 是 |  |  |  |
| `source_receipt_id` | `CharField` |  |  |  |  |  |
| `source_receipt_version` | `CharField` |  |  |  |  |  |
| `source_receipt_hash` | `CharField` |  | 是 |  |  |  |
| `target_result_id` | `CharField` |  |  |  |  |  |
| `target_result_hash` | `CharField` |  |  |  |  |  |
| `target_receipt_id` | `CharField` |  |  |  |  |  |
| `target_receipt_hash` | `CharField` |  |  |  |  |  |
| `calendar_id` | `CharField` |  |  |  |  |  |
| `calendar_version` | `CharField` |  |  |  |  |  |
| `calendar_hash` | `CharField` |  |  |  |  |  |
| `source_available_at` | `DateTimeField` |  |  |  |  |  |
| `source_valid_until` | `DateTimeField` |  |  |  |  |  |
| `policy_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `policy_valid_until` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `definition_payload` | `JSONField` |  |  |  |  |  |
| `source_payload` | `JSONField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |

### ScenarioReviewAppendOnlyModel

- 来源文件：`apps/research/infrastructure/scenario_review_reminder_models.py`
- 抽象模型：是
- 说明：Reject instance, default-manager, base-manager, and related mutation paths.

### ScenarioReviewReminderEventModel

- 来源文件：`apps/research/infrastructure/scenario_review_reminder_models.py`
- 数据表：`research_scenario_review_reminder_event`
- 说明：Immutable root/hash-chain occurrence in the internal pull outbox.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `reminder` | `ForeignKey` |  |  |  |  | ScenarioReviewReminderModel |
| `event_type` | `CharField` |  |  |  |  |  |
| `sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `escalation_level` | `PositiveSmallIntegerField` |  |  | 0 |  |  |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `actor_evidence_hash` | `CharField` |  |  |  |  |  |
| `reason_code` | `CharField` |  |  |  |  |  |
| `idempotency_key` | `CharField` |  |  |  |  |  |
| `previous_event_hash` | `CharField` | 是 |  |  |  |  |
| `delivery_scope` | `CharField` |  |  | internal_review |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `external_dispatch_requested` | `BooleanField` |  |  | False |  |  |
| `auto_approval_requested` | `BooleanField` |  |  | False |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `record_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### ScenarioReviewReminderModel

- 来源文件：`apps/research/infrastructure/scenario_review_reminder_models.py`
- 数据表：`research_scenario_review_reminder`
- 说明：Immutable schedule header and exact source binding for one reminder.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `reminder_id` | `CharField` |  |  |  |  |  |
| `reminder_version` | `CharField` |  |  |  |  |  |
| `intent_id` | `CharField` |  | 是 |  |  |  |
| `intent_version` | `CharField` |  |  |  |  |  |
| `intent_content_hash` | `CharField` |  |  |  |  |  |
| `forecast_entry_id` | `CharField` |  |  |  |  |  |
| `forecast_group_id` | `CharField` |  |  |  |  |  |
| `forecast_observation_hash` | `CharField` |  |  |  |  |  |
| `probability_policy_version` | `CharField` |  |  |  |  |  |
| `probability_policy_hash` | `CharField` |  |  |  |  |  |
| `scenario_revision_id` | `UUIDField` |  |  |  |  |  |
| `scenario_set_revision_id` | `UUIDField` | 是 |  |  |  |  |
| `invalidation_evidence_hash` | `CharField` |  |  |  |  |  |
| `intent_reason_code` | `CharField` |  |  |  |  |  |
| `schedule_version` | `CharField` |  |  |  |  |  |
| `schedule_policy_hash` | `CharField` |  |  |  |  |  |
| `expiry_delay` | `DurationField` |  |  |  |  |  |
| `escalation_delay` | `DurationField` |  |  |  |  |  |
| `maximum_escalation_level` | `PositiveSmallIntegerField` |  |  |  |  |  |
| `path_horizon_periods` | `PositiveSmallIntegerField` |  |  |  |  |  |
| `owner_evidence_hash` | `CharField` |  |  |  |  |  |
| `escalation_policy_version` | `CharField` |  |  |  |  |  |
| `escalation_policy_hash` | `CharField` |  |  |  |  |  |
| `path_evidence_hash` | `CharField` |  |  |  |  |  |
| `period_bindings` | `JSONField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `due_at` | `DateTimeField` |  |  |  |  |  |
| `expires_at` | `DateTimeField` |  |  |  |  |  |
| `delivery_scope` | `CharField` |  |  | internal_review |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `external_dispatch_requested` | `BooleanField` |  |  | False |  |  |
| `auto_approval_requested` | `BooleanField` |  |  | False |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R6ActivationAppendOnlyModel

- 来源文件：`apps/research/infrastructure/state_model_activation_models.py`
- 抽象模型：是
- 说明：Permit only one repository-claimed database-keyed insert.

### R6ActivationAuditSnapshotModel

- 来源文件：`apps/research/infrastructure/state_model_activation_models.py`
- 数据表：`research_r6_activation_audit_snapshot`
- 说明：Immutable materialized manifest for stable activation audit paging.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `snapshot_id` | `CharField` |  |  |  |  |  |
| `snapshot_version` | `CharField` |  |  |  |  |  |
| `as_of` | `DateTimeField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `entry_count` | `PositiveIntegerField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `internal_audit_only` | `BooleanField` |  |  | True |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_replace_regime` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R6ActivationAuthorizationModel

- 来源文件：`apps/research/infrastructure/state_model_activation_models.py`
- 数据表：`research_r6_activation_authorization`
- 说明：Immutable exact owner authorization snapshot.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `authorization_id` | `CharField` |  |  |  |  |  |
| `authorization_version` | `CharField` |  |  |  |  |  |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_version` | `CharField` |  |  |  |  |  |
| `scope_hash` | `CharField` |  |  |  |  |  |
| `action` | `CharField` |  |  |  |  |  |
| `subject_approval_id` | `CharField` |  |  |  |  |  |
| `subject_approval_version` | `CharField` |  |  |  |  |  |
| `subject_approval_hash` | `CharField` |  |  |  |  |  |
| `rollback_approval_id` | `CharField` | 是 |  |  |  |  |
| `rollback_approval_version` | `CharField` | 是 |  |  |  |  |
| `rollback_approval_hash` | `CharField` | 是 |  |  |  |  |
| `expected_sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `expected_previous_event_hash` | `CharField` | 是 |  |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `reason_codes` | `JSONField` |  |  |  |  |  |
| `evidence_ref` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_replace_regime` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R6ActivationEventModel

- 来源文件：`apps/research/infrastructure/state_model_activation_models.py`
- 数据表：`research_r6_activation_event`
- 说明：Immutable event in one scope-local activation stack.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `authorization_row` | `OneToOneField` |  |  |  |  | R6ActivationAuthorizationModel |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_version` | `CharField` |  |  |  |  |  |
| `scope_hash` | `CharField` |  |  |  |  |  |
| `action` | `CharField` |  |  |  |  |  |
| `subject_approval_id` | `CharField` |  |  |  |  |  |
| `subject_approval_version` | `CharField` |  |  |  |  |  |
| `subject_approval_hash` | `CharField` |  |  |  |  |  |
| `rollback_approval_id` | `CharField` | 是 |  |  |  |  |
| `rollback_approval_version` | `CharField` | 是 |  |  |  |  |
| `rollback_approval_hash` | `CharField` | 是 |  |  |  |  |
| `authorization_id` | `CharField` |  |  |  |  |  |
| `authorization_version` | `CharField` |  |  |  |  |  |
| `authorization_hash` | `CharField` |  |  |  |  |  |
| `sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `previous_event_hash` | `CharField` | 是 |  |  |  |  |
| `reason_codes` | `JSONField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_replace_regime` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R6ActivationStreamCommitModel

- 来源文件：`apps/research/infrastructure/state_model_activation_models.py`
- 数据表：`research_r6_activation_stream_commit`
- 说明：Immutable three-way commit anchor for one activation transition.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `authorization_row` | `OneToOneField` |  |  |  |  | R6ActivationAuthorizationModel |
| `event_row` | `OneToOneField` |  |  |  |  | R6ActivationEventModel |
| `authorization_id` | `CharField` |  |  |  |  |  |
| `authorization_version` | `CharField` |  |  |  |  |  |
| `authorization_hash` | `CharField` |  |  |  |  |  |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `event_hash` | `CharField` |  |  |  |  |  |
| `scope_id` | `CharField` |  |  |  |  |  |
| `scope_version` | `CharField` |  |  |  |  |  |
| `scope_hash` | `CharField` |  |  |  |  |  |
| `sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `previous_event_hash` | `CharField` | 是 |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_replace_regime` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R6MonitoringAppendOnlyModel

- 来源文件：`apps/research/infrastructure/state_model_monitoring_models.py`
- 抽象模型：是
- 说明：Permit only one repository-claimed database-keyed insert.

### R6MonitoringAssessmentModel

- 来源文件：`apps/research/infrastructure/state_model_monitoring_models.py`
- 数据表：`research_r6_monitoring_assessment`
- 说明：Immutable recomputed monitoring assessment and exact owner graph.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `qualification` | `ForeignKey` |  |  |  |  | R6QualificationAssessmentModel |
| `assessment_id` | `CharField` |  | 是 |  |  |  |
| `qualification_assessment_id` | `CharField` |  |  |  |  |  |
| `qualification_assessment_hash` | `CharField` |  |  |  |  |  |
| `requested_policy_id` | `CharField` |  |  |  |  |  |
| `requested_policy_version` | `CharField` |  |  |  |  |  |
| `expected_policy_hash` | `CharField` |  |  |  |  |  |
| `policy_hash` | `CharField` |  |  |  |  |  |
| `period_calendar_id` | `CharField` |  |  |  |  |  |
| `period_calendar_version` | `CharField` |  |  |  |  |  |
| `period_calendar_hash` | `CharField` |  |  |  |  |  |
| `evaluated_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `observation_count` | `PositiveIntegerField` |  |  |  |  |  |
| `metric_result_count` | `PositiveIntegerField` |  |  |  |  |  |
| `observation_hashes` | `JSONField` |  |  |  |  |  |
| `blockers` | `JSONField` |  |  |  |  |  |
| `policy_payload` | `JSONField` |  |  |  |  |  |
| `period_calendar_payload` | `JSONField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `label_drift_detected` | `BooleanField` |  |  |  |  |  |
| `retirement_review_required` | `BooleanField` |  |  |  |  |  |
| `automatic_retirement` | `BooleanField` |  |  | False |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_replace_regime` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R6MonitoringObservationModel

- 来源文件：`apps/research/infrastructure/state_model_monitoring_models.py`
- 数据表：`research_r6_monitoring_observation`
- 说明：Immutable canonical raw monitoring observation.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `qualification` | `ForeignKey` |  |  |  |  | R6QualificationAssessmentModel |
| `observation_id` | `CharField` |  |  |  |  |  |
| `observation_version` | `CharField` |  |  |  |  |  |
| `qualification_assessment_id` | `CharField` |  |  |  |  |  |
| `qualification_assessment_hash` | `CharField` |  |  |  |  |  |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_hash` | `CharField` |  |  |  |  |  |
| `period_calendar_id` | `CharField` |  |  |  |  |  |
| `period_calendar_version` | `CharField` |  |  |  |  |  |
| `period_calendar_hash` | `CharField` |  |  |  |  |  |
| `observation_period_id` | `CharField` |  |  |  |  |  |
| `period_start` | `DateTimeField` |  |  |  |  |  |
| `period_end` | `DateTimeField` |  |  |  |  |  |
| `source_owner` | `CharField` |  |  |  |  |  |
| `observed_at` | `DateTimeField` |  |  |  |  |  |
| `available_at` | `DateTimeField` |  |  |  |  |  |
| `owner_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `pit_manifest_id` | `CharField` |  |  |  |  |  |
| `pit_manifest_hash` | `CharField` |  |  |  |  |  |
| `evidence_ref` | `CharField` |  |  |  |  |  |
| `label_protocol_version` | `CharField` |  |  |  |  |  |
| `observed_label_set_hash` | `CharField` |  |  |  |  |  |
| `metric_count` | `PositiveIntegerField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_replace_regime` | `BooleanField` |  |  | True |  |  |
| `must_not_publish_current` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R6QualificationAppendOnlyModel

- 来源文件：`apps/research/infrastructure/state_model_qualification_models.py`
- 抽象模型：是
- 说明：Permit only one exact claimed insert with a database-assigned key.

### R6QualificationAssessmentModel

- 来源文件：`apps/research/infrastructure/state_model_qualification_models.py`
- 数据表：`research_r6_qualification_assessment`
- 说明：Immutable canonical qualification assessment evidence.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `assessment_id` | `CharField` |  | 是 |  |  |  |
| `study_id` | `CharField` |  |  |  |  |  |
| `assessed_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `candidate_id` | `CharField` | 是 |  |  |  |  |
| `candidate_version` | `CharField` | 是 |  |  |  |  |
| `study_hash` | `CharField` | 是 |  |  |  |  |
| `preregistration_hash` | `CharField` | 是 |  |  |  |  |
| `baseline_shortfall_report_hash` | `CharField` | 是 |  |  |  |  |
| `candidate_evidence_hash` | `CharField` | 是 |  |  |  |  |
| `advanced_assessment_hash` | `CharField` | 是 |  |  |  |  |
| `pit_manifest_canonical_hash` | `CharField` | 是 |  |  |  |  |
| `artifact_attestation_hash` | `CharField` | 是 |  |  |  |  |
| `advanced_threshold_hash` | `CharField` | 是 |  |  |  |  |
| `derived_metric_bundle_hash` | `CharField` | 是 |  |  |  |  |
| `policy_hash` | `CharField` | 是 |  |  |  |  |
| `metric_result_count` | `PositiveIntegerField` |  |  |  |  |  |
| `blockers` | `JSONField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `may_request_promotion_review` | `BooleanField` |  |  |  |  |  |
| `promotion_decision_present` | `BooleanField` |  |  | False |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_replace_regime` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R6QualificationLifecycleAuthorizationModel

- 来源文件：`apps/research/infrastructure/state_model_qualification_models.py`
- 数据表：`research_r6_qualification_lifecycle_auth`
- 说明：Immutable copy of one research owner lifecycle authorization.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `assessment` | `ForeignKey` |  |  |  |  | R6QualificationAssessmentModel |
| `authorization_id` | `CharField` |  |  |  |  |  |
| `authorization_version` | `CharField` |  |  |  |  |  |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `action` | `CharField` |  |  |  |  |  |
| `expected_sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `owner` | `CharField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `reason_codes` | `JSONField` |  |  |  |  |  |
| `evidence_ref` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_replace_regime` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### R6QualificationLifecycleEventModel

- 来源文件：`apps/research/infrastructure/state_model_qualification_models.py`
- 数据表：`research_r6_qualification_lifecycle_event`
- 说明：Append-only transition event linked to exactly one authorization.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `assessment` | `ForeignKey` |  |  |  |  | R6QualificationAssessmentModel |
| `authorization` | `OneToOneField` |  |  |  |  | R6QualificationLifecycleAuthorizationModel |
| `event_id` | `CharField` |  |  |  |  |  |
| `event_version` | `CharField` |  |  |  |  |  |
| `action` | `CharField` |  |  |  |  |  |
| `sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `occurred_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `previous_event_hash` | `CharField` | 是 |  |  |  |  |
| `reason_codes` | `JSONField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_replace_regime` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |


## risk_center

### AShareExecutionRuleModel

- 来源文件：`apps/risk_center/infrastructure/ashare_execution_rule_models.py`
- 数据表：`risk_center_ashare_execution_rule`
- 说明：One complete canonical A-share execution rule configuration version.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `security_id` | `CharField` |  |  |  |  |  |
| `rule_id` | `CharField` |  |  |  |  |  |
| `rule_version` | `CharField` |  |  |  |  |  |
| `market` | `CharField` |  |  |  |  |  |
| `board` | `CharField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `source_available_at` | `DateTimeField` |  |  |  |  |  |
| `effective_from` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `retirement_effective_at` | `DateTimeField` | 是 |  |  |  |  |
| `retirement_recorded_at` | `DateTimeField` | 是 |  |  |  |  |
| `retirement_request_id` | `UUIDField` | 是 | 是 |  |  |  |
| `retirement_actor_type` | `CharField` | 是 |  |  |  |  |
| `retirement_actor_id` | `CharField` | 是 |  |  |  |  |
| `retirement_request_hash` | `CharField` | 是 |  |  |  |  |

### BrokerExecutionPolicyAppendOnlyModel

- 来源文件：`apps/risk_center/infrastructure/broker_order_execution_policy_models.py`
- 抽象模型：是
- 说明：Permit only exact inserts claimed by this capability's repository.

### BrokerOrderExecutionPolicyActivationModel

- 来源文件：`apps/risk_center/infrastructure/broker_order_execution_policy_models.py`
- 数据表：`risk_center_broker_execution_policy_activation`
- 说明：One immutable actor-bound policy activation in an account hash chain.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `source` | `ForeignKey` |  |  |  |  | BrokerOrderExecutionPolicySourceModel |
| `owner` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `permission_cap` | `CharField` |  |  |  |  |  |
| `policy_id` | `CharField` |  |  |  |  |  |
| `policy_version` | `CharField` |  |  |  |  |  |
| `policy_identity_hash` | `CharField` |  | 是 |  |  |  |
| `account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `source_snapshot_id` | `CharField` |  |  |  |  |  |
| `source_snapshot_version` | `CharField` |  |  |  |  |  |
| `source_snapshot_hash` | `CharField` |  |  |  |  |  |
| `supersedes_policy_hash` | `CharField` | 是 |  |  |  |  |
| `activated_actor_id` | `CharField` |  |  |  |  |  |
| `activated_actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `activated_actor_kind` | `CharField` |  |  |  |  |  |
| `activated_actor_is_staff` | `BooleanField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `activated_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `canonical_policy` | `JSONField` |  |  |  |  |  |
| `canonical_activation` | `JSONField` |  |  |  |  |  |
| `policy_content_hash` | `CharField` |  | 是 |  |  |  |
| `activation_content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### BrokerOrderExecutionPolicySourceModel

- 来源文件：`apps/risk_center/infrastructure/broker_order_execution_policy_models.py`
- 数据表：`risk_center_broker_execution_policy_source`
- 说明：One immutable complete five-component source-bundle first winner.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `source_snapshot_id` | `CharField` |  |  |  |  |  |
| `source_snapshot_version` | `CharField` |  |  |  |  |  |
| `source_identity_hash` | `CharField` |  | 是 |  |  |  |
| `account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `source_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  |  |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### BrokerOrderRiskAuthorizationAppendOnlyModel

- 来源文件：`apps/risk_center/infrastructure/broker_order_risk_authorization_models.py`
- 抽象模型：是
- 说明：Permit only exact, repository-claimed inserts.

### BrokerOrderRiskAuthorizationRecordModel

- 来源文件：`apps/risk_center/infrastructure/broker_order_risk_authorization_models.py`
- 数据表：`risk_center_broker_order_risk_authorization`
- 说明：One immutable authorization in an account/order hash chain.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `subject` | `OneToOneField` |  |  |  |  | BrokerOrderRiskAuthorizationSubjectModel |
| `owner` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `permission_cap` | `CharField` |  |  |  |  |  |
| `authorization_id` | `CharField` |  |  |  |  |  |
| `authorization_version` | `CharField` |  |  |  |  |  |
| `authorization_identity_hash` | `CharField` |  | 是 |  |  |  |
| `subject_hash` | `CharField` |  | 是 |  |  |  |
| `account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `order_id` | `CharField` |  |  |  |  |  |
| `supersedes_authorization_hash` | `CharField` | 是 |  |  |  |  |
| `approved_actor_id` | `CharField` |  |  |  |  |  |
| `approved_actor_kind` | `CharField` |  |  |  |  |  |
| `approved_actor_is_staff` | `BooleanField` |  |  |  |  |  |
| `approved_actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### BrokerOrderRiskAuthorizationSubjectModel

- 来源文件：`apps/risk_center/infrastructure/broker_order_risk_authorization_models.py`
- 数据表：`risk_center_broker_order_risk_subject`
- 说明：One immutable authorization subject first winner.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `subject_id` | `CharField` |  |  |  |  |  |
| `subject_version` | `CharField` |  |  |  |  |  |
| `subject_identity_hash` | `CharField` |  | 是 |  |  |  |
| `account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `order_id` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `supersedes_authorization_hash` | `CharField` | 是 |  |  |  |  |
| `requested_actor_id` | `CharField` |  |  |  |  |  |
| `requested_actor_kind` | `CharField` |  |  |  |  |  |
| `requested_actor_is_staff` | `BooleanField` |  |  |  |  |  |
| `requested_actor_user_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `requested_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### EvidenceOperatorSpecApprovalAppendOnlyModel

- 来源文件：`apps/risk_center/infrastructure/evidence_operator_spec_approval_models.py`
- 抽象模型：是
- 说明：Permit only a repository-claimed insert with a database-assigned key.

### EvidenceOperatorSpecApprovalRecordModel

- 来源文件：`apps/risk_center/infrastructure/evidence_operator_spec_approval_models.py`
- 数据表：`risk_center_evidence_operator_spec_approval`
- 说明：One immutable human-staff approval for one exact subject.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `subject` | `OneToOneField` |  |  |  |  | EvidenceOperatorSpecApprovalSubjectModel |
| `owner` | `CharField` |  |  |  |  |  |
| `capability` | `CharField` |  |  |  |  |  |
| `approval_id` | `CharField` |  |  |  |  |  |
| `approval_version` | `CharField` |  |  |  |  |  |
| `approval_identity_hash` | `CharField` |  | 是 |  |  |  |
| `subject_hash` | `CharField` |  | 是 |  |  |  |
| `operator_id` | `CharField` |  |  |  |  |  |
| `operator_version` | `CharField` |  |  |  |  |  |
| `definition_hash` | `CharField` |  | 是 |  |  |  |
| `supersedes_activation_hash` | `CharField` | 是 |  |  |  |  |
| `approved_actor_id` | `CharField` |  |  |  |  |  |
| `approved_actor_kind` | `CharField` |  |  |  |  |  |
| `approved_actor_is_staff` | `BooleanField` |  |  |  |  |  |
| `approved_actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `issued_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### EvidenceOperatorSpecApprovalSubjectModel

- 来源文件：`apps/risk_center/infrastructure/evidence_operator_spec_approval_models.py`
- 数据表：`risk_center_evidence_operator_spec_subject`
- 说明：One immutable external-definition approval subject first winner.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `subject_id` | `CharField` |  |  |  |  |  |
| `subject_version` | `CharField` |  |  |  |  |  |
| `subject_identity_hash` | `CharField` |  | 是 |  |  |  |
| `operator_id` | `CharField` |  |  |  |  |  |
| `operator_version` | `CharField` |  |  |  |  |  |
| `definition_hash` | `CharField` |  | 是 |  |  |  |
| `supersedes_activation_hash` | `CharField` | 是 |  |  |  |  |
| `requested_actor_id` | `CharField` |  |  |  |  |  |
| `requested_actor_kind` | `CharField` |  |  |  |  |  |
| `requested_actor_is_staff` | `BooleanField` |  |  |  |  |  |
| `requested_actor_user_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `requested_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### M1RebalanceRiskPolicyRevisionModel

- 来源文件：`apps/risk_center/infrastructure/m1_rebalance_risk_policy_models.py`
- 数据表：`risk_center_m1_rebalance_policy_revision`
- 说明：One additive, append-only M1 preview policy version.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `risk_policy_version` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `actor` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `effective_from` | `DateTimeField` |  |  |  |  |  |
| `effective_until` | `DateTimeField` |  |  |  |  |  |
| `known_at` | `DateTimeField` |  |  |  |  |  |
| `reason` | `TextField` |  |  |  |  |  |
| `max_single_position_state` | `CharField` |  |  |  |  |  |
| `max_single_position_pct` | `DecimalField` | 是 |  |  |  |  |
| `max_single_position_reason` | `TextField` | 是 |  |  |  |  |
| `max_total_position_state` | `CharField` |  |  |  |  |  |
| `max_total_position_pct` | `DecimalField` | 是 |  |  |  |  |
| `max_total_position_reason` | `TextField` | 是 |  |  |  |  |
| `max_stop_loss_state` | `CharField` |  |  |  |  |  |
| `max_stop_loss_pct` | `DecimalField` | 是 |  |  |  |  |
| `max_stop_loss_reason` | `TextField` | 是 |  |  |  |  |
| `source_snapshot_schema_version` | `CharField` |  |  |  |  |  |
| `source_snapshot` | `JSONField` |  |  |  |  |  |
| `risk_falsification_schema_version` | `CharField` |  |  |  |  |  |
| `risk_falsification_rules` | `JSONField` |  |  |  |  |  |

### ImmutableScenarioRecordMixin

- 来源文件：`apps/risk_center/infrastructure/models.py`
- 抽象模型：是
- 说明：Reject update/delete for append-only scenario revisions and evidence.

### RiskDailyReportModel

- 来源文件：`apps/risk_center/infrastructure/models.py`
- 数据表：`risk_center_daily_report`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `account_id` | `PositiveIntegerField` |  |  |  |  |  |
| `report_date` | `DateField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `risk_daily_report` | `JSONField` |  |  | dict |  |  |
| `position_daily_report` | `JSONField` |  |  | dict |  |  |
| `post_investment_check` | `JSONField` |  |  | dict |  |  |
| `input_snapshot` | `JSONField` |  |  | dict |  |  |
| `generated_by` | `ForeignKey` | 是 |  |  |  | settings.AUTH_USER_MODEL |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### RiskExceptionModel

- 来源文件：`apps/risk_center/infrastructure/models.py`
- 数据表：`risk_center_exception`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `account_id` | `PositiveIntegerField` | 是 |  |  |  |  |
| `field_name` | `CharField` |  |  |  |  |  |
| `allowed_value` | `JSONField` |  |  |  |  |  |
| `reason` | `TextField` |  |  |  |  |  |
| `created_by` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `expires_at` | `DateTimeField` |  |  |  |  |  |
| `is_active` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### RiskParameterMixin

- 来源文件：`apps/risk_center/infrastructure/models.py`
- 抽象模型：是

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `max_total_position_pct` | `FloatField` | 是 |  |  |  |  |
| `max_single_position_pct` | `FloatField` | 是 |  |  |  |  |
| `max_daily_loss_pct` | `FloatField` | 是 |  |  |  |  |
| `max_drawdown_pct` | `FloatField` | 是 |  |  |  |  |
| `max_stop_loss_pct` | `FloatField` | 是 |  |  |  |  |
| `take_profit_pct` | `FloatField` | 是 |  |  |  |  |
| `min_cash_pct` | `FloatField` | 是 |  |  |  |  |
| `force_stop_loss` | `BooleanField` | 是 |  |  |  |  |
| `hard_exclusions` | `JSONField` |  |  | list |  |  |

### RiskPolicyAuditModel

- 来源文件：`apps/risk_center/infrastructure/models.py`
- 数据表：`risk_center_policy_audit`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `target_type` | `CharField` |  |  |  |  |  |
| `target_id` | `CharField` |  |  |  |  |  |
| `action` | `CharField` |  |  |  |  |  |
| `actor` | `ForeignKey` | 是 |  |  |  | settings.AUTH_USER_MODEL |
| `before` | `JSONField` |  |  | dict |  |  |
| `after` | `JSONField` |  |  | dict |  |  |
| `reason` | `TextField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### ScenarioActivationModel

- 来源文件：`apps/risk_center/infrastructure/models.py`
- 数据表：`risk_center_scenario_activation`
- 说明：Historical active-set pointer; only lifecycle fields may change.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `activation_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `environment` | `CharField` |  |  |  |  |  |
| `purpose` | `CharField` |  |  |  |  |  |
| `scenario_set_revision` | `ForeignKey` |  |  |  | risk_center.ScenarioSetRevisionModel | risk_center.ScenarioSetRevisionModel |
| `previous_activation` | `ForeignKey` | 是 |  |  | self | self |
| `activated_by` | `CharField` |  |  |  |  |  |
| `reason` | `TextField` |  |  |  |  |  |
| `correlation_id` | `CharField` |  |  |  |  |  |
| `activated_at` | `DateTimeField` |  |  | timezone.now |  |  |
| `is_active` | `BooleanField` |  |  | True |  |  |
| `deactivated_at` | `DateTimeField` | 是 |  |  |  |  |

### ScenarioSetModel

- 来源文件：`apps/risk_center/infrastructure/models.py`
- 数据表：`risk_center_scenario_set`
- 说明：Stable identity for a purpose-specific collection of scenarios.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `set_key` | `CharField` |  | 是 |  |  |  |
| `name` | `CharField` |  |  |  |  |  |
| `purpose` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  | risk_center |  |  |
| `applicable_asset_scope` | `JSONField` |  |  | list |  |  |
| `status` | `CharField` |  |  | active |  |  |
| `created_at` | `DateTimeField` |  |  | timezone.now |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### StressScenarioDefinitionModel

- 来源文件：`apps/risk_center/infrastructure/models.py`
- 数据表：`risk_center_stress_scenario_definition`
- 说明：Stable identity and compatibility aliases for a stress scenario.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `scenario_key` | `CharField` |  | 是 |  |  |  |
| `name` | `CharField` |  |  |  |  |  |
| `category` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  | risk_center |  |  |
| `status` | `CharField` |  |  | active |  |  |
| `description` | `TextField` |  |  |  |  |  |
| `legacy_aliases` | `JSONField` |  |  | list |  |  |
| `created_at` | `DateTimeField` |  |  | timezone.now |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### ImmutableScenarioGovernanceAuditMixin

- 来源文件：`apps/risk_center/infrastructure/scenario_governance_models.py`
- 抽象模型：是
- 说明：Reject updates and deletes of canonical governance audit evidence.

### ScenarioGovernanceIdempotencyModel

- 来源文件：`apps/risk_center/infrastructure/scenario_governance_models.py`
- 数据表：`risk_center_scenario_governance_idempotency`
- 说明：Persistent terminal result scoped by actor, capability, and idempotency key.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `record_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `actor_id` | `CharField` |  |  |  |  |  |
| `capability_key` | `CharField` |  |  |  |  |  |
| `idempotency_key` | `CharField` |  |  |  |  |  |
| `operation` | `CharField` |  |  |  |  |  |
| `request_fingerprint` | `CharField` |  |  |  |  |  |
| `preview` | `ForeignKey` |  |  |  | risk_center.ScenarioGovernancePreviewModel | risk_center.ScenarioGovernancePreviewModel |
| `result` | `JSONField` |  |  | dict |  |  |
| `created_at` | `DateTimeField` |  |  | timezone.now |  |  |

### ScenarioGovernancePreviewModel

- 来源文件：`apps/risk_center/infrastructure/scenario_governance_models.py`
- 数据表：`risk_center_scenario_governance_preview`
- 说明：Durable actor-bound preview consumed by at most one committed write.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `preview_id` | `UUIDField` |  |  | uuid.uuid4 |  |  |
| `actor_id` | `CharField` |  |  |  |  |  |
| `actor_kind` | `CharField` |  |  |  |  |  |
| `capability_key` | `CharField` |  |  |  |  |  |
| `operation` | `CharField` |  |  |  |  |  |
| `scenario_key` | `CharField` | 是 |  |  |  |  |
| `exact_payload` | `JSONField` |  |  | dict |  |  |
| `request_fingerprint` | `CharField` |  |  |  |  |  |
| `base_version` | `PositiveIntegerField` | 是 |  |  |  |  |
| `base_hash` | `CharField` | 是 |  |  |  |  |
| `after_hash` | `CharField` |  |  |  |  |  |
| `expires_at` | `DateTimeField` |  |  |  |  |  |
| `consumed_at` | `DateTimeField` | 是 |  |  |  |  |
| `consumed_idempotency_key` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  | timezone.now |  |  |

### ScenarioGovernanceProposalLinkModel

- 来源文件：`apps/risk_center/infrastructure/scenario_governance_models.py`
- 数据表：`risk_center_scenario_governance_proposal`
- 说明：Risk Center lifecycle binding for one persistent AgentProposal row.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `proposal_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `preview` | `OneToOneField` |  |  |  | risk_center.ScenarioGovernancePreviewModel | risk_center.ScenarioGovernancePreviewModel |
| `operation` | `CharField` |  |  |  |  |  |
| `creator_actor_id` | `CharField` |  |  |  |  |  |
| `creator_actor_kind` | `CharField` |  |  |  |  |  |
| `capability_key` | `CharField` |  |  |  |  |  |
| `request_fingerprint` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  | submitted |  |  |
| `scenario_key` | `CharField` | 是 |  |  |  |  |
| `revision` | `ForeignKey` | 是 |  |  | risk_center.StressScenarioRevisionModel | risk_center.StressScenarioRevisionModel |
| `scenario_set_revision` | `ForeignKey` | 是 |  |  | risk_center.ScenarioSetRevisionModel | risk_center.ScenarioSetRevisionModel |
| `target_version` | `PositiveIntegerField` | 是 |  |  |  |  |
| `approved_by_actor_id` | `CharField` | 是 |  |  |  |  |
| `approved_at` | `DateTimeField` | 是 |  |  |  |  |
| `rejected_by_actor_id` | `CharField` | 是 |  |  |  |  |
| `rejected_at` | `DateTimeField` | 是 |  |  |  |  |
| `executed_at` | `DateTimeField` | 是 |  |  |  |  |
| `created_at` | `DateTimeField` |  |  | timezone.now |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |


## rotation

### AssetClassModel

- 来源文件：`apps/rotation/infrastructure/models.py`
- 数据表：`rotation_asset_class`
- 说明：Asset class table

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `code` | `CharField` |  | 是 |  | 资产代码 |  |
| `name` | `CharField` |  |  |  | 资产名称 |  |
| `category` | `CharField` |  |  |  | 资产类别 |  |
| `description` | `TextField` |  |  |  | 资产描述 |  |
| `underlying_index` | `CharField` |  |  |  | 标的指数 |  |
| `currency` | `CharField` |  |  | CNY | 计价货币 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### MomentumScoreModel

- 来源文件：`apps/rotation/infrastructure/models.py`
- 数据表：`rotation_momentum_score`
- 说明：Momentum score cache table

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `asset_code` | `CharField` |  |  |  | 资产代码 |  |
| `calc_date` | `DateField` |  |  |  | 计算日期 |  |
| `momentum_1m` | `FloatField` |  |  | 0.0 | 1月动量 |  |
| `momentum_3m` | `FloatField` |  |  | 0.0 | 3月动量 |  |
| `momentum_6m` | `FloatField` |  |  | 0.0 | 6月动量 |  |
| `momentum_12m` | `FloatField` |  |  | 0.0 | 12月动量 |  |
| `composite_score` | `FloatField` |  |  | 0.0 | 综合得分 |  |
| `rank` | `IntegerField` |  |  | 0 | 排名 |  |
| `sharpe_1m` | `FloatField` |  |  | 0.0 | 1月夏普 |  |
| `sharpe_3m` | `FloatField` |  |  | 0.0 | 3月夏普 |  |
| `ma_signal` | `CharField` |  |  | neutral | 均线信号 |  |
| `trend_strength` | `FloatField` |  |  | 0.0 | 趋势强度 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### PortfolioRotationConfigModel

- 来源文件：`apps/rotation/infrastructure/models.py`
- 数据表：`portfolio_rotation_config`
- 说明：账户级轮动配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `account` | `OneToOneField` |  |  |  | 投资组合账户 | simulated_trading.SimulatedAccountModel |
| `base_config` | `ForeignKey` | 是 |  |  | 基础模板（可选） | RotationConfigModel |
| `risk_tolerance` | `CharField` |  |  | moderate | 风险偏好 |  |
| `regime_allocations` | `JSONField` |  |  | dict | 象限资产配置 |  |
| `is_enabled` | `BooleanField` |  |  | False | 启用后，自动交易将根据当前 Regime 使用此配置调仓 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### RotationConfigModel

- 来源文件：`apps/rotation/infrastructure/models.py`
- 数据表：`rotation_config`
- 说明：Rotation configuration table

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | `CharField` |  | 是 |  | 配置名称 |  |
| `description` | `TextField` |  |  |  | 配置描述 |  |
| `strategy_type` | `CharField` |  |  | momentum | 策略类型 |  |
| `asset_universe` | `JSONField` |  |  | list | 资产池 |  |
| `params` | `JSONField` |  |  | dict | 策略参数 |  |
| `rebalance_frequency` | `CharField` |  |  | monthly | 调仓频率 |  |
| `min_weight` | `FloatField` |  |  | 0.0 | 最小权重 |  |
| `max_weight` | `FloatField` |  |  | 1.0 | 最大权重 |  |
| `max_turnover` | `FloatField` |  |  | 1.0 | 最大换手率 |  |
| `lookback_period` | `IntegerField` |  |  | 252 | 回溯周期（天） |  |
| `regime_allocations` | `JSONField` |  |  | dict | 象限配置 |  |
| `momentum_periods` | `JSONField` |  |  | list | 动量周期 |  |
| `top_n` | `IntegerField` |  |  | 3 | 选资产数量 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### RotationPortfolioModel

- 来源文件：`apps/rotation/infrastructure/models.py`
- 数据表：`rotation_portfolio`
- 说明：Rotation portfolio state table

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `config` | `ForeignKey` |  |  |  | 配置 | RotationConfigModel |
| `trade_date` | `DateField` |  |  |  | 交易日期 |  |
| `current_allocation` | `JSONField` |  |  |  | 当前配置 |  |
| `daily_return` | `FloatField` |  |  | 0.0 | 日收益率 |  |
| `cumulative_return` | `FloatField` |  |  | 0.0 | 累计收益率 |  |
| `portfolio_volatility` | `FloatField` |  |  | 0.0 | 组合波动率 |  |
| `max_drawdown` | `FloatField` |  |  | 0.0 | 最大回撤 |  |
| `turnover_since_last` | `FloatField` |  |  | 0.0 | 换手率 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### RotationSignalModel

- 来源文件：`apps/rotation/infrastructure/models.py`
- 数据表：`rotation_signal`
- 说明：Rotation signal history table

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `config` | `ForeignKey` |  |  |  | 配置 | RotationConfigModel |
| `signal_date` | `DateField` |  |  |  | 信号日期 |  |
| `target_allocation` | `JSONField` |  |  |  | 目标配置 |  |
| `current_regime` | `CharField` |  |  |  | 当前象限 |  |
| `momentum_ranking` | `JSONField` |  |  | list | 动量排名 |  |
| `expected_volatility` | `FloatField` |  |  | 0.0 | 预期波动率 |  |
| `expected_return` | `FloatField` |  |  | 0.0 | 预期收益 |  |
| `action_required` | `CharField` |  |  | hold | 建议操作 |  |
| `reason` | `TextField` |  |  |  | 原因说明 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### RotationTemplateModel

- 来源文件：`apps/rotation/infrastructure/models.py`
- 数据表：`rotation_template`
- 说明：预设风险模板表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | `CharField` |  | 是 |  | 模板名称 |  |
| `key` | `CharField` |  | 是 |  | conservative / moderate / aggressive |  |
| `description` | `TextField` |  |  |  | 模板描述 |  |
| `regime_allocations` | `JSONField` |  |  | dict | 象限配置 |  |
| `display_order` | `IntegerField` |  |  | 0 | 展示顺序 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |


## sector

### ImmutableIndustryTemplateModel

- 来源文件：`apps/sector/infrastructure/industry_operating_template_models.py`
- 抽象模型：是
- 说明：Reject updates and deletes for versioned template evidence.

### IndustryOperatingTemplateVersionModel

- 来源文件：`apps/sector/infrastructure/industry_operating_template_models.py`
- 数据表：`sector_industry_operating_template`
- 说明：One immutable, hash-sealed and unseeded industry template version.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `template_code` | `CharField` |  |  |  |  |  |
| `template_version` | `PositiveIntegerField` |  |  |  |  |  |
| `industry_code` | `CharField` |  |  |  |  |  |
| `name` | `CharField` |  |  |  |  |  |
| `methodology_ref` | `CharField` |  |  |  |  |  |
| `effective_at` | `DateTimeField` |  |  |  |  |  |
| `effective_to` | `DateTimeField` | 是 |  |  |  |  |
| `lifecycle` | `CharField` |  |  |  |  |  |
| `lifecycle_reason` | `CharField` |  |  |  |  |  |
| `supersedes_version` | `PositiveIntegerField` | 是 |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### IndustryTemplateRunEvidenceModel

- 来源文件：`apps/sector/infrastructure/industry_operating_template_models.py`
- 数据表：`sector_industry_template_run_evidence`
- 说明：One immutable, research-only execution evidence version.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `run_key` | `CharField` |  |  |  |  |  |
| `run_version` | `PositiveIntegerField` |  |  |  |  |  |
| `template_code` | `CharField` |  |  |  |  |  |
| `template_version` | `PositiveIntegerField` |  |  |  |  |  |
| `template_content_hash` | `CharField` |  |  |  |  |  |
| `as_of_time` | `DateTimeField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `payload` | `JSONField` |  |  |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### SectorConstituentModel

- 来源文件：`apps/sector/infrastructure/models.py`
- 数据表：`sector_constituent`
- 说明：板块成分股关系表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `sector_code` | `CharField` |  |  |  | 板块代码 |  |
| `stock_code` | `CharField` |  |  |  | 股票代码 |  |
| `enter_date` | `DateField` |  |  |  | 纳入日期 |  |
| `exit_date` | `DateField` | 是 |  |  | 剔除日期 |  |
| `is_current` | `BooleanField` |  |  | True | 是否当前成分股 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### SectorIndexModel

- 来源文件：`apps/sector/infrastructure/models.py`
- 数据表：`sector_index_daily`
- 说明：板块指数日线数据表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `sector_code` | `CharField` |  |  |  | 板块代码 |  |
| `trade_date` | `DateField` |  |  |  | 交易日期 |  |
| `open_price` | `DecimalField` |  |  |  | 开盘点位 |  |
| `high` | `DecimalField` |  |  |  | 最高点位 |  |
| `low` | `DecimalField` |  |  |  | 最低点位 |  |
| `close` | `DecimalField` |  |  |  | 收盘点位 |  |
| `volume` | `BigIntegerField` |  |  |  | 成交量（手） |  |
| `amount` | `DecimalField` |  |  |  | 成交额（元） |  |
| `turnover_rate` | `FloatField` | 是 |  |  | 换手率（%） |  |
| `change_pct` | `FloatField` |  |  |  | 涨跌幅（%） |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### SectorInfoModel

- 来源文件：`apps/sector/infrastructure/models.py`
- 数据表：`sector_info`
- 说明：板块基本信息表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `sector_code` | `CharField` |  | 是 |  | 板块代码 |  |
| `sector_name` | `CharField` |  |  |  | 板块名称 |  |
| `level` | `CharField` |  |  |  | 板块级别 |  |
| `parent_code` | `CharField` | 是 |  |  | 父级板块代码 |  |
| `is_active` | `BooleanField` |  |  | True | 是否活跃 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### SectorPreferenceConfigModel

- 来源文件：`apps/sector/infrastructure/models.py`
- 数据表：`config_sector_preference`
- 说明：板块偏好配置表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `regime` | `CharField` |  |  |  | Recovery/Overheat/Stagflation/Deflation |  |
| `sector_name` | `CharField` |  |  |  | 板块名称 |  |
| `weight` | `FloatField` |  |  | 0.5 | 1.0 表示最强偏好，0.0 表示无偏好 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### SectorRelativeStrengthModel

- 来源文件：`apps/sector/infrastructure/models.py`
- 数据表：`sector_relative_strength`
- 说明：板块相对强弱指标表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `sector_code` | `CharField` |  |  |  | 板块代码 |  |
| `trade_date` | `DateField` |  |  |  | 交易日期 |  |
| `relative_strength` | `FloatField` |  |  |  | 相对强弱（板块收益率 - 大盘收益率） |  |
| `momentum` | `FloatField` |  |  |  | 动量（N日累计收益率，%） |  |
| `momentum_window` | `IntegerField` |  |  | 20 | 动量计算窗口 |  |
| `beta` | `FloatField` | 是 |  |  | 贝塔系数 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### ValidatedSectorModel

- 来源文件：`apps/sector/infrastructure/models.py`
- 抽象模型：是
- 说明：Run model contracts for every ordinary ORM write.


## sentiment

### AppendOnlySentimentEvidence

- 来源文件：`apps/sentiment/infrastructure/models.py`
- 抽象模型：是
- 说明：Reject mutation and instance deletion of inserted analysis evidence.

### SentimentAlertModel

- 来源文件：`apps/sentiment/infrastructure/models.py`
- 数据表：`sentiment_alert`
- 说明：Sentiment 告警 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `alert_type` | `CharField` |  |  |  | 告警类型 |  |
| `severity` | `CharField` |  |  | SEVERITY_WARNING | 严重程度 |  |
| `title` | `CharField` |  |  |  | 告警标题 |  |
| `message` | `TextField` |  |  |  | 告警详情 |  |
| `metadata` | `JSONField` | 是 |  |  | 元数据 |  |
| `is_resolved` | `BooleanField` |  |  | False | 是否已解决 |  |
| `resolved_at` | `DateTimeField` | 是 |  |  | 解决时间 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### SentimentCache

- 来源文件：`apps/sentiment/infrastructure/models.py`
- 数据表：`sentiment_cache`
- 说明：情感分析缓存表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `text_hash` | `CharField` |  | 是 |  | 文本哈希 |  |
| `sentiment_score` | `FloatField` |  |  |  | 情感评分 |  |
| `category` | `CharField` |  |  |  | 情感分类 |  |
| `confidence` | `FloatField` |  |  |  | 置信度 |  |
| `keywords` | `JSONField` |  |  | list | 关键词 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### SentimentIndexModel

- 来源文件：`apps/sentiment/infrastructure/models.py`
- 数据表：`sentiment_index`
- 说明：舆情情绪指数表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `index_date` | `DateField` |  | 是 |  | 指数日期 |  |
| `news_sentiment` | `FloatField` |  |  | 0.0 | 新闻情绪 |  |
| `policy_sentiment` | `FloatField` |  |  | 0.0 | 政策情绪 |  |
| `composite_index` | `FloatField` |  |  | 0.0 | 综合指数 |  |
| `confidence_level` | `FloatField` |  |  | 0.0 | 置信度 |  |
| `data_sufficient` | `BooleanField` |  |  | False | True 表示数据充足，False 表示无数据或数据不足 |  |
| `sector_sentiment` | `JSONField` |  |  | dict | 格式: {"金融": 0.5, "科技": 0.8} |  |
| `news_count` | `IntegerField` |  |  | 0 | 新闻数量 |  |
| `policy_events_count` | `IntegerField` |  |  | 0 | 政策事件数量 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### ValidatedSentimentModel

- 来源文件：`apps/sentiment/infrastructure/models.py`
- 抽象模型：是
- 说明：Run model contracts for every ordinary ORM write.


## setup_wizard

### SetupStateModel

- 来源文件：`apps/setup_wizard/infrastructure/models.py`
- 数据表：`setup_wizard_state`
- 说明：安装状态模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `is_completed` | `BooleanField` |  |  | False | 是否已完成初始化 |  |
| `admin_username` | `CharField` |  |  |  | 创建的管理员用户名 |  |
| `admin_email` | `EmailField` |  |  |  | 管理员邮箱 |  |
| `ai_provider_configured` | `BooleanField` |  |  | False | 是否已配置 AI Provider |  |
| `data_source_configured` | `BooleanField` |  |  | False | 是否已配置数据源 |  |
| `current_step` | `CharField` |  |  | welcome | 当前步骤 |  |
| `completed_steps` | `JSONField` |  |  | list | 已完成的步骤列表 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |
| `completed_at` | `DateTimeField` | 是 |  |  | 完成时间 |  |


## share

### ShareAccessLogModel

- 来源文件：`apps/share/infrastructure/models.py`
- 数据表：`share_access_log`
- 说明：分享访问日志模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `share_link` | `ForeignKey` |  |  |  | 分享链接 | ShareLinkModel |
| `accessed_at` | `DateTimeField` |  |  |  | 访问时间 |  |
| `ip_hash` | `CharField` |  |  |  | IP地址的哈希值，不存储原始IP |  |
| `user_agent` | `TextField` | 是 |  |  | 浏览器/客户端信息 |  |
| `referer` | `TextField` | 是 |  |  | HTTP Referer |  |
| `is_verified` | `BooleanField` |  |  | False | 是否通过密码验证（如果有密码） |  |
| `result_status` | `CharField` |  |  | success | 访问结果 |  |

### ShareDisclaimerConfigModel

- 来源文件：`apps/share/infrastructure/models.py`
- 数据表：`share_disclaimer_config`
- 说明：Global disclaimer content and modal behavior for public share pages.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `singleton_key` | `CharField` |  | 是 | default | 单例键 |  |
| `is_enabled` | `BooleanField` |  |  | True | 显示底部风险提示 |  |
| `modal_enabled` | `BooleanField` |  |  | True | 启用风险提示弹窗 |  |
| `modal_title` | `CharField` |  |  | 重要声明 | 提示标题 |  |
| `modal_confirm_text` | `CharField` |  |  | 我已知悉 | 弹窗确认按钮文案 |  |
| `lines` | `JSONField` |  |  | list | 按顺序展示的风险提示条目 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### ShareLinkModel

- 来源文件：`apps/share/infrastructure/models.py`
- 数据表：`share_link`
- 说明：分享链接模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `ForeignKey` |  |  |  | 所有者 | User |
| `account_id` | `IntegerField` |  |  |  | 关联的模拟账户ID |  |
| `short_code` | `CharField` |  | 是 |  | 用于公开访问的唯一短码 |  |
| `title` | `CharField` |  |  |  | 标题 |  |
| `subtitle` | `CharField` | 是 |  |  | 副标题 |  |
| `theme` | `CharField` |  |  | bloomberg | 公开分享页的展示风格 |  |
| `share_level` | `CharField` |  |  | snapshot | 决定数据展示的详细程度 |  |
| `status` | `CharField` |  |  | active | 状态 |  |
| `password_hash` | `CharField` | 是 |  |  | 使用 Django 的 make_password 生成 |  |
| `expires_at` | `DateTimeField` | 是 |  |  | 过期后无法访问 |  |
| `max_access_count` | `IntegerField` | 是 |  |  | null 表示无限制 |  |
| `access_count` | `IntegerField` |  |  | 0 | 访问次数 |  |
| `last_snapshot_at` | `DateTimeField` | 是 |  |  | 最近一次生成快照的时间 |  |
| `last_accessed_at` | `DateTimeField` | 是 |  |  | 最后访问时间 |  |
| `allow_indexing` | `BooleanField` |  |  | False | 允许后页面可被搜索引擎收录 |  |
| `show_amounts` | `BooleanField` |  |  | False | 显示金额 |  |
| `show_positions` | `BooleanField` |  |  | True | 显示持仓 |  |
| `show_transactions` | `BooleanField` |  |  | True | 显示交易 |  |
| `show_decision_summary` | `BooleanField` |  |  | True | 显示决策摘要 |  |
| `show_decision_evidence` | `BooleanField` |  |  | False | 显示决策依据 |  |
| `show_invalidation_logic` | `BooleanField` |  |  | False | 显示证伪逻辑 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### ShareSnapshotModel

- 来源文件：`apps/share/infrastructure/models.py`
- 数据表：`share_snapshot`
- 说明：分享快照模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `share_link` | `ForeignKey` |  |  |  | 分享链接 | ShareLinkModel |
| `snapshot_version` | `IntegerField` |  |  | 1 | 同一分享链接的快照版本号 |  |
| `summary_payload` | `JSONField` | 是 |  | dict | 账户摘要信息 |  |
| `performance_payload` | `JSONField` | 是 |  | dict | 绩效指标 |  |
| `positions_payload` | `JSONField` | 是 |  | dict | 持仓列表 |  |
| `transactions_payload` | `JSONField` | 是 |  | dict | 交易记录 |  |
| `decision_payload` | `JSONField` | 是 |  | dict | 决策依据和证伪逻辑 |  |
| `generated_at` | `DateTimeField` |  |  |  | 生成时间 |  |
| `source_range_start` | `DateField` | 是 |  |  | 快照数据的起始日期 |  |
| `source_range_end` | `DateField` | 是 |  |  | 快照数据的结束日期 |  |


## signal

### ForecastCalibrationExpectedMemberModel

- 来源文件：`apps/signal/infrastructure/forecast_calibration_sample_models.py`
- 数据表：`signal_forecast_calibration_expected_member`
- 说明：One expected Forecast Ledger member in a frozen denominator.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `definition` | `ForeignKey` |  |  |  |  | ForecastCalibrationSampleDefinitionModel |
| `source_version` | `CharField` |  |  |  |  |  |
| `entry_id` | `CharField` |  |  |  |  |  |
| `observation_version` | `CharField` |  |  |  |  |  |
| `forecast_group_id` | `CharField` |  |  |  |  |  |
| `scenario_revision_id` | `UUIDField` |  |  |  |  |  |
| `scenario_set_revision_id` | `UUIDField` |  |  |  |  |  |
| `subjective_probability` | `DecimalField` |  |  |  |  |  |
| `subjective_probability_source_version` | `CharField` |  |  |  |  |  |
| `model_probability` | `DecimalField` | 是 |  |  |  |  |
| `model_probability_source_version` | `CharField` |  |  |  |  |  |
| `model_promotion_decision_id` | `CharField` |  |  |  |  |  |
| `pit_manifest_id` | `CharField` |  |  |  |  |  |
| `pit_manifest_version` | `CharField` |  |  |  |  |  |
| `pit_manifest_hash` | `CharField` |  |  |  |  |  |
| `censoring_rule_version` | `CharField` |  |  |  |  |  |
| `published_at` | `DateTimeField` |  |  |  |  |  |
| `horizon_end` | `DateTimeField` |  |  |  |  |  |
| `entry_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `outcome_evidence_valid_until` | `DateTimeField` |  |  |  |  |  |
| `evidence_ref` | `CharField` |  |  |  |  |  |
| `content_hash` | `CharField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### ForecastCalibrationSampleDefinitionModel

- 来源文件：`apps/signal/infrastructure/forecast_calibration_sample_models.py`
- 数据表：`signal_forecast_calibration_sample_definition`
- 说明：One outcome-free canonical calibration denominator definition.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `definition_version` | `CharField` |  |  |  |  |  |
| `sample_id` | `CharField` |  |  |  |  |  |
| `sample_version` | `CharField` |  |  |  |  |  |
| `scope_content_hash` | `CharField` |  |  |  |  |  |
| `scenario_set_revision_id` | `UUIDField` |  |  |  |  |  |
| `scenario_revision_ids` | `JSONField` |  |  |  |  |  |
| `forecast_horizon_microseconds` | `BigIntegerField` |  |  |  |  |  |
| `censoring_rule_version` | `CharField` |  |  |  |  |  |
| `sample_window_start` | `DateTimeField` |  |  |  |  |  |
| `sample_window_end` | `DateTimeField` |  |  |  |  |  |
| `available_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `evidence_ref` | `CharField` |  |  |  |  |  |
| `source_content_hash` | `CharField` |  |  |  |  |  |
| `registered_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### ForecastCalibrationSampleMemberReceiptModel

- 来源文件：`apps/signal/infrastructure/forecast_calibration_sample_models.py`
- 数据表：`signal_forecast_calibration_sample_member_receipt`
- 说明：One explicit resolved/unresolved/censored/invalidated receipt member.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `receipt` | `ForeignKey` |  |  |  |  | ForecastCalibrationSampleReceiptModel |
| `expected_member` | `ForeignKey` |  |  |  |  | ForecastCalibrationExpectedMemberModel |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `entry_id` | `CharField` |  |  |  |  |  |
| `expected_member_hash` | `CharField` |  |  |  |  |  |
| `owner_record_version` | `CharField` |  |  |  |  |  |
| `owner_record_hash` | `CharField` |  |  |  |  |  |
| `scenario_revision_id` | `UUIDField` |  |  |  |  |  |
| `scenario_set_revision_id` | `UUIDField` |  |  |  |  |  |
| `pit_manifest_id` | `CharField` |  |  |  |  |  |
| `published_at` | `DateTimeField` |  |  |  |  |  |
| `horizon_end` | `DateTimeField` |  |  |  |  |  |
| `entry_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `resolution` | `CharField` |  |  |  |  |  |
| `scenario_realized` | `BooleanField` | 是 |  |  |  |  |
| `outcome_recorded_at` | `DateTimeField` | 是 |  |  |  |  |
| `outcome_source_type` | `CharField` |  |  |  |  |  |
| `outcome_source_hash` | `CharField` |  |  |  |  |  |
| `invalidation_payload` | `JSONField` | 是 |  |  |  |  |
| `invalidated_at` | `DateTimeField` | 是 |  |  |  |  |
| `invalidation_rule_version` | `CharField` |  |  |  |  |  |
| `invalidation_content_hash` | `CharField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `content_hash` | `CharField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### ForecastCalibrationSampleReceiptModel

- 来源文件：`apps/signal/infrastructure/forecast_calibration_sample_models.py`
- 数据表：`signal_forecast_calibration_sample_receipt`
- 说明：One exhaustive PIT reread receipt for a canonical definition.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `definition` | `ForeignKey` |  |  |  |  | ForecastCalibrationSampleDefinitionModel |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `receipt_id` | `CharField` |  |  |  |  |  |
| `pit_as_of` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### ForecastEvaluation

- 来源文件：`apps/signal/infrastructure/forecast_models.py`
- 数据表：`signal_forecast_evaluation`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `evaluation_id` | `CharField` |  |  |  |  |  |
| `entry` | `ForeignKey` |  |  |  |  | ForecastLedgerEntry |
| `checked_at` | `DateTimeField` |  |  |  |  |  |
| `data_version_ids` | `JSONField` |  |  | list |  |  |
| `conditions` | `JSONField` |  |  | list |  |  |
| `triggered` | `BooleanField` |  |  | False |  |  |
| `first_triggered_at` | `DateTimeField` | 是 |  |  |  |  |
| `status_transition` | `CharField` |  |  |  |  |  |
| `missing_reason` | `TextField` |  |  |  |  |  |
| `idempotency_key` | `CharField` |  | 是 |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### ForecastLedgerEntry

- 来源文件：`apps/signal/infrastructure/forecast_models.py`
- 数据表：`signal_forecast_ledger_entry`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `entry_id` | `CharField` |  |  |  |  |  |
| `signal` | `OneToOneField` | 是 |  |  | signal.InvestmentSignalModel | signal.InvestmentSignalModel |
| `published_at` | `DateTimeField` |  |  |  |  |  |
| `direction` | `CharField` |  |  |  |  |  |
| `asset_code` | `CharField` |  |  |  |  |  |
| `horizon_end` | `DateTimeField` |  |  |  |  |  |
| `benchmark_asset` | `CharField` |  |  |  |  |  |
| `probability` | `FloatField` |  |  |  |  |  |
| `invalidation_rule_version` | `CharField` |  |  |  |  |  |
| `decision_snapshot_id` | `CharField` |  |  |  |  |  |
| `pit_manifest_id` | `CharField` |  |  |  |  |  |
| `strategy_version` | `CharField` |  |  |  |  |  |
| `model_version` | `CharField` |  |  |  |  |  |
| `prompt_version` | `CharField` |  |  |  |  |  |
| `source` | `CharField` |  |  |  |  |  |
| `regime` | `CharField` |  |  |  |  |  |
| `scenario_revision_id` | `UUIDField` | 是 |  |  |  |  |
| `scenario_set_revision_id` | `UUIDField` | 是 |  |  |  |  |
| `subjective_probability` | `DecimalField` | 是 |  |  |  |  |
| `subjective_probability_source_version` | `CharField` |  |  |  |  |  |
| `model_probability` | `DecimalField` | 是 |  |  |  |  |
| `model_probability_source_version` | `CharField` |  |  |  |  |  |
| `model_promotion_decision_id` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  | open |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### ForecastOutcome

- 来源文件：`apps/signal/infrastructure/forecast_models.py`
- 数据表：`signal_forecast_outcome`

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `entry` | `OneToOneField` |  |  |  |  | ForecastLedgerEntry |
| `outcome_type` | `CharField` |  |  |  |  |  |
| `finalized_at` | `DateTimeField` |  |  |  |  |  |
| `asset_return` | `FloatField` | 是 |  |  |  |  |
| `benchmark_return` | `FloatField` | 是 |  |  |  |  |
| `excess_return` | `FloatField` | 是 |  |  |  |  |
| `hit` | `BooleanField` | 是 |  |  |  |  |
| `brier_score` | `FloatField` | 是 |  |  |  |  |
| `scenario_realized` | `BooleanField` | 是 |  |  |  |  |
| `subjective_brier_score` | `FloatField` | 是 |  |  |  |  |
| `model_brier_score` | `FloatField` | 是 |  |  |  |  |
| `evidence` | `JSONField` |  |  | dict |  |  |

### ForecastRealizationAppendOnlyModel

- 来源文件：`apps/signal/infrastructure/forecast_realization_models.py`
- 抽象模型：是
- 说明：Permit only one repository-claimed insert and no mutation/deletion.

### ForecastRealizationManifestModel

- 来源文件：`apps/signal/infrastructure/forecast_realization_models.py`
- 数据表：`signal_forecast_realization_manifest`
- 说明：One complete Signal-owned realization period manifest.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `manifest_version` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  | signal.forecast_ledger |  |  |
| `owner_record_id` | `CharField` |  |  |  |  |  |
| `owner_record_version` | `CharField` |  |  |  |  |  |
| `result_id` | `CharField` |  |  |  |  |  |
| `result_version` | `CharField` |  |  |  |  |  |
| `result_hash` | `CharField` |  |  |  |  |  |
| `calendar_id` | `CharField` |  |  |  |  |  |
| `calendar_version` | `CharField` |  |  |  |  |  |
| `period_id` | `CharField` |  |  |  |  |  |
| `period_version` | `CharField` |  |  |  |  |  |
| `period_hash` | `CharField` |  |  |  |  |  |
| `period_start` | `DateTimeField` |  |  |  |  |  |
| `period_end` | `DateTimeField` |  |  |  |  |  |
| `pit_as_of` | `DateTimeField` |  |  |  |  |  |
| `available_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `evidence_ref` | `CharField` |  |  |  |  |  |
| `source_manifest_hash` | `CharField` |  |  |  |  |  |
| `payload_hash` | `CharField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### ForecastRealizationReceiptModel

- 来源文件：`apps/signal/infrastructure/forecast_realization_models.py`
- 数据表：`signal_forecast_realization_receipt`
- 说明：One exact ForecastOutcome-derived member receipt.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `manifest` | `ForeignKey` |  |  |  |  | ForecastRealizationManifestModel |
| `entry` | `ForeignKey` |  |  |  | signal.ForecastLedgerEntry | signal.ForecastLedgerEntry |
| `receipt_id` | `CharField` |  | 是 |  |  |  |
| `receipt_version` | `CharField` |  |  |  |  |  |
| `observation_id` | `CharField` |  | 是 |  |  |  |
| `observation_version` | `CharField` |  |  |  |  |  |
| `observation_hash` | `CharField` |  | 是 |  |  |  |
| `forecast_group_id` | `CharField` |  |  |  |  |  |
| `scenario_revision_id` | `UUIDField` |  |  |  |  |  |
| `scenario_set_revision_id` | `UUIDField` | 是 |  |  |  |  |
| `subjective_probability` | `DecimalField` |  |  |  |  |  |
| `subjective_probability_source_version` | `CharField` |  |  |  |  |  |
| `model_probability` | `DecimalField` | 是 |  |  |  |  |
| `model_probability_source_version` | `CharField` |  |  |  |  |  |
| `model_promotion_decision_id` | `CharField` |  |  |  |  |  |
| `pit_manifest_id` | `CharField` |  |  |  |  |  |
| `pit_manifest_version` | `CharField` |  |  |  |  |  |
| `pit_manifest_hash` | `CharField` |  |  |  |  |  |
| `censoring_rule_version` | `CharField` |  |  |  |  |  |
| `published_at` | `DateTimeField` |  |  |  |  |  |
| `horizon_end` | `DateTimeField` |  |  |  |  |  |
| `scenario_realized` | `BooleanField` |  |  |  |  |  |
| `outcome_recorded_at` | `DateTimeField` |  |  |  |  |  |
| `outcome_evidence_valid_until` | `DateTimeField` |  |  |  |  |  |
| `available_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `evidence_ref` | `CharField` |  |  |  |  |  |
| `member_source_hash` | `CharField` |  |  |  |  |  |
| `source_outcome_hash` | `CharField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### ForecastRealizationSourceDefinitionMemberModel

- 来源文件：`apps/signal/infrastructure/forecast_realization_models.py`
- 数据表：`signal_forecast_realization_source_definition_member`
- 说明：One exact outcome-free member selector within a source definition.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `definition` | `ForeignKey` |  |  |  |  | ForecastRealizationSourceDefinitionModel |
| `entry_id` | `CharField` |  |  |  |  |  |
| `observation_id` | `CharField` |  |  |  |  |  |
| `observation_version` | `CharField` |  |  |  |  |  |
| `expected_observation_hash` | `CharField` |  |  |  |  |  |
| `forecast_group_id` | `CharField` |  |  |  |  |  |
| `pit_manifest_version` | `CharField` |  |  |  |  |  |
| `pit_manifest_hash` | `CharField` |  |  |  |  |  |
| `censoring_rule_version` | `CharField` |  |  |  |  |  |
| `outcome_evidence_valid_until` | `DateTimeField` |  |  |  |  |  |
| `available_at` | `DateTimeField` |  |  |  |  |  |
| `evidence_ref` | `CharField` |  |  |  |  |  |
| `content_hash` | `CharField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### ForecastRealizationSourceDefinitionModel

- 来源文件：`apps/signal/infrastructure/forecast_realization_models.py`
- 数据表：`signal_forecast_realization_source_definition`
- 说明：One versioned Signal-owned result/calendar/period source definition.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `definition_version` | `CharField` |  |  |  |  |  |
| `owner` | `CharField` |  |  | signal.forecast_ledger |  |  |
| `owner_record_id` | `CharField` |  |  |  |  |  |
| `owner_record_version` | `CharField` |  |  |  |  |  |
| `result_id` | `CharField` |  |  |  |  |  |
| `result_version` | `CharField` |  |  |  |  |  |
| `result_hash` | `CharField` |  |  |  |  |  |
| `calendar_id` | `CharField` |  |  |  |  |  |
| `calendar_version` | `CharField` |  |  |  |  |  |
| `period_id` | `CharField` |  |  |  |  |  |
| `period_version` | `CharField` |  |  |  |  |  |
| `period_hash` | `CharField` |  |  |  |  |  |
| `period_start` | `DateTimeField` |  |  |  |  |  |
| `period_end` | `DateTimeField` |  |  |  |  |  |
| `available_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `evidence_ref` | `CharField` |  |  |  |  |  |
| `source_content_hash` | `CharField` |  |  |  |  |  |
| `registered_at` | `DateTimeField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `research_only` | `BooleanField` |  |  | True |  |  |
| `must_not_use_for_decision` | `BooleanField` |  |  | True |  |  |
| `must_not_execute` | `BooleanField` |  |  | True |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### InvestmentSignalModel

- 来源文件：`apps/signal/infrastructure/models.py`
- 数据表：`investment_signal`
- 说明：投资信号 ORM 模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` | 是 |  |  | NULL表示系统模板信号 | User |
| `asset_code` | `CharField` |  |  |  |  |  |
| `asset_class` | `CharField` |  |  |  |  |  |
| `direction` | `CharField` |  |  |  |  |  |
| `logic_desc` | `TextField` |  |  |  |  |  |
| `invalidation_rule_json` | `JSONField` | 是 |  |  | 结构化证伪规则 (InvalidationRule.to_dict()) |  |
| `invalidation_description` | `TextField` |  |  |  | 证伪逻辑的人类可读描述 |  |
| `invalidation_logic` | `TextField` |  |  |  | [DEPRECATED] 请使用 invalidation_description |  |
| `invalidation_threshold` | `FloatField` | 是 |  |  | [DEPRECATED] 请使用 invalidation_rule_json |  |
| `invalidation_rules` | `JSONField` | 是 |  | dict | [DEPRECATED] 请使用 invalidation_rule_json |  |
| `target_regime` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  | pending |  |  |
| `rejection_reason` | `TextField` |  |  |  |  |  |
| `invalidated_at` | `DateTimeField` | 是 |  |  |  |  |
| `invalidation_details` | `JSONField` | 是 |  |  | 证伪时的详细数据 |  |
| `backtest_performance_score` | `FloatField` | 是 |  |  | 基于历史回测的信号表现评分 (0-100) |  |
| `backtest_count` | `IntegerField` |  |  | 0 | 该信号参与回测的次数 |  |
| `avg_backtest_return` | `FloatField` | 是 |  |  | 该信号在所有回测中的平均收益率 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### UnifiedSignalModel

- 来源文件：`apps/signal/infrastructure/models.py`
- 数据表：`unified_signal`
- 说明：统一信号表（汇总各模块信号）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `signal_date` | `DateField` |  |  |  | 信号日期 |  |
| `signal_source` | `CharField` |  |  |  | 信号来源 |  |
| `signal_type` | `CharField` |  |  |  | 信号类型 |  |
| `asset_code` | `CharField` |  |  |  | 如 ASSET_CODE、ETF_CODE 等 |  |
| `asset_name` | `CharField` |  |  |  | 资产名称 |  |
| `target_weight` | `DecimalField` | 是 |  |  | 建议配置权重 (0-1) |  |
| `current_weight` | `DecimalField` | 是 |  |  | 当前配置权重 |  |
| `priority` | `IntegerField` |  |  | 5 | 1-10，数字越大越重要 |  |
| `is_executed` | `BooleanField` |  |  | False | 是否已执行 |  |
| `executed_at` | `DateTimeField` | 是 |  |  | 执行时间 |  |
| `reason` | `TextField` |  |  |  | 信号生成的详细原因 |  |
| `action_required` | `CharField` |  |  |  | 建议采取的操作 |  |
| `extra_data` | `JSONField` |  |  | dict | 特定模块的额外信息 |  |
| `related_signal_id` | `CharField` |  |  |  | 原始模块中的信号ID |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |


## simulated_trading

### AutomaticTradingInvocationModel

- 来源文件：`apps/simulated_trading/infrastructure/automatic_trading_invocation_models.py`
- 数据表：`simulated_auto_trading_invocation`
- 说明：Persist one caller-owned automatic run identity and its terminal result.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `invocation_id` | `UUIDField` |  | 是 | uuid4 |  |  |
| `namespace` | `CharField` |  |  |  |  |  |
| `invocation_key` | `CharField` |  |  |  |  |  |
| `request_hash` | `CharField` |  |  |  |  |  |
| `request_payload` | `JSONField` |  |  |  |  |  |
| `trade_date` | `DateField` |  |  |  |  |  |
| `account_ids` | `JSONField` |  |  |  |  |  |
| `state` | `CharField` |  |  | STATE_READY |  |  |
| `claim_token` | `UUIDField` | 是 |  |  |  |  |
| `outcome_payload` | `JSONField` | 是 |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |
| `started_at` | `DateTimeField` | 是 |  |  |  |  |
| `finished_at` | `DateTimeField` | 是 |  |  |  |  |

### SimulatedFeeCorrectionEventModel

- 来源文件：`apps/simulated_trading/infrastructure/fee_correction_event_models.py`
- 数据表：`simulated_fee_correction_event`
- 说明：Immutable evidence, revision, and cash-delta event for one simulated Trade.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `account` | `ForeignKey` |  |  |  |  | SimulatedAccountModel |
| `trade` | `ForeignKey` |  |  |  |  | SimulatedTradeModel |
| `actor_user` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `revision` | `PositiveIntegerField` |  |  |  |  |  |
| `account_revision` | `PositiveBigIntegerField` |  |  |  |  |  |
| `account_predecessor_hash` | `CharField` |  |  |  |  |  |
| `account_prefix_hash` | `CharField` |  |  |  |  |  |
| `previous_event` | `ForeignKey` | 是 |  |  | self | self |
| `idempotency_key` | `CharField` |  |  |  |  |  |
| `request_payload_hash` | `CharField` |  |  |  |  |  |
| `trade_snapshot_hash` | `CharField` |  |  |  |  |  |
| `receipt_snapshot_hash` | `CharField` | 是 |  |  |  |  |
| `source_namespace` | `CharField` |  |  |  |  |  |
| `source_record_id` | `CharField` |  |  |  |  |  |
| `verifier_identity` | `CharField` |  |  |  |  |  |
| `source_evidence_hash` | `CharField` |  |  |  |  |  |
| `source_payload_hash` | `CharField` |  |  |  |  |  |
| `source_observed_at` | `DateTimeField` |  |  |  |  |  |
| `evidence_verified_at` | `DateTimeField` |  |  |  |  |  |
| `authority_identity` | `CharField` |  |  |  |  |  |
| `authority_record_id` | `CharField` |  |  |  |  |  |
| `authority_hash` | `CharField` |  |  |  |  |  |
| `authority_snapshot_json` | `JSONField` | 是 |  |  |  |  |
| `authority_snapshot_sha256` | `CharField` | 是 |  |  |  |  |
| `previous_commission` | `DecimalField` |  |  |  |  |  |
| `previous_transfer_fee` | `DecimalField` |  |  |  |  |  |
| `previous_stamp_duty` | `DecimalField` |  |  |  |  |  |
| `revised_commission` | `DecimalField` |  |  |  |  |  |
| `revised_transfer_fee` | `DecimalField` |  |  |  |  |  |
| `revised_stamp_duty` | `DecimalField` |  |  |  |  |  |
| `original_slippage` | `DecimalField` |  |  |  |  |  |
| `commission_delta` | `DecimalField` |  |  |  |  |  |
| `transfer_fee_delta` | `DecimalField` |  |  |  |  |  |
| `stamp_duty_delta` | `DecimalField` |  |  |  |  |  |
| `total_fee_delta` | `DecimalField` |  |  |  |  |  |
| `cash_delta` | `DecimalField` |  |  |  |  |  |
| `posted_at` | `DateTimeField` |  |  |  |  |  |
| `posting_date` | `DateField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### FeeCorrectionEvidenceArtifactModel

- 来源文件：`apps/simulated_trading/infrastructure/fee_correction_evidence_models.py`
- 数据表：`sim_fee_correction_evidence_artifact`
- 说明：One immutable upload with original bytes and exact parsed-row metadata.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `account` | `ForeignKey` |  |  |  |  | SimulatedAccountModel |
| `uploaded_by` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `original_filename` | `CharField` |  |  |  |  |  |
| `assurance_class` | `CharField` |  |  | _ASSURANCE_OPERATOR_ATTESTED_UPLOAD |  |  |
| `schema_version` | `CharField` |  |  |  |  |  |
| `raw_bytes` | `BinaryField` |  |  |  |  |  |
| `content_sha256` | `CharField` |  |  |  |  |  |
| `payload_sha256` | `CharField` |  |  |  |  |  |
| `raw_row_json` | `JSONField` |  |  |  |  |  |
| `parsed_metadata_json` | `JSONField` |  |  |  |  |  |
| `uploaded_at` | `DateTimeField` |  |  |  |  |  |

### FeeCorrectionEvidenceBindingModel

- 来源文件：`apps/simulated_trading/infrastructure/fee_correction_evidence_models.py`
- 数据表：`sim_fee_correction_evidence_binding`
- 说明：Immutable operator attestation binding one artifact to one exact Trade.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `public_id` | `UUIDField` |  | 是 | uuid.uuid4 |  |  |
| `account` | `ForeignKey` |  |  |  |  | SimulatedAccountModel |
| `trade` | `ForeignKey` |  |  |  |  | SimulatedTradeModel |
| `artifact` | `ForeignKey` |  |  |  |  | FeeCorrectionEvidenceArtifactModel |
| `policy` | `ForeignKey` |  |  |  |  | FeeCorrectionEvidencePolicyModel |
| `idempotency_key` | `CharField` |  |  |  |  |  |
| `attested_by` | `ForeignKey` |  |  |  |  | settings.AUTH_USER_MODEL |
| `attestation_version` | `CharField` |  |  |  |  |  |
| `attestation_acknowledged` | `BooleanField` |  |  | False |  |  |
| `assurance_class` | `CharField` |  |  | _ASSURANCE_OPERATOR_ATTESTED_UPLOAD |  |  |
| `expected_revision` | `PositiveIntegerField` |  |  |  |  |  |
| `expected_predecessor_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `content_sha256` | `CharField` |  |  |  |  |  |
| `payload_sha256` | `CharField` |  |  |  |  |  |
| `trade_snapshot_sha256` | `CharField` |  |  |  |  |  |
| `policy_version` | `PositiveIntegerField` |  |  |  |  |  |
| `policy_sha256` | `CharField` |  |  |  |  |  |
| `policy_snapshot_json` | `JSONField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### FeeCorrectionEvidencePolicyModel

- 来源文件：`apps/simulated_trading/infrastructure/fee_correction_evidence_models.py`
- 数据表：`sim_fee_correction_evidence_policy`
- 说明：Per-account qualification policy; all assurance classes default denied.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `account` | `OneToOneField` |  |  |  |  | SimulatedAccountModel |
| `enabled` | `BooleanField` |  |  | False |  |  |
| `allow_operator_attested_upload` | `BooleanField` |  |  | False |  |  |
| `ledger_currency` | `CharField` |  |  |  |  |  |
| `version` | `PositiveIntegerField` |  |  | 1 |  |  |
| `valid_from` | `DateTimeField` | 是 |  |  |  |  |
| `valid_until` | `DateTimeField` | 是 |  |  |  |  |
| `updated_by` | `ForeignKey` | 是 |  |  |  | settings.AUTH_USER_MODEL |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### AccountBenchmarkComponentModel

- 来源文件：`apps/simulated_trading/infrastructure/models.py`
- 数据表：`account_benchmark_component`
- 说明：账户基准成分配置

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `account` | `ForeignKey` |  |  |  | 所属账户 | SimulatedAccountModel |
| `benchmark_code` | `CharField` |  |  |  | 如 000300.SH |  |
| `weight` | `FloatField` |  |  |  | 归一化后总和为 1.0 |  |
| `display_name` | `CharField` |  |  |  | 如 沪深300 |  |
| `sort_order` | `IntegerField` |  |  | 0 | 排序 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### AccountPositionValuationSnapshotModel

- 来源文件：`apps/simulated_trading/infrastructure/models.py`
- 数据表：`account_position_valuation_snapshot`
- 说明：账户持仓时点估值快照

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `account` | `ForeignKey` |  |  |  | 所属账户 | SimulatedAccountModel |
| `record_date` | `DateField` |  |  |  | 记录日期 |  |
| `asset_code` | `CharField` |  |  |  | 资产代码 |  |
| `asset_name` | `CharField` |  |  |  | 资产名称 |  |
| `asset_type` | `CharField` |  |  |  | 资产类型 |  |
| `quantity` | `DecimalField` |  |  |  | 持仓数量 |  |
| `avg_cost` | `DecimalField` |  |  | 0 | 平均成本（元） |  |
| `close_price` | `DecimalField` |  |  | 0 | 收盘价（元） |  |
| `market_value` | `DecimalField` |  |  |  | 市值（元） |  |
| `weight` | `FloatField` |  |  | 0.0 | 仓位占比（市值/总市值） |  |
| `unrealized_pnl` | `DecimalField` |  |  | 0 | 浮动盈亏（元） |  |
| `unrealized_pnl_pct` | `FloatField` |  |  | 0.0 | 浮动盈亏率（%） |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### DailyInspectionNotificationConfigModel

- 来源文件：`apps/simulated_trading/infrastructure/models.py`
- 数据表：`simulated_daily_inspection_notify_config`
- 说明：日更巡检邮件通知配置（账户维度）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `account` | `OneToOneField` |  |  |  | 所属账户 | SimulatedAccountModel |
| `is_enabled` | `BooleanField` |  |  | True | 启用邮件通知 |  |
| `notify_on` | `CharField` |  |  | warning_error | 触发级别 |  |
| `include_owner_email` | `BooleanField` |  |  | True | 包含账户所有者邮箱 |  |
| `recipient_emails` | `JSONField` |  |  | list | 额外收件人 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### DailyInspectionReportModel

- 来源文件：`apps/simulated_trading/infrastructure/models.py`
- 数据表：`simulated_daily_inspection_report`
- 说明：日更巡检报告（账户维度）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `account` | `ForeignKey` |  |  |  | 所属账户 | SimulatedAccountModel |
| `strategy` | `ForeignKey` | 是 |  |  | 关联策略 | strategy.StrategyModel |
| `position_rule` | `ForeignKey` | 是 |  |  | 仓位规则 | strategy.PositionManagementRuleModel |
| `inspection_date` | `DateField` |  |  |  | 巡检日期 |  |
| `status` | `CharField` |  |  | ok | 巡检状态 |  |
| `macro_regime` | `CharField` |  |  |  | 宏观象限 |  |
| `policy_gear` | `CharField` |  |  |  | 政策档位 |  |
| `total_value` | `DecimalField` |  |  | 0 | 账户总资产 |  |
| `current_cash` | `DecimalField` |  |  | 0 | 账户现金 |  |
| `current_market_value` | `DecimalField` |  |  | 0 | 持仓市值 |  |
| `checks` | `JSONField` |  |  | list | 巡检明细 |  |
| `summary` | `JSONField` |  |  | dict | 巡检汇总 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### DailyNetValueModel

- 来源文件：`apps/simulated_trading/infrastructure/models.py`
- 数据表：`simulated_daily_net_value`
- 说明：每日净值记录模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `account` | `ForeignKey` |  |  |  | 所属账户 | SimulatedAccountModel |
| `record_date` | `DateField` |  |  |  | 记录日期 |  |
| `correction_event_watermark` | `PositiveBigIntegerField` | 是 |  |  | 首次写入时已纳入的最大账户内费用更正序号；历史行为空表示覆盖范围未知。 |  |
| `correction_event_watermark_sha256` | `CharField` | 是 |  |  | 已纳入费用更正事件前缀摘要 |  |
| `net_value` | `DecimalField` |  |  |  | 账户总资产（元） |  |
| `cash` | `DecimalField` |  |  |  | 可用现金（元） |  |
| `market_value` | `DecimalField` |  |  |  | 持仓市值（元） |  |
| `daily_return` | `FloatField` |  |  | 0.0 | 相对于前一日的收益率 |  |
| `cumulative_return` | `FloatField` |  |  | 0.0 | 相对于初始资金的收益率 |  |
| `drawdown` | `FloatField` |  |  | 0.0 | 相对于历史最高点的回撤 |  |
| `total_trades` | `IntegerField` |  |  | 0 | 当日交易次数 |  |
| `positions_count` | `IntegerField` |  |  | 0 | 持仓数量 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### FeeConfigModel

- 来源文件：`apps/simulated_trading/infrastructure/models.py`
- 数据表：`simulated_fee_config`
- 说明：交易费率配置模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `config_name` | `CharField` |  | 是 |  | 配置名称 |  |
| `asset_type` | `CharField` |  |  | all | 资产类型 |  |
| `commission_rate_buy` | `FloatField` |  |  | 0.0003 | 默认0.03% |  |
| `commission_rate_sell` | `FloatField` |  |  | 0.0003 | 默认0.03% |  |
| `min_commission` | `FloatField` |  |  |  | 不足按此收取 |  |
| `stamp_duty_rate` | `FloatField` |  |  | 0.001 | 默认0.1%,仅股票 |  |
| `transfer_fee_rate` | `FloatField` |  |  | 2e-05 | 默认0.002% |  |
| `min_transfer_fee` | `FloatField` |  |  | 0.0 | 最低过户费(元) |  |
| `slippage_rate` | `FloatField` |  |  | 0.001 | 默认0.1% |  |
| `is_default` | `BooleanField` |  |  | False | 是否为默认配置 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `description` | `TextField` |  |  |  | 配置说明 |  |
| `fee_policy_id` | `CharField` | 是 |  |  |  |  |
| `fee_policy_version` | `PositiveIntegerField` | 是 |  |  |  |  |
| `fee_policy_account_scope` | `CharField` | 是 |  |  |  |  |
| `fee_policy_effective_from` | `DateTimeField` | 是 |  |  |  |  |
| `fee_policy_valid_until` | `DateTimeField` | 是 |  |  |  |  |
| `fee_policy_transaction_cases` | `JSONField` | 是 |  |  |  |  |
| `fee_policy_content_hash` | `CharField` | 是 |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### LedgerMigrationMapModel

- 来源文件：`apps/simulated_trading/infrastructure/models.py`
- 数据表：`ledger_migration_map`
- 说明：账本迁移映射表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `source_app` | `CharField` |  |  | account | 来源应用 |  |
| `source_table` | `CharField` |  |  |  | 来源表 |  |
| `source_id` | `IntegerField` |  |  |  | 来源ID |  |
| `target_table` | `CharField` |  |  |  | 目标表 |  |
| `target_id` | `IntegerField` |  |  |  | 目标ID |  |
| `migrated_at` | `DateTimeField` |  |  |  | 迁移时间 |  |
| `notes` | `CharField` |  |  |  | 备注 |  |

### NotificationHistoryModel

- 来源文件：`apps/simulated_trading/infrastructure/models.py`
- 数据表：`simulated_notification_history`
- 说明：通知历史记录模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `account` | `ForeignKey` | 是 |  |  | 关联账户 | SimulatedAccountModel |
| `rebalance_proposal` | `ForeignKey` | 是 |  |  | 关联再平衡建议 | RebalanceProposalModel |
| `notification_type` | `CharField` |  |  |  | 如: daily_inspection, rebalance_proposal, position_invalidated |  |
| `channel` | `CharField` |  |  |  | 通知通道 |  |
| `recipient_user_id` | `IntegerField` | 是 |  |  | 接收者用户ID |  |
| `recipient_email` | `EmailField` | 是 |  |  | 接收者邮箱 |  |
| `subject` | `CharField` |  |  |  | 通知主题 |  |
| `body` | `TextField` |  |  |  | 通知内容 |  |
| `status` | `CharField` |  |  | STATUS_PENDING | 发送状态 |  |
| `error_message` | `TextField` |  |  |  | 错误信息 |  |
| `retry_count` | `IntegerField` |  |  | 0 | 重试次数 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `sent_at` | `DateTimeField` | 是 |  |  | 发送时间 |  |
| `metadata` | `JSONField` |  |  | dict | 元数据 |  |

### RebalanceProposalModel

- 来源文件：`apps/simulated_trading/infrastructure/models.py`
- 数据表：`simulated_rebalance_proposal`
- 说明：再平衡建议草案模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `account` | `ForeignKey` |  |  |  | 所属账户 | SimulatedAccountModel |
| `inspection_report` | `ForeignKey` | 是 |  |  | 关联巡检报告 | DailyInspectionReportModel |
| `strategy` | `ForeignKey` | 是 |  |  | 关联策略 | strategy.StrategyModel |
| `source` | `CharField` |  |  | SOURCE_DAILY_INSPECTION | 建议来源 |  |
| `source_description` | `TextField` |  |  |  | 建议生成的原因说明 |  |
| `status` | `CharField` |  |  | STATUS_PENDING | 执行状态 |  |
| `priority` | `CharField` |  |  | normal | 优先级 |  |
| `proposals` | `JSONField` |  |  | list | 再平衡建议列表:         [             {                 "asset_code": "512880.SH",                 "asset_name": "证券ETF",                 "action": "buy" \| "sell" \| "hold",                 "current_quantity": 1000,                 "current_weight": 0.25,                 "target_weight": 0.30,                 "suggested_quantity": 200,                 "reason": "仓位偏离目标",                 "estimated_amount": 5000.00             }         ]          |  |
| `summary` | `JSONField` |  |  | dict | 汇总信息:         {             "total_value": 100000.00,             "current_cash": 5000.00,             "rebalance_assets": ["512880.SH", "515050.SH"],             "buy_count": 2,             "sell_count": 1,             "estimated_trade_amount": 15000.00         }          |  |
| `proposed_by` | `CharField` |  |  | system | 谁创建了这个建议 |  |
| `proposed_at` | `DateTimeField` |  |  |  | 建议时间 |  |
| `reviewed_by` | `CharField` |  |  |  | 审核人 |  |
| `reviewed_at` | `DateTimeField` | 是 |  |  | 审核时间 |  |
| `review_comment` | `TextField` |  |  |  | 审核意见 |  |
| `executed_by` | `CharField` |  |  |  | 执行人 |  |
| `executed_at` | `DateTimeField` | 是 |  |  | 执行时间 |  |
| `execution_result` | `JSONField` | 是 |  |  | 实际执行的交易结果 |  |
| `metadata` | `JSONField` |  |  | dict | 额外的上下文信息 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### UnifiedAccountCashFlowModel

- 来源文件：`apps/simulated_trading/infrastructure/models.py`
- 数据表：`unified_account_cash_flow`
- 说明：统一账户外部现金流

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `account` | `ForeignKey` |  |  |  | 所属账户 | SimulatedAccountModel |
| `flow_type` | `CharField` |  |  |  | 现金流类型 |  |
| `amount` | `DecimalField` |  |  |  | 正数=入金，负数=出金 |  |
| `flow_date` | `DateField` |  |  |  | 发生日期 |  |
| `source_app` | `CharField` |  |  |  | account 或 simulated_trading |  |
| `source_id` | `CharField` |  |  |  | 来源记录ID |  |
| `notes` | `CharField` |  |  |  | 备注 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### SimulatedOrderFillReceiptModel

- 来源文件：`apps/simulated_trading/infrastructure/order_fill_receipt_models.py`
- 数据表：`simulated_order_fill_receipt`
- 说明：Bind one immutable source event and economics snapshot to one Trade row.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `reservation` | `ForeignKey` |  |  |  |  | SimulatedOrderReservationModel |
| `trade` | `OneToOneField` |  |  |  |  | SimulatedTradeModel |
| `fill_sequence` | `PositiveIntegerField` |  |  |  |  |  |
| `source_namespace` | `CharField` |  |  |  |  |  |
| `source_version` | `CharField` |  |  |  |  |  |
| `source_event_id` | `CharField` |  |  |  |  |  |
| `event_kind` | `CharField` |  |  |  |  |  |
| `source_event_payload` | `JSONField` |  |  |  |  |  |
| `source_event_payload_hash` | `CharField` |  |  |  |  |  |
| `source_event_snapshot_hash` | `CharField` |  |  |  |  |  |
| `economic_request_hash` | `CharField` |  |  |  |  |  |
| `economics_snapshot_hash` | `CharField` |  |  |  |  |  |
| `plan_snapshot_hash` | `CharField` |  |  |  |  |  |
| `economics_payload` | `JSONField` |  |  |  |  |  |
| `receipt_hash` | `CharField` |  |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `receipt_version` | `PositiveSmallIntegerField` |  |  | 1 |  |  |
| `initial_position_mark_evidence` | `JSONField` | 是 |  |  |  |  |

### SimulatedOrderReservationModel

- 来源文件：`apps/simulated_trading/infrastructure/order_reservation_models.py`
- 数据表：`simulated_order_reservation`
- 说明：One immutable order request and its conserved, currently held resources.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `account` | `ForeignKey` |  |  |  |  | SimulatedAccountModel |
| `owner_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `idempotency_key` | `CharField` |  |  |  |  |  |
| `intent_payload_hash` | `CharField` |  |  |  |  |  |
| `reservation_request_hash` | `CharField` |  |  |  |  |  |
| `security_id` | `CharField` |  |  |  |  |  |
| `asset_code` | `CharField` |  |  |  |  |  |
| `asset_name` | `CharField` |  |  |  |  |  |
| `side` | `CharField` |  |  |  |  |  |
| `asset_type` | `CharField` |  |  |  |  |  |
| `market` | `CharField` |  |  |  |  |  |
| `board` | `CharField` |  |  |  |  |  |
| `quantity` | `DecimalField` |  |  |  |  |  |
| `limit_price` | `DecimalField` |  |  |  |  |  |
| `notional` | `DecimalField` |  |  |  |  |  |
| `fee_estimate` | `DecimalField` |  |  |  |  |  |
| `fee_budget` | `DecimalField` | 是 |  |  |  |  |
| `commission_estimate` | `DecimalField` |  |  |  |  |  |
| `transfer_fee_estimate` | `DecimalField` |  |  |  |  |  |
| `stamp_duty_estimate` | `DecimalField` |  |  |  |  |  |
| `slippage_estimate` | `DecimalField` |  |  |  |  |  |
| `cash_reserved` | `DecimalField` |  |  |  |  |  |
| `shares_reserved` | `DecimalField` |  |  |  |  |  |
| `filled_quantity` | `DecimalField` |  |  | 0 |  |  |
| `cash_consumed` | `DecimalField` |  |  | 0 |  |  |
| `shares_consumed` | `DecimalField` |  |  | 0 |  |  |
| `cash_released` | `DecimalField` |  |  | 0 |  |  |
| `shares_released` | `DecimalField` |  |  | 0 |  |  |
| `fee_policy_id` | `CharField` |  |  |  |  |  |
| `fee_policy_version` | `PositiveIntegerField` |  |  |  |  |  |
| `fee_config_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `fee_policy_hash` | `CharField` |  |  |  |  |  |
| `plan_snapshot_version` | `PositiveSmallIntegerField` |  |  | 1 |  |  |
| `plan_snapshot` | `JSONField` |  |  |  |  |  |
| `plan_snapshot_hash` | `CharField` |  |  |  |  |  |
| `source_book_cash` | `DecimalField` | 是 |  |  |  |  |
| `source_sellable_quantity` | `DecimalField` | 是 |  |  |  |  |
| `source_snapshot_at` | `DateTimeField` |  |  |  |  |  |
| `market_session` | `DateField` |  |  |  |  |  |
| `settlement_lag_sessions` | `PositiveSmallIntegerField` |  |  |  |  |  |
| `settlement_release_date` | `DateField` | 是 |  |  |  |  |
| `reserved_at` | `DateTimeField` |  |  |  |  |  |
| `status` | `CharField` |  |  | STATUS_ACTIVE |  |  |
| `cancelled_at` | `DateTimeField` | 是 |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### SimulatedAccountRawObservationModel

- 来源文件：`apps/simulated_trading/infrastructure/simulated_account_raw_observation_models.py`
- 数据表：`simulated_account_raw_observation_ledger`
- 说明：One immutable owner-observed physical SimulatedAccount row record.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `observation_id` | `CharField` |  |  |  |  |  |
| `observation_version` | `CharField` |  |  |  |  |  |
| `row_pk` | `PositiveBigIntegerField` |  |  |  |  |  |
| `row_user_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `raw_account_type` | `CharField` |  |  |  |  |  |
| `is_active` | `BooleanField` |  |  |  |  |  |
| `row_created_at` | `DateTimeField` |  |  |  |  |  |
| `row_updated_at` | `DateTimeField` |  |  |  |  |  |
| `is_present` | `BooleanField` |  |  |  |  |  |
| `is_tombstone` | `BooleanField` |  |  |  |  |  |
| `observed_at` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 |  |  |  |  |
| `root_claim_hash` | `CharField` | 是 |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `authority_seal` | `CharField` |  |  |  |  |  |
| `row_seal` | `CharField` |  |  |  |  |  |
| `clock_seal` | `CharField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### SimulatedAccountRowSourceModel

- 来源文件：`apps/simulated_trading/infrastructure/simulated_account_row_source_models.py`
- 数据表：`simulated_account_row_source_ledger`
- 说明：One immutable actor-bound SimulatedTrading source ledger record.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `source_id` | `CharField` |  |  |  |  |  |
| `source_version` | `CharField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `row_user_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `raw_account_type` | `CharField` |  |  |  |  |  |
| `is_active` | `BooleanField` |  |  |  |  |  |
| `row_created_at` | `DateTimeField` |  |  |  |  |  |
| `row_updated_at` | `DateTimeField` |  |  |  |  |  |
| `is_present` | `BooleanField` |  |  |  |  |  |
| `is_tombstone` | `BooleanField` |  |  |  |  |  |
| `observed_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `source_valid_until` | `DateTimeField` |  |  |  |  |  |
| `ttl_valid_until` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `owner_assignment_state` | `CharField` |  |  |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 |  |  |  |  |
| `root_claim_hash` | `CharField` | 是 |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `captured_actor_id` | `CharField` |  |  |  |  |  |
| `captured_actor_user_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `captured_actor_role` | `CharField` |  |  |  |  |  |
| `captured_actor_kind` | `CharField` |  |  |  |  |  |
| `captured_actor_is_staff` | `BooleanField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `row_fact_hash` | `CharField` |  |  |  |  |  |
| `logical_binding_hash` | `CharField` |  |  |  |  |  |
| `actor_binding_hash` | `CharField` |  | 是 |  |  |  |
| `record_header_hash` | `CharField` |  | 是 |  |  |  |
| `ledger_header_hash` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### SimulatedAccountRowSourceV2Model

- 来源文件：`apps/simulated_trading/infrastructure/simulated_account_row_source_v2_models.py`
- 数据表：`simulated_account_row_source_v2_ledger`
- 说明：One immutable owner-observed physical SimulatedAccount row record.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `CharField` |  |  |  |  |  |
| `artifact_type` | `CharField` |  |  |  |  |  |
| `schema` | `CharField` |  |  |  |  |  |
| `source_id` | `CharField` |  |  |  |  |  |
| `source_version` | `CharField` |  |  |  |  |  |
| `account_namespace` | `CharField` |  |  |  |  |  |
| `account_id` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_namespace` | `CharField` |  |  |  |  |  |
| `underlying_unified_account_id` | `PositiveBigIntegerField` |  |  |  |  |  |
| `row_user_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `raw_account_type` | `CharField` |  |  |  |  |  |
| `is_active` | `BooleanField` |  |  |  |  |  |
| `row_created_at` | `DateTimeField` |  |  |  |  |  |
| `row_updated_at` | `DateTimeField` |  |  |  |  |  |
| `is_present` | `BooleanField` |  |  |  |  |  |
| `is_tombstone` | `BooleanField` |  |  |  |  |  |
| `observed_at` | `DateTimeField` |  |  |  |  |  |
| `recorded_at` | `DateTimeField` |  |  |  |  |  |
| `source_valid_until` | `DateTimeField` |  |  |  |  |  |
| `ttl_valid_until` | `DateTimeField` |  |  |  |  |  |
| `valid_until` | `DateTimeField` |  |  |  |  |  |
| `raw_observation_id` | `CharField` |  |  |  |  |  |
| `raw_observation_version` | `CharField` |  |  |  |  |  |
| `raw_observation_identity_hash` | `CharField` |  |  |  |  |  |
| `raw_observation_content_hash` | `CharField` |  |  |  |  |  |
| `raw_observation_observed_at` | `DateTimeField` |  |  |  |  |  |
| `raw_observation_valid_until` | `DateTimeField` |  |  |  |  |  |
| `raw_observation_supersedes_content_hash` | `CharField` | 是 |  |  |  |  |
| `owner_assignment_state` | `CharField` |  |  |  |  |  |
| `raw_observation_owner` | `CharField` |  |  |  |  |  |
| `raw_observation_artifact_type` | `CharField` |  |  |  |  |  |
| `raw_observation_schema` | `CharField` |  |  |  |  |  |
| `supersedes_content_hash` | `CharField` | 是 |  |  |  |  |
| `root_claim_hash` | `CharField` | 是 |  |  |  |  |
| `permission` | `CharField` |  |  |  |  |  |
| `status` | `CharField` |  |  |  |  |  |
| `canonical_payload` | `JSONField` |  |  |  |  |  |
| `identity_hash` | `CharField` |  | 是 |  |  |  |
| `content_hash` | `CharField` |  | 是 |  |  |  |
| `raw_binding_seal` | `CharField` |  | 是 |  |  |  |
| `row_seal` | `CharField` |  |  |  |  |  |
| `logical_seal` | `CharField` |  |  |  |  |  |
| `clock_seal` | `CharField` |  |  |  |  |  |
| `record_seal` | `CharField` |  | 是 |  |  |  |
| `ledger_seal` | `CharField` |  | 是 |  |  |  |
| `persisted_at` | `DateTimeField` |  |  |  |  |  |

### PositionModel

- 来源文件：`apps/simulated_trading/infrastructure/simulated_account_trade_models.py`
- 数据表：`simulated_position`
- 说明：持仓模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `account` | `ForeignKey` |  |  |  | 所属账户 | SimulatedAccountModel |
| `asset_code` | `CharField` |  |  |  | 资产代码 |  |
| `asset_name` | `CharField` |  |  |  | 资产名称 |  |
| `asset_type` | `CharField` |  |  |  | 资产类型 |  |
| `quantity` | `DecimalField` |  |  |  | 持仓数量 |  |
| `available_quantity` | `DecimalField` |  |  |  | 可卖数量 |  |
| `available_quantity_known` | `BooleanField` |  |  | True | 可卖数量是否已知 |  |
| `avg_cost` | `DecimalField` |  |  |  | 平均成本(元) |  |
| `total_cost` | `DecimalField` |  |  |  | 总成本(元) |  |
| `cost_basis_known` | `BooleanField` | 是 |  | None | 成本基数是否已知 |  |
| `current_price` | `DecimalField` |  |  |  | 当前价格(元) |  |
| `market_value` | `DecimalField` |  |  |  | 市值(元) |  |
| `valuation_known` | `BooleanField` |  |  | True | 持仓估值是否已知 |  |
| `unrealized_pnl` | `DecimalField` |  |  | 0 | 浮动盈亏(元) |  |
| `unrealized_pnl_pct` | `FloatField` |  |  | 0.0 | 浮动盈亏率(%) |  |
| `first_buy_date` | `DateField` |  |  |  | 首次买入日期 |  |
| `first_buy_date_known` | `BooleanField` |  |  | True | 首次买入日期是否已知 |  |
| `last_update_date` | `DateField` |  |  |  | 最后更新日期 |  |
| `signal_id` | `IntegerField` | 是 |  |  | 关联信号ID |  |
| `entry_reason` | `CharField` |  |  |  | 入场原因 |  |
| `invalidation_rule_json` | `JSONField` | 是 |  |  | 从信号继承的结构化证伪规则 |  |
| `invalidation_description` | `TextField` |  |  |  | 人类可读的证伪条件描述 |  |
| `is_invalidated` | `BooleanField` |  |  | False | 证伪条件已满足，建议平仓 |  |
| `invalidation_reason` | `TextField` |  |  |  | 证伪原因说明 |  |
| `invalidation_checked_at` | `DateTimeField` | 是 |  |  | 最后一次检查证伪条件的时间 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### SimulatedAccountModel

- 来源文件：`apps/simulated_trading/infrastructure/simulated_account_trade_models.py`
- 数据表：`simulated_account`
- 说明：投资组合账户模型（统一）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` | 是 |  |  | 用户 | settings.AUTH_USER_MODEL |
| `account_name` | `CharField` |  |  |  | 账户名称 |  |
| `account_type` | `CharField` |  |  | simulated | 账户类型 |  |
| `initial_capital` | `DecimalField` |  |  |  | 初始资金(元) |  |
| `current_cash` | `DecimalField` |  |  |  | 当前现金(元) |  |
| `cash_known` | `BooleanField` |  |  | False | 现金余额是否有依据 |  |
| `cash_reconciliation_status` | `CharField` |  |  | unverified | 现金核对状态 |  |
| `current_market_value` | `DecimalField` |  |  | 0 | 当前持仓市值(元) |  |
| `total_value` | `DecimalField` |  |  |  | 总资产(元) |  |
| `total_return` | `FloatField` |  |  | 0.0 | 总收益率(%) |  |
| `annual_return` | `FloatField` |  |  | 0.0 | 年化收益率(%) |  |
| `max_drawdown` | `FloatField` |  |  | 0.0 | 最大回撤(%) |  |
| `sharpe_ratio` | `FloatField` |  |  | 0.0 | 夏普比率 |  |
| `win_rate` | `FloatField` |  |  | 0.0 | 胜率(%) |  |
| `total_trades` | `IntegerField` |  |  | 0 | 总交易次数 |  |
| `winning_trades` | `IntegerField` |  |  | 0 | 盈利交易次数 |  |
| `start_date` | `DateField` |  |  |  | 开始日期 |  |
| `last_trade_date` | `DateField` | 是 |  |  | 最后交易日期 |  |
| `is_active` | `BooleanField` |  |  | True | 是否激活 |  |
| `auto_trading_enabled` | `BooleanField` |  |  | True | 启用自动交易 |  |
| `max_position_pct` | `FloatField` |  |  | 20.0 | 单资产最大持仓比例(%) |  |
| `max_total_position_pct` | `FloatField` |  |  | 95.0 | 总持仓比例上限(%) |  |
| `stop_loss_pct` | `FloatField` | 是 |  |  | 止损比例(%) |  |
| `commission_rate` | `FloatField` |  |  | 0.0003 | 手续费率 |  |
| `slippage_rate` | `FloatField` |  |  | 0.001 | 滑点率 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### SimulatedTradeModel

- 来源文件：`apps/simulated_trading/infrastructure/simulated_account_trade_models.py`
- 数据表：`simulated_trade`
- 说明：模拟交易记录模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `account` | `ForeignKey` |  |  |  | 所属账户 | SimulatedAccountModel |
| `asset_code` | `CharField` |  |  |  | 资产代码 |  |
| `asset_name` | `CharField` |  |  |  | 资产名称 |  |
| `asset_type` | `CharField` |  |  |  | 资产类型 |  |
| `action` | `CharField` |  |  |  | 交易动作 |  |
| `quantity` | `DecimalField` |  |  |  | 交易数量 |  |
| `price` | `DecimalField` |  |  |  | 成交价格(元) |  |
| `amount` | `DecimalField` |  |  |  | 成交金额(元) |  |
| `commission` | `DecimalField` |  |  | 0 | 手续费(元) |  |
| `transfer_fee` | `DecimalField` | 是 |  |  | 过户费(元) |  |
| `stamp_duty` | `DecimalField` | 是 |  |  | 印花税(元) |  |
| `slippage` | `DecimalField` |  |  | 0 | 滑点损失(元) |  |
| `total_cost` | `DecimalField` |  |  |  | 总成本(元) |  |
| `fee_amounts_known` | `BooleanField` | 是 |  | None | 费用金额是否完整已知 |  |
| `cost_basis_known` | `BooleanField` | 是 |  | None | 成本基数是否已知 |  |
| `realized_pnl` | `DecimalField` | 是 |  |  | 已实现盈亏(元) |  |
| `realized_pnl_pct` | `FloatField` | 是 |  |  | 已实现盈亏率(%) |  |
| `reason` | `CharField` |  |  |  | 交易原因 |  |
| `signal_id` | `IntegerField` | 是 |  |  | 关联信号ID |  |
| `order_date` | `DateField` |  |  |  | 订单日期 |  |
| `execution_date` | `DateField` |  |  |  | 执行日期 |  |
| `execution_time` | `DateTimeField` |  |  | timezone.now | 执行时间 |  |
| `status` | `CharField` |  |  | pending | 订单状态 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `idempotency_key` | `CharField` | 是 |  |  |  |  |
| `request_payload_hash` | `CharField` | 是 |  |  |  |  |
| `fee_config_id` | `PositiveBigIntegerField` | 是 |  |  |  |  |
| `fee_schedule_hash` | `CharField` | 是 |  |  |  |  |
| `fee_schedule_snapshot` | `JSONField` | 是 |  |  |  |  |
| `fee_precision_basis` | `CharField` | 是 |  |  |  |  |
| `fee_calculation_purpose` | `CharField` | 是 |  |  |  |  |
| `fee_rounding_policy` | `CharField` | 是 |  |  |  |  |
| `settlement_status` | `CharField` | 是 |  |  |  |  |
| `settlement_security_id` | `CharField` | 是 |  |  |  |  |
| `settlement_market` | `CharField` | 是 |  |  |  |  |
| `settlement_exchange` | `CharField` | 是 |  |  |  |  |
| `settlement_board` | `CharField` | 是 |  |  |  |  |
| `settlement_market_session` | `DateField` | 是 |  |  |  |  |
| `settlement_lag_sessions` | `PositiveIntegerField` | 是 |  |  |  |  |
| `settlement_plan_binding_version` | `PositiveSmallIntegerField` |  |  | 0 |  |  |
| `settlement_plan_binding_payload` | `JSONField` | 是 |  |  |  |  |
| `settlement_plan_binding_hash` | `CharField` | 是 |  |  |  |  |
| `settlement_bundle_id` | `CharField` | 是 |  |  |  |  |
| `settlement_bundle_version` | `CharField` | 是 |  |  |  |  |
| `settlement_bundle_hash` | `CharField` | 是 |  |  |  |  |
| `settlement_policy_id` | `CharField` | 是 |  |  |  |  |
| `settlement_policy_version` | `CharField` | 是 |  |  |  |  |
| `settlement_policy_hash` | `CharField` | 是 |  |  |  |  |
| `execution_rule_v2_hash` | `CharField` | 是 |  |  |  |  |
| `settlement_release_date` | `DateField` | 是 |  |  |  |  |
| `settlement_calendar_snapshot_id` | `CharField` | 是 |  |  |  |  |
| `settlement_calendar_content_hash` | `CharField` | 是 |  |  |  |  |
| `settlement_calendar_record_digest` | `CharField` | 是 |  |  |  |  |
| `settlement_calendar_publication_id` | `CharField` | 是 |  |  |  |  |
| `settlement_calendar_publication_hash` | `CharField` | 是 |  |  |  |  |
| `settlement_calendar_policy_hash` | `CharField` | 是 |  |  |  |  |
| `settlement_calendar_evidence_hash` | `CharField` | 是 |  |  |  |  |
| `settlement_calendar_timezone` | `CharField` | 是 |  |  |  |  |
| `settlement_released_at` | `DateTimeField` | 是 |  |  |  |  |
| `settlement_release_session` | `DateField` | 是 |  |  |  |  |
| `settlement_release_calendar_snapshot_id` | `CharField` | 是 |  |  |  |  |
| `settlement_release_calendar_content_hash` | `CharField` | 是 |  |  |  |  |
| `settlement_release_calendar_record_digest` | `CharField` | 是 |  |  |  |  |
| `settlement_release_calendar_publication_id` | `CharField` | 是 |  |  |  |  |
| `settlement_release_calendar_publication_hash` | `CharField` | 是 |  |  |  |  |
| `settlement_release_calendar_policy_hash` | `CharField` | 是 |  |  |  |  |
| `settlement_release_calendar_evidence_hash` | `CharField` | 是 |  |  |  |  |
| `settlement_release_calendar_timezone` | `CharField` | 是 |  |  |  |  |
| `settlement_release_proof_payload` | `JSONField` | 是 |  | None |  |  |
| `settlement_release_proof_hash` | `CharField` | 是 |  | None |  |  |


## strategy

### AIStrategyConfigModel

- 来源文件：`apps/strategy/infrastructure/models.py`
- 数据表：`ai_strategy_config`
- 说明：AI 策略配置

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `strategy` | `OneToOneField` |  |  |  | 所属策略 | StrategyModel |
| `prompt_template` | `ForeignKey` | 是 |  |  | Prompt模板 | prompt.PromptTemplateORM |
| `chain_config` | `ForeignKey` | 是 |  |  | 链配置 | prompt.ChainConfigORM |
| `ai_provider` | `ForeignKey` | 是 |  |  | AI服务商 | ai_provider.AIProviderConfig |
| `temperature` | `FloatField` |  |  | 0.7 | 温度参数 |  |
| `max_tokens` | `IntegerField` |  |  | 2000 | 最大Token数 |  |
| `approval_mode` | `CharField` |  |  | conditional | 审核模式 |  |
| `confidence_threshold` | `FloatField` |  |  | 0.8 | 置信度高于此值时自动执行 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### AllocationPolicyAdjustmentModel

- 来源文件：`apps/strategy/infrastructure/models.py`
- 数据表：`strategy_allocation_policy_adjustment`
- 说明：Policy-level multipliers stored with an allocation-policy version.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `policy_version` | `ForeignKey` |  |  |  | 策略版本 | AllocationPolicyVersionModel |
| `policy_level` | `CharField` |  |  |  | Policy 档位 |  |
| `equity_multiplier` | `DecimalField` |  |  |  | 权益乘数 |  |
| `expected_return_multiplier` | `DecimalField` |  |  | 1 | 预期收益乘数 |  |
| `expected_volatility_multiplier` | `DecimalField` |  |  | 1 | 预期波动乘数 |  |
| `sharpe_multiplier` | `DecimalField` |  |  | 1 | Sharpe 乘数 |  |

### AllocationPolicyEntryModel

- 来源文件：`apps/strategy/infrastructure/models.py`
- 数据表：`strategy_allocation_policy_entry`
- 说明：One regime/risk-profile cell in an allocation-policy version.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `policy_version` | `ForeignKey` |  |  |  | 策略版本 | AllocationPolicyVersionModel |
| `regime` | `CharField` |  |  |  | Regime |  |
| `risk_profile` | `CharField` |  |  |  | 风险偏好 |  |
| `equity` | `DecimalField` |  |  |  | 权益权重 |  |
| `fixed_income` | `DecimalField` |  |  |  | 固收权重 |  |
| `commodity` | `DecimalField` |  |  |  | 商品权重 |  |
| `cash` | `DecimalField` |  |  |  | 现金权重 |  |
| `reasoning` | `TextField` |  |  |  | 配置理由 |  |
| `expected_return` | `DecimalField` | 是 |  |  | 预期年化收益 |  |
| `expected_volatility` | `DecimalField` | 是 |  |  | 预期波动率 |  |
| `sharpe_ratio` | `DecimalField` | 是 |  |  | 夏普比率 |  |
| `statistics_status` | `CharField` |  |  | StatisticsStatus.NOT_PROVIDED | 统计假设状态 |  |
| `research_evidence_id` | `CharField` | 是 |  |  | 研究证据 ID |  |

### AllocationPolicyVersionModel

- 来源文件：`apps/strategy/infrastructure/models.py`
- 数据表：`strategy_allocation_policy_version`
- 说明：Immutable Strategy-owned asset-allocation policy revision.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `policy_key` | `CharField` |  |  |  | 配置标识 |  |
| `version` | `PositiveIntegerField` |  |  |  | 版本号 |  |
| `status` | `CharField` |  |  | Status.DRAFT | 状态 |  |
| `content_hash` | `CharField` |  |  |  | 内容哈希 |  |
| `source_type` | `CharField` |  |  |  | 来源类型 |  |
| `source_metadata` | `JSONField` |  |  | dict | 来源元数据 |  |
| `change_reason` | `TextField` |  |  |  | 变更原因 |  |
| `based_on_version` | `PositiveIntegerField` | 是 |  |  | 基于版本 |  |
| `created_by` | `ForeignKey` | 是 |  |  | 创建者 | account.AccountProfileModel |
| `activated_by` | `ForeignKey` | 是 |  |  | 激活者 | account.AccountProfileModel |
| `effective_at` | `DateTimeField` | 是 |  |  | 生效时间 |  |
| `activated_at` | `DateTimeField` | 是 |  |  | 激活时间 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |

### PortfolioStrategyAssignmentModel

- 来源文件：`apps/strategy/infrastructure/models.py`
- 数据表：`portfolio_strategy_assignment`
- 说明：投资组合与策略的关联

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `portfolio` | `ForeignKey` |  |  |  | 投资组合 | simulated_trading.SimulatedAccountModel |
| `strategy` | `ForeignKey` |  |  |  | 策略 | StrategyModel |
| `assigned_at` | `DateTimeField` |  |  |  | 分配时间 |  |
| `assigned_by` | `ForeignKey` |  |  |  | 分配者 | account.AccountProfileModel |
| `is_active` | `BooleanField` |  |  | True | 是否激活 |  |
| `override_max_position_pct` | `FloatField` | 是 |  |  | 覆盖单资产最大持仓比例(%) |  |
| `override_stop_loss_pct` | `FloatField` | 是 |  |  | 覆盖止损比例(%) |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### PositionManagementRuleModel

- 来源文件：`apps/strategy/infrastructure/models.py`
- 数据表：`position_management_rule`
- 说明：仓位管理规则（数据库驱动，不在代码中硬编码价格规则）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `strategy` | `OneToOneField` |  |  |  | 所属策略 | StrategyModel |
| `name` | `CharField` |  |  |  | 规则名称 |  |
| `description` | `TextField` |  |  |  | 规则描述 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `price_precision` | `PositiveSmallIntegerField` |  |  | 2 | 价格精度 |  |
| `variables_schema` | `JSONField` |  |  | list |  |  |
| `buy_condition_expr` | `TextField` |  |  |  | 示例: current_price <= support_price and volume_ratio >= 1.2 |  |
| `sell_condition_expr` | `TextField` |  |  |  | 示例: current_price >= resistance_price or regime_score < 0.4 |  |
| `buy_price_expr` | `TextField` |  |  |  | 示例: breakout_price * (1 + slippage_pct) |  |
| `sell_price_expr` | `TextField` |  |  |  | 示例: buy_price * (1 + target_return_pct) |  |
| `stop_loss_expr` | `TextField` |  |  |  | 示例: min(structure_low, buy_price - 2 * atr) |  |
| `take_profit_expr` | `TextField` |  |  |  | 示例: buy_price + 2 * (buy_price - stop_loss_price) |  |
| `position_size_expr` | `TextField` |  |  |  | 示例: (account_equity * risk_per_trade_pct) / abs(buy_price - stop_loss_price) |  |
| `metadata` | `JSONField` |  |  | dict |  |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### RuleConditionModel

- 来源文件：`apps/strategy/infrastructure/models.py`
- 数据表：`rule_condition`
- 说明：规则条件（用于 rule_based 策略）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `strategy` | `ForeignKey` |  |  |  | 所属策略 | StrategyModel |
| `rule_name` | `CharField` |  |  |  | 规则名称 |  |
| `rule_type` | `CharField` |  |  |  | 规则类型 |  |
| `condition_json` | `JSONField` |  |  |  | JSON格式: 支持AND/OR/NOT、比较运算、趋势判断 |  |
| `action` | `CharField` |  |  |  | 动作 |  |
| `weight` | `FloatField` | 是 |  |  | 目标权重 |  |
| `target_assets` | `JSONField` |  |  | list | 空列表表示所有可投资产 |  |
| `priority` | `IntegerField` |  |  | 0 | 优先级 |  |
| `is_enabled` | `BooleanField` |  |  | True | 是否启用 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### ScriptConfigModel

- 来源文件：`apps/strategy/infrastructure/models.py`
- 数据表：`script_config`
- 说明：脚本配置（用于 script_based 策略）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `strategy` | `OneToOneField` |  |  |  | 所属策略 | StrategyModel |
| `script_language` | `CharField` |  |  | python | 脚本语言 |  |
| `script_code` | `TextField` |  |  |  | 脚本代码 |  |
| `script_hash` | `CharField` |  |  |  | SHA256哈希，用于检测脚本变更 |  |
| `sandbox_config` | `JSONField` |  |  | dict | 沙箱安全策略配置 |  |
| `allowed_modules` | `JSONField` |  |  | list | 允许导入的模块白名单 |  |
| `version` | `CharField` |  |  | 1.0 | 版本号 |  |
| `is_active` | `BooleanField` |  |  | True | 是否激活 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### StrategyExecutionLogModel

- 来源文件：`apps/strategy/infrastructure/models.py`
- 数据表：`strategy_execution_log`
- 说明：策略执行日志

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `strategy` | `ForeignKey` |  |  |  | 策略 | StrategyModel |
| `portfolio` | `ForeignKey` |  |  |  | 投资组合 | simulated_trading.SimulatedAccountModel |
| `execution_time` | `DateTimeField` |  |  |  | 执行时间 |  |
| `execution_duration_ms` | `IntegerField` |  |  |  | 执行时长(ms) |  |
| `execution_result` | `JSONField` |  |  |  | 详细执行信息 |  |
| `signals_generated` | `JSONField` |  |  | list | 信号列表 |  |
| `error_message` | `TextField` |  |  |  | 错误信息 |  |
| `error_traceback` | `TextField` |  |  |  | 错误堆栈 |  |
| `is_success` | `BooleanField` |  |  | True | 是否成功 |  |

### StrategyModel

- 来源文件：`apps/strategy/infrastructure/models.py`
- 数据表：`strategy`
- 说明：策略主表

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | `CharField` |  |  |  | 策略名称 |  |
| `description` | `TextField` |  |  |  | 策略描述 |  |
| `strategy_type` | `CharField` |  |  |  | 策略类型 |  |
| `version` | `PositiveIntegerField` |  |  | 1 | 版本号 |  |
| `is_active` | `BooleanField` |  |  | True | 是否激活 |  |
| `max_position_pct` | `FloatField` |  |  | 20.0 | 单资产最大持仓比例(%) |  |
| `max_total_position_pct` | `FloatField` |  |  | 95.0 | 总持仓比例上限(%) |  |
| `stop_loss_pct` | `FloatField` | 是 |  |  | 止损比例(%) |  |
| `created_by` | `ForeignKey` |  |  |  | 创建者 | account.AccountProfileModel |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### StrategyParamVersionModel

- 来源文件：`apps/strategy/infrastructure/models.py`
- 数据表：`strategy_param_version`
- 说明：策略参数版本配置（支持参数回滚）

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `strategy` | `ForeignKey` |  |  |  | 所属策略 | StrategyModel |
| `version` | `PositiveIntegerField` |  |  |  | 版本号 |  |
| `params_json` | `JSONField` |  |  |  | 策略参数的JSON序列化 |  |
| `is_active` | `BooleanField` |  |  | False | 同一策略只能有一个激活版本 |  |
| `promotion_decision_id` | `CharField` | 是 |  |  | 启用研究门禁后必须引用已批准的 research PromotionDecision |  |
| `change_description` | `TextField` |  |  |  | 记录本次参数变更的原因和内容 |  |
| `changed_by` | `ForeignKey` | 是 |  |  | 变更者 | account.AccountProfileModel |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |


## task_monitor

### TaskAlertModel

- 来源文件：`apps/task_monitor/infrastructure/models.py`
- 说明：任务告警记录模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `level` | `CharField` |  |  |  | 告警级别 |  |
| `task_id` | `CharField` |  |  |  | 任务ID |  |
| `task_name` | `CharField` |  |  |  | 任务名称 |  |
| `title` | `CharField` |  |  |  | 告警标题 |  |
| `message` | `TextField` |  |  |  | 告警消息 |  |
| `exception` | `TextField` | 是 |  |  | 异常信息 |  |
| `traceback` | `TextField` | 是 |  |  | 堆栈跟踪 |  |
| `is_sent` | `BooleanField` |  |  | False | 已发送 |  |
| `sent_at` | `DateTimeField` | 是 |  |  | 发送时间 |  |
| `send_error` | `TextField` | 是 |  |  | 发送错误 |  |
| `metadata` | `JSONField` |  |  | dict | 元数据 |  |
| `triggered_at` | `DateTimeField` |  |  |  | 触发时间 |  |

### TaskExecutionModel

- 来源文件：`apps/task_monitor/infrastructure/models.py`
- 说明：任务执行记录模型

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `task_id` | `CharField` |  | 是 |  | 任务ID |  |
| `attempt_id` | `CharField` | 是 |  |  | 执行尝试ID |  |
| `task_name` | `CharField` |  |  |  | 任务名称 |  |
| `status` | `CharField` |  |  |  | 状态 |  |
| `args` | `JSONField` |  |  | list | 位置参数 |  |
| `kwargs` | `JSONField` |  |  | dict | 关键字参数 |  |
| `started_at` | `DateTimeField` | 是 |  |  | 开始时间 |  |
| `finished_at` | `DateTimeField` | 是 |  |  | 完成时间 |  |
| `result` | `TextField` | 是 |  |  | 执行结果 |  |
| `exception` | `TextField` | 是 |  |  | 异常信息 |  |
| `traceback` | `TextField` | 是 |  |  | 堆栈跟踪 |  |
| `runtime_seconds` | `FloatField` | 是 |  |  | 运行时长(秒) |  |
| `retries` | `IntegerField` |  |  | 0 | 重试次数 |  |
| `priority` | `CharField` |  |  | normal | 优先级 |  |
| `queue` | `CharField` | 是 |  |  | 队列名称 |  |
| `worker` | `CharField` | 是 |  |  | Worker 名称 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |


## terminal

### TerminalAuditLogORM

- 来源文件：`apps/terminal/infrastructure/models.py`
- 数据表：`terminal_audit_log`
- 说明：终端审计日志

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `user` | `ForeignKey` | 是 |  |  |  | settings.AUTH_USER_MODEL |
| `username` | `CharField` |  |  |  |  |  |
| `session_id` | `CharField` |  |  |  |  |  |
| `command_name` | `CharField` |  |  |  |  |  |
| `risk_level` | `CharField` |  |  |  |  |  |
| `mode` | `CharField` |  |  |  |  |  |
| `params_summary` | `TextField` |  |  |  |  |  |
| `confirmation_required` | `BooleanField` |  |  | False |  |  |
| `confirmation_status` | `CharField` |  |  | not_required |  |  |
| `result_status` | `CharField` |  |  | pending |  |  |
| `error_message` | `TextField` |  |  |  |  |  |
| `duration_ms` | `IntegerField` |  |  | 0 |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |

### TerminalCommandORM

- 来源文件：`apps/terminal/infrastructure/models.py`
- 数据表：`terminal_command`
- 说明：Terminal command configuration persisted in the terminal app.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `name` | `CharField` |  | 是 |  | 命令名称（如：analyze, report） |  |
| `description` | `TextField` |  |  |  | 命令描述 |  |
| `command_type` | `CharField` |  |  | CommandType.PROMPT.value | 命令类型 |  |
| `prompt_template` | `ForeignKey` | 是 |  |  | 关联的Prompt模板（command_type=prompt时使用） | PromptTemplateORM |
| `system_prompt` | `TextField` |  |  |  | 系统提示词（可选） |  |
| `user_prompt_template` | `TextField` |  |  |  | 用户Prompt模板 |  |
| `api_endpoint` | `CharField` |  |  |  | API端点路径（command_type=api时使用） |  |
| `api_method` | `CharField` |  |  | GET | HTTP方法（GET/POST） |  |
| `response_jq_filter` | `CharField` |  |  |  | JQ过滤器，从API响应中提取数据 |  |
| `parameters` | `JSONField` |  |  | list | 参数定义列表 |  |
| `timeout` | `IntegerField` |  |  | 60 | 超时时间（秒） |  |
| `provider_name` | `CharField` |  |  |  | 默认AI提供商名称 |  |
| `model_name` | `CharField` |  |  |  | 默认模型名称 |  |
| `category` | `CharField` |  |  | general | 命令分类 |  |
| `tags` | `JSONField` |  |  | list | 标签列表 |  |
| `is_active` | `BooleanField` |  |  | True | 是否启用 |  |
| `risk_level` | `CharField` |  |  | TerminalRiskLevel.READ.value | 风险等级 |  |
| `requires_mcp` | `BooleanField` |  |  | True | 是否需要 MCP 权限 |  |
| `enabled_in_terminal` | `BooleanField` |  |  | True | 是否在终端中显示 |  |
| `created_at` | `DateTimeField` |  |  |  | 创建时间 |  |
| `updated_at` | `DateTimeField` |  |  |  | 更新时间 |  |

### TerminalRuntimeSettingsORM

- 来源文件：`apps/terminal/infrastructure/models.py`
- 数据表：`terminal_runtime_settings`
- 说明：Terminal runtime settings singleton.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `singleton_key` | `CharField` |  | 是 | default |  |  |
| `answer_chain_enabled` | `BooleanField` |  |  | True | 是否允许在 Terminal 回答中展开查看答案链条 |  |
| `fallback_chat_system_prompt` | `TextField` |  |  |  | Terminal 与共享网页聊天在 fallback 普通对话时注入的系统提示词。可由管理员控制回答范围，例如系统状态、Regime、持仓、信号、回测、RSS 新闻、政策、热点、配置中心等。留空则使用系统默认提示词。 |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |

### TuiMetadataRegistryORM

- 来源文件：`apps/terminal/infrastructure/models.py`
- 数据表：`terminal_tui_metadata_registry`
- 说明：Published TUI operation metadata registry.

| 字段 | 类型 | null | unique | 默认值 | 说明 | 关系目标 |
| --- | --- | --- | --- | --- | --- | --- |
| `registry_key` | `CharField` |  |  | default |  |  |
| `version` | `CharField` |  |  | tui-workbench.v2 |  |  |
| `schema_version` | `CharField` |  |  | tui-metadata.v3 |  |  |
| `status` | `CharField` |  |  | draft |  |  |
| `review_status` | `CharField` |  |  | pending |  |  |
| `generation_source` | `CharField` |  |  | mixed |  |  |
| `backend_version` | `CharField` |  |  |  |  |  |
| `payload` | `JSONField` |  |  | dict |  |  |
| `source_hash` | `CharField` |  |  |  |  |  |
| `source_evidence_hash` | `CharField` |  |  |  |  |  |
| `changed_fields` | `JSONField` |  |  | list |  |  |
| `review_note` | `TextField` |  |  |  |  |  |
| `rollback_of` | `ForeignKey` | 是 |  |  | self | self |
| `approved_by` | `ForeignKey` | 是 |  |  |  | settings.AUTH_USER_MODEL |
| `published_at` | `DateTimeField` | 是 |  |  |  |  |
| `created_at` | `DateTimeField` |  |  |  |  |  |
| `updated_at` | `DateTimeField` |  |  |  |  |  |
