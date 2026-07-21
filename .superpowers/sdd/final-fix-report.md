# WeChat MP Final Fix Report

## Final Fix

**Status:** DONE_WITH_CONCERNS

**Implementation commit:** `c074142 fix: complete wechat mp publish workflow`

### Findings Resolved

1. Added first-class 16:9 cover generation at `/api/platforms/wechat-mp/articles/{article_id}/cover` and exposed configured-model cover generation in the writer UI. Tests create covers through the API rather than direct DB insertion.
2. Added a due scheduled-publish executor, registered `wechat_mp_due_publish_runner` with APScheduler, and added owner-scoped scheduled-job cancellation.
3. Added article revisions and draft-sync revision snapshots. Content, skill, prompt-layout, image, cover, and asset-deletion changes stale prior syncs; publishing requires a current synced revision.
4. Added a server-side `xiaomao-illustrations` prompt contract with white 16:9 hand-drawn Xiaomao visual DNA, rejected image generation for `none`, and made article creation start prompt generation in the same frontend action.
5. Replaced hard-coded WeChat text/image model selection with owner-scoped default `ModelConfig` resolution and legacy-safe fallbacks. Removed the WeChat UI's hard-coded `gpt-image-2` and exposed configured image-model selection.
6. Draft sync and immediate publish now create pending journal rows before remote calls, then persist success or failed status with raw response/error data. Pending reconciliation guards prevent duplicate retries after uncertain outcomes.
7. Successful prompt-provider calls and usage rows commit independently during a batch. Article/prompt/image cost estimates are populated from pricing where available and article aggregate cost is shown in the writer UI.
8. Cached WeChat access tokens are Fernet-encrypted in `token_cache`; raw token strings are not persisted and cached tokens remain reusable after decryption.
9. Asset deletion removes broken image tags or restores prompt markers, updates prompt/article state, stales synced revisions, and draft sync rejects unresolved markers, orphaned URLs, or missing local files.
10. `WechatMpPublishStatus` now includes the actual `submitted` state plus pending/cancelled lifecycle states.

### Verification

- Focused WeChat backend: `61 passed`.
- Full backend: `207 passed`.
- Alembic: fresh SQLite upgrade through `20260721_wmp003` passed.
- Static checks: `git diff --check` and Python module compilation passed.
- Frontend: `npm run build` passed (`tsc` + Vite, 3235 modules transformed).

### Concern

The current environment uses Node.js `18.15.0`; Vite 7 warns that Node `20.19+` or `22.12+` is supported. The production build still completed successfully. Existing bundle-size and Python deprecation warnings remain unchanged and are non-blocking.

## Second Final Fix

**Status:** DONE_WITH_CONCERNS

**Implementation commit:** `3fffa19 fix: resolve second wechat mp final review`

### Findings Resolved

1. WeChat cover and inline image generation now use the shared provider/model size normalizer. The default Doubao path receives `2732x1536` for the `16:9` alias, with regression coverage for inline and cover calls.
2. Publish jobs now have a nullable unique active key per current draft sync. Repeated immediate or scheduled requests return the existing active job across `scheduled`, `pending`, `submitted`, and `publishing`; terminal jobs release the key. The due runner cancels legacy duplicate rows and atomically claims scheduled jobs before provider submission.
3. The WeChat MP due runner now starts in a dedicated scheduler regardless of the disabled default XHS scheduler. An owner-scoped publish-job list endpoint and reload-backed frontend task list expose scheduled jobs and cancellation after reload.
4. Editing a generated prompt restores its placeholder, removes the stale embedded image from article HTML, resets the prompt/article state, invalidates synced revisions, and permits a subsequent image generation.
5. `none` now means skip inline illustrations only: cover generation remains available in the backend and frontend, while inline generation stays blocked.
6. Inline image usage is added to `article.cost_estimate`; the writer displays the aggregate actual cost across writing, prompts, cover, and inline images. A model-aware image-cost endpoint supplies the per-action estimate shown before image buttons.
7. The writer page now provides title and Markdown body editing, saves through article PATCH, refreshes rendered preview/revision state, and tells the user to resync stale drafts before publishing.
8. Deleting an obsolete asset no longer resets a prompt or article when a newer image remains embedded. Only the currently embedded inline asset or current cover changes article state and revision.

### Verification

- Focused second-review regressions: `12 passed`.
- WeChat MP backend: `69 passed`.
- Full backend: `215 passed`.
- Alembic: fresh SQLite upgrade through `20260721_wmp004` passed.
- Static checks: `git diff --check` and Python module compilation passed.
- Frontend: `npm run build` passed (`tsc` + Vite, 3235 modules transformed).

### Concern

The current environment still uses Node.js `18.15.0`; Vite 7 warns that Node `20.19+` or `22.12+` is supported. The production build completed successfully. Existing bundle-size and Python deprecation warnings remain non-blocking.

## Third Final Fix

**Status:** DONE_WITH_CONCERNS

**Implementation commit:** `79690b2 fix: resolve third wechat mp final review`

### Findings Resolved

1. Article PATCH now distinguishes omitted, unchanged, and changed body fields. No-op saves preserve rendered HTML, embedded images, status, and revision; real Markdown/HTML or skill changes remove obsolete markers and inline prompt state, detach historical assets, stale synced drafts, and increment the article revision once.
2. Publish submission now treats only an explicit nonzero WeChat `errcode` as a definitive rejection. Transport, timeout, malformed, and missing-result failures keep the job pending with its unique active key retained, so repeated requests return the same guarded job instead of submitting again.
3. The `none` workflow skips shotlisting and inline prompt generation entirely, clears any prior inline planning state when selected, and can sync normally after cover generation without unresolved placeholders.
4. Inline image generation accepts both `prompt_ready` and `failed`, preserving the editable prompt and allowing a failed provider call to be retried safely.
5. Scheduled publish input is normalized to naive UTC for the existing database column and serialized as explicit UTC (`Z`) in API responses. The frontend continues to submit UTC ISO timestamps and renders explicit UTC responses in browser-local time.
6. The writer and publish pages now expose text/prompt estimate guidance plus visible `¥0` labels for WeChat draft sync and publish actions.

### Verification

- Third-review focused regressions: `6 passed`.
- WeChat MP backend: `75 passed`.
- Full backend: `221 passed`.
- Static checks: `git diff --check` and Python module compilation passed.
- Frontend: `npm run build` passed (`tsc` + Vite, 3235 modules transformed).

### Concern

The current environment still uses Node.js `18.15.0`; Vite 7 warns that Node `20.19+` or `22.12+` is supported. The production build completed successfully. Existing bundle-size and Python/Starlette deprecation warnings remain non-blocking.

## Fourth Final Fix

**Status:** DONE_WITH_CONCERNS

**Implementation commit:** `28aabde fix: resolve fourth wechat mp final review`

### Findings Resolved

1. Active publish identity is now scoped to account, article, and article revision instead of a replaceable draft-sync row. Re-syncing an unchanged revision after an indeterminate publish returns the original guarded job and cannot submit a second remote publish request.
2. Publish token acquisition is classified as a definite pre-submit stage. Token timeouts and malformed token responses fail the journal row, clear its active key, and allow a safe retry; only uncertainty from or after `submit_publish` retains the pending guard.
3. Draft sync now has a database-backed unique active key per account, article, and revision. Token and media-upload failures fail and release the key, explicit WeChat `draft/add` rejections fail and release it, while transport or malformed-result uncertainty after `draft/add` starts remains pending and blocks duplicate remote draft creation.
4. The `none` workflow again creates shotlists and editable prompts. These prompts remain `skipped`, never add or restore HTML markers, can be edited or regenerated, sync without prompt-related rejection, and remain rejected by the inline-image endpoint. Frontend guidance and action availability match this behavior.
5. Migration `20260721_wmp005` adds the draft-sync active key, widens/rekeys publish active keys, preserves canonical active rows, and closes pre-existing duplicate active rows during upgrade.

### Verification

- Fourth-review focused regressions: `7 passed`.
- WeChat MP backend: `81 passed`.
- Full backend: `227 passed`.
- Alembic: fresh SQLite upgrade through `20260721_wmp005` passed; unique draft/publish active-key indexes and `VARCHAR(200)` columns were inspected.
- Static checks: `git diff --check` and Python module compilation passed.
- Frontend: `npm run build` passed (`tsc` + Vite, 3235 modules transformed).

### Concern

The current environment still uses Node.js `18.15.0`; Vite 7 warns that Node `20.19+` or `22.12+` is supported. The production build completed successfully. Existing bundle-size and Python/Starlette deprecation warnings remain non-blocking.

## Fifth Final Fix

**Status:** DONE

### Findings Resolved

1. A successful same-revision draft re-sync now rebinds only active `scheduled` publish jobs for that account and article to the new draft sync. `pending`, `submitted`, and `publishing` jobs remain bound to their original draft syncs so remote submission and reconciliation state is not altered.
2. Migration `20260721_wmp005` now selects remote-active `pending`, `submitted`, and `publishing` rows before `scheduled` rows when canonicalizing duplicate revision-scoped publish jobs, with ID used as the tie-breaker within each priority group.

### Verification

- Focused fifth-review regressions: `2 passed`.
- WeChat MP backend: `82 passed`.
- Full backend: `229 passed`.
- Static checks: `git diff --check` and Python module compilation passed.
- Frontend: not run; no frontend files changed.
