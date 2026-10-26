"""Time Machine: replay the rest of a trade thousands of times from the market's own recent candles.

Each replay strings together random blocks of real recent candles (close-to-close move plus that candle's high and low
around it), starting at the entry price. A replay ends when it touches the stop or the target, or at the horizon.
It shows how wide the outcomes are for that entry / stop / target - it is not a forecast of which one will happen.
"""
from typing import Dict

import numpy as np
import pandas as pd


def simulate(candles: pd.DataFrame, side: int, entry: float, stop: float, target: float, horizon_bars: int,
             n: int = 10_000, lookback_bars: int = 2_000, block: int = 8, seed: int = 7) -> Dict:
    d = candles.tail(lookback_bars + 1)
    prev = d.close.shift(1)
    ret = np.log(d.close / prev).values[1:]
    hi = np.log(d.high / prev).values[1:]                      # candle high / low relative to the previous close
    lo = np.log(d.low / prev).values[1:]
    m = len(ret)
    if m < block * 4:
        raise ValueError("not enough candles to replay")
    rng = np.random.default_rng(seed)
    nblocks = int(np.ceil(horizon_bars / block))
    starts = rng.integers(0, m - block, size=(n, nblocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n, -1)[:, :horizon_bars]
    r, h, l = ret[idx], hi[idx], lo[idx]
    base = np.log(entry) + np.concatenate([np.zeros((n, 1)), np.cumsum(r, axis=1)[:, :-1]], axis=1)   # previous close
    highs, lows, closes = np.exp(base + h), np.exp(base + l), np.exp(base + r)
    if side == 1:
        hit_t, hit_s = highs >= target, lows <= stop
    else:
        hit_t, hit_s = lows <= target, highs >= stop
    big = horizon_bars + 1
    first_t = np.where(hit_t.any(axis=1), hit_t.argmax(axis=1), big)
    first_s = np.where(hit_s.any(axis=1), hit_s.argmax(axis=1), big)
    stop_first = (first_s <= first_t) & (first_s < big)          # same candle -> count the stop (the cautious reading)
    target_first = (first_t < first_s) & (first_t < big)
    neither = ~(stop_first | target_first)
    R = abs(entry - stop)
    final = closes[:, -1]
    end_r = np.where(target_first, abs(target - entry) / R, np.where(stop_first, -1.0, (final - entry) * side / R))
    return {"n": n, "target_first": float(target_first.mean()), "stop_first": float(stop_first.mean()),
            "neither": float(neither.mean()), "avg_r": float(end_r.mean()), "closes": final,
            "paths": closes[:120], "rr": abs(target - entry) / R}
