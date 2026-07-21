# Task 1: WeChat MP Data Foundation

## Status

Complete. The implementation adds an independent WeChat Official Account data foundation only. It does not add account APIs, writer services, image generation, WeChat API calls, frontend code, or any use of Xiaohongshu `illustration_assets`.

## TDD Evidence

### RED

Command:

```bash
/Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/python -m pytest tests/backend/test_wechat_mp.py::test_wechat_mp_models_are_independent_from_xhs_assets -v
```

Result: `1 failed in 0.33s`.

The failure was the required missing-module condition:

```text
ModuleNotFoundError: No module named 'backend.app.models.wechat_mp'
```

### GREEN

The same focused command passed after implementation: `1 passed in 0.32s`.

The ownership test persists a `WechatMpArticle` and `WechatMpAsset` using the default `xiaomao-illustrations` skill, then verifies one WeChat asset exists while `IllustrationAsset` remains empty.

## Files Changed

- `backend/app/models/wechat_mp.py`: seven isolated `wechat_mp_*` SQLAlchemy models.
- `backend/app/schemas/wechat_mp.py`: article/image/draft-sync/publish status literals, create request, and requested response schemas.
- `backend/app/models/__init__.py`: model registration and exports.
- `backend/alembic/versions/20260721_wmp001_add_wechat_mp_tables.py`: reversible creation of tables, foreign keys, and required indexes.
- `tests/backend/test_wechat_mp.py`: isolated SQLite ownership test and fixtures.

## Verification

```bash
/Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/python -m pytest tests/backend/test_api.py tests/backend/test_wechat_mp.py -q
```

Result: `143 passed, 1 warning in 15.23s`. The warning is the existing Starlette `TestClient` deprecation warning for `httpx`.

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/alembic -c backend/alembic.ini upgrade head
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/alembic -c backend/alembic.ini downgrade 17a6f0c5d2e1
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/alembic -c backend/alembic.ini upgrade head
```

Result: all three commands passed. The revision upgraded from `17a6f0c5d2e1` to `20260721_wmp001`, downgraded cleanly, then upgraded again. The initial invocation without `PYTHONPATH=.` failed before loading the migration because the worktree package was not importable; the corrected invocation passed.

## Self-Review

- All new database table names use the `wechat_mp_` prefix.
- WeChat assets are modeled in `wechat_mp_assets`; no Xiaohongshu pipeline model or table is changed.
- The default illustration skill is `xiaomao-illustrations` in article creation and the relevant persistence models.
- Migration indexes cover every applicable `user_id`, `article_id`, `account_id`, `prompt_id`, `draft_sync_id`, and `status` column.
- `git diff --check` passed.
- No concerns identified.
