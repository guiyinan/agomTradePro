"""
Regime Calculation Fix Script

This script fixes the regime calculation by converting CPI index values
to year-over-year percentages before calculating momentum and Z-scores.

PROBLEM:
- CPI is stored as INDEX (100.8, 100.7...)
- Not as YoY percentage (0.3%, 0.2%...)
- This causes extreme Z-scores when momentum is calculated on index changes

SOLUTION:
- Convert CPI index to YoY percentage
- Recalculate momentum, Z-scores, and regime distribution
"""

import os
from dotenv import load_dotenv
from datetime import date
import math

load_dotenv()

db_url = os.environ.get('DATABASE_URL', '')

if db_url.startswith('postgresql://'):
    rest = db_url.replace('postgresql://', '')
    user_pass, host_port_db = rest.split('@')
    user, password = user_pass.split(':')

    if '/' in host_port_db:
        host_port, database = host_port_db.split('/')
        if ':' in host_port:
            host, port = host_port.split(':')
        else:
            host = host_port
            port = 5432

    try:
        import pg8000

        conn = pg8000.connect(
            host=host,
            port=int(port),
            database=database,
            user=user,
            password=password
        )
        cursor = conn.cursor()

        print('='*70)
        print('  REGIME CALCULATION FIX')
        print('='*70)
        print()

        # Get all CPI and PMI data
        cursor.execute("""
            SELECT reporting_period, value
            FROM macro_indicator
            WHERE code = 'CN_CPI'
            ORDER BY reporting_period ASC
        """)
        cpi_all = cursor.fetchall()

        cursor.execute("""
            SELECT reporting_period, value
            FROM macro_indicator
            WHERE code = 'CN_PMI'
            ORDER BY reporting_period ASC
        """)
        pmi_all = cursor.fetchall()

        # Convert CPI index to YoY percentage
        print('=== Step 1: Convert CPI Index to YoY Percentage ===')
        print()

        cpi_yoy = []
        for i, (period, index_value) in enumerate(cpi_all):
            if i >= 12:  # Need at least 12 months of data
                # Get same month last year
                last_year_index = cpi_all[i - 12][1]
                # Calculate YoY percentage
                yoy_pct = (index_value / last_year_index - 1) * 100
                cpi_yoy.append((period, yoy_pct))

                if i >= len(cpi_all) - 5:  # Show last 5
                    print(f'{period}: CPI Index={index_value:.1f}, YoY={yoy_pct:+.2f}%')
            else:
                cpi_yoy.append((period, 0.0))  # Placeholder for early months

        print()

        # Extract values
        cpi_values = [v for _, v in cpi_yoy]
        pmi_values = [v for _, v in pmi_all]

        # Helper functions
        def calculate_absolute_momentum(series, period=3):
            """Calculate 3-month absolute momentum"""
            momentums = []
            for i in range(len(series)):
                if i < period:
                    momentums.append(0.0)
                else:
                    momentum = series[i] - series[i - period]
                    momentums.append(momentum)
            return momentums

        def calculate_zscore(series, window=60, min_periods=24):
            """Calculate rolling Z-score"""
            n = len(series)
            z_scores = []

            for i in range(n):
                if i < min_periods - 1:
                    z_scores.append(0.0)
                else:
                    start = max(0, i - window + 1)
                    window_data = series[start:i+1]

                    mean_val = sum(window_data) / len(window_data)
                    variance = sum((x - mean_val) ** 2 for x in window_data) / len(window_data)
                    std_val = math.sqrt(variance)

                    if std_val > 0:
                        z = (series[i] - mean_val) / std_val
                    else:
                        z = 0.0
                    z_scores.append(z)

            return z_scores

        def sigmoid(x, k=2.0):
            """Sigmoid function"""
            try:
                return 1.0 / (1.0 + math.exp(-k * x))
            except OverflowError:
                return 1.0 if x > 0 else 0.0

        def calculate_regime_distribution(growth_z, inflation_z, k=2.0):
            """Calculate regime distribution"""
            p_growth_up = sigmoid(growth_z, k)
            p_inflation_up = sigmoid(inflation_z, k)

            recovery = p_growth_up * (1 - p_inflation_up)
            overheat = p_growth_up * p_inflation_up
            stagflation = (1 - p_growth_up) * p_inflation_up
            deflation = (1 - p_growth_up) * (1 - p_inflation_up)

            total = recovery + overheat + stagflation + deflation

            if total == 0:
                return {
                    "Recovery": 0.25,
                    "Overheat": 0.25,
                    "Stagflation": 0.25,
                    "Deflation": 0.25,
                }

            return {
                "Recovery": recovery / total,
                "Overheat": overheat / total,
                "Stagflation": stagflation / total,
                "Deflation": deflation / total,
            }

        # Calculate corrected values
        print('=== Step 2: Calculate Corrected Values ===')
        print()

        # PMI: use relative momentum
        pmi_momentums = []
        for i in range(len(pmi_values)):
            if i < 3:
                pmi_momentums.append(0.0)
            else:
                momentum = (pmi_values[i] - pmi_values[i - 3]) / abs(pmi_values[i - 3])
                pmi_momentums.append(momentum)

        # CPI YoY: use absolute momentum
        cpi_momentums = calculate_absolute_momentum(cpi_values, period=3)

        # Calculate Z-scores
        pmi_z_scores = calculate_zscore(pmi_momentums, window=60, min_periods=24)
        cpi_z_scores = calculate_zscore(cpi_momentums, window=60, min_periods=24)

        # Show comparison
        print('COMPARISON: Original vs Corrected Z-Scores')
        print('-' * 70)

        cursor.execute("""
            SELECT observed_at, growth_momentum_z, inflation_momentum_z, dominant_regime
            FROM regime_log
            ORDER BY observed_at DESC
            LIMIT 10
        """)
        stored_data = cursor.fetchall()

        for stored_obs, stored_gz, stored_iz, stored_dom in stored_data:
            # Find matching index in our data
            try:
                idx = next(i for i, (p, _) in enumerate(cpi_all) if str(p) == str(stored_obs))

                if idx < len(cpi_z_scores):
                    corrected_iz = cpi_z_scores[idx]
                    corrected_gz = pmi_z_scores[idx]

                    # Calculate corrected regime
                    dist = calculate_regime_distribution(corrected_gz, corrected_iz)
                    corrected_dom = max(dist, key=dist.get)

                    print(f'{stored_obs}:')
                    print(f'  BEFORE: Z=({stored_gz:+.2f}, {stored_iz:+.2f}) -> {stored_dom}')
                    print(f'  AFTER:  Z=({corrected_gz:+.2f}, {corrected_iz:+.2f}) -> {corrected_dom}')

                    if abs(corrected_iz - stored_iz) > 0.5:
                        print(f'  ^^ Significant difference in inflation Z-score!')
            except StopIteration:
                pass

        print()
        print('='*70)
        print('  RECOMMENDATION')
        print('='*70)
        print()
        print('The regime calculation needs to be fixed by:')
        print()
        print('1. Using CPI YoY percentage instead of index for calculation')
        print('2. Recalculating all regime_log records with corrected method')
        print()
        print('This can be done by:')
        print('- Running: python manage.py recalculate_regime --use-yoy')
        print('Or updating the regime calculation service')
        print()

        cursor.close()
        conn.close()

    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()
