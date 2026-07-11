#!/usr/bin/env python3
"""Applies queued keyword/URL management ops from the dashboard (KV mgmt:* keys)
to data/keywords.json. Exit code 10 = ops applied (poller should
re-track + redeploy); 0 = nothing to do.

Ops: add_keywords {brand, tier, keywords[]} · remove_keyword {brand, keyword}
     add_domain {name, domain, gsc_site?, location_code?, language_code?, seed_keywords[]?}
     remove_domain {brand}
     set_geogrid {brand, center:[lat,lng], grid, spacing_miles, zoom?, keywords[]}
     add_geogrid_keywords {brand, keywords[]} · remove_geogrid_keyword {brand, keyword}
     remove_geogrid {brand}
Removals go to blocked_keywords so auto-discovery can't resurrect them.
Geogrid ops queue a map-grid re-run themselves (req:map-grid) instead of a full re-track.
"""
import config
import json, pathlib, sys, urllib.request, urllib.parse

KEYWORDS = config.KEYWORDS
CF = config.cloudflare()
API = (f"https://api.cloudflare.com/client/v4/accounts/{CF['account_id']}"
       f"/storage/kv/namespaces/{CF['kv_namespace']}") if CF and CF.get("kv_namespace") else None
HDRS = {"Authorization": f"Bearer {CF['api_token']}"} if CF else {}
TIER_FIELD = {"target": "target_keywords", "brand": "brand_keywords",
              "local": "local_keywords", "seed": "seed_keywords"}


def kv(path, method="GET", data=None):
    req = urllib.request.Request(API + path, method=method, data=data, headers=HDRS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    if not API:
        return 0  # hosted mode not configured — nothing to poll
    keys = [k["name"] for k in (kv("/keys?prefix=mgmt:").get("result") or [])]
    if not keys:
        return 0
    cfg = json.loads(KEYWORDS.read_text())
    applied = []
    geogrid_changed = False
    for key in sorted(keys):
        try:
            req = urllib.request.Request(f"{API}/values/{urllib.parse.quote(key)}", headers=HDRS)
            with urllib.request.urlopen(req, timeout=30) as r:
                op = json.load(r)
        except Exception as e:
            print(f"  skip {key}: {e}")
            continue
        a = op.get("action")
        try:
            if a == "add_keywords":
                b = cfg["brands"].get(op["brand"])
                if b is not None:
                    field = TIER_FIELD.get(op.get("tier", "target"), "target_keywords")
                    cur = b.setdefault(field, [])
                    blocked = set(x.lower() for x in b.get("blocked_keywords", []))
                    added = 0
                    for kw in op["keywords"]:
                        kw = " ".join(str(kw).split())[:80]
                        if kw and kw.lower() not in {c.lower() for c in cur}:
                            cur.append(kw)
                            added += 1
                        if kw.lower() in blocked:
                            b["blocked_keywords"] = [x for x in b["blocked_keywords"] if x.lower() != kw.lower()]
                    applied.append(f"add_keywords {op['brand']}/{field}: +{added}")
            elif a == "remove_keyword":
                b = cfg["brands"].get(op["brand"])
                if b is not None:
                    kwl = op["keyword"].lower()
                    for field in TIER_FIELD.values():
                        if field in b:
                            b[field] = [x for x in b[field] if x.lower() != kwl]
                    bl = b.setdefault("blocked_keywords", [])
                    if kwl not in {x.lower() for x in bl}:
                        bl.append(op["keyword"])
                    applied.append(f"remove_keyword {op['brand']}: {op['keyword']}")
            elif a == "add_domain":
                name = op["name"].strip()[:40]
                if name not in cfg["brands"]:
                    cfg["brands"][name] = {
                        "domain": op["domain"],
                        "gsc_site": op.get("gsc_site") or f"https://{op['domain']}/",
                        "geo": None,
                        "seed_keywords": op.get("seed_keywords") or [],
                        "brand_keywords": [name.lower()],
                    }
                    if op.get("location_code"):
                        cfg["brands"][name]["location_code"] = int(op["location_code"])
                    if op.get("language_code"):
                        cfg["brands"][name]["language_code"] = op["language_code"]
                    applied.append(f"add_domain {name} ({op['domain']})")
            elif a == "remove_domain":
                if op["brand"] in cfg["brands"]:
                    del cfg["brands"][op["brand"]]
                    applied.append(f"remove_domain {op['brand']}")
            elif a == "set_geogrid":
                b = cfg["brands"].get(op["brand"])
                if b is not None:
                    kws = [" ".join(str(k).split())[:80] for k in op["keywords"] if str(k).strip()][:5]
                    b["geogrid"] = {"center": [round(float(op["center"][0]), 6), round(float(op["center"][1]), 6)],
                                    "grid": int(op.get("grid", 7)),
                                    "spacing_miles": float(op.get("spacing_miles", 3.5)),
                                    "zoom": op.get("zoom") or "13z",
                                    "keywords": kws}
                    geogrid_changed = True
                    applied.append(f"set_geogrid {op['brand']}: {len(kws)} kw")
            elif a == "add_geogrid_keywords":
                gg = (cfg["brands"].get(op["brand"]) or {}).get("geogrid")
                if gg:
                    cur = gg.setdefault("keywords", [])
                    for kw in op["keywords"]:
                        kw = " ".join(str(kw).split())[:80]
                        if kw and kw.lower() not in {c.lower() for c in cur} and len(cur) < 5:
                            cur.append(kw)
                    geogrid_changed = True
                    applied.append(f"add_geogrid_keywords {op['brand']}: now {len(cur)}")
            elif a == "remove_geogrid_keyword":
                gg = (cfg["brands"].get(op["brand"]) or {}).get("geogrid")
                if gg:
                    kwl = op["keyword"].lower()
                    gg["keywords"] = [x for x in gg.get("keywords", []) if x.lower() != kwl]
                    geogrid_changed = True
                    applied.append(f"remove_geogrid_keyword {op['brand']}: {op['keyword']}")
            elif a == "remove_geogrid":
                b = cfg["brands"].get(op["brand"])
                if b is not None and b.get("geogrid"):
                    del b["geogrid"]
                    geogrid_changed = True
                    applied.append(f"remove_geogrid {op['brand']}")
        except Exception as e:
            print(f"  op {key} failed: {e}")
        kv(f"/values/{urllib.parse.quote(key)}", method="DELETE")
    if applied:
        KEYWORDS.write_text(json.dumps(cfg, indent=2))
        for a in applied:
            print(f"  applied: {a}")
        if geogrid_changed:
            # queue a map-grid re-run so the poller re-scans + redeploys the grid page
            kv("/values/req:map-grid", method="PUT", data=b"queued-by-manage-apply")
        if any(not x.startswith(("set_geogrid", "add_geogrid", "remove_geogrid")) for x in applied):
            return 10
    return 0


if __name__ == "__main__":
    sys.exit(main())
