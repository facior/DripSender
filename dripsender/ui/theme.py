"""Kolory, czcionki i style widżetów."""

from __future__ import annotations

from tkinter import ttk

import customtkinter as ctk

BG = "#101319"
SURFACE = "#181c25"
SURFACE_HI = "#212734"
BORDER = "#2b3342"
TEXT = "#e8ebf2"
MUTED = "#8b94a8"
ACCENT = "#4c8dff"
ACCENT_HOVER = "#3a76e0"
OK = "#3ecf8e"
OK_DIM = "#1f6b4c"
WARN = "#f5a623"
ERR = "#ff5f5f"
ERR_HOVER = "#e04545"

FONT_FAMILY = "Segoe UI"

STATUS_COLORS = {
    "pending": MUTED,
    "sent": OK,
    "error": ERR,
    "skipped": WARN,
    "unsubscribed": "#b07cd6",
}

LEVEL_COLORS = {
    "ok": OK,
    "info": ACCENT,
    "warn": WARN,
    "error": ERR,
}


def font(size: int = 12, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)


def mono(size: int = 11) -> ctk.CTkFont:
    return ctk.CTkFont(family="Consolas", size=size)


def apply_appearance() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")


def style_tables(widget) -> None:
    """Stylizuje ttk.Treeview tak, aby pasował do reszty okna."""
    style = ttk.Style(widget)
    try:
        style.theme_use("clam")
    except Exception:  # noqa: BLE001 - motyw clam jest zwykle dostępny
        pass

    style.configure(
        "Mailer.Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=TEXT,
        rowheight=30,
        borderwidth=0,
        font=(FONT_FAMILY, 10),
    )
    style.configure(
        "Mailer.Treeview.Heading",
        background=SURFACE_HI,
        foreground=MUTED,
        relief="flat",
        borderwidth=0,
        padding=(8, 8),
        font=(FONT_FAMILY, 10, "bold"),
    )
    style.map(
        "Mailer.Treeview",
        background=[("selected", ACCENT)],
        foreground=[("selected", "#ffffff")],
    )
    style.map("Mailer.Treeview.Heading", background=[("active", BORDER)])
    style.layout(
        "Mailer.Treeview",
        [("Mailer.Treeview.treearea", {"sticky": "nswe"})],
    )

    style.configure(
        "Mailer.Vertical.TScrollbar",
        background=SURFACE_HI,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=MUTED,
        borderwidth=0,
        width=12,
    )
    style.map("Mailer.Vertical.TScrollbar", background=[("active", BORDER)])

    style.configure(
        "Mailer.Horizontal.TScrollbar",
        background=SURFACE_HI,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=MUTED,
        borderwidth=0,
    )
    style.map("Mailer.Horizontal.TScrollbar", background=[("active", BORDER)])
