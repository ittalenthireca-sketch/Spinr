-- RLS coverage audit — Phase 1.2 (production-readiness audit D09)
--
-- Run this against the production/staging Postgres cluster whenever you
-- change RLS posture, as a gate in CI, or on demand to answer the
-- question "does every public-schema table enforce row-level security?".
--
-- Usage
-- -----
-- Against a live DB (service role or any superuser/owner):
--
--     psql "$DATABASE_URL" -f backend/scripts/rls_audit.sql
--
-- Expected output (PASS): all three sections return ZERO rows.
--
-- Sections
-- --------
--  1. Tables in ``public`` WITHOUT RLS enabled.
--  2. Tables in ``public`` with RLS enabled but ZERO policies.
--     (Note: RLS-enabled + no-policy is already deny-by-default for
--      anon/authenticated; this flags it anyway because it's almost
--      always a missed classification.)
--  3. Policies that grant ``FOR ALL`` or ``FOR SELECT`` with
--     ``USING (true)`` to the ``authenticated`` role — a common
--     footgun when copy-pasting from templates.
--
-- Each section prints a header row via RAISE NOTICE so the output is
-- readable in a CI log even when the result set is empty.


\echo ''
\echo '== RLS AUDIT =='
\echo ''

\echo '[1] public tables WITHOUT row_security enabled (expected: 0 rows)'
SELECT
    c.relname          AS table_name,
    c.relrowsecurity   AS rls_enabled,
    c.relforcerowsecurity AS rls_forced
FROM   pg_class     c
JOIN   pg_namespace n ON n.oid = c.relnamespace
WHERE  n.nspname = 'public'
  AND  c.relkind = 'r'           -- ordinary tables only
  AND  c.relrowsecurity = false
ORDER  BY c.relname;

\echo ''
\echo '[2] public tables with RLS enabled but ZERO policies (expected: 0 rows)'
SELECT
    c.relname AS table_name
FROM   pg_class     c
JOIN   pg_namespace n ON n.oid = c.relnamespace
LEFT   JOIN pg_policy p ON p.polrelid = c.oid
WHERE  n.nspname = 'public'
  AND  c.relkind = 'r'
  AND  c.relrowsecurity = true
GROUP  BY c.relname
HAVING COUNT(p.polname) = 0
ORDER  BY c.relname;

\echo ''
\echo '[3] policies that open ALL or SELECT to authenticated with USING(true)'
\echo '    (expected: 0 rows — or only rows you have knowingly allow-listed)'
SELECT
    schemaname,
    tablename,
    policyname,
    cmd,
    roles,
    qual
FROM   pg_policies
WHERE  schemaname = 'public'
  AND  'authenticated' = ANY (roles)
  AND  cmd IN ('ALL', 'SELECT')
  AND  qual = 'true'
  -- Known allow-listed public-read catalogue tables go here:
  AND  tablename NOT IN ('subscription_plans', 'quests', 'area_fees',
                         'vehicle_types', 'fare_configs', 'service_areas',
                         'faqs', 'document_requirements')
ORDER  BY tablename, policyname;

\echo ''
\echo '== END RLS AUDIT =='
