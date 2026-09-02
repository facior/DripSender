"""Sekwencja wiadomości: pierwsza wiadomość i follow-upy, każdy z własnym szablonem."""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..engine import SequenceSnapshot, compose, load_smtp_config, sample_recipient
from ..mailer import Mailer, MailerError, placeholders_in, unknown_placeholders
from ..store import now_iso
from . import theme
from .dialogs import PreviewDialog
from .widgets import Card, button, entry, textbox

HTML_ZNACZNIKI = [
    ("B", "<b>", "</b>", "pogrubienie"),
    ("I", "<i>", "</i>", "kursywa"),
    ("Link", '<a href="https://">', "</a>", "odnośnik"),
    ("¶", "<p>", "</p>", "akapit"),
    ("↵", "<br>", "", "złamanie wiersza"),
]


class SequenceView(ctk.CTkScrollableFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.store = app.store
        self._last_focus = None
        self.current_id: int | None = None

        self.grid_columnconfigure(0, weight=1)

        self._build_steps_card()
        self._build_editor_card()
        self.refresh()
        self._parent_canvas.bind("<Configure>", self._dopasuj_pole_tresci, add="+")

    def _dopasuj_pole_tresci(self, _event=None) -> None:
        """Pole treści bierze tyle wysokości, ile zostaje po reszcie zawartości."""
        try:
            widok = self._parent_canvas.winfo_height()
            biezaca = self.body_text.winfo_height()
            calosc = self.card.winfo_y() + self.card.winfo_height()
        except Exception:  # noqa: BLE001 - widget mógł już zniknąć
            return
        if widok < 200 or biezaca < 10:
            return
        stale = calosc - biezaca
        nowa = max(110, widok - stale - 10)
        if abs(nowa - biezaca) > 10:
            self.body_text.configure(height=nowa)

    # ------------------------------------------------------------ lista kroków

    def _build_steps_card(self) -> None:
        """Kroki jako pasek przycisków - tabela zabierała za dużo miejsca edytorowi."""
        card = Card(
            self,
            "Sekwencja",
            "Kroki wychodzą po kolei. Odbiorca, który odpisze albo się wypisze, "
            "wypada z dalszych kroków.",
        )
        card.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        self.steps_strip = ctk.CTkFrame(body, fg_color="transparent", height=1)
        self.steps_strip.grid(row=0, column=0, sticky="ew")

        bar = ctk.CTkFrame(body, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        bar.grid_columnconfigure(4, weight=1)
        button(bar, "Dodaj krok", self.add_step, width=115, height=30).grid(
            row=0, column=0, padx=(0, 8)
        )
        button(bar, "Włącz / wyłącz", self.toggle_step, kind="ghost", width=135, height=30).grid(
            row=0, column=1, padx=(0, 8)
        )
        button(bar, "▲", lambda: self.move_step(-1), kind="ghost", width=40, height=30).grid(
            row=0, column=2, padx=(0, 4)
        )
        button(bar, "▼", lambda: self.move_step(1), kind="ghost", width=40, height=30).grid(
            row=0, column=3, padx=(0, 8)
        )
        button(bar, "Usuń krok", self.delete_step, kind="danger", width=105, height=30).grid(
            row=0, column=5
        )

    # ---------------------------------------------------------------- edytor

    def _build_editor_card(self) -> None:
        self.card = Card(self, "Treść kroku")
        self.card.grid(row=1, column=0, sticky="ew")
        body = self.card.body

        head = ctk.CTkFrame(body, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            head, text="Nazwa kroku", font=theme.font(11), text_color=theme.MUTED, width=110,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.name_entry = entry(head, "np. Przypomnienie po tygodniu")
        self.name_entry.grid(row=0, column=1, sticky="ew", padx=(0, 16))
        ctk.CTkLabel(
            head, text="Wyślij po (dni)", font=theme.font(11), text_color=theme.MUTED,
            anchor="w",
        ).grid(row=0, column=2, padx=(0, 8))
        self.delay_entry = entry(head, "4", width=70)
        self.delay_entry.grid(row=0, column=3)

        temat_head = ctk.CTkFrame(body, fg_color="transparent")
        temat_head.grid(row=2, column=0, sticky="ew")
        temat_head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            temat_head, text="Temat", font=theme.font(11), text_color=theme.MUTED, anchor="w"
        ).grid(row=0, column=0, sticky="w")
        self.chips = ctk.CTkFrame(temat_head, fg_color="transparent")
        self.chips.grid(row=0, column=1, sticky="e")
        self.subject_entry = entry(body, "Temat wiadomości")
        self.subject_entry.grid(row=3, column=0, sticky="ew", pady=(2, 10))
        self.subject_entry.bind("<FocusIn>", lambda _e: self._remember(self.subject_entry))

        tresc_head = ctk.CTkFrame(body, fg_color="transparent")
        tresc_head.grid(row=4, column=0, sticky="ew")
        tresc_head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            tresc_head, text="Treść", font=theme.font(11), text_color=theme.MUTED, anchor="w"
        ).grid(row=0, column=0, sticky="w")

        self.html_toolbar = ctk.CTkFrame(tresc_head, fg_color="transparent")
        self.html_toolbar.grid(row=0, column=1, sticky="e", padx=(0, 12))
        for index, (etykieta, otwarcie, zamkniecie, opis) in enumerate(HTML_ZNACZNIKI):
            button(
                self.html_toolbar,
                etykieta,
                lambda o=otwarcie, z=zamkniecie: self._wrap_selection(o, z),
                kind="ghost",
                width=46,
                height=26,
            ).grid(row=0, column=index, padx=(0, 4))

        self.html_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            tresc_head,
            text="HTML (dla zaawansowanych)",
            variable=self.html_var,
            command=self._toggle_html,
            font=theme.font(11),
            text_color=theme.MUTED,
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=4,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            border_color=theme.BORDER,
        ).grid(row=0, column=2, sticky="e")

        # Wysokość dopasowuje się do okna w _dopasuj_pole_tresci(): w przewijanym
        # widoku waga wiersza nic nie daje, a sztywna wartość albo marnuje miejsce
        # na dużym ekranie, albo spycha przyciski poza widok na małym.
        self.body_text = textbox(body, height=140)
        self.body_text.grid(row=5, column=0, sticky="ew", pady=(2, 10))
        self.body_text.bind("<FocusIn>", lambda _e: self._remember(self.body_text))

        self._build_attachments(body)

        self.warning_label = ctk.CTkLabel(
            body, text="", font=theme.font(11), text_color=theme.WARN, anchor="w", justify="left"
        )
        self.warning_label.grid(row=7, column=0, sticky="ew", pady=(10, 0))

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=8, column=0, sticky="ew", pady=(12, 0))
        actions.grid_columnconfigure(3, weight=1)
        button(actions, "Zapisz krok", self.save_and_confirm, width=130).grid(
            row=0, column=0, padx=(0, 8)
        )
        button(actions, "Podgląd", self.preview, kind="ghost", width=110).grid(
            row=0, column=1, padx=(0, 8)
        )
        button(actions, "Wyślij test do siebie", self.send_test, kind="ghost", width=180).grid(
            row=0, column=2
        )
        button(
            actions,
            "Jak działają znaczniki?",
            lambda: self.app.go_to("guide"),
            kind="ghost",
            width=190,
        ).grid(row=0, column=4)

    def _build_attachments(self, parent) -> None:
        wrapper = ctk.CTkFrame(parent, fg_color="transparent")
        wrapper.grid(row=6, column=0, sticky="ew")
        wrapper.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(wrapper, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            head, text="Załączniki", font=theme.font(11), text_color=theme.MUTED, anchor="w"
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.attachments_summary = ctk.CTkLabel(
            head, text="brak", font=theme.font(11), text_color=theme.MUTED, anchor="w"
        )
        self.attachments_summary.grid(row=0, column=1, sticky="w")
        button(head, "Dodaj plik", self.add_attachment, kind="ghost", width=105, height=30).grid(
            row=0, column=2, sticky="e"
        )

        # height=1: pusta CTkFrame domyślnie żąda 200 px i wypychała pole treści.
        self.attachments_frame = ctk.CTkFrame(wrapper, fg_color="transparent", height=1)
        self.attachments_frame.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.attachments_frame.grid_columnconfigure(0, weight=1)

    # ------------------------------------------------------------- pomocnicze

    def _remember(self, widget) -> None:
        self._last_focus = widget

    def _insert_placeholder(self, key: str) -> None:
        token = "{" + key + "}"
        target = self._last_focus or self.body_text
        try:
            target.insert("insert", token)
        except Exception:  # noqa: BLE001 - CTkEntry używa indeksów liczbowych
            target.insert(len(target.get()), token)
        target.focus_set()

    def _wrap_selection(self, otwarcie: str, zamkniecie: str) -> None:
        """Otacza zaznaczony tekst znacznikiem HTML albo wstawia sam znacznik."""
        pole = self.body_text
        try:
            zaznaczone = pole.get("sel.first", "sel.last")
        except Exception:  # noqa: BLE001 - brak zaznaczenia
            zaznaczone = ""
        if zaznaczone:
            pole.delete("sel.first", "sel.last")
            pole.insert("insert", otwarcie + zaznaczone + zamkniecie)
        else:
            pole.insert("insert", otwarcie + zamkniecie)
        pole.focus_set()

    def _toggle_html(self) -> None:
        self._update_html_toolbar()
        self.save()

    def _update_html_toolbar(self) -> None:
        if self.html_var.get():
            self.html_toolbar.grid()
        else:
            self.html_toolbar.grid_remove()

    def _known_keys(self) -> list[str]:
        return ["email"] + self.store.field_keys()

    def _selected_id(self) -> int | None:
        return self.current_id

    def select_step(self, template_id: int) -> None:
        if template_id == self.current_id:
            return
        self.save()
        self.current_id = template_id
        self.refresh_steps()
        self.load_step()

    # ---------------------------------------------------------------- kroki

    def add_step(self) -> None:
        self.save()
        numer = len(self.store.list_templates()) + 1
        nowy = self.store.add_template("Krok " + str(numer), delay_days=3)
        self.current_id = nowy
        self.refresh()

    def delete_step(self) -> None:
        wybrany = self._selected_id()
        if wybrany is None:
            return
        krok = self.store.get_template(wybrany)
        if not messagebox.askyesno(
            "Usunąć krok?",
            "Usunąć krok '" + (krok.name if krok else "") + "' z sekwencji?",
            parent=self.winfo_toplevel(),
        ):
            return
        if not self.store.delete_template(wybrany):
            messagebox.showinfo(
                "Nie można usunąć",
                "Sekwencja musi mieć co najmniej jeden krok.",
                parent=self.winfo_toplevel(),
            )
            return
        self.current_id = None
        self.refresh()

    def toggle_step(self) -> None:
        wybrany = self._selected_id()
        if wybrany is None:
            return
        krok = self.store.get_template(wybrany)
        if krok:
            self.store.update_template(wybrany, active=not krok.active)
            self.refresh()

    def move_step(self, direction: int) -> None:
        wybrany = self._selected_id()
        if wybrany is None:
            return
        if self.store.move_template(wybrany, direction):
            self.refresh()

    # --------------------------------------------------------- zapis i odczyt

    def save(self) -> None:
        """Zapisuje aktualnie otwarty krok."""
        if self.current_id is None:
            return
        if self.store.get_template(self.current_id) is None:
            return
        self.store.update_template(
            self.current_id,
            name=self.name_entry.get().strip() or "Krok",
            subject=self.subject_entry.get(),
            body=self.body_text.get("1.0", "end-1c"),
            is_html=self.html_var.get(),
            delay_days=_jako_int(self.delay_entry.get(), 0),
        )
        self._update_warning()

    def save_and_confirm(self) -> None:
        self.save()
        self.refresh_steps()
        messagebox.showinfo("Zapisano", "Krok został zapisany.", parent=self.winfo_toplevel())

    def load_step(self) -> None:
        krok = self.store.get_template(self.current_id) if self.current_id else None
        if krok is None:
            return
        self.card.configure()
        self.name_entry.delete(0, "end")
        self.name_entry.insert(0, krok.name)
        self.delay_entry.delete(0, "end")
        self.delay_entry.insert(0, str(krok.delay_days))
        self.subject_entry.delete(0, "end")
        self.subject_entry.insert(0, krok.subject)
        self.body_text.delete("1.0", "end")
        self.body_text.insert("1.0", krok.body)
        self.html_var.set(krok.is_html)
        self._update_html_toolbar()
        self.refresh_attachments()
        self._update_warning()

        pierwszy = self.store.list_templates()[0].id if self.store.list_templates() else None
        self.delay_entry.configure(state="disabled" if krok.id == pierwszy else "normal")

    # ------------------------------------------------------------ załączniki

    def add_attachment(self) -> None:
        if self.current_id is None:
            return
        paths = filedialog.askopenfilenames(
            title="Wybierz załączniki", parent=self.winfo_toplevel()
        )
        if not paths:
            return
        krok = self.store.get_template(self.current_id)
        biezace = list(krok.attachments) if krok else []
        for path in paths:
            if path not in biezace:
                biezace.append(path)
        self.store.update_template(self.current_id, attachments=biezace)
        self.refresh_attachments()

    def remove_attachment(self, path: str) -> None:
        krok = self.store.get_template(self.current_id) if self.current_id else None
        if krok is None:
            return
        self.store.update_template(
            self.current_id, attachments=[p for p in krok.attachments if p != path]
        )
        self.refresh_attachments()

    def refresh_attachments(self) -> None:
        for child in self.attachments_frame.winfo_children():
            child.destroy()
        krok = self.store.get_template(self.current_id) if self.current_id else None
        paths = list(krok.attachments) if krok else []
        self.attachments_summary.configure(
            text="brak" if not paths else str(len(paths)) + " "
            + ("plik" if len(paths) == 1 else "pliki/plików")
        )
        if not paths:
            return
        for index, path in enumerate(paths):
            istnieje = Path(path).is_file()
            row = ctk.CTkFrame(self.attachments_frame, fg_color=theme.SURFACE_HI, corner_radius=6)
            row.grid(row=index, column=0, sticky="ew", pady=2)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                row,
                text=Path(path).name + ("" if istnieje else "   (nie znaleziono pliku)"),
                font=theme.font(11),
                text_color=theme.TEXT if istnieje else theme.ERR,
                anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=12, pady=6)
            button(
                row, "Usuń", lambda p=path: self.remove_attachment(p), kind="ghost",
                width=70, height=26,
            ).grid(row=0, column=1, padx=(0, 6), pady=4)

    # -------------------------------------------------------- podgląd i test

    def _wybrany_krok(self):
        return self.store.get_template(self.current_id) if self.current_id else None

    def preview(self) -> None:
        self.save()
        krok = self._wybrany_krok()
        if krok is None:
            return
        odbiorca = self.store.next_due() or (self.store.list_recipients() or [None])[0]
        PreviewDialog(self, self.store, odbiorca, krok).show()

    def send_test(self) -> None:
        self.save()
        krok = self._wybrany_krok()
        if krok is None:
            return
        config = load_smtp_config(self.store, self.app.vault)
        problems = config.validate()
        if problems:
            messagebox.showwarning(
                "Brak konfiguracji",
                "Uzupełnij ustawienia SMTP:\n\n" + "\n".join("- " + p for p in problems),
                parent=self.winfo_toplevel(),
            )
            return

        target = config.sender
        if not messagebox.askyesno(
            "Wysłać wiadomość testową?",
            "Testowy mail z kroku '" + krok.name + "' poleci na adres " + target + ". Kontynuować?",
            parent=self.winfo_toplevel(),
        ):
            return

        odbiorca = self.store.next_due() or (self.store.list_recipients() or [None])[0]
        if odbiorca is None:
            odbiorca = sample_recipient(self.store, target)
        snapshot = SequenceSnapshot.from_store(self.store)
        subject, body, unsubscribe_to = compose(
            krok, self.store, odbiorca, config.sender, snapshot
        )
        subject = "[TEST] " + subject

        def worker() -> None:
            try:
                Mailer(config).send(
                    target, subject, body, krok.is_html, krok.attachments, unsubscribe_to
                )
            except (MailerError, Exception) as exc:  # noqa: BLE001
                komunikat = str(exc)
                self.after(0, lambda: self._test_done(False, komunikat))
            else:
                self.after(0, lambda: self._test_done(True, target))

        self.warning_label.configure(text="Wysyłam wiadomość testową...", text_color=theme.ACCENT)
        threading.Thread(target=worker, name="test-mail", daemon=True).start()

    def _test_done(self, ok: bool, detail: str) -> None:
        self._update_warning()
        if ok:
            self.store.set_setting("test_sent_at", now_iso())
            self.store.log("ok", "Wysłano wiadomość testową.", detail)
            messagebox.showinfo(
                "Wysłano",
                "Wiadomość testowa poleciała na " + detail + ".",
                parent=self.winfo_toplevel(),
            )
        else:
            self.store.log("error", "Test nieudany: " + detail)
            messagebox.showerror("Test nieudany", detail, parent=self.winfo_toplevel())
        self.app.refresh_all()

    # ------------------------------------------------------------ odświeżanie

    def refresh(self) -> None:
        kroki = self.store.list_templates()
        if self.current_id is None or not any(k.id == self.current_id for k in kroki):
            self.current_id = kroki[0].id if kroki else None
        self.refresh_steps()
        self.after(50, self._dopasuj_pole_tresci)
        self.refresh_chips()
        self.load_step()

    KROKOW_W_WIERSZU = 4

    def refresh_steps(self) -> None:
        """Kroki jako kafelki. Przy większej liczbie zawijają się do kolejnego wiersza."""
        for child in self.steps_strip.winfo_children():
            child.destroy()
        kroki = self.store.list_templates()
        aktywne = [k for k in kroki if k.active]
        for kolumna in range(self.KROKOW_W_WIERSZU):
            self.steps_strip.grid_columnconfigure(kolumna, weight=1, uniform="krok")

        for index, krok in enumerate(kroki):
            if not krok.active:
                opis = "nie bierze udziału"
            elif krok.id == aktywne[0].id:
                opis = "wychodzi od razu"
            else:
                dni = krok.delay_days
                opis = "po " + str(dni) + (" dniu" if dni == 1 else " dniach")
            numer = str(aktywne.index(krok) + 1) if krok in aktywne else "–"
            wybrany = krok.id == self.current_id

            chip = ctk.CTkFrame(
                self.steps_strip,
                fg_color=theme.ACCENT if wybrany else theme.SURFACE_HI,
                corner_radius=10,
                border_width=1,
                border_color=theme.ACCENT if wybrany else theme.BORDER,
            )
            chip.grid(
                row=index // self.KROKOW_W_WIERSZU,
                column=index % self.KROKOW_W_WIERSZU,
                padx=(0, 8),
                pady=(0, 8),
                sticky="ew",
            )
            chip.grid_columnconfigure(1, weight=1)

            odznaka = ctk.CTkLabel(
                chip,
                text=numer,
                font=theme.font(13, "bold"),
                text_color="#ffffff" if wybrany else (
                    theme.ACCENT if krok.active else theme.MUTED
                ),
                fg_color="transparent" if wybrany else theme.SURFACE,
                corner_radius=12,
                width=26,
                height=26,
            )
            odznaka.grid(row=0, column=0, rowspan=2, padx=(12, 10), pady=12)

            nazwa = ctk.CTkLabel(
                chip,
                text=krok.name,
                font=theme.font(12, "bold"),
                text_color="#ffffff" if wybrany else (
                    theme.TEXT if krok.active else theme.MUTED
                ),
                anchor="w",
            )
            nazwa.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=(12, 0))

            podpis = ctk.CTkLabel(
                chip,
                text=opis,
                font=theme.font(10),
                text_color="#dbe6ff" if wybrany else (
                    theme.MUTED if krok.active else "#5a6474"
                ),
                anchor="w",
            )
            podpis.grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=(0, 12))

            for widget in (chip, odznaka, nazwa, podpis):
                widget.bind("<Button-1>", lambda _e, i=krok.id: self.select_step(i))

    def refresh_chips(self) -> None:
        for child in self.chips.winfo_children():
            child.destroy()
        for index, key in enumerate(self._known_keys()):
            button(
                self.chips,
                "{" + key + "}",
                lambda k=key: self._insert_placeholder(k),
                kind="ghost",
                width=len(key) * 9 + 40,
                height=30,
            ).grid(row=0, column=index, padx=(0, 6))

    def _update_warning(self) -> None:
        combined = self.subject_entry.get() + "\n" + self.body_text.get("1.0", "end-1c")
        uzyte = placeholders_in(combined)
        unknown = unknown_placeholders(combined, self._known_keys())
        bez_domyslnej = [
            f.key for f in self.store.list_fields() if f.key in uzyte and not f.fallback.strip()
        ]

        linie = []
        if unknown:
            linie.append(
                "Nieznane znaczniki: "
                + ", ".join("{" + name + "}" for name in unknown)
                + " - klient zobaczy je w mailu dosłownie, razem z klamrami."
            )
        if bez_domyslnej:
            linie.append(
                "Bez wartości domyślnej: "
                + ", ".join("{" + key + "}" for key in bez_domyslnej)
                + " - u odbiorcy z pustą rubryką zostanie w tym miejscu dziura. "
                "Uzupełnij domyślną w Odbiorcy > Pola."
            )
        self.warning_label.configure(text="\n\n".join(linie), text_color=theme.WARN)


def _jako_int(value: str, default: int) -> int:
    try:
        return max(0, int(float(str(value).strip().replace(",", "."))))
    except (TypeError, ValueError):
        return default
