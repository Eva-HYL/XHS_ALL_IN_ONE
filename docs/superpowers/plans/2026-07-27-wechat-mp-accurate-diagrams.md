# WeChat MP Accurate Diagrams Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate relevant text-free cover/concept images and deterministic, accurate study diagrams.

**Architecture:** Parse marked article sections into a small diagram specification, render it to SVG, and persist it through the existing asset path. Keep the image provider for concept/cover scenes, but move character metadata out of the visual prompt and obtain a title-aware cover scene from the text model.

**Tech Stack:** FastAPI, SQLAlchemy, SVG strings, React/TypeScript, pytest.

## Global Constraints

- Never ask an image model to render factual Chinese labels.
- Do not send aspect ratio, percentages, prompt fragments, or character setup as visible image content.
- Preserve existing asset, cost, ownership, draft invalidation, and queue contracts.

### Task 1: Diagram Specification and SVG Renderer

**Files:**
- Create: `backend/app/services/wechat_mp_diagram_service.py`
- Modify: `tests/backend/test_wechat_mp.py`

- [ ] Write failing tests for parsing arrows and markdown tables into exact ordered labels, then run the focused pytest selection.
- [ ] Implement `parse_section_diagram(section_summary: str, source_excerpt: str) -> dict | None` and `render_section_diagram_svg(spec: dict) -> str` with escaped text, arrows, cards, and no model-created labels.
- [ ] Run focused tests and commit `feat: render accurate wechat diagrams`.

### Task 2: Route Diagram Assets Through Existing Generation

**Files:**
- Modify: `backend/app/services/wechat_mp_image_service.py`
- Modify: `tests/backend/test_wechat_mp.py`

- [ ] Write a failing generation test proving a diagram prompt creates an SVG asset without calling `_call_image_model` and backfills the article placeholder.
- [ ] Dispatch parseable diagram sections to the renderer, persist the SVG in media storage, attach `provider_response={"generation_mode":"structured_diagram"}`, and skip image-model usage recording.
- [ ] Run the WeChat test module and commit `feat: generate deterministic wechat diagram assets`.

### Task 3: Title-Aware Text-Free Cover Prompts

**Files:**
- Modify: `backend/app/services/wechat_mp_image_prompt_service.py`
- Modify: `backend/app/services/wechat_mp_image_service.py`
- Modify: `backend/app/services/wechat_mp_writer_service.py`
- Modify: `tests/backend/test_wechat_mp.py`

- [ ] Write failing tests that a cover prompt prioritizes the title/brief scene, bans character setup text, and supplies a detailed visual cover brief from article writing.
- [ ] Add a dedicated cover prompt contract and cover-brief requirement: one topic-specific action, 1-3 related objects, cat as a secondary assistant, no visible text or unrelated props.
- [ ] Use the contract when generating covers, record any text-model cover-prompt usage, and run the WeChat test module.
- [ ] Commit `fix: make wechat covers topic-driven`.

### Task 4: Writer Status and Verification

**Files:**
- Modify: `frontend/src/pages/platforms/wechat-mp/writer-page.tsx`
- Modify: `tests/backend/test_wechat_mp.py`

- [ ] Add explicit `准确图解` versus `插画` status to each prompt card and a note that structured labels are system-rendered.
- [ ] Run backend tests and `npm run build`.
- [ ] Commit `feat: identify accurate diagram generation mode`.
