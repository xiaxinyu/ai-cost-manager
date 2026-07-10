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

# cost-analysis Azure billing export -> cost-YYYY-M-D.csv
tree_src="${tmpdir}/downloads-bills"
tree_bills="${tmpdir}/bills-tree"
mkdir -p "${tree_src}/proj-a/token" "${tree_src}/proj-a/performance" \
  "${tree_src}/proj-b/token/sub-a"
printf 'billing\n' > "${tree_src}/proj-a/cost-2026-7-8.csv"
printf 'in\n' > "${tree_src}/proj-a/token/input-tokens-2026-7-8.csv"
printf '"Time","m"\n' > "${tree_src}/proj-a/performance/Model requests-data-7_8_2026, 1_00_00 PM.csv"
printf 'nested\n' > "${tree_src}/proj-b/token/sub-a/output-tokens-2026-7-9.csv"

out_all="$("${SCRIPT}" --all -s "${tree_src}" -b "${tree_bills}" -n 2>&1)" || fail "dry-run --all failed"
assert_contains "${out_all}" "[proj-a]" "all mode project a"
assert_contains "${out_all}" "proj-a/cost-2026-7-8.csv" "billing cost path"
assert_contains "${out_all}" "proj-a/token/input-tokens-2026-7-8.csv" "normalized token path"
assert_contains "${out_all}" "proj-a/performance/model-requests-2026-7-8.csv" "grafana rename in tree"
assert_contains "${out_all}" "proj-b/token/sub-a/output-tokens-2026-7-9.csv" "nested subproject path"
assert_contains "${out_all}" "matched=4" "four files in tree sync"

"${SCRIPT}" --all -s "${tree_src}" -b "${tree_bills}" -f >/dev/null
[[ -f "${tree_bills}/proj-a/cost-2026-7-8.csv" ]] || fail "tree billing not copied"
[[ -f "${tree_bills}/proj-a/performance/model-requests-2026-7-8.csv" ]] || fail "tree grafana not copied"
[[ -f "${tree_src}/proj-a/cost-2026-7-8.csv" ]] || fail "copy mode should keep source"

mkdir -p "${tree_src}/techlab-aiops-gpt5.1"
printf '"UsageDate","ResourceId","ResourceType","ResourceLocation","ResourceGroupName","ServiceName","ServiceTier","Meter","CostUSD","Cost","Currency"\n' > "${tree_src}/techlab-aiops-gpt5.1/cost-analysis (2).csv"
printf '"2026-07-07","/subscriptions/x/resourcegroups/techlab-aiops-gpt5.1/providers/microsoft.cognitiveservices/accounts/res","microsoft.cognitiveservices/accounts","US East 2","techlab-aiops-gpt5.1","Foundry Models","Azure OpenAI GPT5","meter","1.00","1.00","USD"\n' >> "${tree_src}/techlab-aiops-gpt5.1/cost-analysis (2).csv"
printf '"2026-07-09","/subscriptions/x/resourcegroups/techlab-aiops-gpt5.1/providers/microsoft.cognitiveservices/accounts/res","microsoft.cognitiveservices/accounts","US East 2","techlab-aiops-gpt5.1","Foundry Models","Azure OpenAI GPT5","meter","2.00","2.00","USD"\n' >> "${tree_src}/techlab-aiops-gpt5.1/cost-analysis (2).csv"

out_cost="$("${SCRIPT}" -p techlab-aiops-gpt5.1 -s "${tree_src}" -b "${tree_bills}" -n 2>&1)" || fail "cost-analysis dry-run failed"
assert_contains "${out_cost}" "billing rename" "cost-analysis labeled as billing rename"
assert_contains "${out_cost}" "techlab-aiops-gpt5.1/cost-2026-7-9.csv" "cost-analysis uses max UsageDate"
assert_not_contains "${out_cost}" "unrecognized: cost-analysis" "cost-analysis should be recognized"

"${SCRIPT}" -p techlab-aiops-gpt5.1 -s "${tree_src}" -b "${tree_bills}" -f >/dev/null
[[ -f "${tree_bills}/techlab-aiops-gpt5.1/cost-2026-7-9.csv" ]] || fail "cost-analysis not synced"
[[ -d "${tree_bills}/techlab-aiops-gpt5.1/token" ]] || fail "token dir should be created"
[[ -d "${tree_bills}/techlab-aiops-gpt5.1/performance" ]] || fail "performance dir should be created"

flat_dl="${tmpdir}/flat-downloads"
mkdir -p "${flat_dl}"
printf '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n"2026-07-07","1.00","1.00","","USD"\n' > "${flat_dl}/cost-analysis (1).csv"

out_summary="$("${SCRIPT}" --all -s "${tree_src}" -b "${tree_bills}" --flat-downloads "${flat_dl}" -n 2>&1)" || fail "summary cost-analysis dry-run failed"
assert_contains "${out_summary}" "[flat] skipped cost-analysis (1).csv" "summary flat file skipped without project"
assert_contains "${out_summary}" "pass -p <project> --flat-downloads" "flat skip hint"

out_no_flat="$("${SCRIPT}" --all -s "${tree_src}" -b "${tree_bills}" -n 2>&1)" || fail "dry-run without flat failed"
assert_not_contains "${out_no_flat}" "flat cost-analysis" "--all should not scan ~/Downloads without --flat-downloads"

printf 'All migrate-grafana-downloads checks passed.\n'
