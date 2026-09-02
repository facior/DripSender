"""Bezpieczne przechowywanie hasła SMTP.

Hasło trafia do Menedżera poświadczeń Windows (biblioteka ``keyring``).
Gdyby był niedostępny, używamy zaszyfrowanego zapisu w bazie - słabszego,
ale związanego z konkretnym komputerem i kontem użytkownika.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import uuid

from .branding import APP_SLUG as SERVICE

FALLBACK_KEY = "smtp_password_local"
METHOD_KEY = "password_storage"

try:  # pragma: no cover - zależne od systemu
    import keyring

    _HAS_KEYRING = True
except Exception:  # pragma: no cover
    keyring = None  # type: ignore[assignment]
    _HAS_KEYRING = False


def _machine_key() -> bytes:
    seed = f"{uuid.getnode()}::{os.environ.get('USERNAME', '')}::{SERVICE}"
    return hashlib.sha256(seed.encode("utf-8")).digest()


def _xor(data: bytes) -> bytes:
    key = _machine_key()
    return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(data))


def _obfuscate(text: str) -> str:
    return base64.b64encode(_xor(text.encode("utf-8"))).decode("ascii")


def _deobfuscate(text: str) -> str:
    try:
        return _xor(base64.b64decode(text.encode("ascii"))).decode("utf-8")
    except Exception:
        return ""


class PasswordVault:
    """Zapisuje/odczytuje hasło dla konkretnego konta SMTP."""

    def __init__(self, store) -> None:
        self.store = store

    @property
    def uses_keyring(self) -> bool:
        return self.store.get_setting(METHOD_KEY, "") == "keyring"

    def set(self, account: str, password: str) -> None:
        account = (account or "").strip()
        if not account:
            return
        if not password:
            self.delete(account)
            return
        if _HAS_KEYRING:
            try:
                keyring.set_password(SERVICE, account, password)
                self.store.set_setting(METHOD_KEY, "keyring")
                self.store.set_setting(FALLBACK_KEY, "")
                return
            except Exception:
                pass
        self.store.set_setting(FALLBACK_KEY, _obfuscate(password))
        self.store.set_setting(METHOD_KEY, "local")

    def get(self, account: str) -> str:
        account = (account or "").strip()
        if not account:
            return ""
        if _HAS_KEYRING:
            try:
                stored = keyring.get_password(SERVICE, account)
                if stored:
                    return stored
            except Exception:
                pass
        raw = self.store.get_setting(FALLBACK_KEY, "")
        return _deobfuscate(raw) if raw else ""

    def delete(self, account: str) -> None:
        account = (account or "").strip()
        if _HAS_KEYRING and account:
            try:
                keyring.delete_password(SERVICE, account)
            except Exception:
                pass
        self.store.set_setting(FALLBACK_KEY, "")
        self.store.set_setting(METHOD_KEY, "")

    def storage_label(self) -> str:
        if self.uses_keyring:
            return "Menedżer poświadczeń Windows"
        if self.store.get_setting(FALLBACK_KEY, ""):
            return "zaszyfrowany plik lokalny"
        return "brak zapisanego hasła"


# ------------------------------------------------------------- blokada programu

LOCK_ITERATIONS = 200_000


def _hash_pin(pin: str, salt: bytes) -> str:
    return base64.b64encode(
        hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, LOCK_ITERATIONS)
    ).decode("ascii")


def set_app_lock(store, pin: str) -> None:
    """Zapisuje skrót PIN-u. Samego PIN-u nigdzie nie trzymamy."""
    if not pin:
        store.update_settings({"app_lock_enabled": "0", "app_lock_hash": "", "app_lock_salt": ""})
        return
    salt = os.urandom(16)
    store.update_settings(
        {
            "app_lock_enabled": "1",
            "app_lock_salt": base64.b64encode(salt).decode("ascii"),
            "app_lock_hash": _hash_pin(pin, salt),
        }
    )


def check_app_lock(store, pin: str) -> bool:
    zapisany = store.get_setting("app_lock_hash", "")
    salt_b64 = store.get_setting("app_lock_salt", "")
    if not zapisany or not salt_b64:
        return True
    try:
        salt = base64.b64decode(salt_b64)
    except Exception:  # noqa: BLE001
        return False
    return hmac.compare_digest(_hash_pin(pin or "", salt), zapisany)


def app_lock_enabled(store) -> bool:
    return store.get_bool("app_lock_enabled") and bool(store.get_setting("app_lock_hash"))
