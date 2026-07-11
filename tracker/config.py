"""Shared configuration for SEO Command Center.

Everything user-specific lives in .env (repo root) or real environment
variables. Nothing here is hardcoded to any person, brand, or machine.
Zero third-party dependencies — Python stdlib only.
"""
import base64
import json
import os
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = REPO / "data"
SITE = REPO / "site"
KEYWORDS = DATA / "keywords.json"
DB = DATA / "ranks.db"
RESEARCH_CACHE = DATA / "research-cache.json"

_ENV_LOADED = False


def _load_env():
    """Read .env once and merge into os.environ (env vars win)."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    envfile = REPO / ".env"
    if envfile.exists():
        for line in envfile.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def env(key, default=""):
    _load_env()
    return os.environ.get(key, default)


def require(key, hint=""):
    v = env(key)
    if not v:
        raise SystemExit(
            f"Missing {key} — add it to .env (run `python setup.py` for the guided setup).{' ' + hint if hint else ''}")
    return v


def dfs_header():
    """Authorization header for DataForSEO."""
    login = require("DATAFORSEO_LOGIN", "Sign up at https://dataforseo.com (pay-as-you-go).")
    password = require("DATAFORSEO_PASSWORD")
    return "Basic " + base64.b64encode(f"{login}:{password}".encode()).decode()


DEFAULT_BRAND = "Tested Media"  # made by tested.media — set BRAND_NAME in .env to rebrand
DEFAULT_LOGO = REPO / "assets" / "testedmedia.svg"


def brand_name():
    return env("BRAND_NAME", DEFAULT_BRAND)


def logo_html():
    """Sidebar logo. Priority: LOGO_FILE (your own SVG) → BRAND_NAME wordmark →
    default Tested Media logo."""
    logo_file = env("LOGO_FILE")
    if logo_file and pathlib.Path(logo_file).expanduser().exists():
        return pathlib.Path(logo_file).expanduser().read_text()
    name = brand_name()
    if name == DEFAULT_BRAND and DEFAULT_LOGO.exists():
        return DEFAULT_LOGO.read_text()
    return ('<span style="font-family:\'Plus Jakarta Sans\',sans-serif;font-weight:800;'
            'font-size:15px;letter-spacing:.4px;color:#fff">'
            + name.upper().replace(" ", "&thinsp;|&thinsp;", 1) + "</span>")


def load_keywords():
    if not KEYWORDS.exists():
        raise SystemExit("data/keywords.json not found — run `python setup.py` first.")
    return json.loads(KEYWORDS.read_text())


def gsc_paths():
    """Optional Google Search Console OAuth files. Both must exist to enable GSC."""
    secret = env("GSC_CLIENT_SECRET", str(REPO / "credentials" / "gsc-client-secret.json"))
    tokens = env("GSC_TOKENS", str(REPO / "credentials" / "gsc-tokens.json"))
    return pathlib.Path(secret).expanduser(), pathlib.Path(tokens).expanduser()


def cloudflare():
    """Optional Cloudflare Pages hosting config (None = local-only mode)."""
    acct = env("CF_ACCOUNT_ID")
    token = env("CF_API_TOKEN")
    project = env("CF_PAGES_PROJECT", "seo-command-center")
    if not (acct and token):
        return None
    return {"account_id": acct, "api_token": token, "project": project,
            "kv_namespace": env("CF_KV_NAMESPACE"),
            "auth_email": env("CF_AUTH_EMAIL"), "auth_key": env("CF_GLOBAL_KEY")}


def telegram():
    """Optional Telegram alerts config (None = disabled)."""
    token = env("TELEGRAM_BOT_TOKEN")
    chat = env("TELEGRAM_CHAT_ID")
    return {"token": token, "chat_id": chat} if token and chat else None
