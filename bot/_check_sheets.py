import json
import time
import base64
from urllib import request, parse
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

with open("/data/gcp-service-account.json") as f:
    sa = json.load(f)


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


header = b64u(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
now = int(time.time())
claim = b64u(json.dumps({
    "iss": sa["client_email"],
    "scope": "https://www.googleapis.com/auth/spreadsheets.readonly",
    "aud": "https://oauth2.googleapis.com/token",
    "iat": now,
    "exp": now + 3600,
}).encode())
msg = f"{header}.{claim}".encode()

key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
sig = key.sign(msg, padding.PKCS1v15(), hashes.SHA256())
jwt = f"{header}.{claim}.{b64u(sig)}"

data = parse.urlencode({
    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
    "assertion": jwt,
}).encode()
req = request.Request("https://oauth2.googleapis.com/token", data=data)
token = json.loads(request.urlopen(req).read())["access_token"]

sheets = [
    ("MOIL", "1Av1S2wFoiLrIeeaBO-gFGgsBtzuwMgL1ziVd2lS6c3k"),
    ("BANDI", "1nk0J3xog_TzVraMyAwpE494Q-2XQ1yw6-amtsrsoNaU"),
    ("MOROCCANOIL", "1qMNUVwizL6okhjiTI6ViEbdVHAIc-prkqnAcYQkwEmI"),
]
for name, sid in sheets:
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sid}?fields=properties.title"
    r = request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        body = json.loads(request.urlopen(r).read())
        title = body.get("properties", {}).get("title")
        print(f"{name}: OK -> {title}")
    except Exception as e:
        print(f"{name}: FAIL -> {e}")
