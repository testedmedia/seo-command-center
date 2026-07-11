// Keyword/URL management queue. Auth enforced by _middleware.js.
// Ops are queued in KV; the Mini poller applies them to keywords.json,
// re-tracks, and redeploys within ~2-5 minutes.
const ACTIONS = ["add_keywords", "remove_keyword", "add_domain", "remove_domain",
  "set_geogrid", "add_geogrid_keywords", "remove_geogrid_keyword", "remove_geogrid"];
const TIERS = ["target", "brand", "local", "seed"];

export async function onRequestPost(context) {
  let body;
  try {
    body = await context.request.json();
  } catch {
    return json({ ok: false, error: "invalid JSON" }, 400);
  }
  const action = body.action || "";
  if (!ACTIONS.includes(action)) return json({ ok: false, error: "unknown action" }, 400);

  if (action === "add_keywords") {
    if (!body.brand || !Array.isArray(body.keywords) || !body.keywords.length)
      return json({ ok: false, error: "brand + keywords[] required" }, 400);
    if (body.keywords.length > 50) return json({ ok: false, error: "max 50 keywords per add" }, 400);
    if (!TIERS.includes(body.tier || "target")) return json({ ok: false, error: "bad tier" }, 400);
  }
  if (action === "remove_keyword" && (!body.brand || !body.keyword))
    return json({ ok: false, error: "brand + keyword required" }, 400);
  if (action === "add_domain") {
    const dom = (body.domain || "").toLowerCase().replace(/^https?:\/\//, "").replace(/\/.*$/, "");
    if (!/^[a-z0-9.-]+\.[a-z]{2,}$/.test(dom)) return json({ ok: false, error: "invalid domain" }, 400);
    if (!body.name) return json({ ok: false, error: "name required" }, 400);
    body.domain = dom;
  }
  if (action === "remove_domain" && !body.brand)
    return json({ ok: false, error: "brand required" }, 400);
  if (action === "set_geogrid") {
    if (!body.brand) return json({ ok: false, error: "brand required" }, 400);
    const c = body.center;
    if (!Array.isArray(c) || c.length !== 2 || !isFinite(c[0]) || !isFinite(c[1])
        || Math.abs(c[0]) > 90 || Math.abs(c[1]) > 180)
      return json({ ok: false, error: "center must be [lat, lng]" }, 400);
    if (![5, 7, 9].includes(body.grid | 0)) return json({ ok: false, error: "grid must be 5, 7 or 9" }, 400);
    const sp = Number(body.spacing_miles);
    if (!(sp >= 0.5 && sp <= 15)) return json({ ok: false, error: "spacing 0.5-15 miles" }, 400);
    if (!Array.isArray(body.keywords) || !body.keywords.length || body.keywords.length > 5)
      return json({ ok: false, error: "1-5 keywords" }, 400);
  }
  if (action === "add_geogrid_keywords") {
    if (!body.brand || !Array.isArray(body.keywords) || !body.keywords.length || body.keywords.length > 5)
      return json({ ok: false, error: "brand + 1-5 keywords required" }, 400);
  }
  if (action === "remove_geogrid_keyword" && (!body.brand || !body.keyword))
    return json({ ok: false, error: "brand + keyword required" }, 400);
  if (action === "remove_geogrid" && !body.brand)
    return json({ ok: false, error: "brand required" }, 400);

  const id = "mgmt:" + Date.now() + ":" + Math.random().toString(36).slice(2, 8);
  await context.env.REFRESH_KV.put(id, JSON.stringify(body), { expirationTtl: 604800 });
  // dirty flag lets the worker skip the KV list call (1,000/day free-tier cap)
  await context.env.REFRESH_KV.put("mgmt-dirty", "1", { expirationTtl: 604800 });
  return json({ ok: true, queued: action, id, eta: "~2-5 min" });
}

export async function onRequestGet(context) {
  const keys = (await context.env.REFRESH_KV.list({ prefix: "mgmt:" })).keys;
  const pending = [];
  for (const k of keys) {
    const v = await context.env.REFRESH_KV.get(k.name);
    if (v) pending.push(JSON.parse(v));
  }
  return json({ pending });
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
}
