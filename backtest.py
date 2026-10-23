"""Walk-forward backtest of the scalping setups on historical candles (no look-ahead).

At every step the engine only sees candles up to that bar. Each new setup is simulated forward:
limit orders must actually be touched within their validity window, the stop wins if stop and
target fall inside the same candle, the spread is charged, and the trade is managed like the
ticket says: half off at TP1, stop to break-even, rest to TP2, flat after `horizon` bars.
"""
import json
import os
import time
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from config import SPREADS
from scalping import ENGINE_VERSION, PARAMS, Context, find_setups
from technical import adx, ema, supertrend

CACHE_DIR = os.path.join(os.path.dirname(__file__), "backtest_cache")


# ---------------------------------------------------------------- higher-timeframe bias without look-ahead

def _fast_score(df: pd.DataFrame) -> pd.Series:
    c = df["close"]
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    stack = np.where((e20 > e50) & (e50 > e200), 1.0, np.where((e20 < e50) & (e50 < e200), -1.0, 0.5 * np.sign(e20 - e50)))
    macd = ema(c, 12) - ema(c, 26)
    hist = macd - ema(macd, 9)
    a, pdi, mdi = adx(df)
    dmi = np.where(a > 22, 1.0, 0.4) * np.sign(pdi - mdi)
    st = supertrend(df)
    score = (2 * stack + 0.5 * np.sign(c - e200) + 1.5 * np.sign(hist) + 1.5 * st + 1.5 * dmi) / 7.0
    return pd.Series(100 * score, index=df.index)


def htf_bias_series(df: pd.DataFrame) -> pd.Series:
    """M15 + H1 bias built from the execution candles, only using bars that had closed."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = []
    for rule, w in (("15min", 1.0), ("1h", 2.0)):
        r = df.resample(rule, label="right", closed="right").agg(agg).dropna()
        sc = _fast_score(r).reindex(df.index, method="ffill")   # right-labelled = known at bar close
        out.append((sc, w))
    return sum(s * w for s, w in out) / sum(w for _, w in out)


# ---------------------------------------------------------------- trade simulation

def simulate(df: pd.DataFrame, i: int, s, spread: float, horizon: int, bar_minutes: int) -> Dict:
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    d, entry, stop, tp1, tp2 = s.direction, s.entry, s.stop, s.tp1, s.tp2
    risk = abs(entry - stop) or 1e-9
    j = i + 1
    if s.order_type != "MARKET":
        wait = max(1, int(s.valid_minutes / bar_minutes))
        while j < min(len(df), i + 1 + wait):
            if (l[j] <= entry) if d == 1 else (h[j] >= entry):
                break
            j += 1
        else:
            return {"filled": False}
        start = j            # fill bar: only stops can be hit on it conservatively
    else:
        entry = c[i]
        risk = abs(entry - stop) or 1e-9
        start = i + 1
    cost = spread / risk
    half_done, r_total, sl = False, 0.0, stop
    end = min(len(df), start + horizon)
    for k in range(start, end):
        if (l[k] <= sl) if d == 1 else (h[k] >= sl):
            r_total += (0.5 if half_done else 1.0) * ((sl - entry) * d) / risk
            return {"filled": True, "r": round(r_total - cost, 3), "outcome": "TP1→BE" if half_done else "SL", "bars": k - i}
        if k == start and s.order_type != "MARKET":
            continue
        if not half_done and ((h[k] >= tp1) if d == 1 else (l[k] <= tp1)):
            r_total += 0.5 * abs(tp1 - entry) / risk
            half_done, sl = True, entry
        if half_done and ((h[k] >= tp2) if d == 1 else (l[k] <= tp2)):
            r_total += 0.5 * abs(tp2 - entry) / risk
            return {"filled": True, "r": round(r_total - cost, 3), "outcome": "TP2", "bars": k - i}
    last = c[end - 1]
    r_total += (0.5 if half_done else 1.0) * ((last - entry) * d) / risk
    return {"filled": True, "r": round(r_total - cost, 3), "outcome": "time exit", "bars": end - 1 - i}


def simulate_exits(df: pd.DataFrame, i: int, s, spread: float, horizon: int, bar_minutes: int) -> Dict:
    """R of the same trade under simpler exits: all at 1R, all at TP1, all at TP2 (stop never moved)."""
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    d, entry, stop = s.direction, s.entry, s.stop
    j = i + 1
    if s.order_type != "MARKET":
        wait = max(1, int(s.valid_minutes / bar_minutes))
        while j < min(len(df), i + 1 + wait):
            if (l[j] <= entry) if d == 1 else (h[j] >= entry):
                break
            j += 1
        else:
            return {}
        start, skip_first = j, True
    else:
        entry, start, skip_first = c[i], i + 1, False
    risk = abs(entry - stop) or 1e-9
    cost = spread / risk
    end = min(len(df), start + horizon)
    out = {}
    for name, target in (("r_1r", entry + d * risk), ("r_tp1", s.tp1), ("r_tp2", s.tp2)):
        r = None
        for k in range(start, end):
            if (l[k] <= stop) if d == 1 else (h[k] >= stop):
                r = -1.0
                break
            if k == start and skip_first:
                continue
            if (h[k] >= target) if d == 1 else (l[k] <= target):
                r = abs(target - entry) / risk
                break
        if r is None:
            r = (c[end - 1] - entry) * d / risk
        out[name] = round(r - cost, 3)
    return out


# ---------------------------------------------------------------- walk-forward run

def run_backtest(df: pd.DataFrame, symbol: str, bar_minutes: int = 5, daily: Optional[pd.DataFrame] = None,
                 inter=None, window: int = 600, step: int = 3, horizon: int = 36, extra_df: Optional[pd.DataFrame] = None,
                 progress: Optional[Callable[[float], None]] = None) -> pd.DataFrame:
    bias = htf_bias_series(df)
    spread = SPREADS.get(symbol, 0.0)
    rows: List[Dict] = []
    last_seen: Dict[tuple, int] = {}
    idxs = range(window, len(df) - 2, step)
    for n, i in enumerate(idxs):
        sub = df.iloc[i - window:i + 1]
        t = sub.index[-1]
        b = bias.iloc[i]
        if np.isnan(b):
            continue
        dly = daily[daily.index <= t] if daily is not None else None
        im = None
        if inter:
            name, sign, idf = inter
            im = (name, sign, idf[idf.index <= t])
        try:
            ex = extra_df.loc[t].to_dict() if extra_df is not None and t in extra_df.index else None
            ctx = Context(sub, symbol, float(b), now=t, daily=dly, intermarket=im, extra=ex)
            setups = find_setups(ctx)
        except Exception:  # noqa: BLE001 - a malformed window should not stop the run
            continue
        for s in setups:
            k = (s.name, s.direction)
            if i - last_seen.get(k, -10_000) < 12:      # same idea still alive: don't count twice
                continue
            last_seen[k] = i
            res = simulate(df, i, s, spread, horizon, bar_minutes)
            if res.get("filled"):
                res.update(simulate_exits(df, i, s, spread, horizon, bar_minutes))
            d = s.direction
            rows.append({"time": t, "hour": t.hour, "setup": s.name, "side": s.side, "grade": s.grade, "points": s.points,
                         "order": s.order_type, "rr_tp2": round(s.rr(s.tp2), 2),
                         "session": ctx.session["quality"],
                         # context at signal time, signed so that positive = in favour of the trade
                         "f_htf": round(float(b) * d, 1),
                         "f_vwap": round(float(ctx.vwap_z) * d, 2),
                         "f_adr": round(float(ctx.adr_used), 0) if ctx.adr_used is not None else None,
                         "f_inter": (ctx.inter["bias"] * d) if ctx.inter else 0,
                         "f_atrpct": round(ctx.atr_pct, 0),
                         "f_mom": round(float(ctx.momentum) * d, 2),
                         "f_kz": bool(ctx.session["killzone"]),
                         "f_confirmed": any("confirmed" in x or "rejection" in x for x in s.reasons),
                         "f_confluence": any("confluence" in x for x in s.reasons),
                         **res})
        if progress and n % 10 == 0:
            progress(n / max(1, len(idxs)))
    return pd.DataFrame(rows)


def summarize(trades: pd.DataFrame, by: str) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    filled = trades[trades["filled"]]
    if filled.empty:
        return pd.DataFrame()
    g = filled.groupby(by)["r"]
    out = pd.DataFrame({
        "trades": g.size(),
        "win %": g.apply(lambda r: 100 * (r > 0).mean()).round(0),
        "avg R": g.mean().round(2),
        "total R": g.sum().round(1),
        "profit factor": g.apply(lambda r: round(r[r > 0].sum() / max(1e-9, -r[r < 0].sum()), 2)),
    })
    fills = trades.groupby(by)["filled"].mean().mul(100).round(0).rename("fill %")
    return out.join(fills).sort_values("avg R", ascending=False)


# ---------------------------------------------------------------- disk cache & edge lookup

def cache_path(symbol: str, tf: str) -> str:
    return os.path.join(CACHE_DIR, f"{symbol}_{tf}.json")


def save(symbol: str, tf: str, trades: pd.DataFrame, meta: Dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    t = trades.copy()
    t["time"] = t["time"].astype(str)
    with open(cache_path(symbol, tf), "w", encoding="utf-8") as fh:
        json.dump({"meta": {**meta, "saved": time.time(), "params": dict(PARAMS), "engine": ENGINE_VERSION}, "trades": t.to_dict("records")}, fh)


def load(symbol: str, tf: str):
    try:
        with open(cache_path(symbol, tf), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None, None
    if data["meta"].get("params") != PARAMS or data["meta"].get("engine") != ENGINE_VERSION:
        # engine changed since this run: stats no longer apply
        return None, {**data["meta"], "outdated": True}
    t = pd.DataFrame(data["trades"])
    if not t.empty:
        t["time"] = pd.to_datetime(t["time"], utc=True, format="ISO8601")
    return t, data["meta"]


def edge(trades: Optional[pd.DataFrame], setup_name: str) -> Optional[Dict]:
    """Historical stats for one setup type (needs at least 8 filled trades to say anything)."""
    if trades is None or trades.empty:
        return None
    f = trades[(trades["setup"] == setup_name) & (trades["filled"])]
    if len(f) < 8:
        return None
    return {"n": int(len(f)), "win": float(100 * (f["r"] > 0).mean()), "avg_r": float(f["r"].mean()),
            "pf": float(f.loc[f["r"] > 0, "r"].sum() / max(1e-9, -f.loc[f["r"] < 0, "r"].sum()))}


GRADE_ORDER = ["C", "B", "A", "A+"]


def evidence_cap(e: Optional[Dict]):
    """Highest grade the measured history allows, and why. None = no cap."""
    if not e:
        return "B", "not backtested on this market yet - capped at B"
    if e["n"] < 20:
        return "B", f"only {e['n']} backtest trades - capped at B"
    if e["avg_r"] <= -0.05:
        return "C", f"loses in backtest ({e['avg_r']:+.2f}R over {e['n']} trades) - no edge"
    if e["avg_r"] < 0.05:
        return "B", f"breakeven in backtest ({e['avg_r']:+.2f}R) - no clear edge"
    return None, f"positive backtest edge ({e['avg_r']:+.2f}R over {e['n']} trades)"


def cap_grade(grade: str, cap: Optional[str]) -> str:
    if cap is None or grade not in GRADE_ORDER:
        return grade
    return GRADE_ORDER[min(GRADE_ORDER.index(grade), GRADE_ORDER.index(cap))]


def hour_edge(trades: Optional[pd.DataFrame], hour: int) -> Optional[Dict]:
    """All setups combined at this UTC hour (needs 30+ trades)."""
    if trades is None or trades.empty or "hour" not in trades:
        return None
    f = trades[(trades["hour"] == hour) & trades["filled"]]
    if len(f) < 30:
        return None
    return {"n": int(len(f)), "avg_r": float(f["r"].mean()), "win": float(100 * (f["r"] > 0).mean())}


def apply_edge(setups, trades: Optional[pd.DataFrame], hour: Optional[int] = None):
    """Measured history overrides opinion: a setup can't grade above what its backtest supports."""
    for s in setups:
        e = edge(trades, s.name)
        s.edge = e
        cap, why = evidence_cap(e)
        if e and e["n"] >= 20 and e["avg_r"] >= 0.15:
            s.points += 1
            s.grade = "A+" if s.points >= 5 else "A" if s.points == 4 else "B" if s.points == 3 else "C"
        he = hour_edge(trades, hour) if hour is not None else None
        if he and he["avg_r"] <= -0.15:
            # out-of-sample study (Oct 2026): skipping weak hours was the only filter that stayed positive on unseen data
            s.reasons.append(f"{hour:02d}:00 UTC is historically weak ({he['avg_r']:+.2f}R over {he['n']} trades) - capped at B")
            cap = "B" if cap is None else cap_grade(cap, "B")
        capped = cap_grade(s.grade, cap)
        if capped != s.grade:
            s.reasons.append(why)
            s.grade = capped
        elif e:
            s.reasons.append(f"backtest {e['win']:.0f}% win, {e['avg_r']:+.2f}R avg over {e['n']} trades")
    return sorted(setups, key=lambda s: (-GRADE_ORDER.index(s.grade), -s.points))
