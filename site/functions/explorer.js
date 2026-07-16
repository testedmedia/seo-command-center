// Site Explorer proxy — Ahrefs-style domain/page analysis from the edge via DataForSEO.
// Auth enforced by _middleware.js (cookie gate). Creds = DFS_LOGIN/DFS_PASSWORD Pages secrets.
//
// Tabs (each is one POST {target, tab, ...}):
//   overview     labs domain_rank_overview (organic+paid+traffic value) + backlinks summary
//                + Ahrefs free DR + account balance                              ~$0.03
//   history      labs historical_rank_overview (24mo) + backlinks history (12mo) ~$0.04
//   pages        labs relevant_pages (top pages by organic traffic)              ~$0.01-0.11
//   keywords     labs ranked_keywords w/ movement flags (new/up/down)            ~$0.01-0.11
//   paidkeywords labs ranked_keywords item_types=paid                            ~$0.01
//   backlinks    backlinks/backlinks one_per_domain; mode=all|dofollow|broken|new ~$0.02
//   anchors      backlinks/anchors                                               ~$0.02
//   linkpages    backlinks/domain_pages (pages by referring domains)             ~$0.02
//   broken       backlinks/domain_pages filtered 4xx/5xx w/ live links           ~$0.02
//   refdomains   backlinks/referring_domains                                     ~$0.02
//   competitors  labs competitors_domain                                         ~$0.02
//   contentgap   labs domain_intersection target vs brand (they rank, brand not) ~$0.02
//
// Target may be a bare domain OR a full page URL (Page Inspect mode) — backlinks
// endpoints take either; Labs endpoints get the domain part when given a URL.
// Results cache in KV for 24h per target+tab+params (cache hits are free).
// LIVE pulls capped at DAILY_LIMIT/day across all tabs — a runaway backstop, not
// a budget (a full 11-tab domain analysis ≈ $0.20; 1,000 pulls ≈ $20 worst case).
const DAILY_LIMIT = 1000;
const CACHE_TTL = 86400;
const LABS = "https://api.dataforseo.com/v3/dataforseo_labs/google";
const BL = "https://api.dataforseo.com/v3/backlinks";

export async function onRequestPost(context) {
  const login = context.env.DFS_LOGIN, pass = context.env.DFS_PASSWORD;
  if (!login || !pass)
    return json({ ok: false, error: "DataForSEO credentials not configured on the server" }, 500);

  let body;
  try { body = await context.request.json(); }
  catch { return json({ ok: false, error: "invalid JSON" }, 400); }

  const raw = String(body.target || "").toLowerCase()
    .replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/[#?].*$/, "");
  if (!/^[a-z0-9.-]+\.[a-z]{2,}(\/\S*)?$/.test(raw))
    return json({ ok: false, error: "invalid domain or URL" }, 400);
  const isPage = raw.replace(/\/+$/, "").includes("/");
  const domain = raw.split("/")[0];
  const target = isPage ? "https://" + raw : domain; // backlinks API wants full URL for pages
  const labsTarget = domain;                          // Labs endpoints are domain-scoped
  const tab = String(body.tab || "overview");
  const mode = String(body.mode || "all");
  const vs = String(body.vs || "").toLowerCase().replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/.*$/, "");
  const loc = parseInt(body.location_code, 10) || 2840;
  const lang = /^[a-z]{2}$/.test(body.language_code || "") ? body.language_code : "en";

  const kv = context.env.REFRESH_KV;
  const day = new Date().toISOString().slice(0, 10);
  const cacheKey = `explorer:v3:${tab}:${mode}:${vs}:${raw}:${loc}`;
  const countKey = `count:explorer:${day}`;

  if (!body.force) {
    const hit = await kv.get(cacheKey);
    if (hit) {
      const d = JSON.parse(hit);
      d.cached = true;
      d.used = parseInt((await kv.get(countKey)) || "0", 10);
      d.limit = DAILY_LIMIT;
      return json(d);
    }
  }

  const used = parseInt((await kv.get(countKey)) || "0", 10);
  if (used >= DAILY_LIMIT)
    return json({ ok: false, error: `daily explorer limit reached (${DAILY_LIMIT}/day)`, used, limit: DAILY_LIMIT }, 429);

  const auth = "Basic " + btoa(login + ":" + pass);
  async function dfs(url, payload) {
    const r = await fetch(url, {
      method: "POST",
      headers: { Authorization: auth, "Content-Type": "application/json" },
      body: JSON.stringify([payload]),
    });
    const d = await r.json();
    const task = (d.tasks || [])[0] || {};
    if (task.status_code && task.status_code >= 40000)
      throw new Error("DataForSEO: " + (task.status_message || task.status_code));
    return { cost: d.cost || 0, result: ((task.result || [])[0]) || {} };
  }
  const n = v => v == null ? 0 : Math.round(v);
  const kwRow = it => {
    const kd = it.keyword_data || {}, ki = kd.keyword_info || {};
    const se = ((it.ranked_serp_element || {}).serp_item) || {};
    const rc = se.rank_changes || {};
    return { kw: kd.keyword || "", rank: se.rank_absolute || null,
             prev: rc.previous_rank_absolute || null,
             move: rc.is_new ? "new" : rc.is_up ? "up" : rc.is_down ? "down" : "",
             vol: n(ki.search_volume), cpc: Math.round((ki.cpc || 0) * 100) / 100,
             traffic: n(se.etv), url: se.relative_url || se.url || "" };
  };

  let out = { ok: true, target: raw, tab, isPage, rows: [] };
  let cost = 0;
  try {
    if (tab === "overview") {
      const [rank, bl] = await Promise.allSettled([
        dfs(`${LABS}/domain_rank_overview/live`, { target: labsTarget, location_code: loc, language_code: lang }),
        dfs(`${BL}/summary/live`, { target, internal_list_limit: 10, backlinks_status_type: "live" }),
      ]);
      let dr = null, balance = null;
      try {
        const r = await fetch(`https://api.ahrefs.com/v3/public/domain-rating-free?target=${domain}`,
          { headers: { Accept: "application/json" } });
        dr = (await r.json())?.domain_rating?.domain_rating ?? null;
      } catch {}
      try {
        const r = await fetch("https://api.dataforseo.com/v3/appendix/user_data",
          { headers: { Authorization: auth } });
        balance = (await r.json())?.tasks?.[0]?.result?.[0]?.money?.balance ?? null;
      } catch {}
      const o = {};
      if (rank.status === "fulfilled") {
        cost += rank.value.cost;
        const m = ((rank.value.result.items || [])[0] || {}).metrics || {};
        const org = m.organic || {}, paid = m.paid || {};
        o.traffic = n(org.etv); o.keywords = n(org.count);
        o.top3 = n(org.pos_1) + n(org.pos_2_3);
        o.page1 = o.top3 + n(org.pos_4_10);
        o.traffic_value = n(org.estimated_paid_traffic_cost);
        o.paid_traffic = n(paid.etv); o.paid_keywords = n(paid.count);
      }
      if (bl.status === "fulfilled") {
        cost += bl.value.cost;
        const s = bl.value.result;
        o.dfs_rank = n(s.rank); o.backlinks = n(s.backlinks);
        o.ref_domains = n(s.referring_main_domains || s.referring_domains);
        o.broken_pages = n(s.broken_pages); o.broken_backlinks = n(s.broken_backlinks);
        o.spam_score = n(s.target_spam_score);
      } else {
        o.backlinks_error = String(bl.reason && bl.reason.message || bl.reason || "backlinks unavailable");
      }
      o.dr = dr; o.balance = balance;
      out.overview = o;
    } else if (tab === "history") {
      const from = new Date(); from.setMonth(from.getMonth() - 24);
      const blFrom = new Date(); blFrom.setMonth(blFrom.getMonth() - 12);
      const [labs, bl] = await Promise.allSettled([
        dfs(`${LABS}/historical_rank_overview/live`, {
          target: labsTarget, location_code: loc, language_code: lang,
          date_from: from.toISOString().slice(0, 10) }),
        dfs(`${BL}/history/live`, { target: domain, date_from: blFrom.toISOString().slice(0, 10) }),
      ]);
      out.organic = []; out.links = [];
      if (labs.status === "fulfilled") {
        cost += labs.value.cost;
        out.organic = (labs.value.result.items || []).map(it => {
          const o = (it.metrics || {}).organic || {}, p = (it.metrics || {}).paid || {};
          return { ym: `${it.year}-${String(it.month).padStart(2, "0")}`,
                   traffic: n(o.etv), keywords: n(o.count),
                   top3: n(o.pos_1) + n(o.pos_2_3),
                   pos4_10: n(o.pos_4_10),
                   pos11_50: n(o.pos_11_20) + n(o.pos_21_30) + n(o.pos_31_40) + n(o.pos_41_50),
                   paid_traffic: n(p.etv) };
        }).sort((a, b) => a.ym < b.ym ? -1 : 1);
      }
      if (bl.status === "fulfilled") {
        cost += bl.value.cost;
        out.links = (bl.value.result.items || []).map(it => ({
          ym: String(it.date || "").slice(0, 7),
          backlinks: n(it.backlinks), ref_domains: n(it.referring_main_domains || it.referring_domains),
          new_links: n(it.new_backlinks), lost_links: n(it.lost_backlinks),
          new_domains: n(it.new_referring_domains), lost_domains: n(it.lost_referring_domains),
          rank: n(it.rank) })).sort((a, b) => a.ym < b.ym ? -1 : 1);
      }
      if (!out.organic.length && !out.links.length) throw new Error("no history available for this target");
    } else if (tab === "pages") {
      const r = await dfs(`${LABS}/relevant_pages/live`, {
        target: labsTarget, location_code: loc, language_code: lang,
        order_by: ["metrics.organic.etv,desc"], limit: 100 });
      cost += r.cost;
      out.rows = (r.result.items || []).map(it => {
        const m = (it.metrics || {}).organic || {};
        return { url: it.page_address, traffic: n(m.etv), keywords: n(m.count), top3: n(m.pos_1) + n(m.pos_2_3) };
      });
    } else if (tab === "keywords" || tab === "paidkeywords") {
      const payload = { target: isPage && tab === "keywords" ? target : labsTarget,
        location_code: loc, language_code: lang,
        order_by: ["ranked_serp_element.serp_item.etv,desc"], limit: 200 };
      if (tab === "paidkeywords") payload.item_types = ["paid"];
      const r = await dfs(`${LABS}/ranked_keywords/live`, payload);
      cost += r.cost;
      out.rows = (r.result.items || []).map(kwRow);
    } else if (tab === "backlinks") {
      const payload = { target, limit: 100, mode: "one_per_domain",
        order_by: ["domain_from_rank,desc"] };
      if (mode === "dofollow") payload.filters = ["dofollow", "=", true];
      else if (mode === "broken") payload.filters = ["is_broken", "=", true];
      else if (mode === "new") {
        const d90 = new Date(); d90.setDate(d90.getDate() - 90);
        payload.filters = ["first_seen", ">", d90.toISOString().slice(0, 10) + " 00:00:00 +00:00"];
      }
      const r = await dfs(`${BL}/backlinks/live`, payload);
      cost += r.cost;
      out.rows = (r.result.items || []).map(it => ({
        url_from: it.url_from || "", title: (it.page_from_title || "").slice(0, 120),
        anchor: (it.anchor || "").slice(0, 120), url_to: it.url_to || "",
        domain_rank: n(it.domain_from_rank), dofollow: !!it.dofollow,
        spam: n(it.backlink_spam_score),
        flag: it.is_broken ? "broken" : it.is_lost ? "lost" : it.is_new ? "new" : "",
        first_seen: (it.first_seen || "").slice(0, 10) }));
    } else if (tab === "anchors") {
      const r = await dfs(`${BL}/anchors/live`, {
        target, limit: 100, order_by: ["referring_domains,desc"] });
      cost += r.cost;
      out.rows = (r.result.items || []).map(it => ({
        anchor: it.anchor == null || it.anchor === "" ? "(empty)" : String(it.anchor).slice(0, 120),
        ref_domains: n(it.referring_main_domains || it.referring_domains),
        backlinks: n(it.backlinks), spam: n(it.backlinks_spam_score),
        first_seen: (it.first_seen || "").slice(0, 10) }));
    } else if (tab === "linkpages") {
      const r = await dfs(`${BL}/domain_pages/live`, {
        target: domain, limit: 100, order_by: ["page_summary.referring_domains,desc"] });
      cost += r.cost;
      out.rows = (r.result.items || []).map(it => {
        const s = it.page_summary || {};
        return { url: it.page || "", ref_domains: n(s.referring_main_domains || s.referring_domains),
                 backlinks: n(s.backlinks), rank: n(s.rank), first_seen: (s.first_seen || "").slice(0, 10) };
      }).filter(r => r.url);
    } else if (tab === "broken") {
      // Broken pages = 4xx/5xx pages that still have live backlinks pointing at them.
      const r = await dfs(`${BL}/domain_pages/live`, {
        target: domain, limit: 100,
        filters: [["status_code", ">=", 400], "and", ["page_summary.backlinks", ">", 0]],
        order_by: ["page_summary.referring_domains,desc"] });
      cost += r.cost;
      out.rows = (r.result.items || []).map(it => {
        const s = it.page_summary || {};
        return { url: it.page || "", status: n(it.status_code),
                 ref_domains: n(s.referring_main_domains || s.referring_domains), backlinks: n(s.backlinks) };
      }).filter(r => r.url);
    } else if (tab === "refdomains") {
      const r = await dfs(`${BL}/referring_domains/live`, {
        target, limit: 100, order_by: ["rank,desc"], backlinks_status_type: "live" });
      cost += r.cost;
      out.rows = (r.result.items || []).map(it => ({
        domain: it.domain || "", rank: n(it.rank),
        backlinks: n(it.backlinks), first_seen: (it.first_seen || "").slice(0, 10) }));
    } else if (tab === "competitors") {
      const r = await dfs(`${LABS}/competitors_domain/live`, {
        target: labsTarget, location_code: loc, language_code: lang, limit: 50 });
      cost += r.cost;
      out.rows = (r.result.items || []).filter(it => it.domain !== labsTarget).map(it => {
        const full = ((it.full_domain_metrics || {}).organic) || {};
        return { domain: it.domain || "", shared_kw: n(it.intersections),
                 avg_pos: Math.round((it.avg_position || 0) * 10) / 10,
                 traffic: n(full.etv), keywords: n(full.count) };
      });
    } else if (tab === "contentgap") {
      if (!/^[a-z0-9.-]+\.[a-z]{2,}$/.test(vs)) return json({ ok: false, error: "pick a brand to compare against" }, 400);
      const r = await dfs(`${LABS}/domain_intersection/live`, {
        target1: labsTarget, target2: vs, intersections: false,
        location_code: loc, language_code: lang, limit: 200,
        order_by: ["first_domain_serp_element.etv,desc"] });
      cost += r.cost;
      out.rows = (r.result.items || []).map(it => {
        const kd = it.keyword_data || {}, ki = kd.keyword_info || {};
        const se1 = it.first_domain_serp_element || {};
        return { kw: kd.keyword || "", their_rank: se1.rank_absolute || null,
                 vol: n(ki.search_volume), cpc: Math.round((ki.cpc || 0) * 100) / 100,
                 traffic: n(se1.etv), url: se1.relative_url || se1.url || "" };
      });
    } else {
      return json({ ok: false, error: "unknown tab" }, 400);
    }
  } catch (e) {
    return json({ ok: false, error: e.message }, 502);
  }

  out.cost = Math.round(cost * 10000) / 10000;
  await kv.put(countKey, String(used + 1), { expirationTtl: 172800 });
  await kv.put(cacheKey, JSON.stringify(out), { expirationTtl: CACHE_TTL });
  out.used = used + 1; out.limit = DAILY_LIMIT; out.cached = false;
  return json(out);
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
}
