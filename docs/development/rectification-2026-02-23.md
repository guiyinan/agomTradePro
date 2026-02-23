# 外包交付整改报告（2026-02-23）

> 甲方验收日期：2026-02-23
> 整改负责人：外包团队
> 问题来源：甲方验收发现

---

## 一、甲方验收发现的问题

### 问题 1：API 路由契约不完整

**问题描述**：
外包团队在修复 P0 路由冲突时，仅移除了冲突的 `events/` 路由定义，未创建独立的 API 路由文件。导致 `/api/policy/events/` 端点返回 HTML 页面而非 JSON。

**甲方修复方案**：
```python
# 新增 apps/policy/interface/api_urls.py
# 专门用于 API 路由，与页面路由分离
```

**根本原因**：
- 修复思路不完整，只解决了"冲突"表象，未解决"API 契约"本质
- 缺少对 API 端点的契约测试

---

### 问题 2：UpdatePolicyEventUseCase 遗漏 event_id 参数

**问题描述**：
外包团队修复了 `DeletePolicyEventUseCase` 添加 `event_id` 参数，但遗漏了 `UpdatePolicyEventUseCase`。导致更新操作仍可能影响同日其他事件。

**甲方修复方案**：
```python
# UpdatePolicyEventUseCase.execute() 添加 event_id 参数
def execute(
    self,
    event_date: date,
    level: PolicyLevel,
    title: str,
    description: str,
    evidence_url: str,
    event_id: Optional[int] = None  # 新增
) -> CreatePolicyEventOutput:
```

**根本原因**：
- 修复不彻底，只修复了 Delete，未同步修复 Update
- 缺少对"成对操作"的联想思维

---

### 问题 3：缺少 API 契约测试

**问题描述**：
外包团队未添加 API 契约测试，无法验证 `/api/policy/events/` 返回 JSON 而非 HTML。

**甲方新增测试**：
- `test_api_policy_events_endpoint_returns_json_contract`
- `test_delete_policy_event_by_id_only_deletes_target_event`
- `test_update_policy_event_by_id_only_updates_target_event`

**根本原因**：
- Guardrail 测试只检查了"路由不冲突"，未检查"API 返回正确格式"
- 测试覆盖面不足

---

## 二、反思与教训

### 1. 修复不彻底

| 问题 | 外包修复 | 甲方补充 |
|------|----------|----------|
| 路由冲突 | 移除冲突路由 | 创建独立 API 路由文件 |
| 同日事件操作 | 只修复 Delete | 同时修复 Update |
| 测试 | 只测路由不冲突 | 测 API 返回格式、精确操作 |

**教训**：修复问题时，要考虑所有相关场景，不要只修复"眼前"的问题。

### 2. 缺少契约思维

外包团队只关注"功能实现"，未关注"API 契约"：
- API 端点应该返回什么格式？
- 同一操作在不同端点是否一致？

**教训**：API 开发必须以契约为先，先定义契约，再实现功能。

### 3. 测试覆盖不足

Guardrail 测试只覆盖了"防止回归"，未覆盖"契约验证"：
- 缺少 API 格式测试
- 缺少精确操作测试

**教训**：测试要覆盖契约层面，不只是功能层面。

---

## 三、整改措施

### 1. 开发规范更新

在 `outsourcing-work-guidelines.md` 中新增：

```markdown
### API 路由规范

1. **API 与页面路由分离**
   - API 路由必须放在 `api_urls.py` 中
   - 页面路由放在 `urls.py` 中
   - 两者不得混用同一个文件

2. **API 契约测试**
   - 每个 API 端点必须有契约测试
   - 验证返回格式（JSON/HTML）
   - 验证状态码符合预期

3. **成对操作一致性**
   - 如果修复了 Delete 操作，必须同步检查 Update/Create 操作
   - 相似功能的参数签名必须一致
```

### 2. 检查清单更新

在 PR 检查清单中新增：

```markdown
- [ ] API 路由是否与页面路由分离？
- [ ] API 端点是否返回正确的 Content-Type？
- [ ] 是否检查了所有成对操作（CRUD）？
- [ ] 是否添加了契约测试？
```

### 3. 代码审查要点

1. **路由文件检查**：确认 API 和页面路由是否分离
2. **参数一致性检查**：CRUD 操作的参数签名是否一致
3. **契约测试检查**：是否验证了 API 返回格式

---

## 四、费用扣除确认

根据外包合同条款，因甲方自行修复以下问题，扣除相应维修费：

| 问题 | 扣除比例 | 说明 |
|------|----------|------|
| API 路由契约不完整 | 10% | 需创建独立 API 路由文件 |
| UpdateUseCase 遗漏修复 | 5% | 需同步修复成对操作 |
| 缺少契约测试 | 5% | 需添加 API 契约测试 |

**合计扣除：20%**

---

## 五、承诺

外包团队承诺：

1. 后续修复将完整考虑所有相关场景
2. API 开发将遵循"契约先行"原则
3. 测试将覆盖契约层面，不只是功能层面
4. 成对操作将保持一致性

---

**整改日期**：2026-02-23
**整改人**：外包开发团队
