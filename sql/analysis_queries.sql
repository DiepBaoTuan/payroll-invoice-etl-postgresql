-- =====================================================================
-- Payroll Invoice Importer - Analytical queries (PostgreSQL)
-- Run against the tables defined in sql/schema.sql
-- =====================================================================


-- ---------------------------------------------------------------------
-- Q1. Monthly billed amount per customer + month-over-month growth
-- Skills: CTE, date_trunc, LAG window function, NULLIF
-- ---------------------------------------------------------------------
WITH monthly AS (
    SELECT
        f.customer,
        date_trunc('month', ie.week_ending)::date AS month,
        SUM(ie.total_amount)                      AS billed
    FROM invoice_entries ie
    JOIN import_files f ON f.id = ie.import_file_id
    GROUP BY f.customer, date_trunc('month', ie.week_ending)
)
SELECT
    customer,
    month,
    billed,
    LAG(billed) OVER w AS prev_month_billed,
    ROUND(100.0 * (billed - LAG(billed) OVER w)
          / NULLIF(LAG(billed) OVER w, 0), 1) AS mom_growth_pct
FROM monthly
WINDOW w AS (PARTITION BY customer ORDER BY month)
ORDER BY customer, month;


-- ---------------------------------------------------------------------
-- Q2. Weekly hours, overtime ratio and headcount per customer
-- Skills: aggregation, COUNT DISTINCT, NULLIF to avoid divide-by-zero
-- ---------------------------------------------------------------------
SELECT
    f.customer,
    ie.week_ending,
    COUNT(DISTINCT ie.employee_number)                         AS headcount,
    SUM(ie.regular_hours)                                      AS regular_hours,
    SUM(ie.overtime_hours)                                     AS overtime_hours,
    ROUND(100.0 * SUM(ie.overtime_hours)
          / NULLIF(SUM(ie.total_hours), 0), 1)                 AS overtime_pct,
    SUM(ie.total_amount)                                       AS billed
FROM invoice_entries ie
JOIN import_files f ON f.id = ie.import_file_id
GROUP BY f.customer, ie.week_ending
ORDER BY f.customer, ie.week_ending DESC;


-- ---------------------------------------------------------------------
-- Q3. Top 10 employees by hours worked each month
-- Skills: RANK() OVER (PARTITION BY ...), filtering on a window result
-- ---------------------------------------------------------------------
WITH emp_month AS (
    SELECT
        date_trunc('month', week_ending)::date AS month,
        employee_number,
        MAX(first_name || ' ' || last_name)    AS employee_name,
        SUM(total_hours)                       AS hours
    FROM invoice_entries
    GROUP BY 1, 2
),
ranked AS (
    SELECT *,
           RANK() OVER (PARTITION BY month ORDER BY hours DESC) AS hours_rank
    FROM emp_month
)
SELECT month, hours_rank, employee_number, employee_name, hours
FROM ranked
WHERE hours_rank <= 10
ORDER BY month DESC, hours_rank;


-- ---------------------------------------------------------------------
-- Q4. Average bill-rate markup over pay rate by position
-- Skills: derived metrics, HAVING, excluding adjustment rows
-- ---------------------------------------------------------------------
SELECT
    position,
    COUNT(*)                                                   AS rows,
    ROUND(AVG(pay_rate), 2)                                    AS avg_pay_rate,
    ROUND(AVG(regular_bill_rate), 2)                           AS avg_bill_rate,
    ROUND(AVG(100.0 * (regular_bill_rate - pay_rate)
              / NULLIF(pay_rate, 0)), 1)                       AS avg_markup_pct
FROM invoice_entries
WHERE pay_rate > 0
  AND regular_bill_rate > 0
  AND adjustment_type IS NULL          -- exclude pay/bill difference rows
GROUP BY position
HAVING COUNT(*) >= 5
ORDER BY avg_markup_pct DESC;


-- ---------------------------------------------------------------------
-- Q5. Cross-invoice duplicate audit
-- Same employee / week / position / hours / amount billed on two
-- different invoices -> potential double billing to review.
-- Skills: self-join, inequality join to avoid mirrored pairs
-- ---------------------------------------------------------------------
SELECT
    a.employee_number,
    a.week_ending,
    a.position,
    a.total_hours,
    a.total_amount,
    fa.invoice_number AS invoice_a,
    fb.invoice_number AS invoice_b,
    a.force_import OR b.force_import AS was_force_imported
FROM invoice_entries a
JOIN invoice_entries b
  ON  a.employee_number = b.employee_number
  AND a.week_ending     = b.week_ending
  AND a.position        IS NOT DISTINCT FROM b.position
  AND a.section_type    IS NOT DISTINCT FROM b.section_type
  AND a.total_hours     = b.total_hours
  AND a.total_amount    = b.total_amount
  AND a.import_file_id  < b.import_file_id
JOIN import_files fa ON fa.id = a.import_file_id
JOIN import_files fb ON fb.id = b.import_file_id
ORDER BY a.week_ending DESC, a.employee_number;


-- ---------------------------------------------------------------------
-- Q6. Import pipeline health by month
-- Skills: conditional aggregation with FILTER, durations with intervals
-- ---------------------------------------------------------------------
SELECT
    date_trunc('month', started_at)::date                      AS month,
    COUNT(*)                                                   AS runs,
    COUNT(*) FILTER (WHERE status = 'success')                 AS successful_runs,
    COUNT(*) FILTER (WHERE status LIKE 'stopped%')             AS preview_only_runs,
    COUNT(*) FILTER (WHERE status = 'completed_with_errors')   AS runs_with_errors,
    ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'success')
          / NULLIF(COUNT(*) FILTER (WHERE status NOT LIKE 'stopped%'), 0), 1)
                                                               AS import_success_rate_pct,
    SUM(files_processed)                                       AS files_processed,
    SUM(rows_inserted)                                         AS rows_inserted,
    SUM(rows_skipped)                                          AS rows_skipped,
    ROUND(AVG(EXTRACT(EPOCH FROM finished_at - started_at)), 1) AS avg_run_seconds
FROM import_runs
GROUP BY 1
ORDER BY 1 DESC;


-- ---------------------------------------------------------------------
-- Q7. Most frequent import error types
-- Skills: text normalization with regexp_replace, GROUP BY on an expression
-- (first sentence of the message, row numbers collapsed to "N")
-- ---------------------------------------------------------------------
SELECT
    regexp_replace(split_part(error_message, '.', 1), '\d+', 'N', 'g') AS error_type,
    COUNT(*)                          AS occurrences,
    COUNT(DISTINCT file_name)         AS files_affected,
    MAX(e.import_run_id)              AS last_seen_run
FROM import_errors e
GROUP BY 1
ORDER BY occurrences DESC
LIMIT 20;


-- ---------------------------------------------------------------------
-- Q8. Year-to-date running payroll total per customer
-- Skills: cumulative SUM() OVER with ORDER BY
-- ---------------------------------------------------------------------
WITH weekly AS (
    SELECT
        f.customer,
        ie.week_ending,
        SUM(ie.total_amount) AS weekly_billed
    FROM invoice_entries ie
    JOIN import_files f ON f.id = ie.import_file_id
    WHERE ie.week_ending >= date_trunc('year', CURRENT_DATE)
    GROUP BY f.customer, ie.week_ending
)
SELECT
    customer,
    week_ending,
    weekly_billed,
    SUM(weekly_billed) OVER (PARTITION BY customer ORDER BY week_ending) AS ytd_billed
FROM weekly
ORDER BY customer, week_ending;
