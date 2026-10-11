#!/usr/bin/env python3
"""Read exact Mercado Pago production checkout URL securely, without creating any payment."""
import json,os,secrets,subprocess,sys,time,urllib.error,urllib.request,urllib.parse,re
account=os.environ["CLOUDFLARE_ACCOUNT_ID"];token=os.environ["CLOUDFLARE_API_TOKEN"]
base="https://api.cloudflare.com/client/v4/accounts/"+account+"/workers/scripts/calculafacil-pro-fulfillment/secrets"
worker="https://calculafacil-pro-fulfillment.lumen-b2b.workers.dev"
key=secrets.token_hex(48)
def cf(method,url,payload=None):
    headers={"Authorization":"Bearer "+token,"Accept":"application/json"}
    if payload is not None:headers["Content-Type"]="application/json"
    req=urllib.request.Request(url,headers=headers,method=method,
        data=json.dumps(payload).encode() if payload is not None else None)
    try:
        with urllib.request.urlopen(req,timeout=20) as res:
            data=res.read()
            return res.status,json.loads(data) if data else {}
    except urllib.error.HTTPError as exc:return exc.code,{}
def probe(secret=None):
    cfg='url = "'+worker+'/__internal/get-production-checkout"\nrequest = "POST"\n'
    if secret:cfg+='header = "X-LUMEN-PREFERENCE-AUDIT-KEY: '+secret+'"\n'
    p=subprocess.run(["curl","--silent","--show-error","--max-time","17",
        "--max-redirs","0","--config","-","--write-out","\\n%{http_code}"],
        input=cfg,text=True,capture_output=True,timeout=20)
    if p.returncode!=0 or "\n" not in p.stdout:return "network_failed",{}
    body,status=p.stdout.rsplit("\n",1)
    try:data=json.loads(body)
    except ValueError:data={}
    return status.strip(),data
status,_=probe()
if status!="404":sys.exit("PRODUCTION_LINK_AUDIT_NOT_PRIVATELY_PROTECTED")
status,created=cf("PUT",base,{"name":"PREFERENCE_AUDIT_KEY","text":key,"type":"secret_text"})
if status not in (200,201) or not created.get("success"):
    sys.exit("PRODUCTION_LINK_AUDIT_KEY_NOT_INSTALLED")
try:
    outcome=None
    for _ in range(12):
        status,outcome=probe(key)
        if status=="404":time.sleep(2);continue
        break
    if status!="200" or outcome.get("ok") is not True:
        reason=str(outcome.get("error") or "unknown")
        sys.exit("MP_PRODUCTION_LINK_NOT_VALIDATED_"+re.sub("[^a-z0-9_]","",reason)[:48])
    official=str(outcome.get("checkoutUrl") or "")
    parsed=urllib.parse.urlparse(official)
    id=str(outcome.get("preferenceId") or "")
    if id!="59348768-483e73d1-8b3f-450c-a610-b7ce39d70da9" or \
       parsed.scheme!="https" or parsed.hostname!="www.mercadopago.com.ar" or \
       outcome.get("vendorVerified") is not True or \
       outcome.get("amountVerified") is not True or \
       outcome.get("returnVerified") is not True or \
       outcome.get("paid") is not False or \
       outcome.get("deliveryEnabled") is not False:
        sys.exit("MP_PRODUCTION_LINK_REDIRECT_NOT_MATCHING_VERIFIED_PREFERENCE")
    print("VERIFIED_OFFICIAL_PRODUCTION_LINK="+official)
    print("VERIFIED_PRODUCTION_PREFERENCE="+id)
    print("VERIFIED_ACCOUNT_AND_AMOUNT=YES")
    print("REAL_PAYMENT_CREATED=NO")
    print("PUBLIC_CHECKOUT_ENABLED=NO")
finally:
    status,_=cf("DELETE",base+"/PREFERENCE_AUDIT_KEY")
    if status not in (200,204):sys.exit("PRODUCTION_LINK_AUDIT_KEY_NOT_CLEANED")
    print("AUDIT_SECRET_REMOVED")
status,_=probe()
if status!="404":sys.exit("PRODUCTION_LINK_AUDIT_ROUTE_STILL_EXPOSED")
