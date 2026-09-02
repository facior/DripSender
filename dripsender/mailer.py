"""Wysyłka wiadomości przez SMTP oraz podstawianie danych w szablonie."""

from __future__ import annotations

import mimetypes
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr
from pathlib import Path
from typing import Iterable, Sequence

PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


class MailerError(Exception):
    """Błąd wysyłki opisany po ludzku, gotowy do pokazania w interfejsie."""

    def __init__(self, message: str, fatal: bool = False) -> None:
        super().__init__(message)
        self.fatal = fatal


def render(template: str, values: dict[str, str]) -> str:
    """Podstawia {klucz} wartościami. Nieznane znaczniki zostawia nietknięte."""

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in values:
            return str(values[key] if values[key] is not None else "")
        return match.group(0)

    return PLACEHOLDER_RE.sub(replace, template or "")


def placeholders_in(template: str) -> list[str]:
    seen: list[str] = []
    for match in PLACEHOLDER_RE.finditer(template or ""):
        if match.group(1) not in seen:
            seen.append(match.group(1))
    return seen


def unknown_placeholders(template: str, known: Iterable[str]) -> list[str]:
    known_set = set(known)
    return [name for name in placeholders_in(template) if name not in known_set]


def append_unsubscribe(body: str, footer: str, is_html: bool) -> str:
    """Dokleja stopkę z informacją o wypisaniu, oddzieloną kreską."""
    footer = (footer or "").strip()
    if not footer:
        return body
    if is_html:
        return body + (
            '<hr style="border:none;border-top:1px solid #ddd;margin:24px 0 8px">'
            '<p style="font-size:12px;color:#777;margin:0">' + footer + "</p>"
        )
    return body.rstrip() + "\n\n-- \n" + footer


def html_to_text(html: str) -> str:
    """Prosta wersja tekstowa maila HTML - jako alternatywa w multipart."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", html or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"(?i)</(h[1-6]|div|tr|li)\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    return re.sub(r"\n{3,}", "\n\n", text).strip()


@dataclass
class SmtpConfig:
    host: str = "smtp.gmail.com"
    port: int = 465
    security: str = "ssl"  # ssl | starttls | none
    user: str = ""
    password: str = ""
    from_name: str = ""
    from_email: str = ""
    reply_to: str = ""
    timeout: int = 30

    @property
    def sender(self) -> str:
        return (self.from_email or self.user).strip()

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.host.strip():
            problems.append("Brak serwera SMTP.")
        if not self.port:
            problems.append("Brak portu SMTP.")
        if not self.user.strip():
            problems.append("Brak loginu SMTP.")
        if not self.password:
            problems.append("Brak hasła SMTP (dla Gmaila: hasło aplikacji).")
        if not self.sender:
            problems.append("Brak adresu nadawcy.")
        elif "@" not in parseaddr(self.sender)[1]:
            problems.append("Adres nadawcy jest nieprawidłowy.")
        return problems


def friendly_smtp_error(exc: Exception) -> MailerError:
    """Tłumaczy wyjątki smtplib na komunikaty zrozumiałe dla użytkownika."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return MailerError(
            "Serwer odrzucił logowanie. W Gmailu trzeba włączyć weryfikację dwuetapową "
            "i wygenerować 16-znakowe hasło aplikacji - zwykłe hasło do konta nie zadziała.",
            fatal=True,
        )
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return MailerError("Serwer odrzucił adres odbiorcy (może nie istnieć).")
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return MailerError(
            "Serwer odrzucił adres nadawcy. Musi zgadzać się z kontem, na które się logujesz.",
            fatal=True,
        )
    if isinstance(exc, smtplib.SMTPDataError):
        code = getattr(exc, "smtp_code", 0)
        if code in (421, 450, 452, 550, 554):
            return MailerError(
                "Serwer chwilowo odmówił przyjęcia wiadomości (limit wysyłki lub filtr "
                "antyspamowy). Zwiększ odstęp między mailami i spróbuj później."
            )
        return MailerError("Serwer odrzucił treść wiadomości: " + str(exc))
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return MailerError("Serwer zerwał połączenie w trakcie wysyłki.")
    if isinstance(exc, smtplib.SMTPConnectError):
        return MailerError("Nie udało się połączyć z serwerem SMTP. Sprawdź adres i port.")
    if isinstance(exc, ssl.SSLError):
        return MailerError(
            "Błąd szyfrowania połączenia. Sprawdź, czy port pasuje do trybu "
            "(465 = SSL, 587 = STARTTLS)."
        )
    if isinstance(exc, (TimeoutError, OSError)):
        return MailerError(
            "Brak połączenia z serwerem SMTP. Sprawdź internet, zaporę lub program antywirusowy."
        )
    return MailerError("Nieoczekiwany błąd wysyłki: " + str(exc))


class Mailer:
    """Wysyła pojedyncze wiadomości. Połączenie otwiera na czas jednej wysyłki."""

    def __init__(self, config: SmtpConfig) -> None:
        self.config = config

    def _connect(self) -> smtplib.SMTP:
        cfg = self.config
        context = ssl.create_default_context()
        if cfg.security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                cfg.host, cfg.port, timeout=cfg.timeout, context=context
            )
        else:
            server = smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout)
            server.ehlo()
            if cfg.security == "starttls":
                server.starttls(context=context)
                server.ehlo()
        if cfg.user:
            server.login(cfg.user, cfg.password)
        return server

    def verify(self) -> tuple[bool, str]:
        """Sprawdza konfigurację i logowanie. Nie wysyła żadnej wiadomości."""
        problems = self.config.validate()
        if problems:
            return False, " ".join(problems)
        try:
            server = self._connect()
        except Exception as exc:  # noqa: BLE001 - tłumaczymy na komunikat
            return False, str(friendly_smtp_error(exc))
        try:
            server.noop()
        finally:
            try:
                server.quit()
            except Exception:  # noqa: BLE001
                pass
        return True, "Połączenie i logowanie działają poprawnie."

    def build_message(
        self,
        to_email: str,
        subject: str,
        body: str,
        is_html: bool = False,
        attachments: Sequence[str] = (),
        unsubscribe_to: str = "",
    ) -> EmailMessage:
        cfg = self.config
        message = EmailMessage()
        message["From"] = formataddr((cfg.from_name.strip() or None, cfg.sender))
        message["To"] = to_email
        message["Subject"] = subject
        if cfg.reply_to.strip():
            message["Reply-To"] = cfg.reply_to.strip()
        domain = cfg.sender.split("@")[-1] if "@" in cfg.sender else None
        message["Message-ID"] = make_msgid(domain=domain)
        if unsubscribe_to:
            # Nagłówek rozumiany przez Gmaila i Outlooka - pokazują przycisk "Wypisz się".
            message["List-Unsubscribe"] = "<mailto:" + unsubscribe_to + "?subject=STOP>"

        if is_html:
            message.set_content(html_to_text(body))
            message.add_alternative(body, subtype="html")
        else:
            message.set_content(body)

        for raw_path in attachments:
            path = Path(raw_path)
            if not path.is_file():
                raise MailerError("Nie znaleziono załącznika: " + str(path), fatal=True)
            guessed, _ = mimetypes.guess_type(path.name)
            maintype, _, subtype = (guessed or "application/octet-stream").partition("/")
            message.add_attachment(
                path.read_bytes(),
                maintype=maintype,
                subtype=subtype or "octet-stream",
                filename=path.name,
            )
        return message

    def send(
        self,
        to_email: str,
        subject: str,
        body: str,
        is_html: bool = False,
        attachments: Sequence[str] = (),
        unsubscribe_to: str = "",
    ) -> str:
        """Wysyła wiadomość i zwraca jej Message-ID.

        Identyfikator zapisujemy przy odbiorcy, żeby później rozpoznać odpowiedź
        po nagłówku In-Reply-To.
        """
        message = self.build_message(
            to_email, subject, body, is_html, attachments, unsubscribe_to
        )
        try:
            server = self._connect()
        except Exception as exc:  # noqa: BLE001
            raise friendly_smtp_error(exc) from exc
        try:
            server.send_message(message)
        except Exception as exc:  # noqa: BLE001
            raise friendly_smtp_error(exc) from exc
        finally:
            try:
                server.quit()
            except Exception:  # noqa: BLE001
                pass
        return str(message["Message-ID"] or "")
