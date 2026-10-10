\set ON_ERROR_STOP on
\getenv exporter_password AGOMTRADEPRO_S6_EXPORTER_PASSWORD
\getenv database POSTGRES_DB

SELECT length(:'exporter_password') >= 32
   AND :'exporter_password' !~ '[^A-Za-z0-9_-]'
       AS exporter_password_valid
\gset
\if :exporter_password_valid
\else
  \echo [ERROR] exporter role password contract failed
  SELECT 1 / 0 AS exporter_password_contract_guard_failed;
\endif

SELECT 'CREATE ROLE agomtradepro_s6_exporter'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'agomtradepro_s6_exporter'
)
\gexec
ALTER ROLE agomtradepro_s6_exporter
    WITH LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE agomtradepro_s6_exporter SET default_transaction_read_only = 'on';
SELECT pg_catalog.format(
    'ALTER ROLE %I PASSWORD %L', 'agomtradepro_s6_exporter', :'exporter_password'
)
\gexec
GRANT CONNECT ON DATABASE :"database" TO agomtradepro_s6_exporter;
GRANT USAGE ON SCHEMA public TO agomtradepro_s6_exporter;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agomtradepro_s6_exporter;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO agomtradepro_s6_exporter;
ALTER DEFAULT PRIVILEGES FOR ROLE agomtradepro_owner IN SCHEMA public
    GRANT SELECT ON TABLES TO agomtradepro_s6_exporter;
ALTER DEFAULT PRIVILEGES FOR ROLE agomtradepro_owner IN SCHEMA public
    GRANT SELECT ON SEQUENCES TO agomtradepro_s6_exporter;

DO $read_only_exporter_guard$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members
        WHERE member = 'agomtradepro_s6_exporter'::pg_catalog.regrole
    ) THEN
        RAISE EXCEPTION 'S6 exporter role must have no role memberships';
    END IF;
    IF pg_catalog.has_database_privilege(
        'agomtradepro_s6_exporter', current_database(), 'CREATE'
    ) OR pg_catalog.has_database_privilege(
        'agomtradepro_s6_exporter', current_database(), 'TEMP'
    ) OR pg_catalog.has_schema_privilege(
        'agomtradepro_s6_exporter', 'public', 'CREATE'
    ) THEN
        RAISE EXCEPTION 'S6 exporter role has a write-capable database privilege';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND (
              pg_catalog.has_table_privilege('agomtradepro_s6_exporter', relation.oid, 'INSERT')
              OR pg_catalog.has_table_privilege('agomtradepro_s6_exporter', relation.oid, 'UPDATE')
              OR pg_catalog.has_table_privilege('agomtradepro_s6_exporter', relation.oid, 'DELETE')
              OR pg_catalog.has_table_privilege('agomtradepro_s6_exporter', relation.oid, 'TRUNCATE')
              OR pg_catalog.has_table_privilege('agomtradepro_s6_exporter', relation.oid, 'REFERENCES')
              OR pg_catalog.has_table_privilege('agomtradepro_s6_exporter', relation.oid, 'TRIGGER')
          )
    ) THEN
        RAISE EXCEPTION 'S6 exporter role has a table write privilege';
    END IF;
END
$read_only_exporter_guard$;
\echo s6_exporter_role_bootstrap=ok
