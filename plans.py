"""All tested signal plans in one place, with a setup meter for each (how many of the plan's conditions are met now).

Tier A = high accuracy (83-91% win, small wins).  Tier B = trend trades (~40% win, trailing stop, bigger wins).
Used by the app's signal board, the Gmail worker and the cloud page.   run_plan(plan, get) with get(symbol, tf) -> closed candles.
"""
import json
import os
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

import meanrev
import proplan
from config import SPREADS
from technical import add_indicators

HERE = os.path.dirname(os.path.abspath(__file__))
AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}

PLANS = [
    {"id": "eur_a", "sym": "EURUSD", "tf": "H1", "tier": "A", "kind": "mr", "strat": "mr_eur", "peer": "GBPUSD",
     "name": "EURUSD dip-buy / rally-sell"},
    {"id": "eur_r3", "sym": "EURUSD", "tf": "H1", "tier": "A", "kind": "mr", "strat": "mr_eur_r3", "peer": "GBPUSD",
     "name": "EURUSD Connors R3"},
    {"id": "gold_a", "sym": "XAUUSD", "tf": "H1", "tier": "A", "kind": "mr", "strat": "mr_gold", "peer": "EURUSD",
     "name": "Gold deep dip"},
    {"id": "gold_a15", "sym": "XAUUSD", "tf": "M15", "tier": "A", "kind": "mr", "strat": "mr_gold15", "peer": "EURUSD",
     "name": "Gold deep dip"},
    {"id": "gold_pull", "sym": "XAUUSD", "tf": "H1", "tier": "B", "kind": "pull", "name": "Gold trend pullback"},
    {"id": "btc_brk", "sym": "BTCUSD", "tf": "H1", "tier": "B", "kind": "brk", "name": "Bitcoin 7-day breakout"},
    # gold_pro (Pro Pullback, kind "pro") left the board 2026-10-27: weaker in the newer years (PF 1.22), 7/11 years up,
    # often the opposite side of gold_pull, and it doubled the drawdown of the mix. The code below still supports it.
]
TIER_TEXT = {"A": "A · high accuracy", "B": "B · trend trade (trailing stop)"}


def stats(plan: Dict) -> Optional[Dict]:
    try:
        with open(os.path.join(HERE, "models", "strategy_stats.json"), encoding="utf-8") as fh:
            return json.load(fh)["stats"].get(f"plan|{plan['id']}")
    except (OSError, ValueError, KeyError):
        return None


# ---------------------------------------------------------------- gold trend pullback (buys only)
# 10y Dukascopy H1 gold, $0.25 cost, one trade at a time (research 2026-10-27):
#   old rules (daily up, EMA20 > EMA50, dip to EMA20, stop 2 / trail 3 ATR)   778 trades, PF 1.34 (old 1.16, new 1.63), dd 20.5R
#   + 4H trend up + London/New York hours 07-17 UTC                          533 trades, PF 1.61 (old 1.43, new 1.92), dd 12.8R
#   + stop 1.5 / trail 3.5 ATR (middle of a plateau: every stop 1.5-2.5 x trail 2.5-4 profitable in both halves)
#                                                                             499 trades, 34% win, PF 1.78 (old 1.55, new 2.15),
#                                                                             +1.93R a month, dd 12.4R, 9 of 10 years up
#   The entry timing is real: it beat all 40 runs of random entries with the same filters and exit (random PF ~1.43).
#   Gold only: the same rule on 12 currency pairs and silver lost or broke even, and gold sells lost.
#   Rejected: both sides, breakout entries (no extra profit, bigger drawdown), part-close at 1R, fixed 2R / 3R targets.

PULL_STOP_ATR, PULL_TRAIL_ATR = 1.5, 3.5
PULL_HOURS = (7, 17)                       # UTC, candle open hour


def add_h4_trend(d: pd.DataFrame, src: pd.DataFrame) -> None:
    """t4 = +1 / -1 / 0: the last closed 4H candle (built from H1) has close > EMA50 > EMA200 (or the reverse)."""
    h4 = add_indicators(src.resample("4h").agg(AGG).dropna())
    t = pd.Series(np.where((h4.close > h4.ema50) & (h4.ema50 > h4.ema200), 1,
                           np.where((h4.close < h4.ema50) & (h4.ema50 < h4.ema200), -1, 0)), index=h4.index + pd.Timedelta(hours=4))
    d["t4"] = t.reindex(d.index, method="ffill").fillna(0).values


def pull_prepare(h1: pd.DataFrame) -> pd.DataFrame:
    d = add_indicators(h1)
    meanrev.add_daily_trend(d)
    add_h4_trend(d, h1)
    return d


def pull_checks(d: pd.DataFrame, i: int) -> Dict:
    o, l, c = d.open.values, d.low.values, d.close.values
    e20, e50 = d.ema20.values, d.ema50.values
    hr = d.index[i].hour
    res = {"daily_up": d.dtrend.iloc[i] == 1, "h4_up": d.t4.iloc[i] == 1, "ema_up": e20[i] > e50[i],
           "session": PULL_HOURS[0] <= hr < PULL_HOURS[1], "touch": l[i] <= e20[i],
           "close_above": c[i] > e20[i], "bull": c[i] > o[i]}
    res["signal"] = all(res.values())
    return res


def pull_trades(h1: pd.DataFrame, sym: str = "XAUUSD") -> List[Dict]:
    """Daily + 4H uptrend, EMA20 above EMA50, London/New York hours: a candle dips to EMA20 and closes bullish back above
    it -> buy at the close. Stop 1.5xATR, then the stop trails 3.5xATR behind the best price (no fixed target)."""
    d = pull_prepare(h1)
    c, h, l, a = d.close.values, d.high.values, d.low.values, d.atr.values
    cost = SPREADS.get(sym, 0)
    out, i, n = [], 250, len(d)
    while i < n:
        if not pull_checks(d, i)["signal"]:
            i += 1
            continue
        e = c[i]
        R = PULL_STOP_ATR * a[i]
        stop, peak = e - R, e
        path = [(d.index[i], stop)]
        exit_i = None
        for j in range(i + 1, min(n, i + 300)):
            if l[j] <= stop:
                exit_i = j
                break
            peak = max(peak, h[j])
            stop = max(stop, peak - PULL_TRAIL_ATR * a[j])
            path.append((d.index[j], stop))
        tr = {"i": i, "time": d.index[i], "side": 1, "entry": float(e), "stop0": float(e - R), "tier": "EMA20 pullback"}
        if exit_i is None and i + 300 < n:                 # held 300 candles without the stop: close at the market
            j = i + 299
            tr.update(exit_i=j, exit=float(c[j]), exit_time=d.index[j], open=False, stop_now=float(stop),
                      r=(c[j] - e - cost) / R, path=path)
            out.append(tr)
            i = j + 1
            continue
        if exit_i is None:
            tr.update(exit_i=None, exit=None, exit_time=None, open=True, stop_now=float(stop),
                      r=(c[-1] - e) / R, open_r=(c[-1] - e) / R, path=path + [(d.index[-1], stop)])
            out.append(tr)
            break
        tr.update(exit_i=exit_i, exit=float(stop), exit_time=d.index[exit_i], open=False, stop_now=float(stop),
                  r=(stop - e - cost) / R, path=path + [(d.index[exit_i], stop)])
        out.append(tr)
        i = exit_i + 1
    return out


# ---------------------------------------------------------------- Bitcoin 7-day breakout (both sides)
# Dukascopy BTCUSD H1 2017-10 .. 2026-10, cost 0.04% of price, one trade at a time (research 2026-10-27):
#   close above the highest close of the last 168 hours (7 days) with the daily (close vs 50-day average) and 4H trend up,
#   or below the 7-day lowest close with both trends down. Stop 2xATR, then the stop trails 4xATR behind the best price.
#   527 trades, 33% win, PF 1.69 (older 1.67, newer 1.72), +1.9R a month, worst drop 21R, 8 of 10 years up.
#   Every neighbour (lookback 120-336 h x stop 1.5-3 / trail 3.5-6) was profitable in both halves (PF 1.6-2.1);
#   double cost: PF 1.62; with ~0.055%/day overnight financing (trades last ~1 day): PF 1.61 in both halves.
#   Beat all 30 runs of random entries with the same trend filters and exit (random median PF 1.40).
#   The gold pullback rule on Bitcoin worked in the older years but faded lately (newer PF 1.0-1.3), so it is not used.

BRK_BARS, BRK_STOP_ATR, BRK_TRAIL_ATR = 168, 2.0, 4.0
COST_PCT = {"BTCUSD": 0.0004}              # spread as a share of price (crypto spreads scale with the price)


def brk_prepare(h1: pd.DataFrame) -> pd.DataFrame:
    d = add_indicators(h1)
    meanrev.add_daily_trend(d)
    add_h4_trend(d, h1)
    d["hh"] = d.close.rolling(BRK_BARS).max().shift(1)
    d["ll"] = d.close.rolling(BRK_BARS).min().shift(1)
    return d


def brk_checks(d: pd.DataFrame, i: int) -> Dict:
    c = d.close.iloc[i]
    side = 1 if d.dtrend.iloc[i] == 1 else -1 if d.dtrend.iloc[i] == -1 else 0
    res = {"side": side, "daily": side != 0, "h4": side != 0 and d.t4.iloc[i] == side,
           "break": (side == 1 and c > d.hh.iloc[i]) or (side == -1 and c < d.ll.iloc[i]),
           "level": float(d.hh.iloc[i] if side >= 0 else d.ll.iloc[i]), "close": float(c)}
    res["signal"] = res["daily"] and res["h4"] and res["break"]
    return res


def brk_trades(h1: pd.DataFrame, sym: str = "BTCUSD") -> List[Dict]:
    """7-day breakout with the daily + 4H trend -> enter at the close; stop 2xATR, trailing 4xATR (no fixed target)."""
    d = brk_prepare(h1)
    c, h, l, a = d.close.values, d.high.values, d.low.values, d.atr.values
    out, i, n = [], 250, len(d)
    while i < n:
        ck = brk_checks(d, i)
        if not ck["signal"]:
            i += 1
            continue
        s_ = ck["side"]
        e = c[i]
        R = BRK_STOP_ATR * a[i]
        cost = COST_PCT[sym] * e if sym in COST_PCT else SPREADS.get(sym, 0)
        stop, best = e - s_ * R, e
        path = [(d.index[i], stop)]
        exit_i = None
        for j in range(i + 1, min(n, i + 300)):
            if (s_ == 1 and l[j] <= stop) or (s_ == -1 and h[j] >= stop):
                exit_i = j
                break
            best = max(best, h[j]) if s_ == 1 else min(best, l[j])
            stop = max(stop, best - BRK_TRAIL_ATR * a[j]) if s_ == 1 else min(stop, best + BRK_TRAIL_ATR * a[j])
            path.append((d.index[j], stop))
        tr = {"i": i, "time": d.index[i], "side": s_, "entry": float(e), "stop0": float(e - s_ * R), "tier": "7-day breakout"}
        if exit_i is None and i + 300 < n:
            j = i + 299
            tr.update(exit_i=j, exit=float(c[j]), exit_time=d.index[j], open=False, stop_now=float(stop),
                      r=(c[j] - e) * s_ / R - cost / R, path=path)
            out.append(tr)
            i = j + 1
            continue
        if exit_i is None:
            tr.update(exit_i=None, exit=None, exit_time=None, open=True, stop_now=float(stop),
                      r=(c[-1] - e) * s_ / R, open_r=(c[-1] - e) * s_ / R, path=path + [(d.index[-1], stop)])
            out.append(tr)
            break
        tr.update(exit_i=exit_i, exit=float(stop), exit_time=d.index[exit_i], open=False, stop_now=float(stop),
                  r=(stop - e) * s_ / R - cost / R, path=path + [(d.index[exit_i], stop)])
        out.append(tr)
        i = exit_i + 1
    return out


# ---------------------------------------------------------------- meters

def _meter(side: str, items: List, note: str = "") -> Dict:
    met = sum(1 for _, ok, _ in items if ok)
    return {"side": side, "met": met, "total": len(items), "items": items, "ready": met == len(items), "note": note}


def mr_meter(plan: Dict, m: Dict) -> Dict:
    dollar_ok = m.get("usd_wide") is None or m["usd_wide"] < meanrev.USD_WIDE_MAX
    dollar = ("Dollar calm (" + plan["peer"] + ")", dollar_ok,
              "no data" if m.get("usd_wide") is None else f"{m['usd_wide']:.2f} (<{meanrev.USD_WIDE_MAX})")
    calm = ("No news spike (last 3 candles)", m["calm"], f"{m['spike']:.1f}×ATR")
    brk = ("No structure break (30 candles)", not m.get("breakdown"), "clear" if not m.get("breakdown") else "break")
    if plan["strat"] == "mr_eur_r3":
        r = m.get("rsi2_last3") or [50, 50, 50]
        up = m["uptrend"]
        want = 1 if up else -1
        falls = (r[2] < r[1] < r[0]) if up else (r[2] > r[1] > r[0])
        return _meter("BUY" if up else "SELL", [
            ("Trend (200-average)", True, "buy dips" if up else "sell rallies"),
            ("Daily trend agrees", m.get("dtrend") == want, ""), calm, brk, dollar,
            ("RSI2 " + ("falling" if up else "rising") + " 3 candles in a row", falls, " > ".join(f"{v:.0f}" for v in r)),
            ("RSI2 " + ("< 10" if up else "> 90"), r[2] < 10 if up else r[2] > 90, f"{r[2]:.0f}")])
    if plan["strat"] == "mr_eur":
        if m["uptrend"]:
            dip = ("Dip deep enough (RSI2 < 2 or 2-candle < 10)", m["level"] < 2 or m["cum2"] < 10,
                   f"RSI2 {m['level']:.0f} · 2-candle {m['cum2']:.0f}")
            return _meter("BUY", [("Uptrend (above 200-average)", True, "buy dips"), calm, brk, dollar, dip])
        rally = ("Rally strong enough (RSI2 > 98)", m["level"] > 98, f"RSI2 {m['level']:.0f}")
        return _meter("SELL", [("Downtrend (below 200-average)", True, "sell rallies"), calm, brk, dollar, rally])
    items = [("H1 uptrend", (m.get("h1trend") == 1) if plan["strat"] == "mr_gold15" else m["uptrend"], ""),
             ("Daily uptrend (50-day average)", m.get("dtrend") == 1, ""), calm, brk, dollar,
             ("Deep dip (RSI2 < 2)", m["level"] < 2, f"RSI2 {m['level']:.0f}")]
    if plan["strat"] == "mr_gold15":
        items.insert(0, ("Price above its M15 200-average", m["uptrend"], ""))
    return _meter("BUY", items)


def pull_meter(c: Dict) -> Dict:
    return _meter("BUY", [("Daily uptrend (50-day average)", c["daily_up"], ""), ("4H uptrend (close > EMA50 > EMA200)", c["h4_up"], ""),
                          ("EMA20 above EMA50 (H1)", c["ema_up"], ""), ("London / New York hours (07-17 UTC)", c["session"], ""),
                          ("Candle dipped to EMA20", c["touch"], ""), ("Closed back above EMA20", c["close_above"], ""),
                          ("Bullish candle", c["bull"], "")])


def brk_meter(c: Dict) -> Dict:
    side = "BUY" if c["side"] == 1 else "SELL" if c["side"] == -1 else "—"
    word = "above the 7-day high" if c["side"] >= 0 else "below the 7-day low"
    return _meter(side, [("Daily trend clear (50-day average)", c["daily"], side), ("4H trend agrees", c["h4"], ""),
                         ("Closed " + word, c["break"], f"{c['close']:,.0f} vs {c['level']:,.0f}")])


def pro_meter(c: Dict, daily: int, monday: bool) -> Dict:
    side = "BUY" if c["trend"] == 1 else "SELL" if c["trend"] == -1 else "—"
    return _meter(side, [("4H trend clear", bool(c["trend"]), side), ("Daily trend agrees", bool(c["trend"]) and daily == c["trend"], ""),
                         ("Not Monday", not monday, ""), ("Active session 07-17 UTC", c["session"], ""),
                         ("ADX ≥ 20", c["adx_ok"], f"{c['adx']:.0f}"), ("Structure (EMA20 vs EMA50)", c["structure"], ""),
                         ("Pulled back to EMA20", c["pullback"], ""), ("Confirmation candle", c["confirm"], ""),
                         ("Stop within 3×ATR", c["stop_ok"], "")])


# ---------------------------------------------------------------- run

def run_plan(plan: Dict, get: Callable[[str, str], Optional[pd.DataFrame]]) -> Dict:
    """Trades on the loaded closed history, the setup meter for the last closed candle, the last price."""
    sym, tf = plan["sym"], plan["tf"]
    d_raw = get(sym, tf)
    if d_raw is None or len(d_raw) < 300:
        raise RuntimeError(f"not enough {sym} {tf} data")
    if plan["kind"] == "mr":
        peer = get(plan["peer"], tf)
        trend_src = get(sym, "H1").close if plan["strat"] == "mr_gold15" else None
        cfg = meanrev.exit_cfg(sym, plan["strat"])
        trades = meanrev.trades(d_raw, sym, plan["strat"], cfg["stop_atr"], tp1_r=cfg["tp1_r"], peer=peer, trend_src=trend_src)
        dm = meanrev.prepare(d_raw)
        if peer is not None:
            dm["usd_wide"] = meanrev.usd_wide(dm, peer)
        if plan["strat"] in ("mr_gold", "mr_gold15", "mr_eur_r3"):
            meanrev.add_daily_trend(dm, src=trend_src)
        if plan["strat"] == "mr_gold15":
            meanrev.add_h1_trend(dm, trend_src)
        meter = mr_meter(plan, meanrev.checks(dm, len(dm) - 1, plan["strat"]))
    elif plan["kind"] == "brk":
        trades = brk_trades(d_raw, sym)
        dm = brk_prepare(d_raw)
        meter = brk_meter(brk_checks(dm, len(dm) - 1))
    elif plan["kind"] == "pull":
        trades = pull_trades(d_raw, sym)
        dm = pull_prepare(d_raw)
        meter = pull_meter(pull_checks(dm, len(dm) - 1))
    else:
        h4, daily = d_raw.resample("4h").agg(AGG).dropna(), d_raw.resample("1D").agg(AGG).dropna()
        trades = proplan.trades(d_raw, sym, 60, "pro", h4=h4, daily=daily)
        dm = add_indicators(d_raw)
        t4 = proplan.h4_trend(d_raw, h4, 60)
        chk = proplan.pro_pullback_checks(dm, t4, len(dm) - 1)
        dtr = int(proplan.daily_trend(d_raw, daily, 60).iloc[-1])
        meter = pro_meter(chk, dtr, dm.index[-1].weekday() == 0)
    open_t = trades[-1] if trades and trades[-1].get("open") else None
    return {"plan": plan, "trades": trades, "open": open_t, "meter": meter, "price": float(dm.close.iloc[-1]),
            "time": dm.index[-1], "stats": stats(plan)}
