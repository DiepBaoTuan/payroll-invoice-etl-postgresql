import argparse

import pandas as pd
from sqlalchemy import create_engine

from config import DATABASE_URL, PROCESSED_DIR, FAILED_DIR
from files import get_excel_files, file_hash, move_file_safely, read_excel_raw
from parsing import parse_invoice_sections
from parsing import extract_invoice_total
from parsing import parse_invoice_filename
from customers import get_confirmed_customer_for_file
from cleaning import clean_dataframe
from console_paging import print_paginated_items
from timing import track_input
from config import APP_VERSION, APP_MINOR_VERSION
from preview_report import create_preview_report

from db import (
    create_import_run,
    finish_import_run,
    log_import_file,
    update_import_file_status,
    log_error,
    insert_rows,
    confirm_insert_skipped_rows,
    force_insert_rows,
)

from summaries import (
    build_invoice_preview,
    confirm_invoices,
)

from timing import start_timer, elapsed_seconds, get_idle_seconds



def parse_args():
    parser = argparse.ArgumentParser(description="Parse and import invoice Excel files.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse files and create a preview report, then stop before import.",
    )
    mode.add_argument(
        "--report-only",
        action="store_true",
        help="Create the Excel preview report and stop before import.",
    )
    mode.add_argument(
        "--commit",
        action="store_true",
        help="Allow the normal interactive import confirmation flow.",
    )
    return parser.parse_args()


def render_pay_difference_candidate(item, display_number):
    df_index, row = item

    name = f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()
    name = name[:20]

    return (
        f"{display_number:<3} "
        f"Excel row {row.get('_excel_row_number')} | "
        f"Emp {row.get('employee_number')} | "
        f"{name} | "
        f"WE {row.get('week_ending')} | "
        f"Pay rate ${float(row.get('pay_rate') or 0):,.2f} | "
        f"Hours {float(row.get('total_hours') or 0):,.2f} | "
        f"Amount ${float(row.get('total_amount') or 0):,.2f}"
    )

def render_bill_difference_candidate(item, display_number):
    df_index, row = item

    name = f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()
    name = name[:20]

    pay_rate = float(row.get("pay_rate") or 0)
    regular_bill_rate = row.get("regular_bill_rate")
    overtime_bill_rate = row.get("overtime_bill_rate")
    regular_markup = row.get("regular_markup")
    overtime_markup = row.get("overtime_markup")

    return (
        f"{display_number:<3} "
        f"Excel row {row.get('_excel_row_number')} | "
        f"Emp {row.get('employee_number')} | "
        f"{name} | "
        f"WE {row.get('week_ending')} | "
        f"Pay rate ${pay_rate:,.2f} | "
        f"Reg BR {regular_bill_rate} | "
        f"OT BR {overtime_bill_rate} | "
        f"Reg MU {regular_markup} | "
        f"OT MU {overtime_markup} | "
        f"Hours {float(row.get('total_hours') or 0):,.2f} | "
        f"Amount ${float(row.get('total_amount') or 0):,.2f}"
    )
        
def confirm_pay_difference_candidates_for_invoice(invoice):
    df = invoice["df"]

    if "_pay_difference_candidate" not in df.columns:
        return

    if "adjustment_type" not in df.columns:
        df["adjustment_type"] = None

    candidate_mask = (
        df["_pay_difference_candidate"].eq(True)
        & ~df["adjustment_type"].eq("pay_difference")
    )

    candidates = df[candidate_mask]

    if candidates.empty:
        return

    file_path = invoice["file_path"]
    invoice_index = invoice["invoice_index"]

    candidate_items = list(candidates.iterrows())

    candidate_index_map = {
        display_index: df_index
        for display_index, (df_index, row) in enumerate(candidate_items, start=1)
    }

    print_paginated_items(
        title=(
            f"Pay-difference candidates for "
            f"[{invoice_index}] {file_path.name}"
        ),
        items=candidate_items,
        render_item=render_pay_difference_candidate,
        empty_message="No possible pay-difference rows.",
    )

    print()
    print("Pay-difference confirmation options:")
    print("  A = label all candidates as pay_difference")
    print("  N = label none")
    print("  1,3 = label only selected candidate numbers")

    while True:
        choice = track_input("Choose pay-difference rows to label: ").strip()

        if choice.lower() == "a":
            df.loc[candidate_mask, "adjustment_type"] = "pay_difference"
            return

        if choice.lower() == "n":
            return

        try:
            selected_numbers = {
                int(part.strip())
                for part in choice.split(",")
                if part.strip()
            }

            valid_numbers = set(candidate_index_map.keys())

            if selected_numbers and selected_numbers.issubset(valid_numbers):
                selected_df_indexes = [
                    candidate_index_map[number]
                    for number in sorted(selected_numbers)
                ]

                df.loc[selected_df_indexes, "adjustment_type"] = "pay_difference"
                return

        except ValueError:
            pass

        print("Invalid choice. Use A, N, or numbers like 1,3.")

def confirm_bill_difference_candidates_for_invoice(invoice):
    df = invoice["df"]

    if "_bill_difference_candidate" not in df.columns:
        return

    if "adjustment_type" not in df.columns:
        df["adjustment_type"] = None

    candidate_mask = (
        df["_bill_difference_candidate"].eq(True)
        & ~df["adjustment_type"].eq("bill_difference")
    )

    candidates = df[candidate_mask]

    if candidates.empty:
        return

    file_path = invoice["file_path"]
    invoice_index = invoice["invoice_index"]

    candidate_items = list(candidates.iterrows())

    candidate_index_map = {
        display_index: df_index
        for display_index, (df_index, row) in enumerate(candidate_items, start=1)
    }

    print_paginated_items(
        title=(
            f"Bill-difference candidates for "
            f"[{invoice_index}] {file_path.name}"
        ),
        items=candidate_items,
        render_item=render_bill_difference_candidate,
        empty_message="No bill-difference candidates.",
    )

    print()
    print("Bill-difference confirmation options:")
    print("  A = label all candidates as bill_difference")
    print("  N = label none")
    print("  1,3 = label only selected candidate numbers")

    while True:
        choice = track_input("Choose bill-difference rows to label: ").strip()

        if choice.lower() == "a":
            df.loc[candidate_mask, "adjustment_type"] = "bill_difference"
            return

        if choice.lower() == "n":
            return

        try:
            selected_numbers = {
                int(part.strip())
                for part in choice.split(",")
                if part.strip()
            }

            valid_numbers = set(candidate_index_map.keys())

            if selected_numbers and selected_numbers.issubset(valid_numbers):
                selected_df_indexes = [
                    candidate_index_map[number]
                    for number in sorted(selected_numbers)
                ]

                df.loc[selected_df_indexes, "adjustment_type"] = "bill_difference"
                return

        except ValueError:
            pass

        print("Invalid choice. Use A, N, or numbers like 1,3.")
        
                
def clean_error_message(error):
    """
    Return a readable error message without dumping SQL statements,
    parameter objects, or long trace details.

    Preserves intentional spacing for formatted section summaries.
    """

    error_text = str(error)

    if "[SQL:" in error_text:
        error_text = error_text.split("[SQL:")[0].strip()

    if "[parameters:" in error_text:
        error_text = error_text.split("[parameters:")[0].strip()

    if "(Background on this error" in error_text:
        error_text = error_text.split("(Background on this error")[0].strip()

    cleaned_lines = []

    for line in error_text.splitlines():
        # Preserve spacing for formatted summary rows.
        if "|" in line or line.strip().startswith("- "):
            cleaned_lines.append(line.rstrip())
        else:
            cleaned_lines.append(" ".join(line.split()))

    return "\n".join(cleaned_lines).strip()
    
        
def round_2(value):
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def build_total_debug_summary(df):
    section_summary = (
        df.groupby(
            ["section_type", "week_ending"],
            dropna=False,
            sort=False,
        )
        .agg(
            rows=("employee_number", "count"),
            total_amount=("total_amount", "sum"),
        )
        .reset_index()
    )

    lines = []

    for _, row in section_summary.iterrows():
        section_type = str(row["section_type"] or "unknown")
        week_ending = str(row["week_ending"] or "Missing")
        rows = int(row["rows"] or 0)
        amount = float(row["total_amount"] or 0)

        lines.append(
            f"  - {section_type:<12} | "
            f"WE {week_ending:<10} | "
            f"{rows:>4} rows | "
            f"${amount:>12,.2f}"
        )

    return "\n".join(lines)


def load_excel(file_path, engine):
    raw = read_excel_raw(file_path)

    df = parse_invoice_sections(file_path, raw=raw)
    df = clean_dataframe(df, file_path, engine)

    filename_data = parse_invoice_filename(file_path.name)

    df["_customer"] = get_confirmed_customer_for_file(engine, file_path)
    df["_invoice_number"] = filename_data["invoice_number"]
    df["_source_file"] = file_path.name


    parsed_total = round(
        float(df["total_amount"].fillna(0).sum()),
        2,
    )

    invoice_total = extract_invoice_total(
        raw,
        expected_total=parsed_total,
    )

    if invoice_total is None:
        section_debug = build_total_debug_summary(df)

        raise ValueError(
            "Could not find invoice total in Excel. "
            f"Parsed rows total = ${parsed_total:,.2f}. "
            "Invoice was not imported.\n"
            "Parsed totals by section:\n"
            f"{section_debug}"
        )

    invoice_total = round(float(invoice_total), 2)
    difference = round(parsed_total - invoice_total, 2)

    if difference != 0:
        section_debug = build_total_debug_summary(df)

        raise ValueError(
            "Invoice total mismatch. <<<<<< "
            f"\nParsed rows total = ${parsed_total:,.2f}; "
            f"Invoice total = ${invoice_total:,.2f}; "
            f"Difference = ${difference:,.2f}\n"
            "Parsed totals by section:\n"
            f"{section_debug}"
        )

    return df


def get_invoice_metadata(df):
    invoice_number = str(df["_invoice_number"].dropna().iloc[0])
    customer = str(df["_customer"].dropna().iloc[0])

    main_week_ending = (
        df.loc[df["section_type"] != "additional", "week_ending"]
        .dropna()
    )

    if len(main_week_ending) > 0:
        week_ending = main_week_ending.iloc[0]
    else:
        week_ending = df["week_ending"].dropna().iloc[0]

    total_hours = round_2(df["total_hours"].fillna(0).sum())
    total_amount = round_2(df["total_amount"].fillna(0).sum())

    return {
        "invoice_number": invoice_number,
        "customer": customer,
        "week_ending": week_ending,
        "total_hours": total_hours,
        "total_amount": total_amount,
    }


def calculate_actual_imported_amount(metadata, insert_result, forced_rows):
    remaining_skipped_amount = 0.0

    forced_row_ids = {
        skipped["dataframe_index"]
        for skipped in forced_rows
        if skipped.get("dataframe_index") is not None
    }

    for skipped in insert_result["skipped_rows"]:
        dataframe_index = skipped.get("dataframe_index")

        if dataframe_index in forced_row_ids:
            continue

        row = skipped.get("row", {})

        remaining_skipped_amount += round_2(
            row.get("total_amount") or 0
        )

    return round_2(metadata["total_amount"] - remaining_skipped_amount)


def print_processed_summary(
    file_path,
    inserted,
    skipped,
    rows_found,
    actual_file_seconds,
):
    print("\n" + "=" * 60)
    print(f"Processed: {file_path.name}")

    print(f"  Inserted : {inserted:,}")

    if skipped > 0:
        print(f"  Skipped  : {skipped:,}")

    print(f"  Parsed   : {rows_found:,}")
    print(f"  Time     : {actual_file_seconds:.2f} seconds")
    print("=" * 60)

def group_failed_file_summaries(items):
    grouped = {}

    for item in items:
        status = item.get("status", "unknown")

        grouped.setdefault(status, []).append(item)

    return grouped


def render_failed_file_item(item, display_number):
    invoice_index = item.get("invoice_index")
    invoice_number = item.get("invoice_number") or "Unknown"
    file_name = item.get("file_name")

    lines = [
        f"  [{invoice_index}] Invoice {invoice_number} - {file_name}"
    ]

    if item.get("error"):
        error_lines = str(item.get("error")).splitlines()
    
        if error_lines:
            lines.append(f"      Error: {error_lines[0]}")
    
            for error_line in error_lines[1:]:
                lines.append(f"             {error_line}")

    lines.append("      " + "-" * 50)

    return "\n".join(lines)


def print_failed_file_summaries_by_status(failed_file_summaries):
    if not failed_file_summaries:
        return

    grouped = group_failed_file_summaries(failed_file_summaries)

    print()
    print("Skipped/failed files by status")
    print("=" * 60)
    print(f"Total items: {len(failed_file_summaries)}")
    print(f"Total statuses: {len(grouped)}")

    for status, items in grouped.items():
        print()
        print(f"Status: {status}")
        print(f"Count : {len(items)}")

        print_paginated_items(
            title=f"Files - {status}",
            items=items,
            render_item=render_failed_file_item,
            empty_message=f"No files with status: {status}",
        )
        
def main():
    args = parse_args()

    print("\n************************************")
    print(f"Invoice Importer v{APP_VERSION} {APP_MINOR_VERSION}")
    print("************************************\n")
    
    overall_start_time = start_timer()

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing from .env")

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"sslmode": "require"},
    )
    run_id = create_import_run(engine)

    files_processed = 0
    files_failed = 0
    rows_inserted_total = 0
    rows_skipped_total = 0
    total_amount_imported = 0.0

    failed_file_summaries = []
    parsed_invoices = []

    excel_files = get_excel_files()

    if not excel_files:
        elapsed = elapsed_seconds(overall_start_time)
        idle = get_idle_seconds()
        processing = elapsed - idle

        summary = (
            "No invoice files found.\n"
            f"Processing time: {processing:.2f} seconds\n"
            f"Idle/input time: {idle:.2f} seconds\n"
            f"Total elapsed time: {elapsed:.2f} seconds\n\n"
        )

        finish_import_run(
            engine=engine,
            run_id=run_id,
            status="success",
            files_processed=0,
            rows_inserted=0,
            rows_skipped=0,
            total_amount=0.0,
            summary=summary,
        )

        print(summary)
        return

    # STEP 1: Parse/clean only. Do not insert yet.
    for invoice_index, file_path in enumerate(excel_files, start=1):
        file_start = start_timer()
        idle_start_total = get_idle_seconds()

        try:
            hash_value = file_hash(file_path)
            df = load_excel(file_path, engine)

            file_idle_seconds = get_idle_seconds() - idle_start_total
            processing_seconds = elapsed_seconds(file_start) - file_idle_seconds

            preview = build_invoice_preview(
                invoice_index=invoice_index,
                file_path=file_path,
                df=df,
                processing_seconds=processing_seconds,
                idle_seconds=file_idle_seconds,
            )

            parsed_invoices.append(
                {
                    "invoice_index": invoice_index,
                    "file_path": file_path,
                    "file_hash": hash_value,
                    "df": df,
                    "processing_seconds": processing_seconds,
                    "idle_seconds": file_idle_seconds,
                    "preview": preview,
                }
            )

        except Exception as e:
            files_failed += 1

            clean_error = clean_error_message(e)

            failed_file_summaries.append(
                {
                    "invoice_index": invoice_index,
                    "invoice_number": None,
                    "file_name": file_path.name,
                    "status": "failed during parsing",
                    "error": clean_error,
                }
            )

            try:
                log_error(engine, run_id, file_path.name, clean_error)
            except Exception as log_exception:
                print(f"Could not log error to database: {log_exception}")

            moved_path = move_file_safely(file_path, FAILED_DIR)

            if moved_path is None:
                print(f"Warning: could not move failed file because it was missing: {file_path.name}")

            print(f"Failed {file_path.name}: {clean_error}")

    if not parsed_invoices:
        elapsed = elapsed_seconds(overall_start_time)
        idle = get_idle_seconds()
        processing = elapsed - idle
    
        summary = (
            "No valid invoices found to import.\n"
            f"Files failed: {files_failed}\n"
            f"Processing time: {processing:.2f} seconds\n"
            f"Idle/input time: {idle:.2f} seconds\n"
            f"Total elapsed time: {elapsed:.2f} seconds"
        )
    
        if failed_file_summaries:
            summary += (
                "\n\nSkipped/failed files: "
                f"{len(failed_file_summaries)} item(s). "
                "Details shown in console output."
            )
    
        finish_import_run(
            engine=engine,
            run_id=run_id,
            status="completed_with_errors",
            files_processed=0,
            rows_inserted=0,
            rows_skipped=0,
            total_amount=0.0,
            summary=summary,
        )
    
        print(summary)
    
        if failed_file_summaries:
            print_failed_file_summaries_by_status(failed_file_summaries)
    
        return
        

    if args.dry_run or args.report_only:
        report_path = create_preview_report(parsed_invoices)
        elapsed = elapsed_seconds(overall_start_time)
        idle = get_idle_seconds()
        processing = elapsed - idle
        mode_name = "dry run" if args.dry_run else "report only"
        summary = (
            f"Stopped after {mode_name}; no rows were imported.\n"
            f"Preview report: {report_path}\n"
            f"Files parsed: {len(parsed_invoices)}\n"
            f"Files failed: {files_failed}\n"
            f"Processing time: {processing:.2f} seconds\n"
            f"Idle/input time: {idle:.2f} seconds\n"
            f"Total elapsed time: {elapsed:.2f} seconds"
        )

        finish_import_run(
            engine=engine,
            run_id=run_id,
            status="stopped_after_preview_report",
            files_processed=0,
            rows_inserted=0,
            rows_skipped=0,
            total_amount=0.0,
            summary=summary,
        )

        print(summary)

        if failed_file_summaries:
            print_failed_file_summaries_by_status(failed_file_summaries)

        return

    print("\nPreview review options:")
    print("  R = create Excel preview report")
    print("  C = continue with terminal preview/confirmation")
    print("  N = stop without importing")
    
    while True:
        review_choice = track_input("Choose preview option: ").strip().lower()
    
        if review_choice == "r":
            report_path = create_preview_report(parsed_invoices)
    
            print()
            print(f"Excel preview report created: {report_path}")
            print("Open the report and review it before continuing.")
            print()
            print("Next options:")
            print("  C = continue with terminal preview/confirmation")
            print("  N = stop without importing")
    
            continue_choice = track_input("Choose option: ").strip().lower()
    
            if continue_choice == "c":
                break
    
            if continue_choice == "n":
                finish_import_run(
                    engine=engine,
                    run_id=run_id,
                    status="stopped_after_preview_report",
                    files_processed=0,
                    rows_inserted=0,
                    rows_skipped=0,
                    total_amount=0.0,
                    summary=(
                        "Stopped after creating Excel preview report.\n"
                        f"Preview report: {report_path}"
                    ),
                )
    
                print("Stopped without importing.")
                return
    
            print("Invalid option. Returning to preview options.")
    
        elif review_choice == "c":
            break
    
        elif review_choice == "n":
            finish_import_run(
                engine=engine,
                run_id=run_id,
                status="stopped_before_import",
                files_processed=0,
                rows_inserted=0,
                rows_skipped=0,
                total_amount=0.0,
                summary="Stopped before import by user.",
            )
    
            print("Stopped without importing.")
            return
    
        else:
            print("Invalid option. Use R, C, or N.")
    
    seen_file_paths = set()
    deduped_parsed_invoices = []
    
    for invoice in parsed_invoices:
        file_key = str(invoice["file_path"].resolve())
    
        if file_key in seen_file_paths:
            print(f"Warning: duplicate parsed invoice entry skipped: {invoice['file_path'].name}")
            continue
    
        seen_file_paths.add(file_key)
        deduped_parsed_invoices.append(invoice)
    
    parsed_invoices = deduped_parsed_invoices
    
    # STEP 2: Confirm invoices to import.
    selected_invoice_indexes = confirm_invoices(parsed_invoices)

    # STEP 3: Insert selected invoices only.
    for invoice in parsed_invoices:
        invoice_index = invoice["invoice_index"]
        file_path = invoice["file_path"]
        df = invoice["df"]
        import_file_id = None
        metadata = {}

        if invoice_index not in selected_invoice_indexes:
            invoice_number = (
                df["_invoice_number"].dropna().iloc[0]
                if "_invoice_number" in df.columns and len(df["_invoice_number"].dropna())
                else "Missing"
            )
        
            failed_file_summaries.append(
                {
                    "invoice_index": invoice_index,
                    "invoice_number": invoice_number,
                    "file_name": file_path.name,
                    "status": "skipped by user",
                    "error": None,
                }
            )
            continue
            
        confirm_pay_difference_candidates_for_invoice(invoice)
        confirm_bill_difference_candidates_for_invoice(invoice)

        try:
            metadata = get_invoice_metadata(df)
            rows_found = len(df)

            import_start = start_timer()

            import_file_id = log_import_file(
                engine=engine,
                run_id=run_id,
                file_path=file_path,
                file_hash_value=invoice["file_hash"],
                rows_found=rows_found,
                rows_inserted=0,
                status="running",
                invoice_number=metadata["invoice_number"],
                customer=metadata["customer"],
                week_ending=metadata["week_ending"],
                total_hours=metadata["total_hours"],
                total_amount=metadata["total_amount"],
            )

            insert_result = insert_rows(engine, df, import_file_id)

            inserted = int(insert_result["inserted"])
            skipped = int(insert_result["skipped"])

            forced_rows = confirm_insert_skipped_rows(
                insert_result["skipped_rows"]
            )

            forced_inserted = int(
                force_insert_rows(
                    engine,
                    forced_rows,
                    import_file_id,
                )
            )

            inserted += forced_inserted
            skipped = max(0, skipped - forced_inserted)

            log_import_file(
                engine=engine,
                run_id=run_id,
                file_path=file_path,
                file_hash_value=invoice["file_hash"],
                rows_found=rows_found,
                rows_inserted=inserted,
                status="success",
                invoice_number=metadata["invoice_number"],
                customer=metadata["customer"],
                week_ending=metadata["week_ending"],
                total_hours=metadata["total_hours"],
                total_amount=metadata["total_amount"],
            )

            import_seconds = elapsed_seconds(import_start)
            actual_file_seconds = invoice["processing_seconds"] + import_seconds

            files_processed += 1
            rows_inserted_total += inserted
            rows_skipped_total += skipped

            actual_imported_amount = calculate_actual_imported_amount(
                metadata=metadata,
                insert_result=insert_result,
                forced_rows=forced_rows,
            )

            total_amount_imported = round_2(total_amount_imported + actual_imported_amount)

            moved_path = move_file_safely(file_path, PROCESSED_DIR)

            if moved_path is None:
                print(f"Warning: could not move processed file because it was missing: {file_path.name}")

            print_processed_summary(
                file_path=file_path,
                inserted=inserted,
                skipped=skipped,
                rows_found=rows_found,
                actual_file_seconds=actual_file_seconds,
            )

        except Exception as e:
            files_failed += 1
            clean_error = clean_error_message(e)
            
            try:
                if import_file_id:
                    update_import_file_status(
                        engine,
                        import_file_id,
                        "failed",
                    )                
            except Exception as status_exception:
                print(f"Could not update import file status: {status_exception}")

            failed_file_summaries.append(
                {
                    "invoice_index": invoice_index,
                    "invoice_number": metadata.get("invoice_number") if "metadata" in locals() else None,
                    "file_name": file_path.name,
                    "status": "failed during import",
                    "error": clean_error,
                }
            )

            try:
                log_error(engine, run_id, file_path.name, clean_error)
            except Exception as log_exception:
                print(f"Could not log error to database: {log_exception}")

            moved_path = move_file_safely(file_path, FAILED_DIR)

            if moved_path is None:
                print(f"Warning: could not move failed parsing file because it was missing: {file_path.name}")

            print(f"Failed import for {file_path.name}: {clean_error}")

    status = "success" if files_failed == 0 else "completed_with_errors"

    elapsed = elapsed_seconds(overall_start_time)
    idle = get_idle_seconds()
    processing = elapsed - idle

    summary_lines = [
        "\n\n======================",
        "    IMPORT SUMMARY",
        "----------------------",
        "",
        f"Files processed: {files_processed}",
    ]

    if files_failed > 0:
        summary_lines.append(
            f">>>> Files failed: {files_failed} <<<<"
        )

    summary_lines.append(
        f"Rows inserted: {rows_inserted_total}"
    )

    if rows_skipped_total > 0:
        summary_lines.append(
            f">>>> Rows skipped: {rows_skipped_total} <<<<"
        )

    summary_lines.extend(
        [
            "",
            f"Total amount imported: ${total_amount_imported:,.2f}",
            "",
            f"Processing time: {processing:.2f} seconds",
        ]
    )

    if idle > 0:
        summary_lines.append(
            f"Idle/input time: {idle:.2f} seconds"
        )

    summary_lines.append(
        f"Total elapsed time: {elapsed:.2f} seconds"
    )

    summary = "\n".join(summary_lines)

    if failed_file_summaries:
        summary += (
            "\n\nSkipped/failed files: "
            f"{len(failed_file_summaries)} item(s). "
            "Details shown below."
        )

    finish_import_run(
        engine=engine,
        run_id=run_id,
        status=status,
        files_processed=files_processed,
        rows_inserted=rows_inserted_total,
        rows_skipped=rows_skipped_total,
        total_amount=total_amount_imported,
        summary=summary,
    )

    print(summary)
    
    if failed_file_summaries:
        print_failed_file_summaries_by_status(failed_file_summaries)

if __name__ == "__main__":
    main()