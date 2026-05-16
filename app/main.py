from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Body, Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel

from .db import (
    clear_all_model_prices,
    get_cost_forecast_baseline,
    get_forecast_model_unit_prices,
    get_model_price_by_id,
    get_model_price_filter_options,
    get_model_prices,
    get_model_prices_meta,
    get_project_model_config,
    get_all_currencies,
    get_all_financial_stats,
    get_available_currencies,
    get_connection,
    get_project_stats,
    get_rows,
    get_imported_token_breakdown_by_model,
    get_imported_token_models_with_prices,
    get_imported_token_meta,
    get_token_timeseries,
    get_all_token_timeseries,
    verify_all_financial_consistency,
    get_model_implied_usd_per_1m_analysis,
    get_project_daily_implied_usd_per_1m_timeseries,
    get_timeseries,
    init_db,
    list_forecast_model_catalog,
    list_price_source_catalog,
    list_projects,
    list_projects_with_imported_tokens,
    update_price_source_catalog_row,
    upsert_project_model_config,
)
from .ingest import ingest_all, ingest_selected, list_ingested_files, list_missing_files, verify_ingested_files
from .token_ingest import (
    ingest_token_all,
    ingest_token_selected,
    list_ingested_token_files,
    list_missing_token_files,
    verify_ingested_token_files,
)
from .auth import authenticate_user, require_active_user


class ImportRunRequest(BaseModel):
    reimport_changed: bool = False
    file_path_rels: Optional[list[str]] = None


class ProjectModelConfigRequest(BaseModel):
    model_name: str
    api_version: Optional[str] = None
    azure_endpoint: Optional[str] = None


class RetailSyncBody(BaseModel):
    series: str = "all"
    probe_marketing: bool = False
    arm_region: Optional[str] = None


class PriceSourcePatchBody(BaseModel):
    title: Optional[str] = None
    reference_url: Optional[str] = None
    api_url: Optional[str] = None
    notes: Optional[str] = None


def _default_bills_dir() -> str:
    return str(Path(__file__).resolve().parents[1] / "bills")


def _default_db_path() -> str:
    return str(Path(__file__).resolve().parents[1] / "data" / "cost_mgmt.sqlite3")


def create_app(
    *,
    db_path: str,
    bills_dir: str,
    auto_ingest: bool = True,
) -> FastAPI:
    templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        Path(db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        conn = get_connection(db_path)
        try:
            init_db(conn)
        finally:
            conn.close()
        yield

    app = FastAPI(title="Models Cost Management", version="1.0.0", lifespan=_lifespan)

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    auth_enabled = os.getenv("COST_MGMT_AUTH_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
    session_secret_key = os.getenv("COST_MGMT_SESSION_SECRET_KEY", "").strip()
    if not session_secret_key:
        # Dev fallback: for production you MUST set COST_MGMT_SESSION_SECRET_KEY.
        session_secret_key = "dev-insecure-change-me"
    cookie_secure = os.getenv("COST_MGMT_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes", "on"}

    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret_key,
        session_cookie="cost_mgmt_session",
        same_site="lax",
        https_only=cookie_secure,
    )

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        # Hardening headers (inline script for page JS; Chart.js served from /static).
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "object-src 'none'; "
            "form-action 'self'; "
        )
        return response

    def _auth_dep(request: Request) -> str:
        if not auth_enabled:
            return "anonymous"
        return require_active_user(request, db_path=db_path)

    def _price_source_catalog_snapshot() -> list[dict[str, object]]:
        conn = get_connection(db_path)
        try:
            init_db(conn)
            return list_price_source_catalog(conn)
        finally:
            conn.close()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        err = request.query_params.get("error", "").strip().lower()
        login_error = err if err == "invalid" else None
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "auth_enabled": auth_enabled,
                "login_error": login_error,
            },
        )

    @app.post("/auth/login")
    def login_submit(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
    ):
        if not auth_enabled:
            return RedirectResponse(url="/", status_code=303)

        conn = get_connection(db_path)
        try:
            ok = authenticate_user(conn, username=username, password=password)
            if not ok:
                # Browser-friendly: same themed page as /login (avoid plain-text 401).
                return RedirectResponse(url="/login?error=invalid", status_code=303)
        finally:
            conn.close()

        request.session["username"] = username
        return RedirectResponse(url="/", status_code=303)

    @app.post("/auth/logout")
    def logout(request: Request):
        request.session.pop("username", None)
        return RedirectResponse(url="/login", status_code=303)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        if auth_enabled:
            # If not logged in, show login page.
            username = request.session.get("username")
            if not username:
                return RedirectResponse(url="/login", status_code=303)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "default_db_path": db_path,
                "default_bills_dir": bills_dir,
                "username": request.session.get("username", ""),
            },
        )

    @app.get("/import", response_class=HTMLResponse)
    def import_page(request: Request) -> HTMLResponse:
        if auth_enabled:
            username = request.session.get("username")
            if not username:
                return RedirectResponse(url="/login", status_code=303)
        return templates.TemplateResponse(
            request,
            "import.html",
            {"username": request.session.get("username", "")},
        )

    @app.get("/reports", response_class=HTMLResponse)
    def reports_page(request: Request) -> HTMLResponse:
        if auth_enabled:
            username = request.session.get("username")
            if not username:
                return RedirectResponse(url="/login", status_code=303)
        return templates.TemplateResponse(
            request,
            "reports.html",
            {"username": request.session.get("username", "")},
        )

    @app.get("/tokens", response_class=HTMLResponse)
    def tokens_page(request: Request) -> HTMLResponse:
        if auth_enabled:
            username = request.session.get("username")
            if not username:
                return RedirectResponse(url="/login", status_code=303)
        return templates.TemplateResponse(
            request,
            "tokens.html",
            {"username": request.session.get("username", "")},
        )

    @app.get("/forecast", response_class=HTMLResponse)
    def forecast_page(request: Request) -> HTMLResponse:
        if auth_enabled:
            username = request.session.get("username")
            if not username:
                return RedirectResponse(url="/login", status_code=303)
        return templates.TemplateResponse(
            request,
            "forecast.html",
            {"username": request.session.get("username", "")},
        )

    @app.get("/prices", response_class=HTMLResponse)
    def prices_page(request: Request) -> HTMLResponse:
        if auth_enabled:
            username = request.session.get("username")
            if not username:
                return RedirectResponse(url="/login", status_code=303)
        return templates.TemplateResponse(
            request,
            "prices.html",
            {"username": request.session.get("username", "")},
        )

    @app.get("/price-sources", response_class=HTMLResponse)
    def price_sources_page(request: Request) -> HTMLResponse:
        if auth_enabled:
            username = request.session.get("username")
            if not username:
                return RedirectResponse(url="/login", status_code=303)
        return templates.TemplateResponse(
            request,
            "price-sources.html",
            {"username": request.session.get("username", "")},
        )

    @app.get("/api/projects")
    def api_projects(_: str = Depends(_auth_dep)) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            projects = list_projects(conn)
            token_projects = list_projects_with_imported_tokens(conn)
            return JSONResponse(
                {
                    "projects": projects,
                    "projects_with_imported_tokens": token_projects,
                }
            )
        finally:
            conn.close()

    @app.get("/api/projects/latest-token")
    def api_projects_latest_token(_: str = Depends(_auth_dep)) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                """
                SELECT project_name
                FROM ingested_token_files
                ORDER BY ingested_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
            return JSONResponse({"project_name": row["project_name"] if row else None})
        finally:
            conn.close()

    @app.get("/api/projects/latest")
    def api_projects_latest(_: str = Depends(_auth_dep)) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            row = conn.execute(
                """
                SELECT project_name
                FROM ingested_files
                ORDER BY ingested_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
            return JSONResponse({"project_name": row["project_name"] if row else None})
        finally:
            conn.close()

    @app.get("/api/projects/{project_name}/stats")
    def api_project_stats(
        project_name: str,
        from_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        to_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        currency: Optional[str] = Query(default=None, description="Currency code"),
        _: str = Depends(_auth_dep),
    ) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            stats = get_project_stats(conn, project_name, from_date=from_date, to_date=to_date, currency=currency)
            return JSONResponse(
                {
                    "project": stats.project_name,
                    "currency": stats.currency,
                    "from_date": stats.from_date,
                    "to_date": stats.to_date,
                    "min_usage_date": stats.min_usage_date,
                    "max_usage_date": stats.max_usage_date,
                    "actual_cost_usd_total": stats.actual_cost_usd_total,
                    "actual_days": stats.actual_days,
                    "estimated_input_tokens": stats.estimated_input_tokens,
                    "estimated_output_tokens": stats.estimated_output_tokens,
                    "estimated_total_tokens": stats.estimated_total_tokens,
                    "token_estimate_model": stats.token_estimate_model,
                    "token_data_source": stats.token_data_source,
                }
            )
        finally:
            conn.close()

    @app.get("/api/projects/{project_name}/model-unit-prices")
    def api_model_unit_prices(
        project_name: str,
        start_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        currency: Optional[str] = Query(default=None, description="Currency code"),
        _: str = Depends(_auth_dep),
    ) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            payload = get_model_implied_usd_per_1m_analysis(
                conn,
                project_name,
                start_date=start_date,
                end_date=end_date,
                currency=currency,
            )
            return JSONResponse(payload)
        finally:
            conn.close()

    @app.get("/api/projects/{project_name}/implied-unit-prices-timeseries")
    def api_implied_unit_prices_timeseries(
        project_name: str,
        start_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        currency: Optional[str] = Query(default=None, description="Currency code"),
        _: str = Depends(_auth_dep),
    ) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            payload = get_project_daily_implied_usd_per_1m_timeseries(
                conn,
                project_name,
                start_date=start_date,
                end_date=end_date,
                currency=currency,
            )
            return JSONResponse(payload)
        finally:
            conn.close()

    @app.get("/api/projects/{project_name}/timeseries")
    def api_timeseries(
        project_name: str,
        start_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        granularity: str = Query(default="day", description="day|month"),
        currency: Optional[str] = Query(default=None, description="Currency code"),
        _: str = Depends(_auth_dep),
    ) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            points, chosen_currency = get_timeseries(
                conn,
                project_name,
                start_date=start_date,
                end_date=end_date,
                granularity=granularity,
                currency=currency,
            )
            if currency is None:
                available = get_available_currencies(conn, project_name)
            else:
                available = [currency]

            return JSONResponse(
                {
                    "project": project_name,
                    "currency": chosen_currency,
                    "available_currencies": available,
                    "granularity": granularity,
                    "points": points,
                }
            )
        finally:
            conn.close()

    @app.get("/api/projects/{project_name}/forecast-baseline")
    def api_forecast_baseline(
        project_name: str,
        window_days: int = Query(default=28, ge=7, le=90),
        currency: Optional[str] = Query(default=None),
        _: str = Depends(_auth_dep),
    ) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            out = get_cost_forecast_baseline(
                conn, project_name, window_days=window_days, currency=currency
            )
            return JSONResponse(out)
        finally:
            conn.close()

    @app.get("/api/forecast/model-catalog")
    def api_forecast_model_catalog(_: str = Depends(_auth_dep)) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            opts = list_forecast_model_catalog(conn)
            return JSONResponse({"options": opts})
        finally:
            conn.close()

    @app.get("/api/forecast/model-unit-prices")
    def api_forecast_model_unit_prices(
        vendor: str = Query(..., min_length=1),
        platform: str = Query(..., min_length=1),
        model_series: str = Query(..., min_length=1),
        model_name: str = Query(..., min_length=1),
        price_region: Optional[str] = Query(default=None, description="omit or empty = any region"),
        deployment_scope: Optional[str] = Query(default="global"),
        billing_mode: str = Query(default="standard"),
        _: str = Depends(_auth_dep),
    ) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            pr = (price_region.strip() if price_region else None) or None
            out = get_forecast_model_unit_prices(
                conn,
                vendor=vendor,
                platform=platform,
                model_series=model_series,
                model_name=model_name,
                price_region=pr,
                deployment_scope=(deployment_scope.strip() if deployment_scope else None),
                billing_mode=billing_mode,
            )
            return JSONResponse(out)
        finally:
            conn.close()

    @app.get("/api/projects/{project_name}/token-timeseries")
    def api_token_timeseries(
        project_name: str,
        start_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        granularity: str = Query(default="day", description="day|month"),
        currency: Optional[str] = Query(default=None, description="Currency code"),
        _: str = Depends(_auth_dep),
    ) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            points, chosen_currency, model_name, token_region, token_data_source = get_token_timeseries(
                conn,
                project_name,
                start_date=start_date,
                end_date=end_date,
                granularity=granularity,
                currency=currency,
            )
            if token_data_source == "imported":
                available = []
            elif currency is None:
                available = get_available_currencies(conn, project_name)
            else:
                available = [currency]

            payload: dict[str, object] = {
                "project": project_name,
                "currency": chosen_currency,
                "available_currencies": available,
                "granularity": granularity,
                "token_estimate_model": model_name,
                "token_estimate_region": token_region,
                "token_data_source": token_data_source,
                "points": points,
            }
            if token_data_source == "imported":
                payload["import_meta"] = get_imported_token_meta(
                    conn,
                    project_name,
                    start_date=start_date,
                    end_date=end_date,
                )
                payload["breakdown_by_model"] = get_imported_token_breakdown_by_model(
                    conn,
                    project_name,
                    start_date=start_date,
                    end_date=end_date,
                )
                payload["models_with_prices"] = get_imported_token_models_with_prices(
                    conn,
                    project_name,
                    start_date=start_date,
                    end_date=end_date,
                )
            return JSONResponse(payload)
        finally:
            conn.close()

    @app.get("/api/projects/{project_name}/rows")
    def api_rows(
        project_name: str,
        start_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        currency: Optional[str] = Query(default=None, description="Currency code"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
        mode: str = Query(default="simple", description="simple|full"),
        _: str = Depends(_auth_dep),
    ) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            result = get_rows(
                conn,
                project_name,
                start_date=start_date,
                end_date=end_date,
                currency=currency,
                page=page,
                page_size=page_size,
                mode=mode,
            )
            return JSONResponse(result)
        finally:
            conn.close()

    @app.get("/api/projects/{project_name}/model-config")
    def api_project_model_config(
        project_name: str,
        _: str = Depends(_auth_dep),
    ) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            cfg = get_project_model_config(conn, project_name)
            return JSONResponse({"project_name": project_name, "config": cfg})
        finally:
            conn.close()

    @app.put("/api/projects/{project_name}/model-config")
    def api_project_model_config_upsert(
        project_name: str,
        req: ProjectModelConfigRequest = Body(...),
        _: str = Depends(_auth_dep),
    ) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            upsert_project_model_config(
                conn,
                project_name=project_name,
                model_name=req.model_name.strip(),
                api_version=(req.api_version or "").strip() or None,
                azure_endpoint=(req.azure_endpoint or "").strip() or None,
            )
            cfg = get_project_model_config(conn, project_name)
            return JSONResponse({"project_name": project_name, "config": cfg})
        finally:
            conn.close()

    @app.get("/api/import/missing-files")
    def api_missing_files(_: str = Depends(_auth_dep)) -> JSONResponse:
        billing = list_missing_files(bills_dir=bills_dir, db_path=db_path)
        token = list_missing_token_files(bills_dir=bills_dir, db_path=db_path)
        missing = sorted(
            [*billing, *token],
            key=lambda x: float(x.get("source_last_modified") or 0),
            reverse=True,
        )
        return JSONResponse(
            {
                "missing_count": len(missing),
                "missing_billing_count": len(billing),
                "missing_token_count": len(token),
                "missing_files": missing,
            }
        )

    def _is_token_file_path(file_path_rel: str) -> bool:
        parts = Path(file_path_rel).parts
        return len(parts) >= 2 and parts[1].lower() == "token"

    @app.post("/api/import/run")
    def api_import_run(
        req: ImportRunRequest = Body(...),
        _: str = Depends(_auth_dep),
    ) -> JSONResponse:
        try:
            billing_paths: list[str] | None = None
            token_paths: list[str] | None = None
            if req.file_path_rels is not None:
                billing_paths = [p for p in req.file_path_rels if not _is_token_file_path(p)]
                token_paths = [p for p in req.file_path_rels if _is_token_file_path(p)]

            if req.file_path_rels is None:
                billing_result = ingest_all(
                    bills_dir=bills_dir, db_path=db_path, reimport_changed=req.reimport_changed
                )
                token_result = ingest_token_all(
                    bills_dir=bills_dir, db_path=db_path, reimport_changed=req.reimport_changed
                )
            else:
                billing_result = ingest_selected(
                    bills_dir=bills_dir,
                    db_path=db_path,
                    file_path_rels=billing_paths,
                    reimport_changed=req.reimport_changed,
                )
                token_result = ingest_token_selected(
                    bills_dir=bills_dir,
                    db_path=db_path,
                    file_path_rels=token_paths,
                    reimport_changed=req.reimport_changed,
                )

            verification_passed = (
                billing_result.verification_passed and token_result.verification_passed
            )
            return JSONResponse(
                {
                    "projects_discovered": billing_result.projects_discovered
                    + token_result.projects_discovered,
                    "files_discovered": billing_result.files_discovered + token_result.files_discovered,
                    "files_skipped": billing_result.files_skipped + token_result.files_skipped,
                    "files_ingested": billing_result.files_ingested + token_result.files_ingested,
                    "rows_ingested": billing_result.rows_ingested + token_result.rows_ingested,
                    "files_verified": billing_result.files_verified + token_result.files_verified,
                    "verification_passed": verification_passed,
                    "billing_files_ingested": billing_result.files_ingested,
                    "token_files_ingested": token_result.files_ingested,
                    "billing_rows_ingested": billing_result.rows_ingested,
                    "token_rows_ingested": token_result.rows_ingested,
                    "price_source_catalog": _price_source_catalog_snapshot(),
                }
            )
        except Exception as e:
            # Keep API 200 so the UI can visualize the audit failure reason.
            return JSONResponse(
                {
                    "projects_discovered": 0,
                    "files_discovered": 0,
                    "files_skipped": 0,
                    "files_ingested": 0,
                    "rows_ingested": 0,
                    "files_verified": 0,
                    "verification_passed": False,
                    "import_error": str(e),
                    "price_source_catalog": _price_source_catalog_snapshot(),
                }
            )

    @app.get("/api/import/verify-ingested-files")
    def api_verify_ingested_files(
        limit: int = Query(default=50, ge=1, le=200),
        file_path_rels: Optional[list[str]] = Query(
            default=None,
            description="Verify exactly these ingested file_path_rel values (repeat the query param).",
        ),
        _: str = Depends(_auth_dep),
    ) -> JSONResponse:
        try:
            billing_paths: list[str] | None = None
            token_paths: list[str] | None = None
            if file_path_rels is not None:
                billing_paths = [p for p in file_path_rels if not _is_token_file_path(p)]
                token_paths = [p for p in file_path_rels if _is_token_file_path(p)]

            items: list[dict[str, object]] = []
            pass_count = 0
            fail_count = 0

            if file_path_rels is None or billing_paths:
                billing_result = verify_ingested_files(
                    bills_dir=bills_dir,
                    db_path=db_path,
                    limit=limit,
                    file_path_rels=billing_paths,
                )
                pass_count += billing_result.pass_count
                fail_count += billing_result.fail_count
                items.extend(
                    {
                        "file_path_rel": it.file_path_rel,
                        "pass": it.pass_check,
                        "error": it.error,
                    }
                    for it in billing_result.items
                )

            if file_path_rels is None or token_paths:
                token_result = verify_ingested_token_files(
                    bills_dir=bills_dir,
                    db_path=db_path,
                    limit=limit,
                    file_path_rels=token_paths,
                )
                pass_count += token_result.pass_count
                fail_count += token_result.fail_count
                items.extend(
                    {
                        "file_path_rel": it.file_path_rel,
                        "pass": it.pass_check,
                        "error": it.error,
                    }
                    for it in token_result.items
                )
            return JSONResponse(
                {
                    "limit": limit,
                    "ok": fail_count == 0,
                    "pass_count": pass_count,
                    "fail_count": fail_count,
                    "items": items,
                }
            )
        except Exception as e:
            return JSONResponse(
                {
                    "limit": limit,
                    "ok": False,
                    "pass_count": 0,
                    "fail_count": 1,
                    "items": [],
                    "import_error": str(e),
                }
            )

    @app.get("/api/import/ingested-files")
    def api_ingested_files(
        limit: int = Query(default=50, ge=1, le=200),
        _: str = Depends(_auth_dep),
    ) -> JSONResponse:
        billing = list_ingested_files(db_path=db_path, limit=limit)
        token = list_ingested_token_files(db_path=db_path, limit=limit)
        files = sorted(
            [*billing, *token],
            key=lambda x: str(x.get("ingested_at") or ""),
            reverse=True,
        )[:limit]
        return JSONResponse({"limit": limit, "files": files})

    @app.get("/api/reports/all-financial")
    def api_all_financial_reports(
        start_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        currency: Optional[str] = Query(default=None, description="Currency code"),
        project_names: Optional[list[str]] = Query(
            default=None,
            description="Filter by project names (repeat the query param for multiple values). Example: project_names=projA&project_names=projB",
        ),
        _: str = Depends(_auth_dep),
    ) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            currencies = get_all_currencies(
                conn,
                start_date=start_date,
                end_date=end_date,
                project_names=project_names,
            )
            stats = get_all_financial_stats(
                conn,
                start_date=start_date,
                end_date=end_date,
                currency=currency,
                project_names=project_names,
            )

            chosen_currency = stats.get("currency")
            (
                token_daily_points,
                token_model_display,
                token_region_display,
                token_data_source,
            ) = get_all_token_timeseries(
                conn,
                start_date=start_date,
                end_date=end_date,
                granularity="day",
                currency=chosen_currency,
                project_names=project_names,
            )
            token_monthly_points, _, _, _ = get_all_token_timeseries(
                conn,
                start_date=start_date,
                end_date=end_date,
                granularity="month",
                currency=chosen_currency,
                project_names=project_names,
            )
            return JSONResponse(
                {
                    "currency_options": currencies,
                    **stats,
                    "token_daily_points": token_daily_points,
                    "token_monthly_points": token_monthly_points,
                    "token_estimate_model_display": token_model_display,
                    "token_estimate_region_display": token_region_display,
                    "token_data_source": token_data_source,
                }
            )
        finally:
            conn.close()

    @app.get("/api/verify/reports-all-financial-consistency")
    def api_verify_all_financial_consistency(
        start_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
        currency: Optional[str] = Query(default=None, description="Currency code"),
        project_names: Optional[list[str]] = Query(
            default=None,
            description="Filter by project names (repeat the query param for multiple values). Example: project_names=projA&project_names=projB",
        ),
        mode: str = Query(default="quick", description="quick|deep"),
        _: str = Depends(_auth_dep),
    ) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            result = verify_all_financial_consistency(
                conn,
                start_date=start_date,
                end_date=end_date,
                currency=currency,
                project_names=project_names,
                mode=mode,
            )
            return JSONResponse(result)
        finally:
            conn.close()

    @app.get("/api/prices/filters")
    def api_price_filters(_: str = Depends(_auth_dep)) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            return JSONResponse(get_model_price_filter_options(conn))
        finally:
            conn.close()

    @app.get("/api/prices/meta")
    def api_prices_meta(_: str = Depends(_auth_dep)) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            return JSONResponse(get_model_prices_meta(conn))
        finally:
            conn.close()

    @app.get("/api/prices")
    def api_prices(
        vendor: Optional[str] = Query(default=None),
        platform: Optional[str] = Query(default=None),
        model_series: Optional[str] = Query(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=100, ge=1, le=500),
        _: str = Depends(_auth_dep),
    ) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            rows, total = get_model_prices(
                conn,
                vendor=vendor,
                platform=platform,
                model_series=model_series,
                page=page,
                page_size=page_size,
            )
            return JSONResponse(
                {
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "rows": rows,
                }
            )
        finally:
            conn.close()

    @app.get("/api/prices/sync-series-options")
    def api_prices_sync_series_options(_: str = Depends(_auth_dep)) -> JSONResponse:
        from .azure_retail_prices import sync_series_options

        return JSONResponse({"series": sync_series_options()})

    @app.post("/api/prices/sync-retail")
    async def api_prices_sync_retail(body: RetailSyncBody, _: str = Depends(_auth_dep)) -> JSONResponse:
        from .azure_retail_prices import (
            allowed_series_keys,
            import_openai_retail_prices,
            probe_azure_marketing_pricing_endpoints,
        )

        if body.series not in allowed_series_keys():
            raise HTTPException(status_code=400, detail="invalid series key")

        marketing = None
        if body.probe_marketing:
            marketing = await asyncio.to_thread(probe_azure_marketing_pricing_endpoints)

        try:
            result = await asyncio.to_thread(
                import_openai_retail_prices,
                db_path=str(db_path),
                series_key=body.series,
                arm_region=body.arm_region,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

        return JSONResponse(
            {
                "ok": True,
                "retail": {
                    "rows_fetched": result.rows_fetched,
                    "rows_imported": result.rows_imported,
                    "retail_rows_deleted": result.retail_rows_deleted,
                    "retrieved_at_utc": result.retrieved_at_utc,
                    "filter_url": result.filter_url,
                },
                "marketing_probe": marketing,
                "price_source_catalog": _price_source_catalog_snapshot(),
            }
        )

    @app.post("/api/prices/clear-all")
    def api_prices_clear_all(_: str = Depends(_auth_dep)) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            init_db(conn)
            deleted = clear_all_model_prices(conn)
            return JSONResponse({"ok": True, "deleted": deleted})
        finally:
            conn.close()

    @app.get("/api/price-sources")
    def api_price_sources_list(_: str = Depends(_auth_dep)) -> JSONResponse:
        return JSONResponse({"sources": _price_source_catalog_snapshot()})

    @app.patch("/api/price-sources/{row_id}")
    def api_price_sources_patch(
        row_id: int,
        body: PriceSourcePatchBody = Body(...),
        _: str = Depends(_auth_dep),
    ) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            init_db(conn)
            out = update_price_source_catalog_row(
                conn,
                row_id,
                title=body.title,
                reference_url=body.reference_url,
                api_url=body.api_url,
                notes=body.notes,
            )
            if out is None:
                raise HTTPException(status_code=404, detail="Price source row not found")
            return JSONResponse(out)
        finally:
            conn.close()

    @app.get("/api/prices/row/{price_id}")
    def api_price_row(price_id: int, _: str = Depends(_auth_dep)) -> JSONResponse:
        conn = get_connection(db_path)
        try:
            row = get_model_price_by_id(conn, price_id)
            if row is None:
                raise HTTPException(status_code=404, detail="Price row not found")
            return JSONResponse(row)
        finally:
            conn.close()

    return app


db_path = os.getenv("COST_MGMT_DB_PATH", _default_db_path())
bills_dir = os.getenv("BILLS_DIR_PATH", _default_bills_dir())
# Avoid importing/ingesting during unit tests by default; production runs can set AUTO_INGEST=1.
auto_ingest = os.getenv("AUTO_INGEST", "0").strip().lower() in {"1", "true", "yes", "on"}

app = create_app(db_path=db_path, bills_dir=bills_dir, auto_ingest=auto_ingest)
