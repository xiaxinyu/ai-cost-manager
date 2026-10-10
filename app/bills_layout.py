from __future__ import annotations

import re
from pathlib import Path

TOKEN_SUBDIRS = ("token", "performance")

_METRIC_FILENAME_PREFIXES = (
    "cache-match-rate-",
    "avg-latency-",
    "model-requests-",
)

_LEGACY_FILE_STEMS = (
    "input-tokens",
    "output-tokens",
    "cache-match-rate",
    "avg-latency",
    "model-requests",
)

_DATE_SUFFIX_RE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}\.csv$", re.IGNORECASE)
_LEGACY_SLUG_DATE_RE = re.compile(r"^(.+)-(\d{4}-\d{1,2}-\d{1,2})\.csv$", re.IGNORECASE)
# Allow YYYY-M-D (preferred) and month-only YYYY-M used by a few legacy cost files.
_SNAPSHOT_DATE_DIR_RE = re.compile(r"^\d{4}-\d{1,2}(?:-\d{1,2})?$")
_DATE_IN_FILENAME_RE = re.compile(r"(\d{4}-\d{1,2}(?:-\d{1,2})?)\.csv$", re.IGNORECASE)


def is_snapshot_date_dir(name: str) -> bool:
    """True for date folder names like 2026-9-8 (no zero-padding required)."""
    return bool(_SNAPSHOT_DATE_DIR_RE.match(str(name or "").strip()))


def snapshot_date_from_filename(filename: str) -> str:
    """Extract YYYY-M-D suffix from a CSV filename, or '' if absent."""
    match = _DATE_IN_FILENAME_RE.search(Path(filename).name)
    return match.group(1) if match else ""


def snapshot_date_from_relpath(file_path_rel: str) -> str:
    """
    Snapshot date for a bills-relative path.

    Prefers an explicit date directory under the project; falls back to the
    filename date suffix.
    """
    parts = Path(file_path_rel).parts
    if len(parts) >= 2 and is_snapshot_date_dir(parts[1]):
        return parts[1]
    return snapshot_date_from_filename(parts[-1] if parts else "")


def _filename_lower(filename: str) -> str:
    return Path(filename).name.lower()


def is_grafana_metric_csv_filename(filename: str) -> bool:
    """Raw Grafana export names (before migrate-grafana normalization)."""
    low = _filename_lower(filename)
    if not low.endswith(".csv"):
        return False
    return (
        low.startswith("token cache match rate")
        or low.startswith("model requests")
        or low.startswith("average latency")
    )


def is_grafana_token_usage_csv_filename(filename: str) -> bool:
    """Raw Grafana export names such as ``Input Tokens-data-as-joinbyfield-….csv``."""
    low = _filename_lower(filename)
    if not low.endswith(".csv") or is_grafana_metric_csv_filename(filename):
        return False
    return low.startswith("input tokens") or low.startswith("output tokens")


def is_metric_csv_filename(filename: str) -> bool:
    low = _filename_lower(filename)
    if any(low.startswith(prefix) for prefix in _METRIC_FILENAME_PREFIXES):
        return True
    return is_grafana_metric_csv_filename(filename)


def is_token_usage_csv_filename(filename: str) -> bool:
    low = _filename_lower(filename)
    if not low.endswith(".csv") or is_metric_csv_filename(filename):
        return False
    if low.startswith("input-tokens") or low.startswith("output-tokens"):
        return True
    return is_grafana_token_usage_csv_filename(filename)


def is_token_or_metric_csv_filename(filename: str) -> bool:
    return is_token_usage_csv_filename(filename) or is_metric_csv_filename(filename)


def metric_name_from_filename(filename: str) -> str | None:
    """Map normalized or Grafana metric filenames to DB metric_name keys."""
    low = _filename_lower(filename)
    if low.startswith("cache-match-rate-") or low.startswith("token cache match rate"):
        return "cache_match_rate"
    if low.startswith("avg-latency-") or low.startswith("average latency"):
        return "avg_latency"
    if low.startswith("model-requests-") or low.startswith("model requests"):
        return "model_requests"
    return None


def canonical_stem_from_filename(filename: str) -> str | None:
    """
    Return canonical file stem (without date), e.g. ``input-tokens``.

    Supports both normalized and raw Grafana download names.
    """
    low = _filename_lower(filename)
    if low.startswith("input-tokens") or low.startswith("input tokens"):
        return "input-tokens"
    if low.startswith("output-tokens") or low.startswith("output tokens"):
        return "output-tokens"
    metric = metric_name_from_filename(filename)
    if metric == "cache_match_rate":
        return "cache-match-rate"
    if metric == "avg_latency":
        return "avg-latency"
    if metric == "model_requests":
        return "model-requests"
    return None


def subproject_from_filename(filename: str) -> str:
    """
    Parse optional subproject slug embedded in legacy flat filenames:
    input-tokens-coding-1-2026-7-7.csv -> coding-1
    input-tokens-2026-7-7.csv -> ''
    """
    name = Path(filename).name
    low = name.lower()
    for stem in _LEGACY_FILE_STEMS:
        prefix = f"{stem}-"
        if not low.startswith(prefix):
            continue
        rest = name[len(prefix) :]
        if _DATE_SUFFIX_RE.match(rest):
            return ""
        match = _LEGACY_SLUG_DATE_RE.match(rest)
        if match:
            return match.group(1)
        return ""
    return ""


def subproject_from_resource_id(resource_id: str | None) -> str:
    """
    Derive subproject slug from an Azure ResourceId path.

    Example:
      .../accounts/proj-mdm-coding-1-resource -> proj-mdm-coding-1-resource
    """
    if not resource_id:
        return ""
    rid = str(resource_id).strip().rstrip("/")
    if not rid:
        return ""
    return rid.split("/")[-1] or ""


def _token_kind_index(parts: tuple[str, ...]) -> int | None:
    for idx, part in enumerate(parts):
        if part.lower() in TOKEN_SUBDIRS:
            return idx
    return None


def subproject_from_relpath(file_path_rel: str) -> str:
    """
    Resolve subproject from a bills-relative CSV path.

    Preferred date-snapshot (flat under subproject):
      <project>/<date>/<subproject>/<file>.csv
    Date-snapshot with kind dirs (compat):
      <project>/<date>/<subproject>/token|performance/<file>.csv
      <project>/<date>/token|performance/<file>.csv
    Legacy nested:
      <project>/token|performance/<subproject>/<file>.csv
    Legacy flat:
      <project>/token|performance/<file>.csv
    """
    parts = Path(file_path_rel).parts
    if len(parts) < 3:
        return ""

    filename = parts[-1]
    kind_idx = _token_kind_index(parts)

    # Preferred: <project>/<date>/<subproject>/file.csv
    if (
        kind_idx is None
        and len(parts) == 4
        and is_snapshot_date_dir(parts[1])
        and is_token_or_metric_csv_filename(filename)
    ):
        candidate = parts[2].strip()
        if candidate.lower() in TOKEN_SUBDIRS:
            return ""
        return candidate

    # Date root flat (no subproject): <project>/<date>/file.csv
    if (
        kind_idx is None
        and len(parts) == 3
        and is_snapshot_date_dir(parts[1])
        and is_token_or_metric_csv_filename(filename)
    ):
        return subproject_from_filename(filename)

    if kind_idx is None:
        return ""

    # Date layout with kind + subproject: <project>/<date>/<subproject>/<kind>/file.csv
    if kind_idx >= 3 and is_snapshot_date_dir(parts[1]):
        candidate = parts[kind_idx - 1]
        if candidate.lower() in TOKEN_SUBDIRS or candidate.lower().endswith(".csv"):
            return ""
        return candidate

    # Date layout with kind, no subproject: <project>/<date>/<kind>/file.csv
    if kind_idx == 2 and is_snapshot_date_dir(parts[1]):
        return subproject_from_filename(filename)

    # Legacy: <project>/<kind>/[subproject/]file.csv
    if kind_idx == 1:
        if len(parts) >= 4 and not parts[2].lower().endswith(".csv"):
            return parts[2]
        return subproject_from_filename(filename)

    return ""


def token_import_path_display(*, subproject_name: str | None = None) -> str:
    if subproject_name:
        return f"bills/<project>/<date>/{subproject_name}/"
    return "bills/<project>/<date>/<subproject>/"


def is_token_metric_csv_relpath(file_path_rel: str) -> bool:
    parts = Path(file_path_rel).parts
    if not parts or not is_metric_csv_filename(parts[-1]):
        return False
    kind_idx = _token_kind_index(parts)
    if kind_idx is not None:
        return True
    # Flat date-snapshot: under <date>/ or <date>/<subproject>/
    return len(parts) >= 3 and is_snapshot_date_dir(parts[1])


def is_token_usage_csv_relpath(file_path_rel: str) -> bool:
    if is_token_metric_csv_relpath(file_path_rel):
        return False
    parts = Path(file_path_rel).parts
    if not parts or not is_token_usage_csv_filename(parts[-1]):
        return False
    kind_idx = _token_kind_index(parts)
    if kind_idx is not None:
        return parts[kind_idx].lower() == "token"
    return len(parts) >= 3 and is_snapshot_date_dir(parts[1])


def is_billing_csv_relpath(file_path_rel: str) -> bool:
    """
    Billing CSVs live at project root (legacy) or under a date directory root.
    Token/metric filenames are never treated as billing, even at the date root.
    """
    parts = Path(file_path_rel).parts
    if len(parts) < 2 or not parts[-1].lower().endswith(".csv"):
        return False
    if is_token_or_metric_csv_filename(parts[-1]):
        return False
    if _token_kind_index(parts) is not None:
        return False
    if len(parts) == 2:
        return True
    if len(parts) == 3 and is_snapshot_date_dir(parts[1]):
        return True
    return False


def canonical_bills_relpath(file_path_rel: str) -> str | None:
    """
    Canonical date-snapshot path (no token/performance kind directories).

    Returns None when the path cannot be classified or has no snapshot date.
    """
    parts = Path(file_path_rel).parts
    if len(parts) < 2:
        return None

    project = parts[0]
    filename = parts[-1]
    if not filename.lower().endswith(".csv"):
        return None

    date = snapshot_date_from_relpath(file_path_rel) or snapshot_date_from_filename(filename)
    if not date:
        return None

    if is_billing_csv_relpath(file_path_rel) or (
        len(parts) == 2 and not is_token_or_metric_csv_filename(filename)
    ):
        return f"{project}/{date}/{filename}"

    if is_token_or_metric_csv_filename(filename) or _token_kind_index(parts) is not None:
        subproject = subproject_from_relpath(file_path_rel)
        if subproject:
            return f"{project}/{date}/{subproject}/{filename}"
        return f"{project}/{date}/{filename}"

    return None


def plan_date_layout_relpath(file_path_rel: str) -> str | None:
    """
    Map any supported bills-relative path to the canonical date-flat layout.

    Returns None when already canonical, or when the path cannot be remapped.
    """
    canonical = canonical_bills_relpath(file_path_rel)
    if canonical is None:
        return None
    if Path(canonical).as_posix() == Path(file_path_rel).as_posix():
        return None
    return canonical


def discover_subprojects_on_disk(bills_dir: str | Path, project_name: str) -> list[str]:
    project_dir = Path(bills_dir).expanduser().resolve() / project_name
    if not project_dir.is_dir():
        return []

    found: set[str] = set()
    for subdir_name in TOKEN_SUBDIRS:
        subdir = project_dir / subdir_name
        if not subdir.is_dir():
            continue
        for child in subdir.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                found.add(child.name)

    for date_dir in project_dir.iterdir():
        if not date_dir.is_dir() or not is_snapshot_date_dir(date_dir.name):
            continue
        for child in date_dir.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            if child.name.lower() in TOKEN_SUBDIRS:
                continue
            has_kind = (child / "token").is_dir() or (child / "performance").is_dir()
            has_flat = any(
                is_token_or_metric_csv_filename(p.name) for p in child.glob("*.csv")
            )
            if has_kind or has_flat:
                found.add(child.name)

    return sorted(found)


def iter_project_csv_files(
    project_dir: Path,
    *,
    subdir_name: str,
    accept_filename,
    include_date_flat: bool = False,
) -> list[tuple[Path, str, str]]:
    """
    Discover CSV files under legacy kind dirs and date-snapshot layouts.

    Set ``include_date_flat=True`` to also scan preferred flat paths
    ``<date>/<subproject>/*.csv`` and ``<date>/*.csv``. Callers that loop
    both ``token`` and ``performance`` should enable flat scan on only one
    iteration to avoid duplicates.
    """
    bills_path = project_dir.parent
    candidates: list[Path] = []

    # Legacy: <project>/<kind>/*.csv and <project>/<kind>/<subproject>/*.csv
    subdir = project_dir / subdir_name
    if subdir.is_dir():
        for csv_path in subdir.glob("*.csv"):
            candidates.append(csv_path)
        for child in sorted(subdir.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            for csv_path in child.glob("*.csv"):
                candidates.append(csv_path)

    # Date-snapshot with kind dirs (compat):
    #   <project>/<date>/<kind>/*.csv
    #   <project>/<date>/<subproject>/<kind>/*.csv
    for date_dir in sorted(project_dir.iterdir()):
        if not date_dir.is_dir() or not is_snapshot_date_dir(date_dir.name):
            continue
        flat_kind = date_dir / subdir_name
        if flat_kind.is_dir():
            for csv_path in flat_kind.glob("*.csv"):
                candidates.append(csv_path)
        for sub_dir in sorted(date_dir.iterdir()):
            if not sub_dir.is_dir() or sub_dir.name.startswith("."):
                continue
            if sub_dir.name.lower() in TOKEN_SUBDIRS:
                continue
            kind_dir = sub_dir / subdir_name
            if not kind_dir.is_dir():
                continue
            for csv_path in kind_dir.glob("*.csv"):
                candidates.append(csv_path)

    if include_date_flat:
        for date_dir in sorted(project_dir.iterdir()):
            if not date_dir.is_dir() or not is_snapshot_date_dir(date_dir.name):
                continue
            for csv_path in date_dir.glob("*.csv"):
                candidates.append(csv_path)
            for sub_dir in sorted(date_dir.iterdir()):
                if not sub_dir.is_dir() or sub_dir.name.startswith("."):
                    continue
                if sub_dir.name.lower() in TOKEN_SUBDIRS:
                    continue
                for csv_path in sub_dir.glob("*.csv"):
                    candidates.append(csv_path)

    results: list[tuple[Path, str, str]] = []
    seen: set[str] = set()
    for csv_path in candidates:
        if not accept_filename(csv_path.name):
            continue
        rel_path = str(csv_path.relative_to(bills_path))
        if rel_path in seen:
            continue
        seen.add(rel_path)
        results.append((csv_path, rel_path, subproject_from_relpath(rel_path)))

    results.sort(key=lambda item: (_file_sort_key(item[0]), item[1]))
    return results


def iter_billing_csv_files(project_dir: Path) -> list[tuple[Path, str]]:
    """
    Discover billing CSVs: project-root (legacy) and date-directory roots.

    Returns (csv_path_abs, file_path_rel), oldest first.
    """
    bills_path = project_dir.parent
    candidates: list[Path] = []

    for csv_path in project_dir.glob("*.csv"):
        candidates.append(csv_path)

    for date_dir in sorted(project_dir.iterdir()):
        if not date_dir.is_dir() or not is_snapshot_date_dir(date_dir.name):
            continue
        for csv_path in date_dir.glob("*.csv"):
            candidates.append(csv_path)

    results: list[tuple[Path, str]] = []
    for csv_path in candidates:
        rel_path = str(csv_path.relative_to(bills_path))
        if not is_billing_csv_relpath(rel_path):
            continue
        results.append((csv_path, rel_path))

    results.sort(key=lambda item: (_file_sort_key(item[0]), item[1]))
    return results


def enrich_file_listing_row(row: dict[str, object]) -> dict[str, object]:
    """Add snapshot_date / subproject_name derived from file_path_rel."""
    rel = str(row.get("file_path_rel") or "")
    out = dict(row)
    out["snapshot_date"] = snapshot_date_from_relpath(rel)
    out["subproject_name"] = subproject_from_relpath(rel)
    return out


def _file_sort_key(csv_path: Path) -> tuple[float, str]:
    try:
        mtime = float(csv_path.stat().st_mtime)
    except OSError:
        mtime = 0.0
    return (mtime, csv_path.name)
