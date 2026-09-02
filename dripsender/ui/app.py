"""Główne okno aplikacji: nawigacja, pompa zdarzeń silnika, zamykanie."""

from __future__ import annotations

import os
import queue
from tkinter import messagebox

import customtkinter as ctk

from .. import APP_TITLE, __version__
from ..engine import STATE_LABELS, STATE_PAUSED, STATE_RUNNING, CampaignEngine
from ..inbox import InboxWatcher
from ..paths import resource_path
from ..security import PasswordVault, app_lock_enabled
from ..store import Store
from ..tray import TrayIcon, tray_available
from . import theme
from .about_view import AboutView
from .campaign_view import CampaignView
from .dialogs import LockDialog, ReportDialog
from .guide_view import GuideView
from .log_view import LogView
from .recipients_view import RecipientsView
from .settings_view import SettingsView
from .sequence_view import SequenceView

NAV = [
    ("campaign", "Kampania"),
    ("recipients", "Odbiorcy"),
    ("sequence", "Sekwencja"),
    ("settings", "Ustawienia"),
    ("log", "Historia"),
    ("guide", "Instrukcja"),
    ("about", "O autorze"),
]

EVENT_POLL_MS = 120


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__(fg_color=theme.BG)
        theme.apply_appearance()
        self.title(APP_TITLE)
        self.geometry("1180x760")
        self.minsize(980, 640)

        self.store = Store()
        # Stan z poprzedniego uruchomienia czytamy, zanim go wyzerujemy - służy
        # do automatycznego wznowienia kampanii przerwanej zamknięciem programu.
        poprzedni_stan = self.store.get_setting("campaign_state")
        self.store.set_setting("campaign_state", "idle")
        self.vault = PasswordVault(self.store)
        self.events: queue.Queue = queue.Queue()
        self.engine = CampaignEngine(self.store, self.vault, self.events)
        self.inbox = InboxWatcher(self.store, self.vault, self._on_inbox_result)
        self.tray: TrayIcon | None = None
        self._tray_notified = False

        theme.style_tables(self)
        self._apply_icon()

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_content()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(EVENT_POLL_MS, self._pump_events)
        self._show(self._initial_view())
        self._start_tray()
        self.sync_inbox_watcher()
        if poprzedni_stan == STATE_RUNNING and self.store.get_bool("auto_resume", True):
            self.after(1500, self._auto_resume)

    # ------------------------------------------------------------------ budowa

    def _apply_icon(self) -> None:
        """Ustawia ikonę okna. CustomTkinter potrafi ją zresetować, stąd powtórka."""
        icon = resource_path("assets/icon.ico")
        if not icon.exists():
            return

        def set_icon() -> None:
            try:
                self.iconbitmap(str(icon))
            except Exception:  # noqa: BLE001 - brak ikony nie może blokować startu
                pass

        set_icon()
        self.after(300, set_icon)

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=0, width=230)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(len(NAV) + 1, weight=1)

        header = ctk.CTkFrame(sidebar, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(26, 24))
        ctk.CTkLabel(
            header, text=APP_TITLE, font=theme.font(17, "bold"), text_color=theme.TEXT, anchor="w"
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text="wysyłka po jednym mailu",
            font=theme.font(10),
            text_color=theme.MUTED,
            anchor="w",
        ).grid(row=1, column=0, sticky="w")

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for index, (key, label) in enumerate(NAV, start=1):
            btn = ctk.CTkButton(
                sidebar,
                text="   " + label,
                anchor="w",
                height=42,
                corner_radius=8,
                fg_color="transparent",
                hover_color=theme.SURFACE_HI,
                text_color=theme.MUTED,
                font=theme.font(13),
                command=lambda k=key: self._show(k),
            )
            btn.grid(row=index, column=0, sticky="ew", padx=14, pady=3)
            self.nav_buttons[key] = btn

        footer = ctk.CTkFrame(sidebar, fg_color="transparent")
        footer.grid(row=len(NAV) + 2, column=0, sticky="ew", padx=20, pady=(0, 20))
        self.sidebar_status = ctk.CTkLabel(
            footer,
            text="",
            font=theme.font(10),
            text_color=theme.MUTED,
            anchor="w",
            justify="left",
            wraplength=190,
        )
        self.sidebar_status.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            footer,
            text="wersja " + __version__,
            font=theme.font(10),
            text_color=theme.BORDER,
            anchor="w",
            justify="left",
            wraplength=190,
        ).grid(row=1, column=0, sticky="ew", pady=(8, 0))

    def _build_content(self) -> None:
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.grid(row=0, column=1, sticky="nsew", padx=24, pady=24)
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        self.views = {
            "campaign": CampaignView(container, self),
            "recipients": RecipientsView(container, self),
            "sequence": SequenceView(container, self),
            "settings": SettingsView(container, self),
            "log": LogView(container, self),
            "guide": GuideView(container, self),
            "about": AboutView(container, self),
        }
        for view in self.views.values():
            view.grid(row=0, column=0, sticky="nsew")
            view.grid_remove()
        self.current = "campaign"

    # -------------------------------------------------------------- nawigacja

    def _initial_view(self) -> str:
        """Świeża instalacja startuje od instrukcji, skonfigurowana od kampanii."""
        skonfigurowane = bool(self.store.get_setting("smtp_user").strip())
        ma_odbiorcow = self.store.counts().get("total", 0) > 0
        return "campaign" if (skonfigurowane or ma_odbiorcow) else "guide"

    def go_to(self, key: str) -> None:
        """Publiczne przejście do zakładki - używane przez przyciski w instrukcji."""
        self._show(key)

    def _show(self, key: str) -> None:
        if self.current == "sequence" and key != "sequence":
            self.views["sequence"].save()

        for name, view in self.views.items():
            if name == key:
                view.grid()
            else:
                view.grid_remove()
        for name, btn in self.nav_buttons.items():
            active = name == key
            btn.configure(
                fg_color=theme.ACCENT if active else "transparent",
                text_color="#ffffff" if active else theme.MUTED,
            )
        self.current = key
        view = self.views[key]
        if hasattr(view, "refresh"):
            view.refresh()

    # -------------------------------------------------------------- odświeżanie

    def refresh_all(self) -> None:
        for view in self.views.values():
            if hasattr(view, "refresh") and view is not self.views["sequence"]:
                view.refresh()
        self._update_sidebar_status()

    def on_fields_changed(self) -> None:
        self.views["recipients"].rebuild_table()
        self.views["sequence"].refresh_chips()
        self.refresh_all()

    def _update_sidebar_status(self) -> None:
        counts = self.store.counts()
        self.sidebar_status.configure(
            text="W kolejce: "
            + str(counts.get("pending", 0))
            + "\nWysłane: "
            + str(counts.get("sent", 0))
            + "\nBłędy: "
            + str(counts.get("error", 0))
        )

    # ------------------------------------------------------------ zdarzenia

    def _pump_events(self) -> None:
        if not self.winfo_exists():  # okno zamknięte - nie planujemy kolejnego cyklu
            return
        campaign = self.views["campaign"]
        needs_refresh = False
        try:
            while True:
                event = self.events.get_nowait()
                kind = event.get("type")
                if kind == "tick":
                    campaign.on_tick(
                        event.get("remaining", 0.0),
                        event.get("next_email", ""),
                        event.get("paused", False),
                    )
                elif kind == "sending":
                    campaign.on_sending(event.get("email", ""), event.get("attempt", 1))
                elif kind == "waiting":
                    campaign.on_waiting(
                        event.get("reason", ""),
                        event.get("resume_at", ""),
                        event.get("next_email", ""),
                    )
                elif kind == "daily":
                    needs_refresh = True
                elif kind in ("sent", "error", "state", "log"):
                    needs_refresh = True
                    if kind == "state" and self.tray is not None:
                        self.tray.set_status(event.get("label", ""))
                elif kind == "finished":
                    needs_refresh = True
                    if self.tray is not None and not self.winfo_viewable():
                        self.tray.notify("Kampania zakończona.")
                    self.after(50, lambda summary=event["summary"]: ReportDialog(self, summary).show())
        except queue.Empty:
            pass

        if needs_refresh:
            self.refresh_all()
        self.after(EVENT_POLL_MS, self._pump_events)

    # ------------------------------------------------------ zasobnik systemowy

    def _start_tray(self) -> None:
        if not tray_available() or not self.store.get_bool("minimize_to_tray", True):
            return
        icon = TrayIcon(self, self._restore_window, self._tray_toggle, self._quit_app)
        self.tray = icon if icon.start() else None
        if self.tray:
            self.tray.set_status(STATE_LABELS.get(self.engine.state, ""))

    def sync_inbox_watcher(self) -> None:
        """Uruchamia albo zatrzymuje nasłuch skrzynki zgodnie z ustawieniem."""
        if self.store.get_bool("imap_enabled"):
            if not self.inbox.running:
                self.inbox.start()
        elif self.inbox.running:
            self.inbox.stop()

    def _on_inbox_result(self, wynik) -> None:
        """Wywoływane z wątku nasłuchu - robotę oddajemy wątkowi GUI."""
        if not wynik.changed:
            return
        try:
            self.after(0, self.refresh_all)
        except Exception:  # noqa: BLE001 - okno mogło już zniknąć
            pass

    def restore_from_backup(self, sciezka: str) -> None:
        """Podmienia bazę na kopię i zamyka program - dane wczytają się przy starcie."""
        import shutil

        self.engine.stop("Przywracanie kopii zapasowej.")
        self.engine.shutdown()
        self.inbox.stop()
        cel = self.store.path
        self.store.close()
        try:
            shutil.copyfile(sciezka, cel)
            for dodatek in ("-wal", "-shm"):
                pomocniczy = cel + dodatek
                if os.path.exists(pomocniczy):
                    os.remove(pomocniczy)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "Nie udało się przywrócić",
                "Kopia nie została wgrana:\n" + str(exc),
                parent=self,
            )
            return
        messagebox.showinfo(
            "Kopia przywrócona",
            "Dane zostały wgrane. Program zamknie się teraz - uruchom go ponownie, "
            "aby zobaczyć przywróconą listę.",
            parent=self,
        )
        if self.tray is not None:
            self.tray.stop()
        self.destroy()

    def unlock(self) -> bool:
        """Pyta o PIN przed pokazaniem okna. False = użytkownik zrezygnował."""
        if not app_lock_enabled(self.store):
            return True
        self.withdraw()
        self.update()
        otwarte = LockDialog(self, self.store).show()
        if not otwarte:
            try:
                self.inbox.stop()
                self.engine.shutdown()
                self.store.close()
            except Exception:  # noqa: BLE001
                pass
            self.destroy()
            return False
        self.deiconify()
        return True

    def _restore_window(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def _tray_toggle(self) -> None:
        if self.engine.state == STATE_RUNNING:
            self.engine.pause()
        elif self.engine.state == STATE_PAUSED:
            self.engine.resume()
        self.refresh_all()

    def _auto_resume(self) -> None:
        """Wznawia kampanię przerwaną zamknięciem programu, o ile nic nie brakuje."""
        if self.engine.is_active or self.engine.preflight():
            return
        try:
            self.engine.start()
        except ValueError:
            return
        self.store.log("info", "Kampania wznowiona automatycznie po starcie programu.")
        if self.tray:
            self.tray.notify("Kampania została wznowiona.")
        self.refresh_all()

    # -------------------------------------------------------------- zamykanie

    def _on_close(self) -> None:
        """Krzyżyk chowa do zasobnika, o ile użytkownik tego nie wyłączył."""
        if self.tray is not None and self.store.get_bool("minimize_to_tray", True):
            self.withdraw()
            if not self._tray_notified:
                self.tray.notify(
                    "Program działa dalej w tle - kampania leci. "
                    "Kliknij ikonę, aby wrócić, albo wybierz Zakończ."
                )
                self._tray_notified = True
            return
        self._quit_app()

    def _quit_app(self) -> None:
        self._restore_window()
        if self.engine.is_active:
            if not messagebox.askyesno(
                "Zamknąć aplikację?",
                "Kampania jest w toku. Zamknięcie przerwie wysyłkę - pozostali odbiorcy "
                "zachowają status 'Oczekuje' i po ponownym uruchomieniu wznowisz od nich.\n\n"
                "Zamknąć teraz?",
                parent=self,
            ):
                return
            self.engine.stop("Aplikacja została zamknięta.")
        try:
            self.views["sequence"].save()
        except Exception:  # noqa: BLE001 - zamykanie nie może się wysypać
            pass
        if self.tray is not None:
            self.tray.stop()
        self.inbox.stop()
        self.engine.shutdown()
        self.store.close()
        self.destroy()


def run() -> None:
    app = App()
    if not app.unlock():
        return
    app.mainloop()

