#!/usr/bin/env python3
"""AI Visibility checker (ported from OpenSEO's ai-search module).

For each brand's target + brand keywords, pulls the Google SERP with the AI
Overview block and records:
  - does an AI Overview appear for the keyword?
  - is OUR domain cited in its references?
  - which domains ARE cited (the AI-citation competitors)
Renders ai-visibility.html for the rank-tracker site.

Cost ≈ $0.0035/keyword ≈ $0.25/run. Run weekly:
  python3 scripts/seo-ai-visibility.py
"""
import base64, json, pathlib, sys, urllib.request, datetime
from collections import Counter
import config
import shell as seo_shell

BASE = config.DATA
KEYWORDS = config.KEYWORDS
OUT_JSON = config.DATA / "ai-visibility.json"
OUT_HTML = config.DATA / "ai-visibility.html"
SERP_API = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
LOC_US = 2840


dfs_header = config.dfs_header


def check(header, keyword, domain, loc, lang):
    body = json.dumps([{"keyword": keyword, "location_code": loc, "language_code": lang,
                        "device": "desktop", "depth": 20, "load_async_ai_overview": True}]).encode()
    req = urllib.request.Request(SERP_API, data=body, method="POST",
                                 headers={"Authorization": dfs_header() if header is None else header,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        d = json.load(r)
    cost = d.get("cost", 0)
    items = (d["tasks"][0].get("result") or [{}])[0].get("items") or []
    dom = domain.lower().replace("www.", "")
    ai = next((i for i in items if i.get("type") == "ai_overview"), None)
    if not ai:
        return {"has_ai": False, "cited": False, "refs": []}, cost
    refs = []
    for ref in ai.get("references") or []:
        rd = (ref.get("domain") or "").lower().replace("www.", "")
        if rd:
            refs.append(rd)
    cited = any(rd == dom or rd.endswith("." + dom) for rd in refs)
    return {"has_ai": True, "cited": cited, "refs": refs}, cost


def run():
    header = dfs_header()
    cfg = json.loads(KEYWORDS.read_text())
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    total = 0.0
    result = {"generated": now, "brands": {}}
    for brand, meta in cfg["brands"].items():
        domain = meta["domain"]
        loc = meta.get("location_code", LOC_US)
        lang = meta.get("language_code", "en")
        kws = list(dict.fromkeys(meta.get("target_keywords", []) + meta.get("seed_keywords", [])))
        rows, cite_counter = [], Counter()
        for kw in kws:
            try:
                res, c = check(header, kw, domain, loc, lang)
                total += c
                rows.append({"keyword": kw, **res})
                for rd in res["refs"]:
                    if not (rd == domain or rd.endswith("." + domain)):
                        cite_counter[rd] += 1
            except Exception as e:
                print(f"    {brand} / {kw} FAILED: {e}", flush=True)
        n_ai = sum(1 for r in rows if r["has_ai"])
        n_cited = sum(1 for r in rows if r["cited"])
        result["brands"][brand] = {"domain": domain, "rows": rows,
                                   "top_cited": cite_counter.most_common(10),
                                   "n_ai": n_ai, "n_cited": n_cited}
        print(f"  {brand:22} {len(rows)} kw checked, AI overview on {n_ai}, we're cited in {n_cited}", flush=True)
    OUT_JSON.write_text(json.dumps(result, indent=1))
    print(f"\nTotal cost ${total:.4f} at {now}")
    return result


EXTRA_CSS = """
.grid{display:grid;grid-template-columns:300px 1fr}
.grid>div{padding:14px 18px;min-width:0}
.grid>div:first-child{border-right:1px solid var(--line)}
@media(max-width:900px){.grid{grid-template-columns:1fr}.grid>div:first-child{border-right:none;border-bottom:1px solid var(--line)}}
"""


def render(result):
    blocks = []
    for brand, b in result["brands"].items():
        rows = ""
        for r in b["rows"]:
            if r["has_ai"]:
                status = ('<span class="pillb ok">CITED</span>' if r["cited"]
                          else '<span class="pillb miss">NOT CITED</span>')
                refs = ", ".join(r["refs"][:4]) + ("…" if len(r["refs"]) > 4 else "")
            else:
                status = '<span class="pillb none">NO AI OVERVIEW</span>'
                refs = "—"
            rows += f'<tr><td class="kw">{r["keyword"]}</td><td>{status}</td><td class="who">{refs}</td></tr>'
        cited_list = "".join(f'<tr><td class="kw">{d}</td><td class="num">{n}</td></tr>'
                             for d, n in b["top_cited"]) or '<tr><td colspan=2>—</td></tr>'
        pct = f'{b["n_cited"]}/{b["n_ai"]}' if b["n_ai"] else "0/0"
        blocks.append(f"""
  <section class="card"><div class="chead"><h2>{brand}</h2><span class="dom">{b["domain"]}</span>
    <span class="score">AI Overviews on {b["n_ai"]}/{len(b["rows"])} keywords · cited in {pct}</span></div>
    <div class="grid">
      <div><div class="sublbl">Who AI cites instead (count)</div>
      <div class="scroll"><table><thead><tr><th>Domain</th><th>Citations</th></tr></thead><tbody>{cited_list}</tbody></table></div></div>
      <div><div class="sublbl">Keyword · AI Overview status · cited sources</div>
      <div class="scroll gscroll"><table><thead><tr><th>Keyword</th><th>Status</th><th>Sources cited</th></tr></thead><tbody>{rows}</tbody></table></div></div>
    </div>
  </section>""")
    html = seo_shell.page(
        active="ai-visibility",
        title_html="AI <span>Visibility</span>",
        content="".join(blocks),
        updated=result["generated"],
        right_meta=f'Generated: {result["generated"]} · Google AI Overviews, US desktop',
        refresh_tool="ai-visibility",
        extra_css=EXTRA_CSS)
    OUT_HTML.write_text(html)
    print(f"Report -> {OUT_HTML}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "render":
        render(json.loads(OUT_JSON.read_text()))
    else:
        render(run())
