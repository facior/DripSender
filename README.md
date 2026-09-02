# DripSender

Desktopowa aplikacja (Windows) do wysyłki maili do listy klientów **po jednym, w równych odstępach czasu** — domyślnie jeden mail co 5 minut. Prowadzi odbiorców przez **sekwencję wiadomości** (pierwszy mail + follow-upy), czyta skrzynkę, żeby rozpoznać odpowiedzi i odbicia, i pracuje w tle.

---

## Jak to działa

Każdy odbiorca przechodzi przez kolejne kroki sekwencji. Kto odpisze, wypisze się albo odbije — wypada z dalszych kroków.

```
Start ──► klient 1 ──[5 min]──► klient 2 ──[5 min]──► klient 3 ──► ...
                │                    │
          [po 4 dniach]        odpisał → koniec
                ▼
          follow-up do klienta 1
```

Stan przeżywa zamknięcie programu: nikt nie dostanie tej samej wiadomości dwa razy.

## Zakładki

| Zakładka | Co robi |
|---|---|
| **Kampania** | Start / Pauza / Stop, licznik do następnego maila, wybór grupy docelowej, wykres 14 dni |
| **Odbiorcy** | Lista: dodawanie, import z CSV/Excela, grupy, sprawdzanie listy, sortowanie, eksport |
| **Sekwencja** | Kroki wiadomości: pierwszy mail i follow-upy, każdy z własnym szablonem i odstępem |
| **Ustawienia** | SMTP, tempo, godziny wysyłki, praca w tle, stopka wypisania, nasłuch skrzynki, PIN, kopie |
| **Historia** | Log wszystkich zdarzeń z eksportem do CSV |
| **Instrukcja** | Podpięcie krok po kroku jako żywy checklist + wyjaśnienie znaczników |
| **O autorze** | Kontakt, możliwości programu, co dzieje się z danymi, licencja |

Przy pierwszym uruchomieniu aplikacja otwiera się na **Instrukcji**, a nie na pustej Kampanii.

---

## Sekwencja i follow-upy

Zakładka **Sekwencja** to pasek kroków plus edytor wybranego kroku:

```
[1 · Wiadomość główna]   [2 · Follow-up po 4 dniach]   [– · Przypomnienie (wyłączony)]
        od razu                  po 4 dniach
```

- Pierwszy krok wychodzi zaraz po starcie kampanii.
- Każdy kolejny ma własne **opóźnienie w dniach**, liczone od poprzedniej wiadomości do tego odbiorcy.
- Krok można **wyłączyć** — zostaje w bibliotece, ale nie bierze udziału w wysyłce.
- Każdy krok ma własny temat, treść i załączniki.

W zimnym mailingu większość odpowiedzi przychodzi po follow-upie, nie po pierwszej wiadomości — dlatego drugi krok jest przygotowany od razu (domyślnie wyłączony, włączasz jednym kliknięciem).

## Nasłuch skrzynki (IMAP)

Po włączeniu w Ustawieniach program czyta pocztę na tym samym koncie i rozpoznaje:

| Co przychodzi | Co robi program |
|---|---|
| Odpowiedź od odbiorcy | status **Odpowiedział**, koniec sekwencji dla tej osoby |
| Raport niedostarczenia | status **Odbity** — adres nie działa |
| Odpowiedź zaczynająca się od STOP | status **Wypisany**, pomijany na stałe |

Odpowiedzi dopasowywane są najpierw po nagłówku `In-Reply-To` (czyli po identyfikatorze naszej wiadomości), a dopiero potem po adresie nadawcy — dzięki temu działa też wtedy, gdy klient odpisuje z innego adresu.

Słowo STOP musi stać **na początku własnej treści odbiorcy**. Cytat naszej stopki na dole odpowiedzi go nie wyzwala, więc zainteresowany klient nie zostanie przez pomyłkę wypisany.

**Program niczego nie kasuje ani nie przenosi** — tylko czyta. Wymaga włączonego IMAP na koncie Gmail i tego samego hasła aplikacji co wysyłka.

## Grupy odbiorców

Każdy odbiorca może należeć do dowolnych grup („hurtownie", „woj. śląskie"). Na pulpicie kampanii wybierasz, do której grupy leci wysyłka — reszta listy zostaje nietknięta. Dzięki temu jedna baza obsługuje wiele kampanii bez kasowania historii.

## Import z pliku

**Odbiorcy → Wczytaj plik** przyjmuje CSV i Excela (.xlsx). Program sam rozpoznaje separator i kodowanie, a kolumny dopasowuje po nagłówkach:

```
Nazwa firmy ; Osoba kontaktowa ; Adres e-mail ; Telefon
     ↓               ↓                 ↓
  {firma}         {imie}             email
```

Dopasowanie widać w oknie importu i można je poprawić ręcznie. Duplikaty i błędne adresy odpadają, a podsumowanie mówi ile czego wpadło.

## Sprawdzenie listy

**Odbiorcy → Sprawdź listę** przegląda bazę zanim ruszy wysyłka:

- **literówki w domenach** — `gmial.com`, `intera.pl`, `outlok.com` i podobne, z podpowiedzią poprawnej wersji,
- **domeny bez poczty** — sprawdzenie rekordów MX w DNS; taka wysyłka na pewno się odbije,
- **adresy ogólne** — `biuro@`, `info@`, `kontakt@` trafiają do skrzynki zbiorczej i rzadziej dostają odpowiedź.

Zaznaczone pozycje można usunąć albo oznaczyć jako pominięte.

---

## Personalizacja treści

Znaczniki w klamrach podmieniają się na dane konkretnego odbiorcy:

```
Temat:  Oferta współpracy dla {firma}

Dzień dobry {imie},

piszę w sprawie możliwej współpracy z firmą {firma}.
```

Domyślnie dostępne są `{email}`, `{imie}` i `{firma}`. Własne pola dodajesz w **Odbiorcy → Pola**. Każde pole ma **wartość domyślną** — wskakuje tam, gdzie odbiorca ma pustą rubrykę, więc nigdy nie wyjdzie „Dzień dobry ,".

Edytor ostrzega na pomarańczowo przed dwoma pułapkami: nieznanym znacznikiem (pójdzie w mailu dosłownie) i polem bez wartości domyślnej (zostawi dziurę w zdaniu).

## Godziny wysyłki i limit dzienny

- **Okno czasowe** — dni tygodnia i godziny. Poza nim program czeka i sam wraca do pracy („Wznowię jutro o 09:00"). Okno przez północ (22:00–06:00) też działa.
- **Limit dzienny** — domyślnie 450 wiadomości, poniżej limitu Gmaila (~500). Po wyczerpaniu kampania czeka do jutra.

## Praca w tle

- Krzyżyk chowa program do zasobnika, kampania leci dalej.
- Autostart z Windows (tylko w wersji `.exe`).
- Wznawianie kampanii przerwanej zamknięciem programu.

## Bezpieczeństwo

- Hasło SMTP w **Menedżerze poświadczeń Windows**, nie w pliku.
- Opcjonalny **PIN przy uruchomieniu** — w bazie leży wyłącznie jego nieodwracalny skrót (PBKDF2, 200 tys. iteracji).
- **Kopia zapasowa jednym kliknięciem** i przywracanie — kopię można zrobić przy działającej kampanii.
- Poza wysyłką maili i czytaniem skrzynki program nie łączy się z niczym.

---

## Konfiguracja Gmaila

Gmail **nie przyjmie** zwykłego hasła. Potrzebne jest 16-znakowe *hasło aplikacji*:

1. Włącz weryfikację dwuetapową na koncie Google.
2. Wejdź na <https://myaccount.google.com/apppasswords> (zakładka **Instrukcja** ma przycisk).
3. Wklej hasło w polu **Hasło aplikacji**.
4. Kliknij **Testuj połączenie** — powinno zwrócić „OK".

| Pole | Wysyłka (SMTP) | Nasłuch (IMAP) |
|---|---|---|
| Serwer | `smtp.gmail.com` | `imap.gmail.com` |
| Port | `465` | `993` |
| Szyfrowanie | SSL/TLS | SSL |

To samo hasło aplikacji obsługuje obie funkcje.

---

## Zmiana nazwy i danych autora

Wszystko, co dotyczy marki, siedzi w [dripsender/branding.py](dripsender/branding.py) — nazwa, wersja, dane autora oraz listy `FEATURES` i `PRIVACY_NOTES` zasilające zakładkę O autorze.

**Uwaga przy zmianie `APP_SLUG`:** wyznacza katalog `%APPDATA%\<APP_SLUG>` i wpis w Menedżerze poświadczeń. Po zmianie program zacznie od pustej bazy.

## Uruchamianie

```
build.bat                      # buduje dist\DripSender.exe
py -3.13 main.py               # wersja deweloperska
```

Dane: `%APPDATA%\DripSender\mailer.db`. Pusty plik `portable.txt` obok `.exe` przenosi je do podkatalogu `dane\`.

## Struktura projektu

```
main.py                     punkt wejścia
build.bat                   budowanie .exe
dripsender/
    branding.py             nazwa, wersja, dane autora
    paths.py                katalog danych, tryb przenośny
    store.py                SQLite: ustawienia, pola, odbiorcy, szablony, log
    security.py             hasło SMTP i PIN aplikacji
    mailer.py               SMTP, budowa wiadomości, szablony
    engine.py               wątek kampanii: sekwencja, odstępy, ponowienia
    schedule.py             okno czasowe wysyłki
    inbox.py                nasłuch IMAP: odpowiedzi, odbicia, wypisania
    importer.py             wczytywanie CSV i Excela
    validate.py             sprawdzanie listy przed wysyłką
    tray.py                 zasobnik systemowy i autostart
    ui/
        theme.py            kolory i style
        widgets.py          karty, kafelki, tabela, wykres
        dialogs.py          okna modalne
        app.py              główne okno i nawigacja
        campaign_view.py    pulpit kampanii
        recipients_view.py  lista odbiorców
        sequence_view.py    edytor sekwencji
        settings_view.py    ustawienia
        log_view.py         historia zdarzeń
        guide_view.py       instrukcja
        about_view.py       o autorze
```

## Zachowanie w sytuacjach brzegowych

- **Błąd wysyłki** — 2 ponowienia co 15 s, potem status „Błąd" i kampania leci dalej.
- **Odrzucone logowanie lub adres nadawcy** — kampania zatrzymuje się od razu.
- **Zamknięcie w trakcie** — krzyżyk chowa do zasobnika; przy prawdziwym zamknięciu kolejka czeka i wznawia się po starcie.
- **Poza godzinami / wyczerpany limit** — czekanie z podanym terminem wznowienia, nie błąd.
- **Wszyscy obsłużeni, ktoś czeka na follow-up** — kampania czeka do jego terminu.
- **Wypisany** nie wraca do kolejki nawet po zresetowaniu statusów całej listy.

## Czego program nie robi

- **Nie wysyła równolegle** — jeden mail na raz, z założenia.
- **Status „Zakończony" znaczy, że serwer przyjął wiadomość.** Odbicia wykrywa dopiero nasłuch skrzynki; przy wyłączonym IMAP zostają niezauważone.
- **Nie sprawdza treści pod kątem filtrów antyspamowych** — o wyglądzie i języku wiadomości decyduje użytkownik.
