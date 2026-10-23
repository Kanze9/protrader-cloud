"""The user's own TradingView strategies, ported as engine setups (non-repainting, closed candles only).

1. Pro Pullback (专业交易者思路 - 趋势回调策略): 4H EMA50/200 trend, pullback to EMA20 that holds EMA50,
   confirmation candle closing beyond the prior candle, ADX >= 20, 07-17 UTC, stop = 10-bar swing +/- 0.3 ATR
   (skip if wider than 3 ATR), target 2R.
2. Signal v26 (世界最强信号 v26): 1H EMA200 + 15m EMA50 trend, 15m RSI > 50 / < 50, 15m ADX > 20, engulfing or
   pin bar, volume > 1.3x average, ATR > 0.8x its average, close within 1.5 ATR of EMA20, Bollinger width
   expanding; stop = min(5-bar structure, k x ATR), target = m x ATR (per-symbol presets from the script).
"""
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from technical import add_indicators

PRO_PULLBACK = "Pro Pullback (your indicator)"
SIGNAL_V26 = "Signal v26 (your indicator)"

# Signal v26 presets: (stop ATR multiple, target ATR multiple)
V26_PRESETS = {"EURUSD": (1.5, 3.0), "GBPUSD": (1.5, 3.0), "USDJPY": (1.5, 3.0),
               "XAUUSD": (3.0, 6.0), "BTCUSD": (2.5, 6.0), "NAS100": (2.5, 5.0)}


def _with_ind(df: pd.DataFrame) -> pd.DataFrame:
    return df if "ema200" in df else add_indicators(df)


def htf_features(exec_df: pd.DataFrame, tf_min: int, frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Higher-timeframe values known at each execution candle's close (no look-ahead).

    frames: {"H4": df, "H1": df, "M15": df} with bar-open timestamps. An HTF bar is used only once it has closed.
    """
    exec_close = exec_df.index + pd.Timedelta(minutes=tf_min)
    out = pd.DataFrame(index=exec_df.index)
    spec = {"H4": (240, {"close": "h4_close", "ema50": "h4_ema50", "ema200": "h4_ema200"}),
            "H1": (60, {"close": "h1_close", "ema200": "h1_ema200"}),
            "M15": (15, {"close": "m15_close", "ema50": "m15_ema50", "rsi": "m15_rsi", "adx": "m15_adx"})}
    for key, (mins, cols) in spec.items():
        f = frames.get(key)
        if f is None or len(f) < 30:
            continue
        f = _with_ind(f)[list(cols)].rename(columns=cols)
        f.index = f.index + pd.Timedelta(minutes=mins)            # stamp each HTF bar at its close time
        f = f[~f.index.duplicated(keep="last")].sort_index()
        aligned = f.reindex(f.index.union(exec_close)).ffill().reindex(exec_close)
        aligned.index = exec_df.index
        out = out.join(aligned)
    return out


def _mk(ctx, name, d, entry, stop, tp1, tp2, tp3, trigger, reasons):
    from scalping import Setup
    rnd = lambda v: round(float(v), ctx.inst.digits)
    return Setup(name, d, "MARKET", rnd(entry), rnd(stop), rnd(tp1), rnd(tp2), rnd(tp3), trigger, reasons=reasons)


def pro_pullback(ctx) -> List:
    x = ctx.extra or {}
    need = ("h4_close", "h4_ema50", "h4_ema200")
    if any(pd.isna(x.get(k)) for k in need):
        return []
    df = ctx.df
    last, prev = df.iloc[-1], df.iloc[-2]
    hour = df.index[-1].hour
    if not (7 <= hour < 17) or last.adx < 20:
        return []
    up = x["h4_close"] > x["h4_ema200"] and x["h4_ema50"] > x["h4_ema200"]
    dn = x["h4_close"] < x["h4_ema200"] and x["h4_ema50"] < x["h4_ema200"]
    a = float(last.atr)
    f = ctx.inst.digits
    out = []
    if up and last.close > last.ema50 and last.ema20 > last.ema50 and (df["low"].tail(4) <= df["ema20"].tail(4)).any() \
            and last.close > last.open and last.close > prev.high and last.close > last.ema20:
        stop = df["low"].tail(10).min() - 0.3 * a
        dist = last.close - stop
        if 0 < dist <= 3 * a:
            e = last.close
            out.append(_mk(ctx, PRO_PULLBACK, 1, e, stop, e + dist, e + 2 * dist, e + 3 * dist,
                           f"Buy at market: 4H uptrend, pullback to EMA20 held EMA50, confirmation candle closed above "
                           f"{prev.high:.{f}f}. Target 2R.",
                           ["4H EMA50 > EMA200", "pullback to EMA20 held structure", f"ADX {last.adx:.0f}"]))
    if dn and last.close < last.ema50 and last.ema20 < last.ema50 and (df["high"].tail(4) >= df["ema20"].tail(4)).any() \
            and last.close < last.open and last.close < prev.low and last.close < last.ema20:
        stop = df["high"].tail(10).max() + 0.3 * a
        dist = stop - last.close
        if 0 < dist <= 3 * a:
            e = last.close
            out.append(_mk(ctx, PRO_PULLBACK, -1, e, stop, e - dist, e - 2 * dist, e - 3 * dist,
                           f"Sell at market: 4H downtrend, pullback to EMA20 held EMA50, confirmation candle closed below "
                           f"{prev.low:.{f}f}. Target 2R.",
                           ["4H EMA50 < EMA200", "pullback to EMA20 held structure", f"ADX {last.adx:.0f}"]))
    return out


def signal_v26(ctx) -> List:
    x = ctx.extra or {}
    need = ("h1_ema200", "m15_ema50", "m15_rsi", "m15_adx")
    if any(pd.isna(x.get(k)) for k in need):
        return []
    df = ctx.df
    last, prev = df.iloc[-1], df.iloc[-2]
    sl_m, tp_m = V26_PRESETS.get(ctx.symbol, (2.0, 4.0))
    a = float(last.atr)
    rng = last.high - last.low
    vol = df["volume"]
    vol_ok = True if (vol.tail(40) <= 0).mean() > 0.5 else last.volume > 1.3 * vol.tail(20).mean()
    atr_ok = a > 0.8 * df["atr"].tail(20).mean()
    near = abs(last.close - last.ema20) < 1.5 * a
    bbw = (4 * df["close"].rolling(20).std()) / df["close"].rolling(20).mean() * 100
    vola_ok = bbw.iloc[-1] > bbw.tail(20).mean()
    strong = x["m15_adx"] > 20
    if not (vol_ok and atr_ok and near and vola_ok and strong):
        return []
    out = []
    bull_pat = (prev.close < prev.open and last.close > last.open and last.close > prev.open and last.open < prev.close) or \
               (rng > 0 and (last.close - last.low) / rng > 0.7 and last.close > last.open)
    bear_pat = (prev.close > prev.open and last.close < last.open and last.close < prev.open and last.open > prev.close) or \
               (rng > 0 and (last.high - last.close) / rng > 0.7 and last.close < last.open)
    e = last.close
    if bull_pat and last.close > x["h1_ema200"] and last.close > x["m15_ema50"] and x["m15_rsi"] > 50:
        stop = min(df["low"].tail(5).min(), e - sl_m * a)
        tp = e + tp_m * a
        out.append(_mk(ctx, SIGNAL_V26, 1, e, stop, e + 0.5 * (tp - e), tp, e + 1.5 * (tp - e),
                       "Buy at market: above 1H EMA200 and 15m EMA50, 15m RSI > 50, bullish engulfing / pin bar "
                       "with volume and volatility expansion.",
                       ["1H + 15m trend up", f"15m ADX {x['m15_adx']:.0f}", "volume & BB expansion"]))
    if bear_pat and last.close < x["h1_ema200"] and last.close < x["m15_ema50"] and x["m15_rsi"] < 50:
        stop = max(df["high"].tail(5).max(), e + sl_m * a)
        tp = e - tp_m * a
        out.append(_mk(ctx, SIGNAL_V26, -1, e, stop, e - 0.5 * (e - tp), tp, e - 1.5 * (e - tp),
                       "Sell at market: below 1H EMA200 and 15m EMA50, 15m RSI < 50, bearish engulfing / pin bar "
                       "with volume and volatility expansion.",
                       ["1H + 15m trend down", f"15m ADX {x['m15_adx']:.0f}", "volume & BB expansion"]))
    return out
