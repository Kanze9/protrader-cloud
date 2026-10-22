"""One hourly run in the cloud (GitHub Actions): run every tested plan (plans.PLANS), email new signals / TP1 / exits,
and upload a signal page to the InfinityFree site by FTP.   Local preview:  .venv\\Scripts\\python cloud_job.py --local

Environment (GitHub secrets): GMAIL_USER, GMAIL_APP_PASSWORD, ALERT_EMAIL_TO, ALERT_LOT, FTP_HOST, FTP_USER, FTP_PASSWORD.
The "already emailed" memory is kept on the FTP space outside the public folder (state.json next to htdocs).
"""
import html
import io
import json
import os
import sys
from ftplib import FTP, error_perm

import pandas as pd

import alert_worker as aw
from config import INSTRUMENTS, TIMEFRAMES
from notify import email_ready, send_email

HERE = os.path.dirname(os.path.abspath(__file__))
COST_NOTE = {"EURUSD": "assumes ~0.9 pip cost (Razor)", "XAUUSD": "assumes ~$0.25/oz cost (Razor)"}
CSS = """body{margin:0;background:#070b14;color:#dbe6f5;font-family:-apple-system,Segoe UI,Arial,sans-serif}
.w{max-width:760px;margin:auto;padding:16px}h1{font-size:20px;letter-spacing:.08em;color:#4dd8ff;margin:4px 0 2px}
h2{font-size:17px;letter-spacing:.06em;color:#4dd8ff;margin:24px 0 0}
.m{color:#7d8ca3;font-size:13px}.card{background:#0d1524;border:1px solid #1f2d44;border-radius:12px;padding:14px;margin:12px 0}
.hd{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.tag{font-size:12px;padding:2px 8px;border-radius:10px;font-weight:700}.tA{background:#063d33;color:#00e5c0}.tB{background:#3d2b06;color:#ffb547}
.big{font-size:26px;font-weight:700;margin:6px 0 2px}.buy{color:#00e5c0}.sell{color:#ff4d6d}.wait{color:#ffb547}
.bar{height:8px;background:#16233a;border-radius:6px;overflow:hidden;margin:6px 0}.bar i{display:block;height:100%}
table{width:100%;border-collapse:collapse;font-size:14px}td{padding:5px 4px;border-bottom:1px solid #16233a}
td.r{text-align:right;color:#9fb0c8}.mono{font-family:Menlo,Consolas,monospace}.ok{color:#00e5c0}.bad{color:#ff4d6d}
details summary{cursor:pointer;color:#9fb0c8;font-size:13px;margin-top:6px}
td{overflow-wrap:anywhere}@media(max-width:480px){h1{font-size:17px}.big{font-size:22px}table{font-size:13px}.w{padding:12px}}"""


def ftp():
    # GitHub passes a missing secret as an empty string, so fall back on empty values too
    host = (os.environ.get("FTP_HOST") or "ftpupload.net").strip()
    user, pw = (os.environ.get("FTP_USER") or "").strip(), os.environ.get("FTP_PASSWORD") or ""
    if not user or not pw:
        raise SystemExit("FTP_USER / FTP_PASSWORD secret is empty - add them in Settings -> Secrets and variables -> Actions.")
    f = FTP(timeout=60)
    f.connect(host, 21)
    f.login(user, pw)
    return f


def load_state_ftp():
    try:
        with ftp() as f:
            buf = io.BytesIO()
            f.retrbinary("RETR state.json", buf.write)
            return json.loads(buf.getvalue().decode("utf-8"))
    except (error_perm, ValueError, KeyError):
        return {}


def upload_ftp(page: str, state: dict):
    with ftp() as f:
        f.storbinary("STOR state.json", io.BytesIO(json.dumps(state, indent=1).encode("utf-8")))
        f.cwd("htdocs")
        # PAGE_NAME: e.g. a long random name like "s-7f3k9q2.html" works as a private link if folder passwords are unavailable
        f.storbinary(f"STOR {os.environ.get('PAGE_NAME') or 'index.html'}", io.BytesIO(page.encode("utf-8")))


def card(res: dict) -> str:
    p = res["plan"]
    tag = f"<span class='tag t{p['tier']}'>{'A · HIGH ACCURACY' if p['tier'] == 'A' else 'B · TREND TRADE'}</span>"
    head = f"<div class='hd'><b>{html.escape(p['name'])} <span class='m'>({p['tf']})</span></b>{tag}</div>"
    if "error" in res:
        return f"<div class='card'>{head}<div class='bad'>No data this hour: {html.escape(res['error'][:150])}</div></div>"
    inst = INSTRUMENTS[p["sym"]]
    fmt = lambda x: f"{x:,.{inst.digits}f}"
    dist = (lambda v, e: f"${abs(v - e):,.2f}") if p["sym"] == "XAUUSD" else (lambda v, e: f"{abs(v - e) / inst.pip:.0f} pips")
    mins = TIMEFRAMES[p["tf"]][1]
    t = res["open"]
    if t:
        buy = t["side"] == 1
        e, s0 = t["entry"], t["stop0"]
        rows = [("Entry", fmt(e), f"{t['time'] + pd.Timedelta(minutes=mins):%m-%d %H:%M} UTC"),
                ("Stop now", fmt(t.get("stop_now", s0)), f"started at {fmt(s0)} (-{dist(s0, e)})")]
        for k, ((v, _, pct), hit) in enumerate(zip(t.get("tps") or [], t.get("tp_hit") or []), 1):
            note = "HIT ✓" if hit else f"{pct}% of past trades reached it"
            rows.append((f"TP{k}", fmt(v), f"+{dist(v, e)} · {note}" + (" · close HALF, SL to entry" if k == 1 else "")))
        if t.get("tps"):
            rows.append(("Final exit", fmt(t.get("target_now", e)), "close the rest on the snap-back across the 5-candle average"))
        else:
            rows.append(("Exit", "trailing", "no fixed TP: keep moving the stop to 'Stop now' each hour"))
        rows.append(("Now", fmt(res["price"]), f"{t.get('open_r', 0):+.2f}R"))
        body = (f"<div class='big {'buy' if buy else 'sell'}'>IN TRADE · {'BUY' if buy else 'SELL'}</div>"
                "<table>" + "".join(f"<tr><td>{k}</td><td class='mono'><b>{v}</b></td><td class='r'>{html.escape(n)}</td></tr>"
                                    for k, v, n in rows) + "</table>")
    else:
        m = res["meter"]
        pct = round(100 * m["met"] / m["total"])
        color = "#00e5c0" if m["ready"] else "#ffb547" if pct >= 60 else "#4a5a75"
        missing = [n for n, ok, _ in m["items"] if not ok]
        body = (f"<div class='big wait'>WAIT</div><div>{html.escape(m['side'])} setup <b>{m['met']}/{m['total']}</b> ready"
                f"{' - waiting for: ' + html.escape(', '.join(missing[:3])) if missing else ''}</div>"
                f"<div class='bar'><i style='width:{pct}%;background:{color}'></i></div>"
                "<details><summary>All conditions</summary><table>" +
                "".join(f"<tr><td>{html.escape(n)}</td><td class='r {'ok' if ok else 'bad'}'>{'✓' if ok else '✗'} {html.escape(v)}</td></tr>"
                        for n, ok, v in m["items"]) + "</table></details>")
    s = res["stats"]
    tested = (f"{s['n']} trades · win {s['win']:.0f}% · PF {s['pf']:.2f} (older {s['pf_train']:.2f} / newer {s['pf_test']:.2f}) · "
              f"~{s['per_month']:.1f}/month · {COST_NOTE.get(p['sym'], '')}" if s else "")
    hist = [x for x in res["trades"] if not x.get("open")][-5:][::-1]
    hist_html = " ".join(f"<span class='{'ok' if x['r'] > 0 else 'bad'}'>{x['r']:+.2f}R</span>" for x in hist)
    return (f"<div class='card'>{head}{body}<div class='m' style='margin-top:8px'>Last results: {hist_html or 'none in view'}"
            f"<br>Tested: {html.escape(tested)}</div></div>")


def render(results) -> str:
    now = pd.Timestamp.now(tz="UTC")
    secs = []
    for sym, title in (("EURUSD", "EURUSD"), ("XAUUSD", "GOLD · XAUUSD")):
        rs = [r for r in results if r["plan"]["sym"] == sym]
        price = next((r["price"] for r in rs if "price" in r), None)
        secs.append(f"<h2>{title}</h2><div class='m'>last close {f'{price:,.{INSTRUMENTS[sym].digits}f}' if price else '-'}</div>"
                    + "".join(card(r) for r in rs))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="300">
<meta name="robots" content="noindex,nofollow"><title>ProTrader</title><style>{CSS}</style></head><body><div class="w">
<h1>◆ PROTRADER</h1><div class="m">Updated {now:%Y-%m-%d %H:%M} UTC · data refreshes every hour<br>
<b class="ok">A</b> = high accuracy (83-91% win, small wins) · <b style="color:#ffb547">B</b> = trend trade (~40% win, trailing stop, bigger wins)</div>
{''.join(secs)}
<div class="card m">The setup meter shows how many of a plan's tested conditions are met now. A signal comes only at full.
Testing / education only. Not financial advice.</div>
</div></body></html>"""


def main():
    local = "--local" in sys.argv
    results = aw.run_all()
    state = {} if local else load_state_ftp()
    if email_ready() and (not local or "--email" in sys.argv):
        aw.check_once(state, send=send_email, results=results)
    elif not local:
        print("Gmail secrets missing - no emails this run")
    page = render(results)
    if local:
        os.makedirs(os.path.join(HERE, "site"), exist_ok=True)
        out = os.path.join(HERE, "site", "index.html")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(page)
        print("Page written to", out)
        return
    upload_ftp(page, state)
    print("Page and state uploaded:", ", ".join(
        f"{r['plan']['id']} {'ERROR' if 'error' in r else 'IN TRADE' if r['open'] else 'wait'}" for r in results))


if __name__ == "__main__":
    main()
