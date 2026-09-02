"""Historia zdarzeń: wysyłki, błędy, testy połączenia."""

from __future__ import annotations

import csv
from tkinter import filedialog, messagebox

import customtkinter as ctk

from . import theme
from .widgets import Card, DataTable, button

LEVEL_LABELS = {
    "Wszystko": None,
    "Wysłane": "ok",
    "Ostrzeżenia": "warn",
    "Błędy": "error",
    "Informacje": "info",
}


class LogView(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.store = app.store

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        card = Card(self, "Historia", "Ostatnie 500 zdarzeń, od najnowszego.")
        card.grid(row=0, column=0, sticky="nsew")
        card.body.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(card.body, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        bar.grid_columnconfigure(3, weight=1)

        self.level_var = ctk.StringVar(value="Wszystko")
        ctk.CTkOptionMenu(
            bar,
            values=list(LEVEL_LABELS),
            variable=self.level_var,
            command=lambda _value: self.refresh(),
            width=150,
            height=34,
            corner_radius=8,
            fg_color=theme.SURFACE_HI,
            button_color=theme.BORDER,
            button_hover_color=theme.ACCENT,
            text_color=theme.TEXT,
            font=theme.font(12),
        ).grid(row=0, column=0, padx=(0, 8))
        button(bar, "Odśwież", self.refresh, kind="ghost", width=100).grid(row=0, column=1, padx=(0, 8))
        button(bar, "Eksport CSV", self.export_csv, kind="ghost", width=130).grid(
            row=0, column=2, padx=(0, 8)
        )
        button(bar, "Wyczyść historię", self.clear, kind="danger", width=150).grid(row=0, column=4)

        self.table = DataTable(
            card.body,
            [
                ("ts", "Kiedy", 160),
                ("email", "Odbiorca", 240),
                ("message", "Zdarzenie", 520),
            ],
        )
        self.table.grid(row=1, column=0, sticky="nsew")
        self.refresh()

    def refresh(self) -> None:
        level = LEVEL_LABELS.get(self.level_var.get())
        rows = self.store.list_log(limit=500, level=level)
        self.table.clear()
        for index, row in enumerate(rows):
            tags = ["lvl_" + row["level"]]
            if index % 2:
                tags.append("odd")
            self.table.add_row(
                str(row["id"]), [row["ts"], row["email"] or "-", row["message"]], tags=tags
            )

    def export_csv(self) -> None:
        rows = self.store.list_log(limit=100000)
        if not rows:
            messagebox.showinfo(
                "Pusto", "Historia jest pusta.", parent=self.winfo_toplevel()
            )
            return
        path = filedialog.asksaveasfilename(
            title="Zapisz historię",
            defaultextension=".csv",
            filetypes=[("Plik CSV", "*.csv")],
            initialfile="historia-wysylki.csv",
            parent=self.winfo_toplevel(),
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["Kiedy", "Poziom", "Odbiorca", "Zdarzenie"])
            for row in rows:
                writer.writerow([row["ts"], row["level"], row["email"] or "", row["message"]])
        messagebox.showinfo(
            "Zapisano", "Historia zapisana do:\n" + path, parent=self.winfo_toplevel()
        )

    def clear(self) -> None:
        if messagebox.askyesno(
            "Wyczyścić historię?",
            "Usunąć wszystkie wpisy z historii? Statusy odbiorców pozostaną bez zmian.",
            parent=self.winfo_toplevel(),
        ):
            self.store.clear_log()
            self.app.refresh_all()
