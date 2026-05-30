import os
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


def load_local_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()

DATA_DIR = BACKEND_DIR / "data"
DATABASE_PATH = DATA_DIR / "app.db"

STORAGE_DIR = PROJECT_ROOT / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
EXPORTS_DIR = STORAGE_DIR / "exports"
TEMPLATES_DIR = STORAGE_DIR / "templates"
DIANXIAOMI_TEMU_TEMPLATE_PATH = TEMPLATES_DIR / "dianxiaomi_temu_semi_managed_import_template.xlsx"

ALIYUN_OSS_ENABLED = os.getenv("ALIYUN_OSS_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
ALIYUN_OSS_ACCESS_KEY_ID = os.getenv("ALIYUN_OSS_ACCESS_KEY_ID", "").strip()
ALIYUN_OSS_ACCESS_KEY_SECRET = os.getenv("ALIYUN_OSS_ACCESS_KEY_SECRET", "").strip()
ALIYUN_OSS_ENDPOINT = os.getenv("ALIYUN_OSS_ENDPOINT", "").strip().rstrip("/")
ALIYUN_OSS_BUCKET = os.getenv("ALIYUN_OSS_BUCKET", "").strip()
ALIYUN_OSS_PUBLIC_BASE_URL = os.getenv("ALIYUN_OSS_PUBLIC_BASE_URL", "").strip().rstrip("/")
ALIYUN_OSS_OBJECT_PREFIX = os.getenv("ALIYUN_OSS_OBJECT_PREFIX", "temu-listing").strip().strip("/")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip().rstrip("/")
OPENAI_TEXT_MODEL = os.getenv("OPENAI_TEXT_MODEL", "gpt-4.1-mini").strip()
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1").strip()
OPENAI_IMAGE_QUALITY = os.getenv("OPENAI_IMAGE_QUALITY", "medium").strip()


def ensure_runtime_dirs() -> None:
    for path in (DATA_DIR, UPLOADS_DIR, EXPORTS_DIR, TEMPLATES_DIR):
        path.mkdir(parents=True, exist_ok=True)
