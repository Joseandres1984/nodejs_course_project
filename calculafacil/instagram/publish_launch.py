"""Publish exactly one user-authorized organic CalculaFácil PRO post to @lumen.b2b.

No ads, billing, bulk outreach, profile mutations, or recurring publication.
Fail closed before mutating provider state. Reruns check remote Instagram feed
for the immutable campaign marker; duplicate posts are prohibited.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from io import BytesIO

from PIL import Image

API="https://graph.instagram.com/v26.0"
EXPECTED_ID="17841427692864676"
EXPECTED_USERNAME="lumen.b2b"
SITE="https://calculafacil.lumen-b2b.workers.dev"
ASSET=SITE+"/instagram/calculafacil-pro-lanzamiento.jpg"
CHECKOUT=SITE+"/pro.html"
TRACKED=CHECKOUT+"?utm_source=instagram&utm_medium=organic&utm_campaign=lumen_b2b_calculafacil_pro_oct26"
MARKER="CALCULAFACIL_PRO_LUMEN_OCT2026"

CAPTION=(
    "¿Vendés, pero no sabés cuánto ganás realmente?\n\n"
    "LUMEN presenta CalculaFácil PRO: un Kit Excel editable para emprendedores y comercios.\n\n"
    "Incluye 7 hojas: precios y márgenes, proyección de 12 meses, punto de equilibrio, "
    "cuotas, promociones e instrucciones.\n\n"
    "Precio: AR$ 9.900. Pago único, sin suscripción.\n"
    "Comprás por Mercado Pago y descargás el archivo luego de verificar tu pago aprobado.\n\n"
    "Conocé el kit: calculafacil.lumen-b2b.workers.dev/pro.html\n"
    "Si tenés dudas, escribinos por mensaje directo.\n\n"
    "#CalculaFacilPRO #EmprendedoresArgentina #PlanillaExcel #PreciosDeVenta "
    "#MargenDeGanancia #Negocios #LumenB2B\n"
    "#"+MARKER
)

def _request(method,url,token,data=None):
    headers={"Authorization":"Bearer "+token,"Accept":"application/json",
             "User-Agent":"LUMEN-CalculaFacil-Organic-Launch/1.0"}
    payload=None
    if data is not None:
        payload=urllib.parse.urlencode({**data,"access_token":token}).encode("utf-8")
        headers["Content-Type"]="application/x-www-form-urlencoded"
    req=urllib.request.Request(url,method=method,headers=headers,data=payload)
    try:
        with urllib.request.urlopen(req,timeout=25) as response:
            return response.status,json.load(response)
    except urllib.error.HTTPError as ex:
        # Never log response bodies; they may contain provider-sensitive data.
        raise RuntimeError("instagram_http_"+str(ex.code)) from None
    except (urllib.error.URLError,TimeoutError):
        raise RuntimeError("instagram_provider_unreachable") from None

def _get_asset():
    req=urllib.request.Request(ASSET+"?campaign="+MARKER,
        headers={"Accept":"image/jpeg","User-Agent":"LUMEN-Public-Media-Check/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=25) as resp:
            mime=str(resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            raw=resp.read(1024*1024)
            if resp.status!=200 or mime!="image/jpeg":
                raise RuntimeError("marketing_visual_not_public_image")
    except urllib.error.HTTPError as ex:
        raise RuntimeError("marketing_visual_http_"+str(ex.code)) from None
    image=Image.open(BytesIO(raw))
    image.load()
    if image.size!=(1080,1350) or image.format!="JPEG" or len(raw)<30000:
        raise RuntimeError("marketing_visual_invalid_size_or_encoding")
    print("LIVE_INSTAGRAM_CAMPAIGN_IMAGE_OK_1080x1350")

def _recent(token):
    status,body=_request("GET",API+"/me/media?fields=id%2Ccaption%2Cpermalink%2Ctimestamp&limit=100",token)
    if status!=200 or not isinstance(body.get("data"),list):
        raise RuntimeError("instagram_recent_feed_unavailable")
    return body["data"]

def _published_before(posts):
    for row in posts:
        if MARKER in str(row.get("caption") or ""):
            return row
    return None

def _verify_account(token):
    status,account=_request("GET",API+"/me?fields=user_id%2Cid%2Cusername",token)
    ident=str(account.get("user_id") or account.get("id") or "")
    username=str(account.get("username") or "")
    if status!=200 or ident!=EXPECTED_ID or username!=EXPECTED_USERNAME:
        raise RuntimeError("wrong_instagram_account_or_missing_access")
    print("INSTAGRAM_ACCOUNT_VERIFIED=@"+username)

def _poll_ready(container,token):
    for attempt in range(24):
        _,status=_request("GET",API+"/"+urllib.parse.quote(container,safe="")+
            "?fields=status_code%2Cstatus",token)
        code=str(status.get("status_code") or "").upper()
        if code=="FINISHED":
            return
        if code in ("ERROR","EXPIRED"):
            raise RuntimeError("instagram_media_processing_"+code.lower())
        time.sleep(3)
    raise RuntimeError("instagram_media_processing_timeout")

def _published_details(post_id,token):
    _,body=_request("GET",API+"/"+urllib.parse.quote(post_id,safe="")+
        "?fields=id%2Cpermalink%2Ccaption",token)
    if str(body.get("id"))!=str(post_id) or MARKER not in str(body.get("caption") or ""):
        raise RuntimeError("instagram_post_detail_not_verified")
    link=body.get("permalink") or ""
    parsed=urllib.parse.urlparse(link)
    if parsed.scheme!="https" or parsed.hostname not in ("www.instagram.com","instagram.com"):
        raise RuntimeError("instagram_post_permalink_invalid")
    return link

def main():
    if len(sys.argv)>1 and sys.argv[1]=="--self-test":
        assert MARKER in CAPTION
        assert "AR$ 9.900" in CAPTION
        assert "7 hojas" in CAPTION
        assert "Mercado Pago" in CAPTION
        assert TRACKED.startswith(CHECKOUT)
        assert ASSET.startswith(SITE+"/instagram/")
        assert _published_before([{"caption":CAPTION,"permalink":"https://www.instagram.com/p/FAKE/"}])
        assert not _published_before([{"caption":"Another post"}])
        print("CAMPAIGN_SAFETY_OFFLINE_TESTS_PASSED")
        return
    if os.getenv("LUMEN_IG_ONE_TIME_CAMPAIGN_AUTHORIZATION")!="organic_calculafacil_pro_launch_20261011":
        raise RuntimeError("one_time_campaign_not_authorized")
    token=os.environ.get("LUMEN_INSTAGRAM_ACCESS_TOKEN","").strip()
    if len(token)<30:raise RuntimeError("instagram_token_missing")
    _get_asset()
    _verify_account(token)
    posts=_recent(token)
    previous=_published_before(posts)
    if previous:
        url=previous.get("permalink") or "not_available"
        print("INSTAGRAM_CALCULAFACIL_PRO_ALREADY_PUBLISHED")
        print("VERIFIED_POST_URL="+url)
        print("NEW_POSTS_CREATED=0")
        return
    print("INSTAGRAM_ORGANIC_SINGLE_POST_PUBLICATION_AUTHORIZED")
    status,created=_request("POST",API+"/"+EXPECTED_ID+"/media",token,
        {"image_url":ASSET,"caption":CAPTION})
    cid=str(created.get("id") or "")
    if status not in (200,201) or not cid.isdecimal():
        raise RuntimeError("instagram_media_container_not_confirmed")
    _poll_ready(cid,token)
    # Recheck feed immediately before publish to avoid creating duplicates.
    if _published_before(_recent(token)):
        raise RuntimeError("instagram_campaign_appeared_before_publish")
    status,published=_request("POST",API+"/"+EXPECTED_ID+"/media_publish",token,
        {"creation_id":cid})
    pid=str(published.get("id") or "")
    if status not in (200,201) or not pid.isdecimal():
        raise RuntimeError("instagram_media_publish_receipt_not_confirmed")
    permalink=_published_details(pid,token)
    print("INSTAGRAM_CAMPAIGN_PUBLISHED_AND_VERIFIED")
    print("VERIFIED_POST_URL="+permalink)
    print("VERIFIED_INSTAGRAM_MEDIA_ID="+pid)
    print("PAID_ADVERTISING_SPEND=0")
    print("REAL_SALES_SETTLEMENTS_NOT_VERIFIED_BY_THIS_WORKFLOW")

if __name__=="__main__":
    try:main()
    except Exception as ex:
        # Errors should never include secrets, payer data, or raw provider bodies.
        print("INSTAGRAM_LAUNCH_FAILED="+type(ex).__name__+":"+str(ex)[:110])
        raise SystemExit(1)
