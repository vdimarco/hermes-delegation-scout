"""Test bootstrap: put the repo root (the plugin directory) on sys.path so ``scout.*``
imports resolve when pytest runs from the repo root; Hermes core modules come from the
editable install of the running interpreter."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
