#!/usr/bin/env bash
# Sync Grafana export CSVs from ~/Downloads/bills into <repo>/bills/.
#
# Two source layouts are supported:
#   1. Bills tree (default): ~/Downloads/bills/<project>/{cost-*.csv,token/,performance/,...}
#   2. Flat Downloads (legacy): ~/Downloads/*.csv with Grafana panel export names
#
# Grafana exports are renamed to repo conventions:
#   token/input-tokens-YYYY-M-D.csv
#   token/output-tokens-YYYY-M-D.csv
#   performance/cache-match-rate-YYYY-M-D.csv
#   performance/model-requests-YYYY-M-D.csv
#   performance/avg-latency-YYYY-M-D.csv
#
# Already-normalized files (cost-*.csv, input-tokens-*.csv, ...) are copied with the same
# relative path under bills/<project>/.
#
# Azure cost-analysis exports (cost-analysis.csv, cost-analysis (1).csv, ...) are renamed to
# bills/<project>/cost-YYYY-M-D.csv using the latest UsageDate in the CSV (or --date).
#
# Usage:
#   ./scripts/migrate-grafana-downloads.sh --all
#   ./scripts/migrate-grafana-downloads.sh --all --dry-run
#   ./scripts/migrate-grafana-downloads.sh -p techlab-aiops-gpt5.1
#   ./scripts/migrate-grafana-downloads.sh -p RG-HK-S56-TATP-QA-Agent -s ~/Downloads -n
#   ./scripts/migrate-grafana-downloads.sh -p techlab-aimas-marketing -u gpt-5.4 -d 2026-6-30
#   ./scripts/migrate-grafana-downloads.sh -p RG-HK-S56-MDM-Coding -u proj-mdm-coding-1-resource \
#     --relocate-legacy coding-1 -n

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SOURCE_DIR="${HOME}/Downloads/bills"
BILLS_DIR="${REPO_ROOT}/bills"
DEFAULT_SOURCE_DIR="${HOME}/Downloads/bills"
PROJECT=""
SUBPROJECT=""
DATE_SUFFIX=""
DATE_FROM_CLI=0
RELOCATE_LEGACY=""
DRY_RUN=0
FORCE=0
SYNC_ALL=0
COPY_MODE=1
LOG_FILE=""
LOG_AUTO=0
FLAT_DOWNLOADS_DIR="${HOME}/Downloads"
SCAN_FLAT_DOWNLOADS=0

matched=0
synced=0
skipped=0
warnings=0
errors=0
PROJECT_LAYOUT_DONE=()

usage() {
  cat <<'EOF'
Sync Grafana / billing CSVs from ~/Downloads/bills into <repo>/bills/.

Options:
  -a, --all            Sync every project subdirectory under the source bills tree
                       (default source: ~/Downloads/bills). Implies copy mode.
  -p, --project NAME   Sync one project folder (required unless --all)
  -u, --subproject NAME
                       Optional subfolder under token/ or performance/ for Grafana
                       exports (flat Downloads mode, or when overriding path)
  --relocate-legacy SLUG
                       Reorganize flat bills files named *-SLUG-YYYY-M-D.csv into
                       token|performance/<subproject>/ (requires -u; use with -n)
  -d, --date DATE      Date suffix for Grafana output filenames (overrides filename date)
  -s, --source DIR     Source directory (default: ~/Downloads/bills)
  -b, --bills-dir DIR  Destination bills root (default: <repo>/bills)
  --log-file PATH      Append structured logs to PATH ("auto" -> logs/migrate-bills-*.log)
  --flat-downloads DIR Also scan DIR/cost-analysis*.csv (opt-in; default: ~/Downloads)
  --move               Move source files instead of copy (legacy flat Downloads behavior)
  -n, --dry-run        Preview only; no files are copied or moved
  -f, --force          Overwrite destination when it already exists
  -h, --help           Show this help

Modes:
  Bills tree sync (default):
    Scans SOURCE/<project>/ recursively for .csv files.
    Normalized files keep their relative path (token/, performance/, nested subprojects).
    Grafana export names are classified and renamed into token/ or performance/.
    cost-analysis*.csv exports are renamed to cost-YYYY-M-D.csv at project root.
    New project / token / performance directories are created under bills/ when needed.

  Flat Downloads (legacy):
    Use -s ~/Downloads with -p PROJECT when Grafana CSVs sit directly in Downloads.
    Optional: --flat-downloads scans ~/Downloads/cost-analysis*.csv and routes by
    ResourceGroupName when present, or -p <project> when not.

Examples:
  ./scripts/migrate-grafana-downloads.sh --all -n
  ./scripts/migrate-grafana-downloads.sh --all --log-file auto
  ./scripts/migrate-grafana-downloads.sh -p techlab-aiops-gpt5.1
  ./scripts/migrate-grafana-downloads.sh -p RG-HK-S56-TATP-QA-Agent -s ~/Downloads --move -f
EOF
}

timestamp() {
  date '+%Y-%m-%d %H:%M:%S'
}

log_write() {
  local level="$1"
  shift
  local line="[$(timestamp)] [${level}] $*"
  printf '%s\n' "${line}"
  if [[ -n "${LOG_FILE}" ]]; then
    printf '%s\n' "${line}" >> "${LOG_FILE}"
  fi
}

log() {
  log_write INFO "$@"
}

log_warn() {
  warnings=$((warnings + 1))
  log_write WARN "$@"
}

log_skip() {
  log_write SKIP "$@"
}

log_sync() {
  log_write SYNC "$@"
}

log_error() {
  errors=$((errors + 1))
  log_write ERROR "$@"
}

die() {
  log_error "$*"
  exit 1
}

init_log_file() {
  if [[ "${LOG_AUTO}" -eq 1 && -z "${LOG_FILE}" ]]; then
    mkdir -p "${REPO_ROOT}/logs"
    LOG_FILE="${REPO_ROOT}/logs/migrate-bills-$(date '+%Y%m%d-%H%M%S').log"
  fi
  if [[ -n "${LOG_FILE}" ]]; then
    mkdir -p "$(dirname "${LOG_FILE}")"
    {
      printf '\n=== migrate-grafana-downloads %s ===\n' "$(timestamp)"
      printf 'source=%s dest=%s mode=%s dry_run=%s force=%s\n' \
        "${SOURCE_DIR}" "${BILLS_DIR}" \
        "$( [[ "${SYNC_ALL}" -eq 1 ]] && printf all || printf project:${PROJECT} )" \
        "${DRY_RUN}" "${FORCE}"
    } >> "${LOG_FILE}"
    log "Log file: ${LOG_FILE}"
  fi
}

while [[ $# -gt 0 ]]; do
  if [[ -z "${1//[[:space:]]/}" ]]; then
    shift
    continue
  fi
  case "$1" in
    -a|--all)
      SYNC_ALL=1
      shift
      ;;
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
    --log-file)
      [[ $# -ge 2 ]] || die "Missing value for $1"
      if [[ "$2" == "auto" ]]; then
        LOG_AUTO=1
        LOG_FILE=""
      else
        LOG_FILE="$2"
      fi
      shift 2
      ;;
    --flat-downloads)
      [[ $# -ge 2 ]] || die "Missing value for $1"
      FLAT_DOWNLOADS_DIR="$2"
      SCAN_FLAT_DOWNLOADS=1
      shift 2
      ;;
    --move)
      COPY_MODE=0
      shift
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
      die "Unknown option: $1 (use --help)"
      ;;
  esac
done

if [[ "${SYNC_ALL}" -eq 0 ]]; then
  [[ -n "${PROJECT}" ]] || die "Project name is required unless --all is used."
fi
if [[ -n "${PROJECT}" ]]; then
  [[ "${PROJECT}" != *"/"* && "${PROJECT}" != *".."* ]] || die "Invalid project name: ${PROJECT}"
fi

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
  [[ -n "${SUBPROJECT}" ]] || die "Invalid --subproject value"
fi

if [[ -n "${RELOCATE_LEGACY}" ]]; then
  RELOCATE_LEGACY="$(normalize_subproject_slug "${RELOCATE_LEGACY}")"
  [[ -n "${RELOCATE_LEGACY}" ]] || die "Invalid --relocate-legacy slug"
  [[ -n "${SUBPROJECT}" ]] || die "--relocate-legacy requires --subproject"
  [[ -n "${PROJECT}" ]] || die "--relocate-legacy requires --project"
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

is_ignored_source_name() {
  local name="$1"
  [[ "${name}" == .DS_Store ]] && return 0
  [[ "${name}" == ._* ]] && return 0
  return 1
}

is_skipped_project_name() {
  local name="$1"
  local low
  low="$(printf '%s' "${name}" | tr '[:upper:]' '[:lower:]')"
  case "${low}" in
    price|prices|.""|"..") return 0 ;;
  esac
  [[ "${name}" == .* ]] && return 0
  return 1
}

is_normalized_billing_file() {
  local rel="$1"
  local base="${rel##*/}"
  [[ "${rel}" == */* ]] && return 1
  [[ "${base}" =~ ^cost-[0-9]{4}-[0-9]{1,2}(-[0-9]{1,2})?\.csv$ ]] && return 0
  [[ "${base}" =~ ^cost-[0-9]{4}\.csv$ ]] && return 0
  return 1
}

is_cost_analysis_file() {
  local base="$1"
  local low
  low="$(printf '%s' "${base}" | tr '[:upper:]' '[:lower:]')"
  [[ "${low}" =~ ^cost-analysis(\ \([0-9]+\))?\.csv$ ]]
}

parse_max_usage_date_from_csv() {
  local src_abs="$1"
  [[ -f "${src_abs}" ]] || return 1
  awk -F',' '
    NR == 1 {
      col = 0
      for (i = 1; i <= NF; i++) {
        gsub(/"/, "", $i)
        if (tolower($i) == "usagedate") col = i
      }
      next
    }
    col > 0 {
      gsub(/"/, "", $col)
      if ($col ~ /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/) print $col
    }
  ' "${src_abs}" | sort | tail -1
}

parse_resource_group_from_csv() {
  local src_abs="$1"
  [[ -f "${src_abs}" ]] || return 1
  awk -F',' '
    NR == 1 {
      col = 0
      for (i = 1; i <= NF; i++) {
        gsub(/"/, "", $i)
        if (tolower($i) == "resourcegroupname") col = i
      }
      next
    }
    col > 0 && NR == 2 {
      gsub(/"/, "", $col)
      if ($col != "") {
        print $col
        exit
      }
    }
  ' "${src_abs}"
}

lookup_project_for_resource_group() {
  local rg="$1"
  local rg_low dir base low
  [[ -n "${rg}" ]] || return 1
  rg_low="$(printf '%s' "${rg}" | tr '[:upper:]' '[:lower:]')"
  for dir in "${SOURCE_DIR}"/* "${BILLS_DIR}"/*; do
    [[ -d "${dir}" ]] || continue
    base="$(basename "${dir}")"
    is_skipped_project_name "${base}" && continue
    low="$(printf '%s' "${base}" | tr '[:upper:]' '[:lower:]')"
    if [[ "${low}" == "${rg_low}" ]]; then
      printf '%s' "${base}"
      return 0
    fi
  done
  printf '%s' "${rg}"
}

resolve_cost_analysis_date() {
  local src_abs="$1"
  local max_date parsed
  if [[ "${DATE_FROM_CLI}" -eq 1 ]]; then
    printf '%s' "${DATE_SUFFIX}"
    return 0
  fi
  max_date="$(parse_max_usage_date_from_csv "${src_abs}" 2>/dev/null || true)"
  if [[ -n "${max_date}" ]]; then
    parsed="$(normalize_date_suffix "${max_date}" 2>/dev/null || true)"
    if [[ -n "${parsed}" ]]; then
      printf '%s' "${parsed}"
      return 0
    fi
  fi
  printf '%s' "${DATE_SUFFIX}"
}

resolve_cost_analysis_dest_rel() {
  local src_abs="$1"
  local date_suffix dest_name
  date_suffix="$(resolve_cost_analysis_date "${src_abs}")"
  dest_name="cost-${date_suffix}.csv"
  printf '%s' "${dest_name}"
}

ensure_project_layout() {
  local project_name="$1"
  local dest_root="${BILLS_DIR}/${project_name}"
  local sub d done_name created=0

  for done_name in "${PROJECT_LAYOUT_DONE[@]+"${PROJECT_LAYOUT_DONE[@]}"}"; do
    [[ "${done_name}" == "${project_name}" ]] && return 0
  done
  PROJECT_LAYOUT_DONE+=("${project_name}")

  for sub in "" token performance; do
    d="${dest_root}"
    if [[ -n "${sub}" ]]; then
      d="${dest_root}/${sub}"
    fi
    if [[ ! -d "${d}" ]]; then
      created=1
      if [[ "${DRY_RUN}" -eq 1 ]]; then
        log "would create directory: ${d}/"
      else
        mkdir -p "${d}"
        log "created directory: ${d}/"
      fi
    fi
  done

  if [[ "${created}" -eq 1 ]]; then
    log "[${project_name}] initialized project layout under ${dest_root}/"
  fi
}

is_normalized_token_metric_file() {
  local rel="$1"
  local base="${rel##*/}"
  local low
  low="$(printf '%s' "${base}" | tr '[:upper:]' '[:lower:]')"
  [[ "${low}" == input-tokens-* ]] && return 0
  [[ "${low}" == output-tokens-* ]] && return 0
  [[ "${low}" == cache-match-rate-* ]] && return 0
  [[ "${low}" == model-requests-* ]] && return 0
  [[ "${low}" == avg-latency-* ]] && return 0
  return 1
}

is_valid_normalized_rel() {
  local rel="$1"
  is_normalized_billing_file "${rel}" && return 0
  [[ "${rel}" == token/* || "${rel}" == performance/* ]] || return 1
  is_normalized_token_metric_file "${rel}"
}

subproject_from_source_rel() {
  local rel="$1"
  if [[ "${rel}" =~ ^(token|performance)/([^/]+)/.+ ]]; then
    local seg="${BASH_REMATCH[2]}"
    case "${seg}" in
      input-tokens*|output-tokens*|cache-match-rate*|model-requests*|avg-latency*)
        return 1
        ;;
      *)
        printf '%s' "${seg}"
        return 0
        ;;
    esac
  fi
  return 1
}

resolve_grafana_dest_rel() {
  local src_rel="$1"
  local src_base="$2"
  local kind_and_stem dest_subdir file_stem dest_date dest_name subproj=""

  kind_and_stem="$(classify_file "${src_base}" 2>/dev/null || true)"
  [[ -n "${kind_and_stem}" ]] || return 1

  read -r dest_subdir file_stem <<<"${kind_and_stem}"
  dest_date="$(resolve_dest_date "${src_base}")"
  dest_name="$(build_dest_name "${file_stem}" "${dest_date}")"

  if [[ -n "${SUBPROJECT}" ]]; then
    subproj="${SUBPROJECT}"
  else
    subproj="$(subproject_from_source_rel "${src_rel}" 2>/dev/null || true)"
  fi

  if [[ -n "${subproj}" ]]; then
    printf '%s/%s/%s' "${dest_subdir}" "${subproj}" "${dest_name}"
  else
    printf '%s/%s' "${dest_subdir}" "${dest_name}"
  fi
}

resolve_dest_rel() {
  local src_rel="$1"
  local src_base="$2"
  local src_abs="$3"
  local grafana_rel cost_rel=""

  if is_cost_analysis_file "${src_base}"; then
    cost_rel="$(resolve_cost_analysis_dest_rel "${src_abs}")"
    [[ -n "${cost_rel}" ]] && printf '%s' "${cost_rel}" && return 0
  fi

  if is_valid_normalized_rel "${src_rel}"; then
    printf '%s' "${src_rel}"
    return 0
  fi

  grafana_rel="$(resolve_grafana_dest_rel "${src_rel}" "${src_base}" 2>/dev/null || true)"
  if [[ -n "${grafana_rel}" ]]; then
    printf '%s' "${grafana_rel}"
    return 0
  fi

  return 1
}

sync_file_to_dest() {
  local src="$1"
  local dest="$2"
  local label="$3"

  matched=$((matched + 1))

  if [[ -e "${dest}" && "${FORCE}" -eq 0 ]]; then
    if cmp -s "${src}" "${dest}" 2>/dev/null; then
      skipped=$((skipped + 1))
      log_skip "${label}: unchanged ${dest}"
      return 0
    fi
    skipped=$((skipped + 1))
    log_skip "${label}: exists ${dest} (use --force to overwrite)"
    return 0
  fi

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log_sync "${label}: ${src} -> ${dest}"
    synced=$((synced + 1))
    return 0
  fi

  mkdir -p "$(dirname "${dest}")"
  if [[ "${COPY_MODE}" -eq 1 ]]; then
    cp -p "${src}" "${dest}"
    log_sync "${label}: copied $(basename "${src}") -> ${dest}"
  else
    mv "${src}" "${dest}"
    log_sync "${label}: moved $(basename "${src}") -> ${dest}"
  fi
  synced=$((synced + 1))
  return 0
}

process_tree_csv() {
  local project_name="$1"
  local src_abs="$2"
  local src_rel="$3"
  local src_base dest_rel dest_abs label

  src_base="$(basename "${src_abs}")"
  if is_ignored_source_name "${src_base}"; then
    return 0
  fi

  dest_rel="$(resolve_dest_rel "${src_rel}" "${src_base}" "${src_abs}" 2>/dev/null || true)"
  if [[ -z "${dest_rel}" ]]; then
    log_warn "[${project_name}] unrecognized: ${src_rel}"
    return 0
  fi

  ensure_project_layout "${project_name}"
  dest_abs="${BILLS_DIR}/${project_name}/${dest_rel}"
  if is_cost_analysis_file "${src_base}"; then
    label="[${project_name}] billing rename"
  elif classify_file "${src_base}" >/dev/null 2>&1; then
    label="[${project_name}] rename"
  else
    label="[${project_name}]"
  fi
  sync_file_to_dest "${src_abs}" "${dest_abs}" "${label}"
}

process_flat_cost_analysis() {
  local src_abs="$1"
  local src_base="$2"
  local rg project_name dest_rel dest_abs label

  if is_ignored_source_name "${src_base}"; then
    return 0
  fi
  if ! is_cost_analysis_file "${src_base}"; then
    return 0
  fi

  rg="$(parse_resource_group_from_csv "${src_abs}" 2>/dev/null || true)"
  if [[ -z "${rg}" ]]; then
    if [[ -n "${PROJECT}" ]]; then
      project_name="${PROJECT}"
      log "[flat] ${src_base}: using --project ${project_name}"
    else
      log "[flat] skipped ${src_base}: move to ~/Downloads/bills/<project>/ and run --all, or pass -p <project> --flat-downloads"
      return 0
    fi
  else
    project_name="$(lookup_project_for_resource_group "${rg}")"
    log "[flat] ResourceGroupName=${rg} -> project ${project_name}"
  fi

  dest_rel="$(resolve_cost_analysis_dest_rel "${src_abs}")"
  ensure_project_layout "${project_name}"
  dest_abs="${BILLS_DIR}/${project_name}/${dest_rel}"
  label="[${project_name}] billing rename (flat:${src_base})"
  sync_file_to_dest "${src_abs}" "${dest_abs}" "${label}"
}

scan_flat_cost_analysis_files() {
  local f src_base
  shopt -s nullglob
  local -a files=()

  if [[ "${SCAN_FLAT_DOWNLOADS}" -eq 0 ]]; then
    return 0
  fi

  [[ -d "${FLAT_DOWNLOADS_DIR}" ]] || return 0

  for f in "${FLAT_DOWNLOADS_DIR}"/cost-analysis*.csv; do
    [[ -f "${f}" ]] || continue
    files+=("${f}")
  done

  [[ ${#files[@]} -eq 0 ]] && return 0

  log ""
  log "---- flat cost-analysis: ${FLAT_DOWNLOADS_DIR} ----"
  log "discovered ${#files[@]} cost-analysis file(s)"
  for f in "${files[@]}"; do
    process_flat_cost_analysis "${f}" "$(basename "${f}")"
  done
}

scan_project_tree() {
  local project_name="$1"
  local project_src="$2"
  local -a found=()
  local rel src_abs

  if [[ ! -d "${project_src}" ]]; then
    log_warn "Project source missing, skipped: ${project_src}"
    return 0
  fi

  log ""
  log "---- project: ${project_name} ----"
  log "source: ${project_src}"
  log "dest:   ${BILLS_DIR}/${project_name}/"

  while IFS= read -r -d '' src_abs; do
    rel="${src_abs#"${project_src}/"}"
    found+=("${rel}")
  done < <(find "${project_src}" -type f -name '*.csv' -print0 | sort -z)

  if [[ ${#found[@]} -eq 0 ]]; then
    log_warn "[${project_name}] no .csv files found"
    return 0
  fi

  log "[${project_name}] discovered ${#found[@]} csv file(s)"
  local item
  for item in "${found[@]}"; do
    process_tree_csv "${project_name}" "${project_src}/${item}" "${item}"
  done
}

sync_all_projects() {
  local entry project_name project_src count=0

  shopt -s nullglob
  for entry in "${SOURCE_DIR}"/*; do
    [[ -d "${entry}" ]] || continue
    project_name="$(basename "${entry}")"
    is_skipped_project_name "${project_name}" && continue
    count=$((count + 1))
    scan_project_tree "${project_name}" "${entry}"
  done

  scan_flat_cost_analysis_files

  if [[ "${count}" -eq 0 && "${matched}" -eq 0 ]]; then
    log_warn "No project subdirectories found under ${SOURCE_DIR}"
  fi
}

uses_bills_tree_mode() {
  if [[ "${SYNC_ALL}" -eq 1 ]]; then
    return 0
  fi
  if [[ -n "${PROJECT}" && -d "${SOURCE_DIR}/${PROJECT}" ]]; then
    return 0
  fi
  return 1
}

effective_dest_root() {
  local base="$1"
  if [[ -n "${SUBPROJECT}" ]]; then
    printf '%s/%s' "${base}" "${SUBPROJECT}"
  else
    printf '%s' "${base}"
  fi
}

move_file() {
  local src="$1"
  local dest_dir="$2"
  local dest_name="$3"
  local dest="${dest_dir}/${dest_name}"
  sync_file_to_dest "${src}" "${dest}" "flat"
}

process_group() {
  local group_label="$1"
  local dest_dir="$2"
  shift 2
  local -a entries=("$@")
  local entry file_stem src dest_name dest_path target_dir dest_date src_base
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

    dest_date="$(resolve_dest_date "${src_base}")"
    dest_name="$(build_dest_name "${file_stem}" "${dest_date}")"
    dest_path="${target_dir}/${dest_name}"

    if printf '%s\n' "${seen_dest_paths}" | grep -Fxq "${dest_path}"; then
      log_warn "duplicate destination ${dest_name}"
    else
      seen_dest_paths="${seen_dest_paths}${dest_path}"$'\n'
    fi

    move_file "${src}" "${target_dir}" "${dest_name}" || true
  done

  log ""
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
    log "Source has no top-level .csv files."
    log "For bills tree sync, place files under ${SOURCE_DIR}/<project>/ or run with --all."
  else
    log "Found ${csv_count} top-level .csv file(s), but none matched Grafana panel names:"
    for f in "${SOURCE_DIR}"/*.csv; do
      [[ -f "${f}" ]] || continue
      base="$(basename "${f}")"
      if ! classify_file "${base}" >/dev/null 2>&1; then
        log "  ? ${base}"
      fi
    done
  fi
}

relocate_legacy_bills_files() {
  local subdir dest_dir src base stem date_suffix dest_name target_dir
  local -a stems=("input-tokens" "output-tokens" "cache-match-rate" "avg-latency" "model-requests")
  local DEST_TOKEN="${BILLS_DIR}/${PROJECT}/token"
  local DEST_PERF="${BILLS_DIR}/${PROJECT}/performance"

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
        move_file "${src}" "${target_dir}" "${dest_name}" || true
      done
    done
  done
}

process_flat_downloads() {
  local DEST_TOKEN="${BILLS_DIR}/${PROJECT}/token"
  local DEST_PERF="${BILLS_DIR}/${PROJECT}/performance"
  local -a perf_entries=() token_entries=()
  local src base kind_and_stem dest_subdir file_stem entry

  shopt -s nullglob
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
    local sorted_perf=()
    while IFS= read -r line; do
      sorted_perf+=("${line}")
    done < <(printf '%s\n' "${perf_entries[@]}" | sort)
    process_group "performance" "${DEST_PERF}" "${sorted_perf[@]}"
  fi
  if [[ ${#token_entries[@]} -gt 0 ]]; then
    local sorted_token=()
    while IFS= read -r line; do
      sorted_token+=("${line}")
    done < <(printf '%s\n' "${token_entries[@]}" | sort)
    process_group "token" "${DEST_TOKEN}" "${sorted_token[@]}"
  fi

  if [[ "${matched}" -eq 0 ]]; then
    report_no_download_matches
  fi
}

print_summary() {
  log ""
  log "======== summary ========"
  log "matched=${matched} synced=${synced} skipped=${skipped} warnings=${warnings} errors=${errors}"
  if [[ -n "${LOG_FILE}" ]]; then
    log "log file: ${LOG_FILE}"
  fi
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    log "mode: dry-run (no files changed)"
  elif [[ "${COPY_MODE}" -eq 1 ]]; then
    log "mode: copy (source preserved)"
  else
    log "mode: move (source removed on success)"
  fi
}

init_log_file

log "Source:  ${SOURCE_DIR}"
log "Dest:    ${BILLS_DIR}"
if [[ "${SYNC_ALL}" -eq 1 ]]; then
  log "Scope:   all projects"
else
  log "Project: ${PROJECT}"
fi
[[ -n "${SUBPROJECT}" ]] && log "Subproject override: ${SUBPROJECT}"
if [[ "${DATE_FROM_CLI}" -eq 1 ]]; then
  log "Date:    ${DATE_SUFFIX} (from --date)"
else
  log "Date:    per file (Grafana name / cost-analysis UsageDate), fallback ${DATE_SUFFIX}"
fi
[[ "${DRY_RUN}" -eq 1 ]] && log "Dry-run: yes"
[[ "${FORCE}" -eq 1 ]] && log "Force:   yes"

if [[ -n "${RELOCATE_LEGACY}" ]]; then
  COPY_MODE=0
  relocate_legacy_bills_files
  print_summary
  exit 0
fi

if uses_bills_tree_mode; then
  if [[ "${SYNC_ALL}" -eq 1 ]]; then
    sync_all_projects
  else
    scan_project_tree "${PROJECT}" "${SOURCE_DIR}/${PROJECT}"
  fi
else
  COPY_MODE=0
  process_flat_downloads
fi

print_summary

if [[ "${errors}" -gt 0 ]]; then
  exit 1
fi
