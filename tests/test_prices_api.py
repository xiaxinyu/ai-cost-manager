from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import create_user
from app.main import create_app
from app.price_ingest import import_price_csv, import_price_csv_merge


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
    assert "GPT-5.5 Series" in filters["model_series"]

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
    assert "price_source_catalog" in meta
    assert isinstance(meta["price_source_catalog"], list)
    assert len(meta["price_source_catalog"]) >= 1

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
    assert any(s["key"] == "eastus2_core_models" for s in opts["series"])
    assert any(s["key"] == "gpt_51_52" for s in opts["series"])
    assert any(s["key"] == "eastus2_gpt_51_52" for s in opts["series"])

    bad = client.post("/api/prices/sync-retail", json={"series": "not-a-real-key"})
    assert bad.status_code == 400


def test_openai_gpt55_api_pricing_csv_merge(tmp_path):
    db_path = tmp_path / "openai_gpt55.sqlite3"
    csv_path = Path(__file__).resolve().parents[1] / "fixtures" / "pricing" / "openai_com_api_pricing_gpt55_2026-05-13.csv"
    r = import_price_csv_merge(db_path=str(db_path), csv_path=str(csv_path))
    assert r.rows_read == 5

    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        n = int(
            conn.execute(
                "SELECT COUNT(*) FROM model_prices WHERE source_id = ?",
                ("openai_com_api_pricing_gpt55_20260513",),
            ).fetchone()[0]
        )
        assert n == 5
        row = conn.execute(
            "SELECT source_url, vendor, platform FROM model_prices WHERE model_name = ? LIMIT 1",
            ("GPT-5.5 Pro",),
        ).fetchone()
        assert row is not None
        assert "https://openai.com/zh-Hans-CN/api/pricing/" in row[0]
        assert row[1] == "OpenAI"
        assert row[2] == "openai-api"
    finally:
        conn.close()


def test_import_price_csv_merge_preserves_other_sources(tmp_path):
    db_path = tmp_path / "merge.sqlite3"
    bills_dir = tmp_path / "bills_m"
    bills_dir.mkdir()

    base_csv = tmp_path / "base.csv"
    base_csv.write_text(
        "vendor,platform,source_id,source_url,effective_date,retrieved_at_utc,price_region,price_currency,model_series,model_name,context_bucket,deployment_scope,billing_mode,metric_name,amount,unit_quantity,unit_name,unit_expression,notes\n"
        "Microsoft,azure-openai,keep_src,https://example.com,2026-01-01,2026-01-01T00:00:00Z,eastus2,USD,Other Series,Other Model,,global,standard,input,9.99,1000000,tokens,USD/1M tokens,\n",
        encoding="utf-8",
    )
    import_price_csv(db_path=str(db_path), csv_path=str(base_csv))

    marketing = Path(__file__).resolve().parents[1] / "fixtures" / "pricing" / "azure_marketing_gpt51_gpt52_eastus2_2026-05-13.csv"
    r = import_price_csv_merge(db_path=str(db_path), csv_path=str(marketing))
    assert r.rows_read == 45

    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        n_keep = int(
            conn.execute("SELECT COUNT(*) FROM model_prices WHERE source_id = ?", ("keep_src",)).fetchone()[0]
        )
        n_m = int(
            conn.execute(
                "SELECT COUNT(*) FROM model_prices WHERE source_id = ?",
                ("azure_marketing_table_gpt51_gpt52_eastus2_20260513",),
            ).fetchone()[0]
        )
        assert n_keep == 1
        assert n_m == 45
    finally:
        conn.close()
