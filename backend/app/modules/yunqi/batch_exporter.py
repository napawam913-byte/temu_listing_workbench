from __future__ import annotations

import json
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app.core.config import STORAGE_DIR
from app.core.database import init_db
from app.modules.recommendation.keyword_index import rebuild_all_product_keyword_index
from app.modules.yunqi.category_catalog import list_yunqi_categories
from app.modules.yunqi.collector import YunqiCollectorError, collect_yunqi_excel_file
from app.modules.yunqi.filter_configs import write_yunqi_category_filter_config
from app.modules.yunqi.rpa_exporter import YunqiRpaError, export_yunqi_excel_via_rpa


BATCH_RUN_DIR = STORAGE_DIR / "yunqi_exports" / "batch_runs"
BatchLogCallback = Callable[[str], None]


def list_yunqi_leaf_categories(
    *,
    category_prefix: str | None = None,
    category_limit: int | None = None,
) -> list[dict[str, Any]]:
    rows = list_yunqi_categories(active_only=True)
    leaf_rows = [row for row in rows if not bool(row.get("has_children"))]
    selected_rows = leaf_rows or rows
    prefix = normalize_filter_text(category_prefix or "")

    categories: list[dict[str, Any]] = []
    for row in selected_rows:
        path = [str(item).strip() for item in row.get("path") or [] if str(item).strip()]
        path_text = str(row.get("path_text") or " > ".join(path)).strip()
        label = str(row.get("label") or "").strip()
        if not path or label == "全分类" or path_text == "全分类":
            continue
        if prefix:
            haystack = normalize_filter_text(f"{path_text} {' '.join(path)} {label}")
            if prefix not in haystack:
                continue
        categories.append({**row, "path": path, "path_text": path_text})
        if category_limit is not None and len(categories) >= max(0, category_limit):
            break
    return categories


def export_yunqi_all_categories(
    *,
    headless: bool | None = None,
    background_headed: bool | None = True,
    keep_open_on_error: bool = True,
    keep_browser_open: bool = True,
    use_cdp: bool = True,
    category_prefix: str | None = None,
    category_limit: int | None = None,
    delay_seconds: float = 1.0,
    import_after_export: bool = False,
    import_limit: int | None = None,
    rebuild_keywords: bool = True,
    stop_on_error: bool = False,
    max_consecutive_errors: int = 3,
    log: BatchLogCallback | None = None,
) -> dict[str, Any]:
    init_db()
    categories = list_yunqi_leaf_categories(category_prefix=category_prefix, category_limit=category_limit)
    if not categories:
        raise YunqiCollectorError("没有找到可轮询导出的云启末级类目。请先爬取并导入类目库。")

    BATCH_RUN_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest_path = BATCH_RUN_DIR / f"yunqi_batch_export_{run_id}.json"
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "status": "running",
        "started_at": now_text(),
        "finished_at": None,
        "category_count": len(categories),
        "success_count": 0,
        "failed_count": 0,
        "import_after_export": import_after_export,
        "downloads": [],
        "manifest_path": str(manifest_path),
    }
    write_manifest(manifest_path, manifest)

    imported_total = 0
    created_total = 0
    updated_total = 0
    consecutive_errors = 0

    for index, category in enumerate(categories, start=1):
        path = [str(item).strip() for item in category.get("path") or [] if str(item).strip()]
        path_text = str(category.get("path_text") or " > ".join(path)).strip()
        category_key = str(category.get("category_key") or category.get("id") or "").strip()
        config_path = write_yunqi_category_filter_config(
            category_key=category_key,
            category_path=path,
            path_text=path_text,
        )
        item: dict[str, Any] = {
            "index": index,
            "total": len(categories),
            "category_key": category_key,
            "category_path": path,
            "path_text": path_text,
            "config_path": str(config_path),
            "status": "running",
            "started_at": now_text(),
        }
        manifest["downloads"].append(item)
        write_manifest(manifest_path, manifest)
        emit(log, f"[{index}/{len(categories)}] 开始导出：{path_text}")

        try:
            export_result = export_yunqi_excel_via_rpa(
                filter_config_path=config_path,
                headless=headless,
                background_headed=background_headed,
                keep_open_on_error=keep_open_on_error,
                keep_browser_open=keep_browser_open,
                use_cdp=use_cdp,
                run_step="full",
            )
            item["status"] = "exported"
            item["finished_at"] = now_text()
            item["rpa"] = export_result
            item["download_path"] = export_result.get("download_path")
            item["suggested_filename"] = export_result.get("suggested_filename")
            manifest["success_count"] += 1
            consecutive_errors = 0
            emit(log, f"[{index}/{len(categories)}] 导出完成：{item.get('download_path')}")

            if import_after_export and item.get("download_path"):
                import_result = collect_yunqi_excel_file(
                    item["download_path"],
                    limit=import_limit,
                    rebuild_keywords=False,
                )
                item["status"] = "imported"
                item["import_result"] = import_result
                imported_total += int(import_result.get("imported_count") or 0)
                created_total += int(import_result.get("created_count") or 0)
                updated_total += int(import_result.get("updated_count") or 0)
                emit(log, f"[{index}/{len(categories)}] 已导入数据库：{import_result.get('imported_count', 0)} 条")
        except (YunqiCollectorError, YunqiRpaError, Exception) as exc:  # noqa: BLE001
            item["status"] = "failed"
            item["finished_at"] = now_text()
            item["error"] = str(exc)
            item["traceback"] = traceback.format_exc()
            manifest["failed_count"] += 1
            consecutive_errors += 1
            emit(log, f"[{index}/{len(categories)}] 失败：{exc}")
            if stop_on_error or consecutive_errors >= max(1, max_consecutive_errors):
                item["stopped_batch"] = True
                break
        finally:
            write_manifest(manifest_path, manifest)

        if delay_seconds > 0 and index < len(categories):
            time.sleep(delay_seconds)

    keyword_result: dict[str, int] | None = None
    if import_after_export and rebuild_keywords and imported_total > 0:
        keyword_result = rebuild_all_product_keyword_index()
        emit(log, f"关键词索引已重建：{keyword_result.get('keyword_count', 0)} 条")

    processed_count = manifest["success_count"] + manifest["failed_count"]
    manifest.update(
        {
            "status": "completed" if manifest["failed_count"] == 0 and processed_count == len(categories) else "partial",
            "finished_at": now_text(),
            "processed_count": processed_count,
            "imported_count": imported_total,
            "created_count": created_total,
            "updated_count": updated_total,
            "keyword_result": keyword_result,
        }
    )
    write_manifest(manifest_path, manifest)
    return manifest


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_filter_text(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def now_text() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def emit(log: BatchLogCallback | None, message: str) -> None:
    if log:
        log(message)
