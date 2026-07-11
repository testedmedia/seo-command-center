// Live keyword research proxy — calls DataForSEO from the edge so credentials
// never reach the browser. Auth enforced by _middleware.js (cookie gate).
// Cost guard: DAILY_LIMIT runs/day tracked in KV. Each run ≈ $0.01-0.05.
const DAILY_LIMIT = 20;
const SUGGEST_API = "https://api.dataforseo.com/v3/dataforseo_labs/google/keyword_suggestions/live";
const RANKED_API = "https://api.dataforseo.com/v3/dataforseo_labs/google/ranked_keywords/live";
const MAX_SEEDS = 5;

export async function onRequestPost(context) {
  const login = context.env.DFS_LOGIN, pass = context.env.DFS_PASSWORD;
  if (!login || !pass)
    return json({ ok: false, error: "DataForSEO credentials not configured on the server" }, 500);

  let body;
  try { body = await context.request.json(); }
  catch { return json({ ok: false, error: "invalid JSON" }, 400); }

  const mode = body.mode || "";
  const loc = parseInt(body.location_code, 10) || 2840;
  const lang = /^[a-z]{2}$/.test(body.language_code || "") ? body.language_code : "en";

  let tasks = [];
  if (mode === "seeds") {
    const seeds = (Array.isArray(body.seeds) ? body.seeds : [])
      .map(s => String(s).trim().slice(0, 80)).filter(Boolean).slice(0, MAX_SEEDS);
    if (!seeds.length) return json({ ok: false, error: "at least one seed keyword required" }, 400);
    tasks = seeds.map(seed => ({
      url: SUGGEST_API,
      payload: [{ keyword: seed, location_code: loc, language_code: lang, limit: 40,
                  order_by: ["keyword_info.search_volume,desc"] }],
    }));
  } else if (mode === "competitor") {
    const dom = String(body.domain || "").toLowerCase()
      .replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/.*$/, "");
    if (!/^[a-z0-9.-]+\.[a-z]{2,}$/.test(dom)) return json({ ok: false, error: "invalid domain" }, 400);
    tasks = [{
      url: RANKED_API,
      payload: [{ target: dom, location_code: loc, language_code: lang, limit: 200,
                  order_by: ["keyword_data.keyword_info.search_volume,desc"] }],
    }];
  } else {
    return json({ ok: false, error: "mode must be seeds or competitor" }, 400);
  }

  // rate limit
  const kv = context.env.REFRESH_KV;
  const day = new Date().toISOString().slice(0, 10);
  const countKey = `count:research:${day}`;
  const used = parseInt((await kv.get(countKey)) || "0", 10);
  if (used >= DAILY_LIMIT)
    return json({ ok: false, error: `daily research limit reached (${DAILY_LIMIT}/day)`, used, limit: DAILY_LIMIT }, 429);
  await kv.put(countKey, String(used + 1), { expirationTtl: 172800 });

  const auth = "Basic " + btoa(login + ":" + pass);
  const rows = new Map();
  let cost = 0;
  for (const t of tasks) {
    let d;
    try {
      const r = await fetch(t.url, {
        method: "POST",
        headers: { Authorization: auth, "Content-Type": "application/json" },
        body: JSON.stringify(t.payload),
      });
      d = await r.json();
    } catch (e) {
      return json({ ok: false, error: "DataForSEO request failed: " + e.message }, 502);
    }
    cost += d.cost || 0;
    const task = (d.tasks || [])[0] || {};
    if (task.status_code && task.status_code >= 40000)
      return json({ ok: false, error: "DataForSEO: " + (task.status_message || task.status_code) }, 502);
    const items = ((task.result || [])[0] || {}).items || [];
    for (const it of items) {
      // suggestions: keyword at top level; ranked: nested under keyword_data
      const kd = it.keyword_data || it;
      const ki = kd.keyword_info || {};
      const kw = (kd.keyword || "").trim();
      if (!kw || rows.has(kw.toLowerCase())) continue;
      const se = ((it.ranked_serp_element || {}).serp_item) || {};
      rows.set(kw.toLowerCase(), {
        kw,
        vol: ki.search_volume || 0,
        cpc: Math.round((ki.cpc || 0) * 100) / 100,
        comp: ki.competition_level || (ki.competition != null ? String(ki.competition) : ""),
        rank: se.rank_absolute || null,
      });
    }
  }
  const out = [...rows.values()].sort((a, b) => b.vol - a.vol).slice(0, 300);
  return json({ ok: true, rows: out, cost: Math.round(cost * 10000) / 10000, used: used + 1, limit: DAILY_LIMIT });
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
}
