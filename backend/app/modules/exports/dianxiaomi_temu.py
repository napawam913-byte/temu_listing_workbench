from __future__ import annotations

import re
import shutil
import uuid
from copy import copy
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.core.config import DIANXIAOMI_TEMU_TEMPLATE_PATH, EXPORTS_DIR, ensure_runtime_dirs
from app.modules.creative_generation.listing_title_optimizer import (
    optimize_listing_titles,
    translate_variant_values_to_english,
)
from app.modules.image_storage.aliyun_oss import ImageStorageError, mirror_export_image

TEMPLATE_SHEET_NAME = "导入模板"
HEADER_ROW = 1
DATA_START_ROW = 2
EXPORT_MODE_DISTRIBUTION = "distribution"
EXPORT_MODE_CURATED = "curated"

DEFAULT_LENGTH_CM = 10
DEFAULT_WIDTH_CM = 10
DEFAULT_HEIGHT_CM = 5
DEFAULT_WEIGHT_G = 200
DEFAULT_DECLARED_PRICE = 300
DEFAULT_STOCK = 0
DEFAULT_DELIVERY_DAYS = ""
MAX_CAROUSEL_IMAGE_COUNT = 10
MAX_PRODUCT_MATERIAL_IMAGE_COUNT = 1

TITLE_TRANSLATIONS = {
    "龙之宇": "Longzhiyu",
    "钥匙扣套装": "Keychain Set",
    "钥匙扣": "Keychain",
    "钥匙链": "Key Chain",
    "龙虾扣": "Lobster Clasp",
    "小挂件": "Small Pendant",
    "挂件": "Pendant",
    "软胶": "Soft Rubber",
    "立体": "3D",
    "娃娃": "Doll",
    "定制": "Custom",
    "套装": "Set",
    "可爱": "Cute",
    "创意": "Creative",
    "书包": "Backpack",
    "包包": "Bag",
    "背包": "Backpack",
    "配饰": "Accessory",
    "饰品": "Accessory",
    "饰扣": "Charm",
    "服装": "Clothing",
    "汽车": "Car",
    "首字母": "Initial",
    "爱心": "Heart",
    "流苏": "Tassel",
    "滴胶": "Resin",
    "跨境": "Cross-border",
    "热销": "Best-selling",
    "门店": "Store",
    "小礼品": "Small Gift",
    "礼品": "Gift",
    "礼物": "Gift",
    "食玩": "Toy Candy",
    "面包": "Bread",
    "批发": "Wholesale",
    "波西米亚": "Bohemian",
    "海星": "Starfish",
    "手工": "Handmade",
    "编织": "Woven",
    "手链": "Bracelet",
    "手饰": "Hand Jewelry",
    "陶瓷": "Ceramic",
    "材质": "Material",
    "配件": "Accessory",
    "闺蜜": "Best Friend",
    "朋友": "Friend",
    "同学": "Classmate",
    "节日": "Holiday",
    "最佳": "Best",
    "微波炉": "Microwave",
    "三明治机": "Sandwich Maker",
    "快速": "Quick",
    "清洁": "Easy Clean",
    "家庭": "Home",
    "烹饪": "Cooking",
    "朋克": "Punk",
    "街头": "Street",
    "项链": "Necklace",
    "不锈钢": "Stainless Steel",
    "吊坠": "Pendant",
    "镀金": "Gold Plated",
    "简约": "Minimalist",
    "时尚": "Fashion",
    "男士": "Men",
    "女士": "Women",
    "儿童": "Kids",
    "少女": "Girls",
    "透明": "Clear",
    "礼品袋": "Gift Bag",
    "防水": "Waterproof",
    "香水": "Perfume",
    "烘焙": "Bakery",
    "生日": "Birthday",
    "派对": "Party",
    "毕业": "Graduation",
    "糖果盒": "Candy Box",
    "纸质": "Paper",
    "装饰": "Decoration",
    "PVC": "PVC",
    "Y2K": "Y2K",
}

ALLOWED_VARIANT_NAMES = [
    "颜色",
    "风格",
    "材质",
    "口味",
    "适用人群",
    "容量",
    "成分",
    "重量",
    "品类",
    "数量",
    "型号",
    "头发长度",
    "被套尺码",
    "RAM+ROM",
    "存储容量",
    "厚被尺码",
    "手机型号",
]

VARIANT_NAME_ALIASES = {
    "颜色": "颜色",
    "颜色分类": "颜色",
    "色": "颜色",
    "color": "颜色",
    "colour": "颜色",
    "风格": "风格",
    "款式": "风格",
    "样式": "风格",
    "style": "风格",
    "材质": "材质",
    "材料": "材质",
    "material": "材质",
    "口味": "口味",
    "味道": "口味",
    "flavor": "口味",
    "flavour": "口味",
    "适用人群": "适用人群",
    "人群": "适用人群",
    "适用年龄": "适用人群",
    "容量": "容量",
    "容积": "容量",
    "capacity": "容量",
    "成分": "成分",
    "重量": "重量",
    "净重": "重量",
    "毛重": "重量",
    "weight": "重量",
    "品类": "品类",
    "类别": "品类",
    "分类": "品类",
    "数量": "数量",
    "件数": "数量",
    "个数": "数量",
    "包装数量": "数量",
    "型号": "型号",
    "尺寸": "型号",
    "尺码": "型号",
    "model": "型号",
    "头发长度": "头发长度",
    "发长": "头发长度",
    "被套尺码": "被套尺码",
    "ram+rom": "RAM+ROM",
    "内存组合": "RAM+ROM",
    "存储容量": "存储容量",
    "存储": "存储容量",
    "厚被尺码": "厚被尺码",
    "手机型号": "手机型号",
    "适用型号": "手机型号",
}


class DianxiaomiExportError(Exception):
    pass


def export_dianxiaomi_temu_template(records: list[dict[str, Any]], export_mode: str = EXPORT_MODE_CURATED) -> Path:
    export_mode = normalize_export_mode(export_mode)
    ensure_runtime_dirs()
    if not DIANXIAOMI_TEMU_TEMPLATE_PATH.exists():
        raise DianxiaomiExportError("缺少店小秘 TEMU 半托管导入模板")

    normalized_records = [record for record in records if record.get("skuEntries")]
    if not normalized_records:
        raise DianxiaomiExportError("没有可导出的 SKU 链接记录")

    export_path = EXPORTS_DIR / f"dianxiaomi_temu_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.xlsx"
    shutil.copyfile(DIANXIAOMI_TEMU_TEMPLATE_PATH, export_path)

    workbook = load_workbook(export_path)
    worksheet = workbook[TEMPLATE_SHEET_NAME]
    template_row = DATA_START_ROW

    if worksheet.max_row > DATA_START_ROW:
        worksheet.delete_rows(DATA_START_ROW + 1, worksheet.max_row - DATA_START_ROW)
    for column_index in range(1, worksheet.max_column + 1):
        worksheet.cell(row=DATA_START_ROW, column=column_index).value = None

    output_rows: list[list[Any]] = []
    for record in normalized_records:
        output_rows.extend(build_rows_for_record(record, export_mode=export_mode))

    for offset, values in enumerate(output_rows):
        row_index = DATA_START_ROW + offset
        clone_row_style(worksheet, template_row, row_index)
        for column_index, value in enumerate(values, start=1):
            worksheet.cell(row=row_index, column=column_index, value=value)

    workbook.save(export_path)
    return export_path


def build_rows_for_record(record: dict[str, Any], export_mode: str = EXPORT_MODE_CURATED) -> list[list[Any]]:
    export_mode = normalize_export_mode(export_mode)
    sku_entries = record.get("skuEntries") or []
    product_title = clean_text(record.get("productTitle")) or "未命名商品"
    product_title_en = normalize_english_title(record.get("productTitleEn"), product_title)
    optimized_titles = optimize_listing_titles(
        record,
        fallback_title_cn=product_title,
        fallback_title_en=product_title_en,
    )
    product_title = optimized_titles["title_cn"]
    product_title_en = optimized_titles["title_en"]
    product_id = clean_text(record.get("productId")) or uuid.uuid4().hex[:10]
    raw_main_image_url = pick_record_main_image(record, export_mode)
    main_image_url = export_image_url(raw_main_image_url, product_id, "main", 1, record)
    material_image_urls = unique_http_urls([
        export_image_url(image_url, product_id, "material", index, record)
        for index, image_url in enumerate(pick_product_material_images(record, export_mode, raw_main_image_url), start=1)
    ])
    source_url = pick_record_source_url(record)
    variant_count = len(sku_entries)
    carousel_image_urls = material_image_urls[:MAX_CAROUSEL_IMAGE_COUNT]
    carousel_images = "\n".join(carousel_image_urls)
    product_material_images = "\n".join(material_image_urls[:MAX_PRODUCT_MATERIAL_IMAGE_COUNT])
    description = build_description_from_images(carousel_image_urls)

    prepared_skus: list[tuple[dict[str, Any], str, list[tuple[str, str]]]] = []
    raw_variant_values: list[str] = []
    for index, sku_entry in enumerate(sku_entries, start=1):
        sku_name = clean_text(sku_entry.get("name")) or f"SKU {index}"
        variant_pairs = derive_variant_pairs(sku_entry, sku_name)
        prepared_skus.append((sku_entry, sku_name, variant_pairs))
        raw_variant_values.extend(value for _name, value in variant_pairs)

    variant_value_translations = translate_variant_values_to_english(raw_variant_values)

    rows: list[list[Any]] = []
    for index, (sku_entry, sku_name, raw_variant_pairs) in enumerate(prepared_skus, start=1):
        sku_image_url = export_image_url(pick_sku_image(sku_entry, export_mode), product_id, "sku", index, record) or main_image_url
        weight_g = weight_to_grams(sku_entry.get("weight")) or DEFAULT_WEIGHT_G
        variant_pairs = [
            (name, variant_value_translations.get(value, value))
            for name, value in raw_variant_pairs
        ]
        variant_one = variant_pairs[0]
        variant_two = variant_pairs[1] if len(variant_pairs) > 1 else ("", "")

        rows.append(
            [
                product_title,  # A *产品标题
                product_title_en,  # B *英文标题
                description,  # C 产品描述
                "",  # D 产品货号
                variant_one[0],  # E *变种属性名称一
                variant_one[1],  # F *变种属性值一
                variant_two[0],  # G 变种属性名称二
                variant_two[1],  # H 变种属性值二
                sku_image_url,  # I 预览图
                DEFAULT_DECLARED_PRICE,  # J *申报价格
                "",  # K SKU货号
                DEFAULT_LENGTH_CM,  # L *长（cm）
                DEFAULT_WIDTH_CM,  # M *宽（cm）
                DEFAULT_HEIGHT_CM,  # N *高（cm）
                weight_g,  # O *重量（g）
                "",  # P 识别码类型
                "",  # Q 识别码
                "",  # R 站外产品链接
                carousel_images,  # S *轮播图
                product_material_images,  # T *产品素材图
                "不规则",  # U 外包装形状
                "硬包装",  # V 外包装类型
                "",  # W 外包装图片
                "",  # X 建议售价（USD）
                DEFAULT_STOCK,  # Y 库存
                DEFAULT_DELIVERY_DAYS,  # Z 发货时效（天）
                source_url,  # AA 真实详情页URL
                "未知",  # AB 是否无属性
                variant_count,  # AC 变体数量
            ]
        )

    return rows


def normalize_english_title(raw_title_en: Any, product_title: str) -> str:
    title_en = clean_text(raw_title_en)
    if title_en and not contains_cjk(title_en):
        return title_en

    translated = translate_title_locally(product_title)
    return translated or "Assorted Product"


def translate_title_locally(title: str) -> str:
    text = clean_text(title)
    if not text:
        return ""
    if not contains_cjk(text):
        return text

    for chinese, english in sorted(TITLE_TRANSLATIONS.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(chinese, f" {english} ")

    text = re.sub(r"[，,、/|]+", " ", text)
    text = re.sub(r"[（）()【】\[\]：:；;，,。.!！?？]", " ", text)
    text = re.sub(r"[\u4e00-\u9fff]+", " ", text)
    words = []
    seen: set[str] = set()
    for word in re.split(r"\s+", text):
        clean_word = word.strip("-_ ")
        if not clean_word:
            continue
        key = clean_word.lower()
        if key in seen:
            continue
        seen.add(key)
        words.append(clean_word)

    result = " ".join(words)
    result = re.sub(r"\s+", " ", result).strip(" -")
    if len(result.split()) < 2:
        return "Assorted Product"
    return result[:240]


def contains_cjk(value: Any) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(value or "")))


def derive_variant_pairs(sku_entry: dict[str, Any], fallback_value: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []

    for component in sku_entry.get("componentSkus") or []:
        if not isinstance(component, dict):
            continue
        raw_specs = component.get("rawSpecs") or {}
        if isinstance(raw_specs, dict):
            for raw_name, raw_value in raw_specs.items():
                add_variant_candidate(candidates, raw_name, raw_value)
        add_variant_candidates_from_text(candidates, component.get("specText"))

    for source_sku in sku_entry.get("sourceSkuLinks") or []:
        if not isinstance(source_sku, dict):
            continue
        add_variant_candidates_from_text(candidates, source_sku.get("specText"))
        add_variant_candidates_from_text(candidates, source_sku.get("optionText"))

    add_variant_candidates_from_text(candidates, sku_entry.get("name"))

    merged: dict[str, list[str]] = {}
    has_named_candidates = any(clean_text(raw_name) for raw_name, _raw_value in candidates)
    for raw_name, raw_value in candidates:
        name = normalize_variant_name(raw_name, raw_value)
        value = clean_text(raw_value)
        if not value:
            continue
        if has_named_candidates and not clean_text(raw_name) and name == "型号":
            continue
        merged.setdefault(name, [])
        if value not in merged[name]:
            merged[name].append(value)

    pairs = [(name, "+".join(values)) for name, values in merged.items() if values]
    if pairs:
        return pairs[:2]

    fallback_name = normalize_variant_name("", fallback_value)
    return [(fallback_name, clean_text(fallback_value) or "默认款")]


def add_variant_candidate(candidates: list[tuple[str, str]], raw_name: Any, raw_value: Any) -> None:
    name = clean_text(raw_name)
    value = clean_text(raw_value)
    if not value:
        return
    candidates.append((name, value))


def add_variant_candidates_from_text(candidates: list[tuple[str, str]], value: Any) -> None:
    text = clean_text(value)
    if not text:
        return

    found = False
    for segment in re.split(r"[,，;；\n]+", text):
        if ":" in segment or "：" in segment:
            raw_name, raw_value = re.split(r"[:：]", segment, maxsplit=1)
            if clean_text(raw_name) and clean_text(raw_value):
                add_variant_candidate(candidates, raw_name, raw_value)
                found = True

    if not found:
        candidates.append(("", text))


def normalize_variant_name(raw_name: Any, raw_value: Any = "") -> str:
    name = clean_text(raw_name)
    value = clean_text(raw_value)
    if name in ALLOWED_VARIANT_NAMES:
        return name

    normalized_name = normalize_variant_key(name)
    if normalized_name in VARIANT_NAME_ALIASES:
        return VARIANT_NAME_ALIASES[normalized_name]

    text = f"{name} {value}".lower()
    if re.search(r"ram\s*\+?\s*rom|内存组合", text):
        return "RAM+ROM"
    if re.search(r"\b\d+\s*(?:gb|tb)\b|存储|内存|容量", text, re.I):
        return "存储容量" if "容量" not in text else "容量"
    if re.search(r"iphone|手机|华为|小米|oppo|vivo|samsung|三星|适用型号", text, re.I):
        return "手机型号"
    if re.search(r"kg|公斤|千克|g\b|克|重量|净重|毛重", text, re.I):
        return "重量"
    if re.search(r"\d+\s*(?:件|个|只|套|pcs?|pc)|数量|件数|起订|起批", text, re.I):
        return "数量"
    if re.search(r"黑|白|红|蓝|绿|黄|紫|粉|金|银|灰|棕|色|color", text, re.I):
        return "颜色"
    if re.search(r"pvc|硅胶|金属|不锈钢|陶瓷|木|塑料|材质|材料", text, re.I):
        return "材质"
    if re.search(r"男|女|儿童|成人|宝宝|宠物|适用人群", text):
        return "适用人群"
    if re.search(r"口味|味|flavo[u]?r", text, re.I):
        return "口味"
    if re.search(r"风格|款式|style", text, re.I):
        return "风格"
    if re.search(r"品类|类别|分类", text):
        return "品类"

    return "型号"


def normalize_variant_key(value: str) -> str:
    return re.sub(r"[\s/_\-（）()【】\[\]]+", "", value).lower()


def normalize_export_mode(export_mode: str) -> str:
    if export_mode == EXPORT_MODE_DISTRIBUTION:
        return EXPORT_MODE_DISTRIBUTION
    return EXPORT_MODE_CURATED


def pick_record_main_image(record: dict[str, Any], export_mode: str = EXPORT_MODE_CURATED) -> str:
    slot_main_image = first_non_empty(*pick_slot_image_urls(record, "main", export_mode))
    if slot_main_image:
        return slot_main_image

    if export_mode == EXPORT_MODE_DISTRIBUTION:
        return pick_original_record_main_image(record)

    main_image = record.get("mainImage") or {}
    return first_non_empty(
        main_image.get("editedCloudUrl"),
        main_image.get("editedUrl"),
        main_image.get("displayCloudUrl"),
        main_image.get("displayUrl"),
        main_image.get("sourceCloudUrl"),
        main_image.get("sourceUrl"),
        record.get("productImageUrl"),
        *(source.get("imageUrl") for source in record.get("sourceLinks") or [] if isinstance(source, dict)),
    )


def pick_original_record_main_image(record: dict[str, Any]) -> str:
    main_image = record.get("mainImage") or {}
    return first_non_empty(
        *(source.get("imageUrl") for source in record.get("sourceLinks") or [] if isinstance(source, dict)),
        main_image.get("sourceCloudUrl"),
        main_image.get("sourceUrl"),
        record.get("productImageUrl"),
        main_image.get("displayCloudUrl"),
        main_image.get("displayUrl"),
        main_image.get("editedCloudUrl"),
        main_image.get("editedUrl"),
    )


def pick_product_material_images(record: dict[str, Any], export_mode: str, main_image_url: str) -> list[str]:
    slot_image_urls = pick_slot_image_urls(record, "carousel", export_mode)
    if slot_image_urls:
        return slot_image_urls[:MAX_CAROUSEL_IMAGE_COUNT]

    image_assets = [asset for asset in record.get("productMaterialImages") or [] if isinstance(asset, dict)]
    if export_mode == EXPORT_MODE_DISTRIBUTION:
        return unique_strings(
            [
                *(pick_asset_original_url(asset) for asset in image_assets),
                *(source.get("imageUrl") for source in record.get("sourceLinks") or [] if isinstance(source, dict)),
                main_image_url,
            ]
        )

    return unique_strings([*(pick_asset_curated_url(asset) for asset in image_assets), main_image_url])


def pick_slot_image_urls(record: dict[str, Any], slot_type: str, export_mode: str) -> list[str]:
    image_slots = [slot for slot in record.get("imageSlots") or [] if isinstance(slot, dict)]
    if not image_slots:
        return []

    asset_map = build_record_asset_map(record)
    image_urls: list[str] = []
    for slot in sorted(image_slots, key=lambda item: positive_number(item.get("order")) or 0):
        if slot.get("type") != slot_type:
            continue
        asset = asset_map.get(clean_text(slot.get("assetId"))) or {}
        image_url = (
            pick_asset_original_url(asset)
            if export_mode == EXPORT_MODE_DISTRIBUTION
            else pick_asset_curated_url(asset)
        )
        image_urls.append(first_non_empty(image_url, slot.get("imageUrl"), slot.get("url")))
    return unique_strings(image_urls)


def build_record_asset_map(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    asset_map: dict[str, dict[str, Any]] = {}

    def add_asset(asset: Any) -> None:
        if not isinstance(asset, dict):
            return
        asset_id = clean_text(asset.get("id"))
        if asset_id:
            asset_map[asset_id] = asset

    add_asset(record.get("mainImage"))
    for asset in record.get("productMaterialImages") or []:
        add_asset(asset)

    for index, source in enumerate(record.get("sourceLinks") or [], start=1):
        if not isinstance(source, dict):
            continue
        source_image_url = clean_text(source.get("imageUrl"))
        if source_image_url:
            source_id = clean_text(source.get("id")) or str(index)
            add_asset(
                {
                    "id": f"{record.get('id')}-source-image-{source_id}",
                    "role": "product-material",
                    "sourceUrl": source_image_url,
                    "displayUrl": source_image_url,
                }
            )

    for sku_entry in record.get("skuEntries") or []:
        if not isinstance(sku_entry, dict):
            continue
        add_asset(sku_entry.get("imageAsset"))
        sku_image_url = clean_text(sku_entry.get("imageUrl"))
        sku_entry_id = clean_text(sku_entry.get("id"))
        if sku_image_url and sku_entry_id:
            add_asset(
                {
                    "id": f"{record.get('id')}-sku-url-{sku_entry_id}",
                    "role": "sales-sku",
                    "sourceUrl": sku_image_url,
                    "displayUrl": sku_image_url,
                }
            )

    for job in record.get("creativeJobs") or []:
        if not isinstance(job, dict):
            continue
        result_image_url = clean_text(job.get("resultImageUrl"))
        job_id = clean_text(job.get("id"))
        if result_image_url and job_id:
            add_asset(
                {
                    "id": f"{record.get('id')}-creative-job-{job_id}",
                    "role": "sales-sku" if job.get("targetSkuEntryId") else "product-material",
                    "editedUrl": result_image_url,
                    "editedCloudUrl": result_image_url,
                }
            )

    return asset_map


def build_description_from_images(image_urls: list[str]) -> str:
    return "\n".join(unique_http_urls(image_urls))


def pick_sku_image(sku_entry: dict[str, Any], export_mode: str = EXPORT_MODE_CURATED) -> str:
    image_asset = sku_entry.get("imageAsset") or {}
    if export_mode == EXPORT_MODE_DISTRIBUTION:
        return first_non_empty(
            pick_asset_original_url(image_asset),
            sku_entry.get("imageUrl"),
            *pick_sku_link_images(sku_entry),
        )

    return first_non_empty(
        pick_asset_curated_url(image_asset),
        sku_entry.get("imageUrl"),
        *pick_sku_link_images(sku_entry),
    )


def pick_sku_link_images(sku_entry: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for source_sku in sku_entry.get("sourceSkuLinks") or []:
        if isinstance(source_sku, dict):
            candidates.append(source_sku.get("imageUrl"))
    for component in sku_entry.get("componentSkus") or []:
        if isinstance(component, dict):
            candidates.extend([component.get("imageUrl"), component.get("sourceImageUrl")])
    return candidates


def pick_asset_original_url(image_asset: dict[str, Any]) -> str:
    return first_non_empty(
        image_asset.get("sourceCloudUrl"),
        image_asset.get("sourceUrl"),
        image_asset.get("displayCloudUrl"),
        image_asset.get("displayUrl"),
        image_asset.get("editedCloudUrl"),
        image_asset.get("editedUrl"),
    )


def pick_asset_curated_url(image_asset: dict[str, Any]) -> str:
    return first_non_empty(
        image_asset.get("editedCloudUrl"),
        image_asset.get("editedUrl"),
        image_asset.get("displayCloudUrl"),
        image_asset.get("displayUrl"),
        image_asset.get("sourceCloudUrl"),
        image_asset.get("sourceUrl"),
    )


def export_image_url(image_url: str, product_id: str, role: str, index: int, record: dict[str, Any]) -> str:
    clean_url = clean_text(image_url)
    if not clean_url:
        return ""
    if is_http_url(clean_url) and not is_processed_image_url(record, clean_url):
        return clean_url
    try:
        return mirror_export_image(clean_url, f"{build_image_key_product_part(product_id)}/{role}-{index}")
    except ImageStorageError as exc:
        if is_http_url(clean_url):
            return clean_url
        raise DianxiaomiExportError(str(exc)) from exc


def is_processed_image_url(record: dict[str, Any], image_url: str) -> bool:
    clean_url = clean_text(image_url)
    if not clean_url:
        return False

    for asset in iter_record_image_assets(record):
        if not isinstance(asset, dict):
            continue
        if clean_url in processed_asset_urls(asset):
            return True
    return False


def iter_record_image_assets(record: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []

    def add_asset(asset: Any) -> None:
        if isinstance(asset, dict):
            assets.append(asset)

    add_asset(record.get("mainImage"))
    for asset in record.get("productMaterialImages") or []:
        add_asset(asset)
    for sku_entry in record.get("skuEntries") or []:
        if isinstance(sku_entry, dict):
            add_asset(sku_entry.get("imageAsset"))
    for job in record.get("creativeJobs") or []:
        if not isinstance(job, dict):
            continue
        result_image_url = clean_text(job.get("resultImageUrl"))
        if result_image_url:
            add_asset(
                {
                    "editedUrl": result_image_url,
                    "editedCloudUrl": result_image_url,
                    "storageKey": job.get("resultStorageKey") or "",
                }
            )
    return assets


def processed_asset_urls(asset: dict[str, Any]) -> set[str]:
    urls = {
        clean_text(asset.get("editedCloudUrl")),
        clean_text(asset.get("editedUrl")),
    }
    if clean_text(asset.get("storageKey")):
        urls.update(
            {
                clean_text(asset.get("displayCloudUrl")),
                clean_text(asset.get("displayUrl")),
            }
        )
    return {url for url in urls if url}


def build_image_key_product_part(product_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", product_id).strip("-")[:64] or "product"


def pick_record_source_url(record: dict[str, Any]) -> str:
    return first_non_empty(
        record.get("productSourceUrl"),
        *(source.get("productUrl") for source in record.get("sourceLinks") or [] if isinstance(source, dict)),
    )


def build_sku_code(product_id: str, index: int, sku_entry: dict[str, Any]) -> str:
    raw_id = clean_text(sku_entry.get("id")) or f"sku-{index}"
    clean_product_id = re.sub(r"[^A-Za-z0-9_-]+", "-", product_id).strip("-")[:36] or "product"
    clean_sku_id = re.sub(r"[^A-Za-z0-9_-]+", "-", raw_id).strip("-")[:28] or f"sku-{index}"
    return f"{clean_product_id}-{index}-{clean_sku_id}"


def weight_to_grams(value: Any) -> int | None:
    number = positive_number(value)
    if number is None:
        return None
    # LinkList 的 weight 来自 1688 采集，单位约定为 kg。
    return max(1, round(number * 1000))


def positive_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def first_non_empty(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = clean_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def unique_http_urls(values: list[str]) -> list[str]:
    return [value for value in unique_strings(values) if is_http_url(value)]


def is_http_url(value: Any) -> bool:
    return clean_text(value).lower().startswith(("http://", "https://"))


def clone_row_style(worksheet: Any, template_row: int, target_row: int) -> None:
    if target_row == template_row:
        return
    worksheet.row_dimensions[target_row].height = worksheet.row_dimensions[template_row].height
    for column_index in range(1, worksheet.max_column + 1):
        source = worksheet.cell(row=template_row, column=column_index)
        target = worksheet.cell(row=target_row, column=column_index)
        if source.has_style:
            target.font = copy(source.font)
            target.fill = copy(source.fill)
            target.border = copy(source.border)
            target.alignment = copy(source.alignment)
            target.number_format = source.number_format
            target.protection = copy(source.protection)
