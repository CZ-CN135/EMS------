# -*- coding: utf-8 -*-
import os
import sys
import subprocess
from PySide6.QtWidgets import QMessageBox
from ems_waveform_viewer.utils import rgb_to_excel_color, short_name

class ExcelManager:
    def __init__(self):
        self._excel_app = None

    def open_and_locate(self, path: str, excel_row: int, excel_col: int, target_col: str = None, move_cols=None, parent_widget=None):
        abspath = os.path.abspath(path)
        try:
            import win32com.client  # type: ignore
        except Exception:
            self._launch_default(abspath)
            if parent_widget: parent_widget.lbl_readout.setText("未安装 pywin32，已用系统默认程序打开文件（无法自动排版/定位）。")
            return False

        try:
            try:
                app = win32com.client.GetActiveObject("Excel.Application")
            except Exception:
                app = win32com.client.Dispatch("Excel.Application")
            self._excel_app = app

            try: app.DisplayAlerts = False
            except Exception: pass
            app.Visible = True
            try: app.WindowState = -4143
            except Exception: pass

            target_norm = os.path.normcase(abspath)
            wb = None
            try:
                for w in app.Workbooks:
                    try:
                        if os.path.normcase(str(w.FullName)) == target_norm:
                            wb = w
                            break
                    except Exception: continue
            except Exception: pass

            if wb is None:
                wb = app.Workbooks.Open(abspath, UpdateLinks=0, ReadOnly=False, Local=True)

            ws = wb.Worksheets(1)
            ws.Activate()
            try: app.ActiveWindow.Activate()
            except Exception: pass

            try: ws.Columns(1).ColumnWidth = 21.00
            except Exception: pass
            try: ws.Rows(1).WrapText = True
            except Exception: pass

            try: app.ActiveWindow.FreezePanes = False
            except Exception: pass
            try: ws.Range("A2").Select()
            except Exception: pass
            frozen_ok = False
            try:
                app.ActiveWindow.FreezePanes = True
                frozen_ok = True
            except Exception: frozen_ok = False
            if not frozen_ok:
                try:
                    app.ActiveWindow.SplitRow = 1
                    app.ActiveWindow.SplitColumn = 0
                    app.ActiveWindow.FreezePanes = True
                except Exception: pass

            if move_cols:
                self._move_columns_to_front(ws, move_cols)
                if target_col:
                    new_idx = self._find_col_by_name(ws, target_col)
                    if new_idx: excel_col = new_idx

            ORANGE_BGR = rgb_to_excel_color(255, 165, 0)
            try:
                cell = ws.Cells(excel_row, excel_col)
                cell.Interior.Pattern = 1
                cell.Interior.Color = ORANGE_BGR
                try: app.Goto(cell, True)
                except Exception: cell.Select()
            except Exception: pass

            try: app.WindowState = -4143
            except Exception: pass
            try: app.ActiveWindow.Activate()
            except Exception: pass
            try: app.CutCopyMode = False
            except Exception: pass

            if parent_widget:
                parent_widget.lbl_readout.setText(f"已在 Excel 中打开并定位：{os.path.basename(abspath)}（第 {excel_row} 行、第 {excel_col} 列）")
            return True
        except Exception as e:
            self._launch_default(abspath)
            if parent_widget: parent_widget.lbl_readout.setText(f"Excel 自动定位失败（{e}），已用系统默认程序打开文件。")
            return False

    @staticmethod
    def _find_col_by_name(ws, name: str):
        if not name: return None
        try:
            used = ws.UsedRange
            last_col = used.Column + used.Columns.Count - 1
        except Exception: return None
        for c in range(1, last_col + 1):
            v = ws.Cells(1, c).Value
            if v is None: continue
            if str(v).strip() == name: return c
        short_target = short_name(name)
        for c in range(1, last_col + 1):
            v = ws.Cells(1, c).Value
            if v is None: continue
            if short_name(str(v).strip()) == short_target: return c
        return None

    @staticmethod
    def _move_columns_to_front(ws, col_names):
        if not col_names: return
        wanted = set(col_names)
        try:
            used = ws.UsedRange
            last_col = used.Column + used.Columns.Count - 1
        except Exception: return

        found = []
        for c in range(1, last_col + 1):
            v = ws.Cells(1, c).Value
            if v is None: continue
            s = str(v).strip()
            if s in wanted:
                found.append((c, s))
                if len(found) == len(wanted): break
        if not found: return
        found.sort()

        target = 2
        for orig, _name in found:
            if orig == target:
                target += 1
                continue
            try:
                ws.Columns(orig).Cut()
                ws.Columns(target).Insert(Shift=-4161)
            except Exception: pass
            target += 1

    @staticmethod
    def _launch_default(path: str):
        try:
            if sys.platform.startswith("win"): os.startfile(path)
            elif sys.platform == "darwin": subprocess.Popen(["open", path])
            else: subprocess.Popen(["xdg-open", path])
        except Exception as e:
            QMessageBox.warning(None, "打开失败", f"无法打开文件：\n{path}\n{e}")