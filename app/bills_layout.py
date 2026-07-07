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


def is_metric_csv_filename(filename: str) -> bool:
    low = filename.lower()
    return any(low.startswith(prefix) for prefix in _METRIC_FILENAME_PREFIXES)


def is_token_usage_csv_filename(filename: str) -> bool:
    low = Path(filename).name.lower()
    if not low.endswith(".csv") or is_metric_csv_filename(filename):
        return False
    return low.startswith("input-tokens") or low.startswith("output-tokens")


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


def subproject_from_relpath(file_path_rel: str) -> str:
    """
    Resolve subproject from a bills-relative CSV path.

    Nested layout:
      <project>/token/<subproject>/input-tokens-2026-7-7.csv
    Flat layout:
      <project>/token/input-tokens-2026-7-7.csv

    Legacy flat slug-in-name is also recognized for backward compatibility.
    """
    parts = Path(file_path_rel).parts
    if len(parts) < 3:
        return ""

    subdir = parts[1].lower()
    if subdir not in TOKEN_SUBDIRS:
        return ""

    filename = parts[-1]
    if len(parts) >= 4 and not parts[2].lower().endswith(".csv"):
        return parts[2]

    return subproject_from_filename(filename)


def token_import_path_display(*, subproject_name: str | None = None) -> str:
    if subproject_name:
        return f"bills/<project>/{TOKEN_SUBDIRS[0]}/{subproject_name}/"
    return "bills/<project>/token/"


def is_token_metric_csv_relpath(file_path_rel: str) -> bool:
    parts = Path(file_path_rel).parts
    if len(parts) < 3:
        return False
    subdir = parts[1].lower()
    if subdir == "performance":
        return is_metric_csv_filename(parts[-1])
    if subdir == "token":
        return is_metric_csv_filename(parts[-1])
    return False


def is_token_usage_csv_relpath(file_path_rel: str) -> bool:
    if is_token_metric_csv_relpath(file_path_rel):
        return False
    parts = Path(file_path_rel).parts
    if len(parts) < 3 or parts[1].lower() != "token":
        return False
    return is_token_usage_csv_filename(parts[-1])


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
    return sorted(found)


def iter_project_csv_files(
    project_dir: Path,
    *,
    subdir_name: str,
    accept_filename,
) -> list[tuple[Path, str, str]]:
    """
    Discover CSV files under flat and nested layouts for one bills subfolder.

    Returns list of (csv_path_abs, file_path_rel, subproject_name), oldest first.
    """
    bills_path = project_dir.parent
    subdir = project_dir / subdir_name
    if not subdir.is_dir():
        return []

    candidates: list[Path] = []
    for csv_path in subdir.glob("*.csv"):
        candidates.append(csv_path)
    for child in sorted(subdir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        for csv_path in child.glob("*.csv"):
            candidates.append(csv_path)

    results: list[tuple[Path, str, str]] = []
    for csv_path in candidates:
        if not accept_filename(csv_path.name):
            continue
        rel_path = str(csv_path.relative_to(bills_path))
        results.append((csv_path, rel_path, subproject_from_relpath(rel_path)))

    results.sort(key=lambda item: (_file_sort_key(item[0]), item[1]))
    return results


def _file_sort_key(csv_path: Path) -> tuple[float, str]:
    try:
        mtime = float(csv_path.stat().st_mtime)
    except OSError:
        mtime = 0.0
    return (mtime, csv_path.name)
