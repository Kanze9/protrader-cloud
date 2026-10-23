"""Seasonality from long daily history (TradingView TVC / broker symbols): month-of-year and year-end window stats.

Tested 2026-10-22 on gold 2007-2026: December alone up 58% of years (weak), mid-Dec -> end-Jan up 84% (avg +5%),
January the strongest month. DXY/gold: strong same-day inverse link but no next-day predictive power.
"""
import logging
from typing import Dict, Optional

import pandas as pd

import data_feed

log = logging.getLogger(__name__)
LONG_SYMBOL = {"XAUUSD": ("TVC", "GOLD"), "EURUSD": ("PEPPERSTONE", "EURUSD"), "GBPUSD": ("PEPPERSTONE", "GBPUSD"),
               "USDJPY": ("PEPPERSTONE", "USDJPY"), "BTCUSD": ("PEPPERSTONE", "BTCUSD"), "NAS100": ("PEPPERSTONE", "NAS100")}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def stats(symbol: str) -> Optional[Dict]:
    from tvDatafeed import Interval, TvDatafeed
    ex, sym = LONG_SYMBOL.get(symbol, ("PEPPERSTONE", symbol))
    try:
        if data_feed._tv_client is None:
            data_feed._tv_client = TvDatafeed()
        d = data_feed._tv_client.get_hist(symbol=sym, exchange=ex, interval=Interval.in_daily, n_bars=5000)
    except Exception as e:  # noqa: BLE001
        log.warning("seasonality %s failed: %s", symbol, e)
        return None
    if d is None or len(d) < 500:
        return None
    c = d["close"]
    c.index = pd.to_datetime(c.index).normalize()
    m = c.resample("ME").last().pct_change().dropna() * 100
    now = pd.Timestamp.now()
    m = m[~((m.index.year == now.year) & (m.index.month == now.month))]      # drop the unfinished month
    by = m.groupby(m.index.month).agg(["mean", lambda x: (x > 0).mean() * 100, "count"])
    by.columns = ["avg", "up", "n"]
    win = []
    for y in sorted(set(c.index.year)):
        a, b = c[c.index >= f"{y}-12-15"].head(1), c[c.index >= f"{y + 1}-01-31"].head(1)
        if len(a) and len(b):
            win.append((b.iloc[0] / a.iloc[0] - 1) * 100)
    w = pd.Series(win, dtype=float)
    return {"by_month": by, "first_year": int(c.index[0].year),
            "yearend_up": float((w > 0).mean() * 100) if len(w) else None,
            "yearend_avg": float(w.mean()) if len(w) else None, "yearend_n": len(w)}


def text(symbol: str, st: Optional[Dict], now: Optional[pd.Timestamp] = None) -> str:
    if not st:
        return ""
    now = now or pd.Timestamp.now(tz="UTC")
    row = st["by_month"].loc[now.month] if now.month in st["by_month"].index else None
    out = []
    if row is not None:
        strength = "strong" if row["up"] >= 65 else "weak" if row["up"] < 58 else "mild"
        out.append(f"Seasonality ({symbol}, since {st['first_year']}): {MONTHS[now.month - 1]} was up "
                   f"{row['up']:.0f}% of {int(row['n'])} years, avg {row['avg']:+.2f}% ({strength} tendency).")
    in_window = (now.month == 12 and now.day >= 15) or now.month == 1
    if st.get("yearend_up") is not None and (in_window or now.month in (11, 12)):
        out.append(f"Year-end window (mid-Dec -> end-Jan) was up {st['yearend_up']:.0f}% of {st['yearend_n']} years, "
                   f"avg {st['yearend_avg']:+.2f}%" + (" - we are inside it now." if in_window else " - starts mid-December."))
    out.append("Seasonality is a background tilt for days-to-weeks, not a scalp trigger.")
    return " ".join(out)
