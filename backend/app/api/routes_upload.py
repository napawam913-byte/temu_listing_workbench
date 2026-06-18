from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.auth import require_current_user
from app.modules.dianxiaomi.template_importer import (
    DianxiaomiTemplateImportError,
    import_dianxiaomi_template_file,
)
from app.modules.sourcing_1688.link_importer import Link1688ImportError, import_1688_links
from app.modules.yunqi.importer import YunqiImportError, import_yunqi_file

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


class Import1688LinksRequest(BaseModel):
    product_urls: list[str] = Field(..., min_length=1)


@router.post("/yunqi")
async def upload_yunqi_file(
    file: UploadFile = File(...),
    current_user: dict[str, Any] = Depends(require_current_user),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    try:
        return import_yunqi_file(file.file, file.filename, add_to_pool_user_id=current_user["id"])
    except YunqiImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"导入失败：{exc}") from exc


@router.post("/dianxiaomi-template")
async def upload_dianxiaomi_template_file(
    file: UploadFile = File(...),
    current_user: dict[str, Any] = Depends(require_current_user),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    suffix = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if suffix not in {"xlsx", "xlsm"}:
        raise HTTPException(status_code=400, detail="请上传店小秘标准 Excel 模板（.xlsx 或 .xlsm）")

    try:
        return import_dianxiaomi_template_file(file.file, file.filename, user_id=current_user["id"])
    except DianxiaomiTemplateImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"店小秘模板导入失败：{exc}") from exc


@router.post("/1688")
def upload_1688_links(payload: Import1688LinksRequest, current_user: dict[str, Any] = Depends(require_current_user)):
    try:
        return import_1688_links(payload.product_urls, add_to_pool_user_id=current_user["id"])
    except Link1688ImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"1688 链接采集失败：{exc}") from exc
