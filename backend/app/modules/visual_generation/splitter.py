from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from app.core.image_plugins import register_optional_image_plugins

register_optional_image_plugins()

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


POSITION_NAMES = {
    "1x1": ["center"],
    "2x2": ["top-left", "top-right", "bottom-left", "bottom-right"],
    "3x3": [
        "top-left",
        "top-center",
        "top-right",
        "middle-left",
        "middle-center",
        "middle-right",
        "bottom-left",
        "bottom-center",
        "bottom-right",
    ],
}


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class PanelManifest:
    panelIndex: int
    row: int
    col: int
    position: str
    cellRect: Rect
    cropRect: Rect
    output: str


class GridSplitError(ValueError):
    pass


def parse_layout(layout: str) -> tuple[int, int]:
    normalized = str(layout or "").lower().replace("*", "x").strip()
    if normalized not in POSITION_NAMES:
        raise GridSplitError("layout must be 1x1, 2x2, or 3x3")
    rows, cols = normalized.split("x")
    return int(rows), int(cols)


def layout_key(rows: int, cols: int) -> str:
    return f"{rows}x{cols}"


def centered_square(rect: Rect) -> Rect:
    side = min(rect.width, rect.height)
    return Rect(
        x=rect.x + (rect.width - side) // 2,
        y=rect.y + (rect.height - side) // 2,
        width=side,
        height=side,
    )


def panel_rects(
    image_width: int,
    image_height: int,
    rows: int,
    cols: int,
    safe_margin_ratio: float,
) -> Iterable[tuple[int, int, Rect, Rect]]:
    if safe_margin_ratio < 0 or safe_margin_ratio >= 0.25:
        raise GridSplitError("safe_margin_ratio must be >= 0 and < 0.25")

    for row in range(rows):
        for col in range(cols):
            x0 = round(col * image_width / cols)
            y0 = round(row * image_height / rows)
            x1 = round((col + 1) * image_width / cols)
            y1 = round((row + 1) * image_height / rows)
            cell = Rect(x=x0, y=y0, width=x1 - x0, height=y1 - y0)

            margin_x = round(cell.width * safe_margin_ratio)
            margin_y = round(cell.height * safe_margin_ratio)
            crop = Rect(
                x=cell.x + margin_x,
                y=cell.y + margin_y,
                width=max(1, cell.width - margin_x * 2),
                height=max(1, cell.height - margin_y * 2),
            )
            yield row, col, cell, centered_square(crop)


def save_panel(
    source: Image.Image,
    crop: Rect,
    output_path: Path,
    target_size: int,
    output_format: str,
    quality: int,
    sharpen: float,
) -> None:
    if target_size <= 0:
        raise GridSplitError("target_size must be positive")
    if quality < 1 or quality > 100:
        raise GridSplitError("quality must be between 1 and 100")

    panel = source.crop((crop.x, crop.y, crop.x + crop.width, crop.y + crop.height))
    panel = panel.resize((target_size, target_size), Image.Resampling.LANCZOS)

    if sharpen > 0:
        panel = panel.filter(ImageFilter.UnsharpMask(radius=1.2, percent=int(120 * sharpen), threshold=3))
        panel = ImageEnhance.Sharpness(panel).enhance(1.0 + 0.15 * sharpen)

    normalized_format = output_format.lower()
    if normalized_format in {"jpg", "jpeg"}:
        panel = panel.convert("RGB")
        panel.save(output_path, format="JPEG", quality=quality, optimize=True)
    elif normalized_format == "webp":
        panel.save(output_path, format="WEBP", quality=quality, method=6)
    elif normalized_format == "png":
        panel.save(output_path, format="PNG", optimize=True)
    else:
        raise GridSplitError("format must be webp, jpg, jpeg, or png")


def draw_debug(
    source: Image.Image,
    panels: list[PanelManifest],
    output_path: Path,
    rows: int,
    cols: int,
) -> None:
    debug = source.convert("RGB").copy()
    draw = ImageDraw.Draw(debug)
    font = ImageFont.load_default()

    width, height = debug.size
    red = (230, 40, 40)
    green = (30, 190, 90)
    yellow = (255, 225, 70)

    for col in range(1, cols):
        x = round(col * width / cols)
        draw.line((x, 0, x, height), fill=red, width=max(2, width // 500))
    for row in range(1, rows):
        y = round(row * height / rows)
        draw.line((0, y, width, y), fill=red, width=max(2, height // 500))

    for panel in panels:
        crop = panel.cropRect
        draw.rectangle(
            (crop.x, crop.y, crop.x + crop.width, crop.y + crop.height),
            outline=green,
            width=max(3, min(width, height) // 350),
        )
        label = str(panel.panelIndex).zfill(2)
        label_x = crop.x + 10
        label_y = crop.y + 10
        text_box = draw.textbbox((label_x, label_y), label, font=font)
        pad = 5
        draw.rectangle(
            (
                text_box[0] - pad,
                text_box[1] - pad,
                text_box[2] + pad,
                text_box[3] + pad,
            ),
            fill=yellow,
        )
        draw.text((label_x, label_y), label, fill=(20, 20, 20), font=font)

    debug.save(output_path, format="JPEG", quality=92, optimize=True)


def split_grid_file(
    *,
    input_path: Path,
    output_dir: Path,
    layout: str = "3x3",
    target_size: int = 800,
    safe_margin_ratio: float = 0.03,
    output_format: str = "webp",
    quality: int = 92,
    sharpen: float = 0.7,
) -> dict:
    rows, cols = parse_layout(layout)
    key = layout_key(rows, cols)
    if not input_path.exists():
        raise GridSplitError(f"input image does not exist: {input_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    extension = "jpg" if output_format == "jpeg" else output_format

    source = Image.open(input_path)
    source.load()
    source = source.convert("RGB")

    panels: list[PanelManifest] = []
    positions = POSITION_NAMES[key]
    for index, (row, col, cell, crop) in enumerate(
        panel_rects(source.width, source.height, rows, cols, safe_margin_ratio),
        start=1,
    ):
        output_name = f"panel_{index:02d}.{extension}"
        save_panel(
            source=source,
            crop=crop,
            output_path=output_dir / output_name,
            target_size=target_size,
            output_format=output_format,
            quality=quality,
            sharpen=sharpen,
        )
        panels.append(
            PanelManifest(
                panelIndex=index,
                row=row,
                col=col,
                position=positions[index - 1],
                cellRect=cell,
                cropRect=crop,
                output=output_name,
            )
        )

    debug_path = output_dir / "debug_grid.jpg"
    draw_debug(source, panels, debug_path, rows, cols)

    manifest = {
        "source": str(input_path),
        "layout": key,
        "sourceSize": {"width": source.width, "height": source.height},
        "targetSize": target_size,
        "safeMarginRatio": safe_margin_ratio,
        "format": output_format,
        "quality": quality,
        "debugImage": debug_path.name,
        "panels": [asdict(panel) for panel in panels],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
