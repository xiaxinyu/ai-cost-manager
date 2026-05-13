from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from .ingest import ingest_all
from .main import create_app
from .auth import create_user
from .db import get_connection, init_db
from .bill_sync import sync_csv_file
from .azure_retail_prices import allowed_series_keys, import_openai_retail_prices
from .price_ingest import import_price_csv, import_price_csv_merge


def _default_bills_dir() -> str:
    return str(Path(__file__).resolve().parents[1] / "bills")


def _default_db_path() -> str:
    return str(Path(__file__).resolve().parents[1] / "data" / "cost_mgmt.sqlite3")


def _default_price_csv_path() -> str:
    return str(
        Path(__file__).resolve().parents[1]
        / "bills"
        / "price"
        / "azure_openai_prices_2026-04-29_eastus_usd.csv"
    )


def _default_marketing_merge_csv_path() -> str:
    return str(
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "pricing"
        / "azure_marketing_gpt51_gpt52_eastus2_2026-05-13.csv"
    )


def _default_openai_gpt55_api_csv_path() -> str:
    return str(
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "pricing"
        / "openai_com_api_pricing_gpt55_2026-05-13.csv"
    )


def _cli_common_parent() -> argparse.ArgumentParser:
    """Shared --db-path / --bills-dir on each subcommand (can appear after the subcommand name)."""
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--bills-dir", default=_default_bills_dir(), help="Directory containing bills/<project>/*.csv")
    p.add_argument("--db-path", default=_default_db_path(), help="SQLite database file path")
    return p


def main() -> None:
    common = _cli_common_parent()
    parser = argparse.ArgumentParser(description="Cost management CSV ingestion + web server")

    sub = parser.add_subparsers(dest="cmd", required=True)

    ingest_p = sub.add_parser("ingest", parents=[common], help="Ingest bills/*/*.csv into SQLite")
    ingest_p.add_argument("--reimport-changed", action="store_true", help="Re-import files whose checksum changed")

    admin_p = sub.add_parser("create-admin", parents=[common], help="Create/Update admin user for login")
    admin_p.add_argument("--username", default=os.getenv("COST_MGMT_ADMIN_USER", "admin"))
    admin_p.add_argument("--password", default=os.getenv("COST_MGMT_ADMIN_PASSWORD", "admin12345"))
    admin_p.add_argument("--inactive", action="store_true", help="Create user as inactive")

    serve_p = sub.add_parser("serve", parents=[common], help="Start web server")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8000)

    sync_p = sub.add_parser(
        "sync-bill",
        parents=[common],
        help="Sync an older CSV using a newer CSV (overlapping dates only)",
    )
    sync_p.add_argument("--old", required=True, help="Old CSV path (absolute or relative)")
    sync_p.add_argument("--new", required=True, help="New CSV path (absolute or relative)")
    sync_p.add_argument("--dry-run", action="store_true", help="Compute diff but don't rewrite old file")
    sync_p.add_argument("--float-tol", type=float, default=1e-9, help="Float compare tolerance (abs+rel)")

    price_p = sub.add_parser("import-prices", parents=[common], help="Import model price CSV into SQLite")
    price_p.add_argument("--csv-path", default=_default_price_csv_path(), help="Price CSV path")
    price_p.add_argument(
        "--merge",
        action="store_true",
        help="Only replace rows whose source_id appears in this CSV, then insert (keeps other sources).",
    )

    retail_p = sub.add_parser(
        "import-retail-prices",
        parents=[common],
        help="Merge Azure OpenAI meters from prices.azure.com (replaces only azure_retail_prices_api rows)",
    )
    retail_p.add_argument(
        "--series",
        default="all",
        choices=sorted(allowed_series_keys()),
        help="OData slice to fetch before merge (default: all OpenAI meters)",
    )

    merge_p = sub.add_parser(
        "import-marketing-gpt51-gpt52-prices",
        parents=[common],
        help="Merge East US 2 GPT-5.1/5.2 marketing snapshot (model_series follows model_name: GPT-5.1 vs GPT-5.2)",
    )
    merge_p.add_argument("--csv-path", default=_default_marketing_merge_csv_path(), help="Override CSV path")

    openai55_p = sub.add_parser(
        "import-openai-gpt55-api-prices",
        parents=[common],
        help="Merge OpenAI.com API pricing snapshot for GPT-5.5 / GPT-5.5 Pro (USD per 1M tokens)",
    )
    openai55_p.add_argument("--csv-path", default=_default_openai_gpt55_api_csv_path(), help="Override CSV path")

    args = parser.parse_args()

    bills_dir = args.bills_dir
    db_path = args.db_path

    Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    if args.cmd == "ingest":
        r = ingest_all(bills_dir=bills_dir, db_path=db_path, reimport_changed=bool(args.reimport_changed))
        print(r)
        return

    if args.cmd == "create-admin":
        conn = get_connection(db_path)
        try:
            init_db(conn)
            create_user(
                conn,
                username=str(args.username),
                password=str(args.password),
                is_active=not bool(args.inactive),
            )
            print("admin user ready")
        finally:
            conn.close()
        return

    if args.cmd == "serve":
        # Data should already be ingested; we keep auto_ingest off to avoid surprises.
        app = create_app(db_path=db_path, bills_dir=bills_dir, auto_ingest=False)
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
        return

    if args.cmd == "sync-bill":
        report = sync_csv_file(
            old_path=str(args.old),
            new_path=str(args.new),
            dry_run=bool(args.dry_run),
            float_tol=float(args.float_tol),
        )
        print(report)
        return

    if args.cmd == "import-prices":
        if args.merge:
            result = import_price_csv_merge(db_path=db_path, csv_path=str(args.csv_path))
        else:
            result = import_price_csv(db_path=db_path, csv_path=str(args.csv_path))
        print(result)
        return

    if args.cmd == "import-marketing-gpt51-gpt52-prices":
        result = import_price_csv_merge(db_path=db_path, csv_path=str(args.csv_path))
        print(result)
        return

    if args.cmd == "import-openai-gpt55-api-prices":
        result = import_price_csv_merge(db_path=db_path, csv_path=str(args.csv_path))
        print(result)
        return

    if args.cmd == "import-retail-prices":
        result = import_openai_retail_prices(db_path=db_path, series_key=str(args.series))
        print(result)
        return

    raise RuntimeError("unreachable")


if __name__ == "__main__":
    main()
