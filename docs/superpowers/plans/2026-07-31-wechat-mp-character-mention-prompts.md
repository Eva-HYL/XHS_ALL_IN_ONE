# WeChat MP Character Mention Prompts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store and display concise `主角：@形象名` references in WeChat MP cover and inline prompts while expanding them to full character instructions and four confirmed views only during image generation.

**Architecture:** Character-reference formatting and parsing live in `wechat_mp_character_service.py`. Writer and prompt services persist the reference form; cover and inline image services resolve it to an owned character, full prompt, and four-view anchor at execution time. The React writer displays a tooltip badge sourced from the character library, and an idempotent backfill converts existing prompts without touching generated assets.

**Tech Stack:** FastAPI, SQLAlchemy 2, SQLite, React, TypeScript, Ant Design, pytest, Vite.

## Global Constraints

- The built-in character display name is exactly `小猫生图`.
- Stored cover and inline prompts use `主角：@形象名` as the first non-empty line.
- Stored prompts must not repeat the expanded character description.
- Actual image calls still receive the full character prompt and four confirmed reference images.
- One prompt supports at most one primary character mention.
- `none` mode does not add or resolve a character mention.
- Existing generated images, article HTML, usage records, and costs are not modified by backfill.
- All production data conversion must be idempotent.

---

### Task 1: Character Mention Contract

**Files:**
- Modify: `backend/app/services/wechat_mp_character_service.py`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:**
- Produces: `XIAOMAO_CHARACTER_NAME = "小猫生图"`.
- Produces: `format_character_mention(character: WechatMpIllustrationCharacter) -> str`.
- Produces: `format_character_prompt(character: WechatMpIllustrationCharacter, scene_prompt: str) -> str`.
- Produces: `parse_character_mention(text: str) -> tuple[str | None, str]`.
- Produces: `resolve_character_by_skill(db: Session, *, user_id: int, skill_name: str) -> WechatMpIllustrationCharacter | None`.
- Updates: `resolve_prompt_character(...) -> tuple[WechatMpIllustrationCharacter | None, str]` to remove the complete mention line.

- [ ] **Step 1: Write failing contract tests**

Add tests that assert:

```python
def test_character_mention_formats_and_parses_the_full_reference_line():
    from backend.app.services.wechat_mp_character_service import (
        format_character_prompt,
        parse_character_mention,
    )

    character = WechatMpIllustrationCharacter(
        user_id=1,
        name="小猫生图",
        skill_name="xiaomao-illustrations",
        prompt="完整形象介绍",
    )
    stored = format_character_prompt(character, "小猫压住流程图")
    assert stored == "主角：@小猫生图\n具体画面：小猫压住流程图"
    assert parse_character_mention(stored) == ("小猫生图", "具体画面：小猫压住流程图")


def test_character_mention_rejects_multiple_primary_characters():
    from backend.app.services.wechat_mp_character_service import parse_character_mention

    with pytest.raises(ValueError, match="one primary"):
        parse_character_mention("主角：@小猫生图\n主角：@护士兔")
```

Extend the built-in character API assertion to require `name == "小猫生图"`.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py \
  -k 'character_mention or illustration_characters_are_user_managed'
```

Expected: failures because the constants and helpers do not exist and the built-in name is still `小猫插画`.

- [ ] **Step 3: Implement the minimal character-reference helpers**

Implement the exact behavior:

```python
XIAOMAO_CHARACTER_NAME = "小猫生图"
CHARACTER_MENTION_RE = re.compile(r"(?m)^[ \t]*主角[：:][ \t]*@([^\s@,，。；;：:（）()]+)[ \t]*$")


def format_character_mention(character: WechatMpIllustrationCharacter) -> str:
    return f"主角：@{character.name}"


def format_character_prompt(character: WechatMpIllustrationCharacter, scene_prompt: str) -> str:
    _, cleaned = parse_character_mention(scene_prompt)
    cleaned = cleaned.strip()
    if cleaned and not cleaned.startswith("具体画面："):
        cleaned = f"具体画面：{cleaned}"
    return "\n".join(part for part in (format_character_mention(character), cleaned) if part)


def parse_character_mention(text: str) -> tuple[str | None, str]:
    names = CHARACTER_MENTION_RE.findall(text)
    if len(set(names)) > 1:
        raise ValueError("Each prompt supports one primary @character mention")
    name = names[0] if names else None
    cleaned = CHARACTER_MENTION_RE.sub("", text).strip()
    return name, cleaned


def resolve_character_by_skill(
    db: Session,
    *,
    user_id: int,
    skill_name: str,
) -> WechatMpIllustrationCharacter | None:
    if skill_name == NONE_SKILL_NAME:
        return None
    if skill_name == XIAOMAO_SKILL_NAME:
        return ensure_builtin_character(db, user_id)
    return db.scalar(select(WechatMpIllustrationCharacter).where(
        WechatMpIllustrationCharacter.user_id == user_id,
        WechatMpIllustrationCharacter.skill_name == skill_name,
        WechatMpIllustrationCharacter.archived_at.is_(None),
    ))
```

Update `ensure_builtin_character()` to create and synchronize the built-in display name. Update `resolve_prompt_character()` to use `parse_character_mention()` and preserve the existing owner lookup and four-view validation.

- [ ] **Step 4: Run targeted tests**

Run the command from Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/wechat_mp_character_service.py tests/backend/test_wechat_mp.py
git commit -m "feat: add wechat character mention contract"
```

---

### Task 2: Persist Mentions and Expand Them During Generation

**Files:**
- Modify: `backend/app/services/wechat_mp_writer_service.py`
- Modify: `backend/app/services/wechat_mp_image_prompt_service.py`
- Modify: `backend/app/services/wechat_mp_image_service.py`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:**
- Consumes: `format_character_prompt`, `parse_character_mention`, and `resolve_prompt_character` from Task 1.
- Produces: cover briefs and inline `prompt`/`editable_prompt` values in reference form.
- Preserves: full expanded prompt only in `WechatMpAsset.prompt` for audit.

- [ ] **Step 1: Write failing article and prompt persistence tests**

Add assertions to article creation and prompt generation:

```python
assert data["cover_brief"] == "主角：@小猫生图\n具体画面：小猫压住一张计划表"
assert data[0]["editable_prompt"].startswith("主角：@小猫生图\n具体画面：")
assert "主角必须是一只胖胖慵懒" not in data[0]["editable_prompt"]
```

Add a regeneration test that verifies `_call_prompt_model` receives `db` and `user_id`, and the returned stored prompt retains `主角：@小猫生图`.

- [ ] **Step 2: Write failing image-call expansion tests**

For inline and cover generation, monkeypatch `_call_image_model` and assert:

```python
assert "主角：@小猫生图" not in captured["prompt"]
assert "主角必须是一只胖胖慵懒" in captured["prompt"]
assert "具体画面：" in captured["prompt"]
assert len(captured["reference_images"]) == 4
```

Also assert the created asset keeps the expanded prompt for audit while the article/prompt row keeps the mention form.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py \
  -k 'create_wechat_mp_article_generates or generate_prompts_defaults or regenerate_prompt or cover_uses or character_anchor'
```

Expected: cover and inline prompts contain old forms, and cover generation does not parse a mention.

- [ ] **Step 4: Store mention-form cover and inline prompts**

In `generate_wechat_article()`:

```python
character = resolve_character_by_skill(
    db,
    user_id=user_id,
    skill_name=request.illustration_skill or XIAOMAO_SKILL_NAME,
)
cover_brief = (
    format_character_prompt(character, result["cover_brief"])
    if character is not None
    else result["cover_brief"].strip()
)
```

In `_call_prompt_model()`, continue sending `build_skill_prompt()` to the model, but return:

```python
character = resolve_character_by_skill(db, user_id=user_id, skill_name=skill_name)
stored_prompt = (
    format_character_prompt(character, prompt)
    if character is not None
    else prompt
)
```

Pass `db` and `article.user_id` from `regenerate_image_prompt()` so regeneration uses the same character context.

- [ ] **Step 5: Expand references only at image-call time**

For inline images, retain the existing `resolve_prompt_character()` flow and build:

```python
effective_prompt = (
    f"{character.prompt}\n具体画面：{scene_prompt}"
    if character is not None
    else scene_prompt
)
```

For covers, call `resolve_prompt_character()` with `article.cover_brief`, resolve that character's confirmed anchor, and pass the cleaned scene plus full character prompt to `_call_image_model()`. Do not prepend `build_skill_prompt()` a second time.

- [ ] **Step 6: Run targeted tests**

Run the command from Step 3. Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add \
  backend/app/services/wechat_mp_writer_service.py \
  backend/app/services/wechat_mp_image_prompt_service.py \
  backend/app/services/wechat_mp_image_service.py \
  tests/backend/test_wechat_mp.py
git commit -m "feat: use character mentions in wechat prompts"
```

---

### Task 3: Add Hoverable Character Badges to Cover and Inline Editors

**Files:**
- Modify: `frontend/src/pages/platforms/wechat-mp/writer-page.tsx`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:**
- Consumes: `WechatMpIllustrationCharacter.name`, `.prompt`, `.is_available`, prompt `.character_id`, and `.skill_name`.
- Produces: hoverable `Tooltip` badges and exact mention-line replacement in the editor.

- [ ] **Step 1: Write failing frontend source assertions**

Add:

```python
def test_wechat_writer_shows_hoverable_character_mentions_for_cover_and_inline_prompts():
    source = Path("frontend/src/pages/platforms/wechat-mp/writer-page.tsx").read_text()

    assert "Tooltip" in source
    assert "character.prompt" in source
    assert "主角：@" in source
    assert "replaceCharacterMention" in source
    assert source.count("characterMentionBadge") >= 2
```

- [ ] **Step 2: Run the source test and verify RED**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py \
  -k hoverable_character_mentions
```

Expected: FAIL because no tooltip badge exists.

- [ ] **Step 3: Implement mention helpers and badges**

Import `Tooltip`. Add:

```tsx
function replaceCharacterMention(text: string, name: string): string {
  const scene = text.replace(/^[ \t]*主角[：:][ \t]*@[^\s@,，。；;：:（）()]+[ \t]*$/gm, "").trim();
  return `主角：@${name}${scene ? `\n${scene}` : ""}`;
}
```

Resolve the character from `character_id`, then `skill_name`, then the mention text. Render:

```tsx
const characterMentionBadge = character ? (
  <Tooltip title={<div><strong>{character.name}</strong><div>{character.prompt}</div></div>}>
    <Tag color={character.is_available ? "blue" : "gold"}>
      主角：@{character.name}
    </Tag>
  </Tooltip>
) : null;
```

Show the badge above the cover textarea and above every inline textarea. Change character selection to call `replaceCharacterMention()` instead of appending `@name`.

- [ ] **Step 4: Build and test**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py \
  -k 'hoverable_character_mentions or character_page'
cd frontend && npm run build
```

Expected: tests PASS and Vite build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/platforms/wechat-mp/writer-page.tsx tests/backend/test_wechat_mp.py
git commit -m "feat: show hoverable wechat character mentions"
```

---

### Task 4: Idempotent Existing-Data Backfill

**Files:**
- Create: `backend/app/services/wechat_mp_character_mention_backfill.py`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:**
- Produces: `backfill_character_mentions(db: Session, *, user_id: int | None = None) -> dict[str, int]`.
- Consumes: character formatting and lookup helpers from Task 1.

- [ ] **Step 1: Write a failing idempotency and preservation test**

Create an article, prompt, and generated asset using the expanded character description. Call backfill twice and assert:

```python
first = backfill_character_mentions(session, user_id=owner.id)
second = backfill_character_mentions(session, user_id=owner.id)

assert first == {"articles_updated": 1, "prompts_updated": 1}
assert second == {"articles_updated": 0, "prompts_updated": 0}
assert article.cover_brief.startswith("主角：@小猫生图")
assert prompt.editable_prompt.startswith("主角：@小猫生图")
assert "主角必须是一只胖胖慵懒" not in prompt.editable_prompt
assert session.get(WechatMpAsset, asset.id).public_url == original_public_url
assert article.html_body == original_html
assert article.cost_estimate == original_cost
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py \
  -k character_mention_backfill
```

Expected: FAIL because the service does not exist.

- [ ] **Step 3: Implement the backfill**

The function must:

- Query non-`none` articles, optionally scoped by `user_id`.
- Resolve each article character from `illustration_skill`.
- Normalize `cover_brief` with `format_character_prompt()`.
- Query prompts and resolve by `character_id` first, then `skill_name`.
- Remove either the current character prompt or the legacy built-in prompt prefix before formatting.
- Update both `prompt` and `editable_prompt`.
- Commit once and return exact update counts.
- Never query or mutate `WechatMpAsset`, article HTML, usage, or cost fields.

- [ ] **Step 4: Run targeted and combined backend tests**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py \
  -k 'character_mention or generate_prompts or generate_cover or character_anchor'
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/wechat_mp_character_mention_backfill.py tests/backend/test_wechat_mp.py
git commit -m "feat: backfill wechat character mentions"
```

---

### Task 5: Release and Production Verification

**Files:**
- Modify only if verification finds a defect in files from Tasks 1-4.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: deployed Atlas release and converted production records.

- [ ] **Step 1: Run final local verification**

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py \
  -k 'character_mention or illustration_characters or generate_prompts or generate_cover or character_anchor'
cd frontend && npm run build
git diff --check
```

Expected: targeted tests PASS, frontend build succeeds, and `git diff --check` is clean.

- [ ] **Step 2: Push the feature branch**

```bash
git push origin codex/wechat-mp-auto-publish
```

- [ ] **Step 3: Merge and rebuild Atlas**

```bash
ssh Atlas 'cd /root/xhs-all-in-one &&
  git fetch eva-fork codex/wechat-mp-auto-publish &&
  git merge --no-edit FETCH_HEAD &&
  docker compose up -d --build app'
```

- [ ] **Step 4: Run the production backfill**

Run `backfill_character_mentions()` inside `spider-xhs` for user `huangyilundada@gmail.com`. Record the returned article and prompt update counts. Run it a second time and require both counts to be zero.

- [ ] **Step 5: Verify production behavior**

Verify:

- Container state is `running healthy`.
- Built-in character API returns `name == "小猫生图"`.
- Current account cover briefs and inline prompts begin with `主角：@小猫生图`.
- Stored prompts do not contain the expanded character description.
- Existing asset row counts and files remain unchanged by backfill.
- Targeted tests prove both cover and inline image calls resolve four confirmed references; production verification does not trigger additional paid image calls.
- The served frontend bundle contains the tooltip badge and mention replacement code.

- [ ] **Step 6: Report release evidence**

Report commit SHAs, targeted test count, frontend build result, production backfill counts, container health, and confirmation that production verification incurred no new image-generation cost.
