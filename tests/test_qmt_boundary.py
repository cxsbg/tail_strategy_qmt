from __future__ import annotations

from pathlib import Path


def test_xtquant_is_only_referenced_inside_qmt_package() -> None:
    root = Path("src")
    offenders: list[Path] = []

    for path in root.rglob("*.py"):
        if "qmt" in path.parts:
            continue
        if "xtquant" in path.read_text(encoding="utf-8"):
            offenders.append(path)

    assert offenders == []
