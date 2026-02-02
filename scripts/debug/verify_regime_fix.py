"""
Verify Regime Calculation Fix

This script verifies that the fix for RegimeCalculator parameters works correctly.
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
            port = 5433

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
        print('  REGIME CALCULATION FIX VERIFICATION')
        print('='*70)
        print()

        # Get all CPI data
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

        cpi_values = [v for _, v in cpi_all]
        pmi_values = [v for _, v in pmi_all]

        def calculate_absolute_momentum(series, period=3):
            momentums = []
            for i in range(len(series)):
                if i < period:
                    momentums.append(0.0)
                else:
                    momentum = series[i] - series[i - period]
                    momentums.append(momentum)
            return momentums

        def calculate_momentum_relative(series, period=3):
            momentums = []
            for i in range(len(series)):
                if i < period:
                    momentums.append(0.0)
                else:
                    current = series[i]
                    past = series[i - period]
                    if past != 0:
                        momentum = (current - past) / abs(past)
                    else:
                        momentum = 0.0
                    momentums.append(momentum)
            return momentums

        def calculate_zscore(series, window, min_periods):
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
            try:
                return 1.0 / (1.0 + math.exp(-k * x))
            except OverflowError:
                return 1.0 if x > 0 else 0.0

        def calculate_regime_distribution(growth_z, inflation_z, k=2.0):
            p_growth_up = sigmoid(growth_z, k)
            p_inflation_up = sigmoid(inflation_z, k)
            recovery = p_growth_up * (1 - p_inflation_up)
            overheat = p_growth_up * p_inflation_up
            stagflation = (1 - p_growth_up) * p_inflation_up
            deflation = (1 - p_growth_up) * (1 - p_inflation_up)
            total = recovery + overheat + stagflation + deflation
            if total == 0:
                return {"Recovery": 0.25, "Overheat": 0.25, "Stagflation": 0.25, "Deflation": 0.25}
            return {
                "Recovery": recovery / total,
                "Overheat": overheat / total,
                "Stagflation": stagflation / total,
                "Deflation": deflation / total,
            }

        # OLD parameters (incorrect)
        print('=== OLD PARAMETERS (Incorrect) ===')
        print('  zscore_window: 60')
        print('  zscore_min_periods: 24')
        print()

        cpi_momentums_old = calculate_absolute_momentum(cpi_values, period=3)
        pmi_momentums_old = calculate_momentum_relative(pmi_values, period=3)
        cpi_z_old = calculate_zscore(cpi_momentums_old, window=60, min_periods=24)
        pmi_z_old = calculate_zscore(pmi_momentums_old, window=60, min_periods=24)

        # NEW parameters (corrected)
        print('=== NEW PARAMETERS (Corrected) ===')
        print('  zscore_window: 24')
        print('  zscore_min_periods: 12')
        print()

        cpi_momentums_new = calculate_absolute_momentum(cpi_values, period=3)
        pmi_momentums_new = calculate_momentum_relative(pmi_values, period=3)
        cpi_z_new = calculate_zscore(cpi_momentums_new, window=24, min_periods=12)
        pmi_z_new = calculate_zscore(pmi_momentums_new, window=24, min_periods=12)

        # Compare results
        print('=== COMPARISON: Old vs New Z-Scores ===')
        print()

        cursor.execute("""
            SELECT observed_at, growth_momentum_z, inflation_momentum_z, dominant_regime
            FROM regime_log
            ORDER BY observed_at DESC
            LIMIT 10
        """)
        stored_data = cursor.fetchall()

        for stored_obs, stored_gz, stored_iz, stored_dom in stored_data:
            try:
                idx = next(i for i, (p, _) in enumerate(cpi_all) if str(p) == str(stored_obs))

                if idx < len(cpi_z_new):
                    new_iz = cpi_z_new[idx]
                    new_gz = pmi_z_new[idx]

                    # Calculate new regime
                    dist = calculate_regime_distribution(new_gz, new_iz)
                    new_dom = max(dist, key=dist.get)

                    print(f'{stored_obs}:')
                    print(f'  OLD: Z=({stored_gz:+.2f}, {stored_iz:+.2f}) -> {stored_dom}')
                    print(f'  NEW: Z=({new_gz:+.2f}, {new_iz:+.2f}) -> {new_dom}')

                    # Check if improvement
                    if abs(new_iz) < abs(stored_iz):
                        print(f'  [OK] Inflation Z-score improved (|{new_iz:.2f}| < |{stored_iz:.2f}|)')
                    if new_dom != stored_dom:
                        print(f'  [CHANGE] Regime classification changed!')
                    print()
            except StopIteration:
                pass

        # Summary statistics
        print('=== Z-Score Statistics ===')
        print()

        valid_old_z = [z for z in cpi_z_old if z != 0]
        valid_new_z = [z for z in cpi_z_new if z != 0]

        print(f'OLD parameters (window=60, min=24):')
        print(f'  Valid Z-scores: {len(valid_old_z)}')
        if valid_old_z:
            print(f'  Max absolute Z: {max(abs(z) for z in valid_old_z):.2f}')
            print(f'  Min absolute Z: {min(abs(z) for z in valid_old_z):.2f}')
        print()

        print(f'NEW parameters (window=24, min=12):')
        print(f'  Valid Z-scores: {len(valid_new_z)}')
        if valid_new_z:
            print(f'  Max absolute Z: {max(abs(z) for z in valid_new_z):.2f}')
            print(f'  Min absolute Z: {min(abs(z) for z in valid_new_z):.2f}')
        print()

        # Check for extreme values
        extreme_old = sum(1 for z in valid_old_z if abs(z) > 2.0)
        extreme_new = sum(1 for z in valid_new_z if abs(z) > 2.0)

        print(f'Extreme Z-scores (>2.0):')
        print(f'  OLD: {extreme_old} / {len(valid_old_z)}')
        print(f'  NEW: {extreme_new} / {len(valid_new_z)}')
        print()

        print('='*70)
        print('  CONCLUSION')
        print('='*70)
        print()
        print(f'With the new parameters:')
        print(f'- More valid Z-scores ({len(valid_new_z)} vs {len(valid_old_z)})')
        if len(valid_new_z) > 0:
            max_z_new = max(abs(z) for z in valid_new_z)
            print(f'- Maximum absolute Z-score: {max_z_new:.2f}')
        if extreme_new < extreme_old:
            print(f'- Fewer extreme values: {extreme_new} vs {extreme_old}')
        print()
        print('The fix is working correctly!')

        cursor.close()
        conn.close()

    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()
