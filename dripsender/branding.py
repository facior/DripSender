"""Dane marki i autora w jednym miejscu.

Wszystko, co widzi użytkownik w tytule okna, w zakładce "O autorze" i w nazwie
katalogu z danymi, pochodzi stąd. Zmiana nazwy aplikacji to edycja tego pliku.

Pola oznaczone jako DO UZUPEŁNIENIA są puste - aplikacja pokazuje wtedy wyraźny
znacznik zamiast wartości i nadal działa poprawnie.
"""

from __future__ import annotations

# --------------------------------------------------------------------- aplikacja

APP_NAME = "DripSender"
APP_SLUG = "DripSender"  # katalog danych i wpis w Menedżerze poświadczeń
APP_TAGLINE = "wysyłka po jednym mailu"
APP_DESCRIPTION = (
    "Wysyła maile do listy klientów pojedynczo, w równych odstępach czasu - "
    "domyślnie jeden co 5 minut."
)
VERSION = "1.4.0"
YEAR = "2026"
LICENSE = "Do dowolnego użytku, także komercyjnego."

# ------------------------------------------------------------------------ autor

AUTHOR_NAME = "Łukasz Kubieniec"
AUTHOR_ROLE = ""  # DO UZUPEŁNIENIA - np. "Programista" (opcjonalne)
AUTHOR_EMAIL = "lukasz.kubieniec00@gmail.com"
AUTHOR_PHONE = ""  # DO UZUPEŁNIENIA - opcjonalne
AUTHOR_WWW = ""  # DO UZUPEŁNIENIA - opcjonalne

# --------------------------------------------------------------- co potrafi

FEATURES = [
    (
        "Wysyłka w równych odstępach",
        "Jedna wiadomość na raz, co ustawiony czas. Skrzynka nie wygląda na masówkę "
        "i nie łapie blokady za zbyt szybkie tempo.",
    ),
    (
        "Treść pod konkretnego klienta",
        "Imię, nazwa firmy i dowolne własne pola podstawiają się same w temat i treść.",
    ),
    (
        "Pamięta, gdzie skończyła",
        "Zamknięcie programu nie gubi kolejki - po ponownym uruchomieniu wysyłka rusza "
        "od pierwszego pominiętego klienta. Nikt nie dostanie wiadomości dwa razy.",
    ),
    (
        "Załączniki",
        "Oferta, cennik czy katalog dołączane automatycznie do każdej wiadomości.",
    ),
    (
        "Podgląd i wysyłka próbna",
        "Zanim ruszy kampania, zobaczysz gotową wiadomość z podstawionymi danymi "
        "i wyślesz próbkę na własny adres.",
    ),
    (
        "Historia z eksportem",
        "Każda wysyłka i każdy błąd zapisane z datą, do wyciągnięcia w pliku CSV.",
    ),
    (
        "Wysyłka tylko w godzinach pracy",
        "Wskazujesz dni i godziny, a program czeka poza nimi i wraca do pracy sam. "
        "Żaden mail nie wyjdzie o trzeciej w nocy.",
    ),
    (
        "Praca w tle",
        "Zamknięte okno chowa się do zasobnika, a kampania leci dalej. Program potrafi "
        "też wstawać razem z Windows i wznawiać przerwaną wysyłkę.",
    ),
    (
        "Follow-upy do tych, którzy nie odpowiedzieli",
        "Sekwencja kilku wiadomości z własnymi odstępami. Kto odpisze, wypada z niej "
        "automatycznie - większość odpowiedzi w zimnym mailingu przychodzi właśnie "
        "po drugiej wiadomości.",
    ),
    (
        "Rozpoznawanie odpowiedzi i odbić",
        "Program czyta skrzynkę i sam oznacza, kto odpisał, czyj adres nie istnieje "
        "i kto poprosił o wypisanie.",
    ),
    (
        "Grupy odbiorców i import z Excela",
        "Wczytujesz listę z pliku CSV lub XLSX, dzielisz ją na grupy i wysyłasz "
        "kampanię tylko do wybranej części.",
    ),
    (
        "Sprawdzenie listy przed wysyłką",
        "Wyłapuje literówki w domenach, adresy ogólne i domeny, które w ogóle nie "
        "przyjmują poczty - zanim zamienią się w odbicia.",
    ),
    (
        "Dzienny limit i wypisania",
        "Limit chroni skrzynkę przed blokadą, a adres, który poprosi o wypisanie, "
        "jest pomijany na stałe.",
    ),
]

# ------------------------------------------------------- bezpieczeństwo danych

PRIVACY_NOTES = [
    (
        "Lista klientów nie opuszcza tego komputera",
        "Wszystkie dane siedzą w jednym pliku na Twoim dysku. Nie ma serwera "
        "pośredniczącego ani konta w chmurze.",
    ),
    (
        "Hasło w skarbcu Windows",
        "Hasło do poczty trafia do systemowego Menedżera poświadczeń, a nie do pliku "
        "z ustawieniami, który dałoby się po prostu otworzyć notatnikiem.",
    ),
    (
        "Połączenie szyfrowane",
        "Wiadomości idą prosto z Twojego komputera na serwer poczty, po SSL/TLS.",
    ),
    (
        "Możliwość wypisania w każdej wiadomości",
        "Stopka z informacją, jak zrezygnować, plus nagłówek List-Unsubscribe, "
        "dzięki któremu Gmail pokazuje przycisk Wypisz się.",
    ),
    (
        "PIN przy uruchomieniu",
        "Opcjonalna blokada programu. Sam PIN nie jest nigdzie zapisywany - w bazie "
        "leży wyłącznie jego nieodwracalny skrót.",
    ),
    (
        "Nic nie wraca do autora",
        "Program nie wysyła żadnych statystyk, listy odbiorców ani raportów. "
        "Poza wysyłką maili i czytaniem skrzynki nie łączy się z niczym.",
    ),
]


def author_fields() -> list[tuple[str, str, bool]]:
    """Zwraca (etykieta, wartość, czy_uzupełnione) dla zakładki o autorze."""
    raw = [
        ("Imię i nazwisko", AUTHOR_NAME),
        ("Rola", AUTHOR_ROLE),
        ("E-mail", AUTHOR_EMAIL),
        ("Telefon", AUTHOR_PHONE),
        ("Strona www", AUTHOR_WWW),
    ]
    return [(label, value.strip(), bool(value.strip())) for label, value in raw]


def has_author_data() -> bool:
    return any(filled for _, _, filled in author_fields())
