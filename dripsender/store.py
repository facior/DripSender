"""Warstwa danych aplikacji: SQLite z ustawieniami, polami, odbiorcami, szablonami i logiem."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

from .paths import db_path

EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[A-Za-z]{2,}$")

STATUS_PENDING = "pending"
STATUS_SENT = "sent"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"
STATUS_UNSUBSCRIBED = "unsubscribed"
STATUS_REPLIED = "replied"
STATUS_BOUNCED = "bounced"

STATUS_LABELS = {
    STATUS_PENDING: "W kolejce",
    STATUS_SENT: "Zakończony",
    STATUS_ERROR: "Błąd",
    STATUS_SKIPPED: "Pominięty",
    STATUS_UNSUBSCRIBED: "Wypisany",
    STATUS_REPLIED: "Odpowiedział",
    STATUS_BOUNCED: "Odbity",
}

# Statusy, które trwale wyjmują odbiorcę z sekwencji.
FINAL_STATUSES = (
    STATUS_SENT,
    STATUS_ERROR,
    STATUS_SKIPPED,
    STATUS_UNSUBSCRIBED,
    STATUS_REPLIED,
    STATUS_BOUNCED,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fields (
    key      TEXT PRIMARY KEY,
    label    TEXT NOT NULL,
    fallback TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS recipients (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT NOT NULL COLLATE NOCASE,
    data            TEXT NOT NULL DEFAULT '{}',
    tags            TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'pending',
    stage           INTEGER NOT NULL DEFAULT 0,
    next_due_at     TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    sent_at         TEXT,
    replied_at      TEXT,
    last_message_id TEXT,
    position        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    UNIQUE (email)
);
CREATE TABLE IF NOT EXISTS templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    subject     TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL DEFAULT '',
    is_html     INTEGER NOT NULL DEFAULT 0,
    attachments TEXT NOT NULL DEFAULT '[]',
    delay_days  INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1,
    position    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    level   TEXT NOT NULL,
    email   TEXT,
    message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sent_counter (
    day   TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_recipients_queue
    ON recipients(status, next_due_at, position, id);
"""

DEFAULT_BODY = """Dzień dobry {imie},

piszę w sprawie możliwej współpracy z firmą {firma}.

Pozdrawiam
"""

DEFAULT_FOLLOWUP = """Dzień dobry {imie},

wracam do mojej poprzedniej wiadomości - może umknęła w natłoku poczty.
Chętnie odpowiem na pytania.

Pozdrawiam
"""

DEFAULT_UNSUBSCRIBE = (
    "Nie chcesz otrzymywać ode mnie wiadomości? Odpisz STOP, a usunę Twój adres z listy."
)

DEFAULT_SETTINGS: dict[str, str] = {
    "smtp_host": "smtp.gmail.com",
    "smtp_port": "465",
    "smtp_security": "ssl",
    "smtp_user": "",
    "from_name": "",
    "from_email": "",
    "reply_to": "",
    "interval_minutes": "5",
    "jitter_percent": "0",
    "max_retries": "2",
    "body_is_html": "0",
    "attachments": "[]",
    "unsubscribe_enabled": "0",
    "unsubscribe_text": DEFAULT_UNSUBSCRIBE,
    "hours_enabled": "0",
    "hours_from": "09:00",
    "hours_to": "17:00",
    "hours_days": "0,1,2,3,4",
    "daily_limit": "450",
    "minimize_to_tray": "1",
    "autostart": "0",
    "auto_resume": "1",
    "target_tag": "",
    "imap_enabled": "0",
    "imap_host": "imap.gmail.com",
    "imap_port": "993",
    "imap_folder": "INBOX",
    "imap_interval_minutes": "10",
    "imap_lookback_days": "14",
    "imap_stop_word": "STOP",
    "imap_last_check": "",
    "imap_last_uid": "",
    "app_lock_enabled": "0",
    "app_lock_hash": "",
    "app_lock_salt": "",
    "smtp_verified_at": "",
    "test_sent_at": "",
    "campaign_state": "idle",
    "campaign_started_at": "",
    "campaign_finished_at": "",
}

DEFAULT_FIELDS = [
    ("imie", "Imię", "Państwo"),
    ("firma", "Firma", ""),
]


@dataclass
class Field:
    """Pole personalizacji, dostępne w szablonie jako {klucz}."""

    key: str
    label: str
    fallback: str = ""
    position: int = 0


@dataclass
class Template:
    """Jeden krok sekwencji: pierwsza wiadomość albo follow-up."""

    id: int
    name: str
    subject: str = ""
    body: str = ""
    is_html: bool = False
    attachments: list[str] = field(default_factory=list)
    delay_days: int = 0
    active: bool = True
    position: int = 0


@dataclass
class Recipient:
    id: int
    email: str
    data: dict[str, str]
    tags: list[str] = field(default_factory=list)
    status: str = STATUS_PENDING
    stage: int = 0
    next_due_at: str | None = None
    attempts: int = 0
    last_error: str | None = None
    sent_at: str | None = None
    replied_at: str | None = None
    last_message_id: str | None = None
    position: int = 0

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


def now_iso() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def valid_email(value: str) -> bool:
    return bool(EMAIL_RE.match((value or "").strip()))


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


class Store:
    """Cienka warstwa nad SQLite, bezpieczna dla wątku wysyłki i wątku GUI."""

    def __init__(self, path=None) -> None:
        self.path = str(path or db_path())
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        self._migrate()
        self._seed()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ migracje

    def _migrate(self) -> None:
        """Dokłada kolumny, których brakuje w bazach z wcześniejszych wersji."""
        nowe = {
            "recipients": {
                "tags": "TEXT NOT NULL DEFAULT '[]'",
                "stage": "INTEGER NOT NULL DEFAULT 0",
                "next_due_at": "TEXT",
                "replied_at": "TEXT",
                "last_message_id": "TEXT",
            }
        }
        with self._lock:
            for tabela, kolumny in nowe.items():
                istniejace = {
                    row["name"]
                    for row in self._conn.execute("PRAGMA table_info(" + tabela + ")").fetchall()
                }
                for nazwa, definicja in kolumny.items():
                    if nazwa not in istniejace:
                        self._conn.execute(
                            "ALTER TABLE " + tabela + " ADD COLUMN " + nazwa + " " + definicja
                        )
            self._conn.commit()

    def _seed(self) -> None:
        with self._lock:
            for key, value in DEFAULT_SETTINGS.items():
                self._conn.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value)
                )
            if not self._conn.execute("SELECT COUNT(*) AS c FROM fields").fetchone()["c"]:
                for position, (key, label, fallback) in enumerate(DEFAULT_FIELDS):
                    self._conn.execute(
                        "INSERT INTO fields (key, label, fallback, position) VALUES (?, ?, ?, ?)",
                        (key, label, fallback, position),
                    )
            self._conn.commit()
        self._seed_templates()

    def _seed_templates(self) -> None:
        """Pierwszy szablon przejmuje treść z poprzedniej wersji, jeśli tam była."""
        with self._lock:
            if self._conn.execute("SELECT COUNT(*) AS c FROM templates").fetchone()["c"]:
                return
            stary_temat = self.get_setting("subject", "")
            stara_tresc = self.get_setting("body", "")
            self._conn.execute(
                "INSERT INTO templates (name, subject, body, is_html, attachments, "
                "delay_days, active, position) VALUES (?, ?, ?, ?, ?, 0, 1, 0)",
                (
                    "Wiadomość główna",
                    stary_temat or "Wiadomość dla {firma}",
                    stara_tresc or DEFAULT_BODY,
                    1 if self.get_bool("body_is_html") else 0,
                    self.get_setting("attachments", "[]"),
                ),
            )
            self._conn.execute(
                "INSERT INTO templates (name, subject, body, is_html, attachments, "
                "delay_days, active, position) VALUES (?, ?, ?, 0, '[]', 4, 0, 1)",
                ("Follow-up po 4 dniach", "Re: {firma}", DEFAULT_FOLLOWUP),
            )
            self._conn.commit()

    # --------------------------------------------------------------- ustawienia

    def get_setting(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.update_settings({key: value})

    def update_settings(self, values: dict[str, Any]) -> None:
        with self._lock:
            for key, value in values.items():
                self._conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, "" if value is None else str(value)),
                )
            self._conn.commit()

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(float(self.get_setting(key, str(default))))
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        return self.get_setting(key, "1" if default else "0") in {"1", "true", "True"}

    def get_list(self, key: str) -> list:
        try:
            value = json.loads(self.get_setting(key, "[]"))
        except json.JSONDecodeError:
            return []
        return value if isinstance(value, list) else []

    def set_list(self, key: str, value: Sequence) -> None:
        self.set_setting(key, json.dumps(list(value), ensure_ascii=False))

    # -------------------------------------------------------------------- pola

    def list_fields(self) -> list[Field]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, label, fallback, position FROM fields ORDER BY position, key"
            ).fetchall()
        return [Field(r["key"], r["label"], r["fallback"], r["position"]) for r in rows]

    def field_keys(self) -> list[str]:
        return [f.key for f in self.list_fields()]

    def add_field(self, key: str, label: str, fallback: str = "") -> None:
        key = re.sub(r"[^a-z0-9_]", "", (key or "").strip().lower())
        if not key:
            raise ValueError("Klucz pola może zawierać tylko małe litery, cyfry i podkreślnik.")
        if key == "email":
            raise ValueError("Pole 'email' jest wbudowane i nie trzeba go dodawać.")
        with self._lock:
            if self._conn.execute("SELECT 1 FROM fields WHERE key = ?", (key,)).fetchone():
                raise ValueError("Pole o kluczu '" + key + "' już istnieje.")
            position = self._conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM fields"
            ).fetchone()["p"]
            self._conn.execute(
                "INSERT INTO fields (key, label, fallback, position) VALUES (?, ?, ?, ?)",
                (key, label.strip() or key, fallback, position),
            )
            self._conn.commit()

    def update_field(self, key: str, label: str, fallback: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE fields SET label = ?, fallback = ? WHERE key = ?",
                (label.strip() or key, fallback, key),
            )
            self._conn.commit()

    def remove_field(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM fields WHERE key = ?", (key,))
            for row in self._conn.execute("SELECT id, data FROM recipients").fetchall():
                try:
                    data = json.loads(row["data"])
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict) and key in data:
                    data.pop(key, None)
                    self._conn.execute(
                        "UPDATE recipients SET data = ? WHERE id = ?",
                        (json.dumps(data, ensure_ascii=False), row["id"]),
                    )
            self._conn.commit()

    # --------------------------------------------------------------- szablony

    @staticmethod
    def _to_template(row: sqlite3.Row) -> Template:
        try:
            attachments = json.loads(row["attachments"])
        except json.JSONDecodeError:
            attachments = []
        return Template(
            id=row["id"],
            name=row["name"],
            subject=row["subject"],
            body=row["body"],
            is_html=bool(row["is_html"]),
            attachments=[str(p) for p in attachments] if isinstance(attachments, list) else [],
            delay_days=row["delay_days"],
            active=bool(row["active"]),
            position=row["position"],
        )

    def list_templates(self, only_active: bool = False) -> list[Template]:
        query = "SELECT * FROM templates"
        if only_active:
            query += " WHERE active = 1"
        query += " ORDER BY position, id"
        with self._lock:
            rows = self._conn.execute(query).fetchall()
        return [self._to_template(row) for row in rows]

    def get_template(self, template_id: int) -> Template | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM templates WHERE id = ?", (template_id,)
            ).fetchone()
        return self._to_template(row) if row else None

    def add_template(self, name: str, delay_days: int = 3) -> int:
        with self._lock:
            position = self._conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM templates"
            ).fetchone()["p"]
            cursor = self._conn.execute(
                "INSERT INTO templates (name, subject, body, delay_days, active, position) "
                "VALUES (?, ?, ?, ?, 0, ?)",
                (name.strip() or "Nowy szablon", "Re: {firma}", DEFAULT_FOLLOWUP,
                 max(0, delay_days), position),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def update_template(self, template_id: int, **pola: Any) -> None:
        dozwolone = {
            "name", "subject", "body", "is_html", "attachments", "delay_days", "active"
        }
        zmiany = {k: v for k, v in pola.items() if k in dozwolone}
        if not zmiany:
            return
        if "attachments" in zmiany and not isinstance(zmiany["attachments"], str):
            zmiany["attachments"] = json.dumps(
                [str(p) for p in zmiany["attachments"]], ensure_ascii=False
            )
        for klucz in ("is_html", "active"):
            if klucz in zmiany:
                zmiany[klucz] = 1 if zmiany[klucz] else 0
        sets = ", ".join(k + " = ?" for k in zmiany)
        with self._lock:
            self._conn.execute(
                "UPDATE templates SET " + sets + " WHERE id = ?",
                [*zmiany.values(), template_id],
            )
            self._conn.commit()

    def delete_template(self, template_id: int) -> bool:
        with self._lock:
            ile = self._conn.execute("SELECT COUNT(*) AS c FROM templates").fetchone()["c"]
            if ile <= 1:
                return False
            self._conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
            self._conn.commit()
            return True

    def move_template(self, template_id: int, direction: int) -> bool:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM templates ORDER BY position, id"
            ).fetchall()
            order = [row["id"] for row in rows]
            if template_id not in order:
                return False
            index = order.index(template_id)
            target = index + direction
            if target < 0 or target >= len(order):
                return False
            order[index], order[target] = order[target], order[index]
            for position, row_id in enumerate(order):
                self._conn.execute(
                    "UPDATE templates SET position = ? WHERE id = ?", (position, row_id)
                )
            self._conn.commit()
            return True

    def sequence(self) -> list[Template]:
        """Aktywne kroki sekwencji w kolejności wysyłki."""
        return self.list_templates(only_active=True)

    # ---------------------------------------------------------------- odbiorcy

    @staticmethod
    def _to_recipient(row: sqlite3.Row) -> Recipient:
        try:
            data = json.loads(row["data"])
        except json.JSONDecodeError:
            data = {}
        try:
            tags = json.loads(row["tags"] or "[]")
        except (json.JSONDecodeError, TypeError):
            tags = []
        return Recipient(
            id=row["id"],
            email=row["email"],
            data=data if isinstance(data, dict) else {},
            tags=[str(t) for t in tags] if isinstance(tags, list) else [],
            status=row["status"],
            stage=row["stage"] or 0,
            next_due_at=row["next_due_at"],
            attempts=row["attempts"],
            last_error=row["last_error"],
            sent_at=row["sent_at"],
            replied_at=row["replied_at"],
            last_message_id=row["last_message_id"],
            position=row["position"],
        )

    def list_recipients(
        self, status: str | None = None, search: str = "", tag: str = ""
    ) -> list[Recipient]:
        query = "SELECT * FROM recipients"
        params: list[Any] = []
        clauses: list[str] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if search.strip():
            clauses.append("(email LIKE ? OR data LIKE ?)")
            like = "%" + search.strip() + "%"
            params.extend([like, like])
        if tag:
            clauses.append("tags LIKE ?")
            params.append('%"' + tag + '"%')
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY position, id"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._to_recipient(row) for row in rows]

    def get_recipient(self, recipient_id: int) -> Recipient | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM recipients WHERE id = ?", (recipient_id,)
            ).fetchone()
        return self._to_recipient(row) if row else None

    def find_by_email(self, email: str) -> Recipient | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM recipients WHERE email = ?", (normalize_email(email),)
            ).fetchone()
        return self._to_recipient(row) if row else None

    def add_recipient(
        self, email: str, data: dict[str, str] | None = None, tags: Sequence[str] = ()
    ) -> int:
        email = (email or "").strip()
        if not valid_email(email):
            raise ValueError("Nieprawidłowy adres e-mail: " + (email or "(pusty)"))
        payload = json.dumps({k: (v or "") for k, v in (data or {}).items()}, ensure_ascii=False)
        with self._lock:
            if self._conn.execute(
                "SELECT 1 FROM recipients WHERE email = ?", (email,)
            ).fetchone():
                raise ValueError("Adres " + email + " jest już na liście.")
            position = self._conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM recipients"
            ).fetchone()["p"]
            cursor = self._conn.execute(
                "INSERT INTO recipients (email, data, tags, status, position, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    email,
                    payload,
                    json.dumps(list(tags), ensure_ascii=False),
                    STATUS_PENDING,
                    position,
                    now_iso(),
                ),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def add_many(
        self, entries: Iterable[tuple[str, dict[str, str]]], tags: Sequence[str] = ()
    ) -> dict[str, list[str]]:
        """Dodaje wiele adresów naraz. Zwraca listy: added, duplicate, invalid."""
        result: dict[str, list[str]] = {"added": [], "duplicate": [], "invalid": []}
        seen: set[str] = set()
        tag_json = json.dumps(list(tags), ensure_ascii=False)
        with self._lock:
            position = self._conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM recipients"
            ).fetchone()["p"]
            for email, data in entries:
                email = (email or "").strip()
                if not valid_email(email):
                    if email:
                        result["invalid"].append(email)
                    continue
                lowered = email.lower()
                if lowered in seen or self._conn.execute(
                    "SELECT 1 FROM recipients WHERE email = ?", (email,)
                ).fetchone():
                    result["duplicate"].append(email)
                    continue
                self._conn.execute(
                    "INSERT INTO recipients (email, data, tags, status, position, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        email,
                        json.dumps({k: (v or "") for k, v in data.items()}, ensure_ascii=False),
                        tag_json,
                        STATUS_PENDING,
                        position,
                        now_iso(),
                    ),
                )
                seen.add(lowered)
                result["added"].append(email)
                position += 1
            self._conn.commit()
        return result

    def update_recipient(self, recipient_id: int, email: str, data: dict[str, str]) -> None:
        email = (email or "").strip()
        if not valid_email(email):
            raise ValueError("Nieprawidłowy adres e-mail: " + (email or "(pusty)"))
        with self._lock:
            clash = self._conn.execute(
                "SELECT 1 FROM recipients WHERE email = ? AND id <> ?", (email, recipient_id)
            ).fetchone()
            if clash:
                raise ValueError("Adres " + email + " jest już przypisany do innego odbiorcy.")
            self._conn.execute(
                "UPDATE recipients SET email = ?, data = ? WHERE id = ?",
                (email, json.dumps(data, ensure_ascii=False), recipient_id),
            )
            self._conn.commit()

    def delete_recipients(self, ids: Sequence[int]) -> int:
        if not ids:
            return 0
        marks = ",".join("?" for _ in ids)
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM recipients WHERE id IN (" + marks + ")", list(ids)
            )
            self._conn.commit()
            return cursor.rowcount

    def clear_recipients(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM recipients")
            self._conn.commit()

    # ------------------------------------------------------------------- tagi

    def all_tags(self) -> list[str]:
        tagi: set[str] = set()
        for recipient in self.list_recipients():
            tagi.update(recipient.tags)
        return sorted(tagi)

    def set_tags(self, ids: Sequence[int], tags: Sequence[str]) -> int:
        if not ids:
            return 0
        payload = json.dumps(sorted({t.strip() for t in tags if t.strip()}), ensure_ascii=False)
        marks = ",".join("?" for _ in ids)
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recipients SET tags = ? WHERE id IN (" + marks + ")", [payload, *ids]
            )
            self._conn.commit()
            return cursor.rowcount

    def add_tag(self, ids: Sequence[int], tag: str) -> int:
        tag = tag.strip()
        if not tag or not ids:
            return 0
        zmienione = 0
        with self._lock:
            for recipient_id in ids:
                recipient = self.get_recipient(recipient_id)
                if recipient is None or tag in recipient.tags:
                    continue
                nowe = sorted({*recipient.tags, tag})
                self._conn.execute(
                    "UPDATE recipients SET tags = ? WHERE id = ?",
                    (json.dumps(nowe, ensure_ascii=False), recipient_id),
                )
                zmienione += 1
            self._conn.commit()
        return zmienione

    def remove_tag(self, ids: Sequence[int], tag: str) -> int:
        zmienione = 0
        with self._lock:
            for recipient_id in ids:
                recipient = self.get_recipient(recipient_id)
                if recipient is None or tag not in recipient.tags:
                    continue
                nowe = [t for t in recipient.tags if t != tag]
                self._conn.execute(
                    "UPDATE recipients SET tags = ? WHERE id = ?",
                    (json.dumps(nowe, ensure_ascii=False), recipient_id),
                )
                zmienione += 1
            self._conn.commit()
        return zmienione

    # ------------------------------------------------------------ stan wysyłki

    def reset_status(self, ids: Sequence[int] | None = None) -> int:
        """Przywraca do kolejki od pierwszego kroku. Wypisanych nigdy nie rusza."""
        columns = (
            "status = ?, stage = 0, next_due_at = NULL, attempts = 0, "
            "last_error = NULL, sent_at = NULL, replied_at = NULL"
        )
        guard = " status <> '" + STATUS_UNSUBSCRIBED + "'"
        with self._lock:
            if ids:
                marks = ",".join("?" for _ in ids)
                cursor = self._conn.execute(
                    "UPDATE recipients SET " + columns + " WHERE id IN (" + marks + ") AND" + guard,
                    [STATUS_PENDING, *ids],
                )
            else:
                cursor = self._conn.execute(
                    "UPDATE recipients SET " + columns + " WHERE" + guard, (STATUS_PENDING,)
                )
            self._conn.commit()
            return cursor.rowcount

    def set_status(self, ids: Sequence[int], status: str) -> int:
        if not ids:
            return 0
        marks = ",".join("?" for _ in ids)
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE recipients SET status = ? WHERE id IN (" + marks + ")", [status, *ids]
            )
            self._conn.commit()
            return cursor.rowcount

    def set_status_by_email(self, email: str, status: str, stamp_reply: bool = False) -> bool:
        """Używane przez nasłuch skrzynki: odpowiedź, odbicie, prośba o wypisanie."""
        recipient = self.find_by_email(email)
        if recipient is None or recipient.status == status:
            return False
        # Wypisanie jest decyzją odbiorcy - nasłuch skrzynki jej nie cofa.
        if recipient.status == STATUS_UNSUBSCRIBED and status != STATUS_UNSUBSCRIBED:
            return False
        with self._lock:
            if stamp_reply:
                self._conn.execute(
                    "UPDATE recipients SET status = ?, replied_at = ? WHERE id = ?",
                    (status, now_iso(), recipient.id),
                )
            else:
                self._conn.execute(
                    "UPDATE recipients SET status = ? WHERE id = ?", (status, recipient.id)
                )
            self._conn.commit()
        return True

    def move_recipient(self, recipient_id: int, direction: int) -> bool:
        """Przesuwa odbiorcę w kolejce wysyłki. direction: -1 w górę, 1 w dół."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM recipients ORDER BY position, id"
            ).fetchall()
            order = [row["id"] for row in rows]
            if recipient_id not in order:
                return False
            index = order.index(recipient_id)
            target = index + direction
            if target < 0 or target >= len(order):
                return False
            order[index], order[target] = order[target], order[index]
            for position, row_id in enumerate(order):
                self._conn.execute(
                    "UPDATE recipients SET position = ? WHERE id = ?", (position, row_id)
                )
            self._conn.commit()
            return True

    # ---------------------------------------------------------------- kolejka

    def next_due(self, tag: str = "", moment: datetime | None = None) -> Recipient | None:
        """Kolejny odbiorca gotowy do wysyłki - z uwzględnieniem opóźnień follow-upów."""
        teraz = (moment or datetime.now()).isoformat(sep=" ", timespec="seconds")
        query = (
            "SELECT * FROM recipients WHERE status = ? "
            "AND (next_due_at IS NULL OR next_due_at <= ?)"
        )
        params: list[Any] = [STATUS_PENDING, teraz]
        if tag:
            query += " AND tags LIKE ?"
            params.append('%"' + tag + '"%')
        query += " ORDER BY (next_due_at IS NULL) DESC, next_due_at, position, id LIMIT 1"
        with self._lock:
            row = self._conn.execute(query, params).fetchone()
        return self._to_recipient(row) if row else None

    def next_pending(self, tag: str = "") -> Recipient | None:
        """Ktokolwiek jeszcze w kolejce, także czekający na follow-up."""
        query = "SELECT * FROM recipients WHERE status = ?"
        params: list[Any] = [STATUS_PENDING]
        if tag:
            query += " AND tags LIKE ?"
            params.append('%"' + tag + '"%')
        query += " ORDER BY position, id LIMIT 1"
        with self._lock:
            row = self._conn.execute(query, params).fetchone()
        return self._to_recipient(row) if row else None

    def earliest_due(self, tag: str = "") -> str | None:
        """Najbliższy termin follow-upu, gdy nikt nie jest gotowy teraz."""
        query = "SELECT MIN(next_due_at) AS m FROM recipients WHERE status = ? AND next_due_at IS NOT NULL"
        params: list[Any] = [STATUS_PENDING]
        if tag:
            query += " AND tags LIKE ?"
            params.append('%"' + tag + '"%')
        with self._lock:
            row = self._conn.execute(query, params).fetchone()
        return row["m"] if row and row["m"] else None

    def mark_step_sent(
        self,
        recipient_id: int,
        stage: int,
        attempts: int,
        message_id: str = "",
        next_due_at: str | None = None,
    ) -> None:
        """Zapisuje wysłany krok. Brak kolejnego terminu kończy sekwencję."""
        status = STATUS_PENDING if next_due_at else STATUS_SENT
        with self._lock:
            self._conn.execute(
                "UPDATE recipients SET status = ?, stage = ?, attempts = ?, sent_at = ?, "
                "last_error = NULL, last_message_id = ?, next_due_at = ? WHERE id = ?",
                (status, stage, attempts, now_iso(), message_id, next_due_at, recipient_id),
            )
            self._conn.commit()

    def mark_sent(self, recipient_id: int, attempts: int) -> None:
        """Zgodność ze starszym API - kończy sekwencję dla odbiorcy."""
        self.mark_step_sent(recipient_id, 1, attempts)

    def mark_error(self, recipient_id: int, attempts: int, error: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE recipients SET status = ?, attempts = ?, last_error = ?, "
                "next_due_at = NULL WHERE id = ?",
                (STATUS_ERROR, attempts, (error or "")[:500], recipient_id),
            )
            self._conn.commit()

    def counts(self, tag: str = "") -> dict[str, int]:
        query = "SELECT status, COUNT(*) AS c FROM recipients"
        params: list[Any] = []
        if tag:
            query += " WHERE tags LIKE ?"
            params.append('%"' + tag + '"%')
        query += " GROUP BY status"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        result = {status: 0 for status in STATUS_LABELS}
        for row in rows:
            result[row["status"]] = row["c"]
        result["total"] = sum(result[status] for status in STATUS_LABELS)
        return result

    # ---------------------------------------------------------- licznik dzienny

    @staticmethod
    def today() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def bump_sent_today(self) -> int:
        day = self.today()
        with self._lock:
            self._conn.execute(
                "INSERT INTO sent_counter (day, count) VALUES (?, 1) "
                "ON CONFLICT(day) DO UPDATE SET count = count + 1",
                (day,),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT count FROM sent_counter WHERE day = ?", (day,)
            ).fetchone()
        return row["count"] if row else 0

    def sent_today(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT count FROM sent_counter WHERE day = ?", (self.today(),)
            ).fetchone()
        return row["count"] if row else 0

    def sent_history(self, days: int = 14) -> list[tuple[str, int]]:
        """Ostatnie N dni, od najstarszego, z zerami dla dni bez wysyłki."""
        with self._lock:
            rows = self._conn.execute("SELECT day, count FROM sent_counter").fetchall()
        mapa = {row["day"]: row["count"] for row in rows}
        dzis = datetime.now().date()
        wynik = []
        for offset in range(days - 1, -1, -1):
            dzien = (dzis - timedelta(days=offset)).strftime("%Y-%m-%d")
            wynik.append((dzien, mapa.get(dzien, 0)))
        return wynik

    # --------------------------------------------------------- kopia zapasowa

    def backup_to(self, target: str) -> None:
        """Bezpieczna kopia bazy, także przy trwającej kampanii.

        Używa wbudowanego mechanizmu SQLite zamiast kopiowania pliku - dzięki temu
        nie trzeba zamykać programu ani martwić się o pliki -wal i -shm.
        """
        with self._lock:
            docelowa = sqlite3.connect(target)
            try:
                self._conn.backup(docelowa)
            finally:
                docelowa.close()

    # --------------------------------------------------------------------- log

    def log(self, level: str, message: str, email: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO log (ts, level, email, message) VALUES (?, ?, ?, ?)",
                (now_iso(), level, email, message),
            )
            self._conn.commit()

    def list_log(self, limit: int = 500, level: str | None = None) -> list[sqlite3.Row]:
        query = "SELECT * FROM log"
        params: list[Any] = []
        if level:
            query += " WHERE level = ?"
            params.append(level)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            return self._conn.execute(query, params).fetchall()

    def clear_log(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM log")
            self._conn.commit()


def verify_backup(path: str) -> tuple[bool, str]:
    """Sprawdza, czy plik jest bazą DripSendera, zanim nadpiszemy działającą."""
    try:
        conn = sqlite3.connect("file:" + path + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return False, "Nie udało się otworzyć pliku: " + str(exc)
    try:
        tabele = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    except sqlite3.DatabaseError:
        return False, "To nie jest plik bazy danych."
    finally:
        conn.close()

    brakujace = {"settings", "recipients", "fields"} - tabele
    if brakujace:
        return False, "Plik nie wygląda na kopię DripSendera (brak tabel: " + ", ".join(sorted(brakujace)) + ")."
    return True, "Kopia wygląda poprawnie."
