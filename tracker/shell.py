#!/usr/bin/env python3
"""Shared sidebar shell for every rank-tracker page.

All tool pages (competitors, ai-visibility, site-health, link-gap, map-grid)
render inside the SAME app shell as the main rankings dashboard: left sidebar
with Tracked URLs + Reports nav, main column with mhead title row.

Usage:
    import shell
    html = shell.page(active="competitors",
                          title_html="Competitor <span>Gap</span>",
                          content=blocks_html,
                          updated=generated,
                          right_meta=f"Generated: {generated}",
                          refresh_tool="competitors",
                          extra_css=EXTRA_CSS)
"""
import json
import pathlib
import urllib.parse

import config

KEYWORDS = config.KEYWORDS

_ICONS = {
    "rankings": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>',
    "research": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.35-4.35"/></svg>',
    "competitors": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/></svg>',
    "ai-visibility": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM19 15l.9 2.4L22 18.3l-2.1.9L19 21.6l-.9-2.4-2.1-.9 2.1-.9z"/></svg>',
    "site-health": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12h4l3-8 4 16 3-8h6"/></svg>',
    "link-gap": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M10 14a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.5 1.5"/><path d="M14 10a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.5-1.5"/></svg>',
    "map-grid": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 21s-7-5.5-7-11a7 7 0 0 1 14 0c0 5.5-7 11-7 11z"/><circle cx="12" cy="10" r="2.6"/></svg>',
}
_GLOBE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"/></svg>'

_REPORTS = [
    ("rankings", "/", "Rankings", "keywords &amp; positions"),
    ("research", "/research", "Research", "keyword ideas"),
    ("competitors", "/competitors", "Competitors", "keyword gap"),
    ("ai-visibility", "/ai-visibility", "AI Visibility", "AI Overview citations"),
    ("site-health", "/site-health", "Site Health", "technical audit"),
    ("link-gap", "/link-gap", "Link Gap", "links competitors have"),
    ("map-grid", "/map-grid", "Map Grid", "local map-pack coverage"),
]

# Same tokens + sidebar CSS as the main dashboard template, plus the shared
# card/table look every report page uses.
SHELL_CSS = """
:root{--bg:#000;--bg2:#0b0b0e;--card:#0f0f14;--ink:#fff;--ink2:#b6b6bd;--mut:#76767f;
--line:rgba(255,255,255,.13);--line2:rgba(255,255,255,.22);--gold:#ff7a2e;
--grad:linear-gradient(180deg,#ff9142,#ff6a17);--up:#39d98a;--down:#ff5c5c;--blue:#6ab0ff;--ease:cubic-bezier(.22,1,.36,1)}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font:14.5px/1.5 'Inter',-apple-system,sans-serif}
.app{display:grid;grid-template-columns:236px 1fr;min-height:100vh}
aside{background:var(--bg2);border-right:1px solid var(--line);padding:20px 14px;display:flex;flex-direction:column;gap:4px;position:sticky;top:0;height:100vh;overflow-y:auto}
.logo{padding:2px 8px 18px}.logo svg{height:24px;width:auto}.logo svg path{fill:#fff}
.navlbl{font-size:10px;text-transform:uppercase;letter-spacing:.8px;color:var(--mut);padding:8px 10px 6px}
.nav{display:flex;flex-direction:column;gap:2px}
.navitem{position:relative;display:flex;align-items:center;gap:10px;background:none;border:1px solid transparent;border-left:3px solid transparent;border-radius:12px;padding:9px 12px 9px 11px;cursor:pointer;text-align:left;width:100%;transition:background .15s ease,border-color .15s ease;user-select:none;text-decoration:none;color:inherit}
.navitem:hover{background:rgba(255,255,255,.04)}
.navitem.on{background:var(--card);border-color:var(--line);border-left:3px solid var(--gold)}
.navitem .bico{flex:0 0 24px;width:24px;height:24px;display:flex;align-items:center;justify-content:center}
.navitem .bico img{width:20px;height:20px;border-radius:5px;background:#1b1b20}
.navitem .bico svg{width:17px;height:17px;color:var(--mut);transition:color .15s ease}
.navitem.on .bico svg,.navitem:hover .bico svg{color:var(--gold)}
.bfall{width:20px;height:20px;border-radius:5px;background:rgba(255,122,46,.16);color:var(--gold);font-family:'Plus Jakarta Sans';font-weight:800;font-size:11px;display:none;align-items:center;justify-content:center}
.navitem .btxt{display:flex;flex-direction:column;gap:1px;min-width:0;flex:1}
.navitem .bname{font-family:'Plus Jakarta Sans';font-weight:700;font-size:13.5px;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.navitem.on .bname{color:var(--gold)}
.navitem .bmeta{font-size:11px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sfoot{margin-top:auto;padding:12px 10px;border-top:1px solid var(--line);font-size:11px;color:var(--mut);line-height:1.7}
main{padding:22px 26px 48px;min-width:0}
.mhead{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:16px}
.mhead h1{font-family:'Plus Jakarta Sans';font-weight:800;font-size:20px}
.mhead h1 span{color:var(--gold)}
.mhead .upd{margin-left:auto;color:var(--mut);font-size:12px}
.rfr{background:none;border:1px solid rgba(255,122,46,.4);color:var(--gold);border-radius:100px;padding:7px 14px;font-size:13px;cursor:pointer;font-family:'Plus Jakarta Sans';font-weight:700}
.rfr:hover{background:rgba(255,122,46,.12)}
.legend{color:var(--mut);font-size:11.5px;margin:0 0 14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;margin-bottom:16px;overflow:hidden}
.chead{display:flex;align-items:center;gap:11px;padding:13px 18px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.chead h2{font-family:'Plus Jakarta Sans';font-size:15px;font-weight:700}
.dom{color:var(--mut);font-size:12.5px}.score{margin-left:auto;color:var(--mut);font-size:11.5px}
.sublbl{font-size:10.5px;text-transform:uppercase;letter-spacing:.6px;color:var(--mut);margin-bottom:10px}
.scroll{overflow-x:auto}.gscroll{max-height:430px;overflow-y:auto}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.55px;color:var(--mut);padding:9px 13px;border-bottom:1px solid var(--line);white-space:nowrap;background:var(--card);position:sticky;top:0;z-index:1}
td{padding:8px 13px;border-bottom:1px solid rgba(255,255,255,.06);font-size:13px;color:var(--ink2);vertical-align:top}
td.kw{color:var(--ink)}
tr:last-child td{border-bottom:none}
.num{text-align:right;font-variant-numeric:tabular-nums}.vol{font-weight:600;color:var(--ink)}
.who{color:var(--mut);font-size:11.5px}
.hot{display:inline-block;margin-left:7px;font-size:9.5px;font-weight:700;color:var(--gold);border:1px solid rgba(255,122,46,.45);border-radius:100px;padding:1px 6px}
.pillb{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.4px;border-radius:100px;padding:2px 9px;border:1px solid var(--line);white-space:nowrap}
.pillb.ok{color:var(--up);border-color:rgba(57,217,138,.4)}
.pillb.miss{color:var(--down);border-color:rgba(255,92,92,.4)}
.pillb.crit{color:var(--down);border-color:rgba(255,92,92,.4)}
.pillb.warn{color:var(--gold);border-color:rgba(255,122,46,.4)}
.pillb.info{color:var(--blue);border-color:rgba(106,176,255,.4)}
.pillb.none{color:var(--mut)}
footer{color:var(--mut);font-size:11.5px;text-align:center;margin-top:22px}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.72);backdrop-filter:blur(4px);z-index:3000;display:none;align-items:center;justify-content:center;padding:20px}
.overlay.open{display:flex}
.modal{background:#111116;border:1px solid rgba(255,122,46,.3);border-radius:18px;padding:26px;width:100%;max-width:460px;box-shadow:0 30px 80px rgba(0,0,0,.7);max-height:90vh;overflow-y:auto}
.modal h3{font-family:'Plus Jakarta Sans';font-size:17px;font-weight:800;margin-bottom:6px}
.mlbl{font-size:10.5px;text-transform:uppercase;letter-spacing:.6px;color:var(--mut);margin:14px 0 7px}
.chips{display:flex;flex-wrap:wrap;gap:7px}
.chips button{background:var(--card);border:1px solid var(--line);color:var(--ink2);border-radius:100px;padding:6px 13px;font-size:12.5px;cursor:pointer;font-family:'Plus Jakarta Sans';font-weight:600}
.chips button.on{background:rgba(255,122,46,.14);border-color:rgba(255,122,46,.45);color:var(--gold)}
.modal input,.modal textarea{width:100%;background:#000;border:1px solid var(--line2);color:var(--ink);border-radius:12px;padding:11px 14px;font-size:14px;font-family:'Inter';resize:vertical}
.modal input:focus,.modal textarea:focus{outline:none;border-color:var(--gold)}
.mrow{display:flex;gap:10px;justify-content:flex-end;margin-top:18px}
.mbtn{border-radius:100px;padding:10px 20px;font-family:'Plus Jakarta Sans';font-weight:700;font-size:13.5px;cursor:pointer;border:none}
.mbtn.go{background:var(--grad);color:#fff}
.mbtn.ghost{background:none;border:1px solid var(--line);color:var(--ink2)}
.mhint{color:var(--mut);font-size:11.5px;margin-top:6px;line-height:1.5}
#toast{position:fixed;bottom:26px;left:50%;transform:translateX(-50%);background:#16161c;border:1px solid rgba(255,122,46,.4);color:var(--ink);border-radius:100px;padding:11px 22px;font-size:13.5px;z-index:3100;display:none;box-shadow:0 12px 40px rgba(0,0,0,.6)}
@media(max-width:920px){.app{grid-template-columns:1fr}aside{position:static;height:auto;flex-direction:row;flex-wrap:wrap;align-items:center}.nav{flex-direction:row;flex-wrap:wrap}.navitem{width:auto}.sfoot{display:none}}
"""

_REFRESH_JS = """
document.getElementById('refreshbtn').addEventListener('click',function(){
  var b=this;b.textContent='Queuing\\u2026';
  fetch('/refresh?tool=__TOOL__',{method:'POST'}).then(function(r){return r.json();}).then(function(d){b.textContent=d.ok?('\\u2713 Queued ('+d.used+'/'+d.limit+' today) \\u2014 new data in ~3-10 min'):('\\u2717 '+(d.error||'failed'));}).catch(function(){b.textContent='\\u2717 Failed \\u2014 try again';});
});
"""


def _brand_items():
    cfg = json.loads(KEYWORDS.read_text())
    items = []
    for brand, meta in cfg["brands"].items():
        domain = meta["domain"]
        letter = (brand[:1] or "?").upper()
        href = "/#" + urllib.parse.quote(brand)
        items.append(
            f'<a class="navitem" href="{href}"><span class="bico">'
            f'<img src="https://www.google.com/s2/favicons?domain={domain}&amp;sz=64" alt="" '
            f'onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\'">'
            f'<span class="bfall">{letter}</span></span>'
            f'<span class="btxt"><span class="bname">{brand}</span><span class="bmeta">{domain}</span></span></a>')
    return "".join(items)


def _reports_nav(active):
    items = []
    for key, href, name, meta in _REPORTS:
        on = " on" if key == active else ""
        items.append(
            f'<a class="navitem{on}" href="{href}"><span class="bico">{_ICONS[key]}</span>'
            f'<span class="btxt"><span class="bname">{name}</span><span class="bmeta">{meta}</span></span></a>')
    return "".join(items)


def page(active, title_html, content, updated="", right_meta="",
         refresh_tool=None, refresh_label="↻ Re-run",
         extra_css="", head_extra="", body_end="", page_title=None):
    logo = config.logo_html()
    if page_title is None:
        page_title = title_html.replace("<span>", "").replace("</span>", "") + " · " + config.brand_name()
    refresh_btn = f'<button class="rfr" id="refreshbtn">{refresh_label}</button>' if refresh_tool else ""
    refresh_js = ("<script>" + _REFRESH_JS.replace("__TOOL__", refresh_tool) + "</script>") if refresh_tool else ""
    upd = f'<span class="upd">{right_meta}</span>' if right_meta else ""
    return ("""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>""" + page_title + """</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
""" + head_extra + """
<style>""" + SHELL_CSS + extra_css + """</style></head><body>
<div class="app">
<aside>
  <div class="logo">""" + logo + """</div>
  <div class="navlbl">Tracked URLs</div>
  <nav class="nav"><a class="navitem" href="/"><span class="bico">""" + _GLOBE + """</span><span class="btxt"><span class="bname">All URLs</span><span class="bmeta">rankings dashboard</span></span></a>""" + _brand_items() + """</nav>
  <div class="navlbl" style="margin-top:14px">Reports</div>
  <nav class="nav">""" + _reports_nav(active) + """</nav>
  <div class="sfoot">Last update:<br>""" + (updated or "—") + """<br><br>Google US · top 100<br>Updates daily · geo weekly</div>
</aside>
<main>
  <div class="mhead"><h1>""" + title_html + """</h1>""" + upd + refresh_btn + """</div>
""" + content + """
</main>
</div>
""" + refresh_js + body_end + """</body></html>""")
