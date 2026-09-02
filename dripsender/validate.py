"""Sprawdzanie listy odbiorców przed wysyłką.

Wyłapuje trzy rodzaje kłopotów, zanim zamienią się w odbicia i utratę reputacji
skrzynki: literówki w domenach, adresy ogólne o niskiej skuteczności oraz domeny,
które w ogóle nie przyjmują poczty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

try:  # pragma: no cover - opcjonalna zależność
    import dns.resolver

    _HAS_DNS = True
except Exception:  # pragma: no cover
    dns = None  # type: ignore[assignment]
    _HAS_DNS = False

# Najczęstsze literówki w popularnych domenach.
LITEROWKI = {
    "gmial.com": "gmail.com",
    "gmai.com": "gmail.com",
    "gmail.pl": "gmail.com",
    "gmaill.com": "gmail.com",
    "gmail.co": "gmail.com",
    "gmil.com": "gmail.com",
    "wp.p": "wp.pl",
    "wp.com": "wp.pl",
    "onet.p": "onet.pl",
    "o2.p": "o2.pl",
    "intera.pl": "interia.pl",
    "interia.com": "interia.pl",
    "wpp.pl": "wp.pl",
    "outlok.com": "outlook.com",
    "hotmial.com": "hotmail.com",
    "yaho.com": "yahoo.com",
}

# Adresy ogólne - trafiają do skrzynki zbiorczej, odpowiadalność jest niska.
ADRESY_OGOLNE = {
    "info", "biuro", "office", "kontakt", "contact", "sekretariat", "recepcja",
    "admin", "administracja", "poczta", "mail", "firma", "sklep", "bok",
    "no-reply", "noreply", "sprzedaz", "marketing", "hr", "rekrutacja",
}

POZIOM_BLAD = "blad"
POZIOM_OSTRZEZENIE = "ostrzezenie"


def dns_available() -> bool:
    return _HAS_DNS


@dataclass
class Uwaga:
    recipient_id: int
    email: str
    poziom: str
    opis: str
    podpowiedz: str = ""


@dataclass
class Raport:
    sprawdzone: int = 0
    uwagi: list[Uwaga] = field(default_factory=list)
    domeny_bez_poczty: set[str] = field(default_factory=set)
    dns_sprawdzony: bool = False

    @property
    def bledy(self) -> list[Uwaga]:
        return [u for u in self.uwagi if u.poziom == POZIOM_BLAD]

    @property
    def ostrzezenia(self) -> list[Uwaga]:
        return [u for u in self.uwagi if u.poziom == POZIOM_OSTRZEZENIE]

    def podsumowanie(self) -> str:
        if not self.uwagi:
            return "Sprawdzono " + str(self.sprawdzone) + " adresów - wszystko wygląda dobrze."
        czesci = ["Sprawdzono " + str(self.sprawdzone) + " adresów"]
        if self.bledy:
            czesci.append("do poprawy: " + str(len(self.bledy)))
        if self.ostrzezenia:
            czesci.append("do rozważenia: " + str(len(self.ostrzezenia)))
        if not self.dns_sprawdzony:
            czesci.append("bez sprawdzania domen w DNS")
        return ", ".join(czesci) + "."


def domena(email: str) -> str:
    return email.split("@")[-1].strip().lower() if "@" in email else ""


def czesc_lokalna(email: str) -> str:
    return email.split("@")[0].strip().lower() if "@" in email else email.lower()


def sprawdz_mx(nazwa: str, timeout: float = 3.0) -> bool:
    """Czy domena ma rekord MX albo chociaż A. Brak = poczta nie dojdzie."""
    if not _HAS_DNS or not nazwa:
        return True
    resolver = dns.resolver.Resolver()
    resolver.lifetime = timeout
    resolver.timeout = timeout
    try:
        odpowiedz = resolver.resolve(nazwa, "MX")
        if len(odpowiedz):
            return True
    except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        pass
    except dns.resolver.NXDOMAIN:
        return False
    except Exception:  # noqa: BLE001 - brak sieci nie może oskarżać adresu
        return True
    try:
        resolver.resolve(nazwa, "A")
        return True
    except dns.resolver.NXDOMAIN:
        return False
    except Exception:  # noqa: BLE001
        return True


def sprawdz(
    recipients,
    sprawdzaj_dns: bool = True,
    postep: Callable[[int, int], None] | None = None,
) -> Raport:
    """Przegląda listę odbiorców i zwraca raport z uwagami."""
    raport = Raport(sprawdzone=len(recipients))
    domeny: dict[str, list] = {}

    for recipient in recipients:
        adres = recipient.email.strip().lower()
        nazwa_domeny = domena(adres)
        domeny.setdefault(nazwa_domeny, []).append(recipient)

        if nazwa_domeny in LITEROWKI:
            raport.uwagi.append(
                Uwaga(
                    recipient.id,
                    recipient.email,
                    POZIOM_BLAD,
                    "Domena wygląda na literówkę.",
                    "Czy chodziło o " + LITEROWKI[nazwa_domeny] + "?",
                )
            )
            continue

        if czesc_lokalna(adres) in ADRESY_OGOLNE:
            raport.uwagi.append(
                Uwaga(
                    recipient.id,
                    recipient.email,
                    POZIOM_OSTRZEZENIE,
                    "Adres ogólny - trafia do skrzynki zbiorczej.",
                    "Jeśli masz adres do konkretnej osoby, odpowiedź jest znacznie bardziej prawdopodobna.",
                )
            )

    if sprawdzaj_dns and _HAS_DNS:
        raport.dns_sprawdzony = True
        unikalne = [d for d in domeny if d and d not in LITEROWKI]
        for numer, nazwa in enumerate(unikalne, start=1):
            if postep:
                postep(numer, len(unikalne))
            if sprawdz_mx(nazwa):
                continue
            raport.domeny_bez_poczty.add(nazwa)
            for recipient in domeny[nazwa]:
                raport.uwagi.append(
                    Uwaga(
                        recipient.id,
                        recipient.email,
                        POZIOM_BLAD,
                        "Domena nie przyjmuje poczty (brak wpisu w DNS).",
                        "Wysyłka na ten adres na pewno się odbije.",
                    )
                )
    return raport
