"""Buy / sell strength zones: price areas where the market turned several times before, ranked by strength.

Swing lows (support) and swing highs (resistance) that sit close together are grouped into one zone. A zone's strength
(0-99) grows with the number of separate reactions, how hard price bounced away, and how recent the last reaction was.
A zone that price has since closed through is broken and dropped. The active buy zone is the strongest unbroken support
below price, the active sell zone the strongest resistance above it.
"""
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from technical import add_indicators

PIVOT = 5            # a swing needs 5 lower highs / higher lows on each side
MIN_GAP = 10         # reactions closer than 10 candles count as one
LABELS = ((80, "VERY STRONG"), (60, "STRONG"), (40, "MODERATE"), (0, "WEAK"))


def label(score: float) -> str:
    return next(name for lim, name in LABELS if score >= lim)


def _pivots(h, l, k=PIVOT):
    n = len(h)
    hi = [i for i in range(k, n - k) if h[i] == h[i - k:i + k + 1].max()]
    lo = [i for i in range(k, n - k) if l[i] == l[i - k:i + k + 1].min()]
    return hi, lo


def _cluster(idx: List[int], price: np.ndarray, tol: float) -> List[List[int]]:
    groups: List[List[int]] = []
    for i in sorted(idx, key=lambda j: price[j]):
        if groups and price[i] - price[groups[-1][0]] <= tol:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def find_zones(df: pd.DataFrame, upto: Optional[int] = None) -> Dict:
    """Zones from closed candles up to index `upto` (default: all). Returns active buy / sell zones, trend and location."""
    d = add_indicators(df) if "atr" not in df else df
    n = len(d) if upto is None else upto + 1
    h, l, c, o = d.high.values[:n], d.low.values[:n], d.close.values[:n], d.open.values[:n]
    atr = float(np.nanmedian(d.atr.values[max(0, n - 200):n]))
    price = float(c[-1])
    tol = 0.6 * atr
    hi_idx, lo_idx = _pivots(h, l)
    zones = []
    for side, idx, src in (("buy", lo_idx, l), ("sell", hi_idx, h)):
        for g in _cluster(idx, src, tol):
            g = sorted(g)
            reactions = [g[0]]
            for i in g[1:]:
                if i - reactions[-1] >= MIN_GAP:
                    reactions.append(i)
            top, bot = float(max(src[g])), float(min(src[g]))
            if top - bot < 0.3 * atr:                       # give thin zones a minimum height
                mid = (top + bot) / 2
                top, bot = mid + 0.15 * atr, mid - 0.15 * atr
            last = reactions[-1]
            after = c[last + 1:]
            broken = bool((after < bot - 0.25 * atr).any()) if side == "buy" else bool((after > top + 0.25 * atr).any())
            if broken:
                continue
            # how far price moved away within 10 candles of each reaction, in ATR
            bounce = []
            for i in reactions:
                seg = slice(i + 1, min(n, i + 11))
                if seg.start >= n:
                    continue
                bounce.append(((h[seg].max() - src[i]) if side == "buy" else (src[i] - l[seg].min())) / atr)
            bounce_avg = float(np.mean(bounce)) if bounce else 0.0
            age = (n - 1 - last) / max(1, n)                   # 0 = just now, 1 = start of the history
            # up to 75 for 5+ reactions, 10 for strong bounces, 14 for a recent last reaction
            score = min(99.0, 15 * min(len(reactions), 5) + 5 * min(bounce_avg, 2) + 14 * (1 - age))
            zones.append({"side": side, "top": top, "bottom": bot, "reactions": len(reactions), "score": round(score),
                          "label": label(score), "last_time": d.index[last], "first_time": d.index[g[0]], "bounce_atr": bounce_avg})
    buys = [z for z in zones if z["side"] == "buy" and z["bottom"] < price]
    sells = [z for z in zones if z["side"] == "sell" and z["top"] > price]
    buy = max(buys, key=lambda z: (z["score"], z["top"])) if buys else None
    sell = max(sells, key=lambda z: (z["score"], -z["bottom"])) if sells else None
    e50, e200 = float(d.ema50.values[n - 1]), float(d.ema200.values[n - 1])
    trend = "UP" if price > e50 > e200 else "DOWN" if price < e50 < e200 else "SIDEWAYS"
    loc, nearest = "between zones", None
    dist = []
    if buy:
        dist.append(("buy", (price - buy["top"]) / atr))
    if sell:
        dist.append(("sell", (sell["bottom"] - price) / atr))
    if buy and buy["bottom"] <= price <= buy["top"]:
        loc = "inside the buy zone"
    elif sell and sell["bottom"] <= price <= sell["top"]:
        loc = "inside the sell zone"
    elif dist:
        nearest = min(dist, key=lambda x: x[1])
        loc = f"near the {nearest[0]} zone" if nearest[1] < 1.5 else "between zones"
    return {"buy": buy, "sell": sell, "trend": trend, "location": loc, "price": price, "atr": atr,
            "nearest": nearest, "all": zones}
