import pandas as pd

from sqlalchemy import MetaData, Table, text
from sqlalchemy.dialects.postgresql import insert

from timing import track_input
from console_paging import print_paginated_items


DUPLICATE_KEY_COLUMNS = [
    "import_file_id",
    "employee_number",
    "week_ending",
    "area",
    "position",
    "section_type",
    "total_hours",
    "total_amount",
    "pay_rate",
    "weekly_rate",
]

NUMERIC_DUPLICATE_COLUMNS = {
    "total_hours",
    "total_amount",
    "pay_rate",
    "weekly_rate",
}


def round_2_or_zero(value):
    if value is None:
        return 0.0

    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def create_import_run(engine):
    with engine.begin() as conn:
        result = conn.execute(
            text("""
                insert into import_runs (status, started_at)
                values ('running', now())
                returning id
            """)
        )

        return result.scalar()


def finish_import_run(
    engine,
    run_id,
    status,
    files_processed,
    rows_inserted,
    rows_skipped,
    total_amount,
    summary,
):
    with engine.begin() as conn:
        conn.execute(
            text("""
                update import_runs
                set
                    status = :status,
                    finished_at = now(),
                    files_processed = :files_processed,
                    rows_inserted = :rows_inserted,
                    rows_skipped = :rows_skipped,
                    total_payroll = :total_amount,
                    summary = :summary
                where id = :run_id
            """),
            {
                "run_id": int(run_id),
                "status": status,
                "files_processed": int(files_processed),
                "rows_inserted": int(rows_inserted),
                "rows_skipped": int(rows_skipped),
                "total_amount": round_2_or_zero(total_amount),
                "summary": summary,
            },
        )


def log_import_file(
    engine,
    run_id,
    file_path,
    file_hash_value,
    rows_found,
    rows_inserted,
    status,
    invoice_number,
    customer,
    week_ending,
    total_hours,
    total_amount,
):
    with engine.begin() as conn:
        result = conn.execute(
            text("""
                insert into import_files (
                    import_run_id,
                    file_name,
                    file_hash,
                    rows_found,
                    rows_inserted,
                    status,
                    invoice_number,
                    customer,
                    week_ending,
                    total_hours,
                    total_amount
                )
                values (
                    :import_run_id,
                    :file_name,
                    :file_hash,
                    :rows_found,
                    :rows_inserted,
                    :status,
                    :invoice_number,
                    :customer,
                    :week_ending,
                    :total_hours,
                    :total_amount
                )
                on conflict (customer, invoice_number)
                do update set
                    import_run_id = excluded.import_run_id,
                    file_name = excluded.file_name,
                    file_hash = excluded.file_hash,
                    rows_found = excluded.rows_found,
                    rows_inserted = excluded.rows_inserted,
                    status = excluded.status,
                    week_ending = excluded.week_ending,
                    total_hours = excluded.total_hours,
                    total_amount = excluded.total_amount
                returning id
            """),
            {
                "import_run_id": int(run_id),
                "file_name": file_path.name,
                "file_hash": file_hash_value,
                "rows_found": int(rows_found),
                "rows_inserted": int(rows_inserted),
                "status": status,
                "invoice_number": invoice_number,
                "customer": customer,
                "week_ending": week_ending,
                "total_hours": round_2_or_zero(total_hours),
                "total_amount": round_2_or_zero(total_amount),
            },
        )

        return result.scalar()


def update_import_file_status(engine, import_file_id, status):
    if not import_file_id:
        return

    with engine.begin() as conn:
        conn.execute(
            text("""
                update import_files
                set status = :status
                where id = :id
            """),
            {
                "id": int(import_file_id),
                "status": status,
            },
        )


def log_error(engine, run_id, file_name, error_message):
    with engine.begin() as conn:
        conn.execute(
            text("""
                insert into import_errors (
                    import_run_id,
                    file_name,
                    error_message,
                    raw_data
                )
                values (
                    :import_run_id,
                    :file_name,
                    :error_message,
                    '{}'::jsonb
                )
            """),
            {
                "import_run_id": int(run_id),
                "file_name": file_name,
                "error_message": str(error_message),
            },
        )


def normalize_key_value(column, value):
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass

    if hasattr(value, "date") and not isinstance(value, str):
        try:
            return value.date()
        except Exception:
            return value

    if column in NUMERIC_DUPLICATE_COLUMNS:
        try:
            return round(float(value), 2)
        except Exception:
            return value

    if isinstance(value, str):
        return value.strip()

    return value


def make_duplicate_key(row):
    return tuple(
        normalize_key_value(column, row.get(column))
        for column in DUPLICATE_KEY_COLUMNS
    )


def prepare_df_for_insert(df, import_file_id: int, force_import=False):
    prepared = df.copy()

    prepared["import_file_id"] = int(import_file_id)
    prepared["force_import"] = bool(force_import)

    prepared = prepared.astype(object).where(pd.notnull(prepared), None)

    return prepared


def fetch_existing_possible_duplicates(engine, df, import_file_id):
    employee_numbers = [
        value
        for value in df["employee_number"].dropna().unique().tolist()
    ]

    week_endings = [
        value
        for value in df["week_ending"].dropna().unique().tolist()
    ]

    if not employee_numbers or not week_endings:
        return []

    with engine.begin() as conn:
        rows = conn.execute(
            text("""
                select
                    ie.id,
                    ie.import_file_id,
                    ie.employee_number,
                    ie.week_ending,
                    ie.area,
                    ie.position,
                    ie.section_type,
                    ie.total_hours,
                    ie.total_amount,
                    ie.pay_rate,
                    ie.weekly_rate,
                    ie.force_import,
                    ie.imported_at,
                    f.invoice_number,
                    f.file_name as source_file
                from invoice_entries ie
                join import_files f
                    on f.id = ie.import_file_id
                where ie.import_file_id = :import_file_id
                  and ie.employee_number = any(:employee_numbers)
                  and ie.week_ending = any(:week_endings)
            """),
            {
                "import_file_id": int(import_file_id),
                "employee_numbers": employee_numbers,
                "week_endings": week_endings,
            },
        ).mappings().all()

    return rows

def build_existing_duplicate_map(existing_rows):
    existing_map = {}

    for row in existing_rows:
        key = make_duplicate_key(row)

        existing_map.setdefault(key, []).append(
            {
                "id": row.get("id"),
                "invoice_number": row.get("invoice_number"),
                "source_file": row.get("source_file"),
                "imported_at": row.get("imported_at"),
                "force_import": row.get("force_import"),
            }
        )

    return existing_map


def split_duplicate_rows(df, existing_map):
    duplicate_indexes = set()
    skipped_rows = []
    seen_current_file = {}

    for idx, row in df.iterrows():
        row_dict = row.to_dict()
        key = make_duplicate_key(row_dict)

        if key in existing_map:
            duplicate_indexes.add(idx)

            skipped_rows.append(
                {
                    "dataframe_index": idx,
                    "excel_row_number": row_dict.get("_excel_row_number"),
                    "reason": "Duplicate row already exists in invoice_entries",
                    "existing_records": existing_map[key],
                    "duplicate_source": "database",
                    "row": row_dict,
                }
            )

            continue

        if key in seen_current_file:
            duplicate_indexes.add(idx)

            first_row = seen_current_file[key]

            skipped_rows.append(
                {
                    "dataframe_index": idx,
                    "excel_row_number": row_dict.get("_excel_row_number"),
                    "reason": "Duplicate row within the current Excel invoice",
                    "existing_records": [],
                    "duplicate_source": "current_file",
                    "first_excel_row_number": first_row.get("_excel_row_number"),
                    "first_row": first_row,
                    "row": row_dict,
                }
            )

            continue

        seen_current_file[key] = row_dict

    clean_df = df.drop(index=list(duplicate_indexes))

    return clean_df, skipped_rows


def bulk_insert_df(engine, df, import_file_id: int, force_import=False):
    if df.empty:
        return 0

    metadata = MetaData()
    table = Table("invoice_entries", metadata, autoload_with=engine)

    prepared = prepare_df_for_insert(
        df=df,
        import_file_id=import_file_id,
        force_import=force_import,
    )

    drop_columns = [
        "_excel_row_number",
        "_customer",
        "_invoice_number",
        "_source_file",
        "_pay_difference_candidate",
        "_bill_difference_candidate",
    ]

    for col in drop_columns:
        if col in prepared.columns:
            prepared = prepared.drop(columns=[col])
            
    records = prepared.to_dict(orient="records")

    if not records:
        return 0

    stmt = insert(table).values(records)

    if not force_import:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=DUPLICATE_KEY_COLUMNS,
            index_where=text("force_import = false"),
        )

    with engine.begin() as conn:
        result = conn.execute(stmt)

    return result.rowcount or 0


def insert_rows(engine, df, import_file_id: int):
    df = df.copy()

    df["import_file_id"] = int(import_file_id)

    existing_rows = fetch_existing_possible_duplicates(
        engine,
        df,
        import_file_id,
    )

    existing_map = build_existing_duplicate_map(existing_rows)

    clean_df, skipped_rows = split_duplicate_rows(df, existing_map)

    inserted_count = bulk_insert_df(
        engine=engine,
        df=clean_df,
        import_file_id=import_file_id,
        force_import=False,
    )

    expected_insert_count = len(clean_df)

    if inserted_count != expected_insert_count:
        skipped_rows.append(
            {
                "dataframe_index": None,
                "excel_row_number": None,
                "reason": (
                    "Database skipped one or more rows during bulk insert. "
                    "This usually means a race-condition duplicate or an "
                    "index/key mismatch."
                ),
                "existing_records": [],
                "duplicate_source": "bulk_insert_conflict",
                "row": {},
            }
        )

    return {
        "inserted": inserted_count,
        "skipped": len(skipped_rows),
        "skipped_rows": skipped_rows,
    }


def format_imported_date(value):
    if not value:
        return None

    return str(value).split(" ")[0]


def render_skipped_row(skipped, display_number):
    row = skipped.get("row", {})
    lines = []

    lines.append(
        f"[{display_number}] Excel row {skipped.get('excel_row_number')} - "
        f"{skipped.get('reason')}"
    )

    if row:
        lines.append(
            f"    Emp: {row.get('employee_number')} | "
            f"Name: {row.get('first_name')} {row.get('last_name')} | "
            f"WE: {row.get('week_ending')} | "
            f"Hours: {row.get('total_hours')} | "
            f"Amount: ${row.get('total_amount')}"
        )

    duplicate_source = skipped.get("duplicate_source")

    if duplicate_source == "database":
        existing_records = skipped.get("existing_records", [])

        lines.append(f"    Existing DB matches: {len(existing_records)}")

        for existing in existing_records[:5]:
            imported_date = format_imported_date(existing.get("imported_at"))

            force_note = ""
            if existing.get("force_import"):
                force_note = " | force_import: true"

            lines.append(
                f"      Invoice: {existing.get('invoice_number')} | "
                f"Imported: {imported_date}{force_note}"
            )

            lines.append(
                f"        File: {existing.get('source_file')}"
            )

        if len(existing_records) > 5:
            lines.append(
                f"      ... {len(existing_records) - 5} more existing DB matches"
            )

    elif duplicate_source == "current_file":
        lines.append(
            f"    Duplicate of earlier row in this same invoice: "
            f"Excel row {skipped.get('first_excel_row_number')}"
        )

    elif duplicate_source == "bulk_insert_conflict":
        lines.append(
            "    No exact row detail available because the conflict happened "
            "inside the database bulk insert."
        )

    return "\n".join(lines)


def confirm_insert_skipped_rows(skipped_rows):
    if not skipped_rows:
        return []

    print_paginated_items(
        title="Skipped rows detected",
        items=skipped_rows,
        render_item=render_skipped_row,
        empty_message="No skipped rows detected.",
    )

    print("\nOptions:")
    print("  A = insert all skipped rows anyway")
    print("  N = insert none")
    print("  1,3 = insert specific skipped rows")

    while True:
        choice = track_input("Choose skipped rows to force insert: ").strip()

        if choice.lower() == "a":
            return [
                skipped
                for skipped in skipped_rows
                if skipped.get("row")
            ]

        if choice.lower() == "n":
            return []

        try:
            selected_indexes = {
                int(part.strip())
                for part in choice.split(",")
                if part.strip()
            }

            valid_indexes = set(range(1, len(skipped_rows) + 1))

            if selected_indexes and selected_indexes.issubset(valid_indexes):
                return [
                    skipped_rows[i - 1]
                    for i in sorted(selected_indexes)
                    if skipped_rows[i - 1].get("row")
                ]

        except ValueError:
            pass

        print("Invalid choice. Use A, N, or row numbers like 1,3.")


def force_insert_rows(engine, skipped_rows, import_file_id: int):
    if not skipped_rows:
        return 0

    forced_records = []

    for skipped in skipped_rows:
        row = dict(skipped["row"])

        if not row:
            continue

        forced_records.append(row)

    if not forced_records:
        return 0

    forced_df = pd.DataFrame(forced_records)

    return bulk_insert_df(
        engine=engine,
        df=forced_df,
        import_file_id=import_file_id,
        force_import=True,
    )