import urllib.request
import json
import urllib.error
import os
from app.core.security import create_access_token

# Let's create a token to bypass require_admin
# Wait, let me just hit it and see if it returns 401/403 or 404.
req = urllib.request.Request("http://127.0.0.1:8000/products", method="POST", data=b"{}", headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req) as res:
        print(res.status, res.read().decode())
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode())
