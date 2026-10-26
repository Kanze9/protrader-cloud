"""Opening-range breakout watcher (the screen from the reel), for gold and EURUSD.

The range is the high and low of the first 15 or 30 minutes after the London (08:00 London) or New York (09:30 New York)
open, with daylight-saving time handled. A breakout is the first 5-minute candle that CLOSES above the range high (buy)
or below the range low (sell) within 2 hours. Tested on 2 years of gold and EURUSD with costs: it broke even or lost
(PF 0.76-1.02), so this is a watching tool, not one of the tested signals.
"""
from typing import Dict, Optional

import pandas as pd

SESSIONS = {"London": ("Europe/London", "08:00"), "New York": ("America/New_York", "09:30")}
WINDOW_MIN = 120          # a breakout must come within 2 hours of the range closing
SESSION_HOURS = 4         # how long the replay runs after the entry


def opening_range(m5: pd.DataFrame, session: str, or_min: int = 15, now: Optional[pd.Timestamp] = None) -> Optional[Dict]:
    """The latest session whose range has started: range high / low, status and the breakout (if any)."""
    tz, hm = SESSIONS[session]
    now = now or pd.Timestamp.now(tz="UTC")
    loc = m5.tz_convert(tz)
    for day in sorted(set(loc.index.date), reverse=True):
        start = pd.Timestamp(f"{day} {hm}", tz=tz)
        if start > now:
            continue
        end = start + pd.Timedelta(minutes=or_min)
        rng = loc[(loc.index >= start) & (loc.index < end)]
        if rng.empty:
            continue
        hi, lo = float(rng.high.max()), float(rng.low.min())
        res = {"session": session, "start": start, "end": end, "high": hi, "low": lo, "or_min": or_min,
               "side": 0, "break_time": None, "entry": None, "stop": None, "day_candles": loc[loc.index >= start - pd.Timedelta(minutes=60)]}
        if now < end:
            res["status"] = "Building range"
            return res
        after = loc[(loc.index >= end) & (loc.index < end + pd.Timedelta(minutes=WINDOW_MIN))]
        closed = after[after.index + pd.Timedelta(minutes=5) <= now]          # closed 5-minute candles only
        for t, b in closed.iterrows():
            if b.close > hi or b.close < lo:
                side = 1 if b.close > hi else -1
                res.update(side=side, break_time=t, entry=float(b.close), stop=lo if side == 1 else hi,
                           status=f"Broke out {'up' if side == 1 else 'down'}")
                return res
        res["status"] = "Watching" if now < end + pd.Timedelta(minutes=WINDOW_MIN) else "No breakout (window closed)"
        return res
    return None
