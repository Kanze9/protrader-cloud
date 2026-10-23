"""Trade-quality model ("similar past setups"): gradient boosting on ~15k walk-forward backtest trades.

The raw model is over-confident on data it has seen (80% 'win rate' in-sample vs ~46% on unseen trades), so the app
never shows its raw probability. It shows the *calibrated* outcome: how setups in the same score bucket actually did
on unseen later data (walk-forward test split). Train with:  .venv\\Scripts\\python quality.py <trades.pkl>
"""
import os
import pickle
import sys
from typing import Dict, Optional

import numpy as np
import pandas as pd

PATH = os.path.join(os.path.dirname(__file__), "models", "quality.pkl")
NUM = ["f_htf", "f_vwap", "f_adr", "f_inter", "f_atrpct", "f_mom", "rr_tp2", "points"]
BOOL = ["f_kz", "f_confirmed", "f_confluence"]
CAT = ["setup", "side", "sym", "session"]


def design(d: pd.DataFrame, cols=None) -> pd.DataFrame:
    X = d[NUM].astype(float).copy()
    for b in BOOL:
        X[b] = d[b].astype(float)
    hr = d["hour"].astype(float)
    X["hsin"], X["hcos"] = np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24)
    X = X.join(pd.get_dummies(d[CAT].astype(str), prefix=CAT).astype(float))
    return X.reindex(columns=cols, fill_value=0.0) if cols is not None else X


def train(trades: pd.DataFrame) -> Dict:
    from sklearn.ensemble import HistGradientBoostingClassifier

    t = trades[trades["filled"]].copy().reset_index(drop=True)
    parts = []
    for _, g in t.groupby(["sym", "tf"]):
        g = g.sort_values("time")
        g["split"] = np.where(g["time"] > g["time"].quantile(0.6), "test", "train")
        parts.append(g)
    t = pd.concat(parts).reset_index(drop=True)
    tr, te = t[t.split == "train"], t[t.split == "test"]
    params = dict(max_depth=3, learning_rate=0.04, max_iter=250, l2_regularization=2.0, min_samples_leaf=40, random_state=7)
    m = HistGradientBoostingClassifier(**params).fit(design(tr), (tr["r"] > 0).astype(int))
    cols = list(design(tr).columns)
    p = m.predict_proba(design(te, cols))[:, 1]
    edges = np.quantile(p, [0, .2, .4, .6, .8, 1.0])
    edges[0], edges[-1] = 0.0, 1.0
    b = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, 4)
    calib = [{"lo": float(edges[k]), "hi": float(edges[k + 1]), "n": int((b == k).sum()),
              "win": float((te["r"].values[b == k] > 0).mean() * 100), "avg_r": float(te["r"].values[b == k].mean())}
             for k in range(5)]
    # final model on all data; buckets keep the walk-forward (unseen) outcomes
    full = HistGradientBoostingClassifier(**params).fit(design(t, cols), (t["r"] > 0).astype(int))
    return {"model": full, "cols": cols, "calib": calib, "edges": edges.tolist(), "n_trades": len(t)}


def save(bundle: Dict) -> None:
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "wb") as fh:
        pickle.dump(bundle, fh)


def load() -> Optional[Dict]:
    try:
        with open(PATH, "rb") as fh:
            return pickle.load(fh)
    except (OSError, pickle.UnpicklingError, EOFError):
        return None


def features(ctx, s, symbol: str) -> Dict:
    """Same features the backtest records, for a live setup."""
    d = s.direction
    return {"setup": s.name, "side": s.side, "sym": symbol, "session": ctx.session["quality"],
            "hour": ctx.df.index[-1].hour, "rr_tp2": round(s.rr(s.tp2), 2), "points": s.points,
            "f_htf": ctx.htf_bias * d, "f_vwap": ctx.vwap_z * d,
            "f_adr": ctx.adr_used if ctx.adr_used is not None else 0.0,
            "f_inter": (ctx.inter["bias"] * d) if ctx.inter else 0, "f_atrpct": ctx.atr_pct,
            "f_mom": ctx.momentum * d, "f_kz": bool(ctx.session["killzone"]),
            "f_confirmed": any("confirmed" in x or "rejection" in x for x in s.reasons),
            "f_confluence": any("confluence" in x for x in s.reasons)}


def similar(bundle: Optional[Dict], feats: Dict) -> Optional[Dict]:
    """Calibrated outcome of past setups in the same model-score bucket (unseen-data results)."""
    if not bundle:
        return None
    p = float(bundle["model"].predict_proba(design(pd.DataFrame([feats]), bundle["cols"]))[:, 1][0])
    k = int(np.clip(np.searchsorted(bundle["edges"], p, side="right") - 1, 0, 4))
    c = bundle["calib"][k]
    return {"bucket": k + 1, "win": c["win"], "avg_r": c["avg_r"], "n": c["n"]}


if __name__ == "__main__":
    src = sys.argv[1]
    b = train(pd.read_pickle(src))
    save(b)
    print(f"trained on {b['n_trades']} trades; unseen-data buckets:")
    for i, c in enumerate(b["calib"], 1):
        print(f"  bucket {i}: score {c['lo']:.2f}-{c['hi']:.2f} -> won {c['win']:.0f}%, avg {c['avg_r']:+.3f}R ({c['n']})")
