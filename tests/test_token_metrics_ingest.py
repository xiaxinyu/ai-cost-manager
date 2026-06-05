from __future__ import annotations

import sqlite3

from app.db import init_db
from app.token_metric_ingest import ingest_token_metric_all


def test_token_metric_ingest_upsert_and_repeat_import(tmp_path):
    bills_dir = tmp_path / "bills"
    proj = bills_dir / "projA"
    (proj / "token").mkdir(parents=True, exist_ok=True)
    (proj / "performance").mkdir(parents=True, exist_ok=True)

    f1 = proj / "token" / "cache-match-rate-2026-6-4.csv"
    f1.write_text(
        '"Time","gpt-4o"\n'
        "2026-06-01 00:00:00,0.533%\n",
        encoding="utf-8",
    )
    f2 = proj / "performance" / "avg-latency-2026-6-4.csv"
    f2.write_text(
        '"Time","gpt-4o"\n'
        "2026-06-01 00:00:00,9.10 s\n",
        encoding="utf-8",
    )
    f3 = proj / "performance" / "model-requests-2026-6-4.csv"
    f3.write_text(
        '"Time","gpt-4o"\n'
        "2026-06-01 00:00:00,3.61 K\n",
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    r1 = ingest_token_metric_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=True)
    assert r1.verification_passed is True
    assert r1.files_ingested == 3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    try:
        rows = conn.execute(
            "SELECT metric_name, metric_unit, metric_value FROM token_metric_points ORDER BY metric_name"
        ).fetchall()
        by_name = {r["metric_name"]: (r["metric_unit"], float(r["metric_value"])) for r in rows}
        assert by_name["cache_match_rate"][0] == "pct"
        assert abs(by_name["cache_match_rate"][1] - 0.533) < 1e-6
        assert by_name["avg_latency"][0] == "ms"
        assert abs(by_name["avg_latency"][1] - 9100.0) < 1e-6
        assert by_name["model_requests"][0] == "count"
        assert abs(by_name["model_requests"][1] - 3610.0) < 1e-6
    finally:
        conn.close()

    # Repeat import updates value (upsert)
    f2.write_text(
        '"Time","gpt-4o"\n'
        "2026-06-01 00:00:00,1.00 s\n",
        encoding="utf-8",
    )
    r2 = ingest_token_metric_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=True)
    assert r2.verification_passed is True
    conn2 = sqlite3.connect(db_path)
    conn2.row_factory = sqlite3.Row
    init_db(conn2)
    try:
        v = conn2.execute(
            "SELECT metric_value FROM token_metric_points WHERE metric_name='avg_latency' LIMIT 1"
        ).fetchone()["metric_value"]
        assert abs(float(v) - 1000.0) < 1e-6
    finally:
        conn2.close()

