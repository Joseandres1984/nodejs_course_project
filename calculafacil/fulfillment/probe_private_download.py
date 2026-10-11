#!/usr/bin/env python3
"""Verify an actual private XLSX HTTP download; no production checkout or logs of file contents."""
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

account=os.environ["CLOUDFLARE_ACCOUNT_ID"]
token=os.environ["CLOUDFLARE_API_TOKEN"]
base=f"https://api.cloudflare.com/client/v4/accounts/{account}/workers/scripts/calculafacil-pro-fulfillment/secrets"
endpoint="https://calculafacil-pro-fulfillment.lumen-b2b.workers.dev"
name="KIT_AUDIT_SECRET"
key=secrets.token_hex(48)

def cf(method,url,payload=None):
    headers={"Authorization":"Bearer "+token,"Accept":"application/json"}
    data=None
    if payload is not None:
        data=json.dumps(payload).encode()
        headers["Content-Type"]="application/json"
    req=urllib.request.Request(url,method=method,data=data,headers=headers)
    try:
        with urllib.request.urlopen(req,timeout=20) as response:
            raw=response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        return exc.code,{}

def curl(path,verb="GET",header=None,out=None):
    config=f'url = "{endpoint}{path}"\nrequest = "{verb}"\n'
    if header:
        config+='header = "X-LUMEN-KIT-AUDIT-KEY: '+header+'"\n'
    args=["curl","--silent","--show-error","--max-time","15","--max-redirs","0",
          "--config","-","--write-out","%{http_code}"]
    if out: args+=["--output",str(out)]
    else: args+=["--output","/dev/null"]
    result=subprocess.run(args,input=config,text=True,capture_output=True,timeout=18)
    return result.stdout.strip() if result.returncode==0 else "network_failure"

status,response=cf("PUT",base,{"name":name,"text":key,"type":"secret_text"})
if status not in (200,201) or not response.get("success"):
    sys.exit("PRIVATE_DIAGNOSTIC_SECRET_INSTALL_FAILED")
try:
    path="/__internal/transport-test-download"
    pre=curl(path,"POST")
    if pre!="404":sys.exit("PRIVATE_TRANSPORT_UNPROTECTED_OR_NOT_READY")
    blocked=curl("/download?payment_id=12345678&until=9999999999999&sig=invalid-signature","GET")
    if blocked!="503":sys.exit("PUBLIC_DOWNLOAD_IS_NOT_DISABLED")
    with tempfile.TemporaryDirectory(prefix="cf_pro_private_") as directory:
        dest=Path(directory)/"test_download.xlsx"
        result="unknown"
        for attempt in range(12):
            result=curl(path,"POST",key,dest)
            if result=="200":break
            time.sleep(2)
        if result!="200":
            sys.exit("PRIVATE_TRANSPORT_DOWNLOAD_FAILED_HTTP_"+result)
        size=dest.stat().st_size
        if size<10000 or size>1024*1024:sys.exit("XLSX_FILE_SIZE_OUT_OF_RANGE")
        with zipfile.ZipFile(dest) as xlsx:
            if xlsx.testzip() is not None:sys.exit("XLSX_ZIP_CONTENT_CORRUPT")
            names=xlsx.namelist()
            sheets=[n for n in names if n.startswith("xl/worksheets/sheet")
                    and n.endswith(".xml") and "/" not in n[len("xl/worksheets/"):]]
            if len(sheets)!=7:sys.exit("XLSX_UNEXPECTED_SHEET_COUNT_"+str(len(sheets)))
            if "xl/workbook.xml" not in names:sys.exit("XLSX_MISSING_WORKBOOK")
        print("PRIVATE_HTTP_DOWNLOAD_VALID=YES")
        print("XLSX_BYTES_RECEIVED="+str(size))
        print("XLSX_WORKSHEETS_VALIDATED="+str(len(sheets)))
        print("PUBLIC_COMMERCIAL_DOWNLOAD=DISABLED")
        print("CUSTOMER_PAYMENT_OCCURRED=NO")
finally:
    status,_=cf("DELETE",base+"/"+name)
    if status not in (200,204):
        sys.exit("PRIVATE_DIAGNOSTIC_SECRET_CLEANUP_UNCONFIRMED")
    print("PRIVATE_DIAGNOSTIC_SECRET_REMOVED")
