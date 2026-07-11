// Cookie-session auth gate — orange matrix login page, brandable via BRAND_NAME env
// ACCESS_KEY and AUTH_SALT come from the Pages project environment
// (worker.py deploy-config sets them from your .env — nothing hardcoded).

async function tokenFor(p, SALT) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(p + "|" + SALT));
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, "0")).join("");
}

const LOGIN_HTML = "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n<title>Sign in \u00b7 __BRANDNAME__</title>\n<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\"><link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>\n<link href=\"https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@600;700;800&family=Inter:wght@400;500;600&display=swap\" rel=\"stylesheet\">\n<style>\n:root{--bg:#000;--card:#0f0f14;--ink:#fff;--ink2:#b6b6bd;--mut:#76767f;--line:rgba(255,255,255,.13);--line2:rgba(255,255,255,.22);--gold:#ff7a2e;--grad:linear-gradient(180deg,#ff9142,#ff6a17);--ease:cubic-bezier(.22,1,.36,1)}\n*{box-sizing:border-box;margin:0;padding:0}\nhtml,body{height:100%}\nbody{background:var(--bg);color:var(--ink);font:15px/1.55 'Inter',-apple-system,sans-serif;display:flex;align-items:center;justify-content:center;padding:24px;position:relative;overflow:hidden}\n#mx{position:fixed;inset:0;z-index:0;opacity:.55}\n.scrim{position:fixed;inset:0;z-index:1;background:radial-gradient(ellipse at center,rgba(0,0,0,.72) 0%,rgba(0,0,0,.35) 60%,rgba(0,0,0,.15) 100%);pointer-events:none}\n.wrap{width:100%;max-width:400px;position:relative;z-index:2}\n.logo{display:flex;justify-content:center;margin-bottom:26px}\n.logo svg{height:32px;width:auto}.logo svg path{fill:#fff}\n.card{background:rgba(15,15,20,.92);backdrop-filter:blur(6px);border:1px solid var(--line);border-radius:18px;padding:34px 30px 30px;box-shadow:0 30px 80px rgba(0,0,0,.65)}\n.eyebrow{display:inline-flex;align-items:center;gap:8px;font-size:11px;letter-spacing:.8px;text-transform:uppercase;color:var(--ink2);border:1px solid var(--line2);border-radius:100px;padding:5px 13px;margin-bottom:16px}\n.dot{width:6px;height:6px;border-radius:50%;background:var(--gold);animation:pulse 1.8s var(--ease) infinite}\n@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}\nh1{font-family:'Plus Jakarta Sans';font-weight:800;font-size:23px;letter-spacing:-.2px}\nh1 span{color:var(--gold)}\n.sub{color:var(--mut);font-size:13.5px;margin:7px 0 24px}\nlabel{display:block;font-size:12px;font-weight:600;letter-spacing:.4px;text-transform:uppercase;color:var(--ink2);margin-bottom:8px}\ninput{width:100%;background:#000;border:1px solid var(--line2);color:var(--ink);border-radius:12px;padding:13px 16px;font-size:15px;font-family:'Inter';transition:border-color .25s var(--ease)}\ninput:focus{outline:none;border-color:var(--gold)}\nbutton{width:100%;margin-top:16px;background:var(--grad);border:none;color:#fff;border-radius:100px;padding:14px;font-family:'Plus Jakarta Sans';font-weight:700;font-size:15px;cursor:pointer;transition:transform .2s var(--ease),box-shadow .2s var(--ease)}\nbutton:hover{transform:translateY(-1px);box-shadow:0 10px 30px rgba(255,122,46,.35)}\n.err{display:__ERRDISP__;background:rgba(255,92,92,.09);border:1px solid rgba(255,92,92,.35);color:#ff8f8f;border-radius:12px;padding:10px 14px;font-size:13px;margin-bottom:16px}\n.foot{text-align:center;color:var(--mut);font-size:11.5px;margin-top:22px;letter-spacing:.3px}\n</style></head><body>\n<canvas id=\"mx\"></canvas><div class=\"scrim\"></div>\n<div class=\"wrap\">\n  <div class=\"logo\"><span style=\"font-family:'Plus Jakarta Sans',sans-serif;font-weight:800;font-size:22px;letter-spacing:1px;color:#fff\">__BRANDNAME__</span></div>\n  <div class=\"card\">\n    <div class=\"eyebrow\"><span class=\"dot\"></span>Self-hosted \u00b7 private</div>\n    <h1>Command <span>Center</span></h1>\n    <p class=\"sub\">Rankings, research, competitors, site health and local grids \u2014 enter your access key to continue.</p>\n    <div class=\"err\">Wrong access key. Try again.</div>\n    <form method=\"POST\" action=\"/login\">\n      <label for=\"password\">Access key</label>\n      <input id=\"password\" name=\"password\" type=\"password\" autocomplete=\"current-password\" autofocus required>\n      <button type=\"submit\">Sign in</button>\n    </form>\n  </div>\n  <div class=\"foot\">__BRANDNAME__ \u00b7 AUTHORIZED ACCESS ONLY</div>\n</div>\n<script>\n(function(){\n  var canvas=document.getElementById('mx'),ctx=canvas.getContext('2d');\n  function resize(){canvas.width=window.innerWidth;canvas.height=window.innerHeight}\n  resize();window.addEventListener('resize',resize);\n  var chars='\u30a2\u30a4\u30a6\u30a8\u30aa\u30ab\u30ad\u30af\u30b1\u30b3\u30b5\u30b7\u30b9\u30bb\u30bd\u30bf\u30c1\u30c4\u30c6\u30c8\u30ca\u30cb\u30cc\u30cd\u30ce\u30cf\u30d2\u30d5\u30d8\u30db\u30de\u30df\u30e0\u30e1\u30e2\u30e4\u30e6\u30e8\u30e9\u30ea\u30eb\u30ec\u30ed\u30ef\u30f2\u30f30123456789ABCDEF';\n  var fontSize=14,columns=Math.floor(canvas.width/fontSize),drops=Array(columns).fill(1);\n  function draw(){\n    ctx.fillStyle='rgba(0,0,0,0.05)';ctx.fillRect(0,0,canvas.width,canvas.height);\n    ctx.font=fontSize+'px monospace';\n    for(var i=0;i<drops.length;i++){\n      var ch=chars[Math.floor(Math.random()*chars.length)],x=i*fontSize,y=drops[i]*fontSize;\n      ctx.fillStyle=Math.random()>0.95?'#ffd9bf':'rgba(255,'+Math.floor(96+Math.random()*60)+',23,'+(0.55+Math.random()*0.4)+')';\n      ctx.fillText(ch,x,y);\n      if(y>canvas.height&&Math.random()>0.975){drops[i]=0}\n      drops[i]++;\n    }\n  }\n  setInterval(draw,40);\n})();\n</script>\n</body></html>";

function loginPage(withError, BRAND) {
  return LOGIN_HTML.replace("__ERRDISP__", withError ? "block" : "none").split("__BRANDNAME__").join(BRAND);
}

export async function onRequest(context) {
  const PASS = context.env.ACCESS_KEY;
  const SALT = context.env.AUTH_SALT || "seo-command-center";
  const BRAND = context.env.BRAND_NAME || "SEO Command Center";
  if (!PASS) return new Response("ACCESS_KEY not configured — run `python worker.py deploy-config`", { status: 500 });
  const req = context.request;
  const url = new URL(req.url);
  const expected = await tokenFor(PASS, SALT);
  const cookies = req.headers.get("Cookie") || "";
  const m = cookies.match(/rt_auth=([a-f0-9]{64})/);
  if (m && m[1] === expected) {
    if (url.pathname === "/login") {
      return new Response(null, { status: 302, headers: { Location: "/" } });
    }
    return context.next();
  }
  if (req.method === "POST" && url.pathname === "/login") {
    const form = await req.formData();
    if (form.get("password") === PASS) {
      return new Response(null, {
        status: 302,
        headers: {
          Location: "/",
          "Set-Cookie": "rt_auth=" + expected + "; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000",
        },
      });
    }
    return new Response(loginPage(true, BRAND), { status: 401, headers: { "Content-Type": "text/html;charset=utf-8" } });
  }
  return new Response(loginPage(false, BRAND), { status: 401, headers: { "Content-Type": "text/html;charset=utf-8" } });
}
