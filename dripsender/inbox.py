"""Nasłuch skrzynki odbiorczej przez IMAP.

Czyta pocztę nadawcy i rozpoznaje trzy rzeczy:

* **odpowiedź** - odbiorca odpisał, więc wypada z dalszych kroków sekwencji,
* **odbicie** - adres nie istnieje albo skrzynka odrzuciła wiadomość,
* **prośbę o wypisanie** - odpowiedź zaczynająca się od słowa STOP.

Program niczego nie kasuje ani nie przenosi - tylko czyta.
"""

from __future__ import annotations

import email
import imaplib
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import Message
from email.utils import parseaddr
from typing import Callable

from .security import PasswordVault
from .store import (
    STATUS_BOUNCED,
    STATUS_REPLIED,
    STATUS_UNSUBSCRIBED,
    Store,
    normalize_email,
)

EMAIL_IN_TEXT = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
MESSAGE_ID_RE = re.compile(r"<[^>]+>")

# Adresy, z których przychodzą raporty niedostarczenia.
DAEMON_HINTS = ("mailer-daemon", "postmaster", "mail-daemon", "no-reply@")


class InboxError(Exception):
    """Problem z odczytem skrzynki, opisany po ludzku."""


@dataclass
class ImapConfig:
    host: str = "imap.gmail.com"
    port: int = 993
    user: str = ""
    password: str = ""
    folder: str = "INBOX"
    lookback_days: int = 14
    stop_word: str = "STOP"
    timeout: int = 30

    @classmethod
    def from_store(cls, store: Store, vault: PasswordVault) -> "ImapConfig":
        user = store.get_setting("smtp_user").strip()
        return cls(
            host=store.get_setting("imap_host", "imap.gmail.com").strip(),
            port=store.get_int("imap_port", 993),
            user=user,
            password=vault.get(user),
            folder=store.get_setting("imap_folder", "INBOX").strip() or "INBOX",
            lookback_days=max(1, store.get_int("imap_lookback_days", 14)),
            stop_word=store.get_setting("imap_stop_word", "STOP").strip().upper() or "STOP",
        )

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.host:
            problems.append("Brak serwera IMAP.")
        if not self.user:
            problems.append("Brak loginu - uzupełnij najpierw konto SMTP.")
        if not self.password:
            problems.append("Brak hasła aplikacji.")
        return problems


@dataclass
class InboxResult:
    checked: int = 0
    replies: int = 0
    bounces: int = 0
    unsubscribes: int = 0
    error: str = ""

    @property
    def changed(self) -> int:
        return self.replies + self.bounces + self.unsubscribes

    def describe(self) -> str:
        if self.error:
            return self.error
        if not self.checked:
            return "Brak nowych wiadomości w skrzynce."
        czesci = ["Sprawdzono " + str(self.checked) + " wiadomości"]
        if self.replies:
            czesci.append("odpowiedzi: " + str(self.replies))
        if self.bounces:
            czesci.append("odbicia: " + str(self.bounces))
        if self.unsubscribes:
            czesci.append("wypisania: " + str(self.unsubscribes))
        if not self.changed:
            czesci.append("nic nowego dla kampanii")
        return ", ".join(czesci) + "."


def _decode(value) -> str:
    """Nagłówki bywają zakodowane MIME - sprowadzamy je do zwykłego tekstu."""
    if not value:
        return ""
    try:
        parts = email.header.decode_header(value)
    except Exception:  # noqa: BLE001
        return str(value)
    wynik = []
    for tekst, kodowanie in parts:
        if isinstance(tekst, bytes):
            try:
                wynik.append(tekst.decode(kodowanie or "utf-8", errors="replace"))
            except LookupError:
                wynik.append(tekst.decode("utf-8", errors="replace"))
        else:
            wynik.append(tekst)
    return "".join(wynik)


def _plain_text(message: Message, limit: int = 4000) -> str:
    """Wyciąga tekstową treść wiadomości, pomijając załączniki."""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_type() == "text/plain":
                try:
                    surowe = part.get_payload(decode=True) or b""
                except Exception:  # noqa: BLE001
                    continue
                kodowanie = part.get_content_charset() or "utf-8"
                try:
                    return surowe.decode(kodowanie, errors="replace")[:limit]
                except LookupError:
                    return surowe.decode("utf-8", errors="replace")[:limit]
        return ""
    try:
        surowe = message.get_payload(decode=True) or b""
    except Exception:  # noqa: BLE001
        return ""
    kodowanie = message.get_content_charset() or "utf-8"
    try:
        return surowe.decode(kodowanie, errors="replace")[:limit]
    except LookupError:
        return surowe.decode("utf-8", errors="replace")[:limit]


def _referenced_ids(message: Message) -> list[str]:
    surowe = " ".join(
        filter(None, [message.get("In-Reply-To", ""), message.get("References", "")])
    )
    return MESSAGE_ID_RE.findall(surowe)


def _bounce_candidates(message: Message, text: str) -> list[str]:
    """Adresy, których może dotyczyć raport - od najpewniejszego.

    Raport zawiera zwykle także nasz własny adres, więc wybór właściwego
    zostawiamy warstwie wyżej: bierze pierwszy, który jest na liście odbiorców.
    """
    kandydaci: list[str] = []
    for part in message.walk():
        if part.get_content_type() == "message/delivery-status":
            ladunek = part.get_payload()
            if not isinstance(ladunek, list):
                continue
            for podczesc in ladunek:
                if not isinstance(podczesc, Message):
                    continue
                for naglowek in ("Final-Recipient", "Original-Recipient"):
                    znalezione = EMAIL_IN_TEXT.search(podczesc.get(naglowek, "") or "")
                    if znalezione:
                        kandydaci.append(znalezione.group(0))
    kandydaci.extend(EMAIL_IN_TEXT.findall(text or ""))
    widziane: list[str] = []
    for adres in kandydaci:
        if adres.lower() not in [w.lower() for w in widziane]:
            widziane.append(adres)
    return widziane


def _strip_quotes(text: str) -> str:
    """Odcina cytat poprzedniej wiadomości i stopkę - liczy się tylko to, co napisał człowiek."""
    linie: list[str] = []
    for linia in (text or "").splitlines():
        obcieta = linia.strip()
        if obcieta.startswith(">"):
            continue
        if obcieta in ("--", "-- ", "__", "----"):
            break
        niska = obcieta.lower()
        if "napisał" in niska and (
            niska.startswith("w dniu") or niska.startswith("dnia") or niska.startswith("on ")
        ):
            break
        if niska.startswith("od:") or niska.startswith("from:") or niska.startswith("wysłano:"):
            break
        linie.append(linia)
    return "\n".join(linie).strip()


def _looks_like_bounce(from_address: str, subject: str, message: Message) -> bool:
    nadawca = from_address.lower()
    if any(hint in nadawca for hint in DAEMON_HINTS):
        return True
    if message.get_content_type() == "multipart/report":
        return True
    temat = subject.lower()
    return any(
        fraza in temat
        for fraza in (
            "undelivered",
            "undeliverable",
            "delivery status notification",
            "returned mail",
            "failure notice",
            "nie dostarczono",
        )
    )


def _is_stop_request(text: str, stop_word: str) -> bool:
    """Czy odpowiedź to prośba o wypisanie.

    Słowo musi stać na POCZĄTKU własnej treści odbiorcy. Szukanie go gdziekolwiek
    kończyło się wypisywaniem zainteresowanych klientów, którzy w odpowiedzi
    cytowali naszą stopkę ze słowem STOP.
    """
    czysty = _strip_quotes(text)[:200].upper()
    if not czysty:
        return False
    return re.match(r"^\W*" + re.escape(stop_word) + r"\b", czysty) is not None


class InboxWatcher:
    """Odpytuje skrzynkę w tle i aktualizuje statusy odbiorców."""

    def __init__(
        self,
        store: Store,
        vault: PasswordVault,
        on_result: Callable[[InboxResult], None] | None = None,
    ) -> None:
        self.store = store
        self.vault = vault
        self.on_result = on_result
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    # ---------------------------------------------------------------- odczyt

    def check_once(self) -> InboxResult:
        config = ImapConfig.from_store(self.store, self.vault)
        problems = config.validate()
        if problems:
            return InboxResult(error=" ".join(problems))

        result = InboxResult()
        try:
            polaczenie = imaplib.IMAP4_SSL(config.host, config.port, timeout=config.timeout)
        except Exception as exc:  # noqa: BLE001
            return InboxResult(error="Nie udało się połączyć z serwerem IMAP: " + str(exc))

        try:
            polaczenie.login(config.user, config.password)
            polaczenie.select(config.folder, readonly=True)

            od_kiedy = (datetime.now() - timedelta(days=config.lookback_days)).strftime(
                "%d-%b-%Y"
            )
            status, dane = polaczenie.uid("SEARCH", None, "SINCE", od_kiedy)
            if status != "OK":
                return InboxResult(error="Serwer odrzucił wyszukiwanie wiadomości.")

            uids = (dane[0] or b"").split()
            ostatni = self.store.get_setting("imap_last_uid", "")
            if ostatni.isdigit():
                uids = [u for u in uids if int(u) > int(ostatni)]
            uids = uids[-300:]  # rozsądny sufit na jedno przejście

            najwyzszy = int(ostatni) if ostatni.isdigit() else 0
            for uid in uids:
                status, fetched = polaczenie.uid("FETCH", uid, "(RFC822)")
                if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                    continue
                wiadomosc = email.message_from_bytes(fetched[0][1])
                result.checked += 1
                self._process(wiadomosc, config, result)
                najwyzszy = max(najwyzszy, int(uid))

            self.store.update_settings(
                {"imap_last_uid": str(najwyzszy), "imap_last_check": _teraz()}
            )
        except imaplib.IMAP4.error as exc:
            return InboxResult(
                error="Serwer IMAP odrzucił logowanie lub polecenie: "
                + str(exc)
                + " (Gmail wymaga włączonego IMAP i hasła aplikacji)."
            )
        except Exception as exc:  # noqa: BLE001
            return InboxResult(error="Błąd odczytu skrzynki: " + str(exc))
        finally:
            try:
                polaczenie.logout()
            except Exception:  # noqa: BLE001
                pass
        return result

    def _process(self, wiadomosc: Message, config: ImapConfig, result: InboxResult) -> None:
        nadawca = normalize_email(parseaddr(_decode(wiadomosc.get("From", "")))[1])
        temat = _decode(wiadomosc.get("Subject", ""))
        tresc = _plain_text(wiadomosc)

        # 1. Raport niedostarczenia
        if _looks_like_bounce(nadawca, temat, wiadomosc):
            for kandydat in _bounce_candidates(wiadomosc, tresc):
                adres = normalize_email(kandydat)
                if not self.store.find_by_email(adres):
                    continue  # w raporcie jest też nasz własny adres - pomijamy
                if self.store.set_status_by_email(adres, STATUS_BOUNCED):
                    result.bounces += 1
                    self.store.log("warn", "Wiadomość odbiła się - adres nie działa.", adres)
                break
            return

        # 2. Dopasowanie po Message-ID naszej wysyłki, a jeśli nie - po nadawcy
        odbiorca = None
        identyfikatory = _referenced_ids(wiadomosc)
        if identyfikatory:
            for kandydat in self.store.list_recipients():
                if kandydat.last_message_id and kandydat.last_message_id in identyfikatory:
                    odbiorca = kandydat
                    break
        if odbiorca is None and nadawca:
            odbiorca = self.store.find_by_email(nadawca)
        if odbiorca is None:
            return

        # 3. Prośba o wypisanie ma pierwszeństwo przed zwykłą odpowiedzią
        if _is_stop_request(tresc, config.stop_word):
            if self.store.set_status_by_email(odbiorca.email, STATUS_UNSUBSCRIBED):
                result.unsubscribes += 1
                self.store.log(
                    "info", "Odpisał " + config.stop_word + " - wypisany z listy.", odbiorca.email
                )
            return

        if self.store.set_status_by_email(odbiorca.email, STATUS_REPLIED, stamp_reply=True):
            result.replies += 1
            self.store.log("ok", "Odpowiedział - wypada z dalszych kroków.", odbiorca.email)

    # ------------------------------------------------------------------ wątek

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="inbox", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3)
        self._thread = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def check_now(self) -> None:
        """Budzi wątek, żeby sprawdził skrzynkę bez czekania na kolejny cykl."""
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self.store.get_bool("imap_enabled"):
                wynik = self.check_once()
                if wynik.error:
                    self.store.log("warn", "Nasłuch skrzynki: " + wynik.error)
                elif wynik.changed:
                    self.store.log("info", "Nasłuch skrzynki: " + wynik.describe())
                if self.on_result:
                    self.on_result(wynik)

            minuty = max(1, self.store.get_int("imap_interval_minutes", 10))
            self._wake.wait(timeout=minuty * 60)
            self._wake.clear()


def _teraz() -> str:
    from .store import now_iso

    return now_iso()
