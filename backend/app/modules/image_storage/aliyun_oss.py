from __future__ import annotations

import hashlib
import mimetypes
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from app.core import config as app_config

MAX_IMAGE_BYTES = 20 * 1024 * 1024
HTTP_TIMEOUT_SECONDS = 20
IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class ImageStorageError(Exception):
    pass


class DisabledImageStorage:
    enabled = False

    def mirror(self, source_ref: str, _key_hint: str) -> str:
        return clean_text(source_ref)


class AliyunOssImageStorage:
    enabled = True

    def __init__(self) -> None:
        settings = get_oss_settings()
        missing = [
            name
            for name, value in {
                "ALIYUN_OSS_ACCESS_KEY_ID": settings["access_key_id"],
                "ALIYUN_OSS_ACCESS_KEY_SECRET": settings["access_key_secret"],
                "ALIYUN_OSS_ENDPOINT": settings["endpoint"],
                "ALIYUN_OSS_BUCKET": settings["bucket"],
            }.items()
            if not value
        ]
        if missing:
            raise ImageStorageError(f"OSS 已启用，但缺少配置：{', '.join(missing)}")

        try:
            import oss2
        except ImportError as exc:
            raise ImageStorageError("OSS 已启用，但缺少 Python 依赖 oss2；请先执行 pip install -r backend/requirements.txt") from exc

        self.bucket_name = settings["bucket"]
        self.endpoint = settings["endpoint"]
        self.public_base_url = settings["public_base_url"] or default_public_base_url(settings["bucket"], settings["endpoint"])
        self.object_prefix = settings["object_prefix"]
        self.bucket = oss2.Bucket(
            oss2.Auth(settings["access_key_id"], settings["access_key_secret"]),
            normalize_endpoint(settings["endpoint"]),
            settings["bucket"],
        )
        self.cache: dict[str, str] = {}

    def mirror(self, source_ref: str, key_hint: str) -> str:
        source_ref = clean_text(source_ref)
        if not source_ref:
            return ""
        if self.is_already_public_oss_url(source_ref):
            return source_ref
        if source_ref in self.cache:
            return self.cache[source_ref]

        image_bytes, content_type, source_name = read_image_ref(source_ref)
        object_key = build_object_key(self.object_prefix, key_hint, source_name, content_type, image_bytes)
        self.bucket.put_object(
            object_key,
            image_bytes,
            headers={
                "Content-Type": content_type,
                "Cache-Control": "public, max-age=31536000",
                "x-oss-object-acl": "public-read",
            },
        )
        public_url = f"{self.public_base_url}/{quote(object_key, safe='/')}"
        self.cache[source_ref] = public_url
        return public_url

    def upload_bytes(self, image_bytes: bytes, content_type: str, key_hint: str) -> dict[str, str]:
        content_type = guess_content_type("", content_type)
        object_key = build_object_key(self.object_prefix, key_hint, "", content_type, image_bytes)
        self.bucket.put_object(
            object_key,
            image_bytes,
            headers={
                "Content-Type": content_type,
                "Cache-Control": "public, max-age=31536000",
                "x-oss-object-acl": "public-read",
            },
        )
        return {
            "storageKey": object_key,
            "url": f"{self.public_base_url}/{quote(object_key, safe='/')}",
        }

    def is_already_public_oss_url(self, source_ref: str) -> bool:
        return source_ref.startswith(f"{self.public_base_url}/")


_DEFAULT_STORAGE: DisabledImageStorage | AliyunOssImageStorage | None = None
_DEFAULT_STORAGE_KEY: tuple[str, ...] | None = None


def get_image_storage() -> DisabledImageStorage | AliyunOssImageStorage:
    global _DEFAULT_STORAGE, _DEFAULT_STORAGE_KEY
    settings = get_oss_settings()
    storage_key = tuple(settings.values())
    if _DEFAULT_STORAGE is not None and _DEFAULT_STORAGE_KEY == storage_key:
        return _DEFAULT_STORAGE
    if not is_enabled(settings["enabled"]):
        _DEFAULT_STORAGE = DisabledImageStorage()
    else:
        _DEFAULT_STORAGE = AliyunOssImageStorage()
    _DEFAULT_STORAGE_KEY = storage_key
    return _DEFAULT_STORAGE


def mirror_export_image(source_ref: str, key_hint: str) -> str:
    return get_image_storage().mirror(source_ref, key_hint)


def upload_image_bytes(image_bytes: bytes, content_type: str, key_hint: str) -> dict[str, str]:
    storage = get_image_storage()
    if not isinstance(storage, AliyunOssImageStorage):
        raise ImageStorageError("OSS 未启用，无法保存生成图片")
    return storage.upload_bytes(image_bytes, content_type, key_hint)


def get_oss_settings() -> dict[str, str]:
    return {
        "enabled": os.getenv("ALIYUN_OSS_ENABLED", "1" if app_config.ALIYUN_OSS_ENABLED else ""),
        "access_key_id": os.getenv("ALIYUN_OSS_ACCESS_KEY_ID", app_config.ALIYUN_OSS_ACCESS_KEY_ID).strip(),
        "access_key_secret": os.getenv("ALIYUN_OSS_ACCESS_KEY_SECRET", app_config.ALIYUN_OSS_ACCESS_KEY_SECRET).strip(),
        "endpoint": os.getenv("ALIYUN_OSS_ENDPOINT", app_config.ALIYUN_OSS_ENDPOINT).strip().rstrip("/"),
        "bucket": os.getenv("ALIYUN_OSS_BUCKET", app_config.ALIYUN_OSS_BUCKET).strip(),
        "public_base_url": os.getenv("ALIYUN_OSS_PUBLIC_BASE_URL", app_config.ALIYUN_OSS_PUBLIC_BASE_URL).strip().rstrip("/"),
        "object_prefix": os.getenv("ALIYUN_OSS_OBJECT_PREFIX", app_config.ALIYUN_OSS_OBJECT_PREFIX).strip().strip("/"),
    }


def is_enabled(value: str) -> bool:
    return clean_text(value).lower() in {"1", "true", "yes", "on"}


def read_image_ref(source_ref: str) -> tuple[bytes, str, str]:
    parsed = urlparse(source_ref)
    if parsed.scheme in {"http", "https"}:
        return download_image(source_ref)

    source_path = Path(source_ref)
    if source_path.exists() and source_path.is_file():
        image_bytes = source_path.read_bytes()
        content_type = guess_content_type(source_path.name, "")
        return image_bytes, content_type, source_path.name

    raise ImageStorageError(f"无法读取图片：{source_ref}")


def download_image(source_url: str) -> tuple[bytes, str, str]:
    request = Request(
        source_url,
        headers={
            "User-Agent": "Mozilla/5.0 TemuListingWorkbench/1.0",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            image_bytes = response.read(MAX_IMAGE_BYTES + 1)
    except Exception as exc:  # pragma: no cover - network failures vary by host.
        raise ImageStorageError(f"下载图片失败：{source_url}") from exc

    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ImageStorageError(f"图片超过 20MB，无法上传 OSS：{source_url}")

    parsed = urlparse(source_url)
    source_name = Path(parsed.path).name
    content_type = guess_content_type(source_name, content_type)
    if not content_type.startswith("image/"):
        raise ImageStorageError(f"图片地址返回的不是图片内容：{source_url}")
    return image_bytes, content_type, source_name


def build_object_key(prefix: str, key_hint: str, source_name: str, content_type: str, image_bytes: bytes) -> str:
    digest = hashlib.sha1(image_bytes).hexdigest()[:16]
    extension = pick_extension(source_name, content_type)
    safe_hint = sanitize_object_key_hint(key_hint)
    return "/".join(part for part in [prefix, f"{safe_hint}-{digest}{extension}"] if part)


def sanitize_object_key_hint(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9/_-]+", "-", clean_text(value)).strip("-/")
    text = re.sub(r"-{2,}", "-", text)
    return text[:120] or "image"


def pick_extension(source_name: str, content_type: str) -> str:
    suffix = Path(source_name).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return IMAGE_EXTENSIONS.get(content_type) or mimetypes.guess_extension(content_type) or ".jpg"


def guess_content_type(source_name: str, content_type: str) -> str:
    if content_type.startswith("image/"):
        return content_type
    guessed, _ = mimetypes.guess_type(source_name)
    return guessed or "image/jpeg"


def normalize_endpoint(endpoint: str) -> str:
    if endpoint.startswith(("http://", "https://")):
        return endpoint
    return f"https://{endpoint}"


def default_public_base_url(bucket_name: str, endpoint: str) -> str:
    parsed = urlparse(normalize_endpoint(endpoint))
    host = parsed.netloc or parsed.path
    return f"https://{bucket_name}.{host}".rstrip("/")


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()
