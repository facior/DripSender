"""Lista odbiorców: dodawanie, import z pliku, grupy, sprawdzanie i statusy."""

from __future__ import annotations

import csv
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..store import STATUS_LABELS, STATUS_PENDING, STATUS_UNSUBSCRIBED
from . import theme
from .dialogs import (
    BulkAddDialog,
    FieldsDialog,
    ImportDialog,
    RecipientDialog,
    TagsDialog,
    ValidateDialog,
)
from .widgets import Card, DataTable, button, entry

FILTER_ALL = "Wszyscy"
FILTERS = [FILTER_ALL] + list(STATUS_LABELS.values())
LABEL_TO_STATUS = {label: status for status, label in STATUS_LABELS.items()}
TAG_ALL = "Wszystkie grupy"


class RecipientsView(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.store = app.store
        self.sort_key = "lp"
        self.sort_desc = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.card = Card(
            self,
            "Odbiorcy",
            "Kolejność na liście to kolejność wysyłki. Dwuklik otwiera edycję odbiorcy.",
        )
        self.card.grid(row=0, column=0, sticky="nsew")
        self.card.body.grid_rowconfigure(3, weight=1)

        self._build_toolbar()
        self.table: DataTable | None = None
        self.rebuild_table()

    # ------------------------------------------------------------------ budowa

    def _build_toolbar(self) -> None:
        akcje = ctk.CTkFrame(self.card.body, fg_color="transparent")
        akcje.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        akcje.grid_columnconfigure(5, weight=1)
        button(akcje, "Dodaj", self.add_one, width=80).grid(row=0, column=0, padx=(0, 8))
        button(akcje, "Wklej wielu", self.add_many, kind="ghost", width=110).grid(
            row=0, column=1, padx=(0, 8)
        )
        button(akcje, "Wczytaj plik", self.import_file, kind="ghost", width=115).grid(
            row=0, column=2, padx=(0, 8)
        )
        button(akcje, "Edytuj", self.edit_selected, kind="ghost", width=80).grid(
            row=0, column=3, padx=(0, 8)
        )
        button(akcje, "Usuń", self.delete_selected, kind="danger", width=80).grid(
            row=0, column=4
        )

        narzedzia = ctk.CTkFrame(self.card.body, fg_color="transparent")
        narzedzia.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        narzedzia.grid_columnconfigure(7, weight=1)
        button(narzedzia, "Grupy", self.manage_tags, kind="ghost", width=80).grid(
            row=0, column=0, padx=(0, 8)
        )
        button(narzedzia, "Pola", self.manage_fields, kind="ghost", width=70).grid(
            row=0, column=1, padx=(0, 8)
        )
        button(narzedzia, "▲", lambda: self.move_selected(-1), kind="ghost", width=40).grid(
            row=0, column=2, padx=(0, 4)
        )
        button(narzedzia, "▼", lambda: self.move_selected(1), kind="ghost", width=40).grid(
            row=0, column=3, padx=(0, 8)
        )
        button(narzedzia, "Wypisz", self.mark_unsubscribed, kind="ghost", width=85).grid(
            row=0, column=4, padx=(0, 8)
        )
        button(narzedzia, "Resetuj status", self.reset_selected, kind="ghost", width=125).grid(
            row=0, column=5, padx=(0, 8)
        )
        button(narzedzia, "Sprawdź listę", self.validate_list, kind="ghost", width=120).grid(
            row=0, column=6, padx=(0, 8)
        )
        button(narzedzia, "Eksport CSV", self.export_csv, kind="ghost", width=115).grid(
            row=0, column=8
        )

        filtry = ctk.CTkFrame(self.card.body, fg_color="transparent")
        filtry.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        filtry.grid_columnconfigure(2, weight=1)

        self.filter_var = ctk.StringVar(value=FILTER_ALL)
        self.status_menu = self._menu(filtry, FILTERS, self.filter_var, 0, 130)
        self.tag_var = ctk.StringVar(value=TAG_ALL)
        self.tag_menu = self._menu(filtry, [TAG_ALL], self.tag_var, 1, 150)

        self.search_entry = entry(filtry, "Szukaj adresu lub danych odbiorcy...", width=180)
        self.search_entry.grid(row=0, column=2, sticky="ew")
        self.search_entry.bind("<KeyRelease>", lambda _event: self.refresh())

        self.summary_label = ctk.CTkLabel(
            self.card.body, text="", font=theme.font(11), text_color=theme.MUTED, anchor="w"
        )
        self.summary_label.grid(row=4, column=0, sticky="ew", pady=(10, 0))

    def _menu(self, parent, values, variable, column: int, width: int):
        widget = ctk.CTkOptionMenu(
            parent,
            values=values,
            variable=variable,
            command=lambda _v: self.refresh(),
            width=width,
            height=34,
            corner_radius=8,
            fg_color=theme.SURFACE_HI,
            button_color=theme.BORDER,
            button_hover_color=theme.ACCENT,
            text_color=theme.TEXT,
            font=theme.font(12),
        )
        widget.grid(row=0, column=column, padx=(0, 8), sticky="w")
        return widget

    def rebuild_table(self) -> None:
        """Przebudowuje tabelę po zmianie zestawu pól personalizacji."""
        if self.table is not None:
            self.table.destroy()
        columns = [("lp", "#", 44), ("email", "E-mail", 220)]
        for field_def in self.store.list_fields():
            columns.append((field_def.key, field_def.label, 120))
        columns.extend(
            [
                ("tags", "Grupy", 130),
                ("status", "Status", 105),
                ("stage", "Etap", 60),
                ("info", "Szczegóły", 230),
            ]
        )
        self.table = DataTable(
            self.card.body, columns, on_double_click=self.edit_selected, horizontal_scroll=True
        )
        self.table.grid(row=3, column=0, sticky="nsew")
        self.table.bind_headings(self.sort_by)
        self.refresh()

    # ---------------------------------------------------------------- działania

    def add_one(self) -> None:
        if RecipientDialog(self, self.store).show():
            self.app.refresh_all()

    def add_many(self) -> None:
        if BulkAddDialog(self, self.store).show():
            self.app.refresh_all()

    def import_file(self) -> None:
        if ImportDialog(self, self.store).show():
            self.app.refresh_all()

    def validate_list(self) -> None:
        if ValidateDialog(self, self.store).show():
            self.app.refresh_all()

    def manage_tags(self) -> None:
        ids = self._selected_ids()
        if not ids:
            messagebox.showinfo(
                "Nic nie zaznaczono",
                "Zaznacz odbiorców, którym chcesz przypisać grupę.",
                parent=self.winfo_toplevel(),
            )
            return
        if TagsDialog(self, self.store, ids).show():
            self.app.refresh_all()

    def manage_fields(self) -> None:
        if FieldsDialog(self, self.store).show():
            self.app.on_fields_changed()

    def _selected_ids(self) -> list[int]:
        return [int(value) for value in (self.table.selected_ids() if self.table else [])]

    def _selected_recipient(self):
        selected = self._selected_ids()
        return self.store.get_recipient(selected[0]) if len(selected) == 1 else None

    def edit_selected(self) -> None:
        recipient = self._selected_recipient()
        if not recipient:
            messagebox.showinfo(
                "Wybierz odbiorcę",
                "Zaznacz dokładnie jednego odbiorcę do edycji.",
                parent=self.winfo_toplevel(),
            )
            return
        if RecipientDialog(self, self.store, recipient).show():
            self.app.refresh_all()

    def delete_selected(self) -> None:
        ids = self._selected_ids()
        if not ids:
            messagebox.showinfo(
                "Nic nie zaznaczono",
                "Zaznacz odbiorców, których chcesz usunąć.",
                parent=self.winfo_toplevel(),
            )
            return
        if not messagebox.askyesno(
            "Usunąć odbiorców?",
            "Usunąć zaznaczonych odbiorców (" + str(len(ids)) + ")?",
            parent=self.winfo_toplevel(),
        ):
            return
        self.store.delete_recipients(ids)
        self.app.refresh_all()

    def reset_selected(self) -> None:
        ids = self._selected_ids()
        if ids:
            question = (
                "Cofnąć zaznaczonych ("
                + str(len(ids))
                + ") na początek sekwencji? Dostaną wszystkie kroki od nowa."
            )
        else:
            question = (
                "Nic nie zaznaczono. Cofnąć na początek sekwencji WSZYSTKICH odbiorców? "
                "Cała lista przejdzie kampanię jeszcze raz."
            )
        if not messagebox.askyesno("Reset statusu", question, parent=self.winfo_toplevel()):
            return
        self.store.reset_status(ids or None)
        self.app.refresh_all()

    def mark_unsubscribed(self) -> None:
        """Adres, który poprosił o wypisanie, znika z kolejki na stałe."""
        ids = self._selected_ids()
        if not ids:
            messagebox.showinfo(
                "Nic nie zaznaczono",
                "Zaznacz odbiorców, którzy poprosili o wypisanie.",
                parent=self.winfo_toplevel(),
            )
            return
        if not messagebox.askyesno(
            "Oznaczyć jako wypisanych?",
            "Zaznaczeni (" + str(len(ids)) + ") nie dostaną już żadnej wiadomości. "
            "Reset statusów ich nie ruszy.",
            parent=self.winfo_toplevel(),
        ):
            return
        self.store.set_status(ids, STATUS_UNSUBSCRIBED)
        for recipient_id in ids:
            recipient = self.store.get_recipient(recipient_id)
            if recipient:
                self.store.log("info", "Oznaczono jako wypisanego.", recipient.email)
        self.app.refresh_all()

    def move_selected(self, direction: int) -> None:
        ids = self._selected_ids()
        if len(ids) != 1:
            messagebox.showinfo(
                "Wybierz jednego",
                "Zaznacz dokładnie jednego odbiorcę, żeby przesunąć go w kolejce.",
                parent=self.winfo_toplevel(),
            )
            return
        if self.sort_key != "lp" or self.sort_desc:
            self.sort_key, self.sort_desc = "lp", False
        if self.store.move_recipient(ids[0], direction):
            self.refresh()
            self.table.tree.selection_set(str(ids[0]))
            self.table.tree.see(str(ids[0]))

    def sort_by(self, key: str) -> None:
        if key == self.sort_key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = key, False
        self.refresh()

    def export_csv(self) -> None:
        recipients, numery = self._current_rows()
        if not recipients:
            messagebox.showinfo(
                "Pusto", "Nie ma czego wyeksportować.", parent=self.winfo_toplevel()
            )
            return
        path = filedialog.asksaveasfilename(
            title="Zapisz listę odbiorców",
            defaultextension=".csv",
            filetypes=[("Plik CSV", "*.csv")],
            initialfile="odbiorcy.csv",
            parent=self.winfo_toplevel(),
        )
        if not path:
            return
        fields = self.store.list_fields()
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(
                ["Lp", "E-mail"]
                + [f.label for f in fields]
                + ["Grupy", "Status", "Etap", "Próby", "Wysłano", "Odpowiedź", "Błąd"]
            )
            for recipient in recipients:
                writer.writerow(
                    [numery.get(recipient.id, ""), recipient.email]
                    + [recipient.data.get(f.key, "") for f in fields]
                    + [
                        ", ".join(recipient.tags),
                        recipient.status_label,
                        recipient.stage,
                        recipient.attempts,
                        recipient.sent_at or "",
                        recipient.replied_at or "",
                        recipient.last_error or "",
                    ]
                )
        messagebox.showinfo(
            "Zapisano",
            "Wyeksportowano " + str(len(recipients)) + " odbiorców do:\n" + path,
            parent=self.winfo_toplevel(),
        )

    # ------------------------------------------------------------- odświeżanie

    def _current_rows(self):
        """Zwraca (odbiorcy po filtrach i sortowaniu, numer w kolejce wysyłki)."""
        label = self.filter_var.get()
        status = LABEL_TO_STATUS.get(label) if label != FILTER_ALL else None
        tag = "" if self.tag_var.get() == TAG_ALL else self.tag_var.get()
        search = self.search_entry.get()

        numery = {r.id: i for i, r in enumerate(self.store.list_recipients(), start=1)}
        recipients = self.store.list_recipients(status=status, search=search, tag=tag)

        klucze = {
            "lp": lambda r: numery.get(r.id, 0),
            "email": lambda r: r.email.lower(),
            "tags": lambda r: ", ".join(r.tags).lower(),
            "status": lambda r: r.status_label,
            "stage": lambda r: r.stage,
            "info": lambda r: (r.sent_at or r.last_error or ""),
        }
        for field_def in self.store.list_fields():
            klucze[field_def.key] = lambda r, k=field_def.key: (r.data.get(k) or "").lower()
        recipients.sort(key=klucze.get(self.sort_key, klucze["lp"]), reverse=self.sort_desc)
        return recipients, numery

    def refresh(self) -> None:
        if self.table is None:
            return
        self._refresh_tag_menu()
        recipients, numery = self._current_rows()
        field_keys = [f.key for f in self.store.list_fields()]
        kroki = len(self.store.sequence())
        self.table.set_sort_indicator(self.sort_key, self.sort_desc)

        self.table.clear()
        for recipient in recipients:
            index = numery.get(recipient.id, 0)
            info = self._opis(recipient)
            values = [str(index), recipient.email]
            values.extend(recipient.data.get(key, "") for key in field_keys)
            values.extend(
                [
                    ", ".join(recipient.tags),
                    recipient.status_label,
                    str(recipient.stage) + "/" + str(kroki) if kroki else str(recipient.stage),
                    info,
                ]
            )
            tags = [recipient.status]
            if index % 2 == 0:
                tags.append("odd")
            self.table.add_row(str(recipient.id), values, tags=tags)

        counts = self.store.counts()
        self.summary_label.configure(
            text="Pokazano "
            + str(len(recipients))
            + " z "
            + str(counts.get("total", 0))
            + "   |   w kolejce: "
            + str(counts.get(STATUS_PENDING, 0))
            + "   |   zakończeni: "
            + str(counts.get("sent", 0))
            + "   |   odpowiedzieli: "
            + str(counts.get("replied", 0))
            + "   |   odbici: "
            + str(counts.get("bounced", 0))
            + "   |   wypisani: "
            + str(counts.get(STATUS_UNSUBSCRIBED, 0))
            + "   |   błędy: "
            + str(counts.get("error", 0))
        )

    @staticmethod
    def _opis(recipient) -> str:
        if recipient.status == "sent":
            return "Zakończono " + (recipient.sent_at or "")
        if recipient.status == "error":
            return recipient.last_error or "Błąd wysyłki"
        if recipient.status == "replied":
            return "Odpowiedział " + (recipient.replied_at or "")
        if recipient.status == "bounced":
            return "Adres odbił wiadomość"
        if recipient.status == STATUS_UNSUBSCRIBED:
            return "Poprosił o wypisanie - pomijany na stałe"
        if recipient.next_due_at:
            return "Następny krok: " + recipient.next_due_at[:16]
        return ""

    def _refresh_tag_menu(self) -> None:
        wartosci = [TAG_ALL] + self.store.all_tags()
        self.tag_menu.configure(values=wartosci)
        if self.tag_var.get() not in wartosci:
            self.tag_var.set(TAG_ALL)
