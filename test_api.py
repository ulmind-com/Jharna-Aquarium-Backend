from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
res = client.get("/products?admin=true&limit=100")
print(res.status_code)
if res.status_code != 200:
    print(res.json())
else:
    print(len(res.json()), "products returned")
