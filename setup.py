#!/usr/bin/env python3
"""SEO Command Center — guided setup. Run: python setup.py

Walks you through everything, validates your DataForSEO credentials with a
free API call, and writes .env + data/keywords.json. Re-run any time; it
won't clobber existing sites unless you tell it to.
"""
import base64
import getpass
import json
import pathlib
import re
import secrets
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parent
ENV = REPO / ".env"
KEYWORDS = REPO / "data" / "keywords.json"

COUNTRIES = {
    "us": (2840, "en", "United States"), "uk": (2826, "en", "United Kingdom"),
    "gb": (2826, "en", "United Kingdom"), "ca": (2124, "en", "Canada"),
    "au": (2036, "en", "Australia"), "de": (2276, "de", "Germany"),
    "fr": (2250, "fr", "France"), "es": (2724, "es", "Spain"),
    "it": (2380, "it", "Italy"), "nl": (2528, "nl", "Netherlands"),
    "br": (2076, "pt", "Brazil"), "mx": (2484, "es", "Mexico"),
    "co": (2170, "es", "Colombia"), "ar": (2032, "es", "Argentina"),
    "in": (2356, "en", "India"), "jp": (2392, "ja", "Japan"),
}


def ask(prompt, default=None, required=True, secret=False):
    sfx = f" [{default}]" if default else ""
    while True:
        try:
            v = (getpass.getpass(f"{prompt}{sfx}: ") if secret else input(f"{prompt}{sfx}: ")).strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit("\nSetup aborted — nothing was written. Run `python setup.py` again any time.")
        if not v and default is not None:
            return default
        if v or not required:
            return v
        print("  (required)")


def yes(prompt, default=False):
    d = "Y/n" if default else "y/N"
    v = input(f"{prompt} ({d}): ").strip().lower()
    return v.startswith("y") if v else default


def validate_dfs(login, password):
    """Free call — confirms the credentials work and shows remaining balance."""
    auth = "Basic " + base64.b64encode(f"{login}:{password}".encode()).decode()
    req = urllib.request.Request("https://api.dataforseo.com/v3/appendix/user_data",
                                 headers={"Authorization": auth})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        money = ((d["tasks"][0]["result"] or [{}])[0].get("money") or {})
        bal = money.get("balance")
        print(f"  ✓ credentials valid" + (f" — balance ${bal:,.2f}" if bal is not None else ""))
        return True
    except urllib.error.HTTPError as e:
        print(f"  ✗ DataForSEO rejected those credentials (HTTP {e.code}). "
              "Use the API login + API password from https://app.dataforseo.com/api-access")
        return False
    except Exception as e:
        print(f"  ✗ could not reach DataForSEO: {e}")
        return False


def main():
    print("\n━━━ SEO Command Center · setup ━━━\n")
    env = {}

    # 1. branding + access key
    brand = ask("Name shown in the dashboard header (enter = keep the Tested Media logo)", "Tested Media")
    if brand != "Tested Media":
        env["BRAND_NAME"] = brand
    print("\nThe access key is the password for your dashboard's login page.")
    env["ACCESS_KEY"] = ask("Access key", secrets.token_urlsafe(12))
    env["AUTH_SALT"] = secrets.token_hex(8)

    # 2. DataForSEO (the only hard requirement)
    print("\nDataForSEO powers rankings, research, competitors and map grids.")
    print("Sign up (pay-as-you-go, ~$0.60/week for 500 keywords): https://dataforseo.com")
    while True:
        login = ask("DataForSEO API login (usually your email)")
        password = ask("DataForSEO API password", secret=True)
        if validate_dfs(login, password):
            break
        print("  Let's try again.\n")
    env["DATAFORSEO_LOGIN"] = login
    env["DATAFORSEO_PASSWORD"] = password

    # 3. sites
    sites = {}
    if KEYWORDS.exists() and not yes("\ndata/keywords.json already exists — replace it?", False):
        sites = None
    if sites is not None:
        print("\nAdd the site(s) you want to track. You can add more later from the dashboard.")
        while True:
            name = ask("\nSite name (e.g. Acme Coffee)")
            domain = ask("Domain (e.g. acmecoffee.com)").lower()
            domain = re.sub(r"^https?://", "", domain).strip("/").replace("www.", "")
            cc = ask("Country code (us, uk, ca, au, de, fr, es, co, …)", "us").lower()
            loc, lang, label = COUNTRIES.get(cc, COUNTRIES["us"])
            print(f"  → Google {label}, language '{lang}'")
            seeds = ask("Seed keywords for research, comma-separated (e.g. specialty coffee beans)", required=False)
            entry = {
                "domain": domain,
                "gsc_site": f"https://{domain}/",
                "geo": None,
                "location_code": loc,
                "language_code": lang,
                "seed_keywords": [s.strip() for s in seeds.split(",") if s.strip()],
                "brand_keywords": [name.lower()],
            }
            sites[name] = entry
            if not yes("Add another site?", False):
                break

    # 4. optional: hosted mode
    print("\nHosted mode puts the dashboard on Cloudflare Pages (free tier) and unlocks")
    print("the in-browser buttons: refresh, add keywords, live research, grid setup.")
    if yes("Configure Cloudflare hosting now?", False):
        print("You need: an account ID (dash.cloudflare.com → any site → right sidebar)")
        print("and an API token with 'Cloudflare Pages: Edit' + 'Workers KV Storage: Edit'")
        print("(dash.cloudflare.com/profile/api-tokens → Create Token).")
        env["CF_ACCOUNT_ID"] = ask("Cloudflare account ID")
        env["CF_API_TOKEN"] = ask("Cloudflare API token", secret=True)
        env["CF_PAGES_PROJECT"] = ask("Pages project name", "seo-command-center")

    # 5. optional: Telegram alerts
    if yes("\nSet up Telegram rank-change alerts?", False):
        print("Create a bot with @BotFather, then message it once and grab your chat id")
        print("from https://api.telegram.org/bot<TOKEN>/getUpdates")
        env["TELEGRAM_BOT_TOKEN"] = ask("Bot token", secret=True)
        env["TELEGRAM_CHAT_ID"] = ask("Chat ID")

    # write
    lines = [f"{k}={v}" for k, v in env.items()]
    ENV.write_text("# SEO Command Center — generated by setup.py (never commit this file)\n"
                   + "\n".join(lines) + "\n")
    print(f"\n✓ wrote .env")
    if sites is not None:
        KEYWORDS.parent.mkdir(exist_ok=True)
        KEYWORDS.write_text(json.dumps({"track_cap": 100, "brands": sites}, indent=2))
        print(f"✓ wrote data/keywords.json ({len(sites)} site{'s' if len(sites) != 1 else ''})")

    print("\n━━━ next steps ━━━")
    print("1. python worker.py run all      # first data pull (~$0.10-0.50 depending on sites)")
    print("2. python worker.py serve        # open http://localhost:8000")
    if env.get("CF_ACCOUNT_ID"):
        print("3. python worker.py deploy-config && python worker.py deploy   # go live")
        print("4. python worker.py loop       # keep it fresh + power the dashboard buttons")
    else:
        print("   (later: re-run setup to add Cloudflare hosting for the in-browser buttons)")
    print()


if __name__ == "__main__":
    main()
