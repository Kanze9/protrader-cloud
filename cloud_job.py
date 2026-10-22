"""One hourly run in the cloud (GitHub Actions): check EURUSD, email new signals / TP1 / exits, and upload a
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
SYM = aw.SYM
D = INSTRUMENTS[SYM].digits
PIP = INSTRUMENTS[SYM].pip


def ftp():
    f = FTP(os.environ.get("FTP_HOST", "ftpupload.net"), timeout=60)
    f.login(os.environ["FTP_USER"], os.environ["FTP_PASSWORD"])
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


def fmt(x):
    return f"{x:,.{D}f}"


def wait_reason(m: dict) -> str:
    if not m.get("calm", True):
        return "A news-spike candle printed in the last 3 hours - waiting for the market to calm down."
    if m.get("breakdown"):
        return "Price just broke the last 30 candles' range (LL/BOS) - a structure break, not a dip. Waiting."
    if m.get("usd_wide") is not None and not m["usd_wide"] < meanrev.USD_WIDE_MAX:
        return "The whole US dollar is moving (GBPUSD moved as much as EURUSD) - waiting."
    if m["uptrend"]:
        return (f"Uptrend: waiting to BUY a dip (RSI(2) under 2, or 2-candle RSI(2) sum under 10). "
                f"Now RSI(2) {m['level']:.0f}, 2-candle {m['cum2']:.0f}.")
    return f"Downtrend: waiting to SELL a sharp rally (RSI(2) above 98). Now RSI(2) {m['level']:.0f}."


def render(trades, chk, stats, peer_ok) -> str:
    now = pd.Timestamp.now(tz="UTC")
    last = trades[-1] if trades else None
    open_t = last if last and last.get("open") else None
    css = """body{margin:0;background:#070b14;color:#dbe6f5;font-family:-apple-system,Segoe UI,Arial,sans-serif}
.w{max-width:720px;margin:auto;padding:16px}h1{font-size:20px;letter-spacing:.08em;color:#4dd8ff;margin:4px 0 2px}
.m{color:#7d8ca3;font-size:13px}.card{background:#0d1524;border:1px solid #1f2d44;border-radius:12px;padding:14px;margin:12px 0}
.big{font-size:30px;font-weight:700;margin:4px 0}.buy{color:#00e5c0}.sell{color:#ff4d6d}.wait{color:#ffb547}
table{width:100%;border-collapse:collapse;font-size:14px}td{padding:6px 4px;border-bottom:1px solid #16233a}
td.r{text-align:right;color:#9fb0c8}.mono{font-family:Menlo,Consolas,monospace}.ok{color:#00e5c0}.bad{color:#ff4d6d}
td{overflow-wrap:anywhere}@media(max-width:480px){h1{font-size:17px}.big{font-size:24px}table{font-size:13px}.w{padding:12px}}"""
    if open_t:
        buy = open_t["side"] == 1
        cls, word = ("buy", "BUY (LONG)") if buy else ("sell", "SELL (SHORT)")
        e, s0 = open_t["entry"], open_t["stop0"]
        pips = lambda v: abs(v - e) / PIP
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
        body = f"<div class='big wait'>WAIT</div><div>{html.escape(wait_reason(chk))}</div>"
    checks = [("Trend (200-average)", True, "buy dips" if chk["uptrend"] else "sell rallies"),
              ("No news spike (last 3 candles)", chk["calm"], f"{chk['spike']:.1f}×ATR"),
              ("No structure break (30 candles)", not chk.get("breakdown"), "clear" if not chk.get("breakdown") else "break"),
              ("EUR-only move (GBPUSD check)", chk.get("usd_wide") is None or chk["usd_wide"] < meanrev.USD_WIDE_MAX,
               "no GBPUSD data" if not peer_ok or chk.get("usd_wide") is None else f"{chk['usd_wide']:.2f} / <{meanrev.USD_WIDE_MAX}")]
    chk_html = "".join(f"<tr><td>{n}</td><td class='r {'ok' if ok else 'bad'}'>{'✓' if ok else '✗'} {html.escape(v)}</td></tr>"
                       for n, ok, v in checks)
    hist = [t for t in trades if not t.get("open")][-12:][::-1]
    hist_html = "".join(
        f"<tr><td>{t['time'] + pd.Timedelta(hours=1):%m-%d %H:%M}</td><td class='{'buy' if t['side'] == 1 else 'sell'}'>"
        f"{'BUY' if t['side'] == 1 else 'SELL'}</td><td class='m'>{html.escape(t.get('tier') or '')}</td>"
        f"<td class='r {'ok' if t['r'] > 0 else 'bad'}'>{t['r']:+.2f}R</td></tr>" for t in hist)
    tested = (f"{stats['n']} trades · win {stats['win']:.0f}% · PF {stats['pf']:.2f} (older {stats.get('pf_train', 0):.2f} / "
              f"newer {stats.get('pf_test', 0):.2f}) · 10 years · assumes ~0.9 pip cost (Razor)" if stats else "")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="300">
<meta name="robots" content="noindex,nofollow"><title>ProTrader · EURUSD</title><style>{css}</style></head><body><div class="w">
<h1>◆ PROTRADER · EURUSD</h1><div class="m">Updated {now:%Y-%m-%d %H:%M} UTC · last H1 close {fmt(chk['price'])} at
{chk['time'] + pd.Timedelta(hours=1):%H:%M} UTC · refreshes every hour</div>
<div class="card">{body}</div>
<div class="card"><b>Checklist</b><table>{chk_html}</table></div>
<div class="card"><b>Last signals</b><table>{hist_html or "<tr><td>none in the loaded history</td></tr>"}</table></div>
<div class="card m">Tested: {html.escape(tested)}<br>Testing / education only. Not financial advice.</div>
</div></body></html>"""


def main():
    local = "--local" in sys.argv
    result = aw.plan_trades(with_checks=True)
    trades, _, peer_ok, chk = result
    state = {} if local else load_state_ftp()
    if email_ready() and (not local or "--email" in sys.argv):
        aw.check_once(state, send=send_email, result=result)
    elif not local:
        print("Gmail secrets missing - no emails this run")
    page = render(trades, chk, aw.stats(), peer_ok)
    if local:
        os.makedirs(os.path.join(HERE, "site"), exist_ok=True)
        out = os.path.join(HERE, "site", "index.html")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(page)
        print("Page written to", out)
        return
    upload_ftp(page, state)
    print("Page and state uploaded. Open trade:", bool(trades and trades[-1].get("open")))


if __name__ == "__main__":
    main()
