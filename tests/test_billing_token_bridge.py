from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import create_user
from app.db import (
    get_billing_token_bridge,
    get_connection,
    get_imported_token_daily_by_model,
    get_model_implied_usd_per_1m_analysis,
)
from app.ingest import ingest_all
from app.main import create_app
from app.token_ingest import ingest_token_all


def _create_admin(db_path: str) -> None:
    import sqlite3

    from app.db import init_db

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        create_user(conn, username="admin", password="admin12345", is_active=True)
    finally:
        conn.close()


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


def test_billing_token_bridge_and_meter_matched_prices(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projBridge"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)

    _write_foundry_cost(
        project_dir / "cost.csv",
        [
            ("2026-05-12", "5.3 codex inp Gl 1M Tokens", 10.0),
            ("2026-05-12", "5.3 codex opt Gl 1M Tokens", 4.0),
            ("2026-05-12", "5.4 inp Gl 1M Tokens", 0.05),
            ("2026-05-12", "5.4 opt Gl 1M Tokens", 0.02),
        ],
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","gpt-5.3-codex","gpt-5.4"\n'
        "2026-05-12 10:00:00,2 Mil,1 Mil\n",
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","gpt-5.3-codex","gpt-5.4"\n'
        "2026-05-12 10:00:00,200 K,50 K\n",
        encoding="utf-8",
    )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    conn = get_connection(db_path)
    try:
        bridge = get_billing_token_bridge(conn, "projBridge", currency="USD")
        assert bridge["available"] is True
        assert bridge["parse_rate_by_cost"] == 1.0
        assert "gpt-5.3-codex" in bridge["billing_models"]
        assert "gpt-5.4" in bridge["billing_models"]
        assert "gpt-5.3-codex" in bridge["token_models"]
        assert "gpt-5.4" in bridge["token_models"]
        assert bridge["billing_models_without_tokens"] == []
        assert bridge["token_models_without_billing"] == []

        payload = get_model_implied_usd_per_1m_analysis(conn, "projBridge", currency="USD")
        assert payload["allocation_method"] == "meter_matched"
        by_name = {m["model_name"]: m for m in payload["models"]}
        codex = next(d for d in by_name["gpt-5.3-codex"]["daily"] if d["date"] == "2026-05-12")
        g54 = next(d for d in by_name["gpt-5.4"]["daily"] if d["date"] == "2026-05-12")

        assert codex["allocation_method"] == "meter_matched"
        assert abs(codex["cost_usd_allocated"] - 14.0) < 1e-6
        assert abs(codex["usd_per_1m_input"] - 5.0) < 1e-6  # 10 / 2M * 1e6
        assert abs(codex["usd_per_1m_output"] - 20.0) < 1e-6  # 4 / 200K * 1e6

        assert g54["allocation_method"] == "meter_matched"
        assert abs(g54["cost_usd_allocated"] - 0.07) < 1e-6
        assert abs(g54["usd_per_1m_input"] - 0.05) < 1e-6
        assert abs(g54["usd_per_1m_output"] - 0.4) < 1e-6  # 0.02 / 50K * 1e6

        daily = get_imported_token_daily_by_model(conn, "projBridge", currency="USD")
        daily_by_key = {(str(r["date"]), str(r["model_name"])): r for r in daily}
        d_codex = daily_by_key[("2026-05-12", "gpt-5.3-codex")]
        d_g54 = daily_by_key[("2026-05-12", "gpt-5.4")]
        assert d_codex["allocation_method"] == "meter_matched"
        assert abs(float(d_codex["input_cost_usd"]) - 10.0) < 1e-6
        assert abs(float(d_codex["output_cost_usd"]) - 4.0) < 1e-6
        assert abs(float(d_codex["total_cost_usd"]) - 14.0) < 1e-6
        assert d_g54["allocation_method"] == "meter_matched"
        assert abs(float(d_g54["input_cost_usd"]) - 0.05) < 1e-6
        assert abs(float(d_g54["output_cost_usd"]) - 0.02) < 1e-6
    finally:
        conn.close()


def test_no_proportional_when_meters_unparsed(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projPlain"
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
        payload = get_model_implied_usd_per_1m_analysis(conn, "projPlain", currency="USD")
        assert payload["allocation_method"] == "no_meter_match"
        assert all(not m.get("daily") for m in payload["models"])
        daily = get_imported_token_daily_by_model(conn, "projPlain", currency="USD")
        assert daily[0]["allocation_method"] == "no_meter_match"
        assert daily[0]["total_cost_usd"] is None
        assert daily[0]["usd_per_1m_input"] is None
        assert daily[0]["usd_per_1m_output"] is None
    finally:
        conn.close()


def test_billing_token_bridge_api(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projBridge"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)
    _write_foundry_cost(
        project_dir / "cost.csv",
        [("2026-05-12", "5.3 codex inp Gl 1M Tokens", 1.0)],
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n2026-05-12 10:00:00,1 Mil\n',
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","gpt-5.3-codex"\n2026-05-12 10:00:00,10 K\n',
        encoding="utf-8",
    )
    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    _create_admin(str(db_path))
    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    res = client.get("/api/projects/projBridge/billing-token-bridge?currency=USD")
    assert res.status_code == 200
    data = res.json()
    assert data["available"] is True
    assert data["parse_rate_by_cost"] == 1.0
    assert "gpt-5.3-codex" in data["billing_models"]


def test_variant_model_labels_still_bridge_and_daily_rows(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projVariant"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)
    _write_foundry_cost(
        project_dir / "cost.csv",
        [
            ("2026-05-12", "GPT 5.3 codex input Gl 1M Tokens", 8.0),
            ("2026-05-12", "GPT 5.3 codex output Gl 1M Tokens", 3.0),
            ("2026-05-12", "GPT 5.4 input Gl 1M Tokens", 0.06),
            ("2026-05-12", "GPT 5.4 output Gl 1M Tokens", 0.03),
        ],
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","GPT 5.3 CODEX","GPT5.4"\n'
        "2026-05-12 10:00:00,2 Mil,1 Mil\n",
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","GPT 5.3 CODEX","GPT5.4"\n'
        "2026-05-12 10:00:00,200 K,50 K\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    conn = get_connection(db_path)
    try:
        bridge = get_billing_token_bridge(conn, "projVariant", currency="USD")
        assert bridge["available"] is True
        assert bridge["billing_models_without_tokens"] == []
        assert bridge["token_models_without_billing"] == []
        assert "gpt-5.3-codex" in bridge["billing_models"]
        assert "gpt-5.4" in bridge["billing_models"]

        daily = get_imported_token_daily_by_model(conn, "projVariant")
        assert len(daily) == 2
        model_names = sorted({str(r["model_name"]) for r in daily})
        assert model_names == ["gpt-5.3-codex", "gpt-5.4"]

        payload = get_model_implied_usd_per_1m_analysis(conn, "projVariant", currency="USD")
        assert payload["allocation_method"] == "meter_matched"
        by_name = {m["model_name"]: m for m in payload["models"]}
        assert "gpt-5.3-codex" in by_name
        assert "gpt-5.4" in by_name
    finally:
        conn.close()


def _write_foundry_cost_with_resources(
    path,
    rows: list[tuple[str, str, float, str]],
) -> None:
    lines = [
        '"UsageDate","ResourceId","ResourceType","ResourceLocation","ResourceGroupName",'
        '"ServiceName","ServiceTier","Meter","CostUSD","Cost","Currency"'
    ]
    for usage_date, meter, cost, slug in rows:
        rid = (
            f"/subscriptions/x/resourcegroups/rg/providers/"
            f"microsoft.cognitiveservices/accounts/{slug}"
        )
        lines.append(
            f'"{usage_date}","{rid}","microsoft.cognitiveservices/accounts","US East 2",'
            f'"rg","Foundry Models","Azure OpenAI GPT5","{meter}","{cost}","{cost}","USD"'
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_subproject_meter_cost_scoped_to_resource(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projSub"
    token_sp1 = project_dir / "token" / "sp-one"
    token_sp2 = project_dir / "token" / "sp-two"
    token_sp1.mkdir(parents=True)
    token_sp2.mkdir(parents=True)

    _write_foundry_cost_with_resources(
        project_dir / "cost.csv",
        [
            ("2026-05-12", "5.3 codex inp Gl 1M Tokens", 10.0, "sp-one"),
            ("2026-05-12", "5.3 codex opt Gl 1M Tokens", 4.0, "sp-one"),
            ("2026-05-12", "5.3 codex inp Gl 1M Tokens", 2.0, "sp-two"),
            ("2026-05-12", "5.3 codex opt Gl 1M Tokens", 1.0, "sp-two"),
        ],
    )
    for token_dir, amount in ((token_sp1, "2 Mil"), (token_sp2, "1 Mil")):
        (token_dir / "input-tokens.csv").write_text(
            '"Time","gpt-5.3-codex"\n'
            f"2026-05-12 10:00:00,{amount}\n",
            encoding="utf-8",
        )
        (token_dir / "output-tokens.csv").write_text(
            '"Time","gpt-5.3-codex"\n'
            "2026-05-12 10:00:00,100 K\n",
            encoding="utf-8",
        )

    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    conn = get_connection(db_path)
    try:
        sp1 = get_imported_token_daily_by_model(
            conn, "projSub", currency="USD", subproject_name="sp-one"
        )
        row = next(r for r in sp1 if r["date"] == "2026-05-12")
        assert row["allocation_method"] == "meter_matched"
        assert abs(float(row["input_cost_usd"]) - 10.0) < 1e-6
        assert abs(float(row["output_cost_usd"]) - 4.0) < 1e-6
        assert abs(float(row["usd_per_1m_input"]) - 5.0) < 1e-6
        assert abs(float(row["usd_per_1m_output"]) - 40.0) < 1e-6

        payload = get_model_implied_usd_per_1m_analysis(
            conn, "projSub", currency="USD", subproject_name="sp-two"
        )
        codex = next(m for m in payload["models"] if m["model_name"] == "gpt-5.3-codex")
        assert codex["period_effective_usd_per_1m_input"] == 2.0
        assert codex["period_effective_usd_per_1m_output"] == 10.0
    finally:
        conn.close()


def test_daily_cost_mapping_for_explicit_53_codex_and_54_inp_opt(tmp_path):
    bills_dir = tmp_path / "bills"
    project_dir = bills_dir / "projMap"
    token_dir = project_dir / "token"
    token_dir.mkdir(parents=True)
    _write_foundry_cost(
        project_dir / "cost.csv",
        [
            ("2026-05-12", "5.3 codex inp", 12.0),
            ("2026-05-12", "5.3 codex opt", 6.0),
            ("2026-05-12", "5.4 inp", 0.2),
            ("2026-05-12", "5.4 opt", 0.1),
        ],
    )
    (token_dir / "input-tokens.csv").write_text(
        '"Time","gpt-5.3-codex","gpt-5.4"\n'
        "2026-05-12 10:00:00,3 Mil,1 Mil\n",
        encoding="utf-8",
    )
    (token_dir / "output-tokens.csv").write_text(
        '"Time","gpt-5.3-codex","gpt-5.4"\n'
        "2026-05-12 10:00:00,300 K,100 K\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "cost_mgmt.sqlite3"
    ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)
    ingest_token_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=False)

    conn = get_connection(db_path)
    try:
        daily = get_imported_token_daily_by_model(conn, "projMap", currency="USD")
        by_key = {(str(r["date"]), str(r["model_name"])): r for r in daily}
        d53 = by_key[("2026-05-12", "gpt-5.3-codex")]
        d54 = by_key[("2026-05-12", "gpt-5.4")]
        assert d53["allocation_method"] == "meter_matched"
        assert abs(float(d53["input_cost_usd"]) - 12.0) < 1e-6
        assert abs(float(d53["output_cost_usd"]) - 6.0) < 1e-6
        assert abs(float(d53["total_cost_usd"]) - 18.0) < 1e-6
        assert d54["allocation_method"] == "meter_matched"
        assert abs(float(d54["input_cost_usd"]) - 0.2) < 1e-6
        assert abs(float(d54["output_cost_usd"]) - 0.1) < 1e-6
        assert abs(float(d54["total_cost_usd"]) - 0.3) < 1e-6
    finally:
        conn.close()
