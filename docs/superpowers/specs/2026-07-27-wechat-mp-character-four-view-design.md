# WeChat MP Character Four-View Design

## Goal

Every WeChat MP illustration character, including the built-in `xiaomao-illustrations` character, has four confirmed visual reference assets: front, back, left, and right. Article image generation uses those confirmed assets as reference images and the character's fixed prompt so the character remains visually consistent.

## User Flow

1. A new character starts in `draft` state with its fixed character prompt.
2. The character library shows four required view slots: front, back, left, and right.
3. The user generates or replaces each view independently. Each generated view is saved as a character-view AI asset and displayed in its matching slot.
4. The user explicitly confirms each view. Replacing a view clears only that view's confirmation.
5. A character becomes `confirmed` only when all four slots contain a confirmed asset.
6. The writer can select only confirmed characters. Existing articles using an unconfirmed character remain editable but image generation is blocked with a direct link to the character library.
7. The editable image prompt supports `@形象名`. Typing `@` opens autocomplete for confirmed saved characters. Each prompt supports one primary mentioned character; selecting a mention replaces the article's default character for that image only.
8. During cover or inline image generation, the backend resolves the mentioned character's confirmed four-view assets, or the article's selected character when there is no mention, and sends their public URLs as provider reference images. The user does not need to select individual reference images again.

## Data Model

Add `wechat_mp_character_views` with one row per character and view direction:

- `character_id`, `user_id`, `view` (`front`, `back`, `left`, `right`), `prompt`, `file_path`, `public_url`, `model_name`, `status` (`draft`, `confirmed`), and timestamps.
- A unique constraint on `(character_id, view)` makes replacement an update rather than a second active slot.
- `WechatMpIllustrationCharacter.status` changes from the current always-active state to `draft` or `confirmed` for custom characters and the built-in small-cat virtual character.
- The built-in small cat receives a persisted system-owned character record during migration/bootstrap so it uses the same asset and confirmation workflow as custom characters.
- `WechatMpImagePrompt` stores an optional `character_id` resolved from its selected `@形象名`; this makes a generated image reproducible even if character names later change.

The four view images are independent AI assets held by this table because existing `wechat_mp_assets` requires an article ID and represents article content. Character views are global reusable assets, not article assets.

## Generation Contract

Each view prompt is built from the fixed character prompt plus a non-rendered direction constraint, for example "same character, left profile, full body, neutral pose". The request includes all already confirmed reference views when regenerating a missing view, so later views preserve the first accepted appearance.

Article image generation changes the provider body to include the four resolved public URLs as `reference_images`. The selected character's fixed prompt remains in the text prompt. If a prompt contains an unknown, unconfirmed, or ambiguous `@` mention, generation fails before charging or creating an article asset. If the configured provider cannot accept reference images, generation also fails rather than silently making an inconsistent text-only image.

## API And UI

- `GET /platforms/wechat-mp/illustration-characters` returns character confirmation state and four view records with public URLs.
- `POST /.../{character_id}/views/{view}/generate` generates or replaces one view.
- `POST /.../{character_id}/views/{view}/confirm` confirms a generated view.
- The character library shows a fixed four-card preview grid, view status, generate/regenerate, confirm, and replace actions.
- The writer's character selector labels unavailable characters as "待确认四视图" and disables them.
- The writer prompt editor offers `@` autocomplete. The selected primary character is rendered as a removable mention chip and saved as the prompt's `character_id`.
- The generation endpoint verifies character ownership and full four-view confirmation server-side; the browser cannot bypass it.

## Migration And Safety

- Existing custom characters start as `draft` without views.
- The currently selected built-in small cat starts as `draft` until its four views are generated and confirmed.
- Existing generated article images and historical drafts are unchanged.
- No image is deleted automatically when a view is replaced; its former file remains in storage for audit and recovery.
- All new endpoints are owner-scoped and return `404` for cross-user resources.

## Tests

- A character cannot become confirmed until all four directions have individually confirmed assets.
- Replacing a confirmed view returns the character to `draft`.
- Article generation sends exactly four character reference URLs in stable front/back/left/right order.
- Unconfirmed characters are rejected before an image-provider call.
- An `@` mention resolves to the saved confirmed character and overrides the article default for that one image.
- An unknown or unconfirmed `@` mention is rejected before an image-provider call.
- Cross-user view generation and confirmation return `404`.
