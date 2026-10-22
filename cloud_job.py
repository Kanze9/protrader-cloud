"""One hourly run in the cloud (GitHub Actions): check EURUSD and gold, email new signals / TP1 / exits, and upload a
signal page to the InfinityFree site by FTP.   Local preview:  .venv\\Scripts\\python cloud_job.py --local

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
import meanrev
from config import INSTRUMENTS
from notify import email_ready, send_email

HERE = os.path.dirname(os.path.abspath(__file__))
COST_NOTE = {"EURUSD": "assumes ~0.9 pip cost (Razor)", "XAUUSD": "assumes ~$0.25/oz cost (Razor)"}
CSS = """body{margin:0;background:#070b14;color:#dbe6f5;font-family:-apple-system,Segoe UI,Arial,sans-serif}
.w{max-width:720px;margin:auto;padding:16px}h1{font-size:20px;letter-spacing:.08em;color:#4dd8ff;margin:4px 0 2px}
h2{font-size:17px;letter-spacing:.06em;color:#4dd8ff;margin:22px 0 0}
.m{color:#7d8ca3;font-size:13px}.card{background:#0d1524;border:1px solid #1f2d44;border-radius:12px;padding:14px;margin:12px 0}
.big{font-size:30px;font-weight:700;margin:4px 0}.buy{color:#00e5c0}.sell{color:#ff4d6d}.wait{color:#ffb547}
table{width:100%;border-collapse:collapse;font-size:14px}td{padding:6px 4px;border-bottom:1px solid #16233a}
td.r{text-align:right;color:#9fb0c8}.mono{font-family:Menlo,Consolas,monospace}.ok{color:#00e5c0}.bad{color:#ff4d6d}
td{overflow-wrap:anywhere}@media(max-width:480px){h1{font-size:17px}.big{font-size:24px}table{font-size:13px}.w{padding:12px}}"""


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


def wait_reason(sym: str, strat: str, m: dict) -> str:
    peer = {s: p for _, s, p in aw.MARKETS}.get(strat, "")
    if strat == "mr_gold" and (not m["uptrend"] or m.get("dtrend") != 1):
        return "Gold buys dips only while the daily and H1 trends are both up - not the case now, so it waits."
    if not m.get("calm", True):
        return "A news-spike candle printed in the last 3 hours - waiting for the market to calm down."
    if m.get("breakdown"):
        return "Price just broke the last 30 candles' range (LL/BOS) - a structure break, not a dip. Waiting."
    if m.get("usd_wide") is not None and not m["usd_wide"] < meanrev.USD_WIDE_MAX:
        return f"The whole US dollar is moving ({peer} moved as much as {sym}) - waiting."
    if strat == "mr_gold":
        return f"Uptrend on H1 and daily: waiting to BUY a deep dip (RSI(2) under 2). Now RSI(2) {m['level']:.0f}."
    if m["uptrend"]:
        return (f"Uptrend: waiting to BUY a dip (RSI(2) under 2, or 2-candle RSI(2) sum under 10). "
                f"Now RSI(2) {m['level']:.0f}, 2-candle {m['cum2']:.0f}.")
    return f"Downtrend: waiting to SELL a sharp rally (RSI(2) above 98). Now RSI(2) {m['level']:.0f}."


def section(sym: str, strat: str, peer_sym: str, trades, chk, stats, peer_ok) -> str:
    inst = INSTRUMENTS[sym]
    fmt = lambda x: f"{x:,.{inst.digits}f}"
    last = trades[-1] if trades else None
    open_t = last if last and last.get("open") else None
    if open_t:
        buy = open_t["side"] == 1
        cls, word = ("buy", "BUY (LONG)") if buy else ("sell", "SELL (SHORT)")
        e, s0 = open_t["entry"], open_t["stop0"]
        pips = lambda v: abs(v - e) / inst.pip
        rows = [("Entry", fmt(e), f"{open_t['time'] + pd.Timedelta(hours=1):%m-%d %H:%M} UTC"),
                ("Stop loss", fmt(open_t.get("stop_now", s0)), f"-{pips(s0):.0f} pips" +
                 (" · moved to breakeven" if open_t.get("tp1_time") is not None else ""))]
        for k, ((v, _, pct), hit) in enumerate(zip(open_t.get("tps") or [], open_t.get("tp_hit") or []), 1):
            note = "HIT ✓" if hit else f"{pct}% of past trades reached it"
            if k == 1:
                note += " · close HALF, move SL to entry"
            rows.append((f"TP{k}", fmt(v), f"+{pips(v):.0f} pips · {note}"))
        rows.append(("Final exit", fmt(open_t.get("target_now", e)),
                     f"close the rest when an H1 candle closes back {'above' if buy else 'below'} this 5-candle average"))
        rows.append(("Now", fmt(chk["price"]), f"{open_t.get('open_r', 0):+.2f}R"))
        body = (f"<div class='big {cls}'>IN TRADE · {word}</div><div class='m'>{html.escape(open_t.get('tier') or '')}</div>"
                "<table>" + "".join(f"<tr><td>{k}</td><td class='mono'><b>{v}</b></td><td class='r'>{html.escape(n)}</td></tr>"
                                    for k, v, n in rows) + "</table>")
    else:
        body = f"<div class='big wait'>WAIT</div><div>{html.escape(wait_reason(sym, strat, chk))}</div>"
    if strat == "mr_gold":
        checks = [("H1 uptrend (200-average)", chk["uptrend"], "yes" if chk["uptrend"] else "no"),
                  ("Daily uptrend (50-day average)", chk.get("dtrend") == 1, "yes" if chk.get("dtrend") == 1 else "no")]
    else:
        checks = [("Trend (200-average)", True, "buy dips" if chk["uptrend"] else "sell rallies")]
    checks += [("No news spike (last 3 candles)", chk["calm"], f"{chk['spike']:.1f}×ATR"),
               ("No structure break (30 candles)", not chk.get("breakdown"), "clear" if not chk.get("breakdown") else "break"),
               (f"{sym[:3] if sym != 'XAUUSD' else 'Gold'}-only move ({peer_sym} check)",
                chk.get("usd_wide") is None or chk["usd_wide"] < meanrev.USD_WIDE_MAX,
                f"no {peer_sym} data" if not peer_ok or chk.get("usd_wide") is None else f"{chk['usd_wide']:.2f} / <{meanrev.USD_WIDE_MAX}")]
    chk_html = "".join(f"<tr><td>{n}</td><td class='r {'ok' if ok else 'bad'}'>{'✓' if ok else '✗'} {html.escape(v)}</td></tr>"
                       for n, ok, v in checks)
    hist = [t for t in trades if not t.get("open")][-8:][::-1]
    hist_html = "".join(
        f"<tr><td>{t['time'] + pd.Timedelta(hours=1):%m-%d %H:%M}</td><td class='{'buy' if t['side'] == 1 else 'sell'}'>"
        f"{'BUY' if t['side'] == 1 else 'SELL'}</td><td class='m'>{html.escape(t.get('tier') or '')}</td>"
        f"<td class='r {'ok' if t['r'] > 0 else 'bad'}'>{t['r']:+.2f}R</td></tr>" for t in hist)
    tested = (f"{stats['n']} trades · win {stats['win']:.0f}% · PF {stats['pf']:.2f} (older {stats.get('pf_train', 0):.2f} / "
              f"newer {stats.get('pf_test', 0):.2f}) · 10 years · {COST_NOTE.get(sym, '')}" if stats else "")
    return f"""<h2>{'GOLD · XAUUSD' if sym == 'XAUUSD' else sym}</h2>
<div class="m">last H1 close {fmt(chk['price'])} at {chk['time'] + pd.Timedelta(hours=1):%H:%M} UTC</div>
<div class="card">{body}</div>
<div class="card"><b>Checklist</b><table>{chk_html}</table></div>
<div class="card"><b>Last signals</b><table>{hist_html or "<tr><td>none in the loaded history</td></tr>"}</table>
<div class="m" style="margin-top:8px">Tested: {html.escape(tested)}</div></div>"""


def render(sections) -> str:
    now = pd.Timestamp.now(tz="UTC")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="300">
<meta name="robots" content="noindex,nofollow"><title>ProTrader</title><style>{CSS}</style></head><body><div class="w">
<h1>◆ PROTRADER</h1><div class="m">Updated {now:%Y-%m-%d %H:%M} UTC · data refreshes every hour</div>
{''.join(sections)}
<div class="card m">Testing / education only. Not financial advice.</div>
</div></body></html>"""


def main():
    local = "--local" in sys.argv
    results, sections = {}, []
    for sym, strat, peer_sym in aw.MARKETS:
        try:
            res = aw.plan_trades(sym, strat, peer_sym, with_checks=True)
        except Exception as e:  # noqa: BLE001 - one market failing must not take the page down
            sections.append(f"<h2>{sym}</h2><div class='card bad'>No data this hour: {html.escape(str(e)[:150])}</div>")
            continue
        results[sym] = res
        trades, _, peer_ok, chk = res
        sections.append(section(sym, strat, peer_sym, trades, chk, aw.stats(sym, strat), peer_ok))
    state = {} if local else load_state_ftp()
    if email_ready() and (not local or "--email" in sys.argv):
        aw.check_once(state, send=send_email, results=results)
    elif not local:
        print("Gmail secrets missing - no emails this run")
    page = render(sections)
    if local:
        os.makedirs(os.path.join(HERE, "site"), exist_ok=True)
        out = os.path.join(HERE, "site", "index.html")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(page)
        print("Page written to", out)
        return
    upload_ftp(page, state)
    print("Page and state uploaded:", ", ".join(f"{s} {'IN TRADE' if r[0] and r[0][-1].get('open') else 'wait'}"
                                                for s, r in results.items()))


if __name__ == "__main__":
    main()
