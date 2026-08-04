# WeChat MP Token-Efficient Shotlist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-paragraph prompt generation with deterministic content filtering, zero-token structural prompts, and at most one batched Qwen semantic call per article.

**Architecture:** Parse Markdown into stable content blocks, hard-filter presentation noise, locally generate exact diagram prompts, and batch only ambiguous high-value blocks through `qwen3.7-max`. Persist content/generation fingerprints for reuse, return analysis statistics with generated prompts, and preserve historical image assets when candidates become obsolete.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, SQLAlchemy 2, Alembic, requests, React, TypeScript, Ant Design, pytest.

## Global Constraints

- Scope is only the WeChat MP writer; do not change the Xiaohongshu illustration pipeline.
- Exact process nodes, table labels, category names, and ordering must not be invented, removed, or renamed.
- Hard-filtering and deterministic prompts record zero model tokens and zero model cost.
- Semantic analysis uses at most one model request per article generation action.
- Prefer configured `qwen3.7-max`; only quota/model-availability errors may switch through the existing quota selector.
- Total image candidates are capped at 8; semantic candidates are capped at `min(6, remaining_slots)`.
- `none` returns no body prompts and performs no text-model call.
- Obsolete inline images are removed from article HTML, but `WechatMpAsset` rows and files remain available in the asset library.
- Use TDD for every task and keep each task in its own commit.

### Task 1: Persistence And API Contracts

**Files:**
- Create: `backend/alembic/versions/b7e2c4d6a8f0_add_wechat_prompt_fingerprints.py`
- Modify: `backend/app/models/wechat_mp.py`
- Modify: `backend/app/schemas/wechat_mp.py`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:** Add non-null string fields `WechatMpArticleSection.source_fingerprint`, `analysis_version`, and `WechatMpImagePrompt.generation_fingerprint`. Add `WechatMpPromptAnalysisResponse` and `WechatMpPromptGenerationResponse`. Migration revision is `b7e2c4d6a8f0`, down revision `a4c7e9d2f1b0`.

- [ ] Write failing schema/model tests, including defaults of `""`.
- [ ] Run targeted tests and confirm RED.
- [ ] Add ORM columns (`String(64)`, `String(32)`, `String(64)`) and Alembic columns with `server_default=""`, `nullable=False`.
- [ ] Add analysis counters `source_blocks`, `filtered_blocks`, `deterministic_prompts`, `semantic_candidates`, `reused_prompts`, `model_calls`, `input_tokens`, `output_tokens`, all defaulting to zero. Add response `{items, analysis}`.
- [ ] Verify sole Alembic head is `b7e2c4d6a8f0`; run targeted tests and `git diff --check`.
- [ ] Commit `feat: persist wechat prompt fingerprints`.

### Task 2: Zero-Token Content Analysis Engine

**Files:**
- Create: `backend/app/services/wechat_mp_content_analysis_service.py`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:** Frozen dataclasses `ContentBlock`, `VisualCandidate`, `ContentAnalysis`; `analyze_content(markdown_body: str) -> ContentAnalysis`. Results ordered by score descending then source index ascending.

- [ ] Write failing tests for nonvisual HTML/metadata filtering, exact flow extraction, valid Markdown tables, classification mappings, heading context, no-candidate result, and Jaccard `0.82` dedupe boundary.
- [ ] Confirm RED with `pytest -k content_analysis`.
- [ ] Implement `ANALYSIS_VERSION="v2"`, `MAX_SEMANTIC_INPUT_BLOCKS=24`, `MAX_BLOCK_CHARS=500`, `MAX_TOTAL_INPUT_CHARS=12000`.
- [ ] Implement pure helpers `_parse_blocks`, `_filter_reason`, `_extract_structure`, `_semantic_score`, `_char_bigrams`, `_jaccard`, `_deduplicate`. Hard filters run before arrow/table recognition.
- [ ] Verify tests GREEN and commit `feat: analyze wechat illustration candidates locally`.

### Task 3: Deterministic Prompts And Stable Reuse

**Files:**
- Modify: `backend/app/services/wechat_mp_shotlist_service.py`
- Modify: `backend/app/services/wechat_mp_image_prompt_service.py`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:** `build_deterministic_prompt(candidate, character) -> str`; `generation_fingerprint(candidate, *, character_id, anchor_version, skill_version) -> str`. Shotlist consumes `ContentAnalysis` and matches by source fingerprint before legacy section index.

- [ ] Write failing tests proving exact flows use zero model calls/cost, exact labels remain unchanged, unchanged reruns preserve prompt IDs, and moving a paragraph preserves its ID.
- [ ] Confirm RED.
- [ ] Build deterministic prompts with canonical character mention and exact labels only. Prohibit titles, dimensions, watermarks, explanations, invented labels, and unrelated text.
- [ ] Compute hashes from sorted stable JSON. Match non-empty source fingerprints first; use section index only for legacy rows.
- [ ] Verify existing process/table tests plus new reuse tests and commit `feat: generate exact wechat prompts without tokens`.

### Task 4: One-Call Qwen Semantic Batch

**Files:**
- Create: `backend/app/services/wechat_mp_prompt_batch_service.py`
- Modify: `backend/app/services/wechat_mp_model_service.py`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:** `BatchPromptItem`, `BatchPromptResult`; `generate_semantic_prompts(*, db, user_id, article_title, candidates, character) -> BatchPromptResult`; `resolve_wechat_mp_shotlist_model(...)` explicitly prefers `qwen3.7-max`.

- [ ] Write failing tests for one request, non-duplicated compact payload, max preference, strict JSON, malformed output degradation, and quota-only fallback.
- [ ] Confirm RED with `pytest -k semantic_batch`.
- [ ] Keep fixed instructions/schema in system content and one compact JSON object in user content. Parse only top-level `{items: [...]}`; ignore unknown IDs, duplicates, dropped items, and overflow.
- [ ] Retry only when `is_quota_error` identifies quota/model availability; exclude failed model and use configured `shotlist` selector once. Other errors retain deterministic results without retry.
- [ ] Verify normal request count 1 and explicit quota fallback count 2; commit `feat: batch wechat semantic prompts with qwen`.

### Task 5: Prompt Orchestration, Cost Allocation, And API Response

**Files:**
- Modify: `backend/app/services/wechat_mp_image_prompt_service.py`
- Modify: `backend/app/api/platforms/wechat_mp/articles.py`
- Modify: `backend/app/schemas/wechat_mp.py`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:** `generate_image_prompts(...) -> WechatMpPromptGenerationResult`; API response is `WechatMpPromptGenerationResponse` with status 201.

- [ ] Write failing tests for mixed deterministic/semantic content, empty content, `none`, obsolete cleanup, unchanged revisions, one usage row, and Decimal cost conservation.
- [ ] Confirm RED.
- [ ] Orchestrate: analyze, reuse, deterministic generation, one unresolved semantic batch, one `UsageRecord(step="generate_image_prompts_batch")`, exact cost allocation, obsolete placeholder cleanup, and one transaction commit.
- [ ] Do not increment article revision when fingerprints, prompts, placeholders, and selected skill are unchanged. Never delete historical asset rows/files.
- [ ] Return 201 empty items for no candidates and `none`; reserve 502 for a real configured-provider failure that leaves no deterministic result.
- [ ] Verify lifecycle regressions and commit `feat: orchestrate token-efficient wechat prompts`.

### Task 6: Frontend Results And End-To-End Verification

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/pages/platforms/wechat-mp/writer-page.tsx`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:** Add `WechatMpPromptAnalysis`, `WechatMpPromptGenerationResult`; API client returns the result object rather than a bare prompt list.

- [ ] Add source assertions and TypeScript types; confirm RED.
- [ ] Store `result.items` and `result.analysis` in writer state.
- [ ] Display: `本次分析：原文 {source_blocks} 段，过滤 {filtered_blocks} 段，复用 {reused_prompts} 条，模型调用 {model_calls} 次，Token {input_tokens + output_tokens}。`
- [ ] Empty copy: `未发现值得配图的正文内容，本次未生成装饰性配图。` `none` copy: `已跳过正文提示词和正文生图费用。`
- [ ] Run targeted tests, full backend suite, `cd frontend && npm run build`, and `git diff --check`.
- [ ] Commit `feat: show wechat prompt analysis savings`.

### Task 7: Review, Push, And Atlas Deployment

**Files:** Review all Task 1-6 changes.

- [ ] Review tenant scoping, secret handling, Decimal conservation, one-call guarantee, asset retention, and Xiaohongshu isolation.
- [ ] Run full backend tests and frontend build from a clean tree.
- [ ] Push `codex/wechat-mp-auto-publish`.
- [ ] On Atlas fetch the fork, merge into the active deploy branch, build the app image, recreate only the app service, and run migration.
- [ ] Verify container health, `/api/health` 200, DB revision `b7e2c4d6a8f0`, and probes: details/summary=0 candidates; exact process=0 calls; none=0 calls; semantic multi-block=1 call.
- [ ] Report commits, test/build evidence, deployment image/container/migration evidence, and residual provider limitations.
