#!/usr/bin/env bash
# Migrate Grafana export CSVs from ~/Downloads into bills/<project>/token|performance.
#
# Matches macOS Grafana export names such as:
#   Output Tokens-data-7_6_2026, 5_06_55 PM.csv
#   Input Tokens-data-7_6_2026, 5_06_47 PM.csv
#   Token Cache Match Rate-data-7_6_2026, 5_04_39 PM.csv
#   Model requests-data-7_6_2026, 5_04_30 PM.csv
#   Average Latency-data-7_6_2026, 5_04_25 PM.csv
#
# Renames to repo conventions:
#   token/input-tokens-YYYY-M-D.csv
#   token/output-tokens-YYYY-M-D.csv
#   performance/cache-match-rate-YYYY-M-D.csv
#   performance/model-requests-YYYY-M-D.csv
#   performance/avg-latency-YYYY-M-D.csv
#
# With --subproject NAME, inserts a slug before the date:
#   performance/model-requests-<subproject>-YYYY-M-D.csv
#   token/input-tokens-<subproject>-YYYY-M-D.csv
#
# Usage:
#   ./scripts/migrate-grafana-downloads.sh --project RG-HK-S56-TATP-QA-Agent
#   ./scripts/migrate-grafana-downloads.sh -p techlab-aimas-marketing --subproject gpt-5.4 -d 2026-6-30
#   ./scripts/migrate-grafana-downloads.sh -p rg-techlab-ai-coding -s ~/Downloads -n
#   ./scripts/migrate-grafana-downloads.sh -p RG-HK-S56-TATP-QA-Agent --date 2026-7-6
#   ./scripts/migrate-grafana-downloads.sh -p RG-HK-S56-TATP-QA-Agent --dry-run
#   ./scripts/migrate-grafana-downloads.sh -p RG-HK-S56-TATP-QA-Agent --force
#
# Dry-run (-n / --dry-run): scan Downloads and print each source file and its
# destination path without moving or renaming anything. Use this to verify project,
# date suffix, and target folders before running without -n.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SOURCE_DIR="${HOME}/Downloads"
BILLS_DIR="${REPO_ROOT}/bills"
PROJECT=""
SUBPROJECT=""
DATE_SUFFIX=""
DRY_RUN=0
FORCE=0

usage() {
  cat <<'EOF'
Migrate Grafana CSV exports from Downloads into bills/<project>/.

Options:
  -p, --project NAME   Project folder under bills/ (required)
  -u, --subproject NAME
                       Optional slug inserted before date in output filenames
                       (e.g. model-requests-gpt-5.4-2026-6-30.csv)
  -d, --date DATE      Date suffix for output filenames (default: today)
                       Accepted: YYYY-M-D, YYYY-MM-DD, M_D_YYYY, M/D/YYYY
  -s, --source DIR     Source directory (default: ~/Downloads)
  -b, --bills-dir DIR  Bills root (default: <repo>/bills)
  -n, --dry-run        Preview only: show source -> destination mapping;
                       does not move, rename, or delete any file. Recommended
                       before the first run or when changing --project/--date.
  -f, --force          Overwrite destination if it already exists
  -h, --help           Show this help

Recognized source filename prefixes (with optional --subproject SLUG before date):
  Output Tokens-data*        -> token/output-tokens[-SLUG]-YYYY-M-D.csv
  Input Tokens-data*         -> token/input-tokens[-SLUG]-YYYY-M-D.csv
  Token Cache Match Rate*    -> performance/cache-match-rate[-SLUG]-YYYY-M-D.csv
  Model requests-data*       -> performance/model-requests[-SLUG]-YYYY-M-D.csv
  Average Latency*           -> performance/avg-latency[-SLUG]-YYYY-M-D.csv

Examples:
  # Preview (no files changed)
  ./scripts/migrate-grafana-downloads.sh -p RG-HK-S56-TATP-QA-Agent --dry-run
  ./scripts/migrate-grafana-downloads.sh -p techlab-aimas-marketing -u gpt-5.4 -d 2026-6-30 -n

  # Migrate for real
  ./scripts/migrate-grafana-downloads.sh --project RG-HK-S56-TATP-QA-Agent
  ./scripts/migrate-grafana-downloads.sh -p RG-HK-S56-TATP-QA-Agent -d 7_6_2026
  ./scripts/migrate-grafana-downloads.sh -p techlab-aimas-marketing --subproject gpt-5.4 -d 2026-6-30
EOF
}

log() {
  printf '%s\n' "$*"
}

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  # Ignore blank args (often from a broken `\` line continuation with trailing spaces).
  if [[ -z "${1//[[:space:]]/}" ]]; then
    shift
    continue
  fi
  case "$1" in
    -p|--project)
      [[ $# -ge 2 ]] || die "Missing value for $1"
      PROJECT="$2"
      shift 2
      ;;
    -u|--subproject)
      [[ $# -ge 2 ]] || die "Missing value for $1"
      SUBPROJECT="$2"
      shift 2
      ;;
    -d|--date)
      [[ $# -ge 2 ]] || die "Missing value for $1"
      DATE_SUFFIX="$2"
      shift 2
      ;;
    -s|--source)
      [[ $# -ge 2 ]] || die "Missing value for $1"
      SOURCE_DIR="$2"
      shift 2
      ;;
    -b|--bills-dir)
      [[ $# -ge 2 ]] || die "Missing value for $1"
      BILLS_DIR="$2"
      shift 2
      ;;
    -n|--dry-run)
      DRY_RUN=1
      shift
      ;;
    -f|--force)
      FORCE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ "$1" == "--dry-run" ]]; then
        die "Unknown option: $1 — did the previous line end with '\\\\' plus trailing spaces? Use one line, or put nothing after '\\\\'. Example: ... --subproject coding-1 -n"
      fi
      die "Unknown option: $1 (use --help)"
      ;;
  esac
done

[[ -n "${PROJECT}" ]] || die "Project name is required. Example: --project RG-HK-S56-TATP-QA-Agent"

SOURCE_DIR="$(cd "${SOURCE_DIR}" 2>/dev/null && pwd || true)"
[[ -n "${SOURCE_DIR}" && -d "${SOURCE_DIR}" ]] || die "Source directory not found: ${SOURCE_DIR}"

BILLS_DIR="$(cd "${BILLS_DIR}" 2>/dev/null && pwd || true)"
[[ -n "${BILLS_DIR}" ]] || die "Bills directory not found: ${BILLS_DIR}"

DEST_TOKEN="${BILLS_DIR}/${PROJECT}/token"
DEST_PERF="${BILLS_DIR}/${PROJECT}/performance"

normalize_date_suffix() {
  local input="$1"
  local year month day

  if [[ "${input}" =~ ^([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})$ ]]; then
    year="${BASH_REMATCH[1]}"
    month="${BASH_REMATCH[2]}"
    day="${BASH_REMATCH[3]}"
  elif [[ "${input}" =~ ^([0-9]{1,2})_([0-9]{1,2})_([0-9]{4})$ ]]; then
    month="${BASH_REMATCH[1]}"
    day="${BASH_REMATCH[2]}"
    year="${BASH_REMATCH[3]}"
  elif [[ "${input}" =~ ^([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})$ ]]; then
    month="${BASH_REMATCH[1]}"
    day="${BASH_REMATCH[2]}"
    year="${BASH_REMATCH[3]}"
  else
    return 1
  fi

  month="${month#0}"
  day="${day#0}"
  printf '%s-%s-%s' "${year}" "${month}" "${day}"
}

current_date_suffix() {
  local year month day
  year="$(date +%Y)"
  month="$(date +%-m)"
  day="$(date +%-d)"
  printf '%s-%s-%s' "${year}" "${month}" "${day}"
}

if [[ -n "${DATE_SUFFIX}" ]]; then
  DATE_SUFFIX="$(normalize_date_suffix "${DATE_SUFFIX}" || true)"
  [[ -n "${DATE_SUFFIX}" ]] || die "Invalid --date format. Use YYYY-M-D, M_D_YYYY, or M/D/YYYY"
else
  DATE_SUFFIX="$(current_date_suffix)"
fi

normalize_subproject_slug() {
  local input="$1"
  local slug
  slug="$(printf '%s' "${input}" | tr '[:upper:]' '[:lower:]')"
  slug="${slug// /-}"
  slug="$(printf '%s' "${slug}" | sed -E 's/[^a-z0-9._-]+/-/g; s/-+/-/g; s/^[.-]+|[.-]+$//g')"
  printf '%s' "${slug}"
}

if [[ -n "${SUBPROJECT}" ]]; then
  SUBPROJECT="$(normalize_subproject_slug "${SUBPROJECT}")"
  [[ -n "${SUBPROJECT}" ]] || die "Invalid --subproject value (use letters, numbers, hyphens, underscores)"
fi

build_dest_name() {
  local file_stem="$1"
  if [[ -n "${SUBPROJECT}" ]]; then
    printf '%s-%s-%s.csv' "${file_stem}" "${SUBPROJECT}" "${DATE_SUFFIX}"
  else
    printf '%s-%s.csv' "${file_stem}" "${DATE_SUFFIX}"
  fi
}

classify_file() {
  local name="$1"

  case "${name}" in
    "Output Tokens-data"*)
      printf 'token output-tokens'
      ;;
    "Input Tokens-data"*)
      printf 'token input-tokens'
      ;;
    "Token Cache Match Rate"*)
      printf 'performance cache-match-rate'
      ;;
    "Model requests-data"*)
      printf 'performance model-requests'
      ;;
    "Average Latency"*)
      printf 'performance avg-latency'
      ;;
    *)
      return 1
      ;;
  esac
}

move_file() {
  local src="$1"
  local dest_dir="$2"
  local dest_name="$3"
  local dest="${dest_dir}/${dest_name}"

  if [[ -e "${dest}" && "${FORCE}" -eq 0 ]]; then
    log "  SKIP (exists): ${dest_name}  <- $(basename "${src}")"
    return 0
  fi

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "  DRY-RUN: $(basename "${src}")"
    log "        -> ${dest}"
    return 0
  fi

  mkdir -p "${dest_dir}"
  mv "${src}" "${dest}"
  log "  MOVED: $(basename "${src}")"
  log "      -> ${dest}"
}

process_group() {
  local group_label="$1"
  local dest_dir="$2"
  shift 2
  local -a entries=("$@")
  local entry file_stem src dest_name dest_path

  [[ ${#entries[@]} -eq 0 ]] && return 0

  log "== ${group_label} =="
  log "   -> ${dest_dir}"

  for entry in "${entries[@]}"; do
    file_stem="${entry%%|*}"
    src="${entry#*|}"

    matched=$((matched + 1))
    dest_name="$(build_dest_name "${file_stem}")"
    dest_path="${dest_dir}/${dest_name}"

    if [[ -e "${dest_path}" && "${FORCE}" -eq 0 ]]; then
      skipped=$((skipped + 1))
    else
      moved=$((moved + 1))
    fi

    move_file "${src}" "${dest_dir}" "${dest_name}"
  done

  log ""
}

shopt -s nullglob
matched=0
moved=0
skipped=0

log "Source:  ${SOURCE_DIR}"
log "Project: ${PROJECT}"
[[ -n "${SUBPROJECT}" ]] && log "Subproject: ${SUBPROJECT}"
log "Date:    ${DATE_SUFFIX}"
log "Dest:    ${DEST_PERF}"
log "         ${DEST_TOKEN}"
log "Order:   performance -> token"
[[ "${DRY_RUN}" -eq 1 ]] && log "Mode:    dry-run"
[[ "${FORCE}" -eq 1 ]] && log "Mode:    force overwrite"
log ""

perf_entries=()
token_entries=()

for src in "${SOURCE_DIR}"/*.csv; do
  [[ -f "${src}" ]] || continue
  base="$(basename "${src}")"

  kind_and_stem="$(classify_file "${base}" 2>/dev/null || true)"
  [[ -n "${kind_and_stem}" ]] || continue

  read -r dest_subdir file_stem <<<"${kind_and_stem}"
  entry="${file_stem}|${src}"

  case "${dest_subdir}" in
    performance) perf_entries+=("${entry}") ;;
    token) token_entries+=("${entry}") ;;
    *) die "Internal error: unknown dest subdir ${dest_subdir}" ;;
  esac
done

if [[ ${#perf_entries[@]} -gt 0 ]]; then
  sorted_perf=()
  while IFS= read -r line; do
    sorted_perf+=("${line}")
  done < <(printf '%s\n' "${perf_entries[@]}" | sort)
  perf_entries=("${sorted_perf[@]}")
fi
if [[ ${#token_entries[@]} -gt 0 ]]; then
  sorted_token=()
  while IFS= read -r line; do
    sorted_token+=("${line}")
  done < <(printf '%s\n' "${token_entries[@]}" | sort)
  token_entries=("${sorted_token[@]}")
fi

if [[ ${#perf_entries[@]} -gt 0 ]]; then
  process_group "performance" "${DEST_PERF}" "${perf_entries[@]}"
fi
if [[ ${#token_entries[@]} -gt 0 ]]; then
  process_group "token" "${DEST_TOKEN}" "${token_entries[@]}"
fi

log ""
if [[ "${matched}" -eq 0 ]]; then
  log "No matching Grafana export files found in ${SOURCE_DIR}."
  log "Expected prefixes:"
  log "  Output Tokens-data"
  log "  Input Tokens-data"
  log "  Token Cache Match Rate"
  log "  Model requests-data"
  log "  Average Latency"
  exit 0
fi

log "Done. matched=${matched} moved=${moved} skipped=${skipped}"
