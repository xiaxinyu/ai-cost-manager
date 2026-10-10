#!/usr/bin/env python3
"""
Rename raw Grafana / Azure cost-analysis downloads under bills/ to canonical names.

Examples:
  …/2026-10-9/proj-…/Input Tokens-data-as-joinbyfield-2026-10-10 15_15_30.csv
  -> …/2026-10-9/proj-…/input-tokens-2026-10-9.csv

  …/2026-10-9/cost-analysis.csv  (or cost-analysis (1).csv)
  -> …/2026-10-9/cost-2026-10-9.csv

Uses the parent snapshot date directory (not timestamps in download names).
Also trims trailing/leading spaces on directory names.

Default is dry-run. Pass --apply to rename.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.bills_layout import (  # noqa: E402
    canonical_stem_from_filename,
    is_snapshot_date_dir,
)


SKIP_PROJECT_NAMES = {"price", "prices"}
_COST_ANALYSIS_RE = re.compile(r"^cost-analysis(?: \(\d+\))?\.csv$", re.IGNORECASE)


def _needs_rename(name: str, stem: str, date: str) -> bool:
    canonical = f"{stem}-{date}.csv"
    return name != canonical


def _is_cost_analysis_filename(name: str) -> bool:
    return bool(_COST_ANALYSIS_RE.match(Path(name).name))


def trim_directory_names(bills_dir: Path, *, apply: bool) -> list[tuple[str, str]]:
    changes: list[tuple[str, str]] = []
    for path in sorted(bills_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if not path.is_dir():
            continue
        cleaned = path.name.strip()
        if not cleaned or cleaned == path.name:
            continue
        rel_old = str(path.relative_to(bills_dir))
        dest = path.with_name(cleaned)
        changes.append((rel_old, str(dest.relative_to(bills_dir))))
        if apply:
            if dest.exists():
                raise FileExistsError(f"Cannot rename dir; target exists: {dest}")
            path.rename(dest)
    return changes


def build_rename_plan(bills_dir: Path) -> list[tuple[Path, Path]]:
    plan: list[tuple[Path, Path]] = []
    for project_dir in sorted(bills_dir.iterdir()):
        if not project_dir.is_dir() or project_dir.name.startswith("."):
            continue
        if project_dir.name.strip().lower() in SKIP_PROJECT_NAMES:
            continue
        for date_dir in sorted(project_dir.iterdir()):
            if not date_dir.is_dir() or not is_snapshot_date_dir(date_dir.name):
                continue
            date = date_dir.name
            targets = [date_dir]
            targets.extend(
                p
                for p in sorted(date_dir.iterdir())
                if p.is_dir() and not p.name.startswith(".")
            )
            for folder in targets:
                for csv_path in sorted(folder.glob("*.csv")):
                    # Azure cost-analysis exports live at the date-dir root.
                    if folder == date_dir and _is_cost_analysis_filename(csv_path.name):
                        dest = date_dir / f"cost-{date}.csv"
                        if csv_path.name != dest.name:
                            plan.append((csv_path, dest))
                        continue
                    stem = canonical_stem_from_filename(csv_path.name)
                    if stem is None or not _needs_rename(csv_path.name, stem, date):
                        continue
                    plan.append((csv_path, folder / f"{stem}-{date}.csv"))
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bills-dir", type=Path, default=ROOT / "bills")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    bills_dir = args.bills_dir.expanduser().resolve()
    if not bills_dir.is_dir():
        print(f"ERROR: bills dir not found: {bills_dir}", file=sys.stderr)
        return 1

    print(f"Bills dir: {bills_dir}")
    dir_changes = trim_directory_names(bills_dir, apply=args.apply)
    print(f"Directory trims: {len(dir_changes)}")
    for old, new in dir_changes[:10]:
        print(f"  {old!r}  ->  {new!r}")

    plan = build_rename_plan(bills_dir)
    print(f"File renames: {len(plan)}")
    for src, dest in plan[:25]:
        print(f"  {src.relative_to(bills_dir)}")
        print(f"    -> {dest.name}")
    if len(plan) > 25:
        print(f"  … {len(plan) - 25} more")

    if not args.apply:
        print("Dry-run only. Re-run with --apply to rename.")
        return 0

    for src, dest in plan:
        if dest.exists() and dest.resolve() != src.resolve():
            raise FileExistsError(f"Destination exists: {dest}")
        if dest.resolve() == src.resolve():
            continue
        src.rename(dest)
    print(f"Renamed {len(plan)} file(s); trimmed {len(dir_changes)} dir(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
