"""
Map Azure Foundry billing ``Meter`` strings to imported token CSV column names.

Examples
--------
- ``5.3 codex inp Gl 1M Tokens``  → ``gpt-5.3-codex`` / input
- ``5.3 codex opt Gl 1M Tokens``  → ``gpt-5.3-codex`` / output
- ``5.3 codex cd inp Gl 1M Tokens`` → ``gpt-5.3-codex`` / cached_input (rolled into input bucket)
- ``5.4 inp Gl 1M Tokens``        → ``gpt-5.4`` / input
- ``5.4 opt Gl 1M Tokens``        → ``gpt-5.4`` / output
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

# version [codex] [cd] inp|opt  (suffix "Gl 1M Tokens" optional)
_FOUNDRY_METER_RE = re.compile(
    r"^\s*(?P<version>\d+(?:\.\d+)?)\s+"
    r"(?:(?P<family>codex)\s+)?"
    r"(?:(?P<cached>cd)\s+)?"
    r"(?P<dir>inp|opt)\b",
    re.IGNORECASE,
)
_METER_TOKEN_RE = re.compile(r"[a-z0-9.]+", re.IGNORECASE)
_MODEL_VERSION_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)")
_MODEL_PREFIXED_VERSION_RE = re.compile(r"^gpt(\d+(?:\.\d+)?)$")
_DIR_INPUT = {"inp", "input"}
_DIR_OUTPUT = {"opt", "outp", "output"}


@dataclass(frozen=True)
class ParsedFoundryMeter:
    raw_meter: str
    version: str
    family: str | None
    billing_direction: str  # input | output | cached_input
    token_direction: str  # input | output (cached_input counts as input for token CSV)
    token_model: str
    rule_id: str = "foundry_v1"


def token_model_name(*, version: str, family: str | None) -> str:
    fam = (family or "").strip().lower()
    if fam:
        return f"gpt-{version}-{fam}"
    return f"gpt-{version}"


def canonical_model_name(name: str | None) -> str:
    """
    Canonicalize model names from token headers / meter-derived labels.

    Examples:
    - "gpt-5.3-codex"  -> "gpt-5.3-codex"
    - "GPT 5.3 CODEX"  -> "gpt-5.3-codex"
    - "gpt53codex"     -> "gpt-53-codex" (best effort)
    """
    if not name:
        return ""
    raw = str(name).strip().lower()
    if not raw:
        return ""

    compact = "".join(ch for ch in raw if ch.isalnum() or ch == ".")
    tokens = _METER_TOKEN_RE.findall(raw)
    has_gpt_hint = ("gpt" in tokens) or ("gpt" in compact)
    has_codex_hint = ("codex" in tokens) or ("codex" in compact)
    is_plain_version = bool(_MODEL_VERSION_RE.fullmatch(raw))

    m_pref = _MODEL_PREFIXED_VERSION_RE.match(compact)
    if m_pref:
        return token_model_name(version=m_pref.group(1), family="codex" if "codex" in raw else None)

    version: str | None = None
    for i, tok in enumerate(tokens):
        if tok == "gpt":
            if i + 1 < len(tokens) and _MODEL_VERSION_RE.fullmatch(tokens[i + 1]):
                version = tokens[i + 1]
                break
        elif _MODEL_PREFIXED_VERSION_RE.match(tok):
            version = _MODEL_PREFIXED_VERSION_RE.match(tok).group(1)  # type: ignore[union-attr]
            break
        elif _MODEL_VERSION_RE.fullmatch(tok):
            version = tok
            break
    if version is None:
        m = _MODEL_VERSION_RE.search(raw)
        if m:
            version = m.group(1)
    if version is None:
        return ""
    if not (has_gpt_hint or has_codex_hint or is_plain_version):
        return ""

    family = "codex" if "codex" in tokens or "codex" in compact else None
    return token_model_name(version=version, family=family)


def _parse_foundry_meter_by_tokens(raw: str) -> ParsedFoundryMeter | None:
    tokens = _METER_TOKEN_RE.findall(raw.lower())
    if not tokens:
        return None

    direction_token: str | None = None
    for tok in tokens:
        if tok in _DIR_INPUT:
            direction_token = "inp"
            break
        if tok in _DIR_OUTPUT:
            direction_token = "opt"
            break
    if direction_token is None:
        return None

    version: str | None = None
    family: str | None = "codex" if "codex" in tokens else None
    for i, tok in enumerate(tokens):
        if tok == "gpt":
            if i + 1 < len(tokens) and _MODEL_VERSION_RE.fullmatch(tokens[i + 1]):
                version = tokens[i + 1]
                break
        pref = _MODEL_PREFIXED_VERSION_RE.match(tok)
        if pref:
            version = pref.group(1)
            break
        if _MODEL_VERSION_RE.fullmatch(tok):
            version = tok
            break
    if version is None:
        return None

    is_cached = ("cd" in tokens) or ("cached" in tokens and direction_token == "inp")
    if direction_token == "inp":
        billing_direction = "cached_input" if is_cached else "input"
        token_direction = "input"
    else:
        billing_direction = "output"
        token_direction = "output"
    return ParsedFoundryMeter(
        raw_meter=raw,
        version=version,
        family=family,
        billing_direction=billing_direction,
        token_direction=token_direction,
        token_model=token_model_name(version=version, family=family),
    )


def _tokenize_meter(meter: str | None) -> list[str]:
    if not meter:
        return []
    return _METER_TOKEN_RE.findall(str(meter).lower())


def _model_signature(model_name: str | None) -> tuple[str | None, str | None]:
    if not model_name:
        return None, None
    canonical = canonical_model_name(model_name)
    if not canonical.startswith("gpt-"):
        return None, None
    parts = canonical.split("-")
    if len(parts) < 2:
        return None, None
    version = parts[1] if len(parts) >= 2 else None
    family = parts[2] if len(parts) >= 3 else None
    return version, family


def meter_matches_model_direction(
    meter: str | None,
    *,
    token_model: str,
    token_direction: str,
) -> bool:
    """
    Explicit model+direction matcher for billing ``Meter`` text.

    Intended for robust reconciliation when strict parser coverage is uncertain.
    """
    tokens = _tokenize_meter(meter)
    if not tokens:
        return False
    version, family = _model_signature(token_model)
    if not version:
        return False

    dirs = _DIR_INPUT if token_direction == "input" else _DIR_OUTPUT
    if not any(tok in dirs for tok in tokens):
        return False

    has_version = False
    for i, tok in enumerate(tokens):
        if tok == version:
            has_version = True
            break
        pref = _MODEL_PREFIXED_VERSION_RE.match(tok)
        if pref and pref.group(1) == version:
            has_version = True
            break
        if tok == "gpt" and i + 1 < len(tokens) and tokens[i + 1] == version:
            has_version = True
            break
    if not has_version:
        return False

    if family == "codex":
        return "codex" in tokens
    return True


def parse_foundry_meter(meter: str | None) -> ParsedFoundryMeter | None:
    if not meter or not str(meter).strip():
        return None
    raw = str(meter).strip()
    m = _FOUNDRY_METER_RE.match(raw.lower())
    if m:
        version = m.group("version")
        family = m.group("family")
        direction_token = m.group("dir").lower()
        is_cached = bool(m.group("cached"))
        if direction_token == "inp":
            billing_direction = "cached_input" if is_cached else "input"
            token_direction = "input"
        elif direction_token == "opt":
            billing_direction = "output"
            token_direction = "output"
        else:
            return None
        return ParsedFoundryMeter(
            raw_meter=raw,
            version=version,
            family=family,
            billing_direction=billing_direction,
            token_direction=token_direction,
            token_model=token_model_name(version=version, family=family),
        )

    return _parse_foundry_meter_by_tokens(raw)


def billing_direction_bucket(billing_direction: str) -> str:
    """Collapse cached_input into the input bucket used by token CSV columns."""
    if billing_direction in {"input", "cached_input"}:
        return "input"
    if billing_direction == "output":
        return "output"
    return billing_direction


def normalize_token_column(name: str | None) -> str:
    """Normalize token CSV header / DB model_name for comparison."""
    if not name:
        return ""
    canonical = canonical_model_name(name)
    if canonical:
        return "".join(ch for ch in canonical.lower() if ch.isalnum())
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def token_models_match(a: str, b: str) -> bool:
    na, nb = normalize_token_column(a), normalize_token_column(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def list_known_meter_patterns() -> list[dict[str, str]]:
    """Documentation helper for UI / tests."""
    return [
        {
            "rule_id": "foundry_v1",
            "pattern": r"{version} [codex] [cd] inp|opt",
            "example": "5.3 codex inp Gl 1M Tokens → gpt-5.3-codex / input",
        },
        {
            "rule_id": "foundry_v1",
            "pattern": r"{version} [codex] [cd] inp|opt",
            "example": "5.4 opt Gl 1M Tokens → gpt-5.4 / output",
        },
    ]


def sum_meter_costs(
    meter_cost_rows: Iterable[tuple[str, float]],
    *,
    token_model: str,
    token_direction: str,
) -> float:
    """
    Sum ``CostUSD`` for transaction rows whose ``Meter`` matches
    ``token_model`` + ``token_direction`` (input includes cached inp).
    """
    total = 0.0
    for meter, cost_usd in meter_cost_rows:
        cost = float(cost_usd or 0.0)
        if cost <= 0:
            continue
        if meter_matches_model_direction(
            meter,
            token_model=token_model,
            token_direction=token_direction,
        ):
            total += cost
    return total


def aggregate_billing_rows(
    rows: Iterable[tuple[str, str, float]],
) -> dict[str, dict[str, dict[str, float]]]:
    """
    Aggregate transaction rows into date → token_model → {input, output, total} costs.

    Each row is (usage_date, meter, cost_usd).
    """
    out: dict[str, dict[str, dict[str, float]]] = {}
    for usage_date, meter, cost_usd in rows:
        parsed = parse_foundry_meter(meter)
        if parsed is None:
            continue
        cost = float(cost_usd or 0.0)
        if cost <= 0:
            continue
        bucket = billing_direction_bucket(parsed.billing_direction)
        day = out.setdefault(str(usage_date), {}).setdefault(
            parsed.token_model,
            {"input": 0.0, "output": 0.0, "total": 0.0},
        )
        day[bucket] = day.get(bucket, 0.0) + cost
        day["total"] = day.get("total", 0.0) + cost
    return out
