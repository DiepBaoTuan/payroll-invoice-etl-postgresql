import shutil
import pandas as pd
import hashlib
from datetime import datetime
from pathlib import Path
from parsing import parse_invoice_filename
from config import INVOICE_DIR


def file_hash(path: Path) -> str:
    h = hashlib.sha256()

    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)

    return h.hexdigest()





def invoice_sort_key(file_path):
    try:
        data = parse_invoice_filename(file_path.name)
        return (
            data["invoice_number"].lower(),
            data["customer"].lower(),
            file_path.name.lower(),
        )
    except Exception:
        return (
            "zzz",
            "zzz",
            file_path.name.lower(),
        )


EXCEL_SUFFIXES = {".xlsx", ".xls"}


def is_valid_excel_file(file_path):
    if not file_path.is_file():
        return False

    if file_path.name.startswith("~$"):
        return False

    if file_path.name.startswith("."):
        return False

    return file_path.suffix.lower() in EXCEL_SUFFIXES


def get_excel_files():
    files = [
        file_path
        for file_path in INVOICE_DIR.iterdir()
        if is_valid_excel_file(file_path)
    ]

    return sorted(files, key=invoice_sort_key)
    


def read_excel_raw(file_path: Path):
    """Read supported Excel files with the correct engine for each suffix."""
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()

    if suffix == ".xlsx":
        return pd.read_excel(file_path, header=None, engine="openpyxl")

    if suffix == ".xls":
        return pd.read_excel(file_path, header=None, engine="xlrd")

    raise ValueError(f"Unsupported Excel file type: {file_path.suffix}")


def move_file_safely(source_path: Path, target_dir: Path):
    target_dir.mkdir(parents=True, exist_ok=True)

    source_path = Path(source_path)

    if not source_path.exists():
        print(f"File already moved or missing, skipping move: {source_path}")
        return None

    target_path = target_dir / source_path.name

    if target_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_path = target_dir / f"{source_path.stem}_{timestamp}{source_path.suffix}"

    shutil.move(str(source_path), str(target_path))

    return target_path