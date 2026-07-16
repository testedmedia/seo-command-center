#!/usr/bin/env python3
"""Rankings dashboard — Pro-Rank-Tracker-style platform on DataForSEO + GSC.

Per brand, merges 3 keyword sources, keeps the top `track_cap` (default 100)
worth-it keywords (score = search volume + GSC impressions):
  1. ranked_keywords   — one cheap Labs call (~$0.02-0.03/domain), all live positions
  2. keyword research  — keyword_suggestions off seeds, CACHED 30 days
  3. GSC queries       — free, last 28 days, impressions/clicks/position
Optional geo SERP re-check for local brands (~$0.015/kw, weekly only).

Dashboard (PRT-style): sidebar URL groups, visibility score, avg rank,
1-update/7d/30d deltas, best-ever rank, per-keyword history graphs,
rank distribution, pagination, stars, CSV export.

Usage: seo-rank-tracker.py [track|render|both] [--refresh-research] [--skip-geo]
"""
import config
import base64, json, pathlib, sqlite3, sys, urllib.request, urllib.parse, datetime

BASE = config.DATA
DB = config.DB
KEYWORDS = config.KEYWORDS
RESEARCH_CACHE = config.RESEARCH_CACHE
OUT_HTML = config.DATA / "dashboard.html"
LOC_US = 2840
RANKED_API = "https://api.dataforseo.com/v3/dataforseo_labs/google/ranked_keywords/live"
SUGGEST_API = "https://api.dataforseo.com/v3/dataforseo_labs/google/keyword_suggestions/live"
SERP_API = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
RESEARCH_MAX_AGE_DAYS = 30


dfs_header = config.dfs_header


def gsc_token():
    try:
        secret_path, tokens_path = config.gsc_paths()
        sec = json.load(open(secret_path))["web"]
        tok = json.load(open(tokens_path))
        data = urllib.parse.urlencode({
            "client_id": sec["client_id"], "client_secret": sec["client_secret"],
            "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"}).encode()
        r = urllib.request.urlopen("https://oauth2.googleapis.com/token", data, timeout=30)
        return json.load(r)["access_token"]
    except Exception as e:
        print(f"  (GSC auth unavailable: {e})", flush=True)
        return None


def post(url, header, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": header, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def init_db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS kw(
        checked_at TEXT, brand TEXT, domain TEXT, keyword TEXT,
        rank INTEGER, search_volume INTEGER, cpc REAL, url TEXT,
        source TEXT, geo TEXT, geo_rank INTEGER,
        gsc_impressions INTEGER, gsc_clicks INTEGER, gsc_position REAL)""")
    for ddl in ("ALTER TABLE kw ADD COLUMN is_brand INTEGER DEFAULT 0",
                "ALTER TABLE kw ADD COLUMN mobile_rank INTEGER",
                "ALTER TABLE kw ADD COLUMN map_rank INTEGER"):
        try:
            con.execute(ddl)
        except sqlite3.OperationalError:
            pass
    con.commit()
    return con


def ranked(header, domain, loc=LOC_US, lang="en"):
    d = post(RANKED_API, header, [{"target": domain, "location_code": loc, "language_code": lang,
             "limit": 1000, "order_by": ["keyword_data.keyword_info.search_volume,desc"]}])
    out = {}
    task = d["tasks"][0]
    if task.get("result") and task["result"][0].get("items"):
        for it in task["result"][0]["items"]:
            kd = it.get("keyword_data", {}); ki = kd.get("keyword_info", {}) or {}
            se = (it.get("ranked_serp_element", {}) or {}).get("serp_item", {}) or {}
            k = (kd.get("keyword") or "").lower()
            if k:
                out[k] = {"keyword": kd.get("keyword"), "rank": se.get("rank_absolute"),
                          "search_volume": ki.get("search_volume") or 0, "cpc": ki.get("cpc") or 0,
                          "url": se.get("relative_url") or se.get("url") or "", "source": "ranked"}
    return out, d.get("cost", 0)


def research(header, cfg, force=False):
    cache = {}
    if RESEARCH_CACHE.exists():
        cache = json.loads(RESEARCH_CACHE.read_text())
    gen = cache.get("generated")
    fresh = False
    if gen and not force:
        age = (datetime.date.today() - datetime.date.fromisoformat(gen)).days
        fresh = age <= RESEARCH_MAX_AGE_DAYS
    out = dict(cache.get("brands", {})) if fresh else {}
    to_fetch = [b for b in cfg["brands"] if b not in out]
    if fresh and not to_fetch:
        print(f"  research: using cache from {gen} (refreshes after {RESEARCH_MAX_AGE_DAYS}d)", flush=True)
        return out, 0.0
    cost = 0.0
    for brand in to_fetch:
        meta = cfg["brands"][brand]
        rows = {}
        for seed in meta.get("seed_keywords", []):
            try:
                d = post(SUGGEST_API, header, [{"keyword": seed, "location_code": meta.get("location_code", LOC_US),
                         "language_code": meta.get("language_code", "en"),
                         "limit": 40, "order_by": ["keyword_info.search_volume,desc"]}])
                cost += d.get("cost", 0)
                for it in (d["tasks"][0].get("result") or [{}])[0].get("items") or []:
                    ki = it.get("keyword_info", {}) or {}
                    k = (it.get("keyword") or "").lower()
                    if k and k not in rows:
                        rows[k] = {"keyword": it.get("keyword"), "search_volume": ki.get("search_volume") or 0,
                                   "cpc": ki.get("cpc") or 0}
            except Exception as e:
                print(f"    suggest '{seed}' failed: {e}", flush=True)
        out[brand] = rows
    RESEARCH_CACHE.write_text(json.dumps({"generated": gen if fresh else str(datetime.date.today()), "brands": out}))
    print(f"  research: refreshed {', '.join(to_fetch)} (${cost:.4f})", flush=True)
    return out, cost


def gsc_queries(at, site):
    if not at or not site:
        return {}
    end = datetime.date.today() - datetime.timedelta(days=3)
    start = end - datetime.timedelta(days=28)
    body = json.dumps({"startDate": str(start), "endDate": str(end),
                       "dimensions": ["query"], "rowLimit": 500}).encode()
    url = f"https://searchconsole.googleapis.com/webmasters/v3/sites/{urllib.parse.quote(site, safe='')}/searchAnalytics/query"
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {at}", "Content-Type": "application/json"})
    out = {}
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
        for row in d.get("rows", []):
            out[row["keys"][0].lower()] = {"impr": int(row.get("impressions", 0)),
                                           "clicks": int(row.get("clicks", 0)),
                                           "pos": round(row.get("position", 0), 1)}
    except Exception as e:
        print(f"    GSC '{site}' failed: {e}", flush=True)
    return out


def geo_check(header, keywords, location_name, domain):
    out, cost = {}, 0.0
    dom = domain.lower().replace("www.", "")
    for kw in keywords:
        try:
            d = post(SERP_API, header, [{"keyword": kw, "location_name": location_name,
                     "language_code": "en", "device": "desktop", "depth": 100}])
            cost += d.get("cost", 0)
            items = (d["tasks"][0].get("result") or [{}])[0].get("items") or []
            gr = None
            for it in items:
                if it.get("type") == "organic":
                    idom = (it.get("domain") or "").lower().replace("www.", "")
                    if idom == dom or idom.endswith("." + dom):
                        gr = it.get("rank_absolute"); break
            out[kw] = gr
        except Exception as e:
            print(f"    geo '{kw}' failed: {e}", flush=True)
    return out, cost


def select_worthy(merged, cap, brand_set=frozenset()):
    """Brand terms are always tracked; then ranked kws; then highest-signal rest."""
    def score(v):
        return (v.get("search_volume") or 0) + (v.get("gsc", {}).get("impr") or 0)
    chosen = {k: v for k, v in merged.items() if k in brand_set}
    ranked_rows = sorted([v for v in merged.values()
                          if v["source"] == "ranked" and v["keyword"].lower() not in chosen],
                         key=score, reverse=True)
    for v in ranked_rows:
        if len(chosen) >= cap:
            break
        chosen[v["keyword"].lower()] = v
    rest = sorted([v for v in merged.values() if v["keyword"].lower() not in chosen],
                  key=score, reverse=True)
    for v in rest:
        if len(chosen) >= cap:
            break
        if score(v) <= 0:
            continue
        chosen[v["keyword"].lower()] = v
    return list(chosen.values())


def local_serp(header, keywords, domain, location_name, lang, brand_name=""):
    """SERP + map-pack position for local terms, searched from the brand's city.
    Returns ({kw: (organic_rank, url)}, {kw: map_pack_rank}, cost)."""
    out, maps, cost = {}, {}, 0.0
    dom = domain.lower().replace("www.", "")
    bname = brand_name.lower()
    for kw in keywords:
        try:
            d = post(SERP_API, header, [{"keyword": kw, "location_name": location_name,
                     "language_code": lang, "device": "desktop", "depth": 100}])
            cost += d.get("cost", 0)
            items = (d["tasks"][0].get("result") or [{}])[0].get("items") or []
            for it in items:
                t = it.get("type")
                if t == "organic" and kw not in out:
                    idom = (it.get("domain") or "").lower().replace("www.", "")
                    if idom == dom or idom.endswith("." + dom):
                        out[kw] = (it.get("rank_absolute"), it.get("url") or "")
                elif t == "local_pack" and kw not in maps:
                    idom = (it.get("domain") or "").lower().replace("www.", "")
                    title = (it.get("title") or "").lower()
                    if idom == dom or idom.endswith("." + dom) or (bname and bname in title):
                        maps[kw] = it.get("rank_group") or it.get("rank_absolute")
        except Exception as e:
            print(f"    local serp '{kw}' failed: {e}", flush=True)
    return out, maps, cost


def brand_serp(header, keywords, domain, loc, lang, device="desktop"):
    """True SERP position for brand terms (exact check, not the Labs index)."""
    out, cost = {}, 0.0
    dom = domain.lower().replace("www.", "")
    for kw in keywords:
        try:
            d = post(SERP_API, header, [{"keyword": kw, "location_code": loc,
                     "language_code": lang, "device": device, "depth": 100}])
            cost += d.get("cost", 0)
            items = (d["tasks"][0].get("result") or [{}])[0].get("items") or []
            for it in items:
                if it.get("type") == "organic":
                    idom = (it.get("domain") or "").lower().replace("www.", "")
                    if idom == dom or idom.endswith("." + dom):
                        out[kw] = (it.get("rank_absolute"), it.get("url") or "")
                        break
        except Exception as e:
            print(f"    brand serp '{kw}' failed: {e}", flush=True)
    return out, cost


def track(force_research=False, skip_geo=False):
    header = dfs_header()
    at = gsc_token()
    cfg = json.loads(KEYWORDS.read_text())
    cap = int(cfg.get("track_cap", 100))
    con = init_db()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    total = 0.0
    res_all, rc = research(header, cfg, force=force_research)
    total += rc
    for brand, meta in cfg["brands"].items():
        domain = meta["domain"]
        loc = meta.get("location_code", LOC_US)
        lang = meta.get("language_code", "en")
        merged, c1 = ranked(header, domain, loc, lang)
        total += c1
        for k, v in (res_all.get(brand) or {}).items():
            if k not in merged:
                merged[k] = {"keyword": v["keyword"], "rank": None, "search_volume": v["search_volume"],
                             "cpc": v["cpc"], "url": "", "source": "research"}
        gsc = gsc_queries(at, meta.get("gsc_site"))
        for k, g in gsc.items():
            if k in merged:
                merged[k]["gsc"] = g
            else:
                merged[k] = {"keyword": k, "rank": None, "search_volume": 0, "cpc": 0,
                             "url": "", "source": "gsc", "gsc": g}
        brand_set = {b.lower() for b in meta.get("brand_keywords", [])}
        local_set = {b.lower() for b in meta.get("local_keywords", [])}
        target_set = {b.lower() for b in meta.get("target_keywords", [])}
        for bk, src in [(b, "brand") for b in meta.get("brand_keywords", [])] + \
                       [(l, "local") for l in meta.get("local_keywords", [])] + \
                       [(t, "target") for t in meta.get("target_keywords", [])]:
            if bk.lower() not in merged:
                merged[bk.lower()] = {"keyword": bk, "rank": None, "search_volume": 0, "cpc": 0,
                                      "url": "", "source": src}
        blocked = {b.lower() for b in meta.get("blocked_keywords", [])}
        for bk in blocked:
            merged.pop(bk, None)
        brand_cap = int(meta.get("track_cap", cap))
        selected = select_worthy(merged, brand_cap, brand_set | local_set | target_set)
        if not skip_geo:
            # brand terms: national SERP; local terms: SERP from the brand's geo city
            if brand_set or target_set:
                bres, cb = brand_serp(header, sorted(brand_set | target_set), domain, loc, lang)
                total += cb
                for k, (rr, uu) in bres.items():
                    row = merged.get(k.lower())
                    if row and rr:
                        row["rank"] = rr
                        if uu:
                            row["url"] = uu
            if target_set:
                mres, cm = brand_serp(header, sorted(target_set), domain, loc, lang, device="mobile")
                total += cm
                for k, (rr, _uu) in mres.items():
                    row = merged.get(k.lower())
                    if row:
                        row["mobile"] = rr
            if local_set:
                loc_name = (meta.get("geo") or {}).get("location_name")
                if loc_name:
                    lres, lmaps, cl = local_serp(header, sorted(local_set), domain, loc_name, lang, brand)
                else:
                    lres, cl = brand_serp(header, sorted(local_set), domain, loc, lang)
                    lmaps = {}
                total += cl
                for k, (rr, uu) in lres.items():
                    row = merged.get(k.lower())
                    if row and rr:
                        row["rank"] = rr
                        if uu:
                            row["url"] = uu
                for k, mp in lmaps.items():
                    row = merged.get(k.lower())
                    if row and mp:
                        row["map"] = mp
        # carry forward last SERP-checked rank for pinned terms on index-only (daily) runs,
        # so brand/local positions don't blank out between Monday full checks
        pinned = brand_set | local_set | target_set
        if pinned:
            prev_run = con.execute("SELECT MAX(checked_at) FROM kw WHERE brand=?", (brand,)).fetchone()[0]
            if prev_run:
                for prow in con.execute(
                        "SELECT keyword, rank, url, mobile_rank, map_rank FROM kw WHERE checked_at=? AND brand=?",
                        (prev_run, brand)):
                    row = merged.get(prow[0].lower())
                    if row and prow[0].lower() in pinned:
                        if prow[1] and not row.get("rank"):
                            row["rank"] = prow[1]
                            if not row.get("url"):
                                row["url"] = prow[2] or ""
                        if prow[3] and not row.get("mobile"):
                            row["mobile"] = prow[3]
                        if prow[4] and not row.get("map"):
                            row["map"] = prow[4]
        geo_ranks, geo_label = {}, None
        if meta.get("geo"):
            geo_label = meta["geo"]["label"]
            if not skip_geo:
                top = sorted(selected, key=lambda x: x.get("search_volume") or 0, reverse=True)
                top_kw = [t["keyword"] for t in top[:meta.get("geo_top_n", 5)]]
                geo_ranks, c3 = geo_check(header, top_kw, meta["geo"]["location_name"], domain)
                total += c3
        for v in selected:
            g = v.get("gsc", {})
            con.execute("INSERT INTO kw VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                now, brand, domain, v["keyword"], v.get("rank"),
                v.get("search_volume") or 0, v.get("cpc") or 0, v.get("url") or "",
                v.get("source"), geo_label, geo_ranks.get(v["keyword"]),
                g.get("impr"), g.get("clicks"), g.get("pos"),
                1 if v["keyword"].lower() in brand_set else (2 if v["keyword"].lower() in local_set
                else (3 if v["keyword"].lower() in target_set else 0)),
                v.get("mobile"), v.get("map")))
        con.commit()
        srcs = {s: sum(1 for v in selected if v["source"] == s) for s in ("ranked", "research", "gsc")}
        nbrand = sum(1 for v in selected if v["keyword"].lower() in brand_set)
        nlocal = sum(1 for v in selected if v["keyword"].lower() in local_set)
        ntarget = sum(1 for v in selected if v["keyword"].lower() in target_set)
        geo_note = f", geo[{geo_label}]={sum(1 for x in geo_ranks.values() if x)}" if (geo_label and not skip_geo) else ""
        print(f"  {brand:22} {len(selected)}/{brand_cap} kw kept of {len(merged)} found "
              f"(ranked {srcs['ranked']}, research {srcs['research']}, gsc {srcs['gsc']}, brand {nbrand}, local {nlocal}, target {ntarget}{geo_note})", flush=True)
    print(f"\nTotal cost ${total:.4f} at {now}")


def render():
    con = init_db()
    cfg = json.loads(KEYWORDS.read_text())
    runs = [r[0] for r in con.execute("SELECT DISTINCT checked_at FROM kw ORDER BY checked_at").fetchall()]
    latest = runs[-1] if runs else None
    prev = runs[-2] if len(runs) > 1 else None
    latest_dt = datetime.datetime.strptime(latest, "%Y-%m-%d %H:%M") if latest else None

    def run_at_days_back(days):
        """Latest run at least `days` old; falls back to the earliest run if history is shorter."""
        if not latest_dt or len(runs) < 2:
            return None
        cutoff = latest_dt - datetime.timedelta(days=days)
        older = [r for r in runs[:-1] if datetime.datetime.strptime(r, "%Y-%m-%d %H:%M") <= cutoff]
        return older[-1] if older else runs[0]

    run7 = run_at_days_back(7)
    run30 = run_at_days_back(30)

    hist = {}
    for ca, brand, kw, rank in con.execute("SELECT checked_at,brand,keyword,rank FROM kw ORDER BY checked_at"):
        hist.setdefault((brand, kw), []).append((ca, rank))

    rows_json, brands_json, hist_json = [], [], {}
    for brand, meta in cfg["brands"].items():
        rows = con.execute("""SELECT keyword,rank,search_volume,cpc,url,source,geo,geo_rank,
            gsc_impressions,gsc_clicks,gsc_position,is_brand,mobile_rank,map_rank FROM kw WHERE checked_at=? AND brand=?
            ORDER BY is_brand DESC, search_volume DESC""", (latest, brand)).fetchall() if latest else []
        geo_label = next((r[6] for r in rows if r[6]), None)
        for kw, rank, vol, cpc, url, source, geo, grank, impr, clicks, gpos, isb, mrank, maprank in rows:
            h = hist.get((brand, kw), [])
            hmap = dict(h)
            ranks_only = [r for _, r in h if r]
            best = min(ranks_only) if ranks_only else None
            p1 = hmap.get(prev) if prev else None
            p7 = hmap.get(run7) if run7 else None
            p30 = hmap.get(run30) if run30 else None
            d1 = (p1 - rank) if (rank and p1) else None
            d7 = (p7 - rank) if (rank and p7) else None
            d30 = (p30 - rank) if (rank and p30) else None
            isnew = bool(rank) and prev is not None and not p1
            key = brand + "" + kw
            hist_json[key] = [[ca[5:16], r] for ca, r in h]
            rows_json.append({"brand": brand, "kw": kw, "rank": rank, "vol": vol or 0,
                "cpc": round(cpc or 0, 2), "url": url or "", "src": source or "",
                "grank": grank, "impr": impr or 0, "clicks": clicks or 0,
                "d1": d1, "d7": d7, "d30": d30, "best": best, "isnew": isnew, "b": isb or 0, "mr": mrank, "mp": maprank})
        brands_json.append({"brand": brand, "domain": meta["domain"], "geo": geo_label})

    logo = config.logo_html()
    html = (_TEMPLATE
            .replace("__UPDATED__", latest or "no data yet")
            .replace("__LOGO__", logo)
            .replace("__BRAND__", config.brand_name())
            .replace("__DATA__", json.dumps(rows_json))
            .replace("__HIST__", json.dumps(hist_json))
            .replace("__BRANDS__", json.dumps(brands_json)))
    OUT_HTML.write_text(html)
    print(f"Dashboard -> {OUT_HTML} ({len(rows_json)} rows, {len(runs)} update{'s' if len(runs)!=1 else ''} of history)")


_TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__BRAND__ · Rankings</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#000;--bg2:#0b0b0e;--card:#0f0f14;--ink:#fff;--ink2:#b6b6bd;--mut:#76767f;
--line:rgba(255,255,255,.13);--line2:rgba(255,255,255,.22);--gold:#ff7a2e;
--grad:linear-gradient(180deg,#ff9142,#ff6a17);--up:#39d98a;--down:#ff5c5c;--ease:cubic-bezier(.22,1,.36,1)}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font:14.5px/1.5 'Inter',-apple-system,sans-serif}
.app{display:grid;grid-template-columns:236px 1fr;min-height:100vh}
aside{background:var(--bg2);border-right:1px solid var(--line);padding:20px 14px;display:flex;flex-direction:column;gap:4px;position:sticky;top:0;height:100vh;overflow-y:auto}
.logo{padding:2px 8px 18px}.logo svg{height:24px;width:auto}.logo svg path{fill:#fff}
.navlbl{font-size:10px;text-transform:uppercase;letter-spacing:.8px;color:var(--mut);padding:8px 10px 6px}
.nav{display:flex;flex-direction:column;gap:2px}
.navitem{position:relative;display:flex;align-items:center;gap:10px;background:none;border:1px solid transparent;border-left:3px solid transparent;border-radius:12px;padding:9px 12px 9px 11px;cursor:pointer;text-align:left;width:100%;transition:background .15s ease,border-color .15s ease;user-select:none}
.navitem:hover{background:rgba(255,255,255,.04)}
.navitem.on{background:var(--card);border-color:var(--line);border-left:3px solid var(--gold)}
.navitem .bico{flex:0 0 24px;width:24px;height:24px;display:flex;align-items:center;justify-content:center}
.navitem .bico img{width:20px;height:20px;border-radius:5px;background:#1b1b20}
.navitem .bico svg{width:17px;height:17px;color:var(--mut);transition:color .15s ease}
.navitem.on .bico svg,.navitem:hover .bico svg{color:var(--gold)}
.bfall{width:20px;height:20px;border-radius:5px;background:rgba(255,122,46,.16);color:var(--gold);font-family:'Plus Jakarta Sans';font-weight:800;font-size:11px;display:flex;align-items:center;justify-content:center}
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
.kpis{display:grid;grid-template-columns:repeat(7,1fr);gap:10px;margin-bottom:14px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px}
.kpi .n{font-family:'Plus Jakarta Sans';font-size:21px;font-weight:800;font-variant-numeric:tabular-nums}
.kpi .l{color:var(--mut);font-size:10px;text-transform:uppercase;letter-spacing:.5px;margin-top:1px}
.kpi.hl .n{color:var(--gold)}.kpi.g .n{color:var(--up)}.kpi.r .n{color:var(--down)}
.dist{display:flex;align-items:center;gap:14px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 16px;margin-bottom:14px;flex-wrap:wrap}
.dist .dl{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--mut);white-space:nowrap}
.dbar{flex:1;display:flex;gap:2px;height:14px;min-width:220px;border-radius:7px;overflow:hidden}
.dbar div{height:100%}
.dleg{display:flex;gap:14px;flex-wrap:wrap;font-size:11.5px;color:var(--ink2)}
.dleg span i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.controls{display:flex;flex-wrap:wrap;gap:9px;align-items:center;margin-bottom:16px}
.controls input,.controls select{background:var(--card);border:1px solid var(--line);color:var(--ink);border-radius:100px;padding:8px 14px;font-size:13px;font-family:'Inter'}
.controls input:focus,.controls select:focus{outline:none;border-color:var(--gold)}
.controls input[type=search]{min-width:190px;flex:1}
.seg{display:flex;background:var(--card);border:1px solid var(--line);border-radius:100px;overflow:hidden}
.seg button{background:none;border:none;color:var(--mut);padding:8px 13px;font-size:12px;cursor:pointer;font-family:'Inter';font-weight:500}
.seg button.on{background:rgba(255,122,46,.14);color:var(--gold);font-weight:600}
.dd{position:relative}
.ddbtn{display:flex;align-items:center;gap:9px;background:var(--card);border:1px solid rgba(255,122,46,.3);color:var(--ink);border-radius:100px;padding:8px 15px;font-size:12.5px;cursor:pointer;font-family:'Plus Jakarta Sans';font-weight:700;transition:border-color .2s var(--ease),box-shadow .2s var(--ease)}
.ddbtn:hover{border-color:rgba(255,122,46,.55)}
.ddbtn:focus-visible,.dd.open .ddbtn{outline:none;border-color:var(--gold);box-shadow:0 0 0 3px rgba(255,122,46,.18)}
.ddchev{transition:transform .2s var(--ease)}
.dd.open .ddchev{transform:rotate(180deg)}
.ddlist{position:absolute;top:calc(100% + 8px);right:0;min-width:148px;background:rgba(17,17,22,.96);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border:1px solid rgba(255,255,255,.14);border-radius:16px;padding:6px;margin:0;list-style:none;z-index:50;display:none;box-shadow:0 24px 60px rgba(0,0,0,.7),0 0 0 1px rgba(255,122,46,.08)}
.dd.open .ddlist{display:block;animation:ddin .16s var(--ease)}
@keyframes ddin{from{opacity:0;transform:translateY(-5px)}to{opacity:1;transform:none}}
.ddlist li{display:flex;align-items:center;justify-content:space-between;gap:20px;height:38px;padding:0 13px;border-radius:11px;font-size:13px;color:var(--ink2);cursor:pointer;white-space:nowrap;font-family:'Plus Jakarta Sans';font-weight:600;transition:background .12s ease,color .12s ease}
.ddlist li:hover,.ddlist li.focused{background:rgba(255,122,46,.13);color:var(--ink)}
.ddlist li[aria-selected="true"]{color:var(--gold)}
.ddlist li::after{content:"";width:14px;height:14px;flex:0 0 14px}
.ddlist li[aria-selected="true"]::after{content:"";background:url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2.5 7.5L5.5 10.5L11.5 3.5" stroke="%23ff7a2e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>') center/contain no-repeat}
.pill{background:var(--card);border:1px solid var(--line);color:var(--ink2);border-radius:100px;padding:8px 15px;font-size:12px;cursor:pointer;font-family:'Plus Jakarta Sans';font-weight:700}
.pill:hover{border-color:var(--gold);color:var(--gold)}
.pill.on{background:rgba(255,122,46,.14);border-color:rgba(255,122,46,.4);color:var(--gold)}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;margin-bottom:16px;overflow:hidden}
.chead{display:flex;align-items:center;gap:11px;padding:13px 18px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.chead h2{font-family:'Plus Jakarta Sans';font-size:15px;font-weight:700}
.dom{color:var(--mut);font-size:12.5px}.score{margin-left:auto;color:var(--mut);font-size:11.5px}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;min-width:1080px}
th{text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.55px;color:var(--mut);padding:9px 13px;border-bottom:1px solid var(--line);cursor:pointer;white-space:nowrap;background:var(--card);position:sticky;top:0;z-index:1}
th.sorted{color:var(--gold)}
td{padding:8px 13px;border-bottom:1px solid rgba(255,255,255,.06);font-size:13px;color:var(--ink2)}
td.kw{color:var(--ink);max-width:260px;cursor:pointer}
td.kw:hover{color:var(--gold)}
tr:last-child td{border-bottom:none}
.num,.vol,.rank,.geo{text-align:right;font-variant-numeric:tabular-nums}
.vol{font-weight:600;color:var(--ink)}
.rank{font-weight:700}
.rank.p1{color:var(--up)}.rank.p2{color:var(--gold)}
.up{color:var(--up)}.down{color:var(--down)}.flat{color:#3d3d44}
.newb{display:inline-block;font-size:9px;font-weight:700;letter-spacing:.5px;color:var(--up);border:1px solid rgba(57,217,138,.4);border-radius:100px;padding:1px 6px;margin-left:6px;vertical-align:1px}
.badge{display:inline-block;font-size:9px;text-transform:uppercase;letter-spacing:.5px;padding:2px 7px;border-radius:100px;border:1px solid var(--line);color:var(--mut)}
.badge.ranked{border-color:rgba(57,217,138,.35);color:var(--up)}
.badge.research{border-color:rgba(255,122,46,.4);color:var(--gold)}
.badge.gsc{border-color:rgba(106,176,255,.35);color:#6ab0ff}
.badge.brand{border-color:rgba(255,122,46,.45);color:var(--gold);font-weight:700}
.url{color:var(--mut);font-size:11.5px;max-width:190px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.url a{color:var(--mut);text-decoration:none;border-bottom:1px dotted rgba(255,255,255,.25)}
.url a:hover{color:var(--gold);border-bottom-color:var(--gold)}
body.fullurls .url{max-width:none;white-space:normal;word-break:break-all}
.star{cursor:pointer;color:#3d3d44;font-size:15px;text-align:center;width:34px}
.star.on{color:var(--gold)}
.spark{width:92px;height:26px}
.chartrow td{background:#0b0b0e;padding:14px 18px}
.chartrow svg{width:100%;height:170px;display:block}
.morebar{display:flex;align-items:center;gap:12px;padding:11px 18px;border-top:1px solid var(--line);font-size:12.5px;color:var(--mut)}
footer{color:var(--mut);font-size:11.5px;text-align:center;margin-top:22px}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.72);backdrop-filter:blur(4px);z-index:100;display:none;align-items:center;justify-content:center;padding:20px}
.overlay.open{display:flex}
.modal{background:#111116;border:1px solid rgba(255,122,46,.3);border-radius:18px;padding:26px;width:100%;max-width:440px;box-shadow:0 30px 80px rgba(0,0,0,.7)}
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
.kwdel{visibility:hidden;background:none;border:none;color:#5a3d3d;cursor:pointer;font-size:13px;padding:0 4px}
tr:hover .kwdel{visibility:visible}
.kwdel:hover{color:var(--down)}
.bdel{visibility:hidden;flex:0 0 auto;background:none;border:none;color:#6b4a4a;cursor:pointer;font-size:12px;padding:4px 6px;border-radius:8px}
.navitem:hover .bdel{visibility:visible}
.bdel:hover{color:var(--down);background:rgba(255,92,92,.1)}
#toast{position:fixed;bottom:26px;left:50%;transform:translateX(-50%);background:#16161c;border:1px solid rgba(255,122,46,.4);color:var(--ink);border-radius:100px;padding:11px 22px;font-size:13.5px;z-index:200;display:none;box-shadow:0 12px 40px rgba(0,0,0,.6)}
@media(max-width:920px){.app{grid-template-columns:1fr}aside{position:static;height:auto;flex-direction:row;flex-wrap:wrap;align-items:center}.nav{flex-direction:row;flex-wrap:wrap}.nav button{width:auto}.sfoot{display:none}.kpis{grid-template-columns:repeat(2,1fr)}}
</style></head><body>
<div class="app">
<aside>
  <div class="logo">__LOGO__</div>
  <div class="navlbl">Tracked URLs</div>
  <nav class="nav" id="nav"></nav>
  <button id="addurl" style="margin:8px 4px 0;background:none;border:1.5px dashed rgba(255,122,46,.45);color:var(--gold);border-radius:12px;padding:10px;width:calc(100% - 8px);cursor:pointer;font-family:'Plus Jakarta Sans';font-weight:700;font-size:13px">＋ Add URL</button>
  <div class="navlbl" style="margin-top:14px">Reports</div>
  <nav class="nav">
    <div class="navitem on"><span class="bico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg></span><span class="btxt"><span class="bname">Rankings</span><span class="bmeta">keywords &amp; positions</span></span></div>
    <div class="navitem" role="button" tabindex="0" onclick="location.href='/research'"><span class="bico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.35-4.35"/></svg></span><span class="btxt"><span class="bname">Research</span><span class="bmeta">keyword ideas</span></span></div>
    <div class="navitem" role="button" tabindex="0" onclick="location.href='/explorer'"><span class="bico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 3a9 9 0 1 0 9 9"/><path d="M21 3l-9 9"/><path d="M15 3h6v6"/></svg></span><span class="btxt"><span class="bname">Site Explorer</span><span class="bmeta">analyze any domain</span></span></div>
    <div class="navitem" role="button" tabindex="0" onclick="location.href='/competitors'"><span class="bico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/></svg></span><span class="btxt"><span class="bname">Competitors</span><span class="bmeta">keyword gap</span></span></div>
    <div class="navitem" role="button" tabindex="0" onclick="location.href='/ai-visibility'"><span class="bico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM19 15l.9 2.4L22 18.3l-2.1.9L19 21.6l-.9-2.4-2.1-.9 2.1-.9z"/></svg></span><span class="btxt"><span class="bname">AI Visibility</span><span class="bmeta">AI Overview citations</span></span></div>
    <div class="navitem" role="button" tabindex="0" onclick="location.href='/site-health'"><span class="bico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12h4l3-8 4 16 3-8h6"/></svg></span><span class="btxt"><span class="bname">Site Health</span><span class="bmeta">technical audit</span></span></div>
    <div class="navitem" role="button" tabindex="0" onclick="location.href='/link-gap'"><span class="bico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M10 14a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.5 1.5"/><path d="M14 10a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.5-1.5"/></svg></span><span class="btxt"><span class="bname">Link Gap</span><span class="bmeta">links competitors have</span></span></div>
    <div class="navitem" role="button" tabindex="0" onclick="location.href='/map-grid'"><span class="bico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 21s-7-5.5-7-11a7 7 0 0 1 14 0c0 5.5-7 11-7 11z"/><circle cx="12" cy="10" r="2.6"/></svg></span><span class="btxt"><span class="bname">Map Grid</span><span class="bmeta">local map-pack coverage</span></span></div>
  </nav>
  <div class="sfoot">Last update:<br>__UPDATED__<br><br>Google US · top 100<br>Updates daily · geo weekly</div>
</aside>
<main>
  <div class="mhead"><h1>Rank <span>Tracker</span></h1><span class="upd">Last checked: __UPDATED__ · Google US organic · desktop</span></div>
  <div class="kpis" id="kpis"></div>
  <div class="dist" id="dist"></div>
  <div class="controls">
    <input type="search" id="q" placeholder="Filter keywords…">
    <div class="seg" id="src">
      <button data-v="" class="on">All sources</button><button data-v="ranked">Ranked</button>
      <button data-v="research">Research</button><button data-v="gsc">GSC</button>
    </div>
    <div class="seg" id="pos">
      <button data-v="" class="on">Any rank</button><button data-v="top3">Top 3</button>
      <button data-v="p1">Page 1</button><button data-v="strike">Striking 5-20</button>
      <button data-v="opp">Opportunity 20+</button>
    </div>
    <button class="pill" id="starf">★ Starred</button>
    <button class="pill" id="brandf">Brand terms</button>
    <button class="pill" id="localf">Local</button>
    <button class="pill" id="targetf">Targets</button>
    <button class="pill" id="urlsf">Full URLs</button>
    <div class="dd" id="psize">
      <button type="button" class="ddbtn" aria-haspopup="listbox" aria-expanded="false" aria-label="Rows per table">
        <span class="ddlabel">Show 25</span>
        <svg class="ddchev" width="11" height="7" viewBox="0 0 11 7" fill="none"><path d="M1 1l4.5 4.5L10 1" stroke="#ff7a2e" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>
      <ul class="ddlist" role="listbox" aria-label="Rows per table">
        <li role="option" data-v="15" aria-selected="false">Show 15</li>
        <li role="option" data-v="25" aria-selected="true">Show 25</li>
        <li role="option" data-v="50" aria-selected="false">Show 50</li>
        <li role="option" data-v="0" aria-selected="false">Show all</li>
      </ul>
    </div>
    <input type="number" id="minvol" placeholder="Min volume" style="width:112px">
    <button class="pill" id="csv">Export CSV</button>
    <button class="pill" id="refreshbtn">↻ Refresh rankings</button>
    <button class="pill" id="addkw">＋ Keywords</button>
  </div>
  <div id="cards"></div>
  <footer>__BRAND__ · DataForSEO + Google Search Console · <span id="shown"></span> keywords shown</footer>
</main>
<div class="overlay" id="kwModal">
  <div class="modal">
    <h3>Add keywords</h3>
    <div class="mlbl">Brand</div><div class="chips" id="kwBrand"></div>
    <div class="mlbl">Tier</div>
    <div class="chips" id="kwTier">
      <button data-v="target" class="on">Target</button><button data-v="brand">Brand</button>
      <button data-v="local">Local</button><button data-v="seed">Research seed</button>
    </div>
    <div class="mlbl">Keywords — one per line (max 50)</div>
    <textarea id="kwList" rows="6" placeholder="ai receptionist pricing&#10;best ai answering service"></textarea>
    <div class="mrow"><button class="mbtn ghost" data-close>Cancel</button><button class="mbtn go" id="kwGo">Add keywords</button></div>
  </div>
</div>
<div class="overlay" id="urlModal">
  <div class="modal">
    <h3>Add URL</h3>
    <div class="mlbl">Brand name</div><input id="uName" placeholder="My Brand">
    <div class="mlbl">Domain</div><input id="uDomain" placeholder="example.com">
    <div class="mlbl">Seed keywords for research — one per line (optional)</div>
    <textarea id="uSeeds" rows="4" placeholder="best example service"></textarea>
    <div class="mrow"><button class="mbtn ghost" data-close>Cancel</button><button class="mbtn go" id="urlGo">Add URL</button></div>
  </div>
</div>
<div id="toast"></div>
</div>
<script>
const DATA=__DATA__, HIST=__HIST__, BRANDS=__BRANDS__;
const SEP="";
let sortKey="vol", sortDir=-1, tab="", pageSize=25;
const extraShown={};
const state={q:"",src:"",pos:"",minvol:0,star:false,bterm:false,lterm:false,tterm:false};
let stars=new Set(JSON.parse(localStorage.getItem('rt_stars')||'[]'));
let openChart=null;
const el=id=>document.getElementById(id);
const fmt=n=>(n||0).toLocaleString();
try{const h=decodeURIComponent(location.hash.slice(1));if(h&&BRANDS.some(b=>b.brand===h))tab=h}catch(e){}

function move(d){if(d==null)return '<span class="flat">·</span>';if(d>0)return '<span class="up">▲'+d+'</span>';if(d<0)return '<span class="down">▼'+Math.abs(d)+'</span>';return '<span class="flat">=</span>'}
let fullUrls=false;
function urlCell(r){
  if(!r.url)return '—';
  let abs=r.url, disp=r.url;
  const dom=(BRANDS.find(b=>b.brand===r.brand)||{}).domain||'';
  if(/^https?:\/\//.test(r.url)){try{const u=new URL(r.url);disp=u.pathname+u.search;}catch(e){}}
  else{abs='https://'+dom+(r.url.startsWith('/')?'':'/')+r.url;}
  if(disp==='')disp='/';
  return `<a href="${abs}" target="_blank" rel="noopener">${fullUrls?abs:disp}</a>`;
}
function keyOf(r){return r.brand+SEP+r.kw}
function passes(r){
  if(tab&&r.brand!==tab)return false;
  if(state.src&&r.src!==state.src)return false;
  if(state.q&&!r.kw.toLowerCase().includes(state.q))return false;
  if(state.minvol&&(r.vol||0)<state.minvol)return false;
  if(state.star&&!stars.has(keyOf(r)))return false;
  if(state.bterm&&r.b!==1)return false;
  if(state.lterm&&r.b!==2)return false;
  if(state.tterm&&r.b!==3)return false;
  if(state.pos==="top3"&&!(r.rank&&r.rank<=3))return false;
  if(state.pos==="p1"&&!(r.rank&&r.rank<=10))return false;
  if(state.pos==="strike"&&!(r.rank&&r.rank>=5&&r.rank<=20))return false;
  if(state.pos==="opp"&&!(!r.rank||r.rank>20))return false;
  return true;
}
function visWeight(p){if(!p)return 0;if(p<=1)return 1;if(p<=3)return .8;if(p<=10)return .55;if(p<=20)return .25;if(p<=50)return .08;return .02}
function kpis(rows){
  const w=rows.map(r=>Math.max(r.vol,10));
  const vis=rows.length?Math.round(rows.reduce((a,r,i)=>a+visWeight(r.rank)*w[i],0)/w.reduce((a,b)=>a+b,0)*100):0;
  const rk=rows.filter(r=>r.rank);
  const avg=rk.length?(rk.reduce((a,r)=>a+r.rank,0)/rk.length).toFixed(1):'—';
  const top3=rows.filter(r=>r.rank&&r.rank<=3).length;
  const p1=rows.filter(r=>r.rank&&r.rank<=10).length;
  const up=rows.filter(r=>r.d1>0).length, down=rows.filter(r=>r.d1<0).length, nw=rows.filter(r=>r.isnew).length;
  el('kpis').innerHTML=`
   <div class="kpi hl"><div class="n">${vis}%</div><div class="l">Visibility</div></div>
   <div class="kpi"><div class="n">${avg}</div><div class="l">Avg rank</div></div>
   <div class="kpi"><div class="n">${fmt(top3)}</div><div class="l">Top 3</div></div>
   <div class="kpi"><div class="n">${fmt(p1)}</div><div class="l">Page 1</div></div>
   <div class="kpi g"><div class="n">${fmt(up)}</div><div class="l">Improved</div></div>
   <div class="kpi r"><div class="n">${fmt(down)}</div><div class="l">Declined</div></div>
   <div class="kpi"><div class="n">${fmt(nw)}</div><div class="l">New</div></div>`;
}
const RAMP=['#ffd9bf','#ffb98c','#ff9859','#ff7a2e','#c95c1a'];
const BUCKETS=[['Top 3',r=>r.rank&&r.rank<=3],['4-10',r=>r.rank&&r.rank>=4&&r.rank<=10],['11-20',r=>r.rank&&r.rank>=11&&r.rank<=20],['21-50',r=>r.rank&&r.rank>=21&&r.rank<=50],['51-100',r=>r.rank&&r.rank>=51]];
function dist(rows){
  const counts=BUCKETS.map(([l,f])=>rows.filter(f).length);
  const unr=rows.filter(r=>!r.rank).length;
  const total=rows.length||1;
  let bar='',leg='';
  counts.forEach((c,i)=>{if(c)bar+=`<div style="width:${c/total*100}%;background:${RAMP[i]}" title="${BUCKETS[i][0]}: ${c}"></div>`});
  if(unr)bar+=`<div style="width:${unr/total*100}%;background:#26262b" title="Not ranking: ${unr}"></div>`;
  counts.forEach((c,i)=>{leg+=`<span><i style="background:${RAMP[i]}"></i>${BUCKETS[i][0]} · ${c}</span>`});
  leg+=`<span><i style="background:#26262b"></i>Not ranking · ${unr}</span>`;
  el('dist').innerHTML=`<span class="dl">Rank distribution</span><div class="dbar">${bar}</div><div class="dleg">${leg}</div>`;
}
function spark(key){
  const h=(HIST[key]||[]).filter(p=>p[1]);
  if(h.length<2)return '<span class="flat">·</span>';
  const ranks=h.map(p=>p[1]);
  const mn=Math.min(...ranks),mx=Math.max(...ranks);
  const W=92,Hh=26,pad=3;
  const xs=i=>pad+i*(W-2*pad)/(h.length-1);
  const ys=r=>mx===mn?Hh/2:pad+(r-mn)*(Hh-2*pad)/(mx-mn);
  const d=h.map((p,i)=>(i?'L':'M')+xs(i).toFixed(1)+' '+ys(p[1]).toFixed(1)).join(' ');
  return `<svg class="spark" viewBox="0 0 ${W} ${Hh}"><path d="${d}" fill="none" stroke="#ff7a2e" stroke-width="1.6"/><circle cx="${xs(h.length-1)}" cy="${ys(ranks[ranks.length-1])}" r="2.4" fill="#ff7a2e"/></svg>`;
}
function bigChart(key){
  const h=HIST[key]||[];
  const pts=h.map((p,i)=>({i,t:p[0],r:p[1]}));
  const withR=pts.filter(p=>p.r);
  if(!withR.length)return '<div style="color:#76767f;font-size:13px">No ranking history yet for this keyword.</div>';
  const mn=Math.max(1,Math.min(...withR.map(p=>p.r))-2);
  const mx=Math.max(...withR.map(p=>p.r))+3;
  const W=760,Hh=170,L=38,R=12,T=14,B=26;
  const xs=i=>L+(pts.length===1?0:i*(W-L-R)/(pts.length-1));
  const ys=r=>T+(r-mn)*(Hh-T-B)/(mx-mn||1);
  let d='',seg=false;
  pts.forEach(p=>{if(p.r){d+=(seg?' L':' M')+xs(p.i).toFixed(1)+' '+ys(p.r).toFixed(1);seg=true}else seg=false});
  const dots=withR.map(p=>`<circle cx="${xs(p.i)}" cy="${ys(p.r)}" r="3.4" fill="#ff7a2e"><title>${p.t} — rank #${p.r}</title></circle>`).join('');
  const ticks=[mn,Math.round((mn+mx)/2),mx].map(v=>`<text x="${L-7}" y="${ys(v)+4}" text-anchor="end" font-size="10" fill="#76767f">${v}</text><line x1="${L}" y1="${ys(v)}" x2="${W-R}" y2="${ys(v)}" stroke="rgba(255,255,255,.06)"/>`).join('');
  const xl=`<text x="${L}" y="${Hh-8}" font-size="10" fill="#76767f">${pts[0].t}</text><text x="${W-R}" y="${Hh-8}" text-anchor="end" font-size="10" fill="#76767f">${pts[pts.length-1].t}</text>`;
  return `<svg viewBox="0 0 ${W} ${Hh}">${ticks}${xl}<path d="${d}" fill="none" stroke="#ff7a2e" stroke-width="2"/>${dots}</svg>
  <div style="color:#76767f;font-size:11px;margin-top:4px">Rank history (lower is better) · ${withR.length} data point${withR.length!==1?'s':''} · updates daily</div>`;
}
function th(k,label){return `<th data-k="${k}" class="${sortKey===k?'sorted':''}">${label}${sortKey===k?(sortDir<0?' ↓':' ↑'):''}</th>`}
function render(){
  const rows=DATA.filter(passes);
  rows.sort((a,b)=>{let x=a[sortKey],y=b[sortKey];x=(x==null?(sortDir<0?-1:1e9):x);y=(y==null?(sortDir<0?-1:1e9):y);return (x<y?-1:x>y?1:0)*sortDir});
  kpis(rows);dist(rows);
  el('shown').textContent=fmt(rows.length);
  const byBrand={};rows.forEach(r=>{(byBrand[r.brand]=byBrand[r.brand]||[]).push(r)});
  let html="";
  BRANDS.filter(b=>!tab||b.brand===tab).forEach(b=>{
    const rs=byBrand[b.brand];if(!rs||!rs.length)return;
    const geoCol=!!b.geo;
    const limit=pageSize===0?rs.length:Math.min(rs.length,pageSize+(extraShown[b.brand]||0));
    const shown=rs.slice(0,limit);
    html+=`<section class="card"><div class="chead"><h2>${b.brand}</h2><span class="dom">${b.domain}</span>
      <span class="score">${fmt(rs.length)} kw · ${fmt(rs.reduce((a,r)=>a+(r.vol||0),0))} vol/mo${b.geo?' · geo: '+b.geo:''}</span></div>
      <div class="scroll"><table><thead><tr>
      <th class="star">★</th>${th('kw','Keyword')}${th('vol','Volume')}${th('rank','Rank')}${th('d1','1Δ')}${th('d7','7dΔ')}${th('d30','30dΔ')}${th('best','Best')}${th('mr','Mobile')}
      ${geoCol?th('grank','Geo'):''}${th('impr','GSC impr')}${th('cpc','CPC')}${th('src','Source')}<th>URL</th><th>Trend</th>
      </tr></thead><tbody>`;
    shown.forEach(r=>{
      const rcls=r.rank?(r.rank<=10?'p1':(r.rank<=20?'p2':'')):'';
      const k=keyOf(r);
      html+=`<tr data-key="${encodeURIComponent(k)}"><td class="star ${stars.has(k)?'on':''}" data-star="${encodeURIComponent(k)}">★<button class="kwdel" data-del="${encodeURIComponent(k)}" title="Stop tracking">✕</button></td>
        <td class="kw" data-chart="${encodeURIComponent(k)}">${r.kw}${r.b===1?'<span class="newb" style="color:var(--gold);border-color:rgba(255,122,46,.45)">BRAND</span>':''}${r.b===2?'<span class="newb" style="color:#6ab0ff;border-color:rgba(106,176,255,.4)">LOCAL</span>':''}${r.b===3?'<span class="newb" style="color:#c9a2ff;border-color:rgba(201,162,255,.4)">TARGET</span>':''}${r.isnew?'<span class="newb">NEW</span>':''}</td>
        <td class="vol">${fmt(r.vol)}</td>
        <td class="rank ${rcls}">${r.rank?('#'+r.rank):'—'}</td>
        <td class="num">${move(r.d1)}</td><td class="num">${move(r.d7)}</td><td class="num">${move(r.d30)}</td>
        <td class="num">${r.best?('#'+r.best):'—'}</td>
        <td class="num">${r.mr?('#'+r.mr):'—'}</td>
        ${geoCol?`<td class="geo">${r.grank?('#'+r.grank):'—'}</td><td class="geo">${r.mp?('📍#'+r.mp):'—'}</td>`:''}
        <td class="num">${r.impr?fmt(r.impr):'—'}</td>
        <td class="num">${r.cpc?('$'+r.cpc.toFixed(2)):'—'}</td>
        <td><span class="badge ${r.src}">${r.src}</span></td>
        <td class="url" title="${r.url}">${urlCell(r)}</td>
        <td data-chart="${encodeURIComponent(k)}" style="cursor:pointer">${spark(k)}</td></tr>`;
      if(openChart===k){
        html+=`<tr class="chartrow"><td colspan="${geoCol?14:13}">${bigChart(k)}</td></tr>`;
      }
    });
    html+="</tbody></table></div>";
    if(limit<rs.length){
      html+=`<div class="morebar">Showing ${fmt(limit)} of ${fmt(rs.length)}
        <button class="pill" data-more="${b.brand}">Show ${Math.min(25,rs.length-limit)} more</button>
        <button class="pill" data-all="${b.brand}">Show all</button></div>`;
    }
    html+="</section>";
  });
  el('cards').innerHTML=html||'<div class="card"><div class="chead">No keywords match these filters.</div></div>';
}
function buildNav(){
  const rowsAll=DATA;
  let h=navBtn('','All URLs','portfolio · '+fmt(rowsAll.length)+' kw',ICO.globe);
  BRANDS.forEach(b=>{
    const rs=rowsAll.filter(r=>r.brand===b.brand);
    const rk=rs.filter(r=>r.rank);
    const avg=rk.length?(rk.reduce((a,r)=>a+r.rank,0)/rk.length).toFixed(0):'—';
    h+=navBtn(b.brand,b.brand,b.domain+' · '+fmt(rs.length)+' kw · avg #'+avg,favIcon(b.domain,b.brand));
  });
  el('nav').innerHTML=h;
}
const ICO={
 globe:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"/></svg>',
 chart:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>',
 target:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/></svg>',
 spark:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM19 15l.9 2.4L22 18.3l-2.1.9L19 21.6l-.9-2.4-2.1-.9 2.1-.9z"/></svg>',
 pulse:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12h4l3-8 4 16 3-8h6"/></svg>',
 link:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M10 14a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.5 1.5"/><path d="M14 10a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.5-1.5"/></svg>',
 pin:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 21s-7-5.5-7-11a7 7 0 0 1 14 0c0 5.5-7 11-7 11z"/><circle cx="12" cy="10" r="2.6"/></svg>'};
function favIcon(domain,name){
  const fb=`<span class=&quot;bfall&quot;>${(name||'?')[0].toUpperCase()}</span>`;
  return `<img src="https://www.google.com/s2/favicons?domain=${domain}&sz=64" loading="lazy" onerror="this.outerHTML='${fb}'">`;
}
function navBtn(t,name,meta,icon){return `<div class="navitem ${tab===t?'on':''}" data-t="${t}" role="button" tabindex="0"><span class="bico">${icon||ICO.globe}</span><span class="btxt"><span class="bname">${name}</span><span class="bmeta">${meta}</span></span>${t?`<button class="bdel" data-deldom="${encodeURIComponent(t)}" title="Remove URL">✕</button>`:''}</div>`}
document.addEventListener('click',e=>{
  const nb=e.target.closest('#nav .navitem');if(nb&&!e.target.closest('.bdel')){tab=nb.dataset.t;history.replaceState(null,'',tab?('#'+encodeURIComponent(tab)):location.pathname);openChart=null;buildNav();render();return}
  const st=e.target.closest('[data-star]');if(st){const k=decodeURIComponent(st.dataset.star);stars.has(k)?stars.delete(k):stars.add(k);localStorage.setItem('rt_stars',JSON.stringify([...stars]));render();return}
  const ch=e.target.closest('[data-chart]');if(ch){const k=decodeURIComponent(ch.dataset.chart);openChart=(openChart===k?null:k);render();return}
  const mr=e.target.closest('[data-more]');if(mr){extraShown[mr.dataset.more]=(extraShown[mr.dataset.more]||0)+25;render();return}
  const al=e.target.closest('[data-all]');if(al){extraShown[al.dataset.all]=1e9;render();return}
  const t=e.target.closest('th[data-k]');if(t){const k=t.dataset.k;if(sortKey===k)sortDir*=-1;else{sortKey=k;sortDir=-1}render();return}
  const sb=e.target.closest('#src button');if(sb){el('src').querySelectorAll('button').forEach(x=>x.classList.remove('on'));sb.classList.add('on');state.src=sb.dataset.v;render();return}
  const pb=e.target.closest('#pos button');if(pb){el('pos').querySelectorAll('button').forEach(x=>x.classList.remove('on'));pb.classList.add('on');state.pos=pb.dataset.v;render();return}
  if(e.target.closest('#starf')){state.star=!state.star;el('starf').classList.toggle('on',state.star);render();return}
  if(e.target.closest('#brandf')){state.bterm=!state.bterm;el('brandf').classList.toggle('on',state.bterm);render();return}
  if(e.target.closest('#localf')){state.lterm=!state.lterm;el('localf').classList.toggle('on',state.lterm);render();return}
  if(e.target.closest('#targetf')){state.tterm=!state.tterm;el('targetf').classList.toggle('on',state.tterm);render();return}
  if(e.target.closest('#urlsf')){fullUrls=!fullUrls;el('urlsf').classList.toggle('on',fullUrls);document.body.classList.toggle('fullurls',fullUrls);render();return}
  const rb=e.target.closest('#refreshbtn');
  if(rb){rb.textContent='Queuing…';fetch('/refresh?tool=rankings',{method:'POST'}).then(r=>r.json()).then(d=>{if(d.ok){rb.textContent='✓ Queued ('+d.used+'/'+d.limit+' today) — live in ~3 min';rb.classList.add('on')}else{rb.textContent='✗ '+(d.error||'failed')}}).catch(()=>{rb.textContent='✗ Failed — try again'});return}
  if(e.target.closest('.url a'))return;
  if(e.target.closest('#csv')){
    const rows=DATA.filter(passes);
    const head="brand,keyword,is_brand_term,volume,rank,change_1,change_7d,change_30d,best,geo_rank,gsc_impressions,gsc_clicks,cpc,source,url";
    const csv=[head].concat(rows.map(r=>[r.brand,'"'+r.kw.replace(/"/g,'""')+'"',r.b?1:0,r.vol,r.rank??'',r.d1??'',r.d7??'',r.d30??'',r.best??'',r.grank??'',r.impr,r.clicks,r.cpc,r.src,'"'+(r.url||'')+'"'].join(','))).join('\n');
    const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='rank-tracker.csv';a.click();return}
});
el('q').addEventListener('input',e=>{state.q=e.target.value.toLowerCase();render()});
el('minvol').addEventListener('input',e=>{state.minvol=+e.target.value||0;render()});
// custom styled dropdown (native selects can't be themed)
(function(){
  const dd=el('psize'),btn=dd.querySelector('.ddbtn'),list=dd.querySelector('.ddlist'),label=dd.querySelector('.ddlabel');
  const opts=[...list.querySelectorAll('li')];
  let fi=opts.findIndex(o=>o.getAttribute('aria-selected')==='true');
  function open(){dd.classList.add('open');btn.setAttribute('aria-expanded','true');focus(fi)}
  function close(){dd.classList.remove('open');btn.setAttribute('aria-expanded','false');opts.forEach(o=>o.classList.remove('focused'))}
  function focus(i){fi=(i+opts.length)%opts.length;opts.forEach((o,j)=>o.classList.toggle('focused',j===fi))}
  function choose(i){
    opts.forEach((o,j)=>o.setAttribute('aria-selected',j===i?'true':'false'));
    label.textContent=opts[i].textContent;
    pageSize=+opts[i].dataset.v;
    Object.keys(extraShown).forEach(k=>delete extraShown[k]);
    close();btn.focus();render();
  }
  btn.addEventListener('click',e=>{e.stopPropagation();dd.classList.contains('open')?close():open()});
  opts.forEach((o,i)=>o.addEventListener('click',e=>{e.stopPropagation();choose(i)}));
  btn.addEventListener('keydown',e=>{
    if(e.key==='ArrowDown'||e.key==='ArrowUp'||e.key==='Enter'||e.key===' '){e.preventDefault();if(!dd.classList.contains('open'))open()}
  });
  dd.addEventListener('keydown',e=>{
    if(!dd.classList.contains('open'))return;
    if(e.key==='ArrowDown'){e.preventDefault();focus(fi+1)}
    else if(e.key==='ArrowUp'){e.preventDefault();focus(fi-1)}
    else if(e.key==='Enter'){e.preventDefault();choose(fi)}
    else if(e.key==='Escape'){close();btn.focus()}
    else if(e.key==='Tab'){close()}
  });
  document.addEventListener('click',()=>close());
})();
function toast(m){const t=el('toast');t.textContent=m;t.style.display='block';setTimeout(()=>t.style.display='none',5000)}
function mpost(payload,btn,okMsg){
  if(btn){btn.disabled=true;btn.textContent='Queuing…'}
  return fetch('/manage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
    .then(r=>r.json()).then(d=>{
      if(d.ok){toast(okMsg+' — live in ~2-5 min');document.querySelectorAll('.overlay').forEach(o=>o.classList.remove('open'))}
      else toast('✗ '+(d.error||'failed'));
    }).catch(()=>toast('✗ request failed')).finally(()=>{if(btn){btn.disabled=false;btn.textContent=btn.id==='kwGo'?'Add keywords':'Add URL'}});
}
let kwBrandSel=BRANDS[0]?BRANDS[0].brand:'';
el('kwBrand').innerHTML=BRANDS.map((b,i)=>`<button data-v="${b.brand}" class="${i===0?'on':''}">${b.brand}</button>`).join('');
document.addEventListener('click',e=>{
  if(e.target.closest('#addkw')){if(tab)kwBrandSel=tab;[...el('kwBrand').children].forEach(c=>c.classList.toggle('on',c.dataset.v===kwBrandSel));el('kwModal').classList.add('open');return}
  if(e.target.closest('#addurl')){el('urlModal').classList.add('open');return}
  if(e.target.closest('[data-close]')){e.target.closest('.overlay').classList.remove('open');return}
  const ov=e.target.classList&&e.target.classList.contains('overlay');if(ov){e.target.classList.remove('open');return}
  const kb=e.target.closest('#kwBrand button');if(kb){kwBrandSel=kb.dataset.v;[...el('kwBrand').children].forEach(c=>c.classList.toggle('on',c===kb));return}
  const kt=e.target.closest('#kwTier button');if(kt){[...el('kwTier').children].forEach(c=>c.classList.toggle('on',c===kt));return}
  if(e.target.closest('#kwGo')){
    const kws=el('kwList').value.split('\n').map(x=>x.trim()).filter(Boolean).slice(0,50);
    if(!kws.length){toast('Enter at least one keyword');return}
    const tier=el('kwTier').querySelector('.on').dataset.v;
    mpost({action:'add_keywords',brand:kwBrandSel,tier,keywords:kws},el('kwGo'),`✓ ${kws.length} keyword${kws.length>1?'s':''} queued for ${kwBrandSel}`);
    el('kwList').value='';return}
  if(e.target.closest('#urlGo')){
    const name=el('uName').value.trim(),dom=el('uDomain').value.trim();
    if(!name||!dom){toast('Name and domain required');return}
    const seeds=el('uSeeds').value.split('\n').map(x=>x.trim()).filter(Boolean);
    mpost({action:'add_domain',name,domain:dom,seed_keywords:seeds},el('urlGo'),`✓ ${name} queued`);return}
  const del=e.target.closest('.kwdel');
  if(del){e.stopPropagation();const k=decodeURIComponent(del.dataset.del);const i=k.indexOf(SEP)>=0?k.indexOf(SEP):-1;
    let brand='',kw=k;for(const b of BRANDS){if(k.startsWith(b.brand)){brand=b.brand;kw=k.slice(b.brand.length);break}}
    if(confirm(`Stop tracking "${kw}" for ${brand}?`))mpost({action:'remove_keyword',brand,keyword:kw},null,`✓ Removing "${kw}"`);
    return}
  const dd2=e.target.closest('.bdel');
  if(dd2){e.stopPropagation();const b=decodeURIComponent(dd2.dataset.deldom);
    if(confirm(`Remove ${b} and ALL its keywords from tracking? History is kept.`)&&confirm(`Really remove ${b}?`))
      mpost({action:'remove_domain',brand:b},null,`✓ Removing ${b}`);
    return}
});
buildNav();render();
</script>
</body></html>"""


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args and not args[0].startswith("--") else "both"
    BASE.mkdir(parents=True, exist_ok=True)
    if cmd in ("track", "both"):
        track(force_research="--refresh-research" in args, skip_geo="--skip-geo" in args)
    if cmd in ("render", "both"):
        render()
