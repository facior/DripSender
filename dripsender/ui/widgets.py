"""Wspólne elementy interfejsu: karty, kafelki statystyk, tabela."""

from __future__ import annotations

from tkinter import ttk
from typing import Callable, Sequence

import customtkinter as ctk

from . import theme


class Card(ctk.CTkFrame):
    """Panel z tytułem i miejscem na zawartość (``body``)."""

    def __init__(self, master, title: str = "", subtitle: str = "", **kwargs) -> None:
        kwargs.setdefault("fg_color", theme.SURFACE)
        kwargs.setdefault("corner_radius", 12)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", theme.BORDER)
        super().__init__(master, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        row = 0
        if title:
            ctk.CTkLabel(
                self, text=title, font=theme.font(14, "bold"), text_color=theme.TEXT, anchor="w"
            ).grid(row=row, column=0, sticky="ew", padx=18, pady=(16, 0))
            row += 1
        if subtitle:
            ctk.CTkLabel(
                self,
                text=subtitle,
                font=theme.font(11),
                text_color=theme.MUTED,
                anchor="w",
                justify="left",
                wraplength=680,
            ).grid(row=row, column=0, sticky="ew", padx=18, pady=(2, 0))
            row += 1

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=row, column=0, sticky="nsew", padx=18, pady=(12, 16))
        self.body.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(row, weight=1)


class StatTile(ctk.CTkFrame):
    """Kafelek z dużą liczbą i podpisem."""

    def __init__(self, master, label: str, value: str = "0", color: str | None = None) -> None:
        super().__init__(
            master,
            fg_color=theme.SURFACE_HI,
            corner_radius=10,
            border_width=1,
            border_color=theme.BORDER,
        )
        self.grid_columnconfigure(0, weight=1)
        self.value_label = ctk.CTkLabel(
            self,
            text=value,
            font=theme.font(26, "bold"),
            text_color=color or theme.TEXT,
            anchor="w",
        )
        self.value_label.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 0))
        ctk.CTkLabel(
            self, text=label, font=theme.font(11), text_color=theme.MUTED, anchor="w"
        ).grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))

    def set(self, value: str | int) -> None:
        self.value_label.configure(text=str(value))


def entry(
    master, placeholder: str = "", show: str | None = None, height: int = 34, **kwargs
) -> ctk.CTkEntry:
    return ctk.CTkEntry(
        master,
        placeholder_text=placeholder,
        show=show,
        height=height,
        corner_radius=8,
        border_color=theme.BORDER,
        fg_color=theme.SURFACE_HI,
        text_color=theme.TEXT,
        font=theme.font(12),
        **kwargs,
    )


def button(
    master,
    text: str,
    command: Callable[[], None] | None = None,
    kind: str = "primary",
    width: int = 130,
    height: int = 36,
    **kwargs,
) -> ctk.CTkButton:
    palette = {
        "primary": (theme.ACCENT, theme.ACCENT_HOVER, "#ffffff"),
        "ghost": ("transparent", theme.SURFACE_HI, theme.TEXT),
        "danger": (theme.ERR, theme.ERR_HOVER, "#ffffff"),
        "success": (theme.OK, theme.OK_DIM, "#0d1117"),
    }
    fg, hover, text_color = palette.get(kind, palette["primary"])
    return ctk.CTkButton(
        master,
        text=text,
        command=command,
        width=width,
        height=height,
        corner_radius=8,
        fg_color=fg,
        hover_color=hover,
        text_color=text_color,
        border_width=1 if kind == "ghost" else 0,
        border_color=theme.BORDER,
        font=theme.font(12, "bold"),
        **kwargs,
    )


def textbox(master, **kwargs) -> ctk.CTkTextbox:
    return ctk.CTkTextbox(
        master,
        corner_radius=8,
        border_width=1,
        border_color=theme.BORDER,
        fg_color=theme.SURFACE_HI,
        text_color=theme.TEXT,
        font=theme.mono(12),
        wrap="word",
        **kwargs,
    )


class DataTable(ctk.CTkFrame):
    """Tabela oparta na ttk.Treeview z paskiem przewijania."""

    def __init__(
        self,
        master,
        columns: Sequence[tuple[str, str, int]],
        on_double_click: Callable[[], None] | None = None,
        selectmode: str = "extended",
        horizontal_scroll: bool = False,
    ) -> None:
        super().__init__(
            master,
            fg_color=theme.SURFACE,
            corner_radius=10,
            border_width=1,
            border_color=theme.BORDER,
        )
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        keys = [c[0] for c in columns]
        self.column_titles = {c[0]: c[1] for c in columns}
        self.tree = ttk.Treeview(
            self,
            columns=keys,
            show="headings",
            style="Mailer.Treeview",
            selectmode=selectmode,
        )
        for key, title, width in columns:
            self.tree.heading(key, text=title, anchor="w")
            self.tree.column(key, width=width, anchor="w", stretch=(width >= 200))
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)

        scrollbar = ttk.Scrollbar(
            self, orient="vertical", command=self.tree.yview, style="Mailer.Vertical.TScrollbar"
        )
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=6)
        self.tree.configure(yscrollcommand=scrollbar.set)

        if horizontal_scroll:
            h_scroll = ttk.Scrollbar(
                self,
                orient="horizontal",
                command=self.tree.xview,
                style="Mailer.Horizontal.TScrollbar",
            )
            h_scroll.grid(row=1, column=0, sticky="ew", padx=(6, 0), pady=(0, 6))
            self.tree.configure(xscrollcommand=h_scroll.set)

        for status, color in theme.STATUS_COLORS.items():
            self.tree.tag_configure(status, foreground=color)
        for level, color in theme.LEVEL_COLORS.items():
            self.tree.tag_configure("lvl_" + level, foreground=color)
        self.tree.tag_configure("odd", background=theme.SURFACE_HI)

        if on_double_click:
            self.tree.bind("<Double-1>", lambda _event: on_double_click())

    def bind_headings(self, callback: Callable[[str], None]) -> None:
        """Klik w nagłówek kolumny woła callback z jej kluczem."""
        for key in self.column_titles:
            self.tree.heading(key, command=lambda k=key: callback(k))

    def set_sort_indicator(self, active_key: str, descending: bool) -> None:
        strzalka = "  ▼" if descending else "  ▲"
        for key, title in self.column_titles.items():
            self.tree.heading(key, text=title + (strzalka if key == active_key else ""))

    def clear(self) -> None:
        self.tree.delete(*self.tree.get_children())

    def add_row(self, row_id: str, values: Sequence[str], tags: Sequence[str] = ()) -> None:
        self.tree.insert("", "end", iid=row_id, values=list(values), tags=tuple(tags))

    def selected_ids(self) -> list[str]:
        return list(self.tree.selection())

    def bind_select(self, callback: Callable[[], None]) -> None:
        self.tree.bind("<<TreeviewSelect>>", lambda _event: callback())


class BarChart(ctk.CTkFrame):
    """Prosty wykres słupkowy na płótnie - bez dodatkowych bibliotek."""

    def __init__(self, master, height: int = 150) -> None:
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.canvas = ctk.CTkCanvas(
            self, height=height, highlightthickness=0, bg=theme.SURFACE
        )
        self.canvas.grid(row=0, column=0, sticky="ew")
        self.dane: list[tuple[str, int]] = []
        self.limit = 0
        self.canvas.bind("<Configure>", lambda _e: self._render())

    def set_data(self, dane: list[tuple[str, int]], limit: int = 0) -> None:
        self.dane = list(dane)
        self.limit = limit
        self._render()

    def _render(self) -> None:
        self.canvas.delete("all")
        szerokosc = self.canvas.winfo_width()
        wysokosc = self.canvas.winfo_height()
        if szerokosc < 20 or wysokosc < 20 or not self.dane:
            return

        margines_dol = 22
        margines_gora = 16
        pole = wysokosc - margines_dol - margines_gora
        maksimum = max([wartosc for _, wartosc in self.dane] + [1])

        krok = szerokosc / len(self.dane)
        szer_slupka = max(6, min(38, krok * 0.6))

        # Linia limitu dziennego, jeśli mieści się w skali.
        if self.limit and self.limit <= maksimum * 1.4:
            y = margines_gora + pole * (1 - self.limit / max(maksimum, self.limit))
            self.canvas.create_line(
                0, y, szerokosc, y, fill=theme.WARN, dash=(4, 3), width=1
            )
            self.canvas.create_text(
                szerokosc - 6, y - 8, text="limit " + str(self.limit),
                fill=theme.WARN, anchor="e", font=("Segoe UI", 8),
            )

        for index, (dzien, wartosc) in enumerate(self.dane):
            srodek = krok * (index + 0.5)
            x0 = srodek - szer_slupka / 2
            x1 = srodek + szer_slupka / 2
            wysokosc_slupka = pole * (wartosc / maksimum) if wartosc else 0
            y1 = margines_gora + pole
            y0 = y1 - wysokosc_slupka
            kolor = theme.ACCENT if wartosc else theme.BORDER
            if wartosc == 0:
                self.canvas.create_line(x0, y1, x1, y1, fill=theme.BORDER, width=2)
            else:
                self.canvas.create_rectangle(x0, y0, x1, y1, fill=kolor, outline="")
                self.canvas.create_text(
                    srodek, y0 - 7, text=str(wartosc), fill=theme.MUTED,
                    font=("Segoe UI", 8), anchor="s",
                )
            self.canvas.create_text(
                srodek, wysokosc - 8, text=dzien[8:10] + "." + dzien[5:7],
                fill=theme.MUTED, font=("Segoe UI", 8),
            )
