# WeChat MP Prompt Ignore And Visual Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist user-level prompt ignore preferences and compile structural article content into validated visual plans before image generation.

**Architecture:** Store tenant-scoped ignore rules and filter candidates before model calls. Parse Markdown structures into typed visual plans, compile image prompts from those plans, and block image generation when source coverage, ordering, relations, or character-count constraints fail.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, SQLAlchemy 2, Alembic, React, TypeScript, Ant Design, pytest.

## Global Constraints

- Scope is only the WeChat MP writer; Xiaohongshu behavior must not change.
- Ignore rules are scoped by `user_id` and default to future similar WeChat MP articles.
- Similarity filtering runs before any text-model call.
- Historical generated assets and usage rows are retained after ignoring a prompt.
- Markdown separators are syntax, never visual content.
- Structured plans preserve exact cells, node order, group membership, and directed relations.
- A generated image may contain at most one confirmed character and the knowledge structure remains primary.
- Every production change follows RED-GREEN-REFACTOR.

### Task 1: Persistence And Contracts

**Files:**
- Create: `backend/alembic/versions/<revision>_add_wechat_prompt_ignore_rules.py`
- Modify: `backend/app/models/wechat_mp.py`
- Modify: `backend/app/schemas/wechat_mp.py`
- Modify: `frontend/src/types/index.ts`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:** Add `WechatMpPromptIgnoreRule`; add `ignored` to prompt status; add `visual_plan` and `quality_report` JSON fields to prompts; expose ignore/restore/rule schemas.

- [ ] Write model/schema tests for tenant ownership, JSON defaults, and `ignored` serialization; run them and confirm RED.
- [ ] Add ORM and Alembic columns/table with non-null server defaults; run migration-head checks.
- [ ] Add matching Pydantic and TypeScript contracts; rerun targeted tests and confirm GREEN.
- [ ] Commit `feat: persist wechat prompt ignore rules`.

### Task 2: Similarity Filter And Ignore Lifecycle

**Files:**
- Create: `backend/app/services/wechat_mp_prompt_ignore_service.py`
- Modify: `backend/app/services/wechat_mp_image_prompt_service.py`
- Modify: `backend/app/api/platforms/wechat_mp/articles.py`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:** `build_concept_signature(candidate)`, `filter_ignored_candidates(...)`, `ignore_prompt(...)`, `restore_prompt(...)`.

- [ ] Write failing tests for exact match, `0.78` concept containment, conservative non-match, cross-user isolation, pre-model filtering, placeholder removal, asset retention, and restore.
- [ ] Confirm tests fail for missing service and endpoints.
- [ ] Implement normalized concept tokens and relation edges; query only active rules for the current user.
- [ ] Implement ignore/restore endpoints and preserve asset rows/files and usage rows.
- [ ] Run lifecycle and token-call tests; commit `feat: skip ignored wechat prompt concepts`.

### Task 3: Typed Visual Plans

**Files:**
- Create: `backend/app/services/wechat_mp_visual_plan_service.py`
- Modify: `backend/app/services/wechat_mp_content_analysis_service.py`
- Modify: `backend/app/services/wechat_mp_image_prompt_service.py`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:** Typed `VisualPlan`; `build_visual_plan(candidate) -> dict`; `validate_visual_plan(candidate, plan) -> QualityReport`; `compile_visual_prompt(plan, character) -> str`.

- [ ] Write failing tests for pipe tables without outer pipes, separator removal, comparison relations, grouped ordered flows, source-cell coverage, and single-character contract.
- [ ] Confirm RED with Article 14 #90-#93 fixtures.
- [ ] Implement tolerant table parsing and typed plan builders for flow/comparison/matrix/classification/semantic.
- [ ] Implement deterministic validation and prompt compilation; reject invalid plans before image calls.
- [ ] Run structural regressions and commit `feat: compile validated wechat visual plans`.

### Task 4: Frontend Ignore And Planning UI

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/pages/platforms/wechat-mp/writer-page.tsx`
- Modify: `frontend/src/types/index.ts`

**Interfaces:** API helpers for ignore, restore, list/update/delete rules; writer cards display visual plans and ignored state.

- [ ] Add source-level frontend assertions for the new actions and confirm RED.
- [ ] Add “只忽略本条” and default “以后忽略类似内容” actions; remove ignored cards from the image queue.
- [ ] Add collapsed ignored list, restore action, and rule-management drawer.
- [ ] Render visual-plan rows, relations, and preflight quality checks beside the editable prompt.
- [ ] Run frontend build and commit `feat: manage ignored wechat prompts`.

### Task 5: Article 14 Regression And Delivery

**Files:**
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:** Article 14 fixtures assert exact plans for prompt concepts #90-#93 without depending on production row IDs.

- [ ] Add regression fixtures for six-process grouping, scope comparison, WBS form comparison, and QC-before-acceptance relation; confirm old behavior fails.
- [ ] Run targeted tests, full backend suite, frontend build, migration upgrade/downgrade check, and `git diff --check`.
- [ ] Push the branch, deploy Atlas, run migration, and verify container health plus `/api/health` 200.
- [ ] Regenerate Article 14 prompts, inspect visual plans and generated previews, and report any provider-level visual limitations separately.
