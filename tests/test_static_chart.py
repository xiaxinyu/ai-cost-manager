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


def test_chart_style_x_axis_uses_date_labels():
    """Category x-axis ticks must map indices to chart date labels, not show 0/5/10."""
    style = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "chart-style.js"
    text = style.read_text(encoding="utf-8")
    assert "function labelAtTick" in text
    assert "labelAtTick(this, value)" in text


def test_dashboard_ui_sort_by_date_desc():
    ui = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "dashboard-ui.js"
    text = ui.read_text(encoding="utf-8")
    assert "function sortByDateDesc" in text


def test_ratio_bounds_include_full_data_range():
    """Ratio Y-axis must not IQR-clip spikes so the chart shows every point."""
    forecasting = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "forecasting.js"
    text = forecasting.read_text(encoding="utf-8")
    assert "always include every data point" in text
    assert "guardHi" not in text


def test_cost_semantics_billing_key():
    semantics = Path(__file__).resolve().parents[1] / "app" / "static" / "js" / "cost-semantics.js"
    text = semantics.read_text(encoding="utf-8")
    assert "billingKey" in text
    assert "By model" in text
    assert "Others ·" in text
