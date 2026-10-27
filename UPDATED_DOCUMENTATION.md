# Python Invoice Importer Documentation

## Version Display

The startup banner now includes both the date-based version and the minor revision:

```text
Invoice Importer v2026.05.26 v8
```



Version: `2026.05.26`

This importer parses payroll invoice Excel files, validates and previews the parsed data, and imports approved rows into a Postgres database, such as Supabase Postgres. The workflow is intentionally review-first: files are parsed and checked before any invoice rows are inserted.

## 1. What the importer does

The importer:

1. Looks for supported Excel files in the invoice folder.
2. Parses invoice sections from each workbook.
3. Confirms the invoice number in the filename matches the invoice number inside Excel.
4. Confirms or creates the customer record.
5. Cleans numeric/text/date fields.
6. Validates invoice totals.
7. Detects pay-difference and bill-difference candidates.
8. Detects invalid or questionable week-ending dates.
9. Creates a terminal preview and/or Excel preview report.
10. Requires user confirmation before importing rows.
11. Reviews same-invoice and cross-invoice duplicate rows before insertion.
12. Moves successfully processed files to `processed/` and failed files to `failed/`.
13. Logs runs, files, and errors to the database.

## 2. Folder structure

Recommended project layout:

```text
invoice_importer/
  cleaning.py
  config.py
  console_paging.py
  customers.py
  db.py
  files.py
  import_invoices.py
  parsing.py
  platform_utils.py
  preview_report.py
  requirements.txt
  summaries.py
  timing.py
  .env
  invoices/
  processed/
  failed/
  reports/
```

The default folders are created automatically when the app starts.

## 3. Supported file types

Supported Excel extensions:

```text
.xlsx
.xls
```

`.xlsx` files are read with `openpyxl`.

`.xls` files are read with `xlrd`.

Temporary Excel files such as `~$filename.xlsx` and hidden files are ignored.

## 4. Install dependencies

Create and activate a virtual environment.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Current dependency ranges:

```txt
pandas>=2.2,<3
openpyxl>=3.1,<4
xlrd>=2.0,<3
SQLAlchemy>=2.0,<3
psycopg2-binary>=2.9,<3
python-dotenv>=1.0,<2
```

For a fully reproducible workstation setup after testing, create a lock file:

```bash
pip freeze > requirements-lock.txt
```

## 5. Environment configuration

Create a `.env` file in the same folder as the Python files.

Example:

```env
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST:5432/postgres
PAGE_SIZE=25
INVOICE_DIR=invoices
PROCESSED_DIR=processed
FAILED_DIR=failed
REPORTS_DIR=reports
```

### Required setting

| Setting | Required | Description |
|---|---:|---|
| `DATABASE_URL` | Yes | SQLAlchemy-compatible Postgres connection string. |

### Optional settings

| Setting | Default | Description |
|---|---|---|
| `PAGE_SIZE` | `25` | Number of rows/items shown per console page. Must be an integer. |
| `INVOICE_DIR` | `invoices` | Folder where new invoice Excel files are placed. |
| `PROCESSED_DIR` | `processed` | Folder where successfully imported files are moved. |
| `FAILED_DIR` | `failed` | Folder where failed files are moved. |
| `REPORTS_DIR` | `reports` | Folder where preview reports are written. |

The database engine uses `pool_pre_ping=True` and `sslmode=require` for Supabase/Postgres compatibility.

## 6. File naming requirement

Invoice filenames must follow this pattern:

```text
Vendor - Customer Name - INVOICE 29373 APR 20 - APR 26 - 2026.xlsx
```

The parser extracts:

- Customer name
- Invoice number
- Invoice period start date
- Invoice period end date

The invoice number from the filename is compared to the invoice number inside Excel. If they do not match, the file fails and is not imported.

The invoice period end date in the filename is also treated as the filename WE date. It must be a Sunday. If the filename period end date is not a Sunday, the file fails before import.

## 7. Running the importer

### Safe preview / dry run

```bash
python import_invoices.py --dry-run
```

This parses files, creates an Excel preview report, logs the run, and stops before import. No invoice rows are inserted.

### Report only

```bash
python import_invoices.py --report-only
```

This creates the preview report and stops before import. This is functionally similar to dry run and is useful when the goal is review-only output.

### Interactive commit flow

```bash
python import_invoices.py --commit
```

This runs the full interactive review process and allows import after confirmation.

### No argument

```bash
python import_invoices.py
```

Currently this enters the same interactive preview/confirmation flow as the normal commit flow. For daily use, prefer `--dry-run` for review-only and `--commit` when you are ready to import.

## 8. Review workflow

The importer does not silently import rows. The normal workflow is:

1. Parse and clean files.
2. Fail any files with hard parsing errors.
3. Show preview options:

```text
R = create Excel preview report
C = continue with terminal preview/confirmation
N = stop without importing
```

4. Show invoice previews in the terminal.
5. Ask which invoices to import:

```text
A = import all invoices
N = import none
1,3 = import only selected invoice numbers above
```

6. For selected invoices, ask about pay-difference candidates.
7. Ask about bill-difference candidates.
8. Ask about same-invoice or same-file skipped duplicates.
9. Ask about possible cross-invoice duplicates.
10. Insert approved rows.
11. Move processed or failed files.
12. Print an import summary.

## 9. Week-ending date rules

Week-ending dates are strict because payroll week-ending errors can cause bad imports.

### Invoice-level period dates

The importer validates invoice-level period dates before using them as default WE dates.

The following dates must be Sundays:

- The Excel `PERIOD THRU` date
- The invoice period end date in the filename, such as `APR 26` in `APR 20 - APR 26 - 2026`

If either invoice-level period date is not a Sunday, the file errors out and is not imported.

Example filename error case:

```text
Vendor - Customer Name - INVOICE 29373 MAY 10 - MAY 16 - 2026.xlsx
```

`2026-05-16` is a Saturday, not a Sunday, so the importer raises an error.

### Explicit WE dates

If a date is preceded by an explicit week-ending phrase, the parsed date must be a Sunday.

Explicit phrases include:

```text
WE 5/18
W/E 5/18
Week ending 5/18
Weekending 5/18
```

If the parsed explicit WE date is not a Sunday, the file errors out and is not imported.

Example error case:

```text
WE 5/16/2026
```

`2026-05-16` is a Saturday, not a Sunday, so the importer raises an error.

### Implicit or effective dates

If a date appears without an explicit WE phrase, the importer treats it as likely an effective date and converts it to the Sunday of that week.

Example:

```text
Effective 5/14/2026
```

If `2026-05-14` is a Thursday, the importer uses Sunday `2026-05-17` as the WE date.

This is a warning, not an error. The warning is shown in:

- Terminal invoice preview
- Excel preview report summary
- Excel preview report row detail

## 10. Validation warnings

Some data issues are warnings instead of hard errors. These warnings are shown before import.

Examples include:

- Numeric values that cannot be parsed cleanly
- Implicit/effective dates converted to Sunday WE dates
- Pay-difference candidates
- Bill-difference candidates
- Possible cross-invoice duplicates

Warnings are kept in internal columns such as:

```text
_week_ending_warning
_validation_warning
```

These internal columns are dropped before database insert, so no schema change is needed for them.

## 11. Hard errors

A file fails and is moved to the failed folder when there is a hard error such as:

- Invalid filename format
- Missing invoice number in Excel
- Filename invoice number does not match Excel invoice number
- No invoice sections detected
- Invoice total cannot be found
- Parsed row total does not match invoice total
- Explicit WE date is not a Sunday
- Customer is not confirmed and user chooses to fail the file

Failed files are logged in `import_errors` when database logging is available.

## 12. Duplicate handling

The importer handles duplicates in two layers.

### Same-invoice / same-file duplicates

The primary duplicate key includes:

```text
import_file_id
employee_number
week_ending
area
position
section_type
total_hours
total_amount
pay_rate
weekly_rate
```

Duplicates within the same file/import scope are skipped first, then shown to the user. The user can force-insert skipped rows if they are legitimate.

### Cross-invoice duplicate review

The cross-invoice duplicate check uses the same logical key but excludes `import_file_id`.

That means the importer looks for prior invoice rows with the same:

```text
employee_number
week_ending
area
position
section_type
total_hours
total_amount
pay_rate
weekly_rate
```

If matches are found from a different invoice, the importer shows them as possible duplicates.

Options:

```text
A = import all possible cross-invoice duplicates and mark force_import true
N = skip all possible cross-invoice duplicates
1,3 = import only selected possible duplicates and mark force_import true
```

This protects against accidental duplicate billing while still allowing legitimate double-billed or repeated invoice rows.

## 13. Pay-difference and bill-difference review

### Pay-difference candidates

Additional-section rows with very low positive pay rates are flagged as possible pay-difference rows.

During import, the user can:

```text
A = label all candidates as pay_difference
N = label none
1,3 = label only selected candidate numbers
```

### Bill-difference candidates

Rows where bill rates appear lower than pay rates are flagged as possible bill-difference rows.

During import, the user can:

```text
A = label all candidates as bill_difference
N = label none
1,3 = label only selected candidate numbers
```

## 14. Preview report

The Excel preview report is created in the reports folder.

Filename pattern:

```text
invoice_preview_report_YYYYMMDD_HHMMSS.xlsx
```

The report includes:

- Summary sheet
- By Section sheet
- Pay Difference Rows sheet
- Rows sheet

The report highlights warnings and includes warning details for WE-date conversions and validation issues.

## 15. Database tables expected by the importer

The importer expects at least these tables:

```text
customers
import_runs
import_files
import_errors
invoice_entries
```

### customers

Used to confirm or create customer names.

Expected fields include:

```text
name
```

The importer expects `name` to support conflict handling:

```sql
ON CONFLICT (name) DO NOTHING
```

### import_runs

Used to log each run.

Expected fields include:

```text
id
status
started_at
finished_at
files_processed
rows_inserted
rows_skipped
total_payroll
summary
```

### import_files

Used to log each invoice file/import document.

Expected fields include:

```text
id
import_run_id
file_name
file_hash
rows_found
rows_inserted
status
invoice_number
customer
week_ending
total_hours
total_amount
```

The current code uses conflict handling on:

```text
customer
invoice_number
```

### import_errors

Used to log parsing/import errors.

Expected fields include:

```text
import_run_id
file_name
error_message
raw_data
```

### invoice_entries

Used for imported invoice rows.

Expected fields include:

```text
import_file_id
force_import
employee_number
last_name
first_name
area
subarea
shift
plant
position
section_type
rate_type
adjustment_type
pay_rate
weekly_rate
total_hours
regular_hours
overtime_hours
regular_bill_rate
overtime_bill_rate
regular_markup
overtime_markup
total_amount
week_ending
imported_at
```

Recommended partial unique index for normal imports:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS ux_invoice_entries_normal_duplicate
ON invoice_entries (
    import_file_id,
    employee_number,
    week_ending,
    area,
    position,
    section_type,
    total_hours,
    total_amount,
    pay_rate,
    weekly_rate
)
WHERE force_import = false;
```

The importer can intentionally insert duplicates with `force_import = true` when the user approves them.

## 16. File movement

After processing:

- Successfully imported files move to `processed/`.
- Failed files move to `failed/`.
- If a file with the same name already exists in the target folder, a timestamp is appended.

Example:

```text
invoice.xlsx
invoice_20260526_153012.xlsx
```

## 17. Troubleshooting

### `DATABASE_URL is missing from .env`

Create `.env` in the project folder and add a valid `DATABASE_URL`.

### `.xls` file fails to read

Confirm `xlrd` is installed:

```bash
pip install "xlrd>=2.0,<3"
```

### Invoice period / explicit WE date error

The Excel `PERIOD THRU` date, the filename invoice-period end date, and any date after `WE`, `W/E`, `Week ending`, or `Weekending` must be Sunday. Correct the workbook, filename, or source data, then rerun.

### Invoice total mismatch

The parsed rows do not equal the invoice total. Review:

- Missing sections
- Incorrect header detection
- Misread total amount column
- Additional/retro sections
- Hidden rows or unusual formatting

The error message includes a parsed total by section to help locate the issue.

### Customer not found

The importer shows close database matches. Choose a match, create a new customer, or fail the file.

### Duplicate rows detected

Review the displayed duplicate details. Use force import only when the duplicate is a legitimate billed row.

## 18. Daily operating checklist

1. Save invoice files into `invoices/`.
2. Run:

```bash
python import_invoices.py --dry-run
```

3. Open the Excel preview report in `reports/`.
4. Resolve any hard errors or suspicious warnings.
5. Run:

```bash
python import_invoices.py --commit
```

6. Review invoice selection, difference candidates, and duplicates.
7. Confirm only the invoices/rows that should import.
8. Check the final import summary.
9. Confirm processed files moved to `processed/`.

## 19. Safety notes

- The importer is designed to stop before import unless the user confirms.
- Hard errors block file import.
- Warning rows remain reviewable before import.
- Cross-invoice duplicate rows do not import silently.
- Forced duplicates are marked with `force_import = true`.
- Preview-only modes do not insert invoice rows.

### Employee section header and section-note detection

The importer treats `EMP##`, `EMP#`, `EMP #`, `EMP NO`, `EMP NO.`, `EMPLOYEE #`, and `EMPLOYEE NUMBER` as valid employee-section headers.

Additional/adjustment wording now takes priority over generic salary wording. This matters for notes such as:

```text
Approved Additional Payment for Salary Emp WE 02/01 & WE 02/08
```

Even though the note contains `Salary`, it is parsed as an `additional` section because it also contains `Additional`. That allows row-level WE values, such as `WE 02/01` and `WE 02/08`, to override the invoice-level `PERIOD THRU` date.

If a section note contains multiple explicit WE dates, the importer validates that each date is Sunday but does not apply the first date to every row. Rows with their own row-level WE note use that row-level date. Rows without a row-level WE note keep the invoice-level `PERIOD THRU` date and receive a warning for review.
## Excel Preview Report Layout Notes

On the Summary sheet, the context columns are placed at the far right, after `Data Validation Warning Notes`:

```text
Customer | File Name | Week Endings | Summary Type
```

The Summary sheet leaves zero-value review counters blank for easier scanning, including pay/bill difference counts, parsing seconds when zero, WE warning counts, and data-validation warning counts. Warning-note columns remain blank when there are no warning notes.


### Salary section date behavior

Salary sections remain `salary` when the note says `Salary` and does not also contain adjustment language such as `Additional`, `Retro`, `Orientation`, `Pay Diff`, `Rate Diff`, or `Difference`. If a salary section note contains a single valid date/WE date, that date is applied to the section rows. If a salary section note contains multiple WE dates, each data row is checked for its own row-level WE date; rows without row-level WE keep the invoice `PERIOD THRU` date and receive a warning for review.


## v7 section classification correction

Plain Salary sections with markup columns remain salary. Sections are classified as additional only when the note includes an additional/retro/orientation/pay-difference indicator, such as `Approved Additional Payment for Salary Emp`. This prevents normal salary sections that contain `REG Mark up` / `OT Mark up` columns from being mislabeled as additional.

### v8 filename and failed-summary updates

- Invoice filenames may include extra trailing text after the invoice period year, such as `(1)`, `copy`, or `- revised`, before the `.xlsx` extension.
- Failed-file summary blocks now include a separator line after each failed item for easier console review.


## v9 rounding update

The importer now rounds batch and invoice summary totals before writing them to Postgres:

- `import_runs.total_payroll`
- `import_files.total_hours`
- `import_files.total_amount`

The code rounds these values to 2 decimal places before insert/update. Existing database rows and SQL views may still need a one-time SQL cleanup or view-definition update if they were created before v9.
