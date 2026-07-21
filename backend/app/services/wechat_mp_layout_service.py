from __future__ import annotations

from html import escape
import re


_ORDERED_ITEM_RE = re.compile(r"^\d+\.\s+(.+)$")
_UNORDERED_ITEM_RE = re.compile(r"^[-*+]\s+(.+)$")


def _image_html(placeholder: dict) -> str:
    url = escape(str(placeholder.get("url", "")), quote=True)
    alt = escape(str(placeholder.get("alt", "")), quote=True)
    if not url:
        return ""
    return f'<img src="{url}" alt="{alt}" style="display:block;max-width:100%;height:auto;margin:20px auto;" />'


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

    for raw_line in markdown_body.splitlines():
        line = raw_line.strip()
        if not line:
            flush_list()
            continue
        if line in image_by_marker:
            flush_list()
            blocks.append(image_by_marker[line])
            continue
        ordered = _ORDERED_ITEM_RE.match(line)
        unordered = _UNORDERED_ITEM_RE.match(line)
        if ordered or unordered:
            tag = "ol" if ordered else "ul"
            if list_tag and list_tag != tag:
                flush_list()
            list_tag = tag
            list_items.append(f'<li style="margin:8px 0;">{escape((ordered or unordered).group(1))}</li>')
            continue
        flush_list()
        if line.startswith("## "):
            blocks.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("# "):
            blocks.append(f"<h1>{escape(line[2:])}</h1>")
        elif line.startswith("> "):
            blocks.append(f'<blockquote style="margin:16px 0;padding:12px 16px;border-left:4px solid #07c160;color:#576b95;">{escape(line[2:])}</blockquote>')
        else:
            blocks.append(f'<p style="margin:16px 0;line-height:1.75;color:#222;">{escape(line)}</p>')
    flush_list()
    return "\n".join(block for block in blocks if block)
