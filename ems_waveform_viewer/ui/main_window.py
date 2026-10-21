# -*- coding: utf-8 -*-
import sys
import datetime
import io
import os
import shutil
import tarfile
import tempfile
import zipfile
import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import QDateTime, Qt, QTimer, QEvent, QSize
from PySide6.QtGui import QKeySequence, QShortcut, QColor, QIcon, QAction
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, 
                               QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSplitter, QTableView, 
                               QTabWidget, QVBoxLayout, QWidget, QDateTimeEdit, QGroupBox, QStyle, QToolBar, 
                               QHeaderView, QDialog)  # <-- 这里加了 QHeaderView 和 QDialog

from ..constants import (ICON_FILE, MAX_CURVES, MAX_READOUT, NAME_RE, CSV_CACHE_LIMIT, MERGED_CACHE_LIMIT,
                         AXIS_LEFT_COLOR, AXIS_RIGHT_COLOR, DEFAULT_CHECKED_COUNT, BOOKMARK_HIGHLIGHT_RATIO)
from ..theme import THEMES
from ..utils import resource_path, _is_checked_state, short_name
from ..data_loader import load_waveform, WaveformFile, merge_waveforms
from ..analysis import analyze_oscillation
from ..excel_export import ExcelManager
from .models import PandasModel
from .delegates import CheckBoxDelegate
from .dialogs import TableSearchDialog, OpenSourceDialog, StatsDialog, OscillationDialog


class WaveformViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EMS 录波曲线查看器")
        self.resize(1600, 960)

        icon_path = resource_path(ICON_FILE)
        if os.path.exists(icon_path): self.setWindowIcon(QIcon(icon_path))

        self._theme_name = "light"
        self._bookmarks, self._bookmark_lines, self._bookmark_tips, self._bookmark_graphics = [], [], [], []
        self._highlight_bookmark_idx = None
        self._last_mouse_xy = None
        self._last_tip_anchor = (0, 0)

        self._combined = None
        self._curves = []
        self._first_load_done = False
        self._x_view, self._mask_idx, self._last_idx = None, None, -1
        self._legend_visible = True
        self._col_axis = {}
        self._loaded_paths = []
        
        self.excel_manager = ExcelManager()

        self._tar_path, self._archive_kind = None, "tar"
        self.type_index, self._type_checks, self._tmpdir = {}, {}, None
        self._csv_files, self._csv_cache, self._cache_order = [], {}, []
        self._combined_cache, self._combined_key, self._current_types = {}, None, frozenset()
        self._search_dialog = None

        self._build_toolbar()

        self.lbl_file = QLabel("未加载文件")
        self.lbl_file.setWordWrap(True)
        self.grp_type = QGroupBox("录波类型（可多选）")
        self.type_layout = QVBoxLayout(self.grp_type)
        self.lbl_files = QLabel("录波文件（可多选）：")
        self.list_files = QListWidget()
        self.list_files.itemChanged.connect(self.schedule_load_csvs)
        
        self.edt_search = QLineEdit()
        self.edt_search.setPlaceholderText("搜索测点，如：有功 / SOC / 光伏 / 频率")
        self.edt_search.textChanged.connect(self.apply_filter)
        self.edt_search.returnPressed.connect(self.on_search_clicked)
        
        self.btn_search = QPushButton("搜索")
        self.btn_search.clicked.connect(self.on_search_clicked)
        self.btn_clear_search = QPushButton("清空")
        self.btn_clear_search.clicked.connect(self.on_clear_search)
        
        self.list_cols = QListWidget()
        self.list_cols.itemChanged.connect(self.schedule_redraw)
        self.list_cols.itemDoubleClicked.connect(self._on_col_double_clicked)
        self._col_delegate = CheckBoxDelegate(self.list_cols)
        self.list_cols.setItemDelegate(self._col_delegate)
        self.list_cols.setMouseTracking(True)
        
        self.btn_all = QPushButton("全选(筛选结果)")
        self.btn_none = QPushButton("全部取消")
        self.btn_all.clicked.connect(lambda: self.check_filtered(Qt.Checked))
        self.btn_none.clicked.connect(lambda: self.check_filtered(Qt.Unchecked))
        self.btn_axis_toggle = QPushButton("切换选中项的轴（左↔右）")
        self.btn_axis_toggle.clicked.connect(self._toggle_selected_axis)

        self.dt_start, self.dt_end = QDateTimeEdit(), QDateTimeEdit()
        for edt in (self.dt_start, self.dt_end):
            edt.setDisplayFormat("MM-dd HH:mm:ss")
            edt.setCalendarPopup(True)
            edt.setKeyboardTracking(False)
            edt.dateTimeChanged.connect(self.schedule_redraw)
        quick = QHBoxLayout()
        for text, minutes in (("全部", 0), ("最近1分钟", 1), ("最近5分钟", 5), ("最近15分钟", 15)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, m=minutes: self.set_quick_range(m))
            quick.addWidget(b)
            
        time_box = QGroupBox("时间范围（横坐标）")
        tl = QVBoxLayout(time_box)
        tl.addWidget(QLabel("开始："))
        tl.addWidget(self.dt_start)
        tl.addWidget(QLabel("结束："))
        tl.addWidget(self.dt_end)
        tl.addLayout(quick)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(self.lbl_file)
        ll.addWidget(self.grp_type)
        ll.addWidget(self.lbl_files)
        ll.addWidget(self.list_files, stretch=1)
        ll.addWidget(time_box)
        ll.addWidget(QLabel("测点选择（纵坐标，可多选；双击可切换左右轴）："))
        search_row = QHBoxLayout()
        search_row.addWidget(self.edt_search, stretch=1)
        search_row.addWidget(self.btn_search)
        search_row.addWidget(self.btn_clear_search)
        ll.addLayout(search_row)
        ll.addWidget(self.list_cols, stretch=2)
        row = QHBoxLayout()
        row.addWidget(self.btn_all)
        row.addWidget(self.btn_none)
        ll.addLayout(row)
        ll.addWidget(self.btn_axis_toggle)
        self._tar_widgets_visible(False)

        axis = pg.DateAxisItem(orientation="bottom", utcOffset=0)
        plot_item = pg.PlotItem(axisItems={"bottom": axis})
        plot_item.showAxis('right')
        for an in ['right', 'left', 'bottom']:
            plot_item.getAxis(an).setTextPen("#333333")
            plot_item.getAxis(an).setPen("#888888")

        self.plot = pg.PlotWidget(plotItem=plot_item, background="#ffffff")
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.addLegend(offset=(10, 10), labelTextColor="#222222")
        self.legend = self.plot.plotItem.legend

        self.plot_item2 = pg.ViewBox()
        plot_item.scene().addItem(self.plot_item2)
        plot_item.getAxis('right').linkToView(self.plot_item2)
        self.plot_item2.setXLink(plot_item.vb)

        def _update_right_view():
            self.plot_item2.setGeometry(plot_item.vb.sceneBoundingRect())
            self.plot_item2.linkedViewChanged(plot_item.vb, self.plot_item2.XAxis)

        plot_item.vb.sigResized.connect(_update_right_view)
        self._update_right_view = _update_right_view
        _update_right_view()

        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#cc0000", width=1, style=Qt.DashLine))
        self.hline = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen("#cc0000", width=1, style=Qt.DashLine))
        for ln in (self.vline, self.hline):
            ln.setVisible(False)
            self.plot.addItem(ln, ignoreBounds=True)

        self.tooltip = pg.TextItem(html="", anchor=(0, 0), border=pg.mkPen("#666666", width=1), fill=pg.mkBrush(25, 25, 25, 225))
        self.tooltip.setZValue(100)
        self.tooltip.setVisible(False)
        self.plot.addItem(self.tooltip, ignoreBounds=True)

        self.plot.scene().sigMouseMoved.connect(self.on_mouse_moved)
        self.plot.scene().sigMouseClicked.connect(self.on_plot_clicked)

        self.lbl_readout = QLabel("提示：左键拖动平移，滚轮缩放；双击曲线定位；按 B 添加书签；Delete 删除最近书签。")
        self.lbl_readout.setStyleSheet("color:#333; padding:4px;")

        tab_plot = QWidget()
        pl = QVBoxLayout(tab_plot)
        pl.addWidget(self.plot, stretch=1)
        pl.addWidget(self.lbl_readout)

        self.table_model = PandasModel()
        self.table = QTableView()
        self.table.setModel(self.table_model)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(150)

        self.tabs = QTabWidget()
        self.tabs.addTab(tab_plot, "曲线图")
        self.tabs.addTab(self.table, "原始数据")

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.tabs)
        splitter.setSizes([380, 1000])
        self.setCentralWidget(splitter)

        self._redraw_timer = QTimer(self, singleShot=True, interval=200)
        self._redraw_timer.timeout.connect(self.redraw)
        self._load_timer = QTimer(self, singleShot=True, interval=250)
        self._load_timer.timeout.connect(self.load_selected_csvs)

        self._setup_shortcuts()
        self._apply_theme()

        if len(sys.argv) > 1: self.load(sys.argv[1])

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self.open_search_dialog)
        QShortcut(QKeySequence("Ctrl+O"), self).activated.connect(self.open_file)
        QShortcut(QKeySequence("B"), self).activated.connect(self.add_bookmark)
        QShortcut(QKeySequence("Ctrl+I"), self).activated.connect(self.show_stats)
        QShortcut(QKeySequence("Ctrl+Shift+I"), self).activated.connect(self.show_oscillation)
        QShortcut(QKeySequence("Delete"), self).activated.connect(self.delete_nearest_bookmark)
        QShortcut(QKeySequence("Shift+Delete"), self).activated.connect(self.clear_bookmarks)

    def _build_toolbar(self):
        bar = QToolBar("主工具栏", self)
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        bar.setIconSize(QSize(10, 10))
        bar.setStyleSheet("""
            QToolBar { padding: 0px 2px; spacing: 2px; border: 0px; min-height: 12px; max-height: 22px; }
            QToolButton { padding: 0px 6px; margin: 0px; min-height: 10px; max-height: 20px; font-size: 12px; }
            QToolButton:hover { background: #e8f0fa; border-radius: 3px; }
        """)
        self.addToolBar(Qt.TopToolBarArea, bar)
        self._toolbar = bar

        actions = [
            ("打开文件…", QStyle.SP_DialogOpenButton, self.open_file, "打开录波文件（Ctrl+O）", True),
            ("导出图片 (PNG)…", QStyle.SP_DialogSaveButton, self.export_png, "导出PNG图片", False),
            ("导出数据 (CSV)…", QStyle.SP_FileDialogDetailedView, self.export_csv, "导出CSV数据", False),
            ("添加书签 (B)", QStyle.SP_DialogApplyButton, self.add_bookmark, "在当前光标处添加书签", True),
            ("删除最近书签 (Del)", QStyle.SP_DialogDiscardButton, self.delete_nearest_bookmark, "删除最近的一条书签", False),
            ("清空书签 (Shift+Del)", QStyle.SP_DialogResetButton, self.clear_bookmarks, "清除所有书签", False),
            ("数据统计…", QStyle.SP_FileDialogContentsView, self.show_stats, "统计选中测点的数据（Ctrl+I）", True),
            ("振荡分析…", QStyle.SP_MediaPlay, self.show_oscillation, "分析振荡频率和幅度（Ctrl+Shift+I）", False),
            ("深色主题", QStyle.SP_ComputerIcon, self._toggle_theme, "切换深色/浅色主题", True),
            ("隐藏图例", QStyle.SP_FileDialogInfoView, self._toggle_legend, "显示/隐藏图例", False)
        ]

        for text, icon_enum, slot, tip, sep_before in actions:
            if sep_before: bar.addSeparator()
            act = QAction(text, self)
            act.setStatusTip(tip)
            try: act.setIcon(self.style().standardIcon(icon_enum))
            except Exception: pass
            act.triggered.connect(slot)
            bar.addAction(act)
            if text == "深色主题": self.act_theme = act
            elif text == "隐藏图例": self.act_legend_toggle = act

    def _theme(self): return THEMES.get(self._theme_name, THEMES["light"])

    def _apply_theme(self):
        th = self._theme()
        try: self.plot.setBackground(th["bg"])
        except Exception: pass
        for ax_name in ("left", "bottom", "right"):
            try:
                ax = self.plot.plotItem.getAxis(ax_name)
                ax.setTextPen(th["fg"])
                ax.setPen(th["axis_pen"])
            except Exception: pass
        try: self.legend.setLabelTextColor(th["legend_text"])
        except Exception: pass
        try: self.tooltip.setOpts(border=pg.mkPen(th["tip_border"], width=1), fill=pg.mkBrush(*th["tip_fill"]))
        except Exception: pass
        try:
            self.vline.setPen(pg.mkPen(th["vline"], width=1, style=Qt.DashLine))
            self.hline.setPen(pg.mkPen(th["hline"], width=1, style=Qt.DashLine))
        except Exception: pass
        try: self.act_theme.setText(th["theme_action_text"])
        except Exception: pass
        try: self.lbl_readout.setStyleSheet(f"color:{th['fg']}; padding:4px;")
        except Exception: pass
        self.redraw()

    def _toggle_theme(self):
        self._theme_name = "dark" if self._theme_name == "light" else "light"
        self._apply_theme()
        self.lbl_readout.setText(f"已切换到{'深色' if self._theme_name == 'dark' else '浅色'}主题。")

    def _build_readout_html(self, snap_x: float) -> str:
        if self._x_view is None or len(self._x_view) == 0: return ""
        idx = self._nearest_index(self._x_view, snap_x)
        secs = int(snap_x)
        ms = int(round((snap_x - secs) * 1000))
        if ms == 1000: secs, ms = secs + 1, 0
        t = datetime.datetime.fromtimestamp(secs, datetime.timezone.utc)
        rows = [f"<tr><td colspan='2' style='color:#ffffff; font-size:13px; font-weight:bold; padding-bottom:3px;'>时间 {t:%H:%M:%S}.{ms:03d}</td></tr>"]
        palette = self._theme()["palette"]
        for i, (disp, _yv, rawv, _col, axis, _item) in enumerate(self._curves[:MAX_READOUT]):
            s = rawv[idx]
            if s is None: continue
            try:
                if pd.isna(s): continue
            except (TypeError, ValueError): pass
            text = str(s)
            if text == "": continue
            color = palette[i % len(palette)]
            name = disp + (" (右)" if axis == 'right' else "")
            rows.append(f"<tr><td style='color:#cccccc; padding-right:14px;'><span style='color:{color};'>●</span> {name}</td>"
                        f"<td align='right' style='color:#ffffff; font-weight:bold;'>{text}</td></tr>")
        if len(self._curves) > MAX_READOUT:
            rows.append(f"<tr><td colspan='2' style='color:#888888;'>…（共 {len(self._curves)} 条）</td></tr>")
        return "<table cellspacing='0' cellpadding='1'>" + "".join(rows) + "</table>"

    def add_bookmark(self):
        if self._combined is None: return
        if self.tooltip.isVisible() and self.vline.isVisible() and self._last_mouse_xy is not None:
            ts, y_data = float(self.vline.value()), float(self._last_mouse_xy[1])
            ax, ay = self._last_tip_anchor
            try: html = self.tooltip.toHtml() or ""
            except Exception: html = ""
            if not html: html = self._build_readout_html(ts)
        else:
            try:
                vr = self.plot.plotItem.vb.viewRect()
                ts, y_data = float(vr.center().x()), float(vr.center().y())
            except Exception:
                ts, y_data = (float(self._x_view[0]) if self._x_view is not None and len(self._x_view) > 0 else 0.0), 0.0
            ax, ay = 0, 0
            html = self._build_readout_html(ts)

        secs = int(ts)
        ms = int(round((ts - secs) * 1000))
        if ms == 1000: secs, ms = secs + 1, 0
        t = datetime.datetime.fromtimestamp(secs, datetime.timezone.utc)
        label = f"{t:%H:%M:%S}.{ms:03d}"

        self._bookmarks.append((ts, y_data, ax, ay, label, html))
        self._draw_bookmarks()
        self.lbl_readout.setText(f"已添加书签：{label}（共 {len(self._bookmarks)} 个）；按 Delete 可删除最近的一条。")

    def delete_nearest_bookmark(self):
        if not self._bookmarks: return
        idx = self._highlight_bookmark_idx
        if idx is None or idx < 0 or idx >= len(self._bookmarks): idx = len(self._bookmarks) - 1
        ts, _y_data, _ax, _ay, label, _html = self._bookmarks.pop(idx)
        self._highlight_bookmark_idx = None
        self._draw_bookmarks()
        self.lbl_readout.setText(f"已删除书签：{label}（剩余 {len(self._bookmarks)} 个）")

    def clear_bookmarks(self):
        if not self._bookmarks: return
        n = len(self._bookmarks)
        self._bookmarks = []
        self._highlight_bookmark_idx = None
        self._draw_bookmarks()
        self.lbl_readout.setText(f"已清除 {n} 个书签。")

    def _draw_bookmarks(self):
        for ln in self._bookmark_lines:
            try: self.plot.removeItem(ln)
            except Exception: pass
        self._bookmark_lines = []
        for tip in self._bookmark_tips:
            try: self.plot.removeItem(tip)
            except Exception: pass
        self._bookmark_tips = []
        self._bookmark_graphics = []
        if not self._bookmarks: return

        th = self._theme()
        pen = pg.mkPen(th["bookmark"], width=1, style=Qt.DashLine)
        for ts, y_data, ax, ay, _label, html in self._bookmarks:
            vline = pg.InfiniteLine(angle=90, pos=ts, movable=False, pen=pen)
            hline = pg.InfiniteLine(angle=0, pos=y_data, movable=False, pen=pen)
            try:
                self.plot.addItem(vline, ignoreBounds=True)
                self.plot.addItem(hline, ignoreBounds=True)
                self._bookmark_lines.extend([vline, hline])
            except Exception: pass

            tip = None
            if html:
                tip = pg.TextItem(html=html, anchor=(ax, ay), border=pg.mkPen(th["tip_border"], width=1), fill=pg.mkBrush(*th["tip_fill"]))
                tip.setZValue(90)
                tip.setPos(ts, y_data)
                try:
                    self.plot.addItem(tip, ignoreBounds=True)
                    self._bookmark_tips.append(tip)
                except Exception: tip = None
            self._bookmark_graphics.append((vline, hline, tip))
        self._apply_bookmark_highlight()

    def _apply_bookmark_highlight(self):
        if not self._bookmark_graphics: return
        th = self._theme()
        normal_pen = pg.mkPen(th["bookmark"], width=1, style=Qt.DashLine)
        highlight_pen = pg.mkPen(th["bookmark"], width=3, style=Qt.DashLine)
        for i, (vline, hline, _tip) in enumerate(self._bookmark_graphics):
            pen = highlight_pen if i == self._highlight_bookmark_idx else normal_pen
            try:
                if vline is not None: vline.setPen(pen)
                if hline is not None: hline.setPen(pen)
            except Exception: pass

    def _update_bookmark_highlight_from_x(self, snap_x: float):
        new_idx = None
        if self._bookmarks:
            try: span = float(self.plot.plotItem.vb.viewRect().width())
            except Exception: span = 0.0
            if span > 0:
                threshold = span * BOOKMARK_HIGHLIGHT_RATIO
                best_i, best_d = None, None
                for i, bk in enumerate(self._bookmarks):
                    d = abs(float(bk[0]) - snap_x)
                    if best_d is None or d < best_d: best_d, best_i = d, i
                if best_d is not None and best_d <= threshold: new_idx = best_i
        if new_idx != self._highlight_bookmark_idx:
            self._highlight_bookmark_idx = new_idx
            self._apply_bookmark_highlight()

    def show_stats(self):
        if self._combined is None or self._mask_idx is None: return
        cols = self.selected_columns()
        if not cols: return
        times_raw = self._combined.raw_time[self._mask_idx]

        col_names, col_stats = [], []
        for disp, col, _axis in cols:
            y_full = self._combined.get_num(col)
            if y_full is None: continue
            ys = y_full[self._mask_idx]
            valid = np.isfinite(ys)
            if valid.sum() == 0: continue
            yv, vidx = ys[valid], np.nonzero(valid)[0]

            col_names.append(disp)
            col_stats.append({
                "min": f"{float(np.nanmin(yv)):.6g}", "max": f"{float(np.nanmax(yv)):.6g}",
                "mean": f"{float(np.nanmean(yv)):.6g}", "std": f"{float(np.nanstd(yv)):.6g}",
                "t_max": str(times_raw[vidx[int(np.nanargmax(yv))]]),
                "t_min": str(times_raw[vidx[int(np.nanargmin(yv))]]), "n": str(int(valid.sum()))
            })
        
        try:
            pairs = sorted(zip(col_names, col_stats), key=lambda p: str(p[0]))
            col_names, col_stats = [p[0] for p in pairs], [p[1] for p in pairs]
        except Exception: pass

        def _collect(k): return ["—" if st is None else st[k] for st in col_stats]
        metric_rows = [("最小值", _collect("min")), ("最大值", _collect("max")), ("平均值", _collect("mean")),
                       ("标准差", _collect("std")), ("峰值时刻", _collect("t_max")), ("谷值时刻", _collect("t_min")), ("样本数", _collect("n"))]

        t_start, t_end = str(times_raw[0]) if len(times_raw) > 0 else "—", str(times_raw[-1]) if len(times_raw) > 0 else "—"
        StatsDialog(self, col_names, metric_rows, t_start, t_end).exec()

    def show_oscillation(self):
        if self._combined is None or self._mask_idx is None: return
        cols = self.selected_columns()
        if not cols: return
        times_raw, t_axis = self._combined.raw_time[self._mask_idx], self._combined.x_ts[self._mask_idx]

        def _fmt_ms(s): return f"{s * 1000.0:.4g}" if s is not None else "—"
        col_names, col_stats = [], []

        for disp, col, _axis in cols:
            y_full = self._combined.get_num(col)
            if y_full is None: continue
            stat = analyze_oscillation(t_axis, y_full[self._mask_idx])
            if stat is None: continue

            f_fft = stat["f_fft"]
            period_ms = (1000.0 / f_fft) if (f_fft and f_fft > 0) else None
            
            col_names.append(disp)
            col_stats.append({
                "mean": f"{stat['mean']:.6g}", "rms": f"{stat['rms']:.6g}", "amp_half": f"{stat['amp_half']:.6g}",
                "amp_pk2pk": f"{stat['amp_pk2pk']:.6g}", "f_fft": f"{f_fft:.6g}" if f_fft is not None else "—",
                "period_ms": f"{period_ms:.4g}" if period_ms is not None else "—",
                "f_zero": f"{stat['f_zero']:.6g}" if stat['f_zero'] is not None else "—",
                "hp_med": _fmt_ms(stat["half_period_median_s"]), "hp_std": _fmt_ms(stat["half_period_std_s"]),
                "ac_period": _fmt_ms(stat["ac_period_s"]), "ac_peak": f"{stat['ac_peak_val']:.4g}" if stat["ac_peak_val"] is not None else "—",
                "pk_period": _fmt_ms(stat["pk_period_s"]), "pk_cv": f"{stat['pk_period_cv']:.3g}" if stat["pk_period_cv"] is not None else "—",
                "n_peaks": str(stat["n_peaks"]), "n_valid": str(stat["n_valid"])
            })

        try:
            pairs = sorted(zip(col_names, col_stats), key=lambda p: str(p[0]))
            col_names, col_stats = [p[0] for p in pairs], [p[1] for p in pairs]
        except Exception: pass

        def _collect(k): return ["—" if st is None else st[k] for st in col_stats]
        metric_rows = [("中心值", _collect("mean")), ("RMS", _collect("rms")), ("振幅 ±", _collect("amp_half")), ("峰峰值", _collect("amp_pk2pk")),
                       ("主频 (Hz)", _collect("f_fft")), ("主周期 (ms)", _collect("period_ms")), ("过零频率 (Hz)", _collect("f_zero")),
                       ("典型半周期 (ms)", _collect("hp_med")), ("半周期抖动 (ms)", _collect("hp_std")), ("自相关周期 (ms)", _collect("ac_period")),
                       ("自相关峰值", _collect("ac_peak")), ("峰值间隔 (ms)", _collect("pk_period")), ("峰值间隔 CV", _collect("pk_cv")),
                       ("峰值数", _collect("n_peaks")), ("有效点数", _collect("n_valid"))]

        t_start, t_end = str(times_raw[0]) if len(times_raw) > 0 else "—", str(times_raw[-1]) if len(times_raw) > 0 else "—"
        OscillationDialog(self, col_names, metric_rows, t_start, t_end).exec()

    def _refresh_col_axis_label(self, row: int):
        item = self.list_cols.item(row)
        if item is None: return
        col = item.data(Qt.UserRole)
        if col is None: return
        disp = short_name(col)
        axis = self._col_axis.get(col, 'left')
        label = disp + ("    [右]" if axis == 'right' else "    [左]")

        prev_blocked = self.list_cols.blockSignals(True)
        try:
            item.setText(label)
            item.setForeground(QColor(AXIS_RIGHT_COLOR if axis == 'right' else AXIS_LEFT_COLOR))
        finally: self.list_cols.blockSignals(prev_blocked)

    def _on_col_double_clicked(self, item):
        col = item.data(Qt.UserRole)
        if col is None: return
        cur = self._col_axis.get(col, 'left')
        self._col_axis[col] = 'right' if cur == 'left' else 'left'
        self._refresh_col_axis_label(self.list_cols.row(item))
        self.schedule_redraw()

    def _toggle_selected_axis(self):
        selected = self.list_cols.selectedItems()
        if not selected: return
        for item in selected:
            col = item.data(Qt.UserRole)
            if col is None: continue
            cur = self._col_axis.get(col, 'left')
            self._col_axis[col] = 'right' if cur == 'left' else 'left'
            self._refresh_col_axis_label(self.list_cols.row(item))
        self.schedule_redraw()

    def _toggle_legend(self):
        self._legend_visible = not self._legend_visible
        try: self.legend.setVisible(self._legend_visible)
        except Exception: pass
        if self._legend_visible:
            self.act_legend_toggle.setText("隐藏图例")
            self.act_legend_toggle.setStatusTip("隐藏曲线图例")
        else:
            self.act_legend_toggle.setText("显示图例")
            self.act_legend_toggle.setStatusTip("显示曲线图例")
        self.lbl_readout.setText(f"图例已{'显示' if self._legend_visible else '隐藏'}。")

    def export_png(self):
        if self._combined is None: return
        default_name = "waveform.png"
        if self._loaded_paths: default_name = f"{os.path.splitext(os.path.basename(self._loaded_paths[0]))[0]}.png"
        path, _ = QFileDialog.getSaveFileName(self, "导出图片", default_name, "PNG 图片 (*.png);;JPEG 图片 (*.jpg *.jpeg);;所有文件 (*)")
        if not path: return
        try:
            self.vline.setVisible(False)
            self.hline.setVisible(False)
            self.tooltip.setVisible(False)
            from pyqtgraph.exporters import ImageExporter
            exporter = ImageExporter(self.plot.plotItem)
            params = exporter.parameters()
            params["width"] = 1920
            try: params["antialias"] = True
            except Exception: pass
            exporter.export(path)
            self.lbl_readout.setText(f"已导出图片：{os.path.basename(path)}")
        except Exception as e: QMessageBox.warning(self, "导出失败", f"无法导出图片：\n{e}")

    def export_csv(self):
        if self._combined is None or self._mask_idx is None: return
        cols = self.selected_columns()
        if not cols: return

        default_name = "waveform.csv"
        if self._loaded_paths: default_name = f"{os.path.splitext(os.path.basename(self._loaded_paths[0]))[0]}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "导出数据", default_name, "CSV 文件 (*.csv);;所有文件 (*)")
        if not path: return
        if not path.lower().endswith(".csv"): path += ".csv"
        try:
            idx, combined = self._mask_idx, self._combined
            times = combined.raw_time[idx]
            data = {"录波时间": times}
            for disp, col, _axis in cols:
                raw_arr = combined.get_raw(col)
                data[disp] = [""] * len(idx) if raw_arr is None else raw_arr[idx]
            pd.DataFrame(data).to_csv(path, index=False, encoding="utf-8-sig")
            self.lbl_readout.setText(f"已导出数据：{os.path.basename(path)}")
        except Exception as e: QMessageBox.warning(self, "导出失败", f"无法导出数据：\n{e}")

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开录波文件", "", "录波文件 (*.tar *.zip *.csv *.tar.gz *.tgz *.csv.zip);;所有文件 (*)")
        if path: self.load(path)

    def load(self, path: str):
        lower = path.lower()
        if lower.endswith((".tar", ".tar.gz", ".tgz")): self.load_tar(path)
        elif lower.endswith(".zip"): self.load_zip(path)
        else: self.load_single_csv(path)

    def load_single_csv(self, path: str):
        try:
            df, t_col, t_parsed, orig_rows, col_pos = load_waveform(path)
            wf = WaveformFile(df, t_col, t_parsed, orig_rows, col_pos)
            combined = merge_waveforms([wf])
            self._cleanup_tmp()
            self._tar_path = None
            self._archive_kind = "tar"
            self._tar_widgets_visible(False)
            self._combined_key = None
            self._loaded_paths = [path]
            self._apply_combined(combined, [f"文件：{os.path.basename(path)}"])
        except Exception as e: QMessageBox.critical(self, "加载失败", f"无法读取文件：\n{e}")

    def load_tar(self, path: str):
        try:
            with tarfile.open(path, "r:*") as tf: members = [m.name for m in tf.getmembers() if m.isfile()]
            self._load_archive(path, members, "tar", "tar 包")
        except Exception as e: QMessageBox.critical(self, "加载失败", f"无法读取 tar 包：\n{e}")

    def load_zip(self, path: str):
        try:
            with zipfile.ZipFile(path, "r") as zf: members = [n for n in zf.namelist() if not n.endswith("/")]
            self._load_archive(path, members, "zip", "zip 包")
        except Exception as e: QMessageBox.critical(self, "加载失败", f"无法读取 zip 包：\n{e}")

    def _load_archive(self, path, members, kind, label):
        type_index = {}
        for name in members:
            m = NAME_RE.match(os.path.basename(name))
            if m: type_index.setdefault(m.group(1).upper(), []).append(name)
        if not type_index:
            QMessageBox.warning(self, "未识别到录波", f"{label}内未找到符合命名规则的录波文件。")
            return

        self._cleanup_tmp()
        self._tar_path, self._archive_kind, self.type_index = path, kind, type_index
        self._csv_cache.clear(); self._cache_order.clear(); self._combined_cache.clear()
        self._combined_key, self._current_types, self._combined, self._loaded_paths = None, frozenset(), None, []

        while self.type_layout.count():
            w = self.type_layout.takeAt(0).widget()
            if w: w.deleteLater()
        self._type_checks = {}
        for t in sorted(type_index):
            cb = QCheckBox(f"{t} 录波（{len(type_index[t])} 个文件）")
            cb.stateChanged.connect(self.on_type_changed)
            self.type_layout.addWidget(cb)
            self._type_checks[t] = cb

        self.list_files.clear()
        self._tar_widgets_visible(True)
        summary = "、".join(f"{t}×{len(v)}" for t, v in sorted(type_index.items()))
        self.lbl_file.setText(f"{label}：{os.path.basename(path)}\n识别到录波类型：{summary}\n请勾选录波类型。")

        if len(self._type_checks) == 1: next(iter(self._type_checks.values())).setChecked(True)

    def _tar_widgets_visible(self, flag: bool):
        for w in (self.grp_type, self.lbl_files, self.list_files): w.setVisible(flag)

    def on_type_changed(self):
        types = frozenset(t for t, cb in self._type_checks.items() if cb.isChecked())
        if types == self._current_types: return
        self._current_types = types

        self.list_files.blockSignals(True); self.list_files.clear(); self.list_files.blockSignals(False)
        self._csv_files = []
        if not types:
            self._combined_key = None
            self._apply_combined(None, ["未勾选录波类型"])
            return
        try: self._extract_types(types)
        except Exception as e:
            QMessageBox.critical(self, "解压失败", f"解压录波文件出错：\n{e}")
            return

        self.list_files.blockSignals(True); self.list_files.setUpdatesEnabled(False)
        for disp, path in self._csv_files:
            item = QListWidgetItem(disp)
            item.setData(Qt.UserRole, path)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list_files.addItem(item)
        self.list_files.setUpdatesEnabled(True); self.list_files.blockSignals(False)

        types_str = "、".join(sorted(types))
        self.lbl_file.setText(f"已解压 {types_str} 录波，共 {len(self._csv_files)} 个 csv。\n请在下方勾选一个或多个录波文件。")
        if self.list_files.count(): self.list_files.item(self.list_files.count() - 1).setCheckState(Qt.Checked)

    def _extract_types(self, types):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.lbl_file.setText(f"正在解压 {'、'.join(sorted(types))} 录波，请稍候…")
        QApplication.processEvents()
        try:
            self._cleanup_tmp()
            self._tmpdir = tempfile.mkdtemp(prefix="ems_wave_")
            found = {}
            if self._archive_kind == "zip": self._extract_from_zip(types, found)
            else: self._extract_from_tar(types, found)
            self._csv_files = sorted(found.items())
        finally: QApplication.restoreOverrideCursor()

    def _extract_from_tar(self, types, found):
        with tarfile.open(self._tar_path, "r:*") as tf:
            for t in types:
                for name in self.type_index.get(t, []):
                    base = os.path.basename(name); low = base.lower()
                    if low.endswith(".csv.tar.gz"):
                        data = tf.extractfile(name).read()
                        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as inner:
                            for im in inner.getmembers():
                                if not im.isfile() or not im.name.lower().endswith(".csv"): continue
                                ibase = os.path.basename(im.name); out = os.path.join(self._tmpdir, ibase)
                                with open(out, "wb") as f: f.write(inner.extractfile(im).read())
                                found.setdefault(ibase, out)
                    elif low.endswith(".csv.zip"):
                        data = tf.extractfile(name).read()
                        with zipfile.ZipFile(io.BytesIO(data), "r") as inner:
                            for im in inner.namelist():
                                if im.endswith("/") or not im.lower().endswith(".csv"): continue
                                ibase = os.path.basename(im); out = os.path.join(self._tmpdir, ibase)
                                with open(out, "wb") as f: f.write(inner.read(im))
                                found.setdefault(ibase, out)
                    elif low.endswith(".csv"):
                        out = os.path.join(self._tmpdir, base)
                        with open(out, "wb") as f: f.write(tf.extractfile(name).read())
                        found.setdefault(base, out)

    def _extract_from_zip(self, types, found):
        with zipfile.ZipFile(self._tar_path, "r") as zf:
            for t in types:
                for name in self.type_index.get(t, []):
                    base = os.path.basename(name); low = base.lower()
                    if low.endswith(".csv.tar.gz"):
                        data = zf.read(name)
                        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as inner:
                            for im in inner.getmembers():
                                if not im.isfile() or not im.name.lower().endswith(".csv"): continue
                                ibase = os.path.basename(im.name); out = os.path.join(self._tmpdir, ibase)
                                with open(out, "wb") as f: f.write(inner.extractfile(im).read())
                                found.setdefault(ibase, out)
                    elif low.endswith(".csv.zip"):
                        data = zf.read(name)
                        with zipfile.ZipFile(io.BytesIO(data), "r") as inner:
                            for im in inner.namelist():
                                if im.endswith("/") or not im.lower().endswith(".csv"): continue
                                ibase = os.path.basename(im); out = os.path.join(self._tmpdir, ibase)
                                with open(out, "wb") as f: f.write(inner.read(im))
                                found.setdefault(ibase, out)
                    elif low.endswith(".csv"):
                        out = os.path.join(self._tmpdir, base)
                        with open(out, "wb") as f: f.write(zf.read(name))
                        found.setdefault(base, out)

    def _cleanup_tmp(self):
        if self._tmpdir and os.path.isdir(self._tmpdir): shutil.rmtree(self._tmpdir, ignore_errors=True)
        self._tmpdir = None

    def closeEvent(self, event):
        self._cleanup_tmp()
        if self._search_dialog is not None: self._search_dialog.close()
        super().closeEvent(event)

    def schedule_load_csvs(self, *_):
        if self._tar_path is not None: self._load_timer.start()

    def _get_waveform(self, path: str) -> WaveformFile:
        wf = self._csv_cache.get(path)
        if wf is not None: return wf
        df, tc, tp, orig_rows, col_pos = load_waveform(path)
        wf = WaveformFile(df, tc, tp, orig_rows, col_pos)
        self._csv_cache[path] = wf
        self._cache_order.append(path)
        while len(self._cache_order) > CSV_CACHE_LIMIT:
            old = self._cache_order.pop(0)
            self._csv_cache.pop(old, None)
        return wf

    def load_selected_csvs(self):
        paths = [(self.list_files.item(i).text(), self.list_files.item(i).data(Qt.UserRole)) 
                 for i in range(self.list_files.count()) if _is_checked_state(self.list_files.item(i).checkState())]
        if not paths:
            self._combined_key = None
            self._apply_combined(None, None)
            return

        paths.sort(key=lambda x: x[1])
        key = tuple(p for _, p in paths)
        if key == self._combined_key: return

        combined = self._combined_cache.get(key)
        if combined is None:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                items = [self._get_waveform(p) for _, p in paths]
                combined = merge_waveforms(items)
            except Exception as e:
                QApplication.restoreOverrideCursor()
                QMessageBox.critical(self, "加载失败", f"读取 csv 出错：\n{e}")
                return
            QApplication.restoreOverrideCursor()

            if len(self._combined_cache) >= MERGED_CACHE_LIMIT:
                self._combined_cache.pop(next(iter(self._combined_cache)))
            self._combined_cache[key] = combined

        self._combined_key = key
        self._loaded_paths = [p for _, p in paths]
        names = [d for d, _ in paths]
        desc = [f"已加载 {len(paths)} 个录波文件：", names[0] + (" …" if len(names) > 1 else "")]
        self._apply_combined(combined, desc)

    def _apply_combined(self, combined, desc_lines):
        self._combined = combined
        self._bookmarks, self._highlight_bookmark_idx = [], None

        if combined is None:
            self.list_cols.blockSignals(True); self.list_cols.clear(); self.list_cols.blockSignals(False)
            self.table_model.set_data(None, [], None)
            self._mask_idx = None
            if desc_lines: self.lbl_file.setText("\n".join(desc_lines))
            self.redraw()
            return

        current = [self.list_cols.item(i).data(Qt.UserRole) for i in range(self.list_cols.count())]
        if current != combined.columns:
            prev_checked = {self.list_cols.item(i).data(Qt.UserRole) for i in range(self.list_cols.count()) if _is_checked_state(self.list_cols.item(i).checkState())}
            self.list_cols.setUpdatesEnabled(False); self.list_cols.blockSignals(True)
            try:
                self.list_cols.clear()
                for col in combined.columns:
                    item = QListWidgetItem()
                    item.setData(Qt.UserRole, col)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Unchecked)
                    item.setToolTip(col)
                    self.list_cols.addItem(item)
                    self._refresh_col_axis_label(self.list_cols.count() - 1)
            finally:
                self.list_cols.blockSignals(False); self.list_cols.setUpdatesEnabled(True)

            if prev_checked:
                for i in range(self.list_cols.count()):
                    if self.list_cols.item(i).data(Qt.UserRole) in prev_checked:
                        self.list_cols.item(i).setCheckState(Qt.Checked)
            elif not self._first_load_done:
                for i in range(min(DEFAULT_CHECKED_COUNT, self.list_cols.count())):
                    self.list_cols.item(i).setCheckState(Qt.Checked)
            self._first_load_done = True
            try: self.list_cols.viewport().update()
            except Exception: pass
            self.apply_filter(self.edt_search.text())

        t0, t1 = combined.t0, combined.t1
        q0, q1 = QDateTime(t0.date(), t0.time()), QDateTime(t1.date(), t1.time())
        if t1 != t1.floor("s"): q1 = q1.addSecs(1)
        for edt, val in ((self.dt_start, q0), (self.dt_end, q1)):
            edt.blockSignals(True); edt.setDateTime(val); edt.blockSignals(False)

        self.lbl_file.setText("\n".join((desc_lines or []) + [f"{combined.n_rows} 行 × {len(combined.columns)} 个测点", f"时间段：{t0} ～ {t1}"]))
        self.redraw()

    def apply_filter(self, text: str):
        text = text.strip().lower()
        for i in range(self.list_cols.count()):
            item = self.list_cols.item(i)
            col = item.data(Qt.UserRole) or ""
            item.setHidden(text not in (item.text() + " " + str(col)).lower() if text else False)

    def on_search_clicked(self): self.apply_filter(self.edt_search.text())
    def on_clear_search(self): self.edt_search.clear()

    def check_filtered(self, state):
        self.list_cols.blockSignals(True); self.list_cols.setUpdatesEnabled(False)
        try:
            for i in range(self.list_cols.count()):
                item = self.list_cols.item(i)
                if not item.isHidden(): item.setCheckState(state)
        finally:
            self.list_cols.setUpdatesEnabled(True); self.list_cols.blockSignals(False)
        try: self.list_cols.viewport().update()
        except Exception: pass
        self.schedule_redraw()

    def selected_columns(self):
        return [(short_name(self.list_cols.item(i).data(Qt.UserRole)), self.list_cols.item(i).data(Qt.UserRole), self._col_axis.get(self.list_cols.item(i).data(Qt.UserRole), 'left'))
                for i in range(self.list_cols.count()) if _is_checked_state(self.list_cols.item(i).checkState())]

    def set_quick_range(self, minutes: int):
        if self._combined is None: return
        t0, t1 = self._combined.t0, self._combined.t1
        q0, q1 = QDateTime(t0.date(), t0.time()), QDateTime(t1.date(), t1.time())
        if t1 != t1.floor("s"): q1 = q1.addSecs(1)
        self.dt_end.blockSignals(True); self.dt_end.setDateTime(q1); self.dt_end.blockSignals(False)
        start = q0 if minutes == 0 else max(q0, q1.addSecs(-minutes * 60))
        self.dt_start.setDateTime(start)

    def schedule_redraw(self, *_):
        if self._combined is not None: self._redraw_timer.start()

    @staticmethod
    def _wallclock_epoch(qdt: QDateTime) -> float:
        return datetime.datetime(qdt.date().year(), qdt.date().month(), qdt.date().day(), qdt.time().hour(),
                                 qdt.time().minute(), qdt.time().second(), qdt.time().msec() * 1000, tzinfo=datetime.timezone.utc).timestamp()

    def redraw(self):
        try: self._redraw()
        except Exception as e: self.lbl_readout.setText(f"绘图出错：{type(e).__name__}: {e}")

    def _redraw(self):
        self.plot.clear(); self.legend.clear()
        try:
            for it in list(self.plot_item2.addedItems): self.plot_item2.removeItem(it)
        except Exception: pass
        self._curves, self._mask_idx, self._bookmark_lines, self._bookmark_tips, self._bookmark_graphics = [], None, [], [], []

        self.plot.addItem(self.vline, ignoreBounds=True)
        self.plot.addItem(self.hline, ignoreBounds=True)
        self.plot.addItem(self.tooltip, ignoreBounds=True)
        self.tooltip.setVisible(False)

        try: self.legend.setVisible(self._legend_visible)
        except Exception: pass

        combined = self._combined
        if combined is None:
            self.table_model.set_data(None, [], None)
            self.plot.plotItem.getAxis('right').setVisible(False)
            return

        cols = self.selected_columns()
        if not cols:
            self.lbl_readout.setText("请在左侧勾选至少一个测点。")
            self.table_model.set_data(None, [], None)
            self.plot.plotItem.getAxis('right').setVisible(False)
            return

        ts, te = self._wallclock_epoch(self.dt_start.dateTime()), self._wallclock_epoch(self.dt_end.dateTime())
        if ts > te: ts, te = te, ts
        x = combined.x_ts
        mask = (x >= ts) & (x <= te)
        if mask.sum() < 2:
            self.lbl_readout.setText(f"所选时间范围内数据点不足。（命中 {int(mask.sum())} 点）")
            self.table_model.set_data(None, [], None)
            self.plot.plotItem.getAxis('right').setVisible(False)
            return

        self._update_table(combined, mask, cols)
        if len(cols) > MAX_CURVES:
            self.lbl_readout.setText(f"已选 {len(cols)} 个测点，超过上限 {MAX_CURVES} 个，曲线仅绘制前 {MAX_CURVES} 条。")
            cols = cols[:MAX_CURVES]

        self._x_view, self._mask_idx, self._last_idx = x[mask], np.nonzero(mask)[0], -1
        palette = self._theme()["palette"]

        has_right = False
        for i, (disp, col, axis) in enumerate(cols):
            y_full = combined.get_num(col)
            if y_full is None: continue
            y, raw = y_full[mask], combined.get_raw(col)[mask]
            pen = pg.mkPen(palette[i % len(palette)], width=2)

            if axis == 'right':
                has_right = True
                item = pg.PlotDataItem(self._x_view, y, pen=pen, connect='finite')
                self.plot_item2.addItem(item)
                try: self.legend.addItem(item, disp + " (右)")
                except Exception: pass
            else:
                item = self.plot.plot(self._x_view, y, pen=pen, name=disp, connect='finite')
            self._curves.append((disp, y, raw, col, axis, item))

        self.plot.plotItem.getAxis('right').setVisible(has_right)
        self.plot.plotItem.setLabel("right", "数值（右）" if has_right else "")
        self.plot.plotItem.setLabel("bottom", "录波时间")
        self.plot.plotItem.setLabel("left", "数值")
        self.plot.setXRange(ts, te, padding=0.02)
        self.plot.plotItem.vb.enableAutoRange(axis='y')
        if has_right:
            try: self.plot_item2.enableAutoRange(axis=pg.ViewBox.YAxis)
            except Exception: pass
        self._draw_bookmarks()

    def _update_table(self, combined, mask, cols):
        if mask is None or not cols:
            self.table_model.set_data(None, [], None)
            return
        times = combined.raw_time[mask]
        headers = ["录波时间"] + [disp for disp, _c, _a in cols]
        n = int(mask.sum())
        vals = np.empty((n, len(cols)), dtype=object)
        for j, (_disp, col, _axis) in enumerate(cols): vals[:, j] = combined.get_raw(col)[mask]
        self.table_model.set_data(times, headers, vals)

    def open_search_dialog(self):
        if self.table_model.rowCount() == 0: return
        if self._search_dialog is None: self._search_dialog = TableSearchDialog(self.table, self.table_model, self)
        self._search_dialog.show(); self._search_dialog.raise_(); self._search_dialog.activateWindow()

    def on_mouse_moved(self, pos):
        if self._combined is None or not self._curves: return
        vb = self.plot.plotItem.vb
        if not self.plot.sceneBoundingRect().contains(pos):
            self.vline.setVisible(False); self.hline.setVisible(False); self.tooltip.setVisible(False); self._last_idx = -1
            if self._highlight_bookmark_idx is not None:
                self._highlight_bookmark_idx = None
                self._apply_bookmark_highlight()
            return
        mp = vb.mapSceneToView(pos)
        self.hline.setPos(mp.y()); self.hline.setVisible(True)
        x = self._x_view
        if x is None or len(x) == 0: return
        idx = self._nearest_index(x, mp.x())
        if idx == self._last_idx: return
        self._last_idx = idx
        snap_x = float(x[idx])
        self.vline.setPos(snap_x); self.vline.setVisible(True)
        html = self._build_readout_html(snap_x)
        if html: self.tooltip.setHtml(html)
        vr = vb.viewRect()
        ax, ay = 1 if mp.x() > vr.center().x() else 0, 0 if mp.y() > vr.center().y() else 1
        self.tooltip.setAnchor((ax, ay))
        self.tooltip.setPos(snap_x, mp.y()); self.tooltip.setVisible(True)
        self._last_mouse_xy, self._last_tip_anchor = (snap_x, float(mp.y())), (ax, ay)
        self._update_bookmark_highlight_from_x(snap_x)

    @staticmethod
    def _nearest_index(x, xv: float) -> int:
        i = int(np.searchsorted(x, xv))
        return (len(x) - 1) if i >= len(x) else (0 if i == 0 else (i if (x[i] - xv) < (xv - x[i - 1]) else i - 1))

    def on_plot_clicked(self, ev):
        if not ev.double() or ev.button() != Qt.LeftButton or self._combined is None or not self._curves: return
        x = self._x_view
        if x is None or len(x) == 0 or not self.plot.sceneBoundingRect().contains(ev.scenePos()): return
        scene_pos = ev.scenePos()
        mp = self.plot.plotItem.vb.mapSceneToView(scene_pos)
        idx = self._nearest_index(x, mp.x())
        mouse_y_left = float(mp.y())
        try: mouse_y_right = float(self.plot_item2.mapSceneToView(scene_pos).y())
        except Exception: mouse_y_right = mouse_y_left
        self._confirm_open_source(idx, mouse_y_left, mouse_y_right)

    def _confirm_open_source(self, idx: int, mouse_y_left: float, mouse_y_right: float):
        combined = self._combined
        if combined is None or self._mask_idx is None or idx < 0 or idx >= len(self._mask_idx): return
        ci = int(self._mask_idx[idx])
        src, row = int(combined.src_file[ci]), int(combined.src_row[ci])
        if src < 0 or row < 0:
            self.lbl_readout.setText("该位置是文件交界处的分隔点，无对应原始数据行。")
            return
        if src >= len(self._loaded_paths): return
        path = self._loaded_paths[src]
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "提示", "找不到对应的原始文件（可能已被删除）。")
            return

        best_col, best_name, best_dist = None, "", None
        for disp, y, _raw, col, axis, _item in self._curves:
            if idx >= len(y): continue
            try: fv = float(y[idx])
            except (TypeError, ValueError): continue
            if np.isnan(fv): continue
            my = mouse_y_left if axis == 'left' else mouse_y_right
            d_norm = abs(fv - my) / max(abs(fv), abs(my), 1e-9)
            if best_dist is None or d_norm < best_dist: best_dist, best_col, best_name = d_norm, col, disp

        excel_row = row + 2
        t_str = str(combined.raw_time[ci]) or "—"
        target_desc = f"第 {excel_row} 行（列由下方“定位到哪一列”决定）"
        curves = [(d, c) for d, _y, _r, c, _a, _it in self._curves]

        dlg = OpenSourceDialog(self, os.path.basename(path), t_str, target_desc, curves, best_col)
        if dlg.exec() != QDialog.Accepted: return
        move_cols, target_col = dlg.selected_columns(), dlg.target_column()
        excel_col = 1
        if target_col:
            col_idx = combined.col_pos.get(target_col, -1)
            if col_idx >= 0: excel_col = col_idx + 1
        self.excel_manager.open_and_locate(path, excel_row, excel_col, target_col, move_cols, self)