import os
import platform
import subprocess
import sys
from pathlib import Path


def get_os_name():
    return platform.system().lower()


def is_windows():
    return get_os_name() == "windows"


def is_macos():
    return get_os_name() == "darwin"


def is_linux():
    return get_os_name() == "linux"


def configure_console():
    """
    Helps Windows terminals handle UTF-8 output better.
    Safe on macOS/Linux too.
    """
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def safe_text(value):
    """
    Replaces characters that may display badly in older Windows terminals.
    """
    if value is None:
        return ""

    text = str(value)

    replacements = {
        "—": "-",
        "–": "-",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


def normalize_path(path_value):
    if path_value is None:
        return None

    return Path(path_value).expanduser().resolve()


def format_path_for_display(path_value):
    if path_value is None:
        return ""

    return str(Path(path_value))


def open_folder(path_value):
    """
    Optional helper if you later want to open invoices/processed/failed folders.
    """
    path = Path(path_value).resolve()

    if is_windows():
        os.startfile(path)  # noqa: S606
        return

    if is_macos():
        subprocess.run(["open", str(path)], check=False)
        return

    subprocess.run(["xdg-open", str(path)], check=False)