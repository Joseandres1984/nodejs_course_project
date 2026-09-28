import app from "./live_truth_worker.js";

const MOBILE_LAYOUT_STYLE = `<style id="lumenMobileLayoutFix">
html,body{max-width:100%;overflow-x:hidden}
.wrap,.page,.section,.grid,.card{min-width:0}
@media(max-width:760px){
  .wrap{width:100%;max-width:100%;padding:12px!important}
  .tabs{
    display:grid!important;
    grid-template-columns:repeat(2,minmax(0,1fr))!important;
    gap:8px!important;
    width:100%!important;
    margin:0!important;
    padding:12px 0!important;
    overflow:visible!important;
    position:static!important;
    background:transparent!important;
  }
  .tabs .tab{
    width:100%!important;
    min-width:0!important;
    max-width:100%!important;
    white-space:normal!important;
    overflow-wrap:anywhere!important;
    word-break:normal!important;
    text-align:center!important;
    line-height:1.15!important;
    padding:10px 8px!important;
  }
  .page,.page.active,.section,.card{width:100%;max-width:100%;min-width:0}
  .card{overflow:hidden!important}
  .post{
    display:grid!important;
    grid-template-columns:minmax(0,1fr)!important;
    width:100%!important;
    max-width:100%!important;
    min-width:0!important;
    overflow:hidden!important;
  }
  .post>*{min-width:0!important;max-width:100%!important}
  .post img{
    display:block!important;
    width:min(100%,520px)!important;
    max-width:100%!important;
    height:auto!important;
    aspect-ratio:auto!important;
    object-fit:contain!important;
    margin:0 auto!important;
  }
  .post pre,.post p,.post div{
    max-width:100%!important;
    overflow-wrap:anywhere!important;
    word-break:break-word!important;
  }
  .post pre{white-space:pre-wrap!important;overflow:auto!important}
  .toplinks{max-width:100%!important}
  table{max-width:none}
  .ntTable,.ctTable,.lumenExpTable{max-width:100%;overflow-x:auto!important;-webkit-overflow-scrolling:touch}
}
@media(max-width:430px){
  .tabs{grid-template-columns:repeat(2,minmax(0,1fr))!important}
  .tabs .tab{font-size:12px!important;padding:9px 6px!important}
  .post img{width:100%!important}
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
    if (!html.includes('id="lumenMobileLayoutFix"')) {
      html = html.replace("</head>", `${MOBILE_LAYOUT_STYLE}</head>`);
    }
    const headers = new Headers(response.headers);
    headers.delete("content-length");
    headers.set("cache-control", "no-store");
    headers.set("x-lumen-mobile-layout", "grid-tabs-contained-media-v1");
    return new Response(html, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};
