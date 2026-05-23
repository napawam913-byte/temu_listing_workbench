from fastapi import APIRouter, File, HTTPException, UploadFile

from app.modules.yunqi.importer import YunqiImportError, import_yunqi_file

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


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
