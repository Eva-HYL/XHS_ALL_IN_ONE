# WeChat MP Character Four Views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require four confirmed character views before a WeChat MP character can generate cover or inline images.

**Architecture:** Persist reusable, private character views separately from article assets. Resolve one confirmed character per generated prompt, inject stable front/back/left/right references into the image-provider request, and expose the state through the character library and writer UI.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic, React, TypeScript, Ant Design.

## Global Constraints

- Character view files live below `storage/character-images/u<user_id>/` and are not exposed through the public media route.
- Valid uploads are JPEG, PNG, or WebP up to 10 MiB; all view routes are owner-scoped and return 404 for foreign records.
- Views are ordered `front`, `back`, `left`, `right`; all must be confirmed before generation.
- `@形象名` can select one confirmed character and overrides the article default only for that prompt.
- Providers without `reference_images` support must fail before creating an article asset or usage record.

---

### Task 1: Persist and manage four view slots

**Files:**
- Modify: `backend/app/models/wechat_mp.py`, `backend/app/schemas/wechat_mp.py`, `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/df9e7f5d9f3a_add_wechat_mp_character_views.py`
- Modify: `backend/app/services/wechat_mp_character_service.py`, `backend/app/api/platforms/wechat_mp/characters.py`, `tests/backend/test_wechat_mp.py`

- [ ] Add `WechatMpCharacterView`, draft/confirmed state, anchor version, and the unique `(character_id, view)` constraint.
- [ ] Add owner-scoped upload, generate, and confirm endpoints; replacing a confirmed view returns the character to draft.
- [ ] Run focused character tests and Alembic head verification.

### Task 2: Enforce anchors during image generation

**Files:**
- Modify: `backend/app/models/wechat_mp.py`, `backend/app/schemas/wechat_mp.py`, `backend/app/services/wechat_mp_image_service.py`, `backend/app/api/platforms/wechat_mp/articles.py`, `tests/backend/test_wechat_mp.py`

- [ ] Store the selected `character_id` on image prompts.
- [ ] Resolve `@name` or article default before the provider call, reject missing/ambiguous/unconfirmed choices, and pass exactly four reference URLs in stable order.
- [ ] Add provider-contract and rejection regression tests.

### Task 3: Character library and writer controls

**Files:**
- Modify: `frontend/src/types/index.ts`, `frontend/src/lib/api.ts`, `frontend/src/pages/platforms/wechat-mp/characters-page.tsx`, `frontend/src/pages/platforms/wechat-mp/writer-page.tsx`

- [ ] Display four direction cards, generate/regenerate, upload, and confirm controls.
- [ ] Disable unconfirmed character choices and provide an actionable link to the library.
- [ ] Add one-primary-character mention selection for editable prompts.

### Task 4: Verification and release

**Files:**
- Verify: `tests/backend/test_wechat_mp.py`, `frontend/package.json`, `Dockerfile`, deployment migration state

- [ ] Run focused and full relevant backend tests, then `npm run build`.
- [ ] Build and deploy with the existing Atlas compose workflow, run migration/head checks, and verify health plus live API responses.
