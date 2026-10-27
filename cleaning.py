import pandas as pd

from config import NUMERIC_COLUMNS, ROUND_2_COLUMNS, TEXT_COLUMNS
from timing import now_utc


def clean_money_or_number(value):
    if pd.isna(value):
        return None

    if isinstance(value, str):
        value = (
            value.replace("$", "")
            .replace(",", "")
            .replace("(", "-")
            .replace(")", "")
            .strip()
        )

        if value == "":
            return None

    result = pd.to_numeric(value, errors="coerce")

    if pd.isna(result):
        return None

    return float(result)


def clean_text_value(value):
    if pd.isna(value):
        return None

    text = str(value).strip()

    if text == "" or text.lower() == "nan":
        return None

    return text


def clean_shift(value):
    if pd.isna(value):
        return None

    number = pd.to_numeric(value, errors="coerce")

    if not pd.isna(number):
        if float(number).is_integer():
            return str(int(number))

        return str(number)

    return clean_text_value(value)


def round_or_none(value, decimals=2):
    if pd.isna(value):
        return None

    number = pd.to_numeric(value, errors="coerce")

    if pd.isna(number):
        return None

    return round(float(number), decimals)


def clean_dataframe(df: pd.DataFrame, file_path, engine) -> pd.DataFrame:
    df = df.copy()

    for col in NUMERIC_COLUMNS:
        if col not in df.columns:
            df[col] = None

        df[col] = df[col].apply(clean_money_or_number)

    for col in ROUND_2_COLUMNS:
        if col in df.columns:
            df[col] = df[col].apply(round_or_none)

    for col in TEXT_COLUMNS:
        if col not in df.columns:
            df[col] = None

        if col == "shift":
            df[col] = df[col].apply(clean_shift)
        else:
            df[col] = df[col].apply(clean_text_value)

    df["week_ending"] = pd.to_datetime(df["week_ending"], errors="coerce").dt.date
    df["imported_at"] = now_utc()

    final_columns = [
        "_excel_row_number",
        "_pay_difference_candidate",
        "_bill_difference_candidate",
        "employee_number",
        "last_name",
        "first_name",
        "area",
        "subarea",
        "shift",
        "plant",
        "position",
        "section_type",
        "rate_type",
        "adjustment_type",
        "pay_rate",
        "weekly_rate",
        "total_hours",
        "regular_hours",
        "overtime_hours",
        "regular_bill_rate",
        "overtime_bill_rate",
        "regular_markup",
        "overtime_markup",
        "total_amount",
        "week_ending",
        "imported_at",
    ]

    for col in final_columns:
        if col not in df.columns:
            df[col] = None

    df = df[final_columns]
    df = df.astype(object).where(pd.notnull(df), None)

    return df