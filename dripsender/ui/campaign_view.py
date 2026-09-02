"""Pulpit kampanii: status, licznik do następnej wysyłki, sterowanie."""

from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from ..engine import STATE_LABELS, STATE_PAUSED, STATE_RUNNING
from ..schedule import SendWindow
from ..store import STATUS_ERROR, STATUS_PENDING, STATUS_SENT
from . import theme
from .widgets import BarChart, Card, StatTile, button


TAG_ALL = "Wszyscy odbiorcy"


def format_countdown(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return str(seconds // 60).rjust(2, "0") + ":" + str(seconds % 60).rjust(2, "0")


class CampaignView(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.store = app.store
        self.engine = app.engine

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._build_status_card()
        self._build_tiles()
        self._build_chart()
        self._build_activity()
        self.refresh()

    # ------------------------------------------------------------------ budowa

    def _build_status_card(self) -> None:
        card = Card(self, "Kampania")
        card.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        body = card.body
        body.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(body, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(1, weight=1)

        self.state_label = ctk.CTkLabel(
            head, text="Gotowa", font=theme.font(22, "bold"), text_color=theme.TEXT, anchor="w"
        )
        self.state_label.grid(row=0, column=0, sticky="w")

        self.countdown_label = ctk.CTkLabel(
            head, text="", font=theme.font(30, "bold"), text_color=theme.ACCENT, anchor="e"
        )
        self.countdown_label.grid(row=0, column=1, sticky="e")

        self.next_label = ctk.CTkLabel(
            body,
            text="Dodaj odbiorców i uzupełnij ustawienia SMTP, aby wystartować.",
            font=theme.font(12),
            text_color=theme.MUTED,
            anchor="w",
        )
        self.next_label.grid(row=1, column=0, sticky="ew", pady=(4, 12))

        self.progress = ctk.CTkProgressBar(
            body, height=8, corner_radius=4, progress_color=theme.ACCENT, fg_color=theme.SURFACE_HI
        )
        self.progress.grid(row=2, column=0, sticky="ew")
        self.progress.set(0)

        self.progress_label = ctk.CTkLabel(
            body, text="", font=theme.font(11), text_color=theme.MUTED, anchor="w"
        )
        self.progress_label.grid(row=3, column=0, sticky="ew", pady=(6, 14))

        grupa = ctk.CTkFrame(body, fg_color="transparent")
        grupa.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        ctk.CTkLabel(
            grupa, text="Wyślij do grupy", font=theme.font(12), text_color=theme.MUTED,
            anchor="w", width=130,
        ).grid(row=0, column=0, sticky="w")
        self.tag_var = ctk.StringVar(value=TAG_ALL)
        self.tag_menu = ctk.CTkOptionMenu(
            grupa,
            values=[TAG_ALL],
            variable=self.tag_var,
            command=self._on_tag_change,
            width=220,
            height=32,
            corner_radius=8,
            fg_color=theme.SURFACE_HI,
            button_color=theme.BORDER,
            button_hover_color=theme.ACCENT,
            text_color=theme.TEXT,
            font=theme.font(12),
        )
        self.tag_menu.grid(row=0, column=1, sticky="w")
        self.sequence_label = ctk.CTkLabel(
            grupa, text="", font=theme.font(11), text_color=theme.MUTED, anchor="w"
        )
        self.sequence_label.grid(row=0, column=2, sticky="w", padx=(18, 0))

        controls = ctk.CTkFrame(body, fg_color="transparent")
        controls.grid(row=5, column=0, sticky="ew")
        controls.grid_columnconfigure(4, weight=1)

        self.start_button = button(controls, "Start kampanii", self._start, width=150)
        self.start_button.grid(row=0, column=0, padx=(0, 8))
        self.pause_button = button(controls, "Pauza", self._toggle_pause, kind="ghost", width=110)
        self.pause_button.grid(row=0, column=1, padx=(0, 8))
        self.stop_button = button(controls, "Stop", self._stop, kind="danger", width=100)
        self.stop_button.grid(row=0, column=2, padx=(0, 8))
        self.skip_button = button(
            controls, "Wyślij następny teraz", self._skip, kind="ghost", width=180
        )
        self.skip_button.grid(row=0, column=3)

    def _build_tiles(self) -> None:
        tiles = ctk.CTkFrame(self, fg_color="transparent")
        tiles.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        for column in range(4):
            tiles.grid_columnconfigure(column, weight=1)

        self.tile_total = StatTile(tiles, "Odbiorcy razem")
        self.tile_total.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.tile_sent = StatTile(tiles, "Wysłane", color=theme.OK)
        self.tile_sent.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        self.tile_pending = StatTile(tiles, "W kolejce", color=theme.ACCENT)
        self.tile_pending.grid(row=0, column=2, sticky="ew", padx=(0, 10))
        self.tile_errors = StatTile(tiles, "Błędy", color=theme.ERR)
        self.tile_errors.grid(row=0, column=3, sticky="ew")

    def _build_chart(self) -> None:
        card = Card(self, "Wysyłka w ostatnich 14 dniach")
        card.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        self.chart = BarChart(card.body, height=140)
        self.chart.grid(row=0, column=0, sticky="ew")

    def _build_activity(self) -> None:
        card = Card(self, "Ostatnie zdarzenia")
        card.grid(row=3, column=0, sticky="nsew")
        card.body.grid_rowconfigure(0, weight=1)
        self.activity = ctk.CTkScrollableFrame(card.body, fg_color="transparent")
        self.activity.grid(row=0, column=0, sticky="nsew")
        self.activity.grid_columnconfigure(0, weight=1)

    # ---------------------------------------------------------------- działania

    def _start(self) -> None:
        try:
            self.engine.start()
        except ValueError as exc:
            messagebox.showwarning(
                "Nie można wystartować",
                "Zanim ruszy wysyłka, popraw:\n\n" + str(exc),
                parent=self.winfo_toplevel(),
            )
            return
        self.refresh()

    def _toggle_pause(self) -> None:
        if self.engine.state == STATE_RUNNING:
            self.engine.pause()
        elif self.engine.state == STATE_PAUSED:
            self.engine.resume()
        self.refresh()

    def _stop(self) -> None:
        if not self.engine.is_active:
            return
        if messagebox.askyesno(
            "Zatrzymać kampanię?",
            "Wysyłka zostanie przerwana. Pozostali odbiorcy zachowają status "
            "'Oczekuje', więc możesz wznowić kampanię później.",
            parent=self.winfo_toplevel(),
        ):
            self.engine.stop()

    def _skip(self) -> None:
        if self.engine.is_active:
            self.engine.send_next_now()

    # ------------------------------------------------------------------ odświeżanie

    def _on_tag_change(self, _value: str = "") -> None:
        wybrana = self.tag_var.get()
        self.store.set_setting("target_tag", "" if wybrana == TAG_ALL else wybrana)
        self.refresh()

    def _refresh_tag_menu(self) -> None:
        wartosci = [TAG_ALL] + self.store.all_tags()
        self.tag_menu.configure(values=wartosci)
        zapisana = self.store.get_setting("target_tag", "")
        self.tag_var.set(zapisana if zapisana in wartosci else TAG_ALL)
        self.tag_menu.configure(state="disabled" if self.engine.is_active else "normal")
        kroki = self.store.sequence()
        if kroki:
            self.sequence_label.configure(
                text="Sekwencja: " + str(len(kroki)) + " "
                + ("krok" if len(kroki) == 1 else "kroki/kroków")
                + " (" + ", ".join(k.name for k in kroki) + ")"
            )
        else:
            self.sequence_label.configure(text="Brak włączonych kroków sekwencji.")

    def refresh(self) -> None:
        self._refresh_tag_menu()
        tag = self.store.get_setting("target_tag", "")
        counts = self.store.counts(tag)
        total = counts.get("total", 0)
        sent = counts.get(STATUS_SENT, 0)
        pending = counts.get(STATUS_PENDING, 0)
        errors = counts.get(STATUS_ERROR, 0)

        self.tile_total.set(total)
        self.tile_sent.set(sent)
        self.tile_pending.set(pending)
        self.tile_errors.set(errors)

        done = sent + errors
        self.progress.set(done / total if total else 0)
        dzis = self.store.sent_today()
        limit = self.store.get_int("daily_limit", 0)
        licznik = "dziś wysłano: " + str(dzis)
        if limit > 0:
            licznik += " z " + str(limit)
            if dzis >= limit:
                licznik += "  (limit wyczerpany)"
        self.progress_label.configure(
            text="Obsłużono " + str(done) + " z " + str(total) + " odbiorców    ·    " + licznik
        )

        state = self.engine.state
        self.state_label.configure(text=STATE_LABELS.get(state, state))
        active = self.engine.is_active
        self.start_button.configure(state="disabled" if active else "normal")
        self.pause_button.configure(
            state="normal" if active else "disabled",
            text="Wznów" if state == STATE_PAUSED else "Pauza",
        )
        self.stop_button.configure(state="normal" if active else "disabled")
        self.skip_button.configure(state="normal" if active else "disabled")

        if not active:
            self.countdown_label.configure(text="")
            interval = self.store.get_int("interval_minutes", 5)
            if pending:
                self.next_label.configure(
                    text=str(pending)
                    + " odbiorców czeka w kolejce. Odstęp między mailami: "
                    + str(interval)
                    + " min - cała lista zajmie około "
                    + _duration_text(max(0, pending - 1) * interval)
                    + "."
                )
            else:
                self.next_label.configure(text="Brak odbiorców oczekujących na wysyłkę.")
            window = SendWindow.from_store(self.store)
            if window.enabled:
                self.next_label.configure(
                    text=self.next_label.cget("text")
                    + "\nGodziny wysyłki: "
                    + window.describe()
                    + "."
                )

        self.chart.set_data(
            self.store.sent_history(14), self.store.get_int("daily_limit", 0)
        )
        self.refresh_activity()

    def refresh_activity(self) -> None:
        for child in self.activity.winfo_children():
            child.destroy()
        rows = self.store.list_log(limit=12)
        if not rows:
            ctk.CTkLabel(
                self.activity,
                text="Tu pojawi się historia wysyłki.",
                font=theme.font(11),
                text_color=theme.MUTED,
                anchor="w",
            ).grid(row=0, column=0, sticky="ew", pady=4)
            return
        for index, row in enumerate(rows):
            line = ctk.CTkFrame(self.activity, fg_color="transparent")
            line.grid(row=index, column=0, sticky="ew", pady=2)
            line.grid_columnconfigure(2, weight=1)
            ctk.CTkLabel(
                line,
                text=row["ts"][-8:],
                font=theme.mono(10),
                text_color=theme.MUTED,
                width=64,
                anchor="w",
            ).grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(
                line,
                text=row["email"] or "-",
                font=theme.font(11),
                text_color=theme.TEXT,
                width=220,
                anchor="w",
            ).grid(row=0, column=1, sticky="w", padx=(8, 8))
            ctk.CTkLabel(
                line,
                text=row["message"],
                font=theme.font(11),
                text_color=theme.LEVEL_COLORS.get(row["level"], theme.MUTED),
                anchor="w",
                justify="left",
            ).grid(row=0, column=2, sticky="ew")

    def on_tick(self, remaining: float, next_email: str, paused: bool) -> None:
        if paused:
            self.countdown_label.configure(text="PAUZA", text_color=theme.WARN)
            self.next_label.configure(text="Wstrzymano. Kliknij 'Wznów', aby kontynuować.")
            return
        self.countdown_label.configure(text=format_countdown(remaining), text_color=theme.ACCENT)
        if next_email:
            self.next_label.configure(text="Następny mail poleci do: " + next_email)

    def on_waiting(self, reason: str, resume_at: str, next_email: str) -> None:
        """Kampania czeka - poza godzinami wysyłki albo po wyczerpaniu limitu."""
        self.countdown_label.configure(text="CZEKAM", text_color=theme.WARN)
        tekst = reason + " Wznowię " + resume_at + "."
        if next_email:
            tekst += "\nNastępny w kolejce: " + next_email
        self.next_label.configure(text=tekst)

    def on_sending(self, email: str, attempt: int) -> None:
        self.countdown_label.configure(text="wysyłam", text_color=theme.OK)
        suffix = "" if attempt == 1 else "  (próba " + str(attempt) + ")"
        self.next_label.configure(text="Wysyłam wiadomość do: " + email + suffix)


def _duration_text(minutes: int) -> str:
    if minutes < 60:
        return str(minutes) + " min"
    hours, rest = divmod(minutes, 60)
    if not rest:
        return str(hours) + " h"
    return str(hours) + " h " + str(rest) + " min"
