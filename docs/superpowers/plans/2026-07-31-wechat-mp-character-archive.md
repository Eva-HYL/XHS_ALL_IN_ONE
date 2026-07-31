# WeChat MP Character Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe delete action that archives user-created WeChat MP characters without breaking historical articles or deleting four-view assets.

**Architecture:** Add a nullable `archived_at` marker to the character model and expose an owner-scoped DELETE endpoint that sets it. Active character lists filter archived rows, while historical resolution functions intentionally continue resolving archived characters. The frontend removes archived cards immediately after a confirmed delete.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic, React, TypeScript, Ant Design, pytest.

## Global Constraints

- Only user-created custom characters may be archived.
- Built-in `xiaomao-illustrations` and virtual `none` cannot be archived.
- Archiving must not delete character rows, four-view rows, or image files.
- Archived characters are hidden from management and new-article selection lists.
- Historical resolution by `skill_name` or `character_id` must continue to work.
- Owner scoping returns `404` for missing, foreign, or already archived characters.
- The migration must extend Alembic head `df9e7f5d9f3a`.

---

## File Structure

- `backend/alembic/versions/a4c7e9d2f1b0_archive_wechat_mp_characters.py`: adds and removes `archived_at`.
- `backend/app/models/wechat_mp.py`: declares the nullable archive timestamp.
- `backend/app/services/wechat_mp_character_service.py`: filters active lists and performs owner-scoped archive updates.
- `backend/app/api/platforms/wechat_mp/characters.py`: exposes the DELETE endpoint.
- `frontend/src/lib/api.ts`: provides the typed archive request.
- `frontend/src/pages/platforms/wechat-mp/characters-page.tsx`: renders confirmation and per-card deletion state.
- `tests/backend/test_wechat_mp.py`: covers persistence, isolation, historical compatibility, and frontend source contracts.

### Task 1: Backend Character Archive Contract

**Files:**
- Create: `backend/alembic/versions/a4c7e9d2f1b0_archive_wechat_mp_characters.py`
- Modify: `backend/app/models/wechat_mp.py`
- Modify: `backend/app/services/wechat_mp_character_service.py`
- Modify: `backend/app/api/platforms/wechat_mp/characters.py`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:**
- Produces: `archive_illustration_character(db: Session, user_id: int, character_id: int) -> None`
- Produces: `DELETE /api/platforms/wechat-mp/illustration-characters/{character_id}` returning `204`
- Preserves: `resolve_confirmed_character_anchor(...)` behavior for archived historical characters.

- [ ] **Step 1: Write failing backend tests**

Add tests that create a custom character with four confirmed view rows, call DELETE, and assert:

```python
response = client.delete(
    f"/api/platforms/wechat-mp/illustration-characters/{character_id}",
    headers=auth_headers,
)
assert response.status_code == 204
assert response.content == b""
assert all(item["id"] != character_id for item in client.get(
    "/api/platforms/wechat-mp/illustration-characters",
    headers=auth_headers,
).json())

session = session_factory()
character = session.get(WechatMpIllustrationCharacter, character_id)
assert character.archived_at is not None
assert session.query(WechatMpCharacterView).filter_by(character_id=character_id).count() == 4
resolved, urls = resolve_confirmed_character_anchor(
    session, user_id=character.user_id, character_id=character_id,
)
assert resolved.id == character_id
assert len(urls) == 4
```

Add separate assertions that deleting the built-in character returns `400`, deleting another user's character returns `404`, and deleting an already archived character returns `404`.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py -k 'archive_wechat_mp_character'
```

Expected: FAIL because the DELETE route and `archived_at` field do not exist.

- [ ] **Step 3: Add the Alembic migration and model field**

Create revision `a4c7e9d2f1b0` with:

```python
revision = "a4c7e9d2f1b0"
down_revision = "df9e7f5d9f3a"

def upgrade() -> None:
    op.add_column(
        "wechat_mp_illustration_characters",
        sa.Column("archived_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_wechat_mp_illustration_characters_archived_at",
        "wechat_mp_illustration_characters",
        ["archived_at"],
    )

def downgrade() -> None:
    op.drop_index(
        "ix_wechat_mp_illustration_characters_archived_at",
        table_name="wechat_mp_illustration_characters",
    )
    op.drop_column("wechat_mp_illustration_characters", "archived_at")
```

Add to `WechatMpIllustrationCharacter`:

```python
archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
```

- [ ] **Step 4: Implement archive service behavior**

Filter `list_illustration_characters()` with:

```python
WechatMpIllustrationCharacter.archived_at.is_(None)
```

Add:

```python
def archive_illustration_character(
    db: Session, user_id: int, character_id: int
) -> None:
    character = db.scalar(select(WechatMpIllustrationCharacter).where(
        WechatMpIllustrationCharacter.id == character_id,
        WechatMpIllustrationCharacter.user_id == user_id,
        WechatMpIllustrationCharacter.archived_at.is_(None),
    ))
    if character is None:
        raise LookupError("WeChat MP character not found")
    if character.skill_name == XIAOMAO_SKILL_NAME:
        raise ValueError("Built-in WeChat MP character cannot be deleted")
    character.archived_at = datetime.utcnow()
    db.commit()
```

Do not add archive filters to `get_owned_character()`, `resolve_character_prompt()`, or `resolve_confirmed_character_anchor()`.

- [ ] **Step 5: Add the DELETE route**

Add:

```python
@router.delete("/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_character(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        archive_illustration_character(db, current_user.id, character_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except LookupError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
```

Import `Response` and `archive_illustration_character`.

- [ ] **Step 6: Run backend tests and verify GREEN**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py -k 'archive_wechat_mp_character or wechat_mp_character'
```

Expected: all selected tests PASS.

- [ ] **Step 7: Verify migration topology**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/alembic \
  -c backend/alembic.ini heads
```

Expected: exactly `a4c7e9d2f1b0 (head)`.

- [ ] **Step 8: Commit backend archive support**

```bash
git add backend/alembic/versions/a4c7e9d2f1b0_archive_wechat_mp_characters.py \
  backend/app/models/wechat_mp.py \
  backend/app/services/wechat_mp_character_service.py \
  backend/app/api/platforms/wechat_mp/characters.py \
  tests/backend/test_wechat_mp.py
git commit -m "feat: archive wechat mp characters"
```

### Task 2: Character Delete UI

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/pages/platforms/wechat-mp/characters-page.tsx`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:**
- Consumes: `DELETE /platforms/wechat-mp/illustration-characters/{characterId}`.
- Produces: `archiveWechatMpIllustrationCharacter(characterId: number): Promise<void>`.

- [ ] **Step 1: Write failing frontend contract test**

Add a source-level contract test:

```python
def test_wechat_mp_character_page_exposes_custom_archive_action():
    source = Path(
        "frontend/src/pages/platforms/wechat-mp/characters-page.tsx"
    ).read_text(encoding="utf-8")
    api_source = Path("frontend/src/lib/api.ts").read_text(encoding="utf-8")

    assert "archiveWechatMpIllustrationCharacter" in api_source
    assert "Popconfirm" in source
    assert "DeleteOutlined" in source
    assert "character.is_builtin" in source
    assert "删除后不再出现在形象库，但历史文章仍保留" in source
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py::test_wechat_mp_character_page_exposes_custom_archive_action
```

Expected: FAIL because the API function and UI controls do not exist.

- [ ] **Step 3: Add the typed API function**

Add to `frontend/src/lib/api.ts`:

```typescript
export async function archiveWechatMpIllustrationCharacter(characterId: number): Promise<void> {
  await http.delete(`/platforms/wechat-mp/illustration-characters/${characterId}`);
}
```

- [ ] **Step 4: Implement per-card archive interaction**

Import `DeleteOutlined`, `Popconfirm`, and `archiveWechatMpIllustrationCharacter`. Add:

```typescript
const [deletingId, setDeletingId] = useState<number | null>(null);

async function archiveCharacter(character: WechatMpIllustrationCharacter) {
  if (!character.id || character.is_builtin) return;
  setDeletingId(character.id);
  setError(null);
  try {
    await archiveWechatMpIllustrationCharacter(character.id);
    setCharacters((items) => items.filter((item) => item.id !== character.id));
    setNotice(`形象「${character.name}」已删除，历史文章不受影响。`);
  } catch {
    setError(`形象「${character.name}」删除失败。`);
  } finally {
    setDeletingId(null);
  }
}
```

For custom character cards only, render:

```tsx
<Popconfirm
  title={`删除形象「${character.name}」？`}
  description="删除后不再出现在形象库，但历史文章仍保留。"
  onConfirm={() => void archiveCharacter(character)}
>
  <Button
    danger
    size="small"
    icon={<DeleteOutlined />}
    loading={deletingId === character.id}
  >
    删除
  </Button>
</Popconfirm>
```

- [ ] **Step 5: Verify frontend test and production build**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py::test_wechat_mp_character_page_exposes_custom_archive_action
npm run build --prefix frontend
```

Expected: test PASS and Vite production build exits `0`.

- [ ] **Step 6: Commit frontend archive interaction**

```bash
git add frontend/src/lib/api.ts \
  frontend/src/pages/platforms/wechat-mp/characters-page.tsx \
  tests/backend/test_wechat_mp.py
git commit -m "feat: add wechat character delete action"
```

### Task 3: Regression, Deployment, and Runtime Verification

**Files:**
- Verify only; no planned source changes.

**Interfaces:**
- Consumes: migration head `a4c7e9d2f1b0`, archive endpoint, and frontend archive action.
- Produces: deployed Atlas container with verified schema and health.

- [ ] **Step 1: Run bounded backend regression**

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py -k 'wechat_mp_character'
git diff --check
```

Expected: all selected tests PASS and no whitespace errors.

- [ ] **Step 2: Push the feature branch**

```bash
git push origin codex/wechat-mp-auto-publish
```

- [ ] **Step 3: Merge and deploy on Atlas**

```bash
ssh Atlas 'cd /root/xhs-all-in-one && git fetch eva-fork codex/wechat-mp-auto-publish'
ssh Atlas 'cd /root/xhs-all-in-one && git merge --no-edit eva-fork/codex/wechat-mp-auto-publish'
ssh Atlas 'cd /root/xhs-all-in-one && docker compose up -d --build app'
```

- [ ] **Step 4: Verify runtime migration and health**

```bash
ssh Atlas 'docker exec -e PYTHONPATH=/app -e DATABASE_URL=sqlite:////app/data/spider_xhs.db spider-xhs alembic -c backend/alembic.ini upgrade head'
ssh Atlas 'docker exec spider-xhs python -c "import sqlite3; db=sqlite3.connect(\"/app/data/spider_xhs.db\"); print(db.execute(\"select version_num from alembic_version\").fetchone()); print([row[1] for row in db.execute(\"pragma table_info(wechat_mp_illustration_characters)\") if row[1] == \"archived_at\"])"'
ssh Atlas 'docker inspect spider-xhs --format "{{.State.Status}} {{.State.Health.Status}}"'
ssh Atlas 'curl -fsS http://127.0.0.1:8000/api/health'
```

`init_db()` runs migrations against the configured production database during container startup. The explicit Alembic command is an idempotent verification path and must override the development URL from `backend/alembic.ini`.

Expected:

```text
('a4c7e9d2f1b0',)
['archived_at']
running healthy
{"status":"ok","service":"spider-xhs"}
```
