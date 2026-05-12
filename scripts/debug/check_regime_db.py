"""
Check Regime data in PostgreSQL database.

This script directly queries the database without Django dependencies.
"""

import os

from dotenv import load_dotenv

load_dotenv()

db_url = os.environ.get('DATABASE_URL', '')
print(f'Database URL: {db_url[:60]}...')
print()

# Parse DATABASE_URL
# postgresql://user:pass@host:port/db
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

    # Try using pg8000 (pure Python PostgreSQL driver)
    try:
        import pg8000
        print('Connecting using pg8000...')

        conn = pg8000.connect(
            host=host,
            port=int(port),
            database=database,
            user=user,
            password=password
        )
        cursor = conn.cursor()

        # Check if table exists
        cursor.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name LIKE '%regime%'
        """)
        tables = cursor.fetchall()
        print(f'Regime tables: {tables}')
        print()

        # Get recent regime data
        cursor.execute("""
            SELECT
                id, observed_at, dominant_regime, confidence,
                growth_momentum_z, inflation_momentum_z, distribution,
                created_at
            FROM regime_log
            ORDER BY observed_at DESC
            LIMIT 30
        """)

        rows = cursor.fetchall()
        print(f'=== Recent Regime Data ({len(rows)} rows) ===\n')

        for row in rows:
            id_val, observed_at, dominant, conf, growth_z, inflation_z, dist, created = row
            print(f'ID:{id_val:4d} | {observed_at} | {dominant:12s} | conf:{conf:.3f} | Z:({growth_z:+.2f}, {inflation_z:+.2f})')
            if dist:
                print(f'       Distribution: {dist}')

        print()

        # Get regime distribution
        cursor.execute("""
            SELECT dominant_regime, COUNT(*) as count
            FROM regime_log
            GROUP BY dominant_regime
            ORDER BY count DESC
        """)
        regime_counts = cursor.fetchall()
        print('=== Regime Distribution ===')
        for regime, count in regime_counts:
            print(f'  {regime:12s}: {count}')
        print()

        # Check for potential issues
        cursor.execute("""
            SELECT
                COUNT(*) FILTER (WHERE confidence < 0.3) as low_conf,
                COUNT(*) FILTER (WHERE confidence > 0.95) as high_conf,
                MIN(observed_at) as min_date,
                MAX(observed_at) as max_date,
                COUNT(*) as total
            FROM regime_log
        """)
        stats = cursor.fetchone()
        low_conf, high_conf, min_date, max_date, total = stats

        print('=== Statistics ===')
        print(f'  Total records: {total}')
        print(f'  Low confidence (<0.3): {low_conf}')
        print(f'  High confidence (>0.95): {high_conf}')
        print(f'  Date range: {min_date} to {max_date}')
        print()

        cursor.close()
        conn.close()

    except ImportError:
        print('pg8000 not installed, trying direct connection...')
        print('Please install: pip install pg8000')
    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()
else:
    print('Not using PostgreSQL DATABASE_URL')
