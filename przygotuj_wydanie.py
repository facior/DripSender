"""Przygotowuje pliki do wgrania na serwer aktualizacji.

Po zbudowaniu programu (``build.bat``) uruchom jedno z dwóch:

    py -3.13 przygotuj_wydanie.py --github uzytkownik/dripsender
    py -3.13 przygotuj_wydanie.py https://example.com/dripsender/1.4.0

Tryb ``--github`` sam składa adresy w formacie GitHub Releases i podaje **stały**
adres dla klienta (``releases/latest/download/update.json``), który nie zmienia się
przy kolejnych wydaniach.

Skrypt policzy sumę kontrolną pliku ``dist/DripSender.exe``, przemianuje go na
wersjonowaną nazwę i wygeneruje ``dist/update.json``. Oba pliki wgrywasz w to samo
miejsce (przy GitHubie: jako załączniki jednego wydania).

Opis zmian możesz podać w pliku ``ZMIANY.txt`` obok skryptu - trafi do okna
aktualizacji, które zobaczy klient.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dripsender import branding  # noqa: E402

KATALOG = Path(__file__).resolve().parent
DIST = KATALOG / "dist"
ZMIANY = KATALOG / "ZMIANY.txt"


def suma_sha256(sciezka: Path) -> str:
    skrot = hashlib.sha256()
    with open(sciezka, "rb") as plik:
        for kawalek in iter(lambda: plik.read(1024 * 1024), b""):
            skrot.update(kawalek)
    return skrot.hexdigest()


def main() -> int:
    argumenty = sys.argv[1:]
    if not argumenty:
        print("Podaj, dokąd trafią pliki. Dwa sposoby:")
        print("  py -3.13 przygotuj_wydanie.py --github uzytkownik/repozytorium")
        print("  py -3.13 przygotuj_wydanie.py https://example.com/dripsender/1.4.0")
        return 1

    tag = "v" + branding.VERSION
    adres_klienta = ""
    if argumenty[0] == "--github":
        if len(argumenty) < 2 or "/" not in argumenty[1]:
            print("BŁĄD: podaj repozytorium w postaci uzytkownik/repozytorium.")
            return 1
        repo = argumenty[1].strip("/")
        baza = "https://github.com/" + repo + "/releases/download/" + tag
        # Adres 'latest' zawsze wskazuje najnowsze wydanie, więc klient wpisuje go raz.
        adres_klienta = "https://github.com/" + repo + "/releases/latest/download/update.json"
    else:
        baza = argumenty[0].rstrip("/")
        if not baza.startswith("https://"):
            print("BŁĄD: adres musi zaczynać się od https:// - program odrzuci inny.")
            return 1
        adres_klienta = baza + "/update.json"

    zbudowany = DIST / (branding.APP_SLUG + ".exe")
    if not zbudowany.is_file():
        print("BŁĄD: nie znaleziono " + str(zbudowany) + ". Uruchom najpierw build.bat.")
        return 1

    wersjonowany = DIST / (branding.APP_SLUG + "-" + branding.VERSION + ".exe")
    if wersjonowany.resolve() != zbudowany.resolve():
        shutil.copyfile(zbudowany, wersjonowany)

    suma = suma_sha256(wersjonowany)
    opis = ZMIANY.read_text(encoding="utf-8").strip() if ZMIANY.is_file() else ""

    manifest = {
        "version": branding.VERSION,
        "url": baza + "/" + wersjonowany.name,
        "sha256": suma,
        "notes": opis,
    }
    plik_manifestu = DIST / "update.json"
    plik_manifestu.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("Gotowe. Wgraj oba pliki w to samo miejsce:")
    print("  " + str(wersjonowany) + "   (" + str(round(wersjonowany.stat().st_size / 1048576, 1)) + " MB)")
    print("  " + str(plik_manifestu))
    print()
    if argumenty[0] == "--github":
        print()
        print("Na GitHubie: Releases > Draft a new release")
        print("  tag:        " + tag)
        print("  zalaczniki: " + wersjonowany.name + "  oraz  update.json")
        print("  UWAGA: repozytorium musi byc publiczne, inaczej pobranie wymaga tokena.")
    print()
    print("Adres do wpisania klientowi w Ustawieniach (wpisuje go raz):")
    print("  " + adres_klienta)
    print()
    print("Suma kontrolna: " + suma)
    if not opis:
        print()
        print("Uwaga: nie ma pliku ZMIANY.txt, więc klient zobaczy okno bez opisu zmian.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
