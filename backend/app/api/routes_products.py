from fastapi import APIRouter, HTTPException, Query

from app.core.database import (
    get_product_categories,
    get_product_stats,
    list_products,
    soft_delete_product,
)

router = APIRouter(prefix="/api/products", tags=["products"])


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
    )


@router.get("/stats")
def product_stats():
    return get_product_stats()


@router.get("/categories")
def product_categories():
    return get_product_categories()


@router.delete("/{product_id}")
def delete_product(product_id: str):
    deleted = soft_delete_product(product_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="商品不存在")
    return {"ok": True}
