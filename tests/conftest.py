from __future__ import annotations

import sys
from pathlib import Path


# Ensure repo root is importable so tests can `import app.*` reliably
# across different runners (local, CI, IDE, Playwright plugin invocations).
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

