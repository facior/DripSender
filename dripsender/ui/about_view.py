"""Zakładka "O autorze": kto zrobił aplikację, kontakt i na czym stoi."""

from __future__ import annotations

import webbrowser
from tkinter import messagebox

import customtkinter as ctk

from .. import branding
from . import theme
from .widgets import Card, button

PLACEHOLDER_HINT = "do uzupełnienia w pliku branding.py"


class AboutView(ctk.CTkScrollableFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_author()
        self._build_features()
        self._build_privacy()
        self._build_footer()

    # ------------------------------------------------------------------ nagłówek

    def _build_header(self) -> None:
        card = Card(self)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            body,
            text=branding.APP_NAME,
            font=theme.font(30, "bold"),
            text_color=theme.TEXT,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            body,
            text="wersja " + branding.VERSION + "   ·   " + branding.APP_TAGLINE,
            font=theme.font(12),
            text_color=theme.ACCENT,
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", pady=(2, 10))
        ctk.CTkLabel(
            body,
            text=branding.APP_DESCRIPTION,
            font=theme.font(12),
            text_color=theme.MUTED,
            anchor="w",
            justify="left",
            wraplength=720,
        ).grid(row=2, column=0, sticky="ew")

    # --------------------------------------------------------------------- autor

    def _build_author(self) -> None:
        card = Card(
            self,
            "Autor",
            "Masz pytanie do działania programu albo pomysł na zmianę? Napisz.",
        )
        card.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        body = card.body
        body.grid_columnconfigure(0, weight=0)  # etykieta trzyma stalą szerokość
        body.grid_columnconfigure(1, weight=1)

        row_index = 0
        for label, value, filled in branding.author_fields():
            if not filled and label in ("Rola", "Telefon", "Strona www"):
                continue  # pola nieobowiązkowe pomijamy, gdy puste
            ctk.CTkLabel(
                body, text=label, font=theme.font(12), text_color=theme.MUTED, anchor="w", width=180
            ).grid(row=row_index, column=0, sticky="w", pady=6)
            ctk.CTkLabel(
                body,
                text=value if filled else PLACEHOLDER_HINT,
                font=theme.font(12, "bold" if filled else "normal"),
                text_color=theme.TEXT if filled else theme.WARN,
                anchor="w",
            ).grid(row=row_index, column=1, sticky="ew", pady=6)
            row_index += 1

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=row_index, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        actions.grid_columnconfigure(3, weight=1)

        column = 0
        if branding.AUTHOR_EMAIL:
            button(actions, "Napisz e-mail", self.write_email, width=140).grid(
                row=0, column=column, padx=(0, 8)
            )
            column += 1
            button(
                actions, "Kopiuj adres", self.copy_email, kind="ghost", width=130
            ).grid(row=0, column=column, padx=(0, 8))
            column += 1
        if branding.AUTHOR_WWW:
            button(
                actions,
                "Otwórz stronę",
                lambda: webbrowser.open(branding.AUTHOR_WWW),
                kind="ghost",
                width=140,
            ).grid(row=0, column=column)

    # ------------------------------------------------------------- co potrafi

    def _bullet_card(self, row: int, title: str, subtitle: str, items, mark: str, color: str) -> None:
        """Karta z listą pozycji: znacznik, pogrubiony nagłówek i opis pod spodem."""
        card = Card(self, title, subtitle)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 14))
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        for index, (name, description) in enumerate(items):
            line = ctk.CTkFrame(body, fg_color=theme.SURFACE_HI, corner_radius=10)
            line.grid(row=index, column=0, sticky="ew", pady=3)
            line.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(
                line, text=mark, font=theme.font(13, "bold"), text_color=color, width=26
            ).grid(row=0, column=0, rowspan=2, padx=(14, 8), pady=12)
            ctk.CTkLabel(
                line, text=name, font=theme.font(12, "bold"), text_color=theme.TEXT, anchor="w"
            ).grid(row=0, column=1, sticky="ew", pady=(12, 0), padx=(0, 14))
            ctk.CTkLabel(
                line,
                text=description,
                font=theme.font(11),
                text_color=theme.MUTED,
                anchor="w",
                justify="left",
                wraplength=680,
            ).grid(row=1, column=1, sticky="ew", pady=(2, 12), padx=(0, 14))

    def _build_features(self) -> None:
        self._bullet_card(
            2,
            "Co potrafi",
            "Skrót tego, co program bierze na siebie.",
            branding.FEATURES,
            "•",
            theme.ACCENT,
        )

    def _build_privacy(self) -> None:
        self._bullet_card(
            3,
            "Twoje dane zostają u Ciebie",
            "Lista klientów i hasło do poczty to wrażliwe rzeczy - oto co się z nimi dzieje.",
            branding.PRIVACY_NOTES,
            "✓",
            theme.OK,
        )

    def _build_footer(self) -> None:
        card = Card(self, "Licencja i prawa")
        card.grid(row=4, column=0, sticky="ew")
        ctk.CTkLabel(
            card.body,
            text=branding.LICENSE
            + "\n© "
            + branding.YEAR
            + ("  " + branding.AUTHOR_NAME if branding.AUTHOR_NAME else ""),
            font=theme.font(11),
            text_color=theme.MUTED,
            anchor="w",
            justify="left",
            wraplength=720,
        ).grid(row=0, column=0, sticky="ew")

    # -------------------------------------------------------------------- akcje

    def write_email(self) -> None:
        subject = branding.APP_NAME + " " + branding.VERSION + " - pytanie"
        webbrowser.open("mailto:" + branding.AUTHOR_EMAIL + "?subject=" + subject.replace(" ", "%20"))

    def copy_email(self) -> None:
        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(branding.AUTHOR_EMAIL)
        messagebox.showinfo(
            "Skopiowano",
            "Adres " + branding.AUTHOR_EMAIL + " trafił do schowka.",
            parent=root,
        )

    def refresh(self) -> None:
        """Zawartość jest statyczna - nic nie trzeba przeliczać."""
