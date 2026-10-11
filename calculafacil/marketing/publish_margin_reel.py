"""Publish exactly one organic CalculaFácil educational Reel via existing Instagram Login.

No ads, DMs, bulk messaging, purchases or binding terms. Repeated runs detect the
immutable marker in the authorized account's remote feed and must not repost.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE="https://graph.instagram.com/v26.0"
ID="17841427692864676"
USERNAME="lumen.b2b"
ASSET="https://calculafacil.lumen-b2b.workers.dev/reels/precios-margen-2026.mp4"
KEY="CFPRO_MARGIN_REEL_OCT26"
PRO="https://calculafacil.lumen-b2b.workers.dev/pro.html"
CAPTION=(
    "Ojo con este error al poner precios en tu emprendimiento.\n\n"
    "Si un producto cuesta $10.000 y lo vendés a $13.000, el RECARGO es 30%, "
    "pero el MARGEN sobre el precio de venta es 23,08%.\n\n"
    "¿Por qué importa? Porque todavía tenés que contemplar tus gastos, comisiones "
    "e impuestos antes de saber cuánto ganás realmente.\n\n"
    "En CalculaFácil tenés 5 calculadoras gratis para probar tus números. "
    "Y si necesitás trabajar con varios artículos, proyecciones y promociones, "
    "conocé nuestro Kit Excel PRO con 7 hojas editables.\n\n"
    "Precio Kit PRO: AR$ 9.900 · pago único · sin suscripción.\n"
    "Web: calculafacil.lumen-b2b.workers.dev/pro.html\n"
    "Si querés aprender a poner precios con más criterio, escribinos por DM.\n\n"
    "#EmprendedoresArgentina #PrecioDeVenta #MargenDeGanancia #Excel "
    "#CalculaFacilPRO #NegociosArgentina #LumenB2B #"+KEY
)

def request(path,token,data=None):
    headers={"Authorization":"Bearer "+token,"Accept":"application/json"}
    content=None
    method="GET"
    if data is not None:
        method="POST"
        content=urllib.parse.urlencode({**data,"access_token":token}).encode()
        headers["Content-Type"]="application/x-www-form-urlencoded"
    req=urllib.request.Request(BASE+path,method=method,headers=headers,data=content)
    try:
        with urllib.request.urlopen(req,timeout=30) as r:
            return r.status,json.load(r)
    except urllib.error.HTTPError as exc:
        raise RuntimeError("instagram_http_"+str(exc.code)) from None
    except (urllib.error.URLError,TimeoutError):
        raise RuntimeError("instagram_network_unavailable") from None

def check_media():
    req=urllib.request.Request(ASSET+"?campaign="+KEY,method="GET",
      headers={"User-Agent":"LUMEN-Instagram-Organic-Reels/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=25) as res:
            mime=str(res.headers.get("content-type") or "").split(";")[0].lower()
            head=res.read(40)
            length=int(res.headers.get("content-length") or 0)
            if res.status!=200 or mime!="video/mp4" or head[4:8]!=b"ftyp":
                raise RuntimeError("reel_video_not_available_from_public_domain")
            if length>0 and not (25000<length<10000000):
                raise RuntimeError("reel_video_unexpected_size")
    except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError):
        raise RuntimeError("reel_video_network_unavailable") from None
    print("REEL_PUBLIC_MP4_MEDIA_READY")

def recent(token):
    status,body=request("/me/media?fields=id%2Ccaption%2Cpermalink%2Ctimestamp&limit=100",token)
    if status!=200 or not isinstance(body.get("data"),list):
        raise RuntimeError("instagram_recent_media_not_available")
    return body["data"]

def previous_post(rows):
    return next((x for x in rows if KEY in str(x.get("caption") or "")),None)

def check_identity(token):
    status,me=request("/me?fields=user_id%2Cid%2Cusername",token)
    if status!=200 or str(me.get("user_id") or me.get("id"))!=ID or me.get("username")!=USERNAME:
        raise RuntimeError("wrong_instagram_account")
    print("VERIFIED_INSTAGRAM_ACCOUNT="+USERNAME)

def wait_processing(container,token):
    for i in range(32):
        status,row=request("/"+urllib.parse.quote(container,safe="")+"?fields=status_code%2Cstatus",token)
        if status!=200:raise RuntimeError("instagram_reel_status_not_readable")
        code=str(row.get("status_code") or "").upper()
        if code=="FINISHED":return
        if code in ("ERROR","EXPIRED"):
            raise RuntimeError("instagram_reel_processing_"+code.lower())
        time.sleep(3)
    raise RuntimeError("instagram_reel_processing_timeout")

def confirm(postid,token):
    status,row=request("/"+urllib.parse.quote(postid,safe="")+"?fields=id%2Ccaption%2Cpermalink",token)
    if status!=200 or str(row.get("id") or "")!=postid or KEY not in str(row.get("caption") or ""):
        raise RuntimeError("instagram_reel_post_receipt_not_verified")
    link=str(row.get("permalink") or "")
    parsed=urllib.parse.urlparse(link)
    if parsed.scheme!="https" or parsed.hostname not in ("www.instagram.com","instagram.com"):
        raise RuntimeError("instagram_reel_permalink_invalid")
    return link

def main():
    if "--self-test" in sys.argv:
        assert KEY in CAPTION and "23,08%" in CAPTION and "30%" in CAPTION
        assert "AR$ 9.900" in CAPTION and PRO.startswith("https://")
        assert previous_post([{"caption":CAPTION}]) is not None
        assert previous_post([{"caption":"another post"}]) is None
        print("REEL_ORGANIC_MARKETING_OFFLINE_TESTS_PASSED")
        return
    if os.getenv("LUMEN_IG_REEL_ONE_TIME_AUTHORIZATION")!="organic_margin_education_20261011":
        raise RuntimeError("one_time_reel_not_authorized")
    token=os.getenv("LUMEN_INSTAGRAM_ACCESS_TOKEN","").strip()
    if len(token)<30:raise RuntimeError("instagram_publisher_secret_missing")
    check_media()
    check_identity(token)
    existing=previous_post(recent(token))
    if existing:
        print("CALCULAFACIL_EDUCATIONAL_REEL_ALREADY_PUBLISHED")
        print("NEW_POSTS_CREATED=0")
        print("POST_URL="+str(existing.get("permalink") or "unknown"))
        return
    print("CALCULAFACIL_ORGANIC_REEL_CREATING_NO_AD_SPEND")
    status,container=request("/"+ID+"/media",token,{
        "media_type":"REELS",
        "video_url":ASSET,
        "caption":CAPTION,
        "share_to_feed":"true"
    })
    identifier=str(container.get("id") or "")
    if status not in (200,201) or not identifier.isdecimal():
        raise RuntimeError("instagram_reel_container_not_created")
    wait_processing(identifier,token)
    if previous_post(recent(token)):
        raise RuntimeError("duplicate_reel_detected_before_publish")
    status,posted=request("/"+ID+"/media_publish",token,{"creation_id":identifier})
    pid=str(posted.get("id") or "")
    if status not in (200,201) or not pid.isdecimal():
        raise RuntimeError("instagram_reel_publish_receipt_missing")
    url=confirm(pid,token)
    print("CALCULAFACIL_EDUCATIONAL_REEL_PUBLISHED_AND_VERIFIED")
    print("VERIFIED_POST_URL="+url)
    print("VERIFIED_INSTAGRAM_MEDIA_ID="+pid)
    print("PAID_AD_SPEND_ARS=0")
    print("REAL_SALES_NOT_CLAIMED")

if __name__=="__main__":
    try:main()
    except Exception as e:
        print("CALCULAFACIL_REEL_PUBLISH_FAILED="+type(e).__name__+":"+str(e)[:110])
        sys.exit(1)
