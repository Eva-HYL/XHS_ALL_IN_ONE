# WeChat Structured Card Style Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace generic deterministic diagram headers and grid tables with article-only knowledge cards matching the approved reference.

**Architecture:** Keep `visual_plan` and the deterministic Pillow pipeline unchanged. Refactor only rendering functions so layout chrome is removed while exact source cells remain the sole text source.

**Tech Stack:** Python 3.11, Pillow, pytest, Docker, SQLite.

## Global Constraints

- Never call the image provider for `flow`, `comparison`, `matrix`, or `classification` plans.
- Never render template-owned titles or explanatory copy.
- Preserve exact source-cell mapping and one confirmed character at the lower-right edge.

---

### Task 1: Lock the article-only card contract

**Files:**
- Modify: `tests/backend/test_wechat_mp.py`
- Modify: `backend/app/services/wechat_mp_structured_image_service.py`

**Interfaces:**
- Consumes: `render_structured_image(plan, user_id, reference_images, output_dir)`.
- Produces: `provider_response["template_text"] == []` and unchanged `rendered_cells`.

- [ ] **Step 1: Write failing metadata and renderer tests**

Add assertions that comparison, matrix, and flow outputs contain no template title/subtitle and retain exact source cells.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest -q tests/backend/test_wechat_mp.py -k 'structured_visual'`

- [ ] **Step 3: Replace header/grid helpers with card layout helpers**

Remove `_draw_header`. Render comparison headers from `plan["columns"]`, matrix rows from `plan["rows"]`, and flow groups from `plan["groups"]` only.

- [ ] **Step 4: Run focused tests and verify pass**

Run the command from Step 2 and expect all selected tests to pass.

### Task 2: Production visual validation

**Files:**
- Verify: `backend/app/services/wechat_mp_structured_image_service.py`

**Interfaces:**
- Consumes: article 14 prompts 90-94.
- Produces: new `deterministic-layout-v1` assets embedded in article 14.

- [ ] **Step 1: Run backend regression and frontend build**

Run the existing visual-plan/ignore/structured-image tests and `npm run build`.

- [ ] **Step 2: Deploy the branch to Atlas**

Fast-forward from `eva-fork/codex/wechat-shotlist-atlas-integration` and rebuild `spider-xhs`.

- [ ] **Step 3: Regenerate prompts 90-94 without image-model usage**

Record `image_gen` count before and after; the counts must match.

- [ ] **Step 4: Inspect all five production PNGs**

Verify no generic headings, exact labels, no content overlap, and one character maximum.

