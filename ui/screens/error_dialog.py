"""Error / log detail dialogs."""

from __future__ import annotations

from typing import List, Optional

import customtkinter as ctk

from ui.theme import COLORS, FONTS


def show_details(
    master,
    *,
    title: str,
    body: str,
) -> None:
    dialog = ctk.CTkToplevel(master)
    dialog.title(title)
    dialog.geometry("460x360")
    dialog.configure(fg_color=COLORS["bg"])
    dialog.transient(master)
    dialog.grab_set()

    ctk.CTkLabel(
        dialog,
        text=title,
        font=FONTS["heading"],
        text_color=COLORS["text"],
    ).pack(anchor="w", padx=16, pady=(16, 8))

    box = ctk.CTkTextbox(
        dialog,
        font=FONTS["small"],
        fg_color=COLORS["panel"],
        text_color=COLORS["muted"],
        wrap="word",
    )
    box.pack(fill="both", expand=True, padx=16, pady=(0, 12))
    box.insert("1.0", body)
    box.configure(state="disabled")

    ctk.CTkButton(
        dialog,
        text="CLOSE",
        command=dialog.destroy,
        fg_color=COLORS["panel_alt"],
        hover_color=COLORS["border"],
        text_color=COLORS["text"],
    ).pack(pady=(0, 16))


def show_log(master, lines: List[str]) -> None:
    show_details(
        master,
        title="Minecraft log",
        body="\n".join(lines) if lines else "(empty log)",
    )
