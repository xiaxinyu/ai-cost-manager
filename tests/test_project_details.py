from __future__ import annotations

import sqlite3

from app.db import (
    ensure_project,
    ensure_project_model_config_from_tokens,
    init_db,
    list_project_details,
    upsert_project_model_config,
)


def _seed_token_row(conn: sqlite3.Connection, project: str, model: str) -> None:
    ensure_project(conn, project)
    conn.execute(
        """
        INSERT INTO token_usage_points(
            project_name, recorded_at, usage_date, model_name,
            token_direction, token_count, source_file, source_row_index
        ) VALUES (?, '2026-06-01 00:00:00', '2026-06-01', ?, 'input', 100, 'p/token/in.csv', 1)
        """,
        (project, model),
    )
    conn.commit()


def test_pick_primary_prefers_gpt4o(tmp_path):
    db_path = tmp_path / "t.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    proj = "RG-HK-S56-RTD-SALES-SUMMARY-T"
    _seed_token_row(conn, proj, "gpt-5.2")
    _seed_token_row(conn, proj, "gpt-4o")

    primary = ensure_project_model_config_from_tokens(conn, proj)
    assert primary == "gpt-4o"
    details = list_project_details(conn)
    row = next(d for d in details if d["name"] == proj)
    assert row["primary_model"] == "gpt-4o"
    assert "gpt-4o" in row["display_label"]
    assert "gpt-4o" in row["token_models"]
    conn.close()


def test_auto_config_from_folder_hint(tmp_path):
    db_path = tmp_path / "t.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    proj = "techlab-aiops-gpt5.1"
    _seed_token_row(conn, proj, "gpt-5.5")
    _seed_token_row(conn, proj, "gpt-5.1")

    primary = ensure_project_model_config_from_tokens(conn, proj)
    assert primary == "gpt-5.1"
    conn.close()


def test_existing_config_not_overwritten(tmp_path):
    db_path = tmp_path / "t.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    proj = "techlab-aiops-gpt5.1"
    _seed_token_row(conn, proj, "gpt-5.1")
    upsert_project_model_config(
        conn,
        project_name=proj,
        model_name="gpt-5.3-codex",
        api_version=None,
        azure_endpoint=None,
    )

    primary = ensure_project_model_config_from_tokens(conn, proj)
    assert primary == "gpt-5.3-codex"
    conn.close()
