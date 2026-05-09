from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_chart_js_served_locally(tmp_path):
    """Vendor Chart.js must be available at /static without CDN."""
    app = create_app(db_path=str(tmp_path / "db.sqlite3"), bills_dir=str(tmp_path / "bills"), auto_ingest=False)
    client = TestClient(app)
    res = client.get("/static/js/chart.umd.min.js")
    assert res.status_code == 200
    assert b"Chart" in res.content[:5000] or b"chart" in res.content[:200].lower()

    bundle = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "chart.umd.min.js"
    assert bundle.is_file()
    assert bundle.stat().st_size > 100_000
