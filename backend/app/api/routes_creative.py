from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.database import list_sensitive_terms
from app.modules.creative_generation.chatgpt_listing import CreativeGenerationError, generate_listing_package
from app.modules.creative_generation.plugin_jobs import (
    CreativePluginJobError,
    claim_next_plugin_job,
    claim_next_plugin_jobs,
    complete_plugin_job,
    create_plugin_jobs,
    list_plugin_jobs,
    sync_records_with_plugin_jobs,
)
from app.modules.sourcing_1688.smart_recommendations import (
    generate_smart_1688_keywords,
    generate_smart_1688_recommendations,
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
    analysis_text: str | None = None
    error_message: str | None = None


class Smart1688RecommendationsRequest(BaseModel):
    product: dict[str, Any] = Field(default_factory=dict)
    keywords: list[dict[str, Any] | str] = Field(default_factory=list)
    limit: int = Field(default=6, ge=1, le=12)


@router.post("/chatgpt/listing-package")
def create_chatgpt_listing_package(payload: ChatgptListingPackageRequest):
    try:
        return generate_listing_package(payload.record, generate_images=payload.generate_images)
    except CreativeGenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/1688-smart-recommendations")
def create_1688_smart_recommendations(payload: Smart1688RecommendationsRequest):
    try:
        return generate_smart_1688_recommendations(payload.product, keywords=payload.keywords, limit=payload.limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/1688-smart-keywords")
def create_1688_smart_keywords(payload: Smart1688RecommendationsRequest):
    try:
        return generate_smart_1688_keywords(payload.product)
    except ValueError as exc:
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


@router.get("/plugin/jobs/next-batch")
def get_next_plugin_creative_jobs(provider: str = "plugin_chatgpt_web", limit: int = 20):
    jobs = claim_next_plugin_jobs(provider=provider, limit=limit)
    return {"items": jobs}


@router.post("/plugin/jobs/{job_id}/result")
def upload_plugin_creative_job_result(job_id: str, payload: PluginCreativeJobResultRequest):
    try:
        return complete_plugin_job(
            job_id,
            image_data_url=payload.image_data_url,
            image_url=payload.image_url,
            analysis_text=payload.analysis_text,
            error_message=payload.error_message,
        )
    except CreativePluginJobError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sensitive-terms")
def get_sensitive_terms(enabled: bool | None = None, category: str | None = None):
    return {"items": list_sensitive_terms(enabled=enabled, category=category)}
