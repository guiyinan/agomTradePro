"""
Recalculate Regime Data with Fixed Parameters

This script recalculates regime_log records using the corrected parameters.
"""

import os
from dotenv import load_dotenv
from datetime import date, datetime
import math
import json

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
        print('  REGIME DATA RECALCULATION')
        print('='*70)
        print()

        # Get macro data
        cursor.execute("""
            SELECT code, value, reporting_period
            FROM macro_indicator
            WHERE code IN ('CN_PMI', 'CN_CPI')
            ORDER BY code, reporting_period ASC
        """)

        raw_data = cursor.fetchall()

        # Organize data by indicator
        pmi_data = []
        cpi_data = []

        for code, value, period in raw_data:
            if 'PMI' in code:
                pmi_data.append((period, value))
            elif 'CPI' in code:
                cpi_data.append((period, value))

        print(f'Loaded data:')
        print(f'  PMI records: {len(pmi_data)}')
        print(f'  CPI records: {len(cpi_data)}')
        print()

        # Calculate regime with NEW parameters
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

        def calculate_zscore(series, window=24, min_periods=12):
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

        # Extract values
        pmi_values = [v for _, v in pmi_data]
        cpi_values = [v for _, v in cpi_data]
        pmi_dates = [d for d, _ in pmi_data]

        # Calculate with NEW parameters
        print('=== Calculating with NEW Parameters ===')
        print('  zscore_window: 24 (was 60)')
        print('  zscore_min_periods: 12 (was 24)')
        print()

        pmi_momentums = calculate_momentum_relative(pmi_values, period=3)
        cpi_momentums = calculate_absolute_momentum(cpi_values, period=3)

        pmi_z_scores = calculate_zscore(pmi_momentums, window=24, min_periods=12)
        cpi_z_scores = calculate_zscore(cpi_momentums, window=24, min_periods=12)

        # Calculate regimes
        results = []
        for i, calc_date in enumerate(pmi_dates):
            if i >= 12:  # Have valid Z-score
                growth_z = pmi_z_scores[i]
                inflation_z = cpi_z_scores[i]

                dist = calculate_regime_distribution(growth_z, inflation_z)
                dominant = max(dist, key=dist.get)

                results.append({
                    'date': calc_date,
                    'growth_z': growth_z,
                    'inflation_z': inflation_z,
                    'distribution': dist,
                    'dominant': dominant,
                    'confidence': dist[dominant]
                })

        print(f'Calculated {len(results)} regime records')
        print()

        # Show comparison with existing data
        print('=== Comparison with Existing Data ===')
        print()

        cursor.execute("""
            SELECT observed_at, growth_momentum_z, inflation_momentum_z, dominant_regime, confidence
            FROM regime_log
            ORDER BY observed_at DESC
        """)
        existing = cursor.fetchall()

        # Backup existing data
        backup_file = 'regime_backup_before_fix.json'
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump([
                {
                    'observed_at': str(r[0]),
                    'growth_momentum_z': float(r[1]),
                    'inflation_momentum_z': float(r[2]),
                    'dominant_regime': r[3],
                    'confidence': float(r[4])
                }
                for r in existing
            ], f, indent=2)

        print(f'Backed up existing data to: {backup_file}')
        print()

        # Show comparison
        print('Date        | OLD Z (growth, inflation) | OLD Regime   | NEW Z (growth, inflation) | NEW Regime')
        print('-' * 90)

        update_count = 0
        for new_result in results:
            date_str = new_result['date']
            new_gz = new_result['growth_z']
            new_iz = new_result['inflation_z']
            new_dom = new_result['dominant']
            new_conf = new_result['confidence']

            # Find matching existing record
            existing_match = None
            for ex in existing:
                if str(ex[0]) == str(date_str):
                    existing_match = ex
                    break

            if existing_match:
                old_gz = float(existing_match[1])
                old_iz = float(existing_match[2])
                old_dom = existing_match[3]

                print(f'{date_str} | ({old_gz:+.2f}, {old_iz:+.2f})     | {old_dom:12s} | ({new_gz:+.2f}, {new_iz:+.2f})     | {new_dom:12s}')

                # Update the record
                cursor.execute("""
                    UPDATE regime_log
                    SET growth_momentum_z = %s,
                        inflation_momentum_z = %s,
                        distribution = %s,
                        dominant_regime = %s,
                        confidence = %s
                    WHERE observed_at = %s
                """, (
                    new_gz,
                    new_iz,
                    json.dumps(new_result['distribution']),
                    new_dom,
                    new_conf,
                    date_str
                ))

                update_count += 1

        print()
        print(f'Updated {update_count} records')
        print()

        # Commit the transaction
        conn.commit()

        print('='*70)
        print('  RECALCULATION COMPLETE')
        print('='*70)
        print()
        print(f'Successfully updated {update_count} regime records')
        print(f'Backup saved to: {backup_file}')
        print()

        cursor.close()
        conn.close()

    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()
