# -*- coding: utf-8 -*-

PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f",
    "#003f5c", "#ffa600", "#58508d", "#ff6361", "#2f4b7c",
]

DARK_PALETTE = [
    "#5ba7e3", "#ff9f4a", "#6ccf6c", "#ff6b6b", "#b07de0",
    "#c08c7d", "#f08bc8", "#4fd3e0", "#e0e04a", "#a8a8a8",
    "#5a8fbe", "#ffbe4a", "#8a82b5", "#ff8a8a", "#5a7fb0",
]

THEMES = {
    "light": {
        "bg": "#ffffff",
        "fg": "#333333",
        "axis_pen": "#888888",
        "legend_text": "#222222",
        "tip_border": "#666666",
        "tip_fill": (25, 25, 25, 225),
        "palette": PALETTE,
        "vline": "#cc0000",
        "hline": "#cc0000",
        "bookmark": "#e67e22",
        "theme_action_text": "深色主题",
    },
    "dark": {
        "bg": "#1e1e1e",
        "fg": "#dddddd",
        "axis_pen": "#666666",
        "legend_text": "#dddddd",
        "tip_border": "#888888",
        "tip_fill": (50, 50, 50, 235),
        "palette": DARK_PALETTE,
        "vline": "#ff6666",
        "hline": "#ff6666",
        "bookmark": "#ffb84d",
        "theme_action_text": "浅色主题",
    },
}