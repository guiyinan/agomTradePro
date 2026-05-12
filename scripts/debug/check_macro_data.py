"""
Check macro_indicator data to diagnose regime calculation issues.
"""

import os

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

        print('=== Macro Indicator Data Analysis ===\n')

        # Check available indicators
        cursor.execute("""
            SELECT code, COUNT(*) as count
            FROM macro_indicator
            GROUP BY code
            ORDER BY code
        """)

        indicators = cursor.fetchall()
        print('Available indicators:\n')
        for code, count in indicators:
            print(f'  {code:30s}: {count} records')
        print()

        # Get recent PMI and CPI data
        print('=== Recent PMI Data ===\n')
        cursor.execute("""
            SELECT code, value, reporting_period, period_type, source
            FROM macro_indicator
            WHERE code LIKE '%PMI%'
            ORDER BY reporting_period DESC
            LIMIT 15
        """)

        for row in cursor.fetchall():
            code, value, period, period_type, source = row
            print(f'  {period} | {code:20s} | {value}')

        print()

        print('=== Recent CPI Data ===\n')
        cursor.execute("""
            SELECT code, value, reporting_period, period_type, source
            FROM macro_indicator
            WHERE code LIKE '%CPI%'
            ORDER BY reporting_period DESC
            LIMIT 15
        """)

        cpi_data = []
        for row in cursor.fetchall():
            code, value, period, period_type, source = row
            cpi_data.append((period, value))
            print(f'  {period} | {code:20s} | {value}')

        print()

        # Check indicator units
        print('=== Indicator Units ===\n')
        cursor.execute("""
            SELECT DISTINCT code, unit
            FROM macro_indicator
            WHERE code LIKE '%CPI%' OR code LIKE '%PMI%'
            ORDER BY code
        """)

        for row in cursor.fetchall():
            code, unit = row
            print(f'  {code:20s} | unit: {unit}')

        print()

        # Manual calculation of what Z-score should be
        print('=== Manual Z-Score Calculation (Latest Data) ===\n')

        if len(cpi_data) >= 4:
            print('CPI values (most recent first):')
            for i, (period, value) in enumerate(cpi_data[:10]):
                print(f'  {i+1}. {period}: {value}')

            print()

            # Calculate absolute momentum (3-month)
            if len(cpi_data) >= 4:
                current = cpi_data[0][1]
                three_months_ago = cpi_data[3][1]

                abs_momentum = current - three_months_ago

                print('3-Month Absolute Momentum:')
                print(f'  Current: {current}')
                print(f'  3 months ago: {three_months_ago}')
                print(f'  Momentum: {abs_momentum} pp')

                # Check if momentum seems unusually high
                if abs(abs_momentum) > 1.0:
                    print('  WARNING: Momentum seems very high!')

        print()

        # Check the actual regime calculation data
        print('=== Checking Regime Calculation Data ===\n')
        cursor.execute("""
            SELECT
                rl.observed_at,
                rl.growth_momentum_z,
                rl.inflation_momentum_z,
                rl.distribution,
                rl.dominant_regime,
                mi_cpi.value as cpi_value,
                mi_cpi.reporting_period as cpi_period
            FROM regime_log rl
            LEFT JOIN LATERAL (
                SELECT value, reporting_period
                FROM macro_indicator
                WHERE reporting_period <= rl.observed_at
                AND code LIKE '%CPI%'
                ORDER BY reporting_period DESC
                LIMIT 1
            ) mi_cpi ON true
            ORDER BY rl.observed_at DESC
            LIMIT 5
        """)

        print('Recent regime with CPI context:\n')
        for row in cursor.fetchall():
            observed_at, growth_z, inflation_z, dist, dominant, cpi_val, cpi_period = row
            print(f'  {observed_at} | Z:({growth_z:+.2f}, {inflation_z:+.2f}) | {dominant:12s}')
            if cpi_val is not None:
                print(f'    Latest CPI: {cpi_val} (period: {cpi_period})')
            print()

        cursor.close()
        conn.close()

    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()
