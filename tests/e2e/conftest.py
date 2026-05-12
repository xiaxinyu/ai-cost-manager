from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

from app.db import get_connection, init_db, upsert_project_model_config
from app.ingest import ingest_selected
from app.auth import create_user


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _write_csv(path: Path, *, rows: list[dict[str, str]]) -> None:
    headers = [
        "UsageDate",
        "ResourceId",
        "ResourceType",
        "ResourceLocation",
        "ResourceGroupName",
        "ServiceName",
        "ServiceTier",
        "Meter",
        "CostUSD",
        "Cost",
        "Currency",
    ]
    lines = [",".join(headers)]
    for r in rows:
        lines.append(",".join(str(r.get(h, "")) for h in headers))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture(scope="session")
def e2e_server_base_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    root = tmp_path_factory.mktemp("e2e")
    bills_dir = root / "bills"
    db_path = root / "cost_mgmt.sqlite3"

    project = "demo-project"
    proj_dir = bills_dir / project
    proj_dir.mkdir(parents=True, exist_ok=True)

    # Two CSVs: ingest only one so Import page shows 1 missing file.
    csv_a = proj_dir / "cost-a.csv"
    csv_b = proj_dir / "cost-b.csv"

    _write_csv(
        csv_a,
        rows=[
            {
                "UsageDate": "2026-05-01",
                "ResourceId": "/subscriptions/x/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/a",
                "ResourceType": "Microsoft.CognitiveServices/accounts",
                "ResourceLocation": "eastus",
                "ResourceGroupName": "rg",
                "ServiceName": "Azure OpenAI",
                "ServiceTier": "Standard",
                "Meter": "Tokens",
                "CostUSD": "1.00",
                "Cost": "1.00",
                "Currency": "USD",
            },
            {
                "UsageDate": "2026-05-02",
                "ResourceId": "/subscriptions/x/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/a",
                "ResourceType": "Microsoft.CognitiveServices/accounts",
                "ResourceLocation": "eastus",
                "ResourceGroupName": "rg",
                "ServiceName": "Azure OpenAI",
                "ServiceTier": "Standard",
                "Meter": "Tokens",
                "CostUSD": "2.00",
                "Cost": "2.00",
                "Currency": "USD",
            },
        ],
    )
    _write_csv(
        csv_b,
        rows=[
            {
                "UsageDate": "2026-05-03",
                "ResourceId": "/subscriptions/x/resourceGroups/rg/providers/Microsoft.CognitiveServices/accounts/b",
                "ResourceType": "Microsoft.CognitiveServices/accounts",
                "ResourceLocation": "eastus",
                "ResourceGroupName": "rg",
                "ServiceName": "Azure OpenAI",
                "ServiceTier": "Standard",
                "Meter": "Tokens",
                "CostUSD": "3.00",
                "Cost": "3.00",
                "Currency": "USD",
            }
        ],
    )

    # Seed DB + admin user + minimal model prices so tokens/prices pages have real data.
    conn = get_connection(db_path)
    try:
        init_db(conn)
        create_user(conn, username="admin", password="ChangeMe_2026!", is_active=True)

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
                "fixture",
                "https://example.invalid/prices",
                "2026-05-01",
                "2026-05-01T00:00:00Z",
                "Azure",
                "AzureOpenAI",
                "eastus",
                "USD",
                "gpt-4o",
                "gpt-4o-mini",
                None,
                None,
                "standard",
                "input",
                0.5,
                1,
                "1M tokens",
                "USD / 1M tokens",
                "fixture",
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
                "fixture",
                "https://example.invalid/prices",
                "2026-05-01",
                "2026-05-01T00:00:00Z",
                "Azure",
                "AzureOpenAI",
                "eastus",
                "USD",
                "gpt-4o",
                "gpt-4o-mini",
                None,
                None,
                "standard",
                "output",
                1.5,
                1,
                "1M tokens",
                "USD / 1M tokens",
                "fixture",
                None,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Ingest only one CSV so the Import UI has a meaningful action.
    ingest_selected(
        bills_dir=bills_dir,
        db_path=db_path,
        file_path_rels=[f"{project}/{csv_a.name}"],
        reimport_changed=False,
    )

    conn2 = get_connection(db_path)
    try:
        upsert_project_model_config(
            conn2,
            project_name=project,
            model_name="gpt-4o-mini",
            api_version=None,
            azure_endpoint=None,
        )
    finally:
        conn2.close()

    port = _free_port()
    env = {
        **os.environ,
        "COST_MGMT_SESSION_SECRET_KEY": "e2e-secret-key",
        "AUTO_INGEST": "0",
    }
    cmd = [
        sys.executable,
        "-m",
        "app.cli",
        "--bills-dir",
        str(bills_dir),
        "--db-path",
        str(db_path),
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]

    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    base_url = f"http://127.0.0.1:{port}"
    try:
        # Wait for readiness.
        deadline = time.time() + 20
        last_err: Exception | None = None
        while time.time() < deadline:
            try:
                r = requests.get(f"{base_url}/health", timeout=1.5)
                if r.status_code == 200:
                    break
            except Exception as e:
                last_err = e
            time.sleep(0.25)
        else:
            out = ""
            if proc.stdout is not None:
                try:
                    out = proc.stdout.read()[-4000:]
                except Exception:
                    out = ""
            raise RuntimeError(f"e2e server failed to start: {last_err}\n{out}")

        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

