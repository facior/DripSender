"""Ścieżki aplikacji: katalog danych, baza, zasoby."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .branding import APP_SLUG as APP_NAME


def is_frozen() -> bool:
    """Czy aplikacja działa jako spakowany plik .exe (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Katalog, w którym leży aplikacja."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Katalog na bazę danych i załączniki.

    Jeśli obok aplikacji leży plik ``portable.txt``, dane trzymamy w podkatalogu
    ``dane`` - dzięki temu całość można przenosić na pendrive.
    """
    if (app_dir() / "portable.txt").exists():
        target = app_dir() / "dane"
    else:
        base = os.environ.get("APPDATA") or str(Path.home())
        target = Path(base) / APP_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def db_path() -> Path:
    return data_dir() / "mailer.db"


def resource_path(relative: str) -> Path:
    """Ścieżka do zasobu dołączonego do paczki PyInstallera."""
    base = Path(getattr(sys, "_MEIPASS", str(app_dir())))
    return base / relative
