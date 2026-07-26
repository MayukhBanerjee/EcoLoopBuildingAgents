#!/usr/bin/env python
"""
run_agent.py — thin wrapper around main.py (Phase 4 entry).

Prefer:  uv run python main.py --dev
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    # Delegate to main.py so both entry points stay identical.
    sys.argv[0] = str(ROOT / "main.py")
    runpy.run_path(str(ROOT / "main.py"), run_name="__main__")
