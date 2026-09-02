"""Ikona w zasobniku systemowym i autostart z Windows.

Dzięki temu długa kampania (kilkaset adresów co 5 minut to nawet kilka dni)
może chodzić w tle, bez okna zajmującego pasek zadań.
"""

from __future__ import annotations

import sys
import threading
from typing import Callable

from . import branding
from .paths import is_frozen, resource_path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

try:  # pragma: no cover - zależne od systemu
    import pystray
    from PIL import Image

    _HAS_TRAY = True
except Exception:  # pragma: no cover
    pystray = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    _HAS_TRAY = False

try:  # pragma: no cover - tylko Windows
    import winreg

    _HAS_REGISTRY = True
except Exception:  # pragma: no cover
    winreg = None  # type: ignore[assignment]
    _HAS_REGISTRY = False


def tray_available() -> bool:
    return _HAS_TRAY


# ----------------------------------------------------------------- autostart


def autostart_supported() -> tuple[bool, str]:
    """Czy da się ustawić autostart i dlaczego ewentualnie nie."""
    if not _HAS_REGISTRY:
        return False, "Autostart działa tylko w systemie Windows."
    if not is_frozen():
        return False, (
            "Autostart działa dopiero w wersji spakowanej do .exe - "
            "w trybie deweloperskim nie ma czego uruchamiać."
        )
    return True, ""


def is_autostart_enabled() -> bool:
    if not _HAS_REGISTRY:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, branding.APP_SLUG)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_autostart(enabled: bool) -> tuple[bool, str]:
    """Dopisuje lub usuwa wpis w rejestrze. Zwraca (udało się, komunikat)."""
    ok, powod = autostart_supported()
    if not ok:
        return False, powod
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(
                    key, branding.APP_SLUG, 0, winreg.REG_SZ, '"' + sys.executable + '"'
                )
            else:
                try:
                    winreg.DeleteValue(key, branding.APP_SLUG)
                except FileNotFoundError:
                    pass
    except OSError as exc:
        return False, "Nie udało się zapisać w rejestrze: " + str(exc)
    return True, "Autostart włączony." if enabled else "Autostart wyłączony."


# --------------------------------------------------------------------- ikona


class TrayIcon:
    """Ikona w zasobniku. Wszystkie akcje wracają do wątku GUI przez ``after``."""

    def __init__(
        self,
        root,
        on_show: Callable[[], None],
        on_toggle: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self.root = root
        self.on_show = on_show
        self.on_toggle = on_toggle
        self.on_quit = on_quit
        self.icon = None
        self._thread: threading.Thread | None = None
        self._status = "Gotowa"

    def _marshal(self, callback: Callable[[], None]) -> Callable[..., None]:
        """Menu klika się w wątku pystray - robotę oddajemy wątkowi Tkintera."""

        def handler(*_args) -> None:
            try:
                self.root.after(0, callback)
            except Exception:  # noqa: BLE001 - okno mogło już zniknąć
                pass

        return handler

    def _load_image(self):
        path = resource_path("assets/icon.png")
        if path.exists():
            return Image.open(path)
        return Image.new("RGB", (64, 64), (76, 141, 255))

    def start(self) -> bool:
        if not _HAS_TRAY or self.icon is not None:
            return False
        menu = pystray.Menu(
            pystray.MenuItem("Pokaż okno", self._marshal(self.on_show), default=True),
            pystray.MenuItem("Wstrzymaj / wznów", self._marshal(self.on_toggle)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Zakończ", self._marshal(self.on_quit)),
        )
        try:
            self.icon = pystray.Icon(
                branding.APP_SLUG, self._load_image(), branding.APP_NAME, menu
            )
            self._thread = threading.Thread(target=self.icon.run, name="tray", daemon=True)
            self._thread.start()
        except Exception:  # noqa: BLE001 - brak zasobnika nie może wywalić aplikacji
            self.icon = None
            return False
        return True

    def set_status(self, status: str) -> None:
        self._status = status
        if self.icon is not None:
            try:
                self.icon.title = branding.APP_NAME + " - " + status
            except Exception:  # noqa: BLE001
                pass

    def notify(self, message: str, title: str = "") -> None:
        if self.icon is None:
            return
        try:
            self.icon.notify(message, title or branding.APP_NAME)
        except Exception:  # noqa: BLE001 - powiadomienia bywają zablokowane
            pass

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:  # noqa: BLE001
                pass
            self.icon = None
