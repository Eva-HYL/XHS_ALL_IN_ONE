# Task 8 Report: WeChat MP Frontend Module

## Status

DONE_WITH_CONCERNS

## Files Changed

- `frontend/src/types/index.ts`
  - Added typed WeChat MP article, prompt, account, asset, draft-sync, publish-job, and request payload types.
- `frontend/src/lib/api.ts`
  - Added typed functions for every implemented `/api/platforms/wechat-mp/*` endpoint.
- `frontend/src/pages/platforms/wechat-mp/wechat-mp-layout.tsx`
  - Added isolated WeChat MP sub-navigation.
- `frontend/src/pages/platforms/wechat-mp/dashboard-page.tsx`
  - Added article/account/asset overview.
- `frontend/src/pages/platforms/wechat-mp/accounts-page.tsx`
  - Added account creation, listing, and connection testing. AppSecret is never rendered from API responses.
- `frontend/src/pages/platforms/wechat-mp/writer-page.tsx`
  - Added six-step article workflow with default `xiaomao-illustrations`, `none` support, prompt editing, image controls, preview, and handoff to publishing.
- `frontend/src/pages/platforms/wechat-mp/assets-page.tsx`
  - Added WeChat MP-only asset listing and deletion.
- `frontend/src/pages/platforms/wechat-mp/publish-page.tsx`
  - Added draft sync, publish submission/status polling, and explicit confirmation for immediate publishing.
- `frontend/src/app/router.tsx`
  - Registered independent `/platforms/wechat-mp/*` routes without changing XHS image-studio routing.
- `frontend/src/components/layout/app-shell.tsx`
  - Added a separate top-level `公众号` navigation group.
- `frontend/package-lock.json`
  - Reconciled the existing stale lockfile during dependency installation so `react-is` is represented.

## Verification

- `PATH=/Users/yingdasun/.nvm/versions/node/v24.14.0/bin:$PATH npm run build` (from `frontend`): PASS. Vite built successfully; only the existing large-chunk warning was emitted.
- `PYTHONPATH=. .venv/bin/python -m pytest tests/backend/test_wechat_mp.py tests/backend/test_api.py -q`: PASS, `188 passed`.
- `PYTHONPATH=. .venv/bin/python -m pytest tests/backend -q`: PASS, `192 passed`.
- OpenAPI check: PASS. All new paths are under `/api/platforms/wechat-mp/*`.
- Route/source isolation check: PASS. `/platforms/xhs/image-studio` remains registered to `XhsImageStudioPage`; no XHS image-studio components are imported by the WeChat MP module.
- Ownership, non-admin visibility, usage-record platform, and WeChat asset-table isolation are covered by the passing backend WeChat MP test suite.

## Self-Review

- API calls use the existing Axios client whose base URL is `/api`; endpoint strings do not duplicate that prefix.
- The writer keeps prompt generation enabled for `none` and disables only image-generation buttons.
- The accounts UI only renders `name`, `app_id`, timestamps/status, and a static security message. It never reads or displays a returned secret.
- Immediate publish always opens a confirmation modal before sending `{ confirm: true }`.
- The backend does not expose draft-sync or publish-job list APIs. The publish page therefore shows statuses for the active workflow session and polls the created publish job; no backend behavior was changed.

## Concerns

- A true visual browser smoke test could not run: this environment has no browser-control capability, and local Vite processes are terminated by the command runner before a separate HTTP request can connect. The TypeScript/Vite production build, route registration, and source isolation checks passed.
- The default system Node is v18 while Vite 7 and React Router 7 require Node 20+. The build was run with the locally installed Node 24 toolchain.

## Review Fix: Reload Persisted Writer State

- Restored `article.illustration_skill` when opening `?article=<id>`, including `none`.
- Added owner-scoped `GET /api/platforms/wechat-mp/articles/{article_id}/prompts` and a frontend client helper so saved prompts are loaded without regeneration.
- The existing `none` behavior remains prompt-enabled while image-generation buttons stay disabled after reload; no XHS image-studio files were changed.

### Fix Verification

- `PYTHONPATH=. .venv/bin/python -m pytest tests/backend/test_wechat_mp.py tests/backend/test_api.py -q`: PASS, `189 passed`.
- `PATH=/Users/yingdasun/.nvm/versions/node/v24.14.0/bin:$PATH npm run build` (from `frontend`): PASS; existing large-chunk warning only.
