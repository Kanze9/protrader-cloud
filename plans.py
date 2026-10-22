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
    {"id": "gold_a", "sym": "XAUUSD", "tf": "H1", "tier": "A", "kind": "mr", "strat": "mr_gold", "peer": "EURUSD",
     "name": "Gold deep dip"},
    {"id": "gold_a15", "sym": "XAUUSD", "tf": "M15", "tier": "A", "kind": "mr", "strat": "mr_gold15", "peer": "EURUSD",
     "name": "Gold deep dip"},
    {"id": "gold_pull", "sym": "XAUUSD", "tf": "H1", "tier": "B", "kind": "pull", "name": "Gold trend: EMA20 pullback buy"},
    {"id": "gold_pro", "sym": "XAUUSD", "tf": "H1", "tier": "B", "kind": "pro", "name": "Gold trend: Pro Pullback"},
]
TIER_TEXT = {"A": "A · high accuracy", "B": "B · trend trade (trailing stop)"}


def stats(plan: Dict) -> Optional[Dict]:
    try:
        with open(os.path.join(HERE, "models", "strategy_stats.json"), encoding="utf-8") as fh:
            return json.load(fh)["stats"].get(f"plan|{plan['id']}")
    except (OSError, ValueError, KeyError):
        return None


# ---------------------------------------------------------------- tier B: gold EMA20 pullback (buys only)

PULL_STOP_ATR, PULL_TRAIL_ATR = 2.0, 3.0


def pull_prepare(h1: pd.DataFrame) -> pd.DataFrame:
    d = add_indicators(h1)
    meanrev.add_daily_trend(d)
    return d


def pull_checks(d: pd.DataFrame, i: int) -> Dict:
    o, l, c = d.open.values, d.low.values, d.close.values
    e20, e50 = d.ema20.values, d.ema50.values
    res = {"daily_up": d.dtrend.iloc[i] == 1, "ema_up": e20[i] > e50[i], "touch": l[i] <= e20[i],
           "close_above": c[i] > e20[i], "bull": c[i] > o[i]}
    res["signal"] = all(res.values())
    return res


def pull_trades(h1: pd.DataFrame, sym: str = "XAUUSD") -> List[Dict]:
    """Daily uptrend + EMA20 above EMA50, a candle dips to EMA20 and closes bullish back above it -> buy at the close.
    Stop 2xATR, then the stop trails 3xATR behind the best price (no fixed target). 10y gold: PF 1.34, ~41% win."""
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
    return _meter("BUY", [("Daily uptrend (50-day average)", c["daily_up"], ""), ("EMA20 above EMA50 (H1)", c["ema_up"], ""),
                          ("Candle dipped to EMA20", c["touch"], ""), ("Closed back above EMA20", c["close_above"], ""),
                          ("Bullish candle", c["bull"], "")])


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
        if plan["strat"] in ("mr_gold", "mr_gold15"):
            meanrev.add_daily_trend(dm, src=trend_src)
        if plan["strat"] == "mr_gold15":
            meanrev.add_h1_trend(dm, trend_src)
        meter = mr_meter(plan, meanrev.checks(dm, len(dm) - 1, plan["strat"]))
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
