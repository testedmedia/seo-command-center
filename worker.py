#!/usr/bin/env python3
"""SEO Command Center worker — runs trackers, polls the dashboard queue, deploys.

Commands:
  python worker.py run <tool>        run one tool now (rankings | research-page |
                                     competitors | ai-visibility | site-health |
                                     link-gap | map-grid | all)
  python worker.py render            re-render every page from stored data (free)
  python worker.py serve [port]      local mode — serve the dashboard at localhost:8000
  python worker.py deploy            deploy the site to Cloudflare Pages (hosted mode)
  python worker.py deploy-config     push ACCESS_KEY + DataForSEO secrets + KV binding
                                     to the Pages project (one-time, after setup.py)
  python worker.py loop              hosted mode — poll the refresh/manage queue every
                                     2 min and auto-run the daily refresh (put this in
                                     cron / launchd / a systemd timer, or just leave a
                                     terminal running)

Local mode needs nothing but DataForSEO credentials. Hosted mode (self-serve
refresh buttons, keyword management and live research from the browser) needs a
free Cloudflare account — see README.
"""
import datetime
import http.server
import json
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "tracker"))
import config  # noqa: E402

TOOLS = {
    "rankings": [("rank_tracker.py", ["both", "--skip-geo"]), ("alerts.py", [])],
    "rankings-full": [("rank_tracker.py", ["both"]), ("alerts.py", [])],
    "research-page": [("research_page.py", [])],
    "explorer-page": [("explorer_page.py", [])],
    "competitors": [("competitor_gap.py", [])],
    "ai-visibility": [("ai_visibility.py", [])],
    "site-health": [("site_audit.py", [])],
    "link-gap": [("link_gap.py", [])],
    "map-grid": [("geogrid.py", ["both"])],
}
PAGES = {  # rendered file -> site path
    "dashboard.html": "index.html",
    "research.html": "research.html",
    "explorer.html": "explorer.html",
    "competitors.html": "competitors.html",
    "ai-visibility.html": "ai-visibility.html",
    "site-health.html": "site-health.html",
    "link-gap.html": "link-gap.html",
    "map-grid.html": "map-grid.html",
}


def run_tool(name):
    steps = TOOLS.get(name)
    if not steps:
        raise SystemExit(f"unknown tool '{name}' — one of: {', '.join(TOOLS)}, all")
    for script, args in steps:
        print(f"→ {script} {' '.join(args)}", flush=True)
        r = subprocess.run([sys.executable, str(REPO / "tracker" / script), *args])
        if r.returncode != 0:
            raise SystemExit(r.returncode)  # the tool already printed why


def render_all():
    for script, args in [("rank_tracker.py", ["render"]), ("research_page.py", []),
                         ("explorer_page.py", []),
                         ("competitor_gap.py", ["render"]), ("ai_visibility.py", ["render"]),
                         ("site_audit.py", ["render"]), ("link_gap.py", ["render"]),
                         ("geogrid.py", ["render"])]:
        try:
            subprocess.run([sys.executable, str(REPO / "tracker" / script), *args], check=True)
        except subprocess.CalledProcessError:
            print(f"  ({script} skipped — no data yet)", flush=True)
    copy_pages()


def copy_pages():
    for src, dst in PAGES.items():
        f = config.DATA / src
        if f.exists():
            shutil.copy(f, config.SITE / dst)


def serve(port=8000):
    render_all()
    import functools
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(config.SITE))
    print(f"Dashboard → http://localhost:{port}  (Ctrl-C to stop)")
    print("Note: refresh/manage/research buttons need hosted mode (Cloudflare Pages Functions).")
    http.server.HTTPServer(("127.0.0.1", port), handler).serve_forever()


def _cf():
    cf = config.cloudflare()
    if not cf:
        raise SystemExit("Hosted mode not configured — set CF_ACCOUNT_ID and CF_API_TOKEN in .env "
                         "(or use `python worker.py serve` for local mode).")
    return cf


def deploy():
    cf = _cf()
    copy_pages()
    env = dict(**__import__("os").environ,
               CLOUDFLARE_ACCOUNT_ID=cf["account_id"], CLOUDFLARE_API_TOKEN=cf["api_token"])
    subprocess.run(["npx", "wrangler", "pages", "deploy", str(config.SITE),
                    f"--project-name={cf['project']}", "--branch=main", "--commit-dirty=true"],
                   check=True, env=env)


def _cf_api(cf, path, method="GET", body=None):
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4{path}",
        data=json.dumps(body).encode() if body is not None else None, method=method,
        headers={"Authorization": f"Bearer {cf['api_token']}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def deploy_config():
    """One-time: create the Pages project + KV namespace if needed, push secrets."""
    cf = _cf()
    acct = cf["account_id"]
    # ensure project exists
    try:
        _cf_api(cf, f"/accounts/{acct}/pages/projects/{cf['project']}")
    except urllib.error.HTTPError:
        print(f"Creating Pages project '{cf['project']}'…")
        _cf_api(cf, f"/accounts/{acct}/pages/projects", "POST",
                {"name": cf["project"], "production_branch": "main"})
    # ensure KV namespace
    ns = cf.get("kv_namespace")
    if not ns:
        r = _cf_api(cf, f"/accounts/{acct}/storage/kv/namespaces", "POST",
                    {"title": f"{cf['project']}-queue"})
        ns = r["result"]["id"]
        with open(REPO / ".env", "a") as f:
            f.write(f"\nCF_KV_NAMESPACE={ns}\n")
        print(f"Created KV namespace {ns} (saved to .env)")
    # push env vars + KV binding
    payload = {"deployment_configs": {"production": {
        "env_vars": {
            "ACCESS_KEY": {"type": "secret_text", "value": config.require("ACCESS_KEY")},
            "AUTH_SALT": {"type": "secret_text", "value": config.env("AUTH_SALT", "seo-command-center")},
            "BRAND_NAME": {"type": "plain_text", "value": config.brand_name()},
            "DFS_LOGIN": {"type": "secret_text", "value": config.require("DATAFORSEO_LOGIN")},
            "DFS_PASSWORD": {"type": "secret_text", "value": config.require("DATAFORSEO_PASSWORD")},
        },
        "kv_namespaces": {"REFRESH_KV": {"namespace_id": ns}},
    }}}
    _cf_api(cf, f"/accounts/{acct}/pages/projects/{cf['project']}", "PATCH", payload)
    print("✓ Pages project configured (access key, DataForSEO secrets, queue binding).")
    print("Now run: python worker.py run all && python worker.py deploy")


def _kv(cf, path, method="GET", data=None):
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{cf['account_id']}/storage/kv/namespaces/{cf['kv_namespace']}{path}",
        data=data, method=method, headers={"Authorization": f"Bearer {cf['api_token']}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def loop():
    cf = _cf()
    if not cf.get("kv_namespace"):
        raise SystemExit("No CF_KV_NAMESPACE in .env — run `python worker.py deploy-config` first.")
    run_hour = int(config.env("DAILY_REFRESH_HOUR", "6"))
    last_daily = None
    print(f"Polling queue every 120s; daily refresh at {run_hour:02d}:00. Ctrl-C to stop.")
    while True:
        try:
            # 1. apply keyword/domain management ops queued from the dashboard
            r = subprocess.run([sys.executable, str(REPO / "tracker" / "manage_apply.py")])
            pending = []
            if r.returncode == 10:
                pending.append("rankings")
            # 2. requested refreshes — single "queue" key, not /keys?prefix=
            # (KV free tier caps list ops at 1,000/day; reads at 100,000/day)
            try:
                queued = _kv(cf, "/values/queue")
            except urllib.error.HTTPError:
                queued = {}
            pending += list(queued)
            # 3. daily refresh
            now = datetime.datetime.now()
            if now.hour == run_hour and last_daily != now.date():
                pending.append("rankings-full" if now.weekday() == 0 else "rankings")
                last_daily = now.date()
            if pending:
                print(f"[{now:%F %T}] running: {', '.join(dict.fromkeys(pending))}", flush=True)
                for tool in dict.fromkeys(pending):
                    try:
                        run_tool(tool if tool in TOOLS else "rankings")
                    except SystemExit as e:
                        print(f"  {tool} failed (exit {e.code})", flush=True)
                    _kv(cf, f"/values/last:{tool}", "PUT", f"{now:%F %T}".encode())
                # clear processed tools from the queue, keeping any queued mid-run
                try:
                    q = _kv(cf, "/values/queue")
                except urllib.error.HTTPError:
                    q = {}
                for tool in pending:
                    q.pop(tool, None)
                _kv(cf, "/values/queue", "PUT", json.dumps(q).encode())
                render_all()
                deploy()
        except Exception as e:
            print(f"loop error (retrying in 120s): {e}", flush=True)
        time.sleep(120)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "run":
        target = sys.argv[2] if len(sys.argv) > 2 else "all"
        for t in (list(TOOLS) if target == "all" else [target]):
            if t == "rankings-full":
                continue
            run_tool(t)
        copy_pages()
    elif cmd == "render":
        render_all()
    elif cmd == "serve":
        serve(int(sys.argv[2]) if len(sys.argv) > 2 else 8000)
    elif cmd == "deploy":
        render_all()
        deploy()
    elif cmd == "deploy-config":
        deploy_config()
    elif cmd == "loop":
        loop()
    else:
        print(__doc__)
