from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.core import config as app_config
from app.core.database import get_app_setting_value


DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


class VisualGenerationError(RuntimeError):
    pass


def get_runtime_setting(key: str, default: str = "") -> str:
    saved_value = get_app_setting_value(key, "")
    if saved_value != "":
        return saved_value
    return os.getenv(key, default).strip()


def get_ai_settings() -> dict[str, str]:
    base_url = get_runtime_setting("OPENAI_BASE_URL", app_config.OPENAI_BASE_URL).strip().rstrip("/")
    return {
        "api_key": get_runtime_setting("OPENAI_API_KEY", app_config.OPENAI_API_KEY).strip(),
        "base_url": base_url or DEFAULT_OPENAI_BASE_URL,
        "text_model": get_runtime_setting("OPENAI_TEXT_MODEL", app_config.OPENAI_TEXT_MODEL).strip() or "gpt-4.1-mini",
        "image_model": get_runtime_setting("OPENAI_IMAGE_MODEL", app_config.OPENAI_IMAGE_MODEL).strip() or "gpt-image-1",
        "image_quality": get_runtime_setting("OPENAI_IMAGE_QUALITY", app_config.OPENAI_IMAGE_QUALITY).strip() or "medium",
    }


def build_api_url(base_url: str, path: str) -> str:
    clean_base = str(base_url or DEFAULT_OPENAI_BASE_URL).strip().rstrip("/")
    clean_path = "/" + str(path or "").strip().lstrip("/")
    return clean_base + clean_path


def request_json(api_url: str, api_key: str, payload: dict[str, Any], *, timeout: int = 300) -> dict[str, Any]:
    if not api_key:
        raise VisualGenerationError("AI API Key is not configured")

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        api_url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise VisualGenerationError(format_http_error(exc.code, error_body)) from exc
    except urllib.error.URLError as exc:
        raise VisualGenerationError(f"AI request failed: {exc}") from exc

    try:
        return json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise VisualGenerationError(f"AI API did not return JSON: {response_body[:500]}") from exc


def format_http_error(status_code: int, error_body: str) -> str:
    try:
        parsed = json.loads(error_body)
    except json.JSONDecodeError:
        return f"HTTP {status_code}: {error_body[:500]}"

    error = parsed.get("error") if isinstance(parsed, dict) else None
    if not isinstance(error, dict):
        return f"HTTP {status_code}: {error_body[:500]}"

    code = str(error.get("code") or "")
    message = str(error.get("message") or "")
    error_type = str(error.get("type") or "")
    if status_code == 401 or code == "invalid_api_key":
        return "AI API Key is invalid, or the key does not match the configured base URL"
    if status_code == 403:
        return f"AI API permission denied: {message}"
    if status_code == 404 and ("model" in message.lower() or "model" in code.lower()):
        return f"AI model is unavailable or misspelled: {message}"
    if status_code == 429:
        return f"AI quota is insufficient or requests are too frequent: {message}"
    if code or error_type:
        return f"HTTP {status_code}, {code or error_type}: {message}"
    return f"HTTP {status_code}: {message or error_body[:500]}"


def find_first_key(obj: object, keys: set[str]) -> object | None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in keys and value:
                return value
        for value in obj.values():
            found = find_first_key(value, keys)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_first_key(item, keys)
            if found:
                return found
    return None


def decode_base64_image(value: object) -> bytes | None:
    if not isinstance(value, str):
        return None
    encoded = value.strip()
    if encoded.startswith("data:image/") and ";base64," in encoded:
        encoded = encoded.split(";base64,", 1)[1]
    try:
        return base64.b64decode(encoded)
    except Exception:
        return None


def download_image(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "TemuListingWorkbench/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            content_type = response.headers.get("Content-Type", "")
            data = response.read()
    except urllib.error.URLError as exc:
        raise VisualGenerationError(f"image URL download failed: {exc}") from exc

    if "image" not in content_type.lower() and not data.startswith((b"\xff\xd8", b"\x89PNG", b"RIFF")):
        raise VisualGenerationError(f"URL did not return image content: {content_type}")
    return data


def image_file_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(suffix, "image/jpeg")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def extract_response_text(response_json: dict[str, Any]) -> str:
    if isinstance(response_json.get("output_text"), str):
        return response_json["output_text"]

    choices = response_json.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = [item["text"] for item in content if isinstance(item, dict) and isinstance(item.get("text"), str)]
                    if parts:
                        return "\n".join(parts)
            if isinstance(first.get("text"), str):
                return first["text"]

    chunks: list[str] = []
    for output in response_json.get("output", []):
        if not isinstance(output, dict):
            continue
        for content in output.get("content", []):
            if not isinstance(content, dict):
                continue
            if isinstance(content.get("text"), str):
                chunks.append(content["text"])
            elif isinstance(content.get("output_text"), str):
                chunks.append(content["output_text"])
    if chunks:
        return "\n".join(chunks)

    fallback = find_first_key(response_json, {"text", "output_text"})
    if isinstance(fallback, str):
        return fallback
    raise VisualGenerationError(f"AI API did not return text: {json.dumps(response_json, ensure_ascii=False)[:1000]}")


def parse_json_from_text(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end < start:
            raise
        data = json.loads(cleaned[start : end + 1])

    if not isinstance(data, dict):
        raise VisualGenerationError("AI JSON result must be an object")
    return data


def request_text_json(
    *,
    api_url: str,
    api_key: str,
    model: str,
    instruction: str,
    temperature: float = 0.2,
) -> dict[str, Any]:
    if api_url.rstrip("/").endswith("/chat/completions"):
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": instruction}],
            "temperature": temperature,
        }
    else:
        payload = {
            "model": model,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": instruction}]}],
            "temperature": temperature,
        }
    response_json = request_json(api_url, api_key, payload)
    return parse_json_from_text(extract_response_text(response_json))


def request_generated_image(
    *,
    api_url: str,
    api_key: str,
    model: str,
    size: str,
    prompt: str,
    reference_image_path: Path | None = None,
) -> bytes:
    normalized_api_url = api_url.rstrip("/")
    if normalized_api_url.endswith("/chat/completions"):
        raise VisualGenerationError("image generation API cannot use /chat/completions")

    if normalized_api_url.endswith("/responses"):
        content: list[dict[str, str]] = [{"type": "input_text", "text": prompt}]
        if reference_image_path and reference_image_path.exists():
            content.append({"type": "input_image", "image_url": image_file_to_data_url(reference_image_path)})
        payload = {
            "model": model,
            "input": [{"role": "user", "content": content}],
            "tools": [{"type": "image_generation"}],
        }
        response_json = request_json(api_url, api_key, payload)
    else:
        payload = {"model": model, "prompt": prompt, "n": 1}
        if size:
            payload["size"] = size
        response_json = request_json(api_url, api_key, payload)

    b64_value = find_first_key(response_json, {"b64_json", "base64", "image_base64", "result"})
    image_bytes = decode_base64_image(b64_value)
    if image_bytes:
        return image_bytes

    url_value = find_first_key(response_json, {"url", "image_url", "uri"})
    if isinstance(url_value, dict):
        url_value = find_first_key(url_value, {"url"})
    if isinstance(url_value, str) and url_value:
        return download_image(url_value)

    raise VisualGenerationError(
        "image generation result did not contain base64 or URL: "
        f"{json.dumps(response_json, ensure_ascii=False)[:1000]}"
    )

