from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont

from backend.app.core.config import get_settings


WIDTH = 1600
HEIGHT = 900
STRUCTURED_KINDS = {"flow", "comparison", "matrix", "classification"}
_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/AssetsV2/com_apple_MobileAsset_Font7/3419fca3821b6019ee74eb8a967ad17dbf54abdd.asset/AssetData/PingFang.ttc",
    "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/53fe5be564086fefc7523ccd0a31200acf92e0e5.asset/AssetData/STHEITI.ttf",
)


def supports_structured_render(plan: dict[str, Any]) -> bool:
    return plan.get("kind") in STRUCTURED_KINDS


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = list(_FONT_CANDIDATES)
    if bold:
        candidates = sorted(candidates, key=lambda item: "Bold" not in item)
    for path in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> float:
    return draw.textlength(text, font=font)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int, max_lines: int = 3) -> list[str]:
    value = str(text).strip()
    if not value:
        return ["—"]
    lines: list[str] = []
    current = ""
    for char in value:
        candidate = current + char
        if current and _text_width(draw, candidate, font) > width:
            lines.append(current)
            current = char
            if len(lines) == max_lines:
                break
        else:
            current = candidate
    if len(lines) < max_lines and current:
        lines.append(current)
    consumed = sum(len(line) for line in lines)
    if consumed < len(value) and lines:
        tail = lines[-1]
        while tail and _text_width(draw, tail + "…", font) > width:
            tail = tail[:-1]
        lines[-1] = tail + "…"
    return lines


def _centered_lines(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    *,
    fill: str = "#1f2933",
    max_lines: int = 3,
) -> None:
    left, top, right, bottom = box
    lines = _wrap(draw, text, font, right - left - 24, max_lines=max_lines)
    line_height = int(getattr(font, "size", 24) * 1.35)
    y = top + max(0, ((bottom - top) - line_height * len(lines)) // 2)
    for line in lines:
        x = left + int(((right - left) - _text_width(draw, line, font)) / 2)
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height


def _reference_bytes(image_ref: str) -> bytes | None:
    if image_ref.startswith("data:") and "," in image_ref:
        return base64.b64decode(image_ref.split(",", 1)[1])
    path = Path(image_ref)
    if not path.is_file():
        file_name = path.name
        storage_dir = Path(get_settings().storage_dir)
        if image_ref.startswith("/api/files/media/"):
            path = storage_dir / "media" / file_name
        elif image_ref.startswith("/api/platforms/wechat-mp/illustration-characters/files/"):
            path = next((storage_dir / "character-images").glob(f"u*/{file_name}"), Path())
    return path.read_bytes() if path.is_file() else None


def _paste_character(canvas: Image.Image, reference_images: list[str] | None) -> bool:
    if not reference_images:
        return False
    content = _reference_bytes(reference_images[0])
    if not content:
        return False
    with Image.open(io.BytesIO(content)) as source:
        character = source.convert("RGBA")
    character.thumbnail((640, 640), Image.Resampling.LANCZOS)
    pixels = character.load()
    for y in range(character.height):
        for x in range(character.width):
            red, green, blue, alpha = pixels[x, y]
            whiteness = min(red, green, blue)
            if whiteness > 245:
                pixels[x, y] = (red, green, blue, 0)
            elif whiteness > 220:
                pixels[x, y] = (red, green, blue, int(alpha * (245 - whiteness) / 25))
    bbox = character.getbbox()
    if bbox:
        character = character.crop(bbox)
    character.thumbnail((230, 190), Image.Resampling.LANCZOS)
    canvas.alpha_composite(character, (WIDTH - character.width - 42, HEIGHT - character.height - 34))
    return True


def _draw_header(draw: ImageDraw.ImageDraw, title: str, subtitle: str) -> None:
    draw.text((62, 42), title, font=_font(40, bold=True), fill="#16212b")
    draw.text((64, 96), subtitle, font=_font(20), fill="#64707c")
    draw.line((62, 132, WIDTH - 62, 132), fill="#d9e0e4", width=2)


def _render_flow(draw: ImageDraw.ImageDraw, plan: dict[str, Any]) -> list[str]:
    nodes = [str(item) for item in plan.get("nodes", [])]
    groups = plan.get("groups", {}) or {}
    _draw_header(draw, "流程关系", "按原文顺序逐项推进，节点不合并、不省略")
    left, right = 66, WIDTH - 66
    gap = 24
    node_width = max(145, min(220, int((right - left - gap * max(len(nodes) - 1, 0)) / max(len(nodes), 1))))
    total_width = node_width * len(nodes) + gap * max(len(nodes) - 1, 0)
    start_x = left + max(0, (right - left - total_width) // 2)
    node_top, node_bottom = 330, 500
    title_font = _font(26, bold=True)
    positions: dict[str, tuple[int, int, int, int]] = {}
    for index, node in enumerate(nodes):
        x = start_x + index * (node_width + gap)
        box = (x, node_top, x + node_width, node_bottom)
        positions[node] = box
        draw.rounded_rectangle(box, radius=22, fill="#ffffff", outline="#263746", width=3)
        draw.ellipse((x + 12, node_top + 12, x + 50, node_top + 50), fill="#e57a2b")
        number = str(index + 1)
        number_font = _font(20, bold=True)
        draw.text((x + 31 - _text_width(draw, number, number_font) / 2, node_top + 18), number, font=number_font, fill="white")
        _centered_lines(draw, (x + 8, node_top + 48, x + node_width - 8, node_bottom - 6), node, title_font, max_lines=3)
        if index < len(nodes) - 1:
            arrow_y = (node_top + node_bottom) // 2
            arrow_start = x + node_width + 4
            arrow_end = arrow_start + gap - 8
            draw.line((arrow_start, arrow_y, arrow_end, arrow_y), fill="#e57a2b", width=5)
            draw.polygon(((arrow_end, arrow_y), (arrow_end - 12, arrow_y - 9), (arrow_end - 12, arrow_y + 9)), fill="#e57a2b")
    group_font = _font(24, bold=True)
    for group, grouped_nodes in groups.items():
        existing = [positions[str(node)] for node in grouped_nodes if str(node) in positions]
        if not existing:
            continue
        group_left, group_right = existing[0][0], existing[-1][2]
        y = node_top - 92
        draw.rounded_rectangle((group_left, y, group_right, y + 54), radius=18, fill="#e8f4f1")
        label = f"{group}组"
        draw.text((group_left + (group_right - group_left - _text_width(draw, label, group_font)) / 2, y + 10), label, font=group_font, fill="#087f73")
        draw.line((group_left + 8, y + 58, group_right - 8, y + 58), fill="#087f73", width=3)
    return nodes


def _render_table(draw: ImageDraw.ImageDraw, plan: dict[str, Any]) -> list[str]:
    columns = [str(item) for item in plan.get("columns", [])]
    rows = list(plan.get("rows", []))
    title = "对比关系" if plan.get("kind") == "comparison" else "结构矩阵"
    _draw_header(draw, title, "同一行横向对照，内容按原始列归属精确呈现")
    table_left, table_right = 62, WIDTH - 280
    table_top, table_bottom = 165, HEIGHT - 58
    label_width = 180
    column_width = int((table_right - table_left - label_width) / max(len(columns), 1))
    row_height = int((table_bottom - table_top) / max(len(rows) + 1, 1))
    header_font = _font(27, bold=True)
    label_font = _font(23, bold=True)
    value_font = _font(21)
    draw.rounded_rectangle((table_left, table_top, table_right, table_bottom), radius=18, fill="#ffffff", outline="#263746", width=3)
    draw.rectangle((table_left, table_top, table_right, table_top + row_height), fill="#e8f4f1")
    draw.line((table_left + label_width, table_top, table_left + label_width, table_bottom), fill="#aebbc4", width=2)
    for index, column in enumerate(columns):
        x0 = table_left + label_width + index * column_width
        if index:
            draw.line((x0, table_top, x0, table_bottom), fill="#aebbc4", width=2)
        _centered_lines(draw, (x0, table_top, x0 + column_width, table_top + row_height), column, header_font, max_lines=2)
    labels: list[str] = []
    for row_index, row in enumerate(rows):
        y0 = table_top + (row_index + 1) * row_height
        draw.line((table_left, y0, table_right, y0), fill="#aebbc4", width=2)
        label = str(row.get("label", ""))
        labels.append(label)
        _centered_lines(draw, (table_left, y0, table_left + label_width, y0 + row_height), label, label_font, max_lines=2)
        values = list(row.get("values", []))
        for column_index in range(len(columns)):
            x0 = table_left + label_width + column_index * column_width
            value = str(values[column_index]) if column_index < len(values) else "—"
            _centered_lines(draw, (x0 + 8, y0 + 4, x0 + column_width - 8, y0 + row_height - 4), value, value_font, max_lines=4)
    relations = plan.get("relations", [])
    if relations:
        relation = relations[0]
        relation_text = f"{relation.get('from', '')} → {relation.get('to', '')}  {relation.get('label', '')}".strip()
        draw.rounded_rectangle((WIDTH - 255, 180, WIDTH - 36, 270), radius=18, fill="#fff1e6")
        _centered_lines(draw, (WIDTH - 247, 184, WIDTH - 44, 266), relation_text, _font(20, bold=True), fill="#a94d13", max_lines=3)
    return columns + labels


def _render_classification(draw: ImageDraw.ImageDraw, plan: dict[str, Any]) -> list[str]:
    items = [list(item) for item in plan.get("items", [])]
    _draw_header(draw, "分类结构", "类别与内容保持一一对应")
    labels: list[str] = []
    top = 170
    row_height = min(120, int(620 / max(len(items), 1)))
    for index, item in enumerate(items):
        label = str(item[0]) if item else ""
        value = "、".join(str(cell) for cell in item[1:])
        labels.append(label)
        y = top + index * (row_height + 12)
        draw.rounded_rectangle((70, y, WIDTH - 300, y + row_height), radius=18, fill="#ffffff", outline="#c6d0d7", width=2)
        draw.rounded_rectangle((70, y, 330, y + row_height), radius=18, fill="#e8f4f1")
        _centered_lines(draw, (82, y + 4, 318, y + row_height - 4), label, _font(24, bold=True), fill="#087f73")
        _centered_lines(draw, (350, y + 4, WIDTH - 320, y + row_height - 4), value, _font(22), max_lines=3)
    return labels


def render_structured_image(
    *,
    plan: dict[str, Any],
    user_id: int,
    reference_images: list[str] | None,
    output_dir: Path,
) -> dict[str, Any]:
    if not supports_structured_render(plan):
        raise ValueError("Visual plan is not supported by the deterministic renderer")
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), "#fbfaf6")
    draw = ImageDraw.Draw(canvas)
    kind = plan.get("kind")
    if kind == "flow":
        rendered_labels = _render_flow(draw, plan)
    elif kind in {"comparison", "matrix"}:
        rendered_labels = _render_table(draw, plan)
    else:
        rendered_labels = _render_classification(draw, plan)
    character_rendered = _paste_character(canvas, reference_images)
    output_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"wechat-mp-u{user_id}-{uuid4().hex}.png"
    path = output_dir / file_name
    canvas.convert("RGB").save(path, format="PNG", optimize=True)
    rendered_cells = [
        str(cell)
        for cell in plan.get("source_cells", [])
        if str(cell).strip()
    ]
    return {
        "file_path": str(path),
        "public_url": f"/api/files/media/{file_name}",
        "model_name": "deterministic-layout-v1",
        "provider_response": {
            "renderer": "pillow",
            "render_kind": kind,
            "rendered_labels": rendered_labels,
            "rendered_cells": rendered_cells,
            "character_rendered": character_rendered,
        },
    }
