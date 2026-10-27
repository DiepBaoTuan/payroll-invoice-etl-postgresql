# Payroll Invoice Importer

> A review-first ETL pipeline that turns messy payroll invoice Excel files into clean, validated, analysis-ready data in PostgreSQL.

![Python](https://img.shields.io/badge/Python-3.x-blue)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supabase-336791)
![pandas](https://img.shields.io/badge/pandas-2.x-150458)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.x-red)

---

## 1. The business problem

Payroll invoices arrive every week as Excel files from vendors. Each file is built by hand, so the layout changes from one file to the next:

- Several sections per workbook (regular, salary, additional, retro, and so on)
- Header names that vary (`EMP#`, `EMP NO.`, `EMPLOYEE NUMBER`, ...)
- Week-ending dates written in free text (`WE 5/18`, `Effective 5/14`, ...)
- Totals that don't always match the line items
- The same row sometimes billed twice

Entering this by hand is slow and error-prone, and one wrong week-ending date or duplicate row means **incorrect billing**.

**Goal:** automate the extraction, catch data-quality problems **before** they reach the database, and keep a full audit trail of every import.

### Project at a glance

| Metric | Value |
|---|---|
| Invoice line items loaded | **156,700+** rows |
| Invoice workbooks processed | **800+** files |
| Unique employees | **5,500+** |
| Payroll hours tracked | **6M+** hours |
| History covered | Dec 2023 → present (weekly) |
| Logged import runs | 94 runs, ~158K rows inserted, 900+ duplicates caught |

## 2. Solution at a glance

| Step | What happens | Why it matters |
|---|---|---|
| **Extract** | Read `.xlsx` / `.xls` files and detect every invoice section automatically | Handles inconsistent layouts |
| **Transform** | Standardize headers, clean numbers, text and dates, and classify sections | One consistent data model |
| **Validate** | Reconcile totals, check week-ending dates, match invoice numbers, flag pay/bill differences | Bad data never gets in silently |
| **Review** | Excel preview report and an interactive terminal preview | A person approves before anything is written |
| **Load** | Bulk insert into PostgreSQL with duplicate protection | Idempotent, safe to re-run |
| **Audit** | Log every run, file and error in the database | Full traceability |

## 3. Workflow

```mermaid
flowchart TD
    A[📂 invoices/<br/>New Excel files] --> B[Parse filename<br/>customer · invoice # · period]
    B --> C[Detect sections & headers<br/>map column aliases]
    C --> D[Clean & standardize<br/>numbers · text · dates]
    D --> E{Validation}
    E -- Hard error --> F[❌ failed/<br/>+ import_errors table]
    E -- OK / warnings --> G[📊 Preview report<br/>Excel + terminal]
    G --> H{User review}
    H -- Reject --> I[Stop · nothing inserted]
    H -- Approve --> J[Label pay/bill differences<br/>Review duplicates]
    J --> K[(PostgreSQL<br/>invoice_entries)]
    K --> L[✅ processed/<br/>+ import_runs / import_files log]
```

### Daily routine

```bash
# 1. Drop new invoice files into invoices/

# 2. Preview only (nothing is written to invoice_entries)
python import_invoices.py --dry-run

# 3. Check the Excel report in reports/, then import
python import_invoices.py --commit
```

## 4. Data quality rules

| Rule | Type | Result |
|---|---|---|
| Invoice # in the filename ≠ invoice # in the Excel file | Hard error | File moved to `failed/` |
| Sum of parsed rows ≠ invoice total | Hard error | File fails, with a per-section breakdown for debugging |
| `PERIOD THRU` / explicit `WE` date is not a Sunday | Hard error | File fails |
| Date with no `WE` label (e.g. "Effective 5/14") | Warning | Moved to that week's Sunday and flagged |
| Section type | Auto-classified | `hourly` / `salary` / `additional` (orientation, retro hours, pay/bill difference) |
| Very low pay rate in an additional section | Warning | Flagged as a **pay-difference** candidate |
| Bill rate lower than pay rate | Warning | Flagged as a **bill-difference** candidate |
| Duplicate row (same 10-column business key) | Review | Skipped by default; can be force-imported with `force_import = true` |
| Unknown customer | Review | Fuzzy-matched against existing customers (`difflib`), or created |

## 5. SQL and database design

The data lands in **PostgreSQL** (hosted on Supabase). SQL handles storage and also enforces the data-integrity rules.

### 5.1 Data model

```mermaid
erDiagram
    customers ||--o{ import_files : "billed to"
    import_runs ||--o{ import_files : contains
    import_runs ||--o{ import_errors : logs
    import_files ||--o{ invoice_entries : contains

    import_runs {
        bigint id PK
        text status
        timestamptz started_at
        timestamptz finished_at
        int rows_inserted
        int rows_skipped
        numeric total_payroll
    }
    import_files {
        bigint id PK
        bigint import_run_id FK
        text customer
        text invoice_number
        text file_hash
        date week_ending
        numeric total_amount
    }
    invoice_entries {
        bigint id PK
        bigint import_file_id FK
        text employee_number
        date week_ending
        text section_type
        numeric pay_rate
        numeric total_hours
        numeric total_amount
        boolean force_import
    }
```

Full DDL: [`sql/schema.sql`](sql/schema.sql)

### 5.2 SQL techniques used in the pipeline

**Upsert (idempotent re-import):** re-importing the same invoice updates the existing log record instead of creating a duplicate.

```sql
INSERT INTO import_files (customer, invoice_number, file_hash, total_amount, ...)
VALUES (:customer, :invoice_number, :file_hash, :total_amount, ...)
ON CONFLICT (customer, invoice_number)
DO UPDATE SET
    file_hash    = EXCLUDED.file_hash,
    total_amount = EXCLUDED.total_amount
RETURNING id;
```

**Partial unique index (business-rule deduplication):** blocks duplicates in normal imports but still allows rows a user has explicitly approved.

```sql
CREATE UNIQUE INDEX invoice_unique_row
ON invoice_entries (import_file_id, employee_number, week_ending, area, position,
                    section_type, total_hours, total_amount, pay_rate, weekly_rate)
WHERE force_import = false;
```

**Constraints as data-quality guards:**

```sql
-- Same customer can't exist twice, even with different casing or spacing
CREATE UNIQUE INDEX customers_name_lower_unique ON customers (lower(trim(name)));

-- Only known adjustment categories are accepted
adjustment_type TEXT CHECK (adjustment_type IS NULL OR adjustment_type IN
    ('pay_difference', 'bill_difference', 'orientation', 'retro_hours', 'additional'))

-- The same file content can never be logged twice
file_hash TEXT UNIQUE

-- Deleting an invoice file removes its rows automatically
import_file_id BIGINT REFERENCES import_files (id) ON DELETE CASCADE
```

**Safe bulk insert:** `INSERT ... ON CONFLICT DO NOTHING` targets the partial index, and the number of inserted rows is checked against the expected count to catch race conditions.

**Parameterized queries:** every query uses bound parameters (`:param`, `= ANY(:list)`), so it is protected against SQL injection.

**Transactions:** each write runs inside `engine.begin()`, so it either commits fully or rolls back.

### 5.3 Analytical queries

Once the data is clean, it can be analysed directly. See [`sql/analysis_queries.sql`](sql/analysis_queries.sql) for queries using **CTEs, window functions (`LAG`, `RANK`, `SUM OVER`), `FILTER`, `date_trunc` and self-joins**, for example:

| # | Business question | SQL skills |
|---|---|---|
| 1 | Monthly billed amount by customer and its month-over-month growth | CTE, `date_trunc`, `LAG` |
| 2 | Weekly hours and overtime ratio per customer | Aggregation, `FILTER`, `NULLIF` |
| 3 | Top 10 employees by hours each month | `RANK() OVER (PARTITION BY ...)` |
| 4 | Average bill-rate markup by position | Derived metrics, `HAVING` |
| 5 | Cross-invoice duplicate audit | Self-join, `EXISTS` |
| 6 | Import pipeline health (success rate, rows skipped) | Conditional aggregation |
| 7 | Most frequent import errors | `regexp_replace`, `GROUP BY` on an expression |
| 8 | Running payroll total for the year | `SUM() OVER (ORDER BY ...)` |

Example: month-over-month billing growth per customer.

```sql
WITH monthly AS (
    SELECT f.customer,
           date_trunc('month', ie.week_ending)::date AS month,
           SUM(ie.total_amount)                      AS billed
    FROM invoice_entries ie
    JOIN import_files f ON f.id = ie.import_file_id
    GROUP BY 1, 2
)
SELECT customer,
       month,
       billed,
       LAG(billed) OVER (PARTITION BY customer ORDER BY month) AS prev_month,
       ROUND(100.0 * (billed - LAG(billed) OVER (PARTITION BY customer ORDER BY month))
             / NULLIF(LAG(billed) OVER (PARTITION BY customer ORDER BY month), 0), 1) AS mom_growth_pct
FROM monthly
ORDER BY customer, month;
```

### 5.4 Reporting layer

On top of the raw tables, a reporting layer feeds dashboards and HR/workforce analysis. It is built as **SQL views**, so it always reflects the latest import and never drifts from the source.

```mermaid
flowchart LR
    subgraph Source["Source (loaded by pipelines)"]
        IE[(invoice_entries<br/>156K rows)]
        IF[(import_files)]
        HR[("emp_GEO_info<br/>HR master")]
    end
    subgraph Clean["Clean / conformed"]
        GD[emp_geo_dedup<br/>1 row per employee]
    end
    subgraph Report["Reporting views"]
        RS[reporting_weekly_summary<br/>invoice × week × section]
        EN[employee_weekly_payroll_enriched_v<br/>invoice rows + HR attributes]
    end
    IE --> RS
    IF --> RS
    IE --> EN
    IF --> EN
    HR --> GD --> EN
```

| View | Grain | Used for |
|---|---|---|
| `reporting_weekly_summary` | customer × invoice × week × section × adjustment | Weekly billing and hours dashboards, invoice reconciliation |
| `emp_geo_dedup` | one row per employee | Conformed HR dimension (branch, location, demographics) |
| `employee_weekly_payroll_enriched_v` | one row per invoice line | Workforce analysis by branch, location, age group, and so on |

Full SQL: [`sql/reporting_layer.sql`](sql/reporting_layer.sql)

### 5.5 Case study: finding a 3× hours inflation with SQL

The first version of the reporting layer used **snapshot tables** (`CREATE TABLE AS`). Reconciling them against the source showed that something was wrong:

| Check | Legacy snapshot table | Source (`invoice_entries`) |
|---|---|---|
| Total hours (same period) | **15.6M** | **5.1M** |
| Rows with HR attributes | ~14% | n/a |

**How the problem was found:**

1. **Reconciliation:** total hours in the reporting table were about 3× the source.
2. **Duplicate-load detector:** `GROUP BY` the business key, then count copies per key. Almost every key appeared **3 times**, and the ID ranges showed three separate loads of the same data.
3. **Fan-out detector:** the HR master held **up to 4 rows per employee**, so the join multiplied rows further (keys with 4, 6 and 8 copies).

```sql
-- Fan-out detector: HR keys that are not unique
SELECT "BoldTalentID", COUNT(*) AS rows_per_employee
FROM "emp_GEO_info"
GROUP BY "BoldTalentID"
HAVING COUNT(*) > 1;
```

**The fix:**

- Replace the snapshot tables with **views** so they can't be loaded twice or go stale.
- Make the HR master 1-to-1 with `DISTINCT ON`, keeping the most complete and most active record:

```sql
SELECT DISTINCT ON (g."BoldTalentID") ...
FROM "emp_GEO_info" g
ORDER BY g."BoldTalentID",
         (g."DateofBirth" IS NULL),          -- prefer records with demographics
         total_hours_all_years DESC,         -- then the most active record
         g.id DESC;                          -- then the latest load
```

- Use a `LEFT JOIN` so no invoice row is ever lost.

**Result: every layer reconciles exactly.**

| Layer | Rows | Hours |
|---|---|---|
| `invoice_entries` (source) | 156,752 | 6,072,054.01 |
| `reporting_weekly_summary` | 156,752 | 6,072,054.01 |
| `employee_weekly_payroll_enriched_v` | 156,752 | 6,072,054.01 |

HR match rate went from **~14% to 99.8–100%** for every customer.

## 6. Project structure

```text
├── import_invoices.py   # Entry point: CLI, orchestrates the full pipeline
├── parsing.py           # Section/header detection, date and week-ending rules, total extraction
├── cleaning.py          # Number/text/shift cleaning, rounding
├── customers.py         # Customer lookup, fuzzy matching, creation (SQL)
├── db.py                # All database I/O: logging, dedup, bulk insert (SQL)
├── summaries.py         # Terminal previews and import summaries
├── preview_report.py    # Excel preview report (openpyxl, styled)
├── files.py             # File discovery, hashing (SHA), safe move
├── config.py            # .env settings, column alias map
├── sql/
│   ├── schema.sql           # Table and index definitions
│   ├── reporting_layer.sql  # Reporting views + data-quality checks
│   └── analysis_queries.sql # Analytical SQL examples
├── invoices/  processed/  failed/  reports/   # Runtime folders (git-ignored)
└── UPDATED_DOCUMENTATION.md                   # Full operating manual
```

## 7. Getting started

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a `.env` file (never commit it):

```env
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST:5432/postgres
PAGE_SIZE=25
```

Create the tables by running `sql/schema.sql`, and optionally `sql/reporting_layer.sql` for the reporting views, then:

```bash
python import_invoices.py --dry-run
```

## 8. Results and impact

- **156K+ invoice rows from 800+ workbooks** loaded through an automated, repeatable pipeline instead of manual data entry
- **900+ duplicate rows** blocked automatically, and **109 validation errors across 57 files** (invalid week-ending dates, invoice-number mismatches, total mismatches) caught before they reached the database
- **Zero silent imports:** every row is validated and approved before it is inserted
- **Duplicate billing protection** at both the application level and the database level
- **Full audit trail:** every run, file and error can be traced in SQL
- **Analysis-ready data** for payroll, overtime, billing-margin and customer trend reporting
- **Reporting layer audited and rebuilt:** found and fixed a 3× hours inflation caused by repeated loads and join fan-out; all layers now reconcile exactly, and HR match rate went from ~14% to ~99.9%

## 9. Tech stack

**Python** (pandas, openpyxl, xlrd) · **PostgreSQL / Supabase** · **SQLAlchemy 2.0** · **psycopg2** · **python-dotenv**

---

*For detailed rules and troubleshooting, see [UPDATED_DOCUMENTATION.md](UPDATED_DOCUMENTATION.md).*
