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


def _normalize_model_markdown(markdown_body: str) -> str:
    body = markdown_body.strip()
    if body.startswith("【") and body.endswith("】"):
        body = body[1:-1].strip()
    return body


def _split_table_row(line: str) -> list[str]:
    cleaned = line.strip().strip("【】").strip()
    return [cell.strip().strip("【】").strip() for cell in cleaned.strip("|").split("|")]


def _is_table_separator(line: str) -> bool:
    cells = _split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _next_nonempty_line_index(lines: list[str], start_index: int) -> int | None:
    index = start_index
    while index < len(lines):
        if lines[index].strip():
            return index
        index += 1
    return None


def _table_html(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(
        f'<th style="border:1px solid #d9d9d9;padding:8px 10px;text-align:left;background:#f6f6f6;">{_inline_markdown(header)}</th>'
        for header in headers
    )
    body_rows = []
    for row in rows:
        cells = "".join(
            f'<td style="border:1px solid #d9d9d9;padding:8px 10px;">{_inline_markdown(cell)}</td>'
            for cell in row
        )
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        '<table style="width:100%;border-collapse:collapse;margin:16px 0;font-size:15px;line-height:1.65;">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
    )


def _render_inline_segment(text: str) -> str:
    escaped = escape(text)
    escaped = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        lambda m: (
            f'<a href="{escape(m.group(2), quote=True)}" target="_blank" '
            f'style="color:#576b95;text-decoration:none;">{m.group(1)}</a>'
        ),
        escaped,
    )
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"~~(.+?)~~", r"<del>\1</del>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", escaped)
    return re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<em>\1</em>", escaped)


def _inline_markdown(text: str) -> str:
    parts = re.split(r"(`[^`]+`)", text)
    rendered: list[str] = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) >= 2:
            rendered.append(
                '<code style="padding:2px 5px;border-radius:4px;background:#f4f4f4;'
                f'font-size:90%;font-family:Menlo,Consolas,monospace;">{escape(part[1:-1])}</code>'
            )
        else:
            rendered.append(_render_inline_segment(part))
    return "".join(rendered)


def _paragraph_html(text: str) -> str:
    body = "<br />".join(_inline_markdown(line) for line in text.splitlines())
    return f'<p style="margin:16px 0;line-height:1.75;color:#222;">{body}</p>'


def _code_block_html(code: str, language: str = "") -> str:
    label = f'<span style="display:block;margin-bottom:8px;color:#7a7a7a;font-size:12px;">{escape(language)}</span>' if language else ""
    return (
        '<pre style="margin:18px 0;padding:14px 16px;border-radius:8px;'
        'background:#f6f8fa;overflow:auto;line-height:1.7;font-size:13px;">'
        f'{label}<code style="font-family:Menlo,Consolas,monospace;color:#24292f;">{escape(code)}</code></pre>'
    )


def _answer_card_html(summary: str, body_lines: list[str]) -> str:
    body = "\n".join(line.strip() for line in body_lines).strip()
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", body):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if paragraph.startswith(("- ", "* ", "+ ")):
            items = [
                f'<li style="margin:6px 0;">{_inline_markdown(item.strip()[2:].strip())}</li>'
                for item in paragraph.splitlines()
                if item.strip()
            ]
            paragraphs.append(f'<ul style="padding-left:1.3em;margin:10px 0;line-height:1.8;">{"".join(items)}</ul>')
        else:
            paragraphs.append(f'<p style="margin:10px 0;line-height:1.8;color:#25322f;">{_inline_markdown(paragraph)}</p>')
    title = _inline_markdown(summary or "点击查看答案与解析")
    return (
        '<section style="margin:18px 0;padding:14px 16px;border-left:4px solid #008575;'
        'background:#f2faf7;border-radius:8px;">'
        f'<p style="margin:0 0 10px;color:#008575;font-weight:700;">{title}</p>'
        f'{"".join(paragraphs)}</section>'
    )


def _parse_details_block(lines: list[str], start_index: int) -> tuple[str, int]:
    summary = "点击查看答案与解析"
    body_lines: list[str] = []
    index = start_index + 1
    while index < len(lines):
        line = lines[index].strip()
        if re.fullmatch(r"</details>", line, flags=re.IGNORECASE):
            return _answer_card_html(summary, body_lines), index + 1
        summary_match = re.fullmatch(r"<summary>(.*?)</summary>", line, flags=re.IGNORECASE)
        if summary_match:
            summary = summary_match.group(1).strip()
        elif line:
            body_lines.append(line)
        else:
            body_lines.append("")
        index += 1
    return _answer_card_html(summary, body_lines), index


def render_wechat_html(markdown_body: str, image_placeholders: list[dict]) -> str:
    """Render the limited article markdown subset accepted by WeChat drafts locally."""
    markdown_body = _normalize_model_markdown(markdown_body)
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

    def is_block_start(candidate: str) -> bool:
        if not candidate:
            return True
        if candidate in image_by_marker:
            return True
        if re.fullmatch(r"<details>", candidate, flags=re.IGNORECASE):
            return True
        if candidate.startswith(("```", "# ", "## ", "### ", "> ")):
            return True
        if re.fullmatch(r"-{3,}", candidate):
            return True
        if _ORDERED_ITEM_RE.match(candidate) or _UNORDERED_ITEM_RE.match(candidate):
            return True
        separator = _next_nonempty_line_index(lines, index + 1) if "|" in candidate else None
        return separator is not None and _is_table_separator(lines[separator].strip())

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
        if re.fullmatch(r"<details>", line, flags=re.IGNORECASE):
            flush_list()
            card_html, index = _parse_details_block(lines, index)
            blocks.append(card_html)
            continue
        if line.startswith("```"):
            flush_list()
            language = line[3:].strip()
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            blocks.append(_code_block_html("\n".join(code_lines), language))
            continue
        if re.fullmatch(r"-{3,}", line):
            flush_list()
            blocks.append('<hr style="border:none;border-top:1px solid #e8e8e8;margin:24px 0;" />')
            index += 1
            continue
        separator_index = _next_nonempty_line_index(lines, index + 1) if "|" in line else None
        if separator_index is not None and _is_table_separator(lines[separator_index].strip()):
            flush_list()
            headers = _split_table_row(line)
            rows: list[list[str]] = []
            index = separator_index + 1
            while index < len(lines):
                table_line = lines[index].strip()
                if not table_line:
                    index += 1
                    continue
                if "|" not in table_line:
                    break
                rows.append(_split_table_row(table_line))
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
            list_items.append(f'<li style="margin:8px 0;">{_inline_markdown((ordered or unordered).group(1))}</li>')
            index += 1
            continue
        flush_list()
        if line.startswith("### "):
            blocks.append(f"<h3>{_inline_markdown(line[4:])}</h3>")
        elif line.startswith("## "):
            blocks.append(f"<h2>{_inline_markdown(line[3:])}</h2>")
        elif line.startswith("# "):
            blocks.append(f"<h1>{_inline_markdown(line[2:])}</h1>")
        elif line.startswith("> "):
            quote_lines = [line[2:].strip()]
            index += 1
            while index < len(lines) and lines[index].strip().startswith("> "):
                quote_lines.append(lines[index].strip()[2:].strip())
                index += 1
            blocks.append(
                '<blockquote style="margin:16px 0;padding:12px 16px;border-left:4px solid #07c160;color:#576b95;">'
                f'{"<br />".join(_inline_markdown(item) for item in quote_lines)}</blockquote>'
            )
            continue
        else:
            paragraph_lines = [line]
            index += 1
            while index < len(lines):
                next_line = lines[index].strip()
                if is_block_start(next_line):
                    break
                paragraph_lines.append(next_line)
                index += 1
            blocks.append(_paragraph_html("\n".join(paragraph_lines)))
            continue
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


def _upgrade_escaped_details(html_body: str) -> str:
    pattern = re.compile(
        r'<p\b[^>]*>&lt;details&gt;</p>\s*'
        r'<p\b[^>]*>&lt;summary&gt;(.*?)&lt;/summary&gt;</p>\s*'
        r'(.*?)'
        r'<p\b[^>]*>&lt;/details&gt;</p>',
        flags=re.S | re.I,
    )

    def replace(match: re.Match[str]) -> str:
        body_text = re.sub(r"<br\s*/?>", "\n", match.group(2), flags=re.I)
        body_text = re.sub(r"</p>\s*<p\b[^>]*>", "\n\n", body_text, flags=re.I)
        body_text = re.sub(r"<[^>]+>", "", body_text)
        return _answer_card_html(match.group(1).strip(), body_text.splitlines())

    return pattern.sub(replace, html_body)


def _upgrade_markdown_leftovers(html_body: str) -> str:
    def paragraph_heading(match: re.Match[str]) -> str:
        level = len(match.group(1))
        tag = f"h{level}"
        return f"<{tag}>{_inline_markdown(match.group(2).strip())}</{tag}>"

    html_body = re.sub(
        r'<p\b[^>]*>\s*(#{1,3})\s+(.+?)\s*</p>',
        paragraph_heading,
        html_body,
        flags=re.S,
    )
    html_body = re.sub(
        r'<p\b[^>]*>\s*-{3,}\s*</p>',
        '<hr style="border:none;border-top:1px solid #e8e8e8;margin:24px 0;" />',
        html_body,
        flags=re.S,
    )

    def inline_container(match: re.Match[str]) -> str:
        tag = match.group(1)
        attrs = match.group(2)
        body = match.group(3)
        return f"<{tag}{attrs}>{_inline_markdown(body)}</{tag}>"

    return re.sub(
        r"<(li|th|td)(\b[^>]*)>([^<]*\*\*[^<]*?)</\1>",
        inline_container,
        html_body,
        flags=re.S,
    )


def apply_wechat_layout_style(html_body: str, layout_style: str | None = "classic", hero_image_url: str | None = None) -> str:
    style = normalize_wechat_layout_style(layout_style)
    html_body = _upgrade_escaped_details(html_body)
    html_body = _upgrade_markdown_leftovers(html_body)
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
