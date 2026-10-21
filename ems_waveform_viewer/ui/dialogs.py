# -*- coding: utf-8 -*-
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableView, 
                               QAbstractItemView, QCheckBox, QGroupBox, QScrollArea, QWidget, QRadioButton, 
                               QButtonGroup, QDialogButtonBox, QTableWidget, QTableWidgetItem)
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtCore import Qt
from ems_waveform_viewer.ui.models import PandasModel

class TableSearchDialog(QDialog):
    def __init__(self, table_view: QTableView, model: PandasModel, parent=None):
        super().__init__(parent)
        self.setWindowTitle("查找和替换")
        self.resize(720, 420)
        self.table_view = table_view
        self.model = model
        self.matches = []
        self.current_idx = -1
        self._cached_keyword = None

        top = QHBoxLayout()
        top.addWidget(QLabel("查找内容(N):"))
        self.edt_find = QLineEdit()
        self.edt_find.setPlaceholderText("输入要查找的内容…")
        self.edt_find.returnPressed.connect(self.find_next)
        top.addWidget(self.edt_find, stretch=1)

        btn_layout = QHBoxLayout()
        self.btn_find_all = QPushButton("查找全部(I)")
        self.btn_find_next = QPushButton("查找下一个(F)")
        self.btn_find_prev = QPushButton("查找上一个")
        self.btn_close = QPushButton("关闭")
        self.btn_find_all.clicked.connect(self.find_all)
        self.btn_find_next.clicked.connect(self.find_next)
        self.btn_find_prev.clicked.connect(self.find_prev)
        self.btn_close.clicked.connect(self.close)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_find_all)
        btn_layout.addWidget(self.btn_find_next)
        btn_layout.addWidget(self.btn_find_prev)
        btn_layout.addWidget(self.btn_close)

        self.result_model = QStandardItemModel()
        self.result_model.setHorizontalHeaderLabels(["行号", "工作表/列名", "单元格", "值"])
        self.result_table = QTableView()
        self.result_table.setModel(self.result_model)
        self.result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.setColumnWidth(0, 60)
        self.result_table.setColumnWidth(1, 220)
        self.result_table.setColumnWidth(2, 80)
        self.result_table.doubleClicked.connect(self.goto_match)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color:#666; padding:2px;")

        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addLayout(btn_layout)
        root.addWidget(self.result_table, stretch=1)
        root.addWidget(self.lbl_status)

    def _collect_matches(self):
        keyword = self.edt_find.text().strip()
        if not keyword: return []
        keyword = keyword.lower()
        rows, cols = self.model.rowCount(), self.model.columnCount()
        matches = []
        for r in range(rows):
            for c in range(cols):
                idx = self.model.index(r, c)
                val = str(self.model.data(idx, Qt.DisplayRole))
                if keyword in val.lower(): matches.append((r, c))
        return matches

    def find_all(self):
        keyword = self.edt_find.text().strip()
        if not keyword: return
        self.result_model.removeRows(0, self.result_model.rowCount())
        self.matches = self._collect_matches()
        self.current_idx = -1
        self._cached_keyword = keyword
        if not self.matches:
            self.lbl_status.setText(f"未找到匹配项：“{keyword}”")
            return
        headers = self.model._headers
        for r, c in self.matches:
            row_num = str(r + 1)
            col_name = headers[c] if c < len(headers) else f"列{c}"
            cell_name = f"{chr(ord('A') + c)}{r + 1}" if c < 26 else f"列{c + 1}行{r + 1}"
            idx = self.model.index(r, c)
            value = str(self.model.data(idx, Qt.DisplayRole))
            items = [QStandardItem(row_num), QStandardItem(col_name), QStandardItem(cell_name), QStandardItem(value)]
            self.result_model.appendRow(items)
        self.lbl_status.setText(f"找到 {len(self.matches)} 个匹配项")

    def find_next(self):
        keyword = self.edt_find.text().strip()
        if not keyword: return
        if not self.matches or self._cached_keyword != keyword:
            self.matches = self._collect_matches()
            self.current_idx = -1
            self._cached_keyword = keyword
            self.find_all()
            if not self.matches: return
        self.current_idx = (self.current_idx + 1) % len(self.matches)
        self._goto_current()

    def find_prev(self):
        keyword = self.edt_find.text().strip()
        if not keyword: return
        if not self.matches or self._cached_keyword != keyword:
            self.matches = self._collect_matches()
            self.current_idx = -1
            self._cached_keyword = keyword
            self.find_all()
            if not self.matches: return
        self.current_idx = (self.current_idx - 1) % len(self.matches)
        self._goto_current()

    def _goto_current(self):
        r, c = self.matches[self.current_idx]
        idx = self.model.index(r, c)
        self.table_view.selectRow(r)
        self.table_view.scrollTo(idx)
        self.result_table.selectRow(self.current_idx)
        self.result_table.scrollTo(self.result_model.index(self.current_idx, 0))
        self.lbl_status.setText(f"第 {self.current_idx + 1} / {len(self.matches)} 项")

    def goto_match(self, index):
        row = index.row()
        if 0 <= row < len(self.matches):
            self.current_idx = row
            self._goto_current()


class OpenSourceDialog(QDialog):
    def __init__(self, parent, file_name: str, time_str: str, target_desc: str, curves, best_col: str = None):
        super().__init__(parent)
        self.setWindowTitle("打开原始文件")
        self.setMinimumWidth(560)
        self.setMinimumHeight(620)
        self._checkboxes, self._radios = [], []
        self._radio_group = QButtonGroup(self)
        self._radio_group.setExclusive(True)

        info = QLabel(f"<b>是否打开原始文件并定位到该点？</b><br><br>文件：{file_name}<br>录波时间：{time_str}<br>定位：{target_desc}")
        info.setWordWrap(True)

        cut_box = QGroupBox("① 剪切到「录波时间」列之后的测点（可多选）")
        cut_layout = QVBoxLayout(cut_box)
        bulk_row = QHBoxLayout()
        self.btn_check_all = QPushButton("全选")
        self.btn_uncheck_all = QPushButton("全部取消")
        self.btn_check_all.clicked.connect(self._check_all)
        self.btn_uncheck_all.clicked.connect(self._uncheck_all)
        bulk_row.addWidget(self.btn_check_all)
        bulk_row.addWidget(self.btn_uncheck_all)
        bulk_row.addStretch(1)
        cut_layout.addLayout(bulk_row)

        cut_inner = QWidget()
        cut_inner_layout = QVBoxLayout(cut_inner)
        cut_inner_layout.setContentsMargins(4, 4, 4, 4)
        cut_inner_layout.setSpacing(2)
        for disp, col in curves:
            cb = QCheckBox(disp)
            cb.setToolTip(col)
            cb.setChecked(col == best_col)
            cut_inner_layout.addWidget(cb)
            self._checkboxes.append((cb, disp, col))
        cut_inner_layout.addStretch(1)

        cut_scroll = QScrollArea()
        cut_scroll.setWidgetResizable(True)
        cut_scroll.setWidget(cut_inner)
        cut_scroll.setMinimumHeight(180)
        cut_layout.addWidget(cut_scroll, stretch=1)

        locate_box = QGroupBox("② 定位到哪一列（单选）")
        locate_layout = QVBoxLayout(locate_box)
        locate_inner = QWidget()
        locate_inner_layout = QVBoxLayout(locate_inner)
        locate_inner_layout.setContentsMargins(4, 4, 4, 4)
        locate_inner_layout.setSpacing(2)
        for i, (disp, col) in enumerate(curves):
            rb = QRadioButton(disp)
            rb.setToolTip(col)
            if (best_col is not None and col == best_col) or (best_col is None and i == 0):
                rb.setChecked(True)
            self._radio_group.addButton(rb, i)
            locate_inner_layout.addWidget(rb)
            self._radios.append((rb, disp, col))
        locate_inner_layout.addStretch(1)

        locate_scroll = QScrollArea()
        locate_scroll.setWidgetResizable(True)
        locate_scroll.setWidget(locate_inner)
        locate_scroll.setMinimumHeight(180)
        locate_layout.addWidget(locate_scroll, stretch=1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("确定")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addWidget(info)
        root.addWidget(cut_box, stretch=1)
        root.addWidget(locate_box, stretch=1)
        root.addWidget(btns)

    def _check_all(self):
        for cb, _disp, _col in self._checkboxes: cb.setChecked(True)

    def _uncheck_all(self):
        for cb, _disp, _col in self._checkboxes: cb.setChecked(False)

    def selected_columns(self):
        return [col for cb, _disp, col in self._checkboxes if cb.isChecked()]

    def target_column(self):
        for rb, _disp, col in self._radios:
            if rb.isChecked(): return col
        return None


class StatsDialog(QDialog):
    """基础统计（转置版）：每个测点为一列，指标为行。"""
    def __init__(self, parent, col_names, metric_rows, t_start, t_end):
        super().__init__(parent)
        self.setWindowTitle("数据统计")
        self.resize(1100, 480)

        info = QLabel(f"<b>统计范围：</b>{t_start} ～ {t_end}<br>共 <b>{len(col_names)}</b> 个测点"
                      f"<br><span style='color:#666;'>每个测点为一列；指标行为：最小值 / 最大值 / 平均值 / 标准差 / 峰值时刻 / 谷值时刻 / 样本数。可点击表头排序。</span>")
        info.setWordWrap(True)

        table = QTableWidget()
        headers = ["指标"] + list(col_names)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(metric_rows))
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(False)

        for i, (name, values) in enumerate(metric_rows):
            item = QTableWidgetItem(name)
            item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            table.setItem(i, 0, item)
            for j, v in enumerate(values):
                it = QTableWidgetItem(str(v))
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, j + 1, it)

        table.horizontalHeader().setStretchLastSection(False)
        table.setColumnWidth(0, 100)
        for j in range(1, len(headers)): table.setColumnWidth(j, 180)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.button(QDialogButtonBox.Close).setText("关闭")
        btns.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addWidget(info)
        root.addWidget(table, stretch=1)
        root.addWidget(btns)


class OscillationDialog(QDialog):
    """振荡分析（转置版）：每个测点为一列，指标为行。"""
    def __init__(self, parent, col_names, metric_rows, t_start, t_end):
        super().__init__(parent)
        self.setWindowTitle("振荡分析")
        self.resize(1500, 560)

        info = QLabel(f"<b>分析范围：</b>{t_start} ～ {t_end}<br>共 <b>{len(col_names)}</b> 个测点（每个测点为一列）"
                      f"<br><span style='color:#666;'>主频/主周期：去均值 FFT 主峰；典型半周期：相邻两次穿越均值线间隔的中位数；"
                      f"自相关周期：自相关第一个显著峰的滞后；峰值间隔：相邻局部极大值间隔的中位数；"
                      f"变异系数 CV = 标准差 / 中位数，越小越规则（<0.3 视为有规则周期）。</span>")
        info.setWordWrap(True)

        table = QTableWidget()
        headers = ["指标"] + list(col_names)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(metric_rows))
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(False)

        for i, (name, values) in enumerate(metric_rows):
            item = QTableWidgetItem(name)
            item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            table.setItem(i, 0, item)
            for j, v in enumerate(values):
                it = QTableWidgetItem(str(v))
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, j + 1, it)

        table.horizontalHeader().setStretchLastSection(False)
        table.setColumnWidth(0, 140)
        for j in range(1, len(headers)): table.setColumnWidth(j, 160)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.button(QDialogButtonBox.Close).setText("关闭")
        btns.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addWidget(info)
        root.addWidget(table, stretch=1)
        root.addWidget(btns)