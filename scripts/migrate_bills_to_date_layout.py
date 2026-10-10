#!/usr/bin/env python3
"""
Migrate bills/ to the canonical date-flat layout.

Legacy:
  bills/<project>/cost-2026-9-8.csv
  bills/<project>/token/<subproject>/input-tokens-2026-9-8.csv

Date + kind dirs (intermediate):
  bills/<project>/2026-9-8/<subproject>/token/input-tokens-2026-9-8.csv
  bills/<project>/2026-9-8/<subproject>/performance/model-requests-2026-9-8.csv

Canonical (preferred):
  bills/<project>/2026-9-8/cost-2026-9-8.csv
  bills/<project>/2026-9-8/<subproject>/input-tokens-2026-9-8.csv
  bills/<project>/2026-9-8/<subproject>/model-requests-2026-9-8.csv

Default is dry-run. Pass --apply to move files. Pass --rewrite-db PATH to
rewrite ingested_* / source_file paths in SQLite after (or with) --apply.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.bills_layout import (  # noqa: E402
    plan_date_layout_relpath,
    snapshot_date_from_filename,
)


SKIP_PROJECT_NAMES = {"price", "prices"}

_DB_PATH_UPDATES = (
    ("ingested_files", "file_path"),
    ("transactions", "source_file"),
    ("ingested_token_files", "file_path"),
    ("token_usage_points", "source_file"),
    ("ingested_token_metric_files", "file_path"),
    ("token_metric_points", "source_file"),
)


def _iter_csv_relpaths(bills_dir: Path) -> list[str]:
    rels: list[str] = []
    for project_dir in sorted(bills_dir.iterdir()):
        if not project_dir.is_dir() or project_dir.name.startswith("."):
            continue
        if project_dir.name.strip().lower() in SKIP_PROJECT_NAMES:
            continue
        for csv_path in project_dir.rglob("*.csv"):
            if not csv_path.is_file():
                continue
            rels.append(str(csv_path.relative_to(bills_dir)))
    return sorted(rels)


def build_migration_plan(bills_dir: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    plan: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for old_rel in _iter_csv_relpaths(bills_dir):
        new_rel = plan_date_layout_relpath(old_rel)
        if new_rel is None:
            # Already canonical, or unclassifiable.
            if snapshot_date_from_filename(old_rel) or "/" in old_rel:
                continue
            skipped.append({"old": old_rel, "reason": "no date in filename"})
            continue
        plan.append({"old": old_rel, "new": new_rel})
    return plan, skipped


def apply_file_moves(bills_dir: Path, plan: list[dict[str, str]]) -> list[dict[str, str]]:
    moved: list[dict[str, str]] = []
    for item in plan:
        src = bills_dir / item["old"]
        dest = bills_dir / item["new"]
        if not src.is_file():
            raise FileNotFoundError(f"Missing source file: {item['old']}")
        if dest.exists():
            raise FileExistsError(f"Destination already exists: {item['new']}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        moved.append(item)
    return moved


def _prune_empty_dirs(root: Path) -> int:
    removed = 0
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if not path.is_dir() or path == root:
            continue
        try:
            next(path.iterdir())
        except StopIteration:
            path.rmdir()
            removed += 1
        except OSError:
            continue
    return removed


def rewrite_db_paths(db_path: Path, mapping: dict[str, str]) -> dict[str, int]:
    if not db_path.is_file():
        raise FileNotFoundError(f"DB not found: {db_path}")
    conn = sqlite3.connect(str(db_path))
    try:
        counts: dict[str, int] = {}
        for table, column in _DB_PATH_UPDATES:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                counts[f"{table}.{column}"] = 0
                continue
            updated = 0
            for old, new in mapping.items():
                cur = conn.execute(
                    f"UPDATE {table} SET {column} = ? WHERE {column} = ?",
                    (new, old),
                )
                updated += int(cur.rowcount or 0)
            counts[f"{table}.{column}"] = updated
        conn.commit()
        return counts
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bills-dir",
        type=Path,
        default=ROOT / "bills",
        help="Bills root directory (default: ./bills)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Move files on disk (default: dry-run only)",
    )
    parser.add_argument(
        "--rewrite-db",
        type=Path,
        default=None,
        help="SQLite DB path whose ingested_*/source_file columns should be rewritten",
    )
    parser.add_argument(
        "--map-out",
        type=Path,
        default=None,
        help="Write old→new mapping JSON (default: stdout summary only)",
    )
    parser.add_argument(
        "--prune-empty",
        action="store_true",
        help="After --apply, remove empty legacy directories under bills/",
    )
    args = parser.parse_args(argv)

    bills_dir = args.bills_dir.expanduser().resolve()
    if not bills_dir.is_dir():
        print(f"ERROR: bills dir not found: {bills_dir}", file=sys.stderr)
        return 1

    plan, skipped = build_migration_plan(bills_dir)
    mapping = {item["old"]: item["new"] for item in plan}

    print(f"Bills dir: {bills_dir}")
    print(f"Planned moves: {len(plan)}")
    print(f"Skipped: {len(skipped)}")
    for item in plan[:20]:
        print(f"  {item['old']}  ->  {item['new']}")
    if len(plan) > 20:
        print(f"  … {len(plan) - 20} more")
    if skipped:
        print("Skipped examples:")
        for item in skipped[:10]:
            print(f"  {item['old']}  ({item['reason']})")

    if args.map_out:
        args.map_out.parent.mkdir(parents=True, exist_ok=True)
        args.map_out.write_text(
            json.dumps({"moves": plan, "skipped": skipped}, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote mapping: {args.map_out}")

    if args.apply:
        moved = apply_file_moves(bills_dir, plan)
        print(f"Moved {len(moved)} file(s).")
        if args.prune_empty:
            removed = _prune_empty_dirs(bills_dir)
            print(f"Pruned {removed} empty director(ies).")
    else:
        print("Dry-run only. Re-run with --apply to move files.")

    if args.rewrite_db is not None:
        if not mapping:
            print("No mapping to rewrite.")
        elif not args.apply:
            print("NOTE: --rewrite-db without --apply uses the planned mapping only.")
        counts = rewrite_db_paths(args.rewrite_db.expanduser().resolve(), mapping)
        print("DB path rewrites:")
        for key, count in counts.items():
            print(f"  {key}: {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
