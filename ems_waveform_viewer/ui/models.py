# -*- coding: utf-8 -*-
import pandas as pd
from PySide6.QtCore import QAbstractTableModel, Qt

class PandasModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self._times = None
        self._vals = None
        self._headers = []

    def set_data(self, times, headers, vals):
        self.beginResetModel()
        self._times, self._headers, self._vals = times, headers, vals
        self.endResetModel()

    def rowCount(self, parent=None):
        return 0 if self._times is None else len(self._times)

    def columnCount(self, parent=None):
        return len(self._headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or self._times is None:
            return None
        r, c = index.row(), index.column()
        if role == Qt.DisplayRole:
            v = self._times[r] if c == 0 else self._vals[r, c - 1]
            if v is None: return ""
            try:
                if pd.isna(v): return ""
            except (TypeError, ValueError): pass
            return str(v)
        if role == Qt.TextAlignmentRole:
            if c == 0: return int(Qt.AlignLeft | Qt.AlignVCenter)
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._headers[section]
        if role == Qt.DisplayRole:
            return str(section + 1)
        return None