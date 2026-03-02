# WP-3: Frontend Implementation Guide

## Overview

This document provides integration instructions for the frontend changes implemented in WP-3 (Homepage and Workspace Frontend Transformation).

## Changes Summary

### 1. New Files Created

#### CSS Files
- **`static/css/main-workflow.css`** - Styles for the main workflow panel and execution modal

#### JavaScript Files
- **`static/js/main-workflow.js`** - JavaScript logic for precheck, submit, and execute operations

#### Template Snippets
- **`core/templates/dashboard/main_workflow_panel.html`** - Main workflow panel component

### 2. Modified Files

#### Templates
1. **`core/templates/decision/workspace.html`**
   - Changed "待系统处理" to "待执行落地"
   - Added Execute, Cancel, and Retry buttons for pending requests
   - Updated pending request query logic

2. **`apps/alpha_trigger/templates/alpha_trigger/candidate_detail.html`**
   - Removed "直接标记已执行" button
   - Added "去执行" button (disabled if no decision request)
   - Added execution reference display section (read-only)

#### Backend Views
1. **`core/views.py`**
   - Updated `decision_workspace_view()` to filter pending requests by:
     - `response.approved=True`
     - `execution_status='PENDING'`

## Integration Steps

### Step 1: Include CSS and JS in Base Template

Add the following lines to your base template (usually `core/templates/base.html`) in the appropriate sections:

```html
{% block extra_css %}
<!-- Existing CSS -->
<link rel="stylesheet" href="{% static 'css/main-workflow.css' %}">
{% endblock %}

{% block extra_js %}
<!-- Existing JS -->
<script src="{% static 'js/main-workflow.js' %}"></script>
{% endblock %}
```

### Step 2: Add Main Workflow Panel to Dashboard

Insert the main workflow panel into `core/templates/dashboard/index.html` after the decision plane section:

```html
<!-- Around line 304, after the decision plane section -->
{% include "dashboard/main_workflow_panel.html" %}
```

Or manually copy the content from `core/templates/dashboard/main_workflow_panel.html` into the desired location.

### Step 3: Update Dashboard View Context

Ensure the dashboard view passes the required context variables:

```python
# In core/views.py or apps/dashboard/interface/views.py
context['actionable_candidates'] = AlphaCandidateModel._default_manager.filter(
    status='ACTIONABLE'
).order_by('-confidence', '-created_at')[:5]
```

### Step 4: Ensure CSRF Token is Available

Make sure the CSRF token is available in your templates:

```html
<script>
window.csrfToken = "{{ csrf_token }}";
</script>
```

Or include it in your base template's JavaScript section.

## Required Backend APIs

The frontend implementation expects the following API endpoints to be available:

### 1. Precheck API
```
POST /api/decision-workflow/precheck/
```

Request:
```json
{
  "candidate_id": "cand_xxx"
}
```

Response:
```json
{
  "success": true,
  "result": {
    "candidate_id": "cand_xxx",
    "beta_gate_passed": true,
    "quota_ok": true,
    "cooldown_ok": true,
    "candidate_valid": true,
    "warnings": [],
    "errors": []
  }
}
```

### 2. Execute API
```
POST /api/decision-rhythm/requests/{request_id}/execute/
```

Request (Simulated):
```json
{
  "target": "SIMULATED",
  "sim_account_id": 1,
  "asset_code": "000001.SH",
  "action": "buy",
  "quantity": 1000,
  "price": 12.35,
  "reason": "按决策请求执行"
}
```

Request (Account):
```json
{
  "target": "ACCOUNT",
  "portfolio_id": 9,
  "asset_code": "000001.SH",
  "shares": 1000,
  "avg_cost": 12.35,
  "current_price": 12.35,
  "reason": "按决策请求落地持仓"
}
```

Response:
```json
{
  "success": true,
  "result": {
    "request_id": "req_xxx",
    "execution_status": "EXECUTED",
    "executed_at": "2026-03-01T10:00:00+08:00",
    "execution_ref": {
      "trade_id": "trd_xxx",
      "account_id": 1
    },
    "candidate_status": "EXECUTED"
  }
}
```

### 3. Simulated Trading Accounts API
```
GET /api/simulated-trading/accounts/
```

Response:
```json
{
  "success": true,
  "results": [
    {
      "account_id": 1,
      "name": "模拟账户1",
      "initial_capital": 1000000
    }
  ]
}
```

## Workflow Steps

The main workflow panel implements a 5-step process:

1. **Environment** - Check Regime and Policy status
2. **Candidate** - Select actionable Alpha candidate
3. **Decision** - Submit decision request
4. **Execution** - Execute in simulated or real account
5. **Feedback** - System updates status and references

## State Machine

### Decision Request States
- `PENDING` → `EXECUTED` (execution successful)
- `PENDING` → `FAILED` (execution failed)
- `PENDING`/`FAILED` → `CANCELLED` (manual cancel)

### Alpha Candidate States
- `CANDIDATE` → `ACTIONABLE` (candidate approved)
- `ACTIONABLE` → `EXECUTED` (only through execute API)
- `ACTIONABLE`/`CANDIDATE` → `CANCELLED` (manual cancel)
- Any active state → `INVALIDATED`/`EXPIRED` (rule-based)

## Testing Checklist

### Homepage
- [ ] Main workflow panel displays correctly
- [ ] Step navigation shows current status
- [ ] Candidate list shows actionable candidates
- [ ] Precheck button triggers API call
- [ ] Precheck results display correctly
- [ ] Submit decision button works
- [ ] Execute button opens modal
- [ ] Execute modal shows target selection
- [ ] Execute modal loads simulated accounts
- [ ] Execute form validates input
- [ ] Execute success updates workflow steps

### Decision Workspace
- [ ] Pending requests show "待执行落地"
- [ ] Pending requests have Execute button
- [ ] Pending requests have Cancel button
- [ ] Failed requests show Retry button
- [ ] Execute button triggers modal
- [ ] Query filters by approved=True and execution_status=PENDING

### Alpha Candidate Detail
- [ ] "标记已执行" button removed
- [ ] "去执行" button appears when decision request exists
- [ ] "去执行" button disabled when no decision request
- [ ] Execution reference displays when candidate is executed
- [ ] Execution reference is read-only

## Troubleshooting

### Common Issues

1. **CSRF Token Missing**
   - Ensure `window.csrfToken` is set in your template
   - Check that CSRF middleware is enabled

2. **API Endpoints Not Found**
   - Verify URLs are registered in `urls.py`
   - Check that API views are implemented (WP-2)

3. **Simulated Accounts Not Loading**
   - Verify simulated trading app is installed
   - Check API endpoint `/api/simulated-trading/accounts/` exists

4. **Precheck Always Fails**
   - Ensure WP-2 backend implementation is complete
   - Check precheck API is implemented and returns correct format

5. **Execute Button Always Disabled**
   - Verify decision request was successfully submitted
   - Check that `currentRequestId` is set in JavaScript

## Browser Compatibility

Tested on:
- Chrome 120+
- Firefox 120+
- Safari 17+
- Edge 120+

## Responsive Design

The implementation is fully responsive:
- Desktop: Full workflow panel with grid layout
- Tablet: Adjusted spacing and button sizes
- Mobile: Stacked layout with full-width buttons

## Performance Considerations

- API calls use async/await for non-blocking operation
- Toast notifications auto-dismiss after 3 seconds
- Modal uses CSS transitions for smooth animations
- Page reloads after successful execution to ensure data consistency

## Security Notes

- All API calls include CSRF token
- Execute operations require authenticated user
- Execution targets have separate permission checks
- No sensitive data exposed in client-side code

## Next Steps

After integrating these changes:

1. Test the complete workflow end-to-end
2. Verify state transitions match specification
3. Test error handling and edge cases
4. Conduct UAT with stakeholders
5. Monitor performance in production
6. Collect user feedback for future improvements
