"""HUD design system: sci-fi terminal look (neon cyan panels, ring gauges, status LEDs) that stays easy to read."""
import math
from typing import List, Optional, Tuple

CYAN, TEAL, RED, AMBER, TEXT, MUTED = "#00e5ff", "#00e5c0", "#ff4d6d", "#ffb547", "#d7e3f0", "#6f8299"
STATE_COLOR = {"ok": TEAL, "warn": AMBER, "bad": RED, "na": MUTED}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;800&family=JetBrains+Mono:wght@400;600;700&family=Inter:wght@400;500;600&display=swap');
:root { --cyan:#00e5ff; --teal:#00e5c0; --red:#ff4d6d; --amber:#ffb547; --text:#d7e3f0; --muted:#6f8299;
        --panel:rgba(8,18,32,.82); --line:rgba(0,229,255,.20); }
.stApp { background:
   radial-gradient(1100px 520px at 75% -12%, rgba(0,229,255,.08), transparent 60%),
   radial-gradient(800px 480px at -8% 110%, rgba(0,229,192,.06), transparent 60%), #04070d; }
.stApp::before { content:""; position:fixed; inset:0; pointer-events:none; z-index:0;
   background-image: linear-gradient(rgba(0,229,255,.03) 1px, transparent 1px),
                     linear-gradient(90deg, rgba(0,229,255,.03) 1px, transparent 1px);
   background-size: 44px 44px; }
.block-container { padding-top: .9rem; padding-bottom: 1rem; max-width: 1700px; }
html, body, .stMarkdown, p, label, .stCaption { font-family: 'Inter', 'Microsoft YaHei', 'PingFang SC', sans-serif; }
section[data-testid="stSidebar"] { background: rgba(5,11,20,.95); border-right: 1px solid var(--line); }
section[data-testid="stSidebar"] h3 { font-family:'Orbitron','Inter','Microsoft YaHei',sans-serif; letter-spacing:.14em; color:var(--cyan); font-size:1rem; }
.stTabs [data-baseweb="tab"] { font-family:'Orbitron','Inter','Microsoft YaHei',sans-serif; letter-spacing:.12em; font-size:.72rem; text-transform:uppercase; }
.stButton button[kind="primary"] { font-family:'Orbitron','Inter','Microsoft YaHei',sans-serif; letter-spacing:.2em; text-transform:uppercase;
   background: linear-gradient(90deg, rgba(0,229,255,.18), rgba(0,229,192,.18)); color: var(--cyan);
   border:1px solid rgba(0,229,255,.55); box-shadow: 0 0 18px rgba(0,229,255,.18); }
.stButton button[kind="primary"]:hover { box-shadow: 0 0 26px rgba(0,229,255,.35); color:#fff; }
h5 { font-family:'Orbitron','Inter','Microsoft YaHei',sans-serif; letter-spacing:.16em; font-size:.74rem !important; color:var(--cyan) !important; text-transform:uppercase; }

.hud { position:relative; background:var(--panel); border:1px solid var(--line); border-radius:4px;
       padding:14px 16px; box-shadow: inset 0 0 0 1px rgba(0,229,255,.03), 0 0 28px rgba(0,229,255,.05); color:var(--text); }
.hud::before, .hud::after { content:""; position:absolute; width:14px; height:14px; border:2px solid var(--cyan); opacity:.85; }
.hud::before { top:-1px; left:-1px; border-right:0; border-bottom:0; }
.hud::after { bottom:-1px; right:-1px; border-left:0; border-top:0; }
.hud-t { font-family:'Orbitron','Inter','Microsoft YaHei',sans-serif; font-size:.64rem; letter-spacing:.22em; color:var(--cyan); text-transform:uppercase; opacity:.9; margin-bottom:10px; }
.mono { font-family:'JetBrains Mono', monospace; font-variant-numeric: tabular-nums; }
.muted { color:var(--muted); }
.led { display:inline-block; width:9px; height:9px; border-radius:50%; background:currentColor; box-shadow:0 0 9px currentColor; margin-right:8px; vertical-align:middle; }
.led.live { animation: pulse 2.6s ease-in-out infinite; }
@keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:.3 } }

.hdr { display:flex; align-items:center; gap:22px; flex-wrap:wrap; padding:10px 16px; margin-bottom:10px; }
.hdr .brand { font-family:'Orbitron','Inter','Microsoft YaHei',sans-serif; font-weight:800; letter-spacing:.24em; color:var(--cyan); font-size:.9rem; text-shadow:0 0 12px rgba(0,229,255,.45); }
.hdr .brand small { display:block; font-weight:500; font-size:.55rem; letter-spacing:.32em; color:var(--muted); }
.hdr .px { font-family:'JetBrains Mono'; font-size:1.9rem; font-weight:700; color:#fff; text-shadow:0 0 14px rgba(255,255,255,.15); }
.hdr .kv { font-size:.72rem; color:var(--muted); text-transform:uppercase; letter-spacing:.12em; }
.hdr .kv b { display:block; font-family:'JetBrains Mono'; font-size:.95rem; color:var(--text); letter-spacing:0; text-transform:none; }
.hdr .sp { flex:1; }

.verdict .act { font-family:'Orbitron','Inter','Microsoft YaHei',sans-serif; font-weight:800; font-size:1.9rem; letter-spacing:.08em; line-height:1.1; }
.verdict .sub { font-size:.92rem; margin-top:6px; line-height:1.45; }
.verdict table { width:100%; border-collapse:collapse; margin-top:12px; font-family:'JetBrains Mono'; font-size:.88rem; }
.verdict td { padding:6px 0; border-bottom:1px dashed rgba(0,229,255,.12); }
.verdict td.l { color:var(--muted); font-family:'Inter'; font-size:.78rem; text-transform:uppercase; letter-spacing:.1em; }
.verdict td.r { text-align:right; color:var(--muted); font-size:.8rem; }
.verdict .lbl { font-family:'Orbitron','Inter','Microsoft YaHei',sans-serif; font-size:.58rem; letter-spacing:.2em; color:var(--cyan); margin-top:12px; opacity:.85; }
.verdict .txt { font-size:.86rem; line-height:1.45; margin-top:3px; }
.verdict .warn { color:var(--amber); font-size:.8rem; margin-top:5px; }
.verdict .bad { color:var(--red); font-size:.8rem; margin-top:5px; }

.gauge { text-align:center; padding:10px 6px 8px 6px; }
.gauge .cap { font-size:.82rem; margin-top:-4px; }
.check { list-style:none; padding:0; margin:0; }
.check li { display:flex; align-items:center; padding:5px 0; border-bottom:1px dashed rgba(0,229,255,.10); font-size:.86rem; }
.check li .d { margin-left:auto; color:var(--muted); font-size:.78rem; font-family:'JetBrains Mono'; text-align:right; }
.macro { display:flex; gap:18px; flex-wrap:wrap; font-size:.8rem; }
.macro span b { font-family:'JetBrains Mono'; }
</style>
"""


def ring(pct: float, color: str, label: str, size: int = 92) -> str:
    """Circular confidence ring."""
    pct = max(0.0, min(100.0, float(pct or 0)))
    r = size / 2 - 7
    c = 2 * math.pi * r
    return f"""<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">
  <circle cx="{size/2}" cy="{size/2}" r="{r}" stroke="rgba(0,229,255,.12)" stroke-width="6" fill="none"/>
  <circle cx="{size/2}" cy="{size/2}" r="{r}" stroke="{color}" stroke-width="6" fill="none" stroke-linecap="round"
          stroke-dasharray="{c * pct / 100:.1f} {c:.1f}" transform="rotate(-90 {size/2} {size/2})"
          style="filter: drop-shadow(0 0 5px {color});"/>
  <text x="50%" y="48%" text-anchor="middle" fill="#fff" font-family="JetBrains Mono" font-size="20" font-weight="700">{pct:.0f}</text>
  <text x="50%" y="66%" text-anchor="middle" fill="{MUTED}" font-family="Orbitron" font-size="7" letter-spacing="2">{label}</text>
</svg>"""


def gauge(title: str, value: float, lo: float, hi: float, shown: str, caption: str, color: str,
          center_zero: bool = False) -> str:
    """Semicircle gauge with a plain-language caption underneath."""
    w, h, r = 168, 98, 66
    cx, cy = w / 2, 84
    frac = (max(lo, min(hi, value)) - lo) / (hi - lo)

    def pt(f):
        a = math.pi * (1 - f)
        return cx + r * math.cos(a), cy - r * math.sin(a)

    x0, y0 = pt(0)
    x1, y1 = pt(1)
    start = 0.5 if center_zero else 0.0
    a0, a1 = sorted((start, frac))
    xa, ya = pt(a0)
    xb, yb = pt(a1)
    large = 1 if (a1 - a0) > 0.5 else 0
    nx, ny = pt(frac)
    return f"""<div class="hud gauge"><div class="hud-t">{title}</div>
<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <path d="M{x0:.1f},{y0:.1f} A{r},{r} 0 0 1 {x1:.1f},{y1:.1f}" stroke="rgba(0,229,255,.12)" stroke-width="9" fill="none" stroke-linecap="round"/>
  <path d="M{xa:.1f},{ya:.1f} A{r},{r} 0 {large} 1 {xb:.1f},{yb:.1f}" stroke="{color}" stroke-width="9" fill="none" stroke-linecap="round"
        style="filter: drop-shadow(0 0 6px {color});"/>
  <circle cx="{nx:.1f}" cy="{ny:.1f}" r="5" fill="#fff" style="filter: drop-shadow(0 0 6px {color});"/>
  <text x="{cx}" y="{cy - 14}" text-anchor="middle" fill="#fff" font-family="JetBrains Mono" font-size="20" font-weight="700">{shown}</text>
</svg>
<div class="cap" style="color:{color}">{caption}</div></div>"""


def checklist(items: List[Tuple[str, str, str]], title: str = "Pre-trade checklist · {ok}/{n} green") -> str:
    """items: (label, state ok/warn/bad/na, detail); title may use {ok} and {n}."""
    lis = "".join(f"<li><span class='led' style='color:{STATE_COLOR[s]}'></span>{lbl}<span class='d'>{det}</span></li>"
                  for lbl, s, det in items)
    ok = sum(1 for _, s, _ in items if s == "ok")
    return f"<div class='hud'><div class='hud-t'>{title.format(ok=ok, n=len(items))}</div><ul class='check'>{lis}</ul></div>"


def header(symbol: str, tf: str, price: str, chg: float, cells: List[Tuple[str, str]], feed_ok: bool,
           session: Optional[str], session_state: str, labels: Optional[dict] = None) -> str:
    L = {"terminal": "SCALPING TERMINAL", "change": "Change", "session": "Session",
         "live": "LIVE FEED", "fallback": "FALLBACK FEED", **(labels or {})}
    led = TEAL if feed_ok else AMBER
    sc = STATE_COLOR.get(session_state, MUTED)
    kv = "".join(f"<div class='kv'>{k}<b>{v}</b></div>" for k, v in cells)
    sess = f"<div class='kv'>{L['session']}<b style='color:{sc}'>{session}</b></div>" if session else ""
    return f"""<div class="hud hdr">
  <div class="brand">◆ PROTRADER AI<small>{L['terminal']}</small></div>
  <div><span class="kv">{symbol} · {tf}</span><div class="px">{price}</div></div>
  <div class="kv">{L['change']}<b style="color:{TEAL if chg >= 0 else RED}">{chg:+.2f}%</b></div>
  {sess}{kv}<div class="sp"></div>
  <div class="kv"><span class="led live" style="color:{led}"></span>{L['live'] if feed_ok else L['fallback']}</div>
</div>"""


def stats_card(title: str, equity: List[float], win: float, avg_r: float, pf: float, n: int,
               labels: Optional[dict] = None) -> str:
    """Performance card: equity curve + win-rate ring + average R + profit factor."""
    L = {"win": "Win rate", "avg": "Avg R", "pf": "Profit factor", "trades": "trades", **(labels or {})}
    w, h = 520, 150
    pts = ""
    if len(equity) > 1:
        lo, hi = min(equity + [0]), max(equity + [0])
        span = (hi - lo) or 1
        pts = " ".join(f"{i * w / (len(equity) - 1):.1f},{h - 8 - (v - lo) / span * (h - 16):.1f}" for i, v in enumerate(equity))
        zero_y = h - 8 - (0 - lo) / span * (h - 16)
    else:
        zero_y = h / 2
    col = TEAL if (equity[-1] if equity else 0) >= 0 else RED
    total = equity[-1] if equity else 0
    return f"""<div class="hud" style="display:flex;gap:16px;align-items:stretch;flex-wrap:wrap">
  <div style="flex:2;min-width:300px">
    <div class="hud-t">{title} <span style="margin-left:8px;padding:2px 8px;border:1px solid {col};border-radius:6px;color:{col}" class="mono">{total:+.1f}R</span></div>
    <svg viewBox="0 0 {w} {h}" width="100%" height="{h}" preserveAspectRatio="none">
      <defs><linearGradient id="eqg" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0%" stop-color="{col}" stop-opacity=".28"/><stop offset="100%" stop-color="{col}" stop-opacity="0"/></linearGradient></defs>
      <line x1="0" x2="{w}" y1="{zero_y:.1f}" y2="{zero_y:.1f}" stroke="rgba(0,229,255,.18)" stroke-dasharray="4 4"/>
      {f'<polygon points="0,{h} {pts} {w},{h}" fill="url(#eqg)"/>' if pts else ''}
      {f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2" style="filter:drop-shadow(0 0 4px {col})"/>' if pts else ''}
    </svg>
  </div>
  <div style="flex:1;min-width:190px;display:flex;flex-direction:column;gap:10px">
    <div class="hud" style="display:flex;align-items:center;gap:12px;padding:10px 12px">{ring(win, CYAN, L['win'].upper(), 78)}
      <div><div class="muted" style="font-size:.78rem">{L['win']}</div><div class="mono" style="font-size:.8rem">{n} {L['trades']}</div></div></div>
    <div class="hud" style="padding:10px 12px"><div class="muted" style="font-size:.78rem">{L['avg']}</div>
      <div class="mono" style="font-size:1.5rem;font-weight:700;color:{TEAL if avg_r >= 0 else RED}">{avg_r:+.2f}R</div></div>
    <div class="hud" style="padding:10px 12px"><div class="muted" style="font-size:.78rem">{L['pf']}</div>
      <div class="mono" style="font-size:1.5rem;font-weight:700;color:{TEAL if pf >= 1 else RED}">{pf:.2f}</div></div>
  </div>
</div>"""
