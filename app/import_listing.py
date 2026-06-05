"""Unified listing of ingested billing, token, and token-metric files."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from .db import get_connection, init_db


def _ingested_at_epoch(ingested_at: object) -> int | None:
    """Parse SQLite UTC `datetime('now')` text to Unix seconds."""
    if ingested_at is None:
        return None
    text = str(ingested_at).strip()
    if not text:
        return None
    try:
        if text.endswith("Z") or "+" in text[10:] or text[10:11] in "-+":
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (TypeError, ValueError, OverflowError):
        return None


def count_all_ingested_files(db_path: str | os.PathLike[str]) -> dict[str, int]:
    conn = get_connection(db_path)
    try:
        init_db(conn)
        billing = int(conn.execute("SELECT COUNT(*) FROM ingested_files").fetchone()[0])
        token = int(conn.execute("SELECT COUNT(*) FROM ingested_token_files").fetchone()[0])
        metric = int(conn.execute("SELECT COUNT(*) FROM ingested_token_metric_files").fetchone()[0])
        return {
            "total": billing + token + metric,
            "billing": billing,
            "token": token,
            "token_metric": metric,
        }
    finally:
        conn.close()


def list_all_ingested_files(
    db_path: str | os.PathLike[str],
    *,
    limit: int = 2000,
    offset: int = 0,
) -> list[dict[str, object]]:
    """
    List ingested files across billing, token usage, and token metrics tables.

    Sorted newest ingested_at first (stable tie-break by source table id).
    """
    limit = max(1, min(int(limit), 5000))
    offset = max(0, int(offset))
    conn = get_connection(db_path)
    try:
        init_db(conn)
        rows = conn.execute(
            """
            SELECT
                project_name,
                file_path_rel,
                file_kind,
                token_direction,
                metric_name,
                row_count,
                ingested_at,
                source_last_modified
            FROM (
                SELECT
                    project_name,
                    file_path AS file_path_rel,
                    'billing' AS file_kind,
                    NULL AS token_direction,
                    NULL AS metric_name,
                    row_count,
                    ingested_at,
                    source_last_modified,
                    id AS sort_id,
                    1 AS kind_order
                FROM ingested_files
                UNION ALL
                SELECT
                    project_name,
                    file_path,
                    'token',
                    token_direction,
                    NULL,
                    row_count,
                    ingested_at,
                    source_last_modified,
                    id,
                    2
                FROM ingested_token_files
                UNION ALL
                SELECT
                    project_name,
                    file_path,
                    'token_metric',
                    NULL,
                    metric_name,
                    row_count,
                    ingested_at,
                    source_last_modified,
                    id,
                    3
                FROM ingested_token_metric_files
            )
            ORDER BY ingested_at DESC, kind_order ASC, sort_id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        return [
            {
                "project_name": r["project_name"],
                "file_path_rel": r["file_path_rel"],
                "file_kind": r["file_kind"],
                "token_direction": r["token_direction"],
                "metric_name": r["metric_name"],
                "row_count": int(r["row_count"]),
                "ingested_at": r["ingested_at"],
                "ingested_at_epoch": _ingested_at_epoch(r["ingested_at"]),
                "source_last_modified": r["source_last_modified"],
            }
            for r in rows
        ]
    finally:
        conn.close()
