from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.modules.sourcing_1688.link_importer import Link1688ImportError, import_1688_links
from app.modules.yunqi.importer import YunqiImportError, import_yunqi_file

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


class Import1688LinksRequest(BaseModel):
    product_urls: list[str] = Field(..., min_length=1)


@router.post("/yunqi")
async def upload_yunqi_file(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    try:
        return import_yunqi_file(file.file, file.filename)
    except YunqiImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"导入失败：{exc}") from exc


@router.post("/1688")
def upload_1688_links(payload: Import1688LinksRequest):
    try:
        return import_1688_links(payload.product_urls)
    except Link1688ImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"1688 链接采集失败：{exc}") from exc
