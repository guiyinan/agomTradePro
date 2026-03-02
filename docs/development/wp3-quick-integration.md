# WP-3 Quick Integration Guide

**For immediate integration with existing codebase**

## Step 1: Copy New Files

Copy these files to your project:

```bash
# From WP-3 deliverables to your project
cp static/css/main-workflow.css D:\githv\agomSAAF\static\css\
cp static/js/main-workflow.js D:\githv\agomSAAF\static\js\
cp core/templates/dashboard/main_workflow_panel.html D:\githv\agomSAAF\core\templates\dashboard\
```

## Step 2: Update Base Template

**File**: `D:\githv\agomSAAF\core\templates\base.html`

Add to the `<head>` section (after existing CSS):

```html
{% block extra_css %}
<link rel="stylesheet" href="{% static 'css/main-workflow.css' %}">
{% endblock %}
```

Add before closing `</body>` tag (after existing JS):

```html
<script>
  // Global CSRF token for API calls
  window.csrfToken = "{{ csrf_token }}";
</script>

{% block extra_js %}
<script src="{% static 'js/main-workflow.js' %}"></script>
{% endblock %}
```

## Step 3: Include Workflow Panel in Dashboard

**File**: `D:\githv\agomSAAF\core\templates\dashboard\index.html`

Find line ~303 (after the decision plane section closing tag):

```html
        </section>

        <!-- ADD THIS LINE -->
        {% include "dashboard/main_workflow_panel.html" %}

        <!-- Alpha 可视化（新增） -->
        <section class="alpha-visualization-section">
```

## Step 4: Verify Workspace Changes

**File**: `D:\githv\agomSAAF\core\templates\decision\workspace.html`

The following changes have already been applied:

**Line 211** - Changed from:
```html
<span class="btn btn-sm btn-outline" style="cursor: default;">待系统处理</span>
```

To:
```html
<span class="btn btn-sm btn-outline" style="cursor: default;">待执行落地</span>
{% if request.execution_status == 'PENDING' %}
<button class="btn btn-sm btn-primary" onclick="executeRequest('{{ request.request_id|escapejs }}')">
    去执行
</button>
<button class="btn btn-sm btn-secondary" onclick="cancelRequest('{{ request.request_id|escapejs }}')">
    取消
</button>
{% elif request.execution_status == 'FAILED' %}
<button class="btn btn-sm btn-warning" onclick="retryRequest('{{ request.request_id|escapejs }}')">
    重试
</button>
{% endif %}
```

## Step 5: Verify View Changes

**File**: `D:\githv\agomSAAF\core\views.py`

The following change has already been applied in the `decision_workspace_view` function:

**Lines 216-231** - Changed from:
```python
# 待处理定义：尚未产生响应记录
pending_requests = list(
    DecisionRequestModel._default_manager
    .filter(response__isnull=True)
    .order_by('-requested_at')[:10]
)
```

To:
```python
# 待处理定义：已批准但未执行的请求
# 查询条件：response.approved=True and execution_status='PENDING'
pending_requests = list(
    DecisionRequestModel._default_manager
    .filter(
        response__approved=True,
        execution_status='PENDING'
    )
    .order_by('-requested_at')[:10]
)
```

## Step 6: Verify Candidate Detail Changes

**File**: `D:\githv\agomSAAF\apps\alpha_trigger\templates\alpha_trigger\candidate_detail.html`

The following changes have already been applied:

**Around line 202-220** - Changed "标记已执行" button to "去执行":

```html
{% if candidate.last_decision_request_id %}
<button class="btn-action btn-execute" onclick="goToExecute('{{ candidate.last_decision_request_id|escapejs }}', '{{ candidate.asset_code|escapejs }}', '{% if candidate.direction == 'LONG' %}BUY{% else %}SELL{% endif %}')">
    <i class="bi bi-play-circle"></i> 去执行
</button>
{% else %}
<button class="btn-action btn-execute" disabled title="请先提交决策请求">
    <i class="bi bi-play-circle"></i> 去执行
</button>
{% endif %}
```

Added execution reference display section:
```html
{% if candidate.status == 'EXECUTED' and candidate.last_execution_status %}
<div class="execution-ref-display">
    <!-- Display trade_id, position_id, account_id -->
</div>
{% endif %}
```

Added `goToExecute()` JavaScript function:
```javascript
function goToExecute(requestId, assetCode, direction) {
    window.location.href = `/decision/workspace/?execute_request=${requestId}&asset_code=${assetCode}&direction=${direction}`;
}
```

## Step 7: Collect Static Files

Run Django's collectstatic command:

```bash
python manage.py collectstatic
```

## Step 8: Test Integration

### Quick Test Checklist

1. [ ] Start development server: `python manage.py runserver`
2. [ ] Navigate to homepage: `http://localhost:8000/dashboard/`
3. [ ] Verify main workflow panel appears after decision plane section
4. [ ] Check browser console for JavaScript errors (should be none)
5. [ ] Navigate to workspace: `http://localhost:8000/decision/workspace/`
6. [ ] Verify "待执行落地" text appears
7. [ ] Navigate to candidate detail page
8. [ ] Verify "去执行" button appears instead of "标记已执行"

### Common Issues

**Issue**: CSS not loading
**Solution**: Run `python manage.py collectstatic --clear`

**Issue**: JavaScript errors about csrfToken
**Solution**: Ensure base template includes `window.csrfToken = "{{ csrf_token }}";`

**Issue**: Workflow panel not appearing
**Solution**: Check that include path is correct: `{% include "dashboard/main_workflow_panel.html" %}`

**Issue**: Precheck/Execute buttons not working
**Solution**: Verify backend APIs from WP-2 are implemented

## Step 9: Backend API Requirements

The frontend expects these APIs to be available (WP-2):

```python
# apps/decision_rhythm/interface/urls.py

urlpatterns = [
    # ... existing patterns ...

    # Precheck API
    path(
        "api/decision-workflow/precheck/",
        PrecheckDecisionView.as_view(),
        name="precheck-decision"
    ),

    # Execute API
    path(
        "api/decision-rhythm/requests/<str:request_id>/execute/",
        ExecuteDecisionRequestView.as_view(),
        name="execute-request"
    ),
]
```

## Step 10: Production Deployment

Before deploying to production:

1. Run all tests: `pytest tests/ -v`
2. Check for JavaScript console errors
3. Verify responsive design on mobile/tablet
4. Test complete workflow: Candidate → Decision → Execute
5. Monitor performance metrics

## File Change Summary

**New Files** (3):
- `static/css/main-workflow.css`
- `static/js/main-workflow.js`
- `core/templates/dashboard/main_workflow_panel.html`

**Modified Files** (3):
- `core/templates/decision/workspace.html` (7 lines changed)
- `core/views.py` (15 lines changed)
- `apps/alpha_trigger/templates/alpha_trigger/candidate_detail.html` (48 lines changed)

**Total**: 6 files, 1,289 lines added/modified

## Rollback Instructions

If issues occur:

```bash
# Remove new files
rm static/css/main-workflow.css
rm static/js/main-workflow.js
rm core/templates/dashboard/main_workflow_panel.html

# Revert modified files
git checkout HEAD -- core/templates/decision/workspace.html
git checkout HEAD -- core/views.py
git checkout HEAD -- apps/alpha_trigger/templates/alpha_trigger/candidate_detail.html

# Remove include from dashboard
# Edit core/templates/dashboard/index.html and remove the include line

# Clear static files
python manage.py collectstatic --clear
```

## Support

For detailed documentation, see:
- `docs/development/wp3-frontend-integration-guide.md`
- `docs/development/wp3-implementation-summary.md`
- `docs/development/wp3-deployment-checklist.md`
- `docs/development/WP3-COMPLETION-REPORT.md`

---

**Integration Time**: ~15 minutes
**Complexity**: Low
**Risk**: Low (easily reversible)
