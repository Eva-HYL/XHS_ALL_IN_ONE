from __future__ import annotations

from html import escape
import re


_ORDERED_ITEM_RE = re.compile(r"^\d+\.\s+(.+)$")
_UNORDERED_ITEM_RE = re.compile(r"^[-*+]\s+(.+)$")
_STYLE_IDS = {"classic", "study_green", "warm_orange", "minimal_gray"}


def get_wechat_layout_styles() -> list[dict[str, str]]:
    return [
        {
            "id": "classic",
            "name": "经典简洁",
            "description": "保留当前草稿结构，只做基础正文排版。",
        },
        {
            "id": "study_green",
            "name": "青绿备考",
            "description": "青绿色小标题、橙色章节胶囊、浅绿口诀框，适合知识型公众号。",
        },
        {
            "id": "warm_orange",
            "name": "暖橙杂志",
            "description": "暖橙强调和卡片分隔，适合轻松叙事与复盘文章。",
        },
        {
            "id": "minimal_gray",
            "name": "极简灰阶",
            "description": "克制的灰阶标题与宽留白，适合正式长文。",
        },
    ]


def normalize_wechat_layout_style(layout_style: str | None) -> str:
    style = (layout_style or "classic").strip()
    if style not in _STYLE_IDS:
        raise ValueError(f"Unsupported WeChat MP layout style: {style}")
    return style


def _image_html(placeholder: dict) -> str:
    url = escape(str(placeholder.get("url", "")), quote=True)
    alt = escape(str(placeholder.get("alt", "")), quote=True)
    if not url:
        return ""
    return f'<img src="{url}" alt="{alt}" style="display:block;max-width:100%;height:auto;margin:20px auto;" />'


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_table_separator(line: str) -> bool:
    cells = _split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _table_html(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(
        f'<th style="border:1px solid #d9d9d9;padding:8px 10px;text-align:left;background:#f6f6f6;">{escape(header)}</th>'
        for header in headers
    )
    body_rows = []
    for row in rows:
        cells = "".join(
            f'<td style="border:1px solid #d9d9d9;padding:8px 10px;">{escape(cell)}</td>'
            for cell in row
        )
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        '<table style="width:100%;border-collapse:collapse;margin:16px 0;font-size:15px;line-height:1.65;">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
    )


def render_wechat_html(markdown_body: str, image_placeholders: list[dict]) -> str:
    """Render the limited article markdown subset accepted by WeChat drafts locally."""
    image_by_marker = {
        str(item.get("placeholder", "")): _image_html(item)
        for item in image_placeholders
        if item.get("placeholder")
    }
    blocks: list[str] = []
    list_items: list[str] = []
    list_tag: str | None = None

    def flush_list() -> None:
        nonlocal list_items, list_tag
        if list_tag:
            blocks.append(f'<{list_tag} style="padding-left:1.5em;margin:16px 0;">{"".join(list_items)}</{list_tag}>')
        list_items = []
        list_tag = None

    lines = markdown_body.splitlines()
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        line = raw_line.strip()
        if not line:
            flush_list()
            index += 1
            continue
        if line in image_by_marker:
            flush_list()
            blocks.append(image_by_marker[line])
            index += 1
            continue
        if "|" in line and index + 1 < len(lines) and _is_table_separator(lines[index + 1].strip()):
            flush_list()
            headers = _split_table_row(line)
            rows: list[list[str]] = []
            index += 2
            while index < len(lines) and "|" in lines[index].strip():
                rows.append(_split_table_row(lines[index]))
                index += 1
            blocks.append(_table_html(headers, rows))
            continue
        ordered = _ORDERED_ITEM_RE.match(line)
        unordered = _UNORDERED_ITEM_RE.match(line)
        if ordered or unordered:
            tag = "ol" if ordered else "ul"
            if list_tag and list_tag != tag:
                flush_list()
            list_tag = tag
            list_items.append(f'<li style="margin:8px 0;">{escape((ordered or unordered).group(1))}</li>')
            index += 1
            continue
        flush_list()
        if line.startswith("### "):
            blocks.append(f"<h3>{escape(line[4:])}</h3>")
        elif line.startswith("## "):
            blocks.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("# "):
            blocks.append(f"<h1>{escape(line[2:])}</h1>")
        elif line.startswith("> "):
            blocks.append(f'<blockquote style="margin:16px 0;padding:12px 16px;border-left:4px solid #07c160;color:#576b95;">{escape(line[2:])}</blockquote>')
        else:
            blocks.append(f'<p style="margin:16px 0;line-height:1.75;color:#222;">{escape(line)}</p>')
        index += 1
    flush_list()
    return "\n".join(block for block in blocks if block)


def layout_style_uses_hero(layout_style: str | None) -> bool:
    return normalize_wechat_layout_style(layout_style) in {"study_green", "warm_orange"}


def _style_images(html_body: str) -> str:
    def replace(match: re.Match[str]) -> str:
        tag = match.group(0)
        if "style=" in tag:
            tag = re.sub(r'\sstyle="[^"]*"', "", tag)
        return tag.rstrip(" />") + ' style="display:block;width:100%;max-width:560px;height:auto;margin:24px auto;border-radius:10px;" />'

    return re.sub(r"<img\b[^>]*>", replace, html_body)


def _style_tables(html_body: str) -> str:
    html_body = re.sub(
        r"<table\b[^>]*>",
        '<table style="width:100%;border-collapse:collapse;margin:18px 0 10px;font-size:15px;line-height:1.65;color:#222;">',
        html_body,
    )
    html_body = re.sub(r"<th\b[^>]*>", '<th style="border:1px solid #d7ddd9;padding:8px 10px;text-align:left;background:#f4f7f5;">', html_body)
    return re.sub(r"<td\b[^>]*>", '<td style="border:1px solid #d7ddd9;padding:8px 10px;">', html_body)


def _style_blocks(html_body: str, style: str) -> str:
    palettes = {
        "study_green": {"accent": "#008575", "soft": "#e5f4ef", "pill": "#df7d2b", "text": "#252525"},
        "warm_orange": {"accent": "#c56a1d", "soft": "#fff3e6", "pill": "#d8792a", "text": "#29231e"},
        "minimal_gray": {"accent": "#333333", "soft": "#f4f4f4", "pill": "#4a4a4a", "text": "#242424"},
    }
    palette = palettes[style]
    html_body = re.sub(
        r"<h1>(.*?)</h1>",
        lambda m: f'<h1 style="margin:12px 0 22px;font-size:24px;line-height:1.35;color:{palette["text"]};font-weight:800;">{m.group(1)}</h1>',
        html_body,
        flags=re.S,
    )
    html_body = re.sub(
        r"<h2>(.*?)</h2>",
        lambda m: (
            f'<p style="margin:30px 0 12px;"><span style="display:inline-block;padding:6px 14px;'
            f'border-radius:999px;background:{palette["pill"]};color:#fff;font-size:14px;font-weight:700;">'
            f'章节复习 · {m.group(1)}</span></p>'
        ),
        html_body,
        flags=re.S,
    )
    html_body = re.sub(
        r"<h3>(.*?)</h3>",
        lambda m: f'<h3 style="margin:24px 0 10px;font-size:18px;line-height:1.5;color:{palette["accent"]};font-weight:800;">{m.group(1)}</h3>',
        html_body,
        flags=re.S,
    )
    html_body = re.sub(
        r'<p\b[^>]*>(.*?)</p>',
        lambda m: f'<p style="margin:12px 0;line-height:1.85;color:{palette["text"]};font-size:15px;">{m.group(1)}</p>',
        html_body,
        flags=re.S,
    )
    html_body = re.sub(
        r'<blockquote\b[^>]*>(.*?)</blockquote>',
        lambda m: (
            f'<section style="margin:14px 0;padding:10px 12px;background:{palette["soft"]};'
            f'border-radius:6px;color:{palette["text"]};font-size:14px;line-height:1.75;">💡 {m.group(1)}</section>'
        ),
        html_body,
        flags=re.S,
    )
    html_body = re.sub(r"<ul\b[^>]*>", '<ul style="padding-left:1.3em;margin:12px 0;line-height:1.8;">', html_body)
    html_body = re.sub(r"<ol\b[^>]*>", '<ol style="padding-left:1.3em;margin:12px 0;line-height:1.8;">', html_body)
    return _style_tables(_style_images(html_body))


def apply_wechat_layout_style(html_body: str, layout_style: str | None = "classic", hero_image_url: str | None = None) -> str:
    style = normalize_wechat_layout_style(layout_style)
    if style == "classic":
        return html_body

    hero = ""
    if hero_image_url:
        hero_url = escape(hero_image_url, quote=True)
        hero = (
            f'<p style="margin:0 0 24px;"><img src="{hero_url}" alt="封面图" '
            'style="display:block;width:100%;max-width:620px;height:auto;margin:0 auto;border-radius:18px;" /></p>'
        )
    content = _style_blocks(html_body, style)
    return (
        '<section style="max-width:677px;margin:0 auto;padding:8px 0 24px;'
        'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;color:#222;">'
        f"{hero}{content}</section>"
    )
