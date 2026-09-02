"""Punkt wejścia aplikacji DripSender."""

from __future__ import annotations

import sys
import traceback


def main() -> int:
    try:
        from dripsender.ui.app import run
    except ImportError as exc:
        print("Brak wymaganych bibliotek:", exc)
        print("Zainstaluj je poleceniem:  pip install -r requirements.txt")
        return 1

    try:
        run()
    except Exception:  # noqa: BLE001 - ostatnia deska ratunku
        traceback.print_exc()
        try:
            from tkinter import messagebox

            messagebox.showerror(
                "Błąd krytyczny",
                "Aplikacja napotkała nieoczekiwany błąd:\n\n" + traceback.format_exc(limit=3),
            )
        except Exception:  # noqa: BLE001
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
