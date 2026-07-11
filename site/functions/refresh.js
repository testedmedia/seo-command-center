// Refresh queue endpoint. Auth is enforced by _middleware.js (cookie gate),
// so anything reaching here is already signed in.
const TOOLS = ["rankings", "competitors", "ai-visibility", "site-health", "link-gap", "map-grid", "all"];

const DAILY_LIMIT = 2; // manual refreshes per tool per day — protects API credits

export async function onRequestPost(context) {
  const url = new URL(context.request.url);
  const tool = url.searchParams.get("tool") || "";
  if (!TOOLS.includes(tool)) {
    return json({ ok: false, error: "unknown tool" }, 400);
  }
  const kv = context.env.REFRESH_KV;
  const day = new Date().toISOString().slice(0, 10);
  const countKey = `count:${tool}:${day}`;
  const used = parseInt((await kv.get(countKey)) || "0", 10);
  if (used >= DAILY_LIMIT) {
    return json({ ok: false, error: `daily limit reached (${DAILY_LIMIT}/day per tool)`, used, limit: DAILY_LIMIT }, 429);
  }
  await kv.put(countKey, String(used + 1), { expirationTtl: 172800 });
  // single "queue" key ({tool: ts}) — the worker polls it every cycle, so one
  // read per cycle instead of a kv.list (free tier caps list ops at 1,000/day)
  const queue = JSON.parse((await kv.get("queue")) || "{}");
  queue[tool] = Date.now();
  await kv.put("queue", JSON.stringify(queue));
  return json({ ok: true, queued: tool, used: used + 1, limit: DAILY_LIMIT });
}

export async function onRequestGet(context) {
  const kv = context.env.REFRESH_KV;
  const pending = Object.keys(JSON.parse((await kv.get("queue")) || "{}"));
  const last = {};
  for (const t of TOOLS) {
    const v = await kv.get("last:" + t);
    if (v) last[t] = v;
  }
  return json({ pending, last });
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status, headers: { "Content-Type": "application/json" },
  });
}
