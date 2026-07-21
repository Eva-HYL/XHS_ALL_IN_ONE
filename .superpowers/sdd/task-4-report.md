# Task 4 Report: Automatic Shotlist and Editable Image Prompts

## Status

Completed on branch `codex/wechat-mp-auto-publish`, based on `97a4d88`.

## RED Evidence

1. Added `test_generate_prompts_defaults_to_xiaomao_skill` before production code.
2. `pytest tests/backend/test_wechat_mp.py::test_generate_prompts_defaults_to_xiaomao_skill -v` could not run because `pytest` is not available on `PATH`.
3. The equivalent repository command, `PYTHONPATH=. .venv/bin/pytest tests/backend/test_wechat_mp.py::test_generate_prompts_defaults_to_xiaomao_skill -v`, failed as expected before implementation:
   - `ImportError: cannot import name 'wechat_mp_image_prompt_service'`

## GREEN Evidence

1. `PYTHONPATH=. .venv/bin/pytest tests/backend/test_wechat_mp.py -k 'prompt or shotlist' -q`
   - `5 passed, 14 deselected`
2. `PYTHONPATH=. .venv/bin/pytest tests/backend/test_wechat_mp.py -q`
   - `19 passed`
3. Both runs emitted existing third-party/deprecation warnings from Starlette TestClient and SQLAlchemy `datetime.utcnow` usage.

## Files Changed

- `backend/app/services/wechat_mp_shotlist_service.py`
  - Selects one to eight semantic illustration anchors from `layout_ready` article Markdown.
- `backend/app/services/wechat_mp_image_prompt_service.py`
  - Adds monkeypatchable `_call_prompt_model`, prompt creation, regeneration, required record metadata, and per-model-call usage records attributed to the article.
- `backend/app/api/platforms/wechat_mp/articles.py`
  - Adds prompt generation, prompt editing, and prompt regeneration endpoints with owner-scoped 404 handling.
- `tests/backend/test_wechat_mp.py`
  - Adds default skill, shotlist/usage attribution, edit/regenerate version, and foreign-access coverage.

## Self-Review

- Default selected skill is `xiaomao-illustrations`; the literal `none` remains a valid supplied skill name and still reaches prompt generation.
- New prompt records set `version=1`, `editable_prompt=prompt`, and `status="prompt_ready"`; edits and regeneration increment version.
- Prompt model usage records include `platform="wechat_mp"`, `resource_type="wechat_mp_article"`, and the article resource ID.
- Article and prompt access is owner-scoped and returns 404 for foreign resources.
- No image generation, WeChat draft synchronization, publishing, or frontend changes were added.

## Concerns

None for the requested scope. The bare `pytest` executable is absent from `PATH`; use `PYTHONPATH=. .venv/bin/pytest` in this repository.

## Review Fixes

### Transactional Prompt Generation

- Added `commit=False` to `record_text_usage()` while preserving its existing default commit behavior.
- Prompt generation now records usage without individual commits and rolls back all shotlist sections, prompts, usage records, and article updates if any model call or final commit fails.
- Added regression coverage where the second prompt-model call fails and verifies no sections, prompts, or usage records remain for the article.

### Malformed Provider Output

- Prompt-model response parsing now validates content type, usage object type, and non-negative integer token counts before returning a result.
- Malformed provider values are normalized to `ValueError`, so the prompt endpoint returns HTTP 502 rather than HTTP 500.

### Verification

1. `PYTHONPATH=. .venv/bin/pytest tests/backend/test_wechat_mp.py -k 'rolls_back_all_records or malformed_prompt_model_output or prompt or shotlist' -q`
   - `8 passed, 14 deselected`
2. `PYTHONPATH=. .venv/bin/pytest tests/backend/test_api.py::test_usage_recording_persists_text_and_image_records -q`
   - `1 passed`
3. `PYTHONPATH=. .venv/bin/pytest tests/backend/test_wechat_mp.py -q`
   - `22 passed`
