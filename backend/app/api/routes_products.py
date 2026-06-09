from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.auth import require_current_user
from app.core.database import (
    add_products_to_pool,
    get_product_categories,
    get_product_stats,
    list_products,
    soft_delete_product,
)

router = APIRouter(prefix="/api/products", tags=["products"])


class AddProductsToPoolRequest(BaseModel):
    product_ids: list[str]


@router.get("")
def get_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    keyword: str | None = None,
    period: str | None = None,
    category: str | None = None,
    price_min: float | None = Query(None, ge=0),
    price_max: float | None = Query(None, ge=0),
    sales_min: int | None = Query(None, ge=0),
    sales_max: int | None = Query(None, ge=0),
    gmv_min: float | None = Query(None, ge=0),
    gmv_max: float | None = Query(None, ge=0),
    scope: str = Query("pool", pattern="^(pool|all)$"),
    sort_by: str | None = Query(None, pattern="^(price|gmv)$"),
    sort_order: str | None = Query(None, pattern="^(asc|desc)$"),
    current_user: dict[str, Any] = Depends(require_current_user),
):
    return list_products(
        page=page,
        page_size=page_size,
        keyword=keyword,
        period=period,
        category=category,
        price_min=price_min,
        price_max=price_max,
        sales_min=sales_min,
        sales_max=sales_max,
        gmv_min=gmv_min,
        gmv_max=gmv_max,
        scope=scope,
        sort_by=sort_by,
        sort_order=sort_order,
        user_id=current_user["id"],
    )


@router.get("/stats")
def product_stats(
    scope: str = Query("pool", pattern="^(pool|all)$"),
    current_user: dict[str, Any] = Depends(require_current_user),
):
    return get_product_stats(scope=scope, user_id=current_user["id"])


@router.post("/pool")
def add_to_product_pool(payload: AddProductsToPoolRequest, current_user: dict[str, Any] = Depends(require_current_user)):
    added_count = add_products_to_pool(payload.product_ids, user_id=current_user["id"])
    return {"ok": True, "added_count": added_count}


@router.get("/categories")
def product_categories(current_user: dict[str, Any] = Depends(require_current_user)):
    return get_product_categories()


@router.delete("/{product_id}")
def delete_product(
    product_id: str,
    scope: str = Query("pool", pattern="^(pool|all)$"),
    current_user: dict[str, Any] = Depends(require_current_user),
):
    deleted = soft_delete_product(product_id, scope=scope, user_id=current_user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="商品不存在")
    return {"ok": True}
