# Streamlit Dashboard Upgrade Plan

## 1. Goal

Upgrade the dashboard experience from Django Admin + HTMX patterns to an interactive Streamlit UI focused on:

- Regime quadrant visualization
- Equity curve visualization
- Signal status visualization

This plan uses gradual replacement:

- New Streamlit dashboard is introduced in parallel.
- Django remains the source of truth for business logic and data.
- Existing dashboard endpoints remain compatible during migration.

## 2. Scope

### In scope

- Add Streamlit application skeleton and pages
- Provide stable dashboard v1 APIs in Django
- Add dependencies and developer run instructions
- Keep legacy dashboard available

### Out of scope (current iteration)

- Full replacement of every dashboard feature card
- Reverse proxy/single-domain production routing
- Historical equity snapshot persistence redesign

## 3. Technical Design

### 3.1 Runtime architecture

- Django serves data and authentication (`/dashboard/api/v1/*`)
- Streamlit renders visual interface (`streamlit run streamlit_app/app.py`)
- Streamlit consumes Django APIs via DRF token auth

### 3.2 New API contracts

1. `GET /dashboard/api/v1/summary/`
   - User identity + portfolio summary + current regime headline
2. `GET /dashboard/api/v1/regime-quadrant/`
   - `current_regime`, `distribution`, `confidence`, macro details
3. `GET /dashboard/api/v1/equity-curve/?range=...`
   - `series`, `range`, `has_history`
4. `GET /dashboard/api/v1/signal-status/?limit=...`
   - `stats`, `signals`, `limit`

### 3.3 Streamlit pages

- `streamlit_app/pages/01_Regime.py`
  - Quadrant chart with current regime highlight
- `streamlit_app/pages/02_Equity_Curve.py`
  - Equity curve by selectable time range
- `streamlit_app/pages/03_Signals.py`
  - Signal status breakdown and recent signals table

## 4. Implementation Milestones

### Phase A: API foundation

- Add v1 dashboard endpoints
- Reuse existing `GetDashboardDataUseCase`
- Keep HTMX endpoints unchanged

### Phase B: Streamlit UI baseline

- Create Streamlit app entry + shared API client
- Implement three visualization pages
- Add token-based configuration in sidebar

### Phase C: Cutover preparation

- Add legacy/new dashboard routing strategy in deployment docs
- Define production reverse proxy and auth forwarding
- Add rollout and rollback checklist

## 5. Validation checklist

- `python manage.py check` passes
- v1 APIs return authenticated data
- Streamlit pages load and render charts
- Existing `/dashboard/` page remains functional

## 6. Runbook (development)

1. Start Django:

```bash
python manage.py runserver
```

2. Start Streamlit:

```bash
streamlit run streamlit_app/app.py
```

3. In Streamlit sidebar:
- Set `Django Base URL` (for example `http://127.0.0.1:8000`)
- Set `DRF Token` for authenticated access

4. Optional cutover toggle in `.env`:

```bash
STREAMLIT_DASHBOARD_ENABLED=True
STREAMLIT_DASHBOARD_URL=http://127.0.0.1:8501
```

- `/dashboard/` routes to Streamlit when enabled.
- `/dashboard/legacy/` remains available as rollback entry.

## 7. Risks and follow-up

- Equity curve history currently falls back when historical snapshots are absent
- Production single-sign-on still needs reverse proxy integration work
- Additional dashboard cards (Alpha/Beta/Quota) can be migrated in subsequent phases
