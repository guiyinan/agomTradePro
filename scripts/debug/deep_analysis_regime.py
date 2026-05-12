"""
Deep Analysis of Regime Calculation Issue

The problem is more complex than just data format.
"""

import math
import os
from datetime import date

from dotenv import load_dotenv

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
        print('  DEEP ANALYSIS: Regime Calculation Issue')
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

        print(f'TOTAL CPI RECORDS: {len(cpi_all)}')
        print()

        # The issue: window=60 but only 35 records!
        print('=== ROOT CAUSE ANALYSIS ===')
        print()
        print('PROBLEM CONFIGURATION:')
        print('  - Z-score window: 60')
        print('  - Min periods: 24')
        print(f'  - Actual data points: {len(cpi_all)}')
        print()
        print('When i=35 (latest data):')
        print('  - Window start: max(0, 35-60+1) = 0')
        print(f'  - Window size: {min(60, len(cpi_all))} data points')
        print('  - But with min_periods=24, first Z-score at i=23')
        print()

        # Calculate momentum the way the code does
        cpi_values = [v for _, v in cpi_all]

        def calculate_absolute_momentum(series, period=3):
            momentums = []
            for i in range(len(series)):
                if i < period:
                    momentums.append(0.0)
                else:
                    momentum = series[i] - series[i - period]
                    momentums.append(momentum)
            return momentums

        cpi_momentums = calculate_absolute_momentum(cpi_values, period=3)

        print('=== CPI Momentum (3-month absolute) ===')
        for i in range(len(cpi_all)):
            if i >= 23:  # First one with valid Z-score
                period = cpi_all[i][0]
                mom = cpi_momentums[i]
                print(f'  {period}: momentum = {mom:+.4f}')
        print()

        # Manual Z-score calculation for the last data point
        print('=== Manual Z-Score Calculation for Latest Data ===')
        print()

        # Get window for last data point
        last_idx = len(cpi_momentums) - 1
        window_start = max(0, last_idx - 60 + 1)
        window_data = cpi_momentums[window_start:last_idx + 1]

        print(f'Window for Z-score calculation (i={last_idx}):')
        print(f'  - Window start: {window_start}')
        print(f'  - Window size: {len(window_data)}')
        print(f'  - Data in window: {window_data}')
        print()

        mean_val = sum(window_data) / len(window_data)
        variance = sum((x - mean_val) ** 2 for x in window_data) / len(window_data)
        std_val = math.sqrt(variance)

        print('Window statistics:')
        print(f'  - Mean: {mean_val:.4f}')
        print(f'  - Std Dev: {std_val:.4f}')
        print(f'  - Current value: {cpi_momentums[last_idx]:.4f}')
        print()

        z_score = (cpi_momentums[last_idx] - mean_val) / std_val if std_val > 0 else 0

        print('Calculated Z-score:')
        print(f'  - Z = ({cpi_momentums[last_idx]:.4f} - {mean_val:.4f}) / {std_val:.4f}')
        print(f'  - Z = {z_score:.4f}')
        print()

        # Analyze the momentum values in the window
        print('=== Momentum Values in Window ===')
        positive_count = sum(1 for x in window_data if x > 0)
        negative_count = sum(1 for x in window_data if x < 0)
        zero_count = sum(1 for x in window_data if x == 0)

        print(f'  - Positive: {positive_count}')
        print(f'  - Negative: {negative_count}')
        print(f'  - Zero: {zero_count}')
        print()

        # The issue: most values are near 0, so std_dev is small
        # When we get a value like +1.1, it becomes a huge Z-score
        print('=== THE PROBLEM ===')
        print()
        print(f'Because most momentums are small (around {mean_val:+.2f}),')
        print(f'the standard deviation is also small ({std_val:.4f}).')
        print()
        print('When we suddenly get momentum = +1.1:')
        print(f'  - Z-score = +1.1 / {std_val:.4f} = {z_score:.2f}')
        print()
        print('This is a STATISTICAL ANOMALY, not necessarily an economic signal!')
        print()

        print('='*70)
        print('  RECOMMENDED FIX')
        print('='*70)
        print()
        print('The issue is NOT the data format, but the CONFIGURATION:')
        print()
        print('1. REDUCE min_periods from 24 to match available data')
        print('   - With only 35 records, min_periods=24 gives only 11 Z-scores')
        print()
        print('2. REDUCE Z-score window from 60 to match available data')
        print('   - Window should be at most 50% of available data')
        print('   - For 35 records, use window=17 or window=20')
        print()
        print('3. OR use a fixed Z-score threshold instead of rolling window')
        print('   - E.g., inflation_momentum > 0.5pp = high inflation')
        print()
        print('4. BEST FIX: Adjust calculation parameters for limited data:')
        print('   - momentum_period = 3')
        print('   - zscore_window = 20 (not 60)')
        print('   - zscore_min_periods = 12 (not 24)')
        print()

        cursor.close()
        conn.close()

    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()
