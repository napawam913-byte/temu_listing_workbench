from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from app.core.config import UPLOADS_DIR, ensure_runtime_dirs
from app.core.database import PRODUCT_CATALOG_SCOPE_POOL_ONLY, insert_upload_batch, replace_products
from app.modules.yunqi.cleaner import normalize_yunqi_dataframe


class YunqiImportError(Exception):
    pass


def import_yunqi_file(file_obj: BinaryIO, filename: str, *, add_to_pool_user_id: str | None = None) -> dict[str, object]:
    ensure_runtime_dirs()
    batch_id = uuid.uuid4().hex
    safe_filename = Path(filename).name
    saved_path = UPLOADS_DIR / f"{batch_id}_{safe_filename}"

    with saved_path.open("wb") as target:
        shutil.copyfileobj(file_obj, target)

    file_type = detect_file_type(saved_path)
    df = read_yunqi_dataframe(saved_path, file_type)
    products, errors = normalize_yunqi_dataframe(df)

    insert_upload_batch(
        batch_id=batch_id,
        source_filename=safe_filename,
        saved_path=saved_path,
        file_type=file_type,
        total_rows=len(df),
        imported_count=len(products),
        failed_count=len(errors),
        status="imported",
        error_message="\n".join(errors[:20]) if errors else None,
    )
    replace_products(
        batch_id,
        products,
        add_to_pool_user_id=add_to_pool_user_id,
        catalog_scope=PRODUCT_CATALOG_SCOPE_POOL_ONLY if add_to_pool_user_id else None,
    )

    return {
        "batch_id": batch_id,
        "source_filename": safe_filename,
        "file_type": file_type,
        "total_rows": len(df),
        "imported_count": len(products),
        "failed_count": len(errors),
        "errors": errors[:20],
    }


def detect_file_type(path: Path) -> str:
    with path.open("rb") as file:
        magic = file.read(4)
    if magic.startswith(b"PK\x03\x04"):
        return "xlsx"
    return "csv"


def read_yunqi_dataframe(path: Path, file_type: str) -> pd.DataFrame:
    if file_type == "xlsx":
        return pd.read_excel(path, engine="openpyxl", header=1)

    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return pd.read_csv(path, encoding=encoding, header=1)
        except Exception as exc:  # noqa: BLE001
            last_error = exc

    raise YunqiImportError(f"无法读取云启 CSV 文件：{last_error}")
