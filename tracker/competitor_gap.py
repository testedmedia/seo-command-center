#!/usr/bin/env python3
"""Competitor keyword-gap analysis (ported from OpenSEO's domain module).

Per brand:
  1. competitors_domain  -> top organic competitors (mega-authority domains filtered)
  2. domain_intersection -> keywords each competitor ranks for that WE DON'T (the gap)
Aggregates, dedupes, scores, renders competitors.html for the rank-tracker site.

Cost ≈ $0.05/brand. Run monthly or on demand:
  python3 scripts/seo-competitor-gap.py
"""
import base64, json, pathlib, sys, urllib.request, datetime
import config
import shell as seo_shell

BASE = config.DATA
KEYWORDS = config.KEYWORDS
OUT_JSON = config.DATA / "competitors.json"
OUT_HTML = config.DATA / "competitors.html"
COMP_API = "https://api.dataforseo.com/v3/dataforseo_labs/google/competitors_domain/live"
INTER_API = "https://api.dataforseo.com/v3/dataforseo_labs/google/domain_intersection/live"
LOC_US = 2840
COMPETITORS_PER_BRAND = 3
GAP_LIMIT = 100

# realistic-competitor filter: mega authority sites are not beatable head-to-head
MEGA = {"reddit.com", "wikipedia.org", "amazon.com", "youtube.com", "quora.com",
        "cdc.gov", "epa.gov", "nih.gov", "healthline.com", "webmd.com", "bobvila.com",
        "hgtv.com", "thespruce.com", "angi.com", "yelp.com", "homedepot.com", "lowes.com",
        "forbes.com", "medium.com", "linkedin.com", "facebook.com", "instagram.com",
        "apple.com", "play.google.com", "apps.apple.com", "ringcentral.com", "zendesk.com",
        "mayoclinic.org", "clevelandclinic.org", "familyhandyman.com", "realsimple.com"}


dfs_header = config.dfs_header


def post(url, header, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": header, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def competitors(header, domain, loc, lang):
    d = post(COMP_API, header, [{"target": domain, "location_code": loc, "language_code": lang,
             "limit": 20, "exclude_top_domains": True}])
    cost = d.get("cost", 0)
    out = []
    for it in (d["tasks"][0].get("result") or [{}])[0].get("items") or []:
        dom = it.get("domain", "")
        if dom == domain or dom.endswith(".gov") or dom.endswith(".gov.co") or dom == "scribd.com" \
                or any(dom == m or dom.endswith("." + m) for m in MEGA):
            continue
        m = (it.get("metrics") or {}).get("organic") or {}
        out.append({"domain": dom, "common": it.get("intersections") or 0,
                    "their_kw": m.get("count") or 0, "etv": round(m.get("etv") or 0)})
    return out, cost


def gap(header, competitor, us, loc, lang):
    d = post(INTER_API, header, [{"target1": competitor, "target2": us,
             "location_code": loc, "language_code": lang, "intersections": False,
             "limit": GAP_LIMIT, "order_by": ["keyword_data.keyword_info.search_volume,desc"]}])
    cost = d.get("cost", 0)
    out = []
    for it in (d["tasks"][0].get("result") or [{}])[0].get("items") or []:
        kd = it.get("keyword_data", {}) or {}
        ki = kd.get("keyword_info", {}) or {}
        fd = ((it.get("first_domain_serp_element") or {}).get("serp_item")
              or it.get("first_domain_serp_element") or {})
        out.append({"keyword": kd.get("keyword"), "vol": ki.get("search_volume") or 0,
                    "cpc": round(ki.get("cpc") or 0, 2), "their_rank": fd.get("rank_absolute"),
                    "their_url": fd.get("relative_url") or fd.get("url") or ""})
    return out, cost


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
        comps, c1 = competitors(header, domain, loc, lang)
        total += c1
        override = meta.get("competitors_override")
        if override:
            picked = [{"domain": o, "common": 0, "their_kw": 0, "etv": 0} for o in override]
        else:
            picked = comps[:COMPETITORS_PER_BRAND]
        gaps = {}
        for comp in picked:
            rows, c2 = gap(header, comp["domain"], domain, loc, lang)
            total += c2
            for r in rows:
                k = (r["keyword"] or "").lower()
                if not k:
                    continue
                if k in gaps:
                    gaps[k]["competitors"].append({"domain": comp["domain"], "rank": r["their_rank"], "url": r["their_url"]})
                else:
                    gaps[k] = {"keyword": r["keyword"], "vol": r["vol"], "cpc": r["cpc"],
                               "competitors": [{"domain": comp["domain"], "rank": r["their_rank"], "url": r["their_url"]}]}
        gap_rows = sorted(gaps.values(), key=lambda g: (-len(g["competitors"]), -(g["vol"] or 0)))
        result["brands"][brand] = {"domain": domain, "competitors": comps[:8], "picked": [c["domain"] for c in picked],
                                   "gaps": gap_rows[:150]}
        print(f"  {brand:22} {len(comps)} competitors, gap kws: {len(gap_rows)} "
              f"(top: {gap_rows[0]['keyword'] if gap_rows else '-'})", flush=True)
    OUT_JSON.write_text(json.dumps(result, indent=1))
    print(f"\nTotal cost ${total:.4f} at {now}")
    return result


EXTRA_CSS = """
.grid{display:grid;grid-template-columns:340px 1fr;gap:0}
.grid>div{padding:14px 18px;min-width:0}
.grid>div:first-child{border-right:1px solid var(--line)}
@media(max-width:900px){.grid{grid-template-columns:1fr}.grid>div:first-child{border-right:none;border-bottom:1px solid var(--line)}}
"""


def render(result):
    brands_html = []
    for brand, b in result["brands"].items():
        comps = "".join(
            f'<tr><td class="kw">{c["domain"]}</td><td class="num">{c["common"]:,}</td>'
            f'<td class="num">{c["their_kw"]:,}</td><td class="num">{c["etv"]:,}</td></tr>'
            for c in b["competitors"])
        gaps = ""
        for g in b["gaps"]:
            who = ", ".join(f'{c["domain"]}{"#"+str(c["rank"]) if c["rank"] else ""}'.replace(c["domain"], c["domain"].split(".")[0]) for c in g["competitors"][:3])
            multi = len(g["competitors"])
            gaps += (f'<tr><td class="kw">{g["keyword"]}{"<span class=hot>"+str(multi)+"×</span>" if multi>1 else ""}</td>'
                     f'<td class="num vol">{g["vol"]:,}</td><td class="num">{"$"+format(g["cpc"],".2f") if g["cpc"] else "—"}</td>'
                     f'<td class="who">{who}</td></tr>')
        brands_html.append(f"""
  <section class="card"><div class="chead"><h2>{brand}</h2><span class="dom">{b["domain"]}</span>
    <span class="score">{len(b["gaps"])} gap keywords · vs {", ".join(b["picked"]) or "—"}</span></div>
    <div class="grid">
      <div><div class="sublbl">Top organic competitors</div>
      <div class="scroll"><table><thead><tr><th>Domain</th><th>Shared kw</th><th>Their kw</th><th>Est. traffic</th></tr></thead>
      <tbody>{comps or '<tr><td colspan=4>None found</td></tr>'}</tbody></table></div></div>
      <div><div class="sublbl">Keyword gap — they rank, you don't (sorted: most competitors, then volume)</div>
      <div class="scroll gscroll"><table><thead><tr><th>Keyword</th><th>Volume</th><th>CPC</th><th>Who ranks</th></tr></thead>
      <tbody>{gaps or '<tr><td colspan=4>No gap — or run again later.</td></tr>'}</tbody></table></div></div>
    </div>
  </section>""")
    html = seo_shell.page(
        active="competitors",
        title_html="Competitor <span>Gap</span>",
        content="".join(brands_html),
        updated=result["generated"],
        right_meta=f'Generated: {result["generated"]}',
        refresh_tool="competitors",
        extra_css=EXTRA_CSS)
    OUT_HTML.write_text(html)
    print(f"Report -> {OUT_HTML}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "render":
        render(json.loads(OUT_JSON.read_text()))
    else:
        render(run())
