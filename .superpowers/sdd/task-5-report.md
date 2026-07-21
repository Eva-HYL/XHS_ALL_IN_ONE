# Task 5 Report: WeChat MP Image Generation and Asset Library

## Status

Complete. Implemented only the WeChat MP image generation path, independent asset persistence/library endpoints, article HTML backfill, image usage records, and focused tests.

## RED Evidence

1. Added `test_generate_wechat_mp_image_saves_only_wechat_asset_and_backfills_article` and `test_wechat_mp_assets_are_owner_scoped_and_delete_local_media` before production code.
2. Ran:

   ```bash
   PYTHONPATH=. .venv/bin/pytest tests/backend/test_wechat_mp.py -k "generate_wechat_mp_image_saves_only_wechat_asset_and_backfills_article or wechat_mp_assets_are_owner_scoped" -v
   ```

3. Result: both tests failed because `backend.app.services.wechat_mp_image_service` and `backend.app.api.platforms.wechat_mp.assets` did not exist.

## GREEN Evidence

1. Implemented `generate_asset_for_prompt` and the monkeypatchable `_call_image_model` seam.
2. Added prompt image generation, independent asset list/delete routes, article backfill, status transitions, and platform/resource-scoped image usage recording.
3. Ran focused tests:

   ```bash
   PYTHONPATH=. .venv/bin/pytest tests/backend/test_wechat_mp.py -k "image or asset" -q
   ```

   Result: `4 passed`.

4. Ran WeChat MP tests:

   ```bash
   PYTHONPATH=. .venv/bin/pytest tests/backend/test_wechat_mp.py -q
   ```

   Result: `25 passed`.

5. Ran the relevant full backend suite and syntax/diff checks:

   ```bash
   PYTHONPATH=. .venv/bin/pytest tests/backend -q
   PYTHONPATH=. .venv/bin/python -m compileall -q backend/app/services/wechat_mp_image_service.py backend/app/api/platforms/wechat_mp/assets.py backend/app/api/platforms/wechat_mp/articles.py
   git diff --check
   ```

   Result: `171 passed`; compile and diff checks passed.

## Files Changed

- `backend/app/services/wechat_mp_image_service.py`: independent provider seam, media persistence, WeChat asset persistence, prompt/article status updates, HTML backfill, and usage recording.
- `backend/app/api/platforms/wechat_mp/assets.py`: owner-scoped asset list/delete endpoints and safe media-directory deletion.
- `backend/app/api/platforms/wechat_mp/articles.py`: prompt-scoped image generation endpoint on the required `/api/platforms/wechat-mp/prompts/{prompt_id}/image` path.
- `backend/app/main.py`: mounts the prompt-image and asset routers.
- `backend/app/services/usage_recording_service.py`: supports platform/resource metadata and caller-controlled commits for atomic image generation.
- `tests/backend/test_wechat_mp.py`: coverage for isolated WeChat asset persistence, prompt/article/usage changes, owner scoping, and local file deletion.

## Self-Review

- Generated images use only `WechatMpAsset` / `wechat_mp_assets`; no XHS `IllustrationAsset` or `illustration_assets` writes occur.
- Prompt and asset lookups are user-scoped; foreign access returns 404.
- Local deletion resolves paths and only unlinks files under the configured media directory.
- Provider-facing code is isolated from XHS image service classes and uses the shared media storage/public URL convention.
- No WeChat draft sync, publishing, or frontend work was added.

## Concerns

None.

## Review Fix: Prompt Placeholder Backfill

### Root Cause

The article writer rendered `html_body` without image placeholders. Prompt generation created `WechatMpImagePrompt` rows but did not insert their stable markers into the article, so generated `WechatMpAsset` records could not be embedded by the image backfill service.

### Fix

1. Prompt generation now inserts one stable `{{image:prompt-<id>}}` marker per prompt into `article.html_body`, directly after the matching rendered source section when possible and otherwise at the end of the article.
2. Marker insertion is idempotent, so existing markers are never duplicated. Prompt regeneration retains the same prompt ID and marker.
3. The image test now executes the real article -> prompt -> image flow; no test fixture manually injects a marker.
4. Independent `WechatMpAsset` persistence, owner scoping, usage records, and the absence of XHS `IllustrationAsset` writes remain covered.

### Verification

```bash
PYTHONPATH=. .venv/bin/pytest tests/backend/test_wechat_mp.py -k "prompt or image or asset" -q
```

Result: `12 passed, 13 deselected`.

```bash
PYTHONPATH=. .venv/bin/pytest tests/backend/test_wechat_mp.py -q
```

Result: `25 passed`.
