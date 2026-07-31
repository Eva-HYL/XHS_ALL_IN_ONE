# WeChat MP Character Mention Prompts Design

## Goal

Replace repeated character descriptions in WeChat MP cover and inline image prompts with a stable, editable character reference:

```text
主角：@小猫生图
```

The UI exposes the referenced character's full description on hover. Image generation still receives the complete character prompt and the four confirmed reference views.

## Scope

- Rename the built-in character display name from `小猫插画` to `小猫生图`.
- Add the character reference to generated cover prompts and inline prompts.
- Support the same `主角：@形象名` format for user-created characters.
- Convert existing cover briefs and image prompts to the reference format.
- Preserve existing generated images and assets during conversion.
- Keep `none` mode free of character references.

## Stored Prompt Contract

Cover briefs and editable inline prompts store user-facing content, not expanded character instructions.

```text
主角：@小猫生图
具体画面：<cover or section scene description>
```

Rules:

- The character reference is the first non-empty line.
- A prompt contains at most one primary character reference.
- Regeneration preserves the selected article character.
- Selecting another confirmed character replaces the whole existing `主角：@...` line.
- Character descriptions, model names, aspect ratios, and four-view URLs are not copied into the stored prompt.

## Generation Data Flow

1. The text model receives the full selected character description as private generation context.
2. The text model returns only the scene or diagram description.
3. The application stores `主角：@形象名` plus the returned scene description.
4. Before cover or inline image generation, the backend parses the mention.
5. The backend resolves the mentioned character within the current user account.
6. The backend requires all four views to be confirmed.
7. The backend removes the character-reference line from the scene text.
8. The backend sends the image model the full character description, cleaned scene prompt, and four confirmed reference images.

This keeps editable prompts concise without weakening character consistency.

## Cover Behavior

- Article creation prefixes `cover_brief` with the selected character reference.
- The cover prompt is editable before generation.
- Cover generation resolves the mention instead of assuming the article default character.
- A manually selected confirmed character can override the article default.
- `none` mode retains a scene-only cover prompt and does not resolve a character anchor.

## Inline Prompt Behavior

- New and regenerated inline prompts start with the selected character reference.
- The text model must not repeat the full character description in its output.
- Manual character selection replaces the reference line instead of appending a loose `@name` token.
- Inline image generation expands the reference internally and stores the expanded prompt only on the generated asset audit record.

## UI

The cover and each inline prompt show a compact character badge above the textarea:

```text
主角：@小猫生图
```

Hovering the badge shows:

- Character name.
- Full character description.
- Four-view confirmation state.

The textarea retains the same plain-text reference so copied prompts remain meaningful. A native textarea cannot provide reliable substring hover behavior, so the badge is the explicit hover target.

## Existing Data Conversion

An idempotent production backfill converts existing records:

- For each non-`none` article, ensure `cover_brief` begins with its selected character reference.
- For each image prompt, resolve `character_id` first and `skill_name` second.
- Remove the known expanded character-description prefix when present.
- Ensure `prompt` and `editable_prompt` begin with the resolved reference.
- Do not modify `WechatMpAsset`, generated image files, article HTML, usage records, or costs.
- Re-running the backfill produces no additional changes.

## Error Handling

- Unknown mention: reject generation with a clear “mentioned character was not found” error.
- Multiple mentions: reject generation; one prompt supports one primary character.
- Unconfirmed character: reject generation and direct the user to confirm all four views.
- Missing view file: reject generation even if the database record says confirmed.
- `none` mode: ignore character parsing and do not generate inline images.

## Verification

- Unit tests verify built-in and custom mention formatting.
- Unit tests verify full character descriptions are absent from stored prompts.
- Unit tests verify mention parsing removes the complete `主角：@...` line.
- Cover and inline generation tests verify full character context and four reference images reach the image model.
- Frontend source tests verify both cover and inline prompt badges use `Tooltip`.
- Backfill tests verify conversion is idempotent and leaves existing assets unchanged.
- Production verification checks the current account's converted prompts, hover description, and one cover plus one inline generation path.
