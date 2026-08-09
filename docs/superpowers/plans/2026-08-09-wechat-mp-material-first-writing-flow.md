# 公众号素材优先写作流程 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将公众号文章创建改为素材优先、无素材可用、自动生成可编辑写作简报并在同一页生成正文的五步流程。

**Architecture:** 在现有公众号文章路由下增加无状态写作简报接口，复用当前文本模型和素材归属加载逻辑，简报调用独立写入用量记录。前端新增纯函数管理来源有效性和简报过期状态，writer 页只替换文章创建前的 UI 与步骤编号，后续文章、提示词、生图和发布接口保持不变。

**Tech Stack:** FastAPI、Pydantic、SQLAlchemy、React 19、TypeScript、Ant Design、Node test runner、Pytest。

## Global Constraints

- 仅修改用户 fork `Eva-HYL/XHS_ALL_IN_ONE` 的 `codex/wechat-shotlist-atlas-integration` 分支。
- 素材归属必须按当前用户校验；不存在、删除或属于其他用户的素材返回 404。
- 没有素材时必须允许使用一句话想法生成简报和正文。
- 未选择素材且未输入想法时不得调用模型。
- 自动整理不得静默覆盖用户已经编辑的简报。
- 写作简报调用记录 `platform="wechat_mp"`、`step="prepare_writing_brief"`。
- 不新增数据库表或迁移，不改动文章编辑、提示词、生图、资产保存和发布契约。
- 所有生产代码遵循测试先行；每项测试必须先因缺少目标行为而失败。

---

### Task 1: 后端写作简报接口

**Files:**
- Modify: `backend/app/schemas/wechat_mp.py`
- Modify: `backend/app/services/wechat_mp_writer_service.py`
- Modify: `backend/app/api/platforms/wechat_mp/articles.py`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:**
- Consumes: `_load_selected_materials(db, user_id, material_ids)`、`_compose_source_material(manual_material, selected_materials)`、`resolve_wechat_mp_model(...)`、`record_text_usage(...)`。
- Produces: `WechatMpWritingBriefRequest`、`WechatMpWritingBriefResponse`、`prepare_wechat_writing_brief(...)`、`POST /api/platforms/wechat-mp/articles/writing-brief`。

- [ ] **Step 1: Write failing API tests for material and no-material briefs**

在 `tests/backend/test_wechat_mp.py` 增加：

```python
def test_prepare_wechat_writing_brief_uses_material_and_records_usage(api_client, auth_headers, monkeypatch):
    from backend.app.models import UsageRecord
    from backend.app.services import wechat_mp_writer_service as writer

    captured = {}

    def fake_call(*, idea, source_material, model_name, **kwargs):
        captured.update(idea=idea, source_material=source_material)
        return {
            "title": "范围管理高频考点",
            "topic": "梳理范围流程与易错关系",
            "target_reader": "软考考生",
            "tone": "清晰紧凑",
            "input_tokens": 40,
            "output_tokens": 20,
            "model_name": model_name,
        }

    monkeypatch.setattr(writer, "_call_writing_brief_model", fake_call)
    client, session_factory = api_client
    material = client.post(
        "/api/platforms/wechat-mp/materials",
        json={"title": "范围资料", "content": "规划→收集→定义→WBS→确认→控制"},
        headers=auth_headers,
    ).json()
    response = client.post(
        "/api/platforms/wechat-mp/articles/writing-brief",
        json={"material_ids": [material["id"]], "idea": "突出考试区别"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["title"] == "范围管理高频考点"
    assert "范围资料" in captured["source_material"]
    assert captured["idea"] == "突出考试区别"
    session = session_factory()
    try:
        assert session.query(UsageRecord).filter_by(platform="wechat_mp", step="prepare_writing_brief").count() == 1
    finally:
        session.close()


def test_prepare_wechat_writing_brief_accepts_idea_without_material(api_client, auth_headers, monkeypatch):
    from backend.app.services import wechat_mp_writer_service as writer

    monkeypatch.setattr(writer, "_call_writing_brief_model", lambda **kwargs: {
        "title": "一个人的阅读史",
        "topic": "从第一本推理小说谈阅读记忆",
        "target_reader": "普通读者",
        "tone": "克制",
        "input_tokens": 10,
        "output_tokens": 10,
        "model_name": kwargs["model_name"],
    })
    client, _ = api_client
    response = client.post(
        "/api/platforms/wechat-mp/articles/writing-brief",
        json={"material_ids": [], "idea": "写我读的第一本推理小说"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["topic"] == "从第一本推理小说谈阅读记忆"


def test_prepare_wechat_writing_brief_rejects_empty_source(api_client, auth_headers):
    client, _ = api_client
    response = client.post(
        "/api/platforms/wechat-mp/articles/writing-brief",
        json={"material_ids": [], "idea": "   "},
        headers=auth_headers,
    )
    assert response.status_code == 400
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py::test_prepare_wechat_writing_brief_uses_material_and_records_usage \
  tests/backend/test_wechat_mp.py::test_prepare_wechat_writing_brief_accepts_idea_without_material \
  tests/backend/test_wechat_mp.py::test_prepare_wechat_writing_brief_rejects_empty_source
```

Expected: FAIL because `/articles/writing-brief` and `_call_writing_brief_model` do not exist.

- [ ] **Step 3: Add request and response schemas**

在 `backend/app/schemas/wechat_mp.py` 增加：

```python
class WechatMpWritingBriefRequest(BaseModel):
    material_ids: list[int] = Field(default_factory=list)
    idea: str = Field(default="", max_length=10000)


class WechatMpWritingBriefResponse(BaseModel):
    title: str
    topic: str
    target_reader: str
    tone: str
    cost_estimate: dict
```

- [ ] **Step 4: Implement the brief service**

在 `backend/app/services/wechat_mp_writer_service.py` 增加 `_WRITING_BRIEF_PROMPT`、`_call_writing_brief_model(...)` 和：

```python
def prepare_wechat_writing_brief(*, db: Session, user_id: int, material_ids: list[int], idea: str) -> dict[str, Any]:
    from backend.app.services.wechat_mp_model_service import resolve_wechat_mp_model

    selected_materials = _load_selected_materials(db, user_id, material_ids)
    source_material = _compose_source_material("", selected_materials)
    normalized_idea = idea.strip()
    if not normalized_idea and not source_material.strip():
        raise WechatMpWritingBriefSourceError("请先选择素材或输入一句话想法")
    model = resolve_wechat_mp_model(db=db, user_id=user_id, model_type="text")
    result = _call_writing_brief_model(
        idea=normalized_idea,
        source_material=source_material,
        model_name=model.model_name,
        base_url=model.base_url,
        api_key=model.api_key,
    )
    usage = record_text_usage(
        db=db,
        user_id=user_id,
        pipeline_run_id=None,
        step="prepare_writing_brief",
        model=result["model_name"],
        input_tokens=int(result["input_tokens"]),
        output_tokens=int(result["output_tokens"]),
        platform="wechat_mp",
        resource_type="wechat_mp_writing_brief",
        resource_id=None,
    )
    return {
        "title": result["title"].strip()[:255],
        "topic": result["topic"].strip(),
        "target_reader": result["target_reader"].strip(),
        "tone": result["tone"].strip(),
        "cost_estimate": {"currency": "CNY", "total_yuan": str(usage.cost_yuan), "calls": 1},
    }
```

`_call_writing_brief_model` 使用 `/chat/completions`、`response_format={"type": "json_object"}`，只接受包含四个字符串字段的 JSON；模型或解析错误继续抛 `ValueError`。`WechatMpWritingBriefSourceError` 只表示输入来源无效。

- [ ] **Step 5: Register the static endpoint before `/{article_id}`**

在 `backend/app/api/platforms/wechat_mp/articles.py` 的动态文章路由之前增加：

```python
@router.post("/writing-brief", response_model=WechatMpWritingBriefResponse)
def prepare_writing_brief(...):
    if not payload.material_ids and not payload.idea.strip():
        raise HTTPException(status_code=400, detail="请先选择素材或输入一句话想法")
    try:
        return prepare_wechat_writing_brief(...)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WechatMpWritingBriefSourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
```

- [ ] **Step 6: Run targeted tests and verify GREEN**

Run the command from Step 2. Expected: `3 passed`.

- [ ] **Step 7: Commit Task 1**

```bash
git add backend/app/schemas/wechat_mp.py backend/app/services/wechat_mp_writer_service.py backend/app/api/platforms/wechat_mp/articles.py tests/backend/test_wechat_mp.py
git commit -m "feat: add wechat writing brief endpoint"
```

### Task 2: 保留确认标题并修复恢复键

**Files:**
- Modify: `backend/app/services/wechat_mp_writer_service.py`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:**
- Consumes: `WechatMpArticleCreateRequest.title`。
- Produces: `_call_writer_model(*, title_hint: str, ...)`，文章响应标题始终等于去除首尾空白后的 `title_hint`。

- [ ] **Step 1: Write a failing title-preservation test**

修改 `test_create_wechat_mp_article_generates_markdown_html_and_usage` 的 fake seam，使其捕获 `title_hint`，并断言：

```python
assert captured["title_hint"] == "稳定输出"
assert data["title"] == "稳定输出"
```

保留 fake 模型返回不同标题 `会偷懒的人，反而更稳定`，证明服务端以已确认标题为准。

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py::test_create_wechat_mp_article_generates_markdown_html_and_usage
```

Expected: FAIL because `title_hint` is not passed and returned title is model title.

- [ ] **Step 3: Pass and enforce the confirmed title**

更新 `_WRITER_PROMPT`，明确 `title` 必须与输入 `title_hint` 一致；更新 `_call_writer_model` 签名与用户 JSON；在 `generate_wechat_article` 中传入 `request.title.strip()`，并在构造 ORM 前执行：

```python
result["title"] = request.title.strip()
```

- [ ] **Step 4: Run title and material article tests**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py::test_create_wechat_mp_article_generates_markdown_html_and_usage \
  tests/backend/test_wechat_mp.py::test_create_wechat_mp_article_can_use_material_library_items
```

Expected: `2 passed`.

- [ ] **Step 5: Commit Task 2**

```bash
git add backend/app/services/wechat_mp_writer_service.py tests/backend/test_wechat_mp.py
git commit -m "fix: preserve confirmed wechat article title"
```

### Task 3: 前端写作来源状态与 API 合同

**Files:**
- Create: `frontend/src/pages/platforms/wechat-mp/writing-flow.ts`
- Create: `frontend/tests/wechat-mp-writing-flow.test.ts`
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/package.json`

**Interfaces:**
- Produces: `hasWritingSource(materialIds, idea)`、`writingSourceFingerprint(materialIds, idea)`、`isWritingBriefReady(title, topic)`、`WECHAT_WRITER_STEPS`、`prepareWechatMpWritingBrief(payload)`。
- Consumes: `WechatMpWritingBriefRequest`、`WechatMpWritingBrief` 前端类型。

- [ ] **Step 1: Write failing pure behavior tests**

创建 `frontend/tests/wechat-mp-writing-flow.test.ts`：

```ts
import assert from "node:assert/strict";
import test from "node:test";

import {
  hasWritingSource,
  isWritingBriefReady,
  WECHAT_WRITER_STEPS,
  writingSourceFingerprint,
} from "../src/pages/platforms/wechat-mp/writing-flow.ts";

test("writing source accepts either selected materials or a nonblank idea", () => {
  assert.equal(hasWritingSource([1], ""), true);
  assert.equal(hasWritingSource([], " 一句话想法 "), true);
  assert.equal(hasWritingSource([], "   "), false);
});

test("source fingerprint is stable for the confirmed material order and normalized idea", () => {
  assert.equal(writingSourceFingerprint([3, 1], "  复习重点  "), "3,1|复习重点");
});

test("brief readiness requires editable title and topic", () => {
  assert.equal(isWritingBriefReady("标题", "主题"), true);
  assert.equal(isWritingBriefReady("", "主题"), false);
});

test("writer navigation contains the five simplified stages", () => {
  assert.deepEqual(WECHAT_WRITER_STEPS, [
    "选择素材与写作要求",
    "编辑与预览",
    "生成提示词",
    "编辑提示词并生图",
    "同步草稿/发布",
  ]);
});
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
cd frontend && node --test --experimental-strip-types tests/wechat-mp-writing-flow.test.ts
```

Expected: FAIL because `writing-flow.ts` does not exist.

- [ ] **Step 3: Implement pure helpers**

创建 `writing-flow.ts`，用 `trim()` 归一化 idea，保留已确认素材顺序；`isWritingBriefReady` 只检查非空标题和主题；导出五步常量。

- [ ] **Step 4: Add front-end request and response types**

在 `frontend/src/types/index.ts` 增加：

```ts
export type WechatMpWritingBriefRequest = { material_ids: number[]; idea: string };
export type WechatMpWritingBrief = {
  title: string;
  topic: string;
  target_reader: string;
  tone: string;
  cost_estimate: { currency: string; total_yuan: string; calls: number };
};
```

在 `frontend/src/lib/api.ts` 增加 `prepareWechatMpWritingBrief(payload)`，POST 到 `/platforms/wechat-mp/articles/writing-brief`。

- [ ] **Step 5: Register and run the front-end behavior test**

在 `frontend/package.json` 增加：

```json
"test:wechat-writing-flow": "node --test --experimental-strip-types tests/wechat-mp-writing-flow.test.ts"
```

Run: `cd frontend && npm run test:wechat-writing-flow`. Expected: `4 passed`.

- [ ] **Step 6: Commit Task 3**

```bash
git add frontend/src/pages/platforms/wechat-mp/writing-flow.ts frontend/tests/wechat-mp-writing-flow.test.ts frontend/src/types/index.ts frontend/src/lib/api.ts frontend/package.json
git commit -m "feat: add wechat writing brief client state"
```

### Task 4: 素材优先五步 writer UI

**Files:**
- Modify: `frontend/src/pages/platforms/wechat-mp/writer-page.tsx`
- Modify: `frontend/tests/wechat-mp-writing-flow.test.ts`
- Test: `tests/backend/test_wechat_mp.py`

**Interfaces:**
- Consumes: `prepareWechatMpWritingBrief`、`hasWritingSource`、`writingSourceFingerprint`、`isWritingBriefReady`、`WECHAT_WRITER_STEPS`。
- Produces: 置顶素材选择、无素材 idea 入口、内联写作简报、五步导航、同页正文生成。

- [ ] **Step 1: Add a failing writer source-contract test**

在 `frontend/tests/wechat-mp-writing-flow.test.ts` 读取 `writer-page.tsx`，断言生产页包含 `使用选中素材`、`智能补全写作简报`、`prepareWechatMpWritingBrief`，且不再包含 `下一步：生成文章` 和 `2. 生成文章`。先运行并确认因旧页面仍存在而失败。

- [ ] **Step 2: Add brief and confirmed-material state**

在 `writer-page.tsx` 增加：

```ts
const [draftMaterialIds, setDraftMaterialIds] = useState<number[]>([]);
const [selectedMaterialIds, setSelectedMaterialIds] = useState<number[]>([]);
const [idea, setIdea] = useState("");
const [briefBusy, setBriefBusy] = useState(false);
const [briefVisible, setBriefVisible] = useState(false);
const [briefSourceFingerprint, setBriefSourceFingerprint] = useState<string | null>(null);
const [briefCost, setBriefCost] = useState<WechatMpWritingBrief["cost_estimate"] | null>(null);
```

`prepareBrief(nextMaterialIds)` 使用明确传入的已确认素材 ID，成功时填充 `title/topic/reader/tone` 并保存来源指纹；失败时保留来源、显示可编辑简报字段和重试提示。

- [ ] **Step 3: Replace the first two workflow cards with one source-and-brief card**

将素材多选放在第一行，使用 `draftMaterialIds`。`使用选中素材（N）` 将 staged IDs 提交到 `selectedMaterialIds` 并自动调用 `prepareBrief`；无素材时使用 `idea` 和 `智能补全写作简报`。简报区域可编辑，形象选择保留现有可用性约束。

正文主按钮直接调用 `createArticle`，启用条件为：

```ts
hasWritingSource(selectedMaterialIds, idea) && isWritingBriefReady(title, topic)
```

`source_material` 传 `idea`，`material_ids` 传已确认素材。

- [ ] **Step 4: Shift the workflow from six stages to five**

使用 `WECHAT_WRITER_STEPS` 构造 Steps，并统一调整所有 `workflowStep`：创建后进入 1；编辑页进入 2；提示词完成进入 3；图片页进入 4；已有 prompt 文章直接进入 3。删除旧 `workflowStep === 1` 生成确认卡。

- [ ] **Step 5: Preserve stale briefs and no-material fallback**

当前来源指纹与 `briefSourceFingerprint` 不一致时显示 `写作来源已变化，建议重新整理`，不修改 title/topic/reader/tone。素材加载失败只禁用素材选择，不禁用 idea 和手动简报。

- [ ] **Step 6: Run front-end tests and build**

Run:

```bash
cd frontend && npm run test:wechat-writing-flow
cd frontend && npm run test:wechat-image-queue
cd frontend && npm run build
```

Expected: writing flow `5 passed`、image queue `7 passed`、TypeScript/Vite build exit 0。

- [ ] **Step 7: Run existing writer integration assertions**

Run:

```bash
PYTHONPATH=. /Users/yingdasun/eva-project/XHS_ALL_IN_ONE/.venv/bin/pytest -q \
  tests/backend/test_wechat_mp.py::test_wechat_mp_writer_shows_inline_generated_images_next_to_prompts \
  tests/backend/test_wechat_mp.py::test_wechat_mp_writer_cover_generation_is_independent_and_inline_previewed \
  tests/backend/test_wechat_mp.py::test_wechat_mp_writer_ignores_stale_prompt_generation_updates
```

Expected: `3 passed`。

- [ ] **Step 8: Commit Task 4**

```bash
git add frontend/src/pages/platforms/wechat-mp/writer-page.tsx frontend/tests/wechat-mp-writing-flow.test.ts
git commit -m "feat: streamline wechat material-first writing"
```

### Task 5: 全量定向验证与 Atlas 部署

**Files:**
- Verify only.

**Interfaces:**
- Consumes: Tasks 1-4 commits.
- Produces: clean worktree, pushed branch, Atlas healthy container serving the new production bundle.

- [ ] **Step 1: Run all new and directly coupled tests**

Run Task 1、Task 2、Task 4 的后端命令，以及两个前端 test scripts。任何失败都必须先定位并修复，不得以旧失败跳过新行为。

- [ ] **Step 2: Run production build and diff checks**

```bash
cd frontend && npm run build
git diff --check
git status --short
```

Expected: build exit 0、无 whitespace error、只包含预期提交后的 clean status。

- [ ] **Step 3: Push the feature branch**

```bash
git push origin codex/wechat-shotlist-atlas-integration
```

- [ ] **Step 4: Fast-forward and rebuild Atlas**

```bash
ssh Atlas 'cd /root/xhs-all-in-one && git fetch origin codex/wechat-shotlist-atlas-integration && git merge --ff-only FETCH_HEAD && docker compose up -d --build app'
```

- [ ] **Step 5: Verify production evidence**

确认 Atlas Git HEAD 等于本地 HEAD；`spider-xhs` 使用新镜像且为 `running healthy`；容器源码包含 `prepareWechatMpWritingBrief` 和 `使用选中素材`；生产 JS bundle 包含 `智能补全写作简报`。
