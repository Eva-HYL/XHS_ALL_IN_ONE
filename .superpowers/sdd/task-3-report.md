# Task 3 Report: Article Writer, Layout, and Billing Records

## Status

Completed on branch `codex/wechat-mp-auto-publish` from base `3da85e1`.

## TDD Evidence

### RED

Added `test_create_wechat_mp_article_generates_markdown_html_and_usage` before implementation.

Initial command:

```bash
PYTHONPATH=. .venv/bin/pytest tests/backend/test_wechat_mp.py::test_create_wechat_mp_article_generates_markdown_html_and_usage -v
```

Initial result: failed with `ImportError: cannot import name 'wechat_mp_writer_service'`, confirming the service/router did not yet exist. The bare `pytest` command was unavailable on `PATH`; the project virtualenv runner was used for all subsequent evidence.

### GREEN

After implementation, the same focused generation test passed:

```text
1 passed
```

Focused article suite:

```bash
PYTHONPATH=. .venv/bin/pytest tests/backend/test_wechat_mp.py -k article -q
```

Result: `4 passed, 11 deselected`.

Relevant regression suite:

```bash
PYTHONPATH=. .venv/bin/pytest tests/backend/test_wechat_mp.py tests/backend/test_api.py::test_usage_recording_persists_text_and_image_records -q
```

Result: `16 passed`.

Full backend suite:

```bash
PYTHONPATH=. .venv/bin/pytest tests/backend -q
```

Result: `161 passed`.

Validation also passed:

```bash
PYTHONPATH=. .venv/bin/python -m py_compile backend/app/api/platforms/wechat_mp/articles.py backend/app/services/wechat_mp_writer_service.py backend/app/services/wechat_mp_layout_service.py backend/alembic/versions/20260721_wmp002_add_usage_record_resources.py
PYTHONPATH=. .venv/bin/alembic -c backend/alembic.ini heads
git diff --check
```

Alembic reports `20260721_wmp002 (head)` and `git diff --check` produced no errors.

## Delivered

- Added local WeChat-safe Markdown rendering for headings, paragraphs, blockquotes, ordered/unordered lists, and explicit image placeholders.
- Added `_call_writer_model` as the monkeypatchable JSON writer seam and `generate_wechat_article` to persist rendered articles and text usage.
- Added create, list, detail, and owner-scoped patch article endpoints, registered in the application router.
- Extended `UsageRecord` and `record_text_usage` with optional platform/resource attribution. WeChat writer usage records carry `platform="wechat_mp"`, `resource_type="wechat_mp_article"`, and the persisted article ID.
- Added Alembic revision `20260721_wmp002` for the billing metadata columns and indexes.
- Added endpoint, renderer, ownership, patch, billing, and malformed model-response tests.

## Files Changed

- `backend/app/api/platforms/wechat_mp/articles.py`
- `backend/app/main.py`
- `backend/app/models/pipeline.py`
- `backend/app/services/usage_recording_service.py`
- `backend/app/services/wechat_mp_layout_service.py`
- `backend/app/services/wechat_mp_writer_service.py`
- `backend/alembic/versions/20260721_wmp002_add_usage_record_resources.py`
- `tests/backend/test_wechat_mp.py`

## Self-Review

- Article reads and edits are user-owner scoped and return `404` for foreign IDs.
- Writer failures and malformed model JSON surface as `502`; article and billing persistence are rolled back for locally detected malformed result data.
- Billing uses an existing priced model (`qwen3.7-plus`) so a generation cannot succeed without a price snapshot.
- The renderer escapes user Markdown and image attributes before producing HTML.
- Scope deliberately excludes prompts, shotlists, image generation, drafts, publishing, and frontend behavior.

## Concerns

- Live writer requests require `WECHAT_MP_WRITER_BASE_URL` and `WECHAT_MP_WRITER_API_KEY`. Tests monkeypatch `_call_writer_model`, so no network call occurs in the suite.
- Existing `datetime.utcnow()` deprecation warnings remain in inherited model code and tests; no new test failures result.
