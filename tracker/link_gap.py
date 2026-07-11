#!/usr/bin/env python3
"""Link-gap analysis (Ahrefs link-intersect style).

Per brand:
  1. Pull the live top organic listings for its #1 target keyword. For LOCAL
     brands, prefer real service-business competitors (SaaS marketplaces filtered
     out) so the surfaced links are citations a local business can replicate.
  2. backlinks/domain_intersection (partial mode) -> referring domains that link
     to those competitors but NOT to us.
  3. HARD junk filter (spam nets, shorteners, mirrors, foreign gov/edu, PBNs,
     un-linkable platforms).
  4. Fetch each survivor's homepage title (free, on the Mini) and CLASSIFY it:
     Directory / Roundup / Peer / Blog / News — each with an outreach angle +
     difficulty, so it's an action list, not a data dump.

Cost ≈ $0.03/brand (API). Run monthly or on demand:
  python3 scripts/seo-link-gap.py
"""
import base64, gzip, io, json, pathlib, re, sys, urllib.request, datetime
import config
import shell as seo_shell

BASE = config.DATA
KEYWORDS = config.KEYWORDS
OUT_JSON = config.DATA / "link-gap.json"
OUT_HTML = config.DATA / "link-gap.html"
SERP_API = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
INTER_API = "https://api.dataforseo.com/v3/backlinks/domain_intersection/live"
LOC_US = 2840
MAX_COMPETITORS = 5
GAP_LIMIT = 200          # pull deep, then filter hard
KEEP_PER_BRAND = 30      # survivors to classify + show
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

# ---- competitor filters -----------------------------------------------------
MEGA = {"reddit.com", "wikipedia.org", "amazon.com", "youtube.com", "quora.com", "yelp.com",
        "cdc.gov", "epa.gov", "nih.gov", "healthline.com", "webmd.com", "bobvila.com",
        "hgtv.com", "thespruce.com", "angi.com", "thumbtack.com", "homedepot.com", "lowes.com",
        "forbes.com", "medium.com", "linkedin.com", "facebook.com", "instagram.com", "pinterest.com",
        "apple.com", "play.google.com", "apps.apple.com", "google.com", "care.com", "taskrabbit.com",
        "mayoclinic.org", "clevelandclinic.org", "familyhandyman.com", "realsimple.com", "scribd.com"}
# for LOCAL brands: these are SaaS/marketplace, not replicable service-business peers
SAAS_MARKETPLACE = {"turno.com", "tidy.com", "airtasker.com", "guesty.com", "hostaway.com",
                    "igms.com", "ownerrez.com", "hospitable.com", "airbnb.com", "vrbo.com",
                    "booking.com", "housecallpro.com", "jobber.com", "getjobber.com", "zenmaid.com",
                    "bookingkoala.com", "launch27.com", "maidcentral.com", "sidehusl.com"}

# ---- junk filters for referring domains -------------------------------------
SHORTENERS = {"bit.ly", "t.co", "tinyurl.com", "lnkd.in", "ow.ly", "buff.ly", "cutt.ly",
              "rebrand.ly", "is.gd", "goo.gl", "shorturl.at", "rb.gy", "trib.al"}
NON_LINKABLE = {"medium.com", "hubspot.com", "clickup.com", "github.com", "gitlab.com",
                "docs.google.com", "sites.google.com", "scribd.com", "slideshare.net",
                "issuu.com", "pinterest.com", "facebook.com", "twitter.com", "x.com",
                "youtube.com", "reddit.com", "quora.com", "notion.so", "substack.com",
                "wordpress.com", "blogspot.com", "wix.com", "weebly.com", "vuink.com",
                "grokipedia.com", "androidrank.org", "zeemly.com", "stackwho.com",
                "keywordseverywhere.com", "cbinsights.com", "beehiiv.com", "jedgar.co"}
JUNK_RE = re.compile(r"(bhs-links|seo-cartel|seomuda|sergechel|-r\d+\.(xyz|online|info)$"
                     r"|\.(xyz|online|shop|top|monster|buzz|click)$)", re.I)
FOREIGN_GOV_EDU = re.compile(r"\.(gov|edu|gob|ac|org)\.[a-z]{2}$", re.I)  # .gov.gh, .edu.pe, .gob.mx


def is_junk(dom, spam, rank, backlinks):
    d = dom.lower()
    if spam >= 25:
        return True
    if d in SHORTENERS or d in NON_LINKABLE:
        return True
    if JUNK_RE.search(d) or FOREIGN_GOV_EDU.search(d):
        return True
    if d.endswith(".edu") and rank < 30:   # spammy .edu injections
        return True
    if rank == 0 and backlinks < 5:        # PBN / throwaway
        return True
    return False


dfs_header = config.dfs_header


def post(url, header, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": header, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def fetch_title(domain):
    try:
        req = urllib.request.Request(f"https://{domain}/",
                                     headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=12) as r:
            raw = r.read(200000)
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            html = raw.decode("utf-8", "replace")
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        return " ".join(m.group(1).split())[:120] if m else ""
    except Exception:
        return ""


def top_competitors(header, keyword, us, loc, lang, location_name=None, local=False):
    payload = {"keyword": keyword, "language_code": lang, "device": "desktop", "depth": 30}
    if location_name:
        payload["location_name"] = location_name
    else:
        payload["location_code"] = loc
    d = post(SERP_API, header, [payload])
    cost = d.get("cost", 0)
    items = (d["tasks"][0].get("result") or [{}])[0].get("items") or []
    out, seen = [], set()
    for it in items:
        if it.get("type") != "organic":
            continue
        dom = (it.get("domain") or "").lower().replace("www.", "")
        if not dom or dom in seen or dom == us or dom.endswith("." + us):
            continue
        if dom.endswith(".gov") or any(dom == m or dom.endswith("." + m) for m in MEGA):
            continue
        if local and (dom in SAAS_MARKETPLACE or any(dom.endswith("." + s) for s in SAAS_MARKETPLACE)):
            continue
        seen.add(dom)
        out.append({"domain": dom, "serp_rank": it.get("rank_absolute")})
        if len(out) >= MAX_COMPETITORS:
            break
    return out, cost


def link_gap(header, competitors, us):
    targets = {str(i + 1): c for i, c in enumerate(competitors[:MAX_COMPETITORS])}
    if not targets:
        return [], 0
    d = post(INTER_API, header, [{"targets": targets, "exclude_targets": [us],
             "intersection_mode": "partial", "limit": GAP_LIMIT, "order_by": ["1.rank,desc"]}])
    cost = d.get("cost", 0)
    rows = []
    for it in (d["tasks"][0].get("result") or [{}])[0].get("items") or []:
        di = it.get("domain_intersection") or {}
        entries = [v for v in di.values() if v]
        if not entries:
            continue
        ref = entries[0].get("target")
        if not ref:
            continue
        rank = max((e.get("rank") or 0) for e in entries)
        spam = max((e.get("backlinks_spam_score") or 0) for e in entries)
        backlinks = sum((e.get("backlinks") or 0) for e in entries)
        if is_junk(ref, spam, rank, backlinks):
            continue
        rows.append({"ref": ref, "rank": rank, "spam": spam, "backlinks": backlinks,
                     "links_to": [targets[k] for k, v in di.items() if v]})
    # sort: more shared competitors first, then domain rank
    rows.sort(key=lambda r: (-len(r["links_to"]), -r["rank"]))
    return rows[:KEEP_PER_BRAND], cost


# ---- classification ---------------------------------------------------------
DIR_RE = re.compile(r"\b(director|listing|list of|top \d|best \d|best |reviews?|compare|comparison"
                    r"|vs\b|catalog|marketplace|tools|apps|software|find a|hub|rankings?|alternatives)\b", re.I)
ROUNDUP_RE = re.compile(r"\b(guide|resources?|how to|tips|ultimate|checklist|ways to|ideas)\b", re.I)
NEWS_RE = re.compile(r"\b(news|magazine|times|post|daily|journal|press|media|today|report)\b", re.I)


def classify(ref, title, niche_words):
    t = (title + " " + ref).lower()
    if any(w in t for w in niche_words):
        return ("Peer / competitor", "Skip (rival) — or pitch a partnership / guest-post swap.", "N/A")
    if DIR_RE.search(t):
        return ("Directory / listing", "Submit your listing (many free, some paid). Highest-certainty link.", "Easy")
    if ROUNDUP_RE.search(t):
        return ("Roundup / resource", "Email the author to be added to the list — lead with a unique stat or angle.", "Medium")
    if NEWS_RE.search(t):
        return ("News / media", "Digital-PR pitch with a data hook or expert quote (HARO-style).", "Hard")
    return ("Blog / editorial", "Guest-post pitch or expert-quote contribution.", "Medium")


def run():
    header = dfs_header()
    cfg = json.loads(KEYWORDS.read_text())
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    total = 0.0
    result = {"generated": now, "brands": {}}
    for brand, meta in cfg["brands"].items():
        us = meta["domain"].lower().replace("www.", "")
        targets = meta.get("target_keywords") or meta.get("seed_keywords") or []
        if not targets:
            continue
        kw = targets[0]
        loc = meta.get("location_code", LOC_US)
        lang = meta.get("language_code", "en")
        loc_name = (meta.get("geo") or {}).get("location_name")
        is_local = bool(loc_name)
        comps, c1 = top_competitors(header, kw, us, loc, lang, loc_name, local=is_local)
        total += c1
        rows, c2 = link_gap(header, [c["domain"] for c in comps], us)
        total += c2
        # classify survivors (fetch titles — free)
        niche = [w for w in re.split(r"\W+", kw.lower()) if len(w) > 3][:3]
        for r in rows:
            r["title"] = fetch_title(r["ref"])
            r["category"], r["angle"], r["difficulty"] = classify(r["ref"], r["title"], niche)
        result["brands"][brand] = {"domain": us, "keyword": kw, "local": is_local,
                                   "competitors": comps, "gaps": rows}
        cats = {}
        for r in rows:
            cats[r["category"]] = cats.get(r["category"], 0) + 1
        print(f"  {brand:22} kw={kw!r} comps={[c['domain'] for c in comps]} kept={len(rows)} {cats}", flush=True)
    OUT_JSON.write_text(json.dumps(result, indent=1))
    print(f"\nTotal cost ${total:.4f} at {now}")
    return result


CAT_CLASS = {"Directory / listing": "ok", "Roundup / resource": "warn", "Blog / editorial": "warn",
             "News / media": "miss", "Peer / competitor": "info"}


EXTRA_CSS = """
.gscroll{max-height:560px}
table{min-width:900px}
td.kw{max-width:280px}
td.kw a{color:var(--ink);text-decoration:none;border-bottom:1px dotted rgba(255,255,255,.25)}
td.kw a:hover{color:var(--gold)}
.ttl{color:var(--mut);font-size:11px;margin-top:3px;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ang{color:var(--ink2);font-size:12px;max-width:320px}
.dif{font-size:12px}
"""


def render(result):
    blocks = []
    for brand, b in result["brands"].items():
        comps = " · ".join(f'{c["domain"]} (#{c["serp_rank"]})' for c in b["competitors"]) or "—"
        rows = ""
        for g in b["gaps"]:
            who = ", ".join(d.split(".")[0] for d in g["links_to"])
            n = len(g["links_to"])
            spam = f'<span class="pillb {"miss" if g["spam"]>=15 else "ok"}">{g["spam"]}</span>'
            cat = f'<span class="pillb {CAT_CLASS.get(g["category"],"warn")}">{g["category"]}</span>'
            rows += (f'<tr><td class="kw"><a href="https://{g["ref"]}" target="_blank" rel="noopener">{g["ref"]}</a>'
                     f'{"<span class=hot>"+str(n)+"×</span>" if n>1 else ""}'
                     f'<div class="ttl">{g.get("title","")}</div></td>'
                     f'<td class="num">{g["rank"]:,}</td><td>{cat}</td>'
                     f'<td class="dif">{g["difficulty"]}</td><td class="ang">{g["angle"]}</td>'
                     f'<td>{spam}</td></tr>')
        note = "local service-business peers" if b.get("local") else "top organic competitors"
        blocks.append(f"""
  <section class="card"><div class="chead"><h2>{brand}</h2><span class="dom">{b["domain"]}</span>
    <span class="score">“{b["keyword"]}” · {note}: {comps}</span></div>
    <div class="scroll gscroll"><table><thead><tr>
      <th>Referring domain — they link to rivals, not you</th><th>DR</th><th>Type</th><th>Effort</th><th>How to get the link</th><th>Spam</th>
    </tr></thead><tbody>{rows or '<tr><td colspan=6 class="kw">No clean link gap found.</td></tr>'}</tbody></table></div>
  </section>""")
    legend = ('<p class="legend">Domains linking to your rivals but not you, junk filtered, '
              'classified by how to earn the link. Green type = easiest. Start at the top of each list.</p>')
    html = seo_shell.page(
        active="link-gap",
        title_html="Link <span>Gap</span>",
        content=legend + "".join(blocks),
        updated=result["generated"],
        right_meta=f'Generated: {result["generated"]}',
        refresh_tool="link-gap",
        extra_css=EXTRA_CSS)
    OUT_HTML.write_text(html)
    print(f"Report -> {OUT_HTML}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "render":
        render(json.loads(OUT_JSON.read_text()))
    else:
        render(run())
