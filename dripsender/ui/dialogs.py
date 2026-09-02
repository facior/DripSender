"""Okna modalne: odbiorca, import, walidacja, tagi, pola, podgląd, raport, blokada."""

from __future__ import annotations

import re
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .. import importer, validate
from ..engine import CampaignSummary, SequenceSnapshot, compose, sample_recipient
from ..security import check_app_lock
from ..store import STATUS_SKIPPED, Recipient, Store, Template, valid_email
from . import theme
from .widgets import Card, DataTable, button, entry, textbox

SPLIT_RE = re.compile(r"[\t;,|]")


class ModalDialog(ctk.CTkToplevel):
    """Baza dla okien modalnych: wyśrodkowanie, blokada okna głównego, Esc."""

    def __init__(self, parent, title: str, width: int = 560, height: int = 460) -> None:
        super().__init__(parent, fg_color=theme.BG)
        self.title(title)
        self.resizable(True, True)
        self.minsize(420, 260)
        self.transient(parent.winfo_toplevel())
        self.result = None
        self._center(parent, width, height)
        self.bind("<Escape>", lambda _event: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.after(120, self._grab)

    def _grab(self) -> None:
        try:
            self.grab_set()
            self.lift()
            self.focus_force()
        except Exception:  # noqa: BLE001 - okno mogło już zostać zamknięte
            pass

    def _center(self, parent, width: int, height: int) -> None:
        root = parent.winfo_toplevel()
        root.update_idletasks()
        x = root.winfo_x() + (root.winfo_width() - width) // 2
        y = root.winfo_y() + (root.winfo_height() - height) // 3
        self.geometry(str(width) + "x" + str(height) + "+" + str(max(0, x)) + "+" + str(max(0, y)))

    def _cancel(self) -> None:
        self.result = None
        self.destroy()

    def show(self):
        self.wait_window()
        return self.result

    def warn(self, message: str, title: str = "Uwaga") -> None:
        messagebox.showwarning(title, message, parent=self)


class RecipientDialog(ModalDialog):
    """Dodawanie lub edycja pojedynczego odbiorcy."""

    def __init__(self, parent, store: Store, recipient: Recipient | None = None) -> None:
        self.store = store
        self.recipient = recipient
        self.fields = store.list_fields()
        height = 300 + 62 * len(self.fields)
        super().__init__(
            parent, "Edytuj odbiorcę" if recipient else "Nowy odbiorca", 560, min(height, 660)
        )
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        card = Card(
            self,
            "Dane odbiorcy",
            "Puste pola zostaną zastąpione wartością domyślną z okna Odbiorcy > Pola.",
        )
        card.grid(row=0, column=0, sticky="nsew", padx=16, pady=(16, 8))
        form = card.body

        ctk.CTkLabel(
            form, text="Adres e-mail", font=theme.font(11), text_color=theme.MUTED, anchor="w"
        ).grid(row=0, column=0, sticky="ew")
        self.email_entry = entry(form, "klient@example.com")
        self.email_entry.grid(row=1, column=0, sticky="ew", pady=(2, 10))

        self.field_entries: dict[str, ctk.CTkEntry] = {}
        for index, field_def in enumerate(self.fields):
            row = 2 + index * 2
            ctk.CTkLabel(
                form,
                text=field_def.label + "  {" + field_def.key + "}",
                font=theme.font(11),
                text_color=theme.MUTED,
                anchor="w",
            ).grid(row=row, column=0, sticky="ew")
            widget = entry(form, field_def.fallback or "")
            widget.grid(row=row + 1, column=0, sticky="ew", pady=(2, 10))
            self.field_entries[field_def.key] = widget

        wiersz_tagow = 2 + len(self.fields) * 2
        ctk.CTkLabel(
            form, text="Grupy (po przecinku)", font=theme.font(11), text_color=theme.MUTED,
            anchor="w",
        ).grid(row=wiersz_tagow, column=0, sticky="ew")
        self.tags_entry = entry(form, "np. hurtownie, śląskie")
        self.tags_entry.grid(row=wiersz_tagow + 1, column=0, sticky="ew", pady=(2, 10))

        if recipient:
            self.email_entry.insert(0, recipient.email)
            for key, widget in self.field_entries.items():
                widget.insert(0, recipient.data.get(key, ""))
            self.tags_entry.insert(0, ", ".join(recipient.tags))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        actions.grid_columnconfigure(0, weight=1)
        button(actions, "Anuluj", self._cancel, kind="ghost", width=110).grid(
            row=0, column=1, padx=(0, 8)
        )
        button(actions, "Zapisz", self._save, width=110).grid(row=0, column=2)

        self.email_entry.focus_set()
        self.bind("<Return>", lambda _event: self._save())

    def _save(self) -> None:
        email = self.email_entry.get().strip()
        if not valid_email(email):
            self.warn("Podaj poprawny adres e-mail.")
            return
        data = {key: widget.get().strip() for key, widget in self.field_entries.items()}
        tagi = [t.strip() for t in self.tags_entry.get().split(",") if t.strip()]
        try:
            if self.recipient:
                self.store.update_recipient(self.recipient.id, email, data)
                self.store.set_tags([self.recipient.id], tagi)
            else:
                self.store.add_recipient(email, data, tagi)
        except ValueError as exc:
            self.warn(str(exc))
            return
        self.result = True
        self.destroy()


class BulkAddDialog(ModalDialog):
    """Wklejanie wielu odbiorców naraz."""

    def __init__(self, parent, store: Store) -> None:
        self.store = store
        self.fields = store.list_fields()
        super().__init__(parent, "Dodaj wielu odbiorców", 720, 640)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        order = " ; ".join(["email"] + [f.key for f in self.fields])
        card = Card(
            self,
            "Wklej listę",
            "Jeden odbiorca w każdej linii. Kolejność kolumn:  "
            + order
            + "\nRozdzielaj średnikiem, przecinkiem lub tabulatorem. "
            "Sam adres e-mail w linii też wystarczy.",
        )
        card.grid(row=0, column=0, sticky="nsew", padx=16, pady=(16, 8))
        card.body.grid_rowconfigure(0, weight=1)

        self.input = textbox(card.body)
        self.input.grid(row=0, column=0, sticky="nsew")

        tagi = ctk.CTkFrame(card.body, fg_color="transparent")
        tagi.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        tagi.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            tagi, text="Przypisz do grup", font=theme.font(11), text_color=theme.MUTED,
            width=140, anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.tags_entry = entry(tagi, "opcjonalnie, po przecinku")
        self.tags_entry.grid(row=0, column=1, sticky="ew")

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        actions.grid_columnconfigure(0, weight=1)
        button(actions, "Anuluj", self._cancel, kind="ghost", width=110).grid(
            row=0, column=1, padx=(0, 8)
        )
        button(actions, "Dodaj do listy", self._save, width=140).grid(row=0, column=2)
        self.input.focus_set()

    def _save(self) -> None:
        raw = self.input.get("1.0", "end").strip()
        if not raw:
            self.warn("Wklej najpierw adresy.")
            return
        keys = [f.key for f in self.fields]
        entries: list[tuple[str, dict[str, str]]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [part.strip() for part in SPLIT_RE.split(line)]
            data = {key: (parts[i + 1] if i + 1 < len(parts) else "") for i, key in enumerate(keys)}
            entries.append((parts[0], data))

        tagi = [t.strip() for t in self.tags_entry.get().split(",") if t.strip()]
        result = self.store.add_many(entries, tagi)
        summary = "Dodano: " + str(len(result["added"]))
        if result["duplicate"]:
            summary += "\nPominięto duplikaty: " + str(len(result["duplicate"]))
        if result["invalid"]:
            preview = ", ".join(result["invalid"][:5])
            summary += "\nBłędne adresy: " + str(len(result["invalid"])) + " (" + preview + ")"
        messagebox.showinfo("Import zakończony", summary, parent=self)
        self.result = len(result["added"])
        self.destroy()


class ImportDialog(ModalDialog):
    """Wczytanie listy z pliku CSV lub Excela z mapowaniem kolumn."""

    BRAK = "— nie importuj —"

    def __init__(self, parent, store: Store) -> None:
        self.store = store
        self.fields = store.list_fields()
        self.arkusz = None
        super().__init__(parent, "Wczytaj listę z pliku", 860, 660)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        gora = Card(
            self,
            "Plik z listą",
            "Obsługiwane formaty: CSV i Excel (.xlsx). Program sam rozpozna separator "
            "i spróbuje dopasować kolumny.",
        )
        gora.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        gora.body.grid_columnconfigure(1, weight=1)

        button(gora.body, "Wybierz plik", self.pick_file, width=140).grid(
            row=0, column=0, padx=(0, 12)
        )
        self.file_label = ctk.CTkLabel(
            gora.body, text="Nie wybrano pliku.", font=theme.font(11),
            text_color=theme.MUTED, anchor="w",
        )
        self.file_label.grid(row=0, column=1, sticky="ew")

        self.header_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            gora.body,
            text="Pierwszy wiersz to nagłówki",
            variable=self.header_var,
            command=self._reload,
            font=theme.font(11),
            text_color=theme.MUTED,
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=4,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            border_color=theme.BORDER,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))

        self.dol = Card(self, "Podgląd i przypisanie kolumn")
        self.dol.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 8))
        self.dol.body.grid_rowconfigure(1, weight=1)
        self.dol.body.grid_columnconfigure(0, weight=1)

        self.mapping_frame = ctk.CTkFrame(self.dol.body, fg_color="transparent")
        self.mapping_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        self.preview = DataTable(self.dol.body, [("info", "Podgląd", 700)])
        self.preview.grid(row=1, column=0, sticky="nsew")

        tagi = ctk.CTkFrame(self.dol.body, fg_color="transparent")
        tagi.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        tagi.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            tagi, text="Przypisz do grup", font=theme.font(11), text_color=theme.MUTED,
            width=140, anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.tags_entry = entry(tagi, "opcjonalnie, po przecinku")
        self.tags_entry.grid(row=0, column=1, sticky="ew")

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))
        actions.grid_columnconfigure(0, weight=1)
        button(actions, "Anuluj", self._cancel, kind="ghost", width=110).grid(
            row=0, column=1, padx=(0, 8)
        )
        self.import_button = button(actions, "Importuj", self._import, width=130)
        self.import_button.grid(row=0, column=2)
        self.import_button.configure(state="disabled")

    def pick_file(self) -> None:
        typy = [("Wszystkie obsługiwane", "*.csv *.xlsx *.xlsm"), ("CSV", "*.csv")]
        if importer.excel_available():
            typy.append(("Excel", "*.xlsx *.xlsm"))
        path = filedialog.askopenfilename(title="Wybierz plik z listą", filetypes=typy, parent=self)
        if not path:
            return
        self.path = path
        self._reload()

    def _reload(self) -> None:
        if not getattr(self, "path", ""):
            return
        try:
            self.arkusz = importer.wczytaj(self.path, self.header_var.get())
        except ValueError as exc:
            self.warn(str(exc), "Nie udało się wczytać")
            self.arkusz = None
            self.import_button.configure(state="disabled")
            return
        self.file_label.configure(
            text=self.arkusz.zrodlo + "   ·   wierszy: " + str(len(self.arkusz.wiersze))
        )
        self._build_mapping()
        self._build_preview()
        self.import_button.configure(state="normal")

    def _build_mapping(self) -> None:
        for child in self.mapping_frame.winfo_children():
            child.destroy()
        if self.arkusz is None:
            return
        zgadniete = self.arkusz.zgadnij_mapowanie([f.key for f in self.fields])
        wybory = [self.BRAK] + [
            str(i + 1) + ". " + h for i, h in enumerate(self.arkusz.naglowki)
        ]
        self.mapping_vars: dict[str, ctk.StringVar] = {}

        docelowe = [("email", "Adres e-mail (wymagane)")] + [
            (f.key, f.label) for f in self.fields
        ]
        for index, (klucz, etykieta) in enumerate(docelowe):
            kolumna = index % 3
            wiersz = index // 3
            ramka = ctk.CTkFrame(self.mapping_frame, fg_color="transparent")
            ramka.grid(row=wiersz, column=kolumna, sticky="ew", padx=(0, 16), pady=4)
            ctk.CTkLabel(
                ramka, text=etykieta, font=theme.font(11), text_color=theme.MUTED, anchor="w"
            ).grid(row=0, column=0, sticky="w")
            wskazana = zgadniete.get(klucz)
            var = ctk.StringVar(
                value=wybory[wskazana + 1] if wskazana is not None else self.BRAK
            )
            ctk.CTkOptionMenu(
                ramka,
                values=wybory,
                variable=var,
                width=200,
                height=32,
                corner_radius=8,
                fg_color=theme.SURFACE_HI,
                button_color=theme.BORDER,
                button_hover_color=theme.ACCENT,
                text_color=theme.TEXT,
                font=theme.font(11),
            ).grid(row=1, column=0, sticky="ew", pady=(2, 0))
            self.mapping_vars[klucz] = var

    def _build_preview(self) -> None:
        if self.arkusz is None:
            return
        self.preview.destroy()
        kolumny = [
            (str(i), naglowek[:22], 150) for i, naglowek in enumerate(self.arkusz.naglowki)
        ]
        self.preview = DataTable(self.dol.body, kolumny, horizontal_scroll=True)
        self.preview.grid(row=1, column=0, sticky="nsew")
        self.preview.tree.configure(height=6)
        for index, wiersz in enumerate(self.arkusz.podglad):
            self.preview.add_row(
                str(index), wiersz, tags=("odd",) if index % 2 else ()
            )

    def _mapowanie(self) -> dict[str, int]:
        wynik: dict[str, int] = {}
        for klucz, var in self.mapping_vars.items():
            wartosc = var.get()
            if wartosc == self.BRAK:
                continue
            try:
                wynik[klucz] = int(wartosc.split(".")[0]) - 1
            except ValueError:
                continue
        return wynik

    def _import(self) -> None:
        if self.arkusz is None:
            return
        mapowanie = self._mapowanie()
        if "email" not in mapowanie:
            self.warn("Wskaż kolumnę z adresem e-mail.")
            return
        wpisy = importer.na_odbiorcow(self.arkusz, mapowanie, [f.key for f in self.fields])
        tagi = [t.strip() for t in self.tags_entry.get().split(",") if t.strip()]
        wynik = self.store.add_many(wpisy, tagi)

        podsumowanie = "Dodano: " + str(len(wynik["added"]))
        if wynik["duplicate"]:
            podsumowanie += "\nPominięto duplikaty: " + str(len(wynik["duplicate"]))
        if wynik["invalid"]:
            podglad = ", ".join(wynik["invalid"][:5])
            podsumowanie += (
                "\nBłędne adresy: " + str(len(wynik["invalid"])) + " (" + podglad + ")"
            )
        messagebox.showinfo("Import zakończony", podsumowanie, parent=self)
        self.result = len(wynik["added"])
        self.destroy()


class ValidateDialog(ModalDialog):
    """Sprawdzenie listy: literówki, adresy ogólne, martwe domeny."""

    def __init__(self, parent, store: Store) -> None:
        self.store = store
        self.raport = None
        super().__init__(parent, "Sprawdzenie listy", 900, 620)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        card = Card(
            self,
            "Co może się zepsuć przy wysyłce",
            "Literówki i martwe domeny kończą się odbiciami, które psują reputację "
            "skrzynki. Adresy ogólne rzadziej dostają odpowiedź.",
        )
        card.grid(row=0, column=0, sticky="nsew", padx=16, pady=(16, 8))
        card.body.grid_rowconfigure(1, weight=1)

        self.status_label = ctk.CTkLabel(
            card.body, text="Sprawdzam...", font=theme.font(12), text_color=theme.ACCENT,
            anchor="w",
        )
        self.status_label.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        self.table = DataTable(
            card.body,
            [
                ("poziom", "Waga", 110),
                ("email", "Adres", 260),
                ("opis", "Co jest nie tak", 260),
                ("podpowiedz", "Podpowiedź", 300),
            ],
            horizontal_scroll=True,
        )
        self.table.grid(row=1, column=0, sticky="nsew")

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        actions.grid_columnconfigure(2, weight=1)
        self.delete_button = button(
            actions, "Usuń zaznaczone", self.delete_selected, kind="danger", width=160
        )
        self.delete_button.grid(row=0, column=0, padx=(0, 8))
        self.skip_button = button(
            actions, "Pomiń w wysyłce", self.skip_selected, kind="ghost", width=150
        )
        self.skip_button.grid(row=0, column=1)
        button(actions, "Zamknij", self.destroy, kind="ghost", width=110).grid(row=0, column=3)

        self.after(200, self._start)

    def _start(self) -> None:
        recipients = self.store.list_recipients()
        if not recipients:
            self.status_label.configure(text="Lista jest pusta.", text_color=theme.MUTED)
            return

        def do_gui(callback) -> None:
            """Okno mogło już zostać zamknięte w trakcie skanowania DNS."""
            try:
                if self.winfo_exists():
                    self.after(0, callback)
            except Exception:  # noqa: BLE001 - Tk zniknął spod wątku
                pass

        def postep(numer: int, ile: int) -> None:
            do_gui(
                lambda: self.status_label.configure(
                    text="Sprawdzam domeny w DNS: " + str(numer) + " z " + str(ile) + "..."
                )
            )

        def worker() -> None:
            raport = validate.sprawdz(recipients, sprawdzaj_dns=True, postep=postep)
            do_gui(lambda: self._done(raport))

        threading.Thread(target=worker, name="validate", daemon=True).start()

    def _done(self, raport) -> None:
        self.raport = raport
        kolor = theme.OK if not raport.uwagi else theme.WARN
        self.status_label.configure(text=raport.podsumowanie(), text_color=kolor)
        self.table.clear()
        for index, uwaga in enumerate(raport.uwagi):
            tag = "error" if uwaga.poziom == validate.POZIOM_BLAD else "skipped"
            self.table.add_row(
                str(uwaga.recipient_id) + ":" + str(index),
                [
                    "do poprawy" if uwaga.poziom == validate.POZIOM_BLAD else "do rozważenia",
                    uwaga.email,
                    uwaga.opis,
                    uwaga.podpowiedz,
                ],
                tags=(tag,),
            )
        if not validate.dns_available():
            self.status_label.configure(
                text=raport.podsumowanie() + " (biblioteka DNS niedostępna)"
            )

    def _zaznaczone_id(self) -> list[int]:
        return sorted({int(v.split(":")[0]) for v in self.table.selected_ids()})

    def delete_selected(self) -> None:
        ids = self._zaznaczone_id()
        if not ids:
            self.warn("Zaznacz wiersze, których dotyczy akcja.")
            return
        if not messagebox.askyesno(
            "Usunąć odbiorców?",
            "Usunąć z listy " + str(len(ids)) + " odbiorców?",
            parent=self,
        ):
            return
        self.store.delete_recipients(ids)
        self.result = True
        self.destroy()

    def skip_selected(self) -> None:
        ids = self._zaznaczone_id()
        if not ids:
            self.warn("Zaznacz wiersze, których dotyczy akcja.")
            return
        self.store.set_status(ids, STATUS_SKIPPED)
        self.result = True
        self.destroy()


class TagsDialog(ModalDialog):
    """Przypisywanie grup zaznaczonym odbiorcom."""

    def __init__(self, parent, store: Store, ids: list[int]) -> None:
        self.store = store
        self.ids = ids
        super().__init__(parent, "Grupy odbiorców", 560, 460)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        card = Card(
            self,
            "Grupy dla " + str(len(ids)) + " zaznaczonych",
            "Grupa pozwala wysłać kampanię tylko do części listy - wybierzesz ją "
            "na pulpicie kampanii.",
        )
        card.grid(row=0, column=0, sticky="nsew", padx=16, pady=(16, 8))
        card.body.grid_rowconfigure(1, weight=1)

        dodaj = ctk.CTkFrame(card.body, fg_color="transparent")
        dodaj.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        dodaj.grid_columnconfigure(0, weight=1)
        self.tag_entry = entry(dodaj, "nazwa grupy")
        self.tag_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        button(dodaj, "Przypisz", self._add, width=110).grid(row=0, column=1)

        self.table = DataTable(
            card.body, [("tag", "Istniejące grupy", 300), ("ile", "Odbiorców", 120)],
            selectmode="browse",
        )
        self.table.grid(row=1, column=0, sticky="nsew")

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        actions.grid_columnconfigure(2, weight=1)
        button(actions, "Przypisz zaznaczoną", self._add_selected, width=180).grid(
            row=0, column=0, padx=(0, 8)
        )
        button(actions, "Odepnij zaznaczoną", self._remove_selected, kind="ghost", width=170).grid(
            row=0, column=1
        )
        button(actions, "Zamknij", self.destroy, kind="ghost", width=110).grid(row=0, column=3)

        self._refresh()

    def _refresh(self) -> None:
        self.table.clear()
        wszystkie = self.store.all_tags()
        for index, tag in enumerate(wszystkie):
            ile = len(self.store.list_recipients(tag=tag))
            self.table.add_row(tag, [tag, str(ile)], tags=("odd",) if index % 2 else ())

    def _add(self) -> None:
        tag = self.tag_entry.get().strip()
        if not tag:
            self.warn("Wpisz nazwę grupy.")
            return
        self.store.add_tag(self.ids, tag)
        self.tag_entry.delete(0, "end")
        self.result = True
        self._refresh()

    def _add_selected(self) -> None:
        wybrane = self.table.selected_ids()
        if not wybrane:
            self.warn("Zaznacz grupę na liście.")
            return
        self.store.add_tag(self.ids, wybrane[0])
        self.result = True
        self._refresh()

    def _remove_selected(self) -> None:
        wybrane = self.table.selected_ids()
        if not wybrane:
            self.warn("Zaznacz grupę na liście.")
            return
        self.store.remove_tag(self.ids, wybrane[0])
        self.result = True
        self._refresh()


class FieldsDialog(ModalDialog):
    """Zarządzanie polami personalizacji."""

    def __init__(self, parent, store: Store) -> None:
        self.store = store
        super().__init__(parent, "Pola personalizacji", 720, 560)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        card = Card(
            self,
            "Pola dostępne w szablonie",
            "Każde pole tworzy znacznik {klucz}, który podmienia się na dane odbiorcy. "
            "Wartość domyślna wskakuje tam, gdzie odbiorca ma puste pole.",
        )
        card.grid(row=0, column=0, sticky="nsew", padx=16, pady=(16, 8))
        card.body.grid_rowconfigure(0, weight=1)

        self.table = DataTable(
            card.body,
            [("key", "Znacznik", 150), ("label", "Nazwa", 200), ("fallback", "Domyślnie", 200)],
        )
        self.table.grid(row=0, column=0, sticky="nsew")

        form = ctk.CTkFrame(card.body, fg_color="transparent")
        form.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        for column in range(3):
            form.grid_columnconfigure(column, weight=1)
        self.key_entry = entry(form, "np. miasto")
        self.key_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.label_entry = entry(form, "Nazwa widoczna, np. Miasto")
        self.label_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.fallback_entry = entry(form, "Wartość domyślna")
        self.fallback_entry.grid(row=0, column=2, sticky="ew")

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        actions.grid_columnconfigure(2, weight=1)
        button(actions, "Dodaj pole", self._add, width=120).grid(row=0, column=0, padx=(0, 8))
        button(actions, "Usuń zaznaczone", self._remove, kind="danger", width=150).grid(
            row=0, column=1, padx=(0, 8)
        )
        button(actions, "Zamknij", self.destroy, kind="ghost", width=110).grid(row=0, column=3)

        self._refresh()

    def _refresh(self) -> None:
        self.table.clear()
        for index, field_def in enumerate(self.store.list_fields()):
            self.table.add_row(
                field_def.key,
                ["{" + field_def.key + "}", field_def.label, field_def.fallback or "-"],
                tags=("odd",) if index % 2 else (),
            )

    def _add(self) -> None:
        try:
            self.store.add_field(
                self.key_entry.get(), self.label_entry.get(), self.fallback_entry.get().strip()
            )
        except ValueError as exc:
            self.warn(str(exc))
            return
        for widget in (self.key_entry, self.label_entry, self.fallback_entry):
            widget.delete(0, "end")
        self.result = True
        self._refresh()

    def _remove(self) -> None:
        selected = self.table.selected_ids()
        if not selected:
            self.warn("Zaznacz pole do usunięcia.")
            return
        if not messagebox.askyesno(
            "Usunąć pole?",
            "Usunięcie pola skasuje jego wartości u wszystkich odbiorców. Kontynuować?",
            parent=self,
        ):
            return
        for key in selected:
            self.store.remove_field(key)
        self.result = True
        self._refresh()


class PreviewDialog(ModalDialog):
    """Podgląd wiadomości po podstawieniu danych odbiorcy."""

    def __init__(
        self, parent, store: Store, recipient: Recipient | None, step: Template
    ) -> None:
        super().__init__(parent, "Podgląd wiadomości", 720, 620)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        if recipient:
            header = "Podgląd kroku '" + step.name + "' dla: " + recipient.email
        else:
            recipient = sample_recipient(store)
            header = "Lista jest pusta - podgląd na danych przykładowych"

        subject, body, _ = compose(
            step, store, recipient, "", SequenceSnapshot.from_store(store)
        )

        card = Card(self, header, "Temat: " + subject)
        card.grid(row=0, column=0, sticky="nsew", padx=16, pady=(16, 8))
        card.body.grid_rowconfigure(0, weight=1)
        view = textbox(card.body)
        view.grid(row=0, column=0, sticky="nsew")
        view.insert("1.0", body)
        view.configure(state="disabled")

        button(self, "Zamknij", self.destroy, kind="ghost", width=110).grid(
            row=1, column=0, sticky="e", padx=16, pady=(0, 16)
        )


class ReportDialog(ModalDialog):
    """Podsumowanie zakończonej kampanii."""

    def __init__(self, parent, summary: CampaignSummary) -> None:
        super().__init__(parent, "Raport kampanii", 560, 420)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        card = Card(self, "Kampania zakończona", summary.reason)
        card.grid(row=0, column=0, sticky="nsew", padx=16, pady=(16, 8))

        rows = [
            ("Wysłane w tej sesji", str(summary.sent), theme.OK),
            ("Błędy", str(summary.errors), theme.ERR if summary.errors else theme.MUTED),
            ("Pozostało w kolejce", str(summary.remaining), theme.TEXT),
            ("Start", summary.started_at or "-", theme.MUTED),
            ("Koniec", summary.finished_at or "-", theme.MUTED),
        ]
        card.body.grid_columnconfigure(0, weight=0)
        card.body.grid_columnconfigure(1, weight=1)
        for index, (label, value, color) in enumerate(rows):
            ctk.CTkLabel(
                card.body, text=label, font=theme.font(12), text_color=theme.MUTED, anchor="w"
            ).grid(row=index, column=0, sticky="w", pady=6)
            ctk.CTkLabel(
                card.body, text=value, font=theme.font(13, "bold"), text_color=color, anchor="e"
            ).grid(row=index, column=1, sticky="e", pady=6)

        button(self, "Zamknij", self.destroy, width=110).grid(
            row=1, column=0, sticky="e", padx=16, pady=(0, 16)
        )


class LockDialog(ModalDialog):
    """Pytanie o PIN przy starcie programu."""

    def __init__(self, parent, store: Store) -> None:
        self.store = store
        self.proby = 0
        super().__init__(parent, "Dostęp do programu", 460, 320)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.protocol("WM_DELETE_WINDOW", self._odmowa)
        self.bind("<Escape>", lambda _e: self._odmowa())

        card = Card(
            self,
            "Program jest zablokowany",
            "Lista klientów to dane osobowe - podaj PIN, aby otworzyć program.",
        )
        card.grid(row=0, column=0, sticky="nsew", padx=16, pady=(16, 8))

        self.pin_entry = entry(card.body, "PIN", show="*")
        self.pin_entry.grid(row=0, column=0, sticky="ew", pady=(6, 6))
        self.pin_entry.bind("<Return>", lambda _e: self._sprawdz())

        self.info = ctk.CTkLabel(
            card.body, text="", font=theme.font(11), text_color=theme.ERR, anchor="w"
        )
        self.info.grid(row=1, column=0, sticky="ew")

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        actions.grid_columnconfigure(0, weight=1)
        button(actions, "Zamknij program", self._odmowa, kind="ghost", width=150).grid(
            row=0, column=1, padx=(0, 8)
        )
        button(actions, "Otwórz", self._sprawdz, width=110).grid(row=0, column=2)
        self.after(200, lambda: self.pin_entry.focus_force())

    def _sprawdz(self) -> None:
        if check_app_lock(self.store, self.pin_entry.get()):
            self.result = True
            self.destroy()
            return
        self.proby += 1
        self.pin_entry.delete(0, "end")
        self.info.configure(text="Nieprawidłowy PIN. Próba " + str(self.proby) + ".")

    def _odmowa(self) -> None:
        self.result = False
        self.destroy()
