#!/usr/bin/env bash
# Smoke tests for scripts/migrate-grafana-downloads.sh (run via pytest or directly).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="${ROOT}/scripts/migrate-grafana-downloads.sh"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  local msg="$3"
  [[ "${haystack}" == *"${needle}"* ]] || fail "${msg} (missing: ${needle})"
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  local msg="$3"
  [[ "${haystack}" != *"${needle}"* ]] || fail "${msg} (unexpected: ${needle})"
}

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

src="${tmpdir}/downloads"
bills="${tmpdir}/bills"
mkdir -p "${src}"

# Grafana-style export names (macOS Downloads)
printf '"Time","gpt-4o"\n2026-07-07 00:00:00,1\n' > "${src}/Input Tokens-data-7_7_2026, 5_06_47 PM.csv"
printf '"Time","gpt-4o"\n2026-07-07 00:00:00,2\n' > "${src}/Output Tokens-data-7_7_2026, 5_06_55 PM.csv"
printf '"Time","gpt-4o"\n2026-07-07 00:00:00,3\n' > "${src}/Model requests-data-7_7_2026, 5_04_30 PM.csv"
printf '"Time","gpt-4o"\n2026-07-07 00:00:00,4\n' > "${src}/Average Latency-data-7_7_2026, 5_04_25 PM.csv"
printf '"Time","gpt-4o"\n2026-07-07 00:00:00,5\n' > "${src}/Token Cache Match Rate-data-7_7_2026, 5_04_39 PM.csv"
printf '"Time","gpt-4o"\n2026-07-07 00:00:00,6\n' > "${src}/input tokens-data-7_7_2026, 5_04_39 PM.csv"

out="$("${SCRIPT}" -p proj-flat -s "${src}" -b "${bills}" -n 2>&1)" || fail "dry-run flat failed"
assert_contains "${out}" "token/input-tokens-2026-7-7.csv" "flat token input path"
assert_contains "${out}" "token/output-tokens-2026-7-7.csv" "flat token output path"
assert_contains "${out}" "performance/model-requests-2026-7-7.csv" "flat performance path"
assert_contains "${out}" "performance/avg-latency-2026-7-7.csv" "flat avg latency path"
assert_contains "${out}" "performance/cache-match-rate-2026-7-7.csv" "cache under performance"
assert_contains "${out}" "matched=6" "six grafana files matched (case-insensitive input)"

out_sub="$("${SCRIPT}" -p proj-mdm -u coding-1 -s "${src}" -b "${bills}" -n 2>&1)" || fail "dry-run subproject failed"
assert_contains "${out_sub}" "token/coding-1/input-tokens-2026-7-7.csv" "nested token input"
assert_contains "${out_sub}" "performance/coding-1/model-requests-2026-7-7.csv" "nested performance"
assert_not_contains "${out_sub}" "input-tokens-coding-1-" "no slug in filename"

"${SCRIPT}" -p proj-flat -s "${src}" -b "${bills}" -f >/dev/null
[[ -f "${bills}/proj-flat/token/input-tokens-2026-7-7.csv" ]] || fail "input file not moved"
[[ -f "${bills}/proj-flat/performance/model-requests-2026-7-7.csv" ]] || fail "perf file not moved"
[[ ! -f "${src}/Input Tokens-data-7_7_2026, 5_06_47 PM.csv" ]] || fail "source should be removed after mv"

out_force="$("${SCRIPT}" -p proj-flat -s "${src}" -b "${bills}" -f -n 2>&1)" || true
assert_contains "${out_force}" "No matching Grafana export files found" "sources already moved"

printf '"Time","gpt-4o"\n' > "${src}/Input Tokens-data-6_30_2026, 1_00_00 PM.csv"
out_cli_date="$("${SCRIPT}" -p proj-date -d 2026-6-30 -s "${src}" -b "${bills}" -n 2>&1)"
assert_contains "${out_cli_date}" "input-tokens-2026-6-30.csv" "--date overrides filename date"

# joinbyfield Grafana export names -> date from filename
printf '"Time","gpt-4o"\n' > "${src}/Input Tokens-data-as-joinbyfield-7_7_2026, 11_16_12 AM.csv"
out_join="$("${SCRIPT}" -p proj-join -s "${src}" -b "${bills}" -n 2>&1)"
assert_contains "${out_join}" "input-tokens-2026-7-7.csv" "joinbyfield export date parsed"

# relocate legacy slug-in-filename -> subfolder
legacy_token="${bills}/proj-legacy/token"
legacy_perf="${bills}/proj-legacy/performance"
mkdir -p "${legacy_token}" "${legacy_perf}"
printf 'in\n' > "${legacy_token}/input-tokens-coding-1-2026-7-7.csv"
printf 'out\n' > "${legacy_token}/output-tokens-coding-1-2026-7-7.csv"
printf 'req\n' > "${legacy_perf}/model-requests-coding-1-2026-7-7.csv"
out_reloc="$("${SCRIPT}" -p proj-legacy -u proj-mdm-coding-1-resource --relocate-legacy coding-1 -s "${src}" -b "${bills}" -n 2>&1)"
assert_contains "${out_reloc}" "token/proj-mdm-coding-1-resource/input-tokens-2026-7-7.csv" "relocate legacy token"
assert_contains "${out_reloc}" "performance/proj-mdm-coding-1-resource/model-requests-2026-7-7.csv" "relocate legacy perf"

printf 'All migrate-grafana-downloads checks passed.\n'
