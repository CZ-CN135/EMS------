# -*- coding: utf-8 -*-

ICON_FILE = "竖曲线.png"

MAX_CURVES = 16
MAX_READOUT = 8
TIME_FMT = "%Y%m%d-%H:%M:%S.%f"

NAME_RE = __import__('re').compile(
    r"^([A-Za-z0-9]+)_\d{8}-\d{6}.*\.csv(\.(tar\.gz|zip))?$",
    __import__('re').IGNORECASE)

CSV_CACHE_LIMIT = 20
MERGED_CACHE_LIMIT = 8

AXIS_LEFT_COLOR = "#222222"
AXIS_RIGHT_COLOR = "#1f77b4"

DEFAULT_CHECKED_COUNT = 2
BOOKMARK_HIGHLIGHT_RATIO = 0.04
OSC_ENVELOPE_WIN = 31

_CHECKED_INT = 2
_UNCHECKED_INT = 0