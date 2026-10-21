# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
from ems_waveform_viewer.constants import TIME_FMT

def load_waveform(path: str):
    df = None
    last_err = None

    for enc in ("utf-8-sig", "gb18030"):
        try:
            headers = pd.read_csv(path, encoding=enc, nrows=0).columns.tolist()
        except Exception as e:
            last_err = e
            continue

        col_pos = {c: i for i, c in enumerate(headers)}

        try:
            head = pd.read_csv(path, encoding=enc, nrows=200, dtype=str, keep_default_na=False, low_memory=False)
        except Exception as e:
            last_err = e
            continue

        if head.shape[1] < 2:
            raise RuntimeError("文件列数不足：需要 1 列时间 + 至少 1 列数据")

        t_col = head.columns[0]
        sample_t = head[t_col].astype(str).str.strip()
        probe_t = pd.to_datetime(sample_t, format=TIME_FMT, errors="coerce")
        if probe_t.isna().all():
            probe_t = pd.to_datetime(sample_t, errors="coerce")
        if probe_t.isna().all():
            raise RuntimeError("未找到可解析的时间行")

        numeric_cols = []
        for c in head.columns[1:]:
            s = head[c].astype(str).str.strip()
            num = pd.to_numeric(s, errors="coerce")
            if num.notna().sum() >= max(1, int(len(s) * 0.8)):
                numeric_cols.append(c)
        if not numeric_cols:
            raise RuntimeError("未找到可用的数值数据列")

        try:
            usecols = [t_col] + numeric_cols
            df = pd.read_csv(path, encoding=enc, usecols=usecols, dtype=str, keep_default_na=False, low_memory=False)
            break
        except Exception as e:
            last_err = e
            df = None
            continue

    if df is None:
        raise RuntimeError(f"文件读取失败：{last_err}")
    if df.shape[1] < 2:
        raise RuntimeError("文件列数不足")

    t_col = df.columns[0]
    orig_rows = np.arange(len(df), dtype=np.int64)

    t_parsed = pd.to_datetime(df[t_col], format=TIME_FMT, errors="coerce")
    if t_parsed.isna().all():
        t_parsed = pd.to_datetime(df[t_col], errors="coerce")

    valid = t_parsed.notna()
    if not valid.any():
        raise RuntimeError("未找到可解析的时间行")
    valid_np = valid.to_numpy()

    df = df[valid].reset_index(drop=True)
    t_parsed = t_parsed[valid].reset_index(drop=True)
    orig_rows = orig_rows[valid_np]

    order = np.argsort(t_parsed.to_numpy(), kind="stable")
    df = df.iloc[order].reset_index(drop=True)
    t_parsed = t_parsed.iloc[order].reset_index(drop=True)
    orig_rows = orig_rows[order]

    return df, t_col, t_parsed, orig_rows, col_pos


class WaveformFile:
    __slots__ = ("t_col", "columns", "x_ts", "raw_time", "num", "raw", "orig_rows", "col_pos", "_df")

    def __init__(self, df, t_col, t_parsed, orig_rows, col_pos):
        self.t_col = t_col
        self.columns = list(df.columns[1:])
        self.x_ts = (t_parsed.values.astype("datetime64[ns]").astype("int64") / 1e9)
        self.raw_time = df[t_col].to_numpy(dtype=object)
        self.orig_rows = np.asarray(orig_rows, dtype=np.int64)
        self.col_pos = dict(col_pos)
        self._df = df
        self.num = {}
        self.raw = {}

    def ensure_col(self, col):
        if col in self.raw:
            return
        if self._df is None or col not in self._df.columns:
            return
        s = self._df[col]
        self.raw[col] = s.to_numpy(dtype=object)
        self.num[col] = pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)


class CombinedData:
    __slots__ = ("t_col", "columns", "x_ts", "raw_time", "t0", "t1", "n_rows",
                 "src_file", "src_row", "src_pos", "col_pos", "_items", "_num_cache", "_raw_cache")

    def __init__(self, items, t_col, columns, x_ts, raw_time, t0, t1, src_file, src_row, src_pos, col_pos):
        self.t_col = t_col
        self.columns = columns
        self.x_ts = x_ts
        self.raw_time = raw_time
        self.t0 = t0
        self.t1 = t1
        self.n_rows = len(x_ts)
        self.src_file = src_file
        self.src_row = src_row
        self.src_pos = src_pos
        self.col_pos = col_pos

        self._items = items
        self._num_cache = {}
        self._raw_cache = {}

    def get_num(self, col):
        cached = self._num_cache.get(col)
        if cached is not None:
            return cached
        arr = np.full(self.n_rows, np.nan, dtype=np.float64)
        for i, it in enumerate(self._items):
            it.ensure_col(col)
            col_num = it.num.get(col)
            if col_num is None:
                continue
            m = (self.src_file == i)
            if not m.any():
                continue
            pos_in_file = self.src_pos[m]
            valid = (pos_in_file >= 0) & (pos_in_file < len(col_num))
            if not valid.any():
                continue
            target_idx = np.nonzero(m)[0][valid]
            arr[target_idx] = col_num[pos_in_file[valid]]
        self._num_cache[col] = arr
        return arr

    def get_raw(self, col):
        cached = self._raw_cache.get(col)
        if cached is not None:
            return cached
        arr = np.empty(self.n_rows, dtype=object)
        arr[:] = ""
        for i, it in enumerate(self._items):
            it.ensure_col(col)
            col_raw = it.raw.get(col)
            if col_raw is None:
                continue
            m = (self.src_file == i)
            if not m.any():
                continue
            pos_in_file = self.src_pos[m]
            valid = (pos_in_file >= 0) & (pos_in_file < len(col_raw))
            if not valid.any():
                continue
            target_idx = np.nonzero(m)[0][valid]
            arr[target_idx] = col_raw[pos_in_file[valid]]
        self._raw_cache[col] = arr
        return arr


def merge_waveforms(items):
    if not items:
        return None

    if len(items) == 1:
        it = items[0]
        if len(it.x_ts) == 0:
            return None
        t0 = pd.Timestamp(it.x_ts[0], unit="s")
        t1 = pd.Timestamp(it.x_ts[-1], unit="s")
        n = len(it.x_ts)
        src_file = np.zeros(n, dtype=np.int32)
        src_row = np.asarray(it.orig_rows, dtype=np.int64)
        src_pos = np.arange(n, dtype=np.int64)
        return CombinedData(items=items, t_col=it.t_col, columns=it.columns, x_ts=it.x_ts, raw_time=it.raw_time,
                            t0=t0, t1=t1, src_file=src_file, src_row=src_row, src_pos=src_pos, col_pos=dict(it.col_pos))

    cols = list(items[0].columns)
    col_set = set(cols)
    for it in items[1:]:
        for c in it.columns:
            if c not in col_set:
                cols.append(c)
                col_set.add(c)

    col_pos = {}
    for it in items:
        for c in it.columns:
            if c not in col_pos:
                col_pos[c] = it.col_pos.get(c, -1)

    total = sum(len(it.x_ts) for it in items) + (len(items) - 1)
    x_ts = np.empty(total, dtype=np.float64)
    raw_time = np.empty(total, dtype=object)
    src_file = np.full(total, -1, dtype=np.int32)
    src_row = np.full(total, -1, dtype=np.int64)
    src_pos = np.full(total, -1, dtype=np.int64)

    pos = 0
    for i, it in enumerate(items):
        n = len(it.x_ts)
        x_ts[pos:pos + n] = it.x_ts
        raw_time[pos:pos + n] = it.raw_time
        src_file[pos:pos + n] = i
        src_row[pos:pos + n] = it.orig_rows
        src_pos[pos:pos + n] = np.arange(n, dtype=np.int64)
        pos += n
        if i < len(items) - 1:
            x_ts[pos] = (it.x_ts[-1] + 0.001) if n else 0.0
            raw_time[pos] = ""
            src_file[pos] = -1
            src_row[pos] = -1
            src_pos[pos] = -1
            pos += 1

    order = np.argsort(x_ts, kind="stable")
    x_ts = x_ts[order]
    raw_time = raw_time[order]
    src_file = src_file[order]
    src_row = src_row[order]
    src_pos = src_pos[order]

    t0 = pd.Timestamp(x_ts[0], unit="s")
    t1 = pd.Timestamp(x_ts[-1], unit="s")
    return CombinedData(items=items, t_col=items[0].t_col, columns=cols, x_ts=x_ts, raw_time=raw_time,
                        t0=t0, t1=t1, src_file=src_file, src_row=src_row, src_pos=src_pos, col_pos=col_pos)