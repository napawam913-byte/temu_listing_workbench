from __future__ import annotations

import json
import marshal
import shutil
import sys
import time
from pathlib import Path
from typing import Any


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
BASE_CODE_PATHS = [
    APP_DIR / "work" / "terminal_app_base.pyc",
    Path(getattr(sys, "_MEIPASS", APP_DIR)) / "terminal_app_base.pyc",
    APP_DIR / "terminal_app_base.pyc",
    APP_DIR / "__pycache__" / "terminal_app.cpython-313.pyc",
]

DEFAULT_IMAGE_POSTPROCESS = {
    "enabled": True,
    "targetWidth": 800,
    "targetHeight": 800,
    "quality": 88,
    "maxBytes": 2 * 1024 * 1024,
    "minSourceWidth": 300,
    "minSourceHeight": 300,
    "outputFormat": "jpg",
    "mode": "pad",
    "background": "#FFFFFF",
    "compressorPath": "C:/Users/AA/Desktop/优化工具/图片压缩起.exe",
}


def _load_base_namespace() -> dict[str, Any]:
    searched: list[str] = []
    for path in BASE_CODE_PATHS:
        searched.append(str(path))
        if not path.exists():
            continue
        ns: dict[str, Any] = {
            "__name__": "_dxm_temu_terminal_base",
            "__file__": str(Path(__file__).resolve()),
        }
        data = path.read_bytes()
        exec(marshal.loads(data[16:]), ns)
        return ns
    raise RuntimeError("没有找到机器人基座程序；已查找：" + " | ".join(searched))


BASE = _load_base_namespace()
IMAGE_EXTS = set(BASE.get("IMAGE_EXTS") or {".jpg", ".jpeg", ".png", ".webp", ".bmp"})
PIPELINE_CONFIG_PATH = Path(BASE.get("PIPELINE_CONFIG_PATH", APP_DIR / "work" / "state" / "automation-config.json"))


def _log(level: str, message: str, **extra: Any) -> None:
    logger = BASE.get("_log")
    if callable(logger):
        logger(level, message, **extra)
        return
    print(f"[{level}] {message} {extra if extra else ''}")


def _save_json(name: str, data: Any) -> Path | None:
    saver = BASE.get("_save_json")
    if callable(saver):
        return saver(name, data)
    return None


def _safe_error_text(value: Any) -> str:
    helper = BASE.get("_safe_error_text")
    if callable(helper):
        return helper(value)
    return str(value).encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def _normalize_image_postprocess_config(value: Any) -> dict[str, Any]:
    config = dict(DEFAULT_IMAGE_POSTPROCESS)
    if isinstance(value, dict):
        config.update({key: value.get(key, config[key]) for key in config})
    config["enabled"] = bool(config.get("enabled", True))
    for key in ("targetWidth", "targetHeight", "quality", "maxBytes", "minSourceWidth", "minSourceHeight"):
        try:
            config[key] = int(config.get(key) or DEFAULT_IMAGE_POSTPROCESS[key])
        except Exception:
            config[key] = DEFAULT_IMAGE_POSTPROCESS[key]
    config["targetWidth"] = max(1, config["targetWidth"])
    config["targetHeight"] = max(1, config["targetHeight"])
    config["quality"] = min(95, max(50, config["quality"]))
    config["maxBytes"] = max(128 * 1024, config["maxBytes"])
    config["minSourceWidth"] = max(1, config["minSourceWidth"])
    config["minSourceHeight"] = max(1, config["minSourceHeight"])
    config["outputFormat"] = str(config.get("outputFormat") or "jpg").strip().lower()
    if config["outputFormat"] not in {"jpg", "jpeg", "png", "webp"}:
        config["outputFormat"] = "jpg"
    config["mode"] = str(config.get("mode") or "pad").strip().lower()
    if config["mode"] not in {"pad", "cover"}:
        config["mode"] = "pad"
    config["background"] = str(config.get("background") or "#FFFFFF").strip() or "#FFFFFF"
    config["compressorPath"] = str(config.get("compressorPath") or DEFAULT_IMAGE_POSTPROCESS["compressorPath"]).strip()
    return config


_base_load_pipeline_config = BASE.get("_load_pipeline_config")
_base_save_pipeline_config = BASE.get("_save_pipeline_config")


def _load_pipeline_config() -> dict[str, Any]:
    if callable(_base_load_pipeline_config):
        config = _base_load_pipeline_config()
    else:
        config = {}
    if not isinstance(config, dict):
        config = {}
    config["imagePostprocess"] = _normalize_image_postprocess_config(config.get("imagePostprocess"))
    return config


def _save_pipeline_config(config: dict[str, Any]) -> None:
    existing_image_config: dict[str, Any] | None = None
    try:
        if PIPELINE_CONFIG_PATH.exists():
            existing = json.loads(PIPELINE_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and isinstance(existing.get("imagePostprocess"), dict):
                existing_image_config = existing["imagePostprocess"]
    except Exception:
        existing_image_config = None

    image_config = _normalize_image_postprocess_config(
        config.get("imagePostprocess") if isinstance(config, dict) and "imagePostprocess" in config else existing_image_config
    )
    if callable(_base_save_pipeline_config):
        _base_save_pipeline_config(config)
    try:
        PIPELINE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {}
        if PIPELINE_CONFIG_PATH.exists():
            loaded = json.loads(PIPELINE_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload.update(loaded)
        payload["imagePostprocess"] = image_config
        PIPELINE_CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        _log("WARN", "图片后处理配置保存失败", error=_safe_error_text(exc))


BASE["_load_pipeline_config"] = _load_pipeline_config
BASE["_save_pipeline_config"] = _save_pipeline_config


def _unique_child_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{index:03d}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")


def _resolve_download_folder(folder_text: str) -> Path:
    raw = str(folder_text or "").strip()
    candidates: list[Path] = []
    if raw:
        repair = BASE.get("_repair_mojibake_text")
        raw_candidates = repair(raw) if callable(repair) else [raw]
        for text in raw_candidates:
            path = Path(text).expanduser()
            if not path.is_absolute():
                path = (APP_DIR / path).resolve()
            candidates.append(path)
    pipeline_folder = BASE.get("_pipeline_image_folder")
    if callable(pipeline_folder):
        try:
            candidates.append(Path(pipeline_folder(_load_pipeline_config())))
        except Exception:
            pass
    for folder in candidates:
        if folder.exists() and folder.is_dir():
            return folder
    checked = " | ".join(str(path) for path in candidates) or raw
    raise RuntimeError(f"图片下载文件夹不存在：{checked}")


def _image_files(folder: Path) -> list[Path]:
    return [
        path
        for path in sorted(folder.iterdir(), key=lambda item: item.name.lower())
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS
    ]


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = str(value or "#FFFFFF").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except Exception:
        return (255, 255, 255)


def _save_square_image(img: Any, output_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    from PIL import Image, ImageOps

    target = (int(config["targetWidth"]), int(config["targetHeight"]))
    bg = _hex_to_rgb(str(config.get("background") or "#FFFFFF"))
    method = getattr(Image.Resampling, "LANCZOS", Image.LANCZOS)
    img = ImageOps.exif_transpose(img)
    if config.get("mode") == "cover":
        square = ImageOps.fit(img, target, method=method, centering=(0.5, 0.5))
        if square.mode != "RGB":
            canvas = Image.new("RGB", target, bg)
            if "A" in square.getbands():
                canvas.paste(square.convert("RGBA"), (0, 0), square.convert("RGBA").split()[-1])
            else:
                canvas.paste(square.convert("RGB"), (0, 0))
            square = canvas
        else:
            square = square.convert("RGB")
    else:
        contained = ImageOps.contain(img, target, method=method)
        canvas = Image.new("RGB", target, bg)
        x = (target[0] - contained.width) // 2
        y = (target[1] - contained.height) // 2
        if "A" in contained.getbands():
            rgba = contained.convert("RGBA")
            canvas.paste(rgba, (x, y), rgba.split()[-1])
        else:
            canvas.paste(contained.convert("RGB"), (x, y))
        square = canvas

    temp_path = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")
    fmt = str(config.get("outputFormat") or "jpg").upper()
    if fmt == "JPG":
        fmt = "JPEG"
    quality_candidates = [int(config["quality"]), 84, 80, 76, 72, 68, 64, 60]
    max_bytes = int(config["maxBytes"])
    last_size = 0
    for quality in quality_candidates:
        save_kwargs: dict[str, Any] = {"format": fmt}
        if fmt in {"JPEG", "WEBP"}:
            save_kwargs.update({"quality": quality, "optimize": True})
        square.save(temp_path, **save_kwargs)
        last_size = temp_path.stat().st_size
        if last_size <= max_bytes or fmt == "PNG":
            break
    temp_path.replace(output_path)
    return {"width": target[0], "height": target[1], "size": output_path.stat().st_size, "quality": quality_candidates[-1] if last_size > max_bytes else quality}


def _postprocess_downloaded_product_images(folder: Path, config: dict[str, Any]) -> dict[str, Any]:
    from PIL import Image

    folder.mkdir(parents=True, exist_ok=True)
    ignored_dir = folder / "_ignored_small_images"
    original_dir = folder / "_original_before_square"
    manifest: list[dict[str, Any]] = []
    processed = 0
    ignored = 0
    failed = 0

    for path in _image_files(folder):
        record: dict[str, Any] = {"name": path.name, "path": str(path)}
        try:
            with Image.open(path) as img:
                src_width, src_height = img.size
                record.update({"sourceWidth": src_width, "sourceHeight": src_height, "sourceSize": path.stat().st_size})
                if src_width < int(config["minSourceWidth"]) or src_height < int(config["minSourceHeight"]):
                    ignored_dir.mkdir(parents=True, exist_ok=True)
                    dest = _unique_child_path(ignored_dir / path.name)
                    img.close()
                    shutil.move(str(path), str(dest))
                    record.update({"status": "ignored_small", "movedTo": str(dest)})
                    ignored += 1
                    manifest.append(record)
                    _log("WARN", "图片太小，已移入忽略目录，避免误传", name=path.name, width=src_width, height=src_height)
                    continue

                suffix = ".jpg" if str(config.get("outputFormat")).lower() in {"jpg", "jpeg"} else f".{config.get('outputFormat')}"
                output_path = path.with_suffix(suffix)
                output_path = output_path if output_path == path else _unique_child_path(output_path)
                output = _save_square_image(img, output_path, config)
                if output_path != path and path.exists():
                    original_dir.mkdir(parents=True, exist_ok=True)
                    img.close()
                    shutil.move(str(path), str(_unique_child_path(original_dir / path.name)))
                record.update({"status": "processed", "output": str(output_path), **output})
                processed += 1
                _log("OK", "图片已压缩为 800x800 方图", name=output_path.name, source=f"{src_width}x{src_height}", size=output.get("size"))
        except Exception as exc:
            failed += 1
            record.update({"status": "failed", "error": _safe_error_text(exc)})
            _log("ERROR", "图片后处理失败", name=path.name, error=_safe_error_text(exc))
        manifest.append(record)

    payload = {
        "ok": failed == 0,
        "folder": str(folder),
        "processed": processed,
        "ignored": ignored,
        "failed": failed,
        "config": config,
        "images": manifest,
    }
    (folder / "image-postprocess-manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _save_json("image-postprocess-run", payload)
    _log("OK", "图片下载后处理完成", folder=str(folder), processed=processed, ignored=ignored, failed=failed)
    if failed:
        raise RuntimeError(f"图片后处理失败 {failed} 张，详情见 {folder / 'image-postprocess-manifest.json'}")
    return payload


_base_download_product_images = BASE["LEGACY"]["DxmTemuRobot"].download_product_images


def download_product_images_with_postprocess(self: Any, folder_text: str = "") -> Any:
    result = _base_download_product_images(self, folder_text)
    config = _load_pipeline_config()
    image_config = _normalize_image_postprocess_config(config.get("imagePostprocess"))
    if not image_config.get("enabled"):
        _log("INFO", "图片下载后处理已关闭，跳过 800x800 压缩", folder=folder_text)
        return result
    folder = _resolve_download_folder(folder_text)
    _log(
        "INFO",
        "开始图片下载后处理：1:1 方图 800x800",
        folder=str(folder),
        compressorPath=image_config.get("compressorPath"),
        mode=image_config.get("mode"),
    )
    _postprocess_downloaded_product_images(folder, image_config)
    return result


BASE["LEGACY"]["DxmTemuRobot"].download_product_images = download_product_images_with_postprocess


def main() -> None:
    BASE["LEGACY"]["DxmTemuRobot"].download_product_images = download_product_images_with_postprocess
    BASE["main"]()


if __name__ == "__main__":
    main()
