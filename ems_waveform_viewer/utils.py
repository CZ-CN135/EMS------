# -*- coding: utf-8 -*-
import sys
import os
import re
from constants import _CHECKED_INT, _UNCHECKED_INT

def resource_path(relative_path: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, relative_path)

def _check_state_int(state) -> int:
    if state is None:
        return _UNCHECKED_INT
    v = getattr(state, 'value', None)
    if v is not None:
        try:
            return int(v)
        except (TypeError, ValueError):
            pass
    try:
        return int(state)
    except (TypeError, ValueError):
        pass
    s = str(state)
    if 'Checked' in s and 'Unchecked' not in s:
        return _CHECKED_INT
    return _UNCHECKED_INT

def _is_checked_state(state) -> bool:
    return _check_state_int(state) == _CHECKED_INT

def short_name(col: str) -> str:
    return re.sub(r"\s*[（(]设备名称[:：][^)）]*[)）]\s*$", "", col).strip()

def rgb_to_excel_color(r: int, g: int, b: int) -> int:
    return (b << 16) | (g << 8) | r