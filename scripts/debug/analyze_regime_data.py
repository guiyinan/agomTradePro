"""
Analyze Regime Data Issues in PostgreSQL.

This script checks the raw data used for regime calculation.
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

        print('=== Analyzing Regime Data Issues ===\n')

        # Check recent regime data with potential issues
        cursor.execute("""
            SELECT
                id, observed_at, dominant_regime, confidence,
                growth_momentum_z, inflation_momentum_z, distribution
            FROM regime_log
            ORDER BY observed_at DESC
            LIMIT 15
        """)

        rows = cursor.fetchall()

        print('Recent Regime Data (looking for issues):\n')
        for row in rows:
            id_val, observed_at, dominant, conf, growth_z, inflation_z, dist = row

            # Flag potential issues
            issues = []
            if abs(inflation_z) > 2.0:
                issues.append(f'VERY HIGH inflation Z: {inflation_z:.2f}')
            elif abs(inflation_z) > 1.5:
                issues.append(f'High inflation Z: {inflation_z:.2f}')

            if abs(growth_z) > 2.0:
                issues.append(f'VERY HIGH growth Z: {growth_z:.2f}')
            elif abs(growth_z) > 1.5:
                issues.append(f'High growth Z: {growth_z:.2f}')

            if conf < 0.4:
                issues.append(f'Low confidence: {conf:.3f}')

            status = ' [ISSUE: ' + ', '.join(issues) + ']' if issues else ''

            print(f'ID:{id_val:3d} | {observed_at} | {dominant:12s} | Z:({growth_z:+.2f}, {inflation_z:+.2f}){status}')

        print()

        # Get the raw macro data to understand what's happening
        print('=== Raw Macro Data Analysis ===\n')

        # Check recent PMI and CPI data
        cursor.execute("""
            SELECT code, value, reporting_period, published_at
            FROM macro_macroindicator
            WHERE code IN ('CN_PMI_MANUFACTURING', 'CN_CPI_YOY')
            ORDER BY reporting_period DESC
            LIMIT 20
        """)

        macro_rows = cursor.fetchall()
        print(f'Recent PMI/CPI data ({len(macro_rows)} rows):\n')

        pmi_data = []
        cpi_data = []

        for row in macro_rows:
            code, value, period, published = row
            print(f'{code:20s} | {period} | value: {value}')

            if 'PMI' in code:
                pmi_data.append((period, value))
            elif 'CPI' in code:
                cpi_data.append((period, value))

        print()

        # Calculate what the momentum should be manually
        print('=== Manual Momentum Calculation ===\n')

        if len(cpi_data) >= 4:
            print('CPI data (most recent first):')
            for period, value in cpi_data[:6]:
                print(f'  {period}: {value}%')

            # Calculate 3-month absolute momentum
            if len(cpi_data) >= 4:
                current = cpi_data[0][1]  # Most recent
                three_months_ago = cpi_data[3][1]  # 3 periods back

                abs_momentum = current - three_months_ago
                rel_momentum = (current - three_months_ago) / abs(three_months_ago) if three_months_ago != 0 else 0

                print()
                print(f'3-month momentum calculation:')
                print(f'  Current: {current}%')
                print(f'  3 months ago: {three_months_ago}%')
                print(f'  Absolute momentum: {abs_momentum:.4f} pp')
                print(f'  Relative momentum: {rel_momentum:.4f} ({rel_momentum*100:.1f}%)')

        print()

        # Check if there's an issue with how distribution is stored
        print('=== Checking Distribution Format ===\n')
        cursor.execute("""
            SELECT id, observed_at, distribution, dominant_regime, confidence
            FROM regime_log
            ORDER BY observed_at DESC
            LIMIT 5
        """)

        for row in cursor.fetchall():
            id_val, observed_at, dist, dominant, conf = row
            print(f'ID: {id_val}, Date: {observed_at}')
            print(f'  Distribution type: {type(dist)}')
            print(f'  Distribution: {dist}')
            print(f'  Dominant: {dominant}, Confidence: {conf}')
            print()

        cursor.close()
        conn.close()

    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()
