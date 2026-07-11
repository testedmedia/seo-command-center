#!/usr/bin/env python3
"""Seed the dashboard with realistic sample data — no API key needed.

    python demo.py && python worker.py serve

Lets you explore every page before creating a DataForSEO account.
Wipes nothing you care about: it only writes to data/ when data/ is empty
(pass --force to overwrite).
"""
import datetime
import json
import pathlib
import random
import sqlite3
import sys

REPO = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "tracker"))
import config  # noqa: E402

random.seed(42)

BRANDS = {
    "Acme Coffee": {
        "domain": "acmecoffee.com", "gsc_site": "https://acmecoffee.com/", "geo": None,
        "location_code": 2840, "language_code": "en",
        "seed_keywords": ["specialty coffee beans", "single origin coffee"],
        "brand_keywords": ["acme coffee"],
        "target_keywords": ["best coffee subscription", "fresh roasted coffee beans",
                            "single origin espresso", "light roast coffee online"],
    },
    "BrightSmile Dental": {
        "domain": "brightsmile.dental", "gsc_site": "https://brightsmile.dental/", "geo": None,
        "location_code": 2840, "language_code": "en",
        "seed_keywords": ["dentist near me", "teeth whitening"],
        "brand_keywords": ["brightsmile dental"],
        "local_keywords": ["dentist austin", "emergency dentist austin", "invisalign austin"],
        "geogrid": {"center": [30.2672, -97.7431], "grid": 7, "spacing_miles": 2.5,
                    "zoom": "13z", "keywords": ["dentist", "emergency dentist"]},
    },
}

KWS = {
    "Acme Coffee": [
        ("acme coffee", 1300, 1.1, 1, "ranked", 1), ("best coffee subscription", 9900, 4.2, 12, "ranked", 3),
        ("fresh roasted coffee beans", 4400, 2.8, 7, "ranked", 3), ("single origin espresso", 1900, 3.1, 15, "ranked", 3),
        ("light roast coffee online", 880, 2.4, 22, "ranked", 3), ("specialty coffee beans", 8100, 3.6, 9, "ranked", 0),
        ("coffee bean grinder guide", 2900, 1.9, 31, "research", 0), ("pour over coffee ratio", 6600, 0.9, None, "research", 0),
        ("how to store coffee beans", 3600, 1.2, 18, "gsc", 0), ("ethiopian yirgacheffe", 2400, 2.2, 11, "ranked", 0),
        ("cold brew concentrate", 5400, 3.4, 27, "research", 0), ("coffee subscription gift", 1600, 5.1, 14, "ranked", 0),
    ],
    "BrightSmile Dental": [
        ("brightsmile dental", 720, 2.3, 1, "ranked", 1), ("dentist austin", 12100, 12.5, 8, "ranked", 2),
        ("emergency dentist austin", 2900, 18.2, 5, "ranked", 2), ("invisalign austin", 1900, 15.7, 11, "ranked", 2),
        ("teeth whitening cost", 14800, 6.8, 24, "research", 0), ("dental implants austin", 1600, 22.4, 19, "ranked", 0),
        ("pediatric dentist austin", 2400, 9.3, 16, "ranked", 0), ("root canal cost", 9900, 8.1, None, "research", 0),
        ("veneers before and after", 8100, 4.4, 33, "research", 0), ("dentist open saturday", 4400, 7.7, 13, "gsc", 0),
    ],
}


def seed():
    force = "--force" in sys.argv
    if config.DB.exists() and not force:
        raise SystemExit("data/ already has a database — pass --force to overwrite with demo data.")
    config.DATA.mkdir(exist_ok=True)
    config.KEYWORDS.write_text(json.dumps({"track_cap": 100, "brands": BRANDS}, indent=2))

    if config.DB.exists():
        config.DB.unlink()
    con = sqlite3.connect(config.DB)
    con.execute("""CREATE TABLE kw(checked_at TEXT, brand TEXT, domain TEXT, keyword TEXT,
        rank INTEGER, search_volume INTEGER, cpc REAL, url TEXT, source TEXT, geo TEXT,
        geo_rank INTEGER, gsc_impressions INTEGER, gsc_clicks INTEGER, gsc_position REAL,
        is_brand INTEGER DEFAULT 0, mobile_rank INTEGER, map_rank INTEGER)""")
    con.execute("""CREATE TABLE geogrid(checked_at TEXT, brand TEXT, keyword TEXT,
        lat REAL, lng REAL, rank INTEGER, top3 TEXT)""")

    today = datetime.datetime.now().replace(hour=6, minute=0)
    runs = [(today - datetime.timedelta(days=d)).strftime("%Y-%m-%d %H:%M") for d in (14, 7, 3, 1, 0)]
    for brand, rows in KWS.items():
        dom = BRANDS[brand]["domain"]
        for kw, vol, cpc, rank, src, tier in rows:
            r = rank
            for i, run in enumerate(runs):
                jitter = random.choice([-3, -2, -1, -1, 0, 0, 1, 2]) if r else 0
                cur = max(1, r + jitter * (len(runs) - 1 - i)) if r else None
                url = f"/{kw.replace(' ', '-')}" if cur else ""
                impr = vol // 10 if src == "gsc" or random.random() < .4 else None
                con.execute("INSERT INTO kw VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (run, brand, dom, kw, cur, vol, cpc, url, src, None, None,
                             impr, (impr or 0) // 20 if impr else None,
                             round(cur + random.random() * 3, 1) if cur and impr else None,
                             tier, cur + random.choice([-2, 0, 1]) if cur and tier == 3 else None,
                             random.choice([1, 2, 3]) if tier == 2 and cur and cur <= 10 else None))

    gg = BRANDS["BrightSmile Dental"]["geogrid"]
    lat0, lng0 = gg["center"]
    comps = ["Downtown Dental Studio", "Lakeside Family Dentistry", "Capitol Smiles"]
    import math
    for run in runs[-2:]:
        for kw in gg["keywords"]:
            for r_i in range(gg["grid"]):
                for c_i in range(gg["grid"]):
                    half = (gg["grid"] - 1) / 2
                    lat = lat0 + (half - r_i) * gg["spacing_miles"] / 69.0
                    lng = lng0 + (c_i - half) * gg["spacing_miles"] / (69.0 * math.cos(math.radians(lat0)))
                    dist = math.hypot(r_i - half, c_i - half)
                    rank = None if dist > 2.8 and random.random() < .7 else max(1, int(dist * 1.6 + random.random() * 3))
                    top3 = [{"t": t, "r": i + 1} for i, t in enumerate(random.sample(comps, 2))]
                    if rank and rank <= 3:
                        top3.insert(rank - 1, {"t": "BrightSmile Dental", "r": rank})
                    con.execute("INSERT INTO geogrid VALUES (?,?,?,?,?,?,?)",
                                (run, "BrightSmile Dental", kw, round(lat, 6), round(lng, 6), rank,
                                 json.dumps([{"t": x["t"], "r": i + 1} for i, x in enumerate(top3[:3])])))
    con.commit()

    now = runs[-1]
    (config.DATA / "competitors.json").write_text(json.dumps({"generated": now, "brands": {
        "Acme Coffee": {"domain": "acmecoffee.com",
            "competitors": [{"domain": "beanboxco.com", "common": 42, "their_kw": 8100, "etv": 12400},
                            {"domain": "roastcollective.com", "common": 31, "their_kw": 5600, "etv": 8900},
                            {"domain": "javapress.com", "common": 18, "their_kw": 2300, "etv": 3100}],
            "picked": ["beanboxco.com", "roastcollective.com"],
            "gaps": [{"keyword": "coffee of the month club", "vol": 8100, "cpc": 5.2,
                      "competitors": [{"domain": "beanboxco.com", "rank": 4, "url": "/club"},
                                      {"domain": "roastcollective.com", "rank": 9, "url": "/monthly"}]},
                     {"keyword": "whole bean vs ground", "vol": 4400, "cpc": 1.1,
                      "competitors": [{"domain": "beanboxco.com", "rank": 6, "url": "/blog/whole-vs-ground"}]},
                     {"keyword": "arabica vs robusta", "vol": 12100, "cpc": 0.8,
                      "competitors": [{"domain": "roastcollective.com", "rank": 3, "url": "/learn"}]}]},
        "BrightSmile Dental": {"domain": "brightsmile.dental",
            "competitors": [{"domain": "austindentalco.com", "common": 27, "their_kw": 1900, "etv": 5200}],
            "picked": ["austindentalco.com"],
            "gaps": [{"keyword": "same day crowns austin", "vol": 590, "cpc": 14.2,
                      "competitors": [{"domain": "austindentalco.com", "rank": 5, "url": "/crowns"}]}]},
    }}, indent=1))

    (config.DATA / "ai-visibility.json").write_text(json.dumps({"generated": now, "brands": {
        "Acme Coffee": {"domain": "acmecoffee.com", "n_ai": 4, "n_cited": 1,
            "top_cited": [["wikipedia.org", 3], ["seriouseats.com", 2], ["beanboxco.com", 2]],
            "rows": [{"keyword": "specialty coffee beans", "has_ai": True, "cited": True,
                      "refs": ["acmecoffee.com", "wikipedia.org", "seriouseats.com"]},
                     {"keyword": "single origin coffee", "has_ai": True, "cited": False,
                      "refs": ["wikipedia.org", "beanboxco.com"]},
                     {"keyword": "best coffee subscription", "has_ai": True, "cited": False,
                      "refs": ["seriouseats.com", "beanboxco.com"]},
                     {"keyword": "pour over coffee ratio", "has_ai": True, "cited": False,
                      "refs": ["wikipedia.org"]},
                     {"keyword": "cold brew concentrate", "has_ai": False, "cited": False, "refs": []}]},
        "BrightSmile Dental": {"domain": "brightsmile.dental", "n_ai": 2, "n_cited": 0,
            "top_cited": [["healthline.com", 2], ["webmd.com", 1]],
            "rows": [{"keyword": "teeth whitening", "has_ai": True, "cited": False,
                      "refs": ["healthline.com", "webmd.com"]},
                     {"keyword": "dentist near me", "has_ai": False, "cited": False, "refs": []},
                     {"keyword": "invisalign austin", "has_ai": True, "cited": False,
                      "refs": ["healthline.com"]}]},
    }}, indent=1))

    (config.DATA / "site-health.json").write_text(json.dumps({"generated": now, "brands": {
        "Acme Coffee": {"domain": "acmecoffee.com", "source": "sitemap", "pages_crawled": 84,
            "score": 91, "noalt_total": 6,
            "issue_counts": {"title_long": 12, "desc_missing": 3, "thin": 2},
            "issues": {"title_long": [{"url": "https://acmecoffee.com/blog/roast-guide", "title": ""}],
                       "desc_missing": [{"url": "https://acmecoffee.com/pages/wholesale", "title": ""}],
                       "thin": [{"url": "https://acmecoffee.com/tags/decaf", "title": ""}]},
            "broken_links": [{"url": "https://acmecoffee.com/old-menu", "status": 404}]},
        "BrightSmile Dental": {"domain": "brightsmile.dental", "source": "crawl", "pages_crawled": 31,
            "score": 78, "noalt_total": 14,
            "issue_counts": {"h1_bad": 9, "canonical_missing": 5, "title_dup": 4},
            "issues": {"h1_bad": [{"url": "https://brightsmile.dental/services", "title": ""}],
                       "canonical_missing": [{"url": "https://brightsmile.dental/team", "title": ""}],
                       "title_dup": [{"url": "https://brightsmile.dental/blog/page/2", "title": ""}]},
            "broken_links": []},
    }}, indent=1))

    (config.DATA / "link-gap.json").write_text(json.dumps({"generated": now, "brands": {
        "Acme Coffee": {"domain": "acmecoffee.com", "keyword": "specialty coffee beans", "local": False,
            "competitors": [{"domain": "beanboxco.com", "serp_rank": 3}, {"domain": "roastcollective.com", "serp_rank": 5}],
            "gaps": [{"ref": "coffeereview.com", "rank": 2400, "spam": 4, "links_to": ["beanboxco.com", "roastcollective.com"],
                      "title": "Coffee Review — the world's leading coffee guide",
                      "category": "Roundup / resource", "angle": "Submit your beans for review — lead with a unique origin story.", "difficulty": "Medium"},
                     {"ref": "sprudge.com", "rank": 5100, "spam": 6, "links_to": ["beanboxco.com"],
                      "title": "Sprudge — coffee news and culture",
                      "category": "News / media", "angle": "Digital-PR pitch with a data hook or expert quote.", "difficulty": "Hard"},
                     {"ref": "bestcoffeesubscriptions.net", "rank": 890, "spam": 11, "links_to": ["beanboxco.com", "roastcollective.com"],
                      "title": "Best Coffee Subscriptions — 2026 rankings",
                      "category": "Directory / listing", "angle": "Submit your listing (many free). Highest-certainty link.", "difficulty": "Easy"}]},
    }}, indent=1))
    con.close()
    print("✓ demo data seeded — now run:  python worker.py serve")


if __name__ == "__main__":
    seed()
