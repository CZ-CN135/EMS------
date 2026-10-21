# -*- coding: utf-8 -*-
import numpy as np
from ems_waveform_viewer.constants import OSC_ENVELOPE_WIN

try:
    from scipy.signal import find_peaks as _scipy_find_peaks
    _HAS_SCIPY = True
except Exception:
    _scipy_find_peaks = None
    _HAS_SCIPY = False


def _estimate_dt(t: np.ndarray):
    if t is None or len(t) < 2: return None
    diffs = np.diff(t)
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    if len(diffs) == 0: return None
    return float(np.median(diffs))


def _sliding_envelope(y: np.ndarray, win_size: int):
    n = len(y)
    if n == 0: return 0.0, 0.0
    if win_size < 3: win_size = 3
    if win_size % 2 == 0: win_size += 1
    if n < win_size:
        win_size = n if (n % 2 == 1) else max(3, n - 1)
        if win_size < 3: return float(np.max(y)), float(np.min(y))
    half = win_size // 2
    ypad = np.pad(y, (half, half), mode='edge')
    try:
        from numpy.lib.stride_tricks import sliding_window_view
        windows = sliding_window_view(ypad, win_size)
        pos = float(np.mean(np.max(windows, axis=1)))
        neg = float(np.mean(np.min(windows, axis=1)))
    except Exception:
        pos, neg = float(np.max(y)), float(np.min(y))
    return pos, neg


def _estimate_freq_fft(t: np.ndarray, y: np.ndarray):
    n = len(y)
    if n < 8: return None, None
    dt = _estimate_dt(t)
    if dt is None or dt <= 0: return None, None
    y0 = y - np.mean(y)
    win = np.hanning(n)
    yw = y0 * win
    Y = np.fft.rfft(yw)
    freqs = np.fft.rfftfreq(n, d=dt)
    mag = np.abs(Y)
    guard = min(3, len(mag))
    mag[:guard] = 0.0
    if len(mag) == 0: return None, None
    k = int(np.argmax(mag))
    if k <= 0 or freqs[k] <= 0: return None, None
    f0 = float(freqs[k])
    amp = 2.0 * float(mag[k]) / max(1e-12, float(np.sum(win)))
    return f0, amp


def _estimate_freq_zero_cross(t: np.ndarray, y: np.ndarray):
    n = len(y)
    if n < 4: return None
    y0 = y - np.mean(y)
    s = np.sign(y0)
    nz = s != 0
    if int(nz.sum()) < 3: return None
    s = s[nz]
    tz = t[nz]
    idx = np.nonzero(np.diff(s) != 0)[0]
    if len(idx) < 3: return None

    duration = float(tz[-1] - tz[0])
    if duration <= 0: return None
    f_zero = float(len(idx) / (2.0 * duration))

    cross_times = tz[idx + 1]
    half_periods = np.diff(cross_times)
    half_periods = half_periods[np.isfinite(half_periods) & (half_periods > 0)]

    if len(half_periods) == 0:
        return {"f_zero": f_zero, "half_period_median_s": None, "half_period_std_s": None,
                "half_period_min_s": None, "half_period_max_s": None, "n_cross": int(len(idx))}

    return {"f_zero": f_zero, "half_period_median_s": float(np.median(half_periods)),
            "half_period_std_s": float(np.std(half_periods)), "half_period_min_s": float(np.min(half_periods)),
            "half_period_max_s": float(np.max(half_periods)), "n_cross": int(len(idx))}


def _estimate_period_autocorr(t: np.ndarray, y: np.ndarray):
    n = len(y)
    if n < 32: return {"period_s": None, "ac_peak_val": None, "ac_decay": None}
    dt = _estimate_dt(t)
    if dt is None or dt <= 0: return {"period_s": None, "ac_peak_val": None, "ac_decay": None}

    y0 = y - np.mean(y)
    try:
        idx = np.arange(n)
        slope, intercept = np.polyfit(idx, y0, 1)
        y0 = y0 - (slope * idx + intercept)
    except Exception: pass

    max_lag = max(1, n // 2)
    try:
        y0 = y0 - np.mean(y0)
        denom = float(np.dot(y0, y0))
        if denom <= 0: return {"period_s": None, "ac_peak_val": None, "ac_decay": None}
        ac = np.empty(max_lag + 1, dtype=np.float64)
        for k in range(max_lag + 1):
            ac[k] = 1.0 if k == 0 else float(np.dot(y0[:-k], y0[k:])) / denom
    except Exception:
        return {"period_s": None, "ac_peak_val": None, "ac_decay": None}

    start = 1
    for k in range(1, max_lag + 1):
        if ac[k] < 0:
            start = k + 1
            break

    ac_decay = float(np.min(ac[1:start])) if start > 1 else None
    peak_idx = None
    peak_val = None
    for k in range(max(start, 1), max_lag):
        if ac[k] > ac[k - 1] and ac[k] > ac[k + 1] and ac[k] > 0.3:
            peak_idx, peak_val = k, float(ac[k])
            break

    if peak_idx is None: return {"period_s": None, "ac_peak_val": None, "ac_decay": ac_decay}
    return {"period_s": float(peak_idx * dt), "ac_peak_val": peak_val, "ac_decay": ac_decay}


def _find_peaks_simple(y: np.ndarray):
    if len(y) < 3: return np.array([], dtype=np.int64)
    left = y[1:-1] > y[:-2]
    right = y[1:-1] > y[2:]
    return np.nonzero(left & right)[0] + 1


def _estimate_period_peak_intervals(t: np.ndarray, y: np.ndarray):
    n = len(y)
    if n < 16: return {"period_s": None, "period_std_s": None, "period_cv": None, "n_peaks": 0}
    y0 = y - np.mean(y)

    if _HAS_SCIPY:
        try:
            prom = float(np.std(y0) * 0.5) if np.std(y0) > 0 else None
            peaks, _ = _scipy_find_peaks(y0, prominence=prom)
        except Exception:
            peaks = _find_peaks_simple(y0)
    else:
        peaks = _find_peaks_simple(y0)

    peaks = np.asarray(peaks, dtype=np.int64)
    if len(peaks) < 3: return {"period_s": None, "period_std_s": None, "period_cv": None, "n_peaks": int(len(peaks))}

    peak_t = t[peaks]
    intervals = np.diff(peak_t)
    intervals = intervals[np.isfinite(intervals) & (intervals > 0)]
    if len(intervals) < 2: return {"period_s": None, "period_std_s": None, "period_cv": None, "n_peaks": int(len(peaks))}

    med = float(np.median(intervals))
    std = float(np.std(intervals))
    cv = (std / med) if med > 0 else None
    return {"period_s": med, "period_std_s": std, "period_cv": cv, "n_peaks": int(len(peaks))}


def analyze_oscillation(t: np.ndarray, y: np.ndarray):
    if t is None or y is None or len(y) < 4: return None
    valid = np.isfinite(t) & np.isfinite(y)
    if int(valid.sum()) < 4: return None
    t, y = t[valid], y[valid]

    mean_v = float(np.mean(y))
    y0 = y - mean_v
    rms = float(np.sqrt(np.mean(y0 * y0)))

    pos_mean, neg_mean = _sliding_envelope(y, OSC_ENVELOPE_WIN)
    amp_half = (pos_mean - neg_mean) / 2.0
    amp_pk2pk = pos_mean - neg_mean

    f_fft, amp_fft = _estimate_freq_fft(t, y)
    zc = _estimate_freq_zero_cross(t, y)
    ac = _estimate_period_autocorr(t, y)
    pk = _estimate_period_peak_intervals(t, y)

    return {
        "mean": mean_v, "rms": rms, "pos_mean": pos_mean, "neg_mean": neg_mean,
        "amp_half": amp_half, "amp_pk2pk": amp_pk2pk, "f_fft": f_fft, "amp_fft": amp_fft,
        "f_zero": (zc["f_zero"] if zc else None),
        "half_period_median_s": (zc["half_period_median_s"] if zc else None),
        "half_period_std_s": (zc["half_period_std_s"] if zc else None),
        "half_period_min_s": (zc["half_period_min_s"] if zc else None),
        "half_period_max_s": (zc["half_period_max_s"] if zc else None),
        "n_cross": (zc["n_cross"] if zc else 0),
        "ac_period_s": ac["period_s"], "ac_peak_val": ac["ac_peak_val"], "ac_decay": ac["ac_decay"],
        "pk_period_s": pk["period_s"], "pk_period_std_s": pk["period_std_s"], "pk_period_cv": pk["period_cv"], "n_peaks": pk["n_peaks"],
        "n_valid": int(valid.sum()),
    }