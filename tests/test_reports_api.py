from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from app.auth import create_user
from app.db import init_db
from app.ingest import ingest_all
from app.main import create_app
from app.token_ingest import ingest_token_all


def _create_admin(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        create_user(conn, username="admin", password="admin12345", is_active=True)
    finally:
        conn.close()


def test_all_financial_report_stats(tmp_path):
    bills_dir = tmp_path / "bills"

    # Two projects to validate "all projects" aggregation.
    p1 = bills_dir / "projA"
    p2 = bills_dir / "projB"
    p1.mkdir(parents=True, exist_ok=True)
    p2.mkdir(parents=True, exist_ok=True)

    # Day1: projA=1, projB=2 => sum=3
    # Day2: projA=3, projB missing => sum=3
    (p1 / "2026.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-01-01","1.0","1.0","","USD"\n'
        '"2026-01-02","3.0","3.0","","USD"\n',
        encoding="utf-8",
    )
    (p2 / "2026.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-01-01","2.0","2.0","","USD"\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)

    _create_admin(str(db_path))
    client.post("/auth/login", data={"username": "admin", "password": "admin12345"})

    res = client.get("/api/reports/all-financial?currency=USD")
    assert res.status_code == 200
    payload = res.json()
    assert payload["currency_options"]
    assert payload["currency"] == "USD"
    assert "project_breakdown" in payload
    assert "catalog_market" in payload
    assert payload["catalog_market"]["available"] is False
    pb = payload["project_breakdown"]
    assert isinstance(pb, list) and len(pb) == 2
    by_name = {r["project_name"]: r for r in pb}
    assert by_name["projA"]["actual_cost_usd_total"] == 4.0
    assert by_name["projB"]["actual_cost_usd_total"] == 2.0
    assert "catalog_cost_usd" in by_name["projA"]
    assert "billing_variance_usd" in by_name["projA"]
    assert "billing_variance_pct" in by_name["projA"]
    assert "meter_variance_usd" in by_name["projA"]
    assert "meter_variance_pct" in by_name["projA"]
    assert by_name["projA"]["catalog_cost_usd"] is None
    assert by_name["projA"]["billing_variance_usd"] is None
    assert by_name["projA"]["billing_variance_pct"] is None
    assert by_name["projA"]["meter_variance_usd"] is None
    assert by_name["projA"]["meter_variance_pct"] is None
    # Billing-only projects: no meter match → platform attributed to full total
    assert by_name["projA"]["meter_cost_usd"] is None
    assert by_name["projA"]["platform_cost_usd"] == 4.0
    assert by_name["projB"]["platform_cost_usd"] == 2.0
    meter = by_name["projA"].get("meter_cost_usd") or 0.0
    platform = by_name["projA"].get("platform_cost_usd") or 0.0
    assert meter + platform <= by_name["projA"]["actual_cost_usd_total"] + 0.01
    assert by_name["projA"]["avg_daily_cost_usd"] == 2.0
    assert by_name["projB"]["avg_daily_cost_usd"] == 2.0

    pdc = payload["project_daily_cost"]
    assert pdc["currency"] == "USD"
    assert pdc["dates"] == ["2026-01-01", "2026-01-02"]
    assert set(pdc["projects"]) == {"projA", "projB"}
    summaries = {s["project_name"]: s for s in pdc["summaries"]}
    assert summaries["projA"]["avg_daily_cost_usd"] == 2.0
    assert summaries["projA"]["billed_days"] == 2
    assert "meter_share_pct" in summaries["projA"]
    points_by_key = {(p["project_name"], p["date"]): p["cost_usd"] for p in pdc["points"]}
    assert points_by_key[("projA", "2026-01-01")] == 1.0
    assert points_by_key[("projA", "2026-01-02")] == 3.0
    assert points_by_key[("projB", "2026-01-01")] == 2.0
    assert by_name["projA"]["actual_cost_usd_total"] == summaries["projA"]["total_cost_usd"]
    assert by_name["projA"]["actual_days"] == summaries["projA"]["billed_days"]

    daily = payload["daily"]
    # daily points are summed per day, so values are [3, 3]
    assert daily["count_days"] == 2
    assert daily["total_actual"] == 6.0
    assert daily["avg_actual"] == 3.0
    assert daily["median_actual"] == 3.0
    assert daily["var_actual"] == 0.0

    monthly = payload["monthly"]
    assert monthly["count_months"] == 1
    assert monthly["avg_actual"] == 6.0 / 1.0

    # Validate project filtering (single project scope).
    res2 = client.get("/api/reports/all-financial?currency=USD&project_names=projA")
    assert res2.status_code == 200
    payload2 = res2.json()
    assert len(payload2["project_breakdown"]) == 1
    assert payload2["project_breakdown"][0]["project_name"] == "projA"
    assert payload2["project_breakdown"][0]["actual_cost_usd_total"] == 4.0
    daily2 = payload2["daily"]
    # projA has Day1=1, Day2=3 => total=4, avg=2, median=2, variance=1 (population variance)
    assert daily2["count_days"] == 2
    assert daily2["total_actual"] == 4.0
    assert daily2["avg_actual"] == 2.0
    assert daily2["median_actual"] == 2.0
    assert daily2["var_actual"] == 1.0

    assert "token_daily_points" in payload
    assert "token_monthly_points" in payload
    assert "token_models_display" in payload
    assert "token_import_path" in payload
    assert "token_actual" in payload
    assert "token_estimate" not in payload

    assert len(payload["token_daily_points"]) == daily["count_days"]
    assert len(payload["token_monthly_points"]) == monthly["count_months"]

    td0 = payload["token_daily_points"][0]
    assert "input_tokens" in td0
    assert "output_tokens" in td0
    assert "total_tokens" in td0
    assert all(p["total_tokens"] is None for p in payload["token_daily_points"])
    assert payload["token_actual"]["input_tokens_total"] == 0.0

    assert "insights" in payload
    assert isinstance(payload["insights"], list)
    assert len(payload["insights"]) >= 1
    first = payload["insights"][0]
    assert "id" in first
    assert "severity" in first
    assert "title" in first
    assert "summary" in first

    # Verify consistency between report-scoped aggregation and per-project dashboard calculations.
    ver = client.get("/api/verify/reports-all-financial-consistency?currency=USD&mode=deep")
    assert ver.status_code == 200
    ver_payload = ver.json()
    assert ver_payload["ok"] is True
    assert ver_payload["failed_count"] == 0
    assert payload["scope_quality"]["projects_in_scope"] == 2
    assert payload["scope_quality"]["projects_with_billing"] == 2

    summary_res = client.get("/api/billing/projects-summary?currency=USD")
    assert summary_res.status_code == 200
    summary_payload = summary_res.json()
    assert summary_payload["currency"] == "USD"
    assert len(summary_payload["summaries"]) == 2


def test_all_financial_report_includes_token_only_projects_and_verifies(tmp_path):
    bills_dir = tmp_path / "bills"

    billing_project = bills_dir / "projBill"
    token_project = bills_dir / "projTokenOnly" / "token"
    billing_project.mkdir(parents=True, exist_ok=True)
    token_project.mkdir(parents=True, exist_ok=True)

    (billing_project / "2026.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-01-01","5.0","5.0","","USD"\n',
        encoding="utf-8",
    )
    (token_project / "input-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n'
        "2026-01-03 10:00:00,1 K\n",
        encoding="utf-8",
    )
    (token_project / "output-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n'
        "2026-01-03 10:00:00,2 K\n",
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)

    _create_admin(str(db_path))
    client.post("/auth/login", data={"username": "admin", "password": "admin12345"})

    res = client.get("/api/reports/all-financial?currency=USD")
    assert res.status_code == 200
    payload = res.json()

    by_name = {r["project_name"]: r for r in payload["project_breakdown"]}
    assert by_name["projBill"]["actual_cost_usd_total"] == 5.0
    assert by_name["projTokenOnly"]["actual_cost_usd_total"] == 0.0
    assert by_name["projTokenOnly"]["input_tokens"] == 1000.0
    assert by_name["projTokenOnly"]["output_tokens"] == 2000.0
    assert payload["scope_quality"]["token_only_projects"] == 1

    token_by_date = {p["date"]: p for p in payload["token_daily_points"]}
    assert token_by_date["2026-01-01"]["input_tokens"] is None
    assert token_by_date["2026-01-03"]["input_tokens"] == 1000.0
    assert payload["token_actual"]["input_tokens_total"] == 1000.0

    ver = client.get("/api/verify/reports-all-financial-consistency?currency=USD&mode=deep")
    assert ver.status_code == 200
    ver_payload = ver.json()
    assert ver_payload["ok"] is True
    assert ver_payload["failed_count"] == 0


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


def _seed_gpt53_codex_prices(conn: sqlite3.Connection) -> None:
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


def test_all_financial_report_exposes_unit_rate_comparison(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projBridge"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)
    _write_foundry_cost(
        project_dir / "cost.csv",
        [
            ("2026-05-12", "5.3 codex inp Gl 1M Tokens", 10.0),
            ("2026-05-12", "5.3 codex opt Gl 1M Tokens", 4.0),
        ],
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n2026-05-12 10:00:00,2 Mil\n',
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n2026-05-12 10:00:00,200 K\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        _seed_gpt53_codex_prices(conn)
    finally:
        conn.close()

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    _create_admin(str(db_path))
    client.post("/auth/login", data={"username": "admin", "password": "admin12345"})

    res = client.get("/api/reports/all-financial?currency=USD&project_names=projBridge")
    assert res.status_code == 200
    catalog = res.json()["catalog_market"]
    assert catalog["available"] is True
    assert len(catalog["model_unit_rates"]) >= 1
    assert len(catalog["project_unit_rates"]) == 1
    row = next(
        r for r in catalog["model_unit_rates"] if "codex" in str(r["model_name"]).lower()
    )
    assert row["effective_usd_per_1m_input"] == 5.0
    assert row["effective_usd_per_1m_output"] == 20.0

    payload = res.json()
    summary = catalog["summary"]
    assert summary["variance_pct"] is not None
    assert summary["variance_usd"] is not None
    assert summary["meter_variance_pct"] is not None
    assert summary["meter_variance_usd"] is not None
    pb = payload["project_breakdown"][0]
    assert pb["project_name"] == "projBridge"
    assert pb["catalog_cost_usd"] == summary["total_catalog_cost_usd"]
    assert pb["billing_variance_pct"] == summary["variance_pct"]
    assert pb["billing_variance_usd"] == summary["variance_usd"]
    assert pb["meter_variance_pct"] == summary["meter_variance_pct"]
    assert pb["meter_variance_usd"] == summary["meter_variance_usd"]


def test_project_breakdown_exposes_billing_and_meter_variance(tmp_path):
    """Platform fees inflate billing variance but not meter variance."""
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projPlatformHeavy"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)
    _write_foundry_cost(
        project_dir / "cost.csv",
        [
            ("2026-05-12", "5.3 codex inp Gl 1M Tokens", 10.0),
            ("2026-05-12", "5.3 codex opt Gl 1M Tokens", 4.0),
        ],
    )
    (project_dir / "platform.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-05-12","100.0","100.0","","USD"\n',
        encoding="utf-8",
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n2026-05-12 10:00:00,2 Mil\n',
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n2026-05-12 10:00:00,200 K\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        _seed_gpt53_codex_prices(conn)
    finally:
        conn.close()

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    _create_admin(str(db_path))
    client.post("/auth/login", data={"username": "admin", "password": "admin12345"})

    res = client.get(
        "/api/reports/all-financial?currency=USD&project_names=projPlatformHeavy"
    )
    assert res.status_code == 200
    payload = res.json()
    pb = payload["project_breakdown"][0]
    summary = payload["catalog_market"]["summary"]

    assert pb["actual_cost_usd_total"] == 114.0
    assert pb["meter_cost_usd"] == 14.0
    assert pb["platform_cost_usd"] == 100.0
    assert pb["billing_variance_pct"] == summary["variance_pct"]
    assert pb["billing_variance_usd"] == summary["variance_usd"]
    assert pb["meter_variance_pct"] == summary["meter_variance_pct"]
    assert pb["meter_variance_usd"] == summary["meter_variance_usd"]
    assert pb["billing_variance_pct"] is not None
    assert pb["meter_variance_pct"] is not None
    assert pb["billing_variance_pct"] > pb["meter_variance_pct"]


def test_reports_page_layout_without_token_forecast(tmp_path):
    bills_dir = tmp_path / "bills"
    bills_dir.mkdir(parents=True)
    db_path = tmp_path / "cost_mgmt.sqlite3"
    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    _create_admin(str(db_path))
    client.post("/auth/login", data={"username": "admin", "password": "admin12345"})

    page = client.get("/reports")
    assert page.status_code == 200
    assert "tokenForecastChart" not in page.text
    assert "Token Forecast (7d)" not in page.text
    assert "costForecastChart" not in page.text
    assert "OpEx forecast (7d)" not in page.text
    assert "reportCashFlowChart" in page.text
    assert "reportDailyChartCard" in page.text
    assert "report-tokens" in page.text
    assert "projectSummariesTable" in page.text
    assert "report-daily-by-project" not in page.text
    assert "report-glance" in page.text
    assert "reportStatementCompare" in page.text
    assert "reportStatementConnector" in page.text
    assert "reportStatementBridge" not in page.text
    assert "reportOpexCompositionRow" not in page.text
    assert "incomeLineShare" not in page.text
    assert "hero_summary_meta" in page.text
    assert "reportRefArchPanel" in page.text
    assert "reportBenchmarkRow" not in page.text
    assert "reportVolumeRow" in page.text
    assert "reportIncomeStatement" in page.text
    assert "reportIncomeHead" in page.text
    assert "reportCashFlowTieOut" in page.text
    assert "report-raw-data" not in page.text
    assert "filterCard" in page.text
    assert "date-range-picker.js" in page.text
    assert "dateRangePicker" in page.text
    assert "reportStatusBar" in page.text
    assert "reportToolbarGrid" in page.text
    assert "heroMetricGrid" in page.text
    assert "reportUnitRatesPanel" in page.text
    assert "unit-price-table.js" in page.text
    assert "reportUnitRatesScopedTable" in page.text
    assert "reportIncomeSupplement" in page.text
    assert "reportCollapseDetails" in page.text
    assert "reportCashFlowLedgerDetails" in page.text
    assert "reportModelExtrasDetails" in page.text
    assert "reportSectionCard" in page.text
    assert "reportConsumeChartPane" in page.text
    assert "reportAllocBillingVarianceChip" in page.text
    assert "reportAllocMeterVarianceChip" in page.text
    assert "reportModelBillingVarianceChip" in page.text
    assert "reportModelMeterVarianceChip" in page.text
    assert "colGroupVariance--billing" in page.text
    assert "colGroupVariance--meter" in page.text
    assert "colVariance--billing" in page.text
    assert "colVariance--meter" in page.text
    assert "colGroupVariance" in page.text
    assert "reportConsumeStatement" not in page.text


def test_all_financial_report_rejects_invalid_date_range(tmp_path):
    bills_dir = tmp_path / "bills"
    p1 = bills_dir / "projA"
    p1.mkdir(parents=True, exist_ok=True)
    (p1 / "2026.csv").write_text(
        '"UsageDate","CostUSD","Cost","ForecastCost","Currency"\n'
        '"2026-01-01","1.0","1.0","","USD"\n',
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    _create_admin(str(db_path))
    client.post("/auth/login", data={"username": "admin", "password": "admin12345"})

    bad_format = client.get("/api/reports/all-financial?start_date=2026/01/01")
    assert bad_format.status_code == 400
    assert bad_format.json()["detail"] == "start_date must be YYYY-MM-DD"

    bad_order = client.get("/api/reports/all-financial?start_date=2026-01-02&end_date=2026-01-01")
    assert bad_order.status_code == 400
    assert bad_order.json()["detail"] == "start_date must be earlier than or equal to end_date"

    verify_bad_order = client.get(
        "/api/verify/reports-all-financial-consistency?start_date=2026-01-02&end_date=2026-01-01"
    )
    assert verify_bad_order.status_code == 400
    assert verify_bad_order.json()["detail"] == "start_date must be earlier than or equal to end_date"
