from __future__ import annotations

from app.db import _sort_rows_by_date_desc


def test_sort_rows_by_date_desc_newest_first_stable_model_tie():
    rows = [
        {"date": "2026-02-01", "model_name": "gpt-4o"},
        {"date": "2026-02-03", "model_name": "gpt-5"},
        {"date": "2026-02-03", "model_name": "gpt-4o"},
        {"date": "2026-01-15", "model_name": "gpt-4o"},
    ]
    _sort_rows_by_date_desc(rows)
    assert [r["date"] for r in rows] == [
        "2026-02-03",
        "2026-02-03",
        "2026-02-01",
        "2026-01-15",
    ]
    assert rows[0]["model_name"] == "gpt-4o"
    assert rows[1]["model_name"] == "gpt-5"
