from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import create_user
from app.db import get_connection, init_db
from app.main import create_app


def test_price_sources_list_and_patch(tmp_path):
    db_path = tmp_path / "cost_mgmt.sqlite3"
    bills_dir = tmp_path / "bills"
    bills_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection(db_path)
    try:
        init_db(conn)
        create_user(conn, username="admin", password="admin12345", is_active=True)
    finally:
        conn.close()

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)

    res = client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    assert res.status_code in {200, 303}

    r = client.get("/api/price-sources")
    assert r.status_code == 200
    rows = r.json()["sources"]
    assert len(rows) >= 1
    row_id = int(rows[0]["id"])

    p = client.patch(
        f"/api/price-sources/{row_id}",
        json={"notes": "patched-by-test"},
    )
    assert p.status_code == 200
    assert p.json()["notes"] == "patched-by-test"

    r2 = client.get("/api/price-sources")
    row = next(x for x in r2.json()["sources"] if int(x["id"]) == row_id)
    assert row["notes"] == "patched-by-test"
