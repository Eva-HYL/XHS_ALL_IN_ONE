from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


ANALYSIS_VERSION = "v2"
MAX_SEMANTIC_INPUT_BLOCKS = 24
MAX_BLOCK_CHARS = 500
MAX_TOTAL_INPUT_CHARS = 12000

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_TABLE_DIVIDER_CELL_RE = re.compile(r"^:?-{3,}:?$")
_FLOW_SPLIT_RE = re.compile(r"\s*(?:→|->|⇒|=>|＞)\s*")
_MAPPING_RE = re.compile(r"^\s*[-*+]\s+(.+?)\s*[：:]\s*(.+?)\s*$")
_DIMENSION_RE = re.compile(r"\b\d{2,4}\s*(?:x|×)\s*\d{2,4}\b", re.IGNORECASE)
_MARKDOWN_DECORATION_RE = re.compile(r"[`*_]")


@dataclass(frozen=True)
class ContentBlock:
    source_index: int
    heading_path: tuple[str, ...]
    raw_text: str
    cleaned_text: str
    fingerprint: str


@dataclass(frozen=True)
class VisualCandidate:
    block: ContentBlock
    kind: str
    structure: tuple[tuple[str, ...], ...]
    score: float

    @property
    def source_index(self) -> int:
        return self.block.source_index

    @property
    def heading_path(self) -> tuple[str, ...]:
        return self.block.heading_path

    @property
    def fingerprint(self) -> str:
        return self.block.fingerprint


@dataclass(frozen=True)
class ContentAnalysis:
    blocks: tuple[ContentBlock, ...]
    candidates: tuple[VisualCandidate, ...]
    filtered_blocks: int
    analysis_version: str = ANALYSIS_VERSION

    @property
    def deterministic_candidates(self) -> tuple[VisualCandidate, ...]:
        return tuple(candidate for candidate in self.candidates if candidate.kind != "semantic")

    @property
    def semantic_candidates(self) -> tuple[VisualCandidate, ...]:
        return tuple(candidate for candidate in self.candidates if candidate.kind == "semantic")


def _clean_text(text: str) -> str:
    text = re.sub(r"!?(?:\[[^\]]*\])\([^)]*\)", "", text)
    text = _MARKDOWN_DECORATION_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _new_block(source_index: int, heading_path: tuple[str, ...], lines: list[str]) -> ContentBlock:
    raw_text = "\n".join(lines).strip()
    full_cleaned_text = _clean_text(raw_text)
    fingerprint = hashlib.sha256(full_cleaned_text.encode("utf-8")).hexdigest()
    return ContentBlock(
        source_index=source_index,
        heading_path=heading_path,
        raw_text=raw_text,
        cleaned_text=full_cleaned_text[:MAX_BLOCK_CHARS],
        fingerprint=fingerprint,
    )


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 3


def _parse_blocks(markdown_body: str) -> tuple[ContentBlock, ...]:
    """Split Markdown into source-stable blocks while retaining active headings."""
    lines = markdown_body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[ContentBlock] = []
    heading_stack: list[str] = []
    index = 0
    source_index = 0

    def append_block(block_lines: list[str], path: tuple[str, ...]) -> None:
        nonlocal source_index
        if not any(line.strip() for line in block_lines):
            return
        blocks.append(_new_block(source_index, path, block_lines))
        source_index += 1

    while index < len(lines):
        line = lines[index]
        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            title = _clean_text(heading.group(2))
            heading_stack[level - 1 :] = [title]
            index += 1
            continue
        if not line.strip():
            index += 1
            continue

        path = tuple(heading_stack)
        if line.strip().startswith("```"):
            block_lines = [line]
            index += 1
            while index < len(lines):
                block_lines.append(lines[index])
                if lines[index].strip().startswith("```"):
                    index += 1
                    break
                index += 1
            append_block(block_lines, path)
            continue

        if _is_table_line(line):
            block_lines = [line]
            index += 1
            while index < len(lines):
                current = lines[index]
                if not current.strip():
                    if index + 1 < len(lines) and _is_table_line(lines[index + 1]):
                        index += 1
                        continue
                    break
                if not _is_table_line(current):
                    break
                block_lines.append(current)
                index += 1
            append_block(block_lines, path)
            continue

        block_lines = [line]
        index += 1
        while index < len(lines):
            current = lines[index]
            if not current.strip() or _HEADING_RE.match(current) or _is_table_line(current):
                break
            block_lines.append(current)
            index += 1
        append_block(block_lines, path)

    return tuple(blocks)


def _filter_reason(block: ContentBlock) -> str | None:
    text = block.raw_text.strip()
    lowered = text.lower()
    if not text:
        return "empty"
    if "```" in text:
        return "code"
    if re.search(r"</?(?:details|summary|script|style|meta)\b", lowered):
        return "html"
    if _DIMENSION_RE.search(text) or any(word in text for word in ("提示词", "水印", "封面尺寸", "生成参数")):
        return "metadata"
    return None


def _table_rows(text: str) -> tuple[tuple[str, ...], ...] | None:
    rows: list[tuple[str, ...]] = []
    for line in text.splitlines():
        if not _is_table_line(line):
            return None
        cells = tuple(_clean_text(cell) for cell in line.strip()[1:-1].split("|"))
        if not cells or any(not cell for cell in cells):
            return None
        rows.append(cells)
    if len(rows) < 3 or len(rows[0]) < 2:
        return None
    divider = rows[1]
    if len(divider) != len(rows[0]) or not all(_TABLE_DIVIDER_CELL_RE.fullmatch(cell) for cell in divider):
        return None
    if any(len(row) != len(rows[0]) for row in rows[2:]):
        return None
    return tuple([rows[0], *rows[2:]])


def _extract_structure(block: ContentBlock) -> tuple[str, tuple[tuple[str, ...], ...]] | None:
    table = _table_rows(block.raw_text)
    if table is not None:
        return "table", table

    flow_nodes = [
        _clean_text(node).strip("。；;，,：:")
        for node in _FLOW_SPLIT_RE.split(block.raw_text)
        if _clean_text(node).strip("。；;，,：:")
    ]
    if len(flow_nodes) >= 3 and len(flow_nodes) <= 12 and _FLOW_SPLIT_RE.search(block.raw_text):
        return "flow", (tuple(flow_nodes),)

    mappings: list[tuple[str, ...]] = []
    for line in block.raw_text.splitlines():
        match = _MAPPING_RE.match(line)
        if match is None:
            continue
        key = _clean_text(match.group(1))
        value = _clean_text(match.group(2))
        if key and value:
            mappings.append((key, value))
    if len(mappings) >= 2 and len({mapping[0] for mapping in mappings}) == len(mappings):
        return "classification", tuple(mappings)
    return None


def _semantic_score(block: ContentBlock) -> float:
    text = block.cleaned_text
    if len(text) < 16 or text.startswith("|"):
        return 0.0
    if any(phrase in text for phrase in ("欢迎关注", "点赞", "转发", "下一篇再见", "感谢阅读")):
        return 0.0

    keywords = (
        "问题", "方法", "原因", "结果", "步骤", "原则", "风险", "对比", "核心", "关键",
        "策略", "实践", "案例", "结论", "目标", "选择", "变化", "影响", "冲突", "解决",
    )
    keyword_count = sum(keyword in text for keyword in keywords)
    score = 0.20 + min(len(text) / 240, 0.30) + min(keyword_count * 0.12, 0.36)
    if re.search(r"\d+(?:\.\d+)?(?:%|个|步|种|项|倍)", text):
        score += 0.10
    return round(score, 4) if score >= 0.50 else 0.0


def _char_bigrams(text: str) -> frozenset[str]:
    normalized = re.sub(r"\s+", "", text)
    if len(normalized) < 2:
        return frozenset()
    return frozenset(normalized[index : index + 2] for index in range(len(normalized) - 1))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _deduplicate(candidates: tuple[VisualCandidate, ...]) -> tuple[VisualCandidate, ...]:
    retained: list[VisualCandidate] = []
    for candidate in sorted(candidates, key=lambda item: (-item.score, item.source_index)):
        bigrams = _char_bigrams(candidate.block.cleaned_text)
        if any(_jaccard(bigrams, _char_bigrams(existing.block.cleaned_text)) >= 0.82 for existing in retained):
            continue
        retained.append(candidate)
    return tuple(retained)


def analyze_content(markdown_body: str) -> ContentAnalysis:
    blocks = _parse_blocks(markdown_body)
    filtered_blocks = 0
    deterministic: list[VisualCandidate] = []
    semantic: list[VisualCandidate] = []
    for block in blocks:
        if _filter_reason(block) is not None:
            filtered_blocks += 1
            continue
        structure = _extract_structure(block)
        if structure is not None:
            kind, values = structure
            score = {"flow": 1.0, "table": 0.95, "classification": 0.90}[kind]
            deterministic.append(VisualCandidate(block, kind, values, score))
            continue
        score = _semantic_score(block)
        if score:
            semantic.append(VisualCandidate(block, "semantic", (), score))

    selected_semantic: list[VisualCandidate] = []
    input_chars = 0
    for candidate in sorted(semantic, key=lambda item: (-item.score, item.source_index)):
        if len(selected_semantic) >= MAX_SEMANTIC_INPUT_BLOCKS:
            break
        next_size = len(candidate.block.cleaned_text)
        if input_chars + next_size > MAX_TOTAL_INPUT_CHARS:
            continue
        selected_semantic.append(candidate)
        input_chars += next_size

    candidates = _deduplicate(tuple(deterministic + selected_semantic))
    candidates = tuple(sorted(candidates, key=lambda item: (-item.score, item.source_index)))
    return ContentAnalysis(blocks=blocks, candidates=candidates, filtered_blocks=filtered_blocks)
