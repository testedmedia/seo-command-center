#!/usr/bin/env python3
"""Local map-pack geogrid tracker (LocalFalcon-style).

For each brand with a `geogrid` block in keywords.json:
  1. Build an N×N grid of GPS points around the service-area center.
  2. For each keyword × point, query Google Maps SERP FROM that exact point
     and find the brand's map-pack rank there.
  3. Store one row per (point, keyword) in the `geogrid` SQLite table.
  4. render() emits map-grid.html — a dark Leaflet map with a colored,
     numbered pin per point (green ≤3, orange 4-10, red 11+/absent),
     keyword chips, a run selector, and a compare-to-previous-run toggle.

Cost ≈ $0.002/pull. 7×7 × 3 keywords = $0.29/run per brand. Weekly, not daily.

Usage: seo-geogrid.py [track|render|both]   (default: both)
"""
import base64, json, math, pathlib, sqlite3, sys, urllib.request, datetime
import config
import shell as seo_shell

BASE = config.DATA
KEYWORDS = config.KEYWORDS
DB = config.DB
OUT_HTML = config.DATA / "map-grid.html"
MAPS_API = "https://api.dataforseo.com/v3/serp/google/maps/live/advanced"
DEPTH = 20
COST_PER_PULL = 0.002  # measured 2026-07-11


dfs_header = config.dfs_header


def post(url, header, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": header, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def init_db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS geogrid(
        checked_at TEXT, brand TEXT, keyword TEXT,
        lat REAL, lng REAL, rank INTEGER)""")
    con.execute("CREATE INDEX IF NOT EXISTS ix_geogrid ON geogrid(brand,keyword,checked_at)")
    try:
        con.execute("ALTER TABLE geogrid ADD COLUMN top3 TEXT")
    except sqlite3.OperationalError:
        pass
    con.commit()
    return con


def grid_points(center, n, spacing_miles):
    """N×N grid of (lat,lng) centered on `center`, `spacing_miles` apart."""
    lat0, lng0 = center
    half = (n - 1) / 2.0
    dlat = spacing_miles / 69.0
    dlng = spacing_miles / (69.0 * math.cos(math.radians(lat0)))
    pts = []
    for r in range(n):                       # north (top) -> south
        for c in range(n):                   # west (left) -> east
            lat = lat0 + (half - r) * dlat
            lng = lng0 + (c - half) * dlng
            pts.append((round(lat, 6), round(lng, 6)))
    return pts


def brand_rank_at(header, keyword, lat, lng, zoom, domain, brand_name):
    """Map-pack rank of the brand at one GPS point + who holds the top 3 there.
    Returns (rank or None, top3 list of {t: title, r: rank}, cost)."""
    dom = domain.lower().replace("www.", "")
    bname = brand_name.lower()
    coord = f"{lat},{lng},{zoom}"
    d = post(MAPS_API, header, [{"keyword": keyword, "location_coordinate": coord,
             "language_code": "en", "depth": DEPTH}])
    cost = d.get("cost", 0) or COST_PER_PULL
    items = (d["tasks"][0].get("result") or [{}])[0].get("items") or []
    rank, top3 = None, []
    for it in items:
        rg = it.get("rank_group") or it.get("rank_absolute")
        if rg and rg <= 3 and it.get("title"):
            top3.append({"t": it["title"][:60], "r": rg})
        if rank is None:
            idom = (it.get("domain") or "").lower().replace("www.", "")
            title = (it.get("title") or "").lower()
            if idom == dom or idom.endswith("." + dom) or (bname and bname in title):
                rank = rg
    return rank, top3[:3], cost


def track():
    header = dfs_header()
    cfg = json.loads(config.KEYWORDS.read_text())
    con = init_db()
    checked_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    total = 0.0
    for brand, meta in cfg["brands"].items():
        gg = meta.get("geogrid")
        if not gg:
            continue
        domain = meta["domain"]
        bname = (meta.get("brand_keywords") or [brand])[0]
        n = int(gg.get("grid", 7))
        zoom = gg.get("zoom", "13z")
        pts = grid_points(gg["center"], n, float(gg.get("spacing_miles", 3.5)))
        print(f"{brand}: {n}x{n}={len(pts)} pts × {len(gg['keywords'])} kw @ {zoom}", flush=True)
        rows = []
        for kw in gg["keywords"]:
            found, ranks = 0, []
            for (lat, lng) in pts:
                try:
                    rank, top3_here, c = brand_rank_at(header, kw, lat, lng, zoom, domain, bname)
                    total += c
                except Exception as e:
                    print(f"    '{kw}' @ {lat},{lng} failed: {e}", flush=True)
                    rank, top3_here = None, []
                rows.append((checked_at, brand, kw, lat, lng, rank,
                             json.dumps(top3_here) if top3_here else None))
                if rank is not None:
                    found += 1
                    ranks.append(rank)
            avg = f"{sum(ranks)/len(ranks):.1f}" if ranks else "—"
            top3 = sum(1 for r in ranks if r <= 3)
            print(f"    {kw:26} in-pack {found}/{len(pts)}  avg {avg}  top3 {top3}", flush=True)
        con.executemany("INSERT INTO geogrid(checked_at,brand,keyword,lat,lng,rank,top3) VALUES (?,?,?,?,?,?,?)", rows)
        con.commit()
    con.close()
    print(f"\nTotal cost ${total:.4f} at {checked_at}", flush=True)
    return total


def _load_runs():
    """{brand: {keyword: {checked_at: [{lat,lng,rank}, ...]}}} from all stored runs."""
    con = init_db()
    data = {}
    for ca, brand, kw, lat, lng, rank, top3 in con.execute(
            "SELECT checked_at,brand,keyword,lat,lng,rank,top3 FROM geogrid ORDER BY checked_at,keyword"):
        pt = {"lat": lat, "lng": lng, "rank": rank}
        if top3:
            try:
                pt["top3"] = json.loads(top3)
            except ValueError:
                pass
        data.setdefault(brand, {}).setdefault(kw, {}).setdefault(ca, []).append(pt)
    con.close()
    # include configured keywords that have NO scan yet, so a just-added keyword
    # shows its chip immediately (with a "scan in progress" state) instead of vanishing
    try:
        cfg = json.loads(config.KEYWORDS.read_text())
        for brand, meta in cfg["brands"].items():
            gg = meta.get("geogrid")
            if gg:
                for kw in gg.get("keywords", []):
                    data.setdefault(brand, {}).setdefault(kw, {})
    except Exception:
        pass
    return data


EXTRA_CSS = """
.bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:12px 18px;border-bottom:1px solid var(--line)}
.bar .lbl{font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--mut);margin-right:2px}
.chip{background:none;border:1px solid var(--line);color:var(--ink2);border-radius:100px;padding:6px 13px;font-size:12.5px;cursor:pointer;font-family:'Inter';font-weight:500}
.chip.on{color:var(--gold);border-color:rgba(255,122,46,.5);background:rgba(255,122,46,.08)}
.chip:hover{color:var(--ink)}
.chipx{display:none;margin-left:7px;color:#6b4a4a;font-size:11px}
.chip:hover .chipx{display:inline}
.chipx:hover{color:var(--down)}
.runsel{display:flex;align-items:center;gap:8px;margin-left:auto}
.runsel button{background:none;border:1px solid var(--line);color:var(--ink2);border-radius:8px;width:30px;height:30px;cursor:pointer;font-size:15px}
.runsel button:hover:not(:disabled){color:var(--gold);border-color:rgba(255,122,46,.4)}
.runsel button:disabled{opacity:.3;cursor:default}
.runsel .rlabel{font-size:12.5px;color:var(--ink2);min-width:150px;text-align:center;font-variant-numeric:tabular-nums}
.cmp{display:flex;align-items:center;gap:7px;font-size:12.5px;color:var(--ink2);cursor:pointer;user-select:none}
.cmp input{accent-color:var(--gold);width:15px;height:15px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line)}
.kpi{background:var(--card);padding:14px 18px}
.kpi .v{font-family:'Plus Jakarta Sans';font-weight:800;font-size:22px;font-variant-numeric:tabular-nums}
.kpi .k{color:var(--mut);font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;margin-top:2px}
.kd{font-size:11.5px;margin-left:8px;font-weight:700;vertical-align:3px}
.kd.up{color:var(--up)}.kd.down{color:var(--down)}.kd.flat{color:var(--mut)}
.ghist{padding:12px 18px 8px;border-top:1px solid var(--line)}
.glbl{font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--mut);margin-bottom:6px;display:flex;gap:16px;align-items:center}
.glbl .dot{width:9px;height:9px;border-radius:2px;margin-right:5px}
.gempty{color:var(--mut);font-size:12px;padding:8px 0 14px}
.map{height:520px;width:100%;background:#0a0a0e}
.leaflet-container{background:#0a0a0e}
.tilepane{filter:none}
.leaflet-control-attribution{background:rgba(0,0,0,.5)!important;color:#76767f!important}
.leaflet-control-attribution a{color:#b6b6bd!important}
.gpin{display:flex;align-items:center;justify-content:center;font-family:'Plus Jakarta Sans';font-weight:800;font-size:12px;color:#06110b;border-radius:50%;border:2px solid rgba(0,0,0,.55);box-shadow:0 2px 6px rgba(0,0,0,.5)}
.gpin .delta{position:absolute;top:-8px;right:-8px;font-size:9px;font-weight:800;padding:0 3px;border-radius:6px;line-height:14px}
.swatch{display:inline-flex;align-items:center;gap:5px;margin-right:14px}
.dot{width:11px;height:11px;border-radius:50%;display:inline-block}
.empty{padding:40px 18px;color:var(--mut);font-size:13px;text-align:center}
@media(max-width:720px){.kpis{grid-template-columns:repeat(2,1fr)}.runsel{margin-left:0}}
"""


def render():
    data = _load_runs()
    logo = config.logo_html()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    cfg = json.loads(config.KEYWORDS.read_text())
    centers = {b: (m.get("geogrid") or {}).get("center")
               for b, m in cfg["brands"].items() if m.get("geogrid")}
    brand_cfg = {b: (m.get("geogrid") or None) for b, m in cfg["brands"].items()}
    payload = json.dumps({"data": data, "centers": centers, "brands": brand_cfg})
    content = """<p class="legend">
<span class="swatch"><i class="dot" style="background:#39d98a"></i>Top 3 (in the pack)</span>
<span class="swatch"><i class="dot" style="background:#ff7a2e"></i>4–10</span>
<span class="swatch"><i class="dot" style="background:#ff5c5c"></i>11+ / not shown</span>
Each pin = your Google map-pack rank when someone searches from that exact spot.
<button class="rfr" id="cfgbtn" style="margin-left:12px;padding:5px 12px;font-size:12px">⚙ Set up grid</button></p>
<div id="mount"></div>
<div class="overlay" id="ggModal">
  <div class="modal">
    <h3>Grid setup</h3>
    <div class="mhint">Track your Google map-pack rank across a grid of GPS points. Scans run on the next queue pass (~2-5 min), then weekly.</div>
    <div class="mlbl">Brand</div><div class="chips" id="ggBrand"></div>
    <div class="mlbl">Grid center — lat, lng</div>
    <input id="ggCenter" placeholder="30.2672, -97.7431">
    <div class="mhint">Google Maps → right-click your service-area center → click the coordinates to copy them.</div>
    <div class="mlbl">Grid size</div>
    <div class="chips" id="ggSize">
      <button data-v="5">5 × 5</button><button data-v="7" class="on">7 × 7</button><button data-v="9">9 × 9</button>
    </div>
    <div class="mlbl">Point spacing (miles)</div>
    <input id="ggSpacing" type="number" step="0.5" min="0.5" max="15" value="3.5">
    <div class="mlbl">Keywords — one per line (max 5)</div>
    <textarea id="ggKws" rows="4" placeholder="dentist&#10;emergency dentist"></textarea>
    <div class="mrow">
      <button class="mbtn ghost" id="ggRemove" style="margin-right:auto;color:var(--down);border-color:rgba(255,92,92,.35);display:none">Remove grid</button>
      <button class="mbtn ghost" data-close>Cancel</button><button class="mbtn go" id="ggGo">Save grid</button>
    </div>
  </div>
</div>
<div id="toast"></div>"""
    body_end = """<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
var PAYLOAD = __PAYLOAD__;
var DATA = PAYLOAD.data, CENTERS = PAYLOAD.centers, BRANDCFG = PAYLOAD.brands;
function toast(msg){ var t=document.getElementById('toast'); t.textContent=msg; t.style.display='block'; clearTimeout(t._h); t._h=setTimeout(function(){t.style.display='none';},5000); }
function manage(body, okMsg){
  return fetch('/manage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(function(r){return r.json();})
    .then(function(d){ toast(d.ok?okMsg:('Failed: '+(d.error||'unknown'))); return d.ok; })
    .catch(function(){ toast('Request failed — try again'); return false; });
}
function pinColor(r){ if(r===null||r===undefined) return '#ff5c5c'; if(r<=3) return '#39d98a'; if(r<=10) return '#ff7a2e'; return '#ff5c5c'; }
function pinText(r){ return (r===null||r===undefined) ? '\\u2014' : String(r); }
function commas(n){ return n.toLocaleString('en-US'); }

function runStats(pts){
  var sum=0,ranked=0,t3=0,t10=0;
  pts.forEach(function(p){var r=p.rank; if(r!==null&&r!==undefined){sum+=r;ranked++;if(r<=3)t3++;if(r<=10)t10++;}});
  var n=pts.length||1;
  return {avg: ranked? sum/ranked : null, t3: t3/n*100, t10: t10/n*100, n: pts.length};
}
function setKd(card, sel, diff, fmt){
  var el=card.querySelector(sel); if(!el) return;
  el.classList.remove('up','down');
  if(diff===null||diff===undefined||Math.abs(diff)<0.05){ el.textContent=''; return; }
  var up=diff>0;  // positive = improvement (caller orients the sign)
  el.textContent=(up?'▲':'▼')+fmt(Math.abs(diff));
  el.classList.add(up?'up':'down');
}
function renderTrend(card, runsMap){
  var runs=Object.keys(runsMap).sort();
  var st=runs.map(function(r){var s=runStats(runsMap[r]); s.run=r; return s;});
  var el=card.querySelector('.gsvg'); if(!el) return;
  if(st.length<2){ el.innerHTML='<div class="gempty">Trend chart appears after the next scan ('+st.length+' run stored so far). Every scan is kept forever.</div>'; return; }
  var W=640,H=120,P=26;
  var maxAvg=Math.max.apply(null,st.map(function(s){return s.avg===null?20:s.avg;}).concat([10]));
  function x(i){return P + i*(W-2*P)/(st.length-1);}
  function yAvg(v){return P + (v-1)/(maxAvg-1)*(H-2*P);}
  function yPct(v){return (H-P) - v/100*(H-2*P);}
  var avgLine=st.map(function(s,i){return x(i)+','+yAvg(s.avg===null?maxAvg:s.avg);}).join(' ');
  var t3Line=st.map(function(s,i){return x(i)+','+yPct(s.t3);}).join(' ');
  var dots='';
  st.forEach(function(s,i){
    dots+='<circle cx="'+x(i)+'" cy="'+yAvg(s.avg===null?maxAvg:s.avg)+'" r="3.5" fill="#ff7a2e"><title>'+s.run+' — avg rank '+(s.avg===null?'not in pack':s.avg.toFixed(1))+'</title></circle>';
    dots+='<circle cx="'+x(i)+'" cy="'+yPct(s.t3)+'" r="3.5" fill="#39d98a"><title>'+s.run+' — top 3: '+Math.round(s.t3)+'% of pins</title></circle>';
  });
  var labels='';
  var step=Math.max(1,Math.ceil(st.length/6));
  st.forEach(function(s,i){ if(i%step===0||i===st.length-1){ labels+='<text x="'+x(i)+'" y="'+(H-4)+'" fill="#76767f" font-size="9.5" text-anchor="middle">'+s.run.slice(5,10)+'</text>'; }});
  el.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:'+H+'px;display:block" preserveAspectRatio="xMidYMid meet">'
    +'<line x1="'+P+'" y1="'+(H-P)+'" x2="'+(W-P)+'" y2="'+(H-P)+'" stroke="rgba(255,255,255,.13)"/>'
    +'<polyline points="'+t3Line+'" fill="none" stroke="#39d98a" stroke-width="2" stroke-dasharray="5 4" stroke-linejoin="round"/>'
    +'<polyline points="'+avgLine+'" fill="none" stroke="#ff7a2e" stroke-width="2.5" stroke-linejoin="round"/>'
    +dots+labels+'</svg>';
}

var maps = {};  // brandKey -> {map, layer}
function buildBrand(brand){
  var kws = Object.keys(DATA[brand]);
  if(!kws.length) return;
  var key = brand.replace(/[^a-z0-9]/gi,'');
  var state = { kw: kws[0], runIdx: 0, compare: false };

  var card = document.createElement('section'); card.className='card';
  var center = CENTERS[brand] || DATA[brand][kws[0]] && (function(){var r=DATA[brand][kws[0]];var f=r[Object.keys(r)[0]][0];return [f.lat,f.lng];})();
  card.innerHTML =
    '<div class="chead"><h2>'+brand+'</h2><span class="dom">local map-pack coverage</span></div>'
    +'<div class="bar"><span class="lbl">Keyword</span><span class="kwchips"></span>'
    +'<span class="runsel"><label class="cmp"><input type="checkbox" class="cmpbox"> vs prev</label>'
    +'<button class="prev">\\u2039</button><span class="rlabel"></span><button class="next">\\u203a</button></span></div>'
    +'<div class="kpis"><div class="kpi"><div class="v vAvg">—<span class="kd kdAvg"></span></div><div class="k">Avg map rank</div></div>'
    +'<div class="kpi"><div class="v vT3">—<span class="kd kdT3"></span></div><div class="k">% pins in top 3</div></div>'
    +'<div class="kpi"><div class="v vT10">—<span class="kd kdT10"></span></div><div class="k">% pins in top 10</div></div>'
    +'<div class="kpi"><div class="v vCov">—</div><div class="k">Grid points</div></div></div>'
    +'<div class="ghist"><div class="glbl">History<span><i class="dot" style="background:#ff7a2e;display:inline-block"></i>avg rank (lower = better)</span><span><i class="dot" style="background:#39d98a;display:inline-block"></i>% pins in top 3</span></div><div class="gsvg"></div></div>'
    +'<div class="map" id="map_'+key+'"></div>';
  document.getElementById('mount').appendChild(card);

  var chipWrap = card.querySelector('.kwchips');
  kws.forEach(function(kw){
    var b=document.createElement('button'); b.className='chip'+(kw===state.kw?' on':'');
    var lbl=document.createElement('span'); lbl.textContent=kw; b.appendChild(lbl);
    var x=document.createElement('span'); x.textContent='\\u2715'; x.className='chipx'; x.title='Stop tracking this keyword';
    x.onclick=function(ev){ ev.stopPropagation();
      if(!confirm('Stop tracking \\u201c'+kw+'\\u201d on the '+brand+' grid?')) return;
      manage({action:'remove_geogrid_keyword', brand:brand, keyword:kw},
             'Removed \\u2014 grid re-scans in ~2-5 min'); };
    b.appendChild(x);
    b.onclick=function(){ state.kw=kw; state.runIdx=0; chipWrap.querySelectorAll('.chip').forEach(function(z){z.classList.remove('on');}); b.classList.add('on'); draw(); };
    chipWrap.appendChild(b);
  });
  var add=document.createElement('button'); add.className='chip'; add.textContent='\\uff0b keyword'; add.title='Add a keyword to this grid';
  add.onclick=function(){ openModal(brand); };
  chipWrap.appendChild(add);

  var map = L.map('map_'+key, {zoomControl:true, attributionControl:true}).setView(center, 11);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',{
    maxZoom:20, subdomains:'abcd', attribution:'&copy; OpenStreetMap &copy; CARTO'}).addTo(map);
  map.getPane('tilePane').classList.add('tilepane');
  var layer = L.layerGroup().addTo(map);

  card.querySelector('.prev').onclick=function(){ var runs=Object.keys(DATA[brand][state.kw]); if(state.runIdx<runs.length-1){state.runIdx++;draw();} };
  card.querySelector('.next').onclick=function(){ if(state.runIdx>0){state.runIdx--;draw();} };
  card.querySelector('.cmpbox').onchange=function(){ state.compare=this.checked; draw(); };

  function draw(){
    var runsMap=DATA[brand][state.kw]||{};
    var runs=Object.keys(runsMap).sort();       // oldest..newest
    runs.reverse();                              // newest first -> idx 0 = latest
    if(!runs.length){
      layer.clearLayers();
      card.querySelector('.vAvg').childNodes[0].textContent='—';
      card.querySelector('.vT3').childNodes[0].textContent='—';
      card.querySelector('.vT10').childNodes[0].textContent='—';
      card.querySelector('.vCov').textContent='—';
      ['.kdAvg','.kdT3','.kdT10'].forEach(function(s){var e=card.querySelector(s);if(e){e.textContent='';e.classList.remove('up','down');}});
      card.querySelector('.rlabel').textContent='first scan in progress…';
      card.querySelector('.prev').disabled=true; card.querySelector('.next').disabled=true;
      var g=card.querySelector('.gsvg'); if(g) g.innerHTML='<div class="gempty">"'+state.kw+'" was just added. Its first grid scan is running now — pins and history appear here within a few minutes (the page auto-refreshes).</div>';
      return;
    }
    if(state.runIdx>runs.length-1) state.runIdx=runs.length-1;
    var run=runs[state.runIdx];
    var pts=runsMap[run];
    var prevRun = runs[state.runIdx+1];
    var prevPts = prevRun ? runsMap[prevRun] : null;
    var prevByPt = {};
    if(prevPts){ prevPts.forEach(function(p){ prevByPt[p.lat.toFixed(4)+','+p.lng.toFixed(4)]=p.rank; }); }

    layer.clearLayers();
    var sum=0,ranked=0,t3=0,t10=0;
    pts.forEach(function(p){
      var r=p.rank, col=pinColor(r);
      if(r!==null&&r!==undefined){ sum+=r; ranked++; if(r<=3)t3++; if(r<=10)t10++; }
      var deltaHtml='';
      if(state.compare&&prevPts){
        var pr=prevByPt[p.lat.toFixed(4)+','+p.lng.toFixed(4)];
        if(pr!==undefined){
          var cur=(r===null||r===undefined)?99:r, old=(pr===null||pr===undefined)?99:pr;
          if(cur<old) deltaHtml='<span class="delta" style="background:#39d98a;color:#06110b">\\u25b2</span>';
          else if(cur>old) deltaHtml='<span class="delta" style="background:#ff5c5c;color:#fff">\\u25bc</span>';
        }
      }
      var icon=L.divIcon({className:'', html:'<div class="gpin" style="width:30px;height:30px;position:relative;background:'+col+'">'+pinText(r)+deltaHtml+'</div>', iconSize:[30,30], iconAnchor:[15,15]});
      var pop='<b>'+(r===null||r===undefined?'Not in pack':'Rank #'+r)+'</b><br>'+p.lat.toFixed(4)+', '+p.lng.toFixed(4);
      if(p.top3&&p.top3.length){
        pop+='<br><span style="font-size:10px;letter-spacing:.5px;text-transform:uppercase;color:#888">Top 3 here</span>';
        p.top3.forEach(function(c){ pop+='<br>'+c.r+'. '+c.t.replace(/</g,'&lt;'); });
      }
      L.marker([p.lat,p.lng],{icon:icon}).addTo(layer).bindPopup(pop);
    });
    var n=pts.length;
    card.querySelector('.vAvg').childNodes[0].textContent = ranked?(sum/ranked).toFixed(1):'—';
    card.querySelector('.vT3').childNodes[0].textContent = n?Math.round(t3/n*100)+'%':'—';
    card.querySelector('.vT10').childNodes[0].textContent = n?Math.round(t10/n*100)+'%':'—';
    card.querySelector('.vCov').textContent = commas(n);
    // improvement vs the previous run: for rank, lower is better; for %, higher is better
    var ps = prevPts ? runStats(prevPts) : null;
    var curAvg = ranked? sum/ranked : null;
    setKd(card, '.kdAvg', (ps && ps.avg!==null && curAvg!==null) ? ps.avg-curAvg : null, function(d){return d.toFixed(1);});
    setKd(card, '.kdT3',  ps && n ? (t3/n*100)-ps.t3 : null, function(d){return Math.round(d)+'pp';});
    setKd(card, '.kdT10', ps && n ? (t10/n*100)-ps.t10 : null, function(d){return Math.round(d)+'pp';});
    renderTrend(card, runsMap);
    var d=new Date(run.replace(' ','T'));
    card.querySelector('.rlabel').textContent = run+'  (run '+(runs.length-state.runIdx)+'/'+runs.length+')';
    card.querySelector('.prev').disabled = state.runIdx>=runs.length-1;
    card.querySelector('.next').disabled = state.runIdx<=0;
    card.querySelector('.cmpbox').disabled = !prevPts;
  }
  draw();
}

var brands=Object.keys(DATA);
if(!brands.length){ document.getElementById('mount').innerHTML='<div class="card"><div class="empty">No grids configured yet. Click \\u201c\\u2699 Set up grid\\u201d to pick a brand, drop a center point and add keywords \\u2014 the first scan runs within ~5 minutes.</div></div>'; }
else { brands.forEach(buildBrand); }

// ---- grid setup modal ----
var mSel={brand:null, size:7};
var modal=document.getElementById('ggModal');
function openModal(brand){
  var wrap=document.getElementById('ggBrand'); wrap.innerHTML='';
  Object.keys(BRANDCFG).forEach(function(b){
    var btn=document.createElement('button'); btn.textContent=b+(BRANDCFG[b]?' \\u2713':'');
    btn.onclick=function(){ mSel.brand=b; wrap.querySelectorAll('button').forEach(function(z){z.classList.remove('on');}); btn.classList.add('on'); prefill(b); };
    wrap.appendChild(btn);
    if(b===brand){ btn.click(); }
  });
  if(!brand){ var first=wrap.querySelector('button'); if(first) first.click(); }
  modal.classList.add('open');
}
function prefill(b){
  var gg=BRANDCFG[b];
  document.getElementById('ggCenter').value = gg&&gg.center ? gg.center[0]+', '+gg.center[1] : '';
  document.getElementById('ggSpacing').value = gg&&gg.spacing_miles ? gg.spacing_miles : 3.5;
  document.getElementById('ggKws').value = gg&&gg.keywords ? gg.keywords.join('\\n') : '';
  mSel.size = gg&&gg.grid ? gg.grid : 7;
  document.querySelectorAll('#ggSize button').forEach(function(z){ z.classList.toggle('on', +z.dataset.v===mSel.size); });
  document.getElementById('ggRemove').style.display = gg ? '' : 'none';
}
document.querySelectorAll('#ggSize button').forEach(function(z){
  z.onclick=function(){ mSel.size=+z.dataset.v; document.querySelectorAll('#ggSize button').forEach(function(y){y.classList.remove('on');}); z.classList.add('on'); };
});
document.getElementById('cfgbtn').onclick=function(){ openModal(null); };
modal.addEventListener('click',function(e){ if(e.target===modal||e.target.hasAttribute('data-close')) modal.classList.remove('open'); });
document.getElementById('ggGo').onclick=function(){
  var m=(document.getElementById('ggCenter').value||'').split(',');
  var lat=parseFloat(m[0]), lng=parseFloat(m[1]);
  var kws=document.getElementById('ggKws').value.split('\\n').map(function(s){return s.trim();}).filter(Boolean).slice(0,5);
  if(!mSel.brand) return toast('Pick a brand');
  if(!isFinite(lat)||!isFinite(lng)) return toast('Center must be \\u201clat, lng\\u201d');
  if(!kws.length) return toast('Add at least one keyword');
  var pulls=mSel.size*mSel.size*kws.length;
  manage({action:'set_geogrid', brand:mSel.brand, center:[lat,lng], grid:mSel.size,
          spacing_miles:parseFloat(document.getElementById('ggSpacing').value)||3.5, keywords:kws},
         'Grid saved \\u2014 first scan ('+pulls+' points, ~$'+(pulls*0.002).toFixed(2)+') starts in ~2-5 min')
    .then(function(ok){ if(ok) modal.classList.remove('open'); });
};
document.getElementById('ggRemove').onclick=function(){
  if(!mSel.brand||!confirm('Remove the '+mSel.brand+' grid? History stays in the database.')) return;
  manage({action:'remove_geogrid', brand:mSel.brand}, 'Grid removed')
    .then(function(ok){ if(ok) modal.classList.remove('open'); });
};
</script>"""
    body_end = body_end.replace("__PAYLOAD__", payload)
    html = seo_shell.page(
        active="map-grid",
        title_html="Map <span>Grid</span>",
        content=content,
        updated=now,
        right_meta="Generated: " + now,
        refresh_tool="map-grid",
        extra_css=EXTRA_CSS,
        head_extra='<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">',
        body_end=body_end)
    OUT_HTML.write_text(html)
    print(f"Report -> {OUT_HTML}", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "both"
    if cmd in ("track", "both"):
        track()
    if cmd in ("render", "both"):
        render()
