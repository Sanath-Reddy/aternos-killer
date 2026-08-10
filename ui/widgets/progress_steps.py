"""Checklist-style progress for hosting startup."""

from __future__ import annotations

from typing import Dict, List

import customtkinter as ctk

from ui.theme import COLORS, FONTS


class ProgressSteps(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._rows: List[ctk.CTkLabel] = []

    def set_steps(self, steps: List[Dict[str, str]]) -> None:
        for row in self._rows:
            row.destroy()
        self._rows.clear()

        for step in steps:
            state = step.get("state", "pending")
            label = step.get("label", "")
            if state == "done":
                prefix, color = "✓", COLORS["ok"]
            elif state == "active":
                prefix, color = "…", COLORS["warn"]
            elif state == "error":
                prefix, color = "✗", COLORS["danger"]
            else:
                prefix, color = "○", COLORS["muted"]

            row = ctk.CTkLabel(
                self,
                text=f"{prefix}  {label}",
                font=FONTS["body"],
                text_color=color,
                anchor="w",
            )
            row.pack(fill="x", pady=3)
            self._rows.append(row)
