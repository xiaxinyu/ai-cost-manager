from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.auth import create_user
from app.money import round_cost
from app.db import (
    get_catalog_market_cost_timeseries,
    get_connection,
    get_model_implied_usd_per_1m_analysis,
    get_project_daily_implied_usd_per_1m_timeseries,
    init_db,
)
from app.ingest import ingest_all
from app.main import create_app
from app.token_ingest import ingest_token_all


def _write_foundry_cost(path, rows: list[tuple[str, str, float]]) -> None:
    lines = [
        '"UsageDate","ResourceId","ResourceType","ResourceLocation","ResourceGroupName",'
        '"ServiceName","ServiceTier","Meter","CostUSD","Cost","Currency"'
    ]
    rid = "/subscriptions/x/resourcegroups/rg/providers/microsoft.cognitiveservices/accounts/a"
    for usage_date, meter, cost in rows:
        lines.append(
            f'"{usage_date}","{rid}","microsoft.cognitiveservices/accounts","US East 2",'
            f'"rg","Foundry Models","Azure OpenAI GPT5","{meter}","{cost}","{cost}","USD"'
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _create_admin(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        create_user(conn, username="admin", password="admin12345", is_active=True)
    finally:
        conn.close()


def test_model_implied_usd_per_1m_daily_stats(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projM"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)

    _write_foundry_cost(
        project_dir / "cost.csv",
        [
            ("2026-05-01", "5.3 codex inp Gl 1M Tokens", 8.0),
            ("2026-05-01", "5.3 codex opt Gl 1M Tokens", 2.0),
            ("2026-05-02", "5.3 codex inp Gl 1M Tokens", 20.0),
            ("2026-05-02", "5.3 codex opt Gl 1M Tokens", 4.0),
            ("2026-05-02", "5.4 inp Gl 1M Tokens", 5.0),
            ("2026-05-02", "5.4 opt Gl 1M Tokens", 1.0),
        ],
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","gpt-5.3-codex","gpt-5.4"\n'
        "2026-05-01 10:00:00,1 Mil,0\n"
        "2026-05-02 10:00:00,2 Mil,1 Mil\n",
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","gpt-5.3-codex","gpt-5.4"\n'
        "2026-05-01 10:00:00,100 K,0\n"
        "2026-05-02 10:00:00,200 K,50 K\n",
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    conn = get_connection(db_path)
    try:
        payload = get_model_implied_usd_per_1m_analysis(conn, "projM", currency="USD")
    finally:
        conn.close()

    assert payload["available"] is True
    assert payload["allocation_method"] == "meter_matched"
    by_name = {m["model_name"]: m for m in payload["models"]}
    assert "gpt-5.3-codex" in by_name and "gpt-5.4" in by_name

    codex_day1 = next(d for d in by_name["gpt-5.3-codex"]["daily"] if d["date"] == "2026-05-01")
    assert codex_day1["allocation_method"] == "meter_matched"
    assert codex_day1["usd_per_1m_input"] == round_cost(8.0)
    assert codex_day1["usd_per_1m_output"] == round_cost(20.0)
    assert codex_day1["usd_per_1m_blended"] == round_cost(10.0 / 1_100_000 * 1_000_000)

    codex_day2 = next(d for d in by_name["gpt-5.3-codex"]["daily"] if d["date"] == "2026-05-02")
    g54_day2 = next(d for d in by_name["gpt-5.4"]["daily"] if d["date"] == "2026-05-02")
    assert codex_day2["cost_usd_allocated"] == round_cost(24.0)
    assert g54_day2["cost_usd_allocated"] == round_cost(6.0)
    assert codex_day2["usd_per_1m_input"] == round_cost(10.0)

    st_codex = by_name["gpt-5.3-codex"]["stats"]["blended"]
    assert st_codex["count"] == 2


def test_project_daily_implied_usd_per_1m_timeseries(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projM"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)

    _write_foundry_cost(
        project_dir / "cost.csv",
        [
            ("2026-05-01", "5.3 codex inp Gl 1M Tokens", 8.0),
            ("2026-05-01", "5.3 codex opt Gl 1M Tokens", 2.0),
            ("2026-05-02", "5.3 codex inp Gl 1M Tokens", 20.0),
            ("2026-05-02", "5.3 codex opt Gl 1M Tokens", 4.0),
            ("2026-05-02", "5.4 inp Gl 1M Tokens", 5.0),
            ("2026-05-02", "5.4 opt Gl 1M Tokens", 1.0),
        ],
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","gpt-5.3-codex","gpt-5.4"\n'
        "2026-05-01 10:00:00,1 Mil,0\n"
        "2026-05-02 10:00:00,2 Mil,1 Mil\n",
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","gpt-5.3-codex","gpt-5.4"\n'
        "2026-05-01 10:00:00,100 K,0\n"
        "2026-05-02 10:00:00,200 K,50 K\n",
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    conn = get_connection(db_path)
    try:
        payload = get_project_daily_implied_usd_per_1m_timeseries(conn, "projM", currency="USD")
    finally:
        conn.close()

    assert payload["available"] is True
    by_date = {p["date"]: p for p in payload["points"]}
    d1 = by_date["2026-05-01"]
    assert abs(float(d1["usd_per_1m_input"]) - 8.0) < 1e-6
    assert abs(float(d1["usd_per_1m_output"]) - 20.0) < 1e-6
    d2 = by_date["2026-05-02"]
    assert abs(float(d2["usd_per_1m_input"]) - round_cost(25.0 / 3_000_000 * 1_000_000)) < 1e-6
    assert abs(float(d2["usd_per_1m_output"]) - 20.0) < 1e-6

    st_in = payload["stats"]["input"]
    assert st_in["count"] == 2
    st_out = payload["stats"]["output"]
    assert st_out["count"] == 2


def test_model_unit_prices_api(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projM"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)
    _write_foundry_cost(
        project_dir / "cost.csv",
        [
            ("2026-05-01", "5.3 codex inp Gl 1M Tokens", 3.0),
            ("2026-05-01", "5.3 codex opt Gl 1M Tokens", 1.0),
        ],
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n2026-05-01 10:00:00,1 Mil\n',
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n2026-05-01 10:00:00,50 K\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    _create_admin(str(db_path))
    client.post("/auth/login", data={"username": "admin", "password": "admin12345"})

    res = client.get("/api/projects/projM/model-unit-prices?currency=USD")
    assert res.status_code == 200
    data = res.json()
    assert data["available"] is True
    assert len(data["models"]) == 1
    assert data["models"][0]["stats"]["blended"]["count"] == 1
    assert data["allocation_method"] == "meter_matched"

    res_ip = client.get("/api/projects/projM/implied-unit-prices-timeseries?currency=USD")
    assert res_ip.status_code == 200
    ip = res_ip.json()
    assert ip["available"] is True
    assert len(ip["points"]) >= 1
    assert ip["stats"]["input"]["count"] == 1

    page = client.get("/tokens")
    assert page.status_code == 200
    assert "unitPriceSection" in page.text
    assert "impliedUnitPriceInputChart" in page.text


def test_catalog_prefers_global_standard_over_cheaper_fuzzy(tmp_path):
    """gpt-5.1 should use GPT-5.1 Global (1.25/10), not codex-mini (0.25/2)."""
    db_path = tmp_path / "cost_mgmt.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        rows = [
            ("GPT-5.1 Global", "global", "standard", "input", 1.25),
            ("GPT-5.1 Global", "global", "standard", "output", 10.0),
            ("GPT-5.1-codex-mini Global", "global", "standard", "input", 0.25),
            ("GPT-5.1-codex-mini Global", "global", "standard", "output", 2.0),
        ]
        for model_name, scope, mode, metric, amount in rows:
            conn.execute(
                """
                INSERT INTO model_prices(
                    source_id, source_url, effective_date, retrieved_at_utc,
                    vendor, platform, price_region, price_currency,
                    model_series, model_name, context_bucket, deployment_scope,
                    billing_mode, metric_name, amount,
                    unit_quantity, unit_name, unit_expression, notes, source_detail_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "src",
                    "https://example.com",
                    "2026-05-13",
                    "2026-05-13T00:00:00Z",
                    "Microsoft",
                    "azure-openai",
                    "eastus2",
                    "USD",
                    "GPT-5.1",
                    model_name,
                    None,
                    scope,
                    mode,
                    metric,
                    amount,
                    1_000_000,
                    "tokens",
                    "USD/1M tokens",
                    None,
                    None,
                ),
            )
        conn.commit()
        from app.db import _resolve_catalog_prices_for_model_name

        resolved = _resolve_catalog_prices_for_model_name(conn, "gpt-5.1")
    finally:
        conn.close()

    assert resolved["input_source"]["catalog_model_name"] == "GPT-5.1 Global"
    assert resolved["input_source"]["amount"] == 1.25
    assert resolved["input_source"]["price_tier"] == "global_standard"
    assert resolved["input_source"]["match_kind"] == "exact"
    assert resolved["output_source"]["catalog_model_name"] == "GPT-5.1 Global"
    assert resolved["output_source"]["amount"] == 10.0


def test_catalog_prices_gpt_4o_family_match(tmp_path):
    """gpt-4o dated snapshots and shorthand labels match GPT-4o catalog rows."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        for metric, amount in (("input", 5.5), ("output", 16.5)):
            conn.execute(
                """
                INSERT INTO model_prices(
                    source_id, source_url, effective_date, retrieved_at_utc,
                    vendor, platform, price_region, price_currency,
                    model_series, model_name, context_bucket, deployment_scope,
                    billing_mode, metric_name, amount,
                    unit_quantity, unit_name, unit_expression, notes, source_detail_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "src",
                    "https://example.com",
                    "2026-04-29",
                    "2026-04-29T00:00:00Z",
                    "Microsoft",
                    "azure-openai",
                    "East US",
                    "USD",
                    "GPT-4o Series",
                    "GPT-4o-2024-0513",
                    None,
                    "global",
                    "standard",
                    metric,
                    amount,
                    1_000_000,
                    "tokens",
                    "USD/1M tokens",
                    None,
                    None,
                ),
            )
        conn.commit()
        from app.db import _resolve_catalog_prices_for_model_name

        for token_model in ("gpt-4o", "gpt-4o-2024-11-20", "gpt 4o 1120"):
            resolved = _resolve_catalog_prices_for_model_name(conn, token_model)
            assert resolved["input_source"] is not None, token_model
            assert resolved["input_source"]["catalog_model_name"] == "GPT-4o-2024-0513"
            assert resolved["input_source"]["amount"] == 5.5
            assert resolved["output_source"]["amount"] == 16.5
    finally:
        conn.close()


def test_catalog_prices_fuzzy_match_normalized_model_name(tmp_path):
    """Token CSV model keys like gpt-5.3-codex should match catalog GPT-5.3 Codex."""
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projCat"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)
    (project_dir / "cost.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-05-01","10.0","10.0","","USD"\n',
        encoding="utf-8",
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n2026-05-01 10:00:00,1 Mil\n',
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n2026-05-01 10:00:00,100 K\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        conn.execute(
            """
            INSERT INTO model_prices(
                source_id, source_url, effective_date, retrieved_at_utc,
                vendor, platform, price_region, price_currency,
                model_series, model_name, context_bucket, deployment_scope,
                billing_mode, metric_name, amount,
                unit_quantity, unit_name, unit_expression, notes, source_detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "src",
                "https://example.com",
                "2026-04-29",
                "2026-04-29T00:00:00Z",
                "Microsoft",
                "azure-openai",
                "East US",
                "USD",
                "GPT-5.3",
                "GPT-5.3 Codex",
                None,
                "global",
                "standard",
                "input",
                1.75,
                1_000_000,
                "tokens",
                "USD/1M tokens",
                None,
                None,
            ),
        )
        conn.execute(
            """
            INSERT INTO model_prices(
                source_id, source_url, effective_date, retrieved_at_utc,
                vendor, platform, price_region, price_currency,
                model_series, model_name, context_bucket, deployment_scope,
                billing_mode, metric_name, amount,
                unit_quantity, unit_name, unit_expression, notes, source_detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "src",
                "https://example.com",
                "2026-04-29",
                "2026-04-29T00:00:00Z",
                "Microsoft",
                "azure-openai",
                "East US",
                "USD",
                "GPT-5.3",
                "GPT-5.3 Codex",
                None,
                "global",
                "standard",
                "output",
                14.0,
                1_000_000,
                "tokens",
                "USD/1M tokens",
                None,
                None,
            ),
        )
        conn.commit()
        payload = get_model_implied_usd_per_1m_analysis(conn, "projCat", currency="USD")
    finally:
        conn.close()

    assert payload["available"] is True
    model = next(m for m in payload["models"] if "codex" in m["model_name"].lower())
    assert model["catalog_usd_per_1m_input"] == 1.75
    assert model["catalog_usd_per_1m_output"] == 14.0


def test_catalog_market_cost_timeseries(tmp_path):
    """1M input + 100K output at catalog 1.75 / 14 USD per 1M → 3.15 USD market cost."""
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projCat"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)
    (project_dir / "cost.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-05-01","10.0","10.0","","USD"\n',
        encoding="utf-8",
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n2026-05-01 10:00:00,1 Mil\n',
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n2026-05-01 10:00:00,100 K\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        for metric, amount in (("input", 1.75), ("output", 14.0)):
            conn.execute(
                """
                INSERT INTO model_prices(
                    source_id, source_url, effective_date, retrieved_at_utc,
                    vendor, platform, price_region, price_currency,
                    model_series, model_name, context_bucket, deployment_scope,
                    billing_mode, metric_name, amount,
                    unit_quantity, unit_name, unit_expression, notes, source_detail_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "src",
                    "https://example.com",
                    "2026-04-29",
                    "2026-04-29T00:00:00Z",
                    "Microsoft",
                    "azure-openai",
                    "East US",
                    "USD",
                    "GPT-5.3",
                    "GPT-5.3 Codex",
                    None,
                    "global",
                    "standard",
                    metric,
                    amount,
                    1_000_000,
                    "tokens",
                    "USD/1M tokens",
                    None,
                    None,
                ),
            )
        conn.commit()
        payload = get_catalog_market_cost_timeseries(conn, "projCat", currency="USD")
    finally:
        conn.close()

    assert payload["available"] is True
    assert payload["token_data_source"] == "imported"
    assert len(payload["points"]) == 1
    assert payload["points"][0]["catalog_cost_usd"] == round_cost(3.15)
    assert payload["points"][0]["actual_cost_usd"] == round_cost(10.0)
    assert payload["summary"]["total_catalog_cost_usd"] == round_cost(3.15)
    assert payload["summary"]["total_actual_cost_usd"] == round_cost(10.0)
    assert len(payload["daily_by_model"]) >= 1
    assert payload["daily_by_model"][0]["catalog_cost_usd"] == round_cost(3.15)
    assert len(payload["model_summary"]) >= 1
    assert payload["model_summary"][0]["catalog_cost_usd"] == round_cost(3.15)
    ms = payload["model_summary"][0]
    assert ms["catalog_price_input"]["catalog_model_name"] == "GPT-5.3 Codex"
    assert ms["catalog_price_input"]["amount"] == 1.75
    assert ms["catalog_price_output"]["catalog_model_name"] == "GPT-5.3 Codex"
    assert ms["catalog_price_output"]["amount"] == 14.0
    assert ms["catalog_price_input"]["match_kind"] in ("exact", "fuzzy")

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    _create_admin(str(db_path))
    client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    page = client.get("/")
    assert page.status_code == 200
    assert "timeseriesChartMarket" in page.text
    assert "catalogMarketTotal" in page.text
    assert "modelCostSummaryTable" in page.text
    assert "timeseriesChartInputByModel" in page.text
    assert "timeseriesChartOutputByModel" in page.text
    assert "projectInputCostTotal" in page.text
    assert "costModelSection" in page.text
    assert "Catalog source (Model Prices)" in page.text

    api = client.get("/api/projects/projCat/catalog-market-timeseries?currency=USD")
    assert api.status_code == 200
    body = api.json()
    assert body["available"] is True
    assert body["points"][0]["catalog_cost_usd"] == round_cost(3.15)
    assert len(body["daily_by_model"]) >= 1
    assert len(body["model_summary"]) >= 1
    assert "input_cost_usd" in body["daily_by_model"][0]
    assert "total_input_cost_usd" in body["summary"]
    assert "total_output_cost_usd" in body["summary"]
    assert "total_meter_cost_usd" in body["summary"]


def test_imported_daily_by_model_money_fields_two_decimals(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projDaily"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)
    (project_dir / "cost.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-05-01","10.0","10.0","","USD"\n',
        encoding="utf-8",
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","model-a"\n2026-05-01 10:00:00,1 Mil\n',
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","model-a"\n2026-05-01 10:00:00,100 K\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    conn = get_connection(db_path)
    try:
        from app.db import get_imported_token_daily_by_model

        rows = get_imported_token_daily_by_model(conn, "projDaily", currency="USD")
    finally:
        conn.close()

    assert len(rows) >= 1
    row = rows[0]
    for key in ("input_cost_usd", "output_cost_usd", "total_cost_usd", "usd_per_1m_input", "usd_per_1m_output"):
        val = row.get(key)
        if val is not None:
            assert val == round_cost(val), f"{key} not 2dp: {val}"


def test_implied_timeseries_follows_token_calendar_not_full_billing(tmp_path):
    """Billing may span months; implied series stays on token days (no March-only billing)."""
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projSpan"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)
    (project_dir / "cost.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-03-01","1.0","1.0","","USD"\n'
        '"2026-05-01","10.0","10.0","","USD"\n'
        '"2026-05-02","20.0","20.0","","USD"\n',
        encoding="utf-8",
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","m"\n2026-05-01 10:00:00,1 Mil\n2026-05-02 10:00:00,1 Mil\n',
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","m"\n2026-05-01 10:00:00,100 K\n2026-05-02 10:00:00,100 K\n',
        encoding="utf-8",
    )
    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    conn = get_connection(db_path)
    try:
        payload = get_project_daily_implied_usd_per_1m_timeseries(conn, "projSpan", currency="USD")
    finally:
        conn.close()
    dates = [p["date"] for p in payload["points"]]
    assert dates == ["2026-05-01", "2026-05-02"]
    assert payload["from_date"] == "2026-05-01"
    assert payload["to_date"] == "2026-05-02"
    assert "2026-03-01" not in dates


def test_implied_timeseries_extends_through_billing_tail_without_tokens(tmp_path):
    """Trailing billing days after the last token row still appear (cost, null implied $/1M)."""
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projTail"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)
    (project_dir / "cost.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-05-01","10.0","10.0","","USD"\n'
        '"2026-05-02","20.0","20.0","","USD"\n'
        '"2026-05-03","5.0","5.0","","USD"\n',
        encoding="utf-8",
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","m"\n2026-05-01 10:00:00,1 Mil\n2026-05-02 10:00:00,1 Mil\n',
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","m"\n2026-05-01 10:00:00,100 K\n2026-05-02 10:00:00,100 K\n',
        encoding="utf-8",
    )
    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    conn = get_connection(db_path)
    try:
        payload = get_project_daily_implied_usd_per_1m_timeseries(conn, "projTail", currency="USD")
    finally:
        conn.close()
    dates = [p["date"] for p in payload["points"]]
    assert dates == ["2026-05-01", "2026-05-02", "2026-05-03"]
    assert payload["to_date"] == "2026-05-03"
    d3 = next(p for p in payload["points"] if p["date"] == "2026-05-03")
    assert d3["usd_per_1m_input"] is None
    assert d3["usd_per_1m_output"] is None
    assert d3["cost_usd"] is not None
