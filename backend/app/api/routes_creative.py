from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.database import list_sensitive_terms
from app.modules.creative_generation.chatgpt_listing import CreativeGenerationError, generate_listing_package
from app.modules.creative_generation.plugin_jobs import (
    CreativePluginJobError,
    claim_next_plugin_job,
    complete_plugin_job,
    create_plugin_jobs,
    list_plugin_jobs,
    sync_records_with_plugin_jobs,
)

router = APIRouter(prefix="/api/creative", tags=["creative"])


class ChatgptListingPackageRequest(BaseModel):
    record: dict[str, Any] = Field(default_factory=dict)
    generate_images: bool = Field(default=True)


class PluginCreativeJobsRequest(BaseModel):
    records: list[dict[str, Any]] = Field(default_factory=list)
    provider: str = Field(default="plugin_chatgpt_web")


class PluginCreativeJobResultRequest(BaseModel):
    image_data_url: str | None = None
    image_url: str | None = None
    error_message: str | None = None


@router.post("/chatgpt/listing-package")
def create_chatgpt_listing_package(payload: ChatgptListingPackageRequest):
    try:
        return generate_listing_package(payload.record, generate_images=payload.generate_images)
    except CreativeGenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/plugin/jobs")
def create_plugin_creative_jobs(payload: PluginCreativeJobsRequest):
    jobs = create_plugin_jobs(payload.records, provider=payload.provider)
    return {"items": jobs}


@router.post("/plugin/jobs/sync")
def sync_plugin_creative_jobs(payload: PluginCreativeJobsRequest):
    return sync_records_with_plugin_jobs(payload.records, provider=payload.provider)


@router.get("/plugin/jobs")
def get_plugin_creative_jobs(
    provider: str = "plugin_chatgpt_web",
    record_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
):
    return {"items": list_plugin_jobs(provider=provider, record_id=record_id, status=status, limit=limit)}


@router.get("/plugin/jobs/next")
def get_next_plugin_creative_job(provider: str = "plugin_chatgpt_web"):
    job = claim_next_plugin_job(provider=provider)
    return {"item": job}


@router.post("/plugin/jobs/{job_id}/result")
def upload_plugin_creative_job_result(job_id: str, payload: PluginCreativeJobResultRequest):
    try:
        return complete_plugin_job(
            job_id,
            image_data_url=payload.image_data_url,
            image_url=payload.image_url,
            error_message=payload.error_message,
        )
    except CreativePluginJobError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sensitive-terms")
def get_sensitive_terms(enabled: bool | None = None, category: str | None = None):
    return {"items": list_sensitive_terms(enabled=enabled, category=category)}
