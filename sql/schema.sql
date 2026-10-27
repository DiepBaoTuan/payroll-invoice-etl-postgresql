-- =====================================================================
-- Payroll Invoice Importer - PostgreSQL schema (Supabase)
-- Mirrors the production tables used by the importer.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Customers: master list, case/whitespace-insensitive uniqueness
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS customers (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,                -- ON CONFLICT (name) DO NOTHING
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- "Acme Foods" and " acme foods " are treated as the same customer
CREATE UNIQUE INDEX IF NOT EXISTS customers_name_lower_unique
    ON customers (lower(trim(name)));

-- ---------------------------------------------------------------------
-- Import runs: one row per execution of import_invoices.py
-- status: running / success / completed_with_errors /
--         stopped_after_preview_report / stopped_before_import
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS import_runs (
    id               BIGSERIAL PRIMARY KEY,
    started_at       TIMESTAMPTZ DEFAULT now(),
    finished_at      TIMESTAMPTZ,
    status           TEXT,
    files_processed  INTEGER DEFAULT 0,
    rows_inserted    INTEGER DEFAULT 0,
    rows_skipped     INTEGER DEFAULT 0,
    total_payroll    NUMERIC DEFAULT 0,
    summary          TEXT
);

-- ---------------------------------------------------------------------
-- Import files: one row per invoice workbook
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS import_files (
    id              BIGSERIAL PRIMARY KEY,
    import_run_id   BIGINT REFERENCES import_runs (id),
    file_name       TEXT NOT NULL,
    file_hash       TEXT UNIQUE,                     -- same file content can't be logged twice
    rows_found      INTEGER DEFAULT 0,
    rows_inserted   INTEGER DEFAULT 0,
    status          TEXT,                            -- success / failed
    uploaded_at     TIMESTAMPTZ DEFAULT now(),
    invoice_number  TEXT,
    customer        TEXT,
    week_ending     DATE,
    total_hours     NUMERIC,
    total_amount    NUMERIC
);

-- Upsert target: one invoice number per customer
CREATE UNIQUE INDEX IF NOT EXISTS import_files_customer_invoice_unique
    ON import_files (customer, invoice_number);

-- ---------------------------------------------------------------------
-- Import errors: parsing / validation failures for audit
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS import_errors (
    id              BIGSERIAL PRIMARY KEY,
    import_run_id   BIGINT REFERENCES import_runs (id) ON DELETE CASCADE,
    file_name       TEXT,
    row_number      INTEGER,
    error_message   TEXT,
    raw_data        JSONB,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Invoice entries: the fact table, one row per billed employee line
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS invoice_entries (
    id                  BIGSERIAL PRIMARY KEY,
    import_file_id      BIGINT NOT NULL REFERENCES import_files (id) ON DELETE CASCADE,
    force_import        BOOLEAN DEFAULT false,
    employee_number     TEXT,
    last_name           TEXT,
    first_name          TEXT,
    area                TEXT,
    subarea             TEXT,
    shift               TEXT,
    plant               TEXT,
    position            TEXT,
    section_type        TEXT,                        -- hourly / salary / additional
    rate_type           TEXT,                        -- hourly / weekly
    adjustment_type     TEXT CHECK (
        adjustment_type IS NULL OR adjustment_type IN (
            'pay_difference', 'bill_difference', 'orientation', 'retro_hours', 'additional'
        )
    ),
    pay_rate            NUMERIC,
    weekly_rate         NUMERIC,
    total_hours         NUMERIC,
    regular_hours       NUMERIC,
    overtime_hours      NUMERIC,
    regular_bill_rate   NUMERIC,
    overtime_bill_rate  NUMERIC,
    regular_markup      NUMERIC,
    overtime_markup     NUMERIC,
    total_amount        NUMERIC,
    week_ending         DATE,
    imported_at         TIMESTAMPTZ DEFAULT now()
);

-- Business-key de-duplication for normal imports.
-- Rows approved by a user are inserted with force_import = true and bypass it.
CREATE UNIQUE INDEX IF NOT EXISTS invoice_unique_row
ON invoice_entries (
    import_file_id, employee_number, week_ending, area, position,
    section_type, total_hours, total_amount, pay_rate, weekly_rate
)
WHERE force_import = false;

-- Supporting indexes for joins and time-based analytics
CREATE INDEX IF NOT EXISTS invoice_entries_import_file_id_idx
    ON invoice_entries (import_file_id);
CREATE INDEX IF NOT EXISTS invoice_entries_week_ending_idx
    ON invoice_entries (week_ending);
