"""Automatyczna aktualizacja programu z serwera.

Program pobiera plik opisu wydania (JSON), porównuje wersje i - jeśli jest nowsza -
ściąga nowy plik ``.exe``, sprawdza jego sumę kontrolną i podmienia się na niego.

Bezpieczeństwo, bo to najwrażliwsze miejsce w całej aplikacji:

* adres musi być **https** (wyjątek tylko dla localhost, na potrzeby testów),
* pobrany plik musi mieć **sumę SHA-256 zgodną z opisem wydania** - inaczej ląduje
  w koszu i instalacja nie rusza,
* program **nigdy nie cofa się do starszej wersji**,
* pobieranie ma limit rozmiaru, żeby podstawiony plik nie zapchał dysku.

Opis wydania (``update.json``)::

    {
      "version": "1.4.0",
      "url": "https://.../DripSender-1.4.0.exe",
      "sha256": "e3b0c44298fc1c149afbf4c8996fb924...",
      "notes": "Co nowego w tej wersji"
    }
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from . import branding
from .paths import is_frozen

LIMIT_POBIERANIA = 300 * 1024 * 1024  # 300 MB - z ogromnym zapasem na plik ~45 MB
TIMEOUT = 20
KAWALEK = 64 * 1024
LOKALNE = {"127.0.0.1", "localhost", "::1"}


class UpdateError(Exception):
    """Problem z aktualizacją, opisany po ludzku."""


@dataclass
class Wydanie:
    version: str
    url: str
    sha256: str
    notes: str = ""

    @property
    def opis(self) -> str:
        return self.notes.strip() or "Autor nie dołączył opisu zmian."


def wersja_krotka(tekst: str) -> tuple[int, ...]:
    """'1.10.2' -> (1, 10, 2). Nieliczbowe końcówki są pomijane."""
    czesci = re.findall(r"\d+", tekst or "")
    return tuple(int(c) for c in czesci[:4]) or (0,)


def nowsza(kandydat: str, obecna: str) -> bool:
    return wersja_krotka(kandydat) > wersja_krotka(obecna)


def aktualizacje_dostepne() -> tuple[bool, str]:
    """Czy program w ogóle może się zaktualizować."""
    if not is_frozen():
        return False, (
            "Aktualizacja podmienia plik .exe, więc działa dopiero w wersji spakowanej - "
            "w trybie deweloperskim nie ma czego podmieniać."
        )
    return True, ""


def _sprawdz_adres(url: str) -> None:
    rozbior = urlparse(url or "")
    if rozbior.scheme == "https":
        return
    if rozbior.scheme == "http" and rozbior.hostname in LOKALNE:
        return  # tylko na potrzeby testów na tym komputerze
    raise UpdateError(
        "Adres aktualizacji musi zaczynać się od https:// - inaczej ktoś po drodze "
        "mógłby podstawić własny plik."
    )


def sprawdz(url: str, obecna: str | None = None) -> Wydanie | None:
    """Pobiera opis wydania. Zwraca ``Wydanie`` tylko gdy jest nowsze niż obecne."""
    url = (url or "").strip()
    if not url:
        raise UpdateError("Nie ustawiono adresu z aktualizacjami.")
    _sprawdz_adres(url)
    obecna = obecna or branding.VERSION

    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as odpowiedz:
            surowe = odpowiedz.read(1024 * 1024)
    except urllib.error.HTTPError as exc:
        raise UpdateError("Serwer odpowiedział błędem " + str(exc.code) + ".") from exc
    except urllib.error.URLError as exc:
        raise UpdateError("Brak połączenia z serwerem aktualizacji: " + str(exc.reason)) from exc
    except Exception as exc:  # noqa: BLE001
        raise UpdateError("Nie udało się pobrać informacji o wersji: " + str(exc)) from exc

    try:
        dane = json.loads(surowe.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("Plik z opisem wydania jest uszkodzony.") from exc
    if not isinstance(dane, dict):
        raise UpdateError("Plik z opisem wydania ma nieoczekiwaną postać.")

    wersja = str(dane.get("version", "")).strip()
    plik = str(dane.get("url", "")).strip()
    suma = str(dane.get("sha256", "")).strip().lower()
    if not wersja or not plik or not suma:
        raise UpdateError("Opis wydania nie zawiera wersji, adresu pliku albo sumy kontrolnej.")
    if not re.fullmatch(r"[0-9a-f]{64}", suma):
        raise UpdateError("Suma kontrolna w opisie wydania jest nieprawidłowa.")
    _sprawdz_adres(plik)

    if not nowsza(wersja, obecna):
        return None
    return Wydanie(wersja, plik, suma, str(dane.get("notes", "")))


def pobierz(
    wydanie: Wydanie, katalog: str | None = None, postep: Callable[[int, int], None] | None = None
) -> Path:
    """Ściąga plik i sprawdza sumę kontrolną. Niezgodna suma = plik do kosza."""
    _sprawdz_adres(wydanie.url)
    katalog_docelowy = Path(katalog or tempfile.gettempdir())
    katalog_docelowy.mkdir(parents=True, exist_ok=True)
    cel = katalog_docelowy / (branding.APP_SLUG + "-" + wydanie.version + ".exe")

    skrot = hashlib.sha256()
    pobrane = 0
    try:
        with urllib.request.urlopen(wydanie.url, timeout=TIMEOUT) as odpowiedz:
            calosc = int(odpowiedz.headers.get("Content-Length") or 0)
            if calosc > LIMIT_POBIERANIA:
                raise UpdateError("Plik aktualizacji jest podejrzanie duży - przerwano.")
            with open(cel, "wb") as plik:
                while True:
                    kawalek = odpowiedz.read(KAWALEK)
                    if not kawalek:
                        break
                    pobrane += len(kawalek)
                    if pobrane > LIMIT_POBIERANIA:
                        raise UpdateError("Plik aktualizacji przekroczył dozwolony rozmiar.")
                    plik.write(kawalek)
                    skrot.update(kawalek)
                    if postep:
                        postep(pobrane, calosc)
    except UpdateError:
        cel.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        cel.unlink(missing_ok=True)
        raise UpdateError("Pobieranie nie powiodło się: " + str(exc)) from exc

    if skrot.hexdigest() != wydanie.sha256:
        cel.unlink(missing_ok=True)
        raise UpdateError(
            "Suma kontrolna pobranego pliku nie zgadza się z opisem wydania. "
            "Plik został usunięty, aktualizacja przerwana."
        )
    return cel


SKRYPT_PODMIANY = """@echo off
chcp 65001 >nul
rem Czeka az program sie zamknie, podmienia plik i uruchamia nowa wersje.
:czekaj
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
    ping -n 2 127.0.0.1 >nul
    goto czekaj
)
move /Y "{nowy}" "{docelowy}" >nul
if errorlevel 1 (
    echo Nie udalo sie podmienic pliku programu.
    pause
    exit /b 1
)
start "" "{docelowy}"
del "%~f0"
"""


def zainstaluj(nowy_plik: str | Path, docelowy: str | Path | None = None) -> Path:
    """Uruchamia skrypt, który po zamknięciu programu podmieni plik i wystartuje go.

    Windows nie pozwala nadpisać działającego ``.exe``, więc robotę wykonuje mały
    plik wsadowy odpalony obok - czeka na koniec naszego procesu i dopiero podmienia.
    """
    nowy_plik = Path(nowy_plik)
    if not nowy_plik.is_file():
        raise UpdateError("Nie znaleziono pobranego pliku aktualizacji.")
    cel = Path(docelowy or sys.executable)

    skrypt = Path(tempfile.gettempdir()) / (branding.APP_SLUG + "-aktualizacja.bat")
    skrypt.write_text(
        SKRYPT_PODMIANY.format(pid=os.getpid(), nowy=nowy_plik, docelowy=cel),
        encoding="utf-8",
    )
    try:
        subprocess.Popen(
            ["cmd", "/c", str(skrypt)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0),
            close_fds=True,
        )
    except Exception as exc:  # noqa: BLE001
        raise UpdateError("Nie udało się uruchomić instalatora: " + str(exc)) from exc
    return skrypt
