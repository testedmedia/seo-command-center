#!/usr/bin/env python3
"""Technical SEO site auditor (ported from OpenSEO's SiteAuditWorkflow, zero API cost).

Per brand domain: reads sitemap.xml (falls back to homepage crawl), fetches up to
PAGE_CAP pages, and checks each page for:
  - HTTP status / redirect chain
  - title: missing, too long (>60), duplicate across site
  - meta description: missing, too long (>160), duplicate
  - H1: missing or multiple
  - canonical: missing or pointing elsewhere
  - noindex flag
  - thin content (<200 words)
  - images missing alt text
  - broken internal links (sampled across pages)
Renders site-health.html for the rank-tracker site. Free — runs on the Mini.

  python3 scripts/seo-site-audit.py
"""
import gzip, io, json, pathlib, re, sys, urllib.request, urllib.parse, datetime
import config
import shell as seo_shell
from collections import Counter, defaultdict
from html.parser import HTMLParser

BASE = config.DATA
KEYWORDS = config.KEYWORDS
OUT_JSON = config.DATA / "site-health.json"
OUT_HTML = config.DATA / "site-health.html"
PAGE_CAP = 150
LINK_SAMPLE_CAP = 250
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36 SEOCommandCenter/1.0"


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        return r.status, r.geturl(), raw.decode("utf-8", "replace")


def head_status(url, timeout=12):
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.metas = {}
        self.h1 = []
        self.canonical = None
        self.links = []
        self.imgs_total = 0
        self.imgs_noalt = 0
        self.text_len = 0
        self._in = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "h1":
            self.h1_tags = getattr(self, "h1_tags", 0) + 1
        if tag in ("title", "h1", "script", "style"):
            self._in = tag
        if tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name:
                self.metas[name] = a.get("content") or ""
        if tag == "link" and (a.get("rel") or "").lower() == "canonical":
            self.canonical = a.get("href")
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag == "img":
            self.imgs_total += 1
            if not (a.get("alt") or "").strip():
                self.imgs_noalt += 1

    def handle_endtag(self, tag):
        if self._in == tag:
            self._in = None

    def handle_data(self, data):
        if self._in == "title":
            self.title += data
        elif self._in == "h1":
            self.h1.append(data.strip())
        elif self._in in ("script", "style"):
            return
        self.text_len += len(data.split())


def sitemap_urls(domain):
    urls, seen_maps = [], set()

    def walk(sm_url):
        if sm_url in seen_maps or len(urls) >= PAGE_CAP * 3:
            return
        seen_maps.add(sm_url)
        try:
            _, _, xml = fetch(sm_url)
        except Exception:
            return
        locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", xml)
        if "<sitemapindex" in xml:
            for l in locs[:10]:
                walk(l.strip())
        else:
            urls.extend(l.strip() for l in locs)

    walk(f"https://{domain}/sitemap.xml")
    return list(dict.fromkeys(urls))


def audit_site(domain):
    urls = sitemap_urls(domain)
    crawl_source = "sitemap"
    if not urls:
        crawl_source = "homepage crawl"
        urls = [f"https://{domain}/"]
    urls = urls[:PAGE_CAP]
    pages, internal_links = [], set()
    for u in urls:
        rec = {"url": u}
        try:
            status, final, html = fetch(u)
            p = PageParser()
            try:
                p.feed(html)
            except Exception:
                pass
            title = " ".join(p.title.split())
            desc = " ".join((p.metas.get("description") or "").split())
            robots = (p.metas.get("robots") or "").lower()
            canon = p.canonical
            canon_abs = urllib.parse.urljoin(final, canon) if canon else None
            norm = lambda x: (x or "").rstrip("/").replace("https://www.", "https://")
            rec.update({
                "status": status,
                "redirected": norm(final) != norm(u),
                "title": title, "title_missing": not title, "title_long": len(title) > 60,
                "desc": desc, "desc_missing": not desc, "desc_long": len(desc) > 160,
                "h1_count": getattr(p, "h1_tags", 0),
                "canonical_missing": canon is None,
                "canonical_mismatch": bool(canon_abs) and norm(canon_abs) != norm(final),
                "noindex": "noindex" in robots,
                "words": p.text_len, "thin": p.text_len < 200,
                "imgs": p.imgs_total, "imgs_noalt": p.imgs_noalt,
            })
            for href in p.links:
                absu = urllib.parse.urljoin(final, href.split("#")[0])
                pr = urllib.parse.urlparse(absu)
                if pr.scheme in ("http", "https") and pr.netloc.replace("www.", "") == domain.replace("www.", ""):
                    internal_links.add(absu)
        except urllib.error.HTTPError as e:
            rec.update({"status": e.code, "error": True})
        except Exception as e:
            rec.update({"status": 0, "error": True, "err": str(e)[:80]})
        pages.append(rec)
        print(f"    {rec.get('status','?'):>3} {u[:90]}", flush=True)

    # redirected sitemap URLs (funnels, locale redirects) serve ANOTHER page's meta —
    # count them only under the "redirected" notice, never for meta/dup issues
    ok_pages = [p for p in pages if p.get("status") == 200 and not p.get("error")
                and not p.get("redirected")]
    dup_titles = {t: c for t, c in Counter(p["title"] for p in ok_pages if p.get("title")).items() if c > 1}
    dup_descs = {t: c for t, c in Counter(p["desc"] for p in ok_pages if p.get("desc")).items() if c > 1}
    for p in ok_pages:
        p["title_dup"] = p.get("title") in dup_titles
        p["desc_dup"] = p.get("desc") in dup_descs

    # broken internal link sample
    known = {p["url"].rstrip("/") for p in pages}
    to_check = [l for l in internal_links if l.rstrip("/") not in known][:LINK_SAMPLE_CAP]
    broken = []
    for l in to_check:
        s = head_status(l)
        if s in (404, 410, 0):
            broken.append({"url": l, "status": s})
    issues = {
        "errors_4xx_5xx": [p for p in pages if (p.get("status") or 0) >= 400 or p.get("status") == 0],
        "title_missing": [p for p in ok_pages if p.get("title_missing")],
        "title_dup": [p for p in ok_pages if p.get("title_dup")],
        "title_long": [p for p in ok_pages if p.get("title_long")],
        "desc_missing": [p for p in ok_pages if p.get("desc_missing")],
        "desc_dup": [p for p in ok_pages if p.get("desc_dup")],
        "h1_bad": [p for p in ok_pages if p.get("h1_count", 1) != 1],
        "canonical_missing": [p for p in ok_pages if p.get("canonical_missing")],
        "canonical_mismatch": [p for p in ok_pages if p.get("canonical_mismatch")],
        "noindex": [p for p in ok_pages if p.get("noindex")],
        "thin": [p for p in ok_pages if p.get("thin")],
        "redirected": [p for p in pages if p.get("status") == 200 and p.get("redirected")],
    }
    score = 100
    weights = {"errors_4xx_5xx": 4, "title_missing": 2, "title_dup": 1, "desc_missing": 1,
               "desc_dup": 0.5, "h1_bad": 1, "canonical_missing": 0.5, "canonical_mismatch": 2,
               "noindex": 3, "thin": 0.5, "title_long": 0.2, "redirected": 0.3}
    npages = max(len(pages), 1)
    for k, w in weights.items():
        score -= min(25, w * len(issues[k]) * 20 / npages)
    score -= min(15, len(broken) * 1.5)
    return {"domain": domain, "source": crawl_source, "pages_crawled": len(pages),
            "score": max(0, round(score)),
            "issues": {k: [{"url": p["url"], "title": p.get("title", ""), "status": p.get("status"),
                            "h1": p.get("h1_count"), "words": p.get("words")} for p in v[:25]] for k, v in issues.items()},
            "issue_counts": {k: len(v) for k, v in issues.items()},
            "broken_links": broken[:40], "noalt_total": sum(p.get("imgs_noalt", 0) for p in ok_pages)}


ISSUE_LABELS = [
    ("errors_4xx_5xx", "Pages erroring (4xx/5xx/dead)", "crit"),
    ("noindex", "Pages with noindex", "crit"),
    ("canonical_mismatch", "Canonical points elsewhere", "crit"),
    ("title_missing", "Missing title", "warn"),
    ("title_dup", "Duplicate titles", "warn"),
    ("desc_missing", "Missing meta description", "warn"),
    ("desc_dup", "Duplicate meta descriptions", "warn"),
    ("h1_bad", "H1 missing or multiple", "warn"),
    ("thin", "Thin content (<200 words)", "warn"),
    ("canonical_missing", "Missing canonical", "info"),
    ("title_long", "Title too long (>60)", "info"),
    ("redirected", "Sitemap URL redirects", "info"),
]


EXTRA_CSS = """
table{min-width:760px}
td.kw{white-space:nowrap}
.num{font-weight:600;color:var(--ink)}
.hscore{font-family:'Plus Jakarta Sans';font-weight:800;font-size:19px;border-radius:100px;padding:3px 15px;border:1px solid var(--line)}
.hscore.ok{color:var(--up);border-color:rgba(57,217,138,.4)}
.hscore.mid{color:var(--gold);border-color:rgba(255,122,46,.4)}
.hscore.bad{color:var(--down);border-color:rgba(255,92,92,.4)}
"""


def render(result):
    blocks = []
    for brand, b in result["brands"].items():
        rows = ""
        for key, label, sev in ISSUE_LABELS:
            n = b["issue_counts"].get(key, 0)
            if n == 0:
                continue
            examples = b["issues"].get(key, [])[:6]
            ex_html = "<br>".join(f'<span class="who">{e["url"].replace("https://","")}</span>' for e in examples)
            rows += (f'<tr><td><span class="pillb {sev}">{ {"crit":"CRITICAL","warn":"WARNING","info":"NOTICE"}[sev] }</span></td>'
                     f'<td class="kw">{label}</td><td class="num">{n}</td><td>{ex_html}</td></tr>')
        if b["broken_links"]:
            ex = "<br>".join(f'<span class="who">{l["url"].replace("https://","")} → {l["status"] or "dead"}</span>' for l in b["broken_links"][:6])
            rows += (f'<tr><td><span class="pillb crit">CRITICAL</span></td><td class="kw">Broken internal links</td>'
                     f'<td class="num">{len(b["broken_links"])}</td><td>{ex}</td></tr>')
        if not rows:
            rows = '<tr><td colspan=4 class="kw">No issues found — clean crawl.</td></tr>'
        scls = "ok" if b["score"] >= 85 else ("mid" if b["score"] >= 65 else "bad")
        blocks.append(f"""
  <section class="card"><div class="chead"><h2>{brand}</h2><span class="dom">{b["domain"]}</span>
    <span class="hscore {scls}">{b["score"]}</span>
    <span class="score">{b["pages_crawled"]} pages via {b["source"]} · {b["noalt_total"]} images missing alt</span></div>
    <div class="scroll"><table><thead><tr><th>Severity</th><th>Issue</th><th>Pages</th><th>Examples</th></tr></thead>
    <tbody>{rows}</tbody></table></div>
  </section>""")
    html = seo_shell.page(
        active="site-health",
        title_html="Site <span>Health</span>",
        content="".join(blocks),
        updated=result["generated"],
        right_meta=f'Generated: {result["generated"]} · crawled from the Mini, zero API cost',
        refresh_tool="site-health",
        extra_css=EXTRA_CSS)
    OUT_HTML.write_text(html)
    print(f"Report -> {OUT_HTML}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "render":
        render(json.loads(OUT_JSON.read_text()))
        raise SystemExit(0)
    cfg = json.loads(KEYWORDS.read_text())
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    result = {"generated": now, "brands": {}}
    for brand, meta in cfg["brands"].items():
        print(f"  auditing {brand} ({meta['domain']})...", flush=True)
        result["brands"][brand] = audit_site(meta["domain"])
        b = result["brands"][brand]
        print(f"  {brand:22} score={b['score']} pages={b['pages_crawled']} broken={len(b['broken_links'])}", flush=True)
    OUT_JSON.write_text(json.dumps(result, indent=1))
    render(result)
