from __future__ import annotations

import re

import pytest


def _extract_leading_int(text: str) -> int:
    m = re.search(r"\d+", text or "")
    return int(m.group(0)) if m else 0


def _canvas_data_url_len_expr(canvas_id: str) -> str:
    # Return JS expression that evaluates to an integer length.
    return f"""(() => {{
      const c = document.getElementById({canvas_id!r});
      if (!c) return 0;
      try {{
        return String(c.toDataURL()).length;
      }} catch (e) {{
        return 0;
      }}
    }})()"""


def _login(page, base_url: str) -> None:
    page.goto(f"{base_url}/login")
    page.fill("#username", "admin")
    page.fill("#password", "ChangeMe_2026!")
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(re.escape(base_url) + r"/$"))


@pytest.mark.e2e
def test_desktop_primary_workflows(page, e2e_server_base_url: str) -> None:
    base_url = e2e_server_base_url
    _login(page, base_url)

    # Dashboard loaded: project list should be populated.
    page.wait_for_selector("#projectSelect option", state="attached")
    page.wait_for_timeout(400)

    # Charts should render non-empty canvases.
    for cid in [
        "timeseriesChartActual",
        "timeseriesChartMarket",
    ]:
        n = page.evaluate(_canvas_data_url_len_expr(cid))
        assert n > 2000, f"canvas {cid} looks empty (dataURL len={n})"

    # Tokens page
    page.goto(f"{base_url}/tokens")
    page.wait_for_selector("#projectSelect")
    page.click("#loadTokensBtn")
    page.wait_for_timeout(500)
    for cid in ["tokenInputChart", "tokenOutputChart", "tokenRatioChart"]:
        n = page.evaluate(_canvas_data_url_len_expr(cid))
        assert n > 2000, f"canvas {cid} looks empty (dataURL len={n})"

    # Import page: should have at least 1 missing file and import should reduce it.
    page.goto(f"{base_url}/import")
    page.wait_for_selector("#missingFilesTbody")
    page.wait_for_timeout(400)
    missing_before = page.text_content("#missingCount")
    assert missing_before is not None
    assert _extract_leading_int(missing_before.strip()) >= 1
    page.check("input.filePick[type=checkbox]")
    page.click("#importBtn")
    page.wait_for_timeout(800)
    missing_after = page.text_content("#missingCount")
    assert missing_after is not None
    assert _extract_leading_int(missing_after.strip()) == 0

    # Reports page: load and render charts
    page.goto(f"{base_url}/reports")
    page.wait_for_selector("#loadBtn")
    page.click("#loadBtn")
    page.wait_for_timeout(700)
    for cid in ["dailyChart", "monthlyChart", "dailyTokenChart", "dailyTokenRatioChart"]:
        n = page.evaluate(_canvas_data_url_len_expr(cid))
        assert n > 2000, f"canvas {cid} looks empty (dataURL len={n})"

    # Prices page: query should succeed and show at least 1 row from seeded prices.
    page.goto(f"{base_url}/prices")
    page.wait_for_selector("#queryBtn")
    page.click("#queryBtn")
    page.wait_for_timeout(500)
    rows = page.locator("#tbody tr").count()
    assert rows >= 1

    # Logout
    page.goto(f"{base_url}/")
    page.click("#logoutBtnTop")
    page.wait_for_url(re.compile(re.escape(base_url) + r"/login"))


@pytest.mark.e2e
def test_mobile_smoke(page, e2e_server_base_url: str) -> None:
    # Mobile viewport: ensure primary pages load and at least one chart renders.
    page.set_viewport_size({"width": 390, "height": 844})
    base_url = e2e_server_base_url
    _login(page, base_url)

    page.wait_for_selector("#projectSelect option", state="attached")
    page.wait_for_timeout(400)
    n = page.evaluate(_canvas_data_url_len_expr("timeseriesChartActual"))
    assert n > 2000

    for path, selector in [
        ("/tokens", "#tokenInputChart"),
        ("/reports", "#dailyChart"),
        ("/prices", "#queryBtn"),
        ("/import", "#importBtn"),
    ]:
        page.goto(f"{base_url}{path}")
        page.wait_for_selector(selector)
