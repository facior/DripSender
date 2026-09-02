"""Instrukcja podpięcia krok po kroku plus informacje o aplikacji.

Kroki nie są statycznym tekstem - każdy sam sprawdza, czy został wykonany,
i prowadzi przyciskiem do właściwej zakładki.
"""

from __future__ import annotations

import subprocess
import webbrowser
from tkinter import messagebox

import customtkinter as ctk

from .. import branding
from ..engine import load_smtp_config
from ..paths import data_dir
from ..security import _HAS_KEYRING
from ..schedule import SendWindow
from ..store import STATUS_PENDING
from . import theme
from .widgets import Card, button

GMAIL_APP_PASSWORDS_URL = "https://myaccount.google.com/apppasswords"
GMAIL_2FA_URL = "https://myaccount.google.com/signinoptions/two-step-verification"

DONE_MARK = "✓"
TODO_MARK = "○"


class Step(ctk.CTkFrame):
    """Jeden krok instrukcji: numer, opis, znacznik wykonania i przycisk akcji."""

    def __init__(
        self,
        master,
        number: int,
        title: str,
        description: str,
        action_label: str = "",
        action=None,
        checkable: bool = True,
    ) -> None:
        super().__init__(master, fg_color=theme.SURFACE_HI, corner_radius=10)
        self.checkable = checkable
        self.grid_columnconfigure(1, weight=1)

        self.badge = ctk.CTkLabel(
            self,
            text=str(number),
            font=theme.font(13, "bold"),
            text_color=theme.MUTED,
            fg_color=theme.SURFACE,
            corner_radius=14,
            width=28,
            height=28,
        )
        self.badge.grid(row=0, column=0, rowspan=2, padx=(14, 12), pady=14)

        self.title_label = ctk.CTkLabel(
            self, text=title, font=theme.font(13, "bold"), text_color=theme.TEXT, anchor="w"
        )
        self.title_label.grid(row=0, column=1, sticky="ew", pady=(14, 0))

        ctk.CTkLabel(
            self,
            text=description,
            font=theme.font(11),
            text_color=theme.MUTED,
            anchor="w",
            justify="left",
            wraplength=430,
        ).grid(row=1, column=1, sticky="ew", pady=(2, 14))

        if action_label:
            button(self, action_label, action, kind="ghost", width=170, height=32).grid(
                row=0, column=2, rowspan=2, padx=(12, 14)
            )

        self.status_label = ctk.CTkLabel(
            self, text="", font=theme.font(11, "bold"), text_color=theme.MUTED, width=110
        )
        self.status_label.grid(row=0, column=3, rowspan=2, padx=(0, 14))

    def set_done(self, done: bool, done_text: str = "gotowe", todo_text: str = "do zrobienia") -> None:
        if not self.checkable:
            self.status_label.configure(text="")
            return
        if done:
            self.status_label.configure(text=DONE_MARK + "  " + done_text, text_color=theme.OK)
            self.badge.configure(text=DONE_MARK, text_color=theme.OK)
        else:
            self.status_label.configure(text=TODO_MARK + "  " + todo_text, text_color=theme.MUTED)


class GuideView(ctk.CTkScrollableFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.store = app.store
        self.grid_columnconfigure(0, weight=1)

        self._build_steps()
        self._build_placeholders()
        self._build_info()
        self._build_faq()
        self.refresh()

    # ------------------------------------------------------------------- kroki

    def _build_steps(self) -> None:
        card = Card(
            self,
            "Podpięcie krok po kroku",
            "Znaczniki po prawej aktualizują się same - wiadomo, co jest zrobione, "
            "a co jeszcze przed Tobą.",
        )
        card.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        self.steps: dict[str, Step] = {}

        def add(key: str, number: int, title: str, desc: str, label="", action=None, checkable=True):
            step = Step(body, number, title, desc, label, action, checkable)
            step.grid(row=number - 1, column=0, sticky="ew", pady=4)
            self.steps[key] = step

        add(
            "2fa",
            1,
            "Włącz weryfikację dwuetapową w Google",
            "Bez niej Google nie pozwoli wygenerować hasła aplikacji. Robisz to raz, "
            "na koncie, z którego będą wychodzić maile.",
            "Otwórz ustawienia Google",
            lambda: webbrowser.open(GMAIL_2FA_URL),
            checkable=False,
        )
        add(
            "app_password",
            2,
            "Wygeneruj hasło aplikacji",
            "16 znaków, które wkleisz zamiast zwykłego hasła. Zwykłe hasło do konta "
            "zostanie przez Gmaila odrzucone.",
            "Wygeneruj hasło",
            lambda: webbrowser.open(GMAIL_APP_PASSWORDS_URL),
            checkable=False,
        )
        add(
            "smtp",
            3,
            "Uzupełnij dane konta w Ustawieniach",
            "Kliknij przycisk Gmail, żeby wypełnić serwer i port jednym kliknięciem, "
            "a potem wpisz login i wklej hasło aplikacji.",
            "Przejdź do Ustawień",
            lambda: self.app.go_to("settings"),
        )
        add(
            "verified",
            4,
            "Sprawdź połączenie",
            "Przycisk Testuj połączenie w Ustawieniach loguje się na serwer, ale nie "
            "wysyła żadnej wiadomości. Musi zwrócić OK.",
            "Testuj połączenie",
            lambda: self.app.go_to("settings"),
        )
        add(
            "recipients",
            5,
            "Wgraj listę klientów",
            "Dodaj pojedynczo albo wklej wielu naraz. Kolejność na liście to kolejność "
            "wysyłki, a duplikaty odpadają same.",
            "Przejdź do Odbiorców",
            lambda: self.app.go_to("recipients"),
        )
        add(
            "template",
            6,
            "Ułóż treść i sekwencję",
            "Wstaw znaczniki w klamrach, np. {imie} albo {firma}. Możesz też włączyć "
            "follow-up, który poleci do tych, którzy nie odpowiedzą.",
            "Przejdź do Sekwencji",
            lambda: self.app.go_to("sequence"),
        )
        add(
            "test_sent",
            7,
            "Wyślij mail testowy do siebie",
            "Zanim ruszy kampania, zobacz w swojej skrzynce, jak wiadomość wygląda "
            "naprawdę - z podstawionymi danymi i załącznikami.",
            "Wyślij test",
            lambda: self.app.go_to("sequence"),
        )
        add(
            "ready",
            8,
            "Odpal kampanię",
            "Pierwszy mail wychodzi od razu, każdy kolejny po ustawionym odstępie. "
            "Program może przez ten czas siedzieć w zasobniku - zamknięcie okna "
            "go nie kończy.",
            "Przejdź do Kampanii",
            lambda: self.app.go_to("campaign"),
        )

    # ------------------------------------------------------------- znaczniki

    def _build_placeholders(self) -> None:
        card = Card(
            self,
            "Jak działają znaczniki",
            "Znacznik w klamrach to puste miejsce, które przed wysyłką wypełnia się danymi "
            "konkretnego odbiorcy. Każdy mail powstaje osobno.",
        )
        card.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        example = ctk.CTkFrame(body, fg_color=theme.SURFACE_HI, corner_radius=10)
        example.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        example.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            example,
            text="Piszesz raz:",
            font=theme.font(11),
            text_color=theme.MUTED,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 0))
        ctk.CTkLabel(
            example,
            text="Dzień dobry {imie}, piszę w sprawie firmy {firma}.",
            font=theme.mono(11),
            text_color=theme.ACCENT,
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=14, pady=(2, 8))
        ctk.CTkLabel(
            example,
            text="Klienci dostają:",
            font=theme.font(11),
            text_color=theme.MUTED,
            anchor="w",
        ).grid(row=2, column=0, sticky="ew", padx=14)
        ctk.CTkLabel(
            example,
            text="Dzień dobry Anna, piszę w sprawie firmy Kowalska Design.\n"
            "Dzień dobry Piotr, piszę w sprawie firmy Beta Hurt.",
            font=theme.mono(11),
            text_color=theme.OK,
            anchor="w",
            justify="left",
        ).grid(row=3, column=0, sticky="ew", padx=14, pady=(2, 12))

        ctk.CTkLabel(
            body,
            text="Znaczniki dostępne w tym programie:",
            font=theme.font(11),
            text_color=theme.MUTED,
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", pady=(0, 6))

        self.placeholder_rows = ctk.CTkFrame(body, fg_color="transparent")
        self.placeholder_rows.grid(row=2, column=0, sticky="ew")
        self.placeholder_rows.grid_columnconfigure(2, weight=1)

        rules = ctk.CTkFrame(body, fg_color="transparent")
        rules.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        rules.grid_columnconfigure(0, weight=1)
        for index, text in enumerate(
            [
                "Wielkość liter ma znaczenie - {Imie} to nie to samo co {imie} i nie zadziała.",
                "Znacznik, którego nie ma na liście powyżej, klient zobaczy w mailu dosłownie, "
                "razem z klamrami. Zakładka Sekwencja ostrzega przed tym na pomarańczowo.",
                "Puste pole u odbiorcy zastępuje wartość domyślna. Jeśli jej nie ustawisz, "
                "w tym miejscu zostanie dziura - np. \"w sprawie firmy .\"",
                "Nowe znaczniki dodajesz w Odbiorcy > Pola. Pojawiają się w szablonie od razu.",
            ]
        ):
            line = ctk.CTkFrame(rules, fg_color="transparent")
            line.grid(row=index, column=0, sticky="ew", pady=2)
            line.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(
                line, text="—", font=theme.font(11), text_color=theme.ACCENT, width=18
            ).grid(row=0, column=0, sticky="nw")
            ctk.CTkLabel(
                line,
                text=text,
                font=theme.font(11),
                text_color=theme.MUTED,
                anchor="w",
                justify="left",
                wraplength=740,
            ).grid(row=0, column=1, sticky="ew")

    def _refresh_placeholders(self) -> None:
        """Lista znaczników odświeża się po każdej zmianie pól."""
        for child in self.placeholder_rows.winfo_children():
            child.destroy()

        wiersze = [("{email}", "adres odbiorcy", "zawsze wypełniony", theme.OK)]
        for field_def in self.store.list_fields():
            if field_def.fallback.strip():
                opis, kolor = "gdy puste: " + field_def.fallback, theme.OK
            else:
                opis, kolor = "brak wartości domyślnej", theme.WARN
            wiersze.append(("{" + field_def.key + "}", field_def.label, opis, kolor))

        for index, (tag, zrodlo, opis, kolor) in enumerate(wiersze):
            ctk.CTkLabel(
                self.placeholder_rows,
                text=tag,
                font=theme.mono(11),
                text_color=theme.ACCENT,
                anchor="w",
                width=110,
            ).grid(row=index, column=0, sticky="w", pady=3)
            ctk.CTkLabel(
                self.placeholder_rows,
                text=zrodlo,
                font=theme.font(11),
                text_color=theme.TEXT,
                anchor="w",
                width=200,
            ).grid(row=index, column=1, sticky="w", pady=3)
            ctk.CTkLabel(
                self.placeholder_rows,
                text=opis,
                font=theme.font(11),
                text_color=kolor,
                anchor="w",
            ).grid(row=index, column=2, sticky="ew", pady=3)

    # ---------------------------------------------------------------- informacje

    def _build_info(self) -> None:
        card = Card(self, "Informacje o aplikacji")
        card.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        body = card.body
        body.grid_columnconfigure(0, weight=0)  # etykieta trzyma stalą szerokość
        body.grid_columnconfigure(1, weight=1)

        self.info_rows: dict[str, ctk.CTkLabel] = {}
        labels = [
            ("version", "Wersja"),
            ("data", "Katalog danych"),
            ("password", "Hasło SMTP trzymane w"),
            ("interval", "Odstęp między mailami"),
            ("hours", "Godziny wysyłki"),
            ("pace", "Maksymalnie na dobę"),
            ("today", "Wysłane dzisiaj"),
            ("queue", "Aktualna kolejka"),
        ]
        for index, (key, label) in enumerate(labels):
            ctk.CTkLabel(
                body, text=label, font=theme.font(12), text_color=theme.MUTED, anchor="w", width=210
            ).grid(row=index, column=0, sticky="w", pady=5)
            value = ctk.CTkLabel(
                body,
                text="",
                font=theme.font(12),
                text_color=theme.TEXT,
                anchor="w",
                justify="left",
                wraplength=520,
            )
            value.grid(row=index, column=1, sticky="ew", pady=5)
            self.info_rows[key] = value

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=len(labels), column=0, columnspan=2, sticky="ew", pady=(14, 0))
        actions.grid_columnconfigure(2, weight=1)
        button(actions, "Otwórz katalog danych", self.open_data_dir, kind="ghost", width=190).grid(
            row=0, column=0, padx=(0, 8)
        )
        button(actions, "Kopia zapasowa listy", self.backup_hint, kind="ghost", width=180).grid(
            row=0, column=1
        )

    def _build_faq(self) -> None:
        card = Card(self, "Dobrze wiedzieć")
        card.grid(row=3, column=0, sticky="ew", pady=(0, 14))
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        notes = [
            (
                "Limit Gmaila",
                "Zwykłe konto przyjmuje około 500 maili na dobę, konto Workspace około 2000. "
                "Przy odstępie 5 minut wychodzi maksymalnie 288 dziennie, więc limit jest "
                "bezpieczny. Schodzenie poniżej 3 minut zwiększa ryzyko blokady konta.",
            ),
            (
                "Zamknięcie aplikacji w trakcie",
                "Krzyżyk domyślnie chowa program do zasobnika i wysyłka leci dalej. "
                "Jeśli naprawdę go zamkniesz, odbiorcy bez maila zostają ze statusem "
                "Oczekuje, a przy włączonym wznawianiu kampania podejmie kolejkę sama "
                "po następnym uruchomieniu. Nikt nie dostanie wiadomości dwa razy.",
            ),
            (
                "Godziny wysyłki",
                "Bez ustawionego okna kampania rozpoczęta wieczorem wysyła maile w nocy. "
                "W Ustawieniach wskaż dni i godziny - poza nimi program czeka i sam wraca "
                "do pracy o wyznaczonej porze.",
            ),
            (
                "Wypisani",
                "Adres oznaczony jako Wypisany jest pomijany na stałe. Nie wróci do kolejki "
                "nawet po zresetowaniu statusów całej listy.",
            ),
            (
                "Co znaczą statusy",
                "Oczekuje - czeka w kolejce.  Wysłany - poszedł, z datą.  "
                "Błąd - serwer odmówił, powód widać w kolumnie Szczegóły.  "
                "Status można cofnąć przyciskiem Resetuj status.",
            ),
            (
                "Gdy wysyłka się nie uda",
                "Aplikacja ponawia próbę (domyślnie 2 razy, co 15 sekund) i leci dalej. "
                "Wyjątkiem jest odrzucone logowanie albo zły adres nadawcy - wtedy kampania "
                "zatrzymuje się od razu, bo kolejne próby i tak by nie przeszły.",
            ),
            (
                "Wersja przenośna",
                "Połóż pusty plik portable.txt obok pliku .exe, a dane zapiszą się w "
                "podkatalogu dane\\ zamiast w profilu użytkownika. Całość można wtedy "
                "nosić na pendrivie.",
            ),
        ]
        for index, (title, text) in enumerate(notes):
            row = ctk.CTkFrame(body, fg_color=theme.SURFACE_HI, corner_radius=10)
            row.grid(row=index, column=0, sticky="ew", pady=4)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                row, text=title, font=theme.font(12, "bold"), text_color=theme.TEXT, anchor="w"
            ).grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 0))
            ctk.CTkLabel(
                row,
                text=text,
                font=theme.font(11),
                text_color=theme.MUTED,
                anchor="w",
                justify="left",
                wraplength=760,
            ).grid(row=1, column=0, sticky="ew", padx=14, pady=(4, 12))

    # ------------------------------------------------------------------- akcje

    def open_data_dir(self) -> None:
        try:
            subprocess.Popen(["explorer", str(data_dir())])
        except Exception as exc:  # noqa: BLE001 - brak eksploratora nie może wywalić okna
            messagebox.showwarning(
                "Nie udało się otworzyć",
                "Katalog z danymi:\n" + str(data_dir()) + "\n\n" + str(exc),
                parent=self.winfo_toplevel(),
            )

    def backup_hint(self) -> None:
        messagebox.showinfo(
            "Kopia zapasowa",
            "Cała lista odbiorców, szablon i historia siedzą w jednym pliku:\n\n"
            + str(data_dir() / "mailer.db")
            + "\n\nSkopiuj go w bezpieczne miejsce przy zamkniętej aplikacji. "
            "Przywrócenie to podmiana tego samego pliku.",
            parent=self.winfo_toplevel(),
        )

    # -------------------------------------------------------------- odświeżanie

    def refresh(self) -> None:
        self._refresh_placeholders()
        config = load_smtp_config(self.store, self.app.vault)
        smtp_ok = not config.validate()
        verified = bool(self.store.get_setting("smtp_verified_at"))
        counts = self.store.counts()
        has_recipients = counts.get("total", 0) > 0
        has_template = bool(
            self.store.get_setting("subject").strip() and self.store.get_setting("body").strip()
        )
        test_sent = bool(self.store.get_setting("test_sent_at"))
        pending = counts.get(STATUS_PENDING, 0)

        self.steps["2fa"].set_done(False)
        self.steps["app_password"].set_done(False)
        self.steps["smtp"].set_done(smtp_ok, "uzupełnione", "brak danych")
        self.steps["verified"].set_done(verified, "połączenie OK", "niesprawdzone")
        self.steps["recipients"].set_done(
            has_recipients, str(counts.get("total", 0)) + " na liście", "lista pusta"
        )
        self.steps["template"].set_done(has_template, "gotowy", "pusty")
        self.steps["test_sent"].set_done(test_sent, "wysłany", "brak testu")
        self.steps["ready"].set_done(
            smtp_ok and has_recipients and has_template and pending > 0,
            "można startować",
            "brakuje kroków",
        )

        interval = self.store.get_int("interval_minutes", 5)
        per_day = int(24 * 60 / interval) if interval else 0
        self.info_rows["version"].configure(
            text=branding.APP_NAME + " " + branding.VERSION
        )
        self.info_rows["data"].configure(text=str(data_dir()))
        self.info_rows["password"].configure(
            text=(
                "Menedżer poświadczeń Windows"
                if _HAS_KEYRING
                else "zaszyfrowany plik lokalny (brak keyring)"
            )
        )
        self.info_rows["interval"].configure(text="co " + str(interval) + " min")
        self.info_rows["hours"].configure(text=SendWindow.from_store(self.store).describe())
        limit = self.store.get_int("daily_limit", 0)
        dzis = self.store.sent_today()
        self.info_rows["today"].configure(
            text=str(dzis) + (" z limitu " + str(limit) if limit else "  (limit wyłączony)")
        )
        self.info_rows["pace"].configure(
            text="do " + str(per_day) + " maili"
            + ("   (limit zwykłego Gmaila to ok. 500)" if per_day > 500 else "")
        )
        self.info_rows["queue"].configure(
            text=str(pending)
            + " w kolejce, "
            + str(counts.get("sent", 0))
            + " wysłanych, "
            + str(counts.get("error", 0))
            + " z błędem"
        )
