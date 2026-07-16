#!/usr/bin/env python3
"""Renders the /explorer page — Ahrefs-style Site Explorer for any domain or URL.

Static shell page; all analysis happens client-side against the /explorer
Pages Function (live DataForSEO proxy, 24h KV cache). A full all-tabs run
of one domain costs about $0.20 in DataForSEO credits; cached re-checks are
free. No API cost to render this page. Usage: explorer_page.py
"""
import json
import datetime
import config
import shell as seo_shell

OUT_HTML = config.DATA / "explorer.html"

EXTRA_CSS = r""".panel{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px;margin-bottom:16px}
.frow{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.frow input[type=text]{flex:1;min-width:260px;background:#000;border:1px solid var(--line2);color:var(--ink);border-radius:12px;padding:11px 14px;font-size:14px;font-family:'Inter'}
.frow input:focus{outline:none;border-color:var(--gold)}
.gobtn{background:var(--grad);border:none;color:#fff;border-radius:100px;padding:12px 24px;font-family:'Plus Jakarta Sans';font-weight:700;font-size:14px;cursor:pointer}
.gobtn:disabled{opacity:.5;cursor:default}
.hint{color:var(--mut);font-size:11.5px;margin-top:8px;line-height:1.6}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-bottom:16px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:15px 17px}
.kpi .kv{font-family:'Plus Jakarta Sans';font-weight:800;font-size:22px}
.kpi .kl{font-size:10.5px;text-transform:uppercase;letter-spacing:.6px;color:var(--mut);margin-top:3px}
.kpi.gold .kv{color:var(--gold)}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.tabs button{background:var(--card);border:1px solid var(--line);color:var(--ink2);border-radius:100px;padding:8px 17px;font-size:13px;cursor:pointer;font-family:'Plus Jakarta Sans';font-weight:700}
.tabs button.on{background:rgba(255,122,46,.14);border-color:rgba(255,122,46,.45);color:var(--gold)}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;margin-bottom:16px;overflow:hidden}
.resbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:13px 18px;border-bottom:1px solid var(--line)}
.resbar .cnt{font-family:'Plus Jakarta Sans';font-weight:700;font-size:13.5px}
.resbar .cost{color:var(--mut);font-size:11.5px}
.resbar input[type=search]{margin-left:auto;background:#000;border:1px solid var(--line2);color:var(--ink);border-radius:100px;padding:7px 14px;font-size:12.5px;min-width:180px}
.resbar input:focus{outline:none;border-color:var(--gold)}
.csv{background:none;border:1px solid rgba(255,122,46,.4);color:var(--gold);border-radius:100px;padding:7px 14px;font-size:12px;cursor:pointer;font-family:'Plus Jakarta Sans';font-weight:700}
.scroll{overflow-x:auto}.gscroll{max-height:640px;overflow-y:auto}
table{width:100%;border-collapse:collapse;min-width:720px}
th{text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.55px;color:var(--mut);padding:9px 13px;border-bottom:1px solid var(--line);white-space:nowrap;background:var(--card);position:sticky;top:0;z-index:1;cursor:pointer;user-select:none}
th.sorted{color:var(--gold)}
td{padding:8px 13px;border-bottom:1px solid rgba(255,255,255,.06);font-size:13px;color:var(--ink2);vertical-align:top}
td.kw{color:var(--ink);word-break:break-all}
td a{color:var(--ink);text-decoration:none;word-break:break-all}
td a:hover{color:var(--gold)}
tr:last-child td{border-bottom:none}
.num{text-align:right;font-variant-numeric:tabular-nums}.vol{font-weight:600;color:var(--ink)}
.pillb{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.4px;border-radius:100px;padding:2px 9px;border:1px solid var(--line);white-space:nowrap}
.pillb.crit{color:var(--down);border-color:rgba(255,92,92,.4)}
.pillb.info{color:var(--blue);border-color:rgba(106,176,255,.4)}
#spin{display:none;width:16px;height:16px;border:2px solid rgba(255,122,46,.3);border-top-color:var(--gold);border-radius:50%;animation:sp 1s linear infinite;vertical-align:-3px;margin-left:8px}
@keyframes sp{to{transform:rotate(360deg)}}
#toast{position:fixed;bottom:26px;left:50%;transform:translateX(-50%);background:#16161c;border:1px solid rgba(255,122,46,.4);color:var(--ink);border-radius:100px;padding:11px 22px;font-size:13.5px;z-index:3100;display:none;box-shadow:0 12px 40px rgba(0,0,0,.6)}
.tabwrap{display:flex;gap:20px;flex-wrap:wrap;margin-bottom:14px}
.tabgroup{display:flex;flex-direction:column;gap:6px}
.tglbl{font-size:9.5px;text-transform:uppercase;letter-spacing:.7px;color:var(--mut);padding-left:4px}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:0}
.chips2{display:flex;gap:7px;flex-wrap:wrap;align-items:center}
.chips2 button{background:#000;border:1px solid var(--line);color:var(--ink2);border-radius:100px;padding:5px 13px;font-size:12px;cursor:pointer;font-family:'Plus Jakarta Sans';font-weight:600}
.chips2 button.on{background:rgba(255,122,46,.14);border-color:rgba(255,122,46,.45);color:var(--gold)}
.mv{display:inline-block;font-size:10px;font-weight:700;border-radius:100px;padding:1px 7px;margin-left:7px}
.mv.new{color:var(--blue);border:1px solid rgba(106,176,255,.4)}
.mv.up{color:var(--up);border:1px solid rgba(57,217,138,.4)}
.mv.down{color:var(--down);border:1px solid rgba(255,92,92,.4)}
.mv.broken{color:var(--down);border:1px solid rgba(255,92,92,.4)}
.mv.lost{color:var(--mut);border:1px solid var(--line)}
.dfl{color:var(--up);font-weight:700;font-size:11px}
.nfl{color:var(--mut);font-size:11px}
.pagemode{display:none;margin:0 0 14px;padding:10px 16px;border:1px solid rgba(106,176,255,.4);border-radius:12px;color:var(--blue);font-size:12.5px;background:rgba(106,176,255,.06)}
.chartrow{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;margin-bottom:16px}
.chartcard{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px 18px}
.chartcard h3{font-family:'Plus Jakarta Sans';font-size:12.5px;font-weight:700;margin-bottom:2px}
.chartcard .csub{font-size:10.5px;color:var(--mut);margin-bottom:10px}
.chartcard svg{width:100%;height:130px;display:block}
.leg{display:flex;gap:14px;flex-wrap:wrap;margin-top:8px}
.leg span{font-size:10.5px;color:var(--mut);display:flex;align-items:center;gap:5px}
.leg i{width:10px;height:10px;border-radius:3px;display:inline-block}
@media(max-width:920px){.app{grid-template-columns:1fr}aside{position:static;height:auto;flex-direction:row;flex-wrap:wrap;align-items:center}.nav{flex-direction:row;flex-wrap:wrap}.navitem{width:auto}.sfoot{display:none}}
"""

_CONTENT = r"""<div class="panel">
  <div class="frow">
    <input type="text" id="dom" placeholder="any-domain.com or a full page URL" autofocus>
    <button class="gobtn" id="runbtn">Analyze<span id="spin"></span></button>
  </div>
  <div class="hint" id="hintline">Overview and history charts run first. Then click through the tabs, each pulls live on first view and caches for 24 hours. Full deep analysis of one domain ≈ $0.20.</div>
</div>

<div class="pagemode" id="pagemode">Page Inspect mode: analyzing a single URL. Backlinks, anchors and referring domains are scoped to this page; keywords show what this page ranks for.</div>
<div class="kpis" id="kpis" style="display:none"></div>
<div class="chartrow" id="charts" style="display:none"></div>
<div class="tabwrap" id="tabs" style="display:none">
  <div class="tabgroup"><div class="tglbl">Backlink profile</div>
    <div class="tabs">
      <button data-t="backlinks">Backlinks</button>
      <button data-t="anchors">Anchors</button>
      <button data-t="refdomains">Ref. Domains</button>
      <button data-t="linkpages">Pages by Links</button>
      <button data-t="broken">Broken Pages</button>
    </div></div>
  <div class="tabgroup"><div class="tglbl">Organic search</div>
    <div class="tabs">
      <button data-t="keywords">Keywords</button>
      <button data-t="pages" class="on">Top Pages</button>
      <button data-t="competitors">Competitors</button>
      <button data-t="contentgap">Content Gap</button>
    </div></div>
  <div class="tabgroup"><div class="tglbl">Paid search</div>
    <div class="tabs"><button data-t="paidkeywords">Paid Keywords</button></div></div>
  <div class="tabgroup"><div class="tglbl">Structure</div>
    <div class="tabs"><button data-t="structure">Site Structure</button></div></div>
</div>
<section class="card" id="rescard" style="display:none">
  <div class="resbar">
    <span class="cnt" id="rescnt"></span>
    <span class="cost" id="rescost"></span>
    <span class="chips2" id="subchips"></span>
    <input type="search" id="q" placeholder="Filter rows...">
    <button class="csv" id="csv">CSV</button>
  </div>
  <div class="scroll gscroll"><table><thead id="thead"></thead><tbody id="tbody"></tbody></table></div>
</section>
<div id="toast"></div>"""

_JS = r"""var BRANDS = __BRANDS__;
var COLS = {
  pages: [["url","Page",0],["traffic","Traffic /mo",1],["keywords","Keywords",1],["top3","Top 3",1]],
  keywords: [["kw","Keyword",0],["rank","Pos",1],["move","Change",0],["vol","Volume",1],["traffic","Traffic",1],["cpc","CPC",1],["url","URL",0]],
  paidkeywords: [["kw","Keyword",0],["rank","Ad pos",1],["vol","Volume",1],["cpc","CPC",1],["url","Landing page",0]],
  backlinks: [["url_from","Linking page",0],["anchor","Anchor",0],["domain_rank","Domain rank",1],["dofollow","Follow",0],["flag","Status",0],["spam","Spam",1],["first_seen","First seen",0]],
  anchors: [["anchor","Anchor text",0],["ref_domains","Ref. domains",1],["backlinks","Backlinks",1],["spam","Spam",1],["first_seen","First seen",0]],
  linkpages: [["url","Page",0],["ref_domains","Ref. domains",1],["backlinks","Backlinks",1],["rank","Page rank",1],["first_seen","First seen",0]],
  broken: [["url","Broken page",0],["status","HTTP",1],["ref_domains","Ref. domains",1],["backlinks","Backlinks",1]],
  refdomains: [["domain","Referring domain",0],["rank","Domain rank",1],["backlinks","Links to target",1],["first_seen","First seen",0]],
  competitors: [["domain","Competing domain",0],["shared_kw","Shared keywords",1],["avg_pos","Their avg pos",1],["traffic","Their traffic",1],["keywords","Their keywords",1]],
  contentgap: [["kw","Keyword they rank for",0],["their_rank","Their pos",1],["vol","Volume",1],["traffic","Their traffic",1],["cpc","CPC",1],["url","Their page",0]],
  structure: [["path","Section",0],["pages","Pages",1],["traffic","Traffic /mo",1],["keywords","Keywords",1]]
};
var state = { target:'', tab:'pages', rows:[], sortK:null, sortDir:-1, data:{}, sub:{keywords:'all', backlinks:'all', contentgap:''} };
function el(id){return document.getElementById(id);}
function fmt(n){return (n==null?0:n).toLocaleString('en-US');}
function toast(msg){ var t=el('toast'); t.textContent=msg; t.style.display='block'; clearTimeout(t._h); t._h=setTimeout(function(){t.style.display='none';},6000); }

function post(payload){
  payload.target=state.target;
  return fetch('/explorer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}).then(function(r){return r.json();});
}

el('runbtn').onclick=function(){
  var dom=el('dom').value.trim();
  if(!dom) return toast('Type a domain or URL');
  state.target=dom; state.data={}; state.sub={keywords:'all', backlinks:'all', contentgap:''};
  var b=el('runbtn'); b.disabled=true; el('spin').style.display='inline-block';
  post({tab:'overview'}).then(function(d){
    b.disabled=false; el('spin').style.display='none';
    if(!d.ok){ toast('Failed: '+(d.error||'unknown')); return; }
    el('pagemode').style.display=d.isPage?'block':'none';
    renderOverview(d);
    el('tabs').style.display='flex';
    loadCharts();
    setTab('pages');
  }).catch(function(){ b.disabled=false; el('spin').style.display='none'; toast('Request failed — try again'); });
};
el('dom').addEventListener('keydown',function(e){ if(e.key==='Enter') el('runbtn').click(); });

function renderOverview(d){
  var o=d.overview||{};
  var k=el('kpis'); k.style.display='grid';
  var cells=[
    ['DR (Ahrefs)', o.dr!=null?o.dr:'—','gold'],
    ['Organic traffic /mo', fmt(o.traffic)],
    ['Traffic value /mo', '$'+fmt(o.traffic_value)],
    ['Ranking keywords', fmt(o.keywords)],
    ['Page 1 rankings', fmt(o.page1)],
    ['Backlinks', o.backlinks_error?'—':fmt(o.backlinks)],
    ['Ref. domains', o.backlinks_error?'—':fmt(o.ref_domains)],
    ['Broken pages', o.backlinks_error?'—':fmt(o.broken_pages)],
    ['Paid traffic /mo', fmt(o.paid_traffic)],
    ['Spam score', o.backlinks_error?'—':(o.spam_score||0)]
  ];
  k.innerHTML=cells.map(function(c){
    return '<div class="kpi'+(c[2]?' '+c[2]:'')+'"><div class="kv">'+c[1]+'</div><div class="kl">'+c[0]+'</div></div>';
  }).join('');
  if(o.balance!=null) el('hintline').textContent='DataForSEO balance: $'+o.balance.toFixed(2)+' · a full domain analysis (all tabs) ≈ $0.20 · results cache 24h so re-checks are free.';
  if(o.backlinks_error) toast('Backlinks data: '+o.backlinks_error);
}

// ---- history charts (inline SVG, no libs) ----
function svgPath(vals,W,H,pad){
  var mx=Math.max.apply(null,vals.concat([1]));
  var pts=vals.map(function(v,i){
    return [pad+i*(W-2*pad)/Math.max(vals.length-1,1), H-pad-(v/mx)*(H-2*pad)];
  });
  return {mx:mx, line:pts.map(function(p,i){return (i?'L':'M')+p[0].toFixed(1)+','+p[1].toFixed(1);}).join(' '),
          area:'M'+pad+','+(H-pad)+' '+pts.map(function(p){return 'L'+p[0].toFixed(1)+','+p[1].toFixed(1);}).join(' ')+' L'+(W-pad)+','+(H-pad)+' Z'};
}
function chartCard(title,sub,svg,legend){
  return '<div class="chartcard"><h3>'+title+'</h3><div class="csub">'+sub+'</div>'+svg
    +(legend?'<div class="leg">'+legend+'</div>':'')+'</div>';
}
function loadCharts(){
  post({tab:'history'}).then(function(d){
    if(!d.ok){ el('charts').style.display='none'; return; }
    var W=560,H=130,P=6, html='';
    var org=d.organic||[], lnk=d.links||[];
    if(org.length>1){
      var t=svgPath(org.map(function(r){return r.traffic;}),W,H,P);
      html+=chartCard('Organic traffic','monthly est. visits · peak '+fmt(t.mx),
        '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none"><path d="'+t.area+'" fill="rgba(255,122,46,.14)"/><path d="'+t.line+'" fill="none" stroke="#ff7a2e" stroke-width="2"/></svg>',
        '<span><i style="background:#ff7a2e"></i>'+org[0].ym+' → '+org[org.length-1].ym+'</span>');
      var k1=svgPath(org.map(function(r){return r.top3;}),W,H,P);
      var k2=svgPath(org.map(function(r){return r.top3+r.pos4_10;}),W,H,P);
      var k3=svgPath(org.map(function(r){return r.top3+r.pos4_10+r.pos11_50;}),W,H,P);
      html+=chartCard('Ranking keywords by position','top 3 / page 1 / top 50 · peak '+fmt(k3.mx),
        '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none"><path d="'+k3.area+'" fill="rgba(106,176,255,.12)"/><path d="'+k2.area+'" fill="rgba(106,176,255,.2)"/><path d="'+k1.area+'" fill="rgba(57,217,138,.28)"/><path d="'+k3.line+'" fill="none" stroke="#6ab0ff" stroke-width="1.6"/></svg>',
        '<span><i style="background:rgba(57,217,138,.7)"></i>top 3</span><span><i style="background:rgba(106,176,255,.55)"></i>pos 4-10</span><span><i style="background:rgba(106,176,255,.25)"></i>pos 11-50</span>');
    }
    if(lnk.length>1){
      var r1=svgPath(lnk.map(function(r){return r.ref_domains;}),W,H,P);
      var bw=(W-2*P)/lnk.length;
      var mxNL=Math.max.apply(null,lnk.map(function(r){return Math.max(r.new_links,r.lost_links);}).concat([1]));
      var bars=lnk.map(function(r,i){
        var x=P+i*bw+bw*0.15, w=bw*0.3;
        var hN=(r.new_links/mxNL)*(H*0.4), hL=(r.lost_links/mxNL)*(H*0.4);
        return '<rect x="'+x.toFixed(1)+'" y="'+(H-P-hN).toFixed(1)+'" width="'+w.toFixed(1)+'" height="'+hN.toFixed(1)+'" fill="rgba(57,217,138,.5)"/>'
             + '<rect x="'+(x+w).toFixed(1)+'" y="'+(H-P-hL).toFixed(1)+'" width="'+w.toFixed(1)+'" height="'+hL.toFixed(1)+'" fill="rgba(255,92,92,.5)"/>';
      }).join('');
      html+=chartCard('Referring domains + new/lost links','12 months · '+fmt(lnk[lnk.length-1].ref_domains)+' ref. domains now',
        '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+bars+'<path d="'+r1.line+'" fill="none" stroke="#ff7a2e" stroke-width="2"/></svg>',
        '<span><i style="background:#ff7a2e"></i>ref. domains</span><span><i style="background:rgba(57,217,138,.7)"></i>new links</span><span><i style="background:rgba(255,92,92,.7)"></i>lost links</span>');
    }
    if(html){ el('charts').innerHTML=html; el('charts').style.display='grid'; }
    else el('charts').style.display='none';
  }).catch(function(){ el('charts').style.display='none'; });
}

// ---- tabs ----
document.querySelectorAll('#tabs .tabs button').forEach(function(b){
  b.onclick=function(){ setTab(b.dataset.t); };
});
function setTab(tab){
  document.querySelectorAll('#tabs .tabs button').forEach(function(z){z.classList.toggle('on',z.dataset.t===tab);});
  state.tab=tab; state.sortK=null;
  renderSubchips();
  loadTab();
}
function cacheId(){
  var tab=state.tab;
  if(tab==='keywords') return 'keywords'; // movement chips filter client-side
  if(tab==='backlinks') return 'backlinks:'+state.sub.backlinks;
  if(tab==='contentgap') return 'contentgap:'+state.sub.contentgap;
  return tab;
}
function renderSubchips(){
  var s=el('subchips'); s.innerHTML='';
  if(state.tab==='keywords'){
    ['all','new','up','down'].forEach(function(m){
      var b=document.createElement('button'); b.textContent=m==='all'?'All':m.charAt(0).toUpperCase()+m.slice(1);
      if(state.sub.keywords===m)b.classList.add('on');
      b.onclick=function(){ state.sub.keywords=m; renderSubchips(); drawBody(); };
      s.appendChild(b);
    });
  } else if(state.tab==='backlinks'){
    [['all','All'],['dofollow','Dofollow'],['new','New 90d'],['broken','Broken']].forEach(function(m){
      var b=document.createElement('button'); b.textContent=m[1];
      if(state.sub.backlinks===m[0])b.classList.add('on');
      b.onclick=function(){ state.sub.backlinks=m[0]; renderSubchips(); loadTab(); };
      s.appendChild(b);
    });
  } else if(state.tab==='contentgap'){
    Object.keys(BRANDS).forEach(function(name){
      var b=document.createElement('button'); b.textContent='vs '+name;
      if(state.sub.contentgap===BRANDS[name])b.classList.add('on');
      b.onclick=function(){ state.sub.contentgap=BRANDS[name]; renderSubchips(); loadTab(); };
      s.appendChild(b);
    });
  }
}
function loadTab(){
  var tab=state.tab, id=cacheId();
  el('rescard').style.display='';
  if(tab==='contentgap' && !state.sub.contentgap){
    el('rescnt').textContent='Pick a brand to compare against'; el('rescost').textContent='';
    el('thead').innerHTML=''; el('tbody').innerHTML=''; return;
  }
  if(tab==='structure'){ loadStructure(); return; }
  if(state.data[id]){ renderRows(state.data[id]); return; }
  el('rescnt').textContent='Loading...'; el('rescost').textContent='';
  el('thead').innerHTML=''; el('tbody').innerHTML='';
  var payload={tab:tab};
  if(tab==='backlinks') payload.mode=state.sub.backlinks;
  if(tab==='contentgap') payload.vs=state.sub.contentgap;
  post(payload).then(function(d){
    if(!d.ok){ el('rescnt').textContent='Failed'; toast('Failed: '+(d.error||'unknown')); return; }
    state.data[id]=d; if(state.tab===tab) renderRows(d);
  }).catch(function(){ el('rescnt').textContent='Failed'; toast('Request failed'); });
}
function loadStructure(){
  var pagesData=state.data['pages'];
  if(!pagesData){
    el('rescnt').textContent='Loading...'; el('thead').innerHTML=''; el('tbody').innerHTML='';
    post({tab:'pages'}).then(function(d){
      if(!d.ok){ el('rescnt').textContent='Failed'; toast('Failed: '+(d.error||'unknown')); return; }
      state.data['pages']=d; if(state.tab==='structure') loadStructure();
    }).catch(function(){ el('rescnt').textContent='Failed'; });
    return;
  }
  var agg={};
  (pagesData.rows||[]).forEach(function(r){
    var m=(r.url||'').match(/^https?:\/\/[^/]+(\/[^/]*)/);
    var seg=m?(m[1].length>1?m[1]+(r.url.indexOf(m[1]+'/')>-1?'/…':''):'/'):'/';
    var key=m&&m[1].length>1?m[1].replace(/\/$/,'')+'/':'/ (root pages)';
    (agg[key]=agg[key]||{path:key,pages:0,traffic:0,keywords:0});
    agg[key].pages++; agg[key].traffic+=r.traffic||0; agg[key].keywords+=r.keywords||0;
  });
  var rows=Object.values(agg).sort(function(a,b){return b.traffic-a.traffic;});
  renderRows({rows:rows, cached:true, cost:0, used:'-', limit:'-', structureNote:true});
}

function renderRows(d){
  var cols=COLS[state.tab];
  state.rows=d.rows||[];
  el('rescard').style.display='';
  el('rescnt').textContent=fmt(state.rows.length)+' rows · '+state.target;
  el('rescost').textContent=d.structureNote?'computed free from Top Pages data'
    :(d.cached?'cached (free)':'live pull $'+(d.cost||0).toFixed(4)+' · '+d.used+' pulls today');
  el('thead').innerHTML='<tr>'+cols.map(function(c){
    return '<th data-k="'+c[0]+'"'+(c[2]?' style="text-align:right"':'')+'>'+c[1]+'</th>';
  }).join('')+'</tr>';
  el('thead').querySelectorAll('th').forEach(function(th){
    th.onclick=function(){
      var k=th.dataset.k;
      state.sortDir=(state.sortK===k)?-state.sortDir:-1; state.sortK=k;
      el('thead').querySelectorAll('th').forEach(function(z){z.classList.toggle('sorted',z===th);});
      drawBody();
    };
  });
  drawBody();
}

function drawBody(){
  var cols=COLS[state.tab];
  var q=el('q').value.toLowerCase();
  var rows=state.rows.filter(function(r){
    if(state.tab==='keywords' && state.sub.keywords!=='all' && r.move!==state.sub.keywords) return false;
    return !q || JSON.stringify(r).toLowerCase().indexOf(q)>-1;
  });
  if(state.sortK){
    var k=state.sortK, dir=state.sortDir;
    rows=rows.slice().sort(function(a,b){
      var x=a[k]==null?-1:a[k], y=b[k]==null?-1:b[k];
      return (x>y?1:x<y?-1:0)*dir;
    });
  }
  var dom=state.target.split('/')[0];
  el('tbody').innerHTML=rows.map(function(r){
    return '<tr>'+cols.map(function(c){
      var v=r[c[0]];
      if((c[0]==='url'||c[0]==='url_from')&&v){
        var href=/^https?:/.test(v)?v:'https://'+dom+v;
        return '<td class="kw"><a href="'+href.replace(/"/g,'&quot;')+'" target="_blank" rel="noopener">'+String(v).replace(/</g,'&lt;')+'</a></td>';
      }
      if(c[0]==='domain'&&v) return '<td class="kw"><a href="https://'+v+'" target="_blank" rel="noopener">'+v+'</a></td>';
      if(c[0]==='status') return '<td class="num"><span class="pillb crit">'+(v||'—')+'</span></td>';
      if(c[0]==='move') return '<td>'+(v?'<span class="mv '+v+'">'+v.toUpperCase()+(v!=='new'&&r.prev?' '+r.prev+'→'+r.rank:'')+'</span>':'')+'</td>';
      if(c[0]==='flag') return '<td>'+(v?'<span class="mv '+v+'">'+v.toUpperCase()+'</span>':'')+'</td>';
      if(c[0]==='dofollow') return '<td>'+(v?'<span class="dfl">follow</span>':'<span class="nfl">nofollow</span>')+'</td>';
      if(c[0]==='rank'&&(state.tab==='keywords'||state.tab==='paidkeywords')) return '<td class="num">'+(v?'#'+v:'—')+'</td>';
      if(c[0]==='their_rank') return '<td class="num">'+(v?'#'+v:'—')+'</td>';
      if(c[0]==='cpc') return '<td class="num">'+(v?'$'+v.toFixed(2):'—')+'</td>';
      if(c[0]==='avg_pos') return '<td class="num">'+(v||'—')+'</td>';
      if(c[2]) return '<td class="num vol">'+fmt(v)+'</td>';
      return '<td>'+String(v==null?'—':v).replace(/</g,'&lt;')+'</td>';
    }).join('')+'</tr>';
  }).join('');
}
el('q').oninput=drawBody;
el('csv').onclick=function(){
  var cols=COLS[state.tab];
  var lines=[cols.map(function(c){return c[1];}).join(',')].concat(state.rows.map(function(r){
    return cols.map(function(c){ var v=r[c[0]]; return '"'+String(v==null?'':v).replace(/"/g,'""')+'"'; }).join(',');
  }));
  var a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([lines.join('\n')],{type:'text/csv'}));
  a.download=state.target.replace(/[^a-z0-9.]+/g,'-')+'-'+state.tab+'.csv'; a.click();
};
"""


def render():
    kws = config.load_keywords()
    brands = {name: cfg["domain"] for name, cfg in kws.get("brands", {}).items()
              if isinstance(cfg, dict) and cfg.get("domain")}
    body_end = "<script>" + _JS.replace("__BRANDS__", json.dumps(brands)) + "</script>"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    html = seo_shell.page(
        active="explorer",
        title_html="Site <span>Explorer</span>",
        content=_CONTENT,
        updated=now,
        right_meta="any domain · live DataForSEO · Ahrefs-grade",
        extra_css=EXTRA_CSS,
        body_end=body_end,
        page_title="Site Explorer · " + config.brand_name())
    OUT_HTML.write_text(html)
    print(f"Report -> {OUT_HTML}")


if __name__ == "__main__":
    render()
