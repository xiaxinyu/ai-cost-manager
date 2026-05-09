from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


FLOAT_COLUMNS = {"CostUSD", "Cost", "ForecastCost"}


@dataclass(frozen=True)
class SyncReport:
    old_path: str
    new_path: str
    key_columns: list[str]
    scope_dates: str
    rows_old_total: int
    rows_new_total: int
    rows_scope_old: int
    rows_scope_new: int
    rows_updated: int
    rows_added: int
    rows_unchanged: int
    rows_old_unmatched_in_scope: int
    changed: bool


def _norm_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip().strip("\ufeff").strip()


def _to_float_or_none(v: Any) -> float | None:
    s = _norm_str(v)
    if s == "" or s.lower() in {"null", "none"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _float_equal(a: Any, b: Any, *, tol: float) -> bool:
    fa = _to_float_or_none(a)
    fb = _to_float_or_none(b)
    if fa is None and fb is None:
        return True
    if fa is None or fb is None:
        return False
    if math.isclose(fa, fb, rel_tol=tol, abs_tol=tol):
        return True
    return False


def _row_equal(row_a: dict[str, Any], row_b: dict[str, Any], *, columns: Iterable[str], float_tol: float) -> bool:
    for c in columns:
        if c in FLOAT_COLUMNS:
            if not _float_equal(row_a.get(c), row_b.get(c), tol=float_tol):
                return False
        else:
            if _norm_str(row_a.get(c)) != _norm_str(row_b.get(c)):
                return False
    return True


def _detect_key_columns(common_cols: list[str]) -> list[str]:
    """
    Choose a stable business key based on the CSV's characteristics:
    - UsageDate is day-level
    - ResourceId identifies the resource
    - Meter/service fields split charges (tokens vs endpoint vs bandwidth)
    - Currency avoids USD/local duplication edge cases
    """
    preferred = [
        "UsageDate",
        "ResourceId",
        "Meter",
        "Currency",
        "ServiceName",
        "ServiceTier",
        "ResourceLocation",
        "ResourceGroupName",
        "ResourceType",
    ]
    return [c for c in preferred if c in common_cols]


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        rows: list[dict[str, str]] = []
        for r in reader:
            rows.append({k: ("" if v is None else str(v)) for k, v in r.items()})
        return header, rows


def _write_csv_rows(path: Path, header: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for r in rows:
            out = {h: ("" if r.get(h) is None else r.get(h)) for h in header}
            writer.writerow(out)


def sync_csv_file(
    *,
    old_path: str | Path,
    new_path: str | Path,
    float_tol: float = 1e-9,
    dry_run: bool = False,
) -> SyncReport:
    """
    Update `old_path` using `new_path` for overlapping UsageDate values.

    Rules:
    - Determine business key from common columns (see `_detect_key_columns`).
    - Only rows whose `UsageDate` exists in BOTH files are in-scope.
    - For in-scope rows: upsert from new into old by key.
      - if the same key exists and values differ => update
      - if key exists only in new => add
      - if key exists only in old => keep (but counted as unmatched) to avoid data loss
    - If no material change detected, don't rewrite the old file.
    """
    old_p = Path(old_path).expanduser().resolve()
    new_p = Path(new_path).expanduser().resolve()

    old_header, old_rows = _read_csv_rows(old_p)
    new_header, new_rows = _read_csv_rows(new_p)

    common_cols = [c for c in old_header if c in set(new_header)]
    if "UsageDate" not in common_cols:
        raise ValueError("Both CSVs must contain UsageDate")

    key_cols = _detect_key_columns(common_cols)
    if len(key_cols) < 2:
        raise ValueError("Insufficient common columns to build a stable key")

    old_dates = {_norm_str(r.get("UsageDate")) for r in old_rows if _norm_str(r.get("UsageDate"))}
    new_dates = {_norm_str(r.get("UsageDate")) for r in new_rows if _norm_str(r.get("UsageDate"))}
    scope_dates = old_dates & new_dates

    def make_key(r: dict[str, Any]) -> tuple[str, ...]:
        return tuple(_norm_str(r.get(c)) for c in key_cols)

    # Build key->row maps for in-scope dates only.
    old_in_scope_keys: dict[tuple[str, ...], dict[str, Any]] = {}
    for r in old_rows:
        if _norm_str(r.get("UsageDate")) in scope_dates:
            old_in_scope_keys[make_key(r)] = r

    new_in_scope_keys: dict[tuple[str, ...], dict[str, Any]] = {}
    for r in new_rows:
        if _norm_str(r.get("UsageDate")) in scope_dates:
            new_in_scope_keys[make_key(r)] = r

    # Decide which columns are compared for equality.
    compare_cols = common_cols

    rows_updated = 0
    rows_added = 0
    rows_unchanged = 0

    # Apply updates into a new list preserving old order.
    updated_old_rows: list[dict[str, Any]] = []
    seen_scope_keys: set[tuple[str, ...]] = set()

    for r in old_rows:
        ud = _norm_str(r.get("UsageDate"))
        if ud not in scope_dates:
            updated_old_rows.append(r)
            continue

        k = make_key(r)
        seen_scope_keys.add(k)
        new_r = new_in_scope_keys.get(k)
        if new_r is None:
            updated_old_rows.append(r)
            continue

        if _row_equal(r, new_r, columns=compare_cols, float_tol=float_tol):
            rows_unchanged += 1
            updated_old_rows.append(r)
            continue

        merged = dict(r)
        for c in old_header:
            if c in new_r:
                merged[c] = new_r.get(c)
        rows_updated += 1
        updated_old_rows.append(merged)

    # Append new-only keys in-scope (missing from old) in a deterministic order.
    new_only_items = [(k, new_in_scope_keys[k]) for k in new_in_scope_keys.keys() if k not in old_in_scope_keys]
    new_only_items.sort(key=lambda x: x[0])
    for _, r in new_only_items:
        # Only keep columns present in old file header so we don't change schema unexpectedly.
        updated_old_rows.append({h: r.get(h, "") for h in old_header})
        rows_added += 1

    rows_old_unmatched_in_scope = len([k for k in old_in_scope_keys.keys() if k not in new_in_scope_keys])
    changed = (rows_updated + rows_added) > 0

    if changed and not dry_run:
        # Only rewrite if content materially changed.
        _write_csv_rows(old_p, old_header, updated_old_rows)

    return SyncReport(
        old_path=str(old_p),
        new_path=str(new_p),
        key_columns=key_cols,
        scope_dates="overlap(UsageDate)",
        rows_old_total=len(old_rows),
        rows_new_total=len(new_rows),
        rows_scope_old=len(old_in_scope_keys),
        rows_scope_new=len(new_in_scope_keys),
        rows_updated=rows_updated,
        rows_added=rows_added,
        rows_unchanged=rows_unchanged,
        rows_old_unmatched_in_scope=rows_old_unmatched_in_scope,
        changed=changed,
    )

