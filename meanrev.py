"""High win-rate mode: classic professional mean-reversion plans (buy a sharp dip inside an uptrend, sell the bounce).

Sources: Larry Connors' RSI(2) and Double-7 systems; Bollinger-band reversion to the middle band. Win rates of 60-80%
are typical for this style; winners are small, so a safety stop and the trend filter matter.
Tested 2026-10-22 (spread included, first 60% vs unseen 40%), long side only, 200-period trend filter:
  XAUUSD D1 ~20y  Bollinger lower band -> middle band   76% win, PF 9.1 (unseen 80% win)
  XAUUSD D1 ~20y  RSI(2) < 5 -> close above SMA5        73% win, PF 2.2 (unseen 80% win)
  XAUUSD D1 ~20y  Double-7 + 3xATR stop                 70% win, PF 1.5 (unseen 76% win)
  XAUUSD H1 2y    Bollinger lower band -> middle band   69% win, PF 1.4 (unseen 73% win)
  EURUSD H1 2y    RSI(2) < 5 -> close above SMA5        70% win, PF 1.6 (unseen 69% win)
  EURUSD H1 2y    same, 1.5xATR stop, half off at TP1 = 1R and stop to breakeven
                  (Dukascopy 2024-10..2026-10)          68% win, PF 1.5, +0.12R (unseen 70% win, PF 1.8)
  EURUSD M5/M15 scalping (20 methods: RSI(2), Bollinger, VWAP, Stochastic, MACD, Supertrend, London breakout,
                  squeeze, range fade, Pro Pullback, v26): none profitable after spread over 2 years.
  USDJPY: nothing robust.
EURUSD H1 10y (Dukascopy 2016-2026) - the 2-year numbers above did NOT hold over 10 years (RSI(2)<5: 61% win, PF 1.06).
  Robust over 10 years: RSI(2) < 2, skip if a news-spike candle (> 2.5xATR) printed in the last 3 hours, 3xATR stop,
  exit on the bounce                                  242 trades, 68% win, PF 1.42 (first 60% 1.43, last 40% 1.39),
                                                      profitable in 9 of 11 years, ~2 signals a month.
  Dips caused by a news spike lost in both halves (PF 0.86) - that is why they are skipped.
  Rejected: H4 RSI(2) (result depends on the candle start hour), Pro Pullback / v26 / Donchian on EURUSD (negative over 10y).
All signals use closed candles only.
"""
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from config import SPREADS
from technical import add_indicators, rsi

NAMES = {"mr_gold15": "Gold deep dip-buy on M15 (daily + H1 uptrend, dollar check)", "mr_gold": "Gold deep dip-buy with daily trend + dollar check", "mr_eur": "EURUSD dip & rally fade, news-spike filter", "mr_rsi2x": "EURUSD deep dip-buy, news-spike filter", "mr_any": "Gold dip-buy combo (high win rate)", "mr_bb": "Bollinger dip-buy (high win rate)", "mr_rsi2": "Connors RSI(2) dip-buy (high win rate)",
         "mr_d7": "Connors Double-7 dip-buy (high win rate)"}


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    d = add_indicators(df)
    d["sma200"] = d.close.rolling(200).mean()
    d["sma5"] = d.close.rolling(5).mean()
    d["rsi2"] = rsi(d.close, 2)
    d["lo7"] = d.close.rolling(7).min()
    d["hi7"] = d.close.rolling(7).max()
    d["spike"] = ((d.high - d.low) / d.atr).rolling(3).max()       # biggest candle of the last 3, in ATR (news spike)
    d["cum2"] = d.rsi2 + d.rsi2.shift(1)                             # Connors cumulative RSI(2), 2 candles
    d["lo30"] = d.low.rolling(BREAK_BARS).min().shift(1)             # range before this candle (breakdown check)
    d["hi30"] = d.high.rolling(BREAK_BARS).max().shift(1)
    return d


def signal(d: pd.DataFrame, i: int, strat: str):
    """(side, tier) for the candle that just closed; side 0 = no signal.
    mr_eur (EURUSD H1, 10y tested): deep dip = RSI(2) < 2 above SMA200; 2-candle dip = RSI(2) sum of 2 candles < 10 above
    SMA200; rally sell = RSI(2) > 98 below SMA200. All skipped after a news-spike candle.
    10y Dukascopy: 674 trades, 69% win, PF 1.32 (older 60% 1.39, newer 40% 1.22), 9 of 11 years profitable, ~5.6/month."""
    if strat == "mr_gold15":                                  # gold M15: deep dips with the daily AND H1 uptrend
        side, tier = signal(d, i, "mr_eur")
        if side != 1 or tier != "deep dip" or not (d.dtrend.iloc[i] == 1 and d.h1trend.iloc[i] == 1):
            return 0, None
        return side, tier
    if strat == "mr_gold":                                    # gold: only deep dips, only with the daily uptrend
        side, tier = signal(d, i, "mr_eur")
        if side != 1 or tier != "deep dip" or not d.dtrend.iloc[i] == 1:
            return 0, None
        return side, tier
    if strat != "mr_eur":
        return (1, "strong") if entry(d, i, strat) else (0, None)
    if not d.spike.iloc[i] < SPIKE_MAX:
        return 0, None
    if "usd_wide" in d and not d.usd_wide.iloc[i] < USD_WIDE_MAX:     # GBPUSD moved as much: a dollar-wide move, skip
        return 0, None
    up = d.close.iloc[i] > d.sma200.iloc[i]
    breakdown = d.close.iloc[i] < d.lo30.iloc[i]                       # closed below the last 30 candles' low
    breakout = d.close.iloc[i] > d.hi30.iloc[i]
    if up and breakdown or not up and breakout:                         # a structure break, not a dip: it tends to keep going
        return 0, None
    if up and d.rsi2.iloc[i] < 2:
        return 1, "deep dip"
    if up and d.cum2.iloc[i] < 10:
        return 1, "2-candle dip"
    if not up and d.rsi2.iloc[i] > 98:
        return -1, "rally sell"
    return 0, None


def entry(d: pd.DataFrame, i: int, strat: str) -> bool:
    c = d.close.iloc[i]
    if not c > d.sma200.iloc[i]:
        return False
    if strat == "mr_bb":
        return c < d.bb_lo.iloc[i]
    if strat == "mr_rsi2":
        return d.rsi2.iloc[i] < 5
    if strat == "mr_rsi2x":
        return d.rsi2.iloc[i] < 2 and d.spike.iloc[i] < SPIKE_MAX
    if strat == "mr_d7":
        return c <= d.lo7.iloc[i]
    if strat == "mr_any":
        return c < d.bb_lo.iloc[i] or d.rsi2.iloc[i] < 5 or c <= d.lo7.iloc[i]
    return False


def exit_now(d: pd.DataFrame, j: int, strat: str, side: int = 1) -> bool:
    c = d.close.iloc[j]
    if side == -1:
        return c < d.sma5.iloc[j]
    if strat == "mr_bb":
        return c > d.bb_mid.iloc[j]
    if strat in ("mr_rsi2", "mr_rsi2x", "mr_eur", "mr_gold", "mr_gold15", "mr_any"):
        return c > d.sma5.iloc[j]
    if strat == "mr_d7":
        return c >= d.hi7.iloc[j]
    return False


def checks(d: pd.DataFrame, i: int, strat: str) -> Dict:
    c = d.close.iloc[i]
    res = {"uptrend": bool(c > d.sma200.iloc[i]), "sma200": float(d.sma200.iloc[i])}
    if strat == "mr_bb":
        res.update(dip=bool(c < d.bb_lo.iloc[i]), level=float(d.bb_lo.iloc[i]), target=float(d.bb_mid.iloc[i]))
    elif strat == "mr_rsi2":
        res.update(dip=bool(d.rsi2.iloc[i] < 5), level=float(d.rsi2.iloc[i]), target=float(d.sma5.iloc[i]))
    elif strat in ("mr_eur", "mr_gold", "mr_gold15"):
        side, tier = signal(d, i, strat)
        up = res["uptrend"]
        res.update(dtrend=float(d.dtrend.iloc[i]) if "dtrend" in d and d.dtrend.iloc[i] == d.dtrend.iloc[i] else None,
                   h1trend=float(d.h1trend.iloc[i]) if "h1trend" in d and d.h1trend.iloc[i] == d.h1trend.iloc[i] else None)
        res.update(usd_wide=float(d.usd_wide.iloc[i]) if "usd_wide" in d else None,
                   breakdown=bool(d.close.iloc[i] < d.lo30.iloc[i]) if res["uptrend"] else bool(d.close.iloc[i] > d.hi30.iloc[i]))
        res.update(dip=bool(side), side=side, tier=tier, level=float(d.rsi2.iloc[i]), cum2=float(d.cum2.iloc[i]),
                   target=float(d.sma5.iloc[i]), spike=float(d.spike.iloc[i]), calm=bool(d.spike.iloc[i] < SPIKE_MAX),
                   mode="buy dips" if up else "sell rallies")
    elif strat == "mr_rsi2x":
        res.update(dip=bool(d.rsi2.iloc[i] < 2), level=float(d.rsi2.iloc[i]), target=float(d.sma5.iloc[i]),
                   spike=float(d.spike.iloc[i]), calm=bool(d.spike.iloc[i] < SPIKE_MAX))
    elif strat == "mr_any":
        res.update(dip=bool(c < d.bb_lo.iloc[i] or d.rsi2.iloc[i] < 5 or c <= d.lo7.iloc[i]),
                   level=float(d.rsi2.iloc[i]), target=float(d.sma5.iloc[i]),
                   bb=bool(c < d.bb_lo.iloc[i]), rsi2=bool(d.rsi2.iloc[i] < 5), d7=bool(c <= d.lo7.iloc[i]))
    else:
        res.update(dip=bool(c <= d.lo7.iloc[i]), level=float(d.lo7.iloc[i]), target=float(d.hi7.iloc[i]))
    return res


# per-market exit settings that tested better than the default 3xATR safety stop
EXITS = {("EURUSD", "mr_rsi2"): {"stop_atr": 1.5, "tp1_r": 1.0}, ("EURUSD", "mr_rsi2x"): {"stop_atr": 3.0, "tp1_r": None},
         ("EURUSD", "mr_eur"): {"stop_atr": 3.0, "tp1_r": 0.25 / 3.0},
         ("XAUUSD", "mr_gold"): {"stop_atr": 3.0, "tp1_r": 0.25 / 3.0},
         ("XAUUSD", "mr_gold15"): {"stop_atr": 3.0, "tp1_r": 0.25 / 3.0}}   # TP1 = +0.25xATR: close half, stop to breakeven
SPIKE_MAX = 2.5
# Breakdown filter (EURUSD 10y): a dip that closes below the previous 30 candles' low (LL / BOS) is a structure break.
# Skipping those: PF 1.75 -> 2.13 (older 2.05 / newer 2.29), full stop-outs halved, all 11 years profitable.
BREAK_BARS = 30
# Information targets: (distance in R of the stop, % of 10y EURUSD trades whose best move reached it before the exit).
# Fixed take-profits made less money than the bounce exit, so these are shown as odds, not as the plan's exit.
# USD-wide filter (EURUSD): GBPUSD's 5-candle move / EURUSD's 5-candle move, each in its own ATR. At >= 0.9 the whole
# dollar is moving and the snap-back had no edge over 10y (PF 0.99); below it PF 1.50 (older 1.45 / newer 1.59).
USD_WIDE_MAX = 0.9
# Gold (XAUUSD 10y): deep dips only, daily close above its 50-day average, and the dollar check against EURUSD.
# 132 trades, 89% win, PF 4.11 (older 4.28 / newer 3.91), all 10 years profitable. Rally sells and Asia-hour trades lost lately.
DAILY_SMA = 50
USD_WIDE_BARS = 5


def usd_wide(d: pd.DataFrame, peer: pd.DataFrame, k: int = USD_WIDE_BARS) -> pd.Series:
    g = peer.close.reindex(d.index, method="ffill")
    gatr = (peer.high - peer.low).rolling(14).mean().reindex(d.index, method="ffill")
    return ((g - g.shift(k)) / gatr) / ((d.close - d.close.shift(k)) / d.atr)


# mr_eur / mr_gold TP1 is the real half-close level (0.25xATR)
def add_daily_trend(d: pd.DataFrame, n: int = DAILY_SMA, src: Optional[pd.Series] = None) -> None:
    """dtrend = +1 / -1: yesterday's daily close above / below its n-day average (known at today's open).
    src: a longer close series (e.g. H1) when d itself is too short."""
    day = (src if src is not None else d.close).resample("1D").last().dropna()
    t = (day > day.rolling(n).mean()).astype(float) * 2 - 1
    t[day.rolling(n).mean().isna()] = np.nan
    t.index = t.index + pd.Timedelta(days=1)
    d["dtrend"] = t.reindex(d.index, method="ffill")


def add_h1_trend(d: pd.DataFrame, h1_close: pd.Series, n: int = 200) -> None:
    """h1trend = +1 / -1: the last closed H1 candle above / below its n-candle average."""
    m = h1_close.rolling(n).mean()
    t = (h1_close > m).astype(float) * 2 - 1
    t[m.isna()] = np.nan
    t.index = t.index + pd.Timedelta(hours=1)                     # known when that H1 candle closes
    d["h1trend"] = t.reindex(d.index, method="ffill")


TP_LEVELS = {"mr_gold15": [(0.25 / 3.0, 92), (0.30, 37), (0.50, 12)], "mr_gold": [(0.25 / 3.0, 92), (0.30, 36), (0.50, 11)], "mr_eur": [(0.25 / 3.0, 86), (0.30, 33), (0.50, 12)], "mr_rsi2x": [(0.15, 72), (0.30, 44), (0.50, 15)]}


def exit_cfg(sym: str, strat: str) -> Dict:
    return EXITS.get((sym, strat), {"stop_atr": 3.0, "tp1_r": None})


def trades(df: pd.DataFrame, sym: str, strat: str, stop_atr: Optional[float] = 3.0, max_bars: int = 400,
           tp1_r: Optional[float] = None, peer: Optional[pd.DataFrame] = None,
           trend_src: Optional[pd.Series] = None) -> List[Dict]:
    """One position at a time; enter at the signal candle's close, exit at the close when the bounce is done.
    With tp1_r: half the position is closed at entry + tp1_r x risk and the stop moves to breakeven.
    peer: the cross-check pair (GBPUSD for EURUSD) for the USD-wide filter; without it the filter is off.
    trend_src: H1 closes for the trend filters of a faster chart (mr_gold15), so a short M15 history is enough."""
    d = prepare(df)
    if peer is not None and strat in ("mr_eur", "mr_gold", "mr_gold15"):
        d["usd_wide"] = usd_wide(d, peer)
    if strat in ("mr_gold", "mr_gold15"):
        add_daily_trend(d, src=trend_src)
    if strat == "mr_gold15":
        add_h1_trend(d, trend_src if trend_src is not None else d.close.resample("1h").last().dropna())
    c, h, l, a = d.close.values, d.high.values, d.low.values, d.atr.values
    spread = SPREADS.get(sym, 0)
    out, i, n = [], 210, len(d)
    while i < n:
        side, tier = signal(d, i, strat)
        if not side:
            i += 1
            continue
        e = c[i]
        risk = (stop_atr or 3.0) * a[i]
        stop = e - side * risk if stop_atr else None
        stop0 = stop if stop is not None else e - side * risk
        tp1 = e + side * tp1_r * risk if tp1_r else None
        tgt0 = float(d.bb_mid.iloc[i] if strat == "mr_bb" else d.hi7.iloc[i] if strat == "mr_d7" else d.sma5.iloc[i])
        tr = {"i": i, "time": d.index[i], "side": side, "tier": tier, "entry": float(e), "stop0": float(stop0),
              "tp1": float(tp1) if tp1 else None,
              "tp2": float(tgt0 if (tgt0 - e) * side > 0 else e + side * 0.5 * risk),     # bounce target at the signal
              "tp1_time": None,
              "tps": [(float(e + side * lv * risk), lv, pct) for lv, pct in TP_LEVELS.get(strat, [])]}
        best = 0.0
        half = None
        px, j = None, i + 1
        while j < min(n, i + 1 + max_bars):
            best = max(best, ((h[j] - e) if side == 1 else (e - l[j])) / risk)
            if stop is not None and ((l[j] <= stop) if side == 1 else (h[j] >= stop)):
                px = stop
                break
            if tp1 is not None and half is None and ((h[j] >= tp1) if side == 1 else (l[j] <= tp1)):
                half, stop, tr["tp1_time"] = tp1_r, e, d.index[j]          # bank half, stop to breakeven
            if exit_now(d, j, strat, side):
                px = c[j]
                break
            j += 1
        tr["tp_hit"] = [best >= lv for _, lv, _ in tr["tps"]]
        tr["target_now"] = float(d.bb_mid.iloc[min(j, n - 1)] if strat == "mr_bb" else d.sma5.iloc[min(j, n - 1)])
        blend = lambda rest: 0.5 * half + 0.5 * rest if half is not None else rest
        path = [(d.index[i], stop0)] + ([(tr["tp1_time"], e)] if half is not None else [])
        if px is None:                                        # still open at the last candle
            tr.update(exit_i=None, exit=None, exit_time=None, open=True, r=blend((c[-1] - e) * side / risk),
                      open_r=blend((c[-1] - e) * side / risk), stop_now=float(stop if stop is not None else stop0),
                      path=path + [(d.index[-1], stop if stop is not None else stop0)])
            out.append(tr)
            break
        tr.update(exit_i=j, exit=float(px), exit_time=d.index[j], open=False,
                  r=blend((px - e) * side / risk) - spread / risk,
                  path=path + [(d.index[j], stop if stop is not None else stop0)])
        out.append(tr)
        i = j + 1
    return out
