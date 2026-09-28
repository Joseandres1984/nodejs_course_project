import app from "./live_truth_worker.js";

const MOBILE_LAYOUT_STYLE = `<style id="lumenMobileLayoutFix">
html,body{width:100%;max-width:100%;overflow-x:hidden!important}
body *{min-width:0}
.wrap,.page,.page.active,.section,.grid,.card{max-width:100%;min-width:0}
img,svg,canvas,video{max-width:100%;height:auto}

@media(max-width:760px){
  html,body{overflow-x:hidden!important}
  .wrap{width:100%!important;max-width:100%!important;margin:0!important;padding:12px!important;overflow:hidden!important}
  .top{width:100%!important;max-width:100%!important;align-items:flex-start!important;flex-direction:column!important}
  .toplinks{width:100%!important;max-width:100%!important;justify-content:flex-start!important}

  nav.tabs,#tabs,.tabs{
    display:grid!important;
    grid-template-columns:repeat(2,minmax(0,1fr))!important;
    gap:8px!important;
    width:100%!important;
    max-width:100%!important;
    min-width:0!important;
    margin:0!important;
    padding:12px 0!important;
    overflow:visible!important;
    position:static!important;
    background:transparent!important;
    white-space:normal!important;
  }
  nav.tabs>button,#tabs>button,.tabs .tab,.tabs button{
    display:flex!important;
    align-items:center!important;
    justify-content:center!important;
    width:100%!important;
    max-width:100%!important;
    min-width:0!important;
    margin:0!important;
    white-space:normal!important;
    overflow:hidden!important;
    overflow-wrap:anywhere!important;
    word-break:normal!important;
    text-overflow:clip!important;
    text-align:center!important;
    line-height:1.15!important;
    padding:10px 7px!important;
  }

  .page,.page.active,.section,.card,.grid{width:100%!important;max-width:100%!important;min-width:0!important}
  .card{overflow:hidden!important}
  .g6,.g5,.g4,.g3,.g2,.ntGrid,.ntMoney,.ntModules,.ntSplit,.ntGuard{grid-template-columns:1fr!important}

  .post{
    display:grid!important;
    grid-template-columns:minmax(0,1fr)!important;
    width:100%!important;
    max-width:100%!important;
    min-width:0!important;
    gap:12px!important;
    overflow:hidden!important;
  }
  .post>*{width:100%!important;min-width:0!important;max-width:100%!important}
  .post img,.card img{
    display:block!important;
    width:100%!important;
    max-width:100%!important;
    height:auto!important;
    aspect-ratio:auto!important;
    object-fit:contain!important;
    margin:0 auto!important;
  }
  .post pre,.post p,.post div,.card p,.card div,.card h1,.card h2,.card h3{
    max-width:100%!important;
    overflow-wrap:anywhere!important;
    word-break:normal!important;
  }
  .post pre{white-space:pre-wrap!important;overflow:auto!important}

  table{width:max-content!important;min-width:100%!important;max-width:none!important}
  .ntTable,.ctTable,.lumenExpTable,.tableWrap,[class*="Table"]{max-width:100%!important;overflow-x:auto!important;-webkit-overflow-scrolling:touch}
}

@media(max-width:430px){
  nav.tabs,#tabs,.tabs{grid-template-columns:repeat(2,minmax(0,1fr))!important}
  nav.tabs>button,#tabs>button,.tabs .tab,.tabs button{font-size:12px!important;padding:9px 5px!important}
  .wrap{padding:10px!important}
  .card{padding:12px!important}
}
</style>`;

export default {
  async fetch(request, env, ctx) {
    const response = await app.fetch(request, env, ctx);
    const url = new URL(request.url);
    if (
      request.method !== "GET" ||
      !response.ok ||
      !["/", "/index.html", "/full"].includes(url.pathname) ||
      !String(response.headers.get("content-type") || "").includes("text/html")
    ) return response;

    let html = await response.text();
    html = html.replace(/<style id="lumenMobileLayoutFix">[\s\S]*?<\/style>/, "");
    html = html.replace("</head>", `${MOBILE_LAYOUT_STYLE}</head>`);

    const headers = new Headers(response.headers);
    headers.delete("content-length");
    headers.set("cache-control", "no-store, no-cache, must-revalidate");
    headers.set("pragma", "no-cache");
    headers.set("expires", "0");
    headers.set("x-lumen-mobile-layout", "strict-contained-grid-v2");
    return new Response(html, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};
