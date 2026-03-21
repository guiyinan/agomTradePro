# Audit Module Guide

## Overview

The Audit module provides comprehensive attribution analysis and performance validation for the AgomTradePro system. It enables users to:

1. **Analyze Investment Performance Attribution** - Decompose portfolio returns into timing, selection, and interaction effects
2. **Validate Macro Indicator Performance** - Evaluate how well macro indicators predict regime changes
3. **Configure and Test Thresholds** - Optimize indicator thresholds through validation testing
4. **Generate Detailed Reports** - Produce actionable insights and recommendations

## Architecture

The Audit module follows the four-layer architecture pattern:

```
apps/audit/
├── domain/           # Pure business logic
│   ├── entities.py    # Data entities (RegimePeriod, AttributionResult, etc.)
│   └── services.py    # Business rules (analyze_attribution, Brinson model, etc.)
├── application/      # Use case orchestration
│   └── use_cases.py   # Application logic (GenerateAttributionReportUseCase, etc.)
├── infrastructure/   # External integrations
│   ├── models.py     # Django ORM models
│   └── repositories.py # Data access layer
└── interface/        # API and UI
    ├── views.py      # REST API endpoints
    ├── serializers.py # DRF serializers
    ├── urls.py       # URL routing
    └── templates/    # HTML templates
```

## Key Features

### 1. Attribution Analysis

#### Supported Methods

1. **Heuristic Attribution** (Default)
   - Simple rule-based decomposition
   - 30% of positive returns attributed to timing
   - 50% of excess returns attributed to selection
   - Fast computation, easy to understand

2. **Brinson Attribution** (Advanced)
   - Standard financial industry model
   - Mathematically rigorous decomposition:
     - Allocation Effect: Σ(wp_i - wb_i) × (rb_i - rb)
     - Selection Effect: Σ wb_i × (rp_i - rb_i)
     - Interaction Effect: Σ(wp_i - wb_i) × (rp_i - rb_i)
   - More accurate, requires weight data

#### Attribution Report Contents

```
AttributionResult {
    total_return: float          # Total portfolio return
    regime_timing_pnl: float     # Timing contribution
    asset_selection_pnl: float  # Selection contribution
    interaction_pnl: float       # Interaction contribution
    transaction_cost_pnl: float  # Trading costs
    loss_source: LossSource      # Primary loss source
    loss_amount: float           # Total loss
    loss_periods: List[RegimePeriod]
    lesson_learned: str          # Key insights
    improvement_suggestions: List[str]
    period_attributions: List[Dict]  # Period-by-period breakdown
}
```

### 2. Indicator Performance Validation

#### Evaluation Metrics

For each macro indicator, the module calculates:

- **Confusion Matrix**: TP, FP, TN, FN
- **Precision**: TP / (TP + FP)
- **Recall**: TP / (TP + FN)
- **F1 Score**: 2 × (Precision × Recall) / (Precision + Recall)
- **Accuracy**: (TP + TN) / Total
- **Lead Time**: Mean and std of signal lead time (months)
- **Stability Score**: Correlation between pre-2015 and post-2015 performance
- **Decay Rate**: Performance degradation over time
- **Signal Strength**: Average confidence of signals

#### Recommendation Logic

| F1 Score | Stability | Decay Rate | Action |
|----------|-----------|------------|--------|
| ≥ 0.8 | ≥ 0.8 | < 0.2 | INCREASE weight |
| ≥ 0.6 | ≥ 0.6 | < 0.2 | KEEP current |
| 0.4-0.6 | 0.4-0.6 | 0.2-0.3 | DECREASE weight |
| < 0.4 | < 0.4 | > 0.3 | REMOVE indicator |

### 3. Threshold Configuration

#### Supported Indicators

**Growth Indicators:**
- CN_PMI (PMI)
- CN_GDP (GDP)
- CN_RFI (Retail Sales)
- CN_FAI (Fixed Asset Investment)
- CN_EX_IM (Exports/Imports)
- CN_VALUE_ADDED (Industrial Value Added)

**Inflation Indicators:**
- CN_CPI (CPI)
- CN_PPI (PPI)

**Sentiment Indicators:**
- CN_BCI (Business Confidence)
- CN_CCI (Consumer Confidence)

#### Threshold Parameters

Each indicator has configurable thresholds:

```python
IndicatorThresholdConfig {
    level_low: float           # Bearish threshold
    level_high: float          # Bullish threshold
    base_weight: float         # Base weight in regime calculation
    min_weight: float          # Minimum allowed weight
    max_weight: float          # Maximum allowed weight
    decay_threshold: float     # F1 score threshold for decay
    improvement_threshold: float # Threshold for improvement bonus
}
```

## API Reference

### Attribution Endpoints

#### POST /api/audit/reports/generate/
Generate attribution report for a backtest.

**Request:**
```json
{
  "backtest_id": 1
}
```

**Response:**
```json
{
  "id": 1,
  "backtest_id": 1,
  "total_pnl": 0.10,
  "regime_timing_pnl": 0.03,
  "asset_selection_pnl": 0.05,
  "interaction_pnl": 0.02,
  "regime_accuracy": 0.75,
  "loss_analyses": [...],
  "experience_summaries": [...]
}
```

#### GET /api/audit/summary/
Get attribution summary by backtest or date range.

**Query Parameters:**
- `backtest_id` (int): Backtest ID
- `start_date` (string): Start date (YYYY-MM-DD)
- `end_date` (string): End date (YYYY-MM-DD)

**Response:**
```json
[
  {
    "id": 1,
    "total_pnl": 0.10,
    "period_start": "2024-01-01",
    "period_end": "2024-06-30"
  }
]
```

### Indicator Performance Endpoints

#### GET /api/audit/indicator-performance/<indicator_code>/
Get detailed performance for a single indicator.

#### POST /api/audit/validate-all-indicators/
Run validation for all indicators.

**Request:**
```json
{
  "start_date": "2024-01-01",
  "end_date": "2024-12-31",
  "use_shadow_mode": false
}
```

#### POST /api/audit/update-threshold/

### API Routing Rule

- Canonical API: `/api/audit/...`
- Legacy compatibility: `/audit/api/...`
- SDK / MCP / frontend new code must use canonical `/api/audit/...`
Update indicator threshold configuration.

**Request:**
```json
{
  "indicator_code": "CN_PMI",
  "level_low": 49.0,
  "level_high": 51.0
}
```

## Web Interface

### Main Pages

1. **/audit/page/** - Dashboard with quick actions and latest reports
2. **/audit/reports/<report_id>/** - Detailed attribution report view
3. **/audit/indicator-performance/** - Indicator evaluation dashboard
4. **/audit/threshold-validation/** - Interactive threshold editor

### Chart Visualizations

#### Attribution Charts
- **Waterfall Chart**: PnL decomposition (timing → selection → interaction → total)
- **Trend Chart**: Period-by-period attribution over time
- **Pie Chart**: Sector/asset breakdown

#### Performance Charts
- **F1 Distribution**: Histogram of F1 scores across indicators
- **Scatter Plot**: Stability vs F1 score
- **Ranking Chart**: Top 10 indicators by F1 score
- **Action Distribution**: Pie chart of recommended actions

#### Threshold Editor
- **Interactive Sliders**: Real-time threshold adjustment
- **Signal Preview**: Mini charts showing signal distribution
- **Historical Comparison**: Past validation results
- **Batch Operations**: Save all, reset all, export/import

## Usage Examples

### Example 1: Generate Attribution Report

```python
from apps.audit.application.use_cases import GenerateAttributionReportUseCase, GenerateAttributionReportRequest
from apps.audit.infrastructure.repositories import DjangoAuditRepository, DjangoBacktestRepository

use_case = GenerateAttributionReportUseCase(
    audit_repository=DjangoAuditRepository(),
    backtest_repository=DjangoBacktestRepository()
)

request = GenerateAttributionReportRequest(backtest_id=123)
response = use_case.execute(request)

if response.success:
    print(f"Report generated: {response.report_id}")
    print(f"Total return: {response.report.total_pnl}")
    print(f"Timing PnL: {response.report.regime_timing_pnl}")
else:
    print(f"Error: {response.error}")
```

### Example 2: Validate Indicator Performance

```python
from apps.audit.application.use_cases import EvaluateIndicatorPerformanceUseCase, EvaluateIndicatorPerformanceRequest

use_case = EvaluateIndicatorPerformanceUseCase(
    audit_repository=DjangoAuditRepository()
)

request = EvaluateIndicatorPerformanceRequest(
    indicator_code="CN_PMI",
    start_date=date(2020, 1, 1),
    end_date=date(2024, 12, 31)
)

response = use_case.execute(request)

if response.success:
    report = response.report
    print(f"F1 Score: {report.f1_score}")
    print(f"Stability: {report.stability_score}")
    print(f"Recommendation: {report.recommended_action}")
```

### Example 3: Batch Validate All Indicators

```python
from apps.audit.application.use_cases import ValidateThresholdsUseCase, ValidateThresholdsRequest

use_case = ValidateThresholdsUseCase(
    audit_repository=DjangoAuditRepository()
)

request = ValidateThresholdsRequest(
    start_date=date(2023, 1, 1),
    end_date=date(2024, 12, 31)
)

response = use_case.execute(request)

if response.success:
    validation = response.validation_report
    print(f"Total indicators: {validation.total_indicators}")
    print(f"Approved: {validation.approved_indicators}")
    print(f"Rejected: {validation.rejected_indicators}")
    print(f"Overall: {validation.overall_recommendation}")
```

## Testing

### Unit Tests

Location: `tests/unit/domain/audit/`

Run tests:
```bash
pytest tests/unit/domain/audit/ -v
pytest tests/unit/domain/audit/test_entities.py -v
pytest tests/unit/domain/audit/test_attribution_services.py -v
pytest tests/unit/domain/audit/test_performance_analyzer.py -v
```

### Integration Tests

Location: `tests/integration/audit/`

Run tests:
```bash
pytest tests/integration/audit/ -v
pytest tests/integration/audit/test_full_attribution_workflow.py -v
pytest tests/integration/audit/test_api_endpoints.py -v
```

### Test Coverage

Target: Domain layer ≥ 90% coverage

Check coverage:
```bash
pytest tests/unit/domain/audit/ --cov=apps/audit/domain --cov-report=html
```

## Configuration

### Management Commands

Initialize indicator thresholds:
```bash
python manage.py init_indicator_thresholds
python manage.py init_indicator_thresholds --refresh
```

Initialize confidence configuration:
```bash
python manage.py init_confidence_config
```

Validate high-frequency indicators:
```bash
python manage.py validate_high_frequency_indicators
```

### Settings

No module-specific settings required. Uses Django settings from `core.settings`.

## Troubleshooting

### Common Issues

1. **"指标不存在" Error**
   - Cause: Indicator not in IndicatorThresholdConfigModel
   - Solution: Run `python manage.py init_indicator_thresholds`

2. **"无数据" Error**
   - Cause: No macro data for the indicator in the evaluation period
   - Solution: Check MacroIndicator table has data for the date range

3. **Low F1 Scores**
   - Cause: Thresholds may be too strict or indicator truly not predictive
   - Solution: Use threshold editor to adjust levels

4. **Visualization Not Loading**
   - Cause: Chart.js not loaded or data format error
   - Solution: Check browser console, verify Chart.js CDN access

## Performance Considerations

- Attribution analysis: O(n) where n = number of periods
- Indicator validation: O(m × k) where m = indicators, k = regime snapshots
- Brinson model: O(n × p) where p = asset classes
- Chart rendering: O(d) where d = data points

## Future Enhancements

- [ ] Multi-factor attribution models (Fama-French)
- [ ] Risk-adjusted attribution (Sharpe decomposition)
- [ ] Sector-level attribution breakdown
- [ ] Transaction cost detailed analysis
- [ ] PDF/Excel export for reports
- [ ] Real-time attribution monitoring
- [ ] Machine learning for threshold optimization

## References

- Brinson, G., Hood, L.R., & Beebower, R.S. (1986). "Determinants of Portfolio Performance"
- Attribution Analysis Best Practices (CFA Institute)
- Domain-Driven Design (Eric Evans)
