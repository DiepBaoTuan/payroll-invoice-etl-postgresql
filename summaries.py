import pandas as pd

from timing import track_input
from console_paging import print_paginated_items

def build_section_summary(df):
    return (
        df.groupby(
            ["section_type", "week_ending"],
            dropna=False,
            sort=False,
        )
        .agg(
            rows=("employee_number", "count"),
            total_hours=("total_hours", "sum"),
            total_amount=("total_amount", "sum"),
        )
        .reset_index()
    )


def append_section_summary(lines, section_summary, include_total_row=False):
    lines.append("      Section       WE          Rows      Hours          Total")
    lines.append("      ------------  ----------  ------  ----------  ------------")

    total_rows = 0
    total_hours = 0.0
    total_amount = 0.0

    for _, row in section_summary.iterrows():
        section_type = row["section_type"] if row["section_type"] else "unknown"

        week_ending = (
            str(row["week_ending"])
            if not pd.isna(row["week_ending"])
            else "Missing"
        )

        rows = int(row["rows"])

        hours = (
            float(row["total_hours"])
            if not pd.isna(row["total_hours"])
            else 0.0
        )

        amount = (
            float(row["total_amount"])
            if not pd.isna(row["total_amount"])
            else 0.0
        )

        total_rows += rows
        total_hours += hours
        total_amount += amount

        lines.append(
            f"      {section_type:<12}  {week_ending:<10}  "
            f"{rows:>6}  {hours:>10,.2f}  ${amount:>11,.2f}"
        )

    if include_total_row:
        lines.append("      ------------  ----------  ------  ----------  ------------")

        lines.append(
            f"      {'TOTAL':<12}  {'':<10}  "
            f"{total_rows:>6}  {total_hours:>10,.2f}  ${total_amount:>11,.2f}"
        )

def get_bill_difference_rows(df):
    if "adjustment_type" not in df.columns:
        confirmed = df.iloc[0:0]
    else:
        confirmed = df[df["adjustment_type"].eq("bill_difference")]

    if "_bill_difference_candidate" not in df.columns:
        candidates = df.iloc[0:0]
    else:
        candidates = df[
            df["_bill_difference_candidate"].eq(True)
            & ~df["adjustment_type"].eq("bill_difference")
        ]

    return confirmed, candidates
    
def get_pay_difference_rows(df):
    if "adjustment_type" not in df.columns:
        confirmed = df.iloc[0:0]
    else:
        confirmed = df[df["adjustment_type"].eq("pay_difference")]

    if "_pay_difference_candidate" not in df.columns:
        candidates = df.iloc[0:0]
    else:
        candidates = df[
            df["_pay_difference_candidate"].eq(True)
            & ~df["adjustment_type"].eq("pay_difference")
        ]

    return confirmed, candidates

def get_bill_difference_rows(df):
    if "adjustment_type" not in df.columns:
        confirmed = df.iloc[0:0]
    else:
        confirmed = df[df["adjustment_type"].eq("bill_difference")]

    if "_bill_difference_candidate" not in df.columns:
        candidates = df.iloc[0:0]
    else:
        candidates = df[
            df["_bill_difference_candidate"].eq(True)
            & ~df["adjustment_type"].eq("bill_difference")
        ]

    return confirmed, candidates
    
def build_pay_difference_summary(df):
    confirmed, candidates = get_pay_difference_rows(df)
    bill_confirmed, bill_candidates = get_bill_difference_rows(df)

    if (
        confirmed.empty
        and candidates.empty
        and bill_confirmed.empty
        and bill_candidates.empty
    ):
        return []

    lines = [
        "",
        (
            f"    Pay difference : "
            f"{len(confirmed)} confirmed / {len(candidates)} candidates"
        ),
        (
            f"    Bill difference: "
            f"{len(bill_confirmed)} confirmed / {len(bill_candidates)} candidates"
        ),
    ]

    if not confirmed.empty:
        lines.extend(
            [
                "",
                "    Confirmed pay-difference rows:",
                "      #   Excel Row  Emp        Name                  WE          Pay Rate  Hours     Amount",
                "      --  ---------  ---------  --------------------  ----------  --------  --------  ----------",
            ]
        )

        for display_index, (_, row) in enumerate(confirmed.iterrows(), start=1):
            name = f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()
            name = name[:20]

            lines.append(
                f"      {display_index:<2}  "
                f"{str(row.get('_excel_row_number') or ''):<9}  "
                f"{str(row.get('employee_number') or ''):<9}  "
                f"{name:<20}  "
                f"{str(row.get('week_ending') or ''):<10}  "
                f"{float(row.get('pay_rate') or 0):>8.2f}  "
                f"{float(row.get('total_hours') or 0):>8.2f}  "
                f"${float(row.get('total_amount') or 0):>9,.2f}"
            )

    if not candidates.empty:
        lines.extend(
            [
                "",
                "    Possible pay-difference rows detected:",
                "      #   Excel Row  Emp        Name                  WE          Pay Rate  Hours     Amount",
                "      --  ---------  ---------  --------------------  ----------  --------  --------  ----------",
            ]
        )

        for display_index, (_, row) in enumerate(candidates.iterrows(), start=1):
            name = f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()
            name = name[:20]

            lines.append(
                f"      {display_index:<2}  "
                f"{str(row.get('_excel_row_number') or ''):<9}  "
                f"{str(row.get('employee_number') or ''):<9}  "
                f"{name:<20}  "
                f"{str(row.get('week_ending') or ''):<10}  "
                f"{float(row.get('pay_rate') or 0):>8.2f}  "
                f"{float(row.get('total_hours') or 0):>8.2f}  "
                f"${float(row.get('total_amount') or 0):>9,.2f}"
            )

        lines.append("")
        lines.append(
            f"    Candidate count: {len(candidates)}. "
            "You will be asked to confirm these before import."
        )

    return lines
    
def build_pay_difference_candidate_summary(df):
    if "_pay_difference_candidate" not in df.columns:
        return []

    candidates = df[
        df["_pay_difference_candidate"].eq(True)
        & ~df["adjustment_type"].eq("pay_difference")
    ]

    if candidates.empty:
        return []

    lines = [
        "",
        "    Possible pay-difference rows detected:",
        "      #   Excel Row  Emp        Name                  WE          Pay Rate  Hours     Amount",
        "      --  ---------  ---------  --------------------  ----------  --------  --------  ----------",
    ]

    for display_index, (_, row) in enumerate(candidates.iterrows(), start=1):
        name = f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()
        name = name[:20]

        lines.append(
            f"      {display_index:<2}  "
            f"{str(row.get('_excel_row_number') or ''):<9}  "
            f"{str(row.get('employee_number') or ''):<9}  "
            f"{name:<20}  "
            f"{str(row.get('week_ending') or ''):<10}  "
            f"{float(row.get('pay_rate') or 0):>8.2f}  "
            f"{float(row.get('total_hours') or 0):>8.2f}  "
            f"${float(row.get('total_amount') or 0):>9,.2f}"
        )

    lines.append("")
    lines.append(
        f"    Candidate count: {len(candidates)}. "
        "You will be asked to confirm these before import."
    )

    return lines

def build_invoice_preview(
    invoice_index,
    file_path,
    df,
    processing_seconds,
    idle_seconds,
):
    customer = (
        df["_customer"].dropna().iloc[0]
        if "_customer" in df.columns and len(df["_customer"].dropna())
        else "Missing"
    )
    
    invoice_number = (
        df["_invoice_number"].dropna().iloc[0]
        if "_invoice_number" in df.columns and len(df["_invoice_number"].dropna())
        else "Missing"
    )

    week_endings = sorted([
        str(x)
        for x in df["week_ending"].dropna().unique()
    ],reverse=True,)

    section_summary = build_section_summary(df)

    lines = [
        f"[{invoice_index}] {file_path.name}",
        f"    Customer: {customer}",
        f"    Invoice : {invoice_number}",
        f"    WE      : {', '.join(week_endings) if week_endings else 'Missing'}",
        "",
    ]

    append_section_summary(
        lines,
        section_summary,
        include_total_row=True,
    )

    pay_difference_lines = build_pay_difference_summary(df)

    if pay_difference_lines:
        lines.extend(pay_difference_lines)
    
    lines.extend([
        "",
        (
            f"    Processing time: {processing_seconds:.2f} seconds"
            f" | Rows parsed: {len(df)}"
        ),
    ])
    if idle_seconds > 0:
        lines.extend([
            "",
            f"    Idle/input time: {idle_seconds:.2f} seconds",
        ])

    return "\n".join(lines)
    
def render_invoice_preview(invoice, display_number):
    return invoice["preview"]


def confirm_invoices(parsed_invoices):
    print_paginated_items(
        title="Parsed invoices",
        items=parsed_invoices,
        render_item=render_invoice_preview,
        empty_message="No parsed invoices found.",
    )

    print("\nImport options:")
    print("  A = import all invoices")
    print("  N = import none")
    print("  1,3 = import only selected invoice numbers above")

    while True:
        choice = track_input("Choose invoices to import: ").strip()

        if choice.lower() == "a":
            return {
                invoice["invoice_index"]
                for invoice in parsed_invoices
            }

        if choice.lower() == "n":
            return set()

        try:
            selected = {
                int(part.strip())
                for part in choice.split(",")
                if part.strip()
            }

            valid = {
                invoice["invoice_index"]
                for invoice in parsed_invoices
            }

            if selected and selected.issubset(valid):
                return selected

        except ValueError:
            pass

        print("Invalid choice. Use A, N, or invoice numbers like 1,3.")
        
def build_import_summary(
    invoice_index,
    df,
    file_name,
    inserted,
    skipped,
    processing_seconds,
    idle_seconds,
):
    invoice_number = (
        df["_invoice_number"].dropna().iloc[0]
        if len(df["_invoice_number"].dropna())
        else "Missing"
    )

    customer = (
        df["_customer"].dropna().iloc[0]
        if len(df["_customer"].dropna())
        else "Missing"
    )

    week_endings = sorted([
        str(x)
        for x in df["week_ending"].dropna().unique()
    ],reverse=True,)

    retro_week_endings = sorted(
        [
            str(x)
            for x in df.loc[
                df["section_type"].eq("additional"),
                "week_ending",
            ]
            .dropna()
            .unique()
        ],reverse=True,
    )

    section_summary = build_section_summary(df)

    summary_lines = [
        f"  [{invoice_index}] Invoice : {invoice_number}\n    [{file_name}]",
        f"    Customer: {customer}",
        f"    Processing time: {processing_seconds:.2f} seconds",
        f"    WE      : {', '.join(week_endings) if week_endings else 'Missing'}",
    ]

    if idle_seconds > 0:
        summary_lines.append(
            f"    Idle/input time: {idle_seconds:.2f} seconds"
        )

    if retro_week_endings:
        summary_lines.append(
            f"    Retro/additional week ending: {', '.join(retro_week_endings)}"
        )

    summary_lines.extend(
        [
            "",
            "    By section:",
        ]
    )

    append_section_summary(
        summary_lines,
        section_summary,
        include_total_row=True,
    )

    return "\n".join(summary_lines)