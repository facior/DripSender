"""Okno czasowe wysyłki: dni tygodnia i godziny, w których wolno wysyłać."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

DAY_NAMES = ["pon", "wt", "śr", "czw", "pt", "sob", "ndz"]
DAY_NAMES_LONG = [
    "poniedziałek",
    "wtorek",
    "środa",
    "czwartek",
    "piątek",
    "sobota",
    "niedziela",
]


def parse_time(value: str, default: time) -> time:
    """Przyjmuje '9', '9:30', '09:30'. Przy bzdurze zwraca wartość domyślną."""
    text = (value or "").strip().replace(".", ":")
    if not text:
        return default
    parts = text.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 and parts[1] else 0
    except ValueError:
        return default
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return default
    return time(hour, minute)


def parse_days(value: str) -> set[int]:
    """'0,1,2,3,4' -> {0,1,2,3,4}, gdzie 0 to poniedziałek."""
    days: set[int] = set()
    for part in (value or "").split(","):
        part = part.strip()
        if part.isdigit() and 0 <= int(part) <= 6:
            days.add(int(part))
    return days


@dataclass
class SendWindow:
    """Przedział, w którym wolno wysyłać. Obsługuje też okna przez północ."""

    enabled: bool = False
    start: time = time(9, 0)
    end: time = time(17, 0)
    days: frozenset[int] = frozenset({0, 1, 2, 3, 4})

    @classmethod
    def from_store(cls, store) -> "SendWindow":
        # Pustego zestawu dni NIE zastępujemy domyślnym: brak zaznaczenia ma zostać
        # brakiem, żeby kontrola przed startem mogła o tym powiedzieć wprost.
        return cls(
            enabled=store.get_bool("hours_enabled"),
            start=parse_time(store.get_setting("hours_from", "09:00"), time(9, 0)),
            end=parse_time(store.get_setting("hours_to", "17:00"), time(17, 0)),
            days=frozenset(parse_days(store.get_setting("hours_days", "0,1,2,3,4"))),
        )

    @property
    def overnight(self) -> bool:
        """Okno typu 22:00-06:00 przechodzi przez północ."""
        return self.start > self.end

    def _within_hours(self, moment: datetime) -> bool:
        current = moment.time()
        if self.start == self.end:
            return True  # pełna doba
        if self.overnight:
            return current >= self.start or current < self.end
        return self.start <= current < self.end

    def allows(self, moment: datetime | None = None) -> bool:
        """Czy w danej chwili wolno wysyłać."""
        if not self.enabled:
            return True
        moment = moment or datetime.now()
        if not self._within_hours(moment):
            return False
        # Dla okna przez północ liczy się dzień, w którym okno się zaczęło.
        day = moment.weekday()
        if self.overnight and moment.time() < self.end:
            day = (day - 1) % 7
        return day in self.days

    def next_open(self, moment: datetime | None = None) -> datetime | None:
        """Najbliższy moment, w którym okno będzie otwarte."""
        if not self.enabled or not self.days:
            return None
        moment = moment or datetime.now()
        if self.allows(moment):
            return moment
        probe = moment.replace(second=0, microsecond=0)
        for _ in range(8 * 24 * 60):  # tydzień z zapasem, krok minutowy
            probe += timedelta(minutes=1)
            if self.allows(probe):
                return probe
        return None

    def describe(self) -> str:
        if not self.enabled:
            return "bez ograniczeń - o każdej porze"
        if not self.days:
            return "żaden dzień nie jest zaznaczony - wysyłka nie ruszy"
        dni = ", ".join(DAY_NAMES[d] for d in sorted(self.days))
        return dni + "  " + self.start.strftime("%H:%M") + "-" + self.end.strftime("%H:%M")


def human_moment(moment: datetime, now: datetime | None = None) -> str:
    """'dziś o 14:30', 'jutro o 09:00', 'w czwartek o 09:00'."""
    now = now or datetime.now()
    delta_days = (moment.date() - now.date()).days
    czas = moment.strftime("%H:%M")
    if delta_days == 0:
        return "dziś o " + czas
    if delta_days == 1:
        return "jutro o " + czas
    if 2 <= delta_days <= 6:
        return "w " + DAY_NAMES_LONG[moment.weekday()] + " o " + czas
    return moment.strftime("%d.%m") + " o " + czas
