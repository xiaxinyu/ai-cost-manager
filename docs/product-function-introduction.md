# Models Cost Management - Product Function Introduction

## Overview

Models Cost Management is a lightweight cost-management web app that ingests project billing CSV files into SQLite, tracks import status, and provides audit-style dashboards and financial reporting across one or more projects.

The goal is to help you manage billing data professionally: reliable import control, project-scoped analytics, and repeatable financial summaries.

## Key Capabilities

### 1) Authentication & Session

- Login/logout with server-side session cookies.
- Optional authentication toggle via environment configuration.
- Session persistence works across requests; production should set a strong `COST_MGMT_SESSION_SECRET_KEY`.

### 2) CSV Ingestion & Normalized Storage

- Discover CSV files under `bills/<project>/...`.
- Parse CSV rows into a normalized SQLite table: `transactions`.
- Store the original row payload as `raw_json` for traceability and future re-rendering.
- Track ingested files in `ingested_files` to prevent duplicate imports.

### 3) Import Workflow (Missing-File Control)

- Dedicated import page at `/import`.
- The UI compares disk files vs. `ingested_files` to show missing bills.
- You can select:
  - Specific missing files (checkbox list)
  - Re-import behavior (optional reimport of changed files)
- After importing, the page refreshes missing/imported lists.

### 4) Project Analytics Dashboard

- Main dashboard shows project-level billing data with:
  - Project switching
  - Simple and Complex display modes
- Data is rendered from the normalized `transactions` table.

### 5) Financial Reports (All / Single / Multiple Projects)

- Reports page at `/reports`.
- Supports project scoping via a single checkbox dropdown:
  - `All projects` (clears filtering)
  - One or more selected projects (multi-project aggregation)
- Computes audit-style financial metrics (per day and per month), including:
  - Total actual and forecast
  - Average, median, and variance (population variance)
  - Daily and monthly Actual vs Forecast charts

## Data Model (Audit-Focused)

- `transactions`
  - Stores normalized columns for CSV row attributes (e.g., `usage_date`, `project_name`, `cost_usd`, `forecast_cost`, `currency`, etc.).
  - Keeps `raw_json` to preserve the original parsed row content.
  - Enforces uniqueness via `(project_name, source_file, source_row_index)`.
- `ingested_files`
  - Stores file-level import metadata (so the system can detect missing/duplicate imports).

## Security & Hardening

- Session cookie options:
  - `HttpOnly` (via framework defaults)
  - optional HTTPS-only mode via `COST_MGMT_COOKIE_SECURE`
- Security response headers are applied globally (including `Content-Security-Policy` adapted for inline scripts and locally served Chart.js under `/static/js/`).
- Production deployment should set:
  - `COST_MGMT_SESSION_SECRET_KEY` (no dev fallback)
  - `COST_MGMT_COOKIE_SECURE=1` behind HTTPS

## User Workflows

1. Visit `/login` (if authentication is enabled).
2. Import missing bills via `/import`:
   - Select missing files
   - Click import (selected files only)
3. Use the main dashboard to browse project analytics.
4. Use `/reports` to generate financial summaries:
   - Choose project scope (All / Single / Multiple)
   - Select currency and date range
   - Load report to update metrics and charts

## Key API Endpoints (Reference)

- `GET /api/projects`
  - Lists discovered projects.
- `POST /api/import/run`
  - Imports missing CSVs (all missing or selected by `file_path_rels`).
- `GET /api/import/missing-files`
  - Returns missing bills that are not yet ingested.
- `GET /api/reports/all-financial`
  - Returns financial summary and charts.
  - Supports optional filters:
    - `start_date`, `end_date`, `currency`
    - `project_names` (repeatable query param for multi-project selection)

## Configuration (High-Level)

- `COST_MGMT_DB_PATH`: SQLite database path
- `BILLS_DIR_PATH`: root bills directory (`bills/`)
- `AUTO_INGEST`: default ingest behavior at startup (recommended off for controlled imports)
- `COST_MGMT_AUTH_ENABLED`: enable/disable auth layer
- `COST_MGMT_SESSION_SECRET_KEY`: session signing key
- `COST_MGMT_COOKIE_SECURE`: HTTPS-only cookies in production

