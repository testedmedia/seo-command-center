#!/usr/bin/env python3
"""Rank-change alerts (PRT-style notifications) — Telegram digest after each
daily tracking run. Compares the two latest runs in ranks.db and reports:
  - keywords that ENTERED or LEFT page 1
  - moves of 5+ positions (volume >= 100, or any pinned brand/local/target term)
  - brand-term rank changes (always)
Silent when nothing meaningful moved.
"""
import json, pathlib, sqlite3, urllib.request, urllib.parse
import config

_tg = config.telegram()
if not _tg:
    raise SystemExit(0)  # Telegram alerts not configured — skip silently
TOK, CHAT = _tg["token"], _tg["chat_id"]
DB = config.DB

con = sqlite3.connect(DB)
runs = [r[0] for r in con.execute("SELECT DISTINCT checked_at FROM kw ORDER BY checked_at DESC LIMIT 2")]
if len(runs) < 2:
    raise SystemExit(0)
latest, prev = runs

cur = {(b, k): (r, v or 0, ib or 0) for b, k, r, v, ib in con.execute(
    "SELECT brand, keyword, rank, search_volume, is_brand FROM kw WHERE checked_at=?", (latest,))}
old = {(b, k): r for b, k, r in con.execute(
    "SELECT brand, keyword, rank FROM kw WHERE checked_at=?", (prev,))}

lines = []
for (b, k), (r, vol, ib) in sorted(cur.items()):
    p = old.get((b, k))
    if r and (p is None or not p) and r <= 10:
        lines.append(f"🟢 {b}: “{k}” entered page 1 → #{r}")
    elif p and p <= 10 and (not r or r > 10):
        lines.append(f"🔴 {b}: “{k}” dropped off page 1 (#{p} → {'#'+str(r) if r else 'gone'})")
    elif r and p and abs(p - r) >= 5 and (vol >= 100 or ib):
        arrow = "📈" if r < p else "📉"
        lines.append(f"{arrow} {b}: “{k}” #{p} → #{r} (vol {vol:,})")
    elif ib == 1 and r != p and (r or p):
        lines.append(f"🏷 {b} brand term: “{k}” {'#'+str(p) if p else '—'} → {'#'+str(r) if r else '—'}")

if not lines:
    raise SystemExit(0)
MAX = 25
shown = lines[:MAX]
if len(lines) > MAX:
    shown.append(f"…and {len(lines) - MAX} more (see dashboard)")
msg = (f"📊 Rank Tracker — changes ({latest} vs {prev})\n\n" + "\n".join(shown)
       + ("\n\n" + config.env("DASHBOARD_URL") if config.env("DASHBOARD_URL") else ""))
data = urllib.parse.urlencode({"chat_id": CHAT, "text": msg, "disable_web_page_preview": "true"}).encode()
urllib.request.urlopen(f"https://api.telegram.org/bot{TOK}/sendMessage", data, timeout=30)
print(f"alert sent: {len(lines)} changes")
