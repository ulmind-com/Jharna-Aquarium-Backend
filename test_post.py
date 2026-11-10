import urllib.request
import json
import urllib.error

data = json.dumps({"name": "test", "slug": "test"}).encode()
req = urllib.request.Request("http://127.0.0.1:8000/brands", data=data, headers={"Content-Type": "application/json"}, method="POST")

try:
    with urllib.request.urlopen(req) as res:
        print(res.status, res.read().decode())
except urllib.error.HTTPError as e:
    print("HTTPError", e.code, e.read().decode())
