from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from app.auth import create_user
from app.main import create_app
from app.db import init_db


def _create_admin(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
        create_user(conn, username="admin", password="admin12345", is_active=True)
    finally:
        conn.close()


def test_import_page_redirect_and_access(tmp_path):
    bills_dir = tmp_path / "bills"
    bills_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "cost_mgmt.sqlite3"

    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)

    # Unauthenticated users should be redirected to login.
    res = client.get("/import", follow_redirects=False)
    assert res.status_code in {302, 307, 303}

    _create_admin(str(db_path))
    login = client.post("/auth/login", data={"username": "admin", "password": "admin12345"})
    assert login.status_code in {200, 303}

    res2 = client.get("/import")
    assert res2.status_code == 200
    assert "Import data" in res2.text
    assert "import-missing" in res2.text


def test_login_wrong_password_shows_themed_page(tmp_path):
    bills_dir = tmp_path / "bills"
    bills_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "cost_mgmt.sqlite3"
    app = create_app(db_path=str(db_path), bills_dir=str(bills_dir), auto_ingest=False)
    client = TestClient(app)
    _create_admin(str(db_path))

    res = client.post(
        "/auth/login",
        data={"username": "admin", "password": "not-the-password"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert "error=invalid" in (res.headers.get("location") or "")

    page = client.get("/login?error=invalid")
    assert page.status_code == 200
    assert "Sign-in failed" in page.text
    assert "Incorrect username or password" in page.text

