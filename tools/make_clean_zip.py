"""
Кроссплатформенная сборка "чистого" ZIP-архива проекта:
- нормализует пути в ZIP (всегда forward slashes: dir/file.py)
- исключает мусор (__pycache__, .venv, .env, логи, архивы)
"""

from __future__ import annotations

import os
import fnmatch
import zipfile
from datetime import datetime
from pathlib import Path

EXCLUDE_DIRS = {
    ".git", ".idea", ".vscode",
    "__pycache__", ".pytest_cache",
    ".venv", "venv", "env",
    "tmp", "temp", "build", "dist",
}

EXCLUDE_PATTERNS = [
    "*.pyc", "*.pyo", "*.pyd",
    "*.log",
    "*.zip", "*.rar", "*.7z",
    ".env",
]

PROJECT_ROOT = Path(__file__).resolve().parents[1]

def is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDE_DIRS:
        return True
    for pat in EXCLUDE_PATTERNS:
        if fnmatch.fnmatch(path.name, pat):
            return True
    return False

def build_zip() -> Path:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_name = f"discord-bot-uvd_clean_{ts}.zip"
    out_path = PROJECT_ROOT / out_name

    files = [p for p in PROJECT_ROOT.rglob("*") if p.is_file() and not is_excluded(p)]
    files.sort(key=lambda p: str(p.relative_to(PROJECT_ROOT)).lower())

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            rel = p.relative_to(PROJECT_ROOT)
            # ZIP-стандарт: forward slashes
            arcname = rel.as_posix()
            zf.write(p, arcname)

    return out_path

if __name__ == "__main__":
    out = build_zip()
    print(f"[OK] Created: {out}")
