from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent

DATA_DIR = BACKEND_DIR / "data"
DATABASE_PATH = DATA_DIR / "app.db"

STORAGE_DIR = PROJECT_ROOT / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
EXPORTS_DIR = STORAGE_DIR / "exports"


def ensure_runtime_dirs() -> None:
    for path in (DATA_DIR, UPLOADS_DIR, EXPORTS_DIR):
        path.mkdir(parents=True, exist_ok=True)
