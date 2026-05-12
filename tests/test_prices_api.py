from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import create_user
from app.main import create_app
from app.price_ingest import import_price_csv


def test_prices_filters_and_query(tmp_path):
    db_path = tmp_path / "cost_mgmt.sqlite3"
    bills_dir = tmp_path / "bills"
    bills_dir.mkdir(parents=True, exist_ok=True)

    price_csv = tmp_path / "prices.csv"
    price_csv.write_text(
        "vendor,platform,source_id,effective_date,retrieved_at_utc,price_region,price_currency,model_series,model_name,context_bucket,deployment_scope,billing_mode,metric_name,amount,unit_quantity,unit_name,unit_expression,source_url,notes\n"
        "Microsoft,azure-openai,src,2026-04-29,2026-04-29T00:00:00Z,East US,USD,GPT-5.3 Series,GPT-5.3 Codex,,global,standard,input,1.75,1000000,tokens,USD/1M tokens,https://example.com,\n",
        encoding="utf-8",
    )
    import_price_csv(db_path=str(db_path), csv_path=str(price_csv))

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)

    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        create_user(conn, username="admin", password="admin12345", is_active=True)
    finally:
        conn.close()

    res = client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    assert res.status_code in {200, 303}

    filters = client.get("/api/prices/filters").json()
    assert "Microsoft" in filters["vendors"]
    assert "azure-openai" in filters["platforms"]
    assert "GPT-5.3 Series" in filters["model_series"]

    rows = client.get(
        "/api/prices?vendor=Microsoft&platform=azure-openai&model_series=GPT-5.3%20Series"
    ).json()
    assert rows["total"] == 1
    assert rows["page"] == 1
    assert rows["page_size"] == 100
    assert len(rows["rows"]) == 1
    assert rows["rows"][0]["model_name"] == "GPT-5.3 Codex"
    rid = rows["rows"][0]["id"]
    assert isinstance(rid, int)

    meta = client.get("/api/prices/meta").json()
    assert meta["total_rows"] == 1
    assert len(meta["sources"]) == 1
    assert meta["sources"][0]["source_id"] == "src"

    p2 = client.get("/api/prices?page=2&page_size=10").json()
    assert p2["total"] == 1
    assert p2["rows"] == []

    detail = client.get(f"/api/prices/row/{rid}").json()
    assert detail["id"] == rid
    assert detail["metric_name"] == "input"
    assert detail["source_detail"] is None

    missing = client.get("/api/prices/row/999999")
    assert missing.status_code == 404

    opts = client.get("/api/prices/sync-series-options").json()
    assert "series" in opts
    assert any(s["key"] == "all" for s in opts["series"])

    bad = client.post("/api/prices/sync-retail", json={"series": "not-a-real-key"})
    assert bad.status_code == 400
