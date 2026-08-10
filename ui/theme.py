"""
ui/theme.py — Visual tokens for BlockSync.

Minecraft-hosting look: deep forest greens, warm stone accents, dark slate.
Avoids generic purple gradients and cream/serif brochure aesthetics.
"""

from __future__ import annotations

COLORS = {
    "bg": "#1a1f1a",
    "panel": "#242b24",
    "panel_alt": "#2e362e",
    "border": "#3d4a3d",
    "text": "#e8efe6",
    "muted": "#9aab96",
    "accent": "#6fbf73",
    "accent_hover": "#85d089",
    "accent_dim": "#3f7a43",
    "warn": "#d4a017",
    "danger": "#c75c5c",
    "danger_hover": "#d97878",
    "ok": "#6fbf73",
    "offline": "#8a9488",
}

FONTS = {
    "brand": ("Segoe UI Semibold", 28),
    "title": ("Segoe UI Semibold", 20),
    "heading": ("Segoe UI Semibold", 16),
    "body": ("Segoe UI", 14),
    "small": ("Segoe UI", 12),
    "mono": ("Cascadia Mono", 13),
}

WINDOW = {
    "title": "BlockSync",
    "geometry": "480x640",
    "min_size": (420, 560),
}
