from __future__ import annotations

import subprocess
from pathlib import Path


def test_migrate_grafana_downloads_smoke():
    root = Path(__file__).resolve().parents[1]
    script = root / "tests" / "test_migrate_grafana_downloads.sh"
    result = subprocess.run(
        ["bash", str(script)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
