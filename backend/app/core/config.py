import os
from pathlib import Path


def _resolve_path_env(name: str) -> Path | None:
    value = os.getenv(name, "").strip()
    return Path(value).expanduser().resolve() if value else None


BACKEND_DIR = _resolve_path_env("TEMU_WORKBENCH_BACKEND_DIR") or Path(__file__).resolve().parents[2]
PROJECT_ROOT = _resolve_path_env("TEMU_WORKBENCH_PROJECT_ROOT") or BACKEND_DIR.parent


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


def resolve_database_path() -> Path:
    configured_path = os.getenv("TEMU_WORKBENCH_DATABASE_PATH") or os.getenv("DATABASE_PATH")
    if configured_path:
        return Path(configured_path).expanduser()
    return DATA_DIR / "app.db"


DATABASE_PATH = resolve_database_path()

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
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.aicoming.top/v1").strip().rstrip("/")
OPENAI_TEXT_MODEL = os.getenv("OPENAI_TEXT_MODEL", "gpt-5.5").strip()
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2-1k").strip()
OPENAI_IMAGE_QUALITY = os.getenv("OPENAI_IMAGE_QUALITY", "medium").strip()

REDIS_URL = os.getenv("REDIS_URL", "").strip()

VISUAL_DEFAULT_MODE = os.getenv("VISUAL_DEFAULT_MODE", "main-gallery").strip()
VISUAL_DEFAULT_LAYOUT = os.getenv("VISUAL_DEFAULT_LAYOUT", "3x3").strip()
VISUAL_DEFAULT_REQUESTED_COUNT = os.getenv("VISUAL_DEFAULT_REQUESTED_COUNT", "9").strip()
VISUAL_IMAGE_SIZE = os.getenv("VISUAL_IMAGE_SIZE", "1024x1024").strip()
VISUAL_ALLOW_SHORT_LABELS = os.getenv("VISUAL_ALLOW_SHORT_LABELS", "1").strip()
VISUAL_USE_REFERENCE_IMAGE = os.getenv("VISUAL_USE_REFERENCE_IMAGE", "1").strip()
VISUAL_UPLOAD_TO_OSS_DEFAULT = os.getenv("VISUAL_UPLOAD_TO_OSS_DEFAULT", "0").strip()
VISUAL_SPLIT_TARGET_SIZE = os.getenv("VISUAL_SPLIT_TARGET_SIZE", "800").strip()
VISUAL_SPLIT_FORMAT = os.getenv("VISUAL_SPLIT_FORMAT", "webp").strip()
VISUAL_SPLIT_QUALITY = os.getenv("VISUAL_SPLIT_QUALITY", "92").strip()
VISUAL_SPLIT_SAFE_MARGIN_RATIO = os.getenv("VISUAL_SPLIT_SAFE_MARGIN_RATIO", "0.03").strip()
VISUAL_SPLIT_SHARPEN = os.getenv("VISUAL_SPLIT_SHARPEN", "0.7").strip()
VISUAL_QUEUE_REDIS_ENABLED = os.getenv("VISUAL_QUEUE_REDIS_ENABLED", "0").strip()
VISUAL_QUEUE_NAME = os.getenv("VISUAL_QUEUE_NAME", "visual:tasks:queue").strip()
VISUAL_QUEUE_DRAIN_MAX_JOBS = os.getenv("VISUAL_QUEUE_DRAIN_MAX_JOBS", "3").strip()
VISUAL_QUEUE_WORKER_LOCK_SECONDS = os.getenv("VISUAL_QUEUE_WORKER_LOCK_SECONDS", "3600").strip()
VISUAL_QUEUE_POP_TIMEOUT_SECONDS = os.getenv("VISUAL_QUEUE_POP_TIMEOUT_SECONDS", "1").strip()
VISUAL_QUEUE_RETRY_NAME = os.getenv("VISUAL_QUEUE_RETRY_NAME", "visual:tasks:retry").strip()
VISUAL_QUEUE_DEAD_NAME = os.getenv("VISUAL_QUEUE_DEAD_NAME", "visual:tasks:dead").strip()
VISUAL_QUEUE_MAX_RETRIES = os.getenv("VISUAL_QUEUE_MAX_RETRIES", "2").strip()
VISUAL_QUEUE_RETRY_DELAY_SECONDS = os.getenv("VISUAL_QUEUE_RETRY_DELAY_SECONDS", "30").strip()
VISUAL_USER_CONCURRENCY_LIMIT = os.getenv("VISUAL_USER_CONCURRENCY_LIMIT", "5").strip()
VISUAL_TEAM_CONCURRENCY_LIMIT = os.getenv("VISUAL_TEAM_CONCURRENCY_LIMIT", "5").strip()

TMAPI_API_TOKEN = os.getenv("TMAPI_API_TOKEN", "").strip()
TMAPI_BASE_URL = os.getenv("TMAPI_BASE_URL", "http://api.tmapi.top").strip().rstrip("/")

WORKBENCH_SYNC_TOKEN = (
    os.getenv("WORKBENCH_SYNC_TOKEN")
    or os.getenv("TEMU_WORKBENCH_SYNC_TOKEN")
    or ""
).strip()
WORKBENCH_INGEST_TOKEN = (
    os.getenv("WORKBENCH_INGEST_TOKEN")
    or os.getenv("TEMU_WORKBENCH_INGEST_TOKEN")
    or ""
).strip()

WORKBENCH_DEFAULT_USERNAME = os.getenv("WORKBENCH_DEFAULT_USERNAME", "admin").strip() or "admin"
WORKBENCH_DEFAULT_PASSWORD = os.getenv("WORKBENCH_DEFAULT_PASSWORD", "admin123").strip() or "admin123"
WORKBENCH_SESSION_COOKIE_NAME = os.getenv("WORKBENCH_SESSION_COOKIE_NAME", "temu_workbench_session").strip() or "temu_workbench_session"
WORKBENCH_SESSION_COOKIE_SECURE = (
    os.getenv("WORKBENCH_SESSION_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes", "on"}
)
WORKBENCH_SESSION_COOKIE_SAMESITE = os.getenv("WORKBENCH_SESSION_COOKIE_SAMESITE", "lax").strip().lower() or "lax"
if WORKBENCH_SESSION_COOKIE_SAMESITE not in {"lax", "strict", "none"}:
    WORKBENCH_SESSION_COOKIE_SAMESITE = "lax"
WORKBENCH_SESSION_COOKIE_MAX_AGE_SECONDS = int(os.getenv("WORKBENCH_SESSION_COOKIE_MAX_AGE_SECONDS", "2592000"))


def ensure_runtime_dirs() -> None:
    for path in (DATA_DIR, DATABASE_PATH.parent, UPLOADS_DIR, EXPORTS_DIR, TEMPLATES_DIR):
        path.mkdir(parents=True, exist_ok=True)
