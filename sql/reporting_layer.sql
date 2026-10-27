-- =====================================================================
-- Payroll Invoice Importer - Reporting layer (PostgreSQL)
--
-- Sources
--   invoice_entries + import_files  : loaded by import_invoices.py
--   "emp_GEO_info"                  : HR master (branch, location,
--                                     demographics), loaded separately
--
-- Outputs
--   reporting_weekly_summary              : invoice x week x section totals
--   employee_weekly_payroll_enriched_v    : invoice rows + HR attributes
--
-- Built as VIEWS (not CREATE TABLE AS snapshots) so they always reflect
-- the latest import and can never drift from the source tables.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. Weekly summary per invoice / section / adjustment
--    Replaces the static snapshot table reporting_weekly_summary_v2,
--    which stopped at week ending 2026-05-24.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW reporting_weekly_summary AS
SELECT
    f.customer,
    f.invoice_number,
    f.file_name                     AS source_file,
    ie.week_ending,
    ie.section_type,
    ie.adjustment_type,
    COUNT(*)                        AS row_count,
    ROUND(SUM(ie.total_hours), 2)   AS total_hours,
    ROUND(SUM(ie.regular_hours), 2) AS regular_hours,
    ROUND(SUM(ie.overtime_hours), 2) AS overtime_hours,
    ROUND(SUM(ie.total_amount), 2)  AS total_amount
FROM invoice_entries ie
JOIN import_files f ON f.id = ie.import_file_id
GROUP BY
    f.customer, f.invoice_number, f.file_name,
    ie.week_ending, ie.section_type, ie.adjustment_type;


-- ---------------------------------------------------------------------
-- 2. HR master, de-duplicated to ONE row per employee
--    "emp_GEO_info" can hold up to 4 rows per BoldTalentID (one per
--    branch / re-hire). Joining to it directly fans out invoice rows and
--    multiplies hours. DISTINCT ON keeps the most complete, most recent
--    record per employee.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW emp_geo_dedup AS
SELECT DISTINCT ON (g."BoldTalentID")
    g."BoldTalentID"   AS employee_number,
    g."Branch"         AS branch,
    g."City"           AS city,
    g."County"         AS county,
    g."State"          AS state,
    g."DateofBirth"    AS date_of_birth,
    g."Gender"         AS gender,
    g."Race"           AS race,
    g."Veteran"        AS veteran
FROM "emp_GEO_info" g
WHERE g."BoldTalentID" IS NOT NULL
ORDER BY
    g."BoldTalentID",
    (g."DateofBirth" IS NULL),                                   -- prefer rows with demographics
    COALESCE(g."Total Hours 2026", 0) + COALESCE(g."Total Hours 2025", 0)
        + COALESCE(g."Total Hours 2024", 0) DESC,                -- then the most active record
    g.id DESC;                                                   -- then the latest load


-- ---------------------------------------------------------------------
-- 3. Invoice rows enriched with HR attributes
--    LEFT JOIN keeps every invoice row even when the employee is missing
--    from the HR master; the 1:1 dedup view guarantees no fan-out.
--    Age is calculated as of the week-ending date, not today.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW employee_weekly_payroll_enriched_v AS
SELECT
    ie.id                     AS invoice_entry_id,
    f.customer,
    f.invoice_number,
    ie.week_ending,
    ie.employee_number,
    ie.last_name,
    ie.first_name,
    ie.shift,
    ie.plant,
    ie.position,
    ie.section_type,
    ie.adjustment_type,
    ie.total_hours,
    ie.regular_hours,
    ie.overtime_hours,
    ie.total_amount,
    g.branch,
    g.city,
    g.state,
    g.date_of_birth,
    g.gender,
    g.race,
    g.veteran,
    DATE_PART('year', AGE(ie.week_ending, g.date_of_birth))::int AS age_at_week_ending,
    (g.employee_number IS NOT NULL)                               AS has_hr_match
FROM invoice_entries ie
JOIN import_files f        ON f.id = ie.import_file_id
LEFT JOIN emp_geo_dedup g  ON g.employee_number = ie.employee_number;


-- =====================================================================
-- Data-quality checks for the reporting layer
-- Every check should return the "expected" result shown in the comment.
-- =====================================================================

-- DQ1. Join fan-out detector: HR keys that are NOT unique.
--      Any row here means a direct join to "emp_GEO_info" will duplicate data.
SELECT "BoldTalentID", COUNT(*) AS rows_per_employee
FROM "emp_GEO_info"
GROUP BY "BoldTalentID"
HAVING COUNT(*) > 1
ORDER BY rows_per_employee DESC
LIMIT 20;

-- DQ2. Reconciliation: reporting views vs. source.
--      Expected: all three row counts equal, all three hour totals equal.
SELECT 'invoice_entries (source)'           AS layer, COUNT(*)::numeric AS rows, ROUND(SUM(total_hours), 2) AS hours
FROM invoice_entries
UNION ALL
SELECT 'reporting_weekly_summary',           SUM(row_count),                     ROUND(SUM(total_hours), 2)
FROM reporting_weekly_summary
UNION ALL
SELECT 'employee_weekly_payroll_enriched_v', COUNT(*),                            ROUND(SUM(total_hours), 2)
FROM employee_weekly_payroll_enriched_v;

-- DQ3. HR match rate by customer (how complete is the enrichment?)
SELECT
    customer,
    COUNT(*)                                                    AS rows,
    ROUND(100.0 * COUNT(*) FILTER (WHERE has_hr_match) / COUNT(*), 1)         AS hr_match_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE date_of_birth IS NOT NULL) / COUNT(*), 1) AS dob_fill_pct
FROM employee_weekly_payroll_enriched_v
GROUP BY customer
ORDER BY rows DESC;

-- DQ4. Duplicate-load detector for any snapshot table
--      (how the 3x load of the legacy employee_weekly_payroll_enriched was found).
--      Expected for a clean table: a single row with copies = 1.
SELECT copies, COUNT(*) AS keys
FROM (
    SELECT COUNT(*) AS copies
    FROM employee_weekly_payroll_enriched
    GROUP BY employees_number, week_ending, customer, total_hours
) x
GROUP BY copies
ORDER BY copies;
