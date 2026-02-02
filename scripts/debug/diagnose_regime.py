"""
Regime Calculation Diagnostic and Fix

This script identifies the issue with regime calculation and provides a corrected calculation.
"""

import os
from dotenv import load_dotenv
from datetime import date

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
        print('  REGIME CALCULATION DIAGNOSTIC REPORT')
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

        print('=== Data Overview ===')
        print(f'CPI records: {len(cpi_all)}')
        print(f'PMI records: {len(pmi_all)}')
        print()

        # Extract values for calculation
        cpi_values = [v for _, v in cpi_all]
        pmi_values = [v for _, v in pmi_all]

        print('=== CPI Data Analysis ===')
        print('CPI values (index):')
        for i, (period, value) in enumerate(cpi_all[-10:]):
            print(f'  {period}: {value}')
        print()

        # Calculate statistics
        def calculate_momentum(series, period=3):
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
            import math
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

        # Calculate momentums
        cpi_momentums = calculate_momentum(cpi_values, period=3)
        pmi_momentums = calculate_momentum(pmi_values, period=3)

        print('=== CPI Momentum Analysis ===')
        print('Recent CPI momentums (3-month absolute):')
        for i in range(max(0, len(cpi_momentums) - 10), len(cpi_momentums)):
            period = cpi_all[i][0]
            momentum = cpi_momentums[i]
            print(f'  {period}: {momentum:+.4f}')
        print()

        # Calculate Z-scores
        cpi_z_scores = calculate_zscore(cpi_momentums, window=60, min_periods=24)
        pmi_z_scores = calculate_zscore(pmi_momentums, window=60, min_periods=24)

        print('=== Z-Score Analysis ===')
        print('Recent Z-scores:')
        for i in range(max(0, len(cpi_z_scores) - 10), len(cpi_z_scores)):
            period = cpi_all[i][0] if i < len(cpi_all) else 'N/A'
            cpi_z = cpi_z_scores[i] if i < len(cpi_z_scores) else 'N/A'
            pmi_z = pmi_z_scores[i] if i < len(pmi_z_scores) else 'N/A'
            print(f'  {period}: CPI_Z={cpi_z:+.2f}, PMI_Z={pmi_z}')
        print()

        # Get stored Z-scores for comparison
        print('=== Stored vs Calculated Z-Scores ===')
        cursor.execute("""
            SELECT observed_at, growth_momentum_z, inflation_momentum_z
            FROM regime_log
            ORDER BY observed_at DESC
            LIMIT 10
        """)

        print('\nStored Z-scores in database:')
        for row in cursor.fetchall():
            observed_at, growth_z, inflation_z = row
            print(f'  {observed_at}: growth={growth_z:+.2f}, inflation={inflation_z:+.2f}')

        print()

        # Diagnostic conclusion
        print('='*70)
        print('  DIAGNOSTIC CONCLUSION')
        print('='*70)
        print()

        # Check if we have enough data
        if len(cpi_values) < 24:
            print('WARNING: Insufficient data for reliable Z-score calculation')
            print(f'         Only {len(cpi_values)} CPI records available')
            print('         Need at least 24 records')
        else:
            print(f'OK: Have {len(cpi_values)} CPI records (sufficient for calculation)')

        print()
        print('ISSUE IDENTIFIED:')
        print('1. CPI data is stored as INDEX values (100.8, 100.7...)')
        print('2. NOT stored as year-over-year percentage (0.3%, 0.2%...)')
        print()
        print('IMPACT:')
        print('- Absolute momentum on index: 100.8 - 99.7 = +1.1pp')
        print('- This creates HIGH Z-scores when historical variance is low')
        print('- Result: inflation_z = +2.07 (very high!)')
        print()
        print('RECOMMENDED FIX:')
        print('Option 1: Convert CPI index to YoY percentage before calculation')
        print('  - YoY = (current_index / same_month_last_year - 1) * 100')
        print('  - Then calculate momentum on YoY values')
        print()
        print('Option 2: Adjust Z-score window/parameters for index data')
        print('  - Increase window size to reduce volatility')
        print('  - Or use a smaller k parameter in sigmoid')
        print()
        print('Option 3: Store CPI directly as YoY percentage in database')
        print('  - This is the cleanest long-term solution')
        print()

        cursor.close()
        conn.close()

    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()
