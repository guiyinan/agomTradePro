"""
Check all tables and find macro data.
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

        print('=== All Tables in Database ===\n')

        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)

        tables = cursor.fetchall()
        for table in tables:
            print(f'  {table[0]}')

        print()

        # Check for macro indicator data in various tables
        possible_macro_tables = [
            'macro_indicator',
            'macroindicator',
            'indicator',
            'indicators'
        ]

        for table_name in possible_macro_tables:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = %s
                )
            """, (table_name,))
            exists = cursor.fetchone()[0]

            if exists:
                print(f'Found table: {table_name}')
                cursor.execute(f"""
                    SELECT COUNT(*) FROM {table_name}
                """)
                count = cursor.fetchone()[0]
                print(f'  Records: {count}')

                if count > 0 and count < 100:
                    cursor.execute(f"""
                        SELECT * FROM {table_name}
                        LIMIT 5
                    """)
                    print('  Sample data:')
                    for row in cursor.fetchall():
                        print(f'    {row}')

        print()

        # Check the regime_log table structure
        print('=== Regime Log Table Structure ===\n')
        cursor.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'regime_log'
            ORDER BY ordinal_position
        """)

        for col in cursor.fetchall():
            print(f'  {col[0]}: {col[1]}')

        print()

        cursor.close()
        conn.close()

    except Exception as e:
        print(f'Error: {e}')
        import traceback
        traceback.print_exc()
