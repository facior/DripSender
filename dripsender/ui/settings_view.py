"""Ustawienia konta SMTP i tempa wysyłki."""

from __future__ import annotations

import threading
import webbrowser
from datetime import time
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..engine import load_smtp_config
from ..paths import data_dir
from .. import branding, updater
from ..security import app_lock_enabled, set_app_lock
from ..updater import aktualizacje_dostepne
from ..schedule import DAY_NAMES, SendWindow, parse_time
from ..store import now_iso, verify_backup
from ..tray import autostart_supported, is_autostart_enabled, set_autostart
from ..mailer import Mailer
from . import theme
from .widgets import Card, button, entry

GMAIL_APP_PASSWORDS_URL = "https://myaccount.google.com/apppasswords"

PRESETS = {
    "Gmail": ("smtp.gmail.com", "465", "ssl"),
    "Outlook / Microsoft 365": ("smtp.office365.com", "587", "starttls"),
    "Inny serwer": ("", "587", "starttls"),
}

SECURITY_LABELS = {
    "ssl": "SSL/TLS (port 465)",
    "starttls": "STARTTLS (port 587)",
    "none": "Bez szyfrowania",
}
LABEL_TO_SECURITY = {label: key for key, label in SECURITY_LABELS.items()}


class SettingsView(ctk.CTkScrollableFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.store = app.store
        self.vault = app.vault
        self.grid_columnconfigure(0, weight=1)

        self._build_account_card()
        self._build_pace_card()
        self._build_hours_card()
        self._build_background_card()
        self._build_unsubscribe_card()
        self._build_inbox_card()
        self._build_security_card()
        self._build_update_card()
        self.refresh()

    # ------------------------------------------------------------------ budowa

    def _build_account_card(self) -> None:
        card = Card(
            self,
            "Konto wysyłkowe (SMTP)",
            "Gmail wymaga włączonej weryfikacji dwuetapowej i 16-znakowego hasła aplikacji. "
            "Zwykłe hasło do konta zostanie odrzucone.",
        )
        card.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        body = card.body
        body.grid_columnconfigure(1, weight=1)

        preset_row = ctk.CTkFrame(body, fg_color="transparent")
        preset_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ctk.CTkLabel(
            preset_row, text="Szybkie ustawienie", font=theme.font(12), text_color=theme.TEXT
        ).grid(row=0, column=0, padx=(0, 12))
        for index, name in enumerate(PRESETS):
            button(
                preset_row,
                name,
                lambda n=name: self._apply_preset(n),
                kind="ghost",
                width=170,
                height=32,
            ).grid(row=0, column=index + 1, padx=(0, 8))

        self.host_entry = self._row(body, 1, "Serwer SMTP", "smtp.gmail.com")
        self.port_entry = self._row(body, 2, "Port", "465")
        self.security_var = ctk.StringVar(value=SECURITY_LABELS["ssl"])
        security_row = self._form_row(body, 3, "Szyfrowanie")
        ctk.CTkOptionMenu(
            security_row,
            values=list(SECURITY_LABELS.values()),
            variable=self.security_var,
            width=220,
            height=34,
            corner_radius=8,
            fg_color=theme.SURFACE_HI,
            button_color=theme.BORDER,
            button_hover_color=theme.ACCENT,
            text_color=theme.TEXT,
            font=theme.font(12),
        ).grid(row=0, column=1, sticky="w")

        self.user_entry = self._row(body, 4, "Login (adres e-mail)", "twoj.adres@gmail.com")
        self.password_entry = self._row(body, 5, "Hasło aplikacji", "16 znaków z Google", show="*")
        self.from_name_entry = self._row(body, 6, "Nazwa nadawcy", "Jan Kowalski")
        self.from_email_entry = self._row(
            body, 7, "Adres nadawcy", "puste = taki jak login"
        )
        self.reply_to_entry = self._row(body, 8, "Odpowiedzi na adres", "opcjonalnie")

        self.storage_label = ctk.CTkLabel(
            body, text="", font=theme.font(10), text_color=theme.MUTED, anchor="w"
        )
        self.storage_label.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        actions.grid_columnconfigure(3, weight=1)
        button(actions, "Zapisz", self.save_and_confirm, width=110).grid(row=0, column=0, padx=(0, 8))
        self.test_button = button(
            actions, "Testuj połączenie", self.test_connection, kind="ghost", width=160
        )
        self.test_button.grid(row=0, column=1, padx=(0, 8))
        button(
            actions,
            "Jak zrobić hasło aplikacji?",
            lambda: webbrowser.open(GMAIL_APP_PASSWORDS_URL),
            kind="ghost",
            width=210,
        ).grid(row=0, column=2)

        self.status_label = ctk.CTkLabel(
            body, text="", font=theme.font(11), text_color=theme.MUTED, anchor="w",
            justify="left", wraplength=640,
        )
        self.status_label.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    def _build_pace_card(self) -> None:
        card = Card(
            self,
            "Tempo wysyłki",
            "Jeden mail na odstęp. Przy 5 minutach wychodzi 12 maili na godzinę, "
            "czyli maksymalnie 288 na dobę - mieści się w limicie Gmaila (ok. 500/dzień).",
        )
        card.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        body = card.body
        body.grid_columnconfigure(1, weight=1)

        self.interval_entry = self._row(body, 0, "Odstęp między mailami (min)", "5")
        self.retries_entry = self._row(body, 1, "Ponowne próby przy błędzie", "2")
        self.jitter_entry = self._row(body, 2, "Losowe odchylenie odstępu (%)", "0")
        self.daily_limit_entry = self._row(body, 3, "Dzienny limit wiadomości", "450")

        ctk.CTkLabel(
            body,
            text="Odchylenie 0% = równe odstępy co do sekundy. Ustaw np. 20%, aby wysyłka "
            "wyglądała mniej automatycznie (przy 5 min mail poleci między 4 a 6 minutą).\n"
            "Dzienny limit chroni przed blokadą konta - po jego wyczerpaniu kampania czeka "
            "do następnego dnia. Wpisz 0, aby wyłączyć.",
            font=theme.font(10),
            text_color=theme.MUTED,
            anchor="w",
            justify="left",
            wraplength=640,
        ).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        button(body, "Zapisz", self.save_and_confirm, width=110).grid(
            row=5, column=0, sticky="w", pady=(14, 0)
        )

    def _build_hours_card(self) -> None:
        card = Card(
            self,
            "Godziny wysyłki",
            "Bez tego kampania rozpoczęta wieczorem będzie wysyłać maile w środku nocy. "
            "Poza wyznaczonym oknem program czeka i wznawia wysyłkę sam.",
        )
        card.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        self.hours_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            body,
            text="Wysyłaj tylko w wybranych dniach i godzinach",
            variable=self.hours_var,
            command=self._update_hours_preview,
            font=theme.font(12),
            text_color=theme.TEXT,
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=4,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            border_color=theme.BORDER,
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))

        dni = ctk.CTkFrame(body, fg_color="transparent")
        dni.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(
            dni, text="Dni", font=theme.font(12), text_color=theme.TEXT, anchor="w", width=230
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))
        self.day_vars: dict[int, ctk.BooleanVar] = {}
        for index, nazwa in enumerate(DAY_NAMES):
            var = ctk.BooleanVar(value=index < 5)
            ctk.CTkCheckBox(
                dni,
                text=nazwa,
                variable=var,
                command=self._update_hours_preview,
                width=58,
                font=theme.font(11),
                text_color=theme.TEXT,
                checkbox_width=16,
                checkbox_height=16,
                corner_radius=4,
                fg_color=theme.ACCENT,
                hover_color=theme.ACCENT_HOVER,
                border_color=theme.BORDER,
            ).grid(row=0, column=index + 1, padx=(0, 10))
            self.day_vars[index] = var

        godziny = ctk.CTkFrame(body, fg_color="transparent")
        godziny.grid(row=2, column=0, sticky="ew")
        ctk.CTkLabel(
            godziny, text="Od / do", font=theme.font(12), text_color=theme.TEXT,
            anchor="w", width=230,
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))
        self.hours_from_entry = entry(godziny, "09:00", width=90)
        self.hours_from_entry.grid(row=0, column=1)
        self.hours_from_entry.bind("<KeyRelease>", lambda _e: self._update_hours_preview())
        ctk.CTkLabel(godziny, text="—", font=theme.font(12), text_color=theme.MUTED).grid(
            row=0, column=2, padx=10
        )
        self.hours_to_entry = entry(godziny, "17:00", width=90)
        self.hours_to_entry.grid(row=0, column=3)
        self.hours_to_entry.bind("<KeyRelease>", lambda _e: self._update_hours_preview())

        self.hours_preview = ctk.CTkLabel(
            body, text="", font=theme.font(11), text_color=theme.MUTED, anchor="w",
            justify="left", wraplength=640,
        )
        self.hours_preview.grid(row=3, column=0, sticky="ew", pady=(12, 0))

        button(body, "Zapisz", self.save_and_confirm, width=110).grid(
            row=4, column=0, sticky="w", pady=(14, 0)
        )

    def _build_background_card(self) -> None:
        card = Card(
            self,
            "Praca w tle",
            "Lista kilkuset adresów co 5 minut to nawet kilka dni wysyłki. "
            "Te opcje pozwalają zostawić program samemu sobie.",
        )
        card.grid(row=3, column=0, sticky="ew", pady=(0, 14))
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        def checkbox(row: int, tekst: str, opis: str, var: ctk.BooleanVar, command=None):
            ctk.CTkCheckBox(
                body,
                text=tekst,
                variable=var,
                command=command,
                font=theme.font(12),
                text_color=theme.TEXT,
                checkbox_width=18,
                checkbox_height=18,
                corner_radius=4,
                fg_color=theme.ACCENT,
                hover_color=theme.ACCENT_HOVER,
                border_color=theme.BORDER,
            ).grid(row=row, column=0, sticky="w", pady=(6, 0))
            ctk.CTkLabel(
                body, text=opis, font=theme.font(10), text_color=theme.MUTED,
                anchor="w", justify="left", wraplength=640,
            ).grid(row=row + 1, column=0, sticky="ew", padx=(28, 0), pady=(0, 6))

        self.tray_var = ctk.BooleanVar(value=True)
        checkbox(
            0,
            "Zamknięcie okna chowa program do zasobnika",
            "Krzyżyk nie kończy kampanii - program siedzi przy zegarku i wysyła dalej. "
            "Żeby go naprawdę zamknąć, kliknij ikonę prawym przyciskiem i wybierz Zakończ.",
            self.tray_var,
        )
        self.autostart_var = ctk.BooleanVar(value=False)
        checkbox(
            2,
            "Uruchamiaj razem z Windows",
            "Program wstanie po zalogowaniu do systemu.",
            self.autostart_var,
        )
        self.resume_var = ctk.BooleanVar(value=True)
        checkbox(
            4,
            "Wznawiaj przerwaną kampanię po starcie",
            "Jeśli program zostanie zamknięty w trakcie wysyłki, po ponownym uruchomieniu "
            "sam podejmie kolejkę od pierwszego pominiętego odbiorcy.",
            self.resume_var,
        )

        self.background_note = ctk.CTkLabel(
            body, text="", font=theme.font(10), text_color=theme.MUTED,
            anchor="w", justify="left", wraplength=640,
        )
        self.background_note.grid(row=6, column=0, sticky="ew", pady=(4, 0))

        button(body, "Zapisz", self.save_and_confirm, width=110).grid(
            row=7, column=0, sticky="w", pady=(14, 0)
        )

        ctk.CTkLabel(
            body,
            text="Lista odbiorców, szablon i historia zapisują się w:\n" + str(data_dir()),
            font=theme.font(10),
            text_color=theme.MUTED,
            anchor="w",
            justify="left",
            wraplength=640,
        ).grid(row=8, column=0, sticky="ew", pady=(18, 0))

    def _apply_lock(self) -> None:
        """Ustawia lub zdejmuje PIN. Bez modalnych okien - save() bywa cichy."""
        pin = self.pin_entry.get().strip()
        powtorz = self.pin_repeat_entry.get().strip()

        if not self.lock_var.get():
            set_app_lock(self.store, "")
            self.pin_entry.delete(0, "end")
            self.pin_repeat_entry.delete(0, "end")
            self.lock_status.configure(text="Blokada wyłączona.", text_color=theme.MUTED)
            return

        if pin:
            if pin != powtorz:
                self.lock_status.configure(
                    text="Wpisane PIN-y różnią się - blokada bez zmian.", text_color=theme.WARN
                )
                return
            if len(pin) < 4:
                self.lock_status.configure(
                    text="PIN powinien mieć co najmniej 4 znaki.", text_color=theme.WARN
                )
                return
            set_app_lock(self.store, pin)
            self.pin_entry.delete(0, "end")
            self.pin_repeat_entry.delete(0, "end")
            self.lock_status.configure(text="PIN zapisany.", text_color=theme.OK)
            return

        if not app_lock_enabled(self.store):
            self.lock_var.set(False)
            self.store.set_setting("app_lock_enabled", "0")
            self.lock_status.configure(
                text="Najpierw ustaw PIN - dopiero wtedy blokada zadziała.",
                text_color=theme.WARN,
            )
        else:
            self.store.set_setting("app_lock_enabled", "1")
            self.lock_status.configure(text="Blokada aktywna.", text_color=theme.OK)

    def _apply_autostart(self) -> None:
        """Dopisuje lub usuwa wpis autostartu w rejestrze Windows."""
        chciany = self.autostart_var.get()
        if chciany == is_autostart_enabled():
            return
        ok, komunikat = set_autostart(chciany)
        self.background_note.configure(
            text=komunikat, text_color=theme.MUTED if ok else theme.WARN
        )
        if not ok:
            self.autostart_var.set(is_autostart_enabled())

    def _update_hours_preview(self) -> None:
        window = SendWindow(
            enabled=self.hours_var.get(),
            start=parse_time(self.hours_from_entry.get(), time(9, 0)),
            end=parse_time(self.hours_to_entry.get(), time(17, 0)),
            days=frozenset(d for d, var in self.day_vars.items() if var.get()),
        )
        if not window.enabled:
            tekst = "Wysyłka o dowolnej porze, także w nocy i w weekend."
        elif not window.days:
            tekst = "Nie zaznaczono żadnego dnia - kampania nie ruszy."
        else:
            tekst = "Okno wysyłki: " + window.describe()
            if window.overnight:
                tekst += "   (okno przechodzi przez północ)"
        self.hours_preview.configure(
            text=tekst,
            text_color=theme.WARN if (window.enabled and not window.days) else theme.MUTED,
        )

    def _build_unsubscribe_card(self) -> None:
        card = Card(
            self,
            "Stopka z możliwością wypisania",
            "Dotyczy wszystkich kroków sekwencji. Przy mailingu handlowym w UE oczekuje "
            "się, że odbiorca łatwo zrezygnuje.",
        )
        card.grid(row=4, column=0, sticky="ew", pady=(0, 14))
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        self.unsub_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            body,
            text="Dopisuj stopkę na końcu każdej wiadomości",
            variable=self.unsub_var,
            font=theme.font(12),
            text_color=theme.TEXT,
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=4,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            border_color=theme.BORDER,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.unsub_entry = entry(body, "Treść stopki")
        self.unsub_entry.grid(row=1, column=0, sticky="ew")

        ctk.CTkLabel(
            body,
            text="Program dodaje też nagłówek List-Unsubscribe, dzięki któremu Gmail i "
            "Outlook pokazują przycisk Wypisz się. Przy włączonym nasłuchu skrzynki "
            "odpowiedź STOP wypisuje adres automatycznie.",
            font=theme.font(10),
            text_color=theme.MUTED,
            anchor="w",
            justify="left",
            wraplength=640,
        ).grid(row=2, column=0, sticky="ew", pady=(8, 0))

        button(body, "Zapisz", self.save_and_confirm, width=110).grid(
            row=3, column=0, sticky="w", pady=(14, 0)
        )

    def _build_inbox_card(self) -> None:
        card = Card(
            self,
            "Nasłuch skrzynki (IMAP)",
            "Program czyta pocztę na tym samym koncie i rozpoznaje odpowiedzi, odbicia "
            "oraz prośby o wypisanie. Niczego nie kasuje ani nie przenosi.",
        )
        card.grid(row=5, column=0, sticky="ew", pady=(0, 14))
        body = card.body
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)

        self.imap_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            body,
            text="Sprawdzaj skrzynkę i aktualizuj statusy odbiorców",
            variable=self.imap_var,
            font=theme.font(12),
            text_color=theme.TEXT,
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=4,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            border_color=theme.BORDER,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        self.imap_host_entry = self._row(body, 1, "Serwer IMAP", "imap.gmail.com")
        self.imap_port_entry = self._row(body, 2, "Port", "993")
        self.imap_folder_entry = self._row(body, 3, "Folder", "INBOX")
        self.imap_interval_entry = self._row(body, 4, "Sprawdzaj co (min)", "10")
        self.imap_days_entry = self._row(body, 5, "Zasięg wstecz (dni)", "14")
        self.imap_stop_entry = self._row(body, 6, "Słowo oznaczające wypisanie", "STOP")

        ctk.CTkLabel(
            body,
            text="Odpowiedź od odbiorcy zdejmuje go z dalszych kroków sekwencji. "
            "Wiadomość zaczynająca się od słowa wypisania nadaje status Wypisany. "
            "Raport niedostarczenia ustawia status Odbity.",
            font=theme.font(10),
            text_color=theme.MUTED,
            anchor="w",
            justify="left",
            wraplength=640,
        ).grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        actions.grid_columnconfigure(2, weight=1)
        button(actions, "Zapisz", self.save_and_confirm, width=110).grid(
            row=0, column=0, padx=(0, 8)
        )
        self.inbox_button = button(
            actions, "Sprawdź teraz", self.check_inbox, kind="ghost", width=150
        )
        self.inbox_button.grid(row=0, column=1)

        self.inbox_status = ctk.CTkLabel(
            body,
            text="",
            font=theme.font(11),
            text_color=theme.MUTED,
            anchor="w",
            justify="left",
            wraplength=640,
        )
        self.inbox_status.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    def _build_security_card(self) -> None:
        card = Card(
            self,
            "Bezpieczeństwo i kopia zapasowa",
            "Lista klientów to dane osobowe. PIN chroni je przed kimś, kto usiądzie "
            "przy tym komputerze.",
        )
        card.grid(row=6, column=0, sticky="ew", pady=(0, 14))
        body = card.body
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)

        self.lock_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            body,
            text="Pytaj o PIN przy uruchomieniu programu",
            variable=self.lock_var,
            font=theme.font(12),
            text_color=theme.TEXT,
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=4,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            border_color=theme.BORDER,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        self.pin_entry = self._row(body, 1, "Nowy PIN", "puste = bez zmiany", show="*")
        self.pin_repeat_entry = self._row(body, 2, "Powtórz PIN", "", show="*")

        self.lock_status = ctk.CTkLabel(
            body, text="", font=theme.font(10), text_color=theme.MUTED, anchor="w"
        )
        self.lock_status.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        actions.grid_columnconfigure(3, weight=1)
        button(actions, "Zapisz", self.save_and_confirm, width=110).grid(
            row=0, column=0, padx=(0, 8)
        )
        button(actions, "Zrób kopię", self.make_backup, kind="ghost", width=130).grid(
            row=0, column=1, padx=(0, 8)
        )
        button(actions, "Przywróć kopię", self.restore_backup, kind="ghost", width=150).grid(
            row=0, column=2
        )

        ctk.CTkLabel(
            body,
            text="Kopia to jeden plik z całą listą, sekwencją i historią. Można ją zrobić "
            "przy działającej kampanii. Przywrócenie nadpisuje bieżące dane i wymaga "
            "ponownego uruchomienia programu.",
            font=theme.font(10),
            text_color=theme.MUTED,
            anchor="w",
            justify="left",
            wraplength=640,
        ).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    # --------------------------------------------------------- akcje dodatkowe

    def check_inbox(self) -> None:
        self.save()
        self.inbox_button.configure(state="disabled", text="Sprawdzam...")
        self.inbox_status.configure(text="Łączę się ze skrzynką...", text_color=theme.ACCENT)

        def worker() -> None:
            wynik = self.app.inbox.check_once()
            self.after(0, lambda: self._inbox_done(wynik))

        threading.Thread(target=worker, name="inbox-check", daemon=True).start()

    def _inbox_done(self, wynik) -> None:
        self.inbox_button.configure(state="normal", text="Sprawdź teraz")
        self.inbox_status.configure(
            text=wynik.describe(), text_color=theme.ERR if wynik.error else theme.OK
        )
        self.store.log(
            "warn" if wynik.error else "info", "Nasłuch skrzynki: " + wynik.describe()
        )
        self.app.refresh_all()

    def make_backup(self) -> None:
        sciezka = filedialog.asksaveasfilename(
            title="Zapisz kopię zapasową",
            defaultextension=".db",
            filetypes=[("Kopia DripSender", "*.db")],
            initialfile="dripsender-kopia-" + now_iso()[:10] + ".db",
            parent=self.winfo_toplevel(),
        )
        if not sciezka:
            return
        try:
            self.store.backup_to(sciezka)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "Nie udało się",
                "Kopia nie powstała:\n" + str(exc),
                parent=self.winfo_toplevel(),
            )
            return
        messagebox.showinfo(
            "Kopia gotowa", "Zapisano do:\n" + sciezka, parent=self.winfo_toplevel()
        )

    def restore_backup(self) -> None:
        sciezka = filedialog.askopenfilename(
            title="Wybierz kopię do przywrócenia",
            filetypes=[("Kopia DripSender", "*.db"), ("Wszystkie pliki", "*.*")],
            parent=self.winfo_toplevel(),
        )
        if not sciezka:
            return
        ok, komunikat = verify_backup(sciezka)
        if not ok:
            messagebox.showerror("Zła kopia", komunikat, parent=self.winfo_toplevel())
            return
        if not messagebox.askyesno(
            "Przywrócić kopię?",
            "Bieżąca lista, sekwencja i historia zostaną NADPISANE zawartością kopii.\n\n"
            "Tej operacji nie da się cofnąć. Kontynuować?",
            parent=self.winfo_toplevel(),
        ):
            return
        self.app.restore_from_backup(sciezka)

    def _build_update_card(self) -> None:
        card = Card(
            self,
            "Aktualizacje programu",
            "Program sprawdza pod podanym adresem, czy jest nowsza wersja, i może ją "
            "pobrać oraz podmienić samodzielnie.",
        )
        card.grid(row=7, column=0, sticky="ew", pady=(0, 14))
        body = card.body
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)

        self.update_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            body,
            text="Sprawdzaj dostępność aktualizacji przy uruchomieniu",
            variable=self.update_var,
            font=theme.font(12),
            text_color=theme.TEXT,
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=4,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            border_color=theme.BORDER,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        self.update_url_entry = self._row(
            body, 1, "Adres pliku z wersją", "https://.../update.json"
        )

        ctk.CTkLabel(
            body,
            text="Adres musi zaczynać się od https - inaczej ktoś po drodze mógłby podstawić "
            "własny plik. Pobrana aktualizacja jest sprawdzana sumą kontrolną SHA-256 "
            "z opisu wydania; niezgodna suma oznacza odrzucenie pliku bez instalacji.",
            font=theme.font(10),
            text_color=theme.MUTED,
            anchor="w",
            justify="left",
            wraplength=640,
        ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        actions.grid_columnconfigure(2, weight=1)
        button(actions, "Zapisz", self.save_and_confirm, width=110).grid(
            row=0, column=0, padx=(0, 8)
        )
        self.update_button = button(
            actions, "Sprawdź aktualizacje", self.check_update, kind="ghost", width=180
        )
        self.update_button.grid(row=0, column=1)

        self.update_status = ctk.CTkLabel(
            body,
            text="",
            font=theme.font(11),
            text_color=theme.MUTED,
            anchor="w",
            justify="left",
            wraplength=640,
        )
        self.update_status.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    def check_update(self) -> None:
        self.save()
        mozliwa, powod = aktualizacje_dostepne()
        adres = self.store.get_setting("update_url", "").strip()
        if not adres:
            self.update_status.configure(
                text="Najpierw wpisz adres pliku z opisem wydania.", text_color=theme.WARN
            )
            return

        self.update_button.configure(state="disabled", text="Sprawdzam...")
        self.update_status.configure(text="Pytam serwer o wersję...", text_color=theme.ACCENT)

        def worker() -> None:
            try:
                wydanie = updater.sprawdz(adres, branding.VERSION)
            except updater.UpdateError as exc:
                komunikat = str(exc)
                self.after(0, lambda: self._update_done(None, komunikat, mozliwa, powod))
            else:
                self.after(0, lambda: self._update_done(wydanie, "", mozliwa, powod))

        threading.Thread(target=worker, name="update-check", daemon=True).start()

    def _update_done(self, wydanie, blad: str, mozliwa: bool, powod: str) -> None:
        self.update_button.configure(state="normal", text="Sprawdź aktualizacje")
        self.store.set_setting("update_last_check", now_iso())
        if blad:
            self.update_status.configure(text=blad, text_color=theme.ERR)
            return
        if wydanie is None:
            self.update_status.configure(
                text="Masz najnowszą wersję (" + branding.VERSION + ").", text_color=theme.OK
            )
            return
        if not mozliwa:
            self.update_status.configure(
                text="Jest wersja " + wydanie.version + ", ale " + powod, text_color=theme.WARN
            )
            return
        self.update_status.configure(
            text="Dostępna wersja " + wydanie.version + ".", text_color=theme.ACCENT
        )
        self.app.pokaz_aktualizacje(wydanie)

    def _form_row(self, parent, row: int, label: str):
        """Zwraca ramkę wiersza z etykietą po lewej i miejscem na pole po prawej."""
        holder = ctk.CTkFrame(parent, fg_color="transparent")
        holder.grid(row=row, column=0, columnspan=2, sticky="ew", pady=6)
        holder.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            holder, text=label, font=theme.font(12), text_color=theme.TEXT, anchor="w", width=230
        ).grid(row=0, column=0, sticky="w", padx=(0, 16))
        return holder

    def _row(self, parent, row: int, label: str, placeholder: str, show: str | None = None):
        holder = self._form_row(parent, row, label)
        widget = entry(holder, placeholder, show=show)
        widget.grid(row=0, column=1, sticky="ew")
        return widget

    # ------------------------------------------------------------------ akcje

    def _apply_preset(self, name: str) -> None:
        host, port, security = PRESETS[name]
        self.host_entry.delete(0, "end")
        self.host_entry.insert(0, host)
        self.port_entry.delete(0, "end")
        self.port_entry.insert(0, port)
        self.security_var.set(SECURITY_LABELS[security])

    def save(self) -> None:
        user = self.user_entry.get().strip()
        self.store.update_settings(
            {
                "smtp_host": self.host_entry.get().strip(),
                "smtp_port": self.port_entry.get().strip() or "465",
                "smtp_security": LABEL_TO_SECURITY.get(self.security_var.get(), "ssl"),
                "smtp_user": user,
                "from_name": self.from_name_entry.get().strip(),
                "from_email": self.from_email_entry.get().strip(),
                "reply_to": self.reply_to_entry.get().strip(),
                "interval_minutes": max(1, _as_int(self.interval_entry.get(), 5)),
                "max_retries": max(0, _as_int(self.retries_entry.get(), 2)),
                "jitter_percent": min(50, max(0, _as_int(self.jitter_entry.get(), 0))),
                "daily_limit": max(0, _as_int(self.daily_limit_entry.get(), 450)),
                "hours_enabled": "1" if self.hours_var.get() else "0",
                "hours_from": self.hours_from_entry.get().strip() or "09:00",
                "hours_to": self.hours_to_entry.get().strip() or "17:00",
                "hours_days": ",".join(
                    str(d) for d, var in sorted(self.day_vars.items()) if var.get()
                ),
                "minimize_to_tray": "1" if self.tray_var.get() else "0",
                "auto_resume": "1" if self.resume_var.get() else "0",
                "imap_enabled": "1" if self.imap_var.get() else "0",
                "imap_host": self.imap_host_entry.get().strip() or "imap.gmail.com",
                "imap_port": _as_int(self.imap_port_entry.get(), 993),
                "imap_folder": self.imap_folder_entry.get().strip() or "INBOX",
                "imap_interval_minutes": max(1, _as_int(self.imap_interval_entry.get(), 10)),
                "imap_lookback_days": max(1, _as_int(self.imap_days_entry.get(), 14)),
                "imap_stop_word": self.imap_stop_entry.get().strip().upper() or "STOP",
                "unsubscribe_enabled": "1" if self.unsub_var.get() else "0",
                "unsubscribe_text": self.unsub_entry.get(),
                "update_auto_check": "1" if self.update_var.get() else "0",
                "update_url": self.update_url_entry.get().strip(),
            }
        )
        self._apply_autostart()
        self._apply_lock()
        self.app.sync_inbox_watcher()
        # Pole hasła zawsze pokazuje zapisaną wartość, więc puste = użytkownik je skasował.
        password = self.password_entry.get()
        if password:
            self.vault.set(user, password)
        else:
            self.vault.delete(user)
        self.storage_label.configure(
            text="Hasło przechowywane w: " + self.vault.storage_label()
        )

    def save_and_confirm(self) -> None:
        self.save()
        self.app.refresh_all()
        messagebox.showinfo(
            "Zapisano", "Ustawienia zostały zapisane.", parent=self.winfo_toplevel()
        )

    def test_connection(self) -> None:
        self.save()
        config = load_smtp_config(self.store, self.vault)
        self.test_button.configure(state="disabled", text="Testuję...")
        self.status_label.configure(text="Łączę z serwerem...", text_color=theme.ACCENT)

        def worker() -> None:
            ok, message = Mailer(config).verify()
            self.after(0, lambda: self._test_done(ok, message))

        threading.Thread(target=worker, name="smtp-test", daemon=True).start()

    def _test_done(self, ok: bool, message: str) -> None:
        self.test_button.configure(state="normal", text="Testuj połączenie")
        self.store.set_setting("smtp_verified_at", now_iso() if ok else "")
        self.status_label.configure(
            text=("OK - " if ok else "Błąd - ") + message,
            text_color=theme.OK if ok else theme.ERR,
        )
        self.store.log("ok" if ok else "error", "Test połączenia SMTP: " + message)
        self.app.refresh_all()

    # ------------------------------------------------------------- odświeżanie

    def refresh(self) -> None:
        values = {
            self.host_entry: self.store.get_setting("smtp_host"),
            self.port_entry: self.store.get_setting("smtp_port"),
            self.user_entry: self.store.get_setting("smtp_user"),
            self.from_name_entry: self.store.get_setting("from_name"),
            self.from_email_entry: self.store.get_setting("from_email"),
            self.reply_to_entry: self.store.get_setting("reply_to"),
            self.interval_entry: self.store.get_setting("interval_minutes"),
            self.retries_entry: self.store.get_setting("max_retries"),
            self.jitter_entry: self.store.get_setting("jitter_percent"),
            self.imap_host_entry: self.store.get_setting("imap_host"),
            self.imap_port_entry: self.store.get_setting("imap_port"),
            self.imap_folder_entry: self.store.get_setting("imap_folder"),
            self.imap_interval_entry: self.store.get_setting("imap_interval_minutes"),
            self.imap_days_entry: self.store.get_setting("imap_lookback_days"),
            self.imap_stop_entry: self.store.get_setting("imap_stop_word"),
            self.update_url_entry: self.store.get_setting("update_url"),
            self.daily_limit_entry: self.store.get_setting("daily_limit"),
            self.hours_from_entry: self.store.get_setting("hours_from"),
            self.hours_to_entry: self.store.get_setting("hours_to"),
        }
        for widget, value in values.items():
            widget.delete(0, "end")
            widget.insert(0, value)

        self.security_var.set(
            SECURITY_LABELS.get(self.store.get_setting("smtp_security", "ssl"), SECURITY_LABELS["ssl"])
        )
        self.hours_var.set(self.store.get_bool("hours_enabled"))
        wybrane = parse_days_setting(self.store.get_setting("hours_days", "0,1,2,3,4"))
        for day, var in self.day_vars.items():
            var.set(day in wybrane)
        self._update_hours_preview()

        self.unsub_var.set(self.store.get_bool("unsubscribe_enabled"))
        self.unsub_entry.delete(0, "end")
        self.unsub_entry.insert(0, self.store.get_setting("unsubscribe_text"))
        self.update_var.set(self.store.get_bool("update_auto_check", True))
        ostatnia = self.store.get_setting("update_last_check", "")
        mozliwa, powod = aktualizacje_dostepne()
        self.update_status.configure(
            text=powod if not mozliwa else (
                "Ostatnie sprawdzenie: " + ostatnia if ostatnia else
                "Jeszcze nie sprawdzano aktualizacji."
            ),
            text_color=theme.MUTED,
        )
        self.imap_var.set(self.store.get_bool("imap_enabled"))
        ostatnie = self.store.get_setting("imap_last_check", "")
        self.inbox_status.configure(
            text="Ostatnie sprawdzenie: " + ostatnie if ostatnie else "Skrzynka jeszcze niesprawdzana.",
            text_color=theme.MUTED,
        )
        self.lock_var.set(app_lock_enabled(self.store))
        self.lock_status.configure(
            text="Blokada aktywna." if app_lock_enabled(self.store) else "Blokada wyłączona.",
            text_color=theme.MUTED,
        )

        self.tray_var.set(self.store.get_bool("minimize_to_tray", True))
        self.resume_var.set(self.store.get_bool("auto_resume", True))
        self.autostart_var.set(is_autostart_enabled())
        mozliwy, powod = autostart_supported()
        self.background_note.configure(
            text=powod if not mozliwy else "", text_color=theme.MUTED
        )

        stored_password = self.vault.get(self.store.get_setting("smtp_user"))
        self.password_entry.delete(0, "end")
        if stored_password:
            self.password_entry.insert(0, stored_password)
        self.storage_label.configure(text="Hasło przechowywane w: " + self.vault.storage_label())


def parse_days_setting(value: str) -> set[int]:
    return {int(p) for p in (value or "").split(",") if p.strip().isdigit()}


def _as_int(value: str, default: int) -> int:
    try:
        return int(float(str(value).strip().replace(",", ".")))
    except (TypeError, ValueError):
        return default
