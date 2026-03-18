# WP-3 Deployment Checklist

## Pre-deployment Requirements

### Backend APIs (WP-2)
Before deploying WP-3 frontend changes, ensure these APIs are implemented and tested:

- [ ] `POST /api/decision-workflow/precheck/` - Precheck API
- [ ] `POST /api/decision-rhythm/requests/{request_id}/execute/` - Execute API
- [ ] `GET /api/simulated-trading/accounts/` - Simulated accounts list
- [ ] `POST /api/decision-rhythm/submit/` - Extended with candidate_id and execution_target

### Database Migrations (WP-1)
Ensure these migrations are applied:

- [ ] DecisionRequestModel has execution fields (candidate_id, execution_target, execution_status, executed_at, execution_ref)
- [ ] AlphaCandidateModel has tracking fields (last_decision_request_id, last_execution_status)
- [ ] Historical data backfilled correctly

## Integration Steps

### Step 1: Include Static Files

Add to `core/templates/base.html`:

```html
<head>
  <!-- Existing head content -->
  {% block extra_css %}
  <link rel="stylesheet" href="{% static 'css/main-workflow.css' %}">
  {% endblock %}
</head>
<body>
  <!-- Existing body content -->

  <script>
    // Make CSRF token available globally
    window.csrfToken = "{{ csrf_token }}";
  </script>

  {% block extra_js %}
  <script src="{% static 'js/main-workflow.js' %}"></script>
  {% endblock %}
</body>
```

### Step 2: Add Main Workflow Panel to Dashboard

In `core/templates/dashboard/index.html`, after line 303 (after decision plane section):

```html
        </section>

        <!-- 主流程面板 -->
        {% include "dashboard/main_workflow_panel.html" %}

        <!-- Alpha 可视化（新增） -->
        <section class="alpha-visualization-section">
```

### Step 3: Verify Context Variables

Ensure dashboard view provides these variables:

```python
# In core/views.py or apps/dashboard/interface/views.py
context['actionable_candidates'] = AlphaCandidateModel.objects.filter(
    status='ACTIONABLE'
).order_by('-confidence', '-created_at')[:5]
```

### Step 4: Update URLs (if not already done)

Ensure these URL patterns exist in `apps/decision_rhythm/interface/urls.py`:

```python
urlpatterns = [
    # ... existing patterns ...

    # Execute API (WP-2)
    path(
        "api/decision-rhythm/requests/<str:request_id>/execute/",
        ExecuteDecisionRequestView.as_view(),
        name="execute-request"
    ),
]
```

And create a new URL configuration for precheck:

```python
# In apps/decision_rhythm/interface/urls.py or a new decision_workflow app
path(
    "api/decision-workflow/precheck/",
    PrecheckDecisionView.as_view(),
    name="precheck-decision"
),
```

## Testing Checklist

### Manual Testing

#### Homepage
1. [ ] Navigate to homepage (`/dashboard/`)
2. [ ] Verify main workflow panel appears
3. [ ] Check step navigation shows correct status
4. [ ] Verify actionable candidates display
5. [ ] Click "预检查" button
6. [ ] Verify precheck results appear
7. [ ] Click "提交决策" button
8. [ ] Verify success message
9. [ ] Click "执行" button
10. [ ] Verify modal opens
11. [ ] Select "模拟盘" target
12. [ ] Fill in execution parameters
13. [ ] Click "确认执行"
14. [ ] Verify success and page reload
15. [ ] Check workflow steps updated

#### Decision Workspace
1. [ ] Navigate to workspace (`/decision/workspace/`)
2. [ ] Verify pending requests show "待执行落地"
3. [ ] Verify approved but unexecuted requests appear
4. [ ] Click "去执行" button
5. [ ] Verify execution modal opens
6. [ ] Click "取消" button
7. [ ] Verify request is cancelled
8. [ ] Create a failed execution
9. [ ] Verify "重试" button appears
10. [ ] Click "重试" and verify it works

#### Alpha Candidate Detail
1. [ ] Navigate to candidate detail page
2. [ ] Verify "直接标记已执行" button is removed
3. [ ] Verify "去执行" button appears (if decision request exists)
4. [ ] Click "去执行" button
5. [ ] Verify redirects to workspace with execute modal
6. [ ] Execute the candidate
7. [ ] Return to candidate detail
8. [ ] Verify execution reference displays
9. [ ] Verify trade_id/position_id shown correctly
10. [ ] Verify fields are read-only

### Automated Testing

Run these test suites:

```bash
# Unit tests
pytest tests/unit/test_decision_execution_workflow.py -v
pytest tests/unit/test_alpha_candidate_execution_tracking.py -v

# Integration tests (to be created)
pytest tests/integration/decision_workflow/test_precheck.py -v
pytest tests/integration/decision_workflow/test_execute.py -v

# E2E tests (to be created)
pytest tests/playwright/tests/uat/test_main_workflow.py -v
```

### Browser Testing

Test on these browsers:
- [ ] Chrome (latest)
- [ ] Firefox (latest)
- [ ] Safari (latest)
- [ ] Edge (latest)

Test responsive design:
- [ ] Desktop (1920x1080)
- [ ] Laptop (1366x768)
- [ ] Tablet (768x1024)
- [ ] Mobile (375x667)

## Post-deployment Verification

### System Health Checks

1. [ ] Homepage loads without errors
2. [ ] Workspace loads without errors
3. [ ] Candidate detail pages load without errors
4. [ ] No JavaScript console errors
5. [ ] No CSS loading errors
6. [ ] API endpoints respond correctly
7. [ ] Database queries performant (< 100ms)

### Functional Verification

1. [ ] Complete workflow: Candidate → Decision → Execute → Feedback
2. [ ] Verify state transitions match specification
3. [ ] Verify execution references saved correctly
4. [ ] Verify candidate status updates correctly
5. [ ] Verify decision request status updates correctly
6. [ ] Verify precheck catches blocking conditions
7. [ ] Verify execute modal validates input

### Performance Verification

1. [ ] Homepage loads in < 2 seconds
2. [ ] Workspace loads in < 1 second
3. [ ] API calls complete in < 500ms
4. [ ] No memory leaks (monitor for 1 hour)
5. [ ] No database connection leaks

## Rollback Plan

If issues are discovered:

### Quick Rollback
1. Comment out the include statement in dashboard/index.html:
   ```html
   <!-- {% include "dashboard/main_workflow_panel.html" %} -->
   ```

2. Revert workspace.html changes:
   ```bash
   git checkout HEAD -- core/templates/decision/workspace.html
   ```

3. Revert candidate_detail.html changes:
   ```bash
   git checkout HEAD -- apps/alpha_trigger/templates/alpha_trigger/candidate_detail.html
   ```

4. Restart web server

### Full Rollback
1. Revert all WP-3 commits:
   ```bash
   git revert <commit-hash>
   ```

2. Clear static files cache:
   ```bash
   python manage.py collectstatic --clear
   ```

3. Restart web server and clear browser cache

## Monitoring

After deployment, monitor these metrics:

### Application Metrics
- Page load times (homepage, workspace, candidate detail)
- API response times (precheck, execute)
- Error rates (4xx, 5xx)
- Database query performance

### Business Metrics
- Number of candidates processed
- Number of decisions submitted
- Number of executions completed
- Execution success rate
- Average time from candidate to execution

### User Experience
- User feedback on workflow clarity
- Task completion rate
- Error messages encountered
- Support tickets related to workflow

## Documentation Updates

After successful deployment:

- [ ] Update user guide with new workflow steps
- [ ] Update API documentation with new endpoints
- [ ] Update screenshots in documentation
- [ ] Create training materials for new workflow
- [ ] Update changelog/release notes

## Support Preparation

Prepare for user questions:

- [ ] Create FAQ for new workflow
- [ ] Train support team on new features
- [ ] Prepare demo videos
- [ ] Create troubleshooting guide
- [ ] Set up monitoring alerts

## Success Criteria

Deployment is successful when:

1. ✅ All manual tests pass
2. ✅ All automated tests pass
3. ✅ No critical bugs reported
4. ✅ Performance metrics within bounds
5. ✅ Users can complete full workflow
6. ✅ State machine enforcement works
7. ✅ Execution references saved correctly
8. ✅ No regression in existing features

## Timeline

- **Day 1**: Deploy to staging, run tests
- **Day 2**: UAT with stakeholders
- **Day 3**: Fix any issues, prepare for production
- **Day 4**: Deploy to production (morning)
- **Day 4-7**: Monitor and address issues
- **Day 8**: Post-deployment review

## Contacts

- **Developer**: Claude (AI Assistant)
- **Project Lead**: [Assign]
- **QA Lead**: [Assign]
- **DevOps**: [Assign]
- **Product Owner**: [Assign]

---

**Note**: This checklist assumes WP-1 and WP-2 are fully completed and deployed. Do not deploy WP-3 until backend dependencies are ready.
