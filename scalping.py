"""Intraday scalping engine (M5/M15): sessions, VWAP, key levels, structure, liquidity sweeps, graded setups.

The trading day rolls at 17:00 New York time (the FX rollover), like a broker's daily candle.
"""
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from config import INSTRUMENTS, SPREADS
from technical import add_indicators, fair_value_gaps

NY = "America/New_York"

# Execution parameters (validated with backtest.py - change them there first, not by feel)
# 2026-10-22 sweep on XAUUSD/EURUSD/USDJPY/GBPUSD M5: wider stops beat 0.15/0.5/1.2 on all four.
PARAMS = {"stop_buffer_atr": 0.5, "min_stop_atr": 1.5, "tp1_min_r": 1.0}
ENGINE_VERSION = 4   # bump when setup logic or levels change: saved backtests from older engines are discarded
ROUND_STEP = {"XAUUSD": 10.0, "BTCUSD": 500.0, "EURUSD": 0.0050, "USDJPY": 0.50,
              "GBPUSD": 0.0050, "NAS100": 100.0}


# ---------------------------------------------------------------- time & sessions

def trading_day(index: pd.DatetimeIndex) -> np.ndarray:
    return np.array((index.tz_convert(NY) + pd.Timedelta(hours=7)).date)


def session_info(now: pd.Timestamp, symbol: str) -> Dict:
    ny = now.tz_convert(NY)
    h = ny.hour + ny.minute / 60
    wd = ny.weekday()  # Mon=0
    closed = not symbol.startswith("BTC") and ((wd == 4 and h >= 17) or wd == 5 or (wd == 6 and h < 17))
    sessions = []
    if h >= 19 or h < 4:
        sessions.append("Asia")
    if 3 <= h < 12:
        sessions.append("London")
    if 8 <= h < 17:
        sessions.append("New York")
    if 2 <= h < 5:
        kz = "London open killzone"
    elif 7 <= h < 10:
        kz = "New York open killzone"
    elif 10 <= h < 12:
        kz = "London close"
    else:
        kz = None
    if closed:
        quality = "market closed"
    elif kz in ("London open killzone", "New York open killzone"):
        quality = "prime"
    elif "London" in sessions or "New York" in sessions:
        quality = "active"
    else:
        quality = "slow (Asia / late NY)"
    return {"ny_time": f"{ny:%H:%M} NY", "sessions": sessions or ["between sessions"],
            "killzone": kz, "quality": quality, "closed": closed}


# ---------------------------------------------------------------- VWAP & levels

def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    day = trading_day(df.index)
    tp = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].where(df["volume"] > 0, np.nan)
    if vol.isna().mean() > 0.5:            # feeds without volume: equal weights
        vol = pd.Series(1.0, index=df.index)
    vol = vol.fillna(vol.median())
    cv = vol.groupby(day).cumsum()
    vwap = (tp * vol).groupby(day).cumsum() / cv
    sd = np.sqrt(((tp - vwap) ** 2 * vol).groupby(day).cumsum() / cv)
    df["vwap"] = vwap
    for k in (1, 2):
        df[f"vwap_up{k}"] = vwap + k * sd
        df[f"vwap_lo{k}"] = vwap - k * sd
    df["vwap_sd"] = sd
    return df


def volume_profile(bars: pd.DataFrame, bins: int = 48) -> Optional[Dict[str, float]]:
    """Session volume profile: POC (most traded price) and the 70% value area (VAH / VAL).

    Each candle's (tick) volume is spread evenly across its high-low range.
    """
    if len(bars) < 12:
        return None
    lo, hi = float(bars["low"].min()), float(bars["high"].max())
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    mids = (edges[:-1] + edges[1:]) / 2
    vol = bars["volume"].to_numpy(dtype=float)
    if np.nanmean(vol > 0) < 0.5:
        vol = np.ones(len(bars))
    prof = np.zeros(bins)
    for h, l, v in zip(bars["high"].to_numpy(), bars["low"].to_numpy(), vol):
        a, b = np.searchsorted(edges, l, "right") - 1, np.searchsorted(edges, h, "left")
        a, b = max(0, a), min(bins, max(b, a + 1))
        prof[a:b] += v / (b - a)
    poc = int(prof.argmax())
    total, lo_i, hi_i, acc = prof.sum(), poc, poc, prof[poc]
    while acc < 0.7 * total and (lo_i > 0 or hi_i < bins - 1):
        down = prof[lo_i - 1] if lo_i > 0 else -1
        up = prof[hi_i + 1] if hi_i < bins - 1 else -1
        if up >= down:
            hi_i += 1; acc += prof[hi_i]
        else:
            lo_i -= 1; acc += prof[lo_i]
    return {"POC": float(mids[poc]), "VAH": float(edges[hi_i + 1]), "VAL": float(edges[lo_i])}


def key_levels(df: pd.DataFrame, symbol: str) -> Dict[str, float]:
    day = trading_day(df.index)
    days = sorted(set(day))
    today = df[day == days[-1]]
    lv: Dict[str, float] = {}
    if len(days) > 1:
        prev = df[day == days[-2]]
        lv.update(PDH=prev["high"].max(), PDL=prev["low"].min(), PDC=prev["close"].iloc[-1])
    lv["Day open"] = today["open"].iloc[0]
    if len(days) > 1:
        vp_prev = volume_profile(df[day == days[-2]])
        if vp_prev:
            lv.update({"pPOC": vp_prev["POC"], "pVAH": vp_prev["VAH"], "pVAL": vp_prev["VAL"]})
    vp = volume_profile(today)
    if vp:
        lv.update(vp)
    ny_h = today.index.tz_convert(NY).hour
    asia = today[(ny_h >= 17) | (ny_h < 2)]
    if len(asia) >= 3:
        lv["Asia high"], lv["Asia low"] = asia["high"].max(), asia["low"].min()
    if len(today) > 1:
        lv["Day high"], lv["Day low"] = today["high"].iloc[:-1].max(), today["low"].iloc[:-1].min()
    price, step = df["close"].iloc[-1], ROUND_STEP[symbol]
    base = np.floor(price / step) * step
    lv["Round below"], lv["Round above"] = base, base + step
    return {k: float(v) for k, v in lv.items()}


# ---------------------------------------------------------------- structure

def structure_events(df: pd.DataFrame, k: int = 3) -> List[Dict]:
    """BOS / CHoCH from fractal swings (k bars each side), in time order."""
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    n = len(df)
    swing_hi = {i + k: h[i] for i in range(k, n - k) if h[i] == h[i - k:i + k + 1].max()}
    swing_lo = {i + k: l[i] for i in range(k, n - k) if l[i] == l[i - k:i + k + 1].min()}
    last_hi = last_lo = None
    trend, events = None, []
    for i in range(n):
        if i in swing_hi:
            last_hi = [swing_hi[i], False]
        if i in swing_lo:
            last_lo = [swing_lo[i], False]
        if last_hi and not last_hi[1] and c[i] > last_hi[0]:
            events.append({"i": i, "time": df.index[i], "dir": 1, "level": last_hi[0],
                           "type": "CHoCH" if trend == -1 else "BOS"})
            last_hi[1], trend = True, 1
        if last_lo and not last_lo[1] and c[i] < last_lo[0]:
            events.append({"i": i, "time": df.index[i], "dir": -1, "level": last_lo[0],
                           "type": "CHoCH" if trend == 1 else "BOS"})
            last_lo[1], trend = True, -1
    return events


def liquidity_sweeps(df: pd.DataFrame, levels: Dict[str, float], atr: float, lookback: int = 6) -> List[Dict]:
    """A wick through a liquidity pool that closes back inside = stop hunt."""
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    n = len(df)
    # (name, level, kind): stops rest above highs ("hi"), below lows ("lo"); opens/closes act as both
    kind_of = {"PDH": "hi", "Asia high": "hi", "PDL": "lo", "Asia low": "lo"}
    pools = [(name, lvl, kind_of.get(name, "both")) for name, lvl in levels.items()
             if not name.startswith(("Round", "Day high", "Day low", "POC", "VAH", "VAL", "pPOC", "pVAH", "pVAL"))]
    # recent swing highs/lows (formed at least 3 bars before the sweep candle)
    for i in range(max(3, n - 60), n - lookback - 2):
        if h[i] == h[i - 3:i + 4].max():
            pools.append(("swing high", h[i], "hi"))
        if l[i] == l[i - 3:i + 4].min():
            pools.append(("swing low", l[i], "lo"))
    out = []
    for j in range(n - lookback, n):
        for name, lvl, kind in pools:
            if kind != "lo" and h[j] > lvl + 0.05 * atr and c[j] < lvl and h[j - 1] <= lvl + 0.5 * atr:
                out.append({"i": j, "time": df.index[j], "side": "buy-side", "dir": -1,
                            "level": lvl, "name": name, "extreme": h[j]})
            if kind != "hi" and l[j] < lvl - 0.05 * atr and c[j] > lvl and l[j - 1] >= lvl - 0.5 * atr:
                out.append({"i": j, "time": df.index[j], "side": "sell-side", "dir": 1,
                            "level": lvl, "name": name, "extreme": l[j]})
    named = [s for s in out if s["name"] not in ("swing high", "swing low")]
    return sorted(named or out, key=lambda s: s["i"])


# ---------------------------------------------------------------- setups

@dataclass
class Setup:
    name: str
    direction: int                  # +1 long, -1 short
    order_type: str                 # MARKET / BUY_LIMIT / SELL_LIMIT
    entry: float
    stop: float
    tp1: float
    tp2: float
    tp3: float
    trigger: str
    points: int = 0
    grade: str = "C"
    reasons: List[str] = field(default_factory=list)
    valid_minutes: int = 45

    @property
    def side(self) -> str:
        return "LONG" if self.direction == 1 else "SHORT"

    def rr(self, tp: float) -> float:
        return abs(tp - self.entry) / (abs(self.entry - self.stop) or 1e-9)


def _intermarket_read(df: pd.DataFrame, inter) -> Optional[Dict]:
    """What the driver (DXY, yields...) says about this instrument right now."""
    if not inter:
        return None
    name, sign, idf = inter
    joined = pd.concat([df["close"].rename("a"), idf["close"].rename("b")], axis=1, join="inner").dropna()
    if len(joined) < 60:
        return None
    ret = joined.pct_change().dropna().tail(150)
    corr = float(ret["a"].corr(ret["b"]))
    b = joined["b"]
    hourly = (b / b.shift(12) - 1) * 100                        # rolling 1-hour % change on M5
    chg = float(hourly.iloc[-1])
    z = chg / (float(hourly.tail(300).std()) or 1e-9)           # move vs the driver's normal hourly noise
    driver_dir = int(np.sign(chg)) if abs(z) >= 0.5 else 0
    holds = corr * sign > 0.15                                  # relationship actually present lately
    return {"name": name, "sign": sign, "chg_pct": chg, "z": z, "corr": corr, "holds": holds,
            "bias": driver_dir * sign if holds else 0}


class Context:
    """Everything the setup detectors need, computed once."""

    def __init__(self, df: pd.DataFrame, symbol: str, htf_bias: float, now: Optional[pd.Timestamp] = None,
                 daily: Optional[pd.DataFrame] = None, intermarket=None, extra: Optional[Dict] = None):
        self.symbol = symbol
        self.inst = INSTRUMENTS[symbol]
        self.df = add_vwap(add_indicators(df))
        last = self.df.iloc[-1]
        self.price, self.atr = float(last.close), float(last.atr)
        self.spread = SPREADS.get(symbol, 0.0)
        self.htf_bias = htf_bias
        self.now = now or pd.Timestamp.now(tz="UTC")
        self.session = session_info(self.now, symbol)
        self.levels = key_levels(self.df, symbol)
        self.events = structure_events(self.df)
        self.sweeps = liquidity_sweeps(self.df, self.levels, self.atr)
        self.fvgs = fair_value_gaps(self.df, lookback=40, min_atr=0.25)
        atr_hist = self.df["atr"].tail(300)
        self.atr_pct = float((atr_hist < self.atr).mean() * 100)
        self.vwap, self.vwap_sd = float(last.vwap), float(last.vwap_sd) or self.atr
        self.vwap_z = (self.price - self.vwap) / self.vwap_sd
        body = (self.df["close"] - self.df["open"]).tail(3)
        self.momentum = float(body.sum() / self.atr)
        self.adr = self.adr_used = None
        if daily is not None and len(daily) > 15:
            self.adr = float((daily["high"] - daily["low"]).iloc[-15:-1].mean())
            day_rng = self.levels.get("Day high", self.price) - self.levels.get("Day low", self.price)
            day_rng = max(day_rng, self.df["high"].iloc[-1] - self.df["low"].iloc[-1])
            self.adr_used = float(100 * day_rng / self.adr) if self.adr else None
        self.inter = _intermarket_read(self.df, intermarket)
        self.extra = extra or {}          # higher-timeframe values for the user's strategies

    # level map for targets & confluence
    def all_levels(self) -> List[tuple]:
        lv = [(k, v) for k, v in self.levels.items()]
        last = self.df.iloc[-1]
        lv += [("VWAP", self.vwap), ("VWAP +1σ", last.vwap_up1), ("VWAP -1σ", last.vwap_lo1),
               ("VWAP +2σ", last.vwap_up2), ("VWAP -2σ", last.vwap_lo2)]
        return [(k, float(v)) for k, v in lv]

    def near_level(self, price: float, tol_atr: float = 0.3) -> Optional[str]:
        for k, v in self.all_levels():
            if abs(price - v) <= tol_atr * self.atr:
                return k
        return None


def _build(ctx: Context, name: str, d: int, entry: float, stop_struct: float, trigger: str,
           market: bool, reasons: List[str]) -> Setup:
    a = ctx.atr
    stop = stop_struct - d * (PARAMS["stop_buffer_atr"] * a + ctx.spread)
    if abs(entry - stop) < PARAMS["min_stop_atr"] * a:      # never tighter than this many ATRs
        stop = entry - d * PARAMS["min_stop_atr"] * a
    risk = abs(entry - stop)
    cands = sorted({v for _, v in ctx.all_levels() if (v - entry) * d >= PARAMS["tp1_min_r"] * risk},
                   key=lambda v: abs(v - entry))
    tp1 = cands[0] if cands else entry + d * 1.5 * risk
    later = [v for v in cands if (v - tp1) * d >= 0.5 * risk]
    tp2 = later[0] if later else entry + d * max(2.5 * risk, abs(tp1 - entry) + risk)
    tp3 = entry + d * max(4.0 * risk, abs(tp2 - entry) + risk)
    rnd = lambda x: round(float(x), ctx.inst.digits)
    order = "MARKET" if market else ("BUY_LIMIT" if d == 1 else "SELL_LIMIT")
    return Setup(name, d, order, rnd(entry), rnd(stop), rnd(tp1), rnd(tp2), rnd(tp3), trigger, reasons=list(reasons))


def _sweep_reversal(ctx: Context) -> List[Setup]:
    out = []
    if not ctx.sweeps:
        return out
    s = ctx.sweeps[-1]
    d, f = s["dir"], ctx.inst.digits
    after = [e for e in ctx.events if e["i"] >= s["i"] - 1 and e["dir"] == d]
    last = ctx.df.iloc[-1]
    rejection = (last.close - last.open) * d > 0.4 * ctx.atr
    reasons = [f"{s['side']} liquidity swept at {s['name']} {s['level']:.{f}f} ({s['time']:%H:%M} UTC)"]
    if after:
        reasons.append(f"{after[-1]['type']} confirmed at {after[-1]['level']:.{f}f}")
    if rejection:
        reasons.append("strong rejection candle")
    confirmed = bool(after) or rejection
    ran = (ctx.price - s["level"]) * d
    market = confirmed and ran < 1.0 * ctx.atr
    entry = ctx.price if market else s["level"] + d * 0.1 * ctx.atr
    trig = (f"{'Sell' if d == -1 else 'Buy'} {'now' if market else 'on retest of ' + format(s['level'], f'.{f}f')}: "
            f"stop hunt beyond {s['name']}, " + ("structure shifted." if after else
                                                  "wait for M5 CHoCH before entering." if not confirmed else "rejection confirmed."))
    st = _build(ctx, "Liquidity sweep reversal", d, entry, s["extreme"], trig, market, reasons)
    st.points += 2 if after else (1 if rejection else 0)
    out.append(st)
    return out


def _vwap_pullback(ctx: Context) -> List[Setup]:
    d = int(np.sign(ctx.htf_bias))
    if d == 0 or abs(ctx.htf_bias) < 15:
        return []
    tail = ctx.df.tail(20)
    side_share = ((tail["close"] - tail["vwap"]) * d > 0).mean()
    touched = (((tail["low"] if d == 1 else tail["high"]).tail(4) - tail["vwap"].tail(4)) * d).min() <= 0.3 * ctx.atr
    if side_share < 0.6 or (ctx.price - ctx.vwap) * d < -0.2 * ctx.atr:
        return []
    market = touched and abs(ctx.price - ctx.vwap) <= 0.5 * ctx.atr
    entry = ctx.price if market else ctx.vwap + d * 0.1 * ctx.atr
    swing = tail["low"].tail(6).min() if d == 1 else tail["high"].tail(6).max()
    stop_struct = min(swing, ctx.vwap - ctx.vwap_sd) if d == 1 else max(swing, ctx.vwap + ctx.vwap_sd)
    reasons = [f"price held {'above' if d == 1 else 'below'} VWAP {side_share * 100:.0f}% of last 20 bars",
               f"higher-timeframe bias {ctx.htf_bias:+.0f}"]
    trig = (f"{'Buy' if d == 1 else 'Sell'} {'now - VWAP retest holding' if market else 'limit at VWAP ' + format(ctx.vwap, f'.{ctx.inst.digits}f')}; "
            f"cancel if an M5 candle closes through VWAP -1σ.")
    st = _build(ctx, "VWAP pullback with trend", d, entry, stop_struct, trig, market, reasons)
    st.points += 1 if touched else 0
    return [st]


def _break_retest(ctx: Context) -> List[Setup]:
    n = len(ctx.df)
    recent = [e for e in ctx.events if e["i"] >= n - 20]
    if not recent:
        return []
    e = recent[-1]
    d, lvl, f = e["dir"], e["level"], ctx.inst.digits
    if (ctx.price - lvl) * d < -0.1 * ctx.atr or (ctx.price - lvl) * d > 1.2 * ctx.atr:
        return []
    market = abs(ctx.price - lvl) <= 0.2 * ctx.atr
    entry = ctx.price if market else lvl + d * 0.05 * ctx.atr
    reasons = [f"M5 {e['type']} {'up' if d == 1 else 'down'} through {lvl:.{f}f} at {e['time']:%H:%M} UTC"]
    trig = (f"{'Buy' if d == 1 else 'Sell'} {'now' if market else 'limit'} on retest of broken level {lvl:.{f}f}; "
            f"invalid if price closes back {'below' if d == 1 else 'above'} it.")
    st = _build(ctx, f"{e['type']} break & retest", d, entry, lvl - d * 0.6 * ctx.atr, trig, market, reasons)
    st.points += 1 if e["type"] == "BOS" else 0
    return [st]


def _range_breakout(ctx: Context) -> List[Setup]:
    if "Asia high" not in ctx.levels or not ctx.session["killzone"]:
        return []
    hi, lo, f = ctx.levels["Asia high"], ctx.levels["Asia low"], ctx.inst.digits
    height = hi - lo
    if not (0.8 * ctx.atr <= height <= 6 * ctx.atr):
        return []
    tail = ctx.df.tail(12)
    for d, edge in ((1, hi), (-1, lo)):
        broke = ((tail["close"] - edge) * d > 0.1 * ctx.atr).any()
        if broke and (ctx.price - edge) * d > -0.2 * ctx.atr and (ctx.price - edge) * d < height:
            market = abs(ctx.price - edge) <= 0.25 * ctx.atr
            entry = ctx.price if market else edge + d * 0.05 * ctx.atr
            st = _build(ctx, "Asian range breakout", d, entry, edge - d * min(0.5 * height, 1.0 * ctx.atr),
                        f"{'Buy' if d == 1 else 'Sell'} the retest of the Asian {'high' if d == 1 else 'low'} {edge:.{f}f} "
                        f"during {ctx.session['killzone']}; measured move {edge + d * height:.{f}f}.",
                        market, [f"Asian range {lo:.{f}f}-{hi:.{f}f} broken in {ctx.session['killzone']}"])
            return [st]
    return []


def _fvg_retest(ctx: Context) -> List[Setup]:
    d = int(np.sign(ctx.htf_bias))
    f = ctx.inst.digits
    for g in reversed(ctx.fvgs):
        gd = 1 if g["type"] == "bullish" else -1
        if gd != d:
            continue
        edge = g["top"] if d == 1 else g["bottom"]
        dist = (ctx.price - edge) * d
        if 0 <= dist <= 1.2 * ctx.atr:
            mid = (g["top"] + g["bottom"]) / 2
            st = _build(ctx, "Fair value gap retest", d, mid, g["bottom"] if d == 1 else g["top"],
                        f"{'Buy' if d == 1 else 'Sell'} limit in the M5 {g['type']} FVG "
                        f"{g['bottom']:.{f}f}-{g['top']:.{f}f} (midpoint {mid:.{f}f}).",
                        False, [f"unfilled {g['type']} imbalance from {g['time']:%H:%M} UTC in trend direction"])
            return [st]
    return []


def _grade(ctx: Context, s: Setup, news_block: bool) -> Setup:
    d = s.direction
    if ctx.htf_bias * d > 15:
        s.points += 2; s.reasons.append("aligned with M15/H1 bias")
    elif ctx.htf_bias * d < -40:
        s.points -= 1 if s.name.startswith("Liquidity") else 2
        s.reasons.append("against higher-timeframe bias")
    q = ctx.session["quality"]
    if q == "prime":
        s.points += 1; s.reasons.append(ctx.session["killzone"])
    elif q.startswith("slow"):
        s.points -= 1; s.reasons.append("slow session - expect less follow-through")
    lvl = ctx.near_level(s.entry)
    if lvl:
        s.points += 1; s.reasons.append(f"entry at confluence: {lvl}")
    if s.rr(s.tp2) >= 2.0:
        s.points += 1
    if ctx.atr_pct < 15:
        s.points -= 1; s.reasons.append("volatility very low")
    cost_r = ctx.spread / (abs(s.entry - s.stop) or 1e-9)
    if cost_r > 0.15:
        s.points -= 1; s.reasons.append(f"spread costs {cost_r:.2f}R")
    im = ctx.inter
    if im and im["bias"]:
        if im["bias"] == d:
            s.points += 1; s.reasons.append(f"{im['name']} confirms ({im['chg_pct']:+.2f}% last hour)")
        else:
            s.points -= 1; s.reasons.append(f"{im['name']} disagrees ({im['chg_pct']:+.2f}% last hour)")
    if ctx.adr_used is not None and ctx.adr_used > 90 and not s.name.startswith("Liquidity"):
        s.points -= 1; s.reasons.append(f"{ctx.adr_used:.0f}% of the average daily range already used")
    if news_block:
        s.points -= 3; s.reasons.append("high-impact news within 30 min")
    if ctx.session["closed"]:
        s.points -= 5
    s.grade = "A+" if s.points >= 5 else "A" if s.points == 4 else "B" if s.points == 3 else "C"
    s.valid_minutes = 30 if s.order_type == "MARKET" else 60
    return s


def find_setups(ctx: Context, news_block: bool = False) -> List[Setup]:
    found: List[Setup] = []
    from userstrats import pro_pullback, signal_v26
    for det in (_sweep_reversal, _vwap_pullback, _break_retest, _range_breakout, _fvg_retest, pro_pullback, signal_v26):
        found += det(ctx)
    return sorted((_grade(ctx, s, news_block) for s in found), key=lambda s: -s.points)


# ---------------------------------------------------------------- text for the AI / UI

def context_text(ctx: Context, setups: List[Setup]) -> str:
    f = ctx.inst.digits
    fx = lambda v: f"{v:.{f}f}"
    s = ctx.session
    lines = [f"Session: {', '.join(s['sessions'])} | {s['ny_time']} | killzone: {s['killzone'] or 'none'} | quality: {s['quality']}",
             f"Price {fx(ctx.price)} | M5 ATR {fx(ctx.atr)} (percentile {ctx.atr_pct:.0f}) | "
             f"VWAP {fx(ctx.vwap)} (price at {ctx.vwap_z:+.1f}σ) | last-3-bar momentum {ctx.momentum:+.1f} ATR | "
             f"typical cost {fx(ctx.spread)}",
             "Key levels: " + ", ".join(f"{k} {fx(v)}" for k, v in ctx.levels.items())]
    if ctx.adr:
        lines.append(f"Average daily range (14d) {fx(ctx.adr)}; today has used {ctx.adr_used:.0f}% of it")
    if ctx.inter:
        im = ctx.inter
        lines.append(f"Intermarket: {im['name']} {im['chg_pct']:+.2f}% last hour ({im['z']:+.1f} sd), M5 return correlation {im['corr']:+.2f} "
                     f"({'relationship holding' if im['holds'] else 'relationship weak today'}); "
                     f"implied bias for this instrument: {['bearish', 'neutral', 'bullish'][im['bias'] + 1]}")
    if ctx.events:
        lines.append("Recent structure: " + "; ".join(
            f"{e['type']} {'up' if e['dir'] == 1 else 'down'} @{fx(e['level'])} {e['time']:%H:%M}" for e in ctx.events[-4:]))
    if ctx.sweeps:
        lines.append("Liquidity sweeps: " + "; ".join(
            f"{w['side']} at {w['name']} {fx(w['level'])} (wick {fx(w['extreme'])}) {w['time']:%H:%M}" for w in ctx.sweeps[-3:]))
    lines.append("Last 12 M5 candles (UTC time O H L C):")
    for t, r in ctx.df.tail(12).iterrows():
        lines.append(f"  {t:%H:%M} {fx(r.open)} {fx(r.high)} {fx(r.low)} {fx(r.close)}")
    lines.append("Setups detected by the engine (best first):")
    for x in setups:
        lines.append(f"- [{x.grade}] {x.side} {x.name}: {x.order_type} {fx(x.entry)} SL {fx(x.stop)} "
                     f"TP {fx(x.tp1)}/{fx(x.tp2)}/{fx(x.tp3)} (TP2 {x.rr(x.tp2):.1f}R). {x.trigger} "
                     f"Reasons: {'; '.join(x.reasons)}")
    if not setups:
        lines.append("- none")
    return "\n".join(lines)


def setup_to_signal(s: Setup, ctx: Context, decision: Optional[str] = None) -> Dict:
    return {
        "decision": decision or s.side, "confidence": min(90, 40 + 10 * s.points), "order_type": s.order_type,
        "setup": s.name, "grade": s.grade, "entry": s.entry, "stop_loss": s.stop,
        "tp1": s.tp1, "tp2": s.tp2, "tp3": s.tp3, "trigger": s.trigger,
        "valid_minutes": s.valid_minutes, "reasons": s.reasons,
        "management": "Take 50% at TP1 and move stop to break-even; trail the rest behind M5 swings to TP2/TP3.",
    }


def as_dicts(setups: List[Setup]) -> List[Dict]:
    return [{**asdict(s), "side": s.side, "rr_tp2": round(s.rr(s.tp2), 2)} for s in setups]
