# Brinson Attribution Methodology

## Overview

The Brinson attribution model is the industry standard for portfolio performance decomposition. It breaks down excess returns into three components:

1. **Allocation Effect** - Asset allocation decisions
2. **Selection Effect** - Security selection within asset classes
3. **Interaction Effect** - Interaction between allocation and selection

## Mathematical Foundation

### Basic Formulas

Given:
- **Portfolio weights**: wp_i (weight of asset i in portfolio)
- **Benchmark weights**: wb_i (weight of asset i in benchmark)
- **Portfolio returns**: rp_i (return of asset i in portfolio)
- **Benchmark returns**: rb_i (return of asset i in benchmark)
- **Benchmark return**: rb = Σ wb_i × rb_i

### Attribution Components

#### 1. Allocation Effect

```
Allocation Effect = Σ (wp_i - wb_i) × (rb_i - rb)
```

**Interpretation:** The contribution from overweighting/underweighting asset classes that outperformed/underperformed the benchmark.

- Positive value: Good timing decisions (overweight outperforming sectors)
- Negative value: Poor timing decisions (underweight outperforming sectors)

#### 2. Selection Effect

```
Selection Effect = Σ wb_i × (rp_i - rb_i)
```

**Interpretation:** The contribution from selecting better/worse securities within each asset class compared to the benchmark.

- Positive value: Good stock picking (outperformed benchmark within sector)
- Negative value: Poor stock picking (underperformed benchmark within sector)

#### 3. Interaction Effect

```
Interaction Effect = Σ (wp_i - wb_i) × (rp_i - rb_i)
```

**Interpretation:** The contribution from the interaction between allocation and selection decisions.

- Positive value: Good combination (overweight + outperform in that sector)
- Negative value: Poor combination (overweight + underperform in that sector)

### Verification

```
Excess Return = Portfolio Return - Benchmark Return
             = Allocation + Selection + Interaction
```

The three components should sum to the excess return (within rounding error).

## Implementation in AgomSAAF

### Domain Layer

Located in `apps/audit/domain/services.py`:

```python
def calculate_brinson_attribution(
    portfolio_returns: Dict[str, List[Tuple[date, float]]],
    benchmark_returns: Dict[str, List[Tuple[date, float]]],
    portfolio_weights: Dict[str, Dict[date, float]],
    benchmark_weights: Dict[str, Dict[date, float]],
    evaluation_period: Tuple[date, date],
) -> BrinsonAttributionResult
```

### Data Requirements

1. **Portfolio Returns**: Time series of returns for each asset class
2. **Benchmark Returns**: Time series of benchmark returns for each asset class
3. **Portfolio Weights**: Time series of portfolio weights (may vary over time)
4. **Benchmark Weights**: Time series of benchmark weights (may vary over time)

### Result Structure

```python
@dataclass(frozen=True)
class BrinsonAttributionResult:
    benchmark_return: float
    portfolio_return: float
    excess_return: float
    allocation_effect: float
    selection_effect: float
    interaction_effect: float
    attribution_sum: float  # For verification
    period_breakdown: List[Dict]  # Period-by-period analysis
    sector_breakdown: Dict[str, Dict]  # Sector-by-sector details
```

## Usage Example

### Simple Case (Two Assets)

**Setup:**
- Assets: Equity, Bond
- Portfolio: 60% Equity, 40% Bond
- Benchmark: 50% Equity, 50% Bond
- Returns: Equity +8%, Bond +4%

**Benchmark Return:**
```
rb = 0.5 × 8% + 0.5 × 4% = 6%
```

**Portfolio Return (assuming security-level returns equal sector returns):**
```
rp = 0.6 × 8% + 0.4 × 4% = 6.4%
```

**Excess Return:**
```
Excess = 6.4% - 6% = 0.4%
```

**Allocation Effect:**
```
Equity: (0.6 - 0.5) × (8% - 6%) = 0.1 × 2% = 0.2%
Bond:   (0.4 - 0.5) × (4% - 6%) = -0.1 × -2% = 0.2%
Total: 0.4%
```

**Selection Effect:**
```
Equity: 0.5 × (8% - 8%) = 0%
Bond:   0.5 × (4% - 4%) = 0%
Total: 0%
```

**Interaction Effect:**
```
Equity: (0.6 - 0.5) × (8% - 8%) = 0%
Bond:   (0.4 - 0.5) × (4% - 4%) = 0%
Total: 0%
```

**Result:**
- Allocation: +0.4% (all excess return from timing decision)
- Selection: 0% (no security selection skill)
- Interaction: 0%
- Total: +0.4% ✓

## Comparison with Heuristic Method

| Aspect | Heuristic | Brinson |
|--------|-----------|---------|
| **Basis** | Rules of thumb (30%/50%) | Mathematical decomposition |
| **Input** | Returns only | Returns + Weights |
| **Accuracy** | Approximate | Precise |
| **Interpretability** | Simple | Requires training |
| **Computation** | Fast | Moderate |
| **Use Case** | Quick assessment | Formal analysis |

## Practical Considerations

### When to Use Brinson

1. **Detailed Performance Review** - Quarter-end or year-end analysis
2. **Manager Evaluation** - Assessing fund manager skill
3. **Risk Attribution** - Understanding sources of alpha
4. **Benchmark Comparison** - Against custom benchmarks

### When to Use Heuristic

1. **Real-time Monitoring** - Quick performance updates
2. **Limited Data** - When weight data not available
3. **Communication** - Explaining to non-technical audiences
4. **Screening** - Initial pass before detailed analysis

### Common Pitfalls

1. **Missing Weight Data**
   - Problem: Brinson requires both portfolio and benchmark weights
   - Solution: Use equal weights or estimate from holdings

2. **Time-Varying Weights**
   - Problem: Weights change during evaluation period
   - Solution: Use time-weighted averages or sub-period analysis

3. **Multi-Level Benchmarks**
   - Problem: Benchmark has nested asset classes
   - Solution: Apply Brinson at each level separately

4. **Cash Drag**
   - Problem: Uninvested cash creates zero allocation
   - Solution: Treat cash as separate asset class

## Extensions

### Brinson-Fachler Model

Adds cash allocation effect:
```
Cash Effect = (wp_cash - wb_cash) × (rb_cash - rb)
```

### Brinson with Risk Adjustment

Adjusts returns for risk before attribution:
```
Risk-Adjusted Return = Return - (Risk_Aversion × Risk)
```

### Multi-Currency Brinson

Accounts for currency effects:
```
Currency Effect = Σ wp_i × (rp_local - rp_base_currency)
```

## References

1. Brinson, G., Hood, L.R., & Beebower, R.S. (1986). "Determinants of Portfolio Performance II: An Update", Financial Analysts Journal, 42(4), 40-48.

2. CFA Institute (2022). "Performance Attribution", CFA Program Curriculum.

3. Bacon, C. (2008). "Practical Portfolio Performance Measurement and Attribution", Wiley Finance.

## Validation

To validate our Brinson implementation:

```python
# Run validation test
pytest tests/unit/domain/audit/test_attribution_services.py::TestBrinsonAttribution -v

# Check that components sum to excess
assert abs(allocation + selection + interaction - excess) < 1e-6
```

## Summary

The Brinson attribution model provides a rigorous framework for understanding the sources of portfolio returns. By separating allocation, selection, and interaction effects, investors can:

1. Identify true skill vs. luck
2. Improve decision-making processes
3. Communicate performance more effectively
4. Make better manager selection decisions

The implementation in AgomSAAF maintains the mathematical rigor of the original Brinson model while adapting it to the unique requirements of macro regime-based investing.
