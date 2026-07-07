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
# With --subproject NAME, writes into token/<subproject>/ or performance/<subproject>/:
#   token/coding-1/input-tokens-YYYY-M-D.csv
#   performance/coding-1/model-requests-YYYY-M-D.csv
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
DATE_FROM_CLI=0
RELOCATE_LEGACY=""
DRY_RUN=0
FORCE=0

usage() {
  cat <<'EOF'
Migrate Grafana CSV exports from Downloads into bills/<project>/.

Options:
  -p, --project NAME   Project folder under bills/ (required)
  -u, --subproject NAME
                       Optional subfolder under token/ or performance/
                       (e.g. token/coding-1/input-tokens-2026-6-30.csv)
  --relocate-legacy SLUG
                       Reorganize flat bills files named *-SLUG-YYYY-M-D.csv into
                       token|performance/<subproject>/ (requires -u; use with -n)
  -d, --date DATE      Date suffix for all output filenames (overrides filename date)
                       If omitted, each file uses the date embedded in its Grafana
                       export name (e.g. ...-data-7_7_2026,... -> 2026-7-7), else today
                       Accepted for --date: YYYY-M-D, YYYY-MM-DD, M_D_YYYY, M/D/YYYY
  -s, --source DIR     Source directory (default: ~/Downloads)
  -b, --bills-dir DIR  Bills root (default: <repo>/bills)
  -n, --dry-run        Preview only: show source -> destination mapping;
                       does not move, rename, or delete any file. Recommended
                       before the first run or when changing --project/--date.
  -f, --force          Overwrite destination if it already exists
  -h, --help           Show this help

Recognized source filename prefixes (optional --subproject subfolder):
  Output Tokens-data*        -> token[/SLUG]/output-tokens-YYYY-M-D.csv
  Input Tokens-data*         -> token[/SLUG]/input-tokens-YYYY-M-D.csv
  Token Cache Match Rate*    -> performance[/SLUG]/cache-match-rate-YYYY-M-D.csv
  Model requests-data*       -> performance[/SLUG]/model-requests-YYYY-M-D.csv
  Average Latency*           -> performance[/SLUG]/avg-latency-YYYY-M-D.csv

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
    --relocate-legacy)
      [[ $# -ge 2 ]] || die "Missing value for $1"
      RELOCATE_LEGACY="$2"
      shift 2
      ;;
    -d|--date)
      [[ $# -ge 2 ]] || die "Missing value for $1"
      DATE_SUFFIX="$2"
      DATE_FROM_CLI=1
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
        die "Unknown option: $1 — broken line continuation? Put nothing after backslash, or use -n on the same line."
      fi
      die "Unknown option: $1 (use --help)"
      ;;
  esac
done

[[ -n "${PROJECT}" ]] || die "Project name is required. Example: --project RG-HK-S56-TATP-QA-Agent"
[[ "${PROJECT}" != *"/"* && "${PROJECT}" != *".."* ]] || die "Invalid project name (no slashes or ..): ${PROJECT}"

SOURCE_DIR="$(cd "${SOURCE_DIR}" 2>/dev/null && pwd || true)"
[[ -n "${SOURCE_DIR}" && -d "${SOURCE_DIR}" ]] || die "Source directory not found: ${SOURCE_DIR}"

resolve_bills_dir() {
  local dir="$1"
  if [[ -d "${dir}" ]]; then
    cd "${dir}" && pwd
    return 0
  fi
  local parent="${dir%/*}"
  local base="${dir##*/}"
  if [[ "${dir}" == "${base}" || -z "${parent}" ]]; then
    mkdir -p "${dir}" 2>/dev/null || return 1
    cd "${dir}" && pwd
    return 0
  fi
  if [[ -d "${parent}" ]]; then
    printf '%s/%s' "$(cd "${parent}" && pwd)" "${base}"
    return 0
  fi
  return 1
}

BILLS_DIR="$(resolve_bills_dir "${BILLS_DIR}" || true)"
[[ -n "${BILLS_DIR}" ]] || die "Bills directory not found (create parent or pass -b): ${BILLS_DIR}"

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
  month="$(date +%m)"
  day="$(date +%d)"
  month="${month#0}"
  day="${day#0}"
  printf '%s-%s-%s' "${year}" "${month}" "${day}"
}

parse_date_from_grafana_name() {
  local name="$1"
  local year month day

  # Match M_D_YYYY anywhere in Grafana export names, e.g.:
  #   ...-data-7_7_2026, ...
  #   ...-data-as-joinbyfield-7_7_2026, ...
  #   Average Latency (Time to Last Byte)-data-7_7_2026, ...
  if [[ "${name}" =~ ([0-9]{1,2})_([0-9]{1,2})_([0-9]{4}) ]]; then
    month="${BASH_REMATCH[1]}"
    day="${BASH_REMATCH[2]}"
    year="${BASH_REMATCH[3]}"
    normalize_date_suffix "${year}-${month}-${day}"
    return 0
  fi
  return 1
}

if [[ "${DATE_FROM_CLI}" -eq 1 ]]; then
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

if [[ -n "${RELOCATE_LEGACY}" ]]; then
  RELOCATE_LEGACY="$(normalize_subproject_slug "${RELOCATE_LEGACY}")"
  [[ -n "${RELOCATE_LEGACY}" ]] || die "Invalid --relocate-legacy slug"
  [[ -n "${SUBPROJECT}" ]] || die "--relocate-legacy requires --subproject (target subfolder name)"
fi

build_dest_name() {
  local file_stem="$1"
  local date_suffix="$2"
  printf '%s-%s.csv' "${file_stem}" "${date_suffix}"
}

classify_file() {
  local name="$1"
  local low
  low="$(printf '%s' "${name}" | tr '[:upper:]' '[:lower:]')"

  case "${low}" in
    output\ tokens-data*)
      printf 'token output-tokens'
      ;;
    input\ tokens-data*)
      printf 'token input-tokens'
      ;;
    token\ cache\ match\ rate*)
      printf 'performance cache-match-rate'
      ;;
    model\ requests-data*)
      printf 'performance model-requests'
      ;;
    average\ latency*)
      printf 'performance avg-latency'
      ;;
    *)
      return 1
      ;;
  esac
}

resolve_dest_date() {
  local src_name="$1"
  if [[ "${DATE_FROM_CLI}" -eq 1 ]]; then
    printf '%s' "${DATE_SUFFIX}"
    return 0
  fi
  local parsed
  parsed="$(parse_date_from_grafana_name "${src_name}" 2>/dev/null || true)"
  if [[ -n "${parsed}" ]]; then
    printf '%s' "${parsed}"
  else
    printf '%s' "${DATE_SUFFIX}"
  fi
}

move_file() {
  local src="$1"
  local dest_dir="$2"
  local dest_name="$3"
  local dest="${dest_dir}/${dest_name}"

  if [[ -e "${dest}" && "${FORCE}" -eq 0 ]]; then
    log "  SKIP (exists): ${dest_name}  <- $(basename "${src}")"
    return 2
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
  return 0
}

process_group() {
  local group_label="$1"
  local dest_dir="$2"
  shift 2
  local -a entries=("$@")
  local entry file_stem src dest_name dest_path target_dir dest_date src_base rc
  local seen_dest_paths=""

  [[ ${#entries[@]} -eq 0 ]] && return 0

  target_dir="${dest_dir}"
  if [[ -n "${SUBPROJECT}" ]]; then
    target_dir="${dest_dir}/${SUBPROJECT}"
  fi

  log "== ${group_label} =="
  log "   -> ${target_dir}"

  for entry in "${entries[@]}"; do
    file_stem="${entry%%|*}"
    src="${entry#*|}"
    src_base="$(basename "${src}")"

    matched=$((matched + 1))
    dest_date="$(resolve_dest_date "${src_base}")"
    dest_name="$(build_dest_name "${file_stem}" "${dest_date}")"
    dest_path="${target_dir}/${dest_name}"

    if printf '%s\n' "${seen_dest_paths}" | grep -Fxq "${dest_path}"; then
      log "  WARN: duplicate destination ${dest_name} (multiple sources map to same path)"
    else
      seen_dest_paths="${seen_dest_paths}${dest_path}"$'\n'
    fi

    move_file "${src}" "${target_dir}" "${dest_name}"
    rc=$?
    if [[ "${rc}" -eq 2 ]]; then
      skipped=$((skipped + 1))
    elif [[ "${rc}" -eq 0 ]]; then
      moved=$((moved + 1))
    fi
  done

  log ""
}

effective_dest_root() {
  local base="$1"
  if [[ -n "${SUBPROJECT}" ]]; then
    printf '%s/%s' "${base}" "${SUBPROJECT}"
  else
    printf '%s' "${base}"
  fi
}

report_no_download_matches() {
  local csv_count=0
  local f base
  shopt -s nullglob
  for f in "${SOURCE_DIR}"/*.csv; do
    [[ -f "${f}" ]] || continue
    csv_count=$((csv_count + 1))
  done

  log "No matching Grafana export files found in ${SOURCE_DIR}."
  if [[ "${csv_count}" -eq 0 ]]; then
    log ""
    log "Downloads has no .csv files. Common causes:"
    log "  1. Grafana exports were already moved by a previous migrate run."
    log "  2. Export again from Grafana (panel menu -> Inspect -> Data -> Download CSV)."
    log "  3. Use -s DIR if files are not in ~/Downloads."
  else
    log ""
    log "Found ${csv_count} .csv file(s) in Downloads, but none matched Grafana panel names:"
    for f in "${SOURCE_DIR}"/*.csv; do
      [[ -f "${f}" ]] || continue
      base="$(basename "${f}")"
      if ! classify_file "${base}" >/dev/null 2>&1; then
        log "  ? ${base}"
      fi
    done
  fi
  log ""
  log "Expected Grafana export name prefixes (case-insensitive):"
  log "  Output Tokens-data*"
  log "  Input Tokens-data*"
  log "  Token Cache Match Rate*"
  log "  Model requests-data*"
  log "  Average Latency*"
  if [[ -n "${SUBPROJECT}" ]]; then
    log ""
    log "If you already migrated with slug-in-filename (e.g. input-tokens-coding-1-2026-7-7.csv),"
    log "reorganize into subfolders instead of re-downloading:"
    log "  ./scripts/migrate-grafana-downloads.sh -p ${PROJECT} -u ${SUBPROJECT} \\"
    log "    --relocate-legacy coding-1 -n"
  fi
}

relocate_legacy_bills_files() {
  local subdir dest_dir src base stem legacy_slug date_suffix dest_name dest_path target_dir
  local -a stems=("input-tokens" "output-tokens" "cache-match-rate" "avg-latency" "model-requests")

  log "Relocate legacy flat files (*-${RELOCATE_LEGACY}-YYYY-M-D.csv) -> subfolder ${SUBPROJECT}/"
  log ""

  for subdir in performance token; do
    dest_dir="${BILLS_DIR}/${PROJECT}/${subdir}"
    target_dir="$(effective_dest_root "${dest_dir}")"
    [[ -d "${dest_dir}" ]] || continue

    for stem in "${stems[@]}"; do
      for src in "${dest_dir}/${stem}-${RELOCATE_LEGACY}-"*.csv; do
        [[ -f "${src}" ]] || continue
        base="$(basename "${src}")"
        if [[ ! "${base}" =~ ^(input-tokens|output-tokens|cache-match-rate|avg-latency|model-requests)-${RELOCATE_LEGACY}-([0-9]{4}-[0-9]{1,2}-[0-9]{1,2})\.csv$ ]]; then
          continue
        fi
        date_suffix="${BASH_REMATCH[2]}"
        dest_name="${stem}-${date_suffix}.csv"
        dest_path="${target_dir}/${dest_name}"

        matched=$((matched + 1))
        move_file "${src}" "${target_dir}" "${dest_name}"
        rc=$?
        if [[ "${rc}" -eq 2 ]]; then
          skipped=$((skipped + 1))
        elif [[ "${rc}" -eq 0 ]]; then
          moved=$((moved + 1))
        fi
      done
    done
  done
}

shopt -s nullglob
matched=0
moved=0
skipped=0

log "Source:  ${SOURCE_DIR}"
log "Project: ${PROJECT}"
[[ -n "${SUBPROJECT}" ]] && log "Subproject: ${SUBPROJECT}"
if [[ "${DATE_FROM_CLI}" -eq 1 ]]; then
  log "Date:    ${DATE_SUFFIX} (from --date, all files)"
else
  log "Date:    per file from Grafana name (*-data-M_D_YYYY,...), fallback ${DATE_SUFFIX}"
fi
log "Dest:    $(effective_dest_root "${DEST_PERF}")"
log "         $(effective_dest_root "${DEST_TOKEN}")"
log "Order:   performance -> token"
[[ "${DRY_RUN}" -eq 1 ]] && log "Mode:    dry-run"
[[ "${FORCE}" -eq 1 ]] && log "Mode:    force overwrite"
log ""

if [[ -n "${RELOCATE_LEGACY}" ]]; then
  relocate_legacy_bills_files
  log ""
  if [[ "${matched}" -eq 0 ]]; then
    log "No legacy flat files matching *-${RELOCATE_LEGACY}-YYYY-M-D.csv under:"
    log "  ${DEST_TOKEN}/"
    log "  ${DEST_PERF}/"
    exit 0
  fi
  log "Done (relocate). matched=${matched} moved=${moved} skipped=${skipped}"
  exit 0
fi

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
  report_no_download_matches
  exit 0
fi

log "Done. matched=${matched} moved=${moved} skipped=${skipped}"
