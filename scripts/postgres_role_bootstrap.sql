\set ON_ERROR_STOP on
\getenv runtime_password AGOMTRADEPRO_RUNTIME_PASSWORD
\getenv migrator_password AGOMTRADEPRO_MIGRATOR_PASSWORD
\getenv admin_password AGOMTRADEPRO_ADMIN_PASSWORD
\getenv admin_role POSTGRES_USER

SELECT length(:'admin_password') >= 32
   AND :'admin_password' !~ '[^A-Za-z0-9_-]'
   AND :'admin_password' !~* '^(replace-with|change-this|your-password|password|secret|changeme|example|placeholder)'
   AND length(:'runtime_password') >= 32
   AND length(:'migrator_password') >= 32
   AND :'admin_password' <> :'runtime_password'
   AND :'admin_password' <> :'migrator_password'
   AND :'runtime_password' <> :'migrator_password'
   AND :'runtime_password' !~ '[^A-Za-z0-9_-]'
   AND :'migrator_password' !~ '[^A-Za-z0-9_-]'
   AND :'runtime_password' !~* '^(replace-with|change-this|your-password|password|secret)'
   AND :'migrator_password' !~* '^(replace-with|change-this|your-password|password|secret)'
       AS role_passwords_valid
\gset
\if :role_passwords_valid
\else
  \echo [ERROR] role passwords must be distinct, URL-safe values with at least 32 characters
  \quit 3
\endif

BEGIN;

SELECT 'CREATE ROLE agomtradepro_owner'
WHERE NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'agomtradepro_owner')
\gexec
SELECT 'CREATE ROLE agomtradepro_migrator'
WHERE NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'agomtradepro_migrator')
\gexec
SELECT 'CREATE ROLE agomtradepro_runtime'
WHERE NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'agomtradepro_runtime')
\gexec

ALTER ROLE agomtradepro_owner
    WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
ALTER ROLE agomtradepro_migrator
    WITH LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE agomtradepro_runtime
    WITH LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

SELECT pg_catalog.format('ALTER ROLE agomtradepro_runtime PASSWORD %L', :'runtime_password')
\gexec
SELECT pg_catalog.format('ALTER ROLE agomtradepro_migrator PASSWORD %L', :'migrator_password')
\gexec
SELECT pg_catalog.format('ALTER ROLE %I PASSWORD %L', :'admin_role', :'admin_password')
\gexec

DO $clear_memberships$
DECLARE
    membership record;
BEGIN
    FOR membership IN
        SELECT parent.rolname
        FROM pg_catalog.pg_auth_members AS link
        JOIN pg_catalog.pg_roles AS parent ON parent.oid = link.roleid
        WHERE link.member = 'agomtradepro_owner'::pg_catalog.regrole
    LOOP
        EXECUTE pg_catalog.format('REVOKE %I FROM agomtradepro_owner', membership.rolname);
    END LOOP;

    FOR membership IN
        SELECT parent.rolname
        FROM pg_catalog.pg_auth_members AS link
        JOIN pg_catalog.pg_roles AS parent ON parent.oid = link.roleid
        WHERE link.member = 'agomtradepro_runtime'::pg_catalog.regrole
    LOOP
        EXECUTE pg_catalog.format('REVOKE %I FROM agomtradepro_runtime', membership.rolname);
    END LOOP;

    FOR membership IN
        SELECT parent.rolname
        FROM pg_catalog.pg_auth_members AS link
        JOIN pg_catalog.pg_roles AS parent ON parent.oid = link.roleid
        WHERE link.member = 'agomtradepro_migrator'::pg_catalog.regrole
          AND parent.rolname <> 'agomtradepro_owner'
    LOOP
        EXECUTE pg_catalog.format('REVOKE %I FROM agomtradepro_migrator', membership.rolname);
    END LOOP;

    FOR membership IN
        SELECT child.rolname
        FROM pg_catalog.pg_auth_members AS link
        JOIN pg_catalog.pg_roles AS child ON child.oid = link.member
        WHERE link.roleid = 'agomtradepro_owner'::pg_catalog.regrole
          AND child.rolname <> 'agomtradepro_migrator'
    LOOP
        EXECUTE pg_catalog.format('REVOKE agomtradepro_owner FROM %I', membership.rolname);
    END LOOP;
END
$clear_memberships$;

REVOKE agomtradepro_owner FROM agomtradepro_migrator;
GRANT agomtradepro_owner TO agomtradepro_migrator
    WITH INHERIT FALSE, SET TRUE, ADMIN FALSE;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM agomtradepro_runtime;
GRANT USAGE ON SCHEMA public TO agomtradepro_runtime;
GRANT USAGE, CREATE ON SCHEMA public TO agomtradepro_owner;

SELECT pg_catalog.format(
           'ALTER TABLE %I.%I OWNER TO agomtradepro_owner',
           namespace.nspname,
           relation.relname
       )
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relkind IN ('r', 'p')
  AND relation.relowner = :'admin_role'::pg_catalog.regrole
\gexec

SELECT pg_catalog.format(
           'ALTER SEQUENCE %I.%I OWNER TO agomtradepro_owner',
           namespace.nspname,
           relation.relname
       )
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relkind = 'S'
  AND relation.relowner = :'admin_role'::pg_catalog.regrole
\gexec

SELECT 'ALTER TABLE public.account_authority_generation OWNER TO agomtradepro_owner'
WHERE pg_catalog.to_regclass('public.account_authority_generation') IS NOT NULL
\gexec
SELECT 'ALTER FUNCTION public.account_authority_generation_bump() OWNER TO agomtradepro_owner'
WHERE pg_catalog.to_regprocedure('public.account_authority_generation_bump()') IS NOT NULL
\gexec
SELECT 'ALTER FUNCTION public.account_authority_generation_bump() SET search_path = pg_catalog'
WHERE pg_catalog.to_regprocedure('public.account_authority_generation_bump()') IS NOT NULL
\gexec
SELECT 'ALTER FUNCTION public.account_authority_generation_fence_lock() OWNER TO agomtradepro_owner'
WHERE pg_catalog.to_regprocedure('public.account_authority_generation_fence_lock()') IS NOT NULL
\gexec
SELECT 'ALTER FUNCTION public.account_authority_generation_fence_lock() SET search_path = pg_catalog'
WHERE pg_catalog.to_regprocedure('public.account_authority_generation_fence_lock()') IS NOT NULL
\gexec

SET ROLE agomtradepro_owner;
ALTER DEFAULT PRIVILEGES
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES
    REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO agomtradepro_runtime;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO agomtradepro_runtime;
ALTER DEFAULT PRIVILEGES
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

SELECT pg_catalog.format(
           'REVOKE ALL PRIVILEGES ON TABLE %I.%I FROM PUBLIC, agomtradepro_runtime',
           namespace.nspname,
           relation.relname
       )
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND relation.relowner = 'agomtradepro_owner'::pg_catalog.regrole
\gexec

SELECT pg_catalog.format(
           'REVOKE ALL PRIVILEGES ON SEQUENCE %I.%I FROM PUBLIC, agomtradepro_runtime',
           namespace.nspname,
           relation.relname
       )
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relkind = 'S'
  AND relation.relowner = 'agomtradepro_owner'::pg_catalog.regrole
\gexec

SELECT pg_catalog.format(
           'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I.%I TO agomtradepro_runtime',
           namespace.nspname,
           relation.relname
       )
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND relation.relowner = 'agomtradepro_owner'::pg_catalog.regrole
\gexec

SELECT pg_catalog.format(
           'GRANT USAGE, SELECT ON SEQUENCE %I.%I TO agomtradepro_runtime',
           namespace.nspname,
           relation.relname
       )
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
WHERE namespace.nspname = 'public'
  AND relation.relkind = 'S'
  AND relation.relowner = 'agomtradepro_owner'::pg_catalog.regrole
\gexec

SELECT pg_catalog.to_regclass('public.account_authority_generation') IS NOT NULL
       AS generation_table_exists
\gset
\if :generation_table_exists
REVOKE ALL ON TABLE public.account_authority_generation FROM PUBLIC, agomtradepro_runtime;
GRANT SELECT ON TABLE public.account_authority_generation TO agomtradepro_runtime;
\endif

SELECT pg_catalog.to_regprocedure('public.account_authority_generation_bump()') IS NOT NULL
       AS bump_function_exists
\gset
\if :bump_function_exists
REVOKE EXECUTE ON FUNCTION public.account_authority_generation_bump()
    FROM PUBLIC, agomtradepro_runtime;
\endif

SELECT pg_catalog.to_regprocedure('public.account_authority_generation_fence_lock()') IS NOT NULL
       AS fence_lock_function_exists
\gset
\if :fence_lock_function_exists
REVOKE EXECUTE ON FUNCTION public.account_authority_generation_fence_lock()
    FROM PUBLIC, agomtradepro_runtime;
GRANT EXECUTE ON FUNCTION public.account_authority_generation_fence_lock()
    TO agomtradepro_runtime;
\endif

RESET ROLE;

DO $postconditions$
DECLARE
    trigger_count integer;
    source_table_count integer;
    invalid_source_owner_count integer;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles
        WHERE rolname = session_user AND rolsuper
    ) THEN
        RAISE EXCEPTION 'role bootstrap connection must use the PostgreSQL admin role';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members
        WHERE member = 'agomtradepro_runtime'::pg_catalog.regrole
    ) THEN
        RAISE EXCEPTION 'runtime role must not be a member of any role';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM (
        SELECT relation.relowner AS owner_oid
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT function.proowner
        FROM pg_catalog.pg_proc AS function
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = function.pronamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT data_type.typowner
        FROM pg_catalog.pg_type AS data_type
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = data_type.typnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT collation.collowner
        FROM pg_catalog.pg_collation AS collation
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = collation.collnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT conversion.conowner
        FROM pg_catalog.pg_conversion AS conversion
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = conversion.connamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT operator_class.opcowner
        FROM pg_catalog.pg_opclass AS operator_class
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = operator_class.opcnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT operator_family.opfowner
        FROM pg_catalog.pg_opfamily AS operator_family
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = operator_family.opfnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT config.cfgowner
        FROM pg_catalog.pg_ts_config AS config
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = config.cfgnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT dictionary.dictowner
        FROM pg_catalog.pg_ts_dict AS dictionary
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = dictionary.dictnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT extension.extowner
        FROM pg_catalog.pg_extension AS extension
        WHERE extension.extnamespace = 'public'::pg_catalog.regnamespace
        UNION ALL
        SELECT statistic.stxowner
        FROM pg_catalog.pg_statistic_ext AS statistic
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = statistic.stxnamespace
        WHERE namespace.nspname = 'public'
        UNION ALL
        SELECT namespace.nspowner
        FROM pg_catalog.pg_namespace AS namespace
        WHERE namespace.nspname = 'public'
        ) AS public_object_owners
        WHERE public_object_owners.owner_oid = 'agomtradepro_runtime'::pg_catalog.regrole
    ) THEN
        RAISE EXCEPTION 'runtime still owns a public database object';
    END IF;
    IF NOT pg_catalog.pg_has_role(
        'agomtradepro_migrator', 'agomtradepro_owner', 'SET'
    ) THEN
        RAISE EXCEPTION 'migrator must be able to SET ROLE owner';
    END IF;
    IF pg_catalog.pg_has_role(
        'agomtradepro_runtime', 'agomtradepro_owner', 'MEMBER'
    ) THEN
        RAISE EXCEPTION 'runtime must not be a member of owner';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_auth_members AS link
        WHERE link.member = 'agomtradepro_migrator'::pg_catalog.regrole
          AND link.roleid = 'agomtradepro_owner'::pg_catalog.regrole
          AND NOT link.admin_option
          AND COALESCE((pg_catalog.to_jsonb(link)->>'set_option')::boolean, true)
          AND NOT COALESCE((pg_catalog.to_jsonb(link)->>'inherit_option')::boolean, false)
    ) OR (
        SELECT count(*)
        FROM pg_catalog.pg_auth_members
        WHERE member = 'agomtradepro_migrator'::pg_catalog.regrole
    ) <> 1 THEN
        RAISE EXCEPTION 'migrator must have only non-admin membership in owner';
    END IF;
    IF (
        SELECT count(*) FROM pg_catalog.pg_auth_members
        WHERE roleid = 'agomtradepro_owner'::pg_catalog.regrole
    ) <> 1 OR NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members AS link
        WHERE link.roleid = 'agomtradepro_owner'::pg_catalog.regrole
          AND link.member = 'agomtradepro_migrator'::pg_catalog.regrole
          AND NOT link.admin_option
          AND COALESCE((pg_catalog.to_jsonb(link)->>'set_option')::boolean, true)
          AND NOT COALESCE((pg_catalog.to_jsonb(link)->>'inherit_option')::boolean, false)
    ) THEN
        RAISE EXCEPTION 'migrator must be the only member able to SET ROLE owner';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_namespace AS namespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(
            COALESCE(namespace.nspacl,
                     pg_catalog.acldefault('n', namespace.nspowner))
        ) AS acl
        WHERE namespace.nspname = 'public'
          AND acl.grantee = 0
          AND acl.privilege_type = 'CREATE'
    ) THEN
        RAISE EXCEPTION 'PUBLIC still has CREATE on the public schema';
    END IF;

    IF pg_catalog.to_regclass('public.account_authority_generation') IS NOT NULL THEN
        SELECT count(*), count(DISTINCT relation.oid),
               count(*) FILTER (
                   WHERE relation.relowner <> 'agomtradepro_owner'::pg_catalog.regrole
               )
        INTO trigger_count, source_table_count, invalid_source_owner_count
        FROM pg_catalog.pg_trigger AS trigger
        JOIN pg_catalog.pg_class AS relation ON relation.oid = trigger.tgrelid
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND NOT trigger.tgisinternal
          AND trigger.tgname IN ('acct_auth_gen_stmt', 'acct_auth_gen_truncate');

        IF trigger_count <> 44 OR source_table_count <> 22 OR invalid_source_owner_count <> 0 THEN
            RAISE EXCEPTION 'authority source ownership/trigger inventory is incomplete';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.account_authority_generation
            HAVING count(*) = 1
               AND bool_and(singleton = 1 AND generation >= 0)
        ) THEN
            RAISE EXCEPTION 'authority generation singleton row is invalid';
        END IF;
        IF pg_catalog.to_regprocedure('public.account_authority_generation_fence_lock()') IS NULL THEN
            RAISE EXCEPTION 'authority generation fence lock function is missing';
        END IF;
    END IF;
END
$postconditions$;

COMMIT;

\echo postgres_role_bootstrap=ok
