"""10-year stats for every plan in plans.PLANS, from the Dukascopy history in models/ (fetch_dukascopy.py).

Run:  .venv\\Scripts\\python build_plan_stats.py      (updates the plan|<id> entries in models/strategy_stats.json)
H1 plans use ~10 years of H1 (Bitcoin from 2017-10); M15 plans use what models/duka_<sym>_M15.pkl holds. Razor-like costs, one trade at a time,
closed candles only. pf_train / pf_test = older 60% / newer 40% of the trades. Also stores the closed trades' (time, R)
so the app can draw each plan's equity curve.
"""
import json
import os
import warnings

import numpy as np
import pandas as pd

import config
import meanrev
import plans

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "models", "strategy_stats.json")
CURVES = os.path.join(HERE, "models", "plan_curves.json")
COST = {"XAUUSD": 0.25, "EURUSD": 0.00009, "GBPUSD": 0.00011}


def get(sym: str, tf: str):
    p = os.path.join(HERE, "models", f"duka_{sym}_{tf}.pkl")
    if not os.path.exists(p):
        return None
    d = pd.read_pickle(p)
    return d[d.volume > 0]


def stats_for(tr, first, last):
    closed = [t for t in tr if not t.get("open")]
    r = pd.Series([t["r"] for t in closed], dtype=float)
    if r.empty:
        return None
    eq = r.cumsum()
    cut = int(len(r) * 0.6)
    pf = lambda x: float(x[x > 0].sum() / max(1e-9, -x[x < 0].sum()))
    months = max(1.0, (last - first).days / 30.4)
    s = {"n": len(r), "win": float((r > 0).mean() * 100), "avg_r": float(r.mean()), "pf": pf(r), "pf_train": pf(r[:cut]),
         "pf_test": pf(r[cut:]), "per_month": len(r) / months, "from": str(first)[:10], "to": str(last)[:10],
         "max_dd": float((eq.cummax() - eq).max()), "avg_win": float(r[r > 0].mean()) if (r > 0).any() else 0.0,
         "avg_loss": float(r[r < 0].mean()) if (r < 0).any() else 0.0}
    hits = [t["tp_hit"] for t in closed if t.get("tp_hit")]
    if hits:
        s["tp_reach"] = [round(100 * float(np.mean([h[k] for h in hits]))) for k in range(len(hits[0]))]
    yrs = pd.Series(r.values, index=pd.to_datetime([t["time"] for t in closed])).groupby(lambda t: t.year).sum()
    s["years_up"] = f"{int((yrs > 0).sum())}/{len(yrs)}"
    return s


def main():
    for k, v in COST.items():
        config.SPREADS[k] = meanrev.SPREADS[k] = plans.SPREADS[k] = v
    with open(OUT, encoding="utf-8") as fh:
        data = json.load(fh)
    curves = {}
    for p in plans.PLANS:
        d = get(p["sym"], p["tf"])
        if d is None:
            print(p["id"], "no data")
            continue
        res = plans.run_plan(p, get)
        s = stats_for(res["trades"], d.index[0], d.index[-1])
        data["stats"][f"plan|{p['id']}"] = s
        curves[p["id"]] = [[str(t["time"])[:16], round(float(t["r"]), 3)] for t in res["trades"] if not t.get("open")]
        print(f"{p['id']:10s} {s['n']:5d} trades  win {s['win']:3.0f}%  PF {s['pf']:.2f} (old {s['pf_train']:.2f} new {s['pf_test']:.2f})  "
              f"{s['avg_r'] * s['per_month']:+.2f}R/month  dd {s['max_dd']:.1f}R  {s['years_up']} years up", flush=True)
    data["built_plans"] = str(pd.Timestamp.now(tz="UTC"))[:16]
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    with open(CURVES, "w", encoding="utf-8") as fh:
        json.dump(curves, fh)


if __name__ == "__main__":
    main()
