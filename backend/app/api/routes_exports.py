from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.auth import require_current_user
from app.modules.exports.dianxiaomi_temu import EXPORT_MODE_CURATED, DianxiaomiExportError, export_dianxiaomi_temu_template

router = APIRouter(prefix="/api/exports", tags=["exports"])


class DianxiaomiTemuExportRequest(BaseModel):
    records: list[dict[str, Any]] = Field(default_factory=list)
    export_mode: str = Field(default=EXPORT_MODE_CURATED)


@router.post("/dianxiaomi/temu-semi-managed")
def export_dianxiaomi_temu(
    payload: DianxiaomiTemuExportRequest,
    current_user: dict[str, Any] = Depends(require_current_user),
):
    try:
        export_path = export_dianxiaomi_temu_template(payload.records, export_mode=payload.export_mode)
    except DianxiaomiExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return FileResponse(
        export_path,
        filename=export_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
