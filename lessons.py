"""Lessons memory: turn the app's own measured track record into short, checkable rules for the AI and the user.

This is how the system 'gains experience': every backtest replay and every journaled signal adds evidence,
and only patterns with enough trades and a meaningful difference become lessons.
"""
from typing import List, Optional

import pandas as pd

MIN_N = 30          # trades needed before a pattern counts
MIN_DIFF = 0.10     # R difference that matters


def _avg(f: pd.DataFrame, mask) -> Optional[tuple]:
    sub = f[mask]
    return (float(sub["r"].mean()), len(sub)) if len(sub) >= MIN_N else None


def _contrast(f: pd.DataFrame, mask, yes: str, no: str) -> Optional[str]:
    a, b = _avg(f, mask), _avg(f, ~mask)
    if not a or not b or abs(a[0] - b[0]) < MIN_DIFF:
        return None
    better, worse = (yes, no) if a[0] > b[0] else (no, yes)
    (ra, na), (rb, nb) = (a, b) if a[0] > b[0] else (b, a)
    return f"{better}: {ra:+.2f}R/trade ({na}) vs {worse}: {rb:+.2f}R ({nb})"


def build(trades: Optional[pd.DataFrame], journal: Optional[pd.DataFrame], symbol: str, tf: str) -> List[str]:
    out: List[str] = []
    if trades is not None and not trades.empty:
        f = trades[trades["filled"]].copy()
        if len(f) >= MIN_N:
            g = f.groupby("setup")["r"].agg(["mean", "size"])
            g = g[g["size"] >= 20].sort_values("mean")
            if len(g):
                best, worst = g.index[-1], g.index[0]
                out.append(f"Best setup here: {best} ({g.loc[best, 'mean']:+.2f}R over {int(g.loc[best, 'size'])}); "
                           f"worst: {worst} ({g.loc[worst, 'mean']:+.2f}R over {int(g.loc[worst, 'size'])}).")
            s = f.groupby("session")["r"].agg(["mean", "size"])
            s = s[s["size"] >= MIN_N]
            if len(s) > 1:
                out.append("By session: " + ", ".join(f"{k.split(' (')[0]} {v['mean']:+.2f}R" for k, v in s.iterrows()) + ".")
            if "hour" in f:
                h = f.groupby("hour")["r"].agg(["mean", "size"])
                h = h[h["size"] >= MIN_N]
                bad = [int(x) for x in h[h["mean"] <= -0.2].index]
                good = [int(x) for x in h[h["mean"] >= 0.1].index]
                if bad:
                    out.append("Weak UTC hours (avoid): " + ", ".join(f"{x:02d}" for x in bad) + ".")
                if good:
                    out.append("Stronger UTC hours: " + ", ".join(f"{x:02d}" for x in good) + ".")
            checks = []
            if "f_htf" in f:
                checks.append(_contrast(f, f["f_htf"] > 15, "with the higher-timeframe trend", "against it"))
            if "f_kz" in f:
                checks.append(_contrast(f, f["f_kz"].astype(bool), "inside killzones", "outside killzones"))
            if "f_confirmed" in f:
                checks.append(_contrast(f, f["f_confirmed"].astype(bool), "with confirmation (CHoCH / rejection)", "without"))
            if "f_adr" in f:
                checks.append(_contrast(f, f["f_adr"].fillna(0) > 100, "after the day's range is exhausted", "before"))
            if "f_inter" in f:
                checks.append(_contrast(f, f["f_inter"] > 0, "when the DXY/yield driver agrees", "when it doesn't"))
            if "f_vwap" in f:
                checks.append(_contrast(f, f["f_vwap"] < 0, "entering at a discount to VWAP (for the side)", "entering at a premium"))
            out += [c + "." for c in checks if c]
            if {"r_1r", "r_tp2"} <= set(f.columns):
                w1, wr = (f["r_1r"] > 0).mean() * 100, (f["r"] > 0).mean() * 100
                out.append(f"Exit style: 1R target wins {w1:.0f}% ({f['r_1r'].mean():+.2f}R avg); current partial plan wins "
                           f"{wr:.0f}% ({f['r'].mean():+.2f}R); all-to-TP2 {f['r_tp2'].mean():+.2f}R. Higher win rate is not the same as profit.")
    if journal is not None and not journal.empty:
        j = journal[(journal["symbol"] == symbol)].dropna(subset=["r_multiple"])
        if len(j):
            r = pd.to_numeric(j["r_multiple"], errors="coerce").dropna()
            out.append(f"Live journal on {symbol}: {len(r)} closed signals, {(r > 0).mean() * 100:.0f}% won, {r.sum():+.1f}R total.")
    return out


def prompt_text(lessons: List[str], symbol: str, tf: str) -> str:
    if not lessons:
        return ""
    return (f"# Lessons from this app's own track record on {symbol} {tf} (walk-forward backtest + live journal)\n"
            + "\n".join(f"- {x}" for x in lessons)
            + "\nWeigh these like a trader weighs years of experience: they are measured, not opinions.")
