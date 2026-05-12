from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.azure_retail_prices import (
    compose_retail_filter,
    import_openai_retail_prices,
    normalize_retail_item,
    retail_filter_url,
)


def test_normalize_retail_item_gpt55_priority_output():
    item = {
        "currencyCode": "USD",
        "retailPrice": 82.5,
        "armRegionName": "eastus2",
        "effectiveStartDate": "2026-03-01T00:00:00Z",
        "meterId": "m1",
        "meterName": "5.5 ShortCo PP opt Dz 1M Tokens",
        "productName": "Azure OpenAI GPT5",
        "skuName": "5.5 ShortCo PP opt Dz",
        "skuId": "sku/1",
        "unitOfMeasure": "1M",
    }
    row = normalize_retail_item(
        item,
        retrieved_at_utc="2026-05-09T00:00:00Z",
        source_listing_url="https://prices.azure.com/api/retail/prices?$filter=test",
    )
    d = json.loads(row[19])
    assert row[6] == "eastus2"
    assert row[7] == "USD"
    assert row[8] == "GPT-5.5 Series (Azure Retail)"
    assert row[9] == "5.5 ShortCo PP opt Dz"
    assert row[10] == "short_context"
    assert row[11] == "data_zone"
    assert row[12] == "priority"
    assert row[13] == "output"
    assert row[14] == 82.5
    assert d["retailItem"]["meterId"] == "m1"


def test_import_openai_retail_prices_with_fixture_opener(tmp_path):
    fixture = json.loads(
        Path(__file__).resolve().parent.joinpath("fixtures", "azure_retail_openai_page.json").read_text(
            encoding="utf-8"
        )
    )
    pages = [fixture]

    def opener(url: str):
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return None

            def read(self):
                if not pages:
                    return b"{}"
                return json.dumps({"Items": pages.pop(0), "NextPageLink": None}).encode("utf-8")

        return _Resp()

    db_path = tmp_path / "db.sqlite3"
    r = import_openai_retail_prices(db_path=str(db_path), opener=opener)
    assert r.rows_fetched == 2
    assert r.rows_imported == 2
    assert r.retail_rows_deleted >= 0
    assert "prices.azure.com" in r.filter_url


def test_compose_retail_filter_gpt55():
    f = compose_retail_filter("gpt_55")
    assert "5.5" in f
    assert "Foundry Models" in f


def test_retail_filter_url_contains_filter():
    u = retail_filter_url("all")
    assert u.startswith("https://prices.azure.com/api/retail/prices")


def test_import_openai_retail_prices_live_smoke(tmp_path):
    """Optional live call; skipped in CI unless RUN_LIVE_AZURE_RETAIL=1."""
    import os

    if os.getenv("RUN_LIVE_AZURE_RETAIL", "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip("set RUN_LIVE_AZURE_RETAIL=1 to run live Azure Retail import smoke test")

    db_path = tmp_path / "live.sqlite3"
    r = import_openai_retail_prices(db_path=str(db_path))
    assert r.rows_imported > 1000
