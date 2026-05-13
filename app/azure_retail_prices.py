from __future__ import annotations

import json
import re
import sqlite3
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterator

from .db import get_connection, init_db

RETAIL_API_BASE = "https://prices.azure.com/api/retail/prices"
# Foundry Models carries Azure OpenAI / GPT retail meters (matches Azure pricing portal data).
OPENAI_RETAIL_FILTER = "serviceName eq 'Foundry Models' and contains(productName,'OpenAI')"
MARKETING_PRICING_URL = "https://azure.microsoft.com/en-us/pricing/details/azure-openai/"
SOURCE_ID = "azure_retail_prices_api"
# Public marketing pages (often HTML). Legacy JSON paths may 404; retail import uses prices.azure.com.
MARKETING_PRICING_API_CANDIDATES = (
    "https://azure.microsoft.com/en-us/pricing/details/azure-openai/",
    "https://azure.microsoft.com/en-us/pricing/api/",
    "https://azure.microsoft.com/en-us/api/pricing/details/azure-openai/",
    "https://azure.microsoft.com/api/pricing/details/azure-openai/",
)

# UI + API whitelist: OData filter suffix (AND …) appended to OPENAI_RETAIL_FILTER.
# Names align with Azure OpenAI marketing tables; rows use Microsoft retail fields (skuName, meterName, …).
RETAIL_SYNC_SERIES: tuple[tuple[str, str, str], ...] = (
    ("all", "All OpenAI meters (Foundry + OpenAI product name)", ""),
    (
        "eastus2_core_models",
        "East US 2 — GPT-4o + GPT-5.1 … GPT-5.5 (retail catalog)",
        " and armRegionName eq 'eastus2' and ("
        "("
        "(contains(skuName,'4o') or contains(meterName,'4o') or contains(tolower(productName),'4o'))"
        " and not (contains(skuName,'5.') or contains(meterName,'5.'))"
        ") or ("
        "(contains(skuName,'5.1') or contains(meterName,'5.1'))"
        " and not (contains(skuName,'5.2') or contains(meterName,'5.2'))"
        " and not (contains(skuName,'5.3') or contains(meterName,'5.3'))"
        " and not (contains(skuName,'5.4') or contains(meterName,'5.4'))"
        " and not (contains(skuName,'5.5') or contains(meterName,'5.5'))"
        ") or ("
        "(contains(skuName,'5.2') or contains(meterName,'5.2'))"
        " and not (contains(skuName,'5.3') or contains(meterName,'5.3'))"
        " and not (contains(skuName,'5.4') or contains(meterName,'5.4'))"
        " and not (contains(skuName,'5.5') or contains(meterName,'5.5'))"
        ") or ("
        "(contains(skuName,'5.3') or contains(meterName,'5.3'))"
        " and not (contains(skuName,'5.4') or contains(meterName,'5.4'))"
        " and not (contains(skuName,'5.5') or contains(meterName,'5.5'))"
        ") or ("
        "(contains(skuName,'5.4') or contains(meterName,'5.4'))"
        " and not (contains(skuName,'5.5') or contains(meterName,'5.5'))"
        ") or ("
        "contains(skuName,'5.5') or contains(meterName,'5.5')"
        ")"
        ")",
    ),
    (
        "eastus2_gpt_51_52",
        "East US 2 — GPT-5.1 + GPT-5.2 (matches pricing page / retail API)",
        " and armRegionName eq 'eastus2' and ("
        "("
        "(contains(skuName,'5.1') or contains(meterName,'5.1'))"
        " and not (contains(skuName,'5.2') or contains(meterName,'5.2'))"
        " and not (contains(skuName,'5.3') or contains(meterName,'5.3'))"
        " and not (contains(skuName,'5.4') or contains(meterName,'5.4'))"
        " and not (contains(skuName,'5.5') or contains(meterName,'5.5'))"
        ") or ("
        "(contains(skuName,'5.2') or contains(meterName,'5.2'))"
        " and not (contains(skuName,'5.3') or contains(meterName,'5.3'))"
        " and not (contains(skuName,'5.4') or contains(meterName,'5.4'))"
        " and not (contains(skuName,'5.5') or contains(meterName,'5.5'))"
        ")"
        ")",
    ),
    (
        "gpt_51_52",
        "GPT-5.1 + GPT-5.2 (all Series / marketing variants; set region below — same catalog as azure.microsoft.com pricing tables)",
        " and ("
        "("
        "(contains(skuName,'5.1') or contains(meterName,'5.1'))"
        " and not (contains(skuName,'5.2') or contains(meterName,'5.2'))"
        " and not (contains(skuName,'5.3') or contains(meterName,'5.3'))"
        " and not (contains(skuName,'5.4') or contains(meterName,'5.4'))"
        " and not (contains(skuName,'5.5') or contains(meterName,'5.5'))"
        ") or ("
        "(contains(skuName,'5.2') or contains(meterName,'5.2'))"
        " and not (contains(skuName,'5.3') or contains(meterName,'5.3'))"
        " and not (contains(skuName,'5.4') or contains(meterName,'5.4'))"
        " and not (contains(skuName,'5.5') or contains(meterName,'5.5'))"
        ")"
        ")",
    ),
    (
        "gpt_55_54",
        "GPT-5.5 + GPT-5.4 (one sync)",
        " and ((contains(skuName,'5.5') or contains(meterName,'5.5')) or (contains(skuName,'5.4') or contains(meterName,'5.4')))",
    ),
    ("gpt_55", "GPT-5.5 (SKU/meter contains 5.5)", " and (contains(skuName,'5.5') or contains(meterName,'5.5'))"),
    ("gpt_54", "GPT-5.4", " and (contains(skuName,'5.4') or contains(meterName,'5.4')) and not (contains(skuName,'5.5') or contains(meterName,'5.5'))"),
    ("gpt_53", "GPT-5.3", " and (contains(skuName,'5.3') or contains(meterName,'5.3')) and not (contains(skuName,'5.4') or contains(meterName,'5.4')) and not (contains(skuName,'5.5') or contains(meterName,'5.5'))"),
    ("gpt_52", "GPT-5.2", " and (contains(skuName,'5.2') or contains(meterName,'5.2')) and not (contains(skuName,'5.3') or contains(meterName,'5.3')) and not (contains(skuName,'5.4') or contains(meterName,'5.4')) and not (contains(skuName,'5.5') or contains(meterName,'5.5'))"),
    (
        "gpt_51",
        "GPT-5.1 family",
        " and (contains(skuName,'5.1') or contains(meterName,'5.1'))"
        " and not (contains(skuName,'5.2') or contains(meterName,'5.2'))"
        " and not (contains(skuName,'5.3') or contains(meterName,'5.3'))"
        " and not (contains(skuName,'5.4') or contains(meterName,'5.4'))"
        " and not (contains(skuName,'5.5') or contains(meterName,'5.5'))",
    ),
    ("gpt_51_codex", "GPT-5.1 Codex only", " and contains(skuName,'5.1') and contains(skuName,'codex')"),
    (
        "gpt_4o",
        "GPT-4o",
        " and (contains(skuName,'4o') or contains(meterName,'4o') or contains(tolower(productName),'4o'))"
        " and not (contains(skuName,'5.') or contains(meterName,'5.'))",
    ),
    ("gpt_5_mini", "GPT-5 mini", " and contains(skuName,'5 mini')"),
    ("gpt_5_nano", "GPT-5 nano", " and contains(skuName,'5 nano')"),
)


def allowed_series_keys() -> frozenset[str]:
    return frozenset(k for k, _, _ in RETAIL_SYNC_SERIES)


def sync_series_options() -> list[dict[str, str]]:
    return [{"key": k, "label": lab} for k, lab, _ in RETAIL_SYNC_SERIES]


def _odata_escape_literal(value: str) -> str:
    return str(value or "").replace("'", "''")


def normalize_arm_region_slug(raw: str | None) -> str | None:
    """Map UI labels to Azure retail `armRegionName` (e.g. eastus2)."""
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    compact = re.sub(r"[\s_-]+", "", s.lower())
    aliases = {
        "eastus2": "eastus2",
        "eastus2region": "eastus2",
    }
    if compact in aliases:
        return aliases[compact]
    if re.fullmatch(r"[a-z][a-z0-9]*", compact):
        return compact
    return None


def append_arm_region_to_filter(expr: str, arm_region: str | None) -> str:
    slug = normalize_arm_region_slug(arm_region)
    if not slug:
        return expr
    frag = f"armRegionName eq '{_odata_escape_literal(slug)}'"
    if frag.lower() in expr.lower():
        return expr
    return f"{expr} and {frag}"


def compose_retail_filter(series_key: str, *, arm_region: str | None = None) -> str:
    if series_key not in allowed_series_keys():
        raise ValueError(f"unsupported series_key: {series_key!r}")
    for k, _, extra in RETAIL_SYNC_SERIES:
        if k == series_key:
            base = OPENAI_RETAIL_FILTER + extra
            return append_arm_region_to_filter(base, arm_region)
    return append_arm_region_to_filter(OPENAI_RETAIL_FILTER, arm_region)


def listing_url_for_filter(filter_expr: str) -> str:
    return f"{RETAIL_API_BASE}?$filter={urllib.parse.quote(filter_expr)}"


def retail_filter_url(series_key: str = "all", *, arm_region: str | None = None) -> str:
    return listing_url_for_filter(compose_retail_filter(series_key, arm_region=arm_region))


def _gpt_51_52_model_sql_fragment() -> str:
    return (
        "( (model_series LIKE '%GPT-5.1%' OR model_name LIKE '%5.1%')"
        " OR (model_series LIKE '%GPT-5.2%' OR model_name LIKE '%5.2%')"
        ")"
        " AND model_series NOT LIKE '%GPT-5.3%'"
        " AND model_series NOT LIKE '%GPT-5.4%'"
        " AND model_series NOT LIKE '%GPT-5.5%'"
    )


def _sql_region_matches_arm_filter(arm_region: str | None) -> str | None:
    """SQL fragment matching `price_region` to an ARM region slug; None = do not filter by region."""
    slug = normalize_arm_region_slug(arm_region)
    if not slug:
        return None
    if slug == "eastus2":
        return (
            "("
            " lower(trim(price_region)) IN ('eastus2','east us 2','eastus 2')"
            " OR price_region LIKE 'East US%2'"
            ")"
        )
    if re.fullmatch(r"[a-z][a-z0-9]*", slug):
        return f"(lower(trim(price_region)) = '{slug}')"
    return None


def delete_sql_clause_for_retail_series(series_key: str, *, arm_region: str | None = None) -> str | None:
    """
    Returns SQL fragment (without WHERE) to match existing retail rows to remove
    before inserting an updated slice. None = delete all retail rows.

    For ``gpt_51_52``, pass ``arm_region`` (e.g. ``eastus2``) so deletes match the
    same geography as the OData filter; omit for all regions.
    """
    if series_key == "all":
        return None
    if series_key == "eastus2_core_models":
        return (
            "source_id = ? AND ("
            " lower(trim(price_region)) IN ('eastus2','east us 2','eastus 2')"
            " OR price_region LIKE 'East US%2'"
            ") AND ("
            " model_series LIKE '%GPT-4o%' OR model_name LIKE '%GPT-4o%'"
            " OR (model_name LIKE '%4o%' AND model_series NOT LIKE '%GPT-5%')"
            " OR model_series LIKE '%GPT-5.1%'"
            " OR model_series LIKE '%GPT-5.2%'"
            " OR model_series LIKE '%GPT-5.3%'"
            " OR model_series LIKE '%GPT-5.4%'"
            " OR model_series LIKE '%GPT-5.5%'"
            ")"
        )
    if series_key == "eastus2_gpt_51_52":
        return (
            "source_id = ? AND ("
            " lower(trim(price_region)) IN ('eastus2','east us 2','eastus 2')"
            " OR price_region LIKE 'East US%2'"
            ") AND ("
            " (model_series LIKE '%GPT-5.1%' OR model_name LIKE '%5.1%')"
            " OR (model_series LIKE '%GPT-5.2%' OR model_name LIKE '%5.2%')"
            ")"
            " AND model_series NOT LIKE '%GPT-5.3%'"
            " AND model_series NOT LIKE '%GPT-5.4%'"
            " AND model_series NOT LIKE '%GPT-5.5%'"
        )
    if series_key == "gpt_51_52":
        model_sql = _gpt_51_52_model_sql_fragment()
        reg_sql = _sql_region_matches_arm_filter(arm_region)
        if reg_sql:
            return f"source_id = ? AND {reg_sql} AND {model_sql}"
        return f"source_id = ? AND {model_sql}"
    if series_key == "gpt_4o":
        return (
            "source_id = ? AND ("
            " model_series LIKE '%GPT-4o%' OR model_name LIKE '%GPT-4o%'"
            " OR (model_name LIKE '%4o%' AND model_series NOT LIKE '%GPT-5%')"
            ")"
        )
    if series_key == "gpt_51":
        return (
            "source_id = ? AND (model_series LIKE '%GPT-5.1%' OR model_name LIKE '%5.1%') "
            "AND model_series NOT LIKE '%GPT-5.2%' AND model_series NOT LIKE '%GPT-5.3%' "
            "AND model_series NOT LIKE '%GPT-5.4%' AND model_series NOT LIKE '%GPT-5.5%'"
        )
    if series_key == "gpt_55_54":
        return (
            "source_id = ? AND ("
            "model_series LIKE '%GPT-5.5%' OR model_series LIKE '%GPT-5.4%' "
            "OR model_name LIKE '%5.5%' OR model_name LIKE '%5.4%'"
            ")"
        )
    if series_key == "gpt_55":
        return "source_id = ? AND (model_series LIKE '%GPT-5.5%' OR model_name LIKE '5.5%')"
    if series_key == "gpt_54":
        return "source_id = ? AND (model_series LIKE '%GPT-5.4%' OR model_name LIKE '5.4%') AND model_series NOT LIKE '%GPT-5.5%' AND model_name NOT LIKE '5.5%'"
    if series_key == "gpt_53":
        return "source_id = ? AND (model_series LIKE '%GPT-5.3%' OR model_name LIKE '5.3%') AND model_series NOT LIKE '%GPT-5.4%' AND model_series NOT LIKE '%GPT-5.5%'"
    if series_key == "gpt_52":
        return "source_id = ? AND (model_series LIKE '%GPT-5.2%' OR model_name LIKE '5.2%') AND model_series NOT LIKE '%GPT-5.3%' AND model_series NOT LIKE '%GPT-5.4%' AND model_series NOT LIKE '%GPT-5.5%'"
    if series_key == "gpt_51_codex":
        return "source_id = ? AND (model_series LIKE '%Codex%' OR model_name LIKE '%codex%') AND (model_name LIKE '5.1%' OR model_series LIKE '%5.1%')"
    if series_key == "gpt_5_mini":
        return "source_id = ? AND (model_name LIKE '5 mini%' OR model_series LIKE '%mini Series%')"
    if series_key == "gpt_5_nano":
        return "source_id = ? AND (model_name LIKE '5 nano%' OR model_series LIKE '%nano Series%')"
    raise ValueError(f"unsupported series_key: {series_key!r}")


def probe_azure_marketing_pricing_endpoints(
    *,
    opener: Callable[[str], Any] | None = None,
    timeout: int = 25,
) -> list[dict[str, Any]]:
    """Read-only checks of Microsoft marketing pricing URLs (often HTML behind CDN)."""
    open_fn = opener or (lambda u: urllib.request.urlopen(u, timeout=timeout))
    out: list[dict[str, Any]] = []
    for url in MARKETING_PRICING_API_CANDIDATES:
        rec: dict[str, Any] = {"url": url}
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json, */*"})
            with open_fn(req) as resp:
                rec["status"] = getattr(resp, "status", None) or resp.getcode()
                ctype = resp.headers.get("Content-Type", "") if hasattr(resp, "headers") else ""
                rec["content_type"] = ctype
                chunk = resp.read(800)
                rec["body_prefix"] = chunk[:200].decode("utf-8", errors="replace")
                rec["looks_like_json"] = chunk.strip()[:1] in (b"{", b"[")
        except Exception as e:
            rec["error"] = str(e)
        out.append(rec)
    return out


def _unique_key(row: tuple[Any, ...]) -> tuple[Any, ...]:
    """Matches UNIQUE(...) columns on model_prices (excluding auto id)."""
    return (
        row[0],
        row[2],
        row[4],
        row[5],
        row[6],
        row[7],
        row[8],
        row[9],
        row[10],
        row[11],
        row[12],
        row[13],
    )


def _dedupe_rows(rows: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    used: set[tuple[Any, ...]] = set()
    out: list[tuple[Any, ...]] = []
    for row in rows:
        r = list(row)
        key = _unique_key(tuple(r))
        if key not in used:
            used.add(key)
            out.append(tuple(r))
            continue
        try:
            mid = str(json.loads(r[19] or "{}").get("retailItem", {}).get("meterId") or "")[:10]
        except Exception:
            mid = ""
        suffix = mid or "meter"
        r[12] = f"{r[12]}__{suffix}"
        key = _unique_key(tuple(r))
        n = 0
        while key in used:
            n += 1
            r[12] = f"{r[12]}_{n}"
            key = _unique_key(tuple(r))
        used.add(key)
        out.append(tuple(r))
    return out


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _effective_date(item: dict[str, Any]) -> str:
    raw = (item.get("effectiveStartDate") or "")[:10]
    return raw if raw else "1970-01-01"


def _parse_metric(sku: str, meter: str) -> str:
    blob = f"{sku} {meter}".lower()
    if re.search(r"\bcd\s*inp", blob) or "batch cd" in blob:
        return "cached_input"
    if re.search(r"\binp\b", blob) or " inp" in blob:
        return "input"
    if re.search(r"\bopt\b", blob) or " opt" in blob:
        return "output"
    if "embedding" in blob:
        return "embedding"
    if "fine" in blob and "tune" in blob:
        return "finetune"
    return "other"


def _parse_billing_mode(sku: str, meter: str) -> str:
    blob = f"{sku} {meter}".lower()
    if "batch" in blob:
        return "batch"
    if re.search(r"(^|[\s_/])pp([\s_/]|$)", blob):
        return "priority"
    if "flex" in blob:
        return "flex"
    return "standard"


def _parse_context_bucket(sku: str, meter: str) -> str | None:
    blob = f"{sku} {meter}".lower()
    if "shortco" in blob:
        return "short_context"
    if "longco" in blob:
        return "long_context"
    return None


def _parse_deployment_scope(sku: str, meter: str) -> str | None:
    blob = f"{sku} {meter}".lower()
    if re.search(r"\bgl$", blob) or blob.endswith(" gl") or " gl " in blob:
        return "global"
    if re.search(r"\bdz$", blob) or blob.endswith(" dz") or " dz " in blob:
        return "data_zone"
    return None


def _infer_model_series(product_name: str, sku_name: str) -> str:
    combined = f"{sku_name} {product_name}".lower()
    if ("4o" in combined or "4-o" in combined) and "5." not in sku_name:
        return "GPT-4o Series"
    s = sku_name.strip()
    if re.match(r"^5\.\d+\s+codex", s, re.I):
        m = re.match(r"^(5\.\d+)\s+codex", s, re.I)
        return f"GPT-{m.group(1)} Codex Series" if m else "GPT Codex Series"
    if re.match(r"^5\.\d+", s):
        m = re.match(r"^(5\.\d+)", s)
        return f"GPT-{m.group(1)} Series" if m else "GPT-5 Series"
    m = re.match(r"^(\d+)\s+mini", s, re.I)
    if m:
        return f"GPT-{m.group(1)} mini Series"
    m = re.match(r"^(\d+(?:\.\d+)?)\s+nano", s, re.I)
    if m:
        return f"GPT-{m.group(1)} nano Series"
    if "codex" in s.lower():
        return "GPT Codex Series"
    if product_name:
        return product_name.strip()
    return "Azure OpenAI"


def _unit_fields(item: dict[str, Any], currency: str) -> tuple[int, str, str]:
    uom = (item.get("unitOfMeasure") or "").strip()
    if uom.upper() == "1M":
        qty = 1_000_000
        expr = f"{currency}/1M tokens"
    elif uom.upper() == "1K":
        qty = 1_000
        expr = f"{currency}/1K tokens"
    elif uom:
        try:
            qty = int(float(uom))
            expr = f"{currency}/{uom} tokens"
        except ValueError:
            qty = 1
            expr = f"{currency}/{uom}"
    else:
        qty = 1
        expr = f"{currency}/unit"
    unit_name = "tokens" if "token" in (item.get("meterName") or "").lower() else "units"
    return qty, unit_name, expr


def _azure_marketing_style_model_name(sku: str, meter: str, product: str) -> str:
    """
    Build a display name closer to Azure OpenAI marketing tables (Model column),
    from retail `skuName` tokens (Gl/Dz → Global/Data Zone, strip meter/billing tails).
    """
    s = (sku or "").strip()
    if not s:
        return (meter or product or "Azure OpenAI")[:160]
    scope = ""
    if re.search(r"\sGl$", s, re.I):
        scope = " Global"
        s = re.sub(r"\sGl$", "", s, flags=re.I).strip()
    elif re.search(r"\sDz$", s, re.I):
        scope = " Data Zone"
        s = re.sub(r"\sDz$", "", s, flags=re.I).strip()
    while True:
        nxt = re.sub(r"\s+(cd\s+)?(inp|opt)$", "", s, flags=re.I).strip()
        if nxt == s:
            break
        s = nxt
    s = re.sub(r"\s+Batch(\s+cd)?(\s+(inp|opt))?$", "", s, flags=re.I).strip()
    s = re.sub(r"\s+PP(\s+(inp|opt))?$", "", s, flags=re.I).strip()
    s = re.sub(r"\s+ShortCo$", "", s, flags=re.I).strip()
    s = re.sub(r"\s+Flex.*$", "", s, flags=re.I).strip()
    s = re.sub(r"\s+Batch$", "", s, flags=re.I).strip()
    if re.match(r"^5\.\d+", s) and not s.lower().startswith("gpt-"):
        s = "GPT-" + s
    elif re.match(r"(?i)^4o", s):
        s = re.sub(r"(?i)^4o", "GPT-4o", s)
    elif "4o" in s.lower() and "5." not in s:
        if not re.match(r"(?i)^gpt", s):
            s = "GPT-4o " + s
    out = (s + scope).strip()
    out = re.sub(r"\s+", " ", out)
    return out[:200] if out else (product or "Azure OpenAI")[:160]


def normalize_retail_item(
    item: dict[str, Any],
    *,
    retrieved_at_utc: str,
    source_listing_url: str,
    marketing_url: str = MARKETING_PRICING_URL,
) -> tuple[Any, ...]:
    sku = str(item.get("skuName") or "").strip()
    meter = str(item.get("meterName") or "").strip()
    product = str(item.get("productName") or "").strip()
    region = str(item.get("armRegionName") or "").strip() or "unknown"
    currency = str(item.get("currencyCode") or "USD").strip()
    amount = float(item.get("retailPrice") or item.get("unitPrice") or 0.0)
    metric = _parse_metric(sku, meter)
    billing = _parse_billing_mode(sku, meter)
    ctx = _parse_context_bucket(sku, meter)
    scope = _parse_deployment_scope(sku, meter)
    series = _infer_model_series(product, sku)
    display_name = _azure_marketing_style_model_name(sku, meter, product)
    qty, unit_name, unit_expr = _unit_fields(item, currency)
    eff = _effective_date(item)
    meter_id = str(item.get("meterId") or "")
    notes = (
        f"Microsoft unit price catalog (prices.azure.com; Foundry Models + OpenAI filter). "
        f"Reference page: {marketing_url} "
        f"meterId={meter_id} skuId={item.get('skuId','')}"
    )
    detail = {
        "retailItem": item,
        "normalized": {
            "metric_name": metric,
            "billing_mode": billing,
            "context_bucket": ctx,
            "deployment_scope": scope,
            "model_series": series,
        },
    }
    row = (
        SOURCE_ID,
        source_listing_url,
        eff,
        retrieved_at_utc,
        "Microsoft",
        "azure-openai",
        region,
        currency,
        series,
        display_name,
        ctx,
        scope,
        billing,
        metric,
        amount,
        qty,
        unit_name,
        unit_expr,
        notes,
        json.dumps(detail, ensure_ascii=False),
    )
    return row


def iter_retail_pages(
    *,
    filter_expr: str = OPENAI_RETAIL_FILTER,
    opener: Callable[[str], Any] | None = None,
) -> Iterator[dict[str, Any]]:
    url: str | None = f"{RETAIL_API_BASE}?$filter={urllib.parse.quote(filter_expr)}"
    open_fn = opener or (lambda u: urllib.request.urlopen(u, timeout=300))
    while url:
        with open_fn(url) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        for it in payload.get("Items") or []:
            yield it
        url = payload.get("NextPageLink")


_INSERT_MODEL_PRICE_SQL = """
        INSERT INTO model_prices(
            source_id, source_url, effective_date, retrieved_at_utc,
            vendor, platform, price_region, price_currency,
            model_series, model_name, context_bucket, deployment_scope,
            billing_mode, metric_name, amount,
            unit_quantity, unit_name, unit_expression, notes, source_detail_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """


def _delete_existing_retail(
    conn: sqlite3.Connection, series_key: str, *, arm_region: str | None = None
) -> int:
    clause = delete_sql_clause_for_retail_series(series_key, arm_region=arm_region)
    if clause is None:
        cur = conn.execute("DELETE FROM model_prices WHERE source_id = ?", (SOURCE_ID,))
    else:
        cur = conn.execute(f"DELETE FROM model_prices WHERE {clause}", (SOURCE_ID,))
    return int(cur.rowcount or 0)


@dataclass(frozen=True)
class RetailImportResult:
    rows_fetched: int
    rows_imported: int
    retail_rows_deleted: int
    retrieved_at_utc: str
    filter_url: str


def import_openai_retail_prices(
    *,
    db_path: str,
    series_key: str = "all",
    arm_region: str | None = None,
    opener: Callable[[str], Any] | None = None,
) -> RetailImportResult:
    if series_key not in allowed_series_keys():
        raise ValueError(f"unsupported series_key: {series_key!r}")
    filter_expr = compose_retail_filter(series_key, arm_region=arm_region)
    listing = listing_url_for_filter(filter_expr)
    retrieved = _iso_utc_now()
    rows: list[tuple[Any, ...]] = []
    for item in iter_retail_pages(filter_expr=filter_expr, opener=opener):
        rows.append(
            normalize_retail_item(
                item,
                retrieved_at_utc=retrieved,
                source_listing_url=listing,
            )
        )

    rows = _dedupe_rows(rows)

    conn = get_connection(db_path)
    try:
        init_db(conn)
        deleted = _delete_existing_retail(conn, series_key, arm_region=arm_region)
        if rows:
            conn.executemany(_INSERT_MODEL_PRICE_SQL, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return RetailImportResult(
        rows_fetched=len(rows),
        rows_imported=len(rows),
        retail_rows_deleted=deleted,
        retrieved_at_utc=retrieved,
        filter_url=listing,
    )
