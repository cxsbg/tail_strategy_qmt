from __future__ import annotations

import sys
from pathlib import Path


def ensure_src_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    src_path = project_root / "src"
    src_text = str(src_path)
    if src_text not in sys.path:
        sys.path.insert(0, src_text)
