"""Read-only diagnostic for the organic Instagram -> paid Excel buyer journey.

No tokens, captions, profile personal data, customer PII, or payment details are logged.
This script never publishes, messages followers, updates the profile, or spends money.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API="https://graph.instagram.com/v26.0"
EXPECTED_USERNAME="lumen.b2b"
EXPECTED_ID="17841427692864676"
PRODUCT="calculafacil.lumen-b2b.workers.dev"
LAUNCH_POST_ID="18178583491430935"
MARKER="CALCULAFACIL_PRO_LUMEN_OCT2026"

def get(path,token):
    req=urllib.request.Request(
        API+path,method="GET",
        headers={"Authorization":"Bearer "+token,"Accept":"application/json",
                 "User-Agent":"LUMEN-Organic-Conversion-Audit/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=20) as r:
            return r.status,json.load(r)
    except urllib.error.HTTPError as ex:
        return ex.code,{}
    except (TimeoutError,urllib.error.URLError):
        return 0,{}

def check_profile_website(value):
    url=str(value or "").strip()
    if not url:
        return "MISSING"
    if not url.startswith(("https://","http://")):
        url="https://"+url
    try:
        parsed=urllib.parse.urlparse(url)
    except ValueError:
        return "UNVERIFIED"
    if parsed.hostname and parsed.hostname.lower()==PRODUCT and parsed.path.lower().rstrip("/") in ("","/pro.html"):
        return "CORRECT_PRODUCT_OR_FREE_HOMEPAGE"
    if parsed.hostname and parsed.hostname.lower() in ("www.instagram.com","instagram.com"):
        return "INSTAGRAM_PROFILE_LOOP"
    return "OTHER_LINK_NOT_VERIFIED"

def main():
    if "--self-test" in sys.argv:
        assert check_profile_website("https://"+PRODUCT+"/pro.html")=="CORRECT_PRODUCT_OR_FREE_HOMEPAGE"
        assert check_profile_website("https://"+PRODUCT+"/")=="CORRECT_PRODUCT_OR_FREE_HOMEPAGE"
        assert check_profile_website("")=="MISSING"
        assert check_profile_website("https://unrelated.example/landing")=="OTHER_LINK_NOT_VERIFIED"
        print("INSTAGRAM_BIO_BUYER_PATH_SAFETY_TESTS_PASS")
        return
    token=os.getenv("LUMEN_INSTAGRAM_ACCESS_TOKEN","").strip()
    if len(token)<30:
        raise RuntimeError("instagram_existing_token_not_available")
    info_fields="user_id,id,username,website,followers_count,media_count"
    status,me=get("/me?fields="+urllib.parse.quote(info_fields,safe=","),token)
    website_field_available=(status==200 and isinstance(me,dict) and "website" in me)
    if status!=200:
        status,me=get("/me?fields=user_id,id,username",token)
        if status!=200:
            raise RuntimeError("instagram_identity_not_readable")
    identity=str(me.get("user_id") or me.get("id") or "")
    username=str(me.get("username") or "")
    if identity!=EXPECTED_ID or username!=EXPECTED_USERNAME:
        raise RuntimeError("instagram_merchant_account_mismatch")
    print("VERIFIED_INSTAGRAM_ACCOUNT=@lumen.b2b")
    if website_field_available:
        print("INSTAGRAM_PROFILE_PRODUCT_LINK_STATUS="+check_profile_website(me.get("website")))
    else:
        print("INSTAGRAM_PROFILE_PRODUCT_LINK_STATUS=NOT_ACCESSIBLE_VIA_CONNECTED_API")
    followers=me.get("followers_count")
    if isinstance(followers,int) and followers>=0:
        print("INSTAGRAM_FOLLOWER_COUNT="+str(followers))
    status,posts=get("/me/media?fields=id,caption,permalink,like_count,comments_count&limit=50",token)
    if status!=200 or not isinstance(posts.get("data"),list):
        print("INSTAGRAM_POST_METRICS=NOT_AVAILABLE")
        return
    matched=next((x for x in posts["data"]
       if isinstance(x,dict) and str(x.get("id") or "")==LAUNCH_POST_ID and
          MARKER in str(x.get("caption") or "")),None)
    if matched is None:
        print("CALCULAFACIL_PRO_POST_FOUND_IN_RECENT_FEED=NO")
        return
    print("CALCULAFACIL_PRO_POST_FOUND_IN_RECENT_FEED=YES")
    for field,name in (("like_count","POST_LIKES"),("comments_count","POST_COMMENTS")):
        count=matched.get(field)
        if isinstance(count,int) and count>=0:print(name+"="+str(count))
    print("POST_REACH_OR_SALES=NOT_INFERRED_FROM_LIKES")
    print("AUTOMATIC_OUTBOUND_MESSAGING=NO")
    print("PAID_ADVERTISING_SPEND=0")

if __name__=="__main__":
    try:main()
    except Exception as ex:
        print("INSTAGRAM_BIO_AUDIT_UNAVAILABLE="+str(ex)[:110])
        raise SystemExit(1)
