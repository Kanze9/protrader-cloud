"""Gmail alerts: send an email, and turn a plan trade into an email with entry, SL, TP1-3 and the exit rule."""
import html
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Dict, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv

from config import INSTRUMENTS
from risk import position_size

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def email_ready() -> bool:
    return bool(os.getenv("GMAIL_USER") and os.getenv("GMAIL_APP_PASSWORD"))


def alert_lot() -> float:
    try:
        return float(os.getenv("ALERT_LOT", "0.02"))
    except ValueError:
        return 0.02


def send_email(subject: str, text: str, html_body: Optional[str] = None) -> None:
    user, pw = os.getenv("GMAIL_USER", "").strip(), os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    if not user or not pw:
        raise RuntimeError("Gmail is not set up - run set_email.py first.")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, os.getenv("ALERT_EMAIL_TO", user)
    msg.set_content(text)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as s:
        s.login(user, pw)
        s.send_message(msg)


def _rows_html(rows: List[Tuple[str, str, str]]) -> str:
    out = ""
    for k, v, note in rows:
        out += (f"<tr><td style='padding:4px 10px;color:#555'>{html.escape(k)}</td>"
                f"<td style='padding:4px 10px;font-weight:bold;font-family:monospace'>{html.escape(v)}</td>"
                f"<td style='padding:4px 10px;color:#555'>{html.escape(note)}</td></tr>")
    return out


def signal_email(sym: str, t: Dict, stats: Optional[Dict], lot: float, news: List[Dict], balance: float = 1000.0,
                 leverage: int = 500, shift_hours: int = 1) -> Tuple[str, str, str]:
    """Entry email for an open plan trade (meanrev.trades output)."""
    inst = INSTRUMENTS[sym]
    d = inst.digits
    f = lambda x: f"{x:,.{d}f}"
    buy = t["side"] == 1
    side = "BUY (LONG)" if buy else "SELL (SHORT)"
    e, s0 = t["entry"], t["stop0"]
    ps = position_size(sym, e, s0, balance, 1.0, leverage, lot)
    pip_usd = ps["pip_value_usd"]
    pips = lambda v: abs(v - e) / inst.pip
    # distance as traders say it: pips for FX, dollars of price for gold
    dist = (lambda v: f"${abs(v - e):,.2f} price move") if sym == "XAUUSD" else (lambda v: f"{pips(v):.0f} pips")
    when = t["time"] + pd.Timedelta(hours=shift_hours)       # signal is known when the H1 candle closes
    rows = [("Direction", side, t.get("tier") or ""),
            ("Entry", f(e), f"enter now at market (H1 candle closed {when:%Y-%m-%d %H:%M} UTC)"),
            ("Stop loss", f(s0), f"-{dist(s0)} · -${pips(s0) * pip_usd:,.2f}")]
    for k, (v, lv, pct) in enumerate(t.get("tps") or [], 1):
        note = f"+{dist(v)} · +${pips(v) * pip_usd:,.2f} · {pct}% of past trades reached it"
        if k == 1 and t.get("tp1"):
            note = (f"+{dist(v)} · +${pips(v) * pip_usd / 2:,.2f} on the half you close · {pct}% of past trades reached it"
                    " · CLOSE HALF here and move SL to entry (breakeven)")
        rows.append((f"TP{k}", f(v), note))
    rows.append(("Final exit", f(t.get("target_now", e)),
                 f"close the rest when an H1 candle closes back {'above' if buy else 'below'} the 5-candle average (moves each hour)"))
    per_move = f"$1 move = ${pip_usd * 10:,.2f}" if sym == "XAUUSD" else f"pip value ${pip_usd:,.2f}"
    rows.append(("Size", f"{ps['lots']:.2f} lot", f"{per_move} · margin ${ps['margin_usd']:,.2f} at 1:{leverage}"))
    skip = (f"Skip it if price is already {'above' if buy else 'below'} TP1 ({f(t['tps'][0][0])}) or "
            f"{'below' if buy else 'above'} the stop ({f(s0)})."
            if t.get("tps") else "Skip it if price already moved far from the entry.")
    tested = (f"Tested 10 years: {stats['n']} trades, win {stats['win']:.0f}%, PF {stats['pf']:.2f}"
              f" (older {stats.get('pf_train', 0):.2f} / newer {stats.get('pf_test', 0):.2f}). "
              f"Assumes {'~$0.25/oz' if sym == 'XAUUSD' else '~0.9 pip'} cost (Razor)."
              if stats else "")
    news_txt = "; ".join(f"{n['time']:%H:%M} UTC {n.get('ccy', '')} {n.get('title', '')}" for n in news)
    warn = f"HIGH-IMPACT NEWS SOON: {news_txt} - wait until it is out." if news else "No high-impact news in the next hour."
    subject = f"ProTrader · {('BUY' if buy else 'SELL')} {sym} @ {f(e)} · SL {f(s0)} · TP1 {f(t['tps'][0][0]) if t.get('tps') else '-'}"
    text = "\n".join([f"{side} {sym}", ""] + [f"{k:11s} {v:>12s}  {n}" for k, v, n in rows] +
                     ["", skip, warn, tested, "", "Testing / education only. Not financial advice."])
    html_body = (f"<div style='font-family:Arial,sans-serif'><h2 style='color:{'#0a8f6a' if buy else '#c2185b'}'>"
                 f"{html.escape(side)} {html.escape(sym)}</h2><table style='border-collapse:collapse'>{_rows_html(rows)}</table>"
                 f"<p>{html.escape(skip)}</p><p style='color:{'#c62828' if news else '#555'}'><b>{html.escape(warn)}</b></p>"
                 f"<p style='color:#555'>{html.escape(tested)}</p><p style='color:#999;font-size:12px'>"
                 f"Testing / education only. Not financial advice.</p></div>")
    return subject, text, html_body


def update_email(sym: str, t: Dict, kind: str) -> Tuple[str, str]:
    """Follow-up emails: TP1 hit, or the trade closed."""
    d = INSTRUMENTS[sym].digits
    side = "BUY" if t["side"] == 1 else "SELL"
    if kind == "tp1":
        return (f"ProTrader · TP1 hit {sym} {side} - close half, SL to {t['entry']:,.{d}f}",
                f"TP1 reached on your {sym} {side} from {t['entry']:,.{d}f}.\nClose HALF now and move the stop loss to the entry "
                f"price ({t['entry']:,.{d}f}). The rest closes on the snap-back.")
    res = "WIN" if t["r"] > 0 else "LOSS"
    return (f"ProTrader · {sym} {side} closed: {res} {t['r']:+.2f}R",
            f"The plan closed your {sym} {side} from {t['entry']:,.{d}f} at {t['exit']:,.{d}f} ({t['r']:+.2f}R).\n"
            f"Close any part of the position that is still open.")
