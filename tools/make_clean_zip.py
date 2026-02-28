
import os, fnmatch, zipfile
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", "build", "dist"}
EXCLUDE_PATTERNS = ["*.pyc", "*.log", ".env"]

def is_excluded(path: Path) -> bool:

    if any(part in EXCLUDE_DIRS for part in path.parts):
        return True
    if any(fnmatch.fnmatch(path.name, pat) for pat in EXCLUDE_PATTERNS):
        return True
    return False

def build_zip() -> Path:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    out_name = f"discord-bot-uvd_clean_{ts}.zip"
    out_path = PROJECT_ROOT / out_name

    files = [p for p in PROJECT_ROOT.rglob("*") if p.is_file() and not is_excluded(p.relative_to(PROJECT_ROOT))]
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in files:
            rel_path = file.relative_to(PROJECT_ROOT).as_posix()
            zf.write(file, rel_path)
    print(f"[OK] Собран чистый архив: {out_path}")

if __name__ == "__main__":
    build_zip()
