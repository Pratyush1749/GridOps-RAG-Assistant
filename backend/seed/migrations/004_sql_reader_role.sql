-- =============================================================================
-- 004_sql_reader_role.sql
-- A role that can only SELECT the seven ops tables. SQLService.execute_sql
-- switches to it (SET LOCAL ROLE) before running approved Text2SQL queries,
-- so Postgres itself refuses reads of `users`, the LangGraph checkpoint
-- tables, or anything else, whatever the SQL text says.
--
-- Idempotent (re-run on every API start). Runs after 003, which recreates the
-- ops tables, so the grants are re-applied each time. If the connecting user
-- may not create roles, this is skipped with a NOTICE and execute_sql fails
-- closed until a DBA creates the role (or SQL_READER_ROLE is set to '').
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gridops_reader') THEN
        CREATE ROLE gridops_reader NOLOGIN;
    END IF;
    GRANT USAGE ON SCHEMA public TO gridops_reader;
    GRANT SELECT ON substations, feeders, transformers, meters, outages,
                    scada_alarms, crew_dispatch_logs TO gridops_reader;
    -- Lets a non-superuser application role switch to it.
    EXECUTE format('GRANT gridops_reader TO %I', current_user);
EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'gridops_reader role not created: %', SQLERRM;
END
$$;
