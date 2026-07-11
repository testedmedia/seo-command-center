#!/usr/bin/env python3
"""Renders the /research page — in-UI keyword research.

Static shell page; all the work happens client-side against the /research
Pages Function (live DataForSEO proxy) and /manage (add-to-tracking queue).
No API cost to render. Usage: seo-research-page.py
"""
import json
import pathlib
import datetime
import config
import shell as seo_shell

KEYWORDS = config.KEYWORDS
OUT_HTML = config.DATA / "research.html"

EXTRA_CSS = """
.panel{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px;margin-bottom:16px}
.seg{display:inline-flex;background:#000;border:1px solid var(--line);border-radius:100px;overflow:hidden}
.seg button{background:none;border:none;color:var(--mut);padding:8px 16px;font-size:12.5px;cursor:pointer;font-family:'Plus Jakarta Sans';font-weight:700}
.seg button.on{background:rgba(255,122,46,.14);color:var(--gold)}
.frow{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-start;margin-top:14px}
.frow textarea,.frow input[type=text]{flex:1;min-width:260px;background:#000;border:1px solid var(--line2);color:var(--ink);border-radius:12px;padding:11px 14px;font-size:14px;font-family:'Inter';resize:vertical}
.frow textarea:focus,.frow input:focus{outline:none;border-color:var(--gold)}
.gobtn{background:var(--grad);border:none;color:#fff;border-radius:100px;padding:12px 24px;font-family:'Plus Jakarta Sans';font-weight:700;font-size:14px;cursor:pointer}
.gobtn:disabled{opacity:.5;cursor:default}
.hint{color:var(--mut);font-size:11.5px;margin-top:8px;line-height:1.6}
.resbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:13px 18px;border-bottom:1px solid var(--line)}
.resbar .cnt{font-family:'Plus Jakarta Sans';font-weight:700;font-size:13.5px}
.resbar .cost{color:var(--mut);font-size:11.5px}
.trackbtn{margin-left:auto;background:var(--grad);border:none;color:#fff;border-radius:100px;padding:9px 18px;font-family:'Plus Jakarta Sans';font-weight:700;font-size:13px;cursor:pointer}
.trackbtn:disabled{opacity:.4;cursor:default}
table{min-width:760px}
td.ck,th.ck{width:36px;text-align:center}
td.ck input,th.ck input{accent-color:var(--gold);width:15px;height:15px;cursor:pointer}
.comp{font-size:11px;text-transform:uppercase;letter-spacing:.4px}
.comp.LOW{color:var(--up)}.comp.MEDIUM{color:var(--gold)}.comp.HIGH{color:var(--down)}
.already{color:var(--mut);font-size:10.5px;border:1px solid var(--line);border-radius:100px;padding:1px 7px;margin-left:7px}
#spin{display:none;width:16px;height:16px;border:2px solid rgba(255,122,46,.3);border-top-color:var(--gold);border-radius:50%;animation:sp 1s linear infinite;vertical-align:-3px;margin-left:8px}
@keyframes sp{to{transform:rotate(360deg)}}
"""

_JS = """
var BRANDS = __BRANDS__;
var TRACKED = __TRACKED__;
var sel = {brand: Object.keys(BRANDS)[0], mode: 'seeds', tier: 'target'};
var results = [];
function el(id){return document.getElementById(id);}
function toast(msg){ var t=el('toast'); t.textContent=msg; t.style.display='block'; clearTimeout(t._h); t._h=setTimeout(function(){t.style.display='none';},6000); }

// brand chips
(function(){
  var wrap=el('rBrand');
  Object.keys(BRANDS).forEach(function(b,i){
    var btn=document.createElement('button'); btn.textContent=b; if(i===0)btn.classList.add('on');
    btn.onclick=function(){ sel.brand=b; wrap.querySelectorAll('button').forEach(function(z){z.classList.remove('on');}); btn.classList.add('on'); };
    wrap.appendChild(btn);
  });
})();
// mode seg
document.querySelectorAll('#rMode button').forEach(function(b){
  b.onclick=function(){ sel.mode=b.dataset.v;
    document.querySelectorAll('#rMode button').forEach(function(z){z.classList.remove('on');}); b.classList.add('on');
    el('seedBox').style.display = sel.mode==='seeds'?'':'none';
    el('compBox').style.display = sel.mode==='competitor'?'':'none'; };
});
// tier chips
document.querySelectorAll('#rTier button').forEach(function(b){
  b.onclick=function(){ sel.tier=b.dataset.v;
    document.querySelectorAll('#rTier button').forEach(function(z){z.classList.remove('on');}); b.classList.add('on'); };
});

el('runbtn').onclick=function(){
  var body={mode:sel.mode,
            location_code:(BRANDS[sel.brand]||{}).location_code||2840,
            language_code:(BRANDS[sel.brand]||{}).language_code||'en'};
  if(sel.mode==='seeds'){
    body.seeds=el('seeds').value.split('\\n').map(function(s){return s.trim();}).filter(Boolean).slice(0,5);
    if(!body.seeds.length) return toast('Type at least one seed keyword');
  } else {
    body.domain=el('compdom').value.trim();
    if(!body.domain) return toast('Type a competitor domain');
  }
  var b=el('runbtn'); b.disabled=true; el('spin').style.display='inline-block';
  fetch('/research',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(function(r){return r.json();})
    .then(function(d){
      b.disabled=false; el('spin').style.display='none';
      if(!d.ok){ toast('Failed: '+(d.error||'unknown')); return; }
      results=d.rows||[];
      renderRows(d);
    })
    .catch(function(){ b.disabled=false; el('spin').style.display='none'; toast('Request failed — try again'); });
};

function tracked(kw){
  var set=TRACKED[sel.brand]||[];
  return set.indexOf(kw.toLowerCase())>-1;
}
function renderRows(d){
  el('rescard').style.display='';
  el('rescnt').textContent=results.length.toLocaleString('en-US')+' keywords';
  el('rescost').textContent='this pull cost $'+(d.cost||0).toFixed(4)+' · '+d.used+'/'+d.limit+' research runs today';
  var tb=el('resbody'); tb.innerHTML='';
  results.forEach(function(r,i){
    var tr=document.createElement('tr');
    var isTracked=tracked(r.kw);
    tr.innerHTML='<td class="ck"><input type="checkbox" data-i="'+i+'"'+(isTracked?' disabled':'')+'></td>'
      +'<td class="kw">'+r.kw.replace(/</g,'&lt;')+(isTracked?'<span class="already">tracked</span>':'')+'</td>'
      +'<td class="num vol">'+(r.vol||0).toLocaleString('en-US')+'</td>'
      +'<td class="num">'+(r.cpc?'$'+r.cpc.toFixed(2):'—')+'</td>'
      +'<td><span class="comp '+(r.comp||'')+'">'+(r.comp||'—')+'</span></td>'
      +'<td class="num">'+(r.rank?'#'+r.rank:'—')+'</td>';
    tb.appendChild(tr);
  });
  updateTrackBtn();
  tb.querySelectorAll('input').forEach(function(c){ c.onchange=updateTrackBtn; });
}
function selectedKws(){
  return [...document.querySelectorAll('#resbody input:checked')].map(function(c){ return results[+c.dataset.i].kw; });
}
function updateTrackBtn(){
  var n=selectedKws().length;
  el('trackbtn').textContent='Track '+n+' selected → '+sel.brand;
  el('trackbtn').disabled=!n;
}
el('selall').onchange=function(){
  var on=this.checked;
  document.querySelectorAll('#resbody input:not(:disabled)').forEach(function(c){c.checked=on;});
  updateTrackBtn();
};
el('trackbtn').onclick=function(){
  var kws=selectedKws().slice(0,50);
  if(!kws.length) return;
  var b=el('trackbtn'); b.disabled=true;
  fetch('/manage',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:'add_keywords',brand:sel.brand,tier:sel.tier,keywords:kws})})
    .then(function(r){return r.json();})
    .then(function(d){
      if(d.ok){ toast('✓ '+kws.length+' keywords queued for '+sel.brand+' ('+sel.tier+') — tracking in ~2-5 min');
        (TRACKED[sel.brand]=TRACKED[sel.brand]||[]).push.apply(TRACKED[sel.brand],kws.map(function(k){return k.toLowerCase();}));
        renderRows({cost:0,used:'-',limit:'-'});
        el('rescost').textContent='keywords queued — check the Rankings page after the next update';
      } else { toast('Failed: '+(d.error||'unknown')); b.disabled=false; }
    })
    .catch(function(){ toast('Request failed'); b.disabled=false; });
};
"""


def render():
    cfg = json.loads(KEYWORDS.read_text())
    brands = {b: {"domain": m["domain"],
                  "location_code": m.get("location_code", 2840),
                  "language_code": m.get("language_code", "en")}
              for b, m in cfg["brands"].items()}
    # everything each brand already tracks (pinned tiers + seeds), for "tracked" badges
    tracked = {}
    for b, m in cfg["brands"].items():
        kws = set()
        for f in ("brand_keywords", "local_keywords", "target_keywords", "seed_keywords"):
            kws.update(x.lower() for x in m.get(f, []))
        tracked[b] = sorted(kws)

    content = """
<div class="panel">
  <div class="mlbl" style="margin-top:0">Find keywords for</div>
  <div class="chips" id="rBrand"></div>
  <div class="frow" style="align-items:center">
    <div class="seg" id="rMode">
      <button data-v="seeds" class="on">From seed keywords</button>
      <button data-v="competitor">Steal from a competitor</button>
    </div>
  </div>
  <div id="seedBox">
    <div class="frow">
      <textarea id="seeds" rows="3" placeholder="ai receptionist&#10;ai answering service"></textarea>
    </div>
    <div class="hint">Up to 5 seeds, one per line. Pulls up to 40 related keywords per seed with live volume + CPC (Google, the brand's country). ~$0.01 per seed.</div>
  </div>
  <div id="compBox" style="display:none">
    <div class="frow">
      <input type="text" id="compdom" placeholder="competitor.com">
    </div>
    <div class="hint">Pulls the top 200 keywords the competitor ranks for, sorted by volume — their organic playbook. ~$0.02 per pull.</div>
  </div>
  <div class="frow">
    <button class="gobtn" id="runbtn">Run research<span id="spin"></span></button>
  </div>
  <div class="mlbl">Add selected keywords as</div>
  <div class="chips" id="rTier">
    <button data-v="target" class="on">Target</button><button data-v="seed">Research seed</button>
    <button data-v="local">Local</button><button data-v="brand">Brand</button>
  </div>
</div>
<section class="card" id="rescard" style="display:none">
  <div class="resbar">
    <span class="cnt" id="rescnt"></span>
    <span class="cost" id="rescost"></span>
    <button class="trackbtn" id="trackbtn" disabled>Track 0 selected</button>
  </div>
  <div class="scroll gscroll" style="max-height:600px">
    <table><thead><tr>
      <th class="ck"><input type="checkbox" id="selall" title="Select all"></th>
      <th>Keyword</th><th style="text-align:right">Volume</th><th style="text-align:right">CPC</th><th>Competition</th><th style="text-align:right">Their rank</th>
    </tr></thead><tbody id="resbody"></tbody></table>
  </div>
</section>
<div id="toast"></div>"""

    body_end = ("<script>" + _JS
                .replace("__BRANDS__", json.dumps(brands))
                .replace("__TRACKED__", json.dumps(tracked)) + "</script>")

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    html = seo_shell.page(
        active="research",
        title_html="Keyword <span>Research</span>",
        content=content,
        updated=now,
        right_meta="live DataForSEO · results in seconds",
        extra_css=EXTRA_CSS,
        body_end=body_end,
        page_title="Keyword Research · " + config.brand_name())
    OUT_HTML.write_text(html)
    print(f"Report -> {OUT_HTML}")


if __name__ == "__main__":
    render()
