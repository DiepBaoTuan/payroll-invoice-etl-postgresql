import os
from pathlib import Path
from dotenv import load_dotenv
from platform_utils import configure_console, normalize_path

configure_console()

BASE_DIR = Path(__file__).parent.resolve()
ENV_PATH = BASE_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip() or None


def get_int_env(name, default):
    value = os.getenv(name, "").strip()

    if not value:
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got: {value!r}") from exc


PAGE_SIZE = get_int_env("PAGE_SIZE", 25)
APP_VERSION = "2026.05.26"
APP_MINOR_VERSION = "v10"

def get_folder_from_env(env_name, default_folder_name):
    value = os.getenv(env_name, "").strip()

    if value:
        return normalize_path(value)

    return BASE_DIR / default_folder_name


INVOICE_DIR = get_folder_from_env("INVOICE_DIR", "invoices")
PROCESSED_DIR = get_folder_from_env("PROCESSED_DIR", "processed")
FAILED_DIR = get_folder_from_env("FAILED_DIR", "failed")
REPORTS_DIR = get_folder_from_env("REPORTS_DIR", "reports")

for folder in [INVOICE_DIR, PROCESSED_DIR, FAILED_DIR, REPORTS_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

COLUMN_ALIASES = {
    "EMP##": "employee_number",
    "EMP#": "employee_number",
    "EMP #": "employee_number",
    "EMP NO": "employee_number",
    "EMP NO.": "employee_number",
    "EMPLOYEE #": "employee_number",
    "EMPLOYEE NUMBER": "employee_number",
    "LAST NAME": "last_name",
    "FIRST NAME": "first_name",
    "AREA": "area",
    "SUBAREA": "subarea",
    "SHIFT": "shift",
    "PLANT": "plant",
    "POSITION": "position",
    "PAY RATE": "pay_rate",
    "WEEKLY RATE": "weekly_rate",
    "TOTAL HRS": "total_hours",
    "TOTAL": "total_hours",
    "REG HRS": "regular_hours",
    "OT HRS": "overtime_hours",
    "REG BR": "regular_bill_rate",
    "OT BR": "overtime_bill_rate",
    "REG MARK UP": "regular_markup",
    "REG MARKUP": "regular_markup",
    "OT MARK UP": "overtime_markup",
    "OT MARKUP": "overtime_markup",
    "$ TOTAL": "total_amount",
    "TOTAL2": "total_amount",
}

NUMERIC_COLUMNS = [
    "pay_rate", "weekly_rate", "total_hours", "regular_hours",
    "overtime_hours", "regular_bill_rate", "overtime_bill_rate",
    "regular_markup", "overtime_markup", "total_amount",
]

ROUND_2_COLUMNS = NUMERIC_COLUMNS

TEXT_COLUMNS = [
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
]