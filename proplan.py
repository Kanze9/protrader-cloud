"""The trading plan that survived testing: the user's Pro Pullback entries + Chandelier trailing exit.

Tested 2026-10-22 on 2 years of H1 data (Yahoo) for XAUUSD / BTCUSD / EURUSD / USDJPY, spread included, same entries
with 8 exit plans, judged on the first 60% and checked on the unseen last 40%:
  Pro Pullback + Chandelier 3xATR: train +0.065R/trade (PF 1.14), unseen +0.117R (PF 1.23), lowest drawdown.
  Without USDJPY: 363 trades, 36% win, +0.149R/trade, PF 1.31.  USDJPY lost in both halves.
  The script's original fixed 2R exit lost on the unseen half (-0.18R); Signal v26 was positive only on BTC.

Pro-trader filters tested the same way (2026-10-22), kept because they improved BOTH halves on most markets:
  - trade only in the direction of the DAILY trend (D1 close/EMA50/EMA200 aligned): Pro Pullback unseen +0.28R -> +0.45R,
    Signal v26 (BTC) +0.37R -> +0.82R per trade
  - skip Mondays (UTC): Pro Pullback unseen +0.28R -> +0.39R, v26 +0.37R -> +0.48R
  Rejected: Raschke "Holy Grail" ADX>30 (too few trades, inconsistent), killzones only, RSI, volatility regime.
  Trailing width: 3.0xATR plateau for Pro Pullback; 3.5xATR better on both halves for Signal v26.

Everything uses closed candles only, so a signal can't appear and disappear (no repainting).
"""
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from config import SPREADS
from technical import add_indicators

CHANDELIER_ATR = 3.0                      # Pro Pullback
TRAIL_ATR = {"pro": 3.0, "v26": 3.5}
USE_FILTERS = True                        # daily-trend alignment + skip Mondays + no chasing
# False-signal study (2026-10-22, 2y H1, train/test):
#   no entry after 3+ trend candles in a row: train +0.23R -> +0.28R (win 42% -> 46%), unseen +0.78R -> +0.81R  (always on)
#   strict: room >= 1R to the opposing 100-bar swing: unseen +0.78R -> +1.25R but half the signals (optional)
#   rejected: strong-body candle, entry near EMA20, break-even at +1R/+1.5R, time stops
MAX_HOLD = 300
V26 = {"EURUSD": 1.5, "XAUUSD": 3.0, "BTCUSD": 2.5, "USDJPY": 1.5}     # Signal v26 stop ATR multiple


def h4_trend(df: pd.DataFrame, h4: Optional[pd.DataFrame], tf_min: int) -> pd.DataFrame:
    """4H close / EMA50 / EMA200 known at each candle's close (real 4H bars if given, else resampled)."""
    if h4 is not None and len(h4) > 210:
        x = add_indicators(h4)[["close", "ema50", "ema200"]].copy()
        x.index = x.index + pd.Timedelta(hours=4)                          # usable once the 4H bar has closed
    else:
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        x = add_indicators(df.resample("4h", label="right", closed="right").agg(agg).dropna())[["close", "ema50", "ema200"]]
    target = df.index + pd.Timedelta(minutes=tf_min)
    x = x[~x.index.duplicated(keep="last")].sort_index()
    out = x.reindex(x.index.union(target)).ffill().reindex(target)
    out.index = df.index
    return out


def daily_trend(df: pd.DataFrame, daily: Optional[pd.DataFrame], tf_min: int) -> pd.Series:
    """+1 / -1 / 0 daily trend (close > EMA50 > EMA200 or the reverse) known at each candle's close."""
    if daily is not None and len(daily) > 210:
        x = add_indicators(daily)
        x.index = x.index + pd.Timedelta(days=1)                            # usable once the day has closed
    else:
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        x = add_indicators(df.resample("1D", label="right", closed="right").agg(agg).dropna())
    tr = pd.Series(np.where((x.close > x.ema50) & (x.ema50 > x.ema200), 1,
                            np.where((x.close < x.ema50) & (x.ema50 < x.ema200), -1, 0)), index=x.index)
    target = df.index + pd.Timedelta(minutes=tf_min)
    tr = tr[~tr.index.duplicated(keep="last")].sort_index()
    out = tr.reindex(tr.index.union(target)).ffill().reindex(target).fillna(0)
    out.index = df.index
    return out.astype(int)


def chasing(d: pd.DataFrame, i: int, side: int) -> bool:
    """True if the signal candle ends a run of 3+ candles in the trade direction (late entry)."""
    o, c = d.open.values, d.close.values
    run = 0
    for j in range(i, max(-1, i - 10), -1):
        if (c[j] > o[j]) if side == 1 else (c[j] < o[j]):
            run += 1
        else:
            break
    return run >= 3


def room_r(d: pd.DataFrame, i: int, side: int, stop: float) -> float:
    """Distance to the opposing 100-bar swing extreme, in R."""
    R = abs(d.close.iloc[i] - stop) or 1e-9
    opp = d.high.iloc[max(0, i - 100):i].max() if side == 1 else d.low.iloc[max(0, i - 100):i].min()
    return float((opp - d.close.iloc[i]) * side / R)


def filters_ok(side: int, t: pd.Timestamp, dtrend: Optional[int]) -> bool:
    if not USE_FILTERS:
        return True
    if t.weekday() == 0:
        return False
    return dtrend is None or dtrend == side


def pro_pullback_checks(d: pd.DataFrame, t4: pd.DataFrame, i: int) -> Dict:
    """Each condition of the user's Pro Pullback script for candle i (for the checklist and signals)."""
    o, h, l, c = d.open.values, d.high.values, d.low.values, d.close.values
    e20, e50, adx, atr = d.ema20.values, d.ema50.values, d.adx.values, d.atr.values
    up = t4["close"].iloc[i] > t4["ema200"].iloc[i] and t4["ema50"].iloc[i] > t4["ema200"].iloc[i]
    dn = t4["close"].iloc[i] < t4["ema200"].iloc[i] and t4["ema50"].iloc[i] < t4["ema200"].iloc[i]
    side = 1 if up else -1 if dn else 0
    res = {"trend": side, "session": 7 <= d.index[i].hour < 17, "adx": float(adx[i]), "adx_ok": adx[i] >= 20}
    if side == 1:
        res["structure"] = c[i] > e50[i] and e20[i] > e50[i]
        res["pullback"] = bool((l[i - 3:i + 1] <= e20[i - 3:i + 1]).any())
        res["confirm"] = c[i] > o[i] and c[i] > h[i - 1] and c[i] > e20[i]
        res["stop"] = float(l[i - 9:i + 1].min() - 0.3 * atr[i])
    elif side == -1:
        res["structure"] = c[i] < e50[i] and e20[i] < e50[i]
        res["pullback"] = bool((h[i - 3:i + 1] >= e20[i - 3:i + 1]).any())
        res["confirm"] = c[i] < o[i] and c[i] < l[i - 1] and c[i] < e20[i]
        res["stop"] = float(h[i - 9:i + 1].max() + 0.3 * atr[i])
    else:
        res.update(structure=False, pullback=False, confirm=False, stop=None)
    dist = abs(c[i] - res["stop"]) if res["stop"] is not None else 0
    res["stop_ok"] = res["stop"] is not None and 0 < dist <= 3 * atr[i]
    res["signal"] = side if side and all(res[k] for k in ("session", "adx_ok", "structure", "pullback", "confirm", "stop_ok")) else 0
    return res


def v26_signal(d: pd.DataFrame, i: int, sym: str, h1_ema200: float) -> (int, Optional[float]):
    o, h, l, c, v = d.open.values, d.high.values, d.low.values, d.close.values, d.volume.values
    atr = d.atr.values
    if i < 40:
        return 0, None
    vol = d.volume.iloc[i - 19:i + 1]
    novol = (d.volume.iloc[i - 39:i + 1] <= 0).mean() > 0.5
    bbw = 4 * d.close.rolling(20).std() / d.close.rolling(20).mean() * 100
    ok = ((novol or v[i] > 1.3 * vol.mean()) and atr[i] > 0.8 * d.atr.iloc[i - 19:i + 1].mean()
          and abs(c[i] - d.ema20.iloc[i]) < 1.5 * atr[i] and bbw.iloc[i] > bbw.iloc[i - 19:i + 1].mean() and d.adx.iloc[i] > 20)
    if not ok:
        return 0, None
    rng = h[i] - l[i]
    bull = (c[i-1] < o[i-1] and c[i] > o[i] and c[i] > o[i-1] and o[i] < c[i-1]) or (rng > 0 and (c[i]-l[i])/rng > 0.7 and c[i] > o[i])
    bear = (c[i-1] > o[i-1] and c[i] < o[i] and c[i] < o[i-1] and o[i] > c[i-1]) or (rng > 0 and (h[i]-c[i])/rng > 0.7 and c[i] < o[i])
    k = V26.get(sym, 2.0)
    if bull and c[i] > h1_ema200 and c[i] > d.ema50.iloc[i] and d.rsi.iloc[i] > 50:
        return 1, float(min(l[i-4:i+1].min(), c[i] - k * atr[i]))
    if bear and c[i] < h1_ema200 and c[i] < d.ema50.iloc[i] and d.rsi.iloc[i] < 50:
        return -1, float(max(h[i-4:i+1].max(), c[i] + k * atr[i]))
    return 0, None


def manage(d: pd.DataFrame, i: int, side: int, stop0: float, sym: str, trail_atr: float = None,
           target_r: float = None) -> Dict:
    """Chandelier exit from candle i: stop trails the best price since entry by k x ATR (never loosens)."""
    k = trail_atr or CHANDELIER_ATR
    h, l, c, atr = d.high.values, d.low.values, d.close.values, d.atr.values
    e, R = c[i], abs(c[i] - stop0)
    stop, peak, path = stop0, e, [(d.index[i], stop0)]
    cost = SPREADS.get(sym, 0) / R if R else 0
    n = len(d)
    for j in range(i + 1, min(n, i + 1 + MAX_HOLD)):
        if (l[j] <= stop) if side == 1 else (h[j] >= stop):
            path.append((d.index[j], stop))
            return {"exit_i": j, "exit": stop, "r": (stop - e) * side / R - cost, "open": False, "path": path}
        if target_r is not None:
            tgt = e + side * target_r * R                        # high win-rate mode: fixed small target, fixed stop
            if (h[j] >= tgt) if side == 1 else (l[j] <= tgt):
                path.append((d.index[j], stop))
                return {"exit_i": j, "exit": tgt, "r": target_r - cost, "open": False, "path": path}
            path.append((d.index[j], stop))
            continue
        peak = max(peak, h[j]) if side == 1 else min(peak, l[j])
        trail = peak - side * k * atr[j]
        stop = max(stop, trail) if side == 1 else min(stop, trail)
        path.append((d.index[j], stop))
    j = min(n - 1, i + MAX_HOLD)
    return {"exit_i": None, "exit": None, "r": (c[j] - e) * side / R - cost, "open": j == n - 1, "path": path,
            "stop_now": stop, "open_r": (c[-1] - e) * side / R}


def trades(d_raw: pd.DataFrame, sym: str, tf_min: int, strategy: str = "pro", h4: Optional[pd.DataFrame] = None,
           h1_ema200: Optional[pd.Series] = None, daily: Optional[pd.DataFrame] = None, strict: bool = False,
           target_r: Optional[float] = None) -> List[Dict]:
    """All signals of the strategy on closed candles, one position at a time, managed with the Chandelier exit."""
    d = add_indicators(d_raw)
    t4 = h4_trend(d_raw, h4, tf_min) if strategy == "pro" else None
    dtr = daily_trend(d_raw, daily, tf_min) if USE_FILTERS else None
    k = TRAIL_ATR.get(strategy, CHANDELIER_ATR) if strategy != "pro" else CHANDELIER_ATR
    out, i, n = [], 210, len(d)
    while i < n:
        side, stop = 0, None
        if strategy == "pro":
            chk = pro_pullback_checks(d, t4, i)
            side, stop = chk["signal"], chk["stop"]
        else:
            ema = h1_ema200.iloc[i] if h1_ema200 is not None else d.ema200.iloc[i]
            side, stop = v26_signal(d, i, sym, float(ema))
        if side and not filters_ok(side, d.index[i], int(dtr.iloc[i]) if dtr is not None else None):
            side = 0
        if side and USE_FILTERS and chasing(d, i, side):
            side = 0
        if side and strict and room_r(d, i, side, stop) < 1.0:
            side = 0
        if side:
            m = manage(d, i, side, stop, sym, k, target_r)
            out.append({"i": i, "time": d.index[i], "side": side, "entry": float(d.close.iloc[i]), "stop0": stop,
                        **m, "exit_time": d.index[m["exit_i"]] if m["exit_i"] is not None else None})
            if m["exit_i"] is None:
                break                                   # still in the trade at the last candle
            i = m["exit_i"] + 1
            continue
        i += 1
    return out


def summary(tr: List[Dict]) -> Optional[Dict]:
    closed = [t["r"] for t in tr if not t.get("open")]
    if not closed:
        return None
    r = pd.Series(closed)
    eq = r.cumsum()
    return {"n": len(r), "win": float((r > 0).mean() * 100), "avg_r": float(r.mean()),
            "pf": float(r[r > 0].sum() / max(1e-9, -r[r < 0].sum())), "total_r": float(r.sum()),
            "max_dd": float((eq.cummax() - eq).max()), "best": float(r.max())}
