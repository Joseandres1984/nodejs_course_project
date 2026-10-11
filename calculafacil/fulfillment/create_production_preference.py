#!/usr/bin/env python3
"""Create an unpublished production Checkout Pro preference, without charging anyone.

Runs only under GitHub Actions with preexisting Cloudflare deploy credentials.
Uses a one-time random administrator secret installed on the Worker and then removed.
No Mercado Pago token or customer data leaves Cloudflare.
"""
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ACCOUNT = os.environ["CLOUDFLARE_ACCOUNT_ID"]
TOKEN = os.environ["CLOUDFLARE_API_TOKEN"]
BASE = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/workers/scripts/calculafacil-pro-fulfillment/secrets"
HOST = "https://calculafacil-pro-fulfillment.lumen-b2b.workers.dev"
SECRET_NAME = "PREFERENCE_SETUP_KEY"
SECRET = secrets.token_hex(48)

def api(method, url, body=None):
    headers = {"Authorization": "Bearer "+TOKEN, "Accept": "application/json"}
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body).encode()
    request=urllib.request.Request(url, data=payload, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        return error.code, {}

def invoke(path, admin=None):
    config='url = "'+HOST+path+'"\nrequest = "POST"\n'
    if admin: config+='header = "X-LUMEN-PREFERENCE-SETUP-KEY: '+admin+'"\n'
    result = subprocess.run(
        ["curl","--silent","--show-error","--max-time","18",
         "--max-redirs","0","--config","-","--write-out","\\n%{http_code}"],
        input=config, text=True, capture_output=True, timeout=22
    )
    if result.returncode or "\n" not in result.stdout:
        return "network_error",{}
    body,status=result.stdout.rsplit("\n",1)
    try: parsed=json.loads(body)
    except ValueError: parsed={}
    return status.strip(),parsed

status,secret_list=api("GET",BASE)
if status!=200 or not secret_list.get("success"):
    sys.exit("CLOUDFLARE_SECRET_AUDIT_UNAVAILABLE")
existing={s.get("name") for s in secret_list.get("result",[])}
if not {"MP_ACCESS_TOKEN","DOWNLOAD_SIGNING_KEY"}.issubset(existing):
    sys.exit("PRODUCTION_CREDENTIALS_NOT_READY")
# A one-time setup call must be impossible without the private secret.
unprotected,_=invoke("/__internal/create-production-preference")
if unprotected!="404":
    sys.exit("UNAUTHENTICATED_PRODUCTION_PREFERENCE_ROUTE_NOT_BLOCKED")
status,created=api("PUT",BASE,{"name":SECRET_NAME,"text":SECRET,"type":"secret_text"})
if status not in (200,201) or not created.get("success"):
    sys.exit("PRODUCTION_SETUP_KEY_INSTALL_FAILED")
try:
    result=None
    for _ in range(12):
        status,result=invoke("/__internal/create-production-preference",SECRET)
        if status=="404":
            time.sleep(2)
            continue
        break
    if status!="200":
        detail=str(result.get("error") or "unknown")
        safe=re.sub("[^a-z0-9_]", "", detail)[:65]
        sys.exit("PRODUCTION_PREFERENCE_CREATION_FAILED_HTTP_"+status+"_"+safe)
    if result.get("ok") is not True or result.get("sellerVerified") is not True or \
       result.get("productVerified") is not True or result.get("backUrlsVerified") is not True or \
       result.get("paymentCharged") is not False or result.get("commercialDeliveryEnabled") is not False:
        sys.exit("PRODUCTION_PREFERENCE_NOT_VALIDATED")
    pref=str(result.get("preferenceId",""))
    url=result.get("checkoutUrl")
    if not re.fullmatch("[a-zA-Z0-9_-]{5,160}",pref):
        sys.exit("PRODUCTION_PREFERENCE_ID_UNEXPECTED")
    parsed=urllib.parse.urlparse(url or "")
    if parsed.scheme!="https" or parsed.hostname not in (
       "www.mercadopago.com.ar","mercadopago.com.ar",
       "www.mercadopago.com","mercadopago.com"):
        sys.exit("PRODUCTION_LINK_ORIGIN_NOT_VERIFIED")
    print("PRODUCTION_CHECKOUT_PREFERENCE_CREATED=YES")
    print("PRODUCTION_PREFERENCE_ID="+pref)
    print("PRODUCTION_CHECKOUT_HOST="+parsed.hostname)
    print("PRODUCTION_MERCHANT_VERIFIED=YES")
    print("PRODUCTION_ITEM_AND_AMOUNT_VERIFIED=ARS_9900")
    print("PRODUCTION_BUYER_RETURN_URL_VERIFIED=YES")
    print("PRODUCTION_PURCHASES_CHARGED=NO")
    print("PRODUCTION_COMMERCE_REMAINS_DISABLED=YES")
finally:
    status,_=api("DELETE",BASE+"/"+SECRET_NAME)
    if status not in (200,204):
        sys.exit("PRODUCTION_SETUP_KEY_CLEANUP_NOT_VERIFIED")
    print("TEMPORARY_PRODUCTION_PREFERENCE_SETUP_SECRET_REMOVED")
# No private admin setup key should remain usable after creation.
after,_=invoke("/__internal/create-production-preference")
if after!="404":
    sys.exit("PRODUCTION_ADMIN_SETUP_ROUTE_STILL_ACCESSIBLE")
