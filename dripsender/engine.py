"""Silnik kampanii: wątek w tle prowadzący odbiorców przez sekwencję wiadomości."""

from __future__ import annotations

import queue
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .mailer import Mailer, MailerError, SmtpConfig, append_unsubscribe, render
from .schedule import SendWindow, human_moment
from .security import PasswordVault
from .store import Recipient, Store, Template, now_iso

STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_PAUSED = "paused"
STATE_FINISHED = "finished"
STATE_STOPPED = "stopped"

STATE_LABELS = {
    STATE_IDLE: "Gotowa",
    STATE_RUNNING: "Wysyłka w toku",
    STATE_PAUSED: "Wstrzymana",
    STATE_FINISHED: "Zakończona",
    STATE_STOPPED: "Zatrzymana",
}

RETRY_DELAY_SECONDS = 15
TICK_SECONDS = 0.25


def build_values(store: Store, recipient: Recipient) -> dict[str, str]:
    """Zestaw wartości do podstawienia w szablonie dla danego odbiorcy."""
    values: dict[str, str] = {"email": recipient.email}
    for field_def in store.list_fields():
        raw = (recipient.data.get(field_def.key) or "").strip()
        values[field_def.key] = raw or field_def.fallback
    return values


def load_smtp_config(store: Store, vault: PasswordVault) -> SmtpConfig:
    user = store.get_setting("smtp_user")
    return SmtpConfig(
        host=store.get_setting("smtp_host", "smtp.gmail.com").strip(),
        port=store.get_int("smtp_port", 465),
        security=store.get_setting("smtp_security", "ssl"),
        user=user.strip(),
        password=vault.get(user),
        from_name=store.get_setting("from_name"),
        from_email=store.get_setting("from_email"),
        reply_to=store.get_setting("reply_to"),
    )


@dataclass
class SequenceSnapshot:
    """Sekwencja zamrożona na czas kampanii - edycja w trakcie nie zmienia jej biegu."""

    steps: list[Template] = field(default_factory=list)
    unsubscribe: bool = False
    unsubscribe_text: str = ""

    @classmethod
    def from_store(cls, store: Store) -> "SequenceSnapshot":
        return cls(
            steps=store.sequence(),
            unsubscribe=store.get_bool("unsubscribe_enabled"),
            unsubscribe_text=store.get_setting("unsubscribe_text"),
        )

    def step(self, stage: int) -> Template | None:
        return self.steps[stage] if 0 <= stage < len(self.steps) else None

    def next_due_after(self, stage: int, moment: datetime | None = None) -> str | None:
        """Termin kolejnego kroku po wysłaniu kroku o indeksie ``stage``."""
        nastepny = self.step(stage + 1)
        if nastepny is None:
            return None
        moment = moment or datetime.now()
        termin = moment + timedelta(days=max(0, nastepny.delay_days))
        return termin.isoformat(sep=" ", timespec="seconds")


def compose(
    step: Template,
    store: Store,
    recipient: Recipient,
    sender: str = "",
    snapshot: SequenceSnapshot | None = None,
) -> tuple[str, str, str]:
    """Składa gotową wiadomość: temat, treść i adres do wypisania.

    Jedna droga dla kampanii, podglądu i maila testowego - dzięki temu podgląd
    pokazuje dokładnie to, co dostanie odbiorca.
    """
    values = build_values(store, recipient)
    subject = render(step.subject, values)
    body = render(step.body, values)
    unsubscribe_to = ""

    wlaczona = snapshot.unsubscribe if snapshot else store.get_bool("unsubscribe_enabled")
    tekst = snapshot.unsubscribe_text if snapshot else store.get_setting("unsubscribe_text")
    if wlaczona:
        body = append_unsubscribe(body, render(tekst, values), step.is_html)
        unsubscribe_to = sender
    return subject, body, unsubscribe_to


def sample_recipient(store: Store, email: str = "przyklad@example.com") -> Recipient:
    """Sztuczny odbiorca do podglądu, gdy lista jest jeszcze pusta."""
    data = {
        field_def.key: field_def.fallback or ("<" + field_def.label + ">")
        for field_def in store.list_fields()
    }
    return Recipient(id=0, email=email, data=data)


@dataclass
class CampaignSummary:
    sent: int = 0
    errors: int = 0
    remaining: int = 0
    started_at: str = ""
    finished_at: str = ""
    reason: str = ""


class CampaignEngine:
    """Steruje wysyłką: start, pauza, stop, wymuszenie kolejnego maila."""

    def __init__(self, store: Store, vault: PasswordVault, events: queue.Queue) -> None:
        self.store = store
        self.vault = vault
        self.events = events
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._skip_wait = threading.Event()
        self._state = STATE_IDLE
        self._lock = threading.RLock()
        self._session_sent = 0
        self._session_errors = 0
        self._stop_reason = "Zatrzymana przez użytkownika."

    # ------------------------------------------------------------------ status

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def is_active(self) -> bool:
        return self.state in (STATE_RUNNING, STATE_PAUSED)

    @property
    def target_tag(self) -> str:
        return self.store.get_setting("target_tag", "").strip()

    def _set_state(self, state: str) -> None:
        with self._lock:
            self._state = state
        self.store.set_setting("campaign_state", state)
        self._emit("state", state=state, label=STATE_LABELS.get(state, state))

    def _emit(self, event_type: str, **payload: Any) -> None:
        payload["type"] = event_type
        self.events.put(payload)

    def _log(self, level: str, message: str, email: str | None = None) -> None:
        self.store.log(level, message, email)
        self._emit("log", level=level, message=message, email=email)

    # --------------------------------------------------------------- sterowanie

    def preflight(self) -> list[str]:
        """Zwraca listę problemów, które blokują start kampanii."""
        problems = load_smtp_config(self.store, self.vault).validate()
        kroki = self.store.sequence()
        if not kroki:
            problems.append("Żaden szablon nie jest włączony do sekwencji.")
        for step in kroki:
            if not step.subject.strip() or not step.body.strip():
                problems.append("Szablon '" + step.name + "' ma pusty temat albo treść.")
        tag = self.target_tag
        if not self.store.next_pending(tag):
            if tag:
                problems.append("W grupie '" + tag + "' nikt nie czeka na wysyłkę.")
            else:
                problems.append("Na liście nie ma odbiorców oczekujących na wysyłkę.")
        window = SendWindow.from_store(self.store)
        if window.enabled and not window.days:
            problems.append("Nie zaznaczono żadnego dnia wysyłki w Ustawieniach.")
        return problems

    def start(self) -> None:
        if self.is_active:
            return
        problems = self.preflight()
        if problems:
            raise ValueError("\n".join("- " + p for p in problems))
        self._stop.clear()
        self._pause.clear()
        self._skip_wait.clear()
        self._session_sent = 0
        self._session_errors = 0
        self.store.update_settings(
            {"campaign_started_at": now_iso(), "campaign_finished_at": ""}
        )
        self._set_state(STATE_RUNNING)
        kroki = len(self.store.sequence())
        self._log(
            "info",
            "Kampania wystartowała. Kroków w sekwencji: "
            + str(kroki)
            + (", grupa: " + self.target_tag if self.target_tag else ""),
        )
        self._thread = threading.Thread(target=self._run, name="campaign", daemon=True)
        self._thread.start()

    def pause(self) -> None:
        if self.state != STATE_RUNNING:
            return
        self._pause.set()
        self._set_state(STATE_PAUSED)
        self._log("info", "Kampania wstrzymana.")

    def resume(self) -> None:
        if self.state != STATE_PAUSED:
            return
        self._pause.clear()
        self._set_state(STATE_RUNNING)
        self._log("info", "Kampania wznowiona.")

    def stop(self, reason: str = "Zatrzymana przez użytkownika.") -> None:
        if not self.is_active:
            return
        self._stop_reason = reason
        self._stop.set()
        self._pause.clear()
        self._skip_wait.set()

    def send_next_now(self) -> None:
        """Skraca oczekiwanie i wysyła kolejny mail natychmiast."""
        if self.state == STATE_PAUSED:
            self.resume()
        self._skip_wait.set()

    def shutdown(self) -> None:
        self._stop.set()
        self._pause.clear()
        self._skip_wait.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3)

    # ------------------------------------------------------------------- wątek

    def _run(self) -> None:
        reason = "Wysłano wszystkie kroki sekwencji."
        try:
            config = load_smtp_config(self.store, self.vault)
            mailer = Mailer(config)
            snapshot = SequenceSnapshot.from_store(self.store)
            max_retries = max(0, self.store.get_int("max_retries", 2))
            tag = self.target_tag

            while not self._stop.is_set():
                recipient = self.store.next_due(tag)

                if recipient is None:
                    # Nikt nie jest gotowy teraz - może ktoś czeka na follow-up.
                    termin = self.store.earliest_due(tag)
                    if termin is None:
                        break
                    if not self._wait_for_followup(termin):
                        reason = self._stop_reason
                        break
                    continue

                self._wait_while_paused()
                if self._stop.is_set():
                    reason = self._stop_reason
                    break

                if not self._wait_for_slot():
                    reason = self._stop_reason
                    break

                step = snapshot.step(recipient.stage)
                if step is None:
                    # Sekwencję skrócono w międzyczasie - domykamy odbiorcę.
                    self.store.mark_step_sent(
                        recipient.id, recipient.stage, recipient.attempts
                    )
                    continue

                fatal = self._send_one(mailer, recipient, step, snapshot, max_retries)
                if fatal:
                    reason = fatal
                    break

                if self.store.next_due(tag) is None and self.store.earliest_due(tag) is None:
                    break
                if not self._wait_interval():
                    reason = self._stop_reason
                    break
            else:
                reason = self._stop_reason
        except Exception as exc:  # noqa: BLE001 - wątek nie może zginąć po cichu
            reason = "Błąd krytyczny: " + str(exc)
            self._log("error", reason)

        self._finish(reason)

    def _send_one(
        self,
        mailer: Mailer,
        recipient: Recipient,
        step: Template,
        snapshot: SequenceSnapshot,
        max_retries: int,
    ) -> str | None:
        """Wysyła jeden krok sekwencji. Zwraca powód przerwania kampanii lub None."""
        subject, body, unsubscribe_to = compose(
            step, self.store, recipient, mailer.config.sender, snapshot
        )
        attempts = recipient.attempts
        opis_kroku = "krok " + str(recipient.stage + 1) + "/" + str(len(snapshot.steps))

        for attempt in range(max_retries + 1):
            if self._stop.is_set():
                return None
            attempts += 1
            self._emit(
                "sending", email=recipient.email, attempt=attempt + 1, step=opis_kroku
            )
            try:
                message_id = mailer.send(
                    recipient.email,
                    subject,
                    body,
                    step.is_html,
                    step.attachments,
                    unsubscribe_to,
                )
            except MailerError as exc:
                message = str(exc)
                if exc.fatal:
                    self.store.mark_error(recipient.id, attempts, message)
                    self._session_errors += 1
                    self._log("error", message, recipient.email)
                    self._emit("error", email=recipient.email, message=message)
                    return "Kampania przerwana: " + message
                if attempt < max_retries:
                    self._log(
                        "warn",
                        "Próba " + str(attempt + 1) + " nieudana: " + message + " Ponawiam.",
                        recipient.email,
                    )
                    if not self._sleep_interruptible(RETRY_DELAY_SECONDS):
                        return None
                    continue
                self.store.mark_error(recipient.id, attempts, message)
                self._session_errors += 1
                self._log("error", "Nie udało się wysłać: " + message, recipient.email)
                self._emit("error", email=recipient.email, message=message)
                return None
            else:
                nastepny = snapshot.next_due_after(recipient.stage)
                self.store.mark_step_sent(
                    recipient.id, recipient.stage + 1, attempts, message_id or "", nastepny
                )
                dzis = self.store.bump_sent_today()
                self._session_sent += 1
                komunikat = "Wysłano (" + opis_kroku + ": " + step.name + ")."
                if nastepny:
                    komunikat += " Kolejny krok " + nastepny[:16] + "."
                self._log("ok", komunikat, recipient.email)
                self._emit("sent", email=recipient.email, id=recipient.id)
                self._emit("daily", sent_today=dzis)
                return None
        return None

    # --------------------------------------------- okno czasowe i limit dobowy

    def _blocked(self) -> tuple[datetime | None, str] | None:
        """Czy coś blokuje wysyłkę. Zwraca (moment odblokowania, powód) albo None."""
        now = datetime.now()
        window = SendWindow.from_store(self.store)
        limit = self.store.get_int("daily_limit", 0)

        if limit > 0 and self.store.sent_today() >= limit:
            jutro = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            return window.next_open(jutro) or jutro, (
                "Dzienny limit " + str(limit) + " wiadomości został wyczerpany."
            )

        if not window.allows(now):
            moment = window.next_open(now)
            if moment is None:
                return None, (
                    "W ustawieniach nie zaznaczono żadnego dnia wysyłki - "
                    "kampania nie ma kiedy ruszyć."
                )
            return moment, "Poza godzinami wysyłki (" + window.describe() + ")."

        return None

    def _wait_for_slot(self) -> bool:
        """Czeka, aż wolno będzie wysłać. False = kampania zatrzymana."""
        ostatni_powod = ""
        while not self._stop.is_set():
            self._wait_while_paused()
            if self._stop.is_set():
                return False

            blokada = self._blocked()
            if blokada is None:
                if ostatni_powod:
                    self._log("info", "Wznawiam wysyłkę.")
                return True

            moment, powod = blokada
            if moment is None:  # blokada, której nic nie zdejmie
                self._stop_reason = powod
                self._log("error", powod)
                self._stop.set()
                return False

            if powod != ostatni_powod:
                self._log("info", powod + " Wznowię " + human_moment(moment) + ".")
                ostatni_powod = powod
            self._emit(
                "waiting",
                reason=powod,
                resume_at=human_moment(moment),
                next_email=self._next_email(),
            )
            time.sleep(1.0)
        return False

    def _wait_for_followup(self, termin_iso: str) -> bool:
        """Nikt nie jest gotowy teraz - czekamy na najbliższy termin follow-upu."""
        try:
            termin = datetime.fromisoformat(termin_iso)
        except ValueError:
            return True
        powod = "Wszyscy obsłużeni w tej rundzie. Czekam na termin follow-upu."
        self._log("info", powod + " Wznowię " + human_moment(termin) + ".")
        while not self._stop.is_set():
            self._wait_while_paused()
            if self._stop.is_set():
                return False
            if self._skip_wait.is_set():
                self._skip_wait.clear()
                self._log("info", "Pominięto oczekiwanie na follow-up.")
                return True
            if datetime.now() >= termin:
                return True
            self._emit("waiting", reason=powod, resume_at=human_moment(termin), next_email="")
            time.sleep(1.0)
        return False

    # ----------------------------------------------------------------- czekanie

    def _interval_seconds(self) -> float:
        minutes = max(0.1, float(self.store.get_int("interval_minutes", 5)))
        base = minutes * 60.0
        jitter = max(0, min(50, self.store.get_int("jitter_percent", 0)))
        if jitter:
            spread = base * jitter / 100.0
            base = max(10.0, base + random.uniform(-spread, spread))
        return base

    def _wait_while_paused(self) -> None:
        while self._pause.is_set() and not self._stop.is_set():
            self._emit("tick", remaining=0.0, paused=True, next_email=self._next_email())
            time.sleep(TICK_SECONDS)

    def _sleep_interruptible(self, seconds: float) -> bool:
        """Śpi podanym czasem. Zwraca False, gdy kampania została zatrzymana."""
        deadline = time.monotonic() + seconds
        while not self._stop.is_set():
            if time.monotonic() >= deadline:
                return True
            time.sleep(min(TICK_SECONDS, max(0.05, deadline - time.monotonic())))
        return False

    def _wait_interval(self) -> bool:
        """Odlicza przerwę do kolejnego maila. False = zatrzymano kampanię."""
        self._skip_wait.clear()
        remaining = self._interval_seconds()
        next_email = self._next_email()
        deadline = time.monotonic() + remaining

        while not self._stop.is_set():
            if self._skip_wait.is_set():
                self._skip_wait.clear()
                self._log("info", "Pominięto oczekiwanie - wysyłam następny mail.")
                return True
            if self._pause.is_set():
                remaining = max(0.0, deadline - time.monotonic())
                deadline = time.monotonic() + remaining
                self._emit("tick", remaining=remaining, paused=True, next_email=next_email)
                time.sleep(TICK_SECONDS)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            self._emit("tick", remaining=remaining, paused=False, next_email=next_email)
            time.sleep(TICK_SECONDS)
        return False

    def _next_email(self) -> str:
        upcoming = self.store.next_due(self.target_tag)
        return upcoming.email if upcoming else ""

    # ------------------------------------------------------------- podsumowanie

    def _finish(self, reason: str) -> None:
        counts = self.store.counts(self.target_tag)
        finished_at = now_iso()
        self.store.set_setting("campaign_finished_at", finished_at)
        summary = CampaignSummary(
            sent=self._session_sent,
            errors=self._session_errors,
            remaining=counts.get("pending", 0),
            started_at=self.store.get_setting("campaign_started_at"),
            finished_at=finished_at,
            reason=reason,
        )
        state = (
            STATE_FINISHED
            if summary.remaining == 0 and not self._stop.is_set()
            else STATE_STOPPED
        )
        self._set_state(state)
        self._log(
            "info",
            "Koniec kampanii. Wysłane: "
            + str(summary.sent)
            + ", błędy: "
            + str(summary.errors)
            + ", pozostało: "
            + str(summary.remaining)
            + ". "
            + reason,
        )
        self._emit("finished", summary=summary)
        self._thread = None
