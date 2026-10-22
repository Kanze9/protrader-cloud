"""Technical analysis engine: indicators, structure, levels, patterns and a confluence score."""
from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np
import pandas as pd


# ---------------------------------------------------------------- indicators

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx(df: pd.DataFrame, n: int = 14):
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(df, n)
    pdi = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    mdi = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), pdi, mdi


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> pd.Series:
    """+1 bullish / -1 bearish."""
    a = atr(df, n)
    hl2 = (df["high"] + df["low"]) / 2
    upper = (hl2 + mult * a).to_numpy(copy=True)
    lower = (hl2 - mult * a).to_numpy(copy=True)
    close = df["close"].to_numpy()
    direction = np.ones(len(df))
    for i in range(1, len(df)):
        # bands only ratchet in the trend's favour
        if close[i - 1] <= upper[i - 1]:
            upper[i] = min(upper[i], upper[i - 1])
        if close[i - 1] >= lower[i - 1]:
            lower[i] = max(lower[i], lower[i - 1])
        if close[i] > upper[i - 1]:
            direction[i] = 1
        elif close[i] < lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
    return pd.Series(direction, index=df.index)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["close"]
    for n in (20, 50, 200):
        df[f"ema{n}"] = ema(c, n)
    df["rsi"] = rsi(c)
    macd = ema(c, 12) - ema(c, 26)
    df["macd"], df["macd_signal"] = macd, ema(macd, 9)
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    df["atr"] = atr(df)
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    df["bb_mid"], df["bb_up"], df["bb_lo"] = mid, mid + 2 * sd, mid - 2 * sd
    df["adx"], df["pdi"], df["mdi"] = adx(df)
    lo14, hi14 = df["low"].rolling(14).min(), df["high"].rolling(14).max()
    df["stoch_k"] = 100 * (c - lo14) / (hi14 - lo14).replace(0, np.nan)
    df["stoch_d"] = df["stoch_k"].rolling(3).mean()
    df["supertrend"] = supertrend(df)
    return df


# ---------------------------------------------------------------- structure

def swing_points(df: pd.DataFrame, left: int = 5, right: int = 5):
    """Fractal swing highs / lows (confirmed only)."""
    highs, lows = [], []
    h, l = df["high"].values, df["low"].values
    for i in range(left, len(df) - right):
        if h[i] == max(h[i - left:i + right + 1]):
            highs.append((df.index[i], h[i]))
        if l[i] == min(l[i - left:i + right + 1]):
            lows.append((df.index[i], l[i]))
    return highs, lows


def market_structure(highs, lows) -> str:
    if len(highs) < 2 or len(lows) < 2:
        return "undefined"
    hh = highs[-1][1] > highs[-2][1]
    hl = lows[-1][1] > lows[-2][1]
    if hh and hl:
        return "bullish (HH + HL)"
    if not hh and not hl:
        return "bearish (LH + LL)"
    return "ranging / transition"


def cluster_levels(prices: List[float], tol: float) -> List[Dict]:
    """Merge nearby swing prices into S/R zones, weighted by touches."""
    zones = []
    for p in sorted(prices):
        if zones and abs(p - zones[-1]["price"]) <= tol:
            z = zones[-1]
            z["price"] = (z["price"] * z["touches"] + p) / (z["touches"] + 1)
            z["touches"] += 1
        else:
            zones.append({"price": p, "touches": 1})
    return zones


def fair_value_gaps(df: pd.DataFrame, lookback: int = 60, min_atr: float = 0.3) -> List[Dict]:
    """Unfilled 3-candle imbalances (SMC fair value gaps)."""
    out = []
    sub = df.tail(lookback)
    a = df["atr"].iloc[-1]
    for i in range(2, len(sub)):
        h0, l0 = sub["high"].iloc[i - 2], sub["low"].iloc[i - 2]
        h2, l2 = sub["high"].iloc[i], sub["low"].iloc[i]
        after = sub.iloc[i + 1:]
        if l2 > h0 and (l2 - h0) >= min_atr * a:
            if after.empty or after["low"].min() > h0:
                out.append({"type": "bullish", "top": l2, "bottom": h0, "time": sub.index[i]})
        if h2 < l0 and (l0 - h2) >= min_atr * a:
            if after.empty or after["high"].max() < l0:
                out.append({"type": "bearish", "top": l0, "bottom": h2, "time": sub.index[i]})
    return out[-4:]


def candle_patterns(df: pd.DataFrame) -> List[str]:
    out = []
    o, h, l, c = (df[k].iloc[-3:].values for k in ("open", "high", "low", "close"))
    body = abs(c[-1] - o[-1])
    rng = h[-1] - l[-1] or 1e-9
    upper_wick = h[-1] - max(o[-1], c[-1])
    lower_wick = min(o[-1], c[-1]) - l[-1]
    if c[-1] > o[-1] and c[-2] < o[-2] and c[-1] >= o[-2] and o[-1] <= c[-2]:
        out.append("bullish engulfing")
    if c[-1] < o[-1] and c[-2] > o[-2] and c[-1] <= o[-2] and o[-1] >= c[-2]:
        out.append("bearish engulfing")
    if lower_wick > 2 * body and upper_wick < body and body / rng < 0.35:
        out.append("hammer / bullish pin bar")
    if upper_wick > 2 * body and lower_wick < body and body / rng < 0.35:
        out.append("shooting star / bearish pin bar")
    if body / rng < 0.1:
        out.append("doji (indecision)")
    if h[-1] < h[-2] and l[-1] > l[-2]:
        out.append("inside bar (compression)")
    return out


def rsi_divergence(df: pd.DataFrame, highs, lows) -> str:
    if len(highs) >= 2:
        (t1, p1), (t2, p2) = highs[-2], highs[-1]
        if p2 > p1 and df.loc[t2, "rsi"] < df.loc[t1, "rsi"]:
            return "bearish RSI divergence"
    if len(lows) >= 2:
        (t1, p1), (t2, p2) = lows[-2], lows[-1]
        if p2 < p1 and df.loc[t2, "rsi"] > df.loc[t1, "rsi"]:
            return "bullish RSI divergence"
    return "none"


def pivots(daily: pd.DataFrame) -> Dict[str, float]:
    """Classic floor pivots from the previous completed day."""
    prev = daily.iloc[-2]
    p = (prev.high + prev.low + prev.close) / 3
    return {"R3": prev.high + 2 * (p - prev.low), "R2": p + (prev.high - prev.low), "R1": 2 * p - prev.low,
            "P": p, "S1": 2 * p - prev.high, "S2": p - (prev.high - prev.low),
            "S3": prev.low - 2 * (prev.high - p)}


def fibonacci(highs, lows) -> Dict:
    if not highs or not lows:
        return {}
    hi_t, hi = max(highs[-6:], key=lambda x: x[1])
    lo_t, lo = min(lows[-6:], key=lambda x: x[1])
    up_leg = lo_t < hi_t  # retracing an up-move
    levels = {}
    for r in (0.236, 0.382, 0.5, 0.618, 0.705, 0.786):
        levels[f"{r:.3f}"] = hi - (hi - lo) * r if up_leg else lo + (hi - lo) * r
    for r in (1.272, 1.618):
        levels[f"ext {r}"] = lo + (hi - lo) * r if up_leg else hi - (hi - lo) * r
    return {"leg": "up" if up_leg else "down", "swing_high": hi, "swing_low": lo, "levels": levels}


# ---------------------------------------------------------------- summary

@dataclass
class TFAnalysis:
    tf: str
    price: float
    atr: float
    score: float                      # -100 bearish .. +100 bullish
    trend: str
    structure: str
    signals: Dict[str, str] = field(default_factory=dict)
    supports: List[Dict] = field(default_factory=list)
    resistances: List[Dict] = field(default_factory=list)
    fvgs: List[Dict] = field(default_factory=list)
    patterns: List[str] = field(default_factory=list)
    divergence: str = "none"
    fib: Dict = field(default_factory=dict)
    liquidity: Dict = field(default_factory=dict)


def analyze_tf(df: pd.DataFrame, tf: str) -> TFAnalysis:
    df = add_indicators(df)
    last = df.iloc[-1]
    price, a = float(last.close), float(last.atr)
    highs, lows = swing_points(df)
    votes: Dict[str, float] = {}
    sig: Dict[str, str] = {}

    # Trend (EMA stack and slope)
    if last.ema20 > last.ema50 > last.ema200:
        votes["ema"] = 1; sig["EMA 20/50/200"] = "bullish stack"
    elif last.ema20 < last.ema50 < last.ema200:
        votes["ema"] = -1; sig["EMA 20/50/200"] = "bearish stack"
    else:
        votes["ema"] = 0.5 * np.sign(last.ema20 - last.ema50); sig["EMA 20/50/200"] = "mixed"
    votes["price_vs_200"] = 0.5 * np.sign(price - last.ema200)
    sig["Price vs EMA200"] = "above" if price > last.ema200 else "below"

    # Momentum
    sig["RSI(14)"] = f"{last.rsi:.1f}"
    if last.rsi > 70:
        votes["rsi"] = -0.5; sig["RSI(14)"] += " overbought"
    elif last.rsi < 30:
        votes["rsi"] = 0.5; sig["RSI(14)"] += " oversold"
    else:
        votes["rsi"] = (last.rsi - 50) / 40
    votes["macd"] = 0.7 * np.sign(last.macd_hist) + 0.3 * np.sign(last.macd)
    sig["MACD"] = ("bullish" if last.macd_hist > 0 else "bearish") + \
        (" (expanding)" if abs(last.macd_hist) > abs(df["macd_hist"].iloc[-2]) else " (fading)")
    sig["Stochastic"] = f"%K {last.stoch_k:.0f} / %D {last.stoch_d:.0f}"
    votes["stoch"] = 0.3 * np.sign(last.stoch_k - last.stoch_d)
    votes["supertrend"] = float(last.supertrend)
    sig["Supertrend(10,3)"] = "bullish" if last.supertrend > 0 else "bearish"

    # Trend strength
    trending = last.adx > 22
    sig["ADX"] = f"{last.adx:.1f} ({'trending' if trending else 'weak / range'}), +DI {last.pdi:.0f} / -DI {last.mdi:.0f}"
    votes["dmi"] = (1 if trending else 0.4) * np.sign(last.pdi - last.mdi)

    # Volatility
    bbw = (last.bb_up - last.bb_lo) / last.bb_mid
    sig["Bollinger"] = f"width {bbw * 100:.2f}% " + (
        "above upper band" if price > last.bb_up else "below lower band" if price < last.bb_lo else "inside bands")

    structure = market_structure(highs, lows)
    votes["structure"] = 1 if structure.startswith("bullish") else -1 if structure.startswith("bearish") else 0

    div = rsi_divergence(df, highs, lows)
    if div.startswith("bullish"):
        votes["divergence"] = 0.7
    elif div.startswith("bearish"):
        votes["divergence"] = -0.7

    pats = candle_patterns(df)
    for p in pats:
        if p.startswith("bullish") or p.startswith("hammer"):
            votes["candle"] = 0.5
        elif p.startswith("bearish") or p.startswith("shooting"):
            votes["candle"] = -0.5

    weights = {"ema": 2, "price_vs_200": 1, "rsi": 1, "macd": 1.5, "stoch": 0.5, "supertrend": 1.5,
               "dmi": 1.5, "structure": 2, "divergence": 1, "candle": 0.7}
    total_w = sum(weights[k] for k in votes)
    score = 100 * sum(votes[k] * weights[k] for k in votes) / total_w

    zones = cluster_levels([p for _, p in highs[-25:]] + [p for _, p in lows[-25:]], tol=0.5 * a)
    supports = sorted([z for z in zones if z["price"] < price], key=lambda z: -z["price"])[:4]
    resistances = sorted([z for z in zones if z["price"] > price], key=lambda z: z["price"])[:4]

    recent = df.tail(50)
    liquidity = {"buy_side (equal highs / recent high)": float(recent["high"].max()),
                 "sell_side (equal lows / recent low)": float(recent["low"].min())}

    trend = "uptrend" if score > 25 else "downtrend" if score < -25 else "sideways"
    return TFAnalysis(tf, price, a, round(float(score), 1), trend, structure, sig, supports, resistances,
                      fair_value_gaps(df), pats, div, fibonacci(highs, lows), liquidity)


def mtf_score(analyses: List[TFAnalysis]) -> float:
    """Higher timeframes weigh more (top-down)."""
    w = np.arange(1, len(analyses) + 1, dtype=float)
    return round(float(np.average([a.score for a in analyses], weights=w)), 1)


def to_prompt_text(a: TFAnalysis, digits: int) -> str:
    f = lambda x: f"{x:.{digits}f}"
    lines = [f"### {a.tf}  price {f(a.price)}  ATR {f(a.atr)}  score {a.score:+.0f}  ({a.trend})",
             f"Structure: {a.structure}"]
    lines += [f"- {k}: {v}" for k, v in a.signals.items()]
    lines.append("Supports: " + ", ".join(f"{f(z['price'])}(x{z['touches']})" for z in a.supports))
    lines.append("Resistances: " + ", ".join(f"{f(z['price'])}(x{z['touches']})" for z in a.resistances))
    if a.fvgs:
        lines.append("Unfilled FVGs: " + "; ".join(f"{g['type']} {f(g['bottom'])}-{f(g['top'])}" for g in a.fvgs))
    lines.append("Liquidity pools: " + ", ".join(f"{k} {f(v)}" for k, v in a.liquidity.items()))
    if a.fib:
        lines.append(f"Fib ({a.fib['leg']} leg {f(a.fib['swing_low'])}-{f(a.fib['swing_high'])}): " +
                     ", ".join(f"{k}={f(v)}" for k, v in a.fib["levels"].items()))
    lines.append(f"Candles: {', '.join(a.patterns) or 'nothing notable'};  Divergence: {a.divergence}")
    return "\n".join(lines)


def order_blocks(df: pd.DataFrame, lookback: int = 150, max_n: int = 3) -> List[Dict]:
    """Unmitigated order blocks: the last opposite candle before a displacement that broke structure.

    Bullish OB = last down candle before a strong up-move (>= 1.5 ATR within 3 bars) that closes above the
    prior 10-bar high. Bearish is the mirror. Dropped once price closes through the far side of the zone.
    """
    if "atr" not in df:
        df = add_indicators(df)
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = df["atr"].to_numpy()
    n = len(df)
    out = []
    for i in range(max(11, n - lookback), n - 3):
        nxt = slice(i + 1, i + 4)
        if c[i] < o[i] and c[nxt].max() > h[i - 10:i].max() and c[nxt].max() - c[i] >= 1.5 * a[i]:
            if not (c[i + 4:] < l[i]).any():
                out.append({"type": "bullish", "top": float(h[i]), "bottom": float(l[i]), "time": df.index[i]})
        if c[i] > o[i] and c[nxt].min() < l[i - 10:i].min() and c[i] - c[nxt].min() >= 1.5 * a[i]:
            if not (c[i + 4:] > h[i]).any():
                out.append({"type": "bearish", "top": float(h[i]), "bottom": float(l[i]), "time": df.index[i]})
    return out[-max_n:]
