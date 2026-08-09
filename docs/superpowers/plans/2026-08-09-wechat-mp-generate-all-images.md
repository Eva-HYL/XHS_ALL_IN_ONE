# WeChat MP Generate All Images Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one button that appends every eligible WeChat MP inline-image prompt to the existing serial image queue.

**Architecture:** Keep queue execution in `WechatMpWriterPage` and reuse `runImageQueue` unchanged. Add pure eligibility helpers derived from the current prompt, asset, active ID, and queue state; the batch handler appends eligible IDs in prompt order and starts the existing worker once.

**Tech Stack:** React, TypeScript, Ant Design, existing Python source-contract tests, Vite.

## Global Constraints

- Do not add a backend endpoint, database migration, persistent batch job, or parallel image generation.
- Skip generated, ignored, `none`, active, queued, and already-asset-backed prompts.
- Allow `prompt_ready` and `failed` prompts.
- Preserve page order and prevent duplicate queue IDs.
- Only the active prompt card shows loading; queued cards keep the existing queued state.
- A failed image must not stop later queue items.
- Cover generation is not part of this batch.

---

### Task 1: Batch Enqueue Eligible Inline Images

**Files:**
- Modify: `frontend/src/pages/platforms/wechat-mp/writer-page.tsx`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:**
- Consumes: `prompts: WechatMpImagePrompt[]`, `assets: WechatMpAsset[]`, `activeImagePromptId: number | null`, `imageQueueRef.current: number[]`, and existing `runImageQueue(): Promise<void>`.
- Produces: `isPromptImageComplete(prompt): boolean`, `eligibleImagePrompts: WechatMpImagePrompt[]`, and `enqueueAllImages(): void` inside `WechatMpWriterPage`.

- [ ] **Step 1: Write the failing source-contract test**

Append this test near the existing writer queue tests in `tests/backend/test_wechat_mp.py`:

```python
def test_wechat_writer_can_enqueue_all_missing_inline_images_serially():
    source = Path("frontend/src/pages/platforms/wechat-mp/writer-page.tsx").read_text(encoding="utf-8")

    assert "function enqueueAllImages()" in source
    assert "eligibleImagePrompts" in source
    assert 'prompt.status !== "ignored"' in source
    assert 'prompt.status !== "generated"' in source
    assert 'prompt.skill_name !== "none"' in source
    assert "imageQueueRef.current.includes(prompt.id)" in source
    assert "void runImageQueue()" in source
    assert "一键生成全部正文图片" in source
    assert "正在按队列生成" in source
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py::test_wechat_writer_can_enqueue_all_missing_inline_images_serially
```

Expected: FAIL because `enqueueAllImages` and the button text do not exist.

- [ ] **Step 3: Implement eligibility and batch enqueue**

In `WechatMpWriterPage`, immediately before `runImageQueue`, derive completed and eligible prompts:

```tsx
  function isPromptImageComplete(prompt: WechatMpImagePrompt) {
    return prompt.status === "generated"
      || assets.some((asset) => asset.prompt_id === prompt.id && asset.role !== "cover");
  }

  const eligibleImagePrompts = prompts.filter((prompt) =>
    prompt.skill_name !== "none"
    && prompt.status !== "ignored"
    && prompt.status !== "generated"
    && !isPromptImageComplete(prompt)
    && activeImagePromptId !== prompt.id
    && !imageQueueRef.current.includes(prompt.id)
  );
```

Immediately after `enqueueImage`, add the handler. It must preserve prompt order and start the worker only after all IDs are appended:

```tsx
  function enqueueAllImages() {
    const promptIds = eligibleImagePrompts.map((prompt) => prompt.id);
    if (promptIds.length === 0) return;
    imageQueueRef.current = [...imageQueueRef.current, ...promptIds];
    setImageQueue([...imageQueueRef.current]);
    setNotice(`已将 ${promptIds.length} 张正文配图加入串行生成队列。`);
    void runImageQueue();
  }
```

- [ ] **Step 4: Add the batch button and dynamic state**

Under the image pricing text and above the cover card, render:

```tsx
          <Button
            type="primary"
            icon={<PictureOutlined />}
            disabled={eligibleImagePrompts.length === 0}
            onClick={enqueueAllImages}
          >
            {activeImagePromptId !== null || imageQueue.length > 0
              ? `正在按队列生成（剩余 ${imageQueue.length}）`
              : `一键生成全部正文图片（${eligibleImagePrompts.length}）`}
          </Button>
```

Do not set `loading` on this global button because the active prompt card is the only loading indicator. Keep it disabled when no additional prompts can be appended.

- [ ] **Step 5: Run the focused test and verify GREEN**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py::test_wechat_writer_can_enqueue_all_missing_inline_images_serially \
  tests/backend/test_wechat_mp.py::test_wechat_mp_writer_shows_inline_generated_images_next_to_prompts
```

Expected: `2 passed`.

- [ ] **Step 6: Run writer regression and frontend build**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py -k 'wechat_writer or image_queue or inline_generated_images'
cd frontend && npm run build
```

Expected: all selected tests pass and Vite exits with code 0.

- [ ] **Step 7: Commit implementation**

```bash
git add frontend/src/pages/platforms/wechat-mp/writer-page.tsx tests/backend/test_wechat_mp.py
git commit -m "feat: generate all wechat inline images"
```
