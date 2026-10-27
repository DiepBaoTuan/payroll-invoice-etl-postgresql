import re
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

from config import COLUMN_ALIASES
from timing import now_utc

def clean_numeric_value(value):
    if pd.isna(value):
        return None

    text = str(value).strip()

    if text == "":
        return None

    text = (
        text.replace("$", "")
        .replace(",", "")
        .replace("(", "-")
        .replace(")", "")
        .strip()
    )

    try:
        return float(text)
    except ValueError:
        return None
        

def normalize_header(value):
    if pd.isna(value):
        return ""

    value = str(value).strip().upper()
    value = value.replace("\n", " ")

    return " ".join(value.split())


EMPLOYEE_HEADER_LABELS = {
    "EMP##",
    "EMP#",
    "EMP #",
    "EMP NO",
    "EMP NO.",
    "EMPLOYEE #",
    "EMPLOYEE NUMBER",
}


MONTH_NAME_TO_NUMBER = {
    "JAN": 1,
    "JANUARY": 1,
    "FEB": 2,
    "FEBRUARY": 2,
    "MAR": 3,
    "MARCH": 3,
    "APR": 4,
    "APRIL": 4,
    "MAY": 5,
    "JUN": 6,
    "JUNE": 6,
    "JUL": 7,
    "JULY": 7,
    "AUG": 8,
    "AUGUST": 8,
    "SEP": 9,
    "SEPT": 9,
    "SEPTEMBER": 9,
    "OCT": 10,
    "OCTOBER": 10,
    "NOV": 11,
    "NOVEMBER": 11,
    "DEC": 12,
    "DECEMBER": 12,
}


def parse_month_name(month_text, file_name):
    month_key = str(month_text or "").strip().upper()

    if month_key not in MONTH_NAME_TO_NUMBER:
        raise ValueError(
            f"Invalid month in filename: {month_text!r} in {file_name}."
        )

    return MONTH_NAME_TO_NUMBER[month_key]


def validate_filename_period_end(period_end, file_name):
    if not is_sunday(period_end):
        raise ValueError(
            f"Invalid invoice period in filename: {file_name}. "
            f"Period end date {period_end} ({format_weekday(period_end)}) "
            "must be Sunday because it is the filename WE date."
        )

    return period_end


def invoice_number_has_adjustment_suffix(invoice_number):
    """
    Return True for adjustment-style invoice numbers such as 29477-A.

    These invoices often contain rate-difference rows without a clear
    section note. They should still be reviewed as pay-difference candidates
    when the pay rate is a small positive amount.
    """
    text = str(invoice_number or "").strip().upper()
    return bool(re.search(r"-[A-Z]+$", text))

def parse_invoice_filename(file_name):
    name = Path(file_name).stem.strip()

    pattern = (
        r"^.+?\s*-\s*"
        r"(?P<customer>.+?)\s*-\s*"
        r"INVOICE\s+(?P<invoice_number>[A-Z0-9-]+)\s+"
        r"(?P<start_month>[A-Z]{3,9})\s+(?P<start_day>\d{1,2})\s*-\s*"
        r"(?P<end_month>[A-Z]{3,9})\s+(?P<end_day>\d{1,2})\s*-\s*"
        # Allow extra trailing text after the year, e.g. "(1)", "copy", or "- revised".
        r"(?P<year>\d{4})(?:\s*(?P<suffix>.+))?$"
    )

    match = re.match(pattern, name, re.IGNORECASE)

    if not match:
        raise ValueError(
            f"Invalid filename format: {file_name}. Expected: "
            "Vendor - Customer Name - INVOICE 29373 APR 20 - APR 26 - 2026.xlsx"
        )

    year = int(match.group("year"))
    start_month = parse_month_name(match.group("start_month"), file_name)
    end_month = parse_month_name(match.group("end_month"), file_name)
    start_day = int(match.group("start_day"))
    end_day = int(match.group("end_day"))

    try:
        filename_period_end = datetime(year, end_month, end_day).date()
    except ValueError as exc:
        raise ValueError(
            f"Invalid invoice period end date in filename: {file_name}. "
            f"Parsed end date parts: {match.group('end_month')} {end_day}, {year}."
        ) from exc

    start_year = year

    # Handles filename periods that cross year-end, e.g. DEC 30 - JAN 5 - 2026.
    if start_month > end_month:
        start_year -= 1

    try:
        filename_period_start = datetime(start_year, start_month, start_day).date()
    except ValueError as exc:
        raise ValueError(
            f"Invalid invoice period start date in filename: {file_name}. "
            f"Parsed start date parts: {match.group('start_month')} {start_day}, {start_year}."
        ) from exc

    if filename_period_start > filename_period_end:
        raise ValueError(
            f"Invalid invoice period in filename: {file_name}. "
            f"Start date {filename_period_start} is after end date {filename_period_end}."
        )

    validate_filename_period_end(filename_period_end, file_name)

    return {
        "customer": " ".join(match.group("customer").split()),
        "invoice_number": match.group("invoice_number"),
        "filename_period_start": filename_period_start,
        "filename_period_end": filename_period_end,
    }


def parse_date_value(value):
    if pd.isna(value):
        return None

    parsed = pd.to_datetime(value, errors="coerce")

    if pd.isna(parsed):
        return None

    return parsed.date()


def is_sunday(value):
    return value is not None and value.weekday() == 6


def sunday_of_week(value):
    if value is None:
        return None

    days_until_sunday = (6 - value.weekday()) % 7
    return value + timedelta(days=days_until_sunday)


def format_weekday(value):
    if value is None:
        return "unknown"

    return value.strftime("%A")


def validate_explicit_week_ending(parsed_date, source_text, excel_row_number):
    if parsed_date is None:
        return None

    if not is_sunday(parsed_date):
        raise ValueError(
            "Invalid explicit WE date. "
            f"Excel row {excel_row_number}: {source_text!r} parsed as "
            f"{parsed_date} ({format_weekday(parsed_date)}), but WE dates "
            "must be Sundays."
        )

    return parsed_date


def convert_implicit_date_to_week_ending(parsed_date, source_text, excel_row_number):
    if parsed_date is None:
        return None, None

    week_ending = sunday_of_week(parsed_date)

    warning = (
        "Implicit/effective date used for week ending. "
        f"Excel row {excel_row_number}: {source_text!r} parsed as "
        f"{parsed_date} ({format_weekday(parsed_date)}); using Sunday "
        f"{week_ending} as WE date."
    )

    return week_ending, warning


def validate_invoice_period_thru(period_thru, excel_row_number):
    if period_thru is None:
        return None

    if not is_sunday(period_thru):
        raise ValueError(
            "Invalid invoice PERIOD THRU date. "
            f"Excel row {excel_row_number}: PERIOD THRU parsed as "
            f"{period_thru} ({format_weekday(period_thru)}), but invoice "
            "period / WE dates must be Sundays."
        )

    return period_thru


def extract_invoice_period_thru(raw: pd.DataFrame):
    for row_index in range(len(raw)):
        row_values = [normalize_header(v) for v in raw.iloc[row_index].tolist()]

        for col_index, value in enumerate(row_values):
            if value == "PERIOD THRU" and row_index + 1 < len(raw):
                parsed_date = parse_date_value(raw.iloc[row_index + 1, col_index])

                return validate_invoice_period_thru(
                    parsed_date,
                    row_index + 2,
                )

    return None


def extract_excel_invoice_number(raw: pd.DataFrame):
    for row_index in range(len(raw)):
        row_values = [normalize_header(v) for v in raw.iloc[row_index].tolist()]

        for col_index, value in enumerate(row_values):
            if value == "INVOICE NO." and row_index + 1 < len(raw):
                invoice_value = raw.iloc[row_index + 1, col_index]

                if pd.isna(invoice_value):
                    return None

                parsed = str(invoice_value).strip()

                if parsed.endswith(".0"):
                    parsed = parsed[:-2]

                return parsed

    return None

    
def detect_section_type(headers, note_text="", section_number=1):
    header_set = set(headers)
    note_text = (note_text or "").upper()

    # Additional/adjustment section indicators must win before the generic
    # salary classification. Some adjustment notes contain text like
    # "Approved Additional Payment for Salary Emp ..."; those are still
    # additional sections and need row-level WE handling.
    additional_note_keywords = [
        "ORIENTATION",
        "ADDITIONAL",
        "RETRO",
        "MISSING HOURS",
        "MISSING HRS",
        "PAY DIFF",
        "RATE DIFF",
        "DIFFERENCE",
    ]

    if any(keyword in note_text for keyword in additional_note_keywords):
        return "additional"

    if re.search(r"PAY\s+RATE\s+.*DIFFERENCE", note_text):
        return "additional"

    if re.search(r"PAY\s+.*DIFFERENCE", note_text):
        return "additional"

    if re.search(r"RATE\s+.*DIFFERENCE", note_text):
        return "additional"

    # A plain Salary section should remain salary even when it has billing
    # markup columns. The markup headers are common in normal salary sections.
    # Additional/retro/orientation indicators above still win for notes such as
    # "Approved Additional Payment for Salary Emp ...".
    if "SALARY" in note_text:
        return "salary"

    if "WEEKLY RATE" in header_set:
        return "salary"

    if (
        "REG MARK UP" in header_set
        or "REG MARKUP" in header_set
        or "OT MARK UP" in header_set
        or "OT MARKUP" in header_set
    ):
        return "additional"

    # Important rule:
    # If this is a later physical employee section, do not classify it as hourly.
    # Normal hourly invoice body should be the first physical section.
    if section_number > 1:
        return "additional"

    return "hourly"
    
    
def detect_adjustment_type(note_text, section_type):
    note_text = (note_text or "").upper()

    if section_type != "additional":
        return None

    pay_difference_patterns = [
        r"PAY\s+RATE\s+.*DIFFERENCE",
        r"PAY\s+.*DIFFERENCE",
        r"RATE\s+.*DIFFERENCE",
        r"PAY\s+DIFF",
        r"RATE\s+DIFF",
        r"DIFFERENCE",
    ]

    if any(re.search(pattern, note_text) for pattern in pay_difference_patterns):
        return "pay_difference"

    if "ORIENTATION" in note_text:
        return "orientation"

    if "RETRO" in note_text:
        return "retro_hours"

    return "additional"
    
def is_bill_difference_candidate(row_dict):
    if row_dict.get("adjustment_type") == "bill_difference":
        return False

    pay_rate = clean_numeric_value(row_dict.get("pay_rate"))
    regular_bill_rate = clean_numeric_value(row_dict.get("regular_bill_rate"))
    overtime_bill_rate = clean_numeric_value(row_dict.get("overtime_bill_rate"))

    if pay_rate is None or pay_rate <= 0:
        return False

    bill_rates = [
        value
        for value in [
            regular_bill_rate,
            overtime_bill_rate,
        ]
        if value is not None and value > 0
    ]

    if not bill_rates:
        return False

    return any(bill_rate < pay_rate for bill_rate in bill_rates)
    
    
def is_low_pay_rate_pay_difference_candidate(row_dict, threshold=6):
    """
    Flag small positive pay rates for review as possible pay-difference rows.

    Candidate rules:
    - additional/adjustment sections with low positive pay rates
    - rows already marked additional/pay_difference with low positive pay rates
    - adjustment-style invoice numbers such as 29477-A with low positive pay rates

    The row is only a candidate here. The user still confirms whether to label
    it as pay_difference before import.
    """
    section_type = row_dict.get("section_type")
    adjustment_type = row_dict.get("adjustment_type")
    invoice_number = row_dict.get("_invoice_number")

    is_candidate_context = (
        section_type == "additional"
        or adjustment_type in {"additional", "pay_difference"}
        or invoice_number_has_adjustment_suffix(invoice_number)
    )

    if not is_candidate_context:
        return False

    pay_rate = clean_numeric_value(row_dict.get("pay_rate"))

    if pay_rate is None:
        return False

    return pay_rate > 0 and pay_rate < threshold
        
def detect_rate_type(headers):
    header_set = set(headers)

    if "WEEKLY RATE" in header_set:
        return "weekly"

    return "hourly"


def is_header_row(row_values):
    return any(value in EMPLOYEE_HEADER_LABELS for value in row_values)


def is_probably_data_row(row):
    employee_number = row.iloc[0] if len(row) > 0 else None
    last_name = row.iloc[1] if len(row) > 1 else None
    first_name = row.iloc[2] if len(row) > 2 else None

    for value in [employee_number, last_name, first_name]:
        if pd.isna(value):
            return False

        text = str(value).strip().upper()

        if text in EMPLOYEE_HEADER_LABELS or text in ["", "TOTAL", "GRAND TOTAL"]:
            return False

    return True

def build_column_positions(row_values, section_type):
    """
    Build column mapping for a section header row.

    Handles cases where:
    - TOTAL means total_hours
    - duplicate TOTAL / TOTAL2 means total_amount
    - salary/additional sections may not use $ TOTAL
    """

    column_positions = {}

    total_indices = []
    total_amount_indices = []

    for col_index, header in enumerate(row_values):
        header = normalize_header(header)

        if not header:
            continue

        # Handle ambiguous TOTAL separately.
        if header == "TOTAL":
            total_indices.append(col_index)
            continue

        # Explicit total amount labels.
        if header in {
            "$ TOTAL",
            "TOTAL2",
            "TOTAL.1",
            "TOTAL AMOUNT",
            "AMOUNT",
            "AMOUNT DUE",
        }:
            total_amount_indices.append(col_index)
            continue

        # Normal direct aliases.
        if header in COLUMN_ALIASES:
            column_positions[col_index] = COLUMN_ALIASES[header]

    mapped_fields = set(column_positions.values())

    # If TOTAL HRS was not present, first TOTAL is usually hours.
    if "total_hours" not in mapped_fields and total_indices:
        column_positions[total_indices[0]] = "total_hours"

    # Explicit amount column wins.
    if total_amount_indices:
        column_positions[total_amount_indices[-1]] = "total_amount"

    # If there are multiple TOTAL columns, last one is usually the amount.
    elif len(total_indices) >= 2:
        column_positions[total_indices[-1]] = "total_amount"

    return column_positions

def infer_total_amount_from_row(data_row, column_positions):
    """
    Fallback for salary/additional sections where the total amount column
    is not clearly labeled.

    It looks for the rightmost numeric value not already mapped as a known
    non-amount field.
    """

    excluded_fields = {
        "employee_number",
        "shift",
        "pay_rate",
        "weekly_rate",
        "total_hours",
        "regular_hours",
        "overtime_hours",
        "regular_bill_rate",
        "overtime_bill_rate",
        "regular_markup",
        "overtime_markup",
    }

    excluded_columns = {
        col_index
        for col_index, db_column in column_positions.items()
        if db_column in excluded_fields
    }

    candidates = []

    for col_index, value in enumerate(data_row.tolist()):
        if col_index in excluded_columns:
            continue

        number = clean_numeric_value(value)

        if number is not None and number > 0:
            candidates.append((col_index, number))

    if not candidates:
        return None

    # Amount is usually the rightmost numeric value in the data row.
    return sorted(candidates, key=lambda x: x[0])[-1][1]
    
def extract_section_week_ending(raw: pd.DataFrame, header_row_index: int, default_year=None):
    if header_row_index == 0:
        return None, None

    excel_row_number = header_row_index
    note_row = raw.iloc[header_row_index - 1].tolist()
    note_text = " ".join(
        [
            str(v).strip()
            for v in note_row
            if not pd.isna(v)
        ]
    ).upper()

    def build_date(month, day, year_text=None):
        if year_text:
            year = int(year_text)

            if year < 100:
                year += 2000
        else:
            if default_year is None:
                return None

            year = default_year

        try:
            return datetime(year, int(month), int(day)).date()
        except ValueError:
            return None

    # 1. Explicit WE dates are strict: each one must already be Sunday.
    # If a section note contains multiple explicit WE dates, do not apply the
    # first one to all rows. Row-level WE notes should drive the individual
    # rows; rows without row-level WE will keep the invoice PERIOD THRU date
    # and carry a warning.
    explicit_we_patterns = [
        r"\bWE\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b",
        r"\bW/E\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b",
        r"\bWEEK\s*ENDING\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b",
    ]

    explicit_matches = []

    for pattern in explicit_we_patterns:
        explicit_matches.extend(list(re.finditer(pattern, note_text)))

    if explicit_matches:
        validated_dates = []

        for match in explicit_matches:
            parsed_date = build_date(
                match.group(1),
                match.group(2),
                match.group(3),
            )

            if parsed_date:
                validated_dates.append(
                    validate_explicit_week_ending(
                        parsed_date,
                        match.group(0),
                        excel_row_number,
                    )
                )

        unique_dates = sorted(set(validated_dates))

        if len(unique_dates) == 1:
            return unique_dates[0], None

        if len(unique_dates) > 1:
            warning = (
                "Multiple explicit WE dates found in section note. "
                f"Excel row {excel_row_number}: {', '.join(str(date) for date in unique_dates)}. "
                "Using row-level WE dates where present; rows without row-level WE "
                "keep the invoice PERIOD THRU date and should be reviewed."
            )

            return None, warning

    # 2. EFFECTIVE dates are not WE dates. Convert to the Sunday of that week
    #    and preserve a warning for review.
    effective_date_match = re.search(
        r"\bEFFECTIVE\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b",
        note_text,
    )

    if effective_date_match:
        parsed_date = build_date(
            effective_date_match.group(1),
            effective_date_match.group(2),
            effective_date_match.group(3),
        )

        if parsed_date:
            return convert_implicit_date_to_week_ending(
                parsed_date,
                effective_date_match.group(0),
                excel_row_number,
            )

    # 3. Full dates without explicit WE are treated as effective dates.
    full_date_match = re.search(
        r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b",
        note_text,
    )

    if full_date_match:
        parsed_date = build_date(
            full_date_match.group(1),
            full_date_match.group(2),
            full_date_match.group(3),
        )

        if parsed_date:
            return convert_implicit_date_to_week_ending(
                parsed_date,
                full_date_match.group(0),
                excel_row_number,
            )

    # 4. Last fallback: standalone short date in the note row. This is allowed
    #    only for section notes, not data rows, and is treated as effective date.
    short_date_match = re.search(
        r"\b(\d{1,2})/(\d{1,2})\b",
        note_text,
    )

    if short_date_match:
        parsed_date = build_date(
            short_date_match.group(1),
            short_date_match.group(2),
        )

        if parsed_date:
            return convert_implicit_date_to_week_ending(
                parsed_date,
                short_date_match.group(0),
                excel_row_number,
            )

    return None, None

def note_has_multiple_we_dates(raw: pd.DataFrame, header_row_index: int):
    if header_row_index == 0:
        return False

    note_row = raw.iloc[header_row_index - 1].tolist()
    note_text = " ".join([str(v) for v in note_row if not pd.isna(v)]).upper()

    if "WE" not in note_text:
        return False

    dates = re.findall(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", note_text)

    return len(dates) >= 2


def extract_row_week_ending_from_col_r(row, default_year=None):
    values = row.tolist()

    # The row-level WE note is usually on the right side of the row,
    # but the exact column can move: R, S, T, etc.
    right_side_values = values[15:] if len(values) > 15 else values

    # Search right side first, then the full row as fallback.
    search_values = right_side_values + values

    for value in search_values:
        if pd.isna(value):
            continue

        text = str(value).strip().upper()

        if not text:
            continue

        def build_date(month, day, year_text=None):
            if year_text:
                year = int(year_text)

                if year < 100:
                    year += 2000
            else:
                year = default_year or now_utc().year

            return datetime(year, int(month), int(day)).date()

        explicit_we_patterns = [
            r"\bWE\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b",
            r"\bW/E\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b",
            r"\bWEEK\s*ENDING\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b",
        ]

        for pattern in explicit_we_patterns:
            match = re.search(pattern, text)

            if not match:
                continue

            parsed_date = build_date(
                match.group(1),
                match.group(2),
                match.group(3),
            )

            return (
                validate_explicit_week_ending(
                    parsed_date,
                    match.group(0),
                    row.name + 1 if getattr(row, "name", None) is not None else "unknown",
                ),
                None,
            )

        implicit_patterns = [
            r"\bEFFECTIVE\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b",
        ]

        for pattern in implicit_patterns:
            match = re.search(pattern, text)

            if not match:
                continue

            parsed_date = build_date(
                match.group(1),
                match.group(2),
                match.group(3),
            )

            return convert_implicit_date_to_week_ending(
                parsed_date,
                match.group(0),
                row.name + 1 if getattr(row, "name", None) is not None else "unknown",
            )

    return None, None


def parse_invoice_sections(file_path: Path, raw=None) -> pd.DataFrame:
    if raw is None:
        raw = pd.read_excel(file_path, header=None, engine="openpyxl")

    parsed_sections = []

    filename_data = parse_invoice_filename(file_path.name)
    filename_invoice_number = filename_data["invoice_number"]

    excel_invoice_number = extract_excel_invoice_number(raw)

    if not excel_invoice_number:
        raise ValueError(
            f"Missing invoice number in Excel file. "
            f"Expected filename invoice number: {filename_invoice_number}"
        )

    if str(excel_invoice_number).strip() != str(filename_invoice_number).strip():
        raise ValueError(
            f"Invoice number mismatch. Filename: {filename_invoice_number}; "
            f"Excel: {excel_invoice_number}"
        )

    invoice_week_ending = extract_invoice_period_thru(raw)
    default_year = invoice_week_ending.year if invoice_week_ending else None

    physical_section_number = 0

    for row_index in range(len(raw)):
        row_values = [
            normalize_header(value)
            for value in raw.iloc[row_index].tolist()
        ]

        if not is_header_row(row_values):
            continue

        physical_section_number += 1

        note_text = ""

        if row_index > 0:
            note_text = " ".join(
                [
                    str(value).strip()
                    for value in raw.iloc[row_index - 1].tolist()
                    if not pd.isna(value)
                ]
            )

        section_type = detect_section_type(
            row_values,
            note_text=note_text,
            section_number=physical_section_number,
        )

        rate_type = detect_rate_type(row_values)

        adjustment_type = detect_adjustment_type(
            note_text,
            section_type,
        )

        section_week_ending = invoice_week_ending

        # Check date notes for every section type, including salary.
        # A salary section with a single WE/date note should use that date for
        # all rows. If the note contains multiple dates, each row must carry its
        # own explicit row-level WE where applicable.
        section_specific_we, section_we_warning = extract_section_week_ending(
            raw,
            row_index,
            default_year=default_year,
        )

        if section_specific_we:
            section_week_ending = section_specific_we

        section_requires_row_level_we = note_has_multiple_we_dates(
            raw,
            row_index,
        )
        
        column_positions = build_column_positions(
            row_values,
            section_type=section_type,
        )

        data_rows = []

        for data_index in range(row_index + 1, len(raw)):
            data_row = raw.iloc[data_index]

            next_row_values = [
                normalize_header(value)
                for value in data_row.tolist()
            ]

            if is_header_row(next_row_values):
                break

            if data_row.isna().all():
                continue

            if not is_probably_data_row(data_row):
                continue

            row_week_ending = section_week_ending

            # Row-level explicit WE values win when a section has multiple dates
            # in the note, or for additional/adjustment sections where row WE
            # notes are common. This is intentionally not limited to additional
            # sections so salary sections with dated notes are handled correctly.
            row_we_warning = section_we_warning

            should_check_row_level_we = (
                section_requires_row_level_we
                or section_type == "additional"
            )

            if should_check_row_level_we:
                row_specific_we, row_specific_we_warning = extract_row_week_ending_from_col_r(
                    data_row,
                    default_year=default_year,
                )

                if row_specific_we:
                    row_week_ending = row_specific_we
                    row_we_warning = row_specific_we_warning
                elif section_requires_row_level_we:
                    row_we_warning = (
                        f"Section note on Excel row {row_index} contains multiple WE dates, "
                        f"but Excel row {data_index + 1} does not have an explicit row-level WE date. "
                        "Using invoice PERIOD THRU date; review before import."
                    )

            row_dict = {
                "_excel_row_number": data_index + 1,
                "_week_ending_warning": row_we_warning,
                "_invoice_number": filename_invoice_number,
                "section_type": section_type,
                "rate_type": rate_type,
                "adjustment_type": adjustment_type,
                "week_ending": row_week_ending,
                "imported_at": now_utc(),
            }

            for col_index, db_column in column_positions.items():
                row_dict[db_column] = data_row.iloc[col_index]

            if (
                section_type in {"salary", "additional"}
                and (
                    "total_amount" not in row_dict
                    or pd.isna(row_dict.get("total_amount"))
                )
            ):
                inferred_total_amount = infer_total_amount_from_row(
                    data_row,
                    column_positions,
                )

                if inferred_total_amount is not None:
                    row_dict["total_amount"] = inferred_total_amount

            row_dict["_pay_difference_candidate"] = (
                is_low_pay_rate_pay_difference_candidate(row_dict)
            )
            row_dict["_bill_difference_candidate"] = (
                is_bill_difference_candidate(row_dict)
            )

            data_rows.append(row_dict)

        if data_rows:
            parsed_sections.append(pd.DataFrame(data_rows))

    if not parsed_sections:
        raise ValueError("No invoice sections found. Could not detect employee header rows such as EMP## or EMP#.")

    return pd.concat(parsed_sections, ignore_index=True)
    
        
def extract_invoice_total(raw: pd.DataFrame, expected_total=None):
    """
    Finds invoice grand total in the Excel sheet.

    Strategy:
    1. If expected_total is provided, prefer the numeric value closest to it.
    2. Search near the bottom / thank-you area first.
    3. Prefer large right-side totals.
    4. Avoid picking smaller section totals above the final invoice total.
    """

    expected_total = (
        round(float(expected_total), 2)
        if expected_total is not None
        else None
    )

    thank_you_patterns = [
        "THANK YOU",
        "THANK YOU FOR YOUR BUSINESS",
        "BILLING QUESTIONS",
        "FOR BILLING QUESTIONS",
        "972-787-0157",
    ]

    invoice_total_keywords = [
        "INVOICE TOTAL",
        "AMOUNT DUE",
        "BALANCE DUE",
        "GRAND TOTAL",
    ]

    generic_total_keywords = [
        "TOTAL",
    ]

    def row_text_at(row_index):
        return " ".join(
            [
                str(value).strip().upper()
                for value in raw.iloc[row_index].tolist()
                if not pd.isna(value)
            ]
        )

    def collect_numeric_values(row_index):
        row = raw.iloc[row_index]
        values = []

        for col_index, value in enumerate(row.tolist()):
            number = clean_numeric_value(value)

            if number is None:
                continue

            if number <= 0:
                continue

            values.append(
                {
                    "row_index": row_index,
                    "col_index": col_index,
                    "amount": round(float(number), 2),
                    "raw_value": value,
                }
            )

        return values

    thank_you_row_index = None

    for row_index in range(len(raw)):
        row_text = row_text_at(row_index)

        if any(pattern in row_text for pattern in thank_you_patterns):
            thank_you_row_index = row_index
            break

    search_ranges = []

    if thank_you_row_index is not None:
        search_ranges.append(
            (
                max(0, thank_you_row_index - 10),
                thank_you_row_index + 1,
                "near_thank_you",
            )
        )

    # Always search bottom of sheet as fallback.
    search_ranges.append(
        (
            max(0, len(raw) - 80),
            len(raw),
            "bottom_scan",
        )
    )

    candidate_totals = []

    for search_start, search_end, search_reason in search_ranges:
        for row_index in range(search_start, min(search_end, len(raw))):
            row_text = row_text_at(row_index)
            numeric_values = collect_numeric_values(row_index)

            if not numeric_values:
                continue

            has_invoice_total_keyword = any(
                keyword in row_text
                for keyword in invoice_total_keywords
            )

            has_generic_total_keyword = any(
                keyword in row_text
                for keyword in generic_total_keywords
            )

            single_number_row = len(numeric_values) == 1

            for numeric in numeric_values:
                amount = numeric["amount"]
                col_index = numeric["col_index"]

                score = 0

                if expected_total is not None:
                    difference = abs(amount - expected_total)

                    # Exact / near exact expected total should dominate.
                    if difference <= 0.01:
                        score += 1_000_000
                    elif difference <= 1.00:
                        score += 500_000
                    else:
                        # Still allow candidates, but penalize by distance.
                        score -= min(difference, 100_000)

                    # Strongly prefer values near expected total.
                    # This prevents a section total like 1,283.88 from beating 362,241.58.
                    score += max(0, 100_000 - difference)

                if has_invoice_total_keyword:
                    score += 20_000

                if has_generic_total_keyword:
                    score += 5_000

                if single_number_row:
                    score += 2_000

                if search_reason == "near_thank_you":
                    score += 10_000

                # Prefer rows lower in the sheet.
                score += row_index * 10

                # Prefer right-side cells.
                score += col_index

                # Prefer larger amounts when no expected total is available.
                if expected_total is None:
                    score += min(amount, 1_000_000) / 10

                candidate_totals.append(
                    {
                        "score": score,
                        "amount": amount,
                        "row_index": row_index,
                        "col_index": col_index,
                        "reason": search_reason,
                        "row_text": row_text,
                    }
                )

    if not candidate_totals:
        return None

    # If expected_total exists, first try exact or very close matches.
    if expected_total is not None:
        close_matches = [
            candidate
            for candidate in candidate_totals
            if abs(candidate["amount"] - expected_total) <= 0.01
        ]

        if close_matches:
            best_close = sorted(
                close_matches,
                key=lambda candidate: (
                    candidate["row_index"],
                    candidate["col_index"],
                    candidate["score"],
                ),
                reverse=True,
            )[0]

            return best_close["amount"]

    best = sorted(
        candidate_totals,
        key=lambda candidate: candidate["score"],
        reverse=True,
    )[0]

    return best["amount"]