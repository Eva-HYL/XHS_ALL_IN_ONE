# WeChat MP Accurate Diagram Generation

## Goal

Make generated WeChat article images useful as study material. Ordinary concept illustrations remain AI-generated. Flowcharts, comparison tables, and classification structures render their factual labels deterministically so that model-generated image text cannot introduce missing, duplicated, or unrelated content.

## Scope

- Keep the existing article, prompt, asset, cost, and queue APIs.
- Preserve existing generated assets as history; do not overwrite or charge for them automatically.
- Apply the new behavior only to newly generated or manually regenerated images.
- Keep the selected character as a supporting visual element without allowing it to cover diagram content.

## Generation Modes

### Concept illustration

Sections without a diagram marker use the image model. The final prompt must require the supplied concept only, hand-drawn style, no visible text, no metadata, no watermark request, no extra objects, and no additional labels. The API `size` field controls the aspect ratio; ratio words are not sent as visual content.

### Structured diagram

Sections marked as `流程图`, `对比表/分类卡片`, or `分类结构图` do not ask the image model to render labels. The system parses the source section into an ordered diagram specification and renders the labels, arrows, cards, and table cells itself. The visual layer is a restrained hand-drawn SVG with the selected character placed only in the margin. Only text extracted from the article is rendered; no model-created labels are accepted.

If a section cannot be parsed into a valid diagram specification, it falls back to a text-free concept illustration rather than making a misleading diagram.

## Data Flow

1. The shotlist keeps its current diagram marker and source excerpt.
2. Prompt generation chooses `concept` or `structured_diagram` from the marker.
3. Image generation dispatches structured diagrams to the deterministic SVG renderer and other sections to the image provider.
4. Both paths save a normal `WechatMpAsset`, backfill the article placeholder, update article status, invalidate stale drafts, and record cost. The deterministic renderer records zero image-model cost.
5. The existing single-image queue and future one-click queue operate unchanged because both paths return the same asset response.

## Quality Rules

- No visible aspect ratio, percentage, prompt fragment, title, watermark request, or unrelated text.
- Structured diagrams preserve the source order and exact labels.
- Concept illustrations use no text at all.
- The character never stands upright, wears clothing, covers labels, or adds unrelated props.
- A diagram renderer error never silently produces a malformed factual diagram; it becomes a text-free concept illustration and reports the fallback in asset metadata.

## UI

Each prompt card displays its mode: `插画` or `准确图解`. Structured outputs retain the existing preview, regeneration button, asset storage, and article placement. A small note explains that labels are system-rendered for accuracy.

## Tests

- A flow source creates an SVG asset with ordered, exact labels and arrows.
- A markdown table creates cards or a table with exact headers and cells.
- Concept prompts contain no visible-text or metadata instructions.
- Generated assets keep the current ownership, placeholder backfill, draft invalidation, usage-record, and queue contracts.
- Renderer parse failure falls back to text-free concept generation and captures the fallback metadata.
